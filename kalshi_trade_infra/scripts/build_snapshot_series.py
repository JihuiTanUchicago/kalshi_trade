"""Build data_pipeline/snapshot_series.txt: the FROZEN series watchlist the per-minute
snapshot collector samples (see data_pipeline/snapshot_collector.py).

Selection: every Crypto-category series + the top N real series by current open-market
count, excluding the combinatorial parlay series (KXMVECROSSCATEGORY*). Enumeration uses
/series (crypto) and /events?with_nested_markets (real counts) -- NOT /markets?status=open,
which is ~99.9% parlay markets and never reaches the real universe.

This picks membership by current activity ONCE, then the list is frozen (committed). Re-run
only to deliberately expand the frozen set; review the diff before committing.

Run:  python -m scripts.build_snapshot_series            # top 20 real + crypto
      TOP_REAL=40 python -m scripts.build_snapshot_series # wider
"""
from __future__ import annotations

import os
import time
from collections import Counter

from data_pipeline.common import api_get

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_pipeline", "snapshot_series.txt")
TOP_REAL = int(os.getenv("TOP_REAL", "20"))
PARLAY_PREFIX = "KXMVECROSSCATEGORY"


def crypto_series() -> list:
    return [s["ticker"] for s in api_get("/series", {"category": "Crypto"}).get("series", []) if s.get("ticker")]


def real_series_by_open_markets() -> Counter:
    """Open-market count per series, from /events (bypasses the parlay flood)."""
    cnt: Counter = Counter()
    cursor = None
    for _ in range(400):
        params = {"limit": 200, "status": "open", "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        data = api_get("/events", params)
        events = data.get("events") or []
        for e in events:
            s = e.get("series_ticker")
            if s:
                cnt[s] += len(e.get("markets") or [])
        cursor = data.get("cursor")
        if not cursor or not events:
            break
        time.sleep(0.12)
    return cnt


def build() -> list:
    all_crypto = crypto_series()
    counts = real_series_by_open_markets()
    # Keep only crypto series that currently HAVE open markets. A 0-market series
    # produces no rows anyway; including it is a wasted request every snapshot (and
    # at the ~5 rps unauthenticated limit, wasted requests are what blow the 60s
    # budget). Re-running this picks up any that have since opened markets.
    crypto = [s for s in all_crypto if counts.get(s, 0) > 0]
    chosen = list(crypto)
    seen = set(crypto)
    added = 0
    for series, _ in counts.most_common():
        if added >= TOP_REAL:
            break
        if series in seen or series.startswith(PARLAY_PREFIX):
            continue
        seen.add(series)
        chosen.append(series)
        added += 1
    approx = sum(counts.get(s, 0) for s in chosen)
    print("crypto=%d/%d active + top_real=%d -> %d series, ~%d open markets"
          % (len(crypto), len(all_crypto), added, len(chosen), approx))
    return chosen


if __name__ == "__main__":
    series = build()
    with open(OUT, "w") as f:
        f.write("\n".join(series) + "\n")
    print("wrote", OUT)
