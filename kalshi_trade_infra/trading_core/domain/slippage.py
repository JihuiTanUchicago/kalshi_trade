"""What a paper P&L might have been after the slippage a live order typically pays: an estimate to
show beside paper realized P&L, never P&L itself.

A paper fill buys at the ask and sells at the bid of a quote up to 2s old (SimulatedVenue's
max_quote_age_seconds) and pays Kalshi's taker fee, so it pays the spread and the fee a live taker
order pays. What it never pays is the price moving between that quote and a real order landing. The
estimate takes a fixed amount off every contract each time an order fills: a closed position's entry
fill and its exit fill, or its entry fill alone when it was held to settlement (settlement is not a
fill). Display only: no fill, gate, gate input or trade decision reads it.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Optional

from trading_core.domain.money import cents, exact

# Dollars a contract, each time an order fills as a taker: 0.5 cents. Measured on Kalshi's own books by
# app/trading/exec_cost_model.py (PR #32): the ask a taker decided on moved up by a mean 0.2c by 1s and
# 0.55c by 2s (it moved up 12-16% of the time at 1s, 27-34% at 2s). Paper quotes can be up to 2s old,
# so the assumption sits near the 2s figure. Owner's decision, 2026-10-27.
LIVE_SLIPPAGE_PER_CONTRACT_FILL = Decimal("0.005")


def contract_fills(qty, held_to_settlement: bool) -> int:
    """Contracts times taker fills for one closed position row: `qty` contracts bought (the entry fill)
    and sold again (the exit fill), or only bought when the row was held to settlement."""
    return int(qty) * (1 if held_to_settlement else 2)


def slippage_cost(fills) -> Decimal:
    """The estimate's charge, in dollars, for `fills` contract fills (contract_fills summed)."""
    return LIVE_SLIPPAGE_PER_CONTRACT_FILL * int(fills or 0)


def after_live_slippage(realized, fills) -> float:
    """Paper realized P&L `realized` (a sum of stored money) less the typical live slippage on its
    `fills` contract fills, rounded once to the cent as every page rounds money (money.cents)."""
    return cents(exact(realized) - slippage_cost(fills))


def per_fill_cents() -> float:
    """The assumption in cents a contract per fill, as a page says it (0.5)."""
    return float(LIVE_SLIPPAGE_PER_CONTRACT_FILL * 100)


PAPER = "paper"  # the only book the estimate is for: live and demo fills are real, their P&L already pays it


def paper_estimate(book: str, realized, fills) -> Optional[Dict[str, float]]:
    """What a page shows beside one book's realized P&L: {"pnl": the estimate, "per_fill_cents": the
    assumption}, for the paper book only and only once it has a closed fill. None for live and demo
    (never estimated) and for a book with no closed trade. One book at a time: books are never summed."""
    if book != PAPER or not int(fills or 0):
        return None
    return {"pnl": after_live_slippage(realized, fills), "per_fill_cents": per_fill_cents()}
