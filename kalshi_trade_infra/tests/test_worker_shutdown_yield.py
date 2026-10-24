"""A deploy's SIGTERM hands held research runs back to the queue without spending their resume
budget; reviews/chats are left to the reaper; the worker then exits."""
import pytest

from app import repository as repo
from app import worker


class _Cur:
    def __init__(self, rowcount=1):
        self.sql, self.rowcount = [], rowcount

    def execute(self, sql, params=()):
        self.sql.append((" ".join(sql.split()), params))


def test_yield_run_requeues_only_the_run_this_worker_holds_and_keeps_resume_budget():
    cur = _Cur()
    assert repo.yield_run(cur, 9, "host:1:0") is True
    sql, params = cur.sql[0]
    assert sql.startswith("UPDATE app_agent_runs SET status='queued', worker_id=NULL")
    assert "resume_count" not in sql, "a clean restart must not spend the crash resume budget"
    assert "WHERE id=%s AND status='running' AND worker_id=%s" in sql and params[1:] == (9, "host:1:0")
    assert any("INSERT INTO app_agent_events" in s or "app_agent_events" in s for s, _ in cur.sql[1:])


def test_yield_run_is_a_no_op_for_a_run_it_no_longer_holds():
    cur = _Cur(rowcount=0)
    assert repo.yield_run(cur, 9, "host:1:0") is False and len(cur.sql) == 1


def test_sigterm_yields_research_runs_then_exits(monkeypatch):
    yielded, closed = [], []

    class Conn:
        def cursor(self):
            return object()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(worker, "get_db_conn", lambda: Conn())
    monkeypatch.setattr(worker.repo, "yield_run", lambda cur, rid, wid: yielded.append((rid, wid)) or True)

    class Exit(Exception):
        pass

    def fake_exit(code):
        raise Exit(code)

    monkeypatch.setattr(worker.os, "_exit", fake_exit)
    monkeypatch.setattr(worker, "_HELD", {"w:0": {"id": 1, "kind": "research"}, "w:1": {"id": 2, "kind": "review"}})
    monkeypatch.setattr(worker, "_STOPPING", worker.threading.Event())
    with pytest.raises(Exit):
        worker._yield_on_sigterm(15, None)
    assert yielded == [(1, "w:0")], "only research runs are handed back"
    assert worker._STOPPING.is_set() and closed == [True]
