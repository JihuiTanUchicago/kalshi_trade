import math
from datetime import datetime, timezone

import pytest

from app import spec as specmod
from app.markets import BtcSeries, Contract, snapshot
from data_pipeline.binary_theory import theoretical_p_yes


def test_defaults_fill_missing_fields():
    s = specmod.validate({"market": "btc_daily"})
    assert s["market"] == "btc_daily"
    assert s["sizing"]["max_positions"] == 1
    assert s["exit"]["take_profit"] is None


def test_every_problem_is_reported_not_clamped():
    with pytest.raises(specmod.SpecError) as e:
        specmod.validate({
            "market": "nasdaq", "side": "maybe", "bogus": 1,
            "entry": {"min_edge": 0.9, "filters": [{"feature": "astrology", "op": "==", "value": "x"}]},
        })
    msg = str(e.value)
    for needle in ("unknown field bogus", "market must be", "side must be", "entry.min_edge=0.9", "astrology", "op must be", "value must be"):
        assert needle in msg


def test_cross_field_rules():
    with pytest.raises(specmod.SpecError, match="min_price must be <="):
        specmod.validate({"entry": {"min_price": 0.8, "max_price": 0.2}})
    with pytest.raises(specmod.SpecError, match="min_tte_min must be <"):
        specmod.validate({"entry": {"min_tte_min": 10, "max_tte_min": 5}})


def test_bool_is_not_a_number():
    with pytest.raises(specmod.SpecError):
        specmod.validate({"sizing": {"stake": True}})


def _snap(spot=100.0, strike=100.0, tte_min=10.0, bid=0.45, ask=0.47, vol=0.001, ret5=0.0):
    ts = 1_800_000_000
    contract = Contract("T", strike, datetime.fromtimestamp(ts + tte_min * 60, tz=timezone.utc))
    feats = {"spot": spot, "ret_1m": 0.0, "ret_5m": ret5, "ret_15m": 0.0, "ret_60m": 0.0, "vol_15m": vol, "vol_60m": vol}
    return snapshot(feats, contract, ts, bid, ask)


def test_zero_drift_matches_house_binary_theory():
    snap = _snap(spot=101.0, strike=100.0, tte_min=7.0, vol=0.0015)
    s = specmod.validate({"model": {"vol_window": 60}})
    row = {"cb_price": 101.0, "target_btc_price": 100.0, "time_to_expiry_sec": 7 * 60, "cb_vol_5m": 0.0015}
    assert math.isclose(specmod.fair_yes(s, snap.features), theoretical_p_yes(row), rel_tol=1e-9)


def test_momentum_drift_moves_fair_value():
    up = _snap(ret5=0.002)
    flat = specmod.validate({})
    mom = specmod.validate({"model": {"drift_window": 5, "drift_beta": 1.0}})
    rev = specmod.validate({"model": {"drift_window": 5, "drift_beta": -1.0}})
    assert specmod.fair_yes(mom, up.features) > specmod.fair_yes(flat, up.features) > specmod.fair_yes(rev, up.features)


def test_entries_pick_the_side_with_edge_and_respect_bounds():
    # Spot well above strike: YES fair ~1, so a 60c ask is a big YES edge.
    snap = _snap(spot=102.0, strike=100.0, tte_min=5, bid=0.58, ask=0.60)
    s = specmod.validate({"entry": {"min_edge": 0.1, "max_price": 0.95}})
    [e] = specmod.entries(s, [snap])
    assert e.side == "yes" and e.price == 0.60 and e.edge > 0.3
    assert specmod.entries(specmod.validate({"side": "no"}), [snap]) == []
    assert specmod.entries(specmod.validate({"entry": {"max_price": 0.5}}), [snap]) == []
    assert specmod.entries(specmod.validate({"entry": {"max_tte_min": 3}}), [snap]) == []
    blocked = specmod.validate({"entry": {"filters": [{"feature": "spot", "op": "<", "value": 50}]}})
    assert specmod.entries(blocked, [snap]) == []


def test_no_side_prices_mirror_the_yes_book():
    snap = _snap(spot=98.0, strike=100.0, tte_min=5, bid=0.40, ask=0.42)
    [e] = specmod.entries(specmod.validate({"side": "no"}), [snap])
    assert e.side == "no" and math.isclose(e.price, 0.60)


def test_exit_signals():
    snap = _snap(bid=0.70, ask=0.72)
    tp = specmod.validate({"exit": {"take_profit": 0.2}})
    sl = specmod.validate({"exit": {"stop_loss": 0.2}})
    assert specmod.exit_signal(tp, "yes", 0.45, snap) == ("take_profit", 0.70)
    assert specmod.exit_signal(sl, "no", 0.55, snap) == ("stop_loss", pytest.approx(0.28))
    assert specmod.exit_signal(specmod.validate({}), "yes", 0.45, snap) is None
    no_bid = _snap(bid=0.0, ask=0.02)
    assert specmod.exit_signal(sl, "yes", 0.5, no_bid) is None  # nobody to sell to


def test_snapshot_rejects_untradable_books():
    assert _snap(bid=0.5, ask=0.5) is None
    assert _snap(bid=0.0, ask=1.0) is None
    assert _snap(tte_min=-1) is None


def test_btc_series_has_no_lookahead_and_goes_stale():
    t0 = 1_800_000_000 - 1_800_000_000 % 60
    candles = [(t0 + 60 * i, 100.0 + i) for i in range(120)]
    series = BtcSeries(candles)
    ts = t0 + 60 * 100  # the candle starting here has NOT closed yet
    f = series.features_at(ts)
    assert f["spot"] == 199.0  # close of the candle that started at t0+99m
    assert math.isclose(f["ret_1m"], math.log(199.0 / 198.0))
    assert series.features_at(t0 + 60 * 30) is None  # under 60 minutes of history
    assert series.features_at(t0 + 60 * 130) is None  # last candle is too old


def test_describe_reads_like_english():
    lines = specmod.describe(specmod.validate({"exit": {"take_profit": 0.2}}))
    assert any("takes profit at +20" in line for line in lines)
