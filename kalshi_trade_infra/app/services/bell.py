"""The bell's list, shaped for reading: notices about the same thing in a row become one line.

Five comments on one post, or a strategy paused three times while the user was away, used to fill
the list with near-identical lines and push everything else out of its 20 slots. Adjacent notices
of one kind about one page (same `kind` and `link`) collapse into the newest, which carries how
many more it stands for. Grouping is display-only: every row stays stored, read and counted as it
was, and the words of each notice are not changed (engine-written text included)."""
from typing import Dict, List

SHOWN = 20      # lines the bell lists
READ_ROWS = 100  # newest rows read to fill them; a fixed bound however many notices a user has


def grouped(rows: List[Dict], shown: int = SHOWN) -> List[Dict]:
    """`rows` newest first, as list_notifications returns them. Returns at most `shown` items
    ({id, kind, body, link, created_at, read, more}); `read` is False when any row it stands
    for is unread."""
    out: List[Dict] = []
    for r in rows:
        last = out[-1] if out else None
        if last is not None and r.get("link") and r.get("kind") == last["kind"] and r.get("link") == last["link"]:
            last["more"] += 1
            last["read"] = last["read"] and r.get("read_at") is not None
            continue
        if len(out) == shown:
            break
        out.append({"id": r["id"], "kind": r["kind"], "body": r["body"], "link": r.get("link"),
                    "created_at": r["created_at"], "read": r.get("read_at") is not None, "more": 0})
    return out
