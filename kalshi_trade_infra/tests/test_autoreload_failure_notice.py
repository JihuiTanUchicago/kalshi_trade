"""A failed auto-reload reaches the user: one bell notice (throttled) with the customer-safe reason,
the credits it tried to add and a link to Billing, and a banner on Billing until an auto-reload
succeeds or a card is saved. What is charged, when, with which idempotency key, and what the ledger
records are unchanged, and nothing about the notice can break or roll back the charge path. Each
notice written is also emailed once (an account email, whatever Settings' optional-email switch says),
through a stubbed boto3 with sockets blocked. MySQL twin: test_autoreload_failure_notice_db.py."""
import socket
import sys
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.adapters.stripe import billing
from app.web.routes import billing as billing_routes

UID = 7
NOW = billing_routes.repo.now_utc()


class Conn:
    def cursor(self):
        return object()


@pytest.fixture
def world(monkeypatch):
    """A carded user with auto-reload on, at $3 (under the $5 threshold), payments on in-process.
    Every Stripe call is stubbed; notices land in a list."""
    from app import repository as repo

    w = SimpleNamespace(notes=[], credits=[], charges=[], charge_result=None, charge_error=None, ok_at=None,
                        emails=[], ses_error=None)
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("a socket was opened: %r" % (a,)))

    def send_email(**kw):
        if w.ses_error:
            raise w.ses_error
        w.emails.append(kw)

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda service, region_name=None: (
        SimpleNamespace(send_email=send_email) if service == "ses" else pytest.fail(service))))
    monkeypatch.setattr(repo, "get_user", lambda cur, uid: {"id": uid, "email": "away@example.com", "name": "Ada"})
    # Account email: the optional-email switch is never read for it.
    monkeypatch.setattr(repo, "optional_email_address", lambda *a: pytest.fail("read the optional-email switch"))
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_autoreload_failure")
    monkeypatch.setattr(billing, "_stripe", lambda *a, **k: pytest.fail("a Stripe call escaped the stubs"))
    monkeypatch.setattr(repo, "get_stripe_customer", lambda cur, uid: {
        "stripe_customer_id": "cus_fixture", "default_pm_id": "pm_fixture", "auto_reload": 1,
        "reload_amount": Decimal("25.00"), "reload_threshold": Decimal("5.00")})
    monkeypatch.setattr(repo, "credit_balance", lambda cur, uid: 3.0)

    def charge(customer_id, pm_id, amount_cents, off_session, idem, metadata=None):
        w.charges.append({"customer": customer_id, "pm": pm_id, "cents": amount_cents, "off_session": off_session,
                          "idem": idem, "metadata": metadata})
        if w.charge_error:
            raise w.charge_error
        return w.charge_result or {"id": "pi_" + idem, "status": "succeeded"}

    monkeypatch.setattr(billing, "charge", charge)
    monkeypatch.setattr(repo, "add_credit", lambda cur, uid, kind, amount, memo, stripe_ref=None, run_id=None:
                        w.credits.append((kind, amount, stripe_ref)) or True)

    class Tx:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(repo, "transaction", lambda conn: Tx())

    def latest(cur, uid, kind):
        mine = [n for n in w.notes if n["kind"] == kind]
        return mine[-1] if mine else None

    monkeypatch.setattr(repo, "latest_notification", latest)
    monkeypatch.setattr(repo, "last_credit_at", lambda cur, uid, kind: w.ok_at if kind == "autoreload" else pytest.fail(kind))
    monkeypatch.setattr(repo, "add_notification", lambda cur, uid, kind, body, link=None: w.notes.append(
        {"kind": kind, "body": body, "link": link, "created_at": NOW, "read_at": None}) or len(w.notes))
    return w


def _declined(decline_code="insufficient_funds"):
    return billing.StripeError("Your card has insufficient funds. req_abc123 pm_fixture", kind="card_error",
                               code="card_declined", decline_code=decline_code)


def test_a_declined_auto_reload_rings_the_bell_with_the_reason_and_still_raises_as_before(world):
    world.charge_error = _declined()
    with pytest.raises(billing.StripeError) as raised:
        billing.auto_reload(Conn(), UID, trigger="run42")
    assert raised.value is world.charge_error  # the same error reaches charge_usage, which logs it
    # The charge itself is what it always was: the reload amount plus the fee, off-session, keyed by trigger.
    assert world.charges == [{"customer": "cus_fixture", "pm": "pm_fixture", "cents": billing.topup_charge_cents(Decimal("25")),
                              "off_session": True, "idem": "reload-7-run42",
                              "metadata": {"user_id": UID, "credits": "25.00", "purpose": "autoreload"}}]
    assert world.credits == []  # nothing credited, no new ledger kind
    [note] = world.notes
    assert note["kind"] == "reload_failed" and note["link"] == "/billing"
    assert note["body"] == ("Auto-reload couldn't add $25.00 in credits. Your card was declined for insufficient funds. "
                            "Try another card. Research pauses when your credits run out. Update your card on Billing.")
    assert "req_abc123" not in note["body"] and "pm_fixture" not in note["body"]  # never Stripe's own text
    assert "list price" not in note["body"]
    # One email for the one notice: the same words, a link to Billing, nothing internal.
    [mail] = world.emails
    assert mail["Destination"] == {"ToAddresses": ["away@example.com"]}
    assert mail["Message"]["Subject"]["Data"] == "Tau auto-reload couldn't add credits"
    text = mail["Message"]["Body"]["Text"]["Data"]
    assert text.startswith("Hi Ada,\n\nAuto-reload couldn't add $25.00 in credits. Your card was declined for "
                           "insufficient funds. Try another card.\n\nResearch pauses when your credits run out.")
    from app.adapters.ses import notify
    assert "  %s/billing\n" % notify.PUBLIC_URL in text
    for internal in ("req_abc123", "pm_fixture", "cus_fixture", "pi_", "reload-7", "list price", "margin", "user_id"):
        assert internal not in text.lower()


def test_an_outage_says_the_charge_did_not_complete_never_the_upstream_text(world):
    world.charge_error = billing.StripeError("Could not reach Stripe: HTTPSConnectionPool(host='api.stripe.com')")
    with pytest.raises(billing.StripeError):
        billing.auto_reload(Conn(), UID, trigger="run1")
    assert "The charge couldn't be completed just now." in world.notes[0]["body"]
    assert "api.stripe.com" not in world.notes[0]["body"] and "HTTPS" not in world.notes[0]["body"]


@pytest.mark.parametrize("status,reason", [
    ("requires_action", billing._CARD_DECLINE_COPY["authentication_required"]),
    ("requires_payment_method", billing.CARD_DECLINED),
    ("canceled", billing.RELOAD_FAILED_FALLBACK),
])
def test_a_charge_that_did_not_succeed_rings_the_bell_and_returns_false_as_before(world, status, reason):
    world.charge_result = {"id": "pi_x", "status": status}
    assert billing.auto_reload(Conn(), UID, trigger="run2") is False
    assert world.credits == [] and len(world.charges) == 1
    assert reason in world.notes[0]["body"]


def test_a_processing_charge_is_not_a_failure(world):
    world.charge_result = {"id": "pi_x", "status": "processing"}  # the webhook credits it if it succeeds
    assert billing.auto_reload(Conn(), UID, trigger="run3") is False
    assert world.notes == [] and world.emails == []


def test_a_successful_auto_reload_writes_no_notice(world):
    assert billing.auto_reload(Conn(), UID, trigger="run4") is True
    assert world.credits == [("autoreload", Decimal("25.00"), "pi_reload-7-run4")] and world.notes == []
    assert world.emails == []


def test_one_notice_while_the_card_keeps_failing(world):
    world.charge_error = _declined()
    for trigger in ("run5", "run5", "run6"):  # every model call of a run, then the next run
        with pytest.raises(billing.StripeError):
            billing.auto_reload(Conn(), UID, trigger=trigger)
    assert len(world.charges) == 3 and len(world.notes) == 1  # charges unchanged, one notice
    assert len(world.emails) == 1  # and one email: it is sent only for a notice written
    # Read in the bell, but within the window: still one.
    world.notes[0]["read_at"] = NOW
    with pytest.raises(billing.StripeError):
        billing.auto_reload(Conn(), UID, trigger="run7")
    assert len(world.notes) == 1
    # Unread but old: still one (never two unread).
    world.notes[0].update(read_at=None, created_at=NOW - timedelta(hours=30))
    with pytest.raises(billing.StripeError):
        billing.auto_reload(Conn(), UID, trigger="run8")
    assert len(world.notes) == 1 and len(world.emails) == 1
    # Read and older than the window: the next failure rings again.
    world.notes[0].update(read_at=NOW - timedelta(hours=7), created_at=NOW - timedelta(hours=7))
    with pytest.raises(billing.StripeError):
        billing.auto_reload(Conn(), UID, trigger="run9")
    assert len(world.notes) == 2 and len(world.emails) == 2
    # A successful auto-reload since the last notice ends the spell: the next failure is told at once.
    world.ok_at = NOW + timedelta(seconds=1)
    with pytest.raises(billing.StripeError):
        billing.auto_reload(Conn(), UID, trigger="run9b")
    assert len(world.notes) == 3 and len(world.emails) == 3


def test_a_broken_notice_write_never_reaches_the_charge_path(world, monkeypatch, capsys):
    from app import repository as repo

    monkeypatch.setattr(repo, "latest_notification", lambda *a: (_ for _ in ()).throw(RuntimeError("db gone")))
    world.charge_error = _declined()
    with pytest.raises(billing.StripeError) as raised:
        billing.auto_reload(Conn(), UID, trigger="run10")
    assert raised.value is world.charge_error  # the charge's own error, not the notice's
    world.charge_error, world.charge_result = None, {"id": "pi_y", "status": "requires_action"}
    assert billing.auto_reload(Conn(), UID, trigger="run11") is False
    assert "notice not written" in capsys.readouterr().out
    assert world.emails == []  # no notice, no email
    # And charge_usage still swallows the reload failure, as before: research keeps its result.
    monkeypatch.setattr(billing, "usage_cost", lambda *a: Decimal("0.5"))
    world.charge_error = _declined()
    billing.charge_usage(Conn(), UID, "m", 10, 10, run_id=12)
    assert ("usage", Decimal("-0.5"), None) in world.credits


def test_a_failed_email_never_reaches_the_charge_path_or_the_notice(world, monkeypatch, capsys):
    from app import repository as repo

    # SES refuses (sandbox, outage): logged by the sender, the notice stands, the charge error is unchanged.
    world.ses_error, world.charge_error = RuntimeError("MessageRejected: not verified"), _declined()
    with pytest.raises(billing.StripeError) as raised:
        billing.auto_reload(Conn(), UID, trigger="run20")
    assert raised.value is world.charge_error and len(world.notes) == 1 and world.emails == []
    assert "SES send to away@example.com failed" in capsys.readouterr().out
    # The address read breaks: logged and swallowed, the notice still counts as written.
    world.notes.clear()
    monkeypatch.setattr(repo, "get_user", lambda *a: (_ for _ in ()).throw(RuntimeError("db gone")))
    world.charge_error, world.charge_result = None, {"id": "pi_z", "status": "requires_payment_method"}
    assert billing.auto_reload(Conn(), UID, trigger="run21") is False
    assert len(world.notes) == 1 and "failure email not sent" in capsys.readouterr().out
    assert world.credits == [] and [c["idem"] for c in world.charges] == ["reload-7-run20", "reload-7-run21"]


def test_a_user_without_an_address_gets_the_notice_and_no_email(world, monkeypatch):
    from app import repository as repo

    monkeypatch.setattr(repo, "get_user", lambda cur, uid: {"id": uid, "email": None, "name": "Ada"})
    world.charge_error = _declined()
    with pytest.raises(billing.StripeError):
        billing.auto_reload(Conn(), UID, trigger="run22")
    assert len(world.notes) == 1 and world.emails == []


def _ctx(body=None):
    return SimpleNamespace(cur=object(), uid=UID, body=body or {}, user={"id": UID}, conn=Conn(), query={})


def test_billing_shows_the_last_failure_until_an_auto_reload_succeeds(monkeypatch):
    repo = billing_routes.repo
    note = {"id": 3, "body": billing.reload_failed_body(Decimal("20"), billing.CARD_DECLINED), "created_at": NOW, "read_at": NOW}
    monkeypatch.setattr(repo, "latest_notification", lambda cur, uid, kind: note if kind == "reload_failed" else None)
    ok_at = [None]
    monkeypatch.setattr(repo, "last_credit_at", lambda cur, uid, kind: ok_at[0] if kind == "autoreload" else pytest.fail(kind))
    # Read in the bell or not, Billing still says it: it is about the card, not the bell.
    assert billing_routes._reload_failed(object(), UID) == {
        "at": NOW, "text": "It couldn’t add $20.00 in credits. " + billing.CARD_DECLINED}
    for older in (NOW - timedelta(minutes=5), NOW):  # an older success (or one in the same second) keeps it
        ok_at[0] = older
        assert billing_routes._reload_failed(object(), UID)["at"] == NOW
    ok_at[0] = NOW + timedelta(minutes=5)
    assert billing_routes._reload_failed(object(), UID) is None
    monkeypatch.setattr(repo, "latest_notification", lambda *a: (_ for _ in ()).throw(RuntimeError("db gone")))
    assert billing_routes._reload_failed(object(), UID) is None  # a readout: never a broken page


def test_saving_a_card_clears_the_failure_and_a_failed_clear_still_saves_it(monkeypatch):
    repo = billing_routes.repo
    saved, cleared = [], []
    monkeypatch.setattr(repo, "get_stripe_customer", lambda cur, uid: {"stripe_customer_id": "cus_fixture"})
    monkeypatch.setattr(billing, "set_default_card", lambda cid, pm: None)
    monkeypatch.setattr(repo, "set_default_pm", lambda cur, uid, pm: saved.append(pm))
    monkeypatch.setattr(repo, "delete_notifications", lambda cur, uid, kind: cleared.append(kind) or 1)
    assert billing_routes.billing_card_added(_ctx({"payment_method_id": "pm_new"})) == {"ok": True}
    assert saved == ["pm_new"] and cleared == ["reload_failed"]
    monkeypatch.setattr(repo, "delete_notifications", lambda *a: (_ for _ in ()).throw(RuntimeError("db gone")))
    assert billing_routes.billing_card_added(_ctx({"payment_method_id": "pm_2"})) == {"ok": True}
    assert saved == ["pm_new", "pm_2"]


def test_repository_reads_are_one_statement_each():
    from app import repository as repo

    class Cur:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params):
            self.executed.append((" ".join(sql.split()), params))

        def fetchone(self):
            return {"t": NOW}

    cur = Cur()
    assert repo.last_credit_at(cur, UID, "autoreload") == NOW
    assert cur.executed == [("SELECT MAX(created_at) AS t FROM app_credit_ledger WHERE user_id=%s AND kind=%s", (UID, "autoreload"))]
    cur = Cur()
    repo.latest_notification(cur, UID, "reload_failed")
    assert cur.executed[0][1] == (UID, "reload_failed") and "ORDER BY id DESC LIMIT 1" in cur.executed[0][0]
