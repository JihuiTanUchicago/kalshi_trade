"""Fees are a property of a venue, so the core asks a FeeModel instead of hard-coding Kalshi's."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from trading_core.domain.instruments import Instrument


@runtime_checkable
class FeeModel(Protocol):
    def fee(self, instrument: Instrument, qty: float, price: float, maker: bool = False) -> float:
        """Total fee in quote currency for a fill of ``qty`` at ``price``."""
        ...


class ZeroFees:
    def fee(self, instrument: Instrument, qty: float, price: float, maker: bool = False) -> float:
        return 0.0
