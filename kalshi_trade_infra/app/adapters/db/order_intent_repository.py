"""The durable order-intent log (EXECUTION_RISK_HARDENING P0-1): one row per real exchange order, written before the POST and settled after, plus the TCA reads over it."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.adapters.db.sql import _json, now_utc


# A row is written and COMMITTED before every real exchange order and updated after, so every
# order has a durable, idempotent identity. client_order_id == intent_id, reused on any retry.


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def insert_order_intent(
    cur, intent_id: str, deployment_id: int, user_id: int, mode: str, action: str, side: str,
    ticker: str, qty: int, limit_price: float, client_order_id: str, position_id: Optional[int] = None,
    reason: Optional[str] = None, market_close_time: Optional[datetime] = None,
) -> None:
    """Record an order intent as 'sent' BEFORE the exchange POST. The caller commits this (its own
    transaction) so the intent is durable even if the process dies the instant after the order is
    placed — recovery then reconciles it against the exchange."""
    now = now_utc()
    cur.execute(
        """INSERT INTO app_order_intents
             (intent_id, deployment_id, user_id, position_id, mode, action, side, ticker, qty,
              limit_price, client_order_id, status, reason, market_close_time, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'sent',%s,%s,%s,%s)""",
        (intent_id, deployment_id, user_id, position_id, mode, action, side, ticker, int(qty),
         limit_price, client_order_id, reason, _naive_utc(market_close_time), now, now),
    )


def mark_order_intent(
    cur, intent_id: str, status: str, external_order_id: Optional[str] = None, fill_qty: Optional[int] = None,
    fill_price: Optional[float] = None, fee: Optional[float] = None, raw_json: Optional[dict] = None,
) -> bool:
    """Update an intent's status/outcome (e.g. 'unfilled', 'error'). Fill fields are only overwritten
    when provided (COALESCE), so a status-only update keeps whatever was recorded."""
    cur.execute(
        """UPDATE app_order_intents
             SET status=%s, external_order_id=COALESCE(%s,external_order_id), fill_qty=COALESCE(%s,fill_qty),
                 fill_price=COALESCE(%s,fill_price), fee=COALESCE(%s,fee), raw_json=COALESCE(%s,raw_json),
                 updated_at=%s
           WHERE intent_id=%s""",
        (status, external_order_id, fill_qty, fill_price, fee, _json(raw_json), now_utc(), intent_id),
    )
    return cur.rowcount == 1


def claim_intent_booking(
    cur, intent_id: str, external_order_id: Optional[str] = None, fill_qty: Optional[int] = None,
    fill_price: Optional[float] = None, fee: Optional[float] = None, raw_json: Optional[dict] = None,
) -> bool:
    """Atomically transition an intent to 'booked' (recording the fill), only if it is not ALREADY
    booked. Returns True iff THIS caller won the transition — the single-booking guard that makes the
    live path and crash-recovery race-safe: whoever books first wins, the loser books nothing. Must
    run inside the same transaction as the position/ledger write it guards (see repo.transaction)."""
    cur.execute(
        """UPDATE app_order_intents
             SET status='booked', external_order_id=COALESCE(%s,external_order_id), fill_qty=COALESCE(%s,fill_qty),
                 fill_price=COALESCE(%s,fill_price), fee=COALESCE(%s,fee), raw_json=COALESCE(%s,raw_json),
                 updated_at=%s
           WHERE intent_id=%s AND status<>'booked'""",
        (external_order_id, fill_qty, fill_price, fee, _json(raw_json), now_utc(), intent_id),
    )
    return cur.rowcount == 1


def open_sent_intents(cur, older_than_seconds: int = 30, limit: int = 200) -> List[Dict]:
    """Intents still 'sent' (POST issued, outcome unknown) older than a grace window — the
    unresolved in-flight orders a crash/lost-response can leave (the F1/F2 smoke alarm)."""
    cutoff = now_utc() - timedelta(seconds=int(older_than_seconds))
    cur.execute(
        "SELECT * FROM app_order_intents WHERE status='sent' AND created_at <= %s ORDER BY created_at LIMIT %s",
        (cutoff, int(limit)),
    )
    return cur.fetchall()


def ticker_has_inflight_intent(cur, user_id: int, ticker: str, within_seconds: int, mode: str) -> bool:
    """True when this user has a ``mode`` order on ``ticker`` still 'sent' (outcome unknown) from
    the last ``within_seconds``. The exchange position is per account, so this spans every deployment
    of that mode; demo and live are separate accounts, so neither holds the other's ticker."""
    cutoff = now_utc() - timedelta(seconds=int(within_seconds))
    cur.execute(
        "SELECT 1 AS x FROM app_order_intents WHERE user_id=%s AND ticker=%s AND mode=%s AND status='sent' "
        "AND created_at >= %s LIMIT 1",
        (int(user_id), ticker, str(mode), cutoff),
    )
    return cur.fetchone() is not None


def order_intents_between(cur, since: datetime, until: Optional[datetime] = None,
                          modes=("live", "demo")) -> List[Dict]:
    """Real-order intents (live/demo) created in [since, until), oldest first, for TCA."""
    until = until or now_utc()
    marks = ",".join(["%s"] * len(modes))
    cur.execute(
        "SELECT * FROM app_order_intents WHERE created_at >= %s AND created_at < %s "
        "AND mode IN (" + marks + ") ORDER BY created_at",
        (_naive_utc(since), _naive_utc(until), *modes),
    )
    return cur.fetchall()


def yes_quote_at(cur, ticker: str, ts: datetime, max_lag_seconds: int = 30) -> Optional[Dict]:
    """The first recorded YES top-of-book for ``ticker`` at or after ``ts`` (within ``max_lag_seconds``):
    the websocket tick table first, the REST snapshot table as the fallback. None if neither has one."""
    start = _naive_utc(ts)
    end = start + timedelta(seconds=int(max_lag_seconds))
    for sql in (
        "SELECT yes_bid_dollars, yes_ask_dollars, observed_at_utc AS at FROM forward_quote_ticks "
        "WHERE market_ticker=%s AND observed_at_utc >= %s AND observed_at_utc < %s "
        "ORDER BY observed_at_utc LIMIT 1",
        "SELECT yes_bid_dollars, yes_ask_dollars, snapshot_time_utc AS at FROM forward_quotes "
        "WHERE market_ticker=%s AND snapshot_time_utc >= %s AND snapshot_time_utc < %s "
        "ORDER BY snapshot_time_utc LIMIT 1",
    ):
        cur.execute(sql, (ticker, start, end))
        row = cur.fetchone()
        if row and row.get("yes_bid_dollars") is not None and row.get("yes_ask_dollars") is not None:
            return {"yes_bid": float(row["yes_bid_dollars"]), "yes_ask": float(row["yes_ask_dollars"]), "at": row["at"]}
    return None
