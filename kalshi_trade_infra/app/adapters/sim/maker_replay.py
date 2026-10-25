"""Replay a passive market maker over the tick archive and score it on rewards plus trading P&L.

    python -m app.adapters.sim.maker_replay --series KXCRYPTOLEAD15M --start 2026-10-25T10 --end 2026-10-25T16
    python -m app.adapters.sim.maker_replay --series KXBTCD --start ... --pool-per-hour 10   # what-if pool

Each second of the window: every resting-liquidity reward program live on a replayed contract
pays its snapshot share (pricing.depth_rewards, our virtual size counted in the book), then the
QuotingLoop re-decides its quotes from the replayed touch. Books and prints come from
TickStore (kalshi_book / kalshi_trades); fills from QueueReplayVenue's queue model. Programs come
from the LIP snapshots data_pipeline.lip_programs writes (every snapshot overlapping the window),
or from ``--pool-per-hour`` for a hypothetical pool on every contract.

At the end every open position is marked at its contract's last mid (a contract that closed in the
window sits at ~0 or ~1 by then). Reported: rewards, trading P&L, fills, peak collateral, and both
per contract.
"""
from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.adapters.sim.queue_replay import QueueReplayVenue
from trading_core.domain import BinaryTerms, Instrument, InstrumentId, InstrumentKind, Portfolio, Quote
from trading_core.engine.quoting import MakerConfig, QuotingLoop, net_yes
from trading_core.pricing.depth_rewards import DepthRewardTerms, snapshot_reward

NS = 1_000_000_000
MAKER_RATE = 0.0175


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
                 fees: Optional[MakerFees] = None, decide_every_s: int = 1) -> None:
        self.series, self.cfg = list(series), cfg
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
        quotes, secs_to_close, rewarded = {}, {}, set()
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
                rewarded.add(yid)
            quotes[yid] = Quote(yid, float(sec), by, ask, v.books[t]["yes"].get(by), v.books[t]["no"].get(bn))
            close = self.close_ts.get(t)
            if close:
                secs_to_close[yid] = close - sec
        if sec % self.decide_every_s == 0:
            earned = {InstrumentId("kalshi", t, "yes"): r for t, r in self.rewards.items()}
            fills = self.loop.step(float(sec), quotes, secs_to_close=secs_to_close, rewarded=rewarded,
                                   earned=earned).fills
        else:
            fills = self.loop.book_fills()
        self.fills += len(fills)
        self.filled_qty += sum(f.qty for f in fills)
        collateral = sum(o.qty * o.price for o in v.open_orders())
        for iid, pos in self.book.open_positions().items():
            collateral += abs(pos.qty) * pos.avg_price
        self.peak_collateral = max(self.peak_collateral, collateral)
        for yid in quotes:
            self.max_abs_inventory = max(self.max_abs_inventory, abs(net_yes(self.book.positions, yid)))

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
            book = store.read("kalshi_book", h, he)
            trades = store.read("kalshi_trades", h, he)
            book = _only_series(book, self.series)
            trades = _only_series(trades, self.series)
            if book is None:
                continue
            ev: List[tuple] = []
            index: Dict[Tuple[str, str, float], List[int]] = defaultdict(list)
            if trades is not None:
                for r, k, px, c, s in zip(trades["rt"].to_pylist(), trades["ticker"].to_pylist(),
                                          trades["yes_price"].to_pylist(), trades["count"].to_pylist(),
                                          trades["taker_side"].to_pylist()):
                    if c is None or px is None or s not in ("yes", "no"):
                        continue
                    ev.append((r, 0, k, s, float(px), float(c)))
                    ladder = "yes" if s == "no" else "no"
                    index[(k, ladder, round(px if ladder == "yes" else 1 - px, 4))].append(r)
            subcent = set()
            for r, k, kind, side, px, q in zip(book["rt"].to_pylist(), book["ticker"].to_pylist(),
                                               book["kind"].to_pylist(), book["side"].to_pylist(),
                                               book["price"].to_pylist(), book["qty"].to_pylist()):
                ev.append((r, 1, k, kind, side, px, q or 0.0))
                if px is not None and abs(px * 100 - round(px * 100)) > 1e-6:
                    subcent.add(k)
            ev.sort(key=lambda e: (e[0], e[1]))
            self.venue.set_trade_index({k: sorted(v) for k, v in index.items()})
            tickers = sorted({e[2] for e in ev})
            for t in tickers:
                self._instrument(t, 0.001 if t in subcent else 0.01)
            cur = int(h.timestamp())
            for e in ev:
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

    def report(self) -> dict:
        late = self.loop.book_fills()
        self.fills += len(late)
        self.filled_qty += sum(f.qty for f in late)
        marks = {}
        for t, m in self.last_mid.items():
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
                "per_contract": {t: {k: round(v, 2) if isinstance(v, float) else v for k, v in d.items()}
                                 for t, d in sorted(per.items(), key=lambda kv: -(kv[1]["reward"] + kv[1]["pnl"]))}}


def _only_series(t, series: Sequence[str]):
    if t is None or t.num_rows == 0:
        return None
    import pyarrow.compute as pc
    mask = None
    for s in series:
        m = pc.starts_with(t["ticker"], s + "-")
        mask = m if mask is None else pc.or_(mask, m)
    t = t.filter(mask)
    return t if t.num_rows else None


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
