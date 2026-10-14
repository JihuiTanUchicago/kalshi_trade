"""Kalshi market-universe catalog (Phase 1 of the all-markets collector; see PLAN.md).

Pulls *all* Kalshi markets (not just the two BTC series) into `markets`, then
aggregates a searchable `kalshi_series` catalog — the stable logical "contracts"
users search by name. Markets renew; the series is persistent.

Run:  python -m data_pipeline.catalog_collector            # one full refresh
      python -m data_pipeline.catalog_collector --loop     # refresh every N minutes
"""
from __future__ import annotations

import sys
import time
from typing import Dict, List, Optional

from data_pipeline.common import api_get, get_db_conn, utc_now
from data_pipeline.forward_collector import insert_market_upserts

REFRESH_MINUTES = 30
OPEN_STATES = ("active", "open", "initialized")


def _series_of(m: Dict) -> Optional[str]:
    # Kalshi's /markets payload omits series_ticker; it's the event_ticker prefix
    # before the first '-' (series tickers themselves never contain a '-').
    s = m.get("series_ticker")
    if s:
        return s
    ev = m.get("event_ticker") or m.get("ticker") or ""
    return ev.split("-", 1)[0] or None


def fetch_all_markets(status: Optional[str] = "open", page_limit: int = 1000, max_pages: int = 200) -> List[Dict]:
    """Paginate GET /markets with the cursor until exhausted. Defaults to open
    markets (the current tradeable universe) to avoid drowning in settled history."""
    out: List[Dict] = []
    cursor: Optional[str] = None
    for _ in range(max_pages):
        params: Dict[str, object] = {"limit": page_limit}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        data = api_get("/markets", params)
        batch = data.get("markets") or []
        for m in batch:
            m["series_ticker"] = _series_of(m)
        out.extend(batch)
        cursor = data.get("cursor")
        if not cursor or not batch:
            break
    return out


def refresh_series(cur) -> int:
    """Rebuild the series catalog from whatever is in `markets` right now."""
    now = utc_now().replace(tzinfo=None)
    open_list = ",".join("'%s'" % s for s in OPEN_STATES)
    cur.execute(
        """INSERT INTO kalshi_series (series_ticker, title, category, open_markets, total_markets, updated_at)
           SELECT m.series_ticker,
                  SUBSTRING(MAX(m.title), 1, 255) AS title,
                  NULL AS category,
                  SUM(m.status IN (%s)) AS open_markets,
                  COUNT(*) AS total_markets,
                  %%s
           FROM markets m WHERE m.series_ticker IS NOT NULL AND m.series_ticker <> ''
           GROUP BY m.series_ticker
           ON DUPLICATE KEY UPDATE title=VALUES(title), open_markets=VALUES(open_markets),
             total_markets=VALUES(total_markets), updated_at=VALUES(updated_at)""" % open_list,
        (now,),
    )
    cur.execute("SELECT COUNT(*) AS n FROM kalshi_series")
    row = cur.fetchone()
    return int(row["n"] if isinstance(row, dict) else row[0])


PAGE_SLEEP = float(os.getenv("CATALOG_PAGE_SLEEP", "0.4"))  # gentle on a shared box/micro DB


def refresh_once(status: Optional[str] = "open") -> Dict[str, int]:
    """Stream the catalog: fetch one page, upsert it, sleep, repeat — so memory and
    DB load stay flat even across thousands of markets (never loads them all at once)."""
    conn = get_db_conn()
    total = n_open = 0
    cursor: Optional[str] = None
    try:
        cur = conn.cursor()
        for _ in range(200):
            params: Dict[str, object] = {"limit": 1000}
            if status:
                params["status"] = status
            if cursor:
                params["cursor"] = cursor
            data = api_get("/markets", params)
            batch = data.get("markets") or []
            for m in batch:
                m["series_ticker"] = _series_of(m)
                n_open += 1 if m.get("status") in OPEN_STATES else 0
            insert_market_upserts(cur, batch)
            conn.commit()
            total += len(batch)
            cursor = data.get("cursor")
            if not cursor or not batch:
                break
            time.sleep(PAGE_SLEEP)  # throttle: spread the load, don't starve serving
        n_series = refresh_series(cur)
        conn.commit()
        print("[catalog] markets=%d (open=%d) series=%d" % (total, n_open, n_series), flush=True)
        return {"markets": total, "open": n_open, "series": n_series}
    finally:
        conn.close()


def backfill_series(conn) -> None:
    """One-time: fill series_ticker on legacy rows. Cheap after the first run."""
    cur = conn.cursor()
    cur.execute("UPDATE markets SET series_ticker=SUBSTRING_INDEX(event_ticker,'-',1) "
                "WHERE (series_ticker IS NULL OR series_ticker='') AND event_ticker IS NOT NULL")
    conn.commit()


def main() -> None:
    loop = "--loop" in sys.argv
    while True:
        try:
            refresh_once()
        except Exception as e:  # keep the loop alive
            print("[catalog] refresh failed: %r" % e, flush=True)
        if not loop:
            return
        time.sleep(REFRESH_MINUTES * 60)


if __name__ == "__main__":
    main()
