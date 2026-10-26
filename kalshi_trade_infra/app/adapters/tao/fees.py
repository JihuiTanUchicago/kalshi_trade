"""The TAO swap fee as a ``trading_core.ports.FeeModel``. Price impact is not a fee: it is already
in the fill price (``app.adapters.tao.tao_fees.fill_price``), so this charges only the per-swap chain cost."""
from __future__ import annotations

from app.adapters.tao import tao_fees
from trading_core.domain import Instrument


class TaoSwapFees:
    def fee(self, instrument: Instrument, qty: float, price: float, maker: bool = False) -> float:
        return tao_fees.swap_fee(abs(qty) * price * instrument.multiplier)
