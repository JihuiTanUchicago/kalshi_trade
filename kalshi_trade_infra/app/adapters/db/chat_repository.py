"""Co-pilot chat history, autopilot action log reads, and agent proposals awaiting a decision."""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from app.adapters.db.sql import _json, _loads, now_utc


LAST_ACTION_WINDOW = 1000  # chat rows back that last_autopilot_action looks
# The engine's own pause line (trading/engine.py: the loss guard and the drawdown force-close). Its text
# is the engine's and stays as written; the panel says it in words on the way out.
AUTO_PAUSED = re.compile(r"Paused deployment #(\d+) automatically\b")


def last_autopilot_action(cur, user_id: int) -> Optional[Dict]:
    """Most recent agent/system line about autopilot, for the floating status window.

    It looks through the user's newest LAST_ACTION_WINDOW chat rows, taken from idx_chat_user
    (user_id, id) alone. The status poll runs every 20s, and without the bound a user with no such
    line scanned back through their whole chat history each time (20k rows, ~30ms on a busy account).
    A line further back than that is not shown; the card then says when it last reviewed, and the
    panel's idle line says reviews run on a schedule.
    A research session the autopilot starts is a move too (agent.act's "Started a fresh research
    session on ..." line, which never names the autopilot): without it a busy autopilot's card read
    "Last move: Autopilot switched on" from days back while it started a session every hour.
    The engine's loss-guard and drawdown pauses are moves too ("Paused deployment #12 automatically.
    ...", which names neither the autopilot nor the strategy): without them the card's last move was an
    older deploy while the newest thing that happened was a pause. That line comes with the paused
    deployment as "deployment" ({"id", "title", "mode"}; title and mode None once it is gone), so the
    panel can say it by the strategy's name (customer_text.auto_pause_line)."""
    cur.execute(
        """SELECT c.content, c.created_at FROM
             (SELECT id FROM app_chat_messages WHERE user_id=%s ORDER BY id DESC LIMIT %s) recent
           JOIN app_chat_messages c ON c.id=recent.id
           WHERE c.role='system'
                 AND (c.content LIKE '%%utopilot%%' OR c.content LIKE '%%LIVE%%' OR c.content LIKE '%%Kill%%'
                      OR c.content LIKE 'Started a fresh research session%%'
                      OR c.content LIKE 'Paused deployment #%% automatically%%')
           ORDER BY c.id DESC LIMIT 1""",
        (user_id, LAST_ACTION_WINDOW),
    )
    r = cur.fetchone()
    if not r:
        return None
    out = {"text": r["content"], "at": r["created_at"]}
    m = AUTO_PAUSED.match(r["content"] or "")
    if m:
        cur.execute("SELECT s.title, d.mode FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id "
                    "WHERE d.id=%s AND d.user_id=%s", (int(m.group(1)), user_id))
        d = cur.fetchone() or {}
        out["deployment"] = {"id": int(m.group(1)), "title": d.get("title"), "mode": d.get("mode")}
    return out


def deployment_names(cur, user_id: int, deployment_ids: List[int]) -> Dict[int, Dict]:
    """{deployment id: {"title", "mode"}} for the user's own deployments among ``deployment_ids``, for
    the chat feed's automatic-pause lines (customer_text.chat_rows). Another user's id, or one that is
    gone, is left out. One read by primary key."""
    ids = sorted({int(i) for i in deployment_ids})
    if not ids:
        return {}
    cur.execute("SELECT d.id, s.title, d.mode FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id "
                "WHERE d.user_id=%s AND d.id IN (" + ",".join(["%s"] * len(ids)) + ")", (user_id, *ids))
    return {int(r["id"]): {"title": r["title"], "mode": r["mode"]} for r in cur.fetchall()}


def last_chat_turn_cost(cur, user_id: int) -> Optional[float]:
    """What the user's newest finished chat turn (one message answered, or one that failed) debited
    from their credits, in dollars; None when they have no finished turn. A turn that debited nothing
    reads 0. Read through idx_runs_user (user_id, kind, ...) and the ledger's run index."""
    cur.execute(
        "SELECT r.id, (SELECT COALESCE(-SUM(l.amount_usd), 0) FROM app_credit_ledger l "
        "WHERE l.run_id = r.id AND l.kind='usage' AND l.user_id=%s) AS cost "
        "FROM app_agent_runs r WHERE r.user_id=%s AND r.kind='chat' AND r.status IN ('succeeded','failed') "
        "ORDER BY r.id DESC LIMIT 1",
        (user_id, user_id),
    )
    r = cur.fetchone()
    return float(r["cost"] or 0) if r else None


# When the newest review ran: its start, or the time it was queued while it hasn't started yet.
REVIEW_AT_SQL = ("SELECT COALESCE(started_at, created_at) AS at FROM app_agent_runs "
                 "WHERE user_id=%s AND kind='review' ORDER BY id DESC LIMIT 1")


def last_review_at(cur, user_id: int):
    """When the most recent autopilot REVIEW run ran (whether or not it acted), for the panel's
    liveness readout. A quiet review takes no action and posts nothing, so without this a working
    autopilot looks dead between actions; this shows it is alive and on cadence. It is the review's
    start (started_at): a review that waited 40 minutes for a worker read "Last check-in 40m ago" the
    moment it ran. Until the newest review starts, the time it was queued stands in."""
    cur.execute(REVIEW_AT_SQL, (user_id,))
    r = cur.fetchone()
    return r["at"] if r else None


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
    """The newest `limit` lines after `after_id`, oldest first. A proposal's line carries the book
    (deployment_mode: paper, demo or live) of the deployment it would change, so the panel can say
    whether approving it touches real money before anyone presses Approve."""
    cur.execute(
        """SELECT m.id, m.role, m.content, m.created_at, m.proposal_id,
                  p.kind AS proposal_kind, p.status AS proposal_status, p.deployment_id, p.strategy_id,
                  d.mode AS deployment_mode
           FROM app_chat_messages m LEFT JOIN app_proposals p ON p.id=m.proposal_id
                LEFT JOIN app_deployments d ON d.id=p.deployment_id
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
