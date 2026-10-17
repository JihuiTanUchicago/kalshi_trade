"""Synthetic World Monitor HTTP contract fixtures; never contact the hosted service."""
from datetime import datetime, timedelta, timezone
import json

import pytest
import requests

from app import worldmonitor_data as data

NOW = datetime(2027, 2, 1, 15, tzinfo=timezone.utc)
KEY = "synthetic-worldmonitor-private"


def item(**changes):
    return {"source": "Example Agency", "title": "Federal Reserve policy statement",
            "link": "https://www.federalreserve.gov/newsevents/example.htm",
            "publishedAt": int((NOW - timedelta(hours=1)).timestamp() * 1000),
            "snippet": "A synthetic RSS excerpt.", "isAlert": True,
            "importanceScore": 138, "credibilityScore": 90, "corroborationCount": 3,
            "tickers": ["SPY"], **changes}


def digest(rows=None, **changes):
    return {"categories": {"policy": {"items": [item()] if rows is None else rows}},
            "generatedAt": data.iso(NOW), "coverage": {"state": "complete", "feedTotal": 2, "feedCompleted": 2,
                                                         "attemptedAt": data.iso(NOW)}, "feedStatuses": {}, **changes}


class Response:
    def __init__(self, payload=None, *, raw=None, status=200, error=None):
        self.raw = json.dumps(digest() if payload is None else payload).encode() if raw is None else raw
        self.status_code, self.closed, self.error = status, False, error

    def iter_content(self, chunk_size):
        for i in range(0, len(self.raw), chunk_size):
            yield self.raw[i:i + chunk_size]
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses, self.calls, self.closed = list(responses), [], False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self):
        self.closed = True


def client(*responses, key=KEY, **kwargs):
    session = Session(*responses)
    return data.WorldMonitorClient(data.Config(key), session=session, clock=lambda: NOW, **kwargs), session


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An offline World Monitor test tried a network session")
    monkeypatch.setattr(data.requests, "Session", forbidden)


def test_config_defaults_are_local_safe_and_credentials_are_not_in_repr(tmp_path):
    cfg = data.Config.from_env({})
    assert cfg.api_key == "" and cfg.variants == ("finance", "full")
    cfg = data.Config.from_env({"WORLDMONITOR_API_KEY": KEY, "TAU_WORLDMONITOR_JOURNAL": str(tmp_path / "archive.db")})
    assert KEY not in repr(cfg) and cfg.journal_path == tmp_path / "archive.db"
    assert cfg.namespace != data.Config("different-key").namespace


@pytest.mark.parametrize("kwargs", [{"api_key": "bad\nkey"}, {"api_key": "bad key"}, {"variants": ()},
    {"variants": ("energy",)}, {"variants": ("finance", "orders")}])
def test_bad_configuration_does_not_pass_to_http(kwargs):
    with pytest.raises(data.NewsError):
        data.Config(**kwargs)


def test_http_contract_auth_headers_provenance_and_raw_fields_are_not_forwarded():
    response = Response(digest([item(storyMeta={"firstSeen": 1}, raw_secret=KEY)]))
    c, session = client(response)
    with c:
        result = c.digest("finance")
    url, args = session.calls[0]
    assert url == "https://api.worldmonitor.app/api/news/v1/list-feed-digest"
    assert args["params"] == {"variant": "finance", "lang": "en"}
    assert args["headers"]["X-WorldMonitor-Key"] == KEY and "Tau-News" in args["headers"]["User-Agent"]
    assert args["allow_redirects"] is False and args["stream"] is True and args["timeout"] == (3.05, 12)
    story = result["items"][0]
    assert story["publisher_host"] == "www.federalreserve.gov" and story["provider_scores"]["importanceScore"] == 138
    assert story["published_at"] == data.iso(NOW - timedelta(hours=1))
    assert "firstSeen" not in json.dumps(result) and KEY not in json.dumps(result)
    assert result["observed_at"] == data.iso(NOW) and result["vendor_first_seen_is_not_tau_observation"]
    assert response.closed and session.closed


def test_no_key_or_disabled_variant_is_rejected_before_http():
    for key, variant in [("", "finance"), (KEY, "energy"), (KEY, "../../orders")]:
        c, session = client(key=key)
        with pytest.raises(data.NewsError):
            c.digest(variant)
        assert session.calls == []


@pytest.mark.parametrize("status,code", [(401, "authentication"), (402, "payment"), (403, "entitlement"),
    (429, "rate_limit"), (503, "provider_unavailable"), (302, "provider_request")])
def test_provider_errors_close_response_and_do_not_leak_or_retry(status, code):
    response = Response({"message": KEY}, status=status)
    c, session = client(response)
    with pytest.raises(data.NewsError) as err:
        c.digest("finance")
    assert err.value.code == code and KEY not in str(err.value)
    assert len(session.calls) == 1 and response.closed


@pytest.mark.parametrize("exception", [requests.Timeout("URL secret " + KEY), requests.ConnectionError(KEY)])
def test_transport_errors_are_sanitized_without_paid_retries(exception):
    c, session = client(exception)
    with pytest.raises(data.NewsError) as err:
        c.digest("finance")
    assert err.value.code == "provider_unavailable" and KEY not in str(err.value) and len(session.calls) == 1


def test_stale_partial_coverage_and_feed_failures_are_distinct_from_fetch_time():
    raw = digest(generatedAt=data.iso(NOW - timedelta(hours=2)),
                 coverage={"state": "stale", "servedStale": True, "staleAgeSeconds": 7200,
                           "attemptedAt": data.iso(NOW), "feedTotal": 3, "feedCompleted": 1},
                 feedStatuses={"Provider B": "timeout", "Provider C": "partial-undated"})
    c, _ = client(Response(raw))
    result = c.digest("full")
    assert result["coverage"]["state"] == "stale" and result["coverage"]["served_stale"]
    assert result["generated_at"] != result["coverage"]["attempted_at"]
    assert result["feed_statuses"]["Provider B"] == "timeout"


def test_duplicates_across_categories_merge_but_unknown_dates_are_not_retrieval_dates():
    raw = digest([item(), item(publishedAt=0, link="https://example.org/undated")])
    raw["categories"]["markets"] = {"items": [item()]}
    result = data.normalize_digest(raw, "finance", NOW)
    assert len(result["items"]) == 2 and result["items"][0]["categories"] == ["markets", "policy"]
    assert result["items"][1]["published_at"] is None and result["undated_items"] == 1


def test_future_items_malformed_dates_and_reflected_credentials_are_withheld():
    raw = digest([item(publishedAt=int((NOW + timedelta(minutes=1)).timestamp() * 1000)),
                  item(title="Echo " + KEY), item(publishedAt=True), item(publishedAt="yesterday")])
    result = data.normalize_digest(raw, "full", NOW, api_key=KEY)
    assert result["items"] == [] and result["future_items_excluded"] == 1 and result["invalid_items"] == 3
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize("link", ["javascript:alert(1)", "file:///etc/passwd", "http://127.0.0.1/private",
    "https://localhost/secret", "https://private.internal/news", "https://user:secret@example.com/x",
    "https://example.com:8443/x", "https://example.com/x\nsecret"])
def test_unsafe_article_links_do_not_reach_the_journal(link):
    result = data.normalize_digest(digest([item(link=link)]), "finance", NOW)
    assert result["items"] == [] and result["invalid_items"] == 1


@pytest.mark.parametrize("payload", [[], {}, {"categories": []}, digest(categories={"bad": {"items": None}}),
    digest(coverage={"state": "invented"}), digest(coverage={"state": "complete", "feedTotal": True}),
    digest(feedStatuses={"feed": "failed"}), digest(generatedAt="undated"),
    digest(generatedAt=data.iso(NOW + timedelta(minutes=2)))])
def test_invalid_digest_structure_fails_visibly(payload):
    with pytest.raises(data.NewsError):
        data.normalize_digest(payload, "finance", NOW)


def test_html_is_plain_text_and_empty_snippet_does_not_become_an_invented_summary():
    result = data.normalize_digest(digest([item(title="<b>Policy &amp; rates</b>", snippet="")]), "finance", NOW)
    assert result["items"][0]["title"] == "Policy & rates" and result["items"][0]["excerpt"] == ""


def test_response_and_record_limits_never_archive_an_apparently_complete_subset(monkeypatch):
    monkeypatch.setattr(data, "MAX_ITEMS", 1)
    with pytest.raises(data.NewsError) as err:
        data.normalize_digest(digest([item(), item(link="https://example.com/other")]), "finance", NOW)
    assert err.value.code == "response_limit"
    monkeypatch.setattr(data, "MAX_RESPONSE_BYTES", 1)
    response = Response()
    c, _ = client(response)
    with pytest.raises(data.NewsError) as err:
        c.digest("finance")
    assert err.value.code == "response_limit" and response.closed


def test_stream_decode_errors_and_cancellation_close_the_response():
    c, _ = client(Response(raw=b"not-json"))
    with pytest.raises(data.NewsError, match="invalid JSON"):
        c.digest("finance")
    response = Response(error=requests.ConnectionError(KEY))
    c, session = client(response)
    with pytest.raises(data.NewsError):
        c.digest("finance")
    assert response.closed and len(session.calls) == 1
    class Cancelled(Exception):
        pass
    response = Response()
    c, session = client(response)
    def checkpoint():
        if session.calls:
            raise Cancelled()
    c.checkpoint = checkpoint
    with pytest.raises(Cancelled):
        c.digest("finance")
    assert response.closed and len(session.calls) == 1


def test_status_cli_is_local_and_does_not_print_key(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("WORLDMONITOR_API_KEY", KEY)
    monkeypatch.setenv("TAU_WORLDMONITOR_JOURNAL", str(tmp_path / "unused.sqlite3"))
    monkeypatch.delenv("TAU_WORLDMONITOR_ENABLED", raising=False)
    monkeypatch.setattr("sys.argv", ["worldmonitor", "status"])
    assert data.main() == 0
    text = capsys.readouterr().out
    assert KEY not in text and not json.loads(text)["network_checked"] and not json.loads(text)["enabled"]
    assert not (tmp_path / "unused.sqlite3").exists()
