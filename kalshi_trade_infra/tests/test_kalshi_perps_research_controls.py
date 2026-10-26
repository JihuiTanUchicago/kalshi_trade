"""Default-off entry points and UTC research windows, without real infrastructure."""
import os
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import agent, backtest, partitions, server, spec
from app.adapters.kalshi_perps import kalshi_perps_backtest as simulator
from app.adapters.kalshi_perps import kalshi_perps_repository as sources


def forbidden(*_args, **_kwargs):
    pytest.fail("Disabled research must not queue work, bill, or contact infrastructure")


def context(body):
    return server.Ctx(SimpleNamespace(cursor=lambda: object()), {"id": 7}, ("11",), {}, body, SimpleNamespace())


@pytest.mark.parametrize("flag", [None, "0", "invalid"])
@pytest.mark.parametrize("deeper", [False, True])
def test_manual_perpetual_research_rejects_disabled_configuration_before_queue(monkeypatch, flag, deeper):
    monkeypatch.delenv("TAU_KALSHI_PERPS_ENABLED", raising=False)
    if flag is not None:
        monkeypatch.setenv("TAU_KALSHI_PERPS_ENABLED", flag)
    monkeypatch.setattr(server, "_require_research_capacity", forbidden)
    monkeypatch.setattr(server.repo, "create_run", forbidden)
    monkeypatch.setattr(server, "_owned_strategy", lambda _ctx: {"market": "btc_perp", "status": "passed"})
    handler = server.dig_deeper if deeper else server.create_run
    with pytest.raises(server.ApiError) as error:
        handler(context({"market": "btc_perp", "prompt": "Test a causal Bitcoin research idea"}))
    assert error.value.status == 409


@pytest.mark.parametrize("sid", [None, 11])
def test_agent_cannot_queue_disabled_perpetual_research(monkeypatch, sid):
    monkeypatch.delenv("TAU_KALSHI_PERPS_ENABLED", raising=False)
    monkeypatch.setattr(agent.repo, "get_strategy", lambda *_a: {"market": "btc_perp", "status": "passed"})
    monkeypatch.setattr(agent.repo, "create_run", forbidden)
    monkeypatch.setattr(agent.repo, "count_runs", forbidden)
    message, proposal = agent.act(object(), {"id": 7}, {
        "type": "research", "market": "btc_perp", "strategy_id": sid,
        "idea": "Study an observed funding imbalance",
    }, autopilot=True)
    assert "disabled" in message.lower() and proposal is None


def test_enabled_perpetual_research_uses_the_existing_manual_queue(monkeypatch):
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENABLED", "1")
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENVIRONMENT", "production")
    monkeypatch.setattr(server, "_require_research_capacity", lambda _ctx: None)
    queued = []
    monkeypatch.setattr(server.repo, "create_run", lambda *a, **kw: queued.append((a, kw)) or 88)
    assert server.create_run(context({"market": "btc_perp", "prompt": "Test a causal Bitcoin research idea"})) == {"id": 88}
    assert queued[0][0][1:4] == (7, "research", "btc_perp")


def test_perpetual_default_capital_and_market_guide_do_not_change_binary_defaults():
    normalized = spec.validate({"market": "btc_perp"})
    assert normalized["sizing"] == {"stake": 100.0, "max_positions": 1}
    assert spec.DEFAULT_SPEC["sizing"]["stake"] == 5
    assert "observed" in spec.research_guide("btc_perp") or "observable" in spec.research_guide("btc_perp")
    assert spec.research_guide("btc15m") == spec.SPEC_GUIDE
    assert "perpetual" in agent._research_system("btc_perp").lower()
    assert agent._research_system("btc15m") == agent.RESEARCH_SYSTEM


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="Requires POSIX timezone handling")
@pytest.mark.parametrize("host_zone", ["UTC", "Asia/Shanghai", "America/New_York"])
@pytest.mark.parametrize("aware", [False, True])
def test_perpetual_loaders_convert_repo_utc_without_host_timezone_shift(monkeypatch, host_zone, aware):
    saved_zone = os.environ.get("TZ")
    os.environ["TZ"] = host_zone
    time.tzset()
    try:
        frozen_now = datetime(2026, 10, 23, 4, tzinfo=timezone.utc)
        clock_value = frozen_now if aware else frozen_now.replace(tzinfo=None)
        expected = int((frozen_now - timedelta(days=90)).timestamp())
        captured = []
        monkeypatch.setenv("TAU_KALSHI_PERPS_ENABLED", "1")
        monkeypatch.setenv("TAU_KALSHI_PERPS_ENVIRONMENT", "production")
        monkeypatch.setattr(partitions, "now_utc", lambda: clock_value)
        monkeypatch.setattr(sources, "partition_lock", lambda *_args: nullcontext())
        monkeypatch.setattr(partitions.rr, "get_active_partition", lambda *_args: None)

        def empty_history(_cur, _market, since, *_args, **_kwargs):
            captured.append(since)
            return {"candles": [], "data_fingerprint": "a" * 64}

        monkeypatch.setattr(sources, "load_history", empty_history)
        with pytest.raises(ValueError, match="Not enough completed"):
            partitions.ensure_partition(object(), "btc_perp")

        from app import repository
        from data_pipeline import common

        class Connection:
            closed = False

            def cursor(self):
                return nullcontext(object())

            def close(self):
                self.closed = True

        connection = Connection()
        monkeypatch.setattr(repository, "now_utc", lambda: clock_value)
        monkeypatch.setattr(common, "get_db_conn", lambda: connection)
        monkeypatch.setattr(simulator, "build_dataset", lambda _market, _history: "loaded")
        assert backtest.load_from_db(backtest.MARKETS["btc_perp"]) == "loaded"
        assert connection.closed and captured == [expected, expected]
    finally:
        if saved_zone is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved_zone
        time.tzset()
