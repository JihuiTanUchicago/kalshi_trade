"""Out-of-sample replay of a strategy against the Kalshi DEMO (dev) environment.

This produces the SECOND line on a strategy's equity chart: alongside the
backtest's simulated curve (built from our own collected history), a *realized*
curve computed from the real Kalshi demo order-book prices for the same
contracts over the same out-of-sample window.

RISK NOTE — DEV-ONLY, READ-ONLY. This module only issues unauthenticated GETs
for public candlesticks against the demo host in ``KALSHI_DEV_API_BASE``. It
never authenticates, never POSTs, and never places or cancels an order. It
re-scores the identical spec with the backtester's own ``simulate`` / ``metrics``
/ fee model, so the realized curve is directly comparable to the simulated one:
the only thing that changes is the prices (real demo book vs our collected
book). BTC spot features are the real underlying and so are reused unchanged.

Graceful degradation: when ``KALSHI_DEV_API_BASE`` is unset, or the demo host
is unreachable, or no candlesticks come back for the window, this returns
``None`` (no second line) and never raises into the page.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

from app import backtest
from app.markets import Contract, snapshot

# Kalshi demo base, e.g. "https://demo-api.kalshi.co/trade-api/v2". Absent -> no curve.
KALSHI_DEV_API_BASE = os.getenv("KALSHI_DEV_API_BASE", "").rstrip("/")
# Bound the number of per-contract candlestick calls on a cache miss.
# ponytail: sequential per-contract fetch, capped to the FIRST N out-of-sample
# contracts. btc15m has ~96 contracts/day, so N=60 covers the opening ~15h of
# the OOS window. Raise MAX_CONTRACTS, parallelise the fetch, or persist the
# realized curve if the full window must be shown.
MAX_CONTRACTS = int(os.getenv("KALSHI_DEV_MAX_CONTRACTS", "60"))
CACHE_TTL_SECONDS = 600

# The contract-independent BTC features; the rest are rebuilt from dev quotes.
_BTC_FEATURE_KEYS = ("spot", "ret_1m", "ret_5m", "ret_15m", "ret_60m", "vol_15m", "vol_60m")

_cache: Dict[str, Tuple[float, Optional[Dict]]] = {}
_lock = threading.Lock()


def unavailable_reason() -> str:
    if not KALSHI_DEV_API_BASE:
        return "Kalshi demo replay isn't configured on this server (set KALSHI_DEV_API_BASE)."
    return "No Kalshi demo prices are available for this strategy's unseen window yet."


def _dev_get(path: str, params: Dict, timeout: int = 15) -> Dict:
    resp = requests.get(KALSHI_DEV_API_BASE + path, params=params, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError("dev GET %s -> %d" % (path, resp.status_code))
    return resp.json()


def _dev_candles(series: str, ticker: str, start_ts: int, end_ts: int,
                 period_min: int) -> Optional[List[Tuple[int, float, float]]]:
    """(end_period_ts, yes_bid, yes_ask) in dollars, or None if the host errored."""
    try:
        data = _dev_get(
            "/series/%s/markets/%s/candlesticks" % (series, ticker),
            {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_min},
        )
    except Exception:
        return None
    out: List[Tuple[int, float, float]] = []
    for c in data.get("candlesticks") or []:
        bid = (c.get("yes_bid") or {}).get("close_dollars")
        ask = (c.get("yes_ask") or {}).get("close_dollars")
        try:
            out.append((int(c["end_period_ts"]), float(bid), float(ask)))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _compute(spec: Dict, ds: backtest.Dataset) -> Optional[Dict]:
    cutoff = ds.cutoff_ts
    oos_frames = [(ts, snaps) for ts, snaps in ds.frames if ts >= cutoff]
    if not oos_frames:
        return None

    # Distinct OOS contracts in ascending first-seen order, capped.
    contracts: Dict[str, Contract] = {}
    for _ts, snaps in oos_frames:
        for sn in snaps:
            contracts.setdefault(sn.contract.ticker, sn.contract)
    order = list(contracts.keys())
    tickers = order[:MAX_CONTRACTS]

    # (ticker, ts) -> (yes_bid, yes_ask) from the real demo book.
    quotes: Dict[Tuple[str, int], Tuple[float, float]] = {}
    host_reachable = False
    for tk in tickers:
        c = contracts[tk]
        rows = _dev_candles(ds.market.series, tk, cutoff, int(c.close_time.timestamp()),
                            ds.market.candle_minutes)
        if rows is None:
            continue
        host_reachable = True
        for ts, bid, ask in rows:
            quotes[(tk, ts)] = (bid, ask)
    if not quotes:
        return None  # host down or no demo data for this window -> no second line

    # Rebuild OOS snapshots off dev quotes, reusing the real BTC features.
    allowed = set(tickers)
    dev_frames: List[Tuple[int, List]] = []
    for ts, snaps in oos_frames:
        base = {k: snaps[0].features[k] for k in _BTC_FEATURE_KEYS}
        rebuilt = []
        for sn in snaps:
            if sn.contract.ticker not in allowed:
                continue
            q = quotes.get((sn.contract.ticker, ts))
            if q is None:
                continue
            ns = snapshot(base, sn.contract, ts, q[0], q[1])
            if ns is not None:
                rebuilt.append(ns)
        if rebuilt:
            dev_frames.append((ts, rebuilt))
    if not dev_frames:
        return None

    dev_ds = backtest.Dataset(ds.market, dev_frames, ds.results,
                              dev_frames[0][0], dev_frames[-1][0], len(tickers))
    stake = spec["sizing"]["stake"]
    capital = stake * spec["sizing"]["max_positions"]
    days = (dev_ds.end_ts - dev_ds.start_ts) / 86400.0
    trades = backtest.simulate(spec, dev_ds, dev_ds.start_ts, dev_ds.end_ts + 1)
    m = backtest.metrics(trades, capital, days)
    curve = backtest._downsample(m["_curve"])
    return {
        "dev_curve": [[ts, v] for ts, v in curve],
        "dev_metrics": {k: m[k] for k in
                        ("trades", "pnl", "roi", "win_rate", "profit_factor", "max_drawdown")},
        "contracts": len(tickers),
        "capped": len(order) > len(tickers),
        "env": "kalshi-dev",
    }


def dev_curve_for_strategy(strategy_id: int, spec: Dict, market_key: str) -> Optional[Dict]:
    """Realized demo-environment OOS curve for one strategy, cached per id.

    Returns None (caller shows no second line) when demo replay is unconfigured
    or unavailable. Never raises on a dev/data problem.
    """
    if not KALSHI_DEV_API_BASE:
        return None
    key = str(strategy_id)
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    try:
        ds = backtest.dataset(market_key)
        out = _compute(spec, ds)
    except Exception:
        out = None
    with _lock:
        _cache[key] = (now, out)
    return out
