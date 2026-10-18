"""The 'Kept' default view hides rejected/void without deleting rows (ledger stays intact)."""
from app.repository import _strategy_filter_sql, NOISE_STATUSES


def test_hide_noise_excludes_rejected_and_void_by_default():
    sql, params = _strategy_filter_sql(None, None, None, None, None, False, hide_noise=True)
    assert "s.status NOT IN" in sql
    for s in NOISE_STATUSES:
        assert s in params  # the excluded statuses are bound, not interpolated


def test_explicit_status_overrides_hide_noise():
    # Picking a specific status (e.g. the Rejected chip) must SHOW it — no NOT IN clause.
    sql, params = _strategy_filter_sql(None, "rejected", None, None, None, False, hide_noise=True)
    assert "NOT IN" not in sql
    assert "s.status=%s" in sql and "rejected" in params


def test_hide_noise_off_lists_everything():
    sql, _ = _strategy_filter_sql(None, None, None, None, None, False, hide_noise=False)
    assert "NOT IN" not in sql
