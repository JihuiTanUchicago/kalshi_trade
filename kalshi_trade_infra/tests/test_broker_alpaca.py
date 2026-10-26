"""Offline protocol fixtures: no real OAuth codes, accounts or order calls."""
import pytest
import requests
from urllib.parse import parse_qs, urlsplit

from app.adapters.brokers import broker_alpaca as alpaca


class Response:
    def __init__(self, data=None, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("ALPACA_OAUTH_CLIENT_ID", "test-client")
    monkeypatch.setenv("ALPACA_OAUTH_CLIENT_SECRET", "synthetic-client-secret")


def test_market_data_keys_do_not_configure_an_oauth_app(monkeypatch):
    monkeypatch.delenv("ALPACA_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ALPACA_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("APCA_API_KEY_ID", "a-data-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "a-data-secret")
    assert alpaca.status()["configured"] is False


@pytest.mark.parametrize("permission,expected", [("read", ["data"]), ("trading", ["data trading"])])
def test_authorize_is_explicit_about_paper_scope_and_callback(configured, permission, expected):
    result = alpaca.begin("https://tau.example/auth/brokers/alpaca/callback", "random-state", "paper", permission)
    url = urlsplit(result["authorization_url"])
    query = parse_qs(url.query)
    assert url.scheme == "https" and url.netloc == "app.alpaca.markets"
    assert query["env"] == ["paper"] and query["scope"] == expected
    assert query["state"] == ["random-state"] and query["client_id"] == ["test-client"]
    assert "synthetic-client-secret" not in result["authorization_url"]
    assert "account:write" not in query["scope"][0]


def test_exchange_stays_server_side_then_checks_correct_environment(configured, monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"access_token": "synthetic-grant", "token_type": "bearer", "scope": "data"})

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"id": "synthetic-private-id", "account_number": "ABC01234", "cash": "1000000"})

    monkeypatch.setattr(alpaca.requests, "post", post)
    monkeypatch.setattr(alpaca.requests, "get", get)
    credentials = alpaca.exchange({"code": "synthetic-code"}, {"requested_scopes": ["data"]}, "https://tau.example/callback", "paper")
    metadata = alpaca.inspect(credentials, "paper")
    assert calls[0][0] == alpaca.TOKEN_URL
    assert calls[0][1]["data"]["client_secret"] == "synthetic-client-secret"
    assert calls[0][1]["data"]["redirect_uri"] == "https://tau.example/callback"
    assert calls[1][0] == "https://paper-api.alpaca.markets/v2/account"
    assert calls[1][1]["headers"]["Authorization"] == "Bearer synthetic-grant"
    assert all(call[1]["allow_redirects"] is False for call in calls)
    assert metadata["account_label"] == "Paper · ••••1234"
    assert metadata["verification"] == "account_verified"
    assert not {"id", "account_number", "cash", "access_token"} & metadata.keys()
    assert credentials["account_id"] == "synthetic-private-id"


@pytest.mark.parametrize("data", [
    {"access_token": "secret", "token_type": "bearer", "scope": "data trading"},
    {"access_token": "secret", "token_type": "bearer", "scope": ""},
    {"access_token": "header\r\ninjection", "token_type": "bearer", "scope": "data"},
    {"access_token": "secret", "token_type": "unknown", "scope": "data"},
    {"access_token": "secret", "token_type": "bearer", "scope": "data", "expires_in": -1},
    ["unexpected"],
])
def test_bad_grants_and_unrequested_permissions_are_refused(configured, monkeypatch, data):
    monkeypatch.setattr(alpaca.requests, "post", lambda *a, **kw: Response(data))
    with pytest.raises(alpaca.Error) as exc:
        alpaca.exchange({"code": "code"}, {"requested_scopes": ["data"]}, "https://tau.example/callback", "paper")
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("failure", [Response({"error": "secret-body"}, 302), Response({"error": "secret-body"}, 401)])
def test_provider_http_errors_do_not_reveal_body_or_follow_redirects(monkeypatch, failure):
    monkeypatch.setattr(alpaca.requests, "post", lambda *a, **kw: failure)
    with pytest.raises(alpaca.Error) as exc:
        alpaca.exchange({"code": "code"}, {"requested_scopes": ["data"]}, "https://tau.example/callback", "paper")
    assert "secret-body" not in str(exc.value)


def test_transport_errors_are_sanitized(monkeypatch):
    def broken(*args, **kwargs):
        raise requests.ConnectionError("sensitive HTTP request")
    monkeypatch.setattr(alpaca.requests, "get", broken)
    with pytest.raises(alpaca.Error) as exc:
        alpaca.inspect({"access_token": "private"}, "live")
    assert "sensitive" not in str(exc.value)


@pytest.mark.parametrize("environment", ["demo", "https://evil.example", None, []])
def test_no_arbitrary_broker_api_host(environment):
    with pytest.raises(alpaca.Error):
        alpaca.begin("https://tau.example/callback", "state", environment)
