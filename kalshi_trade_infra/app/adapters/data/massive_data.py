"""Read-only Massive FX, rates and option chains. No trading/account endpoints.

    python -m app.adapters.data.massive_data status
    python -m app.adapters.data.massive_data fx-bars EURUSD --start 2026-10-01 --end 2026-10-15
    python -m app.adapters.data.massive_data macro treasury_yields --start 2026-10-01 --end 2026-10-15
    python -m app.adapters.data.massive_data options-chain SPY --expiration-date 2026-10-23
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlsplit

import requests

from app.adapters.data.market_data_common import MarketDataError, TIMEFRAMES, equity_symbols as symbols_checked, get_json, iso, number, timestamp, utc_now

DATA_URL = "https://api.massive.com"
MAX_SYMBOLS = 3
MAX_PAGES = 3
MAX_ROWS = 5_000
OPTIONS_LIMIT = 50
DEFAULT_SYMBOLS = "EURUSD,USDJPY,GBPUSD"
DATASETS = ("fx", "treasury_yields", "funding_conditions", "options")
RATE_FIELDS = {
    "treasury_yields": tuple("yield_" + x for x in (
        "1_month", "3_month", "6_month", "1_year", "2_year", "3_year", "5_year",
        "7_year", "10_year", "20_year", "30_year")),
    "funding_conditions": (
        "effective_fed_funds_rate", "effective_fed_funds_volume", "fed_funds_target_lower",
        "fed_funds_target_upper", "fed_overnight_repo_treasury_amount",
        "fed_overnight_reverse_repo_treasury_amount", "financial_commercial_paper_90d_rate",
        "interest_on_reserve_balances", "nonfinancial_commercial_paper_90d_rate",
        "obfr_25th_percentile", "obfr_75th_percentile", "obfr_volume", "overnight_bank_funding_rate",
        "secured_overnight_financing_rate", "sofr_25th_percentile", "sofr_75th_percentile", "sofr_volume",
        "tgcr_25th_percentile", "tgcr_75th_percentile", "tri_party_general_collateral_rate",
        "tri_party_general_collateral_volume"),
}


def pairs_checked(symbols: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(symbols, (list, tuple)) or not 1 <= len(symbols) <= MAX_SYMBOLS:
        raise MarketDataError("invalid_request", "Request between one and three FX pairs.")
    result = []
    for symbol in symbols:
        if not isinstance(symbol, str) or not re.fullmatch(r"(?:C:)?[A-Za-z]{3}/?[A-Za-z]{3}", symbol):
            raise MarketDataError("invalid_request", "FX symbols must look like EURUSD, EUR/USD or C:EURUSD.")
        pair = symbol.upper().removeprefix("C:").replace("/", "")
        if pair[:3] == pair[3:]:
            raise MarketDataError("invalid_request", "An FX pair must contain two different currencies.")
        if "C:" + pair not in result:
            result.append("C:" + pair)
    return tuple(result)


def _date(value) -> date:
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError()
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise MarketDataError("invalid_data", "Dates must use YYYY-MM-DD.") from None


def _epoch(value, units: int) -> datetime:
    try:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError()
        seconds, remainder = divmod(value, units)
        return datetime.fromtimestamp(seconds, timezone.utc) + timedelta(microseconds=remainder * 1_000_000 // units)
    except (ValueError, OverflowError, OSError):
        raise MarketDataError("invalid_data", "Massive returned an invalid event timestamp.") from None


def options_checked(query: Dict) -> Dict:
    if set(query) - {"symbols", "expiration_date", "contract_type", "strike_min", "strike_max"}:
        raise MarketDataError("invalid_request", "Unsupported option-chain filter.")
    symbols = symbols_checked(query.get("symbols"))
    if len(symbols) != 1:
        raise MarketDataError("invalid_request", "Request one underlying per option chain.")
    result = {"symbols": list(symbols)}
    if "expiration_date" in query:
        result["expiration_date"] = _date(query["expiration_date"]).isoformat()
    if "contract_type" in query:
        if not isinstance(query["contract_type"], str) or query["contract_type"] not in {"call", "put"}:
            raise MarketDataError("invalid_request", "Option contract_type must be call or put.")
        result["contract_type"] = query["contract_type"]
    for key in ("strike_min", "strike_max"):
        if key in query:
            result[key] = number(query[key], positive=True)
    if result.get("strike_min", 0) > result.get("strike_max", float("inf")):
        raise MarketDataError("invalid_request", "Option strike_min cannot exceed strike_max.")
    return result


@dataclass(frozen=True)
class Config:
    api_key: str = field(repr=False)
    fx_feed: str = "end_of_day"
    datasets: tuple[str, ...] = DATASETS

    def __post_init__(self):
        if not self.api_key.strip() or "\n" in self.api_key or "\r" in self.api_key:
            raise MarketDataError("not_configured", "Set MASSIVE_API_KEY in the agent server environment.")
        if self.fx_feed not in {"end_of_day", "realtime"}:
            raise MarketDataError("invalid_configuration", "TAU_MASSIVE_FX_FEED must be end_of_day or realtime.")
        if not self.datasets or set(self.datasets) - set(DATASETS):
            raise MarketDataError("invalid_configuration", "TAU_MASSIVE_DATASETS contains an unsupported dataset.")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        return cls(env.get("MASSIVE_API_KEY", "").strip(),
                   env.get("TAU_MASSIVE_FX_FEED", "end_of_day").strip(),
                   tuple(x.strip() for x in env.get("TAU_MASSIVE_DATASETS", ",".join(DATASETS)).split(",")))


class MassiveDataClient:
    def __init__(self, config: Config, *, session=None, sleep: Callable = time.sleep,
                 clock: Callable = utc_now, checkpoint: Callable = lambda: None):
        self.config = config
        self.session = session if session is not None else requests.Session()
        self.sleep, self.clock, self.checkpoint = sleep, clock, checkpoint

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

    def _get(self, path: str, params: Dict) -> Dict:
        if not re.fullmatch(
            r"/v1/last_quote/currencies/[A-Z]{3}/[A-Z]{3}"
            r"|/v2/aggs/ticker/C:[A-Z]{6}/range/(?:1|5|15)/(?:minute|hour|day)/\d+/\d+"
            r"|/fed/v1/(?:treasury-yields|funding-conditions)"
            r"|/v3/snapshot/options/[A-Z][A-Z0-9.-]{0,14}", path):
            raise MarketDataError("invalid_request", "Only supported read-only Massive data endpoints are allowed.")
        payload = get_json(self.session, DATA_URL + path, params=params,
                           headers={"Authorization": "Bearer " + self.config.api_key}, provider="Massive",
                           sleep=self.sleep, checkpoint=self.checkpoint)
        if not isinstance(payload.get("status"), str) or payload["status"] not in {"OK", "DELAYED", "success"}:
            raise MarketDataError("provider_request", "Massive did not return a successful data response.")
        return payload

    def _metadata(self, asset_class: str, feed: str) -> Dict:
        return {"provider": "massive", "asset_class": asset_class, "feed": feed,
                "retrieved_at": iso(self.clock())}

    def _enabled(self, dataset: str) -> None:
        if dataset not in self.config.datasets:
            raise MarketDataError("dataset_disabled", "This Massive dataset is disabled by the server configuration.")

    def _window(self, start: datetime, end: datetime) -> tuple[datetime, datetime]:
        start, end = timestamp(start), timestamp(end)
        if not start < end or end > self.clock() or end - start > timedelta(days=90):
            raise MarketDataError("invalid_request", "Data requires an increasing past window of at most 90 days.")
        return start, end

    def _cursor(self, url, path: str) -> str:
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != "api.massive.com" or parsed.port not in {None, 443}
                    or parsed.username or parsed.password or parsed.fragment or parsed.path != path):
                raise ValueError()
            query = parse_qs(parsed.query, strict_parsing=True, max_num_fields=20)
            cursor = query.get("cursor", [])
            if len(cursor) != 1 or not cursor[0] or len(cursor[0]) > 4096:
                raise ValueError()
            if any(key.lower() in {"apikey", "api_key", "authorization", "token"} for key in query):
                raise ValueError()
            return cursor[0]
        except (AttributeError, TypeError, ValueError):
            raise MarketDataError("invalid_data", "Massive returned an unsafe or invalid pagination link.") from None

    def _pages(self, path: str, params: Dict):
        cursors, count = set(), 0
        for _ in range(MAX_PAGES):
            payload = self._get(path, params)
            rows = payload.get("results", [] if payload.get("resultsCount", payload.get("count")) == 0 else None)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise MarketDataError("invalid_data", "Massive returned a malformed historical data list.")
            count += len(rows)
            if count > MAX_ROWS:
                raise MarketDataError("request_limit", "Massive data exceeds the row budget. Use a shorter window or coarser bars.")
            yield payload, rows
            link = payload.get("next_url")
            if link is None or link == "":
                return
            cursor = self._cursor(link, path)
            if cursor in cursors:
                raise MarketDataError("invalid_data", "Massive returned a repeated pagination cursor.")
            cursors.add(cursor)
            # Rebuild on our fixed host/path and preserve our filters; never forward a provider URL or API key.
            params = {**params, "cursor": cursor}
        raise MarketDataError("request_limit", "Massive data exceeds the page budget. Narrow the query.")

    def fx_bars(self, symbols: Sequence[str], start: datetime, end: datetime, *, timeframe: str = "1Hour") -> Dict:
        self._enabled("fx")
        symbols = pairs_checked(symbols)
        start, end = self._window(start, end)
        if timeframe not in TIMEFRAMES:
            raise MarketDataError("invalid_request", "Unsupported FX bar timeframe.")
        if self.config.fx_feed == "end_of_day" and end > self.clock().replace(hour=0, minute=0, second=0, microsecond=0):
            raise MarketDataError("recency", "The configured end-of-day FX feed cannot query today's intervals.")
        multiplier, timespan = {"1Min": (1, "minute"), "5Min": (5, "minute"), "15Min": (15, "minute"),
                                "1Hour": (1, "hour"), "1Day": (1, "day")}[timeframe]
        bars, excluded = {}, 0
        for symbol in symbols:
            path = "/v2/aggs/ticker/%s/range/%d/%s/%d/%d" % (
                symbol, multiplier, timespan, int(start.timestamp() * 1000), int(end.timestamp() * 1000) - 1)
            points = {}
            for payload, rows in self._pages(path, {"adjusted": "false", "sort": "asc", "limit": 50_000}):
                if payload.get("ticker", symbol) != symbol:
                    raise MarketDataError("invalid_data", "Massive returned an unexpected FX ticker.")
                for row in rows:
                    try:
                        t = _epoch(row["t"], 1000)
                        values = {name: number(row[key], positive=True) for name, key in
                                  (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))}
                        if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
                            raise ValueError()
                        interval_end = t + timedelta(seconds=TIMEFRAMES[timeframe])
                        point = {"timestamp": iso(t), "interval_end": iso(interval_end), **values,
                                 "volume": None, "vendor_quote_activity": number(row["v"]) if row.get("v") is not None else None}
                    except (KeyError, TypeError, ValueError):
                        raise MarketDataError("invalid_data", "Massive returned a malformed FX bar.") from None
                    if start <= t and interval_end <= end:
                        points[point["timestamp"]] = point
                    else:
                        excluded += 1
            bars[symbol] = [points[t] for t in sorted(points)]
        return {**self._metadata("forex", self.config.fx_feed), "start": iso(start), "end_exclusive": iso(end),
                "timeframe": timeframe, "bars": bars, "complete": True, "excluded_bars": excluded,
                "aggregate_basis": "bid_ask_quotes", "volume_kind": "no_consolidated_traded_volume",
                "limitation": "Quote-derived bars are not executions or guaranteed fills. History may contain later corrections."}

    def fx_quotes(self, symbols: Sequence[str]) -> Dict:
        self._enabled("fx")
        symbols = pairs_checked(symbols)
        if self.config.fx_feed != "realtime":
            raise MarketDataError("recency", "Current FX quotes require TAU_MASSIVE_FX_FEED=realtime and matching entitlement.")
        result = {}
        for symbol in symbols:
            pair = symbol[2:]
            raw = self._get("/v1/last_quote/currencies/%s/%s" % (pair[:3], pair[3:]), {})
            if raw.get("symbol", pair[:3] + "/" + pair[3:]) != pair[:3] + "/" + pair[3:]:
                raise MarketDataError("invalid_data", "Massive returned an unexpected quote pair.")
            quote = raw.get("last")
            if quote is None:
                result[symbol] = {"status": "missing"}
                continue
            try:
                bid, ask = number(quote["bid"]), number(quote["ask"])
                point = {"timestamp": iso(_epoch(quote["timestamp"], 1000)), "bid": bid or None,
                         "ask": ask or None, "crossed": bool(bid and ask and bid > ask)}
            except (KeyError, TypeError):
                raise MarketDataError("invalid_data", "Massive returned a malformed FX quote.") from None
            result[symbol] = {"status": "available", "latest_quote": point}
        return {**self._metadata("forex", "realtime"), "snapshots": result,
                "coverage": "Vendor FX BBO; decentralized market, not a consolidated exchange tape"}

    def macro(self, dataset: str, start: datetime, end: datetime) -> Dict:
        if not isinstance(dataset, str) or dataset not in RATE_FIELDS:
            raise MarketDataError("invalid_request", "Macro dataset must be treasury_yields or funding_conditions.")
        self._enabled(dataset)
        start, end = self._window(start, end)
        path = "/fed/v1/" + dataset.replace("_", "-")
        points = {}
        for _, rows in self._pages(path, {"date.gte": start.date().isoformat(), "date.lte": end.date().isoformat(),
                                          "sort": "date.asc", "limit": 100}):
            for row in rows:
                observed = _date(row.get("date"))
                if not start.date() <= observed <= end.date():
                    continue
                values = {key: number(row[key], signed="volume" not in key and "amount" not in key)
                          for key in RATE_FIELDS[dataset] if row.get(key) is not None}
                if values:
                    points[observed.isoformat()] = {"date": observed.isoformat(), **values}
        return {**self._metadata("economy", "daily_official_publications"), "dataset": dataset,
                "start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
                "observations": [points[d] for d in sorted(points)], "complete": True,
                "rate_units": "percent", "volume_units": "billions_of_USD", "point_in_time": False,
                "limitation": "Dates are observation dates, not release/vintage timestamps. Latest revised history is for current analysis only."}

    def options_chain(self, query: Dict) -> Dict:
        self._enabled("options")
        query = options_checked(query)
        symbol = query["symbols"][0]
        params = {"limit": OPTIONS_LIMIT, "sort": "strike_price", "order": "asc",
                  "expiration_date.gte": self.clock().date().isoformat()}
        for source, target in (("expiration_date", "expiration_date"), ("contract_type", "contract_type"),
                               ("strike_min", "strike_price.gte"), ("strike_max", "strike_price.lte")):
            if source in query:
                params[target] = query[source]
        if "expiration_date" in query and _date(query["expiration_date"]) < self.clock().date():
            raise MarketDataError("invalid_request", "Current option chains cannot request expired contracts.")
        raw = self._get("/v3/snapshot/options/" + symbol, params)
        rows = raw.get("results")
        if not isinstance(rows, list) or len(rows) > OPTIONS_LIMIT:
            raise MarketDataError("invalid_data", "Massive returned an invalid option-chain page.")
        result = {}
        for row in rows:
            try:
                details = row["details"]
                ticker = details["ticker"]
                if not isinstance(ticker, str) or not re.fullmatch(r"O:[A-Z0-9.]{1,15}\d{6}[CP]\d{8}", ticker):
                    raise ValueError()
                if not isinstance(details["contract_type"], str) or details["contract_type"] not in {"call", "put"}:
                    raise ValueError()
                item = {"status": "available", "strike_price": number(details["strike_price"], positive=True),
                        "expiration_date": _date(details["expiration_date"]).isoformat(),
                        "contract_type": details["contract_type"],
                        "greeks": {key: number(value, signed=True) for key, value in (row.get("greeks") or {}).items()
                                   if key in {"delta", "gamma", "theta", "vega"} and value is not None},
                        "implied_volatility": number(row["implied_volatility"]) if row.get("implied_volatility") is not None else None,
                        "open_interest": number(row["open_interest"]) if row.get("open_interest") is not None else None}
                quote = row.get("last_quote")
                if quote:
                    bid, ask = number(quote["bid"]), number(quote["ask"])
                    item["latest_quote"] = {"timestamp": iso(_epoch(quote["last_updated"], 1_000_000_000)),
                                             "bid": bid or None, "ask": ask or None,
                                             "crossed": bool(bid and ask and bid > ask)}
                trade = row.get("last_trade")
                if trade:
                    item["latest_trade"] = {"timestamp": iso(_epoch(trade["sip_timestamp"], 1_000_000_000)),
                                             "price": number(trade["price"], positive=True), "size": number(trade["size"])}
                underlying = row.get("underlying_asset")
                if underlying and underlying.get("price") is not None:
                    if underlying.get("ticker", symbol) != symbol:
                        raise ValueError()
                    item["underlying_price"] = number(underlying["price"], positive=True)
                    if underlying.get("last_updated"):
                        item["underlying_timestamp"] = iso(_epoch(underlying["last_updated"], 1_000_000_000))
                    else:
                        item.update(underlying_price_fresh=False, underlying_price_age_seconds=None)
                if query.get("expiration_date", item["expiration_date"]) != item["expiration_date"]:
                    raise ValueError()
                if query.get("contract_type", item["contract_type"]) != item["contract_type"]:
                    raise ValueError()
                if not query.get("strike_min", 0) <= item["strike_price"] <= query.get("strike_max", float("inf")):
                    raise ValueError()
                if ticker in result or _date(item["expiration_date"]) < self.clock().date():
                    raise ValueError()
                result[ticker] = item
            except (KeyError, TypeError, ValueError, AttributeError):
                raise MarketDataError("invalid_data", "Massive returned malformed option-chain data.") from None
        return {**self._metadata("us_option", "subscription_dependent"), "underlying": symbol,
                "filters": query, "snapshots": result, "complete": not bool(raw.get("next_url")),
                "sample_limit": OPTIONS_LIMIT, "sample_kind": "first_page_sorted_by_strike",
                "open_interest_asof": "previous_trading_day_close",
                "greeks_asof": "no_independent_analytics_timestamp",
                "limitation": "Filter expiry/type/strikes to refine a truncated chain. Greeks/IV are current snapshots, not historical; missing fields stay missing. Underlying and option recency depend on separate entitlements."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    quotes = sub.add_parser("fx-quotes")
    quotes.add_argument("symbols", nargs="+")
    for name in ("fx-bars", "macro"):
        command = sub.add_parser(name)
        command.add_argument("symbols", nargs="+", help="FX pairs, or one macro dataset")
        command.add_argument("--start", required=True)
        command.add_argument("--end", required=True)
        if name == "fx-bars":
            command.add_argument("--timeframe", default="1Hour", choices=tuple(TIMEFRAMES))
    options = sub.add_parser("options-chain")
    options.add_argument("symbol")
    options.add_argument("--expiration-date")
    options.add_argument("--contract-type", choices=("call", "put"))
    options.add_argument("--strike-min", type=float)
    options.add_argument("--strike-max", type=float)
    args = parser.parse_args()
    try:
        config = Config.from_env()
        if args.command == "status":
            print(json.dumps({"provider": "massive", "credentials_configured": True, "fx_feed": config.fx_feed,
                              "datasets": config.datasets, "agent_enabled": os.getenv("TAU_MASSIVE_ENABLED") == "1",
                              "connectivity_tested": False}))
            return 0
        with MassiveDataClient(config) as client:
            if args.command == "fx-quotes":
                result = client.fx_quotes(args.symbols)
            elif args.command == "options-chain":
                query = {"symbols": [args.symbol]}
                query.update({key: getattr(args, key) for key in ("expiration_date", "contract_type", "strike_min", "strike_max")
                              if getattr(args, key) is not None})
                result = client.options_chain(query)
            else:
                start = timestamp(args.start + "T00:00:00Z" if len(args.start) == 10 else args.start)
                end = timestamp(args.end + "T00:00:00Z" if len(args.end) == 10 else args.end)
                if args.command == "fx-bars":
                    result = client.fx_bars(args.symbols, start, end, timeframe=args.timeframe)
                else:
                    if len(args.symbols) != 1:
                        parser.error("macro requires one dataset")
                    result = client.macro(args.symbols[0], start, end)
        print(json.dumps(result, allow_nan=False))
        return 0
    except MarketDataError as e:
        print(json.dumps({"provider": "massive", "status": "unavailable", "code": e.code, "message": str(e)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
