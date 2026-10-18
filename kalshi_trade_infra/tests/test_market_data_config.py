"""Offline routing, production preflight and worker environment contracts."""
from datetime import timedelta
import json
from pathlib import Path
import subprocess

import pytest

from app import agent_market_data as market, market_data_config as settings
from app.llm import Usage
from app.market_data_common import MarketDataError
from tests.test_agent_databento_data import NOW, provider as databento_provider
from tests.test_agent_market_data import final_check, provider as alpaca_provider, scripted


def environment(**overrides):
    return {"TAU_MARKET_DATA_PRIMARY": "databento", "TAU_DATABENTO_DEFAULT_DATASET": "EQUS.MINI",
            "TAU_DATABENTO_ENABLED": "1", "TAU_DATABENTO_DATASETS": "EQUS.MINI,GLBX.MDP3",
            "DATABENTO_API_KEY": "synthetic-databento-secret", "TAU_DATABENTO_MAX_COST_USD": "0.10",
            "TAU_ALPACA_ENABLED": "0", "TAU_MASSIVE_ENABLED": "0", **overrides}


@pytest.fixture
def configured(monkeypatch):
    for key, value in environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(market, "utc_now", lambda: NOW)
    market._CACHE.clear()
    yield
    market._CACHE.clear()


def test_default_routing_keeps_existing_installations_compatible():
    routing = settings.Routing.from_env({})
    assert routing.resolve({"kind": "bars"}) == {"provider": "alpaca", "kind": "bars"}
    assert routing.describe()["automatic_fallback"] is False


def test_implicit_history_is_databento_but_snapshots_and_explicit_overrides_are_preserved():
    routing = settings.Routing.from_env(environment())
    assert routing.resolve({"kind": "bars"}) == {"provider": "databento", "kind": "bars", "dataset": "EQUS.MINI"}
    assert routing.resolve({"kind": "snapshots"})["provider"] == "alpaca"
    explicit = {"provider": "alpaca", "kind": "bars", "symbols": ["SPY"]}
    assert routing.resolve(explicit) == explicit
    assert market._request(explicit)["provider"] == "alpaca"
    future = {"provider": "databento", "kind": "bars", "dataset": "GLBX.MDP3", "symbols": ["ESZ6"]}
    assert routing.resolve(future) == future


@pytest.mark.parametrize("overrides", [
    {"TAU_MARKET_DATA_PRIMARY": "massive"}, {"TAU_MARKET_DATA_PRIMARY": ""},
    {"TAU_DATABENTO_DEFAULT_DATASET": ""}, {"TAU_DATABENTO_DEFAULT_DATASET": "GLBX.UNKNOWN"},
    {"TAU_DATABENTO_DEFAULT_DATASET": "https://untrusted.invalid"},
])
def test_invalid_route_never_silently_defaults(overrides):
    with pytest.raises(MarketDataError):
        settings.Routing.from_env(environment(**overrides))


def test_model_omits_provider_and_reaches_databento(configured, databento_provider):
    request = {"market_data_requests": [{"kind": "bars", "symbols": ["SPY"], "lookback_days": 3}]}
    model, prompts = scripted([json.dumps(request), '{"reply":"checked"}'])
    md = market.AgentMarketData(market.DataScope())
    assert md.ask(model, "system", [], final_check, Usage()) == "checked"
    assert len(databento_provider) == 1 and databento_provider[0][1] == "EQUS.MINI"
    assert databento_provider[0][2:4] == (NOW - timedelta(days=3), NOW)
    assert '"primary_bar_provider": "databento"' in prompts[0][1][-1]["content"]
    assert '"last_close": 101' in prompts[1][1][-1]["content"]


def test_explicit_alpaca_override_survives_model_validation_and_second_parse(configured, monkeypatch, databento_provider, alpaca_provider):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "synthetic-alpaca-id")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "synthetic-alpaca-secret")
    request = {"market_data_requests": [
        {"provider": "alpaca", "kind": "bars", "symbols": ["AAPL"]},
        {"kind": "bars", "symbols": ["SPY"]}]}
    model, prompts = scripted([json.dumps(request), '{"reply":"checked both"}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert [c[0] for c in alpaca_provider] == ["snapshots", "bars"]
    assert alpaca_provider[1][1] == ["AAPL"]
    assert len(databento_provider) == 1 and databento_provider[0][0] == ["SPY"]
    results = json.loads(prompts[1][1][-1]["content"].split("\n", 1)[1])
    assert [r["request"]["provider"] for r in results] == ["alpaca", "databento"]


def test_historical_primary_does_not_download_duplicate_alpaca_context(configured, monkeypatch, databento_provider, alpaca_provider):
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "synthetic-alpaca-id")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "synthetic-alpaca-secret")
    cutoff, start = NOW - timedelta(days=30), NOW - timedelta(days=32)
    model, _ = scripted([json.dumps({"market_data_requests": [{"kind": "bars", "symbols": ["SPY"], "lookback_days": 90}]}),
                         '{"reply":"only training bars"}'])
    market.AgentMarketData(market.DataScope(start, cutoff)).ask(model, "system", [], final_check, Usage())
    assert alpaca_provider == [] and len(databento_provider) == 1
    assert databento_provider[0][2:4] == (start, cutoff)


def test_disabled_primary_does_not_fall_back_to_enabled_alpaca(configured, monkeypatch, databento_provider, alpaca_provider):
    monkeypatch.setenv("TAU_DATABENTO_ENABLED", "0")
    monkeypatch.setenv("TAU_ALPACA_ENABLED", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "synthetic-alpaca-id")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "synthetic-alpaca-secret")
    model, prompts = scripted([json.dumps({"market_data_requests": [{"kind": "bars", "symbols": ["SPY"]}]}),
                              '{"reply":"primary unavailable"}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert '"code": "provider_disabled"' in prompts[1][1][-1]["content"]
    assert databento_provider == [] and [c[0] for c in alpaca_provider] == ["snapshots"]


def test_bad_routing_degrades_without_provider_reads_or_secret_echo(configured, monkeypatch, databento_provider, alpaca_provider):
    monkeypatch.setenv("TAU_MARKET_DATA_PRIMARY", "synthetic-wrong-secret")
    model, prompts = scripted(['{"reply":"configuration unavailable"}'])
    market.AgentMarketData(market.DataScope()).ask(model, "system", [], final_check, Usage())
    assert '"code": "invalid_configuration"' in prompts[0][1][-1]["content"]
    assert "synthetic-wrong-secret" not in str(prompts)
    assert databento_provider == alpaca_provider == []


def test_preflight_checks_configuration_without_network_or_secret_output(monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("preflight must be offline"))
    report = settings.check_configuration(environment())
    assert report["ready"] is True and report["errors"] == []
    assert report["provider_validation"] == "not_performed" and report["network_requests"] == 0
    assert report["providers"]["databento"]["historical_only"] is True
    assert "synthetic-databento-secret" not in json.dumps(report)
    assert report["routing"]["default_bar_dataset"] == "EQUS.MINI"


@pytest.mark.parametrize("overrides,code", [
    ({"DATABENTO_API_KEY": ""}, "not_configured"),
    ({"TAU_DATABENTO_MAX_COST_USD": "0"}, "cost_limit"),
    ({"TAU_DATABENTO_MAX_COST_USD": "NaN"}, "invalid_cost"),
    ({"TAU_DATABENTO_MAX_COST_USD": "-1"}, "invalid_cost"),
    ({"TAU_DATABENTO_ENABLED": "0"}, "provider_disabled"),
    ({"TAU_DATABENTO_ENABLED": "true"}, "invalid_configuration"),
    ({"TAU_DATABENTO_DATASETS": ""}, "invalid_configuration"),
    ({"TAU_MASSIVE_ENABLED": "1", "MASSIVE_API_KEY": ""}, "not_configured"),
    ({"TAU_ALPACA_ENABLED": "1", "APCA_API_KEY_ID": "", "APCA_API_SECRET_KEY": ""}, "not_configured"),
])
def test_incomplete_production_configuration_is_not_ready(overrides, code):
    report = settings.check_configuration(environment(**overrides))
    assert report["ready"] is False and code in {e["code"] for e in report["errors"]}


def test_disabled_unused_credentials_are_optional():
    report = settings.check_configuration(environment(MASSIVE_API_KEY="", APCA_API_KEY_ID="", APCA_API_SECRET_KEY=""))
    assert report["ready"] and not report["providers"]["massive"]["configured"]


def test_preflight_validates_secondary_feeds_and_watchlists():
    env = environment(TAU_ALPACA_ENABLED="1", APCA_API_KEY_ID="synthetic", APCA_API_SECRET_KEY="synthetic",
                      TAU_ALPACA_FEED="unsupported", TAU_MASSIVE_ENABLED="1", MASSIVE_API_KEY="synthetic",
                      TAU_MASSIVE_DATASETS="fx", TAU_MASSIVE_FX_SYMBOLS="EURUSD,USDJPY,GBPUSD,EURJPY")
    report = settings.check_configuration(env)
    assert not report["ready"] and {e["field"] for e in report["errors"]} == {"alpaca", "massive"}


def test_cli_exit_codes_are_actionable_and_output_is_redacted(monkeypatch, capsys):
    for key, value in environment().items():
        monkeypatch.setenv(key, value)
    assert settings.main(["check"]) == 0
    report = capsys.readouterr().out
    assert json.loads(report)["ready"] and "synthetic-databento-secret" not in report
    monkeypatch.setenv("DATABENTO_API_KEY", "")
    assert settings.main(["check"]) == 2
    assert not json.loads(capsys.readouterr().out)["ready"]


def test_worker_sources_overlay_after_base_secrets_and_fails_if_present_invalid(tmp_path):
    unit = Path("scripts/systemd/recursive-agents.service").read_text()
    line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert line.index(".env.app") < line.index(".env.market-data")
    assert "/bin/bash -ec " in line
    # Run the actual Bash loading portion against synthetic files, not /opt.
    (tmp_path / ".env.aws").write_text("export TAU_MARKET_DATA_PRIMARY=alpaca\n")
    (tmp_path / ".env.app").write_text("export TAU_MARKET_DATA_PRIMARY=alpaca\n")
    (tmp_path / "logs").mkdir()
    (tmp_path / ".venv/bin").mkdir(parents=True)
    # Synthetic preflight executable; failures must stop before worker launch.
    python = tmp_path / ".venv/bin/python"
    python.write_text('#!/bin/bash\n[ "$*" = "-m app.market_data_config check" ] && [ "$TAU_MARKET_DATA_PRIMARY" = databento ]\n')
    python.chmod(0o700)
    body = line.split(" -ec '", 1)[1].rsplit("'", 1)[0].split("; set +a;", 1)[0]
    body = body.replace("/opt/kalshi", str(tmp_path))
    def run():
        return subprocess.run(["/bin/bash", "-ec", body + '; printf "%s" "$TAU_MARKET_DATA_PRIMARY"'], capture_output=True, text=True)
    result = run()
    assert result.returncode == 0 and result.stdout == "alpaca"
    (tmp_path / ".env.market-data").write_text("export TAU_MARKET_DATA_PRIMARY=databento\n")
    result = run()
    assert result.returncode == 0 and result.stdout == "databento"
    (tmp_path / ".env.market-data").write_text("this is not valid config\n")
    assert run().returncode != 0
    (tmp_path / ".env.market-data").write_text("export TAU_MARKET_DATA_PRIMARY=invalid\n")
    assert run().returncode != 0
    (tmp_path / ".env.market-data").unlink()
    (tmp_path / ".env.market-data").symlink_to(tmp_path / "missing-overlay")
    assert run().returncode != 0
