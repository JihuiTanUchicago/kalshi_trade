"""Risk hardening for the app engine: auto-flatten on pause/stop + position-level stop-loss.

Money-critical, real-order path. Same non-MySQL pattern as test_app_force_sell.py: monkeypatched
repo functions + a recording fake kernel. No live DB, no real orders.

Covers:
  - pause/stop -> EVERY open position closed (paper via sell, live/demo via the kernel);
  - a flatten whose live close partial-fills books the slice, keeps the remainder, closes nothing
    fully (retries next sweep) — never leaves exposure untracked;
  - live/demo flatten with no execution path closes nothing but does not crash (loud log);
  - the position-level stop fires when a position is down > threshold of COST while whole-capital
    drawdown is < 25%; does NOT fire within threshold; fires for a NO position; 0 disables it.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import engine
from app import repository as repo


# -- helpers (mirror test_app_force_sell.py) -----------------------------------


def _dep(mode="paper", capital=100.0):
    return {"id": 1, "user_id": 1, "mode": mode, "market": "btc15m", "result": {"capital": capital},
            "spec": {"side": "yes", "sizing": {"stake": 5.0, "max_positions": 20}}}


def _pos(pid=1, side="yes", qty=10, entry=0.50, mark=0.40):
    return {"id": pid, "user_id": 1, "ticker": "BTC-%d" % pid, "side": side, "qty": qty,
            "entry_price": entry, "entry_fee": 0.0, "mark_price": mark}


class _Kernel:
    def __init__(self, fill=None, fill_price=None, fee=0.0):
        self.intents = []
        self.fill = fill
        self.fill_price = fill_price
        self.fee = fee

    def execute(self, intent):
        self.intents.append(intent)
        return SimpleNamespace(
            fill_qty_contracts=intent.qty_contracts if self.fill is None else self.fill,
            fill_price_dollars=intent.limit_price_dollars if self.fill_price is None else self.fill_price,
            fee_dollars=self.fee)


class _Conn:
    def cursor(self):
        return object()


@contextmanager
def _tx(conn):
    yield object()


def _wire_closes(monkeypatch, positions):
    """Record paper sells + kernel closes for the flatten/stop paths."""
    rec = {"closed": [], "paused": None, "chats": 0, "sold": []}
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: list(positions))
    monkeypatch.setattr(engine.repo, "close_position",
                        lambda cur, pid, px, fee, pnl, reason: (rec["closed"].append((pid, reason)), True)[1])
    monkeypatch.setattr(engine, "_paper_sell",
                        lambda conn, pos, price, reason: rec["sold"].append((pos["id"], reason)))
    monkeypatch.setattr(engine.repo, "set_deployment_status",
                        lambda cur, uid, dep_id, status, reason: (rec.__setitem__("paused", (status, reason)), True)[1])
    monkeypatch.setattr(engine.repo, "add_chat", lambda *a, **k: rec.__setitem__("chats", rec["chats"] + 1))
    monkeypatch.setattr(engine.repo, "create_run", lambda *a, **k: 1)
    monkeypatch.setattr(engine.repo, "add_ledger", lambda *a, **k: None)
    monkeypatch.setattr(engine.repo, "user_risk_config",
                        lambda cur, uid: {"drawdown_limit_pct": 25.0, "position_stop_pct": 40.0,
                                          "max_open_positions": 20, "max_open_notional": 1000.0})
    monkeypatch.setattr(engine.repo, "transaction", _tx)
    # P0-3: flatten now leases each position before a real kernel sell (so two engines never both
    # sell it). The lease always wins in these single-engine tests.
    monkeypatch.setattr(engine.repo, "claim_position_close", lambda *a, **k: True)
    return rec


# -- auto-flatten on pause/stop ------------------------------------------------


def test_flatten_paper_closes_every_open_position(monkeypatch):
    rec = _wire_closes(monkeypatch, [_pos(1), _pos(2)])
    closed = engine.flatten_deployment(_Conn(), _dep(mode="paper"), engine.Sources())
    assert closed == 2
    assert rec["sold"] == [(1, "flatten"), (2, "flatten")]  # both out via the paper exit path


def test_flatten_live_routes_sells_to_the_kernel(monkeypatch):
    rec = _wire_closes(monkeypatch, [_pos(1), _pos(2)])
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)
    k = _Kernel()
    sources = engine.Sources(live_kernel=lambda uid: k, demo_kernel=lambda uid: _Kernel())
    closed = engine.flatten_deployment(_Conn(), _dep(mode="live"), sources)
    assert closed == 2
    assert [i.action for i in k.intents] == ["sell", "sell"]
    assert rec["closed"] == [(1, "flatten"), (2, "flatten")]


def test_flatten_live_without_kernel_closes_nothing_and_does_not_crash(monkeypatch):
    # Live gate off / no key: no execution path -> nothing closes (loud log), but no exception.
    rec = _wire_closes(monkeypatch, [_pos(1)])
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", False)
    closed = engine.flatten_deployment(_Conn(), _dep(mode="live"), engine.Sources())
    assert closed == 0 and rec["closed"] == [] and rec["sold"] == []


def test_flatten_partial_fill_keeps_remainder_untracked_as_nothing(monkeypatch):
    # The kernel sells only 3 of 10: the slice is booked, the row shrinks to 7, and flatten reports
    # 0 fully-closed — the remainder retries next sweep, never dropped (would double-count/re-sell).
    booked = {}
    monkeypatch.setattr(engine.repo, "book_partial_exit",
                        lambda cur, pos, fq, px, fee, pnl, reason: booked.update(fq=fq, reason=reason) or True)
    monkeypatch.setattr(engine.repo, "transaction", _tx)
    monkeypatch.setattr(engine.repo, "claim_position_close", lambda *a, **k: True)  # P0-3 lease (single engine)
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)
    pos = {"id": 1, "deployment_id": 1, "user_id": 1, "mode": "live", "ticker": "BTC-1", "side": "yes",
           "qty": 10, "entry_price": 0.50, "entry_fee": 1.0, "mark_price": 0.44}
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [pos])
    k = _Kernel(fill=3, fill_price=0.44, fee=0.06)
    sources = engine.Sources(live_kernel=lambda uid: k)
    closed = engine.flatten_deployment(_Conn(), _dep(mode="live"), sources)
    assert closed == 0 and booked["fq"] == 3 and booked["reason"] == "flatten"


def test_enforce_flatten_sweep_is_contained(monkeypatch):
    # One deployment's flatten raising must not stop the sweep or the others.
    deps = [_dep(), dict(_dep(), id=2, user_id=2), dict(_dep(), id=3, user_id=3)]
    monkeypatch.setattr(engine.repo, "paused_deployments_with_open_positions",
                        lambda cur, market: deps if market == "btc15m" else [])
    seen = []

    def _flat(conn, dep, sources):
        seen.append(dep["id"])
        if dep["id"] == 2:
            raise RuntimeError("boom")
        return 1
    monkeypatch.setattr(engine, "flatten_deployment", _flat)
    assert engine.enforce_flatten_on_pause(_Conn(), engine.Sources()) == 2  # dep 1 + dep 3
    assert seen == [1, 2, 3]


# -- position-level stop-loss --------------------------------------------------


def _wire_stop(monkeypatch, positions, realized, stop_pct=40.0, dd_pct=25.0):
    rec = {"closed": [], "paused": None, "chats": 0}
    monkeypatch.setattr(engine.repo, "user_risk_config",
                        lambda cur, uid: {"drawdown_limit_pct": dd_pct, "position_stop_pct": stop_pct,
                                          "max_open_positions": 20, "max_open_notional": 1000.0})
    monkeypatch.setattr(engine.repo, "deployment_realized_series", lambda cur, dep_id: list(realized))
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: list(positions))
    monkeypatch.setattr(engine.repo, "close_position",
                        lambda cur, pid, px, fee, pnl, reason: (rec["closed"].append((pid, reason)), True)[1])
    monkeypatch.setattr(engine, "_paper_sell",
                        lambda conn, pos, price, reason: rec["closed"].append((pos["id"], reason)))
    monkeypatch.setattr(engine.repo, "set_deployment_status",
                        lambda cur, uid, dep_id, status, reason: (rec.__setitem__("paused", (status, reason)), True)[1])
    monkeypatch.setattr(engine.repo, "add_chat", lambda *a, **k: rec.__setitem__("chats", rec["chats"] + 1))
    monkeypatch.setattr(engine.repo, "create_run", lambda *a, **k: 1)
    monkeypatch.setattr(engine.repo, "add_ledger", lambda *a, **k: None)
    monkeypatch.setattr(engine.repo, "transaction", _tx)
    return rec


def test_position_stop_fires_when_capital_drawdown_is_tiny(monkeypatch):
    # The reported gap: 6 @ 0.79 -> mark 0.44. Loss/cost = (4.74-2.64)/4.74 = 44.3% >= 40% stop.
    # Capital drawdown: no realized, unrealized -2.10 on a $100 base = 2.1% << 25% -> the OLD guard
    # would NOT fire. The position-stop must.
    pos = _pos(qty=6, entry=0.79, mark=0.44)
    rec = _wire_stop(monkeypatch, [pos], realized=[])
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources()) is True
    assert rec["closed"] == [(1, "stop")]
    assert "position down" in rec["paused"][1] and "stop" in rec["paused"][1]


def test_position_stop_does_not_fire_within_threshold(monkeypatch):
    # 10 @ 0.50 -> mark 0.40: 20% of cost < 40% stop, and 1% capital drawdown < 25%. Untouched.
    rec = _wire_stop(monkeypatch, [_pos(entry=0.50, mark=0.40)], realized=[])
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources()) is False
    assert rec["closed"] == [] and rec["paused"] is None


def test_position_stop_is_side_aware_for_no(monkeypatch):
    # NO position: liquidation = 1 - mark. Bought NO at 0.30 (cost basis), mark_price (YES ask) 0.80
    # -> NO liquidation 0.20. Loss/cost = (0.30-0.20)/0.30 = 33% < 40%: NOT stopped.
    rec = _wire_stop(monkeypatch, [_pos(side="no", qty=10, entry=0.30, mark=0.80)], realized=[])
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources()) is False
    # Now YES ask 0.88 -> NO liquidation 0.12. Loss/cost = (0.30-0.12)/0.30 = 60% >= 40%: stopped.
    rec2 = _wire_stop(monkeypatch, [_pos(side="no", qty=10, entry=0.30, mark=0.88)], realized=[])
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources()) is True
    assert rec2["closed"] == [(1, "stop")]


def test_position_stop_disabled_when_zero(monkeypatch):
    # stop_pct=0 disables the position stop; with drawdown also tiny, the cratered position stays.
    pos = _pos(qty=6, entry=0.79, mark=0.44)
    rec = _wire_stop(monkeypatch, [pos], realized=[], stop_pct=0.0)
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources()) is False
    assert rec["closed"] == [] and rec["paused"] is None


def test_drawdown_still_fires_with_stop_enabled(monkeypatch):
    # Regression: the whole-capital drawdown guard still fires on its own condition (and names
    # "drawdown"), even with the position stop present. realized [+10,-40] -> 40% drawdown >= 25%.
    rec = _wire_stop(monkeypatch, [_pos()], realized=[10.0, -40.0])
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources()) is True
    assert rec["closed"] == [(1, "drawdown")]
    assert rec["paused"][1].startswith("force-closed: drawdown")


# -- engine liveness read ------------------------------------------------------


def test_engine_last_tick_age_handles_missing_row():
    from app import repository as repo

    class _Cur:
        def __init__(self, row):
            self._row = row

        def execute(self, sql, params=()):
            pass

        def fetchone(self):
            return self._row

    assert repo.engine_last_tick_age_seconds(_Cur({"a": 12})) == 12
    assert repo.engine_last_tick_age_seconds(_Cur({"a": None})) is None  # never ticked
    assert repo.engine_last_tick_age_seconds(_Cur(None)) is None         # row absent


def test_worst_position_loss_pct_picks_the_worst(monkeypatch):
    # Two positions; the worst drives the number. p1: 20% loss, p2: 44.3% loss.
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id:
                        [_pos(1, entry=0.50, mark=0.40), _pos(2, qty=6, entry=0.79, mark=0.44)])
    assert engine.worst_position_loss_pct(object(), _dep()) == pytest.approx(44.303797, abs=1e-4)


def test_mark_staleness_gate_suppresses_trigger_off_stale_mark(monkeypatch):
    # P1-2: a mark PROVABLY older than APP_MARK_MAX_AGE_SECONDS must not drive a force-sell (the
    # stalled-feed case). A fresh or un-timestamped mark is evaluated exactly as before (additive).
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    stale = dict(_pos(2, qty=6, entry=0.79, mark=0.44), mark_ts=now - timedelta(seconds=10_000))
    fresh = dict(_pos(2, qty=6, entry=0.79, mark=0.44), mark_ts=now)
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [stale])
    assert engine.worst_position_loss_pct(object(), _dep()) == 0.0  # stale -> skipped
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [fresh])
    assert engine.worst_position_loss_pct(object(), _dep()) == pytest.approx(44.303797, abs=1e-4)
    # no mark_ts at all -> treated as fresh (additive: behaves as before the gate)
    assert engine._mark_is_fresh(_pos()) is True


class _MarkCur:
    def __init__(self):
        self.calls = []
        self.rowcount = 0

    def execute(self, sql, args):
        self.calls.append(args)
        self.rowcount = 1


def test_marks_a_no_position_at_its_own_bid():
    # A NO position sells at 1 - yes_ask, so it is marked with the YES ask; a YES position with the
    # YES bid. On a 0.30/0.40 book, 1 - yes_bid would value NO at 0.70 when it sells for 0.60.
    cur = _MarkCur()
    now = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)
    assert repo.update_marks(cur, "nfl", {"T": (0.30, 0.40)}, now) == 2
    assert [(a[0], a[-1]) for a in cur.calls] == [(0.30, "yes"), (0.40, "no")]
    # A side with no usable price keeps its last mark: no YES offers means nobody bids for NO.
    cur = _MarkCur()
    repo.update_marks(cur, "nfl", {"T": (0.30, None), "U": (0.0, 1.0)}, now)
    assert [(a[0], a[-1]) for a in cur.calls] == [(0.30, "yes")]


def test_ws_mark_returns_bid_and_ask_from_one_fresh_quote():
    now = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)

    class _Feed:
        def __init__(self, ts):
            self.msg = {"ts": ts, "yes_bid_dollars": "0.30", "yes_ask_dollars": "0.40"}

        def get_latest(self, ticker):
            return self.msg

    assert engine._ws_mark(_Feed(now.timestamp()), "T", now) == (0.30, 0.40)
    assert engine._ws_mark(_Feed(now.timestamp() - 60), "T", now) is None  # stale: REST quote instead
