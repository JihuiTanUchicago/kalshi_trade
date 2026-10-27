"""The Strategies list against a real MySQL stamps the same verdict as each strategy's own page: "Missed
final test" for a validation pass whose one-time holdout failed, "Held back" for one the diversification
check then held back (a holdout pass, a pass stored before app_strategies.experiment_id, or a probation
strategy that passed on paper), nothing for a true pass or a plain miss. The list judges all of them with
one read of their experiments' later rows (plus one for a strategy stored without its experiment id),
whatever the page size. The research session page names the strategy a held-back pass repeats, by title.
Written through the repository layer only (no engine, no order). Opt in as for test_app_engine_db.py
(APP_TEST_MYSQL=1).
"""
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


class _Counting:
    """A cursor that counts the statements that read app_experiment_results."""

    def __init__(self, cur):
        self.cur, self.later = cur, 0

    def execute(self, sql, args=None):
        self.later += "app_experiment_results" in sql
        return self.cur.execute(sql, args)

    def __getattr__(self, name):
        return getattr(self.cur, name)


def test_the_list_stamps_what_each_page_says_in_one_read(conn, monkeypatch):
    from app import repository as repo
    from app import server
    from app.research import research_repository as rr
    from app.web.routes import research
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "verdicts@example.invalid", "V", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 1}})
    run = repo.create_run(cur, uid, "research", "btc15m", "custom", "idea")
    curve = [[1761000000 + 3600 * i, 0.05 if i % 3 else -0.04] for i in range(40)]
    ok = {"p_value": 0.01, "mean_net_return": 0.02, "ci_lo": 0.002, "ci_hi": 0.04}
    luck = {"p_value": 0.48, "mean_net_return": -0.003, "ci_lo": -0.03, "ci_hi": 0.025}

    def strategy(title, status, rows, link=True, min_sample=30):
        sid = repo.insert_strategy(cur, uid, run, None, "btc15m", "custom", title, "t", spec, status,
                                   {"classification": "statistically_supported"})
        eid = rr.preregister(cur, {"user_id": uid, "run_id": run, "strategy_id": sid, "market": "btc15m",
                                   "hypothesis_hash": uuid.uuid4().hex, "spec": spec, "economic_rationale": "{}",
                                   "primary_metric": "m", "null_hypothesis": "", "alt_hypothesis": "", "planned_test": "t",
                                   "falsification_criteria": "", "min_sample": min_sample, "cost_assumptions": {},
                                   "research_partition_id": 0, "planned_n_tests": 2, "correction_method": "BH"})
        for phase, cls, m in rows:
            rr.append_result(cur, eid, phase, cls, 40, metrics=dict(m, holdout_consumed=phase == "holdout"), equity_curve=curve)
        if link:
            cur.execute("UPDATE app_strategies SET experiment_id=%s WHERE id=%s", (eid, sid))
        return sid, eid

    val = ("validation", "statistically_supported", ok)
    sid = {}
    sid["true pass"], peer_eid = strategy("Late fade", "passed", [val, ("holdout", "forward_validated", ok),
                                                                   ("forward", "deployment_candidate", {})])
    sid["missed"], _ = strategy("Early fade", "passed", [val, ("holdout", "inconclusive", luck)])
    sid["held"], _ = strategy("Late fade, tighter", "passed", [val, ("holdout", "forward_validated", ok)])
    sid["legacy held"], _ = strategy("Old late fade", "passed", [val, ("holdout", "forward_validated", ok)], link=False)
    sid["awaiting holdout"], _ = strategy("Mid fade", "passed", [val])
    near = ("validation", "inconclusive", {"net_pnl": 4.1})
    sid["paper held"], _ = strategy("Rain no", "failed", [near, ("paper", "forward_validated", ok)], min_sample=40)
    sid["paper missed"], _ = strategy("Rain yes", "failed", [near, ("paper", "rejected", luck)], min_sample=40)
    sid["void"], _ = strategy("Noise", "failed", [("validation", "rejected", luck)])
    reason = "max |corr| 0.93 to deployed experiment %d exceeds 0.80" % peer_eid
    repo.add_event(cur, run, "verdict", "Late fade, tighter: diversification gate blocked (stays forward-validated, not deployable) — %s." % reason,
                   {"title": "Late fade, tighter", "phase": "forward", "marginal_ok": False, "reason": reason})
    repo.add_chat(cur, uid, "system", "Paper forward gate: Rain no passed on paper (40 paper trades, p=0.010, +2.0%% per "
                                      "trade) but stays off the candidate list: %s." % reason)

    user = repo.get_user(cur, uid)
    counting = _Counting(cur)
    monkeypatch.setattr(conn, "cursor", lambda *a, **k: counting)
    by_id = {}
    for status in ("", "failed"):  # the default (Kept) view leaves Void out; its chip lists them
        counting.later = 0
        listed = server.list_strategies(server.Ctx(conn, user, (), {"status": status, "page": "0"}, {}, None))
        by_id.update({c["id"]: c.get("verdict") for c in listed["strategies"]})
        assert counting.later == 1  # every listed strategy's later rows in one read
    assert {k: by_id[v] for k, v in sid.items()} == {
        "true pass": None, "missed": "missed_final", "held": "held_back", "legacy held": "held_back",
        "awaiting holdout": None, "paper held": "held_back", "paper missed": None, "void": None}
    # Each page says the same, and a held-back one names what held it back, never an experiment id.
    for name, s in sid.items():
        page = server.get_strategy(server.Ctx(conn, user, (str(s),), {}, {}, None))
        assert page.get("verdict") == by_id[s], name
    page = server.get_strategy(server.Ctx(conn, user, (str(sid["paper held"]),), {}, {}, None))
    assert [(ln["gate"], ln["label"]) for ln in page["why_failed"]] == [("diversification", "Too similar to “Late fade”")]
    assert page["why_failed"][0]["measured"] == "a 0.93 correlation of daily results with “Late fade”"

    # The session page: the held-back pass says so by name; the missed one lists its holdout checks.
    later = research._later_missed(counting, uid, repo.list_strategies(cur, uid, run_id=run))
    assert later[sid["held"]]["verdict"] == "held_back"
    assert later[sid["held"]]["later_missed"][0]["label"] == "Too similar to “Late fade”"
    assert later[sid["missed"]]["verdict"] == "missed_final"
    assert later[sid["missed"]]["later_missed"][0]["label"] == "The edge could be luck on the locked holdout"
    assert sid["true pass"] not in later and str(peer_eid) not in str(later)
