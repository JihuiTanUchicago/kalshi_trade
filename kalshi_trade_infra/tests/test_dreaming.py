"""Dreaming keeps the best replay-validated policy and never makes it worse."""
from app import dreaming
from app.replay import Node
from app.llm import Usage
from app.exploration import DefaultPolicy


class _Cur:
    def execute(self, *a): pass
    def fetchone(self): return None


class _Conn:
    def cursor(self): return _Cur()
    def commit(self): pass


def _tree(n_tail=19):
    # Winner (best unseen P&L) is the FIRST node, so a policy that stops early still
    # catches it with fewer generations -> higher replay V than revealing everything.
    win = Node(score=9.0, in_sample={"pnl": 90, "trades": 10}, tested=True, oos_pnl=81.0, passed=True)
    tail = [Node(score=1.0, in_sample={"pnl": 10, "trades": 8}, tested=True, oos_pnl=1.0) for _ in range(n_tail)]
    return [win] + tail


# A policy that stops after 4 (fewer generations than the default's full sweep).
STOP_EARLY = """
def next_batch(state):
    if state["proposed"] >= 4:
        return 0
    return 4
def select_finalists(candidates, state):
    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
    return [c for c in ranked[:3] if c["in_sample"]["pnl"] > 0 and c["in_sample"]["trades"] >= 5]
"""


def _patch(monkeypatch, tree, candidates, saved):
    monkeypatch.setattr(dreaming.replay, "build_tree", lambda *a, **k: tree)
    monkeypatch.setattr(dreaming.repo, "get_policy", lambda *a, **k: None)
    monkeypatch.setattr(dreaming.repo, "set_policy",
                        lambda cur, uid, code, score: saved.update(code=code, score=score))
    monkeypatch.setattr(dreaming, "ask_json",
                        lambda model, sysmsg, msgs, check, usage: check({"policies": candidates}))


def test_evolve_adopts_a_cheaper_policy(monkeypatch):
    saved = {}
    _patch(monkeypatch, _tree(), [STOP_EARLY], saved)
    out = dreaming.evolve_policy(_Conn(), 1, "btc15m", model=None, usage=Usage(), log=lambda *a, **k: None)
    assert out is True
    assert "code" in saved and saved["score"] > 0  # the better policy was stored


def test_no_improvement_keeps_current(monkeypatch):
    saved = {}
    # Candidate is a NO-OP (never proposes) -> strictly worse -> not adopted.
    worse = "def next_batch(state):\n    return 0\ndef select_finalists(candidates, state):\n    return []"
    _patch(monkeypatch, _tree(), [worse], saved)
    out = dreaming.evolve_policy(_Conn(), 1, "btc15m", model=None, usage=Usage(), log=lambda *a, **k: None)
    assert out is False and saved == {}


def test_too_little_history_skips(monkeypatch):
    saved, called = {}, []
    monkeypatch.setattr(dreaming.replay, "build_tree", lambda *a, **k: _tree(n_tail=3))  # 4 nodes < MIN_TREE
    monkeypatch.setattr(dreaming, "ask_json", lambda *a, **k: called.append(1) or [])
    out = dreaming.evolve_policy(_Conn(), 1, "btc15m", model=None, usage=Usage(), log=lambda *a, **k: None)
    assert out is False and called == []  # no LLM call when there isn't enough history


def test_unsafe_candidate_is_ignored(monkeypatch):
    saved = {}
    _patch(monkeypatch, _tree(), ["import os\ndef next_batch(s): return 0", STOP_EARLY], saved)
    out = dreaming.evolve_policy(_Conn(), 1, "btc15m", model=None, usage=Usage(), log=lambda *a, **k: None)
    assert out is True and "code" in saved  # the unsafe one skipped, the good one adopted


def test_current_policy_defaults_when_none(monkeypatch):
    monkeypatch.setattr(dreaming.repo, "get_policy", lambda *a, **k: None)
    assert isinstance(dreaming.current_policy(_Cur(), 1), DefaultPolicy)
