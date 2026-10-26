"""Page error reports from browsers (app_client_errors): a bounded table and the admin readout's groups.

A row holds only what locates a bug (kind, message, script file and line, page path, theme, build)
and whether the visitor was signed in. No user id, address or request content: app/client_errors.py
cleans every field before it gets here.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from app.adapters.db.sql import now_utc

KEEP_ROWS = 5000      # newest rows kept; older ones are pruned on each insert
KEEP_DAYS = 7


def insert_client_error(cur, report: Dict[str, Any], signed_in: bool, keep_rows: int = KEEP_ROWS,
                        keep_days: int = KEEP_DAYS) -> int:
    """Store one cleaned report, then prune: rows older than keep_days, and every row more than
    keep_rows ids behind this one, so the table never holds more than keep_rows rows. Both deletes
    walk an index (the primary key, idx_ce_created). Returns the new row's id."""
    now = now_utc()
    cur.execute(
        """INSERT INTO app_client_errors (created_at, kind, message, src, line, col, path, theme, ver, signed_in)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (now, report["kind"], report["message"], report["src"], report["line"], report["col"],
         report["path"], report["theme"], report["ver"], 1 if signed_in else 0),
    )
    new_id = int(cur.lastrowid or 0)
    if new_id > keep_rows:
        cur.execute("DELETE FROM app_client_errors WHERE id <= %s", (new_id - keep_rows,))
    cur.execute("DELETE FROM app_client_errors WHERE created_at < %s", (now - timedelta(days=keep_days),))
    return new_id


def client_error_groups(cur, hours: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
    """The last `hours` of reports grouped by message and page (and kind), most recently seen first:
    how many, first and last seen, how many came from signed-out visitors, the themes and the builds
    (newest first) they came from, and the script position of the newest one."""
    cur.execute(
        """SELECT kind, message, path, COUNT(*) AS n, SUM(signed_in = 0) AS signed_out,
                  MIN(created_at) AS first_seen, MAX(created_at) AS last_seen,
                  GROUP_CONCAT(DISTINCT NULLIF(theme, '') ORDER BY theme SEPARATOR ',') AS themes,
                  GROUP_CONCAT(NULLIF(ver, '') ORDER BY id DESC SEPARATOR ',') AS versions,
                  SUBSTRING_INDEX(GROUP_CONCAT(CONCAT(src, ':', COALESCE(line, 0), ':', COALESCE(col, 0))
                                               ORDER BY id DESC SEPARATOR ','), ',', 1) AS at
           FROM app_client_errors WHERE created_at >= %s
           GROUP BY kind, message, path ORDER BY last_seen DESC, n DESC LIMIT %s""",
        (now_utc() - timedelta(hours=hours), int(limit)),
    )

    def text(v: Any) -> str:  # GROUP_CONCAT can come back as bytes
        return v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else (v or "")

    out = []
    for r in cur.fetchall():
        at = text(r.get("at"))
        out.append({"kind": r["kind"], "message": r["message"], "path": r["path"], "n": int(r["n"]),
                    "signed_out": int(r.get("signed_out") or 0),
                    "first_seen": r["first_seen"], "last_seen": r["last_seen"],
                    "themes": [t for t in text(r.get("themes")).split(",") if t],
                    # Newest build first, each once (the concat runs newest first, so a long one loses the oldest).
                    "versions": list(dict.fromkeys(v for v in text(r.get("versions")).split(",") if v)),
                    "at": "" if at.startswith(":") else at})
    return out
