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


# -- signed order flow from market_trades ----------------------------------------


class _FlowCur:
    def __init__(self, row=None, fail=False):
        self.row, self.fail, self.sql, self.params = row, fail, None, None

    def execute(self, sql, params=()):
        if self.fail:
            raise RuntimeError("no table")
        self.sql, self.params = " ".join(sql.split()), params

    def fetchone(self):
        return self.row


def test_trade_flow_signs_volume_by_taker_side_strictly_before_the_minute():
    mk = datetime(2026, 1, 1, 12, 0, 0)
    cur = _FlowCur({"y60": 30, "n60": 10, "y300": 40, "n300": 60})
    f = b.trade_flow(cur, "KXBTC15M-X", mk)
    assert f == {"taker_yes_vol_60s": 30.0, "taker_no_vol_60s": 10.0,
                 "flow_imbalance_60s": 0.5, "flow_imbalance_300s": -0.2}
    assert "created_time >= %s AND created_time < %s" in cur.sql
    assert cur.params[2] == "KXBTC15M-X"
    assert cur.params[4] == mk and cur.params[3] == datetime(2026, 1, 1, 11, 55, 0)
    assert cur.params[0] == datetime(2026, 1, 1, 11, 59, 0)


def test_trade_flow_no_trades_is_zero_volume_and_no_imbalance():
    f = b.trade_flow(_FlowCur({"y60": None, "n60": None, "y300": None, "n300": None}), "K", datetime(2026, 1, 1))
    assert f["taker_yes_vol_60s"] == 0.0 and f["flow_imbalance_60s"] is None and f["flow_imbalance_300s"] is None


def test_trade_flow_read_failure_leaves_features_null():
    f = b.trade_flow(_FlowCur(fail=True), "K", datetime(2026, 1, 1))
    assert set(f.values()) == {None}


def test_build_row_carries_flow_columns_and_upsert_writes_them():
    row = b.build_row(StubCursor(), datetime(2026, 1, 1, 12, 0, 0), _tq("KXBTC15M-26JAN011200-B92000"))
    for k in ("taker_yes_vol_60s", "taker_no_vol_60s", "flow_imbalance_60s", "flow_imbalance_300s"):
        assert k in row

    class _Rec:
        def execute(self, sql, params=()):
            self.sql, self.params = sql, params

    rec = _Rec()
    b.upsert_row(rec, row)
    assert rec.sql.count("%s") == len(rec.params) == 33
    assert "flow_imbalance_300s=VALUES(flow_imbalance_300s)" in rec.sql
