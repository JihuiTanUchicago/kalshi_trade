"""Community routes: the feed, posts, comments, reactions, mentions and post images. Moved verbatim
from app.server, which re-imports every name for its route table."""
from __future__ import annotations

import threading
from datetime import timedelta
from typing import Dict, Iterable, Optional, Set

from app import repository as repo
from app.adapters.ses import notify
from app.services import customer_text
from app.web.http import ApiError, Ctx, _int_param
from app.web.routes.strategies import _later_verdicts
from data_pipeline.common import get_db_conn
from trading_core.domain.money import cents


MAX_POSTS_PER_HOUR = 30


def _post_snapshot(cur, user_id: int, kind: str, ref_id: int) -> Optional[Dict]:
    """Build a self-contained, denormalized snapshot from the user's OWN strategy
    or deployment, so a post never exposes another user's data or a live spec."""
    if kind == "strategy":
        strat = repo.get_strategy(cur, user_id, ref_id)
        if strat is None:
            raise ApiError(404, "That strategy isn’t yours or doesn’t exist.")
        oos = (strat.get("result") or {}).get("out_of_sample") or {}
        # A later check its status leaves out (Missed final test, Held back) rides as `verdict`, the stamp its
        # page and list show: the card said Passed for a strategy its own page didn't.
        # A pass with no gatekeeper record (the old loose backtest gate) gets `no_gatekeeper_record`, from the same
        # read: its out_of_sample is the later-period slice that picked it, not held out, as its page and the
        # Strategies list say (#590); the card said "on unseen data". The seeded example is never judged.
        recorded: set = set()
        later = _later_verdicts(cur, user_id, [strat], recorded=recorded).get(strat["id"])
        unrecorded = (strat["status"] == "passed" and strat.get("direction") != repo.DEMO_DIRECTION
                      and strat["id"] not in recorded)
        # The backtest's held-out window: `days` is its span, so the feed can say over what.
        return {"kind": "strategy", "id": strat["id"], "title": strat["title"], "market": strat["market"],
                "status": strat["status"], **({"verdict": later[0]} if later else {}),
                **({"no_gatekeeper_record": True} if unrecorded else {}), "pnl": oos.get("pnl"),
                "trades": oos.get("trades"), "win_rate": oos.get("win_rate"), "days": oos.get("days")}
    if kind == "deployment":
        dep = repo.get_deployment(cur, user_id, ref_id)
        if dep is None:
            raise ApiError(404, "That deployment isn’t yours or doesn’t exist.")
        since = dep.get("created_at")
        return {"kind": "deployment", "id": dep["id"], "title": dep["title"], "market": dep["market"],
                "mode": dep["mode"], "realized_pnl": cents(dep["realized_pnl"]), "closed_trades": dep["closed_trades"],
                "since": since.strftime("%Y-%m-%dT%H:%M:%SZ") if since else None}
    if kind == "pnl":
        # Each book's all-time realized P&L with its closed-trade count, never added together.
        paper = repo.realized_pnl(cur, user_id, "paper")
        live = repo.realized_pnl(cur, user_id, "live")
        counts = repo.closed_trade_counts(cur, user_id)
        return {"kind": "pnl", "paper_pnl": cents(paper), "live_pnl": cents(live),
                "paper_trades": counts.get("paper", 0), "live_trades": counts.get("live", 0)}
    return None


# What a shared card shows every reader, by kind: the figures the feed prints, never a spec, rules, the
# run behind it, or a credit balance. A stored snapshot holds no more today; this keeps it so.
SNAPSHOT_FIELDS = {
    "strategy": ("kind", "title", "market", "status", "verdict", "no_gatekeeper_record", "pnl", "trades", "win_rate", "days"),
    "deployment": ("kind", "title", "market", "mode", "realized_pnl", "closed_trades", "since"),
    "pnl": ("kind", "paper_pnl", "live_pnl", "paper_trades", "live_trades"),
}


def _snapshot_out(snap, mine: bool, unrecorded: bool = False) -> Optional[Dict]:
    """A post's shared card as one reader sees it. The author's row id goes only to the author, whose
    card links their own strategy page; anyone else's card is no link, so it needs none. A title reads
    as the app shows a person's text (no address, no internal model id). `unrecorded` (the feed read's
    no_gatekeeper_record, POST_NO_RECORD_SQL) flags a "passed" card stored before its snapshot carried
    the flag, so it says later-period as its page does, not "on unseen data"."""
    if not isinstance(snap, dict) or snap.get("kind") not in SNAPSHOT_FIELDS:
        return None
    out = {k: snap[k] for k in SNAPSHOT_FIELDS[snap["kind"]] if k in snap}
    if unrecorded and out["kind"] == "strategy" and out.get("status") == "passed" and not out.get("verdict"):
        out["no_gatekeeper_record"] = True
    if out.get("title"):
        out["title"] = customer_text.clean(out["title"], "A strategy")
    if mine and snap.get("id") is not None:
        out["id"] = snap["id"]
    return out


def _post_out(p: Dict) -> Dict:
    return {
        "id": p["id"], "body": p["body"], "kind": p["kind"], "snapshot": _snapshot_out(p.get("snapshot"), bool(p.get("mine")), bool(p.get("no_gatekeeper_record"))),
        "likes": p["likes_count"], "comments": p["comments_count"], "created_at": p["created_at"],
        "author": customer_text.display_name(p.get("name"), "Trader"), "username": p.get("username"), "picture": p.get("picture_url"),
        "mine": p.get("mine", False), "liked": p.get("liked", False),
        "reactions": p.get("reactions", []),
        "image": ("/api/community/image/%d" % p["image_id"]) if p.get("image_id") else None,
        "edited": bool(p.get("edited_at")),
    }


def community(ctx: Ctx):
    before = int(ctx.query.get("before") or 0)
    mine_only = str(ctx.query.get("mine") or "") in ("1", "true")
    return {"posts": [_post_out(p) for p in repo.list_posts(ctx.cur, ctx.uid, before, mine_only=mine_only)]}


IMAGE_MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}
MAX_IMAGE_BYTES = 3 * 1024 * 1024


def _decode_image(data_url: str):
    import base64 as _b64
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        raw = _b64.b64decode(data_url, validate=True)
    except Exception:
        raise ApiError(400, "That image couldn’t be read.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ApiError(413, "Images must be under 3 MB.")
    ctype = next((t for magic, t in IMAGE_MAGIC.items() if raw.startswith(magic)), None)
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        ctype = "image/webp"
    if not ctype:
        raise ApiError(400, "Only PNG, JPEG, WebP, or GIF images are allowed.")
    return ctype, raw


def post_link(pid: int) -> str:
    """Where a notice about a post opens: the feed, scrolled to that post (or saying it's gone)."""
    return "/community#post-%d" % pid


def _notify_mentions(cur, author_uid: int, author_name: str, body: str, link: str, told: int = 0,
                     where: str = "a post") -> Set[int]:
    """Notify every @-mentioned user (in-app + email), skipping the author, and `told`: the post's
    author, whom a reply already notifies (one reply, one line in their bell). `where` is what the
    mention is in ("a post" or "a reply"). Returns who was emailed, so a new post's digest doesn't
    email them about it again. Best-effort."""
    emailed: Set[int] = set()
    handles = {h.lower() for h in repo.MENTION_RE.findall(body or "")}
    if not handles:
        return emailed
    for u in repo.users_by_usernames(cur, list(handles)):
        if u["id"] in (author_uid, told):
            continue
        try:
            repo.add_notification(cur, u["id"], "mention", "%s mentioned you in %s." % (author_name, where), link)
        except Exception as e:
            print("[mention] in-app notice failed: %r" % e, flush=True)
        if u.get("email") and not u.get("email_opt_out"):  # optional email: Settings can turn it off
            try:
                notify.mention_notice(u["email"], u.get("name"), author_name, body, notify.page_url(link),
                                      notify.unsubscribe_url(u["id"]))
                emailed.add(u["id"])
            except Exception as e:
                print("[mention] email failed: %r" % e, flush=True)
    return emailed


def mention_candidates(ctx: Ctx):
    q = (ctx.query.get("q") or "").strip()[:32]
    return {"users": [{"username": u["username"], "name": customer_text.display_name(u["name"], u["username"])}
                      for u in repo.mention_candidates(ctx.cur, q)]}


def create_community_post(ctx: Ctx):
    body = str(ctx.body.get("body") or "").strip()
    kind = ctx.body.get("kind") or "note"
    image = ctx.body.get("image")
    if kind not in ("note", "strategy", "deployment", "pnl"):
        raise ApiError(400, "Unknown post type.")
    if not body and kind == "note" and not image:
        raise ApiError(400, "Write something or attach a photo first.")
    if len(body) > 2000:
        raise ApiError(400, "Keep posts under 2,000 characters.")
    cur = ctx.cur
    if repo.recent_posts_count(cur, ctx.uid, repo.now_utc() - timedelta(hours=1)) >= MAX_POSTS_PER_HOUR:
        raise ApiError(429, "You’ve posted a lot this hour. Give it a minute.")
    image_id = None
    if image:
        ctype, raw = _decode_image(str(image))
        image_id = repo.store_image(cur, ctx.uid, ctype, raw)
    snapshot = _post_snapshot(cur, ctx.uid, kind, int(ctx.body.get("ref_id") or 0)) if kind != "note" else None
    pid = repo.create_post(cur, ctx.uid, body or _default_share_text(kind, snapshot), kind, snapshot, image_id)
    author = customer_text.display_name((repo.get_user(cur, ctx.uid) or {}).get("name"), "A trader")
    told = _notify_mentions(cur, ctx.uid, author, body, post_link(pid))
    _email_community_post_async(ctx.uid, author, body or _default_share_text(kind, snapshot), pid, told)
    return {"id": pid}


def _email_community_post_async(author_uid: int, author: str, preview: str, pid: int,
                                skip: Iterable[int] = ()) -> None:
    """Email opted-in users about a new post, with a link to it, off the request thread so posting
    stays snappy. `skip`: users its mention email already told about this post (one email per post).
    Cooldown + opt-out are enforced per recipient; SES sandbox silently no-ops unverified sends."""
    skip = set(skip)
    def run():
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            recipients = [r for r in repo.community_email_recipients(cur, author_uid) if r["id"] not in skip]
            for r in recipients:
                notify.community_post_notice(r["email"], r.get("name"), author, preview, notify.unsubscribe_url(r["id"]),
                                             notify.page_url(post_link(pid)))
            repo.mark_community_emailed(cur, [r["id"] for r in recipients])  # cooldown applies even to sandbox-skipped
        except Exception as e:
            print("[community] post email dispatch failed: %r" % e, flush=True)
    threading.Thread(target=run, daemon=True).start()


def edit_community_post(ctx: Ctx):
    body = str(ctx.body.get("body") or "").strip()
    if not body:
        raise ApiError(400, "A post can’t be empty.")
    if len(body) > 2000:
        raise ApiError(400, "Keep posts under 2,000 characters.")
    if not repo.edit_post(ctx.cur, _int_param(ctx), ctx.uid, body):
        raise ApiError(403, "You can only edit your own posts.")
    return {"ok": True}


def delete_community_post(ctx: Ctx):
    """The author takes their post down, with its replies and photo. A notice that still links it
    opens the feed saying the post is gone."""
    if not repo.delete_post(ctx.cur, _int_param(ctx), ctx.uid):
        raise ApiError(403, "You can only delete your own posts.")
    return {"ok": True}


def community_image(ctx: Ctx):
    img = repo.get_image(ctx.cur, _int_param(ctx))
    if not img:
        raise ApiError(404, "Image not found.")
    return ("image", img["content_type"], bytes(img["data"]))


def _default_share_text(kind: str, snap: Optional[Dict]) -> str:
    if kind == "pnl" and snap:
        return "Sharing my results so far."
    if snap:
        return "Sharing a %s." % kind
    return ""


def like_post(ctx: Ctx):
    pid = _int_param(ctx)
    if not repo.post_exists(ctx.cur, pid):
        raise ApiError(404, "No such post.")
    return {"liked": repo.toggle_like(ctx.cur, pid, ctx.uid)}


# A fixed emoji palette — reactions are restricted to these so stored values stay
# small and safe (no arbitrary input).
REACTION_EMOJI = ["tau", "👍", "❤️", "🔥", "🚀", "😂", "🎉", "💯", "👀", "🤔", "😮",
                  "😢", "🙌", "🧠", "📈", "📉", "💸", "✅", "❌", "🐂", "🐻",
                  "🐐", "🦍", "🐳", "💎", "🤡", "💀", "🫡", "🌙"]


def react_post(ctx: Ctx):
    pid = _int_param(ctx)
    emoji = str(ctx.body.get("emoji") or "")
    if emoji not in REACTION_EMOJI:
        raise ApiError(400, "Unsupported reaction.")
    if not repo.post_exists(ctx.cur, pid):
        raise ApiError(404, "No such post.")
    repo.toggle_reaction(ctx.cur, pid, ctx.uid, emoji)
    return {"reactions": repo.reactions_for(ctx.cur, [pid], ctx.uid).get(pid, [])}


def post_comments(ctx: Ctx):
    pid = _int_param(ctx)
    return {"comments": [{"body": c["body"], "author": customer_text.display_name(c["name"], "Trader"), "username": c.get("username"), "picture": c["picture_url"], "created_at": c["created_at"]} for c in repo.list_comments(ctx.cur, pid)]}


def create_comment(ctx: Ctx):
    pid = _int_param(ctx)
    body = str(ctx.body.get("body") or "").strip()
    if not body:
        raise ApiError(400, "Write a comment first.")
    if len(body) > 1000:
        raise ApiError(400, "Keep comments under 1,000 characters.")
    author = repo.post_author(ctx.cur, pid)
    if not author:
        raise ApiError(404, "No such post.")
    repo.add_comment(ctx.cur, pid, ctx.uid, body)
    commenter = customer_text.display_name((repo.get_user(ctx.cur, ctx.uid) or {}).get("name"), "Someone")
    _notify_mentions(ctx.cur, ctx.uid, commenter, body, post_link(pid), told=author["user_id"], where="a reply")
    if author["user_id"] != ctx.uid:  # don't notify yourself
        try:
            repo.add_notification(ctx.cur, author["user_id"], "comment",
                                  "%s replied to your post." % commenter, post_link(pid))
        except Exception as e:
            print("[community] in-app notice failed for post %s: %r" % (pid, e), flush=True)
    # Don't email yourself, or anyone who turned optional email off in Settings.
    if author["user_id"] != ctx.uid and author.get("email") and not author.get("email_opt_out"):
        try:
            notify.comment_notice(author["email"], author.get("name"), commenter, author.get("preview") or "", body,
                                  notify.page_url(post_link(pid)), notify.unsubscribe_url(author["user_id"]))
        except Exception as e:
            print("[community] reply notice failed for post %s: %r" % (pid, e), flush=True)
    return {"ok": True}
