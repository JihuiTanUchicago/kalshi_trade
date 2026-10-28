"""The Strategies list against a real MySQL stamps the same verdict as each strategy's own page: "Missed
final test" for a validation pass whose one-time holdout failed, "Held back" for one the diversification
check then held back (a holdout pass, a pass stored before app_strategies.experiment_id, or a probation
strategy that passed on paper), nothing for a true pass or a plain miss. The list judges all of them with
one read of their experiments' later rows (plus one for a strategy stored without its experiment id),
whatever the page size. The research session page names the strategy a held-back pass repeats, by title.
The headlines agree with them: the Research page's all-time "Passed every gate" and the autopilot panel's
week count only cleared passes and say the rest as not cleared, each judged in one batched read.
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
    """A cursor that counts the reads of the experiments' later rows (research_repository.later_results).
    The passes' own read only probes a void or rejected strategy's paper row, through idx_res_exp."""

    def __init__(self, cur):
        self.cur, self.later, self.sqls = cur, 0, []

    def execute(self, sql, args=None):
        self.later += "LEFT JOIN app_experiment_results" in sql
        self.sqls.append(" ".join(str(sql).split()))
        return self.cur.execute(sql, args)

    def reads(self, part):
        return sum(part in s for s in self.sqls)

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
    by_id, shown = {}, {}
    # The default (Kept) view leaves Void out; its chip lists them. Passed and Not cleared list by verdict.
    for status in ("", "failed", "passed", "not_cleared"):
        counting.later = 0
        listed = server.list_strategies(server.Ctx(conn, user, (), {"status": status, "page": "0"}, {}, None))
        by_id.update({c["id"]: c.get("verdict") for c in listed["strategies"]})
        shown[status] = ({c["id"] for c in listed["strategies"]}, listed["matched"])
        assert counting.later == 1  # every pass's and every listed strategy's later rows in one read
    # The chips count what the rows stamp, across every page: 5 stored passes, 2 cleared, 3 not; and of 3
    # stored void, the probation strategy held back after passing on paper is not cleared either (it is
    # stamped Held back, so it counted under Void beside rows that never passed anything). Void 3 -> 2,
    # Not cleared 3 -> 4, and the Kept view lists it (5 -> 6). The total is unchanged.
    assert {k: listed["counts"].get(k) for k in ("passed", "not_cleared", "failed", "total")} == {
        "passed": 2, "not_cleared": 4, "failed": 2, "total": 8}
    assert shown["passed"] == ({sid["true pass"], sid["awaiting holdout"]}, 2)
    assert shown["not_cleared"] == ({sid["missed"], sid["held"], sid["legacy held"], sid["paper held"]}, 4)
    assert shown["failed"] == ({sid["paper missed"], sid["void"]}, 2)
    assert shown[""][1] == 6 and sid["paper held"] in shown[""][0]
    assert {k: by_id[v] for k, v in sid.items()} == {
        "true pass": None, "missed": "missed_final", "held": "held_back", "legacy held": "held_back",
        "awaiting holdout": None, "paper held": "held_back", "paper missed": None, "void": None}
    # The research list's row for the session: its counter holds the 5 stored passes, and the row takes off the
    # 3 its page says weren't cleared (Passed 2, 3 not cleared), in one read of the later rows for the list.
    repo.set_run_counts(cur, run, 8, 5)
    counting.later = 0
    runs = server.list_runs(server.Ctx(conn, user, (), {}, {}, None))["runs"]
    assert {r["id"]: r.get("not_cleared") for r in runs if not r.get("example")} == {run: 3}
    assert counting.later == 1

    # The headlines count what the rows and the Strategies chips count. The Research page's "kept N that beat
    # every gate" (all time) and the autopilot panel's "N passed" this week read 5 stored passes; 2 were
    # cleared, and 3 are said apart as not cleared. Cold, the Research headline judges every research pass in
    # one read of the passes and one of their later rows (plus the legacy fallback for the pass stored without
    # its experiment id), and the session rows reuse that judgment: no second later-rows read.
    research._RUN_TOTALS.clear()
    counting.later, counting.sqls = 0, []
    listed = server.list_runs(server.Ctx(conn, user, (), {}, {}, None))
    assert {k: listed["totals"][k] for k in ("tried", "passed", "not_cleared")} == {"tried": 8, "passed": 2, "not_cleared": 3}
    row = next(r for r in listed["runs"] if r["id"] == run)
    assert row["strategies_passed"] - row["not_cleared"] == listed["totals"]["passed"]
    assert counting.later == 1 and counting.reads("s.run_id FROM app_strategies s WHERE") == 1
    assert counting.reads("SELECT strategy_id, MAX(id) AS id FROM app_experiments") == 1  # the legacy pass's experiment
    assert not counting.reads("SELECT COUNT(*) AS n FROM app_strategies")
    # Warm (inside the 30s cache), the headline reads nothing; the rows read their own sessions' passes.
    counting.later, counting.sqls = 0, []
    again = server.list_runs(server.Ctx(conn, user, (), {}, {}, None))
    assert again["totals"] == listed["totals"] and counting.later == 1
    assert counting.reads("s.run_id FROM app_strategies s WHERE") == 1
    counting.later, counting.sqls = 0, []
    assert server.list_runs(server.Ctx(conn, user, (), {"since": again["v"]}, {}, None)) == {"v": again["v"], "same": True}
    assert counting.later == 0 and len(counting.sqls) == 2  # an unchanged poll: the counts and the version
    # The Strategies list's Passed chip agrees with the headline (every pass here is from this session).
    assert listed["totals"]["passed"] == server.list_strategies(
        server.Ctx(conn, user, (), {"status": "", "page": "0"}, {}, None))["counts"]["passed"]
    # The passes read scans neither table: the user's passes by idx_strat_user (or idx_strat_run), their
    # sessions by key (on a table this small the planner may pick idx_runs_user over PRIMARY).
    from datetime import timedelta
    since = repo.now_utc() - timedelta(days=7)
    cur.execute("EXPLAIN SELECT s.id FROM app_strategies s WHERE s.user_id=%s AND s.status='passed' AND EXISTS "
                "(SELECT 1 FROM app_agent_runs r WHERE r.id=s.run_id AND r.kind='research' AND r.created_at>=%s)", (uid, since))
    plan = cur.fetchall()
    assert plan and all(r["type"] != "ALL" and r.get("key") for r in plan), plan

    # The autopilot panel's week: the same 5 stored passes, 2 passed and 3 not cleared, in its research line,
    # its last 7 days and its story. Judged only on a poll that finds a pass, then kept while the count holds.
    from app.web.routes import chat as chat_routes
    chat_routes._WEEK_PASSES.clear()
    counting.later, counting.sqls = 0, []
    status = server.autopilot_status(server.Ctx(conn, user, (), {}, {}, None))
    assert (status["research"]["passed_7d"], status["research"]["not_cleared_7d"]) == (2, 3)
    assert counting.later == 1 and counting.reads("s.run_id FROM app_strategies s WHERE") == 1
    first = len(counting.sqls)
    counting.later, counting.sqls = 0, []
    status = server.autopilot_status(server.Ctx(conn, user, (), {}, {}, None))
    assert status["research"]["passed_7d"] == 2 and counting.later == 0
    assert not counting.reads("s.run_id FROM app_strategies s WHERE") and len(counting.sqls) <= first - 3
    cur.execute("UPDATE app_users SET autopilot=1 WHERE id=%s", (uid,))
    on = server.autopilot_status(server.Ctx(conn, repo.get_user(cur, uid), (), {}, {}, None))
    assert (on["week"]["passed"], on["week"]["not_cleared"]) == (2, 3)
    assert any("and 2 passed, and 3 more passed but weren’t cleared to trade." in ln for ln in on["story"]), on["story"]
    cur.execute("UPDATE app_users SET autopilot=0 WHERE id=%s", (uid,))
    # Each page says the same, and a held-back one names what held it back, never an experiment id.
    for name, s in sid.items():
        page = server.get_strategy(server.Ctx(conn, user, (str(s),), {}, {}, None))
        assert page.get("verdict") == by_id[s], name
    page = server.get_strategy(server.Ctx(conn, user, (str(sid["paper held"]),), {}, {}, None))
    assert [(ln["gate"], ln["label"]) for ln in page["why_failed"]] == [("diversification", "Too similar to “Late fade”")]
    assert page["why_failed"][0]["measured"] == "a 0.93 correlation of daily results with “Late fade”"

    # The session page: the held-back pass says so by name; the missed one lists its holdout checks.
    # The dashboard's "since your last visit": what passed, without the ones a later check left uncleared.
    from datetime import timedelta
    from app.web.routes import dashboard
    since = dashboard._passed_since(cur, uid, repo.now_utc() - timedelta(hours=1))
    assert since["n"] == 2 and {i["id"] for i in since["items"]} == {sid["true pass"], sid["awaiting holdout"]}
    assert since["not_cleared_n"] == 3
    assert {(i["id"], i["verdict"]) for i in since["not_cleared"]} == {
        (sid["missed"], "missed_final"), (sid["held"], "held_back"), (sid["legacy held"], "held_back")}
    assert all(set(i) == {"id", "title", "verdict"} for i in since["not_cleared"])

    later = research._later_missed(counting, uid, repo.list_strategies(cur, uid, run_id=run))
    assert later[sid["held"]]["verdict"] == "held_back"
    assert later[sid["held"]]["later_missed"][0]["label"] == "Too similar to “Late fade”"
    assert later[sid["missed"]]["verdict"] == "missed_final"
    assert later[sid["missed"]]["later_missed"][0]["label"] == "The edge could be luck on the locked holdout"
    # The peer's experiment id never rides along: no value is that id and no text names an experiment
    # (a substring check on the id alone matches digits inside a figure like "2.50%").
    def values(v):
        if isinstance(v, dict):
            for x in v.values():
                yield from values(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                yield from values(x)
        else:
            yield v
    assert sid["true pass"] not in later and peer_eid not in list(values(later))
    assert "experiment" not in str(later).lower()


def test_the_list_flags_a_pass_with_no_gatekeeper_record_as_its_page_does(conn, monkeypatch):
    """A pass from the old loose backtest gate has no gatekeeper record: its page reads "Not validated (record
    missing)" (experiment None) and calls its out_of_sample later-period. The list says which passes have none
    (no_gatekeeper_record) from the reads it already makes for every pass: the same answer as each page, and
    no statement it didn't send before."""
    from app import repository as repo
    from app import server
    from app.research import research_repository as rr
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "norecord@example.invalid", "N", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 1}})
    run = repo.create_run(cur, uid, "research", "btc15m", "custom", "idea")
    oos = {"in_sample": {"pnl": 2.0, "trades": 20}, "out_of_sample": {"pnl": 6.2, "trades": 40, "days": 30}}

    def strategy(title, status, link):
        sid = repo.insert_strategy(cur, uid, run, None, "btc15m", "custom", title, "t", spec, status, dict(oos))
        if link is None:
            return sid
        eid = rr.preregister(cur, {"user_id": uid, "run_id": run, "strategy_id": sid, "market": "btc15m",
                                   "hypothesis_hash": uuid.uuid4().hex, "spec": spec, "economic_rationale": "{}",
                                   "primary_metric": "m", "null_hypothesis": "", "alt_hypothesis": "", "planned_test": "t",
                                   "falsification_criteria": "", "min_sample": 30, "cost_assumptions": {},
                                   "research_partition_id": 0, "planned_n_tests": 2, "correction_method": "BH"})
        if link == "id":
            cur.execute("UPDATE app_strategies SET experiment_id=%s WHERE id=%s", (eid, sid))
        return sid

    sid = {"linked": strategy("Linked pass", "passed", "id"), "legacy": strategy("Legacy pass", "passed", "strategy"),
           "loose": strategy("Loose pass", "passed", None), "void": strategy("Loose void", "failed", None)}
    user = repo.get_user(cur, uid)
    counting = _Counting(cur)
    monkeypatch.setattr(conn, "cursor", lambda *a, **k: counting)
    listed = server.list_strategies(server.Ctx(conn, user, (), {"status": "", "page": "0"}, {}, None))
    sent = len(counting.sqls)
    flags = {c["id"]: c.get("no_gatekeeper_record", False) for c in listed["strategies"]}
    assert {k: flags.get(v) for k, v in sid.items() if v in flags} == {"linked": False, "legacy": False, "loose": True}
    for k in ("linked", "legacy", "loose"):  # each page: experiment None exactly when the list flags it
        page = server.get_strategy(server.Ctx(conn, user, (str(sid[k]),), {}, {}, None))
        assert (page.get("experiment") is None) == flags[sid[k]], k
    # The list's statements: the reads it made before (the later rows once, the legacy pass's experiment once).
    monkeypatch.setattr("app.web.routes.strategies._attach_no_record", lambda *a: None)
    counting.sqls = []
    server.list_strategies(server.Ctx(conn, user, (), {"status": "", "page": "0"}, {}, None))
    assert len(counting.sqls) == sent
    # The session page renders the same rows and gives the same answer, from its own later-check reads.
    monkeypatch.undo()
    monkeypatch.setattr(conn, "cursor", lambda *a, **k: counting)
    counting.sqls = []
    session = server.get_run(server.Ctx(conn, user, (str(run),), {}, {}, None))
    in_run = {c["id"]: c.get("no_gatekeeper_record", False) for c in session["strategies"]}
    # The loose void too, from the list read's own column (test_the_list_says_a_void_with_no_record_...).
    assert {k: in_run[v] for k, v in sid.items()} == {"linked": False, "legacy": False, "loose": True, "void": True}
    counting.sqls = []  # warm now (its first call fills the page's short caches), count a second call each way
    server.get_run(server.Ctx(conn, user, (str(run),), {}, {}, None))
    sent = len(counting.sqls)
    monkeypatch.setattr("app.web.routes.research._attach_no_record", lambda *a: None)
    counting.sqls = []
    server.get_run(server.Ctx(conn, user, (str(run),), {}, {}, None))
    assert len(counting.sqls) == sent


def test_the_list_says_a_void_with_no_record_is_not_held_out_and_the_summary_leaves_it_out(conn, monkeypatch):
    """The first version's simple backtest path stored strategies as "failed" with no gatekeeper record. Their rows
    said "unseen data" and counted under "Void on unseen data". The list's own read flags them (void_no_record, by
    the rule a pass is flagged by), each page says the same from its experiment read, and the counts' one
    statement says how many of the counted voids have none, the seeded example's left out. No new statement."""
    from app import repository as repo
    from app import server
    from app.adapters.db import strategy_repository as strat
    from app.research import research_repository as rr
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "voidflag@example.invalid", "V", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 1}})
    run = repo.create_run(cur, uid, "research", "btc15m", "custom", "idea")
    oos = {"in_sample": {"pnl": 2.0, "trades": 20}, "out_of_sample": {"pnl": -1.5, "trades": 40, "days": 30}}

    def strategy(title, status, link, direction="custom"):
        sid = repo.insert_strategy(cur, uid, run, None, "btc15m", direction, title, "t", spec, status, dict(oos))
        if link is None:
            return sid
        eid = rr.preregister(cur, {"user_id": uid, "run_id": run, "strategy_id": sid, "market": "btc15m",
                                   "hypothesis_hash": uuid.uuid4().hex, "spec": spec, "economic_rationale": "{}",
                                   "primary_metric": "m", "null_hypothesis": "", "alt_hypothesis": "", "planned_test": "t",
                                   "falsification_criteria": "", "min_sample": 30, "cost_assumptions": {},
                                   "research_partition_id": 0, "planned_n_tests": 2, "correction_method": "BH"})
        if link == "id":
            cur.execute("UPDATE app_strategies SET experiment_id=%s WHERE id=%s", (eid, sid))
        return sid

    sid = {"gated": strategy("Gatekeeper void", "failed", "id"), "legacy": strategy("Legacy void", "failed", "strategy"),
           "loose": strategy("Loose void", "failed", None), "loose2": strategy("Loose void 2", "failed", None),
           "pass": strategy("Loose pass", "passed", None),
           "example": strategy("Example void", "failed", None, direction=repo.DEMO_DIRECTION)}
    # The counts: every void (the Void chip), and those with no record apart, the seeded example's in neither.
    counts = repo.count_strategies(cur, uid)
    assert (counts["failed"], counts["failed_no_record"], counts["passed"]) == (4, 2, 1)
    assert counts["examples"]["failed"] == 1
    user = repo.get_user(cur, uid)
    counting = _Counting(cur)
    monkeypatch.setattr(conn, "cursor", lambda *a, **k: counting)
    ask = lambda: server.list_strategies(server.Ctx(conn, user, (), {"status": "failed", "page": "0"}, {}, None))
    listed = ask()
    sent = len(counting.sqls)
    assert listed["counts"]["failed"] == 4 and listed["counts"]["failed_no_record"] == 2
    flags = {c["id"]: c.get("no_gatekeeper_record", False) for c in listed["strategies"]}
    want = {"gated": False, "legacy": False, "loose": True, "loose2": True, "example": True}
    assert {k: flags[sid[k]] for k in want} == want
    for k in want:  # each page: flagged exactly when the list flags it, from its own experiment read
        page = server.get_strategy(server.Ctx(conn, user, (str(sid[k]),), {}, {}, None))
        assert page.get("no_gatekeeper_record", False) == flags[sid[k]] == (page.get("experiment") is None), k
    # The pass is flagged as before, by the list's later-check reads, not by the void column.
    kept = server.list_strategies(server.Ctx(conn, user, (), {"status": "passed", "page": "0"}, {}, None))
    assert [c.get("no_gatekeeper_record") for c in kept["strategies"]] == [True]
    # The same statements as with no void column: the flag and the count ride in reads the list already sent.
    monkeypatch.setattr(strat, "VOID_NO_RECORD_SQL", "(0)")
    counting.sqls = []
    bare = ask()
    assert len(counting.sqls) == sent and "failed_no_record" not in bare["counts"]
    assert not any(c.get("no_gatekeeper_record") for c in bare["strategies"])


def test_the_since_strip_judges_every_pass_since_the_visit_in_one_read(conn):
    """The dashboard's "since your last visit" judged only the newest 50 passes: with 60, of which the 10
    oldest then missed their one-time holdout, it said "60 strategies passed" and named none as not cleared.
    Every pass is judged now, with one read of their experiments' later rows."""
    from datetime import timedelta
    from app import repository as repo
    from app.research import research_repository as rr
    from app.trading import spec as specmod
    from app.web.routes import dashboard

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "since60@example.invalid", "S", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 1}})
    run = repo.create_run(cur, uid, "research", "btc15m", "custom", "idea")
    curve = [[1761000000 + 3600 * i, 0.05 if i % 3 else -0.04] for i in range(40)]
    ok = {"p_value": 0.01, "mean_net_return": 0.02, "ci_lo": 0.002, "ci_hi": 0.04}
    luck = {"p_value": 0.48, "mean_net_return": -0.003, "ci_lo": -0.03, "ci_hi": 0.025}
    missed = []
    for i in range(60):
        sid = repo.insert_strategy(cur, uid, run, None, "btc15m", "custom", "Pass %d" % i, "t", spec, "passed",
                                   {"classification": "statistically_supported"})
        eid = rr.preregister(cur, {"user_id": uid, "run_id": run, "strategy_id": sid, "market": "btc15m",
                                   "hypothesis_hash": uuid.uuid4().hex, "spec": spec, "economic_rationale": "{}",
                                   "primary_metric": "m", "null_hypothesis": "", "alt_hypothesis": "", "planned_test": "t",
                                   "falsification_criteria": "", "min_sample": 30, "cost_assumptions": {},
                                   "research_partition_id": 0, "planned_n_tests": 2, "correction_method": "BH"})
        rr.append_result(cur, eid, "validation", "statistically_supported", 40, metrics=dict(ok), equity_curve=curve)
        if i < 10:  # the oldest ten, past the newest 50
            rr.append_result(cur, eid, "holdout", "inconclusive", 40, metrics=dict(luck, holdout_consumed=True), equity_curve=curve)
            missed.append(sid)
        cur.execute("UPDATE app_strategies SET experiment_id=%s WHERE id=%s", (eid, sid))
    counting = _Counting(cur)
    got = dashboard._passed_since(counting, uid, repo.now_utc() - timedelta(hours=1))
    assert counting.later == 1
    assert got["n"] == 50 and got["not_cleared_n"] == 10 and "more" not in got
    assert [i["id"] for i in got["not_cleared"]] == missed[::-1][:3]
    assert {i["verdict"] for i in got["not_cleared"]} == {"missed_final"}
    assert not {i["id"] for i in got["items"]} & set(missed)
