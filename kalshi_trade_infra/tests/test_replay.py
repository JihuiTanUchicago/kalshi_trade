"""The replay simulator scores an exploration policy over a recorded discovery
tree with no new LLM/backtest calls: it reveals recorded nodes as the policy
sizes rounds, credits only outcomes that were actually recorded, and rewards
reaching good strategies with fewer generations."""
from app import replay
from app.replay import Node, replay as run_replay
from app.exploration import DefaultPolicy, ExplorationPolicy, PolicyState, Batch


def _node(score, pnl, trades, tested=True, oos=0.0, passed=False):
    return Node(score=score, in_sample={"pnl": pnl, "trades": trades}, tested=tested, oos_pnl=oos, passed=passed)


# A tree where the single best (out-of-sample) strategy is the 2nd recorded node.
TREE = [
    _node(5.0, 40, 10, tested=True, oos=12.0, passed=True),
    _node(9.0, 90, 10, tested=True, oos=81.0, passed=True),   # the winner
    _node(1.0, -5, 20, tested=True, oos=-9.0, passed=False),
    _node(2.0, 80, 3,  tested=False),                          # too few trades -> never gated
] + [_node(0.5, 10, 8, tested=True, oos=1.0) for _ in range(20)]


def test_objective_math_is_quality_minus_cost_plus_parallelism():
    r = run_replay(DefaultPolicy(), TREE, budget=8, b1=0.1, b2=0.1)
    # DefaultPolicy on budget 8 reveals 8 nodes in rounds of 4,4 -> parallelism 4.
    assert r.generations == 8 and r.rounds == 2 and r.parallelism == 4.0
    assert abs(r.value - (r.best_quality - 0.1 * 8 + 0.1 * 4.0)) < 1e-9
    assert r.best_quality == 81.0  # the winner is within the first 8 revealed


def test_reaching_the_winner_cheaper_scores_higher():
    # Policy A stops after 4 (still catches the winner at index 1); Policy B reveals all 24.
    class StopAt4(ExplorationPolicy):
        def next_batch(self, s): return Batch(4 if s.proposed < 4 else 0)
        def select_finalists(self, c, s): return DefaultPolicy().select_finalists(c, s)
    class RevealAll(ExplorationPolicy):
        def next_batch(self, s): return Batch(4)
        def select_finalists(self, c, s): return DefaultPolicy().select_finalists(c, s)
    a = run_replay(StopAt4(), TREE, budget=999)
    b = run_replay(RevealAll(), TREE, budget=999)
    assert a.best_quality == b.best_quality == 81.0   # both find the winner
    assert a.generations == 4 and b.generations == len(TREE)
    assert a.value > b.value                            # fewer generations -> better score


def test_reveal_stops_when_tree_exhausted():
    small = TREE[:3]
    r = run_replay(DefaultPolicy(), small, budget=100)
    assert r.generations == 3  # can't reveal more than the recorded tree holds


def test_untested_finalists_do_not_credit_quality():
    # Only an untested node is selectable -> quality 0 (we can't credit an unrecorded outcome).
    tree = [_node(9.0, 100, 10, tested=False)]
    r = run_replay(DefaultPolicy(), tree, budget=4)
    assert r.best_quality == 0.0 and r.passed == 0


class _FakeCur:
    def __init__(self, rows): self._rows = rows
    def execute(self, *a): pass
    def fetchall(self): return self._rows


def test_build_tree_maps_records_to_nodes():
    import json
    rows = [
        {"status": "passed",   "result_json": json.dumps({"in_sample": {"pnl": 90, "trades": 10}, "out_of_sample": {"pnl": 81}})},
        {"status": "failed",   "result_json": json.dumps({"in_sample": {"pnl": 50, "trades": 12}, "out_of_sample": {"pnl": -3}})},
        {"status": "rejected", "result_json": json.dumps({"in_sample": {"pnl": 80, "trades": 3}})},  # never gated
    ]
    tree = replay.build_tree(_FakeCur(rows), user_id=1, market="btc15m")
    assert len(tree) == 3
    assert tree[0].tested and tree[0].oos_pnl == 81 and tree[0].passed
    assert tree[1].tested and tree[1].oos_pnl == -3 and not tree[1].passed
    assert not tree[2].tested and tree[2].oos_pnl == 0.0 and not tree[2].passed
