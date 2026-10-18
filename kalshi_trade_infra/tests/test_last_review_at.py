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
