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
    """What each page says about demo: dashboard bucket, Deploy board, autopilot idle, strategy page."""
    from app import server

    c = _ctx(conn, uid)
    return {"dashboard": server.dashboard(c)["demo"]["health"],
            "deploy": server.list_deployments(c)["demo_health"],
            "autopilot": server.autopilot_status(c)["idle"],
            "strategy": server.get_strategy(_ctx(conn, uid, (sid,)))["demo_health"]}


def test_an_empty_demo_account_refuses_every_order_silently_and_every_page_now_says_so(conn, offline):
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
    key_line = "Demo isn't trading: your Kalshi demo key isn't connected. Add it on the Funds page."
    for where, health in _seen(conn, uid, sid).items():
        assert health["code"] == "demo_key" and health["line"] == key_line, where
        assert health["action"] == {"label": "Add demo key", "href": "/funds"}, where
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
