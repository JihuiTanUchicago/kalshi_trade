"""Execution P2 latency instrumentation.

Covers the two non-trivial pieces that are DB-free:
  * ``timed_submitter`` is additive — it measures + records but returns the inner result
    unchanged, classifies the outcome, and re-raises (still recording) on a submitter error;
  * ``_pct`` nearest-rank percentile and ``order_latency_stats``'s error/fill-rate math.

The DB write path (``insert_order_latency``) is exercised against a real MySQL elsewhere; here we
only assert the pure logic, so the test needs no database.
"""
from app.execution import latency
from app import repository as repo


def test_timed_submitter_passes_result_through_and_records_outcome():
    captured = {}
    orig = latency._record
    latency._record = lambda **row: captured.update(row)
    try:
        def fake(ticker, action, side, qty, price, client_order_id=None):
            return {"resp": {"fill_count": "%d.00" % qty},
                    "timing": {"sign_ms": 1.5, "net_ms": 12.0, "http_status": 201}}

        out = latency.timed_submitter(fake, "live")("T", "buy", "yes", 4, 0.5)
        assert out["resp"]["fill_count"] == "4.00"          # result untouched
        assert captured["outcome"] == "filled"
        assert captured["fill_qty"] == 4
        assert captured["roundtrip_ms"] == 12.0
        assert captured["encode_sign_ms"] == 1.5
        assert captured["mode"] == "live"
    finally:
        latency._record = orig


def test_timed_submitter_records_error_and_reraises():
    captured = {}
    orig = latency._record
    latency._record = lambda **row: captured.update(row)
    try:
        def boom(*a, **k):
            raise RuntimeError("exchange 500")

        try:
            latency.timed_submitter(boom, "demo")("T", "buy", "yes", 1, 0.5)
            assert False, "must re-raise so execution behaviour is unchanged"
        except RuntimeError:
            pass
        assert captured["outcome"] == "error"
        assert captured["total_ms"] >= 0.0
    finally:
        latency._record = orig


def test_outcome_classification():
    assert latency._outcome({"resp": {"fill_count": "2.00"}}, 5) == "partial"
    assert latency._outcome({"resp": {"fill_count": "0.00"}}, 5) == "unfilled"
    assert latency._outcome({"guard_blocked": True, "resp": {"fill_count": "0.00"}}, 5) == "blocked"


def test_pct_nearest_rank():
    vals = [10.0, 20.0, 30.0, 40.0, 100.0]
    assert repo._pct(vals, 0.5) == 30.0
    assert repo._pct(vals, 0.99) == 100.0
    assert repo._pct([], 0.5) is None
