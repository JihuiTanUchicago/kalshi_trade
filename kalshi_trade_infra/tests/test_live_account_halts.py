"""Account-level halts in the legacy live engine.

The per-strategy caps read only the engine's own booked trades. These pin the
two guards that read Kalshi instead: a book/Kalshi mismatch that persists pauses
every live strategy (and lifts itself once the books agree), and a whole-account
loss past the daily limit pauses them until a human resumes.
"""
import json
from datetime import datetime, timedelta

import data_pipeline.live_alerter as la
import data_pipeline.live_trading_engine as lte

T0 = datetime(2026, 10, 24, 8, 0, 0)


class Cur:
    """collector_state + live_model_state, the only tables the halts touch."""

    def __init__(self, day_start=None):
        self.state = {}
        if day_start is not None:
            self.state[lte.ACCOUNT_DAY_START_KEY] = json.dumps(day_start)
        self.paused = {}
        self._last = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self._last = []
        if s.startswith("SELECT state_value FROM collector_state"):
            v = self.state.get(params[0])
            self._last = [{"state_value": v}] if v is not None else []
        elif s.startswith("INSERT INTO collector_state"):
            self.state[params[0]] = params[1]
        elif s.startswith("INSERT INTO live_model_state") and "paused=1" in s:
            self.paused[params[0]] = params[1]
        elif s.startswith("INSERT INTO live_model_state") and "paused=0" in s:
            self.paused.pop(params[0], None)
        else:
            raise AssertionError("unexpected SQL: " + s[:90])

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return self._last


def mismatch(ticker="T1", kind=la.SHORT):
    return [("%s|%s" % (ticker, kind), kind, "SHORT/direction mismatch on %s: Kalshi -3, our book 5" % ticker)]


def run(monkeypatch, cur, tracker, now, rows, equity=None, pause_states=None):
    monkeypatch.setattr(la, "classify_mismatches", lambda c: rows)
    monkeypatch.setattr(lte, "account_equity_dollars", lambda: equity)
    states = pause_states if pause_states is not None else {}
    return lte.enforce_account_halts(cur, now, tracker, states)


# -- position mismatch -----------------------------------------------------------


def test_a_one_tick_mismatch_does_not_pause(monkeypatch):
    cur, tr = Cur(), lte.MismatchTracker(halt_after=240)
    run(monkeypatch, cur, tr, T0, mismatch())
    assert cur.paused == {}


def test_a_persisting_mismatch_pauses_every_live_strategy(monkeypatch):
    cur, tr = Cur(), lte.MismatchTracker(halt_after=240)
    run(monkeypatch, cur, tr, T0, mismatch())
    states = run(monkeypatch, cur, tr, T0 + timedelta(minutes=5), mismatch())
    assert set(cur.paused) == set(lte.LIVE_MODELS) == set(states)
    assert all(r.startswith(lte.MISMATCH_PAUSE_PREFIX) and "T1" in r for r in cur.paused.values())


def test_a_mismatch_that_clears_in_between_restarts_the_clock(monkeypatch):
    cur, tr = Cur(), lte.MismatchTracker(halt_after=240)
    run(monkeypatch, cur, tr, T0, mismatch())
    run(monkeypatch, cur, tr, T0 + timedelta(minutes=2), [])
    run(monkeypatch, cur, tr, T0 + timedelta(minutes=5), mismatch())
    assert cur.paused == {}


def test_the_mismatch_pause_lifts_once_books_agree_but_others_stay(monkeypatch):
    cur, tr = Cur(), lte.MismatchTracker(halt_after=240)
    run(monkeypatch, cur, tr, T0, mismatch())
    states = run(monkeypatch, cur, tr, T0 + timedelta(minutes=5), mismatch())
    # A risk-breach pause on one strategy must survive the mismatch clearing.
    states["random_forest"] = {"paused_reason": "risk breach: MAX_DAILY_LOSS"}
    cur.paused["random_forest"] = "risk breach: MAX_DAILY_LOSS"
    states = run(monkeypatch, cur, tr, T0 + timedelta(minutes=6), [], pause_states=states)
    assert set(states) == {"random_forest"} and set(cur.paused) == {"random_forest"}


def test_unreadable_kalshi_changes_nothing(monkeypatch):
    cur, tr = Cur(), lte.MismatchTracker(halt_after=240)
    run(monkeypatch, cur, tr, T0, mismatch())
    run(monkeypatch, cur, tr, T0 + timedelta(minutes=5), mismatch())
    unreadable = [(la.UNREADABLE, la.UNREADABLE, "could not read Kalshi positions")]
    states = run(monkeypatch, cur, tr, T0 + timedelta(minutes=6), unreadable,
                 pause_states={m: {"paused_reason": r} for m, r in cur.paused.items()})
    assert set(states) == set(lte.LIVE_MODELS)  # not lifted on an unknown


# -- whole-account daily loss ------------------------------------------------------


def test_first_reading_of_the_day_sets_the_baseline(monkeypatch):
    cur = Cur(day_start={"date": "2026-10-23", "equity": 200.0})
    run(monkeypatch, cur, lte.MismatchTracker(), T0, [], equity=100.0)
    assert json.loads(cur.state[lte.ACCOUNT_DAY_START_KEY]) == {"date": "2026-10-24", "equity": 100.0}
    assert cur.paused == {}  # yesterday's higher equity is not today's loss


def test_account_loss_past_the_limit_pauses_everything(monkeypatch):
    monkeypatch.setattr(lte, "ACCOUNT_MAX_DAILY_LOSS", 15.0)
    cur = Cur(day_start={"date": "2026-10-24", "equity": 100.0})
    run(monkeypatch, cur, lte.MismatchTracker(), T0, [], equity=84.0)
    assert set(cur.paused) == set(lte.LIVE_MODELS)
    assert all(r.startswith(lte.ACCOUNT_LOSS_PAUSE_PREFIX) for r in cur.paused.values())


def test_account_loss_within_the_limit_trades_on(monkeypatch):
    monkeypatch.setattr(lte, "ACCOUNT_MAX_DAILY_LOSS", 15.0)
    cur = Cur(day_start={"date": "2026-10-24", "equity": 100.0})
    run(monkeypatch, cur, lte.MismatchTracker(), T0, [], equity=86.0)
    assert cur.paused == {}


def test_unreadable_balance_changes_nothing(monkeypatch):
    cur = Cur(day_start={"date": "2026-10-24", "equity": 100.0})
    run(monkeypatch, cur, lte.MismatchTracker(), T0, [], equity=None)
    assert cur.paused == {}


def test_equity_counts_positions_not_just_cash(monkeypatch):
    monkeypatch.setattr(lte, "api_get_auth", lambda path: {"balance": 8000, "portfolio_value": 2000})
    assert lte.account_equity_dollars() == 100.0
    monkeypatch.setattr(lte, "api_get_auth", lambda path: {"balance": 8000})
    assert lte.account_equity_dollars() is None
