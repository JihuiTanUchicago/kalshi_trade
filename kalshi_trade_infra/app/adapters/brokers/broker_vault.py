"""Encrypted broker credentials, isolated from the Kalshi-key ciphertext format.

The same deployment key protects this vault, but authenticated context prevents
moving a ciphertext between users, brokers, environments, or OAuth purposes.
Neither plaintext secrets nor provider responses belong in logs or metadata.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = b"\x01"
_MAX_PAYLOAD_BYTES = 65_536
_CONTEXT_PART = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")


class BrokerVaultError(ValueError):
    """Invalid or unauthenticated credentials; deliberately omits secret data."""


def _cipher() -> AESGCM:
    raw = os.getenv("APP_SECRET_KEY", "")
    try:
        key = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if len(key) != 32:
        raise RuntimeError("APP_SECRET_KEY must be 32 random bytes, urlsafe-base64 encoded.")
    return AESGCM(key)


def configured() -> bool:
    """Whether the deployment encryption key is valid, without disclosing it."""
    try:
        _cipher()
    except RuntimeError:
        return False
    return True


def _aad(user_id: int, provider: str, environment: str, purpose: str) -> bytes:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise BrokerVaultError("Invalid broker credential context.")
    if any(not isinstance(value, str) or not _CONTEXT_PART.fullmatch(value)
           for value in (provider, environment, purpose)):
        raise BrokerVaultError("Invalid broker credential context.")
    return f"broker:v1:{user_id}:{provider}:{environment}:{purpose}".encode("ascii")


def _encode(payload: dict[str, Any]) -> bytes:
    if not isinstance(payload, dict):
        raise BrokerVaultError("Broker credentials must be a JSON object.")
    try:
        value = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise BrokerVaultError("Broker credentials must be a JSON object.") from None
    if len(value) > _MAX_PAYLOAD_BYTES:
        raise BrokerVaultError("Broker credentials exceed the storage limit.")
    return value


def encrypt(user_id: int, provider: str, environment: str, purpose: str,
            payload: dict[str, Any]) -> bytes:
    """Encrypt a bounded JSON object; ciphertext is version + nonce + GCM data."""
    aad = _aad(user_id, provider, environment, purpose)
    plaintext = _encode(payload)
    nonce = os.urandom(12)
    return _VERSION + nonce + _cipher().encrypt(nonce, plaintext, aad)


def decrypt(user_id: int, provider: str, environment: str, purpose: str,
            payload: bytes) -> dict[str, Any]:
    """Authenticate and decode credentials, refusing swapped or corrupt blobs."""
    aad = _aad(user_id, provider, environment, purpose)
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise BrokerVaultError("Broker credentials could not be decrypted.")
    value = bytes(payload)
    if (len(value) < 1 + 12 + 16 or len(value) > 1 + 12 + 16 + _MAX_PAYLOAD_BYTES
            or value[:1] != _VERSION):
        raise BrokerVaultError("Broker credentials could not be decrypted.")
    cipher = _cipher()  # A missing server key is an operator error, not bad user data.
    try:
        decoded = json.loads(cipher.decrypt(value[1:13], value[13:], aad).decode("utf-8"))
    except (InvalidTag, ValueError, UnicodeError, RecursionError):
        raise BrokerVaultError("Broker credentials could not be decrypted.") from None
    if not isinstance(decoded, dict):
        raise BrokerVaultError("Broker credentials must be a JSON object.")
    return decoded
