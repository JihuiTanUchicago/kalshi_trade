"""Explore routes: the market browser, the hot-markets sidebar and one market's page, read from the
datalake's explore feed (cached, refreshed in the background). Moved verbatim from app.server,
which re-imports every name for its route table."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app import repository as repo
from app.services import btc_spot
from app.trading.markets import MARKETS, NEW_YORK
from app.web.http import ApiError, Ctx
from app.web.routes.strategies import _mark_fields


# The collector writes a small gzipped feed of the hottest collected markets to S3; the
# web app reads + caches it, so browsing ~41k markets never touches the data lake per request.
_EXPLORE_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_EXPLORE_BUCKET = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-568386354218-us-east-1")
_EXPLORE_KEY = os.getenv("DATALAKE_EXPLORE_KEY", "explore/latest.json.gz")
_EXPLORE_SORTS = ("v24", "oi", "last")


_EXPLORE_LOCK = threading.Lock()
_S3: Dict[str, Any] = {}


def _fetch_explore_feed() -> Dict:
    try:
        import gzip as _gzip
        if "c" not in _S3:
            import boto3
            _S3["c"] = boto3.client("s3")
        raw = _S3["c"].get_object(Bucket=_EXPLORE_BUCKET, Key=_EXPLORE_KEY)["Body"].read()
        return json.loads(_gzip.decompress(raw))
    except Exception:  # feed not written yet, or S3 unreachable -> empty, not an error
        return None


def _refresh_explore_feed() -> None:
    try:
        data = _fetch_explore_feed()
        if data is not None or _EXPLORE_CACHE["data"] is None:
            _EXPLORE_CACHE.update(data=data or {"at": None, "total": 0, "shown": 0, "markets": []})
        _EXPLORE_CACHE["at"] = time.time()
    finally:
        _EXPLORE_CACHE["refreshing"] = False


def _explore_feed() -> Dict:
    """The Explore feed from S3, cached 45s. Once warm, a stale copy is served while ONE background
    thread refetches, so no request waits on S3 and concurrent misses don't each download the feed.
    A failed fetch keeps the last good copy rather than blanking the page."""
    now = time.time()
    if _EXPLORE_CACHE["data"] is None:
        with _EXPLORE_LOCK:
            if _EXPLORE_CACHE["data"] is None:
                _EXPLORE_CACHE["refreshing"] = True
                _refresh_explore_feed()
        return _EXPLORE_CACHE["data"]
    if now - _EXPLORE_CACHE["at"] >= 45 and not _EXPLORE_CACHE.get("refreshing"):
        with _EXPLORE_LOCK:
            if not _EXPLORE_CACHE.get("refreshing"):
                _EXPLORE_CACHE["refreshing"] = True
                threading.Thread(target=_refresh_explore_feed, daemon=True).start()
    return _EXPLORE_CACHE["data"]


def _efloat(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# A timed event's ticker says when it closes, in New York time: KXBTC15M-26OCT262345 closes 11:45pm ET
# on Oct 26, 2026 and KXBTCD-26OCT2717 at 5pm. Sports and daily events (26OCT26MINDEN, 26OCT27) carry
# no hour, so they get no close time rather than a guessed one.
_TIMED_EVENT = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})?(?:-|$)")
_MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}


def _ticker_close_at(ticker: Optional[str]) -> Optional[datetime]:
    """When a contract on a timed event closes, read from its ticker; None when it carries no hour."""
    m = _TIMED_EVENT.match(ticker or "")
    if not m or m.group(2) not in _MONTHS or NEW_YORK is None:
        return None
    try:
        return datetime(2000 + int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)), int(m.group(4)), int(m.group(5) or 0),
                        tzinfo=NEW_YORK)
    except ValueError:  # hour 24 or a day the month doesn't have: not a time
        return None


def _ticker_close(ticker: Optional[str]) -> Optional[str]:
    """The same close as UTC ISO, for the page."""
    at = _ticker_close_at(ticker)
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if at else None


# The app's own names for a series, searched with its contracts: Kalshi titles the 15-minute contracts
# "BTC price up in next 15 mins?", so a search for "bitcoin" missed them until "Bitcoin 15-minute" counted.
_SERIES_NAMES: Dict[str, str] = {}
for _m in MARKETS.values():
    _SERIES_NAMES[_m.series] = (_SERIES_NAMES.get(_m.series, "") + " " + _m.label).strip()


def explore_list(ctx: Ctx):
    data = _explore_feed()
    q = (ctx.query.get("q") or "").strip().lower()
    sort = ctx.query.get("sort") if ctx.query.get("sort") in _EXPLORE_SORTS else "v24"
    try:
        page = max(0, int(ctx.query.get("page") or 0))
    except ValueError:
        page = 0
    per = 40
    markets = data.get("markets") or []
    if q:
        markets = [m for m in markets
                   if q in " ".join((m.get("ti") or "", m.get("t") or "", m.get("s") or "", _SERIES_NAMES.get(m.get("s") or "", ""))).lower()]
    # "Price" orders by the price the list shows (the bid/ask midpoint, else the last trade), so the
    # column reads top to bottom; sorting on the last trade alone put quoted markets that never traded last.
    rank = (lambda m: _feed_mid(m) or 0.0) if sort == "last" else (lambda m: _efloat(m.get(sort)))
    markets = sorted(markets, key=rank, reverse=True)
    matched = len(markets)
    rows, spot = _strike_distances(ctx, [{**{k: v for k, v in m.items() if k != "h"}, "ct": _ticker_close(m.get("t"))}
                                         for m in markets[page * per:(page + 1) * per]], data.get("markets") or [])
    return {"at": data.get("at"), "total": data.get("total"), "shown": data.get("shown"),
            "matched": matched, "page": page, "per": per, "sort": sort, "markets": rows, **spot}


def explore_hot(ctx: Ctx):
    """Top markets that carry a price trace, for the Hot Markets sidebar, each with its close time and,
    for a Bitcoin contract, how far spot is from its strike, as Explore's rows."""
    data = _explore_feed()
    hot = [{**m, "ct": _ticker_close(m.get("t"))} for m in (data.get("markets") or []) if m.get("h")][:16]
    rows, spot = _strike_distances(ctx, hot, data.get("markets") or [])
    return {"at": data.get("at"), "markets": rows, **spot}


def _feed_mid(m: Dict) -> Optional[float]:
    """Mid (0..1 probability) for one explore-feed contract: the bid/ask midpoint, else last."""
    b, a = _efloat(m.get("bid")), _efloat(m.get("ask"))
    if b > 0 and a > 0:
        return round((b + a) / 2, 4)
    last = _efloat(m.get("last"))
    return round(last, 4) if last > 0 else None


def _cnum(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


_MINE_FIELDS = ("id", "mode", "side", "qty", "entry_price", "status", "title", "strategy_id", "market_close_time",
                "opened_at", "closed_at", "exit_price", "pnl", "close_reason")


def _market_mine(ctx: Ctx, ticker: str, open_ts: Optional[int]) -> Optional[Dict]:
    """The reader's own positions in one contract, for its market page: open ones marked to market,
    and those settled since the contract opened (30 days back when its open time is unknown). Each
    row keeps its mode; the page totals each money book apart. None when the read failed, so the
    page says so instead of showing an empty book."""
    since = datetime.fromtimestamp(open_ts, timezone.utc) if open_ts else datetime.now(timezone.utc) - timedelta(days=30)
    try:
        rows = repo.user_positions_in_ticker(ctx.cur, ctx.uid, ticker, since.replace(tzinfo=None))
    except Exception as e:
        print("[explore] market %s positions failed: %r" % (ticker, e), flush=True)
        return None
    pick = lambda p: {**{k: p.get(k) for k in _MINE_FIELDS},
                      "cost": _mark_fields(p)["cost"]}  # contracts x entry price plus the fee, as every page rounds it
    return {"open": [{**pick(p), **_mark_fields(p)} for p in rows["open"]], "closed": [pick(p) for p in rows["closed"]]}


def _market_terms(m: Dict) -> Dict:
    """How a contract settles, from Kalshi's market record: its rules, when the result is expected,
    and the result once it has one."""
    return {"rules": m.get("rules_primary") or "", "rules_more": m.get("rules_secondary") or "",
            "settles_at": m.get("expected_expiration_time") or m.get("expiration_time"), "result": m.get("result") or ""}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def explore_market(ctx: Ctx):
    """One market's dataset for the Explore detail view: its metadata, how it settles, the price
    history Kalshi has for it (the same candlesticks the backtester trains on), and the reader's
    own positions in it. Fetched on demand from Kalshi's public API — no lake query, no new storage.
    `as_of` is when the figures were read: now for Kalshi's record, the feed's time for its snapshot."""
    from data_pipeline.common import api_get, parse_iso_to_dt
    import time as _time
    ticker = (ctx.query.get("ticker") or "").strip()
    if not ticker:
        raise ApiError(400, "No market given.")
    series = ticker.split("-", 1)[0]
    m: Dict = {}
    open_ts = None
    try:
        m = (api_get("/markets/%s" % ticker) or {}).get("market") or {}
        open_ts = int(parse_iso_to_dt(m.get("open_time")).timestamp()) if m.get("open_time") else None
        close_ts = int(parse_iso_to_dt(m.get("close_time")).timestamp()) if m.get("close_time") else None
        now = int(_time.time())
        start = open_ts or (now - 30 * 86400)
        end = min(close_ts or now, now)
        span = max(1, end - start)
        # Prefer minute resolution; fall back to coarser only when the span would blow past
        # Kalshi's per-request candle cap (minute for <=2 days, hourly to ~2 months, else daily).
        period = 1 if span <= 2 * 86400 else (60 if span <= 60 * 86400 else 1440)  # minutes
        cs = api_get("/series/%s/markets/%s/candlesticks" % (series, ticker),
                     {"start_ts": start, "end_ts": end, "period_interval": period}).get("candlesticks") or []
    except Exception as e:
        # The raw error named the proxy and Kalshi's host to the user; keep that in the log.
        if " failed 404:" in str(e):  # api_get's RuntimeError carries the status in its text
            raise ApiError(404, "Kalshi has no market %s." % ticker)
        print("[explore] market %s history failed: %r" % (ticker, e), flush=True)
        # Still show the market: Kalshi's own record if that call got through, else the Explore
        # feed's snapshot of it. Only the chart waits for Kalshi (history_unavailable).
        snap = m and {"title": m.get("title"), "sub": m.get("yes_sub_title") or m.get("subtitle"), "yes_bid": m.get("yes_bid_dollars"),
                      "yes_ask": m.get("yes_ask_dollars"), "last": m.get("last_price_dollars"), "volume_24h": m.get("volume_24h_fp"),
                      "open_interest": m.get("open_interest_fp"), "status": m.get("status"), "close_time": m.get("close_time"),
                      **_market_terms(m), "as_of": _iso_now()}
        if not snap:
            feed = _explore_feed()
            f = next((x for x in (feed.get("markets") or []) if x.get("t") == ticker), None)
            # The feed carries no close time, but a timed event's ticker says it (as Explore's rows and the spot
            # section read it): the page said "Closes —" above "Time left 5 hr · closes 21:00 UTC".
            snap = f and {"title": f.get("ti"), "sub": f.get("su"), "yes_bid": f.get("bid"), "yes_ask": f.get("ask"),
                          "last": f.get("last"), "volume_24h": f.get("v24"), "open_interest": f.get("oi"),
                          "status": f.get("st"), "close_time": _ticker_close(ticker), "as_of": feed.get("at"), "snapshot": True}
        if not snap:
            raise ApiError(502, "Kalshi didn't send this market's history just now. Try again in a minute.")
        return {**snap, "ticker": ticker, "series": series, "title": snap["title"] or "", "sub": snap["sub"] or "",
                "period_min": None, "points": [], "history_unavailable": True, "mine": _market_mine(ctx, ticker, open_ts)}
    points = []
    for c in cs:
        price = (c.get("price") or {})
        yb, ya = (c.get("yes_bid") or {}), (c.get("yes_ask") or {})
        yes = _cnum(price.get("close_dollars"))
        if yes is None:
            b, a = _cnum(yb.get("close_dollars")), _cnum(ya.get("close_dollars"))
            yes = (b + a) / 2 if b is not None and a is not None else None
        if yes is not None:
            points.append({"t": int(c["end_period_ts"]), "yes": round(yes, 4), "vol": _cnum(c.get("volume_fp")) or 0})
    return {
        "ticker": ticker, "series": series,
        "title": m.get("title") or "", "sub": m.get("yes_sub_title") or m.get("subtitle") or "",
        "yes_bid": m.get("yes_bid_dollars"), "yes_ask": m.get("yes_ask_dollars"), "last": m.get("last_price_dollars"),
        "volume_24h": m.get("volume_24h_fp"), "open_interest": m.get("open_interest_fp"),
        "status": m.get("status"), "close_time": m.get("close_time"), "period_min": period, "points": points,
        **_market_terms(m), "as_of": _iso_now(), "mine": _market_mine(ctx, ticker, open_ts),
    }


# A Bitcoin contract's page shows where Bitcoin is against its strike, from what the collectors stored:
# never an exchange or Kalshi call in the request. Its own read, so the page draws without waiting on it.
# Every reader shares one spot read for SPOT_TTL_S; a contract's strike and close don't move, so each is
# kept STRIKE_TTL_S. Both caches are only mutated in place.
SPOT_TTL_S = 5.0
STRIKE_TTL_S = 300.0
_STRIKE_KEEP = 2000  # contracts' strikes held at once; a full cache starts over
SPOT_LOOKBACK = timedelta(days=1)  # older than this is no stored price at all
_SPOT_CACHE: Dict[str, Any] = {"at": 0.0, "row": None}
_STRIKE_CACHE: Dict[str, Any] = {}


def _spot_row(ctx: Ctx) -> Optional[Dict]:
    now = time.time()
    if now - _SPOT_CACHE["at"] >= SPOT_TTL_S:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - SPOT_LOOKBACK
        _SPOT_CACHE.update(row=repo.latest_spot(ctx.cur, btc_spot.SPOT_PRODUCT, since), at=now)
    return _SPOT_CACHE["row"]


def _strike_record(ctx: Ctx, ticker: str) -> Optional[Dict]:
    """The collector's record of the contract, or None (not collected, or the read failed: the ticker
    still gives the strike of most contracts)."""
    now = time.time()
    hit = _STRIKE_CACHE.get(ticker)
    if hit and now - hit[0] < STRIKE_TTL_S:
        return hit[1]
    try:
        rec = repo.market_strike(ctx.cur, ticker)
    except Exception as e:
        print("[explore] strike %s read failed: %r" % (ticker, e), flush=True)
        return None
    if len(_STRIKE_CACHE) >= _STRIKE_KEEP:
        _STRIKE_CACHE.clear()
    _STRIKE_CACHE[ticker] = (now, rec)
    return rec


def _spot_view(row: Optional[Dict], now: datetime) -> Optional[Dict]:
    """The stored spot as the page shows it: its price, when it was taken, its age and whether that is stale."""
    if not row:
        return None
    at = row["at"].replace(tzinfo=timezone.utc)
    age = max(0, int((now - at).total_seconds()))
    return {"price": row["price"], "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "age_s": age, "stale": age > btc_spot.STALE_AFTER_S}


def _strike_distances(ctx: Ctx, rows: List[Dict], feed: List[Dict]) -> Tuple[List[Dict], Dict]:
    """Explore's rows with how far stored spot is from each Bitcoin contract's strike (`vs`: side, diff in
    $, pct), and the spot itself under "spot". Strikes come from the tickers alone, a bucket's edges from
    its ladder's other tickers in the feed, and spot from the one shared read (_spot_row), so a page of
    rows costs at most one DB read. A stale, missing or failed spot gives no `vs` and says why in "spot";
    a page with no Bitcoin strike on it reads nothing and gets no "spot" at all."""
    strikes = {}
    for m in rows:
        k = btc_spot.contract_strike(m["t"]) if btc_spot.is_btc_contract(m.get("t")) else None
        if k:
            strikes[m["t"]] = k
    if not strikes:
        return rows, {}
    try:
        spot = _spot_view(_spot_row(ctx), datetime.now(timezone.utc))
    except Exception as e:
        print("[explore] list spot read failed: %r" % (e,), flush=True)
        return rows, {"spot": {"failed": True}}
    if not spot or spot["stale"]:
        return rows, {"spot": spot}
    ladders = {t.rpartition("-")[0] for t, k in strikes.items() if k["kind"] == "range"}
    centres: Dict[str, List[float]] = {}
    if ladders:
        for m in feed:
            ev = (m.get("t") or "").rpartition("-")[0]
            k = btc_spot.contract_strike(m["t"]) if ev in ladders else None
            if k and k["kind"] == "range":
                centres.setdefault(ev, []).append(k["value"])
    out = []
    for m in rows:
        k = strikes.get(m["t"])
        k = k and btc_spot.with_bucket_edges(k, btc_spot.bucket_width(centres.get(m["t"].rpartition("-")[0], ())))
        if k and (k["kind"] != "range" or k["lo"] is not None):  # a lone bucket's edges aren't known
            v = btc_spot.against_strike(spot["price"], k)
            m = {**m, "vs": {"side": v["side"], "diff": v["diff"], "pct": v["pct"]}}
        out.append(m)
    return out, {"spot": spot}


def explore_spot(ctx: Ctx):
    """Bitcoin against one Bitcoin contract's strike: the newest stored spot and its age (stale past
    btc_spot.STALE_AFTER_S, still shown), the strike, which side of it spot is on and by how much, and
    the time left to the close. Ages and time left are worked out per request from the cached reads."""
    ticker = (ctx.query.get("ticker") or "").strip()
    if not btc_spot.is_btc_contract(ticker):
        raise ApiError(400, "Not a Bitcoin contract.")
    try:
        row = _spot_row(ctx)
    except Exception as e:
        print("[explore] spot read failed: %r" % (e,), flush=True)
        raise ApiError(503, "Bitcoin’s latest price didn’t load. Try again in a moment.")
    rec = _strike_record(ctx, ticker)
    strike = btc_spot.contract_strike(ticker, rec)
    now = datetime.now(timezone.utc)
    close_at = rec["close_time"].replace(tzinfo=timezone.utc) if rec and rec.get("close_time") else _ticker_close_at(ticker)
    spot = _spot_view(row, now)
    return {"ticker": ticker, "spot": spot, "strike": strike,
            "vs": btc_spot.against_strike(spot["price"], strike) if spot and strike else None,
            "close_time": close_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if close_at else None,
            "secs_left": max(0, int((close_at - now).total_seconds())) if close_at else None,
            "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
