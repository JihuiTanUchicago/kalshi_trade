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
      no_bid_dollars DECIMAL(10,4) NULL,
      no_ask_dollars DECIMAL(10,4) NULL,
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
    CREATE TABLE IF NOT EXISTS forward_quote_ticks (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      observed_at_utc DATETIME(3) NOT NULL,
      market_ticker VARCHAR(128) NOT NULL,
      event_ticker VARCHAR(128) NULL,
      yes_bid_dollars DECIMAL(10,4) NULL,
      yes_ask_dollars DECIMAL(10,4) NULL,
      yes_bid_size_fp DECIMAL(18,2) NULL,
      yes_ask_size_fp DECIMAL(18,2) NULL,
      INDEX idx_fqt_market_time (market_ticker, observed_at_utc),
      INDEX idx_fqt_time (observed_at_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS model_features_1m (
      snapshot_minute_utc DATETIME NOT NULL,
      market_ticker VARCHAR(128) NULL,
      event_ticker VARCHAR(128) NULL,
      target_btc_price DECIMAL(18,4) NULL,
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
      INDEX idx_sim_pred_model_time (model_name, snapshot_minute_utc),
      INDEX idx_sim_pred_time_only (snapshot_minute_utc)
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
      INDEX idx_sim_trades_status (status, opened_at_utc),
      INDEX idx_sim_trades_status_model (status, model_name)
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
      INDEX idx_sim_equity_model_time (model_name, snapshot_minute_utc),
      INDEX idx_sim_equity_time_only (snapshot_minute_utc)
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
    CREATE TABLE IF NOT EXISTS model_research_runs (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at_utc DATETIME NOT NULL,
      model_name VARCHAR(64) NOT NULL,
      stage VARCHAR(32) NOT NULL,
      objective_pnl_dollars DECIMAL(14,6) NOT NULL,
      n_train INT NOT NULL,
      n_eval INT NOT NULL,
      params_json JSON NOT NULL,
      selected_features_json JSON NOT NULL,
      metrics_json JSON NOT NULL,
      status VARCHAR(16) NOT NULL,
      notes VARCHAR(255) NULL,
      INDEX idx_mr_model_stage_time (model_name, stage, created_at_utc),
      INDEX idx_mr_status_time (status, created_at_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS model_research_feature_importance (
      run_id BIGINT NOT NULL,
      model_name VARCHAR(64) NOT NULL,
      feature_name VARCHAR(128) NOT NULL,
      importance_abs_mean DECIMAL(18,10) NOT NULL,
      importance_signed_mean DECIMAL(18,10) NOT NULL,
      rank_order INT NOT NULL,
      method VARCHAR(32) NOT NULL,
      created_at_utc DATETIME NOT NULL,
      PRIMARY KEY (run_id, feature_name),
      INDEX idx_mrfi_model_run (model_name, run_id),
      CONSTRAINT fk_mrfi_run FOREIGN KEY (run_id) REFERENCES model_research_runs(id) ON DELETE CASCADE
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
    CREATE TABLE IF NOT EXISTS sim_settings (
      settings_key VARCHAR(64) PRIMARY KEY,
      settings_json JSON NOT NULL,
      updated_at_utc DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_model_state (
      model_name VARCHAR(32) PRIMARY KEY,
      paused TINYINT(1) NOT NULL DEFAULT 0,
      paused_reason VARCHAR(255) NULL,
      paused_at_utc DATETIME NULL,
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
      model_name VARCHAR(32) NOT NULL,
      market_ticker VARCHAR(128) NOT NULL,
      opened_at_utc DATETIME NOT NULL,
      qty_contracts INT NOT NULL,
      entry_price_dollars DECIMAL(10,6) NOT NULL,
      raw_json JSON NOT NULL,
      PRIMARY KEY (model_name, market_ticker)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS live_model_state (
      model_name VARCHAR(32) PRIMARY KEY,
      paused TINYINT(1) NOT NULL DEFAULT 0,
      paused_reason VARCHAR(255) NULL,
      paused_at_utc DATETIME NULL,
      updated_at_utc DATETIME NOT NULL
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
        # Backward-compatible schema migration for existing deployments.
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE()
              AND TABLE_NAME='model_features_1m'
              AND COLUMN_NAME='target_btc_price'
            """
        )
        has_col = cur.fetchone()["c"] > 0
        if not has_col:
            cur.execute(
                """
                ALTER TABLE model_features_1m
                ADD COLUMN target_btc_price DECIMAL(18,4) NULL
                AFTER event_ticker
                """
            )

        for col_name, add_col_sql in (
            ("no_bid_dollars", "ALTER TABLE forward_quotes ADD COLUMN no_bid_dollars DECIMAL(10,4) NULL AFTER open_interest_fp"),
            ("no_ask_dollars", "ALTER TABLE forward_quotes ADD COLUMN no_ask_dollars DECIMAL(10,4) NULL AFTER no_bid_dollars"),
        ):
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='forward_quotes' AND COLUMN_NAME=%s
                """,
                (col_name,),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute(add_col_sql)

        # live_positions used to be PK'd on market_ticker alone (one global
        # RF-only book) - multi-strategy live trading needs one position per
        # (model_name, market_ticker) so independent strategies can't clobber
        # each other's position rows. Safe to run unconditionally: only
        # touches the PK shape, and this table is empty between trades by
        # design (a position lives here only while open).
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='live_positions'
              AND CONSTRAINT_NAME='PRIMARY' AND COLUMN_NAME='model_name'
            """
        )
        if cur.fetchone()["c"] == 0:
            cur.execute("SELECT COUNT(*) AS c FROM live_positions")
            if cur.fetchone()["c"] == 0:
                cur.execute("ALTER TABLE live_positions DROP PRIMARY KEY, ADD PRIMARY KEY (model_name, market_ticker)")
            else:
                print("[WARN] live_positions has open rows and an old PK shape - skipping automatic migration, resolve manually.")

        # Indexes added after these tables already existed in deployed
        # environments - CREATE TABLE IF NOT EXISTS above is a no-op there,
        # so add them explicitly if missing.
        for table, index_name, add_index_sql in (
            ("sim_equity_1m", "idx_sim_equity_time_only", "ALTER TABLE sim_equity_1m ADD INDEX idx_sim_equity_time_only (snapshot_minute_utc)"),
            ("sim_trades", "idx_sim_trades_status_model", "ALTER TABLE sim_trades ADD INDEX idx_sim_trades_status_model (status, model_name)"),
            ("sim_model_predictions_1m", "idx_sim_pred_time_only", "ALTER TABLE sim_model_predictions_1m ADD INDEX idx_sim_pred_time_only (snapshot_minute_utc)"),
            # sim_portfolio_20s_updater.py re-derives the running peak equity
            # with "SELECT MAX(peak_equity_dollars) WHERE model_name=..." every
            # 20s, forever, over an append-only table - after 6 months of
            # history this became a slow full scan per model per tick, and a
            # pileup of those queries queuing behind each other on a small RDS
            # instance is what exhausted max_connections in the 2026-09-13
            # incident. A covering index lets MySQL answer the MAX via a loose
            # index scan instead of reading every row.
            ("sim_portfolio_20s", "idx_sim_portfolio_model_peak", "ALTER TABLE sim_portfolio_20s ADD INDEX idx_sim_portfolio_model_peak (model_name, peak_equity_dollars)"),
            ("live_portfolio_20s", "idx_live_portfolio_peak", "ALTER TABLE live_portfolio_20s ADD INDEX idx_live_portfolio_peak (peak_equity_dollars)"),
            # forward_feed_health() filters purely by snapshot_time_utc (no
            # ticker), which the existing (market_ticker, snapshot_time_utc)
            # and (event_ticker, snapshot_time_utc) composite indexes can't
            # serve - it was doing a full scan of forward_quotes (the largest
            # table, ~1M+ rows) on every /health and every "/" page load,
            # 10-14s each, part of the same 2026-09-13 incident.
            ("forward_quotes", "idx_fq_time_only", "ALTER TABLE forward_quotes ADD INDEX idx_fq_time_only (snapshot_time_utc)"),
        ):
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s
                """,
                (table, index_name),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute(add_index_sql)
    conn.close()
    print("Schema initialized.")


if __name__ == "__main__":
    main()
