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
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Hashable, Optional, Tuple, TypeVar

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from data_pipeline.common import KalshiCredentials, get_kalshi_cash_balance_dollars

KALSHI_FUNDING_URL = "https://kalshi.com/account/funding"


class KalshiKeyError(ValueError):
    """User-facing problem with a submitted key. Messages are fixed text: never the key itself."""


# What the user sees for anything that isn't a readable private key (garbage, a public key, a key cut
# off mid-copy, the key ID pasted in the wrong box).
PRIVATE_KEY_FORMAT = ("That isn’t a private key Kalshi can use. Paste the whole .key file Kalshi downloaded, "
                      "from its -----BEGIN line to its -----END line, or choose the file.")


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
        raise KalshiKeyError(PRIVATE_KEY_FORMAT)
    if not isinstance(key, RSAPrivateKey):
        raise KalshiKeyError("That isn’t an RSA key, and Kalshi API keys always are. Choose the .key file "
                             "Kalshi downloaded when you created the key.")
    return key


def credentials_from_row(user_id: int, row: dict) -> KalshiCredentials:
    return row["key_id"], parse_private_key(decrypt_private_key(user_id, row["private_key_enc"]))


def balance(creds: KalshiCredentials) -> Optional[float]:
    return get_kalshi_cash_balance_dollars(creds)


# The dashboard polls often; a short per-user memo keeps a live balance on screen without a
# Kalshi round-trip every tick. Values only (never the key or creds) are cached.
_BALANCE_CACHE: Dict[int, Tuple[float, Optional[float]]] = {}
_BALANCE_TTL = 60.0
# A memo counts as kept only with this long still to run, so a page read that checked it a moment
# earlier still answers from it.
KEPT_MARGIN = 5.0
T = TypeVar("T")


def remember_balance(user_id: int, value: Optional[float]) -> None:
    """Seed the memo with a balance just read (a key was verified), so Funds shows the new key's cash
    rather than a value cached for the key it replaced."""
    _BALANCE_CACHE[user_id] = (time.monotonic(), value)


class _Flight:
    """One read in flight: its answer (or what it raised) once `done` is set."""

    __slots__ = ("done", "value", "error")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Any = None
        self.error: Optional[BaseException] = None


_FLIGHTS: Dict[Hashable, _Flight] = {}
_FLIGHTS_LOCK = threading.Lock()


def single_flight(key: Hashable, read: Callable[[], T]) -> T:
    """read() for `key` (("live" | "demo", user id)), with at most one in flight per key: a caller that finds
    one in flight waits for it and takes its answer instead of asking Kalshi again. Two tabs open, or a poll
    and its page's follow-up at once, were each a Kalshi balance read the moment the memo ran out. For
    display reads only (the read-only balance GETs): nothing that sizes or gates an order goes through it.
    No timeout of its own: the read under it has Kalshi's, and a waiter waits no longer than it."""
    with _FLIGHTS_LOCK:
        flight = _FLIGHTS.get(key)
        lead = flight is None
        if lead:
            flight = _FLIGHTS[key] = _Flight()
    if not lead:
        flight.done.wait()
        if flight.error is not None:
            raise flight.error
        return flight.value
    try:
        flight.value = read()
        return flight.value
    except BaseException as e:  # noqa: BLE001 - handed to the waiters, then raised here as it was
        flight.error = e
        raise
    finally:
        with _FLIGHTS_LOCK:
            _FLIGHTS.pop(key, None)
        flight.done.set()


def balance_cached(user_id: int, creds: KalshiCredentials, ttl: float = _BALANCE_TTL) -> Optional[float]:
    """Best-effort live cash balance with a short TTL memo. Returns None (never raises) when
    Kalshi can't be reached, so callers degrade to a 'couldn't read it' state. One Kalshi read per user
    at a time (single_flight): reads that miss the memo together share it. Display only."""
    hit = _BALANCE_CACHE.get(user_id)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    return single_flight(("live", user_id), lambda: _read_into_memo(user_id, creds, ttl))


def _read_into_memo(user_id: int, creds: KalshiCredentials, ttl: float) -> Optional[float]:
    now = time.monotonic()
    hit = _BALANCE_CACHE.get(user_id)
    if hit and now - hit[0] < ttl:  # a read that finished just before this one started
        return hit[1]
    try:
        value = balance(creds)
    except Exception:
        value = None
    # A key saved meanwhile seeded the memo with its own cash (remember_balance): that stays.
    if _BALANCE_CACHE.get(user_id) is hit:
        _BALANCE_CACHE[user_id] = (now, value)
    return value


def balance_kept(user_id: int) -> bool:
    """Whether balance_cached would answer from the memo now, never asking Kalshi. Reads the memo only."""
    return memo_kept(_BALANCE_CACHE, user_id, _BALANCE_TTL)


def balance_read_at(user_id: int) -> Optional[datetime]:
    """When the memoized balance was read from Kalshi (naive UTC), so a page can say how old the figure
    is; None when nothing is memoized. Reads the memo only, never Kalshi."""
    return memo_read_at(_BALANCE_CACHE, user_id)


def balance_memo(user_id: int) -> Optional[Tuple[Optional[float], datetime]]:
    """(cash, when it was read) as the memo holds it, however old, or None when it holds nothing. For a
    page that must never wait on Kalshi: it shows an old figure with its age, then asks for a fresh one.
    Reads the memo only, never Kalshi."""
    return memo_peek(_BALANCE_CACHE, user_id)


def memo_peek(cache: Dict[int, Tuple[float, Optional[float]]], user_id: int) -> Optional[Tuple[Optional[float], datetime]]:
    """(value, when it was read as naive UTC) from a (monotonic time, value) balance memo, however old;
    None when it holds nothing for this user. The demo balance memo (demo_twins) has the same shape."""
    hit = cache.get(user_id)
    if not hit:
        return None
    age = max(0.0, time.monotonic() - hit[0])
    return hit[1], (datetime.now(timezone.utc) - timedelta(seconds=age)).replace(tzinfo=None, microsecond=0)


def memo_read_at(cache: Dict[int, Tuple[float, Optional[float]]], user_id: int) -> Optional[datetime]:
    """When a (monotonic time, value) balance memo was filled for this user, as naive UTC; None when it
    holds nothing. The demo balance memo (demo_twins) has the same shape and reads this too."""
    hit = memo_peek(cache, user_id)
    return None if hit is None else hit[1]


def memo_kept(cache: Dict[int, Tuple[float, Optional[float]]], user_id: int, ttl: float) -> bool:
    """Whether a (monotonic time, value) balance memo holds this user's balance with at least KEPT_MARGIN
    of its `ttl` to run (a failed read memoized as None counts: it answers from memory too)."""
    hit = cache.get(user_id)
    return bool(hit) and time.monotonic() - hit[0] < ttl - KEPT_MARGIN


def verify(key_id: str, pem: str) -> float:
    """Prove the key works before storing it. Returns the cash balance."""
    key_id = (key_id or "").strip()
    if not key_id or len(key_id) > 128:
        raise KalshiKeyError("Paste the Key ID from the API keys page on kalshi.com: the short code shown next to "
                             "the key, like a952bcbe-ec3b-4b5b-….")
    cash = balance((key_id, parse_private_key(pem)))
    if cash is None:
        raise KalshiKeyError("Kalshi didn’t accept this key, or couldn’t be reached just now. Check that the Key ID "
                             "and the private key come from the same key, and that the key is still listed on "
                             "kalshi.com. A key made on demo.kalshi.co is a demo key: add it under Demo key instead.")
    return cash


def order_submitter(creds: KalshiCredentials):
    """Submitter for MarketableLimitKernel, signing as this user."""
    from data_pipeline.live_trading_engine import place_limit_order

    def submit(ticker: str, action: str, side: str, qty: int, price: float,
               client_order_id: Optional[str] = None) -> dict:
        return place_limit_order(ticker, action, side, qty, price, credentials=creds,
                                 client_order_id=client_order_id)

    return submit
