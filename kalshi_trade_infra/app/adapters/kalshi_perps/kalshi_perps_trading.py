"""Manual, per-user native Bitcoin perpetual trading, separate from binary execution.

Native Kalshi margin limits are authoritative. There are no Tau notional or
leverage caps, leverage request fields, synthetic fills, or automatic sends.
Every intent is confirmed exactly, claimed and committed before one POST.
All SQL remains in repositories and no transaction spans a broker request.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

from app.adapters.kalshi import kalshi_account as account
from app.adapters.kalshi_perps import kalshi_perps_orders_repository as store
from app.adapters.kalshi_perps import kalshi_perps_trading_client as broker
from app import repository as repo

PREVIEW_TTL_SECONDS = 120
SNAPSHOT_TTL_SECONDS = 30
QUOTE_TTL_SECONDS = 10
PROPOSAL_KIND = "kalshi_perps_live"
_REQUEST_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,79}\Z")
_USER_FIELDS = {"side", "count", "price", "reduce_only"}


class Error(ValueError):
    """Fixed, credential-free errors safe for the authenticated API."""

    def __init__(self, message: str, status: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def enabled() -> bool:
    return os.getenv("TAU_KALSHI_PERPS_LIVE_ENABLED", "0").lower() in ("1", "true")


def environment() -> str:
    value = os.getenv("TAU_KALSHI_PERPS_LIVE_ENVIRONMENT", "production")
    if value not in ("production", "demo"):
        raise Error("The operator must select a fixed production or demo perps environment.", 503, "configuration")
    return value


def _require_enabled() -> None:
    if not enabled():
        raise Error("New Bitcoin perpetual orders are disabled by the operator.", 503, "disabled")


def _now() -> datetime:
    return repo.now_utc().replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _decimal(value, *, signed: bool = False, positive: bool = False) -> Decimal:
    try:
        return store._signed_money(value) if signed else store._money(value, positive=positive)
    except (ValueError, TypeError):
        raise Error("A precise native perpetual decimal is required.") from None


def _text(value) -> str:
    return format(value if isinstance(value, Decimal) else Decimal(str(value)), "f")


def _key(cur, user_id: int, env: str) -> tuple[str, dict]:
    getter = repo.get_kalshi_key if env == "production" else repo.get_kalshi_dev_key
    row = getter(cur, user_id)
    if not row or not isinstance(row.get("key_id"), str) or not row.get("private_key_enc"):
        raise Error("Connect your own Kalshi key in Settings for this environment.", 409, "not_connected")
    digest = hashlib.sha256()
    for value in (str(user_id).encode(), env.encode(), row["key_id"].encode(), bytes(row["private_key_enc"])):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest(), row


def _client(user_id: int, row: dict, env: str):
    try:
        credentials = account.credentials_from_row(user_id, row)
        return broker.Client(credentials, env, os.getenv("TAU_KALSHI_PERPS_PROXY_URL") or None)
    except Exception:
        raise Error("Your Kalshi credentials could not be loaded for this environment.", 409, "credentials_unavailable") from None


def _fresh(payload: dict, env: str, ttl: int = SNAPSHOT_TTL_SECONDS) -> None:
    try:
        if payload["environment"] != env or not isinstance(payload["retrieved_at"], str):
            raise ValueError()
        date = datetime.fromisoformat(payload["retrieved_at"].replace("Z", "+00:00"))
        if date.tzinfo is None or not -5 <= (_now() - date).total_seconds() <= ttl:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise Error("A fresh, complete Kalshi perps read is required.", 409, "stale_state") from None


def _schedule(instrument: dict, env: str, exchange: dict) -> None:
    if instrument.get("status") != "active" or instrument.get("verified_bitcoin") is not True:
        raise Error("The verified Bitcoin perpetual market is not active.", 409, "market_closed")
    schedule = instrument.get("schedule")
    if schedule is None:
        # Verified BTC's published 24/7-except-maintenance contract rule, together
        # with fresh affirmative native exchange state, is the opening evidence.
        if (Decimal(instrument["contract_multiplier"]) != Decimal("0.0001")
                or exchange.get("exchange_active") is not True or exchange.get("trading_active") is not True):
            raise Error("Bitcoin perpetual opening evidence is unavailable.", 409, "market_closed")
        return
    if not isinstance(schedule, dict) or schedule.get("is_open") is not True:
        raise Error("The native Bitcoin perpetual schedule is closed or unknown.", 409, "market_closed")
    now = int(_now().timestamp())
    for name in ("next_close_ts", "next_open_ts"):
        value = schedule.get(name)
        if value is not None and (type(value) is not int or value < 0):
            raise Error("The native perpetual schedule is unavailable.", 409, "market_closed")
    close, opening = schedule.get("next_close_ts"), schedule.get("next_open_ts")
    if close is not None and close <= now or close is not None and opening is not None and now < opening <= close:
        raise Error("The native perpetual schedule needs a fresh opening state.", 409, "market_closed")


def _snapshot(client, env: str, ticker: str | None = None) -> dict:
    entitlement = client.enabled_status()
    _fresh(entitlement, env)
    if entitlement.get("enabled") is not True:
        raise Error("Kalshi has not enabled perpetual trading for this user.", 409, "not_eligible")
    exchange = client.exchange_status()
    _fresh(exchange, env)
    if exchange.get("exchange_active") is not True or exchange.get("trading_active") is not True:
        raise Error("Kalshi perpetual trading is paused.", 409, "market_closed")
    instrument = client.market(ticker or os.getenv("TAU_KALSHI_PERPS_LIVE_TICKER") or None)
    _fresh(instrument, env)
    _schedule(instrument, env, exchange)
    book = client.orderbook(instrument["ticker"])
    balance, risk, fees, positions = client.balance(), client.risk(), client.fee_tiers(), client.positions()
    for payload in (entitlement, exchange, instrument, balance, risk, fees, positions):
        _fresh(payload, env)
    _fresh(book, env, QUOTE_TTL_SECONDS)
    try:
        bids, asks = book["orderbook"]["bids"], book["orderbook"]["asks"]
        bid = max(_decimal(level[0], positive=True) for level in bids)
        ask = min(_decimal(level[0], positive=True) for level in asks)
        if bid > ask or balance.get("available_balance_computed") is not True:
            raise ValueError()
        accounts = [row for row in balance["subaccount_balances"] if row["subaccount"] == 0]
        if len(accounts) != 1:
            raise ValueError()
        primary = accounts[0]
        for field in ("account_equity", "available_balance", "initial_margin", "maintenance_margin"):
            _decimal(primary[field], signed=True)
        _decimal(balance["settled_funds"], signed=True)
        leverage = _decimal(risk["account_leverage"])
        _decimal(risk["total_position_notional"])
        rate = _decimal(fees["taker_fee_rates"][instrument["ticker"]], signed=True)
        seen = set()
        for position in positions["positions"]:
            if position["subaccount"] != 0 or position["market_ticker"] in seen:
                raise ValueError()
            seen.add(position["market_ticker"])
            _decimal(position["position"], signed=True)
    except (KeyError, TypeError, ValueError):
        raise Error("Complete native margin, fees, positions and uncrossed depth are required.", 409, "incomplete_state") from None
    timestamps = [datetime.fromisoformat(payload["retrieved_at"].replace("Z", "+00:00"))
                  for payload in (entitlement, exchange, instrument, book, balance, risk, fees, positions)]
    return {"environment": env, "retrieved_at": _iso(min(timestamps)), "exchange": exchange,
            "instrument": instrument, "account": primary, "settled_funds": balance["settled_funds"],
            "risk": risk, "positions": positions["positions"], "rate": rate,
            "quote": {"bid": _text(bid), "ask": _text(ask), "retrieved_at": book["retrieved_at"]},
            "leverage": leverage}


def _fresh_snapshot(state: dict, env: str) -> None:
    _fresh(state, env)
    _fresh({"environment": env, "retrieved_at": state["quote"]["retrieved_at"]}, env, QUOTE_TTL_SECONDS)
    _schedule(state["instrument"], env, state["exchange"])


def _user_request(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != _USER_FIELDS:
        raise Error("Use only side, whole-contract count, USD limit price and reduce_only.")
    try:
        normalized = store._request({**value, "ticker": "BTC", "market_version": 1,
            "time_in_force": "immediate_or_cancel", "self_trade_prevention_type": "taker_at_cross",
            "post_only": False, "cancel_order_on_pause": True, "subaccount": 0})
    except ValueError:
        raise Error("A whole positive contract count and tick-valid USD per-contract limit are required.") from None
    return {field: normalized[field] for field in _USER_FIELDS}


def _ticket(value: dict) -> tuple[str, dict]:
    if not isinstance(value, dict) or set(value) != _USER_FIELDS | {"request_key"}:
        raise Error("A draft request key and normalized native order are required.")
    key = value["request_key"]
    if not isinstance(key, str) or not _REQUEST_KEY.fullmatch(key):
        raise Error("Use a fresh request key of 8 to 80 safe characters.")
    return key, _user_request({field: value[field] for field in _USER_FIELDS})


def _reduce_only(request: dict, snapshot: dict) -> None:
    if not request["reduce_only"]:
        return
    position = next((_decimal(row["position"], signed=True) for row in snapshot["positions"]
                     if row["market_ticker"] == snapshot["instrument"]["ticker"]), Decimal(0))
    if (position == 0 or request["side"] != ("ask" if position > 0 else "bid")
            or Decimal(request["count"]) > abs(position)):
        raise Error("A reduce-only order must oppose and fit the current native position.", 409, "invalid_reduce_only")


def _owned(cur, user_id: int, env: str, order_id: int) -> dict:
    try:
        row = store.get_order(cur, user_id, env, order_id)
    except ValueError:
        raise Error("The stored perpetual order is unavailable.", 409, "invalid_order") from None
    if row is None:
        raise Error("No such perpetual order for this owner and environment.", 404, "not_found")
    return row


def _proposal(cur, user_id: int, proposal_id: int, env: str) -> dict:
    if type(proposal_id) is not int or proposal_id < 1:
        raise Error("No such perpetual proposal.", 404, "not_found")
    row = repo.get_proposal(cur, user_id, proposal_id)
    if (not row or row["kind"] != PROPOSAL_KIND or not isinstance(row.get("payload"), dict)
            or row["payload"].get("environment") != env):
        raise Error("No such perpetual proposal for this owner and environment.", 404, "not_found")
    return row


def public_order(row: dict) -> dict:
    quantity, cash = Decimal(str(row["filled_count"])), row["filled_notional_usd"]
    with localcontext() as context:
        context.prec = 60
        average = _text(Decimal(str(cash)) / quantity) if quantity > 0 and cash is not None else None
    created = row["created_at"].replace(tzinfo=timezone.utc)
    request = {field: row["request"][field] for field in
               ("ticker", "side", "count", "price", "time_in_force", "reduce_only")}
    # The native wire body retains fixed-point count and its frozen digest;
    # the public whole-contract ticket has the user's integer representation.
    request["count"] = str(int(Decimal(row["request"]["count"])))
    return {"id": row["id"], "environment": row["environment"], "client_order_id": row["client_order_id"],
            "source": row["source"], "status": row["status"], "version": row["version"],
            "request_hash": row["request_hash"], "request": request,
            "filled_count": _text(quantity), "remaining_count": None if row["remaining_count"] is None else _text(row["remaining_count"]),
            "filled_avg_price": average, "total_fees": None if row["fees_paid_usd"] is None else _text(row["fees_paid_usd"]),
            "created_at": _iso(created), "expires_at": _iso(created + timedelta(seconds=PREVIEW_TTL_SECONDS)),
            "preview": row["preview"], "error_code": row["error_code"]}


def overview(conn, user_id: int) -> dict:
    env = environment()
    with conn.cursor() as cur:
        policy = store.get_settings(cur, user_id, env)
        orders = store.list_orders(cur, user_id, env)
        try:
            _, key = _key(cur, user_id, env)
        except Error:
            key = None
    result = {"enabled": enabled(), "environment": env, "policy": _public_policy(policy),
              "connected": key is not None, "eligible": False, "account": None, "risk": None,
              "market": None, "quote": None, "fees": None, "positions": [],
              "orders": [public_order(row) for row in orders]}
    if not enabled() or key is None:
        return result
    try:
        with _client(user_id, key, env) as client:
            state = _snapshot(client, env)
        result.update(eligible=True, account={**{field: _text(state["account"][field]) for field in
            ("account_equity", "available_balance", "initial_margin", "maintenance_margin")},
            "settled_funds": _text(state["settled_funds"])},
            risk={field: _text(state["risk"][field]) for field in ("account_leverage", "total_position_notional")},
            market={field: state["instrument"][field] for field in
                    ("ticker", "title", "contract_multiplier", "tick_size", "market_version")},
            quote=state["quote"], fees={"taker_rate": _text(state["rate"])},
            positions=[{"ticker": row["market_ticker"], "position": row["position"]} for row in state["positions"]])
    except (broker.Error, Error):
        result.update(message="Fresh native perpetual eligibility or account state could not be confirmed.",
                      error_code="account_unavailable")
    return result


def _public_policy(policy: dict) -> dict:
    return {field: policy[field] for field in ("enabled", "version", "manual_confirmation_required", "risk_mode")}


def save_policy(conn, user_id: int, body: dict) -> dict:
    if (not isinstance(body, dict) or set(body) - {"enabled", "acknowledge_real_money", "expected_version"}
            or type(body.get("enabled")) is not bool or type(body.get("expected_version")) is not int):
        raise Error("An explicit opt-in and current policy version are required.")
    if body["enabled"]:
        _require_enabled()
        if body.get("acknowledge_real_money") is not True:
            raise Error("Acknowledge real money before enabling manual perpetual orders.")
    try:
        with repo.transaction(conn) as cur:
            policy = store.save_settings(cur, user_id, environment(), enabled=body["enabled"],
                                         expected_version=body["expected_version"])
    except ValueError:
        raise Error("The manual perpetual policy changed; refresh before confirming.", 409, "policy_changed") from None
    return {"policy": _public_policy(policy)}


def guard_key_change(cur, user_id: int, env: str) -> None:
    """Credential writers call inside their transaction, before save/delete.

    The stable owner lock serializes credential changes with a submission claim.
    Keep the original connection available to reconcile any possibly sent order,
    even while the global submission switch or the user's policy is disabled.
    """
    try:
        store.lock_user(cur, user_id, env)
        pending = store.reservation_orders(cur, user_id, env)
    except ValueError:
        raise Error("Perpetual order state must be verified before changing this key.", 409, "reconciliation_required") from None
    if pending:
        raise Error("Reconcile open or uncertain perpetual orders before changing this environment's key.",
                    409, "reconciliation_required")


def create_order(conn, user_id: int, body: dict) -> dict:
    key, request = _ticket(body)
    return _create_order(conn, user_id, key, request)


def _create_order(conn, user_id: int, token: str, request: dict, proposal_id: int | None = None) -> dict:
    _require_enabled()
    env = environment()
    with conn.cursor() as cur:
        existing = store.get_order_by_token(cur, user_id, env, token)
        if existing is not None:
            if ({field: existing["request"][field] for field in _USER_FIELDS} != request
                    or existing["proposal_id"] != proposal_id):
                raise Error("The draft request key already identifies a different order.", 409, "request_conflict")
            return {"order": public_order(existing)}
        policy = store.get_settings(cur, user_id, env)
        if not policy["enabled"]:
            raise Error("Enable manual perpetual trading for this user first.", 409, "policy_disabled")
        revision, key_row = _key(cur, user_id, env)
        if store.reservation_orders(cur, user_id, env):
            raise Error("Check the prior perpetual submission before creating another order.", 409, "reconciliation_required")
        if proposal_id is not None and _proposal(cur, user_id, proposal_id, env)["status"] != "pending":
            raise Error("This perpetual proposal was already decided.", 409, "proposal_decided")
    try:
        with _client(user_id, key_row, env) as client:
            state = _snapshot(client, env)
    except broker.Error:
        raise Error("Native perpetual preflight failed; no order was sent.", 409, "preflight_failed") from None
    _reduce_only(request, state)
    wire = {**request, "ticker": state["instrument"]["ticker"], "market_version": state["instrument"]["market_version"],
            "time_in_force": "immediate_or_cancel", "self_trade_prevention_type": "taker_at_cross",
            "post_only": False, "cancel_order_on_pause": True, "subaccount": 0}
    with localcontext() as context:
        context.prec = 80
        notional = Decimal(request["count"]) * Decimal(request["price"])
        preview = {"contract_multiplier": state["instrument"]["contract_multiplier"],
                   "btc_quantity": _text(Decimal(request["count"]) * Decimal(state["instrument"]["contract_multiplier"])),
                   "notional_usd": _text(notional), "taker_fee_rate": _text(state["rate"]),
                   "estimated_fee_usd": _text(notional * state["rate"]),
                   "account_equity": state["account"]["account_equity"],
                   "available_balance": state["account"]["available_balance"],
                   "account_leverage": _text(state["leverage"]), "quoted_at": state["quote"]["retrieved_at"]}
    try:
        with repo.transaction(conn) as cur:
            store.lock_user(cur, user_id, env)
            _require_enabled()
            if environment() != env or _key(cur, user_id, env)[0] != revision:
                raise Error("The perpetual key or environment changed; preview again.", 409, "key_changed")
            current = store.get_settings(cur, user_id, env, for_update=True)
            if not current["enabled"] or current["version"] != policy["version"]:
                raise Error("The manual perpetual policy changed; preview again.", 409, "policy_changed")
            if store.reservation_orders(cur, user_id, env):
                raise Error("A competing perpetual submission needs reconciliation.", 409, "reconciliation_required")
            if proposal_id is not None and _proposal(cur, user_id, proposal_id, env)["status"] != "pending":
                raise Error("This perpetual proposal was already decided.", 409, "proposal_decided")
            _fresh_snapshot(state, env)
            row = store.insert_draft(cur, user_id, env, token, revision, wire, instrument=state["instrument"],
                                     source="agent" if proposal_id is not None else "user", proposal_id=proposal_id, preview=preview)
    except Error:
        raise
    except ValueError:
        raise Error("The perpetual draft could not be frozen; refresh the ticket.", 409, "invalid_order") from None
    return {"order": public_order(row)}


def preview_proposal(conn, user_id: int, proposal_id: int, body: dict) -> dict:
    if not isinstance(body, dict) or set(body) != {"request_key"}:
        raise Error("Only a request key is allowed when reviewing a perpetual proposal.")
    with conn.cursor() as cur:
        proposal = _proposal(cur, user_id, proposal_id, environment())
        request = _user_request(proposal["payload"].get("order"))
    token, request = _ticket({**request, "request_key": body["request_key"]})
    return _create_order(conn, user_id, token, request, proposal_id)


def _confirmation(body: dict, row: dict) -> None:
    if (not isinstance(body, dict) or set(body) != {"confirmed", "expected_version", "request_hash"}
            or body.get("confirmed") is not True or type(body.get("expected_version")) is not int
            or body.get("expected_version") != row["version"] or body.get("request_hash") != row["request_hash"]):
        raise Error("Confirm the exact current perpetual ticket, version and digest.", 409, "confirmation_required")


def _not_expired(row: dict) -> None:
    age = (_now() - row["created_at"].replace(tzinfo=timezone.utc)).total_seconds()
    if not -5 <= age < PREVIEW_TTL_SECONDS:
        raise Error("This perpetual preview expired; review a fresh ticket.", 409, "preview_expired")


def _record(conn, user_id: int, env: str, order_id: int, **values) -> dict:
    with repo.transaction(conn) as cur:
        try:
            changed = store.record_result(cur, user_id, env, order_id, **values)
        except ValueError:
            changed = False
        row = _owned(cur, user_id, env, order_id)
        if not changed and row["status"] not in store.TERMINAL:
            store.record_result(cur, user_id, env, order_id, status="unknown", error_code="invalid_broker_projection")
            row = _owned(cur, user_id, env, order_id)
    return row


def _reconcile(client, row: dict, env: str) -> dict:
    """Only complete native order + fill facts release an uncertain IOC intent."""
    start = max(0, int(row["created_at"].replace(tzinfo=timezone.utc).timestamp()) - 60)
    if row["broker_order_id"] is None:
        listing = client.orders(row["request"]["ticker"], min_ts=start)
        _fresh(listing, env)
        if listing.get("complete") is not True:
            raise Error("Native perpetual order history is incomplete.", 409, "incomplete_state")
        matches = [item for item in listing["orders"] if item.get("client_order_id") == row["client_order_id"]]
        if len(matches) != 1:
            raise Error("The uncertain perpetual order has not been identified conclusively.", 409, "order_not_found")
        observed = matches[0]
    else:
        payload = client.order(row["broker_order_id"])
        _fresh(payload, env)
        observed = payload["order"]
    if (observed.get("client_order_id") != row["client_order_id"]
            or observed.get("ticker") != row["request"]["ticker"] or observed.get("side") != row["request"]["side"]
            or Decimal(observed["price"]) != Decimal(row["request"]["price"])
            or row["broker_order_id"] is not None and observed["order_id"] != row["broker_order_id"]):
        raise Error("The native perpetual order identity is inconsistent.", 409, "invalid_response")
    if any(name in observed and (type(observed[name]) is not int or observed[name] != 0)
           for name in ("subaccount", "subaccount_number")):
        raise Error("The native perpetual subaccount is inconsistent.", 409, "invalid_response")
    quantity = _decimal(observed["fill_count"])
    if quantity > Decimal(row["request"]["count"]) or _decimal(observed["remaining_count"]) != 0:
        raise Error("The native IOC remainder is not conclusively closed.", 409, "incomplete_state")
    ledger = client.fills(start)
    _fresh(ledger, env)
    if ledger.get("complete") is not True:
        raise Error("The native perpetual fill history is incomplete.", 409, "incomplete_state")
    count, cash, fees, seen = Decimal(0), Decimal(0), Decimal(0), set()
    with localcontext() as context:
        context.prec = 80
        for fill in ledger["fills"]:
            if fill["order_id"] != observed["order_id"]:
                continue
            if (fill["fill_id"] in seen or fill["ticker"] != row["request"]["ticker"]
                    or fill["side"] != row["request"]["side"]
                    or any(name in fill and (type(fill[name]) is not int or fill[name] != 0)
                           for name in ("subaccount", "subaccount_number"))):
                raise Error("The native perpetual fill identity is inconsistent.", 409, "invalid_response")
            seen.add(fill["fill_id"])
            size = _decimal(fill["count"], positive=True)
            price = _decimal(fill["price"], positive=True)
            limit = Decimal(row["request"]["price"])
            if (row["request"]["side"] == "bid" and price > limit
                    or row["request"]["side"] == "ask" and price < limit):
                raise Error("A native perpetual fill violates the confirmed limit.", 409, "invalid_response")
            count += size
            cash += size * price
            fees += _decimal(fill["fees"], signed=True)
    if count != quantity:
        raise Error("Native perpetual order and fill quantities have not reconciled.", 409, "incomplete_state")
    positions, balance = client.positions(), client.balance()
    _fresh(positions, env)
    _fresh(balance, env)
    if balance.get("available_balance_computed") is not True:
        raise Error("Fresh native perpetual margin state is unavailable.", 409, "incomplete_state")
    return dict(status="canceled" if count == 0 else "filled" if count == Decimal(row["request"]["count"]) else "partial",
                broker_order_id=observed["order_id"], filled_count=_text(count), remaining_count="0",
                filled_notional_usd=_text(cash), fees_paid_usd=_text(fees))


def submit_order(conn, user_id: int, order_id: int, body: dict) -> dict:
    env = environment()
    with conn.cursor() as cur:
        row = _owned(cur, user_id, env, order_id)
        # A repeated confirmation reports the irreversible claim; it does not
        # create another authorization even if its old version is now stale.
        if row["claimed_at"] is not None or row["status"] in store.TERMINAL:
            return {"order": public_order(row)}
        _confirmation(body, row)
        _not_expired(row)
        policy = store.get_settings(cur, user_id, env)
        revision, key_row = _key(cur, user_id, env)
        if revision != row["key_revision_hash"]:
            raise Error("The perpetual key changed; review a new ticket.", 409, "key_changed")
        if not policy["enabled"] or store.reservation_orders(cur, user_id, env):
            raise Error("Enable manual perps and reconcile any prior submission first.", 409, "reconciliation_required")
    _require_enabled()
    try:
        with _client(user_id, key_row, env) as client:
            state = _snapshot(client, env, row["request"]["ticker"])
            _reduce_only(row["request"], state)
            if (store.instrument_digest(state["instrument"], row["request"], env) != row["instrument_hash"]
                    or state["rate"] != _decimal(row["preview"]["taker_fee_rate"], signed=True)):
                raise Error("Native perpetual contract or fee terms changed; preview again.", 409, "preview_stale")
            with repo.transaction(conn) as cur:
                store.lock_user(cur, user_id, env)
                _require_enabled()
                current = _owned(cur, user_id, env, order_id)
                if current["claimed_at"] is not None:
                    return {"order": public_order(current)}
                _confirmation(body, current)
                _not_expired(current)
                live_policy = store.get_settings(cur, user_id, env, for_update=True)
                if (environment() != env or _key(cur, user_id, env)[0] != revision
                        or live_policy["version"] != policy["version"] or not live_policy["enabled"]
                        or live_policy["risk_revision"] != policy["risk_revision"]
                        or store.reservation_orders(cur, user_id, env)):
                    raise Error("The key, manual policy or native account snapshot changed; refresh.", 409, "stale_state")
                if current["proposal_id"] is not None:
                    proposal = _proposal(cur, user_id, current["proposal_id"], env)
                    if proposal["status"] != "pending":
                        raise Error("This perpetual proposal was already submitted or declined.", 409, "proposal_decided")
                _fresh_snapshot(state, env)
                if current["status"] == "draft":
                    if not store.approve_order(cur, user_id, env, order_id, expected_version=current["version"],
                        expected_policy_version=live_policy["version"], expected_request_hash=current["request_hash"],
                        key_revision_hash=revision, actor_user_id=user_id, confirmed=True):
                        raise Error("The perpetual confirmation changed; refresh.", 409, "stale_state")
                    current = _owned(cur, user_id, env, order_id)
                if not store.claim_submission(cur, user_id, env, order_id, expected_version=current["version"],
                    expected_policy_version=live_policy["version"], expected_risk_revision=live_policy["risk_revision"],
                    key_revision_hash=revision):
                    raise Error("The perpetual order could not acquire a single-send claim.", 409, "stale_state")
                if current["proposal_id"] is not None and not repo.decide_proposal(cur, current["proposal_id"], "applied"):
                    raise Error("This perpetual proposal was already decided.", 409, "proposal_decided")
                frozen = _owned(cur, user_id, env, order_id)
            # The irreversible claim and proposal decision are committed here.
            if not enabled() or environment() != env:
                result = _record(conn, user_id, env, order_id, status="unknown", error_code="reconciliation_required")
                return {"order": public_order(result)}
            try:
                ack = client.submit_order(frozen["request"])
                _fresh(ack, env)
                result = _record(conn, user_id, env, order_id, status="accepted", broker_order_id=ack["order_id"],
                                 filled_count=ack["fill_count"], remaining_count=ack["remaining_count"])
                # Positive-fill economics come from the complete REST ledger,
                # avoiding rounding an average fee into purported exact cash.
                try:
                    projection = _reconcile(client, result, env)
                except (broker.Error, Error, KeyError, ValueError):
                    result = _record(conn, user_id, env, order_id, status="unknown", error_code="reconciliation_required")
                else:
                    result = _record(conn, user_id, env, order_id, **projection)
            except broker.Error as exc:
                result = _record(conn, user_id, env, order_id,
                    status="rejected" if exc.rejected and not exc.uncertain else "unknown",
                    error_code="broker_rejected" if exc.rejected and not exc.uncertain else "submission_uncertain")
            except Exception:
                result = _record(conn, user_id, env, order_id, status="unknown", error_code="submission_uncertain")
    except broker.Error:
        raise Error("Native perpetual preflight failed; no order was sent.", 409, "preflight_failed") from None
    except ValueError as exc:
        if isinstance(exc, Error):
            raise
        raise Error("Native perpetual terms could not be revalidated; no order was sent.", 409, "preflight_failed") from None
    return {"order": public_order(result)}


def refresh_order(conn, user_id: int, order_id: int) -> dict:
    env = environment()
    with conn.cursor() as cur:
        row = _owned(cur, user_id, env, order_id)
        if row["claimed_at"] is None or row["status"] in store.TERMINAL:
            return {"order": public_order(row)}
        revision, key_row = _key(cur, user_id, env)
        if revision != row["key_revision_hash"]:
            raise Error("The order belongs to an earlier Kalshi key; restore its connection to reconcile.", 409, "key_changed")
    try:
        with _client(user_id, key_row, env) as client:
            values = _reconcile(client, row, env)
    except (broker.Error, Error, KeyError, ValueError):
        values = dict(status="unknown", error_code="reconciliation_required")
    return {"order": public_order(_record(conn, user_id, env, order_id, **values))}


def cancel_order(conn, user_id: int, order_id: int, body: dict) -> dict:
    env = environment()
    with repo.transaction(conn) as cur:
        store.lock_user(cur, user_id, env)
        row = _owned(cur, user_id, env, order_id)
        _confirmation(body, row)
        if row["status"] in store.TERMINAL:
            return {"order": public_order(row)}
        if row["claimed_at"] is None:
            store.cancel_draft(cur, user_id, env, order_id, expected_version=row["version"])
            return {"order": public_order(_owned(cur, user_id, env, order_id))}
        revision, key_row = _key(cur, user_id, env)
        if revision != row["key_revision_hash"]:
            raise Error("The order's Kalshi key changed; cancellation needs its original connection.", 409, "key_changed")
        if row["broker_order_id"] is None or row["status"] == "cancel_pending" or row["error_code"] == "cancel_uncertain":
            reconcile = True
        else:
            reconcile = not store.begin_cancel(cur, user_id, env, order_id, expected_version=row["version"])
    if reconcile:
        return refresh_order(conn, user_id, order_id)
    try:
        with _client(user_id, key_row, env) as client:
            acknowledgement = client.cancel_order(row["broker_order_id"])
            _fresh(acknowledgement, env)
            if acknowledgement.get("client_order_id", row["client_order_id"]) != row["client_order_id"]:
                raise Error("The native cancel identity is inconsistent.", 409, "invalid_response")
            values = _reconcile(client, row, env)
    except (broker.Error, Error, KeyError, ValueError):
        values = dict(status="unknown", error_code="cancel_uncertain")
    return {"order": public_order(_record(conn, user_id, env, order_id, **values))}


def propose_for_agent(cur, user_id: int, action: dict) -> tuple[str, int]:
    """Caller owns a transaction; create only a proposal, with no broker calls."""
    _require_enabled()
    env = environment()
    if not isinstance(action, dict) or set(action) - (_USER_FIELDS | {"reason"}):
        raise Error("A native perpetual proposal requires direction, contracts, limit and reduce_only.")
    request = _user_request({field: action.get(field) for field in _USER_FIELDS})
    reason = action.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 1000:
        raise Error("Use a short perpetual proposal reason.")
    store.lock_user(cur, user_id, env)
    if not store.get_settings(cur, user_id, env)["enabled"]:
        raise Error("Enable this user's manual perpetual policy before proposing live orders.", 409, "policy_disabled")
    _key(cur, user_id, env)
    proposal_id = repo.create_proposal(cur, user_id, PROPOSAL_KIND,
        "Manual Bitcoin perpetual %s %s contracts at USD %s per contract. %s" %
        (request["side"], request["count"], request["price"], reason),
        payload={"environment": env, "order": request})
    return "Proposed a Bitcoin perpetual order. Review the exact live ticket in Funds and confirm it separately.", proposal_id


def decide_proposal(conn, user_id: int, proposal_id: int, decision: str) -> dict:
    if decision not in ("approve", "reject"):
        raise Error("Choose approve or reject.")
    env = environment()
    with repo.transaction(conn) as cur:
        store.lock_user(cur, user_id, env)
        proposal = _proposal(cur, user_id, proposal_id, env)
        if proposal["status"] != "pending":
            raise Error("This perpetual proposal was already decided.", 409, "proposal_decided")
        if decision == "reject":
            if not repo.decide_proposal(cur, proposal_id, "rejected"):
                raise Error("This perpetual proposal was already decided.", 409, "proposal_decided")
            return {"ok": True, "status": "rejected"}
    return {"ok": True, "review_required": True, "review_url": "/funds?perps_proposal=%d" % proposal_id,
            "message": "Review the exact Bitcoin perpetual ticket in Funds. This action has not submitted an order."}


def agent_context(conn, user_id: int) -> str:
    if not enabled():
        return ""
    with conn.cursor() as cur:
        if not store.get_settings(cur, user_id, environment())["enabled"]:
            return ""
    state = overview(conn, user_id)
    if not state["connected"] or not state["eligible"]:
        return "Bitcoin perpetual live access is unavailable; no live order may be submitted."
    safe = {field: state[field] for field in ("environment", "account", "risk", "market", "quote", "fees", "positions")}
    return ("Native Bitcoin perpetual account context. Every order requires a separate manual Funds confirmation. "
            "Kalshi controls margin/leverage; propose exact native contracts and USD-per-contract limits only. "
            + json.dumps(safe, sort_keys=True, separators=(",", ":")))
