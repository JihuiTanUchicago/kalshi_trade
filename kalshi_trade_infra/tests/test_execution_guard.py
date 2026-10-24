"""Process-wide execution guards (app/execution/guard.py, EXECUTION_RISK_HARDENING P1-3).

The guard module ships a thorough ``__main__`` self-check, but pytest never runs it, so a
regression to the real-order backstops — or to the ONE invariant that makes them safe, that a
SELL is never blocked — would pass the suite unnoticed. These lock the four gates and that
invariant in CI. Pure unit tests: a fake in-memory submitter, no live DB, no network.
"""
from app.execution.guard import ExecutionGuard


def _fake_submitter(calls):
    def ok(ticker, action, side, qty, price, client_order_id=None):
        calls.append((action, qty, price))
        return {"resp": {"fill_count": "%d.00" % qty}, "client_order_id": client_order_id}
    return ok


def _guard(**over):
    kw = dict(max_qty=100, max_notional=50.0, rate_limit=3, rate_window_s=10.0,
              breaker_errors=2, breaker_cooldown_s=30.0)
    kw.update(over)
    return ExecutionGuard(**kw)


def _blocked(res):
    return res.get("guard_blocked") is True


# -- fat-finger ----------------------------------------------------------------

def test_fat_finger_blocks_buy_over_ceilings_and_off_grid():
    calls = []
    sub = _guard().wrap(_fake_submitter(calls))
    assert _blocked(sub("T", "buy", "yes", 999, 0.50))     # qty over the ceiling
    assert _blocked(sub("T", "buy", "yes", 0, 0.50))       # qty < 1
    assert _blocked(sub("T", "buy", "yes", 1, 0.0))        # price off the 1c..99c grid
    assert _blocked(sub("T", "buy", "yes", 60, 0.99))      # 59.40 notional over the 50 ceiling
    assert calls == []                                     # none of these ever reached the exchange


def test_fat_finger_lets_a_well_sized_buy_through():
    calls = []
    sub = _guard().wrap(_fake_submitter(calls))
    assert not _blocked(sub("T", "buy", "yes", 10, 0.40))  # 4.00 notional, on grid, under ceilings
    assert calls == [("buy", 10, 0.40)]


# -- kill switch ---------------------------------------------------------------

def test_kill_switch_halts_buys_but_never_sells(monkeypatch):
    calls = []
    sub = _guard().wrap(_fake_submitter(calls))
    monkeypatch.setenv("APP_KILL_SWITCH", "1")
    assert _blocked(sub("T", "buy", "yes", 1, 0.50))       # new risk halted instantly
    assert not _blocked(sub("T", "sell", "yes", 1, 0.50))  # an exit must always get flat
    assert calls == [("sell", 1, 0.50)]


# -- rate limit ----------------------------------------------------------------

def test_rate_limit_caps_buys_and_does_not_count_sells():
    calls = []
    sub = _guard(rate_limit=3).wrap(_fake_submitter(calls))
    assert all(not _blocked(sub("T", "buy", "yes", 1, 0.50)) for _ in range(3))  # 3 allowed
    assert not _blocked(sub("T", "sell", "yes", 1, 0.50))  # a sell between buys is never counted
    assert _blocked(sub("T", "buy", "yes", 1, 0.50))       # 4th buy in the window blocked


# -- circuit breaker -----------------------------------------------------------

def test_circuit_breaker_opens_on_consecutive_errors_then_blocks_buys_not_sells():
    import pytest
    g = _guard(rate_limit=0, breaker_errors=2)  # rate limit off so only the breaker is under test

    def boom(*a, **k):
        raise RuntimeError("exchange 500")

    s_err = g.wrap(boom)
    for _ in range(2):                                     # two consecutive errors open the breaker
        with pytest.raises(RuntimeError):
            s_err("T", "buy", "yes", 1, 0.50)

    calls = []
    s_ok = g.wrap(_fake_submitter(calls))                  # same shared guard state
    assert _blocked(s_ok("T", "buy", "yes", 1, 0.50))      # buys refused while open
    assert not _blocked(s_ok("T", "sell", "yes", 1, 0.50)) # sells keep trying throughout
    assert calls == [("sell", 1, 0.50)]


def test_a_success_resets_the_error_streak_before_the_breaker_trips():
    g = _guard(rate_limit=0, breaker_errors=2)
    calls = []
    ok = g.wrap(_fake_submitter(calls))

    def boom(*a, **k):
        raise RuntimeError("exchange 500")

    s_err = g.wrap(boom)
    import pytest
    with pytest.raises(RuntimeError):                      # 1 error (one short of the breaker)
        s_err("T", "buy", "yes", 1, 0.50)
    assert not _blocked(ok("T", "buy", "yes", 1, 0.50))    # a success clears the consecutive count
    with pytest.raises(RuntimeError):                      # 1 more error — streak is 1, not 2
        s_err("T", "buy", "yes", 1, 0.50)
    assert not _blocked(ok("T", "buy", "yes", 1, 0.50))    # so the breaker never opened
