"""How Kalshi settles a market, and what a contract is worth at it: one reading for the live engine
(engine.settle_due), market history (hist_markets) and every backtest, so research pays a cancelled
market exactly what the live book is paid.

Kalshi settles a binary market it cancels (a postponed game, a retired player) with result "scalar",
status "finalized", and a fair price it sets in settlement_value_dollars (often $0.50, else near the
last trade). 9,723 of ~496k settled markets in our series ended that way (scan of 2026-10-31), nearly
all sports. Stdlib only, no I/O."""
from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple, Union

# The fallback for a final market with no result and no published price: unwound at cost.
VOID = "void"
# Statuses after which Kalshi will not change a market's result again.
_FINAL_STATUSES = ("settled", "finalized")

# What Sources.result reports for a ticker: "yes" or "no"; VOID; a YES payout per contract in
# [0, 1] for a market Kalshi settled at a price (a fair-value settlement); None = not settled yet.
Settlement = Union[str, float, None]


def _settlement_value(m: Dict) -> Optional[float]:
    """The YES payout per contract Kalshi published for a settled market, in dollars, or None."""
    raw = m.get("settlement_value_dollars")
    scale = 1.0
    if raw in (None, ""):
        raw, scale = m.get("settlement_value"), 100.0  # the older field, in cents
    try:
        v = float(raw) / scale
    except (TypeError, ValueError):
        return None
    return v if 0.0 <= v <= 1.0 else None


def market_settlement(m: Dict) -> Settlement:
    """How Kalshi settled one market object (GET /markets/{ticker}'s "market").

    A YES/NO result is final as soon as Kalshi publishes it. Without one, the market is only settled
    once its status is final: then it paid the published settlement value, or (no value) it was
    voided. A market with no result and a non-final status (closed, determined, disputed) is None:
    try again next round."""
    result = (m.get("result") or "").lower()
    if result in ("yes", "no"):
        return result
    status = (m.get("status") or "").lower()
    if result == VOID or status in ("void", "voided"):
        return VOID
    if status not in _FINAL_STATUSES:
        return None
    value = _settlement_value(m)
    return VOID if value is None else value


def settlement_terms(settlement: Settlement, side: str, qty: float, entry_price: float,
                     entry_fee: float) -> Tuple[float, float, float]:
    """(payout, exit_price, pnl) of holding `qty` contracts of `side` to a settled market.

    YES/NO pays $1 a contract to the winning side. A price settlement pays its value to YES and one
    minus it to NO. A void refunds what the contracts cost; the entry fee is not refunded (the
    conservative reading of Kalshi's void terms, so paper never books more than live would)."""
    if settlement == VOID:
        payout = qty * entry_price
        exit_price = entry_price
    elif isinstance(settlement, str):
        exit_price = 1.0 if settlement == side else 0.0
        payout = qty * exit_price
    else:
        exit_price = float(settlement) if side == "yes" else 1.0 - float(settlement)
        payout = qty * exit_price
    return payout, exit_price, payout - qty * entry_price - entry_fee


def settlement_label(settlement: Settlement) -> str:
    """How a settled ticker reads in the ledger: "YES", "NO", "VOID (refunded at cost)", or for a
    market Kalshi cancelled and settled at a fair price, "VOID at $0.50 a YES contract"."""
    if settlement == VOID:
        return "VOID (refunded at cost)"
    if isinstance(settlement, str):
        return settlement.upper()
    return "VOID at $%.2f a YES contract" % float(settlement)


# hist_markets stores a fair-price settlement as result VOID with its YES value in settle_value.
def dataset_result(row: Mapping) -> Settlement:
    """A hist_markets row's settlement as datasets carry it (Dataset.results): "yes"/"no", or the YES
    payout per contract of a market Kalshi cancelled at a fair price. None for a void with no value."""
    result = (row.get("result") or "").lower()
    if result in ("yes", "no"):
        return result
    value = row.get("settle_value")
    return float(value) if value is not None else None


def yes_no_or_value(settlement: Settlement) -> bool:
    """True for a result a backtest can pay: YES, NO, or a settlement price."""
    return settlement in ("yes", "no") or isinstance(settlement, float)


def contract_payout(settlement: Settlement, side: str) -> float:
    """What one contract of `side` pays at a dataset settlement. A missing result pays 0 (a loss), as
    the backtest has always booked it."""
    if isinstance(settlement, str):
        return 1.0 if settlement == side else 0.0
    if settlement is None:
        return 0.0
    return float(settlement) if side == "yes" else 1.0 - float(settlement)
