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
from functools import lru_cache

TAKER_FEE_RATE = Decimal("0.07")
MAKER_FEE_RATE = Decimal("0.0175")
_CENT = Decimal("0.01")


@lru_cache(maxsize=1 << 16)  # pure; a backtest asks for the same (size, price) fee millions of times
def _fee_dollars(rate: Decimal, qty_contracts: int, price_dollars: float) -> float:
    p = Decimal(str(price_dollars))
    raw = rate * Decimal(qty_contracts) * p * (Decimal(1) - p)
    return float(raw.quantize(_CENT, rounding=ROUND_CEILING))


def taker_fee_dollars(qty_contracts: int, price_dollars: float) -> float:
    return _fee_dollars(TAKER_FEE_RATE, qty_contracts, price_dollars)


def maker_fee_dollars(qty_contracts: int, price_dollars: float) -> float:
    return _fee_dollars(MAKER_FEE_RATE, qty_contracts, price_dollars)


def taker_fee_per_contract_dollars(qty_contracts: int, price_dollars: float) -> float:
    """Per-contract taker fee for an order of `qty_contracts` at `price_dollars` -
    the state-dependent cost the entry edge must clear, net-of-fee, so the system
    stops taking fee-negative trades near the 50c mid where this fee peaks.

    It is the REAL schedule for the order the trade will actually place, divided
    across its contracts: Kalshi ceils the fee to the cent per order, and this
    amortizes that cent over the order. Evaluated at the fill price, so it tracks
    the P*(1-P) peak - not a flat per-trade constant. Netting it from the gross
    edge makes the gate strictly stricter than a gross gate (the fee is >= 0),
    which is the whole point: a thin positive gross edge at 50c is net negative.
    """
    q = max(1, int(qty_contracts))
    return taker_fee_dollars(q, price_dollars) / q


def demo() -> None:
    """Runnable self-check: the per-contract fee is the real schedule, peaks at
    the 50c mid, and nets the gross edge negative on a thin edge there."""
    # State-dependent: peaks at the 50c mid, smaller toward the extremes.
    assert taker_fee_per_contract_dollars(100, 0.50) > taker_fee_per_contract_dollars(100, 0.20)
    assert taker_fee_per_contract_dollars(100, 0.90) < taker_fee_per_contract_dollars(100, 0.50)
    # 0.07*0.5*0.5 = 0.0175 per contract at the mid (ceil is negligible at size).
    assert abs(taker_fee_per_contract_dollars(100, 0.50) - 0.0175) < 1e-9
    # A 1.5c gross edge at the 50c mid is net-NEGATIVE once the ~1.75c fee is paid.
    assert 0.015 - taker_fee_per_contract_dollars(100, 0.50) < 0
    print("kalshi_fees demo OK")


if __name__ == "__main__":
    demo()
