"""Durable, per-user Alpaca paper order intents; no broker HTTP belongs here.

Use mutators inside ``app.repository.transaction`` and release the transaction
before network I/O. Each mutation locks the stable app_users row first, matching
broker connection mutations, so disconnects, claims and reconciliation serialize.
Rows expose the decoded, allowlisted broker payload as ``request``; request_json
and unprojected broker bodies are never returned. Monetary values are DECIMAL.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.repository import now_utc

STATUSES = frozenset({
    "draft", "submitting", "submitted", "unknown", "rejected", "cancel_pending", "canceled",
})
BROKER_STATUSES = frozenset({
    "new", "partially_filled", "filled", "done_for_day", "canceled", "expired", "replaced",
    "pending_cancel", "pending_replace", "accepted", "pending_new", "accepted_for_bidding",
    "stopped", "rejected", "suspended", "calculated",
})
ERROR_CODES = frozenset({
    "broker_rejected", "submission_uncertain", "order_not_yet_found", "cancel_needs_reconciliation",
})
_BROKER_TERMINAL = frozenset({"filled", "canceled", "expired", "rejected"})
_TRANSITIONS = {
    "draft": frozenset({"draft", "rejected", "canceled"}),
    "submitting": frozenset({"submitting", "submitted", "unknown", "rejected", "cancel_pending", "canceled"}),
    "submitted": frozenset({"submitted", "cancel_pending", "unknown", "rejected", "canceled"}),
    "unknown": frozenset({"unknown", "submitted", "cancel_pending", "rejected", "canceled"}),
    "cancel_pending": frozenset({"cancel_pending", "submitted", "unknown", "rejected", "canceled"}),
    "rejected": frozenset({"rejected"}),
    "canceled": frozenset({"canceled"}),
}
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_REQUEST_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_CLIENT_ID = re.compile(r"tau-paper-[a-f0-9]{32}\Z")
_BROKER_ID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9./-]{0,14}\Z")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
_REQUEST_FIELDS = frozenset({
    "symbol", "qty", "side", "type", "time_in_force", "limit_price", "client_order_id", "extended_hours",
})
_COLUMNS = (
    "id, user_id, request_key, connection_hash, client_order_id, request_json, source, "
    "proposal_id, status, broker_order_id, broker_status, filled_qty, filled_avg_price, "
    "error_code, created_at, updated_at, submitted_at"
)

DDL = [
    """
    CREATE TABLE IF NOT EXISTS app_alpaca_paper_orders (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      request_key VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      connection_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      client_order_id VARCHAR(48) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      request_json JSON NOT NULL,
      source VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      proposal_id BIGINT NULL,
      status VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'draft',
      broker_order_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
      broker_status VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
      filled_qty DECIMAL(20,8) NOT NULL DEFAULT 0,
      filled_avg_price DECIMAL(20,8) NULL,
      error_code VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      submitted_at DATETIME NULL,
      UNIQUE KEY uq_alpaca_paper_request (user_id, request_key),
      UNIQUE KEY uq_alpaca_paper_client_id (client_order_id),
      INDEX idx_alpaca_paper_owner (user_id, id),
      INDEX idx_alpaca_paper_unsettled (user_id, connection_hash, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def _identifier(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2**63 - 1:
        raise ValueError("Invalid Alpaca paper " + label + ".")


def _hash(value: str) -> None:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("Alpaca paper connection identifier must be a SHA-256 hash.")


def _decimal(value: Any, *, positive: bool = False) -> Decimal:
    # Reject binary floats, exponents, non-finite values, rounding and truncation.
    if isinstance(value, Decimal) and (not value.is_finite() or value.adjusted() >= 12
            or not -8 <= value.as_tuple().exponent <= 12):
        raise ValueError("Alpaca paper amounts must fit DECIMAL(20,8).")
    text = format(value, "f") if isinstance(value, Decimal) else value
    if not isinstance(text, str) or not _NUMBER.fullmatch(text):
        raise ValueError("Alpaca paper amounts must fit DECIMAL(20,8).")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid Alpaca paper amount.") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("Invalid Alpaca paper amount.")
    return result


def _request(request: dict) -> tuple[dict, str]:
    if not isinstance(request, dict) or set(request) != _REQUEST_FIELDS:
        raise ValueError("Alpaca paper request must contain only normalized order fields.")
    value = dict(request)
    if (not isinstance(value.get("symbol"), str) or not _SYMBOL.fullmatch(value["symbol"])
            or not isinstance(value.get("client_order_id"), str)
            or not _CLIENT_ID.fullmatch(value["client_order_id"])
            or value.get("side") not in ("buy", "sell")
            or value.get("type") != "limit" or value.get("time_in_force") != "day"
            or value.get("extended_hours") is not False):
        raise ValueError("Invalid normalized Alpaca paper order.")
    for key in ("qty", "limit_price"):
        _decimal(value[key], positive=True)
        if not isinstance(value[key], str):
            raise ValueError("Normalized Alpaca paper order amounts must be strings.")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > 8192:
        raise ValueError("Alpaca paper order exceeds the storage limit.")
    return value, encoded


def _decode_row(row: dict | None) -> dict | None:
    if row is None:
        return None
    # Explicit projection keeps accidental joined/private columns out of callers.
    result = {name: row.get(name) for name in _COLUMNS.split(", ") if name != "request_json"}
    value = row.get("request_json")
    request = json.loads(value) if isinstance(value, (str, bytes)) else value
    result["request"], _ = _request(request)
    return result


def lock_user(cur: Any, user_id: int) -> None:
    """Take the same stable owner lock used for broker connection mutations."""
    _identifier(user_id, "owner")
    cur.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (user_id,))
    if cur.fetchone() is None:
        raise ValueError("Alpaca paper order owner does not exist.")


def _proposal(cur: Any, user_id: int, proposal_id: int) -> None:
    _identifier(proposal_id, "proposal")
    cur.execute(
        "SELECT id FROM app_proposals WHERE id=%s AND user_id=%s AND kind='alpaca_paper'",
        (proposal_id, user_id),
    )
    if cur.fetchone() is None:
        raise ValueError("Alpaca paper proposal does not belong to this owner.")


def insert_order(cur: Any, user_id: int, request_key: str, connection_hash: str,
                 request: dict, source: str = "user", proposal_id: int | None = None) -> dict:
    """Persist before HTTP; replays return the original identity and frozen request.

    A caller may generate a new client_order_id on a repeated HTTP request; only
    that field is ignored when comparing the normalized replay payload. The
    saved client_order_id is always returned and never replaced.
    """
    _identifier(user_id, "owner")
    _hash(connection_hash)
    if not isinstance(request_key, str) or not _REQUEST_KEY.fullmatch(request_key):
        raise ValueError("Invalid Alpaca paper request key.")
    if source not in ("user", "agent"):
        raise ValueError("Invalid Alpaca paper order source.")
    if proposal_id is not None:
        _identifier(proposal_id, "proposal")
    request, encoded = _request(request)
    lock_user(cur, user_id)
    cur.execute(
        f"SELECT {_COLUMNS} FROM app_alpaca_paper_orders WHERE user_id=%s AND request_key=%s FOR UPDATE",
        (user_id, request_key),
    )
    existing = _decode_row(cur.fetchone())
    if existing is not None:
        old = {key: value for key, value in existing["request"].items() if key != "client_order_id"}
        new = {key: value for key, value in request.items() if key != "client_order_id"}
        if (existing["connection_hash"] != connection_hash or old != new or existing["source"] != source
                or (proposal_id is not None and existing["proposal_id"] != proposal_id)):
            raise ValueError("Alpaca paper request key conflicts with an existing order.")
        return existing
    if proposal_id is not None:
        _proposal(cur, user_id, proposal_id)
    now = now_utc()
    cur.execute(
        """INSERT INTO app_alpaca_paper_orders
           (user_id, request_key, connection_hash, client_order_id, request_json, source,
            proposal_id, status, filled_qty, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',0,%s,%s)""",
        (user_id, request_key, connection_hash, request["client_order_id"], encoded,
         source, proposal_id, now, now),
    )
    row = get_order(cur, user_id, cur.lastrowid)
    if row is None:
        raise ValueError("Alpaca paper order could not be read after persistence.")
    return row


def get_order(cur: Any, user_id: int, order_id: int, for_update: bool = False) -> dict | None:
    _identifier(user_id, "owner")
    _identifier(order_id, "order")
    if not isinstance(for_update, bool):
        raise ValueError("Invalid Alpaca paper row lock flag.")
    suffix = " FOR UPDATE" if for_update else ""
    cur.execute(
        f"SELECT {_COLUMNS} FROM app_alpaca_paper_orders WHERE user_id=%s AND id=%s" + suffix,
        (user_id, order_id),
    )
    return _decode_row(cur.fetchone())


def list_orders(cur: Any, user_id: int, limit: int = 50) -> list[dict]:
    _identifier(user_id, "owner")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Alpaca paper order limit must be between 1 and 100.")
    cur.execute(
        f"SELECT {_COLUMNS} FROM app_alpaca_paper_orders WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    return [_decode_row(row) for row in cur.fetchall()]


def in_flight_orders(cur: Any, user_id: int, connection_hash: str) -> list[dict]:
    _identifier(user_id, "owner")
    _hash(connection_hash)
    cur.execute(
        f"""SELECT {_COLUMNS} FROM app_alpaca_paper_orders
            WHERE user_id=%s AND connection_hash=%s
              AND status IN ('submitting','unknown','cancel_pending') ORDER BY id DESC LIMIT 501""",
        (user_id, connection_hash),
    )
    return [_decode_row(row) for row in cur.fetchall()]


def unsettled_orders(cur: Any, user_id: int, connection_hash: str) -> list[dict]:
    """Return up to 501 reservations; callers must halt if more than 500 exist."""
    _identifier(user_id, "owner")
    _hash(connection_hash)
    cur.execute(
        f"""SELECT {_COLUMNS} FROM app_alpaca_paper_orders
            WHERE user_id=%s AND connection_hash=%s
              AND (status IN ('submitting','unknown','cancel_pending')
                   OR (status='submitted' AND
                       (broker_status IS NULL OR broker_status NOT IN ('filled','canceled','expired','rejected'))))
            ORDER BY id DESC LIMIT 501""",
        (user_id, connection_hash),
    )
    return [_decode_row(row) for row in cur.fetchall()]


def submission_count(cur: Any, user_id: int, connection_hash: str) -> int:
    """Monotonic claim count, including filled/rejected/broker-canceled orders.

    Snapshot before capacity HTTP and compare again under the stable owner lock
    before claiming. Unsettled IDs alone miss an intervening order that has
    already filled, and MAX(id) misses an older draft claimed after newer orders.
    The ledger never deletes claims or moves them back into draft.
    """
    _identifier(user_id, "owner")
    _hash(connection_hash)
    cur.execute(
        """SELECT COUNT(*) AS submission_count FROM app_alpaca_paper_orders
           WHERE user_id=%s AND connection_hash=%s
             AND (status IN ('submitting','submitted','unknown','rejected','cancel_pending')
                  OR broker_order_id IS NOT NULL OR submitted_at IS NOT NULL)""",
        (user_id, connection_hash),
    )
    row = cur.fetchone()
    count = None if row is None else row.get("submission_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("Alpaca paper submission count is unavailable.")
    return count


def bind_proposal(cur: Any, user_id: int, order_id: int, proposal_id: int) -> bool:
    _identifier(user_id, "owner")
    _identifier(order_id, "order")
    _identifier(proposal_id, "proposal")
    lock_user(cur, user_id)
    _proposal(cur, user_id, proposal_id)
    cur.execute(
        """UPDATE app_alpaca_paper_orders SET proposal_id=%s, updated_at=%s
           WHERE user_id=%s AND id=%s AND status='draft'
             AND (proposal_id IS NULL OR proposal_id=%s)""",
        (proposal_id, now_utc(), user_id, order_id, proposal_id),
    )
    return cur.rowcount == 1


def claim_submission(cur: Any, user_id: int, order_id: int) -> bool:
    """Exactly one claim can move a frozen intent into the HTTP uncertainty window."""
    _identifier(user_id, "owner")
    _identifier(order_id, "order")
    lock_user(cur, user_id)
    cur.execute(
        """UPDATE app_alpaca_paper_orders SET status='submitting', error_code=NULL, updated_at=%s
           WHERE user_id=%s AND id=%s AND status='draft'""",
        (now_utc(), user_id, order_id),
    )
    return cur.rowcount == 1


def record_result(cur: Any, user_id: int, order_id: int, *, status: str,
                  broker_order_id: str | None = None, broker_status: str | None = None,
                  filled_qty: str | Decimal | None = None, filled_avg_price: str | Decimal | None = None,
                  error_code: str | None = None) -> bool:
    """Record a normalized broker observation without reopening terminal orders.

    An older observation cannot decrease fills, replace an established broker
    identity, clear a terminal broker status or overwrite its fill price. False
    means a missing owner/order or a stale/illegal state transition.
    """
    _identifier(user_id, "owner")
    _identifier(order_id, "order")
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("Invalid Alpaca paper order status.")
    if broker_order_id is not None and (not isinstance(broker_order_id, str)
                                       or not _BROKER_ID.fullmatch(broker_order_id)):
        raise ValueError("Invalid Alpaca paper broker order identifier.")
    if broker_status is not None and (not isinstance(broker_status, str) or broker_status not in BROKER_STATUSES):
        raise ValueError("Invalid Alpaca paper broker status.")
    if error_code is not None and (not isinstance(error_code, str) or error_code not in ERROR_CODES):
        raise ValueError("Invalid Alpaca paper error code.")
    quantity = None if filled_qty is None else _decimal(filled_qty)
    average = None if filled_avg_price is None else _decimal(filled_avg_price, positive=True)
    if (quantity == 0 and average is not None) or (quantity is not None and quantity > 0 and average is None):
        raise ValueError("Alpaca paper fill quantity and average price must agree.")
    lock_user(cur, user_id)
    row = get_order(cur, user_id, order_id, for_update=True)
    if row is None or status not in _TRANSITIONS.get(row["status"], ()):
        return False
    if row["broker_order_id"] is not None and broker_order_id not in (None, row["broker_order_id"]):
        return False
    old_quantity = Decimal(str(row["filled_qty"]))
    if quantity is None:
        quantity = old_quantity
        average = row["filled_avg_price"] if average is None else average
    if (quantity == 0 and average is not None) or (quantity > 0 and average is None):
        return False
    if quantity > Decimal(row["request"]["qty"]):
        return False
    if quantity < old_quantity:
        return False
    if row["broker_status"] in _BROKER_TERMINAL and broker_status not in (None, row["broker_status"]):
        return False
    if row["broker_status"] in _BROKER_TERMINAL and status != row["status"]:
        return False
    if row["broker_status"] in _BROKER_TERMINAL and (quantity != old_quantity
            or (average is not None and average != row["filled_avg_price"])):
        return False
    broker_order_id = row["broker_order_id"] if broker_order_id is None else broker_order_id
    broker_status = row["broker_status"] if broker_status is None else broker_status
    if (status == "canceled" and row["status"] != "draft"
            and broker_order_id is None and row["submitted_at"] is None):
        return False
    submitted_at = row["submitted_at"] or (now_utc() if status in ("submitted", "cancel_pending") else None)
    fields = {"status": status, "broker_order_id": broker_order_id, "broker_status": broker_status,
              "filled_qty": quantity, "filled_avg_price": average, "error_code": error_code,
              "submitted_at": submitted_at}
    if all(row[key] == value for key, value in fields.items()):
        return True
    cur.execute(
        """UPDATE app_alpaca_paper_orders
           SET status=%s, broker_order_id=%s, broker_status=%s, filled_qty=%s,
               filled_avg_price=%s, error_code=%s, submitted_at=%s, updated_at=%s
           WHERE user_id=%s AND id=%s AND status=%s""",
        (status, broker_order_id, broker_status, quantity, average, error_code,
         submitted_at, now_utc(), user_id, order_id, row["status"]),
    )
    return cur.rowcount == 1


def cancel_draft(cur: Any, user_id: int, order_id: int) -> bool:
    _identifier(user_id, "owner")
    _identifier(order_id, "order")
    lock_user(cur, user_id)
    cur.execute(
        """UPDATE app_alpaca_paper_orders SET status='canceled', error_code=NULL, updated_at=%s
           WHERE user_id=%s AND id=%s AND status='draft'""",
        (now_utc(), user_id, order_id),
    )
    return cur.rowcount == 1
