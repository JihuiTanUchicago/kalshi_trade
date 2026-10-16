"""A user's own Kalshi account: their API key, balance and orders.

We never hold customer money (that would require CFTC registration). A user
who wants live trading connects a Kalshi API key; the private key is stored
encrypted (AES-256-GCM, key from APP_SECRET_KEY, bound to the user id so a
ciphertext cannot be moved between users) and only decrypted in memory to sign
requests.
"""
from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from data_pipeline.common import KalshiCredentials, get_kalshi_cash_balance_dollars

KALSHI_FUNDING_URL = "https://kalshi.com/account/funding"


class KalshiKeyError(ValueError):
    """User-facing problem with a submitted key."""


def _cipher() -> AESGCM:
    raw = os.getenv("APP_SECRET_KEY", "")
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception:
        key = b""
    if len(key) != 32:
        raise RuntimeError("APP_SECRET_KEY must be 32 random bytes, urlsafe-base64 encoded.")
    return AESGCM(key)


def encrypt_private_key(user_id: int, pem: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + _cipher().encrypt(nonce, pem.encode("utf-8"), b"user:%d" % user_id)


def decrypt_private_key(user_id: int, blob: bytes) -> str:
    return _cipher().decrypt(bytes(blob[:12]), bytes(blob[12:]), b"user:%d" % user_id).decode("utf-8")


def parse_private_key(pem: str):
    try:
        key = serialization.load_pem_private_key(pem.strip().encode("utf-8"), password=None)
    except Exception:
        raise KalshiKeyError("That doesn't look like the private key file Kalshi gave you (PEM, starts with -----BEGIN).")
    if not isinstance(key, RSAPrivateKey):
        raise KalshiKeyError("Kalshi API keys are RSA keys; this one isn't.")
    return key


def credentials_from_row(user_id: int, row: dict) -> KalshiCredentials:
    return row["key_id"], parse_private_key(decrypt_private_key(user_id, row["private_key_enc"]))


def balance(creds: KalshiCredentials) -> Optional[float]:
    return get_kalshi_cash_balance_dollars(creds)


def verify(key_id: str, pem: str) -> float:
    """Prove the key works before storing it. Returns the cash balance."""
    key_id = (key_id or "").strip()
    if not key_id or len(key_id) > 128:
        raise KalshiKeyError("Enter the API key ID from your Kalshi account settings.")
    cash = balance((key_id, parse_private_key(pem)))
    if cash is None:
        raise KalshiKeyError("Kalshi rejected this key. Check the key ID matches the private key and that it is active.")
    return cash


def order_submitter(creds: KalshiCredentials):
    """Submitter for MarketableLimitKernel, signing as this user."""
    from data_pipeline.live_trading_engine import place_limit_order

    def submit(ticker: str, action: str, side: str, qty: int, price: float) -> dict:
        return place_limit_order(ticker, action, side, qty, price, credentials=creds)

    return submit
