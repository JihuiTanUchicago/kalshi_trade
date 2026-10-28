"""Customer copy writes an apostrophe curly ("isn’t"), as the pages do (customer_text.curly).

Walk 2026-10-27: the out-of-credits refusal ("You're out of credits."), the bell's fallback line ("There's an
update on your account."), a failed auto-reload's line on Billing and in the bell ("It couldn't add $25.00 in
credits.") and the admin waitlist's refusal ("That email isn't on the waitlist.") said theirs straight, beside
pages that write them curly. The money path's own words (the engine's kill switch, pause and fill lines) are
said as written and are not held here."""
import ast
import inspect
import re
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import repository as repo
from app import server
from app.adapters.stripe import billing
from app.services import customer_text as ct
from app.web import views
from app.web.http import ApiError
from app.web.routes import admin as admin_routes
from app.web.routes import billing as billing_routes

STRAIGHT = re.compile(r"[A-Za-z]'[A-Za-z]")
NOW = datetime(2026, 10, 27, 15, 0)


def _ctx(body=None):
    return SimpleNamespace(cur=object(), uid=7, body=body or {}, user={"id": 7, "email": "a@example.com"}, query={})


def _module_strings(module):
    """Every string constant ``module`` assigns at its top level: the fallbacks and the fixed lines it hands out."""
    out = {}
    for node in ast.parse(inspect.getsource(module)).body:
        for t in (node.targets if isinstance(node, ast.Assign) else []):
            if isinstance(t, ast.Name) and isinstance(getattr(module, t.id, None), str):
                out[t.id] = getattr(module, t.id)
    return out


def test_customer_text_fallbacks_write_apostrophes_curly():
    lines = _module_strings(ct)
    # The fallbacks the bell, a run's log and the autopilot panel show in place of text they can't show.
    assert {"EVENT_FALLBACK", "NOTICE_FALLBACK", "CHAT_FALLBACK", "NO_ANSWER", "NO_ANSWER_LINE"} <= set(lines)
    for name, text in lines.items():
        assert not STRAIGHT.search(text), "%s = %r" % (name, text)
    assert ct.NOTICE_FALLBACK == "There’s an update on your account."


def test_the_bell_says_its_fallback_curly(monkeypatch):
    monkeypatch.setattr(repo, "list_notifications", lambda cur, uid, **k: [
        {"id": 1, "kind": "x", "body": "Traceback (most recent call last): boom", "link": None, "created_at": NOW, "read_at": None}])
    monkeypatch.setattr(repo, "count_unread_notifications", lambda cur, uid: 1)
    assert [n["body"] for n in server.notifications(_ctx())["items"]] == ["There’s an update on your account."]


def test_out_of_credits_refusal_is_curly_and_says_where_to_add_them(monkeypatch):
    monkeypatch.setattr(views.billing, "configured", lambda: True)
    monkeypatch.setattr(views, "_needs_card", lambda ctx: False)
    monkeypatch.setattr(views.repo, "credit_balance", lambda cur, uid: 0)
    for gerund in ("researching", "chatting with the agent"):
        with pytest.raises(ApiError) as e:
            views._require_billing_ready(_ctx(), gerund)
        assert e.value.status == 402
        assert e.value.message == "You’re out of credits. Add credits on the Billing tab to keep %s." % gerund
        assert not STRAIGHT.search(e.value.message)


@pytest.mark.parametrize("reason", sorted(set(billing._CARD_DECLINE_COPY.values()) | {billing.CARD_DECLINED, billing.RELOAD_FAILED_FALLBACK}))
def test_a_failed_auto_reload_reads_curly_on_billing_and_in_the_bell(monkeypatch, reason):
    body = billing.reload_failed_body(Decimal("25"), reason)  # stored as the email says it, straight
    note = {"id": 3, "kind": billing.RELOAD_FAILED_KIND, "body": body, "link": "/billing", "created_at": NOW, "read_at": None}
    monkeypatch.setattr(repo, "latest_notification", lambda cur, uid, kind: note)
    monkeypatch.setattr(repo, "last_credit_at", lambda cur, uid, kind: None)
    text = billing_routes._reload_failed(object(), 7)["text"]
    assert text.startswith("It couldn’t add $25.00 in credits. ")
    assert not STRAIGHT.search(text), text
    bell = ct.notification_rows([dict(note)])[0]["body"]
    assert bell.startswith("Auto-reload couldn’t add $25.00 in credits. ") and bell.endswith(" Update your card on Billing.")
    assert not STRAIGHT.search(bell), bell


def test_the_bell_curls_only_billings_own_lines():
    assert ct.CURLY_KINDS == {billing.RELOAD_FAILED_KIND}
    # Any other kind keeps its stored words: the engine's lines are the money path's, said as written.
    kept = "Kill switch is on: new buys won't be placed."
    assert ct.notification_rows([{"kind": "kill_switch", "body": kept}])[0]["body"] == kept


def test_the_admin_waitlist_refusal_is_curly(monkeypatch):
    monkeypatch.setattr(admin_routes, "_require_admin", lambda ctx: None)
    monkeypatch.setattr(server.repo, "remove_waitlist", lambda cur, e: False)
    with pytest.raises(ApiError) as e:
        server.admin_waitlist(_ctx({"email": "x@y.com", "action": "remove"}))
    assert e.value.status == 404 and e.value.message == "That email isn’t on the waitlist."


def test_the_server_failure_reply_is_curly():
    # Every unexpected error's reply, which both themes print on the page that failed.
    src = inspect.getsource(server.Handler)
    assert '{"error": "Something went wrong on our side. It’s been logged."}' in src
    assert "It's been logged" not in src


def test_a_key_tau_cannot_store_yet_says_so_without_the_servers_setup(monkeypatch):
    # Walk 2026-10-28: "This server can’t store keys yet (encryption key not configured)." named how the server is set up.
    from app.web.routes import funds
    monkeypatch.setattr(funds.kalshi_account, "verify", lambda key_id, pem: 10.0)
    monkeypatch.setattr(funds.kalshi_account, "parse_private_key", lambda pem: object())
    monkeypatch.setattr(funds.kalshi_dev_exec, "demo_fills", lambda creds: [])

    def no_key(uid, pem):
        raise RuntimeError("the encryption key is not set")

    monkeypatch.setattr(funds.kalshi_account, "encrypt_private_key", no_key)
    for save in (funds.save_kalshi_key, funds.save_kalshi_dev_key):
        with pytest.raises(ApiError) as e:
            save(_ctx({"key_id": "a952bcbe", "private_key": "pem"}))
        assert e.value.status == 503 and e.value.message == "Tau can’t store API keys yet. Please try again later."

    def no_host(creds):
        raise funds.kalshi_dev_exec.DemoHostError("no demo host")

    monkeypatch.setattr(funds.kalshi_dev_exec, "demo_fills", no_host)
    with pytest.raises(ApiError) as e:
        funds.save_kalshi_dev_key(_ctx({"key_id": "a952bcbe", "private_key": "pem"}))
    assert e.value.message == "Kalshi’s demo exchange isn’t available on Tau yet. Please try again later."
