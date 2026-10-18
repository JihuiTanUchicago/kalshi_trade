"""Fit-on-research-and-FREEZE for code/ML strategies, and the fold-boundary guarantee.

A code strategy that trains a model defines fit(window): it is run ONCE on the research window,
its params are frozen into the pre-registered spec, and signals() predicts with those frozen
params on every later (unseen) window WITHOUT refitting. This is the non-negotiable invariant —
a model that re-fit inside signals() at validation time would score itself on held-out data and
its "edge" would be fake. These tests prove the params are frozen, part of the experiment
identity, fed to signals on a DIFFERENT window, and that no cross-fold channel (data_dir) is open.
"""
from app import backtest, sandbox
from app import spec as specmod
from app.gatekeeper import Prereg

from tests.test_code_strategy import _dataset, _code_spec, BUY_ALL, needs_confiner

# A strategy that TRAINS on research (here: just counts the research frames) and predicts with
# the frozen count. If signals ever refit on its own window it would see the fold's own frame
# count instead of the research one — the leak this whole mechanism closes.
FIT_COUNT = """
def fit(window):
    return {"n": len(window["frames"])}
def signals(window):
    n = window["params"]["n"]
    out = []
    for i, fr in enumerate(window["frames"]):
        if i == 0 and fr["contracts"]:
            out.append([{"ticker": fr["contracts"][0]["ticker"], "side": "yes", "score": float(n)}])
        else:
            out.append([])
    return out
"""


# -- unit: freeze sets / skips params ------------------------------------------


def test_freeze_sets_params_from_fit(monkeypatch):
    monkeypatch.setattr(sandbox, "strategy_has_fit", lambda code: True)
    monkeypatch.setattr(sandbox, "run_strategy_fit", lambda code, window, **kw: {"theta": 42})
    spec = _code_spec(code=FIT_COUNT)
    frozen = backtest.freeze_code_model(spec, _dataset())
    assert frozen["params"] == {"theta": 42}
    assert "params" not in spec  # original spec is not mutated


def test_freeze_is_noop_without_fit():
    spec = _code_spec(code=BUY_ALL)          # pure-rule code strategy, no fit()
    assert backtest.freeze_code_model(spec, _dataset()) is spec


def test_fit_failure_leaves_spec_unfrozen(monkeypatch):
    monkeypatch.setattr(sandbox, "strategy_has_fit", lambda code: True)

    def boom(code, window, **kw):
        raise sandbox.SandboxError("fit blew up")

    monkeypatch.setattr(sandbox, "run_strategy_fit", boom)
    spec = _code_spec(code=FIT_COUNT)
    assert "params" not in backtest.freeze_code_model(spec, _dataset())  # fails honestly, no crash


# -- the frozen model is part of the pre-registered identity -------------------


def test_frozen_params_are_part_of_experiment_identity():
    base = _code_spec(code=FIT_COUNT)
    a = Prereg(user_id=1, run_id=1, market="btc15m", spec=dict(base, params={"n": 10}),
               economic_rationale="m").hypothesis_hash()
    b = Prereg(user_id=1, run_id=1, market="btc15m", spec=dict(base, params={"n": 20}),
               economic_rationale="m").hypothesis_hash()
    assert a != b  # swapping the frozen model is a different experiment — it cannot be done post-hoc


# -- fold boundary at the sandbox call -----------------------------------------


def test_backtest_feeds_frozen_params_and_no_data_dir(monkeypatch):
    """The anti-leak boundary: every signals() run on a fold is handed the frozen params and
    data_dir=None, so it can read ONLY that fold's frames + the research-fit model — never another
    fold's data through a persisted dir."""
    captured = {}

    def fake(code, window, **kw):
        captured["data_dir"] = kw.get("data_dir", "ABSENT")
        captured["params"] = window.get("params")
        return [[] for _ in window["frames"]]

    monkeypatch.setattr(sandbox, "run_strategy_signals", fake)
    ds = _dataset()
    spec = dict(_code_spec(code=FIT_COUNT), params={"theta": 7})
    backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1)
    assert captured["data_dir"] is None          # no cross-run / cross-fold channel
    assert captured["params"] == {"theta": 7}    # the frozen model, not a refit


# -- the real sandbox: fit on research, NOT refit on validation ----------------


@needs_confiner
def test_model_frozen_on_research_is_not_refit_on_validation():
    research = _dataset(n=40)   # ~600 frames
    validation = _dataset(n=10)  # ~150 frames — a DIFFERENT window
    r, v = len(research.frames), len(validation.frames)
    assert r != v  # the discriminator: a refit would read v, the frozen model carries r

    spec = _code_spec(code=FIT_COUNT, max_positions=1)
    frozen = backtest.freeze_code_model(spec, research)
    assert frozen["params"]["n"] == r  # fit() saw ONLY the research window

    # Score the frozen model on the validation window. signals() emits a score == the frozen
    # research frame count; if it could refit it would emit v. The trade's edge carries that score.
    trades = backtest.simulate(frozen, validation, validation.start_ts, validation.end_ts + 1)
    assert trades, "the frozen params must flow into signals (no params -> KeyError -> no trades)"
    assert any(abs(t.edge - float(r)) < 1e-9 for t in trades)
    assert not any(abs(t.edge - float(v)) < 1e-9 for t in trades)
