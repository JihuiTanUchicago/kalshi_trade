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
    monkeypatch.setattr(server.repo, 'series_with_candles', lambda *a: set())
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


def test_sub_minimum_balance_blocks_research_start(monkeypatch):
    # A POSITIVE but sub-minimum balance passes the >0 card gate yet must still be blocked from
    # STARTING a research session — post-paid billing would otherwise overshoot it negative.
    from decimal import Decimal
    monkeypatch.setattr(server.billing, 'configured', lambda: True)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: {'default_pm_id': 'pm_fixture'})
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 0.5)
    monkeypatch.setattr(server.billing, 'MIN_RUN_BALANCE', Decimal('1.00'))
    monkeypatch.setattr(server.repo, 'create_run', lambda *a, **k: pytest.fail('agent work queued'))
    with pytest.raises(server.ApiError, match='at least') as error:
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
    assert data['spent_7d'] == 1.6 and data['runway_days'] == 430.5
    assert data['cards'] == [] and data['ledger'] == []
    assert data['min_topup'] <= data['max_topup']
    assert data['autoreload_amount'] >= data['min_reload_amount']


def test_billing_runway_is_absent_without_recent_usage_or_balance(monkeypatch):
    monkeypatch.setattr(server.billing, 'configured', lambda: False)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_rows', lambda *a: [])
    seen = []
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda cur, uid, since=None: seen.append(since) or (0.0 if since else 5.0))
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 15.0)
    data = server.billing_state(context())
    assert data['spent'] == 5.0 and data['spent_7d'] == 0.0 and data['runway_days'] is None
    assert any(s is not None for s in seen)
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda cur, uid, since=None: 2.0)
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: -1.0)
    assert server.billing_state(context())['runway_days'] is None


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


def _ap_ctx(monkeypatch, autopilot=1):
    # Minimal Ctx + repo stubs for the autopilot_status handler (deployments/pnl/actions mocked out).
    ctx = server.Ctx(
        SimpleNamespace(cursor=lambda: object()),
        {'id': 7, 'email': 'trader@example.invalid', 'name': 'S', 'picture_url': None,
         'autopilot': autopilot, 'autopilot_live': 0, 'autopilot_daily_loss_limit': 50,
         'autopilot_model': None},
        (), {}, {}, SimpleNamespace())
    monkeypatch.setattr(server.repo, 'list_deployments', lambda *a: [])
    monkeypatch.setattr(server.repo, 'get_kalshi_key', lambda *a: None)
    monkeypatch.setattr(server.repo, 'realized_pnl', lambda *a: 0.0)
    monkeypatch.setattr(server.repo, 'last_autopilot_action', lambda *a: None)
    monkeypatch.setattr(server.repo, 'last_review_at', lambda *a: None)
    monkeypatch.setattr(server.repo, 'list_runs', lambda *a, **k: [])
    monkeypatch.setattr(server.repo, 'research_week', lambda *a, **k: [])
    monkeypatch.setattr(server.repo, 'strategies_passed_since', lambda *a, **k: 0)
    monkeypatch.setattr(server.billing, 'configured', lambda: True)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 10.0)
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda *a: 0.0)
    return ctx


def test_autopilot_status_flags_billing_blocked(monkeypatch):
    # Autopilot ON but can't spend -> the panel is told WHY it's quiet (reason: credits, card on file).
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid: False)
    monkeypatch.setattr(server, '_needs_card', lambda c: False)
    out = server.autopilot_status(ctx)
    assert out['billing_blocked'] is True and out['billing_reason'] == 'credits'


def test_autopilot_status_not_blocked_when_ready(monkeypatch):
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid: True)
    out = server.autopilot_status(ctx)
    assert out['billing_blocked'] is False and out['billing_reason'] is None


def test_autopilot_status_warns_before_credits_run_out(monkeypatch):
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid: True)
    assert server.autopilot_status(ctx)['credits_low_days'] is None  # no usage this week
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 2.0)
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda cur, uid, since=None: 7.0)
    assert server.autopilot_status(ctx)['credits_low_days'] == 2.0  # $2 at $1 a day
    monkeypatch.setattr(server.repo, 'get_stripe_customer',
                        lambda *a: {'auto_reload': 1, 'default_pm_id': 'pm_synthetic'})
    assert server.autopilot_status(ctx)['credits_low_days'] is None  # auto-reload tops it up
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 70.0)
    assert server.autopilot_status(ctx)['credits_low_days'] is None  # 70 days left


def test_autopilot_status_not_blocked_when_autopilot_off(monkeypatch):
    # Even if the spend gate would fail, an OFF autopilot is not "blocked" — it's just off.
    ctx = _ap_ctx(monkeypatch, autopilot=0)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid: False)
    out = server.autopilot_status(ctx)
    assert out['billing_blocked'] is False


def test_me_exposes_min_run_balance(monkeypatch):
    # The research page needs the floor to warn a below-minimum user BEFORE they hit the 402.
    from decimal import Decimal
    monkeypatch.setattr(server.billing, 'configured', lambda: True)
    monkeypatch.setattr(server.billing, 'MIN_RUN_BALANCE', Decimal('1.00'))
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: {'default_pm_id': 'pm'})
    monkeypatch.setattr(server.repo, 'get_kalshi_key', lambda *a: None)
    monkeypatch.setattr(server.repo, 'get_kalshi_dev_key', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 0.5)
    monkeypatch.setattr(server.repo, 'spot_symbols_with_data', lambda *a: set())
    monkeypatch.setattr(server.repo, 'series_with_candles', lambda *a: set())
    data = server.me(context())
    assert data['min_run_balance'] == 1.0 and data['credit_balance'] == 0.5


def test_me_exposes_perps_live_available(monkeypatch):
    # The Funds page hides the Bitcoin-perps box unless live perps are enabled on this server.
    monkeypatch.setattr(server.billing, 'configured', lambda: False)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'get_kalshi_key', lambda *a: None)
    monkeypatch.setattr(server.repo, 'get_kalshi_dev_key', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 10.0)
    monkeypatch.setattr(server.repo, 'spot_symbols_with_data', lambda *a: set())
    monkeypatch.setattr(server.repo, 'series_with_candles', lambda *a: set())
    monkeypatch.setattr(server.kalshi_perps_trading, 'enabled', lambda: False)
    assert server.me(context())['perps_live_available'] is False
    monkeypatch.setattr(server.kalshi_perps_trading, 'enabled', lambda: True)
    assert server.me(context())['perps_live_available'] is True


@pytest.mark.parametrize('bundle', ['app.js', 'app.meridian.js'])
def test_every_market_has_a_short_label(bundle):
    # A market missing from MKT_SHORT falls back to its long label, which reads oddly in
    # filters and cards next to the short ones ("Bitcoin 15-minute, per-second data").
    import re
    from pathlib import Path
    from app import markets
    src = (Path(__file__).resolve().parents[1] / 'app' / 'static' / bundle).read_text()
    block = src[src.index('const MKT_SHORT = {'):]
    keys = set(re.findall(r'(\w+):', block[:block.index('};')]))
    assert set(markets.MARKETS) - keys == set()
