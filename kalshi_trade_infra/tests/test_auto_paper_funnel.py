"""Autopilot funnel: every gatekeeper-cleared candidate that never ran on paper is put on paper
through act()'s deploy path, bounded per review and in total; never live; never re-deploys a
strategy whose paper run was stopped."""
from app.research import agent

S = lambda sid, market="btc15m": {"id": sid, "status": "passed", "title": "S%d" % sid, "market": market,
                                  "spec": {"side": "yes", "sizing": {"stake": 5.0, "max_positions": 5}}}


def _patch(monkeypatch, strategies, deps=(), candidates=None):
    r = agent.repo
    created = []
    monkeypatch.setattr(r, "list_deployments", lambda cur, uid, include_stopped=False: list(deps))
    monkeypatch.setattr(r, "list_strategies", lambda cur, uid, status=None, limit=500: list(strategies))
    monkeypatch.setattr(r, "get_strategy", lambda cur, uid, sid: next(s for s in strategies if s["id"] == sid))
    monkeypatch.setattr(agent, "_is_deployment_candidate",
                        lambda cur, sid: True if candidates is None else sid in candidates)
    monkeypatch.setattr(r, "create_proposal", lambda *a, **k: 1)
    monkeypatch.setattr(r, "create_deployment",
                        lambda cur, uid, sid, market, mode: created.append((sid, mode)) or 99)
    monkeypatch.setattr(r, "add_notification", lambda *a, **k: 1)  # the bell for each new paper strategy
    return created


def test_candidates_go_to_paper_only(monkeypatch):
    created = _patch(monkeypatch, [S(1), S(2)], candidates={1})
    lines = agent.auto_paper_candidates(None, {"id": 1, "autopilot": True})
    assert created == [(1, "paper")] and len(lines) == 1


def test_off_when_autopilot_is_off(monkeypatch):
    created = _patch(monkeypatch, [S(1)])
    assert agent.auto_paper_candidates(None, {"id": 1, "autopilot": False}) == [] and created == []


def test_a_stopped_paper_run_is_not_redeployed(monkeypatch):
    created = _patch(monkeypatch, [S(1)], deps=[{"strategy_id": 1, "mode": "paper", "status": "stopped"}])
    assert agent.auto_paper_candidates(None, {"id": 1, "autopilot": True}) == [] and created == []


def test_bounded_per_review_and_in_total(monkeypatch):
    created = _patch(monkeypatch, [S(i) for i in range(1, 10)])
    agent.auto_paper_candidates(None, {"id": 1, "autopilot": True})
    assert len(created) == agent.AUTO_PAPER_MAX_NEW
    busy = [{"strategy_id": 100 + i, "mode": "paper", "status": "running"} for i in range(agent.AUTO_PAPER_MAX_ACTIVE)]
    created = _patch(monkeypatch, [S(1)], deps=busy)
    assert agent.auto_paper_candidates(None, {"id": 1, "autopilot": True}) == [] and created == []


def test_research_only_markets_are_skipped(monkeypatch):
    from app.markets import MARKETS
    research_only = next((k for k, m in MARKETS.items() if not m.deployable), None)
    if research_only is None:
        return
    created = _patch(monkeypatch, [S(1, market=research_only)])
    assert agent.auto_paper_candidates(None, {"id": 1, "autopilot": True}) == [] and created == []
