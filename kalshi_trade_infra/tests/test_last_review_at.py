from datetime import datetime

from app import repository as repo


class _StubCursor:
    """Returns one canned row (or None) for the single SELECT last_review_at runs."""

    def __init__(self, row):
        self.row = row

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self.row


def test_last_review_at_returns_latest_review_timestamp():
    dt = datetime(2026, 10, 18, 9, 0, 0)
    assert repo.last_review_at(_StubCursor({"created_at": dt}), 7) == dt


def test_last_review_at_none_when_no_review_yet():
    assert repo.last_review_at(_StubCursor(None), 7) is None


def test_active_agent_run_reads_the_oldest_queued_or_running_chat_or_review():
    seen = []

    class _Cur(_StubCursor):
        def execute(self, sql, params):
            seen.append((sql, params))

    row = {"id": 3, "kind": "review", "status": "queued", "created_at": None, "heartbeat_at": None}
    assert repo.active_agent_run(_Cur(row), 7, "review") == row
    assert repo.active_agent_run(_Cur(None), 7) is None
    (one, p1), (both, p2) = seen
    assert "kind=%s" in one and p1 == (7, "review")
    assert "kind IN ('chat','review')" in both and p2 == (7,)
    for sql in (one, both):
        assert "status IN ('queued','running')" in sql and "heartbeat_at" in sql and "ORDER BY id LIMIT 1" in sql


def test_research_queue_ahead_counts_queued_research_with_a_lower_id():
    seen = []

    class _Cur(_StubCursor):
        def execute(self, sql, params):
            seen.append((sql, params))

    assert repo.research_queue_ahead(_Cur({"n": 2}), 41) == 2
    sql, params = seen[0]
    assert "kind='research'" in sql and "status='queued'" in sql and "id<%s" in sql and params == (41,)
