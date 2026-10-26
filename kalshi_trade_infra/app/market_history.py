"""Backtest history for both markets, from the official sources.

    Kalshi settled markets  -> hist_markets   (strike, close time, result)
    Kalshi candlesticks     -> market_candles (top-of-book bid/ask per period)
    Coinbase 1m candles     -> btc_candles_1m (BTC price path)

Resumable and idempotent: every write is an upsert and every market carries a
`candles_done` flag, so a crash or restart just carries on. Run forever with
`python -m app.market_history` (refreshes every 10 minutes) or once with
`--once`.

Labels come from Kalshi's own `result`, not from re-deriving settlement from
Coinbase: Kalshi settles on the CF Benchmarks BRTI average, which differs from
any single exchange's last trade.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

from app.trading.markets import CURATED, MARKETS, Market
from data_pipeline.common import api_get, get_db_conn, parse_iso_to_dt, utc_now

COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/%s/candles"  # %s = product, e.g. BTC-USD
COINBASE_MAX_CANDLES = 300
# Daily-ladder strikes this far from BTC at the event's open are never
# tradable (they sit at 0c/100c all day), so their candles are not fetched.
# The band is centred on the price at OPEN, which is known at decision time -
# centring it on the settlement value would leak the future into which
# contracts the backtest can see.
LADDER_BAND = 0.07
REFRESH_SECONDS = 600
KALSHI_PAUSE_SECONDS = 0.07  # ~14 req/s, under the basic tier's 20/s
# Backfill: when a market's history_days reaches further back than what was collected (it was
# raised, or collection started late), fill the gap at the OLD end too, a bounded slice per pass
# so a 10-minute cycle stays short. The forward sync above only ever moves forward.
BACKFILL_GAP_SECONDS = 86400          # ignore gaps under a day (normal edge of the window)
SPOT_BACKFILL_SECONDS_PER_PASS = 7 * 86400
OLD_MARKET_SECONDS = 30 * 86400       # candles of a market closed longer ago may be unavailable
# Wall-clock budget for one pass (settled markets + candles). The watchdog restarts us when no cycle completes
# within 1500s, and a long backfill (a raised history_days, ~100 catalog series) used to blow past
# that every pass, so no cycle ever finished. Past the budget the pass ends and the rest of the
# backlog resumes next pass, rotating so every series gets its turn.
PASS_BUDGET_SECONDS = int(os.getenv("HISTORY_PASS_BUDGET_SECONDS", "900"))
BACKLOG_SLEEP_SECONDS = 60
# Most of one market's backlog per pass. Without it the first few series with a deep backlog (an
# hourly series at 1-minute candles, a 365-day weather backfill) ate the whole budget and the
# rotation advanced ~8 of ~1,000 series a pass, so a new series waited a day for its first candle.
MARKET_SLICE_SECONDS = int(os.getenv("HISTORY_MARKET_SLICE_SECONDS", "20"))
# Kalshi moves markets settled before a rolling cutoff to /historical/*; the live endpoints stop
# serving them. Refetched hourly.
CUTOFF_TTL_SECONDS = 3600
_cutoff_cache: Dict[str, object] = {}
# Series filled first, with no per-market slice: the research thread is waiting on a year of weather.
# Exact tickers come first (in this order), then anything matching a prefix. Env-tunable; empty = off.
PRIORITY_SERIES = [t for t in os.getenv(
    "HISTORY_PRIORITY_SERIES", "KXHIGHCHI,KXHIGHAUS,KXHIGHMIA,KXHIGHDEN,KXHIGHLAX,KXHIGHPHIL").split(",") if t]
PRIORITY_PREFIXES = tuple(t for t in os.getenv("HISTORY_PRIORITY_PREFIXES", "KXHIGH,KXLOW").split(",") if t)
# Catalog series re-list their settled markets at most this often (curated: every pass). Two API calls
# for each of ~1,000 series every pass was a third of the budget for lists that change daily.
SETTLED_MIN_INTERVAL_SECONDS = int(os.getenv("HISTORY_SETTLED_MIN_INTERVAL_SECONDS", "3600"))
_last_settled: Dict[str, float] = {}
# Catalog series that get history at all (curated, research-requested and PRIORITY_* always do).
# Head-to-head lines are what the sports research uses; the long tail of props/futures (fantasy weekly
# leaders, chess, surfing, "next team") was ~15 GiB/day of settled-market candles on 10-26.
HISTORY_SERIES_PATTERN = re.compile(os.getenv("HISTORY_SERIES_PATTERN", r"GAME|MATCH|SPREAD|TOTAL"), re.I)
# Where the catalog rotation resumes. Starts at a random point so the hourly web deploys, which
# restart this process, don't send every pass back to the same first ~100 series.
_candle_rotation: Optional[int] = None


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def sync_spot_candles(cur, symbol: str, start_ts: int, end_ts: int) -> int:
    """Coinbase one-minute candles for `symbol` (e.g. BTC-USD) in [start_ts, end_ts).
    Returns rows written into spot_candles_1m."""
    written = 0
    t = start_ts - (start_ts % 60)
    while t < end_ts:
        chunk_end = min(t + COINBASE_MAX_CANDLES * 60, end_ts)
        params = {
            "granularity": 60,
            "start": datetime.fromtimestamp(t, tz=timezone.utc).isoformat(),
            "end": datetime.fromtimestamp(chunk_end, tz=timezone.utc).isoformat(),
        }
        resp = None
        for attempt in range(6):
            resp = requests.get(COINBASE_CANDLES_URL % symbol, params=params, timeout=20)
            if resp.status_code != 429:
                break
            time.sleep(1.0 + attempt)
        if resp is None or resp.status_code >= 400:
            raise RuntimeError("Coinbase candles failed %s: %s" % (getattr(resp, "status_code", "?"), resp.text[:200] if resp else ""))
        # [time, low, high, open, close, volume]
        rows = [
            (symbol, int(r[0]), r[3], r[2], r[1], r[4], r[5])
            for r in resp.json()
            if t <= int(r[0]) < chunk_end
        ]
        if rows:
            cur.executemany(
                """
                INSERT INTO spot_candles_1m (symbol, start_ts, open, high, low, close, volume)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE open=VALUES(open), high=VALUES(high), low=VALUES(low),
                  close=VALUES(close), volume=VALUES(volume)
                """,
                rows,
            )
            written += len(rows)
        t = chunk_end
        time.sleep(0.15)
    return written


def historical_cutoff() -> Optional[datetime]:
    """Kalshi's market_settled_ts cutoff (tz-aware), or None if it can't be fetched (then only the
    live endpoints are used, as before)."""
    now = time.time()
    if _cutoff_cache and now - float(_cutoff_cache["at"]) < CUTOFF_TTL_SECONDS:
        return _cutoff_cache["ts"]  # type: ignore[return-value]
    try:
        ts = parse_iso_to_dt((api_get("/historical/cutoff") or {}).get("market_settled_ts"))
    except Exception as e:
        print("[market_history] historical cutoff unavailable: %r" % (e,), flush=True)
        return _cutoff_cache.get("ts")  # type: ignore[return-value]
    _cutoff_cache.update(at=now, ts=ts)
    return ts


def _market_pages(path: str, params: Dict):
    cursor = None
    while True:
        data = api_get(path, dict(params, cursor=cursor) if cursor else params)
        yield data.get("markets") or []
        cursor = data.get("cursor")
        if not cursor:
            return
        time.sleep(KALSHI_PAUSE_SECONDS)


def sync_settled_markets(cur, market: Market, min_close: datetime, max_close: Optional[datetime] = None) -> int:
    base = {"series_ticker": market.series, "min_close_ts": int(min_close.timestamp()), "limit": 1000}
    sources = []
    cutoff = historical_cutoff()
    if cutoff is not None and min_close < cutoff:
        hist_max = cutoff if max_close is None else min(max_close, cutoff)
        sources.append(("/historical/markets", dict(base, max_close_ts=int(hist_max.timestamp()))))
    live = dict(base, status="settled")
    if max_close is not None:
        live["max_close_ts"] = int(max_close.timestamp())
    sources.append(("/markets", live))
    lo, hi = min_close, max_close
    written = 0
    for path, params in sources:
        for page in _market_pages(path, params):
            # /historical/markets ignores min/max_close_ts and returns the whole series (back to
            # 2021 for some), newest first, so trim to the window and stop once past its old end.
            closes = [parse_iso_to_dt(m.get("close_time")) for m in page]
            page = [m for m, c in zip(page, closes) if c is not None and c >= lo and (hi is None or c <= hi)]
            written += _upsert_settled(cur, market, page)
            if any(c is not None and c < lo for c in closes):
                break
    return written


def _upsert_settled(cur, market: Market, markets) -> int:
    rows = []
    for m in markets:
        close_time = parse_iso_to_dt(m.get("close_time"))
        open_time = parse_iso_to_dt(m.get("open_time"))
        strike = m.get("floor_strike")
        result = (m.get("result") or "").lower()
        if close_time is None or open_time is None or result not in ("yes", "no"):
            continue
        # Underlying markets price against a strike; sports (underlying=None) settle on an
        # outcome and carry no floor_strike, so store a 0.0 sentinel (never used - snapshot
        # computes no moneyness without a spot).
        if strike is None:
            if market.underlying is not None:
                continue
            strike = 0.0
        if not market.is_target_event(close_time):
            continue
        rows.append(
            (
                m["ticker"],
                market.series,
                m.get("event_ticker") or "",
                float(strike),
                _naive_utc(open_time),
                _naive_utc(close_time),
                result,
                m.get("expiration_value"),
            )
        )
    if rows:
        cur.executemany(
            """
            INSERT INTO hist_markets
              (ticker, series_ticker, event_ticker, strike, open_time, close_time, result, expiration_value)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE result=VALUES(result), expiration_value=VALUES(expiration_value)
            """,
            rows,
        )
    return len(rows)


def _spot_close_at(cur, symbol: str, ts: int) -> Optional[float]:
    cur.execute(
        "SELECT close FROM spot_candles_1m WHERE symbol=%s AND start_ts <= %s AND start_ts > %s "
        "ORDER BY start_ts DESC LIMIT 1",
        (symbol, ts, ts - 600),
    )
    row = cur.fetchone()
    return float(row["close"]) if row else None


def _num(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _px(d: Dict, field: str):
    """A candle price field: the live API names it "<field>_dollars", /historical just "<field>"."""
    v = d.get(field + "_dollars")
    return v if v is not None else d.get(field)


def slim_candle_raw(c: Dict) -> Dict:
    """The part of a Kalshi candle the row's columns do not already hold: the period's highs and lows.

    The full candle repeated every column (open/close, volume, OI, end ts) as strings, ~325 bytes of
    a ~615-byte row on a 185M-row table. Nothing reads raw_json back; this keeps the only extra info.
    """
    out = {}
    for key, side in (("b", "yes_bid"), ("a", "yes_ask"), ("p", "price")):
        d = c.get(side) or {}
        for k, field in (("l", "low"), ("h", "high")):
            if _px(d, field) is not None:
                out[key + k] = _px(d, field)
    return out


def sync_market_candles(cur, market: Market, limit: int = 2000, deadline: Optional[float] = None) -> int:
    """Fetch candles for settled markets that do not have them yet, stopping at `deadline`."""
    cur.execute(
        """
        SELECT ticker, strike, open_time, close_time FROM hist_markets
        WHERE series_ticker=%s AND candles_done=0 AND close_time >= %s ORDER BY close_time DESC LIMIT %s
        """,
        # Only inside history_days: older rows (e.g. from a since-trimmed /historical page) wait
        # untouched until the window is raised to reach them.
        (market.series, _naive_utc(utc_now() - timedelta(days=market.history_days)), limit),
    )
    pending = cur.fetchall()
    cutoff = historical_cutoff()
    cutoff_ts = cutoff.timestamp() if cutoff is not None else None
    done = 0
    for m in pending:
        if deadline is not None and time.time() >= deadline:
            break
        open_ts = int(m["open_time"].replace(tzinfo=timezone.utc).timestamp())
        close_ts = int(m["close_time"].replace(tzinfo=timezone.utc).timestamp())
        if market.close_hour_et is not None:
            spot = _spot_close_at(cur, market.underlying, open_ts)
            if spot is None:
                continue  # underlying spot history not there yet; try again next pass
            if abs(float(m["strike"]) / spot - 1.0) > LADDER_BAND:
                cur.execute("UPDATE hist_markets SET candles_done=2 WHERE ticker=%s", (m["ticker"],))
                continue
        # Kalshi caps candlesticks at 5000 per request; chunk the window by time, since a market
        # listed for days at 1-minute candles (e.g. NBA games) blows past the cap in one call.
        max_candles = 4900
        if cutoff_ts is not None and close_ts < cutoff_ts:
            path = "/historical/markets/%s/candlesticks" % m["ticker"]
        else:
            path = "/series/%s/markets/%s/candlesticks" % (market.series, m["ticker"])
        span = market.candle_minutes * 60
        candles = []
        data: Optional[Dict] = {}
        t = open_ts
        while t < close_ts:
            chunk_end = min(t + max_candles * span, close_ts)
            try:
                data = api_get(
                    path,
                    {"start_ts": t, "end_ts": chunk_end, "period_interval": market.candle_minutes},
                )
            except RuntimeError as e:
                # Only an OLD (backfilled) market may be written off on a 400/404: Kalshi may no
                # longer serve it. A recent one keeps raising, so a real bug is retried, not hidden.
                if not _is_client_error(e) or time.time() - close_ts < OLD_MARKET_SECONDS:
                    raise
                data = None  # skip it so it can't block the rest of the series
                break
            candles.extend(data.get("candlesticks") or [])
            t = chunk_end
        if data is None:
            cur.execute("UPDATE hist_markets SET candles_done=3 WHERE ticker=%s", (m["ticker"],))
            continue
        now = _naive_utc(utc_now())
        rows = []
        for c in candles:
            bid = c.get("yes_bid") or {}
            ask = c.get("yes_ask") or {}
            price = c.get("price") or {}
            rows.append(
                (
                    m["ticker"],
                    int(c["end_period_ts"]),
                    market.candle_minutes,
                    _num(_px(bid, "open")),
                    _num(_px(bid, "close")),
                    _num(_px(ask, "open")),
                    _num(_px(ask, "close")),
                    _num(_px(price, "open")),
                    _num(_px(price, "close")),
                    _num(c.get("volume_fp", c.get("volume"))),
                    _num(c.get("open_interest_fp", c.get("open_interest"))),
                    now,
                    json.dumps(slim_candle_raw(c), separators=(",", ":")),
                )
            )
        if rows:
            cur.executemany(
                """
                INSERT INTO market_candles
                  (ticker, end_period_ts, period_interval_minutes, yes_bid_open, yes_bid_close,
                   yes_ask_open, yes_ask_close, price_open, price_close, volume_fp, open_interest_fp,
                   collected_at_utc, raw_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE yes_bid_close=VALUES(yes_bid_close), yes_ask_close=VALUES(yes_ask_close)
                """,
                rows,
            )
        cur.execute("UPDATE hist_markets SET candles_done=1 WHERE ticker=%s", (m["ticker"],))
        done += 1
        time.sleep(KALSHI_PAUSE_SECONDS)
    return done


def _is_client_error(e: Exception) -> bool:
    """api_get raises RuntimeError("GET <url> failed <status>: ...") on HTTP errors. A 400/404
    is permanent for that resource (e.g. a market past Kalshi's retention); 5xx and 429 are not."""
    msg = str(e)
    return " failed 400" in msg or " failed 404" in msg


def backfill_spot(cur, symbol: str, history_days: int, now: datetime) -> int:
    """Fill spot candles between the history floor and the OLDEST collected candle, at most
    SPOT_BACKFILL_SECONDS_PER_PASS per call (newest part of the gap first)."""
    floor_ts = int((now - timedelta(days=history_days + 1)).timestamp())
    cur.execute("SELECT MIN(start_ts) AS t FROM spot_candles_1m WHERE symbol=%s", (symbol,))
    first = (cur.fetchone() or {}).get("t")
    if first is None or int(first) - floor_ts < BACKFILL_GAP_SECONDS:
        return 0
    start = max(floor_ts, int(first) - SPOT_BACKFILL_SECONDS_PER_PASS)
    return sync_spot_candles(cur, symbol, start, int(first))


def backfill_settled_markets(cur, market: Market, now: datetime) -> int:
    """Settled markets between the history floor and the OLDEST collected close. Their candles
    are then fetched by sync_market_candles like any candles_done=0 row (newest first)."""
    floor = now - timedelta(days=market.history_days)
    cur.execute("SELECT MIN(close_time) AS t FROM hist_markets WHERE series_ticker=%s", (market.series,))
    first = (cur.fetchone() or {}).get("t")
    if first is None:
        return 0  # nothing collected yet: the forward sync starts from the floor anyway
    first = first.replace(tzinfo=timezone.utc) if first.tzinfo is None else first
    if (first - floor).total_seconds() < BACKFILL_GAP_SECONDS:
        return 0
    return sync_settled_markets(cur, market, floor, max_close=first)


def refresh(cur) -> Dict[str, int]:
    now = utc_now()
    deadline = time.time() + PASS_BUDGET_SECONDS
    end_ts = int(now.timestamp()) - 60
    stats: Dict[str, int] = {}
    # One spot-candle series per distinct underlying in MARKETS (BTC-USD, ETH-USD, …),
    # each backfilled over the longest history_days of the markets that use it.
    by_symbol: Dict[str, int] = {}
    for m in MARKETS.values():
        if m.underlying is None:  # sports: no spot series to sync
            continue
        if m.kind != "binary":  # Continuous venues have their own native collectors.
            continue
        by_symbol[m.underlying] = max(by_symbol.get(m.underlying, 0), m.history_days)
    for symbol, history_days in by_symbol.items():
        cur.execute("SELECT MAX(start_ts) AS t FROM spot_candles_1m WHERE symbol=%s", (symbol,))
        last = (cur.fetchone() or {}).get("t")
        start = int(last) + 60 if last else int((now - timedelta(days=history_days + 1)).timestamp())
        stats["spot_" + symbol] = sync_spot_candles(cur, symbol, start, end_ts)
        try:
            stats["spot_backfill_" + symbol] = backfill_spot(cur, symbol, history_days, now)
        except Exception as e:
            print("[market_history] %s spot backfill failed: %r (retry next pass)" % (symbol, e), flush=True)
    requested = _requested(cur)
    binary = [m for m in MARKETS.values() if m.kind == "binary" and m.source == "candles"  # never perpetuals
              and _history_wanted(m, requested)]
    stats["deferred"] = sync_all_markets(cur, binary, now, deadline, stats, requested=requested)
    return stats


def _sync_settled(cur, market: Market, now: datetime, stats: Dict[str, int]) -> None:
    cur.execute("SELECT MAX(close_time) AS t FROM hist_markets WHERE series_ticker=%s", (market.series,))
    last_close = (cur.fetchone() or {}).get("t")
    floor = now - timedelta(days=market.history_days)
    since = max(last_close.replace(tzinfo=timezone.utc) - timedelta(hours=2), floor) if last_close else floor
    stats[market.key + "_markets"] = sync_settled_markets(cur, market, since)
    stats[market.key + "_backfill"] = backfill_settled_markets(cur, market, now)


def _history_wanted(market: Market, requested: List[str]) -> bool:
    return (market.key in CURATED or market.key in requested or _priority_rank(market.series) is not None
            or bool(HISTORY_SERIES_PATTERN.search(market.series)))


def _priority_rank(series: str) -> Optional[int]:
    if series in PRIORITY_SERIES:
        return PRIORITY_SERIES.index(series)
    if PRIORITY_PREFIXES and series.startswith(PRIORITY_PREFIXES):
        return len(PRIORITY_SERIES)
    return None


def _requested(cur) -> List[str]:
    """Markets research asked for history on (app/research/rsi_repair.py): synced right after the curated set."""
    from app.research import rsi_repair
    return [r["market"] for r in rsi_repair.wanted(cur, "history")]


def sync_all_markets(cur, markets, now: datetime, deadline: float, stats: Dict[str, int],
                     requested: Optional[List[str]] = None) -> int:
    """Settled markets + candles for every market within the pass budget. Curated first (they are
    what's traded), then PRIORITY_* series, both with no per-market slice; then the rest of the
    catalog (~1,000 series) in a rotating order, MARKET_SLICE_SECONDS each, resumed where the last
    pass ran out. Returns how many markets were left for the next pass.

    Contained per market: one series' API/DB hiccup must not abort the others (it retries next pass).
    """
    global _candle_rotation
    curated = [m for m in markets if m.key in CURATED]
    ranked = [(r, i, m) for i, m in enumerate(markets) if m.key not in CURATED
              for r in [_priority_rank(m.series)] if r is not None]
    priority = [m for _r, _i, m in sorted(ranked, key=lambda t: (t[0], t[1]))]
    asked = [m for k in (requested or []) for m in markets if m.key == k and m.key not in CURATED]
    priority = asked + [m for m in priority if m not in asked]
    front = curated + priority
    front_keys = {m.key for m in front}
    rest = [m for m in markets if m.key not in front_keys]
    if _candle_rotation is None:
        _candle_rotation = random.randrange(len(rest)) if rest else 0
    start = _candle_rotation % len(rest) if rest else 0
    order = front + rest[start:] + rest[:start]
    for i, market in enumerate(order):
        if time.time() >= deadline:
            _candle_rotation = start + max(i - len(front), 0)
            return len(order) - i
        last = _last_settled.get(market.key)
        if market.key in CURATED or last is None or time.time() - last >= SETTLED_MIN_INTERVAL_SECONDS:
            try:
                _sync_settled(cur, market, now, stats)
                _last_settled[market.key] = time.time()
            except Exception as e:
                print("[market_history] %s sync failed: %r (retry next pass)" % (market.key, e), flush=True)
        slice_end = deadline if market.key in front_keys else min(deadline, time.time() + MARKET_SLICE_SECONDS)
        try:
            sync_market_candles(cur, market, deadline=slice_end)
        except Exception as e:
            print("[market_history] %s candles failed: %r (retry next pass)" % (market.key, e), flush=True)
    _candle_rotation = 0
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    while True:
        sleep = REFRESH_SECONDS
        try:
            conn = get_db_conn()
            try:
                with conn.cursor() as cur:
                    stats = refresh(cur)
                    print("[market_history] %s %s" % (utc_now().isoformat(), stats), flush=True)
                    if stats.get("deferred"):
                        sleep = BACKLOG_SLEEP_SECONDS  # backlog left: come straight back for it
                    # Heartbeat on a COMPLETED cycle only: a wedged/hung refresh never reaches
                    # here, so the heartbeat goes stale and the watchdog restarts us (self-heal).
                    cur.execute(
                        """
                        INSERT INTO collector_state (state_key, state_value, updated_at_utc)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                        """,
                        (
                            "market_history_last_cycle",
                            json.dumps({"cycle_utc": utc_now().isoformat()}),
                            utc_now().replace(tzinfo=None),
                        ),
                    )
            finally:
                conn.close()
        except Exception as e:  # keep the loop alive; a dead collector is what stales the backtests
            print("[market_history] ERROR %s" % e, flush=True)
            if args.once:
                raise
        if args.once:
            return
        time.sleep(sleep)


if __name__ == "__main__":
    main()
