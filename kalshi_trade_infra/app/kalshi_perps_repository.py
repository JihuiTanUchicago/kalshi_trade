"""Append-only public Bitcoin perpetual collection batches and frozen sources.

No existing binary/spot history tables are read or changed. Frozen partitions
pin the exact committed batch manifest, as well as its high-water version. A
later commit with a lower allocated ID cannot enter an already frozen source.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.kalshi_perps_data import (
    BASE_URLS, MAX_BATCH_BYTES, MAX_CANDLES, MAX_FUNDING, MAX_HISTORY_SECONDS,
    SOURCE_SCHEMA, Config, candle_coverage, canonical_json, epoch, fingerprint,
    funding_coverage, normalize_instrument, requested_range, ticker_checked,
)
from app.market_data_common import MarketDataError

MAX_READ_BATCHES = 2000
MAX_READ_BYTES = 64 * 1024 * 1024
_VERSION = re.compile(r"kalshi-perps-v1:(production|demo):([1-9][0-9]{0,18})\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")

DDL = (
    """CREATE TABLE IF NOT EXISTS kalshi_perps_batches (
       id BIGINT AUTO_INCREMENT PRIMARY KEY,
       environment VARCHAR(10) NOT NULL,
       ticker VARCHAR(200) NOT NULL,
       start_ts BIGINT NOT NULL,
       end_ts BIGINT NOT NULL,
       retrieved_at DATETIME(6) NOT NULL,
       data_fingerprint CHAR(64) NOT NULL,
       candle_count INT NOT NULL,
       funding_count INT NOT NULL,
       observation_count INT NOT NULL,
       observation_start_ts BIGINT NULL,
       observation_end_ts BIGINT NULL,
       funding_status VARCHAR(16) NOT NULL,
       payload_json JSON NOT NULL,
       UNIQUE KEY uq_perps_batch_fingerprint (environment, ticker, data_fingerprint),
       INDEX idx_perps_history (environment, ticker, id),
       INDEX idx_perps_ranges (environment, start_ts, end_ts)
       ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS kalshi_perps_partition_sources (
       partition_id BIGINT PRIMARY KEY,
       source_version VARCHAR(80) NOT NULL,
       data_fingerprint CHAR(64) NOT NULL,
       source_manifest_json JSON NOT NULL
       ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
)


def _version(environment: str, batch_id: int) -> str:
    return "kalshi-perps-v1:%s:%d" % (environment, batch_id)


def _parse_version(value: Any) -> tuple[str, int]:
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise MarketDataError("invalid_request", "Invalid frozen Kalshi perpetual source version.")
    return match.group(1), int(match.group(2))


def _manifest(value: Any, source_version: str) -> list[dict]:
    """Canonical committed IDs and hashes, bounded independently of SQL results."""
    _, maximum = _parse_version(source_version)
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_READ_BATCHES:
        raise MarketDataError("invalid_request", "A bounded frozen perpetual batch manifest is required.")
    out = []
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {"id", "data_fingerprint", "retrieved_at"}:
            raise MarketDataError("invalid_request", "Invalid frozen perpetual batch manifest.")
        batch_id, digest = item.get("id"), item.get("data_fingerprint")
        if (isinstance(batch_id, bool) or not isinstance(batch_id, int) or not 1 <= batch_id <= maximum
                or batch_id in seen or not isinstance(digest, str) or _HASH.fullmatch(digest) is None):
            raise MarketDataError("invalid_request", "Invalid frozen perpetual batch identity or fingerprint.")
        seen.add(batch_id)
        out.append({"id": batch_id, "data_fingerprint": digest})
    if maximum not in seen:
        raise MarketDataError("invalid_request", "The frozen perpetual manifest must include its version anchor.")
    return sorted(out, key=lambda item: item["id"])


def _market_config(market: Any) -> Config:
    if (getattr(market, "kind", None) != "perpetual"
            or getattr(market, "underlying", None) != "BTC-USD"):
        raise MarketDataError("invalid_request", "Only the Bitcoin perpetual research market is supported.")
    config = Config.from_env()
    config.require_enabled()
    return config


def _decode(row: dict) -> dict:
    value = row.get("payload_json")
    encoded = value if isinstance(value, (str, bytes)) else canonical_json(value)
    if len(encoded) > MAX_BATCH_BYTES:
        raise MarketDataError("invalid_data", "Stored perpetual batch exceeds its size bound.")
    try:
        batch = json.loads(encoded)
        if not isinstance(batch, dict) or batch.get("data_fingerprint") != row.get("data_fingerprint"):
            raise ValueError()
        content = {key: item for key, item in batch.items() if key != "data_fingerprint"}
        if fingerprint(content) != batch["data_fingerprint"]:
            raise ValueError()
        if batch.get("environment") != row.get("environment") or batch.get("ticker") != row.get("ticker"):
            raise ValueError()
        return batch
    except (ValueError, TypeError, UnicodeDecodeError):
        raise MarketDataError("invalid_data", "Stored perpetual batch integrity check failed.") from None


def _validate_batch(batch: Any) -> tuple[dict, str]:
    if not isinstance(batch, dict):
        raise MarketDataError("invalid_data", "A normalized perpetual batch is required.")
    try:
        if set(batch) - {"environment", "source_schema", "ticker", "request_start_ts", "request_end_ts",
                         "retrieved_at", "instrument", "candles", "funding", "observations",
                         "coverage", "data_fingerprint"}:
            raise ValueError()
        env = batch["environment"]
        if env not in BASE_URLS or batch["source_schema"] != SOURCE_SCHEMA:
            raise ValueError()
        ticker = ticker_checked(batch["ticker"])
        start, end = requested_range(batch["request_start_ts"], batch["request_end_ts"])
        retrieved = epoch(batch["retrieved_at"])
        instrument = batch["instrument"]
        expected = normalize_instrument(instrument, env, instrument["retrieved_at"])
        if (instrument != expected or epoch(instrument["retrieved_at"]) > retrieved or instrument["ticker"] != ticker
                or batch["environment"] != instrument["environment"]):
            raise ValueError()
        for name, limit in (("candles", MAX_CANDLES), ("funding", MAX_FUNDING), ("observations", 100)):
            rows = batch[name]
            if not isinstance(rows, list) or len(rows) > limit:
                raise ValueError()
            for row in rows:
                if not isinstance(row, dict) or epoch(row["retrieved_at"]) > retrieved:
                    raise ValueError()
                ts = row["ts"]
                if name != "observations" and not start <= epoch(ts) <= end:
                    raise ValueError()
                if name == "observations" and row["available_at"] < ts:
                    raise ValueError()
        if not isinstance(batch["coverage"], dict):
            raise ValueError()
        data = {key: value for key, value in batch.items() if key != "data_fingerprint"}
        result = {**data, "data_fingerprint": fingerprint(data)}
        if batch.get("data_fingerprint", result["data_fingerprint"]) != result["data_fingerprint"]:
            raise ValueError()
        encoded = canonical_json(result)
        if len(encoded.encode("utf-8")) > MAX_BATCH_BYTES:
            raise MarketDataError("batch_too_large", "Normalized perpetual batch exceeds the bounded size limit.")
        return result, encoded
    except (KeyError, ValueError, TypeError):
        raise MarketDataError("invalid_data", "The normalized Bitcoin perpetual batch is invalid.") from None


def store_batch(cur: Any, batch: dict) -> str:
    """Append validated data; the caller owns transaction/commit boundaries."""
    normalized, encoded = _validate_batch(batch)
    config = Config.from_env()
    config.require_enabled()
    if config.environment != normalized["environment"]:
        raise MarketDataError("invalid_request", "Perpetual production and demo collections cannot share a write context.")
    if config.ticker is not None and config.ticker != normalized["ticker"]:
        raise MarketDataError("invalid_request", "Perpetual batch does not match the configured native ticker.")
    cur.execute(
        """INSERT IGNORE INTO kalshi_perps_batches
           (environment,ticker,start_ts,end_ts,retrieved_at,data_fingerprint,
            candle_count,funding_count,observation_count,observation_start_ts,observation_end_ts,
            funding_status,payload_json)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (normalized["environment"], normalized["ticker"], normalized["request_start_ts"],
         normalized["request_end_ts"], datetime.fromtimestamp(epoch(normalized["retrieved_at"]), timezone.utc).replace(tzinfo=None),
         normalized["data_fingerprint"], len(normalized["candles"]), len(normalized["funding"]),
         len(normalized["observations"]),
         min((int(row["ts"]) for row in normalized["observations"]), default=None),
         max((epoch(row["available_at"]) for row in normalized["observations"]), default=None),
         normalized["coverage"]["funding"]["status"], encoded),
    )
    cur.execute("SELECT id FROM kalshi_perps_batches WHERE environment=%s AND ticker=%s AND data_fingerprint=%s",
                (normalized["environment"], normalized["ticker"], normalized["data_fingerprint"]))
    row = cur.fetchone()
    if row is None:
        raise MarketDataError("storage_error", "Perpetual batch was not persisted.")
    return _version(normalized["environment"], int(row["id"]))


def _latest(cur: Any, config: Config, source_version: str | None = None) -> dict | None:
    if source_version is not None:
        environment, batch_id = _parse_version(source_version)
        if environment != config.environment:
            raise MarketDataError("invalid_request", "Frozen perpetual source belongs to a different environment.")
        cur.execute("SELECT * FROM kalshi_perps_batches WHERE environment=%s AND id=%s",
                    (environment, batch_id))
    elif config.ticker is not None:
        cur.execute("SELECT * FROM kalshi_perps_batches WHERE environment=%s AND ticker=%s ORDER BY id DESC LIMIT 1",
                    (config.environment, config.ticker))
    else:
        cur.execute("SELECT * FROM kalshi_perps_batches WHERE environment=%s ORDER BY id DESC LIMIT 1",
                    (config.environment,))
    row = cur.fetchone()
    if row is not None and config.ticker is not None and row["ticker"] != config.ticker:
        raise MarketDataError("invalid_request", "Frozen perpetual source belongs to a different ticker.")
    if row is None and source_version is not None:
        raise MarketDataError("not_available", "The frozen perpetual source version is unavailable.")
    return row


def _covered(intervals: list[tuple[int, int]], start: int, end: int) -> bool:
    next_ts = start
    for left, right in sorted(intervals):
        if right < next_ts:
            continue
        if left > next_ts:
            return False
        next_ts = max(next_ts, right + 1)
        if next_ts > end:
            return True
    return next_ts > end


def load_history(cur: Any, market: Any, since_ts: int, end_ts: int | None = None, *,
                 source_version: str | None = None, source_manifest: list[dict] | None = None) -> dict:
    """Resolve native ticker from immutable storage; Market.series is only an alias."""
    config = _market_config(market)
    manifest = _manifest(source_manifest, source_version) if source_manifest is not None else None
    start = epoch(since_ts)
    requested_end = epoch(end_ts) if end_ts is not None else None
    latest = _latest(cur, config, source_version)
    if latest is None:
        raise MarketDataError("not_available", "No native Bitcoin perpetual collection is available in this environment.")
    latest_batch = _decode(latest)
    end = requested_end if requested_end is not None else int(latest["end_ts"])
    requested_range(start, end, max_seconds=MAX_HISTORY_SECONDS)
    ticker = ticker_checked(latest["ticker"])
    max_id = int(latest["id"])
    if manifest is not None:
        ids = [item["id"] for item in manifest]
        placeholders = ",".join(["%s"] * len(ids))
        cur.execute("SELECT * FROM kalshi_perps_batches WHERE environment=%s AND ticker=%s "
                    "AND id IN (" + placeholders + ") ORDER BY id ASC",
                    (config.environment, ticker, *ids))
    else:
        cur.execute(
            """SELECT * FROM kalshi_perps_batches WHERE environment=%s AND ticker=%s
               AND id<=%s AND ((end_ts>=%s AND start_ts<=%s)
                 OR (observation_count>0 AND observation_start_ts<=%s)) ORDER BY id ASC LIMIT %s""",
            (config.environment, ticker, max_id, start, end, end, MAX_READ_BATCHES + 1),
        )
    stored = cur.fetchall()
    if manifest is not None:
        actual = sorted([{"id": int(row["id"]), "data_fingerprint": row["data_fingerprint"]}
                         for row in stored], key=lambda item: item["id"])
        if actual != manifest:
            raise MarketDataError("source_conflict", "Frozen perpetual source batches are missing or have changed.")
    if len(stored) > MAX_READ_BATCHES:
        raise MarketDataError("history_too_large", "Perpetual history exceeds the batch read bound; no data was truncated.")
    if sum(len(row["payload_json"]) if isinstance(row.get("payload_json"), (str, bytes))
           else len(canonical_json(row.get("payload_json"))) for row in stored) > MAX_READ_BYTES:
        raise MarketDataError("history_too_large", "Perpetual history exceeds the storage read bound; no data was truncated.")
    candles: dict[int, dict] = {}
    funding: dict[int, dict] = {}
    observations: dict[tuple, dict] = {}
    funding_intervals = []
    funding_failures = []
    candle_intervals = []
    source_batches = []
    unit_fields = ("contract_size", "underlying_multiplier", "contract_multiplier", "price_basis",
                   "price_unit", "market_version", "quantity_step", "funding_rate_unit")
    instrument = latest_batch["instrument"]
    for stored_row in stored:
        batch = _decode(stored_row)
        if any(batch["instrument"].get(key) != instrument.get(key) for key in unit_fields):
            raise MarketDataError("instrument_revision", "Perpetual unit metadata changed inside this history; use a compatible source interval.")
        source_batches.append({"id": int(stored_row["id"]), "data_fingerprint": batch["data_fingerprint"],
                               "retrieved_at": batch["retrieved_at"]})
        # A later successful response supersedes values AND omissions in its
        # range. Failed retrievals cannot erase previously acquired evidence.
        for name, target in (("candles", candles), ("funding", funding)):
            status = batch["coverage"].get(name, {})
            success = (status.get("retrieval_complete") is True if name == "funding"
                       else status.get("status") in {"complete", "partial", "empty"})
            if success:
                left, right = epoch(status["start_ts"]), epoch(status["end_ts"])
                for ts in list(target):
                    if left <= ts <= right:
                        del target[ts]
        for name, target in (("candles", candles), ("funding", funding)):
            for row in batch[name]:
                ts = epoch(row["ts"])
                if start <= ts <= end:
                    target[ts] = row
        for row in batch["observations"]:
            # Historical source timestamps alone do not make current observations causal.
            if row["ts"] <= end and row["available_at"] <= end:
                observations[(row["kind"], row["ts"], row["available_at"])] = row
        fc = batch["coverage"].get("funding", {})
        if fc.get("retrieval_complete") is True:
            funding_intervals.append((epoch(fc["start_ts"]), epoch(fc["end_ts"])))
        elif fc.get("error_code") and epoch(fc["start_ts"]) <= end and epoch(fc["end_ts"]) >= start:
            funding_failures.append({"start_ts": epoch(fc["start_ts"]), "end_ts": epoch(fc["end_ts"]),
                                     "error_code": fc["error_code"], "batch_id": int(stored_row["id"])})
        cc = batch["coverage"].get("candles", {})
        if cc.get("status") in {"complete", "partial", "empty"}:
            candle_intervals.append((epoch(cc["start_ts"]), epoch(cc["end_ts"])))
    candle_rows = [candles[ts] for ts in sorted(candles)]
    funding_rows = [funding[ts] for ts in sorted(funding)]
    candle_status = candle_coverage(candle_rows, start, end)
    candle_status["retrieval_complete"] = _covered(candle_intervals, start, end)
    candle_status["complete"] = candle_status["complete"] and candle_status["retrieval_complete"]
    funding_retrieval_complete = _covered(funding_intervals, start, end)
    funding_status = funding_coverage(funding_rows, start, end,
                                     retrieval_complete=funding_retrieval_complete,
                                     error_code=funding_failures[-1]["error_code"] if funding_failures and not funding_retrieval_complete else None)
    funding_status["retrieval_failures"] = funding_failures
    coverage = {
        "candles": candle_status,
        "funding": funding_status,
        "observations": {"row_count": len(observations), "status": "observed" if observations else "empty",
                         "availability_policy": "available_at <= decision timestamp"},
        "source_batches": source_batches, "start_ts": start, "end_ts": end,
    }
    result = {"ticker": ticker, "environment": config.environment, "instrument": instrument,
              "candles": candle_rows, "funding": funding_rows,
              "observations": sorted(observations.values(), key=lambda row: (row["available_at"], row["ts"], row["kind"])),
              "coverage": coverage, "source_schema": SOURCE_SCHEMA,
              "source_version": _version(config.environment, max_id)}
    result["data_fingerprint"] = fingerprint(result)
    return result


def ready(cur: Any, market: Any) -> bool:
    try:
        config = _market_config(market)
    except MarketDataError as exc:
        if exc.code == "disabled":
            return False
        raise
    bounds = history_bounds(cur, market)
    return bounds is not None and bounds["count"] >= 2


def history_bounds(cur: Any, market: Any) -> dict | None:
    config = _market_config(market)
    row = _latest(cur, config)
    if row is None:
        return None
    cur.execute("""SELECT MIN(start_ts) AS min_ts, MAX(end_ts) AS max_ts FROM kalshi_perps_batches
                   WHERE environment=%s AND ticker=%s AND id<=%s AND candle_count>0""",
                (config.environment, row["ticker"], int(row["id"])))
    bounds = cur.fetchone()
    if not bounds or bounds.get("min_ts") is None:
        return None
    start, end = int(bounds["min_ts"]), int(bounds["max_ts"])
    start = max(start, end - MAX_HISTORY_SECONDS)
    history = load_history(cur, market, start, end, source_version=_version(config.environment, int(row["id"])))
    points = [candle["ts"] for candle in history["candles"]]
    if not points:
        return None
    return {"min_ts": min(points), "max_ts": max(points),
            "count": len(points), "ticker": row["ticker"], "environment": config.environment,
            "source_version": history["source_version"], "data_fingerprint": history["data_fingerprint"],
            "coverage": history["coverage"]}


def candle_points(cur: Any, market: Any, since: datetime | int, *,
                  source_version: str | None = None) -> list[int]:
    value = since.replace(tzinfo=timezone.utc) if isinstance(since, datetime) and since.tzinfo is None else since
    history = load_history(cur, market, epoch(value), source_version=source_version)
    return [int(row["ts"]) for row in history["candles"]]


def bind_partition_source(cur: Any, partition_id: int, source_version: str, data_fingerprint: str,
                          source_manifest: list[dict]) -> None:
    """Bind once; a duplicate ID cannot silently replace a frozen holdout source."""
    if isinstance(partition_id, bool) or not isinstance(partition_id, int) or partition_id < 1:
        raise MarketDataError("invalid_request", "A valid research partition ID is required.")
    manifest = _manifest(source_manifest, source_version)
    if not isinstance(data_fingerprint, str) or _HASH.fullmatch(data_fingerprint) is None:
        raise MarketDataError("invalid_request", "A complete perpetual data fingerprint is required.")
    cur.execute("""INSERT IGNORE INTO kalshi_perps_partition_sources
                   (partition_id,source_version,data_fingerprint,source_manifest_json) VALUES (%s,%s,%s,%s)""",
                (partition_id, source_version, data_fingerprint, canonical_json(manifest)))
    saved = partition_source(cur, partition_id)
    if saved != {"source_version": source_version, "data_fingerprint": data_fingerprint,
                 "source_manifest": manifest}:
        raise MarketDataError("source_conflict", "This research partition is already bound to a different perpetual source.")


def partition_source(cur: Any, partition_id: int) -> dict | None:
    cur.execute("SELECT source_version,data_fingerprint,source_manifest_json "
                "FROM kalshi_perps_partition_sources WHERE partition_id=%s",
                (partition_id,))
    row = cur.fetchone()
    if row is None:
        return None
    try:
        raw = row["source_manifest_json"]
        manifest = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        manifest = _manifest(manifest, row["source_version"])
    except (KeyError, TypeError, ValueError):
        raise MarketDataError("source_conflict", "The frozen perpetual source manifest is invalid.") from None
    return {"source_version": row["source_version"], "data_fingerprint": row["data_fingerprint"],
            "source_manifest": manifest}


@contextmanager
def partition_lock(cur: Any, market: Any):
    """Serialize initial perps partition creation without changing trading locks."""
    config = _market_config(market)
    name = "tau:kalshi_perps:partition:" + config.environment + ":btc_perp"
    cur.execute("SELECT GET_LOCK(%s,5) AS acquired", (name,))
    row = cur.fetchone()
    if row is None or row.get("acquired") != 1:
        raise ValueError("Bitcoin perpetual partition initialization is busy; retry shortly.")
    try:
        yield
    finally:
        cur.execute("SELECT RELEASE_LOCK(%s) AS released", (name,))
