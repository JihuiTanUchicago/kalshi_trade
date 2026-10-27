"""A running research session's "N tested so far, M passed" lines against a real MySQL: each counts apart the
passes a later check left uncleared by the time it was written (Missed final test, Held back), as the session's
done line, its Passed figure and the research list's rows do. The agent's stored count holds them, so a session
read "9 tested so far, 3 passed" over a page saying Passed 1. The page judges them with the verdict read it
already makes (one read of the experiments' later rows), never a read per line or per strategy.
Written through the repository layer only (no engine, no order). Opt in as for test_app_engine_db.py
(APP_TEST_MYSQL=1).
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


class _Counting:
    """A cursor that counts the reads of the experiments' later rows (research_repository.later_results)."""

    def __init__(self, cur):
        self.cur, self.later, self.sqls = cur, 0, []

    def execute(self, sql, args=None):
        self.later += "LEFT JOIN app_experiment_results" in sql
        self.sqls.append(" ".join(str(sql).split()))
        return self.cur.execute(sql, args)

    def __getattr__(self, name):
        return getattr(self.cur, name)


def test_a_running_sessions_progress_lines_count_the_uncleared_passes_apart(conn, monkeypatch):
    from app import repository as repo
    from app import server
    from app.research import research_repository as rr
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "progress@example.invalid", "P", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 1}})
    run = repo.create_run(cur, uid, "research", "btc15m", "custom", "idea", run_forever=True)
    start = repo.now_utc().replace(microsecond=0) - timedelta(hours=1)
    cur.execute("UPDATE app_agent_runs SET status='running', started_at=%s, heartbeat_at=%s WHERE id=%s",
                (start, repo.now_utc(), run))
    curve = [[1761000000 + 3600 * i, 0.05 if i % 3 else -0.04] for i in range(40)]
    ok = {"p_value": 0.01, "mean_net_return": 0.02, "ci_lo": 0.002, "ci_hi": 0.04}
    luck = {"p_value": 0.48, "mean_net_return": -0.003, "ci_lo": -0.03, "ci_hi": 0.025}

    def strategy(title, minute, rows):
        sid = repo.insert_strategy(cur, uid, run, None, "btc15m", "custom", title, "t", spec, "passed",
                                   {"classification": "statistically_supported"})
        eid = rr.preregister(cur, {"user_id": uid, "run_id": run, "strategy_id": sid, "market": "btc15m",
                                   "hypothesis_hash": uuid.uuid4().hex, "spec": spec, "economic_rationale": "{}",
                                   "primary_metric": "m", "null_hypothesis": "", "alt_hypothesis": "", "planned_test": "t",
                                   "falsification_criteria": "", "min_sample": 30, "cost_assumptions": {},
                                   "research_partition_id": 0, "planned_n_tests": 2, "correction_method": "BH"})
        for phase, cls, m in rows:
            rr.append_result(cur, eid, phase, cls, 40, metrics=dict(m, holdout_consumed=phase == "holdout"), equity_curve=curve)
        cur.execute("UPDATE app_strategies SET experiment_id=%s, created_at=%s WHERE id=%s",
                    (eid, start + timedelta(minutes=minute), sid))
        return sid, eid

    def still(tested, passed, minute):
        repo.add_event(cur, run, "step", "Still running - %d tested so far, %d passed. Exploring more (stop anytime)."
                       % (tested, passed), None)
        cur.execute("UPDATE app_agent_events SET created_at=%s WHERE id=(SELECT m FROM (SELECT MAX(id) m FROM "
                    "app_agent_events WHERE run_id=%s) x)", (start + timedelta(minutes=minute), run))

    val = ("validation", "statistically_supported", ok)
    _, peer_eid = strategy("Late fade", 5, [val, ("holdout", "forward_validated", ok), ("forward", "deployment_candidate", {})])
    still(3, 1, 10)
    strategy("Early fade", 15, [val, ("holdout", "inconclusive", luck)])  # Missed final test
    still(6, 2, 20)
    held, _ = strategy("Late fade, tighter", 25, [val, ("holdout", "forward_validated", ok)])  # Held back
    reason = "max |corr| 0.93 to deployed experiment %d exceeds 0.80" % peer_eid
    repo.add_event(cur, run, "verdict", "Late fade, tighter: diversification gate blocked (stays forward-validated, not "
                                        "deployable) — %s." % reason,
                   {"title": "Late fade, tighter", "phase": "forward", "marginal_ok": False, "reason": reason})
    cur.execute("UPDATE app_agent_events SET created_at=%s WHERE id=(SELECT m FROM (SELECT MAX(id) m FROM "
                "app_agent_events WHERE run_id=%s) x)", (start + timedelta(minutes=26), run))
    still(9, 3, 30)
    repo.update_run_progress(cur, run, 9, 3)

    user = repo.get_user(cur, uid)
    counting = _Counting(cur)
    monkeypatch.setattr(conn, "cursor", lambda *a, **k: counting)
    page = server.get_run(server.Ctx(conn, user, (str(run),), {}, {}, None))
    assert counting.later == 1  # the session's verdicts in the one read the page already made
    notes = [(e.get("data") or {}).get("note") for e in page["events"] if e["message"].startswith("Still running")]
    assert notes == [
        "3 tested so far, 1 passed. Looking for more; you can stop it anytime.",
        "6 tested so far, 1 cleared every check; 1 more passed its first test, then wasn't cleared to trade. "
        "Looking for more; you can stop it anytime.",
        "9 tested so far, 1 cleared every check; 2 more passed their first test, then weren't cleared to trade. "
        "Looking for more; you can stop it anytime."]
    # The stored lines are unchanged, and the page's own stamps agree with the last line.
    assert all(e["message"].startswith("Still running - ") for e in page["events"] if e["kind"] == "step")
    stamps = sorted(s.get("verdict") or "" for s in page["strategies"])
    assert stamps == ["", "held_back", "missed_final"]
    assert next(s for s in page["strategies"] if s["id"] == held)["verdict"] == "held_back"
    # The research list's row for the session says the same: 3 stored passes, 2 not cleared.
    from app.web.routes import research
    research._RUN_TOTALS.clear()
    rows = server.list_runs(server.Ctx(conn, user, (), {}, {}, None))["runs"]
    row = next(r for r in rows if r["id"] == run)
    assert (row["strategies_passed"], row.get("not_cleared")) == (3, 2)
    # A poll after the last line reads only the new events, and still counts the uncleared passes apart.
    last = max(e["id"] for e in page["events"])
    still(12, 3, 40)
    counting.later = 0
    more = server.get_run(server.Ctx(conn, user, (str(run),), {"after": str(last)}, {}, None))["events"]
    assert [e["data"]["note"] for e in more] == [
        "12 tested so far, 1 cleared every check; 2 more passed their first test, then weren't cleared to trade. "
        "Looking for more; you can stop it anytime."]
    assert counting.later == 1
