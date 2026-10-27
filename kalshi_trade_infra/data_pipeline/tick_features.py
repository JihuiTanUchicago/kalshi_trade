"""features_1s: one row per (Kalshi BTC contract, second it is open), built from the tick archive.

Built by tick_archiver for each archived hour (needs that hour's kalshi tables, and the
Coinbase hour plus the 5 minutes before it for spot returns and volatility). Written one file
per series, ticks/v1/features_1s/date=YYYY-MM-DD/hour=HH/series=<SERIES>/part.parquet, with a
manifest like the raw tables (its tables.series lists the series and their row counts); read it
with TickStore.features_1s(...).

Every value at ``sec`` uses only events received before ``sec`` (rt < sec * 1e9): ``sec`` is
the END of the second, as in tick_store's frames. Book state is carried forward between
updates; ``book_age_s`` says how old it is, so stale rows can be dropped.

Columns (float32 unless noted):
  sec (int64), ticker, series (str), close_ts (int64), strike_lo, strike_hi
  yes_bid, yes_ask, yes_bid_size, yes_ask_size, bid_depth, ask_depth (within 5c of each touch),
  updates (book deltas in the second), mid, spread, microprice, imbalance
  yes_taker_10s, no_taker_10s, yes_taker_60s, no_taker_60s, n_prints_60s, last_yes
  spot (Coinbase product of the series' coin: BTC-USD, ETH-USD for KXETH15M, ...),
  spot_ret_1s, spot_ret_10s, spot_ret_60s, spot_ret_300s (log), rv_60s, rv_300s (stdev
  of 1s log returns, per second), spot_taker_imb_60s
  secs_to_close, dist_sigma: log distance from spot to the strike on the YES side, over
  rv_300s * sqrt(secs_to_close). Floor only: ln(spot/lo). Cap only: ln(hi/spot). Both (range):
  the nearer edge, min(ln(spot/lo), ln(hi/spot)), positive inside the range. Null when undefined.
  book_age_s, spot_stale (bool: no Coinbase ticker message in the last 5s)
  spot_comp: cross-exchange BTC price, the median mid of the BRTI venues quoted in the last 60s
  (Coinbase, Kraken, Bitstamp, Gemini, Bullish, Crypto.com, LMAX; tick_spot.py), a proxy for the
  index Kalshi settles on. spot_comp_n: venues in it. spot_cb_comp_bp: Coinbase mid minus
  spot_comp, in basis points. dist_sigma_comp: dist_sigma with spot_comp in place of spot.
  Null for non-BTC series. Hours built before this change lack the four columns (the reader
  returns them as null); with only Coinbase quoting, spot_comp is Coinbase's mid, spot_comp_n 1.
  opt_p_yes: the Deribit options-implied probability that the contract settles YES (floor, cap or
  range; data_pipeline/options_surface.py), priced at spot_comp (Coinbase spot without it) off the
  newest deribit_surface snapshot received before the second. opt_iv: the implied vol at the
  contract's strike and horizon, annualized. Null off BTC, without a surface younger than
  options_surface.MAX_AGE_S, and in hours built before the Deribit recorder (2026-10-25).
  pm_p_yes: Polymarket's probability for the same event (data_pipeline/polymarket.py): the
  15-minute up/down window with the contract's open and close for KXBTC15M, else the daily strike
  ladder settling at the contract's close read as a curve at its strikes (KXBTCD/KXBTC at noon ET).
  From the newest polymarket_top poll received before the second, at most PM_MAX_AGE_S old.
  pm_age_s: seconds since that poll; pm_spread: the Polymarket YES spread behind it. Null where
  Polymarket lists no twin, and in hours built before the Polymarket recorder (2026-10-25).
"""
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np

NS = 1_000_000_000
DEPTH = 0.05
SPOT_LOOKBACK_S = 300
FLOW_LOOKBACK_S = 60
SPOT_STALE_S = 5
ROW_GROUP = 1 << 20

F32 = ["strike_lo", "strike_hi", "yes_bid", "yes_ask", "yes_bid_size", "yes_ask_size", "bid_depth", "ask_depth",
       "updates", "mid", "spread", "microprice", "imbalance", "yes_taker_10s", "no_taker_10s", "yes_taker_60s",
       "no_taker_60s", "n_prints_60s", "last_yes", "spot", "spot_ret_1s", "spot_ret_10s", "spot_ret_60s",
       "spot_ret_300s", "rv_60s", "rv_300s", "spot_taker_imb_60s", "secs_to_close", "dist_sigma", "book_age_s",
       "spot_comp", "spot_comp_n", "spot_cb_comp_bp", "dist_sigma_comp", "opt_p_yes", "opt_iv",
       "pm_p_yes", "pm_age_s", "pm_spread"]
PM_MAX_AGE_S = 30


def schema():
    import pyarrow as pa
    fields = [("sec", pa.int64()), ("ticker", pa.string()), ("series", pa.string()), ("close_ts", pa.int64())]
    fields += [(c, pa.float32()) for c in F32]
    fields.append(("spot_stale", pa.bool_()))
    return pa.schema(fields)


def _np(t, name) -> np.ndarray:
    return t[name].to_numpy(zero_copy_only=False)


def _roll_sum(x: np.ndarray, k: int) -> np.ndarray:
    """Sum of x[i-k+1..i]; NaN counts as 0."""
    c = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x, nan=0.0))])
    i = np.arange(1, len(x) + 1)
    return c[i] - c[np.maximum(i - k, 0)]


def _roll_std(x: np.ndarray, k: int) -> np.ndarray:
    """Population stdev over the last k values, ignoring NaN; NaN with fewer than 2 values."""
    ok = ~np.isnan(x)
    v = np.where(ok, x, 0.0)
    n = _roll_sum(ok.astype(float), k)
    s1 = _roll_sum(v, k)
    s2 = _roll_sum(v * v, k)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = s2 / n - (s1 / n) ** 2
    out = np.sqrt(np.maximum(var, 0.0))
    out[n < 2] = np.nan
    return out


def _lag_diff(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    out[k:] = x[k:] - x[:-k]
    return out


def spot_features(store, hour: datetime, product: str = "BTC-USD") -> Dict[str, np.ndarray]:
    """Spot columns for the hour's 3600 seconds, computed on a window that starts
    SPOT_LOOKBACK_S earlier so 300s returns/volatility exist from the first second."""
    start = hour - timedelta(seconds=SPOT_LOOKBACK_S)
    end = hour + timedelta(hours=1)
    sp = store.spot_1s(start, end, product)
    logp = np.log(sp["price"].astype(float))
    r1 = _lag_diff(logp, 1)
    buy, sell = _roll_sum(sp["taker_buy"], 60), _roll_sum(sp["taker_sell"], 60)
    with np.errstate(invalid="ignore", divide="ignore"):
        imb = np.where(buy + sell > 0, (buy - sell) / (buy + sell), np.nan)
    # Staleness: seconds since the last Coinbase ticker message (best bid/ask update).
    tk = store.read("coinbase_ticker", start, end, tickers=[product], columns=["rt", "product_id"])
    seen = np.zeros(len(sp["sec"]), dtype=bool)
    if tk is not None and tk.num_rows:
        idx = (_np(tk, "rt") // NS + 1 - sp["sec"][0]).astype(np.int64)
        idx = idx[(idx >= 0) & (idx < len(seen))]
        seen[idx] = True
    pos = np.where(seen, np.arange(len(seen)), -10**9)
    last_seen = np.maximum.accumulate(pos)
    stale = (np.arange(len(seen)) - last_seen) > SPOT_STALE_S - 1   # nothing in the last 5 seconds
    out = {"spot": sp["price"], "spot_ret_1s": r1, "spot_ret_10s": _lag_diff(logp, 10),
           "spot_ret_60s": _lag_diff(logp, 60), "spot_ret_300s": _lag_diff(logp, 300),
           "rv_60s": _roll_std(r1, 60), "rv_300s": _roll_std(r1, 300), "spot_taker_imb_60s": imb,
           "spot_stale": stale}
    out = {k: v[SPOT_LOOKBACK_S:] for k, v in out.items()}
    out.update(composite_features(store, hour, product))
    return out


def composite_features(store, hour: datetime, product: str = "BTC-USD") -> Dict[str, np.ndarray]:
    """spot_comp, spot_comp_n, spot_cb_comp_bp for the hour's 3600 seconds (NaN off BTC: the
    other venues are recorded for BTC only)."""
    nan = np.full(3600, np.nan)
    if product != "BTC-USD" or not hasattr(store, "composite_1s"):
        return {"spot_comp": nan, "spot_comp_n": nan.copy(), "spot_cb_comp_bp": nan.copy()}
    c = store.composite_1s(hour, hour + timedelta(hours=1), product)
    comp = c["spot_comp"].astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        bp = (c["mid_coinbase"] / comp - 1.0) * 1e4
    return {"spot_comp": comp, "spot_comp_n": c["n_venues"].astype(float), "spot_cb_comp_bp": bp}


def _group(t, key: str) -> Dict[str, np.ndarray]:
    """{value: row indices in original order}. Groups on integer codes: an hour's kalshi_book is ~9M
    rows, and its ticker column as Python strings alone was ~0.5 GB of the archiver's 2 GB cap."""
    import pyarrow.compute as pc
    if t is None or t.num_rows == 0:
        return {}
    names = pc.unique(t[key])
    vals = pc.index_in(t[key], value_set=names, skip_nulls=False).to_numpy(zero_copy_only=False)
    names = names.to_pylist()
    order = np.argsort(vals, kind="stable")
    sv = vals[order]
    out = {}
    if len(sv) == 0:
        return out
    cuts = np.nonzero(sv[1:] != sv[:-1])[0] + 1
    for a, b in zip(np.concatenate([[0], cuts]), np.concatenate([cuts, [len(sv)]])):
        out[names[int(sv[a])]] = order[a:b]
    return out


def book_at_secs(rt, kind, side, price, qty, upd_rt, secs: np.ndarray) -> Dict[str, np.ndarray]:
    """One ticker's top of book at each second boundary (events with rt < sec * NS applied).
    Events cost a dict update each; the max/depth scan runs once per second, not per event,
    which matters for the 15-minute contract (~400 deltas a second)."""
    n = len(secs)
    cols = {k: np.full(n, np.nan) for k in ("bid", "bid_size", "ask", "ask_size", "bid_depth", "ask_depth", "upd")}
    rt, kind, side, price, qty, upd_rt = (np.asarray(x).tolist() for x in (rt, kind, side, price, qty, upd_rt))
    yes: Dict[float, float] = {}
    no: Dict[float, float] = {}
    have = False
    last_upd = np.nan
    i, m = 0, len(rt)
    for k in range(n):
        bound = int(secs[k]) * NS
        while i < m and rt[i] < bound:
            kd, s = int(kind[i]), side[i]
            if kd in (0, 3):
                if s is None:
                    yes, no, have = {}, {}, True
                    u = upd_rt[i]
                    last_upd = float(u) if u is not None and u == u else (float(rt[i]) if kd == 0 else np.nan)
                else:
                    (yes if s == "yes" else no)[float(price[i])] = float(qty[i])
            elif kd == 1 and have and s in ("yes", "no") and price[i] == price[i]:
                lv = yes if s == "yes" else no
                p = float(price[i])
                q = lv.get(p, 0.0) + float(qty[i])
                if q <= 1e-9:
                    lv.pop(p, None)
                else:
                    lv[p] = q
                last_upd = float(rt[i])
            i += 1
        if not have:
            continue
        cols["upd"][k] = last_upd
        if yes:
            bb = max(yes)
            cols["bid"][k], cols["bid_size"][k] = bb, yes[bb]
            cols["bid_depth"][k] = sum(q for p, q in yes.items() if p >= bb - DEPTH - 1e-9)
        if no:
            bn = max(no)
            cols["ask"][k], cols["ask_size"][k] = round(1.0 - bn, 4), no[bn]
            cols["ask_depth"][k] = sum(q for p, q in no.items() if p >= bn - DEPTH - 1e-9)
    return cols


def ticker_rows(ticker: str, meta: Dict, secs: np.ndarray, spot: Dict[str, np.ndarray],
                book_rows: Optional[Dict[str, np.ndarray]], trade_rows: Optional[Dict[str, np.ndarray]],
                surfaces=None, pm=None) -> Optional[Dict]:
    open_ts, close_ts = meta.get("open_ts"), meta.get("close_ts")
    mask = np.ones(len(secs), dtype=bool)
    if open_ts is not None:
        mask &= secs > open_ts
    if close_ts is not None:
        mask &= secs <= close_ts
    if not mask.any():
        return None
    n = len(secs)
    out: Dict[str, np.ndarray] = {}
    # book: state as of the last event with rt < sec
    names = ("yes_bid", "yes_bid_size", "yes_ask", "yes_ask_size", "bid_depth", "ask_depth")
    if book_rows is not None and len(book_rows["rt"]):
        st = book_at_secs(book_rows["rt"], book_rows["kind"], book_rows["side"], book_rows["price"],
                          book_rows["qty"], book_rows["upd_rt"], secs)
        for name, src in zip(names, ("bid", "bid_size", "ask", "ask_size", "bid_depth", "ask_depth")):
            out[name] = st[src]
        out["book_age_s"] = secs - st["upd"] / NS
        dsec = book_rows["rt"][book_rows["kind"] == 1] // NS + 1
        dsec = dsec[(dsec >= secs[0]) & (dsec <= secs[-1])]
        out["updates"] = np.bincount((dsec - secs[0]).astype(np.int64), minlength=n).astype(float)
    else:
        for name in names + ("book_age_s",):
            out[name] = np.full(n, np.nan)
        out["updates"] = np.zeros(n)
    bid, ask, bs, as_ = out["yes_bid"], out["yes_ask"], out["yes_bid_size"], out["yes_ask_size"]
    with np.errstate(invalid="ignore", divide="ignore"):
        out["mid"] = (bid + ask) / 2
        out["spread"] = ask - bid
        out["microprice"] = (bid * as_ + ask * bs) / (bs + as_)
        out["imbalance"] = (bs - as_) / (bs + as_)
    # flow: rolling sums over seconds, from FLOW_LOOKBACK_S before the hour
    w0 = secs[0] - FLOW_LOOKBACK_S
    m = n + FLOW_LOOKBACK_S
    yes_v, no_v, cnt, last = np.zeros(m), np.zeros(m), np.zeros(m), np.full(m, np.nan)
    if trade_rows is not None and len(trade_rows["rt"]):
        j = (trade_rows["rt"] // NS + 1 - w0).astype(np.int64)
        ok = (j >= 0) & (j < m)
        c = np.nan_to_num(trade_rows["count"].astype(float), nan=0.0)
        np.add.at(cnt, j[ok], 1)
        np.add.at(yes_v, j[ok & (trade_rows["taker_side"] == "yes")], c[ok & (trade_rows["taker_side"] == "yes")])
        np.add.at(no_v, j[ok & (trade_rows["taker_side"] == "no")], c[ok & (trade_rows["taker_side"] == "no")])
        px = trade_rows["yes_price"].astype(float)
        last[j[ok]] = px[ok]
    from data_pipeline.tick_store import _ffill
    sl = slice(FLOW_LOOKBACK_S, None)
    out["yes_taker_10s"], out["no_taker_10s"] = _roll_sum(yes_v, 10)[sl], _roll_sum(no_v, 10)[sl]
    out["yes_taker_60s"], out["no_taker_60s"] = _roll_sum(yes_v, 60)[sl], _roll_sum(no_v, 60)[sl]
    out["n_prints_60s"] = _roll_sum(cnt, 60)[sl]
    out["last_yes"] = _ffill(last)[sl]
    out.update({k: v for k, v in spot.items()})
    lo, hi = meta.get("floor_strike"), meta.get("cap_strike")
    stc = (close_ts - secs).astype(float) if close_ts is not None else np.full(n, np.nan)
    out["secs_to_close"] = stc
    denom = spot["rv_300s"] * np.sqrt(np.maximum(stc, 0.0))
    out["dist_sigma"] = _dist_sigma(spot["spot"], lo, hi, denom)
    comp = spot.get("spot_comp")
    out["dist_sigma_comp"] = _dist_sigma(comp, lo, hi, denom) if comp is not None else np.full(n, np.nan)
    px = spot["spot"].astype(float)
    if comp is not None:
        px = np.where(np.isfinite(comp), comp, px)
    out.update(option_cols(surfaces, secs, lo, hi, close_ts, px))
    from data_pipeline.polymarket import UPDOWN_SERIES
    series = meta.get("series") or ticker.split("-")[0]
    out.update(polymarket_cols(pm, secs, lo, hi, open_ts if series in UPDOWN_SERIES else None, close_ts))
    out["strike_lo"] = np.full(n, np.nan if lo is None else lo)
    out["strike_hi"] = np.full(n, np.nan if hi is None else hi)
    rows = {k: v[mask] for k, v in out.items()}
    k = int(mask.sum())
    rows["sec"] = secs[mask]
    rows["ticker"] = np.array([ticker] * k, dtype=object)
    rows["series"] = np.array([meta.get("series") or ticker.split("-")[0]] * k, dtype=object)
    rows["close_ts"] = np.full(k, -1 if close_ts is None else close_ts, dtype=np.int64)
    return rows


def _dist_sigma(spot: np.ndarray, lo, hi, denom: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.asarray(spot, dtype=float)
        if lo is not None and hi is not None:
            num = np.minimum(np.log(s / lo), np.log(hi / s))
        elif lo is not None:
            num = np.log(s / lo)
        elif hi is not None:
            num = np.log(hi / s)
        else:
            num = np.full(len(s), np.nan)
        return np.where(denom > 0, num / denom, np.nan)


def option_cols(surfaces, secs: np.ndarray, lo, hi, close_ts, spot: np.ndarray) -> Dict[str, np.ndarray]:
    """opt_p_yes / opt_iv per second off the newest surface known before each second."""
    from data_pipeline import options_surface as osf
    n = len(secs)
    p, v = np.full(n, np.nan), np.full(n, np.nan)
    if surfaces is None or not len(surfaces) or close_ts is None or (lo is None and hi is None):
        return {"opt_p_yes": p, "opt_iv": v}
    idx = surfaces.indexes(secs)
    ok = idx >= 0
    for i in np.unique(idx[ok]):
        m = idx == i
        p[m], v[m] = osf.prob_yes(surfaces.surfaces[int(i)], secs[m].astype(float), lo, hi, float(close_ts), spot[m])
    return {"opt_p_yes": p, "opt_iv": v}


def polymarket_cols(pm, secs: np.ndarray, lo, hi, open_ts, close_ts) -> Dict[str, np.ndarray]:
    """pm_p_yes / pm_age_s / pm_spread per second from the newest Polymarket poll before it."""
    n = len(secs)
    out = {k: np.full(n, np.nan) for k in ("pm_p_yes", "pm_age_s", "pm_spread")}
    if pm is None or close_ts is None or (lo is None and hi is None):
        return out
    polls = pm.polls(int(close_ts))
    if not polls:
        return out
    # each poll's value holds from the second after it was received until the next poll
    for i, poll in enumerate(polls):
        f = pm.prob(lo, hi, int(close_ts), open_ts, poll)
        start = poll[0] + 1
        stop = min(polls[i + 1][0] + 1 if i + 1 < len(polls) else start + PM_MAX_AGE_S, start + PM_MAX_AGE_S)
        a, b = np.searchsorted(secs, start), np.searchsorted(secs, stop)
        if a >= b:
            continue
        if f is None:
            continue
        out["pm_p_yes"][a:b] = f["pm_p_yes"]
        out["pm_spread"][a:b] = f["pm_spread"]
        out["pm_age_s"][a:b] = secs[a:b] - f["pm_ts"]
    return out


def load_polymarket(store, hour: datetime):
    """The Polymarket polls that can price this hour (PmSeries), or None before the recorder."""
    from data_pipeline import polymarket
    tops = store.read("polymarket_top", hour - timedelta(seconds=PM_MAX_AGE_S), hour + timedelta(hours=1))
    if tops is None or not tops.num_rows:
        return None
    mk = store.read("polymarket_markets", hour - timedelta(hours=1), hour + timedelta(hours=1))
    if mk is None or not mk.num_rows:
        return None
    s = polymarket.PmSeries(polymarket.quotes_from_archive(mk.to_pylist(), tops.to_pylist()))
    return s if len(s) else None


def load_surfaces(store, hour: datetime):
    """The Deribit surfaces that can price this hour (received up to MAX_AGE_S before it), or None."""
    from data_pipeline import options_surface as osf
    t = store.read("deribit_surface", hour - timedelta(seconds=osf.MAX_AGE_S), hour + timedelta(hours=1))
    if t is None or not t.num_rows:
        return None
    return osf.SurfaceSeries(osf.surfaces_from_rows(t.to_pylist()))


def _latest_meta(t) -> Dict[str, Dict]:
    meta: Dict[str, Dict] = {}
    if t is None:
        return meta
    for r in t.to_pylist():          # small: one row per market per change/hour
        meta[r["ticker"]] = {"series": r.get("series"), "open_ts": r.get("open_ts"), "close_ts": r.get("close_ts"),
                             "floor_strike": r.get("floor_strike"), "cap_strike": r.get("cap_strike")}
    return meta


BOOK_COLS = ("rt", "ticker", "kind", "side", "price", "qty", "upd_rt")  # what book_at_secs reads
TICKER_BATCH = int(os.getenv("TAU_FEATURES_TICKER_BATCH", "200"))  # tickers whose book is in memory at once
_SIDES = np.array(["yes", "no", None], dtype=object)  # kalshi_book side codes 0/1/2 (2 = snapshot reset)


def build_hour(store, hour: datetime, out_dir: str) -> Optional[Dict]:
    """Write features_1s for one hour as one Parquet file per series, <out_dir>/<series>.parquet,
    so a reader of KXBTC15M fetches a few MB, not every BTC contract. Returns {"rows",
    "tickers", "series": {series: rows}, "files": {series: path}}, or None when the hour has no
    market metadata (nothing was recorded)."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    hour = hour.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = hour + timedelta(hours=1)
    meta = _latest_meta(store.read("kalshi_markets", hour, end))
    if not meta:
        return None
    h0 = int(hour.timestamp())
    secs = np.arange(h0 + 1, h0 + 3601, dtype=np.int64)
    from data_pipeline.tick_recorder import spot_product
    spots: Dict[str, Dict[str, np.ndarray]] = {}
    def load(tickers: List[str]):
        """Book and trade columns for these tickers only: a whole hour of kalshi_book (~9M rows)
        held at once took the build past the archiver unit's 2 GB MemoryMax (prod 10-25 23:00Z on)."""
        book = store.read("kalshi_book", hour, end, tickers=tickers, columns=list(BOOK_COLS))
        trades = store.read("kalshi_trades", hour - timedelta(seconds=FLOW_LOOKBACK_S), end, tickers=tickers)
        bgroups, tgroups = _group(book, "ticker"), _group(trades, "ticker")
        bcols = {c: _np(book, c) for c in ("rt", "kind", "price", "qty", "upd_rt")} if bgroups else {}
        if bgroups:  # sides as int8 codes, decoded per ticker: millions of Python strings otherwise
            bcols["side"] = pc.fill_null(pc.index_in(book["side"], value_set=pa.array(_SIDES[:2])), 2) \
                .to_numpy(zero_copy_only=False).astype(np.int8)
        tcols = {c: _np(trades, c) for c in ("rt", "yes_price", "count", "taker_side")} if tgroups else {}
        return bgroups, bcols, tgroups, tcols

    sch = schema()
    writers: Dict[str, object] = {}
    pending: Dict[str, List] = {}
    files: Dict[str, str] = {}

    def flush(series: str) -> None:
        # One row group per ~1M rows, not per ticker: the spot columns repeat across a
        # series' tickers each second, so big row groups dictionary-encode them (3-4x smaller).
        if pending.get(series):
            writers[series].write_table(pa.concat_tables(pending[series]), row_group_size=ROW_GROUP)
            pending[series] = []

    per_series: Dict[str, int] = {}
    total, nt = 0, 0
    surfaces = False      # loaded on the first BTC contract
    pm = False
    try:
        ordered = sorted(meta)
        for k, ticker in enumerate(ordered):
            if k % TICKER_BATCH == 0:
                bgroups = bcols = tgroups = tcols = None  # drop the last batch before loading the next
                bgroups, bcols, tgroups, tcols = load(ordered[k:k + TICKER_BATCH])
            bi, ti = bgroups.get(ticker), tgroups.get(ticker)
            product = spot_product(meta[ticker].get("series") or ticker) or "BTC-USD"
            if product not in spots:
                spots[product] = spot_features(store, hour, product)
            if product == "BTC-USD" and surfaces is False:
                try:
                    surfaces = load_surfaces(store, hour)
                except Exception as e:  # noqa: BLE001 - the options columns are optional
                    print(f"[WARN] deribit surfaces for {hour:%Y-%m-%d %H}: {e}", flush=True)
                    surfaces = None
            if product == "BTC-USD" and pm is False:
                try:
                    pm = load_polymarket(store, hour)
                except Exception as e:  # noqa: BLE001 - the Polymarket columns are optional
                    print(f"[WARN] polymarket quotes for {hour:%Y-%m-%d %H}: {e}", flush=True)
                    pm = None
            rows = ticker_rows(ticker, meta[ticker], secs, spots[product],
                               {c: (_SIDES[v[bi]] if c == "side" else v[bi]) for c, v in bcols.items()}
                               if bi is not None else None,
                               {c: v[ti] for c, v in tcols.items()} if ti is not None else None,
                               surfaces if product == "BTC-USD" else None,
                               pm if product == "BTC-USD" else None)
            if rows is None:
                continue
            arrays = []
            for f in sch:
                v = rows[f.name]
                if f.type == pa.float32():
                    v = np.asarray(v, dtype=np.float64).astype(np.float32)
                elif f.type == pa.bool_():
                    v = np.asarray(v, dtype=bool)
                arrays.append(pa.array(v, type=f.type))
            series = str(rows["series"][0])
            for other in [k for k, v in pending.items() if v and k != series]:
                flush(other)  # tickers come sorted, so a series is done once another starts: free its buffer
            if series not in writers:
                files[series] = os.path.join(out_dir, series + ".parquet")
                writers[series] = pq.ParquetWriter(files[series], sch, compression="zstd")
            pending.setdefault(series, []).append(pa.Table.from_arrays(arrays, schema=sch))
            if sum(t.num_rows for t in pending[series]) >= ROW_GROUP:
                flush(series)
            per_series[series] = per_series.get(series, 0) + len(rows["sec"])
            total += len(rows["sec"])
            nt += 1
        for series in list(pending):
            flush(series)
    finally:
        for w in writers.values():
            w.close()
    return {"rows": total, "tickers": nt, "series": per_series, "files": files}
