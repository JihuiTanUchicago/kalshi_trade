"""Isolated native BTC-perps transport using one user's in-memory RSA key.

No database access, environment credentials, binary endpoints, or retry of writes.
The calling service owns approval, freshness, per-user locking and reconciliation.
Native USD-per-contract prices and contract quantities remain decimal strings.
"""
from __future__ import annotations

import base64
import copy
import json
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Callable
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.adapters.kalshi_perps.kalshi_perps_data import BASE_URLS, Config, normalize_instrument, ticker_checked
from app.adapters.data.market_data_common import MarketDataError

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_PAGES = 20
MAX_ROWS = 10_000
MAX_LEVELS = 1000
MAX_REQUEST_SECONDS = 15
MAX_PAGINATION_SECONDS = 30
_FIXED = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_ORDER_FIELDS = frozenset({
    "client_order_id", "ticker", "side", "count", "price", "time_in_force",
    "self_trade_prevention_type", "post_only", "cancel_order_on_pause",
    "reduce_only", "subaccount", "market_version",
})


class Error(ValueError):
    """Safe failure classification; messages never contain provider bodies/keys."""

    def __init__(self, code: str, message: str, status: int | None = None, *,
                 rejected: bool = False, uncertain: bool = False) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.rejected, self.uncertain = rejected, uncertain


def _invalid(*, uncertain: bool = False, status: int | None = None) -> Error:
    return Error("invalid_response", "Kalshi returned an invalid perpetual response.",
                 status, uncertain=uncertain)


def _identifier(value: Any, *, empty: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > 256 or (not value and not empty)
            or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise ValueError()
    return value


def _order_id(value: Any) -> str:
    # Valid URL-segment subset, without imposing an undocumented UUID format.
    value = _identifier(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError()
    return value


def _number(value: Any, *, positive: bool = False, nonnegative: bool = False) -> str:
    # Precision/encoding bounds limit parsing work, not account leverage/notional.
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError()
    text = str(value)
    if len(text) > 128:
        raise ValueError()
    try:
        number = Decimal(text)
        if (not number.is_finite() or abs(number.as_tuple().exponent) > 128
                or positive and number <= 0 or nonnegative and number < 0):
            raise ValueError()
        return format(number, "f")
    except (InvalidOperation, OverflowError):
        raise ValueError() from None


def _integer(value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError()
    return value


def _json_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


class Client:
    """Short-lived, single-user, primary-subaccount native REST client."""

    def __init__(self, credentials: tuple, environment: str = "production",
                 proxy_url: str | None = None, *, session: Any = None,
                 clock: Callable = time.time, monotonic: Callable = time.monotonic) -> None:
        try:
            Config(True, environment, proxy_url=proxy_url)
            if not isinstance(credentials, tuple) or len(credentials) != 2:
                raise ValueError()
            key_id, key = credentials
            _identifier(key_id)
            if not isinstance(key, RSAPrivateKey):
                raise ValueError()
        except (ValueError, TypeError, MarketDataError):
            raise Error("invalid_configuration", "A user's RSA credentials and a fixed perps environment are required.",
                        rejected=True) from None
        self.environment, self._proxy_url = environment, proxy_url
        self._key_id, self._key = key_id, key
        self._session = session if session is not None else requests.Session()
        self._clock, self._monotonic = clock, monotonic
        self._closed = False
        self._response_bytes = 0
        self._instruments: dict[str, tuple[dict, float]] = {}
        self._isolate_session()
        if isinstance(self._session, requests.Session):
            # An injected session must not bring an adapter that retries POSTs.
            for adapter in self._session.adapters.values():
                adapter.close()
            self._session.adapters.clear()
            self._session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))

    def __enter__(self) -> "Client":
        if self._closed:
            raise Error("closed", "The perpetual client is closed.", rejected=True)
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            try:
                self._session.close()
            finally:
                self._closed = True
                self._key_id = self._key = None
                self._instruments.clear()

    def _isolate_session(self) -> None:
        self._session.trust_env = False
        # Also clear injected requests sessions and cookies received since last call.
        for name in ("headers", "params", "cookies", "proxies"):
            value = getattr(self._session, name, None)
            if value is not None:
                value.clear()
        self._session.auth = None
        self._session.hooks = {"response": []}
        self._session.cert = None
        self._session.verify = True

    def _now(self) -> float:
        value = self._clock()
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError()
            value = value.timestamp()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError()
        return value

    def _headers(self, method: str, path: str, private: bool) -> dict:
        headers = {"Accept": "application/json"}
        if private:
            try:
                timestamp = str(int(self._now() * 1000))
                message = (timestamp + method + "/trade-api/v2" + path).encode("utf-8")
                signature = self._key.sign(message, padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                    hashes.SHA256())
            except Exception:
                raise Error("signing_failed", "The user's perpetual request could not be signed.",
                            rejected=True) from None
            headers.update({"KALSHI-ACCESS-KEY": self._key_id,
                            "KALSHI-ACCESS-TIMESTAMP": timestamp,
                            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("ascii")})
        return headers

    @staticmethod
    def _allowed(method: str, path: str, private: bool) -> bool:
        if method == "GET":
            if private:
                return path in {"/margin/enabled", "/margin/balance", "/margin/risk",
                                "/margin/notional_risk_limit", "/margin/fee_tiers",
                                "/account/limits/perps", "/margin/orders", "/margin/positions",
                                "/margin/fills"} or bool(re.fullmatch(r"/margin/orders/[A-Za-z0-9_-]+", path))
            return path in {"/margin/exchange/status", "/margin/markets"} or bool(
                re.fullmatch(r"/margin/markets/[A-Za-z0-9_-]+(?:/orderbook)?", path))
        return private and (method == "POST" and path == "/margin/orders" or
                            method == "DELETE" and bool(re.fullmatch(r"/margin/orders/[A-Za-z0-9_-]+", path)))

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 body: dict | None = None, private: bool = True) -> dict:
        if self._closed:
            raise Error("closed", "The perpetual client is closed.", rejected=True)
        if not self._allowed(method, path, private):
            raise Error("invalid_request", "Only the dedicated native perpetual endpoints are allowed.", rejected=True)
        mutation = method != "GET"
        response, status = None, None
        started = self._monotonic()
        try:
            self._isolate_session()
            headers = self._headers(method, path, private)
            data = None
            if body is not None:
                headers["Content-Type"] = "application/json"
                data = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
                if len(data.encode("utf-8")) > 4096:
                    raise Error("invalid_order", "The perpetual order body is too large.", rejected=True)
            # Exactly one attempt, including mutations; no generic retry adapter.
            response = self._session.request(
                method, BASE_URLS[self.environment] + path, params=params or {}, data=data,
                headers=headers, timeout=(3.05, 8), allow_redirects=False, stream=True,
                auth=(), cookies={}, proxies={"https": self._proxy_url} if self._proxy_url else {},
                verify=True)
            status = response.status_code
            expected = 201 if method == "POST" else 200
            if status != expected:
                # A definite client rejection cannot have created this order. All
                # other mutation outcomes remain unknown, including redirects/429.
                rejected = mutation and status in {400, 401, 403, 404, 422} and not (method == "DELETE" and status == 404)
                code = {401: "authentication_failed", 403: "access_denied", 409: "conflict",
                        429: "rate_limited"}.get(status, "provider_rejected" if rejected else "provider_unavailable")
                raise Error(code, "Kalshi did not accept the perpetual request (HTTP %d)." % status,
                            status, rejected=rejected, uncertain=mutation and not rejected)
            encoded = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                if self._monotonic() - started > MAX_REQUEST_SECONDS:
                    raise ValueError()
                encoded.extend(chunk)
                if len(encoded) > MAX_RESPONSE_BYTES:
                    raise ValueError()
            self._response_bytes = len(encoded)
            payload = json.loads(encoded, parse_float=Decimal, object_pairs_hook=_json_object,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(payload, dict):
                raise ValueError()
            retrieved = datetime.fromtimestamp(self._now(), timezone.utc).isoformat().replace("+00:00", "Z")
            return {**payload, "environment": self.environment, "retrieved_at": retrieved}
        except Error:
            raise
        except requests.RequestException:
            raise Error("provider_unavailable", "Kalshi perpetual connectivity could not be confirmed.",
                        status, uncertain=mutation) from None
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            raise _invalid(uncertain=mutation, status=status) from None
        finally:
            if response is not None:
                try:
                    response.close()
                except (requests.RequestException, OSError):
                    # A cleanup failure cannot erase an already parsed receipt.
                    pass

    @staticmethod
    def _shape(payload: dict, check: Callable, *, mutation: bool = False) -> dict:
        try:
            check(payload)
        except (ValueError, TypeError, KeyError, InvalidOperation, MarketDataError):
            raise _invalid(uncertain=mutation, status=201 if mutation else 200) from None
        return payload

    def enabled_status(self) -> dict:
        def check(p):
            if not isinstance(p["enabled"], bool):
                raise ValueError()
        return self._shape(self._request("GET", "/margin/enabled"), check)

    def exchange_status(self) -> dict:
        def check(p):
            if any(not isinstance(p[k], bool) for k in ("exchange_active", "trading_active")):
                raise ValueError()
        return self._shape(self._request("GET", "/margin/exchange/status", private=False), check)

    def market(self, ticker: str | None = None) -> dict:
        try:
            if ticker is not None:
                ticker_checked(ticker)
                payload = self._request("GET", "/margin/markets/" + ticker, private=False)
                instrument = normalize_instrument(payload["market"], self.environment, payload["retrieved_at"])
                if instrument["ticker"] != ticker:
                    raise ValueError()
            else:
                payload = self._request("GET", "/margin/markets", private=False)
                rows = payload["markets"]
                if (not isinstance(rows, list) or len(rows) > 1000 or payload.get("cursor")
                        or payload.get("next_cursor")):
                    raise ValueError()
                matches = []
                for row in rows:
                    try:
                        matches.append(normalize_instrument(row, self.environment, payload["retrieved_at"]))
                    except MarketDataError as exc:
                        if exc.code != "not_bitcoin":
                            raise
                if len(matches) != 1:
                    raise Error("market_unavailable", "Discovery requires one verified native Bitcoin perpetual market.")
                instrument = matches[0]
            self._instruments[instrument["ticker"]] = (instrument, self._monotonic())
            return copy.deepcopy(instrument)
        except (ValueError, KeyError, TypeError, MarketDataError) as exc:
            if isinstance(exc, Error):
                raise
            raise Error("invalid_market", "Verified native Bitcoin perpetual metadata is unavailable.") from None

    instrument = market

    def _instrument(self, ticker: str) -> dict:
        try:
            ticker_checked(ticker)
        except MarketDataError:
            raise Error("invalid_market", "A native Bitcoin perpetual ticker is required.", rejected=True) from None
        cached = self._instruments.get(ticker)
        return cached[0] if cached and self._monotonic() - cached[1] <= 5 else self.market(ticker)

    def orderbook(self, ticker: str) -> dict:
        self._instrument(ticker)
        def check(p):
            book = p["orderbook"]
            if not isinstance(book, dict):
                raise ValueError()
            for side in ("bids", "asks"):
                levels = book[side]
                if not isinstance(levels, list) or len(levels) > MAX_LEVELS:
                    raise ValueError()
                seen = set()
                for level in levels:
                    if not isinstance(level, list) or len(level) != 2:
                        raise ValueError()
                    level[0], level[1] = _number(level[0], positive=True), _number(level[1], positive=True)
                    price = Decimal(level[0])
                    if price in seen:
                        raise ValueError()
                    seen.add(price)
            if book["bids"] and book["asks"] and max(Decimal(x[0]) for x in book["bids"]) > min(Decimal(x[0]) for x in book["asks"]):
                raise ValueError()
        return self._shape(self._request("GET", "/margin/markets/" + ticker + "/orderbook",
                                         params={"depth": 100}, private=False), check)

    def balance(self) -> dict:
        def check(p):
            rows = p["subaccount_balances"]
            if not isinstance(rows, list) or len(rows) > 64:
                raise ValueError()
            accounts = set()
            for row in rows:
                sub = _integer(row["subaccount"])
                if sub in accounts:
                    raise ValueError()
                accounts.add(sub)
                for name in ("position_value", "account_equity", "available_balance", "maintenance_margin",
                             "initial_margin", "resting_orders_margin"):
                    row[name] = _number(row[name], nonnegative=name.endswith("margin"))
            if 0 not in accounts:
                raise ValueError()
            p["settled_funds"] = _number(p["settled_funds"])
            p["available_balance_computed"] = True
        return self._shape(self._request("GET", "/margin/balance",
                                         params={"compute_available_balance": "true"}), check)

    def risk(self) -> dict:
        def check(p):
            for key in ("account_leverage", "total_position_notional", "total_maintenance_margin"):
                p[key] = _number(p[key], nonnegative=True)
            rows = p["positions"]
            if not isinstance(rows, list) or len(rows) > MAX_ROWS:
                raise ValueError()
            for row in rows:
                _integer(row["subaccount"])
                ticker_checked(row["market_ticker"])
                for key in ("position", "mark_price", "position_notional", "maintenance_margin_required",
                            "position_leverage", "estimated_liquidation_price"):
                    if row.get(key) is not None:
                        row[key] = _number(row[key])
        return self._shape(self._request("GET", "/margin/risk"), check)

    def notional_risk_limit(self) -> dict:
        def check(p):
            for key in ("default_notional_value_risk_limit", "total_current_usage"):
                p[key] = _number(p[key], nonnegative=True)
            for key in ("member_notional_value_risk_limit", "effective_account_notional_value_risk_limit"):
                if p.get(key) is not None:
                    p[key] = _number(p[key], nonnegative=True)
            for key in ("notional_value_risk_limits_by_market_ticker", "current_usage_by_market_ticker"):
                mapping = p[key]
                if not isinstance(mapping, dict) or len(mapping) > MAX_ROWS:
                    raise ValueError()
                for ticker, value in mapping.items():
                    ticker_checked(ticker)
                    mapping[ticker] = _number(value, nonnegative=True)
        return self._shape(self._request("GET", "/margin/notional_risk_limit"), check)

    def fee_tiers(self) -> dict:
        def check(p):
            for key in ("maker_fee_rates", "taker_fee_rates"):
                mapping = p[key]
                if not isinstance(mapping, dict) or len(mapping) > MAX_ROWS:
                    raise ValueError()
                for ticker, value in mapping.items():
                    ticker_checked(ticker)
                    mapping[ticker] = _number(value)
        return self._shape(self._request("GET", "/margin/fee_tiers"), check)

    def api_limits(self) -> dict:
        def check(p):
            _identifier(p["usage_tier"])
            for key in ("read", "write"):
                for field in ("refill_rate", "bucket_capacity"):
                    _integer(p[key][field], minimum=1)
        return self._shape(self._request("GET", "/account/limits/perps"), check)

    @staticmethod
    def _order_row(row: dict) -> None:
        _order_id(row["order_id"])
        ticker_checked(row["ticker"])
        if row["side"] not in {"bid", "ask"}:
            raise ValueError()
        for key in ("price", "fill_count", "remaining_count"):
            row[key] = _number(row[key], nonnegative=True)
        if row.get("client_order_id") is not None:
            _identifier(row["client_order_id"], empty=True)
        for field in ("subaccount", "subaccount_number"):
            if field in row and _integer(row[field]) != 0:
                raise ValueError()

    def positions(self, ticker: str | None = None) -> dict:
        params = {"subaccount": 0}
        if ticker is not None:
            self._instrument(ticker)
            params["ticker"] = ticker
        def check(p):
            rows = p["positions"]
            if not isinstance(rows, list) or len(rows) > MAX_ROWS or p.get("cursor") or p.get("next_cursor"):
                raise ValueError()
            for row in rows:
                if _integer(row["subaccount"]) != 0 or ticker is not None and row["market_ticker"] != ticker:
                    raise ValueError()
                ticker_checked(row["market_ticker"])
                row["position"] = _number(row["position"])
                for key in ("entry_price", "unrealized_pnl", "fees", "margin_used", "roe"):
                    if row.get(key) is not None:
                        row[key] = _number(row[key])
        return self._shape(self._request("GET", "/margin/positions", params=params), check)

    def _pages(self, path: str, key: str, params: dict, validate: Callable) -> dict:
        output, seen_cursors, identities, total_bytes = [], set(), {}, 0
        started = self._monotonic()
        for _ in range(MAX_PAGES):
            payload = self._request("GET", path, params=params)
            total_bytes += self._response_bytes
            try:
                rows, cursor = payload[key], payload["cursor"]
                if (not isinstance(rows, list) or len(rows) > params["limit"]
                        or not isinstance(cursor, str) or len(cursor) > 2048
                        or payload.get("next_cursor")):
                    raise ValueError()
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError()
                    validate(row)
                    identity = row["order_id" if key == "orders" else "fill_id"]
                    if identity in identities:
                        # An evolving/overlapping read is not a complete snapshot.
                        raise ValueError()
                    identities[identity] = True
                    output.append(row)
                if total_bytes > MAX_PAGE_BYTES or len(output) > MAX_ROWS or self._monotonic() - started > MAX_PAGINATION_SECONDS:
                    raise ValueError()
                if not cursor:
                    return {key: output, "cursor": "", "complete": True,
                            "environment": self.environment, "retrieved_at": payload["retrieved_at"]}
                if cursor in seen_cursors:
                    raise ValueError()
                seen_cursors.add(cursor)
                params = {**params, "cursor": cursor}
            except (ValueError, TypeError, KeyError, MarketDataError):
                raise Error("incomplete_state", "Kalshi perpetual pagination did not yield a complete account read.") from None
        raise Error("incomplete_state", "Kalshi perpetual pagination exceeded its bounded page limit.")

    def orders(self, ticker: str | None = None, min_ts: int | None = None) -> dict:
        params = {"subaccount": 0, "limit": 1000}
        if ticker is not None:
            self._instrument(ticker)
            params["ticker"] = ticker
        try:
            if min_ts is not None:
                params["min_ts"] = _integer(min_ts)
        except ValueError:
            raise Error("invalid_request", "A valid order-history timestamp is required.", rejected=True) from None
        def check(row):
            self._order_row(row)
            if ticker is not None and row["ticker"] != ticker:
                raise ValueError()
            for field in ("subaccount", "subaccount_number"):
                if field in row and _integer(row[field]) != 0:
                    raise ValueError()
        return self._pages("/margin/orders", "orders", params, check)

    def fills(self, min_ts: int) -> dict:
        try:
            minimum = _integer(min_ts)
        except ValueError:
            raise Error("invalid_request", "A valid fill-history timestamp is required.", rejected=True) from None
        def check(row):
            _identifier(row["fill_id"])
            _order_id(row["order_id"])
            ticker_checked(row["ticker"])
            if row["side"] not in {"bid", "ask"}:
                raise ValueError()
            for key in ("price", "count", "fees"):
                row[key] = _number(row[key], positive=key in {"price", "count"})
            for key in ("entry_price", "realized_pnl"):
                if row.get(key) is not None:
                    row[key] = _number(row[key])
            for field in ("subaccount", "subaccount_number"):
                if field in row and _integer(row[field]) != 0:
                    raise ValueError()
        return self._pages("/margin/fills", "fills", {"subaccount": 0, "min_ts": minimum, "limit": 1000}, check)

    def order(self, order_id: str) -> dict:
        try:
            encoded = quote(_order_id(order_id), safe="")
        except ValueError:
            raise Error("invalid_request", "A valid native perpetual order ID is required.", rejected=True) from None
        def check(p):
            self._order_row(p["order"])
            if p["order"]["order_id"] != order_id:
                raise ValueError()
        return self._shape(self._request("GET", "/margin/orders/" + encoded, params={"subaccount": 0}), check)

    def submit_order(self, body: dict) -> dict:
        try:
            if not isinstance(body, dict) or set(body) != _ORDER_FIELDS:
                raise ValueError()
            # Freeze at entry, before metadata I/O can yield to another caller.
            body = copy.deepcopy(body)
            client_id = _identifier(body["client_order_id"])
            if str(uuid.UUID(client_id)) != client_id:
                raise ValueError()
            ticker_checked(body["ticker"])
            if (body["side"] not in {"bid", "ask"}
                    or body["time_in_force"] != "immediate_or_cancel"
                    or body["self_trade_prevention_type"] != "taker_at_cross"
                    or body["post_only"] is not False or body["cancel_order_on_pause"] is not True
                    or not isinstance(body["reduce_only"], bool)
                    or type(body["subaccount"]) is not int or body["subaccount"] != 0):
                raise ValueError()
            if _integer(body["market_version"], minimum=1) > 2 ** 31 - 1:
                raise ValueError()
            for key in ("count", "price"):
                if not isinstance(body[key], str) or len(body[key]) > 128 or not _FIXED.fullmatch(body[key]):
                    raise ValueError()
                _number(body[key], positive=True)
            qty, price = Decimal(body["count"]), Decimal(body["price"])
            if qty != qty.to_integral_value():
                raise ValueError()
        except (ValueError, TypeError, MarketDataError, InvalidOperation):
            raise Error("invalid_order", "A fixed native BTC perpetual IOC order with whole contracts is required.", rejected=True) from None
        instrument = self._instrument(body["ticker"])
        with localcontext() as context:
            context.prec = 300
            if (body["market_version"] != instrument["market_version"]
                    or price % Decimal(instrument["tick_size"]) != 0):
                raise Error("stale_market", "Refresh the native perpetual market version and price tick before confirming.", rejected=True)
        payload = self._request("POST", "/margin/orders", body=body)
        def check(p):
            _order_id(p["order_id"])
            filled = Decimal(_number(p["fill_count"], nonnegative=True))
            remaining = Decimal(_number(p["remaining_count"], nonnegative=True))
            if filled > qty or remaining != 0 or p.get("client_order_id", client_id) != client_id:
                raise ValueError()
            if filled > 0:
                p["average_fill_price"] = _number(p["average_fill_price"], positive=True)
                p["average_fee_paid"] = _number(p["average_fee_paid"])
                with localcontext() as ctx:
                    ctx.prec = 300
                    average = Decimal(p["average_fill_price"])
                    if (filled % Decimal(instrument["quantity_step"]) != 0
                            or body["side"] == "bid" and average > price
                            or body["side"] == "ask" and average < price):
                        raise ValueError()
                    p["acknowledged_fee_total"] = format(filled * Decimal(p["average_fee_paid"]), "f")
            p["fill_count"], p["remaining_count"] = format(filled, "f"), format(remaining, "f")
        return self._shape(payload, check, mutation=True)

    def cancel_order(self, order_id: str) -> dict:
        try:
            encoded = quote(_order_id(order_id), safe="")
        except ValueError:
            raise Error("invalid_request", "A valid native perpetual order ID is required.", rejected=True) from None
        payload = self._request("DELETE", "/margin/orders/" + encoded, params={"subaccount": 0})
        try:
            if payload["order_id"] != order_id:
                raise ValueError()
            payload["reduced_by"] = _number(payload["reduced_by"], nonnegative=True)
        except (ValueError, TypeError, KeyError):
            raise _invalid(uncertain=True, status=200) from None
        return payload
