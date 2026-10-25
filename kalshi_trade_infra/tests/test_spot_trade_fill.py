"""Live spot stays current when Coinbase's candles endpoint lags (it publishes in ~5-minute batches,
measured 2026-10-25): missing minutes are rebuilt from public trades, so the engine stops skipping
ticks the backtest takes on its complete candle history."""
from datetime import datetime, timezone

from app import engine
from app.markets import MAX_BTC_GAP_SECONDS

T0 = 1_790_000_040 - 1_790_000_040 % 60   # a minute boundary


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _trade(ts, px, tid):
    return {"time": _iso(ts), "price": str(px), "size": "0.01", "trade_id": tid, "side": "buy"}


class _Resp:
    def __init__(self, data, headers=None):
        self._data, self.headers = data, headers or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _candles(newest, n=90, px=100.0):
    # newest first, like Coinbase: [start, low, high, open, close, volume]
    return [[newest - 60 * i, 0, 0, 0, px, 1] for i in range(n)]


def test_trade_closes_takes_last_trade_per_closed_minute():
    trades = [_trade(T0 + 5, 101, 1), _trade(T0 + 50, 102, 2), _trade(T0 + 50, 103, 3),
              _trade(T0 + 70, 104, 4), _trade(T0 + 125, 105, 5)]
    out = engine.trade_closes(trades, after_ts=T0 - 60, now_ts=T0 + 130)
    # last trade of each minute wins (ties broken by trade_id); the open minute T0+120 is left out
    assert out == {T0: 103.0, T0 + 60: 104.0}


def test_trade_closes_refuses_a_hole():
    trades = [_trade(T0 + 200, 101, 1), _trade(T0 + 250, 102, 2)]
    # newest candle T0, so T0+60 is the first missing minute; trades only reach T0+180
    assert engine.trade_closes(trades, after_ts=T0, now_ts=T0 + 400) is None


def test_stale_candles_are_filled_and_features_are_fresh(monkeypatch):
    newest, now = T0, T0 + 60 + 270           # newest candle closed 270 s ago (> the 180 s cutoff)
    calls = []

    def get(url, params=None, timeout=None):
        calls.append((url, dict(params or {})))
        if url.endswith("/candles"):
            return _Resp(_candles(newest))
        return _Resp([_trade(T0 + 60 * k + 30, 110 + k, 10 + k) for k in range(1, 6)])
    monkeypatch.setattr(engine.requests, "get", get)
    assert engine.BtcSeries([(int(r[0]), float(r[4])) for r in _candles(newest)]).features_at(int(now)) is None
    s = engine.fetch_minute_series("BTC-USD", now=now)
    f = s.features_at(int(now))
    assert f is not None and f["spot"] == 114.0      # minute T0+240 closed at T0+300; T0+300 still open
    assert s.ts[-1] == T0 + 240 and now - (s.ts[-1] + 60) <= MAX_BTC_GAP_SECONDS
    assert [u.rsplit("/", 1)[1] for u, _ in calls] == ["candles", "trades"]


def test_trade_fill_pages_back_until_it_reaches_the_candles(monkeypatch):
    newest, now = T0, T0 + 400
    pages = {None: ([_trade(T0 + 300 + k, 120, 100 + k) for k in range(30)], {"cb-after": "100"}),
             "100": ([_trade(T0 + 70, 111, 50), _trade(T0 + 200, 113, 60)], {"cb-after": "50"})}
    seen = []

    def get(url, params=None, timeout=None):
        if url.endswith("/candles"):
            return _Resp(_candles(newest))
        seen.append((params or {}).get("after"))
        data, headers = pages[(params or {}).get("after")]
        return _Resp(data, headers)
    monkeypatch.setattr(engine.requests, "get", get)
    s = engine.fetch_minute_series("ETH-USD", now=now)
    assert seen == [None, "100"]
    assert dict(zip(s.ts, s.close))[T0 + 60] == 111.0 and dict(zip(s.ts, s.close))[T0 + 300] == 120.0
    assert T0 + 120 not in s.ts   # a minute with no trades has no candle either, same as Coinbase


def test_fresh_candles_skip_the_trades_call(monkeypatch):
    calls = []
    monkeypatch.setattr(engine.requests, "get",
                        lambda url, **k: calls.append(url) or _Resp(_candles(T0)))
    engine.fetch_minute_series("BTC-USD", now=T0 + 100)   # newest closed 40 s ago: nothing missing
    assert len(calls) == 1


def test_dead_feed_and_trade_errors_keep_the_candles(monkeypatch):
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/trades"):
            raise RuntimeError("boom")
        return _Resp(_candles(T0))
    monkeypatch.setattr(engine.requests, "get", get)
    s = engine.fetch_minute_series("BTC-USD", now=T0 + 300)        # trades fail: candles as they are
    assert s.ts[-1] == T0 and len(calls) == 2
    calls.clear()
    engine.fetch_minute_series("BTC-USD", now=T0 + 60 + engine.MAX_TRADE_FILL_S + 1)
    assert len(calls) == 1   # a feed stale for 15+ minutes is dead, not batching: no fill attempt


def test_spot_and_cross_feeds_share_the_fill(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "fetch_minute_series", lambda p, now=None: seen.append(p) or "S")
    monkeypatch.setattr(engine, "_cross_cache", {})
    assert engine.fetch_spot_series(engine.MARKETS["btc15m"]) == "S"
    assert engine.fetch_product_series("ETH-USD") == "S"
    assert seen == ["BTC-USD", "ETH-USD"]
