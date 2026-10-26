"""Process-wide guards on the real-order path (EXECUTION_RISK_HARDENING P1-3).

``guarded_submitter`` wraps a kernel submitter so EVERY real exchange order passes four
backstops before it is sent. One invariant makes this safe to ADD without weakening any
existing guard: **a SELL is never blocked** — an exit must always be able to get flat.
Only new risk (a BUY) is ever gated, and a blocked BUY is reported as ``unfilled``, which
the kernel already handles (a missed entry costs nothing).

  * kill switch   — APP_KILL_SWITCH=1 (process env, needs a restart to change) OR the DB-backed
                    switch (kill_switch.py: `python -m app.execution.kill_switch on`, picked up by
                    every process within ~5s, no restart) halts all new BUYS.
  * fat-finger    — a BUY above a hard qty / notional ceiling, or off the 1c..99c grid, is
                    refused. A defence-in-depth ceiling WELL above any legitimate order; a
                    breach means a caller mis-sized, so it rejects loudly, never resizes.
  * rate limit    — at most N BUYS per rolling window, so a runaway loop can't machine-gun
                    the exchange (and trip our API key's own rate limit).
  * circuit break — after K consecutive submitter ERRORS the breaker opens for a cooldown,
                    refusing BUYS until it half-opens; SELLS keep trying throughout, and the
                    first success closes it again.

All limits are env-tunable; the numeric ones are read once at construction, the kill switch
every call. Live's guard is a single process-wide instance (counters/breaker are global state);
demo has its own, with the same limits and the same kill switch (``demo_guarded_submitter``), so
one venue's errors never open the other's breaker. Each is protected by one lock — the submitter
is called from the single engine tick thread, the lock is just belt-and-braces. ponytail: global lock, fine until the engine goes multi-threaded.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional

from app.execution.kill_switch import DbKillSwitch


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class OrderBlocked(Exception):
    """A BUY was refused by a guard. Not raised to callers (the wrapper returns an
    ``unfilled`` result instead); kept as the typed reason for logging/tests."""


class ExecutionGuard:
    """Shared state for the kill switch, rate limiter and error circuit breaker."""

    def __init__(
        self,
        max_qty: int,
        max_notional: float,
        rate_limit: int,
        rate_window_s: float,
        breaker_errors: int,
        breaker_cooldown_s: float,
        db_switch=None,
    ) -> None:
        self.max_qty = int(max_qty)
        self.max_notional = float(max_notional)
        self.rate_limit = int(rate_limit)
        self.rate_window_s = float(rate_window_s)
        self.breaker_errors = int(breaker_errors)
        self.breaker_cooldown_s = float(breaker_cooldown_s)
        self._db_switch = db_switch  # DbKillSwitch or None (env-only)
        self._lock = threading.Lock()
        self._buy_times: Deque[float] = deque()
        self._consec_errors = 0
        self._open_until = 0.0  # breaker open while monotonic() < this

    # -- read-only checks (caller holds no lock) ------------------------------
    def _kill_switch_on(self) -> bool:
        if os.getenv("APP_KILL_SWITCH") == "1":
            return True
        return self._db_switch is not None and self._db_switch.is_on()

    def _fat_finger_reason(self, qty: int, price: float) -> Optional[str]:
        if qty < 1:
            return "qty %d < 1" % qty
        if qty > self.max_qty:
            return "qty %d > max %d" % (qty, self.max_qty)
        if not (0.01 <= price <= 0.99):
            return "price %.4f off 1c..99c grid" % price
        if qty * price > self.max_notional + 1e-9:
            return "notional %.2f > max %.2f" % (qty * price, self.max_notional)
        return None

    # -- the wrapper ----------------------------------------------------------
    def wrap(self, submit: Callable[..., dict]) -> Callable[..., dict]:
        """Return a submitter with the guards applied. Same signature as the inner one."""

        def guarded(ticker: str, action: str, side: str, qty: int, price: float,
                    client_order_id: Optional[str] = None) -> dict:
            is_buy = str(action).lower() == "buy"
            if is_buy:
                reason = self._pre_buy_reason(int(qty), float(price), now=time.monotonic())
                if reason is not None:
                    print("[guard] BUY blocked (%s): %s %s %dx@%.4f" % (reason, ticker, side, qty, price),
                          flush=True)
                    return _unfilled(client_order_id)
            # SELLS bypass every gate above (exits must always be able to run). Both buys and
            # sells go through the breaker's error accounting so a sell that works clears it.
            try:
                res = submit(ticker, action, side, qty, price, client_order_id=client_order_id)
            except Exception:
                self._record_error()
                raise
            self._record_success()
            return res

        return guarded

    def _pre_buy_reason(self, qty: int, price: float, now: float) -> Optional[str]:
        """Why this BUY must not be sent, or None. Holds the lock for the rate/breaker state."""
        if self._kill_switch_on():
            return "kill switch"
        ff = self._fat_finger_reason(qty, price)
        if ff is not None:
            return ff
        with self._lock:
            if now < self._open_until:
                return "circuit breaker open"
            if self.rate_limit > 0:
                cutoff = now - self.rate_window_s
                while self._buy_times and self._buy_times[0] < cutoff:
                    self._buy_times.popleft()
                if len(self._buy_times) >= self.rate_limit:
                    return "rate limit %d/%.0fs" % (self.rate_limit, self.rate_window_s)
                self._buy_times.append(now)
        return None

    def _record_error(self) -> None:
        with self._lock:
            self._consec_errors += 1
            if self.breaker_errors > 0 and self._consec_errors >= self.breaker_errors:
                self._open_until = time.monotonic() + self.breaker_cooldown_s
                print("[guard] circuit breaker OPEN after %d consecutive order errors; "
                      "blocking new BUYS for %.0fs" % (self._consec_errors, self.breaker_cooldown_s),
                      flush=True)

    def _record_success(self) -> None:
        with self._lock:
            self._consec_errors = 0
            self._open_until = 0.0


def _unfilled(client_order_id: Optional[str]) -> Dict:
    """A result the kernel's fill parser reads as a clean no-fill (fill_count 0)."""
    return {"client_order_id": client_order_id, "resp": {"fill_count": "0.00"}, "guard_blocked": True}


# Single process-wide guard. Limits are intentionally generous backstops, not sizing tools.
_GUARD = ExecutionGuard(
    max_qty=_env_int("APP_EXEC_MAX_QTY", 10000),
    max_notional=_env_float("APP_EXEC_MAX_NOTIONAL", 5000.0),
    rate_limit=_env_int("APP_EXEC_RATE_LIMIT", 30),
    rate_window_s=_env_float("APP_EXEC_RATE_WINDOW_SECONDS", 10.0),
    breaker_errors=_env_int("APP_EXEC_BREAKER_ERRORS", 5),
    breaker_cooldown_s=_env_float("APP_EXEC_BREAKER_COOLDOWN_SECONDS", 30.0),
    db_switch=DbKillSwitch(),
)


def guarded_submitter(submit: Callable[..., dict]) -> Callable[..., dict]:
    """Wrap a kernel submitter with the process-wide execution guards (P1-3)."""
    return _GUARD.wrap(submit)


# Demo (Kalshi's sandbox) has a guard of its own with the same limits, so demo's errors never open
# live's breaker: an empty demo account has every order refused, and those refusals used to count
# toward the one breaker live shares, blocking every live BUY for its cooldown. Its rate limit and
# breaker count demo orders only. The kill switch stays one switch: the same env flag and the same
# DB switch instance (one cached read) halt BUYS on both.
_DEMO_GUARD = ExecutionGuard(
    max_qty=_env_int("APP_EXEC_MAX_QTY", 10000),
    max_notional=_env_float("APP_EXEC_MAX_NOTIONAL", 5000.0),
    rate_limit=_env_int("APP_EXEC_RATE_LIMIT", 30),
    rate_window_s=_env_float("APP_EXEC_RATE_WINDOW_SECONDS", 10.0),
    breaker_errors=_env_int("APP_EXEC_BREAKER_ERRORS", 5),
    breaker_cooldown_s=_env_float("APP_EXEC_BREAKER_COOLDOWN_SECONDS", 30.0),
    db_switch=_GUARD._db_switch,
)


def demo_guarded_submitter(submit: Callable[..., dict]) -> Callable[..., dict]:
    """Wrap a DEMO kernel submitter with demo's own execution guards (live's limits, its own counters)."""
    return _DEMO_GUARD.wrap(submit)


if __name__ == "__main__":  # self-check: the four gates, and that sells always pass
    g = ExecutionGuard(max_qty=100, max_notional=50.0, rate_limit=3, rate_window_s=10.0,
                       breaker_errors=2, breaker_cooldown_s=30.0)
    calls = {"n": 0}

    def ok(ticker, action, side, qty, price, client_order_id=None):
        calls["n"] += 1
        return {"resp": {"fill_count": "%d.00" % qty}, "client_order_id": client_order_id}

    sub = g.wrap(ok)
    # fat-finger: qty over ceiling blocks a BUY, never reaches ok
    before = calls["n"]
    assert sub("T", "buy", "yes", 999, 0.50).get("guard_blocked") and calls["n"] == before
    # off-grid price blocks
    assert sub("T", "buy", "yes", 1, 0.0).get("guard_blocked")
    # kill switch blocks a buy, not a sell
    os.environ["APP_KILL_SWITCH"] = "1"
    assert sub("T", "buy", "yes", 1, 0.50).get("guard_blocked")
    assert sub("T", "sell", "yes", 1, 0.50).get("guard_blocked") is None  # sell passes
    del os.environ["APP_KILL_SWITCH"]
    # rate limit: 3 allowed, 4th blocked; a sell in between is never counted
    g2 = ExecutionGuard(10000, 5000.0, 3, 10.0, 5, 30.0)
    s2 = g2.wrap(ok)
    assert all(s2("T", "buy", "yes", 1, 0.50).get("guard_blocked") is None for _ in range(3))
    assert s2("T", "buy", "yes", 1, 0.50).get("guard_blocked")
    assert s2("T", "sell", "yes", 1, 0.50).get("guard_blocked") is None  # sell still passes
    # circuit breaker: 2 consecutive errors open it; buys blocked, sells pass
    g3 = ExecutionGuard(10000, 5000.0, 0, 10.0, 2, 30.0)

    def boom(*a, **k):
        raise RuntimeError("exchange 500")

    s3 = g3.wrap(boom)
    for _ in range(2):
        try:
            s3("T", "buy", "yes", 1, 0.50)
        except RuntimeError:
            pass
    s3buy = g3.wrap(ok)("T", "buy", "yes", 1, 0.50)  # breaker shared via g3
    assert s3buy.get("guard_blocked")
    assert g3.wrap(ok)("T", "sell", "yes", 1, 0.50).get("guard_blocked") is None  # sell passes
    print("guard self-check OK")
