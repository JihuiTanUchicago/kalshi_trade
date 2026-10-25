"""Money-path tests against a real MySQL (transactions, row locks and SKIP
LOCKED cannot be faked honestly). Opt in with APP_TEST_MYSQL=1 and the usual
MYSQL_* variables pointing at a throwaway database with no `app.worker engine`
running against it (a live engine would trade the test deployments mid-test):

    docker run -d -e MYSQL_ROOT_PASSWORD=devroot -e MYSQL_DATABASE=kalshi_trade -p 3307:3306 mysql:8.0
    APP_TEST_MYSQL=1 MYSQL_HOST=127.0.0.1 MYSQL_PORT=3307 MYSQL_USER=root MYSQL_PASSWORD=devroot \
        python -m pytest tests/test_app_engine_db.py
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


@pytest.fixture
def user(conn):
    from app import repository as repo

    u = repo.upsert_google_user(conn.cursor(), "test:" + uuid.uuid4().hex, "t@example.com", "T", None)
    yield u
    # Leave nothing running for a local engine to trade.
    conn.cursor().execute("UPDATE app_deployments SET status='stopped' WHERE user_id IN (SELECT id FROM app_users WHERE google_sub LIKE 'test:%%')")


def _deployment(conn, user, spec_over=None):
    from app import repository as repo
    from app import spec as specmod

    spec = specmod.validate(dict({"side": "yes", "entry": {"min_edge": 0.1}}, **(spec_over or {})))
    sid = repo.insert_strategy(conn.cursor(), user["id"], None, None, "btc15m", "volatility", "T", "t", spec, "passed",
                               {"capital": 10, "out_of_sample": {"max_drawdown": 3}})
    did = repo.create_deployment(conn.cursor(), user["id"], sid, "btc15m", "paper")
    return next(d for d in repo.running_deployments(conn.cursor(), "btc15m") if d["id"] == did)


def _snap(ticker, close_in_min=5, bid=0.38, ask=0.40):
    from app.markets import Contract, snapshot

    now = int(datetime.now(timezone.utc).timestamp())
    contract = Contract(ticker, 98.0, datetime.fromtimestamp(now + close_in_min * 60, tz=timezone.utc))
    feats = {"spot": 100.0, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0, "vol_15m": 0.0005, "vol_60m": 0.0005}
    return snapshot(feats, contract, now, bid, ask)


def test_starting_balance(conn, user):
    from app import repository as repo

    assert repo.paper_balance(conn.cursor(), user["id"]) == 1000.0


def test_paper_buy_then_settle_balances_to_the_cent(conn, user):
    from app import engine
    from app import repository as repo

    dep = _deployment(conn, user, {"sizing": {"stake": 10.0, "max_positions": 20}})  # $10 / 40c = 25 contracts
    ticker = "TEST-" + uuid.uuid4().hex[:8]
    out = engine.decide(conn, dep, [_snap(ticker)], {ticker: 1000.0}, engine.Sources())
    assert out["entries"] == 1
    [pos] = repo.open_positions(conn.cursor(), dep["id"])
    assert pos["qty"] == 25 and float(pos["entry_price"]) == 0.40 and float(pos["entry_fee"]) == 0.42
    assert repo.paper_balance(conn.cursor(), user["id"]) == pytest.approx(1000 - 10 - 0.42)

    conn.cursor().execute("UPDATE app_positions SET market_close_time=%s WHERE id=%s",
                          (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1), pos["id"]))
    src = engine.Sources(result=lambda t: "yes")
    # Other tests' expired positions in the shared DB may settle too; this one must settle exactly once.
    assert engine.settle_due(conn, engine.MARKETS["btc15m"], src, datetime.now(timezone.utc)) >= 1
    assert engine.settle_due(conn, engine.MARKETS["btc15m"], src, datetime.now(timezone.utc)) == 0  # idempotent
    assert repo.paper_balance(conn.cursor(), user["id"]) == pytest.approx(1000 - 10 - 0.42 + 25)
    cur = conn.cursor()
    cur.execute("SELECT pnl FROM app_positions WHERE id=%s", (pos["id"],))
    assert float(cur.fetchone()["pnl"]) == pytest.approx(25 - 10 - 0.42)


def test_no_position_settles_on_a_no_result(conn, user):
    """Settlement pays the NO side: a NO position whose market resolves NO is worth
    $1/contract. `payout = qty if result == pos["side"]` must be side-generic."""
    from app import engine
    from app import repository as repo

    dep = _deployment(conn, user)
    cur = conn.cursor()
    pid = repo.insert_position(cur, dep["id"], user["id"], "paper", "NOTEST-" + uuid.uuid4().hex[:8], "no", 10, 0.60,
                               0.10, datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1))
    src = engine.Sources(result=lambda t: "no")  # BTC did NOT cross the strike -> NO wins
    assert engine.settle_due(conn, engine.MARKETS["btc15m"], src, datetime.now(timezone.utc)) >= 1
    cur.execute("SELECT status, close_reason, exit_price, pnl FROM app_positions WHERE id=%s", (pid,))
    row = cur.fetchone()
    assert (row["status"], row["close_reason"]) == ("closed", "settled") and float(row["exit_price"]) == 1.0
    # pnl = payout(=qty) - qty*entry - entry_fee = 10 - 10*0.60 - 0.10 = 3.90
    assert float(row["pnl"]) == pytest.approx(10 - 10 * 0.60 - 0.10)

    # A YES result on the same (NO) position pays nothing.
    pid2 = repo.insert_position(cur, dep["id"], user["id"], "paper", "NOTEST-" + uuid.uuid4().hex[:8], "no", 10, 0.60,
                                0.10, datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1))
    engine.settle_due(conn, engine.MARKETS["btc15m"], engine.Sources(result=lambda t: "yes"), datetime.now(timezone.utc))
    cur.execute("SELECT exit_price, pnl FROM app_positions WHERE id=%s", (pid2,))
    row2 = cur.fetchone()
    assert float(row2["exit_price"]) == 0.0 and float(row2["pnl"]) == pytest.approx(-10 * 0.60 - 0.10)


def test_paper_buy_respects_cash_and_book_size(conn, user):
    from app import engine
    from app import repository as repo

    dep = _deployment(conn, user)
    ticker = "TEST-" + uuid.uuid4().hex[:8]
    engine.decide(conn, dep, [_snap(ticker)], {ticker: 3.0}, engine.Sources())
    [pos] = repo.open_positions(conn.cursor(), dep["id"])
    assert pos["qty"] == 3  # never more than the book showed

    broke = repo.upsert_google_user(conn.cursor(), "test:" + uuid.uuid4().hex, "b@example.com", "B", None)
    repo.add_ledger(conn.cursor(), broke["id"], "withdrawal", -1000, "test")
    dep2 = _deployment(conn, broke)
    engine.decide(conn, dep2, [_snap(ticker)], {}, engine.Sources())
    assert not repo.open_positions(conn.cursor(), dep2["id"])


def test_one_decision_per_slot(conn, user):
    from app import repository as repo

    dep = _deployment(conn, user)
    assert repo.claim_decision(conn.cursor(), dep["id"], 1000) is True
    assert repo.claim_decision(conn.cursor(), dep["id"], 1000) is False
    assert repo.claim_decision(conn.cursor(), dep["id"], 1060) is True


def test_two_workers_never_take_the_same_run(conn, user):
    from app import repository as repo
    from data_pipeline.common import get_db_conn

    cur = conn.cursor()
    cur.execute("UPDATE app_agent_runs SET status='cancelled' WHERE status='queued'")
    ids = {repo.create_run(cur, user["id"], "research", "btc15m", "momentum") for _ in range(2)}
    other = get_db_conn()
    try:
        a = repo.claim_run(conn, "w1")
        b = repo.claim_run(other, "w2")
        assert {a["id"], b["id"]} == ids
        assert repo.claim_run(conn, "w3") is None
    finally:
        other.close()


def test_research_week_leaves_out_the_seeded_demo_session(conn, user):
    """A brand-new account's autopilot panel read "2 tested" from the demo it never ran."""
    from app import repository as repo

    cur = conn.cursor()
    since = repo.now_utc() - timedelta(days=7)
    repo.seed_demo_session(cur, user["id"])
    assert sum(int(r["tried"]) for r in repo.research_week(cur, user["id"], since)) == 0
    rid = repo.create_run(cur, user["id"], "research", "btc15m", "momentum")
    cur.execute("UPDATE app_agent_runs SET status='cancelled', hypotheses_tried=3 WHERE id=%s", (rid,))
    week = repo.research_week(cur, user["id"], since)
    assert sum(int(r["tried"]) for r in week) == 3 and sum(int(r["runs"]) for r in week) == 1
    # include_demo still counts it when asked (the Research headline no longer does).
    cur.execute("UPDATE app_agent_runs SET hypotheses_tried=2 WHERE user_id=%s AND direction='random_walk'", (user["id"],))
    every = repo.research_week(cur, user["id"], since, include_demo=True)
    assert sum(int(r["tried"]) for r in every) == 5 and sum(int(r["runs"]) for r in every) == 2


def test_research_spend_is_the_ledger_debits_of_research_runs_only(conn, user):
    """The autopilot panel's "$X spent" is what research debited this week: not chat, not
    autopilot reviews, not the seeded demo, not last week."""
    from decimal import Decimal
    from app import repository as repo

    cur = conn.cursor()
    since = repo.now_utc() - timedelta(days=7)
    repo.seed_demo_session(cur, user["id"])
    cur.execute("SELECT id FROM app_agent_runs WHERE user_id=%s AND direction='random_walk'", (user["id"],))
    demo = cur.fetchone()["id"]
    research = repo.create_run(cur, user["id"], "research", "btc15m", "momentum")
    chat = repo.create_run(cur, user["id"], "chat")
    review = repo.create_run(cur, user["id"], "review")
    cur.execute("UPDATE app_agent_runs SET status='cancelled' WHERE id IN (%s,%s,%s)", (research, chat, review))
    for run_id, amount in ((research, "-1.250000"), (research, "-0.500000"), (chat, "-0.300000"),
                           (review, "-0.700000"), (demo, "-9.000000")):
        repo.add_credit(cur, user["id"], "usage", Decimal(amount), "Agent usage", run_id=run_id)
    repo.add_credit(cur, user["id"], "usage", Decimal("-4"), "Agent usage", run_id=research)
    cur.execute("UPDATE app_credit_ledger SET created_at=%s WHERE user_id=%s AND amount_usd=-4",
                (since - timedelta(days=1), user["id"]))  # last week's debit on the same run
    repo.add_credit(cur, user["id"], "topup", Decimal("20"), "Added credits")
    assert repo.research_spent_since(cur, user["id"], since) == pytest.approx(1.75)


def test_runs_spent_sums_each_runs_usage_debits(conn, user):
    """The run page's "Spent so far": the usage rows billed to that run, nothing else."""
    from decimal import Decimal
    from app import repository as repo

    cur = conn.cursor()
    a = repo.create_run(cur, user["id"], "research", "btc15m", "momentum")
    b = repo.create_run(cur, user["id"], "research", "btc15m", "momentum")
    idle = repo.create_run(cur, user["id"], "research", "btc15m", "momentum")
    cur.execute("UPDATE app_agent_runs SET status='cancelled' WHERE id IN (%s,%s,%s)", (a, b, idle))
    for run_id, amount in ((a, "-1.250000"), (a, "-0.587250"), (b, "-0.300000")):
        repo.add_credit(cur, user["id"], "usage", Decimal(amount), "Agent usage", run_id=run_id)
    repo.add_credit(cur, user["id"], "admin_grant", Decimal("5"), "Grant", run_id=a)  # not usage
    spent = repo.runs_spent(cur, user["id"], [a, b, idle])
    assert spent == {a: pytest.approx(1.83725), b: pytest.approx(0.3)}
    assert repo.runs_spent(cur, user["id"] + 10**9, [a]) == {}  # another user's run reads nothing
    cur.execute("SHOW INDEX FROM app_credit_ledger WHERE Key_name='idx_credit_run_kind'")
    assert [r["Column_name"] for r in cur.fetchall()] == ["run_id", "kind"]


def test_autopilot_paper_week_counts_only_what_the_autopilot_put_on_paper(conn, user):
    """The scorecard's paper figures: strategies the autopilot deployed itself (an 'applied' deploy
    proposal it never asked about), not ones the user approved or deployed by hand, nor demo."""
    from app import repository as repo
    from app import spec as specmod

    cur = conn.cursor()
    now = repo.now_utc()
    since = now - timedelta(days=7)
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}})

    def strategy():
        return repo.insert_strategy(cur, user["id"], None, None, "btc15m", "volatility", "T", "t", spec, "passed",
                                    {"capital": 10})

    def closed(dep, pnl, when):
        pid = repo.insert_position(cur, dep, user["id"], "paper", "WK-" + uuid.uuid4().hex[:8], "yes", 1, 0.5, 0.0,
                                   now)
        cur.execute("UPDATE app_positions SET status='closed', pnl=%s, closed_at=%s WHERE id=%s", (pnl, when, pid))

    auto_new, auto_old, approved, manual = strategy(), strategy(), strategy(), strategy()
    for sid in (auto_new, auto_old):
        repo.create_proposal(cur, user["id"], "deploy", "Autopilot", None, sid, "applied")
    pid = repo.create_proposal(cur, user["id"], "deploy", "Asked", None, approved, "pending")
    assert repo.decide_proposal(cur, pid, "applied")  # the user approved it: theirs, not the autopilot's
    d_new = repo.create_deployment(cur, user["id"], auto_new, "btc15m", "paper")
    d_old = repo.create_deployment(cur, user["id"], auto_old, "btc15m", "paper")
    cur.execute("UPDATE app_deployments SET created_at=%s WHERE id=%s", (since - timedelta(days=3), d_old))
    repo.create_deployment(cur, user["id"], auto_old, "eth15m", "paper")  # a new leg is not a new start
    d_demo = repo.create_deployment(cur, user["id"], auto_new, "btc15m", "demo")
    d_approved = repo.create_deployment(cur, user["id"], approved, "btc15m", "paper")
    d_manual = repo.create_deployment(cur, user["id"], manual, "btc15m", "paper")
    closed(d_new, 2.5, now - timedelta(days=1))
    closed(d_old, -1.0, now - timedelta(hours=2))
    closed(d_old, 9.0, since - timedelta(days=1))  # last week
    closed(d_approved, 40.0, now - timedelta(hours=1))
    closed(d_manual, 50.0, now - timedelta(hours=1))
    cur.execute("UPDATE app_positions SET mode='demo' WHERE deployment_id=%s", (d_demo,))
    week = repo.autopilot_paper_week(cur, user["id"], since)
    assert week == {"started": 1, "pnl": pytest.approx(1.5), "trades": 2}


def test_finished_session_costs_are_set_size_research_sessions_that_debited(conn, user):
    """The cost hint's samples: research sessions that ran to their end on a set number of ideas,
    each totalled from its own ledger rows. Not run-forever, cancelled, demo, chat, or zero-cost."""
    from decimal import Decimal
    from app import repository as repo

    cur = conn.cursor()
    repo.seed_demo_session(cur, user["id"])

    def run(kind="research", status="succeeded", forever=False, debits=()):
        rid = repo.create_run(cur, user["id"], kind, "btc15m", "momentum", run_forever=forever)
        cur.execute("UPDATE app_agent_runs SET status=%s WHERE id=%s", (status, rid))
        for amount in debits:
            repo.add_credit(cur, user["id"], "usage", Decimal(amount), "Agent usage", run_id=rid)
        return rid

    run(debits=("-1.000000", "-0.500000"))
    run(forever=True, debits=("-9.137000",))
    run(status="cancelled", debits=("-8.137000",))
    run(kind="chat", debits=("-7.137000",))
    run(debits=())  # debited nothing
    run(debits=("-2.250000",))
    cur.execute("SELECT id FROM app_agent_runs WHERE user_id=%s AND direction='random_walk'", (user["id"],))
    demo = cur.fetchone()["id"]
    cur.execute("UPDATE app_agent_runs SET status='succeeded' WHERE id=%s", (demo,))
    repo.add_credit(cur, user["id"], "usage", Decimal("-6.137"), "Agent usage", run_id=demo)
    assert repo.finished_session_costs(cur, user["id"], 10) == [pytest.approx(2.25), pytest.approx(1.5)]
    assert repo.finished_session_costs(cur, user["id"], 1) == [pytest.approx(2.25)]
    every = repo.recent_session_costs(cur, repo.now_utc() - timedelta(days=1))
    assert (None, pytest.approx(2.25)) in every and (None, pytest.approx(1.5)) in every
    assert not any(round(cost, 3) in (9.137, 8.137, 7.137, 6.137) for _, cost in every)


def test_the_interactive_lane_skips_research(conn, user):
    from app import repository as repo

    cur = conn.cursor()
    cur.execute("UPDATE app_agent_runs SET status='cancelled' WHERE status='queued'")
    repo.create_run(cur, user["id"], "research", "btc15m", "momentum")
    review = repo.create_run(cur, user["id"], "review", None, "scheduled")
    assert repo.claim_run(conn, "chat0", skip_research=True)["id"] == review
    assert repo.claim_run(conn, "chat0", skip_research=True) is None
    assert repo.claim_run(conn, "w1")["kind"] == "research"


def test_weekly_passed_count_only_counts_this_weeks_research_runs(conn, user):
    # The panel says "this week it tested N ideas and M passed": M must come from the same runs as
    # N, never from chat adjustments or shared copies (no research run) or a review run.
    from app import repository as repo
    from app import spec as specmod

    cur = conn.cursor()
    cur.execute("UPDATE app_agent_runs SET status='cancelled' WHERE status='queued'")
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}})
    research = repo.create_run(cur, user["id"], "research", "btc15m", "momentum")
    review = repo.create_run(cur, user["id"], "review", None, "scheduled")
    for run_id, status in ((research, "passed"), (research, "rejected"), (None, "passed"), (review, "passed")):
        repo.insert_strategy(cur, user["id"], run_id, None, "btc15m", "momentum", "T", "t", spec, status, {})
    since = repo.now_utc() - timedelta(days=7)
    assert repo.strategies_passed_since(cur, user["id"], since) == 1
    assert repo.strategies_passed_since(cur, user["id"], repo.now_utc() + timedelta(minutes=5)) == 0


def test_strategy_counts_include_how_many_are_deployed(conn, user):
    from app import repository as repo

    cur = conn.cursor()
    before = repo.count_strategies(cur, user["id"])  # the fixture user can carry other tests' rows
    dep = _deployment(conn, user)
    counts = repo.count_strategies(cur, user["id"])
    assert counts["deployed"] == before["deployed"] + 1 and counts["total"] == before["total"] + 1
    repo.set_deployment_status(cur, user["id"], dep["id"], "stopped")
    assert repo.count_strategies(cur, user["id"])["deployed"] == before["deployed"]


def test_loss_guard_pauses_and_asks_for_review(conn, user):
    from app import engine
    from app import repository as repo

    dep = _deployment(conn, user)
    cur = conn.cursor()
    pid = repo.insert_position(cur, dep["id"], user["id"], "paper", "X", "yes", 10, 0.5, 0.1,
                               datetime.now(timezone.utc))
    repo.close_position(cur, pid, 0.0, 0.0, -9.0, "settled")
    assert engine.loss_guard(cur, dep) is True
    assert repo.get_deployment(cur, user["id"], dep["id"])["status"] == "paused"
    assert repo.count_runs(cur, user["id"], "review", active_only=True) == 1


def test_paper_withdrawal_cannot_overdraw(conn, user):
    from app import server

    ctx = server.Ctx(conn, user, (), {}, {"kind": "withdraw", "amount": 5000}, None)
    with pytest.raises(server.ApiError, match="only have"):
        server.paper_transfer(ctx)
    ctx.body = {"kind": "withdraw", "amount": 400}
    server.paper_transfer(ctx)
    from app import repository as repo

    assert repo.paper_balance(conn.cursor(), user["id"]) == 600.0


def test_a_stopped_out_position_is_scored_against_holding_once_it_settles(conn, user):
    from app import engine
    from app import repository as repo

    dep = _deployment(conn, user)
    cur = conn.cursor()
    ticker = "TEST-" + uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    close = (now - timedelta(minutes=1)).replace(tzinfo=None)
    pid = repo.insert_position(cur, dep["id"], user["id"], "paper", ticker, "no", 11, 0.19, 0.10, close, None)
    assert repo.close_position(cur, pid, 0.024, 0.0, -1.98, "stop")
    assert [p["id"] for p in repo.unscored_early_exits(cur, "btc15m", now) if p["id"] == pid] == [pid]
    engine._last_exit_score.clear()
    engine.score_early_exits(conn, engine.MARKETS["btc15m"], engine.Sources(result=lambda t: "yes"), now)
    assert pid not in [p["id"] for p in repo.unscored_early_exits(cur, "btc15m", now)]
    card = repo.early_exit_scorecard(cur, user["id"], since=now - timedelta(days=1))
    assert card["stop"] == {"exits": 1, "scored": 1, "pnl": -1.98, "scored_pnl": -1.98, "hold_pnl": -2.19, "saved": 0.21}


def test_scorecard_separates_the_breacher_from_positions_flattened_alongside_it(conn, user):
    from app import repository as repo

    dep = _deployment(conn, user)
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    close = (now - timedelta(minutes=1)).replace(tzinfo=None)
    breacher = repo.insert_position(cur, dep["id"], user["id"], "paper", "TEST-" + uuid.uuid4().hex[:8], "no", 2, 0.80, 0.02, close, None)
    healthy = repo.insert_position(cur, dep["id"], user["id"], "paper", "TEST-" + uuid.uuid4().hex[:8], "no", 5, 0.87, 0.05, close, None)
    assert repo.close_position(cur, breacher, 0.38, 0.0, -0.91, "stop")   # -52%: past the 40% stop
    assert repo.close_position(cur, healthy, 0.94, 0.0, 0.28, "stop")     # +8%: sold alongside it
    cur.execute("UPDATE app_positions SET settle_result='no', hold_pnl=%s WHERE id=%s", (0.60, healthy))
    card = repo.early_exit_scorecard(cur, user["id"], since=now - timedelta(days=1))
    assert card["stop"]["exits"] == 2
    assert card["stop"]["collateral"] == {"exits": 1, "scored": 1, "saved": -0.32}


def test_underpowered_verdict_pnl_reaches_probation_but_not_replay(conn, user):
    """A below-min-sample verdict records its validation P&L with no p-value. Paper probation's
    candidate read returns that P&L; the replay optimizer's read masks it, so the research loop
    learns from no more than it did before the P&L was recorded."""
    from app import repository as repo
    from app import research_repository as rr
    from app import spec as specmod

    cur = conn.cursor()
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}})
    sid = repo.insert_strategy(cur, user["id"], None, None, "btc15m", "volatility", "U", "t", spec, "rejected",
                               {"capital": 10, "in_sample": {"trades": 300, "pnl": 40.0}})
    eid = rr.preregister(cur, dict(
        user_id=user["id"], run_id=None, strategy_id=sid, market="btc15m", hypothesis_hash=uuid.uuid4().hex,
        spec=spec, economic_rationale="m", primary_metric="mean_net_return_per_trade", null_hypothesis="edge<=0",
        alt_hypothesis="edge>0", planned_test="stationary_bootstrap", falsification_criteria="ci_lo<=0",
        min_sample=150, cost_assumptions={}, research_partition_id=0, planned_n_tests=1, correction_method="BH"))
    rr.append_result(cur, eid, "validation", "inconclusive", 56, metrics={"net_pnl": 7.25, "n_trials_audited": 3})
    got = [c for c in rr.underpowered_candidates(cur, user["id"], 10) if c["strategy_id"] == sid]
    assert got == [{"strategy_id": sid, "market": "btc15m", "p_value": None, "net_pnl": 7.25, "n_trades": 56}]
    rec = [r for r in rr.experiment_records_for_replay(cur, user["id"], "btc15m") if r["experiment_id"] == eid]
    assert len(rec) == 1 and rec[0]["net_pnl"] is None and rec[0]["classification"] == "inconclusive"


def test_paper_fills_for_gate_sums_exit_slices_and_marks_settled_trips(conn, user):
    """The forward gate's read: one trip per entry fill, exit slices weighted by quantity, and a
    trip counts as settled only when every slice settled. Open trips and legacy fills stay out."""
    from app import repository as repo

    dep = _deployment(conn, user)
    cur = conn.cursor()
    close = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None)
    ref = "sim:" + uuid.uuid4().hex[:8]
    a = repo.insert_position(cur, dep["id"], user["id"], "paper", "GATE-A-1", "yes", 6, 0.40, 0.06, close, ref)
    b = repo.insert_position(cur, dep["id"], user["id"], "paper", "GATE-A-1", "yes", 4, 0.40, 0.04, close, ref)
    assert repo.close_position(cur, a, 0.50, 0.03, 0.51, "take_profit")
    assert repo.close_position(cur, b, 1.00, 0.0, 2.36, "settled")
    s = repo.insert_position(cur, dep["id"], user["id"], "paper", "GATE-B-1", "no", 5, 0.70, 0.05, close, "sim:" + uuid.uuid4().hex[:8])
    assert repo.close_position(cur, s, 1.00, 0.0, 1.45, "settled")
    repo.insert_position(cur, dep["id"], user["id"], "paper", "GATE-C-1", "yes", 1, 0.5, 0.01, close, "sim:" + uuid.uuid4().hex[:8])
    legacy = repo.insert_position(cur, dep["id"], user["id"], "paper", "GATE-D-1", "yes", 1, 0.5, 0.01, close, None)
    assert repo.close_position(cur, legacy, 1.0, 0.0, 0.49, "settled")
    got = sorted(repo.paper_fills_for_gate(cur, user["id"], dep["strategy_id"]), key=lambda r: r["ticker"])
    assert [(r["ticker"], r["qty"], r["settled"]) for r in got] == [("GATE-A-1", 10, False), ("GATE-B-1", 5, True)]
    assert got[0]["exit_price"] == pytest.approx(0.70) and got[0]["pnl"] == pytest.approx(2.87)
    assert got[0]["fees"] == pytest.approx(0.13)


def test_code_paper_rows_keep_their_replayed_times_and_count_for_the_gate(conn, user):
    """The code paper replay's reads and writes: only running paper code strategies are listed, a
    replayed trip keeps its own open/close times, and the forward gate reads it as a sim: fill."""
    from app import repository as repo
    from app import spec as specmod

    spec = specmod.validate({"market": "btc15m", "code": "def signals(window):\n    return []\n",
                             "sizing": {"stake": 5, "max_positions": 1}})
    sid = repo.insert_strategy(conn.cursor(), user["id"], None, None, "btc15m", "volatility", "C", "c", spec, "rejected", {})
    did = repo.create_deployment(conn.cursor(), user["id"], sid, "btc15m", "paper")
    dsl = _deployment(conn, user)
    cur = conn.cursor()
    listed = [d["id"] for d in repo.running_code_paper_deployments(cur)]
    assert did in listed and dsl["id"] not in listed
    opened, closed = datetime(2026, 10, 24, 18, 0), datetime(2026, 10, 24, 21, 0)
    ref = "sim:replay:%d:KXBTC-REPLAY-1:%d" % (did, 1793210400)
    repo.insert_closed_position(cur, did, user["id"], "paper", "KXBTC-REPLAY-1", "yes", 5, 0.40, 0.05, 1.0, 0.0,
                                2.95, "settled", closed, ref, opened_at=opened, closed_at=closed)
    assert repo.deployment_order_refs(cur, did, "sim:replay:") == {ref}
    got = repo.paper_fills_for_gate(cur, user["id"], sid)
    assert [(g["opened_at"], g["closed_at"], g["settled"], g["pnl"]) for g in got] == [(opened, closed, True, 2.95)]
