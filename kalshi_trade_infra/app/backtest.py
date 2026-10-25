"""Replay a spec over real Kalshi history and decide if it may be deployed.

Honesty rules, each closing a way backtests usually flatter themselves:

* Buys pay the ask, sells hit the bid, and every fill pays Kalshi's taker fee
  (`kalshi_fees`), rounded up per order as Kalshi does.
* Fills happen on the NEXT bar, not the one that produced the signal (FILL_MODEL), the way
  the live kernel re-prices at submit: an entry fills only if the next ask is still within the
  edge-clearing reservation price, and never for more than the displayed top-of-book size.
* Positions settle on Kalshi's own result for that contract.
* The window is split in time: the agent iterates on IN-SAMPLE only and never
  sees out-of-sample numbers until its final candidates are frozen. A spec
  passes only if it also makes money on the period it never saw.
* The number of hypotheses tried is reported next to every pass, because the
  best of twenty tries is weaker evidence than the only try.
"""
from __future__ import annotations

import copy
import logging
import math
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from app import freedata
from app import spec as specmod
from app import options_fair, sports_odds, weather_fcst
from app.markets import (MARKETS, NEW_YORK, WEATHER_STATIONS, BtcSeries, Contract, Market, Snapshot, snapshot,
                         cross_features, cross_product,
                         weather_obs_applies)
from data_pipeline.architecture.execution_kernel import reservation_price
from data_pipeline.kalshi_fees import taker_fee_dollars

IN_SAMPLE_FRACTION = 0.7
MIN_FIT_SAMPLES = 200  # a learned model needs this many labelled research rows before it is fit
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


def build_dataset(market: Market, markets: List[Dict], candles: List[Dict], btc: List[Tuple[int, float]],
                  micro: Optional[Dict[Tuple[str, int], Dict[str, float]]] = None,
                  frame_series: Optional[Dict[str, List[Tuple[int, float]]]] = None,
                  frame_series_applies: Optional[Callable[[str, int], bool]] = None,
                  forecasts=None, cross: Optional[List[Tuple[int, float]]] = None) -> Dataset:
    """markets: {ticker, strike, close_time, result}; candles: (ticker, end_period_ts, yes_bid, yes_ask)
    tuples as repository.load_history returns them, or the equivalent dicts.
    micro: {(ticker, decision_ts): {feature: value}} order-book features to merge per snapshot (optional).
    frame_series: {feature: [(known_at_ts, value)]} market-wide series (e.g. weather-station readings)
    as-of joined onto every frame, so a frame only sees values already known at its ts.
    frame_series_applies(ticker, ts): which contracts in a frame they describe (default: all).
    forecasts: an external fair-value book (forecast_book: weather forecasts or sportsbook odds); each
    contract then carries its features (book.features, the same call the live engine makes).
    cross: one-minute (start_ts, close) of markets.cross_product(market), whose CROSS_FEATURES are
    merged onto every frame they're fresh for (the engine's _with_cross does the same live)."""
    micro = micro or {}
    series = BtcSeries(btc)
    xprod = cross_product(market) if cross else None
    xseries = BtcSeries(cross) if xprod else None
    # Sports (and any market with underlying=None) have no spot path: every frame with a
    # two-sided quote is tradable on price/order-book features alone, so skip the
    # fresh-underlying gate and feed snapshot() an empty feature base.
    has_underlying = market.underlying is not None
    contracts = {}
    results = {}
    for m in markets:
        ct = m["close_time"]
        ct = ct if ct.tzinfo else ct.replace(tzinfo=timezone.utc)
        contracts[m["ticker"]] = Contract(m["ticker"], float(m["strike"]), ct, series=market.series)
        results[m["ticker"]] = m["result"]
    by_ts: Dict[int, List[Tuple[Contract, Optional[float], Optional[float]]]] = defaultdict(list)
    for c in candles:
        if isinstance(c, dict):
            c = (c["ticker"], c["end_period_ts"], c["yes_bid_close"], c["yes_ask_close"])
        ticker, end_ts, bid, ask = c
        contract = contracts.get(ticker)
        if contract is None:
            continue
        by_ts[int(end_ts)].append(
            (contract, float(bid) if bid is not None else None, float(ask) if ask is not None else None)
        )
    joined = {name: freedata.asof_join(list(by_ts), obs) for name, obs in (frame_series or {}).items()}
    frames = []
    for ts in sorted(by_ts):
        feats = series.features_at(ts) if has_underlying else {}
        if feats is None:
            continue
        if xseries is not None:
            xf = cross_features(xprod, xseries, ts)
            if xf:
                feats = dict(feats, **xf)
        extra = {n: j[ts] for n, j in joined.items() if ts in j}
        with_extra = dict(feats, **extra) if extra else feats
        snaps = []
        for ct, b, a in by_ts[ts]:
            cf = with_extra if extra and (frame_series_applies is None or frame_series_applies(ct.ticker, ts)) else feats
            s = snapshot(cf, ct, ts, b, a,
                         weather_fcst.with_forecast(micro.get((ct.ticker, ts)), forecasts, ct, ts, b, a, cf))
            if s is not None:
                snaps.append(s)
        if snaps:
            frames.append((ts, snaps))
    start = frames[0][0] if frames else 0
    end = frames[-1][0] if frames else 0
    return Dataset(market, frames, results, start, end, len(contracts))


def build_spot_dataset(market: Market, candles: List[Tuple[int, float]],
                       tao_usd: Optional[List[Tuple[int, float]]] = None,
                       features: Optional[Dict[int, Dict[str, float]]] = None) -> Dataset:
    """A continuous-price (spot) Dataset for a TAO subnet alpha token - the spot analogue of
    build_dataset, with NO contracts/strikes/settlement.

    candles  : (ts, alpha_price_in_TAO) for symbol TAO-SN{n} (the pool ratio tau_pool/alpha_pool),
               the primary traded series.
    tao_usd  : (ts, TAO/USD rate) for symbol TAO-USD; forward-filled onto each frame so alpha-in-
               USD can be derived (alpha_usd = alpha_tao * tao_usd). No third series is stored.
    features : {ts: {emission_weight, tao_pool, alpha_pool, registrations, net_stake_flow, ...}}
               from tao_subnet_features, joined by ts exactly like model_features_1m is by minute.

    Each frame is (ts, {"alpha_tao", "tao_usd", "alpha_usd", "features"}); simulate_spot and the
    signals(window) contract read these. Positions settle on NOTHING - they close on an exit
    signal or at the final mark - so Dataset.results is empty and contracts is 0."""
    rows = sorted((int(t), float(p)) for t, p in candles if p and float(p) > 0)
    rates = sorted((int(t), float(r)) for t, r in (tao_usd or []) if r and float(r) > 0)
    feats = features or {}
    frames: List[Tuple[int, Dict]] = []
    ri = 0
    last_rate: Optional[float] = None
    for ts, alpha_tao in rows:
        while ri < len(rates) and rates[ri][0] <= ts:  # forward-fill the most recent TAO/USD rate
            last_rate = rates[ri][1]
            ri += 1
        alpha_usd = alpha_tao * last_rate if last_rate is not None else None
        frames.append((ts, {"alpha_tao": alpha_tao, "tao_usd": last_rate,
                            "alpha_usd": alpha_usd, "features": feats.get(ts, {})}))
    start = frames[0][0] if frames else 0
    end = frames[-1][0] if frames else 0
    return Dataset(market, frames, {}, start, end, 0)


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
    position_stop_pct: Optional[float] = None   # None = POSITION_STOP_PCT; 0 = no stop


# The position-level stop paper and live enforce (engine.force_sell_if_drawn_down, the user's
# position_stop_pct, default 40): an open position marked down past this percent of its cost
# (qty * entry + entry fee, marked at the side's bid) is sold. The backtest applies it too, so the
# gate tests the rule that actually trades. Not simulated: the deployment PAUSE that follows a live
# stop, and intra-bar dips (live marks every few seconds; the backtest sees one quote per bar).
POSITION_STOP_PCT = float(os.getenv("TAU_BACKTEST_POSITION_STOP_PCT", "40"))


def _stop_hit(pos, snap: Snapshot, stop_pct: float) -> Optional[float]:
    """The bid to sell at when `pos` is past the stop on this bar's quote, else None."""
    if stop_pct <= 0:
        return None
    bid = specmod.side_prices(snap)[pos.side][1]
    cost = pos.qty * pos.entry_price + pos.fee
    if bid <= 0 or cost <= 0:
        return None          # no bid to sell into: live cannot close it either, so it settles
    return bid if 100.0 * (cost - pos.qty * bid) / cost >= stop_pct else None


def simulate(spec: Dict, ds: Dataset, start_ts: int, end_ts: int, what_if: Optional[WhatIf] = None) -> List[Trade]:
    """Trades for positions OPENED in [start_ts, end_ts). Positions settle on
    Kalshi's result even if that is after end_ts - the result was fixed by the
    market, not chosen by the backtest.

    A cross-contract (`cross`) spec routes to simulate_pairs. A code strategy (spec has
    `code`) computes a per-frame target book in the sandbox once; the entry/exit/sizing/
    fee/settlement mechanics below are then IDENTICAL to a DSL spec. Everything else is the
    single-contract DSL path, unchanged."""
    if ds.market.kind == "perpetual" or specmod.is_perpetual_spec(spec):
        if ds.market.kind != "perpetual" or spec.get("market") != ds.market.key:
            raise ValueError("Perpetual research requires its own matching instrument dataset.")
        from app.kalshi_perps_backtest import simulate as simulate_perpetual
        return simulate_perpetual(spec, ds, start_ts, end_ts, what_if)
    if spec.get("cross"):
        return simulate_pairs(spec, ds, start_ts, end_ts, what_if)
    if ds.market.kind == "spot":
        return simulate_spot(spec, ds, start_ts, end_ts, what_if)
    if FILL_MODEL == "next_bar":
        return _simulate_next_bar(spec, ds, start_ts, end_ts, what_if)
    w = what_if or WhatIf()
    slip = w.slippage_cents / 100.0
    stake = w.stake if w.stake is not None else spec["sizing"]["stake"]
    max_pos = spec["sizing"]["max_positions"]
    book = _code_book(spec, ds, start_ts, end_ts) if specmod.is_code_spec(spec) else None
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
            if not snap:
                sig = None
            elif book is not None:
                sig = _code_exit(book, ts, pos, snap)
            else:
                sig = specmod.exit_signal(spec, pos.side, pos.entry_price, snap)
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
        cands = _code_entries(book, ts, snaps) if book is not None else specmod.entries(spec, snaps)
        for cand in cands:
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


# How single-contract binary fills are modeled. "next_bar" (default) mirrors the live kernel: the
# signal is computed from a bar's closing quote, the order executes against the NEXT bar's quote,
# an entry is abandoned if that ask is past the edge-clearing reservation price (exactly
# execution_kernel.reservation_price, the cap live and paper enforce), and the filled size is capped
# at the displayed best-level size when the feed carries it. "signal_bar" is the legacy optimistic
# model that filled at the very quote that produced the signal; it is kept for comparison only.
FILL_MODEL = os.getenv("TAU_BACKTEST_FILL_MODEL", "next_bar")
FILL_MAX_DELAY_BARS = 2  # an order whose next quote is further away than this many bars expires
# Highest ask an entry may lift. A 99c contract pays at most 1c, which the taker fee eats, so a buy
# there can never profit; on an empty book (no bid, 99c ask) it is the only "offer". Sports ladders
# that went empty (KXNFLRECYDSPROT: 83% of quotes yes_ask >= 0.99) let code strategies "buy" at 99c
# and lose ~80c a trade at a ~1% win rate (run 2815), burying any real signal under phantom fills.
MAX_ENTRY_ASK = 0.98


def _top_size(snap: Snapshot, side: str) -> Optional[float]:
    """Contracts resting at the best level a BUY of `side` would take: YES buys lift the YES ask;
    NO buys hit the YES bid (a NO ask is 1 - YES bid). None when the feed has no size."""
    v = snap.features.get("yes_ask_size" if side == "yes" else "yes_bid_size")
    return float(v) if v is not None else None


def _simulate_next_bar(spec: Dict, ds: Dataset, start_ts: int, end_ts: int,
                       what_if: Optional[WhatIf] = None) -> List[Trade]:
    """simulate() under FILL_MODEL="next_bar". Same sizing, fees, holding and settlement rules; the
    only difference is WHEN and AT WHAT PRICE an order fills:

    * an entry signalled at bar t fills at bar t+1's ask for that contract, only if that ask (plus
      what-if slippage) is <= the reservation price for the spec's own fair value and min_edge (a
      code strategy, which has no fair value, may not pay more than its signal price), and for at
      most the displayed top-of-book size. Otherwise the entry is missed, as live would abandon it;
    * an exit signalled at bar t sells at bar t+1's bid. Until it fills the position keeps settling
      normally, so a contract that expires first simply settles;
    * an order whose next quote is more than FILL_MAX_DELAY_BARS bars away expires unfilled.

    Entry timestamps are fill times, so trade timing, the purged splits and the cross-day checks all
    see when the position really existed."""
    w = what_if or WhatIf()
    slip = w.slippage_cents / 100.0
    stake = w.stake if w.stake is not None else spec["sizing"]["stake"]
    max_pos = spec["sizing"]["max_positions"]
    book = _code_book(spec, ds, start_ts, end_ts) if specmod.is_code_spec(spec) else None
    min_edge = None if book is not None else float(spec["entry"]["min_edge"])
    max_delay = FILL_MAX_DELAY_BARS * max(int(getattr(ds.market, "decision_seconds", 60) or 60), 1)
    open_: List[_Open] = []
    trades: List[Trade] = []
    pending_entries: List[Tuple[int, specmod.Entry]] = []
    pending_exits: Dict[str, Tuple[int, str]] = {}  # ticker -> (signal ts, exit reason)
    stop_pct = POSITION_STOP_PCT if w.position_stop_pct is None else float(w.position_stop_pct)

    def fee(qty: int, price: float) -> float:
        return taker_fee_dollars(qty, price) * w.fee_multiplier

    def settle(pos: _Open) -> None:
        won = ds.results.get(pos.ticker) == pos.side
        trades.append(Trade(pos.ticker, pos.side, pos.qty, pos.entry_ts, pos.entry_price, pos.close_ts,
                            1.0 if won else 0.0, pos.fee, "settled", pos.edge))

    for ts, snaps in ds.frames[_first_frame(ds, start_ts):]:
        keep = []
        for pos in open_:
            if pos.close_ts <= ts:
                settle(pos)
                pending_exits.pop(pos.ticker, None)
            else:
                keep.append(pos)
        open_ = keep
        by_ticker = {s.contract.ticker: s for s in snaps}

        # 0. The position stop paper/live enforce sells at this bar's bid, ahead of any spec exit.
        keep = []
        for pos in open_:
            snap = by_ticker.get(pos.ticker)
            bid = _stop_hit(pos, snap, stop_pct) if snap is not None else None
            if bid is None:
                keep.append(pos)
                continue
            price = max(0.0, bid - slip)
            trades.append(Trade(pos.ticker, pos.side, pos.qty, pos.entry_ts, pos.entry_price, ts, price,
                                pos.fee + fee(pos.qty, price), "stop", pos.edge))
            pending_exits.pop(pos.ticker, None)
        open_ = keep

        # 1. Exits signalled on an earlier bar sell at this bar's bid.
        keep = []
        for pos in open_:
            sig = pending_exits.get(pos.ticker)
            snap = by_ticker.get(pos.ticker)
            if sig is not None and ts - sig[0] > max_delay:
                pending_exits.pop(pos.ticker)  # stale; re-evaluated below
            elif sig is not None and snap is not None:
                sell = specmod.side_prices(snap)[pos.side][1]
                if sell > 0:
                    price = max(0.0, sell - slip)
                    trades.append(Trade(pos.ticker, pos.side, pos.qty, pos.entry_ts, pos.entry_price, ts,
                                        price, pos.fee + fee(pos.qty, price), sig[1], pos.edge))
                    pending_exits.pop(pos.ticker)
                    continue
            keep.append(pos)
        open_ = keep

        # 2. Entries signalled on the previous bar fill at this bar's ask, within the reservation.
        held = {p.ticker for p in open_}
        for sig_ts, cand in pending_entries:
            if len(open_) >= max_pos:
                break
            ticker = cand.snapshot.contract.ticker
            snap = by_ticker.get(ticker)
            if ts - sig_ts > max_delay or ticker in held or snap is None:
                continue
            ask = specmod.side_prices(snap)[cand.side][0]
            if not 0.0 < ask <= MAX_ENTRY_ASK:
                continue
            price = min(0.99, ask + slip)
            qty = specmod.contracts_for(stake, price)
            size = _top_size(snap, cand.side)
            if size is not None:
                qty = min(qty, int(size))
            if qty < 1:
                continue
            limit = cand.price if min_edge is None else reservation_price(cand.fair, min_edge, qty)
            if limit is None or price > limit + 1e-9:
                continue  # the ask ran past what the edge allows: live abandons, so do we
            open_.append(_Open(ticker, cand.side, qty, ts, price, fee(qty, price),
                               int(snap.contract.close_time.timestamp()), cand.edge))
            held.add(ticker)
        pending_entries = []

        # 3. New exit signals on open positions (filled next bar).
        for pos in open_:
            if pos.ticker in pending_exits:
                continue
            snap = by_ticker.get(pos.ticker)
            if not snap:
                continue
            sig = _code_exit(book, ts, pos, snap) if book is not None else \
                specmod.exit_signal(spec, pos.side, pos.entry_price, snap)
            if sig is not None:
                pending_exits[pos.ticker] = (ts, sig[0])

        # 4. New entry signals (filled next bar), only inside the window.
        if ts >= end_ts:
            if not open_:
                break
            continue
        cands = _code_entries(book, ts, snaps) if book is not None else specmod.entries(spec, snaps)
        pending_entries = [(ts, c) for c in cands if c.snapshot.contract.ticker not in held]
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


# -- arbitrary-quant code strategies -------------------------------------------
# The sandbox runs the agent's signals(window) ONCE over the in-window frames and returns a
# target book per frame; the shared simulate() loop then applies sizing/fees/settlement. Any
# sandbox failure or malformed output yields an empty book -> zero trades (fails the gate
# honestly) rather than crashing the research run.


def _binary_window(market: str, frames: List[Tuple[int, List[Snapshot]]]) -> Dict:
    """The signals(window) / fit(window) input for a binary market: per-frame contract quotes +
    features. The ONE place this window shape is built, so fit and signals see the same thing."""
    return {"market": market, "frames": [
        {"ts": ts, "contracts": [
            {"ticker": s.contract.ticker, "strike": s.contract.strike,
             # The Kalshi event (game / day / window) the contract belongs to: its ticker minus the
             # strike suffix, so a ladder's strikes group without the proposer parsing tickers.
             "event": s.contract.ticker.rsplit("-", 1)[0],
             "close_ts": int(s.contract.close_time.timestamp()),
             "yes_bid": s.yes_bid, "yes_ask": s.yes_ask,
             # Mirrored into features too: rule specs list yes_bid/yes_ask as features, so generated
             # code often reads c["features"]["yes_bid"] and saw None (a dropped thesis in prod).
             "features": dict(s.features, yes_bid=s.yes_bid, yes_ask=s.yes_ask)}
            for s in snaps]}
        for ts, snaps in frames]}


def _code_book(spec: Dict, ds: Dataset, start_ts: int, end_ts: int) -> Dict[int, Dict[str, Tuple[str, float]]]:
    """Run the strategy and return {ts: {ticker: (side, score)}} for in-window decision frames.
    # ponytail: serializes the window to JSON per simulate() call (O(frames x contracts)); fine
    # for current window sizes, switch to a binary channel if windows grow much larger."""
    from app import sandbox
    frames = [(ts, snaps) for ts, snaps in ds.frames if start_ts <= ts < end_ts]
    window = _binary_window(spec["market"], frames)
    freedata.enrich(spec, window)  # as-of join requested free external data into frame["external"]
    if spec.get("params") is not None:
        window["params"] = spec["params"]  # the frozen research-fit model; signals predicts, never refits
    try:
        # data_dir=None: no cross-run channel, so signals on this fold can read ONLY these frames +
        # the frozen params — it cannot reach another fold's data (fold-boundary enforced here).
        raw = sandbox.run_strategy_signals(spec["code"], window, data_dir=None)
    except sandbox.SandboxError as e:
        logging.getLogger(__name__).warning("code strategy sandbox failure: %s", e)
        return {}
    return _parse_book(raw, frames)


def _fit_results(ds: Dataset, frames: List[Tuple[int, List[Snapshot]]]) -> Dict[str, str]:
    """The training labels fit(window) reads as window["results"] ({ticker: "yes"|"no"}): only
    contracts that SETTLED inside the research window, so no outcome dated past the fold reaches the
    frozen model. signals() never gets results (its window is the one being scored). Before this,
    fit() saw no results at all, so every supervised model trained on all-NO labels and failed with
    "only one class present" or fit nothing."""
    out: Dict[str, str] = {}
    for _, snaps in frames:
        for s in snaps:
            tk = s.contract.ticker
            if tk not in out and ds.results.get(tk) in ("yes", "no") \
                    and s.contract.close_time.timestamp() <= ds.end_ts:
                out[tk] = ds.results[tk]
    return out


def freeze_code_model(spec: Dict, ds: Dataset, diag: Optional[Dict] = None) -> Dict:
    """Fit-on-research-and-FREEZE. If the agent's code defines fit(window), run it ONCE over the
    whole RESEARCH window `ds` and freeze the returned params into spec['params'] — which becomes
    part of the pre-registered, hashed experiment identity. signals() then predicts with those
    frozen params on every fold (research, validation, holdout) WITHOUT refitting, so the model the
    gatekeeper scores on unseen data was fit only on research (closes the fit-at-test-time leak).

    No fit() (a pure-rule code strategy) or a non-code DSL spec -> returned unchanged. A fit failure
    logs and returns the spec unfrozen; signals then runs without params and, if it needed a model,
    produces an empty book -> the hypothesis fails the gate honestly rather than crashing the run.

    If `diag` (a dict) is passed, a fit failure records the raw error under `code_fit_failed` so the
    research loop can tell the agent WHY its hypothesis took ~0 trades (a single-class training
    window is the usual cause) instead of leaving it to guess. Pure observability: it never changes
    the fit or whether the spec is frozen."""
    from app import sandbox
    if ds.market.kind == "perpetual":
        # Phase one uses trusted causal rules, never a full-fold arbitrary code strategy.
        return specmod.validate(spec)
    if not specmod.is_code_spec(spec) or not sandbox.strategy_has_fit(spec["code"]):
        return spec
    frames = list(ds.frames)
    window = _binary_window(spec["market"], frames) if ds.market.kind != "spot" else _spot_window(spec["market"], frames)
    if ds.market.kind != "spot":
        window["results"] = _fit_results(ds, frames)
    freedata.enrich(spec, window)  # research-fold external data, as-of joined (fit sees research only)
    try:
        params = sandbox.run_strategy_fit(spec["code"], window, data_dir=None)
    except sandbox.SandboxError as e:
        logging.getLogger(__name__).warning("code strategy fit failed; running without a frozen model: %s", e)
        if diag is not None:
            diag["code_fit_failed"] = str(e)[:300]
        return spec
    return dict(spec, params=params)


def _parse_book(raw, frames) -> Dict[int, Dict[str, Tuple[str, float]]]:
    """Validate untrusted sandbox output into a book. Any shape violation -> {} (no trades)."""
    if not isinstance(raw, list) or len(raw) != len(frames):
        return {}
    book: Dict[int, Dict[str, Tuple[str, float]]] = {}
    for (ts, snaps), picks in zip(frames, raw):
        tickers = {s.contract.ticker for s in snaps}
        want: Dict[str, Tuple[str, float]] = {}
        if not isinstance(picks, list):
            return {}
        for p in picks:
            if not isinstance(p, dict):
                return {}
            ticker, side, score = p.get("ticker"), p.get("side"), p.get("score", 0.0)
            if ticker not in tickers or side not in ("yes", "no"):
                return {}
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                return {}
            want.setdefault(ticker, (side, float(score)))  # first listing of a ticker wins
        book[ts] = want
    return book


def _code_entries(book: Dict[int, Dict[str, Tuple[str, float]]], ts: int, snaps: List[Snapshot]):
    """The contracts the code wants to OPEN at this frame, best score first, as spec.Entry so the
    shared loop treats them exactly like DSL entries. fair/edge carry the strategy's own score."""
    want = book.get(ts)
    if not want:
        return []
    by_ticker = {s.contract.ticker: s for s in snaps}
    out = []
    for ticker, (side, score) in want.items():
        snap = by_ticker.get(ticker)
        if snap is None:
            continue
        price = specmod.side_prices(snap)[side][0]
        if price <= 0 or price > MAX_ENTRY_ASK:
            continue
        out.append(specmod.Entry(snap, side, price, price, score))
    out.sort(key=lambda e: e.edge, reverse=True)
    return out


def _code_exit(book: Dict[int, Dict[str, Tuple[str, float]]], ts: int, pos: _Open, snap: Snapshot):
    """Exit when the code stops listing this (ticker, side): sell at the bid. Frames past the
    window are not in the book, so open positions there are simply held to settlement."""
    want = book.get(ts)
    if want is None:
        return None  # not a decision frame we control -> hold
    tgt = want.get(pos.ticker)
    if tgt is not None and tgt[0] == pos.side:
        return None  # still wanted -> hold
    sell = specmod.side_prices(snap)[pos.side][1]
    if sell <= 0:
        return None  # nobody to sell to; hold to settlement
    return "signal", sell


# -- spot (continuous price) strategies ----------------------------------------
# A TAO subnet alpha token is a price series, not a binary contract: no strike, no expiry, no
# $0/$1 settlement. simulate_spot is simulate() minus settlement/contract bookkeeping - positions
# are long/flat (short is a parsed stub, off by default: there is no on-chain short), PnL is
# qty*(exit-entry)-fees, and fills slip against pool depth (tao_fees) instead of paying a Kalshi
# taker fee. metrics()/gatekeeper consume the resulting Trade list unchanged. The code-strategy
# seam is reused: signals(window) returns a per-frame target book, same as the binary path.

from app import tao_fees  # noqa: E402  (local venue cost model, mirrors kalshi_fees import)

# Shorting an AMM-only asset is not possible on-chain (TAO_VENUE_DESIGN.md §D), so "short" picks
# are parsed but dropped unless this is flipped on for research of a hypothetical short venue.
SPOT_ALLOW_SHORT = False
SPOT_SIDES = ("long", "short")


@dataclass
class _OpenSpot:
    side: str            # "long" | "short"
    qty: float           # alpha tokens held (fractional; not integer contracts)
    entry_ts: int
    entry_price: float   # fill price in the chosen denomination
    fee: float           # entry swap/tx cost so far (denomination)


def _spot_frame_prices(frame: Dict, denom: str) -> Tuple[Optional[float], Optional[float]]:
    """(mid price in the chosen denomination, alpha_pool depth) for one spot frame. USD uses the
    derived alpha_usd (None when no TAO/USD rate is known yet); TAO uses the raw pool-ratio price."""
    price = frame["alpha_usd"] if denom == "usd" else frame["alpha_tao"]
    alpha_pool = frame.get("features", {}).get("alpha_pool")
    return price, alpha_pool


def simulate_spot(spec: Dict, ds: Dataset, start_ts: int, end_ts: int,
                  what_if: Optional[WhatIf] = None, denom: str = "usd") -> List[Trade]:
    """Trades for spot positions OPENED in [start_ts, end_ts). `denom` picks the PnL/price unit:
    "usd" (default - what the customer reads returns in) or "tao" (the pool/slippage-native unit).
    Sizing (sizing.stake) is always a USD notional; qty is the alpha tokens that buys at the mid,
    so the two denominations describe the SAME position and differ only by the TAO/USD rate.

    A spot strategy is a code strategy (signals(window)); a non-code spec yields no book -> no
    trades (the binary DSL has no meaning without a strike). Any sandbox/shape failure -> {} ->
    zero trades, failing the gate honestly rather than crashing the run."""
    w = what_if or WhatIf()
    stake = w.stake if w.stake is not None else spec["sizing"]["stake"]
    max_pos = spec["sizing"]["max_positions"]
    book = _spot_code_book(spec, ds, start_ts, end_ts) if specmod.is_code_spec(spec) else {}
    open_: List[_OpenSpot] = []
    trades: List[Trade] = []
    last: Optional[Tuple[int, float, Optional[float]]] = None  # (ts, mark, pool) of newest priced frame

    def close(pos: _OpenSpot, ts: int, mid: float, alpha_pool: Optional[float], reason: str) -> None:
        sell = tao_fees.fill_price(mid, pos.qty, "sell", alpha_pool)
        fee = pos.fee + tao_fees.swap_fee(pos.qty * sell)
        trades.append(Trade("%s" % ds.market.key, pos.side, pos.qty, pos.entry_ts, pos.entry_price,
                            ts, sell, fee, reason, 0.0))

    for ts, frame in ds.frames[_first_frame(ds, start_ts):]:
        mid, alpha_pool = _spot_frame_prices(frame, denom)
        if mid is None or mid <= 0:
            continue  # no priced frame (e.g. USD before the first TAO/USD rate) -> cannot trade
        last = (ts, mid, alpha_pool)
        target = book.get(ts)  # (side, score) the strategy wants held now, or None

        keep: List[_OpenSpot] = []
        for pos in open_:
            if target is not None and target[0] == pos.side:
                keep.append(pos)              # still wanted -> hold
            else:
                close(pos, ts, mid, alpha_pool, "exit")  # dropped or flipped -> flat out
        open_ = keep

        if ts >= end_ts:
            continue  # past the window: only manage/close what is open, never open new
        held = {p.side for p in open_}
        if target is not None and target[0] not in held and len(open_) < max_pos:
            side = target[0]
            buy = tao_fees.fill_price(mid, 0.0, "buy", alpha_pool)  # impact needs qty; size on mid first
            qty = stake / mid if mid > 0 else 0.0
            if qty > 0:
                buy = tao_fees.fill_price(mid, qty, "buy", alpha_pool)
                open_.append(_OpenSpot(side, qty, ts, buy, tao_fees.swap_fee(qty * buy)))

    for pos in open_:  # window ended with positions open: mark them out at the final priced frame
        if last is not None:
            ts, mid, alpha_pool = last
            close(pos, ts, mid, alpha_pool, "mark")
    return trades


def _spot_code_book(spec: Dict, ds: Dataset, start_ts: int, end_ts: int) -> Dict[int, Tuple[str, float]]:
    """Run the spot strategy and return {ts: (side, score)} for in-window frames. The window
    carries the alpha-in-TAO price, the TAO/USD rate, the derived alpha-in-USD price and the TAO
    subnet features, so signals() can trade and report in either denomination (§C mechanisms)."""
    from app import sandbox
    frames = [(ts, fr) for ts, fr in ds.frames if start_ts <= ts < end_ts]
    window = _spot_window(spec["market"], frames)
    freedata.enrich(spec, window)  # as-of join requested free external data into frame["external"]
    if spec.get("params") is not None:
        window["params"] = spec["params"]  # frozen research-fit model
    try:
        raw = sandbox.run_strategy_signals(spec["code"], window, data_dir=None)
    except sandbox.SandboxError as e:
        logging.getLogger(__name__).warning("spot code strategy sandbox failure: %s", e)
        return {}
    return _parse_spot_book(raw, frames)


def _spot_window(market: str, frames: List[Tuple[int, Dict]]) -> Dict:
    """The signals(window) / fit(window) input for a continuous-price (spot) market."""
    return {"market": market, "kind": "spot", "frames": [
        {"ts": ts, "alpha_tao": fr["alpha_tao"], "tao_usd": fr["tao_usd"],
         "alpha_usd": fr["alpha_usd"], "features": fr["features"]}
        for ts, fr in frames]}


def _parse_spot_book(raw, frames) -> Dict[int, Tuple[str, float]]:
    """Validate untrusted sandbox output into {ts: (side, score)}. Element i is the book wanted at
    frame i: a list of {"side": "long"|"short", "score": float?}; the first valid long/short pick
    wins (one position per series). Empty/flat -> no entry for that ts. Short is dropped unless
    SPOT_ALLOW_SHORT. Any shape violation -> {} (no trades), same contract as _parse_book."""
    if not isinstance(raw, list) or len(raw) != len(frames):
        return {}
    book: Dict[int, Tuple[str, float]] = {}
    for (ts, _fr), picks in zip(frames, raw):
        if not isinstance(picks, list):
            return {}
        chosen: Optional[Tuple[str, float]] = None
        for p in picks:
            if not isinstance(p, dict):
                return {}
            side, score = p.get("side"), p.get("score", 0.0)
            if side not in SPOT_SIDES:
                return {}
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                return {}
            if side == "short" and not SPOT_ALLOW_SHORT:
                continue  # on-chain short does not exist; stub only
            if chosen is None:
                chosen = (side, float(score))
        if chosen is not None:
            book[ts] = chosen
    return book


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


# Fixed, economically-meaningful regime cuts for conditional-edge attribution. They are NOT a
# tunable grid: the price bands come straight from the documented Kalshi favorite-longshot bias
# (Bürgi-Deng-Whelan: cheap "longshot" contracts are where takers systematically overpay), side
# captures a yes/no asymmetry, and the ET session captures the time-of-day participation regime.
# Keeping the cuts few and fixed is deliberate - it points the agent at a real mechanism, not at
# a fishing grid over in-sample noise.
_PRICE_BANDS = (("longshot_lt15c", 0.15), ("mid_15_85c", 0.85), ("favorite_gt85c", 1.01))
_SESSIONS = (("asia_overnight_0_7", 0, 8), ("eu_us_open_8_12", 8, 13),
             ("us_afternoon_13_16", 13, 17), ("us_evening_17_23", 17, 24))


def _price_band(price: float) -> str:
    for name, hi in _PRICE_BANDS:
        if price < hi:
            return name
    return _PRICE_BANDS[-1][0]


def _session(entry_ts: int) -> str:
    hour = datetime.fromtimestamp(entry_ts, tz=timezone.utc).astimezone(NEW_YORK).hour
    for name, lo, hi in _SESSIONS:
        if lo <= hour < hi:
            return name
    return _SESSIONS[0][0]


def attribution(trades: List[Trade]) -> Dict:
    """Where a trade list's net edge concentrates, sliced by a few FIXED regimes (entry-price
    band, yes/no side, ET session). Each bucket reports {mean_net, n}: mean per-trade NET return
    = pnl / (qty * entry_price) - the SAME quantity the gatekeeper scores, so the research hint
    the agent sees is on the same footing as the held-out verdict it will later be judged on.

    Research-only: this runs on the leak-free research fold (research_fold_metrics), which the
    generator may inspect freely; it never touches validation/holdout. It changes no gate - it
    only sharpens which CONDITIONAL mechanism the agent proposes next (durable BTC-binary edge is
    conditional, per the design). Empty/zero-cost trades are skipped; an empty list -> {}."""
    cuts = {"price": {}, "side": {}, "session": {}}

    def add(group: str, key: str, ret: float) -> None:
        b = cuts[group].setdefault(key, [0.0, 0])
        b[0] += ret
        b[1] += 1
    for t in trades:
        cost = getattr(t, "capital_at_risk", t.qty * t.entry_price)
        if cost <= 0:
            continue
        ret = t.pnl / cost
        add("price", "continuous_price" if hasattr(t, "capital_at_risk") else _price_band(t.entry_price), ret)
        add("side", t.side, ret)
        add("session", _session(t.entry_ts), ret)
    return {group: {k: {"mean_net": round(s / n, 4), "n": n} for k, (s, n) in buckets.items()}
            for group, buckets in cuts.items() if buckets}


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
            if market.source == "ticks":
                from app import research_repository as rr
                from app import tick_dataset
                contracts = rr.partition_contracts(cur, market, since)
                return tick_dataset.load_window(market, contracts, 0, 2 ** 62)
            if market.kind == "perpetual":
                from app.kalshi_perps_repository import load_history
                from app.kalshi_perps_backtest import build_dataset as build_perpetual_dataset
                utc_since = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since
                return build_perpetual_dataset(market, load_history(cur, market, int(utc_since.timestamp())))
            h = repo.load_history(cur, market.series, market.candle_minutes, since, market.underlying,
                                  cross=cross_product(market))
    finally:
        conn.close()
    frame_series, applies = station_frame_series(market)
    return build_dataset(market, h["markets"], h["candles"], h["btc"], h.get("micro"), frame_series, applies,
                         forecast_book(market, since), cross=h.get("cross"))


def station_frame_series(market: Market) -> Tuple[Optional[Dict[str, List[Tuple[int, float]]]],
                                                   Optional[Callable[[str, int], bool]]]:
    """(frame_series, frame_series_applies) for build_dataset: a weather series' settlement-station
    readings, attached only on each contract's settling day. (None, None) for every other market.
    Every loader (research, and the gated validation/holdout windows) uses this, so a rule never
    sees a feature in research that the gate's window lacks."""
    if market.series not in WEATHER_STATIONS:
        return None, None
    return (freedata.station_observations(WEATHER_STATIONS[market.series]),
            lambda ticker, ts: weather_obs_applies(market.series, ticker, ts))


def forecast_book(market: Market, since: datetime):
    """The window's external fair-value book: issued NWS forecasts for a weather series, collected
    sportsbook odds for an NBA/NHL game series, the Deribit options surface and Polymarket's prices
    for a Bitcoin strike series (app.fair_books.combine), else None. None too if unreadable: the features are then absent, and a rule needing
    them simply never enters."""
    if market.series in options_fair.SERIES:
        from app.adapters.polymarket import features as polymarket
        from app.fair_books import combine
        try:
            opt = options_fair.book_for_series(market.series, lambda: options_fair.load_book(since))
        except Exception as e:  # noqa: BLE001 - S3 outage/no history: the opt_* features are absent
            print("[backtest] options surface unavailable for %s: %r" % (market.key, e), flush=True)
            opt = None
        try:
            pm = polymarket.book_for_series(market.series, lambda: polymarket.load_book(market.series, since))
        except Exception as e:  # noqa: BLE001 - S3 outage/no history: the pm_* features are absent
            print("[backtest] polymarket quotes unavailable for %s: %r" % (market.key, e), flush=True)
            pm = None
        return combine(opt, pm)
    if market.series not in WEATHER_STATIONS and market.series not in sports_odds.SPORTS:
        return None
    from app import repository as repo
    from data_pipeline.common import get_db_conn
    try:
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                if market.series in sports_odds.SPORTS:
                    return sports_odds.book_for_series(market.series, lambda sport: repo.load_sports_odds(
                        cur, sport, since - timedelta(days=sports_odds.MAX_AGE_MIN / 1440.0 + 1)))
                early = since - timedelta(days=weather_fcst.BIAS_DAYS * 2)
                return weather_fcst.book_for_series(
                    market.series,
                    lambda station, kind: repo.load_weather_forecasts(cur, station, kind, early.date()),
                    lambda series: repo.load_weather_actuals(cur, series, early))
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - a missing table/outage must not fail the research run
        print("[backtest] external fair-value data unavailable for %s: %r" % (market.key, e), flush=True)
        return None


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


def _unfit_reason(feats: List[str], present: Dict[str, int], n_labelled: int,
                  n_usable: int, nclass: int) -> str:
    """Concrete reason a learned model was left unfitted: name the binding cause (a feature that
    is null on most research rows, or only one settlement class, or just a thin sample)."""
    if nclass < 2 and n_usable >= MIN_FIT_SAMPLES:
        return "only one settlement class across %d labelled research rows" % n_usable
    if feats and n_labelled:
        worst = min(feats, key=lambda nm: present.get(nm, 0))
        null_pct = round(100 * (1 - present[worst] / n_labelled))
        if present[worst] < n_labelled:
            return ("feature '%s' is null in ~%d%% of research rows (only %d usable labelled rows, "
                    "need %d)" % (worst, null_pct, n_usable, MIN_FIT_SAMPLES))
    return "only %d usable labelled research rows (need %d)" % (n_usable, MIN_FIT_SAMPLES)


def fit_spec_on_research(spec: Dict, ds: Dataset, diag: Optional[Dict] = None) -> Dict:
    """FREEZE a learned model's coefficients, fit on the RESEARCH dataset `ds`. For a gbm/code/
    already-fitted spec this is a no-op (returns the spec unchanged). For an unfitted logistic/
    calibration spec it builds the (features, settlement) training set from every tradable snapshot
    in `ds` and fits P(YES) with a ridge logistic (stats.fit_logistic), returning a NEW spec with
    model.coef/model.intercept filled in.

    This is the one place model fitting happens, and it happens ONLY on research data (§B.4): the
    returned frozen spec is what gets pre-registered and what the gatekeeper later scores on the
    untouched validation/holdout windows - no re-fitting there, so no leak. Too few labelled rows
    (or a fit error) leaves the spec unfitted; fair_yes then returns None (no trades) and the gate
    fails it honestly rather than trading a model fit on nothing.

    If `diag` (a dict) is passed, it is filled in place with WHY the fit went the way it did -
    per-feature non-null coverage, labelled/usable row counts, and a human `reason` string that is
    non-empty only when the model was left unfitted. Pure observability: it never changes the fit
    itself or when a model is left unfitted (still research-only, still frozen)."""
    from app import spec as specmod
    from app import stats
    if not specmod.is_learned_model(spec) or specmod.is_fitted(spec):
        return spec
    m = spec["model"]
    calibration = m.get("kind") == "calibration"
    feats = m.get("features") or (["mid"] if calibration else [])
    X: List[List[float]] = []
    y: List[float] = []
    n_labelled = 0
    present = {name: 0 for name in feats}  # non-null count per required feature, labelled rows only
    for _ts, snaps in ds.frames:
        for s in snaps:
            result = ds.results.get(s.contract.ticker)
            if result not in ("yes", "no"):
                continue
            n_labelled += 1
            f = s.features
            if calibration:
                mid = f.get("mid")
                present["mid"] += mid is not None
                if mid is None:
                    continue
                row = [specmod._logit(mid)]
            else:
                vals = [f.get(name) for name in feats]
                for name, v in zip(feats, vals):
                    present[name] += v is not None
                if any(v is None for v in vals):
                    continue
                row = [float(v) for v in vals]
            X.append(row)
            y.append(1.0 if result == "yes" else 0.0)

    nclass = len(set(y))
    if diag is not None:
        diag.update(n_labelled=n_labelled, n_usable=len(X), min_fit=MIN_FIT_SAMPLES,
                    coverage={nm: round(present[nm] / n_labelled, 3) if n_labelled else 0.0
                              for nm in feats})
    if len(X) < MIN_FIT_SAMPLES or nclass < 2:
        reason = _unfit_reason(feats, present, n_labelled, len(X), nclass)
        if diag is not None:
            diag["reason"] = reason
        logging.getLogger(__name__).info("learned model (%s) left unfitted: %s", m.get("kind"), reason)
        return spec
    try:
        coef, intercept = stats.fit_logistic(X, y)
    except (ValueError, ZeroDivisionError) as e:
        logging.getLogger(__name__).warning("learned model fit failed (%s); left unfitted", e)
        return spec
    fitted = copy.deepcopy(spec)
    fitted["model"]["coef"] = [float(c) for c in coef]
    fitted["model"]["intercept"] = float(intercept)
    # Re-validate so an absurd fit (NaN/inf/over the coef cap) is caught now, not at trade time.
    try:
        return specmod.validate(fitted)
    except specmod.SpecError as e:
        logging.getLogger(__name__).warning("fitted model failed validation (%s); left unfitted", e)
        return spec


def zero_trade_reason(spec: Dict, ds: Dataset) -> str:
    """Why a (fitted/pure-rule) spec took 0 trades on the research fold: the ONE entry constraint
    that selects ~0 rows - its binding constraint - so the develop loop gets a concrete reason
    instead of 'coef:[]/0 trades'. Counts each gate's pass rate independently over all snapshots
    and names the tightest. Observability only; it never changes a trade or a trial."""
    from app import spec as specmod
    if specmod.is_perpetual_spec(spec):
        return ("0 trades: " + ds.last_rejection if getattr(ds, "last_rejection", None) else
                "0 trades: no perpetual rule signal with a complete lookback, funding coverage and next-bar fill.")
    if specmod.is_code_spec(spec):
        return "0 trades: the code strategy's signals(window) fired no entry on the research fold"
    e = spec["entry"]
    n = tte = spread = fair = 0
    filt = [0] * len(e["filters"])
    for _ts, snaps in ds.frames:
        for s in snaps:
            f = s.features
            n += 1
            if e["min_tte_min"] <= f.get("tte_min", -1) <= e["max_tte_min"]:
                tte += 1
            if f.get("spread", 1e9) <= e["max_spread"]:
                spread += 1
            for i, flt in enumerate(e["filters"]):
                if specmod._passes(flt, f):
                    filt[i] += 1
            if specmod.fair_yes(spec, f) is not None:
                fair += 1
    if n == 0:
        return "0 trades: the research fold has no tradable snapshots"
    gates = [("time-to-expiry window [%g,%g]min" % (e["min_tte_min"], e["max_tte_min"]), tte),
             ("max_spread<=%g" % e["max_spread"], spread),
             ("model fair-value available", fair)]
    for i, flt in enumerate(e["filters"]):
        gates.append(("%s%s%g" % (flt["feature"], flt["op"], flt["value"]), filt[i]))
    label, cnt = min(gates, key=lambda g: g[1])
    pct = round(100 * cnt / n)
    if cnt == 0:
        return "0 trades: no research row satisfies %s (binding constraint; 0 of %d rows)" % (label, n)
    if cnt < 0.02 * n:
        return ("0 trades: %s selects only %d of %d rows (~%d%%), the binding constraint"
                % (label, cnt, n, pct))
    return ("0 trades: every entry gate passes rows (tightest is %s at ~%d%%), so min_edge=%g clears "
            "on no row after fees - loosen the edge/price band or rethink the mechanism, not the gates"
            % (label, pct, e["min_edge"]))


def feature_coverage(ds: Dataset) -> Dict[str, int]:
    """Non-null coverage (% of research snapshots) for every known feature on THIS market, so the
    proposer only reaches for features the market actually populates. Micro features (ob_imbalance,
    trade flow) are null on markets whose feed never carried them (sports, NEAR).
    # ponytail: full scan over FEATURES x snapshots, once per research prompt; fine at research
    # dataset sizes, revisit if prompt-building ever shows up hot."""
    from app.markets import FEATURES
    if ds.market.kind == "perpetual":
        rows = [frame for _, frame in ds.frames]
        if not rows:
            return {}
        keys = {key for frame in rows for key in frame.get("features", {})}
        return {key: round(100 * sum(frame.get("features", {}).get(key) is not None for frame in rows) / len(rows))
                for key in sorted(keys)}
    n = 0
    present = {name: 0 for name in FEATURES}
    for _ts, snaps in ds.frames:
        for s in snaps:
            n += 1
            f = s.features
            for name in FEATURES:
                if f.get(name) is not None:
                    present[name] += 1
    return {name: round(100 * c / n) for name, c in present.items()} if n else {}


def feature_ranges(ds: Dataset, max_samples: int = 20000) -> Dict[str, List[float]]:
    """[p10, p50, p90] of every populated numeric feature on THIS market's snapshots (an evenly
    strided sample of at most max_samples), so the proposer sets filter cuts where the data lives:
    run 2563 asked for fcst_age_h below its 0.5h floor and took 0 trades."""
    from app.markets import FEATURES
    if not ds.frames or ds.market.kind == "perpetual":
        return {}
    total = sum(len(snaps) for _ts, snaps in ds.frames)
    stride = max(1, total // max_samples)
    vals: Dict[str, List[float]] = {}
    i = 0
    for _ts, snaps in ds.frames:
        for sn in snaps:
            i += 1
            if i % stride:
                continue
            for name, v in sn.features.items():
                if name in FEATURES and isinstance(v, (int, float)) and math.isfinite(v):
                    vals.setdefault(name, []).append(float(v))
    out = {}
    for name, xs in sorted(vals.items()):
        xs.sort()
        out[name] = [float("%.3g" % xs[min(len(xs) - 1, int(q * len(xs)))]) for q in (0.1, 0.5, 0.9)]
    return out


def research_fold_trades(spec: Dict, ds: Dataset, embargo_seconds: int, n_splits: int = 4,
                         what_if: Optional[WhatIf] = None) -> List[Trade]:
    """The trades research_fold_metrics scores: simulate the spec across the whole Research window,
    keep only the pooled PURGED walk-forward test folds (stats.purged_walkforward_splits), ordered
    by entry. Too few trades to split -> every trade. Research data only, so free to inspect."""
    from app import stats
    trades = sorted(simulate(spec, ds, ds.start_ts, ds.end_ts + 1, what_if), key=lambda t: t.entry_ts)
    if not trades:
        return []
    splits = stats.purged_walkforward_splits([t.entry_ts for t in trades],
                                             [t.exit_ts for t in trades], n_splits, embargo_seconds)
    test_idx = sorted({i for sp in splits for i in sp["test_idx"]})
    return [trades[i] for i in test_idx] if test_idx else trades


def research_fold_metrics(spec: Dict, ds: Dataset, embargo_seconds: int,
                          n_splits: int = 4, what_if: Optional[WhatIf] = None) -> Dict:
    """In-research "OOS" metrics via a PURGED walk-forward split (Lopez de Prado) instead of a
    single 70/30 cut: simulate the spec across the whole Research window, then score it only on
    the pooled test folds. stats.purged_walkforward_splits drops train frames that settle into
    (purge) or run up to (embargo) a test block, so the fold is leak-free WITHIN Research — the
    agent may look at it freely. Returns {"capital", "in_sample": metrics} mirroring evaluate()."""
    stake = (what_if.stake if what_if and what_if.stake is not None else spec["sizing"]["stake"])
    capital = stake * spec["sizing"]["max_positions"]
    fold = research_fold_trades(spec, ds, embargo_seconds, n_splits, what_if)
    span = (fold[-1].exit_ts - fold[0].entry_ts) / 86400.0 if fold else (ds.end_ts - ds.start_ts) / 86400.0
    m = metrics(fold, capital, max(span, 1e-9))
    m.pop("_curve", None)
    return {"capital": capital, "in_sample": m, "attribution": attribution(fold)}
