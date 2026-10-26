"""Sanity properties for the Kalshi binary-option quant toolkit (app/trading/quant.py)."""
import math

from app.trading import quant


def _sig():
    return quant.annualize_vol(0.002)  # ~0.2%/min BTC vol, annualized


def test_fair_value_moneyness():
    sig = _sig()
    assert abs(quant.yes_fair_value(100000, 100000, 60, sig, "above") - 0.5) < 0.02
    assert quant.yes_fair_value(140000, 100000, 60, sig, "above") > 0.99   # deep ITM
    assert quant.yes_fair_value(60000, 100000, 60, sig, "above") < 0.01    # deep OTM


def test_fair_value_monotonic_and_side():
    sig = _sig()
    lo = quant.yes_fair_value(99000, 100000, 120, sig, "above")
    mid = quant.yes_fair_value(100000, 100000, 120, sig, "above")
    hi = quant.yes_fair_value(101000, 100000, 120, sig, "above")
    assert lo < mid < hi
    # below == 1 - above
    assert abs(quant.yes_fair_value(101000, 100000, 120, sig, "below") - (1 - hi)) < 1e-12


def test_fair_value_expiry_and_zero_vol():
    assert quant.yes_fair_value(110000, 100000, 0, 0.5, "above") == 1.0
    assert quant.yes_fair_value(90000, 100000, 0, 0.5, "above") == 0.0
    assert quant.yes_fair_value(100000, 100000, 0, 0.5, "above") == 0.5
    assert quant.yes_fair_value(110000, 100000, 60, 0.0, "above") == 1.0  # zero vol -> certain


def test_edge_sign():
    # fair > price => positive edge for YES, negative for NO
    assert abs(quant.edge(0.60, 0.50, "yes") - 0.10) < 1e-9
    assert abs(quant.edge(0.60, 0.50, "no") + 0.10) < 1e-9
    assert abs(quant.edge(0.40, 0.50, "yes") + 0.10) < 1e-9


def test_after_fee_edge_is_less_than_gross():
    gross = quant.edge(0.60, 0.50, "yes") * 100
    net = quant.after_fee_edge(0.60, 0.50, 100, "yes")
    assert net < gross and (gross - net) == quant.kalshi_fee(0.50, 100)


def test_kelly():
    assert quant.kelly_fraction(0.50, 0.50) == 0.0          # no edge -> no bet
    assert quant.kelly_fraction(0.40, 0.50) == 0.0          # negative edge -> no bet
    assert quant.kelly_fraction(0.70, 0.50) > quant.kelly_fraction(0.60, 0.50)  # grows with edge
    # (q - P)/(1 - P): q=0.7,P=0.5 -> 0.4
    assert abs(quant.kelly_fraction(0.70, 0.50) - 0.4) < 1e-9
    assert abs(quant.fractional_kelly(0.70, 0.50, frac=0.25) - 0.1) < 1e-9
    assert quant.kelly_fraction(0.9, 0.0) == 0.0 and quant.kelly_fraction(0.9, 1.0) == 0.0  # degenerate prices


def test_fee_nonneg_and_peaks_midbook():
    assert quant.kalshi_fee(0.50, 10) >= 0
    assert quant.kalshi_fee(0.50, 100) >= quant.kalshi_fee(0.05, 100)  # fee peaks near 0.5


def test_portfolio_and_drawdown():
    assert quant.max_drawdown([100, 120, 90, 110, 80]) == 40.0
    assert quant.max_drawdown([10, 20, 30]) == 0.0
    pm = quant.portfolio_metrics([{"cost": 30, "market": "a"}, {"cost": 10, "market": "a"}, {"cost": 10, "market": "b"}])
    assert pm["total_exposure"] == 50.0 and pm["n_markets"] == 2
    assert abs(pm["concentration"] - 0.8) < 1e-9
    assert quant.portfolio_metrics([]) == {"total_exposure": 0.0, "concentration": 0.0, "n_markets": 0}


def test_demo_runs():
    quant.demo()
