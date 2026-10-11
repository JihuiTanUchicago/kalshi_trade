"""Unit tests for the pure feature-vector formulas in modeling_features.py.
These are the ground truth for what every model (sim and live) actually sees,
so any drift here silently changes every prediction - worth pinning down."""
import math

from data_pipeline.modeling_features import FEATURE_COLS, build_feature_vector, coalesce_float, has_target


def _idx(name):
    return FEATURE_COLS.index(name)


def _base_row(**overrides):
    row = {
        "yes_bid_dollars": 0.40,
        "yes_ask_dollars": 0.42,
        "spread_dollars": 0.02,
        "mid_dollars": 0.41,
        "orderbook_imbalance": 0.1,
        "mid_ret_1m": 0.0,
        "mid_ret_3m": 0.0,
        "trades_last_60s_count": 5,
        "trades_last_60s_volume_fp": 10.0,
        "trades_last_60s_vwap_yes": 0.41,
        "quote_change_events_60s": 3,
        "time_to_expiry_sec": 300,
        "cb_price": 65000.0,
        "cb_ret_1m": 0.001,
        "cb_ret_3m": 0.002,
        "cb_ret_5m": 0.003,
        "cb_vol_5m": 0.01,
        "target_btc_price": 64500.0,
    }
    row.update(overrides)
    return row


def test_coalesce_float_treats_none_as_zero():
    assert coalesce_float(None) == 0.0
    assert coalesce_float("1.5") == 1.5
    assert coalesce_float(2) == 2.0


def test_has_target_requires_positive_value():
    assert has_target({"target_btc_price": 100.0}) is True
    assert has_target({"target_btc_price": 0.0}) is False
    assert has_target({"target_btc_price": None}) is False
    assert has_target({}) is False


def test_moneyness_abs_and_pct_match_documented_formula():
    row = _base_row(cb_price=65000.0, target_btc_price=64500.0)
    vec = build_feature_vector(row)
    # moneyness_abs = cb_price - target_btc_price
    assert vec[_idx("moneyness_abs")] == 500.0
    # moneyness_pct = moneyness_abs / target_btc_price
    assert vec[_idx("moneyness_pct")] == 500.0 / 64500.0


def test_moneyness_vol_scaled_matches_documented_formula():
    row = _base_row(cb_price=65000.0, target_btc_price=64500.0, cb_vol_5m=0.02)
    vec = build_feature_vector(row)
    expected_abs = 500.0
    expected_denom = max(65000.0 * max(0.02, 1e-6), 1e-6)
    assert vec[_idx("moneyness_vol_scaled")] == expected_abs / expected_denom


def test_moneyness_interaction_terms_match_documented_formulas():
    row = _base_row(
        cb_price=65000.0, target_btc_price=64500.0,
        time_to_expiry_sec=400, orderbook_imbalance=0.25, quote_change_events_60s=7,
    )
    vec = build_feature_vector(row)
    m_pct = 500.0 / 64500.0
    assert vec[_idx("moneyness_x_sqrt_tte")] == m_pct * math.sqrt(400)
    assert vec[_idx("moneyness_x_imbalance")] == m_pct * 0.25
    assert vec[_idx("moneyness_x_qchg")] == m_pct * 7


def test_moneyness_features_zero_when_target_missing():
    row = _base_row(target_btc_price=None)
    vec = build_feature_vector(row)
    for name in ("moneyness_abs", "moneyness_pct", "moneyness_vol_scaled", "moneyness_x_sqrt_tte", "moneyness_x_imbalance", "moneyness_x_qchg"):
        assert vec[_idx(name)] == 0.0


def test_time_to_expiry_floor_of_one_second_for_sqrt_tte():
    # time_to_expiry_sec <= 0 should floor to 1.0 inside the sqrt, not error
    # or go negative/NaN.
    row = _base_row(time_to_expiry_sec=-5, cb_price=65000.0, target_btc_price=64500.0)
    vec = build_feature_vector(row)
    m_pct = 500.0 / 64500.0
    assert vec[_idx("moneyness_x_sqrt_tte")] == m_pct * math.sqrt(1.0)


def test_missing_optional_fields_coalesce_to_zero_not_error():
    row = {"target_btc_price": 100.0, "cb_price": 100.0}
    vec = build_feature_vector(row)
    assert len(vec) == len(FEATURE_COLS)
    assert vec[_idx("yes_bid_dollars")] == 0.0
    assert vec[_idx("orderbook_imbalance")] == 0.0
