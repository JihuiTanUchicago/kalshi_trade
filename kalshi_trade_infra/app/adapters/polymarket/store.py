"""Where Polymarket quotes come from: the live heartbeat snapshot, and S3 for research.

  live      collector_state tick_recorder_polymarket: the recorder's newest priced snapshot (one
            row per market: data_pipeline.polymarket.MARKET_FIELDS + bid, ask, sizes, ts)
  research  the history day files (one-minute prices per market, back before the recorder) and,
            for days without one yet, the hourly archive (polymarket_markets + polymarket_top)
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from data_pipeline import polymarket as pmk

RESEARCH_STEP_S = 60          # the archive is thinned to one poll a minute, the history's fidelity
FETCH_WORKERS = 8             # day files download in parallel (a 60-day read was ~59 serial GETs)


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


def _day_quotes(path: Optional[str], kinds: Sequence[str], lo_ts: int, hi_ts: int) -> Optional[List[pmk.PmQuote]]:
    """quotes_from_history of one day file's rows of ``kinds`` stamped within [lo_ts, hi_ts] (minus
    up/down quotes before their window), or None when there is no file or it is empty. Filtered in
    Arrow and built column-wise with one PmMarket per market: row dicts cost ~0.3s a day."""
    if not path:
        return None
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    tb = pq.read_table(path)
    if not tb.num_rows:
        return None
    t = pc.cast(tb.column("t"), pa.int64())
    ts = pc.multiply(pc.divide(pc.add(t, 59), 60), 60)      # end of its minute, as quotes_from_history
    keep = pc.and_(pc.is_in(tb.column("kind"), value_set=pa.array(list(kinds), pa.string())),
                   pc.and_(pc.greater_equal(ts, lo_ts), pc.less_equal(ts, hi_ts)))
    # up/down quotes from before the window opened have no Kalshi twin (load_quotes drops them)
    early = pc.and_(pc.equal(tb.column("kind"), "updown"), pc.less(ts, tb.column("start_ts")))
    keep = pc.and_(keep, pc.invert(pc.fill_null(early, False)))
    tb = tb.append_column("ts", ts).filter(keep)
    cols = {c: tb.column(c).to_pylist() for c in ("market_id", "slug", "kind", "strike_lo", "strike_hi",
                                                   "start_ts", "end_ts", "p", "ts")}
    markets: Dict[str, pmk.PmMarket] = {}
    out = []
    for i, mid in enumerate(cols["market_id"]):
        m = markets.get(mid)
        if m is None:
            m = markets[mid] = pmk.PmMarket(str(mid), str(cols["slug"][i] or ""), "", "", "", "", "", "Yes",
                                            cols["kind"][i], cols["strike_lo"][i], cols["strike_hi"][i],
                                            cols["start_ts"][i], cols["end_ts"][i])
        p = cols["p"][i]
        out.append(pmk.PmQuote(m, p, p, cols["ts"][i]))
    return out


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
    # Only probe days that have files: the history and archive tables cover a few days of a 90-day
    # window, and every missing hour cost a 404 round trip (prod btc15m loads timed out on it).
    history = store.dates(f"v1/{pmk.DAY_TABLE}/v={pmk.HIST_VERSION}")
    archived = store.dates("v1/polymarket_top")
    days = []
    while day < until:
        days.append(day)
        day += timedelta(days=1)
    wanted = [d for d in days if history is None or f"{d:%Y-%m-%d}" in history]
    if wanted and getattr(store, "local_root", None) is None and hasattr(store, "_client"):
        store._client()          # make the boto3 client once, before the threads share it
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        paths = dict(zip(wanted, ex.map(lambda d: store._fetch(pmk.day_key(d)), wanted)))
    out: List[pmk.PmQuote] = []
    for day in days:
        qs = _day_quotes(paths.get(day), kinds, lo_ts, hi_ts)
        if qs is None and archived is not None and f"{day:%Y-%m-%d}" not in archived:
            continue
        if qs is None:
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
    return out
