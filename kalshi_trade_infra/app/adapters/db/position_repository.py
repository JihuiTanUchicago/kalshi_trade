"""Positions: the open and closed rows a deployment books, their marks, partial exits and close claims."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.adapters.db.sql import now_utc


def open_positions(cur, deployment_id: int) -> List[Dict]:
    cur.execute("SELECT * FROM app_positions WHERE deployment_id=%s AND status='open' ORDER BY id", (deployment_id,))
    return cur.fetchall()


def deployment_realized_series(cur, deployment_id: int) -> List[float]:
    """Realized P&L of each closed position, oldest first — the engine folds this into a
    cumulative equity curve for the drawdown force-sell. Same `status='closed'` definition
    the loss guard uses, so the two agree on what counts as realized."""
    cur.execute(
        "SELECT COALESCE(pnl,0) AS pnl FROM app_positions WHERE deployment_id=%s AND status='closed' ORDER BY closed_at, id",
        (deployment_id,),
    )
    return [float(r["pnl"]) for r in cur.fetchall()]


def update_marks(cur, market: str, marks: Dict[str, float], now: datetime) -> int:
    """Stamp the current YES bid on every open position whose ticker is in `marks`.
    Called from the engine tick, which already holds the live book — no extra API calls.
    `market` scopes the update so one market's tick can't touch another's rows."""
    if not marks:
        return 0
    ts = now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now
    n = 0
    for ticker, mark in marks.items():
        if mark is None:
            continue
        cur.execute(
            """UPDATE app_positions p JOIN app_deployments d ON d.id=p.deployment_id
               SET p.mark_price=%s, p.mark_ts=%s
               WHERE p.status='open' AND p.ticker=%s AND d.market=%s""",
            (round(float(mark), 4), ts, ticker, market),
        )
        n += cur.rowcount
    return n


def market_has_open_positions(cur, market: str) -> bool:
    """Whether any deployment on `market` holds an open position — so the engine knows to refresh
    marks (unrealized P&L + the drawdown guard read them) every tick, not only when a decision is due."""
    cur.execute(
        "SELECT 1 FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id "
        "WHERE p.status='open' AND d.market=%s LIMIT 1", (market,))
    return cur.fetchone() is not None


def user_positions(cur, user_id: int, status: str = "open", limit: int = 100) -> List[Dict]:
    cur.execute(
        """SELECT p.*, s.title FROM app_positions p
           JOIN app_deployments d ON d.id=p.deployment_id JOIN app_strategies s ON s.id=d.strategy_id
           WHERE p.user_id=%s AND p.status=%s ORDER BY p.id DESC LIMIT %s""",
        (user_id, status, limit),
    )
    return cur.fetchall()


def positions_for_strategy(cur, user_id: int, strategy_id: int, status: str = "open") -> List[Dict]:
    """Open positions a strategy is holding right now, across its deployments."""
    cur.execute(
        """SELECT p.*, d.mode FROM app_positions p
           JOIN app_deployments d ON d.id=p.deployment_id
           WHERE d.strategy_id=%s AND p.user_id=%s AND p.status=%s ORDER BY p.id DESC""",
        (strategy_id, user_id, status),
    )
    return cur.fetchall()


def insert_position(
    cur, deployment_id: int, user_id: int, mode: str, ticker: str, side: str, qty: int, entry_price: float,
    entry_fee: float, market_close_time: datetime, order_ref: Optional[str] = None,
) -> int:
    cur.execute(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
             market_close_time, opened_at, status, order_ref)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s)""",
        (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
         market_close_time.astimezone(timezone.utc).replace(tzinfo=None) if market_close_time.tzinfo else market_close_time,
         now_utc(), order_ref),
    )
    return cur.lastrowid


# Close reasons that are the safety stop selling a loser (position stop, spec stop, drawdown sweep).
STOP_EXIT_REASONS = ("stop", "stop_loss", "drawdown")


def unscored_early_exits(cur, market: str, now: datetime, days: int = 30, limit: int = 20) -> List[Dict]:
    """Positions on `market` that closed before settlement (stop, take-profit, flatten...) whose
    contract has now closed, not yet scored against holding to the end. Newest first, bounded."""
    cur.execute(
        """SELECT p.id, p.ticker, p.side, p.qty, p.entry_price, p.entry_fee
           FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
           WHERE d.market=%s AND p.status='closed' AND p.close_reason<>'settled' AND p.hold_pnl IS NULL
             AND p.market_close_time <= %s AND p.closed_at >= %s
           ORDER BY p.id DESC LIMIT %s""",
        (market, now.replace(tzinfo=None), (now - timedelta(days=days)).replace(tzinfo=None), int(limit)),
    )
    return cur.fetchall()


def score_early_exit(cur, position_id: int, result: str, hold_pnl: float) -> bool:
    cur.execute("UPDATE app_positions SET settle_result=%s, hold_pnl=%s WHERE id=%s AND hold_pnl IS NULL",
                (result, round(hold_pnl, 4), position_id))
    return cur.rowcount == 1


def early_exit_scorecard(cur, user_id: int, mode: str = "paper", since: Optional[datetime] = None) -> Dict[str, Dict]:
    """Per close reason: how many positions exited before settlement, their realized P&L, and (for
    the ones whose contract has settled) what holding to the end would have made. `saved` > 0 means
    selling early beat holding. This is the evidence for the stop setting, on the live book.

    One position past the stop flattens the WHOLE deployment, so a 'stop' row mixes the breacher with
    healthy positions sold alongside it. Those (exit above the user's stop line) also appear under
    stop['collateral'], the evidence for whether the stop should close only the breaching position."""
    collateral = ("p.close_reason='stop' AND p.entry_price>0 "
                  "AND p.exit_price > p.entry_price * (1 - u.position_stop_pct / 100)")
    sql = ("""SELECT p.close_reason AS reason, COUNT(*) AS exits, COUNT(p.hold_pnl) AS scored,
                     COALESCE(SUM(p.pnl),0) AS pnl,
                     COALESCE(SUM(CASE WHEN p.hold_pnl IS NOT NULL THEN p.pnl END),0) AS scored_pnl,
                     COALESCE(SUM(p.hold_pnl),0) AS hold_pnl,
                     COALESCE(SUM(CASE WHEN {c} THEN 1 END),0) AS c_exits,
                     COALESCE(SUM(CASE WHEN {c} AND p.hold_pnl IS NOT NULL THEN 1 END),0) AS c_scored,
                     COALESCE(SUM(CASE WHEN {c} AND p.hold_pnl IS NOT NULL THEN p.pnl - p.hold_pnl END),0) AS c_saved
              FROM app_positions p JOIN app_users u ON u.id=p.user_id
              WHERE p.user_id=%s AND p.mode=%s AND p.status='closed' AND p.close_reason<>'settled'""").format(c=collateral)
    args: List = [user_id, mode]
    if since is not None:
        sql += " AND p.closed_at >= %s"
        args.append(since.replace(tzinfo=None))
    cur.execute(sql + " GROUP BY p.close_reason", args)
    out = {}
    for r in cur.fetchall():
        scored_pnl, hold = float(r["scored_pnl"] or 0), float(r["hold_pnl"] or 0)
        row = {"exits": int(r["exits"]), "scored": int(r["scored"]),
               "pnl": round(float(r["pnl"] or 0), 2), "scored_pnl": round(scored_pnl, 2),
               "hold_pnl": round(hold, 2), "saved": round(scored_pnl - hold, 2)}
        if int(r.get("c_exits") or 0):
            row["collateral"] = {"exits": int(r["c_exits"]), "scored": int(r.get("c_scored") or 0),
                                 "saved": round(float(r.get("c_saved") or 0), 2)}
        out[r["reason"] or "other"] = row
    return out


def close_position(cur, position_id: int, exit_price: float, exit_fee: float, pnl: float, reason: str) -> bool:
    """Idempotent: only an open position closes, so a retried tick cannot
    book the same exit twice."""
    cur.execute(
        """UPDATE app_positions SET status='closed', exit_price=%s, exit_fee=%s, pnl=%s, close_reason=%s, closed_at=%s
           WHERE id=%s AND status='open'""",
        (exit_price, exit_fee, round(pnl, 4), reason, now_utc(), position_id),
    )
    return cur.rowcount == 1


def book_partial_exit(cur, pos: Dict, fill_qty: int, exit_price: float, exit_fee: float, pnl: float,
                      reason: str) -> bool:
    """Record a PARTIAL exit fill: shrink the open position to the un-filled remainder and book the
    `fill_qty` sold contracts as their own closed position row (so the realized P&L is counted by the
    loss/drawdown guards and settlement never re-counts the sold contracts). The open row's entry fee
    is split pro-rata with the sold slice.

    Reduce-then-book ordering + the `status='open'` guard make it idempotent and crash-safe: a retried
    tick reads the already-shrunk qty, and a crash between the two statements can only LEAVE a slice
    un-booked, never DOUBLE-count or re-sell. MUST run inside a transaction (see repo.transaction) so
    the two statements commit together. Returns False (books nothing) if the row is no longer open."""
    total_qty = int(pos["qty"])
    fill_qty = int(fill_qty)
    if not 0 < fill_qty < total_qty:
        raise ValueError("partial fill must be between 1 and qty-1, got %d of %d" % (fill_qty, total_qty))
    entry_fee = float(pos["entry_fee"])
    filled_entry_fee = round(entry_fee * fill_qty / total_qty, 4)
    cur.execute(
        "UPDATE app_positions SET qty=%s, entry_fee=%s WHERE id=%s AND status='open'",
        (total_qty - fill_qty, round(entry_fee - filled_entry_fee, 4), pos["id"]),
    )
    if cur.rowcount != 1:
        return False  # already closed/shrunk by another tick — book nothing (idempotent)
    cur.execute(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price,
             entry_fee, market_close_time, opened_at, status, exit_price, exit_fee, pnl, close_reason,
             closed_at, order_ref)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'closed',%s,%s,%s,%s,%s,%s)""",
        (pos["deployment_id"], pos["user_id"], pos["mode"], pos["ticker"], pos["side"], fill_qty,
         pos["entry_price"], filled_entry_fee, pos["market_close_time"], pos["opened_at"],
         exit_price, exit_fee, round(pnl, 4), reason, now_utc(), pos.get("order_ref")),
    )
    return True


def insert_closed_position(
    cur, deployment_id: int, user_id: int, mode: str, ticker: str, side: str, qty: int,
    entry_price: float, entry_fee: float, exit_price: float, exit_fee: float, pnl: float,
    reason: str, market_close_time: datetime, order_ref: Optional[str] = None,
    opened_at: Optional[datetime] = None, closed_at: Optional[datetime] = None,
) -> int:
    """Record a round-trip (bought then immediately sold again) as a single CLOSED position row.
    `opened_at`/`closed_at` (naive UTC) default to now; a replayed paper trade passes its own.

    ONE atomic INSERT, so an autocommit connection can never leave a phantom OPEN leg if it dies
    mid-write (an open-then-close pair of statements could). Used by the cross-pair unwind: the
    excess leg that was flattened on the exchange must count toward realized P&L (the loss and
    drawdown guards sum closed-row pnl) without ever becoming a held position."""
    close = (market_close_time.astimezone(timezone.utc).replace(tzinfo=None)
             if market_close_time.tzinfo else market_close_time)
    cur.execute(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price,
             entry_fee, market_close_time, opened_at, status, exit_price, exit_fee, pnl, close_reason,
             closed_at, order_ref)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'closed',%s,%s,%s,%s,%s,%s)""",
        (deployment_id, user_id, mode, ticker, side, qty, entry_price, round(entry_fee, 4), close,
         opened_at or now_utc(), exit_price, round(exit_fee, 4), round(pnl, 4), reason, closed_at or now_utc(),
         order_ref),
    )
    return cur.lastrowid


def claim_position_close(cur, position_id: int, claimant: str, lease_seconds: int = 300) -> bool:
    """Single-actor guard for the order-PLACING risk sweeps (drawdown force-sell): at most one engine
    may send a real close for a given open position within the lease, so two engines can never both
    sell it into an unintended short. Mirrors claim_decision. The owner can re-claim its own lease
    (so a failed close retries next tick); a different engine only after the lease expires."""
    cutoff = now_utc() - timedelta(seconds=int(lease_seconds))
    cur.execute(
        """UPDATE app_positions SET close_claim=%s, close_claim_ts=%s
           WHERE id=%s AND status='open' AND (close_claim IS NULL OR close_claim=%s OR close_claim_ts < %s)""",
        (claimant, now_utc(), position_id, claimant, cutoff),
    )
    return cur.rowcount == 1


def realized_pnl(cur, user_id: int, mode: str, since: Optional[datetime] = None) -> float:
    sql = "SELECT COALESCE(SUM(pnl),0) AS p FROM app_positions WHERE user_id=%s AND mode=%s AND status='closed'"
    params: List[Any] = [user_id, mode]
    if since is not None:
        sql += " AND closed_at >= %s"
        params.append(since)
    cur.execute(sql, params)
    return float(cur.fetchone()["p"])


def user_open_exposure(cur, user_id: int, mode: Optional[str] = None) -> Dict:
    """Live, cross-deployment open exposure for the per-user portfolio caps: how many open
    positions the user holds and their total entry notional (qty * entry_price), in dollars.
    `mode` narrows it to one mode's positions (paper entries count only paper); None counts all."""
    if mode is None:
        cur.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(qty*entry_price),0) AS notional "
            "FROM app_positions WHERE user_id=%s AND status='open'",
            (user_id,),
        )
    else:
        cur.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(qty*entry_price),0) AS notional "
            "FROM app_positions WHERE user_id=%s AND status='open' AND mode=%s",
            (user_id, mode),
        )
    return cur.fetchone()


def daily_pnl(cur, user_id: int, mode: str, days: int = 60) -> List[Dict]:
    cur.execute(
        """SELECT DATE(closed_at) AS d, SUM(pnl) AS pnl FROM app_positions
           WHERE user_id=%s AND mode=%s AND status='closed' AND closed_at >= %s
           GROUP BY DATE(closed_at) ORDER BY d""",
        (user_id, mode, now_utc() - timedelta(days=days)),
    )
    return cur.fetchall()
