"""A new account's credit pace. The runway divided the last 7 days' spend by 7 even for an account
minutes old, so a first session's $0.44 read "over 3 months at this week's pace" on Billing and the
autopilot card. The pace is now per day of the account's age (at most 7); under a day there is no
pace to project, except that the low-credit warning reads a first day's spend as one day's, so it
never comes later than it did."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import server
from app.web.routes import billing as billing_routes
from app.web.routes import chat as chat_routes

NOW = datetime(2026, 10, 26, 12, 0)
_NO_USAGE = {'research': 0.0, 'autopilot_research': 0.0, 'autopilot_review': 0.0, 'chat': 0.0, 'other': 0.0}


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(billing_routes.repo, 'now_utc', lambda: NOW)


def _ctx(created_at):
    return server.Ctx(SimpleNamespace(cursor=lambda: object()),
                      {'id': 7, 'email': 'trader@example.invalid', 'name': 'Sample', 'autopilot': 1, 'created_at': created_at},
                      (), {}, {}, SimpleNamespace())


def test_pace_days_is_the_account_age_capped_at_a_week():
    assert billing_routes.pace_days(None) == 7.0  # unknown age: the week, as before
    assert billing_routes.pace_days(NOW - timedelta(minutes=12)) == 0.01
    assert billing_routes.pace_days(NOW - timedelta(days=2)) == 2.0
    assert billing_routes.pace_days(NOW - timedelta(days=40)) == 7.0
    assert billing_routes.pace_days(NOW + timedelta(minutes=5)) == 0.0  # a clock skew never goes negative


def test_runway_has_no_projection_on_a_first_day_and_reads_a_young_account_per_day():
    assert billing_routes.runway_days(19.56, 0.44, 0.01) is None
    assert billing_routes.runway_days(12.0, 8.0, 2.0) == 3.0
    assert billing_routes.runway_days(98.4, 1.6, 7.0) == 430.5
    assert billing_routes.runway_days(20.0, 0.0, 3.0) is None and billing_routes.runway_days(0.0, 5.0, 3.0) is None
    # The warning's floor: a first day's spend counts as one day's, never spread over seven.
    assert billing_routes.runway_days(2.0, 3.0, 0.01, floor=True) == 0.7


def _billing(monkeypatch, spent_7d, usage_all, bonus):
    monkeypatch.setattr(server.billing, 'configured', lambda: False)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_statement', lambda *a: [])
    monkeypatch.setattr(server.repo, 'usage_by_source', lambda *a: dict(_NO_USAGE))
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda cur, uid, since=None: spent_7d)
    monkeypatch.setattr(server.repo, 'credit_totals', lambda *a: {
        k: {'all': v, 'n': 1, 'since': v, 'n_since': 1} for k, v in (('bonus', bonus), ('usage', usage_all))})


def test_billing_says_nothing_of_how_long_credits_last_twelve_minutes_into_an_account(monkeypatch):
    _billing(monkeypatch, 0.44, -0.44, 20.0)
    data = server.billing_state(_ctx(NOW - timedelta(minutes=12)))
    assert data['runway_days'] is None and data['pace_days'] == 0.01 and data['spent_7d'] == 0.44
    # Two days in, the same week's spend is two days' spend: $4 a day, not $8 / 7.
    _billing(monkeypatch, 8.0, -8.0, 20.0)
    data = server.billing_state(_ctx(NOW - timedelta(days=2)))
    assert data['runway_days'] == 3.0 and data['pace_days'] == 2.0
    # A week-old account reads exactly as before.
    data = server.billing_state(_ctx(NOW - timedelta(days=30)))
    assert data['runway_days'] == round(12.0 / (8.0 / 7), 1) and data['pace_days'] == 7.0


def test_the_low_credit_warning_comes_no_later_on_a_first_day(monkeypatch):
    reads = SimpleNamespace(customer=lambda: None, balance=lambda: 2.0)
    young = billing_routes._credits_running_low(object(), 7, reads, spent_7d=3.0, created_at=NOW - timedelta(minutes=30))
    assert young == 0.7  # at 3/7 a day it read 4.7 days and said nothing
    assert billing_routes._credits_running_low(object(), 7, reads, spent_7d=3.0) is None  # an unknown age keeps the week
    on = SimpleNamespace(customer=lambda: {'auto_reload': 1, 'default_pm_id': 'pm_x'}, balance=lambda: 2.0)
    assert billing_routes._credits_running_low(object(), 7, on, spent_7d=3.0, created_at=NOW - timedelta(minutes=30)) is None


def test_autopilot_week_runway_matches_billing_for_a_young_account(monkeypatch):
    monkeypatch.setattr(chat_routes.billing, 'configured', lambda: True)
    monkeypatch.setattr(chat_routes.repo, 'autopilot_paper_week', lambda *a: {'started': 0, 'pnl': 0.0, 'trades': 0})
    reads = SimpleNamespace(customer=lambda: None, balance=lambda: 19.56)
    credits = {'by_source': dict(_NO_USAGE, autopilot_research=0.42, autopilot_review=0.02)}
    research = {'cost_7d': 0.42, 'tested_7d': 1, 'passed_7d': 0}
    week = chat_routes._autopilot_week(object(), 7, research, reads, credits, NOW - timedelta(minutes=12))
    assert week['runway_days'] is None and week['pace_days'] == 0.01 and week['credits_left'] == 19.56
    week = chat_routes._autopilot_week(object(), 7, research, reads, credits, NOW - timedelta(days=2))
    # Until research pauses: the balance above the $1.00 floor, at the pace per day so far.
    assert week['runway_days'] == round((19.56 - 1.0) / (0.44 / 2), 1) and week['pace_days'] == 2.0
    # Credits and paper stay apart: nothing here adds a credit figure to a P&L.
    assert week['paper_pnl'] == 0.0 and week['research_credits'] == 0.42
