"""Tables for the Tau customer app. Additive and idempotent, like
data_pipeline/init_schema.py: `python -m app.schema`.

Money is DECIMAL, never FLOAT. Every paper-cash movement is a row in
app_ledger and the balance is their sum, so a balance can always be explained
line by line and two writers cannot lose an update to each other.
"""
from data_pipeline import init_schema
from data_pipeline.common import get_db_conn
from app.adapters.kalshi_perps import kalshi_perps_repository
from app.adapters.alpaca import alpaca_paper_repository
from app.adapters.brokers import broker_repository
from app import rsi_playbook, rsi_repair, rsi_scout, tournament
from app.adapters.kalshi_perps import kalshi_perps_orders_repository

DDL = [
    # -- market history (written by app.market_history; Kalshi candles go in
    # the pipeline's existing market_candles table) ---------------------------
    """
    CREATE TABLE IF NOT EXISTS hist_markets (
      ticker VARCHAR(128) PRIMARY KEY,
      series_ticker VARCHAR(32) NOT NULL,
      event_ticker VARCHAR(128) NOT NULL,
      strike DECIMAL(18,4) NOT NULL,
      open_time DATETIME NOT NULL,
      close_time DATETIME NOT NULL,
      result VARCHAR(8) NULL,
      expiration_value DECIMAL(18,4) NULL,
      candles_done TINYINT(1) NOT NULL DEFAULT 0,
      INDEX idx_hist_series_close (series_ticker, close_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS btc_candles_1m (
      start_ts BIGINT PRIMARY KEY,
      open DECIMAL(18,4) NOT NULL,
      high DECIMAL(18,4) NOT NULL,
      low DECIMAL(18,4) NOT NULL,
      close DECIMAL(18,4) NOT NULL,
      volume DECIMAL(22,8) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Generalized underlying-spot candles keyed by Coinbase product (BTC-USD, ETH-USD, …),
    # so the backtester can price any crypto series off its own underlying. Supersedes
    # btc_candles_1m (BTC rows migrated in by init_schema); readers filter by `symbol`.
    """
    CREATE TABLE IF NOT EXISTS spot_candles_1m (
      symbol VARCHAR(16) NOT NULL,
      start_ts BIGINT NOT NULL,
      open DECIMAL(18,4) NOT NULL,
      high DECIMAL(18,4) NOT NULL,
      low DECIMAL(18,4) NOT NULL,
      close DECIMAL(18,4) NOT NULL,
      volume DECIMAL(22,8) NOT NULL,
      PRIMARY KEY (symbol, start_ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Non-price TAO subnet signals (TAO_VENUE_DESIGN.md §B.3), keyed (netuid, ts) and joined onto
    # the spot price series by ts - the same (key, minute) join model_features_1m uses. The alpha
    # PRICE series itself lives in spot_candles_1m (symbol=TAO-SN{n}); only these tokenomics/flow
    # features and the pool reserves (which drive the slippage fill model) live here. Written by
    # data_pipeline/taostats_collector.py via app/adapters/tao/tao_repository.py; read into the spot backtest
    # window so signals(window) can condition on emission/registration/staking mechanisms.
    """
    CREATE TABLE IF NOT EXISTS tao_subnet_features (
      netuid INT NOT NULL,
      ts BIGINT NOT NULL,
      emission_weight DECIMAL(18,10) NULL,   -- subnet's share of network emissions (tokenomics)
      tao_pool DECIMAL(30,10) NULL,          -- TAO reserve in the subnet AMM pool (tau_pool)
      alpha_pool DECIMAL(30,10) NULL,        -- alpha reserve in the pool (alpha_pool); drives fill depth
      registrations INT NULL,                -- registration events / churn in the window
      net_stake_flow DECIMAL(30,10) NULL,    -- net TAO staked into (−unstaked from) the subnet
      raw_json JSON NULL,                    -- the source taostats payload, for audit
      PRIMARY KEY (netuid, ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # -- identity -------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS app_users (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      google_sub VARCHAR(64) NOT NULL UNIQUE,
      email VARCHAR(320) NOT NULL,
      name VARCHAR(200) NULL,
      picture_url VARCHAR(1000) NULL,
      autopilot TINYINT(1) NOT NULL DEFAULT 0,
      created_at DATETIME NOT NULL,
      last_login_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_sessions (
      token_hash CHAR(64) PRIMARY KEY,
      user_id BIGINT NOT NULL,
      created_at DATETIME NOT NULL,
      expires_at DATETIME NOT NULL,
      INDEX idx_sessions_user (user_id),
      INDEX idx_sessions_expiry (expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_oauth_states (
      state CHAR(43) PRIMARY KEY,
      nonce CHAR(43) NOT NULL,
      code_verifier CHAR(64) NOT NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_oauth_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_kalshi_keys (
      user_id BIGINT PRIMARY KEY,
      key_id VARCHAR(128) NOT NULL,
      private_key_enc BLOB NOT NULL,
      created_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # The per-user Kalshi DEMO (sandbox) API key, a dead ringer for app_kalshi_keys.
    # Kept in its own table so a user's demo key and live key never share a row and
    # the demo execution path (app/adapters/kalshi/kalshi_dev_exec.py) can only ever read the demo key.
    # Encrypted the same way (AES-256-GCM bound to user_id); demo != real money.
    """
    CREATE TABLE IF NOT EXISTS app_kalshi_dev_keys (
      user_id BIGINT PRIMARY KEY,
      key_id VARCHAR(128) NOT NULL,
      private_key_enc BLOB NOT NULL,
      created_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # -- money ----------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS app_ledger (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      kind VARCHAR(24) NOT NULL,
      amount DECIMAL(14,4) NOT NULL,
      position_id BIGINT NULL,
      memo VARCHAR(255) NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_ledger_user_time (user_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # -- agents ---------------------------------------------------------------
    # One queue for every kind of agent work (research, chat, review) so there
    # is one claim path and one place to see what is stuck.
    """
    CREATE TABLE IF NOT EXISTS app_agent_runs (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      kind VARCHAR(16) NOT NULL,
      market VARCHAR(16) NULL,
      direction VARCHAR(48) NULL,
      prompt TEXT NULL,
      deployment_id BIGINT NULL,
      status VARCHAR(16) NOT NULL,
      worker_id VARCHAR(64) NULL,
      hypotheses_tried INT NOT NULL DEFAULT 0,
      strategies_passed INT NOT NULL DEFAULT 0,
      input_tokens INT NOT NULL DEFAULT 0,
      output_tokens INT NOT NULL DEFAULT 0,
      error TEXT NULL,
      created_at DATETIME NOT NULL,
      started_at DATETIME NULL,
      heartbeat_at DATETIME NULL,
      finished_at DATETIME NULL,
      INDEX idx_runs_status (status, created_at),
      INDEX idx_runs_user (user_id, kind, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_agent_events (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      run_id BIGINT NOT NULL,
      kind VARCHAR(16) NOT NULL,
      message TEXT NOT NULL,
      data_json JSON NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_events_run (run_id, id),
      INDEX idx_events_run_kind (run_id, kind, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_strategies (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      run_id BIGINT NULL,
      parent_id BIGINT NULL,
      market VARCHAR(16) NOT NULL,
      direction VARCHAR(48) NOT NULL,
      title VARCHAR(200) NOT NULL,
      thesis TEXT NOT NULL,
      spec_json JSON NOT NULL,
      status VARCHAR(16) NOT NULL,
      result_json JSON NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_strat_user (user_id, status, created_at),
      INDEX idx_strat_run (run_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # -- trading --------------------------------------------------------------
    # Daily tally of what stopped each deployment's entry rule (spec.entry_scan.blocked_at, or
    # 'qualified' / 'no contracts'), one row per (deployment, UTC day, outcome). Readout only.
    """
    CREATE TABLE IF NOT EXISTS app_deployment_scan_days (
      deployment_id BIGINT NOT NULL,
      day DATE NOT NULL,
      outcome VARCHAR(160) NOT NULL,
      n INT NOT NULL DEFAULT 0,
      PRIMARY KEY (deployment_id, day, outcome)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_deployments (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      strategy_id BIGINT NOT NULL,
      market VARCHAR(16) NOT NULL,
      mode VARCHAR(8) NOT NULL,
      status VARCHAR(12) NOT NULL,
      status_reason VARCHAR(255) NULL,
      last_decision_ts BIGINT NOT NULL DEFAULT 0,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      INDEX idx_dep_status (status, market),
      INDEX idx_dep_user (user_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_positions (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      deployment_id BIGINT NOT NULL,
      user_id BIGINT NOT NULL,
      mode VARCHAR(8) NOT NULL,
      ticker VARCHAR(128) NOT NULL,
      side VARCHAR(4) NOT NULL,
      qty INT NOT NULL,
      entry_price DECIMAL(10,4) NOT NULL,
      entry_fee DECIMAL(10,4) NOT NULL,
      market_close_time DATETIME NOT NULL,
      opened_at DATETIME NOT NULL,
      status VARCHAR(8) NOT NULL,
      exit_price DECIMAL(10,4) NULL,
      exit_fee DECIMAL(10,4) NULL,
      pnl DECIMAL(14,4) NULL,
      close_reason VARCHAR(32) NULL,
      closed_at DATETIME NULL,
      order_ref VARCHAR(128) NULL,
      INDEX idx_pos_dep (deployment_id, status),
      INDEX idx_pos_user (user_id, status, closed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Durable order-intent log (EXECUTION_RISK_HARDENING P0-1): one append-only row written and
    # COMMITTED *before* every real exchange order, updated after. It gives each order a durable,
    # idempotent identity (client_order_id = intent_id, reused on any retry) so a timed-out-but-
    # filled order is reconcilable instead of a double-fill, and a crash between the fill and the
    # DB write is recovered deterministically on boot (see repository.open_sent_intents / engine.
    # recover_sent_intents). status: sent -> filled|unfilled|error|booked. No key material here.
    """
    CREATE TABLE IF NOT EXISTS app_order_intents (
      intent_id CHAR(36) PRIMARY KEY,
      deployment_id BIGINT NOT NULL,
      user_id BIGINT NOT NULL,
      position_id BIGINT NULL,            -- the open position an EXIT closes; NULL for an entry
      mode VARCHAR(8) NOT NULL,           -- live|demo (paper never logs an intent — no real order)
      action VARCHAR(4) NOT NULL,         -- buy|sell
      side VARCHAR(4) NOT NULL,           -- yes|no
      ticker VARCHAR(128) NOT NULL,
      qty INT NOT NULL,
      limit_price DECIMAL(10,4) NOT NULL,
      client_order_id VARCHAR(64) NOT NULL,
      status VARCHAR(12) NOT NULL,        -- sent|filled|unfilled|error|booked
      external_order_id VARCHAR(128) NULL,
      fill_qty INT NULL,
      fill_price DECIMAL(10,4) NULL,
      fee DECIMAL(10,6) NULL,
      reason VARCHAR(32) NULL,            -- exit reason (carried into close_position on recovery)
      market_close_time DATETIME NULL,    -- entry recovery needs it to re-create the position row
      raw_json JSON NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      INDEX idx_intent_status (status, created_at),
      UNIQUE KEY uq_intent_coid (client_order_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # -- conversation ---------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS app_chat_messages (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      role VARCHAR(8) NOT NULL,
      content TEXT NOT NULL,
      proposal_id BIGINT NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_chat_user (user_id, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_credit_ledger (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      kind VARCHAR(16) NOT NULL,
      amount_usd DECIMAL(14,6) NOT NULL,
      memo VARCHAR(255) NULL,
      stripe_ref VARCHAR(128) NULL,
      run_id BIGINT NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_credit_user (user_id, id),
      UNIQUE KEY uq_credit_stripe (stripe_ref)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_stripe_customers (
      user_id BIGINT PRIMARY KEY,
      stripe_customer_id VARCHAR(128) NOT NULL,
      default_pm_id VARCHAR(128) NULL,
      auto_reload TINYINT(1) NOT NULL DEFAULT 1,
      reload_amount DECIMAL(10,2) NOT NULL DEFAULT 20.00,
      reload_threshold DECIMAL(10,2) NOT NULL DEFAULT 5.00,
      created_at DATETIME NOT NULL,
      UNIQUE KEY uq_stripe_customer (stripe_customer_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_images (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      content_type VARCHAR(32) NOT NULL,
      data MEDIUMBLOB NOT NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_images_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_posts (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      body TEXT NOT NULL,
      kind VARCHAR(16) NOT NULL DEFAULT 'note',
      snapshot_json JSON NULL,
      likes_count INT NOT NULL DEFAULT 0,
      comments_count INT NOT NULL DEFAULT 0,
      created_at DATETIME NOT NULL,
      INDEX idx_posts_created (created_at),
      INDEX idx_posts_user (user_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_post_likes (
      post_id BIGINT NOT NULL,
      user_id BIGINT NOT NULL,
      created_at DATETIME NOT NULL,
      PRIMARY KEY (post_id, user_id),
      INDEX idx_likes_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_post_comments (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      post_id BIGINT NOT NULL,
      user_id BIGINT NOT NULL,
      body TEXT NOT NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_comments_post (post_id, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_post_reactions (
      post_id BIGINT NOT NULL,
      user_id BIGINT NOT NULL,
      emoji VARCHAR(16) NOT NULL,
      created_at DATETIME NOT NULL,
      PRIMARY KEY (post_id, user_id, emoji),
      INDEX idx_reactions_post (post_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_waitlist (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      email VARCHAR(320) NOT NULL UNIQUE,
      note VARCHAR(500) NULL,
      status VARCHAR(16) NOT NULL DEFAULT 'requested',
      created_at DATETIME NOT NULL,
      INDEX idx_waitlist_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_proposals (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      kind VARCHAR(32) NOT NULL,
      deployment_id BIGINT NULL,
      strategy_id BIGINT NULL,
      reason TEXT NOT NULL,
      status VARCHAR(12) NOT NULL,
      created_at DATETIME NOT NULL,
      decided_at DATETIME NULL,
      INDEX idx_prop_user (user_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Tau-RSI P4: each user's current (self-evolved) exploration policy code, with
    # the replay score it earned. One row per user; absent = the DefaultPolicy.
    """
    CREATE TABLE IF NOT EXISTS app_policies (
      user_id BIGINT PRIMARY KEY,
      code MEDIUMTEXT NOT NULL,
      score DOUBLE NOT NULL,
      updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # In-app notifications (the bell by the profile): a strategy shared to you, a comment on
    # your post, etc. `link` is the in-app path to open; `read_at` NULL = unread.
    """
    CREATE TABLE IF NOT EXISTS app_notifications (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      kind VARCHAR(16) NOT NULL,
      body VARCHAR(400) NOT NULL,
      link VARCHAR(200) NULL,
      created_at DATETIME NOT NULL,
      read_at DATETIME NULL,
      INDEX idx_notif_user (user_id, read_at, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # -- rigorous-research ledger (RESEARCH_PIPELINE_DESIGN.md §B.3) ------------
    # The immutable experiment ledger. Immutability is enforced by table split:
    # registration fields (app_experiments) and result fields
    # (app_experiment_results) are only ever INSERTed, never UPDATEd/DELETEd.
    # Pre-registration. Written ONCE, before any validation number exists. IMMUTABLE.
    """
    CREATE TABLE IF NOT EXISTS app_experiments (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      run_id BIGINT NULL,
      strategy_id BIGINT NULL,              -- links to app_strategies once the row exists
      market VARCHAR(48) NOT NULL,          -- market key, or a cross-contract stream key (a+b)
      hypothesis_hash CHAR(64) NOT NULL,    -- sha256 of frozen spec + rationale; the identity
      spec_json JSON NOT NULL,              -- the FROZEN entry/exit/sizing/model rule
      economic_rationale TEXT NOT NULL,
      primary_metric VARCHAR(48) NOT NULL,
      null_hypothesis TEXT NOT NULL,
      alt_hypothesis TEXT NOT NULL,
      planned_test VARCHAR(64) NOT NULL,
      falsification_criteria TEXT NOT NULL,
      min_sample INT NOT NULL,
      cost_assumptions_json JSON NOT NULL,
      data_provenance_json JSON NULL,       -- {features:[...], sources:[...]} the hypothesis used
      research_partition_id BIGINT NOT NULL,
      planned_n_tests INT NOT NULL,
      correction_method VARCHAR(16) NOT NULL,   -- 'BH' | 'LORD++'
      registered_at DATETIME NOT NULL,
      UNIQUE KEY uq_exp_hash_run (run_id, hypothesis_hash),
      INDEX idx_exp_user_market (user_id, market, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Verdicts. APPEND-ONLY: one row per phase evaluation (validation, holdout, forward).
    # Records EVERY test, including failures and INCONCLUSIVEs. Never updated, never deleted.
    """
    CREATE TABLE IF NOT EXISTS app_experiment_results (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      experiment_id BIGINT NOT NULL,
      phase VARCHAR(12) NOT NULL,           -- 'validation' | 'holdout' | 'forward'
      classification VARCHAR(28) NOT NULL,  -- Classification enum value
      n_trades INT NOT NULL,
      net_pnl DECIMAL(14,4) NULL,
      mean_net_return DECIMAL(14,8) NULL,
      sharpe DECIMAL(10,4) NULL,
      psr DECIMAL(8,6) NULL,                -- probabilistic Sharpe
      dsr DECIMAL(8,6) NULL,                -- deflated Sharpe
      p_value DECIMAL(10,8) NULL,           -- primary (bootstrap) one-sided p
      ci_lo DECIMAL(14,8) NULL,
      ci_hi DECIMAL(14,8) NULL,
      fdr_alpha_i DECIMAL(10,8) NULL,       -- alpha spent on this test (LORD++)
      fdr_reject TINYINT(1) NULL,
      bh_reject TINYINT(1) NULL,
      placebo_p DECIMAL(10,8) NULL,         -- negative-control label-shuffle p
      n_trials_audited INT NULL,            -- trials that competed (feeds DSR)
      holdout_consumed TINYINT(1) NOT NULL DEFAULT 0,
      equity_curve_json JSON NULL,          -- for the research-paper page graphs
      folds_json JSON NULL,                 -- per-day/per-fold cross-day generalization breakdown
      verdict_at DATETIME NOT NULL,
      INDEX idx_res_exp (experiment_id, id),
      INDEX idx_res_phase (phase, verdict_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Online-FDR alpha-wealth STATE. One row per (user_id, market, scope). scope lets us keep
    # a separate wealth stream per market so a flood on btc15m can't starve btc_daily.
    """
    CREATE TABLE IF NOT EXISTS app_fdr_state (
      user_id BIGINT NOT NULL,
      market VARCHAR(48) NOT NULL,          -- per-market stream, or a cross-contract shared stream (a+b)
      method VARCHAR(16) NOT NULL DEFAULT 'LORD++',
      alpha DOUBLE NOT NULL,
      w0 DOUBLE NOT NULL,
      wealth DOUBLE NOT NULL,
      t INT NOT NULL DEFAULT 0,             -- tests performed in this stream
      rejections_json JSON NOT NULL,        -- 1-based indices of rejecting tests (tau_j)
      updated_at DATETIME NOT NULL,
      epoch_to_ts BIGINT NULL,              -- end of the validation window this stream spends on
      PRIMARY KEY (user_id, market)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Locked-Holdout consumption tracker. One row per (market, holdout window fingerprint).
    """
    CREATE TABLE IF NOT EXISTS app_holdout_ledger (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      market VARCHAR(48) NOT NULL,
      partition_id BIGINT NOT NULL,         -- FK to app_data_partitions
      window_fingerprint CHAR(64) NOT NULL, -- sha256 of (holdout_from, holdout_to, data hash)
      evaluations_used INT NOT NULL DEFAULT 0,
      max_evaluations INT NOT NULL,
      consumed TINYINT(1) NOT NULL DEFAULT 0,
      first_used_at DATETIME NULL,
      last_used_at DATETIME NULL,
      UNIQUE KEY uq_holdout_fp (window_fingerprint)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Frozen chronological partition boundaries, so they cannot drift between runs.
    """
    CREATE TABLE IF NOT EXISTS app_data_partitions (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      market VARCHAR(48) NOT NULL,
      research_from_ts BIGINT NOT NULL, research_to_ts BIGINT NOT NULL,
      validation_from_ts BIGINT NOT NULL, validation_to_ts BIGINT NOT NULL,
      holdout_from_ts BIGINT NOT NULL, holdout_to_ts BIGINT NOT NULL,
      embargo_seconds INT NOT NULL,
      purge_seconds INT NOT NULL,
      data_fingerprint CHAR(64) NOT NULL,   -- sha256 over the underlying candle/market rows
      frozen_at DATETIME NOT NULL,
      active TINYINT(1) NOT NULL DEFAULT 1, -- superseded partitions kept for audit, active=0
      INDEX idx_part_market (market, active, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Live position reconciliation audit trail: one open row per (user, ticker)
    # where our book (app_positions) and the user's real Kalshi account disagree.
    # Upserted each sweep and marked resolved when the disagreement clears, so it
    # is a current picture of unresolved divergence, not an append-only log.
    # exchange_qty / book_qty are SIGNED net contracts (YES positive, NO negative).
    """
    CREATE TABLE IF NOT EXISTS app_position_reconcile (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      ticker VARCHAR(128) NOT NULL,
      kind VARCHAR(16) NOT NULL,            -- untracked | book_only | size_mismatch | short
      exchange_qty INT NOT NULL,
      book_qty INT NOT NULL,
      status VARCHAR(10) NOT NULL DEFAULT 'open',  -- open | resolved
      detected_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      resolved_at DATETIME NULL,
      UNIQUE KEY uq_recon_user_ticker (user_id, ticker),
      INDEX idx_recon_status (status, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # One row per demo reconciliation sweep (app/services/demo_record.py): the user's open demo book
    # against the demo exchange's positions, read-only. `mismatches` lists the disagreeing tickers;
    # a ticker in two consecutive sweeps is a real mismatch and keeps every strategy of that user
    # off live (the live gate's demo check). Append-only, so the record since any date is auditable.
    """
    CREATE TABLE IF NOT EXISTS app_demo_reconcile_sweeps (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      checked_at DATETIME NOT NULL,
      tickers INT NOT NULL,                 -- tickers compared (non-flat in the book or on the exchange)
      mismatches JSON NULL,                 -- [{ticker, kind, exchange_qty, book_qty}], signed nets
      INDEX idx_demo_sweep_user (user_id, checked_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Execution P2: per-order latency + outcome on the real-order path (live & demo). One row per
    # exchange POST, written off the send path by the background recorder. No secrets/payload — only
    # operational fields. Index on created_at drives the windowed p50/p95/p99 + error-rate read.
    """
    CREATE TABLE IF NOT EXISTS app_order_latency (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      mode VARCHAR(8) NOT NULL,            -- live|demo
      ticker VARCHAR(128) NOT NULL,
      action VARCHAR(4) NOT NULL,          -- buy|sell
      side VARCHAR(4) NOT NULL,            -- yes|no
      qty INT NOT NULL,
      fill_qty INT NOT NULL DEFAULT 0,
      encode_sign_ms DOUBLE NULL,          -- local order-body build + RSA-PSS sign
      roundtrip_ms DOUBLE NULL,            -- request round-trip: network RTT + exchange processing
      total_ms DOUBLE NOT NULL,            -- wall-clock end-to-end submit
      http_status INT NULL,
      outcome VARCHAR(12) NOT NULL,        -- filled|partial|unfilled|blocked|error
      created_at DATETIME NOT NULL,
      INDEX idx_ol_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Page error reports from browsers (POST /api/client-errors, read grouped on /admin). Only what
    # locates a bug, cleaned by app/client_errors.py: no user id, address, query string or body.
    # Bounded: each insert prunes rows older than 7 days and all but the newest 5000 (by id).
    """
    CREATE TABLE IF NOT EXISTS app_client_errors (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at DATETIME NOT NULL,
      kind VARCHAR(12) NOT NULL,           -- error|rejection|api|view
      message VARCHAR(300) NOT NULL,
      src VARCHAR(80) NOT NULL DEFAULT '', -- script file name, no path or query
      line INT NULL,
      col INT NULL,
      path VARCHAR(120) NOT NULL,          -- page route, ids as :id, no query
      theme VARCHAR(10) NOT NULL DEFAULT '',
      ver VARCHAR(16) NOT NULL DEFAULT '', -- the bundle's build hash
      signed_in TINYINT(1) NOT NULL DEFAULT 0,
      INDEX idx_ce_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Issued NWS station forecasts of the daily max/min (app/weather_fcst_collect.py), one row per
    # (model run, settlement day). known_at_utc = runtime + the model's publication lag: research
    # and the live engine both read only rows with known_at_utc <= the frame (app/adapters/data/weather_fcst).
    """
    CREATE TABLE IF NOT EXISTS weather_forecasts (
      station VARCHAR(8) NOT NULL,         -- NWS climate station as in markets.WEATHER_STATIONS
      model VARCHAR(8) NOT NULL,           -- NBS (NBM blend) | GFS (GFS MOS)
      kind CHAR(3) NOT NULL,               -- max|min
      runtime_utc DATETIME NOT NULL,
      target_day DATE NOT NULL,            -- local climate day the max/min is for
      value_f DECIMAL(6,1) NOT NULL,
      sd_f DECIMAL(5,2) NULL,              -- NBM's XND spread; NULL for GFS MOS
      known_at_utc DATETIME NOT NULL,
      collected_at_utc DATETIME NOT NULL,
      PRIMARY KEY (station, model, kind, runtime_utc, target_day),
      INDEX idx_wf_lookup (station, kind, target_day)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Every sportsbook's two-way moneyline per game as app/sports_odds_collect.py fetched it from
    # The Odds API. collected_at_utc is the known-at time research and live both as-of join on.
    """
    CREATE TABLE IF NOT EXISTS sports_odds (
      sport VARCHAR(32) NOT NULL,          -- The Odds API sport key, e.g. basketball_nba
      event_id VARCHAR(64) NOT NULL,
      commence_utc DATETIME NOT NULL,
      home_code VARCHAR(8) NOT NULL,       -- Kalshi team codes (app/adapters/data/sports_odds.TEAMS)
      away_code VARCHAR(8) NOT NULL,
      book VARCHAR(32) NOT NULL,
      book_update_utc DATETIME NULL,
      home_price DECIMAL(8,1) NOT NULL,    -- American odds
      away_price DECIMAL(8,1) NOT NULL,
      p_home DOUBLE NOT NULL,              -- de-vigged home win probability
      collected_at_utc DATETIME NOT NULL,
      PRIMARY KEY (sport, event_id, book, collected_at_utc),
      INDEX idx_so_lookup (sport, collected_at_utc)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


DDL.extend(broker_repository.DDL)
DDL.extend(alpaca_paper_repository.DDL)
DDL.extend(kalshi_perps_repository.DDL)
DDL.extend(kalshi_perps_orders_repository.DDL)
DDL.extend(rsi_playbook.DDL)
DDL.extend(rsi_scout.DDL)
DDL.extend(tournament.DDL)
DDL.extend(rsi_repair.DDL)


def _add_column_if_missing(cur, table: str, column: str, ddl: str) -> None:
    cur.execute(
        "SELECT COUNT(*) AS c FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (table, column),
    )
    if cur.fetchone()["c"] == 0:
        cur.execute(ddl)


LEGACY_FEATURE_INDEXES = (
    # model_features_1m_builder: WHERE snapshot_minute_utc=%s AND source_status='ok'
    ("trade_quote_features_1m", "idx_tqf_minute",
     "ALTER TABLE trade_quote_features_1m ADD INDEX idx_tqf_minute (snapshot_minute_utc), ALGORITHM=INPLACE, LOCK=NONE"),
    # sim_repository.latest_feature_row / load_feature_rows: WHERE model_eligible=1 ORDER BY minute DESC
    ("model_features_1m", "idx_model_features_eligible",
     "ALTER TABLE model_features_1m ADD INDEX idx_model_features_eligible (model_eligible, snapshot_minute_utc), "
     "ALGORITHM=INPLACE, LOCK=NONE"),
)


def _table_exists(cur, table: str) -> bool:
    cur.execute("SELECT COUNT(*) AS c FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
                (table,))
    return cur.fetchone()["c"] > 0


def _add_index_if_missing(cur, table: str, index_name: str, ddl: str) -> None:
    """Idempotently add a secondary index (online, non-blocking on InnoDB). Checked via
    information_schema.STATISTICS so a re-run is a no-op, same contract as _add_column_if_missing."""
    cur.execute(
        "SELECT COUNT(*) AS c FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s",
        (table, index_name),
    )
    if cur.fetchone()["c"] == 0:
        cur.execute(ddl)


def _ensure_proposal_kind_width(cur) -> None:
    """Admit native perps proposal names on existing installations; never shrink."""
    cur.execute(
        "SELECT DATA_TYPE AS data_type, CHARACTER_MAXIMUM_LENGTH AS max_length, "
        "IS_NULLABLE AS nullable FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        ("app_proposals", "kind"),
    )
    row = cur.fetchone()
    if (not row or row["data_type"] != "varchar" or row["nullable"] != "NO"
            or type(row["max_length"]) is not int):
        raise RuntimeError("Unexpected proposal-kind schema; migration requires review.")
    if row["max_length"] < 32:
        cur.execute("ALTER TABLE app_proposals MODIFY COLUMN kind VARCHAR(32) NOT NULL")


def main() -> None:
    init_schema.main()  # market_candles and the shared pipeline tables
    conn = get_db_conn()
    with conn.cursor() as cur:
        for stmt in DDL:
            cur.execute(stmt)
        _add_column_if_missing(cur, "app_posts", "image_id", "ALTER TABLE app_posts ADD COLUMN image_id BIGINT NULL AFTER snapshot_json")
        _add_column_if_missing(cur, "app_agent_runs", "max_hypotheses", "ALTER TABLE app_agent_runs ADD COLUMN max_hypotheses INT NULL")
        _add_column_if_missing(cur, "app_agent_runs", "run_forever", "ALTER TABLE app_agent_runs ADD COLUMN run_forever TINYINT(1) NOT NULL DEFAULT 0")
        # The LLM the user picked for this run (a models_catalog key). NULL = server default (Sonnet).
        _add_column_if_missing(cur, "app_agent_runs", "model", "ALTER TABLE app_agent_runs ADD COLUMN model VARCHAR(48) NULL")
        # "Dig deeper": a research run seeded from a passed strategy (branch/refine its mechanism).
        # NULL = a fresh idea; non-NULL = the parent strategy this line continues from. The branched
        # strategies carry parent_id=seed_strategy_id so the discovery tree records the lineage.
        _add_column_if_missing(cur, "app_agent_runs", "seed_strategy_id", "ALTER TABLE app_agent_runs ADD COLUMN seed_strategy_id BIGINT NULL")
        # Emergency-recovery checkpoint: a research run's exploration progress (chunks gated so far,
        # the in-progress chunk's developed+frozen theses, round cursor, resolved market/lookback), so
        # a reclaimed run resumes from here instead of re-spending the model credits already explored.
        # NULL = a run that has not checkpointed yet. resume_count bounds how many times a broken run
        # is reclaimed before it fails for good (repository.MAX_RESUMES / TAU_RUN_MAX_RESUMES).
        _add_column_if_missing(cur, "app_agent_runs", "checkpoint_json", "ALTER TABLE app_agent_runs ADD COLUMN checkpoint_json JSON NULL")
        _add_column_if_missing(cur, "app_agent_runs", "resume_count", "ALTER TABLE app_agent_runs ADD COLUMN resume_count INT NOT NULL DEFAULT 0")
        # Delegation seam: a research run the AUTOPILOT opened from a high-level brief (a market +
        # a short angle), not a user-authored verbatim thesis. The proposer treats a brief as a
        # starting DIRECTION and writes the hypotheses itself. 0 = a faithful user idea (Research page).
        _add_column_if_missing(cur, "app_agent_runs", "brief", "ALTER TABLE app_agent_runs ADD COLUMN brief TINYINT(1) NOT NULL DEFAULT 0")
        # Tau-RSI discovery tree: which prior hypothesis this one built on (NULL = root). Nullable
        # + unused for now (P1); the replay simulator and self-evolving policy populate it later.
        _add_column_if_missing(cur, "app_strategies", "parent_id", "ALTER TABLE app_strategies ADD COLUMN parent_id BIGINT NULL")
        # Robust experiment<->strategy link: the full pipeline stamps the strategy with the id of
        # the experiment it was pre-registered under (set in _gate_and_save). The research-paper
        # page resolves by this first, so a strategy always renders ITS own experiment even after
        # a re-hit re-points app_experiments.strategy_id at a later strategy row. NULL = a legacy
        # or loose-path (backtest-only) strategy that never went through the gatekeeper.
        _add_column_if_missing(cur, "app_strategies", "experiment_id", "ALTER TABLE app_strategies ADD COLUMN experiment_id BIGINT NULL")
        # series_with_candles() ("which series have a backtest surface") runs on EVERY authenticated
        # page load via /api/me, as SELECT DISTINCT series_ticker FROM hist_markets WHERE candles_done=1.
        # Without an index on candles_done it full-scans hist_markets (~450k rows, ~6s, up to ~45s under
        # load) and the SPA blocks all rendering on /api/me -> blank page. This (candles_done, series_ticker)
        # index makes it a loose index scan in ms AND removes that repeated full scan from the DB's load.
        _add_index_if_missing(cur, "hist_markets", "idx_hist_candles_series",
                              "ALTER TABLE hist_markets ADD INDEX idx_hist_candles_series (candles_done, series_ticker)")
        # history_freshness() (the dashboard's data-freshness badge) takes MAX(close_time) per series
        # over candles_done=1. The index above finds the rows but not close_time, so it read every
        # settled market (12-14s per /api/dashboard on 2026-10-24 after the history backfill).
        # With close_time in the index it's a loose index scan: one probe per series. The backtest
        # candle load (series_ticker=... AND close_time range AND candles_done=1) uses it too.
        _add_index_if_missing(cur, "hist_markets", "idx_hist_done_series_close",
                              "ALTER TABLE hist_markets ADD INDEX idx_hist_done_series_close "
                              "(candles_done, series_ticker, close_time), ALGORITHM=INPLACE, LOCK=NONE")
        # Cross-day generalization breakdown (per-day/per-fold) the research-paper folds strip renders.
        _add_column_if_missing(cur, "app_experiment_results", "folds_json", "ALTER TABLE app_experiment_results ADD COLUMN folds_json JSON NULL AFTER equity_curve_json")
        # Cross-contract strategies spend from a SHARED FDR stream keyed on a combined key
        # ('btc_daily+eth_daily'), which overruns the old VARCHAR(16). Widen the market key
        # columns to fit. MODIFY is idempotent, so this is safe to re-run.
        for _tbl in ("app_experiments", "app_fdr_state", "app_holdout_ledger", "app_data_partitions"):
            cur.execute("ALTER TABLE %s MODIFY market VARCHAR(48) NOT NULL" % _tbl)
        # Evidence epoch for the LORD++ stream: the end of the validation window it spends on. A
        # fresh stream starts only once validation has fully rolled past it (gatekeeper._lord_state).
        _add_column_if_missing(cur, "app_fdr_state", "epoch_to_ts", "ALTER TABLE app_fdr_state ADD COLUMN epoch_to_ts BIGINT NULL")
        # Waitlist hygiene: drop any waitlist rows for emails that already have an account
        # (case/space-insensitive), so a signed-up user never lingers on the waitlist display.
        cur.execute("DELETE w FROM app_waitlist w JOIN app_users u "
                    "ON LOWER(TRIM(u.email))=LOWER(TRIM(w.email))")
        _add_column_if_missing(cur, "app_posts", "edited_at", "ALTER TABLE app_posts ADD COLUMN edited_at DATETIME NULL")
        _add_column_if_missing(cur, "app_stripe_customers", "reload_amount", "ALTER TABLE app_stripe_customers ADD COLUMN reload_amount DECIMAL(10,2) NOT NULL DEFAULT 20.00")
        _add_column_if_missing(cur, "app_stripe_customers", "reload_threshold", "ALTER TABLE app_stripe_customers ADD COLUMN reload_threshold DECIMAL(10,2) NOT NULL DEFAULT 5.00")
        # Live mark-to-market: the engine stamps the current YES bid on open positions each
        # decision tick (reusing the book it already fetches) so the web can show unrealized P&L.
        _add_column_if_missing(cur, "app_positions", "mark_price", "ALTER TABLE app_positions ADD COLUMN mark_price DECIMAL(10,4) NULL")
        _add_column_if_missing(cur, "app_positions", "mark_ts", "ALTER TABLE app_positions ADD COLUMN mark_ts DATETIME NULL")
        # The latest entry scan per deployment (spec.entry_scan): why it did or didn't buy last decision.
        _add_column_if_missing(cur, "app_deployments", "last_scan_json", "ALTER TABLE app_deployments ADD COLUMN last_scan_json JSON NULL")
        _add_column_if_missing(cur, "app_deployments", "last_scan_at", "ALTER TABLE app_deployments ADD COLUMN last_scan_at DATETIME NULL")
        # Early exits scored against holding to settlement (engine.score_early_exits): what the
        # contract settled at and what the position would have made held to the end.
        _add_column_if_missing(cur, "app_positions", "settle_result", "ALTER TABLE app_positions ADD COLUMN settle_result VARCHAR(4) NULL")
        _add_column_if_missing(cur, "app_positions", "hold_pnl", "ALTER TABLE app_positions ADD COLUMN hold_pnl DECIMAL(14,4) NULL")
        # Per-position close claim (EXECUTION_RISK_HARDENING P0-3): the order-placing risk sweeps
        # (drawdown force-sell) lease a position before sending a real close, so two engines can
        # never both sell the same position into an unintended short. Mirrors claim_decision.
        _add_column_if_missing(cur, "app_positions", "close_claim", "ALTER TABLE app_positions ADD COLUMN close_claim VARCHAR(48) NULL")
        _add_column_if_missing(cur, "app_positions", "close_claim_ts", "ALTER TABLE app_positions ADD COLUMN close_claim_ts DATETIME NULL")
        # Strategy sharing: a shared strategy is COPIED into the recipient's inventory (so it is
        # theirs to deploy and is not revocable). These columns mark the copy's origin.
        _add_column_if_missing(cur, "app_strategies", "shared_from_user_id", "ALTER TABLE app_strategies ADD COLUMN shared_from_user_id BIGINT NULL")
        _add_column_if_missing(cur, "app_strategies", "shared_src_id", "ALTER TABLE app_strategies ADD COLUMN shared_src_id BIGINT NULL")
        # Community email digest: opt-out flag + a per-recipient cooldown timestamp so a flurry of
        # posts can't flood anyone. (Delivery itself waits on SES production access.)
        _add_column_if_missing(cur, "app_users", "email_opt_out", "ALTER TABLE app_users ADD COLUMN email_opt_out TINYINT(1) NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "app_users", "last_community_email_at", "ALTER TABLE app_users ADD COLUMN last_community_email_at DATETIME NULL")
        # Unique @-handle for community mentions. Nullable; uniqueness enforced in assign_username.
        _add_column_if_missing(cur, "app_users", "username", "ALTER TABLE app_users ADD COLUMN username VARCHAR(32) NULL")
        # Human-readable description of what an evolved policy changed + the score it beat,
        # so the research page can explain the self-improvement in plain English.
        _add_column_if_missing(cur, "app_policies", "summary", "ALTER TABLE app_policies ADD COLUMN summary VARCHAR(400) NULL")
        _add_column_if_missing(cur, "app_policies", "base_score", "ALTER TABLE app_policies ADD COLUMN base_score DOUBLE NULL")
        # Which frontend the user picked: 'tau' (default, feature-complete) or 'meridian' (redesign).
        _add_column_if_missing(cur, "app_users", "ui_theme", "ALTER TABLE app_users ADD COLUMN ui_theme VARCHAR(16) NOT NULL DEFAULT 'tau'")
        # Live autopilot: OFF by default; when on (and the server live switch + a Kalshi key are
        # present) the agent may promote paper-passed strategies of ANY side (YES or NO, once
        # NO_SIDE_LIVE_ENABLED is on) to live within the user's own caps. A per-user daily
        # live-loss limit auto-disables it (kill switch).
        _add_column_if_missing(cur, "app_users", "autopilot_live", "ALTER TABLE app_users ADD COLUMN autopilot_live TINYINT(1) NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "app_users", "autopilot_daily_loss_limit", "ALTER TABLE app_users ADD COLUMN autopilot_daily_loss_limit DECIMAL(10,2) NOT NULL DEFAULT 50.00")
        # Demo (sandbox) is app-controlled money: real fills on Kalshi's demo exchange applied to a
        # capital WE set, never the real demo-account balance. `demo_capital` is the reloadable
        # starting capital; `demo_pnl_base` is the realized-P&L snapshot captured at the last reload,
        # so demo P&L shown resets to 0 on reload (equity = capital + realized_since_reload).
        _add_column_if_missing(cur, "app_users", "demo_capital", "ALTER TABLE app_users ADD COLUMN demo_capital DECIMAL(14,4) NOT NULL DEFAULT 1000.0000")
        _add_column_if_missing(cur, "app_users", "demo_pnl_base", "ALTER TABLE app_users ADD COLUMN demo_pnl_base DECIMAL(14,4) NOT NULL DEFAULT 0.0000")
        _add_column_if_missing(cur, "app_experiments", "data_provenance_json", "ALTER TABLE app_experiments ADD COLUMN data_provenance_json JSON NULL AFTER cost_assumptions_json")
        # Risk force-sell + portfolio caps (per-user, conservative defaults): when a deployment's
        # drawdown from its high-water mark exceeds drawdown_limit_pct of its capital, the engine
        # force-closes its open positions (via each mode's own exit path) and pauses it. The two
        # portfolio caps block NEW entries that would push the user past max_open_positions open
        # positions or max_open_notional dollars of open entry notional. drawdown_limit_pct=0 disables
        # the force-sell for that user. Tunable per user; UI wiring is deferred (columns only for now).
        _add_column_if_missing(cur, "app_users", "drawdown_limit_pct", "ALTER TABLE app_users ADD COLUMN drawdown_limit_pct DECIMAL(6,2) NOT NULL DEFAULT 25.00")
        # Position-level stop-loss: force-close a deployment when any OPEN position is down more than
        # this percent of its OWN cost (deployed capital), independent of the whole-capital drawdown
        # guard above — catches a small position that craters (large % of its cost, tiny % of capital).
        # Default 40%; 0 disables. Tunable per user; UI wiring deferred (column only for now).
        _add_column_if_missing(cur, "app_users", "position_stop_pct", "ALTER TABLE app_users ADD COLUMN position_stop_pct DECIMAL(6,2) NOT NULL DEFAULT 40.00")
        _add_column_if_missing(cur, "app_users", "max_open_positions", "ALTER TABLE app_users ADD COLUMN max_open_positions INT NOT NULL DEFAULT 20")
        _add_column_if_missing(cur, "app_users", "max_open_notional", "ALTER TABLE app_users ADD COLUMN max_open_notional DECIMAL(12,2) NOT NULL DEFAULT 1000.00")
        # Per-user execution-control overrides for the live kernel (the co-pilot's `set_exec` action
        # tunes these within a safe envelope). NULL = fall back to the global KALSHI_MAX_* env knob.
        # Each can only shrink or abandon an order and never blocks an exit, so a set value is always
        # a tightening relative to "no cap"; agent-set values are clamped to EXEC_BOUNDS in agent.py.
        _add_column_if_missing(cur, "app_users", "exec_max_book_fraction", "ALTER TABLE app_users ADD COLUMN exec_max_book_fraction DECIMAL(6,4) NULL")
        _add_column_if_missing(cur, "app_users", "exec_max_entry_spread", "ALTER TABLE app_users ADD COLUMN exec_max_entry_spread DECIMAL(6,4) NULL")
        _add_column_if_missing(cur, "app_users", "exec_max_order_notional", "ALTER TABLE app_users ADD COLUMN exec_max_order_notional DECIMAL(12,2) NULL")
        # Autopilot operating plan: a small durable JSON (goals/agenda/deployments/posture) the
        # review reads + rewrites each turn, so reviews are coherent across time instead of
        # independent one-shots. NULL = no plan yet. Bounded in repository.set_autopilot_plan.
        _add_column_if_missing(cur, "app_users", "autopilot_plan", "ALTER TABLE app_users ADD COLUMN autopilot_plan JSON NULL")
        # The model key (from models_catalog) the autopilot's own research/review/chat runs use when
        # the run didn't pick one. NULL = the catalog default. Lets the user route autopilot to a
        # higher-quota model (e.g. Sonnet) so Bedrock throttling stops killing research runs.
        _add_column_if_missing(cur, "app_users", "autopilot_model", "ALTER TABLE app_users ADD COLUMN autopilot_model VARCHAR(64) NULL")
        # The user's standing market focus for the autopilot (JSON list of family names or market
        # keys; NULL = no focus). Binding: research, deploys and the paper funnel stay inside it.
        _add_column_if_missing(cur, "app_users", "autopilot_focus", "ALTER TABLE app_users ADD COLUMN autopilot_focus VARCHAR(255) NULL")
        # Proposal payload: the clamped values a set_risk / set_exec proposal applies on approval
        # (deploy/adjust/pause/resume carry no payload). NULL for the older kinds.
        _add_column_if_missing(cur, "app_proposals", "payload", "ALTER TABLE app_proposals ADD COLUMN payload JSON NULL")
        _ensure_proposal_kind_width(cur)
        # Slow log, 2026-10-25: the scoreboard's verdict read and the proposer's dropped-thesis
        # reads (kind='verdict' AND run_id IN (...)) scanned all ~560k event rows, 3-8s each, since
        # (run_id, id) can't filter on kind and a busy run logs thousands of events.
        _add_index_if_missing(cur, "app_agent_events", "idx_events_run_kind",
                              "ALTER TABLE app_agent_events ADD INDEX idx_events_run_kind (run_id, kind, id), "
                              "ALGORITHM=INPLACE, LOCK=NONE")
        # The run page's "Last check" line (latest_dream_event, once a minute per user) looks for
        # 'Dreaming:' / 'Research policy evolved' lines and walked every event of every run the user
        # has: ~850ms at 6,000 runs and 600k events. A message prefix lets those two LIKE prefixes
        # range-scan the few dream lines instead (~3ms). The order path never writes this table.
        _add_index_if_missing(cur, "app_agent_events", "idx_events_message",
                              "ALTER TABLE app_agent_events ADD INDEX idx_events_message (message(24)), "
                              "ALGORITHM=INPLACE, LOCK=NONE")
        # The autopilot status poll sums the week's research debits (research_spent_since); without
        # this it walks the user's whole ledger through idx_credit_user on every 20s poll.
        _add_index_if_missing(cur, "app_credit_ledger", "idx_credit_user_kind_time",
                              "ALTER TABLE app_credit_ledger ADD INDEX idx_credit_user_kind_time (user_id, kind, created_at), "
                              "ALGORITHM=INPLACE, LOCK=NONE")
        # The run page (2s poll) and the research list sum each run's debits (runs_spent).
        _add_index_if_missing(cur, "app_credit_ledger", "idx_credit_run_kind",
                              "ALTER TABLE app_credit_ledger ADD INDEX idx_credit_run_kind (run_id, kind), "
                              "ALGORITHM=INPLACE, LOCK=NONE")
        # /api/me, the billing gate and the admin list sum the user's whole ledger (credit_balance).
        # Without amount_usd in an index that SUM reads every ledger row of the table; with it, the
        # same SUM reads only the user's index entries. The value is unchanged: same rows, same
        # DECIMAL(14,6) sum. The ledger is append-only (add_credit is its only write).
        _add_index_if_missing(cur, "app_credit_ledger", "idx_credit_user_amount",
                              "ALTER TABLE app_credit_ledger ADD INDEX idx_credit_user_amount (user_id, amount_usd), "
                              "ALGORITHM=INPLACE, LOCK=NONE")
        # The Strategies page counts and lists each strategy's active deployments (EXISTS / COUNT on
        # d.strategy_id), one probe per strategy. With no index on strategy_id every probe walked the
        # whole table: 85ms for 700 strategies against 320 deployments. The engine's per-tick writes
        # (last_decision_ts, the scan) touch neither column; status changes a few times in a life.
        _add_index_if_missing(cur, "app_deployments", "idx_dep_strategy",
                              "ALTER TABLE app_deployments ADD INDEX idx_dep_strategy (strategy_id, status), "
                              "ALGORITHM=INPLACE, LOCK=NONE")
        # Same slow log: the collector box's per-minute reads of the legacy feature tables
        # (data_pipeline.init_schema owns them) full-scanned them, ~5s each, two every minute.
        # They are added here because only this migration runs on every deploy.
        for table, index_name, ddl in LEGACY_FEATURE_INDEXES:
            if _table_exists(cur, table):
                _add_index_if_missing(cur, table, index_name, ddl)
        # Backfill any user still missing a handle (idempotent: only touches NULLs).
        from app import repository as _repo
        cur.execute("SELECT id, email, name FROM app_users WHERE username IS NULL OR username=''")
        for u in cur.fetchall():
            _repo.assign_username(cur, u["id"], u["email"], u["name"])
        # One-time migration: seed spot_candles_1m with existing BTC history so the
        # generalized backtester has BTC's full price path. Idempotent (INSERT IGNORE on PK).
        cur.execute(
            """INSERT IGNORE INTO spot_candles_1m (symbol, start_ts, open, high, low, close, volume)
               SELECT 'BTC-USD', start_ts, open, high, low, close, volume FROM btc_candles_1m"""
        )
    conn.close()
    print("App schema initialized.")


if __name__ == "__main__":
    main()
