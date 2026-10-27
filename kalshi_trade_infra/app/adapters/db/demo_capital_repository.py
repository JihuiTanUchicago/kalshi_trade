"""Demo (sandbox) capital. Demo places REAL orders on Kalshi's sandbox for real fills, but the money is
ours: P&L from those fills is applied to a capital we set, not the real demo-account balance."""
from __future__ import annotations

from typing import Dict, Optional

from app.adapters.db.paper_ledger_repository import STARTING_PAPER_BALANCE
from app.adapters.db.position_repository import realized_pnl
from trading_core.domain.money import cents, exact


def demo_account(cur, user_id: int) -> tuple:
    """(capital, pnl_base) for the user's app-controlled demo account."""
    cur.execute("SELECT demo_capital, demo_pnl_base FROM app_users WHERE id=%s", (user_id,))
    r = cur.fetchone()
    if not r:
        return (STARTING_PAPER_BALANCE, 0.0)
    return (float(r["demo_capital"]), float(r["demo_pnl_base"]))


def reload_demo(cur, user_id: int, amount: float) -> None:
    """Set demo starting capital to `amount` and snapshot current realized P&L as the new
    baseline, so demo P&L shown resets to 0 and future fills accrue from there."""
    base = realized_pnl(cur, user_id, "demo")
    cur.execute(
        "UPDATE app_users SET demo_capital=%s, demo_pnl_base=%s WHERE id=%s",
        (round(amount, 4), round(base, 4), user_id),
    )


def demo_equity(cur, user_id: int, realized: Optional[float] = None) -> Dict:
    """Demo money as cost-basis equity: capital + realized P&L since the last reload. Mirrors
    paper's equity convention (open positions valued at cost), so the three buckets line up.
    `realized` is the all-time realized demo P&L when the caller has already read it."""
    capital, base = demo_account(cur, user_id)
    net = exact(realized_pnl(cur, user_id, "demo") if realized is None else realized) - exact(base)
    return {
        "capital": cents(capital),
        "realized": cents(net),
        "equity": cents(exact(capital) + net),
        "roi": round(float(net) / capital, 4) if capital > 0 else None,
        # Realized demo P&L from before the last reload, which `realized` leaves out. Nonzero means the
        # shown P&L is "since reload", while the track record still counts every closed demo trade.
        "before_reload": cents(base),
    }
