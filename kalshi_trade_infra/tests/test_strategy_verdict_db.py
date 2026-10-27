"""A strategy's page against a real MySQL: a validation pass the diversification check held back after
its one-time holdout reads "Too similar to <the strategy it repeats>" from its run's own verdict event,
and a true pass reads nothing missed. Written through the repository layer only (no engine, no order).
Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import json
import os
import uuid

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


def test_a_held_back_pass_names_the_strategy_it_repeats_from_its_runs_event(conn):
    from app import repository as repo
    from app import server
    from app.research import research_repository as rr
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "held@example.invalid", "H", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 1}})
    run = repo.create_run(cur, uid, "research", "btc15m", "custom", "idea")
    curve = [[1761000000 + 3600 * i, 0.05 if i % 3 else -0.04] for i in range(40)]

    def strategy(title, rows):
        sid = repo.insert_strategy(cur, uid, run, None, "btc15m", "custom", title, "t", spec, "passed",
                                   {"classification": "statistically_supported"})
        eid = rr.preregister(cur, {"user_id": uid, "run_id": run, "strategy_id": sid, "market": "btc15m",
                                   "hypothesis_hash": uuid.uuid4().hex, "spec": spec, "economic_rationale": "{}",
                                   "primary_metric": "m", "null_hypothesis": "", "alt_hypothesis": "", "planned_test": "t",
                                   "falsification_criteria": "", "min_sample": 30, "cost_assumptions": {},
                                   "research_partition_id": 0, "planned_n_tests": 2, "correction_method": "BH"})
        for phase, cls in rows:
            rr.append_result(cur, eid, phase, cls, 40, metrics={"p_value": 0.01, "mean_net_return": 0.02, "ci_lo": 0.002,
                                                                 "ci_hi": 0.04, "holdout_consumed": phase == "holdout"},
                             equity_curve=curve)
        cur.execute("UPDATE app_strategies SET experiment_id=%s WHERE id=%s", (eid, sid))
        return sid, eid

    passed = [("validation", "statistically_supported"), ("holdout", "forward_validated")]
    peer, peer_eid = strategy("Late fade", passed + [("forward", "deployment_candidate")])
    held, _ = strategy("Late fade, tighter", passed)
    reason = "max |corr| 0.93 to deployed experiment %d exceeds 0.80" % peer_eid
    repo.add_event(cur, run, "verdict", "Late fade: diversification gate PASSED, promoted to DEPLOYMENT_CANDIDATE — max |corr| 0.00 within 0.80.",
                   {"title": "Late fade", "phase": "forward", "marginal_ok": True, "reason": "max |corr| 0.00 within 0.80"})
    repo.add_event(cur, run, "verdict", "Late fade, tighter: diversification gate blocked (stays forward-validated, not deployable) — %s." % reason,
                   {"title": "Late fade, tighter", "phase": "forward", "marginal_ok": False, "reason": reason})
    assert repo.forward_verdict(cur, run, "Late fade, tighter")["reason"] == reason
    assert repo.forward_verdict(cur, run, "Never logged") is None

    user = repo.get_user(cur, uid)

    def page(sid):
        return server.get_strategy(server.Ctx(conn, user, (str(sid),), {}, {}, None))

    out = page(held)
    assert out["experiment"]["promoted"] is False
    assert [(ln["gate"], ln["label"]) for ln in out["why_failed"]] == [("diversification", "Too similar to “Late fade”")]
    # The peer goes by its title, never its experiment id (the reason's "deployed experiment N").
    assert out["why_failed"][0]["measured"] == "a 0.93 correlation of daily results with “Late fade”"
    assert "experiment" not in json.dumps(out["why_failed"])
    true_pass = page(peer)
    assert true_pass["experiment"]["promoted"] is True and true_pass["why_failed"] == []
