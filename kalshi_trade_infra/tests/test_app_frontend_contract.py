"""Readiness fields and gates consumed by the Research workspace frontend."""
from types import SimpleNamespace

import pytest

from app import server
from app.web.routes import research as research_routes
from app.web.routes import chat as chat_routes


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
    assert data['credit_balance'] == 98.432156  # as the ledger holds it: the page rounds half up to the cent
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


def _totals(**by_kind):
    """credit_totals' answer: each kind's all-time sum, all of it inside the statement's window."""
    return {k: {'all': v, 'n': 1, 'since': v, 'n_since': 1} for k, v in by_kind.items()}


def test_unconfigured_billing_is_a_complete_readonly_frontend_payload(monkeypatch):
    monkeypatch.setattr(server.billing, 'configured', lambda: False)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_totals', lambda *a: _totals(bonus=100.0, usage=-1.6))
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda *a: 1.6)
    monkeypatch.setattr(server.repo, 'credit_statement', lambda *a: [])
    monkeypatch.setattr(server.repo, 'usage_by_source', lambda *a: dict(_NO_USAGE, research=1.2, autopilot_review=0.4))
    monkeypatch.setattr(server.billing, '_stripe', lambda *a, **k: pytest.fail('provider contacted'))
    data = server.billing_state(context())
    assert data['configured'] is False
    assert data['balance'] == 98.4 and data['spent'] == 1.6
    assert data['spent_7d'] == 1.6 and data['runway_days'] == 430.5
    # The pace, read-only: the last day and the week by what spent it, beside the research floor.
    assert data['spent_24h'] == 1.6 and data['spent_7d_by']['research'] == 1.2 and data['spent_7d_by']['autopilot_review'] == 0.4
    assert data['min_run_balance'] == float(server.billing.MIN_RUN_BALANCE)
    assert data['cards'] == [] and data['ledger'] == []
    assert data['min_topup'] <= data['max_topup']
    assert data['autoreload_amount'] >= data['min_reload_amount']


def test_billing_runway_is_absent_without_recent_usage_or_balance(monkeypatch):
    monkeypatch.setattr(server.billing, 'configured', lambda: False)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_statement', lambda *a: [])
    monkeypatch.setattr(server.repo, 'usage_by_source', lambda *a: dict(_NO_USAGE))
    seen = []
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda cur, uid, since=None: seen.append(since) or 0.0)
    monkeypatch.setattr(server.repo, 'credit_totals', lambda *a: _totals(bonus=20.0, usage=-5.0))
    data = server.billing_state(context())
    assert data['spent'] == 5.0 and data['spent_7d'] == 0.0 and data['runway_days'] is None
    assert any(s is not None for s in seen)
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda cur, uid, since=None: 2.0)
    monkeypatch.setattr(server.repo, 'credit_totals', lambda *a: _totals(bonus=1.0, usage=-2.0))
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


def test_system_engine_boxes_count_running_deployments_per_mode_and_read_the_engine_heartbeat():
    # "N live" used to count every running deployment, paper and demo included, and both engine boxes
    # read the retired engines' heartbeats (so they showed stale while the real engine ran).
    from datetime import timedelta

    now = server.repo.now_utc().replace(tzinfo=None)

    class ReadCursor:
        def __init__(self):
            self.rows = []

        def execute(self, sql, params=()):
            if 'FROM collector_state' in sql:
                self.rows = [{'state_key': 'recursive_engine_last_tick', 'updated_at_utc': now - timedelta(seconds=20)},
                             {'state_key': 'live_trading_last_snapshot', 'updated_at_utc': now - timedelta(days=30)}]
            elif 'FROM app_deployments' in sql and 'GROUP BY mode' in sql:
                assert "status='running'" in sql
                self.rows = [{'mode': 'paper', 'c': 5}, {'mode': 'demo', 'c': 2}, {'mode': 'live', 'c': 1}]
            else:
                self.rows = []

        def fetchone(self):
            return {'n': 0}

        def fetchall(self):
            return self.rows

    ctx = context()
    ctx.conn.cursor = lambda: ReadCursor()
    nodes = server.admin_system(ctx)['nodes']
    assert nodes['live_engine']['live'] == 1 and nodes['live_engine']['demo'] == 2
    assert nodes['sim_engine']['paper'] == 5
    assert 20 <= nodes['live_engine']['age'] < 30 and nodes['sim_engine']['age'] == nodes['live_engine']['age']
    assert 'deployments' not in nodes['live_engine']  # no one figure that sums the modes


def _ap_ctx(monkeypatch, autopilot=1):
    # Minimal Ctx + repo stubs for the autopilot_status handler (deployments/pnl/actions mocked out).
    ctx = server.Ctx(
        SimpleNamespace(cursor=lambda: object()),
        {'id': 7, 'email': 'trader@example.invalid', 'name': 'S', 'picture_url': None,
         'autopilot': autopilot, 'autopilot_live': 0, 'autopilot_daily_loss_limit': 50,
         'autopilot_model': None},
        (), {}, {}, SimpleNamespace())
    monkeypatch.setattr(server.repo, 'list_deployments_brief', lambda *a: [])
    monkeypatch.setattr(server.repo, 'positions_version', lambda *a: (0, 0, 0))  # no positions: nothing kept
    monkeypatch.setattr(server.repo, 'get_kalshi_key', lambda *a: None)
    monkeypatch.setattr(server.repo, 'realized_pnl', lambda *a: 0.0)
    monkeypatch.setattr(server.repo, 'last_autopilot_action', lambda *a: None)
    monkeypatch.setattr(server.repo, 'last_review_at', lambda *a: None)
    monkeypatch.setattr(server.repo, 'active_agent_run', lambda *a: None)
    monkeypatch.setattr(server.repo, 'list_runs', lambda *a, **k: [])
    monkeypatch.setattr(server.repo, 'research_week', lambda *a, **k: [])
    monkeypatch.setattr(server.repo, 'research_spent_since', lambda *a, **k: 0.0)
    monkeypatch.setattr(server.repo, 'autopilot_paper_week', lambda *a, **k: {'started': 0, 'pnl': 0.0, 'trades': 0})
    monkeypatch.setattr(server.repo, 'strategies_passed_since', lambda *a, **k: 0)
    monkeypatch.setattr(server.billing, 'configured', lambda: True)
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(server.repo, 'credit_balance', lambda *a: 10.0)
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda *a: 0.0)
    monkeypatch.setattr(server.repo, 'usage_by_source', lambda *a, **k: dict(_NO_USAGE))
    return ctx


_NO_USAGE = {'research': 0.0, 'autopilot_research': 0.0, 'autopilot_review': 0.0, 'chat': 0.0, 'other': 0.0}


def test_autopilot_status_flags_billing_blocked(monkeypatch):
    # Autopilot ON but can't spend -> the panel is told WHY it's quiet (reason: credits, card on file).
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid, reads=None: False)
    monkeypatch.setattr(chat_routes, '_needs_card', lambda c, reads=None: False)
    out = server.autopilot_status(ctx)
    assert out['billing_blocked'] is True and out['billing_reason'] == 'credits'


def test_autopilot_status_says_when_a_review_is_in_flight(monkeypatch):
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 25, 16, 0)
    monkeypatch.setattr(server.repo, 'now_utc', lambda: now)
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid, reads=None: True)
    review = {'status': 'queued', 'created_at': now - timedelta(seconds=30), 'heartbeat_at': None}
    monkeypatch.setattr(server.repo, 'active_agent_run', lambda cur, uid, kind=None: kind == 'review' and review)
    out = server.autopilot_status(ctx)
    assert out['reviewing'] is True and out['review_wait'] is None
    assert out['story'][0].startswith("Right now it's reviewing the markets")
    off = server.autopilot_status(_ap_ctx(monkeypatch, autopilot=0))
    assert off['reviewing'] is False  # an off autopilot reads nothing extra


def test_a_review_queued_or_silent_past_the_reaper_limit_stops_reading_as_reviewing(monkeypatch):
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 25, 16, 0)
    limit = int(server.worker.ABANDONED_AFTER.total_seconds())
    assert server.RUN_OVERDUE_SECONDS == limit
    monkeypatch.setattr(server.repo, 'now_utc', lambda: now)
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid, reads=None: True)
    review = {}
    monkeypatch.setattr(server.repo, 'active_agent_run', lambda cur, uid, kind=None: review)
    # Right at the limit it is still reviewing; one second past, it isn't.
    review.update(status='queued', created_at=now - timedelta(seconds=limit), heartbeat_at=None)
    assert server.autopilot_status(ctx)['reviewing'] is True
    review.update(created_at=now - timedelta(seconds=limit + 1))
    out = server.autopilot_status(ctx)
    assert out['reviewing'] is False
    assert out['review_wait'] == {'state': 'queued', 'seconds': limit + 1, 'overdue': True}
    # A re-queued run waits from its re-queue, not from when it was first created.
    review.update(created_at=now - timedelta(hours=3), heartbeat_at=now - timedelta(seconds=60))
    assert server.autopilot_status(ctx)['reviewing'] is True
    # Running: only a heartbeat past the limit (the point the reaper stops it) reads as silent.
    review.update(status='running', created_at=now - timedelta(hours=1), started_at=now - timedelta(minutes=50),
                  heartbeat_at=now - timedelta(seconds=limit - 10))
    assert server.autopilot_status(ctx)['reviewing'] is True
    review.update(heartbeat_at=now - timedelta(minutes=7))
    out = server.autopilot_status(ctx)
    assert out['reviewing'] is False and out['review_wait']['state'] == 'silent'
    assert out['story'][0] == ("Its review hasn't checked in for 7 minutes. A review that quiet is normally "
                               "stopped, and the next one starts on schedule.")


def test_chat_pulse_reports_a_wait_only_past_the_reaper_limit(monkeypatch):
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 25, 16, 0)
    monkeypatch.setattr(server.repo, 'now_utc', lambda: now)
    monkeypatch.setattr(server.repo, 'chat_messages', lambda *a: [])
    run = {'status': 'queued', 'created_at': now - timedelta(seconds=20), 'heartbeat_at': None}
    monkeypatch.setattr(server.repo, 'active_agent_run', lambda cur, uid, kind=None: run)
    out = server.get_chat(context())
    assert out['agent_busy'] is True and out['agent_wait'] is None
    run['created_at'] = now - timedelta(minutes=9)
    assert server.get_chat(context())['agent_wait'] == {'state': 'queued', 'seconds': 540, 'overdue': True}
    monkeypatch.setattr(server.repo, 'active_agent_run', lambda *a, **k: None)
    out = server.get_chat(context())
    assert out['agent_busy'] is False and out['agent_wait'] is None


def test_run_page_times_the_queue_on_the_server_and_counts_who_is_ahead(monkeypatch):
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 25, 16, 0)
    monkeypatch.setattr(server.repo, 'now_utc', lambda: now)
    run = {'id': 9, 'kind': 'research', 'status': 'queued', 'created_at': now - timedelta(seconds=19), 'heartbeat_at': None}
    monkeypatch.setattr(server.repo, 'get_run', lambda cur, uid, rid: dict(run))
    monkeypatch.setattr(server.repo, 'runs_spent', lambda *a: {})
    monkeypatch.setattr(server.repo, 'list_strategies', lambda *a, **k: [])
    monkeypatch.setattr(server.repo, 'get_policy', lambda *a: None)
    monkeypatch.setattr(server.repo, 'latest_dream_event', lambda *a: None)
    monkeypatch.setattr(server.repo, 'run_events', lambda *a: [])
    ahead = []
    monkeypatch.setattr(server.repo, 'research_queue_ahead', lambda cur, rid: ahead.append(rid) or 2)
    ctx = context()
    ctx.params = ('9',)
    assert server.get_run(ctx)['run']['wait'] == {'state': 'queued', 'seconds': 19, 'overdue': False}
    assert ahead == []  # only counted once the wait is overdue
    run['created_at'] = now - timedelta(minutes=6)
    assert server.get_run(ctx)['run']['wait'] == {'state': 'queued', 'seconds': 360, 'overdue': True, 'ahead': 2}
    assert ahead == [9]
    run.update(status='running', started_at=now - timedelta(minutes=30), heartbeat_at=now - timedelta(seconds=20))
    assert server.get_run(ctx)['run']['wait'] is None  # beating normally
    run.update(heartbeat_at=now - timedelta(minutes=5))
    assert server.get_run(ctx)['run']['wait'] == {'state': 'silent', 'seconds': 300, 'overdue': True}
    run.update(status='paused')
    assert server.get_run(ctx)['run']['wait'] is None


def test_me_states_what_auto_reload_will_charge_the_card(monkeypatch):
    ctx = _ap_ctx(monkeypatch, autopilot=0)
    monkeypatch.setattr(server.billing, 'TOPUP_FEE', server.Decimal('0.055'))
    monkeypatch.setattr(server.repo, 'get_stripe_customer',
                        lambda *a: {'default_pm_id': 'pm_1', 'auto_reload': 1, 'reload_amount': None, 'reload_threshold': None})
    assert server._auto_reload_terms(ctx) == {'amount': 20.0, 'charge': 21.1, 'threshold': 5.0}
    # Saved amounts below the floors charge the floors, as billing.auto_reload does.
    monkeypatch.setattr(server.repo, 'get_stripe_customer',
                        lambda *a: {'default_pm_id': 'pm_1', 'auto_reload': 1, 'reload_amount': 50, 'reload_threshold': 1})
    assert server._auto_reload_terms(ctx) == {'amount': 50.0, 'charge': 52.75, 'threshold': 5.0}
    for cust in (None, {'default_pm_id': None, 'auto_reload': 1}, {'default_pm_id': 'pm_1', 'auto_reload': 0}):
        monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a, c=cust: c)
        assert server._auto_reload_terms(ctx) is None
    monkeypatch.setattr(server.billing, 'configured', lambda: False)
    assert server._auto_reload_terms(ctx) is None


def test_autopilot_status_not_blocked_when_ready(monkeypatch):
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid, reads=None: True)
    out = server.autopilot_status(ctx)
    assert out['billing_blocked'] is False and out['billing_reason'] is None


def test_autopilot_status_warns_before_credits_run_out(monkeypatch):
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid, reads=None: True)
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
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid, reads=None: False)
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
    from app.trading import markets
    src = (Path(__file__).resolve().parents[1] / 'app' / 'static' / bundle).read_text()
    block = src[src.index('const MKT_SHORT = {'):]
    keys = set(re.findall(r'(\w+):', block[:block.index('};')]))
    assert set(markets.MARKETS) - keys == set()


def test_run_page_and_research_list_carry_each_runs_ledger_spend(monkeypatch):
    # A run-until-stopped session shows what it has taken from credits: the ledger rows billed to
    # the run, read once per response (one grouped query for the list, not one per row).
    calls = []
    monkeypatch.setattr(server.repo, 'runs_spent', lambda cur, uid, ids: calls.append((uid, list(ids))) or {9: 1.83725})
    monkeypatch.setattr(server.repo, 'get_run', lambda cur, uid, rid: {'id': rid, 'kind': 'research', 'status': 'running'})
    monkeypatch.setattr(server.repo, 'list_strategies', lambda *a, **k: [])
    monkeypatch.setattr(server.repo, 'get_policy', lambda *a: None)
    monkeypatch.setattr(server.repo, 'latest_dream_event', lambda *a: None)
    monkeypatch.setattr(server.repo, 'run_events', lambda *a: [])
    ctx = context()
    ctx.params = ('9',)
    assert server.get_run(ctx)['run']['spent_usd'] == 1.84  # to the cent, half up, as Billing rounds
    assert calls == [(7, [9])]
    calls.clear()
    monkeypatch.setattr(server.repo, 'list_runs', lambda cur, uid: [{'id': 9}, {'id': 4}, {'id': 2}])
    monkeypatch.setattr(server.repo, 'active_run_counts', lambda *a, **kw: {})
    monkeypatch.setattr(server.repo, 'list_runs_version', lambda cur, uid: [{'id': 9}, {'id': 4}, {'id': 2}])
    monkeypatch.setattr(research_routes, '_research_totals', lambda *a: {})
    runs = server.list_runs(context())['runs']
    assert [r['spent_usd'] for r in runs] == [1.84, 0.0, 0.0]  # a run with no debit cost nothing
    assert calls == [(7, [9, 4, 2])]


def test_autopilot_status_carries_a_weekly_scorecard_with_credits_and_paper_apart(monkeypatch):
    # Real credits and paper P&L travel as separate fields; nothing adds them up.
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid, reads=None: True)
    monkeypatch.setattr(server.repo, 'research_week', lambda *a, **k: [{'model': None, 'runs': 3, 'tried': 41, 'passed': 0,
                                                                        'input_tokens': 0, 'output_tokens': 0}])
    monkeypatch.setattr(server.repo, 'strategies_passed_since', lambda *a, **k: 2)
    monkeypatch.setattr(server.repo, 'research_spent_since', lambda *a, **k: 7.256)
    seen = []
    monkeypatch.setattr(server.repo, 'autopilot_paper_week',
                        lambda cur, uid, since: seen.append((uid, since)) or {'started': 1, 'pnl': -3.456, 'trades': 4})
    week = server.autopilot_status(ctx)['week']
    assert week == {'research_credits': 7.26, 'tested': 41, 'passed': 2, 'paper_started': 1,
                    'paper_pnl': -3.46, 'paper_trades': 4,
                    'checkin_credits': 0.0, 'credits_left': 10.0, 'runway_days': None}
    assert seen[0][0] == 7 and abs((server.repo.now_utc() - seen[0][1]).total_seconds() - 7 * 86400) < 5
    off = server.autopilot_status(_ap_ctx(monkeypatch, autopilot=0))
    assert 'week' not in off and len(seen) == 1  # an off autopilot reads nothing extra
    # Its check-ins bill too, and the balance lasts as long as the Billing page says at the week's pace.
    monkeypatch.setattr(server.repo, 'usage_by_source', lambda *a, **k: dict(_NO_USAGE, research=6.58, autopilot_review=0.424))
    week = server.autopilot_status(ctx)['week']
    assert week['checkin_credits'] == 0.42 and week['credits_left'] == 10.0 and week['runway_days'] == 10.0


def test_research_estimate_uses_own_median_then_the_typical_one_per_model(monkeypatch):
    # What a session usually costs: the user's own last 10 finished sessions once there are 3, else
    # a server-wide median per model that only exists with 5+ sessions behind it. Cached.
    own = [[1.0, 3.0], [2.0, 9.0, 1.0, 4.0]]
    monkeypatch.setattr(server.repo, 'finished_session_costs', lambda cur, uid, limit: own[0])
    reads = []
    rows = [(None, 1.0), ('opus-4-6', 3.0), (None, 2.0), (None, 5.0), (None, 4.0),
            ('haiku-4-5', 0.2), ('haiku-4-5', 0.3)]
    monkeypatch.setattr(server.repo, 'recent_session_costs', lambda cur, since: reads.append(since) or rows)
    monkeypatch.setattr(research_routes, '_TYPICAL_SESSION_COST', [0.0, {}])
    monkeypatch.setattr(server.repo, 'forever_session_rates', lambda *a: [])
    monkeypatch.setattr(research_routes, '_TYPICAL_FOREVER_RATE', [0.0, {}])
    out = server.research_estimate(context())
    # The default model's NULL runs count as that model; Haiku has too few sessions to show.
    assert out == {'yours': None, 'sessions': 2, 'typical': {server.catalog.DEFAULT_KEY: 3.0},
                   'per_hour': {'yours': None, 'typical': {}}}
    own[0] = own[1]
    assert server.research_estimate(context())['yours'] == 3.0  # median of 1, 2, 4, 9
    assert len(reads) == 1  # the server-wide medians are cached
    assert server._median([5.0, 1.0, 3.0]) == 3.0


# -- idle: why the autopilot places no paper trades right now ---------------------------------------

def _idle_d(**kw):
    d = {'autopilot': True, 'paper_running': 0, 'demo_running': 0, 'live_running': 0, 'paper_open': 0,
         'paper_waiting': [], 'research': {'active': []}, 'focus': [], 'billing_blocked': False}
    d.update(kw)
    return d


def _paper(title='Fade tails — v2', scan=None):
    return {'id': 1, 'title': title, 'scan': scan}


def _waiting(title, why):
    return {'deployment_id': 1, 'title': title, 'why': why}


def _passed(title='Rain tails', market='kxrainnyc', in_focus=True, candidate=False, retired=False):
    return {'id': 5, 'title': title, 'market': market, 'in_focus': in_focus, 'candidate': candidate, 'retired': retired}


@pytest.mark.parametrize('d,paper_run,paused,age,passed,code,line,action', [
    # Strategies running, but the engine hasn't beaten: nothing else matters until it's back.
    (_idle_d(paper_running=1), [_paper()], [], None, [], 'engine',
     "Nothing is trading right now: Tau's trading engine isn't running, so your strategy can't buy or sell. "
     "There's nothing for you to do; it carries on when it's back.", None),
    (_idle_d(paper_running=2), [_paper(), _paper()], [], 1500, [], 'engine',
     "Nothing is trading right now: Tau's trading engine last checked the markets 25 minutes ago, so your 2 "
     "strategies can't buy or sell. There's nothing for you to do; they carry on when it's back.", None),
    # Running and fresh, but the market has no contracts at all.
    (_idle_d(paper_running=1, paper_waiting=[_waiting('Rain tails', 'no open contracts in the order book right now')]),
     [_paper('Rain tails', {'why': 'no open contracts in the order book right now', 'qualifying': 0})], [], 20, [],
     'market_closed', "Nothing is trading right now: the market for Rain tails has no open contracts (closed, or "
     "between events). Trading picks up when new contracts list.", None),
    # Contracts exist, but none fits the entry rules.
    (_idle_d(paper_running=1, paper_waiting=[_waiting('Fade tails', 'no open contract has a spread of 3¢ or less (of 12; tightest is 5¢)')]),
     [_paper('Fade tails', {'why': 'no open contract has a spread of 3¢ or less (of 12; tightest is 5¢)', 'qualifying': 0})], [], 20, [],
     'waiting', "No trades right now: Fade tails is waiting for a contract that fits its entry rules. Its last check: "
     "no open contract has a spread of 3¢ or less (of 12; tightest is 5¢).", None),
    # Deployed but never decided yet.
    (_idle_d(paper_running=1), [_paper()], [], 20, [], 'starting',
     "No trades yet: Fade tails went on paper and hasn't had its first look at the market. It checks at its "
     "market's next decision time.", None),
    # No scan record, but it has closed trades: the line defers to them instead of "No trades yet".
    (_idle_d(paper_running=1, paper_progress={'strategy_id': 1, 'title': 'Fade tails — v2', 'trades': 12}), [_paper()], [], 20, [],
     'flat', "Nothing open right now: Fade tails has closed 12 trades on paper and holds no position. It checks again "
     "at its market's next decision time.", None),
    (_idle_d(paper_running=2, paper_progress={'strategy_id': 1, 'title': 'Rain tails', 'trades': 1}), [_paper(), _paper('Rain tails')], [], 20, [],
     'flat', "Nothing open right now: none of your 2 paper strategies holds a position (the furthest along, Rain tails, "
     "has closed 1 trade). Each checks again at its market's next decision time.", None),
    # Nothing running: billing first, then paused deployments, then the focus, then research.
    (_idle_d(billing_blocked=True, billing_reason='card'), [], [], None, [], 'billing',
     "Nothing is on paper, and it can't research new strategies until you add a payment method.",
     {'label': 'Add a payment method', 'href': '/billing'}),
    (_idle_d(), [], [{'title': 'Rain tails — v1', 'status_reason': 'force-closed: position down 42.0% >= stop 30.0%'},
                     {'title': 'Fade tails', 'status_reason': 'By you'}], None, [], 'stopped',
     "Nothing is trading: your 2 paper strategies are paused (the latest, Rain tails: its safety stop sold a position "
     "that had lost 42% of its cost). Resume one, or let the autopilot find new ones.", {'label': 'Open Deploy', 'href': '/deploy'}),
    (_idle_d(), [], [{'title': 'Fade tails', 'status_reason': 'By you'}], None, [], 'stopped',
     "Nothing is trading: Fade tails is paused: you paused it. Resume one, or let the autopilot find new ones.",
     {'label': 'Open Deploy', 'href': '/deploy'}),
    (_idle_d(focus=['sports']), [], [], None, [_passed(in_focus=False), _passed('Fade BTC', 'btc15m', in_focus=False)], 'focus',
     "Nothing is on paper: your focus is sports, and both your passed strategies are outside it, so it won't deploy "
     "them. It researches inside the focus to find new ones.", {'label': 'Change focus', 'do': 'focus'}),
    (_idle_d(), [], [], None, [_passed(candidate=True)], 'to_deploy',
     "Nothing is on paper yet: Rain tails cleared every check, and the next review puts it on paper. It's between "
     "research runs.", None),
    (_idle_d(), [], [], None, [_passed()], 'no_candidate',
     "Nothing is on paper yet: Rain tails passed the research tests, but it hasn't cleared the last check before paper "
     "(the holdout test). It's between research runs.", None),
    (_idle_d(research={'active': ['BTC 15m']}), [], [], None, [], 'researching',
     "Nothing is on paper yet: no strategy has passed its research tests. It's researching BTC 15m.", None),
    (_idle_d(reviewing=True), [], [], None, [], 'reviewing',
     "Nothing is on paper yet: no strategy has passed its research tests. It's reviewing the markets to pick its next move.", None),
    (_idle_d(), [], [], None, [_passed(retired=True)], 'no_strategies',
     "Nothing is on paper: the strategy that passed was stopped on paper, and no new one has passed since. It's "
     "between research runs.", None),
])
def test_idle_reason_names_why_nothing_trades(d, paper_run, paused, age, passed, code, line, action):
    idle = server._idle_reason(d, paper_run, paused, age, passed)
    assert idle == {'code': code, 'line': line, 'action': action}


@pytest.mark.parametrize('d,paper_run', [
    (_idle_d(autopilot=False), []),                                         # off: the card says so
    (_idle_d(paper_running=1, paper_open=2), [_paper()]),                   # positions open: it is trading
    (_idle_d(paper_running=1), [_paper(scan={'why': '1 of 9 open contracts qualify', 'qualifying': 1})]),
    (_idle_d(demo_running=1), []),                                          # demo runs on its own
])
def test_idle_reason_is_none_while_something_trades(d, paper_run):
    assert server._idle_reason(d, paper_run, [], 20, []) is None


def test_idle_reason_skips_the_engine_when_its_beat_cannot_be_read():
    d = _idle_d(paper_running=1)
    assert server._idle_reason(d, [_paper()], [], server._UNKNOWN, [])['code'] == 'starting'


def test_autopilot_status_carries_idle_and_reads_the_engine_only_with_something_running(monkeypatch):
    ctx = _ap_ctx(monkeypatch, autopilot=1)
    monkeypatch.setattr(server.billing, 'is_ready', lambda cur, uid, reads=None: True)
    reads = []
    monkeypatch.setattr(server.repo, 'engine_last_tick_age_seconds', lambda cur: reads.append(1) or 900)
    monkeypatch.setattr(server.repo, 'list_strategies', lambda *a, **k: [])
    out = server.autopilot_status(ctx)
    assert out['idle']['code'] == 'no_strategies' and reads == []
    # One paper strategy running with the engine 15 minutes quiet: the idle line says so, and the story
    # drops "waits for its own setup", which read as healthy.
    dep = {'id': 3, 'strategy_id': 9, 'title': 'Fade tails', 'mode': 'paper', 'status': 'running', 'market': 'btc15m',
           'scan': None, 'updated_at': None}
    monkeypatch.setattr(server.repo, 'list_deployments_brief', lambda *a, **k: [dep])
    monkeypatch.setattr(server.repo, 'paper_progress', lambda *a: {})
    monkeypatch.setattr(server.repo, 'paper_event_counts', lambda *a: {})
    monkeypatch.setattr(server.repo, 'user_open_exposure', lambda *a: {'n': 0})
    out = server.autopilot_status(ctx)
    assert out['idle']['code'] == 'engine' and reads == [1]
    assert not any('waits for its own setup' in line for line in out['story'])
    off = server.autopilot_status(_ap_ctx(monkeypatch, autopilot=0))
    assert off['idle'] is None


def test_the_story_says_when_the_daily_live_loss_limit_stopped_live():
    d = _idle_d(paper_running=1, paper_open=1, today_live_pnl=-60.5, daily_loss_limit=50.0, live_running=0)
    lines = server._autopilot_story(d)
    assert ("Live trading stopped for today: today's live loss of $60.50 reached your $50.00 daily limit, so live "
            "autopilot switched itself off and live strategies were paused. Paper keeps running.") in lines
    assert not any(line.startswith('Nothing trades real money until') for line in lines)


@pytest.mark.parametrize('customer,charge', [
    # The card wall reads this before a card is saved: auto-reload is on by default, at the default amount.
    (None, None),
    ({'stripe_customer_id': 'cus_fixture', 'default_pm_id': None, 'auto_reload': 1, 'reload_amount': 40, 'reload_threshold': 10}, 42.20),
])
def test_billing_states_what_one_auto_reload_charges_the_card(monkeypatch, customer, charge):
    from decimal import Decimal
    monkeypatch.setattr(server.billing, 'configured', lambda: True)
    monkeypatch.setattr(server.billing, 'TOPUP_FEE', Decimal('0.055'))
    monkeypatch.setattr(server.billing, 'list_cards', lambda *a: [])
    monkeypatch.setattr(server.repo, 'get_stripe_customer', lambda *a: customer)
    monkeypatch.setattr(server.repo, 'credit_totals', lambda *a: _totals(bonus=20.0))
    monkeypatch.setattr(server.repo, 'credit_spent_total', lambda *a, **k: 0.0)
    monkeypatch.setattr(server.repo, 'credit_statement', lambda *a: [])
    monkeypatch.setattr(server.repo, 'usage_by_source', lambda *a: dict(_NO_USAGE))
    data = server.billing_state(context())
    # Credits plus the top-up fee, the same sum billing.auto_reload charges; never the bare credit amount.
    expected = charge if charge is not None else float(server.billing.AUTORELOAD_AMOUNT * Decimal('1.055'))
    assert data['autoreload_charge'] == pytest.approx(expected, abs=0.005)
    assert data['autoreload_charge'] > data['autoreload_amount']
