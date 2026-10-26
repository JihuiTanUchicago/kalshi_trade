"""Offline collector coverage, chunk boundaries, and safe operational output."""
import json
from types import SimpleNamespace

import pytest

from app.adapters.kalshi_perps import kalshi_perps_collector as collector
from app.adapters.kalshi_perps import kalshi_perps_data as data
from app.adapters.data.market_data_common import MarketDataError
from tests.test_kalshi_perps_data import END, NOW, Response, candle_row, client, instrument_row


def test_collection_has_value_metadata_provenance_and_distinct_empty_funding():
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"ticker": "SYNTHBTC", "candlesticks": [candle_row()]}),
                 Response({"funding_rates": []}))
    batch = collector.collect(api, END, END, include_observations=False)
    assert batch["ticker"] == "SYNTHBTC" and batch["environment"] == "production"
    assert batch["candles"][0]["close"] == "7.1500"
    assert batch["coverage"]["funding"]["status"] == "empty"
    assert batch["coverage"]["funding"]["retrieval_complete"] is True
    content = {key: value for key, value in batch.items() if key != "data_fingerprint"}
    assert batch["data_fingerprint"] == data.fingerprint(content)
    assert "metadata_fingerprint" in batch["instrument"]


def test_funding_failure_preserves_candles_with_explicit_unknown_cost_coverage():
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"ticker": "SYNTHBTC", "candlesticks": [candle_row()]}),
                 Response(status=403, body=b"private response must not be retained"))
    batch = collector.collect(api, END, END, include_observations=False)
    assert len(batch["candles"]) == 1 and batch["funding"] == []
    coverage = batch["coverage"]["funding"]
    assert coverage["status"] == "failed" and coverage["retrieval_complete"] is False
    assert coverage["error_code"] == "public_access_unavailable"
    assert "private response" not in data.canonical_json(batch)


def test_optional_observation_failure_is_visible_not_invented():
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"ticker": "SYNTHBTC", "candlesticks": [candle_row()]}),
                 Response({"funding_rates": []}), Response(status=403))
    batch = collector.collect(api, END, END)
    assert batch["observations"] == []
    assert batch["coverage"]["observations"]["status"] == "failed"


def test_summary_contains_counts_and_hashes_not_prices_or_native_bodies():
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"ticker": "SYNTHBTC", "candlesticks": [candle_row()]}),
                 Response({"funding_rates": []}))
    batch = collector.collect(api, END, END, include_observations=False)
    output = collector.summary(batch, "kalshi-perps-v1:production:1")
    assert output["candle_count"] == 1
    assert not ({"candles", "funding", "instrument", "price", "close", "bid", "ask"} & set(output))
    assert output["source_version"] == "kalshi-perps-v1:production:1"


def test_disabled_collector_does_not_request_data():
    api = data.KalshiPerpsDataClient(data.Config(), session=SimpleNamespace(trust_env=False), clock=lambda: NOW)
    with pytest.raises(MarketDataError) as error:
        collector.collect(api, END, END)
    assert error.value.code == "disabled"


def test_range_chunking_is_bounded_contiguous_and_observes_only_once(monkeypatch):
    calls = []
    start = END - 15 * 86400
    api = SimpleNamespace(clock=lambda: NOW, instrument=lambda ticker: {"ticker": "SYNTHBTC"})

    def collect_stub(client, left, right, **kwargs):
        calls.append((left, right, kwargs))
        return {"left": left, "right": right}

    monkeypatch.setattr(collector, "collect", collect_stub)
    batches = list(collector.collect_range(api, start, END))
    assert len(batches) == 3
    assert calls[0][0] == start and calls[-1][1] == END
    assert all(right - left < data.MAX_BATCH_SECONDS for left, right, _ in calls)
    assert all(right + 1 == following[0] for (_, right, _), following in zip(calls, calls[1:]))
    assert [kwargs["include_observations"] for _, _, kwargs in calls] == [False, False, True]


def test_overlong_or_reversed_request_fails_before_discovery():
    api = SimpleNamespace(clock=lambda: NOW, instrument=lambda _: pytest.fail("must not discover"))
    with pytest.raises(MarketDataError):
        list(collector.collect_range(api, END, END - 1))
    with pytest.raises(MarketDataError):
        list(collector.collect_range(api, END - 91 * 86400, END))


def test_cli_default_off_and_date_validation_do_not_touch_db_or_network(monkeypatch, capsys):
    monkeypatch.delenv("TAU_KALSHI_PERPS_ENABLED", raising=False)
    assert collector.main(["--start", "2026-10-01", "--end", "2026-10-02", "--persist"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error_code"] == "disabled"
    assert collector._date("2026-10-01") == collector._date("2026-10-01T00:00:00Z")
    with pytest.raises(Exception):
        collector._date("2026-10-01T00:00:00")
