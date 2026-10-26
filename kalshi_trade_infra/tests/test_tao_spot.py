"""TAO (Bittensor subnet-token) research venue, Phase 1 (TAO_VENUE_DESIGN.md §A-C, §E).

Research-only, long-only: spot markets are deployable=False and route through backtest.simulate_spot
(a continuous-price simulator), never the binary engine. These tests cover the spot simulator's PnL
and pool-depth fill model, the simulate() kind routing, the gatekeeper's spot placebo, dual
TAO/USD denomination, and the tao_repository round-trip - all without a live DB.
"""
from datetime import datetime, timezone

import pytest

from app import backtest, sandbox
from app import gatekeeper as gk
from app import spec as specmod
from app.adapters.tao import tao_repository as taorepo
from app.backtest import Trade
from app.markets import MARKETS, TAO_USD_SYMBOL

needs_confiner = pytest.mark.skipif(not sandbox.os_sandbox_available(),
                                    reason="no OS-level sandbox (sandbox-exec/bwrap/firejail) here")

T0 = 1_800_000_000 - 1_800_000_000 % 3600
HOUR = 3600


def _spot_ds(prices, rate=10.0, alpha_pool=None, market="tao_sn64"):
    """A synthetic spot Dataset: hourly alpha-in-TAO candles, a (constant) TAO/USD rate, and an
    optional pool-depth feature on every frame."""
    candles = [(T0 + i * HOUR, float(p)) for i, p in enumerate(prices)]
    tao_usd = [(T0, float(rate))]
    feats = {ts: {"alpha_pool": float(alpha_pool)} for ts, _ in candles} if alpha_pool else {}
    return backtest.build_spot_dataset(MARKETS[market], candles, tao_usd, feats)


def _code_spec(code, stake=10.0, max_positions=1, market="tao_sn64"):
    return specmod.validate({"market": market, "code": code,
                             "sizing": {"stake": stake, "max_positions": max_positions}})


def _long_book(spec, ds, start_ts, end_ts):
    """Canned book: want LONG on every in-window frame (bypasses the sandbox for determinism).
    Signature matches backtest._spot_code_book(spec, ds, start_ts, end_ts)."""
    return {ts: ("long", 1.0) for ts, _fr in ds.frames if start_ts <= ts < end_ts}


LONG_ALWAYS = """
def signals(window):
    return [[{"side": "long", "score": 1.0}] for _ in window["frames"]]
"""
FLAT_ALWAYS = """
def signals(window):
    return [[] for _ in window["frames"]]
"""


# -- the TAO markets are research-only -----------------------------------------


def test_tao_markets_are_spot_and_not_deployable():
    tao = [m for m in MARKETS.values() if m.kind == "spot"]
    assert len(tao) >= 3
    for m in tao:
        assert m.deployable is False       # the live engine can never tick a TAO market
        assert m.underlying.startswith("TAO-SN")
        assert m.candle_minutes >= 1


# -- simulate_spot: PnL + pool-depth fills -------------------------------------


def test_profitable_long_makes_money(monkeypatch):
    ds = _spot_ds([100, 110, 120, 130])  # rising alpha price
    monkeypatch.setattr(backtest, "_spot_code_book", _long_book)
    trades = backtest.simulate(_code_spec(FLAT_ALWAYS), ds, ds.start_ts, ds.end_ts + 1)
    assert trades and sum(t.pnl for t in trades) > 0


def test_flat_signal_makes_nothing(monkeypatch):
    ds = _spot_ds([100, 110, 120, 130])
    monkeypatch.setattr(backtest, "_spot_code_book", lambda *a, **k: {})
    trades = backtest.simulate(_code_spec(FLAT_ALWAYS), ds, ds.start_ts, ds.end_ts + 1)
    assert trades == []


def test_falling_long_loses_money(monkeypatch):
    ds = _spot_ds([130, 120, 110, 100])
    monkeypatch.setattr(backtest, "_spot_code_book", _long_book)
    trades = backtest.simulate(_code_spec(FLAT_ALWAYS), ds, ds.start_ts, ds.end_ts + 1)
    assert trades and sum(t.pnl for t in trades) < 0


def test_pool_depth_fill_moves_price_against_size(monkeypatch):
    """A bigger position buys more alpha, moving the fill further above mid (price impact)."""
    monkeypatch.setattr(backtest, "_spot_code_book", _long_book)
    small = backtest.simulate(_code_spec(FLAT_ALWAYS, stake=10.0), _spot_ds([100, 100], alpha_pool=50.0),
                              T0, T0 + HOUR + 1)
    big = backtest.simulate(_code_spec(FLAT_ALWAYS, stake=400.0), _spot_ds([100, 100], alpha_pool=50.0),
                            T0, T0 + HOUR + 1)
    assert small and big
    assert big[0].entry_price > small[0].entry_price  # more size -> worse (higher) buy fill


def test_no_pool_depth_still_never_fills_at_mid(monkeypatch):
    monkeypatch.setattr(backtest, "_spot_code_book", _long_book)
    ds = _spot_ds([100, 100], rate=1.0)  # no alpha_pool feature -> conservative flat slippage
    trades = backtest.simulate(_code_spec(FLAT_ALWAYS), ds, T0, T0 + HOUR + 1)
    assert trades and trades[0].entry_price > 100.0  # bought above the $100 mid, not at it


# -- simulate() routes on market.kind ------------------------------------------


def test_simulate_routes_spot_to_simulate_spot(monkeypatch):
    called = {}

    def fake_spot(spec, ds, s, e, w=None):
        called["spot"] = True
        return ["SENTINEL"]

    monkeypatch.setattr(backtest, "simulate_spot", fake_spot)
    ds = _spot_ds([100, 110])
    out = backtest.simulate(_code_spec(FLAT_ALWAYS), ds, ds.start_ts, ds.end_ts + 1)
    assert out == ["SENTINEL"] and called.get("spot")


def test_simulate_binary_path_untouched(monkeypatch):
    """A binary market never reaches simulate_spot - the digital-option path is byte-unchanged."""
    def boom(*a, **k):
        raise AssertionError("binary simulate must not route to simulate_spot")

    monkeypatch.setattr(backtest, "simulate_spot", boom)
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(700)]
    markets, candles = [], []
    for k in range(40):
        o = T0 + k * 900
        close = datetime.fromtimestamp(o + 900, tz=timezone.utc)
        markets.append({"ticker": "M%d" % k, "strike": 98.0, "close_time": close, "result": "yes"})
        for mm in range(1, 16):
            candles.append({"ticker": "M%d" % k, "end_period_ts": o + mm * 60,
                            "yes_bid_close": 0.38, "yes_ask_close": 0.40})
    ds = backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)
    spec = specmod.validate({"market": "btc15m", "side": "yes", "entry": {"min_edge": 0.01}})
    backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1)  # must not raise


# -- dual TAO/USD denomination -------------------------------------------------


def test_window_alpha_usd_is_alpha_tao_times_rate():
    ds = _spot_ds([100, 120, 90], rate=7.5)
    for _ts, fr in ds.frames:
        assert fr["alpha_usd"] == pytest.approx(fr["alpha_tao"] * fr["tao_usd"])


def test_usd_and_tao_denominations_are_consistent(monkeypatch):
    """With a constant TAO/USD rate, USD per-unit trade prices are the TAO prices scaled by the
    rate (the two denominations describe the same position)."""
    monkeypatch.setattr(backtest, "_spot_code_book", _long_book)
    rate = 8.0
    ds = _spot_ds([100, 130], rate=rate)  # no pool feature -> identical flat slippage both runs
    usd = backtest.simulate_spot(_code_spec(FLAT_ALWAYS), ds, T0, T0 + HOUR + 1, denom="usd")
    tao = backtest.simulate_spot(_code_spec(FLAT_ALWAYS), ds, T0, T0 + HOUR + 1, denom="tao")
    assert usd and tao
    assert usd[0].entry_price == pytest.approx(tao[0].entry_price * rate)
    assert usd[0].exit_price == pytest.approx(tao[0].exit_price * rate)


# -- gatekeeper spot placebo ---------------------------------------------------


def _ret_trades(returns):
    """Trades whose per-trade net return (pnl/cost) equals each given value (qty=1, entry=$1)."""
    return [Trade("TAO", "long", 1, T0 + i * HOUR, 1.0, T0 + (i + 1) * HOUR, 1.0 + r, 0.0, "exit", 0.0)
            for i, r in enumerate(returns)]


def test_spot_placebo_small_p_on_strong_edge():
    p = gk._spot_placebo_pvalue(_ret_trades([0.1] * 12), seed=1)
    assert p < 0.05


def test_spot_placebo_mid_p_on_symmetric_null():
    p = gk._spot_placebo_pvalue(_ret_trades([0.1, -0.1] * 6), seed=1)
    assert 0.2 < p < 0.8


def test_spot_placebo_degenerate_returns_one():
    assert gk._spot_placebo_pvalue(_ret_trades([0.1]), seed=1) == 1.0


def test_compute_dispatches_spot_placebo():
    """_compute(kind='spot') runs the sign-flip placebo, not the binary label shuffle."""
    v = gk._compute(_ret_trades([0.05] * 40), n_trials=1, lord_state=gk.stats.lord_init(gk.ALPHA),
                    seed=7, kind="spot")
    assert 0.0 <= v["placebo_p"] <= 1.0 and v["n_trades"] == 40


# -- tao_repository round-trips ------------------------------------------------


def test_netuid_parsing():
    assert taorepo.netuid_of("TAO-SN64") == 64
    assert taorepo.netuid_of("TAO-SN8") == 8


def test_repository_candle_and_feature_round_trip(fake_cursor):
    taorepo.upsert_spot_candle(fake_cursor, "TAO-SN64", T0, 1.0, 1.2, 0.9, 1.1, 5.0)
    taorepo.upsert_spot_candle(fake_cursor, "TAO-SN64", T0 + HOUR, 1.1, 1.3, 1.0, 1.25, 6.0)
    taorepo.upsert_spot_candle(fake_cursor, TAO_USD_SYMBOL, T0, 400.0, 400.0, 400.0, 405.0, 0.0)
    taorepo.upsert_subnet_features(fake_cursor, 64, T0, emission_weight=0.03, tao_pool=1000.0,
                                   alpha_pool=5000.0, registrations=2, net_stake_flow=12.5, raw_json="{}")

    h = taorepo.load_spot_history(fake_cursor, MARKETS["tao_sn64"], T0 - 1)
    assert h["candles"] == [(T0, 1.1), (T0 + HOUR, 1.25)]
    assert h["tao_usd"] == [(T0, 405.0)]
    assert h["features"][T0]["alpha_pool"] == 5000.0
    assert h["features"][T0]["emission_weight"] == pytest.approx(0.03)


def test_repository_upsert_is_idempotent(fake_cursor):
    taorepo.upsert_spot_candle(fake_cursor, "TAO-SN64", T0, 1.0, 1.0, 1.0, 1.0, 1.0)
    taorepo.upsert_spot_candle(fake_cursor, "TAO-SN64", T0, 2.0, 2.0, 2.0, 2.0, 2.0)  # same PK -> overwrite
    assert taorepo.load_candles(fake_cursor, "TAO-SN64", 0) == [(T0, 2.0)]


def test_repository_since_filter(fake_cursor):
    taorepo.upsert_spot_candle(fake_cursor, "TAO-SN64", T0, 1.0, 1.0, 1.0, 1.0, 1.0)
    taorepo.upsert_spot_candle(fake_cursor, "TAO-SN64", T0 + HOUR, 1.1, 1.1, 1.1, 1.1, 1.1)
    assert taorepo.load_candles(fake_cursor, "TAO-SN64", T0 + 1) == [(T0 + HOUR, 1.1)]


# -- end-to-end through the real sandbox ---------------------------------------


@needs_confiner
def test_long_always_code_strategy_profits_through_sandbox():
    ds = _spot_ds([100, 110, 120, 130, 140])
    trades = backtest.simulate(_code_spec(LONG_ALWAYS), ds, ds.start_ts, ds.end_ts + 1)
    assert trades and sum(t.pnl for t in trades) > 0


@needs_confiner
def test_flat_code_strategy_makes_no_trades_through_sandbox():
    ds = _spot_ds([100, 110, 120])
    assert backtest.simulate(_code_spec(FLAT_ALWAYS), ds, ds.start_ts, ds.end_ts + 1) == []
