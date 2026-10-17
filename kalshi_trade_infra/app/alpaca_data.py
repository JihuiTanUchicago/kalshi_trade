"""Read-only Alpaca US stock/ETF data. No brokerage or order endpoints.

    python -m app.alpaca_data status
    python -m app.alpaca_data snapshots SPY AAPL
    python -m app.alpaca_data bars SPY --start 2026-09-01 --end 2026-10-01
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import requests

from app.market_data_common import MarketDataError, TIMEFRAMES, equity_symbols as symbols_checked, get_json, iso, number as _number, timestamp, utc_now

DATA_URL = "https://data.alpaca.markets"
MAX_SYMBOLS = 8
MAX_BARS = 10_000
MAX_PAGES = 5
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Config:
    api_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    feed: str = "iex"

    def __post_init__(self):
        if not self.api_key.strip() or not self.secret_key.strip():
            raise MarketDataError("not_configured", "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY on the agent server.")
        if self.feed not in {"iex", "sip"}:
            raise MarketDataError("invalid_configuration", "TAU_ALPACA_FEED must be iex or sip.")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        endpoint = env.get("ALPACA_DATA_ENDPOINT", DATA_URL).strip().rstrip("/")
        if endpoint != DATA_URL:
            raise MarketDataError("invalid_configuration", "Alpaca market data must use https://data.alpaca.markets.")
        return cls(env.get("APCA_API_KEY_ID", "").strip(), env.get("APCA_API_SECRET_KEY", "").strip(),
                   env.get("TAU_ALPACA_FEED", "iex").strip().lower())

    @property
    def coverage(self) -> str:
        return "IEX exchange only" if self.feed == "iex" else "Consolidated US exchanges (SIP)"


def _bar(row: Dict, timeframe: str) -> Dict:
    try:
        start = timestamp(row["t"])
        if timeframe == "1Day":
            # Daily bars begin at NY midnight; DST days are not always 24 hours.
            local = start.astimezone(NY)
            end = (local.replace(hour=0, minute=0, second=0, microsecond=0)
                   + timedelta(days=1)).astimezone(timezone.utc)
        else:
            end = start + timedelta(seconds=TIMEFRAMES[timeframe])
        values = {name: _number(row[key], positive=True) for name, key in
                  (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))}
        if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
            raise MarketDataError("invalid_data", "Alpaca returned inconsistent OHLC prices.")
        return {"timestamp": iso(start), "interval_end": iso(end), **values, "volume": _number(row["v"])}
    except (KeyError, TypeError):
        raise MarketDataError("invalid_data", "Alpaca returned a malformed price bar.") from None


class AlpacaDataClient:
    def __init__(self, config: Config, *, session=None, sleep: Callable = time.sleep,
                 clock: Callable = utc_now):
        self.config = config
        self.session = session if session is not None else requests.Session()
        self.sleep = sleep
        self.clock = clock

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

    def _get(self, path: str, params: Dict) -> Dict:
        if path not in {"/v2/stocks/snapshots", "/v2/stocks/bars"}:
            raise MarketDataError("invalid_request", "Only read-only stock market-data endpoints are supported.")
        headers = {"APCA-API-KEY-ID": self.config.api_key, "APCA-API-SECRET-KEY": self.config.secret_key}
        return get_json(self.session, DATA_URL + path, headers=headers, params=params,
                        provider="Alpaca", sleep=self.sleep)

    def _metadata(self) -> Dict:
        return {"provider": "alpaca", "asset_class": "us_equity", "currency": "USD",
                "feed": self.config.feed, "coverage": self.config.coverage, "retrieved_at": iso(self.clock())}

    def snapshots(self, symbols: Sequence[str]) -> Dict:
        symbols = symbols_checked(symbols)
        raw = self._get("/v2/stocks/snapshots", {"symbols": ",".join(symbols), "feed": self.config.feed})
        if set(raw) - set(symbols):
            raise MarketDataError("invalid_data", "Alpaca returned unexpected snapshot symbols.")
        result = {}
        for symbol in symbols:
            row = raw.get(symbol)
            if row is None:
                result[symbol] = {"status": "missing"}
                continue
            if not isinstance(row, dict):
                raise MarketDataError("invalid_data", "Alpaca returned a malformed snapshot.")
            item = {}
            try:
                trade = row.get("latestTrade")
                if trade:
                    item["latest_trade"] = {"timestamp": iso(timestamp(trade["t"])),
                                            "price": _number(trade["p"], positive=True), "size": _number(trade["s"])}
                quote = row.get("latestQuote")
                if quote:
                    bid, ask = _number(quote["bp"]), _number(quote["ap"])
                    item["latest_quote"] = {"timestamp": iso(timestamp(quote["t"])),
                                            "bid": bid or None, "ask": ask or None,
                                            "bid_size": _number(quote["bs"]), "ask_size": _number(quote["as"]),
                                            "crossed": bool(bid and ask and bid > ask)}
                for key, name, tf in (("minuteBar", "minute_bar", "1Min"), ("dailyBar", "daily_bar", "1Day"),
                                      ("prevDailyBar", "previous_daily_bar", "1Day")):
                    if row.get(key):
                        item[name] = _bar(row[key], tf)
                result[symbol] = {"status": "available" if item else "missing", **item}
            except (KeyError, TypeError):
                raise MarketDataError("invalid_data", "Alpaca returned malformed trade or quote data.") from None
        return {**self._metadata(), "snapshots": result}

    def bars(self, symbols: Sequence[str], start: datetime, end: datetime, *, timeframe: str = "1Hour") -> Dict:
        symbols = symbols_checked(symbols)
        start, end = timestamp(start), timestamp(end)
        if timeframe not in TIMEFRAMES:
            raise MarketDataError("invalid_request", "Unsupported bar timeframe.")
        if not start < end or end > self.clock():
            raise MarketDataError("invalid_request", "Historical bars need a past, increasing time window.")
        params = {"symbols": ",".join(symbols), "start": iso(start), "end": iso(end - timedelta(microseconds=1)),
                  "timeframe": timeframe, "feed": self.config.feed, "adjustment": "raw", "sort": "asc",
                  "asof": end.astimezone(NY).date().isoformat(), "limit": MAX_BARS}
        by_symbol = {symbol: {} for symbol in symbols}
        tokens, count, excluded = set(), 0, 0
        for _ in range(MAX_PAGES):
            payload = self._get("/v2/stocks/bars", params)
            raw = payload.get("bars")
            if not isinstance(raw, dict) or set(raw) - set(symbols):
                raise MarketDataError("invalid_data", "Alpaca returned a malformed historical-bar response.")
            for symbol, rows in raw.items():
                if not isinstance(rows, list):
                    raise MarketDataError("invalid_data", "Alpaca returned a malformed historical-bar list.")
                count += len(rows)
                if count > MAX_BARS:
                    raise MarketDataError("request_limit", "Historical data exceeds the bar budget. Use a shorter window or coarser timeframe.")
                for row in rows:
                    bar = _bar(row, timeframe)
                    if start <= timestamp(bar["timestamp"]) and timestamp(bar["interval_end"]) <= end:
                        by_symbol[symbol][bar["timestamp"]] = bar
                    else:
                        excluded += 1  # includes bars beginning before the cutoff but completing after it
            token = payload.get("next_page_token")
            if token is None or token == "":
                break
            if not isinstance(token, str) or token in tokens:
                raise MarketDataError("invalid_data", "Alpaca returned a repeated or invalid pagination token.")
            tokens.add(token)
            params = {**params, "page_token": token}
        else:
            raise MarketDataError("request_limit", "Historical data exceeds the page budget. Use a shorter window or coarser timeframe.")
        return {**self._metadata(), "start": iso(start), "end_exclusive": iso(end), "timeframe": timeframe,
                "adjustment": "raw", "symbol_mapping_asof": params["asof"], "excluded_bars": excluded,
                "complete": True, "bars": {symbol: [rows[t] for t in sorted(rows)] for symbol, rows in by_symbol.items()},
                "limitation": "Vendor history can contain later corrections; raw bars are not a point-in-time corporate-action or universe dataset."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "snapshots", "bars"))
    parser.add_argument("symbols", nargs="*")
    parser.add_argument("--start", help="Inclusive ISO timestamp (UTC date also accepted)")
    parser.add_argument("--end", help="Exclusive ISO timestamp (UTC date also accepted)")
    parser.add_argument("--timeframe", default="1Hour", choices=tuple(TIMEFRAMES))
    args = parser.parse_args()
    try:
        config = Config.from_env()
        if args.command == "status":
            print(json.dumps({"provider": "alpaca", "credentials_configured": True, "feed": config.feed,
                              "coverage": config.coverage, "agent_enabled": os.getenv("TAU_ALPACA_ENABLED") == "1",
                              "connectivity_tested": False}))
            return 0
        with AlpacaDataClient(config) as client:
            if args.command == "snapshots":
                result = client.snapshots(args.symbols)
            else:
                if not args.start or not args.end:
                    parser.error("bars requires --start and --end")
                start = timestamp(args.start + "T00:00:00Z" if len(args.start) == 10 else args.start)
                end = timestamp(args.end + "T00:00:00Z" if len(args.end) == 10 else args.end)
                result = client.bars(args.symbols, start, end, timeframe=args.timeframe)
        print(json.dumps(result, allow_nan=False))
        return 0
    except MarketDataError as e:
        print(json.dumps({"provider": "alpaca", "status": "unavailable", "code": e.code, "message": str(e)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
