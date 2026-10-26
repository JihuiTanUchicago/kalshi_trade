"""Offline tests against synthetic official Trading MCP protocol responses."""
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from app.adapters.brokers import broker_robinhood as broker


class Response:
    def __init__(self, payload, status=200, *, sse=False, chunks=None):
        self.status_code = status
        self.headers = {"Content-Type": "text/event-stream" if sse else "application/json"}
        self.chunks = chunks if chunks is not None else [json.dumps(payload).encode()]
        self.closed = False

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("ROBINHOOD_OAUTH_CLIENT_ID", "synthetic-approved-client")
    monkeypatch.setenv("ROBINHOOD_OAUTH_PLATFORM_APPROVED", "1")


def discovery():
    return [
        Response({"resource": broker.RESOURCE, "authorization_servers": [broker.RESOURCE]}),
        Response({"issuer": broker.RESOURCE, "authorization_endpoint": broker.AUTHORIZE,
                  "token_endpoint": broker.TOKEN, "code_challenge_methods_supported": ["S256"],
                  "authorization_response_iss_parameter_supported": True,
                  "grant_types_supported": ["authorization_code", "refresh_token"],
                  "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": ["internal"]}),
    ]


def transport(monkeypatch, responses):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(broker.requests, "request", request)
    return calls


def test_operator_must_register_approved_client_and_never_reuses_data_key(monkeypatch):
    monkeypatch.delenv("ROBINHOOD_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ROBINHOOD_OAUTH_PLATFORM_APPROVED", raising=False)
    monkeypatch.setenv("APCA_API_KEY_ID", "unrelated-market-data-key")
    assert broker.status()["configured"] is False
    monkeypatch.setenv("ROBINHOOD_OAUTH_CLIENT_ID", "synthetic-approved-client")
    assert broker.status()["configured"] is False


def test_pkce_authorize_exact_discovery_resource_and_no_registration(configured, monkeypatch):
    responses = discovery()
    saved = list(responses)
    calls = transport(monkeypatch, responses)
    result = broker.begin("https://tau.example/auth/brokers/robinhood/callback", "pending-state", "live")
    query = parse_qs(urlsplit(result["authorization_url"]).query)
    verifier = result["private"]["code_verifier"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected]
    assert query["code_challenge_method"] == ["S256"]
    assert query["resource"] == [broker.RESOURCE]
    assert query["scope"] == ["internal"]
    assert query["state"] == ["pending-state"]
    assert verifier not in result["authorization_url"]
    assert [(method, url) for method, url, _ in calls] == [
        ("GET", broker.RESOURCE_METADATA), ("GET", broker.SERVER_METADATA)]
    assert all(item.closed for item in saved)
    assert all(kwargs["allow_redirects"] is False for _, _, kwargs in calls)


@pytest.mark.parametrize("field,value", [("issuer", "https://attacker.example"),
                                        ("token_endpoint", "https://attacker.example/steal"),
                                        ("code_challenge_methods_supported", ["plain"]),
                                        ("grant_types_supported", None)])
def test_discovery_changes_fail_closed_before_token_or_browser_redirect(configured, monkeypatch, field, value):
    responses = discovery()
    payload = json.loads(responses[1].chunks[0])
    payload[field] = value
    responses[1] = Response(payload)
    calls = transport(monkeypatch, responses)
    with pytest.raises(broker.Error, match="configuration changed"):
        broker.begin("https://tau.example/callback", "state", "live")
    assert len(calls) == 2


def test_exchange_uses_pkce_public_client_and_preserves_refresh_token(configured, monkeypatch):
    calls = transport(monkeypatch, [Response({"access_token": "synthetic-bearer",
                                             "token_type": "bearer", "refresh_token": "synthetic-refresh",
                                             "expires_in": 3600, "scope": "internal"})])
    monkeypatch.setattr(broker.time, "time", lambda: 1000)
    result = broker.exchange({"code": "synthetic-code", "iss": broker.RESOURCE},
                             {"code_verifier": "synthetic-verifier", "client_id": "synthetic-approved-client"},
                             "https://tau.example/callback", "live")
    assert result["expires_at"] == 4600
    assert result["refresh_token"] == "synthetic-refresh"
    assert calls[0][0:2] == ("POST", broker.TOKEN)
    data = calls[0][2]["data"]
    assert data["code_verifier"] == "synthetic-verifier"
    assert "client_secret" not in data
    assert "synthetic-bearer" not in calls[0][1]


def test_wrong_issuer_and_client_rotation_do_not_exchange_code(configured, monkeypatch):
    calls = transport(monkeypatch, [])
    for query, private in [({"code": "c", "iss": "https://attacker.example"}, {}),
                           ({"code": "c"}, {}),
                           ({"code": "c", "iss": broker.RESOURCE}, {"client_id": "replaced-client"})]:
        with pytest.raises(broker.Error):
            broker.exchange(query, private, "https://tau.example/callback", "live")
    assert calls == []


def test_mcp_verification_only_initializes_and_never_calls_tools(configured, monkeypatch):
    payload = {"jsonrpc": "2.0", "id": "tau-broker-connection", "result": {
        "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
        "instructions": "untrusted remote text must never become public connection metadata"}}
    # The iterator would raise if the implementation waited for stream EOF.
    def events():
        yield b": keepalive\r\n\r\n"
        yield ("event: message\r\ndata: " + json.dumps(payload) + "\r\n\r\n").encode()
        raise AssertionError("Do not wait for an open SSE stream after its initialize result")
    response = Response(None, sse=True, chunks=events())
    calls = transport(monkeypatch, [response])
    result = broker.inspect({"access_token": "synthetic-bearer"}, "live")
    assert result["verification"] == "mcp_initialized"
    assert result["account_verified"] is False
    assert "instructions" not in result
    assert calls[0][2]["json"]["method"] == "initialize"
    assert calls[0][2]["headers"]["Authorization"] == "Bearer synthetic-bearer"
    assert len(calls) == 1 and response.closed


@pytest.mark.parametrize("response", [Response({"secret": "do-not-show"}, 302),
                                      Response({"secret": "do-not-show"}, 401),
                                      Response(None, chunks=[b"x" * 262_145])])
def test_provider_error_bodies_redirects_and_oversized_responses_are_private(configured, monkeypatch, response):
    transport(monkeypatch, [response])
    with pytest.raises(broker.Error) as error:
        broker.inspect({"access_token": "synthetic-bearer"}, "live")
    assert "do-not-show" not in str(error.value)
    assert "synthetic-bearer" not in str(error.value)
    assert response.closed


def test_network_exception_and_paper_scope_fail_safely(configured, monkeypatch):
    transport(monkeypatch, [requests.Timeout("secret-provider-request")])
    with pytest.raises(broker.Error, match="unavailable") as error:
        broker.begin("https://tau.example/callback", "state", "live")
    assert "secret-provider" not in str(error.value)
    with pytest.raises(broker.Error, match="not paper"):
        broker.begin("https://tau.example/callback", "state", "paper")


def test_refresh_uses_only_refresh_endpoint_and_keeps_unrotated_refresh(configured, monkeypatch):
    calls = transport(monkeypatch, [Response({"access_token": "new-synthetic-bearer",
                                             "token_type": "Bearer", "expires_in": 3600})])
    result = broker.refresh({"refresh_token": "old-synthetic-refresh"}, "live")
    assert result["refresh_token"] == "old-synthetic-refresh"
    assert calls[0][2]["data"]["grant_type"] == "refresh_token"
