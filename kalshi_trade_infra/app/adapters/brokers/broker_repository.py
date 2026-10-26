"""Per-user broker connections and single-use OAuth state persistence.

Call each mutator inside ``app.repository.transaction``. They all lock the
existing app_users row first, serializing even the first connection and a delete
that races a callback. Release the transaction before any provider HTTP call.
Only ciphertext reaches secret columns; metadata must already be projected by
the service. Public listing never selects ciphertext or OAuth state hashes.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

from app.repository import now_utc

_CONTEXT_PART = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_MAX_BLOB_BYTES = 65_565  # Vault version + nonce + max JSON + GCM tag.
_MAX_METADATA_BYTES = 8192

DDL = [
    """
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def _context(user_id: int, provider: str, environment: str | None = None) -> None:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("Invalid broker connection owner.")
    if any(not isinstance(value, str) or not _CONTEXT_PART.fullmatch(value)
           for value in (provider,) + (() if environment is None else (environment,))):
        raise ValueError("Invalid broker connection context.")


def _hash(value: str) -> None:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("Broker OAuth state and session identifiers must be SHA-256 hashes.")


def _blob(value: bytes) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)) or not 29 <= len(value) <= _MAX_BLOB_BYTES:
        raise ValueError("Invalid encrypted broker credentials.")
    return bytes(value)


def _lock_user(cur: Any, user_id: int) -> None:
    # A stable row exists before any provider connection, unlike a row lock on
    # the connection itself. Always use the same lock order in every mutation.
    cur.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (user_id,))
    if cur.fetchone() is None:
        raise ValueError("Broker connection owner does not exist.")


def _decode_row(row: dict | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    value = result.pop("metadata_json", None)
    result["metadata"] = (json.loads(value) if isinstance(value, (str, bytes)) else value) or {}
    return result


def list_connections(cur: Any, user_id: int) -> list[dict]:
    """List metadata and connection flags only; never fetch tokens or state."""
    _context(user_id, "broker")
    cur.execute(
        """SELECT provider, environment, (tokens_enc IS NOT NULL) AS connected,
                  (pending_state_hash IS NOT NULL AND pending_expires_at > %s) AS pending,
                  metadata_json, connected_at, updated_at
           FROM app_broker_connections WHERE user_id=%s ORDER BY provider, environment""",
        (now_utc(), user_id),
    )
    rows = []
    for row in cur.fetchall():
        item = _decode_row(row)
        item["connected"] = bool(item["connected"])
        item["pending"] = bool(item["pending"])
        rows.append(item)
    return rows


def get_connection(cur: Any, user_id: int, provider: str, environment: str) -> dict | None:
    """Internal read including encrypted tokens. Do not return this row to HTTP."""
    _context(user_id, provider, environment)
    cur.execute(
        """SELECT user_id, provider, environment, tokens_enc, metadata_json,
                  pending_state_hash, pending_session_hash, pending_expires_at,
                  pending_claimed_at,
                  created_at, connected_at, updated_at
           FROM app_broker_connections WHERE user_id=%s AND provider=%s AND environment=%s""",
        (user_id, provider, environment),
    )
    return _decode_row(cur.fetchone())


def save_attempt(cur: Any, user_id: int, provider: str, environment: str,
                 state_hash: str, session_hash: str, private_enc: bytes,
                 ttl_seconds: int = 600) -> None:
    """Replace only this connection's pending attempt, preserving usable tokens."""
    _context(user_id, provider, environment)
    _hash(state_hash)
    _hash(session_hash)
    private_enc = _blob(private_enc)
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 900:
        raise ValueError("Broker OAuth attempts must expire within 15 minutes.")
    _lock_user(cur, user_id)
    now = now_utc()
    expires_at = now + timedelta(seconds=ttl_seconds)
    cur.execute(
        "DELETE FROM app_broker_oauth_attempts WHERE user_id=%s AND provider=%s AND environment=%s",
        (user_id, provider, environment),
    )
    cur.execute(
        """INSERT INTO app_broker_oauth_attempts
             (state_hash, user_id, provider, environment, session_hash, private_enc, created_at, expires_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (state_hash, user_id, provider, environment, session_hash, private_enc, now, expires_at),
    )
    cur.execute(
        """INSERT INTO app_broker_connections
             (user_id, provider, environment, tokens_enc, metadata_json,
              pending_state_hash, pending_session_hash, pending_expires_at, pending_claimed_at,
              created_at, connected_at, updated_at)
           VALUES (%s,%s,%s,NULL,NULL,%s,%s,%s,NULL,%s,NULL,%s)
           ON DUPLICATE KEY UPDATE pending_state_hash=VALUES(pending_state_hash),
             pending_session_hash=VALUES(pending_session_hash),
             pending_expires_at=VALUES(pending_expires_at), pending_claimed_at=NULL,
             updated_at=VALUES(updated_at)""",
        (user_id, provider, environment, state_hash, session_hash, expires_at, now, now),
    )


def consume_attempt(cur: Any, user_id: int, provider: str, state_hash: str,
                    session_hash: str) -> dict | None:
    """Consume current, unexpired, session-bound state once, before HTTP exchange."""
    _context(user_id, provider)
    _hash(state_hash)
    _hash(session_hash)
    _lock_user(cur, user_id)
    now = now_utc()
    cur.execute(
        """SELECT a.state_hash, a.user_id, a.provider, a.environment, a.session_hash,
                  a.private_enc, a.created_at, a.expires_at
           FROM app_broker_oauth_attempts a JOIN app_broker_connections c
             ON c.user_id=a.user_id AND c.provider=a.provider AND c.environment=a.environment
           WHERE a.user_id=%s AND a.provider=%s AND a.state_hash=%s AND a.session_hash=%s
             AND a.expires_at > %s AND c.pending_state_hash=a.state_hash
             AND c.pending_session_hash=a.session_hash AND c.pending_expires_at > %s
             AND c.pending_claimed_at IS NULL
           FOR UPDATE""",
        (user_id, provider, state_hash, session_hash, now, now),
    )
    row = cur.fetchone()
    if row is None:
        return None
    cur.execute(
        """DELETE FROM app_broker_oauth_attempts
           WHERE user_id=%s AND provider=%s AND state_hash=%s AND session_hash=%s AND expires_at > %s""",
        (user_id, provider, state_hash, session_hash, now),
    )
    if cur.rowcount != 1:
        return None
    cur.execute(
        """UPDATE app_broker_connections SET pending_claimed_at=%s
           WHERE user_id=%s AND provider=%s AND environment=%s
             AND pending_state_hash=%s AND pending_session_hash=%s
             AND pending_claimed_at IS NULL AND pending_expires_at > %s""",
        (now, user_id, provider, row["environment"], state_hash, session_hash, now),
    )
    if cur.rowcount != 1:
        return None
    return dict(row)


def complete_attempt(cur: Any, user_id: int, provider: str, environment: str,
                     state_hash: str, tokens_enc: bytes, metadata: dict) -> bool:
    """Store tokens only if the consumed attempt is still the latest connection."""
    _context(user_id, provider, environment)
    _hash(state_hash)
    tokens_enc = _blob(tokens_enc)
    if not isinstance(metadata, dict):
        raise ValueError("Broker metadata must be a JSON object.")
    try:
        encoded = json.dumps(metadata, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError("Broker metadata must be a JSON object.") from None
    if len(encoded.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise ValueError("Broker metadata exceeds the storage limit.")
    _lock_user(cur, user_id)
    now = now_utc()
    cur.execute(
        """UPDATE app_broker_connections
           SET tokens_enc=%s, metadata_json=%s, connected_at=%s, updated_at=%s,
               pending_state_hash=NULL, pending_session_hash=NULL, pending_expires_at=NULL,
               pending_claimed_at=NULL
           WHERE user_id=%s AND provider=%s AND environment=%s
             AND pending_state_hash=%s AND pending_expires_at > %s
             AND pending_claimed_at IS NOT NULL""",
        (tokens_enc, encoded, now, now, user_id, provider, environment, state_hash, now),
    )
    return cur.rowcount == 1


def disconnect(cur: Any, user_id: int, provider: str, environment: str) -> bool:
    """Delete credentials and pending states, fencing any callback in flight."""
    _context(user_id, provider, environment)
    _lock_user(cur, user_id)
    cur.execute(
        "DELETE FROM app_broker_oauth_attempts WHERE user_id=%s AND provider=%s AND environment=%s",
        (user_id, provider, environment),
    )
    cur.execute(
        "DELETE FROM app_broker_connections WHERE user_id=%s AND provider=%s AND environment=%s",
        (user_id, provider, environment),
    )
    return cur.rowcount == 1
