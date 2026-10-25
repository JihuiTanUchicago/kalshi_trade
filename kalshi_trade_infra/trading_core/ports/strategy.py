"""A strategy maps what is known now to what it wants to hold. It never sees a venue."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence, runtime_checkable

from trading_core.domain.instruments import Instrument, InstrumentId
from trading_core.domain.market_data import Quote
from trading_core.domain.orders import OrderIntent
from trading_core.domain.positions import Position


@dataclass(frozen=True)
class DecisionContext:
    """Everything a strategy may read at one decision time, identical in backtest and live."""

    now: float
    instruments: Mapping[InstrumentId, Instrument]
    quotes: Mapping[InstrumentId, Quote]          # features ride on each Quote
    positions: Mapping[InstrumentId, Position] = field(default_factory=dict)
    capital: float = 0.0


@runtime_checkable
class Strategy(Protocol):
    strategy_id: str

    def decide(self, ctx: DecisionContext) -> Sequence[OrderIntent]:
        """Exits first (``reduce_only=True``), then entries. No I/O, no clock reads: ``ctx.now``."""
        ...
