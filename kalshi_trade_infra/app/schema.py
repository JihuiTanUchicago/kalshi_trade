"""Tables for the Tau customer app. Additive and idempotent, like
data_pipeline/init_schema.py: `python -m app.schema`.

Money is DECIMAL, never FLOAT. Every paper-cash movement is a row in
app_ledger and the balance is their sum, so a balance can always be explained
line by line and two writers cannot lose an update to each other.
"""
from data_pipeline import init_schema
from data_pipeline.common import get_db_conn

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
      INDEX idx_events_run (run_id, id)
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
      kind VARCHAR(12) NOT NULL,
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
]


def _add_column_if_missing(cur, table: str, column: str, ddl: str) -> None:
    cur.execute(
        "SELECT COUNT(*) AS c FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (table, column),
    )
    if cur.fetchone()["c"] == 0:
        cur.execute(ddl)


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
        # Tau-RSI discovery tree: which prior hypothesis this one built on (NULL = root). Nullable
        # + unused for now (P1); the replay simulator and self-evolving policy populate it later.
        _add_column_if_missing(cur, "app_strategies", "parent_id", "ALTER TABLE app_strategies ADD COLUMN parent_id BIGINT NULL")
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
