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
    ``open_fees`` is what the current holding cost in fees (reset when it opens from flat, prorated
    as it is reduced), the fee part of its cost basis for a stop.
    ``multiplier`` is the instrument's value per unit price move (1 for a $1-payout binary).
    """

    instrument: InstrumentId
    qty: float = 0.0
    avg_price: float = 0.0
    realized: float = 0.0
    fees: float = 0.0
    multiplier: float = 1.0
    open_fees: float = 0.0

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) < _EPS

    def apply(self, fill: Fill) -> None:
        if fill.instrument != self.instrument:
            raise ValueError("fill for %s applied to position in %s" % (fill.instrument, self.instrument))
        self.fees += fill.fee
        delta = fill.signed_qty
        if self.is_flat:  # opening: the fill price exactly, not price*q/q with its float drift
            self.qty, self.avg_price, self.open_fees = delta, fill.price, fill.fee
            return
        if (self.qty > 0) == (delta > 0):
            self.open_fees += fill.fee
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
            self.open_fees = fill.fee * remainder / abs(delta)
        else:
            self.open_fees *= 1.0 - closing / abs(self.qty)
            self.qty += delta
            if self.is_flat:
                self.qty, self.avg_price, self.open_fees = 0.0, 0.0, 0.0

    def unrealized(self, mark: Optional[float]) -> float:
        if mark is None or self.is_flat:
            return 0.0
        return self.qty * (mark - self.avg_price) * self.multiplier

    def settle(self, price: float) -> float:
        """Close at a settlement price (a binary's 0 or payout), booking it as realized."""
        pnl = self.unrealized(price)
        self.realized += pnl
        self.qty, self.avg_price, self.open_fees = 0.0, 0.0, 0.0
        return pnl


@dataclass
class Portfolio:
    """Cash plus positions. One per book (a user's paper book and live book never mix).

    Change positions through ``apply``/``settle`` only: they keep the open-position index that
    ``open_positions`` reads (flat positions stay in ``positions`` for their realized P&L, so a long
    backtest would otherwise rescan every instrument it ever traded on every step)."""

    cash: float = 0.0
    positions: Dict[InstrumentId, Position] = field(default_factory=dict)
    _open: Dict[InstrumentId, Position] = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._open = {i: p for i, p in self.positions.items() if not p.is_flat}

    def _reindex(self, pos: Position) -> None:
        if pos.is_flat:
            self._open.pop(pos.instrument, None)
        else:
            self._open[pos.instrument] = pos

    def position(self, instrument: InstrumentId, multiplier: float = 1.0) -> Position:
        pos = self.positions.get(instrument)
        if pos is None:
            pos = self.positions[instrument] = Position(instrument, multiplier=multiplier)
        return pos

    def apply(self, fill: Fill, multiplier: float = 1.0) -> None:
        pos = self.position(fill.instrument, multiplier)
        pos.apply(fill)
        self._reindex(pos)
        self.cash -= fill.signed_qty * fill.price * multiplier + fill.fee

    def settle(self, instrument: InstrumentId, price: float) -> float:
        """Settle a position at ``price`` (a binary's 0 or payout): the proceeds go to cash and the
        position goes flat. Returns the realized P&L of the settlement (fees were paid on entry)."""
        pos = self.positions.get(instrument)
        if pos is None or pos.is_flat:
            return 0.0
        self.cash += pos.qty * price * pos.multiplier
        pnl = pos.settle(price)
        self._reindex(pos)
        return pnl

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
        return dict(self._open)
