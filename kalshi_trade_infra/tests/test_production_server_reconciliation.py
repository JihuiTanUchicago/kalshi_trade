"""Production behavior survives the broker/paper release; no live services."""
from types import SimpleNamespace

import pymysql
import pytest

from app import agent, schema, server
from app import models_catalog as catalog


def context(body=None, query=None):
    return server.Ctx(SimpleNamespace(cursor=lambda: object()), {'id': 17}, (), query or {}, body or {}, None)


@pytest.mark.parametrize('open_signup,expected', [(False, False), (True, True)])
def test_google_creation_retains_deployed_signup_gate(monkeypatch, open_signup, expected):
    observed = []
    monkeypatch.setattr(server, 'OPEN_SIGNUP', open_signup)
    monkeypatch.setattr(server.repo, 'pop_oauth_state', lambda *args: {'code_verifier': 'fixture', 'nonce': 'fixture'})
    monkeypatch.setattr(server.auth, 'exchange_code', lambda *args: {
        'sub': 'synthetic', 'email': 'synthetic@example.test', 'name': 'Synthetic', 'picture': None})
    monkeypatch.setattr(server.repo, 'is_waitlist_approved', lambda *args: False)
    monkeypatch.setattr(server.repo, 'upsert_google_user', lambda *args, **kw: observed.append(kw['allow_new']))
    assert server.google_callback(context(query={'state': 'fixture', 'code': 'fixture'})) == ('redirect', '/signin?pending=1')
    assert observed == [expected]


@pytest.mark.parametrize('key', [catalog.DEFAULT_KEY, 'sonnet-4-5', ''])
def test_autopilot_model_is_owner_scoped_and_defaults_explicitly(monkeypatch, key):
    observed = []
    monkeypatch.setattr(server.repo, 'set_autopilot_model', lambda cur, uid, model: observed.append((uid, model)))
    assert server.autopilot_model(context({'model': key})) == {'ok': True, 'model': key or catalog.DEFAULT_KEY}
    assert observed == [(17, key or None)]
    route = next(row for row in server.ROUTES if row[2] is server.autopilot_model)
    assert route[0] == 'POST' and route[3] is True


def test_unknown_model_cannot_update_preferences(monkeypatch):
    monkeypatch.setattr(server.repo, 'set_autopilot_model', lambda *args: pytest.fail('Invalid choice persisted'))
    with pytest.raises(server.ApiError) as error:
        server.autopilot_model(context({'model': 'unknown-provider-model'}))
    assert error.value.status == 400


def test_data_load_relabels_only_known_failures():
    with pytest.raises(agent.LLMError, match='busy'):
        agent._load('fixture', lambda: (_ for _ in ()).throw(pymysql.OperationalError(2013, 'Lost connection')))
    with pytest.raises(KeyError, match='programming bug'):
        agent._load('fixture', lambda: (_ for _ in ()).throw(KeyError('programming bug')))
    assert agent._load('fixture', lambda: 42) == 42


def test_existing_index_migration_never_recreates_or_drops_it():
    class Cursor:
        def __init__(self, exists):
            self.exists, self.calls = exists, []

        def execute(self, *args):
            self.calls.append(args)

        def fetchone(self):
            return {'c': self.exists}

    for exists in (0, 1):
        cur = Cursor(exists)
        schema._add_index_if_missing(cur, 'hist_markets', 'idx_hist_candles_series', 'ALTER fixture')
        assert len(cur.calls) == (2 if not exists else 1)
    assert any('app_broker_connections' in ddl for ddl in schema.DDL)
    assert any('app_alpaca_paper_orders' in ddl for ddl in schema.DDL)
