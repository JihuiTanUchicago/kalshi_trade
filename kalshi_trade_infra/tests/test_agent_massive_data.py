"""Synthetic Massive integration through real TAU research/copilot entry points."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from app import agent, agent_market_data as market, massive_data
from app.llm import Usage
from tests.test_agent_market_data import final_check, provider as alpaca_provider, scripted
from tests.test_app_agent import Conn, RUN, Store, WINNER, hyps, plan
from tests.test_app_backtest import _dataset

NOW = datetime(2027, 2, 1, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "0")
    monkeypatch.setenv("TAU_MASSIVE_ENABLED", "1")
    monkeypatch.setenv("MASSIVE_API_KEY", "fake-massive-private")
    monkeypatch.setenv("TAU_MASSIVE_FX_FEED", "end_of_day")
    monkeypatch.setenv("TAU_MASSIVE_FX_SYMBOLS", "EURUSD")
    monkeypatch.setenv("TAU_MASSIVE_DATASETS", "fx,treasury_yields,funding_conditions,options")
    monkeypatch.setattr(market, "utc_now", lambda: NOW)
    market._CACHE.clear()
    yield
    market._CACHE.clear()


@pytest.fixture
def provider(monkeypatch):
    calls = []

    class Client:
        def __init__(self, config, *, checkpoint):
            self.config, self.checkpoint = config, checkpoint

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def metadata(self, asset="forex"):
            return {"provider": "massive", "asset_class": asset, "feed": self.config.fx_feed, "retrieved_at": market.iso(NOW)}

        def fx_bars(self, symbols, start, end, *, timeframe):
            self.checkpoint()
            calls.append(("fx_bars", symbols, start, end, timeframe))
            rows = [{"timestamp": market.iso(end - timedelta(hours=1)), "interval_end": market.iso(end),
                     "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2345, "volume": None}]
            return {**self.metadata(), "bars": {s: rows for s in symbols}, "complete": True,
                    "end_exclusive": market.iso(end), "aggregate_basis": "bid_ask_quotes"}

        def fx_quotes(self, symbols):
            self.checkpoint()
            calls.append(("fx_quotes", symbols))
            return {**self.metadata(), "snapshots": {s: {"status": "available", "latest_quote": {
                "timestamp": market.iso(NOW - timedelta(seconds=175)), "bid": 1.12, "ask": 1.13, "crossed": False}}
                for s in symbols}}

        def macro(self, dataset, start, end):
            self.checkpoint()
            calls.append(("macro", dataset, start, end))
            return {**self.metadata("economy"), "dataset": dataset, "point_in_time": False,
                    "observations": [{"date": end.date().isoformat(), "yield_10_year": 4.2}]}

        def options_chain(self, query):
            self.checkpoint()
            calls.append(("options_chain", query))
            return {**self.metadata("us_option"), "complete": False, "sample_limit": 50, "snapshots": {
                "O:SPY270219C00580000": {"status": "available", "greeks": {"delta": 0.5},
                    "implied_volatility": 0.2, "open_interest": 100, "latest_quote": {
                        "timestamp": market.iso(NOW - timedelta(seconds=1)), "bid": 2, "ask": 2.1, "crossed": False},
                    "underlying_price": 580, "underlying_timestamp": market.iso(NOW - timedelta(minutes=15))}}}

    monkeypatch.setattr(market, "MassiveDataClient", Client)
    return calls


def data():
    instance = market.AgentMarketData(market.DataScope())
    instance.massive_config = massive_data.Config.from_env()
    return instance


def query(kind, **kwargs):
    return {"provider": "massive", "kind": kind, **kwargs}


def test_both_disabled_preserves_the_original_model_contract(monkeypatch, provider):
    monkeypatch.setenv("TAU_MASSIVE_ENABLED", "0")
    model, prompts = scripted(['{"reply":"normal"}'])
    messages = [{"role": "user", "content": "original"}]
    assert market.AgentMarketData(market.DataScope()).ask(model, "system", messages, final_check, Usage()) == "normal"
    assert prompts == [("system", messages)] and provider == []


def test_massive_only_gets_fx_and_daily_rates_and_can_request_options(provider):
    request = {"market_data_requests": [query("options_chain", symbols=["SPY"], strike_min=570, strike_max=590)]}
    model, prompts = scripted([json.dumps(request), '{"reply":"I checked the filtered chain."}'])
    usage = Usage()
    assert market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, usage) == "I checked the filtered chain."
    assert [call[0] for call in provider] == ["fx_bars", "macro", "macro", "options_chain"]
    assert provider[0][3] == NOW.replace(hour=0, minute=0)
    assert '"last_close": 1.2345' in prompts[0][1][-1]["content"]
    assert '"volume": null' in prompts[0][1][-1]["content"]
    assert '"delta": 0.5' in prompts[1][1][-1]["content"]
    assert '"underlying_price_fresh": false' in prompts[1][1][-1]["content"]
    assert "fake-massive-private" not in str(prompts)
    assert (usage.input_tokens, usage.output_tokens) == (20, 10)


def test_alpaca_and_massive_coexist_and_missing_massive_credentials_do_not_break_alpaca(monkeypatch, provider, alpaca_provider):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "fake-alpaca-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fake-alpaca-secret")
    monkeypatch.setenv("TAU_ALPACA_SYMBOLS", "SPY")
    monkeypatch.setenv("ALPACA_DATA_ENDPOINT", "https://data.alpaca.markets")
    monkeypatch.setenv("TAU_ALPACA_FEED", "iex")
    monkeypatch.delenv("MASSIVE_API_KEY")
    model, prompts = scripted(['{"reply":"Equities available; Massive unavailable."}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert alpaca_provider == [("snapshots", ["SPY"])] and provider == []
    content = prompts[0][1][-1]["content"]
    assert "501.25" in content and '"code": "not_configured"' in content


def test_both_configured_providers_route_explicit_massive_and_legacy_alpaca_requests(monkeypatch, provider, alpaca_provider):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "fake-alpaca-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fake-alpaca-secret")
    monkeypatch.setenv("TAU_ALPACA_SYMBOLS", "SPY")
    monkeypatch.setenv("ALPACA_DATA_ENDPOINT", "https://data.alpaca.markets")
    monkeypatch.setenv("TAU_ALPACA_FEED", "iex")
    request = {"market_data_requests": [query("options_chain", symbols=["SPY"]),
                                        {"kind": "bars", "symbols": ["AAPL"], "lookback_days": 7}]}
    model, prompts = scripted([json.dumps(request), '{"reply":"Both data sources checked."}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert alpaca_provider[0] == ("snapshots", ["SPY"])
    assert alpaca_provider[1][:2] == ("bars", ["AAPL"])
    assert provider[-1][0] == "options_chain"
    assert '"provider": "alpaca"' in prompts[0][1][-1]["content"]
    assert '"provider": "massive"' in prompts[0][1][-1]["content"]


def test_disabled_provider_does_not_make_requests_or_use_an_existing_cache(provider, monkeypatch):
    instance = data()
    request = query("options_chain", symbols=["SPY"])
    assert instance._read(request)["status"] == "available"
    monkeypatch.setenv("TAU_MASSIVE_ENABLED", "0")
    blocked = data()._read(request)
    assert blocked["code"] == "provider_disabled" and len(provider) == 1


def test_current_quote_and_option_freshness_are_recomputed_on_cache_hits(monkeypatch, provider):
    monkeypatch.setenv("TAU_MASSIVE_FX_FEED", "realtime")
    instance = data()
    request = query("fx_quotes", symbols=["EURUSD"])
    first = instance._read(request)
    assert first["status"] == "available"
    monkeypatch.setattr(market, "utc_now", lambda: NOW + timedelta(seconds=10))
    cached = instance._read(request)
    assert cached["status"] == "stale"
    assert cached["snapshots"]["C:EURUSD"]["latest_quote"]["age_seconds"] == 185
    assert len(provider) == 1
    cached["snapshots"]["C:EURUSD"]["latest_quote"]["bid"] = 999
    assert instance._read(request)["snapshots"]["C:EURUSD"]["latest_quote"]["bid"] == 1.12


def test_cache_separates_credentials_feed_dataset_configuration_and_provider(provider, monkeypatch):
    request = query("options_chain", symbols=["SPY"])
    for key, feed, datasets in (("a", "end_of_day", "fx,options"), ("b", "end_of_day", "fx,options"),
                                ("b", "realtime", "fx,options"), ("b", "realtime", "options")):
        monkeypatch.setenv("MASSIVE_API_KEY", key)
        monkeypatch.setenv("TAU_MASSIVE_FX_FEED", feed)
        monkeypatch.setenv("TAU_MASSIVE_DATASETS", datasets)
        assert data()._read(request)["status"] == "available"
    assert len(provider) == 4


def test_research_clamps_fx_window_and_denies_macro_quotes_and_chains_without_http(provider):
    start, cutoff = NOW - timedelta(days=10), NOW - timedelta(days=3)
    instance = market.AgentMarketData(market.DataScope(start, cutoff))
    instance.massive_config = massive_data.Config.from_env()
    assert instance._read(query("fx_bars", symbols=["EURUSD"], lookback_days=90))["end_exclusive"] == market.iso(cutoff)
    assert provider[0][2:4] == (start, cutoff)
    for request in (query("fx_quotes", symbols=["EURUSD"]), query("options_chain", symbols=["SPY"]),
                    query("macro", dataset="treasury_yields")):
        assert instance._read(request)["code"] == "time_boundary"
    assert len(provider) == 1


def test_macro_does_not_claim_live_rates_and_old_observations_are_stale(provider, monkeypatch):
    instance = data()
    result = instance._read(query("macro", dataset="treasury_yields"))
    assert result["point_in_time"] is False and result["observation_count"] == 1
    assert result["observation_age_days"] == 0 and "not a publication" in result["freshness_note"]
    cached = market._freshness(result, NOW + timedelta(days=8))
    assert cached["status"] == "stale" and cached["observation_age_days"] == 8


def test_daily_macro_cache_reuses_identical_observation_dates_across_minutes(provider, monkeypatch):
    instance = data()
    request = query("macro", dataset="treasury_yields")
    first = instance._read(request)
    monkeypatch.setattr(market, "utc_now", lambda: NOW + timedelta(minutes=1))
    cached = instance._read(request)
    assert len(provider) == 1 and cached["retrieved_at"] == first["retrieved_at"]
    assert cached["served_at"] != first["served_at"]


def test_macro_series_keep_independent_dates_when_latest_row_contains_only_a_policy_rate(provider, monkeypatch):
    def staggered(self, dataset, start, end):
        self.checkpoint()
        return {**self.metadata("economy"), "dataset": dataset, "point_in_time": False,
                "observations": [{"date": "2027-01-29", "secured_overnight_financing_rate": 4.1},
                                 {"date": "2027-02-01", "interest_on_reserve_balances": 4.2,
                                  "secured_overnight_financing_rate": None}]}

    monkeypatch.setattr(market.MassiveDataClient, "macro", staggered)
    result = data()._read(query("macro", dataset="funding_conditions"))
    assert result["observation_age_days"] == 0
    sofr = result["latest_values"]["secured_overnight_financing_rate"]
    assert sofr == {"value": 4.1, "observation_date": "2027-01-29", "observation_age_days": 3, "stale": False}
    assert result["latest_values"]["interest_on_reserve_balances"]["observation_age_days"] == 0


def test_macro_latest_values_retain_a_stale_series_outside_the_recent_row_sample(provider, monkeypatch):
    def staggered(self, dataset, start, end):
        self.checkpoint()
        rows = [{"date": (NOW - timedelta(days=14)).date().isoformat(), "secured_overnight_financing_rate": 0}]
        rows.extend({"date": (NOW - timedelta(days=day)).date().isoformat(), "interest_on_reserve_balances": 4.2}
                    for day in range(13, -1, -1))
        return {**self.metadata("economy"), "dataset": dataset, "point_in_time": False, "observations": rows}

    monkeypatch.setattr(market.MassiveDataClient, "macro", staggered)
    result = data()._read(query("macro", dataset="funding_conditions"))
    assert len(result["sample"]) == 12 and all("secured_overnight_financing_rate" not in row for row in result["sample"])
    sofr = result["latest_values"]["secured_overnight_financing_rate"]
    assert sofr["value"] == 0 and sofr["observation_age_days"] == 14 and sofr["stale"] is True
    cached = market._freshness(result, NOW + timedelta(days=1))
    assert cached["latest_values"]["secured_overnight_financing_rate"]["observation_age_days"] == 15


@pytest.mark.parametrize("query_obj", [query("fx_quotes", symbols=["EURUSD"], lookback_days=1),
    query("fx_bars", symbols=["EURUSD"], timeframe=[]), query("macro", dataset=[]), query("orders"),
    query("fx_bars", symbols=["EURUSD"], url="https://evil.invalid"), query("fx_bars", symbols=["EURUSD"], lookback_days=True),
    query("options_chain", symbols=["SPY"], lookback_days=1), {"provider": [], "kind": "fx_quotes"},
    {"kind": []}, query("fx_bars", symbols=["EURUSD"] * 4)])
def test_invalid_model_requests_can_be_repaired_instead_of_crashing_the_worker(query_obj):
    with pytest.raises(ValueError):
        market._request(query_obj)


def test_dataset_disabled_is_enforced_before_cache_or_network(monkeypatch, provider):
    monkeypatch.setenv("TAU_MASSIVE_DATASETS", "options")
    instance = data()
    assert instance._read(query("fx_bars", symbols=["EURUSD"]))["code"] == "dataset_disabled"
    assert provider == []


def test_massive_http_budget_includes_initial_reads_and_stops_before_extra_requests(monkeypatch, provider):
    monkeypatch.setattr(market, "MAX_MASSIVE_HTTP_REQUESTS", 1)
    model, prompts = scripted(['{"reply":"Only FX was available within the request budget."}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert len(provider) == 1 and '"code": "request_limit"' in prompts[0][1][-1]["content"]


def test_cancel_during_initial_reads_stops_before_any_model_call(provider):
    def checkpoint():
        if provider:
            raise agent.Cancelled()

    model, prompts = scripted([])
    with pytest.raises(agent.Cancelled):
        market.AgentMarketData(market.DataScope(), checkpoint=checkpoint).ask(model, "system", [], final_check, Usage())
    assert len(provider) == 1 and prompts == []


def test_actual_research_entrypoint_uses_fx_only_and_bills_data_request_rounds(monkeypatch, provider):
    store, billed = Store(monkeypatch), []
    monkeypatch.setattr(agent.billing, "charge_usage", lambda *args: billed.append(args))
    request = {"market_data_requests": [query("options_chain", symbols=["SPY"]), query("macro", dataset="funding_conditions")]}
    model, prompts = scripted([plan(), json.dumps(request), hyps(WINNER)])
    ds = _dataset(n_contracts=60)
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model, dataset_fn=lambda *args: ds)
    assert store.finished[0] == "succeeded" and len(store.strategies) == 1
    assert all(call[0] == "fx_bars" and call[3].timestamp() <= ds.cutoff_ts for call in provider)
    assert '"code": "time_boundary"' in prompts[2][1][-1]["content"]
    assert billed[0][3:5] == (30, 15)
    contexts = [event[2]["market_data"] for event in store.events if event[2] and "market_data" in event[2]]
    assert len(contexts) == 3 and all(p["provider"] == "massive" for p in contexts)


def test_actual_copilot_entrypoint_can_request_and_receive_option_chain(monkeypatch, provider):
    records, billed = [], []
    r = agent.repo
    monkeypatch.setattr(r, "get_user", lambda *args: {"id": 7})
    monkeypatch.setattr(r, "heartbeat", lambda *args: "running")
    monkeypatch.setattr(r, "chat_messages", lambda *args, **kwargs: [{"role": "user", "content": "Inspect SPY option IV."}])
    monkeypatch.setattr(r, "list_deployments", lambda *args: [])
    monkeypatch.setattr(r, "list_strategies", lambda *args, **kwargs: [])
    monkeypatch.setattr(r, "add_chat", lambda *args: records.append(args))
    monkeypatch.setattr(r, "add_event", lambda *args: None)
    monkeypatch.setattr(r, "finish_run", lambda *args: None)
    monkeypatch.setattr(agent.billing, "charge_usage", lambda *args: billed.append(args))
    request = {"market_data_requests": [query("options_chain", symbols=["SPY"], contract_type="call")]}
    model, prompts = scripted([json.dumps(request), '{"reply":"The sampled call IV is 20%.","actions":[]}'])
    agent.run_copilot(Conn(), {"id": 1, "user_id": 7, "kind": "chat"}, model=model)
    assert provider[-1][0] == "options_chain" and '"implied_volatility": 0.2' in prompts[1][1][-1]["content"]
    assert records[0][2:] == ("agent", "The sampled call IV is 20%.")
    assert billed[0][3:5] == (20, 10)


def test_real_massive_client_decodes_http_into_the_model_context_without_credentials(monkeypatch):
    from tests.test_massive_data import NOW as provider_now, KEY, client, option, page

    monkeypatch.setenv("TAU_MASSIVE_DATASETS", "options")
    monkeypatch.setattr(market, "utc_now", lambda: provider_now)
    actual_client, session, _ = client(page([option()]))

    def factory(config, *, checkpoint):
        actual_client.checkpoint = checkpoint
        return actual_client

    monkeypatch.setattr(market, "MassiveDataClient", factory)
    request = {"market_data_requests": [query("options_chain", symbols=["SPY"], expiration_date="2026-10-23")]}
    model, prompts = scripted([json.dumps(request), '{"reply":"The sampled delta is 0.5."}'])
    usage = Usage()
    assert market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, usage) == "The sampled delta is 0.5."
    assert session.calls[0][0] == "https://api.massive.com/v3/snapshot/options/SPY"
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer " + KEY
    assert KEY not in str(prompts) and '"delta": 0.5' in prompts[1][1][-1]["content"]
    assert (usage.input_tokens, usage.output_tokens) == (20, 10) and session.closed
