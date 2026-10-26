"""Native, anonymous Kalshi Bitcoin perpetual data; no account/order endpoints.

Prices are the API's USD per contract, not the USD price of one Bitcoin. Final
funding is cash-flow history. Only separately observed provisional estimates may
be used as funding features. No keys, .env loading, binary markets, or fallback
venues are involved.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from app.adapters.data.market_data_common import MarketDataError

BASE_URLS = {
    "production": "https://external-api.kalshi.com/trade-api/v2",
    "demo": "https://external-api.demo.kalshi.co/trade-api/v2",
}
SOURCE_SCHEMA = "kalshi-perps-normalized-v1"
SPEC_URL = "https://docs.kalshi.com/perps_openapi.yaml"
FUNDING_SCHEDULE_URL = "https://help.kalshi.com/en/articles/15357587-btc-perpetual-futures-contract-specifications"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_REQUEST_SECONDS = 20
MAX_BATCH_BYTES = 8 * 1024 * 1024
MAX_MARKETS = 1000
MAX_BATCH_SECONDS = 7 * 86400
MAX_HISTORY_SECONDS = 90 * 86400
MAX_CANDLES = MAX_BATCH_SECONDS // 60 + 1
MAX_FUNDING = 1000
_TICKER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}\Z")
_BITCOIN_TITLE = re.compile(
    r"bitcoin(?:\s*\(btc\))?(?:\s+(?:perpetual(?:\s+futures?)?|perps?|futures?))?\Z",
    re.IGNORECASE,
)
_BITCOIN_SIZE_TITLE = re.compile(r"((?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+))\s+BTC\Z", re.IGNORECASE)


def canonical_json(value: Any) -> str:
    """Stable value encoding, including Decimal values read from MySQL."""
    def default(item: Any) -> Any:
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, datetime):
            return iso_time(item)
        raise TypeError("Unsupported perpetual data value.")
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=default)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def iso_time(value: datetime | int | float) -> str:
    if not isinstance(value, datetime):
        value = datetime.fromtimestamp(value, timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketDataError("invalid_data", "Perpetual data timestamps must have a timezone.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def epoch(value: Any) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError()
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            result = int(value)
            if result != value or not 0 <= result <= 32_503_680_000:
                raise ValueError()
            return result
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError()
        result = int(dt.timestamp())
        if result < 0:
            raise ValueError()
        return result
    except (TypeError, ValueError, OverflowError, OSError):
        raise MarketDataError("invalid_data", "Kalshi returned an invalid perpetual timestamp.") from None


def available_epoch(value: str) -> int:
    """Round retrieval up so subsecond publication cannot appear early."""
    epoch(value)
    return math.ceil(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def ticker_checked(value: Any) -> str:
    if not isinstance(value, str) or not _TICKER.fullmatch(value):
        raise MarketDataError("invalid_request", "A native Kalshi perpetual ticker is required.")
    return value


def numeric(value: Any, *, positive: bool = False, signed: bool = False) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = float(value)
        if not math.isfinite(number) or abs(number) > 1e18:
            raise ValueError()
        if (positive and number <= 0) or (not signed and number < 0):
            raise ValueError()
        return number
    except (TypeError, ValueError, OverflowError):
        raise MarketDataError("invalid_data", "Kalshi returned invalid perpetual numeric data.") from None


def _decimal(value: Any, *, positive: bool = True, signed: bool = False) -> str:
    try:
        if isinstance(value, bool) or value is None:
            raise InvalidOperation()
        result = Decimal(str(value))
        if (not result.is_finite() or result.copy_abs() > Decimal("1e18")
                or result.as_tuple().exponent < -18 or (positive and result <= 0)
                or (not signed and result < 0)):
            raise InvalidOperation()
        return format(result, "f")
    except (InvalidOperation, ValueError, TypeError):
        raise MarketDataError("invalid_data", "Kalshi returned unsupported contract precision.") from None


def requested_range(start_ts: Any, end_ts: Any, *, max_seconds: int = MAX_BATCH_SECONDS) -> tuple[int, int]:
    start, end = epoch(start_ts), epoch(end_ts)
    if end < start or end - start > max_seconds:
        raise MarketDataError("invalid_request", "Perpetual history range is reversed or exceeds the bounded limit.")
    return start, end


def _check_public_proxy(value: str | None) -> None:
    """An operator may opt in to routing, never ambient proxy/account secrets."""
    if value is None:
        return
    try:
        if not isinstance(value, str) or not value or len(value) > 1024 or any(c.isspace() for c in value):
            raise ValueError()
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or parsed.port is not None and not 1 <= parsed.port <= 65535):
            raise ValueError()
    except (TypeError, ValueError):
        raise MarketDataError("invalid_configuration", "TAU_KALSHI_PERPS_PROXY_URL requires a credential-free HTTP(S) proxy URL without a path, query or fragment.") from None


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    environment: str = "production"
    ticker: str | None = None
    proxy_url: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool) or self.environment not in BASE_URLS:
            raise MarketDataError("invalid_configuration", "Kalshi perps requires production or demo environment.")
        if self.ticker is not None:
            ticker_checked(self.ticker)
        _check_public_proxy(self.proxy_url)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        flag = env.get("TAU_KALSHI_PERPS_ENABLED", "false").strip().lower()
        if flag not in {"0", "1", "true", "false"}:
            raise MarketDataError("invalid_configuration", "TAU_KALSHI_PERPS_ENABLED must be true or false.")
        if any(env.get(name, "").strip() for name in (
                "TAU_KALSHI_PERPS_BASE_URL", "TAU_KALSHI_PERPS_ENDPOINT", "TAU_KALSHI_PERPS_URL")):
            raise MarketDataError("invalid_configuration", "Kalshi perpetual hosts are fixed and cannot be configured.")
        return cls(flag in {"1", "true"},
                   env.get("TAU_KALSHI_PERPS_ENVIRONMENT", "production").strip().lower(),
                   env.get("TAU_KALSHI_PERPS_TICKER", "").strip() or None,
                   env.get("TAU_KALSHI_PERPS_PROXY_URL", "").strip() or None)

    def require_enabled(self) -> None:
        if not self.enabled:
            raise MarketDataError("disabled", "Kalshi perpetual research data is disabled; set TAU_KALSHI_PERPS_ENABLED=true.")


def normalize_instrument(row: Any, environment: str, retrieved_at: str) -> dict:
    """Validate Bitcoin from native metadata, retaining the contract-unit inputs."""
    if not isinstance(row, dict) or environment not in BASE_URLS:
        raise MarketDataError("invalid_data", "Kalshi returned malformed perpetual metadata.")
    title = row.get("title")
    sized_title = _BITCOIN_SIZE_TITLE.fullmatch(title.strip()) if isinstance(title, str) else None
    if not isinstance(title, str) or not (_BITCOIN_TITLE.fullmatch(title.strip()) or sized_title):
        raise MarketDataError("not_bitcoin", "Only verified native Bitcoin perpetual metadata is supported.")
    asset_class = row.get("asset_class")
    if asset_class is not None and (not isinstance(asset_class, str) or asset_class.strip().lower() not in {"crypto", "cryptocurrency"}):
        raise MarketDataError("not_bitcoin", "The native perpetual asset class does not describe Bitcoin.")
    try:
        native_ticker = ticker_checked(row["ticker"])
        contract_size = _decimal(row["contract_size"])
        multiplier = _decimal(row["underlying_multiplier"])
        tick_size = _decimal(row["tick_size"])
        fractional = row["fractional_trading_enabled"]
        schedule = row["schedule"]
        version, exchange_index = row["market_version"], row["exchange_index"]
        if (not isinstance(fractional, bool) or isinstance(version, bool) or not isinstance(version, int)
                or version < 1 or isinstance(exchange_index, bool) or not isinstance(exchange_index, int)
                or exchange_index < 0 or row["status"] not in {"active", "inactive", "closed"}
                or row["funding_limit_unit"] != "percentage"
                or row["funding_invalid_premium_handling"] not in {"dampen", "exclude"}):
            raise ValueError()
        with localcontext() as context:
            context.prec = 80
            contract_multiplier = format(Decimal(contract_size) * Decimal(multiplier), "f")
        if sized_title and Decimal(sized_title.group(1)) != Decimal(contract_multiplier):
            raise ValueError()
        instrument = {
            "ticker": native_ticker, "title": title.strip(), "environment": environment,
            "market_id": row.get("market_id"), "market_version": version,
            "exchange_index": exchange_index, "status": row["status"],
            "asset_class": row.get("asset_class"), "verified_bitcoin": True,
            "contract_size": contract_size, "underlying_multiplier": multiplier,
            "contract_multiplier": contract_multiplier,
            "quantity_step": "0.01" if fractional else "1", "tick_size": tick_size,
            "fractional_trading_enabled": fractional,
            "price_unit": "USD", "price_basis": "per_contract", "funding_rate_unit": "decimal",
            "unit_normalization": "contract_size * underlying_multiplier BTC per contract; native USD per contract",
            "funding_limit_unit": row["funding_limit_unit"],
            "funding_deadband": _decimal(row["funding_deadband"], positive=False),
            "funding_cap": _decimal(row["funding_cap"], positive=False),
            "funding_invalid_premium_handling": row["funding_invalid_premium_handling"],
            "schedule": schedule,
            "funding_schedule": {"timezone": "America/New_York", "hours": [0, 8, 16],
                                 "source_url": FUNDING_SCHEDULE_URL},
            "source_schema": SOURCE_SCHEMA, "schema_url": SPEC_URL,
        }
        # Retain bounded public product metadata because changes can alter interpretation.
        product_metadata = row.get("product_metadata")
        if product_metadata is not None:
            if not isinstance(product_metadata, dict) or len(canonical_json(product_metadata)) > 64 * 1024:
                raise ValueError()
            instrument["product_metadata"] = product_metadata
        instrument["metadata_fingerprint"] = fingerprint(instrument)
        instrument["retrieved_at"] = iso_time(epoch(retrieved_at))
        return instrument
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise MarketDataError("invalid_data", "Kalshi Bitcoin perpetual contract metadata is incomplete.") from None


def funding_times(start_ts: int, end_ts: int) -> list[int]:
    """Documented Bitcoin local-clock settlement schedule, including DST changes."""
    zone = ZoneInfo("America/New_York")
    first = datetime.fromtimestamp(start_ts, zone).date()
    last = datetime.fromtimestamp(end_ts, zone).date()
    output = []
    day = first
    while day <= last:
        for hour in (0, 8, 16):
            value = int(datetime(day.year, day.month, day.day, hour, tzinfo=zone).timestamp())
            if start_ts <= value <= end_ts:
                output.append(value)
        day += timedelta(days=1)
    return output


def candle_coverage(candles: list[dict], start_ts: int, end_ts: int) -> dict:
    offsets = {epoch(row["ts"]) % 60 for row in candles}
    if len(offsets) > 1:
        raise MarketDataError("invalid_data", "Kalshi returned inconsistent one-minute candle boundaries.")
    offset = next(iter(offsets), 0)
    first = start_ts + (offset - start_ts) % 60
    expected_count = max(0, (end_ts - first) // 60 + 1)
    present = {epoch(row["ts"]) for row in candles if start_ts <= epoch(row["ts"]) <= end_ts}
    missing_count = expected_count - len(present)
    gaps = []
    gap_start = previous = None
    for value in range(first, end_ts + 1, 60):
        if value not in present:
            if gap_start is None:
                gap_start = value
            previous = value
        elif gap_start is not None:
            gaps.append({"start_ts": gap_start, "end_ts": previous})
            gap_start = previous = None
    if gap_start is not None:
        gaps.append({"start_ts": gap_start, "end_ts": previous})
    complete = bool(candles) and missing_count == 0
    return {"status": "complete" if complete else "partial" if candles else "empty",
            "complete": complete, "start_ts": start_ts, "end_ts": end_ts,
            "row_count": len(present), "expected_count": expected_count,
            "missing_count": missing_count, "missing_intervals": gaps[:100],
            "missing_intervals_truncated": len(gaps) > 100, "period_seconds": 60,
            "timestamp_semantics": "completed exclusive minute boundary; native end retained"}


def funding_coverage(funding: list[dict], start_ts: int, end_ts: int, *,
                     retrieval_complete: bool, error_code: str | None = None) -> dict:
    expected = funding_times(start_ts, end_ts)
    actual = {epoch(row["ts"]) for row in funding}
    missing = sorted(set(expected) - actual)
    complete = retrieval_complete and not missing
    status = ("failed" if error_code else "unknown") if not retrieval_complete else (
        "empty" if not funding else "complete" if complete else "partial")
    return {"status": status, "retrieval_complete": retrieval_complete, "complete": complete,
            "start_ts": start_ts, "end_ts": end_ts, "row_count": len(funding),
            "expected_count": len(expected), "missing_timestamps": missing,
            "schedule": {"timezone": "America/New_York", "hours": [0, 8, 16]},
            "schedule_source_url": FUNDING_SCHEDULE_URL, "error_code": error_code}


class KalshiPerpsDataClient:
    """Fresh anonymous session with fixed endpoint allowlist and bounded responses."""

    def __init__(self, config: Config, *, session: Any = None,
                 sleep: Callable = time.sleep,
                 clock: Callable = lambda: datetime.now(timezone.utc)) -> None:
        self.config = config
        self.session = session if session is not None else requests.Session()
        self.sleep, self.clock = sleep, clock
        self._verified: dict[str, dict] = {}
        self._isolate_session()

    def _isolate_session(self) -> None:
        # Never inherit .netrc, ambient proxies, browser cookies, or account auth.
        self.session.trust_env = False
        if isinstance(self.session, requests.Session):
            self.session.auth = None
            self.session.headers.clear()
            self.session.params.clear()
            self.session.cookies.clear()
            self.session.proxies.clear()
            self.session.hooks = {"response": []}
            self.session.cert = None
            self.session.verify = True

    def __enter__(self) -> "KalshiPerpsDataClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.session.close()

    def _get(self, path: str, params: dict) -> tuple[dict, str]:
        self.config.require_enabled()
        allowed = {"/margin/markets", "/margin/funding_rates/historical", "/margin/funding_rates/estimate"}
        allowed.update("/margin/markets/" + ticker + suffix
                       for ticker in self._verified for suffix in ("", "/candlesticks"))
        # One explicit ticker may be looked up to verify it before any data request.
        if self.config.ticker:
            allowed.add("/margin/markets/" + self.config.ticker)
        if path not in allowed:
            raise MarketDataError("invalid_request", "Only verified public Bitcoin perpetual data endpoints are allowed.")
        for attempt in range(3):
            response = None
            started = time.monotonic()
            delay = min(2 ** attempt, 2)
            try:
                self._isolate_session()
                response = self.session.get(BASE_URLS[self.config.environment] + path,
                                            params=params, headers={"Accept": "application/json"},
                                            timeout=(3.05, 8), allow_redirects=False, stream=True,
                                            auth=(), proxies=({"https": self.config.proxy_url}
                                                             if self.config.proxy_url else {}), cookies={})
                status = response.status_code
                if status == 200:
                    body = bytearray()
                    for chunk in response.iter_content(chunk_size=65536):
                        if time.monotonic() - started > MAX_REQUEST_SECONDS:
                            raise MarketDataError("provider_unavailable", "Kalshi perpetual response exceeded its bounded read duration.")
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise MarketDataError("response_too_large", "Kalshi perpetual response exceeds the bounded size limit.")
                    payload = json.loads(body, parse_float=Decimal,
                                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(payload, dict) or payload.get("cursor") or payload.get("next_cursor"):
                        raise ValueError()
                    return payload, iso_time(self.clock())
                if status not in {429} and not 500 <= status <= 599:
                    code = "public_access_unavailable" if status in {401, 403} else "provider_request"
                    raise MarketDataError(code, "Kalshi public perpetual data is unavailable (HTTP %d)." % status)
                if attempt == 2:
                    code = "rate_limit" if status == 429 else "provider_unavailable"
                    raise MarketDataError(code, "Kalshi public perpetual data failed after three attempts (HTTP %d)." % status)
                try:
                    delay = max(0, min(float(response.headers.get("Retry-After", delay)), 3))
                except (TypeError, ValueError):
                    pass
            except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
                raise MarketDataError("invalid_data", "Kalshi returned malformed public perpetual JSON data.") from None
            except requests.RequestException as exc:
                if attempt == 2:
                    category = ("connection timeout" if isinstance(exc, requests.ConnectTimeout) else
                                "read timeout" if isinstance(exc, requests.ReadTimeout) else
                                "TLS verification failure" if isinstance(exc, requests.exceptions.SSLError) else
                                "proxy connection failure" if isinstance(exc, requests.exceptions.ProxyError) else
                                "network connection failure")
                    hint = (" Check the explicitly configured proxy and outbound network."
                            if self.config.proxy_url else
                            " If this host requires a proxy, set TAU_KALSHI_PERPS_PROXY_URL explicitly.")
                    raise MarketDataError("provider_unavailable", "Kalshi public perpetual data failed after three attempts (%s).%s" %
                                          (category, hint)) from None
            finally:
                if response is not None:
                    response.close()
            self.sleep(delay)
        raise AssertionError("unreachable")

    def discover_bitcoin(self) -> list[dict]:
        payload, retrieved = self._get("/margin/markets", {})
        rows = payload.get("markets")
        if not isinstance(rows, list) or len(rows) > MAX_MARKETS:
            raise MarketDataError("invalid_data", "Kalshi returned an invalid or unbounded perpetual market list.")
        output = []
        seen = set()
        for row in rows:
            try:
                instrument = normalize_instrument(row, self.config.environment, retrieved)
            except MarketDataError as exc:
                if exc.code == "not_bitcoin":
                    continue
                raise
            if instrument["ticker"] in seen:
                raise MarketDataError("invalid_data", "Kalshi returned duplicate Bitcoin perpetual tickers.")
            seen.add(instrument["ticker"])
            self._verified[instrument["ticker"]] = instrument
            output.append(instrument)
        return output

    def instrument(self, ticker: str | None = None) -> dict:
        ticker = ticker or self.config.ticker
        if ticker is None:
            instruments = self.discover_bitcoin()
            if len(instruments) != 1:
                raise MarketDataError("not_available", "Bitcoin perpetual discovery must return one verified native market; configure a native ticker if ambiguous.")
            return instruments[0]
        ticker_checked(ticker)
        if ticker in self._verified:
            return self._verified[ticker]
        # An explicitly supplied ticker is verified by discovery, never guessed.
        if ticker != self.config.ticker:
            self.discover_bitcoin()
            if ticker not in self._verified:
                raise MarketDataError("not_bitcoin", "The requested ticker is not a discovered Bitcoin perpetual market.")
            return self._verified[ticker]
        payload, retrieved = self._get("/margin/markets/" + ticker, {})
        instrument = normalize_instrument(payload.get("market"), self.config.environment, retrieved)
        if instrument["ticker"] != ticker:
            raise MarketDataError("invalid_data", "Kalshi returned a different perpetual ticker.")
        self._verified[ticker] = instrument
        return instrument

    def candles(self, ticker: str, start_ts: int, end_ts: int) -> tuple[list[dict], dict]:
        instrument = self.instrument(ticker)
        start, requested_end = requested_range(start_ts, end_ts)
        # Only completed minute boundaries are usable by the research simulator.
        end = min(requested_end, epoch(self.clock()) - 1)
        if end < start:
            raise MarketDataError("invalid_request", "Request completed perpetual candles only.")
        payload, retrieved = self._get("/margin/markets/" + instrument["ticker"] + "/candlesticks",
                                       {"start_ts": max(0, start - 1), "end_ts": end, "period_interval": 1,
                                        "include_latest_before_start": "false"})
        rows = payload.get("candlesticks")
        if payload.get("ticker") != ticker or not isinstance(rows, list) or len(rows) > MAX_CANDLES:
            raise MarketDataError("invalid_data", "Kalshi returned invalid or unbounded perpetual candles.")
        output: dict[int, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise MarketDataError("invalid_data", "Kalshi returned malformed perpetual candles.")
            native_end = epoch(row.get("end_period_ts"))
            if native_end % 60 not in {0, 59}:
                raise MarketDataError("invalid_data", "Kalshi returned a non-minute perpetual candle boundary.")
            ts = native_end + 1 if native_end % 60 == 59 else native_end
            if not start <= ts <= end or ts > (epoch(self.clock()) // 60) * 60:
                continue
            price = row.get("price")
            if not isinstance(price, dict):
                raise MarketDataError("invalid_data", "Kalshi returned malformed perpetual candle prices.")
            # Native no-trade/synthetic bars have null OHLC. Never carry previous forward.
            if any(price.get(key) is None for key in ("open", "high", "low", "close")):
                continue
            values = {key: _decimal(price[key]) for key in ("open", "high", "low", "close")}
            o, h, lo, c = (Decimal(values[key]) for key in ("open", "high", "low", "close"))
            if not lo <= min(o, c) <= max(o, c) <= h:
                raise MarketDataError("invalid_data", "Kalshi returned inconsistent perpetual OHLC prices.")
            bid = self._quote_close(row.get("bid"))
            ask = self._quote_close(row.get("ask"))
            if bid is not None and ask is not None and Decimal(bid) > Decimal(ask):
                bid = ask = None
            item = {"ts": ts, "native_end_ts": native_end,
                    "timestamp_normalization": "inclusive_second_to_exclusive_minute" if native_end % 60 == 59 else "native_minute_boundary",
                    **values, "bid": bid, "ask": ask,
                    "volume": numeric(row["volume"]) if row.get("volume") is not None else None,
                    "retrieved_at": retrieved, "available_at": ts,
                    "source_schema": SOURCE_SCHEMA}
            if ts in output:
                raise MarketDataError("invalid_data", "Kalshi returned duplicate perpetual candle timestamps.")
            output[ts] = item
        candles = [output[ts] for ts in sorted(output)]
        return candles, candle_coverage(candles, start, end)

    @staticmethod
    def _quote_close(side: Any) -> str | None:
        if not isinstance(side, dict) or side.get("close") is None:
            return None
        value = _decimal(side["close"], positive=False)
        return value if Decimal(value) > 0 else None

    def funding(self, ticker: str, start_ts: int, end_ts: int) -> tuple[list[dict], dict]:
        self.instrument(ticker)
        start, end = requested_range(start_ts, end_ts)
        end = min(end, epoch(self.clock()) - 1)
        if end < start:
            raise MarketDataError("invalid_request", "Request completed funding periods only.")
        payload, retrieved = self._get("/margin/funding_rates/historical",
                                       {"ticker": ticker, "start_ts": start, "end_ts": end})
        rows = payload.get("funding_rates")
        if not isinstance(rows, list) or len(rows) > MAX_FUNDING:
            raise MarketDataError("invalid_data", "Kalshi returned invalid or unbounded funding history.")
        output: dict[int, dict] = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("market_ticker") != ticker:
                raise MarketDataError("invalid_data", "Kalshi returned funding for an unexpected perpetual ticker.")
            ts = epoch(row.get("funding_time"))
            if not start <= ts <= end:
                continue
            rate = _decimal(row.get("funding_rate"), positive=False, signed=True)
            if abs(Decimal(rate)) > 1:
                raise MarketDataError("invalid_data", "Kalshi Bitcoin funding rate exceeds decimal-fraction bounds.")
            if ts in output:
                raise MarketDataError("invalid_data", "Kalshi returned duplicate perpetual funding times.")
            output[ts] = {"ts": ts, "rate": rate, "mark_price": _decimal(row.get("mark_price")),
                          "available_at": max(ts, available_epoch(retrieved)), "retrieved_at": retrieved,
                          "kind": "settled_funding", "source_schema": SOURCE_SCHEMA}
        funding = [output[ts] for ts in sorted(output)]
        return funding, funding_coverage(funding, start, end, retrieval_complete=True)

    def observations(self, ticker: str) -> tuple[list[dict], dict]:
        self.instrument(ticker)
        output = []
        errors = []
        payload, retrieved = self._get("/margin/markets/" + ticker, {})
        raw = payload.get("market")
        current = normalize_instrument(raw, self.config.environment, retrieved)
        if current["ticker"] != ticker:
            raise MarketDataError("invalid_data", "Kalshi returned a different observed perpetual ticker.")
        self._verified[ticker] = current
        available = available_epoch(retrieved)
        bid, ask = (_decimal(raw[key], positive=False) if raw.get(key) is not None else None for key in ("bid", "ask"))
        bid = bid if bid is not None and Decimal(bid) > 0 else None
        ask = ask if ask is not None and Decimal(ask) > 0 else None
        if bid is not None and ask is not None and Decimal(bid) > Decimal(ask):
            bid = ask = None
        if bid is not None or ask is not None:
            output.append({"kind": "quote", "ts": available, "available_at": available,
                           "bid": bid, "ask": ask, "retrieved_at": retrieved})
        for field, kind, value_key in (("settlement_mark_price", "mark", "mark_price"),
                                      ("reference_price", "index", "index_price")):
            price = raw.get(field)
            if price is not None:
                if not isinstance(price, dict):
                    raise MarketDataError("invalid_data", "Kalshi returned malformed observed perpetual prices.")
                source_ts = numeric(price.get("ts_ms")) / 1000
                if source_ts > available + 1:
                    raise MarketDataError("invalid_data", "Kalshi returned future-dated perpetual observations.")
                output.append({"kind": kind, "ts": source_ts, "available_at": available,
                               value_key: _decimal(price.get("price")), "retrieved_at": retrieved})
        try:
            estimate, estimate_retrieved = self._get("/margin/funding_rates/estimate", {"ticker": ticker})
            if estimate.get("market_ticker") not in {None, ticker}:
                raise MarketDataError("invalid_data", "Kalshi returned a different funding-estimate ticker.")
            if estimate.get("funding_rate") is not None:
                ts = epoch(estimate.get("computed_time"))
                estimate_available = available_epoch(estimate_retrieved)
                rate = _decimal(estimate["funding_rate"], positive=False, signed=True)
                if ts > estimate_available or abs(Decimal(rate)) > 1:
                    raise MarketDataError("invalid_data", "Kalshi returned an invalid provisional funding estimate.")
                item = {"kind": "funding_estimate", "ts": ts, "available_at": estimate_available,
                        "funding_rate": rate, "next_funding_ts": epoch(estimate.get("next_funding_time")),
                        "retrieved_at": estimate_retrieved}
                if estimate.get("mark_price") is not None:
                    item["mark_price"] = _decimal(estimate["mark_price"])
                output.append(item)
        except MarketDataError as exc:
            errors.append(exc.code)
        return output, {"status": "partial" if errors else "complete" if output else "empty",
                        "row_count": len(output), "error_codes": errors,
                        "provenance": "current observations become available at retrieval only"}
