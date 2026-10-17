import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest

from app import billing


def test_usage_cost_at_list_price():
    # Sonnet 4.5 list: $3/1M in, $15/1M out.
    c = billing.usage_cost("us.anthropic.claude-sonnet-4-5-20250929-v1:0", 1_000_000, 1_000_000)
    assert c == Decimal("18.000000")
    # The real session from the demo: 7087 in, 3270 out.
    assert billing.usage_cost("sonnet-4-5", 7087, 3270) == Decimal("0.070311")
    # Haiku is cheaper.
    assert billing.usage_cost("haiku-4-5", 1_000_000, 0) == Decimal("1.000000")
    # Unknown model falls back to the sonnet rate, never zero.
    assert billing.usage_cost("mystery-model", 1_000_000, 0) == Decimal("3.000000")


def test_usage_cost_opus_4_5_fallback(monkeypatch):
    # Registry miss must NOT mis-price a 4-5 string at the old $15/$75: the "opus-4-5" fallback
    # entry precedes "opus-4" so the substring loop can't grab the wrong row first.
    import app.models_catalog as models_catalog
    monkeypatch.setattr(models_catalog, "price_for_model_id", lambda m: None)
    assert billing.usage_cost("something-opus-4-5-weird", 1_000_000, 1_000_000) == Decimal("30.000000")
    # A genuine legacy opus-4 still prices at its own $15/$75.
    assert billing.usage_cost("claude-opus-4-20240101", 1_000_000, 0) == Decimal("15.000000")


def test_is_ready_gates_autonomous_spend(monkeypatch):
    import app.repository as repo
    # Payments off => everything is free, nobody is gated.
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "")
    assert billing.is_ready(None, 1) is True

    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test")
    # No customer / no card on file => not ready (would bill into an uncollectable balance).
    monkeypatch.setattr(repo, "get_stripe_customer", lambda cur, uid: None)
    assert billing.is_ready(None, 1) is False
    monkeypatch.setattr(repo, "get_stripe_customer", lambda cur, uid: {"default_pm_id": None})
    assert billing.is_ready(None, 1) is False
    # Card on file but out of credits => still not ready.
    monkeypatch.setattr(repo, "get_stripe_customer", lambda cur, uid: {"default_pm_id": "pm_1"})
    monkeypatch.setattr(repo, "credit_balance", lambda cur, uid: 0)
    assert billing.is_ready(None, 1) is False
    # Card on file AND credits remain => ready.
    monkeypatch.setattr(repo, "credit_balance", lambda cur, uid: 4.2)
    assert billing.is_ready(None, 1) is True


def test_topup_charge_includes_fee():
    # $20 credits + 5.5% = $21.10 -> 2110 cents.
    assert billing.topup_charge_cents(Decimal("20")) == 2110
    assert billing.topup_charge_cents(Decimal("100")) == 10550


def test_webhook_signature_roundtrip(monkeypatch):
    monkeypatch.setattr(billing, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    payload = json.dumps({"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_1"}}}).encode()
    ts = str(int(time.time()))
    sig = hmac.new(b"whsec_test", ("%s." % ts).encode() + payload, hashlib.sha256).hexdigest()
    event = billing.verify_webhook(payload, "t=%s,v1=%s" % (ts, sig))
    assert event["type"] == "payment_intent.succeeded"
    with pytest.raises(billing.StripeError):
        billing.verify_webhook(payload, "t=%s,v1=deadbeef" % ts)
    with pytest.raises(billing.StripeError):  # stale timestamp
        old = str(int(time.time()) - 10_000)
        sig2 = hmac.new(b"whsec_test", ("%s." % old).encode() + payload, hashlib.sha256).hexdigest()
        billing.verify_webhook(payload, "t=%s,v1=%s" % (old, sig2))


def test_not_configured_without_key(monkeypatch):
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "")
    assert billing.configured() is False
    with pytest.raises(billing.StripeError):
        billing._stripe("GET", "/customers")


def test_stripe_form_flatten():
    out = []
    billing._flatten("metadata", {"user_id": 7, "credits": "20"}, out)
    assert ("metadata[user_id]", "7") in out and ("metadata[credits]", "20") in out


def test_get_or_create_customer_reuses_valid_id(monkeypatch):
    calls = []
    def fake(method, path, params=None, idempotency_key=None):
        calls.append((method, path))
        return {"id": path.rsplit("/", 1)[-1]}  # GET returns the existing customer
    monkeypatch.setattr(billing, "_stripe", fake)
    cid = billing.get_or_create_customer({"id": 1, "email": "a@b.co"}, "cus_live123")
    assert cid == "cus_live123"
    assert calls == [("GET", "/customers/cus_live123")]  # validated, not re-created


def test_get_or_create_customer_recreates_stale_id(monkeypatch):
    # GET on the stale (e.g. test-mode) id 404s; POST makes a fresh one.
    def fake(method, path, params=None, idempotency_key=None):
        if method == "GET":
            raise billing.StripeError("No such customer: 'cus_test_old'")
        return {"id": "cus_live_new"}
    monkeypatch.setattr(billing, "_stripe", fake)
    cid = billing.get_or_create_customer({"id": 1, "email": "a@b.co"}, "cus_test_old")
    assert cid == "cus_live_new"
