"""Deployments: a strategy running in paper, demo or live mode, its status, its scan of the market, and the stats its gates read."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.adapters.db.sql import now_utc
from app.adapters.db.strategy_repository import DEMO_DIRECTION, _strategy_row

_EPOCH = datetime(1970, 1, 1)  # naive UTC, as the DATETIME columns are read


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


def list_deployments_brief(cur, user_id: int) -> List[Dict]:
    """The same deployments as list_deployments (not stopped, newest first), with the strategy fields
    and without the position totals (realized_pnl, closed_trades, wins, open_positions). Those totals
    read every position each deployment ever booked (20k for a busy trader), and the autopilot panel,
    which polls every 20s, needs them only for a just-paused one (deployment_closed_totals)."""
    cur.execute(
        """SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.status, d.status_reason, d.last_decision_ts,
                  d.created_at, d.updated_at, d.last_scan_json, d.last_scan_at, s.title, s.direction, s.spec_json, s.result_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.user_id=%s AND d.status <> 'stopped' ORDER BY d.id DESC""",
        (user_id,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def list_deployments_for_display(cur, user_id: int, strategy_id: Optional[int] = None) -> List[Dict]:
    """list_deployments(cur, user_id) as the dashboard and the strategy list show it: the same rows,
    totals and order. Each deployment's positions are summed first, in a derived table read through
    idx_pos_dep, and joined to their deployment row after that. list_deployments groups the joined
    rows instead, so every one of a busy trader's 20k positions carries its strategy's spec and
    result JSON through the GROUP BY (64ms against 31ms). Display only: the engine and the gates
    keep calling list_deployments. `strategy_id` keeps one strategy's deployments (the strategy
    page), the same rows list_deployments filtered to it, without summing every other one's."""
    one = (int(strategy_id),) if strategy_id is not None else ()
    only_pd, only_d = (" AND pd.strategy_id=%s", " AND d.strategy_id=%s") if one else ("", "")
    cur.execute(
        """SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.status, d.status_reason, d.last_decision_ts,
                  d.created_at, d.updated_at, d.last_scan_json, d.last_scan_at, s.title, s.direction, s.spec_json, s.result_json,
                  COALESCE(t.realized_pnl,0) AS realized_pnl, COALESCE(t.closed_trades,0) AS closed_trades,
                  COALESCE(t.wins,0) AS wins, COALESCE(t.open_positions,0) AS open_positions
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           LEFT JOIN (SELECT p.deployment_id,
                             SUM(CASE WHEN p.status='closed' THEN p.pnl END) AS realized_pnl,
                             COUNT(CASE WHEN p.status='closed' THEN 1 END) AS closed_trades,
                             COUNT(CASE WHEN p.status='closed' AND p.pnl > 0 THEN 1 END) AS wins,
                             COUNT(CASE WHEN p.status='open' THEN 1 END) AS open_positions
                      FROM app_deployments pd STRAIGHT_JOIN app_positions p FORCE INDEX (idx_pos_dep) ON p.deployment_id=pd.id
                      WHERE pd.user_id=%s AND pd.status <> 'stopped'""" + only_pd + """
                      GROUP BY p.deployment_id) t ON t.deployment_id=d.id
           WHERE d.user_id=%s AND d.status <> 'stopped'""" + only_d + """ ORDER BY d.id DESC""",
        (user_id, *one, user_id, *one),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


DISPLAY_TOTALS = ("realized_pnl", "closed_trades", "wins", "open_positions")


def deployment_strategies(cur, user_id: int) -> Dict[int, int]:
    """{deployment_id: strategy_id} for every deployment the user has, stopped ones included (an
    adjustment re-points a deployment at a new strategy row, set_deployment_strategy)."""
    cur.execute("SELECT id, strategy_id FROM app_deployments WHERE user_id=%s", (user_id,))
    return {int(r["id"]): int(r["strategy_id"]) for r in cur.fetchall()}


def deployment_rows_for_display(cur, user_id: int, strategy_id: Optional[int] = None) -> List[Dict]:
    """The rows list_deployments_for_display returns, without their position totals (DISPLAY_TOTALS)
    and before _strategy_row: the same deployments, columns and order, read from the deployments and
    their strategies alone (no position is read). services.book_memo adds the totals it kept from the
    full read while the user's positions have not changed."""
    one = (int(strategy_id),) if strategy_id is not None else ()
    cur.execute(
        """SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.status, d.status_reason, d.last_decision_ts,
                  d.created_at, d.updated_at, d.last_scan_json, d.last_scan_at, s.title, s.direction, s.spec_json, s.result_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.user_id=%s AND d.status <> 'stopped'""" + (" AND d.strategy_id=%s" if one else "") + """ ORDER BY d.id DESC""",
        (user_id, *one),
    )
    return cur.fetchall()


def removed_deployments(cur, user_id: int, strategy_id: Optional[int] = None) -> List[Dict]:
    """The user's removed (stopped) deployments, newest first: id, strategy_id, mode, market,
    created_at, removed_at (the row's updated_at, which a stopped row keeps) and title (None when its
    strategy row was deleted). The deployments alone, through idx_dep_user; no position is read, so a
    caller adds their realized P&L with deployment_closed_totals. `strategy_id` keeps one strategy's.
    Display only: the Deploy board and the strategy page name the money the listed deployments leave out."""
    one = (int(strategy_id),) if strategy_id is not None else ()
    cur.execute(
        """SELECT d.id, d.strategy_id, d.mode, d.market, d.created_at, d.updated_at AS removed_at, s.title
           FROM app_deployments d LEFT JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.user_id=%s AND d.status='stopped'""" + (" AND d.strategy_id=%s" if one else "") + " ORDER BY d.id DESC",
        (user_id, *one),
    )
    return list(cur.fetchall())


def deployment_closed_totals(cur, deployment_ids: List[int]) -> Dict[int, Tuple[int, Any]]:
    """{deployment_id: (closed positions, their summed P&L)}, as list_deployments counts closed_trades
    and realized_pnl, for the given deployments in one read over idx_pos_dep (deployment_id, status).
    A deployment with no closed position is absent."""
    ids = sorted({int(i) for i in deployment_ids})
    if not ids:
        return {}
    cur.execute(
        "SELECT deployment_id, COUNT(*) AS n, COALESCE(SUM(pnl),0) AS pnl FROM app_positions "
        "WHERE deployment_id IN (" + ",".join(["%s"] * len(ids)) + ") AND status='closed' GROUP BY deployment_id",
        tuple(ids),
    )
    return {int(r["deployment_id"]): (int(r["n"]), r["pnl"]) for r in cur.fetchall()}


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


def paper_fills_for_gate(cur, user_id: int, strategy_id: int, ref_prefix: str = "sim:") -> List[Dict]:
    """The same closed realistic paper round trips as `paper_round_trips`, with what the forward
    gate scores: contracts, entry and exit price (quantity-weighted over exit slices), fees and how
    the trip ended (`settled` only when every slice settled). Oldest entry first."""
    cur.execute(
        """SELECT p.order_ref, MAX(p.ticker) AS ticker, SUM(p.qty) AS qty,
                  SUM(p.qty * p.entry_price) / NULLIF(SUM(p.qty), 0) AS entry_price,
                  SUM(p.qty * p.exit_price) / NULLIF(SUM(p.qty), 0) AS exit_price,
                  SUM(p.entry_fee + COALESCE(p.exit_fee, 0)) AS fees, SUM(p.pnl) AS pnl,
                  MIN(CASE WHEN p.close_reason='settled' THEN 1 ELSE 0 END) AS settled,
                  MIN(p.opened_at) AS opened_at, MAX(p.closed_at) AS closed_at
           FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
           WHERE p.user_id=%s AND d.strategy_id=%s AND p.mode='paper' AND p.order_ref LIKE %s
           GROUP BY p.order_ref
           HAVING SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END)=0
           ORDER BY MIN(p.opened_at)""",
        (user_id, strategy_id, ref_prefix + "%"),
    )
    return [{"ticker": r.get("ticker"), "qty": int(r["qty"] or 0), "entry_price": float(r["entry_price"] or 0),
             "exit_price": float(r["exit_price"] or 0), "fees": float(r["fees"] or 0), "pnl": float(r["pnl"] or 0),
             "settled": bool(r["settled"]), "opened_at": r["opened_at"], "closed_at": r["closed_at"]}
            for r in cur.fetchall()]


def track_record_rows(cur, user_id: int) -> List[Dict]:
    """Every trade in the user's book for the track record page (app/trading/track_record.py): one row per
    (mode, deployment, entry fill). Partial-exit slices share the entry's order_ref and are summed;
    `open_slices` > 0 marks a trade not yet fully closed; its `pnl` is what the sold slices already
    realized and `open_cost` what is still held at cost. A row with no order_ref is its own trade.
    Two reads: the user's positions grouped alone through idx_pos_user (joined to every deployment, the
    planner walked all users' deployments and their positions), then the strategy of each deployment
    in it, once. Rows come in the order of the group key, as the single join returned them. A trade
    whose deployment row is gone stays out, as the inner join left it out. `dep_status` is the
    deployment's status now, so the page can say which strategies are stopped (they stay in).
    services.book_memo makes the same rows from the same three steps, keeping the first."""
    trades = track_record_trades(cur, user_id)
    if not trades:
        return []
    return track_record_join(trades, track_record_deployments(cur, trades))


# track_record_trades' sums and times, packed into one comma-joined text per trade: pymysql decodes
# every column of every row in Python, and a 23k-trade book's ten columns were ~220ms of the read.
# The DECIMAL sums come back as their own text (what pymysql reads a DECIMAL column from), the times
# as whole seconds; a NULL is '' (CONCAT_WS skips a NULL, which would shift the fields after it).
_TRADE_PACKED = (
    "CONCAT_WS(',', SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END), COALESCE(SUM(p.pnl),0), "
    "COALESCE(SUM(p.entry_fee + COALESCE(p.exit_fee,0)),0), COALESCE(SUM(p.qty * p.entry_price),0), "
    "COALESCE(SUM(CASE WHEN p.status='open' THEN p.qty * p.entry_price END),0), "
    "COALESCE(TIMESTAMPDIFF(SECOND, '1970-01-01', MIN(p.opened_at)),''), "
    "COALESCE(TIMESTAMPDIFF(SECOND, '1970-01-01', MAX(p.closed_at)),''))")
_TRADE_FIELDS = ("open_slices", "pnl", "fees", "cost", "open_cost")


def track_record_trades(cur, user_id: int) -> List[Dict]:
    """track_record_rows' first read: the user's positions grouped per trade, before each trade's
    deployment and strategy are attached: {mode, deployment_id, order_ref, open_slices, pnl, fees,
    cost, open_cost (Decimals, as the sums read), opened_s, closed_s (whole seconds, None for none)}.
    It reads positions alone, so services.book_memo keeps it while the user's positions are unchanged."""
    cur.execute(
        "SELECT p.mode, p.deployment_id, MAX(p.order_ref) AS order_ref, " + _TRADE_PACKED + """ AS v
           FROM app_positions p
           WHERE p.user_id=%s
           GROUP BY p.mode, p.deployment_id, COALESCE(p.order_ref, CONCAT('row:', p.id))
           ORDER BY p.mode, p.deployment_id, COALESCE(p.order_ref, CONCAT('row:', p.id))""",
        (user_id,),
    )
    out = []
    for r in cur.fetchall():
        v = r.pop("v")
        v = (v.decode() if isinstance(v, (bytes, bytearray)) else v).split(",")
        r.update(zip(_TRADE_FIELDS, map(Decimal, v[:5])))
        r["opened_s"] = int(v[5]) if v[5] else None
        r["closed_s"] = int(v[6]) if v[6] else None
        out.append(r)
    return out


def track_record_deployments(cur, trades: List[Dict]) -> Dict[int, Dict]:
    """{deployment_id: {id, strategy_id, status, title, market}} for the deployments the trades are in,
    in one read (the strategy's title, or None when the strategy row is gone)."""
    dep_ids = sorted({t["deployment_id"] for t in trades})
    if not dep_ids:
        return {}
    cur.execute(
        "SELECT d.id, d.strategy_id, d.status, s.title, COALESCE(s.market, d.market) AS market FROM app_deployments d LEFT JOIN app_strategies s ON s.id=d.strategy_id "
        "WHERE d.id IN (" + ",".join(["%s"] * len(dep_ids)) + ")",
        tuple(dep_ids),
    )
    return {d["id"]: d for d in cur.fetchall()}


def track_record_join(trades: List[Dict], deps: Dict[int, Dict], seconds: bool = False) -> List[Dict]:
    """track_record_rows' rows from its two reads: each trade with its deployment's strategy and status,
    the times rebuilt as naive-UTC datetimes; a trade whose deployment row is gone is left out.
    `seconds` gives the times as the unix seconds they were read as instead (opened_ts/closed_ts, which
    track_record.prepare takes as they are), skipping a datetime per time each way."""
    def at(s):
        return None if s is None else _EPOCH + timedelta(seconds=int(s))

    out = []
    for t in trades:
        d = deps.get(t["deployment_id"])
        if d is None:
            continue
        row = {"mode": t["mode"], "strategy_id": d["strategy_id"], "title": d["title"], "market": d["market"],
               "dep_status": d["status"],
               "order_ref": t["order_ref"], "open_slices": t["open_slices"], "pnl": t["pnl"], "fees": t["fees"],
               "cost": t["cost"], "open_cost": t["open_cost"]}
        if seconds:
            row["opened_ts"], row["closed_ts"] = t["opened_s"], t["closed_s"]
        else:
            row["opened_at"], row["closed_at"] = at(t["opened_s"]), at(t["closed_s"])
        out.append(row)
    return out


# Both paper readouts below start from the strategies' deployments and read each one's positions
# through idx_pos_dep, instead of scanning every position the user ever held (the autopilot panel
# polls them). STRAIGHT_JOIN keeps that order; the WHERE clauses are unchanged, so are the counts.
_PAPER_SOURCE = "app_deployments d STRAIGHT_JOIN app_positions p FORCE INDEX (idx_pos_dep) ON p.deployment_id=d.id"


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
             FROM """ + _PAPER_SOURCE + """
             WHERE p.user_id=%s AND p.mode='paper' AND p.order_ref LIKE %s AND d.strategy_id IN (""" + marks + """)
             GROUP BY d.strategy_id, p.order_ref
             HAVING SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END)=0) t
           GROUP BY t.strategy_id""",
        (user_id, ref_prefix + "%", *strategy_ids),
    )
    return {int(r["strategy_id"]): (int(r["trips"] or 0), float(r["pnl"] or 0)) for r in cur.fetchall()}


def paper_round_trips_by_strategy(cur, user_id: int, strategy_ids: List[int], ref_prefix: str = "sim:") -> Dict[int, List[Dict]]:
    """{strategy_id: its closed realistic paper round trips}, each list exactly what
    `paper_round_trips` returns for that strategy (one row per order_ref, still-open slices left out,
    oldest first), for several strategies in one read through idx_pos_dep. A display readout (the
    Deploy board's road to live); the live gate keeps calling paper_round_trips."""
    if not strategy_ids:
        return {}
    marks = ",".join(["%s"] * len(strategy_ids))
    cur.execute(
        """SELECT d.strategy_id, p.order_ref, SUM(p.pnl) AS pnl, MIN(p.opened_at) AS opened_at,
                  MAX(p.closed_at) AS closed_at, MAX(p.ticker) AS ticker
           FROM """ + _PAPER_SOURCE + """
           WHERE p.user_id=%s AND p.mode='paper' AND p.order_ref LIKE %s AND d.strategy_id IN (""" + marks + """)
           GROUP BY d.strategy_id, p.order_ref
           HAVING SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END)=0
           ORDER BY d.strategy_id, MIN(p.opened_at)""",
        (user_id, ref_prefix + "%", *strategy_ids),
    )
    out: Dict[int, List[Dict]] = {}
    for r in cur.fetchall():
        out.setdefault(int(r["strategy_id"]), []).append(
            {"pnl": float(r["pnl"] or 0), "opened_at": r["opened_at"], "closed_at": r["closed_at"], "ticker": r.get("ticker")})
    return out


def book_trade_stats(cur, user_id: int, strategy_ids: List[int], ref_prefix: str = "sim:") -> Dict[int, Dict[str, Dict]]:
    """{strategy_id: {mode: {trades, pnl, pnl_sq, wins, cost}}} over each strategy's completed round
    trips, one book (mode) at a time and never summed across books, for the backtest comparison
    (services.backtest_check). A trade is one entry fill: partial-exit slices share its order_ref and
    are summed (a row with no order_ref is its own trade), and a trade with a slice still open is
    left out until it closes. Paper counts only fills through the simulated venue (order_ref 'sim:'),
    as the track record does. Every deployment of the strategy counts, stopped ones included. Read
    through idx_pos_dep from the strategies' deployments, like the paper readouts above."""
    if not strategy_ids:
        return {}
    marks = ",".join(["%s"] * len(strategy_ids))
    cur.execute(
        """SELECT t.strategy_id, t.mode, COUNT(*) AS trades, COALESCE(SUM(t.pnl),0) AS pnl,
                  COALESCE(SUM(t.pnl * t.pnl),0) AS pnl_sq, SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                  COALESCE(SUM(t.cost),0) AS cost FROM (
             SELECT d.strategy_id, p.mode, SUM(p.pnl) AS pnl, SUM(p.qty * p.entry_price) AS cost
             FROM """ + _PAPER_SOURCE + """
             WHERE d.user_id=%s AND d.strategy_id IN (""" + marks + """)
               AND (p.mode <> 'paper' OR p.order_ref LIKE %s)
             GROUP BY d.strategy_id, p.mode, p.deployment_id, COALESCE(p.order_ref, CONCAT('row:', p.id))
             HAVING SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END)=0) t
           GROUP BY t.strategy_id, t.mode""",
        (user_id, *strategy_ids, ref_prefix + "%"),
    )
    out: Dict[int, Dict[str, Dict]] = {}
    for r in cur.fetchall():
        out.setdefault(int(r["strategy_id"]), {})[r["mode"]] = {
            "trades": int(r["trades"] or 0), "pnl": float(r["pnl"] or 0), "pnl_sq": float(r["pnl_sq"] or 0),
            "wins": int(r["wins"] or 0), "cost": float(r["cost"] or 0)}
    return out


def paper_event_counts(cur, user_id: int, strategy_ids: List[int], ref_prefix: str = "sim:") -> Dict[int, int]:
    """{strategy_id: separate events among its closed realistic paper positions}, in one query. An
    event is the ticker minus its last segment, as agent._trip_event_key groups the live gate's
    events (every city's rain contract on one day is one event). A cheap panel readout."""
    if not strategy_ids:
        return {}
    marks = ",".join(["%s"] * len(strategy_ids))
    cur.execute(
        """SELECT d.strategy_id,
                  COUNT(DISTINCT SUBSTRING(p.ticker, 1, LENGTH(p.ticker) - LENGTH(SUBSTRING_INDEX(p.ticker, '-', -1)) - 1)) AS events
           FROM """ + _PAPER_SOURCE + """
           WHERE p.user_id=%s AND p.mode='paper' AND p.status='closed' AND p.order_ref LIKE %s
             AND d.strategy_id IN (""" + marks + """)
           GROUP BY d.strategy_id""",
        (user_id, ref_prefix + "%", *strategy_ids),
    )
    return {int(r["strategy_id"]): int(r["events"] or 0) for r in cur.fetchall()}


def running_deployments(cur, market: str) -> List[Dict]:
    cur.execute(
        """SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.last_decision_ts, s.spec_json, s.result_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.status='running' AND d.market=%s ORDER BY d.id""",
        (market,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def running_code_paper_deployments(cur) -> List[Dict]:
    """Running paper deployments whose strategy may be agent-written code (its spec JSON names
    "code"; the caller checks spec.is_code_spec). The engine never ticks these: the code paper
    replay (app/services/code_paper.py) trades them."""
    cur.execute(
        """SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.last_decision_ts, d.created_at, s.spec_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.status='running' AND d.mode='paper' AND s.spec_json LIKE %s ORDER BY d.id""",
        ('%"code"%',),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def deployment_order_refs(cur, deployment_id: int, ref_prefix: str) -> set:
    """The order_refs a deployment already booked under `ref_prefix` (a replay books each trade once)."""
    cur.execute("SELECT DISTINCT order_ref FROM app_positions WHERE deployment_id=%s AND order_ref LIKE %s",
                (deployment_id, ref_prefix + "%"))
    return {r["order_ref"] for r in cur.fetchall()}


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


# The strategies the autopilot itself put on paper. Every autopilot deploy writes a 'deploy'
# proposal already 'applied' (agent.act, auto_paper_probation) and never decided; one the user
# approved went through decide_proposal, which stamps decided_at, and a manual deploy writes none.
_AUTOPILOT_STRATEGIES = ("SELECT strategy_id FROM app_proposals WHERE user_id=%s AND kind='deploy' "
                         "AND status='applied' AND decided_at IS NULL AND strategy_id IS NOT NULL")


def activity_since(cur, user_id: int, since) -> Dict:
    """What happened since `since` besides trades, in one read: the changes the autopilot made on
    its own ({kind: n} of its applied, never-decided proposals: deploy, pause, resume, adjust...,
    plus `research`: the research sessions it started, its brief runs, which write no proposal),
    the research sessions started since then ({status: n}, the seeded example left out), and
    whether the user has ever run a research session of their own (`own_sessions`; a brand-new
    account's dashboard points at the example session instead). The last is a LIMIT 1 probe.
    Also what credits the usage debits took since then and over the last 7 days (`spent`: real
    money, the strip shows it apart from every book), and the strategies whose bell said they
    passed the paper forward gate or became ready for live (`milestones`: {kind: [strategy ids]}).
    Those passes happen days after the strategy was created, so passed_since never sees them."""
    week = now_utc() - timedelta(days=7)
    cur.execute(
        "SELECT 'ap' AS src, kind AS k, COUNT(*) AS n FROM app_proposals "
        "WHERE user_id=%s AND status='applied' AND decided_at IS NULL AND created_at>=%s GROUP BY kind "
        "UNION ALL SELECT 'run' AS src, status AS k, COUNT(*) AS n FROM app_agent_runs "
        "WHERE user_id=%s AND kind='research' AND created_at>=%s AND (direction IS NULL OR direction<>%s) GROUP BY status "
        "UNION ALL SELECT 'ap' AS src, 'research' AS k, COUNT(*) AS n FROM app_agent_runs "
        "WHERE user_id=%s AND kind='research' AND created_at>=%s AND brief=1 GROUP BY kind "
        "UNION ALL SELECT 'own' AS src, 'any' AS k, COUNT(*) AS n FROM (SELECT id FROM app_agent_runs "
        "WHERE user_id=%s AND kind='research' AND (direction IS NULL OR direction<>%s) LIMIT 1) o "
        "UNION ALL SELECT 'spent' AS src, 'since' AS k, COALESCE(-SUM(amount_usd),0) AS n FROM app_credit_ledger "
        "WHERE user_id=%s AND kind='usage' AND created_at>=%s "
        "UNION ALL SELECT 'spent' AS src, 'week' AS k, COALESCE(-SUM(amount_usd),0) AS n FROM app_credit_ledger "
        "WHERE user_id=%s AND kind='usage' AND created_at>=%s "
        "UNION ALL SELECT 'note' AS src, CONCAT(kind, ' ', COALESCE(link, '')) AS k, COUNT(*) AS n FROM app_notifications "
        "WHERE user_id=%s AND kind IN ('passed','live_ready') AND created_at>=%s GROUP BY kind, link",
        (user_id, since, user_id, since, DEMO_DIRECTION, user_id, since, user_id, DEMO_DIRECTION,
         user_id, since, user_id, week, user_id, since),
    )
    out: Dict[str, Any] = {"autopilot": {}, "runs": {}, "own_sessions": False,
                           "spent": {"since": 0.0, "week": 0.0}, "milestones": {"passed": [], "live_ready": []}}
    for r in cur.fetchall():
        if r["src"] == "own":
            out["own_sessions"] = int(r["n"]) > 0
        elif r["src"] == "spent":
            out["spent"][r["k"]] = float(r["n"] or 0)  # exact: the page rounds credits half up (credit_cents)
        elif r["src"] == "note":
            kind, _, link = str(r["k"]).partition(" ")
            m = re.match(r"^/strategies/(\d+)$", link)
            if m and kind in out["milestones"] and int(m.group(1)) not in out["milestones"][kind]:
                out["milestones"][kind].append(int(m.group(1)))
        else:
            out["autopilot" if r["src"] == "ap" else "runs"][r["k"]] = int(r["n"])
    for ids in out["milestones"].values():
        ids.sort(reverse=True)
    return out


def autopilot_paper_week(cur, user_id: int, since) -> Dict:
    """The autopilot's paper week for its scorecard, in one read: strategies it first put on paper
    since `since`, and the closed paper trades of its strategies since then (count and P&L)."""
    cur.execute(
        "SELECT st.started, pt.pnl, pt.trades FROM "
        "(SELECT COUNT(*) AS started FROM (SELECT d.strategy_id FROM app_deployments d "
        "  WHERE d.user_id=%s AND d.mode='paper' AND d.strategy_id IN (" + _AUTOPILOT_STRATEGIES + ") "
        "  GROUP BY d.strategy_id HAVING MIN(d.created_at) >= %s) s) st, "
        "(SELECT COALESCE(SUM(p.pnl),0) AS pnl, COUNT(*) AS trades FROM app_positions p "
        "  JOIN app_deployments d ON d.id=p.deployment_id "
        "  WHERE p.user_id=%s AND p.status='closed' AND p.closed_at >= %s AND p.mode='paper' "
        "  AND d.strategy_id IN (" + _AUTOPILOT_STRATEGIES + ")) pt",
        (user_id, user_id, since, user_id, since, user_id),
    )
    r = cur.fetchone() or {}
    return {"started": int(r.get("started") or 0), "pnl": float(r.get("pnl") or 0), "trades": int(r.get("trades") or 0)}


def paper_board_users(cur, limit: int) -> List[int]:
    """Up to `limit` users with a paper deployment running or paused (a road to live on their Deploy
    board), most recently signed in first."""
    cur.execute(
        """SELECT d.user_id FROM app_deployments d JOIN app_users u ON u.id=d.user_id
           WHERE d.mode='paper' AND d.status <> 'stopped'
           GROUP BY d.user_id ORDER BY MAX(u.last_login_at) DESC, d.user_id LIMIT %s""",
        (int(limit),),
    )
    return [int(r["user_id"]) for r in cur.fetchall()]
