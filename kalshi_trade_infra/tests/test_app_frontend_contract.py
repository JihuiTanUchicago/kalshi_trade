"""Readiness fields and gates consumed by the Research workspace frontend."""
from types import SimpleNamespace

import pytest

from app import server


def context(body=None, admin=False):
    return server.Ctx(
        SimpleNamespace(cursor=lambda: object()),
        {'id': 7, 'email': server.ADMIN_EMAIL if admin else 'trader@example.invalid',
         'name': 'Sample', 'picture_url': None, 'autopilot': 0},
        (), {}, body or {}, SimpleNamespace(),
    )


@pytest.mark.parametrize('customer,needs_card', [
    (None, True), ({'default_pm_id': None}, True), ({'default_pm_id': 'pm_fixture'}, False),
])
def test_me_supplies_frontend_billing_readiness(monkeypatch, customer, needs_card):
    monkeypatch.setattr(server.billing, 'configured', lambda: True)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: customer)
    monkeypatch.setattr(server.repo, 'get_kalshi_key', lambda *a: None)
    monkeypatch.setattr(server.repo, 'get_kalshi_dev_key', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 98.432156)
    monkeypatch.setattr(server.repo, 'spot_symbols_with_data', lambda *a: set())
    data = server.me(context())
    assert data['needs_card'] is needs_card
    assert data['billing_enabled'] is True
    assert data['credit_balance'] == 98.4322
    assert data['user']['id'] == 7 and data['user']['autopilot'] is False
    assert data['free_bonus'] > 0 and data['markets'] and data['directions']


@pytest.mark.parametrize('admin', [False, True])
@pytest.mark.parametrize('handler,body', [
    (server.create_run, {'market': 'btc15m', 'prompt': 'Keep the strategy risk unchanged'}),
    (server.post_chat, {'content': 'Explain the saved strategy'}),
])
def test_no_card_stops_agent_work_for_every_role(monkeypatch, admin, handler, body):
    monkeypatch.setattr(server.billing, 'configured', lambda: True)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'create_run', lambda *a, **k: pytest.fail('agent work queued'))
    monkeypatch.setattr(server.repo, 'add_chat', lambda *a, **k: pytest.fail('message stored'))
    with pytest.raises(server.ApiError, match='payment method') as error:
        handler(context(body, admin))
    assert error.value.status == 402


def test_saved_card_without_credits_still_blocks_research(monkeypatch):
    monkeypatch.setattr(server.billing, 'configured', lambda: True)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: {'default_pm_id': 'pm_fixture'})
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 0)
    monkeypatch.setattr(server.repo, 'create_run', lambda *a, **k: pytest.fail('agent work queued'))
    with pytest.raises(server.ApiError, match='out of credits') as error:
        server.create_run(context({'market': 'btc15m', 'prompt': 'Keep the strategy risk unchanged'}))
    assert error.value.status == 402


def test_unconfigured_billing_is_a_complete_readonly_frontend_payload(monkeypatch):
    monkeypatch.setattr(server.billing, 'configured', lambda: False)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 98.4)
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda *a: 1.6)
    monkeypatch.setattr(server.repo, 'credit_rows', lambda *a: [])
    monkeypatch.setattr(server.billing, '_stripe', lambda *a, **k: pytest.fail('provider contacted'))
    data = server.billing_state(context())
    assert data['configured'] is False
    assert data['balance'] == 98.4 and data['spent'] == 1.6
    assert data['cards'] == [] and data['ledger'] == []
    assert data['min_topup'] <= data['max_topup']
    assert data['autoreload_amount'] >= data['min_reload_amount']


def test_admin_read_endpoint_keeps_server_side_authorization():
    with pytest.raises(server.ApiError) as error:
        server.admin_overview(context())
    assert error.value.status == 403


def test_public_system_activity_is_scoped_to_the_signed_in_user():
    class ReadCursor:
        def __init__(self):
            self.queries = []

        def execute(self, sql, params=()):
            self.queries.append((sql, params))

        def fetchone(self):
            return {'n': 0}

        def fetchall(self):
            return []

    cur = ReadCursor()
    ctx = context()
    ctx.conn.cursor = lambda: cur
    data = server.admin_system(ctx)
    assert 'users' not in data['nodes']['web']
    activity = [(sql, params) for sql, params in cur.queries if 'FROM app_agent_events' in sql]
    assert len(activity) == 1
    assert 'r.user_id=%s' in activity[0][0]
    assert activity[0][1] == (7,)
