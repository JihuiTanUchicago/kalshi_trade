"""The autopilot panel (/api/autopilot/status, polled every 20s on every signed-in page) reads its small
figures in one statement (repo.autopilot_pulse) and its credit figures in another (repo.credit_week),
keeps its position sums against the positions' version (services.book_memo) and its last move against
the chat's version. Against a real MySQL; opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).

- Each merged read answers exactly as the reads it replaced (tests/autopilot_status_parts.py), for a
  busy account, the account beside it and an empty one.
- On an account with every kind of row, after each real write that moves a figure the panel shows
  (a trade closing or opening in each book, a move posted, a review or session queued, a debit or a
  top-up, a strategy passing, ideas tried, a Kalshi key saved, a deployment paused or re-pointed, the
  engine beating), the next poll shows the new figure, says what the single reads say, and its whole
  answer equals the one it gives with nothing kept. While nothing moved, the kept reads are used.
"""
import json
import os
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

NOW = datetime(2026, 10, 26, 12, 0, 0)
DAY = NOW.replace(hour=0)
# Reads the panel keeps: none may run on a poll while nothing they read changed.
KEPT = ("SELECT t.strategy_id, COUNT(*) AS trips", "COUNT(DISTINCT SUBSTRING(p.ticker", "SELECT mode, COALESCE(SUM(pnl),0)",
        "AND status='open' AND mode=%s", "AND status='closed' GROUP BY deployment_id", "FROM app_chat_messages WHERE user_id=%s ORDER BY id DESC")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    # The engine's beat is one row for the whole database: put back what was there, so a later test (or
    # the next run against the same database) doesn't find a beat this module left and see every page's
    # data ages tick with the database clock between two reads it compares.
    cur = c.cursor()
    cur.execute("SELECT state_value, updated_at_utc FROM collector_state WHERE state_key='recursive_engine_last_tick'")
    beat = cur.fetchone()
    yield c
    cur = c.cursor()
    cur.execute("UPDATE app_deployments SET status='stopped' WHERE user_id IN "
                "(SELECT id FROM app_users WHERE google_sub LIKE 'test:%%')")
    if beat is None:
        cur.execute("DELETE FROM collector_state WHERE state_key='recursive_engine_last_tick'")
    else:
        cur.execute("UPDATE collector_state SET state_value=%s, updated_at_utc=%s WHERE state_key='recursive_engine_last_tick'",
                    (beat["state_value"], beat["updated_at_utc"]))
    c.close()


@pytest.fixture
def frozen(monkeypatch):
    """One clock for every read (the kept and the fresh answers are compared byte for byte), payments on
    and live trading available, so the panel reads the card, the balance and the key."""
    import sys

    from app.adapters.db import sql
    from app.adapters.stripe import billing
    from app.research import rsi
    from app.services import book_memo
    from app.trading import engine
    from app.web.routes import chat

    real = sql.now_utc
    for m in list(sys.modules.values()):
        if m is not None and getattr(m, "now_utc", None) is real:
            monkeypatch.setattr(m, "now_utc", lambda: NOW)
    for name in ("paper_pace", "paper_trade_rate"):  # the paper pace reads the wall clock
        fn = getattr(rsi, name)
        monkeypatch.setattr(rsi, name, lambda dep, trips, now=None, _fn=fn: _fn(dep, trips, now or NOW))
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_status")
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)
    book_memo.clear()
    chat._LAST_ACTION.clear()
    yield
    book_memo.clear()
    chat._LAST_ACTION.clear()


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


def _account(conn, label, busy=True):
    """An autopilot account with research of every kind this week and before, passed strategies, paper,
    demo and live deployments (one paper one paused today), closed and open trades in each book, debits
    of every source, a top-up, a card and chat lines. `busy=False` is the account alone."""
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, label + "@example.invalid", label, None)["id"]
    cur.execute("UPDATE app_users SET autopilot=1, autopilot_live=1 WHERE id=%s", (uid,))
    ids = {"uid": uid}
    if not busy:
        return ids
    repo.save_stripe_customer(cur, uid, "cus_" + uuid.uuid4().hex[:12])
    repo.set_default_pm(cur, uid, "pm_status")
    repo.set_auto_reload(cur, uid, False)

    def run(kind, market=None, direction=None, status="succeeded", ago=timedelta(hours=3), tried=0, brief=False):
        rid = repo.create_run(cur, uid, kind, market=market, direction=direction, brief=brief)
        at = NOW - ago
        cur.execute("UPDATE app_agent_runs SET status=%s, created_at=%s, started_at=%s, heartbeat_at=%s, "
                    "hypotheses_tried=%s WHERE id=%s", (status, at, at, NOW - timedelta(seconds=30), tried, rid))
        return rid

    ids["old"] = run("research", "btc15m", ago=timedelta(days=9), tried=50)
    ids["week"] = run("research", "eth15m", ago=timedelta(days=2), tried=12)
    ids["auto"] = run("research", "btc15m", ago=timedelta(days=1), tried=7, brief=True)
    ids["example"] = run("research", None, direction=repo.DEMO_DIRECTION, ago=timedelta(days=1), tried=3)
    ids["live"] = run("research", "btc15m", status="running", ago=timedelta(minutes=20), tried=4)
    ids["paused_run"] = run("research", "eth15m", status="paused", ago=timedelta(minutes=50), tried=2)
    ids["review"] = run("review", ago=timedelta(minutes=40))
    ids["chat"] = run("chat", ago=timedelta(minutes=30))

    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 4}})
    result = {"capital": 20.0, "in_sample": {"trades": 80, "pnl": 9.0, "trades_per_day": 2.0},
              "out_of_sample": {"trades": 30, "pnl": 3.0}}
    ids["sids"] = [repo.insert_strategy(cur, uid, ids["week" if i < 4 else "old"], None, "btc15m", "momentum",
                                        "Panel %s %d" % (label, i), "t", spec, "passed", result) for i in range(5)]
    s = ids["sids"]
    deps = ids["deps"] = {
        "paper": repo.create_deployment(cur, uid, s[0], "btc15m", "paper"),
        "paper2": repo.create_deployment(cur, uid, s[1], "btc15m", "paper"),
        "paused": repo.create_deployment(cur, uid, s[2], "btc15m", "paper"),
        "demo": repo.create_deployment(cur, uid, s[0], "btc15m", "demo"),
        "live": repo.create_deployment(cur, uid, s[3], "btc15m", "live"),
    }
    cur.execute("UPDATE app_deployments SET created_at=%s WHERE user_id=%s", (NOW - timedelta(days=3), uid))
    rows = []
    for i in range(60):
        dep, mode = [(deps["paper"], "paper"), (deps["paper2"], "paper"), (deps["paused"], "paper"),
                     (deps["demo"], "demo"), (deps["live"], "live")][i % 5]
        closed = NOW - timedelta(hours=5 * i + 1)  # today's and older
        ref = ("sim:%s-%d" % (label, i)) if mode == "paper" else "%s:%s-%d" % (mode, label, i)
        pnl = round((-1) ** i * (0.4 + i / 100), 4)
        rows.append((dep, uid, mode, "KXBTC15M-26OCT%04d-T9%d" % (i, i % 10), "yes", 3, 0.4, 0.05,
                     closed, closed - timedelta(minutes=30), "closed", 1.0 if pnl > 0 else 0.0, 0.05, pnl, ref, closed,
                     "stop_loss" if i % 7 == 0 else "settled"))
    cur.executemany(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
             market_close_time, opened_at, status, exit_price, exit_fee, pnl, order_ref, closed_at, close_reason)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
    ids["open"] = repo.insert_position(cur, deps["paper"], uid, "paper", "KXBTC15M-26OCT2612-T98", "yes", 4, 0.4, 0.07,
                                       NOW + timedelta(hours=1), order_ref="sim:open-%s" % label)
    repo.set_deployment_status(cur, uid, deps["paused"], "paused", "Loss guard: lost $6.00")
    repo.add_credit(cur, uid, "bonus", 20, "Welcome credit")
    for rid, usd in ((ids["week"], 0.31), (ids["auto"], 0.17), (ids["review"], 0.11), (ids["chat"], 0.07),
                     (ids["example"], 0.05), (None, 0.02), (ids["old"], 1.0)):
        repo.add_credit(cur, uid, "usage", -usd, "Model usage", run_id=rid)
    cur.execute("UPDATE app_credit_ledger SET created_at=%s WHERE user_id=%s AND run_id=%s", (NOW - timedelta(days=9), uid, ids["old"]))
    repo.add_chat(cur, uid, "system", "Autopilot switched on.")
    repo.add_chat(cur, uid, "user", "How is it going?")
    repo.add_chat(cur, uid, "agent", "Two strategies are on paper.")
    return ids


def _engine_beats(cur):
    """The engine's beat, now by the database's clock (the panel measures its age against that clock)."""
    cur.execute("""INSERT INTO collector_state (state_key, state_value, updated_at_utc)
                   VALUES ('recursive_engine_last_tick', '{"live": false}', UTC_TIMESTAMP())
                   ON DUPLICATE KEY UPDATE updated_at_utc=UTC_TIMESTAMP()""")


def test_the_merged_reads_answer_as_the_reads_they_replace(conn, frozen):
    from app import repository as repo
    from tests.autopilot_status_parts import credit_reference, pulse_reference

    cur = conn.cursor()
    _engine_beats(cur)
    since = NOW - timedelta(days=7)
    for ids in (_account(conn, "merged"), _account(conn, "beside"), _account(conn, "alone", busy=False)):
        uid = ids["uid"]
        for review in (False, True):
            for engine in (False, True):
                got = repo.autopilot_pulse(cur, uid, since, review=review, engine=engine)
                ref = pulse_reference(cur, uid, since, review=review, engine=engine)
                if engine:  # seconds since the beat, off the database's wall clock: the two reads may straddle one
                    assert abs(got.pop("engine_age") - ref.pop("engine_age")) <= 1
                assert got == ref, (uid, review, engine)
                assert all(type(got[k]) is int for k in ("runs_7d", "tested_7d", "passed_7d"))
        for balance in (False, True):
            got, ref = repo.credit_week(cur, uid, since, balance=balance), credit_reference(cur, uid, since, balance=balance)
            assert got == ref and all(type(v) is float for v in got["by_source"].values()), (uid, balance)
    # Whether it has ever researched: a new account's seeded example doesn't count; an old session past the week does.
    alone = _account(conn, "fresh", busy=False)["uid"]
    assert repo.autopilot_pulse(cur, alone, since)["researched"] is False
    old = repo.create_run(cur, alone, "research", market="btc15m")
    cur.execute("UPDATE app_agent_runs SET status='succeeded', created_at=%s WHERE id=%s", (NOW - timedelta(days=30), old))
    assert repo.autopilot_pulse(cur, alone, since)["researched"] is True
    busy = _account(conn, "shape")
    got = repo.autopilot_pulse(cur, busy["uid"], since, review=True)
    assert [r["id"] for r in got["research_live"]] == [busy["live"]]  # the paused session isn't in flight
    assert got["passed_7d"] == 4 and got["tested_7d"] == 12 + 7 + 4 + 2  # the example and last week's left out
    week = repo.credit_week(cur, busy["uid"], since, balance=True)
    assert week["research"] == 0.48 and week["by_source"]["autopilot_review"] == 0.11
    # Welcome credits only: no card charge yet, so the page calls the spend free credits, not real money.
    assert week["card_charged"] is False and repo.credit_week(cur, busy["uid"], since)["card_charged"] is None
    repo.add_credit(cur, busy["uid"], "autoreload", 20, "Auto-reload")
    assert repo.credit_week(cur, busy["uid"], since, balance=True)["card_charged"] is True
    # "Last check-in" is when the newest review ran: one queued 40 minutes ago that a busy worker only
    # started 2 minutes ago reads 2 minutes; a newer one still queued stands in with its queued time.
    late = repo.create_run(cur, busy["uid"], "review")
    cur.execute("UPDATE app_agent_runs SET created_at=%s, started_at=%s WHERE id=%s",
                (NOW - timedelta(minutes=40), NOW - timedelta(minutes=2), late))
    for read in (lambda: repo.autopilot_pulse(cur, busy["uid"], since)["last_review_at"],
                 lambda: repo.last_review_at(cur, busy["uid"])):
        assert read() == NOW - timedelta(minutes=2)
    queued = repo.create_run(cur, busy["uid"], "review")
    cur.execute("UPDATE app_agent_runs SET created_at=%s WHERE id=%s", (NOW - timedelta(minutes=1), queued))
    assert repo.autopilot_pulse(cur, busy["uid"], since)["last_review_at"] == NOW - timedelta(minutes=1)
    assert repo.last_review_at(cur, busy["uid"]) == NOW - timedelta(minutes=1)


def _status(counting, uid):
    from app import repository as repo
    from app import server

    counting.log = []
    user = repo.get_user(counting.conn.cursor(), uid)
    out = server.autopilot_status(server.Ctx(counting, user, (), {}, {}, SimpleNamespace()))
    return json.loads(json.dumps(out, default=server._json_default, sort_keys=True)), list(counting.log)


def _fresh(counting, uid):
    from app.services import book_memo
    from app.web.routes import chat

    book_memo.clear()
    chat._LAST_ACTION.clear()
    return _status(counting, uid)


def _single_reads(cur, uid):
    """The panel's figures as the single reads it used to make say them."""
    from app import repository as repo
    from app.web.views import credit_usd

    since = NOW - timedelta(days=7)
    from app import server

    from app.web.routes import chat

    # The single read, said as the panel says it (the engine's pause by name; chat._last_move).
    act = chat._last_move(repo.last_autopilot_action(cur, uid), repo.list_deployments_brief(cur, uid))
    act = json.loads(json.dumps(act, default=server._json_default))
    return {
        "today_live_pnl": round(repo.realized_pnl(cur, uid, "live", DAY), 2),
        "today_paper_pnl": round(repo.realized_pnl(cur, uid, "paper", DAY), 2),
        "paper_open": int(repo.user_open_exposure(cur, uid, "paper")["n"]),
        "last_action": act,
        "kalshi_connected": repo.get_kalshi_key(cur, uid) is not None,
        "reviewing": repo.active_agent_run(cur, uid, "review") is not None,
        "tested_7d": sum(int(r["tried"]) for r in repo.research_week(cur, uid, since)),
        "passed_7d": repo.strategies_passed_since(cur, uid, since),
        "cost_7d": credit_usd(repo.research_spent_since(cur, uid, since)),
        "checkin_credits": credit_usd(repo.usage_by_source(cur, uid, since)["autopilot_review"]),
        "credits_left": credit_usd(repo.credit_balance(cur, uid)),
    }


def _shown(out):
    return {"today_live_pnl": out["today_live_pnl"], "today_paper_pnl": out["today_paper_pnl"], "paper_open": out["paper_open"],
            "last_action": out["last_action"], "kalshi_connected": out["kalshi_connected"], "reviewing": out["reviewing"],
            "tested_7d": out["research"]["tested_7d"], "passed_7d": out["research"]["passed_7d"],
            "cost_7d": out["research"]["cost_7d"], "checkin_credits": out["week"]["checkin_credits"],
            "credits_left": out["week"]["credits_left"]}


def test_every_figure_the_panel_shows_moves_on_the_next_poll_and_a_kept_answer_is_a_fresh_one(conn, frozen):
    from app import repository as repo
    from app.adapters.stripe import billing as billing_mod
    from app.trading.markets import MARKETS

    ids = _account(conn, "moves")
    _account(conn, "next door")
    uid, deps, sids = ids["uid"], ids["deps"], ids["sids"]
    counting = Counting(conn)
    cur = conn.cursor()
    _engine_beats(cur)

    cold, cold_sent = _fresh(counting, uid)
    warm, warm_sent = _status(counting, uid)
    assert warm == cold and len(warm_sent) < len(cold_sent)
    assert not [s for s in warm_sent if any(k in s for k in KEPT)], "a kept read ran while nothing moved"
    assert sum("AS pos_n" in s for s in warm_sent) == 1 and sum("SELECT 'usage' AS part" in s for s in warm_sent) == 1
    assert _shown(warm) == _single_reads(cur, uid)
    assert warm["paused_recent"] and warm["paused_recent"][0]["deployment_id"] == deps["paused"]

    def moved(key, by=None, to=None, at=None):
        """A check that `key` (a dotted path) moved by `by` or to `to`."""
        def get(o):
            for k in key.split("."):
                o = o[k]
            return o

        def check(before, after):
            if to is not None:
                return get(after) == to
            return round(get(after) - get(before), 2) == round(by, 2)
        return check

    def closes_today():
        repo.close_position(cur, ids["open"], 1.0, 0.05, 1.25, "settled")

    def live_trade():
        repo.insert_closed_position(cur, deps["live"], uid, "live", "KXBTC15M-26OCT2611-T97", "yes", 5, 0.6, 0.07, 0.0,
                                    0.0, -3.07, "settled", NOW, order_ref="live:moves-loss", opened_at=NOW - timedelta(hours=1),
                                    closed_at=NOW - timedelta(minutes=5))

    writes = [
        ("a paper trade closes today", closes_today, moved("today_paper_pnl", by=1.25)),
        ("a paper position opens", lambda: repo.insert_position(cur, deps["paper2"], uid, "paper", "KXBTC15M-26OCT2613-T99",
                                                                "yes", 2, 0.3, 0.05, NOW + timedelta(hours=2), order_ref="sim:moves-new"),
         moved("paper_open", by=1)),
        ("a live trade loses today", live_trade, moved("today_live_pnl", by=-3.07)),
        ("the autopilot posts a move", lambda: repo.add_chat(cur, uid, "system", "Autopilot paused Rain: it hit its loss guard."),
         moved("last_action.text", to="Autopilot paused Rain: it hit its loss guard.")),
        ("a chat line that is not a move", lambda: repo.add_chat(cur, uid, "user", "Thanks"),
         moved("last_action.text", to="Autopilot paused Rain: it hit its loss guard.")),
        # The engine's own pause is the newest move, said by the strategy's name, not "#<id>".
        ("the engine pauses a deployment", lambda: repo.add_chat(
            cur, uid, "system", "Paused deployment #%d automatically. Lost $6.00, more than the $5.00 guard (2x its worst "
                                "backtest drawdown)." % deps["paper2"]),
         moved("last_action.text", to="Paused your paper strategy Panel moves 1 automatically: it lost $6.00, more than "
                                      "its $5.00 loss guard.")),
        ("a review is queued", lambda: repo.create_run(cur, uid, "review"), moved("reviewing", to=True)),
        ("a research session is queued", lambda: repo.create_run(cur, uid, "research", market="eth15m", brief=True),
         lambda b, a: MARKETS["eth15m"].label in a["research"]["active"] and len(a["research"]["active"]) == len(b["research"]["active"]) + 1),
        ("research is billed", lambda: repo.add_credit(cur, uid, "usage", -0.5, "Model usage", run_id=ids["week"]),
         moved("research.cost_7d", by=0.5)),
        ("a check-in is billed", lambda: repo.add_credit(cur, uid, "usage", -0.2, "Model usage", run_id=ids["review"]),
         moved("week.checkin_credits", by=0.2)),
        ("credits are added", lambda: repo.add_credit(cur, uid, "topup", 25, "Card top-up"),
         lambda b, a: moved("week.credits_left", by=25)(b, a) and (b["week"]["card_charged"], a["week"]["card_charged"]) == (False, True)),
        ("a strategy passes", lambda: repo.insert_strategy(cur, uid, ids["week"], None, "btc15m", "momentum", "Late pass", "t",
                                                           {"side": "yes"}, "passed", None), moved("research.passed_7d", by=1)),
        ("research tries more ideas", lambda: repo.set_run_counts(cur, ids["live"], 13, 0), moved("research.tested_7d", by=9)),
        ("a Kalshi key is saved", lambda: repo.save_kalshi_key(cur, uid, "key-moves", b"sealed"), moved("mode", to="live")),
        ("a paper deployment pauses", lambda: repo.set_deployment_status(cur, uid, deps["paper2"], "paused", "By you"),
         lambda b, a: deps["paper2"] in [p["deployment_id"] for p in a["paused_recent"]] and a["paper_running"] == b["paper_running"] - 1),
        ("a deployment is re-pointed at another strategy", lambda: repo.set_deployment_strategy(cur, uid, deps["paper"], sids[4]),
         moved("paper_progress.strategy_id", to=sids[4])),
        ("the engine goes quiet", lambda: cur.execute(
            "UPDATE collector_state SET updated_at_utc=UTC_TIMESTAMP() - INTERVAL 2 HOUR WHERE state_key='recursive_engine_last_tick'"),
         moved("idle.code", to="engine")),
    ]
    before = warm
    for what, write, check in writes:
        write()
        kept, kept_sent = _status(counting, uid)  # the reads kept before the write are still there
        fresh, _ = _fresh(counting, uid)
        assert kept == fresh, "%s: the panel served a kept read" % what
        assert check(before, kept), "%s: the panel did not move" % what
        shown = _shown(kept)
        assert shown == _single_reads(cur, uid), what
        for p in kept["paused_recent"]:
            n, pnl = repo.deployment_closed_totals(cur, [p["deployment_id"]]).get(p["deployment_id"], (0, 0))
            assert (p["trades"], p["pnl"]) == (n, round(float(pnl), 2)), what
        progress = repo.paper_progress(cur, uid, sorted({d["strategy_id"] for d in repo.list_deployments(cur, uid)
                                                         if d["mode"] == "paper" and d["status"] == "running"}))
        if kept["paper_progress"]:
            trades, net = progress.get(kept["paper_progress"]["strategy_id"], (0, 0.0))
            assert (kept["paper_progress"]["trades"], kept["paper_progress"]["net_pnl"]) == (trades, round(net, 2)), what
        assert len(kept_sent) <= len(_fresh(counting, uid)[1]), what
        _status(counting, uid)  # keep again for the next write
        before = kept
    assert billing_mod.configured()
