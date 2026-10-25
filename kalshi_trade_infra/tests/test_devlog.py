"""The Dev Logs tab is public: every signed-in user sees it."""
import re

from app import devlog


def test_public_roadmap_has_no_internal_ops_notes():
    # It once listed "2026-10-18", "RDS is drastically undersized" and worker env var names.
    for title, _ in devlog.PLANNED:
        assert not re.fullmatch(r"\d{4}-\d{2}-\d{2}", title.strip()), title
        assert not re.search(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b", title), title  # APCA_API_KEY_ID and kin
        assert not re.search(r"\bPR #\d+|\b[0-9a-f]{7,40}\b", title), title  # merge status, commit hashes
        assert not re.search(r"\b[a-z]+_[a-z_]+\b|\w/\w+/|=\"", title), title  # module names, code paths, code syntax


def test_shipped_entries_are_dated_newest_first():
    dates = [d for d, _, _ in devlog.SHIPPED]
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates)
    assert dates == sorted(dates, reverse=True)
