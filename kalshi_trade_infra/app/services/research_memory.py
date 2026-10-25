"""What the research generator learns from its own dead ends: a leak-safe digest of FAILED strategies.

Pure logic over strategy_memory rows (no DB), so it lives with the research services, not the
repository (ARCHITECTURE.md step 10: the research loop's pieces move out of agent/repository).
"""
from __future__ import annotations

from typing import Dict, List, Optional

# A failed strategy's row status. REJECTED (no mechanism / not a finalist / rejected on
# validation) and INCONCLUSIVE map here (see agent._status_for); "passed"/"pending" don't.
FAILED_STATUSES = ("rejected", "failed")


def _failure_dims(s: Dict) -> List[str]:
    """The leak-safe dimensions of a failed strategy — ONLY its own spec + direction, which the
    generator already proposed and is always allowed to see. No held-out number is read."""
    spec = s.get("spec") or {}
    model = spec.get("model") or {}
    entry = spec.get("entry") or {}
    dims: List[str] = []
    if spec.get("side"):
        dims.append("side=%s" % spec["side"])
    if s.get("direction"):
        dims.append("lens=%s" % s["direction"])
    if spec.get("code"):
        dims.append("mechanism=custom-code")
    else:
        beta = model.get("drift_beta") or 0
        if beta > 0:
            dims.append("mechanism=momentum")
        elif beta < 0:
            dims.append("mechanism=mean-reversion")
        if (model.get("vol_scale") or 1.0) != 1.0:
            dims.append("mechanism=vol-mispricing")
    lo, hi = entry.get("min_price"), entry.get("max_price")
    if lo is not None and hi is not None:
        dims.append("price-band=%.2f-%.2f" % (float(lo), float(hi)))
    return dims


def distill_failures(memory: List[Dict], min_recurrence: int = 2) -> Optional[Dict]:
    """Distill the FAILED strategies in a strategy_memory list into ONE compact, leak-safe
    summary of what keeps failing — recurring spec/mechanism regions and the classification
    tally — so the generator explores AWAY from proven-dead ground instead of re-reading a pile
    of individually-useless rejected rows. Returns None when there's nothing to learn from yet
    (so the caller is a no-op on a fresh market).

    LEAK SAFETY (Leak 2 stays closed): reads ONLY what the generator may already see — the
    classification/status LABELS and the hypotheses' own specs/direction. It never reads a
    validation/holdout P&L/Sharpe/return — those are gatekeeper-held and are not even present on
    these rows (_result_block stores research-fold numbers + the label only). So nothing here can
    leak held-out evidence back into generation; it can only make the generator more skeptical.
    """
    failed = [s for s in memory if s.get("status") in FAILED_STATUSES]
    if not failed:
        return None
    classifications: Dict[str, int] = {}
    dim_counts: Dict[str, int] = {}
    for s in failed:
        cls = (s.get("result") or {}).get("classification") or s.get("status")
        classifications[cls] = classifications.get(cls, 0) + 1
        for d in _failure_dims(s):
            dim_counts[d] = dim_counts.get(d, 0) + 1
    patterns = sorted(((d, c) for d, c in dim_counts.items() if c >= min_recurrence),
                      key=lambda dc: (-dc[1], dc[0]))
    return {"n_failed": len(failed), "classifications": classifications, "patterns": patterns}
