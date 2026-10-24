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
    for name in specmod.FEATURES:
        specmod.validate({"market": BINARY[0],
                          "entry": {"filters": [{"feature": name, "op": ">=", "value": 0}]}})


@pytest.mark.parametrize("market", BINARY)
def test_a_code_spec_validates_on_every_market(market):
    out = specmod.validate({"market": market, "sizing": {"stake": 5, "max_positions": 5}, "code": RULE_CODE})
    assert set(out) == {"market", "sizing", "code"}


@pytest.mark.parametrize("field,value", [("side", "yes"), ("side", "either"), ("model", {"kind": "gbm"}),
                                         ("entry", {"min_edge": 0.05}), ("exit", {"take_profit": None})])
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
