"""DB-backed kill switch: halts new BUYS within the cache window, never touches a SELL, and a DB
error keeps the last value seen instead of silently un-halting."""
import json

from app.execution.guard import ExecutionGuard
from app.execution.kill_switch import DbKillSwitch, read_state, write_state


class Store:
    def __init__(self):
        self.rows = {}
        self.reads = 0
        self.fail = False


class Cur:
    def __init__(self, store):
        self.s = store
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        if self.s.fail:
            raise RuntimeError("db down")
        if sql.lstrip().startswith("SELECT"):
            self.s.reads += 1
            self._row = self.s.rows.get(params[0])
        else:
            key, val, at = params
            self.s.rows[key] = {"state_value": val, "updated_at_utc": at}

    def fetchone(self):
        return self._row


class Conn:
    def __init__(self, store):
        self.s = store

    def cursor(self):
        return Cur(self.s)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_state_round_trip():
    s = Store()
    write_state(Cur(s), True, "bad fills", "todd")
    st = read_state(Cur(s))
    assert st["on"] is True and st["reason"] == "bad fills" and st["by"] == "todd"
    assert read_state(Cur(Store())) == {}


def test_switch_is_cached_then_rereads():
    s, clock = Store(), Clock()
    sw = DbKillSwitch(lambda: Conn(s), cache_seconds=5, clock=clock)
    assert sw.is_on() is False and s.reads == 1
    write_state(Cur(s), True)
    clock.t = 4.9
    assert sw.is_on() is False and s.reads == 1      # still cached
    clock.t = 5.1
    assert sw.is_on() is True and s.reads == 2       # picked up without a restart


def test_db_error_keeps_the_last_value():
    s, clock = Store(), Clock()
    write_state(Cur(s), True)
    sw = DbKillSwitch(lambda: Conn(s), cache_seconds=1, clock=clock)
    assert sw.is_on() is True
    s.fail = True
    clock.t = 2
    assert sw.is_on() is True                         # a blip must not un-halt


def test_connect_failure_before_any_read_is_off():
    def boom():
        raise RuntimeError("no db")
    assert DbKillSwitch(boom, cache_seconds=1).is_on() is False


def _guard(switch):
    return ExecutionGuard(max_qty=1000, max_notional=1000.0, rate_limit=0, rate_window_s=10.0,
                          breaker_errors=0, breaker_cooldown_s=1.0, db_switch=switch)


def _ok(ticker, action, side, qty, price, client_order_id=None):
    return {"resp": {"fill_count": "%d.00" % qty}}


def test_guard_blocks_buys_but_never_sells_when_db_switch_is_on():
    s = Store()
    write_state(Cur(s), True, "incident")
    sub = _guard(DbKillSwitch(lambda: Conn(s), cache_seconds=0)).wrap(_ok)
    assert sub("T", "buy", "yes", 1, 0.5).get("guard_blocked")
    assert sub("T", "sell", "yes", 1, 0.5).get("guard_blocked") is None


def test_guard_passes_buys_when_db_switch_is_off():
    sub = _guard(DbKillSwitch(lambda: Conn(Store()), cache_seconds=0)).wrap(_ok)
    assert sub("T", "buy", "yes", 1, 0.5).get("guard_blocked") is None


# -- admin API -------------------------------------------------------------------

import pytest  # noqa: E402

from app import server  # noqa: E402


def _ctx(store, body=None, email=None):
    return server.Ctx(Conn(store), {"id": 1, "email": email or server.ADMIN_EMAIL}, (), {}, body or {}, None)


def test_admin_flips_the_switch_and_reads_it_back():
    s = Store()
    out = server.admin_kill_switch_set(_ctx(s, {"on": True, "reason": "bad fills"}))
    assert out["on"] is True and out["reason"] == "bad fills" and out["by"] == server.ADMIN_EMAIL
    assert server.admin_kill_switch(_ctx(s))["on"] is True
    assert server.admin_kill_switch_set(_ctx(s, {"on": False}))["on"] is False


def test_admin_switch_rejects_a_non_boolean():
    with pytest.raises(server.ApiError) as e:
        server.admin_kill_switch_set(_ctx(Store(), {"on": "yes"}))
    assert e.value.status == 400


def test_non_admin_cannot_read_or_flip():
    for fn, body in ((server.admin_kill_switch, None), (server.admin_kill_switch_set, {"on": True})):
        with pytest.raises(server.ApiError) as e:
            fn(_ctx(Store(), body, email="someone@else.com"))
        assert e.value.status == 403
