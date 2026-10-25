"""P(S_T > K) read off a ladder of binary prices that all settle at the same time T.

Two venues list binaries on the same underlying and settlement time at different strikes
(Polymarket's "BTC above $110,000 at noon ET" against Kalshi's KXBTCD 111,249.99 strike). The
ladder of one venue's mids is a survival curve: non-increasing in K. Mids are noisy, so the curve
is made monotone first (pool-adjacent-violators, equal weights), then read at another strike by
interpolating on the logit scale, which keeps the tails sensible where linear interpolation in
probability would not. Outside the quoted strikes there is no answer (None): extrapolating a
distribution's tail from two points is a guess, and an absent feature beats a guessed one.

Nor is there one inside a gap the curve falls through too steeply. Polymarket lists every $2,000
and Kalshi every $100; in the last hour the ladder reads 0.999 at 80k and 0.001 at 82k, and
interpolating that put "above 80,600" at 0.79 against Kalshi's 0.47 (2026-10-25). For a normal
terminal price, logit interpolation across a gap of 2 sigma (a logit step of ~3.8) is off by
at most ~3c; past MAX_LOGIT_STEP the shape inside the gap is unresolved and the answer is None.
"""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence, Tuple

EPS = 1e-4          # probabilities are clipped into [EPS, 1 - EPS] before taking logits
MAX_LOGIT_STEP = 3.5   # widest logit drop between neighbouring strikes that is interpolated
SNAP = 1e-3            # a strike within this fraction of the gap from a quoted one reads that one


def monotone_survival(points: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """(strike, P(S > strike)) sorted by strike, made non-increasing by pooling violators.
    Duplicate strikes are averaged; probabilities are clipped to [0, 1]; NaNs are dropped."""
    by_k = {}
    for k, p in points:
        if k is None or p is None or not (k == k) or not (p == p):
            continue
        by_k.setdefault(float(k), []).append(min(max(float(p), 0.0), 1.0))
    ks = sorted(by_k)
    # blocks of [sum, count, first index]; merge while a later block's mean exceeds an earlier's
    blocks: List[List[float]] = []
    for i, k in enumerate(ks):
        vals = by_k[k]
        blocks.append([sum(vals) / len(vals), 1.0, i])
        while len(blocks) > 1 and blocks[-1][0] / blocks[-1][1] > blocks[-2][0] / blocks[-2][1] + 1e-12:
            s, n, _ = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += n
    out: List[Tuple[float, float]] = []
    for j, (s, n, start) in enumerate(blocks):
        end = blocks[j + 1][2] if j + 1 < len(blocks) else len(ks)
        for i in range(int(start), int(end)):
            out.append((ks[i], s / n))
    return out


def _logit(p: float) -> float:
    p = min(max(p, EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def prob_above(curve: Sequence[Tuple[float, float]], k: float,
               max_step: float = MAX_LOGIT_STEP) -> Optional[float]:
    """P(S > k) from a monotone curve (monotone_survival output), or None outside its strikes or
    between two strikes whose logits differ by more than ``max_step`` (k on a strike is exact)."""
    if not curve or k is None:
        return None
    if k < curve[0][0] or k > curve[-1][0]:
        return None
    for (k0, p0), (k1, p1) in zip(curve, curve[1:]):
        if k0 <= k <= k1:
            if k1 == k0:
                return p0
            w = (k - k0) / (k1 - k0)
            if w <= SNAP or w >= 1.0 - SNAP:   # on a strike (Kalshi's 79,999.99 is Polymarket's 80k)
                return p0 if w <= SNAP else p1
            if p0 == p1:
                return p0
            z0, z1 = _logit(p0), _logit(p1)
            if abs(z0 - z1) > max_step:
                return None
            z = (1.0 - w) * z0 + w * z1
            return 1.0 / (1.0 + math.exp(-z))
    return curve[0][1] if k == curve[0][0] else None


def prob_yes(curve: Sequence[Tuple[float, float]], lo: Optional[float], hi: Optional[float]) -> Optional[float]:
    """P(YES) of a contract on the same underlying and settlement time: above ``lo`` (floor only),
    below ``hi`` (cap only) or between them (both). None when either edge is off the curve."""
    if lo is not None and hi is not None:
        a, b = prob_above(curve, lo), prob_above(curve, hi)
        return None if a is None or b is None else max(a - b, 0.0)
    if lo is not None:
        return prob_above(curve, lo)
    if hi is not None:
        b = prob_above(curve, hi)
        return None if b is None else 1.0 - b
    return None
