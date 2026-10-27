"""A market page's "Your positions here", on a real MySQL: user_positions_in_ticker returns the reader's own
positions in one contract, open and settled since the contract opened, each with its mode, strategy title and
id, and nobody else's. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1)."""
import os
import uuid
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


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


def test_positions_in_one_contract_are_the_readers_own_by_mode_and_since_it_opened(conn):
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "mkt@example.com", "M", None)["id"]
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "other@example.com", "O", None)["id"]
    tag = uuid.uuid4().hex[:8].upper()
    here, elsewhere = "KXBTCD-%s-T1" % tag, "KXBTCD-%s-T2" % tag
    opened = datetime(2026, 10, 25, 21, 0)
    close = opened + timedelta(days=1)

    def strategy(user, title):
        sid = repo.insert_strategy(cur, user, None, None, "btc_daily", "momentum", title, "t",
                                   specmod.validate({"market": "btc_daily", "side": "yes"}), "passed", {})
        return sid, {m: repo.create_deployment(cur, user, sid, "btc_daily", m) for m in ("paper", "live")}

    sid, dep = strategy(uid, "Drift")
    gone_sid, gone = strategy(uid, "Deleted later")
    _, theirs = strategy(other, "Not yours")
    live = repo.insert_position(cur, dep["live"], uid, "live", here, "yes", 2, 0.52, 0.02, close)
    paper = repo.insert_position(cur, dep["paper"], uid, "paper", here, "no", 10, 0.44, 0.05, close)
    orphan = repo.insert_position(cur, gone["paper"], uid, "paper", here, "yes", 1, 0.5, 0.01, close)
    repo.insert_position(cur, dep["paper"], uid, "paper", elsewhere, "yes", 3, 0.3, 0.01, close)
    repo.insert_position(cur, theirs["paper"], other, "paper", here, "yes", 4, 0.4, 0.01, close)
    settled = repo.insert_closed_position(cur, dep["paper"], uid, "paper", here, "no", 8, 0.7, 0.08, 0.75, 0.08, 0.24, "take_profit",
                                          close, opened_at=opened + timedelta(hours=1), closed_at=opened + timedelta(hours=2))
    # Settled before this contract opened: the bound leaves it out (the page reads only since the open).
    repo.insert_closed_position(cur, dep["paper"], uid, "paper", here, "no", 1, 0.5, 0.01, 1.0, 0.0, 0.49, "settled",
                                close, opened_at=opened - timedelta(hours=3), closed_at=opened - timedelta(hours=1))
    cur.execute("DELETE FROM app_strategies WHERE id=%s", (gone_sid,))
    conn.commit()

    got = repo.user_positions_in_ticker(cur, uid, here, opened)
    assert [p["id"] for p in got["open"]] == [orphan, paper, live]  # newest first
    by_id = {p["id"]: p for p in got["open"]}
    assert by_id[live]["mode"] == "live" and by_id[paper]["mode"] == "paper"
    assert by_id[live]["title"] == "Drift" and by_id[live]["strategy_id"] == sid
    assert by_id[orphan]["title"] is None  # its strategy was deleted; the position is still money in the book
    assert [p["id"] for p in got["closed"]] == [settled] and float(got["closed"][0]["pnl"]) == 0.24
    assert all(p["ticker"] == here and p["user_id"] == uid for p in got["open"] + got["closed"])
    assert repo.user_positions_in_ticker(cur, other, elsewhere, opened) == {"open": [], "closed": []}


def test_markets_with_strategies_are_the_readers_own_without_the_seeded_example(conn):
    # A market page offers "Your <market> strategies" only for a market the reader has a strategy on: it showed to
    # a reader with none there. The seeded example's strategies (btc15m) aren't theirs, and nobody else's count.
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "mine@example.com", "M", None)["id"]
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "theirs@example.com", "O", None)["id"]
    repo.seed_demo_session(cur, uid)
    repo.insert_strategy(cur, uid, None, None, "btc_daily", "momentum", "Mine", "t",
                         specmod.validate({"market": "btc_daily", "side": "yes"}), "rejected", {})
    repo.insert_strategy(cur, other, None, None, "btc15m", "momentum", "Theirs", "t",
                         specmod.validate({"market": "btc15m", "side": "yes"}), "passed", {})
    conn.commit()
    cur.execute("SELECT COUNT(*) AS n FROM app_strategies WHERE user_id=%s AND market='btc15m'", (uid,))
    assert cur.fetchone()["n"] > 0, "the seeded example has strategies on btc15m"
    assert repo.markets_with_strategies(cur, uid, ["btc15m", "btc_daily"]) == ["btc_daily"]
    assert repo.markets_with_strategies(cur, other, ["btc15m", "btc_daily"]) == ["btc15m"]
    assert repo.markets_with_strategies(cur, uid, []) == []
