"""Broadened co-pilot autonomy: the agent may tune risk + execution controls and start fresh
research, but every money/risk value it sets is CLAMPED into a safe envelope, and every change is
a logged proposal (applied on autopilot, pending otherwise). These tests pin the clamps and the
proposal/apply discipline so a future change can't quietly let the agent disable a stop, exceed a
cap, or loosen past a safe maximum."""
from app import agent


def _capture(monkeypatch):
    """Record proposals + persisted config without a DB."""
    rec = {"proposals": [], "risk": None, "exec": None, "runs": []}
    r = agent.repo
    monkeypatch.setattr(r, "create_proposal",
                        lambda cur, uid, kind, reason, did=None, sid=None, status="pending", payload=None:
                        rec["proposals"].append({"kind": kind, "status": status, "payload": payload}) or 1)
    monkeypatch.setattr(r, "set_user_risk_config", lambda cur, uid, changes: rec.update(risk=changes))
    monkeypatch.setattr(r, "set_user_execution_config", lambda cur, uid, changes: rec.update(exec=changes))
    monkeypatch.setattr(r, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(r, "create_run",
                        lambda cur, uid, kind, market, direction, idea, **kw: rec["runs"].append((market, direction, idea)) or 9)
    return rec


USER = {"id": 1}


# -- set_risk ----------------------------------------------------------------------

def test_set_risk_applies_within_bounds_on_autopilot(monkeypatch):
    rec = _capture(monkeypatch)
    text, pid = agent.act(None, USER, {"type": "set_risk",
                          "changes": {"drawdown_limit_pct": 15, "max_open_positions": 10, "max_open_notional": 500}}, True)
    assert pid == 1
    assert rec["proposals"][-1]["status"] == "applied"
    assert rec["risk"] == {"drawdown_limit_pct": 15.0, "max_open_positions": 10, "max_open_notional": 500.0}


def test_set_risk_is_a_pending_proposal_when_autopilot_off(monkeypatch):
    rec = _capture(monkeypatch)
    text, pid = agent.act(None, USER, {"type": "set_risk", "changes": {"drawdown_limit_pct": 15}}, False)
    assert pid == 1
    assert rec["proposals"][-1]["status"] == "pending"
    assert rec["risk"] is None                       # NOT applied until the user approves


def test_set_risk_cannot_disable_a_stop(monkeypatch):
    rec = _capture(monkeypatch)
    # 0 would disable the force-sell; it is clamped UP to the floor (never <= 0).
    agent.act(None, USER, {"type": "set_risk", "changes": {"drawdown_limit_pct": 0}}, True)
    assert rec["risk"]["drawdown_limit_pct"] == agent.RISK_BOUNDS["drawdown_limit_pct"][0]
    assert rec["risk"]["drawdown_limit_pct"] > 0


def test_set_risk_cannot_exceed_hard_caps(monkeypatch):
    rec = _capture(monkeypatch)
    agent.act(None, USER, {"type": "set_risk",
              "changes": {"drawdown_limit_pct": 999, "max_open_positions": 10000, "max_open_notional": 1e9}}, True)
    assert rec["risk"]["drawdown_limit_pct"] == agent.RISK_BOUNDS["drawdown_limit_pct"][1]
    assert rec["risk"]["max_open_positions"] == agent.RISK_BOUNDS["max_open_positions"][1]
    assert rec["risk"]["max_open_notional"] == agent.RISK_BOUNDS["max_open_notional"][1]


def test_set_risk_can_tighten_freely(monkeypatch):
    rec = _capture(monkeypatch)
    # A tighten (toward the floor) passes through unclamped as long as it's >= the floor.
    agent.act(None, USER, {"type": "set_risk", "changes": {"max_open_notional": 50}}, True)
    assert rec["risk"] == {"max_open_notional": 50.0}


def test_set_risk_ignores_unknown_keys(monkeypatch):
    rec = _capture(monkeypatch)
    text, pid = agent.act(None, USER, {"type": "set_risk",
                          "changes": {"live_enabled": True, "position_stop_pct": 0, "max_open_positions": 5}}, True)
    assert rec["risk"] == {"max_open_positions": 5}   # only the one real, enforced key survived


# -- set_exec ----------------------------------------------------------------------

def test_set_exec_applies_within_bounds(monkeypatch):
    rec = _capture(monkeypatch)
    agent.act(None, USER, {"type": "set_exec",
              "changes": {"exec_max_book_fraction": 0.2, "exec_max_entry_spread": 0.05, "exec_max_order_notional": 100}}, True)
    assert rec["exec"] == {"exec_max_book_fraction": 0.2, "exec_max_entry_spread": 0.05, "exec_max_order_notional": 100.0}


def test_set_exec_loosen_past_ceiling_is_clamped(monkeypatch):
    rec = _capture(monkeypatch)
    agent.act(None, USER, {"type": "set_exec",
              "changes": {"exec_max_book_fraction": 1.0, "exec_max_order_notional": 100000}}, True)
    assert rec["exec"]["exec_max_book_fraction"] == agent.EXEC_BOUNDS["exec_max_book_fraction"][1]
    assert rec["exec"]["exec_max_order_notional"] == agent.EXEC_BOUNDS["exec_max_order_notional"][1]


def test_set_exec_is_pending_when_autopilot_off(monkeypatch):
    rec = _capture(monkeypatch)
    agent.act(None, USER, {"type": "set_exec", "changes": {"exec_max_order_notional": 100}}, False)
    assert rec["proposals"][-1]["status"] == "pending"
    assert rec["exec"] is None


# -- apply_proposal re-clamps defensively ------------------------------------------

def test_apply_proposal_reclamps_a_tampered_payload(monkeypatch):
    rec = _capture(monkeypatch)
    # Even if a stored proposal row somehow carried an out-of-range value, applying it re-clamps.
    agent.apply_proposal(None, 1, {"kind": "set_risk", "payload": {"drawdown_limit_pct": 0, "max_open_notional": 1e9}})
    assert rec["risk"]["drawdown_limit_pct"] == agent.RISK_BOUNDS["drawdown_limit_pct"][0]
    assert rec["risk"]["max_open_notional"] == agent.RISK_BOUNDS["max_open_notional"][1]
    agent.apply_proposal(None, 1, {"kind": "set_exec", "payload": {"exec_max_book_fraction": 5}})
    assert rec["exec"]["exec_max_book_fraction"] == agent.EXEC_BOUNDS["exec_max_book_fraction"][1]


# -- fresh research: same pipeline, same freedom -----------------------------------

def test_research_action_starts_a_fresh_line(monkeypatch):
    rec = _capture(monkeypatch)
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "Fade the overreaction after a large 1-minute BTC move."}, True)
    assert pid is None                               # research queues a run, not a proposal
    assert rec["runs"] == [("btc15m", None, "Fade the overreaction after a large 1-minute BTC move.")]


def test_research_action_rejects_an_unknown_market(monkeypatch):
    rec = _capture(monkeypatch)
    text, pid = agent.act(None, USER, {"type": "research", "market": "not_a_market",
                          "idea": "something plausible here"}, True)
    assert pid is None and rec["runs"] == [] and "market" in text.lower()


def test_research_action_needs_a_real_idea(monkeypatch):
    rec = _capture(monkeypatch)
    text, pid = agent.act(None, USER, {"type": "research", "idea": "hi"}, True)
    assert pid is None and rec["runs"] == []


# -- per-user daily research cap: the autopilot honors it like the manual endpoint ----------------

def test_research_action_respects_the_daily_cap(monkeypatch):
    # With a daily cap set and the user at it, the autopilot declines (not just the manual endpoint).
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent, "MAX_RESEARCH_PER_DAY", 5)
    monkeypatch.setattr(agent.repo, "count_runs",   # 0 active, but 5 in the last day (= the cap)
                        lambda cur, uid, kind, since=None, active_only=False: 5 if since is not None else 0)
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "Fade the overreaction after a large 1-minute BTC move."}, True)
    assert pid is None and rec["runs"] == []
    assert "daily research limit" in text.lower()


def test_research_action_proceeds_under_the_daily_cap(monkeypatch):
    # Cap set but the user is under it: research still launches.
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent, "MAX_RESEARCH_PER_DAY", 5)
    monkeypatch.setattr(agent.repo, "count_runs",   # 0 active, 2 in the last day (under the cap)
                        lambda cur, uid, kind, since=None, active_only=False: 2 if since is not None else 0)
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "Fade the overreaction after a large 1-minute BTC move."}, True)
    assert pid is None and rec["runs"] == [("btc15m", None, "Fade the overreaction after a large 1-minute BTC move.")]


# -- global backpressure: don't launch when the shared research queue is saturated ----------------

def test_research_action_backs_off_when_the_global_queue_is_full(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent, "MAX_GLOBAL_ACTIVE_RESEARCH", 3)
    monkeypatch.setattr(agent.repo, "count_active_research", lambda cur: 3)  # at the global cap
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "Fade the overreaction after a large 1-minute BTC move."}, True)
    assert pid is None and rec["runs"] == []
    assert "queue is full" in text.lower()


def test_research_action_launches_when_global_queue_has_room(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent, "MAX_GLOBAL_ACTIVE_RESEARCH", 3)
    monkeypatch.setattr(agent.repo, "count_active_research", lambda cur: 1)  # under the global cap
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "Fade the overreaction after a large 1-minute BTC move."}, True)
    assert pid is None and rec["runs"] == [("btc15m", None, "Fade the overreaction after a large 1-minute BTC move.")]


# -- per-market dedup/cooldown: don't re-spam a market that's running or just finished -------------

def test_research_action_skips_a_market_already_running(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent.repo, "list_runs",
                        lambda cur, uid, limit=30: [{"id": 5, "market": "btc15m", "status": "running",
                                                     "finished_at": None}])
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "Fade the overreaction after a large 1-minute BTC move."}, True)
    assert pid is None and rec["runs"] == []            # no duplicate line launched
    assert "already running" in text.lower()


def test_research_action_skips_a_market_on_cooldown(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent.repo, "list_runs",
                        lambda cur, uid, limit=30: [{"id": 6, "market": "btc15m", "status": "failed",
                                                     "finished_at": agent.repo.now_utc()}])
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "Another angle on BTC overreaction."}, True)
    assert pid is None and rec["runs"] == []            # just-failed market is on cooldown
    assert "cooldown" in text.lower()


def test_research_action_allows_a_different_market(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent.repo, "list_runs",
                        lambda cur, uid, limit=30: [{"id": 7, "market": "btc15m", "status": "running",
                                                     "finished_at": None}])
    text, pid = agent.act(None, USER, {"type": "research", "market": "eth_daily",
                          "idea": "Mean-revert ETH after a sharp daily gap."}, True)
    assert pid is None and rec["runs"] == [("eth_daily", None, "Mean-revert ETH after a sharp daily gap.")]
