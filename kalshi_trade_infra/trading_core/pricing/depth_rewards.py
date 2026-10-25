"""Resting-liquidity rewards: a venue pays a fixed pool for size resting at or near the touch.

The rule is Kalshi's Liquidity Incentive Program as filed (October 14, 2026 amendment), stated
venue-neutrally so another venue's depth program can reuse it:

* Once a second (at a random instant) the venue snapshots the book. On each side it walks down
  from the best bid, adding whole price levels, until the cumulative size reaches ``target_size``;
  those levels qualify. A side that never reaches the target has nothing qualifying, and a
  snapshot counts only when BOTH sides qualify (two-sided liquidity).
* The reference price is the first level at which the cumulative size reaches
  ``reference_fraction`` (1/5) of the target. An order scores ``discount ** N * size``, N the ticks
  it sits below the reference (0 at or above it). Scores are normalized per side.
* A participant's payout = pool * sum over counted snapshots of (yes share + no share) / 2,
  divided by ALL snapshots of the period (excluded snapshots shrink everyone's payout).

Binary books are two bid ladders: YES bids and NO bids, where a YES ask at p is a NO bid at 1 - p.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

Level = Tuple[float, float]   # (price, total resting size at that price, ours included)


@dataclass(frozen=True)
class DepthRewardTerms:
    pool: float                       # quote currency paid over [start, end)
    start: float                      # unix seconds
    end: float
    target_size: float
    discount_per_tick: float = 0.5
    tick: float = 0.01
    reference_fraction: float = 0.2
    min_payout: float = 1.0

    @property
    def seconds(self) -> float:
        return max(self.end - self.start, 1.0)

    @property
    def pool_per_second(self) -> float:
        return self.pool / self.seconds

    def active(self, ts: float) -> bool:
        return self.start <= ts < self.end


def side_share(levels: Sequence[Level], mine: Mapping[float, float], terms: DepthRewardTerms) -> Optional[float]:
    """Our normalized score on one side, or None when the side cannot reach the target size.

    ``levels`` best (highest) price first, sizes including ours; ``mine`` maps price -> our size."""
    total = 0.0
    reference: Optional[float] = None
    qualifying = []
    for price, size in levels:
        if size <= 0:
            continue
        total += size
        qualifying.append((price, size))
        if reference is None and total >= terms.reference_fraction * terms.target_size:
            reference = price
        if total >= terms.target_size:
            break
    else:
        return None
    score_all = score_mine = 0.0
    for price, size in qualifying:
        n = max(0, int(round((reference - price) / terms.tick)))
        w = terms.discount_per_tick ** n
        score_all += w * size
        score_mine += w * min(mine.get(price, 0.0), size)
    return score_mine / score_all if score_all > 0 else 0.0


def snapshot_reward(yes_levels: Sequence[Level], no_levels: Sequence[Level], mine_yes: Mapping[float, float],
                    mine_no: Mapping[float, float], terms: DepthRewardTerms) -> float:
    """What one snapshot earns us: pool per second * (yes share + no share) / 2, or 0 when the
    snapshot is excluded because a side misses the target."""
    sy = side_share(yes_levels, mine_yes, terms)
    sn = side_share(no_levels, mine_no, terms)
    if sy is None or sn is None:
        return 0.0
    return terms.pool_per_second * (sy + sn) / 2.0
