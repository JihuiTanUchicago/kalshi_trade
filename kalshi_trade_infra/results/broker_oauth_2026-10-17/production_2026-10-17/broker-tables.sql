CREATE TABLE IF NOT EXISTS app_broker_connections (
      user_id BIGINT NOT NULL,
      provider VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      environment VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      tokens_enc MEDIUMBLOB NULL,
      metadata_json JSON NULL,
      pending_state_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
      pending_session_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
      pending_expires_at DATETIME NULL,
      pending_claimed_at DATETIME NULL,
      created_at DATETIME NOT NULL,
      connected_at DATETIME NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (user_id, provider, environment)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_broker_oauth_attempts (
      state_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
      user_id BIGINT NOT NULL,
      provider VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      environment VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      session_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      private_enc MEDIUMBLOB NOT NULL,
      created_at DATETIME NOT NULL,
      expires_at DATETIME NOT NULL,
      INDEX idx_broker_attempt_owner (user_id, provider, environment),
      INDEX idx_broker_attempt_expiry (expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
