"""Per-order latency + outcome instrumentation for the real-order path (Execution P2).

``timed_submitter`` wraps a kernel submitter (live or demo — the same wrapper, so the two
paths report identically) and measures every real exchange POST:

  * ``encode_sign_ms`` — local order-body build + RSA-PSS request signing (captured by the
    HTTP layer and threaded up on the result's ``timing`` dict).
  * ``roundtrip_ms``   — the request round-trip: network RTT to the exchange + exchange
    processing. These two cannot be split at the client without a server-provided
    processing-time, which Kalshi's create-order response does not return, and probing for one
    would add a call to the money path — so they are reported as one honest round-trip number.
  * ``total_ms``       — wall-clock across the whole submit (sign + round-trip + our parsing,
    and for a guard-blocked BUY, just the guard check). The authoritative end-to-end number.
  * ``outcome``        — filled | partial | unfilled | blocked | error, so error rate and
    fill rate are both derivable from the same rows.

Off the critical send path by construction: timing is read AFTER the submit returns (the order
is already acked), and recording is handed to a background daemon via a bounded queue — the send
path only does a non-blocking ``put`` and never touches the DB. Everything degrades silently: a
full queue drops the sample, a dead recorder or a failed insert is swallowed. Instrumentation
must never change execution, so this wrapper returns the inner result (and re-raises the inner
exception) completely unchanged.

Never records secrets: only mode/ticker/action/side/qty/fill and the timings — never the key,
the signature, the client_order_id or the raw order body.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

# ponytail: one unbounded-ish bounded queue + one daemon recorder. Orders are at most tens/min,
# so 4096 is effectively never full; if it ever is, we drop samples (observability), never trades.
_Q: "queue.Queue" = queue.Queue(maxsize=4096)
_RECORDER_STARTED = False
_LOCK = threading.Lock()


def _outcome(res, qty: int) -> str:
    """Classify one child-order POST from the submitter's returned dict (same shape the kernel's
    fill parser reads). Mirrors DummyExecutionKernel's fill logic so the metric agrees with what
    actually got booked."""
    if not isinstance(res, dict):
        return "error"
    if res.get("guard_blocked"):
        return "blocked"
    resp = res.get("resp") or {}
    try:
        fill = int(float(resp.get("fill_count") or 0))
    except (TypeError, ValueError):
        fill = 0
    if fill <= 0:
        return "unfilled"
    return "partial" if fill < int(qty) else "filled"


def _fill_qty(res) -> int:
    try:
        return int(float(((res or {}).get("resp") or {}).get("fill_count") or 0))
    except (TypeError, ValueError):
        return 0


def _recorder_loop() -> None:
    from data_pipeline.common import get_db_conn
    from app import repository as repo

    conn = None
    while True:
        row = _Q.get()
        try:
            if conn is None:
                conn = get_db_conn()
            with conn.cursor() as cur:
                repo.insert_order_latency(cur, **row)
        except Exception:
            conn = None  # drop the connection; next item reconnects. Never crash the recorder.
        finally:
            _Q.task_done()


def _ensure_recorder() -> None:
    global _RECORDER_STARTED
    if _RECORDER_STARTED:
        return
    with _LOCK:
        if _RECORDER_STARTED:
            return
        threading.Thread(target=_recorder_loop, name="order-latency-recorder", daemon=True).start()
        _RECORDER_STARTED = True


def _record(**row) -> None:
    """Hand a sample to the background recorder. Non-blocking; drops on a full queue. Never raises."""
    try:
        _ensure_recorder()
        _Q.put_nowait(row)
    except Exception:
        pass  # observability must never affect the order path


def timed_submitter(submit: Callable[..., dict], mode: str) -> Callable[..., dict]:
    """Wrap a submitter so each real exchange POST is measured and recorded (off the send path).
    Additive: the returned/raised value of the inner submitter is passed through untouched."""

    def timed(ticker: str, action: str, side: str, qty: int, price: float,
              client_order_id: Optional[str] = None) -> dict:
        t0 = time.perf_counter()
        try:
            res = submit(ticker, action, side, qty, price, client_order_id=client_order_id)
        except Exception:
            total_ms = (time.perf_counter() - t0) * 1000.0
            _record(mode=mode, ticker=ticker, action=action, side=side, qty=int(qty), fill_qty=0,
                    encode_sign_ms=None, roundtrip_ms=None, total_ms=total_ms,
                    http_status=None, outcome="error")
            raise
        total_ms = (time.perf_counter() - t0) * 1000.0
        timing = res.get("timing") if isinstance(res, dict) else None
        timing = timing if isinstance(timing, dict) else {}
        _record(mode=mode, ticker=ticker, action=action, side=side, qty=int(qty),
                fill_qty=_fill_qty(res), encode_sign_ms=timing.get("sign_ms"),
                roundtrip_ms=timing.get("net_ms"), total_ms=total_ms,
                http_status=timing.get("http_status"), outcome=_outcome(res, qty))
        return res

    return timed


if __name__ == "__main__":  # self-check: pass-through, outcome classification, error re-raise
    assert _outcome({"resp": {"fill_count": "5.00"}}, 5) == "filled"
    assert _outcome({"resp": {"fill_count": "2.00"}}, 5) == "partial"
    assert _outcome({"resp": {"fill_count": "0.00"}}, 5) == "unfilled"
    assert _outcome({"guard_blocked": True, "resp": {"fill_count": "0.00"}}, 5) == "blocked"
    assert _outcome("boom", 5) == "error"

    seen = {}

    def fake(ticker, action, side, qty, price, client_order_id=None):
        return {"resp": {"fill_count": "%d.00" % qty}, "timing": {"sign_ms": 1.0, "net_ms": 9.0, "http_status": 201}}

    def rec(**row):  # capture instead of DB
        seen.update(row)

    _orig = _record
    globals()["_record"] = rec
    try:
        out = timed_submitter(fake, "demo")("T", "buy", "yes", 3, 0.5)
        assert out["resp"]["fill_count"] == "3.00"  # result passed through unchanged
        assert seen["outcome"] == "filled" and seen["fill_qty"] == 3 and seen["roundtrip_ms"] == 9.0

        def boom(*a, **k):
            raise RuntimeError("exchange 500")

        seen.clear()
        try:
            timed_submitter(boom, "live")("T", "buy", "yes", 1, 0.5)
            assert False, "should re-raise"
        except RuntimeError:
            pass
        assert seen["outcome"] == "error" and seen["total_ms"] >= 0
    finally:
        globals()["_record"] = _orig
    print("latency self-check OK")
