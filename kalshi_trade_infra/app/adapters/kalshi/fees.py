"""Kalshi fee schedules as ``trading_core.ports.FeeModel``s.

Binaries: the official ceil-to-cent ``rate * C * P * (1 - P)`` per order, from
``data_pipeline.kalshi_fees`` (still the one place the formula lives). Perps: Kalshi's per-ticker
taker/maker rates on notional, read from the exchange's fee tiers.
"""
from __future__ import annotations

from typing import Mapping

from data_pipeline import kalshi_fees
from trading_core.domain import Instrument, InstrumentKind
from trading_core.ports import NotionalRateFees


class KalshiBinaryFees:
    """Whole-order fee for a Kalshi binary fill. ``qty`` must be a whole number of contracts,
    because Kalshi ceils per order and a fractional count has no meaning there."""

    def fee(self, instrument: Instrument, qty: float, price: float, maker: bool = False) -> float:
        if instrument.kind is not InstrumentKind.BINARY:
            raise ValueError("KalshiBinaryFees prices binaries, got %s" % instrument.kind.value)
        contracts = abs(qty)
        if contracts != int(contracts):
            raise ValueError("Kalshi contracts are whole, got qty=%r" % qty)
        if contracts == 0:
            return 0.0
        schedule = kalshi_fees.maker_fee_dollars if maker else kalshi_fees.taker_fee_dollars
        return schedule(int(contracts), price)


def kalshi_perps_fees(fee_tiers: Mapping) -> NotionalRateFees:
    """A FeeModel from ``KalshiPerpsTradingClient.fee_tiers()``. A ticker missing from the tiers
    raises rather than silently pricing at a default rate."""
    taker = {t: float(r) for t, r in fee_tiers["taker_fee_rates"].items()}
    maker = {t: float(r) for t, r in fee_tiers["maker_fee_rates"].items()}
    return _StrictRateFees(taker, maker)


class _StrictRateFees(NotionalRateFees):
    def __init__(self, taker: Mapping[str, float], maker: Mapping[str, float]) -> None:
        super().__init__(0.0, 0.0, taker, maker)

    def rate(self, instrument: Instrument, maker: bool = False) -> float:
        table = self._maker if maker else self._taker
        if instrument.id.symbol not in table:
            raise KeyError("no Kalshi perps fee tier for %s" % instrument.id.symbol)
        return table[instrument.id.symbol]
