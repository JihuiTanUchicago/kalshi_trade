"""Cross-asset crypto features: alt-coin markets see BTC's returns and volatility, BTC markets see
ETH's returns, computed from the same one-minute closes and as-of rule in the backtest and live.
Crypto research kept dropping "BTC leads ETH/SOL/XRP" ideas as feature_unavailable (2026-10-24)."""
import math
from datetime import datetime, timezone

from app.trading import backtest, engine
from app.trading.markets import CROSS_FEATURES, MARKETS, BtcSeries, cross_feature_names, cross_product

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def _closes(n, step=0.001, start=T0 - 7200, spike_at=None):
    """BTC closes rising by `step` log per minute; a 10x spike in the candle starting at spike_at."""
    return [(start + 60 * i, 100.0 * math.exp(step * i) * (10.0 if start + 60 * i == spike_at else 1.0))
            for i in range(n)]


def _sol_dataset(cross, minutes=15, n_contracts=4):
    own = [(T0 - 7200 + 60 * i, 20.0) for i in range(n_contracts * minutes + 200)]
    markets, candles = [], []
    for k in range(n_contracts):
        open_ts = T0 + k * minutes * 60
        ticker = "SOL%d" % k
        markets.append({"ticker": ticker, "strike": 19.0, "result": "yes",
                        "close_time": datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)})
        for m in range(1, minutes + 1):
            candles.append((ticker, open_ts + m * 60, 0.40, 0.42))
    return backtest.build_dataset(MARKETS["sol15m"], markets, candles, own, cross=cross)


def test_each_crypto_market_gets_the_right_cross_coin():
    assert cross_product(MARKETS["btc15m"]) == "ETH-USD" and cross_product(MARKETS["btc_daily"]) == "ETH-USD"
    for key in ("eth15m", "eth_daily", "sol15m", "sol_daily", "xrp_daily", "doge15m", "near15m", "zec15m", "hype15m"):
        assert cross_product(MARKETS[key]) == "BTC-USD", key
    for key in ("nba_game", "high_ny", "btc15m_tick", "btc_perp", "tao_sn64"):
        assert cross_product(MARKETS[key]) is None and cross_feature_names(MARKETS[key]) == frozenset(), key
    assert cross_feature_names(MARKETS["sol15m"]) == {"btc_ret_1m", "btc_ret_5m", "btc_ret_15m", "btc_ret_60m", "btc_vol_60m"}
    assert cross_feature_names(MARKETS["btc15m"]) == {"eth_ret_5m", "eth_ret_15m", "eth_ret_60m"}
    assert set(CROSS_FEATURES) == cross_feature_names(MARKETS["sol15m"]) | cross_feature_names(MARKETS["btc15m"])


def test_alt_frames_carry_btc_returns_as_of_the_decision_with_no_lookahead():
    first_ts = T0 + 60
    # The candle STARTING at the decision ts closes after it: its 10x print must not leak in.
    ds = _sol_dataset(_closes(400, spike_at=first_ts))
    ts, snaps = ds.frames[0]
    assert ts == first_ts
    f = snaps[0].features
    assert math.isclose(f["btc_ret_1m"], 0.001, abs_tol=1e-12)
    assert math.isclose(f["btc_ret_5m"], 0.005, abs_tol=1e-12)
    assert math.isclose(f["btc_ret_60m"], 0.060, abs_tol=1e-12)
    assert math.isclose(f["btc_vol_60m"], 0.0, abs_tol=1e-9)  # constant drift: no dispersion
    assert f["spot"] == 20.0 and "eth_ret_5m" not in f  # its own spot is still SOL's
    later = dict(ds.frames)[first_ts + 60][0].features
    assert later["btc_ret_1m"] > 2.0  # one minute on, the spike candle has closed and shows


def test_a_stale_or_missing_cross_feed_keeps_the_frame_but_not_the_cross_features():
    stale = _closes(200, start=T0 - 20000)  # last close ~2h before the first decision
    for cross in (stale, None, []):
        ds = _sol_dataset(cross)
        assert ds.frames and not any(k in ds.frames[0][1][0].features for k in CROSS_FEATURES)


def test_live_engine_merges_the_same_values_the_backtest_saw():
    closes = _closes(400)
    ds = _sol_dataset(closes)
    ts, snaps = ds.frames[3]
    asked = []
    src = engine.Sources(cross_spot=lambda product: asked.append(product) or BtcSeries(closes))
    own = BtcSeries([(T0 - 7200 + 60 * i, 20.0) for i in range(260)]).features_at(ts)
    live = engine._with_cross(MARKETS["sol15m"], src, ts, own)
    assert asked == ["BTC-USD"]
    assert {k: live[k] for k in CROSS_FEATURES if k in live} == {k: snaps[0].features[k] for k in cross_feature_names(MARKETS["sol15m"])}
    # No cross source (tests' default), a fetch error, or a sports market: features unchanged.
    assert engine._with_cross(MARKETS["sol15m"], engine.Sources(), ts, own) == own

    def boom(product):
        raise RuntimeError("coinbase down")
    assert engine._with_cross(MARKETS["sol15m"], engine.Sources(cross_spot=boom), ts, own) == own
    assert engine._with_cross(MARKETS["nba_game"], src, ts, {}) == {}
    assert engine._with_cross(MARKETS["sol15m"], src, ts, None) is None


def test_product_series_fetch_is_shared_for_a_few_seconds(monkeypatch):
    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [[T0 - 60 * i, 0, 0, 0, 100.0, 0] for i in range(120)]
    monkeypatch.setattr(engine, "_cross_cache", {})
    monkeypatch.setattr(engine.requests, "get", lambda url, **k: calls.append(url) or Resp())
    a = engine.fetch_product_series("BTC-USD")
    b = engine.fetch_product_series("BTC-USD")
    assert a is b and len(calls) == 1 and "BTC-USD" in calls[0]
