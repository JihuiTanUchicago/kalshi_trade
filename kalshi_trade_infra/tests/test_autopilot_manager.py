"""Autopilot = OPERATION MANAGER, not a one-shot reactor. These pin the three shifts:
  1. DELEGATE — a research action hands the pipeline a market + a short ANGLE (brief=True), and the
     proposer treats a brief as a starting direction, NOT a verbatim thesis.
  2. OPERATING PLAN — a small durable plan round-trips (bounded) and is surfaced in the context.
  3. PORTFOLIO — promote-over-explore still holds and portfolio guidance is present.
Plus a guard that the delegation path touches no money gate/clamp.
"""
from app.research import agent
from app import repository as repo


USER = {"id": 1}


# -- Shift 1: DELEGATE, don't author ---------------------------------------------------------------


def test_research_action_delegates_market_and_angle(monkeypatch):
    rec = {}
    monkeypatch.setattr(repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(agent, "_market_research_recent", lambda *a, **k: None)
    monkeypatch.setattr(repo, "create_run",
                        lambda cur, uid, kind, market, direction, idea, **kw: rec.update(
                            market=market, idea=idea, brief=kw.get("brief")) or 9)
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "order-flow if this market has microstructure data"}, True)
    assert pid is None                                   # research queues a run, not a money proposal
    assert rec["market"] == "btc15m"
    assert rec["brief"] is True                          # DELEGATED: flagged as a brief, not a thesis
    assert rec["idea"] == "order-flow if this market has microstructure data"


def test_research_action_stamps_user_autopilot_model(monkeypatch):
    rec = {}
    monkeypatch.setattr(repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(agent, "_market_research_recent", lambda *a, **k: None)
    monkeypatch.setattr(repo, "create_run",
                        lambda cur, uid, kind, market, direction, idea, **kw: rec.update(model=kw.get("model")) or 9)
    agent.act(None, {"id": 1, "autopilot_model": "claude-sonnet-5-5"},
              {"type": "research", "market": "btc15m", "idea": "order-flow microstructure angle"}, True)
    assert rec["model"] == "claude-sonnet-5-5"   # autopilot research runs on the user's chosen model
    # and None (default) when the user hasn't picked one
    rec.clear()
    agent.act(None, {"id": 1}, {"type": "research", "market": "btc15m", "idea": "order-flow microstructure angle"}, True)
    assert rec.get("model") is None


def test_brief_research_prompt_delegates_not_authors():
    run = {"market": "nhl_game", "prompt": "favorite-longshot on this sports market", "brief": 1}
    p = agent._research_prompt(run, _mini_ds("nhl_game"), [], count=3)
    assert "NOT a finished thesis" in p and "delegated" in p.lower()
    assert "GENERATE the concrete, testable" in p
    assert "Stay faithful to what the user asked for" not in p   # the manual-idea framing is gone


def test_user_idea_research_prompt_stays_faithful():
    # A Research-page run (no brief flag) must keep fidelity to the user's own idea.
    run = {"market": "nhl_game", "prompt": "fade heavy favorites late"}
    p = agent._research_prompt(run, _mini_ds("nhl_game"), [], count=3)
    assert "Stay faithful to what the user asked for" in p
    assert "NOT a finished thesis" not in p


def _mini_ds(market_key):
    from app import backtest
    from app.markets import MARKETS
    return backtest.Dataset(market=MARKETS[market_key], frames=[], results={}, start_ts=0, end_ts=86400, contracts=0)


# -- Shift 2: PERSISTENT OPERATING PLAN ------------------------------------------------------------


class _FakeCur:
    """Minimal cursor: stores the plan value written by UPDATE and returns it on SELECT."""
    def __init__(self):
        self._raw = None
        self._row = None

    def execute(self, sql, params=None):
        if sql.strip().upper().startswith("UPDATE"):
            self._raw = params[0]
        else:
            self._row = {"autopilot_plan": self._raw}

    def fetchone(self):
        return self._row


def test_operating_plan_round_trips_and_is_bounded():
    cur = _FakeCur()
    repo.set_autopilot_plan(cur, 1, {
        "goals": "prove a fee-surviving BTC edge",
        "agenda": "x" * 5000,                 # oversized -> must be truncated
        "posture": "conservative on live",
        "junk": "should be dropped",          # unknown key -> must be filtered out
    })
    got = repo.autopilot_plan(cur, 1)
    assert got["goals"] == "prove a fee-surviving BTC edge"
    assert len(got["agenda"]) == repo._PLAN_FIELD_MAX   # bounded briefing, not a growing journal
    assert got["posture"] == "conservative on live"
    assert "junk" not in got                            # only the known fields persist


def test_operating_plan_surfaced_in_context(monkeypatch):
    _wire_context(monkeypatch)
    monkeypatch.setattr(repo, "autopilot_plan", lambda cur, uid: {"goals": "chase a proven BTC edge"})
    ctx = agent._copilot_context(None, USER)
    assert "Your operating plan" in ctx and "chase a proven BTC edge" in ctx


def test_copilot_check_accepts_and_sanitizes_plan():
    out = agent._copilot_check({"reply": "ok", "actions": [], "plan": {"goals": "g"}})
    assert out["plan"] == {"goals": "g"}
    out2 = agent._copilot_check({"reply": "ok", "actions": [], "plan": "not a dict"})
    assert out2["plan"] is None                         # a non-dict plan is ignored, never persisted


# -- Shift 3: PORTFOLIO-LEVEL reasoning ------------------------------------------------------------


def test_promote_over_explore_still_holds(monkeypatch):
    _wire_context(monkeypatch,
                  strat={"passed": [{"id": 3, "title": "BTC drift", "market": "btc15m",
                                     "result": {"out_of_sample": {"pnl": 12, "trades": 40}}}]})
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: True)
    ctx = agent._copilot_context(None, USER)
    assert "DEPLOYMENT-CANDIDATE" in ctx and "PROMOTE it to paper" in ctx
    assert "PROMOTE OVER EXPLORE" in ctx                # portfolio guidance present


def test_portfolio_guidance_present(monkeypatch):
    _wire_context(monkeypatch)
    ctx = agent._copilot_context(None, USER)
    assert "RUN IT AS A PORTFOLIO" in ctx
    assert "microstructure" in ctx and "BTC" in ctx     # steer toward data-rich markets


def _wire_context(monkeypatch, **over):
    monkeypatch.setattr(repo, "list_deployments", lambda cur, uid, **k: over.get("deps", []))
    strat = over.get("strat", {})
    monkeypatch.setattr(repo, "list_strategies", lambda cur, uid, status=None, **k: strat.get(status, []))
    monkeypatch.setattr(repo, "user_risk_config", lambda cur, uid: {})
    monkeypatch.setattr(repo, "user_execution_config", lambda cur, uid: {})
    monkeypatch.setattr(repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(repo, "autopilot_plan", lambda cur, uid: over.get("plan", {}))


# -- guard: the delegation changes touch NO money gate/clamp ---------------------------------------


def test_delegation_did_not_touch_clamps_or_gates():
    # The clamp envelopes and the live/deploy gate helpers are exactly as before — unchanged shape.
    assert set(agent.RISK_BOUNDS) == {"drawdown_limit_pct", "max_open_positions", "max_open_notional"}
    assert "exec_max_order_notional" in agent.EXEC_BOUNDS
    for name in ("live_autopilot_ok", "_proven_on_paper", "_is_deployment_candidate", "raises_risk"):
        assert hasattr(agent, name)
    # A research action never creates a proposal or moves money (pid is None) even on autopilot.
    text, pid = agent.act(_FakeCur2(), USER, {"type": "research", "idea": "a short angle to explore"}, True)
    assert pid is None


class _FakeCur2:
    lastrowid = 9
    def execute(self, *a, **k): pass
    def fetchone(self): return {"n": 0}
    def fetchall(self): return []


def test_market_backed_off_after_repeated_failures(monkeypatch):
    # A market that fails repeatedly (>= RESEARCH_FAIL_LIMIT) within the day is backed off, so the
    # autopilot stops burning runs on a chronically-bad market and hunts a different one.
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 19, 12, 0, 0)
    monkeypatch.setattr(repo, "now_utc", lambda: now)
    fails = [{"id": i, "market": "natgas", "status": "failed",
              "finished_at": now - timedelta(hours=7 + i)} for i in range(agent.RESEARCH_FAIL_LIMIT)]
    monkeypatch.setattr(repo, "list_runs", lambda cur, uid, limit=30: fails)
    reason = agent._market_research_recent(None, 1, "natgas")
    assert reason is not None and "backed off" in reason


def test_market_with_a_single_old_failure_is_not_backed_off(monkeypatch):
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 19, 12, 0, 0)
    monkeypatch.setattr(repo, "now_utc", lambda: now)
    # one failure, 7h ago (past the 6h short cooldown, under the fail limit) -> clear to research
    monkeypatch.setattr(repo, "list_runs", lambda cur, uid, limit=30:
                        [{"id": 1, "market": "btc15m", "status": "failed", "finished_at": now - timedelta(hours=7)}])
    assert agent._market_research_recent(None, 1, "btc15m") is None
