"""Credits, usage metering, and Stripe — the money layer.

Model (OpenRouter-style):
  - Credits are real USD, separate from the paper trading balance. New users get
    a one-time FREE_BONUS of free credits.
  - Agent usage (research + chat) is billed per token at the model's published
    list price (`PRICES`) times USAGE_MARGIN, deducted from the balance.
  - Topping up charges the card for the credits plus a TOPUP_FEE (our revenue).
  - When the balance falls to AUTORELOAD_THRESHOLD or below, a saved card is
    charged off-session to add AUTORELOAD_AMOUNT (if auto-reload is on).

Stripe is called over plain HTTPS (form-encoded) so there's no SDK to install on
the box's Python 3.9. Every money write is idempotent: Stripe PaymentIntents use
an idempotency key, and credit rows that come from Stripe carry a unique
`stripe_ref` so a replayed webhook can't double-credit.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple

import requests

STRIPE_API = "https://api.stripe.com/v1"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
# A Stripe payment-method configuration (child of the account default) with Link
# disabled and card + Apple Pay + Google Pay enabled, so the Payment Element stays
# compact. Set via Parameter Store; falls back to card-only when unset.
STRIPE_PAYMENT_CONFIG = os.getenv("STRIPE_PAYMENT_CONFIG", "")

FREE_BONUS = Decimal(os.getenv("TAU_FREE_CREDITS", "20"))
TOPUP_FEE = Decimal(os.getenv("TAU_TOPUP_FEE", "0.055"))  # 5.5% on credit purchases
# A research/review run bills POST-PAID on actual tokens, so a run started on a near-zero balance
# overshoots into the negative by roughly one chunk's cost (observed: a user at -$4.11). Require this
# much headroom to START a billed run, so a balance can't be driven meaningfully negative. Chat (one
# cheap call) keeps the plain >0 gate. Env-tunable; ~one small session's worth.
MIN_RUN_BALANCE = Decimal(os.getenv("TAU_MIN_RUN_BALANCE", "1.00"))
AUTORELOAD_THRESHOLD = Decimal("5")   # default + floor for "reload when balance drops to Y"
AUTORELOAD_AMOUNT = Decimal("20")     # default + floor for "reload X dollars"
MIN_TOPUP = Decimal("5")
MAX_TOPUP = Decimal("1000")
CENT = Decimal("0.01")

# Anthropic public list price, USD per 1,000,000 tokens (input, output). The REFERENCE rate;
# the customer is billed list * USAGE_MARGIN (see below). Our Bedrock cost is covered by AWS
# credits, so list-vs-cost is one margin and USAGE_MARGIN is the markup on top of list.
# Matched by substring in insertion order, so every point release MUST precede its bare prefix:
# "opus-4" is a substring of "opus-4-5" and "opus-5" of "opus-5-5", so a bare entry first would
# mis-price the newer model on a registry miss.
PRICES: Dict[str, Tuple[Decimal, Decimal]] = {
    "sonnet-5-5": (Decimal("2"), Decimal("10")),
    "sonnet-5": (Decimal("2"), Decimal("10")),
    "sonnet-4-6": (Decimal("3"), Decimal("15")),
    "sonnet-4-5": (Decimal("3"), Decimal("15")),
    "sonnet-4": (Decimal("3"), Decimal("15")),
    "haiku-5-5": (Decimal("0.1"), Decimal("0.5")),
    "haiku-4-5": (Decimal("1"), Decimal("5")),
    "opus-5-5": (Decimal("4"), Decimal("20")),
    "opus-5": (Decimal("5"), Decimal("25")),
    "opus-4-8": (Decimal("5"), Decimal("25")),
    "opus-4-7": (Decimal("5"), Decimal("25")),
    "opus-4-6": (Decimal("5"), Decimal("25")),
    "opus-4-5": (Decimal("5"), Decimal("25")),
    "opus-4": (Decimal("15"), Decimal("75")),
    "fable-5": (Decimal("10"), Decimal("50")),
    "3-5-sonnet": (Decimal("3"), Decimal("15")),
    "3-5-haiku": (Decimal("0.8"), Decimal("4")),
}
_DEFAULT_PRICE = (Decimal("3"), Decimal("15"))

# Markup charged to the customer ON TOP of the list price, to cover storage, infra,
# orchestration and the rest. 1 = list price, 2 = double (a 100% margin). Env-tunable.
USAGE_MARGIN = Decimal(os.getenv("TAU_USAGE_MARGIN", "2"))


class StripeError(RuntimeError):
    """A Stripe call that failed. The message is Stripe's own text (or the network error) and is for
    the server log only: it can name request parameters, object ids and hosts. ``kind``, ``code`` and
    ``decline_code`` are Stripe's error fields, which customer_message() turns into words a user reads."""

    def __init__(self, message: str, kind: str = "", code: str = "", decline_code: str = ""):
        super().__init__(message)
        self.kind, self.code, self.decline_code = kind, code, decline_code


# A declined card in the user's words, by Stripe's decline_code or code. Anything not listed reads as a
# plain decline. Stripe's own message text is never shown.
_CARD_DECLINE_COPY = {
    "insufficient_funds": "Your card was declined for insufficient funds. Try another card.",
    "expired_card": "That card has expired. Add a current card and try again.",
    "incorrect_cvc": "The card's security code didn't match. Add the card again with the right code.",
    "invalid_cvc": "The card's security code didn't match. Add the card again with the right code.",
    "incorrect_number": "The card number isn't right. Add the card again.",
    "invalid_number": "The card number isn't right. Add the card again.",
    "card_velocity_exceeded": "Your card is over its spending limit for now. Try another card, or ask your bank.",
    "authentication_required": "Your bank wants to approve this charge itself, which can't be done here. "
                               "Try another card.",
    "processing_error": "The card couldn't be processed just now. Try again in a minute.",
}
CARD_DECLINED = "Your card was declined. Try another card, or ask your bank why."


def customer_message(e: StripeError, fallback: str) -> str:
    """What a user reads for a failed Stripe call: a declined card in plain words, anything else (an
    outage, a stale id, a bad request) the caller's ``fallback`` saying what to do next."""
    if e.kind == "card_error":
        return _CARD_DECLINE_COPY.get(e.decline_code) or _CARD_DECLINE_COPY.get(e.code) or CARD_DECLINED
    return fallback


def configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


_UNREAD = object()


class Reads:
    """The user's saved Stripe customer row and credit balance, each read at most once. One request
    derives several fields from them (/api/me: needs_card, auto_reload and credit_balance; the
    autopilot poll: billing_blocked, billing_reason and credits_low_days), and each field used to
    re-read them. Make one per request: it never sees a write made after its first read."""

    def __init__(self, cur, user_id: int):
        self.cur, self.user_id = cur, user_id
        self._customer = self._balance = _UNREAD

    def customer(self) -> Optional[Dict]:
        if self._customer is _UNREAD:
            from app import repository as repo  # local: billing <-> repository would be a circular import
            self._customer = repo.get_stripe_customer(self.cur, self.user_id)
        return self._customer

    def balance(self) -> float:
        if self._balance is _UNREAD:
            from app import repository as repo
            self._balance = repo.credit_balance(self.cur, self.user_id)
        return self._balance


def is_ready(cur, user_id: int, reads: Optional[Reads] = None) -> bool:
    """True when this user may be billed for an agent run: payments off (everything is free) OR a
    card is on file AND credits remain. The plain-predicate twin of server._require_billing_ready,
    for AUTONOMOUS paths (the autopilot heartbeat) that have no request to raise a 402 into — they
    skip a non-ready user instead of billing Opus runs into an uncollectable negative balance.
    Strictly a spend GUARD: it only ever PREVENTS a run, never enables one. `reads` lets a request
    that shows these figures share its reads with the check; the rule is the same either way."""
    if not configured():
        return True
    reads = reads or Reads(cur, user_id)
    cust = reads.customer()
    if not (cust and cust.get("default_pm_id")):
        return False
    # Headroom, not just >0: an autonomous research/review run would otherwise overshoot a near-zero
    # balance into the negative (post-paid billing). Require one session's worth before acting.
    return Decimal(str(reads.balance())) >= MIN_RUN_BALANCE


def _price_for(model: str) -> Tuple[Decimal, Decimal]:
    # A user-chosen model is billed at its EXACT registry price (keyed on the
    # invokable modelId); the substring table below is the fallback for legacy
    # model strings and anything not in the registry.
    from app.adapters.llm import models_catalog
    exact = models_catalog.price_for_model_id(model)
    if exact is not None:
        return exact
    for key, price in PRICES.items():
        if key in (model or ""):
            return price
    return _DEFAULT_PRICE


def usage_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """USD to bill for one agent call = list price * USAGE_MARGIN. 6-dp precision."""
    pin, pout = _price_for(model)
    list_cost = (Decimal(int(input_tokens)) * pin + Decimal(int(output_tokens)) * pout) / Decimal(1_000_000)
    return (list_cost * USAGE_MARGIN).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def topup_charge_cents(credits: Decimal) -> int:
    """What the card is charged (credits + fee), in cents."""
    total = (credits * (Decimal(1) + TOPUP_FEE)).quantize(CENT, rounding=ROUND_HALF_UP)
    return int(total * 100)


# -- Stripe over HTTPS -----------------------------------------------------------


def _flatten(prefix: str, value, out: List[Tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten("%s[%s]" % (prefix, k), v, out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _flatten("%s[%d]" % (prefix, i), v, out)
    elif value is not None:
        out.append((prefix, str(value)))


def _stripe(method: str, path: str, params: Optional[Dict] = None, idempotency_key: Optional[str] = None) -> Dict:
    if not STRIPE_SECRET_KEY:
        raise StripeError("Stripe is not configured on the server.")
    data: List[Tuple[str, str]] = []
    for k, v in (params or {}).items():
        _flatten(k, v, data)
    headers = {"Authorization": "Bearer " + STRIPE_SECRET_KEY}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    url = STRIPE_API + path
    try:
        if method == "GET":
            resp = requests.get(url, params=data, headers=headers, timeout=25)
        else:
            resp = requests.post(url, data=data, headers=headers, timeout=25)
    except requests.RequestException as e:
        raise StripeError("Could not reach Stripe: %s" % e)
    body = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        err = (body.get("error") or {})
        raise StripeError(err.get("message") or "Stripe error %s" % resp.status_code, kind=err.get("type") or "",
                          code=err.get("code") or "", decline_code=err.get("decline_code") or "")
    return body


def get_or_create_customer(user: Dict, existing_id: Optional[str]) -> str:
    if existing_id:
        try:
            cust = _stripe("GET", "/customers/" + existing_id)
            if not cust.get("deleted"):
                return existing_id
        except StripeError:
            pass  # stale id (e.g. test->live mode switch, or deleted) -> make a fresh one
    cust = _stripe("POST", "/customers", {
        "email": user["email"], "name": user.get("name") or "", "metadata": {"user_id": user["id"]},
    }, idempotency_key="cust-%s" % user["id"])
    return cust["id"]


def create_setup_intent(customer_id: str) -> Dict:
    # Card only. Apple Pay / Google Pay still surface on top of the card method
    # (once the domain is registered + the browser supports them); this keeps the
    # Payment Element from listing every account-enabled method (BLIK, Pix, …).
    params = {"customer": customer_id, "usage": "off_session"}
    if STRIPE_PAYMENT_CONFIG:
        params["payment_method_configuration"] = STRIPE_PAYMENT_CONFIG  # card + wallets, no Link
    else:
        params["payment_method_types"] = ["card"]
    si = _stripe("POST", "/setup_intents", params)
    return {"client_secret": si["client_secret"]}


def list_cards(customer_id: str) -> List[Dict]:
    pms = _stripe("GET", "/payment_methods", {"customer": customer_id, "type": "card"}).get("data", [])
    out = []
    for pm in pms:
        card = pm.get("card") or {}
        out.append({"id": pm["id"], "brand": card.get("brand"), "last4": card.get("last4"),
                    "exp_month": card.get("exp_month"), "exp_year": card.get("exp_year")})
    return out


def set_default_card(customer_id: str, pm_id: str) -> None:
    _stripe("POST", "/customers/" + customer_id, {"invoice_settings": {"default_payment_method": pm_id}})


def detach_card(pm_id: str) -> None:
    _stripe("POST", "/payment_methods/%s/detach" % pm_id)


def charge(customer_id: str, pm_id: str, amount_cents: int, off_session: bool, idem: str,
           metadata: Optional[Dict] = None) -> Dict:
    """Confirm a PaymentIntent now. Returns {status, id}. Raises on hard failure."""
    pi = _stripe("POST", "/payment_intents", {
        "amount": amount_cents, "currency": "usd", "customer": customer_id, "payment_method": pm_id,
        "confirm": "true", "off_session": "true" if off_session else "false",
        # Card-only, no redirect methods -> no return_url needed for off-session charges.
        "automatic_payment_methods": {"enabled": "true", "allow_redirects": "never"},
        "description": "Tau credits", "metadata": metadata or {},
    }, idempotency_key=idem)
    return {"id": pi["id"], "status": pi["status"]}


def verify_webhook(payload: bytes, sig_header: str, tolerance: int = 300) -> Dict:
    """Verify a Stripe webhook signature (t=...,v1=...) and return the event JSON."""
    import json

    if not STRIPE_WEBHOOK_SECRET:
        raise StripeError("Webhook secret not configured.")
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    ts, v1 = parts.get("t"), parts.get("v1")
    if not ts or not v1:
        raise StripeError("Bad signature header.")
    if abs(time.time() - int(ts)) > tolerance:
        raise StripeError("Signature timestamp outside tolerance.")
    signed = ("%s." % ts).encode() + payload
    expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, v1):
        raise StripeError("Signature mismatch.")
    return json.loads(payload)


# -- orchestration (credits <-> usage <-> auto-reload) ---------------------------


def charge_usage(conn, user_id: int, model: str, input_tokens: int, output_tokens: int, run_id: Optional[int]) -> None:
    """Deduct the cost of one agent call from the user's credits, then auto-reload
    if the balance has fallen to the threshold. Best-effort: never raises into the
    agent path (a metering failure must not lose the user's research)."""
    from app import repository as repo

    cost = usage_cost(model, input_tokens, output_tokens)
    if cost <= 0:
        return
    try:
        with repo.transaction(conn) as cur:
            repo.add_credit(cur, user_id, "usage", -cost, "Agent usage · %s" % model, run_id=run_id)
    except Exception as e:
        print("[billing] usage charge failed for user %s: %r" % (user_id, e), flush=True)
        return
    try:
        auto_reload(conn, user_id, trigger="run%s" % (run_id or "x"))
    except Exception as e:
        print("[billing] auto-reload failed for user %s: %r" % (user_id, e), flush=True)


def auto_reload(conn, user_id: int, trigger: str) -> bool:
    """If auto-reload is on and the balance has fallen to the user's threshold,
    charge the saved card off-session to add the user's reload amount. Returns True
    if credits were added. Idempotent per trigger."""
    from app import repository as repo

    cur = conn.cursor()
    cust = repo.get_stripe_customer(cur, user_id)
    if not cust or not cust.get("auto_reload") or not cust.get("default_pm_id") or not configured():
        return False
    threshold = max(AUTORELOAD_THRESHOLD, Decimal(str(cust.get("reload_threshold") or AUTORELOAD_THRESHOLD)))
    amount = max(AUTORELOAD_AMOUNT, Decimal(str(cust.get("reload_amount") or AUTORELOAD_AMOUNT)))
    if Decimal(str(repo.credit_balance(cur, user_id))) > threshold:
        return False
    idem = "reload-%s-%s" % (user_id, trigger)
    try:
        pi = charge(cust["stripe_customer_id"], cust["default_pm_id"], topup_charge_cents(amount),
                    off_session=True, idem=idem,
                    metadata={"user_id": user_id, "credits": str(amount), "purpose": "autoreload"})
    except StripeError as e:
        reload_failed_notice(conn, user_id, amount, error=e)
        raise  # unchanged: charge_usage logs it, as before
    if pi["status"] != "succeeded":
        print("[billing] auto-reload PI %s status=%s" % (pi["id"], pi["status"]), flush=True)
        if pi["status"] != "processing":  # processing can still succeed, and the webhook credits it then
            reload_failed_notice(conn, user_id, amount, status=pi["status"])
        return False
    with repo.transaction(conn) as tx:
        added = repo.add_credit(tx, user_id, "autoreload", amount,
                                "Auto-reload $%s" % amount, stripe_ref=pi["id"])
    return added


# -- telling the user an auto-reload failed -------------------------------------------------------
# A failed auto-reload used to reach only the server log, and research then paused at the floor with
# nothing saying why. It rings the bell instead: one line with the customer-safe reason (never
# Stripe's own text), the credits it tried to add and a link to Billing, which shows the same as a
# banner until a later auto-reload succeeds or the user saves a card.
RELOAD_FAILED_KIND = "reload_failed"
# A failing card fails again on every model call of the run (Stripe replays the same idempotency key)
# and on every later run: at most one notice per user per RELOAD_FAILED_EVERY_HOURS, and never a
# second while one is still unread. The window alone would stack a fresh unread line every 6 hours for
# a user who is away; the unread rule alone would re-ring on the next model call after they open the
# bell. A successful auto-reload ends the spell, so the next failure is told at once.
RELOAD_FAILED_EVERY_HOURS = 6
RELOAD_FAILED_FALLBACK = "The charge couldn't be completed just now."
_RELOAD_FAILED_TAIL = " Research pauses when your credits run out. Update your card on Billing."


def reload_failed_reason(error: Optional[StripeError] = None, status: str = "") -> str:
    """Why an auto-reload failed, in the user's words: a declined card by Stripe's codes, a charge the
    bank wants to approve itself, or RELOAD_FAILED_FALLBACK. Never Stripe's own message."""
    if error is not None:
        return customer_message(error, RELOAD_FAILED_FALLBACK)
    if status == "requires_action":
        return _CARD_DECLINE_COPY["authentication_required"]
    return CARD_DECLINED if status == "requires_payment_method" else RELOAD_FAILED_FALLBACK


def reload_failed_body(amount, reason: str) -> str:
    return "Auto-reload couldn't add $%s in credits. %s%s" % (
        Decimal(str(amount)).quantize(CENT, rounding=ROUND_HALF_UP), reason, _RELOAD_FAILED_TAIL)


def reload_failed_text(body: str) -> str:
    """A failure notice as Billing's banner says it, under its "Auto-reload failed" heading: the bell
    line without its pointer to Billing, starting "It couldn't add $X in credits."."""
    text = body[:-len(_RELOAD_FAILED_TAIL)] if body.endswith(_RELOAD_FAILED_TAIL) else body
    return "It " + text[len("Auto-reload "):] if text.startswith("Auto-reload couldn't") else text


def reload_failed_notice(conn, user_id: int, amount, error: Optional[StripeError] = None, status: str = "") -> bool:
    """Ring the bell for a failed auto-reload, throttled (RELOAD_FAILED_EVERY_HOURS). Its own
    autocommit statements on a fresh cursor, never inside the charge's transaction, and every error is
    logged and swallowed: telling the user can never change, break or roll back the charge path.
    True when a notice was added."""
    try:
        from datetime import timedelta

        from app import repository as repo

        cur = conn.cursor()
        last = repo.latest_notification(cur, user_id, RELOAD_FAILED_KIND)
        # The bell marks every notice read at once, so the newest one stands for all of them. An
        # auto-reload that succeeded since it ended that spell: a new failure is news again.
        if last and (last["read_at"] is None
                     or last["created_at"] >= repo.now_utc() - timedelta(hours=RELOAD_FAILED_EVERY_HOURS)):
            ok_at = repo.last_credit_at(cur, user_id, "autoreload")
            if ok_at is None or ok_at < last["created_at"]:
                return False
        reason = reload_failed_reason(error, status)
        repo.add_notification(cur, user_id, RELOAD_FAILED_KIND, reload_failed_body(amount, reason), "/billing")
    except Exception as e:  # noqa: BLE001 - the notice must never reach the charge path
        print("[billing] auto-reload failure notice not written for user %s: %r" % (user_id, e), flush=True)
        return False
    reload_failed_email(conn, user_id, amount, reason)
    return True


def reload_failed_email(conn, user_id: int, amount, reason: str) -> bool:
    """Email the user the notice reload_failed_notice just wrote, so someone away from the bell learns
    research is about to pause. Called only after a notice is written, so it keeps the notice's
    throttle: one email per notice. An account email, sent whatever Settings' optional-email switch
    says (app/adapters/db/email_prefs_repository.py). Runs after the notice's autocommit write, outside
    any transaction, and every error is logged and swallowed: it can never change the charge path.
    True when SES accepted it."""
    try:
        from app import repository as repo
        from app.adapters.ses import notify

        user = repo.get_user(conn.cursor(), user_id) or {}
        if not user.get("email"):
            return False
        return bool(notify.reload_failed_email(user["email"], user.get("name"),
                                               Decimal(str(amount)).quantize(CENT, rounding=ROUND_HALF_UP), reason))
    except Exception as e:  # noqa: BLE001 - the email must never reach the charge path
        print("[billing] auto-reload failure email not sent for user %s: %r" % (user_id, e), flush=True)
        return False
