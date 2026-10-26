"""How long credits last, what happens next and what a top-up costs, as the pages are told.

- The runway counts down to where research pauses (the balance under billing.MIN_RUN_BALANCE), not to
  $0: at $2.40 and $1.50 a day research pauses within a day, and "about 2 days" was a day late.
- With auto-reload on, the next thing at that pace is a card charge: reload_days counts down to the
  auto-reload trigger, and is None while the last reload stands failed.
- A top-up answers with what the card was charged, as billing.topup_charge_cents works it, and an
  amount out of range is refused in dollars, never the field's name.
- A credits pause while the auto-reload card is declined says the card is the step, not "add credits".

Synthetic inputs only: no Stripe, database or network is called. No charge, fee or threshold moves.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import server
from app.server import ApiError
from app.web.routes import billing as billing_routes
from app.web.routes import chat as chat_routes

NOW = datetime(2026, 10, 26, 12, 0)
_NO_USAGE = {'research': 0.0, 'autopilot_research': 0.0, 'autopilot_review': 0.0, 'chat': 0.0, 'other': 0.0}
ON = {'stripe_customer_id': 'cus_synthetic', 'default_pm_id': 'pm_synthetic', 'auto_reload': 1,
      'reload_amount': Decimal('25'), 'reload_threshold': Decimal('5')}


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(billing_routes.repo, 'now_utc', lambda: NOW)


def _ctx(body=None, created_at=None):
    return server.Ctx(SimpleNamespace(cursor=lambda: object()),
                      {'id': 7, 'email': 'trader@example.invalid', 'name': 'Sample', 'autopilot': 1,
                       'created_at': created_at or NOW - timedelta(days=40)},
                      (), {}, body or {}, SimpleNamespace())


def test_the_runway_counts_down_to_where_research_pauses_not_to_zero(monkeypatch):
    # $2.40 at $10.50 a week ($1.50 a day): $1.40 above the $1.00 floor is under a day, not 1.6 days.
    assert billing_routes.runway_days(2.40, 10.50, 7.0, stop_at=1.0) == 0.9
    assert billing_routes.runway_days(2.40, 10.50, 7.0) == 1.6  # the old count, to $0
    assert billing_routes.runway_days(0.62, 17.50, 7.0, stop_at=1.0) is None  # already under the floor
    monkeypatch.setattr(billing_routes.billing, 'configured', lambda: True)
    assert billing_routes.pause_at() == float(billing_routes.billing.MIN_RUN_BALANCE) == 1.0
    monkeypatch.setattr(billing_routes.billing, 'configured', lambda: False)
    assert billing_routes.pause_at() == 0.0  # payments off: nothing pauses, so the runway is to $0


def test_reload_days_is_when_auto_reload_next_charges_the_card():
    # $25.71 at $100.17 a week falls to the $5.00 trigger in about a day and a half.
    assert billing_routes.reload_days(ON, 25.71, 100.17, 7.0) == round((25.71 - 5) / (100.17 / 7), 1) == 1.4
    assert billing_routes.reload_days(dict(ON, auto_reload=0), 25.71, 100.17, 7.0) is None
    assert billing_routes.reload_days(dict(ON, default_pm_id=None), 25.71, 100.17, 7.0) is None
    assert billing_routes.reload_days(None, 25.71, 100.17, 7.0) is None
    assert billing_routes.reload_days(ON, 4.20, 100.17, 7.0) is None  # at the trigger: a reload is due now
    # A saved trigger under the minimum reads as billing.auto_reload reads it: the minimum.
    assert billing_routes.reload_trigger(dict(ON, reload_threshold=Decimal('1'))) == billing_routes.billing.AUTORELOAD_THRESHOLD


def _billing(monkeypatch, cust, failed=None, balance=25.71, spent_7d=100.17):
    monkeypatch.setattr(billing_routes.billing, 'configured', lambda: True)
    monkeypatch.setattr(billing_routes.billing, 'list_cards', lambda cid: [{'id': 'pm_synthetic', 'brand': 'visa', 'last4': '4242'}])
    monkeypatch.setattr(billing_routes.repo, 'get_stripe_customer', lambda *a: cust)
    monkeypatch.setattr(billing_routes, '_reload_failed', lambda cur, uid: failed)
    monkeypatch.setattr(billing_routes.repo, 'credit_statement', lambda *a: [])
    monkeypatch.setattr(billing_routes.repo, 'usage_by_source', lambda *a: dict(_NO_USAGE, research=spent_7d))
    monkeypatch.setattr(billing_routes.repo, 'credit_spent_total', lambda cur, uid, since=None: spent_7d)
    monkeypatch.setattr(billing_routes.repo, 'credit_totals', lambda *a: {
        'topup': {'all': balance + spent_7d, 'n': 1, 'since': 0, 'n_since': 0},
        'usage': {'all': -spent_7d, 'n': 1, 'since': -spent_7d, 'n_since': 1}})


def test_billing_says_when_the_card_is_next_charged_and_when_research_pauses(monkeypatch):
    _billing(monkeypatch, ON)
    d = server.billing_state(_ctx())
    assert d['reload_days'] == 1.4 and d['runway_days'] == round((25.71 - 1) / (100.17 / 7), 1)
    assert d['autoreload_charge'] == 26.38  # $25 plus the fee, as billing.topup_charge_cents works it
    # While the last reload stands failed there is no next charge to count down to.
    _billing(monkeypatch, ON, failed={'at': NOW, 'text': "It couldn't add $25.00 in credits."})
    assert server.billing_state(_ctx())['reload_days'] is None
    # Auto-reload off: no reload, and the runway is to the pause.
    _billing(monkeypatch, dict(ON, auto_reload=0), balance=2.40, spent_7d=10.50)
    d = server.billing_state(_ctx())
    assert d['reload_days'] is None and d['runway_days'] == 0.9


@pytest.fixture
def carded(monkeypatch):
    added = []
    monkeypatch.setattr(billing_routes.billing, 'configured', lambda: True)
    monkeypatch.setattr(billing_routes.repo, 'get_stripe_customer', lambda *a: ON)

    @contextmanager
    def tx(conn):
        yield object()

    monkeypatch.setattr(billing_routes.repo, 'transaction', tx)
    monkeypatch.setattr(billing_routes.repo, 'add_credit', lambda tx, uid, kind, credits, memo, stripe_ref=None: added.append(credits))
    monkeypatch.setattr(billing_routes.repo, 'credit_balance', lambda *a: 21.4)
    charges = []

    def charge(cid, pm, cents, off_session, idem, metadata=None):
        charges.append(cents)
        return {'id': 'pi_synthetic', 'status': 'succeeded'}

    monkeypatch.setattr(billing_routes.billing, 'charge', charge)
    monkeypatch.setattr(billing_routes.billing, '_stripe', lambda *a, **k: pytest.fail('Stripe called'))
    return charges


def test_a_top_up_answers_with_what_the_card_paid_to_the_cent(carded):
    # $19 plus 5.5% is $20.045, which the card pays as $20.05; a float sum read $20.04.
    r = server.billing_topup(_ctx({'amount': 19}))
    assert carded == [2005] and r['charged'] == 20.05 and r['balance'] == 21.4
    assert round(19 * (1 + 0.055), 2) == 20.04  # the float the page used to show


@pytest.mark.parametrize('body', [{'amount': 3}, {'amount': 2000}, {'amount': 'twenty'}, {}])
def test_a_top_up_out_of_range_is_refused_in_dollars(carded, body):
    with pytest.raises(ApiError) as e:
        server.billing_topup(_ctx(body))
    assert e.value.status == 400 and e.value.message == 'Add between $5.00 and $1,000.00 in credits.'
    assert carded == []  # nothing charged


def test_auto_reload_settings_out_of_range_are_refused_in_dollars(monkeypatch, carded):
    monkeypatch.setattr(billing_routes.repo, 'set_auto_reload', lambda *a, **k: pytest.fail('saved'))
    with pytest.raises(ApiError) as e:
        server.billing_autoreload(_ctx({'on': True, 'amount': 3}))
    assert e.value.message == 'Auto-reload adds between $20.00 and $1,000.00 at a time.'
    with pytest.raises(ApiError) as e:
        server.billing_autoreload(_ctx({'on': True, 'threshold': 1}))
    assert e.value.message == 'Auto-reload can start at a balance between $5.00 and $1,000.00.'


def test_the_autopilot_status_names_a_declined_reload_only_when_it_is_why_credits_are_short(monkeypatch):
    failed = {'at': NOW, 'text': "It couldn't add $25.00 in credits. Your card was declined for insufficient funds. Try another card."}
    monkeypatch.setattr(billing_routes, '_reload_failed', lambda cur, uid: failed)
    reads = SimpleNamespace(customer=lambda: ON, balance=lambda: 0.62)
    assert billing_routes.reload_failed_now(object(), 7, reads) == failed['text']
    # Above the trigger a reload never fires, so it can't be failing; auto-reload off: nothing to fail.
    assert billing_routes.reload_failed_now(object(), 7, SimpleNamespace(customer=lambda: ON, balance=lambda: 12.0)) is None
    assert billing_routes.reload_failed_now(object(), 7, SimpleNamespace(customer=lambda: dict(ON, auto_reload=0),
                                                                       balance=lambda: 0.62)) is None
    monkeypatch.setattr(billing_routes, '_reload_failed', lambda cur, uid: None)
    assert billing_routes.reload_failed_now(object(), 7, reads) is None


def test_the_idle_line_says_the_card_is_the_step_when_the_reload_was_declined():
    d = {'autopilot': True, 'billing_blocked': True, 'billing_reason': 'credits', 'reload_failed': 'It couldn\'t add $25.00.'}
    idle = chat_routes._idle_reason(d, [], [], 20, [])
    assert idle['code'] == 'billing' and "auto-reload couldn't charge your card" in idle['line']
    assert idle['line'].endswith('Update it on Billing, then add credits.')
    assert idle['action'] == {'label': 'Update card', 'href': '/billing'}
    idle = chat_routes._idle_reason(dict(d, reload_failed=None), [], [], 20, [])
    assert idle['line'].endswith('until you add credits.') and idle['action']['label'] == 'Add credits'


def test_api_me_carries_a_declined_reload_only_while_it_is_why_credits_are_short(monkeypatch):
    from app.web.routes import account as account_routes
    failed = {'at': NOW, 'text': "It couldn't add $25.00 in credits. Your card was declined for insufficient funds. Try another card."}
    balance = [0.62]

    class Reads:
        def __init__(self, cur, uid):
            pass

        def customer(self):
            return ON

        def balance(self):
            return balance[0]

    monkeypatch.setattr(server.billing, 'configured', lambda: True)
    monkeypatch.setattr(server.billing, 'Reads', Reads)
    monkeypatch.setattr(billing_routes, '_reload_failed', lambda cur, uid: failed)
    monkeypatch.setattr(account_routes, '_researchable_markets', lambda cur: [])
    monkeypatch.setattr(account_routes, 'models', lambda ctx: [])
    monkeypatch.setattr(server.repo, 'get_kalshi_key', lambda cur, uid: None)
    monkeypatch.setattr(server.repo, 'get_kalshi_dev_key', lambda cur, uid: None)
    ctx = server.Ctx(SimpleNamespace(cursor=lambda: object()),
                     {'id': 7, 'email': 'trader@example.invalid', 'name': 'Sample', 'picture_url': None, 'autopilot': 1},
                     (), {}, {}, SimpleNamespace(headers={}))
    me = server.me(ctx)
    assert me['reload_failed'] == failed['text'] and me['auto_reload']['charge'] == 26.38
    balance[0] = 12.0  # above the trigger: a reload never fired, so nothing is failing
    assert server.me(ctx)['reload_failed'] is None
