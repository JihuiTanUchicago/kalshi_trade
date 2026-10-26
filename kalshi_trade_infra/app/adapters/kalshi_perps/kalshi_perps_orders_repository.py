"""Durable owner-scoped Bitcoin perpetual intents; no HTTP or credentials here.

Mutators MUST run inside ``app.repository.transaction``. Every mutation first
locks the stable app_users row, then the environment's policy/risk row. Commit a
successful submission claim BEFORE any network request. A claimed intent can
never be claimed again, including after a timeout, crash, rejection or cancel.
Uncertain sends retain reservations and can only be reconciled, never retried.

Money is USD per native contract, not binary prices or USD per Bitcoin. Kalshi's
native account/market margin limits are authoritative; this store imposes no Tau
notional or leverage cap. Each send still needs explicit owner confirmation.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from app.repository import now_utc


STATUSES = frozenset({"draft", "approved", "claimed", "accepted", "unknown", "cancel_pending",
                      "rejected", "filled", "partial", "canceled"})
TERMINAL = frozenset({"rejected", "filled", "partial", "canceled"})
ERROR_CODES = frozenset({"submission_uncertain", "broker_rejected", "cancel_uncertain",
                         "reconciliation_required", "order_not_found", "user_canceled",
                         "invalid_broker_projection"})
_TRANSITIONS = {
    "claimed": {"claimed", "accepted", "unknown", "cancel_pending", *TERMINAL},
    "accepted": {"accepted", "unknown", "cancel_pending", *TERMINAL},
    "unknown": {"unknown", "accepted", "cancel_pending", *TERMINAL},
    "cancel_pending": {"cancel_pending", "unknown", "accepted", *TERMINAL},
    **{status: {status} for status in TERMINAL},
}
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_TICKER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}\Z")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?\Z")
_COUNT = re.compile(r"[1-9][0-9]{0,19}(?:\.0{1,2})?\Z")
_REQUEST_FIELDS = frozenset({"ticker", "side", "count", "price", "time_in_force",
                              "self_trade_prevention_type", "market_version",
                              "cancel_order_on_pause", "reduce_only", "post_only", "subaccount"})
_PREVIEW_FIELDS = frozenset({"contract_multiplier", "btc_quantity", "notional_usd", "taker_fee_rate",
                             "estimated_fee_usd", "account_equity", "available_balance",
                             "account_leverage", "quoted_at"})
_SETTINGS_COLUMNS = ("user_id, environment, enabled, manual_confirmation_required, risk_mode, "
                     "version, risk_revision, created_at, updated_at")
_ORDER_COLUMNS = (
    "id, user_id, environment, client_token, key_revision_hash, client_order_id, request_hash, "
    "request_json, instrument_hash, source, proposal_id, preview_json, notional_usd, reserved_usd, status, version, "
    "approved_by_user_id, approved_policy_version, approved_at, claimed_at, broker_order_id, "
    "filled_count, remaining_count, filled_notional_usd, fees_paid_usd, error_code, created_at, updated_at"
)

DDL = [
    """CREATE TABLE IF NOT EXISTS app_kalshi_perps_settings (
      user_id BIGINT NOT NULL,
      environment VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      enabled BOOLEAN NOT NULL DEFAULT FALSE,
      manual_confirmation_required BOOLEAN NOT NULL DEFAULT TRUE,
      risk_mode VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'kalshi_limits',
      version BIGINT NOT NULL DEFAULT 0,
      risk_revision BIGINT NOT NULL DEFAULT 0,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (user_id, environment)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS app_kalshi_perps_orders (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      environment VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      client_token VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      key_revision_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      client_order_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      request_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      request_json JSON NOT NULL,
      instrument_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      source VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      proposal_id BIGINT NULL,
      preview_json JSON NULL,
      notional_usd DECIMAL(38,18) NOT NULL,
      reserved_usd DECIMAL(38,18) NOT NULL,
      status VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'draft',
      version BIGINT NOT NULL DEFAULT 0,
      approved_by_user_id BIGINT NULL,
      approved_policy_version BIGINT NULL,
      approved_at DATETIME NULL,
      claimed_at DATETIME NULL,
      broker_order_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL,
      filled_count DECIMAL(38,18) NOT NULL DEFAULT 0,
      remaining_count DECIMAL(38,18) NULL,
      filled_notional_usd DECIMAL(38,18) NULL,
      fees_paid_usd DECIMAL(38,18) NULL,
      error_code VARCHAR(48) CHARACTER SET ascii COLLATE ascii_bin NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      UNIQUE KEY uq_kalshi_perps_token (user_id, environment, client_token),
      UNIQUE KEY uq_kalshi_perps_client (environment, client_order_id),
      INDEX idx_kalshi_perps_owner (user_id, environment, id),
      INDEX idx_kalshi_perps_reservations (user_id, environment, status),
      INDEX idx_kalshi_perps_claims (user_id, environment, claimed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # Standing conditions found by app.adapters.kalshi_perps.kalshi_perps_watch, so each is announced
    # once (and once when it clears) rather than on every sweep.
    """CREATE TABLE IF NOT EXISTS app_kalshi_perps_watch (
      user_id BIGINT NOT NULL,
      environment VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      alert_key VARCHAR(220) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      kind VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      detail VARCHAR(400) NOT NULL,
      status VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'open',
      detected_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      resolved_at DATETIME NULL,
      PRIMARY KEY (user_id, environment, alert_key),
      INDEX idx_kalshi_perps_watch_open (environment, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


def _identifier(value: int, name: str, *, zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not (0 if zero else 1) <= value < 2**63:
        raise ValueError("Invalid perpetual %s." % name)


def _context(user_id: int, environment: str) -> None:
    _identifier(user_id, "owner")
    if environment not in ("production", "demo"):
        raise ValueError("A production or demo perpetual context is required.")


def _hash(value: str, name: str) -> None:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("Perpetual %s must be a SHA-256 hash." % name)


def _money(value: str | Decimal, *, positive: bool = False) -> Decimal:
    # No floats, exponents, silent SQL rounding or unbounded Decimal formatting.
    if isinstance(value, Decimal):
        parts = value.as_tuple()
        if (not value.is_finite() or value.adjusted() >= 20 or len(parts.digits) > 76
                or not -76 <= parts.exponent <= 20):
            raise ValueError("Perpetual amounts must fit DECIMAL(38,18).")
        # Multiplying canonical count "10.00" by an 18-place price can add
        # insignificant zeroes. Remove only zeroes, without Decimal.normalize's
        # ambient-context rounding, before checking the actual SQL precision.
        digits, exponent = list(parts.digits), parts.exponent
        while len(digits) > 1 and digits[-1] == 0:
            digits.pop()
            exponent += 1
        if not -18 <= exponent <= 20:
            raise ValueError("Perpetual amounts must fit DECIMAL(38,18).")
        value = Decimal((parts.sign, tuple(digits), exponent))
        text = format(value, "f")
    else:
        text = value
    if not isinstance(text, str) or not _NUMBER.fullmatch(text):
        raise ValueError("Perpetual amounts must be precise USD/contract decimals.")
    try:
        result = Decimal(text)
    except InvalidOperation:
        raise ValueError("Invalid perpetual amount.") from None
    if result < 0 or (positive and result == 0):
        raise ValueError("Invalid perpetual amount.")
    return result


def _number_text(value: str | Decimal, *, positive: bool = False) -> str:
    text = format(_money(value, positive=positive), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _signed_money(value: str | Decimal) -> Decimal:
    negative = isinstance(value, str) and value.startswith("-") or isinstance(value, Decimal) and value.is_signed()
    magnitude = value[1:] if isinstance(value, str) and negative else value.copy_abs() if isinstance(value, Decimal) else value
    result = _money(magnitude)
    return result.copy_negate() if negative and result != 0 else result


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value: dict) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _request(value: dict, *, with_client_id: bool = False) -> dict:
    required = _REQUEST_FIELDS | ({"client_order_id"} if with_client_id else set())
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Only normalized native perpetual limit IOC fields are allowed.")
    result = dict(value)
    if (not isinstance(result["ticker"], str) or not _TICKER.fullmatch(result["ticker"])
            or result["side"] not in ("bid", "ask")
            or result["time_in_force"] != "immediate_or_cancel"
            or result["self_trade_prevention_type"] != "taker_at_cross"
            or result["cancel_order_on_pause"] is not True
            or result["post_only"] is not False
            or type(result["subaccount"]) is not int or result["subaccount"] != 0
            or not isinstance(result["reduce_only"], bool)):
        raise ValueError("Invalid native perpetual IOC order.")
    _identifier(result["market_version"], "market version")
    count = result["count"]
    if not isinstance(count, str) or not _COUNT.fullmatch(count):
        raise ValueError("Perpetual order count must be a positive whole-contract string.")
    result["count"] = format(Decimal(count), ".2f")
    result["price"] = _number_text(result["price"], positive=True)
    if with_client_id:
        try:
            client = uuid.UUID(result["client_order_id"])
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Perpetual client order identity must be a server UUID.") from None
        if str(client) != result["client_order_id"] or client.version != 4:
            raise ValueError("Perpetual client order identity must be a server UUID4.")
    return result


def instrument_digest(instrument: dict, request: dict, environment: str) -> str:
    """Identity of immutable, validated native contract economics (no live quote)."""
    if environment not in ("production", "demo") or not isinstance(request, dict):
        raise ValueError("A native perpetual instrument context is required.")
    request = _request(request, with_client_id="client_order_id" in request)
    if (not isinstance(instrument, dict) or instrument.get("verified_bitcoin") is not True
            or instrument.get("ticker") != request["ticker"]
            or instrument.get("market_version") != request["market_version"]
            or instrument.get("environment") != environment
            or instrument.get("price_basis") != "per_contract" or instrument.get("price_unit") != "USD"):
        raise ValueError("A matching verified native 0.0001 BTC instrument is required.")
    _identifier(instrument["market_version"], "instrument market version")
    contract_size = _money(instrument.get("contract_size"), positive=True)
    underlying = _money(instrument.get("underlying_multiplier"), positive=True)
    multiplier = _money(instrument.get("contract_multiplier"), positive=True)
    tick = _money(instrument.get("tick_size"), positive=True)
    with localcontext() as context:
        context.prec = 60
        if (multiplier != contract_size * underlying or multiplier != Decimal("0.0001")
                or Decimal(request["price"]) % tick != 0):
            raise ValueError("Native perpetual contract multiplier/tick is inconsistent.")
    return _digest({"ticker": request["ticker"], "market_version": request["market_version"],
                    "environment": environment, "contract_size": _number_text(contract_size), "asset": "BTC",
                    "price_unit": "USD", "price_basis": "per_contract",
                    "underlying_multiplier": _number_text(underlying),
                    "contract_multiplier": _number_text(multiplier), "tick_size": _number_text(tick)})


def _preview(value: dict | None) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - _PREVIEW_FIELDS:
        raise ValueError("Only safe normalized perpetual preview fields are allowed.")
    result = {}
    for key, item in value.items():
        if key == "quoted_at":
            try:
                if not isinstance(item, str) or not 20 <= len(item) <= 40:
                    raise ValueError()
                date = datetime.fromisoformat(item.replace("Z", "+00:00"))
                if date.tzinfo is None or date.utcoffset() is None:
                    raise ValueError()
                result[key] = date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except (ValueError, OverflowError):
                raise ValueError("Perpetual quote preview time must be a UTC ISO timestamp.") from None
        elif key == "estimated_fee_usd":
            # This is an explicitly estimated JSON value, not settled cash in a
            # DECIMAL column. Preserve the product's extra fractional precision.
            text = format(item, "f") if isinstance(item, Decimal) and item.is_finite() and abs(item.as_tuple().exponent) <= 80 else item
            if (not isinstance(text, str) or len(text) > 102
                    or not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,39})(?:\.[0-9]{1,60})?", text)):
                raise ValueError("A precise fixed-decimal estimated fee is required.")
            result[key] = text.rstrip("0").rstrip(".") if "." in text else text
        elif key in ("account_equity", "available_balance", "taker_fee_rate"):
            result[key] = format(_signed_money(item), "f")
        else:
            result[key] = _number_text(item)
    return result


def _decode_order(row: dict | None) -> dict | None:
    if row is None:
        return None
    result = {name: row.get(name) for name in _ORDER_COLUMNS.split(", ")
              if name not in ("request_json", "preview_json")}
    encoded = row.get("request_json")
    request = json.loads(encoded) if isinstance(encoded, (str, bytes)) else encoded
    result["request"] = _request(request, with_client_id=True)
    if result["client_order_id"] != request["client_order_id"] or result["request_hash"] != _digest(result["request"]):
        raise ValueError("Stored perpetual order digest is inconsistent.")
    preview = row.get("preview_json")
    result["preview"] = _preview(json.loads(preview) if isinstance(preview, (str, bytes)) else preview)
    return result


def lock_user(cur: Any, user_id: int, environment: str) -> None:
    """Stable owner lock shared with credentials/settings changes; use a transaction."""
    _context(user_id, environment)
    cur.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (user_id,))
    if cur.fetchone() is None:
        raise ValueError("Perpetual order owner does not exist.")


def get_settings(cur: Any, user_id: int, environment: str, *, for_update: bool = False) -> dict:
    _context(user_id, environment)
    if not isinstance(for_update, bool):
        raise ValueError("Invalid perpetual row-lock flag.")
    cur.execute(f"SELECT {_SETTINGS_COLUMNS} FROM app_kalshi_perps_settings "
                "WHERE user_id=%s AND environment=%s" + (" FOR UPDATE" if for_update else ""),
                (user_id, environment))
    row = cur.fetchone()
    if row is None:
        return dict(user_id=user_id, environment=environment, enabled=False,
                    manual_confirmation_required=True, risk_mode="kalshi_limits", version=0,
                    risk_revision=0, created_at=None, updated_at=None)
    result = {name: row.get(name) for name in _SETTINGS_COLUMNS.split(", ")}
    if type(result["enabled"]) not in (bool, int) or result["enabled"] not in (False, True, 0, 1):
        raise ValueError("Perpetual opt-in setting is invalid.")
    result["enabled"] = bool(result["enabled"])
    if result["manual_confirmation_required"] not in (True, 1) or result["risk_mode"] != "kalshi_limits":
        raise ValueError("Perpetual settings require manual confirmation and Kalshi native limits.")
    result["manual_confirmation_required"] = True
    for key in ("version", "risk_revision"):
        _identifier(result[key], key, zero=True)
    return result


def _ensure_settings(cur: Any, user_id: int, environment: str) -> dict:
    settings = get_settings(cur, user_id, environment, for_update=True)
    if settings["created_at"] is None:
        now = now_utc()
        cur.execute("""INSERT INTO app_kalshi_perps_settings
            (user_id,environment,enabled,manual_confirmation_required,risk_mode,version,risk_revision,created_at,updated_at)
            VALUES (%s,%s,FALSE,TRUE,'kalshi_limits',0,0,%s,%s)""", (user_id, environment, now, now))
        settings = get_settings(cur, user_id, environment, for_update=True)
    return settings


def save_settings(cur: Any, user_id: int, environment: str, *, enabled: bool,
                  expected_version: int) -> dict:
    """Explicit owner opt-in/out; no money caps or autonomous-send toggle exists."""
    _context(user_id, environment)
    _identifier(expected_version, "policy version", zero=True)
    if not isinstance(enabled, bool):
        raise ValueError("Perpetual opt-in must be an explicit boolean.")
    lock_user(cur, user_id, environment)
    row = _ensure_settings(cur, user_id, environment)
    if row["version"] != expected_version:
        raise ValueError("Perpetual settings changed; refresh before confirming.")
    cur.execute("""UPDATE app_kalshi_perps_settings
        SET enabled=%s,version=version+1,risk_revision=risk_revision+1,updated_at=%s
        WHERE user_id=%s AND environment=%s AND version=%s""",
                (enabled, now_utc(), user_id, environment, expected_version))
    if cur.rowcount != 1:
        raise ValueError("Perpetual settings changed; refresh before confirming.")
    return get_settings(cur, user_id, environment)


def _bump_risk(cur: Any, user_id: int, environment: str, expected_revision: int) -> None:
    cur.execute("""UPDATE app_kalshi_perps_settings SET risk_revision=risk_revision+1,updated_at=%s
        WHERE user_id=%s AND environment=%s AND risk_revision=%s""",
                (now_utc(), user_id, environment, expected_revision))
    if cur.rowcount != 1:
        raise ValueError("Perpetual risk snapshot changed; transaction must roll back.")


def insert_draft(cur: Any, user_id: int, environment: str, client_token: str,
                 key_revision_hash: str, request: dict, *, instrument: dict,
                 source: str = "user", reserved_usd: str | Decimal = "0",
                 proposal_id: int | None = None, preview: dict | None = None) -> dict:
    """Idempotent draft with server UUID and immutable normalized request digest."""
    _context(user_id, environment)
    _hash(key_revision_hash, "key revision")
    if not isinstance(client_token, str) or not _TOKEN.fullmatch(client_token):
        raise ValueError("Invalid perpetual draft client token.")
    if source not in ("user", "agent"):
        raise ValueError("Invalid perpetual draft source.")
    if source == "agent":
        _identifier(proposal_id, "agent proposal")
    elif proposal_id is not None:
        raise ValueError("User perpetual drafts cannot bind an agent proposal.")
    request = _request(request)
    instrument_hash = instrument_digest(instrument, request, environment)
    frozen_preview = _preview(preview)
    reservation = _money(reserved_usd)
    with localcontext() as context:
        context.prec = 60
        notional = _money(Decimal(request["count"]) * Decimal(request["price"]), positive=True)
    lock_user(cur, user_id, environment)
    _ensure_settings(cur, user_id, environment)
    cur.execute(f"SELECT {_ORDER_COLUMNS} FROM app_kalshi_perps_orders "
                "WHERE user_id=%s AND environment=%s AND client_token=%s FOR UPDATE",
                (user_id, environment, client_token))
    existing = _decode_order(cur.fetchone())
    if existing is not None:
        saved_request = {key: value for key, value in existing["request"].items() if key != "client_order_id"}
        if (saved_request != request or existing["key_revision_hash"] != key_revision_hash
                or existing["instrument_hash"] != instrument_hash or existing["source"] != source
                or existing["proposal_id"] != proposal_id
                or Decimal(str(existing["reserved_usd"])) != reservation
                or Decimal(str(existing["notional_usd"])) != notional):
            raise ValueError("Perpetual draft token conflicts with an immutable order.")
        return existing
    if proposal_id is not None:
        cur.execute("SELECT id FROM app_proposals WHERE id=%s AND user_id=%s AND kind='kalshi_perps_live'",
                    (proposal_id, user_id))
        if cur.fetchone() is None:
            raise ValueError("Perpetual proposal does not belong to this owner/kind.")
    request["client_order_id"] = str(uuid.uuid4())
    now = now_utc()
    cur.execute("""INSERT INTO app_kalshi_perps_orders
        (user_id,environment,client_token,key_revision_hash,client_order_id,request_hash,request_json,
         instrument_hash,source,proposal_id,preview_json,notional_usd,reserved_usd,status,version,filled_count,created_at,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',0,0,%s,%s)""",
        (user_id, environment, client_token, key_revision_hash, request["client_order_id"],
         _digest(request), _canonical(request), instrument_hash, source, proposal_id,
         _canonical(frozen_preview), notional, reservation, now, now))
    row = get_order(cur, user_id, environment, cur.lastrowid)
    if row is None:
        raise ValueError("Perpetual draft was not readable after persistence.")
    return row


def get_order(cur: Any, user_id: int, environment: str, order_id: int,
              *, for_update: bool = False) -> dict | None:
    _context(user_id, environment)
    _identifier(order_id, "order")
    if not isinstance(for_update, bool):
        raise ValueError("Invalid perpetual row-lock flag.")
    cur.execute(f"SELECT {_ORDER_COLUMNS} FROM app_kalshi_perps_orders "
                "WHERE user_id=%s AND environment=%s AND id=%s" + (" FOR UPDATE" if for_update else ""),
                (user_id, environment, order_id))
    return _decode_order(cur.fetchone())


def get_order_by_token(cur: Any, user_id: int, environment: str, client_token: str) -> dict | None:
    _context(user_id, environment)
    if not isinstance(client_token, str) or not _TOKEN.fullmatch(client_token):
        raise ValueError("Invalid perpetual draft client token.")
    cur.execute(f"SELECT {_ORDER_COLUMNS} FROM app_kalshi_perps_orders "
                "WHERE user_id=%s AND environment=%s AND client_token=%s", (user_id, environment, client_token))
    return _decode_order(cur.fetchone())


def list_orders(cur: Any, user_id: int, environment: str, limit: int = 50) -> list[dict]:
    _context(user_id, environment)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Perpetual order limit must be an integer in 1..100.")
    cur.execute(f"SELECT {_ORDER_COLUMNS} FROM app_kalshi_perps_orders "
                "WHERE user_id=%s AND environment=%s ORDER BY id DESC LIMIT %s",
                (user_id, environment, limit))
    return [_decode_order(row) for row in cur.fetchall()]


def reservation_orders(cur: Any, user_id: int, environment: str) -> list[dict]:
    """All possibly sent orders, across key rotations; 501 is an overflow sentinel."""
    _context(user_id, environment)
    cur.execute(f"SELECT {_ORDER_COLUMNS} FROM app_kalshi_perps_orders "
                "WHERE user_id=%s AND environment=%s "
                "AND status IN ('claimed','accepted','unknown','cancel_pending') ORDER BY id DESC LIMIT 501",
                (user_id, environment))
    return [_decode_order(row) for row in cur.fetchall()]


def submission_count(cur: Any, user_id: int, environment: str) -> int:
    """Monotonic sends across all key revisions, including terminal orders."""
    _context(user_id, environment)
    cur.execute("""SELECT COUNT(*) AS submission_count FROM app_kalshi_perps_orders
        WHERE user_id=%s AND environment=%s AND claimed_at IS NOT NULL""", (user_id, environment))
    row = cur.fetchone()
    value = None if row is None else row.get("submission_count")
    _identifier(value, "submission count", zero=True)
    return value


def approve_order(cur: Any, user_id: int, environment: str, order_id: int, *,
                  expected_version: int, expected_policy_version: int,
                  expected_request_hash: str, key_revision_hash: str,
                  actor_user_id: int, confirmed: bool) -> bool:
    """Approve exactly the displayed draft under the current owner policy/key."""
    _context(user_id, environment)
    _identifier(order_id, "order")
    _identifier(expected_version, "order version", zero=True)
    _identifier(expected_policy_version, "policy version", zero=True)
    _identifier(actor_user_id, "confirming actor")
    _hash(key_revision_hash, "key revision")
    _hash(expected_request_hash, "confirmed request")
    if actor_user_id != user_id or confirmed is not True:
        raise ValueError("The owner must explicitly confirm each perpetual order.")
    lock_user(cur, user_id, environment)
    policy = _ensure_settings(cur, user_id, environment)
    row = get_order(cur, user_id, environment, order_id, for_update=True)
    if (not policy["enabled"] or policy["version"] != expected_policy_version or row is None
            or row["status"] != "draft" or row["version"] != expected_version
            or row["request_hash"] != expected_request_hash
            or row["key_revision_hash"] != key_revision_hash):
        return False
    cur.execute("""UPDATE app_kalshi_perps_orders SET status='approved',version=version+1,
        approved_by_user_id=%s,approved_policy_version=%s,approved_at=%s,updated_at=%s
        WHERE user_id=%s AND environment=%s AND id=%s AND status='draft' AND version=%s""",
        (actor_user_id, policy["version"], now_utc(), now_utc(), user_id, environment, order_id, expected_version))
    return cur.rowcount == 1


def claim_submission(cur: Any, user_id: int, environment: str, order_id: int, *,
                     expected_version: int, expected_policy_version: int,
                     expected_risk_revision: int, key_revision_hash: str) -> bool:
    """Irreversible single-send CAS. Commit this transaction before any HTTP."""
    _context(user_id, environment)
    _identifier(order_id, "order")
    for name, value in (("order version", expected_version), ("policy version", expected_policy_version),
                        ("risk revision", expected_risk_revision)):
        _identifier(value, name, zero=True)
    _hash(key_revision_hash, "key revision")
    lock_user(cur, user_id, environment)
    policy = _ensure_settings(cur, user_id, environment)
    row = get_order(cur, user_id, environment, order_id, for_update=True)
    if (row is None or not policy["enabled"] or policy["version"] != expected_policy_version
            or policy["risk_revision"] != expected_risk_revision or row["status"] != "approved"
            or row["version"] != expected_version or row["claimed_at"] is not None
            or row["approved_by_user_id"] != user_id or row["approved_at"] is None
            or row["approved_policy_version"] != policy["version"]
            or row["key_revision_hash"] != key_revision_hash):
        return False
    cur.execute("""UPDATE app_kalshi_perps_orders SET status='claimed',version=version+1,
        claimed_at=%s,error_code=NULL,updated_at=%s WHERE user_id=%s AND environment=%s AND id=%s
        AND status='approved' AND version=%s AND claimed_at IS NULL""",
        (now_utc(), now_utc(), user_id, environment, order_id, expected_version))
    changed = cur.rowcount == 1
    if changed:
        _bump_risk(cur, user_id, environment, expected_risk_revision)
    return changed


def cancel_draft(cur: Any, user_id: int, environment: str, order_id: int,
                 *, expected_version: int) -> bool:
    """Cancel only a definitely unsent draft/approval; never release a send claim."""
    _context(user_id, environment)
    _identifier(order_id, "order")
    _identifier(expected_version, "order version", zero=True)
    lock_user(cur, user_id, environment)
    policy = _ensure_settings(cur, user_id, environment)
    cur.execute("""UPDATE app_kalshi_perps_orders SET status='canceled',version=version+1,
        remaining_count=0,error_code='user_canceled',updated_at=%s
        WHERE user_id=%s AND environment=%s AND id=%s AND status IN ('draft','approved')
        AND version=%s AND claimed_at IS NULL""", (now_utc(), user_id, environment, order_id, expected_version))
    changed = cur.rowcount == 1
    if changed:
        _bump_risk(cur, user_id, environment, policy["risk_revision"])
    return changed


def record_result(cur: Any, user_id: int, environment: str, order_id: int, *, status: str,
                  broker_order_id: str | None = None, filled_count: str | Decimal | None = None,
                  remaining_count: str | Decimal | None = None,
                  filled_notional_usd: str | Decimal | None = None,
                  fees_paid_usd: str | Decimal | None = None, error_code: str | None = None,
                  expected_version: int | None = None) -> bool:
    """Persist only a minimal normalized observation; never infer missing IOC fields.

    ``partial`` is terminal for IOC only when remaining_count is explicitly zero.
    Terminal fill/cash values never change; fills, cash and fees cannot regress.
    An older or conflicting observation returns False without altering the row.
    """
    _context(user_id, environment)
    _identifier(order_id, "order")
    if not isinstance(status, str) or status not in STATUSES - {"draft", "approved", "claimed"}:
        raise ValueError("Invalid normalized perpetual result status.")
    if expected_version is not None:
        _identifier(expected_version, "order version", zero=True)
    if broker_order_id is not None and (not isinstance(broker_order_id, str)
            or not 1 <= len(broker_order_id) <= 256 or not all(32 < ord(c) < 127 for c in broker_order_id)):
        raise ValueError("Invalid bounded perpetual broker order identifier.")
    if error_code is not None and (not isinstance(error_code, str) or error_code not in ERROR_CODES):
        raise ValueError("Invalid normalized perpetual error code.")
    values = {key: None if value is None else (_signed_money(value) if key == "fees_paid_usd" else _money(value)) for key, value in (
        ("filled_count", filled_count), ("remaining_count", remaining_count),
        ("filled_notional_usd", filled_notional_usd), ("fees_paid_usd", fees_paid_usd))}
    lock_user(cur, user_id, environment)
    policy = _ensure_settings(cur, user_id, environment)
    row = get_order(cur, user_id, environment, order_id, for_update=True)
    if (row is None or row["claimed_at"] is None or status not in _TRANSITIONS.get(row["status"], ())
            or (expected_version is not None and row["version"] != expected_version)
            or row["broker_order_id"] not in (None, broker_order_id) and broker_order_id is not None):
        return False
    if status == "unknown" and (row["status"] == "cancel_pending" or row["error_code"] == "cancel_uncertain"):
        # A failed read cannot erase an ambiguous prior DELETE and authorize
        # another cancellation mutation. Only a conclusive terminal read clears it.
        error_code = "cancel_uncertain"
    for key in values:
        if values[key] is None:
            values[key] = row[key]
    quantity = values["filled_count"]
    requested = Decimal(row["request"]["count"])
    old_quantity = Decimal(str(row["filled_count"]))
    if quantity < old_quantity or quantity > requested:
        return False
    # Cumulative cash for one observed fill quantity is not cash for a larger
    # quantity. Missing new monetary fields must remain unknown, not be reused.
    if quantity > old_quantity:
        if filled_notional_usd is None:
            values["filled_notional_usd"] = None
        if fees_paid_usd is None:
            values["fees_paid_usd"] = None
    remaining = values["remaining_count"]
    with localcontext() as context:
        context.prec = 80
        total_count = None if remaining is None else remaining + quantity
    if remaining is not None and (total_count > requested
            or row["remaining_count"] is not None and remaining > row["remaining_count"]):
        return False
    for key in ("filled_notional_usd", "fees_paid_usd"):
        if (values[key] is not None and row[key] is not None and values[key] < row[key]
                and (key != "fees_paid_usd" or quantity == old_quantity)):
            return False
    if (values["filled_notional_usd"] not in (None, Decimal(0)) and quantity == 0
            or quantity == old_quantity and row["filled_notional_usd"] is not None
            and values["filled_notional_usd"] != row["filled_notional_usd"]):
        return False
    cash = values["filled_notional_usd"]
    if quantity > 0 and cash is not None:
        with localcontext() as context:
            context.prec = 60
            limit_cash = quantity * Decimal(row["request"]["price"])
            if (cash <= 0 or row["request"]["side"] == "bid" and cash > limit_cash
                    or row["request"]["side"] == "ask" and cash < limit_cash):
                return False
    broker = row["broker_order_id"] if broker_order_id is None else broker_order_id
    if status in ("accepted", "cancel_pending", "filled", "partial", "canceled") and broker is None:
        return False
    if status in ("filled", "partial", "canceled") and remaining != 0:
        return False
    if ((status == "filled" and quantity != requested)
            or (status == "partial" and not 0 < quantity < requested)
            or (status in ("canceled", "rejected") and quantity != 0)):
        return False
    if status == "rejected" and error_code != "broker_rejected":
        return False
    if status in ("filled", "partial") and (values["filled_notional_usd"] is None
            or values["filled_notional_usd"] <= 0 or values["fees_paid_usd"] is None):
        return False
    fields = dict(values, status=status, broker_order_id=broker, error_code=error_code)
    if row["status"] in TERMINAL:
        return all(row[key] == value for key, value in fields.items())
    if all(row[key] == value for key, value in fields.items()):
        return True
    cur.execute("""UPDATE app_kalshi_perps_orders SET status=%s,broker_order_id=%s,filled_count=%s,
        remaining_count=%s,filled_notional_usd=%s,fees_paid_usd=%s,error_code=%s,
        version=version+1,updated_at=%s WHERE user_id=%s AND environment=%s AND id=%s
        AND status=%s AND version=%s AND claimed_at IS NOT NULL""",
        (status, broker, quantity, remaining, values["filled_notional_usd"], values["fees_paid_usd"],
         error_code, now_utc(), user_id, environment, order_id, row["status"], row["version"]))
    changed = cur.rowcount == 1
    if changed:
        _bump_risk(cur, user_id, environment, policy["risk_revision"])
    return changed


def begin_cancel(cur: Any, user_id: int, environment: str, order_id: int,
                 *, expected_version: int) -> bool:
    """Persist cancel uncertainty before HTTP; keep the reservation until proof."""
    _context(user_id, environment)
    _identifier(order_id, "order")
    _identifier(expected_version, "order version", zero=True)
    lock_user(cur, user_id, environment)
    row = get_order(cur, user_id, environment, order_id, for_update=True)
    if (row is None or row["status"] not in ("claimed", "accepted", "unknown")
            or row["version"] != expected_version or row["error_code"] == "cancel_uncertain"):
        return False
    return record_result(cur, user_id, environment, order_id, status="cancel_pending",
                         expected_version=expected_version)


# -- position and margin watch (app.adapters.kalshi_perps.kalshi_perps_watch) ------------------------


def users_to_watch(cur: Any, environment: str) -> list[int]:
    """Users whose perps account could hold something: opted in, any order that
    filled, or a watch condition still open (so it can clear)."""
    if environment not in ("production", "demo"):
        raise ValueError("A native perpetual environment is required.")
    cur.execute("""SELECT user_id FROM app_kalshi_perps_settings WHERE environment=%s AND enabled=TRUE
        UNION SELECT user_id FROM app_kalshi_perps_orders WHERE environment=%s AND filled_count > 0
        UNION SELECT user_id FROM app_kalshi_perps_watch WHERE environment=%s AND status='open'
        ORDER BY user_id""", (environment, environment, environment))
    return [int(row["user_id"]) for row in cur.fetchall()]


def filled_net_by_ticker(cur: Any, user_id: int, environment: str) -> dict[str, Decimal]:
    """Signed contracts Tau's own orders filled, per ticker: bid +, ask -. This is
    the book the exchange position is checked against."""
    _context(user_id, environment)
    cur.execute("""SELECT request_json, filled_count FROM app_kalshi_perps_orders
        WHERE user_id=%s AND environment=%s AND filled_count > 0""", (user_id, environment))
    net: dict[str, Decimal] = {}
    for row in cur.fetchall():
        request = row["request_json"]
        request = request if isinstance(request, dict) else json.loads(request)
        qty = Decimal(str(row["filled_count"]))
        signed = qty if request["side"] == "bid" else -qty
        net[request["ticker"]] = net.get(request["ticker"], Decimal(0)) + signed
    return {ticker: qty for ticker, qty in net.items() if qty != 0}


def open_watch_rows(cur: Any, user_id: int, environment: str) -> list[dict]:
    _context(user_id, environment)
    cur.execute("""SELECT alert_key, kind, detail, detected_at, updated_at FROM app_kalshi_perps_watch
        WHERE user_id=%s AND environment=%s AND status='open'""", (user_id, environment))
    return list(cur.fetchall())


def upsert_watch(cur: Any, user_id: int, environment: str, alert_key: str, kind: str, detail: str) -> None:
    _context(user_id, environment)
    now = now_utc()
    cur.execute("""INSERT INTO app_kalshi_perps_watch
        (user_id, environment, alert_key, kind, detail, status, detected_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,'open',%s,%s)
        ON DUPLICATE KEY UPDATE kind=VALUES(kind), detail=VALUES(detail), updated_at=VALUES(updated_at),
          detected_at=IF(status='open', detected_at, VALUES(detected_at)), status='open', resolved_at=NULL""",
                (user_id, environment, alert_key[:220], kind, detail[:400], now, now))


def resolve_watch(cur: Any, user_id: int, environment: str, alert_keys: list[str]) -> None:
    _context(user_id, environment)
    if not alert_keys:
        return
    now = now_utc()
    marks = ",".join(["%s"] * len(alert_keys))
    cur.execute("UPDATE app_kalshi_perps_watch SET status='resolved', resolved_at=%s, updated_at=%s "
                "WHERE user_id=%s AND environment=%s AND status='open' AND alert_key IN (" + marks + ")",
                (now, now, user_id, environment, *alert_keys))
