"""Deployments: a strategy running in paper, demo or live mode, its status, its scan of the market, and the stats its gates read."""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from app.adapters.db.sql import now_utc
from app.adapters.db.strategy_repository import _strategy_row


def create_deployment(cur, user_id: int, strategy_id: int, market: str, mode: str) -> int:
    now = now_utc()
    cur.execute(
        """INSERT INTO app_deployments (user_id, strategy_id, market, mode, status, created_at, updated_at)
           VALUES (%s,%s,%s,%s,'running',%s,%s)""",
        (user_id, strategy_id, market, mode, now, now),
    )
    return cur.lastrowid


_DEPLOYMENT_SELECT = """
    SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.status, d.status_reason, d.last_decision_ts,
           d.created_at, d.updated_at, d.last_scan_json, d.last_scan_at, s.title, s.direction, s.spec_json, s.result_json,
           COALESCE(SUM(CASE WHEN p.status='closed' THEN p.pnl END),0) AS realized_pnl,
           COUNT(CASE WHEN p.status='closed' THEN 1 END) AS closed_trades,
           COUNT(CASE WHEN p.status='closed' AND p.pnl > 0 THEN 1 END) AS wins,
           COUNT(CASE WHEN p.status='open' THEN 1 END) AS open_positions
    FROM app_deployments d
    JOIN app_strategies s ON s.id=d.strategy_id
    LEFT JOIN app_positions p ON p.deployment_id=d.id
"""


def list_deployments(cur, user_id: int, include_stopped: bool = False) -> List[Dict]:
    sql = _DEPLOYMENT_SELECT + " WHERE d.user_id=%s"
    if not include_stopped:
        sql += " AND d.status <> 'stopped'"
    sql += " GROUP BY d.id ORDER BY d.id DESC"
    cur.execute(sql, (user_id,))
    return [_strategy_row(r) for r in cur.fetchall()]


def get_deployment(cur, user_id: int, deployment_id: int) -> Optional[Dict]:
    cur.execute(_DEPLOYMENT_SELECT + " WHERE d.id=%s AND d.user_id=%s GROUP BY d.id", (deployment_id, user_id))
    row = cur.fetchone()
    return _strategy_row(row) if row else None


def deployment_closed_stats(cur, deployment_id: int) -> Tuple[int, float]:
    """(closed position rows, their summed P&L) for one deployment."""
    cur.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(pnl),0) AS p FROM app_positions WHERE deployment_id=%s AND status='closed'",
        (deployment_id,),
    )
    row = cur.fetchone() or {}
    return int(row.get("n") or 0), float(row.get("p") or 0)


def paper_round_trips(cur, user_id: int, strategy_id: int, ref_prefix: str = "sim:") -> List[Dict]:
    """Closed PAPER round trips of one strategy that filled through the simulated venue, oldest
    first. One row per entry fill (a part-filled exit's slices share the entry's order_ref and are
    summed), so a single trade is never counted twice. Legacy instant fills (no order_ref) are
    excluded: they are not evidence of what live execution would earn."""
    cur.execute(
        """SELECT p.order_ref, SUM(p.pnl) AS pnl, MIN(p.opened_at) AS opened_at, MAX(p.closed_at) AS closed_at,
                  MAX(p.ticker) AS ticker
           FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
           WHERE p.user_id=%s AND d.strategy_id=%s AND p.mode='paper' AND p.order_ref LIKE %s
           GROUP BY p.order_ref
           HAVING SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END)=0
           ORDER BY MIN(p.opened_at)""",
        (user_id, strategy_id, ref_prefix + "%"),
    )
    return [{"pnl": float(r["pnl"] or 0), "opened_at": r["opened_at"], "closed_at": r["closed_at"],
             "ticker": r.get("ticker")} for r in cur.fetchall()]


def track_record_rows(cur, user_id: int) -> List[Dict]:
    """Every trade in the user's book for the track record page (app/track_record.py): one row per
    (mode, deployment, entry fill). Partial-exit slices share the entry's order_ref and are summed;
    `open_slices` > 0 marks a trade not yet fully closed. A row with no order_ref is its own trade.
    One pass over idx_pos_user; the strategy title rides along so the page needs no second query."""
    cur.execute(
        """SELECT p.mode, MAX(d.strategy_id) AS strategy_id, MAX(s.title) AS title, MAX(s.market) AS market,
                  MAX(p.order_ref) AS order_ref,
                  SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END) AS open_slices,
                  COALESCE(SUM(p.pnl),0) AS pnl,
                  COALESCE(SUM(p.entry_fee + COALESCE(p.exit_fee,0)),0) AS fees,
                  COALESCE(SUM(p.qty * p.entry_price),0) AS cost,
                  MIN(p.opened_at) AS opened_at, MAX(p.closed_at) AS closed_at
           FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
           LEFT JOIN app_strategies s ON s.id=d.strategy_id
           WHERE p.user_id=%s
           GROUP BY p.mode, p.deployment_id, COALESCE(p.order_ref, CONCAT('row:', p.id))""",
        (user_id,),
    )
    return cur.fetchall()


def paper_progress(cur, user_id: int, strategy_ids: List[int], ref_prefix: str = "sim:") -> Dict[int, Tuple[int, float]]:
    """{strategy_id: (closed realistic paper round trips, their net P&L)} for the given strategies,
    in one query. Same counting as `paper_round_trips` (one row per order_ref, still-open slices
    excluded); a cheap progress readout for the autopilot panel, which polls often."""
    if not strategy_ids:
        return {}
    marks = ",".join(["%s"] * len(strategy_ids))
    cur.execute(
        """SELECT t.strategy_id, COUNT(*) AS trips, COALESCE(SUM(t.pnl),0) AS pnl FROM (
             SELECT d.strategy_id, p.order_ref, SUM(p.pnl) AS pnl
             FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
             WHERE p.user_id=%s AND p.mode='paper' AND p.order_ref LIKE %s AND d.strategy_id IN (""" + marks + """)
             GROUP BY d.strategy_id, p.order_ref
             HAVING SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END)=0) t
           GROUP BY t.strategy_id""",
        (user_id, ref_prefix + "%", *strategy_ids),
    )
    return {int(r["strategy_id"]): (int(r["trips"] or 0), float(r["pnl"] or 0)) for r in cur.fetchall()}


def running_deployments(cur, market: str) -> List[Dict]:
    cur.execute(
        """SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.last_decision_ts, s.spec_json, s.result_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.status='running' AND d.market=%s ORDER BY d.id""",
        (market,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def deployments_with_open_positions(cur, market: str) -> List[Dict]:
    """Paused deployments still need their open positions settled."""
    cur.execute(
        """SELECT DISTINCT d.id, d.user_id, d.mode, s.spec_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           JOIN app_positions p ON p.deployment_id=d.id AND p.status='open'
           WHERE d.market=%s""",
        (market,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def paused_deployments_with_open_positions(cur, market: str) -> List[Dict]:
    """Paused/stopped deployments that still hold open positions — the auto-flatten sweep closes
    these so a non-running deployment never keeps exposure nothing is actively managing. (Running
    deployments manage their own exits via the spec + force-sell, so they are excluded here.)"""
    cur.execute(
        """SELECT DISTINCT d.id, d.user_id, d.mode, s.spec_json, s.result_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           JOIN app_positions p ON p.deployment_id=d.id AND p.status='open'
           WHERE d.market=%s AND d.status IN ('paused','stopped')""",
        (market,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def set_deployment_status(cur, user_id: int, deployment_id: int, status: str, reason: Optional[str] = None) -> bool:
    cur.execute(
        "UPDATE app_deployments SET status=%s, status_reason=%s, updated_at=%s WHERE id=%s AND user_id=%s AND status<>'stopped'",
        (status, reason, now_utc(), deployment_id, user_id),
    )
    return cur.rowcount == 1


def set_deployment_scan(cur, deployment_id: int, scan: Dict) -> None:
    """The latest entry scan (spec.entry_scan) for one deployment: why its last decision did or
    didn't buy. Overwritten every decision; a readout only, never read by trading."""
    now = now_utc()
    cur.execute("UPDATE app_deployments SET last_scan_json=%s, last_scan_at=%s WHERE id=%s",
                (json.dumps(scan, separators=(",", ":")), now, deployment_id))
    cur.execute("INSERT INTO app_deployment_scan_days (deployment_id, day, outcome, n) VALUES (%s,%s,%s,1) "
                "ON DUPLICATE KEY UPDATE n=n+1", (deployment_id, now.date(), scan_outcome(scan)))


def scan_outcome(scan: Dict) -> str:
    if scan.get("qualifying"):
        return "qualified"
    if not scan.get("contracts"):
        return "no contracts"
    return (scan.get("blocked_at") or "other")[:160]


def scan_tally(cur, deployment_ids: List[int], days: int = 1) -> Dict[int, Dict[str, int]]:
    """{deployment_id: {outcome: decisions}} over the last `days` UTC days (today included)."""
    if not deployment_ids:
        return {}
    cur.execute("SELECT deployment_id, outcome, SUM(n) AS n FROM app_deployment_scan_days WHERE deployment_id IN (%s) "
                "AND day >= %%s GROUP BY deployment_id, outcome" % ",".join(["%s"] * len(deployment_ids)),
                (*deployment_ids, (now_utc() - timedelta(days=max(1, days) - 1)).date()))
    out: Dict[int, Dict[str, int]] = {}
    for r in cur.fetchall():
        out.setdefault(int(r["deployment_id"]), {})[r["outcome"]] = int(r["n"] or 0)
    return out


def set_deployment_strategy(cur, user_id: int, deployment_id: int, strategy_id: int) -> bool:
    cur.execute(
        "UPDATE app_deployments SET strategy_id=%s, updated_at=%s WHERE id=%s AND user_id=%s",
        (strategy_id, now_utc(), deployment_id, user_id),
    )
    return cur.rowcount == 1


def claim_decision(cur, deployment_id: int, decision_ts: int) -> bool:
    """At most one decision per deployment per slot, however many engines
    run: whoever moves last_decision_ts forward owns the slot."""
    cur.execute(
        "UPDATE app_deployments SET last_decision_ts=%s WHERE id=%s AND status='running' AND last_decision_ts < %s",
        (decision_ts, deployment_id, decision_ts),
    )
    return cur.rowcount == 1
