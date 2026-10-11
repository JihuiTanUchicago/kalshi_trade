"""Tests for sim_repository.py functions that aren't already covered via
process_model_tick in test_sim_engine.py."""
from data_pipeline.sim_repository import best_bid_snapshot


class _TimeAwareForwardQuotesCursor:
    """Distinguishes 'no quote at/before as_of_ts' from 'no quote ever' -
    FakeCursor in conftest.py doesn't model time, so this is a narrower
    purpose-built fake just for best_bid_snapshot's fallback behavior."""

    def __init__(self, rows_before_cutoff, rows_ever):
        self.rows_before_cutoff = rows_before_cutoff
        self.rows_ever = rows_ever
        self._last = None

    def execute(self, sql, params):
        if len(params) == 2:  # as_of_ts-scoped query
            self._last = self.rows_before_cutoff
        else:  # unscoped "latest ever" query
            self._last = self.rows_ever

    def fetchone(self):
        return self._last[0] if self._last else None


def test_best_bid_snapshot_falls_back_to_last_ever_quote_when_none_before_cutoff():
    import datetime

    cur = _TimeAwareForwardQuotesCursor(
        rows_before_cutoff=[],  # nothing at/before as_of_ts
        rows_ever=[{"yes_bid_dollars": 0.97, "yes_bid_size_fp": 50.0, "raw_json": None}],
    )
    snap = best_bid_snapshot(cur, "OLD-TICKER", as_of_ts=datetime.datetime(2026, 1, 1))
    assert snap["bid"] == 0.97, "should fall back to the last-ever quote instead of pricing the exit at $0"


def test_best_bid_snapshot_uses_scoped_quote_when_available():
    import datetime

    cur = _TimeAwareForwardQuotesCursor(
        rows_before_cutoff=[{"yes_bid_dollars": 0.50, "yes_bid_size_fp": 10.0, "raw_json": None}],
        rows_ever=[{"yes_bid_dollars": 0.97, "yes_bid_size_fp": 50.0, "raw_json": None}],
    )
    snap = best_bid_snapshot(cur, "TICKER", as_of_ts=datetime.datetime(2026, 1, 1))
    assert snap["bid"] == 0.50, "should not fall back when a scoped quote actually exists"


def test_best_bid_snapshot_no_fallback_when_truly_no_data_at_all():
    import datetime

    cur = _TimeAwareForwardQuotesCursor(rows_before_cutoff=[], rows_ever=[])
    snap = best_bid_snapshot(cur, "NEVER-SEEN", as_of_ts=datetime.datetime(2026, 1, 1))
    assert snap["bid"] is None
