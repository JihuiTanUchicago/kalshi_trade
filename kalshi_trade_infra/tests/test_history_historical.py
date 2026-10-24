"""market_history reaches past Kalshi's live retention through /historical/*, normalises the
historical candle fields, and keeps each pass inside the watchdog's budget."""
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import market_history as mh
from app.markets import CURATED, MARKETS, Market

CUTOFF = datetime(2026, 8, 25, tzinfo=timezone.utc)


class _Cur:
    def __init__(self, rows=None):
        self.rows, self.sql, self.many = rows or [], [], []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def executemany(self, sql, rows):
        self.many.append((sql, list(rows)))

    def fetchone(self):
        return None

    def fetchall(self):
        return self.rows


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    mh._cutoff_cache.clear()
    mh._last_settled.clear()
    monkeypatch.setattr(mh.time, "sleep", lambda s: None)
    yield
    mh._cutoff_cache.clear()
    mh._last_settled.clear()


def _mkt(ticker, close):
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "floor_strike": 61, "result": "no",
            "open_time": (close - timedelta(days=1)).isoformat(), "close_time": close.isoformat(),
            "expiration_value": "63.00"}


def test_settled_sync_pages_historical_before_the_cutoff_then_live(monkeypatch):
    calls = []

    def api(path, params=None):
        calls.append((path, dict(params or {})))
        if path == "/historical/cutoff":
            return {"market_settled_ts": "2026-08-25T00:00:00Z"}
        if path == "/historical/markets":
            if "cursor" not in params:
                return {"markets": [_mkt("KXHIGHNY-26MAR10-B61.5", CUTOFF - timedelta(days=200))], "cursor": "c2"}
            return {"markets": [_mkt("KXHIGHNY-26MAR11-B61.5", CUTOFF - timedelta(days=199))], "cursor": ""}
        return {"markets": [_mkt("KXHIGHNY-26OCT20-B61.5", CUTOFF + timedelta(days=56))]}

    monkeypatch.setattr(mh, "api_get", api)
    cur = _Cur()
    n = mh.sync_settled_markets(cur, MARKETS["high_ny"], CUTOFF - timedelta(days=365))
    assert n == 3
    hist = [p for path, p in calls if path == "/historical/markets"]
    assert len(hist) == 2 and hist[0]["max_close_ts"] == int(CUTOFF.timestamp())
    assert hist[1]["cursor"] == "c2"
    live = [p for path, p in calls if path == "/markets"]
    assert live and live[0]["status"] == "settled"
    assert all(r[1] == "KXHIGHNY" for _sql, rows in cur.many for r in rows)  # historical rows carry no series


def test_no_historical_call_when_the_window_is_after_the_cutoff(monkeypatch):
    paths = []
    monkeypatch.setattr(mh, "api_get", lambda path, params=None: paths.append(path) or (
        {"market_settled_ts": "2026-08-25T00:00:00Z"} if path == "/historical/cutoff" else {"markets": []}))
    mh.sync_settled_markets(_Cur(), MARKETS["high_ny"], CUTOFF + timedelta(days=10))
    assert "/historical/markets" not in paths and "/markets" in paths


def test_cutoff_failure_falls_back_to_live_only(monkeypatch):
    def api(path, params=None):
        if path == "/historical/cutoff":
            raise RuntimeError("GET x failed 503")
        assert path == "/markets"
        return {"markets": []}

    monkeypatch.setattr(mh, "api_get", api)
    assert mh.sync_settled_markets(_Cur(), MARKETS["high_ny"], CUTOFF - timedelta(days=365)) == 0


HIST_CANDLE = {"end_period_ts": 1773086400, "open_interest": "201.00", "volume": "26.00",
               "price": {"close": "0.2400", "high": "0.2600", "low": "0.2400", "open": "0.2600"},
               "yes_ask": {"close": "0.2400", "high": "0.2700", "low": "0.2400", "open": "0.2600"},
               "yes_bid": {"close": "0.2200", "high": "0.2600", "low": "0.2200", "open": "0.2200"}}


def test_old_market_candles_come_from_historical_with_normalised_fields(monkeypatch):
    paths = []

    def api(path, params=None):
        paths.append(path)
        if path == "/historical/cutoff":
            return {"market_settled_ts": "2026-08-25T00:00:00Z"}
        return {"candlesticks": [HIST_CANDLE]}

    monkeypatch.setattr(mh, "api_get", api)
    close = CUTOFF - timedelta(days=100)
    cur = _Cur(rows=[{"ticker": "KXHIGHNY-26MAR10-B61.5", "strike": 61.0,
                      "open_time": (close - timedelta(days=1)).replace(tzinfo=None), "close_time": close.replace(tzinfo=None)}])
    assert mh.sync_market_candles(cur, MARKETS["high_ny"]) == 1
    assert "/historical/markets/KXHIGHNY-26MAR10-B61.5/candlesticks" in paths
    row = cur.many[0][1][0]
    assert row[3:11] == (0.22, 0.22, 0.26, 0.24, 0.26, 0.24, 26.0, 201.0)
    assert '"bl":"0.2200"' in row[12] and '"ah":"0.2700"' in row[12]


def test_candles_stop_at_the_deadline(monkeypatch):
    monkeypatch.setattr(mh, "api_get", lambda *a, **k: pytest.fail("past the deadline, no fetch"))
    close = datetime.now(timezone.utc) - timedelta(days=1)
    cur = _Cur(rows=[{"ticker": "T", "strike": 0.0, "open_time": (close - timedelta(hours=1)).replace(tzinfo=None),
                      "close_time": close.replace(tzinfo=None)}])
    mh._cutoff_cache.update(at=time.time(), ts=CUTOFF)
    assert mh.sync_market_candles(cur, MARKETS["high_ny"], deadline=time.time() - 1) == 0


def _cat(key):
    return Market(key, key.upper(), key, candle_minutes=60, history_days=30, underlying=None, deployable=True)


def test_pass_budget_runs_curated_first_and_rotates_the_rest(monkeypatch):
    seen = []
    clock = {"left": 0}

    def fake(cur, market, deadline=None):
        seen.append(market.key)
        clock["left"] -= 1

    monkeypatch.setattr(mh, "sync_market_candles", fake)
    settled = []
    monkeypatch.setattr(mh, "_sync_settled", lambda cur, market, now, stats: settled.append(market.key))
    monkeypatch.setattr(mh.time, "time", lambda: 100.0 if clock["left"] > 0 else 200.0)
    mh._candle_rotation = 0
    curated = [MARKETS["high_ny"]]
    rest = [_cat("a"), _cat("b"), _cat("c")]
    clock["left"] = 2  # curated + "a" fit, then the budget is gone
    assert mh.sync_all_markets(_Cur(), curated + rest, None, 150.0, {}) == 2
    assert seen == ["high_ny", "a"]
    assert settled == ["high_ny", "a"]  # the settled-market sync is inside the budget too
    seen.clear()
    clock["left"] = 2
    mh.sync_all_markets(_Cur(), curated + rest, None, 150.0, {})
    assert seen == ["high_ny", "b"]  # resumes after "a", curated still first
    assert "high_ny" in CURATED


def test_historical_rows_outside_the_window_are_dropped_and_paging_stops(monkeypatch):
    calls = []

    def api(path, params=None):
        calls.append(path)
        if path == "/historical/cutoff":
            return {"market_settled_ts": "2026-08-25T00:00:00Z"}
        if path == "/historical/markets":  # ignores min_close_ts: newest first, straight past the floor
            return {"markets": [_mkt("KXHIGHNY-IN", CUTOFF - timedelta(days=10)),
                                _mkt("KXHIGHNY-OLD", CUTOFF - timedelta(days=900))], "cursor": "more"}
        return {"markets": []}

    monkeypatch.setattr(mh, "api_get", api)
    cur = _Cur()
    assert mh.sync_settled_markets(cur, MARKETS["high_ny"], CUTOFF - timedelta(days=100)) == 1
    assert [r[0] for _sql, rows in cur.many for r in rows] == ["KXHIGHNY-IN"]
    assert calls.count("/historical/markets") == 1  # did not follow the cursor into older pages


def test_pending_candles_are_limited_to_the_history_window():
    cur = _Cur()
    mh._cutoff_cache.update(at=time.time(), ts=CUTOFF)
    mh.sync_market_candles(cur, MARKETS["high_ny"])
    sql, params = cur.sql[0]
    assert "close_time >= %s" in sql
    floor = params[1]
    expect = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=MARKETS["high_ny"].history_days)
    assert abs((floor - expect).total_seconds()) < 60


def test_each_market_gets_a_bounded_slice_of_the_pass(monkeypatch):
    got = []
    monkeypatch.setattr(mh, "sync_market_candles", lambda cur, market, deadline=None: got.append(deadline))
    monkeypatch.setattr(mh, "_sync_settled", lambda cur, market, now, stats: None)
    monkeypatch.setattr(mh, "MARKET_SLICE_SECONDS", 20)
    monkeypatch.setattr(mh.time, "time", lambda: 1000.0)
    mh._candle_rotation = 0
    assert mh.sync_all_markets(_Cur(), [_cat("a"), _cat("b")], None, 1900.0, {}) == 0
    assert got == [1020.0, 1020.0]  # a slice each, not the whole 900s budget
    got.clear()
    mh.sync_all_markets(_Cur(), [_cat("a")], None, 1005.0, {})
    assert got == [1005.0]  # never past the pass deadline


def _series(key, series):
    return Market(key, series, key, candle_minutes=60, history_days=365, underlying=None, deployable=True)


def test_priority_weather_goes_right_after_curated_without_a_slice(monkeypatch):
    got = []
    monkeypatch.setattr(mh, "sync_market_candles", lambda cur, market, deadline=None: got.append((market.series, deadline)))
    monkeypatch.setattr(mh, "_sync_settled", lambda cur, market, now, stats: None)
    monkeypatch.setattr(mh, "MARKET_SLICE_SECONDS", 20)
    monkeypatch.setattr(mh, "PRIORITY_SERIES", ["KXHIGHCHI", "KXHIGHAUS"])
    monkeypatch.setattr(mh, "PRIORITY_PREFIXES", ("KXHIGH", "KXLOW"))
    monkeypatch.setattr(mh.time, "time", lambda: 1000.0)
    mh._candle_rotation = 0
    ms = [_series("nba", "KXNBAGAME"), _series("lowtbos", "KXLOWTBOS"), _series("aus", "KXHIGHAUS"),
          _series("chi", "KXHIGHCHI"), MARKETS["high_ny"]]
    mh.sync_all_markets(_Cur(), ms, None, 1900.0, {})
    assert [s for s, _ in got] == ["KXHIGHNY", "KXHIGHCHI", "KXHIGHAUS", "KXLOWTBOS", "KXNBAGAME"]
    assert [d for _, d in got] == [1900.0, 1900.0, 1900.0, 1900.0, 1020.0]


def test_catalog_settled_lists_refresh_at_most_hourly_curated_every_pass(monkeypatch):
    calls = []
    clock = {"t": 1000.0}
    monkeypatch.setattr(mh, "sync_market_candles", lambda cur, market, deadline=None: None)
    monkeypatch.setattr(mh, "_sync_settled", lambda cur, market, now, stats: calls.append(market.key))
    monkeypatch.setattr(mh, "SETTLED_MIN_INTERVAL_SECONDS", 3600)
    monkeypatch.setattr(mh.time, "time", lambda: clock["t"])
    ms = [MARKETS["high_ny"], _cat("a")]
    mh.sync_all_markets(_Cur(), ms, None, 9e9, {})
    clock["t"] += 600
    mh.sync_all_markets(_Cur(), ms, None, 9e9, {})
    assert calls == ["high_ny", "a", "high_ny"]
    clock["t"] += 3600
    mh.sync_all_markets(_Cur(), ms, None, 9e9, {})
    assert calls[-2:] == ["high_ny", "a"]


def test_rotation_starts_at_a_random_point_after_a_restart(monkeypatch):
    monkeypatch.setattr(mh, "sync_market_candles", lambda cur, market, deadline=None: None)
    monkeypatch.setattr(mh, "_sync_settled", lambda cur, market, now, stats: None)
    monkeypatch.setattr(mh.random, "randrange", lambda n: 2)
    mh._candle_rotation = None
    mh.sync_all_markets(_Cur(), [_cat("a"), _cat("b"), _cat("c")], None, 0.0, {})  # budget already gone
    assert mh._candle_rotation == 2
