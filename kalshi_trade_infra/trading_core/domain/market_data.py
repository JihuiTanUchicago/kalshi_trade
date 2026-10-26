"""Market state as the core sees it: one top-of-book quote per instrument per decision time."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from trading_core.domain.instruments import InstrumentId


@dataclass(frozen=True)
class Quote:
    """Top of book plus the point-in-time features a strategy may read.

    ``features`` is the generalisation of ``app.trading.markets.Snapshot.features``: every value must be
    knowable at ``ts`` (no look-ahead), whichever FeatureProvider produced it.
    """

    instrument: InstrumentId
    ts: float                         # unix seconds the book was observed
    bid: Optional[float]              # None = no resting bid
    ask: Optional[float]              # None = no resting ask
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    features: Dict[str, float] = field(default_factory=dict, compare=False, hash=False)

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    def age(self, now_ts: float) -> float:
        return max(0.0, now_ts - self.ts)
