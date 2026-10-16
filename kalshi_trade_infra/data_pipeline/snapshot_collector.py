"""Per-scan synchronized market snapshots -> S3/Parquet (Phase 2; see PLAN.md).

Once a minute (aligned to the :00 boundary), snapshot every open market in a FIXED set of series and record
each one's quote (yes/no bid+ask, last, volume, open interest) under a single
`snapshot_minute_utc` -- a true cross-section (every market sampled in the same scan),
which is what cross-contract analysis needs.

Why a FIXED set of SERIES (not "hot markets", not "all open markets"):
  * A dynamic/hot filter would make membership vary scan-to-scan, so each market's time
    series would be ragged and selection-biased (you'd only see a market once it's already
    hot). Fixing membership keeps every market's series continuous and unbiased.
  * Individual markets are ephemeral (a new BTC 15-min market every 15 min; parlays churn),
    so the stable unit is the SERIES. Membership is fixed at the series level; within a
    series, markets come and go and we capture the full live cross-section each scan.
  * Kalshi's raw /markets?status=open is ~99.9% one combinatorial parlay series
    (KXMVECROSSCATEGORY, 386k+ markets) and buries everything real, so a blind scan can't
    even reach the markets we trade. We fetch per series (/markets?series_ticker=X), which
    bypasses the parlay flood and stays fast.

The frozen set lives in data_pipeline/snapshot_series.txt (one series ticker per line) --
committed so "frozen" is explicit and auditable in git. Built from: all Crypto-category
series + the top real series by open-market count (see scripts/build_snapshot_series.py).
Expand it deliberately toward the "all markets" goal. TAU_SNAPSHOT_SERIES (comma list)
overrides the file for ad-hoc runs.

Writes one Snappy-compressed Parquet object per scan, partitioned by date so queries prune:
    s3://<BUCKET>/snapshots_1m/dt=YYYY-MM-DD/minute=HHMM/part.parquet

RDS is untouched by this firehose -- only the lake grows. Runs on the COLLECTOR box.

Run:  python -m data_pipeline.snapshot_collector            # one snapshot now
      python -m data_pipeline.snapshot_collector --loop     # once a minute, aligned to :00
"""
from __future__ import annotations

import gzip
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional

from data_pipeline.common import api_get

BUCKET = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-<ACCOUNT_ID>-us-east-1")
PREFIX = os.getenv("DATALAKE_SNAPSHOT_PREFIX", "snapshots_1m")
WORKERS = int(os.getenv("SNAPSHOT_WORKERS", "6"))             # series fetched concurrently (api_get is thread-safe)
# Global request-rate cap across ALL workers. Parallelism alone 429s Kalshi's public API;
# the cap spaces request *starts* evenly so we go fast without tripping the limit. ~8 rps
# clears 296 series (~340 requests) in ~45s, under the 60s budget. Tune via SNAPSHOT_RPS.
RPS = float(os.getenv("SNAPSHOT_RPS", "5"))
_MIN_INTERVAL = 1.0 / RPS if RPS > 0 else 0.0
_rate_lock = threading.Lock()
_next_slot = [0.0]
MAX_MARKETS = int(os.getenv("SNAPSHOT_MAX_MARKETS", "80000"))  # safety cap per snapshot


def _throttled_get(path: str, params: Dict[str, object]) -> Dict:
    """api_get behind a global token-bucket so concurrent workers never exceed RPS."""
    if _MIN_INTERVAL:
        with _rate_lock:
            slot = max(time.monotonic(), _next_slot[0])
            _next_slot[0] = slot + _MIN_INTERVAL
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)
    return api_get(path, params)
SERIES_FILE = os.getenv("TAU_SNAPSHOT_SERIES_FILE",
                        os.path.join(os.path.dirname(__file__), "snapshot_series.txt"))
_s3 = None


def watchlist() -> List[str]:
    env = os.getenv("TAU_SNAPSHOT_SERIES", "")
    if env.strip():
        return [s.strip() for s in env.split(",") if s.strip()]
    with open(SERIES_FILE) as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]


def _series_of(m: Dict) -> Optional[str]:
    s = m.get("series_ticker")
    if s:
        return s
    ev = m.get("event_ticker") or m.get("ticker") or ""
    return ev.split("-", 1)[0] or None


def _row(m: Dict, series: Optional[str], minute_iso: str) -> Dict:
    return {
        "snapshot_minute_utc": minute_iso,
        "ticker": m.get("ticker"),
        "event_ticker": m.get("event_ticker"),
        "series_ticker": series,
        "title": m.get("title") or "",
        # The per-market distinguisher within an event (e.g. "$92,300 or above"); without it
        # every strike of one event shows an identical title.
        "sub": m.get("yes_sub_title") or m.get("subtitle") or "",
        "yes_bid": m.get("yes_bid_dollars"),
        "yes_ask": m.get("yes_ask_dollars"),
        "no_bid": m.get("no_bid_dollars"),
        "no_ask": m.get("no_ask_dollars"),
        "last": m.get("last_price_dollars"),
        "volume": m.get("volume_fp"),
        "volume_24h": m.get("volume_24h_fp"),
        "open_interest": m.get("open_interest_fp"),
        "status": m.get("status"),
    }


def _collect_series(series: str, minute_iso: str, max_pages: int = 40) -> List[Dict]:
    rows: List[Dict] = []
    cursor: Optional[str] = None
    for _ in range(max_pages):
        params: Dict[str, object] = {"limit": 1000, "status": "open", "series_ticker": series}
        if cursor:
            params["cursor"] = cursor
        data = _throttled_get("/markets", params)
        batch = data.get("markets") or []
        for m in batch:
            rows.append(_row(m, _series_of(m), minute_iso))
        cursor = data.get("cursor")
        if not cursor or not batch:
            break
    return rows


def _write_parquet(rows: List[Dict], minute: datetime) -> str:
    # Import pyarrow/boto3 lazily so the module imports (and self-checks) without them.
    import boto3
    import pyarrow as pa
    import pyarrow.parquet as pq

    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    table = pa.Table.from_pylist(rows)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    key = "%s/dt=%s/minute=%s/part.parquet" % (PREFIX, minute.strftime("%Y-%m-%d"), minute.strftime("%H%M"))
    _s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
    return key


EXPLORE_KEY = os.getenv("DATALAKE_EXPLORE_KEY", "explore/latest.json.gz")
EXPLORE_TOP = int(os.getenv("EXPLORE_TOP", "3000"))   # hottest N markets surfaced to the Explore tab
HOT_TOP = int(os.getenv("EXPLORE_HOT_TOP", "40"))     # hottest N carry a price trace for the sidebar charts
HOT_HIST = int(os.getenv("EXPLORE_HOT_HIST", "45"))   # minutes of rolling mid-price kept per hot market
_hist: Dict[str, List[float]] = {}  # ticker -> rolling yes-mid ($), in-memory; a "right now" sidebar


def _fnum(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _mid(r: Dict) -> Optional[float]:
    bid, ask = _fnum(r.get("yes_bid")), _fnum(r.get("yes_ask"))
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 4)
    last = _fnum(r.get("last"))
    return round(last, 4) if last > 0 else None


def _write_explore_feed(rows: List[Dict], minute: datetime) -> None:
    """Compact, gzipped feed of the hottest markets for the user-facing Explore tab + Hot Markets
    sidebar. One small object the web app reads + caches, so no lake-query or extra deps on the web
    box. The top HOT_TOP markets carry a rolling price trace so the sidebar can draw a real chart."""
    import boto3
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    ranked = sorted(rows, key=lambda r: _fnum(r.get("volume_24h")), reverse=True)[:EXPLORE_TOP]
    # Roll the mid-price history for the current hot set; forget anything that fell out.
    hot_tickers = {r["ticker"] for r in ranked[:HOT_TOP]}
    for ticker in list(_hist):
        if ticker not in hot_tickers:
            del _hist[ticker]
    for r in ranked[:HOT_TOP]:
        m = _mid(r)
        if m is not None:
            buf = _hist.setdefault(r["ticker"], [])
            buf.append(m)
            del buf[:-HOT_HIST]
    markets = []
    for i, r in enumerate(ranked):
        m = {"t": r["ticker"], "s": r["series_ticker"], "ev": r.get("event_ticker"),
             "ti": r.get("title") or "", "su": r.get("sub") or "", "last": r.get("last"), "bid": r.get("yes_bid"),
             "ask": r.get("yes_ask"), "v24": r.get("volume_24h"), "oi": r.get("open_interest"),
             "st": r.get("status")}
        if i < HOT_TOP and _hist.get(r["ticker"]):
            m["h"] = _hist[r["ticker"]]
        markets.append(m)
    feed = {"at": minute.isoformat(), "total": len(rows), "shown": len(ranked), "markets": markets}
    body = gzip.compress(json.dumps(feed, separators=(",", ":")).encode())
    _s3.put_object(Bucket=BUCKET, Key=EXPLORE_KEY, Body=body,
                   ContentType="application/json", ContentEncoding="gzip")


def snapshot_once() -> Dict[str, object]:
    # One timestamp for the whole cross-section: set once, stamped on every row, so
    # all contracts share an aligned snapshot_minute_utc (what cross-contract joins need).
    # Parallel fetch keeps the real observation window tight (~15-25s) under that label.
    minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    minute_iso = minute.isoformat()
    series = watchlist()
    rows: List[Dict] = []

    def _safe(s: str) -> List[Dict]:
        try:
            return _collect_series(s, minute_iso)
        except Exception as e:  # one bad/throttled series must not abort the whole scan
            print("[snapshot] series %s failed: %r" % (s, e), flush=True)
            return []

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for part in ex.map(_safe, series):
            rows.extend(part)
    if len(rows) > MAX_MARKETS:
        rows = rows[:MAX_MARKETS]
        print("[snapshot] truncated to MAX_MARKETS cap %d" % MAX_MARKETS, flush=True)
    if not rows:
        print("[snapshot] %s -> 0 markets across %d series" % (minute_iso, len(series)), flush=True)
        return {"markets": 0, "series": len(series), "key": None}
    key = _write_parquet(rows, minute)
    try:
        _write_explore_feed(rows, minute)  # best-effort; a feed failure must not drop the snapshot
    except Exception as e:
        print("[snapshot] explore feed failed: %r" % e, flush=True)
    print("[snapshot] %s -> %d markets / %d series -> s3://%s/%s"
          % (minute_iso, len(rows), len(series), BUCKET, key), flush=True)
    return {"markets": len(rows), "series": len(series), "key": key}


def _sleep_to_next_minute() -> None:
    time.sleep(60 - (time.time() % 60))  # wake just after the :00 boundary


def main() -> None:
    loop = "--loop" in sys.argv
    while True:
        if loop:
            _sleep_to_next_minute()  # align every snapshot to the minute boundary
        try:
            snapshot_once()
        except Exception as e:
            print("[snapshot] failed: %r" % e, flush=True)
        if not loop:
            return


def _selfcheck() -> None:
    os.environ["TAU_SNAPSHOT_SERIES"] = " KXBTC15M , KXETH ,"
    assert watchlist() == ["KXBTC15M", "KXETH"], watchlist()
    del os.environ["TAU_SNAPSHOT_SERIES"]
    r = _row({"ticker": "T", "event_ticker": "KXBTC15M-X", "yes_bid_dollars": "0.50"}, "KXBTC15M", "m")
    assert r["series_ticker"] == "KXBTC15M" and r["yes_bid"] == "0.50"
    wl = watchlist()  # the committed frozen file must load and be non-trivial
    assert len(wl) > 50 and "KXVOTEGENERAL" in wl, (len(wl), wl[:3])
    print("selfcheck ok (%d series in frozen file)" % len(wl))


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
