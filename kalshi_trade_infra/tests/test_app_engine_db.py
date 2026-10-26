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
    from app.trading import spec as specmod

    spec = specmod.validate(dict({"side": "yes", "entry": {"min_edge": 0.1}}, **(spec_over or {})))
    sid = repo.insert_strategy(conn.cursor(), user["id"], None, None, "btc15m", "volatility", "T", "t", spec, "passed",
                               {"capital": 10, "out_of_sample": {"max_drawdown": 3}})
    did = repo.create_deployment(conn.cursor(), user["id"], sid, "btc15m", "paper")
    return next(d for d in repo.running_deployments(conn.cursor(), "btc15m") if d["id"] == did)


def _snap(ticker, close_in_min=5, bid=0.38, ask=0.40):
    from app.trading.markets import Contract, snapshot

    now = int(datetime.now(timezone.utc).timestamp())
    contract = Contract(ticker, 98.0, datetime.fromtimestamp(now + close_in_min * 60, tz=timezone.utc))
    feats = {"spot": 100.0, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0, "vol_15m": 0.0005, "vol_60m": 0.0005}
    return snapshot(feats, contract, now, bid, ask)


def test_starting_balance(conn, user):
    from app import repository as repo

    assert repo.paper_balance(conn.cursor(), user["id"]) == 1000.0


def test_paper_buy_then_settle_balances_to_the_cent(conn, user):
    from app.trading import engine
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


def test_the_dashboard_says_why_a_paper_trade_was_entered_and_why_it_exited(conn, user):
    """The engine buys on the rule and sells at the take-profit; the dashboard's line for that trade
    names the same rule and the same exit, from the stored row and the strategy's frozen spec."""
    from app import server
    from app.trading import engine

    dep = _deployment(conn, user, {"sizing": {"stake": 10.0, "max_positions": 1}, "exit": {"take_profit": 0.2}})
    ticker = "TEST-" + uuid.uuid4().hex[:8]
    assert engine.decide(conn, dep, [_snap(ticker)], {ticker: 1000.0}, engine.Sources())["entries"] == 1

    def mine(rows):
        return [p["why"] for p in rows if p["ticker"] == ticker]

    dash = server.dashboard(server.Ctx(conn, dict(user, autopilot=0), (), {}, {}, None))
    assert mine(dash["open_positions"]) == ["Entered at 40¢: edge ≥ 10¢ after fees · Exits: +20¢ take-profit, else settlement"]
    assert engine.decide(conn, dep, [_snap(ticker, bid=0.62, ask=0.64)], {ticker: 1000.0}, engine.Sources())["exits"] == 1
    dash = server.dashboard(server.Ctx(conn, dict(user, autopilot=0), (), {}, {}, None))
    assert mine(dash["recent_closed"]) == [
        "Entered at 40¢: edge ≥ 10¢ after fees · Exited at 62¢: take-profit (+22¢ vs +20¢ target)"]
    assert mine(server.list_deployments(server.Ctx(conn, dict(user, autopilot=0), (), {}, {}, None))["recent_closed"]) == \
        mine(dash["recent_closed"])


def test_no_position_settles_on_a_no_result(conn, user):
    """Settlement pays the NO side: a NO position whose market resolves NO is worth
    $1/contract. `payout = qty if result == pos["side"]` must be side-generic."""
    from app.trading import engine
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
    from app.trading import engine
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


def test_example_finds_the_seeded_session_past_the_newest_fifty(conn, user):
    """/example looked for the example in the runs list (the newest 50), so a user with more sessions
    landed on /research. Its own lookup finds it behind any number, for this user only."""
    from app import repository as repo
    from app import server

    cur = conn.cursor()
    repo.seed_demo_session(cur, user["id"])  # sign-up seeds it already; idempotent
    cur.execute("SELECT id FROM app_agent_runs WHERE user_id=%s AND direction='random_walk'", (user["id"],))
    example = cur.fetchone()["id"]
    for _ in range(55):
        repo.create_run(cur, user["id"], "research", "btc15m", "momentum")
    repo.create_run(cur, user["id"], "chat")
    assert not any(r["id"] == example for r in repo.list_runs(cur, user["id"]))  # off the list...
    assert repo.example_run_id(cur, user["id"]) == example  # ...but still found
    ctx = server.Ctx(conn, user, (), {}, {}, None)
    assert server.example_run(ctx) == {"id": example}
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "o@example.com", "O", None)
    theirs = server.example_run(server.Ctx(conn, other, (), {}, {}, None))["id"]
    assert theirs not in (None, example)  # their own, never this user's
    cur.execute("DELETE FROM app_agent_runs WHERE id=%s", (theirs,))
    assert server.example_run(server.Ctx(conn, other, (), {}, {}, None)) == {"id": None}
    cur.execute("EXPLAIN SELECT id FROM app_agent_runs WHERE user_id=%s AND kind='research' AND direction=%s "
                "ORDER BY id DESC LIMIT 1", (user["id"], "random_walk"))
    assert any("idx_runs_user" in (r.get("possible_keys") or "") for r in cur.fetchall())


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
    from app.trading import spec as specmod

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
    from app.trading import spec as specmod

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
    from app.trading import engine
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
    from app.trading import engine
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
    from app.research import research_repository as rr
    from app.trading import spec as specmod

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
    from app.trading import spec as specmod

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


def _closed_trades(conn, user, dep_id, pnls, start):
    rows = [(dep_id, user["id"], "paper", "TEST-CURVE-%d" % i, "yes", 1, 0.40, 0.01, start + timedelta(minutes=i),
             start + timedelta(minutes=i) - timedelta(hours=1), "closed", start + timedelta(minutes=i), pnl)
            for i, pnl in enumerate(pnls)]
    conn.cursor().executemany(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
           market_close_time, opened_at, status, closed_at, pnl) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)


def test_a_deployment_curve_stays_small_and_keeps_its_end_and_extremes(conn, user):
    """The dashboard sends each deployment's cumulative P&L curve. At 20k closed trades that was 20k
    points (433KB a load); it is now at most CURVE_MAX_POINTS, cut down in SQL, with the first and
    last trade exact and each stretch's lowest and highest point kept, so a one-trade crash shows."""
    import json
    import random
    from decimal import Decimal

    from app import repository as repo, server

    rng = random.Random(5)
    big, small = _deployment(conn, user), _deployment(conn, user)
    pnls = [Decimal(rng.randint(-100, 105)) / 100 for _ in range(20000)]
    pnls[12345] = Decimal("-250.00")  # a single crash and recovery a stride sampler would step over
    pnls[12346] = Decimal("250.00")
    start = datetime(2026, 1, 1)
    _closed_trades(conn, user, big["id"], pnls, start)
    _closed_trades(conn, user, small["id"], [Decimal("1.25"), Decimal("-0.50"), Decimal("0.75")], start)

    def ts(i):
        return int((start + timedelta(minutes=i)).replace(tzinfo=timezone.utc).timestamp())

    curves = repo.deployment_curves(conn.cursor(), user["id"])
    full, cum = [], Decimal(0)
    for i, p in enumerate(pnls):
        cum += p
        full.append([ts(i), float(cum)])
    curve = curves[big["id"]]
    assert len(curve) <= repo.CURVE_MAX_POINTS
    assert curve[0] == full[0] and curve[-1] == full[-1]
    assert curve[-1][1] == float(sum(pnls))  # ends on the deployment's realized P&L, to the cent
    assert [p for p in full if p in curve] == curve  # real trades, in order
    values = [v for _, v in curve]
    assert min(values) == min(v for _, v in full) and max(values) == max(v for _, v in full)
    assert full[12345] in curve  # the crash itself
    # Every stretch keeps its own low and high.
    n, buckets = len(full), (repo.CURVE_MAX_POINTS - 2) // 2
    for b in range(buckets):
        stretch = [v for i, (_, v) in enumerate(full[1:-1], start=2) if (i - 2) * buckets // (n - 2) == b]
        assert min(stretch) in values and max(stretch) in values, b
    # Under the cap a curve is every trade, unchanged.
    assert curves[small["id"]] == [[ts(0), 1.25], [ts(1), 0.75], [ts(2), 1.5]]
    # The dashboard payload no longer grows with the trade count.
    body = json.dumps(server.dashboard(server.Ctx(conn, dict(user, autopilot=0), (), {}, {}, None)),
                      default=server._json_default)
    assert len(body) < 64_000, len(body)


class _Counting:
    """Counts the statements a repository call sends."""

    def __init__(self, cur):
        self.cur, self.n = cur, 0

    def execute(self, sql, args=None):
        self.n += 1
        return self.cur.execute(sql, args)

    def __getattr__(self, name):
        return getattr(self.cur, name)


def test_settled_lately_ranks_by_settle_time_and_reads_only_the_newest_index_entries(conn, user):
    """recent_closed (the dashboard's "Settled lately", Deploy's recent trades) lists the most
    recently settled positions: closed_at newest first, then id. A position that opened first but
    settled last ranks first. The rows come from the newest idx_pos_user entries alone, with no sort.
    A deleted strategy's positions still drop out; the slack covers a few, and the join answers when
    more of the newest drop out. Open positions keep their own SQL and order."""
    import random
    from decimal import Decimal

    from app import repository as repo
    from app.adapters.db import position_repository as pr

    joined = ("SELECT p.*, s.title FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id "
              "JOIN app_strategies s ON s.id=d.strategy_id WHERE p.user_id=%s AND p.status=%s ORDER BY p.id DESC LIMIT %s")
    rng = random.Random(11)
    kept, gone = _deployment(conn, user), _deployment(conn, user)
    start = datetime(2026, 3, 1)

    def trades(dep, closes, status="closed"):
        rows = [(dep["id"], user["id"], "paper", "TEST-SETTLED-%d" % i, "yes", 1, 0.40, 0.01, start, start, status,
                 at, Decimal(rng.randint(-100, 100)) / 100) for i, at in enumerate(closes)]
        conn.cursor().executemany(
            """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
               market_close_time, opened_at, status, closed_at, pnl) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)

    def minutes(lo, hi, n):
        return [start + timedelta(minutes=rng.randint(lo, hi)) for _ in range(n)]

    def check(statements):
        everything = conn.cursor()
        everything.execute(joined, (user["id"], "closed", 10 ** 6))
        settled = sorted(everything.fetchall(), key=lambda r: (r["closed_at"], r["id"]), reverse=True)
        for limit in (12, 20):
            cur = _Counting(conn.cursor())
            assert repo.user_positions(cur, user["id"], "closed", limit) == settled[:limit]
            assert cur.n == statements, (limit, cur.n)
        everything.execute(joined, (user["id"], "open", 100))
        assert repo.user_positions(conn.cursor(), user["id"], "open") == everything.fetchall()

    assert repo.user_positions(conn.cursor(), user["id"], "closed", 12) == []  # dormant: nothing
    trades(kept, [start + timedelta(days=30)])  # opened first (lowest id), a long-dated contract settled last
    trades(kept, minutes(0, 10000, 60))  # opened after it, settled before it, in no particular order
    trades(kept, [None, None], status="open")
    first = repo.user_positions(conn.cursor(), user["id"], "closed", 12)
    assert first[0]["closed_at"] == start + timedelta(days=30)
    assert first[0]["id"] == min(r["id"] for r in repo.user_positions(conn.cursor(), user["id"], "closed", 100))
    check(1)
    trades(gone, minutes(20000, 30000, pr.CLOSED_SLACK - 2))
    conn.cursor().execute("DELETE FROM app_strategies WHERE id=%s", (gone["strategy_id"],))
    check(1)  # a few of the most recently settled belong to the deleted strategy: the slack covers them
    trades(gone, minutes(30000, 40000, 30))
    check(2)  # most of them do: the join answers, in the same order
    plan = conn.cursor()
    plan.execute("EXPLAIN SELECT id, closed_at FROM app_positions FORCE INDEX (idx_pos_user) WHERE user_id=%s "
                 "AND status='closed' ORDER BY closed_at DESC, id DESC LIMIT 20", (user["id"],))
    rows = plan.fetchall()
    assert [r["key"] for r in rows] == ["idx_pos_user"]
    assert "filesort" not in (rows[0]["Extra"] or "")  # read straight off the index, newest first

def test_the_autopilot_panels_reads_answer_as_the_position_scans_they_replace(conn, user):
    """/api/autopilot/status polls every 20s. Its deployment list leaves out the position totals
    (read for a just-paused deployment alone), and its paper readouts start from the strategies'
    deployments through idx_pos_dep instead of scanning every position the user holds. Same answers."""
    from app import repository as repo

    cur = conn.cursor()
    uid = user["id"]
    a, b, quiet = _deployment(conn, user), _deployment(conn, user), _deployment(conn, user)
    a2 = repo.create_deployment(cur, uid, a["strategy_id"], "btc15m", "paper")  # a strategy redeployed
    close = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None)

    def trip(dep_id, ticker, pnls, open_slice=False, ref="sim:"):
        ref = ref and ref + uuid.uuid4().hex[:8]
        for pnl in pnls:
            pid = repo.insert_position(cur, dep_id, uid, "paper", ticker, "yes", 1, 0.40, 0.01, close, ref)
            assert repo.close_position(cur, pid, 0.5, 0.01, pnl, "settled")
        if open_slice:
            repo.insert_position(cur, dep_id, uid, "paper", ticker, "yes", 1, 0.40, 0.01, close, ref)

    trip(a["id"], "KXRAIN-26OCT25-NYC", [0.25, -0.10])  # one trip in two exit slices
    trip(a["id"], "KXRAIN-26OCT25-CHI", [0.40])  # same event, another city
    trip(a2, "KXRAIN-26OCT26-NYC", [-0.30])
    trip(a2, "KXRAIN-26OCT27-NYC", [0.10], open_slice=True)  # still part open: not a trip yet
    trip(b["id"], "KXBTC-26OCT25-B98", [1.10])
    trip(b["id"], "KXBTC-26OCT25-B99", [0.20], ref=None)  # legacy instant fill: not realistic paper
    assert repo.set_deployment_status(cur, uid, b["id"], "paused", "lost $6.00")

    full = repo.list_deployments(cur, uid)
    aggregates = ("realized_pnl", "closed_trades", "wins", "open_positions")
    assert repo.list_deployments_brief(cur, uid) == [{k: v for k, v in d.items() if k not in aggregates} for d in full]
    assert repo.deployment_closed_totals(cur, [d["id"] for d in full]) == {
        d["id"]: (d["closed_trades"], d["realized_pnl"]) for d in full if d["closed_trades"]}
    assert repo.deployment_closed_totals(cur, [quiet["id"]]) == {} == repo.deployment_closed_totals(cur, [])
    from app import server
    assert server._paused_recent(repo.list_deployments_brief(cur, uid), cur=cur) == server._paused_recent(full)
    assert server._paused_recent(full)[0]["trades"] == 2

    sids = sorted({a["strategy_id"], b["strategy_id"], quiet["strategy_id"]})
    marks = ",".join(["%s"] * len(sids))
    cur.execute("""SELECT t.strategy_id, COUNT(*) AS trips, COALESCE(SUM(t.pnl),0) AS pnl FROM (
                     SELECT d.strategy_id, p.order_ref, SUM(p.pnl) AS pnl
                     FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
                     WHERE p.user_id=%s AND p.mode='paper' AND p.order_ref LIKE %s AND d.strategy_id IN (""" + marks + """)
                     GROUP BY d.strategy_id, p.order_ref
                     HAVING SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END)=0) t
                   GROUP BY t.strategy_id""", (uid, "sim:%", *sids))
    before = {int(r["strategy_id"]): (int(r["trips"]), float(r["pnl"])) for r in cur.fetchall()}
    assert repo.paper_progress(cur, uid, sids) == before
    assert before[a["strategy_id"]] == (3, pytest.approx(0.25)) and before[b["strategy_id"]] == (1, pytest.approx(1.10))
    cur.execute("""SELECT d.strategy_id,
                     COUNT(DISTINCT SUBSTRING(p.ticker, 1, LENGTH(p.ticker) - LENGTH(SUBSTRING_INDEX(p.ticker, '-', -1)) - 1)) AS events
                   FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
                   WHERE p.user_id=%s AND p.mode='paper' AND p.status='closed' AND p.order_ref LIKE %s
                     AND d.strategy_id IN (""" + marks + """)
                   GROUP BY d.strategy_id""", (uid, "sim:%", *sids))
    events = {int(r["strategy_id"]): int(r["events"]) for r in cur.fetchall()}
    assert repo.paper_event_counts(cur, uid, sids) == events == {a["strategy_id"]: 3, b["strategy_id"]: 1}
    # The scoreboard reads every paper strategy's trips at once (its tournament) and skips the live-ready
    # check for a strategy whose paper_progress net is below zero: both answer as the per-strategy read.
    one = {s: repo.paper_round_trips(cur, uid, s) for s in sids}
    key = lambda t: (t["opened_at"], t["pnl"], t["ticker"])  # noqa: E731 - ties in opened_at have no set order
    batched = repo.paper_round_trips_by_strategy(cur, uid, sids)
    assert {s: sorted(t, key=key) for s, t in batched.items()} == {s: sorted(t, key=key) for s, t in one.items() if t}
    for s, (n, net) in before.items():
        assert n == len(one[s]) and (net < 0) == (sum(t["pnl"] for t in one[s]) < 0)
    cur.execute("EXPLAIN SELECT d.strategy_id FROM " + repo._PAPER_SOURCE + " WHERE p.user_id=%s AND d.strategy_id IN ("
                + marks + ")", (uid, *sids))
    plan = cur.fetchall()
    assert [r["table"] for r in plan] == ["d", "p"] and plan[1]["key"] == "idx_pos_dep"  # each deployment's own positions


def test_the_dashboard_and_strategy_list_reads_answer_as_the_ones_they_replace(conn, user):
    """The dashboard and the strategy list sum each deployment's positions before joining its row
    (list_deployments_for_display), and the dashboard reads each book's realized P&L and closed
    trades in one pass (closed_book_totals). Same rows, sums and counts as list_deployments,
    realized_pnl and closed_trade_counts, which the engine and the gates keep using."""
    from app import repository as repo

    cur = conn.cursor()
    uid = user["id"]
    a, b, empty, stopped = (_deployment(conn, user) for _ in range(4))
    demo = repo.create_deployment(cur, uid, a["strategy_id"], "btc15m", "demo")
    close = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None)
    day = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)

    def position(dep_id, mode, pnl=None, ticker="KXBTC-26OCT25-B98"):
        pid = repo.insert_position(cur, dep_id, uid, mode, ticker, "yes", 1, 0.40, 0.01, close, None)
        if pnl is not None:
            assert repo.close_position(cur, pid, 0.5, 0.01, pnl, "settled")

    for pnl in (0.25, -0.10, 0.0, 1.05):
        position(a["id"], "paper", pnl)
    position(a["id"], "paper")  # still open
    position(b["id"], "paper", -0.35)
    position(demo, "demo", 0.60)
    position(demo, "demo")
    position(stopped["id"], "paper", 2.00)  # its book still counts; the stopped row is not listed
    assert repo.set_deployment_status(cur, uid, stopped["id"], "stopped")
    cur.execute("UPDATE app_positions SET closed_at=%s WHERE deployment_id=%s", (day - timedelta(days=2), b["id"]))

    listed = repo.list_deployments_for_display(cur, uid)
    assert listed == repo.list_deployments(cur, uid)
    assert repr(listed) == repr(repo.list_deployments(cur, uid))  # the same types too (Decimal sums, int counts)
    by_id = {d["id"]: d for d in listed}
    assert stopped["id"] not in by_id and by_id[empty["id"]]["closed_trades"] == 0
    assert (by_id[a["id"]]["closed_trades"], by_id[a["id"]]["wins"], by_id[a["id"]]["open_positions"]) == (4, 2, 1)

    realized, counts, none = repo.closed_book_totals(cur, uid, day)
    assert realized == {m: (repo.realized_pnl(cur, uid, m), repo.realized_pnl(cur, uid, m, day)) for m in ("paper", "demo", "live")}
    assert counts == repo.closed_trade_counts(cur, uid) == {"paper": 6, "demo": 1}
    assert realized["paper"] == (pytest.approx(2.85), pytest.approx(3.20))
    # With a last visit, the same pass also sums each book since then (the "since your last visit" strip).
    assert none == {}
    again, counts2, recent = repo.closed_book_totals(cur, uid, day, day - timedelta(days=3))
    assert (again, counts2) == (realized, counts)
    assert recent == {"paper": (pytest.approx(2.85), 6), "demo": (pytest.approx(0.60), 1), "live": (0.0, 0)}
    assert repo.closed_book_totals(cur, uid, day, day)[2]["paper"] == (pytest.approx(3.20), 5)  # b's trade is older
    # With `split`, the same pass hands back each deployment's share of its book since the visit: the
    # same rows, so a book's shares add up to its figure, and no book's rows land in another's.
    *same, split = repo.closed_book_totals(cur, uid, day, day - timedelta(days=3), split=True)
    assert tuple(same) == (realized, counts, recent)
    assert split == {("paper", a["id"]): (pytest.approx(1.20), 4), ("paper", b["id"]): (pytest.approx(-0.35), 1),
                     ("paper", stopped["id"]): (pytest.approx(2.00), 1), ("demo", demo): (pytest.approx(0.60), 1)}
    for m in ("paper", "demo", "live"):
        mine = [v for (mode, _), v in split.items() if mode == m]
        assert (sum(p for p, _ in mine), sum(n for _, n in mine)) == (pytest.approx(recent[m][0]), recent[m][1]), m
    assert repo.closed_book_totals(cur, uid, day, day, split=True)[3] == {
        ("paper", a["id"]): (pytest.approx(1.20), 4), ("paper", stopped["id"]): (pytest.approx(2.00), 1),
        ("demo", demo): (pytest.approx(0.60), 1)}  # b's trade is before this visit
    # The paper ledger's balance, deposits and reset come back from one read as from the three.
    assert repo.paper_ledger_summary(cur, uid) == {"balance": repo.paper_balance(cur, uid), "deposited": repo.paper_deposits(cur, uid),
                                                   "reset_at": repo.paper_reset_at(cur, uid)}


def test_since_your_last_visit_reads_new_passes_and_the_autopilots_own_changes(conn, user):
    """passed_since lists the user's own strategies that passed since a time (not the seeded example,
    not a friend's shared copy), newest first, with the full count; activity_since counts the
    autopilot's applied, never-decided proposals by kind and the research sessions started."""
    from app import repository as repo

    cur = conn.cursor()
    uid = user["id"]
    since = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None)
    old = _deployment(conn, user)  # a passed strategy (created now) that is already deployed
    cur.execute("UPDATE app_strategies SET created_at=%s WHERE id=%s", (since - timedelta(days=1), old["strategy_id"]))
    run = repo.create_run(cur, uid, "research", "btc15m", "momentum", "an idea")
    ids = [repo.insert_strategy(cur, uid, run, None, "btc15m", "momentum", "Passed %d" % i, "t", {}, "passed", None)
           for i in range(4)]
    repo.insert_strategy(cur, uid, run, None, "btc15m", "momentum", "Rejected", "t", {}, "rejected", None)
    repo.insert_strategy(cur, uid, None, None, "btc15m", repo.DEMO_DIRECTION, "Example", "t", {}, "passed", None)
    got = repo.passed_since(cur, uid, since)
    assert got == {"n": 4, "items": [{"id": i, "title": "Passed %d" % n} for n, i in reversed(list(enumerate(ids)))][:3]}
    assert repo.passed_since(cur, uid, datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)) == {"n": 0, "items": []}

    repo.create_proposal(cur, uid, "deploy", "auto", None, ids[0], "applied")
    repo.create_proposal(cur, uid, "pause", "auto", old["id"], None, "applied")
    repo.create_proposal(cur, uid, "pause", "auto", old["id"], None, "applied")
    asked = repo.create_proposal(cur, uid, "resume", "asked", old["id"], None, "pending")
    repo.decide_proposal(cur, asked, "applied")  # the user approved it: theirs, not the autopilot's
    repo.create_proposal(cur, uid, "stop", "asked", old["id"], None, "pending")
    act = repo.activity_since(cur, uid, since)
    assert act["autopilot"] == {"deploy": 1, "pause": 2}
    assert sum(act["runs"].values()) == 1
    assert act["own_sessions"] is True  # it has a research session of its own
    assert repo.activity_since(cur, -1, since) == {"autopilot": {}, "runs": {}, "own_sessions": False,
                                                   "spent": {"since": 0.0, "week": 0.0},
                                                   "milestones": {"passed": [], "live_ready": []}}


def test_since_your_last_visit_reads_what_it_cost_and_the_paper_milestones(conn, user):
    """activity_since also sums the usage debits since the visit and over the last 7 days (top-ups and
    the welcome bonus are not spend), and lists the strategies whose bell said they passed the paper
    forward gate or became ready for live since the visit, by id, once each, newest first. Passes the
    strategy's own created_at would hide: the forward gate judges a strategy days after it was made."""
    from app import repository as repo

    cur = conn.cursor()
    uid = user["id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(hours=24)
    repo.add_credit(cur, uid, "usage", -1.25, "Agent usage · m")
    repo.add_credit(cur, uid, "usage", -0.75, "Agent usage · m")
    repo.add_credit(cur, uid, "topup", 20, "Added $20 credits", stripe_ref="t-" + uuid.uuid4().hex)
    repo.add_credit(cur, uid, "usage", -3.0, "Agent usage · m")
    cur.execute("UPDATE app_credit_ledger SET created_at=%s WHERE id=LAST_INSERT_ID()", (now - timedelta(days=3),))
    repo.add_credit(cur, uid, "usage", -9.0, "Agent usage · m")
    cur.execute("UPDATE app_credit_ledger SET created_at=%s WHERE id=LAST_INSERT_ID()", (now - timedelta(days=9),))
    repo.add_notification(cur, uid, "passed", "“A” passed the paper forward gate.", "/strategies/41")
    repo.add_notification(cur, uid, "live_ready", "“A” is ready for live trading.", "/strategies/41")
    repo.add_notification(cur, uid, "live_ready", "“B” is ready for live trading.", "/strategies/57")
    repo.add_notification(cur, uid, "live_ready", "“B” again.", "/strategies/57")
    repo.add_notification(cur, uid, "deployed", "Autopilot put “C” on paper.", "/strategies/60")  # not a milestone
    repo.add_notification(cur, uid, "passed", "“D” passed the paper forward gate.", "/strategies/12")
    cur.execute("UPDATE app_notifications SET created_at=%s WHERE id=LAST_INSERT_ID()", (now - timedelta(days=2),))
    act = repo.activity_since(cur, uid, since)
    assert act["spent"] == {"since": 2.0, "week": 5.0}
    assert act["milestones"] == {"passed": [41], "live_ready": [57, 41]}


def test_the_deploy_board_and_strategy_page_reads_answer_as_the_ones_they_replace(conn, user):
    """The Deploy board reads curves only for the deployments it lists, with the timestamp computed in
    SQL, and the strategy page sums only its own strategy's deployments. Each answers exactly as the
    full read it replaces, filtered to what the page shows: same points, same integers, same rows."""
    from decimal import Decimal

    from app import repository as repo

    cur = conn.cursor()
    uid = user["id"]
    big, small, stopped = (_deployment(conn, user) for _ in range(3))
    demo = repo.create_deployment(cur, uid, big["strategy_id"], "btc15m", "demo")
    start = datetime(2026, 3, 8, 1, 59, 30)  # across a DST change in New York: UTC throughout
    _closed_trades(conn, user, big["id"], [Decimal(i % 7 - 3) / 4 for i in range(400)], start)
    _closed_trades(conn, user, small["id"], [Decimal("0.25"), Decimal("-1.10")], start)
    _closed_trades(conn, user, demo, [Decimal("0.60")], start + timedelta(days=1))
    _closed_trades(conn, user, stopped["id"], [Decimal("2.00")] * 200, start)
    assert repo.set_deployment_status(cur, uid, stopped["id"], "stopped")

    listed = repo.list_deployments_for_display(cur, uid)
    ids = [d["id"] for d in listed]
    assert stopped["id"] not in ids and {big["id"], small["id"], demo} <= set(ids)
    full = repo.deployment_curves(cur, uid)
    shown = repo.deployment_curves(cur, uid, deployment_ids=ids)
    assert repr(shown) == repr({k: v for k, v in full.items() if k in set(ids)})
    assert stopped["id"] in full and stopped["id"] not in shown
    assert len(shown[big["id"]]) <= repo.CURVE_MAX_POINTS
    # The SQL timestamp is the integer the Python conversion of the naive-UTC DATETIME gave.
    cur.execute("SELECT closed_at FROM app_positions WHERE deployment_id IN (%s, %s)", (big["id"], small["id"]))
    stamps = {int(r["closed_at"].replace(tzinfo=timezone.utc).timestamp()) for r in cur.fetchall()}
    assert {t for t, _ in shown[big["id"]] + shown[small["id"]]} <= stamps
    assert shown[small["id"]] == [[int(start.replace(tzinfo=timezone.utc).timestamp()), 0.25],
                                  [int((start + timedelta(minutes=1)).replace(tzinfo=timezone.utc).timestamp()), -0.85]]
    counting = _Counting(cur)
    assert repo.deployment_curves(counting, uid, deployment_ids=[]) == {} and counting.n == 0  # nothing listed, no read

    # The strategy page's deployments: the same rows list_deployments gave, filtered to the strategy.
    for sid in {big["strategy_id"], small["strategy_id"], stopped["strategy_id"]}:
        mine = repo.list_deployments_for_display(cur, uid, strategy_id=sid)
        want = [d for d in repo.list_deployments(cur, uid) if d["strategy_id"] == sid]
        assert repr(mine) == repr(want), sid
    assert [d["id"] for d in repo.list_deployments_for_display(cur, uid, strategy_id=big["strategy_id"])] == [demo, big["id"]]


def test_the_run_pages_dream_line_reads_only_the_dream_lines(conn, user):
    """latest_dream_event range-scans idx_events_message for its two prefixes and answers as the
    scan over every event of every run did: the user's newest dream line, nobody else's."""
    from app import repository as repo

    cur = conn.cursor()
    uid = user["id"]
    every = ("SELECT e.message, e.created_at FROM app_agent_events e IGNORE INDEX (idx_events_message) "
             "JOIN app_agent_runs r ON r.id=e.run_id WHERE r.user_id=%s AND (e.message LIKE 'Dreaming:%%' "
             "OR e.message LIKE 'Research policy evolved%%') ORDER BY e.id DESC LIMIT 1")

    def before():
        cur.execute(every, (uid,))
        return cur.fetchone()

    assert repo.latest_dream_event(cur, uid) is None is before()
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "o@example.com", "O", None)
    first = repo.create_run(cur, uid, "research", "btc15m", "momentum")
    later = repo.create_run(cur, uid, "research", "btc15m", "momentum")
    theirs = repo.create_run(cur, other["id"], "research", "btc15m", "momentum")
    repo.add_event(cur, first, "step", "Dreaming: tested 4 candidate policies over 60 hypotheses")
    repo.add_event(cur, later, "step", "Research policy evolved: dreamed over 61 hypotheses")
    repo.add_event(cur, first, "step", "dreaming: lower case still matches, as LIKE did")
    repo.add_event(cur, later, "agent", "Testing a fade of the open")
    repo.add_event(cur, theirs, "step", "Dreaming: someone else's line")
    got = repo.latest_dream_event(cur, uid)
    assert got == before() and got["message"].startswith("dreaming: lower case")
    cur.execute("SHOW INDEX FROM app_agent_events WHERE Key_name='idx_events_message'")
    assert [(r["Column_name"], r["Sub_part"]) for r in cur.fetchall()] == [("message", 24)]  # schema.main added it


def test_the_credit_balance_reads_its_covering_index_and_stays_exact(conn, user):
    """credit_balance is the same SUM over the user's ledger rows. idx_credit_user_amount
    (user_id, amount_usd) only lets it read them off the index; the total stays exact to the
    micro-dollar, with nobody else's rows in it."""
    import random
    from decimal import Decimal
    from app import repository as repo

    cur = conn.cursor()
    uid = user["id"]
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "o@example.com", "O", None)
    rng = random.Random(5)
    cur.execute("SELECT amount_usd FROM app_credit_ledger WHERE user_id=%s", (uid,))
    welcome = sum((r["amount_usd"] for r in cur.fetchall()), Decimal(0))  # the sign-up bonus
    amounts = [Decimal("20"), Decimal("0.000001"), Decimal("-0.000001"), Decimal("-12.345678"), Decimal("99999.999999")]
    amounts += [Decimal(rng.randint(-5_000_000, 5_000_000)) / 1_000_000 for _ in range(400)]
    for i, amount in enumerate(amounts):
        repo.add_credit(cur, uid, "usage" if amount < 0 else "topup", amount, "t%d" % i)
    repo.add_credit(cur, other["id"], "topup", Decimal("7.777777"), "someone else")
    exact = sum(amounts, welcome)
    cur.execute("SELECT COALESCE(SUM(amount_usd),0) AS b FROM app_credit_ledger IGNORE INDEX (idx_credit_user_amount) "
                "WHERE user_id=%s", (uid,))
    assert cur.fetchone()["b"] == exact
    cur.execute("SELECT COALESCE(SUM(amount_usd),0) AS b FROM app_credit_ledger FORCE INDEX (idx_credit_user_amount) "
                "WHERE user_id=%s", (uid,))
    assert cur.fetchone()["b"] == exact
    assert repo.credit_balance(cur, uid) == float(exact)
    assert repo.credit_balance(cur, other["id"]) == float(welcome + Decimal("7.777777"))
    cur.execute("SHOW INDEX FROM app_credit_ledger WHERE Key_name='idx_credit_user_amount'")
    assert [r["Column_name"] for r in sorted(cur.fetchall(), key=lambda r: r["Seq_in_index"])] == ["user_id", "amount_usd"]


def test_last_autopilot_action_looks_back_a_bounded_window_of_chat(conn, user, monkeypatch):
    """The 20s status poll used to scan a user's whole chat history for the last autopilot line
    whenever there was none. It now looks through the newest LAST_ACTION_WINDOW rows and answers
    as before for any line inside that window."""
    from app import repository as repo
    from app.adapters.db import chat_repository

    old = ("SELECT content, created_at FROM app_chat_messages WHERE user_id=%s AND role='system' AND "
           "(content LIKE '%%utopilot%%' OR content LIKE '%%LIVE%%' OR content LIKE '%%Kill%%') ORDER BY id DESC LIMIT 1")
    uid, cur = user["id"], conn.cursor()

    def before():
        cur.execute(old, (uid,))
        r = cur.fetchone()
        return {"text": r["content"], "at": r["created_at"]} if r else None

    assert repo.last_autopilot_action(cur, uid) is None is before()
    repo.add_chat(cur, uid, "system", "Autopilot deployed Lean into the move on paper.")
    repo.add_chat(cur, uid, "agent", "Autopilot is on; I'll keep an eye on it.")  # not a system line
    repo.add_chat(cur, uid, "system", "Kill switch: live autopilot off, 0 live deployment(s) paused.")
    for i in range(20):
        repo.add_chat(cur, uid, "user" if i % 2 else "system", "Checked the markets; nothing to change.")
    got = repo.last_autopilot_action(cur, uid)
    assert got == before() and got["text"].startswith("Kill switch")
    monkeypatch.setattr(chat_repository, "LAST_ACTION_WINDOW", 21)
    assert repo.last_autopilot_action(cur, uid)["text"].startswith("Kill switch")  # 21 rows back: inside
    monkeypatch.setattr(chat_repository, "LAST_ACTION_WINDOW", 20)
    assert repo.last_autopilot_action(cur, uid) is None  # outside the window


def test_the_engines_own_pause_is_the_last_move_with_its_strategy(conn, user):
    """The engine's "Paused deployment #N automatically." names neither the autopilot nor the strategy,
    so the card's last move stayed on an older deploy. It is the last move now, with the paused
    deployment's strategy title and book for the panel to say it by name; another user's deployment
    number never reads a title."""
    from app import repository as repo

    cur, uid = conn.cursor(), user["id"]
    dep = _deployment(conn, user)
    repo.add_chat(cur, uid, "system", "Autopilot deployed Lean into it on paper.")
    line = "Paused deployment #%d automatically. Lost $12.00, more than the $10.00 guard (2x its worst backtest drawdown)." % dep["id"]
    repo.add_chat(cur, uid, "system", line)
    got = repo.last_autopilot_action(cur, uid)
    assert got["text"] == line  # the engine's text as written
    assert got["deployment"] == {"id": dep["id"], "title": "T", "mode": "paper"}
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "o@example.com", "O", None)
    repo.add_chat(cur, other["id"], "system", line)
    assert repo.last_autopilot_action(cur, other["id"])["deployment"] == {"id": dep["id"], "title": None, "mode": None}
    repo.add_chat(cur, uid, "system", "Autopilot paused Rain: it hit its loss guard.")
    assert "deployment" not in repo.last_autopilot_action(cur, uid)


def test_the_chat_feed_says_the_engines_pause_by_name_and_keeps_the_stored_line(conn, user):
    """The chat feed read the engine's "Paused deployment #N automatically." as stored. It says the
    strategy by name now (GET /api/chat), the stored row keeps the engine's words, and another user's
    deployment number reads no title."""
    from types import SimpleNamespace

    from app import repository as repo
    from app.web.routes import chat as chat_routes

    cur, uid = conn.cursor(), user["id"]
    dep = _deployment(conn, user)
    line = "Paused deployment #%d automatically. Lost $12.00, more than the $10.00 guard (2x its worst backtest drawdown)." % dep["id"]
    repo.add_chat(cur, uid, "system", line)
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "o@example.com", "O", None)
    assert repo.deployment_names(cur, uid, [dep["id"], dep["id"] + 999]) == {dep["id"]: {"title": "T", "mode": "paper"}}
    assert repo.deployment_names(cur, other["id"], [dep["id"]]) == {}
    assert repo.deployment_names(cur, uid, []) == {}

    def feed(user_id):
        out = chat_routes.get_chat(SimpleNamespace(cur=cur, uid=user_id, query={}))
        return [m["content"] for m in out["messages"] if m["role"] == "system"]

    assert feed(uid) == ["Paused your paper strategy T automatically: it lost $12.00, more than its $10.00 loss guard."]
    repo.add_chat(cur, other["id"], "system", line)
    assert feed(other["id"]) == ["Paused one of your strategies automatically: it lost $12.00, more than its $10.00 loss guard."]
    assert [m["content"] for m in repo.chat_messages(cur, uid)] == [line]  # the engine's words, as written


def test_chat_lines_name_the_book_a_proposal_would_change(conn, user):
    """The agent panel says whether Approve touches real money: a proposal's chat line carries its
    deployment's book; a line with no deployment (a risk change, plain chat) carries none."""
    from app import repository as repo

    cur = conn.cursor()
    dep = _deployment(conn, user)
    cur.execute("UPDATE app_deployments SET mode='live' WHERE id=%s", (dep["id"],))
    pause = repo.create_proposal(cur, user["id"], "pause", "Drawdown.", dep["id"], None, "pending")
    risk = repo.create_proposal(cur, user["id"], "set_risk", "Tighter.", None, None, "pending",
                                payload={"max_open_positions": 2})
    repo.add_chat(cur, user["id"], "system", "Proposed to pause T.", pause)
    repo.add_chat(cur, user["id"], "system", "Proposed a risk-control change.", risk)
    repo.add_chat(cur, user["id"], "user", "Why?")
    lines = repo.chat_messages(cur, user["id"])[-3:]
    assert [(m["proposal_kind"], m["deployment_mode"]) for m in lines] == [
        ("pause", "live"), ("set_risk", None), (None, None)]
