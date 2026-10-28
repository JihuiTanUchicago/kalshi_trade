"""Each book against its backtest, against a real MySQL: what counts as one completed trade in each
book (repo.book_trade_stats), and the lines the strategy page and the Deploy board get. Books are
never added up. Display only. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1)."""
import os
import uuid
from datetime import timedelta

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

TICKER = "KXBTC15M-26OCT251800-T98"


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.cursor().execute("UPDATE app_deployments SET status='stopped' WHERE user_id IN "
                       "(SELECT id FROM app_users WHERE google_sub LIKE 'test:%%')")
    c.close()


@pytest.fixture(autouse=True)
def fresh_cache():
    from app import server

    server._BACKTEST_CHECKS.clear()
    yield
    server._BACKTEST_CHECKS.clear()


def _setup(conn):
    """A strategy whose unseen-data backtest made +$0.15 a trade and won 61%, on paper, live and a
    stopped demo deployment, plus another strategy whose trades must never count."""
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "bt@example.com", "B", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 2}})
    result = {"capital": 10.0, "out_of_sample": {"trades": 40, "pnl": 6.0, "win_rate": 0.61},
              "in_sample": {"trades": 90, "pnl": 30.0, "win_rate": 0.7}}
    sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Checked", "t", spec, "passed", result)
    other = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Other", "t", spec, "passed", result)
    deps = {m: repo.create_deployment(cur, uid, sid, "btc15m", m) for m in ("paper", "live", "demo")}
    cur.execute("UPDATE app_deployments SET status='stopped' WHERE id=%s", (deps["demo"],))
    return uid, sid, other, deps, repo.create_deployment(cur, uid, other, "btc15m", "paper")


def _closed(conn, uid, did, mode, pnl, ref=None, qty=10, price=0.46):
    from app import repository as repo

    now = repo.now_utc()
    repo.insert_closed_position(conn.cursor(), did, uid, mode, TICKER, "yes", qty, price, 0.07, price + pnl / qty, 0.07,
                                pnl, "settled", now + timedelta(hours=1), order_ref=ref,
                                opened_at=now - timedelta(hours=2), closed_at=now - timedelta(hours=1))


def _seed(conn):
    from app import repository as repo

    uid, sid, other, deps, other_dep = _setup(conn)
    # Paper: 12 completed trades through the simulated venue averaging +$0.12, one of them sold in two slices.
    for i in range(11):
        _closed(conn, uid, deps["paper"], "paper", 0.62 if i % 2 == 0 else -0.38, ref="sim:%d" % i)
    _closed(conn, uid, deps["paper"], "paper", -0.20, ref="sim:split", qty=6)
    _closed(conn, uid, deps["paper"], "paper", -0.18, ref="sim:split", qty=4)
    _closed(conn, uid, deps["paper"], "paper", 9.0)                      # instant fill: not evidence
    _closed(conn, uid, deps["paper"], "paper", 9.0, ref="sim:half")      # sold half...
    repo.insert_position(conn.cursor(), deps["paper"], uid, "paper", TICKER, "yes", 5, 0.46, 0.03,
                         repo.now_utc() + timedelta(hours=1), "sim:half")  # ...the rest still open: waits
    # Live: 3 trades, too early. Demo (stopped): 10 trades losing 50c each.
    for _ in range(3):
        _closed(conn, uid, deps["live"], "live", 0.40, ref="live-%s" % uuid.uuid4().hex)
    for _ in range(10):
        _closed(conn, uid, deps["demo"], "demo", -0.50)
    _closed(conn, uid, other_dep, "paper", 50.0, ref="sim:other")      # another strategy
    return uid, sid, other, deps


def test_a_books_trades_are_its_own_completed_round_trips(conn):
    from app import repository as repo

    uid, sid, other, _deps = _seed(conn)
    stats = repo.book_trade_stats(conn.cursor(), uid, [sid, other])
    paper, live, demo = stats[sid]["paper"], stats[sid]["live"], stats[sid]["demo"]
    assert paper["trades"] == 12 and paper["pnl"] == pytest.approx(6 * 0.62 - 5 * 0.38 - 0.38)
    assert paper["wins"] == 6 and paper["cost"] == pytest.approx(12 * 10 * 0.46)
    assert live["trades"] == 3 and demo["trades"] == 10 and demo["pnl"] == pytest.approx(-5.0)
    assert stats[other] == {"paper": {"trades": 1, "pnl": 50.0, "pnl_sq": 2500.0, "wins": 1, "cost": pytest.approx(4.6)}}
    assert repo.book_trade_stats(conn.cursor(), uid, []) == {}


def test_the_strategy_page_and_the_deploy_board_get_one_line_per_book(conn):
    from app import repository as repo
    from app import server

    uid, sid, _other, deps = _seed(conn)

    def ctx(*params):
        return server.Ctx(conn, repo.get_user(conn.cursor(), uid), tuple(str(p) for p in params), {}, {}, None)

    checks = server.get_strategy(ctx(sid))["backtest_checks"]
    assert [c["mode"] for c in checks] == ["live", "demo", "paper"]
    live, demo, paper = checks
    assert live["verdict"] == "early" and live["line"].startswith("On live: 3 completed trades so far across all its live runs; too early to tell")
    assert demo["verdict"] == "behind" and demo["line"].startswith(
        "Behind its backtest on demo: 10 trades across all its demo runs: −$0.50/trade vs backtest +$0.15/trade; won 0% vs 61%.")
    assert paper["verdict"] == "within"
    assert paper["line"] == ("On paper: 12 trades across all its paper runs, realistic fills only: +$0.12/trade net of "
                             "fees and spread vs backtest +$0.15/trade; won 50% vs 61%. "
                             "Within the backtest’s usual range.")
    rows = {d["id"]: d for d in server.list_deployments(ctx())["deployments"]}
    assert rows[deps["paper"]]["backtest_check"] == paper and rows[deps["live"]]["backtest_check"] == live
    assert deps["demo"] not in rows  # a stopped deployment is off the board; its trades still count above
