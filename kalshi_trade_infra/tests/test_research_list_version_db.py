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
