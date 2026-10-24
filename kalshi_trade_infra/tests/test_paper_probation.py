"""Forward paper probation: validation near misses run on paper (flag-gated, autopilot only, capped),
and never get a live path, since live still requires a gatekeeper DEPLOYMENT_CANDIDATE."""
from app import agent
from app import research_repository as rr

USER = {"id": 2, "autopilot": True}
SPEC = {"side": "yes", "sizing": {"stake": 5, "max_positions": 1}}


def _cand(sid, market="sol_daily", p=0.15):
    return {"strategy_id": sid, "market": market, "p_value": p, "net_pnl": 12.5, "n_trades": 40}


def _patch(monkeypatch, cands, deps=(), candidates=(), on=True):
    made, props = [], []
    monkeypatch.setattr(agent, "PAPER_PROBATION", on)
    monkeypatch.setattr(agent.rr, "probation_candidates", lambda cur, uid, p, n: list(cands))
    monkeypatch.setattr(agent.repo, "list_deployments", lambda cur, uid, include_stopped=False: list(deps))
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "market": next(c["market"] for c in cands if c["strategy_id"] == sid),
        "title": "S%d" % sid, "spec": dict(SPEC), "status": "rejected"})
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: sid in candidates)
    monkeypatch.setattr(agent.repo, "create_deployment", lambda cur, uid, sid, m, mode: made.append((sid, m, mode)) or 1)
    monkeypatch.setattr(agent.repo, "create_proposal", lambda cur, uid, kind, reason, a, sid, status: props.append((kind, sid, status)) or 1)
    from app import engine
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
