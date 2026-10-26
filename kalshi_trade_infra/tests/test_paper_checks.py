"""The Deploy board's paper -> live checks (services.paper_checks) and the startup warm-up of its boards.

The answer is agent.paper_evidence's, unchanged; what moves is when it is read. A lapsed answer is
served while one background worker reads it again (only once the web server turns that on), the
user's own change drops every answer kept for them, and the boards are read once at startup so the
first one after a deploy doesn't run every gate bootstrap cold. Nothing here starts a thread unless
the test asks for it.
"""
import threading
import time
from types import SimpleNamespace

import pytest

from app import agent
from app.services import paper_checks

REC = (55, 40, 72.0)  # trades, events, hours


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    paper_checks.KEPT.clear()
    paper_checks._GEN.clear()
    paper_checks._PENDING.clear()
    monkeypatch.setitem(paper_checks._BACKGROUND, "on", False)
    monkeypatch.setattr(paper_checks, "WORKER_IDLE", 0.05)  # a worker a test starts exits right after
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: sid != 9)
    yield
    worker = paper_checks._BACKGROUND["worker"]
    if isinstance(worker, threading.Thread):
        worker.join(5)
        assert not worker.is_alive()
    paper_checks.KEPT.clear()


def _gate(answers, calls):
    """paper_evidence giving each strategy's checks from `answers`, noting which cursor asked."""
    def evidence(cur, uid, sid):
        calls.append((cur, uid, sid))
        return {"checks": dict(answers[sid])}
    return evidence


def _age(key, seconds):
    at, val = paper_checks.KEPT[key]
    paper_checks.KEPT[key] = (at - seconds, val)


def test_the_answer_is_the_gates_and_is_kept_until_the_record_moves(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "paper_evidence", _gate({8: {"net_pnl": True, "edge": False, "demo": False},
                                                        9: {"edge": True}}, calls))
    assert paper_checks.failing("cur", 1, 8, REC) == ["edge", "demo"]
    assert paper_checks.failing("cur", 1, 9, REC) == ["candidate"]  # the gatekeeper hasn't promoted it
    assert paper_checks.failing("cur", 1, 8, REC) == ["edge", "demo"] and len(calls) == 2
    paper_checks.failing("cur", 1, 8, (56, 41, 73.0))  # a trade closed: asked again
    assert len(calls) == 3


def test_off_the_web_server_a_lapsed_answer_is_read_in_the_request(monkeypatch):
    calls = []
    answers = {8: {"edge": False}}
    monkeypatch.setattr(agent, "paper_evidence", _gate(answers, calls))
    before = threading.active_count()
    paper_checks.failing("cur", 1, 8, REC)
    _age((1, 8) + REC, paper_checks.FAILING_TTL + 1)
    answers[8] = {"edge": True}
    assert paper_checks.failing("cur", 1, 8, REC) == [] and len(calls) == 2
    assert paper_checks._BACKGROUND["worker"] is None and threading.active_count() == before


def _fake_db(monkeypatch, conns):
    import data_pipeline.common as common

    def connect():
        c = SimpleNamespace(closed=False, cursor=lambda: "worker-cur")
        c.close = lambda: setattr(c, "closed", True)
        conns.append(c)
        return c
    monkeypatch.setattr(common, "get_db_conn", connect)


def _drain(timeout=5.0):
    end = time.time() + timeout
    while (paper_checks._PENDING or not paper_checks._QUEUE.empty()) and time.time() < end:
        time.sleep(0.01)
    assert not paper_checks._PENDING


def test_a_lapsed_answer_is_served_while_the_worker_reads_it_again(monkeypatch):
    calls, conns = [], []
    answers = {8: {"edge": False, "demo": False}}
    monkeypatch.setattr(agent, "paper_evidence", _gate(answers, calls))
    _fake_db(monkeypatch, conns)
    paper_checks.start()
    paper_checks.failing("req-cur", 1, 8, REC)
    _age((1, 8) + REC, paper_checks.FAILING_TTL + 1)
    answers[8] = {"edge": True, "demo": False}
    # The request gets the kept answer at once; the worker reads it on its own connection.
    assert paper_checks.failing("req-cur", 1, 8, REC) == ["edge", "demo"]
    _drain()
    assert calls[-1] == ("worker-cur", 1, 8)
    assert paper_checks.failing("req-cur", 1, 8, REC) == ["demo"] and len(calls) == 2
    # The worker lets its connection go once the queue is empty.
    end = time.time() + 5
    while not conns[-1].closed and time.time() < end:
        time.sleep(0.01)
    assert conns and all(c.closed for c in conns)


def test_an_answer_past_stale_max_is_read_in_the_request(monkeypatch):
    calls = []
    answers = {8: {"edge": False}}
    monkeypatch.setattr(agent, "paper_evidence", _gate(answers, calls))
    paper_checks.start()
    paper_checks.failing("cur", 1, 8, REC)
    _age((1, 8) + REC, paper_checks.STALE_MAX + 1)
    answers[8] = {"edge": True}
    assert paper_checks.failing("cur", 1, 8, REC) == [] and calls[-1][0] == "cur"
    assert not paper_checks._PENDING


def test_a_full_queue_reads_in_the_request(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "paper_evidence", _gate({8: {"edge": False}}, calls))
    monkeypatch.setattr(paper_checks, "_QUEUE", __import__("queue").Queue(maxsize=1))
    paper_checks._QUEUE.put_nowait(((2, 2), 0))  # a refresh already waiting
    monkeypatch.setitem(paper_checks._BACKGROUND, "worker", SimpleNamespace(is_alive=lambda: True))
    paper_checks.start()
    paper_checks.failing("cur", 1, 8, REC)
    _age((1, 8) + REC, paper_checks.FAILING_TTL + 1)
    paper_checks.failing("cur", 1, 8, REC)
    assert [c[0] for c in calls] == ["cur", "cur"]


def test_a_failing_refresh_is_logged_and_the_kept_answer_stays(monkeypatch, capsys):
    conns = []
    _fake_db(monkeypatch, conns)
    state = {"fail": False}

    def evidence(cur, uid, sid):
        if state["fail"]:
            raise RuntimeError("database went away")
        return {"checks": {"edge": False}}
    monkeypatch.setattr(agent, "paper_evidence", evidence)
    paper_checks.start()
    paper_checks.failing("cur", 1, 8, REC)
    _age((1, 8) + REC, paper_checks.FAILING_TTL + 1)
    state["fail"] = True
    assert paper_checks.failing("cur", 1, 8, REC) == ["edge"]
    _drain()
    assert "database went away" in capsys.readouterr().err
    assert paper_checks.KEPT[(1, 8) + REC][1] == ["edge"] and all(c.closed for c in conns)


def test_the_users_own_change_drops_their_answers_and_a_read_under_way(monkeypatch):
    monkeypatch.setattr(agent, "paper_evidence", _gate({8: {"edge": False}, 7: {"edge": False}, 5: {"edge": False}}, []))
    for uid, sid in ((1, 8), (1, 7), (2, 5)):
        paper_checks.failing("cur", uid, sid, REC)
    gen = paper_checks._GEN.get(1, 0)  # a read of user 1's that began before the change
    paper_checks.forget(1, 8)  # a change to strategy 8's deployment: only its evidence reads it
    assert set(paper_checks.KEPT) == {(1, 7) + REC, (2, 5) + REC}
    paper_checks._keep((1, 8) + REC, ["edge"], gen)
    assert (1, 8) + REC not in paper_checks.KEPT
    paper_checks.forget(1)  # a change that may touch any of them
    assert set(paper_checks.KEPT) == {(2, 5) + REC}


def test_every_change_the_user_makes_on_the_board_forgets_it(monkeypatch):
    from app import server

    forgot = []
    monkeypatch.setattr(server.paper_checks, "forget", lambda uid, sid=None: forgot.append((uid, sid)))
    server._ROADS[(1, (8,), ((2, "running"),))] = (time.time(), {8: {"failing": ["edge"]}})
    server._ROADS[(2, (5,), ((3, "running"),))] = (time.time(), {5: {}})
    monkeypatch.setattr(server.repo, "get_deployment", lambda cur, uid, i: {"id": i, "strategy_id": 8, "status": "running",
                                                                            "mode": "paper", "spec": {}, "market": "btc15m"})
    monkeypatch.setattr(server.repo, "set_deployment_status", lambda *a: None)
    monkeypatch.setattr(server.repo, "set_autopilot_live", lambda *a: None)
    monkeypatch.setattr(server.repo, "list_deployments", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "add_chat", lambda *a: None)
    conn = SimpleNamespace(cursor=lambda: None)
    user = {"id": 1}
    server.deployment_action(server.Ctx(conn, user, ("2", "stop"), {}, {}, None))
    assert forgot == [(1, 8)] and set(server._ROADS) == {(2, (5,), ((3, "running"),))}
    server.autopilot_kill(server.Ctx(conn, user, (), {}, {}, None))
    assert forgot == [(1, 8), (1, None)]
    server._ROADS.clear()
    # Deploy, proposal decisions and removal take the same step (their guards need more setup).
    import inspect
    for fn, call in ((server.create_deployment, '_forget_own_change(ctx.uid, s["id"])'),
                     (server.delete_strategy, '_forget_own_change(ctx.uid, s["id"])'),
                     (server.decide_proposal, "_forget_own_change(ctx.uid)")):
        assert call in inspect.getsource(fn), fn.__name__


def test_the_boards_are_read_at_startup_within_their_bounds(monkeypatch):
    from app import server

    conns, read, logged = [], [], []
    import app.server as srv
    monkeypatch.setattr(srv, "get_db_conn", lambda: conns.append(SimpleNamespace(
        cursor=lambda: "warm-cur", close=lambda: conns.append("closed"))) or conns[-1])
    monkeypatch.setattr(server.repo, "paper_board_users", lambda cur, limit: [1, 2, 3, 4][:limit])
    monkeypatch.setattr(server.book_memo, "deployments_for_display", lambda memo: [{"uid": memo.uid}])
    monkeypatch.setattr(server, "_log_line", logged.append)
    monkeypatch.setattr(server.time, "sleep", lambda s: None)

    def roads(cur, uid, deps, memo):
        assert memo.uid == uid  # the board's position sums are read through its memo
        if uid == 2:
            raise RuntimeError("boom")
        read.append((cur, uid, deps))
    monkeypatch.setattr(server, "_deploy_roads", roads)
    assert server.warm_deploy_boards(limit=3) == 2  # user 2's failure is logged and skipped
    assert read == [("warm-cur", 1, [{"uid": 1}]), ("warm-cur", 3, [{"uid": 3}])]
    assert conns[-1] == "closed" and logged[0] == "[app] warming user 2's Deploy board failed (RuntimeError)"
    assert logged[1].startswith("[app] warmed 2 Deploy board(s) in ")
    read.clear()
    assert server.warm_deploy_boards(budget=-1) == 0 and read == []  # out of time before the first
    monkeypatch.setattr(srv, "get_db_conn", lambda: (_ for _ in ()).throw(OSError("no database")))
    assert server.warm_deploy_boards() == 0 and logged[-2] == "[app] warming the Deploy boards failed (OSError)"


def test_importing_the_server_starts_no_background_work():
    from app import server  # noqa: F401

    names = {t.name for t in threading.enumerate()}
    assert "warm-deploy-boards" not in names and "paper-checks" not in names
    assert paper_checks._BACKGROUND["on"] is False
