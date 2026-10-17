"""Read the existing BTC collectors without opening a research store or broker."""
from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from pathlib import Path
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import json
import os
import time

from .common import GateError, timestamp, utcnow
from .configuration import load_environment


POLL_SECONDS = 20
MAX_AGE_SECONDS = 60
WINDOW_SECONDS = 180
HTTP_TIMEOUT_SECONDS = 10
PAGE_SIZE = 5000
MAX_ROWS = 10000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
FEEDS = {
    "kalshi": ("forward_quotes", "id snapshot_time_utc market_ticker event_ticker yes_bid_dollars "
               "yes_ask_dollars yes_bid_size_fp yes_ask_size_fp volume_fp open_interest_fp "
               "no_bid_dollars no_ask_dollars status raw_json"),
    "coinbase": ("coinbase_ticks", "id snapshot_time_utc product_id price bid ask volume_24h status raw_json"),
}


class _NoRedirect(HTTPRedirectHandler):
    # Basic credentials must never be forwarded to another origin.
    def redirect_request(self, *args, **kwargs):
        return None


def _date(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # The infrastructure's DATETIME columns are explicitly UTC, without an offset.
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def _number(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Invalid market number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Nonfinite market number")
    return result


class MarketDataReader:
    def __init__(self, config: dict, env_file: str | Path | None = None):
        if not isinstance(config, dict) or set(config) != {"base_url"} or not isinstance(config["base_url"], str):
            raise GateError("Market-data configuration requires only a base_url")
        url = urlsplit(config["base_url"])
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (url.scheme not in {"http", "https"} or not url.hostname or
                url.scheme == "http" and not local or url.username is not None or
                url.password is not None or url.query or url.fragment):
            raise GateError("Use an HTTPS service URL without credentials, query or fragment; HTTP is local-only")
        self.base_url = config["base_url"].rstrip("/")
        if env_file is not None:
            load_environment(env_file, ["DASHBOARD_USER", "DASHBOARD_PASSWORD"])
        user = os.environ.get("DASHBOARD_USER", "")
        password = os.environ.get("DASHBOARD_PASSWORD", "")
        if not user or not password or ":" in user:
            raise GateError("Configure DASHBOARD_USER and DASHBOARD_PASSWORD locally; values are omitted")
        self._authorization = "Basic " + b64encode(f"{user}:{password}".encode()).decode()
        self._opener = build_opener(_NoRedirect())

    def _rows(self, source: str, start: datetime, end: datetime) -> list[dict]:
        table, fields = FEEDS[source]
        rows = []
        offset = 0
        while True:
            params = {"name": table, "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                      "end": end.strftime("%Y-%m-%d %H:%M:%S"), "offset": offset,
                      "limit": PAGE_SIZE, "columns": ",".join(fields.split())}
            request = Request(self.base_url + "/api/table?" + urlencode(params),
                              headers={"Authorization": self._authorization, "Accept": "application/json"},
                              method="GET")
            try:
                with self._opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
            except HTTPError as exc:
                exc.close()
                if exc.code < 500 and exc.code != 429:
                    raise GateError(f"Market-data HTTP {exc.code}; verify the service URL and dashboard access") from None
                raise
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("Oversized market-data response")
            payload = json.loads(body)
            if (not isinstance(payload, dict) or payload.get("ok") is False or
                    not isinstance(payload.get("rows"), list) or type(payload.get("done")) is not bool):
                raise ValueError("Invalid market-data page")
            batch = payload["rows"]
            if len(batch) > PAGE_SIZE or len(rows) + len(batch) > MAX_ROWS:
                raise ValueError("Market-data window exceeds the read limit")
            rows.extend(batch)
            if payload["done"]:
                return rows
            next_offset = payload.get("next_offset")
            if not batch or type(next_offset) is not int or next_offset != offset + len(batch):
                raise ValueError("Market-data pagination made no progress")
            offset = next_offset

    def _observation(self, source: str, row: dict, received: datetime) -> dict:
        if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0:
            raise ValueError("Invalid source row identity")
        observed = _date(row["snapshot_time_utc"])
        raw = row.get("raw_json")
        raw = json.loads(raw) if isinstance(raw, str) else {} if raw is None else raw
        if not isinstance(raw, dict):
            raise ValueError("Invalid source timestamp document")
        source_at = None
        if source == "kalshi":
            if raw.get("ts_ms") is not None:
                source_at = datetime.fromtimestamp(float(_number(raw["ts_ms"]) / 1000), timezone.utc)
            elif raw.get("ts") is not None:
                source_at = datetime.fromtimestamp(float(_number(raw["ts"])), timezone.utc)
        if source_at is None and raw.get("time") is not None:
            try:
                source_at = timestamp(raw["time"])
            except GateError:
                raise ValueError("Invalid source timestamp") from None
        if observed > received or source_at is not None and source_at > received:
            raise ValueError("Source timestamp is in the future")
        fields = FEEDS[source][1].split()
        result = {name: row.get(name) for name in fields if name != "raw_json"}
        result.update({"kind": "market_data", "source": source, "update_id": f"{source}:{row['id']}",
                       "received_at": received.isoformat()})
        if source == "kalshi":
            result["source_time_utc"] = source_at.isoformat() if source_at else None
            price_fields = ("yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars")
            size_fields = ("yes_bid_size_fp", "yes_ask_size_fp", "volume_fp", "open_interest_fp")
            required = ("yes_bid_dollars", "yes_ask_dollars")
            active = row.get("status") in {"active", "open"} and row.get("market_ticker") != "N/A"
        else:
            result["last_trade_time_utc"] = source_at.isoformat() if source_at else None
            price_fields = ("price", "bid", "ask")
            size_fields = ("volume_24h",)
            required = price_fields
            active = row.get("status") == "ok"
        for name in price_fields + size_fields:
            if row.get(name) is None:
                continue
            value = _number(row[name])
            if value < 0 or name in price_fields and (
                    source == "kalshi" and value > 1 or source == "coinbase" and value <= 0):
                raise ValueError("Market value is outside its valid range")
        pairs = (("yes_bid_dollars", "yes_ask_dollars"), ("no_bid_dollars", "no_ask_dollars")) if source == "kalshi" else (("bid", "ask"),)
        for bid, ask in pairs:
            if row.get(bid) is not None and row.get(ask) is not None and _number(row[bid]) > _number(row[ask]):
                raise ValueError("Crossed market quote")
        collection_age = (received - observed).total_seconds()
        source_age = (received - source_at).total_seconds() if source_at is not None else None
        status, reason = "ok", None
        if not active:
            status, reason = "unavailable", "collector_status"
        elif any(row.get(name) is None for name in required):
            status, reason = "unavailable", "missing_quote"
        elif collection_age > MAX_AGE_SECONDS:
            status, reason = "stale", "collection_age"
        elif source == "kalshi" and source_age is not None and source_age > MAX_AGE_SECONDS:
            status, reason = "stale", "source_age"
        result["health"] = {"status": status, "reason": reason, "collection_age_seconds": collection_age,
                            "source_age_seconds": source_age, "freshness_basis":
                            "collection_and_source" if source == "kalshi" and source_at else "collection"}
        return result

    def _poll(self) -> dict:
        end = timestamp(utcnow())
        start = end - timedelta(seconds=WINDOW_SECONDS)
        feeds = {}
        for source in FEEDS:
            try:
                rows = self._rows(source, start, end)
                received = timestamp(utcnow())
                updates = []
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError("Invalid market-data row")
                    instrument = row.get("market_ticker") if source == "kalshi" else row.get("product_id")
                    if not isinstance(instrument, str):
                        raise ValueError("Missing market identity")
                    if (source == "kalshi" and instrument != "N/A" and not instrument.startswith("KXBTC15M-") or
                            source == "coinbase" and instrument != "BTC-USD"):
                        continue
                    observation = self._observation(source, row, received)
                    if start <= _date(observation["snapshot_time_utc"]) <= end:
                        updates.append(observation)
                updates.sort(key=lambda row: (_date(row["snapshot_time_utc"]), row["id"]))
                health = updates[-1]["health"] if updates else {"status": "unavailable", "reason": "no_rows"}
            except HTTPError as exc:
                updates, health = [], {"status": "unavailable", "reason": f"http_{exc.code}"}
            except (URLError, HTTPException, OSError):
                updates, health = [], {"status": "unavailable", "reason": "transport_error"}
            except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation, OverflowError):
                updates, health = [], {"status": "unavailable", "reason": "invalid_data"}
            feeds[source] = {"updates": updates, "health": health}
        return {"received_at": utcnow(), "feeds": feeds}

    def snapshot(self) -> dict:
        """Return the newest collected batch per feed, retaining explicit health."""
        result = self._poll()
        for feed in result["feeds"].values():
            rows = feed["updates"]
            if rows:
                latest = _date(rows[-1]["snapshot_time_utc"])
                by_instrument = {}
                for row in rows:
                    if _date(row["snapshot_time_utc"]) == latest:
                        by_instrument[row.get("market_ticker", row.get("product_id"))] = row
                feed["updates"] = list(by_instrument.values())
        return result

    def iter_updates(self, iterations: int = 0) -> Iterator[dict]:
        """Yield a three-minute catch-up followed by new rows and health transitions."""
        if type(iterations) is not int or iterations < 0:
            raise GateError("Market-data iterations must be a nonnegative integer")
        seen = {}
        previous_health = {}
        count = 0
        # shortcut: a three-minute overlap cannot replay longer outages; use a durable cursor for archival replay.
        while iterations == 0 or count < iterations:
            started = time.monotonic()
            result = self._poll()
            cutoff = timestamp(result["received_at"]) - timedelta(seconds=WINDOW_SECONDS)
            seen = {identity: observed for identity, observed in seen.items() if observed >= cutoff}
            rows = [row for feed in result["feeds"].values() for row in feed["updates"]]
            rows.sort(key=lambda row: (_date(row["snapshot_time_utc"]), row["id"], row["source"]))
            for row in rows:
                identity = row["update_id"]
                if identity not in seen:
                    seen[identity] = _date(row["snapshot_time_utc"])
                    yield row
            for source, feed in result["feeds"].items():
                health = feed["health"]
                signature = (health["status"], health["reason"])
                if previous_health.get(source) != signature:
                    previous_health[source] = signature
                    yield {"kind": "feed_health", "source": source, "received_at": result["received_at"],
                           "health": health}
            count += 1
            if iterations == 0 or count < iterations:
                time.sleep(max(0, POLL_SECONDS - (time.monotonic() - started)))
