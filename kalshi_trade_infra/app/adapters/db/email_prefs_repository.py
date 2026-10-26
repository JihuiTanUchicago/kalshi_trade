"""Who still wants Tau's optional email: the one switch (app_users.email_opt_out) that Settings and
the unsubscribe link both write, and the reads every optional send checks first.

Optional email is the community mail (new posts, replies, mentions) and the "ready for live trading"
notice. Live-money safety alerts (app/kalshi_perps_watch.py) never read this switch."""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional

from app.adapters.db.sql import now_utc


def set_email_opt_out(cur, user_id: int, opt_out: bool) -> bool:
    """Store the switch. True when the user exists and now holds this value. MySQL counts only
    changed rows, so a value that was already set is confirmed with a read, not reported as a miss
    (a second click on an unsubscribe link, or Off saved twice)."""
    cur.execute("UPDATE app_users SET email_opt_out=%s WHERE id=%s", (1 if opt_out else 0, user_id))
    if cur.rowcount == 1:
        return True
    cur.execute("SELECT id FROM app_users WHERE id=%s", (user_id,))
    return cur.fetchone() is not None


def optional_email_address(cur, user_id: int) -> Optional[str]:
    """The address an optional email may go to, read at send time, or None when the user has
    opted out or has no address."""
    cur.execute("SELECT email, email_opt_out FROM app_users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    if not row or row.get("email_opt_out") or not row.get("email"):
        return None
    return row["email"]


def community_email_recipients(cur, exclude_uid: int, cooldown_hours: int = 4) -> List[Dict]:
    """Users to email about new community activity: opted-in, with an email, not the author,
    and not emailed within the cooldown (so a burst of posts can't flood anyone)."""
    cutoff = now_utc() - timedelta(hours=cooldown_hours)
    cur.execute(
        """SELECT id, email, name FROM app_users
           WHERE id<>%s AND email IS NOT NULL AND email<>'' AND COALESCE(email_opt_out,0)=0
                 AND (last_community_email_at IS NULL OR last_community_email_at < %s)""",
        (exclude_uid, cutoff),
    )
    return cur.fetchall()


def mark_community_emailed(cur, user_ids: List[int]) -> None:
    if not user_ids:
        return
    placeholders = ",".join(["%s"] * len(user_ids))
    cur.execute("UPDATE app_users SET last_community_email_at=%s WHERE id IN (%s)" % ("%s", placeholders),
                [now_utc()] + list(user_ids))
