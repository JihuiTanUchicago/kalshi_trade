"""repo.largest_tables: admin storage-visibility readout (biggest tables by on-disk size)."""
from app import repository as repo


class _StubCursor:
    def __init__(self, rows, raise_on_execute=False):
        self._rows, self._raise = rows, raise_on_execute

    def execute(self, sql, params=()):
        if self._raise:
            raise RuntimeError("information_schema unavailable")

    def fetchall(self):
        return self._rows


def test_largest_tables_parses_rows_biggest_first():
    rows = [{"t": "markets", "mb": 129024}, {"t": "market_candles", "mb": 4096}, {"t": "hist_markets", "mb": 512}]
    out = repo.largest_tables(_StubCursor(rows))
    assert out == [{"table": "markets", "mb": 129024},
                   {"table": "market_candles", "mb": 4096},
                   {"table": "hist_markets", "mb": 512}]


def test_largest_tables_tolerates_null_mb():
    # information_schema can report NULL sizes for some engines; coerce to 0, never crash.
    out = repo.largest_tables(_StubCursor([{"t": "x", "mb": None}]))
    assert out == [{"table": "x", "mb": 0}]


def test_largest_tables_fails_open_to_empty():
    # Telemetry must never break the admin page: a query error yields [], not an exception.
    assert repo.largest_tables(_StubCursor([], raise_on_execute=True)) == []
