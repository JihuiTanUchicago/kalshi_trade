"""Broker repository contract against a stateful fake cursor, never a real DB.

The fake implements only these query shapes and records SQL ownership/locking
predicates. Race tests interleave independently committed repository operations
around the provider HTTP boundary, where no DB lock may be held.
"""
import copy
import hashlib
import json
from datetime import datetime, timedelta

import pytest

from app.adapters.brokers import broker_repository as repo

NOW = datetime(2026, 10, 17, 12, 0, 0)
CIPHER = b"\x01" + b"synthetic-ciphertext" * 3


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class BrokerCursor:
    def __init__(self):
        self.users = {1, 2}
        self.connections = {}
        self.attempts = {}
        self.calls = []
        self.rowcount = 0
        self._rows = []

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        self.rowcount = 0
        self._rows = []
        if sql == "SELECT id FROM app_users WHERE id=%s FOR UPDATE":
            self._rows = [{"id": params[0]}] if params[0] in self.users else []
        elif sql.startswith("DELETE FROM app_broker_oauth_attempts WHERE user_id=%s AND provider=%s AND environment=%s"):
            uid, provider, env = params
            for key, row in list(self.attempts.items()):
                if (row["user_id"], row["provider"], row["environment"]) == (uid, provider, env):
                    del self.attempts[key]
                    self.rowcount += 1
        elif sql.startswith("INSERT INTO app_broker_oauth_attempts"):
            state, uid, provider, env, session, blob, created, expires = params
            assert state not in self.attempts
            self.attempts[state] = dict(state_hash=state, user_id=uid, provider=provider,
                                        environment=env, session_hash=session, private_enc=blob,
                                        created_at=created, expires_at=expires)
            self.rowcount = 1
        elif sql.startswith("INSERT INTO app_broker_connections"):
            uid, provider, env, state, session, expires, created, updated = params
            row = self.connections.setdefault((uid, provider, env), dict(
                user_id=uid, provider=provider, environment=env, tokens_enc=None, metadata_json=None,
                created_at=created, connected_at=None))
            row.update(pending_state_hash=state, pending_session_hash=session,
                       pending_expires_at=expires, pending_claimed_at=None, updated_at=updated)
            self.rowcount = 1
        elif sql.startswith("SELECT a.state_hash"):
            uid, provider, state, session, now, pending_now = params
            row = self.attempts.get(state)
            if row:
                connection = self.connections.get((row["user_id"], row["provider"], row["environment"]))
                if (row["user_id"] == uid and row["provider"] == provider and row["session_hash"] == session
                        and row["expires_at"] > now and connection
                        and connection["pending_state_hash"] == state
                        and connection["pending_session_hash"] == session
                        and connection["pending_expires_at"] > pending_now
                        and connection["pending_claimed_at"] is None):
                    self._rows = [dict(row)]
        elif sql.startswith("DELETE FROM app_broker_oauth_attempts"):
            uid, provider, state, session, now = params
            row = self.attempts.get(state)
            if row and row["user_id"] == uid and row["provider"] == provider and row["session_hash"] == session and row["expires_at"] > now:
                del self.attempts[state]
                self.rowcount = 1
        elif sql.startswith("UPDATE app_broker_connections SET pending_claimed_at"):
            claimed, uid, provider, env, state, session, now = params
            row = self.connections.get((uid, provider, env))
            if (row and row["pending_state_hash"] == state and row["pending_session_hash"] == session
                    and row["pending_expires_at"] > now and row["pending_claimed_at"] is None):
                row["pending_claimed_at"] = claimed
                self.rowcount = 1
        elif sql.startswith("UPDATE app_broker_connections"):
            blob, metadata, connected, updated, uid, provider, env, state, now = params
            row = self.connections.get((uid, provider, env))
            if (row and row["pending_state_hash"] == state and row["pending_expires_at"] > now
                    and row["pending_claimed_at"] is not None):
                row.update(tokens_enc=blob, metadata_json=metadata, connected_at=connected,
                           updated_at=updated, pending_state_hash=None, pending_session_hash=None,
                           pending_expires_at=None, pending_claimed_at=None)
                self.rowcount = 1
        elif sql.startswith("DELETE FROM app_broker_connections"):
            if self.connections.pop(tuple(params), None) is not None:
                self.rowcount = 1
        elif sql.startswith("SELECT user_id, provider, environment, tokens_enc"):
            row = self.connections.get(tuple(params))
            self._rows = [dict(row)] if row else []
        elif sql.startswith("SELECT provider, environment, (tokens_enc IS NOT NULL)"):
            now, uid = params
            for (owner, provider, env), row in sorted(self.connections.items()):
                if owner == uid:
                    self._rows.append(dict(provider=provider, environment=env,
                        connected=row["tokens_enc"] is not None,
                        pending=row["pending_state_hash"] is not None and row["pending_expires_at"] > now,
                        metadata_json=row["metadata_json"], connected_at=row["connected_at"],
                        updated_at=row["updated_at"]))
        else:
            raise AssertionError("Unexpected SQL shape: " + sql)

    def fetchone(self):
        return copy.deepcopy(self._rows[0]) if self._rows else None

    def fetchall(self):
        return copy.deepcopy(self._rows)


@pytest.fixture
def cur(monkeypatch):
    monkeypatch.setattr(repo, "now_utc", lambda: NOW)
    return BrokerCursor()


def start(cur, uid=1, provider="alpaca", env="paper", state="first", session="session"):
    repo.save_attempt(cur, uid, provider, env, hashed(state), hashed(session), CIPHER)
    return hashed(state)


def finish(cur, uid=1, provider="alpaca", env="paper", state="first", session="session"):
    assert repo.consume_attempt(cur, uid, provider, hashed(state), hashed(session))
    return repo.complete_attempt(cur, uid, provider, env, hashed(state), CIPHER, {"scope": "read"})


def test_single_use_callback_then_metadata_only_listing(cur):
    state = start(cur)
    attempt = repo.consume_attempt(cur, 1, "alpaca", state, hashed("session"))
    assert attempt["environment"] == "paper" and attempt["private_enc"] == CIPHER
    assert repo.consume_attempt(cur, 1, "alpaca", state, hashed("session")) is None
    assert repo.complete_attempt(cur, 1, "alpaca", "paper", state, CIPHER, {"scope": "read"})
    assert not repo.complete_attempt(cur, 1, "alpaca", "paper", state, CIPHER, {})
    rows = repo.list_connections(cur, 1)
    assert rows == [dict(provider="alpaca", environment="paper", connected=True,
                         pending=False, metadata={"scope": "read"}, connected_at=NOW, updated_at=NOW)]
    assert repo.list_connections(cur, 2) == []
    assert "tokens_enc" not in rows[0] and "pending_state_hash" not in rows[0]


@pytest.mark.parametrize("uid,provider,session", [(2, "alpaca", "session"),
                            (1, "ibkr", "session"), (1, "alpaca", "other-session")])
def test_wrong_owner_provider_or_session_does_not_burn_state(cur, uid, provider, session):
    state = start(cur)
    assert repo.consume_attempt(cur, uid, provider, state, hashed(session)) is None
    assert state in cur.attempts
    assert repo.consume_attempt(cur, 1, "alpaca", state, hashed("session"))


def test_expired_state_is_refused_and_cannot_complete(cur, monkeypatch):
    state = start(cur)
    monkeypatch.setattr(repo, "now_utc", lambda: NOW + timedelta(minutes=10))
    assert repo.consume_attempt(cur, 1, "alpaca", state, hashed("session")) is None
    assert not repo.complete_attempt(cur, 1, "alpaca", "paper", state, CIPHER, {})
    assert not repo.list_connections(cur, 1)[0]["pending"]


def test_new_attempt_invalidates_old_state_before_exchange(cur):
    old = start(cur)
    new = start(cur, state="second")
    assert old not in cur.attempts
    assert repo.consume_attempt(cur, 1, "alpaca", old, hashed("session")) is None
    assert repo.consume_attempt(cur, 1, "alpaca", new, hashed("session"))


def test_completion_requires_prior_successful_consume(cur):
    state = start(cur)
    assert not repo.complete_attempt(cur, 1, "alpaca", "paper", state, CIPHER, {})
    assert repo.consume_attempt(cur, 1, "alpaca", state, hashed("session"))
    assert repo.complete_attempt(cur, 1, "alpaca", "paper", state, CIPHER, {})


def test_new_attempt_during_exchange_fences_old_completion(cur):
    old = start(cur)
    assert repo.consume_attempt(cur, 1, "alpaca", old, hashed("session"))
    new = start(cur, state="second")
    assert not repo.complete_attempt(cur, 1, "alpaca", "paper", old, CIPHER, {})
    assert cur.connections[(1, "alpaca", "paper")]["pending_state_hash"] == new
    assert repo.get_connection(cur, 1, "alpaca", "paper")["tokens_enc"] is None
    assert finish(cur, state="second")


def test_disconnect_during_exchange_cannot_resurrect_credentials(cur):
    state = start(cur)
    assert repo.consume_attempt(cur, 1, "alpaca", state, hashed("session"))
    assert repo.disconnect(cur, 1, "alpaca", "paper")
    assert not repo.complete_attempt(cur, 1, "alpaca", "paper", state, CIPHER, {})
    assert repo.get_connection(cur, 1, "alpaca", "paper") is None


def test_disconnect_then_reconnect_fences_old_completion(cur):
    old = start(cur)
    assert repo.consume_attempt(cur, 1, "alpaca", old, hashed("session"))
    repo.disconnect(cur, 1, "alpaca", "paper")
    start(cur, state="second")
    assert not repo.complete_attempt(cur, 1, "alpaca", "paper", old, CIPHER, {})
    assert finish(cur, state="second")


def test_reconnect_preserves_old_tokens_until_new_completion(cur):
    start(cur)
    assert finish(cur)
    old = repo.get_connection(cur, 1, "alpaca", "paper")
    start(cur, state="second")
    pending = repo.get_connection(cur, 1, "alpaca", "paper")
    assert pending["tokens_enc"] == old["tokens_enc"]
    assert pending["metadata"] == old["metadata"]
    assert repo.list_connections(cur, 1)[0]["pending"]
    assert repo.list_connections(cur, 1)[0]["connected"]


def test_environment_and_other_users_are_isolated_on_disconnect(cur):
    start(cur)
    start(cur, env="live", state="live")
    start(cur, uid=2, state="other-user")
    start(cur, provider="robinhood", env="live", state="other-provider")
    assert repo.disconnect(cur, 1, "alpaca", "paper")
    assert not repo.disconnect(cur, 1, "alpaca", "paper")
    assert set(cur.attempts) == {hashed("live"), hashed("other-user"), hashed("other-provider")}
    assert repo.get_connection(cur, 1, "alpaca", "live")
    assert repo.get_connection(cur, 2, "alpaca", "paper")


def test_mutations_always_lock_stable_user_row_first(cur):
    operations = [lambda: start(cur),
                  lambda: repo.consume_attempt(cur, 1, "alpaca", hashed("first"), hashed("session")),
                  lambda: repo.complete_attempt(cur, 1, "alpaca", "paper", hashed("first"), CIPHER, {}),
                  lambda: repo.disconnect(cur, 1, "alpaca", "paper")]
    for operation in operations:
        cur.calls.clear()
        operation()
        assert cur.calls[0] == ("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (1,))


def test_sql_carries_ownership_session_expiry_and_attempt_fences(cur):
    start(cur)
    cur.calls.clear()
    repo.consume_attempt(cur, 1, "alpaca", hashed("first"), hashed("session"))
    query = next(sql for sql, _ in cur.calls if sql.startswith("SELECT a.state_hash"))
    for guard in ("a.user_id=%s", "a.provider=%s", "a.state_hash=%s", "a.session_hash=%s",
                  "a.expires_at > %s", "c.pending_state_hash=a.state_hash",
                  "c.pending_session_hash=a.session_hash", "c.pending_expires_at > %s",
                  "c.pending_claimed_at IS NULL", "FOR UPDATE"):
        assert guard in query
    cur.calls.clear()
    repo.complete_attempt(cur, 1, "alpaca", "paper", hashed("first"), CIPHER, {})
    query = next(sql for sql, _ in cur.calls if sql.startswith("UPDATE"))
    for guard in ("user_id=%s", "provider=%s", "environment=%s", "pending_state_hash=%s", "pending_expires_at > %s",
                  "pending_claimed_at IS NOT NULL"):
        assert guard in query


def test_missing_user_cannot_create_orphan_connection(cur):
    with pytest.raises(ValueError, match="owner does not exist"):
        start(cur, uid=99)
    assert not cur.connections and not cur.attempts


@pytest.mark.parametrize("ttl", [0, -1, 901, True, 2.5])
def test_attempt_ttl_is_bounded_before_db_write(cur, ttl):
    with pytest.raises(ValueError, match="15 minutes"):
        repo.save_attempt(cur, 1, "alpaca", "paper", hashed("first"), hashed("session"), CIPHER, ttl)
    assert not cur.calls


@pytest.mark.parametrize("state,session", [("raw-state", hashed("session")), (hashed("first"), "raw-session")])
def test_plaintext_state_or_session_cannot_enter_repository(cur, state, session):
    with pytest.raises(ValueError, match="SHA-256"):
        repo.save_attempt(cur, 1, "alpaca", "paper", state, session, CIPHER)
    assert not cur.calls


@pytest.mark.parametrize("metadata", [[], {"x": float("nan")}, {"x": object()}, {"x": "x" * 8192}])
def test_bad_metadata_is_refused_before_db_write(cur, metadata):
    with pytest.raises(ValueError):
        repo.complete_attempt(cur, 1, "alpaca", "paper", hashed("first"), CIPHER, metadata)
    assert not cur.calls


def test_internal_row_decodes_metadata_without_mutating_cursor(cur):
    start(cur)
    finish(cur)
    result = repo.get_connection(cur, 1, "alpaca", "paper")
    assert result["metadata"] == {"scope": "read"} and result["tokens_enc"] == CIPHER
    assert json.loads(cur.connections[(1, "alpaca", "paper")]["metadata_json"]) == {"scope": "read"}
    assert repo.get_connection(cur, 2, "alpaca", "paper") is None


def test_ddl_is_additive_and_has_unique_state_and_user_provider_environment_keys():
    joined = " ".join(repo.DDL)
    assert len(repo.DDL) == 2 and joined.count("CREATE TABLE IF NOT EXISTS") == 2
    assert "PRIMARY KEY (user_id, provider, environment)" in joined
    assert "ascii_bin PRIMARY KEY" in joined
    assert "tokens_enc MEDIUMBLOB NULL" in joined and "private_enc MEDIUMBLOB NOT NULL" in joined
    assert "state CHAR" not in joined  # Raw OAuth state is never persisted.
