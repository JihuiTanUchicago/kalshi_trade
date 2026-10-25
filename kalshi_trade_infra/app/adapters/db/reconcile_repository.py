"""Live position reconciliation reads: which users to reconcile and their internal book, for app/reconcile.py."""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional

from app.adapters.db.sql import now_utc


# All DB access for app/reconcile.py lives here (repository layer), so the
# reconcile/classify logic stays testable against a fake cursor.


# How long after a user's last live close they are still reconciled. A sell booked
# against a position Kalshi no longer held leaves the book FLAT and the account
# SHORT - the 2026-09-27 failure - so "has open positions" alone would skip
# exactly the account that most needs checking.
RECONCILE_RECENT_DAYS = 3


def users_to_reconcile(cur) -> List[int]:
    """Every user with a live Kalshi key whose book could diverge from the
    exchange: an open live position, a live close in the last few days, or a
    discrepancy that is still open (so it can resolve and lift its halt)."""
    since = now_utc() - timedelta(days=RECONCILE_RECENT_DAYS)
    cur.execute(
        """SELECT DISTINCT k.user_id FROM app_kalshi_keys k
           WHERE EXISTS (SELECT 1 FROM app_positions p WHERE p.user_id=k.user_id AND p.mode='live'
                           AND (p.status='open' OR p.closed_at >= %s))
              OR EXISTS (SELECT 1 FROM app_position_reconcile r
                           WHERE r.user_id=k.user_id AND r.status='open')
           ORDER BY k.user_id""",
        (since,),
    )
    return [int(r["user_id"]) for r in cur.fetchall()]


def legacy_live_book_rows(cur) -> List[Dict]:
    """The legacy engine's open positions (live_positions, YES only), shaped like
    live_book_by_ticker_side rows. They sit on the operator's Kalshi account, so
    reconciling that account without them reads every one as untracked."""
    cur.execute(
        "SELECT market_ticker AS ticker, 'yes' AS side, COALESCE(SUM(qty_contracts),0) AS qty "
        "FROM live_positions GROUP BY market_ticker"
    )
    return cur.fetchall()


def live_book_by_ticker_side(cur, user_id: int) -> List[Dict]:
    """This user's open LIVE positions, summed by (ticker, side). The caller folds
    these into a signed net per ticker (YES positive, NO negative)."""
    cur.execute(
        """SELECT ticker, side, COALESCE(SUM(qty),0) AS qty FROM app_positions
           WHERE user_id=%s AND mode='live' AND status='open'
           GROUP BY ticker, side""",
        (user_id,),
    )
    return cur.fetchall()


def get_position(cur, position_id: int) -> Optional[Dict]:
    """One position row by id (used by crash-recovery to book/close an intent's own position)."""
    cur.execute("SELECT * FROM app_positions WHERE id=%s", (position_id,))
    return cur.fetchone()
