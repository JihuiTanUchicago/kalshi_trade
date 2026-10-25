"""What a strategy wants (OrderIntent) and what a venue did about it (ExecutionReport, Fill).

The split matters: a strategy never prices against the wire or picks a time-in-force. It states
an intent; the execution policy turns it into venue orders; the venue reports fills. Paper,
backtest and live differ only in which Venue sits at the end of that chain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from trading_core.domain.instruments import InstrumentId


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


@dataclass(frozen=True)
class OrderIntent:
    instrument: InstrumentId
    side: Side
    qty: float
    limit_price: Optional[float] = None   # worst acceptable price; None = execution policy decides
    reduce_only: bool = False             # an exit: risk rules may never block it
    strategy_id: str = ""
    reason: str = ""
    # The strategy's own fair value for the instrument, so execution can re-check edge at the
    # price actually available (MarketableLimitKernel's reservation price).
    fair_value: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not self.qty > 0:
            raise ValueError("intent qty must be positive, got %r" % self.qty)

    @property
    def signed_qty(self) -> float:
        return self.side.sign * self.qty


@dataclass(frozen=True)
class Fill:
    instrument: InstrumentId
    side: Side
    qty: float
    price: float
    fee: float = 0.0
    ts: float = 0.0
    order_id: Optional[str] = None

    @property
    def signed_qty(self) -> float:
        return self.side.sign * self.qty

    @property
    def notional(self) -> float:
        return self.qty * self.price


@dataclass(frozen=True)
class ExecutionReport:
    """What the venue says happened. Fills are the venue's numbers, never what was asked for."""

    intent: OrderIntent
    status: str                           # "filled" | "partial" | "unfilled" | "rejected" | "error"
    fills: List[Fill] = field(default_factory=list)
    order_ids: List[str] = field(default_factory=list)
    message: str = ""

    @property
    def filled_qty(self) -> float:
        return sum(f.qty for f in self.fills)

    @property
    def avg_price(self) -> Optional[float]:
        q = self.filled_qty
        return sum(f.qty * f.price for f in self.fills) / q if q else None

    @property
    def fees(self) -> float:
        return sum(f.fee for f in self.fills)


@dataclass(frozen=True)
class RestingOrder:
    """A passive limit order working on a venue's book (a market maker's quote): it fills when
    someone else trades into it, possibly in pieces, until filled or cancelled."""

    order_id: str
    instrument: InstrumentId
    side: Side
    price: float
    qty: float                            # still working
    client_order_id: str = ""
    placed_at: float = 0.0
