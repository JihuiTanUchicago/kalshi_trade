"""The track record and the Strategies page read faster and say exactly what they said, against a real
MySQL. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).

- /api/track-record used to be one join of every position to its deployment and strategy, grouped per
  trade; it now groups the user's positions alone, reads each deployment's strategy once and brings
  the times back as whole seconds. Its rows (same order) and the page's JSON must match the old join
  byte for byte, on a book holding every awkward case: part-sold trades (one still open), instant paper
  fills, the same order_ref in two deployments, a deleted strategy and a deployment row that is gone.
- /api/strategies counts and lists each strategy's active deployments through idx_dep_strategy. An
  index changes the plan, never the answer: every filter's JSON is the same with and without it.
Another account's book sits beside it, so a read that leaked across users would show.
"""
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

NOW = datetime(2026, 10, 26, 12, 30, tzinfo=timezone.utc)
# The read the track record made before (deployment_repository.track_record_rows). It had no ORDER BY:
# MariaDB returned its groups in key order, MySQL in no promised order, so the reference pins the key
# order the new read states.
OLD_TRACK_RECORD_SQL = """
    SELECT p.mode, MAX(d.strategy_id) AS strategy_id, MAX(s.title) AS title,
           MAX(COALESCE(s.market, d.market)) AS market, MAX(d.status) AS dep_status,
           MAX(p.order_ref) AS order_ref,
           SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END) AS open_slices,
           COALESCE(SUM(p.pnl),0) AS pnl,
           COALESCE(SUM(p.entry_fee + COALESCE(p.exit_fee,0)),0) AS fees,
           COALESCE(SUM(p.qty * p.entry_price),0) AS cost,
           COALESCE(SUM(CASE WHEN p.status='open' THEN p.qty * p.entry_price END),0) AS open_cost,
           MIN(p.opened_at) AS opened_at, MAX(p.closed_at) AS closed_at
    FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
    LEFT JOIN app_strategies s ON s.id=d.strategy_id
    WHERE p.user_id=%s
    GROUP BY p.mode, p.deployment_id, COALESCE(p.order_ref, CONCAT('row:', p.id))
    ORDER BY p.mode, p.deployment_id, COALESCE(p.order_ref, CONCAT('row:', p.id))"""
STRATEGY_QUERIES = [{}, {"status": "passed"}, {"status": "rejected"}, {"deployed": "1"}, {"page": "1"},
                    {"market": "eth15m"}, {"direction": "momentum", "status": "failed"}, {"q": "Book"},
                    {"q": "nothing like this"}, {"deployed": "1", "market": "btc15m"}]


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


def _book(conn, rng, label, n_strategies, n_deployments, n_trades):
    """One account: strategies of every status, deployments in every mode and state, and a book of
    closed and open trades, some sold in slices that share their entry's order_ref."""
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, label + "@example.invalid", label, None)["id"]
    sids = []
    for i in range(n_strategies):
        spec = specmod.validate({"side": rng.choice(["yes", "no"]), "entry": {"min_edge": 0.05},
                                 "sizing": {"stake": rng.choice([5.0, 10.0]), "max_positions": 4}})
        result = {"capital": 40.0, "equity": [[1761400000 + 900 * k, round(rng.uniform(-5, 5), 2)] for k in range(20)],
                  "in_sample": {"trades": rng.randint(20, 200), "pnl": round(rng.uniform(-9, 30), 2)},
                  "out_of_sample": {"trades": rng.randint(5, 90), "pnl": round(rng.uniform(-9, 12), 2)}}
        sids.append(repo.insert_strategy(cur, uid, None, None, rng.choice(["btc15m", "eth15m"]),
                                         rng.choice(["momentum", "volatility"]), "Book %s %d" % (label, i), "t", spec,
                                         rng.choice(["passed", "passed", "rejected", "failed", "inconclusive"]), result))
    deps = []
    for i in range(n_deployments):
        mode = ("paper", "paper", "demo", "live")[i % 4]
        did = repo.create_deployment(cur, uid, sids[i % len(sids)], "btc15m", mode)
        if i % 3 == 0:
            cur.execute("UPDATE app_deployments SET status=%s WHERE id=%s", (rng.choice(["stopped", "paused"]), did))
        deps.append((did, mode))
    start = datetime(2026, 8, 1)
    rows = []
    for i in range(n_trades):
        did, mode = rng.choice(deps)
        ref = rng.choice(["sim:%s-%d" % (label, i), None]) if mode == "paper" else "%s:%s-%d" % (mode, label, i)
        opened = start + timedelta(minutes=rng.randint(0, 120000))
        for k in range(rng.choice([1, 1, 1, 2, 3])):  # a part-sold trade: its slices share the entry's order_ref
            still_open = rng.random() < 0.03
            qty, price = rng.randint(1, 20), round(rng.uniform(0.05, 0.9), 2)
            exit_price = None if still_open else rng.choice([0.0, 1.0, round(rng.uniform(0.05, 0.95), 2)])
            closed = None if still_open else opened + timedelta(minutes=rng.randint(1, 900))
            rows.append((did, uid, mode, "KXBTC15M-26OCT%04d-T98" % (i % 300), "yes", qty, price, 0.07,
                         opened + timedelta(hours=1), opened + timedelta(seconds=k), "open" if still_open else "closed",
                         exit_price, None if still_open else 0.07,
                         None if still_open else round(qty * (exit_price - price) - 0.14, 4), ref, closed))
    cur.executemany(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
             market_close_time, opened_at, status, exit_price, exit_fee, pnl, order_ref, closed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
    return uid, sids, deps


def _payload(value):
    from app import server

    return json.dumps(value, default=server._json_default, separators=(",", ":"))


def test_the_track_record_and_strategies_page_say_what_they_said(conn, monkeypatch):
    from app import repository as repo
    from app import server
    from app.trading import track_record

    rng = random.Random(20261026)
    uid, sids, deps = _book(conn, rng, "heavy", 60, 14, 1500)
    _book(conn, rng, "beside", 30, 8, 600)
    cur = conn.cursor()
    # The same order_ref in two deployments is two trades; a strategy deleted under a stopped deployment
    # keeps its trades (untitled); a deployment row that is gone drops its trades, as the join did.
    (d1, _), (d2, _) = [d for d in deps if d[1] == "paper"][:2]
    for did in (d1, d2):
        repo.insert_closed_position(cur, did, uid, "paper", "KXBTC15M-SAME", "yes", 4, 0.5, 0.07, 1.0, 0.0, 1.93,
                                    "settled", NOW, order_ref="sim:same-ref", opened_at=datetime(2026, 9, 1),
                                    closed_at=datetime(2026, 9, 1, 0, 15))
    cur.execute("SELECT strategy_id FROM app_deployments WHERE id=%s", (deps[3][0],))
    cur.execute("DELETE FROM app_strategies WHERE id=%s", (cur.fetchone()["strategy_id"],))
    gone = repo.create_deployment(cur, uid, sids[0], "btc15m", "paper")
    repo.insert_closed_position(cur, gone, uid, "paper", "KXBTC15M-GONE", "yes", 4, 0.5, 0.07, 1.0, 0.0, 1.93, "settled",
                                NOW, order_ref="sim:gone", opened_at=datetime(2026, 9, 2), closed_at=datetime(2026, 9, 2, 1))
    cur.execute("DELETE FROM app_deployments WHERE id=%s", (gone,))

    cur.execute(OLD_TRACK_RECORD_SQL, (uid,))
    old_rows = cur.fetchall()
    new_rows = repo.track_record_rows(cur, uid)
    assert len(new_rows) > 1000 and any(r["title"] is None for r in new_rows) and any(r["open_slices"] for r in new_rows)
    assert not any(r["order_ref"] == "sim:gone" for r in new_rows)
    assert sum(r["order_ref"] == "sim:same-ref" for r in new_rows) == 2
    assert new_rows == old_rows  # every value, the same type, in the same order

    real_build, real_finish = track_record.build, track_record.finish
    # The page finishes its kept buckets at the request's time (track_record.finish, as build does).
    monkeypatch.setattr(server.track_record, "finish", lambda prepared, now=None: real_finish(prepared, NOW))
    server._TRACK_RECORD.pop(uid, None)
    page = _payload(server.get_track_record(server.Ctx(conn, {"id": uid}, (), {}, {}, None)))
    assert page == _payload(real_build(old_rows, NOW))
    assert json.loads(page)["modes"]["paper"]["trades"] > 100

    def strategies_pages():
        return [_payload(server.list_strategies(server.Ctx(conn, {"id": uid}, (), dict(q), {}, None)))
                for q in STRATEGY_QUERIES]

    cur.execute("SELECT COUNT(*) AS n FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='app_deployments' AND INDEX_NAME='idx_dep_strategy'")
    assert cur.fetchone()["n"] == 2  # (strategy_id, status), added by app.schema
    indexed = strategies_pages()
    assert json.loads(indexed[3])["counts"]["deployed"] > 0 and any('"real":' in p for p in indexed)
    cur.execute("ALTER TABLE app_deployments DROP INDEX idx_dep_strategy")
    try:
        assert strategies_pages() == indexed
    finally:
        from app import schema

        schema.main()  # puts the index back for the tests that follow
