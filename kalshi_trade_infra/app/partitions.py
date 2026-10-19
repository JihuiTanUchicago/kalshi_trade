"""Chronological Research / Validation / Locked-Holdout partitions for the
rigorous-research pipeline (RESEARCH_PIPELINE_DESIGN.md §B.4).

Computes and FREEZES the 60/25/15 split for a market and serves the three
datasets. Boundaries are snapped FORWARD to the first contract open_time after
each raw ratio cut so no single contract straddles a boundary; purge/embargo are
derived from the market's observed contract duration, not magic constants, so
they stay correct if the venue changes the contract length.

HOLDOUT DISCIPLINE (structural, not advisory): research_dataset is the ONLY
loader the generator (agent.py) may import — validation_dataset and
holdout_dataset are gatekeeper-only. Enforcement is that agent.py never imports
the latter two; grep it to verify.
"""
from __future__ import annotations

import bisect
import hashlib
from collections import Counter
from datetime import timedelta
from typing import Dict, List, Optional

from app import backtest, research_repository as rr, tao_repository
from app.markets import MARKETS, Market
from app.repository import now_utc

# Ratio cuts (oldest -> newest). Research is the generator's whole world;
# validation is selection under the FDR budget; the newest slice is the
# one-time locked holdout, the closest proxy to "future".
RESEARCH_FRAC = 0.60
VALIDATION_FRAC = 0.25  # (holdout gets the remaining 0.15)

# Holdout one-time-evaluation ceilings (§B.4). A ~10-day holdout cannot survive
# hundreds of looks; btc_daily's holdout is only a handful of settlements.
_DEFAULT_HOLDOUT_MAX_EVALS = 10
_HOLDOUT_MAX_EVALS = {"btc_daily": 3}


def holdout_max_evaluations(market: str) -> int:
    """How many one-time holdout evaluations a partition allows before it is
    consumed. Default 10; btc_daily 3 (too few settlements to spend more)."""
    return _HOLDOUT_MAX_EVALS.get(market, _DEFAULT_HOLDOUT_MAX_EVALS)


def ensure_partition(cur, market: str) -> Dict:
    """The active app_data_partitions row for `market`, freezing a new one if none
    exists or if the underlying data has changed (old one -> active=0). Returns the
    persisted row dict."""
    m = MARKETS[market]
    if m.kind == "spot":
        return _ensure_spot_partition(cur, m)
    since = now_utc() - timedelta(days=m.history_days)
    contracts = rr.partition_contracts(cur, m, since)
    if not contracts:
        raise ValueError("no settled contracts for market %r since %s" % (market, since))
    boundaries = _compute_boundaries(m, contracts)
    active = rr.get_active_partition(cur, market)
    # ponytail: re-freeze on ANY change to the underlying rows (fingerprint diff).
    # Simple and keeps the holdout ledger honest; coarsen to a roll-threshold
    # (e.g. one new contract beyond the current holdout) if partition churn bites.
    if active and active["data_fingerprint"] == boundaries["data_fingerprint"]:
        return active
    return rr.save_partition(cur, market, boundaries)


# -- merged (cross-contract) partitions ----------------------------------------
# A cross-contract spec spans >=2 markets, so it needs ONE partition identity for the whole
# market-SET (pre-registration id + a shared holdout ledger), while each leg keeps its own
# single-market frozen window. ensure_merged_partition freezes that identity row (keyed by the
# FDR stream key, e.g. "btc_daily+eth_daily"); merged_dataset serves the phase dataset by loading
# EACH leg from its own frozen window and unioning the frames (so no leg leaks across its own
# boundary). purge/embargo are the MAX of the legs' — the strictest leak buffer (§E.6).


def ensure_merged_partition(cur, markets: List[str]) -> Dict:
    """The active merged partition row for a cross-contract market-SET, freezing a new one if the
    legs' partitions changed. Each leg is first frozen with ensure_partition; the merged row's
    boundaries are the union span of the legs' windows and its purge/embargo the max of theirs."""
    if len(set(markets)) < 2:
        raise ValueError("ensure_merged_partition needs >=2 distinct markets; one uses ensure_partition")
    legs = [ensure_partition(cur, m) for m in sorted(set(markets))]
    b = _merged_boundaries(legs)
    key = "+".join(sorted(set(markets)))
    active = rr.get_active_partition(cur, key)
    if active and active["data_fingerprint"] == b["data_fingerprint"]:
        return active
    return rr.save_partition(cur, key, b)


def _merged_boundaries(legs: List[Dict]) -> Dict:
    """Union-span boundaries + max purge/embargo for a set of frozen leg partitions. The
    fingerprint folds in each leg's id + fingerprint, so the merged row re-freezes whenever any
    leg re-freezes. These bounds are a record/holdout-fingerprint; the per-leg clipping that
    actually serves data lives in merged_dataset()."""
    h = hashlib.sha256()
    for p in sorted(legs, key=lambda x: int(x["id"])):
        h.update(("%s|%s\n" % (p["id"], p["data_fingerprint"])).encode())
    return {
        "research_from_ts": min(p["research_from_ts"] for p in legs),
        "research_to_ts": max(p["research_to_ts"] for p in legs),
        "validation_from_ts": min(p["validation_from_ts"] for p in legs),
        "validation_to_ts": max(p["validation_to_ts"] for p in legs),
        "holdout_from_ts": min(p["holdout_from_ts"] for p in legs),
        "holdout_to_ts": max(p["holdout_to_ts"] for p in legs),
        "embargo_seconds": max(p["embargo_seconds"] for p in legs),
        "purge_seconds": max(p["purge_seconds"] for p in legs),
        "data_fingerprint": h.hexdigest(),
    }


def merged_partitions(cur, markets: List[str]) -> List:
    """Resolve (freeze/read) each leg's frozen partition. This is the ONLY cursor work the merged
    load needs, so a caller can run it on its own thread and then build the dataset off-cursor
    (merged_dataset_from) inside a fail-fast timeout thread without ever sharing the run cursor."""
    return [(m, ensure_partition(cur, m)) for m in sorted(set(markets))]


def merged_dataset_from(legs: List, phase: str):
    """Build the merged dataset from PRE-RESOLVED legs (from merged_partitions). Touches NO caller
    cursor — each leg loads its own frozen window on its own connection — so it is safe to run
    inside _call_with_timeout's worker thread. Same union/key as merged_dataset."""
    loaders = {"research": research_dataset, "validation": validation_dataset, "holdout": holdout_dataset}
    dses = [loaders[phase](m, p) for m, p in legs]
    return backtest.merge_datasets(dses, key="+".join(m for m, _ in legs))


def merged_dataset(cur, markets: List[str], phase: str):
    """The merged Research/Validation/Holdout dataset for a cross-contract spec: each leg loaded
    from its OWN frozen partition window ('research'|'validation'|'holdout') and unioned frame-by-
    frame via backtest.merge_datasets. The combined market key is the FDR stream key, so the
    gatekeeper spends a cross pair from one shared stream (RESEARCH_PIPELINE_DESIGN §E.6)."""
    return merged_dataset_from(merged_partitions(cur, markets), phase)


# -- spot (continuous-price) partitions ----------------------------------------
# A spot market (TAO subnet alpha) has no settled contracts to anchor a boundary, so the candle
# time grid plays that role: the same 60/25/15 ratio cuts, snapped forward to a real candle ts,
# and purge/embargo = one decision bar (a spot position opens and closes within the window, so
# there is no settlement tail to purge like a binary contract has).


def _ensure_spot_partition(cur, market: Market) -> Dict:
    since = now_utc() - timedelta(days=market.history_days)
    points = tao_repository.spot_candle_points(cur, market, since)
    if len(points) < 2:
        raise ValueError("no TAO spot history for market %r since %s" % (market.key, since))
    b = _compute_spot_boundaries(market, points)
    active = rr.get_active_partition(cur, market.key)
    if active and active["data_fingerprint"] == b["data_fingerprint"]:
        return active
    return rr.save_partition(cur, market.key, b)


def _compute_spot_boundaries(market: Market, points: List[int]) -> Dict:
    """Frozen boundary dict for a spot market from its sorted candle timestamps."""
    pts = sorted(set(int(p) for p in points))
    t0, t1 = pts[0], pts[-1]
    span = t1 - t0
    research_to = _snap_forward(pts, t0 + int(span * RESEARCH_FRAC))
    validation_to = _snap_forward(pts, t0 + int(span * (RESEARCH_FRAC + VALIDATION_FRAC)))
    dur = market.decision_seconds
    h = hashlib.sha256()
    for p in pts:
        h.update(("%s|%d\n" % (market.underlying, p)).encode())
    return {
        "research_from_ts": t0,
        "research_to_ts": research_to,
        "validation_from_ts": research_to,
        "validation_to_ts": validation_to,
        "holdout_from_ts": validation_to,
        "holdout_to_ts": t1 + 1,
        "embargo_seconds": dur,
        "purge_seconds": dur,
        "data_fingerprint": h.hexdigest(),
    }


def _compute_boundaries(market: Market, contracts: List[Dict]) -> Dict:
    """Pure math: the frozen boundary dict for a market given its settled
    contracts. Each contract is {open_ts, close_ts, result, ticker}. Boundaries
    are snapped forward to contract open times; purge/embargo come from the
    observed contract duration."""
    opens = sorted({c["open_ts"] for c in contracts})
    t0 = opens[0]
    t1 = opens[-1]
    span = t1 - t0
    # Snap each raw ratio cut forward to the first contract that opens at/after it,
    # so a contract belongs wholly to one partition.
    research_to = _snap_forward(opens, t0 + int(span * RESEARCH_FRAC))
    validation_to = _snap_forward(opens, t0 + int(span * (RESEARCH_FRAC + VALIDATION_FRAC)))
    # End just past the newest contract's settlement so its frames are included.
    holdout_to = max(c["close_ts"] for c in contracts) + 1

    duration = _contract_duration(contracts)
    purge_seconds = duration                       # a train frame can settle one duration out
    embargo_seconds = duration + market.decision_seconds  # + one decision bar buffer

    return {
        "research_from_ts": t0,
        "research_to_ts": research_to,
        "validation_from_ts": research_to,
        "validation_to_ts": validation_to,
        "holdout_from_ts": validation_to,
        "holdout_to_ts": holdout_to,
        "embargo_seconds": embargo_seconds,
        "purge_seconds": purge_seconds,
        "data_fingerprint": _fingerprint(contracts),
    }


def _snap_forward(opens: List[int], raw_cut: int) -> int:
    """First contract open time >= raw_cut (bisect_left on sorted opens). Clamps to
    the last open if the cut is past all contracts."""
    i = bisect.bisect_left(opens, raw_cut)
    return opens[i] if i < len(opens) else opens[-1]


def _contract_duration(contracts: List[Dict]) -> int:
    """Contract holding period for purge/embargo = the settlement CADENCE: the
    most common gap between consecutive distinct contract close times. Data-driven
    (no magic constant) and robust to the listing window being longer than the
    hold: btc15m settles every 900s, btc_daily every 86400s, so those are the
    purge horizons the spec wants. Falls back to the listing-window mode when
    there is only one settlement to measure."""
    closes = sorted({c["close_ts"] for c in contracts})
    gaps = Counter(b - a for a, b in zip(closes, closes[1:]) if b > a)
    if gaps:
        return int(gaps.most_common(1)[0][0])
    windows = Counter(c["close_ts"] - c["open_ts"] for c in contracts if c["close_ts"] > c["open_ts"])
    return int(windows.most_common(1)[0][0]) if windows else 0


def _fingerprint(contracts: List[Dict]) -> str:
    """sha256 over the underlying market rows (ticker, open, close, result),
    sorted — stable identity for the frozen window."""
    h = hashlib.sha256()
    for c in sorted(contracts, key=lambda x: (x["open_ts"], x["ticker"])):
        h.update(("%s|%d|%d|%s\n" % (c["ticker"], c["open_ts"], c["close_ts"], c["result"])).encode())
    return h.hexdigest()


# -- dataset loaders -----------------------------------------------------------
# Each builds a backtest.Dataset holding only the contracts whose OPEN time falls
# in the window, so simulate() on it is self-contained: a position opened in the
# window settles inside the same dataset, never leaking across a boundary.


def research_dataset(market: str, partition: Dict, history_days: Optional[int] = None) -> backtest.Dataset:
    """THE ONLY dataset the generator may load: contracts opening in
    [research_from_ts, research_to_ts). The in-research walk-forward split
    (stats.purged_walkforward_splits) runs inside this, replacing the single
    0.7 cut; agent.py owns that iteration."""
    return _load_window(market, partition["research_from_ts"], partition["research_to_ts"], history_days)


def validation_dataset(market: str, partition: Dict, history_days: Optional[int] = None) -> backtest.Dataset:
    """Gatekeeper-only. Contracts opening in [validation_from_ts, validation_to_ts)."""
    return _load_window(market, partition["validation_from_ts"], partition["validation_to_ts"], history_days)


def holdout_dataset(market: str, partition: Dict, history_days: Optional[int] = None) -> backtest.Dataset:
    """Gatekeeper-only, one-time. Contracts opening in [holdout_from_ts, holdout_to_ts)."""
    return _load_window(market, partition["holdout_from_ts"], partition["holdout_to_ts"], history_days)


def _load_window(market: str, from_ts: int, to_ts: int, history_days: Optional[int]) -> backtest.Dataset:
    """Load the market's history, keep only contracts opening in [from_ts, to_ts),
    and build a Dataset from them. Opens its own connection (these run in the
    gatekeeper/agent runtime, not under a passed cursor)."""
    from data_pipeline.common import get_db_conn

    m = MARKETS[market]
    since = now_utc() - timedelta(days=history_days or m.history_days)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            if m.kind == "spot":
                h = tao_repository.load_spot_history(cur, m, int(since.timestamp()))
                candles = [(t, p) for t, p in h["candles"] if from_ts <= t < to_ts]
                return backtest.build_spot_dataset(m, candles, h["tao_usd"], h["features"])
            rows = rr.partition_source_rows(cur, m, since)
    finally:
        conn.close()
    sub = [mk for mk in rows["markets"]
           if mk.get("open_ts") is not None and from_ts <= mk["open_ts"] < to_ts]
    return backtest.build_dataset(m, sub, rows["candles"], rows["btc"], rows.get("micro"))
