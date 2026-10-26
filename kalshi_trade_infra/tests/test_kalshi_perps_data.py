"""Synthetic native schemas only; these tests never contact Kalshi."""
import json
from datetime import datetime, timezone

import pytest
import requests
from decimal import Decimal

from app import kalshi_perps_data as data
from app.adapters.data.market_data_common import MarketDataError

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
END = int(NOW.timestamp()) - 60


def instrument_row(**updates):
    row = {"ticker": "SYNTHBTC", "title": "Bitcoin", "asset_class": "crypto",
           "status": "active", "contract_size": "1.000000", "underlying_multiplier": "0.0001",
           "tick_size": "0.0001", "fractional_trading_enabled": False,
           "schedule": None, "exchange_index": 1, "market_version": 1,
           "funding_deadband": 0.0001, "funding_cap": 0.02,
           "funding_limit_unit": "percentage", "funding_invalid_premium_handling": "dampen"}
    return {**row, **updates}


def candle_row(ts=END, **updates):
    row = {"end_period_ts": ts,
           "price": {"open": "7.1000", "high": "7.2000", "low": "7.0000", "close": "7.1500"},
           "bid": {"close": "7.1400"}, "ask": {"close": "7.1600"}, "volume": "10.00"}
    return {**row, **updates}


class Response:
    def __init__(self, payload=None, status=200, body=None, headers=None):
        self.body = body if body is not None else json.dumps(payload).encode()
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index:index + chunk_size]

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        pass


def client(*responses, environment="production", ticker=None):
    return data.KalshiPerpsDataClient(data.Config(True, environment, ticker), session=Session(*responses),
                                    clock=lambda: NOW, sleep=lambda _: None)


def test_default_off_does_not_read_private_env_or_make_requests():
    config = data.Config.from_env({"KALSHI_API_KEY": "private-never-used"})
    session = Session()
    with pytest.raises(MarketDataError) as error:
        data.KalshiPerpsDataClient(config, session=session).discover_bitcoin()
    assert error.value.code == "disabled"
    assert session.calls == []


@pytest.mark.parametrize("env", [
    {"TAU_KALSHI_PERPS_ENABLED": "yes"},
    {"TAU_KALSHI_PERPS_ENVIRONMENT": "staging"},
    {"TAU_KALSHI_PERPS_BASE_URL": "https://example.invalid"},
    {"TAU_KALSHI_PERPS_TICKER": "../portfolio/orders"},
])
def test_configuration_is_bounded(env):
    with pytest.raises(MarketDataError):
        data.Config.from_env(env)


def test_native_bitcoin_discovery_no_guessed_tickers():
    response = Response({"markets": [instrument_row(), instrument_row(ticker="SYNTHBCH", title="Bitcoin Cash")]})
    api = client(response)
    instruments = api.discover_bitcoin()
    assert [row["ticker"] for row in instruments] == ["SYNTHBTC"]
    row = instruments[0]
    assert row["contract_multiplier"] == "0.0001000000"
    assert row["price_basis"] == "per_contract"
    assert row["quantity_step"] == "1"
    assert row["funding_rate_unit"] == "decimal"
    assert row["verified_bitcoin"] is True
    url, kwargs = api.session.calls[0]
    assert url == data.BASE_URLS["production"] + "/margin/markets"
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"] == {"Accept": "application/json"}
    assert kwargs["auth"] == () and kwargs["proxies"] == {} and kwargs["cookies"] == {}
    assert api.session.trust_env is False and response.closed


@pytest.mark.parametrize("title", ["0.0001 BTC", ".0001 BTC"])
def test_native_production_and_demo_size_titles_verify_declared_contract_units(title):
    # Public metadata observed Oct 23; no prices or account fields retained.
    row = instrument_row(title=title, asset_class="Crypto", contract_size="0.000100",
                         underlying_multiplier="1.000000")
    api = client(Response({"markets": [row]}))
    verified = api.discover_bitcoin()
    assert len(verified) == 1 and verified[0]["verified_bitcoin"]
    assert Decimal(verified[0]["contract_multiplier"]) == Decimal("0.0001")


@pytest.mark.parametrize("title,asset", [("0.0001 BCH", "Crypto"), ("0.0001 BTC Cash", "Crypto"),
                                        ("0.0001 BTC", "Stocks")])
def test_bitcoin_size_title_does_not_match_other_underlyings(title, asset):
    api = client(Response({"markets": [instrument_row(title=title, asset_class=asset)]}))
    assert api.discover_bitcoin() == []


def test_bitcoin_size_title_must_agree_with_verified_native_quantity_units():
    api = client(Response({"markets": [instrument_row(title="0.001 BTC")]}))
    with pytest.raises(MarketDataError) as error:
        api.discover_bitcoin()
    assert error.value.code == "invalid_data"


def test_discovery_can_refresh_without_false_duplicate_error():
    api = client(Response({"markets": [instrument_row()]}), Response({"markets": [instrument_row()]}))
    assert api.discover_bitcoin() == api.discover_bitcoin()


def test_explicit_ticker_requires_bitcoin_metadata_and_matches_exactly():
    api = client(Response({"market": instrument_row(title="Ether")}), ticker="SYNTHBTC")
    with pytest.raises(MarketDataError) as error:
        api.instrument()
    assert error.value.code == "not_bitcoin"
    with pytest.raises(MarketDataError):
        api._get("/margin/portfolio/orders", {})


def test_session_strips_ambient_auth_headers_cookies_and_proxy(monkeypatch):
    session = requests.Session()
    session.auth = ("private", "secret")
    session.headers["Authorization"] = "private"
    session.cookies["session"] = "private"
    session.proxies["https"] = "http://private.invalid"
    session.params["api_key"] = "private"
    session.verify = False
    api = data.KalshiPerpsDataClient(data.Config(True), session=session)
    assert session.auth is None and session.trust_env is False
    assert not session.headers and not session.cookies and not session.proxies and not session.params
    assert session.verify is True
    monkeypatch.setattr(session, "get", lambda *args, **kwargs: Response({"markets": []}))
    assert api.discover_bitcoin() == []


def test_completed_candles_normalize_inclusive_second_and_skip_null_or_future():
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"ticker": "SYNTHBTC", "candlesticks": [
                     candle_row(END - 1), candle_row(END + 59),
                     candle_row(END - 61, price={"open": None, "high": None, "low": None, "close": None, "previous": "7.0"}),
                 ]}))
    rows, coverage = api.candles("SYNTHBTC", END - 60, END)
    assert [row["ts"] for row in rows] == [END]
    assert rows[0]["native_end_ts"] == END - 1
    assert rows[0]["available_at"] == END
    assert coverage["complete"] is False and coverage["missing_count"] == 1
    assert api.session.calls[-1][1]["params"]["include_latest_before_start"] == "false"
    assert api.session.calls[-1][1]["params"]["start_ts"] == END - 61


def test_minute_boundary_candles_are_available_at_completed_boundary():
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"ticker": "SYNTHBTC", "candlesticks": [candle_row()]}))
    rows, coverage = api.candles("SYNTHBTC", END, END)
    assert rows[0]["ts"] == rows[0]["available_at"] == END
    assert coverage["complete"] is True


def test_malformed_ohlc_fails_and_crossed_quote_is_missing():
    bad = candle_row(price={"open": "7", "high": "6", "low": "7", "close": "7"})
    api = client(Response({"markets": [instrument_row()]}), Response({"ticker": "SYNTHBTC", "candlesticks": [bad]}))
    with pytest.raises(MarketDataError):
        api.candles("SYNTHBTC", END, END)
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"ticker": "SYNTHBTC", "candlesticks": [candle_row(bid={"close": "8"}, ask={"close": "7"})]}))
    rows, _ = api.candles("SYNTHBTC", END, END)
    assert rows[0]["bid"] is None and rows[0]["ask"] is None


def test_final_funding_keeps_payment_time_and_later_known_time():
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"funding_rates": [{"market_ticker": "SYNTHBTC", "funding_time": data.iso_time(END),
                                              "funding_rate": -0.0001, "mark_price": "7.1"}]}))
    rows, coverage = api.funding("SYNTHBTC", END - 60, END)
    assert rows[0]["ts"] == END and rows[0]["available_at"] == int(NOW.timestamp())
    assert rows[0]["kind"] == "settled_funding" and Decimal(rows[0]["rate"]) < 0
    assert coverage["retrieval_complete"] is True


def test_empty_funding_is_not_a_zero_rate_or_failed_retrieval():
    start = int(datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc).timestamp())
    end = start + 2 * 3600
    api = client(Response({"markets": [instrument_row()]}), Response({"funding_rates": []}))
    rows, coverage = api.funding("SYNTHBTC", start, end)
    assert rows == [] and coverage["status"] == "empty"
    assert coverage["retrieval_complete"] is True and coverage["complete"] is False
    assert coverage["missing_timestamps"]


def test_dst_funding_uses_local_clock_not_assumed_eight_hour_utc_grid():
    start = int(datetime(2026, 11, 1, 0, tzinfo=timezone.utc).timestamp())
    schedule = data.funding_times(start, start + 86400)
    assert 9 * 3600 in [right - left for left, right in zip(schedule, schedule[1:])]


def test_observed_mark_index_and_estimate_are_available_at_retrieval():
    now = int(NOW.timestamp())
    market = instrument_row(bid="7.1", ask="7.2", settlement_mark_price={"price": "7.15", "ts_ms": (now - 2) * 1000},
                            reference_price={"price": "7.14", "ts_ms": (now - 4) * 1000})
    api = client(Response({"markets": [instrument_row()]}), Response({"market": market}),
                 Response({"market_ticker": "SYNTHBTC", "computed_time": data.iso_time(now - 1),
                           "funding_rate": 0.0001, "next_funding_time": data.iso_time(now + 3600)}))
    rows, coverage = api.observations("SYNTHBTC")
    assert {row["kind"] for row in rows} == {"quote", "mark", "index", "funding_estimate"}
    assert all(row["available_at"] == now for row in rows)
    assert coverage["status"] == "complete"
    assert next(row for row in rows if row["kind"] == "funding_estimate")["funding_rate"] == "0.0001"


def test_provider_financial_decimal_strings_survive_exactly():
    value = "1234567890123.123456"
    rate = "0.000123456789012345"
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"ticker": "SYNTHBTC", "candlesticks": [
                     candle_row(price={key: value for key in ("open", "high", "low", "close")})]}),
                 Response(body=('{"funding_rates":[{"market_ticker":"SYNTHBTC","funding_time":"' +
                                data.iso_time(END) + '","funding_rate":' + rate +
                                ',"mark_price":"' + value + '"}]}').encode()))
    candles, _ = api.candles("SYNTHBTC", END, END)
    funding, _ = api.funding("SYNTHBTC", END, END)
    assert candles[0]["close"] == value
    assert funding[0]["mark_price"] == value and funding[0]["rate"] == rate


def test_redirect_and_private_errors_are_not_followed_or_logged():
    api = client(Response(status=302, headers={"Location": "https://private.invalid"}, body=b"secret"))
    with pytest.raises(MarketDataError) as error:
        api.discover_bitcoin()
    assert "secret" not in str(error.value) and "private" not in str(error.value)
    assert len(api.session.calls) == 1


def test_retry_and_response_bounds(monkeypatch):
    api = client(Response(status=429), Response(status=503), Response({"markets": []}))
    assert api.discover_bitcoin() == [] and len(api.session.calls) == 3
    monkeypatch.setattr(data, "MAX_RESPONSE_BYTES", 8)
    api = client(Response(body=b"{" + b"x" * 10))
    with pytest.raises(MarketDataError) as error:
        api.discover_bitcoin()
    assert error.value.code == "response_too_large"


def test_unexpected_pagination_does_not_silently_truncate():
    api = client(Response({"markets": [], "cursor": "another-page"}))
    with pytest.raises(MarketDataError):
        api.discover_bitcoin()


def test_subsecond_retrieval_is_never_rounded_to_earlier_availability():
    assert data.available_epoch("2026-10-23T12:00:00.999Z") == int(NOW.timestamp()) + 1
