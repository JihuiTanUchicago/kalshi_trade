"""Market-making policies: validation, config mapping and hour-clustered scoring."""
import pytest

from trading_core.engine import maker_policy as mr


def test_policy_validation_fills_defaults_and_names_every_problem():
    p = mr.validate_policy({"series": "KXBTC15M", "min_edge": 0.02, "back_off": True, "fair_source": "spot",
                            "mid_band": [0.1, 0.9]})
    assert p["quote_size"] == 100.0 and p["rewarded_only"] is False and p["mid_band"] == [0.1, 0.9]
    cfg = mr.to_config(p)
    assert cfg.min_edge == 0.02 and cfg.back_off and cfg.mid_band == (0.1, 0.9)
    with pytest.raises(mr.PolicyError) as e:
        mr.validate_policy({"series": "KXETH", "quote_size": 0, "fair_source": "oracle", "leverage": 3,
                            "mid_band": [0.9, 0.1], "back_off": "yes"})
    msg = str(e.value)
    for bit in ("series", "quote_size", "fair_source", "leverage", "mid_band", "back_off"):
        assert bit in msg


def _row(m60, reward, fills=10, qty=1000.0):
    return {"hour": 0, "fills": fills, "qty": qty, "reward": reward, "m10": 0.0, "m60": m60, "fees": 0.0}


def test_hour_stats_treat_the_hour_as_the_unit_and_price_the_break_even_pool():
    rows = [_row(-10.0, 0.5), _row(-30.0, 0.5), _row(0.0, 0.0, fills=0, qty=0.0)]   # an idle hour is left out
    s = mr.hour_stats(rows, pool=0.0)
    assert s["hours"] == 2 and s["mean"] == -20.0 and s["se"] == pytest.approx(10.0) and s["t"] == -2.0
    assert s["markout_per_contract"] == -0.02 and s["breakeven_pool"] == 40.0
    paid = mr.hour_stats(rows, pool=60.0)                                # 60 * 0.5 = +30 an hour
    assert paid["mean"] == 10.0 and paid["t"] == 1.0
    assert mr.hour_stats([], pool=10.0)["mean"] is None


def test_baselines_are_valid_policies_on_every_series():
    for s in mr.MAKER_SERIES:
        for name, b in mr.BASELINES.items():
            mr.to_config(mr.validate_policy(dict(b, series=s)))
