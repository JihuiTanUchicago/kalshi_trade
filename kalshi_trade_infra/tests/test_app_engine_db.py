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

    dep = _deployment(conn, user)
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
    cur.execute("SELECT status, exit_price, pnl FROM app_positions WHERE id=%s", (pid,))
    row = cur.fetchone()
    assert row["status"] == "settled" and float(row["exit_price"]) == 1.0
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
