"""The Dev Logs tab is public: every signed-in user sees it."""
import re

from app.web import devlog


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


def test_shipped_titles_are_features_not_engineering_logistics():
    # It once listed "Main f8ff5e2 merged locally" and "[ops] Codified the web-box deploy".
    for _, title, _ in devlog.SHIPPED:
        assert not re.search(r"\bmerged?\b|\borigin\b|\bPR #\d+|\[ops\]|\b[0-9a-f]{7,40}\b", title, re.I), title


def test_shipped_details_do_not_map_credentials_or_cloud_accounts():
    # It once said which provider keys sat in which secret store, named the deploy IAM user and
    # role, and walked through a sandbox secret-read exploit step by step.
    pat = r"AWS_[A-Z_]+|\bIAM\b|\bOIDC\b|\bSSM\b|Actions Secrets|tau-deploy|\bt4g\.|/etc/shadow|exfil|private `\.env`"
    for _, title, detail in devlog.SHIPPED:
        assert not re.search(pat, title + " " + detail), title
