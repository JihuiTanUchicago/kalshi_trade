"""The demo check's SQL against a real MySQL (app/adapters/db/demo_record_repository.py). Needs
APP_TEST_MYSQL=1 and the MYSQL_* variables, like test_app_engine_db.py."""
import os
import uuid
from datetime import timedelta

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


def _strategy_with_demo(conn):
    from app import repository as repo
    from app import spec as specmod

    cur = conn.cursor()
    u = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "t@example.com", "T", None)
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}})
    sid = repo.insert_strategy(cur, u["id"], None, None, "btc15m", "volatility", "T", "t", spec, "passed", {})
    did = repo.create_deployment(cur, u["id"], sid, "btc15m", "demo")
    cur.execute("UPDATE app_deployments SET status='stopped' WHERE id=%s", (did,))
    return u["id"], sid, did


def _intent(conn, uid, did, status, age=timedelta(0), mode="demo"):
    from app import repository as repo

    iid = str(uuid.uuid4())
    cur = conn.cursor()
    repo.insert_order_intent(cur, iid, did, uid, mode, "buy", "yes", "KXBTC15M-T", 1, 0.5, iid)
    cur.execute("UPDATE app_order_intents SET status=%s, created_at=created_at - INTERVAL %s SECOND WHERE intent_id=%s",
                (status, int(age.total_seconds()), iid))


def test_order_outcomes_count_settled_and_lost_orders_of_this_strategy_only(conn):
    from app import repository as repo

    uid, sid, did = _strategy_with_demo(conn)
    assert not repo.has_demo_activity(conn.cursor(), uid)
    for st in ("booked", "booked", "unfilled"):
        _intent(conn, uid, did, st, age=timedelta(hours=3))
    _intent(conn, uid, did, "sent")                              # in flight: not lost yet
    _intent(conn, uid, did, "sent", age=timedelta(hours=2))      # lost
    _intent(conn, uid, did, "unresolved", age=timedelta(hours=5))  # lost
    _intent(conn, uid, did, "booked", mode="live")               # not a demo order
    out = repo.demo_order_outcomes(conn.cursor(), uid, sid, repo.now_utc() - timedelta(hours=1))
    assert out["resolved"] == 3 and out["unresolved"] == 2
    assert out["first_at"] <= repo.now_utc() - timedelta(hours=4)
    assert repo.has_demo_activity(conn.cursor(), uid)
    assert repo.demo_order_outcomes(conn.cursor(), uid, sid + 10_000, repo.now_utc())["resolved"] == 0


def test_sweeps_round_trip_and_include_the_one_just_before_since(conn):
    from app import repository as repo
    from app.services import demo_record

    uid, _sid, _did = _strategy_with_demo(conn)
    now = repo.now_utc().replace(microsecond=0)
    cur = conn.cursor()
    repo.insert_demo_sweep(cur, uid, 2, [{"ticker": "A", "kind": "untracked", "exchange_qty": 1, "book_qty": 0}],
                           checked_at=now - timedelta(hours=3))
    repo.insert_demo_sweep(cur, uid, 2, [{"ticker": "A", "kind": "untracked", "exchange_qty": 1, "book_qty": 0}],
                           checked_at=now - timedelta(hours=2))
    repo.insert_demo_sweep(cur, uid, 1, [], checked_at=now - timedelta(hours=1))
    t = [now - timedelta(hours=h) for h in (3, 2, 1)]
    # The sweep just before `since` comes along, so a mismatch spanning `since` still pairs up.
    rows = repo.demo_sweeps_since(cur, uid, now - timedelta(minutes=150))
    assert [r["checked_at"] for r in rows] == t
    assert rows[0]["mismatches"][0]["ticker"] == "A"
    assert [r["checked_at"] for r in repo.demo_sweeps_since(cur, uid, now - timedelta(minutes=90))] == t[1:]
    assert demo_record.persisted_mismatches(repo.demo_sweeps_since(cur, uid, None)) == ["A"]


def test_demo_book_sums_open_demo_positions_by_ticker_and_side(conn):
    from app import repository as repo

    uid, _sid, did = _strategy_with_demo(conn)
    cur = conn.cursor()
    for mode, side, qty, status in (("demo", "yes", 2, "open"), ("demo", "yes", 3, "open"),
                                    ("demo", "no", 1, "closed"), ("live", "yes", 9, "open")):
        cur.execute(
            """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
                 market_close_time, opened_at, status) VALUES (%s,%s,%s,'KXBTC15M-T',%s,%s,0.5,0,%s,%s,%s)""",
            (did, uid, mode, side, qty, repo.now_utc(), repo.now_utc(), status))
    rows = repo.demo_book_by_ticker_side(cur, uid)
    assert [(r["ticker"], r["side"], int(r["qty"])) for r in rows] == [("KXBTC15M-T", "yes", 5)]
