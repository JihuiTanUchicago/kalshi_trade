"""Co-pilot chat history, autopilot action log reads, and agent proposals awaiting a decision."""
from __future__ import annotations

from typing import Dict, List, Optional

from app.adapters.db.sql import _json, _loads, now_utc


LAST_ACTION_WINDOW = 1000  # chat rows back that last_autopilot_action looks


def last_autopilot_action(cur, user_id: int) -> Optional[Dict]:
    """Most recent agent/system line about autopilot, for the floating status window.

    It looks through the user's newest LAST_ACTION_WINDOW chat rows, taken from idx_chat_user
    (user_id, id) alone. The status poll runs every 20s, and without the bound a user with no such
    line scanned back through their whole chat history each time (20k rows, ~30ms on a busy account).
    A line further back than that is not shown; the card then says when it last reviewed, and the
    panel's idle line says reviews run on a schedule.
    A research session the autopilot starts is a move too (agent.act's "Started a fresh research
    session on ..." line, which never names the autopilot): without it a busy autopilot's card read
    "Last move: Autopilot switched on" from days back while it started a session every hour."""
    cur.execute(
        """SELECT c.content, c.created_at FROM
             (SELECT id FROM app_chat_messages WHERE user_id=%s ORDER BY id DESC LIMIT %s) recent
           JOIN app_chat_messages c ON c.id=recent.id
           WHERE c.role='system'
                 AND (c.content LIKE '%%utopilot%%' OR c.content LIKE '%%LIVE%%' OR c.content LIKE '%%Kill%%'
                      OR c.content LIKE 'Started a fresh research session%%')
           ORDER BY c.id DESC LIMIT 1""",
        (user_id, LAST_ACTION_WINDOW),
    )
    r = cur.fetchone()
    return {"text": r["content"], "at": r["created_at"]} if r else None


def last_review_at(cur, user_id: int):
    """Timestamp of the most recent autopilot REVIEW run (whether or not it acted), for the panel's
    liveness readout. A quiet review takes no action and posts nothing, so without this a working
    autopilot looks dead between actions; this shows it is alive and on cadence."""
    cur.execute(
        "SELECT created_at FROM app_agent_runs WHERE user_id=%s AND kind='review' ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    r = cur.fetchone()
    return r["created_at"] if r else None


def active_agent_run(cur, user_id: int, kind: Optional[str] = None) -> Optional[Dict]:
    """The user's oldest queued or running chat/review run (only `kind` when given), with the times
    the panel needs to tell a run that is working from one that has waited or gone quiet too long:
    status, created_at and heartbeat_at. None when nothing is in flight."""
    kinds = "kind=%s" if kind else "kind IN ('chat','review')"
    cur.execute(
        "SELECT id, kind, status, created_at, heartbeat_at FROM app_agent_runs "
        "WHERE user_id=%s AND " + kinds + " AND status IN ('queued','running') ORDER BY id LIMIT 1",
        (user_id, kind) if kind else (user_id,),
    )
    return cur.fetchone()


def add_chat(cur, user_id: int, role: str, content: str, proposal_id: Optional[int] = None) -> int:
    cur.execute(
        "INSERT INTO app_chat_messages (user_id, role, content, proposal_id, created_at) VALUES (%s,%s,%s,%s,%s)",
        (user_id, role, content, proposal_id, now_utc()),
    )
    return cur.lastrowid


def chat_contains(cur, user_id: int, role: str, needle: str) -> bool:
    """True if the user already has a chat line of `role` containing `needle` (a one-time marker)."""
    cur.execute("SELECT 1 FROM app_chat_messages WHERE user_id=%s AND role=%s AND content LIKE %s LIMIT 1",
                (user_id, role, "%" + needle + "%"))
    return cur.fetchone() is not None


def recent_chat_same(cur, user_id: int, role: str, content: str, since) -> bool:
    """True if the user got this exact `role` line at or after `since` (repeat-notice suppression)."""
    cur.execute("SELECT 1 FROM app_chat_messages WHERE user_id=%s AND role=%s AND created_at>=%s AND content=%s LIMIT 1",
                (user_id, role, since, content))
    return cur.fetchone() is not None


def chat_messages(cur, user_id: int, after_id: int = 0, limit: int = 100) -> List[Dict]:
    cur.execute(
        """SELECT m.id, m.role, m.content, m.created_at, m.proposal_id,
                  p.kind AS proposal_kind, p.status AS proposal_status, p.deployment_id, p.strategy_id
           FROM app_chat_messages m LEFT JOIN app_proposals p ON p.id=m.proposal_id
           WHERE m.user_id=%s AND m.id>%s ORDER BY m.id DESC LIMIT %s""",
        (user_id, after_id, limit),
    )
    return list(reversed(cur.fetchall()))


def create_proposal(
    cur, user_id: int, kind: str, reason: str, deployment_id: Optional[int] = None,
    strategy_id: Optional[int] = None, status: str = "pending", payload: Optional[Dict] = None,
) -> int:
    cur.execute(
        """INSERT INTO app_proposals (user_id, kind, deployment_id, strategy_id, reason, status, payload, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (user_id, kind, deployment_id, strategy_id, reason, status, _json(payload), now_utc()),
    )
    return cur.lastrowid


def get_proposal(cur, user_id: int, proposal_id: int) -> Optional[Dict]:
    cur.execute("SELECT * FROM app_proposals WHERE id=%s AND user_id=%s", (proposal_id, user_id))
    p = cur.fetchone()
    if p is not None and "payload" in p:
        p["payload"] = _loads(p["payload"])
    return p


def decide_proposal(cur, proposal_id: int, status: str) -> bool:
    cur.execute(
        "UPDATE app_proposals SET status=%s, decided_at=%s WHERE id=%s AND status='pending'",
        (status, now_utc(), proposal_id),
    )
    return cur.rowcount == 1
