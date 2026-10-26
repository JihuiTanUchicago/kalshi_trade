"""Billing's statement against a real MySQL: a session's model calls group into one line per day (the
viewer's day, by their offset from UTC) and model, card purchases stay single lines with their Stripe
reference, nothing before the window or of another user shows, the line cap holds, and the per-kind
totals add up to the balance. Read-only SQL; nothing here writes through the billing code.
Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
import random
from datetime import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

OPUS, HAIKU = "Agent usage · us.anthropic.claude-opus-4-6-v1", "Agent usage · us.anthropic.claude-haiku-4-5-20251001-v1:0"
SINCE = datetime(2026, 1, 1)


@pytest.fixture
def account():
    from app import schema
    from app import repository as repo
    from data_pipeline.common import get_db_conn

    schema.main()
    conn = get_db_conn()
    cur = conn.cursor()
    uid, other = (random.randint(10**9, 2 * 10**9) for _ in range(2))
    a = repo.create_run(cur, uid, "research", "btc15m", "momentum", prompt="Fade the open")
    b = repo.create_run(cur, uid, "review")

    def add(user, kind, amount, at, memo, run=None, ref=None):
        cur.execute("INSERT INTO app_credit_ledger (user_id, kind, amount_usd, memo, stripe_ref, run_id, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)", (user, kind, str(amount), memo, ref, run, at))

    ref = "pi_statement_%d" % uid
    add(uid, "bonus", "20", datetime(2025, 12, 20), "Welcome credits")                     # before the window
    add(uid, "usage", "-1.000000", datetime(2025, 12, 31, 23), OPUS, a)                      # before the window
    add(uid, "topup", "40", datetime(2026, 1, 10, 12), "Added $40 credits", ref=ref)
    add(uid, "usage", "-0.250000", datetime(2026, 1, 10, 23, 30), OPUS, a)                   # Jan 10 UTC, 18:30 at UTC-5
    add(uid, "usage", "-0.500000", datetime(2026, 1, 11, 0, 30), OPUS, a)                    # Jan 11 UTC, 19:30 at UTC-5
    add(uid, "usage", "-0.004200", datetime(2026, 1, 11, 0, 40), HAIKU, a)                   # same session, other model
    add(uid, "usage", "-0.012600", datetime(2026, 1, 11, 4), HAIKU, b)                       # a check-in
    add(other, "usage", "-9.000000", datetime(2026, 1, 11, 1), OPUS, None)                    # someone else's
    yield cur, uid, a, b, ref
    cur.execute("DELETE FROM app_credit_ledger WHERE user_id IN (%s,%s)", (uid, other))
    cur.execute("DELETE FROM app_agent_runs WHERE user_id=%s", (uid,))
    conn.close()


def _lines(cur, uid, tz, limit=300):
    from app.adapters.db import billing_repository
    return [(r["kind"], str(r["day"]), r["run_id"], int(r["n"]), Decimal(r["amount"]).quantize(Decimal("0.000001")))
            for r in billing_repository.credit_statement(cur, uid, SINCE, tz, limit)]


def test_a_sessions_calls_are_one_line_a_day_and_model(account):
    cur, uid, a, b, _ref = account
    six = lambda s: Decimal(s)
    # UTC: the session's two Opus calls fall on two days.
    assert _lines(cur, uid, 0) == [
        ("usage", "2026-01-11", b, 1, six("-0.012600")),
        ("usage", "2026-01-11", a, 1, six("-0.004200")),
        ("usage", "2026-01-11", a, 1, six("-0.500000")),
        ("usage", "2026-01-10", a, 1, six("-0.250000")),
        ("topup", "2026-01-10", None, 1, six("40.000000")),
    ]
    # At UTC-5 (getTimezoneOffset 300) both are the evening of Jan 10: one line of two calls.
    assert _lines(cur, uid, 300) == [
        ("usage", "2026-01-10", b, 1, six("-0.012600")),
        ("usage", "2026-01-10", a, 1, six("-0.004200")),
        ("usage", "2026-01-10", a, 2, six("-0.750000")),
        ("topup", "2026-01-10", None, 1, six("40.000000")),
    ]
    assert _lines(cur, uid, 300, limit=2) == _lines(cur, uid, 300)[:2]  # the cap, newest first


def test_each_line_carries_its_run_its_times_and_a_purchase_its_reference(account):
    from app.adapters.db import billing_repository
    cur, uid, a, b, ref = account
    rows = billing_repository.credit_statement(cur, uid, SINCE, 300, 300)
    session = next(r for r in rows if r["run_id"] == a and int(r["n"]) == 2)
    assert (session["first_at"], session["last_at"]) == (datetime(2026, 1, 10, 23, 30), datetime(2026, 1, 11, 0, 30))
    assert (session["run_kind"], session["run_prompt"], session["run_market"], session["memo"]) == ("research", "Fade the open", "btc15m", OPUS)
    assert session["stripe_ref"] is None
    checkin = next(r for r in rows if r["run_id"] == b)
    assert checkin["run_kind"] == "review"
    topup = next(r for r in rows if r["kind"] == "topup")
    assert topup["stripe_ref"] == ref and topup["run_kind"] is None


def test_the_kinds_add_up_to_the_balance_and_split_at_the_window(account):
    from app import repository as repo
    from app.adapters.db import billing_repository
    cur, uid, *_ = account
    totals = billing_repository.credit_totals(cur, uid, SINCE)
    assert set(totals) == {"bonus", "topup", "usage"}
    assert totals["bonus"] == {"all": 20.0, "n": 1, "since": 0.0, "n_since": 0}
    assert totals["topup"] == {"all": 40.0, "n": 1, "since": 40.0, "n_since": 1}
    assert totals["usage"]["n"] == 5 and totals["usage"]["n_since"] == 4
    assert totals["usage"]["all"] == pytest.approx(-1.7668) and totals["usage"]["since"] == pytest.approx(-0.7668)
    assert sum(t["all"] for t in totals.values()) == pytest.approx(repo.credit_balance(cur, uid))
