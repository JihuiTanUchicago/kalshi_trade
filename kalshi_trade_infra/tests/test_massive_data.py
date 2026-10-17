"""Synthetic Massive HTTP contracts. No network, model or account calls."""
from datetime import datetime, timedelta, timezone
import json
import sys

import pytest
import requests

from app import massive_data as data
from tests.test_alpaca_data import Response, Session

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
START = NOW.replace(day=15, hour=0)
END = NOW.replace(day=16, hour=0)
KEY = "synthetic-massive-key-private"


def bar(t=None, **kwargs):
    return {"t": int((t or START).timestamp() * 1000), "o": 1.1, "h": 1.3, "l": 1.0,
            "c": 1.2, "v": 123, **kwargs}


def path(symbol="C:EURUSD", start=START, end=END):
    return "/v2/aggs/ticker/%s/range/1/hour/%d/%d" % (symbol, int(start.timestamp() * 1000), int(end.timestamp() * 1000) - 1)


def page(rows, **kwargs):
    return Response({"status": "OK", "results": rows, **kwargs})


def client(*responses, feed="end_of_day", datasets=data.DATASETS, checkpoint=lambda: None):
    session, sleeps = Session(responses), []
    instance = data.MassiveDataClient(data.Config(KEY, feed, datasets), session=session,
                                      sleep=sleeps.append, clock=lambda: NOW, checkpoint=checkpoint)
    return instance, session, sleeps


def option(**kwargs):
    ns = int(NOW.timestamp()) * 1_000_000_000
    return {"details": {"ticker": "O:SPY261023C00580000", "strike_price": 580,
                        "expiration_date": "2026-10-23", "contract_type": "call"},
            "last_quote": {"bid": 2, "ask": 2.1, "last_updated": ns - 1_000_000_000},
            "last_trade": {"price": 2.05, "size": 1, "sip_timestamp": ns - 2_000_000_000},
            "greeks": {"delta": 0.5, "theta": -0.1}, "implied_volatility": 0.2,
            "open_interest": 123, "underlying_asset": {"ticker": "SPY", "price": 580, "last_updated": ns}, **kwargs}


def test_config_requires_key_hides_it_and_validates_feed_and_datasets():
    config = data.Config.from_env({"MASSIVE_API_KEY": KEY})
    assert KEY not in repr(config) and config.fx_feed == "end_of_day"
    assert config.datasets == data.DATASETS
    for env in ({}, {"MASSIVE_API_KEY": "  "}, {"MASSIVE_API_KEY": "key\nheader"},
                {"MASSIVE_API_KEY": KEY, "TAU_MASSIVE_FX_FEED": "sip"},
                {"MASSIVE_API_KEY": KEY, "TAU_MASSIVE_DATASETS": "orders"}):
        with pytest.raises(data.MarketDataError):
            data.Config.from_env(env)


@pytest.mark.parametrize("symbols", [[], "EURUSD", ["EURUSD"] * 4, [None], ["EUR/USD?key=x"],
                                     ["EURUSD/../../orders"], ["USDUSD"], ["EUR"]])
def test_invalid_fx_pairs_never_make_requests(symbols):
    c, session, _ = client()
    with pytest.raises(data.MarketDataError):
        c.fx_bars(symbols, START, END)
    assert session.calls == []


def test_fx_history_normalizes_symbols_paginates_and_never_claims_trade_volume():
    first = page([bar()], ticker="C:EURUSD", next_url=data.DATA_URL + path() + "?cursor=second")
    second = page([bar(START + timedelta(hours=1))], ticker="C:EURUSD")
    third = page([bar()], ticker="C:USDJPY")
    c, session, _ = client(first, second, third)
    with c:
        result = c.fx_bars(["eur/usd", "C:USDJPY", "EURUSD"], START, END)
    assert list(result["bars"]) == ["C:EURUSD", "C:USDJPY"]
    assert len(result["bars"]["C:EURUSD"]) == 2
    assert result["bars"]["C:EURUSD"][0]["volume"] is None
    assert result["bars"]["C:EURUSD"][0]["vendor_quote_activity"] == 123
    assert result["aggregate_basis"] == "bid_ask_quotes" and result["complete"] is True
    assert session.calls[0][0] == data.DATA_URL + path()
    assert session.calls[1][1]["params"]["cursor"] == "second"
    for url, kwargs in session.calls:
        assert KEY not in url and kwargs["headers"] == {"Authorization": "Bearer " + KEY}
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] == (3.05, 8)
    assert all(r.closed for r in (first, second, third)) and session.closed
    assert KEY not in json.dumps(result)


def test_fx_bars_deduplicate_and_exclude_intervals_crossing_cutoff():
    cutoff = START + timedelta(hours=1, minutes=30)
    c, _, _ = client(page([bar(START - timedelta(hours=1)), bar(), bar(), bar(START + timedelta(hours=1))]))
    result = c.fx_bars(["EURUSD"], START, cutoff)
    assert len(result["bars"]["C:EURUSD"]) == 1 and result["excluded_bars"] == 2
    assert result["bars"]["C:EURUSD"][0]["interval_end"] == data.iso(START + timedelta(hours=1))


def test_end_of_day_recency_is_explicit_and_realtime_does_not_silently_fallback():
    c, session, _ = client()
    for call in (lambda: c.fx_quotes(["EURUSD"]), lambda: c.fx_bars(["EURUSD"], START, NOW)):
        with pytest.raises(data.MarketDataError) as exc:
            call()
        assert exc.value.code == "recency"
    assert session.calls == []
    c, session, _ = client(Response({"message": KEY}, 403), feed="realtime")
    with pytest.raises(data.MarketDataError) as exc:
        c.fx_quotes(["EURUSD"])
    assert exc.value.code == "entitlement" and len(session.calls) == 1 and KEY not in str(exc.value)


def test_current_fx_quote_uses_documented_millisecond_timestamp_and_pair():
    raw = Response({"status": "success", "symbol": "EUR/USD",
                    "last": {"bid": 1.1, "ask": 1.2, "timestamp": int(NOW.timestamp() * 1000)}})
    c, session, _ = client(raw, feed="realtime")
    result = c.fx_quotes(["EURUSD"])
    assert result["snapshots"]["C:EURUSD"]["latest_quote"]["timestamp"] == data.iso(NOW)
    assert session.calls[0][0].endswith("/v1/last_quote/currencies/EUR/USD")


@pytest.mark.parametrize("url", ["https://evil.invalid/x?cursor=a", "http://api.massive.com/x?cursor=a",
    "https://api.massive.com/v3/snapshot/options/SPY?cursor=a", "https://u@api.massive.com/x?cursor=a",
    data.DATA_URL + path() + "?cursor=a&apiKey=SECRET", data.DATA_URL + path() + "?cursor=a#fragment",
    data.DATA_URL + path() + "?cursor=a&cursor=b", data.DATA_URL + path() + "?limit=50000", []])
def test_unsafe_pagination_does_not_forward_key_or_make_a_second_request(url):
    c, session, _ = client(page([bar()], next_url=url))
    with pytest.raises(data.MarketDataError) as exc:
        c.fx_bars(["EURUSD"], START, END)
    assert exc.value.code == "invalid_data" and len(session.calls) == 1
    assert "SECRET" not in str(exc.value)


def test_pagination_cycles_page_bounds_and_row_bounds_fail_without_partial_success(monkeypatch):
    link = data.DATA_URL + path() + "?cursor=a"
    c, session, _ = client(page([bar()], next_url=link), page([bar()], next_url=link))
    with pytest.raises(data.MarketDataError, match="repeated"):
        c.fx_bars(["EURUSD"], START, END)
    assert len(session.calls) == 2
    monkeypatch.setattr(data, "MAX_PAGES", 1)
    c, _, _ = client(page([bar()], next_url=link))
    with pytest.raises(data.MarketDataError, match="page budget"):
        c.fx_bars(["EURUSD"], START, END)
    monkeypatch.setattr(data, "MAX_ROWS", 1)
    c, _, _ = client(page([bar(), bar()]))
    with pytest.raises(data.MarketDataError, match="row budget"):
        c.fx_bars(["EURUSD"], START, END)


@pytest.mark.parametrize("row", [bar(c=float("nan")), bar(l=2), {**bar(), "t": True}, bar(v=-1), {"t": 123}])
def test_invalid_bars_are_not_sent_to_an_agent(row):
    c, _, _ = client(page([row]))
    with pytest.raises(data.MarketDataError):
        c.fx_bars(["EURUSD"], START, END)


@pytest.mark.parametrize("status,code", [(401, "authentication"), (403, "entitlement"), (302, "provider_request"),
                                      (429, "rate_limit"), (503, "provider_unavailable")])
def test_http_failures_hide_provider_bodies_and_have_bounded_retries(status, code):
    c, session, sleeps = client(*[Response({"message": KEY}, status, {"Retry-After": "900"}) for _ in range(3)])
    with pytest.raises(data.MarketDataError) as exc:
        c.macro("treasury_yields", START, END)
    assert exc.value.code == code and KEY not in str(exc.value)
    assert len(session.calls) == (3 if status in {429, 503} else 1)
    assert all(0 <= delay <= 3 for delay in sleeps)


@pytest.mark.parametrize("payload", [[], ValueError(KEY), {"status": "ERROR", "error": KEY}, {"status": []},
                                     {"status": "OK", "results": {}}])
def test_bad_json_and_error_envelopes_are_safe(payload):
    c, session, _ = client(Response(payload))
    with pytest.raises(data.MarketDataError) as exc:
        c.macro("treasury_yields", START, END)
    assert KEY not in str(exc.value) and len(session.calls) == 1


def test_network_errors_do_not_echo_the_authorization_header():
    c, session, _ = client(*[requests.ConnectionError(KEY)] * 3)
    with pytest.raises(data.MarketDataError) as exc:
        c.macro("treasury_yields", START, END)
    assert KEY not in str(exc.value) and len(session.calls) == 3


def test_checkpoint_runs_before_each_network_attempt_and_can_cancel_retry():
    count = 0

    def checkpoint():
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("cancelled")

    c, session, _ = client(Response({}, 503), checkpoint=checkpoint)
    with pytest.raises(RuntimeError, match="cancelled"):
        c.macro("treasury_yields", START, END)
    assert count == 2 and len(session.calls) == 1


def test_macro_has_daily_provenance_signed_rates_nulls_and_no_fabricated_vintage():
    rows = [{"date": "2026-10-14", "yield_2_year": 99},
            {"date": "2026-10-15", "yield_2_year": -0.1, "yield_10_year": None, "ignored": KEY},
            {"date": "2026-10-18", "yield_2_year": 99}]
    c, session, _ = client(page(rows))
    result = c.macro("treasury_yields", START, END)
    assert result["observations"] == [{"date": "2026-10-15", "yield_2_year": -0.1}]
    assert result["point_in_time"] is False and result["rate_units"] == "percent"
    assert session.calls[0][0].endswith("/fed/v1/treasury-yields")
    assert session.calls[0][1]["params"]["date.gte"] == "2026-10-15"
    assert KEY not in json.dumps(result)


def test_empty_history_and_macro_return_explicit_empty_lists():
    c, _, _ = client(Response({"status": "OK", "resultsCount": 0}), page([]))
    assert c.fx_bars(["EURUSD"], START, END)["bars"] == {"C:EURUSD": []}
    assert c.macro("funding_conditions", START, END)["observations"] == []


def test_disabled_datasets_cannot_reach_network():
    c, session, _ = client(datasets=("fx",))
    for call in (lambda: c.macro("treasury_yields", START, END), lambda: c.options_chain({"symbols": ["SPY"]})):
        with pytest.raises(data.MarketDataError) as exc:
            call()
        assert exc.value.code == "dataset_disabled"
    assert session.calls == []


def test_options_snapshot_preserves_greeks_iv_prior_day_oi_and_nanosecond_event_times():
    c, session, _ = client(page([option()], next_url="https://unused.invalid/never-followed"))
    query = {"symbols": ["spy"], "expiration_date": "2026-10-23", "contract_type": "call",
             "strike_min": 570, "strike_max": 590}
    result = c.options_chain(query)
    row = result["snapshots"]["O:SPY261023C00580000"]
    assert row["greeks"] == {"delta": 0.5, "theta": -0.1}
    assert row["implied_volatility"] == 0.2 and row["open_interest"] == 123
    assert row["latest_quote"]["timestamp"] == data.iso(NOW - timedelta(seconds=1))
    assert result["complete"] is False and result["sample_limit"] == 50
    assert result["open_interest_asof"] == "previous_trading_day_close"
    assert len(session.calls) == 1 and session.calls[0][1]["params"]["strike_price.gte"] == 570


def test_missing_option_quote_greeks_and_iv_stay_missing():
    c, _, _ = client(page([option(greeks=None, implied_volatility=None, open_interest=None,
                                 last_quote=None, last_trade=None, underlying_asset=None)]))
    row = next(iter(c.options_chain({"symbols": ["SPY"]})["snapshots"].values()))
    assert row["greeks"] == {} and row["implied_volatility"] is None and row["open_interest"] is None
    assert "latest_quote" not in row


def test_underlying_price_without_its_own_timestamp_is_not_claimed_fresh():
    c, _, _ = client(page([option(underlying_asset={"ticker": "SPY", "price": 580})]))
    row = next(iter(c.options_chain({"symbols": ["SPY"]})["snapshots"].values()))
    assert row["underlying_price"] == 580 and row["underlying_price_fresh"] is False
    assert row["underlying_price_age_seconds"] is None and "underlying_timestamp" not in row


@pytest.mark.parametrize("query", [{"symbols": ["SPY", "QQQ"]}, {"symbols": ["../orders"]},
    {"symbols": ["SPY"], "strike_min": True}, {"symbols": ["SPY"], "strike_min": float("nan")},
    {"symbols": ["SPY"], "strike_min": 590, "strike_max": 580},
    {"symbols": ["SPY"], "expiration_date": "2026-09-01"},
    {"symbols": ["SPY"], "contract_type": []}, {"symbols": ["SPY"], "url": "https://evil.invalid"}])
def test_bad_option_filters_fail_before_http(query):
    c, session, _ = client()
    with pytest.raises(data.MarketDataError):
        c.options_chain(query)
    assert session.calls == []


def test_option_result_must_match_requested_filters_and_have_valid_numeric_fields():
    for row in (option(greeks={"delta": float("inf")}), option(underlying_asset={"ticker": "AAPL", "price": 1}),
                option(details={"ticker": "O:SPY261023C00580000", "strike_price": 580,
                                "expiration_date": "2026-10-30", "contract_type": "call"})):
        c, _, _ = client(page([row]))
        with pytest.raises(data.MarketDataError):
            c.options_chain({"symbols": ["SPY"], "expiration_date": "2026-10-23"})


def test_status_checks_configuration_only_and_never_prints_a_key(monkeypatch, capsys):
    monkeypatch.setenv("MASSIVE_API_KEY", KEY)
    monkeypatch.setenv("TAU_MASSIVE_ENABLED", "0")
    monkeypatch.setenv("TAU_MASSIVE_FX_FEED", "end_of_day")
    monkeypatch.setenv("TAU_MASSIVE_DATASETS", "fx,treasury_yields,options")
    monkeypatch.setattr(sys, "argv", ["massive_data", "status"])
    assert data.main() == 0
    output = capsys.readouterr().out
    assert KEY not in output and json.loads(output)["connectivity_tested"] is False
