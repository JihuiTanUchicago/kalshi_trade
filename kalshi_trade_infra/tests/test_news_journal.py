"""Real SQLite journal behavior with synthetic news and deterministic clocks."""
from datetime import timedelta
import json
import sqlite3

import pytest

from app.adapters.data.news_journal import NewsJournal
from app import worldmonitor_data as data
from tests.test_worldmonitor_data import NOW, digest, item


def packet(rows=None, *, when=NOW, **changes):
    return data.normalize_digest(digest(rows, generatedAt=data.iso(when), **changes), "finance", when)


@pytest.fixture
def journal(tmp_path):
    return NewsJournal(tmp_path / "private/news.sqlite3", "test-namespace")


def read(journal, when=NOW, **kwargs):
    return journal.read("finance", when, start=when - timedelta(days=1), **kwargs)


def test_empty_archive_is_unavailable_without_creating_a_database(journal):
    result = read(journal)
    assert result["code"] == "archive_empty" and not journal.path.exists()


def test_poll_persists_first_observation_and_repeated_items_are_idempotent(journal):
    first = journal.record(packet())
    second = journal.record(packet(when=NOW + timedelta(minutes=1)))
    source = read(journal, NOW + timedelta(minutes=1))["sources"][0]
    assert first["new_articles"] == 1 and second["unchanged_articles"] == 1 and second["new_articles"] == 0
    assert source["first_observed_at"] == source["version_observed_at"] == data.iso(NOW)
    assert source["source_id"].startswith("worldmonitor:") and source["content_sha256"]
    with sqlite3.connect(journal.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM news_versions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM news_polls").fetchone()[0] == 2
    assert journal.path.stat().st_mode & 0o777 == 0o600


def test_old_publication_date_does_not_make_a_newly_fetched_story_available_in_the_past(journal):
    journal.record(packet())
    before = read(journal, NOW - timedelta(minutes=1))
    assert before["code"] == "historical_unavailable" and before["sources"] == []
    assert read(journal)["sources"][0]["published_at"] == data.iso(NOW - timedelta(hours=1))


def test_revision_and_reversion_preserve_each_observed_version(journal):
    journal.record(packet())
    journal.record(packet([item(title="Corrected policy statement")], when=NOW + timedelta(minutes=1)))
    journal.record(packet(when=NOW + timedelta(minutes=2)))
    a = read(journal)["sources"][0]
    b = read(journal, NOW + timedelta(minutes=1))["sources"][0]
    c = read(journal, NOW + timedelta(minutes=2))["sources"][0]
    assert a["title"] == c["title"] != b["title"]
    assert [a["version"], b["version"], c["version"]] == [1, 2, 3]
    assert len({s["source_id"] for s in (a, b, c)}) == 3
    assert a["first_observed_at"] == b["first_observed_at"] == c["first_observed_at"]
    assert b["version_observed_at"] == data.iso(NOW + timedelta(minutes=1))


def test_current_correction_not_matching_query_does_not_resurrect_an_old_version(journal):
    journal.record(packet())
    journal.record(packet([item(title="Corrected unrelated story", snippet="", tickers=[])], when=NOW + timedelta(minutes=1)))
    assert read(journal, query="Federal Reserve")["matched_count"] == 1
    assert read(journal, NOW + timedelta(minutes=1), query="Federal Reserve")["matched_count"] == 0


def test_latest_snapshot_membership_preserves_removals_without_rewriting_past(journal):
    journal.record(packet())
    journal.record(packet([], when=NOW + timedelta(minutes=1)))
    assert read(journal)["returned_count"] == 1
    assert read(journal, NOW + timedelta(minutes=1))["sources"] == []
    assert read(journal, NOW + timedelta(minutes=1))["status"] == "empty"


def test_unknown_dates_are_stored_but_never_counted_as_dated_evidence(journal):
    journal.record(packet([item(publishedAt=0)]))
    result = read(journal)
    assert result["undated_items"] == 1 and result["sources"] == []
    with sqlite3.connect(journal.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM news_versions").fetchone()[0] == 1


def test_key_namespace_and_variant_are_isolated(journal):
    journal.record(packet())
    other = NewsJournal(journal.path, "different-credential-namespace")
    assert read(other)["sources"] == []
    assert journal.read("full", NOW, start=NOW - timedelta(days=1))["sources"] == []


def test_partial_stale_unavailable_coverage_remains_explicit(journal):
    for i, state in enumerate(("partial", "stale", "unavailable")):
        when = NOW + timedelta(minutes=i)
        journal.record(packet(when=when, coverage={"state": state, "attemptedAt": data.iso(when)}))
        result = read(journal, when)
        assert result["status"] == state
        if state == "unavailable":
            assert result["sources"] == []


def test_fresh_poll_with_old_digest_and_expired_poll_are_not_live_news(journal):
    raw = digest(generatedAt=data.iso(NOW - timedelta(hours=2)))
    journal.record(data.normalize_digest(raw, "finance", NOW))
    result = read(journal)
    assert result["poll_age_seconds"] == 0 and result["content_age_seconds"] == 7200 and result["status"] == "stale"
    journal.record(packet(when=NOW + timedelta(minutes=1)))
    assert read(journal, NOW + timedelta(minutes=12))["status"] == "stale"


def test_filters_are_literal_not_sql_patterns_and_limits_are_explicit(journal):
    rows = [item(title="Revenue up 10%_today", link="https://example.org/one"),
            item(title="Revenue up 10Xtoday", link="https://example.org/two")]
    journal.record(packet(rows))
    assert read(journal, query="%_")["matched_count"] == 1
    limited = read(journal, limit=1)
    assert limited["matched_count"] == 2 and limited["returned_count"] == 1 and limited["truncated"] is True


def test_archive_clock_cannot_move_backward_or_partially_insert(journal):
    journal.record(packet())
    with pytest.raises(data.NewsError) as err:
        journal.record(packet([item(title="Backdated revision")], when=NOW - timedelta(minutes=1)))
    assert err.value.code == "clock_regression"
    assert read(journal)["sources"][0]["version"] == 1


def test_restart_reads_persisted_data_and_keeps_provider_observation_separate(journal):
    journal.record(packet())
    reopened = NewsJournal(journal.path, journal.namespace)
    result = read(reopened)
    assert result["observed_at"] == data.iso(NOW)
    assert result["sources"][0]["published_at"] != result["sources"][0]["first_observed_at"]
    assert result["publication_dates_do_not_establish_availability"] is True


def test_many_members_do_not_hit_sqlite_parameter_limits(journal):
    journal.record(packet([item(link="https://example.org/story/%d" % i) for i in range(1001)]))
    result = read(journal, limit=20)
    assert result["matched_count"] == 1001 and len(result["sources"]) == 20


def test_corrupt_database_is_a_safe_journal_error(journal):
    journal.path.parent.mkdir(parents=True)
    journal.path.write_text("not a database")
    with pytest.raises(data.NewsError) as err:
        read(journal)
    assert err.value.code == "journal_unavailable"
