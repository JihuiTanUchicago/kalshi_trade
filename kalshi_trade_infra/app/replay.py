"""Replay simulator — the Dream-RSI "world" (Tau-RSI P2).

A completed research run leaves a *discovery tree*: the hypotheses it proposed,
each with its recorded in-sample score and (for the few that were gated) its
out-of-sample outcome. Because every outcome is already stored, we can score an
alternative exploration policy by REPLAYING it over the recorded nodes — no new
LLM calls and no new backtests. That is the paper's key move: it turns expensive
online policy evaluation into cheap offline reading.

A replay reveals recorded nodes in order as the policy sizes each round
(`next_batch`), lets the policy pick finalists, and scores the trajectory with
the Dream-RSI objective

    V = best_quality  -  b1 * generations  +  b2 * parallelism

where best_quality is the best out-of-sample P&L among finalists the policy
selected that were *actually tested* in the record (we can only credit outcomes
we have), generations is how many nodes it revealed (cost), and parallelism is
the average batch width (rewards batching useful work over sequential nibbling).

This module is pure and side-effect-free: it reads a tree of `Node`s and an
`ExplorationPolicy`, and never touches the LLM, backtester, DB, or network.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app import backtest
from app import repository as repo
from app.exploration import ExplorationPolicy, PolicyState

# Objective coefficients. Tunable; defaults keep cost/parallelism small relative
# to a dollar of out-of-sample P&L so that *finding a better strategy* dominates,
# with ties broken toward fewer generations and more batching.
DEFAULT_COST = 0.10          # b1: penalty per hypothesis generated
DEFAULT_PARALLELISM = 0.10   # b2: bonus per unit of average batch width


@dataclass(frozen=True)
class Node:
    """One recorded hypothesis in the discovery tree."""
    score: float            # in-sample score the policy ranks on
    in_sample: dict         # {"pnl", "trades"} — for the policy's finalist filter
    tested: bool            # was this gated on unseen data (so oos_pnl is real)?
    oos_pnl: float = 0.0    # recorded out-of-sample P&L (meaningful only if tested)
    passed: bool = False    # cleared every gate


@dataclass(frozen=True)
class ReplayResult:
    value: float            # V — the objective
    generations: int        # hypotheses revealed (cost)
    rounds: int             # exploration rounds taken
    parallelism: float      # average batch width
    best_quality: float     # best OOS P&L among selected, tested finalists
    passed: int             # selected finalists that passed


def build_tree(cur, user_id: int, market: str, limit: int = 500) -> List[Node]:
    """Load a user's recorded discovery tree for a market as replay `Node`s
    (in creation order). The only I/O bridge here; `replay()` itself is pure."""
    nodes: List[Node] = []
    for r in repo.strategy_records(cur, user_id, market, limit):
        ins = r["in_sample"]
        nodes.append(Node(
            score=backtest.score(ins) if ins else 0.0,
            in_sample=ins, tested=r["tested"], oos_pnl=r["oos_pnl"], passed=r["passed"],
        ))
    return nodes


def replay(policy: ExplorationPolicy, tree: List[Node], budget: int,
           b1: float = DEFAULT_COST, b2: float = DEFAULT_PARALLELISM) -> ReplayResult:
    """Replay `policy` over the recorded `tree` and score its trajectory.

    The policy sizes each round; the replay reveals that many recorded nodes in
    order (a policy cannot generate outcomes beyond what was recorded — revealing
    stops when the tree is exhausted). The policy then selects finalists from the
    revealed nodes, and we tally the Dream-RSI objective. No LLM/backtest runs."""
    revealed: List[Node] = []
    batch_sizes: List[int] = []
    round_no = 0
    while True:
        round_no += 1
        state = PolicyState(proposed=len(revealed), budget=budget, round=round_no,
                            history=tuple({"score": n.score, "in_sample": n.in_sample} for n in revealed))
        want = policy.next_batch(state).width
        if want <= 0:
            break                                   # policy stopped
        batch = tree[len(revealed):len(revealed) + want]
        if not batch:
            break                                   # tree exhausted — nothing left to reveal
        revealed.extend(batch)
        batch_sizes.append(len(batch))

    candidates = [{"score": n.score, "in_sample": n.in_sample, "_node": n} for n in revealed]
    end_state = PolicyState(proposed=len(revealed), budget=budget, round=round_no)
    finalists = [c["_node"] for c in policy.select_finalists(candidates, end_state)]

    tested_finalists = [n for n in finalists if n.tested]
    best_quality = max((n.oos_pnl for n in tested_finalists), default=0.0)
    generations = len(revealed)
    parallelism = (sum(batch_sizes) / len(batch_sizes)) if batch_sizes else 0.0
    value = best_quality - b1 * generations + b2 * parallelism
    return ReplayResult(
        value=value, generations=generations, rounds=len(batch_sizes),
        parallelism=parallelism, best_quality=best_quality,
        passed=sum(1 for n in finalists if n.passed),
    )
