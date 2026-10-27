"""The paper book's "after typical live slippage" estimate (trading_core.domain.slippage).

Paper fills pay the spread and Kalshi's taker fee but fill at a quote up to 2s old, so they never pay
for the price moving before a real order lands. The estimate takes the owner's assumption (0.5c a
contract each time an order fills, near the 2s figure app/trading/exec_cost_model.py measured) off
paper realized P&L. A closed position fills twice (entry and exit) unless it was held to settlement,
which is not a fill. Paper only, one book at a time, and display only.
"""
from decimal import Decimal

from trading_core.domain import slippage
from trading_core.domain.slippage import (LIVE_SLIPPAGE_PER_CONTRACT_FILL, after_live_slippage, contract_fills,
                                          paper_estimate, per_fill_cents, slippage_cost)


def test_the_assumption_is_half_a_cent_a_contract_per_fill():
    assert LIVE_SLIPPAGE_PER_CONTRACT_FILL == Decimal("0.005")
    assert per_fill_cents() == 0.5
    # It is the cost of the measured move, not a guess: the module cites where it comes from.
    src = open(slippage.__file__, encoding="utf-8").read()
    assert "exec_cost_model.py" in src and "PR #32" in src and "0.55c" in src


def test_an_exited_trade_fills_twice_and_a_settled_one_once():
    assert contract_fills(10, held_to_settlement=False) == 20  # bought, then sold before settlement
    assert contract_fills(10, held_to_settlement=True) == 10   # bought, then settled at $1 or $0: no exit fill
    assert contract_fills(0, False) == 0


def test_the_estimate_takes_the_assumption_off_each_contract_fill():
    # 10 contracts exited (20 fills) and 4 held to settlement (4 fills): 24 x 0.5c = $0.12.
    fills = contract_fills(10, False) + contract_fills(4, True)
    assert slippage_cost(fills) == Decimal("0.120")
    assert after_live_slippage(Decimal("5.0000"), fills) == 4.88
    # Losses get worse, never better.
    assert after_live_slippage(Decimal("-1.2500"), fills) == -1.37


def test_held_to_settlement_costs_half_what_exiting_does():
    held = after_live_slippage(Decimal("3.2000"), contract_fills(20, True))
    sold = after_live_slippage(Decimal("3.2000"), contract_fills(20, False))
    assert (held, sold) == (3.10, 3.00)


def test_money_goes_through_cents_once_half_up():
    # One fill is half a cent: rounded once, half up away from zero, as every page rounds money.
    assert after_live_slippage(Decimal("0"), 1) == -0.01
    assert after_live_slippage(0.7449999999999999, 1) == 0.74  # float noise from a trade-by-trade sum goes first
    assert after_live_slippage(Decimal("0.0100"), 2) == 0.0 and str(after_live_slippage(Decimal("0.0100"), 2)) == "0.0"


def test_it_is_for_the_paper_book_only():
    est = paper_estimate("paper", Decimal("3.2000"), 20)
    assert est == {"pnl": 3.10, "per_fill_cents": 0.5}
    for book in ("live", "demo", "all", "", None):
        assert paper_estimate(book, Decimal("3.2000"), 20) is None
    # No closed fill, nothing to estimate.
    assert paper_estimate("paper", Decimal("0"), 0) is None and paper_estimate("paper", 0, None) is None
