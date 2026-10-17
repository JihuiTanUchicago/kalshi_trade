"""Synthetic Databento data through Tau's real research/copilot interfaces."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from app import agent, agent_market_data as market, databento_data as data
from app.llm import Usage
from tests.test_agent_market_data import final_check, provider as alpaca_provider, scripted
from tests.test_agent_massive_data import provider as massive_provider
from tests.test_app_agent import Conn, RUN, Store, WINNER, hyps, plan
from tests.test_app_backtest import _dataset
from tests.test_databento_data import Response, availability, bar, client, records

NOW = datetime(2027, 2, 1, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "0")
    monkeypatch.setenv("TAU_MASSIVE_ENABLED", "0")
    monkeypatch.setenv("TAU_DATABENTO_ENABLED", "1")
    monkeypatch.setenv("DATABENTO_API_KEY", "fake-databento-agent-private")
    monkeypatch.setenv("TAU_DATABENTO_DATASETS", "EQUS.MINI,GLBX.MDP3")
    monkeypatch.setenv("TAU_DATABENTO_MAX_COST_USD", "0.10")
    monkeypatch.setattr(market, "utc_now", lambda: NOW)
    market._CACHE.clear()
    yield
    market._CACHE.clear()


@pytest.fixture
def provider(monkeypatch):
    calls = []
    class Client:
        def __init__(self, config, *, budget, before_request, checkpoint):
            self.config, self.budget = config, budget
            self.before_request, self.checkpoint = before_request, checkpoint

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def bars(self, symbols, dataset, start, end, *, timeframe):
            for _ in range(2):
                self.before_request()  # Availability and cost metadata attempts.
            self.budget.reserve(Decimal("0.03"))
            self.before_request()  # One paid download attempt.
            calls.append((symbols, dataset, start, end, timeframe))
            bars = [{"timestamp": market.iso(end - timedelta(hours=1)), "interval_end": market.iso(end),
                     "open": 100, "high": 103, "low": 99, "close": 101, "volume": 200,
                     "instrument_id": 123, "publisher_id": 1}]
            return {"provider": "databento", "feed": dataset, "dataset": dataset, "point_in_time": False,
                    "estimated_cost_usd": "0.03", "reserved_cost_usd": str(self.budget.reserved),
                    "bars": {symbol: bars for symbol in symbols}, "complete": True}

    monkeypatch.setattr(market, "DatabentoDataClient", Client)
    return calls


def query(dataset="EQUS.MINI", symbols=None, **kwargs):
    return {"provider": "databento", "kind": "bars", "dataset": dataset, "symbols": symbols or ["SPY"], **kwargs}


def instance(scope=None):
    result = market.AgentMarketData(scope or market.DataScope())
    result._prepare_databento()
    return result


def test_disabled_preserves_original_model_contract_and_makes_no_provider_call(monkeypatch, provider):
    monkeypatch.setenv("TAU_DATABENTO_ENABLED", "0")
    messages = [{"role": "user", "content": "hello"}]
    model, prompts = scripted(['{"reply":"hello"}'])
    assert market.AgentMarketData(market.DataScope()).ask(model, "system", messages, final_check, Usage()) == "hello"
    assert prompts == [("system", messages)] and provider == []


def test_enabled_is_on_demand_without_automatic_downloads_and_does_not_leak_key(provider):
    model, prompts = scripted(['{"reply":"ready"}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert provider == [] and '"status": "on_demand"' in prompts[0][1][-1]["content"]
    assert '"databento": ["EQUS.MINI", "GLBX.MDP3"]' in prompts[0][1][-1]["content"]
    assert "Databento historical OHLCV" in prompts[0][0] and "fake-databento-agent-private" not in str(prompts)


def test_stock_and_futures_requests_use_shared_loop_metering_and_context(provider):
    request = {"market_data_requests": [query(), query("GLBX.MDP3", ["ESZ6"])]}
    model, prompts = scripted([json.dumps(request), '{"reply":"I checked both datasets."}'])
    usage = Usage()
    assert market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, usage) == "I checked both datasets."
    assert [call[1] for call in provider] == ["EQUS.MINI", "GLBX.MDP3"]
    assert provider[0][3] == NOW and provider[0][2] == NOW - timedelta(days=7)
    assert '"last_close": 101' in prompts[1][1][-1]["content"] and '"ESZ6"' in prompts[1][1][-1]["content"]
    assert (usage.input_tokens, usage.output_tokens) == (20, 10)


def test_research_request_uses_only_training_range_and_does_not_accept_model_dates(provider):
    cutoff = NOW - timedelta(days=20)
    start = cutoff - timedelta(days=2)
    result = instance(market.DataScope(start, cutoff))._read(query(lookback_days=90))
    assert result["status"] == "available" and provider[0][2:4] == (start, cutoff)
    with pytest.raises(ValueError):
        market._request(query(end=market.iso(NOW)))


@pytest.mark.parametrize("obj", [query(dataset="ALL"), query(symbols=["ALL_SYMBOLS"]), query(symbols=["ES.c.0"]),
    query(timeframe="5Min"), query(timeframe=[]), query(lookback_days=True), query(lookback_days=91),
    query(url="https://evil.invalid"), {**query(), "kind": "snapshots"}, {**query(), "kind": "orders"},
    {**query(), "stype_in": "parent"}, {**query(), "dataset": None}])
def test_model_cannot_expand_scope_or_request_current_or_trading_endpoints(obj):
    with pytest.raises(ValueError):
        market._request(obj)


def test_dataset_disabled_before_network_including_after_a_cache_hit(monkeypatch, provider):
    md = instance()
    assert md._read(query())["status"] == "available"
    monkeypatch.setenv("TAU_DATABENTO_DATASETS", "GLBX.MDP3")
    md._prepare_databento()
    assert md._read(query())["code"] == "dataset_disabled" and len(provider) == 1


def test_missing_key_is_visible_in_context_without_model_data_guide(monkeypatch, provider):
    monkeypatch.delenv("DATABENTO_API_KEY")
    model, prompts = scripted(['{"reply":"Data unavailable."}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert '"code": "not_configured"' in prompts[0][1][-1]["content"]
    assert "Databento historical OHLCV" not in prompts[0][0] and provider == []


def test_budget_is_shared_across_requests_and_ask_calls_on_one_context(monkeypatch, provider):
    monkeypatch.setenv("TAU_DATABENTO_MAX_COST_USD", "0.05")
    md = market.AgentMarketData(market.DataScope())
    for lookback in (1, 2):
        model, prompts = scripted([json.dumps({"market_data_requests": [query(lookback_days=lookback)]}), '{"reply":"checked"}'])
        md.ask(model, "system", [], final_check, Usage())
    assert len(provider) == 1 and md.databento_budget.reserved == Decimal("0.03")
    assert '"code": "cost_limit"' in prompts[1][1][-1]["content"]


def test_cache_is_provider_credential_and_cap_isolated(monkeypatch, provider):
    md = instance()
    assert md._read(query())["status"] == "available"
    assert md._read(query())["status"] == "available" and len(provider) == 1
    cached = instance()._read(query())
    assert cached["cache_hit"] is True and cached["download_started"] is False
    assert cached["reserved_cost_usd"] == "0" and len(provider) == 1
    monkeypatch.setenv("DATABENTO_API_KEY", "a-different-private-key")
    assert instance()._read(query())["status"] == "available" and len(provider) == 2
    monkeypatch.setenv("TAU_DATABENTO_MAX_COST_USD", "0")
    assert instance()._read(query())["code"] == "cost_limit" and len(provider) == 2


def test_http_attempt_budget_denies_download_after_metadata(monkeypatch, provider):
    monkeypatch.setattr(market, "MAX_DATABENTO_HTTP_REQUESTS", 2)
    model, prompts = scripted([json.dumps({"market_data_requests": [query()]}), '{"reply":"request budget reached"}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert provider == [] and '"code": "request_limit"' in prompts[1][1][-1]["content"]


def test_both_existing_providers_can_coexist_with_databento(monkeypatch, provider, alpaca_provider, massive_provider):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "fake-alpaca-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fake-alpaca-secret")
    monkeypatch.setenv("TAU_ALPACA_SYMBOLS", "SPY")
    monkeypatch.setenv("TAU_MASSIVE_ENABLED", "1")
    monkeypatch.setenv("MASSIVE_API_KEY", "fake-massive-key")
    monkeypatch.setenv("TAU_MASSIVE_DATASETS", "fx")
    monkeypatch.setenv("TAU_MASSIVE_FX_SYMBOLS", "EURUSD")
    request = {"market_data_requests": [query()]}
    model, prompts = scripted([json.dumps(request), '{"reply":"checked"}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert len(alpaca_provider) == len(massive_provider) == len(provider) == 1
    assert '"provider": "alpaca"' in prompts[0][1][-1]["content"]
    assert '"provider": "massive"' in prompts[0][1][-1]["content"]
    assert '"provider": "databento"' in prompts[1][1][-1]["content"]


def test_negative_or_zero_futures_closes_do_not_generate_misleading_percentage_returns():
    bars = [{"timestamp": market.iso(NOW - timedelta(hours=1)), "interval_end": market.iso(NOW),
             "open": 0, "high": 1, "low": -2, "close": value, "volume": 1} for value in (0, -1)]
    result = market._history_summary({"bars": {"CLJ0": bars}})
    assert result["symbols"]["CLJ0"]["close_to_close_return_pct"] is None


def test_actual_research_entrypoint_consumes_databento_and_bills_extra_model_round(monkeypatch, provider):
    store, billed = Store(monkeypatch), []
    monkeypatch.setattr(agent.billing, "charge_usage", lambda *args: billed.append(args))
    model, prompts = scripted([plan(), json.dumps({"market_data_requests": [query("GLBX.MDP3", ["ESZ6"])]}), hyps(WINNER)])
    ds = _dataset(n_contracts=60)
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model, dataset_fn=lambda *args: ds)
    assert store.finished[0] == "succeeded" and len(store.strategies) == 1
    assert provider[0][2].timestamp() >= ds.start_ts and provider[0][3].timestamp() == ds.cutoff_ts
    assert '"last_close": 101' in prompts[2][1][-1]["content"] and billed[0][3:5] == (30, 15)
    events = [item[2]["market_data"] for item in store.events if item[2] and "market_data" in item[2]]
    assert len(events) == 2 and all(event["provider"] == "databento" for event in events)


def test_actual_copilot_entrypoint_can_request_historical_stock_context(monkeypatch, provider):
    saved, billed = [], []
    monkeypatch.setattr(agent.repo, "get_user", lambda *args: {"id": 7})
    monkeypatch.setattr(agent.repo, "heartbeat", lambda *args: "running")
    monkeypatch.setattr(agent.repo, "chat_messages", lambda *args, **kwargs: [{"role": "user", "content": "Check SPY history."}])
    monkeypatch.setattr(agent.repo, "list_deployments", lambda *args: [])
    monkeypatch.setattr(agent.repo, "list_strategies", lambda *args, **kwargs: [])
    monkeypatch.setattr(agent.repo, "add_chat", lambda *args: saved.append(args))
    monkeypatch.setattr(agent.repo, "add_event", lambda *args: None)
    monkeypatch.setattr(agent.repo, "finish_run", lambda *args: None)
    monkeypatch.setattr(agent.billing, "charge_usage", lambda *args: billed.append(args))
    model, prompts = scripted([json.dumps({"market_data_requests": [query()]}), '{"reply":"SPY history checked.","actions":[]}'])
    agent.run_copilot(Conn(), {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert saved[0][2:] == ("agent", "SPY history checked.") and len(provider) == 1
    assert '"last_close": 101' in prompts[1][1][-1]["content"] and billed[0][3:5] == (20, 10)


def test_real_client_decodes_fixture_http_into_context_with_cutoff_and_no_credentials(monkeypatch):
    cutoff = data.timestamp("2026-10-15T15:30:00Z")
    actual, session, _ = client(Response(availability()), Response(0.03), records(bar(), bar(ts="2026-10-15T15:00:00Z")))
    def factory(config, *, budget, before_request, checkpoint):
        actual.config, actual.budget = config, budget
        actual.before_request, actual.checkpoint = before_request, checkpoint
        return actual
    monkeypatch.setattr(market, "DatabentoDataClient", factory)
    model, prompts = scripted([json.dumps({"market_data_requests": [query()]}), '{"reply":"Only completed bars."}'])
    md = market.AgentMarketData(market.DataScope(cutoff - timedelta(days=1), cutoff))
    assert md.ask(model, "system", [], final_check, Usage()) == "Only completed bars."
    result = json.loads(prompts[1][1][-1]["content"].split("\n", 1)[1])[0]["data"]
    assert result["symbols"]["SPY"]["bar_count"] == 1 and result["excluded_bars"] == 1
    assert result["symbols"]["SPY"]["last_completed_at"] == "2026-10-15T15:00:00Z"
    assert session.calls[-1][2]["data"]["end"] == market.iso(cutoff)
    assert "fake-databento-agent-private" not in str(prompts) and session.closed


def test_data_channel_stays_exclusive_and_round_limit_still_enforces_final_output(provider):
    request = json.dumps({"market_data_requests": [query()]})
    mixed = json.dumps({"market_data_requests": [query()], "reply": "premature"})
    model, prompts = scripted([mixed, request, request, request, '{"reply":"done"}'])
    usage = Usage()
    assert market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, usage) == "done"
    assert len(provider) == 1 and (usage.input_tokens, usage.output_tokens) == (50, 25)


def test_research_cancellation_propagates_after_data_request_before_provider_read(provider):
    model, prompts = scripted([json.dumps({"market_data_requests": [query()]})])
    def checkpoint():
        if prompts:
            raise agent.Cancelled()
    with pytest.raises(agent.Cancelled):
        market.AgentMarketData(market.DataScope(), checkpoint=checkpoint).ask(model, "system", [], final_check, Usage())
    assert provider == []
