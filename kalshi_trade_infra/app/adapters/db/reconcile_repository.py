"""Live position reconciliation reads: which users to reconcile and their internal book, for app/trading/reconcile.py."""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional

from app.adapters.db.sql import _json, now_utc


# All DB access for app/trading/reconcile.py lives here (repository layer), so the
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


def open_reconcile_rows(cur, user_id: int) -> List[Dict]:
    cur.execute(
        "SELECT ticker, kind, exchange_qty, book_qty, detected_at, updated_at FROM app_position_reconcile "
        "WHERE user_id=%s AND status='open'",
        (user_id,),
    )
    return cur.fetchall()


def live_entry_halts(cur, user_id: int) -> List[Dict]:
    """Open discrepancies that have survived at least one later sweep
    (updated_at moved past detected_at). While any exist, the engine opens no new
    LIVE position for this user. One sighting is not enough: a fill booked a beat
    after the sweep, or a settlement Kalshi zeroes before we book it, looks like
    a mismatch exactly once. The row resolving lifts the halt by itself."""
    cur.execute(
        "SELECT ticker, kind, exchange_qty, book_qty FROM app_position_reconcile "
        "WHERE user_id=%s AND status='open' AND updated_at > detected_at ORDER BY ticker",
        (user_id,),
    )
    return cur.fetchall()


def upsert_reconcile(cur, user_id: int, ticker: str, kind: str, exchange_qty: int, book_qty: int) -> None:
    """Record (or refresh) an open discrepancy. detected_at is preserved on an
    existing open row so the audit shows when the divergence first appeared; a row
    that had been marked resolved reopens with a fresh detected_at."""
    now = now_utc()
    cur.execute(
        """INSERT INTO app_position_reconcile
             (user_id, ticker, kind, exchange_qty, book_qty, status, detected_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,'open',%s,%s)
           ON DUPLICATE KEY UPDATE
             kind=VALUES(kind), exchange_qty=VALUES(exchange_qty), book_qty=VALUES(book_qty),
             updated_at=VALUES(updated_at),
             detected_at=IF(status='open', detected_at, VALUES(detected_at)),
             status='open', resolved_at=NULL""",
        (user_id, ticker, kind, int(exchange_qty), int(book_qty), now, now),
    )


def resolve_reconcile_except(cur, user_id: int, active_tickers: List[str]) -> int:
    """Mark resolved any still-open discrepancy for this user whose ticker is no
    longer divergent. Empty active set resolves them all."""
    if active_tickers:
        placeholders = ",".join(["%s"] * len(active_tickers))
        sql = ("UPDATE app_position_reconcile SET status='resolved', resolved_at=%s, updated_at=%s "
               "WHERE user_id=%s AND status='open' AND ticker NOT IN (" + placeholders + ")")
        params = [now_utc(), now_utc(), user_id, *active_tickers]
    else:
        sql = ("UPDATE app_position_reconcile SET status='resolved', resolved_at=%s, updated_at=%s "
               "WHERE user_id=%s AND status='open'")
        params = [now_utc(), now_utc(), user_id]
    cur.execute(sql, params)
    return cur.rowcount


def reconcile_deployment_id(cur, user_id: int, market: str) -> int:
    """The user's dedicated, PAUSED reconciliation deployment for `market`, created
    once on demand. Adopted orphans are booked under it so they appear in the user's
    positions and settle at expiry. It is paused (not running) deliberately: the
    engine's decision loop only trades running deployments, so an adopted orphan is
    never acted on by a synthetic spec — adoption records a row, nothing more."""
    cur.execute(
        """SELECT d.id FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.user_id=%s AND d.market=%s AND s.direction='reconcile' LIMIT 1""",
        (user_id, market),
    )
    row = cur.fetchone()
    if row:
        return int(row["id"])
    now = now_utc()
    spec = {"sizing": {"stake": 0.0, "max_positions": 0}, "rules": {}}
    cur.execute(
        """INSERT INTO app_strategies
             (user_id, market, direction, title, thesis, spec_json, status, created_at)
           VALUES (%s,%s,'reconcile',%s,%s,%s,'archived',%s)""",
        (user_id, market, "Reconciliation holdings",
         "System container for adopted untracked exchange positions. Not a tradable strategy.",
         _json(spec), now),
    )
    strategy_id = cur.lastrowid
    cur.execute(
        """INSERT INTO app_deployments (user_id, strategy_id, market, mode, status, status_reason, created_at, updated_at)
           VALUES (%s,%s,%s,'live','paused','Reconciliation container (adopted orphans)',%s,%s)""",
        (user_id, strategy_id, market, now, now),
    )
    return cur.lastrowid
