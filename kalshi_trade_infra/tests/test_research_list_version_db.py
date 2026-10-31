"""The research list's "unchanged" answer against a real MySQL (services.research_list).

The page polls /api/runs every 5s and sends back the version of its last full answer. The version must
move with every write that changes what the list shows (a new session, its progress, its end, a cancel,
a usage debit, the policy, a session going quiet) and with nothing else: not a heartbeat, not another
user's writes. A full answer is what the page would have got without the version. Opt in as for
test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
import uuid
from datetime import timedelta
from unittest import mock

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


def _user(cur):
    from app import repository as repo

    return repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "t@example.com", "T", None)


def test_the_list_version_moves_with_what_the_list_shows_and_nothing_else(conn):
    from app import repository as repo
    from app import server

    cur = conn.cursor()
    user, other = _user(cur), _user(cur)
    uid = user["id"]
    done = repo.create_run(cur, uid, "research", "btc15m", "momentum", run_forever=True)
    cur.execute("UPDATE app_agent_runs SET status='succeeded', finished_at=%s WHERE id=%s", (repo.now_utc(), done))
    live = repo.create_run(cur, uid, "research", "btc15m", "momentum", run_forever=True)
    cur.execute("UPDATE app_agent_runs SET status='running', started_at=%s, heartbeat_at=%s WHERE id=%s",
                (repo.now_utc(), repo.now_utc(), live))
    theirs = repo.create_run(cur, other["id"], "research", "btc15m", "momentum")
    conn.commit()

    def poll(since=None):
        server._RUN_TOTALS.clear()
        statements = []
        real = cur.execute
        cur.execute = lambda sql, args=None: (statements.append(sql), real(sql, args))[1]
        try:
            out = server.list_runs(server.Ctx(conn, user, (), {"since": since} if since else {}, {}, None))
        finally:
            del cur.execute
        conn.commit()
        return out, statements

    first, _ = poll()
    assert first["v"] and [r["id"] for r in first["runs"]][:2] == [live, done]  # then the seeded example
    v = first["v"]
    same, statements = poll(v)
    assert same == {"v": v, "same": True}
    assert not any("app_agent_events" in s for s in statements)  # no log probe, no ledger sum, no policy read
    assert not any("SUM(amount_usd)" in s or "FROM app_policies WHERE" in s for s in statements)

    # Neither a heartbeat (every event bumps it) nor another user's writes move it.
    repo.add_event(cur, live, "thinking", "weighing the spread")
    repo.update_run_progress(cur, theirs, 3, 1)
    repo.add_credit(cur, other["id"], "usage", -0.25, "theirs", run_id=theirs)
    repo.set_policy(cur, other["id"], "x", 0.5)
    conn.commit()
    assert poll(v)[0] == {"v": v, "same": True}

    # Every write the list shows moves it, and the full answer is the one a fresh poll gets.
    writes = [
        lambda: repo.update_run_progress(cur, live, 4, 0),
        lambda: repo.add_credit(cur, uid, "usage", -0.12, "research", run_id=live),
        lambda: repo.set_policy(cur, uid, "y", 0.7, "Prefers fading", 0.6),
        lambda: repo.set_run_market(cur, live, "btc_daily"),
        lambda: repo.pause_run(cur, uid, live),
        lambda: repo.resume_run(cur, uid, live),
        # A running session whose worker went quiet leaves the live counts (the clock, not a write).
        lambda: cur.execute("UPDATE app_agent_runs SET heartbeat_at=%s WHERE id=%s",
                            (repo.now_utc() - timedelta(hours=3), live)),
        lambda: repo.cancel_run(cur, uid, live),
        lambda: repo.create_run(cur, uid, "research", "eth_daily", "momentum"),
    ]
    for i, write in enumerate(writes):
        write()
        conn.commit()
        # One clock for both polls: a quiet session's wait in seconds must not tick between them.
        with mock.patch.object(repo, "now_utc", lambda t=repo.now_utc(): t):
            got, _ = poll(v)
            assert not got.get("same") and got["v"] != v, i
            fresh, _ = poll()
        assert got == fresh, i
        v = got["v"]
        assert poll(v)[0] == {"v": v, "same": True}, i

    # A user with no sessions has nothing to compare: always the full answer.
    empty = _user(cur)
    cur.execute("DELETE FROM app_agent_runs WHERE user_id=%s", (empty["id"],))  # its seeded example
    conn.commit()
    out = server.list_runs(server.Ctx(conn, empty, (), {"since": "anything"}, {}, None))
    assert out["v"] is None and not out["runs"] and not out.get("same")


def test_older_sessions_page_past_the_newest_and_number_from_the_users_own_count(conn):
    """A six-month account's 200 sessions: the list holds the newest RUNS_LISTED, its answer counts every own one
    (own_total), and ?before=<the oldest shown> pages the rest, numbered as the newest page numbers them."""
    from app import repository as repo
    from app import server

    cur = conn.cursor()
    user, other = _user(cur), _user(cur)
    mine = [repo.create_run(cur, user["id"], "research", "btc15m", "momentum") for _ in range(repo.RUNS_LISTED + 7)]
    repo.create_run(cur, other["id"], "research", "btc15m", "momentum")  # never in this user's pages
    # Finished, as six months of sessions are: one at work leads the first page however old (the next test).
    cur.execute("UPDATE app_agent_runs SET status='succeeded', finished_at=%s WHERE user_id=%s", (repo.now_utc(), user["id"]))
    conn.commit()
    server._RUN_TOTALS.clear()
    first = server.list_runs(server.Ctx(conn, user, (), {}, {}, None))
    assert first["own_total"] == len(mine)  # the seeded example left out, as in the session numbers
    assert [r["id"] for r in first["runs"]] == mine[::-1][:repo.RUNS_LISTED]
    assert first["runs"][-1]["seq"] == len(mine) - repo.RUNS_LISTED + 1
    older = server.list_runs(server.Ctx(conn, user, (), {"before": str(first["runs"][-1]["id"])}, {}, None))
    assert older["more"] is False
    rest = [r for r in older["runs"] if not r["example"]]
    assert [r["id"] for r in rest] == mine[::-1][repo.RUNS_LISTED:]
    assert [r["seq"] for r in rest] == list(range(7, 0, -1))
    assert sum(1 for r in older["runs"] if r["example"]) == 1  # the seeded example, on the last page
    conn.commit()


def test_a_session_at_work_leads_the_first_page_however_many_came_after_it(conn):
    """A run-until-stopped session while the autopilot's short sessions pile up after it: the newest RUNS_LISTED had
    passed it, so it was in no list while the head said "1 agent researching now" (walked 2026-10-31). The first page
    carries it, unnumbered, ahead of the newest; its progress moves the list's version; the page's numbers and its
    "Show older" cursor are those of the newest RUNS_LISTED, and the older page still holds it in its place."""
    from app import repository as repo
    from app import server

    cur = conn.cursor()
    user = _user(cur)
    uid = user["id"]
    at_work = repo.create_run(cur, uid, "research", "btc15m", "momentum", run_forever=True)
    cur.execute("UPDATE app_agent_runs SET status='running', started_at=%s, heartbeat_at=%s WHERE id=%s",
                (repo.now_utc(), repo.now_utc(), at_work))
    after = [repo.create_run(cur, uid, "research", "eth15m", "momentum", brief=True) for _ in range(repo.RUNS_LISTED + 3)]
    cur.execute("UPDATE app_agent_runs SET status='succeeded', finished_at=%s WHERE id IN (" + ",".join(["%s"] * len(after)) + ")",
                (repo.now_utc(), *after))
    conn.commit()
    server._RUN_TOTALS.clear()
    first = server.list_runs(server.Ctx(conn, user, (), {}, {}, None))
    ids = [r["id"] for r in first["runs"]]
    assert ids == [at_work] + after[::-1][:repo.RUNS_LISTED]
    assert first["runs"][0]["status"] == "running" and "seq" not in first["runs"][0]
    assert first["counts"]["research_running"] == 1
    total = len(after) + 1
    assert first["own_total"] == total
    assert [r["seq"] for r in first["runs"][1:]] == list(range(total, total - repo.RUNS_LISTED, -1))
    # Its progress moves the version, though the newest RUNS_LISTED don't hold it.
    v = first["v"]
    assert server.list_runs(server.Ctx(conn, user, (), {"since": v}, {}, None)) == {"v": v, "same": True}
    repo.update_run_progress(cur, at_work, 9, 0)
    conn.commit()
    server._RUN_TOTALS.clear()
    moved = server.list_runs(server.Ctx(conn, user, (), {"since": v}, {}, None))
    assert not moved.get("same") and moved["runs"][0]["hypotheses_tried"] == 9
    # Show older pages from the oldest of the newest, and holds it in its place, numbered.
    older = server.list_runs(server.Ctx(conn, user, (), {"before": str(ids[-1])}, {}, None))
    own = [r for r in older["runs"] if not r["example"]]
    assert [r["id"] for r in own] == after[::-1][repo.RUNS_LISTED:] + [at_work]
    assert own[-1]["seq"] == 1
    # Callers that want the newest N only (the agent, the worker) get them alone.
    assert [r["id"] for r in repo.list_runs(cur, uid, limit=5)] == after[::-1][:5]
    conn.commit()
