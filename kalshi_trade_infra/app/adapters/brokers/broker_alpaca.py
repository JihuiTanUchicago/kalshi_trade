"""Alpaca Connect authorization and account verification, without order execution.

OAuth app credentials are separate from the shared APCA_* market-data keys.
See https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api .
"""
from __future__ import annotations

import os
import time
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://app.alpaca.markets/oauth/authorize"
TOKEN_URL = "https://api.alpaca.markets/oauth/token"
ACCOUNT_URLS = {
    "paper": "https://paper-api.alpaca.markets/v2/account",
    "live": "https://api.alpaca.markets/v2/account",
}


class Error(ValueError):
    """Safe to show to the user; never includes a provider response or token."""


def status() -> dict:
    ready = bool(os.getenv("ALPACA_OAUTH_CLIENT_ID", "").strip()
                 and os.getenv("ALPACA_OAUTH_CLIENT_SECRET", "").strip())
    return {"configured": ready, "reason": "" if ready else "Tau’s Alpaca app is awaiting setup."}


def _environment(environment: str) -> None:
    if not isinstance(environment, str) or environment not in ACCOUNT_URLS:
        raise Error("Choose an Alpaca paper or live account.")


def begin(redirect_uri: str, state: str, environment: str, permission: str = "read") -> dict:
    _environment(environment)
    if not status()["configured"]:
        raise Error(status()["reason"])
    if permission not in ("read", "trading"):
        raise Error("Choose account access or account and order authorization.")
    # Read-only account endpoints need no scope. Data supports agent research;
    # order authorization requires an explicit choice on Tau and broker consent.
    scopes = ["data"] + (["trading"] if permission == "trading" else [])
    return {
        "authorization_url": AUTHORIZE_URL + "?" + urlencode({
            "response_type": "code", "client_id": os.environ["ALPACA_OAUTH_CLIENT_ID"].strip(),
            "redirect_uri": redirect_uri, "state": state, "scope": " ".join(scopes),
            "env": environment,
        }),
        "private": {"requested_scopes": scopes},
    }


def _json_response(response) -> dict:
    if response.status_code != 200:
        raise Error("Alpaca could not authorize this connection. Please reconnect.")
    try:
        data = response.json()
    except (ValueError, TypeError):
        raise Error("Alpaca returned an unreadable response.") from None
    if not isinstance(data, dict):
        raise Error("Alpaca returned an unreadable response.")
    return data


def exchange(query: dict, private: dict, redirect_uri: str, environment: str) -> dict:
    _environment(environment)
    code = query.get("code")
    if not isinstance(code, str) or not code or len(code) > 8192 or any(ord(c) < 32 for c in code):
        raise Error("Alpaca did not return an authorization code.")
    try:
        data = _json_response(requests.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code,
            "client_id": os.getenv("ALPACA_OAUTH_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("ALPACA_OAUTH_CLIENT_SECRET", "").strip(),
            "redirect_uri": redirect_uri,
        }, timeout=15, allow_redirects=False))
    except requests.RequestException:
        raise Error("Alpaca is unavailable. Please reconnect shortly.") from None
    token = data.get("access_token")
    if (not isinstance(token, str) or not token or len(token) > 16384
            or any(ord(c) < 33 or ord(c) > 126 for c in token)
            or str(data.get("token_type", "")).lower() != "bearer"):
        raise Error("Alpaca returned an invalid authorization grant.")
    scope = data.get("scope", "")
    if not isinstance(scope, str) or len(scope) > 200:
        raise Error("Alpaca returned invalid permissions.")
    granted = set(scope.split())
    requested = set(private.get("requested_scopes", []))
    if granted != requested:
        raise Error("Alpaca’s permissions did not match your request. Please reconnect.")
    credentials = {"access_token": token, "token_type": "Bearer", "scope": " ".join(sorted(granted))}
    # Alpaca's documented grant has no expiry/refresh token. Honour an expiry
    # when supplied, rather than pretending an undocumented refresh flow exists.
    if "expires_in" in data:
        expiry = data["expires_in"]
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not 0 < expiry <= 10 * 365 * 86400:
            raise Error("Alpaca returned an invalid authorization lifetime.")
        credentials["expires_at"] = int(time.time() + expiry)
    return credentials


def inspect(credentials: dict, environment: str) -> dict:
    _environment(environment)
    try:
        data = _json_response(requests.get(ACCOUNT_URLS[environment], headers={
            "Authorization": "Bearer " + credentials["access_token"],
            "Accept": "application/json",
        }, timeout=15, allow_redirects=False))
    except requests.RequestException:
        raise Error("Alpaca account verification is unavailable. Please reconnect.") from None
    if not isinstance(data.get("id"), str) or not data["id"]:
        raise Error("Alpaca did not confirm access to this account.")
    # Full identifiers and balances are never part of the public connection DTO.
    credentials["account_id"] = data["id"]
    number = str(data.get("account_number", ""))
    suffix = number[-4:] if number.isalnum() and len(number) >= 4 else ""
    return {
        "account_label": ("Paper" if environment == "paper" else "Live") + (" · ••••" + suffix if suffix else " account"),
        "verification": "account_verified", "scopes": credentials["scope"].split(),
        "expires_at": credentials.get("expires_at"),
    }
