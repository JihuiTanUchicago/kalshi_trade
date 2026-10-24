"""Execution cost model from recorded top-of-book ticks: what trading a series actually costs.

Our own fills are too few to calibrate a cost model (TCA, app/tca.py, measures them as they come).
The book itself is not: forward_quote_ticks records one row per top-of-book change for every
contract the feed watches. This module replays those ticks and measures, per series:

  Taker (what an IOC entry pays today)
    * spread          time-weighted p50/p90 of the YES touch spread
    * touch size      p50 contracts resting at the ask and at the bid
    * half-spread + fee   the per-contract cost of crossing at the mid-price level
    * touch decay     P(the ask you decided on has moved UP by arrival), for latency L. With the
                      reservation-price cap, a move past the cap is a missed entry, not a worse fill.

  Maker (post at the touch instead of crossing)
    * fill odds       for a buy resting at the best bid for T seconds, bracketed:
                        lower = the ask trades down to our price (sellers must have hit us)
                        upper = the bid drops below our price (our level was consumed or pulled)
    * adverse move    for lower-bound fills, own-side mid T_m seconds after the fill minus the fill
                      price (negative = we got filled right before the price fell: adverse selection)
    * net vs taker    per contract, (maker cost if filled) vs (taker cost), and what that saving is
                      worth once multiplied by the fill odds

All prices are YES dollars per contract; a buy of NO is the mirror and has the same statistics by
symmetry of the YES book (no_ask = 1 - yes_bid), so the YES-buy view is reported.

Read-only. Pure functions over tick lists, plus one repository read per contract.

    python -m app.exec_cost_model --hours 24 --series KXBTC15M,KXETH15M
"""
from __future__ import annotations

import argparse
import bisect
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from data_pipeline.kalshi_fees import MAKER_FEE_RATE, TAKER_FEE_RATE

LATENCIES = (0.25, 1.0, 2.0, 5.0)
MAKER_HORIZONS = (60, 300)
MARKOUT_SECONDS = 60
# Sample a maker post every this many seconds per contract (posts closer together are correlated).
POST_EVERY_SECONDS = 30.0


@dataclass(frozen=True)
class Tick:
    t: float  # unix seconds
    bid: float
    ask: float
    bid_size: Optional[float]
    ask_size: Optional[float]


def _pct(xs: Sequence[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def _wpct(pairs: Sequence[tuple], q: float) -> Optional[float]:
    """Weighted percentile of (value, weight) pairs."""
    pts = sorted((v, w) for v, w in pairs if w > 0)
    total = sum(w for _, w in pts)
    if not total:
        return None
    acc = 0.0
    for v, w in pts:
        acc += w
        if acc >= q * total - 1e-12:
            return v
    return pts[-1][0]


def fee_per_contract(rate, price: float) -> float:
    """Uncapped per-contract fee rate*P*(1-P) (at size the cent-ceiling amortizes away)."""
    return float(rate) * price * (1.0 - price)


def clean(ticks: Iterable[Tick]) -> List[Tick]:
    """Two-sided, uncrossed, inside the 1c..99c grid, time-ordered."""
    out = [k for k in ticks if 0.0 < k.bid < k.ask < 1.0]
    out.sort(key=lambda k: k.t)
    return out


def taker_stats(ticks: List[Tick], latencies: Iterable[float] = LATENCIES) -> Dict:
    """Spread/size distributions (time-weighted) and touch decay over each latency."""
    if len(ticks) < 2:
        return {"ticks": len(ticks)}
    spreads, bsz, asz = [], [], []
    for a, b in zip(ticks, ticks[1:]):
        w = max(0.0, b.t - a.t)
        spreads.append((round(a.ask - a.bid, 4), w))
        if a.bid_size is not None:
            bsz.append((a.bid_size, w))
        if a.ask_size is not None:
            asz.append((a.ask_size, w))
    times = [k.t for k in ticks]
    decay = {}
    for lat in latencies:
        moved = n = 0
        up_sum = 0.0
        for i, k in enumerate(ticks):
            if k.t + lat > times[-1]:
                break
            j = bisect.bisect_right(times, k.t + lat) - 1  # the book in force at arrival
            later = ticks[j]
            n += 1
            if later.ask > k.ask + 1e-9:
                moved += 1
                up_sum += later.ask - k.ask
        decay["%gs" % lat] = {"p_ask_up": round(moved / n, 4) if n else None,
                              "mean_ask_up": round(up_sum / n, 5) if n else None}
    mids = [(k.bid + k.ask) / 2 for k in ticks]
    p50_mid = _pct(mids, 0.5)
    half = (_wpct(spreads, 0.5) or 0.0) / 2.0
    return {
        "ticks": len(ticks),
        "spread_p50": _wpct(spreads, 0.5), "spread_p90": _wpct(spreads, 0.9),
        "ask_size_p50": _wpct(asz, 0.5), "bid_size_p50": _wpct(bsz, 0.5),
        "mid_p50": p50_mid,
        "taker_cost_per_contract": round(half + fee_per_contract(TAKER_FEE_RATE, p50_mid), 5) if p50_mid else None,
        "touch_decay": decay,
    }


def maker_stats(ticks: List[Tick], horizons: Iterable[int] = MAKER_HORIZONS,
                markout_s: int = MARKOUT_SECONDS, post_every: float = POST_EVERY_SECONDS) -> Dict:
    """Bracketed fill odds and adverse selection for a buy resting at the best bid.

    A post is sampled at most every ``post_every`` seconds. For horizon T the post at price p fills:
      lower bound - some tick in (t, t+T] has ask <= p (the offer traded down through us)
      upper bound - lower, or some tick has bid < p (our level was consumed - or pulled, so upper)
    Adverse move is measured on lower-bound fills: mid ``markout_s`` after the fill minus p.
    """
    times = [k.t for k in ticks]
    out: Dict = {}
    if len(ticks) < 2:
        return out
    for T in horizons:
        posts = lo = hi = 0
        adverse: List[float] = []
        next_post = ticks[0].t
        for i, k in enumerate(ticks):
            if k.t < next_post or k.t + T > times[-1]:
                continue
            next_post = k.t + post_every
            p = k.bid
            posts += 1
            filled_at = None
            consumed = False
            j = i + 1
            while j < len(ticks) and ticks[j].t <= k.t + T:
                if ticks[j].ask <= p + 1e-9:
                    filled_at = ticks[j].t
                    break
                if ticks[j].bid < p - 1e-9:
                    consumed = True
                j += 1
            if filled_at is not None:
                lo += 1
                hi += 1
                m = bisect.bisect_right(times, filled_at + markout_s) - 1
                if times[-1] >= filled_at + markout_s:
                    adverse.append(((ticks[m].bid + ticks[m].ask) / 2) - p)
            elif consumed:
                hi += 1
        out["%ds" % T] = {
            "posts": posts,
            "fill_lower": round(lo / posts, 4) if posts else None,
            "fill_upper": round(hi / posts, 4) if posts else None,
            "adverse_move_mean": round(sum(adverse) / len(adverse), 5) if adverse else None,
            "adverse_n": len(adverse),
        }
    return out


def maker_vs_taker(taker: Dict, maker: Dict) -> Dict:
    """Per-contract economics of resting at the bid vs crossing at the ask, at the median book.

    taker cost  = half-spread + taker fee
    maker cost  = -half-spread + maker fee - adverse_move   (adverse_move < 0 is a cost)
    saving      = taker cost - maker cost, earned only when the post fills; the expected saving
                  per attempted entry is bracketed by the fill odds."""
    mid, spread = taker.get("mid_p50"), taker.get("spread_p50")
    if mid is None or spread is None:
        return {}
    half = spread / 2.0
    taker_cost = half + fee_per_contract(TAKER_FEE_RATE, mid)
    out = {"taker_cost": round(taker_cost, 5)}
    for h, m in maker.items():
        adv = m.get("adverse_move_mean")
        if adv is None or m.get("fill_lower") is None:
            continue
        maker_cost = -half + fee_per_contract(MAKER_FEE_RATE, mid) - adv
        saving = taker_cost - maker_cost
        out[h] = {"maker_cost_if_filled": round(maker_cost, 5), "saving_if_filled": round(saving, 5),
                  "expected_saving_lower": round(saving * m["fill_lower"], 5),
                  "expected_saving_upper": round(saving * m["fill_upper"], 5)}
    return out


def series_model(tick_lists: Dict[str, List[Tick]]) -> Dict:
    """Aggregate per-contract stats into one series view (tick-count weighted means)."""
    per = []
    for ticker, ticks in tick_lists.items():
        ts = clean(ticks)
        if len(ts) < 10:
            continue
        per.append((len(ts), taker_stats(ts), maker_stats(ts)))
    if not per:
        return {"contracts": 0}

    def wmean(get):
        pts = [(get(t, m), n) for n, t, m in per if get(t, m) is not None]
        w = sum(n for _, n in pts)
        return round(sum(v * n for v, n in pts) / w, 5) if w else None

    taker = {k: wmean(lambda t, m, k=k: t.get(k))
             for k in ("spread_p50", "spread_p90", "ask_size_p50", "bid_size_p50", "mid_p50",
                       "taker_cost_per_contract")}
    taker["touch_decay"] = {
        lat: {k: wmean(lambda t, m, lat=lat, k=k: (t.get("touch_decay") or {}).get(lat, {}).get(k))
              for k in ("p_ask_up", "mean_ask_up")}
        for lat in ("%gs" % x for x in LATENCIES)}
    maker = {}
    for h in ("%ds" % x for x in MAKER_HORIZONS):
        maker[h] = {k: wmean(lambda t, m, h=h, k=k: (m.get(h) or {}).get(k))
                    for k in ("fill_lower", "fill_upper", "adverse_move_mean")}
        maker[h]["posts"] = sum((m.get(h) or {}).get("posts") or 0 for _, _, m in per)
        maker[h]["adverse_n"] = sum((m.get(h) or {}).get("adverse_n") or 0 for _, _, m in per)
    return {"contracts": len(per), "ticks": sum(n for n, _, _ in per), "taker": taker, "maker": maker,
            "maker_vs_taker": maker_vs_taker(taker, maker)}


def fetch_ticks(cur, series: str, since: datetime, until: datetime) -> Dict[str, List[Tick]]:
    """Every recorded top-of-book change for the series' contracts in [since, until)."""
    cur.execute(
        "SELECT market_ticker, observed_at_utc, yes_bid_dollars, yes_ask_dollars, yes_bid_size_fp, yes_ask_size_fp "
        "FROM forward_quote_ticks WHERE observed_at_utc >= %s AND observed_at_utc < %s AND market_ticker LIKE %s",
        (since.replace(tzinfo=None), until.replace(tzinfo=None), series + "-%"),
    )
    out: Dict[str, List[Tick]] = {}
    for r in cur.fetchall():
        if r["yes_bid_dollars"] is None or r["yes_ask_dollars"] is None:
            continue
        t = r["observed_at_utc"].replace(tzinfo=timezone.utc).timestamp()
        out.setdefault(r["market_ticker"], []).append(Tick(
            t, float(r["yes_bid_dollars"]), float(r["yes_ask_dollars"]),
            None if r["yes_bid_size_fp"] is None else float(r["yes_bid_size_fp"]),
            None if r["yes_ask_size_fp"] is None else float(r["yes_ask_size_fp"])))
    return out


def report(cur, series: Iterable[str], hours: float = 24.0, now: Optional[datetime] = None) -> Dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=float(hours))
    return {"generated_at": now.isoformat(), "window_hours": float(hours),
            "series": {s: series_model(fetch_ticks(cur, s, since, now)) for s in series}}


def main() -> None:  # pragma: no cover - thin CLI over report()
    from data_pipeline.common import get_db_conn

    ap = argparse.ArgumentParser(description="Execution cost model from recorded top-of-book ticks.")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--series", default="KXBTC15M,KXETH15M,KXSOL15M,KXXRP15M,KXDOGE15M,KXBNB15M")
    args = ap.parse_args()
    conn = get_db_conn()
    try:
        print(json.dumps(report(conn.cursor(), args.series.split(","), args.hours), indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    main()
