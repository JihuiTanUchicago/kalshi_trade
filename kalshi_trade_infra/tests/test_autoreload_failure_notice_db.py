"""A failed auto-reload reaches the user, against a real MySQL: the bell gets one notice per failing
spell (with the customer-safe reason, the credits it tried to add and a link to Billing), Billing
says it by the auto-reload switch until an auto-reload succeeds or a card is saved, and the charges
and the ledger are exactly what they were without the notice. Every notice written is emailed once,
and a throttled failure sends none; the email goes out with Settings' optional-email switch off (it
is account email). Payments are on in-process with every Stripe call stubbed, and boto3 is a stub
that records SES sends. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1)."""
import os
import sys
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


def test_a_failing_card_rings_the_bell_once_and_billing_says_why_until_it_is_fixed(conn, monkeypatch):
    from app import repository as repo
    from app import server
    from app.adapters.stripe import billing

    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_autoreload_failure")
    monkeypatch.setattr(billing, "FREE_BONUS", Decimal("20"))
    monkeypatch.setattr(billing, "_stripe", lambda *a, **k: pytest.fail("a Stripe call escaped the stubs: %r" % (a,)))
    customer = "cus_" + uuid.uuid4().hex[:14]
    monkeypatch.setattr(billing, "get_or_create_customer", lambda user, existing: existing or customer)
    monkeypatch.setattr(billing, "set_default_card", lambda customer_id, pm: None)
    monkeypatch.setattr(billing, "list_cards", lambda customer_id: [{"id": "pm_fail", "brand": "visa", "last4": "0002"}])
    charges, outcome = [], {"error": None}

    def charge(customer_id, pm_id, amount_cents, off_session, idem, metadata=None):
        charges.append((amount_cents, off_session, idem, dict(metadata or {})))
        if outcome["error"]:
            raise outcome["error"]
        return {"id": "pi_" + idem, "status": "succeeded"}

    monkeypatch.setattr(billing, "charge", charge)
    emails = []
    ses = SimpleNamespace(client=lambda service, region_name=None: SimpleNamespace(
        send_email=lambda **kw: emails.append(kw)) if service == "ses" else pytest.fail(service))
    monkeypatch.setitem(sys.modules, "boto3", ses)  # no real SES: every send lands in `emails`

    cur = conn.cursor()
    address = "reloadfail-%s@example.com" % uuid.uuid4().hex[:8]
    user = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, address, "R", None)
    uid = user["id"]
    assert repo.set_email_opt_out(cur, uid, True)  # optional email off: this one is account email

    def ctx(body=None):
        return server.Ctx(conn, repo.get_user(cur, uid), (), {}, body or {}, None)

    def notices():
        cur.execute("SELECT id, kind, body, link, read_at FROM app_notifications WHERE user_id=%s AND kind='reload_failed' "
                    "ORDER BY id", (uid,))
        return cur.fetchall()

    def ledger():
        cur.execute("SELECT kind, amount_usd, stripe_ref FROM app_credit_ledger WHERE user_id=%s ORDER BY id", (uid,))
        return [(r["kind"], Decimal(str(r["amount_usd"])), r["stripe_ref"]) for r in cur.fetchall()]

    assert server.billing_card_added(ctx({"payment_method_id": "pm_fail"})) == {"ok": True}
    server.billing_autoreload(ctx({"on": True, "amount": 25, "threshold": 8}))
    with repo.transaction(conn) as tx:  # spend the welcome credit down to $3, under the $8 threshold
        repo.add_credit(tx, uid, "usage", Decimal("-17"), "Agent usage · fixture")

    # -- the card is declined: every model call of the run tries, and so does the next run --------
    outcome["error"] = billing.StripeError("Your card has expired. (req_Z9 pm_fail)", kind="card_error",
                                           code="expired_card", decline_code="expired_card")
    run_a, run_b = 900000 + uid % 1000, 910000 + uid % 1000
    for run_id in (run_a, run_a, run_b):
        billing.charge_usage(conn, uid, "sonnet-4-6", 1000, 100, run_id)  # never raises, as before
    cents = billing.topup_charge_cents(Decimal("25"))
    assert charges == [(cents, True, "reload-%s-run%s" % (uid, r), {"user_id": uid, "credits": "25.00", "purpose": "autoreload"})
                       for r in (run_a, run_a, run_b)]  # what is charged, how and with which key: unchanged
    kinds = [k for k, _, _ in ledger()]
    assert kinds == ["bonus", "usage", "usage", "usage", "usage"]  # no credit, no new ledger kind
    [note] = notices()
    assert note["link"] == "/billing" and note["read_at"] is None
    assert note["body"] == ("Auto-reload couldn't add $25.00 in credits. That card has expired. Add a current card and try "
                            "again. Research pauses when your credits run out. Update your card on Billing.")
    assert "req_Z9" not in note["body"] and "pm_fail" not in note["body"]
    [mail] = emails  # three failing calls, one notice, one email
    assert mail["Destination"] == {"ToAddresses": [address]}
    text = mail["Message"]["Body"]["Text"]["Data"]
    assert ("Auto-reload couldn't add $25.00 in credits. That card has expired. Add a current card and try again.\n\n"
            "Research pauses when your credits run out.") in text and "/billing\n" in text
    assert not any(s in text for s in ("req_Z9", "pm_fail", customer, "pi_", "reload-%s" % uid, "list price"))
    bell = server.notifications(ctx())
    assert bell["unread"] >= 1 and any(i["kind"] == "reload_failed" and i["link"] == "/billing" for i in bell["items"])

    state = server.billing_state(ctx())
    assert state["reload_failed"]["text"] == "It couldn't add $25.00 in credits. That card has expired. Add a current card and try again."
    # The balance is at the trigger because of it, so /api/me carries it too (the dashboard's Needs you and
    # the research form name the card), and the autopilot poll reads the same text.
    assert server.me(ctx())["reload_failed"] == state["reload_failed"]["text"]
    # The bell read: Billing still says it (it is about the card), and no second notice inside 6 hours.
    server.mark_notifications_read(ctx())
    billing.charge_usage(conn, uid, "sonnet-4-6", 1000, 100, run_b + 1)
    assert len(notices()) == 1 and server.billing_state(ctx())["reload_failed"] is not None
    assert len(emails) == 1  # throttled: no notice, no email
    # Seven hours on, still failing: one more notice.
    cur.execute("UPDATE app_notifications SET created_at=%s, read_at=%s WHERE user_id=%s AND kind='reload_failed'",
                (repo.now_utc() - timedelta(hours=7), repo.now_utc() - timedelta(hours=7), uid))
    billing.charge_usage(conn, uid, "sonnet-4-6", 1000, 100, run_b + 2)
    assert len(notices()) == 2 and len(emails) == 2

    # -- a broken notice write never reaches the charge or the ledger ------------------------------
    before = len(ledger())
    monkeypatch.setattr(repo, "latest_notification", lambda *a: (_ for _ in ()).throw(RuntimeError("db gone")))
    billing.charge_usage(conn, uid, "sonnet-4-6", 1000, 100, run_b + 3)
    assert len(ledger()) == before + 1 and charges[-1][2] == "reload-%s-run%s" % (uid, run_b + 3)
    assert len(emails) == 2  # no notice written, no email
    monkeypatch.undo()  # back to the real repository; re-stub Stripe and SES for what follows
    monkeypatch.setitem(sys.modules, "boto3", ses)
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_autoreload_failure")
    monkeypatch.setattr(billing, "_stripe", lambda *a, **k: pytest.fail("a Stripe call escaped the stubs: %r" % (a,)))
    monkeypatch.setattr(billing, "charge", charge)
    monkeypatch.setattr(billing, "list_cards", lambda customer_id: [])
    monkeypatch.setattr(billing, "set_default_card", lambda customer_id, pm: None)

    # -- the card works again: the auto-reload credits as always and Billing's banner goes ---------
    # (the notices back an hour, so the success is plainly after them: the clock has whole seconds)
    cur.execute("UPDATE app_notifications SET created_at=%s WHERE user_id=%s AND kind='reload_failed'",
                (repo.now_utc() - timedelta(hours=1), uid))
    outcome["error"] = None
    billing.charge_usage(conn, uid, "sonnet-4-6", 1000, 100, run_b + 4)
    assert ledger()[-1] == ("autoreload", Decimal("25"), "pi_reload-%s-run%s" % (uid, run_b + 4))
    assert server.billing_state(ctx())["reload_failed"] is None and len(emails) == 2
    assert server.me(ctx())["reload_failed"] is None

    # -- it fails again, then a new card is saved: the notice is answered, so it goes --------------
    outcome["error"] = billing.StripeError("boom", kind="card_error", code="card_declined", decline_code="do_not_honor")
    with repo.transaction(conn) as tx:
        repo.add_credit(tx, uid, "usage", Decimal("-25"), "Agent usage · fixture")
    billing.charge_usage(conn, uid, "sonnet-4-6", 1000, 100, run_b + 5)
    assert len(notices()) == 3  # the success ended the last spell: told at once, though one is unread
    assert len(emails) == 3 and billing.CARD_DECLINED in emails[-1]["Message"]["Body"]["Text"]["Data"]
    assert billing.CARD_DECLINED in server.billing_state(ctx())["reload_failed"]["text"]
    assert server.billing_card_added(ctx({"payment_method_id": "pm_new"})) == {"ok": True}
    assert not notices() and server.billing_state(ctx())["reload_failed"] is None
    assert server.me(ctx())["reload_failed"] is None
    assert repo.get_stripe_customer(cur, uid)["default_pm_id"] == "pm_new"
