import html
import os
import base64
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from data_pipeline.common import get_db_conn

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
    "sim_model_lab_runs",
    "sim_model_lab_results",
    "live_settings",
    "live_orders",
    "live_positions",
    "live_trades",
    "live_portfolio_20s",
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
    "sim_model_lab_runs",
    "sim_model_lab_results",
]
API_TIME_COLUMN = {
    "model_features_1m": "snapshot_minute_utc",
    "trade_quote_features_1m": "snapshot_minute_utc",
    "forward_quotes": "snapshot_time_utc",
    "coinbase_ticks": "snapshot_time_utc",
    "sim_model_predictions_1m": "snapshot_minute_utc",
    "sim_trades": "opened_at_utc",
    "sim_portfolio_20s": "snapshot_time_utc",
    "sim_model_lab_runs": "run_time_utc",
    "sim_model_lab_results": None,
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


def table_counts():
    conn = get_db_conn()
    out = {}
    with conn.cursor() as cur:
        for t in TABLES:
            cur.execute(f"SELECT COUNT(*) AS c FROM {t}")
            out[t] = cur.fetchone()["c"]
    conn.close()
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
            out["models"].append(
                {
                    "model_name": r["model_name"],
                    "closed_trades": closed,
                    "total_pnl": float(r["total_pnl"] or 0),
                    "win_rate": (wins / closed) if closed > 0 else None,
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
            ORDER BY snapshot_minute_utc DESC, model_name ASC
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
            out["models"].append(
                {
                    "model_name": r["model_name"],
                    "closed_trades": int(r["closed_trades"] or 0),
                    "total_pnl": float(r["total_pnl"] or 0),
                }
            )
    conn.close()
    return out


def _bucket_key(p: float) -> str:
    lo = max(0.0, min(0.9, (int(p * 10) / 10.0)))
    hi = lo + 0.1
    return f"{lo:.1f}-{hi:.1f}"


def sim_metrics(window_hours: int = 6):
    conn = get_db_conn()
    out = {
        "starting_capital": 100.0,
        "live_cutoff_utc": None,
        "live_forward_start_utc": None,
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
        "live_forward": [],
        "model_lab_latest": [],
        "model_lab_run": None,
        "lab_variant_series": {},
        "model_selector_items": [],
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
            SELECT snapshot_minute_utc, model_name, cumulative_pnl_dollars
            FROM sim_equity_1m
            ORDER BY snapshot_minute_utc ASC
            """
        )
        for r in cur.fetchall():
            m = r["model_name"]
            ts = str(r["snapshot_minute_utc"])
            eq = 100.0 + float(r["cumulative_pnl_dollars"] or 0.0)
            out["equity_series_1m"].setdefault(m, []).append({"t": ts, "equity": eq})

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
            score_map[r["model_name"]] = {
                "model_name": r["model_name"],
                "closed_trades": closed,
                "total_pnl": float(r["total_pnl"] or 0),
                "avg_trade_pnl": float(r["avg_pnl"] or 0),
                "win_rate": (wins / closed) if closed > 0 else None,
            }

        cur.execute(
            """
            SELECT p.model_name, p.equity_dollars, p.position_value_dollars
            FROM sim_portfolio_20s p
            JOIN (
              SELECT model_name, MAX(snapshot_time_utc) mx
              FROM sim_portfolio_20s
              GROUP BY model_name
            ) x ON x.model_name=p.model_name AND x.mx=p.snapshot_time_utc
            """
        )
        for r in cur.fetchall():
            m = r["model_name"]
            sc = score_map.get(m, {"model_name": m, "closed_trades": 0, "total_pnl": 0.0, "avg_trade_pnl": 0.0, "win_rate": None})
            sc["equity"] = float(r["equity_dollars"])
            sc["return_pct"] = ((sc["equity"] / 100.0) - 1.0) * 100.0
            sc["position_value"] = float(r["position_value_dollars"] or 0.0)
            out["scorecards"].append(sc)

        cur.execute(
            """
            SELECT p.model_name, p.market_ticker, p.qty_contracts, p.entry_price_dollars, p.opened_at_utc,
                   fq.yes_bid_dollars, fq.yes_ask_dollars
            FROM sim_positions p
            LEFT JOIN (
              SELECT f1.*
              FROM forward_quotes f1
              JOIN (
                SELECT market_ticker, MAX(snapshot_time_utc) mx
                FROM forward_quotes
                GROUP BY market_ticker
              ) f2 ON f2.market_ticker=f1.market_ticker AND f2.mx=f1.snapshot_time_utc
            ) fq ON fq.market_ticker=p.market_ticker
            ORDER BY p.opened_at_utc DESC
            """
        )
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

        cur.execute("SELECT run_id, run_time_utc FROM sim_model_lab_runs ORDER BY run_id DESC LIMIT 1")
        rr = cur.fetchone()
        if rr:
            out["model_lab_run"] = {"run_id": int(rr["run_id"]), "run_time_utc": str(rr["run_time_utc"])}
            out["live_forward_start_utc"] = str(rr["run_time_utc"])

        cutoff = out.get("live_cutoff_utc")
        live_start = out.get("live_forward_start_utc")
        if cutoff and live_start:
            out["in_sample"] = _segment_stats("opened_at_utc < %s", "snapshot_minute_utc < %s", (cutoff,))
            out["out_of_sample"] = _segment_stats(
                "opened_at_utc >= %s AND opened_at_utc < %s",
                "snapshot_minute_utc >= %s AND snapshot_minute_utc < %s",
                (cutoff, live_start),
            )
            out["live_forward"] = _segment_stats(
                "opened_at_utc >= %s",
                "snapshot_minute_utc >= %s",
                (live_start,),
            )
        elif cutoff:
            out["in_sample"] = _segment_stats("opened_at_utc < %s", "snapshot_minute_utc < %s", (cutoff,))
            out["out_of_sample"] = _segment_stats("opened_at_utc >= %s", "snapshot_minute_utc >= %s", (cutoff,))
            out["live_forward"] = _segment_stats("1=0", "1=0", tuple())
        else:
            out["in_sample"] = _segment_stats("1=1", "1=1", tuple())
            out["out_of_sample"] = _segment_stats("1=0", "1=0", tuple())
            out["live_forward"] = _segment_stats("1=0", "1=0", tuple())

        if rr:
            cur.execute(
                """
                SELECT variant_id, model_family, horizon_min, pred_threshold, edge_threshold, segment,
                       n_trades, total_pnl, win_rate, brier, logloss, max_drawdown, sharpe_like
                FROM sim_model_lab_results
                WHERE run_id=%s
                ORDER BY
                  CASE segment
                    WHEN 'live_forward' THEN 1
                    WHEN 'out_of_sample' THEN 2
                    ELSE 3
                  END,
                  total_pnl DESC
                LIMIT 120
                """,
                (rr["run_id"],),
            )
            for r in cur.fetchall():
                out["model_lab_latest"].append(
                    {
                        "variant_id": r["variant_id"],
                        "model_family": r["model_family"],
                        "horizon_min": int(r["horizon_min"]),
                        "pred_threshold": float(r["pred_threshold"]),
                        "edge_threshold": float(r["edge_threshold"]),
                        "segment": r["segment"],
                        "n_trades": int(r["n_trades"]),
                        "total_pnl": float(r["total_pnl"] or 0.0),
                        "win_rate": float(r["win_rate"]) if r["win_rate"] is not None else None,
                        "brier": float(r["brier"]) if r["brier"] is not None else None,
                        "logloss": float(r["logloss"]) if r["logloss"] is not None else None,
                        "max_drawdown": float(r["max_drawdown"] or 0.0),
                        "sharpe_like": float(r["sharpe_like"]) if r["sharpe_like"] is not None else None,
                    }
                )

            cur.execute(
                """
                SELECT r.run_time_utc, x.variant_id, x.total_pnl
                FROM sim_model_lab_results x
                JOIN sim_model_lab_runs r ON r.run_id=x.run_id
                WHERE x.segment='live_forward'
                  AND r.run_time_utc >= (UTC_TIMESTAMP() - INTERVAL 7 DAY)
                ORDER BY r.run_time_utc ASC
                """
            )
            for r in cur.fetchall():
                vid = r["variant_id"]
                ts = str(r["run_time_utc"])
                eq = 100.0 + float(r["total_pnl"] or 0.0)
                out["lab_variant_series"].setdefault(vid, []).append({"t": ts, "equity": eq})

        # Model selector list (ranked): one model/variant per row with compact IS/OOS/LIVE sub-metrics.
        selector_items = []
        for sc in out["scorecards"]:
            total_pnl = float(sc.get("total_pnl") or 0.0)
            current_pnl = float(sc.get("equity", 100.0)) - 100.0
            out["model_selector_items"].append(
                {
                    "id": f"sim:{sc['model_name']}",
                    "kind": "sim",
                    "name": sc["model_name"],
                    "rank": 0,
                    "total_pnl": total_pnl,
                    "win_rate": sc.get("win_rate"),
                    "n_trades": int(sc.get("closed_trades") or 0),
                    "horizon_min": 1,
                    "segment": "combined",
                    "current_pnl": current_pnl,
                    "current_position": float(sc.get("position_value") or 0.0),
                    "eval_mode": "online",
                    "segments": {
                        "live_forward": {
                            "n_trades": int(sc.get("closed_trades") or 0),
                            "total_pnl": total_pnl,
                            "win_rate": sc.get("win_rate"),
                        }
                    },
                }
            )

        lab_rollup: Dict[str, Dict[str, Any]] = {}
        for lr in out["model_lab_latest"]:
            vid = lr["variant_id"]
            seg = str(lr.get("segment") or "unknown")
            rec = lab_rollup.setdefault(
                vid,
                {
                    "id": f"lab:{vid}",
                    "kind": "lab",
                    "name": vid,
                    "rank": 0,
                    "total_pnl": 0.0,
                    "n_trades": 0,
                    "horizon_min": int(lr.get("horizon_min") or 1),
                    "segment": "combined",
                    "current_position": None,
                    "eval_mode": "offline_eval",
                    "segments": {},
                    "_win_num": 0.0,
                    "_win_den": 0,
                },
            )
            seg_trades = int(lr.get("n_trades") or 0)
            seg_pnl = float(lr.get("total_pnl") or 0.0)
            seg_win = lr.get("win_rate")
            rec["segments"][seg] = {"n_trades": seg_trades, "total_pnl": seg_pnl, "win_rate": seg_win}
            rec["total_pnl"] += seg_pnl
            rec["n_trades"] += seg_trades
            if seg_win is not None and seg_trades > 0:
                rec["_win_num"] += float(seg_win) * seg_trades
                rec["_win_den"] += seg_trades
            if seg == "live_forward":
                rec["current_pnl"] = seg_pnl

        for rec in lab_rollup.values():
            den = int(rec.pop("_win_den", 0))
            num = float(rec.pop("_win_num", 0.0))
            rec["win_rate"] = (num / den) if den > 0 else None
            rec.setdefault("current_pnl", rec["total_pnl"])
            selector_items.append(rec)

        selector_items.extend(out["model_selector_items"])
        selector_items.sort(
            key=lambda x: (
                -(x.get("current_pnl") or 0.0),
                -(x.get("total_pnl") or 0.0),
                -(x.get("n_trades") or 0),
                x["id"],
            )
        )
        for i, item in enumerate(selector_items, start=1):
            item["rank"] = i
        out["model_selector_items"] = selector_items

    conn.close()
    return out


def model_lab_metrics(limit_rows: int = 600):
    conn = get_db_conn()
    out = {"latest_run": None, "champion": None, "rows": []}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_id, run_time_utc, cutoff_utc, sample_rows
            FROM sim_model_lab_runs
            ORDER BY run_id DESC
            LIMIT 1
            """
        )
        rr = cur.fetchone()
        if not rr:
            conn.close()
            return out
        out["latest_run"] = {
            "run_id": int(rr["run_id"]),
            "run_time_utc": str(rr["run_time_utc"]),
            "cutoff_utc": str(rr["cutoff_utc"]) if rr.get("cutoff_utc") else None,
            "sample_rows": int(rr.get("sample_rows") or 0),
        }

        cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_model_lab_champion' LIMIT 1")
        ch = cur.fetchone()
        if ch:
            sv = ch["state_value"]
            try:
                out["champion"] = sv if isinstance(sv, dict) else json.loads(sv)
            except Exception:
                out["champion"] = {"raw": str(sv)}

        cur.execute(
            """
            SELECT variant_id, model_family, horizon_min, pred_threshold, edge_threshold, segment,
                   n_samples, n_trades, trade_rate, win_rate, total_pnl, avg_pnl, pnl_per_trade,
                   brier, logloss, max_drawdown, sharpe_like
            FROM sim_model_lab_results
            WHERE run_id=%s
            ORDER BY
              CASE segment WHEN 'live_forward' THEN 1 WHEN 'out_of_sample' THEN 2 ELSE 3 END,
              total_pnl DESC
            LIMIT %s
            """,
            (rr["run_id"], limit_rows),
        )
        for r in cur.fetchall():
            out["rows"].append(
                {
                    "variant_id": r["variant_id"],
                    "model_family": r["model_family"],
                    "horizon_min": int(r["horizon_min"]),
                    "pred_threshold": float(r["pred_threshold"]),
                    "edge_threshold": float(r["edge_threshold"]),
                    "segment": r["segment"],
                    "n_samples": int(r["n_samples"]),
                    "n_trades": int(r["n_trades"]),
                    "trade_rate": float(r["trade_rate"] or 0.0),
                    "win_rate": float(r["win_rate"]) if r["win_rate"] is not None else None,
                    "total_pnl": float(r["total_pnl"] or 0.0),
                    "avg_pnl": float(r["avg_pnl"] or 0.0),
                    "pnl_per_trade": float(r["pnl_per_trade"] or 0.0),
                    "brier": float(r["brier"]) if r["brier"] is not None else None,
                    "logloss": float(r["logloss"]) if r["logloss"] is not None else None,
                    "max_drawdown": float(r["max_drawdown"] or 0.0),
                    "sharpe_like": float(r["sharpe_like"]) if r["sharpe_like"] is not None else None,
                }
            )
    conn.close()
    return out


def default_live_settings():
    return {
        "live_enabled": False,
        "starting_capital": 30.0,
        "signal_threshold": 0.55,
        "edge_threshold": 0.01,
        "max_trade_cost": 2.0,
        "max_open_notional": 6.0,
        "max_concurrent_positions": 1,
        "max_daily_loss": 5.0,
        "max_total_drawdown": 10.0,
        "min_samples_default_rf": 1000,
    }


def live_settings_get():
    conn = get_db_conn()
    out = default_live_settings()
    with conn.cursor() as cur:
        cur.execute("SELECT settings_json FROM live_settings WHERE settings_key='live_config' LIMIT 1")
        r = cur.fetchone()
        if r:
            cfg = r["settings_json"] if isinstance(r["settings_json"], dict) else json.loads(r["settings_json"])
            out.update(cfg or {})
        else:
            cur.execute(
                """
                INSERT INTO live_settings (settings_key, settings_json, updated_at_utc)
                VALUES ('live_config', %s, UTC_TIMESTAMP())
                """,
                (json.dumps(out),),
            )
    conn.close()
    return out


def live_settings_update(patch: Dict):
    allowed = set(default_live_settings().keys())
    cur_cfg = live_settings_get()
    for k, v in patch.items():
        if k not in allowed:
            continue
        cur_cfg[k] = v
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO live_settings (settings_key, settings_json, updated_at_utc)
            VALUES ('live_config', %s, UTC_TIMESTAMP())
            ON DUPLICATE KEY UPDATE settings_json=VALUES(settings_json), updated_at_utc=VALUES(updated_at_utc)
            """,
            (json.dumps(cur_cfg),),
        )
    conn.close()
    return cur_cfg


def live_metrics(window_hours: int = 12):
    conn = get_db_conn()
    out = {
        "settings": live_settings_get(),
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
        for r in cur.fetchall():
            ts = str(r["snapshot_time_utc"])
            out["equity_series_20s"].append({"t": ts, "equity": float(r["equity_dollars"])})
            out["stack_series_20s"].append({"t": ts, "cash": float(r["cash_dollars"]), "position": float(r["position_value_dollars"])})
            out["drawdown_series_20s"].append({"t": ts, "drawdown": float(r["drawdown_dollars"])})
            out["risk_state"] = r["risk_state"]
            try:
                raw = r["raw_json"] if isinstance(r["raw_json"], dict) else json.loads(r["raw_json"] or "{}")
                out["cash_source"] = raw.get("cash_source", out["cash_source"])
            except Exception:
                pass

        cur.execute("SELECT COUNT(*) c, COALESCE(SUM(pnl_dollars),0) p, COALESCE(AVG(pnl_dollars),0) a, COALESCE(SUM(pnl_dollars>0),0) w FROM live_trades WHERE status='closed'")
        s = cur.fetchone()
        closed = int(s["c"] or 0)
        wins = int(s["w"] or 0)
        out["scorecard"] = {
            "closed_trades": closed,
            "total_pnl": float(s["p"] or 0),
            "avg_pnl": float(s["a"] or 0),
            "win_rate": (wins / closed) if closed > 0 else None,
            "equity": (out["equity_series_20s"][-1]["equity"] if out["equity_series_20s"] else out["settings"]["starting_capital"]),
        }

        cur.execute("SELECT market_ticker, qty_contracts, entry_price_dollars, opened_at_utc FROM live_positions ORDER BY opened_at_utc DESC")
        pos_rows = cur.fetchall()
        for p in pos_rows:
            cur.execute("SELECT yes_bid_dollars FROM forward_quotes WHERE market_ticker=%s ORDER BY snapshot_time_utc DESC LIMIT 1", (p["market_ticker"],))
            q = cur.fetchone()
            bid = float(q["yes_bid_dollars"]) if q and q.get("yes_bid_dollars") is not None else float(p["entry_price_dollars"])
            out["open_positions"].append(
                {
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
            SELECT opened_at_utc, closed_at_utc, market_ticker, qty_contracts, entry_price_dollars, exit_price_dollars, pnl_dollars, status
            FROM live_trades
            ORDER BY id DESC
            LIMIT 40
            """
        )
        out["recent_trades"] = [
            {
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
    .card{background:linear-gradient(180deg,#112334 0%,#0e1b29 100%);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:0 14px 32px rgba(0,0,0,.25)}
    .k{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
    .v{font-size:26px;font-weight:700;margin-top:6px}
    .panel{background:linear-gradient(180deg,#101f2f 0%,#0d1b2a 100%);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:0 14px 32px rgba(0,0,0,.24)}
    .table-links{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
    .pill{display:inline-block;padding:8px 12px;border-radius:999px;text-decoration:none;font-size:13px;color:#c8f1ff;background:var(--brand-soft);border:1px solid #1c5b72}
    .pill:hover{filter:brightness(.98)}
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
    @media (max-width: 1000px){.grid{grid-template-columns:repeat(2,minmax(0,1fr));}.grid4{grid-template-columns:repeat(2,minmax(0,1fr));}.row4{grid-template-columns:repeat(2,minmax(0,1fr));}}
    """
    js = """
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
    function renderSegmentSummary(d, models){
      const pick = (arr)=> (arr||[]).filter(r=>models.includes(r.model_name));
      const segs=[
        ['in_sample','In-Sample', 'before live cutoff', pick(d.in_sample)],
        ['out_of_sample','Out-of-Sample', 'from live cutoff to live-forward start', pick(d.out_of_sample)],
        ['live_forward','Live-Forward', 'after live-forward start', pick(d.live_forward)]
      ];
      const el=document.getElementById('sim_model_rows');
      if(!el) return;
      const blocks=[];
      for(const m of models){
        const cards=[]; 
        const lfRow=(pick(d.live_forward)||[]).find(x=>x.model_name===m);
        const lf=segmentTotals(lfRow?[lfRow]:[]);
        const curEq=100 + Number(lf.pnl||0);
        const curRet=((curEq/100)-1)*100;
        const curWr=(lf.win_rate==null?'N/A':`${(100*Number(lf.win_rate)).toFixed(1)}%`);
        cards.push(`<div class='card'><div class='k'>${m} | Current (live-forward basis)</div><div class='v' style='font-size:20px'>$${curEq.toFixed(2)}</div><div class='muted'>ret ${curRet.toFixed(2)}% | closed ${lf.closed} | win ${curWr}</div></div>`);
        for(const [key,label,scope,rows] of segs){
          const row=(rows||[]).find(x=>x.model_name===m);
          const one=row ? [row] : [];
          const s=segmentTotals(one);
          const wr=(s.win_rate==null?'N/A':`${(100*s.win_rate).toFixed(1)}%`);
          const b=(s.avg_brier==null?'N/A':s.avg_brier.toFixed(4));
          const ll=(s.avg_logloss==null?'N/A':s.avg_logloss.toFixed(4));
          cards.push(`<div class='card'><div class='k'>${m} | ${label}</div><div class='v' style='font-size:20px'>$${s.pnl.toFixed(2)}</div><div class='muted'>${scope}</div><div class='muted'>closed ${s.closed} | win ${wr} | preds ${s.preds} | brier ${b} | logloss ${ll}</div></div>`);
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
    async function refreshSimMetrics(){
      const simRoot=document.getElementById('sim-root');
      if(!simRoot) return;
      try{
        const r=await fetch('/sim_metrics',{cache:'no-store'});
        if(!r.ok) return;
        const d=await r.json();
        const fixedModels=['logistic','random_forest'];
        const byModelRaw=(d.equity_series_1m && Object.keys(d.equity_series_1m).length>0) ? d.equity_series_1m : (d.equity_series_20s||{});
        const series={};
        const colors={};
        let idx=0;
        for(const m of fixedModels){
          if(byModelRaw[m]){ series[m]=byModelRaw[m]; colors[m]=simColor(`sim:${m}`, idx++); }
        }
        drawLineChart('equity_chart', series, 'equity', colors, {unit:'$', cutoff:d.live_cutoff_utc});
        const ddSel={};
        for(const m of fixedModels){ if((d.drawdown_series_20s||{})[m]) ddSel[m]=d.drawdown_series_20s[m]; }
        drawLineChart('drawdown_chart', ddSel, 'drawdown', colors, {cutoff:d.live_cutoff_utc});
        const basePicked=fixedModels;
        const model=(d.stack_series_20s&&d.stack_series_20s.logistic) ? 'logistic' : (Object.keys(d.stack_series_20s||{})[0]);
        if(model && d.stack_series_20s && d.stack_series_20s[model]) drawStackChart('stack_chart', d.stack_series_20s[model], 'cash', 'position', {cutoff:d.live_cutoff_utc});
        renderSegmentSummary(d, basePicked);

        renderRows('open_positions_body', (d.open_positions||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','market_ticker','qty_contracts','entry_price','mark_bid','unrealized_pnl','opened_at_utc']);
        renderRows('trades_body', (d.recent_trades||[]).filter(r => basePicked.includes(r.model_name)).slice(0,30), ['id','model_name','market_ticker','opened_at_utc','closed_at_utc','qty_contracts','entry_price','exit_price','pnl','status','expected_entry','slippage','fill_mode']);
        renderRows('calib_body', (d.calibration||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','bucket','n','avg_pred','avg_realized']);
        renderRows('exec_body', (d.execution_quality||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','n','avg_slippage','avg_abs_slippage']);
        renderRows('insample_body', (d.in_sample||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','closed_trades','total_pnl','avg_pnl','win_rate','n_preds','avg_brier','avg_logloss']);
        renderRows('oos_body', (d.out_of_sample||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','closed_trades','total_pnl','avg_pnl','win_rate','n_preds','avg_brier','avg_logloss']);
        renderRows('model_lab_body', d.model_lab_latest||[], ['segment','variant_id','model_family','horizon_min','pred_threshold','edge_threshold','n_trades','total_pnl','win_rate','max_drawdown','brier','logloss','sharpe_like']);
        const cut=document.getElementById('sim_cutoff');
        if(cut){
          if(d.live_cutoff_utc && d.live_forward_start_utc){
            cut.textContent = `train/live cutoff: ${d.live_cutoff_utc} | live-forward start: ${d.live_forward_start_utc}`;
          }else if(d.live_cutoff_utc){
            cut.textContent = `train/live cutoff: ${d.live_cutoff_utc}`;
          }else{
            cut.textContent = 'cutoff not set';
          }
        }
        const ml=document.getElementById('model_lab_meta');
        if(ml){
          if(d.model_lab_run && d.model_lab_run.run_time_utc){
            ml.textContent = `latest model lab run: ${d.model_lab_run.run_time_utc} UTC`;
          }else{
            ml.textContent = 'model lab run pending';
          }
        }
        const lg=document.getElementById('sim_legend');
        if(lg){
          lg.innerHTML = Object.keys(series).map((k,i)=>`<span class='pill' style='border-color:${colors[k]};color:${colors[k]}'>${k}</span>`).join(' ');
        }
      }catch(e){}
    }
    async function refreshLiveMetrics(){
      const root=document.getElementById('live-root');
      if(!root) return;
      try{
        const lp = livePass();
        const r=await fetch('/live_metrics' + (lp?('?live_password='+encodeURIComponent(lp)):'') ,{cache:'no-store'});
        if(!r.ok) return;
        const d=await r.json();
        drawLineChart('live_equity_chart', {'live': d.equity_series_20s||[]}, 'equity', {'live':'#22d3ee'}, {unit:'$'});
        drawLineChart('live_drawdown_chart', {'live': d.drawdown_series_20s||[]}, 'drawdown', {'live':'#f97316'});
        drawStackChart('live_stack_chart', d.stack_series_20s||[], 'cash', 'position');
        renderRows('live_open_positions_body', d.open_positions||[], ['market_ticker','qty_contracts','entry_price','mark_bid','unrealized_pnl','opened_at_utc']);
        renderRows('live_orders_body', d.recent_orders||[], ['created_at_utc','market_ticker','action','side','qty_contracts','limit_price_dollars','status','kalshi_order_id','client_order_id']);
        renderRows('live_trades_body', d.recent_trades||[], ['opened_at_utc','closed_at_utc','market_ticker','qty_contracts','entry_price','exit_price','pnl','status']);
        const sc=document.getElementById('live_score');
        if(sc){
          const s=d.scorecard||{};
          const wr=(s.win_rate==null?'N/A':`${(s.win_rate*100).toFixed(1)}%`);
          sc.innerHTML=`<div class='card'><div class='k'>risk state</div><div class='v' style='font-size:18px'>${d.risk_state||'N/A'}</div></div>` +
                       `<div class='card'><div class='k'>cash source</div><div class='v' style='font-size:16px'>${d.cash_source||'unknown'}</div></div>` +
                       `<div class='card'><div class='k'>equity</div><div class='v' style='font-size:18px'>$${Number(s.equity||d.settings.starting_capital||0).toFixed(2)}</div></div>` +
                       `<div class='card'><div class='k'>total pnl</div><div class='v' style='font-size:18px'>$${Number(s.total_pnl||0).toFixed(2)}</div></div>` +
                       `<div class='card'><div class='k'>closed/win</div><div class='v' style='font-size:16px'>${Number(s.closed_trades||0)} / ${wr}</div></div>`;
        }
        const cfg=d.settings||{};
        const bind=(id,v)=>{const el=document.getElementById(id); if(el) el.value=String(v);};
        bind('ls_live_enabled', cfg.live_enabled ? '1' : '0');
        bind('ls_signal_threshold', cfg.signal_threshold);
        bind('ls_edge_threshold', cfg.edge_threshold);
        bind('ls_max_trade_cost', cfg.max_trade_cost);
        bind('ls_max_open_notional', cfg.max_open_notional);
        bind('ls_max_concurrent_positions', cfg.max_concurrent_positions);
        bind('ls_max_daily_loss', cfg.max_daily_loss);
        bind('ls_max_total_drawdown', cfg.max_total_drawdown);
      }catch(e){}
    }
    async function saveLiveSettings(){
      const root=document.getElementById('live-root');
      if(!root) return;
      const payload={
        live_enabled: document.getElementById('ls_live_enabled').value === '1',
        signal_threshold: Number(document.getElementById('ls_signal_threshold').value),
        edge_threshold: Number(document.getElementById('ls_edge_threshold').value),
        max_trade_cost: Number(document.getElementById('ls_max_trade_cost').value),
        max_open_notional: Number(document.getElementById('ls_max_open_notional').value),
        max_concurrent_positions: Number(document.getElementById('ls_max_concurrent_positions').value),
        max_daily_loss: Number(document.getElementById('ls_max_daily_loss').value),
        max_total_drawdown: Number(document.getElementById('ls_max_total_drawdown').value)
      };
      try{
        const q=new URLSearchParams({
          live_enabled: payload.live_enabled ? '1':'0',
          signal_threshold: String(payload.signal_threshold),
          edge_threshold: String(payload.edge_threshold),
          max_trade_cost: String(payload.max_trade_cost),
          max_open_notional: String(payload.max_open_notional),
          max_concurrent_positions: String(payload.max_concurrent_positions),
          max_daily_loss: String(payload.max_daily_loss),
          max_total_drawdown: String(payload.max_total_drawdown)
        });
        const lp = livePass();
        if(lp) q.set('live_password', lp);
        await fetch('/live_settings_update?' + q.toString(), {cache:'no-store'});
      }catch(e){}
      refreshLiveMetrics();
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
          latest.textContent = `last forward: ${d.latest_forward.snapshot_time_utc} | ${d.latest_forward.market_ticker} | ${d.latest_forward.status}`;
        }
        if(d.forward_health){
          const fh = d.forward_health;
          const bind = (id,val) => { const el=document.getElementById(id); if(el) el.textContent=val; };
          bind('fh_rows_total', Number(fh.rows_total).toLocaleString());
          bind('fh_rows_real', Number(fh.rows_real).toLocaleString());
          bind('fh_na_rate', `${fh.na_rate_pct}%`);
          bind('fh_gaps', Number(fh.gaps_missing_slots).toLocaleString());
          bind('fh_misaligned', Number(fh.misaligned_rows).toLocaleString());
          bind('fh_last', fh.last_snapshot_time || 'N/A');
        }
      }catch(e){}
    }
    function fmt(x, d){
      if(x===null || x===undefined || x==='') return '';
      const n=Number(x); if(Number.isNaN(n)) return String(x);
      return n.toFixed(d);
    }
    async function refreshModelLab(){
      const root=document.getElementById('model-lab-root');
      if(!root) return;
      try{
        const r=await fetch('/model_lab_metrics',{cache:'no-store'});
        if(!r.ok) return;
        const d=await r.json();
        const seg=(document.getElementById('lab_seg')||{}).value||'all';
        const sortKey=(document.getElementById('lab_sort')||{}).value||'total_pnl';
        const rows=(d.rows||[]).filter(x=>seg==='all' ? true : x.segment===seg);
        rows.sort((a,b)=>Number(b[sortKey]||0)-Number(a[sortKey]||0));
        const top = rows.slice(0, 240).map(x=>({
          ...x,
          win_rate: x.win_rate==null ? '' : fmt(100*x.win_rate,1)+'%',
          trade_rate: fmt(100*(x.trade_rate||0),2)+'%',
          total_pnl: fmt(x.total_pnl,2),
          avg_pnl: fmt(x.avg_pnl,3),
          brier: x.brier==null?'':fmt(x.brier,4),
          logloss: x.logloss==null?'':fmt(x.logloss,4),
          max_drawdown: fmt(x.max_drawdown,2),
          sharpe_like: x.sharpe_like==null?'':fmt(x.sharpe_like,3),
        }));
        renderRows('lab_rows', top, ['segment','variant_id','model_family','horizon_min','pred_threshold','edge_threshold','n_samples','n_trades','trade_rate','win_rate','total_pnl','avg_pnl','brier','logloss','max_drawdown','sharpe_like']);
        const meta=document.getElementById('lab_meta');
        if(meta){
          const rr=d.latest_run||{};
          meta.textContent = rr.run_time_utc ? `run ${rr.run_id} | ${rr.run_time_utc} UTC | samples ${rr.sample_rows}` : 'no model-lab run yet';
        }
        const champ=document.getElementById('lab_champion');
        if(champ){
          const c=d.champion||{};
          if(c.variant_id){
            const wr=(c.win_rate==null?'N/A':(100*Number(c.win_rate)).toFixed(1)+'%');
            champ.innerHTML = `<div class='card'><div class='k'>Champion</div><div class='v' style='font-size:18px'>${c.variant_id}</div><div class='muted'>${c.segment} | h=${c.horizon_min} | pnl ${fmt(c.total_pnl,2)} | win ${wr} | obj ${fmt(c.objective,3)}</div></div>`;
          }else{
            champ.innerHTML = `<div class='card'><div class='k'>Champion</div><div class='v' style='font-size:16px'>pending</div></div>`;
          }
        }
      }catch(e){}
    }
    document.addEventListener('change', (e)=>{
      if(e.target && (e.target.id==='lab_seg' || e.target.id==='lab_sort')){ refreshModelLab(); }
    });
    setInterval(refreshHealth, 10000);
    setInterval(refreshSimMetrics, 10000);
    setInterval(refreshLiveMetrics, 10000);
    setInterval(refreshModelLab, 15000);
    window.addEventListener('load', ()=>{ refreshHealth(); refreshSimMetrics(); refreshLiveMetrics(); refreshModelLab(); });
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
                "<a class='pill' href='/?tab=model-lab'>model lab</a>"
                "<a class='pill' href='/?tab=live-trading'>live trading</a>"
                "</div></div>"
            )

            if tab == "simulated-trading":
                body = f"""
                <div class="top">
                  <div>
                    <h1 class="title">Simulated Trading</h1>
                    <div class="sub">Historical backtest + live-forward simulation with regime-aware diagnostics.</div>
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
                <div id="sim_model_rows" style="margin-top:12px"></div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Portfolio Equity (historical + live)</a></div></div>
                  <div id="sim_legend" class="toolbar" style="margin-bottom:8px"></div>
                  <canvas id="equity_chart" width="1120" height="260" style="width:100%;height:260px"></canvas>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Cash vs Position Value (20s)</a></div></div>
                  <canvas id="stack_chart" width="1120" height="220" style="width:100%;height:220px"></canvas>
                </div>
                <div class="panel" style="margin-top:12px">
                  <div class="bar"><div class="nav"><a href="/?tab=simulated-trading">Drawdown (20s)</a></div></div>
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
                  <div class="bar">
                    <div class="nav"><a href="/?tab=simulated-trading">Model Lab Leaderboard (hourly retrain/scan)</a></div>
                    <div id="model_lab_meta" class="muted">model lab run pending</div>
                  </div>
                  <div style="overflow:auto;max-height:32vh">
                    <table>
                      <thead><tr><th>segment</th><th>variant</th><th>family</th><th>horizon</th><th>p_thr</th><th>e_thr</th><th>trades</th><th>total pnl</th><th>win rate</th><th>max dd</th><th>brier</th><th>logloss</th><th>sharpe*</th></tr></thead>
                      <tbody id="model_lab_body"></tbody>
                    </table>
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
                    <div class="sub">RF-only live execution with adjustable risk caps and signal thresholds.</div>
                  </div>
                  <div class="sub">Auth user: <b>{html.escape(AUTH_USER)}</b></div>
                </div>
                {tabs}
                <div id="live-root">
                <div class="panel">
                  <div class="bar"><div class="nav"><a href="/?tab=live-trading">Live Settings</a></div><div><a class="pill" href="javascript:void(0)" onclick="saveLiveSettings()">Save Settings</a></div></div>
                  <div class="grid4">
                    <div class="card"><div class="k">Live Enabled</div><div class="v" style="font-size:16px"><select id="ls_live_enabled"><option value="0">OFF</option><option value="1">ON</option></select></div></div>
                    <div class="card"><div class="k">Signal Threshold</div><div class="v" style="font-size:16px"><input id="ls_signal_threshold" type="number" step="0.01" min="0" max="1" /></div></div>
                    <div class="card"><div class="k">Edge Threshold</div><div class="v" style="font-size:16px"><input id="ls_edge_threshold" type="number" step="0.001" min="0" max="1" /></div></div>
                    <div class="card"><div class="k">Max Trade Cost $</div><div class="v" style="font-size:16px"><input id="ls_max_trade_cost" type="number" step="0.1" min="0" /></div></div>
                  </div>
                  <div class="grid4">
                    <div class="card"><div class="k">Max Open Notional $</div><div class="v" style="font-size:16px"><input id="ls_max_open_notional" type="number" step="0.1" min="0" /></div></div>
                    <div class="card"><div class="k">Max Concurrent Positions</div><div class="v" style="font-size:16px"><input id="ls_max_concurrent_positions" type="number" step="1" min="1" /></div></div>
                    <div class="card"><div class="k">Max Daily Loss $</div><div class="v" style="font-size:16px"><input id="ls_max_daily_loss" type="number" step="0.1" min="0" /></div></div>
                    <div class="card"><div class="k">Max Total Drawdown $</div><div class="v" style="font-size:16px"><input id="ls_max_total_drawdown" type="number" step="0.1" min="0" /></div></div>
                  </div>
                </div>
                <div id="live_score" class="grid4" style="margin-top:12px"></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Live Equity (20s)</div></div><canvas id="live_equity_chart" width="1120" height="250" style="width:100%;height:250px"></canvas></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Live Cash vs Position Value (20s)</div></div><canvas id="live_stack_chart" width="1120" height="220" style="width:100%;height:220px"></canvas></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Live Drawdown (20s)</div></div><canvas id="live_drawdown_chart" width="1120" height="180" style="width:100%;height:180px"></canvas></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Open Positions</div></div><div style="overflow:auto;max-height:24vh"><table><thead><tr><th>ticker</th><th>qty</th><th>entry</th><th>mark bid</th><th>unrealized</th><th>opened</th></tr></thead><tbody id="live_open_positions_body"></tbody></table></div></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Recent Orders</div></div><div style="overflow:auto;max-height:24vh"><table><thead><tr><th>time</th><th>ticker</th><th>action</th><th>side</th><th>qty</th><th>limit</th><th>status</th><th>order id</th><th>client id</th></tr></thead><tbody id="live_orders_body"></tbody></table></div></div>
                <div class="panel" style="margin-top:12px"><div class="bar"><div class="nav">Recent Trades</div></div><div style="overflow:auto;max-height:24vh"><table><thead><tr><th>opened</th><th>closed</th><th>ticker</th><th>qty</th><th>entry</th><th>exit</th><th>pnl</th><th>status</th></tr></thead><tbody id="live_trades_body"></tbody></table></div></div>
                </div>
                """
                self._send(render_page("Live Trading", body))
                return

            if tab == "model-lab":
                body = f"""
                <div class="top">
                  <div>
                    <h1 class="title">Model Lab</h1>
                    <div class="sub">Hourly walk-forward experiment engine across model families, horizons, and thresholds.</div>
                  </div>
                  <div class="sub">Auth user: <b>{html.escape(AUTH_USER)}</b></div>
                </div>
                {tabs}
                <div id="model-lab-root">
                  <div id="lab_champion" class="grid4"></div>
                  <div class="panel" style="margin-top:12px">
                    <div class="bar">
                      <div id="lab_meta" class="muted">loading...</div>
                      <div class="toolbar">
                        <label class="muted">segment</label>
                        <select id="lab_seg">
                          <option value="all">all</option>
                          <option value="live_forward">live_forward</option>
                          <option value="out_of_sample">out_of_sample</option>
                          <option value="in_sample">in_sample</option>
                        </select>
                        <label class="muted">sort</label>
                        <select id="lab_sort">
                          <option value="total_pnl">total_pnl</option>
                          <option value="sharpe_like">sharpe_like</option>
                          <option value="win_rate">win_rate</option>
                          <option value="n_trades">n_trades</option>
                          <option value="brier">brier</option>
                        </select>
                      </div>
                    </div>
                    <div style="overflow:auto;max-height:70vh">
                      <table>
                        <thead><tr><th>segment</th><th>variant</th><th>family</th><th>horizon</th><th>p_thr</th><th>e_thr</th><th>samples</th><th>trades</th><th>trade rate</th><th>win</th><th>total pnl</th><th>avg pnl</th><th>brier</th><th>logloss</th><th>max dd</th><th>sharpe*</th></tr></thead>
                        <tbody id="lab_rows"></tbody>
                      </table>
                    </div>
                  </div>
                </div>
                """
                self._send(render_page("Model Lab", body))
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
            data = sim_metrics()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if parsed.path == "/model_lab_metrics":
            data = model_lab_metrics()
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
            data = live_metrics()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if parsed.path == "/live_settings_update":
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            qs = parse_qs(parsed.query)
            def _g(name, default=None):
                return qs.get(name, [default])[0]
            patch = {}
            if _g("live_enabled") is not None:
                patch["live_enabled"] = _g("live_enabled") in ("1", "true", "True", "yes", "on")
            for k in ("signal_threshold", "edge_threshold", "max_trade_cost", "max_open_notional", "max_daily_loss", "max_total_drawdown"):
                v = _g(k)
                if v is not None:
                    try:
                        patch[k] = float(v)
                    except Exception:
                        pass
            v = _g("max_concurrent_positions")
            if v is not None:
                try:
                    patch["max_concurrent_positions"] = int(float(v))
                except Exception:
                    pass
            cfg = live_settings_update(patch)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "settings": cfg}).encode("utf-8"))
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
            if not self._live_authorized():
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                cfg = live_settings_update(payload)
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
        self._send("not found", 404)


def main():
    server = HTTPServer((HOST, PORT), Handler)
    print(f"Dashboard listening on {HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
