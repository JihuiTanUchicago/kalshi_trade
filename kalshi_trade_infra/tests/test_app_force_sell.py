"""Risk force-sell + portfolio caps for the app engine.

Money-critical: this layer can close REAL live positions. Tested with monkeypatched repo
functions (the established non-MySQL pattern for app-engine logic, as in
test_app_autopilot_live.py) + a recording fake kernel — no live DB, no real orders.

Covers: a deployment past its drawdown limit is force-closed via the correct mode's exit path
and paused; one under the limit is untouched; the live path routes a sell to the LIVE kernel; a
portfolio past the cap blocks a new entry; a force-close exception is contained.
"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app import engine


# -- helpers -------------------------------------------------------------------


def _dep(mode="paper", capital=100.0):
    return {"id": 1, "user_id": 1, "mode": mode, "market": "btc15m", "result": {"capital": capital},
            "spec": {"side": "yes", "sizing": {"stake": 5.0, "max_positions": 20}}}


def _pos(pid=1, side="yes", qty=10, entry=0.50, mark=0.40):
    return {"id": pid, "user_id": 1, "ticker": "BTC-%d" % pid, "side": side, "qty": qty,
            "entry_price": entry, "entry_fee": 0.0, "mark_price": mark}


class _Kernel:
    """Records the intents it is asked to execute; fills `fill` contracts (whole order by default)
    at `fill_price` (the limit price by default)."""

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
        return object()  # every repo call is monkeypatched; the cursor is never used


def _wire(monkeypatch, *, realized, positions, limit_pct=25.0):
    """Patch the repo reads the force-sell makes and record the writes it performs."""
    rec = {"closed": [], "paused": None, "chats": 0}
    monkeypatch.setattr(engine.repo, "user_risk_config",
                        lambda cur, uid: {"drawdown_limit_pct": limit_pct, "max_open_positions": 20,
                                          "max_open_notional": 1000.0})
    monkeypatch.setattr(engine.repo, "deployment_realized_series", lambda cur, dep_id: list(realized))
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: list(positions))
    monkeypatch.setattr(engine.repo, "close_position",
                        lambda cur, pid, px, fee, pnl, reason: (rec["closed"].append((pid, reason)), True)[1])
    monkeypatch.setattr(engine.repo, "set_deployment_status",
                        lambda cur, uid, dep_id, status, reason: (rec.__setitem__("paused", (status, reason)), True)[1])
    monkeypatch.setattr(engine.repo, "add_chat", lambda *a, **k: rec.__setitem__("chats", rec["chats"] + 1))
    monkeypatch.setattr(engine.repo, "create_run", lambda *a, **k: 1)
    monkeypatch.setattr(engine.repo, "add_ledger", lambda *a, **k: None)

    @contextmanager
    def _tx(conn):
        yield object()
    monkeypatch.setattr(engine.repo, "transaction", _tx)
    from tests.conftest import patch_intent_passthrough
    patch_intent_passthrough(monkeypatch)  # P0-1 intent log transparent; claim_position_close -> True
    monkeypatch.setattr(engine.repo, "transaction", _tx)  # keep this file's object()-yielding tx
    return rec


# -- drawdown force-sell -------------------------------------------------------


def test_over_the_limit_force_closes_paper_and_pauses(monkeypatch):
    # realized [+10,-40] -> equity [0,10,-30]: peak 10, now -30 -> $40 drawdown on $100 = 40% >= 25%.
    rec = _wire(monkeypatch, realized=[10.0, -40.0], positions=[_pos()])
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources()) is True
    assert rec["closed"] == [(1, "drawdown")]          # closed via the paper exit path
    assert rec["paused"][0] == "paused" and "drawdown" in rec["paused"][1]
    assert rec["chats"] == 1


def test_under_the_limit_is_untouched(monkeypatch):
    # realized [+10,-5] -> equity [0,10,5]: $5 drawdown on $100 = 5% < 25%.
    rec = _wire(monkeypatch, realized=[10.0, -5.0], positions=[_pos()])
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources()) is False
    assert rec["closed"] == [] and rec["paused"] is None


def test_live_force_close_routes_a_sell_to_the_live_kernel(monkeypatch):
    # LIVE PATH (flagged for human review): a breached LIVE deployment sells through the LIVE kernel.
    rec = _wire(monkeypatch, realized=[-40.0], positions=[_pos()])
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)
    k = _Kernel()
    sources = engine.Sources(live_kernel=lambda uid: k, demo_kernel=lambda uid: _Kernel())
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="live"), sources) is True
    assert len(k.intents) == 1
    assert k.intents[0].action == "sell" and k.intents[0].side == "yes"
    assert rec["closed"] == [(1, "drawdown")] and rec["paused"][0] == "paused"


def test_live_without_kernel_pauses_but_places_no_order(monkeypatch):
    # Live gate off / no key -> no execution path: pause only, never an order; positions settle at expiry.
    rec = _wire(monkeypatch, realized=[-40.0], positions=[_pos()])
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", False)
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="live"), engine.Sources()) is True
    assert rec["closed"] == [] and rec["paused"][0] == "paused"


def test_disabled_when_limit_is_zero(monkeypatch):
    rec = _wire(monkeypatch, realized=[-99.0], positions=[_pos()], limit_pct=0.0)
    assert engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources()) is False
    assert rec["paused"] is None


def test_idempotent_second_pass_closes_nothing(monkeypatch):
    # close_position only closes an OPEN row; after the first pass the position is gone from
    # open_positions, so a retried tick books no second exit.
    open_rows = [_pos()]
    rec = _wire(monkeypatch, realized=[-40.0], positions=open_rows)
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: list(open_rows))

    def _close(cur, pid, px, fee, pnl, reason):
        open_rows[:] = [p for p in open_rows if p["id"] != pid]  # mimic the WHERE status='open' guard
        rec["closed"].append((pid, reason))
        return True
    monkeypatch.setattr(engine.repo, "close_position", _close)

    engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources())
    engine.force_sell_if_drawn_down(_Conn(), _dep(mode="paper"), engine.Sources())
    assert rec["closed"] == [(1, "drawdown")]  # closed exactly once


def test_claimed_sweep_prevents_a_second_concurrent_force_sell(monkeypatch):
    # P0-3 (closes F3): two engines run the force-sell on the SAME open position. The per-position
    # close claim must let exactly ONE of them send the real sell — the other skips — so the second
    # sell can never open an unintended short. The claim, not close-idempotency, is what guards this.
    rec = _wire(monkeypatch, realized=[-40.0], positions=[_pos()])
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [_pos()])  # always still open

    granted = {"1": False}

    def _claim_once(cur, pid, claimant, lease_seconds=300):
        if granted["%d" % pid]:
            return False      # another engine already owns this position's close
        granted["%d" % pid] = True
        return True
    monkeypatch.setattr(engine.repo, "claim_position_close", _claim_once)

    k = _Kernel()
    sources = engine.Sources(live_kernel=lambda uid: k, demo_kernel=lambda uid: _Kernel())
    engine.force_sell_if_drawn_down(_Conn(), _dep(mode="live"), sources)  # engine A
    engine.force_sell_if_drawn_down(_Conn(), _dep(mode="live"), sources)  # engine B (claim denied)
    sells = [i for i in k.intents if i.action == "sell"]
    assert len(sells) == 1   # exactly one real sell across the two engines


def test_one_deployment_failure_is_contained(monkeypatch):
    # enforce_drawdown_limits must not crash if one deployment's force-sell raises.
    deps = [_dep(), dict(_dep(), id=2, user_id=2), dict(_dep(), id=3, user_id=3)]
    monkeypatch.setattr(engine.repo, "running_deployments",
                        lambda cur, market: deps if market == "btc15m" else [])
    seen = []

    def _boom(conn, dep, sources):
        seen.append(dep["id"])
        if dep["id"] == 2:
            raise RuntimeError("kernel exploded")
        return True
    monkeypatch.setattr(engine, "force_sell_if_drawn_down", _boom)
    # Does not raise; the other two deployments are still processed; the two non-raising pause.
    assert engine.enforce_drawdown_limits(_Conn(), engine.Sources()) == 2
    assert seen == [1, 2, 3]


# -- partial exit fills (live/demo) --------------------------------------------


def _pos_full(pid=1, qty=10, entry=0.50, mark=0.40):
    """A full open-position row (all columns book_partial_exit copies)."""
    return {"id": pid, "deployment_id": 1, "user_id": 1, "mode": "live", "ticker": "BTC-%d" % pid,
            "side": "yes", "qty": qty, "entry_price": entry, "entry_fee": 1.0, "mark_price": mark,
            "market_close_time": "2026-01-01 00:00:00", "opened_at": "2026-01-01 00:00:00", "order_ref": "o1"}


def test_partial_live_exit_books_filled_slice_and_keeps_remainder(monkeypatch):
    # Kernel sells only 3 of 10. The 3 must be booked (realized) and the open row shrunk to 7 —
    # NOT dropped (dropping would double-count at settlement and re-sell the 3 next slot).
    booked = {}
    monkeypatch.setattr(engine.repo, "book_partial_exit",
                        lambda cur, pos, fq, px, fee, pnl, reason: booked.update(
                            fill_qty=fq, exit_price=px, pnl=pnl, reason=reason, pid=pos["id"]) or True)
    closed = []
    monkeypatch.setattr(engine.repo, "close_position", lambda *a, **k: closed.append(a))

    @contextmanager
    def _tx(conn):
        yield object()
    monkeypatch.setattr(engine.repo, "transaction", _tx)

    k = _Kernel(fill=3, fill_price=0.44, fee=0.06)
    pos = _pos_full(qty=10, entry=0.50)
    ret = engine._close_position_at(_Conn(), object(), _dep(mode="live"), pos, k, True, 0.44, "drawdown")

    assert ret is False                              # position NOT fully closed
    assert closed == []                              # the full-close path was NOT taken
    assert booked["fill_qty"] == 3 and booked["pid"] == 1 and booked["reason"] == "drawdown"
    # pnl for the 3 sold: 3*(0.44-0.50) - entry_fee*3/10 - fee = -0.18 - 0.30 - 0.06 = -0.54
    assert booked["pnl"] == pytest.approx(3 * (0.44 - 0.50) - 1.0 * 3 / 10 - 0.06)


def test_full_live_exit_closes_the_whole_position(monkeypatch):
    from tests.conftest import patch_intent_passthrough
    patch_intent_passthrough(monkeypatch)  # transparent intent log + a working repo.transaction
    booked = []
    closed = {}
    monkeypatch.setattr(engine.repo, "book_partial_exit", lambda *a, **k: booked.append(a))
    monkeypatch.setattr(engine.repo, "close_position",
                        lambda cur, pid, px, fee, pnl, reason: closed.update(pid=pid, pnl=pnl) or True)
    k = _Kernel(fill=10, fill_price=0.44, fee=0.2)
    ret = engine._close_position_at(_Conn(), object(), _dep(mode="live"), _pos_full(qty=10), k, True, 0.44, "stop")
    assert ret is True and booked == [] and closed["pid"] == 1


def test_paper_exit_always_closes_whole(monkeypatch):
    sold = {}
    monkeypatch.setattr(engine, "_paper_sell", lambda conn, pos, price, reason: sold.update(price=price, reason=reason))
    ret = engine._close_position_at(_Conn(), object(), _dep(mode="paper"), _pos(), None, False, 0.40, "take_profit")
    assert ret is True and sold == {"price": 0.40, "reason": "take_profit"}


def test_book_partial_exit_sql_reduces_and_books(monkeypatch):
    # Repo-layer check against a fake cursor: UPDATE shrinks the open row to the remainder, INSERT
    # books the sold slice as a closed row, and a non-open row (rowcount 0) books nothing.
    from app import repository as repo

    class _FakeCur:
        def __init__(self, update_rowcount=1):
            self.update_rowcount = update_rowcount
            self.rowcount = 0
            self.calls = []

        def execute(self, sql, params=()):
            s = " ".join(sql.split())
            self.calls.append((s, params))
            self.rowcount = self.update_rowcount if s.startswith("UPDATE") else 1

    pos = _pos_full(qty=10, entry=0.50)
    pos["entry_fee"] = 1.0
    cur = _FakeCur()
    assert repo.book_partial_exit(cur, pos, 3, 0.44, 0.06, -0.54, "drawdown") is True
    upd = next(c for c in cur.calls if c[0].startswith("UPDATE"))
    assert upd[1][0] == 7 and upd[1][1] == pytest.approx(0.7)   # qty 10->7, entry_fee 1.0 - 0.3
    ins = next(c for c in cur.calls if c[0].startswith("INSERT"))
    assert "'closed'" in ins[0] and ins[1][5] == 3             # sold slice booked as closed, qty 3

    # Row already gone -> book nothing (idempotent).
    cur0 = _FakeCur(update_rowcount=0)
    assert repo.book_partial_exit(cur0, pos, 3, 0.44, 0.06, -0.54, "drawdown") is False
    assert not any(c[0].startswith("INSERT") for c in cur0.calls)


# -- portfolio caps ------------------------------------------------------------


def _entry(ticker="BTC-NEW", price=0.40):
    close = engine.datetime.now(engine.timezone.utc)
    contract = SimpleNamespace(ticker=ticker, close_time=close)
    return SimpleNamespace(side="yes", price=price, snapshot=SimpleNamespace(contract=contract))


def test_portfolio_position_cap_blocks_a_new_entry(monkeypatch):
    bought = []
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [])
    monkeypatch.setattr(engine.specmod, "entries", lambda spec, snaps: [_entry()])
    monkeypatch.setattr(engine.specmod, "contracts_for", lambda stake, price: 5)
    monkeypatch.setattr(engine, "loss_guard", lambda cur, dep: False)
    monkeypatch.setattr(engine, "_paper_buy", lambda conn, dep, entry, qty: bought.append(qty) or 1)
    monkeypatch.setattr(engine.repo, "user_risk_config",
                        lambda cur, uid: {"drawdown_limit_pct": 25.0, "max_open_positions": 3, "max_open_notional": 1000.0})
    # User already holds 3 open positions across deployments -> the per-user cap blocks any new entry.
    monkeypatch.setattr(engine.repo, "user_open_exposure", lambda cur, uid, mode=None: {"n": 3, "notional": 30.0})

    out = engine.decide(_Conn(), _dep(mode="paper"), [], {}, engine.Sources())
    assert out["entries"] == 0 and bought == []


def test_portfolio_notional_cap_trims_a_new_entry(monkeypatch):
    bought = []
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [])
    monkeypatch.setattr(engine.specmod, "entries", lambda spec, snaps: [_entry(price=0.40)])
    monkeypatch.setattr(engine.specmod, "contracts_for", lambda stake, price: 100)  # wants 100
    monkeypatch.setattr(engine, "loss_guard", lambda cur, dep: False)
    monkeypatch.setattr(engine, "_paper_buy", lambda conn, dep, entry, qty: bought.append(qty) or 1)
    monkeypatch.setattr(engine.repo, "user_risk_config",
                        lambda cur, uid: {"drawdown_limit_pct": 25.0, "max_open_positions": 20, "max_open_notional": 100.0})
    # $96 already open, $4 room, price 0.40 -> only 10 contracts fit under the $100 notional cap.
    monkeypatch.setattr(engine.repo, "user_open_exposure", lambda cur, uid, mode=None: {"n": 1, "notional": 96.0})

    out = engine.decide(_Conn(), _dep(mode="paper"), [], {}, engine.Sources())
    assert out["entries"] == 1 and bought == [10]


def test_a_decision_records_why_it_bought_nothing(monkeypatch):
    from app import spec as specmod
    from app.markets import Contract, snapshot
    from datetime import datetime, timezone
    scans = []
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [])
    monkeypatch.setattr(engine, "loss_guard", lambda cur, dep: False)
    monkeypatch.setattr(engine.repo, "user_risk_config",
                        lambda cur, uid: {"drawdown_limit_pct": 25.0, "max_open_positions": 20, "max_open_notional": 1000.0})
    monkeypatch.setattr(engine.repo, "user_open_exposure", lambda cur, uid, mode=None: {"n": 0, "notional": 0.0})
    monkeypatch.setattr(engine.repo, "set_deployment_scan", lambda cur, dep_id, scan: scans.append((dep_id, scan)))
    ts = 1_800_000_000
    feats = {"spot": 100.0, "ret_1m": 0.0, "ret_5m": 0.0, "ret_15m": 0.0, "ret_60m": 0.0, "vol_15m": 0.001, "vol_60m": 0.001}
    snap = snapshot(feats, Contract("T", 100.0, datetime.fromtimestamp(ts + 600, tz=timezone.utc)), ts, 0.45, 0.47)
    dep = dict(_dep(), spec=specmod.validate({"entry": {"max_tte_min": 3}}))
    out = engine.decide(_Conn(), dep, [snap], {}, engine.Sources())
    assert out["entries"] == 0
    [(dep_id, scan)] = scans
    assert dep_id == 1 and scan["entered"] == 0 and scan["blocked_at"] == "is 1-3 minutes from expiry"
    # A failing readout write never fails the decision.
    monkeypatch.setattr(engine.repo, "set_deployment_scan", lambda *a: (_ for _ in ()).throw(RuntimeError("db")))
    assert engine.decide(_Conn(), dep, [snap], {}, engine.Sources())["entries"] == 0
