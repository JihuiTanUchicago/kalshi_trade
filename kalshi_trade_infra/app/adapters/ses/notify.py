"""Transactional email for Tau, over Amazon SES.

A waitlist signup sends two emails: a confirmation to the person who signed up,
and a notification to the operator so they can grant access. Best-effort: a
failed send is logged, not raised, because the request is already saved.

SES sandbox note: until SES production access is granted, SES only delivers to
*verified* addresses, so the operator (verified) gets mail but arbitrary signup
confirmations are refused and logged. Once production access lands, both work
with no code change.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Optional

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
FROM_EMAIL = os.getenv("TAU_FROM_EMAIL", "tjhprivate0416@gmail.com")
OPERATOR_EMAIL = os.getenv("TAU_OPERATOR_EMAIL", "tjhprivate0416@gmail.com")
PUBLIC_URL = os.getenv("TAU_PUBLIC_URL", "https://d1gfpzcosqrjya.cloudfront.net").rstrip("/")


def _link_secret() -> bytes:
    # Reuse a stable server-side secret so unsubscribe links survive restarts without a new env var.
    return (os.getenv("TAU_LINK_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET") or "tau-dev-secret").encode()


def unsubscribe_token(user_id: int) -> str:
    return hmac.new(_link_secret(), b"unsub:%d" % user_id, hashlib.sha256).hexdigest()[:20]


def unsubscribe_token_valid(user_id: int, token: str) -> bool:
    return hmac.compare_digest(unsubscribe_token(user_id), token or "")


def unsubscribe_url(user_id: int) -> str:
    return "%s/unsubscribe?u=%d&t=%s" % (PUBLIC_URL, user_id, unsubscribe_token(user_id))


def page_url(path: str) -> str:
    """A Tau page as an email links it (the bell's /community#post-<id> becomes a full address)."""
    return PUBLIC_URL + path


_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_MD_PAIRS = re.compile(r"`([^`\n]+)`|\*\*([^*\n]+)\*\*")


def _plain(text: Optional[str], limit: int = 0) -> str:
    """A post or reply as an email quotes it: the feed's `code`, **bold** and [text](url) marks read as
    plain words, cut at `limit` characters with an ellipsis."""
    s = _MD_PAIRS.sub(lambda m: m.group(1) or m.group(2), _MD_LINK.sub(r"\1 (\2)", text or "")).strip()
    return s[:limit - 1].rstrip() + "…" if limit and len(s) > limit else s


def _hi(name: Optional[str]) -> str:
    """The greeting line: the reader's name, or "there" when there is none or it is an email address (a
    Google profile with no name set uses the address as its name: "Hi ann@example.com,")."""
    s = (name or "").strip()
    return "Hi %s," % (s if s and "@" not in s else "there")


def _optional_footer(unsub_url: Optional[str]) -> str:
    """How to stop an optional email: the one-click link when the sender has one, and Settings' switch. Each
    address ends its line: a mail app that links "…/settings)" took the bracket into the link, a page not found."""
    settings = "%s/settings" % PUBLIC_URL
    if unsub_url:
        return "Don't want these? Unsubscribe: %s\nOr turn them off anytime under Email in Settings: %s" % (unsub_url, settings)
    return "Turn these off anytime under Email in Settings: %s" % settings


def _send(to: str, subject: str, body: str, reply_to: Optional[str] = None) -> bool:
    try:
        import boto3  # lazy so local dev without boto3 still runs
    except ImportError:
        print("[notify] boto3 not installed; skipping email", flush=True)
        return False
    try:
        # .env.aws sets AWS_PROFILE for a laptop; on the instance role that is
        # fatal, so the systemd unit unsets it and boto3 uses the role.
        kwargs = {
            "Source": FROM_EMAIL,
            "Destination": {"ToAddresses": [to]},
            "Message": {"Subject": {"Data": subject[:200]}, "Body": {"Text": {"Data": body}}},
        }
        if reply_to:
            kwargs["ReplyToAddresses"] = [reply_to]
        boto3.client("ses", region_name=AWS_REGION).send_email(**kwargs)
        return True
    except Exception as e:  # pragma: no cover - network path
        print("[notify] SES send to %s failed: %r" % (to, e), flush=True)
        return False


def waitlist_request(email: str, note: Optional[str], count: int, open_signup: bool = False) -> bool:
    """Email the operator and confirm to the signer. Returns True if the
    operator notification was sent. `open_signup` is the server's sign-up switch (app.web.settings.OPEN_SIGNUP):
    while it is on anyone can sign in with Google, so the confirmation says so instead of promising an
    invite email that nothing sends (approving a request sends no email). Each paragraph is one line, so a
    phone's mail app wraps it to the screen instead of breaking it mid-sentence."""
    signup_line = email + ((" (%s)" % note) if note else "")
    let_in = ("Sign-up is open, so they can already sign in with Google; nothing to do." if open_signup else
              "To let them in while the Google app is in Testing: add this address as a test user in the Google "
              "Cloud console (Google Auth Platform > Audience).")
    operator_body = (
        "A new person asked for access to Tau.\n\n"
        "Email: %s\n"
        "Note:  %s\n"
        "Total waitlist requests: %d\n\n"
        "%s Reply to this email to reach them directly."
    ) % (email, note or "(none)", count, let_in)
    sent_op = _send(OPERATOR_EMAIL, "Tau waitlist: %s" % signup_line, operator_body, reply_to=email)

    access = ("Sign-up is open now: sign in with Google to start.\n\n  %s/signin" % PUBLIC_URL if open_signup else
              "Access is invite-only right now. Once your request is approved, sign in with Google here:\n\n  %s/signin"
              % PUBLIC_URL)
    confirm_body = (
        "Thanks for joining the Tau waitlist.\n\n"
        "Tau turns a trading idea into strategies an agent researches and backtests.\n\n"
        "%s\n\n"
        "— The Tau team"
    ) % access
    _send(email, "You're on the Tau waitlist", confirm_body)
    return sent_op


def comment_notice(to_email: str, author_name: Optional[str], commenter: str,
                   post_preview: str, comment_body: str, link: Optional[str] = None,
                   unsub_url: Optional[str] = None) -> bool:
    """Tell a post's author that someone replied, with a link that opens the post and its replies.
    Best-effort (SES sandbox only delivers to verified addresses until production access lands)."""
    body = (
        "%s\n\n"
        "%s replied to your post on Tau:\n\n"
        "  Your post: “%s”\n"
        "  Their reply: “%s”\n\n"
        "Read the replies and answer: %s\n\n"
        "— Tau\n\n"
        "%s"
    ) % (_hi(author_name), commenter, _plain(post_preview, 140), _plain(comment_body, 280),
         link or page_url("/community"), _optional_footer(unsub_url))
    return _send(to_email, "%s replied to your Tau post" % commenter, body)


def community_post_notice(to_email: str, name: Optional[str], author: str,
                          preview: str, unsub_url: str, link: Optional[str] = None) -> bool:
    """Tell a user a new post landed in the community, with a link to it. Best-effort; respects the
    per-recipient cooldown and opt-out enforced by the caller."""
    body = (
        "%s\n\n"
        "%s just posted in the Tau community:\n\n"
        "  “%s”\n\n"
        "Read it and join in: %s\n\n"
        "— Tau\n\n"
        "%s"
    ) % (_hi(name), author, _plain(preview, 280), link or page_url("/community"), _optional_footer(unsub_url))
    return _send(to_email, "New in the Tau community", body)


def mention_notice(to_email: str, name: Optional[str], author: str, body: str,
                   link: Optional[str] = None, unsub_url: Optional[str] = None, where: Optional[str] = None) -> bool:
    """Tell a user they were @-mentioned in the community, with a link to where. `where` is what the mention
    is in ("a post" or "a reply"), as the bell says it. Best-effort."""
    text = (
        "%s\n\n"
        "%s mentioned you in %sthe Tau community:\n\n"
        "  “%s”\n\n"
        "Read it and reply: %s\n\n"
        "— Tau\n\n"
        "%s"
    ) % (_hi(name), author, (where + " in ") if where else "", _plain(body, 280), link or page_url("/community"), _optional_footer(unsub_url))
    return _send(to_email, "%s mentioned you on Tau" % author, text)


def live_ready_notice(to_email: str, name: Optional[str], title: str, evidence: str, strategy_url: str,
                      note: str = "", live_open: bool = True) -> bool:
    """Tell a user one of their paper strategies just cleared every paper -> live check. Sent once
    per strategy (the caller dedups). It never turns anything on: going live stays the user's step.
    `live_open` is the server's live switch: while it is closed the email says the strategy waits on
    paper, never that it can be promoted to live now."""
    next_step = (
        "Nothing has changed yet. To trade it live, promote it from its strategy page or turn on live "
        "autopilot. A new live strategy starts at a quarter of its size for its first 20 trades, and "
        "it is paused automatically if live loses money on average.\n\n") if live_open else (
        "Nothing has changed: live trading isn’t open yet, so it stays on paper and nothing trades "
        "real money.\n\n")
    body = (
        "Hi %s,\n\n"
        "Your paper strategy “%s” just cleared every check Tau requires before real money:\n\n"
        "  %s\n\n"
        "%s"
        "%s"
        "  %s\n\n"
        "— Tau"
    ) % (name or "there", title, evidence, next_step, (note + "\n\n") if note else "", strategy_url)
    subject = ("“%s” is ready for live trading" if live_open else "“%s” cleared every paper-to-live check") % title[:80]
    return _send(to_email, subject, body)


def reload_failed_email(to_email: str, name: Optional[str], amount, reason: str) -> bool:
    """Tell a user an auto-reload of their credits failed (app/adapters/stripe/billing.py sends it once
    per bell notice, so it keeps that notice's throttle). An account email: it is sent whatever the
    optional-email switch in Settings says, because research stops when the credits run out. `reason`
    is the customer-safe reason (StripeError.customer_message), never Stripe's own text."""
    body = (
        "%s\n\n"
        "Auto-reload couldn't add $%s in credits. %s\n\n"
        "Research pauses when your credits run out. To keep it going, update your card on Billing:\n\n"
        "  %s/billing\n\n"
        "— Tau\n\n"
        "(An account email about your credits, so Tau sends it even with updates and community email "
        "off in Settings.)"
    ) % (_hi(name), amount, (reason or "").strip(), PUBLIC_URL)
    return _send(to_email, "Tau auto-reload couldn't add credits", body)


def perps_alert(to_email: str, kind: str, detail: str) -> bool:
    """A Bitcoin perps safety alert (app/adapters/kalshi_perps/kalshi_perps_watch.py: a position mismatch,
    near liquidation, or heavy margin). Sent whatever Settings' optional-email switch says, as Settings and
    the unsubscribe page tell the user, so the email says why it came. `detail` is the watch's own line,
    the same one the chat shows."""
    body = (
        "%s.\n\n"
        "Review your perps account on Funds or in the Kalshi app:\n\n"
        "  %s/funds\n\n"
        "— Tau\n\n"
        "(A safety alert about real money, so Tau sends it even with updates and community email off in Settings.)"
    ) % (detail.rstrip("."), PUBLIC_URL)
    return _send(to_email, "Tau: Bitcoin perps %s alert" % kind, body)
