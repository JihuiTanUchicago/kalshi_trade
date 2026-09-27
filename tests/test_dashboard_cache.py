"""The read cache must not outlive a write.

A toggle or a caps save committed to the database and then the dashboard's
very next read - including the refresh the button itself fires - served the
pre-write payload for up to 25 seconds, so a strategy that had just been
switched on kept reading "Off" and a save looked like it had done nothing.
"""
from data_pipeline.dashboard_server import (
    _METRICS_CACHE,
    _cached,
    invalidate_metrics_cache,
)


def _counter():
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return calls["n"]

    return calls, compute


def test_cached_serves_the_memo_within_its_ttl():
    invalidate_metrics_cache()
    calls, compute = _counter()
    assert _cached("k", 60, compute) == 1
    assert _cached("k", 60, compute) == 1
    assert calls["n"] == 1


def test_invalidate_forces_the_next_read_to_recompute():
    invalidate_metrics_cache()
    calls, compute = _counter()
    assert _cached("k", 60, compute) == 1
    invalidate_metrics_cache()
    assert _cached("k", 60, compute) == 2
    assert calls["n"] == 2


def test_invalidate_clears_every_key_not_just_one():
    invalidate_metrics_cache()
    _cached("sim", 60, lambda: "a")
    _cached("live", 60, lambda: "b")
    assert len(_METRICS_CACHE) == 2
    invalidate_metrics_cache()
    assert _METRICS_CACHE == {}


def test_every_post_route_invalidates():
    """The invalidation hangs off do_POST itself, so no future route can
    forget it. Guard the wiring, not each route."""
    import inspect

    from data_pipeline.dashboard_server import Handler

    src = inspect.getsource(Handler.do_POST)
    assert "self._handle_post()" in src
    assert "finally:" in src
    assert "invalidate_metrics_cache()" in src
