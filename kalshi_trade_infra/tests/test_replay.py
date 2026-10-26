"""The replay simulator scores an exploration policy over a recorded discovery
tree with no new LLM/backtest calls: it reveals recorded nodes as the policy
sizes rounds, credits only outcomes that were actually recorded, and rewards
reaching good strategies with fewer generations."""
from app import replay
from app.replay import Node, replay as run_replay
from app.research.exploration import DefaultPolicy, ExplorationPolicy, PolicyState, Batch


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
    """Routes the two queries build_tree can make: the gatekeeper's validation-records query
    (joins app_experiments) vs the legacy strategy_records fallback (app_strategies)."""

    def __init__(self, exp_rows, strat_rows): self._exp, self._strat, self._last = exp_rows, strat_rows, []
    def execute(self, sql, *a): self._last = self._exp if "app_experiments" in sql else self._strat
    def fetchall(self): return self._last


def test_build_tree_prefers_gatekeeper_validation_records():
    # oos_pnl is now the VALIDATION pnl the gatekeeper recorded (not the old reused OOS), so the
    # policy optimizer is scored on gatekeeper-held outcomes; holdout is never a source.
    exp_rows = [
        {"classification": "statistically_supported", "n_trades": 30, "net_pnl": 81.0},
        {"classification": "inconclusive", "n_trades": 12, "net_pnl": -3.0},
    ]
    tree = replay.build_tree(_FakeCur(exp_rows, []), user_id=1, market="btc15m")
    assert len(tree) == 2
    assert tree[0].tested and tree[0].oos_pnl == 81.0 and tree[0].passed and not tree[0].holdout
    assert tree[1].tested and tree[1].oos_pnl == -3.0 and not tree[1].passed and not tree[1].holdout


def test_build_tree_falls_back_to_legacy_records_when_no_ledger():
    import json
    strat_rows = [
        {"status": "passed",   "result_json": json.dumps({"in_sample": {"pnl": 90, "trades": 10}, "out_of_sample": {"pnl": 81}})},
        {"status": "rejected", "result_json": json.dumps({"in_sample": {"pnl": 80, "trades": 3}})},  # never gated
    ]
    tree = replay.build_tree(_FakeCur([], strat_rows), user_id=1, market="btc15m")
    assert len(tree) == 2
    assert tree[0].tested and tree[0].oos_pnl == 81 and tree[0].passed
    assert not tree[1].tested and tree[1].oos_pnl == 0.0


# --- real discovery tree: lineage, branch traversal, parallelism, leak-safety -------------

import random as _random


def _lin(node_id, parent_id, score, oos=0.0, tested=True):
    # pnl is score*10 (unique per node here) so a test can trace reveal order by pnl.
    return Node(score=score, in_sample={"pnl": score * 10, "trades": 10},
                tested=tested, oos_pnl=oos, passed=False, node_id=node_id, parent_id=parent_id)


def test_build_tree_records_lineage_from_experiment_records():
    # strategy_id/parent_id come through so the replay can traverse real branches.
    exp_rows = [
        {"strategy_id": 1, "parent_id": None, "classification": "statistically_supported", "n_trades": 30, "net_pnl": 81.0},
        {"strategy_id": 7, "parent_id": 1, "classification": "inconclusive", "n_trades": 12, "net_pnl": -3.0},
    ]
    tree = replay.build_tree(_FakeCur(exp_rows, []), user_id=1, market="btc15m")
    assert [n.node_id for n in tree] == [1, 7]
    assert [n.parent_id for n in tree] == [None, 1]
    roots, children = replay._structure(tree)
    assert [n.node_id for n in roots] == [1]
    assert [n.node_id for n in children[1]] == [7]


def test_build_tree_records_lineage_from_legacy_records():
    import json
    strat_rows = [
        {"id": 5, "parent_id": None, "status": "passed",
         "result_json": json.dumps({"in_sample": {"pnl": 90, "trades": 10}, "out_of_sample": {"pnl": 81}})},
        {"id": 6, "parent_id": 5, "status": "rejected",
         "result_json": json.dumps({"in_sample": {"pnl": 10, "trades": 7}})},
    ]
    tree = replay.build_tree(_FakeCur([], strat_rows), user_id=1, market="btc15m")
    assert [n.node_id for n in tree] == [5, 6]
    assert [n.parent_id for n in tree] == [None, 5]


def test_replay_traverses_branches_parent_before_child():
    # root 1 -> 11 -> 111 ; independent root 2. A refinement is only eligible once the
    # node it refines has been revealed, so 11 reveals after 1 and 111 after 11.
    tree = [_lin(1, None, 1.0), _lin(11, 1, 2.0), _lin(111, 11, 3.0), _lin(2, None, 4.0)]
    seen = {}

    class Spy(ExplorationPolicy):
        def next_batch(self, s): return Batch(1)
        def select_finalists(self, c, s):
            seen["pnls"] = [x["in_sample"]["pnl"] for x in c]
            return []

    r = run_replay(Spy(), tree, budget=99)
    assert r.generations == 4                      # whole tree revealed
    pos = {pnl: i for i, pnl in enumerate(seen["pnls"])}
    assert pos[10] < pos[20] < pos[30]             # 1 before 11 before 111


def test_generalization_never_reveals_a_child_before_its_parent():
    # A single-root chain 0->1->...->9: however the flat list is shuffled, the lineage
    # forces reveal order 0,1,...,9 (a child only becomes eligible after its parent).
    tree = [_lin(i, (i - 1 if i > 0 else None), float(i)) for i in range(10)]
    seen = {}

    class Spy(ExplorationPolicy):
        def next_batch(self, s): return Batch(1)
        def select_finalists(self, c, s):
            seen["pnls"] = [x["in_sample"]["pnl"] for x in c]
            return []

    for s in range(20):
        order = list(tree)
        _random.Random(s).shuffle(order)
        run_replay(Spy(), order, budget=99)
        assert seen["pnls"] == [i * 10 for i in range(10)]


def test_parallelism_term_and_worker_cap():
    # Eq. 1: V = best_quality - b1*N + b2*(N/rounds) - b3*finalists, and width is capped at W.
    tree = [_node(1.0, 10, 8, tested=True, oos=1.0) for _ in range(12)]

    class Wide(ExplorationPolicy):
        def next_batch(self, s): return Batch(100)            # asks huge; W caps it
        def select_finalists(self, c, s): return DefaultPolicy().select_finalists(c, s)

    r = run_replay(Wide(), tree, budget=99, b2=0.5, workers=4)
    assert r.generations == 12 and r.rounds == 3 and r.parallelism == 4.0   # 12/4 = 3 rounds of 4
    assert abs(r.value - (r.best_quality - 0.1 * 12 + 0.5 * 4.0 - 0.1 * r.finalists)) < 1e-9
    # Default b2=0.0 drops the parallelism term entirely (kept inert online — anti-gaming).
    r0 = run_replay(Wide(), tree, budget=99, workers=4)
    assert abs(r0.value - (r0.best_quality - 0.1 * 12 - 0.1 * r0.finalists)) < 1e-9


def test_policy_never_sees_held_out_numbers_or_the_node():
    # Leak 5 / train-serve: the policy is handed ONLY in-sample views (score + in_sample),
    # never a node's oos_pnl / holdout / the Node object it could read them off.
    tree = [_node(5.0, 40, 10, tested=True, oos=99.0, passed=True)] + \
           [_node(1.0, 10, 8, tested=True, oos=3.0) for _ in range(6)]
    seen = {}

    class Spy(ExplorationPolicy):
        def next_batch(self, s): return Batch(min(4, s.budget - s.proposed))
        def select_finalists(self, c, s):
            seen["keys"] = set().union(*[set(x.keys()) for x in c]) if c else set()
            seen["node_leak"] = any(isinstance(v, Node) for x in c for v in x.values())
            return []

    run_replay(Spy(), tree, budget=len(tree))
    assert seen["keys"] == {"score", "in_sample"}   # no oos_pnl, no holdout, no _node
    assert seen["node_leak"] is False
