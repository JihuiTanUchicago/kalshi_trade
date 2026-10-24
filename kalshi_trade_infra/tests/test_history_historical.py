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
    monkeypatch.setattr(mh.time, "sleep", lambda s: None)
    yield
    mh._cutoff_cache.clear()


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
    monkeypatch.setattr(mh.time, "time", lambda: 100.0 if clock["left"] > 0 else 200.0)
    mh._candle_rotation = 0
    curated = [MARKETS["high_ny"]]
    rest = [_cat("a"), _cat("b"), _cat("c")]
    clock["left"] = 2  # curated + "a" fit, then the budget is gone
    assert mh.sync_all_candles(_Cur(), curated + rest, deadline=150.0) == 2
    assert seen == ["high_ny", "a"]
    seen.clear()
    clock["left"] = 2
    mh.sync_all_candles(_Cur(), curated + rest, deadline=150.0)
    assert seen == ["high_ny", "b"]  # resumes after "a", curated still first
    assert "high_ny" in CURATED
