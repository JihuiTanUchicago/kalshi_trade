"""Positions and portfolios, built only from fills. Same math for paper, backtest and live."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional

from trading_core.domain.instruments import InstrumentId
from trading_core.domain.orders import Fill

_EPS = 1e-12


@dataclass
class Position:
    """Signed net quantity (+ long, - short) at an average entry price.

    ``realized`` and ``fees`` accumulate across the position's life; a flat position keeps them.
    ``multiplier`` is the instrument's value per unit price move (1 for a $1-payout binary).
    """

    instrument: InstrumentId
    qty: float = 0.0
    avg_price: float = 0.0
    realized: float = 0.0
    fees: float = 0.0
    multiplier: float = 1.0

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) < _EPS

    def apply(self, fill: Fill) -> None:
        if fill.instrument != self.instrument:
            raise ValueError("fill for %s applied to position in %s" % (fill.instrument, self.instrument))
        self.fees += fill.fee
        delta = fill.signed_qty
        if self.is_flat or (self.qty > 0) == (delta > 0):
            new_qty = self.qty + delta
            self.avg_price = (self.avg_price * abs(self.qty) + fill.price * abs(delta)) / abs(new_qty)
            self.qty = new_qty
            return
        closing = min(abs(delta), abs(self.qty))
        direction = 1.0 if self.qty > 0 else -1.0
        self.realized += direction * closing * (fill.price - self.avg_price) * self.multiplier
        remainder = abs(delta) - closing
        if remainder > _EPS:  # flipped through flat: the excess opens at the fill price
            self.qty = -direction * remainder
            self.avg_price = fill.price
        else:
            self.qty += delta
            if self.is_flat:
                self.qty, self.avg_price = 0.0, 0.0

    def unrealized(self, mark: Optional[float]) -> float:
        if mark is None or self.is_flat:
            return 0.0
        return self.qty * (mark - self.avg_price) * self.multiplier

    def settle(self, price: float) -> float:
        """Close at a settlement price (a binary's 0 or payout), booking it as realized."""
        pnl = self.unrealized(price)
        self.realized += pnl
        self.qty, self.avg_price = 0.0, 0.0
        return pnl


@dataclass
class Portfolio:
    """Cash plus positions. One per book (a user's paper book and live book never mix)."""

    cash: float = 0.0
    positions: Dict[InstrumentId, Position] = field(default_factory=dict)

    def position(self, instrument: InstrumentId, multiplier: float = 1.0) -> Position:
        pos = self.positions.get(instrument)
        if pos is None:
            pos = self.positions[instrument] = Position(instrument, multiplier=multiplier)
        return pos

    def apply(self, fill: Fill, multiplier: float = 1.0) -> None:
        self.position(fill.instrument, multiplier).apply(fill)
        self.cash -= fill.signed_qty * fill.price * multiplier + fill.fee

    def apply_all(self, fills: Iterable[Fill]) -> None:
        for f in fills:
            self.apply(f)

    def equity(self, marks: Mapping[InstrumentId, float]) -> float:
        """Cash plus every open position at its mark (cost basis when no mark is known)."""
        value = self.cash
        for inst, pos in self.positions.items():
            if not pos.is_flat:
                value += pos.qty * marks.get(inst, pos.avg_price) * pos.multiplier
        return value

    def open_positions(self) -> Dict[InstrumentId, Position]:
        return {i: p for i, p in self.positions.items() if not p.is_flat}
