"""The research sessions the autopilot started, against a real MySQL: the reads that say whose a session is.

An autopilot research session is a brief run (agent.act's `research` action, the research floor, the
data-gap re-test), the same rows Billing lists as "Autopilot research". The research list and run
page carry `by_autopilot` so a new user can tell those sessions from their own, and the dashboard's
"since your last visit" strip counts them under the autopilot (it writes no proposal, so the strip
read "It made no changes" while it researched). Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
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


def _user(cur):
    from app import repository as repo

    return repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "t@example.com", "T", None)


def test_the_list_and_the_run_page_say_which_sessions_the_autopilot_started(conn):
    from app import repository as repo
    from app import server

    cur = conn.cursor()
    user, other = _user(cur), _user(cur)
    uid = user["id"]
    mine = repo.create_run(cur, uid, "research", "btc15m", "momentum", "my idea")
    ap = repo.create_run(cur, uid, "research", "btc15m", None, "an angle", brief=True)
    example = repo.create_run(cur, uid, "research", "btc15m", repo.DEMO_DIRECTION, "random walk")
    theirs = repo.create_run(cur, other["id"], "research", "btc15m", None, "their angle", brief=True)
    conn.commit()

    rows = repo.list_runs(cur, uid)  # the account's own seeded example is in there too
    got = {r["id"]: int(r["by_autopilot"]) for r in rows}
    assert got[mine] == 0 and got[ap] == 1 and theirs not in got and example in got
    assert all(int(r["by_autopilot"]) == 0 for r in rows if r["direction"] == repo.DEMO_DIRECTION)
    assert int(repo.get_run(cur, uid, ap)["by_autopilot"]) == 1 and int(repo.get_run(cur, uid, mine)["by_autopilot"]) == 0
    assert repo.get_run(cur, uid, theirs) is None

    ctx = server.Ctx(conn, user, (), {}, {}, None)
    listed = {r["id"]: r for r in server.list_runs(ctx)["runs"]}
    assert int(listed[ap]["by_autopilot"]) == 1 and int(listed[mine]["by_autopilot"]) == 0
    assert listed[example]["example"] is True
    page = server.get_run(server.Ctx(conn, user, (str(ap),), {}, {}, None))["run"]
    assert int(page["by_autopilot"]) == 1


def test_the_since_strip_counts_the_research_the_autopilot_started(conn):
    from app import repository as repo

    cur = conn.cursor()
    user = _user(cur)
    uid = user["id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(hours=2)
    repo.create_run(cur, uid, "research", "btc15m", None, "an angle", brief=True)
    repo.create_run(cur, uid, "research", "btc_daily", None, "another angle", brief=True)
    old = repo.create_run(cur, uid, "research", "btc15m", None, "before the visit", brief=True)
    cur.execute("UPDATE app_agent_runs SET created_at=%s WHERE id=%s", (since - timedelta(minutes=5), old))
    repo.create_run(cur, uid, "research", "btc15m", "momentum", "my idea")  # the user's own
    repo.create_run(cur, uid, "research", "btc15m", repo.DEMO_DIRECTION, "random walk")  # the example
    repo.create_run(cur, uid, "review", None, None, "scheduled autopilot review", brief=True)  # not research
    repo.create_proposal(cur, uid, "deploy", "auto", None, None, "applied")
    conn.commit()

    act = repo.activity_since(cur, uid, since)
    assert act["autopilot"] == {"deploy": 1, "research": 2}
    assert sum(act["runs"].values()) == 3  # every research session started since, the example left out
    quiet = _user(cur)
    repo.create_run(cur, quiet["id"], "research", "btc15m", "momentum", "my idea")
    conn.commit()
    assert repo.activity_since(cur, quiet["id"], since)["autopilot"] == {}  # no zero row for "research"


def test_the_since_strip_counts_a_silent_session_apart_from_the_running_ones(conn):
    """The strip said "1 running" for a session the Research page listed as "Silent 5 min" under "Running 0" (walk
    2026-10-31). With `silent_before`, a running session whose last beat (or start) is older is counted as `silent`,
    by the line active_run_counts draws; without it the read is as before."""
    from app import repository as repo

    cur = conn.cursor()
    uid = _user(cur)["id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since, cut = now - timedelta(hours=2), now - timedelta(minutes=4)
    quiet = repo.create_run(cur, uid, "research", "btc15m", "momentum", "went quiet")
    beating = repo.create_run(cur, uid, "research", "btc15m", "momentum", "still beating")
    never = repo.create_run(cur, uid, "research", "btc15m", "momentum", "no beat yet, started long ago")
    repo.create_run(cur, uid, "research", "btc15m", "momentum", "waiting for a worker")  # queued
    cur.execute("UPDATE app_agent_runs SET status='running', started_at=%s, heartbeat_at=%s WHERE id=%s",
                (now - timedelta(minutes=30), now - timedelta(minutes=5), quiet))
    cur.execute("UPDATE app_agent_runs SET status='running', started_at=%s, heartbeat_at=%s WHERE id=%s",
                (now - timedelta(minutes=30), now - timedelta(seconds=20), beating))
    cur.execute("UPDATE app_agent_runs SET status='running', started_at=%s, heartbeat_at=NULL WHERE id=%s",
                (now - timedelta(minutes=10), never))
    conn.commit()

    assert repo.activity_since(cur, uid, since, silent_before=cut)["runs"] == {"running": 1, "silent": 2, "queued": 1}
    assert repo.activity_since(cur, uid, since)["runs"] == {"running": 3, "queued": 1}
    # The same line as the dashboard's counts: the silent ones are left out of research_running there.
    assert repo.active_run_counts(cur, uid, silent_before=cut)["research_running"] == 1
