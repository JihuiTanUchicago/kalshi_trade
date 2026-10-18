"""Account connection lifecycle; grants never become agent tools or orders here."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app import broker_repository as store
from app import broker_vault as vault
from app import repository as repo

PROVIDERS = {
    "alpaca": {
        "name": "Alpaca", "environments": ["paper", "live"], "default_environment": "paper",
        "permission_note": "Account and market-data access. Order authorization is optional; Tau execution remains disabled.",
        "setup_url": "https://docs.alpaca.markets/us/docs/about-connect-api",
    },
    "robinhood": {
        "name": "Robinhood", "environments": ["live"], "default_environment": "live",
        "permission_note": "Robinhood Trading MCP connects an Agentic account and can grant order permissions. Tau execution remains disabled.",
        "setup_url": "https://robinhood.com/us/en/support/articles/onboarding-an-external-agent/",
    },
    "ibkr": {
        "name": "Interactive Brokers", "environments": ["live"], "default_environment": "live",
        "permission_note": "Requires an approved IBKR vendor connection. Authorizing access does not start a trading session in Tau.",
        "setup_url": "https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/",
    },
}
STATE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class Error(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _adapter(provider: str):
    if provider not in PROVIDERS:
        raise Error("Unknown brokerage.", 404)
    return importlib.import_module("app.broker_" + provider)


def redirect_uri(provider: str) -> str:
    """Use an explicit origin, never Host/X-Forwarded-Host from the request."""
    if provider not in PROVIDERS:
        raise Error("Unknown brokerage.", 404)
    origin = os.getenv("APP_PUBLIC_URL", "").strip().rstrip("/")
    try:
        url = urlsplit(origin)
        port = url.port
    except ValueError:
        raise Error("Broker connections are awaiting Tau’s public address configuration.", 503) from None
    if (not url.hostname or url.username or url.password or url.path not in ("", "/")
            or url.query or url.fragment or any(ord(c) < 33 or ord(c) > 126 for c in origin)
            or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1")))
            or (port is not None and not 1 <= port <= 65535)):
        raise Error("Broker connections are awaiting Tau’s public address configuration.", 503)
    return origin + "/auth/brokers/" + provider + "/callback"


def _config(provider: str) -> dict:
    adapter = _adapter(provider)
    result = adapter.status()
    if not result["configured"]:
        return {"configured": False, "reason": result.get("reason", "Broker app setup is required.")}
    try:
        redirect_uri(provider)
    except Error as exc:
        return {"configured": False, "reason": str(exc)}
    if not vault.configured():
        return {"configured": False, "reason": "Broker connections are awaiting secure storage setup."}
    return {"configured": bool(result["configured"]), "reason": result.get("reason", "")}


def _iso(value) -> str | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return None


def list_brokers(cur, user_id: int) -> dict:
    rows = store.list_connections(cur, user_id)
    providers = []
    for provider, definition in PROVIDERS.items():
        connections = []
        for row in rows:
            if row["provider"] != provider or row["environment"] not in definition["environments"]:
                continue
            # Only this explicit projection reaches a client. No decrypted grants
            # or arbitrary metadata from upstream services enter the response.
            meta = row.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (TypeError, ValueError):
                    meta = {}
            if not isinstance(meta, dict):
                meta = {}
            scopes = meta.get("scopes", [])
            scopes = [s for s in scopes if isinstance(s, str) and len(s) <= 100][:30] if isinstance(scopes, list) else []
            expiry = meta.get("expires_at")
            expired = isinstance(expiry, (int, float)) and not isinstance(expiry, bool) and expiry <= time.time()
            connections.append({
                "environment": row["environment"], "connected": bool(row.get("connected")),
                "account_label": str(meta.get("account_label") or "Authorized account")[:100],
                "verification": str(meta.get("verification") or "authorization_received")[:40],
                "authorized_at": _iso(row.get("connected_at")), "expires_at": _iso(expiry),
                "expired": expired, "scopes": scopes, "trading_enabled": False,
            })
        providers.append({"id": provider, **definition, **_config(provider), "connections": connections})
    return {"providers": providers}


def _environment(provider: str, environment: str) -> None:
    if provider not in PROVIDERS:
        raise Error("Unknown brokerage.", 404)
    if not isinstance(environment, str) or environment not in PROVIDERS[provider]["environments"]:
        raise Error("Choose an available account environment.")


def _session(session_hash: str) -> None:
    if not isinstance(session_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", session_hash):
        raise Error("Please sign in again before connecting a brokerage.", 401)


def connect(conn, user_id: int, provider: str, environment: str, session_hash: str,
            permission: str = "read") -> dict:
    _environment(provider, environment)
    _session(session_hash)
    if permission not in ("read", "trading"):
        raise Error("Choose an available account permission.")
    config = _config(provider)
    if not config["configured"]:
        raise Error(config["reason"], 503)
    callback = redirect_uri(provider)
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode("ascii")).hexdigest()
    adapter = _adapter(provider)
    try:
        started = (adapter.begin(callback, state, environment, permission=permission) if provider == "alpaca"
                   else adapter.begin(callback, state, environment))
    except adapter.Error as exc:
        raise Error(str(exc), 503) from None
    # Bind the exact callback URI too, so configuration changes cannot redirect
    # an in-flight code exchange to a newly selected origin.
    private = {"provider_private": started["private"], "redirect_uri": callback, "permission": permission}
    encrypted = vault.encrypt(user_id, provider, environment, "state", private)
    with repo.transaction(conn) as cur:
        store.save_attempt(cur, user_id, provider, environment, state_hash, session_hash, encrypted)
    return {"authorization_url": started["authorization_url"]}


def callback(conn, user_id: int, provider: str, query: dict, session_hash: str) -> str:
    _adapter(provider)
    _session(session_hash)
    state = query.get("state", "")
    if not isinstance(state, str) or not STATE_PATTERN.fullmatch(state):
        return "expired"
    state_hash = hashlib.sha256(state.encode("ascii")).hexdigest()
    # Commit consumption BEFORE any network call. A retry/replay cannot exchange
    # the same code concurrently. Other users/sessions cannot burn this state.
    with repo.transaction(conn) as cur:
        attempt = store.consume_attempt(cur, user_id, provider, state_hash, session_hash)
    if attempt is None:
        return "expired"
    if query.get("error") or query.get("denied"):
        return "cancelled"
    environment = attempt["environment"]
    adapter = _adapter(provider)
    try:
        private = vault.decrypt(user_id, provider, environment, "state", attempt["private_enc"])
        credentials = adapter.exchange(query, private["provider_private"], private["redirect_uri"], environment)
        metadata = adapter.inspect(credentials, environment)
        encrypted = vault.encrypt(user_id, provider, environment, "tokens", credentials)
    except Exception:
        # Provider HTTP/crypto errors can carry sensitive request material. Log
        # only the fixed stage/provider; neither exception nor callback query.
        print("[broker] %s authorization or account verification failed" % provider, flush=True)
        return "failed"
    with repo.transaction(conn) as cur:
        saved = store.complete_attempt(cur, user_id, provider, environment, state_hash, encrypted, metadata)
    return "connected" if saved else "superseded"


def disconnect(conn, user_id: int, provider: str, environment: str) -> dict:
    _environment(provider, environment)
    with repo.transaction(conn) as cur:
        store.disconnect(cur, user_id, provider, environment)
    # Providers do not share a revocation contract. Deleting the local encrypted
    # grant is immediate; the user can also revoke the app in their broker UI.
    return {"disconnected": True, "provider_grant_revoked": False}


def main() -> None:
    """Network-free operator configuration check; does not load .env files."""
    import argparse
    parser = argparse.ArgumentParser(description="Check broker OAuth configuration without contacting providers.")
    parser.add_argument("command", choices=["status"])
    parser.parse_args()
    result = []
    for provider, definition in PROVIDERS.items():
        config = _config(provider)
        try:
            callback_url = redirect_uri(provider)
        except Error:
            callback_url = None
        result.append({"provider": provider, "name": definition["name"], **config,
                       "callback_url": callback_url, "trading_enabled": False})
    print(json.dumps({"providers": result}, indent=2))


if __name__ == "__main__":
    main()
