"""Robinhood's official Trading MCP OAuth connection, without tool execution.

This is an approved-client integration, not Robinhood's unrelated crypto API.
Register/approve the hosted Tau client with Robinhood before setting its client
ID. Provider discovery is constrained to the published Robinhood authorities.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import requests

RESOURCE = "https://agent.robinhood.com/mcp/trading"
RESOURCE_METADATA = "https://agent.robinhood.com/.well-known/oauth-protected-resource/mcp/trading"
SERVER_METADATA = "https://agent.robinhood.com/.well-known/oauth-authorization-server"
AUTHORIZE = "https://robinhood.com/oauth"
TOKEN = "https://api.robinhood.com/oauth2/token/"
SCOPE = "internal"
_TIMEOUT = (5, 20)
_MAX_RESPONSE = 262_144


class Error(ValueError):
    """Safe public error; provider response bodies and credentials are excluded."""


def _text(value: object, *, limit: int = 8192) -> str:
    if (not isinstance(value, str) or not value or len(value) > limit
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise Error("Robinhood returned an invalid authorization response.")
    return value


def _client_id() -> str:
    value = os.environ.get("ROBINHOOD_OAUTH_CLIENT_ID", "").strip()
    if not value or os.environ.get("ROBINHOOD_OAUTH_PLATFORM_APPROVED") != "1":
        raise Error("Robinhood requires an approved Tau OAuth client registration.")
    return _text(value, limit=512)


def status() -> dict:
    """Check operator configuration without contacting or registering a provider."""
    try:
        _client_id()
    except Error as exc:
        return {"configured": False, "reason": str(exc)}
    return {"configured": True, "reason": "", "environments": ["live"]}


def _request(method: str, url: str, **kwargs) -> dict:
    # Call sites use constants only. No discovered URL can receive credentials.
    if url not in {RESOURCE_METADATA, SERVER_METADATA, TOKEN, RESOURCE}:
        raise Error("Robinhood authorization endpoint is not allowed.")
    try:
        response = requests.request(method, url, timeout=_TIMEOUT,
                                    allow_redirects=False, stream=True, **kwargs)
    except requests.RequestException:
        raise Error("Robinhood authorization service is unavailable.") from None
    try:
        if response.status_code != 200:
            raise Error("Robinhood declined the authorization request. Reconnect to try again.")
        is_sse = "text/event-stream" in response.headers.get("Content-Type", "").lower()
        buffer, count, deadline = b"", 0, time.monotonic() + 25
        payload = None
        # Consume only through initialize's result. An SSE server is allowed to
        # leave the stream open afterwards; waiting for EOF would hang the flow.
        for chunk in response.iter_content(chunk_size=2048):
            count += len(chunk)
            if count > _MAX_RESPONSE or time.monotonic() > deadline:
                raise ValueError
            buffer += chunk
            if is_sse:
                buffer = buffer.replace(b"\r\n", b"\n")
                while b"\n\n" in buffer:
                    event, buffer = buffer.split(b"\n\n", 1)
                    data = b"\n".join(line[5:].lstrip(b" ") for line in event.splitlines()
                                      if line.startswith(b"data:"))
                    item = json.loads(data) if data else None
                    if isinstance(item, dict) and item.get("id") == "tau-broker-connection":
                        payload = item
                        break
                if payload is not None:
                    break
        if not is_sse:
            payload = json.loads(buffer)
        if not isinstance(payload, dict):
            raise Error("Robinhood returned an invalid authorization response.")
        return payload
    except (ValueError, TypeError, KeyError, requests.RequestException):
        raise Error("Robinhood returned an invalid authorization response.") from None
    finally:
        response.close()


def _discover() -> None:
    resource = _request("GET", RESOURCE_METADATA, headers={"Accept": "application/json"})
    metadata = _request("GET", SERVER_METADATA, headers={"Accept": "application/json"})
    def contains(mapping: dict, field: str, expected: str) -> bool:
        values = mapping.get(field)
        return isinstance(values, list) and expected in values

    if (resource.get("resource") != RESOURCE
            or not contains(resource, "authorization_servers", RESOURCE)
            or metadata.get("issuer") != RESOURCE
            or metadata.get("authorization_endpoint") != AUTHORIZE
            or metadata.get("token_endpoint") != TOKEN
            or metadata.get("authorization_response_iss_parameter_supported") is not True
            or not contains(metadata, "code_challenge_methods_supported", "S256")
            or not contains(metadata, "grant_types_supported", "authorization_code")
            or not contains(metadata, "token_endpoint_auth_methods_supported", "none")
            or not contains(metadata, "scopes_supported", SCOPE)):
        raise Error("Robinhood authorization configuration changed. Contact Tau support.")


def _environment(environment: str) -> None:
    if environment != "live":
        raise Error("Robinhood's Trading MCP connection uses an Agentic account, not paper trading.")


def begin(redirect_uri: str, state: str, environment: str) -> dict:
    """Create PKCE authorization; no dynamic client registration or account write."""
    _environment(environment)
    client_id = _client_id()
    _discover()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return {
        "authorization_url": AUTHORIZE + "?" + urlencode({
            "response_type": "code", "client_id": client_id,
            "redirect_uri": redirect_uri, "state": state, "scope": SCOPE,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "resource": RESOURCE,
        }),
        "private": {"code_verifier": verifier, "client_id": client_id},
    }


def _credentials(payload: dict) -> dict:
    if str(payload.get("token_type", "")).lower() != "bearer":
        raise Error("Robinhood did not issue a supported access token.")
    result = {"access_token": _text(payload.get("access_token")),
              "token_type": "Bearer", "scope": SCOPE}
    if "scope" in payload and payload["scope"] != SCOPE:
        raise Error("Robinhood returned an unexpected permission scope.")
    if payload.get("refresh_token"):
        result["refresh_token"] = _text(payload["refresh_token"])
    try:
        expires_in = int(payload["expires_in"])
        if isinstance(payload["expires_in"], bool) or not 0 < expires_in <= 31_536_000:
            raise ValueError
        result["expires_at"] = int(time.time()) + expires_in
    except (KeyError, TypeError, ValueError, OverflowError):
        raise Error("Robinhood did not issue a valid token expiration.") from None
    return result


def exchange(query: dict, private: dict, redirect_uri: str, environment: str) -> dict:
    _environment(environment)
    client_id = _client_id()
    if query.get("error"):
        raise Error("Robinhood authorization was declined or cancelled.")
    if query.get("iss") != RESOURCE:
        raise Error("Robinhood authorization issuer did not match.")
    if private.get("client_id") != client_id:
        raise Error("Robinhood OAuth registration changed. Restart the connection.")
    payload = _request("POST", TOKEN, headers={"Accept": "application/json"}, data={
        "grant_type": "authorization_code", "client_id": client_id,
        "code": _text(query.get("code"), limit=4096), "redirect_uri": redirect_uri,
        "code_verifier": _text(private.get("code_verifier"), limit=128),
        "resource": RESOURCE,
    })
    return _credentials(payload)


def refresh(credentials: dict, environment: str) -> dict:
    """Explicit renewal for a future worker; never executes an MCP tool."""
    _environment(environment)
    payload = _request("POST", TOKEN, headers={"Accept": "application/json"}, data={
        "grant_type": "refresh_token", "client_id": _client_id(),
        "refresh_token": _text(credentials.get("refresh_token")), "resource": RESOURCE,
    })
    result = _credentials(payload)
    if "refresh_token" not in result:
        result["refresh_token"] = _text(credentials.get("refresh_token"))
    return result


def inspect(credentials: dict, environment: str) -> dict:
    """Validate bearer access through MCP initialize, without calling any tool."""
    _environment(environment)
    token = _text(credentials.get("access_token"))
    payload = _request("POST", RESOURCE, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream", "Content-Type": "application/json",
    }, json={
        "jsonrpc": "2.0", "id": "tau-broker-connection", "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "Tau", "version": "1.0"}},
    })
    result = payload.get("result")
    if (payload.get("jsonrpc") != "2.0" or payload.get("id") != "tau-broker-connection"
            or payload.get("error") or not isinstance(result, dict)
            or not isinstance(result.get("capabilities"), dict)
            or result.get("protocolVersion") not in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")):
        raise Error("Robinhood did not verify the Trading MCP connection.")
    return {"verification": "mcp_initialized", "scope": SCOPE, "scopes": [SCOPE],
            "expires_at": credentials.get("expires_at"),
            "account_label": "Robinhood Agentic account", "account_verified": False}
