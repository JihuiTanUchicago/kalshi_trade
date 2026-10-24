"""The other BRTI exchanges' BTC ticks: parsing for tick_archiver, per-second frames and the
cross-exchange composite for tick_store / tick_features.

Kalshi's BTC contracts settle on CF Benchmarks' BRTI, which is computed every second from the
BTC-USD order books of its constituent exchanges. tick_recorder's SpotRecorder writes each
venue's public feed verbatim (source = venue); this module turns those lines into two tables
per venue, same shape for every venue:

  <venue>_trades  rt, product, trade_id, price, size, taker_side ("buy"/"sell"/None), exch_ns
  <venue>_quotes  rt, product, bid, bid_size, ask, ask_size, exch_ns
                  (a row may carry one side only, e.g. Gemini's top-of-book changes: NULL = unchanged)

``product`` is canonical ("BTC-USD", "BTC-USDC") whatever the venue calls it. Bump
PARSER_VERSION when a parser changes: tick_archiver re-archives the last 48 hours of that
venue's raw lines with the new parser.

The composite (``composite_1s``) is the median across venues of each venue's mid, using only
venues whose book was updated in the last COMPOSITE_MAX_AGE_S. It is a proxy for the BRTI (the
real index is a volume-weighted median over each book's depth curve), good to a few dollars
when the venues agree, and it is what Kalshi's settlement tracks, unlike Coinbase alone.
"""
import json
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

PARSER_VERSION = 2      # 2: LMAX trade side inferred from the touch; repeated trades dropped
NS = 1_000_000_000
COMPOSITE_MAX_AGE_S = 60
QUOTE_COINS = ("USDC", "USDT", "USD")
_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$")


def _num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        f = _num(v)
        return None if f is None else int(f)


def _iso_ns(v) -> Optional[int]:
    """ISO-8601 time with any number of fractional digits -> epoch ns."""
    if not v:
        return None
    m = _ISO.match(str(v).strip())
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1) + (m.group(3) or "+00:00").replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(dt.timestamp()) * NS + int(((m.group(2) or "") + "000000000")[:9])


def canon(symbol) -> Optional[str]:
    """BTC/USD, btcusd, BTC_USD, btc-usd -> BTC-USD; BTCUSDC -> BTC-USDC."""
    if not symbol:
        return None
    s = str(symbol).upper().replace("/", "-").replace("_", "-")
    if "-" not in s:
        for q in QUOTE_COINS:
            if s.endswith(q) and len(s) > len(q):
                return s[:-len(q)] + "-" + q
    return s


def first_level(levels) -> Tuple[Optional[float], Optional[float]]:
    """(price, size) of the touch from [[p, q], ...], [{"price":.., "quantity":..}, ...], or a
    bare [p, q] / {"price":..} level."""
    if not levels:
        return None, None
    lv = levels[0] if isinstance(levels, (list, tuple)) and isinstance(levels[0], (list, tuple, dict)) else levels
    if isinstance(lv, dict):
        p = next((lv[k] for k in ("price", "px", "p") if k in lv), None)
        q = next((lv[k] for k in ("quantity", "amount", "size", "qty", "q") if k in lv), None)
        return _num(p), _num(q)
    if isinstance(lv, (list, tuple)):
        return _num(lv[0]) if lv else None, _num(lv[1]) if len(lv) > 1 else None
    return None, None


def _side(v) -> Optional[str]:
    s = str(v or "").lower()
    return s if s in ("buy", "sell") else None


def parse(source: str, rt: int, data, product_hint: Optional[str] = None) -> Iterable[Tuple[str, tuple]]:
    """(table, row) pairs for one venue message. Unknown shapes yield nothing (the raw line is
    archived regardless, so a later parser can still read it)."""
    if not isinstance(data, dict):
        return
    T, Q = source + "_trades", source + "_quotes"
    if source == "kraken":
        ch, typ = data.get("channel"), data.get("type")
        for t in data.get("data") or []:
            if not isinstance(t, dict):
                continue
            if ch == "trade" and typ == "update":
                yield T, (rt, canon(t.get("symbol")), str(t.get("trade_id")), _num(t.get("price")),
                          _num(t.get("qty")), _side(t.get("side")), _iso_ns(t.get("timestamp")))
            elif ch == "ticker":
                yield Q, (rt, canon(t.get("symbol")), _num(t.get("bid")), _num(t.get("bid_qty")),
                          _num(t.get("ask")), _num(t.get("ask_qty")), _iso_ns(t.get("timestamp")))
    elif source == "bitstamp":
        ch, ev, d = str(data.get("channel") or ""), data.get("event"), data.get("data") or {}
        if not isinstance(d, dict):
            return
        us = _int(d.get("microtimestamp"))
        exch = us * 1000 if us is not None else None
        if ev == "trade" and ch.startswith("live_trades_"):
            yield T, (rt, canon(ch[len("live_trades_"):]), str(d.get("id")),
                      _num(d.get("price_str", d.get("price"))), _num(d.get("amount_str", d.get("amount"))),
                      {0: "buy", 1: "sell"}.get(_int(d.get("type"))), exch)
        elif ev == "data" and ch.startswith("order_book_"):
            bp, bq = first_level(d.get("bids"))
            ap, aq = first_level(d.get("asks"))
            if bp is not None or ap is not None:
                yield Q, (rt, canon(ch[len("order_book_"):]), bp, bq, ap, aq, exch)
    elif source == "gemini":
        if data.get("type") != "update":
            return
        ms = _int(data.get("timestampms"))
        exch = ms * 1_000_000 if ms is not None else None
        prod = canon(product_hint or "BTCUSD")
        for e in data.get("events") or []:
            et = e.get("type")
            if et == "trade":
                yield T, (rt, prod, str(e.get("tid")), _num(e.get("price")), _num(e.get("amount")),
                          {"bid": "sell", "ask": "buy"}.get(e.get("makerSide")), exch)
            elif et == "change":
                p, q = _num(e.get("price")), _num(e.get("remaining"))
                if p is None or not q:
                    continue
                if e.get("side") == "bid":
                    yield Q, (rt, prod, p, q, None, None, exch)
                elif e.get("side") == "ask":
                    yield Q, (rt, prod, None, None, p, q, exch)
    elif source == "bullish":
        dt = str(data.get("dataType") or "")
        payload = data.get("data")
        if payload is None:
            return
        if "Trade" in dt:
            if data.get("type") == "snapshot":     # recent history sent on subscribe
                return
            items = payload.get("trades") if isinstance(payload, dict) and "trades" in payload else payload
            for t in items if isinstance(items, list) else [items]:
                if not isinstance(t, dict):
                    continue
                ms = _int(t.get("createdAtTimestamp") or t.get("publishedAtTimestamp"))
                yield T, (rt, canon(t.get("symbol")), str(t.get("tradeId")), _num(t.get("price")),
                          _num(t.get("quantity")), _side(t.get("side")),
                          ms * 1_000_000 if ms is not None else _iso_ns(t.get("createdAtDatetime")))
        elif "Level1" in dt or "L1" in dt.upper():
            d = payload if isinstance(payload, dict) else {}
            bp, bq = first_level(d.get("bid", d.get("bids")))
            ap, aq = first_level(d.get("ask", d.get("asks")))
            ms = _int(d.get("timestamp") or d.get("publishedAtTimestamp"))
            if bp is not None or ap is not None:
                yield Q, (rt, canon(d.get("symbol")), bp, bq, ap, aq,
                          ms * 1_000_000 if ms is not None else _iso_ns(d.get("datetime")))
    elif source == "cryptocom":
        res = data.get("result")
        if not isinstance(res, dict):
            return
        ch = res.get("channel")
        prod = canon(res.get("instrument_name"))
        for d in res.get("data") or []:
            if not isinstance(d, dict):
                continue
            ms = _int(d.get("t"))
            exch = ms * 1_000_000 if ms is not None else None
            if ch == "trade":
                if data.get("id") not in (-1, None):    # the subscribe answer carries a history snapshot
                    continue
                yield T, (rt, canon(d.get("i")) or prod, str(d.get("d")), _num(d.get("p")), _num(d.get("q")),
                          _side(d.get("s")), exch)
            elif ch == "ticker":
                yield Q, (rt, canon(d.get("i")) or prod, _num(d.get("b")), _num(d.get("bs")),
                          _num(d.get("k")), _num(d.get("ks")), exch)
    elif source == "lmax":
        typ = data.get("type")
        prod = canon(data.get("instrument_id"))
        exch = _iso_ns(data.get("timestamp"))
        if typ == "ORDER_BOOK":
            bp, bq = first_level(data.get("bids"))
            ap, aq = first_level(data.get("asks"))
            if bp is not None or ap is not None:
                yield Q, (rt, prod, bp, bq, ap, aq, exch)
        elif typ == "TICKER":
            bp, ap = _num(data.get("best_bid")), _num(data.get("best_ask"))
            if bp is not None or ap is not None:
                yield Q, (rt, prod, bp, None, ap, None, exch)
            px = _num(data.get("last_price"))
            if data.get("trade_id") is not None and px is not None:
                # LMAX gives no aggressor; the print is nearer the side it lifted. The last trade is
                # repeated on every ticker update; tick_archiver keeps its first appearance only.
                side = None
                if bp is not None and ap is not None and abs(px - ap) != abs(px - bp):
                    side = "buy" if abs(px - ap) < abs(px - bp) else "sell"
                yield T, (rt, prod, str(data.get("trade_id")), px, _num(data.get("last_quantity")), side, exch)


def parse_line(source: str, line: str, product_hint: Optional[str] = None) -> Iterable[Tuple[str, tuple]]:
    rec = json.loads(line)
    if "m" not in rec:
        return
    yield from parse(source, int(rec["rt"]), rec["m"], product_hint)


# --- per-second frames ------------------------------------------------------------------------

def _col(t, name) -> np.ndarray:
    return t[name].to_numpy(zero_copy_only=False)


def quotes_1s(quotes, s0: int, s1: int, bid_col: str = "bid", ask_col: str = "ask") -> Dict[str, np.ndarray]:
    """Dense seconds s0+1..s1: best bid/ask as of the end of each second (each side carried
    forward on its own, so one-sided rows work), mid, and age_s = seconds since the last quote
    row (NaN before the first). Start s0 a few minutes early and slice, so the first seconds
    have a quote and an honest age. ``quotes`` must be in rt order (archive file order is)."""
    from data_pipeline.tick_store import _ffill
    secs = np.arange(s0 + 1, s1 + 1, dtype=np.int64)
    n = len(secs)
    bid, ask, seen = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, dtype=bool)
    if quotes is not None and quotes.num_rows:
        idx = (_col(quotes, "rt") // NS + 1 - (s0 + 1)).astype(np.int64)
        b, a = _col(quotes, bid_col).astype(float), _col(quotes, ask_col).astype(float)
        ok = (idx >= 0) & (idx < n)
        for arr, src in ((bid, b), (ask, a)):
            m = ok & ~np.isnan(src)
            arr[idx[m]] = src[m]            # last write per second wins
        seen[idx[ok]] = True
    bid, ask = _ffill(bid), _ffill(ask)
    pos = np.where(seen, np.arange(n), -10**9)
    last = np.maximum.accumulate(pos) if n else pos
    age = np.where(last >= 0, np.arange(n) - last, np.nan).astype(float)
    with np.errstate(invalid="ignore"):
        mid = np.where((bid > 0) & (ask > 0) & (ask >= bid), (bid + ask) / 2, np.nan)
    return {"sec": secs, "bid": bid, "ask": ask, "mid": mid, "age_s": age}


def composite(mids: Dict[str, np.ndarray], ages: Dict[str, np.ndarray],
              max_age_s: float = COMPOSITE_MAX_AGE_S) -> Tuple[np.ndarray, np.ndarray]:
    """(median mid across venues quoted within the last max_age_s, number of venues used) per
    second."""
    names = sorted(mids)
    if not names:
        return np.array([]), np.array([])
    m = np.vstack([mids[v] for v in names]).astype(float)
    a = np.vstack([ages[v] for v in names]).astype(float)
    with np.errstate(invalid="ignore"):
        use = ~np.isnan(m) & (a <= max_age_s)
    n = use.sum(axis=0).astype(float)
    vals = np.sort(np.where(use, m, np.inf), axis=0)      # unused venues sort last
    med = np.full(m.shape[1], np.nan)
    cols = np.nonzero(n > 0)[0]
    k = n[cols].astype(np.int64)
    lo, hi = vals[(k - 1) // 2, cols], vals[k // 2, cols]
    med[cols] = (lo + hi) / 2
    return med, n
