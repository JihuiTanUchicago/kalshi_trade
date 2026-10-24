"""Read the tick archive (tick_archiver's S3 Parquet) and build per-second frames for research,
backtests and the live engine.

    from data_pipeline.tick_store import TickStore
    ts = TickStore()
    book = ts.book_1s(["KXBTC15M-26OCT241500-00"], start, end)    # {column: np.ndarray}
    spot = ts.spot_1s(start, end)                                  # Coinbase BTC-USD, dense 1s
    comp = ts.composite_1s(start, end)                             # median mid over the BRTI venues
    flow = ts.trades_1s(["KXBTC15M-26OCT241500-00"], start, end)
    raw  = ts.read("kalshi_trades", start, end, tickers=[...])     # pyarrow.Table, tick level
    feat = ts.features_1s(start, end, series=["KXBTC15M"])          # prebuilt per-second features

Frames are columnar dicts of numpy arrays keyed by column name (``sec`` = epoch second, the
END of the second: state after every event with rt < sec). pandas.DataFrame(frame) works where
pandas is installed. Files are cached under TAU_TICK_CACHE, so a second read of the same hours
is local. Only closed, archived hours are visible (the current hour is still on the collector
box's disk). Hours with no archive (recorder down) are simply absent; check
``coverage(source, start, end)`` before trusting a window, it reads the manifest.

Memory: one table-hour filtered to a few tickers is small; the whole kalshi_book hour for every
BTC contract is the big one, so always pass ``tickers`` to book reads.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

BUCKET = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-568386354218-us-east-1")
PREFIX = os.getenv("TAU_TICK_PREFIX", "ticks")
CACHE = os.getenv("TAU_TICK_CACHE", os.path.expanduser("~/.cache/kalshi_ticks"))
NS = 1_000_000_000


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def hours_between(start: datetime, end: datetime) -> List[datetime]:
    h = _utc(start).replace(minute=0, second=0, microsecond=0)
    end = _utc(end)
    out = []
    while h < end:
        out.append(h)
        h += timedelta(hours=1)
    return out


class TickStore:
    def __init__(self, bucket: str = BUCKET, prefix: str = PREFIX, cache_dir: str = CACHE, s3=None,
                 local_root: Optional[str] = None) -> None:
        """``local_root``: read <local_root>/<key> instead of S3 (tests, or a synced copy)."""
        self.bucket, self.prefix, self.cache_dir = bucket, prefix, cache_dir
        self._s3 = s3
        self.local_root = local_root

    # --- files -----------------------------------------------------------------------------
    def _client(self):
        if self._s3 is None:
            import boto3
            self._s3 = boto3.client("s3")
        return self._s3

    def _fetch(self, key: str) -> Optional[str]:
        """Local path of ``key`` (downloaded into the cache once), or None if it does not exist."""
        if self.local_root is not None:
            p = os.path.join(self.local_root, key)
            return p if os.path.exists(p) else None
        p = os.path.join(self.cache_dir, key)
        if os.path.exists(p):
            return p
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            self._client().download_file(self.bucket, key, p + ".part")
        except Exception as e:  # noqa: BLE001 - a missing hour is normal (recorder down, not yet archived)
            code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
            if code in ("404", "NoSuchKey", "NotFound") or "404" in str(e) or "Not Found" in str(e):
                return None
            raise
        os.replace(p + ".part", p)
        return p

    def table_key(self, table: str, hour: datetime) -> str:
        return f"{self.prefix}/v1/{table}/date={hour:%Y-%m-%d}/hour={hour:%H}/part.parquet"

    def read(self, table: str, start: datetime, end: datetime, tickers: Optional[Sequence[str]] = None,
             columns: Optional[List[str]] = None, pad_hours_before: int = 0):
        """Rows of a raw tick ``table`` with start <= rt < end as one pyarrow.Table in file order.
        ``tickers`` filters kalshi_* tables (product ids for coinbase_*). For features use
        features_1s()."""
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        start, end = _utc(start), _utc(end)
        key_col = ("product_id" if table.startswith("coinbase") else "ticker" if table.startswith("kalshi")
                   else "product" if table.endswith(("_trades", "_quotes")) else "ticker")
        filters = []
        if tickers:
            filters.append((key_col, "in", list(tickers)))
        parts = []
        for h in hours_between(start - timedelta(hours=pad_hours_before), end):
            p = self._fetch(self.table_key(table, h))
            if p is None:
                continue
            parts.append(pq.read_table(p, columns=columns, filters=filters or None, partitioning=None))
        if not parts:
            return None
        t = pa.concat_tables(parts)
        lo = int((start - timedelta(hours=pad_hours_before)).timestamp() * NS)
        mask = pc.and_(pc.greater_equal(t["rt"], lo), pc.less(t["rt"], int(end.timestamp() * NS)))
        return t.filter(mask)

    def coverage(self, source: str, start: datetime, end: datetime) -> List[Dict]:
        """The archiver's manifest per hour in the window: messages, max_gap_s, seq_gaps,
        reconnects. A missing hour comes back as {"hour_utc": ..., "missing": True}."""
        out = []
        for h in hours_between(start, end):
            p = self._fetch(f"{self.prefix}/manifest/{source}/date={h:%Y-%m-%d}/{h:%H}.json")
            if p is None:
                out.append({"hour_utc": h.strftime("%Y-%m-%d %H:00:00"), "missing": True})
            else:
                with open(p) as fh:
                    out.append(json.load(fh))
        return out

    # --- frames ----------------------------------------------------------------------------
    def features_1s(self, start: datetime, end: datetime, tickers: Optional[Sequence[str]] = None,
                    series: Optional[Sequence[str]] = None, columns: Optional[List[str]] = None) -> Dict[str, np.ndarray]:
        """The prebuilt per-second feature table (data_pipeline/tick_features.py), start < sec <= end,
        as {column: np.ndarray}. Filter by ``series`` (e.g. ["KXBTC15M"]) and/or ``tickers``; only
        those series' files are fetched (one per series per hour). With neither, every series the
        hour's manifest lists is read."""
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        start, end = _utc(start), _utc(end)
        wanted = list(series) if series else sorted({t.split("-")[0] for t in tickers}) if tickers else None
        filters = [("ticker", "in", list(tickers))] if tickers else None
        parts = []
        for h in hours_between(start, end + timedelta(seconds=1)):   # sec == end lives in end's hour
            names = wanted
            if names is None:
                man = self._fetch(f"{self.prefix}/manifest/features_1s/date={h:%Y-%m-%d}/{h:%H}.json")
                if man is None:
                    continue
                with open(man) as fh:
                    names = sorted(((json.load(fh).get("tables") or {}).get("series") or {}))
            for name in names:
                p = self._fetch(f"{self.prefix}/v1/features_1s/date={h:%Y-%m-%d}/hour={h:%H}/series={name}/part.parquet")
                if p is not None:
                    cols = columns
                    if columns is not None:
                        have = set(pq.read_schema(p).names)
                        cols = [c for c in columns if c in have]
                    parts.append(pq.read_table(p, columns=cols, filters=filters, partitioning=None))
        if not parts:
            return {}
        # Hours built before a column existed lack it; promote fills those rows with nulls.
        t = pa.concat_tables(parts, promote_options="default")
        if "sec" in t.column_names:
            t = t.filter(pc.and_(pc.greater(t["sec"], int(start.timestamp())), pc.less_equal(t["sec"], int(end.timestamp()))))
        return {name: t[name].to_numpy(zero_copy_only=False) for name in t.column_names}

    def book_1s(self, tickers: Sequence[str], start: datetime, end: datetime,
                depth_within: float = 0.05) -> Dict[str, np.ndarray]:
        """Per ticker per second: Kalshi YES best bid/ask with sizes, depth within
        ``depth_within`` dollars of each touch, and the count of book updates in that second.
        Replays from the top of start's hour, where the recorder wrote a full checkpoint."""
        t = self.read("kalshi_book", _utc(start).replace(minute=0, second=0, microsecond=0), end,
                      tickers=tickers)
        return replay_book(t, start, end, depth_within)

    def trades_1s(self, tickers: Sequence[str], start: datetime, end: datetime) -> Dict[str, np.ndarray]:
        """Per ticker per second with prints: count, contracts, YES-taker and NO-taker contracts,
        volume-weighted YES price, last YES price."""
        t = self.read("kalshi_trades", start, end, tickers=tickers)
        return aggregate_kalshi_trades(t)

    def spot_1s(self, start: datetime, end: datetime, product: str = "BTC-USD") -> Dict[str, np.ndarray]:
        """Dense Coinbase seconds over [start, end): last trade price, best bid/ask (forward
        filled), traded size, taker-buy and taker-sell size, number of prints."""
        trades = self.read("coinbase_trades", start, end, tickers=[product])
        ticker = self.read("coinbase_ticker", start, end, tickers=[product])
        return aggregate_spot(trades, ticker, start, end)

    def venue_quotes_1s(self, venue: str, start: datetime, end: datetime, product: str = "BTC-USD",
                        lookback_s: int = 300) -> Dict[str, np.ndarray]:
        """Dense seconds over (start, end] for one venue ("coinbase", "kraken", ...): best bid,
        ask, mid and age_s (seconds since its last quote). Quotes from ``lookback_s`` before
        start are replayed so the first seconds have a book and an honest age."""
        from data_pipeline.tick_spot import quotes_1s
        s0, s1 = int(_utc(start).timestamp()), int(_utc(end).timestamp())
        lo = _utc(start) - timedelta(seconds=lookback_s)
        if venue == "coinbase":
            q = self.read("coinbase_ticker", lo, end, tickers=[product], columns=["rt", "product_id", "best_bid", "best_ask"])
            fr = quotes_1s(q, s0 - lookback_s, s1, "best_bid", "best_ask")
        else:
            q = self.read(venue + "_quotes", lo, end, tickers=[product], columns=["rt", "product", "bid", "ask"])
            fr = quotes_1s(q, s0 - lookback_s, s1)
        return {k: v[lookback_s:] for k, v in fr.items()}

    def composite_1s(self, start: datetime, end: datetime, product: str = "BTC-USD",
                     venues: Optional[Sequence[str]] = None, max_age_s: Optional[float] = None) -> Dict[str, np.ndarray]:
        """Cross-exchange BTC price per second over (start, end]: ``spot_comp`` = median mid of
        the venues quoted in the last ``max_age_s`` (default tick_spot.COMPOSITE_MAX_AGE_S),
        ``n_venues`` used, and each venue's ``mid_<venue>`` / ``age_<venue>``. A proxy for
        the BRTI that Kalshi BTC contracts settle on. Default venues: Coinbase plus every
        recorded BRTI venue."""
        from data_pipeline.tick_recorder import SPOT_VENUES
        from data_pipeline.tick_spot import COMPOSITE_MAX_AGE_S, composite
        venues = list(venues) if venues else ["coinbase"] + list(SPOT_VENUES)
        mids, ages = {}, {}
        secs = None
        for v in venues:
            fr = self.venue_quotes_1s(v, start, end, product)
            secs = fr["sec"]
            mids[v], ages[v] = fr["mid"], fr["age_s"]
        comp, n = composite(mids, ages, COMPOSITE_MAX_AGE_S if max_age_s is None else max_age_s)
        out = {"sec": secs, "spot_comp": comp, "n_venues": n}
        for v in venues:
            out["mid_" + v], out["age_" + v] = mids[v], ages[v]
        return out


def _col(t, name) -> np.ndarray:
    return t[name].to_numpy(zero_copy_only=False)


def replay_book(t, start: datetime, end: datetime, depth_within: float = 0.05) -> Dict[str, np.ndarray]:
    cols = {k: [] for k in ("sec", "ticker", "yes_bid", "yes_bid_size", "yes_ask", "yes_ask_size",
                            "bid_depth", "ask_depth", "updates")}
    if t is None or t.num_rows == 0:
        return {k: np.array(v) for k, v in cols.items()}
    s0, s1 = int(_utc(start).timestamp()), int(_utc(end).timestamp())
    rt, tick, kind = _col(t, "rt"), _col(t, "ticker"), _col(t, "kind")
    side, price, qty = _col(t, "side"), _col(t, "price"), _col(t, "qty")
    books: Dict[str, Dict[str, Dict[float, float]]] = {}
    updates: Dict[str, int] = {}

    def emit(sec: int) -> None:
        for tk, b in books.items():
            yes, no = b["yes"], b["no"]
            bb = max(yes) if yes else None
            bn = max(no) if no else None   # best NO bid -> YES ask = 1 - bn
            cols["sec"].append(sec)
            cols["ticker"].append(tk)
            cols["yes_bid"].append(bb if bb is not None else np.nan)
            cols["yes_bid_size"].append(yes[bb] if bb is not None else 0.0)
            cols["yes_ask"].append(round(1.0 - bn, 4) if bn is not None else np.nan)
            cols["yes_ask_size"].append(no[bn] if bn is not None else 0.0)
            cols["bid_depth"].append(sum(q for p, q in yes.items() if bb is not None and p >= bb - depth_within - 1e-9))
            cols["ask_depth"].append(sum(q for p, q in no.items() if bn is not None and p >= bn - depth_within - 1e-9))
            cols["updates"].append(updates.get(tk, 0))
        updates.clear()

    next_sec = s0 + 1
    for i in range(len(rt)):
        sec_of_row = int(rt[i] // NS) + 1           # an event is visible at the end of its second
        while next_sec < sec_of_row and next_sec <= s1:
            emit(next_sec)
            next_sec += 1
        if sec_of_row > s1:
            break
        tk, k = tick[i], int(kind[i])
        if k in (0, 3):
            if side[i] is None:          # reset marker: the snapshot/checkpoint levels follow
                books[tk] = {"yes": {}, "no": {}}
                continue
            books.setdefault(tk, {"yes": {}, "no": {}})[side[i]][float(price[i])] = float(qty[i])
        elif k == 1 and tk in books and side[i] in ("yes", "no") and price[i] == price[i]:
            lv = books[tk][side[i]]
            q = lv.get(float(price[i]), 0.0) + float(qty[i])
            if q <= 1e-9:
                lv.pop(float(price[i]), None)
            else:
                lv[float(price[i])] = q
            if sec_of_row > s0:
                updates[tk] = updates.get(tk, 0) + 1
    while next_sec <= s1:
        emit(next_sec)
        next_sec += 1
    return {k: np.array(v) for k, v in cols.items()}


def aggregate_kalshi_trades(t) -> Dict[str, np.ndarray]:
    names = ("sec", "ticker", "n", "contracts", "yes_taker", "no_taker", "vwap_yes", "last_yes")
    if t is None or t.num_rows == 0:
        return {k: np.array([]) for k in names}
    rt, tick = _col(t, "rt"), _col(t, "ticker")
    px, cnt, side = _col(t, "yes_price").astype(float), _col(t, "count").astype(float), _col(t, "taker_side")
    agg: Dict[tuple, List[float]] = {}
    order: List[tuple] = []
    for i in range(len(rt)):
        key = (int(rt[i] // NS) + 1, tick[i])
        a = agg.get(key)
        if a is None:
            a = agg[key] = [0, 0.0, 0.0, 0.0, 0.0, np.nan]
            order.append(key)
        c = 0.0 if cnt[i] != cnt[i] else cnt[i]
        a[0] += 1
        a[1] += c
        if side[i] == "yes":
            a[2] += c
        elif side[i] == "no":
            a[3] += c
        if px[i] == px[i]:
            a[4] += px[i] * c
            a[5] = px[i]
    order.sort()
    out = {k: [] for k in names}
    for key in order:
        a = agg[key]
        out["sec"].append(key[0])
        out["ticker"].append(key[1])
        out["n"].append(a[0])
        out["contracts"].append(a[1])
        out["yes_taker"].append(a[2])
        out["no_taker"].append(a[3])
        out["vwap_yes"].append(a[4] / a[1] if a[1] else np.nan)
        out["last_yes"].append(a[5])
    return {k: np.array(v) for k, v in out.items()}


def aggregate_spot(trades, ticker, start: datetime, end: datetime) -> Dict[str, np.ndarray]:
    s0, s1 = int(_utc(start).timestamp()), int(_utc(end).timestamp())
    secs = np.arange(s0 + 1, s1 + 1)
    n = len(secs)
    last = np.full(n, np.nan)
    size, buy, sell, cnt = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n, dtype=np.int64)
    bid, ask = np.full(n, np.nan), np.full(n, np.nan)
    if trades is not None and trades.num_rows:
        idx = (_col(trades, "rt") // NS + 1 - (s0 + 1)).astype(np.int64)
        px, sz, side = _col(trades, "price").astype(float), _col(trades, "size").astype(float), _col(trades, "taker_side")
        ok = (idx >= 0) & (idx < n)
        for i in np.nonzero(ok)[0]:
            j = idx[i]
            last[j] = px[i]
            size[j] += sz[i]
            cnt[j] += 1
            if side[i] == "buy":
                buy[j] += sz[i]
            elif side[i] == "sell":
                sell[j] += sz[i]
    if ticker is not None and ticker.num_rows:
        idx = (_col(ticker, "rt") // NS + 1 - (s0 + 1)).astype(np.int64)
        bb, ba = _col(ticker, "best_bid").astype(float), _col(ticker, "best_ask").astype(float)
        ok = (idx >= 0) & (idx < n)
        bid[idx[ok]] = bb[ok]          # numpy fancy assignment keeps the last write per second
        ask[idx[ok]] = ba[ok]
    return {"sec": secs, "price": _ffill(last), "bid": _ffill(bid), "ask": _ffill(ask), "size": size,
            "taker_buy": buy, "taker_sell": sell, "n": cnt}


def _ffill(a: np.ndarray) -> np.ndarray:
    a = a.copy()
    mask = np.isnan(a)
    if not mask.any():
        return a
    idx = np.where(~mask, np.arange(len(a)), 0)
    np.maximum.accumulate(idx, out=idx)
    out = a[idx]
    out[np.isnan(a) & (np.cumsum(~mask) == 0)] = np.nan
    return out
