"""Local observation journal for news; model-supplied dates cannot backdate evidence.

Content revisions and reversions append versions. Each poll retains its membership
and provider coverage, so later removals/updates do not rewrite an earlier view.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from app.adapters.data.market_data_common import iso, timestamp
from app.worldmonitor_data import NewsError


def _micros(value: datetime) -> int:
    value = timestamp(value)
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


class NewsJournal:
    def __init__(self, path: Path, namespace: str):
        self.path, self.namespace = Path(path), namespace

    @contextmanager
    def _connection(self, *, write=False):
        conn = None
        try:
            if write:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if not self.path.exists():
                    fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(fd)
                conn = sqlite3.connect(str(self.path), timeout=3)
                os.chmod(self.path, 0o600)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS news_versions (
                        namespace TEXT NOT NULL, variant TEXT NOT NULL, article_id TEXT NOT NULL,
                        version INTEGER NOT NULL, content_hash TEXT NOT NULL, source_id TEXT PRIMARY KEY,
                        observed_us INTEGER NOT NULL, first_seen_us INTEGER NOT NULL,
                        published_us INTEGER, search_text TEXT NOT NULL, payload TEXT NOT NULL,
                        UNIQUE(namespace, variant, article_id, version));
                    CREATE INDEX IF NOT EXISTS news_article_versions
                        ON news_versions(namespace, variant, article_id, version DESC);
                    CREATE TABLE IF NOT EXISTS news_polls (
                        id INTEGER PRIMARY KEY, namespace TEXT NOT NULL, variant TEXT NOT NULL,
                        observed_us INTEGER NOT NULL, source_ids TEXT NOT NULL, metadata TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS news_poll_scope
                        ON news_polls(namespace, variant, observed_us DESC, id DESC);
                """)
                conn.execute("BEGIN IMMEDIATE")
            else:
                from urllib.parse import quote
                conn = sqlite3.connect("file:" + quote(str(self.path.resolve()), safe="/") + "?mode=ro", uri=True, timeout=3)
            conn.row_factory = sqlite3.Row
            yield conn
            if write:
                conn.commit()
        except (sqlite3.Error, OSError):
            if conn:
                conn.rollback()
            raise NewsError("journal_unavailable", "The local World Monitor observation journal could not be used.") from None
        finally:
            if conn:
                conn.close()

    def record(self, packet: dict) -> dict:
        observed_at = timestamp(packet["observed_at"])
        observed_us = _micros(observed_at)
        variant = packet["variant"]
        new, revisions, unchanged, ids = 0, 0, 0, []
        with self._connection(write=True) as conn:
            latest_poll = conn.execute("SELECT MAX(observed_us) FROM news_polls WHERE namespace=? AND variant=?",
                                       (self.namespace, variant)).fetchone()[0]
            if latest_poll is not None and observed_us < latest_poll:
                raise NewsError("clock_regression", "A news observation cannot be backdated before the latest local poll.")
            for item in packet["items"]:
                text = json.dumps(item, sort_keys=True, allow_nan=False, ensure_ascii=False)
                digest = hashlib.sha256(text.encode()).hexdigest()
                old = conn.execute("""SELECT version, content_hash, source_id, first_seen_us FROM news_versions
                    WHERE namespace=? AND variant=? AND article_id=? ORDER BY version DESC LIMIT 1""",
                                   (self.namespace, variant, item["article_id"])).fetchone()
                if old and old["content_hash"] == digest:
                    ids.append(old["source_id"])
                    unchanged += 1
                    continue
                version = old["version"] + 1 if old else 1
                first_seen = old["first_seen_us"] if old else observed_us
                identity = hashlib.sha256((self.namespace + variant + item["article_id"] + str(version) + digest).encode()).hexdigest()
                source_id = "worldmonitor:" + identity
                source = {**item, "source_id": source_id, "content_sha256": digest,
                          "first_observed_at": iso(datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=first_seen)),
                          "version_observed_at": iso(observed_at), "version": version,
                          "provider": "worldmonitor", "variant": variant}
                search = " ".join([item["title"], item["excerpt"], item["publisher"], *item["categories"], *item["tickers"]]).casefold()
                conn.execute("INSERT INTO news_versions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (self.namespace, variant, item["article_id"], version, digest, source_id,
                              observed_us, first_seen, _micros(timestamp(item["published_at"])) if item["published_at"] else None,
                              search, json.dumps(source, allow_nan=False, ensure_ascii=False)))
                ids.append(source_id)
                if old:
                    revisions += 1
                else:
                    new += 1
            metadata = {k: v for k, v in packet.items() if k != "items"}
            conn.execute("INSERT INTO news_polls (namespace,variant,observed_us,source_ids,metadata) VALUES (?,?,?,?,?)",
                         (self.namespace, variant, observed_us, json.dumps(ids), json.dumps(metadata, allow_nan=False)))
        return {**metadata, "status": "collected", "items_received": len(packet["items"]),
                "new_articles": new, "revisions": revisions, "unchanged_articles": unchanged}

    def read(self, variant: str, as_of: datetime, *, start: datetime, query: str = "", limit: int = 20) -> dict:
        base = {"provider": "worldmonitor", "kind": "headlines", "variant": variant,
                "as_of": iso(as_of), "window_start": iso(start), "sources": []}
        if not self.path.is_file():
            return {**base, "status": "unavailable", "code": "archive_empty",
                    "message": "No locally observed news is available. Current news was not substituted."}
        with self._connection() as conn:
            poll = conn.execute("""SELECT * FROM news_polls WHERE namespace=? AND variant=? AND observed_us<=?
                ORDER BY observed_us DESC, id DESC LIMIT 1""", (self.namespace, variant, _micros(as_of))).fetchone()
            if poll is None:
                return {**base, "status": "unavailable", "code": "historical_unavailable",
                        "message": "No local news observation exists at or before this cutoff. Publication dates alone are insufficient."}
            ids = json.loads(poll["source_ids"])
            needle = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = []
            for offset in range(0, len(ids), 900):
                chunk = ids[offset:offset + 900]
                sql = """SELECT published_us, payload FROM news_versions WHERE namespace=?
                    AND published_us>=? AND published_us<=? AND observed_us<=? AND search_text LIKE ? ESCAPE '\\'
                    AND source_id IN (%s)""" % ",".join("?" for _ in chunk)
                rows.extend(conn.execute(sql, (self.namespace, _micros(start), _micros(as_of), _micros(as_of),
                                                "%" + needle + "%", *chunk)).fetchall())
        sources = [json.loads(row["payload"]) for row in sorted(rows, key=lambda row: (row["published_us"], row["payload"]), reverse=True)]
        metadata = json.loads(poll["metadata"])
        generated = metadata["generated_at"]
        poll_age = max(0, (_micros(as_of) - poll["observed_us"]) / 1_000_000)
        content_age = (timestamp(as_of) - timestamp(generated)).total_seconds() if generated else None
        state = metadata["coverage"]["state"]
        stale = state == "stale" or metadata["coverage"].get("served_stale", False) or poll_age > 600 or (content_age is not None and content_age > 3600)
        status = ("unavailable" if state == "unavailable" else "stale" if stale else
                  "partial" if state != "complete" or metadata["invalid_items"] or metadata["future_items_excluded"] else
                  "available" if sources else "empty")
        if state == "unavailable":
            sources = []
        return {**base, **metadata, "status": status, "sources": sources[:limit],
                "matched_count": len(sources), "returned_count": min(limit, len(sources)),
                "truncated": len(sources) > limit, "sample_limit": limit,
                "poll_age_seconds": poll_age, "content_age_seconds": content_age,
                "publication_dates_do_not_establish_availability": True,
                "selection": "Latest poll observed by cutoff; dated items; literal case-insensitive substring filter."}
