import json
import pymysql
import pytest

from data_pipeline import forward_collector


class _RaiseCursor:
    """A cursor whose execute always raises a given OperationalError errno."""

    def __init__(self, errno: int):
        self.errno = errno

    def execute(self, *a, **k):
        raise pymysql.err.OperationalError(self.errno, "boom")


def test_upsert_catalog_skips_on_lock_wait_timeout():
    # A stuck txn elsewhere -> lock wait timeout (1205). Catalog is skipped, feed survives.
    assert forward_collector.upsert_catalog(_RaiseCursor(1205), [{"ticker": "X"}]) is False


def test_upsert_catalog_skips_on_deadlock():
    assert forward_collector.upsert_catalog(_RaiseCursor(1213), [{"ticker": "X"}]) is False


def test_upsert_catalog_reraises_connection_loss():
    # A dropped connection (2013) must NOT be swallowed — the caller reconnects.
    with pytest.raises(pymysql.err.OperationalError):
        forward_collector.upsert_catalog(_RaiseCursor(2013), [{"ticker": "X"}])


# -- trade prints -> market_trades ---------------------------------------------


class _RecCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))


def test_trade_row_from_a_ws_trade_message():
    msg = {"trade_id": "t-1", "market_ticker": "KXBTC15M-X-1", "yes_price_dollars": "0.360",
           "no_price_dollars": "0.640", "count_fp": "136.00", "taker_side": "no", "ts": 1669149841}
    row = forward_collector.trade_row(msg)
    trade_id, ticker, created, yes, no, count, taker = row[:7]
    assert (trade_id, ticker, taker) == ("t-1", "KXBTC15M-X-1", "no")
    assert (yes, no, count) == (0.36, 0.64, 136.0)
    assert created.isoformat() == "2022-11-22T20:44:01" and created.tzinfo is None


def test_trade_row_raw_json_keeps_only_fields_without_a_column():
    msg = {"trade_id": "t-9", "market_ticker": "K", "yes_price_dollars": "0.2", "no_price_dollars": "0.8",
           "count_fp": "12.00", "taker_side": "yes", "ts": 1792969888, "ts_ms": 1792969888116,
           "taker_outcome_side": "yes", "taker_book_side": "bid", "is_block_trade": False}
    raw = json.loads(forward_collector.trade_row(msg)[-1])
    assert raw == {"ts_ms": 1792969888116, "taker_outcome_side": "yes", "taker_book_side": "bid",
                   "is_block_trade": False}


def test_trade_row_falls_back_to_cents_and_integer_count():
    row = forward_collector.trade_row({"trade_id": "t-2", "market_ticker": "K", "yes_price": 36,
                                       "no_price": 64, "count": 5, "taker_side": "yes", "ts": 1669149841})
    assert row[3:6] == (0.36, 0.64, 5.0)


def test_trade_row_rejects_unusable_messages():
    assert forward_collector.trade_row({"market_ticker": "K"}) is None
    assert forward_collector.trade_row({"trade_id": "t", "market_ticker": "K", "ts": "not-a-ts"}) is None


def test_insert_trade_row_is_idempotent_sql():
    cur = _RecCursor()
    row = forward_collector.trade_row({"trade_id": "t-3", "market_ticker": "K", "yes_price_dollars": "0.5",
                                       "no_price_dollars": "0.5", "count_fp": "1", "ts": 1669149841})
    forward_collector.insert_trade_row(cur, row)
    sql, params = cur.calls[0]
    assert "INSERT IGNORE INTO market_trades" in sql and params == row


def test_ws_feed_records_trades_and_never_raises():
    feed = forward_collector.WsTickerFeed.__new__(forward_collector.WsTickerFeed)
    feed._db_conn, feed._db_cur = object(), _RecCursor()
    feed._record_trade({"trade_id": "t-4", "market_ticker": "K", "yes_price_dollars": "0.2",
                        "no_price_dollars": "0.8", "count_fp": "3", "ts": 1669149841})
    assert len(feed._db_cur.calls) == 1
    feed._db_cur = _RaiseCursor(1205)
    feed._record_trade({"trade_id": "t-5", "market_ticker": "K", "ts": 1669149841})  # swallowed, logged
