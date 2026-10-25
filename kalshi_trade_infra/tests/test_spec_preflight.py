"""Pre-flight: every spec shape the research prompts teach must pass the validator.

The proposer writes specs from SPEC_GUIDE / CODE_STRATEGY_GUIDE / PERPETUAL_GUIDE. When a guide and
the validator drift apart (2026-10-24: code specs carrying the DSL field "side" were rejected and
whole research batches died), this file fails in CI instead of in a live research run.
"""
import json
import re

import pytest

from app import agent, spec as specmod
from app.markets import MARKETS

BINARY = [k for k, m in MARKETS.items() if m.kind != "perpetual"]
PERP = [k for k, m in MARKETS.items() if m.kind == "perpetual"]

RULE_CODE = '''
def signals(window):
    out = []
    for fr in window["frames"]:
        picks = []
        for c in fr["contracts"]:
            if c["yes_ask"] < 0.2:
                picks.append({"ticker": c["ticker"], "side": "yes", "score": 1.0})
        out.append(picks)
    return out
'''


def _guide_code(marker_start, marker_end):
    """A code example lifted from CODE_STRATEGY_GUIDE (dedented), so a guide edit is re-checked."""
    g = specmod.CODE_STRATEGY_GUIDE
    body = g[g.index(marker_start):g.index(marker_end)]
    return "\n".join(line[2:] if line.startswith("  ") else line for line in body.splitlines())


def _full_dsl(market):
    """Every field SPEC_GUIDE documents, each set to a value inside its documented range."""
    return {
        "market": market, "side": "yes",
        "model": {"kind": "gbm", "vol_window": 60, "vol_scale": 1.0, "drift_window": 15, "drift_beta": 0.5},
        "entry": {"min_edge": 0.05, "min_price": 0.05, "max_price": 0.95, "min_tte_min": 1, "max_tte_min": 1440,
                  "max_spread": 0.05, "filters": [{"feature": "tte_min", "op": ">", "value": 2}]},
        "exit": {"take_profit": 0.2, "stop_loss": 0.2, "min_edge_to_hold": None},
        "sizing": {"stake": 5, "max_positions": 20},
    }


def test_every_top_level_field_the_dsl_guide_names_is_accepted():
    named = set(re.findall(r'^\s{2}"(\w+)":', specmod.SPEC_GUIDE.split("Features for filters")[0], re.M))
    assert {"market", "side", "model", "entry", "exit", "sizing", "cross"} <= named
    spec = _full_dsl(BINARY[0])
    assert named - {"cross"} <= set(spec)
    specmod.validate(dict(spec, cross=None))


@pytest.mark.parametrize("market", BINARY)
def test_the_full_documented_dsl_spec_validates_on_every_market(market):
    out = specmod.validate(_full_dsl(market))
    assert out["market"] == market and out["side"] == "yes"


@pytest.mark.parametrize("kind", ["logistic", "calibration"])
def test_learned_model_kinds_validate_as_documented(kind):
    model = {"kind": kind, "features": ["tte_min"]} if kind == "logistic" else {"kind": kind}
    specmod.validate({"market": BINARY[0], "model": model})


def test_every_documented_feature_validates_as_a_filter():
    from app.markets import CROSS_FEATURES
    for name in specmod.FEATURES:
        market = ("btc15m" if name.startswith("eth_") else "eth15m") if name in CROSS_FEATURES else BINARY[0]
        specmod.validate({"market": market,
                          "entry": {"filters": [{"feature": name, "op": ">=", "value": 0}]}})


def test_cross_asset_features_are_refused_on_markets_that_never_carry_them():
    flt = lambda name: {"entry": {"filters": [{"feature": name, "op": ">", "value": 0}]}}
    with pytest.raises(specmod.SpecError, match="only exists on non-BTC crypto markets"):
        specmod.validate(dict(flt("btc_ret_5m"), market="btc15m"))
    with pytest.raises(specmod.SpecError, match="only exists on BTC markets"):
        specmod.validate(dict(flt("eth_ret_15m"), market="sol15m"))
    with pytest.raises(specmod.SpecError, match="only exists on"):
        specmod.validate({"market": "nba_game", "model": {"kind": "logistic", "features": ["btc_ret_1m"]}})
    for market in ("sol_daily", "xrp15m", "hype15m", "eth_daily"):
        specmod.validate(dict(flt("btc_vol_60m"), market=market))
    specmod.validate(dict(flt("eth_ret_60m"), market="btc_daily"))


@pytest.mark.parametrize("market", BINARY)
def test_a_code_spec_validates_on_every_market(market):
    out = specmod.validate({"market": market, "sizing": {"stake": 5, "max_positions": 5}, "code": RULE_CODE})
    assert set(out) == {"market", "sizing", "code"}


@pytest.mark.parametrize("field,value", [("side", "yes"), ("side", "either"), ("model", {"kind": "gbm"}),
                                         ("entry", {"min_edge": 0.05}), ("exit", {"take_profit": None}),
                                         ("cross", {"kind": "cross_strike"})])
def test_dsl_fields_carried_onto_a_code_spec_are_dropped_not_fatal(field, value):
    raw = {"market": BINARY[0], "code": RULE_CODE, field: value}
    out = specmod.validate(raw)
    assert set(out) == {"market", "sizing", "code"}
    assert specmod.ignored_code_fields(raw) == [field]


def test_a_truly_unknown_field_on_a_code_spec_is_still_an_error():
    with pytest.raises(specmod.SpecError, match="unknown field"):
        specmod.validate({"market": BINARY[0], "code": RULE_CODE, "sidee": "yes"})


def test_the_guides_code_examples_pass_the_static_gate():
    rf = _guide_code("  import numpy as np, pickle, base64", "EVENT / NON-PRICE")
    specmod.validate({"market": BINARY[0], "code": rf})


def test_the_guides_dataset_examples_validate():
    out = specmod.validate({"market": BINARY[0], "code": RULE_CODE, "datasets": [
        {"name": "dgs10", "source": "fred", "series": "DGS10", "lag_days": 1},
        {"name": "nyc_high", "source": "asos", "series": "NYC:dailymax", "lag_days": 0}]})
    assert [d["name"] for d in out["datasets"]] == ["dgs10", "nyc_high"]


@pytest.mark.skipif(not PERP, reason="no perpetual market in the catalog")
def test_the_perpetual_guide_example_validates():
    g = specmod.PERPETUAL_GUIDE
    example = json.loads(g[g.index("{"):g.index("}}") + 2])
    assert specmod.validate(example)["market"] in PERP


def test_one_invalid_idea_gets_one_repair_then_no_longer_sinks_the_batch():
    m = BINARY[0]
    good = {"title": "Good", "thesis": "t", "spec": {"market": m, "code": RULE_CODE, "side": "yes"}}
    bad = {"title": "Bad", "thesis": "t", "spec": {"market": m, "entry": {"min_edge": 9}}}
    check = agent._hypotheses_check(m, 3)
    with pytest.raises(ValueError, match="hypotheses\\[1\\].spec"):
        check({"hypotheses": [good, bad]})        # first reply: the error goes back for a repair
    out = check({"hypotheses": [good, bad]})      # still invalid after the repair: keep the good one
    assert [h["title"] for h in out] == ["Good"]
    assert check.invalid and check.invalid[0]["title"] == "Bad"
    assert check.invalid[0]["why"].startswith("spec invalid:")
    with pytest.raises(ValueError):
        check({"hypotheses": [bad]})               # nothing valid: the attempt still fails


def test_a_proposer_batch_that_never_validates_is_a_logged_drop_not_a_dead_run():
    from app import rsi
    assert rsi.classify_drop("spec invalid: unknown field(s) for a code strategy: side") == ("spec_invalid", "pipeline")
    assert rsi.classify_drop("The agent's reply could not be used: hypotheses[0].spec: x")[0] == "spec_invalid"
    card = rsi.run_card({"id": 1, "status": "failed", "market": BINARY[0],
                         "error": "The agent's reply could not be used: unknown field(s) for a code strategy: side"},
                        [{"kind": "verdict", "message": "DROPPED", "data": {"status": "abandoned", "title": "x",
                                                                          "why": "spec invalid: bad"}}])
    assert card["spec_failed_runs"] == 1 and card["deaths"] == {"spec_invalid": 1}
    board = rsi.scoreboard([card])["total"]
    assert board["spec_failed_runs"] == 1 and board["bug_death_rate"] == 1.0


def test_a_multi_day_tte_window_validates():
    # Prod 2026-10-24: an NFL spread spec with min_tte_min=2000 died as "outside 0.0..1500.0".
    out = specmod.validate({"market": BINARY[0], "entry": {"min_tte_min": 2000, "max_tte_min": 10080}})
    assert (out["entry"]["min_tte_min"], out["entry"]["max_tte_min"]) == (2000, 10080)
    assert specmod.validate({"market": BINARY[0]})["entry"]["max_tte_min"] == 1500.0   # default unchanged
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": BINARY[0], "entry": {"max_tte_min": 50000}})


def test_a_min_tte_past_the_default_window_without_a_max_means_from_min_onward():
    # Prod 2026-10-24 run 2689: min_tte_min=2000 with no max died as "min must be < max" (max 1500).
    out = specmod.validate({"market": BINARY[0], "entry": {"min_tte_min": 2000}})
    assert out["entry"]["max_tte_min"] == 43200.0
    with pytest.raises(specmod.SpecError, match="must be < entry.max_tte_min"):
        specmod.validate({"market": BINARY[0], "entry": {"min_tte_min": 2000, "max_tte_min": 1000}})


def test_the_code_window_names_each_contracts_event():
    # Prod 2026-10-24 run 2702: four NFL ladder ideas died "ticker format unknown" trying to group
    # strikes by game; the window now carries the event.
    from datetime import datetime, timezone
    from app import backtest
    from app.markets import Contract, Snapshot
    c = Contract("KXNFLSPREAD-25OCT26KCWAS-KC7", 7.0, datetime(2026, 10, 26, tzinfo=timezone.utc))
    snap = Snapshot(contract=c, ts=1, yes_bid=0.4, yes_ask=0.42, features={})
    w = backtest._binary_window("x", [(1, [snap])])
    assert w["frames"][0]["contracts"][0]["event"] == "KXNFLSPREAD-25OCT26KCWAS"
    assert '"event": str' in specmod.CODE_STRATEGY_GUIDE


def test_a_cross_leg_with_extra_keys_says_how_to_repair_it():
    # Prod 2026-10-24 run 2741: "cross.legs[0] must have exactly feature market" gave the repair
    # round nothing to go on, and the idea died.
    m = BINARY[0]
    with pytest.raises(specmod.SpecError) as e:
        specmod.validate({"market": m, "cross": {"pairing": "cross_strike",
                                                  "legs": [{"market": m, "strike_offset": 1}]}})
    assert 'must be exactly {"market": <key>}' in str(e.value) and "strike_offset" in str(e.value)


def test_the_guide_says_pool_is_off_on_one_minute_event_series():
    from app.markets import MARKETS
    sports = next(k for k, m in MARKETS.items() if m.kind == "binary" and not specmod._poolable(m))
    assert "POOL IS NOT AVAILABLE ON %s" % sports in specmod.research_guide(sports)
    assert "POOL IS NOT AVAILABLE" not in specmod.research_guide("btc15m")


def test_the_code_guide_says_sports_ladders_carry_strikes():
    """Prod hist_markets (2026-10-25): KXNFLTOTAL/SPREAD/RECYDS... carry real floor_strikes; the guide's
    old "there is no strike" line made runs 2754/2761 drop ladder theses as missing_context."""
    assert "There is no strike" not in specmod.CODE_STRATEGY_GUIDE
    assert 'c["strike"]' in specmod.CODE_STRATEGY_GUIDE and "LADDER" in specmod.CODE_STRATEGY_GUIDE


def test_a_null_exit_means_hold_to_settlement():
    """Prod run 2847 lost three ideas to "exit must be an object": the proposer wrote "exit": null."""
    spec = specmod.validate({"market": "btc15m", "side": "yes", "exit": None})
    assert spec["exit"] == {"take_profit": None, "stop_loss": None, "min_edge_to_hold": None}
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": "btc15m", "side": "yes", "exit": "settle"})


def test_a_sub_cent_exit_snaps_to_one_cent():
    """Prod run 2887 lost an idea to "exit.stop_loss=0.008 is outside 0.01..0.99". Prices move in
    whole cents, so a 0.8c stop fires exactly when a 1c stop does."""
    spec = specmod.validate({"market": "btc15m", "side": "yes",
                             "exit": {"stop_loss": 0.008, "take_profit": 0.005}})
    assert spec["exit"]["stop_loss"] == 0.01 and spec["exit"]["take_profit"] == 0.01
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": "btc15m", "side": "yes", "exit": {"stop_loss": -0.02}})


def test_a_code_strategy_can_pool_and_trades_every_pooled_market():
    """Prod run 2897 lost a pooled multi-feature model to "unknown field(s) for a code strategy:
    pool". A pooled code spec is judged on the merged frames, like a pooled DSL rule."""
    out = specmod.validate({"market": "btc15m", "code": RULE_CODE, "pool": ["eth15m", "btc15m"],
                            "sizing": {"stake": 10, "max_positions": 4}})
    assert out["pool"] == ["eth15m"] and specmod.is_multi_market(out)
    assert specmod.involved_markets(out) == ["btc15m", "eth15m"]
    with pytest.raises(specmod.SpecError, match="pool"):
        specmod.validate({"market": "btc15m", "code": RULE_CODE, "pool": ["nba_game"]})
    assert "pool" not in specmod.validate({"market": "btc15m", "code": RULE_CODE})


def test_a_pooled_code_strategy_trades_every_pooled_market(monkeypatch):
    from app import backtest, sandbox

    def in_process(code, window, data_dir=None):   # this test's own trusted code; no confiner needed
        ns = {}
        exec(code, ns)
        return ns["signals"](window)
    monkeypatch.setattr(sandbox, "run_strategy_signals", in_process)
    from tests.test_app_backtest import _dataset, _renamed
    out = specmod.validate({"market": "btc15m", "code": RULE_CODE, "pool": ["eth15m"],
                            "sizing": {"stake": 10, "max_positions": 4}})
    a = _dataset(n_contracts=10)
    merged = backtest.merge_datasets([a, _renamed(a, "E")], key="btc15m+eth15m")
    every = RULE_CODE.replace('if c["yes_ask"] < 0.2:', 'if c["yes_ask"] < 0.99:')
    trades = backtest.simulate(dict(out, code=every), merged, merged.start_ts, merged.end_ts + 1)
    assert {t.ticker[0] for t in trades} == {"M", "E"}   # evidence from both pooled markets
