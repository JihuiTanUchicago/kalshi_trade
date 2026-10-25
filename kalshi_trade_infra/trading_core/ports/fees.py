"""Fees are a property of a venue, so the core asks a FeeModel instead of hard-coding Kalshi's.

Venue-specific schedules (Kalshi's ceil-to-cent P*(1-P) formula, TAO's swap fee) live in their
adapters. The generic pieces live here: a notional-rate model that fits most exchanges (perps,
equities, crypto spot) and a router that picks the model by instrument venue.
"""
from __future__ import annotations

from typing import Mapping, Optional, Protocol, runtime_checkable

from trading_core.domain.instruments import Instrument


@runtime_checkable
class FeeModel(Protocol):
    def fee(self, instrument: Instrument, qty: float, price: float, maker: bool = False) -> float:
        """Total fee in quote currency for a fill of ``qty`` at ``price``."""
        ...


class ZeroFees:
    def fee(self, instrument: Instrument, qty: float, price: float, maker: bool = False) -> float:
        return 0.0


class NotionalRateFees:
    """fee = rate * |qty| * price * multiplier. ``taker_by_symbol``/``maker_by_symbol`` override
    the default rate per instrument symbol (a venue's fee tiers); a negative rate is a rebate."""

    def __init__(self, taker_rate: float, maker_rate: Optional[float] = None,
                 taker_by_symbol: Optional[Mapping[str, float]] = None,
                 maker_by_symbol: Optional[Mapping[str, float]] = None) -> None:
        self.taker_rate = taker_rate
        self.maker_rate = taker_rate if maker_rate is None else maker_rate
        self._taker = dict(taker_by_symbol or {})
        self._maker = dict(maker_by_symbol or {})

    def rate(self, instrument: Instrument, maker: bool = False) -> float:
        sym = instrument.id.symbol
        if maker:
            return self._maker.get(sym, self.maker_rate)
        return self._taker.get(sym, self.taker_rate)

    def fee(self, instrument: Instrument, qty: float, price: float, maker: bool = False) -> float:
        return self.rate(instrument, maker) * abs(qty) * price * instrument.multiplier


class FeesByVenue:
    """Routes by ``instrument.id.venue``. An unknown venue raises instead of costing zero, so a
    newly plugged-in market can never backtest fee-free by omission."""

    def __init__(self, models: Mapping[str, FeeModel]) -> None:
        self._models = dict(models)

    def fee(self, instrument: Instrument, qty: float, price: float, maker: bool = False) -> float:
        try:
            model = self._models[instrument.id.venue]
        except KeyError:
            raise KeyError("no fee model for venue %r" % instrument.id.venue) from None
        return model.fee(instrument, qty, price, maker)
