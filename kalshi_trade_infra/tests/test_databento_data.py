"""Databento wire-contract fixtures only: no real key, model, network or provider charge."""
from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest
import requests

from app.adapters.data import databento_data as data

NOW = datetime(2026, 10, 17, 15, tzinfo=timezone.utc)
START = data.timestamp("2026-10-15T00:00:00Z")
END = data.timestamp("2026-10-16T00:00:00Z")
KEY = "fake-databento-private-key"
CONFIG = data.Config(KEY, ("EQUS.MINI", "GLBX.MDP3"), Decimal("0.10"))


def availability(start="2026-01-01T00:00:00Z", end="2026-10-17T14:00:00Z"):
    return {"start": start, "end": end, "schema": {
        schema: {"start": start, "end": end} for schema, _, _ in data.TIMEFRAMES.values()}}


def bar(symbol="SPY", ts="2026-10-15T14:00:00Z", *, close=101_000_000_000, rtype=34):
    return {"hd": {"ts_event": ts, "rtype": rtype, "publisher_id": 1, "instrument_id": 123},
            "open": "100000000000", "high": "103000000000", "low": "99000000000", "close": str(close),
            "volume": "200", "symbol": symbol}


class Response:
    def __init__(self, payload=None, *, body=None, status=200, headers=None, stream_error=None):
        self.body = json.dumps(payload).encode() if body is None else body
        self.status_code, self.headers, self.closed = status, headers or {}, False
        self.stream_error = stream_error

    def iter_content(self, chunk_size):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]
        if self.stream_error:
            raise self.stream_error

    def close(self):
        self.closed = True


def records(*rows, **kwargs):
    return Response(body=b"\n".join(json.dumps(row).encode() for row in rows), **kwargs)


class Session:
    def __init__(self, responses):
        self.responses, self.calls, self.closed = list(responses), [], False

    def _call(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, url, **kwargs):
        return self._call("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._call("POST", url, kwargs)

    def close(self):
        self.closed = True


def client(*responses, config=CONFIG, **kwargs):
    session = Session(responses)
    sleeps = []
    return data.DatabentoDataClient(config, session=session, sleep=sleeps.append,
                                    clock=lambda: NOW, **kwargs), session, sleeps


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A synthetic Databento test attempted a network session")
    monkeypatch.setattr(data.requests, "Session", forbidden)


def test_configuration_is_disabled_without_explicit_activation_and_secret_safe():
    cfg = data.Config.from_env({"DATABENTO_API_KEY": KEY})
    assert cfg.datasets == () and cfg.max_cost_usd == 0 and KEY not in repr(cfg)
    cfg = data.Config.from_env({"DATABENTO_API_KEY": KEY, "TAU_DATABENTO_DATASETS": "EQUS.MINI,GLBX.MDP3,EQUS.MINI",
                                "TAU_DATABENTO_MAX_COST_USD": "0.05"})
    assert cfg.datasets == CONFIG.datasets and cfg.max_cost_usd == Decimal("0.05")


@pytest.mark.parametrize("key, datasets, cap", [("", (), "0"), ("key:bad", (), "0"), ("key\nsecret", (), "0"),
    (KEY, ("../orders",), "0"), (KEY, ("EQUS.MINI",), "NaN"), (KEY, (), "Infinity"),
    (KEY, (), "-1"), (KEY, (), True)])
def test_bad_configuration_fails_without_exposing_values(key, datasets, cap):
    with pytest.raises(data.MarketDataError) as err:
        data.Config(key, datasets, cap)
    assert KEY not in str(err.value)


@pytest.mark.parametrize("symbols", [[], "SPY", ["SPY"] * 9, [None], ["ALL_SYMBOLS"], ["all_symbols"],
    ["ES.FUT"], ["ES.c.0"], ["SPY.OPT"], ["SPY,QQQ"], ["SPY?key=x"], [" SPY"], ["../orders"]])
def test_unbounded_or_malformed_symbols_do_not_reach_http(symbols):
    c, session, _ = client()
    with pytest.raises(data.MarketDataError):
        c.bars(symbols, "EQUS.MINI", START, END)
    assert session.calls == []


def test_stock_bars_wire_contract_price_scaling_and_missing_symbols():
    responses = [Response(availability()), Response(0.025), records(bar())]
    c, session, sleeps = client(*responses)
    with c:
        result = c.bars(["SPY", "QQQ", "SPY"], "EQUS.MINI", START, END)
    assert result["bars"]["SPY"][0]["close"] == 101
    assert result["bars"]["SPY"][0]["volume"] == 200
    assert result["bars"]["QQQ"] == [] and result["complete"] is True
    assert result["adjustment"] == "raw" and result["point_in_time"] is False
    assert result["estimated_cost_usd"] == "0.025" and result["reserved_cost_usd"] == "0.025"
    assert [call[0] for call in session.calls] == ["GET", "GET", "POST"]
    assert [call[1] for call in session.calls] == [data.DATA_URL + "/" + p for p in (
        "metadata.get_dataset_range", "metadata.get_cost", "timeseries.get_range")]
    estimate = session.calls[1][2]["params"]
    download = session.calls[2][2]["data"]
    assert all(download[key] == value for key, value in estimate.items())
    assert estimate["limit"] == 10001 and estimate["symbols"] == "SPY,QQQ"
    assert download["encoding"] == "json" and download["pretty_px"] == "false"
    assert download["pretty_ts"] == download["map_symbols"] == "true" and download["compression"] == "none"
    assert all(call[2]["auth"] == (KEY, "") and call[2]["allow_redirects"] is False
               and call[2]["timeout"] == (3.05, 8) and call[2]["stream"] is True for call in session.calls)
    assert KEY not in json.dumps(result) and session.closed and all(r.closed for r in responses) and sleeps == []


def test_futures_support_negative_prices_without_implied_currency_or_roll():
    row = bar("CLJ0")
    row.update(open="-1000000000", high="0", low="-3000000000", close="-2000000000")
    c, _, _ = client(Response(availability()), Response(0), records(row))
    result = c.bars(["CLJ0"], "GLBX.MDP3", START, END)
    assert result["bars"]["CLJ0"][0]["close"] == -2 and "currency" not in result
    assert result["symbology"] == "raw_symbol" and result["dataset"] == "GLBX.MDP3"


def test_estimate_does_not_download_or_reserve_and_zero_default_cap_denies_paid_data():
    c, session, _ = client(Response(availability()), Response(0.01), config=data.Config(KEY, CONFIG.datasets))
    assert c.estimate(["SPY"], "EQUS.MINI", START, END)["download_started"] is False
    assert c.budget.reserved == 0 and len(session.calls) == 2
    session.responses.extend([Response(availability()), Response(0.01)])
    with pytest.raises(data.MarketDataError, match="remaining local budget"):
        c.bars(["SPY"], "EQUS.MINI", START, END)
    assert all(method == "GET" for method, _, _ in session.calls)


def test_zero_cost_data_can_be_read_with_zero_budget():
    c, _, _ = client(Response(availability()), Response(0), records(bar()), config=data.Config(KEY, CONFIG.datasets))
    assert c.bars(["SPY"], "EQUS.MINI", START, END)["reserved_cost_usd"] == "0"


def test_zero_budget_rejects_positive_cost_even_below_decimal_arithmetic_precision():
    with pytest.raises(data.MarketDataError) as err:
        data.CostBudget("0").reserve(Decimal("1e-10000000"))
    assert err.value.code == "cost_limit"


def test_shared_decimal_budget_retains_failed_download_estimates_and_never_retries_paid_calls():
    budget = data.CostBudget("0.05")
    c, first, _ = client(Response(availability()), Response(0.03),
                         records(bar(), stream_error=requests.ConnectionError("secret URL " + KEY)), budget=budget)
    with pytest.raises(data.MarketDataError) as err:
        c.bars(["SPY"], "EQUS.MINI", START, END)
    assert KEY not in str(err.value) and budget.reserved == Decimal("0.03")
    second, session, _ = client(Response(availability()), Response(0.03), budget=budget)
    with pytest.raises(data.MarketDataError) as err:
        second.bars(["SPY"], "EQUS.MINI", START, END)
    assert err.value.code == "cost_limit" and len(first.calls) == 3 and len(session.calls) == 2


@pytest.mark.parametrize("cost", [None, True, -1, "NaN", "Infinity", {}, [0.01], "invalid"])
def test_bad_cost_estimate_fails_closed_without_download(cost):
    c, session, _ = client(Response(availability()), Response(cost))
    with pytest.raises(data.MarketDataError) as err:
        c.bars(["SPY"], "EQUS.MINI", START, END)
    assert err.value.code == "invalid_cost" and len(session.calls) == 2


def test_availability_is_schema_specific_and_clipped_range_is_explicit():
    available = availability()
    available["schema"]["ohlcv-1h"] = {"start": "2026-10-15T12:00:00Z", "end": "2026-10-15T15:30:00Z"}
    c, _, _ = client(Response(available), Response(0), records(bar(), bar(ts="2026-10-15T15:00:00Z")))
    result = c.bars(["SPY"], "EQUS.MINI", START, END)
    assert result["requested_start"] == data.iso(START) and result["requested_end_exclusive"] == data.iso(END)
    assert result["start"] == "2026-10-15T12:00:00Z" and result["end_exclusive"] == "2026-10-15T15:30:00Z"
    assert result["availability_clipped"] and not result["complete"] and result["excluded_bars"] == 1
    assert len(result["bars"]["SPY"]) == 1


def test_no_available_overlap_or_schema_does_not_download():
    for payload in (availability(start="2026-10-17T00:00:00Z"), {"schema": {}}, []):
        c, session, _ = client(Response(payload))
        with pytest.raises(data.MarketDataError):
            c.bars(["SPY"], "EQUS.MINI", START, END)
        assert len(session.calls) == 1


def test_only_completed_bars_in_window_are_returned_and_duplicates_are_not_double_counted():
    c, _, _ = client(Response(availability()), Response(0), records(
        bar(ts="2026-10-15T13:00:00Z"), bar(), bar(), bar(ts="2026-10-15T15:00:00Z")))
    result = c.bars(["SPY"], "EQUS.MINI", data.timestamp("2026-10-15T13:00:00.000001Z"),
                    data.timestamp("2026-10-15T15:30:00Z"))
    assert len(result["bars"]["SPY"]) == 1 and result["excluded_bars"] == 2
    assert result["bars"]["SPY"][0]["interval_end"] == "2026-10-15T15:00:00Z"


def test_daily_bars_follow_utc_even_across_us_dst():
    start = data.timestamp("2026-03-08T00:00:00Z")
    end = data.timestamp("2026-03-09T00:00:00Z")
    c, _, _ = client(Response(availability()), Response(0), records(bar(ts=data.iso(start), rtype=35)))
    result = c.bars(["SPY"], "EQUS.MINI", start, end, timeframe="1Day")
    assert result["bars"]["SPY"][0]["interval_end"] == data.iso(end) and result["daily_boundary"] == "UTC"


@pytest.mark.parametrize("row", [bar("QQQ"), bar(close=104_000_000_000), bar(ts="2026-10-15T14:01:00Z"),
    bar(ts="2026-10-15T14:00:00.000000001Z"),
    bar(rtype=0), {**bar(), "open": str(2**63 - 1)}, {**bar(), "volume": -1}, {**bar(), "volume": True},
    {**bar(), "close": "NaN"}, {**bar(), "close": 101.0}, {}, [], None])
def test_malformed_prices_headers_symbols_or_schema_do_not_reach_results(row):
    c, _, _ = client(Response(availability()), Response(0), records(row))
    with pytest.raises(data.MarketDataError):
        c.bars(["SPY"], "EQUS.MINI", START, END)


def test_conflicting_publishers_are_not_merged_into_one_series():
    other = bar()
    other["hd"]["publisher_id"] = 2
    c, _, _ = client(Response(availability()), Response(0), records(bar(), other))
    with pytest.raises(data.MarketDataError) as err:
        c.bars(["SPY"], "EQUS.MINI", START, END)
    assert err.value.code == "ambiguous_data"


@pytest.mark.parametrize("status,code", [(401, "authentication"), (402, "payment_required"), (403, "entitlement"),
    (206, "partial_data"), (302, "provider_request"), (429, "rate_limit"), (503, "provider_request")])
def test_download_errors_are_sanitized_closed_and_not_retried(status, code):
    response = Response({"message": KEY}, status=status)
    c, session, sleeps = client(Response(availability()), Response(0.01), response)
    with pytest.raises(data.MarketDataError) as err:
        c.bars(["SPY"], "EQUS.MINI", START, END)
    assert err.value.code == code and KEY not in str(err.value)
    assert len(session.calls) == 3 and response.closed and sleeps == []


def test_metadata_retry_is_bounded_and_does_not_retry_the_paid_download():
    c, session, sleeps = client(Response(status=429, headers={"Retry-After": "999"}),
                                Response(status=503), Response(availability()), Response(0), records(bar()))
    c.bars(["SPY"], "EQUS.MINI", START, END)
    assert sleeps == [3, 2] and len(session.calls) == 5
    assert sum(call[0] == "POST" for call in session.calls) == 1


def test_native_minute_bars_accept_zero_nanoseconds_and_finish_at_the_cutoff():
    c, _, _ = client(Response(availability()), Response(0), records(bar(ts="2026-10-15T14:59:00.000000000Z", rtype=33)))
    result = c.bars(["SPY"], "EQUS.MINI", START, data.timestamp("2026-10-15T15:00:00Z"), timeframe="1Min")
    assert result["bars"]["SPY"][0]["interval_end"] == "2026-10-15T15:00:00Z"


def test_record_and_byte_limits_never_label_partial_history_complete(monkeypatch):
    monkeypatch.setattr(data, "MAX_BARS", 1)
    response = records(bar(), bar(ts="2026-10-15T15:00:00Z"))
    c, session, _ = client(Response(availability()), Response(0), response)
    with pytest.raises(data.MarketDataError) as err:
        c.bars(["SPY"], "EQUS.MINI", START, END)
    assert err.value.code == "record_limit" and session.calls[-1][2]["data"]["limit"] == 2
    monkeypatch.setattr(data, "MAX_RESPONSE_BYTES", 1)
    c, _, _ = client(Response(availability()), Response(0), records(bar()))
    with pytest.raises(data.MarketDataError) as err:
        c.bars(["SPY"], "EQUS.MINI", START, END)
    assert err.value.code == "response_limit"


def test_cancel_during_stream_closes_response_and_does_not_retry():
    response = records(bar())
    c, session, _ = client(Response(availability()), Response(0), response)
    class Cancelled(Exception):
        pass
    def checkpoint():
        if len(session.calls) == 3:
            raise Cancelled()
    c.checkpoint = checkpoint
    with pytest.raises(Cancelled):
        c.bars(["SPY"], "EQUS.MINI", START, END)
    assert len(session.calls) == 3 and response.closed


def test_invalid_dataset_dates_timeframe_and_paths_are_rejected_before_http():
    c, session, _ = client()
    for dataset, start, end, timeframe in [("XNAS.ITCH", START, END, "1Hour"), ("EQUS.MINI", END, START, "1Hour"),
        ("EQUS.MINI", START, NOW.replace(year=2027), "1Hour"), ("EQUS.MINI", START, END, "5Min"),
        ("EQUS.MINI", START.replace(month=1), END, "1Hour")]:
        with pytest.raises(data.MarketDataError):
            c.bars(["SPY"], dataset, start, end, timeframe=timeframe)
    with pytest.raises(data.MarketDataError):
        c._http("account.purchase", {})
    assert session.calls == []


def test_status_cli_has_no_network_or_secret_output(monkeypatch, capsys):
    monkeypatch.setenv("DATABENTO_API_KEY", KEY)
    monkeypatch.setenv("TAU_DATABENTO_DATASETS", "EQUS.MINI,GLBX.MDP3")
    monkeypatch.setenv("TAU_DATABENTO_MAX_COST_USD", "0")
    monkeypatch.delenv("TAU_DATABENTO_ENABLED", raising=False)
    monkeypatch.setattr("sys.argv", ["databento_data", "status"])
    assert data.main() == 0
    output = capsys.readouterr().out
    assert KEY not in output and json.loads(output)["network_checked"] is False and not json.loads(output)["enabled"]
