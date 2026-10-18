"""Durable order-intent log, exactly-once booking, and crash recovery (EXECUTION_RISK_HARDENING P0).

Money-critical: this is the real-order path. These tests prove, with no live DB and no real orders:
  P0-1  the intent is persisted BEFORE the exchange POST; the persisted client_order_id is the one
        actually sent (so a resend is deduped by Kalshi); crash recovery books a fill EXACTLY ONCE
        and is a no-op on a second pass; an undetermined order is NEVER re-sent (left 'sent').
  P0-2  a filled entry and the cross-pair legs are booked atomically — a crash mid-booking leaves
        NEITHER leg orphaned; booking is idempotent against the intent (recovery vs live race).
  P0-3  the order-placing force-sell claims a position before selling, so two engines never both
        sell it; an exit still flattens even when the intent log write fails.

The engine orchestration is tested against an in-memory Store (repo monkeypatched, with a real
rollback-on-error transaction), and the repo SQL guards against tiny rowcount-aware fake cursors.
"""
import copy
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app import engine
from app import repository as repo
from data_pipeline.architecture.contracts import ExecutionReport, TradeIntent


# -- an in-memory stand-in for the two tables the money path writes --------------


class Store:
    def __init__(self):
        self.intents = {}    # intent_id -> row dict
        self.positions = {}  # id -> row dict
        self._next_pid = 1
        self.events = []     # ordered log of ("intent"|"position"|"execute", key)


def bind_store(monkeypatch, store: Store, kernel=None):
    """Point engine.repo at `store`, with a transaction that really rolls back on error (so the
    atomicity tests are honest). `kernel` records 'execute' into the same event log for ordering."""

    @contextmanager
    def _tx(conn):
        snap = (copy.deepcopy(store.intents), copy.deepcopy(store.positions), store._next_pid)
        try:
            yield SimpleNamespace()  # cursor unused; the shims operate on `store`
        except BaseException:
            store.intents, store.positions, store._next_pid = snap
            raise

    def _insert_intent(cur, intent_id, dep_id, user_id, mode, action, side, ticker, qty, limit_price,
                       client_order_id, position_id=None, reason=None, market_close_time=None):
        store.intents[intent_id] = dict(
            intent_id=intent_id, deployment_id=dep_id, user_id=user_id, mode=mode, action=action,
            side=side, ticker=ticker, qty=int(qty), limit_price=limit_price, client_order_id=client_order_id,
            position_id=position_id, reason=reason, market_close_time=market_close_time, status="sent")
        store.events.append(("intent", intent_id))

    def _mark_intent(cur, intent_id, status, ext=None, fq=None, fp=None, fee=None, raw=None):
        it = store.intents.get(intent_id)
        if it is None:
            return False
        it["status"] = status
        return True

    def _claim_booking(cur, intent_id, ext=None, fq=None, fp=None, fee=None, raw=None):
        it = store.intents.get(intent_id)
        if it is None or it["status"] == "booked":
            return False
        it["status"] = "booked"
        return True

    def _open_sent(cur, older_than_seconds=30, limit=200):
        return [dict(it) for it in store.intents.values() if it["status"] == "sent"]

    def _insert_position(cur, dep_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
                         market_close_time, order_ref=None):
        pid = store._next_pid
        store._next_pid += 1
        store.positions[pid] = dict(
            id=pid, deployment_id=dep_id, user_id=user_id, mode=mode, ticker=ticker, side=side,
            qty=int(qty), entry_price=entry_price, entry_fee=entry_fee, status="open", order_ref=order_ref,
            market_close_time=market_close_time, opened_at=None)
        store.events.append(("position", pid))
        return pid

    def _close_position(cur, position_id, exit_price, exit_fee, pnl, reason):
        p = store.positions.get(position_id)
        if p is None or p["status"] != "open":
            return False
        p.update(status="closed", exit_price=exit_price, exit_fee=exit_fee, pnl=pnl, close_reason=reason)
        return True

    def _book_partial(cur, pos, fill_qty, exit_price, exit_fee, pnl, reason):
        p = store.positions.get(pos["id"])
        if p is None or p["status"] != "open":
            return False
        p["qty"] = int(p["qty"]) - int(fill_qty)
        pid = store._next_pid
        store._next_pid += 1
        store.positions[pid] = dict(id=pid, deployment_id=pos["deployment_id"], status="closed",
                                    qty=int(fill_qty), side=pos["side"], ticker=pos["ticker"])
        return True

    def _get_position(cur, position_id):
        p = store.positions.get(position_id)
        return dict(p) if p else None

    def _open_positions(cur, dep_id):
        return [dict(p) for p in store.positions.values()
                if p["status"] == "open" and p["deployment_id"] == dep_id]

    monkeypatch.setattr(repo, "transaction", _tx)
    monkeypatch.setattr(repo, "insert_order_intent", _insert_intent)
    monkeypatch.setattr(repo, "mark_order_intent", _mark_intent)
    monkeypatch.setattr(repo, "claim_intent_booking", _claim_booking)
    monkeypatch.setattr(repo, "open_sent_intents", _open_sent)
    monkeypatch.setattr(repo, "insert_position", _insert_position)
    monkeypatch.setattr(repo, "close_position", _close_position)
    monkeypatch.setattr(repo, "book_partial_exit", _book_partial)
    monkeypatch.setattr(repo, "get_position", _get_position)
    monkeypatch.setattr(repo, "open_positions", _open_positions)


class _Conn:
    def cursor(self):
        return SimpleNamespace()


class _Kernel:
    """Records every intent it executes (into the Store event log too, for ordering) and returns a
    configurable fill. fill=None => whole order; raises=True => the POST raises (lost response)."""

    def __init__(self, store=None, fill=None, fill_price=None, fee=0.05, raises=False):
        self.store = store
        self.fill = fill
        self.fill_price = fill_price
        self.fee = fee
        self.raises = raises
        self.intents = []

    def execute(self, intent):
        self.intents.append(intent)
        if self.store is not None:
            self.store.events.append(("execute", intent.ticker))
        if self.raises:
            raise RuntimeError("POST timed out after the exchange matched it")
        qty = intent.qty_contracts if self.fill is None else self.fill
        px = intent.limit_price_dollars if self.fill_price is None else self.fill_price
        return ExecutionReport(accepted=qty > 0, status="filled" if qty >= intent.qty_contracts else "partially_filled",
                               fill_price_dollars=px, fill_qty_contracts=qty, external_order_id="ord-1",
                               client_order_id=(intent.metadata or {}).get("client_order_id"), fee_dollars=self.fee)


def _dep(mode="live"):
    return {"id": 1, "user_id": 1, "mode": mode, "market": "btc15m",
            "spec": {"side": "yes", "sizing": {"stake": 5.0, "max_positions": 20}}}


def _pos_full(pid=1, qty=10, entry=0.50, side="yes"):
    return {"id": pid, "deployment_id": 1, "user_id": 1, "mode": "live", "ticker": "BTC-%d" % pid,
            "side": side, "qty": qty, "entry_price": entry, "entry_fee": 1.0, "mark_price": 0.40,
            "market_close_time": "2026-01-01 00:00:00", "opened_at": "2026-01-01 00:00:00", "order_ref": "o1",
            "status": "open"}


# -- P0-1: the intent is durable BEFORE the POST ---------------------------------


def test_intent_is_logged_before_the_order_is_placed(monkeypatch):
    store = Store()
    k = _Kernel(store=store, fill_price=0.44)
    bind_store(monkeypatch, store, k)
    engine._close_position_at(_Conn(), SimpleNamespace(), _dep("live"), _pos_full(), k, True, 0.44, "stop")
    # The durable record of the order exists BEFORE the exchange ever saw it: 'intent' precedes 'execute'.
    kinds = [e[0] for e in store.events]
    assert kinds.index("intent") < kinds.index("execute")


def test_persisted_client_order_id_is_threaded_to_the_submitter():
    # The id we persisted is the id Kalshi receives, so a resend is deduped by client_order_id.
    from data_pipeline.market_data import Quote
    from data_pipeline.common import utc_now
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel

    sent = []

    def submitter(ticker, action, side, qty, price, client_order_id=None):
        sent.append(client_order_id)
        return {"client_order_id": client_order_id, "body": {},
                "resp": {"fill_count": "%d.00" % qty, "average_fill_price": "%.4f" % price,
                         "average_fee_paid": "0.0100", "order_id": "o"}}

    q = Quote(ticker="T", yes_bid=0.70, yes_ask=0.71, yes_bid_size=9999.0, yes_ask_size=9999.0,
              as_of=utc_now(), source="websocket")

    class _Feed:
        def quote(self, ticker, max_age_seconds=None):
            return q

    k = MarketableLimitKernel(submitter, _Feed(), entry_cross_ticks=1, max_entry_slippage=0.5)
    intent = TradeIntent(action="buy", side="yes", ticker="T", qty_contracts=5, limit_price_dollars=0.70,
                         model_name="m", now_ts=None, metadata={"client_order_id": "INTENT-123"})
    k.execute(intent)
    assert sent == ["INTENT-123"]  # the persisted intent id, not a fresh uuid


def test_place_limit_order_reuses_a_provided_client_order_id(monkeypatch):
    # A retry with the same persisted id sends the SAME client_order_id both times (idempotent POST).
    from data_pipeline import live_trading_engine as lte

    bodies = []
    monkeypatch.setattr(lte, "api_post_auth", lambda path, body, **k: bodies.append(body) or {"fill_count": "0.00"})
    lte.place_limit_order("T", "buy", "yes", 3, 0.50, client_order_id="REUSE-ME")
    lte.place_limit_order("T", "buy", "yes", 3, 0.50, client_order_id="REUSE-ME")
    assert [b["client_order_id"] for b in bodies] == ["REUSE-ME", "REUSE-ME"]


# -- P0-1: crash recovery books a fill exactly once ------------------------------


def test_recovery_books_a_filled_entry_exactly_once_and_is_idempotent(monkeypatch):
    # Crash AFTER the buy filled, BEFORE the position row was written: the intent is left 'sent'.
    store = Store()
    bind_store(monkeypatch, store)
    store.intents["i1"] = dict(intent_id="i1", deployment_id=1, user_id=1, mode="live", action="buy",
                               side="yes", ticker="BTC-1", qty=10, client_order_id="i1", position_id=None,
                               reason=None, market_close_time="2026-01-01 00:00:00", status="sent")
    lookup = lambda it: {"filled": 10, "avg_price": 0.42, "fee": 0.06, "order_id": "ord-9"}
    sources = engine.Sources(order_lookup=lookup)

    assert engine.recover_sent_intents(_Conn(), sources, older_than_seconds=0) == 1
    assert len(store.positions) == 1                       # the orphaned fill is now booked
    assert store.intents["i1"]["status"] == "booked"
    # Second pass: the intent is 'booked', so open_sent_intents yields nothing -> no second position.
    assert engine.recover_sent_intents(_Conn(), sources, older_than_seconds=0) == 0
    assert len(store.positions) == 1                       # booked EXACTLY once


def test_recovery_marks_an_unfilled_order_and_books_nothing(monkeypatch):
    store = Store()
    bind_store(monkeypatch, store)
    store.intents["i1"] = dict(intent_id="i1", deployment_id=1, user_id=1, mode="live", action="buy",
                               side="yes", ticker="BTC-1", qty=10, client_order_id="i1", position_id=None,
                               reason=None, market_close_time=None, status="sent")
    sources = engine.Sources(order_lookup=lambda it: {"filled": 0})
    assert engine.recover_sent_intents(_Conn(), sources, older_than_seconds=0) == 1
    assert store.positions == {}
    assert store.intents["i1"]["status"] == "unfilled"


def test_recovery_leaves_an_indeterminate_intent_sent_and_never_resends(monkeypatch):
    # The exchange couldn't tell us -> NEVER re-send; leave 'sent' for the next pass / a human.
    store = Store()
    bind_store(monkeypatch, store)
    store.intents["i1"] = dict(intent_id="i1", deployment_id=1, user_id=1, mode="live", action="buy",
                               side="yes", ticker="BTC-1", qty=10, client_order_id="i1", position_id=None,
                               reason=None, market_close_time=None, status="sent")
    sources = engine.Sources(order_lookup=lambda it: None)  # indeterminate
    assert engine.recover_sent_intents(_Conn(), sources, older_than_seconds=0) == 0
    assert store.positions == {}
    assert store.intents["i1"]["status"] == "sent"


def test_recovery_closes_a_filled_exit_once(monkeypatch):
    # Crash after the SELL filled, before close_position: the open row + a 'sent' exit intent remain.
    store = Store()
    bind_store(monkeypatch, store)
    store.positions[7] = _pos_full(pid=7, qty=10, entry=0.50)
    store.positions[7]["deployment_id"] = 1
    store.intents["x1"] = dict(intent_id="x1", deployment_id=1, user_id=1, mode="live", action="sell",
                               side="yes", ticker="BTC-7", qty=10, client_order_id="x1", position_id=7,
                               reason="drawdown", market_close_time=None, status="sent")
    sources = engine.Sources(order_lookup=lambda it: {"filled": 10, "avg_price": 0.60, "fee": 0.05, "order_id": "o"})
    assert engine.recover_sent_intents(_Conn(), sources, older_than_seconds=0) == 1
    assert store.positions[7]["status"] == "closed"
    # Idempotent: a second pass closes nothing more (intent booked, position already closed).
    assert engine.recover_sent_intents(_Conn(), sources, older_than_seconds=0) == 0
    assert store.positions[7]["status"] == "closed"


# -- P0-2: atomic booking --------------------------------------------------------


def test_pair_legs_are_atomic_a_crash_between_them_leaves_neither(monkeypatch):
    # Both leg orders are placed, then both position inserts share ONE transaction. A failure on the
    # second insert must roll back the first — never one naked leg in the book (closes F5).
    store = Store()
    k = _Kernel(store=store, fill_price=0.40)
    bind_store(monkeypatch, store, k)

    real_insert = repo.insert_position
    calls = {"n": 0}

    def _boom_on_second(cur, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("crash between the two leg inserts")
        return real_insert(cur, *a, **kw)
    monkeypatch.setattr(repo, "insert_position", _boom_on_second)

    # 5-tuple legs (with the own-side unwind price): both fill fully -> hedged pair, no unwind, so
    # exactly two position inserts share one transaction and the 2nd failing rolls back the 1st.
    legs = [("yes", "BTC-A", 0.40, 0.38, "2026-01-01 00:00:00"),
            ("no", "BTC-B", 0.55, 0.43, "2026-01-01 00:00:00")]
    with pytest.raises(RuntimeError):
        engine._kernel_buy_pair(_Conn(), SimpleNamespace(), _dep("demo"), k, legs, 5, "demo")
    assert store.positions == {}           # NEITHER leg booked (both-or-nothing)
    assert len(k.intents) == 2             # ...even though both orders WERE sent to the exchange


def test_filled_entry_is_not_double_booked_when_the_intent_is_already_booked(monkeypatch):
    # If recovery already booked an intent, the live path's claim loses and inserts no second row.
    store = Store()
    bind_store(monkeypatch, store)
    store.intents["i1"] = dict(intent_id="i1", status="booked")  # already booked by recovery
    rep = SimpleNamespace(fill_qty_contracts=10, fill_price_dollars=0.42, fee_dollars=0.05,
                          external_order_id="o", raw_json=None)
    assert engine._book_entry(_Conn(), "i1", 1, 1, "live", "BTC-1", "yes", rep, None) is False
    assert store.positions == {}


# -- P0-2/P0-3: exits are never blocked by the intent machinery ------------------


def test_exit_still_flattens_when_the_intent_log_write_fails(monkeypatch):
    # The durable-intent write is best-effort for an EXIT: if it fails, we STILL sell and close.
    store = Store()
    k = _Kernel(store=store, fill_price=0.44)
    bind_store(monkeypatch, store, k)
    store.positions[1] = _pos_full(pid=1, qty=10, entry=0.50)

    def _boom(*a, **kw):
        raise RuntimeError("intent table unavailable")
    monkeypatch.setattr(repo, "insert_order_intent", _boom)

    ok = engine._close_position_at(_Conn(), SimpleNamespace(), _dep("live"), store.positions[1], k, True, 0.44, "stop")
    assert ok is True                              # the exit flattened anyway
    assert store.positions[1]["status"] == "closed"
    assert len(k.intents) == 1 and k.intents[0].action == "sell"


# -- repo SQL guards (rowcount-exact) --------------------------------------------


class _IntentCur:
    def __init__(self, status="sent"):
        self.status = status
        self.rowcount = 0

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("UPDATE app_order_intents SET status='booked'"):
            self.rowcount = 1 if self.status != "booked" else 0
            if self.rowcount:
                self.status = "booked"
        else:
            self.rowcount = 0


def test_claim_intent_booking_wins_once_then_loses():
    cur = _IntentCur(status="sent")
    assert repo.claim_intent_booking(cur, "i1") is True    # first booker wins
    assert repo.claim_intent_booking(cur, "i1") is False   # already booked -> loser books nothing


class _PosClaimCur:
    def __init__(self, claim=None, claim_ts=None, status="open"):
        self.claim, self.claim_ts, self.status, self.rowcount = claim, claim_ts, status, 0

    def execute(self, sql, params=()):
        claimant, now, _pid, claimant2, cutoff = params
        won = self.status == "open" and (
            self.claim is None or self.claim == claimant or (self.claim_ts is not None and self.claim_ts < cutoff))
        if won:
            self.claim, self.claim_ts, self.rowcount = claimant, now, 1
        else:
            self.rowcount = 0


def test_claim_position_close_leases_to_one_engine():
    cur = _PosClaimCur()                                   # unclaimed, open
    assert repo.claim_position_close(cur, 1, "engine-A") is True
    # A different engine within the lease cannot steal it -> no second concurrent force-sell.
    assert repo.claim_position_close(cur, 1, "engine-B") is False
    # The owner can re-claim its own lease to retry.
    assert repo.claim_position_close(cur, 1, "engine-A") is True


def test_claim_position_close_refuses_a_closed_position():
    cur = _PosClaimCur(status="closed")
    assert repo.claim_position_close(cur, 1, "engine-A") is False
