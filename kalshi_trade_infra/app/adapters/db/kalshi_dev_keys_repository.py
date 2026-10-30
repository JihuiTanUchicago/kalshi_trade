"""Per-user Kalshi demo (sandbox) API key storage."""
from __future__ import annotations

from typing import Dict, Optional

from app.adapters.db.sql import now_utc


# Exact mirror of the live-key accessors above, against app_kalshi_dev_keys. The
# demo execution path reads ONLY these, so a user's demo orders can never pick up
# their live key.


def set_kalshi_dev_key(cur, user_id: int, key_id: str, private_key_enc: bytes) -> None:
    cur.execute(
        """INSERT INTO app_kalshi_dev_keys (user_id, key_id, private_key_enc, created_at) VALUES (%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE key_id=VALUES(key_id), private_key_enc=VALUES(private_key_enc),
             created_at=VALUES(created_at)""",
        (user_id, key_id, private_key_enc, now_utc()),
    )


def get_kalshi_dev_key(cur, user_id: int) -> Optional[Dict]:
    cur.execute("SELECT key_id, private_key_enc, created_at FROM app_kalshi_dev_keys WHERE user_id=%s", (user_id,))
    return cur.fetchone()


def has_kalshi_dev_key(cur, user_id: int) -> bool:
    """Whether a demo key is saved, for a page that only says so: one primary-key probe that selects a
    constant, never the key's id or its encrypted bytes (get_kalshi_dev_key, for the paths that use the key)."""
    cur.execute("SELECT 1 AS present FROM app_kalshi_dev_keys WHERE user_id=%s LIMIT 1", (user_id,))
    return cur.fetchone() is not None


def delete_kalshi_dev_key(cur, user_id: int) -> None:
    cur.execute("DELETE FROM app_kalshi_dev_keys WHERE user_id=%s", (user_id,))
