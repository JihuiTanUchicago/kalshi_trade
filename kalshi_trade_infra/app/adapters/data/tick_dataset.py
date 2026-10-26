"""Research datasets from the per-second tick archive (features_1s, data_pipeline/tick_features.py).

A market with source="ticks" (markets.btc15m_tick) is replayed from TickStore.features_1s instead
of minute candles: one decision every market.decision_seconds, each contract's Snapshot carrying
the book, taker flow and Coinbase spot as of the end of that second (every value uses only events
before it, so nothing peeks). Settlement results come from hist_markets as for every binary market,
so simulate(), the gatekeeper and the partitions treat it like any other Dataset; the next_bar fill
model then fills at the NEXT decision's quote, i.e. a few seconds later, capped by the shown size.

Feature names match the candle path where the meaning is the same (spot, ret_*, vol_15m, vol_60m,
tte_min, moneyness, z_score, yes_bid/ask, spread, mid, hour_et, yes_bid_size, yes_ask_size,
ob_imbalance, trades_60s, taker_*_vol_60s, flow_imb_60s), so a rule and the GBM fair value port
between the two. vol_* / ret_15m / ret_60m / z_score come from minute closes rebuilt from the
per-second spot and need an hour of continuous data, so they are absent early in a window. The
rest exist only here (TICK_FEATURES).
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from app.trading.markets import NEW_YORK, BtcSeries, Contract, Market, Snapshot, TICK_FEATURES  # noqa: F401 - re-exported

MAX_BOOK_AGE_S = float(os.getenv("TAU_TICK_MAX_BOOK_AGE_S", "60"))  # older book state is not a quote

# features_1s column -> snapshot feature (same meaning as the candle path, or tick-only above).
_DIRECT = {
    "spot": "spot", "spot_ret_1s": "ret_1s", "spot_ret_10s": "ret_10s", "spot_ret_60s": "ret_1m",
    "spot_ret_300s": "ret_5m", "rv_60s": "rv_60s", "rv_300s": "rv_300s", "spot_taker_imb_60s": "spot_flow_imb_60s",
    "yes_bid_size": "yes_bid_size", "yes_ask_size": "yes_ask_size", "imbalance": "ob_imbalance",
    "microprice": "microprice", "bid_depth": "bid_depth_5c", "ask_depth": "ask_depth_5c",
    "updates": "book_updates_1s", "book_age_s": "book_age_s", "n_prints_60s": "trades_60s",
    "yes_taker_60s": "taker_yes_vol_60s", "no_taker_60s": "taker_no_vol_60s",
    "yes_taker_10s": "taker_yes_vol_10s", "no_taker_10s": "taker_no_vol_10s",
    "opt_p_yes": "opt_p_yes", "opt_iv": "opt_iv",
    "pm_p_yes": "pm_p_yes", "pm_spread": "pm_spread", "pm_age_s": "pm_age_s",
}
COLUMNS = ["sec", "ticker", "close_ts", "strike_lo", "strike_hi", "yes_bid", "yes_ask", "secs_to_close",
           "dist_sigma", "spot_stale", "spot_comp"] + sorted(set(_DIRECT) - {"spot"}) + ["spot"]


def _flow_imb(yes: float, no: float) -> Optional[float]:
    tot = yes + no
    return (yes - no) / tot if tot > 0 else None


def _minute_series(sec: np.ndarray, spot: np.ndarray) -> BtcSeries:
    """One-minute closes from per-second spot (close of the minute starting t = spot at second t+60),
    so vol_15m / vol_60m / ret_15m / ret_60m are computed exactly as the candle path computes them."""
    ok = np.isfinite(spot)
    u, first = np.unique(sec[ok], return_index=True)
    px = spot[ok][first]
    ends = u % 60 == 0
    return BtcSeries([(int(t) - 60, float(p)) for t, p in zip(u[ends], px[ends])])


def _settle_nowcast(frame: Dict[str, np.ndarray], idx: np.ndarray) -> Dict[str, np.ndarray]:
    """p_settle / settle_sd / settle_z for rows ``idx``, from the frame's BRTI composite
    (data_pipeline/settle_nowcast.py). Empty when the frame has no composite (hours archived
    before the venues were recorded)."""
    if "spot_comp" not in frame or not len(idx):
        return {}
    from data_pipeline import settle_nowcast
    sec = frame["sec"].astype(np.int64)
    comp = frame["spot_comp"].astype(float)
    have = np.isfinite(comp)
    if not have.any():
        return {}
    s0, s1 = int(sec[have].min()), int(sec[have].max())
    dense = np.full(s1 - s0 + 1, np.nan)
    dense[sec[have] - s0] = comp[have]        # one value per second; every ticker's row carries the same one
    mean, sd = settle_nowcast.nowcast_rows(sec[idx], frame["close_ts"].astype(np.int64)[idx],
                                           np.arange(s0, s1 + 1), dense)
    lo, hi = frame["strike_lo"].astype(float)[idx], frame["strike_hi"].astype(float)[idx]
    p = settle_nowcast.p_yes_rows(mean, sd, lo, hi)
    strike = np.where(np.isfinite(lo), lo, hi)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (mean - strike) / sd
    return {"p_settle": p, "settle_sd": sd, "settle_z": z}


def build(market: Market, frame: Dict[str, np.ndarray], results: Dict[str, str],
          contracts_open: Dict[str, int]) -> List[Tuple[int, List[Snapshot]]]:
    """Decision frames from a features_1s frame: rows on the market's cadence, for contracts whose
    result is known and that opened inside the window (contracts_open: ticker -> open_ts), with a
    live two-sided quote no older than MAX_BOOK_AGE_S and fresh Coinbase spot."""
    if not frame or not len(frame.get("sec", ())):
        return []
    step = max(int(market.decision_seconds), 1)
    sec = frame["sec"].astype(np.int64)
    bid, ask = frame["yes_bid"].astype(float), frame["yes_ask"].astype(float)
    keep = (sec % step == 0) & np.isfinite(bid) & np.isfinite(ask) & (ask > 0) & (ask < 1) & (bid >= 0) & (bid < ask)
    keep &= frame["secs_to_close"].astype(float) > 0
    keep &= ~(frame["book_age_s"].astype(float) > MAX_BOOK_AGE_S)
    keep &= ~frame["spot_stale"].astype(bool) & np.isfinite(frame["spot"].astype(float))
    tick = frame["ticker"]
    keep &= np.array([t in results and t in contracts_open for t in tick], dtype=bool)
    idx = np.flatnonzero(keep)
    idx = idx[np.lexsort((tick[idx], sec[idx]))]
    minutes = _minute_series(sec, frame["spot"].astype(float))
    contracts: Dict[str, Contract] = {}
    out: List[Tuple[int, List[Snapshot]]] = []
    cols = {c: frame[c] for c in _DIRECT if c in frame}
    nowcast = _settle_nowcast(frame, idx)
    for row_n, i in enumerate(idx):
        t = str(tick[i])
        ts = int(sec[i])
        c = contracts.get(t)
        if c is None:
            lo, hi = float(frame["strike_lo"][i]), float(frame["strike_hi"][i])
            strike = lo if math.isfinite(lo) else hi     # KXBTC15M is floor-only: "above lo"
            c = contracts[t] = Contract(t, strike if math.isfinite(strike) and strike > 0 else 0.0,
                                        datetime.fromtimestamp(int(frame["close_ts"][i]), tz=timezone.utc),
                                        series=market.series)
        if c.strike <= 0:
            continue
        f: Dict[str, float] = {}
        for col, name in _DIRECT.items():
            if col in cols:
                v = float(cols[col][i])
                if math.isfinite(v):
                    f[name] = v
        b, a = float(bid[i]), float(ask[i])
        f["tte_min"] = float(frame["secs_to_close"][i]) / 60.0
        f["moneyness"] = math.log(f["spot"] / c.strike)
        z = float(frame["dist_sigma"][i])
        if math.isfinite(z):
            f["z_score_5m"] = z
        mf = minutes.features_at(ts)
        if mf:   # the candle path's minute-close returns and vols, so GBM fair values and z_score match it
            for k in ("ret_15m", "ret_60m", "vol_15m", "vol_60m"):
                f[k] = mf[k]
            if mf["vol_60m"] > 0:
                f["z_score"] = f["moneyness"] / (mf["vol_60m"] * math.sqrt(f["tte_min"]))
        for name, y, n in (("flow_imb_60s", "taker_yes_vol_60s", "taker_no_vol_60s"),
                           ("flow_imb_10s", "taker_yes_vol_10s", "taker_no_vol_10s")):
            fi = _flow_imb(f.get(y, 0.0), f.get(n, 0.0))
            if fi is not None:
                f[name] = fi
        for name, vals in nowcast.items():
            v = float(vals[row_n])
            if math.isfinite(v):
                f[name] = v
        f["yes_bid"], f["yes_ask"], f["spread"], f["mid"] = b, a, a - b, (a + b) / 2.0
        if "opt_p_yes" in f:
            f["opt_edge"] = f["opt_p_yes"] - f["mid"]
        if "pm_p_yes" in f:
            f["pm_edge"] = f["pm_p_yes"] - f["mid"]
        f["hour_et"] = float(datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(NEW_YORK).hour)
        snap = Snapshot(contract=c, ts=ts, yes_bid=b, yes_ask=a, features=f)
        if out and out[-1][0] == ts:
            out[-1][1].append(snap)
        else:
            out.append((ts, [snap]))
    return out


def load_window(market: Market, contracts: List[Dict], from_ts: int, to_ts: int,
                read: Optional[Callable[..., Dict[str, np.ndarray]]] = None):
    """Dataset of the contracts opening in [from_ts, to_ts) (contracts: partition_contracts rows),
    replayed from features_1s. `read(start, end, series=, columns=)` defaults to TickStore."""
    from app.trading import backtest
    sub = [c for c in contracts if from_ts <= c["open_ts"] < to_ts and c["open_ts"] >= market.data_from_ts
           and c.get("result") in ("yes", "no")]
    if not sub:
        raise ValueError("no settled %s contracts with per-second data in this window yet "
                         "(the tick archive starts %s)" % (market.series, datetime.fromtimestamp(
                             market.data_from_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%MZ")))
    if read is None:
        from data_pipeline.tick_store import TickStore
        read = TickStore().features_1s
    start = datetime.fromtimestamp(min(c["open_ts"] for c in sub), tz=timezone.utc)
    end = datetime.fromtimestamp(max(c["close_ts"] for c in sub), tz=timezone.utc)
    frame = read(start, end, series=[market.series], columns=COLUMNS)
    results = {c["ticker"]: c["result"] for c in sub}
    frames = build(market, frame, results, {c["ticker"]: c["open_ts"] for c in sub})
    del frame
    if not frames:
        raise ValueError("the tick archive has no usable %s seconds for this window" % market.series)
    traded = {s.contract.ticker for _, snaps in frames for s in snaps}
    return backtest.Dataset(market=market, frames=frames, results={t: r for t, r in results.items() if t in traded},
                            start_ts=frames[0][0], end_ts=frames[-1][0], contracts=len(traded))
