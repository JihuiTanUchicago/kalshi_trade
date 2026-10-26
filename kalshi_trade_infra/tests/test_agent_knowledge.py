"""Exa tools, source identity, temporal scope and model metering with synthetic inputs."""
from datetime import timedelta
import json

import pytest
import requests

from app import agent_knowledge as knowledge
from app.agent_market_data import DataScope
from app.adapters.data.exa_data import ExaDataClient
from app.llm import LLMError, Usage, ask_json
from tests.test_exa_data import CUTOFF, KEY, NOW, Response, Session, response_payload, source


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("TAU_EXA_ENABLED", "1")
    monkeypatch.setenv("EXA_API_KEY", KEY)
    monkeypatch.setenv("TAU_EXA_HISTORICAL_ENABLED", "1")
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "0")
    monkeypatch.setenv("TAU_MASSIVE_ENABLED", "0")
    monkeypatch.setenv("TAU_DATABENTO_ENABLED", "0")


def instance(*responses, scope=None, **options):
    session, events = Session(*responses), []
    def factory(config, **kwargs):
        return ExaDataClient(config, session=session, **kwargs)
    tool = knowledge.AgentKnowledge(scope or DataScope(), lambda *args: events.append(args), client_factory=factory,
                                    clock=lambda: NOW, **options)
    return tool, session, events


def scripted(replies):
    prompts = []
    def model(system, messages):
        prompts.append((system, messages))
        reply = replies.pop(0)
        return reply() if callable(reply) else reply, {"input_tokens": 10, "output_tokens": 5}
    return model, prompts


def tool_request(kind="search", **values):
    return json.dumps({"knowledge_requests": [{"kind": kind, **({"query": "policy announcement"} if not values else values)}]})


def run(tool, model, usage=None):
    usage = usage or Usage()
    result = ask_json(tool.wrap(model, usage), "system", [{"role": "user", "content": "question"}], lambda obj: obj["reply"], usage)
    return result, usage


def test_disabled_is_the_exact_original_model_contract(monkeypatch):
    monkeypatch.setenv("TAU_EXA_ENABLED", "0")
    tool, session, _ = instance()
    model, prompts = scripted(['{"reply":"ordinary answer"}'])
    assert tool.wrap(model, Usage()) is model
    result, usage = run(tool, model)
    assert result == "ordinary answer" and not session.calls
    assert prompts == [("system", [{"role": "user", "content": "question"}])]
    assert usage.input_tokens == 10


def test_enabled_is_on_demand_and_missing_key_is_visible_without_http(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY")
    tool, session, _ = instance()
    model, prompts = scripted(['{"reply":"Web research is unavailable."}'])
    assert run(tool, model)[0] == "Web research is unavailable." and not session.calls
    assert "not_configured" in str(prompts) and KEY not in str(prompts)


def test_search_then_selected_contents_appends_host_citations_and_counts_each_model_call_once():
    tool, session, events = instance(Response(), Response())
    def read():
        return tool_request("contents", source_id=next(iter(tool.sources)))
    def final():
        return json.dumps({"reply": "Here is the sourced explanation.", "source_ids": [list(tool.sources)[-1]]})
    model, prompts = scripted([tool_request(), read, final])
    answer, usage = run(tool, model)
    assert "Sources:" in answer and source()["url"] in answer and "federalreserve.gov" in answer
    assert len(session.calls) == len(events) == 2
    assert (usage.input_tokens, usage.output_tokens) == (30, 15)
    assert "Synthetic full document." in str(prompts[-1]) and KEY not in str(prompts)
    assert events[0][2]["sources"][0]["content_sha256"] and events[0][2]["reported_cost_usd"] == "0.007"


def test_unselected_urls_and_foreign_source_ids_never_reach_contents():
    tool, session, _ = instance()
    model, prompts = scripted([tool_request("contents", source_id="exa:another-users-source"), '{"reply":"Source unavailable."}'])
    assert run(tool, model)[0] == "Source unavailable." and not session.calls
    assert "invalid_source" in str(prompts)


def test_repeated_search_uses_run_local_cache_without_refreshing_dates_or_calling_again():
    tool, session, events = instance(Response())
    model, _ = scripted([tool_request(), tool_request(), '{"reply":"Compared sources."}'])
    run(tool, model)
    assert len(session.calls) == 1
    original, cached = [e[2] for e in events]
    assert cached["cached"] is True and cached["sources"] == original["sources"]
    other, _, _ = instance()
    assert not other.sources and not other.cache


def test_current_cache_expires_and_retains_distinct_retrieval_versions():
    tool, session, _ = instance(Response(), Response(response_payload([source(highlights=["Updated text."])])))
    tool._read({"kind": "search", "query": "same"})
    tool.clock = lambda: NOW + timedelta(seconds=61)
    tool._read({"kind": "search", "query": "same"})
    assert len(session.calls) == 2 and len(tool.sources) == 2


def test_historical_requests_are_host_pinned_and_never_use_current_category_or_crawl():
    tool, session, _ = instance(Response(), scope=DataScope(NOW - timedelta(days=30), CUTOFF))
    model, prompts = scripted([tool_request("publications", query="calibration papers"), '{"reply":"Archived evidence."}'])
    run(tool, model)
    request = session.calls[0][1]["json"]
    assert request["contents"]["snapshotAsOf"] == "2026-10-10T12:00:00Z" and "category" not in request
    assert "provider_snapshot_contract" in str(prompts) and "historical_research" in str(prompts)


def test_disabled_snapshot_and_entitlement_failure_never_fall_back_to_current_web(monkeypatch):
    monkeypatch.setenv("TAU_EXA_HISTORICAL_ENABLED", "0")
    tool, session, _ = instance(scope=DataScope(NOW - timedelta(days=30), CUTOFF))
    model, prompts = scripted([tool_request(), '{"reply":"Archived coverage unavailable."}'])
    run(tool, model)
    assert not session.calls and "historical_disabled" in str(prompts)
    monkeypatch.setenv("TAU_EXA_HISTORICAL_ENABLED", "1")
    tool, session, _ = instance(Response(status=403), scope=DataScope(NOW - timedelta(days=30), CUTOFF))
    model, prompts = scripted([tool_request(), '{"reply":"Archived coverage unavailable."}'])
    run(tool, model)
    assert len(session.calls) == 1 and "entitlement" in str(prompts) and not tool.sources


@pytest.mark.parametrize("raw_request", [
    {"kind": "search", "query": "q", "snapshotAsOf": "2020-01-01"},
    {"kind": "search", "query": "q", "includeDomains": ["example.com"]},
    {"kind": "contents", "url": "https://example.com"},
    {"kind": "orders", "query": "q"},
    {"kind": [], "query": "q"},
    {"query": "q"},
])
def test_model_cannot_change_host_boundaries_sources_or_authority(raw_request):
    with pytest.raises(ValueError):
        knowledge.request_checked(raw_request)


def test_mixed_actions_are_rejected_before_any_provider_call_and_repaired_once():
    tool, session, _ = instance()
    bad = json.dumps({"knowledge_requests": [{"kind": "search", "query": "q"}], "actions": [{"type": "deploy"}]})
    model, prompts = scripted([bad, '{"reply":"Corrected."}'])
    answer, usage = run(tool, model)
    assert answer == "Corrected." and not session.calls and "rejected" in str(prompts[-1])
    assert usage.input_tokens == 20


def test_unknown_citations_get_one_repair_and_cannot_be_invented():
    tool, _, _ = instance(Response())
    bad = '{"reply":"Claim.","source_ids":["exa:invented"]}'
    model, _ = scripted([tool_request(), bad, bad])
    usage = Usage()
    with pytest.raises(LLMError):
        run(tool, model, usage)
    assert usage.input_tokens == 30


def test_web_research_exceeds_old_round_and_request_quotas_until_model_finishes():
    tool, session, events = instance(*(Response() for _ in range(8)))
    queries = [tool_request(query="q%d" % i) for i in range(8)]
    model, prompts = scripted([*queries, '{"reply":"Research completed."}'])
    _, usage = run(tool, model)
    assert len(session.calls) == len(events) == 8 and usage.input_tokens == 90
    assert '"application_quotas": "none"' in str(prompts)
    assert "budget exhausted" not in str(prompts) and "remaining_web_rounds" not in str(prompts)


def test_a_batch_can_contain_more_than_two_requests():
    tool, session, events = instance(*(Response() for _ in range(5)))
    batch = {"knowledge_requests": [{"kind": "search", "query": "q%d" % i} for i in range(5)]}
    model, _ = scripted([json.dumps(batch), '{"reply":"Batch completed."}'])
    _, usage = run(tool, model)
    assert len(session.calls) == len(events) == 5 and usage.input_tokens == 20


def test_cancellation_between_requests_interrupts_an_unrestricted_batch():
    tool, session, events = instance(*(Response() for _ in range(5)))
    class Cancelled(Exception):
        pass
    def checkpoint():
        if len(events) >= 2:
            raise Cancelled()
    tool.checkpoint = checkpoint
    batch = {"knowledge_requests": [{"kind": "search", "query": "q%d" % i} for i in range(5)]}
    model, _ = scripted([json.dumps(batch)])
    usage = Usage()
    with pytest.raises(Cancelled):
        run(tool, model, usage)
    assert len(session.calls) == len(events) == 2 and usage.input_tokens == 10


def test_cancellation_after_model_reply_preserves_usage_and_prevents_paid_request():
    cancelled = False
    class Cancelled(Exception):
        pass
    def checkpoint():
        if cancelled:
            raise Cancelled()
    tool, session, _ = instance(checkpoint=checkpoint)
    def model(*args):
        nonlocal cancelled
        cancelled = True
        return tool_request(), {"input_tokens": 17, "output_tokens": 3}
    usage = Usage()
    with pytest.raises(Cancelled):
        run(tool, model, usage)
    assert (usage.input_tokens, usage.output_tokens) == (17, 3) and not session.calls


def test_timeout_is_explicit_evidence_failure_not_a_fabricated_fact():
    tool, session, _ = instance(requests.Timeout(KEY))
    model, prompts = scripted([tool_request(), '{"reply":"The source request failed."}'])
    answer, _ = run(tool, model)
    assert "Sources" not in answer and not tool.sources and len(session.calls) == 1
    assert "provider_unavailable" in str(prompts) and KEY not in str(prompts)
    assert "cost is unknown" in str(prompts)


def test_added_source_context_is_bounded_even_with_large_metadata_and_excerpts():
    rows = [source(url="https://example.com/" + str(i) + "x" * 1800, title="t" * 300,
                   author="a" * 200, highlights=["x" * 10000]) for i in range(5)]
    tool, _, _ = instance(Response(response_payload(rows)))
    tool._read({"kind": "search", "query": "large"})
    tool.receipts.append(tool.cache[next(iter(tool.cache))][1])
    context = tool._context()
    assert context and sum(len(m["content"]) for m in context) <= knowledge.MAX_CONTEXT_CHARS
    assert "context_excerpt_truncated" in str(context)
