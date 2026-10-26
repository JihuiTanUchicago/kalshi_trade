"""Append-only/frozen source tests with an isolated in-memory SQL stand-in."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import kalshi_perps_data as data
from app import kalshi_perps_repository as repo
from app.adapters.data.market_data_common import MarketDataError
from tests.test_kalshi_perps_data import END, NOW, instrument_row

MARKET = SimpleNamespace(key="btc_perp", kind="perpetual", underlying="BTC-USD", series="BTC_PERP")


def batch(start=END - 60, end=END, *, close=7.15, environment="production", retrieved=None,
          funding_success=True, funding=None, candles=True):
    retrieved = retrieved or data.iso_time(NOW)
    instrument = data.normalize_instrument(instrument_row(), environment, retrieved)
    rows = [{"ts": ts, "native_end_ts": ts - 1, "open": 7.1, "high": 7.3, "low": 7.0,
             "close": close, "bid": 7.14, "ask": 7.16, "volume": 1,
             "available_at": ts, "retrieved_at": retrieved} for ts in range(start, end + 1, 60)] if candles else []
    funding = funding or []
    result = {"environment": environment, "source_schema": data.SOURCE_SCHEMA, "ticker": "SYNTHBTC",
              "instrument": instrument, "request_start_ts": start, "request_end_ts": end,
              "retrieved_at": retrieved, "candles": rows, "funding": funding, "observations": [],
              "coverage": {"candles": data.candle_coverage(rows, start, end),
                           "funding": data.funding_coverage(funding, start, end, retrieval_complete=funding_success,
                                                            error_code=None if funding_success else "provider_unavailable"),
                           "observations": {"status": "not_requested", "row_count": 0}}}
    result["data_fingerprint"] = data.fingerprint(result)
    return result


class Cursor:
    def __init__(self):
        self.batches = []
        self.bindings = {}
        self.calls = []
        self.rows = []
        self.lock_acquired = 1

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        self.rows = []
        if sql.startswith("INSERT IGNORE INTO kalshi_perps_batches"):
            env, ticker, start, end, retrieved, fp, candles, funding, observations, obs_start, obs_end, status, payload = params
            if not any(row["data_fingerprint"] == fp and row["environment"] == env and row["ticker"] == ticker for row in self.batches):
                self.batches.append(dict(id=len(self.batches) + 1, environment=env, ticker=ticker,
                                         start_ts=start, end_ts=end, retrieved_at=retrieved, data_fingerprint=fp,
                                         candle_count=candles, funding_count=funding, observation_count=observations,
                                         observation_start_ts=obs_start, observation_end_ts=obs_end,
                                         funding_status=status, payload_json=payload))
        elif sql.startswith("SELECT id FROM kalshi_perps_batches"):
            env, ticker, fp = params
            self.rows = [{"id": row["id"]} for row in self.batches
                         if (row["environment"], row["ticker"], row["data_fingerprint"]) == (env, ticker, fp)]
        elif sql.startswith("SELECT * FROM kalshi_perps_batches WHERE environment=%s AND id=%s"):
            env, batch_id = params
            self.rows = [row for row in self.batches if row["environment"] == env and row["id"] == batch_id]
        elif sql.startswith("SELECT * FROM kalshi_perps_batches") and "AND id IN (" in sql:
            env, ticker, *ids = params
            self.rows = sorted([row for row in self.batches if row["environment"] == env
                                and row["ticker"] == ticker and row["id"] in ids], key=lambda row: row["id"])
        elif sql.startswith("SELECT * FROM kalshi_perps_batches") and "AND id<=%s" in sql:
            env, ticker, max_id, start, end, obs_end, limit = params
            self.rows = [row for row in self.batches if row["environment"] == env and row["ticker"] == ticker
                         and row["id"] <= max_id and ((row["end_ts"] >= start and row["start_ts"] <= end)
                         or (row["observation_count"] > 0 and row["observation_start_ts"] <= obs_end))][:limit]
        elif sql.startswith("SELECT * FROM kalshi_perps_batches"):
            env = params[0]
            self.rows = [row for row in self.batches if row["environment"] == env
                         and (len(params) == 1 or row["ticker"] == params[1])][-1:]
        elif sql.startswith("SELECT MIN(start_ts)"):
            env, ticker, max_id = params
            rows = [row for row in self.batches if row["environment"] == env and row["ticker"] == ticker
                    and row["id"] <= max_id and row["candle_count"] > 0]
            self.rows = [{"min_ts": min(row["start_ts"] for row in rows), "max_ts": max(row["end_ts"] for row in rows)}] if rows else []
        elif sql.startswith("INSERT IGNORE INTO kalshi_perps_partition_sources"):
            partition_id, version, fp, manifest = params
            self.bindings.setdefault(partition_id, {"source_version": version, "data_fingerprint": fp,
                                                     "source_manifest_json": manifest})
        elif sql.startswith("SELECT source_version,data_fingerprint"):
            self.rows = [self.bindings[params[0]]] if params[0] in self.bindings else []
        elif sql.startswith("SELECT GET_LOCK"):
            self.rows = [{"acquired": self.lock_acquired}]
        elif sql.startswith("SELECT RELEASE_LOCK"):
            self.rows = [{"released": 1}]
        else:
            raise AssertionError("Unexpected SQL: " + sql)

    def fetchone(self):
        return deepcopy(self.rows[0]) if self.rows else None

    def fetchall(self):
        return deepcopy(self.rows)


@pytest.fixture
def cur(monkeypatch):
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENABLED", "true")
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENVIRONMENT", "production")
    monkeypatch.delenv("TAU_KALSHI_PERPS_TICKER", raising=False)
    return Cursor()


def test_batch_is_immutable_idempotent_and_source_uses_native_ticker(cur):
    original = batch()
    version = repo.store_batch(cur, original)
    assert repo.store_batch(cur, original) == version
    assert len(cur.batches) == 1
    loaded = repo.load_history(cur, MARKET, END - 60, END)
    assert loaded["ticker"] == "SYNTHBTC" and loaded["source_version"] == version
    assert [row["ts"] for row in loaded["candles"]] == [END - 60, END]
    assert loaded["coverage"]["funding"]["retrieval_complete"] is True
    assert all("BTC_PERP" not in str(params) for _, params in cur.calls)


def test_frozen_source_keeps_values_and_fingerprint_after_revision(cur):
    first = repo.store_batch(cur, batch())
    frozen = repo.load_history(cur, MARKET, END - 60, END, source_version=first)
    second = repo.store_batch(cur, batch(close=7.2))
    latest = repo.load_history(cur, MARKET, END - 60, END)
    repeated = repo.load_history(cur, MARKET, END - 60, END, source_version=first)
    assert first != second and latest["data_fingerprint"] != frozen["data_fingerprint"]
    assert repeated == frozen
    assert latest["candles"][0]["close"] == 7.2


def test_value_only_and_metadata_only_revisions_change_fingerprints(cur):
    original = batch()
    modified = batch(close=7.2)
    assert original["retrieved_at"] == modified["retrieved_at"]
    assert original["data_fingerprint"] != modified["data_fingerprint"]
    revised = batch()
    revised["instrument"] = data.normalize_instrument(instrument_row(funding_cap=0.01), "production", data.iso_time(NOW))
    revised.pop("data_fingerprint")
    revised["data_fingerprint"] = data.fingerprint(revised)
    assert original["data_fingerprint"] != revised["data_fingerprint"]


def test_source_binding_never_silently_refreezes(cur):
    first = repo.store_batch(cur, batch())
    history = repo.load_history(cur, MARKET, END - 60, END)
    manifest = history["coverage"]["source_batches"]
    repo.bind_partition_source(cur, 42, first, history["data_fingerprint"], manifest)
    repo.bind_partition_source(cur, 42, first, history["data_fingerprint"], manifest)
    with pytest.raises(MarketDataError) as error:
        repo.bind_partition_source(cur, 42, first, "a" * 64, manifest)
    assert error.value.code == "source_conflict"
    assert repo.partition_source(cur, 42)["data_fingerprint"] == history["data_fingerprint"]


def test_frozen_manifest_excludes_a_lower_allocated_id_that_commits_later(cur):
    # MySQL allocates AUTO_INCREMENT IDs before commit. First writer is still
    # invisible when writer 2 commits and the research source is frozen.
    repo.store_batch(cur, batch(start=END - 120, end=END - 60))
    first_uncommitted = cur.batches.pop()
    anchor = deepcopy(first_uncommitted)
    anchor["id"] = 2
    cur.batches.append(anchor)
    version = "kalshi-perps-v1:production:2"
    history = repo.load_history(cur, MARKET, END - 120, END, source_version=version)
    repo.bind_partition_source(cur, 42, version, history["data_fingerprint"], history["coverage"]["source_batches"])
    bound = repo.partition_source(cur, 42)
    cur.batches.insert(0, first_uncommitted)
    repeated = repo.load_history(cur, MARKET, END - 120, END, source_version=version,
                                 source_manifest=bound["source_manifest"])
    assert repeated == history
    assert [item["id"] for item in repeated["coverage"]["source_batches"]] == [2]
    assert repo.load_history(cur, MARKET, END - 120, END)["data_fingerprint"] != history["data_fingerprint"]


@pytest.mark.parametrize("change", ["missing", "fingerprint"])
def test_frozen_manifest_refuses_missing_or_changed_committed_rows(cur, change):
    repo.store_batch(cur, batch())
    repo.store_batch(cur, batch(close=7.2))
    history = repo.load_history(cur, MARKET, END - 60, END)
    if change == "missing":
        cur.batches.pop(0)
    else:
        cur.batches[0]["data_fingerprint"] = "a" * 64
    with pytest.raises(MarketDataError) as error:
        repo.load_history(cur, MARKET, END - 60, END, source_version=history["source_version"],
                          source_manifest=history["coverage"]["source_batches"])
    assert error.value.code == "source_conflict"


@pytest.mark.parametrize("manifest", [
    [], [{"id": True, "data_fingerprint": "a" * 64}],
    [{"id": 1, "data_fingerprint": "a" * 64}] * 2,
    [{"id": 1, "data_fingerprint": "a" * 64}],
    [{"id": 2, "data_fingerprint": "incomplete"}],
    [{"id": 3, "data_fingerprint": "a" * 64}],
    [{"id": 2, "data_fingerprint": "a" * 64, "other": 1}],
])
def test_invalid_frozen_manifest_fails_before_storage_access(cur, manifest):
    with pytest.raises(MarketDataError):
        repo.load_history(cur, MARKET, END - 60, END, source_version="kalshi-perps-v1:production:2",
                          source_manifest=manifest)
    assert not cur.calls


def test_production_demo_storage_and_frozen_versions_cannot_mix(cur, monkeypatch):
    production = repo.store_batch(cur, batch())
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENVIRONMENT", "demo")
    assert repo.ready(cur, MARKET) is False
    with pytest.raises(MarketDataError):
        repo.store_batch(cur, batch())
    demo = repo.store_batch(cur, batch(environment="demo"))
    loaded = repo.load_history(cur, MARKET, END - 60, END)
    assert loaded["environment"] == "demo" and loaded["source_version"] == demo
    with pytest.raises(MarketDataError):
        repo.load_history(cur, MARKET, END - 60, END, source_version=production)


def test_successful_empty_funding_differs_from_failed_coverage(cur):
    repo.store_batch(cur, batch(funding_success=False))
    unknown = repo.load_history(cur, MARKET, END - 60, END)
    assert unknown["funding"] == [] and unknown["coverage"]["funding"]["retrieval_complete"] is False
    assert unknown["coverage"]["funding"]["status"] == "failed"
    assert unknown["coverage"]["funding"]["retrieval_failures"][0]["error_code"] == "provider_unavailable"
    repo.store_batch(cur, batch(funding_success=True))
    known_empty = repo.load_history(cur, MARKET, END - 60, END)
    assert known_empty["funding"] == [] and known_empty["coverage"]["funding"]["retrieval_complete"] is True


def test_later_successful_empty_response_replaces_prior_values(cur):
    repo.store_batch(cur, batch())
    repo.store_batch(cur, batch(candles=False))
    history = repo.load_history(cur, MARKET, END - 60, END)
    assert history["candles"] == [] and history["coverage"]["candles"]["complete"] is False
    assert repo.ready(cur, MARKET) is False and repo.history_bounds(cur, MARKET) is None


def test_corrupt_stored_payload_fails_integrity_check(cur):
    repo.store_batch(cur, batch())
    cur.batches[0]["payload_json"] = cur.batches[0]["payload_json"].replace('"close":7.15', '"close":9.15')
    with pytest.raises(MarketDataError) as error:
        repo.load_history(cur, MARKET, END - 60, END)
    assert error.value.code == "invalid_data"


def test_unit_revision_inside_interval_fails_closed(cur):
    repo.store_batch(cur, batch())
    revised = batch()
    revised["instrument"] = data.normalize_instrument(instrument_row(contract_size="2.000000"), "production", data.iso_time(NOW))
    revised.pop("data_fingerprint")
    revised["data_fingerprint"] = data.fingerprint(revised)
    repo.store_batch(cur, revised)
    with pytest.raises(MarketDataError) as error:
        repo.load_history(cur, MARKET, END - 60, END)
    assert error.value.code == "instrument_revision"


def test_read_batch_bound_fails_without_truncation(cur, monkeypatch):
    repo.store_batch(cur, batch())
    repo.store_batch(cur, batch(close=7.2))
    monkeypatch.setattr(repo, "MAX_READ_BATCHES", 1)
    with pytest.raises(MarketDataError) as error:
        repo.load_history(cur, MARKET, END - 60, END)
    assert error.value.code == "history_too_large"


def test_observations_retrieved_later_do_not_enter_earlier_window(cur):
    original = batch()
    original["observations"] = [{"kind": "funding_estimate", "ts": END - 120,
                                  "available_at": int(NOW.timestamp()), "retrieved_at": data.iso_time(NOW),
                                  "funding_rate": 0.0001}]
    original.pop("data_fingerprint")
    original["data_fingerprint"] = data.fingerprint(original)
    repo.store_batch(cur, original)
    loaded = repo.load_history(cur, MARKET, END - 60, END)
    assert loaded["observations"] == []


def test_ready_bounds_and_points_use_perps_history_only(cur):
    assert repo.ready(cur, MARKET) is False
    repo.store_batch(cur, batch())
    assert repo.ready(cur, MARKET) is True
    bounds = repo.history_bounds(cur, MARKET)
    assert bounds["min_ts"] == END - 60 and bounds["max_ts"] == END and bounds["count"] == 2
    assert repo.candle_points(cur, MARKET, datetime.fromtimestamp(END - 60, timezone.utc)) == [END - 60, END]
    assert all("hist_markets" not in sql and "spot_candles" not in sql for sql, _ in cur.calls)


def test_disabled_repository_does_not_query(cur, monkeypatch):
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENABLED", "false")
    assert repo.ready(cur, MARKET) is False
    with pytest.raises(MarketDataError):
        repo.load_history(cur, MARKET, END - 60, END)
    assert cur.calls == []


def test_pre_window_observation_seeds_asof_feature_even_if_its_collection_range_is_older(cur):
    original = batch(start=END - 180, end=END - 120)
    retrieved = data.iso_time(END - 60)
    original["retrieved_at"] = retrieved
    original["instrument"] = data.normalize_instrument(instrument_row(), "production", retrieved)
    for row in original["candles"]:
        row["retrieved_at"] = retrieved
    original["observations"] = [{"kind": "funding_estimate", "ts": END - 90,
                                  "available_at": END - 60, "retrieved_at": retrieved,
                                  "funding_rate": "0.0001", "next_funding_ts": END + 3600}]
    original.pop("data_fingerprint")
    original["data_fingerprint"] = data.fingerprint(original)
    repo.store_batch(cur, original)
    repo.store_batch(cur, batch())
    history = repo.load_history(cur, MARKET, END - 60, END)
    assert history["observations"] == original["observations"]


def test_native_adapter_collector_repository_simulator_bridge_makes_causal_momentum_trade(cur):
    from decimal import Decimal
    from app import kalshi_perps_backtest as replay
    from app.kalshi_perps_collector import collect
    from tests.test_kalshi_perps_data import Response, candle_row, client

    start = END - 6 * 60
    native = []
    for index in range(7):
        price = str(Decimal("7.123456") + Decimal(index) / 100)
        native.append(candle_row(start + index * 60 - 1,
                                 price={key: price for key in ("open", "high", "low", "close")}))
    api = client(Response({"markets": [instrument_row()]}),
                 Response({"ticker": "SYNTHBTC", "candlesticks": native}),
                 Response({"funding_rates": []}))
    collected = collect(api, start, END, include_observations=False)
    version = repo.store_batch(cur, collected)
    history = repo.load_history(cur, MARKET, start, END, source_version=version)
    market = SimpleNamespace(**vars(MARKET), deployable=False, label="Synthetic BTC research")
    dataset = replay.build_dataset(market, history)
    assert dataset.bars[0].close == Decimal("7.123456")
    assert all(bar.available_at == bar.ts and bar.ts % 60 == 0 for bar in dataset.bars)
    spec = {"market": "btc_perp", "sizing": {"stake": 100, "max_positions": 1},
            "perpetual": replay.normalize_assumptions({"lookback_minutes": 1, "threshold": "0.0001"})}
    trades = replay.simulate(spec, dataset, start, END)
    assert trades and dataset.last_rejection == ""
    assert trades[0].entry_ts >= start + 60
    assert trades[0].underlying_quantity == trades[0].exact_quantity * Decimal("0.0001")


def test_partition_named_lock_is_released_on_failure_and_timeout_is_safe(cur):
    with pytest.raises(RuntimeError):
        with repo.partition_lock(cur, MARKET):
            raise RuntimeError("fixture")
    assert any(sql.startswith("SELECT RELEASE_LOCK") for sql, _ in cur.calls)
    cur.lock_acquired = 0
    count = len(cur.calls)
    with pytest.raises(ValueError, match="busy"):
        with repo.partition_lock(cur, MARKET):
            pytest.fail("must not enter")
    assert len(cur.calls) == count + 1


def test_ddl_is_additive_and_has_no_trading_tables():
    assert isinstance(repo.DDL, tuple) and len(repo.DDL) == 2
    assert all("CREATE TABLE IF NOT EXISTS kalshi_perps_" in sql for sql in repo.DDL)
