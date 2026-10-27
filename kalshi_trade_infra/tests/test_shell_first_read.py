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
ROUTES = ("dashboard", "autopilot_status", "list_runs", "get_run", "list_strategies", "list_deployments", "billing_state",
          "research_scoreboard")


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
    ("/billing", "rsid=abc"),             # its read names the browser's time zone: no tau_tz yet, the page asks
    ("/billing", "rsid=abc; tau_tz=abc"),
    ("/billing", "rsid=abc; tau_tz=99999"),
    ("/billing?setup_intent=seti_1", "rsid=abc; tau_tz=240"),  # back from the card form: the page reads fresh
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


@pytest.mark.parametrize("path,tz", [("/billing", "240"), ("/billing", "-330"), ("/billing", "0"), ("/settings/billing", "240")])
def test_billing_shell_carries_its_read_under_the_url_the_page_asks_with_its_time_zone(web, monkeypatch, path, tz):
    # The page asks '/api/billing?tz=' + getTimezoneOffset(); boot.js keeps that offset in tau_tz.
    answer = {"balance": 12.5, "cards": [{"id": "pm_1", "brand": "visa", "last4": "4242"}], "ledger": [
        {"memo": "</script><script>alert(1)</script>", "created_at": datetime(2026, 10, 26, 8, 0), "amount": Decimal("-0.25")}]}
    calls = _record(monkeypatch, "billing_state", answer)
    r, html = _shell(web, path, "rsid=abc; tau_tz=" + tz)
    assert r.status == 200 and calls == [((), {"tz": tz}, 7)]
    assert _first(html) == [{"url": "/api/billing?tz=" + tz, "body": _wire(answer)}]
    block = html.split('id="tau-first">', 1)[1].split("</script>", 1)[0]
    assert "<" not in block and ">" not in block
    assert html.index('id="tau-first"') > html.index('src="/static/app.js')
    # The read failing (Stripe away, say) leaves Billing to ask for itself, with the account still carried.
    _record(monkeypatch, "billing_state", RuntimeError("stripe down"))
    r, html = _shell(web, path, "rsid=abc; tau_tz=" + tz)
    assert r.status == 200 and _first(html) == [] and 'id="tau-me"' in html


def test_billing_shell_never_waits_on_stripe(web, monkeypatch):
    # An account with a Stripe customer has its saved cards listed by Stripe: a slow Stripe would hold
    # the whole shell blank up to its timeout, so the page asks for itself behind its skeleton.
    calls = _record(monkeypatch, "billing_state", {"balance": 12.5})
    monkeypatch.setattr(shell_reads, "asks_stripe", lambda ctx: True)
    r, html = _shell(web, "/billing", "rsid=abc; tau_tz=240")
    assert r.status == 200 and calls == [] and _first(html) == [] and 'id="tau-me"' in html
    monkeypatch.setattr(shell_reads, "asks_stripe", lambda ctx: False)
    r, html = _shell(web, "/billing", "rsid=abc; tau_tz=240")
    assert len(calls) == 1 and _first(html) == [{"url": "/api/billing?tz=240", "body": {"balance": 12.5}}]


@pytest.mark.parametrize("cookie,tz", [(None, None), ("", None), ("abc", None), ("240", 240), ("-330", -330), ("0", 0),
                                       ("-0", 0), ("12345", None), ("2.5", None), ("240 ", None)])
def test_billing_tz_reads_the_offset_as_the_page_writes_it(cookie, tz):
    assert shell_reads.billing_tz(cookie) == tz


def test_research_carries_its_loop_board_only_while_the_server_keeps_one(web, monkeypatch):
    # Drawn a round trip after the session list, the loop card pushed the list down the screen.
    runs, board = {"runs": [], "v": "r1"}, {"total": {"runs": 2, "explored": 10}, "at": datetime(2026, 10, 26, 8, 0)}
    _record(monkeypatch, "list_runs", runs)
    calls = _record(monkeypatch, "research_scoreboard", board)
    kept = []
    monkeypatch.setattr(shell_reads, "scoreboard_kept", lambda uid, days: kept.append((uid, days)) or True)
    r, html = _shell(web, "/research")
    assert r.status == 200 and kept == [(7, 14)] and calls == [((), {"days": "14"}, 7)]
    assert _first(html) == [{"url": "/api/runs", "body": _wire(runs)},
                            {"url": "/api/research/scoreboard?days=14", "body": _wire(board)}]
    # Not worked out yet (seconds, cold): never on the shell's thread. The list is carried, the page asks for the board.
    monkeypatch.setattr(shell_reads, "scoreboard_kept", lambda uid, days: False)
    r, html = _shell(web, "/research")
    assert r.status == 200 and len(calls) == 1 and _first(html) == [{"url": "/api/runs", "body": _wire(runs)}]


def test_scoreboard_kept_once_the_route_has_worked_the_board_out(monkeypatch):
    from app.web import caches
    from app.web.routes import research
    monkeypatch.setattr(caches, "_SHARED", {})
    monkeypatch.setattr(research, "_research_scoreboard", lambda cur, uid, days: {"uid": uid, "days": days})
    assert not research.scoreboard_kept(7, 14)
    ctx = SimpleNamespace(uid=7, query={"days": "14"}, cur=None)
    assert research.research_scoreboard(ctx) == {"uid": 7, "days": 14}
    assert research.scoreboard_kept(7, 14) and not research.scoreboard_kept(7, 7) and not research.scoreboard_kept(8, 14)


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
    assert shell_reads.first_requests("/billing", "", {}) == []
    assert [r[0] for r in shell_reads.first_requests("/billing", "", {"tau_tz": "-60"})] == ["/api/billing?tz=-60"]
    assert [r[0] for r in shell_reads.first_requests("/research/12", "", {})] == ["/api/runs/12?after=0"]
    assert [r[0] for r in shell_reads.first_requests("/", "", {})] == ["/api/dashboard", "/api/autopilot/status"]
    assert [r[0] for r in shell_reads.first_requests("/research", "", {})] == ["/api/runs", "/api/research/scoreboard?days=14"]


def test_asks_stripe_only_for_a_stripe_customer_with_payments_on(monkeypatch):
    from app.web.routes import billing as billing_routes
    ctx = SimpleNamespace(cur=None, uid=7)
    monkeypatch.setattr(billing_routes.repo, "get_stripe_customer", lambda cur, uid: {"stripe_customer_id": "cus_1"})
    monkeypatch.setattr(billing_routes.billing, "configured", lambda: True)
    assert billing_routes.asks_stripe(ctx) is True
    monkeypatch.setattr(billing_routes.billing, "configured", lambda: False)
    assert billing_routes.asks_stripe(ctx) is False
    monkeypatch.setattr(billing_routes.billing, "configured", lambda: True)
    monkeypatch.setattr(billing_routes.repo, "get_stripe_customer", lambda cur, uid: None)
    assert billing_routes.asks_stripe(ctx) is False
