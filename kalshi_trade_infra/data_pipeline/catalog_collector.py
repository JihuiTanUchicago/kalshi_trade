"""Kalshi market-universe catalog (Phase 1 of the all-markets collector; see PLAN.md).

Pulls *all* Kalshi markets (not just the two BTC series) into `markets`, then
aggregates a searchable `kalshi_series` catalog — the stable logical "contracts"
users search by name. Markets renew; the series is persistent.

Run:  python -m data_pipeline.catalog_collector            # one full refresh
      python -m data_pipeline.catalog_collector --loop     # refresh every N minutes
"""
from __future__ import annotations

import os
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


def refresh_series(cur, seen: Dict[str, Dict[str, object]], complete: bool) -> int:
    """Upsert the series catalog from this refresh's open markets.

    `seen` maps series_ticker -> {"open": n, "title": str}, counted from the /markets pages just
    fetched, so open_markets is Kalshi's live count rather than stale `markets.status` values (a
    row's status only changes when the market is re-fetched). total_markets is an indexed count
    of just these series. The old version GROUP BY'd all of `markets` (11M+ rows, 99% parlays)
    and timed out. Series not seen drop to open_markets=0, but only after a complete fetch, so a
    failed page never empties the catalog."""
    # Whole seconds: DATETIME rounds fractions, so a fractional `now` could make this run's own
    # rows compare as older than `now` and get zeroed below.
    now = utc_now().replace(tzinfo=None, microsecond=0)
    tickers = sorted(seen)
    totals: Dict[str, int] = {}
    for i in range(0, len(tickers), 500):
        chunk = tickers[i:i + 500]
        cur.execute(
            "SELECT series_ticker, COUNT(*) AS n FROM markets WHERE series_ticker IN (%s) GROUP BY series_ticker"
            % ",".join(["%s"] * len(chunk)),
            tuple(chunk),
        )
        for r in cur.fetchall():
            t, n = (r["series_ticker"], r["n"]) if isinstance(r, dict) else (r[0], r[1])
            totals[t] = int(n)
    rows = [
        (t, str(seen[t].get("title") or "")[:255], int(seen[t]["open"]), max(totals.get(t, 0), int(seen[t]["open"])), now)
        for t in tickers
    ]
    if rows:
        cur.executemany(
            """INSERT INTO kalshi_series (series_ticker, title, category, open_markets, total_markets, updated_at)
               VALUES (%s, %s, NULL, %s, %s, %s)
               ON DUPLICATE KEY UPDATE title=COALESCE(NULLIF(title, ''), VALUES(title)), open_markets=VALUES(open_markets),
                 total_markets=VALUES(total_markets), updated_at=VALUES(updated_at)""",
            rows,
        )
    if complete:
        cur.execute("UPDATE kalshi_series SET open_markets=0, updated_at=%s WHERE updated_at < %s AND open_markets <> 0",
                    (now, now))
    cur.execute("SELECT COUNT(*) AS n FROM kalshi_series")
    row = cur.fetchone()
    return int(row["n"] if isinstance(row, dict) else row[0])


PAGE_SLEEP = float(os.getenv("CATALOG_PAGE_SLEEP", "0.4"))  # gentle on a shared box/micro DB
# Kalshi's open universe is ~99.5% multivariate parlays (KXMVECROSSCATEGORY*, ~8.8M rows by
# 2026-10-24), which app/markets never trades and which made `markets` 190GB. With 200 pages of
# 1000 the scan also hit its page cap inside the parlays, before reaching most real series.
# "exclude" skips them at the API; set CATALOG_MVE_FILTER="" to fetch everything again.
MVE_FILTER = os.getenv("CATALOG_MVE_FILTER", "exclude")
MAX_PAGES = 200


def refresh_series_meta(cur) -> int:
    """Enrich kalshi_series with Kalshi's own `category`, `frequency` and series `title` for every
    series we track. The title matters: refresh_series only has a market's title ("Portland wins",
    "Will the maximum temperature be >77° on Oct 25, 2026?"), which app/markets would otherwise
    show as the series label.

    Kalshi's /markets payload carries neither, but the bulk /series endpoint returns both for all
    series in ONE call. app/markets.load_catalog_markets filters on these two columns to generate
    the deployable outcome-settled universe, so without this pass they stay NULL and generation
    yields nothing (safe: the curated 19 still work). Returns the number of rows updated."""
    try:
        data = api_get("/series")
    except Exception as e:  # a meta-fetch hiccup must never stop the catalog loop
        print("[catalog] series-meta fetch failed: %r" % e, flush=True)
        return 0
    meta = {}
    for s in data.get("series") or []:
        t = s.get("ticker")
        if t:
            meta[t] = ((s.get("category") or None), (s.get("frequency") or None),
                       str(s.get("title") or "").strip()[:255])
    if not meta:
        return 0
    cur.execute("SELECT series_ticker FROM kalshi_series")
    rows = [
        meta[r["series_ticker"]] + (r["series_ticker"],)
        for r in cur.fetchall()
        if r["series_ticker"] in meta
    ]
    if rows:
        cur.executemany(
            "UPDATE kalshi_series SET category=%s, frequency=%s, title=COALESCE(NULLIF(%s, ''), title) "
            "WHERE series_ticker=%s", rows
        )
    return len(rows)


def refresh_once(status: Optional[str] = "open") -> Dict[str, int]:
    """Stream the catalog: fetch one page, upsert it, sleep, repeat — so memory and
    DB load stay flat even across thousands of markets (never loads them all at once)."""
    conn = get_db_conn()
    total = n_open = 0
    cursor: Optional[str] = None
    try:
        cur = conn.cursor()
        seen: Dict[str, Dict[str, object]] = {}
        complete = False
        for _ in range(MAX_PAGES):
            params: Dict[str, object] = {"limit": 1000}
            if status:
                params["status"] = status
            if MVE_FILTER:
                params["mve_filter"] = MVE_FILTER
            if cursor:
                params["cursor"] = cursor
            data = api_get("/markets", params)
            batch = data.get("markets") or []
            for m in batch:
                m["series_ticker"] = _series_of(m)
                is_open = m.get("status") in OPEN_STATES
                n_open += 1 if is_open else 0
                s = m["series_ticker"]
                if s:
                    entry = seen.setdefault(s, {"open": 0, "title": m.get("title")})
                    entry["open"] = int(entry["open"]) + (1 if is_open else 0)
            insert_market_upserts(cur, batch)
            conn.commit()
            total += len(batch)
            cursor = data.get("cursor")
            if not cursor or not batch:
                complete = True
                break
            time.sleep(PAGE_SLEEP)  # throttle: spread the load, don't starve serving
        n_series = refresh_series(cur, seen, complete=complete and status == "open")
        conn.commit()
        n_meta = refresh_series_meta(cur)  # fill category + frequency (drives catalog-market generation)
        conn.commit()
        print("[catalog] markets=%d (open=%d) series=%d meta=%d" % (total, n_open, n_series, n_meta), flush=True)
        return {"markets": total, "open": n_open, "series": n_series, "meta": n_meta}
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
