"""Connection lifecycle/API tests with a synthetic provider and repository."""
import base64
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.adapters.brokers import broker_oauth as oauth
from app.adapters.brokers import broker_vault as vault
from app import server

SESSION = hashlib.sha256(b"synthetic-session").hexdigest()


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "https://tau.example")
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    attempts, links, calls = {}, {}, []

    @contextmanager
    def transaction(conn):
        yield None

    def save(cur, uid, provider, env, state_hash, session_hash, private_enc):
        attempts[state_hash] = dict(user_id=uid, provider=provider, environment=env,
                                    session_hash=session_hash, private_enc=private_enc)
        previous = links.get((uid, provider, env), {})
        links[(uid, provider, env)] = {**previous, "attempt": state_hash}

    def consume(cur, uid, provider, state_hash, session_hash):
        attempt = attempts.get(state_hash)
        if not attempt or (attempt["user_id"], attempt["provider"], attempt["session_hash"]) != (uid, provider, session_hash):
            return None
        if links.get((uid, provider, attempt["environment"]), {}).get("attempt") != state_hash:
            return None
        return attempts.pop(state_hash)

    def complete(cur, uid, provider, env, state_hash, tokens_enc, metadata):
        link = links.get((uid, provider, env))
        if not link or link.get("attempt") != state_hash:
            return False
        link.update(tokens_enc=tokens_enc, metadata=metadata, connected_at=datetime(2026, 10, 17))
        return True

    def disconnect(cur, uid, provider, env):
        links.pop((uid, provider, env), None)

    def begin(uri, state, env, **kwargs):
        calls.append(("begin", env, kwargs))
        return {"authorization_url": "https://app.alpaca.markets/oauth/authorize?state=" + state,
                "private": {"verifier": "synthetic-private-verifier"}}

    def exchange(query, private, uri, env):
        calls.append(("exchange", env, private, uri))
        return {"access_token": "synthetic-private-token", "scope": "data"}

    def inspect(credentials, env):
        calls.append(("inspect", env))
        return {"account_label": "••••1234", "scopes": ["data"], "verification": "account_verified"}

    adapter = SimpleNamespace(status=lambda: {"configured": True, "reason": ""}, begin=begin,
                              exchange=exchange, inspect=inspect, Error=ValueError)
    monkeypatch.setattr(oauth, "_adapter", lambda provider: adapter)
    monkeypatch.setattr(oauth.repo, "transaction", transaction)
    monkeypatch.setattr(oauth.store, "save_attempt", save)
    monkeypatch.setattr(oauth.store, "consume_attempt", consume)
    monkeypatch.setattr(oauth.store, "complete_attempt", complete)
    monkeypatch.setattr(oauth.store, "disconnect", disconnect)
    return SimpleNamespace(attempts=attempts, links=links, calls=calls, adapter=adapter)


def begin(provider="alpaca", environment="paper", **kwargs):
    result = oauth.connect(None, 7, provider, environment, SESSION, **kwargs)
    return parse_qs(urlsplit(result["authorization_url"]).query)["state"][0]


def test_single_use_grant_is_encrypted_and_bound_to_the_originating_session(flow):
    state = begin()
    key = hashlib.sha256(state.encode()).hexdigest()
    assert state not in flow.attempts and key in flow.attempts
    assert b"synthetic-private-verifier" not in flow.attempts[key]["private_enc"]
    query = {"state": state, "code": "synthetic-code"}
    assert oauth.callback(None, 7, "alpaca", query, SESSION) == "connected"
    assert oauth.callback(None, 7, "alpaca", query, SESSION) == "expired"
    assert len([c for c in flow.calls if c[0] == "exchange"]) == 1
    token = flow.links[(7, "alpaca", "paper")]["tokens_enc"]
    assert b"synthetic-private-token" not in token
    assert vault.decrypt(7, "alpaca", "paper", "tokens", token)["access_token"] == "synthetic-private-token"


@pytest.mark.parametrize("uid,provider,session", [
    (8, "alpaca", SESSION), (7, "robinhood", SESSION), (7, "alpaca", "b" * 64),
])
def test_foreign_callback_cannot_use_or_consume_the_pending_grant(flow, uid, provider, session):
    state = begin()
    query = {"state": state, "code": "synthetic-code"}
    assert oauth.callback(None, uid, provider, query, session) == "expired"
    assert oauth.callback(None, 7, "alpaca", query, SESSION) == "connected"


def test_cancellation_is_single_use_and_never_calls_token_endpoint(flow):
    state = begin()
    assert oauth.callback(None, 7, "alpaca", {"state": state, "error": "secret-provider-message"}, SESSION) == "cancelled"
    assert oauth.callback(None, 7, "alpaca", {"state": state, "code": "code"}, SESSION) == "expired"
    assert all(call[0] != "exchange" for call in flow.calls)


def test_disconnect_fences_an_inflight_exchange(flow):
    state = begin()
    original = flow.adapter.exchange
    def exchange(*args):
        oauth.disconnect(None, 7, "alpaca", "paper")
        return original(*args)
    flow.adapter.exchange = exchange
    assert oauth.callback(None, 7, "alpaca", {"state": state, "code": "code"}, SESSION) == "superseded"
    assert not flow.links


def test_newer_connection_attempt_fences_an_inflight_exchange(flow):
    state = begin()
    original = flow.adapter.exchange
    def exchange(*args):
        begin()
        return original(*args)
    flow.adapter.exchange = exchange
    assert oauth.callback(None, 7, "alpaca", {"state": state, "code": "code"}, SESSION) == "superseded"
    assert "tokens_enc" not in flow.links[(7, "alpaca", "paper")]


def test_provider_failure_does_not_expose_token_or_exception(flow, capsys):
    state = begin()
    def inspect(*args):
        raise ValueError("access_token=synthetic-private-token")
    flow.adapter.inspect = inspect
    assert oauth.callback(None, 7, "alpaca", {"state": state, "code": "private-code"}, SESSION) == "failed"
    captured = capsys.readouterr()
    assert "private" not in captured.out + captured.err
    assert "tokens_enc" not in flow.links[(7, "alpaca", "paper")]


def test_grants_use_the_callback_saved_at_initiation(flow, monkeypatch):
    state = begin()
    monkeypatch.setenv("APP_PUBLIC_URL", "https://new-origin.example")
    assert oauth.callback(None, 7, "alpaca", {"state": state, "code": "code"}, SESSION) == "connected"
    exchange = next(call for call in flow.calls if call[0] == "exchange")
    assert exchange[3] == "https://tau.example/auth/brokers/alpaca/callback"


def test_paper_and_live_are_separate_grants(flow):
    paper = begin()
    live = begin(environment="live", permission="trading")
    assert oauth.callback(None, 7, "alpaca", {"state": paper, "code": "paper-code"}, SESSION) == "connected"
    assert oauth.callback(None, 7, "alpaca", {"state": live, "code": "live-code"}, SESSION) == "connected"
    oauth.disconnect(None, 7, "alpaca", "paper")
    assert set(flow.links) == {(7, "alpaca", "live")}


@pytest.mark.parametrize("url", ["", "http://tau.example", "https://user:secret@tau.example",
                                  "https://tau.example/path", "https://tau.example?query=1",
                                  "https://tau.example#fragment", "https://tau.example:99999"])
def test_untrusted_or_incomplete_callback_configuration_blocks_connect(flow, monkeypatch, url):
    monkeypatch.setenv("APP_PUBLIC_URL", url)
    with pytest.raises(oauth.Error) as exc:
        begin()
    assert exc.value.status == 503 and not flow.attempts


def test_localhost_callback_supported_without_using_request_host(flow, monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "http://127.0.0.1:8090")
    assert oauth.redirect_uri("alpaca") == "http://127.0.0.1:8090/auth/brokers/alpaca/callback"


@pytest.mark.parametrize("provider,environment,permission", [
    ("unknown", "live", "read"), ("robinhood", "paper", "read"), ("ibkr", "paper", "read"),
    ("alpaca", [], "read"), ("alpaca", "paper", "admin"),
])
def test_bad_request_is_rejected_before_creating_a_grant(flow, provider, environment, permission):
    with pytest.raises(oauth.Error):
        begin(provider, environment, permission=permission)
    assert not flow.attempts


def test_listing_is_an_allowlisted_metadata_projection(flow, monkeypatch):
    monkeypatch.setattr(oauth.store, "list_connections", lambda cur, uid: [{
        "provider": "alpaca", "environment": "paper", "connected": True, "tokens_enc": b"secret-blob",
        "connected_at": datetime(2026, 10, 17), "metadata": {
            "scopes": ["data"], "verification": "account_verified", "account_label": "••••1234",
            "expires_at": 1, "access_token": "secret", "account_id": "private-id", "cash": 1e6,
        },
    }])
    result = oauth.list_brokers(None, 7)
    public = json.dumps(result)
    assert "secret" not in public and "private-id" not in public and "1000000" not in public
    row = result["providers"][0]["connections"][0]
    assert row["connected"] and row["expired"] and row["trading_enabled"] is False
    assert row["expires_at"].startswith("1970-")


def context(body=None, query=None):
    handler = SimpleNamespace(cookies=lambda: {"rsid": "synthetic-session"})
    return server.Ctx(None, {"id": 7}, ("alpaca",), query or {}, body or {}, handler)


def test_connect_route_binds_user_and_session_and_maps_configuration_errors(monkeypatch):
    received = []
    monkeypatch.setattr(server.broker_oauth, "connect", lambda *a, **kw: received.append((a, kw)) or {"authorization_url": "https://app.alpaca.markets/oauth/authorize"})
    assert server.broker_connect(context({"environment": "paper", "permission": "trading"}))["authorization_url"].startswith("https:")
    assert received[0] == ((None, 7, "alpaca", "paper", SESSION), {"permission": "trading"})
    def unavailable(*a, **kw):
        raise oauth.Error("App setup pending.", 503)
    monkeypatch.setattr(server.broker_oauth, "connect", unavailable)
    with pytest.raises(server.ApiError) as exc:
        server.broker_connect(context())
    assert exc.value.status == 503


def test_callback_route_redirects_without_reflecting_secrets(monkeypatch):
    monkeypatch.setattr(server.broker_oauth, "callback", lambda *a: "failed")
    result = server.broker_callback(context(query={"code": "private-code", "state": "private-state", "error": "private-error"}))
    assert result == ("redirect", "/settings/account?broker=alpaca&broker_status=failed")


def test_all_broker_routes_require_a_signed_in_user():
    for method, pattern, fn, required in server.ROUTES:
        if "/brokers" in pattern.pattern:
            assert required is True


def test_connect_without_session_cookie_fails_before_provider_call(monkeypatch):
    ctx = context()
    ctx.handler = SimpleNamespace(cookies=lambda: {})
    with pytest.raises(server.ApiError) as exc:
        server.broker_connect(ctx)
    assert exc.value.status == 401
