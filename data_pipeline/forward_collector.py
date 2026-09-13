import asyncio
import base64
import json
import os
import ssl
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

import certifi
import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from data_pipeline.common import api_get, get_db_conn, parse_iso_to_dt, utc_now


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


def end_minute_bucket(dt: datetime) -> datetime:
    base = dt.replace(second=0, microsecond=0)
    if dt.second == 0 and dt.microsecond == 0:
        return base
    return base + timedelta(minutes=1)


def next_20s_mark(now: Optional[datetime] = None) -> datetime:
    if now is None:
        now = utc_now()
    base = now.replace(microsecond=0)
    sec = base.second
    if sec < 20:
        return base.replace(second=20)
    if sec < 40:
        return base.replace(second=40)
    return (base + timedelta(minutes=1)).replace(second=0)


def fetch_active_kxbtc15m_markets() -> List[Dict]:
    data = api_get("/markets", {"series_ticker": "KXBTC15M", "status": "open", "limit": 200})
    markets = data.get("markets", [])
    if markets:
        return markets
    # Fallback in case status taxonomy changes.
    data = api_get("/markets", {"series_ticker": "KXBTC15M", "limit": 200})
    return data.get("markets", [])


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
            "params": {"channels": ["ticker"], "market_tickers": tickers},
        }
        self._msg_id += 1
        await self._ws.send(json.dumps(payload))

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
                json.dumps(m),
            ),
        )


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

    with conn.cursor() as cur:
        current_event = None
        print("Forward collector started immediately (no initial 15m wait).")
        print("Writing 20-second aligned snapshots (:00/:20/:40) into forward_quotes.")

        while True:
            tick = next_20s_mark()
            sleep_s = max(0.0, (tick - utc_now()).total_seconds())
            time.sleep(sleep_s)

            try:
                markets = fetch_active_kxbtc15m_markets()
            except Exception as e:
                insert_na_snapshot(cur, tick, "MARKETS_API_ERROR")
                print(f"N/A snapshot at={tick.isoformat()} reason=MARKETS_API_ERROR err={e}")
                continue

            if markets:
                insert_market_upserts(cur, markets)
            else:
                insert_na_snapshot(cur, tick, "NO_OPEN_KXBTC15M_MARKET")
                print(f"N/A snapshot at={tick.isoformat()} reason=NO_OPEN_KXBTC15M_MARKET")
                continue

            if current_event is None or not any(m.get("event_ticker") == current_event for m in markets):
                current_event = choose_active_event(markets)
                print(f"Active event -> {current_event}")

            if current_event:
                event_markets = [m for m in markets if m.get("event_ticker") == current_event]
                if not event_markets:
                    insert_na_snapshot(cur, tick, "NO_EVENT_MARKETS", current_event)
                    print(f"N/A snapshot at={tick.isoformat()} reason=NO_EVENT_MARKETS event={current_event}")
                    continue

                ticker_to_event = {m.get("ticker"): m.get("event_ticker") for m in event_markets if m.get("ticker")}
                if ws_feed.enabled:
                    ws_feed.request_subscribe(list(ticker_to_event.keys()), ticker_to_event)

                n = insert_snapshot_rows(cur, event_markets, current_event, tick, ws_feed if ws_feed.enabled else None)
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
                                "event_ticker": current_event,
                                "rows": n,
                                "snapshot_time_utc": tick.isoformat(),
                                "mode": "websocket" if ws_feed.enabled else "rest",
                            }
                        ),
                        utc_now().replace(tzinfo=None),
                    ),
                )
                print(f"snapshot event={current_event} rows={n} at={tick.isoformat()}")
            else:
                insert_na_snapshot(cur, tick, "NO_ACTIVE_EVENT")
                print(f"N/A snapshot at={tick.isoformat()} reason=NO_ACTIVE_EVENT")


def main() -> None:
    while True:
        try:
            loop_forever()
        except Exception as e:
            print(f"[ERROR] forward collector crashed: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
