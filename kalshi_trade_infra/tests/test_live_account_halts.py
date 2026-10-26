"""Account-level halts in the legacy live engine.

The per-strategy caps read only the engine's own booked trades. These pin the
two guards that read Kalshi instead: a book/Kalshi mismatch that persists pauses
every live strategy (and lifts itself once the books agree), and a whole-account
loss past the daily limit pauses them until a human resumes.
"""
import json
from datetime import datetime, timedelta, timezone

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
    monkeypatch.setattr(lte, "kalshi_account_equity_dollars", lambda: equity)
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
    cur = Cur(day_start={"date": "2026-10-23", "value": 200.0})
    run(monkeypatch, cur, lte.MismatchTracker(), T0, [], equity=100.0)
    assert json.loads(cur.state[lte.ACCOUNT_DAY_START_KEY]) == {"date": "2026-10-24", "value": 100.0}
    assert cur.paused == {}  # yesterday's higher equity is not today's loss


def test_account_loss_past_the_limit_pauses_everything(monkeypatch):
    monkeypatch.setattr(lte, "ACCOUNT_MAX_DAILY_LOSS", 15.0)
    cur = Cur(day_start={"date": "2026-10-24", "value": 100.0})
    run(monkeypatch, cur, lte.MismatchTracker(), T0, [], equity=84.0)
    assert set(cur.paused) == set(lte.LIVE_MODELS)
    assert all(r.startswith(lte.ACCOUNT_LOSS_PAUSE_PREFIX) for r in cur.paused.values())


def test_account_loss_within_the_limit_trades_on(monkeypatch):
    monkeypatch.setattr(lte, "ACCOUNT_MAX_DAILY_LOSS", 15.0)
    cur = Cur(day_start={"date": "2026-10-24", "value": 100.0})
    run(monkeypatch, cur, lte.MismatchTracker(), T0, [], equity=86.0)
    assert cur.paused == {}


def test_unreadable_balance_changes_nothing(monkeypatch):
    cur = Cur(day_start={"date": "2026-10-24", "value": 100.0})
    run(monkeypatch, cur, lte.MismatchTracker(), T0, [], equity=None)
    assert cur.paused == {}


def test_equity_counts_positions_not_just_cash(monkeypatch):
    import data_pipeline.common as common

    monkeypatch.setattr(common, "api_get_auth", lambda path, credentials=None: {"balance": 8000, "portfolio_value": 2000})
    assert common.kalshi_account_equity_dollars() == 100.0
    monkeypatch.setattr(common, "api_get_auth", lambda path, credentials=None: {"balance": 8000})
    assert common.kalshi_account_equity_dollars() is None


# -- Tau engine: the same kill switch per app user ----------------------------------


class AppCur(Cur):
    """Adds the app tables enforce_account_equity_limits touches."""

    def __init__(self, users, deployments, day_start=None):
        super().__init__()
        self.users, self.deployments = users, deployments
        self.calls = []
        self.rowcount, self.lastrowid = 0, 1
        for uid, v in (day_start or {}).items():
            self.state["app_equity_day_start:%d" % uid] = json.dumps({"date": TODAY, "value": v})

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self._last = []
        if s.startswith("SELECT u.id, u.autopilot_live, u.autopilot_daily_loss_limit AS lim"):
            self._last = list(self.users)
        elif s.startswith("UPDATE app_users SET autopilot_live"):
            self.calls.append(("autopilot_off", params[-1]))
        elif s.startswith("UPDATE app_deployments SET status"):
            self.calls.append(("pause", params))
            self.rowcount = 1
        elif s.startswith("INSERT INTO app_chat_messages"):
            self.calls.append(("chat", params[2]))
        else:
            super().execute(sql, params)


# The engine reads the UTC day from its own clock. Freeze it, so a run that crosses midnight UTC
# reads the same day the fixtures were written for (it used to fail when a run spanned 00:00 UTC).
NOW = datetime(2026, 10, 24, 23, 59, 59, tzinfo=timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")


class FrozenClock(datetime):
    now_value = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.now_value.astimezone(tz) if tz else cls.now_value.replace(tzinfo=None)


def run_app(monkeypatch, cur, equity, now=NOW):
    from app import engine
    import app.adapters.kalshi.kalshi_account as ka
    import data_pipeline.common as common

    monkeypatch.setattr(engine, "datetime", type("Clock", (FrozenClock,), {"now_value": now}))

    monkeypatch.setattr(engine.repo, "get_kalshi_key", lambda c, uid: {"key_id": "k"})
    monkeypatch.setattr(engine.repo, "list_deployments",
                        lambda c, uid: [d for d in cur.deployments if d["user_id"] == uid])
    monkeypatch.setattr(ka, "credentials_from_row", lambda uid, row: uid)
    monkeypatch.setattr(common, "kalshi_account_equity_dollars", lambda creds: equity[creds])

    class Conn:
        def cursor(self):
            return cur

    return engine.enforce_account_equity_limits(Conn())


def test_app_user_past_their_daily_limit_on_real_equity_is_stopped(monkeypatch):
    cur = AppCur(users=[{"id": 1, "autopilot_live": 1, "lim": 20}],
                 deployments=[{"id": 9, "user_id": 1, "mode": "live", "status": "running"},
                              {"id": 8, "user_id": 1, "mode": "paper", "status": "running"}],
                 day_start={1: 100.0})
    assert run_app(monkeypatch, cur, {1: 79.0}) == 1
    kinds = [c[0] for c in cur.calls]
    assert "autopilot_off" in kinds and kinds.count("pause") == 1  # the paper deployment is untouched
    assert any(c[0] == "chat" and "$21.00" in c[1] for c in cur.calls)


def test_app_user_within_limit_or_unreadable_is_left_alone(monkeypatch):
    users = [{"id": 1, "autopilot_live": 1, "lim": 20}, {"id": 2, "autopilot_live": 0, "lim": 20}]
    cur = AppCur(users=users, deployments=[], day_start={1: 100.0, 2: 100.0})
    assert run_app(monkeypatch, cur, {1: 81.0, 2: None}) == 0
    assert cur.calls == []


def test_app_first_reading_of_the_day_only_sets_the_baseline(monkeypatch):
    cur = AppCur(users=[{"id": 1, "autopilot_live": 1, "lim": 20}], deployments=[])
    assert run_app(monkeypatch, cur, {1: 50.0}) == 0
    assert json.loads(cur.state["app_equity_day_start:1"]) == {"date": TODAY, "value": 50.0}


def test_app_day_rolls_over_at_midnight_utc_on_the_engine_clock(monkeypatch):
    """One second before midnight the day's baseline holds and the limit trips; just after, the new
    UTC day's first reading becomes the baseline and nothing trips."""
    deps = [{"id": 9, "user_id": 1, "mode": "live", "status": "running"}]
    cur = AppCur(users=[{"id": 1, "autopilot_live": 1, "lim": 20}], deployments=deps, day_start={1: 100.0})
    assert run_app(monkeypatch, cur, {1: 79.0}) == 1
    cur = AppCur(users=[{"id": 1, "autopilot_live": 1, "lim": 20}], deployments=deps, day_start={1: 100.0})
    assert run_app(monkeypatch, cur, {1: 79.0}, now=NOW + timedelta(seconds=2)) == 0
    assert json.loads(cur.state["app_equity_day_start:1"]) == {"date": "2026-10-25", "value": 79.0}
    assert cur.calls == []
