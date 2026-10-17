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

import bisect
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

from app import backtest
from app.markets import Contract, snapshot

# Kalshi demo base. Defaults to the PUBLIC demo host so the sim-vs-real second
# line and slippage measurement work out of the box; override (or set to "") via
# the env var. Read-only, unauthenticated candlestick GETs only - never POSTs.
KALSHI_DEV_API_BASE = os.getenv("KALSHI_DEV_API_BASE", "https://demo-api.kalshi.co/trade-api/v2").rstrip("/")
# Bound the number of per-contract candlestick calls on a cache miss.
# ponytail: sequential per-contract fetch, capped to N out-of-sample contracts,
# the strategy's traded contracts first (so slippage/curve always cover the
# contracts that matter) then first-seen to fill the rest. Raise MAX_CONTRACTS,
# parallelise the fetch, or persist the realized curve if the full window must be shown.
MAX_CONTRACTS = int(os.getenv("KALSHI_DEV_MAX_CONTRACTS", "60"))
CACHE_TTL_SECONDS = 600
# Minimum aligned trades before a slippage figure is trustworthy enough to show
# or feed into the cost model. Below this the block is null (graceful).
MIN_ALIGNED_TRADES = 3

# The contract-independent BTC features; the rest are rebuilt from dev quotes.
_BTC_FEATURE_KEYS = ("spot", "ret_1m", "ret_5m", "ret_15m", "ret_60m", "vol_15m", "vol_60m")

_cache: Dict[str, Tuple[float, Optional[Dict]]] = {}
_lock = threading.Lock()
# Latest measured per-fill slippage (cents) per market, populated as dev curves
# are computed, so the research/cost model can read a market-level number
# without a strategy id. ponytail: last-writer-wins across a market's strategies;
# average across strategies if one strategy's window skews it.
_slippage_by_market: Dict[str, float] = {}


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


def _slippage(sim_trades: List, dev_trades: List, capped: bool) -> Optional[Dict]:
    """Realized-vs-simulated execution gap, in cents, per leg.

    Aligns trades by (ticker, entry_ts, side) - the fills both books chose at
    the same decision point. Signed so POSITIVE = the real demo book filled us
    WORSE than our collected book: on entry (a buy) that's paying a higher price
    (dev - sim); on exit (a sell) that's receiving a lower price (sim - dev).
    Exit is only compared when both sides exited at the same time via a market
    sell (not settlement, whose 0/1 payout is identical across books).
    Returns None when too few trades align to mean anything.
    """
    sim_by = {(t.ticker, t.entry_ts): t for t in sim_trades}
    entry_deltas: List[float] = []
    exit_deltas: List[float] = []
    for dt in dev_trades:
        st = sim_by.get((dt.ticker, dt.entry_ts))
        if st is None or st.side != dt.side:
            continue
        entry_deltas.append(dt.entry_price - st.entry_price)
        if dt.reason != "settled" and st.reason != "settled" and dt.exit_ts == st.exit_ts:
            exit_deltas.append(st.exit_price - dt.exit_price)
    if len(entry_deltas) < MIN_ALIGNED_TRADES:
        return None
    entry_cents = round(sum(entry_deltas) / len(entry_deltas) * 100.0, 2)
    exit_cents = (round(sum(exit_deltas) / len(exit_deltas) * 100.0, 2)
                  if len(exit_deltas) >= MIN_ALIGNED_TRADES else None)
    return {"entry_cents": entry_cents, "exit_cents": exit_cents,
            "n_trades": len(entry_deltas), "capped": capped}


def _quote_end_ts(times: List[int], ts: int, interval: int) -> Optional[int]:
    """The end_period_ts of the demo candle that prices decision frame ``ts``:
    an exact hit when the demo book has that period, else the most recent candle
    AT OR BEFORE ``ts`` within one candle interval (the book's last known
    top-of-book), else None. ``times`` is one ticker's candle ends, ascending.

    Decision frames sit on the candle cadence, but the thin demo book skips
    periods, so an exact-only match drops every gap - this bridges a one-interval
    gap without ever letting a stale quote leak past its period."""
    if not times:
        return None
    i = bisect.bisect_right(times, ts) - 1
    if i < 0 or ts - times[i] > interval:
        return None
    return times[i]


def _per_fill_cents(block: Optional[Dict]) -> Optional[float]:
    """The single symmetric per-fill slippage the backtester's `slip` knob wants:
    mean of entry and exit legs (entry alone when exits don't compare)."""
    if not block:
        return None
    entry, exit_ = block["entry_cents"], block["exit_cents"]
    return round((entry + exit_) / 2.0, 2) if exit_ is not None else entry


def _compute(spec: Dict, ds: backtest.Dataset) -> Optional[Dict]:
    cutoff = ds.cutoff_ts
    oos_frames = [(ts, snaps) for ts, snaps in ds.frames if ts >= cutoff]
    if not oos_frames:
        return None

    # Same spec on our collected book over the OOS window. Computed up front so the
    # per-contract demo fetch is spent on the contracts this strategy ACTUALLY
    # trades: on a multi-day market the first-seen strike ladder is almost disjoint
    # from them, so capping to the first MAX_CONTRACTS first-seen tickers left the
    # dev sim with no tradable contracts -> no dev trades, empty curve, null slippage.
    # The gap between these trades and the dev trades IS the realized slippage.
    sim_trades = backtest.simulate(spec, ds, ds.cutoff_ts, ds.end_ts + 1)

    # Distinct OOS contracts: traded ones first, then first-seen, capped.
    contracts: Dict[str, Contract] = {}
    for _ts, snaps in oos_frames:
        for sn in snaps:
            contracts.setdefault(sn.contract.ticker, sn.contract)
    traded = [tk for tk in dict.fromkeys(t.ticker for t in sim_trades) if tk in contracts]
    order = traded + [tk for tk in contracts if tk not in set(traded)]
    tickers = order[:MAX_CONTRACTS]

    # (ticker, ts) -> (yes_bid, yes_ask) and the ticker's candle end-times (ascending)
    # from the real demo book.
    quotes: Dict[Tuple[str, int], Tuple[float, float]] = {}
    cand_ts: Dict[str, List[int]] = {}
    for tk in tickers:
        c = contracts[tk]
        rows = _dev_candles(ds.market.series, tk, cutoff, int(c.close_time.timestamp()),
                            ds.market.candle_minutes)
        if rows is None:
            continue
        rows.sort()
        cand_ts[tk] = [r[0] for r in rows]
        for ts, bid, ask in rows:
            quotes[(tk, ts)] = (bid, ask)
    if not quotes:
        return None  # host down or no demo data for this window -> no second line

    # Rebuild OOS snapshots off dev quotes, reusing the real BTC features. Each
    # frame is priced by the demo candle covering it (exact, else last within one
    # interval - see _quote_end_ts), so a thin book that skips periods still maps.
    interval = ds.market.decision_seconds
    allowed = set(tickers)
    dev_frames: List[Tuple[int, List]] = []
    for ts, snaps in oos_frames:
        base = {k: snaps[0].features[k] for k in _BTC_FEATURE_KEYS}
        rebuilt = []
        for sn in snaps:
            if sn.contract.ticker not in allowed:
                continue
            e = _quote_end_ts(cand_ts.get(sn.contract.ticker) or [], ts, interval)
            if e is None:
                continue
            bid, ask = quotes[(sn.contract.ticker, e)]
            ns = snapshot(base, sn.contract, ts, bid, ask)
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
    capped = len(order) > len(tickers)
    trades = backtest.simulate(spec, dev_ds, dev_ds.start_ts, dev_ds.end_ts + 1)
    m = backtest.metrics(trades, capital, days)
    curve = backtest._downsample(m["_curve"])
    return {
        "dev_curve": [[ts, v] for ts, v in curve],
        "dev_metrics": {k: m[k] for k in
                        ("trades", "pnl", "roi", "win_rate", "profit_factor", "max_drawdown")},
        "contracts": len(tickers),
        "capped": capped,
        "slippage": _slippage(sim_trades, trades, capped),
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
        per_fill = _per_fill_cents(out.get("slippage") if out else None)
        if per_fill is not None:
            _slippage_by_market[market_key] = per_fill
    return out


def measured_slippage_cents(market_key: str) -> Optional[float]:
    """Market-level per-fill slippage (cents) last measured against the demo book,
    or None if none has been computed yet. Signed: positive = real fills worse.

    Feeds the backtester's cost model: the what-if `slippage_cents` default and,
    later, Wave-2's gatekeeper `Prereg.cost_assumptions` consume this so a strategy
    is scored against the REAL measured slippage instead of the 0.0 default.
    Callers clamp to their own bounds (the what-if path clamps to [0, 5])."""
    with _lock:
        return _slippage_by_market.get(market_key)
