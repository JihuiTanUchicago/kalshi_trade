"""Synthetic native Exa HTTP contracts. No provider calls or real credentials."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest
import requests

from app.adapters.data import exa_data as data

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(days=7)
KEY = "synthetic-exa-private-key"


def source(**changes):
    return {"url": "https://www.federalreserve.gov/newsevents/example.htm", "title": "Policy statement",
            "publishedDate": "2026-10-09T18:00:00Z", "author": "Example agency",
            "highlights": ["A synthetic announcement."], "text": "Synthetic full document.", **changes}


def response_payload(rows=None, **changes):
    return {"results": [source()] if rows is None else rows, "requestId": "request-fixture-1",
            "costDollars": {"total": 0.007}, **changes}


class Response:
    def __init__(self, payload=None, status=200, raw=None):
        self.status_code, self.closed = status, False
        self.raw = json.dumps(response_payload() if payload is None else payload).encode() if raw is None else raw

    def iter_content(self, chunk_size):
        for i in range(0, len(self.raw), chunk_size):
            yield self.raw[i:i + chunk_size]

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def client(*responses, **options):
    session = Session(*responses)
    instance = data.ExaDataClient(data.Config(KEY, historical_enabled=options.pop("historical", False)),
                                  session=session,
                                  clock=lambda: NOW, **options)
    return instance, session


def test_search_is_fixed_host_and_returns_source_provenance_and_cost_telemetry():
    c, session = client(Response())
    result = c.search("recent policy announcement")
    url, call = session.calls[0]
    assert url == "https://api.exa.ai/search"
    assert call["json"] == {"query": "recent policy announcement", "type": "auto",
                            "contents": {"highlights": True}}
    assert call["headers"]["x-api-key"] == KEY and call["allow_redirects"] is False
    assert call["stream"] is True and call["timeout"] == (3.05, 10)
    assert result["reported_cost_usd"] == "0.007" and result["request_id"] == "request-fixture-1"
    item = result["sources"][0]
    assert item["publisher_host"] == "www.federalreserve.gov"
    assert item["retrieved_at"] == item["first_seen_at"] == "2026-10-17T12:00:00Z"
    assert item["content_sha256"] == hashlib.sha256(b"A synthetic announcement.").hexdigest()
    assert item["source_id"].startswith("exa:") and result["qualified_backtest_features"] is False
    assert KEY not in json.dumps(result) and KEY not in repr(c.config)


def test_publication_search_is_an_explicit_category_only_on_current_web():
    c, session = client(Response(), Response(), historical=True)
    c.search("prediction market calibration", publications=True)
    c.search("prediction market calibration", publications=True, as_of=CUTOFF)
    current, historical = [v[1]["json"] for v in session.calls]
    assert current["category"] == "publication"
    assert "category" not in historical and historical["query"].startswith("Academic research papers")
    assert historical["contents"] == {"highlights": True, "snapshotAsOf": "2026-10-10T12:00:00Z"}
    assert not {"livecrawl", "maxAgeHours", "subpages", "startPublishedDate", "endPublishedDate"} & historical.keys()


def test_contents_pins_top_level_and_reads_only_the_selected_page():
    c, session = client(Response(), historical=True)
    result = c.contents(source()["url"], as_of=CUTOFF)
    assert session.calls[0][0] == "https://api.exa.ai/contents"
    assert session.calls[0][1]["json"] == {"ids": [source()["url"]], "text": True, "snapshotAsOf": "2026-10-10T12:00:00Z"}
    assert result["sources"][0]["excerpt"] == "Synthetic full document."
    assert result["temporal_basis"] == "provider_snapshot_contract" and result["historical_ranking"] is False


@pytest.mark.parametrize("historical,cutoff,code", [(False, CUTOFF, "historical_disabled"),
                                                    (True, NOW + timedelta(seconds=1), "time_boundary"),
                                                    (True, CUTOFF.replace(tzinfo=None), "time_boundary")])
def test_invalid_history_never_calls_provider(historical, cutoff, code):
    c, session = client(historical=historical)
    with pytest.raises(data.ExaError) as exc:
        c.search("history", as_of=cutoff)
    assert exc.value.code == code and not session.calls


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://localhost/x", "https://127.0.0.1/x",
                                  "https://169.254.169.254/latest/meta-data", "https://10.0.0.2/x",
                                  "https://user:password@example.com/x", "https://example.com:8000/x",
                                  "https://a.internal/x", "https://example.com/a\nb", "https://example.com/<x>"])
def test_private_or_credentialed_source_urls_are_rejected_locally(url):
    c, session = client()
    with pytest.raises(data.ExaError):
        c.contents(url)
    assert not session.calls


@pytest.mark.parametrize("status,code", [(301, "provider_request"), (400, "provider_request"), (401, "authentication"),
                                        (402, "payment"), (403, "entitlement"), (429, "rate_limit"), (503, "provider_unavailable")])
def test_provider_errors_are_sanitized_and_not_retried(status, code):
    response = Response({"error": KEY}, status=status)
    c, session = client(response)
    with pytest.raises(data.ExaError) as exc:
        c.search("event")
    assert exc.value.code == code and KEY not in str(exc.value)
    assert len(session.calls) == 1 and response.closed


def test_timeout_reports_unknown_cost_and_hides_request_details():
    c, session = client(requests.Timeout("private transport " + KEY))
    with pytest.raises(data.ExaError) as exc:
        c.search("event")
    assert KEY not in str(exc.value) and len(session.calls) == 1
    assert "cost is unknown" in str(exc.value)


@pytest.mark.parametrize("raw", [b"not-json", b"[]", b"\xff"])
def test_invalid_response_does_not_become_a_source(raw):
    c, _ = client(Response(raw=raw))
    with pytest.raises(data.ExaError, match="invalid JSON"):
        c.search("event")


def test_response_size_is_bounded_and_closed():
    response = Response(raw=b"x" * (data.MAX_RESPONSE_BYTES + 1))
    c, _ = client(response)
    with pytest.raises(data.ExaError) as exc:
        c.search("event")
    assert exc.value.code == "response_limit" and response.closed


def test_missing_dates_stay_unknown_and_excerpts_are_hashed_before_truncation():
    text = "x" * 5000
    c, _ = client(Response(response_payload([source(publishedDate=None, highlights=[text])])), historical=True)
    item = c.search("history", as_of=CUTOFF)["sources"][0]
    assert item["published_at"] is None and item["excerpt_truncated"] is True
    assert len(item["excerpt"]) == data.MAX_EXCERPT_CHARS
    assert item["content_sha256"] == hashlib.sha256(text.encode()).hexdigest()


def test_optional_title_author_and_invalid_publication_date_stay_unknown():
    c, _ = client(Response(response_payload([source(title=None, author=None, publishedDate="undated")])) )
    item = c.search("announcement")["sources"][0]
    assert item["title"] is item["author"] is item["published_at"] is None


@pytest.mark.parametrize("cost", ["NaN", "Infinity", -1, None, True, "not-a-cost"])
def test_invalid_provider_cost_is_data_error(cost):
    c, _ = client(Response(response_payload(costDollars={"total": cost})))
    with pytest.raises(data.ExaError) as exc:
        c.search("event")
    assert exc.value.code == "invalid_data"


def test_later_publications_and_modified_historical_restrictions_are_withheld():
    c, _ = client(Response(response_payload([source(publishedDate="2026-10-11T00:00:00Z")])),
                      Response(response_payload(warnings=[{"code": "IGNORED_FIELD"}])), historical=True)
    result = c.search("history", as_of=CUTOFF)
    assert result["status"] == "no_results" and result["excluded_after_cutoff"] == 1
    with pytest.raises(data.ExaError) as exc:
        c.search("history", as_of=CUTOFF)
    assert exc.value.code == "time_boundary"


def test_contents_cannot_silently_return_a_different_page():
    c, _ = client(Response(response_payload([source(url="https://example.com/other")])) )
    with pytest.raises(data.ExaError) as exc:
        c.contents(source()["url"])
    assert exc.value.code == "invalid_source"


def test_empty_and_duplicate_results_have_explicit_semantics():
    c, _ = client(Response(response_payload([])), Response(response_payload([source(), source()])))
    assert c.search("empty")["status"] == "no_results"
    assert len(c.search("duplicate")["sources"]) == 1


@pytest.mark.parametrize("query", ["", "x" * 1001, KEY])
def test_bad_queries_do_not_reach_provider(query):
    c, session = client()
    with pytest.raises(data.ExaError):
        c.search(query)
    assert not session.calls


@pytest.mark.parametrize("kwargs", [{"api_key": ""}, {"api_key": "bad\nheader"}, {"historical_enabled": "1"}])
def test_configuration_does_not_echo_credentials(kwargs):
    with pytest.raises(data.ExaError) as exc:
        data.Config(**{"api_key": KEY, **kwargs})
    assert KEY not in str(exc.value) and "bad\nheader" not in str(exc.value)


def test_retired_quota_settings_cannot_block_requests_or_cost_telemetry(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", KEY)
    monkeypatch.setenv("TAU_EXA_MAX_REQUESTS_PER_RUN", "invalid-retired-setting")
    monkeypatch.setenv("TAU_EXA_MAX_COST_PER_RUN_USD", "0")
    monkeypatch.setenv("TAU_EXA_MONTHLY_BUDGET_USD", "0")
    session = Session(*(Response(response_payload(costDollars={"total": 10001})) for _ in range(8)))
    with data.ExaDataClient(data.Config.from_env(), session=session, clock=lambda: NOW) as c:
        for _ in range(8):
            assert c.search("event")["reported_cost_usd"] == "10001"
    assert len(session.calls) == 8


def test_more_than_five_results_are_preserved_without_forcing_provider_sampling():
    rows = [source(url="https://example.com/article/%d" % i) for i in range(10)]
    c, session = client(Response(response_payload(rows)))
    assert len(c.search("policy")["sources"]) == 10
    assert "numResults" not in session.calls[0][1]["json"]


def test_missing_reported_cost_stays_unknown_instead_of_becoming_an_estimate():
    c, _ = client(Response(response_payload(costDollars=None)))
    assert c.search("event")["reported_cost_usd"] is None


def test_status_is_configuration_only(monkeypatch, capsys):
    monkeypatch.setenv("EXA_API_KEY", KEY)
    monkeypatch.setattr("sys.argv", ["exa_data", "status"])
    monkeypatch.setattr(requests, "Session", lambda: pytest.fail("status must not use HTTP"))
    data.main()
    result = capsys.readouterr().out
    assert '"configured": true' in result and '"application_quotas": "none"' in result and KEY not in result
