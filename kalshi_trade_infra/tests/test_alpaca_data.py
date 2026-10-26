"""Provider-contract tests use synthetic responses; they never call Alpaca."""
from datetime import datetime, timezone
import json

import pytest
import requests

from app.adapters.data import alpaca_data as data

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)
CONFIG = data.Config("test-key-private", "test-secret-private", "iex")


def bar(t="2026-10-15T14:00:00Z", close=101):
    return {"t": t, "o": 100, "h": 103, "l": 99, "c": close, "v": 200}


class Response:
    def __init__(self, payload=None, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}
        self.closed = False

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses, self.calls, self.closed = list(responses), [], False

    def get(self, url, **kwargs):
        self.calls.append((url, {**kwargs, "params": dict(kwargs["params"])}))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


def client(*responses, feed="iex"):
    session = Session(responses)
    sleeps = []
    instance = data.AlpacaDataClient(data.Config(CONFIG.api_key, CONFIG.secret_key, feed),
                                     session=session, sleep=sleeps.append, clock=lambda: NOW)
    return instance, session, sleeps


def test_configuration_is_explicit_and_secret_safe():
    assert CONFIG.api_key not in repr(CONFIG) and CONFIG.secret_key not in repr(CONFIG)
    for env in ({}, {"APCA_API_KEY_ID": "key"}):
        with pytest.raises(data.MarketDataError, match="Set APCA"):
            data.Config.from_env(env)
    env = {"APCA_API_KEY_ID": CONFIG.api_key, "APCA_API_SECRET_KEY": CONFIG.secret_key}
    assert data.Config.from_env(env).feed == "iex"
    assert data.Config.from_env({**env, "TAU_ALPACA_FEED": "sip"}).feed == "sip"
    for endpoint in ("http://data.alpaca.markets", "https://evil.invalid", "https://paper-api.alpaca.markets"):
        with pytest.raises(data.MarketDataError, match="must use"):
            data.Config.from_env({**env, "ALPACA_DATA_ENDPOINT": endpoint})


@pytest.mark.parametrize("symbols", [[], ["SPY"] * 9, "SPY", ["SPY,QQQ"], ["../orders"], [None], ["AAPL?x=y"]])
def test_invalid_symbols_fail_without_a_request(symbols):
    c, session, _ = client()
    with pytest.raises(data.MarketDataError):
        c.snapshots(symbols)
    assert session.calls == []


def test_snapshot_contract_headers_provenance_and_missing_symbols():
    response = Response({"SPY": {"latestTrade": {"t": "2026-10-16T14:59:59.123456789Z", "p": 101, "s": 2},
                                 "latestQuote": {"t": "2026-10-16T14:59:59Z", "bp": 100, "ap": 102, "bs": 1, "as": 2},
                                 "minuteBar": bar("2026-10-16T14:59:00Z")}})
    c, session, _ = client(response)
    with c:
        result = c.snapshots(["spy", "QQQ", "SPY"])
    assert result["feed"] == "iex" and result["coverage"] == "IEX exchange only"
    assert result["snapshots"]["SPY"]["latest_trade"]["price"] == 101
    assert result["snapshots"]["QQQ"] == {"status": "missing"}
    url, kwargs = session.calls[0]
    assert url == data.DATA_URL + "/v2/stocks/snapshots"
    assert kwargs["headers"] == {"APCA-API-KEY-ID": CONFIG.api_key, "APCA-API-SECRET-KEY": CONFIG.secret_key}
    assert kwargs["params"] == {"symbols": "SPY,QQQ", "feed": "iex"}
    assert kwargs["allow_redirects"] is False and kwargs["timeout"] == (3.05, 8)
    assert response.closed and session.closed
    assert CONFIG.api_key not in json.dumps(result) and CONFIG.secret_key not in json.dumps(result)


def test_history_follows_pages_even_when_first_page_only_has_one_symbol():
    c, session, _ = client(Response({"bars": {"SPY": [bar()]}, "next_page_token": "page2"}),
                            Response({"bars": {"QQQ": [bar()]}, "next_page_token": None}))
    result = c.bars(["SPY", "QQQ"], data.timestamp("2026-10-15T00:00:00Z"), data.timestamp("2026-10-16T00:00:00Z"))
    assert len(result["bars"]["SPY"]) == len(result["bars"]["QQQ"]) == 1
    assert session.calls[1][1]["params"]["page_token"] == "page2"
    params = session.calls[0][1]["params"]
    assert params["feed"] == "iex" and params["adjustment"] == "raw" and params["sort"] == "asc"
    assert params["end"] == "2026-10-15T23:59:59.999999Z"
    assert result["symbol_mapping_asof"] == "2026-10-15"
    assert result["complete"] is True


def test_history_excludes_bars_crossing_cutoff_and_deduplicates():
    c, _, _ = client(Response({"bars": {"SPY": [bar("2026-10-15T13:00:00Z"), bar("2026-10-15T14:00:00Z"),
                                                    bar("2026-10-15T14:00:00Z"), bar("2026-10-15T15:00:00Z")]}}))
    result = c.bars(["SPY"], data.timestamp("2026-10-15T14:00:00Z"), data.timestamp("2026-10-15T15:30:00Z"))
    assert len(result["bars"]["SPY"]) == 1
    assert result["bars"]["SPY"][0]["interval_end"] == "2026-10-15T15:00:00Z"
    assert result["excluded_bars"] == 2


@pytest.mark.parametrize("start,end", [("2026-03-08T05:00:00Z", "2026-03-09T04:00:00Z"),
                                       ("2025-11-02T04:00:00Z", "2025-11-03T05:00:00Z")])
def test_daily_bar_completion_respects_new_york_dst(start, end):
    c, _, _ = client(Response({"bars": {"SPY": [bar(start)]}}))
    result = c.bars(["SPY"], data.timestamp(start), data.timestamp(end), timeframe="1Day")
    assert result["bars"]["SPY"][0]["interval_end"] == end


@pytest.mark.parametrize("status,code", [(401, "authentication"), (403, "entitlement"), (302, "provider_request"), (422, "provider_request")])
def test_auth_entitlement_and_redirect_failures_are_not_retried_or_downgraded(status, code):
    response = Response({"message": CONFIG.secret_key}, status)
    c, session, sleeps = client(response, feed="sip")
    with pytest.raises(data.MarketDataError) as caught:
        c.snapshots(["SPY"])
    assert caught.value.code == code and CONFIG.secret_key not in str(caught.value)
    assert len(session.calls) == 1 and sleeps == [] and response.closed
    assert session.calls[0][1]["params"]["feed"] == "sip"


def test_rate_limit_backoff_is_bounded_and_preserves_feed():
    c, session, sleeps = client(Response({}, 429, {"Retry-After": "900"}), Response({}, 503), Response({"SPY": None}))
    assert c.snapshots(["SPY"])["snapshots"]["SPY"]["status"] == "missing"
    assert sleeps == [3, 2] and len(session.calls) == 3


def test_network_failures_do_not_expose_request_credentials():
    c, session, _ = client(*[requests.ConnectionError(CONFIG.secret_key)] * 3)
    with pytest.raises(data.MarketDataError) as caught:
        c.snapshots(["SPY"])
    assert caught.value.code == "provider_unavailable" and CONFIG.secret_key not in str(caught.value)
    assert len(session.calls) == 3


@pytest.mark.parametrize("payload", [ValueError("sensitive body"), requests.exceptions.JSONDecodeError("bad", "secret", 0), []])
def test_bad_json_is_a_safe_nonretryable_error(payload):
    c, session, _ = client(Response(payload))
    with pytest.raises(data.MarketDataError) as caught:
        c.snapshots(["SPY"])
    assert caught.value.code == "invalid_data" and len(session.calls) == 1


@pytest.mark.parametrize("bad", [{"c": float("nan")}, {"v": -1}, {"l": 105}, {"t": "2026-10-15T14:00:00"}])
def test_invalid_bars_are_not_passed_to_the_agent(bad):
    c, _, _ = client(Response({"bars": {"SPY": [{**bar(), **bad}]}}))
    with pytest.raises(data.MarketDataError):
        c.bars(["SPY"], data.timestamp("2026-10-15T00:00:00Z"), data.timestamp("2026-10-16T00:00:00Z"))


def test_pagination_cycle_is_rejected_instead_of_returning_partial_data():
    c, session, _ = client(Response({"bars": {"SPY": []}, "next_page_token": "loop"}),
                            Response({"bars": {"SPY": []}, "next_page_token": "loop"}))
    with pytest.raises(data.MarketDataError, match="pagination"):
        c.bars(["SPY"], data.timestamp("2026-10-15T00:00:00Z"), data.timestamp("2026-10-16T00:00:00Z"))
    assert len(session.calls) == 2


def test_page_and_record_caps_fail_explicitly(monkeypatch):
    c, _, _ = client(Response({"bars": {"SPY": []}, "next_page_token": "more"}))
    monkeypatch.setattr(data, "MAX_PAGES", 1)
    with pytest.raises(data.MarketDataError, match="page budget"):
        c.bars(["SPY"], data.timestamp("2026-10-15T00:00:00Z"), data.timestamp("2026-10-16T00:00:00Z"))
    monkeypatch.setattr(data, "MAX_BARS", 1)
    c, _, _ = client(Response({"bars": {"SPY": [bar(), bar()]}}))
    with pytest.raises(data.MarketDataError, match="bar budget"):
        c.bars(["SPY"], data.timestamp("2026-10-15T00:00:00Z"), data.timestamp("2026-10-16T00:00:00Z"))


def test_order_endpoint_is_unreachable():
    c, session, _ = client()
    with pytest.raises(data.MarketDataError, match="read-only"):
        c._get("/v2/orders", {})
    assert session.calls == []
