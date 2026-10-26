"""Demo isolated from live, against a real MySQL: the in-flight block is per mode, a demo order the
exchange refuses outright settles 'unfilled' with the refusal stored, and the live gate's demo check
says demo couldn't trade instead of counting refusals as settled (or lost) orders. Live's own orders
behave exactly as before. Needs APP_TEST_MYSQL=1 and the MYSQL_* variables, like test_app_engine_db.py.

The orders go through the real kernels, guards and exchange adapters (demo_place_limit_order,
place_limit_order -> api_post_auth); only the HTTP POST and the request signing are stubbed."""
import json
import os
import uuid
from collections import deque
from datetime import timedelta

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

TICKER = "KXBTC15M-ISO"
INSUFFICIENT = '{"error":{"code":"insufficient_balance","message":"insufficient balance","service":"exchange"}}'


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


@pytest.fixture
def user(conn):
    """A user with one strategy deployed on demo and on live."""
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    u = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "t@example.com", "T", None)
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}})
    sid = repo.insert_strategy(cur, u["id"], None, None, "btc15m", "volatility", "T", "t", spec, "passed", {})
    deps = {}
    for mode in ("demo", "live"):
        did = repo.create_deployment(cur, u["id"], sid, "btc15m", mode)
        cur.execute("UPDATE app_deployments SET status='stopped' WHERE id=%s", (did,))
        deps[mode] = {"id": did, "user_id": u["id"], "mode": mode}
    return {"id": u["id"], "sid": sid, "deps": deps}


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text

    def json(self):
        return json.loads(self.text)


class _Feed:
    def quote(self, ticker, max_age_seconds=None):
        from data_pipeline.common import utc_now
        from data_pipeline.market_data import Quote

        return Quote(ticker=ticker, yes_bid=0.39, yes_ask=0.40, yes_bid_size=100, yes_ask_size=100,
                     as_of=utc_now() - timedelta(seconds=0.1), source="websocket")


class _Conn:
    def cursor(self):
        return None


@pytest.fixture
def venues(monkeypatch):
    """Real live and demo kernels (guards, adapters) whose HTTP POST answers with ``answer``."""
    from app.trading import engine
    from app.adapters.kalshi import kalshi_account, kalshi_dev_exec
    from app import repository as repo
    from app.execution import guard, latency
    from data_pipeline import common
    from data_pipeline.architecture import position_guard

    for g in (guard._GUARD, guard._DEMO_GUARD):
        monkeypatch.setattr(g, "_consec_errors", 0)
        monkeypatch.setattr(g, "_open_until", 0.0)
        monkeypatch.setattr(g, "_buy_times", deque())
    monkeypatch.setattr(guard._GUARD._db_switch, "is_on", lambda: False)
    monkeypatch.delenv("APP_KILL_SWITCH", raising=False)
    monkeypatch.setattr(latency, "_record", lambda **row: None)
    monkeypatch.setattr(repo, "get_kalshi_key", lambda cur, uid: {"key_id": "live"})
    monkeypatch.setattr(repo, "get_kalshi_dev_key", lambda cur, uid: {"key_id": "demo"})
    monkeypatch.setattr(repo, "user_execution_config", lambda cur, uid: {})
    monkeypatch.setattr(kalshi_account, "credentials_from_row", lambda uid, row: (row["key_id"], object()))
    monkeypatch.setattr(position_guard, "exchange_net_reader", lambda creds: (lambda ticker: 0))
    monkeypatch.setattr(kalshi_dev_exec, "demo_net_reader", lambda creds: (lambda ticker: 0))
    monkeypatch.setattr(common, "kalshi_auth_headers", lambda *a, **k: {})
    monkeypatch.setattr(kalshi_dev_exec, "kalshi_auth_headers", lambda *a, **k: {})
    answer = {"status": 400, "text": INSUFFICIENT}
    posted = []

    def post(url, json=None, headers=None, timeout=None):
        posted.append(url)
        return _Resp(answer["status"], answer["text"])

    monkeypatch.setattr(common.requests, "post", post)
    kernels = {"live": engine.live_kernel_factory(_Conn())(1), "demo": kalshi_dev_exec.demo_kernel_factory(_Conn())(1)}
    for k in kernels.values():
        k._feed = _Feed()
    return {"kernels": kernels, "answer": answer, "posted": posted}


def _intent_row(conn, iid):
    cur = conn.cursor()
    cur.execute("SELECT status, raw_json FROM app_order_intents WHERE intent_id=%s", (iid,))
    row = cur.fetchone()
    return row["status"], (json.loads(row["raw_json"]) if isinstance(row["raw_json"], str) else row["raw_json"])


def _buy(conn, user, venues, mode):
    """One real entry the way the engine sends it: the intent first, then the order through the kernel."""
    from app.trading import engine

    dep = user["deps"][mode]
    iid = engine._log_order_intent(conn, dep, "buy", "yes", TICKER, 1, 0.40, mode)
    try:
        engine._live_trade(conn.cursor(), dep, venues["kernels"][mode], "buy", "yes", TICKER, 1, 0.40,
                           client_order_id_base=iid)
    except Exception as e:
        return iid, e
    return iid, None


# 1. The in-flight block is per mode.

def test_a_demo_order_in_flight_never_holds_live_and_a_live_one_never_holds_demo(conn, user):
    from app.trading import engine
    from app import repository as repo

    uid = user["id"]
    engine._log_order_intent(conn, user["deps"]["demo"], "buy", "yes", TICKER, 1, 0.40, "demo")
    assert engine._order_in_flight(conn.cursor(), uid, TICKER, "demo") is True
    assert engine._order_in_flight(conn.cursor(), uid, TICKER, "live") is False
    engine._log_order_intent(conn, user["deps"]["live"], "buy", "yes", TICKER + "-L", 1, 0.40, "live")
    assert engine._order_in_flight(conn.cursor(), uid, TICKER + "-L", "live") is True
    assert engine._order_in_flight(conn.cursor(), uid, TICKER + "-L", "demo") is False
    assert repo.ticker_has_inflight_intent(conn.cursor(), uid, TICKER, 180, mode="live") is False


def test_within_live_the_block_is_exactly_as_strict_as_before(conn, user):
    """Live's own 'sent' order holds live's ticker across every live deployment for the window, then
    lets go; a settled one never holds it."""
    from app.trading import engine

    uid, dep = user["id"], user["deps"]["live"]
    iid = engine._log_order_intent(conn, dep, "sell", "yes", TICKER, 1, 0.40, "live")
    assert engine._order_in_flight(conn.cursor(), uid, TICKER, "live") is True
    cur = conn.cursor()
    cur.execute("UPDATE app_order_intents SET created_at = created_at - INTERVAL %s SECOND WHERE intent_id=%s",
                (engine.INFLIGHT_BLOCK_SECONDS + 5, iid))
    assert engine._order_in_flight(conn.cursor(), uid, TICKER, "live") is False  # past the window
    iid2 = engine._log_order_intent(conn, dep, "buy", "yes", TICKER, 1, 0.40, "live")
    assert engine._order_in_flight(conn.cursor(), uid, TICKER, "live") is True
    conn.cursor().execute("UPDATE app_order_intents SET status='unfilled' WHERE intent_id=%s", (iid2,))
    assert engine._order_in_flight(conn.cursor(), uid, TICKER, "live") is False


# 2. A definite refusal settles a demo intent; anything else stays 'sent'.

def test_a_demo_order_refused_for_insufficient_balance_settles_unfilled_with_the_refusal(conn, user, venues):
    from app.trading import engine
    from app.execution import guard
    from app.execution.refusal import OrderRefused

    iid, err = _buy(conn, user, venues, "demo")
    assert isinstance(err, OrderRefused) and isinstance(err, RuntimeError)
    assert str(err).startswith("demo POST /portfolio/events/orders failed 400: ")  # same message as before
    status, raw = _intent_row(conn, iid)
    assert status == "unfilled"
    assert raw["status"] == "refused"
    assert raw["refused"]["code"] == "insufficient_balance" and raw["refused"]["http_status"] == 400
    assert guard._DEMO_GUARD._consec_errors == 1 and guard._GUARD._consec_errors == 0  # still counted, on demo
    assert engine._order_in_flight(conn.cursor(), user["id"], TICKER, "demo") is False


@pytest.mark.parametrize("status,text", [
    (500, '{"error":{"code":"internal_server_error"}}'),
    (503, "service unavailable"),
    (409, '{"error":{"code":"order_already_exists","message":"duplicate client_order_id"}}'),
    (429, '{"error":{"code":"too_many_requests"}}'),
    (408, "request timeout"),
])
def test_a_demo_error_that_may_have_left_an_order_stays_sent(conn, user, venues, status, text):
    venues["answer"].update(status=status, text=text)
    iid, err = _buy(conn, user, venues, "demo")
    assert type(err) is RuntimeError
    assert _intent_row(conn, iid) == ("sent", None)


def test_a_demo_timeout_stays_sent(conn, user, venues, monkeypatch):
    import requests
    from data_pipeline import common

    def timeout(*a, **k):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(common.requests, "post", timeout)
    iid, err = _buy(conn, user, venues, "demo")
    assert isinstance(err, requests.Timeout)
    assert _intent_row(conn, iid) == ("sent", None)


# Live's own orders: byte-identical behaviour.

def test_live_orders_behave_exactly_as_before(conn, user, venues):
    """The same 400 insufficient_balance on LIVE raises live's own plain RuntimeError and leaves the
    intent 'sent' for recovery, holding live's ticker, exactly as before this change."""
    from app.trading import engine
    from app.execution import guard

    iid, err = _buy(conn, user, venues, "live")
    assert type(err) is RuntimeError and str(err).startswith("POST ") and " failed 400: " in str(err)
    assert _intent_row(conn, iid) == ("sent", None)
    assert engine._order_in_flight(conn.cursor(), user["id"], TICKER, "live") is True
    assert guard._GUARD._consec_errors == 1 and guard._DEMO_GUARD._consec_errors == 0
    assert any("demo" not in u for u in venues["posted"])  # it really went down live's adapter


# 3. The live gate's demo check.

def test_demo_that_never_traded_says_so_and_why(conn, user, venues):
    from app import repository as repo
    from app.services import demo_record

    for _ in range(3):
        _buy(conn, user, venues, "demo")
    out = repo.demo_order_outcomes(conn.cursor(), user["id"], user["sid"], repo.now_utc() + timedelta(hours=2))
    assert out["refused"] == 3 and out["resolved"] == 0 and out["booked"] == 0 and out["unresolved"] == 0
    assert out["last_refusal"]["code"] == "insufficient_balance"
    ev = demo_record.demo_evidence(conn.cursor(), user["id"], user["sid"])
    assert not ev["ok"] and ev["refused"] == 3
    assert ev["why"].startswith("it couldn't trade on the demo exchange yet: Kalshi refused its 3 demo orders")
    assert "enough balance" in ev["why"] and "never accounted for" not in ev["why"]


def test_refusals_are_never_counted_as_settled_orders(conn, user, venues):
    from app import repository as repo

    did, uid = user["deps"]["demo"]["id"], user["id"]
    cur = conn.cursor()
    for status in ("booked", "booked", "unfilled"):  # orders the demo exchange really took
        iid = str(uuid.uuid4())
        repo.insert_order_intent(cur, iid, did, uid, "demo", "buy", "yes", TICKER, 1, 0.4, iid)
        cur.execute("UPDATE app_order_intents SET status=%s WHERE intent_id=%s", (status, iid))
    _buy(conn, user, venues, "demo")
    out = repo.demo_order_outcomes(conn.cursor(), uid, user["sid"], repo.now_utc())
    assert out["resolved"] == 3 and out["refused"] == 1 and out["booked"] == 2
