"""markets.raw_json keeps only what is read back.

The full Kalshi payload (multivariate legs, custom_strike, rules text) averaged
3.5KB a row over ~1M new markets a day and is most of the RDS growth. The only
reader is the strike target in model_features_1m_builder.
"""
import json

from data_pipeline import forward_collector as fc
from data_pipeline.model_features_1m_builder import _target_from_market_raw

FULL = {
    "ticker": "KXBTCD-26OCT2417-T67999.99", "event_ticker": "KXBTCD-26OCT2417", "status": "active",
    "floor_strike": 67999.99, "strike_type": "greater", "market_type": "binary",
    "mve_selected_legs": [{"event_ticker": "X", "market_ticker": "Y", "side": "yes"}] * 20,
    "custom_strike": {"Team": "x" * 500}, "rules_primary": "r" * 800, "rules_secondary": "s" * 300,
}


class Cur:
    def __init__(self):
        self.params = []

    def execute(self, sql, params=()):
        self.params.append(params)


def test_stored_raw_json_is_slim_but_keeps_the_strike():
    cur = Cur()
    fc.insert_market_upserts(cur, [FULL])
    raw = json.loads(cur.params[0][-1])
    assert raw == {"floor_strike": 67999.99, "strike_type": "greater", "market_type": "binary", "status": "active"}
    assert len(cur.params[0][-1]) < 150
    assert _target_from_market_raw(raw) == 67999.99


def test_strike_price_markets_keep_their_target_too():
    raw = fc.slim_market_raw({"strike_price": 4200, "mve_selected_legs": [1, 2, 3]})
    assert _target_from_market_raw(raw) == 4200.0
