"""Money as every page shows it: summed exactly, then rounded once, half up, to the cent.

A position's money (pnl, fees, prices, cost) is stored on 4 places (DECIMAL(.,4)). The pages reached
a figure three ways: SQL's exact SUM read back as a float, Python floats added trade by trade, and
the browser adding figures already rounded to the cent. Python's round() rounds the binary float, so
an exact half cent went up or down depending on how the float was reached: two live trades of
-$0.1315 and -$0.6135 (-$0.7450 exactly) read -$0.74 on the dashboard and -$0.75 on the track
record. Every money figure a page shows goes through `cents`, so one amount reads one way everywhere.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

PLACE = Decimal("0.0001")  # the places a position's money is stored on
CENT = Decimal("0.01")


def exact(v) -> Decimal:
    """`v` (a Decimal, a float, an int, a numeric str or None) on the 4 places a position's money has.
    A float summed trade by trade carries noise past them (0.7449999999999999), which goes here; the
    float of an exact sum (float(Decimal("-0.7450"))) comes back as that sum. Only for amounts that
    are sums of stored money, which never have a fifth place."""
    return Decimal(str(v or 0)).quantize(PLACE, rounding=ROUND_HALF_UP)


def cents(v) -> float:
    """exact(v) rounded half up (away from zero) to the cent, as the float a JSON answer carries
    (never -0.0): -0.7450 is -0.75 and 0.0050 is 0.01, whichever way the sum was added."""
    return float(exact(v).quantize(CENT, rounding=ROUND_HALF_UP)) + 0.0
