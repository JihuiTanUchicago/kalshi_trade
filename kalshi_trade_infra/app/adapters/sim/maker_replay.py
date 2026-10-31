"""Replay a passive market maker over the tick archive and score it on rewards plus trading P&L.

    python -m app.adapters.sim.maker_replay --series KXCRYPTOLEAD15M --start 2026-10-25T10 --end 2026-10-25T16
    python -m app.adapters.sim.maker_replay --series KXBTCD --start ... --pool-per-hour 10   # what-if pool

Each second of the window: every resting-liquidity reward program live on a replayed contract
pays its snapshot share (pricing.depth_rewards, our virtual size counted in the book), then the
QuotingLoop re-decides its quotes from the replayed touch. Books and prints come from
TickStore (kalshi_book / kalshi_trades); fills from QueueReplayVenue's queue model. Programs come
from the LIP snapshots data_pipeline.lip_programs writes (every snapshot overlapping the window),
or from ``--pool-per-hour`` for a hypothetical pool on every contract.

At the end every open position is marked at its contract's settlement when ``results`` has it
(fetch_results), else at its last mid (a contract that closed in the window sits near 0 or 1). Reported: rewards, trading P&L, fills, peak collateral, and both
per contract.

Policy inputs from the per-second feature table (features_1s), read only when the config needs them:
``fair_source`` "spot" prices a single-strike contract at Phi(dist_sigma_comp) (the spot-implied
probability), "micro" at the book's microprice; ``MakerConfig.pull_move_bp`` reads the underlying's
return over ``move_window_s`` (1, 10 or 60 s). Every fill is also marked out: the mid ``MARKOUTS``
seconds later (the settlement value or last mid if the contract closed first) minus the price paid,
fees included. Markouts and rewards are bucketed by UTC hour (``report()["hours"]``) so a researched
policy is judged with the hour as the independent unit.
"""
from __future__ import annotations

import argparse
import gzip
import heapq
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pyarrow.compute as pc

from app.adapters.sim.queue_replay import QueueReplayVenue
from trading_core.domain import BinaryTerms, Instrument, InstrumentId, InstrumentKind, Portfolio, Quote
from trading_core.engine.quoting import MakerConfig, QuotingLoop, net_yes
from trading_core.pricing.depth_rewards import DepthRewardTerms, snapshot_reward

NS = 1_000_000_000
MAKER_RATE = 0.0175
MARKOUTS = (10, 60)
FAIR_SOURCES = ("mid", "micro", "spot")
MOVE_WINDOWS = {1: "spot_ret_1s", 10: "spot_ret_10s", 60: "spot_ret_60s"}


class MakerFees:
    """Kalshi's maker fee (0.0175 * C * P * (1-P), per fill here) only on series that charge makers
    (fee_type quadratic_with_maker_fees); the crypto series are fee_type quadratic: no maker fee."""

    def __init__(self, charged_series: Iterable[str] = ()) -> None:
        self.charged = set(charged_series)

    def fee(self, instrument: Instrument, qty: float, price: float, maker: bool = False) -> float:
        if not maker or instrument.series not in self.charged:
            return 0.0
        return MAKER_RATE * abs(qty) * price * (1 - price)


def _utc(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _hours(a: datetime, b: datetime):
    h = a.replace(minute=0, second=0, microsecond=0)
    while h < b:
        yield h
        h += timedelta(hours=1)


def load_programs(s3, bucket: str, prefix: str, start: datetime, end: datetime) -> List[dict]:
    """Every liquidity program seen in any LIP snapshot from the day before start through end."""
    seen: Dict[str, dict] = {}
    day = (start - timedelta(days=1)).date()
    while day <= end.date():
        base = f"{prefix}/v1/lip_programs/date={day:%Y-%m-%d}/"
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=base):
            for obj in page.get("Contents") or []:
                doc = json.loads(gzip.decompress(s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()))
                for st in ("active", "upcoming"):
                    for p in doc.get("programs", {}).get(st) or []:
                        seen[p["id"]] = p
        day += timedelta(days=1)
    return list(seen.values())


def program_terms(p: dict, tick: float = 0.01) -> DepthRewardTerms:
    def ts(s):
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    return DepthRewardTerms(pool=float(p["period_reward"]) / 10_000, start=ts(p["start_date"]), end=ts(p["end_date"]),
                            target_size=float(p.get("target_size_fp") or 0) or 1.0,
                            discount_per_tick=(p.get("discount_factor_bps") or 5000) / 10_000, tick=tick)


def _in_series(ticker: str, series: Sequence[str]) -> bool:
    return ticker.split("-")[0] in series


class MakerReplay:
    def __init__(self, series: Sequence[str], cfg: MakerConfig, programs: Sequence[dict] = (),
                 pool_per_hour: Optional[float] = None, target_size: float = 300.0,
                 fees: Optional[MakerFees] = None, decide_every_s: int = 1, tickers_from_markets: bool = False,
                 fair_source: str = "mid", move_window_s: int = 10) -> None:
        """``tickers_from_markets``: read only the book rows of contracts kalshi_markets listed in the
        two hours before each replayed hour (a fraction of the memory; fine for short-dated series)."""
        if fair_source not in FAIR_SOURCES:
            raise ValueError("fair_source must be one of %s" % (FAIR_SOURCES,))
        if move_window_s not in MOVE_WINDOWS:
            raise ValueError("move_window_s must be one of %s" % (sorted(MOVE_WINDOWS),))
        self.series, self.cfg = list(series), cfg
        self.fair_source, self.move_window_s = fair_source, move_window_s
        # The hour's features as one row per ticker and one column per second (a dict of per-second
        # tuples took ~750 MB for a KXBTCD hour): ticker -> row, first second, fair[row, s], move bp[row, s].
        self.feat_row: Dict[str, int] = {}
        self.feat_t0 = 0
        self.feat_fair = np.empty((0, 0))
        self.feat_move = np.empty((0, 0))
        self.pending: Dict[str, List[list]] = defaultdict(list)   # ticker -> [due sec, horizon, hour, outcome, price, qty, fee]
        self.hours: Dict[int, dict] = defaultdict(_hour_row)
        self.tickers_from_markets = tickers_from_markets
        self.pool_per_hour, self.target_size = pool_per_hour, target_size
        self.decide_every_s = max(1, int(decide_every_s))
        self.instruments: Dict[InstrumentId, Instrument] = {}
        self.venue = QueueReplayVenue(fees=fees or MakerFees(), instruments=self.instruments)
        self.book = Portfolio()
        self.loop = QuotingLoop(self.venue, self.instruments, cfg, book=self.book, strategy_id="lip-maker")
        self.programs: Dict[str, List[dict]] = defaultdict(list)
        for p in programs:
            if _in_series(p.get("market_ticker") or "", self.series):
                self.programs[p["market_ticker"]].append(p)
        self.terms: Dict[str, List[DepthRewardTerms]] = {}
        self.close_ts: Dict[str, int] = {}
        self.last_mid: Dict[str, float] = {}
        self.rewards: Dict[str, float] = defaultdict(float)
        self.reward_s: Dict[str, int] = defaultdict(int)
        self.peak_collateral = 0.0
        self.max_abs_inventory = 0.0
        self.fills = 0
        self.filled_qty = 0.0

    # --- instruments and programs --------------------------------------------------------------
    def _instrument(self, ticker: str, tick: float) -> InstrumentId:
        yid = InstrumentId("kalshi", ticker, "yes")
        if yid not in self.instruments:
            close = self.close_ts.get(ticker)
            expiry = datetime.fromtimestamp(close, timezone.utc) if close else datetime(2100, 1, 1, tzinfo=timezone.utc)
            inst = Instrument(yid, InstrumentKind.BINARY, tick_size=tick, series=ticker.split("-")[0],
                              terms=BinaryTerms(expiry=expiry))
            self.instruments[yid] = inst
            self.instruments[inst.complement().id] = inst.complement()
            if self.pool_per_hour:
                self.terms[ticker] = [DepthRewardTerms(pool=self.pool_per_hour, start=0, end=3600,
                                                       target_size=self.target_size, tick=tick)]
            else:
                self.terms[ticker] = [program_terms(p, tick) for p in self.programs.get(ticker, [])]
        return yid

    def _active_terms(self, ticker: str, sec: int) -> Optional[DepthRewardTerms]:
        for t in self.terms.get(ticker) or ():
            if self.pool_per_hour or t.active(sec):
                return t
        return None

    # --- one second ----------------------------------------------------------------------------
    def _second(self, sec: int, tickers: Sequence[str]) -> None:
        v = self.venue
        quotes, secs_to_close, rewarded, fairs = {}, {}, set(), {}
        for t in tickers:
            by, bn = v.best(t, "yes"), v.best(t, "no")
            if by is None or bn is None or by + bn >= 1.0:
                continue
            yid = InstrumentId("kalshi", t, "yes")
            if yid not in self.instruments:
                continue
            ask = round(1.0 - bn, 4)
            self.last_mid[t] = (by + ask) / 2
            terms = self._active_terms(t, sec)
            if terms is not None:
                r = snapshot_reward(v.ladder(t, "yes"), v.ladder(t, "no"), v.ours(t, "yes"), v.ours(t, "no"), terms)
                if r > 0:
                    self.rewards[t] += r
                    self.reward_s[t] += 1
                    self.hours[_hour(sec)]["reward"] += r
                rewarded.add(yid)
            fair, move = self.features_at(t, sec)
            if fair is not None:
                fairs[yid] = fair
            quotes[yid] = Quote(yid, float(sec), by, ask, v.books[t]["yes"].get(by), v.books[t]["no"].get(bn),
                                features={} if move is None else {"spot_move_bp": move})
            self._resolve(t, sec, self.last_mid[t])
            close = self.close_ts.get(t)
            if close:
                secs_to_close[yid] = close - sec
        if sec % self.decide_every_s == 0:
            earned = {InstrumentId("kalshi", t, "yes"): r for t, r in self.rewards.items()}
            fills = self.loop.step(float(sec), quotes, fair=fairs, secs_to_close=secs_to_close, rewarded=rewarded,
                                   earned=earned).fills
        else:
            fills = self.loop.book_fills()
        self._track(fills, sec)
        self.fills += len(fills)
        self.filled_qty += sum(f.qty for f in fills)
        collateral = sum(o.qty * o.price for o in v.open_orders())
        for iid, pos in self.book.open_positions().items():
            collateral += abs(pos.qty) * pos.avg_price
        self.peak_collateral = max(self.peak_collateral, collateral)
        for yid in quotes:
            self.max_abs_inventory = max(self.max_abs_inventory, abs(net_yes(self.book.positions, yid)))

    # --- policy inputs and markouts -------------------------------------------------------------
    def _load_features(self, store, h: datetime, he: datetime, tickers) -> None:
        """(fair, underlying move in bp) per (ticker, second) of the hour from features_1s."""
        cols = ["sec", "ticker", "strike_lo", "strike_hi", "dist_sigma", "dist_sigma_comp", "microprice",
                MOVE_WINDOWS[self.move_window_s]]
        f = store.features_1s(h, he, tickers=tickers, series=None if tickers else self.series, columns=cols)
        self.feat_row, self.feat_fair, self.feat_move = {}, np.empty((0, 0)), np.empty((0, 0))
        if not f or "sec" not in f or not len(f["sec"]):
            return
        sec = np.asarray(f["sec"], dtype=np.int64)
        n = len(sec)

        def col(name):
            return np.asarray(f[name], dtype=float) if name in f else np.full(n, np.nan)

        if self.fair_source == "micro":
            fair = col("microprice")
        elif self.fair_source == "spot":
            d = col("dist_sigma_comp")
            d = np.where(np.isnan(d), col("dist_sigma"), d)
            single = np.isnan(col("strike_lo")) != np.isnan(col("strike_hi"))
            fair = np.full(n, np.nan)
            ok = single & np.isfinite(d)
            fair[ok] = [0.5 * (1.0 + math.erf(x / math.sqrt(2.0))) for x in d[ok]]
        else:
            fair = np.full(n, np.nan)
        move = col(MOVE_WINDOWS[self.move_window_s]) * 1e4
        names, row = np.unique(np.asarray(f["ticker"], dtype=object), return_inverse=True)
        self.feat_t0 = int(sec.min())
        off = sec - self.feat_t0
        self.feat_fair = np.full((len(names), int(off.max()) + 1), np.nan)
        self.feat_move = np.full_like(self.feat_fair, np.nan)
        self.feat_fair[row, off] = fair
        self.feat_move[row, off] = move
        self.feat_row = {t: i for i, t in enumerate(names.tolist())}

    def features_at(self, ticker: str, sec: int) -> Tuple[Optional[float], Optional[float]]:
        """(fair, move bp) of ``ticker`` at ``sec``; None where the hour's features have no value."""
        r = self.feat_row.get(ticker)
        k = int(sec) - self.feat_t0
        if r is None or k < 0 or k >= self.feat_fair.shape[1]:
            return None, None
        fair, move = float(self.feat_fair[r, k]), float(self.feat_move[r, k])
        return (None if math.isnan(fair) else fair), (None if math.isnan(move) else move)

    def _track(self, fills, sec: Optional[int]) -> None:
        for f in fills:
            ts = int(f.ts if f.ts is not None else (sec or 0))
            row = self.hours[_hour(ts)]
            row["fills"] += 1
            row["qty"] += f.qty
            row["fees"] += f.fee or 0.0
            row["fee_stress"] += MAKER_RATE * f.qty * f.price * (1 - f.price)   # if the series charged makers
            for hz in MARKOUTS:
                self.pending[f.instrument.symbol].append([ts + hz, hz, _hour(ts), f.instrument.outcome, f.price,
                                                          f.qty, f.fee or 0.0])

    def _resolve(self, ticker: str, sec: Optional[int], yes_mid: float) -> None:
        """Mark out every pending fill on ``ticker`` due by ``sec`` (all of them when sec is None)."""
        todo = self.pending.get(ticker)
        if not todo:
            return
        keep = []
        for p in todo:
            if sec is not None and p[0] > sec:
                keep.append(p)
                continue
            _due, hz, hour, outcome, price, qty, fee = p
            value = yes_mid if outcome == "yes" else 1.0 - yes_mid
            self.hours[hour]["m%d" % hz] += (value - price) * qty - fee
        if keep:
            self.pending[ticker] = keep
        else:
            self.pending.pop(ticker, None)

    # --- replay --------------------------------------------------------------------------------
    def run(self, store, start: datetime, end: datetime) -> dict:
        s0, s1 = int(start.timestamp()), int(end.timestamp())
        for h in _hours(start, end):
            he = h + timedelta(hours=1)
            mk = store.read("kalshi_markets", h - timedelta(hours=2), he)
            if mk is not None:
                for t, c in zip(mk["ticker"].to_pylist(), mk["close_ts"].to_pylist()):
                    if t and c and _in_series(t, self.series):
                        self.close_ts[t] = int(c)
            want = None
            if self.tickers_from_markets:
                want = sorted(t for t in self.close_ts if self.close_ts[t] > h.timestamp())
                if not want:
                    continue
            if self.fair_source != "mid" or self.cfg.pull_move_bp is not None:
                self._load_features(store, h, he, want)
            book = store.read("kalshi_book", h, he, tickers=want)
            trades = store.read("kalshi_trades", h, he, tickers=want)
            book = _only_series(book, self.series)
            trades = _only_series(trades, self.series)
            if book is None:
                continue
            # Book and trade rows stream in time order batch by batch: a busy hour has millions of book
            # rows, and one Python tuple per row for the whole hour ran the timer out of memory.
            book = book.select(["rt", "ticker", "kind", "side", "price", "qty"]).sort_by("rt")
            index: Dict[Tuple[str, str, float], List[int]] = defaultdict(list)
            trade_ev: List[tuple] = []
            if trades is not None:
                for r, k, px, c, s in zip(trades["rt"].to_pylist(), trades["ticker"].to_pylist(),
                                          trades["yes_price"].to_pylist(), trades["count"].to_pylist(),
                                          trades["taker_side"].to_pylist()):
                    if c is None or px is None or s not in ("yes", "no"):
                        continue
                    trade_ev.append((r, 0, k, s, float(px), float(c)))
                    ladder = "yes" if s == "no" else "no"
                    index[(k, ladder, round(px if ladder == "yes" else 1 - px, 4))].append(r)
                trade_ev.sort(key=lambda e: e[0])
            self.venue.set_trade_index({k: sorted(v) for k, v in index.items()})
            tickers = sorted(set(pc.unique(book["ticker"]).to_pylist()) | {e[2] for e in trade_ev})
            subcent = _subcent_tickers(book)
            for t in tickers:
                self._instrument(t, 0.001 if t in subcent else 0.01)
            cur = int(h.timestamp())
            for e in heapq.merge(trade_ev, _book_events(book), key=lambda e: (e[0], e[1])):
                sec = e[0] // NS + 1
                while cur < sec:
                    if s0 < cur <= s1:
                        self._second(cur, tickers)
                    cur += 1
                if e[1] == 0:
                    _, _, k, s, px, c = e
                    self.venue.on_trade(e[0], k, s, px, c)
                    continue
                _, _, k, kind, side, px, q = e
                if kind in (0, 3):
                    if side is None:
                        self.venue.reset_book(k)
                    elif px is not None:
                        self.venue.set_level(k, side, px, q)
                elif kind == 1 and side in ("yes", "no") and px is not None:
                    self.venue.on_delta(e[0], k, side, px, q)
            while cur <= min(int(he.timestamp()), s1):
                if cur > s0:
                    self._second(cur, tickers)
                cur += 1
            print("maker replay %s: fills %d rewards $%.2f" % (h.strftime("%Y-%m-%dT%H"), self.fills,
                                                                sum(self.rewards.values())), flush=True)
        return self.report()

    def report(self, results: Optional[Dict[str, float]] = None) -> dict:
        """``results``: YES settlement value (1.0 / 0.0) per settled ticker; those are marked at it,
        the rest at their last mid."""
        late = self.loop.book_fills()
        self._track(late, None)
        self.fills += len(late)
        self.filled_qty += sum(f.qty for f in late)
        marks = {}
        results = results or {}
        for t in list(self.pending):                 # horizons past the window's end or the close
            m = results.get(t, self.last_mid.get(t))
            if m is not None:
                self._resolve(t, None, m)
        for t in set(self.last_mid) | set(results):
            m = results.get(t, self.last_mid.get(t))
            if m is None:
                continue
            marks[InstrumentId("kalshi", t, "yes")] = m
            marks[InstrumentId("kalshi", t, "no")] = 1 - m
        pnl = self.book.equity(marks)            # starts from cash 0: trading P&L incl. maker fees
        per: Dict[str, dict] = defaultdict(lambda: {"reward": 0.0, "pnl": 0.0, "fees": 0.0, "reward_s": 0})
        for iid, pos in self.book.positions.items():
            d = per[iid.symbol]
            d["pnl"] += pos.realized + pos.unrealized(marks.get(iid)) - pos.fees
            d["fees"] += pos.fees
        for t, r in self.rewards.items():
            per[t]["reward"] += r
            per[t]["reward_s"] = self.reward_s[t]
        rewards = sum(self.rewards.values())
        return {"rewards": round(rewards, 2), "trading_pnl": round(pnl, 2), "total": round(rewards + pnl, 2),
                "fills": self.fills, "filled_qty": self.filled_qty, "peak_collateral": round(self.peak_collateral, 2),
                "max_abs_inventory": self.max_abs_inventory, "stopped_contracts": len(self.loop.stopped),
                "settled_marks": len([t for t in results if t in self.last_mid]),
                "hours": [dict(hour=h, **{k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()})
                          for h, d in sorted(self.hours.items())],
                "markout_per_contract": {"m%d" % hz: round(sum(d["m%d" % hz] for d in self.hours.values())
                                                             / max(self.filled_qty, 1e-9), 5) for hz in MARKOUTS},
                "per_contract": {t: {k: round(v, 2) if isinstance(v, float) else v for k, v in d.items()}
                                 for t, d in sorted(per.items(), key=lambda kv: -(kv[1]["reward"] + kv[1]["pnl"]))}}


def _hour_row() -> dict:
    row = {"reward": 0.0, "fills": 0, "qty": 0.0, "fees": 0.0, "fee_stress": 0.0}
    row.update({"m%d" % hz: 0.0 for hz in MARKOUTS})
    return row


def _hour(sec: int) -> int:
    return int(sec) // 3600 * 3600


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _book_events(book, batch: int = 65536):
    """(rt, 1, ticker, kind, side, price, qty) per book row, converted one batch at a time."""
    for b in book.to_batches(max_chunksize=batch):
        cols = [b.column(i).to_pylist() for i in range(6)]
        for r, k, kind, side, px, q in zip(*cols):
            yield (r, 1, k, kind, side, px, q or 0.0)


def _subcent_tickers(book) -> set:
    """Tickers quoted off whole cents (a 0.1c tick)."""
    px = book["price"]
    cents = pc.multiply(px, 100.0)
    off = pc.greater(pc.abs(pc.subtract(cents, pc.round(cents))), 1e-6)
    return set(pc.unique(pc.filter(book["ticker"], pc.fill_null(off, False))).to_pylist())


def _only_series(t, series: Sequence[str]):
    if t is None or t.num_rows == 0:
        return None
    mask = None
    for s in series:
        m = pc.starts_with(t["ticker"], s + "-")
        mask = m if mask is None else pc.or_(mask, m)
    t = t.filter(mask)
    return t if t.num_rows else None


def fetch_results(tickers: Iterable[str], get=None) -> Dict[str, float]:
    """YES settlement value of every settled ticker, from Kalshi's public GET /markets/{ticker}."""
    from app.trading.settlement import market_settlement
    if get is None:
        from data_pipeline.common import api_get as get
    out: Dict[str, float] = {}
    for t in tickers:
        try:
            m = (get("/markets/%s" % t) or {}).get("market") or {}
        except Exception as e:  # noqa: BLE001 - an unsettled or unknown market falls back to its mid
            print("[maker_replay] result %s: %r" % (t, e), flush=True)
            continue
        settled = market_settlement(m)
        if settled in ("yes", "no"):
            out[t] = 1.0 if settled == "yes" else 0.0
        elif isinstance(settled, float):  # cancelled at a fair price
            out[t] = settled
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--series", required=True, help="comma separated")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--quote-size", type=float, default=100)
    ap.add_argument("--max-inventory", type=float, default=500)
    ap.add_argument("--min-edge", type=float, default=0.0)
    ap.add_argument("--pull-before-close", type=float, default=60)
    ap.add_argument("--improve-min-spread-ticks", type=int, default=0)
    ap.add_argument("--all-contracts", action="store_true", help="quote contracts without a reward program too")
    ap.add_argument("--pool-per-hour", type=float, default=None, help="hypothetical pool per contract-hour")
    ap.add_argument("--target-size", type=float, default=300)
    ap.add_argument("--contract-loss-limit", type=float, default=None,
                    help="bench a contract once rewards + its P&L fall below minus this many dollars")
    ap.add_argument("--max-touch-size", type=float, default=None,
                    help="skip a side whose touch already rests more than this many contracts")
    ap.add_argument("--maker-fee-series", default="", help="series that charge makers (comma separated)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    import boto3
    from data_pipeline.tick_store import BUCKET, PREFIX, TickStore
    series = [s for s in a.series.split(",") if s]
    start, end = _utc(a.start), _utc(a.end)
    programs = [] if a.pool_per_hour else load_programs(boto3.client("s3"), BUCKET, PREFIX, start, end)
    cfg = MakerConfig(quote_size=a.quote_size, max_inventory=a.max_inventory, min_edge=a.min_edge,
                      pull_before_close_s=a.pull_before_close, improve_min_spread_ticks=a.improve_min_spread_ticks,
                      rewarded_only=not a.all_contracts, contract_loss_limit=a.contract_loss_limit,
                      max_touch_size=a.max_touch_size)
    rep = MakerReplay(series, cfg, programs, pool_per_hour=a.pool_per_hour, target_size=a.target_size,
                      fees=MakerFees([s for s in a.maker_fee_series.split(",") if s])).run(TickStore(), start, end)
    text = json.dumps(rep, indent=1)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
    print(json.dumps({k: v for k, v in rep.items() if k != "per_contract"}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
