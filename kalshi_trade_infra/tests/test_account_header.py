"""Every JSON reply names the account it was read as (X-Tau-Account), so a tab still showing another account (a
sign-in as someone else in another tab) can drop it instead of painting it under the old name (api() in app.js and
app.meridian.js). Through the real dispatch, with synthetic sessions and no database or outside requests."""
import re
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
import requests

from app import server

SESSIONS = {"session-seven": {"id": 7}, "session-eight": {"id": 8}}


@pytest.fixture
def web(monkeypatch):
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    hashed = {server.auth.hash_token(k): v for k, v in SESSIONS.items()}
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: hashed.get(token))

    def refused(ctx):
        raise server.ApiError(404, "No such strategy.")
    routes = [
        ("GET", re.compile("^/api/probe$"), lambda ctx: {"ok": True}, True),
        ("POST", re.compile("^/api/probe$"), lambda ctx: {"ok": True}, True),
        ("GET", re.compile("^/api/refused$"), refused, True),
        ("GET", re.compile("^/api/public$"), lambda ctx: {"ok": True}, False),
    ]
    monkeypatch.setattr(server, "ROUTES", routes)
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%s" % http.server_port
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)


def cookie(token):
    return {"Cookie": "%s=%s" % (server.auth.SESSION_COOKIE, token), "X-Recursive": "1"}


def test_each_reply_names_the_account_it_was_read_as(web):
    assert requests.get(web + "/api/probe", headers=cookie("session-seven"), timeout=2).headers["X-Tau-Account"] == "7"
    assert requests.get(web + "/api/probe", headers=cookie("session-eight"), timeout=2).headers["X-Tau-Account"] == "8"
    # A write, and a refusal Tau answered, name it too: the page says whether the change was made on that account.
    assert requests.post(web + "/api/probe", json={}, headers=cookie("session-eight"), timeout=2).headers["X-Tau-Account"] == "8"
    refused = requests.get(web + "/api/refused", headers=cookie("session-seven"), timeout=2)
    assert refused.status_code == 404 and refused.headers["X-Tau-Account"] == "7"


def test_no_account_is_named_when_none_is_signed_in(web):
    out = requests.get(web + "/api/probe", headers=cookie("expired"), timeout=2)
    assert out.status_code == 401 and "X-Tau-Account" not in out.headers
    assert "X-Tau-Account" not in requests.get(web + "/api/public", timeout=2).headers
    assert "X-Tau-Account" not in requests.get(web + "/api/nowhere", headers=cookie("session-seven"), timeout=2).headers


def test_a_kept_alive_socket_never_carries_the_last_request_s_account(web):
    with requests.Session() as s:  # one connection, one handler, several requests
        assert s.get(web + "/api/probe", headers=cookie("session-seven"), timeout=2).headers["X-Tau-Account"] == "7"
        assert "X-Tau-Account" not in s.get(web + "/api/public", timeout=2).headers
        assert "X-Tau-Account" not in s.get(web + "/api/probe", headers=cookie("expired"), timeout=2).headers
