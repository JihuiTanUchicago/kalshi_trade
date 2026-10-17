"""IBKR approved-vendor OAuth 1.0a authorization and verified LST derivation.

No Client Portal gateway login, brokerage-session initialization or trading
request is performed here. OAuth2 is not substituted for IBKR's documented
third-party RSA/Diffie-Hellman protocol. Credentials belong in Tau's vault.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import dh, padding, rsa
from cryptography.exceptions import UnsupportedAlgorithm
import requests

BASE = "https://api.ibkr.com/v1/api"
AUTHORIZE = "https://interactivebrokers.com/authorize"
_TIMEOUT = (5, 20)
_MAX_KEY_BYTES = 65_536


class Error(ValueError):
    """Public-safe exception, deliberately excluding provider messages and keys."""


def _text(value: object, *, limit: int = 8192) -> str:
    if (not isinstance(value, str) or not value or len(value) > limit
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise Error("IBKR returned an invalid authorization response.")
    return value


def _read_material(variable: str) -> bytes:
    path = Path(os.environ.get(variable, ""))
    if not path.is_absolute():
        raise Error("IBKR requires the approved application's key and DH parameter files.")
    try:
        with path.open("rb") as handle:
            value = handle.read(_MAX_KEY_BYTES + 1)
        if not value or len(value) > _MAX_KEY_BYTES:
            raise ValueError
        return value
    except (OSError, ValueError):
        raise Error("IBKR OAuth key material is missing or invalid.") from None


def _config() -> tuple:
    consumer = os.environ.get("IBKR_OAUTH_CONSUMER_KEY", "").strip()
    if os.environ.get("IBKR_OAUTH_APPROVED") != "1" or not consumer:
        raise Error("IBKR requires an approved third-party OAuth application.")
    _text(consumer, limit=512)
    # Avoid ambiguous OAuth signature normalization for operator-supplied keys.
    if not all(char.isascii() and (char.isalnum() or char in "_-.") for char in consumer):
        raise Error("IBKR OAuth consumer key is invalid.")
    try:
        signing = serialization.load_pem_private_key(_read_material("IBKR_OAUTH_SIGNING_KEY_PATH"), password=None)
        encryption = serialization.load_pem_private_key(_read_material("IBKR_OAUTH_ENCRYPTION_KEY_PATH"), password=None)
        params = serialization.load_pem_parameters(_read_material("IBKR_OAUTH_DH_PARAMS_PATH"))
        if (not isinstance(signing, rsa.RSAPrivateKey) or signing.key_size < 2048
                or not isinstance(encryption, rsa.RSAPrivateKey) or encryption.key_size < 2048
                or signing.public_key().public_numbers() == encryption.public_key().public_numbers()
                or not isinstance(params, dh.DHParameters)):
            raise ValueError
        numbers = params.parameter_numbers()
        if numbers.p.bit_length() < 2048 or numbers.g != 2:
            raise ValueError
    except (TypeError, ValueError, UnsupportedAlgorithm):
        raise Error("IBKR requires separate RSA signing/encryption keys and its supplied DH parameters.") from None
    return consumer, signing, encryption, numbers.p, numbers.g


def status() -> dict:
    try:
        _config()
    except Error as exc:
        return {"configured": False, "reason": str(exc)}
    return {"configured": True, "reason": "", "environments": ["live"]}


def _environment(environment: str) -> None:
    if environment != "live":
        raise Error("IBKR's approved OAuth application connects the user's broker authorization.")


def _params(consumer: str) -> dict:
    return {"oauth_consumer_key": consumer, "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "RSA-SHA256", "oauth_timestamp": str(int(time.time()))}


def _signed_header(url: str, params: dict, consumer: str, signing: rsa.RSAPrivateKey,
                   *, prepend: str = "", lst: bool = False) -> str:
    # IBKR explicitly documents raw sorted pairs, then one encoding pass. This
    # differs from canonical OAuth1 per-value normalization. Callback is 'oob'.
    pairs = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    encoded = quote_plus(pairs) if lst else quote(pairs)
    base_string = prepend + "POST&" + quote_plus(url) + "&" + encoded
    signature = signing.sign(base_string.encode(), padding.PKCS1v15(), hashes.SHA256())
    values = {**params, "oauth_signature": quote_plus(base64.b64encode(signature).decode()),
              "realm": "test_realm" if consumer == "TESTCONS" else "limited_poa"}
    # All variable token values are validated before this header is built.
    return "OAuth " + ", ".join(f'{key}="{value}"' for key, value in sorted(values.items()))


def _token_value(value: object) -> str:
    value = _text(value)
    if not all(char.isascii() and (char.isalnum() or char in "_-./+=") for char in value):
        raise Error("IBKR returned an invalid authorization response.")
    return value


def _post(path: str, params: dict, config: tuple, *, prepend: str = "", lst: bool = False) -> dict:
    if path not in {"/oauth/request_token", "/oauth/access_token", "/oauth/live_session_token"}:
        raise Error("IBKR authorization endpoint is not allowed.")
    consumer, signing = config[:2]
    url = BASE + path
    header = _signed_header(url, params, consumer, signing, prepend=prepend, lst=lst)
    try:
        response = requests.post(url, headers={"Authorization": header,
                                               "User-Agent": "Tau/1.0", "Accept": "application/json"},
                                 timeout=_TIMEOUT, allow_redirects=False)
    except requests.RequestException:
        raise Error("IBKR authorization service is unavailable.") from None
    try:
        if response.status_code != 200:
            raise Error("IBKR declined the authorization request. Reconnect to try again.")
        if len(response.content) > 65_536:
            raise Error("IBKR returned an invalid authorization response.")
        payload = response.json()
        if not isinstance(payload, dict):
            raise Error("IBKR returned an invalid authorization response.")
        return payload
    except (ValueError, TypeError):
        raise Error("IBKR returned an invalid authorization response.") from None
    finally:
        response.close()


def begin(redirect_uri: str, state: str, environment: str) -> dict:
    _environment(environment)
    config = _config()
    params = {**_params(config[0]), "oauth_callback": "oob"}
    payload = _post("/oauth/request_token", params, config)
    token = _token_value(payload.get("oauth_token"))
    # IBKR's verifier guide documents redirect_uri on /authorize. Bind its
    # callback to Tau's single-use state as well as the issued request token.
    split = urlsplit(redirect_uri)
    callback = urlunsplit((split.scheme, split.netloc, split.path,
                          urlencode([*parse_qsl(split.query), ("state", state)]), ""))
    return {"authorization_url": AUTHORIZE + "?" + urlencode({"oauth_token": token,
                                                               "redirect_uri": callback}),
            "private": {"request_token": token, "state": state, "consumer_key": config[0]}}


def _derive_session(credentials: dict, config: tuple) -> dict:
    consumer, _, encryption, prime, generator = config
    token = _token_value(credentials.get("oauth_token"))
    secret = _token_value(credentials.get("oauth_token_secret"))
    try:
        decrypted = encryption.decrypt(base64.b64decode(secret, validate=True), padding.PKCS1v15())
        if not decrypted:
            raise ValueError
    except (ValueError, TypeError):
        raise Error("IBKR access-token secret could not be validated.") from None
    exponent = secrets.randbits(256) or 1
    challenge = format(pow(generator, exponent, prime), "x")
    params = {**_params(consumer), "oauth_token": token, "diffie_hellman_challenge": challenge}
    payload = _post("/oauth/live_session_token", params, config, prepend=decrypted.hex(), lst=True)
    try:
        server_public = int(_text(payload.get("diffie_hellman_response"), limit=4096), 16)
        if not 1 < server_public < prime - 1:
            raise ValueError
        shared = pow(server_public, exponent, prime)
        encoded = shared.to_bytes((shared.bit_length() + 7) // 8, "big")
        if shared.bit_length() % 8 == 0:
            encoded = b"\x00" + encoded
        live_token_bytes = hmac.new(encoded, decrypted, hashlib.sha1).digest()
        proof = hmac.new(live_token_bytes, consumer.encode(), hashlib.sha1).hexdigest()
        server_proof = _text(payload.get("live_session_token_signature"), limit=40)
        if not hmac.compare_digest(proof, server_proof):
            raise ValueError
        expiration = int(payload["live_session_token_expiration"])
        # IBKR returns Unix milliseconds. Accept seconds too for compatibility.
        if expiration > 10_000_000_000:
            expiration //= 1000
        now = int(time.time())
        if not now < expiration <= now + 172_800:
            raise ValueError
    except (KeyError, ValueError, TypeError, OverflowError):
        raise Error("IBKR live-session token verification failed.") from None
    return {**credentials, "live_session_token": base64.b64encode(live_token_bytes).decode(),
            "live_session_token_signature": server_proof, "expires_at": expiration,
            "scope": "broker_authorization", "session_initialized": False}


def exchange(query: dict, private: dict, redirect_uri: str, environment: str) -> dict:
    _environment(environment)
    config = _config()
    if query.get("error") or query.get("denied"):
        raise Error("IBKR authorization was declined or cancelled.")
    token = _token_value(query.get("oauth_token"))
    expected = _token_value(private.get("request_token"))
    if (not hmac.compare_digest(token, expected) or private.get("consumer_key") != config[0]
            or not hmac.compare_digest(_text(query.get("state"), limit=128).encode(),
                                       _text(private.get("state"), limit=128).encode())):
        raise Error("IBKR authorization did not match the pending connection.")
    params = {**_params(config[0]), "oauth_callback": "oob", "oauth_token": token,
              "oauth_verifier": _token_value(query.get("oauth_verifier"))}
    payload = _post("/oauth/access_token", params, config)
    credentials = {"oauth_token": _token_value(payload.get("oauth_token")),
                   "oauth_token_secret": _token_value(payload.get("oauth_token_secret"))}
    return _derive_session(credentials, config)


def refresh(credentials: dict, environment: str) -> dict:
    """Renew IBKR's time-limited LST; never initialize a brokerage session."""
    _environment(environment)
    return _derive_session(credentials, _config())


def inspect(credentials: dict, environment: str) -> dict:
    """Verify saved LST proof; deliberately do not claim account-read acceptance."""
    _environment(environment)
    consumer = _config()[0]
    try:
        token = base64.b64decode(_text(credentials.get("live_session_token")), validate=True)
        proof = hmac.new(token, consumer.encode(), hashlib.sha1).hexdigest()
        if (len(token) != 20 or not hmac.compare_digest(proof, _text(credentials.get("live_session_token_signature")))
                or int(credentials.get("expires_at", 0)) <= int(time.time())):
            raise ValueError
    except (ValueError, TypeError):
        raise Error("IBKR live-session authorization expired or could not be verified.") from None
    return {"verification": "live_session_token_verified", "scope": "broker_authorization",
            "scopes": ["broker_authorization"], "expires_at": int(credentials["expires_at"]),
            "account_label": "IBKR authorization", "account_verified": False,
            "session_initialized": False}
