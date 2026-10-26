"""Dreaming keeps the best replay-validated policy and never makes it worse."""
from app.research import dreaming
from app.replay import Node
from app.llm import Usage
from app.research.exploration import DefaultPolicy


class _Cur:
    def execute(self, *a): pass
    def fetchone(self): return None


class _Conn:
    def cursor(self): return _Cur()
    def commit(self): pass


def _tree(n_tail=15):
    # A SELECTION-GAP tree: the real out-of-sample winner ($90) has a mediocre
    # in-sample score, so the default's rank-by-score top-k never tests it and is
    # stuck crediting a weak decoy ($5). Better *selection* is the generalizable win.
    decoys = [Node(score=9.0 - i * 0.1, in_sample={"pnl": 80, "trades": 10}, tested=True, oos_pnl=5.0)
              for i in range(5)]
    winner = Node(score=0.2, in_sample={"pnl": 15, "trades": 12}, tested=True, oos_pnl=90.0, passed=True)
    tail = [Node(score=0.1, in_sample={"pnl": 5, "trades": 6}, tested=True, oos_pnl=0.5) for _ in range(n_tail)]
    return decoys + [winner] + tail


# A genuinely better policy: it reveals the budget (stopping early does not help a
# score averaged over orderings) and tests every profitable, sturdy candidate, so
# it catches the real winner the default misses -- an order-invariant improvement.
SELECT_PROFITABLE = """
def next_batch(state):
    return min(4, state["budget"] - state["proposed"])
def select_finalists(candidates, state):
    return [c for c in candidates if c["in_sample"]["pnl"] > 0 and c["in_sample"]["trades"] >= 5]
"""

# A policy that stops after 4: it would win on the ONE recorded order if the winner
# sat early, but it overfits that order and loses on the averaged score.
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
                        lambda cur, uid, code, score, summary=None, base_score=None: saved.update(code=code, score=score, summary=summary))
    monkeypatch.setattr(dreaming, "ask_json",
                        lambda model, sysmsg, msgs, check, usage: check({"policies": candidates}))


def test_evolve_adopts_a_generalizable_selection_policy(monkeypatch):
    saved = {}
    _patch(monkeypatch, _tree(), [SELECT_PROFITABLE], saved)
    out = dreaming.evolve_policy(_Conn(), 1, "btc15m", model=None, usage=Usage(), log=lambda *a, **k: None)
    assert out is True
    assert "code" in saved and saved["score"] > 0  # the better selection policy was stored


def test_order_overfit_policy_is_not_adopted(monkeypatch):
    # A tree where the default ALREADY catches the winner (high in-sample score),
    # so there is no selection gap. STOP_EARLY beats the default on this single
    # recorded order (winner sits first) but loses on the averaged score, so the
    # monotonic loop must NOT adopt it.
    win = Node(score=9.0, in_sample={"pnl": 90, "trades": 10}, tested=True, oos_pnl=81.0, passed=True)
    tail = [Node(score=1.0, in_sample={"pnl": 10, "trades": 8}, tested=True, oos_pnl=1.0) for _ in range(23)]
    saved = {}
    _patch(monkeypatch, [win] + tail, [STOP_EARLY], saved)
    out = dreaming.evolve_policy(_Conn(), 1, "btc15m", model=None, usage=Usage(), log=lambda *a, **k: None)
    assert out is False and saved == {}


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
    _patch(monkeypatch, _tree(), ["import os\ndef next_batch(s): return 0", SELECT_PROFITABLE], saved)
    out = dreaming.evolve_policy(_Conn(), 1, "btc15m", model=None, usage=Usage(), log=lambda *a, **k: None)
    assert out is True and "code" in saved  # the unsafe one skipped, the good one adopted


def test_current_policy_defaults_when_none(monkeypatch):
    monkeypatch.setattr(dreaming.repo, "get_policy", lambda *a, **k: None)
    assert isinstance(dreaming.current_policy(_Cur(), 1), DefaultPolicy)
