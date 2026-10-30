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
          "research_scoreboard", "funds")


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


class _Calls(list):
    """(params, query, uid) per call; `kw` the keyword arguments of each call (none: the context alone)."""

    def __init__(self):
        super().__init__()
        self.kw = []


def _record(monkeypatch, name, answer):
    """Stand in for one route as the shell calls it (patched where shell_reads reads it); log its calls."""
    calls = _Calls()

    def fake(ctx, **kw):
        calls.append((ctx.params, dict(ctx.query), ctx.uid))
        calls.kw.append(kw)
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
    if route == "dashboard":
        # Neither of the dashboard's two reads may wait on Kalshi (the live cash, a demo-funds check).
        assert calls.kw == [{}] and status.kw == [{}]
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
    ("/funds?tab=keys", "rsid=abc"),
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


def _funds_db(monkeypatch, live_key=True, demo_key=True):
    """Funds' own-database reads answered without a database, for user 7; its Kalshi client raises, so a
    read that would ask Kalshi fails the test."""
    from app.adapters.kalshi import kalshi_account
    from app.services import book_memo
    from app.trading import demo_twins
    from app.web.routes import funds as funds_routes

    def kalshi(*a, **k):
        raise AssertionError("asked Kalshi")
    r = funds_routes.repo
    monkeypatch.setattr(r, "get_kalshi_key", lambda cur, uid: {"key_id": "LIVEKEY-ABCD-1234"} if live_key else None)
    monkeypatch.setattr(r, "get_kalshi_dev_key", lambda cur, uid: {"key_id": "DEVKEY-WXYZ-5678"} if demo_key else None)
    # The dashboard asks only whether each key is saved (never the key itself).
    monkeypatch.setattr(r, "has_kalshi_key", lambda cur, uid: live_key)
    monkeypatch.setattr(r, "has_kalshi_dev_key", lambda cur, uid: demo_key)
    monkeypatch.setattr(r, "demo_equity", lambda cur, uid, realized=None: {"capital": 1000, "equity": 1003.5, "realized": 3.5,
                                                                            "before_reload": 0})
    monkeypatch.setattr(r, "paper_balance", lambda cur, uid: Decimal("2001.745"))
    monkeypatch.setattr(r, "ledger_rows", lambda cur, uid: [{"memo": "Paper deposit", "amount": Decimal("1000"),
                                                             "created_at": datetime(2026, 10, 26, 8, 0)}])
    monkeypatch.setattr(r, "user_positions", lambda cur, uid, status: [{"mode": "live", "qty": 10, "entry_price": 0.4}])
    monkeypatch.setattr(book_memo, "closed_book_totals", lambda memo, day, visit=None: (
        {"paper": (5.61, 0), "demo": (3.5, 0), "live": (-1.245, 0)}, {"paper": 2, "demo": 1, "live": 1}, {}))
    for mod, name in ((kalshi_account, "balance"), (kalshi_account, "balance_cached"), (kalshi_account, "credentials_from_row"),
                      (kalshi_account, "verify"), (demo_twins, "_read_balance"), (demo_twins, "balance_cached")):
        monkeypatch.setattr(mod, name, kalshi)
    monkeypatch.setattr(kalshi_account, "_BALANCE_CACHE", {})
    monkeypatch.setattr(demo_twins, "_BALANCE_CACHE", {})
    return kalshi_account, demo_twins


@pytest.mark.parametrize("path", ["/funds", "/settings/account"])
def test_funds_shell_carries_its_read_for_an_account_with_kalshi_keys_and_never_asks_kalshi(web, monkeypatch, path):
    # Kalshi's live and demo cash wait on Kalshi (up to its timeout, per key): the shell carries everything
    # from our own database and marks the cash pending, for the page to ask /api/funds/cash after it draws.
    _funds_db(monkeypatch)
    r, html = _shell(web, path)
    first = _first(html)
    assert r.status == 200 and [x["url"] for x in first] == ["/api/funds"]
    body = first[0]["body"]
    assert body["kalshi"]["pending"] is True and body["kalshi"]["balance"] is None and "last_balance" not in body["kalshi"]
    assert body["kalshi_dev"]["pending"] is True and body["kalshi_dev"]["balance"] is None
    # It names the cash reads the page asks next, so boot.js starts them beside the bundle.
    assert first[0]["then"] == ["/api/funds/cash?book=live", "/api/funds/cash?book=demo"]
    # Our own books come whole, each its own: never added together, P&L apart from cash.
    assert body["paper"]["cash"] == 2001.75 and body["paper"]["realized_pnl"] == 5.61 and body["paper"]["ledger"]
    assert body["demo"]["equity"] == 1003.5 and body["kalshi"]["realized_pnl"] == -1.25
    assert (body["kalshi"]["open_positions"], body["kalshi"]["open_at_cost"]) == (1, 4.0)
    assert body["kalshi"]["key_id"] == "LIVE…1234" and "LIVEKEY-ABCD-1234" not in html and "DEVKEY-WXYZ-5678" not in html
    block = html.split('id="tau-first">', 1)[1].split("</script>", 1)[0]
    assert "<" not in block and ">" not in block


def test_funds_reads_each_keys_cash_from_its_memo_alone(monkeypatch):
    from datetime import timezone

    from app.web.routes.funds import funds
    kalshi_account, demo_twins = _funds_db(monkeypatch)
    ctx = SimpleNamespace(cur=None, uid=7)
    now = kalshi_account.time.monotonic()
    utc = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731
    # Nothing memoized: pending, with no figure at all (the page reads "Checking…", never $0).
    out = funds(ctx)
    assert {k: out["kalshi"][k] for k in ("connected", "balance", "pending")} == {"connected": True, "balance": None, "pending": True}
    assert out["kalshi_dev"] == {"connected": True, "key_id": "DEVK…5678", "balance": None, "pending": True,
                                 "copies_from": out["kalshi_dev"]["copies_from"]}
    # Read 70s ago (past the minute): still pending, carrying that figure and when it was read.
    kalshi_account._BALANCE_CACHE[7] = (now - 70, 1234.5649)
    demo_twins._BALANCE_CACHE[7] = (now - 70, None)  # the demo read failed then: nothing to show but pending
    out = funds(ctx)
    k = out["kalshi"]
    assert k["pending"] is True and k["balance"] is None and k["last_balance"] == 1234.56
    assert 68 <= (utc() - k["last_balance_at"]).total_seconds() <= 75
    assert out["kalshi_dev"]["pending"] is True and "last_balance" not in out["kalshi_dev"]
    # Read 10s ago: kept, so it is the figure, dated, and nothing is pending.
    kalshi_account._BALANCE_CACHE[7] = (now - 10, 1234.5)
    demo_twins._BALANCE_CACHE[7] = (now - 10, 250.0)
    out = funds(ctx)
    assert out["kalshi"]["balance"] == 1234.5 and "pending" not in out["kalshi"] and out["kalshi"]["balance_at"]
    assert out["kalshi_dev"]["balance"] == 250.0 and "pending" not in out["kalshi_dev"]
    # A failed read still kept answers as /api/funds does: no figure, not pending ("Kalshi didn't answer").
    kalshi_account._BALANCE_CACHE[7] = (now - 10, None)
    out = funds(ctx)
    assert out["kalshi"]["balance"] is None and "pending" not in out["kalshi"] and "balance_at" not in out["kalshi"]


def test_funds_for_an_account_with_no_key_is_the_whole_read(monkeypatch):
    _funds_db(monkeypatch, live_key=False, demo_key=False)
    from app.web.routes import funds as funds_routes
    ctx = SimpleNamespace(cur=None, uid=7)
    out = funds_routes.funds(ctx)
    assert out["kalshi"]["connected"] is False and out["kalshi_dev"] == {"connected": False}


def test_then_reads_names_only_funds_pending_cash():
    pending, kept = {"connected": True, "pending": True, "balance": None}, {"connected": True, "balance": 12.5}
    assert shell_reads.then_reads("/api/funds", {"kalshi": pending, "kalshi_dev": pending}) == [
        "/api/funds/cash?book=live", "/api/funds/cash?book=demo"]
    assert shell_reads.then_reads("/api/funds", {"kalshi": kept, "kalshi_dev": pending}) == ["/api/funds/cash?book=demo"]
    assert shell_reads.then_reads("/api/funds", {"kalshi": kept, "kalshi_dev": {"connected": False}}) == []
    assert shell_reads.then_reads("/api/dashboard", {"kalshi": pending}) == []
    assert shell_reads.then_reads("/api/funds", []) == []


def test_a_funds_shell_with_each_cash_kept_names_no_reads_after(web, monkeypatch):
    kalshi_account, demo_twins = _funds_db(monkeypatch)
    now = kalshi_account.time.monotonic()
    kalshi_account._BALANCE_CACHE[7] = (now - 10, 1234.5)
    demo_twins._BALANCE_CACHE[7] = (now - 10, 250.0)
    r, html = _shell(web, "/funds")
    first = _first(html)
    assert r.status == 200 and "then" not in first[0] and first[0]["body"]["kalshi"]["balance"] == 1234.5


def test_funds_cash_reads_one_books_cash_in_cents(monkeypatch):
    # The page's follow-up for a pending figure: one book at a time, so neither waits on the other's Kalshi
    # read; only that book's cash, never added to another's.
    from app.web.routes import funds as funds_routes
    kalshi_account, demo_twins = _funds_db(monkeypatch)
    asked = []
    monkeypatch.setattr(kalshi_account, "credentials_from_row", lambda uid, row: ("id", None))
    ttls = []
    monkeypatch.setattr(kalshi_account, "balance_cached", lambda uid, creds, ttl: ttls.append(ttl) or asked.append("live") or 1234.5649)
    monkeypatch.setattr(kalshi_account, "balance_read_at", lambda uid: datetime(2026, 10, 27, 9, 0))
    monkeypatch.setattr(demo_twins, "balance_cached", lambda cur, uid, ttl: ttls.append(ttl) or asked.append("demo") or 500.0)
    ask = lambda book: funds_routes.funds_cash(SimpleNamespace(cur=None, uid=7, query={"book": book} if book else {}))  # noqa: E731
    assert ask("live") == {"book": "live", "connected": True, "balance": 1234.56, "balance_at": datetime(2026, 10, 27, 9, 0)}
    assert asked == ["live"]
    demo = ask("demo")
    assert demo["book"] == "demo" and demo["balance"] == 500.0 and asked == ["live", "demo"]
    # It reads Kalshi again once the memo is no longer kept, the moment a poll's read marks the cash pending.
    assert ttls == [60.0 - kalshi_account.KEPT_MARGIN] * 2
    monkeypatch.setattr(kalshi_account, "balance_cached", lambda uid, creds, ttl: None)  # Kalshi didn't answer
    assert ask("live") == {"book": "live", "connected": True, "balance": None}
    with pytest.raises(ApiError) as e:
        ask(None)
    assert e.value.status == 400
    _funds_db(monkeypatch, live_key=False, demo_key=False)
    assert ask("live")["connected"] is False and ask("demo") == {"book": "demo", "connected": False, "balance": None}


def _dashboard_db(monkeypatch, deps=()):
    """The dashboard's own-database reads answered without a database, for user 7 with a live and a demo key;
    its Kalshi client raises (_funds_db), so a read that would ask Kalshi fails the test."""
    from app.services import book_memo
    from app.web.routes import dashboard as dashboard_routes

    kalshi_account, demo_twins = _funds_db(monkeypatch)
    r = dashboard_routes.repo
    for name, fn in {
        "user_positions": lambda *a, **k: [], "list_deployments_for_display": lambda *a, **k: [dict(d) for d in deps],
        "deployment_curves": lambda *a, **k: {}, "positions_version": lambda cur, uid: (0, 0, 0),
        "paper_ledger_summary": lambda cur, uid: {"balance": 1000.0, "deposited": 1000.0, "reset_at": None},
        "paper_ledger_version": lambda cur, uid: (1, 1),
        "daily_pnl": lambda *a, **k: [], "activity_since": lambda cur, uid, since: {"autopilot": {}, "runs": {}},
        "passed_since": lambda cur, uid, since, **k: {"n": 0, "items": []},
        "demo_equity": lambda cur, uid, realized=None: {"capital": 1000.0, "equity": 1003.5, "realized": 3.5, "roi": .0035,
                                                        "before_reload": 0},
        "open_reconcile_rows": lambda cur, uid: [], "active_run_counts": lambda cur, uid, **kw: {},
        "deployment_strategies": lambda cur, uid: {},
    }.items():
        monkeypatch.setattr(r, name, fn)
    monkeypatch.setattr(book_memo, "closed_book_totals", lambda memo, day, visit=None, split=False, fills=False: (
        {m: (0.0, 0.0) for m in ("paper", "demo", "live")}, {"live": 2},
        {m: (0.0, 0) for m in ("paper", "demo", "live")}) + (({},) if split else ()) + (({},) if fills else ()))
    monkeypatch.setattr(dashboard_routes, "_freshness", lambda cur: {})
    monkeypatch.setattr(dashboard_routes, "_deployment_out", lambda d, *a: {"id": d["id"], "mode": d["mode"], "status": d["status"]})
    monkeypatch.setattr(book_memo, "_LEDGER", {})
    monkeypatch.setattr(book_memo, "_KEPT", {})
    return kalshi_account, demo_twins


# A running demo deployment with a stake: the dashboard's demo-funds check reads the demo cash for it.
DEMO_DEP = {"id": 31, "strategy_id": 5, "mode": "demo", "status": "running", "status_reason": None,
            "spec": {"sizing": {"stake": 5.0, "max_positions": 1}}}


@pytest.mark.parametrize("path", ["/", "/dashboard"])
def test_the_dashboard_shell_carries_its_read_for_an_account_with_kalshi_keys_and_never_asks_kalshi(web, monkeypatch, path):
    # The live cash (and the demo cash a demo-funds check reads) wait on Kalshi, up to its timeout per key: the
    # shell carries everything from our own database, the cash pending, and names the follow-ups ("then").
    _dashboard_db(monkeypatch, deps=[DEMO_DEP])
    _record(monkeypatch, "autopilot_status", {"mode": "paper"})
    r, html = _shell(web, path)
    first = _first(html)
    assert r.status == 200 and [x["url"] for x in first] == ["/api/dashboard", "/api/autopilot/status"]
    body = first[0]["body"]
    live = body["live"]
    assert live["connected"] is True and live["pending"] is True and live["balance"] is None and "last_balance" not in live
    assert (live["closed_trades"], live["realized_pnl"]) == (2, 0.0)  # Tau's own live book, from our database
    assert body["demo"]["health"] is None and body["demo"]["health_pending"] is True
    assert body["paper"]["cash"] == 1000.0 and body["demo"]["equity"] == 1003.5  # each book its own, never added
    assert first[0]["then"] == ["/api/funds/cash?book=live", "/api/funds/cash?book=demo"]
    assert "LIVEKEY-ABCD-1234" not in html and "DEVKEY-WXYZ-5678" not in html


def test_the_dashboard_reads_the_cash_from_its_memo_alone(monkeypatch):
    from datetime import timezone

    from app.web.routes.dashboard import dashboard
    from app.web.views import demo_health_memo
    kalshi_account, demo_twins = _dashboard_db(monkeypatch, deps=[DEMO_DEP])
    ctx = SimpleNamespace(cur=None, uid=7, query={})
    now = kalshi_account.time.monotonic()
    utc = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731
    # Read 70s ago (past the minute): still pending, carrying that figure and when it was read, in cents.
    kalshi_account._BALANCE_CACHE[7] = (now - 70, 1234.5649)
    live = dashboard(ctx)["live"]
    assert live["pending"] is True and live["balance"] is None and live["last_balance"] == 1234.56
    assert 68 <= (utc() - live["last_balance_at"]).total_seconds() <= 75
    # Read 10s ago: kept, so it is the figure, dated, and nothing is pending; so is the demo check's cash.
    kalshi_account._BALANCE_CACHE[7] = (now - 10, 1234.5)
    demo_twins._BALANCE_CACHE[7] = (now - 10, 0.0)
    out = dashboard(ctx)
    assert out["live"]["balance"] == 1234.5 and "pending" not in out["live"] and out["live"]["balance_at"]
    assert out["demo"]["health"]["code"] == "demo_funds" and "health_pending" not in out["demo"]
    assert shell_reads.then_reads("/api/dashboard", out) == []
    # The demo-funds check alone: pending without the memo, never a Kalshi read; nothing to check, nothing pending.
    demo_twins._BALANCE_CACHE.clear()
    assert demo_health_memo(None, 7, [DEMO_DEP]) == (None, True)
    assert demo_health_memo(None, 7, []) == (None, False)


def test_a_demo_check_reads_the_memo_alone_and_keeps_a_line_from_a_figure_under_two_minutes_old(monkeypatch):
    # The pages' demo check (dashboard, autopilot, Deploy board, strategy page) never asks Kalshi (its client raises
    # here). The memo kept: the line, nothing pending. Just past it (the minute boundary): pending, so the page asks
    # the follow-up, with the line from that figure meanwhile, so it doesn't drop out for a poll. Older, or none:
    # pending with no line (never "Demo isn't trading" from an unknown figure).
    from app.web.views import RECENT_ENOUGH, demo_health_memo
    kalshi_account, demo_twins = _dashboard_db(monkeypatch, deps=[DEMO_DEP])
    now = kalshi_account.time.monotonic()
    code = lambda h: h and h["code"]  # noqa: E731
    for age, figure, want in ((10, 0.0, ("demo_funds", False)), (70, 0.0, ("demo_funds", True)),
                              (RECENT_ENOUGH - 5, 0.0, ("demo_funds", True)), (RECENT_ENOUGH + 5, 0.0, (None, True)),
                              (70, 250.0, (None, True)), (70, None, (None, True)), (10, None, (None, False))):
        demo_twins._BALANCE_CACHE[7] = (now - age, figure)
        health, pending = demo_health_memo(None, 7, [DEMO_DEP])
        assert (code(health), pending) == want, (age, figure)
    demo_twins._BALANCE_CACHE.clear()
    assert demo_health_memo(None, 7, [DEMO_DEP]) == (None, True)
    assert demo_health_memo(None, 7, []) == (None, False)  # nothing on demo: no cash needed, nothing pending
    # The strategy page's next rung asks with a stake even with nothing on demo.
    assert demo_health_memo(None, 7, [], stake=5.0) == (None, True)


def test_then_reads_names_the_deploy_boards_pending_demo_cash():
    assert shell_reads.then_reads("/api/deployments", {"demo_health": None, "demo_health_pending": True}) == ["/api/funds/cash?book=demo"]
    assert shell_reads.then_reads("/api/deployments", {"demo_health": None}) == []


def test_then_reads_names_the_dashboards_and_the_autopilots_pending_cash_once():
    pending = {"connected": True, "pending": True, "balance": None}
    dash = {"live": pending, "demo": {"health": None, "health_pending": True}}
    assert shell_reads.then_reads("/api/dashboard?since=1761000000", dash) == ["/api/funds/cash?book=live", "/api/funds/cash?book=demo"]
    assert shell_reads.then_reads("/api/dashboard", {"live": {"connected": True, "balance": 1.0}, "demo": {"health": None}}) == []
    assert shell_reads.then_reads("/api/autopilot/status", {"idle_pending": True}) == ["/api/funds/cash?book=demo"]
    assert shell_reads.then_reads("/api/autopilot/status", {"idle": None}) == []


def test_the_shell_names_a_follow_up_once_across_its_reads(monkeypatch):
    # Both of the dashboard's reads can wait on the demo cash: boot.js starts it once.
    pending = {"connected": True, "pending": True, "balance": None}
    monkeypatch.setattr(shell_reads, "dashboard", lambda ctx, **kw: {"live": pending, "demo": {"health_pending": True}})
    monkeypatch.setattr(shell_reads, "autopilot_status", lambda ctx, **kw: {"idle_pending": True})
    reads, _ = shell_reads.first_reads("/", "", {}, lambda params, q: SimpleNamespace(set_cookies=[]))
    assert [x.get("then") for x in reads] == [["/api/funds/cash?book=live", "/api/funds/cash?book=demo"], None]


def test_the_since_strip_judges_every_pass_past_50_and_says_at_least_past_its_limit(monkeypatch):
    # The strip judged only the newest 50 passes since the visit: with 120, "n" took off only the uncleared among
    # those 50. Every pass is judged now, up to PASSED_JUDGE, in one read; past it the counts say "at least".
    from app.web.routes import dashboard as dashboard_routes
    rows = [{"id": i, "title": "S%d" % i, "spec": {}, "experiment_id": 1000 + i} for i in range(120, 0, -1)]
    asked = []
    monkeypatch.setattr(dashboard_routes.repo, "passed_since",
                        lambda cur, uid, since, limit=3: {"n": len(rows), "items": rows[:limit]})
    # Every tenth pass, the oldest ones among them, missed its one-time holdout.
    monkeypatch.setattr(dashboard_routes, "_later_verdicts", lambda cur, uid, items: asked.append(len(items)) or {
        i["id"]: ("missed_final", {}) for i in items if i["id"] % 10 == 0})
    out = dashboard_routes._passed_since(None, 7, datetime(2026, 10, 1))
    assert asked == [120] and out["n"] == 108 and out["not_cleared_n"] == 12 and "more" not in out
    assert [i["id"] for i in out["items"]] == [119, 118, 117] and [i["id"] for i in out["not_cleared"]] == [120, 110, 100]
    rows[:] = [{"id": i, "title": "S%d" % i, "spec": {}, "experiment_id": i} for i in range(700, 0, -1)]
    asked.clear()
    out = dashboard_routes._passed_since(None, 7, datetime(2026, 10, 1))
    assert asked == [dashboard_routes.PASSED_JUDGE] == [500]
    assert out["more"] is True and out["n"] == 450 and out["not_cleared_n"] == 50  # the newest 500's: at least that many


def test_a_memo_counts_as_kept_only_with_time_to_spare(monkeypatch):
    from app.adapters.kalshi import kalshi_account
    now = 1000.0
    monkeypatch.setattr(kalshi_account.time, "monotonic", lambda: now)
    cache = {7: (now - 50.0, 12.5)}
    assert kalshi_account.memo_kept(cache, 7, 60.0)
    assert not kalshi_account.memo_kept(cache, 8, 60.0)
    # Within KEPT_MARGIN of its end the next read could go to Kalshi: not kept.
    cache[7] = (now - (60.0 - kalshi_account.KEPT_MARGIN), 12.5)
    assert not kalshi_account.memo_kept(cache, 7, 60.0)
    cache[7] = (now - 61.0, 12.5)
    assert not kalshi_account.memo_kept(cache, 7, 60.0)


def _route(path):
    """The handler the server runs for GET `path`, called as it calls it (the context alone)."""
    return next(fn for m, p, fn, _ in server.ROUTES if m == "GET" and p.match(path))


def test_the_dashboard_and_funds_never_ask_kalshi_whoever_asks_and_a_cash_read_moves_the_poll(monkeypatch):
    # The 15s dashboard poll and the 30s Funds poll, and an in-app visit to either, ask the same routes as the
    # shell, which waited on Kalshi (up to its timeout) each time a memo ran out. Kalshi's client raises here.
    import inspect

    from app.web.routes import chat as chat_routes
    kalshi_account, demo_twins = _dashboard_db(monkeypatch, deps=[DEMO_DEP])
    ctx = lambda q=None: SimpleNamespace(cur=None, uid=7, query=dict(q or {}))  # noqa: E731
    now = kalshi_account.time.monotonic()
    kalshi_account._BALANCE_CACHE[7] = (now - 70, 1234.5649)  # read a minute ago: past the memo
    demo_twins._BALANCE_CACHE[7] = (now - 70, 0.0)
    dash = _route("/api/dashboard")(ctx())
    assert dash["live"]["pending"] is True and dash["live"]["last_balance"] == 1234.56 and dash["live"]["balance"] is None
    # The demo check is pending too; its line from the figure read 70s ago stands meanwhile (under two minutes).
    assert dash["demo"]["health_pending"] is True and dash["demo"]["health"]["code"] == "demo_funds"
    funds = _route("/api/funds")(ctx())
    assert funds["kalshi"]["pending"] is True and funds["kalshi"]["last_balance"] == 1234.56
    assert funds["kalshi_dev"]["pending"] is True and funds["kalshi_dev"]["last_balance"] == 0.0
    # The autopilot status the panel polls on every page reads the demo cash the same way (its idle line).
    assert _route("/api/autopilot/status") is chat_routes.autopilot_status
    assert list(inspect.signature(chat_routes.autopilot_status).parameters) == ["ctx"]
    # The poll's version: unchanged while the memo is, so the page's poll is told "same"...
    v = dash["v"]
    assert _route("/api/dashboard")(ctx({"v": v})).get("same") is True
    # ...and moved by a cash read: the follow-up's (kept now, same figure, a new read time), then a new figure.
    kalshi_account._BALANCE_CACHE[7] = (kalshi_account.time.monotonic() - 1, 1234.5649)
    kept = _route("/api/dashboard")(ctx({"v": v}))
    assert not kept.get("same") and kept["v"] != v and kept["live"]["balance"] == 1234.56 and "pending" not in kept["live"]
    assert _route("/api/dashboard")(ctx({"v": kept["v"]})).get("same") is True
    kalshi_account._BALANCE_CACHE[7] = (kalshi_account._BALANCE_CACHE[7][0], 1500.0)
    moved = _route("/api/dashboard")(ctx({"v": kept["v"]}))
    assert not moved.get("same") and moved["live"]["balance"] == 1500.0


def _cash_reads(monkeypatch, delay=0.2):
    """/api/funds/cash for user 7 with a live and a demo key, each Kalshi read taking `delay` and counted."""
    import threading
    import time

    from app.adapters.kalshi import kalshi_account
    from app.trading import demo_twins
    from app.web.routes import funds as funds_routes

    class Reads(dict):
        at_once = None  # [in flight now, most at once]
    reads = Reads(live=0, demo=0)
    reads.at_once = [0, 0]
    lock = threading.Lock()

    def slow(book, value):
        with lock:
            reads[book] += 1
            reads.at_once[0] += 1
            reads.at_once[1] = max(reads.at_once)
        time.sleep(delay)
        with lock:
            reads.at_once[0] -= 1
        return value
    monkeypatch.setattr(funds_routes.repo, "get_kalshi_key", lambda cur, uid: {"key_id": "LIVEKEY-ABCD-1234"})
    monkeypatch.setattr(funds_routes.repo, "get_kalshi_dev_key", lambda cur, uid: {"key_id": "DEVKEY-WXYZ-5678"})
    monkeypatch.setattr(funds_routes.repo, "has_kalshi_key", lambda cur, uid: True)
    monkeypatch.setattr(funds_routes.repo, "has_kalshi_dev_key", lambda cur, uid: True)
    monkeypatch.setattr(kalshi_account, "credentials_from_row", lambda uid, row: ("id", None))
    monkeypatch.setattr(kalshi_account, "balance", lambda creds: slow("live", 1234.5))
    monkeypatch.setattr(demo_twins, "_read_balance", lambda cur, uid, timeout=15: slow("demo", 500.0))
    monkeypatch.setattr(kalshi_account, "_BALANCE_CACHE", {})
    monkeypatch.setattr(demo_twins, "_BALANCE_CACHE", {})
    return reads, lambda book: funds_routes.funds_cash(SimpleNamespace(cur=None, uid=7, query={"book": book}))


def _together(n, fn):
    """fn() from n threads released at once; their answers."""
    import threading

    gate, out = threading.Barrier(n), []

    def run():
        gate.wait()
        out.append(fn())
    threads = [threading.Thread(target=run) for _ in range(n)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    return out


def test_concurrent_cash_reads_make_one_kalshi_read_per_book(monkeypatch):
    # Two tabs, or a poll's follow-up beside another's, the moment the memo runs out: each was a Kalshi read.
    from app.adapters.kalshi import kalshi_account
    from app.trading import demo_twins
    reads, ask = _cash_reads(monkeypatch)
    for book, figure in (("live", 1234.5), ("demo", 500.0)):
        got = _together(8, lambda: ask(book))
        assert len(got) == 8 and {g["balance"] for g in got} == {figure}, book
        assert reads[book] == 1, (book, reads)
    assert reads.at_once[1] == 1
    assert kalshi_account._FLIGHTS == {}
    # Kept now: no read at all; once it runs out (as a minute on), one read again for all of them.
    _together(8, lambda: ask("live"))
    assert reads == {"live": 1, "demo": 1}
    kalshi_account._BALANCE_CACHE[7] = (kalshi_account._BALANCE_CACHE[7][0] - 60, 1234.5)
    demo_twins._BALANCE_CACHE[7] = (demo_twins._BALANCE_CACHE[7][0] - 60, 500.0)
    _together(6, lambda: ask("live")) + _together(6, lambda: ask("demo"))
    assert reads == {"live": 2, "demo": 2}
    assert kalshi_account._FLIGHTS == {}
    # A live read never waits on a demo one (one flight per user and book): the two run at once.
    kalshi_account._BALANCE_CACHE.clear()
    demo_twins._BALANCE_CACHE.clear()
    books = iter(("live", "demo"))
    _together(2, lambda: ask(next(books)))
    assert reads == {"live": 3, "demo": 3} and reads.at_once[1] == 2


def test_a_single_flight_hands_its_answer_or_its_error_to_whoever_waited_and_then_clears(monkeypatch):
    import threading

    from app.adapters.kalshi import kalshi_account
    started, release, calls = threading.Event(), threading.Event(), []

    def read():
        calls.append(1)
        started.set()
        release.wait(5)
        raise RuntimeError("kalshi down")
    errors = []

    def lead():
        try:
            kalshi_account.single_flight(("live", 9), read)
        except RuntimeError as e:
            errors.append(str(e))
    leader = threading.Thread(target=lead)
    leader.start()
    started.wait(5)
    follower = threading.Thread(target=lead)
    follower.start()
    release.set()
    leader.join(5)
    follower.join(5)
    assert calls == [1] and errors == ["kalshi down", "kalshi down"]
    assert kalshi_account.single_flight(("live", 9), lambda: 3.5) == 3.5 and kalshi_account._FLIGHTS == {}


def test_a_live_read_in_flight_never_overwrites_the_cash_of_a_key_saved_meanwhile(monkeypatch):
    from app.adapters.kalshi import kalshi_account
    monkeypatch.setattr(kalshi_account, "_BALANCE_CACHE", {})

    def balance(creds):
        kalshi_account.remember_balance(7, 99.0)  # a new key verified while the old key's read was out
        return 5.0
    monkeypatch.setattr(kalshi_account, "balance", balance)
    assert kalshi_account.balance_cached(7, None) == 5.0
    assert kalshi_account._BALANCE_CACHE[7][1] == 99.0


def test_reads_that_size_or_gate_orders_still_read_kalshi_as_before(monkeypatch):
    # Only the pages' display reads go through the memo and the single flight. Verifying a key still reads Kalshi
    # every time, with a memo kept; the demo-copy sync (which opens demo deployments only on a funded demo
    # account) still reads the demo cash itself, uncached, with its own timeout.
    import inspect

    from app.adapters.kalshi import kalshi_account
    from app.trading import demo_twins
    calls = []
    monkeypatch.setattr(kalshi_account, "balance", lambda creds: calls.append(creds) or 42.0)
    monkeypatch.setattr(kalshi_account, "parse_private_key", lambda pem: "parsed")
    monkeypatch.setattr(kalshi_account, "_BALANCE_CACHE", {7: (kalshi_account.time.monotonic(), 1.0)})
    assert kalshi_account.verify("key-1", "pem") == 42.0 and kalshi_account.verify("key-1", "pem") == 42.0
    assert calls == [("key-1", "parsed")] * 2 and kalshi_account._FLIGHTS == {}
    sync = inspect.signature(demo_twins.sync).parameters["balance"].default
    assert sync is demo_twins._read_balance and inspect.signature(sync).parameters["timeout"].default == 15


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
    _record(monkeypatch, "get_run", ApiError(404, "No such research session."))
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
    assert [r[0] for r in shell_reads.first_requests("/funds", "", {})] == ["/api/funds"]
    assert [r[0] for r in shell_reads.first_requests("/settings/account", "", {})] == ["/api/funds"]


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


def test_no_page_read_has_a_path_that_waits_on_kalshi():
    # The dashboard, Funds, the autopilot status and the demo check took ask_kalshi=True once, a branch that read
    # Kalshi (up to its timeout) and that no page asked any more: gone, so no page read can take it by mistake.
    # Only /api/funds/cash (the page's follow-up) and key verification on save may wait on Kalshi.
    import inspect
    import pathlib

    from app.web import views
    from app.web.routes import chat as chat_routes
    from app.web.routes import dashboard as dashboard_routes
    from app.web.routes import funds as funds_routes
    for fn in (dashboard_routes.dashboard, funds_routes.funds, chat_routes.autopilot_status):
        assert list(inspect.signature(fn).parameters) == ["ctx"], fn.__name__
    assert "ask_kalshi" not in inspect.signature(views.demo_health_memo).parameters
    assert "ask_kalshi" not in inspect.signature(funds_routes.kalshi_cash).parameters
    # None of them (nor the demo check the pages read) reaches a read that may wait on Kalshi.
    waits = ("_live_balance", "_demo_cash", "balance_cached", "single_flight", "kalshi_dev_exec", "verify(")
    for fn in (dashboard_routes.dashboard, funds_routes.funds, funds_routes.kalshi_cash, chat_routes.autopilot_status,
               views.demo_health_memo, views._health_from):
        src = inspect.getsource(fn)
        assert not [w for w in waits if w in src], fn.__name__
    # The shell carries those same handlers, with nothing between: the pages that show Kalshi cash name exactly
    # the reads checked above, and no first read the shell names on any page reaches a Kalshi wait either.
    carried = {}
    for page in ("/", "/dashboard", "/funds", "/settings/account", "/research", "/research/12", "/strategies", "/deploy",
                 "/billing", "/settings/billing"):
        for url, fn, _, _ in shell_reads.first_requests(page, "", {"tau_tz": "-60"}):
            carried[(page, url.split("?", 1)[0])] = fn
    for page in ("/", "/dashboard"):
        assert carried[(page, "/api/dashboard")] is dashboard_routes.dashboard
        assert carried[(page, "/api/autopilot/status")] is chat_routes.autopilot_status
    assert carried[("/funds", "/api/funds")] is carried[("/settings/account", "/api/funds")] is funds_routes.funds
    for (page, url), fn in carried.items():
        src = inspect.getsource(fn)
        assert not [w for w in waits if w in src], (page, url, fn.__name__)
    app = pathlib.Path(views.__file__).resolve().parents[1]
    assert not [str(f) for f in app.rglob("*.py") if "ask_kalshi" in f.read_text(encoding="utf-8")]
