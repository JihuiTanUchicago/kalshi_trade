"""Static code map for the System page drill-down.

Turns a system-map node into the real source behind it, three levels deep:

    component  ->  the module file(s) that implement it
    module     ->  its top-level functions + classes (AST-derived)
    function   ->  its source text + callers/callees (a static call graph)

Everything here is read-only static analysis with the stdlib ``ast`` module -
no new dependencies, no DB. The only external input a request controls is a
module path, which is validated against a whitelist of this repo's own source
(``app/`` and ``data_pipeline/``) so a request can never read arbitrary files.

ponytail: the call graph is name-based - it links a call ``foo()`` to every
definition named ``foo`` across the mapped files, not the one scopes/imports
actually resolve to. That's plenty for "who touches this function" navigation;
upgrade to import-aware resolution only if the ambiguity ever bites.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Repo root = parent of the app/ package (…/kalshi_trade_infra).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ALLOWED_ROOTS = (REPO_ROOT / "app", REPO_ROOT / "data_pipeline")

# system-map node id -> the source module(s) that implement it. Mirrors the
# SYS_NODES / SYS_DESC topology in app/static/app.js. External nodes (kalshi,
# coinbase, bedrock, stripe) have no local source and are omitted.
COMPONENTS: Dict[str, List[str]] = {
    "forward": ["data_pipeline/forward_collector.py"],
    "cb_coll": ["data_pipeline/coinbase_collector.py"],
    "features": [
        "data_pipeline/feature_1m_collector.py",
        "data_pipeline/model_features_1m_builder.py",
        "data_pipeline/modeling_features.py",
    ],
    "db": ["data_pipeline/common.py", "app/schema.py", "data_pipeline/init_schema.py"],
    "web": ["app/server.py", "app/web/http.py", "app/web/settings.py", "app/web/views.py", "app/web/caches.py", "app/web/routes/auth.py", "app/web/routes/strategies.py", "app/web/routes/deployments.py", "app/web/routes/funds.py", "app/web/routes/admin.py", "app/web/routes/brokers.py", "app/web/routes/billing.py", "app/web/routes/community.py", "app/repository.py", "app/web/auth.py", "app/adapters/stripe/billing.py"],
    "agents": ["app/worker.py", "app/research/agent.py", "app/adapters/llm/llm.py"],
    "backtest": ["app/trading/backtest.py", "app/trading/engine.py", "app/trading/spec.py"],
    # Both engine boxes are app/trading/engine.py (recursive-engine), which runs paper, demo and live
    # deployments; the legacy data_pipeline engines are retired and no longer trade.
    "sim_engine": [
        "app/trading/engine.py",
        "data_pipeline/architecture/simulated_venue.py",
        "data_pipeline/architecture/execution_kernel.py",
    ],
    "live_engine": [
        "app/trading/engine.py",
        "data_pipeline/architecture/execution_kernel.py",
        "data_pipeline/architecture/position_guard.py",
        "app/execution/kill_switch.py",
    ],
}

# Every file the call graph spans: the union of the mapped modules. Bounded on
# purpose - this is a drill-down aid, not a whole-repo code-intelligence engine.
_GRAPH_FILES: Tuple[str, ...] = tuple(dict.fromkeys(p for ps in COMPONENTS.values() for p in ps))


class CodeMapError(Exception):
    """A bad request (unknown component, path outside the repo, missing symbol)."""


# -- path whitelist (the security boundary) -----------------------------------


def resolve_module(rel_path: str) -> Path:
    """Map a request-supplied module path to an on-disk file, or reject it.

    Accepts only a ``.py`` file that resolves inside ``app/`` or
    ``data_pipeline/``. ``Path.resolve()`` collapses ``..`` and symlinks first,
    so traversal (``../../etc/passwd``), absolute paths, and symlink escapes are
    all rejected before anything is read.
    """
    if not rel_path or not rel_path.endswith(".py"):
        raise CodeMapError("Not a Python module.")
    target = (REPO_ROOT / rel_path).resolve()
    if not any(target == r or r in target.parents for r in _ALLOWED_ROOTS):
        raise CodeMapError("Path is outside the allowed source tree.")
    if not target.is_file():
        raise CodeMapError("No such module.")
    return target


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _read(rel_path: str) -> Tuple[str, ast.Module]:
    path = resolve_module(rel_path)
    src = path.read_text(encoding="utf-8")
    return src, ast.parse(src)


# -- level 1: component -> modules ---------------------------------------------


def component_modules(node_id: str) -> Dict:
    paths = COMPONENTS.get(node_id)
    if paths is None:
        raise CodeMapError("That component has no source to show.")
    mods = []
    for p in paths:
        src, tree = _read(p)
        defs = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                   for n in tree.body)
        mods.append({"path": p, "name": p.rsplit("/", 1)[-1],
                     "lines": src.count("\n") + 1, "symbols": defs,
                     "doc": _summary(ast.get_docstring(tree))})
    return {"component": node_id, "modules": mods}


def _summary(doc: Optional[str]) -> str:
    if not doc:
        return ""
    line = doc.strip().splitlines()[0].strip()
    return line[:160]


# -- level 2: module -> functions + classes -----------------------------------


def _signature(node) -> str:
    args = [a.arg for a in node.args.posonlyargs + node.args.args]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwonlyargs:
        args.extend(a.arg for a in node.args.kwonlyargs)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    return "%s(%s)" % (node.name, ", ".join(args))


def module_symbols(rel_path: str) -> Dict:
    src, tree = _read(rel_path)
    functions, classes = [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({"name": node.name, "qual": node.name, "lineno": node.lineno,
                              "signature": _signature(node), "doc": _summary(ast.get_docstring(node))})
        elif isinstance(node, ast.ClassDef):
            methods = [{"name": b.name, "qual": "%s.%s" % (node.name, b.name),
                        "lineno": b.lineno, "signature": _signature(b),
                        "doc": _summary(ast.get_docstring(b))}
                       for b in node.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes.append({"name": node.name, "qual": node.name, "lineno": node.lineno,
                            "doc": _summary(ast.get_docstring(node)), "methods": methods})
    return {"module": rel_path, "functions": functions, "classes": classes}


# -- level 3: function -> source + call graph ----------------------------------

class _Def:
    """One function/method definition and the bare names it calls."""

    __slots__ = ("module", "name", "qual", "lineno", "calls")

    def __init__(self, module: str, name: str, qual: str, lineno: int, calls: set):
        self.module = module
        self.name = name
        self.qual = qual
        self.lineno = lineno
        self.calls = calls


def _called_names(node) -> set:
    """Leaf names of every call in a def's body (nested defs included - harmless)."""
    names: set = set()
    for child in node.body:
        for sub in ast.walk(child):
            if isinstance(sub, ast.Call):
                f = sub.func
                if isinstance(f, ast.Name):
                    names.add(f.id)
                elif isinstance(f, ast.Attribute):
                    names.add(f.attr)
    return names


def _collect_defs(rel_path: str) -> List[_Def]:
    _, tree = _read(rel_path)
    out: List[_Def] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(_Def(rel_path, node.name, node.name, node.lineno, _called_names(node)))
        elif isinstance(node, ast.ClassDef):
            for b in node.body:
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(_Def(rel_path, b.name, "%s.%s" % (node.name, b.name),
                                    b.lineno, _called_names(b)))
    return out


# ponytail: graph cached once per process; the mapped source doesn't change
# under a running server. Restart picks up edits - fine for a read-only page.
_GRAPH_CACHE: Optional[List[_Def]] = None


def _graph() -> List[_Def]:
    global _GRAPH_CACHE
    if _GRAPH_CACHE is None:
        defs: List[_Def] = []
        for p in _GRAPH_FILES:
            defs.extend(_collect_defs(p))
        _GRAPH_CACHE = defs
    return _GRAPH_CACHE


def _ref(d: _Def) -> Dict:
    return {"module": d.module, "name": d.name, "qual": d.qual, "lineno": d.lineno}


def function_detail(rel_path: str, func: str) -> Dict:
    """Source text of ``func`` in ``rel_path`` plus its callers and callees.

    ``func`` is a top-level function name or a ``Class.method`` qualname.
    """
    src, tree = _read(rel_path)
    target = _find_def_node(tree, func)
    if target is None:
        raise CodeMapError("No such function in that module.")
    source = ast.get_source_segment(src, target) or ""

    graph = _graph()
    leaf = func.rsplit(".", 1)[-1]
    # Make sure the target's own def (and its call set) is in the graph, even if
    # its module isn't a mapped one (callees can live anywhere whitelisted).
    me = next((d for d in graph if d.module == rel_path and d.qual == func), None)
    if me is None:
        me = next((d for d in _collect_defs(rel_path) if d.qual == func), None)
    my_calls = me.calls if me else set()

    defined = {}
    for d in graph:
        defined.setdefault(d.name, []).append(d)

    callees, seen = [], set()
    for name in sorted(my_calls):
        for d in defined.get(name, []):
            key = (d.module, d.qual)
            if key not in seen and not (d.module == rel_path and d.qual == func):
                seen.add(key)
                callees.append(_ref(d))

    callers, seen = [], set()
    for d in graph:
        if leaf in d.calls and not (d.module == rel_path and d.qual == func):
            key = (d.module, d.qual)
            if key not in seen:
                seen.add(key)
                callers.append(_ref(d))

    return {"module": rel_path, "name": target.name, "qual": func,
            "lineno": target.lineno, "source": source,
            "callers": callers, "callees": callees}


def _find_def_node(tree: ast.Module, func: str):
    cls, _, meth = func.partition(".")
    for node in tree.body:
        if meth:
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for b in node.body:
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name == meth:
                        return b
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            return node
    return None
