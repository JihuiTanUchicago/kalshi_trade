"""Research-only perpetuals cannot enter the existing binary deployment engine."""
from dataclasses import replace

import pytest

from app.trading import engine
from app.trading.markets import Market


class _NoExecution:
    def __getattr__(self, name):
        raise AssertionError("research-only rejection must precede %s" % name)


@pytest.fixture
def perpetual(monkeypatch):
    # The instrument gate must survive an accidentally enabled deployable flag, too.
    market = Market("btc_perp", "BTC-PERP", "Bitcoin perpetual", 1, 30,
                    kind="perpetual", deployable=True)
    monkeypatch.setitem(engine.MARKETS, market.key, market)
    return market


@pytest.mark.parametrize("mode", ["paper", "demo", "live"])
@pytest.mark.parametrize("deployable", [False, True])
@pytest.mark.parametrize("exposure", ["primary", "single_cross", "cross_leg"])
def test_deploy_gate_rejects_perpetuals_in_every_mode(
        monkeypatch, perpetual, mode, deployable, exposure):
    monkeypatch.setitem(engine.MARKETS, perpetual.key, replace(perpetual, deployable=deployable))
    spec = {"market": perpetual.key}
    if exposure == "single_cross":
        spec["cross"] = {"pairing": "cross_strike", "legs": []}
    elif exposure == "cross_leg":
        spec = {"market": "btc15m", "cross": {
            "pairing": "cross_sectional", "legs": [{"market": perpetual.key}],
        }}
    reason = engine.cross_deploy_block(spec, mode)
    assert reason and "research-only" in reason
    assert all(word in reason for word in ("paper", "demo", "live"))


@pytest.mark.parametrize("mode", ["paper", "demo", "live"])
@pytest.mark.parametrize("exposure", ["spec", "deployment", "cross_leg"])
def test_direct_decide_rejects_before_database_or_order_access(perpetual, mode, exposure):
    dep = {"mode": mode, "market": "btc15m", "spec": {"market": "btc15m"}}
    if exposure == "spec":
        dep["spec"]["market"] = perpetual.key
    elif exposure == "deployment":
        dep["market"] = perpetual.key
    else:
        dep["spec"]["cross"] = {
            "pairing": "cross_sectional", "legs": [{"market": perpetual.key}],
        }
    result = engine.decide(_NoExecution(), dep, [], {}, _NoExecution())
    assert "research-only" in result["blocked"]


@pytest.mark.parametrize("deployable", [False, True])
def test_direct_tick_rejects_even_unregistered_perpetual_before_any_work(deployable):
    market = Market("unregistered_perp", "BTC-PERP", "Bitcoin perpetual", 1, 30,
                    kind="perpetual", deployable=deployable)
    result = engine.tick_market(_NoExecution(), market, _NoExecution())
    assert "research-only" in result["blocked"]


@pytest.mark.parametrize("cross", [None, {"legs": None}, {"legs": [None, "invalid"]}])
def test_perpetual_gate_is_safe_with_missing_or_damaged_cross_metadata(perpetual, cross):
    assert "research-only" in engine.cross_deploy_block({"market": perpetual.key, "cross": cross}, "live")


@pytest.mark.parametrize("perpetual_first", [False, True])
def test_cross_frame_rejects_all_legs_before_fetching_any_binary_feed(perpetual, perpetual_first):
    markets = [perpetual.key, "btc15m"] if perpetual_first else ["btc15m", perpetual.key]
    assert engine._cross_market_frame(markets, _NoExecution(), 1_800_000_000) is None


@pytest.mark.parametrize("mode", ["paper", "demo", "live"])
def test_existing_binary_deploy_gate_stays_available(mode):
    assert engine.cross_deploy_block({"market": "btc15m"}, mode) is None
    assert engine.cross_deploy_block({
        "market": "btc15m", "cross": {"pairing": "cross_strike", "legs": []},
    }, mode) is None
