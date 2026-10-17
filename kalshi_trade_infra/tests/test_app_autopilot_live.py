"""Safety gates for live autopilot: it must refuse to go live unless every gate holds,
and must not exceed the user's caps. Side (YES or NO) is no longer gated — live execution
now places the correct leg — but allowing NO must not weaken any other gate."""
from app import agent, engine

PASSED_YES = {"id": 7, "status": "passed", "title": "Tail fade", "market": "btc_daily",
              "direction": "custom", "spec": {"side": "yes", "sizing": {"stake": 5.0, "max_positions": 20}}}
PASSED_NO = {"id": 8, "status": "passed", "title": "NO fade", "market": "btc_daily",
             "direction": "custom", "spec": {"side": "no", "sizing": {"stake": 5.0, "max_positions": 20}}}
PROVEN_NO_PAPER = [{"strategy_id": 8, "mode": "paper", "closed_trades": 12, "realized_pnl": 8.0, "status": "stopped"}]


def _patch(monkeypatch, *, live_enabled=True, key=True, autopilot=True, ap_live=True, today_live=0.0,
           strat=None, paper=None, deployment_candidate=True, no_side_live=True):
    r = agent.repo
    created = {}
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", live_enabled)
    # Staged-rollout flag for NO-side live (default True here to isolate the OTHER gates; the
    # flag-off behavior — NO stays on paper — is verified separately below). YES ignores it.
    monkeypatch.setattr(engine, "NO_SIDE_LIVE_ENABLED", no_side_live)
    # Wave-2 additive gate (§E.5): deploy_live also requires the gatekeeper's DEPLOYMENT_CANDIDATE
    # classification, ON TOP OF every existing gate. Default it True so these tests still exercise
    # the ORIGINAL gates; the gate itself is verified separately below.
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: deployment_candidate)
    monkeypatch.setattr(r, "get_strategy", lambda cur, uid, sid: (strat or dict(PASSED_YES)))
    monkeypatch.setattr(r, "get_kalshi_key", lambda cur, uid: ({"key_id": "x"} if key else None))
    monkeypatch.setattr(r, "realized_pnl", lambda cur, uid, mode, since=None: today_live)
    # Paper history for the research->paper->live gate; default = proven (12 trades, +$8).
    monkeypatch.setattr(r, "list_deployments", lambda cur, uid, include_stopped=False: (
        paper if paper is not None else [{"strategy_id": 7, "mode": "paper", "closed_trades": 12, "realized_pnl": 8.0, "status": "stopped"}]))
    monkeypatch.setattr(r, "create_proposal", lambda *a, **k: 1)
    monkeypatch.setattr(r, "create_deployment", lambda cur, uid, sid, market, mode: (created.__setitem__("mode", mode), 99)[1])
    user = {"id": 1, "autopilot": autopilot, "autopilot_live": ap_live, "autopilot_daily_loss_limit": 50}
    return user, created


def test_refused_until_proven_on_paper(monkeypatch):
    # Not enough paper trades -> stays on paper even with all other gates green.
    user, created = _patch(monkeypatch, paper=[{"strategy_id": 7, "mode": "paper", "closed_trades": 2, "realized_pnl": 1.0, "status": "running"}])
    msg, pid = agent.act(None, user, {"type": "deploy_live", "strategy_id": 7}, autopilot=True)
    assert "mode" not in created and pid is None and "paper" in msg.lower()
    # Enough trades but losing on paper -> refused.
    user, created = _patch(monkeypatch, paper=[{"strategy_id": 7, "mode": "paper", "closed_trades": 20, "realized_pnl": -4.0, "status": "stopped"}])
    msg, pid = agent.act(None, user, {"type": "deploy_live", "strategy_id": 7}, autopilot=True)
    assert "mode" not in created and pid is None


def test_live_when_all_gates_pass(monkeypatch):
    user, created = _patch(monkeypatch)
    msg, pid = agent.act(None, user, {"type": "deploy_live", "strategy_id": 7}, autopilot=True)
    assert created.get("mode") == "live" and "LIVE" in msg and pid == 1


def test_refused_when_any_gate_fails(monkeypatch):
    for kw in (dict(live_enabled=False), dict(key=False), dict(ap_live=False),
               dict(autopilot=False), dict(today_live=-60.0)):  # -60 past the $50 daily limit
        user, created = _patch(monkeypatch, **kw)
        msg, pid = agent.act(None, user, {"type": "deploy_live", "strategy_id": 7}, autopilot=True)
        assert "mode" not in created, "went live despite a failed gate: %r" % kw
        assert pid is None


def test_no_side_strategy_goes_live_when_proven(monkeypatch):
    # The side gate is gone: a proven, gatekeeper-cleared NO-side strategy goes live like YES.
    user, created = _patch(monkeypatch, strat=dict(PASSED_NO), paper=list(PROVEN_NO_PAPER))
    msg, pid = agent.act(None, user, {"type": "deploy_live", "strategy_id": 8}, autopilot=True)
    assert created.get("mode") == "live" and "LIVE" in msg and pid == 1


def test_no_side_strategy_still_refused_when_any_gate_fails(monkeypatch):
    # Allowing NO must not weaken any other live gate: each failure still keeps it on paper.
    for kw in (dict(live_enabled=False), dict(key=False), dict(ap_live=False), dict(autopilot=False),
               dict(today_live=-60.0), dict(deployment_candidate=False), dict(no_side_live=False)):
        user, created = _patch(monkeypatch, strat=dict(PASSED_NO), paper=list(PROVEN_NO_PAPER), **kw)
        msg, pid = agent.act(None, user, {"type": "deploy_live", "strategy_id": 8}, autopilot=True)
        assert "mode" not in created and pid is None, "NO went live despite a failed gate: %r" % kw


def test_not_a_deployment_candidate_stays_on_paper(monkeypatch):
    # Every ORIGINAL gate is green, but the gatekeeper has not promoted the experiment to
    # DEPLOYMENT_CANDIDATE -> the additive gate (§E.5) keeps it off live money.
    user, created = _patch(monkeypatch, deployment_candidate=False)
    msg, pid = agent.act(None, user, {"type": "deploy_live", "strategy_id": 7}, autopilot=True)
    assert "mode" not in created and pid is None and "paper" in msg.lower()


def test_gate_helper_booleans(monkeypatch):
    user, _ = _patch(monkeypatch)
    ok, why = agent.live_autopilot_ok(None, user)
    assert ok and why == ""
    user2, _ = _patch(monkeypatch, key=False)
    ok2, why2 = agent.live_autopilot_ok(None, user2)
    assert not ok2 and "Kalshi" in why2
