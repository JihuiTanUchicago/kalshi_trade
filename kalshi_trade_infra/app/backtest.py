"""Replay a spec over real Kalshi history and decide if it may be deployed.

Honesty rules, each closing a way backtests usually flatter themselves:

* Buys pay the ask, sells hit the bid, and every fill pays Kalshi's taker fee
  (`kalshi_fees`), rounded up per order as Kalshi does.
* Positions settle on Kalshi's own result for that contract.
* The window is split in time: the agent iterates on IN-SAMPLE only and never
  sees out-of-sample numbers until its final candidates are frozen. A spec
  passes only if it also makes money on the period it never saw.
* The number of hypotheses tried is reported next to every pass, because the
  best of twenty tries is weaker evidence than the only try.
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from app import spec as specmod
from app.markets import MARKETS, BtcSeries, Contract, Market, Snapshot, snapshot
from data_pipeline.kalshi_fees import taker_fee_dollars

IN_SAMPLE_FRACTION = 0.7
GATES = {
    "min_oos_trades": 10,
    "min_profit_factor": 1.1,
    "max_drawdown_of_capital": 0.5,
}
EQUITY_POINTS = 160


@dataclass
class Dataset:
    market: Market
    frames: List[Tuple[int, List[Snapshot]]]  # decision ts -> tradable snapshots, ascending
    results: Dict[str, str]  # ticker -> "yes" | "no"
    start_ts: int
    end_ts: int
    contracts: int

    @property
    def cutoff_ts(self) -> int:
        return int(self.start_ts + (self.end_ts - self.start_ts) * IN_SAMPLE_FRACTION)

    def summary(self) -> Dict:
        yes = sum(1 for r in self.results.values() if r == "yes")
        return {
            "market": self.market.key,
            "label": self.market.label,
            "start": _iso(self.start_ts),
            "end": _iso(self.end_ts),
            "out_of_sample_from": _iso(self.cutoff_ts),
            "decision_points": len(self.frames),
            "contracts": self.contracts,
            "yes_rate": round(yes / len(self.results), 3) if self.results else None,
        }


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def build_dataset(market: Market, markets: List[Dict], candles: List[Dict], btc: List[Tuple[int, float]]) -> Dataset:
    """markets: {ticker, strike, close_time, result}; candles: {ticker, end_period_ts, yes_bid_close, yes_ask_close}."""
    series = BtcSeries(btc)
    contracts = {}
    results = {}
    for m in markets:
        ct = m["close_time"]
        ct = ct if ct.tzinfo else ct.replace(tzinfo=timezone.utc)
        contracts[m["ticker"]] = Contract(m["ticker"], float(m["strike"]), ct, series=market.series)
        results[m["ticker"]] = m["result"]
    by_ts: Dict[int, List[Tuple[Contract, Optional[float], Optional[float]]]] = defaultdict(list)
    for c in candles:
        contract = contracts.get(c["ticker"])
        if contract is None:
            continue
        bid = c["yes_bid_close"]
        ask = c["yes_ask_close"]
        by_ts[int(c["end_period_ts"])].append(
            (contract, float(bid) if bid is not None else None, float(ask) if ask is not None else None)
        )
    frames = []
    for ts in sorted(by_ts):
        feats = series.features_at(ts)
        if feats is None:
            continue
        snaps = [s for s in (snapshot(feats, ct, ts, b, a) for ct, b, a in by_ts[ts]) if s is not None]
        if snaps:
            frames.append((ts, snaps))
    start = frames[0][0] if frames else 0
    end = frames[-1][0] if frames else 0
    return Dataset(market, frames, results, start, end, len(contracts))


# -- simulation ----------------------------------------------------------------


@dataclass
class Trade:
    ticker: str
    side: str
    qty: int
    entry_ts: int
    entry_price: float
    exit_ts: int
    exit_price: float
    fees: float
    reason: str
    edge: float

    @property
    def pnl(self) -> float:
        return self.qty * (self.exit_price - self.entry_price) - self.fees


@dataclass
class _Open:
    ticker: str
    side: str
    qty: int
    entry_ts: int
    entry_price: float
    fee: float
    close_ts: int
    edge: float


@dataclass
class WhatIf:
    fee_multiplier: float = 1.0
    slippage_cents: float = 0.0
    stake: Optional[float] = None


def simulate(spec: Dict, ds: Dataset, start_ts: int, end_ts: int, what_if: Optional[WhatIf] = None) -> List[Trade]:
    """Trades for positions OPENED in [start_ts, end_ts). Positions settle on
    Kalshi's result even if that is after end_ts - the result was fixed by the
    market, not chosen by the backtest. A cross-contract (`cross`) spec routes to
    simulate_pairs; everything else is the single-contract path, unchanged."""
    if spec.get("cross"):
        return simulate_pairs(spec, ds, start_ts, end_ts, what_if)
    w = what_if or WhatIf()
    slip = w.slippage_cents / 100.0
    stake = w.stake if w.stake is not None else spec["sizing"]["stake"]
    max_pos = spec["sizing"]["max_positions"]
    open_: List[_Open] = []
    trades: List[Trade] = []

    def fee(qty: int, price: float) -> float:
        return taker_fee_dollars(qty, price) * w.fee_multiplier

    def settle(pos: _Open) -> None:
        won = ds.results.get(pos.ticker) == pos.side
        trades.append(
            Trade(pos.ticker, pos.side, pos.qty, pos.entry_ts, pos.entry_price, pos.close_ts,
                  1.0 if won else 0.0, pos.fee, "settled", pos.edge)
        )

    for ts, snaps in ds.frames[_first_frame(ds, start_ts):]:
        keep = []
        for pos in open_:
            if pos.close_ts <= ts:
                settle(pos)
            else:
                keep.append(pos)
        open_ = keep

        by_ticker = {s.contract.ticker: s for s in snaps}
        keep = []
        for pos in open_:
            snap = by_ticker.get(pos.ticker)
            sig = specmod.exit_signal(spec, pos.side, pos.entry_price, snap) if snap else None
            if sig is None:
                keep.append(pos)
                continue
            reason, price = sig
            price = max(0.0, price - slip)
            trades.append(
                Trade(pos.ticker, pos.side, pos.qty, pos.entry_ts, pos.entry_price, ts, price,
                      pos.fee + fee(pos.qty, price), reason, pos.edge)
            )
        open_ = keep

        if ts >= end_ts:
            if not open_:
                break
            continue  # past the window: only manage what is already open
        held = {p.ticker for p in open_}
        for cand in specmod.entries(spec, snaps):
            if len(open_) >= max_pos:
                break
            if cand.snapshot.contract.ticker in held:
                continue
            price = min(0.99, cand.price + slip)
            qty = specmod.contracts_for(stake, price)
            if qty < 1:
                continue
            ticker = cand.snapshot.contract.ticker
            open_.append(
                _Open(ticker, cand.side, qty, ts, price, fee(qty, price),
                      int(cand.snapshot.contract.close_time.timestamp()), cand.edge)
            )
            held.add(ticker)
    for pos in open_:
        settle(pos)
    return trades


@dataclass
class _OpenPair:
    long_ticker: str
    short_ticker: str  # bought as NO
    qty: int
    entry_ts: int
    long_price: float  # YES price paid
    short_price: float  # NO price paid
    fee: float
    close_ts: int  # max of the two legs' settlement times
    edge: float


def simulate_pairs(spec: Dict, ds: Dataset, start_ts: int, end_ts: int,
                   what_if: Optional[WhatIf] = None) -> List[Trade]:
    """Relative-value pairs opened in [start_ts, end_ts). Each pair is ONE combined Trade: buy
    YES on the underpriced leg + NO on the overpriced leg, held to settlement. entry_price is
    the per-unit cost of both legs (in (0,2)), exit_price the per-unit payoff ({long won}+{short
    won}), so Trade.pnl = qty*(payoff-cost)-fees stays the honest accounting. Fees are Kalshi's
    taker fee on each leg. ds.frames must carry snapshots of every involved market at each frame
    (a single market already does; cross-market needs merge_datasets)."""
    w = what_if or WhatIf()
    slip = w.slippage_cents / 100.0
    stake = w.stake if w.stake is not None else spec["sizing"]["stake"]
    max_pos = spec["sizing"]["max_positions"]
    open_: List[_OpenPair] = []
    trades: List[Trade] = []

    def fee(qty: int, price: float) -> float:
        return taker_fee_dollars(qty, price) * w.fee_multiplier

    def settle(pos: _OpenPair) -> None:
        long_won = ds.results.get(pos.long_ticker) == "yes"
        short_won = ds.results.get(pos.short_ticker) == "no"  # a NO buy wins when it settles "no"
        payoff = (1.0 if long_won else 0.0) + (1.0 if short_won else 0.0)
        trades.append(
            Trade("%s|%s" % (pos.long_ticker, pos.short_ticker), "pair", pos.qty, pos.entry_ts,
                  pos.long_price + pos.short_price, pos.close_ts, payoff, pos.fee, "settled", pos.edge)
        )

    for ts, snaps in ds.frames[_first_frame(ds, start_ts):]:
        keep = []
        for pos in open_:
            if pos.close_ts <= ts:
                settle(pos)
            else:
                keep.append(pos)
        open_ = keep

        if ts >= end_ts:
            if not open_:
                break
            continue  # past the window: only let open pairs settle
        held = {t for p in open_ for t in (p.long_ticker, p.short_ticker)}
        for cand in specmod.pair_entries(spec, snaps):
            if len(open_) >= max_pos:
                break
            lt = cand.long_snap.contract.ticker
            st = cand.short_snap.contract.ticker
            if lt in held or st in held:
                continue
            long_price = min(0.99, cand.long_price + slip)
            short_price = min(0.99, cand.short_price + slip)
            qty = specmod.contracts_for(stake, long_price + short_price)
            if qty < 1:
                continue
            close_ts = max(int(cand.long_snap.contract.close_time.timestamp()),
                           int(cand.short_snap.contract.close_time.timestamp()))
            open_.append(_OpenPair(lt, st, qty, ts, long_price, short_price,
                                   fee(qty, long_price) + fee(qty, short_price), close_ts, cand.edge))
            held.update((lt, st))
    for pos in open_:
        settle(pos)
    return trades


def merge_datasets(datasets: List[Dataset], key: str, label: Optional[str] = None) -> Dataset:
    """Union several single-market Datasets into one whose frames carry every market's snapshots
    at each decision ts - the input a cross-SECTIONAL pair (e.g. BTC vs ETH) needs. `key` is the
    combined market/FDR-stream key (e.g. 'btc_daily+eth_daily'); the synthetic Market carries it
    so the gatekeeper spends from that one shared stream. cross_strike / calendar pairs stay on a
    single market and need no merge (one dataset's frame already holds every strike/settlement)."""
    if not datasets:
        raise ValueError("merge_datasets needs at least one dataset")
    base = datasets[0].market
    market = Market(key=key, series=key, label=label or key, candle_minutes=base.candle_minutes,
                    history_days=base.history_days, close_hour_et=base.close_hour_et,
                    underlying=base.underlying, deployable=False)
    by_ts: Dict[int, List[Snapshot]] = defaultdict(list)
    results: Dict[str, str] = {}
    contracts = 0
    for ds in datasets:
        results.update(ds.results)
        contracts += ds.contracts
        for ts, snaps in ds.frames:
            by_ts[ts].extend(snaps)
    frames = [(ts, by_ts[ts]) for ts in sorted(by_ts)]
    start = frames[0][0] if frames else 0
    end = frames[-1][0] if frames else 0
    return Dataset(market, frames, results, start, end, contracts)


def _first_frame(ds: Dataset, start_ts: int) -> int:
    lo, hi = 0, len(ds.frames)
    while lo < hi:
        mid = (lo + hi) // 2
        if ds.frames[mid][0] < start_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


# -- metrics -----------------------------------------------------------------


def metrics(trades: List[Trade], capital: float, days: float) -> Dict:
    pnl = sum(t.pnl for t in trades)
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [-t.pnl for t in trades if t.pnl < 0]
    curve, peak, max_dd, cum = [], 0.0, 0.0, 0.0
    daily: Dict[int, float] = defaultdict(float)
    for t in sorted(trades, key=lambda x: x.exit_ts):
        cum += t.pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        curve.append((t.exit_ts, round(cum, 4)))
        daily[t.exit_ts // 86400] += t.pnl
    sharpe = None
    if len(daily) >= 5:
        vals = list(daily.values())
        mean = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))
        sharpe = round(mean / sd * math.sqrt(365), 2) if sd > 0 else None
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3) if trades else None,
        "pnl": round(pnl, 2),
        "fees": round(sum(t.fees for t in trades), 2),
        "roi": round(pnl / capital, 4) if capital else None,
        "profit_factor": round(sum(wins) / sum(losses), 2) if losses else (None if not wins else 99.0),
        "max_drawdown": round(max_dd, 2),
        "sharpe": sharpe,
        "avg_edge": round(sum(t.edge for t in trades) / len(trades), 4) if trades else None,
        "days": round(days, 1),
        "trades_per_day": round(len(trades) / days, 2) if days > 0 else None,
        "_curve": curve,
    }


def _downsample(curve: List[Tuple[int, float]], n: int = EQUITY_POINTS) -> List[Tuple[int, float]]:
    if len(curve) <= n:
        return curve
    step = len(curve) / float(n)
    return [curve[int(i * step)] for i in range(n - 1)] + [curve[-1]]


def evaluate(spec: Dict, ds: Dataset, what_if: Optional[WhatIf] = None, include_oos: bool = True) -> Dict:
    """In-sample metrics always; out-of-sample, gates and the curve only when
    include_oos - the agent's iteration loop calls with include_oos=False."""
    stake = (what_if.stake if what_if and what_if.stake is not None else spec["sizing"]["stake"])
    capital = stake * spec["sizing"]["max_positions"]
    cutoff = ds.cutoff_ts
    day = 86400.0
    is_trades = simulate(spec, ds, ds.start_ts, cutoff, what_if)
    out = {"capital": capital, "dataset": ds.summary(), "in_sample": metrics(is_trades, capital, (cutoff - ds.start_ts) / day)}
    if include_oos:
        oos_trades = simulate(spec, ds, cutoff, ds.end_ts + 1, what_if)
        out["out_of_sample"] = metrics(oos_trades, capital, (ds.end_ts - cutoff) / day)
        whole = metrics(is_trades + oos_trades, capital, (ds.end_ts - ds.start_ts) / day)
        out["equity"] = [[ts, v] for ts, v in _downsample(whole["_curve"])]
        out["gates"] = gates(out["in_sample"], out["out_of_sample"], capital)
        out["passed"] = all(g["ok"] for g in out["gates"])
        out["recent_trades"] = [
            {"ticker": t.ticker, "side": t.side, "qty": t.qty, "entry": round(t.entry_price, 4),
             "exit": round(t.exit_price, 4), "pnl": round(t.pnl, 2), "reason": t.reason,
             "opened": _iso(t.entry_ts)}
            for t in sorted(oos_trades, key=lambda x: x.entry_ts)[-12:]
        ]
        out["out_of_sample"].pop("_curve")
    out["in_sample"].pop("_curve")
    return out


def gates(ins: Dict, oos: Dict, capital: float) -> List[Dict]:
    pf = oos["profit_factor"]
    return [
        {"name": "Makes money in-sample", "value": ins["pnl"], "threshold": "> $0", "ok": ins["pnl"] > 0},
        {"name": "Makes money on unseen data", "value": oos["pnl"], "threshold": "> $0", "ok": oos["pnl"] > 0},
        {
            "name": "Enough unseen trades to judge",
            "value": oos["trades"],
            "threshold": "\u2265 %d" % GATES["min_oos_trades"],
            "ok": oos["trades"] >= GATES["min_oos_trades"],
        },
        {
            "name": "Wins outweigh losses on unseen data",
            "value": pf,
            "threshold": "\u2265 %.1f" % GATES["min_profit_factor"],
            "ok": pf is not None and pf >= GATES["min_profit_factor"],
        },
        {
            "name": "Worst drawdown on unseen data",
            "value": oos["max_drawdown"],
            "threshold": "\u2264 $%.0f" % (capital * GATES["max_drawdown_of_capital"]),
            "ok": oos["max_drawdown"] <= capital * GATES["max_drawdown_of_capital"],
        },
    ]


def score(in_sample: Dict) -> float:
    """Rank candidates the agent may promote, using in-sample numbers only."""
    if in_sample["trades"] < 5:
        return -1e9
    return in_sample["pnl"] * min(1.0, in_sample["trades"] / 20.0)


# -- dataset cache -------------------------------------------------------------

DATASET_TTL_SECONDS = 900
_cache: Dict[str, Tuple[float, Dataset]] = {}
_cache_lock = threading.Lock()


def load_dataset(market_key: str, loader: Callable[..., Dataset], history_days: Optional[int] = None) -> Dataset:
    """Process-local cache: history only grows every 10 minutes, and every
    backtest of a market+window in a process reuses the same frames.
    # ponytail: one copy per process (~40MB per market); move to a shared
    # cache if the worker count grows past a handful."""
    market = MARKETS[market_key]
    days = history_days or market.history_days
    ckey = "%s:%d" % (market_key, days)
    with _cache_lock:
        hit = _cache.get(ckey)
        if hit and time.time() - hit[0] < DATASET_TTL_SECONDS:
            return hit[1]
    ds = loader(market, days)
    with _cache_lock:
        _cache[ckey] = (time.time(), ds)
    return ds


def load_from_db(market: Market, history_days: Optional[int] = None) -> Dataset:
    """The production loader for load_dataset()."""
    from app import repository as repo
    from data_pipeline.common import get_db_conn

    since = repo.now_utc() - timedelta(days=history_days or market.history_days)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            h = repo.load_history(cur, market.series, market.candle_minutes, since, market.underlying)
    finally:
        conn.close()
    return build_dataset(market, h["markets"], h["candles"], h["btc"])


def dataset(market_key: str, history_days: Optional[int] = None) -> Dataset:
    return load_dataset(market_key, load_from_db, history_days)


def partition_dataset(market_key: str, partition: Dict, phase: str) -> Dataset:
    """Build the Dataset for one partition window: 'research', 'validation' or 'holdout'. The
    generator loads only 'research' (via partitions.research_dataset) and hands the 'validation'
    window straight to the gatekeeper without ever reading a number off it — this keeps the
    validation/holdout loaders out of agent.py entirely (§B.4). Lazy import of app.partitions
    avoids the import cycle (partitions imports this module)."""
    from app import partitions
    loaders = {"research": partitions.research_dataset,
               "validation": partitions.validation_dataset,
               "holdout": partitions.holdout_dataset}
    return loaders[phase](market_key, partition)


def research_fold_metrics(spec: Dict, ds: Dataset, embargo_seconds: int,
                          n_splits: int = 4, what_if: Optional[WhatIf] = None) -> Dict:
    """In-research "OOS" metrics via a PURGED walk-forward split (Lopez de Prado) instead of a
    single 70/30 cut: simulate the spec across the whole Research window, then score it only on
    the pooled test folds. stats.purged_walkforward_splits drops train frames that settle into
    (purge) or run up to (embargo) a test block, so the fold is leak-free WITHIN Research — the
    agent may look at it freely. Returns {"capital", "in_sample": metrics} mirroring evaluate()."""
    from app import stats
    stake = (what_if.stake if what_if and what_if.stake is not None else spec["sizing"]["stake"])
    capital = stake * spec["sizing"]["max_positions"]
    trades = sorted(simulate(spec, ds, ds.start_ts, ds.end_ts + 1, what_if), key=lambda t: t.entry_ts)
    if trades:
        splits = stats.purged_walkforward_splits([t.entry_ts for t in trades],
                                                 [t.exit_ts for t in trades], n_splits, embargo_seconds)
        test_idx = sorted({i for sp in splits for i in sp["test_idx"]})
        fold = [trades[i] for i in test_idx] if test_idx else trades
        span = (fold[-1].exit_ts - fold[0].entry_ts) / 86400.0 if fold else 0.0
    else:
        fold, span = [], (ds.end_ts - ds.start_ts) / 86400.0
    m = metrics(fold, capital, max(span, 1e-9))
    m.pop("_curve", None)
    return {"capital": capital, "in_sample": m}
