"""Polymarket Bitcoin binaries: a second venue's price for the same BTC events Kalshi lists.

Read only, public, keyless. Every call is an unauthenticated GET (or the CLOB's POST /books, a
batched read) on Gamma (market catalog) and the CLOB (order books, price history). No account,
no API key, no wallet, no orders. If an endpoint ever asks for a key, the recorder logs the
refusal and records nothing from it: we do not work around it.

What Polymarket lists that lines up with Kalshi (classify() below):

  updown   "Bitcoin Up or Down - October 25, 4:00AM-4:15AM ET": YES = BTC at the window's end is at
           or above its start (15-minute windows: Chainlink's BTC/USD 60-second TWAP stream, close to
           Kalshi's 60-second BRTI average rule; hourly: the Binance BTC/USDT 1h candle).
           The 15-minute window is the same event as a KXBTC15M contract (open, close) = (start, end).
  above    "Will the price of Bitcoin be above $110,000 on October 25?" (daily, 12:00 PM ET, Binance
           BTC/USDT one-minute close). A ladder of strikes per day: a survival curve that prices a
           KXBTCD / KXBTC contract settling at the same time (trading_core.pricing.binary_curve).
  below    "... less than $100,000 on ..." (1 - above)
  range    "... between $108,000 and $110,000 on ..." (recorded; not yet used for pricing)
  touch_up / touch_down   "Will Bitcoin reach $130,000 in October?" (recorded only; path dependent)

Settlement sources differ (Kalshi: CF Benchmarks BRTI, 60-second average; Polymarket: Chainlink or
Binance at one instant), so a gap of a cent or two is basis, not mispricing.

Live: every POLL_S seconds the recorder fetches the books of every BTC market that ends within
the book horizon, and every DISCOVER_S seconds the catalog, and
  * appends both verbatim (books trimmed to LEVELS a side) to the tick directory as source
    "polymarket"; tick_archiver turns each hour into polymarket_markets and polymarket_top
    (one row per token per poll) and keeps the raw gzip;
  * writes the latest priced snapshot into its heartbeat (collector_state tick_recorder_polymarket),
    which the live engine reads (app/adapters/polymarket).

History: the CLOB keeps a one-minute price series per token, also for resolved markets, so a
background pass writes, per past UTC day, every 15-minute and hourly up/down window and the daily
strike ladders that ended that day:

  ticks/v1/polymarket_history_day/v=<HIST_VERSION>/date=YYYY-MM-DD/part.parquet   HIST_FIELDS rows,
                                                                       one per market per minute

with a stats line per day under ticks/manifest/polymarket_history/ (markets found, errors).

On start the recorder writes a probe report (status and a sample of each endpoint it uses) to
ticks/manifest/polymarket_probe/, so reachability is checkable from S3 alone.

Run:  python -m data_pipeline.polymarket record        (unit polymarket-recorder, COLLECTOR box)
      python -m data_pipeline.polymarket backfill [days]
      python -m data_pipeline.polymarket probe
"""
import bisect
import json
import math
import os
import re
import socket
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import requests

from trading_core.pricing import binary_curve

GAMMA = os.getenv("TAU_POLYMARKET_GAMMA", "https://gamma-api.polymarket.com")
CLOB = os.getenv("TAU_POLYMARKET_CLOB", "https://clob.polymarket.com")
POLL_S = float(os.getenv("TAU_POLYMARKET_POLL_S", "5"))
DISCOVER_S = float(os.getenv("TAU_POLYMARKET_DISCOVER_S", "60"))
HEARTBEAT_S = 10.0
HORIZON_S = 8 * 86400            # catalog: markets ending within this
DAILY_BOOK_HORIZON_S = 36 * 3600  # books: daily ladders ending within this
UPDOWN_BOOK_HORIZON_S = 2 * 3600  # books: up/down windows ending within this (Polymarket lists days ahead)
MIN_UPDOWN_S = 900                # 5-minute windows have no Kalshi twin: catalog only
LEVELS = 10
BOOKS_CHUNK = 50
DEPTH = 0.05
MAX_SPREAD = 0.20                 # a wider book has no usable mid
# Kalshi series whose strike is the price at the window's open (so a contract IS an up/down window).
# Only these may match a Polymarket up/down market; a KXBTCD contract opening at the same time has a
# fixed strike and must not.
UPDOWN_SERIES = frozenset({"KXBTC15M"})
MIN_STRIKE = 1000.0               # a BTC price strike; smaller numbers are percentages or caps
END_TOL_S = 90                    # Polymarket and Kalshi settlement times that count as the same
HIST_DAYS = int(os.getenv("TAU_POLYMARKET_HIST_DAYS", "60"))
HIST_PASS_S = 3600
HIST_PAUSE_S = 0.12
BUCKET = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-568386354218-us-east-1")
PREFIX = os.getenv("TAU_TICK_PREFIX", "ticks")
HEARTBEAT_KEY = "tick_recorder_polymarket"
DAY_TABLE = "polymarket_history_day"
HIST_VERSION = 2                  # bump to rebuild every day file (a parser fix) without deleting the old ones
SOURCE = "polymarket"
ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "kalshi-trade-research/1.0 (read-only market data)"}

# Gamma market fields kept in the catalog line (enough for classify() to run again in the archiver).
KEEP = ("id", "slug", "question", "conditionId", "clobTokenIds", "outcomes", "outcomePrices", "endDate",
        "startDate", "eventStartTime", "startTime", "groupItemTitle", "groupItemThreshold", "bestBid", "bestAsk",
        "lastTradePrice", "volume", "liquidity", "active", "closed", "acceptingOrders", "orderPriceMinTickSize",
        "negRisk", "umaResolutionStatus", "resolutionSource")
DESC_CHARS = 600
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
KINDS = ("updown", "above", "below", "range", "touch_up", "touch_down")
PRICED_KINDS = ("updown", "above", "below")

MARKET_FIELDS = ("market_id", "slug", "event_slug", "question", "condition_id", "yes_token", "no_token",
                 "yes_label", "kind", "strike_lo", "strike_hi", "start_ts", "end_ts", "tick")
# The research vocabulary for the pm_* features (app.markets.FEATURES; app/adapters/polymarket computes
# them for candle markets and the engine, tick_features for the per-second datasets).
FEATURE_DOCS = {
    "pm_p_yes": "Bitcoin strike markets only: Polymarket's probability for the same event (its 15-minute "
                "up/down window with this contract's open and close for KXBTC15M; its daily strike ladder "
                "read at this contract's strike for KXBTCD/KXBTC settling at noon ET). Absent when Polymarket "
                "lists no twin. Settlement sources differ (Chainlink/Binance vs CF BRTI), so ~1-2c is basis",
    "pm_edge": "Bitcoin strike markets only: pm_p_yes minus the contract's mid (positive = YES cheap vs Polymarket)",
    "pm_spread": "Bitcoin strike markets only: Polymarket's YES bid-ask spread behind pm_p_yes (0 on minute history)",
    "pm_age_s": "Bitcoin strike markets only: seconds since the Polymarket quote behind pm_p_yes",
}
HIST_FIELDS = ("t", "market_id", "slug", "kind", "strike_lo", "strike_hi", "start_ts", "end_ts", "p", "resolved")


# --- markets ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class PmMarket:
    market_id: str
    slug: str
    event_slug: str
    question: str
    condition_id: str
    yes_token: str
    no_token: str
    yes_label: str
    kind: str
    strike_lo: Optional[float]
    strike_hi: Optional[float]
    start_ts: Optional[int]
    end_ts: Optional[int]
    tick: float = 0.01

    def row(self) -> Dict:
        return {f: getattr(self, f) for f in MARKET_FIELDS}


def _jlist(v) -> List:
    """Gamma sends clobTokenIds/outcomes/outcomePrices as JSON-encoded strings."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip().startswith("["):
        try:
            out = json.loads(v)
            return out if isinstance(out, list) else []
        except ValueError:
            return []
    return []


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _iso_s(v) -> Optional[int]:
    if not v or not isinstance(v, str):
        return None
    s = v.strip().replace("Z", "+00:00")
    if len(s) == 10:                       # a bare date
        s += "T00:00:00+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _money(s: str) -> Optional[float]:
    """"$110,000" / "110k" / "1.2m" -> float."""
    m = re.match(r"\$?\s*([\d,]*\.?\d+)\s*([kKmM])?", s.strip())
    if not m:
        return None
    try:
        x = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    mult = {"k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1.0)
    return x * mult


_NUM = r"\$?\s*[\d,]*\.?\d+\s*[kKmM]?"
_SLUG_UPDOWN = re.compile(r"(?:btc|bitcoin)-(?:updown|up-or-down)-(\d+)(m|h)-(\d{9,11})")
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?"
_DATE = r"(" + "|".join(m.capitalize() for m in MONTHS) + r"|" + "|".join(MONTHS) + r")\s+(\d{1,2})"


def _et_ts(d: date, hh: int, mm: int, ampm: str) -> int:
    h = hh % 12 + (12 if ampm.lower().startswith("p") else 0)
    return int(datetime(d.year, d.month, d.day, h, mm, tzinfo=ET).timestamp())


def _date_near(month: str, day: int, ref_ts: int) -> Optional[date]:
    """The (month, day) closest to ref_ts across the neighbouring years."""
    try:
        mon = MONTHS.index(month.lower()) + 1
    except ValueError:
        return None
    ref = datetime.fromtimestamp(ref_ts, tz=ET).date()
    best = None
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            d = date(y, mon, day)
        except ValueError:
            continue
        if best is None or abs((d - ref).days) < abs((best - ref).days):
            best = d
    return best


def is_btc(text: str) -> bool:
    return bool(re.search(r"\b(bitcoin|btc)\b", text or "", re.I))


def classify(m: Dict, event: Optional[Dict] = None, now_ts: Optional[int] = None) -> Optional[PmMarket]:
    """A Gamma market (raw or as kept in the catalog line) as a PmMarket, or None when it is not a
    Bitcoin binary we understand. ``event`` supplies the slug and description when the market's
    own are missing."""
    event = event or {}
    q = str(m.get("question") or "")
    slug = str(m.get("slug") or "")
    ev_slug = str(m.get("event_slug") or event.get("slug") or "")
    if not (is_btc(q) or is_btc(slug.replace("-", " ")) or is_btc(ev_slug.replace("-", " "))):
        return None
    toks = [str(t) for t in _jlist(m.get("clobTokenIds"))]
    outs = [str(o) for o in _jlist(m.get("outcomes"))]
    if len(toks) != 2:
        return None
    yi = 0
    for i, o in enumerate(outs[:2]):
        if o.strip().lower() in ("yes", "up"):
            yi = i
            break
    yes_label = outs[yi] if len(outs) == 2 else "Yes"
    end_ts = _iso_s(m.get("endDate")) or _iso_s(event.get("endDate"))
    ref = end_ts or now_ts or int(time.time())
    desc = str(m.get("description") or event.get("description") or "")
    ql = q.lower()
    lo = hi = start = None
    end = end_ts
    kind = None
    su = _SLUG_UPDOWN.search(slug) or _SLUG_UPDOWN.search(ev_slug)
    if "up or down" in ql or su:
        kind = "updown"
        if su:
            dur = int(su.group(1)) * (60 if su.group(2) == "m" else 3600)
            start = int(su.group(3))
            end = start + dur
        else:
            start = _iso_s(m.get("eventStartTime")) or _iso_s(m.get("startTime"))
            dm = re.search(_DATE, q)
            d = _date_near(dm.group(1), int(dm.group(2)), ref) if dm else None
            tm = re.search(_TIME + r"(?:\s*-\s*" + _TIME + r")?\s*ET", q)
            if d is not None and tm:
                t0 = _et_ts(d, int(tm.group(1)), int(tm.group(2) or 0), tm.group(3))
                if tm.group(4):
                    t1 = _et_ts(d, int(tm.group(4)), int(tm.group(5) or 0), tm.group(6))
                    if t1 <= t0:
                        t1 += 86400
                else:
                    t1 = t0 + 3600          # "4AM ET": the hour starting then
                start, end = start or t0, t1
            elif start is not None and end_ts is not None:
                end = end_ts
    else:
        rm = re.search(r"between\s+(" + _NUM + r")\s+and\s+(" + _NUM + r")", q, re.I)
        am = re.search(r"(?:above|greater than|over|higher than)\s+(" + _NUM + r")", q, re.I)
        bm = re.search(r"(?:below|less than|under|lower than)\s+(" + _NUM + r")", q, re.I)
        um = re.search(r"\b(?:reach|hit)\s+(" + _NUM + r")", q, re.I)
        dn = re.search(r"\b(?:dip|fall|drop)\s+to\s+(" + _NUM + r")", q, re.I)
        if rm:
            kind, lo, hi = "range", _money(rm.group(1)), _money(rm.group(2))
        elif um:
            kind, lo = "touch_up", _money(um.group(1))
        elif dn:
            kind, hi = "touch_down", _money(dn.group(1))
        elif am:
            kind, lo = "above", _money(am.group(1))
        elif bm:
            kind, hi = "below", _money(bm.group(1))
        if kind in ("above", "below", "range"):
            # the settlement instant: the date in the question at the ET time the rules name
            dm = re.search(r"\bon\s+" + _DATE, q) or re.search(_DATE, q)
            tm = re.search(_TIME + r"\s*(?:ET|EST|EDT)", desc) or re.search(r"\b(noon)\b", desc, re.I)
            d = _date_near(dm.group(1), int(dm.group(2)), ref) if dm else None
            if d is not None and tm:
                if tm.group(1).lower() == "noon":
                    end = _et_ts(d, 12, 0, "pm")
                else:
                    end = _et_ts(d, int(tm.group(1)), int(tm.group(2) or 0), tm.group(3))
    if kind is None:
        return None
    if kind in ("above", "touch_up") and lo is None or kind in ("below", "touch_down") and hi is None:
        return None
    if kind == "range" and (lo is None or hi is None):
        return None
    if any(x is not None and x < MIN_STRIKE for x in (lo, hi)):
        return None                     # "dominance above 60%", "market cap above $2T": not a price
    return PmMarket(str(m.get("id") or ""), slug, ev_slug, q[:300], str(m.get("conditionId") or ""),
                    toks[yi], toks[1 - yi], yes_label, kind, lo, hi, start, end,
                    _f(m.get("orderPriceMinTickSize")) or 0.01)


def compact(m: Dict, event: Optional[Dict] = None) -> Dict:
    """What the catalog line keeps of one Gamma market."""
    event = event or {}
    out = {k: m.get(k) for k in KEEP if k in m}
    desc = m.get("description") or event.get("description") or ""
    out["description"] = str(desc)[:DESC_CHARS]
    out["event_slug"] = m.get("event_slug") or event.get("slug")
    out["event_title"] = m.get("event_title") or event.get("title")
    return out


def resolved_yes(m: Dict, pm: PmMarket) -> Optional[float]:
    """1.0 / 0.0 once Gamma shows the market closed with a 1/0 price, else None."""
    if not m.get("closed"):
        return None
    prices = [_f(p) for p in _jlist(m.get("outcomePrices"))]
    outs = [str(o) for o in _jlist(m.get("outcomes"))]
    if len(prices) != 2 or None in prices:
        return None
    yi = outs.index(pm.yes_label) if pm.yes_label in outs else 0
    p = prices[yi]
    return p if p in (0.0, 1.0) else None


# --- books ------------------------------------------------------------------------------------

def _levels(side: Sequence, best_first_desc: bool) -> List[Tuple[float, float]]:
    out = []
    for lv in side or []:
        if isinstance(lv, dict):
            p, s = _f(lv.get("price")), _f(lv.get("size"))
        elif isinstance(lv, (list, tuple)) and len(lv) >= 2:
            p, s = _f(lv[0]), _f(lv[1])
        else:
            continue
        if p is not None and s is not None and s > 0:
            out.append((p, s))
    out.sort(key=lambda x: -x[0] if best_first_desc else x[0])
    return out


def trim_book(b: Dict, levels: int = LEVELS) -> Dict:
    """A CLOB book with LEVELS a side, best first (the CLOB itself lists best last)."""
    bids = _levels(b.get("bids"), True)[:levels]
    asks = _levels(b.get("asks"), False)[:levels]
    out = {k: b.get(k) for k in ("asset_id", "market", "timestamp", "tick_size", "last_trade_price", "hash") if k in b}
    out["bids"] = [[p, s] for p, s in bids]
    out["asks"] = [[p, s] for p, s in asks]
    return out


def top_of_book(b: Optional[Dict]) -> Dict:
    """Best bid/ask, their sizes, the size within DEPTH of each touch, level counts."""
    bids = _levels((b or {}).get("bids"), True)
    asks = _levels((b or {}).get("asks"), False)
    out = {"bid": None, "bid_size": None, "ask": None, "ask_size": None, "bid_depth": None, "ask_depth": None,
           "n_bids": len(bids), "n_asks": len(asks)}
    if bids:
        out["bid"], out["bid_size"] = bids[0]
        out["bid_depth"] = sum(s for p, s in bids if p >= bids[0][0] - DEPTH - 1e-9)
    if asks:
        out["ask"], out["ask_size"] = asks[0]
        out["ask_depth"] = sum(s for p, s in asks if p <= asks[0][0] + DEPTH + 1e-9)
    return out


def yes_quote(yes_top: Dict, no_top: Optional[Dict] = None) -> Tuple[Optional[float], Optional[float]]:
    """The YES outcome's effective bid/ask: its own book, improved by the NO book's mirror
    (selling NO at q is buying YES at 1 - q), since the CLOB matches the two against each other."""
    bid, ask = yes_top.get("bid"), yes_top.get("ask")
    if no_top:
        if no_top.get("ask") is not None:
            mb = round(1.0 - no_top["ask"], 6)
            bid = mb if bid is None else max(bid, mb)
        if no_top.get("bid") is not None:
            ma = round(1.0 - no_top["bid"], 6)
            ask = ma if ask is None else min(ask, ma)
    return bid, ask


# --- pricing a Kalshi contract from Polymarket --------------------------------------------------

@dataclass(frozen=True)
class PmQuote:
    """One Polymarket market's YES quote at ``ts`` (history rows have bid == ask == price)."""
    market: PmMarket
    bid: Optional[float]
    ask: Optional[float]
    ts: int

    def mid(self) -> Optional[float]:
        b, a = self.bid, self.ask
        if b is None or a is None or a < b - 1e-9 or a - b > MAX_SPREAD + 1e-9:
            return None
        return (a + b) / 2.0

    def spread(self) -> Optional[float]:
        return None if self.bid is None or self.ask is None else self.ask - self.bid


def _ladder(quotes: Sequence[PmQuote]) -> Optional[Tuple[List[Tuple[float, float]], float, int, int]]:
    """(monotone survival curve, median spread, points, oldest ts) of the above/below quotes."""
    pts, spreads, ts = [], [], []
    for q in quotes:
        mid = q.mid()
        if mid is None:
            continue
        if q.market.kind == "above":
            pts.append((q.market.strike_lo, mid))
        elif q.market.kind == "below":
            pts.append((q.market.strike_hi, 1.0 - mid))
        else:
            continue
        spreads.append(q.spread() or 0.0)
        ts.append(q.ts)
    if len(pts) < 2:
        return None
    return binary_curve.monotone_survival(pts), sorted(spreads)[len(spreads) // 2], len(pts), min(ts)


def prob_for_contract(quotes: Iterable[PmQuote], lo: Optional[float], hi: Optional[float],
                      close_ts: int, open_ts: Optional[int] = None, ladder=None) -> Optional[Dict[str, float]]:
    """Polymarket's probability that a Kalshi-style contract settles YES ({pm_p_yes, pm_spread,
    pm_n, pm_ts}), or None when Polymarket lists nothing that settles at the same time.

    A floor contract whose window is (open_ts, close_ts) is the same event as an up/down window
    with the same start and end (KXBTC15M against Polymarket's 15-minute windows; its strike is
    the start price on both venues). Pass open_ts only for such contracts (UPDOWN_SERIES). Otherwise the above/below ladder settling at close_ts is a
    survival curve, read at the contract's strikes. ``ladder`` is a cached _ladder() of quotes."""
    same_end = [q for q in quotes if q.market.end_ts is not None and abs(q.market.end_ts - close_ts) <= END_TOL_S]
    if not same_end:
        return None
    if lo is not None and hi is None and open_ts is not None:
        for q in same_end:
            m = q.market
            if m.kind == "updown" and m.start_ts is not None and abs(m.start_ts - open_ts) <= END_TOL_S:
                mid = q.mid()
                if mid is None:
                    return None
                return {"pm_p_yes": mid, "pm_spread": q.spread() or 0.0, "pm_n": 1.0, "pm_ts": float(q.ts)}
    lad = ladder if ladder is not None else _ladder(same_end)
    if not lad:
        return None
    curve, spread, n, ts = lad
    p = binary_curve.prob_yes(curve, lo, hi)
    if p is None:
        return None
    return {"pm_p_yes": p, "pm_spread": spread, "pm_n": float(n), "pm_ts": float(ts)}


class PmSeries:
    """PmQuotes grouped by settlement time and poll: what Polymarket said about each settlement
    time at each moment, priced per contract with one cached ladder per (settlement, poll)."""

    def __init__(self, quotes: Iterable[PmQuote]) -> None:
        groups: Dict[int, Dict[int, List[PmQuote]]] = {}
        for q in quotes:
            if q.market.end_ts is None or q.market.kind not in PRICED_KINDS:
                continue
            groups.setdefault(int(q.market.end_ts), {}).setdefault(int(q.ts), []).append(q)
        self.by_end = {e: sorted(d.items()) for e, d in groups.items()}
        self._ladders: Dict[Tuple[int, int], object] = {}
        self._polls: Dict[int, Tuple[List[Tuple[int, int, List[PmQuote]]], List[int]]] = {}

    def __len__(self) -> int:
        return sum(len(v) for v in self.by_end.values())

    def _polls_for(self, close_ts: int) -> Tuple[List[Tuple[int, int, List[PmQuote]]], List[int]]:
        # research asks per contract per minute, so build each close time's poll list once
        hit = self._polls.get(close_ts)
        if hit is None:
            out = []
            for e, polls in self.by_end.items():
                if abs(e - close_ts) <= END_TOL_S:
                    out.extend((ts, e, qs) for ts, qs in polls)
            out.sort(key=lambda x: x[0])
            hit = self._polls[close_ts] = (out, [p[0] for p in out])
        return hit

    def polls(self, close_ts: int) -> List[Tuple[int, int, List[PmQuote]]]:
        """(poll ts, end_ts, quotes) of the settlement times within END_TOL_S of close_ts.
        Shared and cached: don't mutate."""
        return self._polls_for(close_ts)[0]

    def prob(self, lo: Optional[float], hi: Optional[float], close_ts: int, open_ts: Optional[int],
             poll: Tuple[int, int, List[PmQuote]]) -> Optional[Dict[str, float]]:
        ts, e, qs = poll
        key = (e, ts)
        if key not in self._ladders:
            self._ladders[key] = _ladder(qs) or False
        return prob_for_contract(qs, lo, hi, close_ts, open_ts, ladder=self._ladders[key])

    def at(self, lo: Optional[float], hi: Optional[float], close_ts: int, open_ts: Optional[int], ts: int,
           max_age_s: int) -> Optional[Dict[str, float]]:
        """The contract's pm_* features from the newest poll at or before ts (and no older than
        max_age_s), with pm_age_s."""
        polls, poll_ts = self._polls_for(close_ts)
        i = bisect.bisect_right(poll_ts, ts) - 1
        if i < 0 or ts - poll_ts[i] > max_age_s:
            return None
        best = polls[i]
        out = self.prob(lo, hi, close_ts, open_ts, best)
        if out is not None:
            out["pm_age_s"] = float(ts - out["pm_ts"])
        return out


def quotes_from_snapshot(rows: Iterable[Dict]) -> List[PmQuote]:
    """PmQuotes from heartbeat snapshot rows (MARKET_FIELDS + bid, ask, ts)."""
    out = []
    for r in rows or []:
        try:
            m = PmMarket(**{f: r.get(f) for f in MARKET_FIELDS})
        except TypeError:
            continue
        out.append(PmQuote(m, _f(r.get("bid")), _f(r.get("ask")), int(r.get("ts") or 0)))
    return out


# --- HTTP -------------------------------------------------------------------------------------

class HttpError(RuntimeError):
    def __init__(self, url: str, status: int, body: str) -> None:
        super().__init__(f"{url} -> HTTP {status}: {body[:200]}")
        self.url, self.status, self.body = url, status, body


def _request(method: str, url: str, session=None, params=None, body=None, timeout: int = 15):
    s = session or requests
    for attempt in range(5):
        resp = s.request(method, url, params=params, json=body, timeout=timeout, headers=UA)
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(min(2 ** attempt, 20))
            continue
        if resp.status_code >= 400:
            raise HttpError(url, resp.status_code, resp.text[:500])
        return resp.json()
    raise HttpError(url, 429, "gave up after retries")


def gamma_events(session=None, **params) -> List[Dict]:
    out = _request("GET", f"{GAMMA}/events", session, params=params)
    return out if isinstance(out, list) else (out or {}).get("data") or []


def fetch_books(tokens: Sequence[str], session=None) -> List[Dict]:
    """Books for ``tokens`` (POST /books in chunks; per-token GET /book if the batch call fails)."""
    out: List[Dict] = []
    for i in range(0, len(tokens), BOOKS_CHUNK):
        chunk = list(tokens[i:i + BOOKS_CHUNK])
        try:
            res = _request("POST", f"{CLOB}/books", session, body=[{"token_id": t} for t in chunk])
            out.extend(r for r in (res or []) if isinstance(r, dict))
        except HttpError as e:
            if e.status in (401, 403):
                raise
            for t in chunk:
                try:
                    out.append(_request("GET", f"{CLOB}/book", session, params={"token_id": t}))
                except HttpError as e2:
                    if e2.status != 404:     # a market that just closed has no book
                        raise
    return out


def fetch_price_history(token: str, start_ts: int, end_ts: int, session=None) -> List[Tuple[int, float]]:
    res = _request("GET", f"{CLOB}/prices-history", session,
                   params={"market": token, "startTs": int(start_ts), "endTs": int(end_ts), "fidelity": 1})
    out = []
    for h in (res or {}).get("history") or []:
        t, p = h.get("t"), _f(h.get("p"))
        if t is not None and p is not None:
            out.append((int(t), p))
    return out


# --- discovery ---------------------------------------------------------------------------------

def _hour_slugs(t_et: datetime) -> List[str]:
    """Hourly up/down event slugs. Polymarket put the year in them from 2026
    (bitcoin-up-or-down-october-25-2026-2am-et); the year-less slug is the 2025 event, kept for
    the history backfill of older days."""
    h = f"{t_et.hour % 12 or 12}{'am' if t_et.hour < 12 else 'pm'}"
    md = f"{MONTHS[t_et.month - 1]}-{t_et.day}"
    return [f"bitcoin-up-or-down-{md}-{t_et.year}-{h}-et", f"bitcoin-up-or-down-{md}-{h}-et"]


def window_slugs(start_s: int, end_s: int) -> List[str]:
    """Event slugs of the up/down windows starting in [start_s, end_s): 15-minute and hourly."""
    out = []
    t = start_s - start_s % 900
    while t < end_s:
        if t >= start_s:
            out.append(f"btc-updown-15m-{t}")
            if t % 3600 == 0:
                out += _hour_slugs(datetime.fromtimestamp(t, tz=ET))
        t += 900
    return out


def day_slugs(d: date) -> List[str]:
    """Daily ladder event slugs, with the year (2026 on) and without (2025)."""
    md = f"{MONTHS[d.month - 1]}-{d.day}"
    return [f"bitcoin-above-on-{md}-{d.year}", f"bitcoin-price-on-{md}-{d.year}",
            f"bitcoin-above-on-{md}", f"bitcoin-price-on-{md}"]


def discovery_slugs(now_ts: int) -> List[str]:
    out = window_slugs(now_ts - 900, now_ts + 3 * 3600)
    today = datetime.fromtimestamp(now_ts, tz=ET).date()
    for k in range(3):
        out += day_slugs(today + timedelta(days=k))
    return out


def discover(session=None, now_ts: Optional[int] = None, errors: Optional[List] = None) -> List[Tuple[Dict, Dict]]:
    """(market, event) pairs of every BTC market Gamma lists that ends within HORIZON_S: the
    open bitcoin-tagged events, plus the slugs the up/down and daily series follow (in case the
    tag listing misses some)."""
    now_ts = now_ts or int(time.time())
    events: Dict[str, Dict] = {}

    def add(evs):
        for e in evs or []:
            if isinstance(e, dict):
                events[str(e.get("id") or e.get("slug"))] = e

    for offset in (0, 200, 400):
        try:
            evs = gamma_events(session, tag_slug="bitcoin", closed="false", limit=200, offset=offset)
        except Exception as e:  # noqa: BLE001 - the slug lookups below still run
            if errors is not None:
                errors.append({"call": "events?tag_slug=bitcoin", "error": str(e)[:300]})
            break
        add(evs)
        if len(evs) < 200:
            break
    for slug in discovery_slugs(now_ts):
        try:
            add(gamma_events(session, slug=slug))
        except Exception as e:  # noqa: BLE001
            if errors is not None:
                errors.append({"call": f"events?slug={slug}", "error": str(e)[:300]})
    out = []
    for e in events.values():
        for m in e.get("markets") or []:
            pm = classify(m, e, now_ts)
            if pm is None or pm.end_ts is None or not (now_ts - 3600 <= pm.end_ts <= now_ts + HORIZON_S):
                continue
            if m.get("closed"):
                continue
            out.append((m, e))
    return out


def wants_book(pm: PmMarket, now_ts: int) -> bool:
    if pm.end_ts is None or pm.end_ts < now_ts - 120:
        return False
    if pm.kind == "updown":
        dur = (pm.end_ts - pm.start_ts) if pm.start_ts else None
        return dur is not None and dur >= MIN_UPDOWN_S and pm.end_ts - now_ts <= max(UPDOWN_BOOK_HORIZON_S, 2 * dur)
    if pm.kind in ("above", "below", "range"):
        return pm.end_ts - now_ts <= DAILY_BOOK_HORIZON_S
    return False


# --- archiver ---------------------------------------------------------------------------------

def parse_record(rt: int, data: Dict) -> Iterable[Tuple[str, tuple]]:
    """(table, row) pairs of one recorded line, for tick_archiver:
      polymarket_markets  rt + MARKET_FIELDS + best_bid, best_ask, last_trade, volume, liquidity,
                          active, closed (one row per BTC market per catalog pass)
      polymarket_top      rt, token_id, condition_id, bid, bid_size, ask, ask_size, bid_depth,
                          ask_depth, n_bids, n_asks, last_trade, exch_ms (per token per poll)"""
    if not isinstance(data, dict):
        return
    typ = data.get("type")
    if typ == "catalog":
        for m in data.get("markets") or []:
            pm = classify(m, None, rt // 1_000_000_000)
            if pm is None:
                continue
            yield "polymarket_markets", ((rt,) + tuple(getattr(pm, f) for f in MARKET_FIELDS) + (
                _f(m.get("bestBid")), _f(m.get("bestAsk")), _f(m.get("lastTradePrice")), _f(m.get("volume")),
                _f(m.get("liquidity")), bool(m.get("active")), bool(m.get("closed"))))
    elif typ == "books":
        for b in data.get("books") or []:
            t = top_of_book(b)
            ts = b.get("timestamp")
            try:
                exch_ms = int(float(ts)) if ts is not None else None
            except (TypeError, ValueError):
                exch_ms = None
            yield "polymarket_top", (rt, str(b.get("asset_id") or ""), str(b.get("market") or ""), t["bid"],
                                     t["bid_size"], t["ask"], t["ask_size"], t["bid_depth"], t["ask_depth"],
                                     t["n_bids"], t["n_asks"], _f(b.get("last_trade_price")), exch_ms)


def archive_schemas():
    import pyarrow as pa
    s, f, i64, b = pa.string(), pa.float64(), pa.int64(), pa.bool_()
    rt = ("rt", i64)
    return {
        "polymarket_markets": pa.schema([rt, ("market_id", s), ("slug", s), ("event_slug", s), ("question", s),
                                         ("condition_id", s), ("yes_token", s), ("no_token", s), ("yes_label", s),
                                         ("kind", s), ("strike_lo", f), ("strike_hi", f), ("start_ts", i64),
                                         ("end_ts", i64), ("tick", f), ("best_bid", f), ("best_ask", f),
                                         ("last_trade", f), ("volume", f), ("liquidity", f), ("active", b),
                                         ("closed", b)]),
        "polymarket_top": pa.schema([rt, ("token_id", s), ("condition_id", s), ("bid", f), ("bid_size", f),
                                     ("ask", f), ("ask_size", f), ("bid_depth", f), ("ask_depth", f),
                                     ("n_bids", i64), ("n_asks", i64), ("last_trade", f), ("exch_ms", i64)]),
    }


def quotes_from_archive(markets_rows: Iterable[Dict], top_rows: Iterable[Dict]) -> List[PmQuote]:
    """Every (market, poll) YES quote in an archived span: polymarket_top rows joined to the
    markets of polymarket_markets by token, the NO book folded into the YES quote."""
    by_token: Dict[str, Tuple[PmMarket, str]] = {}
    for r in markets_rows:
        try:
            m = PmMarket(**{f: r.get(f) for f in MARKET_FIELDS})
        except TypeError:
            continue
        if m.kind not in PRICED_KINDS:
            continue
        by_token[m.yes_token] = (m, "yes")
        by_token[m.no_token] = (m, "no")
    polls: Dict[Tuple[str, int], Dict[str, Dict]] = {}
    for r in top_rows:
        hit = by_token.get(r.get("token_id"))
        if hit is None:
            continue
        m, side = hit
        polls.setdefault((m.market_id, int(r["rt"])), {"m": m})[side] = r
    out = []
    for (_mid, rt), d in sorted(polls.items(), key=lambda kv: kv[0][1]):
        y = d.get("yes") or {}
        bid, ask = yes_quote(y, d.get("no"))
        out.append(PmQuote(d["m"], bid, ask, rt // 1_000_000_000))
    return out


# --- recorder ---------------------------------------------------------------------------------

class PolymarketRecorder:
    source = SOURCE

    def __init__(self) -> None:
        from data_pipeline.tick_recorder import TICK_DIR, HourlyFile
        self.file = HourlyFile(TICK_DIR, self.source)
        self.session = requests.Session()
        self.markets: Dict[str, Tuple[PmMarket, Dict]] = {}
        self.last_discover = 0.0
        self.polls = self.fails = self.discovers = 0
        self.last_ok = 0.0
        self.errors: List[str] = []
        self.snapshot: List[Dict] = []
        self.hist = {"days_written": 0, "last_pass": None, "error": None}
        self.lock = threading.Lock()

    def _write(self, rec: Dict) -> None:
        rt = time.time_ns()
        rec = dict(rec, rt=rt) if "rt" not in rec else rec
        with self.lock:
            self.file.write(rec["rt"], json.dumps(rec, separators=(",", ":"), default=str))
            self.file.flush()

    def _err(self, where: str, e: Exception) -> None:
        msg = f"{datetime.now(timezone.utc):%H:%M:%S} {where}: {type(e).__name__}: {e}"[:300]
        self.errors = (self.errors + [msg])[-20:]
        detail = {"where": where, "error": str(e)[:300]}
        if isinstance(e, HttpError):
            detail.update(status=e.status, url=e.url, body=e.body[:300])
        self._write({"meta": "http_error" if isinstance(e, HttpError) else "error", **detail})
        print(f"[WARN] polymarket {msg}", flush=True)

    def discover(self) -> None:
        now = int(time.time())
        errs: List[Dict] = []
        found = discover(self.session, now, errs)
        for e in errs[:5]:
            self._write({"meta": "discover_error", **e})
        if found or not self.markets:
            self.markets = {}
            for m, e in found:
                pm = classify(m, e, now)
                if pm is not None:
                    self.markets[pm.market_id or pm.condition_id] = (pm, m)
        self._write({"m": {"type": "catalog", "markets": [compact(m, e) for m, e in found]}})
        self.discovers += 1
        self.last_discover = time.time()

    def poll(self) -> None:
        now = int(time.time())
        live = [(pm, m) for pm, m in self.markets.values() if wants_book(pm, now)]
        tokens = []
        for pm, _m in live:
            tokens += [pm.yes_token, pm.no_token]
        if not tokens:
            return
        books = fetch_books(tokens, self.session)
        rt = time.time_ns()
        trimmed = [trim_book(b) for b in books]
        self._write({"rt": rt, "m": {"type": "books", "books": trimmed}})
        tops = {str(b.get("asset_id")): top_of_book(b) for b in trimmed}
        snap = []
        for pm, _m in live:
            y = tops.get(pm.yes_token)
            if y is None:
                continue
            bid, ask = yes_quote(y, tops.get(pm.no_token))
            snap.append(dict(pm.row(), bid=bid, ask=ask, bid_size=y["bid_size"], ask_size=y["ask_size"],
                             ts=rt // 1_000_000_000))
        self.snapshot = snap
        self.polls += 1
        self.last_ok = time.time()

    def heartbeat(self) -> None:
        from data_pipeline.tick_recorder import write_heartbeat
        write_heartbeat(HEARTBEAT_KEY, {
            "host": socket.gethostname(), "polls": self.polls, "fails": self.fails, "discovers": self.discovers,
            "markets": len(self.markets), "last_msg_age_s": round(time.time() - self.last_ok, 1) if self.last_ok else None,
            "errors": self.errors[-5:], "history": self.hist, "snapshot": self.snapshot})

    def history_loop(self) -> None:
        while True:
            try:
                self.hist["days_written"] += backfill(session=requests.Session())
                self.hist["error"] = None
            except Exception as e:  # noqa: BLE001 - retried next pass
                self.hist["error"] = f"{type(e).__name__}: {e}"[:300]
                print(f"[WARN] polymarket history: {self.hist['error']}", flush=True)
            self.hist["last_pass"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            time.sleep(HIST_PASS_S)

    def run(self) -> None:
        try:
            write_probe(session=self.session)
        except Exception as e:  # noqa: BLE001 - the probe is diagnostics only
            print(f"[WARN] polymarket probe: {e}", flush=True)
        threading.Thread(target=self.history_loop, daemon=True).start()
        print(f"polymarket recorder -> {self.file.root}/{self.source} books every {POLL_S:g}s", flush=True)
        last_hb = 0.0
        while True:
            t0 = time.time()
            try:
                if t0 - self.last_discover >= DISCOVER_S or (t0 % 900 < POLL_S and t0 - self.last_discover > 30):
                    self.discover()
                self.poll()
            except Exception as e:  # noqa: BLE001 - one bad poll must not stop the recorder
                self.fails += 1
                self._err("poll", e)
                if isinstance(e, HttpError) and e.status in (401, 403):
                    time.sleep(60)       # refused (geo or auth): back off, never retry harder
            if time.time() - last_hb >= HEARTBEAT_S:
                self.heartbeat()
                last_hb = time.time()
            time.sleep(max(0.5, POLL_S - (time.time() - t0)))


# --- history ----------------------------------------------------------------------------------

def day_key(day: datetime) -> str:
    return f"{PREFIX}/v1/{DAY_TABLE}/v={HIST_VERSION}/date={day:%Y-%m-%d}/part.parquet"


def _put_json(s3, key: str, obj: Dict) -> None:
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.json")
        with open(p, "w") as fh:
            json.dump(obj, fh, default=str)
        s3.upload_file(p, BUCKET, key)


def history_rows(day: datetime, session=None, pause_s: float = HIST_PAUSE_S, stats: Optional[Dict] = None) -> List[Dict]:
    """Minute prices of every 15-minute/hourly window and daily ladder that ended on UTC ``day``."""
    t0 = int(day.timestamp())
    slugs = window_slugs(t0 - 3600, t0 + 86400)
    d_et = datetime.fromtimestamp(t0, tz=ET).date()
    for d in (d_et, d_et + timedelta(days=1)):
        slugs += day_slugs(d)
    stats = stats if stats is not None else {}
    rows: List[Dict] = []
    for slug in slugs:
        try:
            evs = gamma_events(session, slug=slug)
        except HttpError as e:
            stats["gamma_errors"] = stats.get("gamma_errors", 0) + 1
            if e.status in (401, 403):
                raise
            continue
        time.sleep(pause_s)
        for e in evs or []:
            for m in e.get("markets") or []:
                pm = classify(m, e, t0)
                if pm is None or pm.kind not in PRICED_KINDS or pm.end_ts is None or not (t0 <= pm.end_ts < t0 + 86400):
                    continue
                if pm.kind == "updown" and (pm.start_ts is None or pm.end_ts - pm.start_ts < MIN_UPDOWN_S):
                    continue
                lo = (pm.start_ts or pm.end_ts - 86400) - 3600
                try:
                    hist = fetch_price_history(pm.yes_token, lo, pm.end_ts + 60, session)
                except HttpError as e2:
                    stats["history_errors"] = stats.get("history_errors", 0) + 1
                    if e2.status in (401, 403):
                        raise
                    continue
                time.sleep(pause_s)
                stats["markets"] = stats.get("markets", 0) + 1
                res = resolved_yes(m, pm)
                for t, p in hist:
                    rows.append({"t": t, "market_id": pm.market_id, "slug": pm.slug, "kind": pm.kind,
                                 "strike_lo": pm.strike_lo, "strike_hi": pm.strike_hi, "start_ts": pm.start_ts,
                                 "end_ts": pm.end_ts, "p": p, "resolved": res})
    return rows


def write_day(rows: List[Dict], path: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    s, f, i64 = pa.string(), pa.float64(), pa.int64()
    sch = pa.schema([("t", i64), ("market_id", s), ("slug", s), ("kind", s), ("strike_lo", f), ("strike_hi", f),
                     ("start_ts", i64), ("end_ts", i64), ("p", f), ("resolved", f)])
    pq.write_table(pa.table({c.name: [r.get(c.name) for r in rows] for c in sch}, schema=sch), path,
                   compression="zstd")


def quotes_from_history(rows: Iterable[Dict]) -> List[PmQuote]:
    out = []
    for r in rows:
        m = PmMarket(str(r["market_id"]), str(r.get("slug") or ""), "", "", "", "", "", "Yes", r["kind"],
                     r.get("strike_lo"), r.get("strike_hi"), r.get("start_ts"), r.get("end_ts"))
        t = int(r["t"])
        # minute series: stamped at the end of the minute it was known in, so every market's
        # price for one minute lands in one poll (a ladder) and none is used before it existed
        out.append(PmQuote(m, r["p"], r["p"], t + (-t) % 60))
    return out


def backfill(days: int = HIST_DAYS, max_days: int = 10_000, s3=None, now: Optional[datetime] = None,
             session=None) -> int:
    """Write the missing day files of the last ``days`` complete UTC days, newest first."""
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    now = now or datetime.now(timezone.utc)
    last = (now - timedelta(minutes=30)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    done = 0
    empty_run = 0
    for k in range(days):
        if done >= max_days or empty_run >= 5:     # Polymarket did not list these series yet
            break
        day = last - timedelta(days=k)
        key = day_key(day)
        try:
            s3.head_object(Bucket=BUCKET, Key=key)
            empty_run = 0
            continue
        except Exception:  # noqa: BLE001 - absent: build it
            pass
        t_start = time.time()
        stats: Dict = {}
        rows = history_rows(day, session, stats=stats)
        stats.update(rows=len(rows), version=HIST_VERSION, built_at=datetime.now(timezone.utc).isoformat())
        try:
            _put_json(s3, f"{PREFIX}/manifest/polymarket_history/date={day:%Y-%m-%d}.json", stats)
        except Exception:  # noqa: BLE001 - diagnostics only
            pass
        if not rows:
            empty_run += 1
            print(f"polymarket history {day:%Y-%m-%d}: nothing ({stats})", flush=True)
            continue
        empty_run = 0
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "part.parquet")
            write_day(rows, p)
            s3.upload_file(p, BUCKET, key)
        done += 1
        print(f"polymarket history {day:%Y-%m-%d}: {stats.get('markets', 0)} markets -> {len(rows)} rows "
              f"in {time.time() - t_start:.0f}s", flush=True)
    return done


# --- probe ------------------------------------------------------------------------------------

def probe(session=None, now_ts: Optional[int] = None) -> Dict:
    """Status and a sample of every endpoint the recorder uses (for checking reachability and
    response shapes from S3, without shell access to the box)."""
    now_ts = now_ts or int(time.time())
    out: Dict = {"ts": now_ts, "host": socket.gethostname(), "calls": []}

    def call(name, fn):
        try:
            res = fn()
            out["calls"].append({"call": name, "ok": True, "sample": json.dumps(res, default=str)[:1500]})
            return res
        except Exception as e:  # noqa: BLE001
            entry = {"call": name, "ok": False, "error": str(e)[:500]}
            if isinstance(e, HttpError):
                entry.update(status=e.status, body=e.body[:500])
            out["calls"].append(entry)
            return None

    tagged = call("gamma events tag_slug=bitcoin", lambda: gamma_events(session, tag_slug="bitcoin", closed="false",
                                                                        limit=200)) or []
    out["tagged_slugs"] = sorted({str(e.get("slug")) for e in tagged})[:200]
    found = []
    for slug in discovery_slugs(now_ts)[:4] + day_slugs(datetime.fromtimestamp(now_ts, tz=ET).date()):
        evs = call(f"gamma events slug={slug}", lambda s=slug: gamma_events(session, slug=s)) or []
        for e in evs:
            for m in e.get("markets") or []:
                pm = classify(m, e, now_ts)
                found.append({"slug": m.get("slug"), "question": m.get("question"), "keys": sorted(m)[:80],
                              "endDate": m.get("endDate"), "eventStartTime": m.get("eventStartTime"),
                              "parsed": pm.row() if pm else None})
    out["markets"] = found[:40]
    toks = [f["parsed"]["yes_token"] for f in found if f.get("parsed")][:2]
    if toks:
        call("clob POST /books", lambda: fetch_books(toks, session))
        call("clob GET /book", lambda: _request("GET", f"{CLOB}/book", session, params={"token_id": toks[0]}))
        call("clob prices-history", lambda: fetch_price_history(toks[0], now_ts - 3600, now_ts, session)[:20])
    return out


def write_probe(session=None, s3=None) -> str:
    rep = probe(session)
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    key = f"{PREFIX}/manifest/polymarket_probe/{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    _put_json(s3, key, rep)
    print(f"polymarket probe -> s3://{BUCKET}/{key}: " +
          ", ".join(f"{c['call']}={'ok' if c['ok'] else c.get('status', 'err')}" for c in rep["calls"]), flush=True)
    return key


def main(argv: List[str]) -> None:
    which = argv[1] if len(argv) > 1 else "record"
    if which == "backfill":
        n = backfill(int(argv[2]) if len(argv) > 2 else HIST_DAYS)
        print(f"polymarket history: wrote {n} day files", flush=True)
        return
    if which == "probe":
        print(json.dumps(probe(), indent=1, default=str)[:20000])
        return
    PolymarketRecorder().run()


if __name__ == "__main__":
    main(sys.argv)
