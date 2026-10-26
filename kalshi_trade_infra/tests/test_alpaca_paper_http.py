"""Real HTTP dispatch/auth/CSRF with synthetic paper service and no database."""
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
import requests

from app import server
from app.research import agent
from app.adapters.alpaca import alpaca_paper


@pytest.fixture
def web(monkeypatch):
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: {"id": 7})
    calls = []

    def stub(name):
        def operation(*args):
            calls.append((name, args))
            return {"environment": "paper", "operation": name}
        return operation

    for name in ("overview", "create_order", "submit_order", "refresh_order", "cancel_order", "decide_proposal"):
        monkeypatch.setattr(server.alpaca_paper, name, stub(name))
    monkeypatch.setattr(server.repo, "get_proposal", lambda cur, uid, pid:
                        {"id": pid, "kind": "alpaca_paper", "status": "pending"})
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    yield SimpleNamespace(url="http://127.0.0.1:%s" % http.server_port, calls=calls, conn=connection,
                          headers={"Cookie": "rsid=synthetic-session", "X-Recursive": "1"})
    http.shutdown(); http.server_close(); thread.join(timeout=2)


PATHS = [
    ("GET", "/api/brokers/alpaca/paper", "overview"),
    ("POST", "/api/brokers/alpaca/paper/orders", "create_order"),
    ("POST", "/api/brokers/alpaca/paper/orders/42/submit", "submit_order"),
    ("POST", "/api/brokers/alpaca/paper/orders/42/refresh", "refresh_order"),
    ("POST", "/api/brokers/alpaca/paper/orders/42/cancel", "cancel_order"),
]


@pytest.mark.parametrize("method,path,operation", PATHS)
def test_paper_dispatch_passes_authenticated_owner_and_never_caches_account_data(web, method, path, operation):
    response = requests.request(method, web.url + path, headers=web.headers, json={}, timeout=2)
    assert response.status_code == 200 and response.json()["operation"] == operation
    assert response.headers["Cache-Control"] == "no-store"
    assert web.calls[0][1][:2] == (web.conn, 7)
    if operation not in ("overview", "create_order"):
        assert web.calls[0][1][2] == 42


@pytest.mark.parametrize("method,path,operation", PATHS)
def test_missing_session_never_reaches_paper_service(web, method, path, operation):
    response = requests.request(method, web.url + path, headers={"X-Recursive": "1"}, json={}, timeout=2)
    assert response.status_code == 401 and not web.calls


@pytest.mark.parametrize("method,path,operation", PATHS[1:])
def test_paper_mutations_require_existing_csrf_header(web, method, path, operation):
    response = requests.post(web.url + path, headers={"Cookie": web.headers["Cookie"]}, json={}, timeout=2)
    assert response.status_code == 403 and not web.calls


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_existing_chat_controls_use_durable_paper_service_outside_generic_transaction(web, decision):
    response = requests.post(web.url + "/api/proposals/13/" + decision, headers=web.headers, json={}, timeout=2)
    assert response.status_code == 200
    assert web.calls == [("decide_proposal", (web.conn, 7, 13, decision))]


def test_safe_service_failure_preserves_status_and_message(web, monkeypatch):
    def unavailable(*args):
        raise alpaca_paper.Error("Connect your paper account first.", 409)
    monkeypatch.setattr(server.alpaca_paper, "submit_order", unavailable)
    response = requests.post(web.url + "/api/brokers/alpaca/paper/orders/42/submit", headers=web.headers, json={}, timeout=2)
    assert response.status_code == 409 and "Connect your paper account" in response.text
    assert "Traceback" not in response.text


@pytest.mark.parametrize("path", ["/api/brokers/alpaca/live/orders", "/api/brokers/alpaca/paper/orders/42/replace"])
def test_no_equity_live_or_replacement_endpoint_is_installed(web, path):
    assert requests.post(web.url + path, headers=web.headers, json={}, timeout=2).status_code == 404
    assert not web.calls


def test_paper_assets_are_versioned_and_loaded_before_connection_mount(web):
    response = requests.get(web.url + "/settings/account", headers=web.headers, timeout=2)
    assert response.status_code == 200
    text = response.text
    assert "{{paper_" not in text and "/static/alpaca-paper.css?v=" in text
    assert text.index('/static/alpaca-paper.js?v=') < text.index('/static/broker-connections.js?v=')


@pytest.mark.parametrize("autopilot", [True, False])
def test_agent_action_only_proposes_regardless_of_kalshi_autopilot(monkeypatch, autopilot):
    calls = []
    monkeypatch.setattr(alpaca_paper, "propose_for_agent", lambda cur, uid, action:
                        calls.append((cur, uid, action)) or ("Paper order awaiting approval.", 13))
    action = {"type": " Alpaca_Paper_Order ", "symbol": "AAPL", "side": "buy", "qty": "1", "limit_price": "100"}
    assert agent.act(None, {"id": 7}, action, autopilot) == ("Paper order awaiting approval.", 13)
    assert calls == [(None, 7, action)]


def test_agent_proposal_failure_is_explained_without_executing(monkeypatch):
    def disconnected(*args):
        raise alpaca_paper.Error("Connect an Alpaca paper account first.", 409)
    monkeypatch.setattr(alpaca_paper, "propose_for_agent", disconnected)
    text, pid = agent.act(None, {"id": 7}, {"type": "alpaca_paper_order"}, True)
    assert pid is None and "Connect an Alpaca paper account" in text
    with pytest.raises(ValueError, match="durable broker order service"):
        agent.apply_proposal(None, 7, {"kind": "alpaca_paper"})
