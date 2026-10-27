"""What a user sees when their demo copy can't trade: an empty Kalshi demo account, or no demo key.

Against a real MySQL, with the simulated venue and never a Kalshi call (the demo balance read is
stubbed, and any request to Kalshi's demo host fails the test). First, what happens today when a
demo copy tries to trade on an empty account (the engine and order path are unchanged): Kalshi's
demo refuses the order, the error escapes the decision, the deployment stays "running" with nothing
booked and its order intent is left 'sent', and nothing reaches the user. Then what each place that
shows demo now says: the dashboard's demo bucket, the Deploy board, the autopilot's idle line and the
strategy page's ladder each give one plain line and the action to take. Opt in as for
test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

STRIKE = 98.0
# What kalshi_dev_exec.demo_place_limit_order raises when the demo exchange refuses an order for want of funds.
REFUSED = ('demo POST /portfolio/orders failed 400: {"error":{"code":"insufficient_balance",'
           '"message":"insufficient balance","service":"exchange"}}')


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.cursor().execute("UPDATE app_deployments SET status='stopped' WHERE user_id IN "
                       "(SELECT id FROM app_users WHERE google_sub LIKE 'test:%%')")
    c.close()


class _Feed:
    def __init__(self):
        self.snaps, self.sizes = {}, {}

    def set(self, snaps, sizes):
        self.snaps, self.sizes = {s.contract.ticker: s for s in snaps}, sizes

    def quote(self, ticker, max_age_seconds=None):
        from data_pipeline.common import utc_now
        from data_pipeline.market_data import Quote

        s = self.snaps.get(ticker)
        if s is None:
            return None
        return Quote(ticker=ticker, yes_bid=s.yes_bid, yes_ask=s.yes_ask, yes_bid_size=self.sizes[(ticker, "no")],
                     yes_ask_size=self.sizes[ticker], as_of=utc_now() - timedelta(seconds=0.1), source="websocket")


@pytest.fixture
def offline(monkeypatch):
    """No request may reach Kalshi; the demo cash read answers whatever the test sets."""
    import requests
    from app.trading import demo_twins

    def no_kalshi(*a, **k):
        raise AssertionError("a request escaped to %r" % (a[:1],))

    monkeypatch.setattr(requests, "get", no_kalshi)
    monkeypatch.setattr(requests, "post", no_kalshi)
    from app.web.routes import chat as chat_routes
    monkeypatch.setattr(chat_routes, "_engine_age", lambda cur: 5)  # the engine ticked a moment ago
    pulse = chat_routes._pulse  # the autopilot panel reads the beat in its pulse
    monkeypatch.setattr(chat_routes, "_pulse", lambda *a, **k: dict(pulse(*a, **k), engine_age=5))
    cash = {}
    monkeypatch.setattr(demo_twins, "_read_balance", lambda cur, uid, timeout=15: cash.get(uid))
    demo_twins._BALANCE_CACHE.clear()

    def set_cash(uid, value):
        cash[uid] = value
        demo_twins._BALANCE_CACHE.clear()  # the next page read sees it, as after the 60s memo
    yield set_cash
    demo_twins._BALANCE_CACHE.clear()


def _user(conn, autopilot=True, key=True):
    from app import repository as repo

    cur = conn.cursor()
    user = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "demo-health@example.com", "D", None)
    if autopilot:
        cur.execute("UPDATE app_users SET autopilot=1 WHERE id=%s", (user["id"],))
    if key:
        repo.set_kalshi_dev_key(cur, user["id"], "demo-key-id", b"never-decrypted")  # the balance read is stubbed
    return user["id"]


def _strategy(conn, uid, stake=10.0, modes=("demo",)):
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": stake, "max_positions": 2}})
    sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Demo health", "t", spec, "passed",
                               {"capital": 2 * stake})
    return sid, {m: repo.create_deployment(cur, uid, sid, "btc15m", m) for m in modes}


def _ctx(conn, uid, params=()):
    from app import repository as repo
    from app import server

    return server.Ctx(conn, repo.get_user(conn.cursor(), uid), tuple(str(p) for p in params), {}, {}, None)


def _seen(conn, uid, sid):
    """What each page says about demo: dashboard bucket, Deploy board, autopilot idle, strategy page. None
    of their reads asks Kalshi: a check that needs the demo cash is marked pending, and, as the page does,
    the demo cash follow-up (/api/funds/cash?book=demo) is read before they are read again, from its memo."""
    from app import repository as repo
    from app import server

    c = _ctx(conn, uid)

    def reads():
        return (server.dashboard(c), server.autopilot_status(c), server.list_deployments(c),
                server.get_strategy(_ctx(conn, uid, (sid,))))
    dash, ap, board, page = reads()
    if dash["demo"].get("health_pending") or ap.get("idle_pending") or board.get("demo_health_pending") \
            or page.get("demo_health_pending"):
        server.funds_cash(server.Ctx(conn, repo.get_user(conn.cursor(), uid), (), {"book": "demo"}, {}, None))
        dash, ap, board, page = reads()
    assert not dash["demo"].get("health_pending") and not ap.get("idle_pending")
    assert not board.get("demo_health_pending") and not page.get("demo_health_pending")
    return {"dashboard": dash["demo"]["health"], "deploy": board["demo_health"], "autopilot": ap["idle"],
            "strategy": page["demo_health"]}


def test_an_empty_demo_account_refuses_every_order_silently_and_every_page_now_says_so(conn, offline, monkeypatch):
    """Today's engine behaviour, observed and left alone: the refusal escapes, nothing is booked."""
    from app.trading import engine
    from app import repository as repo
    from app.execution.guard import ExecutionGuard
    from app.trading.markets import Contract, snapshot
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel

    uid = _user(conn)
    offline(uid, 0.0)
    sid, ids = _strategy(conn, uid)
    cur = conn.cursor()
    dep = next(d for d in repo.running_deployments(cur, "btc15m") if d["id"] == ids["demo"])

    def refuse(ticker, action, side, qty, price, client_order_id=None):
        raise RuntimeError(REFUSED)

    # A guard of its own, wired the way demo_kernel_factory wires the process-wide one.
    guard = ExecutionGuard(max_qty=10000, max_notional=5000.0, rate_limit=0, rate_window_s=10.0,
                           breaker_errors=5, breaker_cooldown_s=30.0)
    feed = _Feed()
    kernel = MarketableLimitKernel(guard.wrap(refuse), feed, entry_cross_ticks=2, exit_cross_ticks=2,
                                   max_entry_slippage=0.10, max_attempts=1)
    ticker = "DMH%s-A" % uuid.uuid4().hex[:6].upper()
    now = int(datetime.now(timezone.utc).timestamp())
    feats = {"spot": 100.0, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0, "vol_15m": 0.0005, "vol_60m": 0.0005}
    snaps = [snapshot(feats, Contract(ticker, STRIKE, datetime.now(timezone.utc) + timedelta(minutes=10)), now, 0.38, 0.40)]
    sizes = {ticker: 500.0, (ticker, "no"): 500.0}
    feed.set(snaps, sizes)
    with pytest.raises(RuntimeError, match="insufficient_balance"):
        engine.decide(conn, dep, snaps, sizes, engine.Sources(demo_kernel=lambda u: kernel))
    assert repo.get_deployment(cur, uid, ids["demo"])["status"] == "running"  # still looks fine
    cur.execute("SELECT COUNT(*) AS n FROM app_positions WHERE deployment_id=%s", (ids["demo"],))
    assert cur.fetchone()["n"] == 0
    cur.execute("SELECT status FROM app_order_intents WHERE deployment_id=%s", (ids["demo"],))
    assert [r["status"] for r in cur.fetchall()] == ["sent"]  # recovery finds no order: indeterminate
    # Each refusal counts as an order error on the guard, which demo shares with live in one process.
    assert guard._consec_errors == 1

    # What the user is now told, in every place that shows demo.
    seen = _seen(conn, uid, sid)
    line = "Demo isn't trading: your Kalshi demo account has $0.00. Add demo funds on Kalshi's demo site."
    for where, health in seen.items():
        assert health["code"] == "demo_funds" and health["line"] == line, where
        assert health["action"] == {"label": "Open Kalshi demo", "href": "https://demo.kalshi.co"}, where
    assert seen["strategy"]["need"] == "demo funds: your Kalshi demo account has $0.00"

    # The dashboard shell's reads never wait on Kalshi: with the demo cash memo kept they say the same; without it
    # the check is marked pending (never a "Demo isn't trading" from an unknown figure) and the page asks again.
    from app import server
    from app.trading import demo_twins
    from app.web import shell_reads

    def no_read(*a, **k):
        raise AssertionError("the shell's read asked Kalshi")
    monkeypatch.setattr(demo_twins, "_read_balance", no_read)
    c = _ctx(conn, uid)
    shell = {url: fn for url, fn, _, _ in shell_reads.first_requests("/", "", {})}  # the dashboard's carried reads
    dashboard, autopilot = shell["/api/dashboard"], shell["/api/autopilot/status"]
    assert dashboard(c)["demo"]["health"] == seen["dashboard"]
    assert autopilot(c)["idle"] == seen["autopilot"]
    demo_twins._BALANCE_CACHE.clear()
    dash, ap = dashboard(c), autopilot(c)
    assert dash["demo"]["health"] is None and dash["demo"]["health_pending"] is True
    assert ap["idle_pending"] is True and (ap["idle"] or {}).get("code") != "demo_funds"
    assert shell_reads.then_reads("/api/autopilot/status", ap) == ["/api/funds/cash?book=demo"]
    # So do the routes themselves, as an in-app visit and each poll ask them: memo gone, pending, no Kalshi read.
    routes = {p.pattern: fn for m, p, fn, _ in server.ROUTES if m == "GET"}
    for path in ("/api/dashboard", "/api/autopilot/status"):
        got = routes["^%s$" % path](_ctx(conn, uid))
        assert (got["demo"]["health_pending"] if path == "/api/dashboard" else got["idle_pending"]) is True, path
    assert routes["^/api/funds$"](_ctx(conn, uid))["kalshi_dev"]["pending"] is True


def test_each_demo_state_says_one_plain_thing(conn, offline):
    from app import server
    from app.trading import engine
    from app import repository as repo

    uid = _user(conn)
    sid, ids = _strategy(conn, uid, stake=10.0)
    cur = conn.cursor()

    # Funded: nothing to say anywhere.
    offline(uid, 250.0)
    assert all(v is None for v in _seen(conn, uid, sid).values())
    # A balance that can't be read is unknown, and unknown is never reported as a problem.
    offline(uid, None)
    assert all(v is None for v in _seen(conn, uid, sid).values())
    # Some cash, but less than one stake: Kalshi refuses the order all the same.
    offline(uid, 3.2)
    seen = _seen(conn, uid, sid)
    assert {h["line"] for h in seen.values()} == {
        "Demo isn't trading: your Kalshi demo account has $3.20, less than one $10.00 stake. "
        "Add demo funds on Kalshi's demo site."}

    # No demo key: the engine pauses the copy (its own reason); every page names the key instead.
    repo.delete_kalshi_dev_key(cur, uid)
    dep = next(d for d in repo.running_deployments(cur, "btc15m") if d["id"] == ids["demo"])
    assert engine.decide(conn, dep, [], {}, engine.Sources(demo_kernel=lambda u: None)) == {"paused": "demo disabled"}
    paused = repo.get_deployment(cur, uid, ids["demo"])
    assert paused["status"] == "paused" and "demo (sandbox) key" in paused["status_reason"]
    key_line = "Demo isn't trading: your Kalshi demo key isn't connected."
    for where, health in _seen(conn, uid, sid).items():
        assert health["code"] == "demo_key" and health["line"] == key_line, where
        assert health["action"] == {"label": "Add it on the Funds page", "href": "/funds#connect-kalshi"}, where
    # Paused by the user, there's nothing demo is failing to do.
    repo.set_deployment_status(cur, uid, ids["demo"], "paused", "By you")
    seen = _seen(conn, uid, sid)
    assert seen["dashboard"] is None and seen["deploy"] is None and seen["strategy"] is None
    assert not seen["autopilot"]["code"].startswith("demo_")  # its own idle line, about paper

    # Autopilot off: the idle line is the autopilot's, so it stays quiet; the other pages still say it.
    repo.set_deployment_status(cur, uid, ids["demo"], "running", None)
    cur.execute("UPDATE app_users SET autopilot=0 WHERE id=%s", (uid,))
    seen = _seen(conn, uid, sid)
    assert seen["autopilot"] is None and seen["dashboard"]["code"] == seen["deploy"]["code"] == "demo_key"
    assert server.get_strategy(_ctx(conn, uid, (sid,)))["demo_health"]["code"] == "demo_key"


def test_a_paper_strategy_learns_what_its_demo_rung_needs(conn, offline):
    """Not on demo yet: with a key and an empty demo account, the next rung says it needs funds; the
    account-wide pages say nothing, since no demo copy is failing."""
    from app import server

    uid = _user(conn)
    sid, _ids = _strategy(conn, uid, stake=10.0, modes=("paper",))
    offline(uid, 0.0)
    seen = _seen(conn, uid, sid)
    assert seen["dashboard"] is None and seen["deploy"] is None
    assert seen["autopilot"] is None or seen["autopilot"]["code"] not in ("demo_funds", "demo_key")
    assert seen["strategy"]["code"] == "demo_funds"
    # Without a key, the strategy page's own deploy check already names it; nothing more is added.
    from app import repository as repo
    repo.delete_kalshi_dev_key(conn.cursor(), uid)
    assert server.get_strategy(_ctx(conn, uid, (sid,)))["demo_health"] is None


def _board_ctx(conn, uid, v):
    """The Deploy board poll's context: its last answer's version (?v=)."""
    from app import repository as repo
    from app import server

    return server.Ctx(conn, repo.get_user(conn.cursor(), uid), (), {"v": v}, {}, None)


def test_the_deploy_board_poll_and_the_strategy_page_never_ask_kalshi(conn, offline, monkeypatch):
    """The Deploy board's 10s poll (and its shell read) and the strategy page read the demo cash from Kalshi, up
    to its 3s demo timeout, each time the memo ran out. They read the memo alone now, whoever asks: the check is
    pending, the page asks /api/funds/cash?book=demo, then reads again once. Kalshi's demo read raises here."""
    import time

    from app import repository as repo
    from app import server
    from app.trading import demo_twins
    from app.web import shell_reads

    uid = _user(conn)
    sid, _ids = _strategy(conn, uid, stake=10.0)  # a demo copy running, $10 a stake
    offline(uid, 0.0)  # the demo account is empty; the memo holds nothing yet
    read = demo_twins._read_balance

    def no_kalshi(*a, **k):
        raise AssertionError("a page read asked Kalshi for the demo cash")
    monkeypatch.setattr(demo_twins, "_read_balance", no_kalshi)
    board_route = next(fn for m, p, fn, _ in server.ROUTES if m == "GET" and p.match("/api/deployments"))
    page_route = next(fn for m, p, fn, _ in server.ROUTES if m == "GET" and p.match("/api/strategies/%d" % sid))
    board = board_route(_ctx(conn, uid))
    page = page_route(_ctx(conn, uid, (sid,)))
    assert board["demo_health"] is None and board["demo_health_pending"] is True
    assert page["demo_health"] is None and page["demo_health_pending"] is True
    assert shell_reads.then_reads("/api/deployments", board) == ["/api/funds/cash?book=demo"]
    # The shell's first read of /deploy is this same route: it carries the board and names the follow-up.
    assert shell_reads.first_requests("/deploy", "", {})[0][1] is server.list_deployments
    # The poll while it is still pending: "same", and no Kalshi read.
    assert board_route(_board_ctx(conn, uid, board["v"])).get("same") is True

    # The follow-up (the one page read that may wait on Kalshi); then each page reads the memo: the line.
    monkeypatch.setattr(demo_twins, "_read_balance", read)
    server.funds_cash(server.Ctx(conn, repo.get_user(conn.cursor(), uid), (), {"book": "demo"}, {}, None))
    monkeypatch.setattr(demo_twins, "_read_balance", no_kalshi)
    after = board_route(_board_ctx(conn, uid, board["v"]))
    assert not after.get("same") and after["v"] != board["v"], "the board's version moves once the demo cash is in"
    assert after["demo_health"]["code"] == "demo_funds" and "demo_health_pending" not in after
    page = page_route(_ctx(conn, uid, (sid,)))
    assert page["demo_health"]["code"] == "demo_funds" and "demo_health_pending" not in page

    # The memo just ran out (70s old): pending again, the line from that figure standing meanwhile; no Kalshi read.
    cash = demo_twins._BALANCE_CACHE[uid][1]
    demo_twins._BALANCE_CACHE[uid] = (time.monotonic() - 70, cash)
    board = board_route(_ctx(conn, uid))
    page = page_route(_ctx(conn, uid, (sid,)))
    assert board["demo_health_pending"] is True and board["demo_health"]["code"] == "demo_funds"
    assert page["demo_health_pending"] is True and page["demo_health"]["code"] == "demo_funds"
    # Over two minutes old: pending with no line until the follow-up is in.
    demo_twins._BALANCE_CACHE[uid] = (time.monotonic() - 130, cash)
    board = board_route(_ctx(conn, uid))
    assert board["demo_health_pending"] is True and board["demo_health"] is None
    assert page_route(_ctx(conn, uid, (sid,)))["demo_health"] is None
