"""Authenticated Kalshi DEMO-environment execution client.

The order-placing sibling of ``app/kalshi_dev.py`` (which is read-only, public,
unauthenticated candlestick GETs). This one SIGNS with a user's own demo
(sandbox) API key and places / cancels test orders and reads fills on Kalshi's
demo exchange. It is NOT real money, but it is built with live-path care.

HARD HOST ISOLATION (security-critical). Every request goes through
``_require_demo_host``: it talks ONLY to a Kalshi demo/sandbox host and REFUSES
to send anything to the production exchange (api.elections.kalshi.com,
trading-api.kalshi.com, api.kalshi.com) or any host that is not clearly a
sandbox. There is NO code path from here to the production host or to the house
/ production key:

  * The base URL is validated on every call and defaults to the public demo host.
  * ``kalshi_auth_headers`` is only ever called WITH the per-user dev credentials,
    so signing never falls back to the env house key (that fallback is what
    ``credentials=None`` would trigger, and ``_require_creds`` forbids it).

It mirrors the live kernel path (``app.engine.live_kernel_factory`` ->
``MarketableLimitKernel``): ``demo_order_submitter`` is the demo twin of
``kalshi_account.order_submitter`` and ``demo_kernel_factory`` the twin of
``live_kernel_factory``, so the engine's demo-mode tick can consume a kernel
with the identical ``execute(TradeIntent) -> ExecutionReport`` interface.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Callable, Dict, Optional
from urllib.parse import urlparse

import requests

from app import repository as repo
from app.execution.refusal import OrderRefused, definite_refusal
from data_pipeline.architecture.execution_kernel import order_wire_params
from data_pipeline.common import KalshiCredentials, kalshi_auth_headers

# Kalshi demo base — same default and env var as the read-only app.kalshi_dev
# client. Already ends with /trade-api/v2, so endpoints below are relative to it.
KALSHI_DEV_API_BASE = os.getenv("KALSHI_DEV_API_BASE", "https://demo-api.kalshi.co/trade-api/v2").rstrip("/")

_ORDER_ENDPOINT = "/portfolio/events/orders"   # matches live ORDER_PATH tail
_CANCEL_ENDPOINT = "/portfolio/orders/%s"
_FILLS_ENDPOINT = "/portfolio/fills"

ORDER_TIME_IN_FORCE = os.getenv("KALSHI_ORDER_TIF", "immediate_or_cancel")

# Hosts this client must NEVER send an order to — the production exchange.
_PRODUCTION_HOSTS = ("api.elections.kalshi.com", "trading-api.kalshi.com", "api.kalshi.com")


class DemoHostError(RuntimeError):
    """The configured base URL is not a Kalshi demo/sandbox host, or no dev key
    was supplied. Raised BEFORE any network call, so a misconfig can never leak
    a demo order onto the real exchange or sign with the house key."""


def _require_demo_host(base_url: str) -> str:
    """Refuse anything that is not plainly a Kalshi demo/sandbox host."""
    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        raise DemoHostError("No host in Kalshi demo base URL %r" % (base_url,))
    if host in _PRODUCTION_HOSTS:
        raise DemoHostError("Refusing to send a demo order to the PRODUCTION host %r" % (host,))
    if "demo" not in host and "sandbox" not in host:
        raise DemoHostError("Refusing: %r is not a Kalshi demo/sandbox host" % (host,))
    return base_url


def _require_creds(credentials: Optional[KalshiCredentials]) -> KalshiCredentials:
    """The dev key is mandatory: never let signing fall back to the house key."""
    if not credentials:
        raise DemoHostError("Demo execution requires the user's own DEV key; no house-key fallback.")
    return credentials


def _signing_path(base_url: str, endpoint: str) -> str:
    """Full URL path Kalshi signs over (e.g. /trade-api/v2/portfolio/...)."""
    return (urlparse(base_url).path or "").rstrip("/") + endpoint


def demo_place_limit_order(
    ticker: str, action: str, side: str, qty: int, price_dollars: float,
    credentials: KalshiCredentials, base_url: Optional[str] = None, timeout: int = 20,
    client_order_id: Optional[str] = None,
) -> Dict:
    """Submit one limit order to the DEMO exchange, signed with the dev key.

    Same body/semantics as data_pipeline.live_trading_engine.place_limit_order
    (YES-leg bid/ask wire via order_wire_params, so a NO order is sent as its YES
    complement; 1c..99c, IOC), so DummyExecutionKernel parses the returned ``resp``
    identically. Reimplemented here rather than reused because the live helper is
    bound to the production host via common.api_post_auth — isolation, not
    duplication. The host guard above is untouched: demo stays sandbox-only."""
    base = _require_demo_host(base_url or KALSHI_DEV_API_BASE)
    creds = _require_creds(credentials)
    if str(side).lower() not in ("yes", "no"):
        raise ValueError("side must be yes or no, got side=%r" % (side,))
    if str(action).lower() not in ("buy", "sell"):
        raise ValueError("action must be buy or sell, got %r" % (action,))
    v2_side, wire_price = order_wire_params(action, side, price_dollars)
    cents = max(1, min(99, int(round(float(wire_price) * 100))))
    client_order_id = client_order_id or str(uuid.uuid4())  # persisted+reused on retry (P0-1)
    body = {
        "ticker": ticker,
        "side": v2_side,
        "count": "%d.00" % int(qty),
        "price": "%.4f" % (cents / 100.0),
        "time_in_force": ORDER_TIME_IN_FORCE,
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": client_order_id,
    }
    # Execution P2: same additive timing breakdown as the live path (sign_ms / net_ms / http_status),
    # measured around the existing calls so demo and live report latency identically.
    _t0 = time.perf_counter()
    headers = kalshi_auth_headers("POST", _signing_path(base, _ORDER_ENDPOINT), creds)
    _t1 = time.perf_counter()
    resp = requests.post(base + _ORDER_ENDPOINT, json=body, headers=headers, timeout=timeout)
    _t2 = time.perf_counter()
    timing = {"sign_ms": (_t1 - _t0) * 1000.0, "net_ms": (_t2 - _t1) * 1000.0, "http_status": resp.status_code}
    if resp.status_code >= 400:
        message = "demo POST %s failed %d: %s" % (_ORDER_ENDPOINT, resp.status_code, resp.text[:400])
        # A definite refusal (no order created, e.g. insufficient_balance) says so, so the engine can
        # settle its intent as unfilled; anything else (5xx, 409, 429, ...) stays an unknown outcome.
        refusal = definite_refusal(resp.status_code, resp.text, client_order_id)
        if refusal is not None:
            raise OrderRefused(message, refusal)
        raise RuntimeError(message)
    return {"client_order_id": client_order_id, "body": body, "resp": resp.json(), "timing": timing}


def demo_cancel_order(order_id: str, credentials: KalshiCredentials,
                      base_url: Optional[str] = None, timeout: int = 20) -> Dict:
    """Cancel a resting demo order by id."""
    base = _require_demo_host(base_url or KALSHI_DEV_API_BASE)
    creds = _require_creds(credentials)
    endpoint = _CANCEL_ENDPOINT % order_id
    headers = kalshi_auth_headers("DELETE", _signing_path(base, endpoint), creds)
    resp = requests.delete(base + endpoint, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError("demo DELETE %s failed %d: %s" % (endpoint, resp.status_code, resp.text[:400]))
    return resp.json()


def demo_fills(credentials: KalshiCredentials, ticker: Optional[str] = None,
               base_url: Optional[str] = None, timeout: int = 20) -> Dict:
    """Read this account's demo fills (optionally one ticker)."""
    base = _require_demo_host(base_url or KALSHI_DEV_API_BASE)
    creds = _require_creds(credentials)
    params = {"ticker": ticker} if ticker else None
    headers = kalshi_auth_headers("GET", _signing_path(base, _FILLS_ENDPOINT), creds)
    resp = requests.get(base + _FILLS_ENDPOINT, params=params, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError("demo GET %s failed %d: %s" % (_FILLS_ENDPOINT, resp.status_code, resp.text[:400]))
    return resp.json()


def demo_balance_dollars(credentials: KalshiCredentials, base_url: Optional[str] = None, timeout: int = 15) -> float:
    """This account's demo (play-money) cash balance in dollars. Read-only, host-isolated."""
    base = _require_demo_host(base_url or KALSHI_DEV_API_BASE)
    creds = _require_creds(credentials)
    endpoint = "/portfolio/balance"
    headers = kalshi_auth_headers("GET", _signing_path(base, endpoint), creds)
    resp = requests.get(base + endpoint, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError("demo GET %s failed %d: %s" % (endpoint, resp.status_code, resp.text[:400]))
    return float(resp.json().get("balance") or 0) / 100.0


def demo_positions(credentials: KalshiCredentials, base_url: Optional[str] = None, timeout: int = 20) -> Dict[str, int]:
    """This account's open demo positions: ticker -> signed net contracts (+ YES, - NO; buying NO is
    a short YES leg on Kalshi). Read-only and host-isolated; follows the cursor across pages."""
    base = _require_demo_host(base_url or KALSHI_DEV_API_BASE)
    creds = _require_creds(credentials)
    endpoint = "/portfolio/positions"
    out: Dict[str, int] = {}
    cursor = None
    for _page in range(50):
        params = {"limit": 1000, **({"cursor": cursor} if cursor else {})}
        headers = kalshi_auth_headers("GET", _signing_path(base, endpoint), creds)
        resp = requests.get(base + endpoint, params=params, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError("demo GET %s failed %d: %s" % (endpoint, resp.status_code, resp.text[:400]))
        body = resp.json()
        for p in body.get("market_positions") or []:
            net = int(float(p.get("position_fp") or p.get("position") or 0))
            if net:
                out[p["ticker"]] = net
        cursor = body.get("cursor")
        if not cursor:
            return out
    raise RuntimeError("demo GET %s: too many pages" % endpoint)


def demo_orders(credentials: KalshiCredentials, ticker: Optional[str] = None,
                base_url: Optional[str] = None, timeout: int = 20, params: Optional[Dict] = None) -> Dict:
    """Read this account's demo orders (optionally one ticker) — used by crash-recovery to find an
    in-flight order by its client_order_id. Host-isolated like every call here (demo/sandbox only)."""
    base = _require_demo_host(base_url or KALSHI_DEV_API_BASE)
    creds = _require_creds(credentials)
    endpoint = "/portfolio/orders"
    params = dict(params or {})
    if ticker:
        params["ticker"] = ticker
    params = params or None
    headers = kalshi_auth_headers("GET", _signing_path(base, endpoint), creds)
    resp = requests.get(base + endpoint, params=params, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError("demo GET %s failed %d: %s" % (endpoint, resp.status_code, resp.text[:400]))
    return resp.json()


def demo_net_reader(credentials: KalshiCredentials, base_url: Optional[str] = None):
    """``read_net`` for PositionGuard against the DEMO exchange: ticker -> signed net
    (+ YES, - NO). Demo twin of position_guard.exchange_net_reader, host-isolated."""
    from data_pipeline.architecture.position_guard import net_from_positions_response

    base = _require_demo_host(base_url or KALSHI_DEV_API_BASE)
    creds = _require_creds(credentials)
    endpoint = "/portfolio/positions"

    def read(ticker: str) -> int:
        headers = kalshi_auth_headers("GET", _signing_path(base, endpoint), creds)
        resp = requests.get(base + endpoint, params={"ticker": ticker}, headers=headers, timeout=5)
        if resp.status_code >= 400:
            raise RuntimeError("demo GET %s failed %d: %s" % (endpoint, resp.status_code, resp.text[:400]))
        return net_from_positions_response(resp.json(), ticker)

    return read


def demo_order_submitter(credentials: KalshiCredentials, base_url: Optional[str] = None):
    """Submitter for MarketableLimitKernel, signing demo orders as this user.
    Demo twin of kalshi_account.order_submitter."""
    creds = _require_creds(credentials)

    def submit(ticker: str, action: str, side: str, qty: int, price: float,
               client_order_id: Optional[str] = None) -> dict:
        return demo_place_limit_order(ticker, action, side, qty, price, credentials=creds,
                                      base_url=base_url, client_order_id=client_order_id)

    return submit


def demo_kernel_factory(conn, ws_feed=None) -> Callable[[int], object]:
    """user_id -> MarketableLimitKernel that places DEMO orders signed with that
    user's own dev key. Demo twin of app.engine.live_kernel_factory; reuses the
    same kernel class and the same AES-GCM-per-user decryption (credentials_from_row),
    so the only thing that changes is the key (dev) and the host (demo).

    `ws_feed` (the shared WsTickerFeed) makes pricing read the live websocket book first with REST
    as the freshness backstop (P1-1); None => REST-only, as before. Demo places REAL sandbox orders,
    so it passes the same execution guards as live (P1-3), with the same limits and kill switch, on
    an instance of its own: a refused demo order never opens live's circuit breaker."""
    from app import kalshi_account
    from app.execution import demo_guarded_submitter, timed_submitter
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
    from data_pipeline.architecture.position_guard import position_guarded_submitter
    from data_pipeline.market_data import MarketFeed

    _require_demo_host(KALSHI_DEV_API_BASE)  # fail fast if the demo host is misconfigured
    feed = MarketFeed(ws_feed=ws_feed)

    def make(user_id: int):
        row = repo.get_kalshi_dev_key(conn.cursor(), user_id)
        if row is None:
            return None
        creds = kalshi_account.credentials_from_row(user_id, row)
        return MarketableLimitKernel(
            timed_submitter(demo_guarded_submitter(position_guarded_submitter(
                demo_order_submitter(creds), demo_net_reader(creds))), mode="demo"), feed,
            entry_cross_ticks=int(os.getenv("KALSHI_ENTRY_CROSS_TICKS", "2")),
            exit_cross_ticks=int(os.getenv("KALSHI_EXIT_CROSS_TICKS", "2")),
            max_entry_slippage=float(os.getenv("KALSHI_MAX_ENTRY_SLIPPAGE", "0.10")),
            max_attempts=int(os.getenv("KALSHI_ORDER_MAX_ATTEMPTS", "3")),
            max_quote_age_seconds=float(os.getenv("KALSHI_MAX_QUOTE_AGE_SECONDS", "2.0")),
        )

    return make
