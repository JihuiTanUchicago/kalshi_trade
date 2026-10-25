"""Where Polymarket quotes come from: the live heartbeat snapshot, and S3 for research.

  live      collector_state tick_recorder_polymarket: the recorder's newest priced snapshot (one
            row per market: data_pipeline.polymarket.MARKET_FIELDS + bid, ask, sizes, ts)
  research  the history day files (one-minute prices per market, back before the recorder) and,
            for days without one yet, the hourly archive (polymarket_markets + polymarket_top)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from data_pipeline import polymarket as pmk

RESEARCH_STEP_S = 60          # the archive is thinned to one poll a minute, the history's fidelity


def latest_snapshot(cur, as_of_ts: int) -> Optional[List[Dict]]:
    """The recorder's newest snapshot rows priced at or before as_of_ts, or None."""
    cur.execute("SELECT state_value FROM collector_state WHERE state_key=%s LIMIT 1", (pmk.HEARTBEAT_KEY,))
    row = cur.fetchone() or {}
    try:
        state = json.loads(row.get("state_value") or "{}")
    except (TypeError, ValueError):
        return None
    rows = [r for r in (state.get("snapshot") or []) if int(r.get("ts") or 0) <= int(as_of_ts)]
    return rows or None


def _day_rows(store, day: datetime) -> List[Dict]:
    import pyarrow.parquet as pq
    p = store._fetch(pmk.day_key(day))
    return pq.read_table(p).to_pylist() if p else []


def _thin(quotes: Iterable[pmk.PmQuote], step_s: int) -> List[pmk.PmQuote]:
    """The first poll of each step_s bucket (a poll is every market priced at one ts)."""
    keep: Dict[int, int] = {}
    qs = list(quotes)
    for q in qs:
        b = q.ts // step_s
        keep[b] = min(keep.get(b, q.ts), q.ts)
    return [q for q in qs if keep[q.ts // step_s] == q.ts]


def load_quotes(since: datetime, until: Optional[datetime] = None, store=None, kinds=pmk.PRICED_KINDS,
                step_s: int = RESEARCH_STEP_S) -> List[pmk.PmQuote]:
    """Stored Polymarket quotes from ``since`` to ``until`` (default now) of markets of ``kinds``.
    Up/down quotes before their window opened are dropped (no Kalshi twin is listed then)."""
    from data_pipeline.tick_store import TickStore
    store = store or TickStore()
    since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    until = until or datetime.now(timezone.utc)
    lo_ts, hi_ts = int(since.timestamp()), int(until.timestamp())
    day = since.replace(hour=0, minute=0, second=0, microsecond=0)
    out: List[pmk.PmQuote] = []
    while day < until:
        rows = _day_rows(store, day)
        if rows:
            qs = pmk.quotes_from_history(r for r in rows if r.get("kind") in kinds)
        else:
            end = min(day + timedelta(days=1), until)
            tops = store.read("polymarket_top", day, end)
            mk = store.read("polymarket_markets", day - timedelta(hours=1), end)
            qs = []
            if tops is not None and tops.num_rows and mk is not None and mk.num_rows:
                qs = _thin(pmk.quotes_from_archive(mk.to_pylist(), tops.to_pylist()), step_s)
        for q in qs:
            m = q.market
            if m.kind not in kinds or not (lo_ts <= q.ts <= hi_ts):
                continue
            if m.kind == "updown" and m.start_ts is not None and q.ts < m.start_ts:
                continue
            out.append(q)
        day += timedelta(days=1)
    return out
