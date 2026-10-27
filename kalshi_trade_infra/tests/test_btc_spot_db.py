"""A Bitcoin market page's stored spot and strike, on a real MySQL: latest_spot returns the newest good
Coinbase snapshot inside its lookback (skipping failed snapshots and other products) over
idx_coinbase_product_time, and market_strike reads the collector's strike fields from markets.raw_json.
Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1)."""
import json
import os
import uuid
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


def _tick(cur, product, at, price, status="ok"):
    cur.execute("INSERT INTO coinbase_ticks (snapshot_time_utc, product_id, price, status, raw_json) VALUES (%s,%s,%s,%s,%s)",
                (at, product, price, status, json.dumps({"price": price})))


def test_latest_spot_is_the_newest_good_snapshot_inside_the_lookback(conn):
    from app import repository as repo

    cur = conn.cursor()
    product = "T" + uuid.uuid4().hex[:10].upper()  # a product of its own, so other rows never answer
    base = datetime(2031, 1, 2, 3, 0, 0)
    _tick(cur, product, base, 100000.5)
    _tick(cur, product, base + timedelta(seconds=20), 100020.25)
    _tick(cur, product, base + timedelta(seconds=40), None, "api_error")  # the newest row failed
    _tick(cur, "X" + product[1:], base + timedelta(seconds=60), 5.0)       # another product
    assert repo.latest_spot(cur, product, base - timedelta(days=1)) == {"at": base + timedelta(seconds=20), "price": 100020.25}
    assert repo.latest_spot(cur, product, base + timedelta(seconds=21)) is None, "nothing good since the lookback"

    cur.execute("EXPLAIN SELECT snapshot_time_utc, price FROM coinbase_ticks WHERE product_id=%s AND snapshot_time_utc>=%s "
                "AND status='ok' AND price IS NOT NULL ORDER BY snapshot_time_utc DESC LIMIT 1", (product, base))
    plan = cur.fetchone()
    # Either time-ordered index reads backwards from the newest row and stops at the first good one (in
    # production every row is BTC-USD, so the two are equally selective); never a scan and a sort.
    assert plan["key"] in ("idx_coinbase_product_time", "idx_coinbase_ticks_time"), plan
    assert "filesort" not in (plan.get("Extra") or "").lower(), plan


def test_market_strike_reads_the_collectors_record(conn):
    from app import repository as repo

    cur = conn.cursor()
    ticker = "KXBTC-%s-B113250" % uuid.uuid4().hex[:8].upper()
    close = datetime(2031, 1, 2, 22, 0, 0)
    cur.execute("INSERT INTO markets (ticker, series_ticker, close_time, last_seen_utc, raw_json) VALUES (%s,%s,%s,%s,%s)",
                (ticker, "KXBTC", close, close, json.dumps({"floor_strike": 113000, "cap_strike": 113499.99, "strike_type": "between"})))
    assert repo.market_strike(cur, ticker) == {"floor_strike": 113000, "cap_strike": 113499.99, "strike_type": "between", "close_time": close}
    assert repo.market_strike(cur, ticker + "X") is None
