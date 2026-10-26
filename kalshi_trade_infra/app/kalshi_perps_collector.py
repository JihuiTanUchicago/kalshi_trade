"""Opt-in native public Bitcoin perps collection, without any running service.

    python -m app.kalshi_perps_collector --start 2026-10-01 --end 2026-10-02

The default prints counts/provenance only. --persist explicitly stores append-only
batches using the normal app DB configuration; no schema migration is performed.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from app.kalshi_perps_data import (
    MAX_BATCH_SECONDS, MAX_HISTORY_SECONDS, SOURCE_SCHEMA, Config,
    KalshiPerpsDataClient, epoch, fingerprint, funding_coverage, iso_time,
    requested_range,
)
from app.adapters.data.market_data_common import MarketDataError


def collect(client: KalshiPerpsDataClient, start_ts: int, end_ts: int, *,
            ticker: str | None = None, include_observations: bool = True) -> dict:
    """Collect at most seven days. Funding failure remains explicit missing coverage."""
    client.config.require_enabled()
    start, end = requested_range(start_ts, end_ts)
    end = min(end, epoch(client.clock()) - 1)
    if end < start:
        raise MarketDataError("invalid_request", "Collect completed Bitcoin perpetual history only.")
    instrument = client.instrument(ticker)
    native_ticker = instrument["ticker"]
    candles, candle_status = client.candles(native_ticker, start, end)
    try:
        funding, funding_status = client.funding(native_ticker, start, end)
    except MarketDataError as exc:
        funding = []
        funding_status = funding_coverage([], start, end, retrieval_complete=False, error_code=exc.code)
    observations = []
    observation_status = {"status": "not_requested", "row_count": 0}
    if include_observations:
        try:
            observations, observation_status = client.observations(native_ticker)
        except MarketDataError as exc:
            observation_status = {"status": "failed", "row_count": 0, "error_codes": [exc.code]}
    # Current observations may refresh metadata. Reject a unit/version transition
    # across the HTTP requests instead of applying changed units to earlier bars.
    final_instrument = client.instrument(native_ticker)
    unit_fields = ("market_version", "contract_size", "underlying_multiplier", "tick_size")
    if any(final_instrument[key] != instrument[key] for key in unit_fields):
        raise MarketDataError("instrument_revision", "Bitcoin perpetual contract metadata changed during collection.")
    batch = {"source_schema": SOURCE_SCHEMA, "ticker": native_ticker,
             "environment": client.config.environment, "instrument": final_instrument,
             "request_start_ts": start, "request_end_ts": end,
             "candles": candles, "funding": funding, "observations": observations,
             "coverage": {"candles": candle_status, "funding": funding_status,
                          "observations": observation_status},
             "retrieved_at": iso_time(client.clock())}
    batch["data_fingerprint"] = fingerprint(batch)
    return batch


def collect_range(client: KalshiPerpsDataClient, start_ts: int, end_ts: int, *,
                  ticker: str | None = None, include_observations: bool = True):
    """Bound a manual backfill to 90 days and 13 sequential seven-day batches."""
    start, end = requested_range(start_ts, end_ts, max_seconds=MAX_HISTORY_SECONDS)
    end = min(end, epoch(client.clock()) - 1)
    if end < start:
        raise MarketDataError("invalid_request", "Collect completed Bitcoin perpetual history only.")
    native = client.instrument(ticker)["ticker"]
    while start <= end:
        batch_end = min(end, start + MAX_BATCH_SECONDS - 1)
        yield collect(client, start, batch_end, ticker=native,
                      include_observations=include_observations and batch_end == end)
        start = batch_end + 1


def summary(batch: dict, source_version: str | None = None) -> dict:
    """Safe operational evidence: no licensed prices, metadata bodies, or accounts."""
    return {"environment": batch["environment"], "source_schema": batch["source_schema"],
            "request_start_ts": batch["request_start_ts"], "request_end_ts": batch["request_end_ts"],
            "candle_count": len(batch["candles"]), "funding_count": len(batch["funding"]),
            "observation_count": len(batch["observations"]),
            "candles_status": batch["coverage"]["candles"]["status"],
            "funding_status": batch["coverage"]["funding"]["status"],
            "funding_retrieval_complete": batch["coverage"]["funding"]["retrieval_complete"],
            "metadata_fingerprint": batch["instrument"]["metadata_fingerprint"],
            "data_fingerprint": batch["data_fingerprint"],
            "retrieved_at": batch["retrieved_at"], "source_version": source_version}


def _date(value: str) -> int:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            if len(value) != 10:
                raise ValueError()
            dt = dt.replace(tzinfo=timezone.utc)
        return epoch(dt)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD (UTC) or an ISO timestamp with a timezone.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect native public Bitcoin perpetual research data.")
    parser.add_argument("--start", required=True, type=_date)
    parser.add_argument("--end", required=True, type=_date)
    parser.add_argument("--ticker", help="Optional native ticker; Bitcoin metadata is always verified.")
    parser.add_argument("--persist", action="store_true", help="Append data to already migrated research tables.")
    parser.add_argument("--no-observations", action="store_true")
    args = parser.parse_args(argv)
    connection: Any = None
    try:
        config = Config.from_env()
        config.require_enabled()
        requested_range(args.start, args.end, max_seconds=MAX_HISTORY_SECONDS)
        if args.persist:
            # Kept lazy: import-time/default-off operation never reads private DB env.
            from data_pipeline.common import get_db_conn
            connection = get_db_conn()
        with KalshiPerpsDataClient(config) as client:
            for batch in collect_range(client, args.start, args.end, ticker=args.ticker,
                                       include_observations=not args.no_observations):
                version = None
                if connection is not None:
                    from app.kalshi_perps_repository import store_batch
                    with connection.cursor() as cur:
                        version = store_batch(cur, batch)
                    connection.commit()
                print(json.dumps(summary(batch, version), sort_keys=True))
        return 0
    except MarketDataError as exc:
        print(json.dumps({"status": "unavailable", "error_code": exc.code, "message": str(exc)}, sort_keys=True))
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
