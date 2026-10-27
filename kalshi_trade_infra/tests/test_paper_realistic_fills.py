"""Paper must fill the way live fills, or paper results are not evidence for the live gate.

Before this, a paper entry filled the whole size instantly at the quoted price and a paper exit
always succeeded. With a paper kernel wired, paper runs the live MarketableLimitKernel over a
SimulatedVenue: it books only what the touch gave, misses on a stale quote, part-fills exits and
tags each fill so the live gate can count realistic paper trades only.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.trading import engine
from app.trading import spec as specmod
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
    from app.trading.markets import Contract, snapshot

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
            return [{"order_ref": "sim:a", "pnl": "1.25", "opened_at": 1, "closed_at": 2, "ticker": "KXSOL15M-A-1"}]

    cur = Rec()
    rows = repo.paper_round_trips(cur, 3, 7)
    assert rows == [{"pnl": 1.25, "opened_at": 1, "closed_at": 2, "ticker": "KXSOL15M-A-1"}]
    assert "p.mode='paper'" in cur.sql and "LIKE %s" in cur.sql and "GROUP BY p.order_ref" in cur.sql
    assert "status='open'" in cur.sql, "a trade with a slice still open is not a closed round trip"
    assert cur.params == (3, 7, engine.SIM_ORDER_REF_PREFIX + "%")


def test_paper_progress_groups_round_trips_per_strategy_in_one_query():
    from app import repository as repo

    class Rec:
        calls = 0

        def execute(self, sql, params=()):
            Rec.calls += 1
            self.sql, self.params = " ".join(sql.split()), params

        def fetchall(self):
            return [{"strategy_id": 7, "trips": 12, "pnl": "3.5"}]

    cur = Rec()
    assert repo.paper_progress(cur, 3, []) == {} and Rec.calls == 0
    assert repo.paper_progress(cur, 3, [7, 9]) == {7: (12, 3.5)}
    assert Rec.calls == 1
    assert "GROUP BY d.strategy_id, p.order_ref" in cur.sql and "status='open'" in cur.sql
    assert "IN (%s,%s)" in cur.sql
    assert cur.params == (3, engine.SIM_ORDER_REF_PREFIX + "%", 7, 9)


def test_autopilot_status_reports_paper_strategy_closest_to_live(monkeypatch):
    from types import SimpleNamespace
    from app import server
    from app.research import agent
    ctx = server.Ctx(SimpleNamespace(cursor=lambda: object()),
                     {"id": 7, "email": "t@example.invalid", "name": "S", "picture_url": None,
                      "autopilot": 1, "autopilot_live": 0, "autopilot_daily_loss_limit": 50,
                      "autopilot_model": None}, (), {}, {}, SimpleNamespace())
    deps = [{"mode": "paper", "status": "running", "strategy_id": 1, "title": "Slow",
             "created_at": server.repo.now_utc().replace(tzinfo=None) - __import__("datetime").timedelta(hours=72),
             "result": {"in_sample": {"trades_per_day": 0.5}}},
            {"mode": "paper", "status": "running", "strategy_id": 2, "title": "Fast"},
            {"mode": "live", "status": "running", "strategy_id": 3, "title": "Live"}]
    from tests.autopilot_status_parts import stub_merged_reads
    stub_merged_reads(monkeypatch)
    monkeypatch.setattr(server.repo, "list_deployments_brief", lambda *a: deps)
    monkeypatch.setattr(server.repo, "positions_version", lambda *a: (17, 13, 40))  # a book: its sums are read
    monkeypatch.setattr(server.repo, "deployment_strategies", lambda *a: {})
    monkeypatch.setattr(server.repo, "engine_last_tick_age_seconds", lambda cur: 20)
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda *a: None)
    monkeypatch.setattr(server.repo, "realized_pnl_by_mode",
                        lambda cur, uid, modes, since: {m: {"live": -2.0, "paper": 1.234}[m] for m in modes})
    monkeypatch.setattr(server.repo, "last_autopilot_action", lambda *a: None)
    monkeypatch.setattr(server.repo, "last_review_at", lambda *a: None)
    monkeypatch.setattr(server.repo, "active_agent_run", lambda *a: None)
    monkeypatch.setattr(server.billing, "configured", lambda: False)
    monkeypatch.setattr(server.repo, "list_runs", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "research_week", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "research_spent_since", lambda *a, **k: 0.0)
    monkeypatch.setattr(server.repo, "autopilot_paper_week", lambda *a, **k: {"started": 0, "pnl": 0.0, "trades": 0})
    monkeypatch.setattr(server.repo, "strategies_passed_since", lambda *a, **k: 0)
    seen = {}
    monkeypatch.setattr(server.repo, "paper_progress",
                        lambda cur, uid, sids: seen.setdefault("sids", sids) and {1: (4, 9.0), 2: (11, -1.0)})
    monkeypatch.setattr(server.repo, "user_open_exposure",
                        lambda cur, uid, mode=None: {"n": 4 if mode == "paper" else 9, "notional": 3.0})
    monkeypatch.setattr(server.repo, "paper_event_counts", lambda cur, uid, sids: {1: 4, 2: 1})
    out = server.autopilot_status(ctx)
    assert out["paper_open"] == 4, "open PAPER positions only"
    assert (out["today_live_pnl"], out["today_paper_pnl"]) == (-2.0, 1.23), "each book's own day"
    assert seen["sids"] == [1, 2], "only running paper strategies are counted"
    assert out["paper_progress"] == {"strategy_id": 2, "title": "Fast", "trades": 11,
                                     "trades_needed": agent.MIN_REALISTIC_PAPER_TRADES,
                                     "net_pnl": -1.0, "strategies": 2,
                                     # Slow: 4 trips in 72h is 1.33/day -> 26 more in 19.5 days. Fast has no pace.
                                     "soonest_days": 19.5, "soonest_title": "Slow"}


def test_autopilot_status_reports_research_activity(monkeypatch):
    from datetime import timedelta
    from app import server
    now = server.repo.now_utc()
    runs = [{"market": "nhl_game", "status": "running", "created_at": now, "hypotheses_tried": 0, "strategies_passed": 0},
            {"market": None, "status": "queued", "created_at": now, "hypotheses_tried": 0, "strategies_passed": 0},
            {"market": "btc15m", "status": "succeeded", "created_at": now - timedelta(days=1),
             "hypotheses_tried": 9, "strategies_passed": 1},
            {"market": "btc15m", "status": "succeeded", "created_at": now - timedelta(days=9),
             "hypotheses_tried": 50, "strategies_passed": 3}]
    from tests.autopilot_status_parts import stub_merged_reads
    stub_merged_reads(monkeypatch)
    monkeypatch.setattr(server.repo, "list_runs", lambda cur, uid, limit=50: runs)
    # The week is one aggregate per model (Todd's prod week: 277 runs, the 50-run list saw 73 ideas).
    week = [{"model": "sonnet-4-5", "runs": 250, "tried": 2400, "passed": 68, "input_tokens": 10_000_000, "output_tokens": 1_000_000},
            {"model": None, "runs": 27, "tried": 268, "passed": 0, "input_tokens": 0, "output_tokens": 0}]
    seen = []
    monkeypatch.setattr(server.repo, "research_week", lambda cur, uid, since: seen.append(since) or week)
    monkeypatch.setattr(server.repo, "strategies_passed_since", lambda cur, uid, since: 1)
    # The week's pass, judged for a later check: nothing left it uncleared (test_hot_endpoint_query_budget
    # covers one that did).
    monkeypatch.setattr(server.repo, "passed_strategies", lambda cur, uid, **k: [])
    # The week's cost is what the ledger debited for research, never the week's tokens re-priced.
    spent = []
    monkeypatch.setattr(server.repo, "research_spent_since", lambda cur, uid, since: spent.append(since) or 12.3456)
    out = server._research_activity(None, 7)
    assert out["active"] == [server.MARKETS["nhl_game"].label, "a market it’s still picking"]
    assert (out["tested_7d"], out["passed_7d"], out["runs_7d"]) == (2668, 1, 277)
    assert out["cost_7d"] == 12.35
    assert abs((now - seen[0]).total_seconds() - 7 * 86400) < 5 and spent == seen  # one window for both
    story = server._autopilot_story({"autopilot": True, "research": dict(out, active=["a market it’s still picking"])})
    assert story[0] == "Right now it’s picking a market to research."
    assert story[1] == "This week it tested 2,668 ideas for ${:,.2f} and 1 passed.".format(out["cost_7d"])


def test_the_story_says_a_pass_a_later_check_left_uncleared_apart_from_what_passed():
    """passed_7d counts only passes cleared to trade; one whose holdout then failed or that the
    diversification check held back (not_cleared_7d) is said apart, never as passed."""
    from app import server

    def line(passed, fell):
        return server._autopilot_story({"autopilot": True, "research": {
            "active": [], "tested_7d": 12, "passed_7d": passed, "not_cleared_7d": fell}})[1]
    assert line(1, 0) == "This week it tested 12 ideas and 1 passed."
    assert line(1, 1) == "This week it tested 12 ideas and 1 passed, and 1 more passed but wasn’t cleared to trade."
    assert line(2, 3) == "This week it tested 12 ideas and 2 passed, and 3 more passed but weren’t cleared to trade."
    assert line(0, 2) == ("This week it tested 12 ideas and none has been cleared to trade yet: 2 passed, but a later "
                          "check didn’t clear them. Each one’s page says which check.")
    assert line(0, 1).endswith("1 passed, but a later check didn’t clear it. Each one’s page says which check.")
    assert "none has passed its tests yet" in line(0, 0)


def test_research_activity_counts_only_runs_that_are_working_now(monkeypatch):
    """A paused run isn't researching, and a running run silent past the reaper's limit (its worker
    died) is not either: both left "Right now it’s researching ..." on every page after the work stopped."""
    from datetime import timedelta
    from app import server
    now = server.repo.now_utc()
    stale = now - timedelta(seconds=server.RUN_OVERDUE_SECONDS + 60)
    runs = [{"market": "nhl_game", "status": "running", "created_at": now, "started_at": now, "heartbeat_at": now},
            {"market": "btc15m", "status": "running", "created_at": stale, "started_at": stale, "heartbeat_at": stale},
            {"market": "eth15m", "status": "paused", "created_at": now, "started_at": now, "heartbeat_at": now},
            {"market": "high_ny", "status": "queued", "created_at": stale, "heartbeat_at": None}]
    from tests.autopilot_status_parts import stub_merged_reads
    stub_merged_reads(monkeypatch)
    monkeypatch.setattr(server.repo, "list_runs", lambda cur, uid, limit=50: runs)
    monkeypatch.setattr(server.repo, "research_week", lambda cur, uid, since: [])
    monkeypatch.setattr(server.repo, "strategies_passed_since", lambda cur, uid, since: 0)
    monkeypatch.setattr(server.repo, "research_spent_since", lambda cur, uid, since: 0.0)
    out = server._research_activity(None, 7)
    # A queued run is waiting for a worker (the reaper never stops one), so it still counts.
    assert out["active"] == [server.MARKETS["nhl_game"].label, server.MARKETS["high_ny"].label]
    runs[:] = runs[1:3]
    assert server._research_activity(None, 7)["active"] == []
    assert server._autopilot_now({"research": server._research_activity(None, 7)}).startswith("Right now it’s between research runs.")


def test_active_run_counts_can_leave_out_a_run_whose_worker_went_quiet():
    """The dashboard's "1 agent researching" counted a running run whose worker died, beside an
    autopilot card saying it was between research runs. With silent_before it drops those."""
    from datetime import datetime
    from app import repository as repo, server

    class Cur:
        def __init__(self):
            self.sql = self.params = None

        def execute(self, sql, params):
            self.sql, self.params = " ".join(sql.split()), params

        def fetchall(self):
            return [{"kind": "research", "status": "running", "n": 1}]

    cur = Cur()
    assert repo.active_run_counts(cur, 7)["research_running"] == 1 and cur.params == (7,)
    assert "heartbeat_at" not in cur.sql
    cut = datetime(2026, 10, 26, 5, 0)
    repo.active_run_counts(cur, 7, silent_before=cut)
    assert cur.params == (7, cut)
    assert "NOT (status='running' AND COALESCE(heartbeat_at, started_at, created_at) < %s)" in cur.sql
    age = (server.repo.now_utc() - server._silent_before()).total_seconds()
    assert abs(age - server.RUN_OVERDUE_SECONDS) < 5


def test_autopilot_story_says_what_it_is_doing_in_plain_words():
    from app import server
    d = {"autopilot": True, "paper_running": 3, "live_running": 0,
         "paper_progress": {"trades": 0, "trades_needed": 30, "net_pnl": 0.0},
         "research": {"active": ["NYC daily high temperature", "NYC daily high temperature", "NHL Game"],
                      "tested_7d": 8, "passed_7d": 0}}
    story = server._autopilot_story(d)
    assert story[0] == "Right now it’s researching NYC daily high temperature and NHL Game."
    assert "tested 8 ideas" in story[1] and "most ideas fail" in story[1]
    assert "3 strategies are on paper" in story[2] and "none has traded yet" in story[2]
    assert "%d trades" % server.agent.MIN_REALISTIC_PAPER_TRADES in story[3] and "live autopilot" in story[3]
    # Progress, idle research, and the off / billing-blocked states.
    d2 = dict(d, research={"active": [], "tested_7d": 0, "passed_7d": 0},
              paper_progress={"trades": 4, "trades_needed": 30, "net_pnl": -1.5})
    story = server._autopilot_story(d2)
    assert story[0].startswith("Right now it’s between research runs")
    assert "4 of the 30 realistic paper trades live needs and is down $1.50 on them net of fees and spread, across all its paper runs" in story[1]
    assert "from %d separate events" % server.agent.MIN_PAPER_EVENTS in story[-1]
    soon = server._autopilot_story(dict(d2, paper_progress=dict(d2["paper_progress"], soonest_days=6.6,
                                                                soonest_title="Rain over NYC — v2")))
    assert soon[2] == ("At the pace they trade, the soonest one could have enough for the live check is about 7 days "
                       "(Rain over NYC), and only if it’s up by then.")
    assert "about a day" in server._autopilot_story(dict(d2, paper_progress=dict(
        d2["paper_progress"], soonest_days=1.2, soonest_title="X")))[2]
    # Bought but not settled: it says so instead of "none has traded yet".
    story = server._autopilot_story(dict(d, paper_open=4))
    assert story[2] == "3 strategies are on paper (pretend money). 4 positions are open, waiting to settle; none has closed yet."
    assert server._autopilot_story(dict(d, paper_running=1, paper_open=1))[2].startswith(
        "1 strategy is on paper (pretend money). 1 position is open")
    assert server._autopilot_story({"autopilot": False})[0].startswith("Autopilot is off.")
    assert server._autopilot_story(dict(d, billing_blocked=True)) == []
    assert "1 strategy is trading real money." in server._autopilot_story(dict(d, live_running=1, live_enabled=True))
    # With the server's live switch closed a running live strategy places no orders: it waits, never "trading".
    closed = server._autopilot_story(dict(d, live_running=1, live_enabled=False))
    assert "1 strategy is live but waiting: live trading isn’t open yet, so it places no orders." in closed
    assert not any("trading real money" in line for line in closed)
    assert "2 strategies are live but waiting: live trading isn’t open yet, so they place no orders." in \
        server._autopilot_story(dict(d, live_running=2))
    assert server._autopilot_story(d)[-1].endswith("and you turn on live autopilot. Live trading isn’t open yet.")
    assert server._autopilot_story(dict(d, live_enabled=True))[-1].endswith("and you turn on live autopilot.")
    why = "no open contract costs 85c to 95c (of 12; nearest is 3c outside)"
    waiting = [{"title": "SOL momentum", "why": why}]
    story = server._autopilot_story(dict(d, paper_waiting=waiting))
    assert "SOL momentum is waiting: No open contract costs 85c to 95c (of 12; nearest is 3c outside)." in story
    assert not any("Each one waits" in line for line in story)
    waiting = [dict(waiting[0], checks_today=14, qualified_today=0),
               {"title": "SOL calm", "why": why, "checks_today": 14, "qualified_today": 0}]
    story = server._autopilot_story(dict(d, paper_waiting=waiting))
    assert ("SOL momentum and SOL calm are waiting: No open contract costs 85c to 95c (of 12; nearest is 3c outside). "
            "Since 00:00 UTC, none of 28 checks found a contract worth buying.") in story


def test_paper_waiting_lists_strategies_whose_last_decision_bought_nothing():
    from app import server
    run = [{"id": 74, "title": "Solana Deep ITM Momentum — Trend Intact", "last_scan_at": None,
            "scan": {"why": "none of the 3 open contracts has spread of 5c or less", "entered": 0, "qualifying": 0}},
           {"id": 75, "title": "Bought", "scan": {"why": "2 of 3 open contracts qualify", "entered": 1, "qualifying": 2}},
           {"id": 76, "title": "Old", "scan": None}]
    assert server._paper_waiting(run) == [{"deployment_id": 74, "title": "Solana Deep ITM Momentum",
                                           "why": "none of the 3 open contracts has spread of 5c or less",
                                           "blocked_at": None, "at": None, "checks_today": 0, "qualified_today": 0}]
    tally = {74: {"qualified": 2, "the spread": 10}}
    assert server._paper_waiting(run, tally)[0]["checks_today"] == 12


# -- Road to live: read-only readiness view ------------------------------------------


def _readiness_ctx(monkeypatch, *, strategy=True, candidate=True, trips=(), live=(True, ""), running=()):
    from app import server
    from app.research import agent
    monkeypatch.setattr(server.repo, "get_strategy",
                        lambda cur, uid, sid: ({"id": sid, "status": "passed"} if strategy else None))
    monkeypatch.setattr(server.repo, "list_deployments_brief", lambda cur, uid: list(running))
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: candidate)
    monkeypatch.setattr(agent.repo, "list_deployments", lambda cur, uid, include_stopped=False: [
        {"strategy_id": 7, "mode": "paper", "closed_trades": 40, "realized_pnl": 5.0}])
    monkeypatch.setattr(agent.repo, "paper_round_trips", lambda cur, uid, sid: list(trips))
    monkeypatch.setattr(agent, "live_autopilot_ok", lambda cur, user: live)
    monkeypatch.setattr(agent.demo_record, "demo_evidence", lambda cur, uid, sid: {
        "ok": False, "why": "no demo orders", "orders": 0, "orders_needed": 20, "unresolved": 0,
        "mismatched_tickers": [], "last_check_at": None})

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
    assert out["paper"]["checks"]["demo"] is False and out["paper"]["demo_orders_needed"] == 20


def test_readiness_names_the_gatekeeper_first(monkeypatch):
    from app import server
    out = server.strategy_live_readiness(_readiness_ctx(monkeypatch, candidate=False))
    assert out["ready"] is False and "gatekeeper" in out["blocking"]


def test_readiness_says_when_the_counts_could_be_in_at_its_pace(monkeypatch):
    from app import server
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # 12 trips over 30h of a running paper deployment: 9.6 a day, 18 to go -> about 1.9 days.
    t0 = now - timedelta(hours=29)
    trips = [{"pnl": 0.2, "opened_at": t0 + timedelta(hours=2 * i), "closed_at": t0 + timedelta(hours=2 * i, minutes=14),
              "ticker": "KXBTC15M-%d-1" % i} for i in range(12)]
    running = [{"id": 1, "strategy_id": 7, "mode": "paper", "status": "running", "created_at": now - timedelta(hours=30),
                "result": {"in_sample": {"trades_per_day": 50}}}]
    out = server.strategy_live_readiness(_readiness_ctx(monkeypatch, trips=trips, running=running))
    assert out["pace"]["running"] is True and out["pace"]["rate_from"] == "paper"
    assert out["pace"]["trades_per_day"] == 9.6 and out["pace"]["eta_days"] == 1.9
    # The gate's own answer is unchanged by the readout.
    assert out["ready"] is False and "realistic fills" in out["blocking"]


def test_readiness_has_no_pace_when_nothing_runs_on_paper(monkeypatch):
    from app import server
    paused = [{"id": 1, "strategy_id": 7, "mode": "paper", "status": "paused", "created_at": datetime.now(timezone.utc).replace(tzinfo=None)}]
    out = server.strategy_live_readiness(_readiness_ctx(monkeypatch, running=paused))
    assert out["pace"] == {"running": False, "eta_days": None, "trades_per_day": None, "rate_from": None}


def test_deploy_roads_count_the_record_as_road_to_live_does(monkeypatch):
    from app import server
    from app.research import agent
    server._ROADS.clear(); server._FAILING.clear()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    t0 = now - timedelta(hours=60)
    # Two strikes of one event are one event; the span is first entry to last exit.
    few = [{"pnl": 0.1, "opened_at": t0, "closed_at": t0 + timedelta(minutes=10), "ticker": "KXR-26OCT01-A"},
           {"pnl": 0.1, "opened_at": t0 + timedelta(hours=1), "closed_at": t0 + timedelta(hours=10), "ticker": "KXR-26OCT01-B"}]
    many = [{"pnl": 0.3, "opened_at": t0 + timedelta(hours=i), "closed_at": t0 + timedelta(hours=i, minutes=5),
             "ticker": "KXR-E%d-A" % i} for i in range(55)]
    monkeypatch.setattr(server.repo, "paper_round_trips_by_strategy", lambda cur, uid, sids: {7: few, 8: many})
    monkeypatch.setattr(agent, "paper_evidence", lambda cur, uid, sid: {"checks": {"net_pnl": True, "edge": False, "demo": False}})
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: True)
    deps = [{"id": 1, "strategy_id": 7, "mode": "paper", "status": "running", "created_at": now - timedelta(hours=61), "result": {}},
            {"id": 2, "strategy_id": 8, "mode": "paper", "status": "paused", "created_at": now - timedelta(hours=61), "result": {}},
            {"id": 3, "strategy_id": 8, "mode": "demo", "status": "running", "created_at": now, "result": {}}]
    roads = server._deploy_roads(None, 1, deps)
    assert roads[7]["trades"] == 2 and roads[7]["events"] == 1 and roads[7]["span_hours"] == 10.0
    assert roads[7]["running"] is True and "failing" not in roads[7]  # the counts aren't in yet
    assert roads[8]["trades"] == 55 and roads[8]["events"] == 55 and roads[8]["running"] is False
    assert roads[8]["failing"] == ["edge", "demo"]
    assert (roads[8]["trades_needed"], roads[8]["events_needed"], roads[8]["span_needed_hours"]) == (30, 20, 48.0)
    server._ROADS.clear(); server._FAILING.clear()


def test_deploy_roads_rerun_the_paper_gate_only_when_the_record_moves(monkeypatch):
    # paper_evidence runs the gate's bootstrap; the 10s Deploy poll must not pay it while nothing closes.
    from app import server
    from app.research import agent
    server._ROADS.clear(); server._FAILING.clear()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    t0 = now - timedelta(hours=60)
    trips = [{"pnl": 0.3, "opened_at": t0 + timedelta(hours=i), "closed_at": t0 + timedelta(hours=i, minutes=5),
              "ticker": "KXR-E%d-A" % i} for i in range(55)]
    calls = []
    monkeypatch.setattr(server.repo, "paper_round_trips_by_strategy", lambda cur, uid, sids: {8: list(trips)})
    monkeypatch.setattr(agent, "paper_evidence", lambda cur, uid, sid: calls.append(sid) or {"checks": {"edge": False}})
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: True)
    deps = [{"id": 2, "strategy_id": 8, "mode": "paper", "status": "running", "created_at": now - timedelta(hours=61), "result": {}}]
    assert server._deploy_roads(None, 1, deps)[8]["failing"] == ["edge"]
    server._ROADS.clear()  # the board's 30s cache lapses, the record hasn't moved
    assert server._deploy_roads(None, 1, deps)[8]["failing"] == ["edge"] and calls == [8]
    trips.append({"pnl": 0.3, "opened_at": now - timedelta(hours=1), "closed_at": now, "ticker": "KXR-E99-A"})
    server._ROADS.clear()  # a trade closed: the gate is asked again
    server._deploy_roads(None, 1, deps)
    assert calls == [8, 8]
    server._ROADS.clear(); server._FAILING.clear()


def test_deploy_roads_follow_a_trade_that_closed_inside_the_cache_window(monkeypatch):
    # The Deploy row showed "Realized +$5.63 · 1 trade" beside "Toward live: 0/30 trades" for up to 30s
    # after a new user's first paper trade closed: the road was kept by time alone.
    from app import server
    from app.services import book_memo
    server._ROADS.clear(); server._FAILING.clear()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    trips = []
    monkeypatch.setattr(book_memo, "paper_round_trips_by_strategy", lambda memo, sids: {8: list(trips)})
    deps = [{"id": 2, "strategy_id": 8, "mode": "paper", "status": "running", "created_at": now - timedelta(hours=1), "result": {}}]
    assert server._deploy_roads(None, 1, deps, book_memo.BookMemo(None, 1, version=(1, 0, 10)))[8]["trades"] == 0
    trips.append({"pnl": 5.63, "opened_at": now - timedelta(minutes=15), "closed_at": now, "ticker": "KXBTC15M-A"})
    # Same version: the kept road stands; the closed trade moves the version and the road with it.
    assert server._deploy_roads(None, 1, deps, book_memo.BookMemo(None, 1, version=(1, 0, 10)))[8]["trades"] == 0
    assert server._deploy_roads(None, 1, deps, book_memo.BookMemo(None, 1, version=(1, 1, 10)))[8]["trades"] == 1
    server._ROADS.clear(); server._FAILING.clear()


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


# -- pairs: legging risk on paper ------------------------------------------------------


class _LegKernel:
    """Fills each (action, side) at a scripted qty cap and price, like a thin simulated book."""

    def __init__(self, caps, prices, fee=0.01):
        self.caps, self.prices, self.fee, self.calls = caps, prices, fee, []

    def execute(self, intent):
        from types import SimpleNamespace
        key = (intent.action, intent.side)
        self.calls.append((key, intent.qty_contracts))
        f = min(int(intent.qty_contracts), self.caps.get(key, intent.qty_contracts))
        return SimpleNamespace(fill_qty_contracts=f, fill_price_dollars=self.prices[key] if f else 0.0,
                               fee_dollars=self.fee * f, external_order_id="o%d" % len(self.calls))


_CLOSE = datetime(2026, 10, 24, 12, 0)
_LEGS = [("yes", "T-LONG", 0.40, 0.38, _CLOSE), ("no", "T-SHORT", 0.45, 0.43, _CLOSE)]
_PRICES = {("buy", "yes"): 0.40, ("buy", "no"): 0.45, ("sell", "yes"): 0.38}


def test_paper_pair_fully_hedged_books_both_legs_under_one_ref(tx):
    cur = _Cur()
    k = _LegKernel({}, _PRICES)
    assert engine._paper_kernel_buy_pair(_Conn(cur), cur, _paper_dep(), k, _LEGS, 10) is True
    assert [p[5] for p in cur.inserted] == [10, 10]
    assert cur.inserted[0][10] == cur.inserted[1][10], "one round trip for the live gate"
    assert cur.inserted[0][10].startswith(engine.SIM_ORDER_REF_PREFIX + "pair-")
    debit = -float(cur.ledger[0][2])
    assert debit == pytest.approx(10 * 0.85 + 0.10 + 0.10)


def test_paper_pair_short_second_leg_unwinds_the_excess(tx):
    cur = _Cur()
    k = _LegKernel({("buy", "no"): 6}, _PRICES)
    assert engine._paper_kernel_buy_pair(_Conn(cur), cur, _paper_dep(), k, _LEGS, 10) is True
    assert (("sell", "yes"), 4) in k.calls, "the 4 unhedged YES are sold back"
    qtys = [p[5] for p in cur.inserted]
    assert qtys == [6, 6, 4]  # hedged YES, hedged NO, the closed unwind row
    unwind_pnl = float(cur.ledger[1][2])
    assert unwind_pnl == pytest.approx(4 * (0.38 - 0.40) - 0.04 - 0.04)


def test_paper_pair_failed_unwind_leaves_a_tracked_naked_leg(tx):
    cur = _Cur()
    k = _LegKernel({("buy", "no"): 6, ("sell", "yes"): 0}, _PRICES)
    assert engine._paper_kernel_buy_pair(_Conn(cur), cur, _paper_dep(), k, _LEGS, 10) is True
    qtys = [p[5] for p in cur.inserted]
    assert qtys == [6, 6, 4], "the 4 naked YES stay open so the guards can close them"
    assert all(p[10] == cur.inserted[0][10] for p in cur.inserted)


def test_paper_pair_with_no_first_leg_fill_books_nothing(tx):
    cur = _Cur()
    k = _LegKernel({("buy", "yes"): 0}, _PRICES)
    assert engine._paper_kernel_buy_pair(_Conn(cur), cur, _paper_dep(), k, _LEGS, 10) is False
    assert cur.inserted == [] and cur.ledger == []
    assert len(k.calls) == 1, "leg 2 is never sent when leg 1 got nothing"
