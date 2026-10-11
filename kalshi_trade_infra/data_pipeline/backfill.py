import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from data_pipeline.common import api_get, get_db_conn, parse_iso_to_dt, utc_now

CUTOFF_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
TARGET_PREFIX = "KXBTC15M-"
ET = ZoneInfo("America/New_York")
INCLUDE_RAW_TRADES = os.getenv("BACKFILL_INCLUDE_RAW_TRADES", "false").lower() == "true"


def is_btc_15_market(m: Dict) -> bool:
    ticker = m.get("ticker", "")
    event_ticker = m.get("event_ticker", "") or ""
    # Strict scope: only BTC up/down 15m contract family.
    return ticker.startswith(TARGET_PREFIX) or event_ticker.startswith("KXBTC15M-")


def upsert_market(cur, m: Dict) -> None:
    cur.execute(
        """
        INSERT INTO markets (ticker,event_ticker,series_ticker,title,subtitle,status,open_time,close_time,expiration_time,last_seen_utc,raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          event_ticker=VALUES(event_ticker), series_ticker=VALUES(series_ticker), title=VALUES(title), subtitle=VALUES(subtitle),
          status=VALUES(status), open_time=VALUES(open_time), close_time=VALUES(close_time), expiration_time=VALUES(expiration_time),
          last_seen_utc=VALUES(last_seen_utc), raw_json=VALUES(raw_json)
        """,
        (
            m.get("ticker"),
            m.get("event_ticker"),
            m.get("series_ticker"),
            m.get("title"),
            m.get("subtitle"),
            m.get("status"),
            parse_iso_to_dt(m.get("open_time")),
            parse_iso_to_dt(m.get("close_time")),
            parse_iso_to_dt(m.get("expiration_time")),
            utc_now().replace(tzinfo=None),
            json.dumps(m),
        ),
    )


def insert_trades(cur, ticker: str) -> int:
    inserted = 0
    cursor: Optional[str] = None
    while True:
        params = {"ticker": ticker, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        data = api_get("/markets/trades", params=params)
        trades = data.get("trades", [])
        for t in trades:
            cur.execute(
                """
                INSERT IGNORE INTO market_trades
                (trade_id,ticker,created_time,yes_price_dollars,no_price_dollars,count_fp,taker_side,collected_at_utc,raw_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    t.get("trade_id"),
                    t.get("ticker"),
                    parse_iso_to_dt(t.get("created_time")),
                    t.get("yes_price_dollars"),
                    t.get("no_price_dollars"),
                    t.get("count_fp"),
                    t.get("taker_side"),
                    utc_now().replace(tzinfo=None),
                    json.dumps(t),
                ),
            )
            inserted += cur.rowcount
        cursor = data.get("cursor")
        if not cursor or not trades:
            break
        time.sleep(0.15)
    return inserted


def insert_candles(cur, ticker: str, open_time: datetime, close_time: datetime) -> int:
    start_ts = int(open_time.timestamp())
    end_ts = int(close_time.timestamp())
    if end_ts <= start_ts:
        return 0
    data = api_get(
        "/markets/candlesticks",
        params={
            "market_tickers": ticker,
            "period_interval": 1,
            "start_ts": start_ts,
            "end_ts": end_ts,
        },
    )
    markets = data.get("markets", [])
    if not markets:
        return 0
    candles = markets[0].get("candlesticks", [])
    inserted = 0
    for c in candles:
        yes_bid = c.get("yes_bid") or {}
        yes_ask = c.get("yes_ask") or {}
        price = c.get("price") or {}
        cur.execute(
            """
            INSERT INTO market_candles
            (ticker,end_period_ts,period_interval_minutes,yes_bid_open,yes_bid_close,yes_ask_open,yes_ask_close,price_open,price_close,volume_fp,open_interest_fp,collected_at_utc,raw_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              yes_bid_open=VALUES(yes_bid_open), yes_bid_close=VALUES(yes_bid_close),
              yes_ask_open=VALUES(yes_ask_open), yes_ask_close=VALUES(yes_ask_close),
              price_open=VALUES(price_open), price_close=VALUES(price_close),
              volume_fp=VALUES(volume_fp), open_interest_fp=VALUES(open_interest_fp),
              collected_at_utc=VALUES(collected_at_utc), raw_json=VALUES(raw_json)
            """,
            (
                ticker,
                c.get("end_period_ts"),
                1,
                yes_bid.get("open_dollars"),
                yes_bid.get("close_dollars"),
                yes_ask.get("open_dollars"),
                yes_ask.get("close_dollars"),
                price.get("open_dollars"),
                price.get("close_dollars"),
                c.get("volume_fp"),
                c.get("open_interest_fp"),
                utc_now().replace(tzinfo=None),
                json.dumps(c),
            ),
        )
        inserted += cur.rowcount
    return inserted


def collect_markets() -> List[Dict]:
    out: List[Dict] = []
    now_et = utc_now().astimezone(ET).replace(second=0, microsecond=0)
    start_et = CUTOFF_START.astimezone(ET).replace(second=0, microsecond=0)
    # round start to 15-minute bucket boundary
    start_et = start_et.replace(minute=(start_et.minute // 15) * 15)
    t = start_et
    probes = 0

    print(f"Deterministic KXBTC15M probe from {start_et.isoformat()} to {now_et.isoformat()}")
    while t <= now_et + timedelta(minutes=30):
        ticker = f"{TARGET_PREFIX}{t.strftime('%y%b%d%H%M').upper()}-{t.minute:02d}"
        probes += 1
        try:
            data = api_get(f"/markets/{ticker}")
            m = data.get("market", {})
            if m and is_btc_15_market(m):
                out.append(m)
        except Exception:
            # Missing or unavailable ticker is expected in sparse periods; skip.
            pass

        if probes % 100 == 0:
            print(f"probe progress={probes} found={len(out)} latest={ticker}")
        t += timedelta(minutes=15)
        time.sleep(0.03)

    if not out:
        print("No KXBTC15M markets found from deterministic probe.")
        return out

    print(f"Collected KXBTC15M candidates={len(out)}")
    return out


def main() -> None:
    conn = get_db_conn()
    markets = collect_markets()
    total_trades = 0
    total_candles = 0

    with conn.cursor() as cur:
        for i, m in enumerate(markets, start=1):
            ticker = m.get("ticker")
            if not ticker:
                continue
            upsert_market(cur, m)
            ot = parse_iso_to_dt(m.get("open_time"))
            ct = parse_iso_to_dt(m.get("close_time"))
            if ot and ct:
                try:
                    total_candles += insert_candles(cur, ticker, ot, ct)
                except Exception as e:
                    print(f"[WARN] candles failed {ticker}: {e}")
            if INCLUDE_RAW_TRADES:
                try:
                    total_trades += insert_trades(cur, ticker)
                except Exception as e:
                    print(f"[WARN] trades failed {ticker}: {e}")
            if i % 25 == 0:
                print(f"progress markets={i}/{len(markets)} trades={total_trades} candles={total_candles}")

        cur.execute(
            """
            INSERT INTO collector_state (state_key,state_value,updated_at_utc)
            VALUES (%s,%s,%s)
            ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
            """,
            (
                "historical_backfill_last_run",
                json.dumps({"markets": len(markets), "trades": total_trades, "candles": total_candles}),
                utc_now().replace(tzinfo=None),
            ),
        )

    conn.close()
    print(f"Done. markets={len(markets)} trades={total_trades} candles={total_candles}")


if __name__ == "__main__":
    main()
