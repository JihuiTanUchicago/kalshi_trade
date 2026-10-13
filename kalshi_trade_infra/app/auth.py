"""Sign in with Google (OpenID Connect authorization-code flow + PKCE) and
server-side sessions.

The ID token is taken straight from Google's token endpoint over TLS, which
OIDC Core 3.1.3.7 accepts in place of a signature check; every claim that
matters (issuer, audience, expiry, nonce, verified email) is still checked.
Sessions are random tokens; only their SHA-256 is stored, so a database leak
does not leak live sessions.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from datetime import timedelta
from typing import Dict, Optional
from urllib.parse import urlencode

import requests

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
# Must exactly match an authorised redirect URI in the Google Cloud console.
REDIRECT_URI = os.getenv("APP_GOOGLE_REDIRECT_URI", "")

SESSION_COOKIE = "rsid"
SESSION_TTL = timedelta(days=30)


class AuthError(ValueError):
    pass


def google_configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET and REDIRECT_URI)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_login() -> Dict[str, str]:
    """state, nonce and PKCE verifier for one sign-in attempt."""
    return {
        "state": secrets.token_urlsafe(32)[:43],
        "nonce": secrets.token_urlsafe(32)[:43],
        "verifier": secrets.token_urlsafe(48)[:64],
    }


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(login: Dict[str, str]) -> str:
    return GOOGLE_AUTH_URL + "?" + urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": login["state"],
        "nonce": login["nonce"],
        "code_challenge": _challenge(login["verifier"]),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })


def _jwt_claims(id_token: str) -> Dict:
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:
        raise AuthError("Google returned an unreadable ID token.")


def check_claims(claims: Dict, nonce: str, now: Optional[float] = None) -> Dict[str, Optional[str]]:
    now = time.time() if now is None else now
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise AuthError("ID token was not issued by Google.")
    aud = claims.get("aud")
    if aud != CLIENT_ID and not (isinstance(aud, list) and CLIENT_ID in aud):
        raise AuthError("ID token is for a different app.")
    if float(claims.get("exp") or 0) < now - 60:
        raise AuthError("ID token has expired.")
    if not secrets.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise AuthError("Sign-in nonce did not match.")
    if not claims.get("sub") or not claims.get("email"):
        raise AuthError("Google did not share an email address.")
    if claims.get("email_verified") not in (True, "true"):
        raise AuthError("Your Google email address is not verified.")
    return {
        "sub": str(claims["sub"]),
        "email": str(claims["email"]),
        "name": claims.get("name"),
        "picture": claims.get("picture"),
    }


def exchange_code(code: str, verifier: str, nonce: str) -> Dict[str, Optional[str]]:
    resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }, timeout=15)
    if resp.status_code >= 400:
        raise AuthError("Google refused the sign-in (%s)." % resp.status_code)
    id_token = (resp.json() or {}).get("id_token")
    if not id_token:
        raise AuthError("Google returned no ID token.")
    return check_claims(_jwt_claims(id_token), nonce)
