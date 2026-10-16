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


def test_objective_math_is_quality_minus_cost_minus_multiple_testing():
    r = run_replay(DefaultPolicy(), TREE, budget=8, b1=0.1, b3=0.1)
    # DefaultPolicy on budget 8 reveals 8 nodes in rounds of 4,4; parallelism is
    # reported for insight but NOT part of V (a batch-width bonus only invited gaming).
    assert r.generations == 8 and r.rounds == 2 and r.parallelism == 4.0
    # V penalizes both compute (generations) and multiple testing (finalists gated).
    assert abs(r.value - (r.best_quality - 0.1 * r.generations - 0.1 * r.finalists)) < 1e-9
    assert r.best_quality == 81.0  # the winner is within the first 8 revealed
    assert r.finalists >= 1


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


def test_generalization_penalizes_order_overfitting():
    # Winner is node 0 here, so stopping early catches it on THIS order. But a past
    # run's order will not recur, so we score the mean over many orderings. Under
    # that, stopping-early usually misses the winner -> it scores WORSE than the
    # default, which reveals everything and catches the winner regardless of order.
    tree = [_node(9.0, 90, 10, tested=True, oos=81.0, passed=True)] + \
           [_node(0.5, 10, 8, tested=True, oos=1.0) for _ in range(23)]

    class StopAt4(ExplorationPolicy):
        def next_batch(self, s): return Batch(4 if s.proposed < 4 else 0)
        def select_finalists(self, c, s): return DefaultPolicy().select_finalists(c, s)

    default_v = replay.replay_generalization(DefaultPolicy(), tree, budget=len(tree))
    stop_v = replay.replay_generalization(StopAt4(), tree, budget=len(tree))
    # On the single recorded order, StopAt4 looks better (cheaper, still catches the winner)...
    assert run_replay(StopAt4(), tree, budget=len(tree)).value > run_replay(DefaultPolicy(), tree, budget=len(tree)).value
    # ...but averaged over orderings it is much worse, because the winner usually lands late.
    assert stop_v < default_v


def test_generalization_rewards_a_genuine_selection_win():
    # The out-of-sample winner has a MEDIOCRE in-sample score, so the default's
    # rank-by-score top-k misses it. A policy that tests every profitable, sturdy
    # candidate catches it -> higher score, and (revealing everything) regardless
    # of order. This is the real, generalizable lever: selection, not stopping.
    decoys = [_node(9.0 - i * 0.1, 80, 10, tested=True, oos=-2.0) for i in range(8)]
    winner = _node(0.2, 15, 12, tested=True, oos=90.0, passed=True)
    tree = decoys + [winner] + [_node(0.1, 5, 6, tested=True, oos=0.5) for _ in range(6)]

    class SelectProfitable(ExplorationPolicy):
        def next_batch(self, s): return Batch(min(4, s.budget - s.proposed))
        def select_finalists(self, c, s):
            return [x for x in c if x["in_sample"]["pnl"] > 0 and x["in_sample"]["trades"] >= 5]

    default = replay.replay(DefaultPolicy(), tree, budget=len(tree))
    assert default.best_quality < 90.0  # default misses the real winner
    default_v = replay.replay_generalization(DefaultPolicy(), tree, budget=len(tree))
    better_v = replay.replay_generalization(SelectProfitable(), tree, budget=len(tree))
    assert better_v > default_v


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
