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
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import time

import pytest

from app import billing, engine, server

# A steady-state poll: the process-wide shared reads (series list, data freshness) and the run page's
# dream line are warm, as they are for every request but one a minute. get_run's run is queued past
# the overdue limit, so it also counts the queue ahead (5 for a run that is working normally).
BUDGET = {"autopilot_status": 20, "me": 5, "get_run": 6, "dashboard": 14}

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


def _ctx(log, balance, run_status="queued", query=None, params=()):
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
