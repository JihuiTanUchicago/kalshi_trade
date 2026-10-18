"""The feature builder now writes one model_features_1m row per active market per
minute (multi-series). These checks pin the safety-critical invariant: only the
PRIMARY (BTC) series is model_eligible and carries Coinbase cb_* features, while a
non-primary series still gets its order-flow features (so research is no longer null)
but is forced model_eligible=0 — the fence that keeps non-BTC rows out of the
eligible-gated live/sim readers."""
from datetime import datetime

from data_pipeline import model_features_1m_builder as b
from data_pipeline.common import is_primary_micro_ticker, micro_series


class StubCursor:
    """Answers only the exact query shapes build_row issues, by SQL substring."""

    def __init__(self):
        self.row = None

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        mk = datetime(2026, 1, 1, 12, 0, 0)
        if "FROM forward_quotes" in s:
            self.row = {
                "snapshot_time_utc": mk, "yes_bid_dollars": 0.50, "yes_ask_dollars": 0.52,
                "yes_bid_size_fp": 120.0, "yes_ask_size_fp": 80.0, "volume_fp": 10.0,
                "open_interest_fp": 5.0,
            }
        elif "FROM coinbase_ticks" in s:
            self.row = {"snapshot_time_utc": mk, "price": 92000.0}
        elif "raw_json" in s and "FROM markets" in s:
            self.row = {"close_time": datetime(2026, 1, 1, 12, 15, 0), "raw_json": {"floor_strike": 92000.0}}
        elif "FROM markets" in s:
            self.row = {"close_time": datetime(2026, 1, 1, 12, 15, 0)}
        else:
            self.row = None

    def fetchone(self):
        return self.row


def _tq(ticker):
    return {"market_ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0],
            "trades_last_60s_count": 3, "trades_last_60s_volume_fp": 9.0,
            "trades_last_60s_vwap_yes": 0.51, "quote_change_events_60s": 2, "source_status": "ok"}


def test_primary_btc_row_is_eligible_with_coinbase_features():
    mk = datetime(2026, 1, 1, 12, 0, 0)
    row = b.build_row(StubCursor(), mk, _tq("KXBTC15M-26JAN011200-B92000"))
    assert row["model_eligible"] == 1, row["guard_reasons"]
    assert row["orderbook_imbalance"] is not None and abs(row["orderbook_imbalance"] - 0.2) < 1e-9
    assert row["cb_price"] is not None  # BTC spot joined for the primary series


def test_non_primary_row_has_orderflow_but_is_never_eligible():
    mk = datetime(2026, 1, 1, 12, 0, 0)
    row = b.build_row(StubCursor(), mk, _tq("KXETH15M-26JAN011200-B3200"))
    # Research features ARE populated (the whole point: no longer null)...
    assert row["orderbook_imbalance"] is not None
    assert row["trades_last_60s_count"] == 3
    # ...but it must never reach the BTC live/sim readers, and carries no BTC spot.
    assert row["model_eligible"] == 0
    assert "NON_PRIMARY_SERIES" in row["guard_reasons"]
    assert row["cb_price"] is None


def test_primary_series_is_first_and_btc():
    assert micro_series()[0] == "KXBTC15M"
    assert is_primary_micro_ticker("KXBTC15M-26JAN011200-B92000")
    assert not is_primary_micro_ticker("KXETH15M-26JAN011200-B3200")
