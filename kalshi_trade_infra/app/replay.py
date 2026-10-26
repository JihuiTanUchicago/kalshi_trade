"""Replay simulator — the Dream-RSI "world" (Tau-RSI P2).

A completed research run leaves a *discovery tree*: the hypotheses it proposed,
each with its recorded in-sample score and (for the few that were gated) its
out-of-sample outcome, plus the parent->child LINEAGE (a refinement node points
back at the strategy it dug deeper on — `app_strategies.parent_id`). Because every
outcome is already stored, we can score an alternative exploration policy by
REPLAYING it over the recorded tree — no new LLM calls and no new backtests. That
is the paper's key move: it turns expensive online policy evaluation into cheap
offline reading.

A replay reveals recorded nodes as the policy sizes each round (`next_batch`,
capped by the worker count W), traversing real branches in recorded parent->child
order — a node is never revealed before its parent, exactly as a refinement can
only exist after the hypothesis it refines. The policy then picks finalists, and
we score the trajectory with the paper's objective (Eq. 1):

    V = best_quality  -  b1 * generations  +  b2 * parallelism  -  b3 * finalists

where best_quality is the best out-of-sample P&L among finalists the policy
selected that were *actually tested* in the record (we can only credit outcomes
we have), generations (N) is how many nodes it revealed (compute cost), parallelism
is N / rounds (the paper's average attempts-per-round — favouring policies that
batch useful continuations rather than run them sequentially), and finalists is how
many hypotheses it sent to the unseen-data gate (a multiple-testing penalty —
every extra out-of-sample test is another chance to crown a fluke).

RIGOR / anti-gaming on parallelism (b2). The paper's parallelism reward is honest
when wide batches are genuinely outcome-neutral (independent BRANCHES explored on
parallel workers). In OUR online loop a round's "width" is the intra-run proposal
count, where wider = each round learns less from the previous one — a real cost the
replay CANNOT see, so a positive b2 would let a wide-but-less-adaptive policy
out-score a better one (the reason a batch-width bonus was removed before). The term
is therefore implemented and tested but DEFAULTS OFF (b2=0); turning it on is gated
on the online hook that makes parallel-branch exploration a real, outcome-neutral
executable lever (see dreaming.PARALLELISM and the roadmap). W (worker cap) bounds
the term either way, matching the paper's feasible batch set A(T;W).

Crucially, a single pass scores one FIXED branch order, and the order of a past run
does not recur: a policy that "stops early" scores well only when that recording
happened to surface the winner's branch early, which will not generalize to the
user's NEXT run. So the dreaming loop scores policies with `replay_generalization`,
the mean V over many shuffled BRANCH orderings (lineage within a branch preserved)
— rewarding policies robust to *where* the winner lands, not ones that memorized
this recording.

This module is pure and side-effect-free: it reads a tree of `Node`s and an
`ExplorationPolicy`, and never touches the LLM, backtester, DB, or network. The
policy is handed only in-sample views (score + in_sample) — never a node's
out-of-sample / holdout numbers (Leak 5).
"""
from __future__ import annotations

import random
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app import backtest
from app import repository as repo
from app import research_repository as rr
from app.research.exploration import ExplorationPolicy, PolicyState

# Objective coefficients. Tunable; defaults keep the penalties small relative to a
# dollar of out-of-sample P&L so that *finding a better strategy* dominates, with
# ties broken toward fewer generations and fewer out-of-sample tests.
DEFAULT_COST = 0.10          # b1: penalty per hypothesis generated (compute)
DEFAULT_FINALIST_PENALTY = 0.10   # b3: penalty per finalist gated (multiple-testing discipline)
DEFAULT_PARALLELISM = 0.0    # b2: parallelism reward (Eq. 1). OFF by default — see module docstring.
DEFAULT_WORKERS = 8          # W: max attempts per round (bounds parallelism; = feasible batch A(T;W))
GENERALIZATION_TRIALS = 32   # branch orderings averaged when scoring a policy for generalization


@dataclass(frozen=True)
class Node:
    """One recorded hypothesis in the discovery tree."""
    score: float            # in-sample score the policy ranks on
    in_sample: dict         # {"pnl", "trades"} — for the policy's finalist filter
    tested: bool            # was this gated on unseen data (so oos_pnl is real)?
    oos_pnl: float = 0.0    # recorded out-of-sample P&L (meaningful only if tested)
    passed: bool = False    # cleared every gate
    holdout: bool = False   # tripwire: the policy optimizer must NEVER see locked-holdout
                            # outcomes (Leak 5). build_tree sources VALIDATION only and leaves
                            # this False; dreaming.evolve_policy asserts none is True.
    node_id: Optional[int] = None    # strategy id — the lineage key (None = no recorded id)
    parent_id: Optional[int] = None  # the node this one refined (None = a root hypothesis)


@dataclass(frozen=True)
class ReplayResult:
    value: float            # V — the objective
    generations: int        # hypotheses revealed (cost, N)
    rounds: int             # exploration rounds taken (k*)
    parallelism: float      # average attempts per round, N/rounds (the paper's parallelism term)
    best_quality: float     # best OOS P&L among selected, tested finalists
    finalists: int          # hypotheses sent to the unseen-data gate (multiple-testing cost)
    passed: int             # selected finalists that passed


def build_tree(cur, user_id: int, market: str, limit: int = 500) -> List[Node]:
    """Load a user's recorded discovery tree for a market as replay `Node`s. The only I/O
    bridge here; `replay()` itself is pure.

    The `oos_pnl` signal is the VALIDATION pnl the Statistical Gatekeeper recorded in the
    ledger (via research_repository.experiment_records_for_replay), NOT the old reused 70/30
    OOS — so the policy optimizer is scored on gatekeeper-held validation outcomes and NEVER on
    the locked holdout (closes Leaks 2 & 5). Every Node is validation-sourced, so `holdout`
    stays False. Each node carries its strategy id + parent_id so `replay` can traverse real
    branches (a refinement points back at the strategy it dug deeper on). Falls back to the
    legacy strategy_records tree for users/markets with no ledger rows yet (pre-gatekeeper
    history), so dreaming still works during the cutover."""
    recs = rr.experiment_records_for_replay(cur, user_id, market)
    if recs:
        nodes: List[Node] = []
        for r in recs:
            pnl = float(r.get("net_pnl") or 0.0)
            ins = {"pnl": pnl, "trades": int(r.get("n_trades") or 0)}
            nodes.append(Node(
                score=backtest.score(ins), in_sample=ins, tested=True, oos_pnl=pnl,
                passed=r.get("classification") == "statistically_supported", holdout=False,
                node_id=_as_int(r.get("strategy_id")), parent_id=_as_int(r.get("parent_id")),
            ))
        return nodes
    nodes = []
    for r in repo.strategy_records(cur, user_id, market, limit):
        ins = r["in_sample"]
        nodes.append(Node(
            score=backtest.score(ins) if ins else 0.0,
            in_sample=ins, tested=r["tested"], oos_pnl=r["oos_pnl"], passed=r["passed"],
            node_id=_as_int(r.get("id")), parent_id=_as_int(r.get("parent_id")),
        ))
    return nodes


def _as_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _structure(tree: List[Node]) -> Tuple[List[Node], Dict[int, List[Node]]]:
    """Split a flat node list into (roots, children-by-parent-id), preserving recorded order.
    A node whose parent_id is unknown in this window (None, or a parent outside the loaded
    set) is a root — so a flat list with no lineage is simply all-roots, and `replay` reveals
    it in list order exactly as the pre-tree version did."""
    index = {n.node_id for n in tree if n.node_id is not None}
    children: Dict[int, List[Node]] = defaultdict(list)
    roots: List[Node] = []
    for n in tree:
        if n.parent_id is not None and n.parent_id in index:
            children[n.parent_id].append(n)
        else:
            roots.append(n)
    return roots, children


def replay(policy: ExplorationPolicy, tree: List[Node], budget: int,
           b1: float = DEFAULT_COST, b3: float = DEFAULT_FINALIST_PENALTY,
           b2: float = DEFAULT_PARALLELISM, workers: int = DEFAULT_WORKERS) -> ReplayResult:
    """Replay `policy` over the recorded `tree` (one fixed branch order) and score it.

    The policy sizes each round (capped at `workers` = W, the feasible batch A(T;W)); the
    replay reveals that many recorded nodes, always parent-before-child along the lineage
    (a refinement only becomes eligible once the node it refines has been revealed). Revealing
    stops when the policy stops or the tree is exhausted. The policy then selects finalists
    from the revealed nodes — handed only in-sample views (score + in_sample), NEVER a node's
    out-of-sample / holdout numbers — and we tally the objective. No LLM/backtest runs.

    This is a single ordering; `replay_generalization` averages it over many branch orderings,
    which is what the dreaming loop scores on (see module docstring). `next_batch` is given only
    {proposed, budget, round} — the same state the live harness provides (`agent._explore_and_gate`),
    so a scored policy behaves in a real run exactly as it was scored (no train/serve skew)."""
    roots, children = _structure(tree)
    revealed: List[Node] = []
    batch_sizes: List[int] = []
    ready: deque = deque(roots)                     # nodes eligible to reveal (parent already revealed)
    round_no = 0
    while ready:
        round_no += 1
        state = PolicyState(proposed=len(revealed), budget=budget, round=round_no)
        want = min(policy.next_batch(state).width, workers)  # W cap: at most `workers` per round
        if want <= 0:
            break                                   # policy stopped
        taken = 0
        while ready and taken < want:
            node = ready.popleft()
            revealed.append(node)
            if node.node_id is not None:
                ready.extend(children.get(node.node_id, ()))  # its refinements become eligible
            taken += 1
        if taken == 0:
            break                                   # nothing left to reveal
        batch_sizes.append(taken)

    # Leak-safe views: the policy sees ONLY in-sample score + metrics, never oos/holdout/the Node.
    views = [{"score": n.score, "in_sample": n.in_sample} for n in revealed]
    by_id = {id(v): n for v, n in zip(views, revealed)}
    end_state = PolicyState(proposed=len(revealed), budget=budget, round=round_no)
    finalists = [by_id[id(v)] for v in policy.select_finalists(views, end_state) if id(v) in by_id]

    tested_finalists = [n for n in finalists if n.tested]
    best_quality = max((n.oos_pnl for n in tested_finalists), default=0.0)
    generations = len(revealed)
    parallelism = (sum(batch_sizes) / len(batch_sizes)) if batch_sizes else 0.0
    value = best_quality - b1 * generations + b2 * parallelism - b3 * len(finalists)
    return ReplayResult(
        value=value, generations=generations, rounds=len(batch_sizes),
        parallelism=parallelism, best_quality=best_quality,
        finalists=len(finalists), passed=sum(1 for n in finalists if n.passed),
    )


def replay_generalization(policy: ExplorationPolicy, tree: List[Node], budget: int,
                          trials: int = GENERALIZATION_TRIALS, seed: int = 0,
                          b1: float = DEFAULT_COST, b3: float = DEFAULT_FINALIST_PENALTY,
                          b2: float = DEFAULT_PARALLELISM, workers: int = DEFAULT_WORKERS) -> float:
    """Mean V of `policy` over `trials` orderings of `tree` (the recorded order plus seeded
    shuffles). Shuffling the flat list reshuffles which BRANCH (and which sibling) surfaces
    first, while `replay` still re-derives the parent->child lineage and never reveals a child
    before its parent — so the recorded order of a past run (which will not recur) is averaged
    out, but the impossible "refinement before the thing it refined" order never occurs. A
    policy that only exploits the recorded order (e.g. stopping early because this recording's
    winner happened to appear early) scores well on a single replay but poorly here. Averaging
    therefore rewards policies robust to where the winner lands, i.e. ones that improve the
    user's FUTURE research, not just the replay number. Deterministic given `seed`."""
    rnd = random.Random(seed)
    total = 0.0
    for i in range(max(1, trials)):
        order = tree if i == 0 else _shuffled(tree, rnd)
        total += replay(policy, order, budget, b1=b1, b3=b3, b2=b2, workers=workers).value
    return total / max(1, trials)


def _shuffled(tree: List[Node], rnd: random.Random) -> List[Node]:
    out = list(tree)
    rnd.shuffle(out)
    return out
