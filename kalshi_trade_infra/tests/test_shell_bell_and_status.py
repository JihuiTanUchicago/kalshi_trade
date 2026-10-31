"""Every signed-in shell carries the bell's list (/api/notifications) beside its page's first reads, and the
dashboard's carries the autopilot status, so neither is one more round trip after paint (app.web.shell_reads).

Through the real handlers, over the counting cursor the hot-endpoint budgets use (payments on, live trading on,
a Kalshi key, autopilot on, a paper and a demo deployment, no cash memo kept): what the shell carries is what the
endpoints answer; each shell stays in its statement budget, the bell adding its two statements explicitly; and
nothing under any of it reaches outside the process (no Kalshi, Stripe, model, AWS or any other HTTP).

Measured 2026-10-30 on a local seeded account (autopilot on, 3 paper + 1 demo deployment, 400 closed trades,
40 notices, 20 sessions; MariaDB, warm memos): the bell's read is 2 statements, ~2ms; the autopilot status 7,
~5ms. Shells (session + /api/me + carried reads): dashboard 27 -> 29, Deploy 11 -> 13, Research 12 -> 14.
Carrying the status on every page too would add 7 more (up to ~14 cold): over the ~3-statement line a page that
doesn't draw it above its figures should pay, so only the dashboard carries it.
"""
import http.client
import json
import re
import socket
import urllib.request
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest
import requests

from app import server
from app.services import book_memo
from app.web import shell_reads, webperf
from app.web.routes import chat as chat_routes
from tests.test_hot_endpoint_query_budget import (
    CREDITS, PULSE, CountingCursor, _board_rows, _pulse_row, production)  # noqa: F401 - production is a fixture

USER = {"id": 7, "email": "trader@example.invalid", "name": "T", "username": "t", "picture_url": None,
        "autopilot": 1, "autopilot_live": 1, "autopilot_daily_loss_limit": 50, "autopilot_model": None,
        "autopilot_focus": None, "ui_theme": "tau", "email_opt_out": 0, "created_at": None}
NOTICES = [
    {"id": 12, "kind": "paused", "body": "Fade tails was paused: it hit its loss guard.", "link": "/strategies/9",
     "created_at": server.datetime(2026, 10, 24, 20), "read_at": None},
    {"id": 11, "kind": "paused", "body": "Fade tails was paused: it hit its loss guard.", "link": "/strategies/9",
     "created_at": server.datetime(2026, 10, 24, 19), "read_at": None},
    {"id": 10, "kind": "deployed", "body": "Autopilot put Fade tails on paper.", "link": "/deploy",
     "created_at": server.datetime(2026, 10, 23, 9), "read_at": server.datetime(2026, 10, 23, 10)},
]
BELL_SQL = ("SELECT n.id, n.kind, n.body, n.link, n.created_at, n.read_at",
            "SELECT COUNT(*) AS c FROM app_notifications")

# Every statement a shell sends, counted cold (a page's first load after a restart: no memo, no minute cache, the
# shared series reads warm): the session, /api/me's, its page's carried reads, then the bell's two, added
# explicitly (carried on every signed-in shell since 2026-10-30: the newest notices and the unread count). Each
# page's own reads are budgeted on their own in test_hot_endpoint_query_budget; these are the shells before the
# bell, on this harness: dashboard 33 (with its autopilot status), Deploy 16, Research 12.
BELL_STATEMENTS = 2
SHELL_BUDGET = {"/": 33 + BELL_STATEMENTS, "/deploy": 16 + BELL_STATEMENTS, "/research": 12 + BELL_STATEMENTS}


class Outside(list):
    """Each attempt to reach past this machine: refused, and kept so the test can say what tried."""


@pytest.fixture
def outside(monkeypatch):
    """No network but 127.0.0.1 (the test server): any socket, HTTP client or AWS client aimed elsewhere is
    refused and recorded, whether or not the code under it swallows the error."""
    tried = Outside()
    connect, getaddrinfo = socket.socket.connect, socket.getaddrinfo
    local = ("127.0.0.1", "localhost", "::1")

    def guard_connect(self, addr):
        if isinstance(addr, tuple) and addr[0] not in local:
            tried.append(("connect", addr))
            raise OSError("outside network refused in this test")
        return connect(self, addr)

    def guard_getaddrinfo(host, *a, **kw):
        if host not in local and host is not None:
            tried.append(("resolve", host))
            raise socket.gaierror("outside network refused in this test")
        return getaddrinfo(host, *a, **kw)

    def refuse(what):
        def fn(*a, **kw):
            tried.append((what, a[1:3] if len(a) > 1 else a))
            raise OSError("outside network refused in this test")
        return fn

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guard_getaddrinfo)
    monkeypatch.setattr(requests.Session, "request", refuse("requests"))
    monkeypatch.setattr(urllib.request, "urlopen", refuse("urlopen"))
    try:
        import boto3
        monkeypatch.setattr(boto3, "client", refuse("boto3.client"))
        monkeypatch.setattr(boto3, "resource", refuse("boto3.resource"))
        monkeypatch.setattr(boto3.session.Session, "client", refuse("boto3.Session.client"))
    except ImportError:  # pragma: no cover - boto3 is in requirements
        pass
    return tried


@pytest.fixture
def shell_web(production, outside, monkeypatch):
    """The app over the counting cursor: every request's statements land in the returned log."""
    from app.adapters.kalshi import kalshi_account
    from app.trading import demo_twins
    log = []
    rows = dict(_board_rows())
    rows.update({
        "FROM app_sessions s JOIN app_users u": [USER],
        PULSE: [_pulse_row({"n": 9, "closed": 7, "top": 30}, [{"id": 5, "strategy_id": 9}, {"id": 6, "strategy_id": 9}])],
        CREDITS: [{"part": "balance", "run_kind": None, "brief": None, "example": None, "s": 10.0}],
        "FROM app_stripe_customers": [{"user_id": 7, "stripe_customer_id": "cus_1", "default_pm_id": "pm_1",
                                       "auto_reload": 0, "reload_amount": 20, "reload_threshold": 5}],
        "SELECT n.id, n.kind, n.body, n.link, n.created_at, n.read_at": NOTICES,
        "SELECT COUNT(*) AS c FROM app_notifications": [{"c": 2}],
    })
    conn = type("Conn", (), {"cursor": lambda self: CountingCursor(log, rows), "close": lambda self: None})()
    monkeypatch.setattr(server, "get_db_conn", lambda: conn)
    # No cash memo kept: every cash figure is pending, never read from Kalshi on these requests.
    monkeypatch.setattr(kalshi_account, "_BALANCE_CACHE", {})
    monkeypatch.setattr(demo_twins, "_BALANCE_CACHE", {})
    for cache in (server._TRACK_RECORD, server._BACKTEST_CHECKS, server._ROADS, server._FAILING, server._RUN_TOTALS):
        cache.clear()
    chat_routes._LAST_ACTION.clear()
    book_memo.clear()
    webrows = list(webperf._ROWS)
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield http.server_port, log, rows
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)
    webperf._ROWS.clear()
    webperf._ROWS.extend(webrows)
    book_memo.clear()


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers={"Cookie": "rsid=abc; tau_ui=tau"})
    r = conn.getresponse()
    body = r.read().decode("utf-8")
    conn.close()
    assert r.status == 200, (path, r.status, body[:300])
    return body


def _carried(html):
    found = re.findall(r'<script type="application/json" id="tau-first">(.*?)</script>', html, re.S)
    assert len(found) == 1
    return {r["url"]: r["body"] for r in json.loads(found[0])}


@pytest.mark.parametrize("path,status_carried", [("/", True), ("/deploy", False), ("/research", False)])
def test_the_shell_carries_the_bell_and_the_dashboard_the_status_as_their_endpoints_answer(shell_web, outside, path, status_carried):
    port, log, rows = shell_web
    carried = _carried(_get(port, path))
    bell = json.loads(_get(port, "/api/notifications"))
    assert carried["/api/notifications"] == bell
    assert bell["unread"] == 2 and bell["items"][0]["more"] == 1  # the two pauses of one strategy read as one line
    status = json.loads(_get(port, "/api/autopilot/status"))
    if status_carried:
        assert carried["/api/autopilot/status"] == status and status["mode"] == "live-armed"
    else:
        # Off the dashboard the status costs its 7+ statements on every load for a pill: the page reads it.
        assert "/api/autopilot/status" not in carried
    # The Hot Markets rail is never carried: its feed waits on S3 when cold.
    assert "/api/explore/hot" not in carried
    assert outside == []


@pytest.mark.parametrize("path", ["/", "/deploy", "/research"])
def test_each_shell_stays_in_its_statement_budget_with_the_bell_added_explicitly(shell_web, outside, path):
    port, log, rows = shell_web
    _get(port, path)
    sent = [s for s, _ in log]
    bell = [s for s in sent if s.startswith(BELL_SQL)]
    assert len(bell) == BELL_STATEMENTS, bell
    assert len(sent) <= SHELL_BUDGET[path], "the %s shell sent %d statements (budget %d):\n  %s" % (
        path, len(sent), SHELL_BUDGET[path], "\n  ".join(sent))
    # The bell's two are the only statements it added: without it the shell sends exactly the rest.
    del log[:]
    book_memo.clear()
    for cache in (server._TRACK_RECORD, server._BACKTEST_CHECKS, server._ROADS, server._FAILING, server._RUN_TOTALS):
        cache.clear()
    chat_routes._LAST_ACTION.clear()
    orig = shell_reads.shell_requests
    try:
        shell_reads.shell_requests = lambda p: []
        _get(port, path)
    finally:
        shell_reads.shell_requests = orig
    assert len(log) == len(sent) - BELL_STATEMENTS
    assert outside == []


def test_nothing_the_shell_carries_reaches_outside_whatever_the_autopilot_state(shell_web, outside, monkeypatch):
    # Off, on, blocked on billing (a zero balance): the status takes another path through its reads each time.
    port, log, rows = shell_web
    for autopilot, balance in ((1, 10.0), (1, 0.0), (0, 10.0)):
        USER_ROW = dict(USER, autopilot=autopilot)
        rows[CREDITS] = [{"part": "balance", "run_kind": None, "brief": None, "example": None, "s": balance}]
        rows["SELECT COALESCE(SUM(amount_usd),0) AS b FROM app_credit_ledger"] = [{"b": balance}]
        book_memo.clear()
        monkeypatch.setattr(server.repo, "session_user", lambda cur, token, row=USER_ROW: (cur.execute("SELECT session"), row)[1])
        for path in ("/", "/deploy", "/research", "/strategies", "/funds", "/explore", "/research/41"):
            _get(port, path)
        _get(port, "/api/autopilot/status")
        _get(port, "/api/notifications")
    assert outside == []
    # The guard itself: a read that did reach for the network would have been refused and kept here.
    with pytest.raises(OSError):
        requests.get("https://api.elections.kalshi.com/trade-api/v2/portfolio/balance", timeout=1)
    with pytest.raises(OSError):
        socket.create_connection(("192.0.2.1", 443), timeout=1)
    assert [t[0] for t in outside] == ["requests", "resolve"]
