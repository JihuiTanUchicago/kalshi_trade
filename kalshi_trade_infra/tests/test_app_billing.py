import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest

from app.adapters.stripe import billing


def test_usage_cost_applies_margin():
    # The customer is billed list price * USAGE_MARGIN (default 2 = 100% markup).
    assert billing.USAGE_MARGIN == Decimal("2")
    # Sonnet 4.5 list $3/$15 per 1M -> 1M+1M = $18 list -> $36 billed.
    c = billing.usage_cost("us.anthropic.claude-sonnet-4-5-20250929-v1:0", 1_000_000, 1_000_000)
    assert c == Decimal("36.000000")
    # The real session from the demo: 7087 in, 3270 out -> $0.070311 list -> $0.140622 billed.
    assert billing.usage_cost("sonnet-4-5", 7087, 3270) == Decimal("0.140622")
    # Haiku is cheaper: $1 list -> $2 billed.
    assert billing.usage_cost("haiku-4-5", 1_000_000, 0) == Decimal("2.000000")
    # Unknown model falls back to the sonnet rate, never zero: $3 list -> $6 billed.
    assert billing.usage_cost("mystery-model", 1_000_000, 0) == Decimal("6.000000")


def test_usage_margin_is_tunable(monkeypatch):
    # A list-price (1x) run can be restored via env; cost scales linearly with the margin.
    monkeypatch.setattr(billing, "USAGE_MARGIN", Decimal("1"))
    assert billing.usage_cost("haiku-4-5", 1_000_000, 0) == Decimal("1.000000")
    monkeypatch.setattr(billing, "USAGE_MARGIN", Decimal("3"))
    assert billing.usage_cost("haiku-4-5", 1_000_000, 0) == Decimal("3.000000")


def test_usage_cost_opus_4_5_fallback(monkeypatch):
    # Registry miss must NOT mis-price a 4-5 string at the old $15/$75: the "opus-4-5" fallback
    # entry precedes "opus-4" so the substring loop can't grab the wrong row first.
    import app.adapters.llm.models_catalog as models_catalog
    monkeypatch.setattr(models_catalog, "price_for_model_id", lambda m: None)
    # opus-4-5 $5/$25 list -> $30 list -> $60 billed at the 2x margin.
    assert billing.usage_cost("something-opus-4-5-weird", 1_000_000, 1_000_000) == Decimal("60.000000")
    # A genuine legacy opus-4 still prices at its own $15/$75 list -> $30 billed.
    assert billing.usage_cost("claude-opus-4-20240101", 1_000_000, 0) == Decimal("30.000000")


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
    # Headroom gate: a POSITIVE but sub-minimum balance can't start a billed run (post-paid billing
    # would overshoot it into the negative — the -$4.11 bug). Must have >= MIN_RUN_BALANCE.
    monkeypatch.setattr(billing, "MIN_RUN_BALANCE", Decimal("1.00"))
    monkeypatch.setattr(repo, "credit_balance", lambda cur, uid: 0.5)
    assert billing.is_ready(None, 1) is False
    monkeypatch.setattr(repo, "credit_balance", lambda cur, uid: 1.0)
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


def test_billing_copy_does_not_promise_list_price_while_a_markup_applies():
    # usage_cost bills list * USAGE_MARGIN, so customer copy must not say usage costs list price.
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    if billing.USAGE_MARGIN == 1:
        pytest.skip("no markup configured")
    # Both bundles and their page files (app-billing.js holds Tau's Billing page), the shared ones both load too.
    # And the shared core both bundles take their money and count helpers from.
    bundles = sorted(p.name for p in static.glob("app*.js")) + sorted(p.name for p in static.glob("page-*.js")) + ["core.js"]
    assert {"app.js", "app.meridian.js", "app-billing.js", "app.meridian-billing.js", "page-autopilot.js"} <= set(bundles)
    for bundle in bundles:
        src = (static / bundle).read_text()
        assert "list price" not in src, bundle


def test_research_spend_reads_the_ledger_for_research_runs_only():
    # The autopilot panel's week cost is what was debited (kind='usage' ledger rows), scoped by the
    # billed run's kind so chat and autopilot reviews don't count as research. MySQL twin:
    # test_app_engine_db.test_research_spend_is_the_ledger_debits_of_research_runs_only.
    from app import repository as repo

    class Cur:
        def execute(self, sql, params):
            self.sql, self.params = " ".join(sql.split()), params

        def fetchone(self):
            return {"s": Decimal("3.140000")}

    cur = Cur()
    assert repo.research_spent_since(cur, 7, "since") == 3.14
    assert cur.params == (7, "since")
    assert "FROM app_credit_ledger l JOIN app_agent_runs r ON r.id = l.run_id" in cur.sql
    assert "l.kind='usage'" in cur.sql and "l.created_at >= %s" in cur.sql and "r.kind='research'" in cur.sql
    assert "r.direction <> 'random_walk'" in cur.sql  # the seeded demo never ran, as in research_week


def test_runs_spent_is_one_grouped_ledger_read():
    from app import repository as repo

    class Cur:
        executed = []

        def execute(self, sql, params):
            self.executed.append((" ".join(sql.split()), params))

        def fetchall(self):
            return [{"run_id": 9, "s": Decimal("1.250000")}, {"run_id": 4, "s": Decimal("0.010000")}]

    cur = Cur()
    assert repo.runs_spent(cur, 7, []) == {} and cur.executed == []  # nothing listed, no query
    assert repo.runs_spent(cur, 7, [9, 4, 9]) == {9: 1.25, 4: 0.01}
    sql, params = cur.executed[0]
    assert len(cur.executed) == 1 and params == (4, 9, 7)
    assert "WHERE run_id IN (%s,%s) AND kind='usage' AND user_id=%s GROUP BY run_id" in sql
