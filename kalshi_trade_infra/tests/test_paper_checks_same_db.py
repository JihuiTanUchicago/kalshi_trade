"""The paper -> live evidence and the Deploy board's checks say exactly what they said, against a real
MySQL. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).

One account holds three paper strategies whose realistic paper records clear the trade, event and hour
counts (a steady winner, a winner that has faded, a loser), plus instant fills the record leaves out.
- agent.paper_evidence, the live gate's evidence, gives the same dict, every figure, with the bootstrap
  that walks only its new blocks and with the per-point loop it replaced (reference_ci).
- The board's checks are the same read in the request, warmed at startup (warm_deploy_boards), served
  from a lapsed answer while the background worker reads it again, and after that read.
- The user's own stop drops the kept answers, so the next board asks the gate again.
"""
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


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


@pytest.fixture(scope="module")
def book(conn):
    """{uid, user, sids, deps}: three paper strategies' records, 60-130 trades each over ~10 days."""
    from app import repository as repo
    from app.trading import spec as specmod

    rng = random.Random(464)
    cur = conn.cursor()
    user = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "checks@example.invalid", "Checks", None)
    uid = user["id"]
    sids, deps = [], {}
    for k, (edge, fade, n) in enumerate([(0.12, False, 130), (0.10, True, 90), (-0.05, False, 60)]):
        spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 4}})
        result = {"capital": 40.0, "out_of_sample": {"trades": 40, "pnl": 6.0}}
        sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", "Checks %d" % k, "t", spec, "passed", result)
        dep = repo.create_deployment(cur, uid, sid, "btc15m", "paper")
        sids.append(sid)
        deps[sid] = dep
        start = NOW - timedelta(days=10)
        for i in range(n):
            opened = start + timedelta(minutes=105 * i + rng.randint(0, 30))
            closed = opened + timedelta(minutes=rng.randint(5, 14))
            p_win = 0.5 + (edge if not (fade and i > n // 2) else -0.15)
            qty, entry = rng.randint(1, 8), round(rng.uniform(0.2, 0.8), 2)
            won = rng.random() < p_win
            fee = round(0.07 * qty * entry * (1 - entry) + 0.01, 4)
            pnl = round(qty * ((1.0 if won else 0.0) - entry) - fee, 4)
            # Strikes of one event share its ticker minus the strike; every third trip adds a second strike.
            event = "KXBTC15M-%s" % opened.strftime("%y%b%d%H%M").upper()
            for strike in ((100,) if i % 3 else (100, 102)):
                repo.insert_closed_position(cur, dep, uid, "paper", "%s-T%d" % (event, strike), "yes", qty, entry, fee,
                                            1.0 if won else 0.0, 0.0, pnl, "settled", closed, order_ref="sim:" + uuid.uuid4().hex,
                                            opened_at=opened, closed_at=closed)
            if i % 25 == 0:  # an instant fill: counted by the legacy check, left out of the realistic record
                repo.insert_closed_position(cur, dep, uid, "paper", "%s-T99" % event, "yes", 1, 0.5, 0.01, 1.0, 0.0, 0.49,
                                            "settled", closed, order_ref="paper:" + uuid.uuid4().hex,
                                            opened_at=opened, closed_at=closed)
    return {"uid": uid, "user": repo.get_user(cur, uid), "sids": sids, "deps": deps}


def _board(conn, user):
    from app import server

    server._ROADS.clear()
    out = server.list_deployments(server.Ctx(conn, user, (), {}, {}, None))
    return {d["strategy_id"]: (d["road"]["trades"], d["road"]["events"], d["road"]["span_hours"], d["road"].get("failing"))
            for d in out["deployments"] if d.get("road")}


def test_the_gates_evidence_is_the_loops_on_a_seeded_paper_book(conn, book, monkeypatch):
    from app.research import stats
    from app.research import agent
    from tests.test_stats_bootstrap_exact import reference_ci

    cur = conn.cursor()
    fast, loop = {}, {}
    for sid in book["sids"]:
        agent._EDGE_P.clear()
        fast[sid] = agent.paper_evidence(cur, book["uid"], sid)
    with monkeypatch.context() as m:
        m.setattr(stats, "stationary_bootstrap_ci", reference_ci)
        for sid in book["sids"]:
            agent._EDGE_P.clear()
            loop[sid] = agent.paper_evidence(cur, book["uid"], sid)
    agent._EDGE_P.clear()
    assert fast == loop
    # The book is one the edge test decides: every record is long enough, and they don't all agree.
    assert all(ev["p_value"] is not None for ev in fast.values())
    assert {ev["checks"]["edge"] for ev in fast.values()} == {True, False}


def test_the_boards_checks_are_the_same_however_they_are_read(conn, book, monkeypatch):
    from app import repository as repo, server
    from app.research import agent
    from app.services import paper_checks

    uid, user = book["uid"], book["user"]
    calls = []
    gate = agent.paper_evidence
    monkeypatch.setattr(agent, "paper_evidence", lambda cur, u, sid: calls.append(sid) or gate(cur, u, sid))
    monkeypatch.setattr(paper_checks, "WORKER_IDLE", 0.05)
    paper_checks.KEPT.clear()
    agent._EDGE_P.clear()
    fresh = _board(conn, user)
    assert sorted(fresh) == sorted(book["sids"]) and all(r[3] is not None for r in fresh.values())
    assert len(calls) == 3

    # Warmed at startup: the board then reads no gate at all.
    assert uid in repo.paper_board_users(conn.cursor(), 10_000)
    monkeypatch.setattr(server.repo, "paper_board_users", lambda cur, limit: [uid])
    paper_checks.KEPT.clear()  # a fresh process
    server._ROADS.clear()
    agent._EDGE_P.clear()
    assert server.warm_deploy_boards() == 1 and len(calls) == 6
    assert _board(conn, user) == fresh and len(calls) == 6

    # Lapsed: the kept answers are served while the worker reads them again on its own connection.
    for key in [k for k in paper_checks.KEPT if k[0] == uid]:
        at, val = paper_checks.KEPT[key]
        paper_checks.KEPT[key] = (at - paper_checks.FAILING_TTL - 1, val)
    monkeypatch.setitem(paper_checks._BACKGROUND, "on", True)
    assert _board(conn, user) == fresh
    end = time.time() + 30
    while (paper_checks._PENDING or len(calls) < 9) and time.time() < end:
        time.sleep(0.02)
    assert len(calls) == 9 and not paper_checks._PENDING
    assert all(time.time() - paper_checks.KEPT[k][0] < paper_checks.FAILING_TTL for k in paper_checks.KEPT if k[0] == uid)
    assert _board(conn, user) == fresh and len(calls) == 9

    # The user's own pause drops what was kept for that strategy: the next board asks its gate again.
    faded, loser = book["sids"][1], book["sids"][2]
    server.deployment_action(server.Ctx(conn, user, (str(book["deps"][faded]), "pause"), {}, {}, None))
    assert sorted(k[1] for k in paper_checks.KEPT if k[0] == uid) == sorted(set(book["sids"]) - {faded})
    assert _board(conn, user) == fresh and calls[9:] == [faded]
    # And a stop takes the strategy off the board.
    server.deployment_action(server.Ctx(conn, user, (str(book["deps"][loser]), "stop"), {}, {}, None))
    after = _board(conn, user)
    assert after == {s: r for s, r in fresh.items() if s != loser} and len(calls) == 10
    worker = paper_checks._BACKGROUND["worker"]
    if worker is not None:
        worker.join(5)
    paper_checks.KEPT.clear()
