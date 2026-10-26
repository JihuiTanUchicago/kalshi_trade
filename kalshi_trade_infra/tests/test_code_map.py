"""Tests for the System-page code drill-down (app/web/code_map.py).

Pure static analysis - no DB, no server. Covers the AST extraction at all
three levels and, critically, the path whitelist that keeps a request from
reading outside the repo.
"""
import pytest

from app.web import code_map


# -- path whitelist (the security boundary) -----------------------------------


@pytest.mark.parametrize("bad", [
    "../../etc/passwd",            # traversal out of the repo
    "/etc/passwd",                 # absolute path
    "app/../../../etc/hosts",      # traversal that climbs past the root
    "README.md",                   # not a .py file
    "data_pipeline/common.pyc",    # not source
    "",                            # empty
    "scripts/deploy.py",           # a real .py but outside app/ + data_pipeline/
])
def test_resolve_module_rejects_paths_outside_the_source_tree(bad):
    with pytest.raises(code_map.CodeMapError):
        code_map.resolve_module(bad)


def test_resolve_module_accepts_a_real_source_file():
    path = code_map.resolve_module("data_pipeline/sim_repository.py")
    assert path.is_file() and path.name == "sim_repository.py"


# -- level 1: component -> modules ---------------------------------------------


def test_component_modules_lists_the_mapped_source():
    out = code_map.component_modules("sim_engine")
    paths = [m["path"] for m in out["modules"]]
    assert "data_pipeline/architecture/simulated_venue.py" in paths
    assert all(m["lines"] > 0 for m in out["modules"])


def test_engine_boxes_open_the_engine_that_trades_not_the_retired_ones():
    for node in ("sim_engine", "live_engine"):
        paths = [m["path"] for m in code_map.component_modules(node)["modules"]]
        assert paths[0] == "app/trading/engine.py"
        assert not any(p in paths for p in ("data_pipeline/live_trading_engine.py",
                                             "data_pipeline/simulated_trading_engine.py"))
    assert "data_pipeline/architecture/position_guard.py" in [
        m["path"] for m in code_map.component_modules("live_engine")["modules"]]


def test_unknown_component_is_rejected():
    with pytest.raises(code_map.CodeMapError):
        code_map.component_modules("not_a_node")


# -- level 2: module -> functions + classes ------------------------------------


def test_module_symbols_extracts_functions():
    out = code_map.module_symbols("data_pipeline/sim_repository.py")
    names = [f["name"] for f in out["functions"]]
    assert "load_feature_rows" in names
    sig = next(f["signature"] for f in out["functions"] if f["name"] == "load_feature_rows")
    assert sig.startswith("load_feature_rows(")


def test_module_symbols_extracts_classes_and_methods():
    out = code_map.module_symbols("app/web/http.py")
    classes = {c["name"]: c for c in out["classes"]}
    assert "Ctx" in classes
    assert any(m["qual"] == "Ctx.uid" for m in classes["Ctx"]["methods"])


# -- level 3: function -> source + call graph ----------------------------------


def test_function_detail_returns_source_and_callers():
    out = code_map.function_detail("data_pipeline/architecture/position_guard.py", "position_guarded_submitter")
    assert out["source"].startswith("def position_guarded_submitter(")
    assert out["lineno"] > 0
    # The live engine wraps its real-order submitter in the position guard - name-based call graph.
    callers = {(c["module"], c["qual"]) for c in out["callers"]}
    assert ("app/trading/engine.py", "live_kernel_factory") in callers


def test_function_detail_rejects_missing_function():
    with pytest.raises(code_map.CodeMapError):
        code_map.function_detail("data_pipeline/sim_repository.py", "no_such_function")


def test_call_graph_is_bidirectional_for_a_known_edge():
    """If A is a caller of B, then A's callees include B (same name-based edge)."""
    b = code_map.function_detail("app/trading/engine.py", "_execution_kernel")
    caller = next(c for c in b["callers"] if c["qual"] == "paper_kernel_factory")
    a = code_map.function_detail(caller["module"], caller["qual"])
    assert any(cal["name"] == "_execution_kernel" for cal in a["callees"])
