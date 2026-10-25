"""Nowcast the settlement value of Kalshi BTC contracts in their final seconds, and score it.

Kalshi settles KXBTC15M (and the hourly KXBTCD / KXBTC) on the SIMPLE AVERAGE of the 60 one-second
values of CF Benchmarks' BRTI before the close. A 15-minute contract's strike is that same average
ending at its open, so every contract's settlement value is the next contract's floor_strike: the
tick archive's kalshi_markets table alone gives exact ground truth (``chain_settlements``).

Inside the window part of the average is already fixed. With n = 60 - tau seconds observed (tau =
seconds to close) and X the index now, under a driftless random walk with per-second stdev sigma:

    mean = (sum of observed seconds + tau * X) / 60
    var  = sigma^2 * tau (tau + 1) (2 tau + 1) / 6 / 60^2          (tau <= 60)
    var  = sigma^2 * ((tau - 60) + 60*61*121 / 6 / 60^2)            (tau > 60: plain walk to the window, then the average)

so the settlement's uncertainty falls like tau^1.5, much faster than the sqrt(tau) a spot-vs-strike
fair value assumes. A quote that follows spot instead of the running average is mispriced; the
evaluation below measures by how much, and whether it survives the taker fee and a 1s fill delay.

We do not see the BRTI itself, only a proxy (tick_store.composite_1s: median mid of the 7
constituent venues). Its error against the official value is measured on every 15m open
(``proxy_errors``) and added to the variance as ``proxy_sd``.

    python -m data_pipeline.settle_nowcast --start 2026-10-24T22:00 --end 2026-10-25T06:00 [--json out.json]
"""
import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from data_pipeline.kalshi_fees import taker_fee_dollars

WINDOW_S = 60
SIGMA_LOOKBACK_S = 900
SIGMA_STEP_S = 30
DEFAULT_PROXY_SD = 4.0          # dollars; composite 60s average vs official strikes, 8 opens on 2026-10-24
OFFSETS = (300, 120, 90, 60, 45, 30, 20, 15, 10, 5, 3, 2, 1)
FILL_DELAY_S = 1                # execution-costs-measured: fill at the ask one second later
SETTLE_SERIES = ("KXBTC15M", "KXBTCD", "KXBTC")


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def window_moments(obs_sum: float, obs_n: int, x_now: float, sigma: float, tau: int,
                   window: int = WINDOW_S, proxy_sd: float = 0.0) -> Tuple[float, float]:
    """(mean, sd) of the settlement average with ``tau`` seconds to close, given the sum of the
    ``obs_n`` window seconds already seen and the index now. ``sigma``: per-second stdev of the
    index in dollars. ``obs_n`` must be window - tau inside the window (0 before it)."""
    tau = max(int(tau), 0)
    rem = min(tau, window)
    mean = (obs_sum + rem * x_now) / window if tau < window else x_now
    if tau >= window:
        var = sigma ** 2 * ((tau - window) + window * (window + 1) * (2 * window + 1) / 6.0 / window ** 2)
    else:
        var = sigma ** 2 * rem * (rem + 1) * (2 * rem + 1) / 6.0 / window ** 2
    # The proxy's error is persistent across the window's seconds, so it does not average down.
    return mean, math.sqrt(var + proxy_sd ** 2)


def p_yes(mean: float, sd: float, strike_type: str, floor: Optional[float], cap: Optional[float]) -> float:
    """P(contract settles YES) for a normal settlement value. Kalshi strike types: greater /
    greater_or_equal (floor), less / less_or_equal (cap), between (floor..cap)."""
    def above(k):
        return 1.0 if sd <= 0 and mean >= k else 0.0 if sd <= 0 else 1.0 - _ncdf((k - mean) / sd)
    if strike_type in ("greater", "greater_or_equal"):
        return above(floor)
    if strike_type in ("less", "less_or_equal"):
        return 1.0 - above(cap)
    if strike_type == "between":
        return above(floor) - above(cap)
    raise ValueError(f"unknown strike_type {strike_type!r}")


def settles_yes(value: float, strike_type: str, floor: Optional[float], cap: Optional[float]) -> bool:
    if strike_type == "greater":
        return value > floor
    if strike_type == "greater_or_equal":
        return value >= floor
    if strike_type == "less":
        return value < cap
    if strike_type == "less_or_equal":
        return value <= cap
    if strike_type == "between":
        return floor <= value <= cap
    raise ValueError(f"unknown strike_type {strike_type!r}")


def markets_meta(store, start: datetime, end: datetime, series: Sequence[str] = SETTLE_SERIES) -> Dict[str, Dict]:
    """Last known terms per ticker from the kalshi_markets tick table (the strike is filled in
    once Kalshi fixes it, so the last non-null value wins)."""
    t = store.read("kalshi_markets", start - timedelta(hours=1), end + timedelta(hours=1),
                   columns=["rt", "ticker", "series", "open_ts", "close_ts", "floor_strike", "cap_strike", "strike_type"])
    out: Dict[str, Dict] = {}
    if t is None:
        return out
    for r in t.to_pylist():
        if r["series"] not in series:
            continue
        m = out.setdefault(r["ticker"], {"ticker": r["ticker"], "series": r["series"]})
        for k in ("open_ts", "close_ts", "floor_strike", "cap_strike", "strike_type"):
            if r[k] is not None:
                m[k] = r[k]
    return out


def chain_settlements(meta: Dict[str, Dict]) -> Dict[int, float]:
    """{close_ts: official 60s BRTI average ending then} from KXBTC15M strikes: the contract
    opening at T has floor_strike = that average ending at T, which is what every BTC contract
    closing at T settles on."""
    return {int(m["open_ts"]): float(m["floor_strike"]) for m in meta.values()
            if m["series"] == "KXBTC15M" and m.get("floor_strike") is not None and m.get("open_ts")}


def window_avg(sec: np.ndarray, x: np.ndarray, close_ts: int, window: int = WINDOW_S) -> Optional[float]:
    w = (sec > close_ts - window) & (sec <= close_ts) & np.isfinite(x)
    return float(x[w].mean()) if w.sum() >= window * 0.8 else None


def proxy_errors(sec: np.ndarray, x: np.ndarray, settles: Dict[int, float]) -> List[Tuple[int, float]]:
    """(ts, proxy 60s average minus official) for every official value the proxy covers."""
    out = []
    for ts, v in sorted(settles.items()):
        a = window_avg(sec, x, ts)
        if a is not None:
            out.append((ts, a - v))
    return out


def sigma_per_s(sec: np.ndarray, x: np.ndarray, lookback: int = SIGMA_LOOKBACK_S, k: int = SIGMA_STEP_S) -> np.ndarray:
    """Trailing per-second stdev of the index in dollars, sqrt(mean((x_t - x_{t-k})^2) / k) over
    the last ``lookback`` seconds (uses only seconds <= t). k > 1 because the composite is a
    median of venues that update at different times: its 1s changes are positively
    autocorrelated, so 1s changes understate how far it moves over the tens of seconds that
    matter here (2026-10-24 22-24Z: 1.85 $/s from 1s changes, 2.3 from 30s, 2.45 from 60s)."""
    d = np.full(len(x), np.nan)
    d[k:] = x[k:] - x[:-k]
    ok = np.isfinite(d)
    v = np.where(ok, d * d, 0.0)
    c2, cn = (np.concatenate([[0.0], np.cumsum(a)]) for a in (v, ok.astype(float)))
    i = np.arange(1, len(x) + 1)
    lo = np.maximum(i - lookback, 0)
    n, s2 = cn[i] - cn[lo], c2[i] - c2[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = np.sqrt(s2 / n / k)
    sd[n < lookback // 4] = np.nan
    return sd


def nowcast_rows(sec: np.ndarray, close_ts: np.ndarray, comp_sec: np.ndarray, comp: np.ndarray,
                 proxy_sd: float = DEFAULT_PROXY_SD) -> Tuple[np.ndarray, np.ndarray]:
    """Vectorised (mean, sd) of the settlement average for rows at seconds ``sec`` of contracts
    closing at ``close_ts``, from the index on DENSE consecutive seconds ``comp_sec`` (holes are
    carried forward). Uses only index seconds <= sec. NaN where the index or its volatility is
    not known yet, or the window starts before comp_sec."""
    from data_pipeline.tick_store import _ffill
    sec, close_ts = np.asarray(sec, dtype=np.int64), np.asarray(close_ts, dtype=np.int64)
    x = _ffill(np.asarray(comp, dtype=float))
    s0 = int(comp_sec[0]) if len(comp_sec) else 0
    n = len(x)
    sig = sigma_per_s(comp_sec, x)
    csum = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x, nan=0.0))])
    cnan = np.concatenate([[0], np.cumsum(np.isnan(x))])
    j = sec - s0
    ok = (j >= 0) & (j < n)
    jj = np.clip(j, 0, max(n - 1, 0))
    tau = np.maximum(close_ts - sec, 0)
    inside = tau < WINDOW_S
    lo = np.clip(close_ts - WINDOW_S + 1 - s0, 0, n)          # first window second's index
    hi = np.clip(jj + 1, 0, n)
    ok &= ~inside | (close_ts - WINDOW_S + 1 - s0 >= 0)
    obs_sum = np.where(inside, csum[hi] - csum[np.minimum(lo, hi)], 0.0)
    obs_nan = np.where(inside, cnan[hi] - cnan[np.minimum(lo, hi)], 0)
    xn, sg = x[jj], sig[jj]
    rem = np.minimum(tau, WINDOW_S).astype(float)
    mean = np.where(inside, (obs_sum + rem * xn) / WINDOW_S, xn)
    w = float(WINDOW_S)
    var = np.where(inside, rem * (rem + 1) * (2 * rem + 1) / 6.0 / w ** 2,
                   (tau - w) + w * (w + 1) * (2 * w + 1) / 6.0 / w ** 2) * sg ** 2
    sd = np.sqrt(var + proxy_sd ** 2)
    bad = ~ok | (obs_nan > 0) | ~np.isfinite(xn) | ~np.isfinite(sg)
    mean[bad], sd[bad] = np.nan, np.nan
    return mean, sd


def p_yes_rows(mean: np.ndarray, sd: np.ndarray, strike_lo: np.ndarray, strike_hi: np.ndarray) -> np.ndarray:
    """Vectorised P(YES) from strike columns as features_1s carries them: floor only = above lo,
    cap only = below hi, both = inside the range. NaN where mean/sd is."""
    erf = np.frompyfunc(math.erf, 1, 1)

    def above(k):
        with np.errstate(invalid="ignore", divide="ignore"):
            return 1.0 - 0.5 * (1.0 + erf(((k - mean) / sd / math.sqrt(2.0)).astype(float)).astype(float))
    lo, hi = np.asarray(strike_lo, dtype=float), np.asarray(strike_hi, dtype=float)
    has_lo, has_hi = np.isfinite(lo), np.isfinite(hi)
    p = np.full(len(mean), np.nan)
    a_lo = above(np.where(has_lo, lo, 0.0))
    a_hi = above(np.where(has_hi, hi, 0.0))
    p = np.where(has_lo & has_hi, a_lo - a_hi, np.where(has_lo, a_lo, np.where(has_hi, 1.0 - a_hi, np.nan)))
    p[~(np.isfinite(mean) & np.isfinite(sd))] = np.nan
    return p


def nowcast_path(sec: np.ndarray, x: np.ndarray, close_ts: int, offsets: Sequence[int],
                 proxy_sd: float) -> Dict[int, Tuple[float, float]]:
    """{tau: (mean, sd)} at each offset, using index values at seconds <= close_ts - tau."""
    taus = np.array(sorted(offsets), dtype=np.int64)
    mean, sd = nowcast_rows(close_ts - taus, np.full(len(taus), close_ts), sec, x, proxy_sd)
    return {int(t): (float(m), float(d)) for t, m, d in zip(taus, mean, sd) if np.isfinite(m)}


def evaluate(store, start: datetime, end: datetime, series: Sequence[str] = SETTLE_SERIES,
             offsets: Sequence[int] = OFFSETS, proxy_sd: Optional[float] = None, margin: float = 0.0,
             max_tau_trade: int = 60) -> Dict:
    """Score the nowcast against official settlements for every contract closing in [start, end).

    Per (contract, offset tau): nowcast P(YES), the book's YES bid/ask/mid at close - tau, and the
    outcome. Trades: at each offset <= max_tau_trade, buy YES at the ask FILL_DELAY_S later if
    P - ask > taker fee + margin (NO symmetric); one trade per contract (the earliest trigger),
    held to settlement, 1 contract, so P&L is per contract in dollars."""
    meta = markets_meta(store, start, end, series)
    settles = chain_settlements(meta)
    comp = store.composite_1s(start - timedelta(seconds=SIGMA_LOOKBACK_S + WINDOW_S), end)
    sec, x = comp["sec"].astype(np.int64), comp["spot_comp"].astype(float)
    errs = proxy_errors(sec, x, settles)
    e = np.array([v for _, v in errs])
    psd = proxy_sd if proxy_sd is not None else (float(np.sqrt((e ** 2).mean())) if len(e) >= 5 else DEFAULT_PROXY_SD)
    s0, s1 = int(start.timestamp()), int(end.timestamp())
    closing = [m for m in meta.values() if m.get("close_ts") and s0 <= m["close_ts"] < s1
               and int(m["close_ts"]) in settles and m.get("strike_type")]
    rows: List[Dict] = []
    trades: List[Dict] = []
    by_hour: Dict[int, List[Dict]] = {}
    for m in closing:
        by_hour.setdefault(int(m["close_ts"]) // 3600, []).append(m)
    for _h, ms in sorted(by_hour.items()):
        lo = min(int(m["close_ts"]) for m in ms) - max(offsets) - 5
        hi = max(int(m["close_ts"]) for m in ms)
        feat = store.features_1s(datetime.fromtimestamp(lo, timezone.utc), datetime.fromtimestamp(hi, timezone.utc),
                                 tickers=[m["ticker"] for m in ms],
                                 columns=["sec", "ticker", "yes_bid", "yes_ask", "yes_bid_size", "yes_ask_size", "book_age_s"])
        book: Dict[Tuple[str, int], Tuple[float, float, float, float]] = {}
        if feat:
            for i in range(len(feat["sec"])):
                book[(feat["ticker"][i], int(feat["sec"][i]))] = (float(feat["yes_bid"][i]), float(feat["yes_ask"][i]),
                                                                    float(feat["yes_bid_size"][i]), float(feat["yes_ask_size"][i]))
        for m in ms:
            c = int(m["close_ts"])
            v = settles[c]
            st, fl, cp = m["strike_type"], m.get("floor_strike"), m.get("cap_strike")
            if (fl is None and st != "less" and st != "less_or_equal") or (cp is None and st in ("less", "less_or_equal", "between")):
                continue
            y = settles_yes(v, st, fl, cp)
            path = nowcast_path(sec, x, c, offsets, psd)
            traded = False
            for tau in sorted(path, reverse=True):
                mean, sd = path[tau]
                p = p_yes(mean, sd, st, fl, cp)
                b = book.get((m["ticker"], c - tau))
                bid, ask = (b[0], b[1]) if b else (np.nan, np.nan)
                mid = (bid + ask) / 2 if np.isfinite(bid) and np.isfinite(ask) else np.nan
                rows.append({"ticker": m["ticker"], "series": m["series"], "close_ts": c, "tau": tau, "p": p,
                             "mean": mean, "sd": sd, "settle": v, "yes": int(y), "bid": bid, "ask": ask, "mid": mid})
                if traded or tau > max_tau_trade:
                    continue
                f = book.get((m["ticker"], c - tau + FILL_DELAY_S))
                if not f:
                    continue
                fbid, fask, fbsz, fasz = f
                if np.isfinite(ask) and np.isfinite(fask) and 0 < fask < 1 and fasz > 0:
                    fee = taker_fee_dollars(1, round(fask, 2))
                    if p - ask > fee + margin:
                        trades.append({"ticker": m["ticker"], "series": m["series"], "tau": tau, "side": "yes",
                                       "p": p, "px": fask, "fee": fee, "pnl": (1.0 if y else 0.0) - fask - fee})
                        traded = True
                        continue
                if np.isfinite(bid) and np.isfinite(fbid) and 0 < fbid < 1 and fbsz > 0:
                    no_px = 1.0 - fbid
                    fee = taker_fee_dollars(1, round(no_px, 2))
                    if (1.0 - p) - (1.0 - bid) > fee + margin:
                        trades.append({"ticker": m["ticker"], "series": m["series"], "tau": tau, "side": "no",
                                       "p": p, "px": no_px, "fee": fee, "pnl": (0.0 if y else 1.0) - no_px - fee})
                        traded = True
    return {"start": start.isoformat(), "end": end.isoformat(), "proxy_sd": psd,
            "proxy_errors": errs, "contracts": len({r["ticker"] for r in rows}), "rows": rows, "trades": trades,
            "scores": score(rows), "calibration": calibration(rows), "trade_summary": trade_summary(trades)}


def _brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(((p - y) ** 2).mean())


def score(rows: List[Dict]) -> Dict:
    """Per series and offset: Brier of the nowcast vs the book mid, on contracts where both exist
    and the book is not already pinned (mid in (0.02, 0.98)), plus the count."""
    out: Dict[str, Dict] = {}
    keys = sorted({(r["series"], r["tau"]) for r in rows}, key=lambda k: (k[0], -k[1]))
    for s, tau in keys:
        rs = [r for r in rows if r["series"] == s and r["tau"] == tau and np.isfinite(r["mid"]) and 0.02 < r["mid"] < 0.98]
        if not rs:
            continue
        p = np.array([r["p"] for r in rs]); mid = np.array([r["mid"] for r in rs]); y = np.array([r["yes"] for r in rs])
        out.setdefault(s, {})[str(tau)] = {"n": len(rs), "brier_nowcast": _brier(p, y), "brier_mid": _brier(mid, y),
                                           "mean_abs_gap": float(np.abs(p - mid).mean())}
    return out


def calibration(rows: List[Dict]) -> Dict:
    """Per offset, over distinct close times: z = (official settlement - nowcast mean) / sd. A
    well-specified nowcast has z ~ N(0, 1): mean ~0, sd ~1, about 5% beyond +-2."""
    out = {}
    seen = {}
    for r in rows:
        seen[(r["close_ts"], r["tau"])] = (r["settle"] - r["mean"]) / r["sd"]
    for tau in sorted({k[1] for k in seen}, reverse=True):
        z = np.array([v for k, v in seen.items() if k[1] == tau])
        out[str(tau)] = {"n": len(z), "z_mean": float(z.mean()), "z_sd": float(z.std()),
                         "beyond_2": float((np.abs(z) > 2).mean())}
    return out


def trade_summary(trades: List[Dict]) -> Dict:
    out = {}
    for s in sorted({t["series"] for t in trades}):
        pnl = np.array([t["pnl"] for t in trades if t["series"] == s])
        out[s] = {"n": len(pnl), "pnl_total": float(pnl.sum()), "pnl_mean": float(pnl.mean()),
                  "pnl_se": float(pnl.std(ddof=1) / math.sqrt(len(pnl))) if len(pnl) > 1 else None,
                  "win_rate": float((pnl > 0).mean())}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    from data_pipeline.tick_store import TickStore
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--series", default=",".join(SETTLE_SERIES))
    ap.add_argument("--margin", type=float, default=0.0)
    ap.add_argument("--proxy-sd", type=float, default=None)
    ap.add_argument("--json", default=None, help="write the full report here")
    a = ap.parse_args(argv)
    start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc)
    rep = evaluate(TickStore(), start, end, series=a.series.split(","), margin=a.margin, proxy_sd=a.proxy_sd)
    e = np.array([v for _, v in rep["proxy_errors"]])
    if len(e):
        print(f"proxy: n={len(e)} bias={e.mean():+.2f} sd={e.std():.2f} -> proxy_sd={rep['proxy_sd']:.2f}")
    print(f"contracts scored: {rep['contracts']}")
    for s, by in rep["scores"].items():
        for tau, v in by.items():
            print(f"{s:9s} tau={tau:>4s}s n={v['n']:4d} brier nowcast={v['brier_nowcast']:.4f} mid={v['brier_mid']:.4f} |gap|={v['mean_abs_gap']:.3f}")
    for tau, v in rep["calibration"].items():
        print(f"calibration tau={tau:>4s}s n={v['n']:3d} z mean={v['z_mean']:+.2f} sd={v['z_sd']:.2f} |z|>2={v['beyond_2']:.2f}")
    for s, v in rep["trade_summary"].items():
        print(f"trades {s}: n={v['n']} pnl={v['pnl_total']:+.2f} mean={v['pnl_mean']:+.4f} se={v['pnl_se']} win={v['win_rate']:.2f}")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
