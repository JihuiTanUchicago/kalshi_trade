"""The web layer's per-user read caches that more than one route module writes or drops: the
track record and the Deploy board's roads to live, plus the one call that forgets a user's
cached reads after a change the web app made itself. Moved verbatim from app.server, which
re-imports every name. Callers mutate these dicts in place and never rebind them."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from app.services import paper_checks


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
