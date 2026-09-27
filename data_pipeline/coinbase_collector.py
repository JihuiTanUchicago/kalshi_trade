import json
import time
from datetime import datetime, timedelta

import requests

from data_pipeline.common import next_20s_mark, get_db_conn, utc_now

PRODUCT_ID = "BTC-USD"
TICKER_URL = f"https://api.exchange.coinbase.com/products/{PRODUCT_ID}/ticker"


def fetch_ticker() -> dict:
    r = requests.get(TICKER_URL, timeout=10)
    if r.status_code >= 400:
        raise RuntimeError(f"coinbase ticker {r.status_code}: {r.text[:200]}")
    return r.json()


def insert_tick(cur, snapshot: datetime, payload: dict, status: str) -> None:
    cur.execute(
        """
        INSERT INTO coinbase_ticks
        (snapshot_time_utc,product_id,price,bid,ask,volume_24h,status,raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            snapshot.replace(tzinfo=None),
            PRODUCT_ID,
            payload.get("price"),
            payload.get("bid"),
            payload.get("ask"),
            payload.get("volume"),
            status,
            json.dumps(payload),
        ),
    )


def run_loop() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        print("Coinbase collector started. Writing 20-second aligned snapshots.")
        while True:
            tick = next_20s_mark(utc_now())
            time.sleep(max(0.0, (tick - utc_now()).total_seconds()))
            try:
                payload = fetch_ticker()
                insert_tick(cur, tick, payload, "ok")
                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES (%s,%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    (
                        "coinbase_collector_last_snapshot",
                        json.dumps({"snapshot_time_utc": tick.isoformat(), "product_id": PRODUCT_ID}),
                        utc_now().replace(tzinfo=None),
                    ),
                )
                print(f"coinbase snapshot at={tick.isoformat()} price={payload.get('price')}")
            except Exception as e:
                insert_tick(cur, tick, {"error": str(e)}, "api_error")
                print(f"coinbase N/A snapshot at={tick.isoformat()} err={e}")


if __name__ == "__main__":
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f"[ERROR] coinbase collector crashed: {e}")
            time.sleep(5)
