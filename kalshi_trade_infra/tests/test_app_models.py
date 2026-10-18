"""Model selection: registry, create_run validation, and that research bills at
the chosen model's exact price."""
from decimal import Decimal

import pytest

from app import billing, server
from app import models_catalog as catalog
from tests.test_app_agent import Conn, LOSER, RUN, Store, WINNER, hyps, plan, scripted
from tests.test_app_backtest import _dataset


class FakeCur:
    lastrowid = 1
    rowcount = 1

    def execute(self, *a):
        pass

    def fetchone(self):
        return {"n": 0}


class FakeConn:
    def cursor(self):
        return FakeCur()


def ctx(body):
    return server.Ctx(FakeConn(), {"id": 1, "autopilot": 0}, (), {}, body, None)


# -- registry (single source of truth) ------------------------------------------


def test_default_model_is_opus_4_5():
    assert catalog.DEFAULT_KEY == "opus-4-5"
    assert catalog.default().model_id == "us.anthropic.claude-opus-4-5-20251101-v1:0"
    cj = catalog.catalog_json()
    assert sum(1 for m in cj if m["default"]) == 1  # exactly one default
    assert next(m for m in cj if m["default"])["key"] == "opus-4-5"


def test_models_endpoint_returns_the_registry():
    res = server.models(ctx({}))
    assert res["default"] == "opus-4-5"
    keys = {m["key"] for m in res["models"]}
    assert {"sonnet-4-5", "opus-4-5", "nova-pro", "llama-3-3-70b"} <= keys


# -- create_run validation ------------------------------------------------------


def test_create_run_accepts_a_valid_model(monkeypatch):
    captured = {}
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(server.repo, "create_run", lambda *a, **k: captured.update(k) or 7)
    assert server.create_run(ctx({"prompt": "a solid research idea", "model": "opus-4-5"})) == {"id": 7}
    assert captured["model"] == "opus-4-5"  # the chosen key is persisted on the run


def test_create_run_rejects_an_unknown_model(monkeypatch):
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(server.repo, "create_run", lambda *a, **k: 1)
    with pytest.raises(server.ApiError) as e:
        server.create_run(ctx({"prompt": "a solid research idea", "model": "gpt-9-turbo"}))
    assert e.value.status == 400  # never meter a model with no known price


def test_create_run_omitted_model_defaults_to_none(monkeypatch):
    captured = {}
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(server.repo, "create_run", lambda *a, **k: captured.update(k) or 1)
    server.create_run(ctx({"prompt": "a solid research idea"}))
    assert captured["model"] is None  # NULL = server default (Sonnet), unchanged behavior


# -- billing is exact, per the registry -----------------------------------------


def test_each_model_prices_exactly_from_the_registry():
    # USD per 1,000,000 tokens (input, output), billed on the invokable modelId at list * 2x margin.
    sonnet = catalog.MODELS["sonnet-4-5"]
    assert billing.usage_cost(sonnet.model_id, 1_000_000, 1_000_000) == Decimal("36.000000")  # (3 + 15) * 2
    opus = catalog.MODELS["opus-4-5"]
    assert billing.usage_cost(opus.model_id, 1_000_000, 1_000_000) == Decimal("60.000000")  # (5 + 25) * 2
    nova = catalog.MODELS["nova-lite"]
    assert billing.usage_cost(nova.model_id, 1_000_000, 1_000_000) == Decimal("0.600000")  # (0.06 + 0.24) * 2
    llama = catalog.MODELS["llama-3-3-70b"]
    assert billing.usage_cost(llama.model_id, 2_000_000, 1_000_000) == Decimal("4.320000")  # (2*0.72 + 0.72) * 2


# -- the chosen model threads through research and billing ----------------------


def _bill_recorder(monkeypatch):
    from app import agent
    billed = []
    monkeypatch.setattr(agent.billing, "charge_usage",
                        lambda conn, uid, model, i, o, rid: billed.append(model))
    return billed


def test_research_bills_at_the_chosen_models_price(monkeypatch):
    from app import agent
    Store(monkeypatch)
    billed = _bill_recorder(monkeypatch)
    model, _ = scripted([plan(), hyps(WINNER, LOSER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 3, "model": "opus-4-5"},
                       model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert billed and all(b == catalog.MODELS["opus-4-5"].model_id for b in billed)


def test_research_without_a_model_bills_at_the_default_sonnet(monkeypatch):
    from app import agent
    Store(monkeypatch)
    billed = _bill_recorder(monkeypatch)
    model, _ = scripted([plan(), hyps(WINNER, LOSER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 3},  # no "model" -> default
                       model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert billed and all(b == catalog.default().model_id for b in billed)
