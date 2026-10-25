"""Where a strategy's own holdings live between decisions.

A backtest keeps them in memory (``Portfolio``). Paper and live keep them in the database, so a
restart resumes the same book and every fill is booked exactly once against its order intent; that
is a DB adapter behind this port. The loop only ever talks to a ``Book``, so all three run the
same steps.
"""
from __future__ import annotations

from typing import Dict, Mapping, Protocol, runtime_checkable

from trading_core.domain.instruments import Instrument, InstrumentId
from trading_core.domain.orders import ExecutionReport
from trading_core.domain.positions import Position


@runtime_checkable
class Book(Protocol):
    cash: float
    positions: Mapping[InstrumentId, Position]   # flat ones may remain, carrying realized P&L

    def open_positions(self) -> Dict[InstrumentId, Position]:
        ...

    def record(self, report: ExecutionReport, instruments: Mapping[InstrumentId, Instrument]) -> None:
        """Book the report's fills. The report carries its intent (reason, meta) for the books that
        need more than the fill to record it."""
        ...

    def settle(self, instrument: InstrumentId, price: float) -> float:
        """Close a held instrument at its settlement price; returns the realized P&L."""
        ...
