"""Community feed SQL: posts, images, reactions, likes, comments."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from app.adapters.db.sql import _json, _loads, now_utc
from app.adapters.db.strategy_repository import DEMO_DIRECTION, NO_EXPERIMENT_SQL


def store_image(cur, user_id: int, content_type: str, data: bytes) -> int:
    cur.execute(
        "INSERT INTO app_images (user_id, content_type, data, created_at) VALUES (%s,%s,%s,%s)",
        (user_id, content_type, data, now_utc()),
    )
    return cur.lastrowid


def get_image(cur, image_id: int) -> Optional[Dict]:
    cur.execute("SELECT content_type, data FROM app_images WHERE id=%s", (image_id,))
    return cur.fetchone()


def create_post(cur, user_id: int, body: str, kind: str, snapshot: Optional[Dict], image_id: Optional[int] = None) -> int:
    cur.execute(
        "INSERT INTO app_posts (user_id, body, kind, snapshot_json, image_id, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (user_id, body[:2000], kind, _json(snapshot), image_id, now_utc()),
    )
    return cur.lastrowid


def edit_post(cur, post_id: int, user_id: int, body: str) -> bool:
    """Edit own post body, stamping edited_at. Returns False if not the owner."""
    cur.execute(
        "UPDATE app_posts SET body=%s, edited_at=%s WHERE id=%s AND user_id=%s",
        (body[:2000], now_utc(), post_id, user_id),
    )
    return cur.rowcount == 1


def delete_post(cur, post_id: int, user_id: int) -> bool:
    """Remove the author's own post with its replies, likes, reactions and photo, so nothing it shared
    stays readable. False when the post isn't theirs or is already gone."""
    cur.execute("SELECT image_id FROM app_posts WHERE id=%s AND user_id=%s", (post_id, user_id))
    row = cur.fetchone()
    if not row:
        return False
    for table in ("app_post_comments", "app_post_likes", "app_post_reactions"):
        cur.execute("DELETE FROM %s WHERE post_id=%%s" % table, (post_id,))
    cur.execute("DELETE FROM app_posts WHERE id=%s AND user_id=%s", (post_id, user_id))
    if row.get("image_id"):
        cur.execute("DELETE FROM app_images WHERE id=%s AND user_id=%s", (row["image_id"], user_id))
    return True


# A shared strategy card whose strategy has no gatekeeper record (NO_EXPERIMENT_SQL), as a column of the feed's own
# read, not a read of its own: its author's strategy by the snapshot's id (primary key), the seeded example never.
# A card stored before the snapshot carried `no_gatekeeper_record` (#598) said "on unseen data" for a pass from the
# old loose backtest gate; the feed adds the flag to a "passed" card from this (community._snapshot_out), and to a
# "failed" one, a void the first version's simple backtest stored with no record (VOID_NO_RECORD_SQL). Display only.
POST_NO_RECORD_SQL = ("(p.kind='strategy' AND EXISTS (SELECT 1 FROM app_strategies s "
                      "WHERE s.id=CAST(JSON_UNQUOTE(JSON_EXTRACT(p.snapshot_json, '$.id')) AS UNSIGNED) "
                      "AND s.user_id=p.user_id AND s.direction<>%s AND " + NO_EXPERIMENT_SQL + ")) AS no_gatekeeper_record")


# The viewer's own strategy card whose strategy they have deleted since, as a column of the same read (its row by the
# snapshot's id, primary key): their card linked its page, which said "Not found". Only the author's card links, so
# only theirs is looked up. Display only (community._snapshot_out).
POST_GONE_SQL = ("(p.kind='strategy' AND p.user_id=%s AND NOT EXISTS (SELECT 1 FROM app_strategies g "
                 "WHERE g.id=CAST(JSON_UNQUOTE(JSON_EXTRACT(p.snapshot_json, '$.id')) AS UNSIGNED) "
                 "AND g.user_id=p.user_id)) AS strategy_gone")


def list_posts(cur, viewer_id: int, before_id: int = 0, limit: int = 30, mine_only: bool = False) -> List[Dict]:
    cur.execute(
        """SELECT p.id, p.body, p.kind, p.snapshot_json, p.image_id, p.edited_at, p.likes_count, p.comments_count, p.created_at,
                  u.name, u.username, u.picture_url, (p.user_id = %s) AS mine,
                  EXISTS(SELECT 1 FROM app_post_likes l WHERE l.post_id=p.id AND l.user_id=%s) AS liked,
                  """ + POST_NO_RECORD_SQL + """, """ + POST_GONE_SQL + """
           FROM app_posts p JOIN app_users u ON u.id=p.user_id
           WHERE (%s = 0 OR p.id < %s) AND (%s = 0 OR p.user_id = %s) ORDER BY p.id DESC LIMIT %s""",
        (viewer_id, viewer_id, DEMO_DIRECTION, viewer_id, before_id, before_id, 1 if mine_only else 0, viewer_id, limit),
    )
    rows = cur.fetchall()
    for r in rows:
        r["snapshot"] = _loads(r.pop("snapshot_json"))
        r["mine"] = bool(r["mine"]); r["liked"] = bool(r["liked"])
        r["no_gatekeeper_record"] = bool(r.get("no_gatekeeper_record"))
        r["strategy_gone"] = bool(r.get("strategy_gone"))
    by_post = reactions_for(cur, [r["id"] for r in rows], viewer_id)
    for r in rows:
        r["reactions"] = by_post.get(r["id"], [])
    return rows


def reactions_for(cur, post_ids: List[int], viewer_id: int) -> Dict[int, List[Dict]]:
    """Per-post emoji counts (+ whether the viewer added each, + up to 8 reactor
    names and @handles for the hover tooltip), most-used first. The names/handles ride
    along in the feed payload so the tooltip renders from already-loaded data with no
    per-hover round-trip. One grouped query for the whole page of posts (no N+1)."""
    if not post_ids:
        return {}
    marks = ",".join(["%s"] * len(post_ids))
    # SEPARATOR is the unit-separator char (never in a name); SUBSTRING_INDEX caps the list.
    cur.execute(
        "SELECT r.post_id, r.emoji, COUNT(*) AS n, MAX(r.user_id=%s) AS mine, "
        "SUBSTRING_INDEX(GROUP_CONCAT(u.name ORDER BY r.created_at SEPARATOR 0x1f), 0x1f, 8) AS names, "
        "SUBSTRING_INDEX(GROUP_CONCAT(COALESCE(u.username,'') ORDER BY r.created_at SEPARATOR 0x1f), 0x1f, 8) AS handles "
        "FROM app_post_reactions r JOIN app_users u ON u.id=r.user_id "
        "WHERE r.post_id IN (%s) GROUP BY r.post_id, r.emoji "
        "ORDER BY n DESC, r.emoji" % ("%s", marks),
        tuple([viewer_id] + list(post_ids)),
    )
    out: Dict[int, List[Dict]] = {}
    for r in cur.fetchall():
        names = [n for n in (r.get("names") or "").split("\x1f") if n]
        handles = [h for h in (r.get("handles") or "").split("\x1f") if h]
        out.setdefault(r["post_id"], []).append(
            {"emoji": r["emoji"], "count": int(r["n"]), "mine": bool(r["mine"]),
             "names": names, "handles": handles})
    return out


def toggle_reaction(cur, post_id: int, user_id: int, emoji: str) -> bool:
    """Add/remove one emoji reaction. Returns True if now reacted."""
    cur.execute("DELETE FROM app_post_reactions WHERE post_id=%s AND user_id=%s AND emoji=%s", (post_id, user_id, emoji))
    if cur.rowcount:
        return False
    cur.execute("INSERT INTO app_post_reactions (post_id, user_id, emoji, created_at) VALUES (%s,%s,%s,%s)",
                (post_id, user_id, emoji, now_utc()))
    return True


def toggle_like(cur, post_id: int, user_id: int) -> bool:
    """Returns True if now liked, False if unliked. Keeps likes_count in sync."""
    cur.execute("DELETE FROM app_post_likes WHERE post_id=%s AND user_id=%s", (post_id, user_id))
    if cur.rowcount:
        cur.execute("UPDATE app_posts SET likes_count=GREATEST(likes_count-1,0) WHERE id=%s", (post_id,))
        return False
    cur.execute("INSERT INTO app_post_likes (post_id, user_id, created_at) VALUES (%s,%s,%s)", (post_id, user_id, now_utc()))
    cur.execute("UPDATE app_posts SET likes_count=likes_count+1 WHERE id=%s", (post_id,))
    return True


def post_exists(cur, post_id: int) -> bool:
    cur.execute("SELECT 1 FROM app_posts WHERE id=%s", (post_id,))
    return cur.fetchone() is not None


def post_author(cur, post_id: int) -> Optional[Dict]:
    """The post's author (user_id, email, email_opt_out, name) plus a short body preview, for
    reply notifications."""
    cur.execute(
        """SELECT p.user_id, u.email, u.email_opt_out, u.name, LEFT(p.body, 140) AS preview
           FROM app_posts p JOIN app_users u ON u.id=p.user_id WHERE p.id=%s""",
        (post_id,),
    )
    return cur.fetchone()


def add_comment(cur, post_id: int, user_id: int, body: str) -> int:
    cur.execute(
        "INSERT INTO app_post_comments (post_id, user_id, body, created_at) VALUES (%s,%s,%s,%s)",
        (post_id, user_id, body[:1000], now_utc()),
    )
    cur.execute("UPDATE app_posts SET comments_count=comments_count+1 WHERE id=%s", (post_id,))
    return cur.lastrowid


def list_comments(cur, post_id: int, limit: int = 100) -> List[Dict]:
    cur.execute(
        """SELECT c.id, c.body, c.created_at, u.name, u.username, u.picture_url
           FROM app_post_comments c JOIN app_users u ON u.id=c.user_id
           WHERE c.post_id=%s ORDER BY c.id LIMIT %s""",
        (post_id, limit),
    )
    return cur.fetchall()


def recent_posts_count(cur, user_id: int, since: datetime) -> int:
    cur.execute("SELECT COUNT(*) AS n FROM app_posts WHERE user_id=%s AND created_at >= %s", (user_id, since))
    return int(cur.fetchone()["n"])
