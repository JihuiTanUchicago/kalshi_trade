"""The agents worker keeps one lane for chats and reviews, so hour-long research runs on every
regular thread can't leave a user's message (or the autopilot review) waiting in the queue."""
from contextlib import contextmanager

from app import repository as repo
from app import worker


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append(sql)

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self):
        self.cur = _Cur()

    def begin(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def cursor(self):
        return self.cur


def test_claim_run_filters_research_only_on_the_interactive_lane():
    c = _Conn()
    assert repo.claim_run(c, "w", skip_research=True) is None
    assert "kind <> 'research'" in c.cur.sql[0]
    c = _Conn()
    repo.claim_run(c, "w")
    assert "kind" not in c.cur.sql[0]


def test_main_starts_the_interactive_lanes(monkeypatch):
    started = []

    class T:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            started.append((self.target, self.args))

        def join(self):
            pass

    monkeypatch.setattr(worker.threading, "Thread", T)
    monkeypatch.setattr(worker.signal, "signal", lambda *a: None)
    monkeypatch.setattr(worker, "CONCURRENCY", 2)
    monkeypatch.setattr(worker, "INTERACTIVE_LANES", 1)
    monkeypatch.setattr(worker.sys, "argv", ["worker", "agents"])
    worker.main()
    lanes = [a for t, a in started if t is worker.agent_loop]
    assert len(lanes) == 3
    assert [len(a) == 2 and a[1] is True for a in lanes] == [False, False, True]
    assert lanes[2][0].endswith(":chat0")
