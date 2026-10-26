"""Forward paper probation: validation near misses run on paper (flag-gated, autopilot only, capped),
and never get a live path, since live still requires a gatekeeper DEPLOYMENT_CANDIDATE."""
from app.research import agent
from app import research_repository as rr

USER = {"id": 2, "autopilot": True}
SPEC = {"side": "yes", "sizing": {"stake": 5, "max_positions": 1}}


def _cand(sid, market="sol_daily", p=0.15):
    return {"strategy_id": sid, "market": market, "p_value": p, "net_pnl": 12.5, "n_trades": 40}


def _patch(monkeypatch, cands, deps=(), candidates=(), on=True):
    made, props = [], []
    monkeypatch.setattr(agent, "PAPER_PROBATION", on)
    monkeypatch.setattr(agent.rr, "probation_candidates", lambda cur, uid, p, n: [c for c in cands if c["p_value"] is not None])
    monkeypatch.setattr(agent.rr, "underpowered_candidates", lambda cur, uid, n: [c for c in cands if c["p_value"] is None])
    monkeypatch.setattr(agent.repo, "list_deployments", lambda cur, uid, include_stopped=False: list(deps))
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "market": next((c.get("strat_market", c["market"]) for c in cands if c["strategy_id"] == sid), "sol_daily"),
        "title": "S%d" % sid, "spec": dict(SPEC), "status": "rejected",
        "result": {"out_of_sample": {"trades": 30, "pnl": 4.0 if sid % 2 else -1.0}}})
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: sid in candidates)
    monkeypatch.setattr(agent.rr, "experiments_for_strategy", lambda cur, sid, eid=None: None)
    monkeypatch.setattr(agent.repo, "create_deployment", lambda cur, uid, sid, m, mode: made.append((sid, m, mode)) or 1)
    monkeypatch.setattr(agent.repo, "create_proposal", lambda cur, uid, kind, reason, a, sid, status: props.append((kind, sid, status)) or 1)
    from app.trading import engine
    monkeypatch.setattr(engine, "cross_deploy_block", lambda spec, mode: "")
    return made, props


def test_off_by_default_and_needs_autopilot(monkeypatch):
    made, _ = _patch(monkeypatch, [_cand(1)], on=False)
    assert agent.auto_paper_probation(None, USER) == [] and made == []
    made, _ = _patch(monkeypatch, [_cand(1)])
    assert agent.auto_paper_probation(None, dict(USER, autopilot=False)) == [] and made == []


def test_near_misses_go_to_paper_only(monkeypatch):
    made, props = _patch(monkeypatch, [_cand(1), _cand(2)])
    lines = agent.auto_paper_probation(None, USER)
    assert made == [(1, "sol_daily", "paper"), (2, "sol_daily", "paper")]
    assert props == [("deploy", 1, "applied"), ("deploy", 2, "applied")]
    assert "[probation #1]" in lines[0] and "can't go live" in lines[0]


def test_skips_tried_undeployable_and_respects_the_cap(monkeypatch):
    deps = [{"strategy_id": 1, "status": "stopped", "mode": "paper"}]
    cands = [_cand(1), _cand(2, market="no_such_market"), _cand(3), _cand(4), _cand(5), _cand(6)]
    made, _ = _patch(monkeypatch, cands, deps=deps)
    monkeypatch.setattr(agent, "PROBATION_MAX_ACTIVE", 2)
    agent.auto_paper_probation(None, USER)
    assert [m[0] for m in made] == [3, 4]


def test_running_candidates_do_not_use_probation_slots(monkeypatch):
    deps = [{"strategy_id": 9, "status": "running", "mode": "paper"},
            {"strategy_id": 8, "status": "running", "mode": "paper"}]
    made, _ = _patch(monkeypatch, [_cand(3)], deps=deps, candidates=(9,))
    monkeypatch.setattr(agent, "PROBATION_MAX_ACTIVE", 2)
    agent.auto_paper_probation(None, USER)
    assert [m[0] for m in made] == [3]  # only #8 counts as probation; one slot left


def test_a_probation_strategy_cannot_go_live(monkeypatch):
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "market": "sol_daily", "title": "S", "spec": dict(SPEC), "status": "passed"})
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: False)
    text, pid = agent.act(None, USER, {"type": "deploy_live", "strategy_id": 1}, autopilot=True)
    assert pid is None and "gatekeeper" in text


def test_candidates_query_takes_the_latest_validation_row_only():
    class Rec:
        def execute(self, sql, params=()):
            self.sql, self.params = sql, params

        def fetchall(self):
            return [{"strategy_id": 5, "market": "m", "p_value": 0.1, "net_pnl": 3, "n_trades": 30}]

    cur = Rec()
    out = rr.probation_candidates(cur, 2, 0.25, 20, limit=7)
    assert out == [{"strategy_id": 5, "market": "m", "p_value": 0.1, "net_pnl": 3.0, "n_trades": 30}]
    assert "MAX(r2.id)" in cur.sql and "r.net_pnl > 0" in cur.sql and cur.params == (2, 0.25, 20, 7)


def _pause_patch(monkeypatch, dep):
    statuses = []
    monkeypatch.setattr(agent.repo, "get_deployment", lambda cur, uid, did: dict(dep))
    monkeypatch.setattr(agent.repo, "create_proposal", lambda *a: 1)
    monkeypatch.setattr(agent.repo, "set_deployment_status", lambda cur, uid, did, st, why=None: statuses.append(st))
    return statuses


def test_autopilot_cannot_pause_a_fresh_paper_deployment(monkeypatch):
    from datetime import timedelta
    now = agent.repo.now_utc()
    dep = {"id": 74, "title": "S", "mode": "paper", "status": "running", "market": "sol15m",
           "spec": dict(SPEC), "created_at": now - timedelta(minutes=10)}
    statuses = _pause_patch(monkeypatch, dep)
    text, pid = agent.act(None, USER, {"type": "pause", "deployment_id": 74, "reason": "zero fills"}, autopilot=True)
    assert pid is None and statuses == [] and "only 0.2 hours" in text
    statuses = _pause_patch(monkeypatch, dict(dep, created_at=now - timedelta(hours=30)))
    agent.act(None, USER, {"type": "pause", "deployment_id": 74, "reason": "idle"}, autopilot=True)
    assert statuses == ["paused"]


def test_fresh_live_deployments_can_always_be_paused(monkeypatch):
    dep = {"id": 9, "title": "L", "mode": "live", "status": "running", "market": "sol15m",
           "spec": dict(SPEC), "created_at": agent.repo.now_utc()}
    statuses = _pause_patch(monkeypatch, dep)
    agent.act(None, USER, {"type": "pause", "deployment_id": 9, "reason": "risk"}, autopilot=True)
    assert statuses == ["paused"]


def test_review_context_shows_deployment_age():
    from datetime import timedelta
    now = agent.repo.now_utc()
    fresh = agent._deployment_age_text({"mode": "paper", "created_at": now - timedelta(minutes=30)})
    assert "0.5 hours ago" in fresh and "too new to judge" in fresh
    old = agent._deployment_age_text({"mode": "paper", "created_at": now - timedelta(days=3)})
    assert "3.0 days ago" in old and "too new" not in old
    live = agent._deployment_age_text({"mode": "live", "created_at": now - timedelta(minutes=30)})
    assert "too new" not in live
    assert agent._deployment_age_text({"mode": "paper"}) == ""


def test_probation_ignores_the_research_focus_and_takes_p_up_to_035(monkeypatch):
    """Todd 2026-10-25: near misses go to paper even off his crypto focus (his were kxrain, p=0.30
    and 0.34). Paper only: no money moves, and live still needs a DEPLOYMENT_CANDIDATE."""
    made, _ = _patch(monkeypatch, [_cand(1, market="sol_daily", p=0.34)])
    monkeypatch.setattr(agent, "focus_tokens", lambda user: ["sports"])
    agent.auto_paper_probation(None, dict(USER, autopilot_focus='["sports"]'))
    assert made == [(1, "sol_daily", "paper")]
    assert agent.PROBATION_MAX_P >= 0.34


def test_a_pooled_near_miss_goes_to_paper_on_every_leg_it_was_judged_on(monkeypatch):
    """A pooled rule's experiment is filed under its FDR stream ("btc_daily+eth_daily+..."), which is
    no market. It paper-trades as the plain rule on its own market first, then on every other leg,
    so the forward test is the hypothesis validation judged, at the same sample rate."""
    pooled = "btc_daily+eth_daily+sol_daily+xrp_daily"
    made, _ = _patch(monkeypatch, [dict(_cand(1, market=pooled, p=None), n_trades=40, strat_market="btc_daily"),
                                   dict(_cand(3, market=pooled), strat_market="doge15m")])
    lines = agent.auto_paper_probation(None, USER)
    # #3's market is not in its experiment's stream
    assert made == [(1, m, "paper") for m in ("btc_daily", "eth_daily", "sol_daily", "xrp_daily")]
    assert "on btc_daily, eth_daily, sol_daily, xrp_daily" in lines[0]


def test_a_running_pooled_entrant_gets_its_missing_legs_once(monkeypatch):
    """16140 went to paper on btc15m alone before legs existed; the next review adds the other three,
    whatever its record looks like, and a stopped (retired) entrant gets none."""
    deps = [{"strategy_id": 1, "status": "running", "mode": "paper", "market": "btc15m"},
            {"strategy_id": 2, "status": "stopped", "mode": "paper", "market": "btc15m"}]
    made, _ = _patch(monkeypatch, [], deps=deps)
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "market": "btc15m", "title": "S%d" % sid, "spec": dict(SPEC), "experiment_id": 9})
    monkeypatch.setattr(agent.rr, "experiments_for_strategy", lambda cur, sid, eid=None: {
        "experiment": {"market": "btc15m+eth15m+sol15m+xrp15m"}})
    lines = agent.auto_paper_probation(None, USER)
    assert made == [(1, m, "paper") for m in ("eth15m", "sol15m", "xrp15m")]
    assert "added eth15m, sol15m, xrp15m" in lines[0]
    deps.extend({"strategy_id": 1, "status": "running", "mode": "paper", "market": m} for m in ("eth15m", "sol15m", "xrp15m"))
    made.clear()
    assert agent.auto_paper_probation(None, USER) == [] and made == []


def test_a_code_near_miss_goes_to_paper_as_one_replayed_deployment(monkeypatch):
    """Todd 2026-10-25 ("Paper only, in the sandbox"): agent-written code enters probation like any
    near miss, as ONE deployment (the sandbox replay trades its whole pooled stream), and only while
    the replay is on."""
    from app.services import code_paper
    cands = [_cand(7, market="btc_daily+eth_daily+sol_daily", p=0.2)]
    for on, want in ((False, []), (True, [(7, "btc_daily", "paper")])):
        made, _ = _patch(monkeypatch, cands)
        monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
            "id": sid, "market": "btc_daily", "title": "Pooled last-4h", "status": "rejected",
            "spec": {"market": "btc_daily", "pool": ["eth_daily", "sol_daily"], "code": "def signals(w): return []",
                     "sizing": {"stake": 5, "max_positions": 1}}, "result": {}})
        monkeypatch.setattr(code_paper, "ENABLED", on)
        lines = agent.auto_paper_probation(None, USER)
        assert made == want
    assert "replaying each settled day in the research sandbox" in lines[0] and "never goes live" in lines[0]
