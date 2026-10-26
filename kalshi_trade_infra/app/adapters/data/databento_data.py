"""Bounded Databento historical OHLCV context; no live feed or trading endpoints.

    python -m app.adapters.data.databento_data status
    python -m app.adapters.data.databento_data estimate SPY --dataset EQUS.MINI --start 2026-10-01 --end 2026-10-16
    python -m app.adapters.data.databento_data bars ESZ6 --dataset GLBX.MDP3 --start 2026-10-01 --end 2026-10-16

The process must explicitly load its environment. Downloads first check a cost
estimate against a local budget (zero by default). This is not a vendor billing cap.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, Mapping, Optional, Sequence

import requests

from app.adapters.data.market_data_common import MarketDataError, iso, timestamp, utc_now

DATA_URL = "https://hist.databento.com/v0"
TIMEFRAMES = {"1Min": ("ohlcv-1m", 60, 33), "1Hour": ("ohlcv-1h", 3600, 34), "1Day": ("ohlcv-1d", 86400, 35)}
MAX_BARS = 10_000
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_REQUEST_SECONDS = 25


def dataset_checked(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{3,8}\.[A-Z0-9]{2,16}", value):
        raise MarketDataError("invalid_request", "Use an explicit Databento dataset code, such as EQUS.MINI or GLBX.MDP3.")
    return value


def symbols_checked(symbols: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(symbols, (list, tuple)) or not 1 <= len(symbols) <= 8:
        raise MarketDataError("invalid_request", "Request one to eight explicit raw stock/ETF or futures contract symbols.")
    result = []
    for symbol in symbols:
        # Preserve exchange spelling/case; never expand parents, continuous contracts or wildcards.
        if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,30}", symbol)
                or symbol != symbol.strip() or symbol.upper() == "ALL_SYMBOLS"
                or re.search(r"\.(?:FUT|OPT|[cvn]\.\d+)$", symbol, re.IGNORECASE)):
            raise MarketDataError("invalid_request", "Use explicit raw symbols; all-symbol, parent and continuous requests are unsupported.")
        if symbol not in result:
            result.append(symbol)
    return tuple(result)


def _money(value) -> Decimal:
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise ValueError()
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError()
        return amount
    except (InvalidOperation, ValueError):
        raise MarketDataError("invalid_cost", "Databento cost values must be finite, non-negative US dollar amounts.") from None


@dataclass(frozen=True)
class Config:
    api_key: str = field(repr=False)
    datasets: tuple[str, ...] = ()
    max_cost_usd: Decimal = Decimal("0")

    def __post_init__(self):
        if not isinstance(self.api_key, str) or not self.api_key or not self.api_key.isascii() or any(c.isspace() for c in self.api_key) or ":" in self.api_key:
            raise MarketDataError("not_configured", "Set DATABENTO_API_KEY in the agent server environment.")
        if not isinstance(self.datasets, tuple) or len(self.datasets) > 8:
            raise MarketDataError("invalid_configuration", "Configure at most eight Databento dataset codes.")
        for dataset in self.datasets:
            dataset_checked(dataset)
        object.__setattr__(self, "max_cost_usd", _money(self.max_cost_usd))

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        return cls(env.get("DATABENTO_API_KEY", "").strip(),
                   tuple(dict.fromkeys(x.strip() for x in env.get("TAU_DATABENTO_DATASETS", "").split(",") if x.strip())),
                   _money(env.get("TAU_DATABENTO_MAX_COST_USD", "0")))


class CostBudget:
    """Reserve estimates before every paid attempt; failures do not refund unknown spend."""

    def __init__(self, limit):
        self.limit = _money(limit)
        self.reserved = Decimal("0")
        self._lock = threading.Lock()

    def reserve(self, amount: Decimal) -> None:
        amount = _money(amount)
        with self._lock:
            if amount > self.limit - self.reserved:
                raise MarketDataError("cost_limit", "Databento's estimated download cost exceeds the remaining local budget; no download was started.")
            self.reserved += amount


def _integer(value, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r"-?\d{1,20}", str(value)):
        raise MarketDataError("invalid_data", "Databento returned an invalid integer field.")
    n = int(value)
    if not low <= n <= high:
        raise MarketDataError("invalid_data", "Databento returned an out-of-range or undefined integer field.")
    return n


def _bar(row: Dict, timeframe: str) -> tuple[str, Dict]:
    try:
        head = row["hd"]
        _, duration, rtype = TIMEFRAMES[timeframe]
        if _integer(head["rtype"], 0, 255) != rtype:
            raise ValueError()
        event_time = head["ts_event"]
        # Python datetime truncates nanoseconds; reject nonzero sub-second wire
        # values before parsing so they cannot be rounded across a cutoff.
        if not isinstance(event_time, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.0{1,9})?Z", event_time):
            raise ValueError()
        start = timestamp(event_time)
        if start.microsecond or int(start.timestamp()) % duration:
            raise ValueError()
        # The wire prices are fixed-point integers, explicitly requested with pretty_px=false.
        prices = {name: _integer(row[name], -(2**63), 2**63 - 2) / 1_000_000_000
                  for name in ("open", "high", "low", "close")}
        if not prices["low"] <= min(prices["open"], prices["close"]) <= max(prices["open"], prices["close"]) <= prices["high"]:
            raise ValueError()
        return row["symbol"], {"timestamp": iso(start), "interval_end": iso(start + timedelta(seconds=duration)),
                               **prices, "volume": _integer(row["volume"], 0, 2**64 - 2),
                               "instrument_id": _integer(head["instrument_id"], 1, 2**32 - 1),
                               "publisher_id": _integer(head["publisher_id"], 1, 2**16 - 1)}
    except (KeyError, TypeError, ValueError):
        raise MarketDataError("invalid_data", "Databento returned a malformed or inconsistent OHLCV record.") from None


class DatabentoDataClient:
    def __init__(self, config: Config, *, session=None, sleep: Callable = time.sleep,
                 clock: Callable = utc_now, budget: Optional[CostBudget] = None,
                 before_request: Callable = lambda: None, checkpoint: Callable = lambda: None):
        self.config = config
        self.session = session if session is not None else requests.Session()
        self.sleep, self.clock = sleep, clock
        self.budget = budget if budget is not None else CostBudget(config.max_cost_usd)
        self.before_request, self.checkpoint = before_request, checkpoint

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

    def _http(self, path: str, params: Dict) -> bytes:
        if path not in {"metadata.get_dataset_range", "metadata.get_cost", "timeseries.get_range"}:
            raise MarketDataError("invalid_request", "Only supported read-only Databento endpoints are allowed.")
        paid = path == "timeseries.get_range"
        for attempt in range(1 if paid else 3):
            self.checkpoint()
            self.before_request()
            response = None
            delay = min(2 ** attempt, 2)
            try:
                method = self.session.post if paid else self.session.get
                started = time.monotonic()
                response = method(DATA_URL + "/" + path, **({"data": params} if paid else {"params": params}),
                                  auth=(self.config.api_key, ""), headers={"Accept": "application/json"},
                                  timeout=(3.05, 8), allow_redirects=False, stream=True)
                status = response.status_code
                if status == 200:
                    parts, size = [], 0
                    for chunk in response.iter_content(chunk_size=65536):
                        self.checkpoint()
                        size += len(chunk)
                        if size > (MAX_RESPONSE_BYTES if paid else 65536) or time.monotonic() - started > MAX_REQUEST_SECONDS:
                            raise MarketDataError("response_limit", "Databento exceeded the bounded response size or duration; no partial data was used.")
                        parts.append(chunk)
                    return b"".join(parts)
                if status in {401, 402, 403, 206}:
                    code, message = {
                        401: ("authentication", "Databento rejected the market-data credentials."),
                        402: ("payment_required", "Databento requires an account payment change; no account change was attempted."),
                        403: ("entitlement", "Databento denied this dataset; no alternate dataset was used."),
                        206: ("partial_data", "Databento only partially resolved the request; no partial history was used."),
                    }[status]
                    raise MarketDataError(code, message)
                if paid or attempt == 2 or (status != 429 and not 500 <= status <= 599):
                    raise MarketDataError("rate_limit" if status == 429 else "provider_request",
                                          "Databento rejected the data request (HTTP %d). Downloads are never automatically retried." % status)
                try:
                    delay = max(0, min(float(response.headers.get("Retry-After", delay)), 3))
                except (TypeError, ValueError):
                    pass
            except requests.RequestException:
                if paid or attempt == 2:
                    raise MarketDataError("provider_unavailable", "Could not complete the Databento request. Downloads are not retried because bytes may already have been billed.") from None
            finally:
                if response is not None:
                    response.close()
            self.sleep(delay)
        raise AssertionError("unreachable")

    def _json(self, path: str, params: Dict):
        try:
            return json.loads(self._http(path, params), parse_float=Decimal)
        except (ValueError, UnicodeError):
            raise MarketDataError("invalid_data", "Databento returned invalid JSON metadata.") from None

    def _plan(self, symbols: Sequence[str], dataset: str, start: datetime, end: datetime, timeframe: str) -> tuple[Dict, Dict]:
        dataset = dataset_checked(dataset)
        symbols = symbols_checked(symbols)
        if dataset not in self.config.datasets:
            raise MarketDataError("dataset_disabled", "This Databento dataset is not in the server's explicit allowlist.")
        start, end = timestamp(start), timestamp(end)
        if not isinstance(timeframe, str) or timeframe not in TIMEFRAMES:
            raise MarketDataError("invalid_request", "Databento supports native 1Min, 1Hour and 1Day bars.")
        if not start < end <= self.clock() or end - start > timedelta(days=90):
            raise MarketDataError("invalid_request", "Databento history requires an increasing past window of at most 90 days.")
        schema = TIMEFRAMES[timeframe][0]
        available = self._json("metadata.get_dataset_range", {"dataset": dataset})
        try:
            window = available["schema"][schema]
            available_start, available_end = timestamp(window["start"]), timestamp(window["end"])
            if available_start >= available_end:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise MarketDataError("invalid_data", "Databento did not provide a valid availability window for this schema.") from None
        effective_start, effective_end = max(start, available_start), min(end, available_end)
        if effective_start >= effective_end:
            raise MarketDataError("data_unavailable", "No entitled Databento history overlaps the requested time window.")
        params = {"dataset": dataset, "symbols": ",".join(symbols), "schema": schema,
                  "start": iso(effective_start), "end": iso(effective_end),
                  "stype_in": "raw_symbol", "stype_out": "instrument_id", "limit": MAX_BARS + 1}
        cost = _money(self._json("metadata.get_cost", params))
        metadata = {"provider": "databento", "feed": dataset, "dataset": dataset,
                    "schema": schema, "timeframe": timeframe, "requested_symbols": list(symbols),
                    "requested_start": iso(start), "requested_end_exclusive": iso(end),
                    "start": iso(effective_start), "end_exclusive": iso(effective_end),
                    "availability_start": iso(available_start), "availability_end_exclusive": iso(available_end),
                    "availability_clipped": effective_start != start or effective_end != end,
                    "estimated_cost_usd": str(cost), "retrieved_at": iso(self.clock()),
                    "adjustment": "raw", "symbology": "raw_symbol", "point_in_time": False,
                    "daily_boundary": "UTC", "data_role": "historical_context",
                    "coverage_note": "Dataset-specific coverage. No-trade intervals have no bar; gaps are not forward-filled. Historical corrections may be present. Futures are explicit contracts, without roll adjustment."}
        return params, metadata

    def estimate(self, symbols: Sequence[str], dataset: str, start: datetime, end: datetime, *, timeframe: str = "1Hour") -> Dict:
        _, metadata = self._plan(symbols, dataset, start, end, timeframe)
        return {**metadata, "download_started": False}

    def bars(self, symbols: Sequence[str], dataset: str, start: datetime, end: datetime, *, timeframe: str = "1Hour") -> Dict:
        params, metadata = self._plan(symbols, dataset, start, end, timeframe)
        self.budget.reserve(Decimal(metadata["estimated_cost_usd"]))
        raw = self._http("timeseries.get_range", {**params, "encoding": "json", "compression": "none",
                                                "pretty_px": "false", "pretty_ts": "true", "map_symbols": "true"})
        lines = raw.splitlines()
        if len(lines) > MAX_BARS:
            raise MarketDataError("record_limit", "Databento history exceeded 10,000 records. Narrow the window or symbols; no partial history was used.")
        bars = {s: {} for s in metadata["requested_symbols"]}
        excluded = 0
        for line in lines:
            self.checkpoint()
            try:
                row = json.loads(line)
                symbol, bar = _bar(row, timeframe)
                if not isinstance(symbol, str) or symbol not in bars:
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise MarketDataError("invalid_data", "Databento returned invalid JSON or unexpected symbol mappings.") from None
            if timestamp(bar["timestamp"]) < timestamp(metadata["start"]) or timestamp(bar["interval_end"]) > timestamp(metadata["end_exclusive"]):
                excluded += 1
                continue
            key = bar["timestamp"]
            if key in bars[symbol] and bars[symbol][key] != bar:
                raise MarketDataError("ambiguous_data", "Databento returned conflicting bars for a symbol and interval; no series were combined.")
            bars[symbol][key] = bar
        return {**metadata, "complete": not metadata["availability_clipped"], "excluded_bars": excluded,
                "cache_hit": False, "download_started": True,
                "reserved_cost_usd": str(self.budget.reserved), "budget_limit_usd": str(self.budget.limit),
                "bars": {s: [rows[k] for k in sorted(rows)] for s, rows in bars.items()}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    for name in ("estimate", "bars"):
        command = commands.add_parser(name)
        command.add_argument("symbols", nargs="+")
        command.add_argument("--dataset", required=True)
        command.add_argument("--start", required=True)
        command.add_argument("--end", required=True)
        command.add_argument("--timeframe", choices=TIMEFRAMES, default="1Hour")
    args = parser.parse_args()
    try:
        config = Config.from_env()
        if args.command == "status":
            result = {"provider": "databento", "configured": True, "enabled": os.getenv("TAU_DATABENTO_ENABLED") == "1",
                      "datasets": config.datasets, "max_estimated_cost_usd": str(config.max_cost_usd),
                      "network_checked": False}
        else:
            start = timestamp(args.start + "T00:00:00Z" if len(args.start) == 10 else args.start)
            end = timestamp(args.end + "T00:00:00Z" if len(args.end) == 10 else args.end)
            with DatabentoDataClient(config) as client:
                result = getattr(client, args.command)(args.symbols, args.dataset, start, end, timeframe=args.timeframe)
        print(json.dumps(result, allow_nan=False))
        return 0
    except MarketDataError as e:
        print(json.dumps({"provider": "databento", "status": "unavailable", "code": e.code, "message": str(e)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
