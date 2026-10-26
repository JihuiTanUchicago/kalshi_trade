"""Broadened co-pilot autonomy: the agent may tune risk + execution controls and start fresh
research, but every money/risk value it sets is CLAMPED into a safe envelope, and every change is
a logged proposal (applied on autopilot, pending otherwise). These tests pin the clamps and the
proposal/apply discipline so a future change can't quietly let the agent disable a stop, exceed a
cap, or loosen past a safe maximum."""
from app.research import agent


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
    # By hand only; on autopilot the angle runs on a market the specialist picks (test below).
    text, pid = agent.act(None, USER, {"type": "research", "market": "not_a_market",
                          "idea": "something plausible here"}, False)
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
    # On autopilot a cooldown market no longer stalls research: the angle runs with market=None, and
    # run_research picks from markets off cooldown (prod 2026-10-24: an hour of reviews started nothing).
    assert pid is None and rec["runs"] == [(None, None, "Another angle on BTC overreaction.")]
    assert "cooldown" in text.lower()


def test_research_action_on_cooldown_still_refuses_when_not_autopilot(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent.repo, "list_runs",
                        lambda cur, uid, limit=30: [{"id": 6, "market": "btc15m", "status": "failed",
                                                     "finished_at": agent.repo.now_utc()}])
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "Another angle on BTC overreaction."}, False)
    assert pid is None and rec["runs"] == [] and "cooldown" in text.lower()


def test_autopilot_research_on_an_unsupported_market_lets_the_specialist_pick(monkeypatch):
    # Prod 2026-10-26 06:10-07:40Z: every review proposed "z-score on LTC 15m", ltc15m isn't a Tau
    # market, the action was refused before any run existed, and no research started for 90 min.
    rec = _capture(monkeypatch)
    text, pid = agent.act(None, USER, {"type": "research", "market": "ltc15m",
                          "idea": "Diversify the z-score mechanism to another crypto 15m."}, True)
    assert pid is None and rec["runs"] == [(None, None, "Diversify the z-score mechanism to another crypto 15m.")]
    assert "ltc15m isn't a market tau supports" in text.lower()
    # a person asking by hand still gets told the market isn't supported
    text, _ = agent.act(None, USER, {"type": "research", "market": "ltc15m",
                        "idea": "Diversify the z-score mechanism to another crypto 15m."}, False)
    assert "can't research that market" in text and len(rec["runs"]) == 1


def test_blocked_markets_and_cooldown_line_come_from_one_read(monkeypatch):
    calls = []
    now = agent.repo.now_utc()
    runs = [{"id": 1, "market": "btc15m", "status": "stopped", "finished_at": now},
            {"id": 2, "market": "eth_daily", "status": "running", "finished_at": None},
            {"id": 3, "market": "high_ny", "status": "succeeded", "finished_at": now - agent.timedelta(days=2)}]
    monkeypatch.setattr(agent.repo, "list_runs", lambda cur, uid, limit=30: calls.append(1) or runs)
    blocked = agent._research_blocked_markets(None, 1)
    assert set(blocked) == {"btc15m", "eth_daily"} and len(calls) == 1
    line = agent._cooldown_line(None, 1)
    assert "do NOT propose" in line and "btc15m" in line and "eth_daily" in line and "high_ny" not in line


def test_the_seeded_example_session_puts_no_market_on_cooldown(monkeypatch):
    # A new account's example session (Todd's random walk on BTC 15-min, finished at sign-up) blocked
    # btc15m for 6h: the first autopilot review was told "btc15m was just researched (run #1)" and its
    # first session moved off the market it chose. The example is not research; a real run still blocks.
    rec = _capture(monkeypatch)
    now = agent.repo.now_utc()
    example = {"id": 1, "market": "btc15m", "direction": agent.repo.DEMO_DIRECTION, "status": "succeeded",
               "finished_at": now}
    monkeypatch.setattr(agent.repo, "list_runs", lambda cur, uid, limit=30: [example])
    assert agent._market_research_recent(None, 1, "btc15m") is None
    assert agent._research_blocked_markets(None, 1) == {}
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc15m",
                          "idea": "Short-term momentum after big moves."}, True)
    assert pid is None and rec["runs"] == [("btc15m", None, "Short-term momentum after big moves.")]
    assert "cooldown" not in text and "run #" not in text
    real = dict(example, id=2, direction=None)
    monkeypatch.setattr(agent.repo, "list_runs", lambda cur, uid, limit=30: [real, example])
    assert "just researched (run #2" in agent._market_research_recent(None, 1, "btc15m")


def test_research_action_allows_a_different_market(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent.repo, "list_runs",
                        lambda cur, uid, limit=30: [{"id": 7, "market": "btc15m", "status": "running",
                                                     "finished_at": None}])
    text, pid = agent.act(None, USER, {"type": "research", "market": "btc_daily",
                          "idea": "Mean-revert BTC after a sharp daily gap."}, True)
    assert pid is None and rec["runs"] == [("btc_daily", None, "Mean-revert BTC after a sharp daily gap.")]


def test_with_every_market_on_cooldown_research_rotates_to_the_stalest_ones(monkeypatch):
    # Prod 2026-10-26: all focus markets on cooldown fell back to all of them and the picker chose
    # zec15m seven runs in a row. Now: the least recently researched, never one already running.
    now = agent.repo.now_utc()
    runs = [{"id": 9, "market": "zec15m", "status": "running", "finished_at": None, "created_at": now},
            {"id": 8, "market": "zec15m", "status": "succeeded", "finished_at": now - agent.timedelta(minutes=5)},
            {"id": 7, "market": "btc15m", "status": "succeeded", "finished_at": now - agent.timedelta(minutes=20)},
            {"id": 6, "market": "eth15m", "status": "succeeded", "finished_at": now - agent.timedelta(hours=5)},
            {"id": 5, "market": "sol15m", "status": "failed", "finished_at": now - agent.timedelta(hours=3)},
            {"id": 4, "market": "btc15m", "status": "succeeded", "finished_at": now - agent.timedelta(hours=9)}]
    monkeypatch.setattr(agent.repo, "list_runs", lambda cur, uid, limit=30: runs)
    ready = ["btc15m", "eth15m", "sol15m", "xrp15m", "zec15m"]
    assert agent._least_recent_markets(None, 1, ready) == ["xrp15m", "eth15m", "sol15m"]
    assert agent._least_recent_markets(None, 1, ready, n=5) == ["xrp15m", "eth15m", "sol15m", "btc15m"]
    assert agent._least_recent_markets(None, 1, ["zec15m"]) == ["zec15m"]  # only a busy one left: keep it


def test_autopilot_crypto_research_is_bitcoin_only_and_manual_research_is_not(monkeypatch):
    # Todd 2026-10-26 14:45Z picked "Bitcoin only" for autopilot crypto research.
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent.repo, "list_runs", lambda cur, uid, limit=30: [])
    text, _ = agent.act(None, USER, {"type": "research", "market": "zec15m",
                        "idea": "Order-flow imbalance on ZEC 15m."}, True)
    assert rec["runs"][-1][0] is None and "BTC only" in text and "zec15m" in text
    agent.act(None, USER, {"type": "research", "market": "zec15m", "idea": "Order-flow imbalance on ZEC 15m."}, False)
    assert rec["runs"][-1][0] == "zec15m"  # a person asking by hand still gets the coin they named
    assert agent.autopilot_scope_ok("btc15m_tick") and agent.autopilot_scope_ok("nba_game")
    assert not agent.autopilot_scope_ok("eth_daily") and not agent.autopilot_scope_ok("sol15m")
    assert "only BTC markets" in agent._cooldown_line(None, 1)
    monkeypatch.setattr(agent, "AUTOPILOT_CRYPTO_COINS", [])
    assert agent.autopilot_scope_ok("eth_daily") and agent.autopilot_scope_line() == ""


def test_with_every_allowed_market_on_cooldown_the_review_is_told_to_research_without_one(monkeypatch):
    # Prod 2026-10-26 15:27-16:27Z: Bitcoin-only left btc15m/btc_daily, both on cooldown, and the
    # reviews started nothing for an hour.
    now = agent.repo.now_utc()
    runs = [{"id": 2, "market": "btc15m", "status": "succeeded", "finished_at": now},
            {"id": 1, "market": "btc_daily", "status": "succeeded", "finished_at": now}]
    monkeypatch.setattr(agent.repo, "list_runs", lambda cur, uid, limit=30: runs)
    monkeypatch.setattr(agent, "_researchable_keys", lambda cur: ["btc15m", "btc_daily", "eth15m"])
    monkeypatch.setattr(agent, "focus_keys", lambda cur, uid, keys: list(keys))
    line = agent._cooldown_line(None, 1)
    assert "does NOT mean stop" in line and "WITHOUT a market" in line
    monkeypatch.setattr(agent, "_researchable_keys", lambda cur: ["btc15m", "btc_daily", "btc15m_tick"])
    assert "do NOT propose these markets" in agent._cooldown_line(None, 1)  # btc15m_tick is still open
