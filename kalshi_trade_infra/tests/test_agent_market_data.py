"""Synthetic agent/provider integration; no real model, broker or database calls."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import agent, agent_market_data as market
from app.alpaca_data import MarketDataError, iso
from app.llm import LLMError, Usage
from tests.test_app_agent import Conn, RUN, Store, WINNER, hyps, plan
from tests.test_app_backtest import _dataset

NOW = datetime(2027, 2, 1, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("TAU_MASSIVE_ENABLED", "0")
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "fake-agent-key-private")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fake-agent-secret-private")
    monkeypatch.setenv("TAU_ALPACA_FEED", "iex")
    monkeypatch.setenv("TAU_ALPACA_SYMBOLS", "SPY")
    monkeypatch.setenv("ALPACA_DATA_ENDPOINT", "https://data.alpaca.markets")
    monkeypatch.setattr(market, "utc_now", lambda: NOW)
    market._CACHE.clear()
    yield
    market._CACHE.clear()


@pytest.fixture
def provider(monkeypatch):
    calls = []

    class Client:
        def __init__(self, config):
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def metadata(self):
            return {"provider": "alpaca", "feed": self.config.feed, "coverage": self.config.coverage,
                    "retrieved_at": iso(NOW), "currency": "USD"}

        def snapshots(self, symbols):
            calls.append(("snapshots", symbols))
            return {**self.metadata(), "snapshots": {s: {"status": "available",
                    "latest_trade": {"timestamp": iso(NOW - timedelta(seconds=175)), "price": 501.25, "size": 2}}
                    for s in symbols}}

        def bars(self, symbols, start, end, *, timeframe):
            calls.append(("bars", symbols, start, end, timeframe))
            points = [{"timestamp": iso(end - timedelta(hours=2)), "interval_end": iso(end - timedelta(hours=1)),
                       "open": 100, "high": 103, "low": 99, "close": 101, "volume": 1000},
                      {"timestamp": iso(end - timedelta(hours=1)), "interval_end": iso(end),
                       "open": 101, "high": 104, "low": 100, "close": 102, "volume": 1200}]
            return {**self.metadata(), "start": iso(start), "end_exclusive": iso(end), "timeframe": timeframe,
                    "adjustment": "raw", "complete": True, "bars": {s: points for s in symbols}}

    monkeypatch.setattr(market, "AlpacaDataClient", Client)
    return calls


def scripted(replies):
    prompts = []

    def model(system, messages):
        prompts.append((system, messages))
        return replies.pop(0), {"input_tokens": 10, "output_tokens": 5}

    return model, prompts


def final_check(obj):
    return obj["reply"]


def test_disabled_provider_preserves_existing_model_contract(monkeypatch, provider):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "0")
    model, prompts = scripted(['{"reply":"normal response"}'])
    messages = [{"role": "user", "content": "original prompt"}]
    result = market.AgentMarketData(market.DataScope()).ask(model, "system", messages, final_check, Usage())
    assert result == "normal response" and prompts == [("system", messages)] and provider == []


def test_missing_credentials_is_visible_and_does_not_break_agent(monkeypatch, provider):
    monkeypatch.delenv("APCA_API_SECRET_KEY")
    model, prompts = scripted(['{"reply":"Stock data is unavailable."}'])
    result = market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert result == "Stock data is unavailable." and provider == []
    assert '"code": "not_configured"' in prompts[0][1][-1]["content"]
    assert "fake-agent-key-private" not in str(prompts)


def test_copilot_gets_initial_prices_and_can_request_another_symbol(provider):
    request = {"market_data_requests": [{"kind": "bars", "symbols": ["AAPL"], "lookback_days": 7}]}
    model, prompts = scripted([json.dumps(request), '{"reply":"I checked AAPL history."}'])
    usage = Usage()
    data = market.AgentMarketData(market.DataScope())
    assert data.ask(model, "system", [], final_check, usage) == "I checked AAPL history."
    assert provider[0] == ("snapshots", ["SPY"])
    assert provider[1][0:2] == ("bars", ["AAPL"])
    assert provider[1][3] == NOW - timedelta(minutes=20)
    assert "501.25" in prompts[0][1][-1]["content"]
    assert '"last_close": 102' in prompts[1][1][-1]["content"]
    assert usage.input_tokens == 20 and usage.output_tokens == 10


def test_current_snapshot_freshness_is_recomputed_on_cache_hit(monkeypatch, provider):
    data = market.AgentMarketData(market.DataScope())
    data.config = market.Config.from_env()
    query = {"kind": "snapshots", "symbols": ["SPY"]}
    first = data._read(query)
    assert first["snapshots"]["SPY"]["latest_trade"]["fresh"] is True
    monkeypatch.setattr(market, "utc_now", lambda: NOW + timedelta(seconds=10))
    second = data._read(query)
    assert second["snapshots"]["SPY"]["latest_trade"]["fresh"] is False
    assert second["snapshots"]["SPY"]["status"] == "stale"
    assert second["snapshots"]["SPY"]["latest_trade"]["age_seconds"] == 185
    assert len(provider) == 1
    second["snapshots"]["SPY"]["latest_trade"]["price"] = 999
    assert data._read(query)["snapshots"]["SPY"]["latest_trade"]["price"] == 501.25


def test_cache_does_not_cross_feed_or_credential_changes(monkeypatch, provider):
    query = {"kind": "snapshots", "symbols": ["SPY"]}
    for feed, key in (("iex", "a"), ("sip", "a"), ("sip", "b")):
        monkeypatch.setenv("TAU_ALPACA_FEED", feed)
        monkeypatch.setenv("APCA_API_KEY_ID", key)
        data = market.AgentMarketData(market.DataScope())
        data.config = market.Config.from_env()
        assert data._read(query)["feed"] == feed
    assert len(provider) == 3


def test_historical_scope_clamps_lookback_and_blocks_snapshots(provider):
    start, cutoff = NOW - timedelta(days=10), NOW - timedelta(days=3)
    data = market.AgentMarketData(market.DataScope(start, cutoff))
    data.config = market.Config.from_env()
    result = data._read({"kind": "bars", "symbols": ["SPY"], "lookback_days": 90})
    assert provider[0][2:4] == (start, cutoff)
    assert result["end_exclusive"] == iso(cutoff)
    blocked = data._read({"kind": "snapshots", "symbols": ["SPY"]})
    assert blocked["code"] == "time_boundary" and len(provider) == 1


def test_entitlement_error_is_data_not_a_fabricated_price(monkeypatch, provider):
    def denied(*args, **kwargs):
        raise MarketDataError("entitlement", "Alpaca denied this data feed.")

    monkeypatch.setattr(market.AlpacaDataClient, "snapshots", denied)
    model, prompts = scripted(['{"reply":"The selected feed is unavailable."}'])
    data = market.AgentMarketData(market.DataScope())
    assert data.ask(model, "system", [], final_check, Usage()) == "The selected feed is unavailable."
    content = prompts[0][1][-1]["content"]
    assert '"code": "entitlement"' in content and "501.25" not in content


def test_history_sample_and_full_window_summary_are_distinguished():
    rows = [{"timestamp": "2026-10-01T00:00:00Z", "interval_end": "2026-10-01T01:00:00Z",
             "close": 100 + i, "high": 120 + i, "low": 90, "volume": 10} for i in range(20)]
    result = market._history_summary({"bars": {"SPY": rows, "MISSING": []}})
    spy = result["symbols"]["SPY"]
    assert spy["bar_count"] == 20 and len(spy["sample"]) == 12
    assert spy["first_close"] == 100 and spy["last_close"] == 119 and spy["volume"] == 200
    assert result["symbols"]["MISSING"]["status"] == "missing"


@pytest.mark.parametrize("query", [
    {"kind": "orders", "symbols": ["SPY"]},
    {"kind": "bars", "symbols": ["SPY"], "url": "https://evil.invalid"},
    {"kind": "bars", "symbols": ["SPY"], "lookback_days": True},
    {"kind": "bars", "symbols": ["SPY"], "lookback_days": 91},
    {"kind": "bars", "symbols": ["SPY"], "timeframe": "10Year"},
    {"kind": "snapshots", "symbols": ["SPY"], "timeframe": "1Min"},
])
def test_agent_requests_cannot_change_endpoints_or_exceed_bounds(query):
    with pytest.raises(ValueError):
        market._request(query)


def test_tool_loop_has_a_hard_budget(provider):
    count = 0

    def model(system, messages):
        nonlocal count
        count += 1
        return json.dumps({"market_data_requests": [{"kind": "snapshots", "symbols": ["S%d" % count]}]}), {}

    with pytest.raises(LLMError, match="budget is exhausted"):
        market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert count == 4  # two data rounds, final response, one validation repair
    assert len(provider) == 3  # initial watchlist + two allowed requests


def test_cancel_during_fetch_stops_before_the_next_model_call(provider):
    model, prompts = scripted([])

    def checkpoint():
        if provider:
            raise agent.Cancelled()

    with pytest.raises(agent.Cancelled):
        market.AgentMarketData(market.DataScope(), checkpoint=checkpoint).ask(model, "system", [], final_check, Usage())
    assert len(provider) == 1 and prompts == []


def test_actual_research_worker_consumes_alpaca_data_and_meters_tool_rounds(monkeypatch, provider):
    store = Store(monkeypatch)
    billed = []
    monkeypatch.setattr(agent.billing, "charge_usage", lambda *args: billed.append(args))
    query = json.dumps({"market_data_requests": [{"kind": "bars", "symbols": ["AAPL"], "lookback_days": 7}]})
    model, prompts = scripted([plan(), query, hyps(WINNER)])
    ds = _dataset(n_contracts=60)
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model, dataset_fn=lambda *args: ds)
    assert store.finished[0] == "succeeded" and len(store.strategies) == 1
    assert all(call[0] == "bars" and call[3].timestamp() <= ds.cutoff_ts for call in provider)
    assert '"last_close": 102' in prompts[2][1][-1]["content"]
    assert "501.25" not in str(prompts)
    assert billed[0][3:5] == (30, 15)  # planning + data request + hypothesis response
    contexts = [event[2]["market_data"] for event in store.events if event[2] and "market_data" in event[2]]
    assert len(contexts) == 2 and all(context["feed"] == "iex" for context in contexts)


def test_actual_copilot_worker_receives_current_data(monkeypatch, provider):
    records = []
    r = agent.repo
    monkeypatch.setattr(r, "get_user", lambda *args: {"id": 7})
    monkeypatch.setattr(r, "heartbeat", lambda *args: "running")
    monkeypatch.setattr(r, "chat_messages", lambda *args, **kwargs: [{"role": "user", "content": "What is SPY trading at?"}])
    monkeypatch.setattr(r, "list_deployments", lambda *args: [])
    monkeypatch.setattr(r, "list_strategies", lambda *args, **kwargs: [])
    monkeypatch.setattr(r, "add_chat", lambda *args: records.append(args))
    monkeypatch.setattr(r, "add_event", lambda *args: None)
    monkeypatch.setattr(r, "finish_run", lambda *args: None)
    monkeypatch.setattr(agent.billing, "charge_usage", lambda *args: None)
    model, prompts = scripted(['{"reply":"SPY last traded at $501.25 on IEX.","actions":[]}'])
    agent.run_copilot(Conn(), {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert provider == [("snapshots", ["SPY"])]
    assert "501.25" in prompts[0][1][-1]["content"]
    assert records[0][2:] == ("agent", "SPY last traded at $501.25 on IEX.")
