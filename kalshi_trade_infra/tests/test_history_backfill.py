"""market_history fills the OLD end of a market's history when history_days reaches further back
than what was collected (raised from 30 to 90 days for the 15m crypto ladders)."""
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import market_history as mh
from app.markets import MARKETS

NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)


class _Cur:
    def __init__(self, one=None, rows=None):
        self.one, self.rows, self.sql = one, rows or [], []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows


def test_settled_markets_gap_at_the_old_end_is_backfilled(monkeypatch):
    calls = []
    monkeypatch.setattr(mh, "sync_settled_markets",
                        lambda cur, market, since, max_close=None: calls.append((since, max_close)) or 7)
    first = (NOW - timedelta(days=41)).replace(tzinfo=None)
    market = MARKETS["btc15m"]
    assert mh.backfill_settled_markets(_Cur({"t": first}), market, NOW) == 7
    since, max_close = calls[0]
    assert since == NOW - timedelta(days=market.history_days)
    assert max_close == first.replace(tzinfo=timezone.utc)


def test_no_backfill_when_collection_already_reaches_the_floor(monkeypatch):
    monkeypatch.setattr(mh, "sync_settled_markets", lambda *a, **k: pytest.fail("no gap, no call"))
    market = MARKETS["btc15m"]
    first = (NOW - timedelta(days=market.history_days) + timedelta(hours=2)).replace(tzinfo=None)
    assert mh.backfill_settled_markets(_Cur({"t": first}), market, NOW) == 0
    assert mh.backfill_settled_markets(_Cur({"t": None}), market, NOW) == 0


def test_spot_backfill_takes_a_bounded_slice_ending_at_the_oldest_candle(monkeypatch):
    seen = []
    monkeypatch.setattr(mh, "sync_spot_candles", lambda cur, sym, a, b: seen.append((sym, a, b)) or 1)
    first = int((NOW - timedelta(days=40)).timestamp())
    assert mh.backfill_spot(_Cur({"t": first}), "BTC-USD", 90, NOW) == 1
    sym, a, b = seen[0]
    assert sym == "BTC-USD" and b == first and b - a == mh.SPOT_BACKFILL_SECONDS_PER_PASS


def _pending(close_dt):
    return {"ticker": "KXBTC15M-OLD", "strike": 100.0, "open_time": (close_dt - timedelta(minutes=15)).replace(tzinfo=None),
            "close_time": close_dt.replace(tzinfo=None)}


def _api_404(path, params=None):
    raise RuntimeError("GET https://x%s failed 404: not found" % path)


def test_an_old_market_kalshi_no_longer_serves_is_written_off_not_blocking(monkeypatch):
    monkeypatch.setattr(mh, "api_get", _api_404)
    monkeypatch.setattr(mh.time, "sleep", lambda s: None)
    old = datetime.fromtimestamp(time.time() - 60 * 86400, tz=timezone.utc)
    cur = _Cur(rows=[_pending(old)])
    assert mh.sync_market_candles(cur, MARKETS["btc15m"]) == 0
    assert any("candles_done=3" in sql for sql, _ in cur.sql)


def test_a_recent_market_client_error_still_raises(monkeypatch):
    monkeypatch.setattr(mh, "api_get", _api_404)
    recent = datetime.fromtimestamp(time.time() - 3600, tz=timezone.utc)
    with pytest.raises(RuntimeError):
        mh.sync_market_candles(_Cur(rows=[_pending(recent)]), MARKETS["btc15m"])
