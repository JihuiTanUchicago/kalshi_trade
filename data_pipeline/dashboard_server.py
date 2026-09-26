import html
import os
import base64
import ast
import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from data_pipeline.architecture.execution_kernel import DummyExecutionKernel
from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.live_trading_engine import (
    LIVE_MODELS,
    close_live_position,
    current_risk_state as live_current_risk_state,
    clear_model_paused as clear_live_model_paused,
    get_all_live_pause_states,
    latest_bid_for_ticker,
    load_settings as live_load_settings,
    place_limit_order,
    update_settings as live_update_settings,
)
from data_pipeline.sim_config import STARTING_CAPITAL
from data_pipeline.sim_repository import clear_model_paused, get_all_model_pause_states, get_model_recommendation_status

HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
AUTH_USER = os.getenv("DASHBOARD_USER", "todd")
AUTH_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
LIVE_TRADING_PASSWORD = os.getenv("LIVE_TRADING_PASSWORD", "iwanttoberich")
LIVE_COOKIE_NAME = "live_gate"
PAGE_SIZE = 100
TABLES = [
    "markets",
    "market_candles",
    "forward_quotes",
    "coinbase_ticks",
    "trade_quote_features_1m",
    "ws_quote_change_1m",
    "model_features_1m",
    "sim_model_predictions_1m",
    "sim_positions",
    "sim_trades",
    "sim_equity_1m",
    "sim_portfolio_20s",
    "model_research_runs",
    "model_research_feature_importance",
    "live_settings",
    "live_orders",
    "live_positions",
    "live_trades",
    "live_portfolio_20s",
    "live_model_state",
    "collector_state",
]
API_TABLES = [
    "model_features_1m",
    "trade_quote_features_1m",
    "forward_quotes",
    "coinbase_ticks",
    "sim_model_predictions_1m",
    "sim_trades",
    "sim_portfolio_20s",
    "model_research_runs",
    "model_research_feature_importance",
]
API_TIME_COLUMN = {
    "model_features_1m": "snapshot_minute_utc",
    "trade_quote_features_1m": "snapshot_minute_utc",
    "forward_quotes": "snapshot_time_utc",
    "coinbase_ticks": "snapshot_time_utc",
    "sim_model_predictions_1m": "snapshot_minute_utc",
    "sim_trades": "opened_at_utc",
    "sim_portfolio_20s": "snapshot_time_utc",
    "model_research_runs": "created_at_utc",
    "model_research_feature_importance": "created_at_utc",
}
API_MAX_LIMIT = 5000


def query_rows(table: str, page: int):
    offset = (page - 1) * PAGE_SIZE
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
        total = cur.fetchone()["c"]
        cur.execute(f"SELECT * FROM {table} ORDER BY 1 DESC LIMIT %s OFFSET %s", (PAGE_SIZE, offset))
        rows = cur.fetchall()
    conn.close()
    return total, rows


def _table_columns(table: str) -> List[str]:
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM {table}")
        cols = [r["Field"] for r in cur.fetchall()]
    conn.close()
    return cols


def query_api_rows(
    table: str,
    offset: int = 0,
    limit: int = 1000,
    start: Optional[str] = None,
    end: Optional[str] = None,
    columns: Optional[List[str]] = None,
):
    if table not in API_TABLES:
        raise ValueError("invalid table")
    safe_limit = max(1, min(API_MAX_LIMIT, int(limit)))
    safe_offset = max(0, int(offset))
    known_cols = _table_columns(table)
    selected_cols = known_cols
    if columns:
        cset = []
        for c in columns:
            c = str(c).strip()
            if c in known_cols:
                cset.append(c)
        if cset:
            selected_cols = cset
    select_sql = ", ".join([f"`{c}`" for c in selected_cols])
    where_parts = []
    params: List[Any] = []
    tcol = API_TIME_COLUMN.get(table)
    if tcol and start:
        where_parts.append(f"`{tcol}` >= %s")
        params.append(start)
    if tcol and end:
        where_parts.append(f"`{tcol}` <= %s")
        params.append(end)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM {table} {where_sql}", tuple(params))
        total = int(cur.fetchone()["c"])
        cur.execute(
            f"SELECT {select_sql} FROM {table} {where_sql} ORDER BY 1 ASC LIMIT %s OFFSET %s",
            tuple(params + [safe_limit, safe_offset]),
        )
        rows = cur.fetchall()
    conn.close()
    return {
        "table": table,
        "offset": safe_offset,
        "limit": safe_limit,
        "total": total,
        "returned": len(rows),
        "done": (safe_offset + len(rows)) >= total,
        "next_offset": safe_offset + len(rows),
        "rows": rows,
        "time_column": tcol,
        "columns": selected_cols,
    }


def _parse_window_hours(qs, default: int) -> int:
    try:
        return int(qs.get("window_hours", [str(default)])[0])
    except (ValueError, TypeError):
        return default


_TABLE_COUNTS_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_TABLE_COUNTS_LOCK = threading.Lock()
_TABLE_COUNTS_TTL_SECONDS = 30


def table_counts():
    """Row counts for the dashboard's table cards. Uses information_schema's
    TABLE_ROWS estimate rather than SELECT COUNT(*) per table - an exact count
    on InnoDB requires a full index scan, and doing that for ~20 tables
    (several hundred thousand rows each after 6+ months of collection) on
    every cache miss was slow enough to time out requests under load. This is
    a display metric, not a trading input, so an estimate is the right
    tradeoff - see the 2026-09-13 connection-exhaustion incident in PLAN.md."""
    now = time.time()
    with _TABLE_COUNTS_LOCK:
        cached = _TABLE_COUNTS_CACHE["data"]
        if cached is not None and (now - _TABLE_COUNTS_CACHE["ts"]) < _TABLE_COUNTS_TTL_SECONDS:
            return cached
    conn = get_db_conn()
    out = {t: 0 for t in TABLES}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN %s",
            (tuple(TABLES),),
        )
        for r in cur.fetchall():
            out[r["TABLE_NAME"]] = int(r["TABLE_ROWS"] or 0)
    conn.close()
    with _TABLE_COUNTS_LOCK:
        _TABLE_COUNTS_CACHE["data"] = out
        _TABLE_COUNTS_CACHE["ts"] = now
    return out


def latest_forward_status():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_time_utc, market_ticker, status, event_ticker
            FROM forward_quotes
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    conn.close()
    return row


def forward_feed_health(window_minutes: int = 120):
    conn = get_db_conn()
    out = {
        "window_minutes": window_minutes,
        "rows_total": 0,
        "rows_na": 0,
        "na_rate_pct": 0.0,
        "rows_real": 0,
        "gaps_missing_slots": 0,
        "misaligned_rows": 0,
        "last_snapshot_time": None,
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM forward_quotes
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
            """,
            (window_minutes,),
        )
        out["rows_total"] = cur.fetchone()["c"]

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM forward_quotes
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
              AND market_ticker='N/A'
            """,
            (window_minutes,),
        )
        out["rows_na"] = cur.fetchone()["c"]
        out["rows_real"] = max(0, out["rows_total"] - out["rows_na"])
        if out["rows_total"] > 0:
            out["na_rate_pct"] = round((out["rows_na"] / out["rows_total"]) * 100, 2)

        # 20-second alignment check: allowed seconds are 0,20,40.
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM forward_quotes
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
              AND MOD(SECOND(snapshot_time_utc), 20) <> 0
            """,
            (window_minutes,),
        )
        out["misaligned_rows"] = cur.fetchone()["c"]

        cur.execute(
            """
            SELECT snapshot_time_utc
            FROM forward_quotes
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
            ORDER BY snapshot_time_utc ASC
            """,
            (window_minutes,),
        )
        rows = cur.fetchall()
        times = [r["snapshot_time_utc"] for r in rows]
        if times:
            out["last_snapshot_time"] = str(times[-1])
            # Expect one row per 20-second slot now. To avoid false gap inflation from
            # legacy minute-only data, start gap analysis at first observed :20/:40 mark.
            start_time = times[0]
            for t in times:
                if t.second in (20, 40):
                    start_time = t
                    break
            slot_times = [t for t in times if t >= start_time]
            unique_slots = set(slot_times)
            span_seconds = int((slot_times[-1] - slot_times[0]).total_seconds())
            expected_slots = (span_seconds // 20) + 1
            out["gaps_missing_slots"] = max(0, expected_slots - len(unique_slots))

    conn.close()
    return out


def latest_model_guard():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_minute_utc, market_ticker, model_eligible, guard_status, guard_reasons_json
            FROM model_features_1m
            ORDER BY snapshot_minute_utc DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    conn.close()
    return row


def sim_summary():
    conn = get_db_conn()
    out = {"models": [], "open_positions": 0, "recent_trades": []}
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM sim_positions")
        out["open_positions"] = cur.fetchone()["c"]

        pause_states = get_all_model_pause_states(cur)

        cur.execute(
            """
            SELECT model_name, COUNT(*) closed_trades,
                   COALESCE(SUM(pnl_dollars),0) total_pnl,
                   COALESCE(SUM(pnl_dollars > 0),0) wins
            FROM sim_trades
            WHERE status='closed'
            GROUP BY model_name
            ORDER BY model_name
            """
        )
        model_rows = cur.fetchall()
        for r in model_rows:
            closed = int(r["closed_trades"] or 0)
            wins = int(r["wins"] or 0)
            pause = pause_states.get(r["model_name"])
            out["models"].append(
                {
                    "model_name": r["model_name"],
                    "closed_trades": closed,
                    "total_pnl": float(r["total_pnl"] or 0),
                    "win_rate": (wins / closed) if closed > 0 else None,
                    "paused": pause is not None,
                    "paused_reason": pause.get("paused_reason") if pause else None,
                }
            )

        cur.execute(
            """
            SELECT id, model_name, market_ticker, opened_at_utc, closed_at_utc, qty_contracts,
                   entry_price_dollars, exit_price_dollars, pnl_dollars, status
            FROM sim_trades
            ORDER BY id DESC
            LIMIT 20
            """
        )
        out["recent_trades"] = cur.fetchall()

        cur.execute(
            """
            SELECT snapshot_minute_utc, model_name, prob_yes, signal_yes, edge_est, train_rows, test_rows, brier, logloss, rf_regime
            FROM sim_model_predictions_1m
            ORDER BY snapshot_minute_utc DESC
            LIMIT 20
            """
        )
        out["recent_preds"] = cur.fetchall()
    conn.close()
    return out


def sim_health_summary():
    conn = get_db_conn()
    out = {"open_positions": 0, "models": []}
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM sim_positions")
        out["open_positions"] = int(cur.fetchone()["c"])
        pause_states = get_all_model_pause_states(cur)
        cur.execute(
            """
            SELECT model_name, COUNT(*) closed_trades, COALESCE(SUM(pnl_dollars),0) total_pnl
            FROM sim_trades
            WHERE status='closed'
            GROUP BY model_name
            ORDER BY model_name
            """
        )
        for r in cur.fetchall():
            pause = pause_states.get(r["model_name"])
            out["models"].append(
                {
                    "model_name": r["model_name"],
                    "closed_trades": int(r["closed_trades"] or 0),
                    "total_pnl": float(r["total_pnl"] or 0),
                    "paused": pause is not None,
                    "paused_reason": pause.get("paused_reason") if pause else None,
                }
            )
    conn.close()
    return out


def _bucket_key(p: float) -> str:
    lo = max(0.0, min(0.9, (int(p * 10) / 10.0)))
    hi = lo + 0.1
    return f"{lo:.1f}-{hi:.1f}"


_METRICS_CACHE: Dict[Any, Any] = {}
_METRICS_CACHE_LOCK = threading.Lock()
_METRICS_CACHE_TTL_SECONDS = 25


def _cached(cache_key, ttl_seconds, compute_fn):
    now = time.time()
    with _METRICS_CACHE_LOCK:
        entry = _METRICS_CACHE.get(cache_key)
        if entry is not None and (now - entry[1]) < ttl_seconds:
            return entry[0]
    data = compute_fn()
    with _METRICS_CACHE_LOCK:
        _METRICS_CACHE[cache_key] = (data, now)
    return data


def sim_metrics(window_hours: int = 6):
    return _cached(("sim_metrics", window_hours), _METRICS_CACHE_TTL_SECONDS, lambda: _sim_metrics_uncached(window_hours))


def build_scorecards(
    score_map: Dict[str, Dict],
    open_positions: List[Dict],
    pause_states: Dict[str, Dict],
    recommendation_fn,
) -> List[Dict]:
    """Portfolio Manager cards: one row per model, equity reconciled with PnL.

    Equity is derived from the same closed-trade aggregates that produce
    total_pnl (plus unrealized on any open position) rather than read off the
    latest sim_portfolio_20s snapshot. That snapshot is written by a separate
    20s process which is skipped entirely while a full sim recompute runs and
    can be down independently of this server, so its last row goes stale while
    total_pnl keeps moving - which showed up as a card reporting an equity that
    contradicted the PnL printed directly underneath it. Deriving it here also
    means a model that has traded but has no portfolio snapshot yet still gets
    a card instead of silently disappearing from the panel.
    """
    unrealized_by_model: Dict[str, float] = {}
    position_value_by_model: Dict[str, float] = {}
    for pos in open_positions:
        m = pos["model_name"]
        qty = int(pos["qty_contracts"])
        unrealized_by_model[m] = unrealized_by_model.get(m, 0.0) + float(pos["unrealized_pnl"])
        position_value_by_model[m] = position_value_by_model.get(m, 0.0) + float(pos["mark_bid"]) * qty

    scorecards: List[Dict] = []
    for m in sorted(set(score_map) | set(unrealized_by_model)):
        pause = pause_states.get(m)
        sc = dict(
            score_map.get(
                m,
                {
                    "model_name": m, "closed_trades": 0, "total_pnl": 0.0, "avg_trade_pnl": 0.0,
                    "win_rate": None,
                    "paused": pause is not None,
                    "paused_reason": pause.get("paused_reason") if pause else None,
                },
            )
        )
        unrealized = unrealized_by_model.get(m, 0.0)
        sc["unrealized_pnl"] = unrealized
        sc["equity"] = STARTING_CAPITAL + float(sc["total_pnl"]) + unrealized
        sc["return_pct"] = ((sc["equity"] / STARTING_CAPITAL) - 1.0) * 100.0
        sc["position_value"] = position_value_by_model.get(m, 0.0)
        sc["recommendation"] = recommendation_fn(m, pause is not None)
        scorecards.append(sc)
    return scorecards


def _sim_metrics_uncached(window_hours: int = 6):
    conn = get_db_conn()
    out = {
        "starting_capital": STARTING_CAPITAL,
        "live_cutoff_utc": None,
        "recompute_in_progress": False,
        "equity_series_20s": {},
        "equity_series_1m": {},
        "stack_series_20s": {},
        "drawdown_series_20s": {},
        "scorecards": [],
        "open_positions": [],
        "recent_trades": [],
        "calibration": [],
        "execution_quality": [],
        "in_sample": [],
        "out_of_sample": [],
    }
    with conn.cursor() as cur:
        cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_live_cutoff_utc' LIMIT 1")
        cutoff_row = cur.fetchone()
        if cutoff_row:
            sv = cutoff_row["state_value"]
            try:
                j = sv if isinstance(sv, dict) else json.loads(sv)
                out["live_cutoff_utc"] = j.get("cutoff_utc")
            except Exception:
                out["live_cutoff_utc"] = str(sv)

        cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_recompute_in_progress' LIMIT 1")
        prog_row = cur.fetchone()
        if prog_row:
            sv = prog_row["state_value"]
            try:
                j = sv if isinstance(sv, dict) else json.loads(sv)
                out["recompute_in_progress"] = bool(j.get("in_progress"))
            except Exception:
                out["recompute_in_progress"] = False

        cur.execute(
            """
            SELECT snapshot_time_utc, model_name, cash_dollars, position_value_dollars, equity_dollars, drawdown_dollars
            FROM sim_portfolio_20s
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s HOUR)
            ORDER BY snapshot_time_utc ASC
            """,
            (window_hours,),
        )
        for r in cur.fetchall():
            m = r["model_name"]
            ts = str(r["snapshot_time_utc"])
            out["equity_series_20s"].setdefault(m, []).append({"t": ts, "equity": float(r["equity_dollars"])})
            out["stack_series_20s"].setdefault(m, []).append(
                {"t": ts, "cash": float(r["cash_dollars"]), "position": float(r["position_value_dollars"])}
            )
            out["drawdown_series_20s"].setdefault(m, []).append({"t": ts, "drawdown": float(r["drawdown_dollars"])})

        cur.execute(
            """
            SELECT snapshot_minute_utc, model_name, cumulative_pnl_dollars, raw_json
            FROM sim_equity_1m
            WHERE snapshot_minute_utc >= (UTC_TIMESTAMP() - INTERVAL %s HOUR)
            ORDER BY snapshot_minute_utc ASC
            """,
            (window_hours,),
        )
        for r in cur.fetchall():
            m = r["model_name"]
            ts = str(r["snapshot_minute_utc"])
            eq = 100.0 + float(r["cumulative_pnl_dollars"] or 0.0)
            try:
                raw_blob = r["raw_json"]
                if isinstance(raw_blob, dict):
                    raw = raw_blob
                elif isinstance(raw_blob, str):
                    try:
                        raw = json.loads(raw_blob or "{}")
                    except Exception:
                        raw = ast.literal_eval(raw_blob) if raw_blob else {}
                else:
                    raw = {}
                if isinstance(raw, dict):
                    # Prefer explicit equity when present; otherwise reconstruct
                    # from cumulative + unrealized to avoid flat-line fallback.
                    if raw.get("equity_dollars") is not None:
                        eq = float(raw["equity_dollars"])
                    elif raw.get("unrealized_pnl_dollars") is not None:
                        eq = 100.0 + float(r["cumulative_pnl_dollars"] or 0.0) + float(raw["unrealized_pnl_dollars"])
            except Exception:
                pass
            out["equity_series_1m"].setdefault(m, []).append({"t": ts, "equity": eq})

        pause_states = get_all_model_pause_states(cur)

        cur.execute(
            """
            SELECT model_name, COUNT(*) closed_trades,
                   COALESCE(SUM(pnl_dollars),0) total_pnl,
                   COALESCE(AVG(pnl_dollars),0) avg_pnl,
                   COALESCE(SUM(pnl_dollars > 0),0) wins
            FROM sim_trades
            WHERE status='closed'
            GROUP BY model_name
            """
        )
        score_map = {}
        for r in cur.fetchall():
            closed = int(r["closed_trades"] or 0)
            wins = int(r["wins"] or 0)
            pause = pause_states.get(r["model_name"])
            score_map[r["model_name"]] = {
                "model_name": r["model_name"],
                "closed_trades": closed,
                "total_pnl": float(r["total_pnl"] or 0),
                "avg_trade_pnl": float(r["avg_pnl"] or 0),
                "win_rate": (wins / closed) if closed > 0 else None,
                "paused": pause is not None,
                "paused_reason": pause.get("paused_reason") if pause else None,
            }

        cur.execute("SELECT DISTINCT market_ticker FROM sim_positions")
        open_tickers = [r["market_ticker"] for r in cur.fetchall()]
        if open_tickers:
            placeholders = ",".join(["%s"] * len(open_tickers))
            cur.execute(
                f"""
                SELECT p.model_name, p.market_ticker, p.qty_contracts, p.entry_price_dollars, p.opened_at_utc,
                       fq.yes_bid_dollars, fq.yes_ask_dollars
                FROM sim_positions p
                LEFT JOIN (
                  SELECT f1.*
                  FROM forward_quotes f1
                  JOIN (
                    SELECT market_ticker, MAX(snapshot_time_utc) mx
                    FROM forward_quotes
                    WHERE market_ticker IN ({placeholders})
                    GROUP BY market_ticker
                  ) f2 ON f2.market_ticker=f1.market_ticker AND f2.mx=f1.snapshot_time_utc
                ) fq ON fq.market_ticker=p.market_ticker
                ORDER BY p.opened_at_utc DESC
                """,
                tuple(open_tickers),
            )
        else:
            cur.execute("SELECT NULL LIMIT 0")
        for r in cur.fetchall():
            entry = float(r["entry_price_dollars"])
            qty = int(r["qty_contracts"])
            mark = float(r["yes_bid_dollars"]) if r["yes_bid_dollars"] is not None else entry
            out["open_positions"].append(
                {
                    "model_name": r["model_name"],
                    "market_ticker": r["market_ticker"],
                    "qty_contracts": qty,
                    "entry_price": entry,
                    "mark_bid": mark,
                    "unrealized_pnl": (mark - entry) * qty,
                    "opened_at_utc": str(r["opened_at_utc"]),
                }
            )

        out["scorecards"] = build_scorecards(
            score_map,
            out["open_positions"],
            pause_states,
            lambda m, paused: get_model_recommendation_status(cur, m, paused),
        )

        cur.execute(
            """
            SELECT id, model_name, market_ticker, opened_at_utc, closed_at_utc, qty_contracts,
                   entry_price_dollars, exit_price_dollars, pnl_dollars, status, raw_json
            FROM sim_trades
            ORDER BY id DESC
            LIMIT 60
            """
        )
        trades = cur.fetchall()
        for r in trades:
            raw = r.get("raw_json") or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            exp_entry = None
            if raw.get("prob_yes") is not None and raw.get("edge") is not None:
                exp_entry = float(raw["prob_yes"]) - float(raw["edge"])
            realized_entry = float(r["entry_price_dollars"])
            slippage = None if exp_entry is None else (realized_entry - exp_entry)
            out["recent_trades"].append(
                {
                    "id": int(r["id"]),
                    "model_name": r["model_name"],
                    "market_ticker": r["market_ticker"],
                    "opened_at_utc": str(r["opened_at_utc"]),
                    "closed_at_utc": str(r["closed_at_utc"]) if r["closed_at_utc"] else None,
                    "qty_contracts": int(r["qty_contracts"]),
                    "entry_price": realized_entry,
                    "exit_price": float(r["exit_price_dollars"]) if r["exit_price_dollars"] is not None else None,
                    "pnl": float(r["pnl_dollars"]) if r["pnl_dollars"] is not None else None,
                    "status": r["status"],
                    "fill_mode": (raw.get("fill") or {}).get("mode"),
                    "expected_entry": exp_entry,
                    "slippage": slippage,
                }
            )

        cur.execute(
            """
            SELECT p.model_name, p.prob_yes, m1.market_ticker,
                   m1.mid_dollars AS mid_now, m2.mid_dollars AS mid_next
            FROM sim_model_predictions_1m p
            JOIN model_features_1m m1 ON m1.snapshot_minute_utc=p.snapshot_minute_utc AND m1.market_ticker=p.market_ticker
            JOIN model_features_1m m2 ON m2.market_ticker=m1.market_ticker AND m2.snapshot_minute_utc=(m1.snapshot_minute_utc + INTERVAL 1 MINUTE)
            WHERE p.snapshot_minute_utc >= (UTC_TIMESTAMP() - INTERVAL %s HOUR)
            ORDER BY p.snapshot_minute_utc DESC
            LIMIT 2000
            """,
            (window_hours,),
        )
        cal: Dict[str, Dict[str, Dict[str, float]]] = {}
        for r in cur.fetchall():
            model = r["model_name"]
            p = float(r["prob_yes"])
            y = 1 if float(r["mid_next"]) > float(r["mid_now"]) else 0
            b = _bucket_key(p)
            cal.setdefault(model, {}).setdefault(b, {"n": 0, "sum_p": 0.0, "sum_y": 0.0})
            cal[model][b]["n"] += 1
            cal[model][b]["sum_p"] += p
            cal[model][b]["sum_y"] += y
        for model, buckets in cal.items():
            for b, v in sorted(buckets.items()):
                if v["n"] <= 0:
                    continue
                out["calibration"].append(
                    {
                        "model_name": model,
                        "bucket": b,
                        "n": int(v["n"]),
                        "avg_pred": v["sum_p"] / v["n"],
                        "avg_realized": v["sum_y"] / v["n"],
                    }
                )

        exec_stats: Dict[str, Dict[str, float]] = {}
        for t in out["recent_trades"]:
            m = t["model_name"]
            exec_stats.setdefault(m, {"n": 0, "sum_slippage": 0.0, "sum_abs_slippage": 0.0})
            if t["slippage"] is not None:
                exec_stats[m]["n"] += 1
                exec_stats[m]["sum_slippage"] += float(t["slippage"])
                exec_stats[m]["sum_abs_slippage"] += abs(float(t["slippage"]))
        for m, v in exec_stats.items():
            n = int(v["n"])
            out["execution_quality"].append(
                {
                    "model_name": m,
                    "n": n,
                    "avg_slippage": (v["sum_slippage"] / n) if n > 0 else None,
                    "avg_abs_slippage": (v["sum_abs_slippage"] / n) if n > 0 else None,
                }
            )

        def _segment_stats(trade_where_sql: str, pred_where_sql: str, params: tuple):
            cur.execute(
                f"""
                SELECT model_name, COUNT(*) closed_trades,
                       COALESCE(SUM(pnl_dollars),0) total_pnl,
                       COALESCE(AVG(pnl_dollars),0) avg_pnl,
                       COALESCE(SUM(pnl_dollars > 0),0) wins
                FROM sim_trades
                WHERE status='closed' AND {trade_where_sql}
                GROUP BY model_name
                ORDER BY model_name
                """,
                params,
            )
            trade_rows = cur.fetchall()
            cur.execute(
                f"""
                SELECT model_name, COUNT(*) n_preds,
                       COALESCE(AVG(brier),0) avg_brier,
                       COALESCE(AVG(logloss),0) avg_logloss
                FROM sim_model_predictions_1m
                WHERE {pred_where_sql}
                GROUP BY model_name
                ORDER BY model_name
                """,
                params,
            )
            pred_map = {r["model_name"]: r for r in cur.fetchall()}
            out_rows = []
            for r in trade_rows:
                m = r["model_name"]
                closed = int(r["closed_trades"] or 0)
                wins = int(r["wins"] or 0)
                p = pred_map.get(m, {})
                out_rows.append(
                    {
                        "model_name": m,
                        "closed_trades": closed,
                        "total_pnl": float(r["total_pnl"] or 0.0),
                        "avg_pnl": float(r["avg_pnl"] or 0.0),
                        "win_rate": (wins / closed) if closed > 0 else None,
                        "n_preds": int(p.get("n_preds") or 0),
                        "avg_brier": float(p.get("avg_brier") or 0.0),
                        "avg_logloss": float(p.get("avg_logloss") or 0.0),
                    }
                )
            return out_rows

        cutoff = out.get("live_cutoff_utc")
        if cutoff:
            out["in_sample"] = _segment_stats("closed_at_utc < %s", "snapshot_minute_utc < %s", (cutoff,))
            out["out_of_sample"] = _segment_stats("closed_at_utc >= %s", "snapshot_minute_utc >= %s", (cutoff,))
        else:
            out["in_sample"] = _segment_stats("closed_at_utc IS NOT NULL", "1=1", tuple())
            out["out_of_sample"] = _segment_stats("1=0", "1=0", tuple())

    conn.close()
    return out


def live_settings_get(model_name: str):
    """Thin wrapper so the dashboard shares one source of truth for live
    settings with the engine that actually trades on them - see
    live_trading_engine.load_settings()."""
    conn = get_db_conn()
    with conn.cursor() as cur:
        out = live_load_settings(cur, model_name)
    conn.commit()
    conn.close()
    return out


def live_settings_update(model_name: str, patch: Dict):
    conn = get_db_conn()
    with conn.cursor() as cur:
        out = live_update_settings(cur, model_name, patch)
    conn.commit()
    conn.close()
    return out


def live_metrics(window_hours: int = 12):
    return _cached(("live_metrics", window_hours), _METRICS_CACHE_TTL_SECONDS, lambda: _live_metrics_uncached(window_hours))


def _live_metrics_uncached(window_hours: int = 12):
    conn = get_db_conn()
    out = {
        "settings": {},
        "models": {},
        "equity_series_20s": [],
        "stack_series_20s": [],
        "drawdown_series_20s": [],
        "open_positions": [],
        "recent_orders": [],
        "recent_trades": [],
        "risk_state": "GREEN",
        "cash_source": "unknown",
        "scorecard": {},
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_time_utc, cash_dollars, position_value_dollars, equity_dollars, drawdown_dollars, risk_state, raw_json
            FROM live_portfolio_20s
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s HOUR)
            ORDER BY snapshot_time_utc ASC
            """,
            (window_hours,),
        )
        latest_equity = None
        for r in cur.fetchall():
            ts = str(r["snapshot_time_utc"])
            out["equity_series_20s"].append({"t": ts, "equity": float(r["equity_dollars"])})
            out["stack_series_20s"].append({"t": ts, "cash": float(r["cash_dollars"]), "position": float(r["position_value_dollars"])})
            out["drawdown_series_20s"].append({"t": ts, "drawdown": float(r["drawdown_dollars"])})
            out["risk_state"] = r["risk_state"]
            latest_equity = float(r["equity_dollars"])
            try:
                raw = r["raw_json"] if isinstance(r["raw_json"], dict) else json.loads(r["raw_json"] or "{}")
                out["cash_source"] = raw.get("cash_source", out["cash_source"])
            except Exception:
                pass

        cur.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(pnl_dollars),0) p, COALESCE(AVG(pnl_dollars),0) a, COALESCE(SUM(pnl_dollars>0),0) w "
            "FROM live_trades WHERE status='closed'"
        )
        s = cur.fetchone()
        closed = int(s["c"] or 0)
        wins = int(s["w"] or 0)
        out["scorecard"] = {
            "closed_trades": closed,
            "total_pnl": float(s["p"] or 0),
            "avg_pnl": float(s["a"] or 0),
            "win_rate": (wins / closed) if closed > 0 else None,
            "equity": latest_equity,
        }

        cur.execute("SELECT model_name, qty_contracts, entry_price_dollars, opened_at_utc, market_ticker FROM live_positions ORDER BY opened_at_utc DESC")
        pos_rows = cur.fetchall()
        latest_bids: Dict[str, Optional[float]] = {}
        tickers = list({p["market_ticker"] for p in pos_rows})
        if tickers:
            placeholders = ",".join(["%s"] * len(tickers))
            cur.execute(
                f"""
                SELECT f1.market_ticker, f1.yes_bid_dollars
                FROM forward_quotes f1
                JOIN (
                  SELECT market_ticker, MAX(snapshot_time_utc) mx
                  FROM forward_quotes
                  WHERE market_ticker IN ({placeholders})
                  GROUP BY market_ticker
                ) f2 ON f2.market_ticker=f1.market_ticker AND f2.mx=f1.snapshot_time_utc
                """,
                tuple(tickers),
            )
            latest_bids = {
                r["market_ticker"]: float(r["yes_bid_dollars"]) if r["yes_bid_dollars"] is not None else None
                for r in cur.fetchall()
            }
        for p in pos_rows:
            bid = latest_bids.get(p["market_ticker"])
            if bid is None:
                bid = float(p["entry_price_dollars"])
            out["open_positions"].append(
                {
                    "model_name": p["model_name"],
                    "market_ticker": p["market_ticker"],
                    "qty_contracts": int(p["qty_contracts"]),
                    "entry_price": float(p["entry_price_dollars"]),
                    "mark_bid": bid,
                    "unrealized_pnl": (bid - float(p["entry_price_dollars"])) * int(p["qty_contracts"]),
                    "opened_at_utc": str(p["opened_at_utc"]),
                }
            )

        cur.execute(
            """
            SELECT created_at_utc, market_ticker, action, side, qty_contracts, limit_price_dollars, status, kalshi_order_id, client_order_id
            FROM live_orders
            ORDER BY id DESC
            LIMIT 40
            """
        )
        out["recent_orders"] = [
            {
                "created_at_utc": str(r["created_at_utc"]),
                "market_ticker": r["market_ticker"],
                "action": r["action"],
                "side": r["side"],
                "qty_contracts": int(r["qty_contracts"]),
                "limit_price_dollars": float(r["limit_price_dollars"]) if r["limit_price_dollars"] is not None else None,
                "status": r["status"],
                "kalshi_order_id": r["kalshi_order_id"],
                "client_order_id": r["client_order_id"],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT model_name, opened_at_utc, closed_at_utc, market_ticker, qty_contracts, entry_price_dollars, exit_price_dollars, pnl_dollars, status
            FROM live_trades
            ORDER BY id DESC
            LIMIT 40
            """
        )
        out["recent_trades"] = [
            {
                "model_name": r["model_name"],
                "opened_at_utc": str(r["opened_at_utc"]),
                "closed_at_utc": str(r["closed_at_utc"]) if r["closed_at_utc"] else None,
                "market_ticker": r["market_ticker"],
                "qty_contracts": int(r["qty_contracts"]),
                "entry_price": float(r["entry_price_dollars"]),
                "exit_price": float(r["exit_price_dollars"]) if r["exit_price_dollars"] is not None else None,
                "pnl": float(r["pnl_dollars"]) if r["pnl_dollars"] is not None else None,
                "status": r["status"],
            }
            for r in cur.fetchall()
        ]

        # Per-strategy settings, pause state, closed-trade record, and the
        # most recent tick's live signal (prob/edge/risk) from the engine's
        # own snapshot - this is what makes each strategy card independently
        # meaningful instead of one global block for everything.
        pause_states = get_all_live_pause_states(cur)
        cur.execute(
            "SELECT model_name, COUNT(*) closed_trades, COALESCE(SUM(pnl_dollars),0) total_pnl, COALESCE(SUM(pnl_dollars>0),0) wins "
            "FROM live_trades WHERE status='closed' GROUP BY model_name"
        )
        trade_stats = {r["model_name"]: r for r in cur.fetchall()}

        cur.execute("SELECT state_value FROM collector_state WHERE state_key='live_trading_last_snapshot' LIMIT 1")
        snap_row = cur.fetchone()
        snap = {}
        if snap_row:
            sv = snap_row.get("state_value")
            try:
                snap = sv if isinstance(sv, dict) else json.loads(sv or "{}")
            except Exception:
                snap = {}
        snap_models = snap.get("models", {}) if isinstance(snap, dict) else {}

        # The same strategy's paper-trading record, so a live card can be read
        # against the sim track record it was promoted on without switching
        # tabs. Same source and shape as the Portfolio Manager's total_pnl, so
        # the two panels always agree.
        placeholders = ",".join(["%s"] * len(LIVE_MODELS))
        cur.execute(
            f"""
            SELECT model_name, COUNT(*) closed_trades,
                   COALESCE(SUM(pnl_dollars),0) total_pnl,
                   COALESCE(SUM(pnl_dollars > 0),0) wins
            FROM sim_trades
            WHERE status='closed' AND model_name IN ({placeholders})
            GROUP BY model_name
            """,
            tuple(LIVE_MODELS),
        )
        sim_stats = {r["model_name"]: r for r in cur.fetchall()}

        for model_name in LIVE_MODELS:
            cfg = live_load_settings(cur, model_name)
            out["settings"][model_name] = cfg
            ts_stat = trade_stats.get(model_name)
            closed_m = int(ts_stat["closed_trades"]) if ts_stat else 0
            wins_m = int(ts_stat["wins"]) if ts_stat else 0
            pause = pause_states.get(model_name)
            live_snap = snap_models.get(model_name, {})
            out["models"][model_name] = {
                "live_enabled": bool(cfg.get("live_enabled")),
                "paused": pause is not None,
                "paused_reason": pause.get("paused_reason") if pause else None,
                "closed_trades": closed_m,
                "total_pnl": float(ts_stat["total_pnl"]) if ts_stat else 0.0,
                "win_rate": (wins_m / closed_m) if closed_m > 0 else None,
                "risk_state": live_snap.get("risk_state", "GREEN"),
                "prob": live_snap.get("prob"),
                "edge": live_snap.get("edge"),
                "signal": live_snap.get("signal"),
            }
            sim_stat = sim_stats.get(model_name)
            sim_closed = int(sim_stat["closed_trades"]) if sim_stat else 0
            sim_wins = int(sim_stat["wins"]) if sim_stat else 0
            out["models"][model_name].update(
                {
                    "sim_total_pnl": float(sim_stat["total_pnl"]) if sim_stat else 0.0,
                    "sim_closed_trades": sim_closed,
                    "sim_win_rate": (sim_wins / sim_closed) if sim_closed > 0 else None,
                }
            )
    conn.close()
    return out


def model_research_summary():
    conn = get_db_conn()
    out = {"best_models": [], "recent_runs": [], "last_run_state": None}
    with conn.cursor() as cur:
        cur.execute("SELECT state_value FROM collector_state WHERE state_key='model_research_last_run' LIMIT 1")
        state = cur.fetchone()
        if state:
            sv = state.get("state_value")
            if isinstance(sv, dict):
                out["last_run_state"] = sv
            else:
                try:
                    out["last_run_state"] = json.loads(sv)
                except Exception:
                    out["last_run_state"] = {"raw": str(sv)}

        cur.execute(
            """
            SELECT r.*
            FROM model_research_runs r
            JOIN (
              SELECT model_name, MAX(objective_pnl_dollars) best_pnl
              FROM model_research_runs
              WHERE stage='selected' AND status='success'
              GROUP BY model_name
            ) b ON b.model_name=r.model_name AND b.best_pnl=r.objective_pnl_dollars
            JOIN (
              SELECT model_name, objective_pnl_dollars, MAX(id) mx
              FROM model_research_runs
              WHERE stage='selected' AND status='success'
              GROUP BY model_name, objective_pnl_dollars
            ) x ON x.model_name=r.model_name AND x.objective_pnl_dollars=r.objective_pnl_dollars AND x.mx=r.id
            ORDER BY r.model_name
            """
        )
        best_runs = cur.fetchall()
        for b in best_runs:
            run_id = int(b["id"])
            cur.execute(
                """
                SELECT feature_name, importance_abs_mean, importance_signed_mean, rank_order, method
                FROM model_research_feature_importance
                WHERE run_id=%s
                ORDER BY rank_order ASC
                LIMIT 20
                """,
                (run_id,),
            )
            imp = [
                {
                    "feature_name": r["feature_name"],
                    "importance_abs_mean": float(r["importance_abs_mean"]),
                    "importance_signed_mean": float(r["importance_signed_mean"]),
                    "rank_order": int(r["rank_order"]),
                    "method": r["method"],
                }
                for r in cur.fetchall()
            ]
            params = b["params_json"] if isinstance(b["params_json"], dict) else json.loads(b["params_json"] or "{}")
            metrics = b["metrics_json"] if isinstance(b["metrics_json"], dict) else json.loads(b["metrics_json"] or "{}")
            feats = (
                b["selected_features_json"]
                if isinstance(b["selected_features_json"], list)
                else json.loads(b["selected_features_json"] or "[]")
            )
            out["best_models"].append(
                {
                    "run_id": run_id,
                    "model_name": b["model_name"],
                    "created_at_utc": str(b["created_at_utc"]),
                    "stage": b["stage"],
                    "objective_pnl_dollars": float(b["objective_pnl_dollars"]),
                    "n_train": int(b["n_train"]),
                    "n_eval": int(b["n_eval"]),
                    "params": params,
                    "metrics": metrics,
                    "selected_features": feats,
                    "feature_importance": imp,
                }
            )

        cur.execute(
            """
            SELECT id, created_at_utc, model_name, stage, objective_pnl_dollars, n_train, n_eval, status, notes
            FROM model_research_runs
            ORDER BY id DESC
            LIMIT 60
            """
        )
        out["recent_runs"] = [
            {
                "id": int(r["id"]),
                "created_at_utc": str(r["created_at_utc"]),
                "model_name": r["model_name"],
                "stage": r["stage"],
                "objective_pnl_dollars": float(r["objective_pnl_dollars"]),
                "n_train": int(r["n_train"]),
                "n_eval": int(r["n_eval"]),
                "status": r["status"],
                "notes": r["notes"],
            }
            for r in cur.fetchall()
        ]
    conn.close()
    return out


def render_page(title: str, body_html: str) -> str:
    css = """
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    :root{
      --bg:#071018;
      --bg-soft:#0d1722;
      --card:#0f1e2d;
      --text:#e5edf7;
      --muted:#95a7bd;
      --line:#1f3448;
      --brand:#22d3ee;
      --brand-soft:#0b3344;
    }
    *{box-sizing:border-box}
    body{margin:0;font-family:"Space Grotesk",ui-sans-serif,system-ui;background:
      radial-gradient(1200px 500px at 10% -10%, #12304a 0%, transparent 55%),
      radial-gradient(900px 500px at 100% -20%, #1d3655 0%, transparent 50%),
      linear-gradient(180deg,var(--bg) 0%,var(--bg-soft) 100%);color:var(--text)}
    .wrap{max-width:1200px;margin:0 auto;padding:28px 20px 40px}
    .top{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin-bottom:20px}
    .title{font-size:28px;font-weight:750;letter-spacing:-0.02em;margin:0}
    .sub{color:var(--muted);font-size:14px}
    .grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:16px 0 22px}
    .grid4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:12px 0 0}
    .row4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
    .row3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
    .card{background:linear-gradient(180deg,#112334 0%,#0e1b29 100%);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:0 14px 32px rgba(0,0,0,.25)}
    .k{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
    .v{font-size:26px;font-weight:700;margin-top:6px}
    .panel{background:linear-gradient(180deg,#101f2f 0%,#0d1b2a 100%);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:0 14px 32px rgba(0,0,0,.24)}
    .table-links{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
    .pill{display:inline-block;padding:8px 12px;border-radius:999px;text-decoration:none;font-size:13px;color:#c8f1ff;background:var(--brand-soft);border:1px solid #1c5b72}
    .pill:hover{filter:brightness(.98)}
    .pill.warn{color:#ffd9d9;background:#3a1414;border-color:#5a1f1f}
    .live-panel{border:2px solid #7a1f1f;background:linear-gradient(180deg,#2a1010 0%,#160a0a 100%);box-shadow:0 0 0 1px #5a1f1f,0 14px 32px rgba(122,31,31,.35)}
    .live-banner{color:#ffb4b4;font-weight:700;letter-spacing:.02em;margin-bottom:10px;display:flex;align-items:center;gap:8px}
    .status-badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:4px 10px;border-radius:999px}
    .status-badge.good{color:#eafff0;background:rgba(12,163,12,.22);border:1px solid #0ca30c}
    .status-badge.critical{color:#ffecec;background:rgba(208,59,59,.22);border:1px solid #d03b3b}
    .status-badge.muted{color:var(--muted);background:rgba(255,255,255,.04);border:1px solid var(--line)}
    .pm-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
    .pm-card{background:linear-gradient(180deg,#112334 0%,#0e1b29 100%);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
    .pm-card .pm-name{font-size:13px;font-weight:700;color:var(--text)}
    .pm-card .pm-equity{font-size:24px;font-weight:700;margin-top:6px}
    .pm-card .pm-pnl{font-size:13px;margin-top:2px}
    .pm-card .pm-reason{font-size:11px;color:var(--muted);margin-top:6px}
    .pm-card .pm-rec{font-size:12px;font-weight:600;margin-top:8px;padding:6px 8px;border-radius:8px}
    .pm-card .pm-pnl.sim-pos{color:#4ade80}
    .pm-card .pm-pnl.sim-neg{color:#f87171}
    .pm-card .pm-pnl.sim-flat{color:var(--muted)}
    .pm-card .pm-rec.promising{color:#eafff0;background:rgba(12,163,12,.16);border:1px solid #0ca30c}
    .pm-card .pm-rec.muted-neg{color:var(--muted);background:rgba(208,59,59,.08);border:1px solid #3a2020}
    .pm-card .pm-rec.muted-neutral{color:var(--muted);background:rgba(255,255,255,.03);border:1px solid var(--line)}
    .bar{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:12px}
    table{width:100%;border-collapse:separate;border-spacing:0;font-size:13px}
    th,td{padding:10px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
    th{position:sticky;top:0;background:#102338;font-weight:650}
    tr:nth-child(even) td{background:#0d1c2c}
    .muted{color:var(--muted)}
    .nav a{text-decoration:none;color:#69e0ff;font-weight:600}
    .badge{display:inline-block;background:#123149;color:#b6ecff;border:1px solid #1e5875;border-radius:999px;padding:3px 8px;font-size:12px}
    input,select,button{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace}
    input,select{background:#0b1723;border:1px solid #1f3448;border-radius:10px;color:#e5edf7;padding:8px 10px;min-width:88px}
    .toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    .metric-pos{color:#34d399}
    .metric-neg{color:#fb7185}
    @media (max-width: 1000px){.grid{grid-template-columns:repeat(2,minmax(0,1fr));}.grid4{grid-template-columns:repeat(2,minmax(0,1fr));}.row4{grid-template-columns:repeat(2,minmax(0,1fr));}.row3{grid-template-columns:repeat(1,minmax(0,1fr));}}
    """
    js = """
    function toUtcMs(v){
      if(v==null) return null;
      if(typeof v === 'number' && Number.isFinite(v)) return v;
      let s=String(v).trim();
      if(/^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$/.test(s)) s=s.replace(' ','T')+'Z';
      else if(/^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}$/.test(s)) s=s+'Z';
      const ms=Date.parse(s);
      return Number.isFinite(ms) ? ms : null;
    }
    function fmtNy(v){
      const ms = toUtcMs(v);
      if(ms==null) return String(v??'');
      const d = new Date(ms);
      const txt = new Intl.DateTimeFormat('en-US', {
        timeZone:'America/New_York',
        year:'numeric', month:'2-digit', day:'2-digit',
        hour:'2-digit', minute:'2-digit', second:'2-digit',
        hour12:false
      }).format(d).replace(',', '');
      return `${txt} ET`;
    }
    function drawLineChart(canvasId, seriesMap, key, colors, opts){
      const c = document.getElementById(canvasId);
      if(!c) return;
      const ctx = c.getContext('2d');
      const w = c.width, h = c.height;
      ctx.clearRect(0,0,w,h);
      opts = opts || {};
      const models = Object.keys(seriesMap||{});
      if(models.length===0) return;
      let all=[];
      for(const m of models){ for(const p of (seriesMap[m]||[])){ all.push(Number(p[key]||0)); } }
      if(all.length===0) return;
      let min=Math.min(...all), max=Math.max(...all);
      if(min===max){ min-=1; max+=1; }
      const pad=40;
      const toX=(i,n)=> pad + (i*(w-2*pad))/Math.max(1,n-1);
      const toY=(v)=> h-pad - ((v-min)*(h-2*pad))/Math.max(1e-9,(max-min));
      // Axes + y-grid/ticks
      ctx.strokeStyle='#263040'; ctx.lineWidth=1; ctx.beginPath(); ctx.moveTo(pad,pad); ctx.lineTo(pad,h-pad); ctx.lineTo(w-pad,h-pad); ctx.stroke();
      ctx.font='11px "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace';
      ctx.fillStyle='#9ca3af';
      for(let k=0;k<=4;k++){
        const v=min + (max-min)*(k/4);
        const y=toY(v);
        ctx.strokeStyle='rgba(148,163,184,0.18)';
        ctx.beginPath(); ctx.moveTo(pad,y); ctx.lineTo(w-pad,y); ctx.stroke();
        const label = opts.unit==='$' ? `$${v.toFixed(2)}` : v.toFixed(4);
        ctx.fillText(label, 6, y+3);
      }
      let idx=0;
      for(const m of models){
        const s=seriesMap[m]||[];
        if(s.length===0) continue;
        ctx.beginPath();
        for(let i=0;i<s.length;i++){
          const x=toX(i,s.length), y=toY(Number(s[i][key]||0));
          if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        }
        ctx.strokeStyle=(colors&&colors[m])||['#0f766e','#ea580c','#1d4ed8'][idx%3];
        ctx.lineWidth=2;
        ctx.stroke();
        idx++;
      }
      if(opts.cutoff && (seriesMap[models[0]]||[]).length>1){
        const base = seriesMap[models[0]];
        const cutoffIdx = base.findIndex(p => String(p.t) >= String(opts.cutoff));
        if(cutoffIdx >= 0){
          const x=toX(cutoffIdx, base.length);
          ctx.strokeStyle='rgba(245,158,11,0.95)';
          ctx.setLineDash([6,4]);
          ctx.beginPath(); ctx.moveTo(x,pad); ctx.lineTo(x,h-pad); ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle='rgba(245,158,11,0.95)';
          ctx.fillText('LIVE START', Math.min(w-96, x+4), pad+12);
        }
      }
    }
    function drawStackChart(canvasId, series, keyA, keyB, opts){
      const c = document.getElementById(canvasId);
      if(!c) return;
      const ctx = c.getContext('2d');
      const w=c.width,h=c.height,pad=40;
      ctx.clearRect(0,0,w,h);
      opts = opts || {};
      if(!series || series.length===0) return;
      const va=series.map(p=>Number(p[keyA]||0));
      const vb=series.map(p=>Number(p[keyB]||0));
      const all=[...va,...vb];
      let min=Math.min(...all,0), max=Math.max(...all,1);
      if(min===max){ min-=1; max+=1; }
      const toX=(i,n)=> pad + (i*(w-2*pad))/Math.max(1,n-1);
      const toY=(v)=> h-pad - ((v-min)*(h-2*pad))/Math.max(1e-9,(max-min));
      const fillLine=(vals,fillColor,lineColor)=>{
        ctx.beginPath();
        for(let i=0;i<vals.length;i++){
          const x=toX(i,vals.length), y=toY(vals[i]);
          if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        }
        ctx.lineTo(toX(vals.length-1,vals.length),toY(min));
        ctx.lineTo(toX(0,vals.length),toY(min));
        ctx.closePath();
        ctx.fillStyle=fillColor; ctx.fill();
        ctx.beginPath();
        for(let i=0;i<vals.length;i++){
          const x=toX(i,vals.length), y=toY(vals[i]);
          if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        }
        ctx.strokeStyle=lineColor; ctx.lineWidth=2; ctx.stroke();
      };
      ctx.strokeStyle='#263040'; ctx.beginPath(); ctx.moveTo(pad,pad); ctx.lineTo(pad,h-pad); ctx.lineTo(w-pad,h-pad); ctx.stroke();
      ctx.font='11px "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace';
      ctx.fillStyle='#9ca3af';
      for(let k=0;k<=4;k++){
        const v=min + (max-min)*(k/4);
        const y=toY(v);
        ctx.strokeStyle='rgba(148,163,184,0.14)';
        ctx.beginPath(); ctx.moveTo(pad,y); ctx.lineTo(w-pad,y); ctx.stroke();
        ctx.fillText(`$${v.toFixed(2)}`, 6, y+3);
      }
      fillLine(va,'rgba(34,211,238,0.12)','rgba(34,211,238,0.95)');
      fillLine(vb,'rgba(245,158,11,0.12)','rgba(245,158,11,0.95)');
      if(opts.cutoff && series.length>1){
        const cutoffIdx = series.findIndex(p => String(p.t) >= String(opts.cutoff));
        if(cutoffIdx >= 0){
          const x=toX(cutoffIdx, series.length);
          ctx.strokeStyle='rgba(245,158,11,0.95)';
          ctx.setLineDash([6,4]);
          ctx.beginPath(); ctx.moveTo(x,pad); ctx.lineTo(x,h-pad); ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle='rgba(245,158,11,0.95)';
          ctx.fillText('LIVE START', Math.min(w-96, x+4), pad+12);
        }
      }
    }
    function computeDrawdownSeriesFromEquity(series){
      if(!series || series.length===0) return [];
      let peak = Number(series[0].equity||0);
      const out=[];
      for(const p of series){
        const eq = Number(p.equity||0);
        if(eq > peak) peak = eq;
        out.push({t:p.t, drawdown:eq - peak});
      }
      return out;
    }
    function sliceAndRebaseSeries(byModelRaw, models, startTs, endTs){
      const startMs=toUtcMs(startTs);
      const endMs=toUtcMs(endTs);
      const out={};
      for(const m of models){
        const src=(byModelRaw[m]||[]);
        const seg=src.filter(p => {
          const pms=toUtcMs(p.t);
          if(pms==null) return false;
          if(startMs!=null && pms < startMs) return false;
          if(endMs!=null && pms >= endMs) return false;
          return true;
        });
        if(seg.length===0) continue;
        const baseEq=Number(seg[0].equity||0);
        out[m]=seg.map(p => ({t:p.t, equity: 100 + (Number(p.equity||0) - baseEq)}));
      }
      return out;
    }
    function rebaseWholeSeries(byModelRaw, models){
      const out={};
      for(const m of models){
        const src=(byModelRaw[m]||[]);
        if(src.length===0) continue;
        const baseEq=Number(src[0].equity||0);
        out[m]=src.map(p => ({t:p.t, equity: 100 + (Number(p.equity||0) - baseEq)}));
      }
      return out;
    }
    function isWalkForwardModel(m){
      return String(m||'').startsWith('walk_forward_');
    }
    function segmentRangeText(seriesMap){
      let minT=null, maxT=null;
      for(const k of Object.keys(seriesMap||{})){
        const arr=seriesMap[k]||[];
        if(arr.length===0) continue;
        const s=arr[0].t, e=arr[arr.length-1].t;
        const sms=toUtcMs(s), ems=toUtcMs(e);
        if(sms==null || ems==null) continue;
        if(minT===null || sms < minT) minT=sms;
        if(maxT===null || ems > maxT) maxT=ems;
      }
      if(minT===null || maxT===null) return '(no data)';
      return `(${fmtNy(minT)} → ${fmtNy(maxT)})`;
    }
    function segmentTotals(rows){
      const out={closed:0,pnl:0,wins:0,preds:0,brierSum:0,brierN:0,loglossSum:0,loglossN:0};
      for(const r of (rows||[])){
        const c=Number(r.closed_trades||0);
        const wr=(r.win_rate==null?null:Number(r.win_rate));
        out.closed += c;
        out.pnl += Number(r.total_pnl||0);
        out.wins += (wr==null?0:(wr*c));
        out.preds += Number(r.n_preds||0);
        if(r.avg_brier!=null){ out.brierSum += Number(r.avg_brier)*Math.max(1,Number(r.n_preds||0)); out.brierN += Math.max(1,Number(r.n_preds||0)); }
        if(r.avg_logloss!=null){ out.loglossSum += Number(r.avg_logloss)*Math.max(1,Number(r.n_preds||0)); out.loglossN += Math.max(1,Number(r.n_preds||0)); }
      }
      out.win_rate = out.closed>0 ? (out.wins/out.closed) : null;
      out.avg_brier = out.brierN>0 ? (out.brierSum/out.brierN) : null;
      out.avg_logloss = out.loglossN>0 ? (out.loglossSum/out.loglossN) : null;
      return out;
    }
    // PnL here comes from the closed-trade aggregates in d.in_sample /
    // d.out_of_sample, never from the equity series feeding the charts: those
    // series only cover the last window_hours and are rebased so their first
    // point is $100, so reading their endpoint reported the change over the
    // visible window (often $0.00) as if it were the segment's total PnL.
    function renderSegmentSummary(d, models, currentBasisLabel){
      const pick = (arr)=> (arr||[]).filter(r=>models.includes(r.model_name));
      const inRows=pick(d.in_sample);
      const oosRows=pick(d.out_of_sample);
      const el=document.getElementById('sim_model_rows');
      if(!el) return;
      const blocks=[];
      for(const m of models){
        const cards=[]; 
        const oosRow=(oosRows||[]).find(x=>x.model_name===m);
        const inRow=(inRows||[]).find(x=>x.model_name===m);
        const hasCutoff=!!d.live_cutoff_utc;
        const isWF=isWalkForwardModel(m);
        const curSeg = isWF
          ? segmentTotals([...(inRow?[inRow]:[]), ...(oosRow?[oosRow]:[])])
          : (hasCutoff ? segmentTotals(oosRow ? [oosRow] : []) : segmentTotals(inRow ? [inRow] : []));
        const curPnl=Number(curSeg.pnl||0);
        const curEq=100+curPnl;
        const curRet=((curEq/100)-1)*100;
        const curWr=(curSeg.win_rate==null?'N/A':`${(100*Number(curSeg.win_rate)).toFixed(1)}%`);
        const curBasis = isWF
          ? 'full walk-forward history'
          : (currentBasisLabel || (hasCutoff ? 'since out-of-sample start' : 'since in-sample start'));
        cards.push(`<div class='card'><div class='k'>${m} | Current (${curBasis})</div><div class='v' style='font-size:20px'>PnL $${curPnl.toFixed(2)}</div><div class='muted'>equity $${curEq.toFixed(2)} | ret ${curRet.toFixed(2)}% | closed ${curSeg.closed} | win ${curWr}</div></div>`);
        const segs = isWF
          ? [
              ['Warmup', 'pre-walk-forward warmup', []],
              ['Walk-Forward OOS', 'all walk-forward predictions/trades', [...(inRow?[inRow]:[]), ...(oosRow?[oosRow]:[])]],
            ]
          : [
              ['In-Sample', 'before live cutoff', inRow ? [inRow] : []],
              ['Out-of-Sample', 'from live cutoff onward', oosRow ? [oosRow] : []],
            ];
        for(const [label,scope,rows] of segs){
          const one=rows||[];
          const s=segmentTotals(one);
          const segPnl = Number(s.pnl||0);
          const wr=(s.win_rate==null?'N/A':`${(100*s.win_rate).toFixed(1)}%`);
          const b=(s.avg_brier==null?'N/A':s.avg_brier.toFixed(4));
          const ll=(s.avg_logloss==null?'N/A':s.avg_logloss.toFixed(4));
          cards.push(`<div class='card'><div class='k'>${m} | ${label}</div><div class='v' style='font-size:20px'>$${segPnl.toFixed(2)}</div><div class='muted'>${scope}</div><div class='muted'>closed ${s.closed} | win ${wr} | preds ${s.preds} | brier ${b} | logloss ${ll}</div></div>`);
        }
        blocks.push(`<div style="margin-top:12px"><div class="bar" style="margin-bottom:8px"><div class="nav">${m}</div></div><div class="row4">${cards.join('')}</div></div>`);
      }
      el.innerHTML=blocks.join('');
    }
    function renderRows(tbodyId, rows, cols){
      const el=document.getElementById(tbodyId); if(!el) return;
      el.innerHTML = rows.map(r => '<tr>' + cols.map(c => `<td>${(r[c]??'')}</td>`).join('') + '</tr>').join('');
    }
    function livePass(){
      const sp = new URLSearchParams(window.location.search || '');
      const q = sp.get('live_password') || '';
      if(q){ try{ localStorage.setItem('live_password', q); }catch(e){} return q; }
      try{ return localStorage.getItem('live_password') || ''; }catch(e){ return ''; }
    }
    const SIM_PALETTE=['#22d3ee','#fb7185','#a3e635','#f59e0b','#c084fc','#60a5fa','#34d399','#f472b6','#f43f5e','#2dd4bf'];
    function simColor(id, idx){
      let h=0; for(let i=0;i<String(id).length;i++){ h=(h*31 + String(id).charCodeAt(i))>>>0; }
      return SIM_PALETTE[(h + idx) % SIM_PALETTE.length];
    }
    const SIM_MODELS=['naive_logistic_baseline','logistic','random_forest','random_forest_high_conviction','binary_theory_edge'];
    const LIVE_MODELS=['random_forest','random_forest_high_conviction','binary_theory_edge'];
    async function resumeModel(modelName){
      if(!confirm(`Resume ${modelName}? It will be allowed to open new positions again.`)) return;
      const r=await fetch('/sim_risk/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:modelName})});
      let j={};
      try{ j=await r.json(); }catch(e){}
      if(!r.ok || !j.ok){ alert(`Resume failed: ${(j&&j.error)||r.status}`); }
      await refreshSimMetrics();
    }
    function renderPortfolioManager(scorecards){
      const grid=document.getElementById('pm_grid');
      const stat=document.getElementById('pm_status');
      if(!grid) return;
      const cards=(scorecards||[]).filter(c=>SIM_MODELS.includes(c.model_name)).sort((a,b)=>a.model_name.localeCompare(b.model_name));
      const pausedCount=cards.filter(c=>c.paused).length;
      if(stat) stat.textContent = pausedCount>0 ? `${pausedCount} of ${cards.length} paused` : `${cards.length} active`;
      grid.innerHTML=cards.map(c=>{
        const pnl=Number(c.total_pnl||0);
        const pnlSign=pnl>0?'+':'';
        const badge=c.paused
          ? `<span class="status-badge critical">&#9679; PAUSED</span>`
          : `<span class="status-badge good">&#9679; ACTIVE</span>`;
        const resumeBtn=c.paused
          ? `<div style="margin-top:8px"><a class="pill warn" href="javascript:void(0)" onclick="resumeModel('${c.model_name}')">Resume trading</a></div>`
          : '';
        const reason=c.paused && c.paused_reason ? `<div class="pm-reason">${c.paused_reason}</div>` : '';
        const equity=(c.equity!==undefined && c.equity!==null) ? `$${Number(c.equity).toFixed(2)}` : 'n/a';
        const unreal=Number(c.unrealized_pnl||0);
        // equity = $100 + realized + unrealized; show the open leg when there
        // is one so the two numbers on the card visibly add up.
        const unrealLine = Math.abs(unreal) >= 0.005
          ? `<div class="pm-pnl">Open position: ${unreal>0?'+':''}$${unreal.toFixed(2)} unrealized</div>`
          : '';
        const rec=c.recommendation||{};
        const recClass = rec.status==='promising' ? 'promising' : (rec.status==='negative' || rec.status==='thin_edge' ? 'muted-neg' : 'muted-neutral');
        const recLine = (!c.paused && rec.label) ? `<div class="pm-rec ${recClass}">${rec.label}</div>` : '';
        const deployBtn = (!c.paused && rec.status==='promising')
          ? `<div style="margin-top:8px"><a class="pill" href="/?tab=live-trading">Review for live deployment &rarr;</a></div>`
          : '';
        return `<div class="pm-card">
          <div style="display:flex;justify-content:space-between;align-items:center"><div class="pm-name">${c.model_name}</div>${badge}</div>
          <div class="pm-equity">${equity}</div>
          <div class="pm-pnl">Total PnL: ${pnlSign}$${pnl.toFixed(2)} &middot; ${c.closed_trades||0} trades${c.win_rate!=null ? ' &middot; '+(c.win_rate*100).toFixed(0)+'% win' : ''}</div>
          ${unrealLine}
          ${recLine}
          ${reason}
          ${resumeBtn}
          ${deployBtn}
        </div>`;
      }).join('');
    }
    // A failed metrics fetch used to `return` silently, leaving a tab that
    // looked identical to "no data yet" - a 500 from /live_metrics went
    // unnoticed that way. Surface it at the top of the tab instead.
    function setFetchError(rootId, msg){
      const root=document.getElementById(rootId);
      if(!root) return;
      const id=rootId+'_fetch_error';
      let el=document.getElementById(id);
      if(!msg){ if(el) el.remove(); return; }
      if(!el){
        el=document.createElement('div');
        el.id=id;
        el.style.cssText='border:1px solid #7f1d1d;background:#2a1215;color:#fca5a5;border-radius:10px;padding:10px 12px;margin-bottom:12px;font-size:13px;line-height:1.5';
        root.insertBefore(el, root.firstChild);
      }
      el.textContent=msg;
    }
    async function refreshSimMetrics(){
      const simRoot=document.getElementById('sim-root');
      if(!simRoot) return;
      try{
        const selectedModels=SIM_MODELS;
        const r=await fetch('/sim_metrics',{cache:'no-store'});
        if(!r.ok){
          setFetchError('sim-root', `Simulated-trading data unavailable: /sim_metrics returned HTTP ${r.status}. The panels below are stale or empty until this is fixed - check the dashboard log on the server.`);
          return;
        }
        setFetchError('sim-root', null);
        const d=await r.json();
        renderPortfolioManager(d.scorecards);
        const byModelRaw=(d.equity_series_1m && Object.keys(d.equity_series_1m).length>0) ? d.equity_series_1m : (d.equity_series_20s||{});
        const colors={};
        let idx=0;
        for(const m of selectedModels){
          if(byModelRaw[m]){ colors[m]=simColor(`sim:${m}`, idx++); }
        }
        const frozenModels=selectedModels.filter(m => !isWalkForwardModel(m));
        const wfModels=selectedModels.filter(m => isWalkForwardModel(m));
        const inSampleSeries = {
          ...sliceAndRebaseSeries(byModelRaw, frozenModels, null, d.live_cutoff_utc || null),
        };
        const outSampleSeries = {
          ...sliceAndRebaseSeries(byModelRaw, frozenModels, d.live_cutoff_utc || null, null),
          ...rebaseWholeSeries(byModelRaw, wfModels),
        };
        const hasCutoff = !!d.live_cutoff_utc;
        const currentBasisLabel = hasCutoff ? 'since out-of-sample start' : 'since in-sample start';
        if(Object.keys(inSampleSeries).length===0 && !d.live_cutoff_utc){
          // Fallback for environments with no cutoff configured yet.
          for(const m of selectedModels){
            if(byModelRaw[m] && byModelRaw[m].length>0){
              const baseEq = Number(byModelRaw[m][0].equity||0);
              inSampleSeries[m]=byModelRaw[m].map(p => ({t:p.t, equity:100 + (Number(p.equity||0)-baseEq)}));
            }
          }
        }
        drawLineChart('equity_chart_in_sample', inSampleSeries, 'equity', colors, {unit:'$'});
        drawLineChart('equity_chart_out_sample', outSampleSeries, 'equity', colors, {unit:'$'});
        const rin=document.getElementById('range_in_sample'); if(rin) rin.textContent=segmentRangeText(inSampleSeries);
        const roo=document.getElementById('range_out_sample'); if(roo) roo.textContent=segmentRangeText(outSampleSeries);
        const basePicked=selectedModels;
        let focusModel=null;
        const opens=(d.open_positions||[]);
        for(const m of selectedModels){
          if(opens.some(r => r.model_name===m)){ focusModel=m; break; }
        }
        if(!focusModel){
          for(const m of selectedModels){
            if((d.stack_series_20s||{})[m] && (d.stack_series_20s[m]||[]).length>0){ focusModel=m; break; }
          }
        }
        if(!focusModel){
          const ks=Object.keys(d.stack_series_20s||{});
          focusModel=ks.length?ks[0]:null;
        }
        if(focusModel && d.stack_series_20s && d.stack_series_20s[focusModel]){
          drawStackChart('stack_chart', d.stack_series_20s[focusModel], 'cash', 'position', {cutoff:d.live_cutoff_utc});
        }else{
          drawStackChart('stack_chart', [], 'cash', 'position', {cutoff:d.live_cutoff_utc});
        }
        const ddSel={};
        if(focusModel && d.equity_series_20s && d.equity_series_20s[focusModel]){
          const dd = computeDrawdownSeriesFromEquity(d.equity_series_20s[focusModel]);
          if(dd.length>0) ddSel[focusModel]=dd;
        }
        if(Object.keys(ddSel).length===0 && focusModel && d.drawdown_series_20s && d.drawdown_series_20s[focusModel]){
          ddSel[focusModel]=d.drawdown_series_20s[focusModel];
        }
        const ddColors = focusModel ? {[focusModel]: (colors[focusModel] || '#22d3ee')} : {};
        drawLineChart('drawdown_chart', ddSel, 'drawdown', ddColors, {cutoff:d.live_cutoff_utc});
        const stNote=document.getElementById('sim_stack_model');
        if(stNote) stNote.textContent = focusModel ? `model: ${focusModel}` : 'model: N/A';
        const ddNote=document.getElementById('sim_drawdown_model');
        if(ddNote) ddNote.textContent = focusModel ? `model: ${focusModel}` : 'model: N/A';
        renderSegmentSummary(d, basePicked, currentBasisLabel);

        renderRows('open_positions_body', (d.open_positions||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','market_ticker','qty_contracts','entry_price','mark_bid','unrealized_pnl','opened_at_utc']);
        renderRows('trades_body', (d.recent_trades||[]).filter(r => basePicked.includes(r.model_name)).slice(0,30), ['id','model_name','market_ticker','opened_at_utc','closed_at_utc','qty_contracts','entry_price','exit_price','pnl','status','expected_entry','slippage','fill_mode']);
        renderRows('calib_body', (d.calibration||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','bucket','n','avg_pred','avg_realized']);
        renderRows('exec_body', (d.execution_quality||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','n','avg_slippage','avg_abs_slippage']);
        renderRows('insample_body', (d.in_sample||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','closed_trades','total_pnl','avg_pnl','win_rate','n_preds','avg_brier','avg_logloss']);
        renderRows('oos_body', (d.out_of_sample||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','closed_trades','total_pnl','avg_pnl','win_rate','n_preds','avg_brier','avg_logloss']);
        const cut=document.getElementById('sim_cutoff');
        if(cut){
          const runNote = d.recompute_in_progress ? ' | recompute in progress (charts temporarily partial)' : '';
          if(d.live_cutoff_utc){
            cut.textContent = `train/live cutoff: ${fmtNy(d.live_cutoff_utc)}${runNote}`;
          }else{
            cut.textContent = `cutoff not set${runNote}`;
          }
        }
        const lg=document.getElementById('sim_legend');
        if(lg){
          const known=selectedModels.filter(m => byModelRaw[m] && byModelRaw[m].length>0);
          lg.innerHTML = known.map((k,i)=>`<span class='pill' style='border-color:${colors[k]};color:${colors[k]}'>${k}</span>`).join(' ');
        }
        try{
          const rr = await fetch('/model_research',{cache:'no-store'});
          if(rr.ok){
            const mr = await rr.json();
            const hdr=document.getElementById('mr_last_run');
            if(hdr){
              const s=mr.last_run_state||{};
              hdr.textContent = s.ran_at_utc ? `last run: ${fmtNy(s.ran_at_utc)} | cutoff: ${fmtNy(s.cutoff_utc)} | train ${s.train_rows||0} | eval ${s.eval_rows||0}` : 'no research run yet';
            }
            const bestBody=document.getElementById('mr_best_models_body');
            if(bestBody){
              bestBody.innerHTML = (mr.best_models||[]).map(x=>{
                const m=x.metrics||{};
                const p=JSON.stringify(x.params||{});
                const feats=(x.selected_features||[]).join(', ');
                return `<tr><td>${x.model_name}</td><td>${x.run_id}</td><td>${fmtNy(x.created_at_utc)}</td><td>${Number(x.objective_pnl_dollars||0).toFixed(2)}</td><td>${m.brier==null?'':Number(m.brier).toFixed(4)}</td><td>${m.logloss==null?'':Number(m.logloss).toFixed(4)}</td><td>${x.n_train}</td><td>${x.n_eval}</td><td style='max-width:320px;white-space:normal;word-break:break-word'>${p}</td><td style='max-width:380px;white-space:normal;word-break:break-word'>${feats}</td></tr>`;
              }).join('');
            }
            const fiBody=document.getElementById('mr_feature_importance_body');
            if(fiBody){
              const rows=[];
              for(const bm of (mr.best_models||[])){
                for(const f of (bm.feature_importance||[]).slice(0,10)){
                  rows.push(`<tr><td>${bm.model_name}</td><td>${bm.run_id}</td><td>${f.rank_order}</td><td>${f.feature_name}</td><td>${Number(f.importance_abs_mean||0).toFixed(6)}</td><td>${Number(f.importance_signed_mean||0).toFixed(6)}</td><td>${f.method||''}</td></tr>`);
                }
              }
              fiBody.innerHTML = rows.join('');
            }
            const recentBody=document.getElementById('mr_recent_runs_body');
            if(recentBody){
              recentBody.innerHTML = (mr.recent_runs||[]).map(r=>`<tr><td>${r.id}</td><td>${fmtNy(r.created_at_utc)}</td><td>${r.model_name}</td><td>${r.stage}</td><td>${Number(r.objective_pnl_dollars||0).toFixed(2)}</td><td>${r.n_train}</td><td>${r.n_eval}</td><td>${r.status}</td><td>${r.notes||''}</td></tr>`).join('');
            }
          }
        }catch(e){}
      }catch(e){
        setFetchError('sim-root', `Simulated-trading data unavailable: /sim_metrics request failed (${e}).`);
      }
    }
    const LIVE_SETTINGS_FIELDS = ['signal_threshold','edge_threshold','max_trade_cost','max_open_notional','max_concurrent_positions','max_daily_loss','max_total_drawdown'];
    const LIVE_FIELD_STEP = {signal_threshold:'0.01', edge_threshold:'0.001', max_trade_cost:'0.1', max_open_notional:'0.1', max_concurrent_positions:'1', max_daily_loss:'0.1', max_total_drawdown:'0.1'};
    async function refreshLiveMetrics(){
      const root=document.getElementById('live-root');
      if(!root) return;
      try{
        const lp = livePass();
        const r=await fetch('/live_metrics' + (lp?('?live_password='+encodeURIComponent(lp)):'') ,{cache:'no-store'});
        if(!r.ok){
          setFetchError('live-root', r.status===403
            ? 'Live panel locked. Append &live_password=... to the URL (or use the unlock link) to view live execution controls.'
            : `Live-trading data unavailable: /live_metrics returned HTTP ${r.status}. Strategy toggles, account status and charts stay empty until this is fixed - check the dashboard log on the server.`);
          return;
        }
        setFetchError('live-root', null);
        const d=await r.json();
        drawLineChart('live_equity_chart', {'live': d.equity_series_20s||[]}, 'equity', {'live':'#22d3ee'}, {unit:'$'});
        drawLineChart('live_drawdown_chart', {'live': d.drawdown_series_20s||[]}, 'drawdown', {'live':'#f97316'});
        drawStackChart('live_stack_chart', d.stack_series_20s||[], 'cash', 'position');
        renderLiveOpenPositions(d.open_positions||[]);
        renderRows('live_orders_body', d.recent_orders||[], ['created_at_utc','market_ticker','action','side','qty_contracts','limit_price_dollars','status','kalshi_order_id','client_order_id']);
        renderRows('live_trades_body', d.recent_trades||[], ['model_name','opened_at_utc','closed_at_utc','market_ticker','qty_contracts','entry_price','exit_price','pnl','status']);
        const sc=document.getElementById('live_score');
        if(sc){
          const s=d.scorecard||{};
          const wr=(s.win_rate==null?'N/A':`${(s.win_rate*100).toFixed(1)}%`);
          const cashNote = d.cash_source==='kalshi_api' ? '' : ` <span class="muted-neg" style="font-size:12px">(estimated - real balance unavailable, see note below)</span>`;
          sc.innerHTML=`<div class='card'><div class='k'>account risk</div><div class='v' style='font-size:18px'>${d.risk_state||'N/A'}</div></div>` +
                       `<div class='card'><div class='k'>cash source</div><div class='v' style='font-size:16px'>${d.cash_source||'unknown'}</div></div>` +
                       `<div class='card'><div class='k'>equity</div><div class='v' style='font-size:18px'>${s.equity==null?'N/A':'$'+Number(s.equity).toFixed(2)}${cashNote}</div></div>` +
                       `<div class='card'><div class='k'>total pnl (all strategies)</div><div class='v' style='font-size:18px'>$${Number(s.total_pnl||0).toFixed(2)}</div></div>` +
                       `<div class='card'><div class='k'>closed/win</div><div class='v' style='font-size:16px'>${Number(s.closed_trades||0)} / ${wr}</div></div>`;
        }
        const balanceNote = document.getElementById('live_balance_note');
        if(balanceNote){
          balanceNote.style.display = (d.cash_source==='kalshi_api') ? 'none' : 'block';
        }
        renderLiveStrategyCards(d.models||{}, d.settings||{});
      }catch(e){
        setFetchError('live-root', `Live-trading data unavailable: /live_metrics request failed (${e}).`);
      }
    }
    function renderLiveOpenPositions(rows){
      const el=document.getElementById('live_open_positions_body'); if(!el) return;
      const cols=['model_name','market_ticker','qty_contracts','entry_price','mark_bid','unrealized_pnl','opened_at_utc'];
      el.innerHTML = (rows||[]).map(r => {
        const t = r.market_ticker, m = r.model_name;
        const cells = cols.map(c => `<td>${(r[c]??'')}</td>`).join('');
        const btn = `<td><a class="pill warn" href="javascript:void(0)" onclick="closeLivePosition('${String(m).replace(/'/g,"\\'")}','${String(t).replace(/'/g,"\\'")}')">Close</a></td>`;
        return '<tr>' + cells + btn + '</tr>';
      }).join('');
    }
    async function closeLivePosition(modelName, ticker){
      if(!confirm(`Close LIVE position (${modelName}) on ${ticker} now at the current market bid? This places a real order.`)) return;
      try{
        const r=await fetch('/live_position/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:modelName, market_ticker:ticker})});
        let j={};
        try{ j=await r.json(); }catch(e){}
        if(!r.ok || !j.ok){ alert(`Close failed: ${(j&&j.error)||r.status}`); }
        else{ alert(`Close order submitted for ${ticker} at bid $${Number(j.close_bid||0).toFixed(2)}.`); }
      }catch(e){ alert(`Close failed: ${e}`); }
      await refreshLiveMetrics();
    }
    function renderLiveStrategyCards(models, settings){
      const el = document.getElementById('live_strategy_cards');
      if(!el) return;
      el.innerHTML = LIVE_MODELS.map(m => {
        const st = models[m] || {};
        const cfg = settings[m] || {};
        const enabled = !!st.live_enabled;
        const paused = !!st.paused;
        const badge = paused
          ? `<span class="status-badge critical">&#9679; AUTO-PAUSED</span>`
          : (enabled ? `<span class="status-badge good">&#9679; LIVE - ON</span>` : `<span class="status-badge muted">&#9679; OFF</span>`);
        const toggleLabel = enabled ? 'Turn OFF' : 'Turn ON';
        const toggleClass = enabled ? 'pill warn' : 'pill';
        const toggleBtn = `<a class="${toggleClass}" href="javascript:void(0)" onclick="toggleLiveModel('${m}', ${!enabled})">${toggleLabel}</a>`;
        const resumeBtn = paused ? `<a class="pill warn" href="javascript:void(0)" onclick="resumeLiveModel('${m}')">Clear auto-pause</a>` : '';
        const reason = paused && st.paused_reason ? `<div class="pm-reason">${st.paused_reason}</div>` : '';
        const wr = st.win_rate==null ? 'N/A' : `${(st.win_rate*100).toFixed(0)}%`;
        const simPnl = Number(st.sim_total_pnl||0);
        const simWr = st.sim_win_rate==null ? 'N/A' : `${(st.sim_win_rate*100).toFixed(0)}%`;
        const simClass = simPnl > 0 ? 'sim-pos' : (simPnl < 0 ? 'sim-neg' : 'sim-flat');
        const prob = st.prob==null ? 'N/A' : Number(st.prob).toFixed(3);
        const edge = st.edge==null ? 'N/A' : Number(st.edge).toFixed(3);
        const signalTxt = st.signal==null ? 'N/A' : (st.signal ? 'YES' : 'no');
        const settingsInputs = LIVE_SETTINGS_FIELDS.map(f =>
          `<div style="display:flex;flex-direction:column;gap:2px;min-width:110px">
             <label style="font-size:11px;color:var(--muted,#8aa)">${f.replace(/_/g,' ')}</label>
             <input id="ls_${m}_${f}" type="number" step="${LIVE_FIELD_STEP[f]}" min="0" value="${cfg[f]??''}" style="background:#0b1723;border:1px solid #1f3448;border-radius:6px;color:#e5edf7;padding:4px 6px;font-size:12px">
           </div>`
        ).join('');
        return `<div class="pm-card">
          <div style="display:flex;justify-content:space-between;align-items:center"><div class="pm-name">${m}</div>${badge}</div>
          <div class="pm-pnl">Live PnL: $${Number(st.total_pnl||0).toFixed(2)} &middot; ${st.closed_trades||0} trades &middot; ${wr} win</div>
          <div class="pm-pnl ${simClass}">Sim PnL: ${simPnl>0?'+':''}$${simPnl.toFixed(2)} &middot; ${st.sim_closed_trades||0} trades &middot; ${simWr} win</div>
          <div class="muted" style="font-size:12px;margin-top:4px">prob ${prob} &middot; edge ${edge} &middot; signal ${signalTxt}</div>
          ${reason}
          <div style="display:flex;gap:8px;margin-top:8px">${toggleBtn}${resumeBtn}</div>
          <details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;color:var(--muted,#8aa)">Strategy settings</summary>
            <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:6px">${settingsInputs}</div>
            <a class="pill" href="javascript:void(0)" onclick="saveLiveModelSettings('${m}')" style="margin-top:8px;display:inline-block">Save settings</a>
          </details>
        </div>`;
      }).join('');
    }
    async function toggleLiveModel(modelName, turnOn){
      const verb = turnOn ? 'Turn ON' : 'Turn OFF';
      const warn = turnOn ? ' This lets it place REAL orders with REAL money on its next tick.' : '';
      if(!confirm(`${verb} live trading for ${modelName}?${warn}`)) return;
      try{
        const lp = livePass();
        const r = await fetch('/live_model/toggle' + (lp?('?live_password='+encodeURIComponent(lp)):''), {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({model_name: modelName, live_enabled: turnOn})
        });
        let j={}; try{ j=await r.json(); }catch(e){}
        if(!r.ok || !j.ok){ alert(`Failed: ${(j&&j.error)||r.status}`); }
      }catch(e){ alert(`Failed: ${e}`); }
      await refreshLiveMetrics();
    }
    async function resumeLiveModel(modelName){
      if(!confirm(`Clear the auto-pause on ${modelName}? It will be allowed to open new positions again.`)) return;
      try{
        const lp = livePass();
        const r = await fetch('/live_model/resume' + (lp?('?live_password='+encodeURIComponent(lp)):''), {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({model_name: modelName})
        });
        let j={}; try{ j=await r.json(); }catch(e){}
        if(!r.ok || !j.ok){ alert(`Failed: ${(j&&j.error)||r.status}`); }
      }catch(e){ alert(`Failed: ${e}`); }
      await refreshLiveMetrics();
    }
    async function saveLiveModelSettings(modelName){
      const patch = {};
      for(const f of LIVE_SETTINGS_FIELDS){
        const el = document.getElementById(`ls_${modelName}_${f}`);
        if(el && el.value !== '') patch[f] = Number(el.value);
      }
      try{
        const lp = livePass();
        const r = await fetch('/live_settings' + (lp?('?live_password='+encodeURIComponent(lp)):''), {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({model_name: modelName, ...patch})
        });
        let j={}; try{ j=await r.json(); }catch(e){}
        if(!r.ok || !j.ok){ alert(`Save failed: ${(j&&j.error)||r.status}`); }
      }catch(e){ alert(`Save failed: ${e}`); }
      await refreshLiveMetrics();
    }
    async function refreshHealth(){
      try{
        const r = await fetch('/health', {cache:'no-store'});
        if(!r.ok) return;
        const d = await r.json();
        if(d.counts){
          for(const [k,v] of Object.entries(d.counts)){
            const el = document.querySelector(`[data-count-key="${k}"]`);
            if(el) el.textContent = Number(v).toLocaleString();
          }
        }
        const latest = document.getElementById('latest-forward');
        if(latest && d.latest_forward){
          latest.textContent = `last forward: ${fmtNy(d.latest_forward.snapshot_time_utc)} | ${d.latest_forward.market_ticker} | ${d.latest_forward.status}`;
        }
        if(d.forward_health){
          const fh = d.forward_health;
          const bind = (id,val) => { const el=document.getElementById(id); if(el) el.textContent=val; };
          bind('fh_rows_total', Number(fh.rows_total).toLocaleString());
          bind('fh_rows_real', Number(fh.rows_real).toLocaleString());
          bind('fh_na_rate', `${fh.na_rate_pct}%`);
          bind('fh_gaps', Number(fh.gaps_missing_slots).toLocaleString());
          bind('fh_misaligned', Number(fh.misaligned_rows).toLocaleString());
          bind('fh_last', fh.last_snapshot_time ? fmtNy(fh.last_snapshot_time) : 'N/A');
        }
      }catch(e){}
    }
    setInterval(refreshHealth, 10000);
    setInterval(refreshSimMetrics, 10000);
    setInterval(refreshLiveMetrics, 10000);
    window.addEventListener('load', ()=>{ refreshHealth(); refreshSimMetrics(); refreshLiveMetrics(); });
    """
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{css}</style></head>
<body><div class="wrap">{body_html}</div><script>{js}</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        if not AUTH_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            user, pw = raw.split(":", 1)
            return user == AUTH_USER and pw == AUTH_PASSWORD
        except Exception:
            return False

    def _send_unauthorized(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Kalshi Dashboard"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Unauthorized")

    def _send(self, body: str, code: int = 200, extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _cookie_map(self):
        raw = self.headers.get("Cookie", "")
        out = {}
        for part in raw.split(";"):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        return out

    def _live_authorized(self, parsed=None) -> bool:
        if not LIVE_TRADING_PASSWORD:
            return True
        if self._cookie_map().get(LIVE_COOKIE_NAME) == "ok":
            return True
        if parsed is not None:
            qs = parse_qs(parsed.query)
            qp = qs.get("live_password", [""])[0]
            if qp and qp == LIVE_TRADING_PASSWORD:
                return True
        return False

    def do_GET(self):
        if not self._authorized():
            self._send_unauthorized()
            return

        parsed = urlparse(self.path)
        if parsed.path == "/model_research":
            payload = model_research_summary()
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/live_unlock":
            qs = parse_qs(parsed.query)
            pw = qs.get("password", [""])[0]
            if pw == LIVE_TRADING_PASSWORD:
                self.send_response(302)
                self.send_header("Set-Cookie", f"{LIVE_COOKIE_NAME}=ok; Path=/; Max-Age=86400; SameSite=Lax")
                self.send_header("Location", "/?tab=live-trading")
                self.end_headers()
                return
            self._send("Live trading password invalid.", 403)
            return

        if parsed.path == "/":
            qs = parse_qs(parsed.query)
            tab = qs.get("tab", ["data-pipeline"])[0]
            counts = table_counts()
            latest = latest_forward_status()
            fh = forward_feed_health()
            mg = latest_model_guard()
            ss = sim_summary()
            cards = "".join(
                [
                    f'<div class="card"><div class="k">{html.escape(t)}</div><div class="v" data-count-key="{html.escape(t)}">{counts.get(t,0):,}</div></div>'
                    for t in TABLES
                ]
            )
            links = "".join([f'<li><a class="pill" href="/table?name={t}">{t}</a></li>' for t in TABLES])
            latest_text = (
                f"last forward: {latest['snapshot_time_utc']} | {latest['market_ticker']} | {latest['status']}"
                if latest
                else "no forward snapshots yet"
            )
            tabs = (
                "<div class='panel' style='margin-bottom:12px'>"
                "<div class='table-links'>"
                "<a class='pill' href='/?tab=data-pipeline'>data pipeline</a>"
                "<a class='pill' href='/?tab=simulated-trading'>simulated trading</a>"
                "<a class='pill' href='/?tab=live-trading'>live trading</a>"
                "</div></div>"
            )

            if tab == "simulated-trading":
                body = f"""
                <div class="top">
                  <div>
                    <h1 class="title">Simulated Trading</h1>
                    <div class="sub">Historical backtest with fixed-model in-sample vs out-of-sample evaluation.</div>
                  </div>
                  <div class="sub">Auth user: <b>{html.escape(AUTH_USER)}</b></div>
                </div>
                {tabs}
                <div id="sim-root">
                <div class="grid4">
                  <div class="card"><div class="k">Initial Capital</div><div class="v">$100.00</div></div>
                  <div class="card"><div class="k">Refresh</div><div class="v" style="font-size:18px">every 10s</div></div>
                  <div class="card"><div class="k">Live Cutoff</div><div id="sim_cutoff" class="v" style="font-size:13px">loading...</div></div>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Portfolio Manager</a></div><div class="muted" id="pm_status">loading...</div></div>
                  <div id="pm_grid" class="pm-grid" style="margin-top:10px"></div>
                </div>
                <div id="sim_model_rows" style="margin-top:12px"></div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Portfolio Equity (Segmented, each starts at $100)</a></div></div>
                  <div id="sim_legend" class="toolbar" style="margin-bottom:8px"></div>
                  <div class="muted" style="margin-bottom:6px">In-Sample <span id="range_in_sample"></span></div>
                  <canvas id="equity_chart_in_sample" width="1120" height="220" style="width:100%;height:220px"></canvas>
                  <div class="muted" style="margin:10px 0 6px 0">Out-of-Sample <span id="range_out_sample"></span></div>
                  <canvas id="equity_chart_out_sample" width="1120" height="220" style="width:100%;height:220px"></canvas>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Cash vs Position Value (20s)</a></div><div class="muted" id="sim_stack_model"></div></div>
                  <canvas id="stack_chart" width="1120" height="220" style="width:100%;height:220px"></canvas>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Drawdown (20s)</a></div><div class="muted" id="sim_drawdown_model"></div></div>
                  <canvas id="drawdown_chart" width="1120" height="180" style="width:100%;height:180px"></canvas>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Open Positions</a></div></div>
                  <div style="overflow:auto;max-height:22vh">
                    <table><thead><tr><th>model</th><th>ticker</th><th>qty</th><th>entry</th><th>mark bid</th><th>unrealized</th><th>opened</th></tr></thead>
                    <tbody id="open_positions_body"></tbody></table>
                  </div>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Trade Timeline / Recent Trades</a></div></div>
                  <div style="overflow:auto;max-height:32vh">
                    <table><thead><tr><th>id</th><th>model</th><th>ticker</th><th>opened</th><th>closed</th><th>qty</th><th>entry</th><th>exit</th><th>pnl</th><th>status</th><th>expected entry</th><th>slippage</th><th>fill mode</th></tr></thead>
                    <tbody id="trades_body"></tbody></table>
                  </div>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Prediction Diagnostics (Calibration)</a></div></div>
                  <div style="overflow:auto;max-height:32vh">
                    <table><thead><tr><th>model</th><th>bucket</th><th>n</th><th>avg pred</th><th>avg realized</th></tr></thead>
                    <tbody id="calib_body"></tbody></table>
                  </div>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Execution Quality</a></div></div>
                  <div style="overflow:auto;max-height:24vh">
                    <table><thead><tr><th>model</th><th>n</th><th>avg slippage</th><th>avg abs slippage</th></tr></thead>
                    <tbody id="exec_body"></tbody></table>
                  </div>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">In-Sample Metrics (before live cutoff)</a></div></div>
                  <div style="overflow:auto;max-height:24vh">
                    <table><thead><tr><th>model</th><th>closed</th><th>total pnl</th><th>avg pnl</th><th>win rate</th><th>pred n</th><th>brier</th><th>logloss</th></tr></thead>
                    <tbody id="insample_body"></tbody></table>
                  </div>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Out-of-Sample Metrics (from live cutoff)</a></div></div>
                  <div style="overflow:auto;max-height:24vh">
                    <table><thead><tr><th>model</th><th>closed</th><th>total pnl</th><th>avg pnl</th><th>win rate</th><th>pred n</th><th>brier</th><th>logloss</th></tr></thead>
                    <tbody id="oos_body"></tbody></table>
                  </div>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Model Research (Hyper-Tuned + Shapley Selection)</a></div><div id="mr_last_run" class="muted">loading...</div></div>
                  <div style="overflow:auto;max-height:30vh">
                    <table><thead><tr><th>model</th><th>run id</th><th>run time</th><th>oos pnl</th><th>brier</th><th>logloss</th><th>train</th><th>eval</th><th>params</th><th>selected features</th></tr></thead>
                    <tbody id="mr_best_models_body"></tbody></table>
                  </div>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Feature Importance (Best Models)</a></div></div>
                  <div style="overflow:auto;max-height:26vh">
                    <table><thead><tr><th>model</th><th>run id</th><th>rank</th><th>feature</th><th>|shap| mean</th><th>signed mean</th><th>method</th></tr></thead>
                    <tbody id="mr_feature_importance_body"></tbody></table>
                  </div>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Research Runs (Recent)</a></div></div>
                  <div style="overflow:auto;max-height:24vh">
                    <table><thead><tr><th>id</th><th>time</th><th>model</th><th>stage</th><th>oos pnl</th><th>train</th><th>eval</th><th>status</th><th>notes</th></tr></thead>
                    <tbody id="mr_recent_runs_body"></tbody></table>
                  </div>
                </div>
                </div>
                """
                self._send(render_page("Simulated Trading", body))
                return

            if tab == "live-trading":
                if not self._live_authorized(parsed):
                    body = f"""
                    <div class="top">
                      <div><h1 class="title">Live Trading Locked</h1><div class="sub">Enter secondary password to access live execution controls.</div></div>
                      <div class="sub">Auth user: <b>{html.escape(AUTH_USER)}</b></div>
                    </div>
                    {tabs}
                    <div class="panel" style="max-width:620px;margin:24px auto">
                      <form method="GET" action="/" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                        <input type="hidden" name="tab" value="live-trading">
                        <input type="password" name="live_password" placeholder="Live trading password" style="flex:1;min-width:220px;background:#0b1723;border:1px solid #1f3448;border-radius:10px;color:#e5edf7;padding:10px 12px">
                        <button class="pill" type="submit">Unlock Live Trading</button>
                      </form>
                    </div>
                    """
                    self._send(render_page("Live Trading Locked", body))
                    return
                body = f"""
                <div class="top">
                  <div>
                    <h1 class="title">Live Trading</h1>
                    <div class="sub">Multi-strategy live execution - each strategy has its own on/off switch, risk caps, and auto-pause on breach.</div>
                  </div>
                  <div class="sub">Auth user: <b>{html.escape(AUTH_USER)}</b></div>
                </div>
                {tabs}
                <div id="live-root">
                <div id="live_balance_note" class="panel live-panel" style="display:none">
                  <div class="live-banner">&#9888; REAL BALANCE UNAVAILABLE &#9888;</div>
                  <div class="muted">Kalshi API trading credentials are not configured on this server, so the account cash/equity shown below is an internal estimate (starting capital plus tracked PnL), not your real Kalshi balance. Real order placement will also fail until credentials are configured. This does not block strategy toggles or monitoring below - it only affects the balance shown and whether an ON strategy can actually place a real order.</div>
                </div>
                <div class="panel live-panel">
                  <div class="live-banner">&#9888; REAL MONEY - LIVE EXECUTION CONTROLS &#9888;</div>
                  <div class="bar"><div class="nav">Account</div></div>
                  <div id="live_score" class="grid4"></div>
                </div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Live Equity (20s)</div></div><canvas id="live_equity_chart" width="1120" height="250" style="width:100%;height:250px"></canvas></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Live Cash vs Position Value (20s)</div></div><canvas id="live_stack_chart" width="1120" height="220" style="width:100%;height:220px"></canvas></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Live Drawdown (20s)</div></div><canvas id="live_drawdown_chart" width="1120" height="180" style="width:100%;height:180px"></canvas></div>
                <div class="panel live-panel" style="margin-top:12px">
                  <div class="bar"><div class="nav">Strategies</div></div>
                  <div id="live_strategy_cards" class="row4"></div>
                </div>
                <div class="panel live-panel" style="margin-top:12px"><div class="bar"><div class="nav">Open Positions</div></div><div style="overflow:auto;max-height:24vh"><table><thead><tr><th>strategy</th><th>ticker</th><th>qty</th><th>entry</th><th>mark bid</th><th>unrealized</th><th>opened</th><th>action</th></tr></thead><tbody id="live_open_positions_body"></tbody></table></div></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Recent Orders</div></div><div style="overflow:auto;max-height:24vh"><table><thead><tr><th>time</th><th>ticker</th><th>action</th><th>side</th><th>qty</th><th>limit</th><th>status</th><th>order id</th><th>client id</th></tr></thead><tbody id="live_orders_body"></tbody></table></div></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Recent Trades</div></div><div style="overflow:auto;max-height:24vh"><table><thead><tr><th>strategy</th><th>opened</th><th>closed</th><th>ticker</th><th>qty</th><th>entry</th><th>exit</th><th>pnl</th><th>status</th></tr></thead><tbody id="live_trades_body"></tbody></table></div></div>
                </div>
                """
                self._send(render_page("Live Trading", body))
                return

            body = f"""
            <div class="top">
              <div>
                <h1 class="title">Data Pipeline</h1>
                <div class="sub">Live data observability for markets, candles, forward snapshots, and 1m features.</div>
              </div>
              <div class="sub">Auth user: <b>{html.escape(AUTH_USER)}</b></div>
            </div>
            {tabs}
            <div class="grid">{cards}</div>
            <div class="panel">
              <div class="bar"><div class="nav"><a href="/?tab=data-pipeline">Overview</a></div><div><span id="latest-forward" class='badge'>{latest_text}</span></div></div>
              <div class="muted" style="margin-bottom:10px">Data tables</div>
              <ul class="table-links">{links}</ul>
            </div>
            <div class="panel" style="margin-top:12px">
              <div class="bar">
                <div class="nav"><a href="/">Forward Feed Health</a></div>
                <div class="muted">window: last {fh['window_minutes']} minutes</div>
              </div>
              <div class="grid4">
                <div class="card"><div class="k">Rows Total</div><div id="fh_rows_total" class="v">{fh['rows_total']:,}</div></div>
                <div class="card"><div class="k">Rows Real</div><div id="fh_rows_real" class="v">{fh['rows_real']:,}</div></div>
                <div class="card"><div class="k">N/A Rate</div><div id="fh_na_rate" class="v">{fh['na_rate_pct']}%</div></div>
                <div class="card"><div class="k">Missing 20s Slots</div><div id="fh_gaps" class="v">{fh['gaps_missing_slots']:,}</div></div>
              </div>
              <div class="grid4">
                <div class="card"><div class="k">Misaligned Rows</div><div id="fh_misaligned" class="v">{fh['misaligned_rows']:,}</div></div>
                <div class="card"><div class="k">Last Snapshot UTC</div><div id="fh_last" class="v" style="font-size:18px">{fh['last_snapshot_time'] or 'N/A'}</div></div>
              </div>
            </div>
            <div class="panel" style="margin-top:12px">
              <div class="bar">
                <div class="nav"><a href="/">Model Data Guard</a></div>
                <div class="muted">latest minute eligibility check</div>
              </div>
              <div class="grid4">
                <div class="card"><div class="k">Guard Status</div><div class="v">{(mg or {}).get('guard_status','N/A')}</div></div>
                <div class="card"><div class="k">Model Eligible</div><div class="v">{(mg or {}).get('model_eligible','N/A')}</div></div>
                <div class="card"><div class="k">Snapshot Minute UTC</div><div class="v" style="font-size:18px">{(str((mg or {}).get('snapshot_minute_utc')) if mg else 'N/A')}</div></div>
                <div class="card"><div class="k">Ticker</div><div class="v" style="font-size:16px">{html.escape(str((mg or {}).get('market_ticker','N/A')))}</div></div>
              </div>
            </div>
            """
            self._send(render_page("Data Pipeline", body))
            return

        if parsed.path == "/health":
            counts = table_counts()
            latest = latest_forward_status()
            fh = forward_feed_health()
            mg = latest_model_guard()
            ss = sim_health_summary()
            if latest and latest.get("snapshot_time_utc"):
                latest["snapshot_time_utc"] = str(latest["snapshot_time_utc"])
            if mg and mg.get("snapshot_minute_utc"):
                mg["snapshot_minute_utc"] = str(mg["snapshot_minute_utc"])
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"ok": True, "counts": counts, "latest_forward": latest, "forward_health": fh, "model_guard": mg, "sim_summary": ss}
                ).encode("utf-8")
            )
            return

        if parsed.path == "/api/tables":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "tables": API_TABLES,
                        "time_columns": API_TIME_COLUMN,
                        "max_limit": API_MAX_LIMIT,
                    }
                ).encode("utf-8")
            )
            return

        if parsed.path == "/api/table":
            qs = parse_qs(parsed.query)
            name = qs.get("name", [""])[0]
            offset = int(qs.get("offset", ["0"])[0])
            limit = int(qs.get("limit", ["1000"])[0])
            start = qs.get("start", [None])[0]
            end = qs.get("end", [None])[0]
            cols_raw = qs.get("columns", [""])[0]
            columns = [c.strip() for c in cols_raw.split(",") if c.strip()] if cols_raw else None
            try:
                payload = query_api_rows(
                    table=name,
                    offset=offset,
                    limit=limit,
                    start=start,
                    end=end,
                    columns=columns,
                )
                self.send_response(200)
            except Exception as e:
                payload = {"ok": False, "error": str(e)}
                self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, default=str).encode("utf-8"))
            return

        if parsed.path == "/sim_metrics":
            qs = parse_qs(parsed.query)
            window_hours = _parse_window_hours(qs, 6)
            data = sim_metrics(window_hours=window_hours)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if parsed.path == "/live_metrics":
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            qs = parse_qs(parsed.query)
            window_hours = _parse_window_hours(qs, 12)
            data = live_metrics(window_hours=window_hours)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if parsed.path == "/table":
            qs = parse_qs(parsed.query)
            name = qs.get("name", [""])[0]
            page = int(qs.get("page", ["1"])[0])
            if name not in TABLES:
                self._send("invalid table", 400)
                return
            total, rows = query_rows(name, page)
            cols = list(rows[0].keys()) if rows else []
            header = "".join([f"<th>{html.escape(str(c))}</th>" for c in cols])
            body_rows = []
            for r in rows:
                tds = "".join([f"<td>{html.escape(str(r[c]))}</td>" for c in cols])
                body_rows.append(f"<tr>{tds}</tr>")
            prev_link = f"<a class='pill' href='/table?name={name}&page={max(1,page-1)}'>Prev</a>"
            next_link = f"<a class='pill' href='/table?name={name}&page={page+1}'>Next</a>"
            body = (
                f"<div class='top'><div><h1 class='title'>Table: {html.escape(name)}</h1>"
                f"<div class='sub'>Total rows: {total:,} | Page: {page}</div></div>"
                f"<div class='nav'><a href='/'>Back to overview</a></div></div>"
                f"<div class='panel'><div class='bar'><div>{prev_link} {next_link}</div>"
                f"<div class='muted'>page size {PAGE_SIZE}</div></div>"
                f"<div style='overflow:auto;max-height:70vh'><table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div></div>"
            )
            self._send(render_page(f"Table {name}", body))
            return

        self._send("not found", 404)

    def do_POST(self):
        if not self._authorized():
            self._send_unauthorized()
            return
        parsed = urlparse(self.path)
        if parsed.path == "/live_settings":
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                model_name = str(payload.pop("model_name", "") or "").strip()
                if model_name not in LIVE_MODELS:
                    raise ValueError(f"model_name must be one of {LIVE_MODELS}")
                cfg = live_settings_update(model_name, payload)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "settings": cfg}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        if parsed.path == "/live_model/toggle":
            # The ON/OFF switch a human clicks per strategy. Never called by
            # any automated code path in this codebase - only from the
            # dashboard button, gated by the live password.
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                model_name = str(payload.get("model_name") or "").strip()
                if model_name not in LIVE_MODELS:
                    raise ValueError(f"model_name must be one of {LIVE_MODELS}")
                live_enabled = bool(payload.get("live_enabled"))
                cfg = live_settings_update(model_name, {"live_enabled": live_enabled})
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "settings": cfg}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        if parsed.path == "/live_model/resume":
            # Clears an auto-triggered risk-breach pause. Does not turn the
            # strategy ON by itself - live_enabled is unaffected.
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                model_name = str(payload.get("model_name") or "").strip()
                if model_name not in LIVE_MODELS:
                    raise ValueError(f"model_name must be one of {LIVE_MODELS}")
                conn = get_db_conn()
                with conn.cursor() as cur:
                    clear_live_model_paused(cur, model_name, utc_now())
                conn.commit()
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        if parsed.path == "/live_position/close":
            # Manually close one existing live position. This is a real,
            # human-clicked action - the account owner reviews and clicks,
            # this handler never fires on its own. Gated by the same live
            # password as /live_settings.
            if not self._live_authorized():
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                ticker = str(payload.get("market_ticker") or "").strip()
                model_name = str(payload.get("model_name") or "").strip()
                if not ticker:
                    raise ValueError("market_ticker is required")
                if not model_name:
                    raise ValueError("model_name is required")
                bid = latest_bid_for_ticker(ticker)
                if bid is None or bid <= 0:
                    raise ValueError(f"no valid current bid available for {ticker} - refusing to close blind")
                conn = get_db_conn()
                with conn.cursor() as cur:
                    kernel = DummyExecutionKernel(place_limit_order)
                    close_live_position(cur, kernel, model_name, ticker, bid, utc_now())
                conn.commit()
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "market_ticker": ticker, "close_bid": bid}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        if parsed.path == "/sim_risk/resume":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                model_name = str(payload.get("model_name") or "").strip()
                if not model_name:
                    raise ValueError("model_name is required")
                conn = get_db_conn()
                with conn.cursor() as cur:
                    clear_model_paused(cur, model_name, utc_now())
                conn.commit()
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "model_name": model_name}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return
        self._send("not found", 404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"Dashboard listening on {HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
