"""The Strategies list against a real MySQL: "best on unseen data first", the autopilot flag, and what
each card's removed deployments made.

The list is paged server-side (50 a page), so finding the best strategy needs the read itself to order
by the unseen-data (out-of-sample) backtest P&L stored in result_json; a page-local sort would miss a
better strategy on page two. A strategy with no unseen test (rejected, tested only, a result with no
P&L) goes last. The card also says when the autopilot found the strategy (its run's brief flag) and,
per book, what its removed deployments made, which together with its active deployment is its book's
whole record. Written through the repository layer only (no engine, no order). Opt in as for
test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
import uuid
from datetime import timedelta

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


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


def _result(pnl):
    ins = {"trades": 50, "pnl": 99.0, "win_rate": 0.6}  # in-sample: never the order key
    if pnl == "no-oos":
        return {"in_sample": ins}
    if pnl == "no-pnl":
        return {"in_sample": ins, "out_of_sample": {"trades": 3}}
    return {"in_sample": ins, "out_of_sample": {"trades": 20, "pnl": pnl, "win_rate": 0.5}}


def test_the_list_finds_the_best_strategy_flags_the_autopilot_and_keeps_removed_money(conn, monkeypatch):
    from app import repository as repo
    from app import server
    from app.services import book_memo
    from app.trading import spec as specmod

    book_memo.clear()
    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "lister@example.invalid", "L", None)["id"]
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "other@example.invalid", "O", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 1}})
    ap_run = repo.create_run(cur, uid, "research", "btc15m", None, "angle", brief=True)
    own_run = repo.create_run(cur, uid, "research", "btc15m", "momentum", "my idea")
    sid = {}
    for title, status, pnl, run in (("mid", "passed", 5.0, own_run), ("worst", "passed", -3.25, ap_run),
                                    ("best", "backtest-only", 12.5, ap_run), ("rejected", "rejected", "no-oos", own_run),
                                    ("no pnl", "passed", "no-pnl", None), ("tiny", "passed", 0.5, None)):
        sid[title] = repo.insert_strategy(cur, uid, run, None, "btc15m", "momentum", title, "t", spec, status, _result(pnl))
    repo.insert_strategy(cur, other, None, None, "btc15m", "momentum", "theirs", "t", spec, "passed", _result(500.0))

    user = repo.get_user(cur, uid)

    def page(**query):
        return server.list_strategies(server.Ctx(conn, user, (), {k: str(v) for k, v in query.items()}, {}, None))

    # The seeded example session's strategies list too (marked "example"); these checks read the user's own.
    titles = lambda out: [c["title"] for c in out["strategies"] if not c.get("example")]  # noqa: E731
    # Best first on unseen data, over every status the view shows; no unseen P&L goes last, newest first.
    assert titles(page(sort="best", status="")) == ["best", "mid", "tiny", "worst", "no pnl"]
    assert titles(page(sort="best", status="rejected")) == ["rejected"]
    # It pages in that order: the second page carries on from the first.
    first = repo.list_strategies(cur, uid, sort="best", limit=2, offset=0, hide_noise=True)
    second = repo.list_strategies(cur, uid, sort="best", limit=2, offset=2, hide_noise=True)
    assert [r["title"] for r in first + second] == ["best", "mid", "tiny", "worst"]
    # The default order is unchanged: newest first, rejected last.
    assert titles(page(status="")) == ["tiny", "no pnl", "best", "worst", "mid"]

    # The autopilot's finds are flagged; the user's own and the chat-made ones are not.
    cards = {c["title"]: c for c in page(status="")["strategies"]}
    assert {t for t, c in cards.items() if c.get("by_autopilot")} == {"best", "worst"}

    # Removed deployments: each book's own total, beside the active record, never added in.
    now = repo.now_utc()

    def closed(did, mode, pnl, i):
        repo.insert_closed_position(cur, did, uid, mode, "KXSL-%s-%d" % (uuid.uuid4().hex[:6], i), "yes", 2, 0.5, 0.02,
                                    1.0, 0.0, pnl, "settled", now, opened_at=now - timedelta(hours=1), closed_at=now)

    gone_paper = repo.create_deployment(cur, uid, sid["mid"], "btc15m", "paper")
    closed(gone_paper, "paper", 1.25, 1)
    closed(gone_paper, "paper", -0.5, 2)
    repo.set_deployment_status(cur, uid, gone_paper, "stopped", "By you")
    gone_demo = repo.create_deployment(cur, uid, sid["mid"], "btc15m", "demo")
    closed(gone_demo, "demo", 3.0, 3)
    repo.set_deployment_status(cur, uid, gone_demo, "stopped", "By you")
    empty = repo.create_deployment(cur, uid, sid["mid"], "btc15m", "paper")  # removed before any trade closed
    repo.set_deployment_status(cur, uid, empty, "stopped", "By you")
    live_now = repo.create_deployment(cur, uid, sid["mid"], "btc15m", "paper")
    closed(live_now, "paper", 2.0, 4)
    repo.insert_position(cur, live_now, uid, "paper", "KXSL-OPEN-%s" % uuid.uuid4().hex[:6], "yes", 2, 0.4, 0.02,
                         now + timedelta(hours=1))  # an open position is no closed trade
    book_memo.clear()
    cards = {c["title"]: c for c in page(status="")["strategies"]}
    mid = cards["mid"]
    assert mid["books"] == ["paper"] and mid["real"]["pnl"] == 2.0 and mid["real"]["trades"] == 1
    assert mid["past"] == {"paper": {"pnl": 0.75, "trades": 2, "deployments": 2},
                           "demo": {"pnl": 3.0, "trades": 1, "deployments": 1}}
    # Active + removed paper is the strategy's whole paper book, which the dashboard counts.
    assert round(mid["real"]["pnl"] + mid["past"]["paper"]["pnl"], 2) == round(repo.realized_pnl(cur, uid, "paper"), 2)
    assert all("past" not in c for t, c in cards.items() if t != "mid")
