"""Synthetic credential encryption tests; no real credentials or provider calls."""
import base64
import json
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import broker_vault as vault


@pytest.fixture
def key(monkeypatch):
    value = os.urandom(32)
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(value).decode())
    return value


def test_round_trip_is_nondeterministic_and_not_plaintext(key):
    payload = {"access_token": "synthetic-secret", "scope": "account:read", "expires_at": 2_000_000_000}
    first = vault.encrypt(7, "alpaca", "paper", "tokens", payload)
    second = vault.encrypt(7, "alpaca", "paper", "tokens", payload)
    assert first != second
    assert b"synthetic-secret" not in first
    assert vault.decrypt(7, "alpaca", "paper", "tokens", first) == payload
    assert vault.decrypt(7, "alpaca", "paper", "tokens", memoryview(first)) == payload
    assert vault.configured()


@pytest.mark.parametrize("context", [
    (8, "alpaca", "paper", "tokens"),
    (7, "robinhood", "paper", "tokens"),
    (7, "alpaca", "live", "tokens"),
    (7, "alpaca", "paper", "state"),
])
def test_ciphertext_cannot_move_between_contexts(key, context):
    blob = vault.encrypt(7, "alpaca", "paper", "tokens", {"access_token": "synthetic-secret"})
    with pytest.raises(vault.BrokerVaultError, match="could not be decrypted"):
        vault.decrypt(*context, blob)


@pytest.mark.parametrize("context", [
    (0, "alpaca", "paper", "tokens"),
    (True, "alpaca", "paper", "tokens"),
    ("7", "alpaca", "paper", "tokens"),
    (7, "alpaca:live", "paper", "tokens"),
    (7, "alpaca", "paper:tokens", "tokens"),
    (7, "alpaca", "paper", ""),
])
def test_context_has_no_delimiter_aliases(key, context):
    with pytest.raises(vault.BrokerVaultError, match="context"):
        vault.encrypt(*context, {})


@pytest.mark.parametrize("raw", [None, "", "garbage", "!" * 44,
                                  base64.urlsafe_b64encode(b"short").decode()])
def test_missing_or_invalid_server_key_fails_closed(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("APP_SECRET_KEY", raw)
    assert not vault.configured()
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        vault.encrypt(7, "alpaca", "paper", "tokens", {})


def test_unpadded_key_is_accepted(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="))
    assert vault.configured()


def test_key_rotation_refuses_old_ciphertext(key, monkeypatch):
    blob = vault.encrypt(7, "alpaca", "paper", "tokens", {"token": "synthetic"})
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    with pytest.raises(vault.BrokerVaultError):
        vault.decrypt(7, "alpaca", "paper", "tokens", blob)


@pytest.mark.parametrize("payload", [None, [], "synthetic-secret", {"x": object()}, {"x": float("nan")}])
def test_payload_must_be_finite_json_object_and_error_omits_secrets(key, payload):
    with pytest.raises(vault.BrokerVaultError) as exc:
        vault.encrypt(7, "alpaca", "paper", "tokens", payload)
    assert "synthetic-secret" not in str(exc.value)


def test_large_payload_is_refused(key):
    with pytest.raises(vault.BrokerVaultError, match="storage limit"):
        vault.encrypt(7, "alpaca", "paper", "state", {"verifier": "x" * 65_536})


@pytest.mark.parametrize("mutation", ["nonce", "ciphertext", "version", "truncated", "oversized"])
def test_malformed_or_tampered_blob_is_refused(key, mutation):
    blob = bytearray(vault.encrypt(7, "alpaca", "paper", "tokens", {"token": "synthetic-secret"}))
    if mutation == "nonce":
        blob[3] ^= 1
    elif mutation == "ciphertext":
        blob[-1] ^= 1
    elif mutation == "version":
        blob[0] = 2
    elif mutation == "truncated":
        blob = blob[:20]
    else:
        blob.extend(b"x" * 65_536)
    with pytest.raises(vault.BrokerVaultError) as exc:
        vault.decrypt(7, "alpaca", "paper", "tokens", blob)
    assert "synthetic-secret" not in str(exc.value)


def test_authenticated_non_object_is_refused(key):
    nonce = os.urandom(12)
    blob = b"\x01" + nonce + AESGCM(key).encrypt(
        nonce, json.dumps(["synthetic-secret"]).encode(), b"broker:v1:7:alpaca:paper:tokens")
    with pytest.raises(vault.BrokerVaultError, match="JSON object"):
        vault.decrypt(7, "alpaca", "paper", "tokens", blob)
