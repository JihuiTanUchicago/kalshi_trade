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
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import requests

from app.markets import MARKETS, Market
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


def sync_settled_markets(cur, market: Market, min_close: datetime) -> int:
    written = 0
    cursor = None
    while True:
        params = {
            "series_ticker": market.series,
            "status": "settled",
            "min_close_ts": int(min_close.timestamp()),
            "limit": 1000,
        }
        if cursor:
            params["cursor"] = cursor
        data = api_get("/markets", params)
        rows = []
        for m in data.get("markets") or []:
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
            written += len(rows)
        cursor = data.get("cursor")
        if not cursor:
            return written
        time.sleep(KALSHI_PAUSE_SECONDS)


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


def sync_market_candles(cur, market: Market, limit: int = 2000) -> int:
    """Fetch candles for settled markets that do not have them yet."""
    cur.execute(
        """
        SELECT ticker, strike, open_time, close_time FROM hist_markets
        WHERE series_ticker=%s AND candles_done=0 ORDER BY close_time DESC LIMIT %s
        """,
        (market.series, limit),
    )
    pending = cur.fetchall()
    done = 0
    for m in pending:
        open_ts = int(m["open_time"].replace(tzinfo=timezone.utc).timestamp())
        close_ts = int(m["close_time"].replace(tzinfo=timezone.utc).timestamp())
        if market.close_hour_et is not None:
            spot = _spot_close_at(cur, market.underlying, open_ts)
            if spot is None:
                continue  # underlying spot history not there yet; try again next pass
            if abs(float(m["strike"]) / spot - 1.0) > LADDER_BAND:
                cur.execute("UPDATE hist_markets SET candles_done=2 WHERE ticker=%s", (m["ticker"],))
                continue
        data = api_get(
            "/series/%s/markets/%s/candlesticks" % (market.series, m["ticker"]),
            {"start_ts": open_ts, "end_ts": close_ts, "period_interval": market.candle_minutes},
        )
        now = _naive_utc(utc_now())
        rows = []
        for c in data.get("candlesticks") or []:
            bid = c.get("yes_bid") or {}
            ask = c.get("yes_ask") or {}
            price = c.get("price") or {}
            rows.append(
                (
                    m["ticker"],
                    int(c["end_period_ts"]),
                    market.candle_minutes,
                    _num(bid.get("open_dollars")),
                    _num(bid.get("close_dollars")),
                    _num(ask.get("open_dollars")),
                    _num(ask.get("close_dollars")),
                    _num(price.get("open_dollars")),
                    _num(price.get("close_dollars")),
                    _num(c.get("volume_fp")),
                    _num(c.get("open_interest_fp")),
                    now,
                    json.dumps(c),
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


def refresh(cur) -> Dict[str, int]:
    now = utc_now()
    end_ts = int(now.timestamp()) - 60
    stats: Dict[str, int] = {}
    # One spot-candle series per distinct underlying in MARKETS (BTC-USD, ETH-USD, …),
    # each backfilled over the longest history_days of the markets that use it.
    by_symbol: Dict[str, int] = {}
    for m in MARKETS.values():
        if m.underlying is None:  # sports: no spot series to sync
            continue
        by_symbol[m.underlying] = max(by_symbol.get(m.underlying, 0), m.history_days)
    for symbol, history_days in by_symbol.items():
        cur.execute("SELECT MAX(start_ts) AS t FROM spot_candles_1m WHERE symbol=%s", (symbol,))
        last = (cur.fetchone() or {}).get("t")
        start = int(last) + 60 if last else int((now - timedelta(days=history_days + 1)).timestamp())
        stats["spot_" + symbol] = sync_spot_candles(cur, symbol, start, end_ts)
    for market in MARKETS.values():
        cur.execute("SELECT MAX(close_time) AS t FROM hist_markets WHERE series_ticker=%s", (market.series,))
        last_close = (cur.fetchone() or {}).get("t")
        floor = now - timedelta(days=market.history_days)
        since = max(last_close.replace(tzinfo=timezone.utc) - timedelta(hours=2), floor) if last_close else floor
        stats[market.key + "_markets"] = sync_settled_markets(cur, market, since)
        stats[market.key + "_candles"] = sync_market_candles(cur, market)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    while True:
        try:
            conn = get_db_conn()
            try:
                with conn.cursor() as cur:
                    print("[market_history] %s %s" % (utc_now().isoformat(), refresh(cur)), flush=True)
            finally:
                conn.close()
        except Exception as e:  # keep the loop alive; a dead collector is what stales the backtests
            print("[market_history] ERROR %s" % e, flush=True)
            if args.once:
                raise
        if args.once:
            return
        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    main()
