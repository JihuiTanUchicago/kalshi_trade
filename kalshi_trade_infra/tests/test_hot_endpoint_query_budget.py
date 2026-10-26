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
(idx_dep_strategy answers each strategy's active-deployment probes).
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import time

import pytest

from app import billing, engine, server

# A steady-state poll: the process-wide shared reads (series list, data freshness) and the run page's
# dream line are warm, as they are for every request but one a minute. get_run's run is queued past
# the overdue limit, so it also counts the queue ahead (5 for a run that is working normally).
BUDGET = {"autopilot_status": 20, "me": 5, "get_run": 6, "dashboard": 14}  # dashboard: the trades CSV counts ride the realized-P&L pass
# The Deploy board polls /api/deployments every 10s; /api/strategies/<id> is the strategy page. Both
# counted cold: the per-book backtest comparison is read once a minute, and these requests include it.
BUDGET.update({"list_deployments": 6, "get_strategy": 6})
# The track record (cached a minute per user; a returning user pays it cold) and the Strategies page.
BUDGET.update({"get_track_record": 2, "list_strategies": 3})

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

    from app import spec as specmod

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
    return {"FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id LEFT JOIN": [
                dict(dep, id=5, mode="paper"), dict(dep, id=6, mode="demo")],
            "FROM app_strategies s LEFT JOIN app_agent_runs r": [strategy]}


@pytest.mark.parametrize("name,kw", [("list_deployments", {}), ("get_strategy", {"params": ("9",)})])
def test_the_deploy_board_and_strategy_page_stay_in_their_query_budget(production, name, kw):
    server._BACKTEST_CHECKS.clear()
    log = _call(name, 10.0, extra=_board_rows(), **kw)
    repeats = sorted({s for s in log if log.count(s) > 1})
    assert not repeats, "%s read the same thing twice in one request: %s" % (name, repeats)
    assert len(log) <= BUDGET[name], "%s sent %d statements (budget %d):\n  %s" % (
        name, len(log), BUDGET[name], "\n  ".join(s for s, _ in log))
    # The board's curves are read for the deployments it lists, not every stopped one's history;
    # the strategy page sums only its own strategy's deployments.
    if name == "list_deployments":
        curves = [p for s, p in log if "SUM(pnl) OVER (PARTITION BY deployment_id" in s]
        assert len(curves) == 1 and curves[0][3:5] == (5, 6)
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
    trade = {"mode": "paper", "order_ref": "sim:1", "open_slices": 0, "pnl": 1.5, "fees": 0.14, "cost": 4.0,
             "open_cost": 0, "opened_s": 1761390000, "closed_s": 1761393600}
    rows = _board_rows()
    rows.update({
        "TIMESTAMPDIFF(SECOND, '1970-01-01', MIN(p.opened_at))": [
            dict(trade, deployment_id=5), dict(trade, deployment_id=5, order_ref="sim:2", pnl=-0.5),
            dict(trade, deployment_id=6, mode="demo", order_ref="demo:3", open_slices=1, closed_s=None, open_cost=2.0)],
        "FROM app_deployments d LEFT JOIN app_strategies s ON s.id=d.strategy_id WHERE d.id IN": [
            {"id": 5, "strategy_id": 9, "title": "Fade tails", "market": "btc15m"},
            {"id": 6, "strategy_id": 9, "title": "Fade tails", "market": "btc15m"}],
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
                {"mode": "live", "deployment_id": 5, "order_ref": "live:1", "open_slices": 1, "pnl": 0, "fees": 0.07,
                 "cost": 4.0, "open_cost": 4.0, "opened_s": 1761390061, "closed_s": None},
                {"mode": "live", "deployment_id": 8, "order_ref": "live:2", "open_slices": 0, "pnl": 1, "fees": 0.07,
                 "cost": 4.0, "open_cost": 0, "opened_s": 1761390000, "closed_s": 1761390900}],
            "WHERE d.id IN": [{"id": 5, "strategy_id": 9, "title": None, "market": None}]}
    log = []
    assert server.repo.track_record_rows(CountingCursor(log, rows), 7) == [
        {"mode": "live", "strategy_id": 9, "title": None, "market": None, "order_ref": "live:1", "open_slices": 1,
         "pnl": 0, "fees": 0.07, "cost": 4.0, "open_cost": 4.0, "opened_at": datetime(2025, 10, 25, 11, 1, 1),
         "closed_at": None}]
    assert log[1][1] == (5, 8)
    log = []
    assert server.repo.track_record_rows(CountingCursor(log, {}), 7) == [] and len(log) == 1  # no trades, no 2nd read
