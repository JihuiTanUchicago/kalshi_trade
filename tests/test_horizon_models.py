from __future__ import annotations

import pandas as pd

from work.horizon_models import (
    ResearchConfig,
    TradeRule,
    backtest_edge_strategy,
    build_expiry_resolution_dataset,
)


def test_build_expiry_resolution_dataset_computes_terminal_label_and_exit() -> None:
    df = pd.DataFrame(
        [
            {
                "snapshot_minute_utc": "2026-03-11 10:00:00",
                "market_ticker": "TEST-1",
                "target_btc_price": 100.0,
                "yes_bid_dollars": 0.40,
                "yes_ask_dollars": 0.45,
                "spread_dollars": 0.05,
                "mid_dollars": 0.425,
                "yes_bid_size_fp": 10.0,
                "yes_ask_size_fp": 5.0,
                "orderbook_imbalance": 0.33,
                "mid_ret_1m": 0.01,
                "mid_ret_3m": 0.02,
                "trades_last_60s_count": 10,
                "trades_last_60s_volume_fp": 100.0,
                "trades_last_60s_vwap_yes": 0.43,
                "quote_change_events_60s": 2,
                "time_to_expiry_sec": 600,
                "cb_price": 102.0,
                "cb_ret_1m": 0.001,
                "cb_ret_3m": 0.002,
                "cb_ret_5m": 0.003,
                "cb_vol_5m": 0.01,
                "kalshi_data_age_sec": 0.0,
                "coinbase_data_age_sec": 0.0,
                "model_eligible": 1,
            },
            {
                "snapshot_minute_utc": "2026-03-11 10:01:00",
                "market_ticker": "TEST-1",
                "target_btc_price": 100.0,
                "yes_bid_dollars": 0.44,
                "yes_ask_dollars": 0.49,
                "spread_dollars": 0.05,
                "mid_dollars": 0.465,
                "yes_bid_size_fp": 11.0,
                "yes_ask_size_fp": 4.0,
                "orderbook_imbalance": 0.47,
                "mid_ret_1m": 0.02,
                "mid_ret_3m": 0.04,
                "trades_last_60s_count": 12,
                "trades_last_60s_volume_fp": 110.0,
                "trades_last_60s_vwap_yes": 0.47,
                "quote_change_events_60s": 3,
                "time_to_expiry_sec": 540,
                "cb_price": 103.0,
                "cb_ret_1m": 0.002,
                "cb_ret_3m": 0.003,
                "cb_ret_5m": 0.004,
                "cb_vol_5m": 0.01,
                "kalshi_data_age_sec": 0.0,
                "coinbase_data_age_sec": 0.0,
                "model_eligible": 1,
            },
            {
                "snapshot_minute_utc": "2026-03-11 10:02:00",
                "market_ticker": "TEST-1",
                "target_btc_price": 100.0,
                "yes_bid_dollars": 0.52,
                "yes_ask_dollars": 0.57,
                "spread_dollars": 0.05,
                "mid_dollars": 0.545,
                "yes_bid_size_fp": 12.0,
                "yes_ask_size_fp": 3.0,
                "orderbook_imbalance": 0.60,
                "mid_ret_1m": 0.03,
                "mid_ret_3m": 0.05,
                "trades_last_60s_count": 14,
                "trades_last_60s_volume_fp": 120.0,
                "trades_last_60s_vwap_yes": 0.54,
                "quote_change_events_60s": 3,
                "time_to_expiry_sec": 480,
                "cb_price": 104.0,
                "cb_ret_1m": 0.002,
                "cb_ret_3m": 0.003,
                "cb_ret_5m": 0.004,
                "cb_vol_5m": 0.01,
                "kalshi_data_age_sec": 0.0,
                "coinbase_data_age_sec": 0.0,
                "model_eligible": 1,
            },
            {
                "snapshot_minute_utc": "2026-03-11 10:03:00",
                "market_ticker": "TEST-1",
                "target_btc_price": 100.0,
                "yes_bid_dollars": 0.95,
                "yes_ask_dollars": 0.98,
                "spread_dollars": 0.03,
                "mid_dollars": 0.965,
                "yes_bid_size_fp": 20.0,
                "yes_ask_size_fp": 1.0,
                "orderbook_imbalance": 0.90,
                "mid_ret_1m": 0.05,
                "mid_ret_3m": 0.07,
                "trades_last_60s_count": 16,
                "trades_last_60s_volume_fp": 140.0,
                "trades_last_60s_vwap_yes": 0.93,
                "quote_change_events_60s": 4,
                "time_to_expiry_sec": 420,
                "cb_price": 105.0,
                "cb_ret_1m": 0.003,
                "cb_ret_3m": 0.004,
                "cb_ret_5m": 0.005,
                "cb_vol_5m": 0.01,
                "kalshi_data_age_sec": 0.0,
                "coinbase_data_age_sec": 0.0,
                "model_eligible": 1,
            },
        ]
    )
    dataset = build_expiry_resolution_dataset(df, ResearchConfig(take_profit_buffer_dollars=0.05))

    first = dataset.iloc[0]
    assert first["resolution_label"] == 1
    assert first["trade_exit_ts"] == pd.Timestamp("2026-03-11 10:02:00")
    assert abs(first["trade_pnl"] - 0.07) < 1e-9


def test_backtest_edge_strategy_exits_and_reenters_on_timestamp() -> None:
    frame = pd.DataFrame(
        [
            {
                "snapshot_minute_utc": pd.Timestamp("2026-03-11 10:00:00"),
                "yes_ask_dollars": 0.40,
                "trade_exit_ts": pd.Timestamp("2026-03-11 10:02:00"),
                "trade_pnl": 0.15,
            },
            {
                "snapshot_minute_utc": pd.Timestamp("2026-03-11 10:01:00"),
                "yes_ask_dollars": 0.35,
                "trade_exit_ts": pd.Timestamp("2026-03-11 10:02:00"),
                "trade_pnl": -0.20,
            },
            {
                "snapshot_minute_utc": pd.Timestamp("2026-03-11 10:02:00"),
                "yes_ask_dollars": 0.50,
                "trade_exit_ts": pd.Timestamp("2026-03-11 10:03:00"),
                "trade_pnl": 0.12,
            },
            {
                "snapshot_minute_utc": pd.Timestamp("2026-03-11 10:03:00"),
                "yes_ask_dollars": 0.60,
                "trade_exit_ts": pd.Timestamp("2026-03-11 10:04:00"),
                "trade_pnl": -0.30,
            },
        ]
    )
    probabilities = [0.70, 0.90, 0.72, 0.20]
    rule = TradeRule(probability_threshold=0.55, edge_threshold=0.10)

    result = backtest_edge_strategy(frame, probabilities, rule)

    assert result.trades == 2
    assert abs(result.pnl - 0.27) < 1e-9
    assert abs(result.win_rate - 1.0) < 1e-9
