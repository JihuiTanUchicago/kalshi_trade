"""Kalshi's official per-contract trading fee formulas.

Source: https://kalshi.com/docs/kalshi-fee-schedule.pdf

    taker (instant match): fee = ceil_cent(0.07  * C * P * (1 - P))
    maker (resting limit):  fee = ceil_cent(0.0175 * C * P * (1 - P))

C is contract count, P is contract price in dollars (0 < P < 1; our own
forward_quotes history shows Kalshi actually quotes this market down to
$0.001 increments, not just whole cents). The fee peaks near P=0.50 and
vanishes near the extremes. Kalshi rounds the fee up to the next cent - not
a flat percentage of notional, so it must not be approximated with a
constant rate.

Uses Decimal rather than float: a plain `math.ceil(x * 100) / 100` can round
an exact $1.75 up to $1.76 because 0.07 * 100 * 0.5 * 0.5 isn't exactly
representable in binary floating point.
"""
from decimal import ROUND_CEILING, Decimal

TAKER_FEE_RATE = Decimal("0.07")
MAKER_FEE_RATE = Decimal("0.0175")
_CENT = Decimal("0.01")


def _fee_dollars(rate: Decimal, qty_contracts: int, price_dollars: float) -> float:
    p = Decimal(str(price_dollars))
    raw = rate * Decimal(qty_contracts) * p * (Decimal(1) - p)
    return float(raw.quantize(_CENT, rounding=ROUND_CEILING))


def taker_fee_dollars(qty_contracts: int, price_dollars: float) -> float:
    return _fee_dollars(TAKER_FEE_RATE, qty_contracts, price_dollars)


