"""Safety gates for live autopilot: it must refuse to go live unless every gate holds,
and must not exceed the user's caps. Side (YES or NO) is no longer gated — live execution
now places the correct leg — but allowing NO must not weaken any other gate."""
from app import agent, engine

PASSED_YES = {"id": 7, "status": "passed", "title": "Tail fade", "market": "btc_daily",
              "direction": "custom", "spec": {"side": "yes", "sizing": {"stake": 5.0, "max_positions": 20}}}
PASSED_NO = {"id": 8, "status": "passed", "title": "NO fade", "market": "btc_daily",
             "direction": "custom", "spec": {"side": "no", "sizing": {"stake": 5.0, "max_positions": 20}}}
def _trips(n=40, hours=72.0, pnls=None):
    """Realistic (simulated-venue) paper round trips, evenly spread over `hours`."""
    from datetime import datetime, timedelta
    t0 = datetime(2026, 10, 1)
    pnls = pnls if pnls is not None else [0.6 if i % 4 else -0.4 for i in range(n)]  # clear positive edge
    step = hours / max(1, len(pnls) - 1)
    return [{"pnl": p, "opened_at": t0 + timedelta(hours=i * step), "closed_at": t0 + timedelta(hours=i * step, minutes=15)}
            for i, p in enumerate(pnls)]


PROVEN_NO_PAPER = [{"strategy_id": 8, "mode": "paper", "closed_trades": 12, "realized_pnl": 8.0, "status": "stopped"}]


def _patch(monkeypatch, *, live_enabled=True, key=True, autopilot=True, ap_live=True, today_live=0.0,
           strat=None, paper=None, deployment_candidate=True, no_side_live=True, trips=None):
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
    # Realistic-fill paper evidence for the strengthened gate; default = proven.
    monkeypatch.setattr(r, "paper_round_trips", lambda cur, uid, sid: (trips if trips is not None else _trips()))
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


def _deploy_live(monkeypatch, **kw):
    user, created = _patch(monkeypatch, **kw)
    msg, pid = agent.act(None, user, {"type": "deploy_live", "strategy_id": 7}, autopilot=True)
    return msg, created


def test_refused_without_enough_realistic_paper_trades(monkeypatch):
    # Legacy totals look proven, but only 10 trades ran on realistic fills.
    msg, created = _deploy_live(monkeypatch, trips=_trips(n=10))
    assert "mode" not in created and "realistic" in msg


def test_refused_when_net_negative_on_realistic_fills(monkeypatch):
    msg, created = _deploy_live(monkeypatch, trips=_trips(pnls=[-0.1] * 40))
    assert "mode" not in created and "isn't up" in msg


def test_refused_when_paper_record_is_too_short(monkeypatch):
    msg, created = _deploy_live(monkeypatch, trips=_trips(hours=6.0))
    assert "mode" not in created and "covers only" in msg


def test_refused_when_edge_is_not_statistically_clear(monkeypatch):
    # Net positive but noise-dominated: +$0.05 drift on +/-$5 swings.
    noisy = [5.05 if i % 2 else -4.95 for i in range(40)]
    msg, created = _deploy_live(monkeypatch, trips=_trips(pnls=noisy))
    assert "mode" not in created and "statistically" in msg


def test_refused_when_the_newer_half_of_the_record_is_down(monkeypatch):
    # A strong first half carries the whole record (net up, edge "clear"), but the newer 20 trades
    # lose money: the edge may have faded, so it stays on paper.
    fading = [1.0 if i % 4 else 0.5 for i in range(20)] + [0.3 if i % 2 else -0.5 for i in range(20)]
    msg, created = _deploy_live(monkeypatch, trips=_trips(pnls=fading))
    assert "mode" not in created and "newer 20 paper trades are down $2.00" in msg
    ev = agent.paper_evidence(None, 1, 7)
    assert ev["checks"]["edge"] and not ev["checks"]["recent"]
    assert (ev["recent_trades"], ev["recent_net_pnl"]) == (20, -2.0)


def test_proven_on_realistic_fills_goes_live(monkeypatch):
    msg, created = _deploy_live(monkeypatch, trips=_trips())
    assert created.get("mode") == "live"


def test_paper_evidence_reports_backtest_realization(monkeypatch):
    _patch(monkeypatch, trips=_trips(pnls=[0.5] * 40))
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "result": {"out_of_sample": {"pnl": 40.0, "trades": 40}}})  # $1.00/trade in backtest
    ev = agent.paper_evidence(None, 1, 7)
    assert ev["paper_mean_pnl"] == 0.5 and ev["backtest_mean_pnl"] == 1.0
    assert ev["realization"] == 0.5
    line = agent.paper_evidence_line(ev)
    assert "50% of backtest" in line and "40/30 realistic" in line


def test_paper_evidence_line_names_the_blocker(monkeypatch):
    _patch(monkeypatch, trips=_trips(n=5))
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: None)
    ev = agent.paper_evidence(None, 1, 7)
    assert ev["realization"] is None
    assert "not live-ready: it needs 30+" in agent.paper_evidence_line(ev)


def test_refused_when_the_trades_come_from_too_few_separate_events(monkeypatch):
    # 40 trades, but five strikes of each of 8 BTC 15-minute events: 8 bets, not 40.
    trips = _trips()
    for i, t in enumerate(trips):
        t["ticker"] = "KXBTC15M-26OCT24%04d-%d" % (i // 5, 60000 + i % 5)
    msg, created = _deploy_live(monkeypatch, trips=trips)
    assert "mode" not in created and "come from only 8 separate events" in msg
    ev = agent.paper_evidence(None, 1, 7)
    assert ev["events"] == 8 and ev["p_value"] is None and not ev["checks"]["events"]


def test_edge_is_tested_on_per_event_pnl():
    trips = [{"pnl": 1.0, "ticker": "KXRAIN-26OCT24-MIA"}, {"pnl": -0.5, "ticker": "KXRAIN-26OCT24-DEN"},
             {"pnl": 2.0, "ticker": "KXRAIN-26OCT25-MIA"}, {"pnl": 0.25, "ticker": None}, {"pnl": 0.25}]
    assert agent._trip_events(trips) == [0.5, 2.0, 0.25, 0.25]
