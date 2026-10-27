"""A signed-in app page's shell carries the page's first reads (app.web.shell_reads), keyed by the URL
the page asks for, so the page draws its figures without one more round trip after the bundle runs
(~0.6s on a phone on a slow network, every full load). Same handler and arguments as the page's own
request, the same JSON; nothing for a URL the shell can't name exactly, or for a read that fails."""
import http.client
import json
import re
from datetime import datetime
from decimal import Decimal
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from app import server
from app.web import shell_reads, webperf
from app.web.http import ApiError, _json_default

USER = {"id": 7, "email": "trader@example.invalid", "name": "Sample", "picture_url": None, "autopilot": 0, "ui_theme": "tau"}
ACCOUNT = {"user": {"id": 7, "ui_theme": "tau"}}
ROUTES = ("dashboard", "autopilot_status", "list_runs", "get_run", "list_strategies", "list_deployments")


@pytest.fixture
def web(monkeypatch):
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: dict(USER))
    monkeypatch.setattr(server, "me", lambda ctx: ACCOUNT)
    rows = list(webperf._ROWS)
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield http.server_port
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)
    webperf._ROWS.clear()
    webperf._ROWS.extend(rows)


def _shell(port, path, cookie="rsid=abc"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", path, headers={"Cookie": cookie} if cookie else {})
    r = conn.getresponse()
    html = r.read().decode("utf-8")
    conn.close()
    return r, html


def _first(html):
    found = re.findall(r'<script type="application/json" id="tau-first">(.*?)</script>', html, re.S)
    assert len(found) <= 1
    return json.loads(found[0]) if found else []


def _wire(value):
    """What the API route sends for this answer (_send_json's encoding), as the page reads it."""
    return json.loads(json.dumps(value, default=_json_default))


def _record(monkeypatch, name, answer):
    """Stand in for one route as the shell calls it (patched where shell_reads reads it); log its calls."""
    calls = []

    def fake(ctx):
        calls.append((ctx.params, dict(ctx.query), ctx.uid))
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(shell_reads, name, fake)
    return calls


@pytest.mark.parametrize("path,route,url,params,query", [
    ("/deploy", "list_deployments", "/api/deployments", (), {}),
    ("/research", "list_runs", "/api/runs", (), {}),
    ("/research/943", "get_run", "/api/runs/943?after=0", ("943",), {"after": "0"}),
    ("/strategies", "list_strategies", "/api/strategies?page=0", (), {"page": "0"}),
    ("/", "dashboard", "/api/dashboard", (), {}),
    ("/dashboard", "dashboard", "/api/dashboard", (), {}),
])
def test_an_app_page_shell_carries_its_first_read_under_the_url_the_page_asks(web, monkeypatch, path, route, url, params, query):
    answer = {"v": "abc", "rows": [{"title": "</script><script>alert(1)</script>", "at": datetime(2026, 10, 26, 8, 0),
                                    "pnl": Decimal("1.25")}]}
    status_answer = {"mode": "paper", "at": datetime(2026, 10, 26, 8, 1)}
    calls = _record(monkeypatch, route, answer)
    status = _record(monkeypatch, "autopilot_status", status_answer)
    r, html = _shell(web, path)
    assert r.status == 200 and calls == [(params, query, 7)]
    reads = [{"url": url, "body": _wire(answer)}]
    if route == "dashboard":
        # Its autopilot card sits above the figures: drawn a round trip after them, it pushed them down.
        reads.append({"url": "/api/autopilot/status", "body": _wire(status_answer)})
    assert _first(html) == reads and len(status) == (1 if route == "dashboard" else 0)
    block = html.split('id="tau-first">', 1)[1].split("</script>", 1)[0]
    assert "<" not in block and ">" not in block
    # After the scripts: the browser finds and starts the bundles before the data's bytes arrive.
    assert html.index('id="tau-first"') > html.index('src="/static/boot.js')
    assert html.index('id="tau-first"') > html.index('src="/static/app.js')
    assert r.getheader("Cache-Control") == "private, no-cache" and "{{" not in html


@pytest.mark.parametrize("path,cookie", [
    ("/billing", "rsid=abc"),             # its read names the browser's time zone: the page asks
    ("/funds", "rsid=abc"),
    ("/strategies?status=passed", "rsid=abc"),  # a filtered list: the page's URL says more
    ("/research?new=1", "rsid=abc"),
    ("/signin", "rsid=abc"),
    ("/", None),                          # signed out
])
def test_shells_with_no_read_they_can_name_carry_none(web, monkeypatch, path, cookie):
    for name in ROUTES:
        _record(monkeypatch, name, AssertionError("not asked"))
    r, html = _shell(web, path, cookie)
    assert r.status == 200 and 'id="tau-first"' not in html


def test_a_failed_first_read_leaves_the_page_to_ask_and_the_account_carried(web, monkeypatch):
    _record(monkeypatch, "get_run", ApiError(404, "No such research run."))
    r, html = _shell(web, "/research/5")
    assert r.status == 200 and _first(html) == [] and 'id="tau-me"' in html
    _record(monkeypatch, "list_deployments", RuntimeError("db down"))
    r, html = _shell(web, "/deploy")
    assert r.status == 200 and _first(html) == [] and 'id="tau-me"' in html
    # One of the dashboard's two failing leaves the other carried.
    _record(monkeypatch, "dashboard", RuntimeError("db down"))
    _record(monkeypatch, "autopilot_status", {"mode": "off"})
    r, html = _shell(web, "/")
    assert r.status == 200 and [x["url"] for x in _first(html)] == ["/api/autopilot/status"]


def test_the_dashboard_url_carries_the_since_the_page_works_out_from_its_visit_cookie(web, monkeypatch):
    calls = _record(monkeypatch, "dashboard", {"v": "x"})
    _record(monkeypatch, "autopilot_status", {"mode": "off"})
    now = int(server.time.time())
    # Back within half an hour: the visit goes on from its own start.
    _, html = _shell(web, "/", "rsid=abc; tau_visit=%d.%d" % (now - 4000, now - 60))
    assert _first(html)[0]["url"] == "/api/dashboard?since=%d" % (now - 4000) and calls[-1][1] == {"since": str(now - 4000)}
    # After a longer gap the last visit ended when it was last seen.
    _, html = _shell(web, "/", "rsid=abc; tau_visit=%d.%d" % (now - 90000, now - 7200))
    assert _first(html)[0]["url"] == "/api/dashboard?since=%d" % (now - 7200)


@pytest.mark.parametrize("cookie,now,since", [
    (None, 1000000, None), ("", 1000000, None), ("junk", 1000000, None),
    ("900000.999000", 1000000, 900000),    # seen 1000s ago: the same visit, from its start
    ("0.999000", 1000000, None),            # no start kept (the page wrote 0): no since
    ("900000.990000", 1000000, 990000),     # seen 10000s ago: the last visit ended then
    ("900000.998200", 1000000, 900000),     # exactly the gap is still the same visit (the page: > gap)
    ("900000.998199", 1000000, 998199),
])
def test_dashboard_since_matches_the_pages_visit_start(cookie, now, since):
    assert shell_reads.dashboard_since(cookie, now) == since


def test_only_the_named_pages_have_first_requests():
    assert shell_reads.first_requests("/explore", "", {}) == []
    assert shell_reads.first_requests("/research/12/x", "", {}) == []
    assert shell_reads.first_requests("/deploy", "x=1", {}) == []
    assert [r[0] for r in shell_reads.first_requests("/research/12", "", {})] == ["/api/runs/12?after=0"]
    assert [r[0] for r in shell_reads.first_requests("/", "", {})] == ["/api/dashboard", "/api/autopilot/status"]
