"""Removed deployments, as the Deploy board and the strategy page name them, against a real MySQL.

Deploy's "Realized" sums the deployments it lists. The dashboard's all-time figure for a book also
counts the deployments that were removed (stopped), so the two disagreed (+$146.04 against +$151.76)
with nothing on the page saying why. The board now sends each book's removed total
(repo.removed_deployments with each deployment's own closed positions, repo.deployment_closed_totals),
and for paper and live the two together, which must be the dashboard's figure to the cent. The strategy
page lists its removed deployments with their book, dates and realized P&L.

One user, written through the repository layer only (no engine, no order): paper, demo and live
deployments, some removed, with closed trades, a part-sold slice on a removed deployment, an open
position on a removed one, a removed deployment whose strategy was then deleted, and a second account
beside it. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

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


@pytest.fixture
def quiet(monkeypatch):
    from app.adapters.stripe import billing
    from app.services import book_memo
    from app.trading import engine
    from app.web.routes import dashboard as dashboard_routes

    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(dashboard_routes, "_freshness", lambda c: {})
    book_memo.clear()
    yield
    book_memo.clear()


def _user(cur, label):
    from app import repository as repo

    return repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, label + "@example.invalid", label, None)["id"]


def _strategy(cur, uid, title):
    from app import repository as repo
    from app.trading import spec as specmod

    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 4}})
    result = {"capital": 20.0, "in_sample": {"trades": 80, "pnl": 9.0}, "out_of_sample": {"trades": 30, "pnl": 3.0}}
    return repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", title, "t", spec, "passed", result)


def _closed(cur, did, uid, mode, pnls, tag):
    """Closed round trips on deployment `did`, one per P&L (four places, as app_positions keeps it)."""
    from app import repository as repo

    at = datetime(2026, 10, 20, 12, 0)
    for i, pnl in enumerate(pnls):
        repo.insert_closed_position(cur, did, uid, mode, "KXBTC15M-26OCT20%02d-T98" % i, "yes", 3, 0.4, 0.05,
                                    1.0 if pnl > 0 else 0.0, 0.05, pnl, "settled", at + timedelta(hours=i),
                                    order_ref="%s:%s-%d" % ("sim" if mode == "paper" else mode, tag, i),
                                    opened_at=at + timedelta(hours=i, minutes=-20), closed_at=at + timedelta(hours=i))


def _book(conn):
    from app import repository as repo

    cur = conn.cursor()
    uid = _user(cur, "removed")
    s_a, s_b, s_gone = (_strategy(cur, uid, t) for t in ("Fade tails", "Rain", "Deleted later"))
    dep = {}
    for key, sid, mode in (("paper_on", s_a, "paper"), ("paper_old", s_a, "paper"), ("paper_older", s_a, "paper"),
                           ("demo_on", s_a, "demo"), ("demo_old", s_a, "demo"), ("live_on", s_b, "live"),
                           ("live_old", s_b, "live"), ("paper_b_old", s_b, "paper"), ("gone", s_gone, "paper")):
        dep[key] = repo.create_deployment(cur, uid, sid, "btc15m", mode)
    _closed(cur, dep["paper_on"], uid, "paper", [40.0249, 106.0151], "on")
    _closed(cur, dep["paper_old"], uid, "paper", [3.3333, -1.1111], "old")
    _closed(cur, dep["paper_older"], uid, "paper", [2.0049], "older")
    _closed(cur, dep["paper_b_old"], uid, "paper", [0.5], "bold")
    _closed(cur, dep["gone"], uid, "paper", [1.25], "gone")
    _closed(cur, dep["demo_on"], uid, "demo", [-10.0], "don")
    _closed(cur, dep["demo_old"], uid, "demo", [4.0], "dold")
    _closed(cur, dep["live_on"], uid, "live", [2.5], "lon")
    _closed(cur, dep["live_old"], uid, "live", [-0.75, 1.0], "lold")
    # A removed deployment that still holds a position, then sells part of it: the sold slice is realized.
    pid = repo.insert_position(cur, dep["paper_old"], uid, "paper", "KXBTC15M-26OCT2612-T99", "yes", 4, 0.4, 0.04,
                               datetime(2026, 10, 27, 12), order_ref="sim:held")
    for key in ("paper_old", "paper_older", "demo_old", "live_old", "paper_b_old", "gone"):
        assert repo.set_deployment_status(cur, uid, dep[key], "stopped", "By you")
    cur.execute("SELECT * FROM app_positions WHERE id=%s", (pid,))
    assert repo.book_partial_exit(cur, cur.fetchone(), 1, 0.7, 0.01, 0.2899, "take_profit")
    assert repo.delete_strategy(cur, uid, s_gone)  # an old strategy deleted after its deployment was removed
    # Another account's removed deployment never shows here.
    other = _user(cur, "beside")
    o_sid = _strategy(cur, other, "Not mine")
    o_dep = repo.create_deployment(cur, other, o_sid, "btc15m", "paper")
    _closed(cur, o_dep, other, "paper", [99.0], "other")
    assert repo.set_deployment_status(cur, other, o_dep, "stopped", "By you")
    return uid, {"a": s_a, "b": s_b, "gone": s_gone}, dep


def _closed_sum(cur, ids):
    cur.execute("SELECT COALESCE(SUM(pnl),0) AS p, COUNT(*) AS n FROM app_positions WHERE status='closed' AND deployment_id IN ("
                + ",".join(["%s"] * len(ids)) + ")", tuple(ids))
    r = cur.fetchone()
    return Decimal(str(r["p"])), int(r["n"])


def _ctx(conn, uid, *params):
    from app import repository as repo
    from app import server

    return server.Ctx(conn, repo.get_user(conn.cursor(), uid), tuple(str(p) for p in params), {}, {}, None)


def test_removed_deployments_are_the_users_stopped_ones_newest_first(conn, quiet):
    from app import repository as repo

    uid, sids, dep = _book(conn)
    cur = conn.cursor()
    rows = repo.removed_deployments(cur, uid)
    assert [r["id"] for r in rows] == sorted((dep[k] for k in ("paper_old", "paper_older", "demo_old", "live_old",
                                                                "paper_b_old", "gone")), reverse=True)
    by_id = {r["id"]: r for r in rows}
    assert by_id[dep["gone"]]["title"] is None  # its strategy row was deleted; the deployment still counts
    assert by_id[dep["live_old"]]["mode"] == "live" and by_id[dep["live_old"]]["strategy_id"] == sids["b"]
    cur.execute("SELECT id, created_at, updated_at FROM app_deployments WHERE id=%s", (dep["paper_old"],))
    stored = cur.fetchone()
    assert (by_id[dep["paper_old"]]["created_at"], by_id[dep["paper_old"]]["removed_at"]) == (stored["created_at"], stored["updated_at"])
    assert [r["id"] for r in repo.removed_deployments(cur, uid, sids["a"])] == [dep["demo_old"], dep["paper_older"], dep["paper_old"]]
    assert repo.removed_deployments(cur, uid, 10 ** 12) == []


def test_the_deploy_board_and_the_dashboard_reconcile_book_by_book(conn, quiet):
    from app import repository as repo
    from app import server

    uid, sids, dep = _book(conn)
    cur = conn.cursor()
    board = server.list_deployments(_ctx(conn, uid))
    dash = server.dashboard(_ctx(conn, uid))
    books = board["realized_by_book"]
    removed = {"paper": ["paper_old", "paper_older", "paper_b_old", "gone"], "demo": ["demo_old"], "live": ["live_old"]}
    listed = {"paper": ["paper_on"], "demo": ["demo_on"], "live": ["live_on"]}
    for mode in ("paper", "demo", "live"):
        gone, n_gone = _closed_sum(cur, [dep[k] for k in removed[mode]])
        shown, _ = _closed_sum(cur, [dep[k] for k in listed[mode]])
        assert books[mode]["removed"] == round(float(gone), 2), mode
        assert books[mode]["removed_deployments"] == len(removed[mode]), mode
        assert books[mode]["listed"] == round(float(shown), 2) == round(sum(r["realized_pnl"] for r in board["deployments"]
                                                                            if r["mode"] == mode), 2), mode
        if mode == "demo":
            assert "all" not in books[mode]  # its dashboard figure counts from its last reload
            continue
        # The two together are the dashboard's all-time figure for the book, to the cent.
        assert books[mode]["all"] == dash[mode]["realized_pnl"] == round(float(shown + gone), 2), mode
    # The part-sold slice on a removed deployment is in its total; the other account's never is.
    assert _closed_sum(cur, [dep["paper_old"]])[1] == 3
    assert books["paper"]["removed"] == round(3.3333 - 1.1111 + 0.2899 + 2.0049 + 0.5 + 1.25, 2)
    # Books are never added together: no figure is two books' money.
    cross = {round(books[a]["listed"] + books[b]["listed"], 2) for a in books for b in books if a != b}
    assert not cross & {v for m in books for v in books[m].values() if isinstance(v, float)}
    assert board["deployments"] and all(r["id"] not in {dep[k] for ks in removed.values() for k in ks} for r in board["deployments"])


def test_the_boards_removed_totals_are_kept_and_never_stale(conn, quiet):
    """The removed deployments are read every poll (one is removed without a position changing); their
    totals are kept for that set of deployments while the positions are unchanged."""
    from app import repository as repo
    from app import server

    uid, sids, dep = _book(conn)
    cur = conn.cursor()

    class Counting:
        def __init__(self, c):
            self.conn, self.log = c, []

        def cursor(self):
            k = self.conn.cursor()
            ex = k.execute

            def execute(sql, params=None):
                self.log.append(" ".join(str(sql).split()))
                return ex(sql, params)
            k.execute = execute
            return k

    counting = Counting(conn)
    totals = "AND status='closed' GROUP BY deployment_id"

    def board():
        counting.log = []
        out = server.list_deployments(server.Ctx(counting, repo.get_user(cur, uid), (), {}, {}, None))
        return out["realized_by_book"], sum(totals in s for s in counting.log)

    first, n = board()
    assert n == 1
    again, n = board()
    assert again == first and n == 0  # kept
    # A deployment removed, no position changed: the board counts it at once.
    assert repo.set_deployment_status(cur, uid, dep["paper_on"], "stopped", "By you")
    moved, n = board()
    assert n == 1 and moved["paper"]["removed_deployments"] == first["paper"]["removed_deployments"] + 1
    assert moved["paper"]["listed"] == 0.0 and moved["paper"]["all"] == first["paper"]["all"]
    # A trade closes on a removed deployment (its held position sells the rest): read again.
    cur.execute("SELECT id FROM app_positions WHERE user_id=%s AND order_ref='sim:held' AND status='open'", (uid,))
    assert repo.close_position(cur, cur.fetchone()["id"], 0.9, 0.03, 1.4567, "take_profit")
    after, n = board()
    gone = [dep[k] for k in ("paper_on", "paper_old", "paper_older", "paper_b_old", "gone")]
    assert n == 1 and after["paper"]["removed"] == round(float(_closed_sum(cur, gone)[0]), 2) != moved["paper"]["removed"]
    assert after["paper"]["all"] == server.dashboard(_ctx(conn, uid))["paper"]["realized_pnl"]


def test_the_strategy_page_lists_its_past_deployments(conn, quiet):
    from app import server

    uid, sids, dep = _book(conn)
    cur = conn.cursor()
    page = server.get_strategy(_ctx(conn, uid, sids["a"]))
    past = page["past_deployments"]
    assert [p["id"] for p in past] == [dep["demo_old"], dep["paper_older"], dep["paper_old"]]
    for p in past:
        pnl, n = _closed_sum(cur, [p["id"]])
        assert (p["realized_pnl"], p["closed_trades"]) == (round(float(pnl), 2), n)
        cur.execute("SELECT mode, created_at, updated_at FROM app_deployments WHERE id=%s", (p["id"],))
        r = cur.fetchone()
        assert (p["mode"], p["created_at"], p["removed_at"]) == (r["mode"], r["created_at"], r["updated_at"])
    assert {d["id"] for d in page["deployments"]} == {dep["paper_on"], dep["demo_on"]}  # the current ones stay apart
    assert server.get_strategy(_ctx(conn, uid, sids["b"]))["past_deployments"][0]["id"] == dep["paper_b_old"]
    # A strategy never deployed has none.
    fresh = _strategy(cur, uid, "Never deployed")
    assert server.get_strategy(_ctx(conn, uid, fresh))["past_deployments"] == []
