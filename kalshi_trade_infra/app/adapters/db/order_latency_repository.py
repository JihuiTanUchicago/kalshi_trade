"""Execution latency: one row per order attempt, and the percentile stats the ops page reads."""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional

from app.adapters.db.sql import now_utc


def insert_order_latency(
    cur, mode: str, ticker: str, action: str, side: str, qty: int, fill_qty: int,
    encode_sign_ms: Optional[float], roundtrip_ms: Optional[float], total_ms: float,
    http_status: Optional[int], outcome: str,
) -> None:
    """One row per real exchange POST (live & demo). Written off the send path by the background
    recorder — no secrets, no order body. Pure observability."""
    cur.execute(
        """INSERT INTO app_order_latency
             (mode, ticker, action, side, qty, fill_qty, encode_sign_ms, roundtrip_ms, total_ms,
              http_status, outcome, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (mode, ticker, action, side, int(qty), int(fill_qty), encode_sign_ms, roundtrip_ms,
         float(total_ms), http_status, outcome, now_utc()),
    )


def _pct(values: List[float], q: float) -> Optional[float]:
    """Nearest-rank percentile of a list (q in 0..1). None for an empty list. Stdlib only —
    ponytail: the window holds tens/hundreds of orders, no numpy needed."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return round(s[k], 2)


def order_latency_stats(cur, window_seconds: int = 3600, mode: Optional[str] = None) -> Dict:
    """Lag + error observability over a trailing window: p50/p95/p99 of round-trip and total
    latency, the encode+sign cost, error/fill rates by outcome, and feed/mark staleness (from the
    marks the engine stamps from the same live book orders are priced against). All read-only."""
    cutoff = now_utc() - timedelta(seconds=int(window_seconds))
    where = "created_at >= %s" + ("" if mode is None else " AND mode=%s")
    args = (cutoff,) if mode is None else (cutoff, mode)
    cur.execute(
        "SELECT outcome, roundtrip_ms, total_ms, encode_sign_ms FROM app_order_latency WHERE " + where,
        args,
    )
    rows = cur.fetchall()
    rt = [float(r["roundtrip_ms"]) for r in rows if r["roundtrip_ms"] is not None]
    tot = [float(r["total_ms"]) for r in rows if r["total_ms"] is not None]
    sign = [float(r["encode_sign_ms"]) for r in rows if r["encode_sign_ms"] is not None]
    by_outcome: Dict[str, int] = {}
    for r in rows:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    n = len(rows)
    errors = by_outcome.get("error", 0)
    filled = by_outcome.get("filled", 0) + by_outcome.get("partial", 0)

    # Feed/mark staleness: how old are the live marks the engine stamps each tick (same book the
    # kernel prices orders from), so a lagging feed shows up here as rising mark age.
    cur.execute(
        "SELECT TIMESTAMPDIFF(SECOND, mark_ts, UTC_TIMESTAMP()) AS age FROM app_positions "
        "WHERE status='open' AND mark_ts IS NOT NULL"
    )
    ages = [float(r["age"]) for r in cur.fetchall() if r["age"] is not None]

    return {
        "window_seconds": int(window_seconds),
        "mode": mode or "all",
        "orders": {
            "count": n,
            "errors": errors,
            "error_rate": round(errors / n, 4) if n else 0.0,
            "fill_rate": round(filled / n, 4) if n else 0.0,
            "by_outcome": by_outcome,
        },
        "roundtrip_ms": {"p50": _pct(rt, 0.50), "p95": _pct(rt, 0.95), "p99": _pct(rt, 0.99),
                         "max": round(max(rt), 2) if rt else None},
        "total_ms": {"p50": _pct(tot, 0.50), "p95": _pct(tot, 0.95), "p99": _pct(tot, 0.99)},
        "encode_sign_ms": {"p50": _pct(sign, 0.50), "p95": _pct(sign, 0.95)},
        "feed_staleness_s": {"p50": _pct(ages, 0.50), "p95": _pct(ages, 0.95),
                             "max": round(max(ages), 2) if ages else None, "open_marks": len(ages)},
    }
