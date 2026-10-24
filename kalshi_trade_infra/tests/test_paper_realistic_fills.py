"""Paper must fill the way live fills, or paper results are not evidence for the live gate.

Before this, a paper entry filled the whole size instantly at the quoted price and a paper exit
always succeeded. With a paper kernel wired, paper runs the live MarketableLimitKernel over a
SimulatedVenue: it books only what the touch gave, misses on a stale quote, part-fills exits and
tags each fill so the live gate can count realistic paper trades only.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app import engine
from app import spec as specmod
from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
from data_pipeline.architecture.simulated_venue import SimulatedVenue
from data_pipeline.common import utc_now
from data_pipeline.kalshi_fees import taker_fee_dollars
from data_pipeline.market_data import Quote

TICKER = "KXBTC15M-26SEP271315-15"


def _quote(bid, ask, bid_size=3000.0, ask_size=3000.0):
    return Quote(ticker=TICKER, yes_bid=bid, yes_ask=ask, yes_bid_size=bid_size, yes_ask_size=ask_size,
                 as_of=utc_now() - timedelta(seconds=0.1), source="websocket")


class _Feed:
    def __init__(self, q):
        self.q = q

    def quote(self, ticker, max_age_seconds=None):
        return self.q


def _sim_kernel(q):
    feed = _Feed(q)
    return MarketableLimitKernel(SimulatedVenue(feed), feed, entry_cross_ticks=2, exit_cross_ticks=2,
                                 max_entry_slippage=0.10, max_attempts=3)


# -- venue: the NO leg is the YES mirror, as on the real wire ----------------------


def test_sim_kernel_buys_no_at_the_no_ask():
    k = _sim_kernel(_quote(0.40, 0.42))
    rep = k.execute(TradeIntent(action="buy", side="no", ticker=TICKER, qty_contracts=5, limit_price_dollars=0.60,
                                model_name="m", now_ts=None, metadata={}))
    assert rep.fill_qty_contracts == 5
    assert rep.fill_price_dollars == pytest.approx(0.60), "buy NO costs 1 - yes_bid"


def test_sim_kernel_sells_no_at_the_no_bid():
    k = _sim_kernel(_quote(0.40, 0.42))
    rep = k.execute(TradeIntent(action="sell", side="no", ticker=TICKER, qty_contracts=5, limit_price_dollars=0.58,
                                model_name="m", now_ts=None, metadata={}))
    assert rep.fill_qty_contracts == 5
    assert rep.fill_price_dollars == pytest.approx(0.58), "sell NO pays 1 - yes_ask"


def test_no_buy_is_capped_by_the_yes_bid_size():
    # Buying NO consumes the resting YES bid, so the YES bid size caps it.
    k = _sim_kernel(_quote(0.40, 0.42, bid_size=3.0))
    rep = k.execute(TradeIntent(action="buy", side="no", ticker=TICKER, qty_contracts=10, limit_price_dollars=0.60,
                                model_name="m", now_ts=None, metadata={}))
    assert rep.fill_qty_contracts == 3


# -- engine.decide: paper entries through the simulated venue ---------------------


class _Cur:
    def __init__(self, open_positions=()):
        self.inserted = []
        self.ledger = []
        self.closed = []
        self.rowcount = 0
        self._open = list(open_positions)
        self._last = []
        self.lastrowid = 1

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SELECT * FROM app_positions WHERE deployment_id=%s AND status='open'"):
            self._last = list(self._open)
        elif s.startswith("INSERT INTO app_positions"):
            self.inserted.append(params)
            self.lastrowid = len(self.inserted)
        elif s.startswith("INSERT INTO app_ledger"):
            self.ledger.append(params)
        elif s.startswith("SELECT COALESCE(SUM(amount),0) AS b FROM app_ledger"):
            self._last = [{"b": 1000.0}]
        elif s.startswith("SELECT COALESCE(SUM(pnl),0) AS p FROM app_positions"):
            self._last = [{"p": 0.0}]
        elif s.startswith("SELECT drawdown_limit_pct, position_stop_pct, max_open_positions, max_open_notional"):
            self._last = [{"drawdown_limit_pct": 25.0, "position_stop_pct": 40.0,
                           "max_open_positions": 20, "max_open_notional": 1000.0}]
        elif s.startswith("SELECT COUNT(*) AS n, COALESCE(SUM(qty*entry_price),0) AS notional FROM app_positions"):
            self._last = [{"n": 0, "notional": 0.0}]
        elif s.startswith("UPDATE app_positions SET status='closed'"):
            self.closed.append(params)
            self.rowcount = 1
        else:
            raise AssertionError("unexpected SQL in paper decide path: %s" % s[:100])

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return self._last


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


@pytest.fixture
def tx(monkeypatch):
    @contextmanager
    def _tx(conn):
        yield conn.cursor()
    monkeypatch.setattr(engine.repo, "transaction", _tx)
    monkeypatch.setattr(engine.repo, "lock_user", lambda cur, uid: None)


def _yes_snapshot(bid=0.30, ask=0.31):
    from app.markets import Contract, snapshot

    now = int(datetime.now(timezone.utc).timestamp())
    # Strike far below spot -> P(YES) ~ 1 -> YES is the high-edge side.
    contract = Contract(TICKER, 90.0, datetime.fromtimestamp(now + 5 * 60, tz=timezone.utc))
    feats = {"spot": 100.0, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0,
             "vol_15m": 0.0005, "vol_60m": 0.0005}
    return snapshot(feats, contract, now, bid, ask)


def _paper_dep():
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}, "sizing": {"stake": 5.0}})
    return {"id": 1, "user_id": 1, "market": "btc15m", "mode": "paper", "spec": spec,
            "result": {"capital": 10, "out_of_sample": {"max_drawdown": 3}}}


def test_paper_entry_books_the_simulated_fill_and_tags_it(tx):
    cur = _Cur()
    snap = _yes_snapshot()
    kernel = _sim_kernel(_quote(0.30, 0.31, ask_size=7.0))
    sources = engine.Sources(paper_kernel=lambda uid: kernel)

    out = engine.decide(_Conn(cur), _paper_dep(), [snap], {snap.contract.ticker: 1000.0}, sources)

    assert out["entries"] == 1
    # INSERT params: (dep_id, user_id, mode, ticker, side, qty, entry_price, entry_fee, close, opened, order_ref)
    params = cur.inserted[0]
    assert params[2] == "paper" and params[4] == "yes"
    assert params[5] == 7, "only the size resting at the touch fills"
    assert float(params[6]) == pytest.approx(0.31)
    assert float(params[7]) == pytest.approx(taker_fee_dollars(7, 0.31), abs=1e-5)
    assert str(params[10]).startswith(engine.SIM_ORDER_REF_PREFIX)
    assert cur.ledger, "the paper cash ledger is debited"


def test_paper_entry_with_no_fresh_quote_books_nothing(tx):
    cur = _Cur()
    snap = _yes_snapshot()
    kernel = _sim_kernel(None)  # stale / missing book at execution time
    sources = engine.Sources(paper_kernel=lambda uid: kernel)

    out = engine.decide(_Conn(cur), _paper_dep(), [snap], {snap.contract.ticker: 1000.0}, sources)

    assert out["entries"] == 0
    assert cur.inserted == [] and cur.ledger == []


def test_paper_without_a_kernel_keeps_legacy_instant_fills(tx):
    cur = _Cur()
    snap = _yes_snapshot()
    out = engine.decide(_Conn(cur), _paper_dep(), [snap], {snap.contract.ticker: 1000.0}, engine.Sources())
    assert out["entries"] == 1
    assert cur.inserted[0][10] is None, "a legacy fill carries no simulated order ref"


# -- exits -------------------------------------------------------------------------


def _pos(qty=10):
    return {"id": 9, "user_id": 1, "deployment_id": 1, "mode": "paper", "ticker": TICKER, "side": "yes",
            "qty": qty, "entry_price": 0.30, "entry_fee": 0.10,
            "market_close_time": datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)}


def test_paper_exit_part_fills_and_leaves_the_rest_open(monkeypatch, tx):
    booked = {}
    monkeypatch.setattr(engine.repo, "book_partial_exit",
                        lambda cur, pos, filled, px, fee, pnl, reason: booked.update(filled=filled, px=px) or True)
    credited = []
    monkeypatch.setattr(engine.repo, "add_ledger", lambda cur, uid, kind, amount, memo, pid=None: credited.append(amount))
    cur = _Cur()
    # 2 lots at the bid on each of the 3 escalating attempts -> 6 of 10 sold.
    thin = _sim_kernel(_quote(0.38, 0.40, bid_size=2.0))
    closed = engine._close_position_at(_Conn(cur), cur, _paper_dep(), _pos(qty=10), thin, False, 0.38, "exit")
    assert closed is False, "a part-filled exit leaves the remainder open"
    assert booked["filled"] == 6 and booked["px"] == pytest.approx(0.38)
    assert credited and credited[0] == pytest.approx(6 * 0.38 - 3 * taker_fee_dollars(2, 0.38), abs=1e-4)  # fee per child order


def test_paper_exit_that_fills_across_retries_closes_at_the_fill(tx):
    cur = _Cur()
    # 4 lots per attempt: 4 + 4 + 2 = the whole 10 within the kernel's 3 attempts.
    kernel = _sim_kernel(_quote(0.38, 0.40, bid_size=4.0))
    closed = engine._close_position_at(_Conn(cur), cur, _paper_dep(), _pos(qty=10), kernel, False, 0.38, "exit")
    assert closed is True
    exit_price, exit_fee = cur.closed[0][0], cur.closed[0][1]
    assert exit_price == pytest.approx(0.38)
    assert exit_fee == pytest.approx(2 * taker_fee_dollars(4, 0.38) + taker_fee_dollars(2, 0.38), abs=1e-4)


def test_paper_exit_with_no_bid_does_not_close(tx):
    cur = _Cur()
    closed = engine._close_position_at(_Conn(cur), cur, _paper_dep(), _pos(), _sim_kernel(None), False, 0.38, "exit")
    assert closed is False


def test_paper_force_close_uses_the_paper_kernel():
    k = object()
    assert engine._force_close_kernel({"mode": "paper", "user_id": 1}, engine.Sources(paper_kernel=lambda u: k)) is k
    assert engine._force_close_kernel({"mode": "paper", "user_id": 1}, engine.Sources()) is None


# -- wiring ------------------------------------------------------------------------


def test_paper_kernel_factory_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("APP_PAPER_REALISTIC_FILLS", "0")
    assert engine.paper_kernel_factory(_Conn(_Cur())) is None


def test_paper_kernel_factory_builds_a_simulated_kernel(monkeypatch):
    monkeypatch.delenv("APP_PAPER_REALISTIC_FILLS", raising=False)
    monkeypatch.setattr(engine.repo, "user_execution_config", lambda cur, uid: {})
    make = engine.paper_kernel_factory(_Conn(_Cur()))
    kernel = make(1)
    assert isinstance(kernel, MarketableLimitKernel)
    assert isinstance(kernel._submitter, SimulatedVenue), "paper must never reach a real submitter"


# -- the live gate's evidence query ---------------------------------------------------


def test_paper_round_trips_counts_only_closed_simulated_fills():
    from app import repository as repo

    class Rec:
        def execute(self, sql, params=()):
            self.sql, self.params = " ".join(sql.split()), params

        def fetchall(self):
            return [{"order_ref": "sim:a", "pnl": "1.25", "opened_at": 1, "closed_at": 2}]

    cur = Rec()
    rows = repo.paper_round_trips(cur, 3, 7)
    assert rows == [{"pnl": 1.25, "opened_at": 1, "closed_at": 2}]
    assert "p.mode='paper'" in cur.sql and "LIKE %s" in cur.sql and "GROUP BY p.order_ref" in cur.sql
    assert "status='open'" in cur.sql, "a trade with a slice still open is not a closed round trip"
    assert cur.params == (3, 7, engine.SIM_ORDER_REF_PREFIX + "%")


# -- Road to live: read-only readiness view ------------------------------------------


def _readiness_ctx(monkeypatch, *, strategy=True, candidate=True, trips=(), live=(True, "")):
    from app import agent, server
    monkeypatch.setattr(server.repo, "get_strategy",
                        lambda cur, uid, sid: ({"id": sid, "status": "passed"} if strategy else None))
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: candidate)
    monkeypatch.setattr(agent.repo, "list_deployments", lambda cur, uid, include_stopped=False: [
        {"strategy_id": 7, "mode": "paper", "closed_trades": 40, "realized_pnl": 5.0}])
    monkeypatch.setattr(agent.repo, "paper_round_trips", lambda cur, uid, sid: list(trips))
    monkeypatch.setattr(agent, "live_autopilot_ok", lambda cur, user: live)

    class C:
        def cursor(self):
            return object()
    return server.Ctx(C(), {"id": 1}, ("7",), {}, {}, None)


def test_readiness_reports_progress_and_the_first_blocker(monkeypatch):
    from app import server
    out = server.strategy_live_readiness(_readiness_ctx(monkeypatch, trips=[]))
    assert out["ready"] is False
    assert out["paper"]["trades"] == 0 and out["paper"]["trades_needed"] == 30
    assert "realistic fills" in out["blocking"]
    assert out["paper"]["p_value"] is None


def test_readiness_names_the_gatekeeper_first(monkeypatch):
    from app import server
    out = server.strategy_live_readiness(_readiness_ctx(monkeypatch, candidate=False))
    assert out["ready"] is False and "gatekeeper" in out["blocking"]


def test_readiness_unknown_strategy_is_404(monkeypatch):
    from app import server
    with pytest.raises(server.ApiError) as e:
        server.strategy_live_readiness(_readiness_ctx(monkeypatch, strategy=False))
    assert e.value.status == 404


def test_paper_fill_stats_reports_the_simulated_fill_rate(monkeypatch):
    monkeypatch.delenv("APP_PAPER_REALISTIC_FILLS", raising=False)
    make = engine.paper_kernel_factory(_Conn(_Cur()))
    make.venue.orders_sent, make.venue.orders_filled = 4, 1
    line = engine.paper_fill_stats(make)
    assert "4 orders sent, 1 filled (25%)" in line
    assert engine.paper_fill_stats(None) is None
