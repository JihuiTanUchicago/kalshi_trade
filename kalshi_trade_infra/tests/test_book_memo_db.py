"""The polled pages keep the sums they make from a user's positions (services.book_memo) until those
positions change, and are never stale for it. Against a real MySQL; opt in as for test_app_engine_db.py
(APP_TEST_MYSQL=1).

On a book with every kind of row (paper, demo and live; closed, open and part-sold trades; a stopped
deployment; a second account beside it), each page's JSON with its kept reads must equal the JSON it
gives with nothing kept, while the book is unchanged and after each write the engine, the autopilot or
the user makes: a position opened, closed, sold in part, a paper trade replayed into the past, a
deployment re-pointed at an adjusted strategy, stopped, and a new one deployed. While nothing changed,
the kept reads must actually be used (fewer statements, none of the full-history sums).
"""
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

NOW = datetime(2026, 10, 26, 12, 0, 0)
# The full-history sums the kept reads stand for: none may run on a request while the book is unchanged.
HEAVY = ("SUM(pnl) OVER (PARTITION BY deployment_id", "LEFT JOIN (SELECT p.deployment_id", "AS paper_all",
         "GROUP BY p.mode, p.deployment_id, COALESCE(p.order_ref", "COUNT(DISTINCT SUBSTRING(p.ticker",
         "SELECT t.strategy_id, COUNT(*) AS trips", "SELECT d.strategy_id, p.order_ref, SUM(p.pnl)", "AS pnl_sq", "GROUP BY DATE(closed_at)")


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


@pytest.fixture
def frozen(monkeypatch):
    """One clock for every read (the kept and the fresh JSON are compared byte for byte)."""
    import sys

    from app.trading import engine, track_record
    from app.adapters.stripe import billing
    from app.research import rsi
    from app.adapters.db import sql
    from app.services import book_memo

    real = sql.now_utc
    for m in list(sys.modules.values()):
        if m is not None and getattr(m, "now_utc", None) is real:
            monkeypatch.setattr(m, "now_utc", lambda: NOW)
    for name in ("paper_pace", "paper_trade_rate"):  # the paper pace reads the wall clock
        fn = getattr(rsi, name)
        monkeypatch.setattr(rsi, name, lambda dep, trips, now=None, _fn=fn: _fn(dep, trips, now or NOW))
    finish = track_record.finish
    monkeypatch.setattr(track_record, "finish", lambda prepared, now=None: finish(prepared, NOW.replace(tzinfo=timezone.utc)))
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", False)
    book_memo.clear()
    yield
    book_memo.clear()


class Counting:
    """The connection, with each statement the request sends recorded."""

    def __init__(self, conn):
        self.conn, self.log = conn, []

    def cursor(self):
        cur = self.conn.cursor()
        ex = cur.execute

        def execute(sql, params=None):
            self.log.append(" ".join(str(sql).split()))
            return ex(sql, params)
        cur.execute = execute
        return cur


def _book(conn, rng, label, n_trades):
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, label + "@example.invalid", label, None)["id"]
    cur.execute("UPDATE app_users SET autopilot=1 WHERE id=%s", (uid,))
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 4}})
    result = {"capital": 20.0, "in_sample": {"trades": 80, "pnl": 9.0}, "out_of_sample": {"trades": 30, "pnl": 3.0}}
    sids = [repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", "Kept %s %d" % (label, i), "t", spec,
                                 "passed", result) for i in range(4)]
    deps = []
    for i, mode in enumerate(("paper", "paper", "demo", "live", "paper")):
        deps.append((repo.create_deployment(cur, uid, sids[i % 3], "btc15m", mode), mode))
    cur.execute("UPDATE app_deployments SET status='stopped' WHERE id=%s", (deps[4][0],))
    rows = []
    for i in range(n_trades):
        did, mode = rng.choice(deps)
        ref = ("sim:%s-%d" % (label, i)) if mode == "paper" else "%s:%s-%d" % (mode, label, i)
        opened = NOW - timedelta(days=80) + timedelta(minutes=rng.randint(0, 80 * 1440 - 60))
        for k in range(rng.choice([1, 1, 2])):
            qty, price = rng.randint(1, 9), round(rng.uniform(0.05, 0.9), 2)
            exit_price = rng.choice([0.0, 1.0])
            rows.append((did, uid, mode, "KXBTC15M-26OCT%04d-T%d" % (i % 400, 90 + k), "yes", qty, price, 0.07,
                         opened + timedelta(hours=1), opened, "closed", exit_price, 0.07,
                         round(qty * (exit_price - price) - 0.14, 4), ref, opened + timedelta(minutes=rng.randint(1, 50))))
    cur.executemany(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
             market_close_time, opened_at, status, exit_price, exit_fee, pnl, order_ref, closed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
    for did, mode in deps[:3]:
        repo.insert_position(cur, did, uid, mode, "KXBTC15M-26OCT2612-T98", "yes", 4, 0.4, 0.07, NOW + timedelta(hours=1),
                             order_ref="%s:open-%d" % ("sim" if mode == "paper" else mode, did))
    return uid, sids, deps


def _pages(counting, uid, sids):
    """{page: its JSON} for the pages that keep reads, and the statements they sent."""
    from app import repository as repo
    from app import server

    user = repo.get_user(counting.conn.cursor(), uid)
    handler = SimpleNamespace(cookies=lambda: {}, headers={}, client_address=("127.0.0.1", 0))
    out, sent = {}, {}
    since = str(int(NOW.replace(tzinfo=timezone.utc).timestamp()) - 3 * 86400)
    for name, params, query in [("dashboard", (), {"since": since}), ("dashboard", (), {}), ("autopilot_status", (), {}),
                                ("list_deployments", (), {}), ("list_strategies", (), {"deployed": "1"}),
                                ("get_strategy", (str(sids[0]),), {}), ("get_track_record", (), {})]:
        # The pages' own minute caches (track record, backtest comparison, road to live) are emptied:
        # only book_memo's kept reads carry over between requests here.
        for cache in (server._TRACK_RECORD, server._BACKTEST_CHECKS, server._ROADS, server._FAILING):
            cache.clear()
        counting.log = []
        res = getattr(server, name)(server.Ctx(counting, user, params, dict(query), {}, handler))
        key = "%s %s %s" % (name, params, sorted(query.items()))
        out[key] = json.dumps(_steady(res), default=server._json_default, sort_keys=True)
        sent[key] = list(counting.log)
    return out, sent


def _steady(v):
    """The payload without the data-feed and engine ages (seconds since a heartbeat, off the wall clock)."""
    if isinstance(v, dict):
        return {k: _steady(x) for k, x in v.items() if k not in ("freshness", "heartbeat_age")}
    if isinstance(v, list):
        return [_steady(x) for x in v]
    return v


def _fresh(counting, uid, sids):
    from app.services import book_memo

    book_memo.clear()
    return _pages(counting, uid, sids)


def test_kept_position_sums_are_used_while_the_book_is_unchanged_and_never_stale_after_a_write(conn, frozen):
    from app import repository as repo
    from app.services import book_memo

    rng = random.Random(20261026)
    uid, sids, deps = _book(conn, rng, "kept", 900)
    _book(conn, rng, "beside", 200)
    counting = Counting(conn)
    cur = conn.cursor()

    fresh, fresh_sent = _fresh(counting, uid, sids)  # nothing kept: every page reads in full, and keeps
    kept, kept_sent = _pages(counting, uid, sids)
    assert kept == fresh
    for page, log in kept_sent.items():
        if not page.startswith("get_strategy"):  # the strategy page sums only its own deployments, directly
            assert not [s for s in log if any(h in s for h in HEAVY)], page
        assert len(log) <= len(fresh_sent[page]), page
    assert sum(map(len, kept_sent.values())) < sum(map(len, fresh_sent.values()))

    paper = [d for d, m in deps if m == "paper"]
    cur.execute("SELECT * FROM app_positions WHERE deployment_id=%s AND status='open'", (paper[0],))
    held = cur.fetchone()
    writes = [
        ("a position opens", lambda: repo.insert_position(cur, paper[1], uid, "paper", "KXBTC15M-26OCT2613-T99", "yes", 3,
                                                          0.3, 0.05, NOW + timedelta(hours=2), order_ref="sim:new")),
        ("it closes", lambda: repo.close_position(cur, _open_id(cur, uid, "sim:new"), 1.0, 0.05, 2.0, "settled")),
        ("a position sells in part", lambda: repo.book_partial_exit(cur, held, 1, 0.6, 0.02, 0.18, "take_profit")),
        ("a paper trade is replayed into the past",
         lambda: repo.insert_closed_position(cur, paper[0], uid, "paper", "KXBTC15M-26SEP0112-T95", "yes", 2, 0.5, 0.05, 1.0,
                                             0.05, 0.9, "settled", NOW - timedelta(days=50), order_ref="sim:replayed",
                                             opened_at=NOW - timedelta(days=50, minutes=30), closed_at=NOW - timedelta(days=50))),
        # The stopped one moves between two running strategies: the panel lists the same strategies,
        # and only the deployments behind them changed.
        ("a stopped deployment is re-pointed", lambda: repo.set_deployment_strategy(cur, uid, paper[2], sids[0])),
        ("a deployment is re-pointed at an adjusted strategy", lambda: repo.set_deployment_strategy(cur, uid, paper[1], sids[3])),
        ("a deployment stops", lambda: repo.set_deployment_status(cur, uid, paper[1], "stopped", "By you")),
        ("a strategy is deployed", lambda: repo.create_deployment(cur, uid, sids[2], "btc15m", "paper")),
    ]
    for what, write in writes:
        write()
        kept, _ = _pages(counting, uid, sids)  # the reads kept before the write are still there
        fresh, _ = _fresh(counting, uid, sids)
        for page in fresh:
            assert kept[page] == fresh[page], "%s: %s served a kept read" % (what, page)
        _pages(counting, uid, sids)  # keep again for the next write


def _open_id(cur, uid, ref):
    cur.execute("SELECT id FROM app_positions WHERE user_id=%s AND order_ref=%s AND status='open'", (uid, ref))
    return cur.fetchone()["id"]


def test_kept_reads_answer_as_the_repository_does(conn, frozen):
    """Each kept read is the repository read it stands for, with the same values and types."""
    from app import repository as repo
    from app.services import book_memo

    rng = random.Random(7)
    uid, sids, deps = _book(conn, rng, "same", 400)
    cur = conn.cursor()
    ids = [d for d, _ in deps]
    for _ in range(2):  # the read that keeps, then the kept answer
        memo = book_memo.BookMemo(cur, uid)
        day = NOW.replace(hour=0)
        assert book_memo.closed_book_totals(memo, day, NOW - timedelta(days=2)) == repo.closed_book_totals(
            cur, uid, day, NOW - timedelta(days=2))
        assert book_memo.closed_book_totals(memo, day, NOW - timedelta(days=2), split=True) == repo.closed_book_totals(
            cur, uid, day, NOW - timedelta(days=2), split=True)
        assert book_memo.deployment_curves(memo, ids) == repo.deployment_curves(cur, uid, deployment_ids=ids)
        assert book_memo.deployments_for_display(memo) == repo.list_deployments_for_display(cur, uid)
        assert book_memo.deployments_for_display(memo, sids[0]) == repo.list_deployments_for_display(cur, uid, strategy_id=sids[0])
        assert book_memo.daily_pnl(memo, "paper") == repo.daily_pnl(cur, uid, "paper")
        assert book_memo.paper_readouts(memo, sids) == (repo.paper_progress(cur, uid, sids), repo.paper_event_counts(cur, uid, sids))
        assert book_memo.paper_round_trips_by_strategy(memo, sids) == repo.paper_round_trips_by_strategy(cur, uid, sids)
        assert book_memo.book_trade_stats(memo, sids) == repo.book_trade_stats(cur, uid, sids)
        assert book_memo.track_record(cur, uid) == __import__("app.trading.track_record", fromlist=["build"]).build(
            repo.track_record_rows(cur, uid))
    assert book_memo._KEPT
