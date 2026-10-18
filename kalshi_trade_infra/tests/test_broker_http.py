"""Actual HTTP dispatch, with synthetic auth/database and no broker requests."""
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
import requests

from app import server


@pytest.fixture
def web(monkeypatch):
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: {"id": 7})
    calls = []
    monkeypatch.setattr(server.broker_oauth, "connect", lambda *a, **kw: calls.append((a, kw)) or {
        "authorization_url": "https://app.alpaca.markets/oauth/authorize?state=synthetic-state"})
    monkeypatch.setattr(server.broker_oauth, "callback", lambda *a, **kw: calls.append((a, kw)) or "connected")
    monkeypatch.setattr(server.broker_oauth, "disconnect", lambda *a: calls.append(a) or {"disconnected": True})
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield SimpleNamespace(url="http://127.0.0.1:%s" % http.server_port, calls=calls,
                          headers={"Cookie": "rsid=synthetic-session", "X-Recursive": "1"})
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)


def test_connect_and_callback_use_real_dispatch_without_leaking_query_or_caching(web, capsys):
    response = requests.post(web.url + "/api/brokers/alpaca/connect", json={"environment": "paper"},
                             headers=web.headers, timeout=2)
    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith("https://app.alpaca.markets/")
    assert response.headers["Cache-Control"] == "no-store"
    response = requests.get(web.url + "/auth/brokers/alpaca/callback?code=private-code&state=private-state",
                            headers=web.headers, allow_redirects=False, timeout=2)
    assert response.status_code == 302
    assert response.headers["Location"] == "/settings/account?broker=alpaca&broker_status=connected"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    assert "private-code" not in capsys.readouterr().out


@pytest.mark.parametrize("path,method", [
    ("/api/brokers", "GET"), ("/api/brokers/alpaca/connect", "POST"),
    ("/api/brokers/alpaca/disconnect", "POST"), ("/auth/brokers/alpaca/callback", "GET"),
])
def test_broker_endpoints_reject_missing_user_before_provider_or_storage(web, path, method):
    response = requests.request(method, web.url + path, headers={"X-Recursive": "1"}, timeout=2)
    assert response.status_code == 401
    assert not web.calls


@pytest.mark.parametrize("path", ["/api/brokers/alpaca/connect", "/api/brokers/alpaca/disconnect"])
def test_mutations_keep_the_csrf_header_requirement(web, path):
    response = requests.post(web.url + path, json={"environment": "paper"},
                             headers={"Cookie": web.headers["Cookie"]}, timeout=2)
    assert response.status_code == 403
    assert not web.calls


def test_duplicate_oauth_query_parameters_rejected_before_state_consumption(web):
    response = requests.get(web.url + "/auth/brokers/alpaca/callback?code=one&code=two&state=state",
                            headers=web.headers, allow_redirects=False, timeout=2)
    assert response.status_code == 400 and not web.calls


def test_provider_not_in_registry_is_not_a_redirect_or_api_target(web):
    response = requests.post(web.url + "/api/brokers/unknown/connect", json={}, headers=web.headers, timeout=2)
    assert response.status_code == 404 and not web.calls
