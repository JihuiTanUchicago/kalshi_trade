"""A definite order refusal: the exchange answered and created no order.

An order whose outcome is unknown stays 'sent' until recovery finds it on the exchange. A refusal the
exchange states outright is different: there is no order to find, so waiting on it only holds the
ticker and leaves the intent looking lost. ``definite_refusal`` decides which errors are that kind,
and it is conservative: anything it is unsure of (a timeout, a connection error, a 5xx, a conflict, a
rate limit, a body that mentions an existing or duplicate order) is not a definite refusal, and
the intent stays 'sent' for recovery exactly as before.

Only the demo adapter raises ``OrderRefused`` today; live's order path is unchanged.
"""
from __future__ import annotations

import json
from typing import Dict, Optional

# 4xx answers that mean the request was rejected before any order existed: a bad or unacceptable
# request (400, 422), failed auth (401, 403), or an unknown market or endpoint (404). Left out on
# purpose: 408 (the request timed out: unknown), 409 (a conflict, such as a client_order_id that
# already exists, so an order may exist), 429 (rate limited: retryable, and in doubt stays 'sent').
DEFINITE_REFUSAL_STATUSES = frozenset({400, 401, 403, 404, 422})
# A body that mentions any of these might be about an order that exists, so it is never definite.
_MAYBE_EXISTS = ("duplicate", "exist", "conflict")


class OrderRefused(RuntimeError):
    """The exchange refused the order outright (see ``definite_refusal``); no order was created.

    A RuntimeError with the same message the adapter always raised, so every caller that catches,
    counts or logs the error (the execution guard, the latency recorder, the engine) sees no change."""

    def __init__(self, message: str, refusal: Dict) -> None:
        super().__init__(message)
        self.refusal = dict(refusal)

    @property
    def client_order_id(self) -> Optional[str]:
        return self.refusal.get("client_order_id")


def definite_refusal(http_status: int, body: str, client_order_id: Optional[str]) -> Optional[Dict]:
    """The refusal record (http_status, code, message, client_order_id) when an order POST's error
    answer means no order was created, else None (an outcome that is unknown stays unknown)."""
    if int(http_status) not in DEFINITE_REFUSAL_STATUSES:
        return None
    text = str(body or "")
    if any(word in text.lower() for word in _MAYBE_EXISTS):
        return None
    code, message = None, None
    try:
        err = (json.loads(text) or {}).get("error") or {}
        if isinstance(err, dict):
            code, message = err.get("code"), err.get("message")
    except (ValueError, AttributeError):
        pass
    return {"http_status": int(http_status), "code": str(code) if code else None,
            "message": str(message)[:200] if message else text[:200] or None,
            "client_order_id": client_order_id}
