"""The strategy page's payload: what it tells the page about a strategy's kind and how it reads."""
import pytest

from app.trading import spec as specmod
from app.web.http import ApiError
from app.web.routes import deployments as deployment_routes
from app.web.routes import strategies as strategy_routes

CODE = "def signals(window):\n    return {}\n"


def _row(spec, status="passed"):
    return {"id": 7, "run_id": None, "parent_id": None, "market": spec.get("market", "btc15m"), "direction": "momentum",
            "title": "t", "thesis": "th", "status": status, "created_at": None, "result": {}, "spec": spec}


def test_a_code_strategy_card_is_research_only_like_the_deploy_route_says():
    code = specmod.validate({"market": "btc15m", "code": CODE})
    card = strategy_routes._strategy_card(_row(code))
    assert card["kind"] == "code" and card["research_only"] is True
    # A rule-based strategy carries neither flag: the page keeps its deploy buttons.
    rule = strategy_routes._strategy_card(_row(specmod.validate({"market": "btc15m", "side": "yes"})))
    assert "kind" not in rule and "research_only" not in rule


def test_the_deploy_route_refuses_a_code_strategy_in_every_mode(monkeypatch):
    # The flag above mirrors this refusal: if the route ever deploys code, the card must change too.
    code = specmod.validate({"market": "btc15m", "code": CODE})
    monkeypatch.setattr(deployment_routes.repo, "get_strategy", lambda cur, uid, sid: _row(code))

    class Ctx:
        cur, uid = None, 1

    for mode in ("paper", "demo", "live"):
        c = Ctx()
        c.body = {"strategy_id": 7, "mode": mode, "confirm": "LIVE"}
        with pytest.raises(ApiError) as err:
            deployment_routes.create_deployment(c)
        assert err.value.status == 409 and "research-only" in str(err.value)


def test_the_rules_read_entry_filters_in_plain_words():
    spec = specmod.validate({"market": "btc15m", "entry": {"filters": [
        {"feature": "ret_5m", "op": ">", "value": 0.004}, {"feature": "ob_imbalance", "op": "<", "value": -0.2},
        {"feature": "vol_60m", "op": "<=", "value": 0.0012}, {"feature": "z_score", "op": ">=", "value": 1.5}]}})
    lines = specmod.describe(spec)
    assert "Only when the 5-minute return is above +0.40%." in lines
    assert "Only when order-book imbalance is below -0.2." in lines
    assert "Only when the 60-minute volatility is at most 0.12%." in lines
    assert "Only when the z-score is at least 1.5." in lines
    assert not any("ret_5m" in line or "ob_imbalance" in line for line in lines)


def test_every_known_feature_reads_as_a_short_phrase_or_its_own_name():
    # A feature documented with a formula or a paragraph keeps its name rather than printing either.
    for name in specmod.FEATURES:
        line = specmod._plain_filter({"feature": name, "op": ">", "value": 1})
        assert line.startswith("Only when ") and " is above " in line and line.endswith(".")
        assert "(" not in line.replace("(ET)", "") and "/" not in line and len(line) < 130, line
