"""Old rows never 500 a page. Against a real MySQL; opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).

Production rows outlive the code that wrote them: a spec from before `cross` (2026-10-16) or the learned
model (`model.kind`, 2026-10-17), a research row whose result is the research-only block (no gates, no
out_of_sample), a seeded spec with no `model` at all (GET /api/strategies/:id answered 500 on one).
Each stored JSON column a page reads (strategy spec and result, deployment scan, run events, community
snapshots, research-paper experiment and verdict rows, demo refusals and sweeps) is seeded the way its
writer stores it today. Then every key in it, recursively (all items of a list at once), is removed
and, separately, set to null, one at a time; the column is also tried as NULL and as an empty object.
Every page whose statements read that column is called on each. A page may refuse in its own words
(ApiError); it may not raise, and its answer must serialize as the server sends it.
"""
import copy
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qsl

import pymysql
import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

# Left out: read only by the live gate's demo check (services.demo_record, via Road to live). Its writer
# and reader shipped together (#386) with a ticker on every mismatch, so no stored row lacks one, and
# the gate is not loosened to read such a row: an unreadable record refuses live, it never passes.
GATE_ONLY = {("mismatches", "*.ticker")}
MAX_DEPTH = 4  # deep enough for result.gates[*].ok and stats.ci[*]; equity points are leaves
DROP = object()


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


def _offline(*a, **k):
    raise RuntimeError("offline in this test")


@pytest.fixture
def quiet(monkeypatch):
    """Nothing leaves the box and nothing goes live: no AWS or other network, Stripe off, the live engine
    off, no market history (the what-if stops after its stored-spec reads), and a demo key whose balance
    is answered here (so the demo-funds line reads every running stake), never by Kalshi."""
    import socket

    import boto3

    from app import repository as repo
    from app import server
    from app.adapters.stripe import billing
    from app.trading import demo_twins, engine

    connect = socket.create_connection

    def local_only(address, *a, **k):
        assert address[0] in ("127.0.0.1", "localhost", os.getenv("MYSQL_HOST")), "network call to %s" % (address,)
        return connect(address, *a, **k)
    monkeypatch.setattr(socket, "create_connection", local_only)
    monkeypatch.setattr(boto3, "client", _offline)
    monkeypatch.setattr(boto3, "resource", _offline)
    monkeypatch.setattr(server.backtest, "dataset", _offline)
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(server, "_freshness", lambda c: {})
    monkeypatch.setattr(repo, "get_kalshi_dev_key", lambda cur, uid: {"key_id": "DEV-test", "private_key_enc": b"",
                                                                       "created_at": datetime(2026, 10, 1)})
    monkeypatch.setattr(demo_twins, "balance_cached", lambda cur, uid, ttl=0: 1.0)


# -- the rows, as their writers store them today ---------------------------------------------------

def _dataset(market="btc15m", label="Bitcoin 15-minute"):
    return {"market": market, "label": label, "start": "2026-09-20T00:00Z", "end": "2026-10-20T00:00Z",
            "out_of_sample_from": "2026-10-11T00:00Z", "decision_points": 2880, "contracts": 2880, "yes_rate": 0.49}


def _metrics(trades, pnl):
    return {"trades": trades, "win_rate": 0.55, "pnl": pnl, "fees": 3.1, "roi": 0.12, "profit_factor": 1.4,
            "max_drawdown": 4.2, "sharpe": 1.7, "avg_edge": 0.061, "days": 9.0, "trades_per_day": 6.2}


def _backtest_result():
    """backtest.evaluate's block: what a strategy tested before the gatekeeper stored."""
    ins, oos = _metrics(140, 9.4), _metrics(56, 3.2)
    return {"capital": 100.0, "dataset": _dataset(), "in_sample": ins, "out_of_sample": oos,
            "equity": [[1760918400 + 900 * i, round(0.05 * i, 2)] for i in range(6)],
            "gates": [{"name": "Makes money on unseen data", "value": 3.2, "threshold": "> $0", "ok": True},
                      {"name": "Enough unseen trades to judge", "value": 56, "threshold": "≥ 30", "ok": True}],
            "passed": True,
            "recent_trades": [{"ticker": "KXBTC15M-26OCT201200-00", "side": "yes", "qty": 9, "entry": 0.52,
                               "exit": 1.0, "pnl": 4.25, "reason": "settled", "opened": "2026-10-19T11:46Z"}]}


def _research_result(classification, reason=None):
    """agent._result_block: research-fold metrics and the classification label only."""
    ins = dict(_metrics(80, 2.1), event_clusters=31, clustered_t=1.9, mean_net_per_event=0.04)
    block = {"capital": 100.0, "dataset": _dataset(), "in_sample": ins, "classification": classification}
    if reason:
        block["challenger_reason"] = reason
    return block


def _scan():
    return {"contracts": 12, "qualifying": 0, "entered": 0,
            "steps": [{"check": "is 1 minute to 25 hours from expiry", "passed": 12},
                      {"check": "has a spread of 5¢ or less", "passed": 0}],
            "blocked_at": "has a spread of 5¢ or less", "nearest": "tightest is 6¢",
            "why": "no open contract has a spread of 5¢ or less (of 12; tightest is 6¢)"}


def _verdict_stats():
    return {"n_trades": 41, "p_value": 0.03, "dsr": 0.91, "psr": 0.97, "sharpe": 1.4, "ci": [0.004, 0.06],
            "mean_net_return": 0.031, "placebo_p": 0.04, "max_drawdown": 3.1, "cross_day_ok": True,
            "min_sample": 30, "alpha_i": 0.012, "fdr_reject": True, "bh_reject": True, "n_trials_audited": 14,
            "cross_day_max_day_share": 0.31, "folds_n": 4, "folds_positive": 3, "cost_stress_ok": True,
            "cost_stress_mean": 0.012}


def _folds():
    return [{"from_ts": 1760918400 + 86400 * i, "to_ts": 1760918400 + 86400 * (i + 1), "n_trades": 10,
             "mean_net_return": 0.02, "net_return": 0.2} for i in range(4)]


def _seed(conn):
    """One account holding a row of each kind the pages read, written by the app's own writers."""
    from app import repository as repo
    from app.research import research_repository as research_repo
    from app.trading import spec as specmod
    from app.web.routes.community import _post_snapshot

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "old-%s@example.invalid" % uuid.uuid4().hex[:8],
                                  "Old Rows", None)["id"]
    cur.execute("UPDATE app_users SET autopilot=1 WHERE id=%s", (uid,))
    run_id = repo.create_run(cur, uid, "research", "btc15m", "momentum", "Spread compression into settlement")
    cur.execute("UPDATE app_agent_runs SET status='succeeded', started_at=%s, finished_at=%s WHERE id=%s",
                (datetime(2026, 10, 20, 10), datetime(2026, 10, 20, 11), run_id))

    dsl = specmod.validate({"side": "yes", "entry": {"min_edge": 0.06, "filters": [
        {"feature": "z_score", "op": ">", "value": 1.0}]}, "exit": {"take_profit": 0.2, "stop_loss": 0.15},
        "sizing": {"stake": 5.0, "max_positions": 20}})
    learned = specmod.validate({"side": "either", "model": {"kind": "logistic", "features": ["moneyness", "tte_min"],
                                                            "coef": [1.2, -0.01], "intercept": 0.1}})
    cross = specmod.validate({"market": "btc_daily", "side": "either",
                              "cross": {"pairing": "cross_strike", "legs": [{"market": "btc_daily"}]}})
    code = {"market": "btc15m", "sizing": {"stake": 5.0, "max_positions": 10}, "datasets": [],
            "code": "def signals(window):\n    return {}\n"}
    perp = specmod.validate({"market": "btc_perp", "sizing": {"stake": 100.0, "max_positions": 1},
                             "perpetual": {"signal": "momentum", "side": "both", "lookback_minutes": 60, "threshold": 0.002}})
    sids = {
        "passed": repo.insert_strategy(cur, uid, run_id, None, "btc15m", "momentum", "Spread squeeze", "Makers "
                                       "widen late; takers pay it.", dsl, "passed", _backtest_result()),
        "failed": repo.insert_strategy(cur, uid, run_id, None, "btc15m", "momentum", "Late drift", "t", learned,
                                       "failed", _research_result("INCONCLUSIVE")),
        "rejected": repo.insert_strategy(cur, uid, run_id, None, "btc_daily", "relative_value", "Strike pair", "t",
                                         cross, "rejected", _research_result("challenger_rejected", "No mechanism.")),
        "code": repo.insert_strategy(cur, uid, run_id, None, "btc15m", "momentum", "Coded rule", "t", code,
                                     "passed", _research_result("STAT_SUPPORTED")),
        "perpetual": repo.insert_strategy(cur, uid, run_id, None, "btc_perp", "momentum", "Perp drift", "t", perp,
                                          "failed", _research_result("INCONCLUSIVE")),
    }
    exp = research_repo.preregister(cur, {
        "user_id": uid, "run_id": run_id, "strategy_id": sids["passed"], "market": "btc15m",
        "hypothesis_hash": uuid.uuid4().hex, "spec": dsl,
        "economic_rationale": json.dumps({"thesis": "t", "mechanism": {"who": "late takers", "why": "urgency"},
                                          "negative_control": "random entry", "challenger": "plausible"}),
        "primary_metric": "mean_net_return_per_trade", "null_hypothesis": "mean <= 0", "alt_hypothesis": "mean > 0",
        "planned_test": "one-sided t", "falsification_criteria": "p >= alpha", "min_sample": 30,
        "cost_assumptions": {"fee": "kalshi_taker", "slippage_cents": 1},
        "data_provenance": {"source": "kalshi", "markets": ["btc15m"]}, "research_partition_id": 1,
        "planned_n_tests": 4, "correction_method": "LORD++"})
    cur.execute("UPDATE app_strategies SET experiment_id=%s WHERE id=%s", (exp, sids["passed"]))
    for phase, cls in (("validation", "STAT_SUPPORTED"), ("holdout", "DEPLOYMENT_CANDIDATE")):
        research_repo.append_result(cur, exp, phase, cls, 41, {"net_pnl": 4.1, "mean_net_return": 0.031, "sharpe": 1.4,
                                                               "psr": 0.97, "dsr": 0.91, "p_value": 0.03, "ci_lo": 0.004,
                                                               "ci_hi": 0.06, "n_trials_audited": 14},
                                    equity_curve=[[1760918400 + 900 * i, 0.01] for i in range(5)], folds=_folds())

    events = {}
    for kind, msg, data in [
        ("step", "Loaded 30 days of Bitcoin 15-minute history.", {"phase": "loading", "rows": 2880}),
        ("hypothesis", "Spread squeeze", {"thesis": "t", "in_sample": _metrics(80, 2.1), "round": 1,
                                          "spec": dsl, "attribution": {"side": {"yes": {"mean_net": 0.02, "n": 40}}}}),
        ("challenger", "Challenger approved - Spread squeeze: plausible", {"title": "Spread squeeze", "decision": "approve"}),
        ("verdict", "PASSED - Spread squeeze: validation verdict is gatekeeper-held (classification=STAT_SUPPORTED, "
                    "41 trades); the numbers never return to the generator.",
         {"title": "Spread squeeze", "status": "passed", "classification": "STAT_SUPPORTED",
          "strategy_id": sids["passed"], "n_tested": 2, "stats": _verdict_stats()}),
        ("verdict", "FAILED - Late drift: validation verdict is gatekeeper-held (classification=INCONCLUSIVE, "
                    "12 trades); the numbers never return to the generator.",
         {"title": "Late drift", "status": "failed", "classification": "INCONCLUSIVE", "strategy_id": sids["failed"],
          "n_tested": 2, "stats": dict(_verdict_stats(), n_trades=12, p_value=0.4, fdr_reject=False)}),
        ("verdict", "REJECTED - Strike pair: not a finalist, so never tested on unseen data (research pnl $-1 over 9 trades).",
         {"title": "Strike pair", "status": "rejected", "strategy_id": sids["rejected"],
          "in_sample": {"pnl": -1.0, "trades": 9}}),
        ("done", "1 of 4 hypotheses passed.", {"passed": 1, "tried": 4}),
    ]:
        repo.add_event(cur, run_id, kind, msg, data)
        cur.execute("SELECT MAX(id) AS id FROM app_agent_events WHERE run_id=%s", (run_id,))
        events.setdefault(kind, []).append(cur.fetchone()["id"])

    paper = repo.create_deployment(cur, uid, sids["passed"], "btc15m", "paper")
    demo = repo.create_deployment(cur, uid, sids["passed"], "btc15m", "demo")
    repo.set_deployment_scan(cur, paper, _scan())
    repo.set_deployment_scan(cur, demo, _scan())
    now = repo.now_utc()
    for i in range(6):
        repo.insert_closed_position(cur, paper, uid, "paper", "KXBTC15M-26OCT20%02d00-00" % i, "yes", 9, 0.52, 0.07,
                                    1.0 if i % 2 else 0.0, 0.0, round(9 * ((1.0 if i % 2 else 0.0) - 0.52) - 0.07, 4),
                                    "settled", now - timedelta(days=2, hours=i), order_ref="sim:old-%d" % i,
                                    opened_at=now - timedelta(days=2, hours=i, minutes=14),
                                    closed_at=now - timedelta(days=2, hours=i))
    repo.insert_position(cur, paper, uid, "paper", "KXBTC15M-26OCT262300-00", "yes", 9, 0.48, 0.07,
                         now + timedelta(hours=1), order_ref="sim:open-1")
    # Demo orders (one filled, one Kalshi refused), so the live check reads its demo record and sweeps.
    for n, (status, raw) in enumerate((("booked", {"order_id": "ord-1", "status": "executed", "fill_count": 4}),
                                       ("unfilled", {"status": "refused", "refused": {
                                           "http_status": 400, "code": "insufficient_balance",
                                           "message": "Insufficient balance", "client_order_id": "old-demo-2"}}))):
        intent = "old-demo-%d-%d" % (demo, n)
        repo.insert_order_intent(cur, intent, demo, uid, "demo", "buy", "yes", "KXBTC15M-26OCT201200-00", 4, 0.52,
                                 intent, market_close_time=now - timedelta(days=1))
        repo.mark_order_intent(cur, intent, status, raw_json=raw)
    repo.insert_demo_sweep(cur, uid, 3, [{"ticker": "KXBTC15M-26OCT201200-00", "kind": "book_only",
                                          "exchange_qty": 0, "book_qty": 4}])
    repo.add_chat(cur, uid, "user", "Can you tighten my risk?")
    pid = repo.create_proposal(cur, uid, "set_risk", "Tighten the stop.", None, None, "pending",
                               payload={"position_stop_pct": 25.0, "max_open_positions": 8})
    repo.add_chat(cur, uid, "agent", "Proposed a risk-control change.", proposal_id=pid)
    dpid = repo.create_proposal(cur, uid, "pause", "Quiet for a day.", paper, None, "pending")
    repo.add_chat(cur, uid, "agent", "Proposed pausing it.", proposal_id=dpid)
    posts = {}
    for kind, ref in (("strategy", sids["passed"]), ("deployment", paper), ("pnl", 0)):
        posts[kind] = repo.create_post(cur, uid, "Look at this %s" % kind, kind, _post_snapshot(cur, uid, kind, ref))
    return uid, run_id, sids, {"paper": paper, "demo": demo}, events, posts


# -- the fuzz --------------------------------------------------------------------------------------

def _paths(value, path=(), depth=0):
    """Every key path in a stored JSON value; a list's items share one path ("*"): all of them change."""
    if depth >= MAX_DEPTH:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            yield path + (k,), v
            yield from _paths(v, path + (k,), depth + 1)
    elif isinstance(value, list) and value and isinstance(value[0], (dict, list)):
        yield from _paths(value[0], path + ("*",), depth + 1)


def _mutate(value, path, new):
    """A copy of value with the key at path removed (new is DROP) or replaced."""
    out = copy.deepcopy(value)

    def go(node, rest):
        if rest[0] == "*":
            for item in (node if isinstance(node, list) else []):
                go(item, rest[1:])
            return
        if not isinstance(node, dict) or rest[0] not in node:
            return
        if len(rest) == 1:
            if new is DROP:
                del node[rest[0]]
            else:
                node[rest[0]] = new
        else:
            go(node[rest[0]], rest[1:])
    go(out, path)
    return out


def _variants(value):
    """(label, stored text or None): the column NULL and {}, then each key dropped and nulled."""
    yield "column NULL", None
    yield "column {}", "{}" if isinstance(value, dict) else "[]"
    for path, v in _paths(value):
        name = ".".join(str(p) for p in path)
        yield "%s removed" % name, json.dumps(_mutate(value, path, DROP))
        if v is not None:
            yield "%s null" % name, json.dumps(_mutate(value, path, None))


def _clear_caches():
    from app import server
    from app.services import book_memo, paper_checks

    for cache in (server._TRACK_RECORD, server._BACKTEST_CHECKS, server._ROADS, server._RUN_TOTALS,
                  server._LAST_DREAM, server._BOOK_SHAPE, paper_checks.KEPT):
        cache.clear()
    book_memo.clear()


def _route(method, url):
    from app import server

    path, _, qs = url.partition("?")
    for meth, rx, fn, _needs in server.ROUTES:
        m = rx.match(path) if meth == method else None
        if m:
            return fn, m.groups(), dict(parse_qsl(qs))
    raise AssertionError("no route for %s %s" % (method, url))


class _Logged:
    """The connection, noting each statement a request sends."""

    def __init__(self, conn):
        self.conn, self.sent = conn, []

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def cursor(self):
        cur = self.conn.cursor()
        execute = cur.execute

        def logged(sql, params=None):
            self.sent.append(" ".join(str(sql).split()))
            return execute(sql, params)
        cur.execute = logged
        return cur


def _reads(sent, table, column):
    """Whether any of these statements can read table.column (by name, or a * select of the table)."""
    return any(column in q or (table in q and re.search(r"SELECT (\w+\.)?\*", q)) for q in sent)


def _call(conn, user, url):
    """Ask for url ("POST /path" posts {}) as the server would answer it: None when it answers, or
    refuses in words it chose (ApiError), else the error and the app line that raised it (a 500)."""
    import traceback

    from app.web import http

    method, _, target = url.rpartition(" ")
    fn, params, query = _route(method or "GET", target)
    handler = SimpleNamespace(cookies=lambda: {}, headers={}, client_address=("127.0.0.1", 0))
    try:
        res = fn(http.Ctx(conn, dict(user), params, query, {}, handler))
        if not (isinstance(res, tuple) and res and res[0] in ("download", "html", "image", "redirect")):
            json.dumps(res, default=http._json_default, separators=(",", ":"))
    except http.ApiError:
        return None
    except Exception as e:  # noqa: BLE001 - every other error is a 500
        frames = [f for f in traceback.extract_tb(e.__traceback__) if "/app/" in f.filename] or \
            traceback.extract_tb(e.__traceback__)
        return "%s: %s (%s:%d)" % (type(e).__name__, e, os.path.relpath(frames[-1].filename), frames[-1].lineno)
    return None


def test_old_and_partial_stored_rows_never_500_a_page(conn, quiet):
    from app import repository as repo

    uid, run_id, sids, deps, events, posts = _seed(conn)
    cur = conn.cursor()
    user = repo.get_user(cur, uid)
    books = ["/api/deployments", "/api/dashboard", "/api/track-record", "/api/trades.csv"]  # the deployed one's
    targets = []  # (what, table, column, row id, the pages that may read it)
    cur.execute("SELECT id, status FROM app_strategies WHERE user_id=%s", (uid,))
    status = {r["id"]: r["status"] for r in cur.fetchall()}
    for name, sid in sids.items():
        # Its own pages, the list filtered to its status (the default list hides failed and rejected), the
        # autopilot panel when it passed (deployed, or passed and waiting), and the books it trades in.
        pages = ["/api/strategies/%d" % sid, "/api/strategies/%d/live-readiness" % sid,
                 "POST /api/strategies/%d/whatif" % sid, "/api/strategies?status=%s" % status[sid]]
        pages += ["/api/autopilot/status"] if status[sid] == "passed" else []
        pages += books if name == "passed" else []
        targets.append(("strategy %s spec" % name, "app_strategies", "spec_json", sid, pages))
        targets.append(("strategy %s result" % name, "app_strategies", "result_json", sid, pages))
    deploy_pages = ["/api/deployments", "/api/dashboard", "/api/autopilot/status",
                    "/api/strategies/%d" % sids["passed"]]
    for name, did in deps.items():
        targets.append(("deployment %s scan" % name, "app_deployments", "last_scan_json", did, deploy_pages))
    run_pages = ["/api/runs/%d" % run_id, "/api/runs", "/api/autopilot/status", "/api/research/scoreboard"]
    for kind, ids in events.items():
        for eid in ids:
            targets.append(("event %s %d" % (kind, eid), "app_agent_events", "data_json", eid, run_pages))
    for name, pid in posts.items():
        targets.append(("post %s snapshot" % name, "app_posts", "snapshot_json", pid, ["/api/community"]))
    demo_pages = ["/api/strategies/%d/live-readiness" % sids["passed"], "/api/strategies/%d" % sids["passed"],
                  "/api/deployments", "/api/autopilot/status", "/api/dashboard"]
    cur.execute("SELECT intent_id FROM app_order_intents WHERE user_id=%s AND status='unfilled'", (uid,))
    targets.append(("demo refusal", "app_order_intents", "raw_json", ("intent_id", cur.fetchone()["intent_id"]),
                    demo_pages))
    cur.execute("SELECT MAX(id) AS id FROM app_demo_reconcile_sweeps WHERE user_id=%s", (uid,))
    targets.append(("demo sweep mismatches", "app_demo_reconcile_sweeps", "mismatches", cur.fetchone()["id"],
                    demo_pages))
    cur.execute("SELECT id FROM app_experiments WHERE strategy_id=%s", (sids["passed"],))
    exp = cur.fetchone()["id"]
    for col in ("spec_json", "cost_assumptions_json", "data_provenance_json", "economic_rationale"):
        targets.append(("experiment %s" % col, "app_experiments", col, exp, ["/api/strategies/%d" % sids["passed"]]))
    cur.execute("SELECT id FROM app_experiment_results WHERE experiment_id=%s", (exp,))
    for r in cur.fetchall():
        for col in ("equity_curve_json", "folds_json"):
            targets.append(("experiment result %d %s" % (r["id"], col), "app_experiment_results", col, r["id"],
                            ["/api/strategies/%d" % sids["passed"]]))

    # Every page answers on the rows as written (else the fuzz below proves nothing), and each target is
    # fuzzed through the pages whose statements read its column.
    read = []
    for what, table, column, row_id, urls in targets:
        keep = []
        for url in urls:
            _clear_caches()
            logged = _Logged(conn)
            assert _call(logged, user, url) is None, (url, _call(conn, user, url))
            if _reads(logged.sent, table, column):
                keep.append(url)
        assert keep, "no page reads %s.%s" % (table, column)
        read.append((what, table, column, row_id, keep))

    failures, calls = {}, 0
    for what, table, column, row_id, urls in read:
        key, row_id = row_id if isinstance(row_id, tuple) else ("id", row_id)
        cur.execute("SELECT %s AS v FROM %s WHERE %s=%%s" % (column, table, key), (row_id,))
        original = cur.fetchone()["v"]
        try:
            stored = json.loads(original) if original else None
        except ValueError:
            stored = original  # economic_rationale may be plain text
        variants = list(_variants(stored)) if isinstance(stored, (dict, list)) else [("column NULL", None)]
        try:
            for label, text in variants:
                if (column, label.rsplit(" ", 1)[0]) in GATE_ONLY:
                    continue
                try:
                    cur.execute("UPDATE %s SET %s=%%s WHERE %s=%%s" % (table, column, key), (text, row_id))
                except pymysql.err.IntegrityError:  # a NOT NULL column can't hold that row
                    continue
                for url in urls:
                    _clear_caches()
                    calls += 1
                    err = _call(conn, user, url)
                    if err:
                        failures.setdefault((url.split("?")[0], err), []).append("%s: %s" % (what, label))
        finally:
            cur.execute("UPDATE %s SET %s=%%s WHERE %s=%%s" % (table, column, key), (original, row_id))
    report = ["%s -> %s\n    %s" % (url, err, "; ".join(sorted(set(cases))[:6]))
              for (url, err), cases in sorted(failures.items())]
    assert not failures, "%d of %d calls failed:\n%s" % (sum(len(c) for c in failures.values()), calls, "\n".join(report))
