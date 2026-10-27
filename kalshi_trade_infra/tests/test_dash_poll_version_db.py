"""The dashboard's and the Deploy board's "unchanged" answers against a real MySQL (services.page_poll).

Both pages poll (/api/dashboard every 15s, /api/deployments every 10s) and send back the version of their
last full answer. These pages show money: paper, demo and live P&L, balances, open positions. So after
every kind of write that moves a figure on a page (a position opened, closed or sold in part, a deployment
paused, paper cash deposited or reset, credits spent, a strategy passing, a live mismatch flagged, demo
capital reloaded, a balance read from Kalshi, an early exit scored) the page's version must move, and the
full answer must be the one a fresh poll gets with nothing kept. A mark the engine stamps (every tick)
does not move the version: the "same" answer carries the marks, and the kept answer with them put back
(as the page does, pollAnswer) must again be what a fresh poll gets. So must the next UTC day, whose
"today" figures restart. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

NOW = datetime(2026, 10, 26, 12, 0, 0)
CLOCK = [NOW]
LIVE_CASH, DEMO_CASH = [250.0], [100.0]
READ_AT, KEPT = [NOW], [True]
SAME_KEYS = {"v", "same", "marks", "unrealized", "freshness", "since_at"}
HEAVY = ("SUM(pnl) OVER (PARTITION BY deployment_id", "LEFT JOIN (SELECT p.deployment_id", "AS paper_all",
         "GROUP BY DATE(closed_at)", "SUM(amount)")


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
def world(monkeypatch):
    """One movable clock for every read, payments on (the strip shows credits), and the Kalshi live and
    demo balances as figures the test sets (never a network call)."""
    import sys

    from app.adapters.db import sql
    from app.adapters.kalshi import kalshi_account
    from app.adapters.stripe import billing
    from app.research import rsi
    from app.services import book_memo
    from app.trading import demo_twins, engine

    real = sql.now_utc
    for m in list(sys.modules.values()):
        if m is not None and getattr(m, "now_utc", None) is real:
            monkeypatch.setattr(m, "now_utc", lambda: CLOCK[0])
    for name in ("paper_pace", "paper_trade_rate"):  # the paper pace reads the wall clock
        fn = getattr(rsi, name)
        monkeypatch.setattr(rsi, name, lambda dep, trips, now=None, _fn=fn: _fn(dep, trips, now or CLOCK[0]))
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_poll")
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(kalshi_account, "credentials_from_row", lambda uid, row: ("key", None))
    monkeypatch.setattr(kalshi_account, "balance_cached", lambda uid, creds, ttl=0: LIVE_CASH[0])
    monkeypatch.setattr(kalshi_account, "balance_read_at", lambda uid: NOW)
    monkeypatch.setattr(demo_twins, "balance_cached", lambda cur, uid, ttl=0: DEMO_CASH[0])
    # The dashboard's poll never asks Kalshi: it reads each cash memo (what the page's follow-up last read, and
    # when), kept or not (KEPT): the figures the test sets, read at READ_AT.
    monkeypatch.setattr(kalshi_account, "memo_peek", lambda cache, uid: (
        DEMO_CASH[0] if cache is demo_twins._BALANCE_CACHE else LIVE_CASH[0], READ_AT[0]))
    monkeypatch.setattr(kalshi_account, "balance_kept", lambda uid: KEPT[0])
    monkeypatch.setattr(demo_twins, "balance_kept", lambda uid: KEPT[0])
    CLOCK[0], LIVE_CASH[0], DEMO_CASH[0], READ_AT[0], KEPT[0] = NOW, 250.0, 100.0, NOW, True
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


def _book(conn):
    """A user with paper, demo and live deployments, closed and open trades in each, paper cash, both
    Kalshi keys and a demo stake; and a second user whose writes must never move the first one's pages."""
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "poll@example.invalid", "Poll", None)["id"]
    cur.execute("UPDATE app_users SET autopilot=1 WHERE id=%s", (uid,))
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 4}})
    result = {"capital": 20.0, "in_sample": {"trades": 80, "pnl": 9.0, "trades_per_day": 3.0},
              "out_of_sample": {"trades": 30, "pnl": 3.0}}
    sids = [repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", "Poll %d" % i, "t", spec, "passed", result)
            for i in range(3)]
    deps = {mode: repo.create_deployment(cur, uid, sids[i], "btc15m", mode) for i, mode in enumerate(("paper", "demo", "live"))}
    repo.add_ledger(cur, uid, "deposit", 1000.0, "Paper account opened")
    rows = []
    for i in range(60):
        mode = ("paper", "paper", "demo", "live")[i % 4]
        opened = NOW - timedelta(days=20) + timedelta(hours=7 * i)
        rows.append((deps[mode], uid, mode, "KXBTC15M-26OCT%04d-T9%d" % (i, i % 9), "yes", 2, 0.4, 0.07,
                     opened + timedelta(hours=1), opened, "closed", 1.0 if i % 3 else 0.0, 0.07,
                     round(2 * ((1.0 if i % 3 else 0.0) - 0.4) - 0.14, 4), "stop" if i % 5 == 0 else "settled",
                     "%s:%d" % ("sim" if mode == "paper" else mode, i), opened + timedelta(minutes=30)))
    cur.executemany(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
             market_close_time, opened_at, status, exit_price, exit_fee, pnl, close_reason, order_ref, closed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
    opens = {mode: repo.insert_position(cur, did, uid, mode, "KXBTC15M-26OCT2612-T98", "yes", 4, 0.4, 0.07,
                                        NOW + timedelta(hours=1), order_ref="%s:open" % ("sim" if mode == "paper" else mode))
             for mode, did in deps.items()}
    repo.update_marks(cur, "btc15m", {"KXBTC15M-26OCT2612-T98": (0.45, 0.47)}, NOW)
    repo.save_kalshi_key(cur, uid, "live-key", b"enc")
    repo.set_kalshi_dev_key(cur, uid, "demo-key", b"enc")
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "other@example.invalid", "Other", None)["id"]
    osid = repo.insert_strategy(cur, other, None, None, "btc15m", "momentum", "Theirs", "t", spec, "passed", result)
    odep = repo.create_deployment(cur, other, osid, "btc15m", "paper")
    conn.commit()
    return uid, sids, deps, opens, other, odep


def _poll(counting, uid, page, query):
    """One request with the pages' own minute caches emptied (only kept reads carry over): its answer
    and the statements it sent."""
    from app import repository as repo
    from app import server

    for cache in (server._TRACK_RECORD, server._BACKTEST_CHECKS, server._ROADS, server._FAILING):
        cache.clear()
    user = repo.get_user(counting.conn.cursor(), uid)
    counting.log = []
    out = getattr(server, page)(server.Ctx(counting, user, (), dict(query), {}, SimpleNamespace()))
    counting.conn.commit()
    return out, list(counting.log)


def _fresh(counting, uid, page, query):
    """The answer with nothing kept; the polls' kept reads are put back after it."""
    from app.services import book_memo

    saved = dict(book_memo._KEPT), dict(book_memo._LEDGER)
    book_memo.clear()
    try:
        return _poll(counting, uid, page, query)[0]
    finally:
        book_memo.clear()
        book_memo._KEPT.update(saved[0])
        book_memo._LEDGER.update(saved[1])


def _drawn(kept, same):
    """What the page draws from a "same" answer: the kept answer with the marks, each deployment's
    unrealized P&L, the data ages and the since-visit start put back (pollAnswer in both bundles)."""
    marks, unreal = same.get("marks") or {}, same.get("unrealized") or {}
    d = dict(kept, open_positions=[dict(p, **marks.get(str(p["id"]), {})) for p in kept.get("open_positions") or []],
             deployments=[dict(x, unrealized_pnl=unreal[str(x["id"])]) if str(x["id"]) in unreal else x
                          for x in kept.get("deployments") or []])
    if same.get("freshness"):
        d["freshness"] = same["freshness"]
    if "since_at" in same and kept.get("since"):
        d["since"] = dict(kept["since"], at=same["since_at"])
    return d


def _canon(out):
    """The answer as JSON, less its version and the data ages (seconds off the wall clock)."""
    from app import server

    return json.dumps({k: v for k, v in out.items() if k not in ("v", "freshness")},
                      default=server._json_default, sort_keys=True)


def _visit():
    return str(int((NOW - timedelta(days=3)).replace(tzinfo=timezone.utc).timestamp()))


PAGES = [("dashboard", {"since": _visit()}), ("dashboard", {}), ("list_deployments", {})]


def test_a_polled_money_page_is_same_only_while_every_figure_it_shows_is_unchanged(conn, world):
    from app import repository as repo

    counting = Counting(conn)
    cur = conn.cursor()
    uid, sids, deps, opens, other, odep = _book(conn)
    kept = {}
    for page, query in PAGES:
        first, _ = _poll(counting, uid, page, query)
        assert first["v"] and _canon(first) == _canon(_fresh(counting, uid, page, query)), page
        kept[(page, str(query))] = first

    def check(label, moves):
        """Every page again with its kept version: the pages in `moves` answer in full, a fresh poll's
        answer; the others answer "same", and what the page draws from it is a fresh poll's answer."""
        for page, query in PAGES:
            key = (page, str(query))
            got, sent = _poll(counting, uid, page, dict(query, v=kept[key]["v"]))
            fresh = _fresh(counting, uid, page, query)
            if page in moves:
                assert not got.get("same") and got["v"] != kept[key]["v"], (label, page, query)
                assert _canon(got) == _canon(fresh), (label, page, query)
                kept[key] = got
                got, sent = _poll(counting, uid, page, dict(query, v=got["v"]))
            assert got.get("same") and set(got) <= SAME_KEYS, (label, page, query, sorted(got))
            assert _canon(_drawn(kept[key], got)) == _canon(fresh), (label, page, query)
            # Unchanged: no paper-ledger sum and no full-history position sum ran.
            assert not [s for s in sent if any(h in s for h in HEAVY)], (label, page, [s for s in sent if any(h in s for h in HEAVY)])

    check("nothing written", ())
    both = ("dashboard", "list_deployments")
    writes = [
        # Another account's trades, cash and deployments never move this one's pages.
        ("another user's writes", (), lambda: (repo.insert_position(cur, odep, other, "paper", "KXBTC15M-26OCT2612-T98", "yes",
                                                                    1, 0.3, 0.02, NOW + timedelta(hours=1)),
                                               repo.add_ledger(cur, other, "deposit", 50.0, "Deposit"))),
        # The engine marks every open position each tick: price and time, or the time alone.
        ("mark moved", (), lambda: repo.update_marks(cur, "btc15m", {"KXBTC15M-26OCT2612-T98": (0.52, 0.55)}, NOW + timedelta(seconds=15))),
        ("mark restamped", (), lambda: repo.update_marks(cur, "btc15m", {"KXBTC15M-26OCT2612-T98": (0.52, 0.55)}, NOW + timedelta(seconds=30))),
        ("position opened", both, lambda: repo.insert_position(cur, deps["paper"], uid, "paper", "KXBTC15M-26OCT2613-T97", "yes", 3, 0.35,
                                                               0.05, NOW + timedelta(hours=2), order_ref="sim:new")),
        ("part sold", both, lambda: repo.book_partial_exit(cur, repo.get_position(cur, opens["demo"]), 1, 0.5, 0.01, 0.08, "take_profit")),
        ("position closed", both, lambda: repo.close_position(cur, opens["live"], 0.6, 0.02, 0.73, "take_profit")),
        ("early exit scored", both, lambda: cur.execute(
            "UPDATE app_positions SET settle_result='no', hold_pnl=-0.94 WHERE id=%s", (opens["live"],))),
        ("deployment paused", both, lambda: repo.set_deployment_status(cur, uid, deps["live"], "paused", "By you")),
        ("paper cash deposited", ("dashboard",), lambda: repo.add_ledger(cur, uid, "deposit", 250.0, "Deposit")),
        ("credits spent", ("dashboard",), lambda: repo.add_credit(cur, uid, "usage", -0.37, "Model usage")),
        ("strategy passed", ("dashboard",), lambda: repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", "New pass",
                                                                         "t", {"side": "yes"}, "passed", {})),
        ("live mismatch flagged", ("dashboard",), lambda: repo.upsert_reconcile(cur, uid, "KXBTC15M-26OCT2612-T98", "qty", 3, 4)),
        ("demo capital reloaded", ("dashboard",), lambda: repo.reload_demo(cur, uid, 400.0)),
        ("Kalshi cash read", ("dashboard",), lambda: LIVE_CASH.__setitem__(0, 312.5)),
        # The poll reads the memo alone: once it runs out the cash is pending (the page asks /api/funds/cash),
        # and the follow-up's read, even of the same figure, is a new read time. Each moves the version.
        ("Kalshi cash memo ran out", ("dashboard",), lambda: KEPT.__setitem__(0, False)),
        ("Kalshi cash read again, same figure", ("dashboard",), lambda: (KEPT.__setitem__(0, True),
                                                                          READ_AT.__setitem__(0, NOW + timedelta(seconds=61)))),
        ("demo cash below a stake", both, lambda: DEMO_CASH.__setitem__(0, 1.0)),
        ("paper account reset", both, lambda: (repo.close_position(cur, opens["paper"], 0.5, 0.02, 0.3, "take_profit"),
                                                         repo.reset_paper_account(cur, uid, 1000.0))),
    ]
    for label, moves, write in writes:
        write()
        conn.commit()
        check(label, moves)

    # The next UTC day: "today" restarts (a trade closed today above), with no write at all.
    CLOCK[0] = datetime(2026, 10, 27, 0, 0, 30)
    check("a new UTC day", both)  # the board's paper pace is counted in hours


def test_an_unchanged_dashboard_poll_keeps_the_paper_cash_until_the_ledger_moves(conn, world):
    from app import repository as repo
    from app.services import book_memo

    counting = Counting(conn)
    uid = _book(conn)[0]
    cur = conn.cursor()
    first, sent = _poll(counting, uid, "dashboard", {})
    assert sum("FROM app_ledger" in s and "SUM(amount)" in s for s in sent) == 1
    _, sent = _poll(counting, uid, "dashboard", {"v": first["v"]})
    assert not any("SUM(amount)" in s for s in sent) and sum("FROM app_ledger" in s for s in sent) == 1
    repo.add_ledger(cur, uid, "fill", -1.6, "Paper buy")
    conn.commit()
    got, sent = _poll(counting, uid, "dashboard", {"v": first["v"]})
    assert sum("SUM(amount)" in s for s in sent) == 1 and got["paper"]["cash"] == round(first["paper"]["cash"] - 1.6, 2)
    # An empty ledger is not summed at all, and reads as the sum would.
    empty = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "empty@example.invalid", "E", None)["id"]
    conn.commit()
    assert book_memo.paper_ledger_summary(cur, empty) == repo.paper_ledger_summary(cur, empty)


def test_a_polled_money_page_carries_the_live_switch_and_a_flip_moves_its_version(conn, world, monkeypatch):
    """The server's live switch (/api/me's live_trading_available) rides the dashboard's and the Deploy board's
    answers, in their version: an open page whose switch flipped (a restart with the flag changed) gets a full
    answer on its next poll, so it says a live deployment waits, or no longer does, without a reload or a read
    of /api/me. The flag itself is only stubbed here, for the test."""
    from app.trading import engine

    counting = Counting(conn)
    uid = _book(conn)[0]
    for page, query in PAGES:
        first, _ = _poll(counting, uid, page, query)
        assert first["live_trading_available"] is False
        same, _ = _poll(counting, uid, page, dict(query, v=first["v"]))
        assert same.get("same") is True
        monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)
        flipped, _ = _poll(counting, uid, page, dict(query, v=first["v"]))
        assert not flipped.get("same") and flipped["v"] != first["v"]
        assert flipped["live_trading_available"] is True
        monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", False)
