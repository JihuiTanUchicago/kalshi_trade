"""Exploration policy — a PURE decision function over the discovery so far.

This is the first foundation piece of Tau-RSI (self-evolving research, adapted
from Dream-RSI, arXiv 2609.14858). The exploration policy decides HOW to search:
how many hypotheses to propose next, which of them earn an out-of-sample test,
and when to stop. It is deliberately a *pure* function of a read-only snapshot of
the discovery tree — it performs NO I/O (no LLM, backtester, DB, or network). The
research harness (`agent.run_research`) does all of that.

Keeping the policy side-effect-free is the key safety invariant: a later,
per-user, LLM-authored policy (Tau-RSI P3/P4) can then run inside a sandbox with
no network/filesystem access, since all it can do is read the tree and return
allocation decisions. For now the only implementation is `DefaultPolicy`, which
reproduces the pipeline's long-standing fixed behavior exactly — this phase (P1)
is a refactor with no behavior change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

# The fixed knobs the pipeline has always used; now owned by the default policy.
BATCH = 4          # hypotheses proposed per round (small, so each round learns from the last)
FINALISTS = 3      # per chunk, the few best that earn an unseen-data test (multiple-testing discipline)
MAX_FINALISTS = 8


@dataclass(frozen=True)
class PolicyState:
    """Read-only snapshot the policy reasons over (the 'discovery tree' so far)."""
    proposed: int                    # hypotheses proposed so far in the current chunk
    budget: int                      # max hypotheses for this chunk
    round: int                       # 1-based round index within the chunk


@dataclass(frozen=True)
class Batch:
    width: int                       # how many hypotheses to propose next; <= 0 means stop exploring


class ExplorationPolicy:
    """Interface: a pure decision function. Implementations must not do I/O."""

    def next_batch(self, state: PolicyState) -> Batch:
        raise NotImplementedError

    def select_finalists(self, candidates: List[Dict], state: PolicyState) -> List[Dict]:
        """From this chunk's scored in-sample candidates, pick the few to gate on
        unseen data. Each candidate carries a precomputed `score` and `in_sample`
        (so the policy needs no backtester)."""
        raise NotImplementedError


class DefaultPolicy(ExplorationPolicy):
    """The pipeline's historical behavior, expressed as a policy:
    a constant batch width capped by the remaining budget, and the top few
    *profitable* in-sample candidates (with a minimum trade count) as finalists.
    Byte-for-byte equivalent to the previous hardcoded loop."""

    def __init__(self, batch: int = BATCH, finalists: int = FINALISTS, max_finalists: int = MAX_FINALISTS):
        self.batch, self.finalists, self.max_finalists = batch, finalists, max_finalists

    def next_batch(self, state: PolicyState) -> Batch:
        return Batch(max(0, min(self.batch, state.budget - state.proposed)))

    def select_finalists(self, candidates: List[Dict], state: PolicyState) -> List[Dict]:
        ranked = sorted(candidates, key=lambda t: t.get("score", 0.0), reverse=True)
        n = min(max(self.finalists, len(candidates) // 10), self.max_finalists)
        out = []
        for t in ranked[:n]:
            ins = t.get("in_sample") or {}
            if (ins.get("pnl") or 0) > 0 and (ins.get("trades") or 0) >= 5:
                out.append(t)
        return out
