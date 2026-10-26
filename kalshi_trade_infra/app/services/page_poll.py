"""The version of a polled page's answer, so a poll that would get back what the page already holds is told "same".

The dashboard polls /api/dashboard every 15s and the Deploy board /api/deployments every 10s. On a busy
account each answer is 50-60KB of JSON (every deployment's curve and backtest comparison, the open and
settled positions), sent, parsed and drawn again although most polls repeat the last one. The page sends
back the `v` of its last full answer; when the answer now is the same, the server says
{"v", "same": true} with the few figures that move without a write, and the page draws from what it kept.

The version is a hash of the answer itself, as it would be sent, less those moving figures. So it moves
with every figure the page shows, whatever moved it: a position opened, closed or partly sold, a
deployment paused or its stake changed, credits spent, a balance read from Kalshi, a UTC day rolling
over, a paper strategy's pace. There is no list of inputs to keep in step with the page, and nothing is
skipped to answer "same": every read runs (the heavy ones are kept until what they read changes, as
services.book_memo keeps the position sums).

What moves without a write rides every "same" answer, fresh:
  - each open position's mark (mark_price, mark_ts and the value and unrealized P&L made from them): the
    engine stamps every open position on each 15s tick, so a version over them would move every poll.
  - each deployment's unrealized P&L (the dashboard sums those marks per deployment).
  - the data ages (`freshness`: seconds since each feed and the engine last wrote), which move every second.
  - the start of the dashboard's "since your last visit" window (`since.at`), which is now less 24 hours
    on a first visit and never earlier than 7 days ago: what the window holds is in the version, its
    moving start is not.
The page puts them back over its kept answer by position and deployment id (pollAnswer in both bundles);
the kept answer with them put back is the full answer a fresh poll gets.
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, Optional

MARK_KEYS = ("mark_price", "mark", "value", "unrealized", "mark_ts")


def moving(out: Dict) -> Dict:
    """The figures of a full answer that move without a write: {"marks": {position id: its mark fields},
    "unrealized": {deployment id: its unrealized P&L}} and, when the answer has them, the data ages
    ("freshness") and the start of the since-your-last-visit window ("since_at")."""
    got = {"marks": {str(p["id"]): {k: p[k] for k in MARK_KEYS if k in p} for p in out.get("open_positions") or []},
           "unrealized": {str(d["id"]): d["unrealized_pnl"] for d in out.get("deployments") or [] if "unrealized_pnl" in d}}
    if "freshness" in out:
        got["freshness"] = out["freshness"]
    if isinstance(out.get("since"), dict) and "at" in out["since"]:
        got["since_at"] = out["since"]["at"]
    return got


def version(out: Dict) -> str:
    """A short hash of the answer less what `moving` carries."""
    rest = {k: v for k, v in out.items() if k not in ("freshness", "v")}
    if "open_positions" in rest:
        rest["open_positions"] = [{k: v for k, v in p.items() if k not in MARK_KEYS} for p in rest["open_positions"]]
    if "deployments" in rest:
        rest["deployments"] = [{k: v for k, v in d.items() if k != "unrealized_pnl"} for d in rest["deployments"]]
    if isinstance(rest.get("since"), dict):
        rest["since"] = {k: v for k, v in rest["since"].items() if k != "at"}
    raw = json.dumps(rest, default=str, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def answer(out: Dict, since: Optional[str]) -> Dict:
    """The full answer with its version, or {"v", "same": true, ...moving} when `since` (the version of
    the page's last full answer) is the version of this one."""
    v = version(out)
    if since and since == v:
        return {"v": v, "same": True, **moving(out)}
    out["v"] = v
    return out
