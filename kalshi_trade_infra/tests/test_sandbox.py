"""The sandbox runs a well-formed policy, and makes every unsafe or broken one
degrade to the DefaultPolicy instead of breaking research or escaping."""
import pytest

from app import sandbox
from app.sandbox import PolicyError, load_policy, safe_policy
from app.exploration import DefaultPolicy, PolicyState


VALID = """
def next_batch(state):
    return min(4, state["budget"] - state["proposed"])

def select_finalists(candidates, state):
    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
    return [c for c in ranked[:3] if c["in_sample"]["pnl"] > 0]
"""


def _cands():
    return [{"score": 9.0, "in_sample": {"pnl": 90, "trades": 10}},
            {"score": 1.0, "in_sample": {"pnl": -5, "trades": 10}},
            {"score": 5.0, "in_sample": {"pnl": 40, "trades": 8}}]


def test_valid_policy_runs():
    p = load_policy(VALID)
    assert p.next_batch(PolicyState(proposed=0, budget=10, round=1)).width == 4
    picked = p.select_finalists(_cands(), PolicyState(0, 10, 1))
    assert [c["score"] for c in picked] == [9.0, 5.0]  # ranked, loser filtered out


@pytest.mark.parametrize("bad", [
    "import os\ndef next_batch(s): return 1\ndef select_finalists(c,s): return []",
    "def next_batch(s): return ().__class__\ndef select_finalists(c,s): return []",  # dunder attr
    "__import__('os')\ndef next_batch(s): return 1\ndef select_finalists(c,s): return []",  # dunder name
])
def test_unsafe_code_is_rejected(bad):
    with pytest.raises(PolicyError):
        load_policy(bad)
    assert isinstance(safe_policy(bad), DefaultPolicy)  # never-break entry point falls back


def test_banned_builtin_falls_back_at_runtime():
    # AST is clean (no import/dunder), but `open` isn't in the safe builtins ->
    # NameError at call time -> fall back to the default's width.
    code = ("def next_batch(state):\n    return len(open('/etc/passwd').read())\n"
            "def select_finalists(candidates, state):\n    return []")
    p = load_policy(code)
    assert p.next_batch(PolicyState(proposed=0, budget=10, round=1)).width == 4  # default, not a crash


def test_missing_functions_rejected():
    with pytest.raises(PolicyError):
        load_policy("def next_batch(s): return 1")  # no select_finalists


def test_bad_output_falls_back():
    code = ("def next_batch(state):\n    return -3\n"  # negative width -> invalid
            "def select_finalists(candidates, state):\n    return [{'score': 1}]")  # not a candidate
    p = load_policy(code)
    assert p.next_batch(PolicyState(proposed=0, budget=10, round=1)).width == 4  # default
    assert p.select_finalists(_cands(), PolicyState(0, 10, 1)) == DefaultPolicy().select_finalists(_cands(), PolicyState(0, 10, 1))


def test_runaway_loop_times_out_and_falls_back(monkeypatch):
    monkeypatch.setattr(sandbox, "_TIMEOUT_S", 0.3)
    code = ("def next_batch(state):\n    x = 0\n    while True:\n        x = x + 1\n"
            "def select_finalists(candidates, state):\n    return []")
    p = load_policy(code)
    assert p.next_batch(PolicyState(proposed=0, budget=10, round=1)).width == 4  # timed out -> default


@pytest.mark.parametrize("garbage", ['{"result": {"a": 1, ', "[1, 2]", ""])
def test_unreadable_strategy_output_is_a_sandbox_error(monkeypatch, garbage):
    # Prod 2026-10-24: a fit() whose out.json came back truncated raised a raw JSONDecodeError,
    # which escaped freeze_code_model's SandboxError handler and killed the whole research run.
    import os
    import types

    def fake_run(argv, cwd, **kw):
        with open(os.path.join(cwd, "out.json"), "w") as f:
            f.write(garbage)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(sandbox, "_confined_argv", lambda inner, scratch, data_dir=None: inner)
    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    code = "def fit(window):\n    return {}\n\ndef signals(window):\n    return []\n"
    with pytest.raises(sandbox.SandboxError, match="unreadable"):
        sandbox.run_strategy_fit(code, {"frames": []})
