"""Independent client of World Monitor's hosted news API; no upstream server code.

    python -m app.worldmonitor_data status
    python -m app.worldmonitor_data poll --variant finance
    python -m app.worldmonitor_data monitor --interval 300

Load the process environment explicitly. Poll/monitor commands access the provider
and persist observations; status is local. The agent flag does not schedule a poller.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import time
from typing import Callable, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

import requests

from app.adapters.data.market_data_common import MarketDataError, iso, timestamp, utc_now

API_URL = "https://api.worldmonitor.app"
DIGEST_PATH = "/api/news/v1/list-feed-digest"
VARIANTS = ("finance", "full")
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 5000
DEFAULT_JOURNAL = Path(__file__).resolve().parent.parent / ".runtime/worldmonitor/news.sqlite3"


class NewsError(RuntimeError):
    """Safe for events/prompts: no provider bodies, headers or credentials."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Config:
    api_key: str = field(default="", repr=False)
    journal_path: Path = DEFAULT_JOURNAL
    variants: tuple[str, ...] = VARIANTS

    def __post_init__(self):
        if not isinstance(self.api_key, str) or any(ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise NewsError("configuration", "WORLDMONITOR_API_KEY has an invalid format.")
        if not isinstance(self.variants, tuple) or not self.variants or set(self.variants) - set(VARIANTS):
            raise NewsError("configuration", "TAU_WORLDMONITOR_VARIANTS must select finance and/or full.")
        object.__setattr__(self, "journal_path", Path(self.journal_path).expanduser().resolve())

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        return cls(env.get("WORLDMONITOR_API_KEY", "").strip(),
                   Path(env.get("TAU_WORLDMONITOR_JOURNAL", "").strip() or DEFAULT_JOURNAL),
                   tuple(dict.fromkeys(x.strip() for x in env.get("TAU_WORLDMONITOR_VARIANTS", "finance,full").split(","))))

    @property
    def namespace(self) -> str:
        # A different service credential must not read a previous account's cached feed.
        return hashlib.sha256((API_URL + "\0" + self.api_key).encode()).hexdigest()


def article_url(value) -> str:
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(c.isspace() or c in "<>\\" for c in value):
            raise ValueError()
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.port not in {None, 80, 443}:
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", url.hostname) or url.hostname.endswith((".local", ".internal", ".localhost")):
            raise ValueError()
        return urlunsplit((url.scheme, url.netloc, url.path, url.query, ""))
    except (TypeError, ValueError):
        raise NewsError("invalid_data", "News links must identify public HTTP(S) articles without credentials.") from None


def _text(value, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 10000:
        raise NewsError("invalid_data", "World Monitor returned an invalid text field.")
    value = html.unescape(re.sub(r"<[^>]*>", " ", value))
    value = " ".join("".join(c for c in value if c.isprintable() or c.isspace()).split())[:limit]
    if required and not value:
        raise NewsError("invalid_data", "World Monitor omitted a news title or publisher.")
    return value


def _epoch_ms(value) -> Optional[str]:
    if value in (None, 0, "0") and not isinstance(value, bool):
        return None
    try:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**53:
            raise ValueError()
        return iso(datetime.fromtimestamp(value // 1000, timezone.utc) + timedelta(milliseconds=value % 1000))
    except (ValueError, OSError, OverflowError):
        raise NewsError("invalid_data", "World Monitor returned an invalid publication timestamp.") from None


def _optional_time(value) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        return iso(timestamp(value))
    except MarketDataError:
        raise NewsError("invalid_data", "World Monitor returned an invalid digest timestamp.") from None


def _item(raw: dict, category: str, key: str) -> dict:
    try:
        title = _text(raw["title"], 500, required=True)
        publisher = _text(raw["source"], 160, required=True)
        url = article_url(raw["link"])
        snippet = _text(raw.get("snippet", ""), 400)
        published_at = _epoch_ms(raw.get("publishedAt"))
        alert = raw.get("isAlert", False)
        if type(alert) is not bool:
            raise ValueError()
        scores = {}
        for name in ("importanceScore", "credibilityScore", "corroborationCount"):
            if name in raw:
                value = raw[name]
                if type(value) is not int or not 0 <= value <= 2**31 - 1:
                    raise ValueError()
                scores[name] = value
        tickers = raw.get("tickers", [])
        if not isinstance(tickers, list) or len(tickers) > 8 or any(not isinstance(t, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", t) for t in tickers):
            raise ValueError()
        # Only typed provenance and short RSS excerpts enter the agent, never raw tool JSON.
        result = {"article_id": hashlib.sha256(url.encode()).hexdigest(), "url": url,
                  "publisher": publisher, "publisher_host": urlsplit(url).hostname,
                  "title": title, "excerpt": snippet, "published_at": published_at,
                  "categories": [category], "tickers": sorted(set(tickers)), "provider_alert": alert,
                  "provider_scores": scores, "scores_are_vendor_assessments": True}
        if key and key in json.dumps(result):
            raise ValueError()
        return result
    except (KeyError, TypeError, ValueError):
        raise NewsError("invalid_data", "World Monitor returned a malformed news item.") from None


def normalize_digest(raw: dict, variant: str, observed_at: datetime, *, api_key: str = "") -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("categories"), dict):
        raise NewsError("invalid_data", "World Monitor returned an invalid feed digest.")
    observed_at = timestamp(observed_at)
    generated = _optional_time(raw.get("generatedAt"))
    if generated and timestamp(generated) > observed_at + timedelta(seconds=60):
        raise NewsError("invalid_data", "The provider digest is dated in the future.")
    coverage_raw = raw.get("coverage", {})
    if not isinstance(coverage_raw, dict):
        raise NewsError("invalid_data", "World Monitor returned invalid coverage metadata.")
    state = coverage_raw.get("state", "unknown")
    if not isinstance(state, str) or state not in {"complete", "partial", "stale", "unavailable", "unknown"}:
        raise NewsError("invalid_data", "World Monitor returned an unknown coverage state.")
    coverage = {"state": state, "attempted_at": _optional_time(coverage_raw.get("attemptedAt"))}
    for name in ("itemsServed", "publisherCount", "feedTotal", "feedCompleted", "categoryTotal", "categoryCompleted", "staleAgeSeconds"):
        if name in coverage_raw:
            value = coverage_raw[name]
            if type(value) is not int or value < 0:
                raise NewsError("invalid_data", "World Monitor returned an invalid coverage count.")
            coverage[name] = value
    if "servedStale" in coverage_raw:
        if type(coverage_raw["servedStale"]) is not bool:
            raise NewsError("invalid_data", "World Monitor returned an invalid stale-content flag.")
        coverage["served_stale"] = coverage_raw["servedStale"]
    statuses = raw.get("feedStatuses", {})
    if not isinstance(statuses, dict) or len(statuses) > MAX_ITEMS:
        raise NewsError("invalid_data", "World Monitor returned invalid feed statuses.")
    feed_statuses = {}
    for name, status in statuses.items():
        if not isinstance(status, str) or status not in {"empty", "timeout", "all-undated", "partial-undated"}:
            raise NewsError("invalid_data", "World Monitor returned an unknown feed status.")
        label = _text(name, 160, required=True)
        if api_key and api_key in label:
            raise NewsError("invalid_data", "World Monitor returned an invalid feed label.")
        feed_statuses[label] = status
    items, invalid, undated, future, count = {}, 0, 0, 0, 0
    for category, bucket in raw["categories"].items():
        category = _text(category, 80, required=True)
        if api_key and api_key in category:
            raise NewsError("invalid_data", "World Monitor returned an invalid category label.")
        if not isinstance(bucket, dict) or not isinstance(bucket.get("items"), list):
            raise NewsError("invalid_data", "World Monitor returned an invalid news category.")
        for row in bucket["items"]:
            count += 1
            if count > MAX_ITEMS:
                raise NewsError("response_limit", "The feed digest exceeded 5,000 items; no partial digest was archived.")
            try:
                item = _item(row, category, api_key)
            except NewsError:
                invalid += 1
                continue
            if item["published_at"] and timestamp(item["published_at"]) > observed_at:
                future += 1
                continue
            if not item["published_at"]:
                undated += 1
            existing = items.get(item["article_id"])
            if existing:
                if {k: v for k, v in existing.items() if k != "categories"} != {k: v for k, v in item.items() if k != "categories"}:
                    invalid += 1
                    continue
                existing["categories"] = sorted(set(existing["categories"] + item["categories"]))
            else:
                items[item["article_id"]] = item
    return {"provider": "worldmonitor", "variant": variant, "language": "en", "observed_at": iso(observed_at),
            "generated_at": generated, "coverage": coverage, "feed_statuses": feed_statuses,
            "invalid_items": invalid, "undated_items": undated, "future_items_excluded": future,
            "items": list(items.values()), "vendor_first_seen_is_not_tau_observation": True}


class WorldMonitorClient:
    def __init__(self, config: Config, *, session=None, clock: Callable = utc_now, checkpoint: Callable = lambda: None):
        self.config, self.clock, self.checkpoint = config, clock, checkpoint
        self.session = session if session is not None else requests.Session()
        if session is None:
            self.session.trust_env = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

    def digest(self, variant: str) -> dict:
        if not self.config.api_key:
            raise NewsError("not_configured", "Set WORLDMONITOR_API_KEY in the agent server environment.")
        if variant not in self.config.variants:
            raise NewsError("variant_disabled", "The requested news variant is not enabled by the operator.")
        self.checkpoint()
        response = None
        started = time.monotonic()
        try:
            response = self.session.get(API_URL + DIGEST_PATH, params={"variant": variant, "lang": "en"},
                                        headers={"X-WorldMonitor-Key": self.config.api_key, "Accept": "application/json",
                                                 "User-Agent": "Tau-News/1.0 (+WorldMonitor-API-client)"},
                                        timeout=(3.05, 12), allow_redirects=False, stream=True)
            status = response.status_code
            if status != 200:
                code, message = {401: ("authentication", "World Monitor rejected the API key."),
                                 402: ("payment", "World Monitor requires a different account plan or credit."),
                                 403: ("entitlement", "World Monitor denied API access; check the subscription."),
                                 429: ("rate_limit", "World Monitor rate-limited this request.")}.get(
                                     status, ("provider_unavailable" if status >= 500 else "provider_request",
                                              "World Monitor rejected the news request (HTTP %d)." % status))
                raise NewsError(code, message + " No automatic retry or fallback was used.")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                self.checkpoint()
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES or time.monotonic() - started > 25:
                    raise NewsError("response_limit", "World Monitor exceeded the bounded response size or duration.")
                chunks.append(chunk)
            return normalize_digest(json.loads(b"".join(chunks)), variant, self.clock(), api_key=self.config.api_key)
        except requests.RequestException:
            raise NewsError("provider_unavailable", "Could not complete the World Monitor request; it was not retried.") from None
        except (TypeError, ValueError, UnicodeError):
            raise NewsError("invalid_data", "World Monitor returned invalid JSON news data.") from None
        finally:
            if response is not None:
                response.close()


def poll_once(config: Config, variant: str, *, client_factory=WorldMonitorClient, checkpoint=lambda: None) -> dict:
    from app.adapters.data.news_journal import NewsJournal
    with client_factory(config, checkpoint=checkpoint) as client:
        packet = client.digest(variant)
    checkpoint()
    return NewsJournal(config.journal_path, config.namespace).record(packet)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    poll = sub.add_parser("poll")
    poll.add_argument("--variant", choices=VARIANTS, default="finance")
    monitor = sub.add_parser("monitor")
    monitor.add_argument("--interval", type=int, default=300)
    monitor.add_argument("--cycles", type=int, default=0, help="0 runs until interrupted")
    args = parser.parse_args()
    try:
        config = Config.from_env()
        if args.command == "status":
            print(json.dumps({"provider": "worldmonitor", "key_present": bool(config.api_key),
                              "enabled": os.getenv("TAU_WORLDMONITOR_ENABLED") == "1",
                              "variants": config.variants, "journal": str(config.journal_path), "network_checked": False}))
            return 0
        if args.command == "poll":
            result = poll_once(config, args.variant)
            print(json.dumps(result, allow_nan=False))
            return 0
        if args.interval < 60 or args.cycles < 0:
            raise NewsError("configuration", "Monitor interval must be at least 60 seconds; cycles must be non-negative.")
        cycle = 0
        while True:
            cycle += 1
            for variant in config.variants:
                try:
                    print(json.dumps(poll_once(config, variant), allow_nan=False), flush=True)
                except NewsError as exc:
                    print(json.dumps({"provider": "worldmonitor", "variant": variant, "status": "unavailable", "code": exc.code, "message": str(exc)}), flush=True)
                    if exc.code in {"not_configured", "authentication", "payment", "entitlement"}:
                        return 2
            if args.cycles and cycle >= args.cycles:
                return 0
            time.sleep(args.interval)
    except NewsError as exc:
        print(json.dumps({"provider": "worldmonitor", "status": "unavailable", "code": exc.code, "message": str(exc)}))
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
