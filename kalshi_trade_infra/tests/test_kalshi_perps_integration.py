"""Offline integration of native-shaped synthetic data and research-only boundaries.

The source and research repositories execute their real SQL against a bounded
in-memory adapter. Statistical outcomes on these artificial prices are test
fixtures, never evidence about an actual Bitcoin strategy or provider access.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from types import SimpleNamespace

import pytest
import requests

from app import backtest, server
from app.research import agent, gatekeeper, partitions
from app.adapters.kalshi_perps import kalshi_perps_collector as collector
from app.adapters.kalshi_perps import kalshi_perps_data as data
from app.adapters.kalshi_perps import kalshi_perps_repository as sources
from app import research_repository as ledger
from app import spec as specmod
from app.markets import MARKETS
from data_pipeline import common
from tests.test_kalshi_perps_data import NOW, Response, Session, instrument_row
from tests.test_research_repository import LedgerCursor, _insert_cols


START = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
END = START + 10 * 86400


def _forbidden(*_args, **_kwargs):
    raise AssertionError("This offline integration must not use an external service or execution path")


class ResearchCursor(LedgerCursor):
    """Compose existing ledger SQL behavior with append-only source storage."""

    def __init__(self):
        super().__init__()
        self.batches = []
        self.bindings = {}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql, params=()):
        statement = " ".join(sql.split())
        self.calls.append((statement, params))
        self._last = []
        if statement.startswith("INSERT IGNORE INTO kalshi_perps_batches"):
            row = dict(zip(_insert_cols(statement), params))
            identity = (row["environment"], row["ticker"], row["data_fingerprint"])
            if not any((item["environment"], item["ticker"], item["data_fingerprint"]) == identity
                       for item in self.batches):
                self.batches.append(dict(row, id=len(self.batches) + 1))
        elif statement.startswith("SELECT id FROM kalshi_perps_batches"):
            self._last = [{"id": row["id"]} for row in self.batches
                          if (row["environment"], row["ticker"], row["data_fingerprint"]) == params]
        elif statement.startswith("SELECT * FROM kalshi_perps_batches"):
            environment = params[0]
            rows = [row for row in self.batches if row["environment"] == environment]
            if "AND id=%s" in statement:
                rows = [row for row in rows if row["id"] == params[1]]
            elif "AND id IN (" in statement:
                rows = sorted([row for row in rows if row["ticker"] == params[1] and row["id"] in params[2:]],
                              key=lambda row: row["id"])
            elif "AND id<=%s" in statement:
                environment, ticker, maximum, start, end, observation_end, limit = params
                rows = [row for row in rows if row["ticker"] == ticker and row["id"] <= maximum
                        and ((row["end_ts"] >= start and row["start_ts"] <= end)
                             or (row["observation_count"] > 0
                                 and row["observation_start_ts"] <= observation_end))][:limit]
            else:
                if len(params) > 1:
                    rows = [row for row in rows if row["ticker"] == params[1]]
                rows = rows[-1:]
            self._last = deepcopy(rows)
        elif statement.startswith("INSERT IGNORE INTO kalshi_perps_partition_sources"):
            partition_id, version, fingerprint, manifest = params
            self.bindings.setdefault(partition_id, {"source_version": version, "data_fingerprint": fingerprint,
                                                     "source_manifest_json": manifest})
        elif statement.startswith("SELECT source_version,data_fingerprint"):
            self._last = [deepcopy(self.bindings[params[0]])] if params[0] in self.bindings else []
        elif statement.startswith("SELECT MIN(start_ts) AS min_ts"):
            environment, ticker, maximum = params
            rows = [row for row in self.batches if row["environment"] == environment
                    and row["ticker"] == ticker and row["id"] <= maximum and row["candle_count"] > 0]
            self._last = [{"min_ts": min(row["start_ts"] for row in rows),
                           "max_ts": max(row["end_ts"] for row in rows)}] if rows else []
        elif statement.startswith("SELECT GET_LOCK"):
            self._last = [{"acquired": 1}]
        elif statement.startswith("SELECT RELEASE_LOCK"):
            self._last = [{"released": 1}]
        elif statement.startswith("SELECT e.id AS experiment_id"):
            # The real trial-count reader selects each experiment's latest validation.
            user_id, market = params
            for experiment in self.t["app_experiments"]:
                results = [row for row in self.t["app_experiment_results"]
                           if row["experiment_id"] == experiment["id"] and row["phase"] == "validation"]
                if results and experiment["user_id"] == user_id and experiment["market"] == market:
                    result = results[-1]
                    self._last.append({"experiment_id": experiment["id"],
                                       "strategy_id": experiment["strategy_id"], "parent_id": None,
                                       "hypothesis_hash": experiment["hypothesis_hash"], "market": market,
                                       **{key: result[key] for key in (
                                           "classification", "n_trades", "net_pnl", "mean_net_return")}})
        else:
            super().execute(sql, params)


class Connection:
    def __init__(self, cursor):
        self.memory_cursor = cursor

    def cursor(self):
        return self.memory_cursor

    def close(self):
        pass


@lru_cache(maxsize=1)
def _native_batches():
    """Ten days cross the real holding embargoes, in two bounded collection batches."""
    output = []
    for start, end in ((START, START + 5 * 86400 - 1), (START + 5 * 86400, END)):
        candles = []
        for timestamp in range(start, end + 1, 60):
            minute = (timestamp - START) // 60
            triangle = minute % 120
            triangle = triangle if triangle <= 60 else 120 - triangle
            price = Decimal("7.123456789012345678") + Decimal("0.02") * triangle
            candles.append({"end_period_ts": timestamp,
                            "price": {key: str(price) for key in ("open", "high", "low", "close")}})
        funding = [{"market_ticker": "SYNTHBTC", "funding_time": timestamp,
                    "funding_rate": "0.000123456789012345", "mark_price": "7.123456789012345678"}
                   for timestamp in data.funding_times(start, end)]
        session = Session(Response({"market": instrument_row(tick_size="0.000000000000000001")}),
                          Response({"ticker": "SYNTHBTC", "candlesticks": candles}),
                          Response({"funding_rates": funding}))
        client = data.KalshiPerpsDataClient(data.Config(True, "production", "SYNTHBTC"),
                                            session=session, clock=lambda: NOW, sleep=_forbidden)
        output.append(collector.collect(client, start, end, include_observations=False))
        assert len(session.calls) == 3
    return tuple(output)


@pytest.fixture
def memory(monkeypatch):
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENABLED", "true")
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENVIRONMENT", "production")
    monkeypatch.setenv("TAU_KALSHI_PERPS_TICKER", "SYNTHBTC")
    for name in ("TAU_KALSHI_PERPS_BASE_URL", "TAU_KALSHI_PERPS_ENDPOINT", "TAU_KALSHI_PERPS_URL"):
        monkeypatch.delenv(name, raising=False)
    cursor = ResearchCursor()
    monkeypatch.setattr(common, "get_db_conn", lambda: Connection(cursor))
    monkeypatch.setattr(server, "get_db_conn", lambda: Connection(cursor))
    monkeypatch.setattr(requests.sessions.Session, "request", _forbidden)
    monkeypatch.setattr(agent, "claude", _forbidden)
    monkeypatch.setattr(partitions, "now_utc", lambda: NOW.replace(tzinfo=None))
    return cursor


@pytest.fixture
def frozen(memory):
    for batch in _native_batches():
        sources.store_batch(memory, batch)
    partition = partitions.ensure_partition(memory, "btc_perp")
    spec = specmod.validate({"market": "btc_perp", "sizing": {"stake": 100},
                             "perpetual": {"signal": "momentum", "lookback_minutes": 1,
                                           "threshold": 0.000001}})
    return SimpleNamespace(cur=memory, partition=partition, spec=spec)


def _preregister(frozen, run_id=1, min_sample=30):
    thesis = {"title": "Synthetic momentum", "thesis": "Fixture only", "min_sample": min_sample}
    pre = agent._prereg(thesis, frozen.spec, {"user_id": 1, "id": run_id}, frozen.partition,
                        1, {"reason": "Fixture eligibility"}, strategy_id=run_id)
    return gatekeeper.preregister(frozen.cur, pre), {
        "spec": frozen.spec, "market": "btc_perp", "user_id": 1, "min_sample": min_sample,
    }


def test_native_collection_storage_frozen_phases_and_actual_validation_bridge(frozen):
    partition = frozen.partition
    assert len(frozen.cur.batches) == 2
    original = _native_batches()[0]
    assert original["candles"][0]["close"] == "7.123456789012345678"
    history = sources.load_history(frozen.cur, MARKETS["btc_perp"], START, END,
                                   source_version=partition["source_version"])
    assert history["candles"][0]["close"] == original["candles"][0]["close"]
    assert history["funding"][0]["rate"] == "0.000123456789012345"
    assert history["instrument"]["funding_schedule"]["timezone"] == "America/New_York"

    datasets = [loader("btc_perp", partition) for loader in (
        partitions.research_dataset, partitions.validation_dataset, partitions.holdout_dataset)]
    for phase, dataset in zip(("research", "validation", "holdout"), datasets):
        assert dataset.partition_id == partition["id"]
        assert dataset.source_version == partition["source_version"]
        assert all(partition[phase + "_from_ts"] <= timestamp < partition[phase + "_to_ts"]
                   for timestamp, _frame in dataset.frames)
        trades = backtest.simulate(frozen.spec, dataset, dataset.start_ts, dataset.end_ts + 1)
        assert trades, (phase, dataset.last_rejection)
        assert all(trade.qty > 0 and trade.entry_ts <= trade.exit_ts < partition[phase + "_to_ts"]
                   for trade in trades)
        assert any(trade.funding_pnl != 0 for trade in trades)

    experiment_id, finalist = _preregister(frozen)
    verdict = gatekeeper.judge_validation(frozen.cur, experiment_id, finalist, datasets[1])
    recorded = ledger.results_for_experiment(frozen.cur, experiment_id, "validation")
    assert verdict["n_trades"] > 0 and recorded[-1]["n_trades"] == verdict["n_trades"]
    assert verdict["classification"] in {item.value for item in gatekeeper.Classification}
    paper = ledger.experiment_by_id(frozen.cur, experiment_id)
    assert paper["experiment"]["research_partition_id"] == partition["id"]
    assert paper["experiment"]["data_provenance"]["source_version"] == partition["source_version"]


def test_consumed_holdout_and_pinned_sources_survive_new_collection(frozen, monkeypatch):
    experiment_id, finalist = _preregister(frozen, min_sample=100_000)
    # A synthetic prerequisite enables testing the holdout latch, without claiming
    # these artificial prices established statistical support for a real strategy.
    ledger.append_result(frozen.cur, experiment_id, "validation", "statistically_supported", 100)
    monkeypatch.setattr(partitions, "holdout_max_evaluations", lambda _market: 1)
    verdict = gatekeeper.judge_holdout(frozen.cur, experiment_id, finalist)
    assert 0 < verdict["n_trades"] < finalist["min_sample"]
    assert verdict["classification"] == "inconclusive" and verdict["holdout_consumed"] == 1
    used = ledger.get_holdout_ledger(frozen.cur, "btc_perp", frozen.partition["id"])
    assert used["evaluations_used"] == 1 and used["consumed"] == 1
    original = partitions.holdout_dataset("btc_perp", frozen.partition)

    revision = deepcopy(_native_batches()[-1])
    for candle in revision["candles"]:
        for key in ("open", "high", "low", "close"):
            candle[key] = str(Decimal(candle[key]) + 1)
    revision.pop("data_fingerprint")
    revision["data_fingerprint"] = data.fingerprint(revision)
    newer = sources.store_batch(frozen.cur, revision)
    assert newer != frozen.partition["source_version"]
    assert partitions.ensure_partition(frozen.cur, "btc_perp")["id"] == frozen.partition["id"]
    assert len(frozen.cur.t["app_data_partitions"]) == 1
    repeated = partitions.holdout_dataset("btc_perp", frozen.partition)
    assert repeated.data_fingerprint == original.data_fingerprint
    assert repeated.frames == original.frames
    assert ledger.get_holdout_ledger(frozen.cur, "btc_perp", frozen.partition["id"]) == used
    with pytest.raises(gatekeeper.HoldoutConsumed):
        gatekeeper.judge_holdout(frozen.cur, experiment_id, finalist)
    other_id, other = _preregister(frozen, run_id=2, min_sample=100_000)
    ledger.append_result(frozen.cur, other_id, "validation", "statistically_supported", 100)
    with pytest.raises(gatekeeper.HoldoutConsumed):
        gatekeeper.judge_holdout(frozen.cur, other_id, other)
    assert not ledger.results_for_experiment(frozen.cur, other_id, "holdout")


@pytest.mark.parametrize("changed", ["partition", "source"])
def test_validation_refuses_a_different_partition_or_source_before_alpha(frozen, changed):
    experiment_id, finalist = _preregister(frozen)
    dataset = partitions.validation_dataset("btc_perp", frozen.partition)
    if changed == "partition":
        dataset.partition_id += 1
    else:
        dataset.source_version = "kalshi-perps-v1:production:99999"
    with pytest.raises(ValueError, match="frozen"):
        gatekeeper.judge_validation(frozen.cur, experiment_id, finalist, dataset)
    assert not frozen.cur.t["app_experiment_results"] and not frozen.cur.t["app_fdr_state"]


def _strategy(spec=None, market="btc_perp"):
    spec = spec or specmod.validate({"market": "btc_perp"})
    return {"id": 11, "run_id": 1, "parent_id": None, "market": market, "direction": "custom",
            "title": "Synthetic research", "thesis": "Fixture only", "status": "passed",
            "created_at": NOW, "spec": spec, "result": {}, "active_deps": 0, "live_deps": 0}


def _ctx(memory, *, body=None, params=()):
    return server.Ctx(Connection(memory), {"id": 1}, params, {}, body or {}, None)


def test_market_picker_uses_actual_perpetual_storage_and_default_off(memory, monkeypatch):
    monkeypatch.setattr(server.repo, "spot_symbols_with_data", lambda *_args: set())
    monkeypatch.setattr(server.repo, "series_with_candles", lambda *_args: set())
    row = next(row for row in server._researchable_markets(memory) if row["key"] == "btc_perp")
    assert row["has_data"] is False and row["research_only"] is True and row["deployable"] is False
    for batch in _native_batches():
        sources.store_batch(memory, batch)
    ready = next(row for row in server._researchable_markets(memory) if row["key"] == "btc_perp")
    assert ready["has_data"] is True and ready["kind"] == "perpetual"
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENABLED", "false")
    assert all(row["key"] != "btc_perp" for row in server._researchable_markets(memory))


def test_perpetual_strategy_card_and_detail_do_not_require_binary_fields(memory, monkeypatch):
    strategy = _strategy()
    monkeypatch.setattr(server.repo, "get_strategy", lambda *_args: deepcopy(strategy))
    monkeypatch.setattr(server.repo, "list_deployments_for_display", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(server.repo, "positions_for_strategy", lambda *_args: [])
    card = server._strategy_card(strategy)
    assert card["side"] == "both" and card["kind"] == "perpetual" and card["research_only"]
    detail = server.get_strategy(_ctx(memory, params=("11",)))
    assert detail["spec"] == strategy["spec"] and detail["holdings"] == []
    assert any("Research only" in rule for rule in detail["rules"])


def test_perpetual_whatif_and_demo_curve_reject_before_binary_provider_access(memory, monkeypatch):
    monkeypatch.setattr(server.repo, "get_strategy", lambda *_args: _strategy())
    monkeypatch.setattr(server.kalshi_dev, "measured_slippage_cents", _forbidden)
    monkeypatch.setattr(server.kalshi_dev, "dev_curve_for_strategy", _forbidden)
    with pytest.raises(server.ApiError) as error:
        server.what_if(_ctx(memory, params=("11",)))
    assert error.value.status == 409
    curve = server.strategy_dev_curve(_ctx(memory, params=("11",)))
    assert curve["dev_curve"] is None and "research-only" in curve["reason"]


@pytest.mark.parametrize("mode", ["paper", "demo", "live"])
@pytest.mark.parametrize("exposure", ["primary", "stored_market_mismatch", "cross_leg"])
def test_manual_deployment_rejects_every_perpetual_exposure(memory, monkeypatch, mode, exposure):
    strategy = _strategy()
    if exposure == "stored_market_mismatch":
        strategy["market"] = "btc15m"
    elif exposure == "cross_leg":
        strategy = _strategy({"market": "btc15m", "cross": {
            "pairing": "cross_sectional", "legs": [{"market": "btc_perp"}]}}, market="btc15m")
    monkeypatch.setattr(server.repo, "get_strategy", lambda *_args: strategy)
    monkeypatch.setattr(server.repo, "create_deployment", _forbidden)
    monkeypatch.setattr(server.repo, "get_kalshi_key", _forbidden)
    monkeypatch.setattr(server.repo, "get_kalshi_dev_key", _forbidden)
    with pytest.raises(server.ApiError) as error:
        server.create_deployment(_ctx(memory, body={"strategy_id": 11, "mode": mode, "confirm": "LIVE"}))
    assert error.value.status == 409 and "research-only" in str(error.value)


@pytest.mark.parametrize("action", ["deploy", "deploy_live", "adjust", "resume"])
@pytest.mark.parametrize("autopilot", [False, True])
def test_agent_actions_cannot_create_apply_or_resume_perpetual_deployments(memory, monkeypatch, action, autopilot):
    strategy = _strategy()
    deployment = dict(strategy, status="paused", strategy_id=11, mode="paper", user_id=1)
    monkeypatch.setattr(agent.repo, "get_strategy", lambda *_args: strategy)
    monkeypatch.setattr(agent.repo, "get_deployment", lambda *_args: deployment)
    for name in ("create_deployment", "create_proposal", "set_deployment_strategy", "set_deployment_status"):
        monkeypatch.setattr(agent.repo, name, _forbidden)
    text, proposal_id = agent.act(memory, {"id": 1}, {
        "type": action, "strategy_id": 11, "deployment_id": 11, "changes": {"sizing": {"stake": 50}},
    }, autopilot=autopilot)
    assert proposal_id is None and "research-only" in text


@pytest.mark.parametrize("action", ["deploy", "adjust", "resume"])
def test_old_agent_proposal_cannot_bypass_perpetual_recheck(memory, monkeypatch, action):
    strategy = _strategy()
    deployment = dict(strategy, status="paused", strategy_id=11, mode="paper", user_id=1)
    monkeypatch.setattr(agent.repo, "get_strategy", lambda *_args: strategy)
    monkeypatch.setattr(agent.repo, "get_deployment", lambda *_args: deployment)
    for name in ("create_deployment", "set_deployment_strategy", "set_deployment_status"):
        monkeypatch.setattr(agent.repo, name, _forbidden)
    with pytest.raises(ValueError, match="perpetual"):
        agent.apply_proposal(memory, 1, {"kind": action, "strategy_id": 11, "deployment_id": 11})


def test_manual_resume_is_blocked_but_pausing_perpetual_exposure_remains_possible(memory, monkeypatch):
    deployment = dict(_strategy(), status="paused", mode="paper")
    monkeypatch.setattr(server.repo, "get_deployment", lambda *_args: deployment)
    writes = []
    monkeypatch.setattr(server.repo, "set_deployment_status", lambda *args: writes.append(args) or True)
    with pytest.raises(server.ApiError) as error:
        server.deployment_action(_ctx(memory, params=("11", "resume")))
    assert error.value.status == 409 and not writes
    assert server.deployment_action(_ctx(memory, params=("11", "pause")))["status"] == "paused"
    assert writes[-1][3] == "paused"


def test_successful_perpetual_research_cannot_be_promoted_for_execution(memory):
    accepted, reason = gatekeeper.marginal_contribution_ok(memory, 1, 11, {
        "market": "btc_perp", "spec": specmod.validate({"market": "btc_perp"})})
    assert accepted is False and "research-only" in reason
    assert not memory.t["app_experiment_results"]


@pytest.mark.parametrize("patch", [
    {"code": "def signals(window): return []"},
    {"cross": {"pairing": "cross_strike", "legs": []}},
    {"model": {"kind": "logistic", "features": ["mid"]}},
    {"perpetual": {"leverage": 2}},
    {"perpetual": {"taker_fee_bps": 0}},
    {"perpetual": {"slippage_bps": 0}},
])
def test_unsupported_perpetual_spec_cannot_enter_research(patch):
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": "btc_perp", **patch})


def test_binary_cross_leg_cannot_smuggle_in_a_perpetual():
    with pytest.raises(specmod.SpecError, match="[Pp]erpetual"):
        specmod.validate({"market": "btc15m", "cross": {
            "pairing": "cross_sectional", "legs": [{"market": "btc_perp"}]}})
