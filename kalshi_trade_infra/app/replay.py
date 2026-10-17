"""Replay simulator — the Dream-RSI "world" (Tau-RSI P2).

A completed research run leaves a *discovery tree*: the hypotheses it proposed,
each with its recorded in-sample score and (for the few that were gated) its
out-of-sample outcome. Because every outcome is already stored, we can score an
alternative exploration policy by REPLAYING it over the recorded nodes — no new
LLM calls and no new backtests. That is the paper's key move: it turns expensive
online policy evaluation into cheap offline reading.

A replay reveals recorded nodes in order as the policy sizes each round
(`next_batch`), lets the policy pick finalists, and scores the trajectory with
the objective

    V = best_quality  -  b1 * generations  -  b3 * finalists

where best_quality is the best out-of-sample P&L among finalists the policy
selected that were *actually tested* in the record (we can only credit outcomes
we have), generations is how many nodes it revealed (compute cost), and finalists
is how many hypotheses it sent to the unseen-data gate — a multiple-testing
penalty, because every extra out-of-sample test is another chance to crown a
fluke (the research brief's "the best of fifty is weaker evidence than the only
one"). Both penalties reward things the replay can actually measure the
consequences of; a batch-width *bonus* was removed because the recorded outcomes
do not depend on batch size, so rewarding wide batches only invited gaming.

Crucially, a single pass scores one FIXED node order, and the order of a past run
does not recur: a policy that "stops early" scores well only when that recording
happened to surface the winner early, which will not generalize to the user's
NEXT run. So the dreaming loop scores policies with `replay_generalization`, the
mean V over many shuffled orderings — which rewards policies robust to *where*
the winner lands, not ones that memorized this recording.

This module is pure and side-effect-free: it reads a tree of `Node`s and an
`ExplorationPolicy`, and never touches the LLM, backtester, DB, or network.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

from app import backtest
from app import repository as repo
from app import research_repository as rr
from app.exploration import ExplorationPolicy, PolicyState

# Objective coefficients. Tunable; defaults keep both penalties small relative to
# a dollar of out-of-sample P&L so that *finding a better strategy* dominates,
# with ties broken toward fewer generations and fewer out-of-sample tests.
DEFAULT_COST = 0.10          # b1: penalty per hypothesis generated (compute)
DEFAULT_FINALIST_PENALTY = 0.10   # b3: penalty per finalist gated (multiple-testing discipline)
GENERALIZATION_TRIALS = 32   # orderings averaged when scoring a policy for generalization


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


@dataclass(frozen=True)
class ReplayResult:
    value: float            # V — the objective
    generations: int        # hypotheses revealed (cost)
    rounds: int             # exploration rounds taken
    parallelism: float      # average batch width (reported for insight; not in V)
    best_quality: float     # best OOS P&L among selected, tested finalists
    finalists: int          # hypotheses sent to the unseen-data gate (multiple-testing cost)
    passed: int             # selected finalists that passed


def build_tree(cur, user_id: int, market: str, limit: int = 500) -> List[Node]:
    """Load a user's recorded discovery tree for a market as replay `Node`s. The only I/O
    bridge here; `replay()` itself is pure.

    The `oos_pnl` signal is now the VALIDATION pnl the Statistical Gatekeeper recorded in the
    ledger (via research_repository.experiment_records_for_replay), NOT the old reused 70/30
    OOS — so the policy optimizer is scored on gatekeeper-held validation outcomes and NEVER on
    the locked holdout (closes Leaks 2 & 5). Every Node is validation-sourced, so `holdout`
    stays False. Falls back to the legacy strategy_records tree for users/markets with no ledger
    rows yet (pre-gatekeeper history), so dreaming still works during the cutover."""
    recs = rr.experiment_records_for_replay(cur, user_id, market)
    if recs:
        nodes: List[Node] = []
        for r in recs:
            pnl = float(r.get("net_pnl") or 0.0)
            ins = {"pnl": pnl, "trades": int(r.get("n_trades") or 0)}
            nodes.append(Node(
                score=backtest.score(ins), in_sample=ins, tested=True, oos_pnl=pnl,
                passed=r.get("classification") == "statistically_supported", holdout=False,
            ))
        return nodes
    nodes = []
    for r in repo.strategy_records(cur, user_id, market, limit):
        ins = r["in_sample"]
        nodes.append(Node(
            score=backtest.score(ins) if ins else 0.0,
            in_sample=ins, tested=r["tested"], oos_pnl=r["oos_pnl"], passed=r["passed"],
        ))
    return nodes


def replay(policy: ExplorationPolicy, tree: List[Node], budget: int,
           b1: float = DEFAULT_COST, b3: float = DEFAULT_FINALIST_PENALTY) -> ReplayResult:
    """Replay `policy` over the recorded `tree` (one fixed order) and score it.

    The policy sizes each round; the replay reveals that many recorded nodes in
    order (a policy cannot generate outcomes beyond what was recorded — revealing
    stops when the tree is exhausted). The policy then selects finalists from the
    revealed nodes, and we tally the objective. No LLM/backtest runs.

    This is a single ordering; `replay_generalization` averages it over many
    orderings, which is what the dreaming loop scores on (see module docstring).
    `next_batch` is given only {proposed, budget, round} — the same state the live
    harness provides (`agent._explore_and_gate`), so a scored policy behaves in a
    real run exactly as it was scored (no train/serve skew)."""
    revealed: List[Node] = []
    batch_sizes: List[int] = []
    round_no = 0
    while True:
        round_no += 1
        state = PolicyState(proposed=len(revealed), budget=budget, round=round_no)
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
    value = best_quality - b1 * generations - b3 * len(finalists)
    return ReplayResult(
        value=value, generations=generations, rounds=len(batch_sizes),
        parallelism=parallelism, best_quality=best_quality,
        finalists=len(finalists), passed=sum(1 for n in finalists if n.passed),
    )


def replay_generalization(policy: ExplorationPolicy, tree: List[Node], budget: int,
                          trials: int = GENERALIZATION_TRIALS, seed: int = 0,
                          b1: float = DEFAULT_COST,
                          b3: float = DEFAULT_FINALIST_PENALTY) -> float:
    """Mean V of `policy` over `trials` orderings of `tree` (the recorded order
    plus seeded shuffles). The recorded order of a past run will not recur, so a
    policy that only exploits *that* order (e.g. stopping early because this
    recording's winner happened to appear early) scores well on a single replay
    but poorly here — its best_quality collapses on the orderings where the winner
    lands late. Averaging therefore rewards policies robust to where the winner
    falls, i.e. ones that improve the user's FUTURE research, not just the replay
    number. Deterministic given `seed`."""
    rnd = random.Random(seed)
    total = 0.0
    for i in range(max(1, trials)):
        order = tree if i == 0 else _shuffled(tree, rnd)
        total += replay(policy, order, budget, b1=b1, b3=b3).value
    return total / max(1, trials)


def _shuffled(tree: List[Node], rnd: random.Random) -> List[Node]:
    out = list(tree)
    rnd.shuffle(out)
    return out
