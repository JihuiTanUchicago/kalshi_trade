"""The Dev Logs tab is public: every signed-in user sees it."""
import re

import pytest

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


def _entries():
    return list(devlog.PLANNED) + [(t, d) for _, t, d in devlog.SHIPPED]


# Every customer reads the Dev Logs, so an entry says what changed in a customer's words. Walk 2026-10-27: entries
# named settings (APP_REVIEW_MODEL), functions and tables (repo.largest_tables(), app_users.autopilot_plan), files
# (app/research/research_eval.py), "our Bedrock account", "the AWS account gets AccessDenied", a model id
# (us.deepseek.r1-v1:0), raw series keys (KXNBAGAME), a run id ("run 213"), raw upstream exceptions
# (ThrottlingException, "(2013, 'Lost connection to MySQL server ...')"), deploy hosts and commit hashes, what a model
# costs Tau ("$1.35/M in") and "list price × 2 (100% margin)". Each kind keeps one of the walk's own examples, which
# the guard must still catch. Allowed, because they are the customer's own words: "Kalshi account" and "Tau account"
# (theirs, not a cloud account), pages a customer can open (/terms, /privacy) and a position's own cost.
INTERNAL = {
    "a setting or env-var name": (r"\b[A-Z]{2,}_[A-Z_]{2,}", "Reviews stay on Sonnet (APP_REVIEW_MODEL)"),
    "a cloud vendor or service": (
        r"\bAWS\b|Bedrock|\bRDS\b|\bEC2\b|\bS3\b|\bIAM\b|\bSSM\b|\bSES\b|\bOIDC\b|CloudFront|CloudWatch|"
        r"\bboto(?:3|core)\b|\b(?:us|eu|ap)-(?:east|west|north|south|central)-\d", "verified invokable on Bedrock us-east-1"),
    "a cloud account": (
        r"\b(?:AWS|Amazon|Bedrock|cloud|hosting|GCP|Azure|Anthropic|provider)(?:['’]s)?\W+(?:\w+\W+)?accounts?\b"
        r"|\bour (?:\w+ )?account\b", "no daily token cap on our Bedrock account"),
    "a credential store or secret": (
        r"Secrets? Manager|Parameter Store|Actions Secrets|\bvault\b|\.env\b|tau-deploy|\bt4g\.|/etc/shadow|exfil",
        "which provider keys sat in Actions Secrets"),
    "a file, module, table or code span": (
        r"\b\w+\.(?:py|js|mjs|css|md|ya?ml|json|sql|sh)\b|\b[a-z0-9]+_[a-z0-9_]+\b|`|\b(?:app|tests?|static|results)/|/api/",
        "shipped app/research/research_eval.py"),
    "a function, class or raw upstream error": (
        r"\b[a-z]+[A-Z]\w*|\w\(\)|\b\w*(?:Error|Exception)\b|AccessDenied|Throttling|\berrno\b|Traceback|"
        r"Lost connection|\(\d{4}, '", "the AWS account gets AccessDenied until Bedrock grants access"),
    "a model, experiment or row id": (
        r"\bclaude-|\banthropic\.|\bus\.[a-z]+\.|-v\d+:\d|\[1m\]|\b(?:run|experiment|exp|user|deployment|strategy) #?\d+\b",
        "Added DeepSeek R1 (us.deepseek.r1-v1:0)"),
    "a raw series key": (r"\bKX[A-Z0-9]{2,}", "KXNBAGAME added as a sports market family"),
    "internal infrastructure": (
        r"\bMySQL\b|information_schema|\b(?:the|on|collector) box\b|\bprod\b|\bDDL\b|\b[0-9a-f]{7,40}\b",
        "Deployed to the collector box (restarted clean)"),
    "what Tau pays for a model or adds on top": (
        r"list price|\bmargins?\b|mark-?up|× ?2\b|raw model cost|\bour cost|what (?:Tau|we) pays?|\$[\d.]+ ?/ ?M\b"
        r"|per million tokens", "Billing: customers charged list price × 2 (100% margin)"),
}


@pytest.mark.parametrize("kind", sorted(INTERNAL))
def test_the_guard_still_catches_what_the_walk_found(kind):
    pat, example = INTERNAL[kind]
    assert re.search(pat, example, re.I), kind


@pytest.mark.parametrize("kind", sorted(INTERNAL))
def test_dev_logs_show_customers_no_internal_detail(kind):
    pat = re.compile(INTERNAL[kind][0], re.I if kind.startswith("what Tau pays") else 0)
    hits = [(title, m.group(0)) for title, detail in _entries() for m in [pat.search(title + " " + detail)] if m]
    assert hits == [], kind


@pytest.mark.parametrize("text", [
    "a sweep compares your actual Kalshi account with Tau’s positions",
    "anyone with a Google sign-in can now create a Tau account directly",
    "public pages at /terms and /privacy, readable signed in or out",
    "sell when a position is down a set share of its own cost",
    "until the AI provider opens them to us",
])
def test_the_guard_leaves_customer_words_alone(text):
    assert [k for k, (pat, _) in INTERNAL.items() if re.search(pat, text)] == []


def test_dev_logs_use_curly_apostrophes_and_quotes():
    for title, detail in _entries():
        assert "'" not in title + detail and '"' not in title + detail, title
