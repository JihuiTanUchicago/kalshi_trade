"""Demo track-record reads and writes for the live gate's demo check (app/services/demo_record.py): the open demo book, reconciliation sweeps, and a strategy's demo order outcomes."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from app.adapters.db.sql import _json, _loads, now_utc

# Intent statuses that settle an order: it was booked (filled) or confirmed unfilled. Anything else
# old enough is an order the app never accounted for.
RESOLVED_INTENT_STATUSES = ("booked", "unfilled")


def demo_book_by_ticker_side(cur, user_id: int) -> List[Dict]:
    """This user's open DEMO positions summed by (ticker, side), the shape reconcile.book_net_from_rows folds."""
    cur.execute(
        """SELECT ticker, side, COALESCE(SUM(qty),0) AS qty FROM app_positions
           WHERE user_id=%s AND mode='demo' AND status='open'
           GROUP BY ticker, side""",
        (user_id,),
    )
    return cur.fetchall()


def demo_key_users(cur) -> List[int]:
    cur.execute("SELECT user_id FROM app_kalshi_dev_keys ORDER BY user_id")
    return [int(r["user_id"]) for r in cur.fetchall()]


def has_demo_activity(cur, user_id: int) -> bool:
    """True once the user has ever sent a demo order or holds a demo position: only then is there a
    demo book worth reconciling."""
    cur.execute(
        """SELECT (EXISTS (SELECT 1 FROM app_order_intents WHERE user_id=%s AND mode='demo')
                OR EXISTS (SELECT 1 FROM app_positions WHERE user_id=%s AND mode='demo' AND status='open')) AS a""",
        (user_id, user_id),
    )
    row = cur.fetchone() or {}
    return bool(row.get("a"))


def insert_demo_sweep(cur, user_id: int, tickers: int, mismatches: List[Dict],
                      checked_at: Optional[datetime] = None) -> None:
    cur.execute(
        "INSERT INTO app_demo_reconcile_sweeps (user_id, checked_at, tickers, mismatches) VALUES (%s,%s,%s,%s)",
        (user_id, checked_at or now_utc(), int(tickers), _json(mismatches)),
    )


def demo_sweeps_since(cur, user_id: int, since: Optional[datetime]) -> List[Dict]:
    """The user's sweeps, oldest first, from the last one before `since` on (so a mismatch that
    started just before `since` and persisted into it still counts). None = every sweep."""
    if since is None:
        cur.execute("SELECT checked_at, tickers, mismatches FROM app_demo_reconcile_sweeps "
                    "WHERE user_id=%s ORDER BY checked_at, id", (user_id,))
    else:
        cur.execute(
            """SELECT checked_at, tickers, mismatches FROM app_demo_reconcile_sweeps
               WHERE user_id=%s AND checked_at >= COALESCE(
                 (SELECT MAX(checked_at) FROM app_demo_reconcile_sweeps WHERE user_id=%s AND checked_at < %s), %s)
               ORDER BY checked_at, id""",
            (user_id, user_id, since, since),
        )
    rows = cur.fetchall()
    for r in rows:
        r["mismatches"] = _loads(r.get("mismatches")) or []
    return rows


def demo_order_outcomes(cur, user_id: int, strategy_id: int, stale_before: datetime) -> Dict:
    """A strategy's demo orders across all its demo deployments: how many settled (booked or
    unfilled), how many were never accounted for (any other status, older than `stale_before`),
    and when the first one was sent. An order the demo exchange refused outright (settled
    'unfilled' with the refusal stored, see engine._settle_refused_intent) never reached the order
    book, so it is counted apart (`refused`, with the latest refusal) and never as a settled order."""
    cur.execute(
        """SELECT i.status, i.created_at, JSON_EXTRACT(i.raw_json, '$.refused') AS refused
           FROM app_order_intents i
           JOIN app_deployments d ON d.id=i.deployment_id
           WHERE i.user_id=%s AND i.mode='demo' AND d.strategy_id=%s
           ORDER BY i.created_at""",
        (user_id, strategy_id),
    )
    rows = cur.fetchall()
    refusals = [_loads(r["refused"]) for r in rows if r["status"] == "unfilled" and r.get("refused") is not None]
    resolved = sum(1 for r in rows if r["status"] in RESOLVED_INTENT_STATUSES) - len(refusals)
    unresolved = sum(1 for r in rows if r["status"] not in RESOLVED_INTENT_STATUSES
                     and r["created_at"] < stale_before)
    first = min((r["created_at"] for r in rows), default=None)
    return {"resolved": resolved, "unresolved": unresolved, "first_at": first,
            "booked": sum(1 for r in rows if r["status"] == "booked"),
            "refused": len(refusals), "last_refusal": refusals[-1] if refusals else None}
