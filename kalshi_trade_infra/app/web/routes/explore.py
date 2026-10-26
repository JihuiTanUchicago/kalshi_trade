"""Explore routes: the market browser, the hot-markets sidebar and one market's page, read from the
datalake's explore feed (cached, refreshed in the background). Moved verbatim from app.server,
which re-imports every name for its route table."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app import repository as repo
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
                   if q in ((m.get("ti") or "") + " " + (m.get("t") or "") + " " + (m.get("s") or "")).lower()]
    markets = sorted(markets, key=lambda m: _efloat(m.get(sort)), reverse=True)
    matched = len(markets)
    return {"at": data.get("at"), "total": data.get("total"), "shown": data.get("shown"),
            "matched": matched, "page": page, "per": per, "sort": sort,
            "markets": [{k: v for k, v in m.items() if k != "h"} for m in markets[page * per:(page + 1) * per]]}


def explore_hot(ctx: Ctx):
    """Top markets that carry a price trace, for the Hot Markets sidebar."""
    data = _explore_feed()
    hot = [m for m in (data.get("markets") or []) if m.get("h")][:16]
    return {"at": data.get("at"), "markets": hot}


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
                      "cost": round(int(p["qty"]) * float(p["entry_price"]) + float(p.get("entry_fee") or 0), 2)}
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
            snap = f and {"title": f.get("ti"), "sub": f.get("su"), "yes_bid": f.get("bid"), "yes_ask": f.get("ask"),
                          "last": f.get("last"), "volume_24h": f.get("v24"), "open_interest": f.get("oi"),
                          "status": f.get("st"), "close_time": None, "as_of": feed.get("at"), "snapshot": True}
        if not snap:
            raise ApiError(502, "Kalshi didn't send this market's history just now. Try again in a minute.")
        return {**snap, "ticker": ticker, "series": series, "title": snap["title"] or ticker, "sub": snap["sub"] or "",
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
        "title": m.get("title") or ticker, "sub": m.get("yes_sub_title") or m.get("subtitle") or "",
        "yes_bid": m.get("yes_bid_dollars"), "yes_ask": m.get("yes_ask_dollars"), "last": m.get("last_price_dollars"),
        "volume_24h": m.get("volume_24h_fp"), "open_interest": m.get("open_interest_fp"),
        "status": m.get("status"), "close_time": m.get("close_time"), "period_min": period, "points": points,
        **_market_terms(m), "as_of": _iso_now(), "mine": _market_mine(ctx, ticker, open_ts),
    }
