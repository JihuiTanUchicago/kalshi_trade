"""Where orders go. Live exchange, sandbox and simulator are all Venues; nothing else differs.

``data_pipeline.architecture.simulated_venue`` already proves the idea for Kalshi: the same
MarketableLimitKernel runs against the real submitter or the simulated one. This port makes the
seam venue-neutral, so Alpaca equities, Kalshi perps or Polymarket plug in the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol, Sequence, runtime_checkable

from trading_core.domain.instruments import InstrumentId, InstrumentKind
from trading_core.domain.orders import ExecutionReport, OrderIntent


@dataclass(frozen=True)
class VenueCapabilities:
    """What a venue supports, so the execution policy adapts instead of branching on a venue name."""

    kinds: frozenset = field(default_factory=lambda: frozenset({InstrumentKind.BINARY}))
    market_orders: bool = False     # Kalshi: no; every order is a limit priced through the touch
    shorting: bool = False          # a sell with nothing held opens a short (position guards forbid it)
    fractional_qty: bool = False
    sends_real_orders: bool = False  # False for simulators and paper; True gates on the live switches


@runtime_checkable
class Venue(Protocol):
    name: str
    capabilities: VenueCapabilities

    def submit(self, intent: OrderIntent, limit_price: float, client_order_id: str) -> ExecutionReport:
        """Send one immediate-or-cancel limit order. Must never retry a write on its own: on a
        transport error the caller reconciles by ``client_order_id`` before doing anything else."""
        ...

    def positions(self) -> Mapping[InstrumentId, float]:
        """The venue's own signed net quantity per instrument: the truth position guards read."""
        ...

    def cash(self) -> Optional[float]:
        """Available cash in quote currency, or None when the venue can't say."""
        ...

    def lookup(self, client_order_ids: Sequence[str]) -> Mapping[str, ExecutionReport]:
        """Crash recovery: what became of orders we may have sent."""
        ...
