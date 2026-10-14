"""Credits, usage metering, and Stripe — the money layer.

Model (OpenRouter-style):
  - Credits are real USD, separate from the paper trading balance. New users get
    a one-time FREE_BONUS of free credits.
  - Agent usage (research + chat) is billed per token at Anthropic's published
    list price for the model used (`PRICES`), deducted from the balance.
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

FREE_BONUS = Decimal(os.getenv("TAU_FREE_CREDITS", "100"))
TOPUP_FEE = Decimal(os.getenv("TAU_TOPUP_FEE", "0.055"))  # 5.5% on credit purchases
AUTORELOAD_THRESHOLD = Decimal("5")   # default + floor for "reload when balance drops to Y"
AUTORELOAD_AMOUNT = Decimal("20")     # default + floor for "reload X dollars"
MIN_TOPUP = Decimal("5")
MAX_TOPUP = Decimal("1000")
CENT = Decimal("0.01")

# Anthropic public list price, USD per 1,000,000 tokens (input, output). What we
# BILL the user; our Bedrock cost is covered by AWS credits (that gap is margin).
PRICES: Dict[str, Tuple[Decimal, Decimal]] = {
    "sonnet-4-5": (Decimal("3"), Decimal("15")),
    "sonnet-4": (Decimal("3"), Decimal("15")),
    "sonnet-5": (Decimal("3"), Decimal("15")),
    "haiku-4-5": (Decimal("1"), Decimal("5")),
    "haiku-5": (Decimal("1"), Decimal("5")),
    "opus-4": (Decimal("15"), Decimal("75")),
    "opus-5": (Decimal("15"), Decimal("75")),
    "3-5-sonnet": (Decimal("3"), Decimal("15")),
    "3-5-haiku": (Decimal("0.8"), Decimal("4")),
}
_DEFAULT_PRICE = (Decimal("3"), Decimal("15"))


class StripeError(RuntimeError):
    pass


def configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


def _price_for(model: str) -> Tuple[Decimal, Decimal]:
    for key, price in PRICES.items():
        if key in (model or ""):
            return price
    return _DEFAULT_PRICE


def usage_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """USD to bill for one agent call, at list price. 6-dp precision."""
    pin, pout = _price_for(model)
    cost = (Decimal(int(input_tokens)) * pin + Decimal(int(output_tokens)) * pout) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


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
        raise StripeError(err.get("message") or "Stripe error %s" % resp.status_code)
    return body


def get_or_create_customer(user: Dict, existing_id: Optional[str]) -> str:
    if existing_id:
        return existing_id
    cust = _stripe("POST", "/customers", {
        "email": user["email"], "name": user.get("name") or "", "metadata": {"user_id": user["id"]},
    }, idempotency_key="cust-%s" % user["id"])
    return cust["id"]


def create_setup_intent(customer_id: str) -> Dict:
    # automatic_payment_methods lets the Payment Element offer Apple Pay / Google
    # Pay alongside card; allow_redirects=never keeps it to no-redirect methods so
    # confirmSetup needs no return_url.
    si = _stripe("POST", "/setup_intents", {
        "customer": customer_id, "usage": "off_session",
        "automatic_payment_methods": {"enabled": "true", "allow_redirects": "never"},
    })
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
    pi = charge(cust["stripe_customer_id"], cust["default_pm_id"], topup_charge_cents(amount),
                off_session=True, idem=idem,
                metadata={"user_id": user_id, "credits": str(amount), "purpose": "autoreload"})
    if pi["status"] != "succeeded":
        print("[billing] auto-reload PI %s status=%s" % (pi["id"], pi["status"]), flush=True)
        return False
    with repo.transaction(conn) as tx:
        added = repo.add_credit(tx, user_id, "autoreload", amount,
                                "Auto-reload $%s" % amount, stripe_ref=pi["id"])
    return added
