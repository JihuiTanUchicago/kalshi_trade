"""Small OAuth client for Alpaca's paper broker; no live endpoint or retries.

Account/risk checks and public DTOs belong to ``alpaca_paper``. A failed mutation
can have reached the broker: callers must reconcile its client ID before doing
anything else, never repeat the POST on a transport error.
"""
from __future__ import annotations

import json
import math
import re
import time
from decimal import Decimal, InvalidOperation

import requests
from requests.adapters import HTTPAdapter
from requests.sessions import Session as RequestsSession

PAPER_BASE_URL = "https://paper-api.alpaca.markets/v2"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_COLLECTION_ITEMS = 500
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?\Z")
_CLIENT_ID = re.compile(r"tau-paper-[a-f0-9]{32}\Z")
_ORDER_ID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z")
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")
_ORDER_FIELDS = frozenset({
    "symbol", "qty", "side", "type", "limit_price", "time_in_force",
    "extended_hours", "client_order_id",
})


class Error(ValueError):
    """Fixed, public-safe message; no upstream body or exception is retained."""

    def __init__(self, message: str, status: int = 400, *, ambiguous: bool = False,
                 not_found: bool = False, rejected: bool = False):
        super().__init__(message)
        self.status = status
        self.ambiguous = ambiguous
        self.not_found = not_found
        self.rejected = rejected


def _symbol(value) -> str:
    if not isinstance(value, str) or len(value) > 15:
        raise Error("Provide a supported US equity symbol.")
    value = value.strip().upper()
    if not _SYMBOL.fullmatch(value):
        raise Error("Provide a supported US equity symbol.")
    return value


def _client_order_id(value) -> str:
    if not isinstance(value, str) or not _CLIENT_ID.fullmatch(value):
        raise Error("Provide the original Tau paper order identifier.")
    return value


def _number(value, label: str) -> tuple[Decimal, str]:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise Error("Provide a valid " + label + ".")
    try:
        text = str(value)
        if len(text) > 40 or not _NUMBER.fullmatch(text):
            raise ValueError
        number = Decimal(text)
        if not number.is_finite() or not 0 < number <= Decimal("1000000000"):
            raise ValueError
    except (ValueError, TypeError, InvalidOperation):
        raise Error("Provide a valid " + label + ".") from None
    # Formatting preserves the exact decimal without the ambient Decimal
    # context rounding the value (which .normalize() could otherwise do).
    canonical = format(number, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return number, canonical


def normalize_order(body: dict) -> dict:
    """Return the exact narrow broker payload or refuse it before any HTTP.

    The asset's ``us_equity`` class, long-only position and capacity are checked
    by the service immediately before it claims and submits the order.
    """
    if not isinstance(body, dict) or set(body) != _ORDER_FIELDS:
        raise Error("Provide a simple whole-share paper limit order.")
    if (body["type"] != "limit" or body["time_in_force"] != "day"
            or body["extended_hours"] is not False or body["side"] not in ("buy", "sell")):
        raise Error("Paper orders support limit prices, day duration and regular hours only.")
    quantity, qty = _number(body["qty"], "whole-share quantity")
    if quantity != quantity.to_integral_value():
        raise Error("Paper orders require a positive whole-share quantity.")
    price, limit_price = _number(body["limit_price"], "limit price")
    decimals = len(limit_price.split(".", 1)[1]) if "." in limit_price else 0
    if decimals > (2 if price >= 1 else 4):
        raise Error("Limit prices allow two decimals at USD 1 or above and four below USD 1.")
    return {
        "symbol": _symbol(body["symbol"]), "qty": qty, "side": body["side"],
        "type": "limit", "limit_price": limit_price, "time_in_force": "day",
        "extended_hours": False, "client_order_id": _client_order_id(body["client_order_id"]),
    }


def _validate_shape(data) -> None:
    """Bound nested upstream JSON before returning private data to the service."""
    stack = [(data, 0)]
    visited = 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        if visited > 50000 or depth > 10:
            raise ValueError
        if isinstance(item, dict):
            if len(item) > 256 or any(not isinstance(k, str) or len(k) > 128 for k in item):
                raise ValueError
            stack.extend((value, depth + 1) for value in item.values())
        elif isinstance(item, list):
            if len(item) > MAX_COLLECTION_ITEMS:
                raise ValueError
            stack.extend((value, depth + 1) for value in item)
        elif isinstance(item, str):
            if len(item) > 16384:
                raise ValueError
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError
        elif item is not None and not isinstance(item, (bool, int)):
            raise ValueError


def _no_duplicate_keys(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


class Client:
    """Per-user OAuth access, pinned to the paper host even for dual grants."""

    def __init__(self, credentials: dict, environment: str = "paper", session=None):
        if environment != "paper":
            raise Error("Only an Alpaca paper account is supported.")
        if not isinstance(credentials, dict):
            raise Error("Reconnect your Alpaca paper account.", 401)
        token = credentials.get("access_token")
        scope = credentials.get("scope", "")
        if (not isinstance(token, str) or not token or len(token) > 16384
                or any(ord(c) < 33 or ord(c) > 126 for c in token)
                or not isinstance(credentials.get("token_type"), str)
                or credentials["token_type"].lower() != "bearer"
                or not isinstance(scope, str) or len(scope) > 200
                or any(ord(c) < 32 or ord(c) > 126 for c in scope)):
            raise Error("Reconnect your Alpaca paper account.", 401)
        self._expires_at = credentials.get("expires_at")
        self._validate_expiry()
        self._token = token
        self._scopes = frozenset(scope.split())
        self._closed = False
        self._owns_session = session is None
        self._session = requests.Session() if session is None else session
        if isinstance(self._session, RequestsSession):
            # Suppress netrc, proxy credentials and a caller's default API-key
            # headers; the only authorization sent is the per-user Bearer token.
            self._session.trust_env = False
            self._session.auth = None
            self._session.headers.clear()
            self._session.params.clear()
            self._session.proxies.clear()
            self._session.cookies.clear()
            self._session.mount("https://", HTTPAdapter(max_retries=0))

    def _validate_expiry(self) -> None:
        expiry = self._expires_at
        if expiry is None:
            return
        if (isinstance(expiry, bool) or not isinstance(expiry, (int, float))
                or (isinstance(expiry, float) and not math.isfinite(expiry))
                or expiry <= time.time()):
            raise Error("Reconnect your expired Alpaca paper account.", 401)

    def __enter__(self) -> Client:
        if self._closed:
            raise Error("The Alpaca paper connection is closed.", 503)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed and self._owns_session:
            self._session.close()
        self._closed = True
        self._token = ""

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 body: dict | None = None, collection_limit: int | None = None,
                 allow_not_found: bool = False):
        mutating = method in ("POST", "DELETE")
        if self._closed:
            raise Error("The Alpaca paper connection is closed.", 503)
        self._validate_expiry()
        if mutating and "trading" not in self._scopes:
            raise Error("Reconnect Alpaca paper with order authorization.", 403)
        response = None
        try:
            # One call only. No session retry adapter, redirects, dynamic host,
            # credential query parameters or environment endpoint overrides.
            response = self._session.request(
                method, PAPER_BASE_URL + path,
                headers={"Authorization": "Bearer " + self._token, "Accept": "application/json"},
                params=params, json=body, timeout=(5, 15), allow_redirects=False, stream=True,
                verify=True,
            )
            status = response.status_code
            expected = {204} if method == "DELETE" else ({200, 201} if method == "POST" else {200})
            if status == 404 and allow_not_found:
                return None
            if status not in expected:
                ambiguous = mutating and (status >= 500 or status in (408, 409) or 200 <= status < 400)
                rejected = method == "POST" and 400 <= status < 500 and not ambiguous
                if status == 401:
                    raise Error("Reconnect your Alpaca paper account.", 401, rejected=rejected)
                if status == 403:
                    raise Error("Alpaca did not authorize this paper request.", 403, rejected=rejected)
                if status == 404:
                    raise Error("This Alpaca paper order was not found.", 404,
                                not_found=True, rejected=rejected)
                if status == 429:
                    raise Error("Alpaca paper requests are temporarily rate limited.", 503, rejected=rejected)
                raise Error("Alpaca did not confirm this paper request.",
                            422 if 400 <= status < 500 and not ambiguous else 502,
                            ambiguous=ambiguous, rejected=rejected)
            if method == "DELETE":
                return None
            data = self._decode(response, ambiguous=mutating)
            valid = (isinstance(data, list) and len(data) <= collection_limit
                     and all(isinstance(item, dict) and item for item in data)) if collection_limit is not None else (
                         isinstance(data, dict) and bool(data))
            if not valid:
                raise Error("Alpaca returned an unreadable paper response.", 502, ambiguous=mutating)
            return data
        except requests.RequestException:
            raise Error("Alpaca paper trading is unavailable; check the order status before continuing.",
                        502, ambiguous=mutating) from None
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _decode(response, *, ambiguous: bool):
        try:
            length = response.headers.get("Content-Length")
            if length is not None and (not str(length).isdigit() or int(length) > MAX_RESPONSE_BYTES):
                raise ValueError
            content = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                if not isinstance(chunk, bytes) or len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ValueError
                content.extend(chunk)
            data = json.loads(content.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
            _validate_shape(data)
            return data
        except (ValueError, TypeError, RecursionError):
            raise Error("Alpaca returned an unreadable paper response.", 502, ambiguous=ambiguous) from None

    def account(self) -> dict:
        return self._request("GET", "/account")

    def positions(self) -> list:
        return self._request("GET", "/positions", collection_limit=MAX_COLLECTION_ITEMS)

    def orders(self, status: str = "open", limit: int = 500) -> list:
        if (status not in ("open", "closed", "all") or isinstance(limit, bool)
                or not isinstance(limit, int) or not 1 <= limit <= MAX_COLLECTION_ITEMS):
            raise Error("Choose an order status and a limit from 1 to 500.")
        return self._request("GET", "/orders", params={
            "status": status, "limit": limit, "direction": "desc", "nested": False,
        }, collection_limit=limit)

    def asset(self, symbol: str) -> dict:
        return self._request("GET", "/assets/" + _symbol(symbol))

    def get_order(self, client_order_id: str) -> dict | None:
        client_order_id = _client_order_id(client_order_id)
        data = self._request("GET", "/orders:by_client_order_id",
                             params={"client_order_id": client_order_id}, allow_not_found=True)
        if data is not None and data.get("client_order_id") != client_order_id:
            raise Error("Alpaca did not confirm the requested paper order.", 502)
        return data

    def submit_order(self, body: dict) -> dict:
        request = normalize_order(body)
        data = self._request("POST", "/orders", body=request)
        if (not isinstance(data.get("id"), str) or not _ORDER_ID.fullmatch(data["id"])
                or data.get("client_order_id") != request["client_order_id"]):
            raise Error("Alpaca did not confirm the submitted paper order; check its status.",
                        502, ambiguous=True)
        return data

    def cancel_order(self, order_id: str) -> None:
        if not isinstance(order_id, str) or not _ORDER_ID.fullmatch(order_id):
            raise Error("Provide a valid Alpaca paper order identifier.")
        self._request("DELETE", "/orders/" + order_id)
