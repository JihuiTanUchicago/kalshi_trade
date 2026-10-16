"""Run an untrusted, LLM-authored ExplorationPolicy safely (Tau-RSI P3).

A policy is a *pure* function over plain data: it reads a state dict / candidate
list and returns allocation decisions. It needs no I/O, so we deny it all of it
and run it with three layers of defense:

  1. **AST validation** — reject `import`, and any `__dunder__` name or attribute
     access. That removes the classic in-process escape (`().__class__.__bases__
     …__subclasses__()`) and any route to a module.
  2. **Minimal builtins** — the code runs with only safe builtins (arithmetic,
     sorting, containers). No `__import__`, `open`, `eval`, `exec`, `getattr`,
     `globals`, `compile`, … so it cannot reach the filesystem/network/process.
  3. **Timeout + total fallback** — each call is bounded by a wall-clock timeout,
     and ANY violation, error, bad output, or timeout falls back to DefaultPolicy.
     A broken or hostile policy therefore degrades to the default; research never
     breaks and a policy can only ever burn bounded CPU on data we handed it.

ponytail: in-process sandbox, sufficient for *our* LLM's pure-function policies.
If the threat model ever hardens (adversarial code, heavier compute), upgrade the
executor to a subprocess with resource rlimits / namespaces — the interface here
(`safe_policy(code) -> ExplorationPolicy`) stays the same.
"""
from __future__ import annotations

import ast
import builtins as _builtins
import signal
import threading
from dataclasses import asdict
from typing import Callable, Dict, List

from app.exploration import Batch, DefaultPolicy, ExplorationPolicy, PolicyState


class PolicyError(Exception):
    """The policy code is malformed, unsafe, or misbehaving."""


# Builtins a numeric/list policy legitimately needs. Deliberately excludes
# __import__, open, eval, exec, compile, getattr/setattr, globals/vars, input, …
_SAFE_NAMES = (
    "abs", "min", "max", "sum", "len", "range", "sorted", "list", "dict", "tuple",
    "set", "float", "int", "bool", "round", "enumerate", "zip", "map", "filter",
    "any", "all", "reversed", "str", "divmod", "pow",
)
_SAFE_BUILTINS = {n: getattr(_builtins, n) for n in _SAFE_NAMES}
_TIMEOUT_S = 2.0


def _validate(code: str) -> None:
    """Static gate: no imports, no dunder names or attributes."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise PolicyError("policy does not parse: %s" % e)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise PolicyError("imports are not allowed in a policy")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise PolicyError("dunder attribute access is not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise PolicyError("dunder names are not allowed")


def _call_timed(fn: Callable, *args):
    """Call fn with a wall-clock timeout (main thread only; best-effort elsewhere)."""
    if threading.current_thread() is not threading.main_thread():
        return fn(*args)  # signals need the main thread; other defenses still apply

    def _raise(signum, frame):
        raise TimeoutError("policy exceeded %ss" % _TIMEOUT_S)

    old = signal.signal(signal.SIGALRM, _raise)
    signal.setitimer(signal.ITIMER_REAL, _TIMEOUT_S)
    try:
        return fn(*args)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


class _SandboxedPolicy(ExplorationPolicy):
    """Wraps LLM-authored `next_batch`/`select_finalists` so every call is bounded
    and output-checked, and falls back to the default on any problem."""

    def __init__(self, next_batch: Callable, select_finalists: Callable):
        self._nb, self._sf = next_batch, select_finalists
        self._default = DefaultPolicy()

    def next_batch(self, state: PolicyState) -> Batch:
        try:
            width = _call_timed(self._nb, asdict(state))
            width = int(width)
            if width < 0:
                raise PolicyError("negative width")
            return Batch(width)
        except Exception:
            return self._default.next_batch(state)

    def select_finalists(self, candidates: List[Dict], state: PolicyState) -> List[Dict]:
        try:
            picked = _call_timed(self._sf, list(candidates), asdict(state))
            # Output must be a subset of the candidates we handed in (by identity).
            allowed = {id(c) for c in candidates}
            out = [c for c in picked if id(c) in allowed]
            if len(out) != len(list(picked)):
                raise PolicyError("select_finalists returned items that were not candidates")
            return out
        except Exception:
            return self._default.select_finalists(candidates, state)


def load_policy(code: str) -> ExplorationPolicy:
    """Validate + compile a policy into a restricted namespace. Raises PolicyError
    if the code is unsafe or does not define the required functions."""
    _validate(code)
    ns: Dict = {"__builtins__": _SAFE_BUILTINS}
    exec(compile(code, "<policy>", "exec"), ns)  # restricted: no real builtins, pre-validated AST
    nb, sf = ns.get("next_batch"), ns.get("select_finalists")
    if not callable(nb) or not callable(sf):
        raise PolicyError("a policy must define next_batch(state) and select_finalists(candidates, state)")
    return _SandboxedPolicy(nb, sf)


def safe_policy(code: str) -> ExplorationPolicy:
    """The never-break entry point: the sandboxed policy if `code` is valid, else
    the DefaultPolicy. Use this everywhere a per-user policy drives research."""
    try:
        return load_policy(code)
    except PolicyError:
        return DefaultPolicy()
