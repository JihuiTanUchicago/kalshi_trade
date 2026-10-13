"""Operator notifications over SNS.

Used for waitlist requests so the owner can manually grant access while the
app is in Google "Testing" mode. Best-effort: a failed publish is logged, not
raised, because the user's request is already saved in the database.
"""
from __future__ import annotations

import os
from typing import Optional

WAITLIST_TOPIC_ARN = os.getenv("RECURSIVE_WAITLIST_TOPIC_ARN", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def publish(topic_arn: str, subject: str, message: str) -> bool:
    if not topic_arn:
        return False
    try:
        import boto3  # imported lazily so local dev without boto3 still runs
    except ImportError:
        print("[notify] boto3 not installed; skipping publish", flush=True)
        return False
    try:
        # The box sets AWS_PROFILE for a laptop; on the instance role that is
        # fatal (boto3 looks for a credentials file that isn't there), so the
        # systemd unit unsets it. boto3 then falls through to the instance role.
        boto3.client("sns", region_name=AWS_REGION).publish(
            TopicArn=topic_arn, Subject=subject[:100], Message=message
        )
        return True
    except Exception as e:  # pragma: no cover - network path
        print("[notify] publish failed: %r" % e, flush=True)
        return False


def waitlist_request(email: str, note: Optional[str], count: int) -> bool:
    body = (
        "A new user asked for access to Recursive.\n\n"
        "Email: %s\n"
        "Note:  %s\n\n"
        "Total waitlist requests: %d\n\n"
        "To grant access while the Google app is in Testing: add this address as a\n"
        "test user in the Google Cloud console (Google Auth Platform > Audience)."
    ) % (email, note or "(none)", count)
    return publish(WAITLIST_TOPIC_ARN, "Recursive waitlist: %s" % email, body)
