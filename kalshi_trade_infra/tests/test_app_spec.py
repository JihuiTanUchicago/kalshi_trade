import math
from datetime import datetime, timezone

import pytest

from app.trading import spec as specmod
from app.trading.markets import BtcSeries, Contract, snapshot
from data_pipeline.binary_theory import theoretical_p_yes


def test_microstructure_features_are_filterable():
    # the collected order-book features are in the FEATURES namespace specs validate against
    s = specmod.validate({"entry": {"filters": [{"feature": "ob_imbalance", "op": ">", "value": 0.2}]}})
    assert s["entry"]["filters"][0]["feature"] == "ob_imbalance"


def test_features_used_records_model_and_filter_inputs():
    s = specmod.validate({"model": {"drift_window": 5, "drift_beta": 1.0},
                          "entry": {"filters": [{"feature": "ob_imbalance", "op": ">", "value": 0.2}]}})
    used = specmod.features_used(s)
    assert "ob_imbalance" in used          # the filter feature
    assert "ret_5m" in used                # the drift window it picked
    assert "spot" in used and "moneyness" in used  # always-on model inputs


def test_data_sources_flags_orderbook_table_only_when_used():
    plain = specmod.validate({"entry": {"min_edge": 0.1}})
    assert "model_features_1m" not in specmod.data_sources_for(plain)
    withob = specmod.validate({"entry": {"filters": [{"feature": "yes_bid_size", "op": ">", "value": 10}]}})
    assert "model_features_1m" in specmod.data_sources_for(withob)


def test_defaults_fill_missing_fields():
    s = specmod.validate({"market": "btc_daily"})
    assert s["market"] == "btc_daily"
    assert s["sizing"]["max_positions"] == 20 and s["sizing"]["stake"] == 5.0  # default $5 x 20 = $100 book
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


def test_describe_reads_an_old_or_partial_stored_spec_without_raising():
    # A seeded spec with no `model` 500ed the strategy page; a stored spec keeps the lines it can fill.
    seeded = {"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 4}}
    assert specmod.describe(seeded) == ["Buys YES contracts when its fair value beats the price by at least 5¢.",
                                        "Stakes $5 per trade, at most 4 open at once."]
    full = specmod.validate({"side": "no", "entry": {"filters": [{"feature": "z_score", "op": ">", "value": 1.0}]},
                             "exit": {"take_profit": 0.2, "stop_loss": 0.1},
                             "cross": {"pairing": "cross_strike", "legs": []}, "market": "btc_daily"})
    whole = specmod.describe(full)
    for key in full:
        for sub in [None] + (list(full[key]) if isinstance(full[key], dict) else []):
            for gone in (True, False):
                spec = {k: (dict(v) if isinstance(v, dict) else v) for k, v in full.items()}
                holder, k = (spec, key) if sub is None else (spec[key], sub)
                if gone:
                    del holder[k]
                else:
                    holder[k] = None
                lines = specmod.describe(spec)  # never raises
                # Nothing made up ("None", a default): every line is one the whole spec says, except the
                # exits line, which rightly reads differently with one exit gone.
                assert set(lines) <= set(whole) or key == "exit"
    assert specmod.describe(None) == [] and specmod.describe({}) == []


def test_cross_contract_spec_validates_and_keys_a_shared_stream():
    # single-contract: cross stays None, stream is just the market.
    single = specmod.validate({"market": "btc_daily"})
    assert single["cross"] is None
    assert specmod.stream_key(single) == "btc_daily" and not specmod.is_cross_contract(single)
    # cross_strike needs no extra market; cross_sectional needs a leg on a different market.
    x = specmod.validate({"market": "btc_daily", "cross": {"pairing": "cross_strike", "legs": []}})
    assert specmod.is_cross_contract(x) and specmod.stream_key(x) == "btc_daily"
    cs = specmod.validate({"market": "btc_daily",
                           "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]}})
    assert specmod.stream_key(cs) == "btc_daily+eth_daily"  # ONE shared stream across both legs


def test_learned_model_validates_unfitted_and_fitted():
    # logistic: unfitted (no coef) is valid — the research pipeline fits it later.
    u = specmod.validate({"model": {"kind": "logistic", "features": ["z_score", "ob_imbalance"]}})
    assert u["model"]["coef"] == [] and not specmod.is_fitted(u) and specmod.is_learned_model(u)
    assert specmod.n_free_params(u) == 3  # intercept + 2 weights -> 3 implicit trials
    # fitted: coef one-per-feature is valid and is_fitted.
    f = specmod.validate({"model": {"kind": "logistic", "features": ["z_score"], "coef": [2.0], "intercept": -0.5}})
    assert specmod.is_fitted(f)
    # calibration takes no features; it recalibrates the mid; 2 free params (slope + intercept).
    c = specmod.validate({"model": {"kind": "calibration"}})
    assert c["model"]["features"] == ["mid"] and specmod.n_free_params(c) == 2
    # gbm stays 1 trial and carries no learned fields (backward compatible default).
    g = specmod.validate({})
    assert g["model"]["kind"] == "gbm" and specmod.n_free_params(g) == 1 and specmod.is_fitted(g)


def test_learned_model_rejects_bad_shapes():
    with pytest.raises(specmod.SpecError, match="not a known feature"):
        specmod.validate({"model": {"kind": "logistic", "features": ["astrology"]}})
    with pytest.raises(specmod.SpecError, match="one value per feature"):
        specmod.validate({"model": {"kind": "logistic", "features": ["z_score"], "coef": [1.0, 2.0]}})
    with pytest.raises(specmod.SpecError, match="1..6 features"):
        specmod.validate({"model": {"kind": "logistic", "features": []}})
    with pytest.raises(specmod.SpecError, match="only apply to kind"):
        specmod.validate({"model": {"kind": "gbm", "features": ["z_score"]}})
    with pytest.raises(specmod.SpecError, match="finite number"):
        specmod.validate({"model": {"kind": "logistic", "features": ["z_score"], "coef": [1e99], "intercept": 0.0}})


def test_learned_fair_value_scores_features_and_is_none_when_unfitted():
    unfit = specmod.validate({"model": {"kind": "logistic", "features": ["z_score"]}})
    assert specmod.fair_yes(unfit, {"z_score": 1.0}) is None  # no signal until frozen
    fit = specmod.validate({"model": {"kind": "logistic", "features": ["z_score"], "coef": [2.0], "intercept": 0.0}})
    assert specmod.fair_yes(fit, {"z_score": 1.0}) > 0.5 > specmod.fair_yes(fit, {"z_score": -1.0})
    assert specmod.fair_yes(fit, {}) is None  # a missing feature is 'no signal', never a crash
    # calibration recalibrates the mid; slope 1, intercept 0 is the identity on the logit.
    cal = specmod.validate({"model": {"kind": "calibration", "coef": [1.0], "intercept": 0.0}})
    assert math.isclose(specmod.fair_yes(cal, {"mid": 0.3}), 0.3, abs_tol=1e-6)


def test_cross_contract_spec_rejects_bad_blocks():
    with pytest.raises(specmod.SpecError, match="cross.pairing"):
        specmod.validate({"cross": {"pairing": "bogus", "legs": []}})
    with pytest.raises(specmod.SpecError, match="different market"):
        specmod.validate({"market": "btc_daily", "cross": {"pairing": "cross_sectional", "legs": []}})
    with pytest.raises(specmod.SpecError, match="not a known market"):
        specmod.validate({"cross": {"pairing": "cross_strike", "legs": [{"market": "doge"}]}})


def test_entry_scan_agrees_with_entries_and_names_the_first_blocking_check():
    snap = _snap(spot=102.0, strike=100.0, tte_min=5, bid=0.58, ask=0.60)
    ok = specmod.validate({"entry": {"min_edge": 0.1, "max_price": 0.95}})
    scan = specmod.entry_scan(ok, [snap])
    assert scan["qualifying"] == len(specmod.entries(ok, [snap])) == 1 and scan["blocked_at"] is None
    late = specmod.validate({"entry": {"max_tte_min": 3}})
    scan = specmod.entry_scan(late, [snap, _snap(tte_min=8)])
    assert scan["blocked_at"] == "is 1-3 minutes from expiry" and scan["nearest"] == "closest is 5 minutes out"
    assert scan["why"] == "no open contract is 1-3 minutes from expiry (of 2; closest is 5 minutes out)"
    cheap = specmod.validate({"entry": {"min_price": 0.85, "max_price": 0.95}})
    scan = specmod.entry_scan(cheap, [snap])
    assert scan["blocked_at"] == "costs 85c to 95c" and scan["nearest"] == "nearest is 25c outside"
    flt = specmod.validate({"entry": {"filters": [{"feature": "ret_5m", "op": ">", "value": 0.01}]}})
    scan = specmod.entry_scan(flt, [_snap(ret5=0.002), _snap(ret5=0.004)])
    assert scan["blocked_at"] == "has the 5-minute return > 0.01" and scan["nearest"] == "closest is 0.004"
    assert [st["passed"] for st in scan["steps"]][:3] == [2, 2, 0]
    greedy = specmod.validate({"entry": {"min_edge": 0.5, "max_price": 0.95}})
    scan = specmod.entry_scan(greedy, [snap])
    assert scan["blocked_at"] == "offers 50c or more of edge after fees" and scan["nearest"].startswith("best is ")
    assert specmod.entries(greedy, [snap]) == []
    assert specmod.entry_scan(ok, [])["why"] == "no open contracts in the order book right now"


def test_plain_feature_names():
    assert specmod.plain_feature("ret_5m") == "the 5-minute return"
    assert specmod.plain_feature("vol_60m") == "the 60-minute volatility"
    assert specmod.plain_feature("z_score") == "the z-score" and specmod.plain_feature("ob_imbalance") == "ob_imbalance"


def test_scan_durations_read_in_hours_on_a_phone():
    assert specmod._duration(60) == "60 minutes" and specmod._duration(95) == "2 hours"
    assert specmod._duration(60 * 30) == "30 hours" and specmod._duration(60 * 72) == "3 days"
    assert specmod._window(300, 1200) == "5-20 hours" and specmod._window(1, 6) == "1-6 minutes"
