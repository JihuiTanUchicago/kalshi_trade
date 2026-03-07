from data_pipeline.common import get_db_conn

DDL = [
    """
    CREATE TABLE IF NOT EXISTS markets (
      ticker VARCHAR(128) PRIMARY KEY,
      event_ticker VARCHAR(128) NULL,
      series_ticker VARCHAR(64) NULL,
      title TEXT NULL,
      subtitle TEXT NULL,
      status VARCHAR(32) NULL,
      open_time DATETIME NULL,
      close_time DATETIME NULL,
      expiration_time DATETIME NULL,
      last_seen_utc DATETIME NOT NULL,
      raw_json JSON NULL,
      INDEX idx_markets_event (event_ticker),
      INDEX idx_markets_series (series_ticker),
      INDEX idx_markets_close (close_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS market_trades (
      trade_id VARCHAR(128) PRIMARY KEY,
      ticker VARCHAR(128) NOT NULL,
      created_time DATETIME NOT NULL,
      yes_price_dollars DECIMAL(10,4) NULL,
      no_price_dollars DECIMAL(10,4) NULL,
      count_fp DECIMAL(18,2) NULL,
      taker_side VARCHAR(8) NULL,
      collected_at_utc DATETIME NOT NULL,
      raw_json JSON NOT NULL,
      INDEX idx_trades_ticker_time (ticker, created_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS market_candles (
      ticker VARCHAR(128) NOT NULL,
      end_period_ts BIGINT NOT NULL,
      period_interval_minutes INT NOT NULL,
      yes_bid_open DECIMAL(10,4) NULL,
      yes_bid_close DECIMAL(10,4) NULL,
      yes_ask_open DECIMAL(10,4) NULL,
      yes_ask_close DECIMAL(10,4) NULL,
      price_open DECIMAL(10,4) NULL,
      price_close DECIMAL(10,4) NULL,
      volume_fp DECIMAL(18,2) NULL,
      open_interest_fp DECIMAL(18,2) NULL,
      collected_at_utc DATETIME NOT NULL,
      raw_json JSON NOT NULL,
      PRIMARY KEY (ticker, end_period_ts, period_interval_minutes),
      INDEX idx_candles_ticker_time (ticker, end_period_ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS forward_quotes (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      snapshot_time_utc DATETIME NOT NULL,
      market_ticker VARCHAR(128) NOT NULL,
      event_ticker VARCHAR(128) NULL,
      yes_bid_dollars DECIMAL(10,4) NULL,
      yes_ask_dollars DECIMAL(10,4) NULL,
      yes_bid_size_fp DECIMAL(18,2) NULL,
      yes_ask_size_fp DECIMAL(18,2) NULL,
      volume_fp DECIMAL(18,2) NULL,
      open_interest_fp DECIMAL(18,2) NULL,
      status VARCHAR(32) NULL,
      raw_json JSON NOT NULL,
      INDEX idx_fq_ticker_time (market_ticker, snapshot_time_utc),
      INDEX idx_fq_event_time (event_ticker, snapshot_time_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS collector_state (
      state_key VARCHAR(128) PRIMARY KEY,
      state_value TEXT NOT NULL,
      updated_at_utc DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS coinbase_ticks (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      snapshot_time_utc DATETIME NOT NULL,
      product_id VARCHAR(32) NOT NULL,
      price DECIMAL(18,4) NULL,
      bid DECIMAL(18,4) NULL,
      ask DECIMAL(18,4) NULL,
      volume_24h DECIMAL(22,6) NULL,
      status VARCHAR(32) NOT NULL,
      raw_json JSON NOT NULL,
      INDEX idx_coinbase_ticks_time (snapshot_time_utc),
      INDEX idx_coinbase_product_time (product_id, snapshot_time_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_quote_features_1m (
      snapshot_minute_utc DATETIME NOT NULL,
      market_ticker VARCHAR(128) NULL,
      event_ticker VARCHAR(128) NULL,
      trades_last_60s_count INT NULL,
      trades_last_60s_volume_fp DECIMAL(18,2) NULL,
      trades_last_60s_vwap_yes DECIMAL(10,4) NULL,
      quote_change_events_60s INT NULL,
      source_status VARCHAR(32) NOT NULL,
      raw_json JSON NOT NULL,
      PRIMARY KEY (snapshot_minute_utc),
      INDEX idx_feature1m_event (event_ticker, snapshot_minute_utc),
      INDEX idx_feature1m_market (market_ticker, snapshot_minute_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS ws_quote_change_1m (
      snapshot_minute_utc DATETIME NOT NULL,
      market_ticker VARCHAR(128) NOT NULL,
      event_ticker VARCHAR(128) NULL,
      quote_change_events INT NOT NULL DEFAULT 0,
      last_yes_bid_dollars DECIMAL(10,4) NULL,
      last_yes_ask_dollars DECIMAL(10,4) NULL,
      updated_at_utc DATETIME NOT NULL,
      PRIMARY KEY (snapshot_minute_utc, market_ticker),
      INDEX idx_wsq_event_time (event_ticker, snapshot_minute_utc),
      INDEX idx_wsq_market_time (market_ticker, snapshot_minute_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS model_features_1m (
      snapshot_minute_utc DATETIME NOT NULL,
      market_ticker VARCHAR(128) NULL,
      event_ticker VARCHAR(128) NULL,
      yes_bid_dollars DECIMAL(10,4) NULL,
      yes_ask_dollars DECIMAL(10,4) NULL,
      spread_dollars DECIMAL(10,4) NULL,
      mid_dollars DECIMAL(10,4) NULL,
      yes_bid_size_fp DECIMAL(18,2) NULL,
      yes_ask_size_fp DECIMAL(18,2) NULL,
      orderbook_imbalance DECIMAL(12,6) NULL,
      mid_ret_1m DECIMAL(14,8) NULL,
      mid_ret_3m DECIMAL(14,8) NULL,
      trades_last_60s_count INT NULL,
      trades_last_60s_volume_fp DECIMAL(18,2) NULL,
      trades_last_60s_vwap_yes DECIMAL(10,4) NULL,
      quote_change_events_60s INT NULL,
      time_to_expiry_sec INT NULL,
      cb_price DECIMAL(18,4) NULL,
      cb_ret_1m DECIMAL(14,8) NULL,
      cb_ret_3m DECIMAL(14,8) NULL,
      cb_ret_5m DECIMAL(14,8) NULL,
      cb_vol_5m DECIMAL(14,8) NULL,
      kalshi_data_age_sec INT NULL,
      coinbase_data_age_sec INT NULL,
      model_eligible TINYINT(1) NOT NULL DEFAULT 0,
      guard_status VARCHAR(16) NOT NULL,
      guard_reasons_json JSON NOT NULL,
      raw_json JSON NOT NULL,
      PRIMARY KEY (snapshot_minute_utc),
      INDEX idx_model_features_market (market_ticker, snapshot_minute_utc),
      INDEX idx_model_features_event (event_ticker, snapshot_minute_utc),
      INDEX idx_model_features_guard (guard_status, snapshot_minute_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_model_predictions_1m (
      snapshot_minute_utc DATETIME NOT NULL,
      model_name VARCHAR(32) NOT NULL,
      market_ticker VARCHAR(128) NULL,
      prob_yes DECIMAL(10,6) NOT NULL,
      signal_yes TINYINT(1) NOT NULL,
      edge_est DECIMAL(10,6) NULL,
      train_rows INT NOT NULL,
      test_rows INT NOT NULL,
      brier DECIMAL(14,8) NULL,
      logloss DECIMAL(14,8) NULL,
      rf_regime VARCHAR(32) NULL,
      raw_json JSON NOT NULL,
      PRIMARY KEY (snapshot_minute_utc, model_name),
      INDEX idx_sim_pred_model_time (model_name, snapshot_minute_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_positions (
      model_name VARCHAR(32) PRIMARY KEY,
      opened_at_utc DATETIME NOT NULL,
      market_ticker VARCHAR(128) NOT NULL,
      qty_contracts INT NOT NULL,
      entry_price_dollars DECIMAL(10,6) NOT NULL,
      trade_id BIGINT NOT NULL,
      raw_json JSON NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_trades (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      model_name VARCHAR(32) NOT NULL,
      market_ticker VARCHAR(128) NOT NULL,
      opened_at_utc DATETIME NOT NULL,
      closed_at_utc DATETIME NULL,
      qty_contracts INT NOT NULL,
      entry_price_dollars DECIMAL(10,6) NOT NULL,
      exit_price_dollars DECIMAL(10,6) NULL,
      pnl_dollars DECIMAL(14,6) NULL,
      status VARCHAR(16) NOT NULL,
      raw_json JSON NOT NULL,
      INDEX idx_sim_trades_model_time (model_name, opened_at_utc),
      INDEX idx_sim_trades_status (status, opened_at_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_equity_1m (
      snapshot_minute_utc DATETIME NOT NULL,
      model_name VARCHAR(32) NOT NULL,
      realized_pnl_dollars DECIMAL(14,6) NOT NULL,
      cumulative_pnl_dollars DECIMAL(14,6) NOT NULL,
      closed_trades_count INT NOT NULL,
      win_rate DECIMAL(10,6) NULL,
      raw_json JSON NOT NULL,
      PRIMARY KEY (snapshot_minute_utc, model_name),
      INDEX idx_sim_equity_model_time (model_name, snapshot_minute_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_portfolio_20s (
      snapshot_time_utc DATETIME NOT NULL,
      model_name VARCHAR(32) NOT NULL,
      cash_dollars DECIMAL(14,6) NOT NULL,
      position_value_dollars DECIMAL(14,6) NOT NULL,
      realized_pnl_dollars DECIMAL(14,6) NOT NULL,
      unrealized_pnl_dollars DECIMAL(14,6) NOT NULL,
      equity_dollars DECIMAL(14,6) NOT NULL,
      peak_equity_dollars DECIMAL(14,6) NOT NULL,
      drawdown_dollars DECIMAL(14,6) NOT NULL,
      raw_json JSON NOT NULL,
      PRIMARY KEY (snapshot_time_utc, model_name),
      INDEX idx_sim_portfolio_model_time (model_name, snapshot_time_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_model_lab_runs (
      run_id BIGINT AUTO_INCREMENT PRIMARY KEY,
      run_time_utc DATETIME NOT NULL,
      cutoff_utc DATETIME NULL,
      sample_rows INT NOT NULL,
      notes_json JSON NOT NULL,
      INDEX idx_model_lab_runs_time (run_time_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_model_lab_results (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      run_id BIGINT NOT NULL,
      variant_id VARCHAR(128) NOT NULL,
      model_family VARCHAR(32) NOT NULL,
      horizon_min INT NOT NULL,
      pred_threshold DECIMAL(10,6) NOT NULL,
      edge_threshold DECIMAL(10,6) NOT NULL,
      segment VARCHAR(32) NOT NULL,
      n_samples INT NOT NULL,
      n_trades INT NOT NULL,
      trade_rate DECIMAL(12,8) NULL,
      win_rate DECIMAL(12,8) NULL,
      total_pnl DECIMAL(16,6) NULL,
      avg_pnl DECIMAL(16,6) NULL,
      pnl_per_trade DECIMAL(16,6) NULL,
      brier DECIMAL(16,8) NULL,
      logloss DECIMAL(16,8) NULL,
      max_drawdown DECIMAL(16,6) NULL,
      sharpe_like DECIMAL(16,8) NULL,
      meta_json JSON NOT NULL,
      INDEX idx_model_lab_results_run (run_id),
      INDEX idx_model_lab_results_variant (variant_id, segment),
      INDEX idx_model_lab_results_segment (segment, total_pnl)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS live_settings (
      settings_key VARCHAR(64) PRIMARY KEY,
      settings_json JSON NOT NULL,
      updated_at_utc DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS live_orders (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at_utc DATETIME NOT NULL,
      market_ticker VARCHAR(128) NOT NULL,
      action VARCHAR(16) NOT NULL,
      side VARCHAR(16) NOT NULL,
      qty_contracts INT NOT NULL,
      limit_price_dollars DECIMAL(10,6) NULL,
      status VARCHAR(32) NOT NULL,
      kalshi_order_id VARCHAR(128) NULL,
      client_order_id VARCHAR(128) NOT NULL,
      raw_json JSON NOT NULL,
      INDEX idx_live_orders_time (created_at_utc),
      INDEX idx_live_orders_status (status, created_at_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS live_positions (
      market_ticker VARCHAR(128) PRIMARY KEY,
      opened_at_utc DATETIME NOT NULL,
      qty_contracts INT NOT NULL,
      entry_price_dollars DECIMAL(10,6) NOT NULL,
      model_name VARCHAR(32) NOT NULL,
      raw_json JSON NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS live_trades (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      opened_at_utc DATETIME NOT NULL,
      closed_at_utc DATETIME NULL,
      market_ticker VARCHAR(128) NOT NULL,
      model_name VARCHAR(32) NOT NULL,
      qty_contracts INT NOT NULL,
      entry_price_dollars DECIMAL(10,6) NOT NULL,
      exit_price_dollars DECIMAL(10,6) NULL,
      pnl_dollars DECIMAL(14,6) NULL,
      status VARCHAR(16) NOT NULL,
      raw_json JSON NOT NULL,
      INDEX idx_live_trades_time (opened_at_utc),
      INDEX idx_live_trades_status (status, opened_at_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS live_portfolio_20s (
      snapshot_time_utc DATETIME NOT NULL PRIMARY KEY,
      cash_dollars DECIMAL(14,6) NOT NULL,
      position_value_dollars DECIMAL(14,6) NOT NULL,
      realized_pnl_dollars DECIMAL(14,6) NOT NULL,
      unrealized_pnl_dollars DECIMAL(14,6) NOT NULL,
      equity_dollars DECIMAL(14,6) NOT NULL,
      peak_equity_dollars DECIMAL(14,6) NOT NULL,
      drawdown_dollars DECIMAL(14,6) NOT NULL,
      risk_state VARCHAR(16) NOT NULL,
      raw_json JSON NOT NULL,
      INDEX idx_live_portfolio_time (snapshot_time_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        for stmt in DDL:
            cur.execute(stmt)
    conn.close()
    print("Schema initialized.")


if __name__ == "__main__":
    main()
