"""The research list's stop_reason against a real MySQL: the out-of-credits probe inside repo.list_runs.

A run-until-stopped session that ran out of credits ends `succeeded` with the agent's out-of-credits
step in its log (agent.run_research). The list reads that step inside its one runs read, only for
finished run-until-stopped sessions, and only from that run's own log. Opt in as for
test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

OUT = "Paused — out of credits. Add more (or turn on auto-reload) and start a new session to keep researching."


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


def _run(cur, uid, status, forever, events=(), error=None):
    from app import repository as repo

    rid = repo.create_run(cur, uid, "research", "btc15m", "momentum", run_forever=forever)
    for kind, message in events:
        repo.add_event(cur, rid, kind, message)
    cur.execute("UPDATE app_agent_runs SET status=%s, error=%s WHERE id=%s", (status, error, rid))
    return rid


def test_the_list_says_which_finished_sessions_ran_out_of_credits(conn):
    from app import repository as repo
    from app import server

    cur = conn.cursor()
    user, other = _user(cur), _user(cur)
    uid = user["id"]
    many = [("step", "Still running - %d tested so far, 0 passed. Exploring more (stop anytime)." % i) for i in range(30)]
    credits = _run(cur, uid, "succeeded", True, many + [("step", OUT), ("done", "0 of 30 hypotheses passed every gate.")])
    ideas = _run(cur, uid, "succeeded", True, many + [("done", "0 of 30 hypotheses passed every gate.")])
    # The same words in a set-size session's log, or a session still running, are not a credits stop.
    bounded = _run(cur, uid, "succeeded", False, [("step", OUT)])
    running = _run(cur, uid, "running", True, [("step", OUT)])
    # Another kind of event with those words (a thought quoting it) is not the agent's step.
    quoted = _run(cur, uid, "succeeded", True, [("thinking", OUT)])
    cancelled = _run(cur, uid, "cancelled", True)
    failed = _run(cur, uid, "failed", False, [("error", "The session hit an unexpected error and stopped.")],
                  error="The session hit an unexpected error and stopped.")
    # Another user's credits stop never marks this user's runs.
    theirs = _run(cur, other["id"], "succeeded", True, [("step", OUT)])
    conn.commit()

    got = {r["id"]: int(r["out_of_credits"]) for r in repo.list_runs(cur, uid)}
    assert got[credits] == 1 and got[ideas] == got[bounded] == got[running] == got[quoted] == 0
    assert theirs not in got

    ctx = server.Ctx(conn, user, (), {}, {}, None)
    runs = {r["id"]: r for r in server.list_runs(ctx)["runs"]}
    assert {i: runs[i]["stop_reason"] for i in (credits, ideas, bounded, running, quoted, cancelled, failed)} == {
        credits: "credits", ideas: "complete", bounded: "limit", running: None, quoted: "complete",
        cancelled: "user", failed: "error"}
    assert all("out_of_credits" not in r for r in runs.values())
    theirs_out = {r["id"]: r["stop_reason"] for r in server.list_runs(server.Ctx(conn, other, (), {}, {}, None))["runs"]}
    assert theirs_out[theirs] == "credits"

    # The probe reads that run's own log through an index, never a scan of every event.
    cur.execute("EXPLAIN SELECT 1 FROM app_agent_events e WHERE e.run_id=%s AND e.kind='step' AND e.message LIKE %s",
                (credits, repo.OUT_OF_CREDITS_STEP + "%"))
    plan = cur.fetchall()
    assert all(p.get("key") for p in plan), plan
