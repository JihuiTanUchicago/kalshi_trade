"""Real TAU research/copilot + Exa decoder, with synthetic HTTP/database/model inputs."""
from datetime import datetime, timezone
import json

import pytest
import pymysql

from app import agent, agent_knowledge as knowledge, agent_market_data as market, agent_news as news
from app.exa_data import ExaDataClient
from app.llm import LLMError, Usage
from app.market_data_common import iso
from tests.test_agent_knowledge import scripted, tool_request
from tests.test_agent_market_data import provider as alpaca_provider
from tests.test_app_agent import Conn, RUN, Store, WINNER, hyps, plan
from tests.test_app_backtest import _dataset
from tests.test_exa_data import KEY, Response, Session, source

NOW = datetime(2027, 2, 1, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("TAU_EXA_ENABLED", "1")
    monkeypatch.setenv("EXA_API_KEY", KEY)
    monkeypatch.setenv("TAU_EXA_HISTORICAL_ENABLED", "1")
    monkeypatch.setenv("TAU_WORLDMONITOR_ENABLED", "0")
    # Retired settings must not reintroduce limits when old worker environments retain them.
    monkeypatch.setenv("TAU_EXA_MAX_REQUESTS_PER_RUN", "0")
    monkeypatch.setenv("TAU_EXA_MAX_COST_PER_RUN_USD", "0")
    monkeypatch.setenv("TAU_EXA_MONTHLY_BUDGET_USD", "0")
    for vendor in ["ALPACA", "MASSIVE", "DATABENTO"]:
        monkeypatch.setenv("TAU_%s_ENABLED" % vendor, "0")
    original = knowledge.AgentKnowledge
    monkeypatch.setattr(agent, "AgentKnowledge", lambda *args, **kwargs: original(*args, **kwargs, clock=lambda: NOW))
    market._CACHE.clear()
    yield
    market._CACHE.clear()


def wire(monkeypatch, *responses):
    session = Session(*responses)
    conn, store, billed, saved = Conn(), Store(monkeypatch), [], []
    monkeypatch.setattr(knowledge, "ExaDataClient", lambda config, **kwargs: ExaDataClient(config, session=session, **kwargs))
    monkeypatch.setattr(agent.billing, "charge_usage", lambda *args: billed.append(args))
    monkeypatch.setattr(agent.repo, "get_user", lambda cur, uid: {"id": uid})
    monkeypatch.setattr(agent.repo, "chat_messages", lambda *args, **kwargs: [{"role": "user", "content": "Investigate current policy news."}])
    monkeypatch.setattr(agent.repo, "list_deployments", lambda *args, **kwargs: [])
    monkeypatch.setattr(agent.repo, "list_strategies", lambda *args, **kwargs: [])
    monkeypatch.setattr(agent.repo, "user_risk_config", lambda *args: {})
    monkeypatch.setattr(agent.repo, "user_execution_config", lambda *args: {})
    monkeypatch.setattr(agent.repo, "add_chat", lambda *args: saved.append(args))
    return session, conn, store, billed, saved


def test_research_entrypoint_receives_archived_sources_saves_citations_and_bills_tool_turns(monkeypatch):
    session, conn, store, billed, _ = wire(monkeypatch, Response())
    theses = []
    def insert(*args):
        theses.append(args[7])
        return store._insert(*args)
    monkeypatch.setattr(agent.repo, "insert_strategy", insert)
    model, prompts = scripted([plan(), tool_request("publications", query="prediction market calibration papers"), hyps(WINNER)])
    ds = _dataset(n_contracts=60)
    agent.run_research(conn, {**RUN, "max_hypotheses": 1}, model=model, dataset_fn=lambda m, h=None: ds)
    assert store.finished[0] == "succeeded" and store.finished[2] == 1
    assert session.calls[0][1]["json"]["contents"]["snapshotAsOf"] == iso(datetime.fromtimestamp(ds.cutoff_ts, timezone.utc))
    assert "category" not in session.calls[0][1]["json"]
    assert len(session.calls) == 1
    assert source()["url"] in theses[0] and "Sources retrieved" in theses[0]
    assert "A synthetic announcement." in str(prompts[-1]) and KEY not in str(prompts)
    assert billed[0][3:5] == (30, 15) and len(billed) == 1
    assert any(e[2] and e[2].get("provider") == "exa" for e in store.events)


def test_copilot_entrypoint_returns_cited_answer_and_event_receipt_without_quota_table(monkeypatch):
    session, conn, store, billed, saved = wire(monkeypatch, Response())
    model, _ = scripted([tool_request(), '{"reply":"Policy news reviewed.","actions":[]}'])
    agent.run_copilot(conn, {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert store.finished[0] == "succeeded" and len(session.calls) == 1
    assert source()["url"] in saved[0][3] and "Sources retrieved" in saved[0][3]
    assert billed[0][3:5] == (20, 10) and len(billed) == 1
    assert any(e[2] and e[2].get("reported_cost_usd") == "0.007" for e in store.events)


def test_forever_research_can_retrieve_in_each_chunk_despite_retired_limits(monkeypatch):
    monkeypatch.setenv("TAU_EXA_MAX_REQUESTS_PER_RUN", "1")
    session, conn, store, billed, _ = wire(monkeypatch, Response(), Response())
    balances = iter([100, 0])
    monkeypatch.setattr(agent.repo, "credit_balance", lambda *args: next(balances))
    queries = [tool_request(query="first question"), tool_request(query="different question")]
    model, prompts = scripted([plan(), queries[0], hyps(WINNER), queries[1], hyps(WINNER)])
    agent.run_research(conn, {**RUN, "run_forever": True, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded" and store.finished[2] == 2
    assert len(session.calls) == 2 and "run_budget" not in str(prompts[-1])
    assert sum(b[3] for b in billed) == 50 and sum(b[4] for b in billed) == 25


def test_retired_monthly_limit_does_not_block_a_second_users_copilot(monkeypatch):
    session, conn, store, billed, _ = wire(monkeypatch, Response(), Response())
    first, _ = scripted([tool_request(), '{"reply":"First checked.","actions":[]}'])
    second, prompts = scripted([tool_request(), '{"reply":"Second checked.","actions":[]}'])
    agent.run_copilot(conn, {"id": 1, "user_id": 7, "kind": "chat"}, model=first)
    agent.run_copilot(conn, {"id": 2, "user_id": 8, "kind": "chat"}, model=second)
    assert len(session.calls) == 2
    assert "monthly_budget" not in str(prompts) and billed[1][1] == 8


def test_provider_denial_is_reported_without_fabricated_sources(monkeypatch):
    session, conn, store, billed, saved = wire(monkeypatch, Response(status=403))
    model, prompts = scripted([tool_request(), '{"reply":"The source feed is unavailable.","actions":[]}'])
    agent.run_copilot(conn, {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert store.finished[0] == "succeeded" and "entitlement" in str(prompts)
    assert len(session.calls) == 1 and any(e[2] and e[2].get("code") == "entitlement" for e in store.events)
    assert "Sources" not in saved[0][3] and billed[0][3:5] == (20, 10)


def test_copilot_model_failure_after_search_still_charges_consumed_usage_once(monkeypatch):
    session, conn, store, billed, _ = wire(monkeypatch, Response())
    calls = 0
    def model(system, messages):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise LLMError("Synthetic provider failure.")
        return tool_request(), {"input_tokens": 11, "output_tokens": 4}
    agent.run_copilot(conn, {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert store.finished[0] == "failed" and len(session.calls) == 1
    assert len(billed) == 1 and billed[0][3:5] == (11, 4)


def test_cancel_after_model_reply_stops_before_spending_and_preserves_cancelled_status(monkeypatch):
    session, conn, store, billed, _ = wire(monkeypatch)
    def model(system, messages):
        store.status = "cancelled"
        return tool_request(), {"input_tokens": 9, "output_tokens": 3}
    agent.run_copilot(conn, {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert store.finished is None and not session.calls
    assert billed[0][3:5] == (9, 3) and len(billed) == 1


def test_existing_market_data_and_exa_interleave_without_double_model_billing(monkeypatch, alpaca_provider):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "fake-alpaca-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fake-alpaca-secret")
    monkeypatch.setenv("TAU_ALPACA_SYMBOLS", "SPY")
    monkeypatch.setenv("TAU_ALPACA_FEED", "iex")
    monkeypatch.setattr(market, "utc_now", lambda: NOW)
    session, conn, store, billed, saved = wire(monkeypatch, Response())
    stock = json.dumps({"market_data_requests": [{"kind": "bars", "symbols": ["AAPL"], "lookback_days": 7}]})
    model, prompts = scripted([tool_request(), stock, '{"reply":"Compared news with AAPL history.","actions":[]}'])
    agent.run_copilot(conn, {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert len(session.calls) == 1 and len(alpaca_provider) == 2
    assert '"last_close": 102' in str(prompts[-1]) and "A synthetic announcement." in str(prompts[-1])
    assert billed[0][3:5] == (30, 15) and source()["url"] in saved[0][3]


def test_web_adapter_does_not_reset_existing_market_data_round_limit(monkeypatch, alpaca_provider):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "fake-alpaca-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fake-alpaca-secret")
    monkeypatch.setenv("TAU_ALPACA_SYMBOLS", "SPY")
    monkeypatch.setenv("TAU_ALPACA_FEED", "iex")
    monkeypatch.setattr(market, "utc_now", lambda: NOW)
    session, _, _, _, _ = wire(monkeypatch, Response(), Response())
    tool = agent.AgentKnowledge(market.DataScope(), lambda *args: None)
    def stock(symbol):
        return json.dumps({"market_data_requests": [{"kind": "bars", "symbols": [symbol], "lookback_days": 7}]})
    model, _ = scripted([tool_request(query="one"), stock("AAPL"), tool_request(query="two"),
                         stock("MSFT"), stock("GOOG"), stock("GOOG"), stock("GOOG")])
    usage = Usage()
    with pytest.raises(LLMError):
        market.AgentMarketData(market.DataScope()).ask(tool.wrap(model, usage), "system", [], lambda obj: obj["reply"], usage)
    assert len(alpaca_provider) == 3  # Initial watchlist plus two permitted reads.
    # 7 model calls: 2 web-tool round-trips + 2 permitted stock reads + ask_json's 3-attempt repair
    # loop on the exhausted round (web tool must not reset the round limit); only the 2 tool calls hit the session.
    assert len(session.calls) == 2 and (usage.input_tokens, usage.output_tokens) == (70, 35)


def test_exa_research_preserves_streamed_proposer_progress(monkeypatch):
    session, conn, store, billed, _ = wire(monkeypatch, Response())
    replies = [plan(), tool_request(), hyps(WINNER)]
    streamed = []

    def model(system, messages, on_delta=None):
        reply = replies.pop(0)
        if on_delta is not None:
            on_delta("Synthetic research progress.")
            streamed.append(reply)
        return reply, {"input_tokens": 10, "output_tokens": 5}

    agent.run_research(conn, {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda *args: _dataset(n_contracts=60))
    thinking = [event for event in store.events if event[0] == "thinking"]
    assert store.finished[0] == "succeeded" and len(session.calls) == 1
    assert len(streamed) == 2 and sum(bool(event[2].get("end")) for event in thinking) == 2
    assert any(event[1] == "Synthetic research progress." for event in thinking)
    assert len(billed) == 1 and billed[0][3:5] == (30, 15)


@pytest.mark.parametrize("research", [False, True])
def test_database_failure_after_retrieval_does_not_charge_consumed_model_usage(monkeypatch, research):
    session, conn, store, billed, _ = wire(monkeypatch, Response())

    def fail_on_receipt(cur, run_id, kind, message, data=None):
        if data and data.get("provider") == "exa":
            raise pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")
        store.events.append((kind, message, data))

    monkeypatch.setattr(agent.repo, "add_event", fail_on_receipt)
    model, _ = scripted(([plan()] if research else []) + [tool_request()])
    with pytest.raises(pymysql.err.OperationalError):
        if research:
            agent.run_research(conn, {**RUN, "max_hypotheses": 1}, model=model,
                               dataset_fn=lambda *args: _dataset(n_contracts=60))
        else:
            agent.run_copilot(conn, {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert store.finished[0] == "failed" and len(session.calls) == 1
    assert billed == []


@pytest.mark.parametrize("exa_enabled", ["0", "1"])
def test_cancelled_final_copilot_reply_cannot_save_or_apply_actions(monkeypatch, exa_enabled):
    monkeypatch.setenv("TAU_EXA_ENABLED", exa_enabled)
    session, conn, store, billed, saved = wire(monkeypatch)
    monkeypatch.setattr(agent, "act", lambda *args: pytest.fail("Cancelled actions must not run."))

    def model(system, messages):
        store.status = "cancelled"
        return json.dumps({"reply": "Cancelled response.", "actions": [{"type": "pause", "deployment_id": 3}]}), {
            "input_tokens": 9, "output_tokens": 3}

    agent.run_copilot(conn, {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert store.finished is None and saved == [] and session.calls == []
    assert len(billed) == 1 and billed[0][3:5] == (9, 3)


@pytest.mark.parametrize("research", [False, True])
def test_gated_news_wrapper_composes_with_exa_and_market_data_offline(monkeypatch, tmp_path, alpaca_provider, research):
    # This covers wrapper compatibility only. The WIP news transport/journal is synthetic here.
    monkeypatch.setenv("TAU_WORLDMONITOR_ENABLED", "1")
    monkeypatch.setenv("WORLDMONITOR_API_KEY", "fake-news-key")
    monkeypatch.setenv("TAU_WORLDMONITOR_JOURNAL", str(tmp_path / "synthetic-news.sqlite"))
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "fake-alpaca-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fake-alpaca-secret")
    monkeypatch.setenv("TAU_ALPACA_SYMBOLS", "SPY")
    monkeypatch.setenv("TAU_ALPACA_FEED", "iex")
    monkeypatch.setattr(market, "utc_now", lambda: NOW)
    session, conn, store, billed, saved = wire(monkeypatch, Response())
    news_scopes = []
    news_source = {"source_id": "worldmonitor:synthetic", "url": "https://example.com/synthetic-news",
                   "publisher_host": "example.com", "excerpt": "Synthetic news context."}

    def read_news(self, request):
        self.checkpoint()
        news_scopes.append(self.scope)
        self.sources[news_source["source_id"]] = news_source
        return {"provider": "worldmonitor", "status": "available", "sources": [news_source]}

    monkeypatch.setattr(news.AgentNews, "_read", read_news)
    stock = json.dumps({"market_data_requests": [{"kind": "bars", "symbols": ["AAPL"], "lookback_days": 7}]})
    news_request = json.dumps({"news_requests": [{"kind": "headlines"}]})
    final = hyps(WINNER) if research else '{"reply":"Compared the synthetic evidence.","actions":[]}'
    model, prompts = scripted(([plan()] if research else []) + [tool_request(), news_request, stock, final])
    ds = _dataset(n_contracts=60)
    if research:
        agent.run_research(conn, {**RUN, "max_hypotheses": 1}, model=model, dataset_fn=lambda *args: ds)
    else:
        agent.run_copilot(conn, {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert store.finished[0] == "succeeded" and len(session.calls) == len(news_scopes) == 1
    assert news_scopes[0].historical is research
    if research:
        assert news_scopes[0].cutoff.timestamp() == ds.cutoff_ts
    assert len(alpaca_provider) == 2
    assert "Synthetic news context." in str(prompts[-1]) and "A synthetic announcement." in str(prompts[-1])
    assert '"last_close": 102' in str(prompts[-1])
    expected = (50, 25) if research else (40, 20)
    assert len(billed) == 1 and billed[0][3:5] == expected
    if not research:
        assert news_source["url"] in saved[0][3] and source()["url"] in saved[0][3]
