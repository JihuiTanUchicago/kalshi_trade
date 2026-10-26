"""Per-user Alpaca paper execution; no live host, shared keys or simulated fills.

Drafts are durable and require a user's approval. Commit the submission claim
before HTTP, never repeat an uncertain POST, and reconcile by client_order_id.
Alpaca remains the source of truth for fills and balances; Tau's Kalshi practice
ledger and live execution engine are independent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.adapters.alpaca import alpaca_paper_client as broker
from app.adapters.alpaca import alpaca_paper_repository as store
from app.adapters.brokers import broker_repository as connections
from app.adapters.brokers import broker_vault as vault
from app import repository as repo

TERMINAL = {"filled", "canceled", "expired", "rejected"}
BROKER_STATES = TERMINAL | {
    "new", "accepted", "pending_new", "partially_filled", "pending_cancel",
    "pending_replace", "accepted_for_bidding", "done_for_day", "replaced",
    "stopped", "suspended", "calculated",
}


class Error(ValueError):
    """Only fixed, credential-free messages cross the HTTP boundary."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return os.getenv("TAU_ALPACA_PAPER_ENABLED", "0") == "1"


def order_limit() -> Decimal:
    try:
        text = os.getenv("TAU_ALPACA_PAPER_MAX_ORDER_USD", "500")
        if not re.fullmatch(r"(?:0|[1-9][0-9]{0,6})(?:\.[0-9]{1,2})?", text):
            raise ValueError()
        value = Decimal(text)
        if not value.is_finite() or not Decimal("0") < value <= Decimal("1000000"):
            raise ValueError()
        return value
    except (InvalidOperation, ValueError):
        raise Error("Alpaca paper order limits need operator configuration.", 503) from None


def _require_enabled() -> None:
    if not enabled():
        raise Error("Alpaca paper order submission is not enabled on this server.", 503)


def _decimal(value, *, signed: bool = False) -> Decimal:
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)) or len(str(value)) > 64:
            raise ValueError()
        text = str(value)
        # Bound the textual scale before constructing/formatting a Decimal.
        # JSON byte limits alone do not stop 1e-1000000000 expanding in format().
        if not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,12})?", text):
            raise ValueError()
        number = Decimal(text)
        if not number.is_finite() or abs(number) > Decimal("1000000000000") or (not signed and number < 0):
            raise ValueError()
        return number
    except (InvalidOperation, ValueError):
        raise Error("Alpaca returned an invalid account or order value.", 502) from None


def _text_number(value, *, signed: bool = False) -> str:
    text = format(_decimal(value, signed=signed), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _grant(cur, user_id: int, *, trading: bool = False) -> tuple[str, dict]:
    row = connections.get_connection(cur, user_id, "alpaca", "paper")
    if not row or not row.get("tokens_enc"):
        raise Error("Connect an Alpaca paper account in Settings first.", 409)
    try:
        credentials = vault.decrypt(user_id, "alpaca", "paper", "tokens", row["tokens_enc"])
    except Exception:
        raise Error("Reconnect the Alpaca paper account to restore secure access.", 409) from None
    expiry = credentials.get("expires_at")
    if expiry is not None and (isinstance(expiry, bool) or not isinstance(expiry, (int, float))
                               or not Decimal(str(expiry)).is_finite() or expiry <= time.time()):
        raise Error("Alpaca paper authorization expired. Reconnect the account.", 409)
    if (not isinstance(credentials.get("account_id"), str) or not credentials["account_id"]
            or not isinstance(credentials.get("scope"), str)):
        raise Error("Reconnect the Alpaca paper account to verify its access.", 409)
    if trading and "trading" not in credentials["scope"].split():
        raise Error("Reconnect the Alpaca paper account with order authorization.", 409)
    fingerprint = hashlib.sha256(bytes(row["tokens_enc"])).hexdigest()
    return fingerprint, credentials


def _same_grant(cur, user_id: int, expected: str) -> dict:
    fingerprint, credentials = _grant(cur, user_id, trading=True)
    if fingerprint != expected:
        raise Error("This order belongs to a previous connection. Create a new paper order.", 409)
    return credentials


def public_order(row: dict) -> dict:
    request = row["request"]
    created = row.get("created_at")
    return {
        "id": row["id"], "client_order_id": row["client_order_id"],
        "source": row["source"], "status": row["status"],
        "broker_status": row.get("broker_status"), "proposal_id": row.get("proposal_id"),
        **{name: request[name] for name in ("symbol", "side", "qty", "limit_price", "time_in_force")},
        "filled_qty": _text_number(row.get("filled_qty") or "0"),
        "filled_avg_price": None if row.get("filled_avg_price") is None else _text_number(row["filled_avg_price"]),
        "created_at": created.replace(tzinfo=timezone.utc).isoformat() if isinstance(created, datetime) else None,
        "error_code": row.get("error_code"),
    }


def _request(body: dict) -> dict:
    if not isinstance(body, dict) or set(body) - {"request_key", "symbol", "side", "qty", "limit_price"}:
        raise Error("Provide a symbol, side, whole-share quantity and limit price.")
    try:
        request = broker.normalize_order({
            "symbol": body.get("symbol"), "side": body.get("side"),
            "qty": body.get("qty"), "limit_price": body.get("limit_price"),
            "type": "limit", "time_in_force": "day", "extended_hours": False,
            "client_order_id": "tau-paper-" + uuid.uuid4().hex,
        })
    except broker.Error as exc:
        raise Error(str(exc), 400) from None
    if _decimal(request["qty"]) * _decimal(request["limit_price"]) > order_limit():
        raise Error("This paper order exceeds the server's per-order notional limit.")
    return request


def _draft(cur, user_id: int, body: dict, source: str) -> dict:
    _require_enabled()
    request = _request(body)
    fingerprint, _ = _grant(cur, user_id, trading=True)
    key = body.get("request_key")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
        raise Error("Provide a stable request key for this paper order.")
    try:
        return store.insert_order(cur, user_id, key, fingerprint, request, source=source)
    except ValueError:
        raise Error("The request key was already used for a different paper order.", 409) from None


def create_order(conn, user_id: int, body: dict) -> dict:
    with repo.transaction(conn) as cur:
        store.lock_user(cur, user_id)
        row = _draft(cur, user_id, body, "user")
    return {"order": public_order(row)}


def propose_for_agent(cur, user_id: int, action: dict) -> tuple[str, int]:
    """Caller owns a transaction; this creates a proposal, never a broker POST."""
    store.lock_user(cur, user_id)
    body = {name: action.get(name) for name in ("symbol", "side", "qty", "limit_price")}
    body["request_key"] = "agent-" + uuid.uuid4().hex
    row = _draft(cur, user_id, body, "agent")
    request = row["request"]
    summary = "%s %s %s at a $%s limit (DAY, Alpaca paper)" % (
        request["side"].capitalize(), request["qty"], request["symbol"], request["limit_price"])
    reason = str(action.get("reason") or "").strip()[:1000]
    proposal_id = repo.create_proposal(cur, user_id, "alpaca_paper", summary + (". " + reason if reason else ""),
                                       payload={"order_id": row["id"]})
    store.bind_proposal(cur, user_id, row["id"], proposal_id)
    return "Proposed %s. Your approval is required before submission." % summary, proposal_id


def _row(cur, user_id: int, order_id: int) -> dict:
    if type(order_id) is not int or not 1 <= order_id <= 2**63 - 1:
        raise Error("Provide a valid Alpaca paper order identifier.")
    row = store.get_order(cur, user_id, order_id, for_update=True)
    if row is None:
        raise Error("No such Alpaca paper order.", 404)
    return row


def _account(raw: dict, credentials: dict, *, for_trade: bool = False) -> dict:
    if (not isinstance(raw, dict) or raw.get("id") != credentials["account_id"]
            or raw.get("currency") != "USD"):
        raise Error("Alpaca did not confirm the connected USD paper account.", 409)
    if for_trade and (raw.get("status") != "ACTIVE"
                      or raw.get("trading_blocked") is not False
                      or raw.get("account_blocked") is not False
                      or raw.get("trade_suspended_by_user", False) is not False):
        raise Error("The Alpaca paper account cannot currently submit orders.", 409)
    return {"status": str(raw.get("status") or "unknown")[:32], "currency": "USD",
            **{key: _text_number(raw.get(key), signed=True) for key in
               ("cash", "buying_power", "equity", "portfolio_value")}}


def _positions(rows: list) -> list[dict]:
    if not isinstance(rows, list) or len(rows) > 500:
        raise Error("Alpaca paper positions could not be safely read.", 502)
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise Error("Alpaca returned an unsupported paper position.", 502)
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
            raise Error("Alpaca returned an unsupported paper position.", 502)
        result.append({"symbol": symbol, **{key: _text_number(row.get(key), signed=True) for key in
                       ("qty", "avg_entry_price", "market_value", "unrealized_pl")}})
    return result


def overview(conn, user_id: int) -> dict:
    with conn.cursor() as cur:
        rows = store.list_orders(cur, user_id)
        try:
            fingerprint, credentials = _grant(cur, user_id)
        except Error as exc:
            credentials, reason = None, str(exc)
        else:
            reason = ""
    result = {"environment": "paper", "enabled": enabled(), "connected": credentials is not None,
              "trading_authorized": bool(credentials and "trading" in credentials["scope"].split()),
              "account": None, "positions": [], "orders": [public_order(row) for row in rows],
              "limits": {"max_order_notional_usd": format(order_limit(), "f")},
              "as_of": repo.now_utc().replace(tzinfo=timezone.utc).isoformat(), "reason": reason}
    if not enabled() or credentials is None:
        return result
    try:
        with broker.Client(credentials) as client:
            # One bounded broker listing refreshes locally tracked fills during
            # account views and agent reviews. Absence is never a cancellation
            # or a license to resend; old/uncertain orders retain direct lookup.
            tracked = [row for row in rows if row["connection_hash"] == fingerprint
                       and row["status"] in ("submitting", "submitted", "unknown", "cancel_pending")
                       and row.get("broker_status") not in TERMINAL]
            if tracked:
                observations = client.orders(status="all", limit=500)
                by_client = {raw.get("client_order_id"): raw for raw in observations}
                for row in tracked:
                    raw = by_client.get(row["client_order_id"])
                    if raw is not None:
                        _record(conn, user_id, row["id"], **_broker_update(row["request"], raw))
                with conn.cursor() as cur:
                    result["orders"] = [public_order(row) for row in store.list_orders(cur, user_id)]
            result["positions"] = _positions(client.positions())
            result["account"] = _account(client.account(), credentials)
    except broker.Error as exc:
        raise Error(str(exc), exc.status) from None
    return result


def _validate_capacity(client, credentials: dict, request: dict, unsettled: list[dict]) -> None:
    asset = client.asset(request["symbol"])
    if (not isinstance(asset, dict) or asset.get("class") != "us_equity" or asset.get("status") != "active"
            or asset.get("tradable") is not True or asset.get("symbol") != request["symbol"]):
        raise Error("Choose an active, tradable US stock or ETF for paper trading.", 409)
    orders = client.orders(status="open", limit=500)
    if not isinstance(orders, list) or len(orders) >= 500 or any(not isinstance(row, dict) for row in orders):
        raise Error("Too many open broker orders to validate paper capacity safely.", 409)
    if any(order.get("side") not in ("buy", "sell") or not isinstance(order.get("symbol"), str)
           for order in orders):
        raise Error("Alpaca returned incomplete open-order capacity data.", 502)
    remote_ids = {row.get("client_order_id") for row in orders}
    if any(row["client_order_id"] not in remote_ids for row in unsettled):
        raise Error("Check the status of previous paper orders before submitting another.", 409)
    positions = client.positions()
    if not isinstance(positions, list) or len(positions) > 500 or any(not isinstance(row, dict) for row in positions):
        raise Error("Paper holdings could not be safely verified.", 502)
    account = _account(client.account(), credentials, for_trade=True)
    quantity = _decimal(request["qty"])
    cost = quantity * _decimal(request["limit_price"])
    if cost > order_limit():
        raise Error("This paper order exceeds the current per-order notional limit.", 409)
    if request["side"] == "buy":
        reserved = Decimal("0")
        for order in orders:
            if order.get("side") != "buy":
                continue
            if order.get("type") != "limit" or order.get("order_class", "simple") not in ("simple", ""):
                raise Error("Wait for existing complex or market buy orders to settle before another paper purchase.", 409)
            remaining = _decimal(order.get("qty")) - _decimal(order.get("filled_qty") or "0")
            if remaining < 0:
                raise Error("Alpaca returned inconsistent open order quantities.", 502)
            reserved += remaining * _decimal(order.get("limit_price"))
        cash = min(_decimal(account["cash"], signed=True), _decimal(account["buying_power"], signed=True))
        if cost > cash - reserved:
            raise Error("Insufficient unreserved paper cash; this integration does not borrow on margin.", 409)
    else:
        held = sum((_decimal(row.get("qty"), signed=True) for row in positions
                    if row.get("symbol") == request["symbol"]), Decimal("0"))
        reserved = Decimal("0")
        for order in orders:
            if order.get("symbol") == request["symbol"] and order.get("side") == "sell":
                remaining = _decimal(order.get("qty")) - _decimal(order.get("filled_qty") or "0")
                if remaining < 0:
                    raise Error("Alpaca returned inconsistent open order quantities.", 502)
                reserved += remaining
        if quantity > held - reserved:
            raise Error("Insufficient unreserved shares; opening short paper positions is not supported.", 409)


def _broker_update(request: dict, raw: dict) -> dict:
    """Reject mismatched acknowledgements; never infer a fill from acceptance."""
    if (not isinstance(raw, dict) or raw.get("client_order_id") != request["client_order_id"]
            or raw.get("symbol") != request["symbol"] or raw.get("side") != request["side"]
            or raw.get("type") != "limit" or raw.get("time_in_force") != "day"
            or raw.get("extended_hours", False) is not False
            or raw.get("order_class", "simple") not in ("simple", "")
            or not isinstance(raw.get("id"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", raw["id"])
            or raw.get("status") not in BROKER_STATES):
        raise Error("Alpaca's order acknowledgement needs reconciliation.", 502)
    qty, filled = _decimal(raw.get("qty")), _decimal(raw.get("filled_qty") or "0")
    if qty != _decimal(request["qty"]) or filled > qty or _decimal(raw.get("limit_price")) != _decimal(request["limit_price"]):
        raise Error("Alpaca's order acknowledgement does not match the request.", 502)
    if raw["status"] == "filled" and filled != qty:
        raise Error("Alpaca's completed fill quantity needs reconciliation.", 502)
    average = raw.get("filled_avg_price")
    if filled == 0 and average is not None:
        raise Error("Alpaca's unfilled order price needs reconciliation.", 502)
    if filled > 0 and (average is None or _decimal(average) <= 0):
        raise Error("Alpaca's fill price needs reconciliation.", 502)
    if any(number != number.quantize(Decimal("0.00000001")) for number in
           (qty, filled) + (() if average is None else (_decimal(average),))):
        raise Error("Alpaca's fill precision needs reconciliation.", 502)
    return {"status": "canceled" if raw["status"] == "canceled" else "rejected" if raw["status"] == "rejected" else "submitted",
            "broker_order_id": raw["id"], "broker_status": raw["status"],
            "filled_qty": _text_number(filled),
            "filled_avg_price": None if average is None else _text_number(average), "error_code": None}


def _record(conn, user_id: int, order_id: int, **changes) -> dict:
    with repo.transaction(conn) as cur:
        store.lock_user(cur, user_id)
        store.record_result(cur, user_id, order_id, **changes)
        row = _row(cur, user_id, order_id)
    return {"order": public_order(row)}


def _decide(cur, user_id: int, row: dict, status: str) -> None:
    if row.get("proposal_id"):
        repo.decide_proposal(cur, row["proposal_id"], status)


def submit_order(conn, user_id: int, order_id: int, *, proposal_id: int | None = None) -> dict:
    _require_enabled()
    with repo.transaction(conn) as cur:
        store.lock_user(cur, user_id)
        row = _row(cur, user_id, order_id)
        if proposal_id is not None and row.get("proposal_id") != proposal_id:
            raise Error("The paper order does not belong to this proposal.", 409)
        if row["status"] != "draft":
            return {"order": public_order(row)}
        fingerprint = row["connection_hash"]
        credentials = _same_grant(cur, user_id, fingerprint)
        pending = store.unsettled_orders(cur, user_id, fingerprint)
        submission_count = store.submission_count(cur, user_id, fingerprint)
        if len(pending) > 500 or any(item["status"] in ("submitting", "unknown", "cancel_pending") for item in pending):
            raise Error("Reconcile the in-flight paper order before submitting another.", 409)
        if row.get("proposal_id"):
            proposal = repo.get_proposal(cur, user_id, row["proposal_id"])
            if not proposal or proposal["status"] != "pending":
                raise Error("This agent paper-order proposal is no longer pending.", 409)
    request = row["request"]
    try:
        request = broker.normalize_order(request)
        with broker.Client(credentials) as client:
            _validate_capacity(client, credentials, request, pending)
            # Re-lock after read-only HTTP, recheck connection and competing sends,
            # then commit BEFORE POST. Disconnect cannot authorize new claims.
            with repo.transaction(conn) as cur:
                store.lock_user(cur, user_id)
                _require_enabled()
                _same_grant(cur, user_id, fingerprint)
                current = _row(cur, user_id, order_id)
                if current["status"] != "draft":
                    return {"order": public_order(current)}
                if store.in_flight_orders(cur, user_id, fingerprint):
                    raise Error("Another paper order is in flight. Check its status first.", 409)
                latest = store.unsettled_orders(cur, user_id, fingerprint)
                # A competing send may have finished between the broker reads
                # and this claim. Its new reservation was absent from those
                # reads, so retry validation instead of spending stale cash.
                if {item["id"] for item in latest} != {item["id"] for item in pending}:
                    raise Error("Paper orders changed during validation. Refresh and try again.", 409)
                # Include a competing order which already filled or was rejected
                # and disappeared from the unsettled set. Count every irreversible
                # send claim, including older drafts submitted out of ID order.
                if store.submission_count(cur, user_id, fingerprint) != submission_count:
                    raise Error("Paper orders changed during validation. Refresh and try again.", 409)
                if current.get("proposal_id"):
                    proposal = repo.get_proposal(cur, user_id, current["proposal_id"])
                    if not proposal or proposal["status"] != "pending":
                        raise Error("This agent paper-order proposal is no longer pending.", 409)
                if not store.claim_submission(cur, user_id, order_id):
                    raise Error("This paper order was already submitted or canceled.", 409)
                _decide(cur, user_id, current, "applied")
            try:
                acknowledged = client.submit_order(request)
                update = _broker_update(request, acknowledged)
            except (broker.Error, Error) as exc:
                # A provider rejection may be definitive; every transport or
                # malformed acknowledgement remains unknown until a GET proves it.
                definitive = isinstance(exc, broker.Error) and bool(getattr(exc, "rejected", False))
                update = {"status": "rejected" if definitive else "unknown",
                          "error_code": "broker_rejected" if definitive else "submission_uncertain"}
            return _record(conn, user_id, order_id, **update)
    except broker.Error as exc:
        raise Error(str(exc), exc.status) from None


def decide_proposal(conn, user_id: int, proposal_id: int, decision: str) -> dict:
    """Keep the existing chat Approve/Decline control on the same intent path."""
    if decision not in ("approve", "reject"):
        raise Error("Choose approve or reject.")
    with repo.transaction(conn) as cur:
        store.lock_user(cur, user_id)
        proposal = repo.get_proposal(cur, user_id, proposal_id)
        if not proposal or proposal["kind"] != "alpaca_paper":
            raise Error("No such paper order proposal.", 404)
        payload = proposal.get("payload")
        if not isinstance(payload, dict) or type(payload.get("order_id")) is not int:
            raise Error("The paper order proposal needs review.", 409)
        order_id = payload["order_id"]
        row = _row(cur, user_id, order_id)
        if row.get("proposal_id") != proposal_id:
            raise Error("The paper order does not belong to this proposal.", 409)
        if decision == "reject":
            if proposal["status"] != "pending" or not store.cancel_draft(cur, user_id, order_id):
                raise Error("This paper order proposal was already decided.", 409)
            repo.decide_proposal(cur, proposal_id, "rejected")
            repo.add_chat(cur, user_id, "system", "You declined the Alpaca paper order.")
            return {"ok": True, "order": public_order(_row(cur, user_id, order_id))}
        if proposal["status"] == "rejected":
            raise Error("This paper order proposal was declined.", 409)
    result = submit_order(conn, user_id, order_id, proposal_id=proposal_id)
    # 'applied' records approval/submission, never a fabricated broker fill.
    with repo.transaction(conn) as cur:
        repo.add_chat(cur, user_id, "system", "Alpaca paper order status: %s. Check the paper account for broker fills." % result["order"]["status"])
    return {"ok": True, **result}


def refresh_order(conn, user_id: int, order_id: int) -> dict:
    with repo.transaction(conn) as cur:
        store.lock_user(cur, user_id)
        row = _row(cur, user_id, order_id)
        if row["status"] == "draft" or (row["status"] == "canceled" and not row.get("broker_order_id")):
            return {"order": public_order(row)}
        credentials = _same_grant(cur, user_id, row["connection_hash"])
    try:
        with broker.Client(credentials) as client:
            raw = client.get_order(row["client_order_id"])
        if raw is None:
            # 404 after a timeout is not proof the original POST can be repeated.
            return _record(conn, user_id, order_id, status="unknown", error_code="order_not_yet_found")
        update = _broker_update(row["request"], raw)
        return _record(conn, user_id, order_id, **update)
    except broker.Error as exc:
        raise Error(str(exc), exc.status) from None


def cancel_order(conn, user_id: int, order_id: int) -> dict:
    # The submission kill switch never prevents canceling an existing paper order.
    with repo.transaction(conn) as cur:
        store.lock_user(cur, user_id)
        row = _row(cur, user_id, order_id)
        if row["status"] == "draft":
            store.cancel_draft(cur, user_id, order_id)
            _decide(cur, user_id, row, "rejected")
            return {"order": public_order(_row(cur, user_id, order_id))}
        if row.get("broker_status") in TERMINAL or row["status"] in ("canceled", "rejected"):
            return {"order": public_order(row)}
        credentials = _same_grant(cur, user_id, row["connection_hash"])
    try:
        with broker.Client(credentials) as client:
            raw = client.get_order(row["client_order_id"])
            if raw is None:
                return _record(conn, user_id, order_id, status="unknown", error_code="order_not_yet_found")
            update = _broker_update(row["request"], raw)
            if update["broker_status"] in TERMINAL:
                return _record(conn, user_id, order_id, **update)
            # Record the cancellation request first. A 204 is acceptance of the
            # request, not evidence of a canceled order or an absence of fills.
            _record(conn, user_id, order_id, **{**update, "status": "cancel_pending"})
            try:
                client.cancel_order(update["broker_order_id"])
            except broker.Error:
                return _record(conn, user_id, order_id, **{**update, "status": "cancel_pending", "error_code": "cancel_needs_reconciliation"})
            return _record(conn, user_id, order_id, **{**update, "status": "cancel_pending"})
    except broker.Error as exc:
        raise Error(str(exc), exc.status) from None


def agent_context(conn, user_id: int) -> str:
    if not enabled():
        return "Alpaca broker paper trading is disabled on this server."
    try:
        data = overview(conn, user_id)
        # No encrypted grants, account IDs or raw provider objects enter prompts.
        packet = {name: data[name] for name in ("connected", "trading_authorized", "account", "positions", "orders", "limits", "as_of")}
        packet["positions"] = packet["positions"][:30]
        packet["orders"] = packet["orders"][:15]
        return "Alpaca PAPER account (broker simulated, separate from Kalshi): " + json.dumps(packet)
    except (Error, broker.Error):
        return "Alpaca paper account is unavailable; do not assume cash, positions or an order fill."


def main() -> None:
    """Offline operator check: configuration readiness is not broker acceptance."""
    import argparse
    from app.adapters.brokers import broker_alpaca, broker_oauth
    parser = argparse.ArgumentParser(description="Check Alpaca paper configuration without network or database access.")
    parser.add_argument("command", choices=["status"])
    parser.parse_args()
    try:
        limit = format(order_limit(), "f")
        callback = broker_oauth.redirect_uri("alpaca")
        valid = True
    except (Error, broker_oauth.Error):
        limit, callback, valid = None, None, False
    result = {"environment": "paper", "enabled": enabled(), "endpoint": broker.PAPER_BASE_URL,
              "oauth_configured": broker_alpaca.status()["configured"], "secure_storage_configured": vault.configured(),
              "callback_url": callback, "max_order_notional_usd": limit,
              "configuration_valid": valid, "live_equity_execution": False,
              "user_confirmation_required": True, "provider_or_account_verified": False}
    result["ready_for_user_connection"] = enabled() and valid and result["oauth_configured"] and result["secure_storage_configured"]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
