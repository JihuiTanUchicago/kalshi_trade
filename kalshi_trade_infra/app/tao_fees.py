"""Fill/slippage + swap-cost model for TAO subnet alpha tokens.

An alpha token is NOT an order book. Buying it is an on-chain `stake` into the subnet's
substrate AMM pool; selling is `unstake`. The executed price therefore moves with trade size
vs the pool's reserves - filling at the printed mid is the single most dangerous way a spot
backtest can lie (TAO_VENUE_DESIGN.md §A.4), so every fill here is marked against pool depth.

The impact is computed in TAO/alpha terms (the pool is `tao_pool` TAO against `alpha_pool`
alpha), so it is a dimensionless fraction that applies equally to the alpha-in-TAO price and the
derived alpha-in-USD price. This mirrors data_pipeline/kalshi_fees.py: the one place the venue's
trading cost math lives, so the backtester and (later) any execution path cost a fill identically.

ponytail: linear depth-impact (fraction of the alpha reserve the trade moves); upgrade to the
full constant-product curve x*y=k only if realized fills prove materially off this.
"""
from __future__ import annotations

from typing import Optional

# Fraction of notional charged per swap as a chain/tx cost (on top of slippage, which is already
# in the fill price). Small and dimensionless so it is denomination-consistent.
SWAP_FEE_RATE = 0.0005  # 5 bps per swap
# When pool depth is unknown (no reserves feature on the frame) we must still NOT fill at mid,
# so assume a conservative flat slippage rather than pretending the trade is free.
DEFAULT_SLIPPAGE_FRACTION = 0.02
# A single trade can never move the price by more than this (keeps a huge size from producing a
# nonsensical negative/doubled fill under the linear model).
MAX_IMPACT_FRACTION = 0.5


def price_impact(qty: float, alpha_pool: Optional[float]) -> float:
    """Dimensionless price-impact fraction for trading `qty` alpha tokens against a pool holding
    `alpha_pool` alpha in reserve. Linear in the fraction of the reserve moved, capped. Falls back
    to DEFAULT_SLIPPAGE_FRACTION when depth is unknown (never zero -> never a free mid fill)."""
    if alpha_pool and alpha_pool > 0:
        return min(abs(qty) / float(alpha_pool), MAX_IMPACT_FRACTION)
    return DEFAULT_SLIPPAGE_FRACTION


def fill_price(mid_price: float, qty: float, side: str, alpha_pool: Optional[float] = None) -> float:
    """Executed price for a swap. `side` is "buy" (open a long / add TAO, price slips UP) or
    "sell" (close / remove TAO, price slips DOWN). `mid_price` may be in TAO or USD; the impact
    fraction is unit-free so the same call works for either denomination."""
    impact = price_impact(qty, alpha_pool)
    return mid_price * (1.0 + impact) if side == "buy" else mid_price * (1.0 - impact)


def swap_fee(notional: float) -> float:
    """Chain/tx cost of one swap, in the same denomination as `notional`."""
    return SWAP_FEE_RATE * abs(notional)


def _demo() -> None:
    # Bigger size slips the fill further from mid, and a buy fills above / a sell below mid.
    assert fill_price(1.0, 10.0, "buy", 1000.0) < fill_price(1.0, 100.0, "buy", 1000.0)
    assert fill_price(1.0, 100.0, "buy", 1000.0) > 1.0 > fill_price(1.0, 100.0, "sell", 1000.0)
    # No depth -> conservative flat slippage, never a free mid fill.
    assert fill_price(1.0, 5.0, "buy", None) == 1.0 + DEFAULT_SLIPPAGE_FRACTION
    # Impact fraction is unit-free: same on a USD mid as on a TAO mid.
    assert abs(price_impact(50.0, 500.0) - 0.1) < 1e-12
    print("tao_fees demo ok")


if __name__ == "__main__":
    _demo()
