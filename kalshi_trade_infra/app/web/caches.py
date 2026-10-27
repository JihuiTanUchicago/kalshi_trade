"""The web layer's read caches that more than one route module writes or drops: the track record,
the Deploy board's roads to live, and the cross-user shared reads (served stale while one thread
refreshes), plus the one call that forgets a user's cached reads after a change the web app made
itself. Moved verbatim from app.server, which re-imports every name. Callers mutate these dicts in place and never rebind them."""
from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable, Dict, Optional, Tuple

from app.services import paper_checks
from data_pipeline.common import get_db_conn


# (built at, payload, trades read, the book's shape the dashboard had seen when it was built)
_TRACK_RECORD: Dict[int, Tuple[float, Dict, int, Optional[Tuple]]] = {}


def _forget_own_change(uid: int, strategy_id: Optional[int] = None) -> None:
    """Drop the user's cached reads after a change the web app made itself (a deploy, a pause, resume
    or stop, an approved proposal, the kill switch, a removed strategy): the track record, whose
    by-strategy rows carry each deployment's status, and the Deploy board's road to live and paper
    checks (services.paper_checks), so the board never shows a check from before the change. A change
    to one strategy's deployment passes `strategy_id`: only that strategy's paper evidence reads it."""
    _TRACK_RECORD.pop(uid, None)
    paper_checks.forget(uid, strategy_id)
    for key in [k for k in _ROADS if k[0] == uid]:
        _ROADS.pop(key, None)


_ROADS: Dict[Tuple, Tuple[float, Dict]] = {}


# Global (not per-user) reads that scan big history tables, shared by every request. Prod 2026-10-24:
# history_freshness's GROUP BY over hist_markets made /api/dashboard take 12-14s, and /api/me paid
# for series_with_candles on every page load. Each value is computed once, then served from memory
# while ONE background thread recomputes it on its own connection after the TTL.
_SHARED: Dict[str, Dict[str, Any]] = {}
_SHARED_LOCK = threading.Lock()


def _shared(key: str, ttl: float, fn: Callable[[Any], Any], cur) -> Any:
    now = time.time()
    with _SHARED_LOCK:
        ent = _SHARED.setdefault(key, {"at": 0.0, "busy": False})
        cold = "val" not in ent
        stale = not cold and now - ent["at"] >= ttl and not ent["busy"]
        if stale:
            ent["busy"] = True
    if cold:
        val = fn(cur)
        with _SHARED_LOCK:
            ent.update(val=val, at=time.time())
        return val
    if stale:
        threading.Thread(target=_refresh_shared, args=(ent, fn), daemon=True).start()
    return ent["val"]


def _shared_kept(key: str) -> bool:
    """Whether _shared holds a value for `key` (fresh or due a refresh), so a read of it answers from
    memory instead of working it out on the caller's thread."""
    with _SHARED_LOCK:
        return "val" in _SHARED.get(key, {})


def _refresh_shared(ent: Dict[str, Any], fn: Callable[[Any], Any]) -> None:
    conn = None
    try:
        conn = get_db_conn()
        val = fn(conn.cursor())
        with _SHARED_LOCK:
            ent.update(val=val, at=time.time())
    except Exception:
        traceback.print_exc()  # keep serving the last good value; the next request retries
    finally:
        ent["busy"] = False
        if conn is not None:
            conn.close()
