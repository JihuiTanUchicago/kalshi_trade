"""`_copilot_context` is what the autonomous autopilot KNOWS each review. These pin the three
memory/awareness blocks added so a review stops repeating dead ends, double-launching research, or
spending blind to its budget — and that a context-read hiccup degrades gracefully instead of failing
the whole review (every block is best-effort)."""
from app import agent


def _wire(monkeypatch, **over):
    r = agent.repo
    monkeypatch.setattr(r, "list_deployments", lambda cur, uid, **k: over.get("deps", []))
    # list_strategies is called for passed (spare), failed and rejected — branch on the status kwarg.
    strat = over.get("strat", {})
    monkeypatch.setattr(r, "list_strategies", lambda cur, uid, status=None, **k: strat.get(status, []))
    monkeypatch.setattr(r, "user_risk_config", lambda cur, uid: {})
    monkeypatch.setattr(r, "user_execution_config", lambda cur, uid: {})
    monkeypatch.setattr(r, "list_runs", over.get("list_runs", lambda cur, uid, limit=6: over.get("runs", [])))
    monkeypatch.setattr(r, "paper_balance", over.get("paper_balance", lambda cur, uid: 1000.0))
    monkeypatch.setattr(r, "demo_equity", lambda cur, uid: {"equity": 500.0})
    monkeypatch.setattr(r, "credit_balance", lambda cur, uid: 42.0)


USER = {"id": 7}


def test_context_surfaces_recent_runs_dead_ends_and_budget(monkeypatch):
    _wire(monkeypatch,
          runs=[{"id": 11, "market": "btc15m", "status": "failed", "hypotheses_tried": 8,
                 "strategies_passed": 0, "prompt": "fade the longshot tails"}],
          strat={"failed": [{"title": "Tail fade v1", "market": "btc15m", "status": "failed"}],
                 "rejected": [{"title": "Momentum chase", "market": "ethdaily", "status": "rejected"}]})
    ctx = agent._copilot_context(None, USER)
    assert "run #11 on btc15m" in ctx and "fade the longshot tails" in ctx
    assert "Tail fade v1" in ctx and "Momentum chase" in ctx       # dead ends it must not re-propose
    assert "research credits $42.00 left" in ctx                   # budget awareness
    assert "paper cash $1000.00" in ctx


def test_context_degrades_when_a_memory_read_fails(monkeypatch):
    # A DB hiccup on the optional blocks must never fail the whole review — the core context still builds.
    def boom(*a, **k):
        raise RuntimeError("db dropped")
    _wire(monkeypatch, list_runs=boom, paper_balance=boom)
    ctx = agent._copilot_context(None, USER)
    assert "Autopilot is OFF." in ctx          # core block rendered
    assert "Markets you can research" in ctx    # trailing block rendered
    assert "Recent research lines" not in ctx   # failed block omitted, no crash
    assert "Account & budget" not in ctx
