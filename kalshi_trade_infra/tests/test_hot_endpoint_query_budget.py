"""SQL statements per request on the polled endpoints, the way test_web_perf guards the shared reads.

/api/autopilot/status polls every 20s, /api/runs/<id> every 2s on the run page, and /api/me and
/api/dashboard load on every page. Each new figure tends to add a read, and a figure that re-reads
what the same request already read (the Stripe customer, the credit balance, the Kalshi key,
demo's realized P&L) costs every viewer on every poll. These tests count the statements one request
sends with payments and live trading switched on, and fail if a request repeats a read or goes over
its budget. Raise a budget only for a read the payload really needs.

Measured 2026-10-25 on a copy of the dev DB filled to busy-autopilot size (6,000 runs, 600k events,
60k credit rows, 20k closed positions per user):
  autopilot_status 22 -> 20 statements, me 6 -> 5, get_run 6 -> 5 (latest_dream_event was ~900ms of
  every 2s poll, now once a minute), dashboard 20 -> 14 (seven realized-P&L sums -> one pass).
Then autopilot_status 177 -> 95ms of SQL on that copy with production indexes: the paper readouts
start from the deployments (idx_pos_dep) and the deployment list drops its position totals. A paper
deployment paused in the last 24h adds one read for its own totals, since the panel shows them.
Then dashboard 15 -> 14 statements, 288 -> 197ms: the closed-trade counts ride the books' realized
P&L pass (idx_pos_user), and the deployments sum their positions before joining their JSON.
Then the dashboard's "since your last visit" strip: its two reads (new passes; the autopilot's own
changes and the sessions started) are paid for by reading the paper ledger once (balance, deposits
and reset, 3 -> 1), and each book's since-visit sums ride the same realized-P&L pass. Still 14.
Measured 2026-10-26 on a seeded busy account (700 strategies, 900 runs, 9,000 positions, beside five
smaller ones): /api/track-record 245 -> 145ms of SQL, 1 -> 2 statements (the positions grouped alone,
then each deployment's strategy once, times read as seconds); /api/strategies 90 -> 12ms, still 3
(idx_dep_strategy answers each strategy's active-deployment probes). Then GET /api/trades.csv for a
5,000-trade book: ~110 -> ~40ms of SQL, 1 -> 2 statements (the times and amounts read as the file's
text in one packed column, then each deployment's strategy once instead of joined to every trade).
Then the deployments' curves (the Deploy board's 10s poll and the dashboard's 15s one) on a seeded
account of 30 deployments and 3,000 closed trades: one JSON array per deployment instead of a row per
kept point, 33 -> 19ms of the read; /api/deployments 67 -> 55ms, /api/dashboard 74 -> 60ms.
Still one statement each; the dashboard measures 13 here (14 was its old ceiling).
Measured 2026-10-26 on a seeded heavy autopilot account (950 runs, 207k events, 80 strategies, 15
deployments, 23k positions, 40k paper-ledger rows) beside five lighter ones: the sums every polled page
re-made from the whole position history (all-time realized P&L, each deployment's totals and curve,
the paper record toward the live check and the backtest comparison, the track record's trades) are
kept per user until the positions change (services.book_memo), behind one index-only version read
(~6ms). Cold, a page pays that read once more (+1; +2 where the sums are grouped by strategy, which
also read the deployments' strategies); while the book is unchanged: /api/dashboard 224 -> 40ms,
/api/autopilot/status 112 -> 36ms, /api/deployments 103 -> 15ms (339 -> 22ms on the polls where its
30s road cache lapses), /api/strategies 41 -> 17ms, /api/track-record after its minute's cache lapses
990 -> ~130ms. The strategy page sums only its own deployments (cheap) and reads them directly.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import time

import pytest

from app import server
from app.trading import engine
from app.adapters.stripe import billing
from app.services import book_memo

# A steady-state poll: the process-wide shared reads (series list, data freshness) and the run page's
# dream line are warm, as they are for every request but one a minute. get_run's run is queued past
# the overdue limit, so it also counts the queue ahead (5 for a run that is working normally).
BUDGET = {"autopilot_status": 20, "me": 5, "get_run": 6, "dashboard": 14}  # dashboard: the trades CSV counts ride the realized-P&L pass
# Counted cold, as above: each page that sums the positions reads their version first (book_memo), +1
# (not the strategy page, which sums only its own deployments).
# The Deploy board polls /api/deployments every 10s; /api/strategies/<id> is the strategy page. Both
# counted cold: the per-book backtest comparison is read once a minute, and these requests include it.
# The board's 7th is each paper strategy's record toward the live check (one read for all of them,
# cached 30s), so a paper row says how far it is and when the counts could be in.
BUDGET.update({"list_deployments": 8, "get_strategy": 6})
# The track record (cached a minute per user; a returning user pays it cold) and the Strategies page.
BUDGET.update({"get_track_record": 3, "list_strategies": 4})
# The trades download (user-clicked, not polled): the mode's closed trades, then their strategies once.
BUDGET.update({"trades_csv": 2})

# Statements that return one aggregate row; any other SELECT answers no rows unless listed below.
AGGREGATE = ("SELECT COALESCE(", "SELECT COUNT(", "SELECT MAX(", "SELECT st.started")


class Row(dict):
    """An aggregate row whose every figure reads 0."""

    def __missing__(self, key):
        return 0


class CountingCursor:
    def __init__(self, log, rows):
        self.log, self.rows, self._out = log, rows, []

    def execute(self, sql, params=None):
        s = " ".join(str(sql).split())
        self.log.append((s, tuple(params) if params else ()))
        hit = next((rows for prefix, rows in self.rows.items() if prefix in s), None)
        self._out = list(hit) if hit is not None else ([Row()] if s.startswith(AGGREGATE) else [])

    def fetchone(self):
        return self._out[0] if self._out else None

    def fetchall(self):
        return list(self._out)


def _ctx(log, balance, run_status="queued", query=None, params=(), extra=None):
    long_ago = datetime(2026, 10, 25) - timedelta(hours=2)
    rows = {
        "FROM app_stripe_customers": [{"user_id": 7, "stripe_customer_id": "cus_1", "default_pm_id": "pm_1",
                                       "auto_reload": 0, "reload_amount": 20, "reload_threshold": 5}],
        "SELECT COALESCE(SUM(amount_usd),0) AS b FROM app_credit_ledger": [{"b": balance}],
        "FROM app_agent_runs WHERE id=%s AND user_id=%s": [{
            "id": 41, "kind": "research", "market": "btc15m", "direction": None, "prompt": "p", "status": run_status,
            "hypotheses_tried": 0, "strategies_passed": 0, "error": None, "max_hypotheses": 10, "run_forever": 0,
            "model": None, "created_at": long_ago, "started_at": None, "finished_at": None, "heartbeat_at": None}],
    }
    rows.update(extra or {})
    user = {"id": 7, "email": "trader@example.invalid", "name": "T", "username": "t", "picture_url": None,
            "autopilot": 1, "autopilot_live": 1, "autopilot_daily_loss_limit": 50, "autopilot_model": None,
            "autopilot_focus": None, "ui_theme": "tau"}
    conn = SimpleNamespace(cursor=lambda: CountingCursor(log, rows))
    return server.Ctx(conn, user, params, query or {}, {}, SimpleNamespace())


@pytest.fixture
def production(monkeypatch):
    """Payments configured and live trading available: the paths that read the card and the key."""
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_budget")
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(server.repo, "now_utc", lambda: datetime(2026, 10, 25))
    server._RUN_TOTALS.clear()
    for key, val in (("series_with_candles", []), ("history_freshness", {})):
        server._SHARED[key] = {"val": val, "at": time.time(), "busy": False}
    server._LAST_DREAM[7] = (time.time(), None)
    book_memo.clear()


def _call(name, balance, **kw):
    log = []
    getattr(server, name)(_ctx(log, balance, **kw))
    return log


# balance 0: autopilot is blocked on credits (is_ready + billing_reason); 10: it isn't, so the
# credits-low readout runs (auto-reload is off) — both used to re-read the card and the balance.
@pytest.mark.parametrize("balance", [0.0, 10.0])
@pytest.mark.parametrize("name,kw", [
    ("autopilot_status", {}),
    ("me", {}),
    ("get_run", {"params": ("41",), "query": {"after": "0"}}),  # queued past the limit: reads the queue too
    ("dashboard", {}),
])
def test_a_hot_request_stays_in_its_query_budget_and_never_repeats_a_read(production, name, kw, balance):
    log = _call(name, balance, **kw)
    repeats = sorted({s for s in log if log.count(s) > 1})
    assert not repeats, "%s read the same thing twice in one request: %s" % (name, repeats)
    assert len(log) <= BUDGET[name], "%s sent %d statements (budget %d):\n  %s" % (
        name, len(log), BUDGET[name], "\n  ".join(s for s, _ in log))


def _board_rows():
    """Two running deployments of one strategy (paper and demo) with their position totals, and that
    strategy, so the Deploy board and the strategy page run every read they make."""
    import json

    from app.trading import spec as specmod

    now = datetime(2026, 10, 25)
    spec = json.dumps(specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}}))
    result = json.dumps({"capital": 10.0, "out_of_sample": {"trades": 40, "pnl": 6.0, "win_rate": 0.6}})
    dep = {"user_id": 7, "strategy_id": 9, "market": "btc15m", "status": "running", "status_reason": None,
           "last_decision_ts": None, "created_at": now - timedelta(days=3), "updated_at": now, "last_scan_json": None,
           "last_scan_at": None, "title": "Fade tails", "direction": None, "spec_json": spec, "result_json": result,
           "realized_pnl": 1.5, "closed_trades": 12, "wins": 7, "open_positions": 1}
    strategy = {"id": 9, "run_id": 3, "parent_id": None, "market": "btc15m", "direction": None, "title": "Fade tails",
                "thesis": "t", "spec_json": spec, "status": "passed", "result_json": result, "experiment_id": None,
                "created_at": now, "hypotheses_tried": 4, "shared_from_user_id": None, "shared_from_name": None}
    bare = {k: v for k, v in dep.items() if k not in server.repo.DISPLAY_TOTALS}
    return {"FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id LEFT JOIN": [
                dict(dep, id=5, mode="paper"), dict(dep, id=6, mode="demo")],
            # The same deployments without their position totals (read while those are kept).
            "s.result_json FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id WHERE": [
                dict(bare, id=5, mode="paper"), dict(bare, id=6, mode="demo")],
            "FROM app_strategies s LEFT JOIN app_agent_runs r": [strategy]}


@pytest.mark.parametrize("name,kw", [("list_deployments", {}), ("get_strategy", {"params": ("9",)})])
def test_the_deploy_board_and_strategy_page_stay_in_their_query_budget(production, name, kw):
    server._BACKTEST_CHECKS.clear()
    server._ROADS.clear(); server._FAILING.clear()
    log = _call(name, 10.0, extra=_board_rows(), **kw)
    repeats = sorted({s for s in log if log.count(s) > 1})
    assert not repeats, "%s read the same thing twice in one request: %s" % (name, repeats)
    assert len(log) <= BUDGET[name], "%s sent %d statements (budget %d):\n  %s" % (
        name, len(log), BUDGET[name], "\n  ".join(s for s, _ in log))
    # The board's curves are read for the deployments it lists, not every stopped one's history;
    # the strategy page sums only its own strategy's deployments.
    if name == "list_deployments":
        curves = [(s, p) for s, p in log if "SUM(pnl) OVER (PARTITION BY deployment_id" in s]
        assert len(curves) == 1 and curves[0][1][3:5] == (5, 6)
        assert "JSON_ARRAYAGG" in curves[0][0]  # one row per deployment, not one per point
    else:
        assert [p for s, p in log if "LEFT JOIN (SELECT p.deployment_id" in s] == [(7, 9, 7, 9)]
        assert not any("SUM(pnl) OVER" in s for s, _ in log)


def test_the_dashboard_reads_curves_only_for_the_deployments_it_shows(production):
    """The Deployed table's curves: read for its listed deployments only, and not at all when it lists
    none (a stopped deployment's history is never drawn there)."""
    log = _call("dashboard", 10.0, extra=_board_rows())
    assert [p[3:5] for s, p in log if "SUM(pnl) OVER (PARTITION BY deployment_id" in s] == [(5, 6)]
    log = _call("dashboard", 10.0)
    assert not any("SUM(pnl) OVER" in s for s, _ in log)


def test_a_deployment_curve_comes_back_as_one_row_and_is_put_in_trade_order():
    """Each deployment's kept points arrive as one JSON array of [trade number, unix ts, cumulative
    P&L], in no promised order (JSON_ARRAYAGG has no ORDER BY on MySQL); the curve is put back in trade
    order, as the row-per-point read returned it, and the DECIMAL's text keeps its float."""
    rows = {"JSON_ARRAYAGG(JSON_ARRAY(rn,": [
        {"deployment_id": 5, "pts": "[[3, 1761390120, 1.2500], [1, 1761390000, -0.2500], [2, 1761390060, 0.1000]]"},
        {"deployment_id": 6, "pts": b"[[1, 1761393600, 12345678.1234]]"}]}
    log = []
    curves = server.repo.deployment_curves(CountingCursor(log, rows), 7, deployment_ids=[6, 5])
    assert curves == {5: [[1761390000, -0.25], [1761390060, 0.1], [1761390120, 1.25]], 6: [[1761393600, 12345678.1234]]}
    assert list(curves) == [5, 6] and len(log) == 1 and log[0][1][3:] == (5, 6, 7)


def _deps(paused_at):
    now = datetime(2026, 10, 25)
    base = {"user_id": 7, "market": "btc15m", "mode": "paper", "last_decision_ts": None, "created_at": now - timedelta(days=3),
            "last_scan_json": None, "last_scan_at": None, "direction": None, "spec_json": "{}", "result_json": None}
    return [dict(base, id=5, strategy_id=9, status="running", status_reason=None, updated_at=now, title="Fade tails"),
            dict(base, id=4, strategy_id=8, status="paused", status_reason="lost $6.00", updated_at=paused_at, title="Rain")]


def test_the_autopilot_panel_reads_position_totals_only_for_a_paper_deployment_paused_today(production):
    # The panel lists deployments without their position totals (every position each one ever booked);
    # only a paper deployment paused in the last 24h shows its trades and P&L, read for it alone.
    totals = {"AND status='closed' GROUP BY deployment_id": [{"deployment_id": 4, "n": 3, "pnl": -1.5}]}
    runs = {}
    for label, paused_at in (("today", datetime(2026, 10, 24, 20)), ("last week", datetime(2026, 10, 18))):
        log = []
        out = server.autopilot_status(_ctx(log, 10.0, extra=dict(totals, **{
            "FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id WHERE d.user_id=%s": _deps(paused_at)})))
        assert not sorted({s for s in log if log.count(s) > 1}), label
        assert not any("LEFT JOIN app_positions" in s for s, _ in log), label
        runs[label] = (out, log)
    out, log = runs["today"]
    assert [p for s, p in log if "AND status='closed' GROUP BY deployment_id" in s] == [(4,)]
    assert out["paused_recent"] == [{"deployment_id": 4, "title": "Rain", "trades": 3, "pnl": -1.5,
                                     "why": "it hit its loss guard"}]
    out, log = runs["last week"]
    assert out["paused_recent"] == [] and not any("AND status='closed' GROUP BY deployment_id" in s for s, _ in log)
    assert len(runs["today"][1]) == len(log) + 1


# The Research list polls /api/runs every 5s. A full answer, cold: the active counts, the all-time totals
# (two reads, cached 30s), the list's version, the policy, the runs and their spend, so 5 on most polls.
# Why each finished session stopped (stop_reason: out of credits, by you, an error, finished) rides the
# runs read, not a read per run. A poll that sends back the version of its last answer while nothing
# moved reads only the counts and the version (services.research_list).
# Measured 2026-10-26 on a seeded account of 300 sessions (5 live, 59k events, 7.5k debits) beside five
# lighter ones: a poll was 4 statements, ~7.5ms of SQL and 21KB of JSON (2.2KB brotli); an unchanged one
# is 2 statements, ~2.2ms and 36 bytes, and a changed one 5 statements, ~8.5ms.
RUNS_BUDGET = (7, 5)
RUNS_SAME_BUDGET = 2


def test_the_research_list_says_why_each_session_stopped_inside_its_budget(production):
    base = {"market": "btc15m", "direction": None, "prompt": "p", "hypotheses_tried": 4, "strategies_passed": 0,
            "error": None, "created_at": None, "started_at": None, "finished_at": None, "heartbeat_at": None}
    rows = [dict(base, id=9, status="succeeded", run_forever=1, out_of_credits=1),
            dict(base, id=8, status="succeeded", run_forever=1, out_of_credits=0),
            dict(base, id=7, status="succeeded", run_forever=0, out_of_credits=0),
            dict(base, id=6, status="cancelled", run_forever=1, out_of_credits=0),
            dict(base, id=5, status="failed", run_forever=0, out_of_credits=0, error="The session hit an unexpected error and stopped."),
            dict(base, id=4, status="running", run_forever=1, out_of_credits=0)]
    counts = []
    for _ in range(2):
        log = []
        out = server.list_runs(_ctx(log, 10.0, extra={"FROM app_agent_runs r WHERE r.user_id=%s": [dict(r) for r in rows]}))
        repeats = sorted({s for s in log if log.count(s) > 1})
        assert not repeats, repeats
        counts.append(len(log))
    assert counts[0] <= RUNS_BUDGET[0] and counts[1] <= RUNS_BUDGET[1], counts
    assert sum("FROM app_agent_events" in s for s, _ in log) == 1  # inside the runs read, never per run
    assert {r["id"]: r["stop_reason"] for r in out["runs"]} == {
        9: "credits", 8: "complete", 7: "limit", 6: "user", 5: "error", 4: None}
    assert not any("out_of_credits" in r for r in out["runs"])


def test_an_unchanged_research_list_poll_reads_only_the_counts_and_the_version(production):
    base = {"market": "btc15m", "direction": None, "prompt": "p", "hypotheses_tried": 4, "strategies_passed": 0,
            "error": None, "created_at": None, "started_at": None, "finished_at": None, "heartbeat_at": None,
            "run_forever": 1, "out_of_credits": 0, "ledger_top": 51, "policy": None}
    rows = [dict(base, id=9, status="running"), dict(base, id=8, status="succeeded")]

    def runs(rs):
        return {"FROM app_agent_runs r WHERE r.user_id=%s": [dict(r) for r in rs]}

    log = []
    first = server.list_runs(_ctx(log, 10.0, extra=runs(rows)))
    assert first["v"] and len(first["runs"]) == 2
    log = []
    same = server.list_runs(_ctx(log, 10.0, query={"since": first["v"]}, extra=runs(rows)))
    assert same == {"v": first["v"], "same": True}
    assert len(log) <= RUNS_SAME_BUDGET, log
    assert not any("app_agent_events" in s or "SUM(amount_usd)" in s or "FROM app_policies WHERE" in s for s, _ in log)
    # A heartbeat is not something the list shows; progress, a debit, the policy, a new session, an error are.
    beat = [dict(rows[0], heartbeat_at=datetime(2026, 10, 25)), rows[1]]
    assert server.list_runs(_ctx([], 10.0, query={"since": first["v"]}, extra=runs(beat))).get("same")
    for moved in ([dict(rows[0], hypotheses_tried=5), rows[1]],
                  [dict(r, ledger_top=52) for r in rows],
                  [dict(r, policy="2026-10-25 00:00:00|0.61|0.52|7") for r in rows],
                  [dict(base, id=10, status="queued")] + rows,
                  [rows[0], dict(rows[1], status="failed", error="The session hit an unexpected error and stopped.")]):
        log = []
        out = server.list_runs(_ctx(log, 10.0, query={"since": first["v"]}, extra=runs(moved)))
        assert not out.get("same") and out["v"] != first["v"] and len(out["runs"]) == len(moved), moved
        assert len(log) <= RUNS_BUDGET[1]
    # The live counts move it too (a session went quiet, or one is waiting).
    out = server.list_runs(_ctx([], 10.0, query={"since": first["v"]}, extra={
        **runs(rows), "SELECT kind, status, COUNT(*)": [{"kind": "research", "status": "queued", "n": 1}]}))
    assert not out.get("same") and out["counts"]["research_queued"] == 1


def test_the_run_page_reads_the_dream_line_once_a_minute_not_every_poll(production, monkeypatch):
    server._LAST_DREAM.clear()
    clock = [time.time()]
    monkeypatch.setattr(server.time, "time", lambda: clock[0])
    polls = [_call("get_run", 10.0, params=("41",), query={"after": "0"}) for _ in range(3)]
    dream = [sum("LIKE 'Dreaming:" in s for s, _ in p) for p in polls]
    assert dream == [1, 0, 0]
    clock[0] += server.LAST_DREAM_TTL
    assert sum("LIKE 'Dreaming:" in s for s, _ in _call("get_run", 10.0, params=("41",), query={"after": "0"})) == 1


def test_shared_billing_reads_answer_as_the_unshared_gate_does(monkeypatch):
    # is_ready is the autonomous spend guard; sharing the request's reads must not change its answer.
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_budget")
    for cust, bal in [(None, 50.0), ({"default_pm_id": None}, 50.0), ({"default_pm_id": "pm"}, 0.5),
                      ({"default_pm_id": "pm"}, 1.0), ({"default_pm_id": "pm"}, 50.0)]:
        monkeypatch.setattr(server.repo, "get_stripe_customer", lambda cur, uid, c=cust: c)
        monkeypatch.setattr(server.repo, "credit_balance", lambda cur, uid, b=bal: b)
        reads = billing.Reads(None, 7)
        assert billing.is_ready(None, 7, reads) is billing.is_ready(None, 7), (cust, bal)
        assert reads.customer() is cust and reads.balance() == bal


def _book_rows():
    """Three trades in two deployments (one still part-open), those deployments' strategy, and a
    deployed strategy card, so the track record and the Strategies page run every read they make."""
    trade = {"mode": "paper", "order_ref": "sim:1", "v": "0,1.5000,0.1400,4.0000,0.0000,1761390000,1761393600"}
    rows = _board_rows()
    rows.update({
        "TIMESTAMPDIFF(SECOND, '1970-01-01', MIN(p.opened_at))": [
            dict(trade, deployment_id=5), dict(trade, deployment_id=5, order_ref="sim:2", v=trade["v"].replace("1.5000", "-0.5000")),
            dict(trade, deployment_id=6, mode="demo", order_ref="demo:3", v="1,1.5000,0.1400,4.0000,2.0000,1761390000,")],
        "FROM app_deployments d LEFT JOIN app_strategies s ON s.id=d.strategy_id WHERE d.id IN": [
            {"id": 5, "strategy_id": 9, "status": "running", "title": "Fade tails", "market": "btc15m"},
            {"id": 6, "strategy_id": 9, "status": "running", "title": "Fade tails", "market": "btc15m"}],
        "AS ex FROM app_strategies s WHERE s.user_id=%s": [{"status": "passed", "n": 1, "dep": 1, "ex": 0}],
    })
    rows["FROM app_strategies s LEFT JOIN app_agent_runs r"][0].update(active_deps=1, live_deps=0)
    return rows


@pytest.mark.parametrize("name", ["get_track_record", "list_strategies"])
def test_the_track_record_and_strategies_page_stay_in_their_query_budget(production, name):
    server._TRACK_RECORD.clear()
    log = []
    out = getattr(server, name)(_ctx(log, 10.0, extra=_book_rows()))
    repeats = sorted({s for s in log if log.count(s) > 1})
    assert not repeats, "%s read the same thing twice in one request: %s" % (name, repeats)
    assert len(log) <= BUDGET[name], "%s sent %d statements (budget %d):\n  %s" % (
        name, len(log), BUDGET[name], "\n  ".join(s for s, _ in log))
    if name == "get_track_record":
        # The trades are grouped from the positions alone; the strategies are read after them, once,
        # for the deployments in the book.
        assert [p for s, p in log if "WHERE d.id IN" in s] == [(5, 6)]
        assert not any("JOIN app_deployments" in s for s, _ in log if "FROM app_positions" in s)
        paper = out["modes"]["paper"]
        assert (paper["trades"], paper["net_pnl"], paper["first_trade_at"]) == (2, 1.0, 1761390000)
        assert out["modes"]["demo"]["open_trades"] == 1 and paper["strategies"][0]["title"] == "Fade tails"
    else:
        assert out["counts"]["deployed"] == 1 and out["strategies"][0]["real"]["pnl"] == 1.5  # paper; demo beside it


def test_the_track_record_rebuilds_its_times_and_drops_a_trade_whose_deployment_is_gone():
    rows = {"TIMESTAMPDIFF(SECOND, '1970-01-01', MIN(p.opened_at))": [
                {"mode": "live", "deployment_id": 5, "order_ref": "live:1", "v": "1,0.0000,0.0700,4.0000,4.0000,1761390061,"},
                {"mode": "live", "deployment_id": 8, "order_ref": "live:2", "v": "0,1.0000,0.0700,4.0000,0.0000,1761390000,1761390900"}],
            "WHERE d.id IN": [{"id": 5, "strategy_id": 9, "status": "stopped", "title": None, "market": None}]}
    log = []
    assert server.repo.track_record_rows(CountingCursor(log, rows), 7) == [
        {"mode": "live", "strategy_id": 9, "title": None, "market": None, "dep_status": "stopped", "order_ref": "live:1",
         "open_slices": Decimal("1"), "pnl": Decimal("0.0000"), "fees": Decimal("0.0700"), "cost": Decimal("4.0000"),
         "open_cost": Decimal("4.0000"), "opened_at": datetime(2025, 10, 25, 11, 1, 1), "closed_at": None}]
    assert log[1][1] == (5, 8)
    log = []
    assert server.repo.track_record_rows(CountingCursor(log, {}), 7) == [] and len(log) == 1  # no trades, no 2nd read


def test_the_trades_download_stays_in_its_query_budget_and_reads_each_strategy_once(production):
    trade = {"mode": "paper", "ticker": "KXBTC15M-26OCT2517-T98", "side": "yes", "close_reason": "settled"}
    rows = {"AS v FROM app_positions p": [
                dict(trade, v="2026-10-25T13:00:00Z,2026-10-25T12:00:00Z,0.4000,1.0000,0.0700,0.0000,2.9300,5,12,5"),
                dict(trade, v="2026-10-25T11:00:00Z,2026-10-25T10:00:00Z,0.5000,,0.0700,,,3,11,6", close_reason=None),
                dict(trade, v="2026-10-25T09:00:00Z,2026-10-25T08:00:00Z,0.5000,0.0000,0.0700,0.0000,-1.5700,3,10,5")],
            "SELECT d.id, d.strategy_id, s.title FROM app_deployments d": [{"id": 5, "strategy_id": 9, "title": "Fade tails"}]}
    log = []
    _, _, _, data = server.trades_csv(_ctx(log, 10.0, query={"mode": "paper"}, extra=rows))
    repeats = sorted({s for s in log if log.count(s) > 1})
    assert not repeats, "trades_csv read the same thing twice in one request: %s" % repeats
    assert len(log) <= BUDGET["trades_csv"], "trades_csv sent %d statements (budget %d):\n  %s" % (
        len(log), BUDGET["trades_csv"], "\n  ".join(s for s, _ in log))
    assert not any("JOIN" in s for s, _ in log if "FROM app_positions" in s)  # the trades are read alone
    assert [p for s, p in log if "WHERE d.id IN" in s] == [(5, 6)]  # each deployment once, not per trade
    assert data.splitlines()[1:] == [  # oldest first; deployment 6 is gone, so no strategy
        "2026-10-25T09:00:00Z,2026-10-25T08:00:00Z,paper,No. 00009,Fade tails,KXBTC15M-26OCT2517-T98,yes,3,"
        "0.5000,0.0000,0.0700,0.0000,-1.5700,settled,10",
        "2026-10-25T11:00:00Z,2026-10-25T10:00:00Z,paper,,,KXBTC15M-26OCT2517-T98,yes,3,0.5000,,0.0700,,,,11",
        "2026-10-25T13:00:00Z,2026-10-25T12:00:00Z,paper,No. 00009,Fade tails,KXBTC15M-26OCT2517-T98,yes,5,"
        "0.4000,1.0000,0.0700,0.0000,2.9300,settled,12"]
    log = []
    server.trades_csv(_ctx(log, 10.0, query={"mode": "live"}))
    assert len(log) == 1  # no trades, no second read


def _paper_book(k):
    """k running paper deployments (one strategy each), each 40 realistic trips in and down $2.50."""
    import json

    from app.trading import spec as specmod

    now = datetime(2026, 10, 25)
    spec = json.dumps(specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}}))
    deps = [{"id": 50 + s, "user_id": 7, "strategy_id": s, "market": "btc15m", "mode": "paper", "status": "running",
             "status_reason": None, "last_decision_ts": None, "created_at": now - timedelta(days=3), "updated_at": now,
             "last_scan_json": None, "last_scan_at": None, "title": "S%d" % s, "direction": None, "spec_json": spec,
             "result_json": None, "realized_pnl": -2.5, "closed_trades": 40, "wins": 10, "open_positions": 0}
            for s in range(1, k + 1)]
    return {"FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id LEFT JOIN app_positions p": deps,
            "SELECT t.strategy_id, COUNT(*) AS trips": [{"strategy_id": s, "trips": 40, "pnl": -2.5} for s in range(1, k + 1)]}


def test_the_research_scoreboard_reads_the_same_for_two_paper_strategies_as_for_six(production):
    """The dashboard's research loop board (/api/research/scoreboard), counted cold. It read each paper
    strategy's record up to four times: the live-ready check (paper_evidence: five reads and a bootstrap,
    even for a strategy down on paper, which can never pass) and the tournament's entrants and book (the
    trips one strategy at a time, twice). Measured 2026-10-26 on a seeded account (320 runs, 4,500 ideas,
    22 deployments, 4,000 positions): 118 -> 29 statements, 11.4s -> under 1s cold."""
    counts = []
    for k in (2, 6):
        server._SHARED.clear()
        log = []
        server.research_scoreboard(_ctx(log, 10.0, query={"days": "14"}, extra=_paper_book(k)))
        assert not any("FROM app_positions p JOIN app_deployments d" in s for s, _ in log)  # no per-strategy trips
        counts.append(len(log))
    assert counts[0] == counts[1], counts


# The positions' version (services.book_memo) and the full-history sums a page keeps behind it.
VERSION = "COALESCE(MAX(id),0) AS top"
HEAVY = ("SUM(pnl) OVER (PARTITION BY deployment_id", "LEFT JOIN (SELECT p.deployment_id", "AS paper_all",
         "GROUP BY DATE(closed_at)", "SELECT t.strategy_id, COUNT(*) AS trips", "COUNT(DISTINCT SUBSTRING(p.ticker",
         "TIMESTAMPDIFF(SECOND, '1970-01-01', MIN(p.opened_at))", "SELECT d.strategy_id, p.order_ref, SUM(p.pnl)", "AS pnl_sq")
STRATEGIES = "SELECT id, strategy_id FROM app_deployments WHERE user_id=%s"


def _panel_rows(strategy_of_4=8):
    return {"FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id WHERE d.user_id=%s": _deps(datetime(2026, 10, 18)),
            STRATEGIES: [{"id": 5, "strategy_id": 9}, {"id": 4, "strategy_id": strategy_of_4}]}


# (cold, kept) statements with these rows and a book of positions: cold pays the version read (and, for
# the reads grouped by strategy, the deployments' strategies once); kept drops every heavy sum.
KEPT_BUDGET = {"dashboard": (16, 14), "list_deployments": (9, 6), "get_track_record": (3, 2), "autopilot_status": (25, 23)}
KEPT_PAGES = [("dashboard", {}, _board_rows), ("list_deployments", {}, _board_rows),
              ("get_track_record", {}, _book_rows),
              ("autopilot_status", {}, _panel_rows)]


def _poll(name, kw, rows, version):
    """One request with the positions at `version` and the rows `rows()` makes (a page's reads change
    the rows they are handed): (its statements, the heavy sums among them, its JSON)."""
    import json

    for cache in (server._TRACK_RECORD, server._BACKTEST_CHECKS, server._ROADS, server._FAILING):
        cache.clear()
    log = []
    out = getattr(server, name)(_ctx(log, 10.0, extra=dict(rows(), **{VERSION: [version]}), **kw))
    return [s for s, _ in log], [s for s, _ in log if any(h in s for h in HEAVY)], json.dumps(
        out, default=server._json_default, sort_keys=True)


@pytest.mark.parametrize("name,kw,rows", KEPT_PAGES)
def test_a_polled_page_keeps_its_position_sums_until_the_positions_change(production, name, kw, rows):
    book = {"n": 40, "closed": 38, "top": 900}
    cold, heavy, out = _poll(name, kw, rows, book)
    assert heavy and sum(VERSION in s for s in cold) == 1  # the version is read once per request
    warm, kept, again = _poll(name, kw, rows, book)
    assert not kept, "%s re-summed the positions while they were unchanged:\n  %s" % (name, "\n  ".join(kept))
    assert again == out
    assert len(cold) <= KEPT_BUDGET[name][0] and len(warm) <= KEPT_BUDGET[name][1], (name, len(cold), len(warm))
    # A position opened (n, top), closed (closed) or replaced (top): each sums again.
    for changed in (dict(book, n=41, top=901), dict(book, closed=39), dict(book, top=950)):
        assert _poll(name, kw, rows, changed)[1] == heavy, changed
        book = changed
    # No positions: nothing is kept (an empty book is never answered from a kept read).
    for _ in range(2):
        assert _poll(name, kw, rows, {"n": 0, "closed": 0, "top": 0})[1] == heavy


def test_the_autopilot_panel_sums_again_when_a_deployment_moves_to_another_strategy(production):
    """paper_progress and paper_event_counts group the positions by their deployment's strategy, and an
    adjustment re-points a deployment without touching a position: the deployments are in the key."""
    book = {"n": 40, "closed": 38, "top": 900}
    _, heavy, _ = _poll("autopilot_status", {}, _panel_rows, book)
    assert _poll("autopilot_status", {}, _panel_rows, book)[1] == []
    assert _poll("autopilot_status", {}, lambda: _panel_rows(strategy_of_4=9), book)[1] == heavy
