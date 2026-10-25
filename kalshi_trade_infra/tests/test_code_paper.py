"""Code paper replay (Todd 2026-10-25, "Paper only, in the sandbox"): agent-written code strategies
on paper probation trade each settled UTC day in the research sandbox, once, forward only, and are
stopped if their picks read later frames."""
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from app import backtest
from app.services import code_paper as cp
from tests.test_code_strategy import T0, _code_spec, _dataset

DAY0 = T0 - T0 % cp.DAY  # the UTC day the fixture's contracts trade in (07:00-17:00)


def _naive(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


class Repo:
    def __init__(self):
        self.cursor, self.rows, self.ledger, self.status = 0, [], [], None

    @contextmanager
    def transaction(self, conn):
        yield "tx"

    def claim_decision(self, cur, dep_id, ts):
        if self.cursor >= ts:
            return False
        self.cursor = ts
        return True

    def deployment_order_refs(self, cur, dep_id, prefix):
        return {r["ref"] for r in self.rows}

    def insert_closed_position(self, cur, dep_id, uid, mode, ticker, side, qty, entry_price, entry_fee, exit_price,
                               exit_fee, pnl, reason, close_time, ref, opened_at=None, closed_at=None):
        self.rows.append({"dep": dep_id, "mode": mode, "ticker": ticker, "qty": qty, "fees": entry_fee + exit_fee,
                          "pnl": pnl, "reason": reason, "ref": ref, "opened_at": opened_at, "closed_at": closed_at})
        return len(self.rows)

    def add_ledger(self, cur, uid, kind, amount, memo, pid):
        self.ledger.append(amount)

    def set_deployment_status(self, cur, uid, dep_id, status, reason):
        self.status = (status, reason)


@pytest.fixture
def repo(monkeypatch):
    r = Repo()
    for name in ("transaction", "claim_decision", "deployment_order_refs", "insert_closed_position", "add_ledger",
                 "set_deployment_status"):
        monkeypatch.setattr(cp.repo, name, getattr(r, name))
    return r


def _dep(created=DAY0 + 3600, cursor=0):
    return {"id": 41, "user_id": 1, "strategy_id": 16128, "market": "btc15m", "spec": _code_spec(),
            "created_at": _naive(created), "last_decision_ts": cursor}


def _buy_all(spec, ds, start_ts, end_ts, warm_from=None):
    return {ts: {s.contract.ticker: ("yes", 1.0) for s in snaps} for ts, snaps in ds.frames if start_ts <= ts < end_ts}


def _peeking(spec, ds, start_ts, end_ts, warm_from=None):
    # buys at a frame only when the window also holds the frame after it: it reads the future
    return {ts: {s.contract.ticker: ("yes", 1.0) for s in snaps}
            for ts, snaps in ds.frames if start_ts <= ts < end_ts and ts + 60 < end_ts}


def test_a_day_is_replayed_only_after_it_ends_and_from_the_deployment_on():
    dep = _dep()
    end = DAY0 + cp.DAY
    assert cp.next_day(dep, end + cp.SETTLE_GRACE_S - 1) is None
    assert cp.next_day(dep, end + cp.SETTLE_GRACE_S) == (DAY0 + 3600, end)
    assert cp.next_day(_dep(cursor=end), end + cp.DAY + cp.SETTLE_GRACE_S) == (end, end + cp.DAY)
    # after an outage, days past the backfill window are skipped, not replayed in a burst
    late = end + 10 * cp.DAY + cp.SETTLE_GRACE_S
    start, _ = cp.next_day(dep, late)
    assert start == late - late % cp.DAY - cp.MAX_BACKFILL_DAYS * cp.DAY


def test_a_settled_day_books_each_trip_once_at_its_own_times(monkeypatch, repo):
    ds = _dataset(n=8, result="yes")
    monkeypatch.setattr(cp, "load_day", lambda spec, s, e, now: ds)
    monkeypatch.setattr(backtest, "_code_book", _buy_all)
    dep, now = _dep(created=DAY0), DAY0 + cp.DAY + cp.SETTLE_GRACE_S
    line = cp.replay(None, dep, now)
    want = backtest.simulate(dep["spec"], ds, DAY0, DAY0 + cp.DAY)
    assert "booked %d paper trade(s)" % len(want) in line and len(want) >= 3
    assert [r["ref"] for r in repo.rows] == ["sim:replay:41:%s:%d" % (t.ticker, t.entry_ts) for t in want]
    assert [r["opened_at"] for r in repo.rows] == [_naive(t.entry_ts) for t in want]
    assert repo.rows[0]["pnl"] == pytest.approx(want[0].pnl) and repo.rows[0]["fees"] == pytest.approx(want[0].fees)
    assert repo.ledger == pytest.approx([t.pnl for t in want])
    assert repo.cursor == DAY0 + cp.DAY
    # the day is claimed: a second replay (another box, a retry) books nothing more
    dep["last_decision_ts"] = 0
    assert cp.replay(None, dep, now) is None and len(repo.rows) == len(want)


def test_code_that_reads_later_frames_is_stopped_not_booked(monkeypatch, repo):
    ds = _dataset(n=8)
    monkeypatch.setattr(cp, "load_day", lambda spec, s, e, now: ds)
    monkeypatch.setattr(backtest, "_code_book", _peeking)
    line = cp.replay(None, _dep(created=DAY0), DAY0 + cp.DAY + cp.SETTLE_GRACE_S)
    assert repo.status[0] == "stopped" and "reads the future" in repo.status[1] and "reads the future" in line
    assert repo.rows == [] and repo.cursor == 0
    # the same check passes a causal strategy
    monkeypatch.setattr(backtest, "_code_book", _buy_all)
    assert cp.peeked_at(_dep()["spec"], ds, DAY0, DAY0 + cp.DAY, seed=1) is None


def test_an_unsettled_trip_holds_the_day_back_then_is_left_out(monkeypatch, repo):
    ds = _dataset(n=8)
    gone = ds.frames[0][1][0].contract.ticker
    ds.results.pop(gone)
    monkeypatch.setattr(cp, "load_day", lambda spec, s, e, now: ds)
    monkeypatch.setattr(backtest, "_code_book", _buy_all)
    dep = _dep(created=DAY0)
    assert "held back" in cp.replay(None, dep, DAY0 + cp.DAY + cp.SETTLE_GRACE_S) and repo.rows == []
    line = cp.replay(None, dep, DAY0 + cp.DAY + cp.MAX_WAIT_S)
    assert "1 unsettled left out" in line and repo.rows and gone not in {r["ticker"] for r in repo.rows}


def test_run_walks_due_days_and_skips_dsl_specs(monkeypatch, repo):
    @contextmanager
    def cursor():
        yield None
    conn = type("C", (), {"cursor": staticmethod(cursor)})()
    dsl = dict(_dep(), id=42, spec={"market": "btc15m", "sizing": {"stake": 5, "max_positions": 1}})
    code = _dep(created=DAY0)
    monkeypatch.setattr(cp.repo, "running_code_paper_deployments",
                        lambda cur: [dsl, dict(code, last_decision_ts=repo.cursor)])
    seen = []
    monkeypatch.setattr(cp, "load_day", lambda spec, s, e, now: seen.append((s, e)) or _dataset(n=2))
    monkeypatch.setattr(backtest, "_code_book", _buy_all)
    lines = cp.run(conn, now_ts=DAY0 + 2 * cp.DAY + cp.SETTLE_GRACE_S)
    assert seen == [(DAY0, DAY0 + cp.DAY), (DAY0 + cp.DAY, DAY0 + 2 * cp.DAY)]
    assert len(lines) == 2 and all(line.startswith("dep 41:") for line in lines)
    monkeypatch.setattr(cp, "ENABLED", False)
    assert cp.run(conn) == []


def test_the_engine_never_ticks_a_code_strategy(monkeypatch):
    from app import engine
    from app.markets import MARKETS
    deps = [{"id": 1, "user_id": 1, "mode": "paper", "last_decision_ts": 0, "spec": _code_spec()}]
    monkeypatch.setattr(engine.repo, "running_deployments", lambda cur, market: deps)
    monkeypatch.setattr(engine.repo, "market_has_open_positions", lambda cur, market: False)
    monkeypatch.setattr(engine, "settle_due", lambda *a: 0)
    monkeypatch.setattr(engine, "score_early_exits", lambda *a: 0)
    conn = type("C", (), {"cursor": lambda self: None})()
    out = engine.tick_market(conn, MARKETS["btc15m"], None, datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc))
    assert "decided" not in out
