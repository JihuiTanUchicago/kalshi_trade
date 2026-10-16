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


def waitlist_request(email: str, note: Optional[str], count: int) -> bool:
    """Email the operator and confirm to the signer. Returns True if the
    operator notification was sent."""
    signup_line = email + ((" (%s)" % note) if note else "")
    operator_body = (
        "A new person asked for access to Tau.\n\n"
        "Email: %s\n"
        "Note:  %s\n"
        "Total waitlist requests: %d\n\n"
        "To let them in while the Google app is in Testing: add this address as a\n"
        "test user in the Google Cloud console (Google Auth Platform > Audience).\n"
        "Reply to this email to reach the applicant directly."
    ) % (email, note or "(none)", count)
    sent_op = _send(OPERATOR_EMAIL, "Tau waitlist: %s" % signup_line, operator_body, reply_to=email)

    confirm_body = (
        "Thanks for joining the Tau waitlist.\n\n"
        "Tau turns a trading idea into strategies an agent researches and backtests\n"
        "on data it never saw. Access is invite-only right now; we'll email you here\n"
        "as soon as your spot opens.\n\n"
        "— The Tau team"
    )
    _send(email, "You're on the Tau waitlist", confirm_body)
    return sent_op


def comment_notice(to_email: str, author_name: Optional[str], commenter: str,
                   post_preview: str, comment_body: str) -> bool:
    """Tell a post's author that someone replied. Best-effort (SES sandbox only
    delivers to verified addresses until production access lands)."""
    body = (
        "Hi %s,\n\n"
        "%s replied to your post on Tau:\n\n"
        "  Your post: “%s”\n"
        "  Their reply: “%s”\n\n"
        "Open the Community tab to read the full thread and reply back.\n\n"
        "— Tau\n\n"
        "(You can turn these off anytime — just let us know.)"
    ) % (author_name or "there", commenter, (post_preview or "").strip(), comment_body.strip())
    return _send(to_email, "%s replied to your Tau post" % commenter, body)


def community_post_notice(to_email: str, name: Optional[str], author: str,
                          preview: str, unsub_url: str) -> bool:
    """Tell a user a new post landed in the community. Best-effort; respects the
    per-recipient cooldown and opt-out enforced by the caller."""
    body = (
        "Hi %s,\n\n"
        "%s just posted in the Tau community:\n\n"
        "  “%s”\n\n"
        "Open the Community tab to read it and join in.\n\n"
        "— Tau\n\n"
        "Don't want these? Unsubscribe: %s"
    ) % (name or "there", author, (preview or "").strip()[:280], unsub_url)
    return _send(to_email, "New in the Tau community", body)
