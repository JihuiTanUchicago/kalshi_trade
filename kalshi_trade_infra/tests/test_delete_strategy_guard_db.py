"""A strategy can't be deleted while any of its deployments still holds an open position, against a
real MySQL. Stopping a deployment leaves its positions open, and the engine settles and flattens
positions through their strategy row: a strategy deleted first left its positions open for good,
with paper cash already paid for them. The admin page counts any such orphans already in the data.
Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

RESULT = {"capital": 40.0, "out_of_sample": {"trades": 40, "pnl": 6.0, "win_rate": 0.61},
          "in_sample": {"trades": 90, "pnl": 30.0, "win_rate": 0.7}}


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.cursor().execute("UPDATE app_deployments SET status='stopped' WHERE user_id IN "
                       "(SELECT id FROM app_users WHERE google_sub LIKE 'test:%%')")
    c.close()


def _user(cur, repo, name):
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "%s@example.com" % name, name, None)["id"]
    return uid, repo.get_user(cur, uid)


def _strategy(cur, repo, uid, title):
    from app import spec as specmod

    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "exit": {"stop_loss": 0.1},
                             "sizing": {"stake": 10.0, "max_positions": 4}})
    return repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", title, "t", spec, "passed", dict(RESULT))


def _ctx(conn, user):
    from app import server

    def ctx(*params, body=None):
        return server.Ctx(conn, user, tuple(str(p) for p in params), {}, body or {}, None)
    return ctx


def test_delete_waits_until_every_deployments_positions_close(conn, monkeypatch):
    from app import engine, server
    from app import repository as repo

    cur = conn.cursor()
    uid, user = _user(cur, repo, "guard")
    ctx = _ctx(conn, user)
    monkeypatch.setattr(server, "_freshness", lambda c: {})
    sid = _strategy(cur, repo, uid, "Guarded")
    deps = {m: repo.create_deployment(cur, uid, sid, "btc15m", m) for m in ("paper", "demo", "live")}
    tag = uuid.uuid4().hex[:8].upper()
    due = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    tickers = {k: "BKG%s-%s" % (tag, k) for k in ("P1", "P2", "L1")}
    # Two paper positions and a live one; demo holds nothing (a mode with none is left out of the message).
    for key, mode in (("P1", "paper"), ("P2", "paper"), ("L1", "live")):
        repo.insert_position(cur, deps[mode], uid, mode, tickers[key], "yes", 10, 0.40, 0.07, due,
                             order_ref="sim:%s" % key)

    # Running: the old guard still answers first.
    with pytest.raises(server.ApiError) as running:
        server.delete_strategy(ctx(sid))
    assert running.value.status == 409 and "Stop this strategy's deployment" in running.value.message
    for did in deps.values():
        server.deployment_action(ctx(did, "stop"))
    assert server.list_deployments(ctx())["deployments"] == []  # nothing is deployed any more

    def refused():
        with pytest.raises(server.ApiError) as e:
            server.delete_strategy(ctx(sid))
        assert e.value.status == 409
        return e.value.message

    three = "This strategy still holds 3 open positions (paper: 2, live: 1). They'll close at settlement; delete it after that."
    assert refused() == three
    assert server.get_strategy(ctx(sid))["delete_block"] == three  # the Remove button's reason, same words
    assert repo.get_strategy(cur, uid, sid) is not None

    def settle(*keys):
        got = {tickers[k]: "yes" for k in keys}
        engine.settle_due(conn, engine.MARKETS["btc15m"], engine.Sources(result=got.get), datetime.now(timezone.utc))

    settle("P1")
    two = "This strategy still holds 2 open positions (paper: 1, live: 1). They'll close at settlement; delete it after that."
    assert refused() == two == server.get_strategy(ctx(sid))["delete_block"]
    settle("P2")
    one = "This strategy still holds 1 open position (live: 1). They'll close at settlement; delete it after that."
    assert refused() == one == server.get_strategy(ctx(sid))["delete_block"]
    settle("L1")
    assert server.get_strategy(ctx(sid))["delete_block"] is None
    assert server.delete_strategy(ctx(sid)) == {"ok": True}
    assert repo.get_strategy(cur, uid, sid) is None


def test_another_users_positions_never_block_a_delete(conn, monkeypatch):
    from app import server
    from app import repository as repo

    cur = conn.cursor()
    uid, user = _user(cur, repo, "mine")
    other, _ = _user(cur, repo, "theirs")
    ctx = _ctx(conn, user)
    monkeypatch.setattr(server, "_freshness", lambda c: {})
    sid = _strategy(cur, repo, uid, "Clear")
    did = repo.create_deployment(cur, uid, sid, "btc15m", "paper")
    close = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)
    # A closed position of its own doesn't block it.
    repo.insert_closed_position(cur, did, uid, "paper", "BKC%s" % uuid.uuid4().hex[:8].upper(), "yes", 10, 0.40, 0.07,
                                1.0, 0.0, 5.53, "settled", close)
    theirs = repo.create_deployment(cur, other, _strategy(cur, repo, other, "Theirs"), "btc15m", "paper")
    repo.insert_position(cur, theirs, other, "paper", "BKT%s" % uuid.uuid4().hex[:8].upper(), "yes", 10, 0.40, 0.07, close)
    server.deployment_action(ctx(did, "stop"))
    assert server.get_strategy(ctx(sid))["delete_block"] is None
    assert server.delete_strategy(ctx(sid)) == {"ok": True}


def test_the_admin_page_counts_open_positions_whose_strategy_is_gone(conn, monkeypatch):
    """Strategies deleted before the guard: their stopped deployments' open positions are counted, by
    mode, fleet-wide. A strategy that still exists, or a closed position, is never counted."""
    from app import server
    from app import repository as repo

    cur = conn.cursor()
    before = repo.orphaned_open_positions(cur)
    uid, user = _user(cur, repo, "orphans")
    ctx = _ctx(conn, user)
    tag = uuid.uuid4().hex[:8].upper()
    soon = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)
    later = soon + timedelta(hours=2)

    gone = _strategy(cur, repo, uid, "Deleted before the guard")
    paper = repo.create_deployment(cur, uid, gone, "btc15m", "paper")
    demo = repo.create_deployment(cur, uid, gone, "btc15m", "demo")
    repo.insert_position(cur, paper, uid, "paper", "BKO%s-A" % tag, "yes", 10, 0.40, 0.07, later)
    repo.insert_position(cur, demo, uid, "demo", "BKO%s-B" % tag, "yes", 5, 0.30, 0.04, soon)
    repo.insert_position(cur, demo, uid, "demo", "BKO%s-C" % tag, "no", 4, 0.50, 0.04, later)
    repo.insert_closed_position(cur, paper, uid, "paper", "BKO%s-D" % tag, "yes", 10, 0.40, 0.07, 1.0, 0.0, 5.53,
                                "settled", soon)
    kept = _strategy(cur, repo, uid, "Still here")
    alive = repo.create_deployment(cur, uid, kept, "btc15m", "live")
    repo.insert_position(cur, alive, uid, "live", "BKO%s-E" % tag, "yes", 3, 0.60, 0.03, soon)
    for did in (paper, demo, alive):
        assert repo.set_deployment_status(cur, uid, did, "stopped")
    assert repo.orphaned_open_positions(cur) == before  # nothing is orphaned while the strategy exists

    assert repo.delete_strategy(cur, uid, gone)  # the row only, as delete_strategy allowed before the guard
    after = repo.orphaned_open_positions(cur)

    def mode(o, m, k):
        return (o["by_mode"].get(m) or {}).get(k) or 0

    assert after["total"] - before["total"] == 3 and after["users"] - before["users"] == 1
    assert mode(after, "paper", "positions") - mode(before, "paper", "positions") == 1
    assert mode(after, "demo", "positions") - mode(before, "demo", "positions") == 2
    assert mode(after, "live", "positions") == mode(before, "live", "positions")  # its strategy still exists
    assert round(mode(after, "paper", "cost") - mode(before, "paper", "cost"), 2) == 4.0
    assert round(mode(after, "demo", "cost") - mode(before, "demo", "cost"), 2) == 3.5
    assert after["by_mode"]["demo"]["oldest_close"] <= soon
    assert after["total"] == sum(m["positions"] for m in after["by_mode"].values())

    # The admin page reads the same figure, for admins only.
    with pytest.raises(server.ApiError) as no:
        server.admin_overview(ctx())
    assert no.value.status == 403
    monkeypatch.setattr(server, "_require_admin", lambda c: None)
    assert server.admin_overview(ctx())["orphaned_open"] == after
