"""Demo has its own execution guard: a refused demo order never opens live's circuit breaker.

An empty Kalshi demo account has every order refused, and each refusal is a submitter error. With
one process-wide guard, five in a row opened the breaker that live shares and blocked every live
BUY for its cooldown. Demo now wraps its submitter with a guard of its own (same env limits, same
kill switch); live's guard and its wiring are unchanged. These drive the real kernel factories with
the exchange calls stubbed: no network, no DB.
"""
from collections import deque

import pytest

from app.execution import guard

REFUSED = ('demo POST /portfolio/orders failed 400: {"error":{"code":"insufficient_balance",'
           '"message":"insufficient balance","service":"exchange"}}')


class _Conn:
    def cursor(self):
        return None


@pytest.fixture
def venues(monkeypatch):
    """Live and demo submitters exactly as the engine builds them, with the exchange stubbed, on the
    real module guards (their counters reset for the test and restored after)."""
    from app import engine
    from app.adapters.kalshi import kalshi_account, kalshi_dev_exec
    from app import repository as repo
    from app.execution import latency
    from data_pipeline import live_trading_engine
    from data_pipeline.architecture import position_guard

    switch = {"db": False}
    for g in (guard._GUARD, guard._DEMO_GUARD):
        monkeypatch.setattr(g, "_consec_errors", 0)
        monkeypatch.setattr(g, "_open_until", 0.0)
        monkeypatch.setattr(g, "_buy_times", deque())
    monkeypatch.setattr(guard._GUARD._db_switch, "is_on", lambda: switch["db"])
    monkeypatch.delenv("APP_KILL_SWITCH", raising=False)
    monkeypatch.setattr(latency, "_record", lambda **row: None)  # no background latency writes
    monkeypatch.setattr(repo, "get_kalshi_key", lambda cur, uid: {"key_id": "live"})
    monkeypatch.setattr(repo, "get_kalshi_dev_key", lambda cur, uid: {"key_id": "demo"})
    monkeypatch.setattr(repo, "user_execution_config", lambda cur, uid: {})
    monkeypatch.setattr(kalshi_account, "credentials_from_row", lambda uid, row: (row["key_id"], object()))
    monkeypatch.setattr(position_guard, "exchange_net_reader", lambda creds: (lambda ticker: 10))
    monkeypatch.setattr(kalshi_dev_exec, "demo_net_reader", lambda creds: (lambda ticker: 10))

    sent = {"live": [], "demo": []}
    fail = {"live": None, "demo": None}

    def exchange(mode):
        def place(ticker, action, side, qty, price, credentials=None, client_order_id=None, **kw):
            if fail[mode]:
                raise RuntimeError(fail[mode])
            sent[mode].append(action)
            return {"client_order_id": client_order_id, "resp": {"fill_count": "%d.00" % qty}}
        return place

    monkeypatch.setattr(live_trading_engine, "place_limit_order", exchange("live"))
    monkeypatch.setattr(kalshi_dev_exec, "demo_place_limit_order", exchange("demo"))
    submit = {"live": engine.live_kernel_factory(_Conn())(1)._submitter,
              "demo": kalshi_dev_exec.demo_kernel_factory(_Conn())(1)._submitter}
    return {"submit": submit, "sent": sent, "fail": fail, "switch": switch}


def _buy(v, mode):
    return v["submit"][mode]("KXT-1", "buy", "yes", 1, 0.40)


def _sell(v, mode):
    return v["submit"][mode]("KXT-1", "sell", "yes", 1, 0.40)


def test_demo_has_a_guard_of_its_own_with_lives_limits_and_kill_switch():
    live, demo = guard._GUARD, guard._DEMO_GUARD
    assert demo is not live
    for limit in ("max_qty", "max_notional", "rate_limit", "rate_window_s", "breaker_errors", "breaker_cooldown_s"):
        assert getattr(demo, limit) == getattr(live, limit), limit
    assert demo._db_switch is live._db_switch  # one kill switch, one cached read


def test_demo_refusals_open_only_the_demo_breaker(venues):
    v = venues
    v["fail"]["demo"] = REFUSED
    for _ in range(guard._DEMO_GUARD.breaker_errors):
        with pytest.raises(RuntimeError, match="insufficient_balance"):
            _buy(v, "demo")
    v["fail"]["demo"] = None
    # Live never saw those errors: its BUY goes out. (Checked before any success, which closes a breaker.)
    assert guard._GUARD._consec_errors == 0
    assert _buy(v, "live").get("guard_blocked") is None and v["sent"]["live"] == ["buy"]
    assert _buy(v, "demo").get("guard_blocked") is True and v["sent"]["demo"] == []  # demo's breaker is open
    assert _sell(v, "demo").get("guard_blocked") is None and v["sent"]["demo"] == ["sell"]  # exits still go


def test_a_live_error_still_opens_the_live_breaker(venues):
    v = venues
    v["fail"]["live"] = "live POST /portfolio/orders failed 500"
    for _ in range(guard._GUARD.breaker_errors):
        with pytest.raises(RuntimeError):
            _buy(v, "live")
    v["fail"]["live"] = None
    assert guard._DEMO_GUARD._consec_errors == 0
    assert _buy(v, "demo").get("guard_blocked") is None and v["sent"]["demo"] == ["buy"]  # demo unaffected
    assert _buy(v, "live").get("guard_blocked") is True and v["sent"]["live"] == []
    assert _sell(v, "live").get("guard_blocked") is None and v["sent"]["live"] == ["sell"]


@pytest.mark.parametrize("how", ["env", "db"])
def test_the_kill_switch_blocks_buys_on_both(venues, monkeypatch, how):
    v = venues
    if how == "env":
        monkeypatch.setenv("APP_KILL_SWITCH", "1")
    else:
        v["switch"]["db"] = True
    assert _buy(v, "live").get("guard_blocked") is True
    assert _buy(v, "demo").get("guard_blocked") is True
    assert v["sent"] == {"live": [], "demo": []}
    assert _sell(v, "live").get("guard_blocked") is None and _sell(v, "demo").get("guard_blocked") is None
    assert v["sent"] == {"live": ["sell"], "demo": ["sell"]}
