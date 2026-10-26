"""The version of what the Research list shows, so its 5s poll can be answered "unchanged".

The list page polls GET /api/runs every 5s. A full answer reads the policy, the newest 50 sessions with
an out-of-credits probe into each finished run-until-stopped session's log, their spend summed from the
credit ledger, and the live counts: four statements, ~16ms of SQL and ~22KB of JSON on an account of
300 sessions, every poll, though most polls repeat the last answer. The page sends back the `v` of its
last full answer as `since`; while the version is the same the server answers {"v", "same": true} from
two statements (this version read and the live counts) and the page repaints from what it kept.

The version covers everything the list derives what it shows from:
  - each of the newest sessions' status, market, counts, run_forever, start and finish, and error
    (repo.list_runs_version; the prompt and direction are never rewritten). A new session is a new row.
    The out-of-credits step is logged before the run finishes, so it lands with a status change.
  - the user's newest credit-ledger id: a usage debit moves a session's spend.
  - the policy's time, scores and summary.
  - the live counts and the all-time totals, as the full answer reads them (the counts every poll,
    since a running session goes quiet by the clock; the totals from their 30s cache, as before).
A session's heartbeat is left out: it moves with every event and the list never shows it.

The version is read before the full answer's reads, so a write landing between them leaves the
answer under the older version and the next poll reads it again (as services.book_memo does).
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional


# What repo.list_runs_version reads, by name: a heartbeat, say, never moves the version.
FIELDS = ("id", "status", "market", "hypotheses_tried", "strategies_passed", "run_forever", "started_at",
          "finished_at", "err", "ledger_top", "policy")


def version(rows: List[Dict], counts: Dict, totals: Dict) -> Optional[str]:
    """A short hash of the list's inputs, or None for a user with no sessions (nothing to compare)."""
    if not rows:
        return None
    raw = json.dumps([[[r.get(k) for k in FIELDS] for r in rows], counts, totals],
                     default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
