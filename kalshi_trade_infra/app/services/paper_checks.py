"""Which paper -> live checks still refuse each paper strategy, as the Deploy board lists them.

agent.paper_evidence decides. The board, which polls every 10s, keeps its answer per user, strategy
and paper record (trades, events, hours), so a strategy is checked again only when its record moves
or the answer is FAILING_TTL old. That re-check is the gate's ~6 reads per strategy plus its seeded
bootstrap (memoized per process on the record), ~60 statements and ~600ms for a busy account's nine
paper strategies, and it ran on the request every five minutes.

- A record that moved (a trade closed) is a new key, read in the request, as before.
- Past FAILING_TTL (and under STALE_MAX) the kept answer is served while one background worker reads
  it again, once start() has been called: the web server calls it; tests and scripts read in the
  request, as before.
- The user's own deploy, pause, resume or stop drops the answers kept for that strategy (only its own
  paper evidence reads its deployments), an approved proposal or the kill switch every answer kept
  for them (forget), and a read already under way for them is not kept, so the board never shows a
  check from before the user's own change.

Display only: the live gate (agent._proven_on_paper) and Road to live call paper_evidence themselves,
and the answer here is that function's, unchanged.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from typing import Dict, List, Optional, Tuple

from app.research import agent

FAILING_TTL = 300.0  # seconds an answer is served as it is
STALE_MAX = 3600.0  # past FAILING_TTL and under this, served while the worker reads it again
MAX_ENTRIES = 5000  # kept answers across users; cleared whole past this
MAX_QUEUED = 256  # refreshes waiting for the worker; past this a lapsed answer is read in the request
WORKER_IDLE = 60.0  # seconds the worker waits for more before it exits (started again when needed)

KEPT: Dict[Tuple, Tuple[float, List[str]]] = {}  # (user, strategy, *record) -> (read at, failing)
_GEN: Dict[int, int] = {}  # user -> forget count: a read started before a forget is not kept
_PENDING: set = set()
_QUEUE: "queue.Queue[Tuple[Tuple, int]]" = queue.Queue(maxsize=MAX_QUEUED)
_LOCK = threading.Lock()
_BACKGROUND = {"on": False, "worker": None}


def failing_checks(cur, uid: int, sid: int) -> List[str]:
    """The checks refusing the strategy: "candidate" when the gatekeeper hasn't promoted it, then
    agent.paper_evidence's failing checks in gate order. Empty means its record clears every check."""
    ev = agent.paper_evidence(cur, uid, sid)
    return ([] if agent._is_deployment_candidate(cur, sid) else ["candidate"]) + [
        k for k, ok in ev["checks"].items() if not ok]


def failing(cur, uid: int, sid: int, record: Tuple) -> List[str]:
    """failing_checks for the strategy whose paper record is `record`, kept as the module says."""
    key = (int(uid), int(sid)) + tuple(record)
    hit = KEPT.get(key)
    if hit is not None:
        age = time.time() - hit[0]
        if age < FAILING_TTL or (age < STALE_MAX and _refresh_later(key)):
            return list(hit[1])
    gen = _GEN.get(key[0], 0)
    val = failing_checks(cur, uid, sid)
    _keep(key, val, gen)
    return list(val)


def forget(uid: int, strategy_id: Optional[int] = None) -> None:
    """Drop the answers kept for the user (only `strategy_id`'s when given), and any read of theirs
    already under way."""
    uid = int(uid)
    with _LOCK:
        _GEN[uid] = _GEN.get(uid, 0) + 1
        for key in [k for k in KEPT if k[0] == uid and (strategy_id is None or k[1] == int(strategy_id))]:
            del KEPT[key]


def start() -> None:
    """Serve a lapsed answer while a background worker reads it again (the web server calls this)."""
    _BACKGROUND["on"] = True


def _keep(key: Tuple, val: List[str], gen: int) -> None:
    with _LOCK:
        if _GEN.get(key[0], 0) != gen:
            return  # the user changed something since this read began
        if len(KEPT) >= MAX_ENTRIES:
            KEPT.clear()
        KEPT[key] = (time.time(), list(val))


def _refresh_later(key: Tuple) -> bool:
    """Queue the key for the worker. False when background reads are off or the queue is full."""
    if not _BACKGROUND["on"]:
        return False
    with _LOCK:
        if key in _PENDING:
            return True
        try:
            _QUEUE.put_nowait((key, _GEN.get(key[0], 0)))
        except queue.Full:
            return False
        _PENDING.add(key)
        worker: Optional[threading.Thread] = _BACKGROUND["worker"]
        if worker is None or not worker.is_alive():
            worker = threading.Thread(target=_work, name="paper-checks", daemon=True)
            _BACKGROUND["worker"] = worker
            worker.start()
    return True


def _work() -> None:
    """Read queued answers again, one at a time, on one connection held only while there is work."""
    from data_pipeline.common import get_db_conn

    conn = None
    while True:
        try:
            key, gen = _QUEUE.get(timeout=WORKER_IDLE if conn is None else 0.5)
        except queue.Empty:
            if conn is not None:
                _close(conn)
                conn = None
                continue
            with _LOCK:
                if _QUEUE.empty():
                    _BACKGROUND["worker"] = None
                    return
            continue
        try:
            if conn is None:
                conn = get_db_conn()
            _keep(key, failing_checks(conn.cursor(), key[0], key[1]), gen)
        except Exception:  # noqa: BLE001 - the kept answer stays; past STALE_MAX a request reads it
            traceback.print_exc()
            if conn is not None:
                _close(conn)
                conn = None
        finally:
            with _LOCK:
                _PENDING.discard(key)


def _close(conn) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
