from app import schema


class _StubCur:
    """Returns a canned information_schema count; records executed SQL."""
    def __init__(self, count):
        self.count = count
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append(sql)

    def fetchone(self):
        return {"c": self.count}


def test_add_index_creates_when_missing():
    cur = _StubCur(0)   # index absent
    schema._add_index_if_missing(cur, "hist_markets", "idx_x", "ALTER TABLE hist_markets ADD INDEX idx_x (a)")
    assert any("ADD INDEX idx_x" in s for s in cur.calls)   # the DDL ran


def test_add_index_skips_when_present():
    cur = _StubCur(1)   # index already exists
    schema._add_index_if_missing(cur, "hist_markets", "idx_x", "ALTER TABLE hist_markets ADD INDEX idx_x (a)")
    assert not any("ADD INDEX" in s for s in cur.calls)     # no-op on re-run
