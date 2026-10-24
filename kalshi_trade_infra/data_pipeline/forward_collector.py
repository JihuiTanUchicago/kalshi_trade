import asyncio
import base64
import json
import os
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

import certifi
import pymysql
import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from data_pipeline.common import (micro_series, next_20s_mark, api_get, fetch_open_markets, get_db_conn,
                                  parse_iso_to_dt, utc_now)


def choose_active_event(markets: List[Dict]) -> Optional[str]:
    now = utc_now()
    in_window = []
    fallback = []
    for m in markets:
        event_ticker = m.get("event_ticker")
        if not event_ticker:
            continue
        open_t = parse_iso_to_dt(m.get("open_time"))
        close_t = parse_iso_to_dt(m.get("close_time"))
        exp_t = parse_iso_to_dt(m.get("expected_expiration_time"))
        if open_t and close_t and open_t <= now < close_t:
            in_window.append((close_t, event_ticker))
        elif close_t and close_t >= now:
            fallback.append((close_t, event_ticker))
        elif exp_t and exp_t >= now:
            fallback.append((exp_t, event_ticker))
    if in_window:
        in_window.sort(key=lambda x: x[0])
        return in_window[0][1]
    if fallback:
        fallback.sort(key=lambda x: x[0])
        return fallback[0][1]
    return None


def _closed(m: Dict) -> bool:
    close_t = parse_iso_to_dt(m.get("close_time"))
    return close_t is not None and close_t <= utc_now()


def end_minute_bucket(dt: datetime) -> datetime:
    base = dt.replace(second=0, microsecond=0)
    if dt.second == 0 and dt.microsecond == 0:
        return base
    return base + timedelta(minutes=1)


# forward_quotes is the ONLY RDS source of top-of-book SIZES (yes_bid_size_fp/
# yes_ask_size_fp) -> the input to orderbook_imbalance (the S3 snapshot lake has
# quotes but no sizes). We snapshot the live order book for every configured micro
# series (common.micro_series(), BTC first), not just BTC, so those sizes exist for
# the other series too. Per-series selection logic is unchanged from the BTC path.
def fetch_active_markets(series_ticker: str) -> List[Dict]:
    # No unfiltered /markets fallback: it lists ~50h of past and future contracts, so the
    # tracked event stayed "present" after it closed and the collector snapshotted a dead
    # market for hours (2026-10-24 16:15Z-). fetch_open_markets falls back to /events.
    return fetch_open_markets(series_ticker, get=api_get)


def fetch_active_kxbtc15m_markets() -> List[Dict]:  # back-compat alias
    return fetch_active_markets("KXBTC15M")


class WsTickerFeed:
    def __init__(self) -> None:
        self.key_id = os.getenv("KALSHI_WS_KEY_ID") or os.getenv("PROD_KEYID")
        self.key_path = os.getenv("KALSHI_WS_PRIVATE_KEY_PATH") or os.getenv("PROD_KEYFILE")
        self.ws_path = "/trade-api/ws/v2"
        self.ws_url = f"wss://api.elections.kalshi.com{self.ws_path}"
        self.enabled = bool(self.key_id and self.key_path and os.path.exists(self.key_path))
        self.started = False
        self._lock = threading.Lock()
        self._latest_by_ticker: Dict[str, Dict] = {}
        self._last_quote_by_ticker: Dict[str, tuple] = {}
        self._event_by_ticker: Dict[str, str] = {}
        self._pending_subscriptions: Set[str] = set()
        self._msg_id = 1

        self._private_key = None
        if self.enabled:
            with open(self.key_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(f.read(), password=None)
        self._db_conn = None
        self._db_cur = None
        self._ws = None
        self._ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    def _ensure_db(self) -> None:
        if self._db_conn is None:
            self._db_conn = get_db_conn()
            self._db_cur = self._db_conn.cursor()

    def _auth_headers(self) -> Dict[str, str]:
        ts = str(int(time.time() * 1000))
        msg = ts + "GET" + self.ws_path
        sig = base64.b64encode(
            self._private_key.sign(
                msg.encode("utf-8"),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
        ).decode("utf-8")
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    def start(self) -> None:
        if not self.enabled or self.started:
            return
        self.started = True
        t = threading.Thread(target=self._run_forever, daemon=True)
        t.start()

    def request_subscribe(self, tickers: List[str], ticker_to_event: Dict[str, str]) -> None:
        if not self.enabled:
            return
        with self._lock:
            for t in tickers:
                self._pending_subscriptions.add(t)
            self._event_by_ticker.update(ticker_to_event)

    def get_latest(self, ticker: str) -> Optional[Dict]:
        with self._lock:
            return self._latest_by_ticker.get(ticker)

    def _run_forever(self) -> None:
        while True:
            try:
                asyncio.run(self._ws_loop())
            except Exception as e:
                print(f"[WARN] websocket loop error: {e}")
            time.sleep(2)

    async def _ws_loop(self) -> None:
        headers = self._auth_headers()
        async with websockets.connect(
            self.ws_url,
            additional_headers=headers,
            ssl=self._ssl_ctx,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=15,
        ) as ws:
            self._ws = ws
            print("websocket connected")
            while True:
                await self._flush_pending_subscriptions()
                try:
                    msg_raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                data = json.loads(msg_raw)
                if data.get("type") == "trade":
                    self._record_trade(data.get("msg") or {})
                    continue
                if data.get("type") != "ticker":
                    continue
                msg = data.get("msg") or {}
                ticker = msg.get("market_ticker")
                if not ticker:
                    continue
                with self._lock:
                    self._latest_by_ticker[ticker] = msg
                self._record_quote_change(msg)

    async def _flush_pending_subscriptions(self) -> None:
        with self._lock:
            tickers = sorted(self._pending_subscriptions)
            self._pending_subscriptions.clear()
        if not tickers or self._ws is None:
            return
        payload = {
            "id": self._msg_id,
            "cmd": "subscribe",
            # "trade" streams every print on these markets into market_trades: who took
            # liquidity, at what price, how many. Book ticks alone can only bracket when a
            # resting order would have filled; prints say when one actually could have.
            "params": {"channels": ["ticker", "trade"], "market_tickers": tickers},
        }
        self._msg_id += 1
        await self._ws.send(json.dumps(payload))

    def _record_quote_tick(self, msg: Dict, ts) -> None:
        """One row per top-of-book change. Best effort: a failure here must
        never interrupt the feed the trading engine prices from."""
        try:
            self._ensure_db()
            self._db_cur.execute(
                """
                INSERT INTO forward_quote_ticks
                (observed_at_utc,market_ticker,event_ticker,yes_bid_dollars,yes_ask_dollars,
                 yes_bid_size_fp,yes_ask_size_fp)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    ts.replace(tzinfo=None),
                    msg.get("market_ticker"),
                    self._event_by_ticker.get(msg.get("market_ticker")),
                    msg.get("yes_bid_dollars"),
                    msg.get("yes_ask_dollars"),
                    msg.get("yes_bid_size_fp") or msg.get("yes_bid_size"),
                    msg.get("yes_ask_size_fp") or msg.get("yes_ask_size"),
                ),
            )
        except Exception as e:
            print(f"[WARN] quote tick insert failed: {e}")

    def _record_trade(self, msg: Dict) -> None:
        """One market_trades row per print. Best effort, like the quote ticks."""
        row = trade_row(msg)
        if row is None:
            return
        try:
            self._ensure_db()
            insert_trade_row(self._db_cur, row)
        except Exception as e:
            print(f"[WARN] trade insert failed: {e}")

    def _record_quote_change(self, msg: Dict) -> None:
        ticker = msg.get("market_ticker")
        if not ticker:
            return
        bid = msg.get("yes_bid_dollars")
        ask = msg.get("yes_ask_dollars")
        if bid is None or ask is None:
            return
        quote = (str(bid), str(ask))

        prev = self._last_quote_by_ticker.get(ticker)
        self._last_quote_by_ticker[ticker] = quote
        if prev is None or prev == quote:
            return

        ts = parse_iso_to_dt(msg.get("time")) or utc_now()
        # Every top-of-book change, at tick resolution. forward_quotes samples
        # this same socket on 20-second marks and throws the rest away, which
        # is fine for features and useless for execution: a fill model cannot
        # be built from a price that is only observed three times a minute,
        # and this history cannot be reconstructed after the fact.
        self._record_quote_tick(msg, ts)
        bucket = end_minute_bucket(ts).replace(tzinfo=None)
        event_ticker = self._event_by_ticker.get(ticker)

        self._ensure_db()
        self._db_cur.execute(
            """
            INSERT INTO ws_quote_change_1m
            (snapshot_minute_utc,market_ticker,event_ticker,quote_change_events,last_yes_bid_dollars,last_yes_ask_dollars,updated_at_utc)
            VALUES (%s,%s,%s,1,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              quote_change_events=quote_change_events+1,
              event_ticker=COALESCE(VALUES(event_ticker), event_ticker),
              last_yes_bid_dollars=VALUES(last_yes_bid_dollars),
              last_yes_ask_dollars=VALUES(last_yes_ask_dollars),
              updated_at_utc=VALUES(updated_at_utc)
            """,
            (bucket, ticker, event_ticker, bid, ask, utc_now().replace(tzinfo=None)),
        )


def _dollars(msg: Dict, key: str) -> Optional[float]:
    """A price in dollars from a WS trade message: ``<key>_dollars`` if sent, else cents."""
    v = msg.get(key + "_dollars")
    if v is not None:
        return float(v)
    v = msg.get(key)
    return None if v is None else float(v) / 100.0


def trade_row(msg: Dict) -> Optional[tuple]:
    """The market_trades row for one WS ``trade`` message, or None if it is unusable."""
    trade_id, ticker = msg.get("trade_id"), msg.get("market_ticker")
    if not trade_id or not ticker:
        return None
    try:
        ts = msg.get("ts")
        created = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts is not None else utc_now()
        yes, no = _dollars(msg, "yes_price"), _dollars(msg, "no_price")
        count = msg.get("count_fp")
        count = float(count) if count is not None else (None if msg.get("count") is None else float(msg["count"]))
    except (TypeError, ValueError):
        return None
    return (str(trade_id), ticker, created.replace(tzinfo=None), yes, no, count, msg.get("taker_side"),
            utc_now().replace(tzinfo=None), json.dumps(msg))


def insert_trade_row(cur, row: tuple) -> None:
    # INSERT IGNORE: a reconnect resubscribes, and the same trade_id can arrive twice.
    cur.execute(
        """
        INSERT IGNORE INTO market_trades
        (trade_id,ticker,created_time,yes_price_dollars,no_price_dollars,count_fp,taker_side,collected_at_utc,raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        row,
    )


# The only raw fields anything reads back from markets.raw_json (model_features_1m_builder's strike
# target), plus a few small identifying ones. The full payload averaged 3.5KB a row - multivariate
# legs, custom_strike and rules text - across ~1M new markets a day, which grew the table to 180GB
# and is most of the RDS's ~10GB/day.
MARKET_RAW_KEYS = ("floor_strike", "cap_strike", "strike_type", "strike_price", "functional_strike",
                   "market_type", "result", "status")


def slim_market_raw(m: Dict) -> Dict:
    return {k: m[k] for k in MARKET_RAW_KEYS if m.get(k) is not None}


def insert_market_upserts(cur, markets: List[Dict]) -> None:
    now = utc_now().replace(tzinfo=None)
    for m in markets:
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
                now,
                json.dumps(slim_market_raw(m)),
            ),
        )


# A stuck/long transaction elsewhere can hold a lock on `markets` and make the upsert block (a
# 24-min stuck kalshi_series txn once crash-looped the whole BTC feed this way). The catalog is
# non-critical metadata; the live price snapshot below does NOT depend on it (it reads `markets`
# from the API, writes a different table). So on lock contention we SKIP the catalog this cycle
# and keep the feed alive, instead of letting the exception propagate out of the loop. The short
# session innodb_lock_wait_timeout set in loop_forever bounds the wait to seconds, not ~50s.
_LOCK_CONTENTION_ERRNOS = (1205, 1213)  # lock wait timeout, deadlock


def upsert_catalog(cur, markets: List[Dict]) -> bool:
    """Upsert the markets catalog, returning False (skipping) on DB lock contention so a stuck
    transaction elsewhere can't crash the live feed. Re-raises anything else (e.g. a dropped
    connection), which the caller handles by reconnecting."""
    try:
        insert_market_upserts(cur, markets)
        return True
    except pymysql.err.OperationalError as e:
        if e.args and e.args[0] in _LOCK_CONTENTION_ERRNOS:
            print(f"[WARN] markets catalog upsert skipped (lock contention errno={e.args[0]}); price feed continues")
            return False
        raise


def _pick_value(ws_msg: Optional[Dict], market: Dict, key: str):
    if ws_msg and ws_msg.get(key) is not None:
        return ws_msg.get(key)
    return market.get(key)


def insert_snapshot_rows(
    cur,
    event_markets: List[Dict],
    event_ticker: str,
    snapshot_time_utc: datetime,
    ws_feed: Optional[WsTickerFeed] = None,
) -> int:
    snapshot_naive = snapshot_time_utc.replace(tzinfo=None)
    rows = 0
    for m in event_markets:
        ticker = m.get("ticker")
        ws_msg = ws_feed.get_latest(ticker) if (ws_feed and ticker) else None
        cur.execute(
            """
            INSERT INTO forward_quotes
            (snapshot_time_utc,market_ticker,event_ticker,yes_bid_dollars,yes_ask_dollars,yes_bid_size_fp,yes_ask_size_fp,volume_fp,open_interest_fp,no_bid_dollars,no_ask_dollars,status,raw_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                snapshot_naive,
                ticker,
                event_ticker,
                _pick_value(ws_msg, m, "yes_bid_dollars"),
                _pick_value(ws_msg, m, "yes_ask_dollars"),
                _pick_value(ws_msg, m, "yes_bid_size_fp"),
                _pick_value(ws_msg, m, "yes_ask_size_fp"),
                _pick_value(ws_msg, m, "volume_fp"),
                _pick_value(ws_msg, m, "open_interest_fp"),
                # WS ticker messages don't carry the NO side; fall back to the
                # last REST market snapshot so this is populated on (almost)
                # every row instead of only the ~0.7% of rows where ws_msg was
                # entirely absent (see research/two_sided_quote_check.py).
                _pick_value(ws_msg, m, "no_bid_dollars"),
                _pick_value(ws_msg, m, "no_ask_dollars"),
                m.get("status"),
                json.dumps(ws_msg if ws_msg else m),
            ),
        )
        rows += 1
    return rows


def insert_na_snapshot(cur, snapshot_time_utc: datetime, reason: str, event_ticker: Optional[str] = None) -> None:
    cur.execute(
        """
        INSERT INTO forward_quotes
        (snapshot_time_utc,market_ticker,event_ticker,yes_bid_dollars,yes_ask_dollars,yes_bid_size_fp,yes_ask_size_fp,volume_fp,open_interest_fp,status,raw_json)
        VALUES (%s,%s,%s,NULL,NULL,NULL,NULL,NULL,NULL,%s,%s)
        """,
        (
            snapshot_time_utc.replace(tzinfo=None),
            "N/A",
            event_ticker,
            f"N/A_{reason}",
            json.dumps({"reason": reason}),
        ),
    )


def loop_forever() -> None:
    conn = get_db_conn()
    ws_feed = WsTickerFeed()
    if ws_feed.enabled:
        ws_feed.start()
        print("Forward collector mode=websocket+rest-fallback")
    else:
        print("Forward collector mode=rest-only (missing websocket creds)")

    series_list = micro_series()
    with conn.cursor() as cur:
        cur.execute("SET SESSION innodb_lock_wait_timeout=5")  # fail fast on a contended write; don't block the 20s cadence
        # One tracked active event per series (BTC's selection logic, unchanged, per series).
        current_event: Dict[str, Optional[str]] = {}
        print(f"Forward collector started immediately (no initial 15m wait). Series={series_list}")
        print("Writing 20-second aligned snapshots (:00/:20/:40) into forward_quotes.")

        while True:
            tick = next_20s_mark()
            sleep_s = max(0.0, (tick - utc_now()).total_seconds())
            time.sleep(sleep_s)

            # Heartbeat EVERY tick, before any market work. Freshness then reflects
            # "the loop is alive," not "a 15-minute event happens to be open" - so a
            # quiet gap between events no longer looks STALE. The richer snapshot
            # write below refreshes state_value when there IS an active event.
            cur.execute(
                """INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                   VALUES ('forward_collector_last_snapshot',%s,%s)
                   ON DUPLICATE KEY UPDATE updated_at_utc=VALUES(updated_at_utc)""",
                (json.dumps({"heartbeat_tick": tick.isoformat()}), utc_now().replace(tzinfo=None)),
            )

            # The first series (BTC by default) keeps the original N/A-row semantics the
            # live-path freshness checks depend on; extra series are additive and only
            # ever make forward_quotes fresher, never staler, so they skip the N/A rows.
            total_rows = 0
            events_snapshotted: List[str] = []
            for idx, series in enumerate(series_list):
                is_primary = idx == 0
                try:
                    markets = fetch_active_markets(series)
                except Exception as e:
                    if is_primary:
                        insert_na_snapshot(cur, tick, "MARKETS_API_ERROR")
                    print(f"N/A snapshot at={tick.isoformat()} series={series} reason=MARKETS_API_ERROR err={e}")
                    continue

                if markets:
                    upsert_catalog(cur, markets)
                else:
                    if is_primary:
                        insert_na_snapshot(cur, tick, "NO_OPEN_KXBTC15M_MARKET")
                    print(f"N/A snapshot at={tick.isoformat()} series={series} reason=NO_OPEN_MARKET")
                    continue

                ev = current_event.get(series)
                if ev is None or not any(m.get("event_ticker") == ev and not _closed(m) for m in markets):
                    ev = choose_active_event(markets)
                    current_event[series] = ev
                    print(f"Active event [{series}] -> {ev}")

                if not ev:
                    if is_primary:
                        insert_na_snapshot(cur, tick, "NO_ACTIVE_EVENT")
                    print(f"N/A snapshot at={tick.isoformat()} series={series} reason=NO_ACTIVE_EVENT")
                    continue

                event_markets = [m for m in markets if m.get("event_ticker") == ev]
                if not event_markets:
                    if is_primary:
                        insert_na_snapshot(cur, tick, "NO_EVENT_MARKETS", ev)
                    print(f"N/A snapshot at={tick.isoformat()} series={series} reason=NO_EVENT_MARKETS event={ev}")
                    continue

                ticker_to_event = {m.get("ticker"): m.get("event_ticker") for m in event_markets if m.get("ticker")}
                if ws_feed.enabled:
                    ws_feed.request_subscribe(list(ticker_to_event.keys()), ticker_to_event)

                total_rows += insert_snapshot_rows(cur, event_markets, ev, tick, ws_feed if ws_feed.enabled else None)
                events_snapshotted.append(ev)

            if events_snapshotted:
                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES (%s,%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    (
                        "forward_collector_last_snapshot",
                        json.dumps(
                            {
                                "event_ticker": events_snapshotted[0],  # primary series, back-compat
                                "events": events_snapshotted,
                                "rows": total_rows,
                                "snapshot_time_utc": tick.isoformat(),
                                "mode": "websocket" if ws_feed.enabled else "rest",
                            }
                        ),
                        utc_now().replace(tzinfo=None),
                    ),
                )
                print(f"snapshot events={events_snapshotted} rows={total_rows} at={tick.isoformat()}")


def main() -> None:
    while True:
        try:
            loop_forever()
        except Exception as e:
            print(f"[ERROR] forward collector crashed: {e}")
            time.sleep(5)


def _selfcheck() -> None:
    # Config comes from common.micro_series(); BTC must stay first (live-path invariant).
    assert micro_series()[0] == "KXBTC15M" and len(micro_series()) > 1, micro_series()
    # Per-series active-event selection prefers the in-window event over a later fallback.
    now = utc_now()
    markets = [
        {"event_ticker": "KXETH15M-A", "open_time": (now - timedelta(minutes=1)).isoformat(),
         "close_time": (now + timedelta(minutes=5)).isoformat()},
        {"event_ticker": "KXETH15M-B", "open_time": (now + timedelta(minutes=5)).isoformat(),
         "close_time": (now + timedelta(minutes=20)).isoformat()},
    ]
    assert choose_active_event(markets) == "KXETH15M-A", choose_active_event(markets)
    print("forward_collector selfcheck ok")


if __name__ == "__main__":
    import sys
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
