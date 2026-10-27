"""trading_core.domain.money: one amount reads one way on every page, however it was summed."""
import random
from decimal import Decimal

from trading_core.domain.money import cents, exact


def test_an_exact_half_cent_rounds_away_from_zero_whichever_way_it_was_summed():
    # -$0.1315 and -$0.6135 are -$0.7450: Python's round() read the SQL sum's float as -0.74 and the
    # trade-by-trade float sum as -0.75. Both are -$0.75 now, and $0.0050 is a cent.
    pnls = [Decimal("-0.1315"), Decimal("-0.6135")]
    assert round(float(sum(pnls)), 2) != round(sum(float(p) for p in pnls), 2)  # the mismatch this fixes
    assert cents(sum(pnls)) == cents(float(sum(pnls))) == cents(sum(float(p) for p in pnls)) == -0.75
    assert cents(Decimal("0.0050")) == 0.01 and cents(-0.005) == -0.01
    assert cents(Decimal("1.2349")) == 1.23 and cents(None) == 0.0


def test_never_negative_zero_and_noise_past_the_fourth_place_goes():
    assert str(cents(-0.0001)) == "0.0"
    assert exact(0.7449999999999999) == Decimal("0.7450")
    assert exact(0.1 + 0.2) == Decimal("0.3000")


def test_float_and_exact_sums_of_stored_money_always_agree():
    rng = random.Random(7)
    for _ in range(20000):
        xs = [Decimal(rng.randint(-50000, 50000)) / 10000 for _ in range(rng.randint(1, 40))]
        assert cents(sum(xs, Decimal(0))) == cents(sum(float(x) for x in xs)), xs
