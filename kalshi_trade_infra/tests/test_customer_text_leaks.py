"""No customer-visible text built from stored rows leaks what is not theirs: another person's or
staff's email address, an internal model id, a raw upstream error, an AWS or credential-store name,
an internal hostname or a file path (app.services.customer_text).

Each render path a customer reads is fed rows poisoned with every kind of leak, the way old rows,
an admin tool or a provider's error left them, and its output is held to customer_text.leaks. The
rows themselves are never rewritten. No DB, no network: the reads are stubbed, and sockets and
boto3 fail the test if anything reaches for them."""
import csv
import io
import json
import socket
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import repository as repo
from app import server
from app.adapters.ses import notify
from app.services import customer_text as ct
from app.services import demo_record
from app.web.routes import billing as billing_routes
from app.web.routes import community

STAFF = "ops.staff@tau-internal.example"
OTHER = "someone.else@example.org"
MODEL_ID = "us.anthropic.claude-opus-4-6-v1"
RAW = ("Bedrock call failed: An error occurred (ValidationException) when calling the InvokeModel "
       "operation on %s" % MODEL_ID)
TRACE = 'Traceback (most recent call last):\n  File "/home/ubuntu/kalshi_trade/app/research/agent.py", line 12'
HOST = "pymysql.err.OperationalError: (2003, \"Can't connect to tau-prod.cluster-abc.us-east-1.rds.amazonaws.com\")"
SECRET = "Could not read secret kalshi/odds_api_key from Secrets Manager (arn:aws:secretsmanager:us-east-1:1:secret:x)"
HTML = "<html><head><title>502 Bad Gateway</title></head><body>nginx at ip-10-0-3-17</body></html>"
POISON = [STAFF, OTHER, MODEL_ID, RAW, TRACE, HOST, SECRET, HTML]

# Customer copy the app really writes: none of it may read as a leak, and clean leaves it as is.
SAFE = [
    "Welcome credits", "Added $10 credits", "Auto-reload $25", "Stripe topup",
    "Research session · Claude Opus 4.6", "Agent usage · Amazon Nova Lite",
    "Lost $12.00, more than the $10.00 guard (2x its worst backtest drawdown).",
    "force-closed: position down 33.0% >= stop 30.0%", "Autopilot daily loss limit hit",
    "Kalshi account daily loss limit hit", "Add your Kalshi demo (sandbox) key on the Funds page to run this on demo.",
    "Live trading is not enabled on this server yet.",
    "Autopilot: momentum faded (win rate 41.2% vs 55% in backtest), pausing to protect capital.",
    "Paused for a server update; resuming from the last checkpoint.",
    "The session hit an unexpected error and stopped.",
    "The model provider is busy right now. The session will pick up again shortly.",
    "Explored 12 hypotheses, then the session was interrupted and stopped — start a new one to keep going.",
    "FAILED - Fade: validation verdict is gatekeeper-held (classification=inconclusive)",
    "“BTC 15m fade” was paused automatically. Lost $3.10, more than the $2.50 guard.",
    "Dana mentioned you.", "Sam shared the strategy “KXBTC15M momentum” with you.",
    "[live-ready #12] “Fade” cleared every paper-to-live check: 31/30 realistic paper trades.",
    "Kalshi said: market is closed", "Stopped: its code changes the decision at 2026-10-25 14:00 UTC.",
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test reached for the network: %r" % (a,))

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    try:
        import boto3
        monkeypatch.setattr(boto3, "client", refuse)
    except ImportError:
        pass


def _ctx(params=(), query=None, body=None, user=None):
    return server.Ctx(SimpleNamespace(cursor=lambda: object()),
                      user or {"id": 7, "email": "trader@example.invalid", "name": "T", "autopilot": 1},
                      tuple(params), query or {}, body or {}, SimpleNamespace())


def _no_leak(out, own_email=None):
    text = out if isinstance(out, str) else json.dumps(out, default=str)
    if own_email:
        text = text.replace(own_email, "")
    for p in (STAFF, OTHER, MODEL_ID, "amazonaws", "kalshi_trade", "Traceback", "arn:aws", "ip-10-0-3-17"):
        assert p not in text, p
    assert ct.leaks(text) == [], (ct.leaks(text), text[:400])


# -- the rules ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", POISON)
def test_every_kind_of_leak_is_caught_and_cleaned(text):
    assert ct.leaks(text)
    assert ct.leaks(ct.clean(text, "Fallback.")) == []


@pytest.mark.parametrize("text", SAFE)
def test_customer_copy_is_left_as_written(text):
    assert ct.leaks(text) == [], text
    assert ct.clean(text, "Fallback.") == text


def test_an_email_or_model_id_in_a_sentence_is_replaced_where_it_stands():
    assert ct.clean("%s mentioned you." % OTHER) == "someone mentioned you."
    assert ct.clean("Billed on %s." % MODEL_ID) == "Billed on the AI model."
    assert ct.clean(RAW, "Fallback.") == "Fallback."  # an internal message goes whole
    assert ct.clean(None) is None and ct.clean("") == ""


def test_a_name_that_is_an_email_is_never_shown():
    assert ct.display_name(OTHER, "Trader") == "Trader"
    assert ct.display_name("  ", "Trader") == "Trader"
    assert ct.display_name("Dana Q.", "Trader") == "Dana Q."


# -- Billing and the receipt ----------------------------------------------------------------------

def _ledger():
    at = datetime(2026, 10, 25, 12, 0)
    return [
        {"kind": "admin_grant", "amount_usd": Decimal("5"), "memo": "Admin grant by %s" % STAFF, "created_at": at,
         "stripe_ref": None, "run_id": None},
        {"kind": "admin_grant", "amount_usd": Decimal("-2"), "memo": "Admin grant by %s" % STAFF, "created_at": at,
         "stripe_ref": None, "run_id": None},
        {"kind": "usage", "amount_usd": Decimal("-0.5"), "memo": "Agent usage · %s" % MODEL_ID, "created_at": at,
         "stripe_ref": None, "run_id": 3, "run_kind": "research", "run_brief": 0},
        {"kind": "bonus", "amount_usd": Decimal("20"), "memo": "Welcome credits", "created_at": at,
         "stripe_ref": None, "run_id": None},
        {"kind": "topup", "amount_usd": Decimal("10"), "memo": RAW, "created_at": at, "stripe_ref": "pi_1",
         "run_id": None},
    ]


def test_an_admin_grant_reads_as_tau_support_never_who_made_it():
    grant, debit = _ledger()[:2]
    assert billing_routes._ledger_memo(grant) == "Credits added by Tau support"
    assert billing_routes._ledger_memo(debit) == "Credits adjusted by Tau support"
    # The statement's grouped rows carry `amount`, the receipt's `amount_usd`: both read the same.
    assert billing_routes._ledger_memo({"kind": "admin_grant", "amount": -2.0, "memo": grant["memo"]}) == \
        "Credits adjusted by Tau support"
    assert billing_routes._ledger_memo({"kind": "admin_grant", "amount": 5.0, "memo": grant["memo"]}) == \
        "Credits added by Tau support"


def test_the_receipt_never_names_staff_or_a_model_id(monkeypatch):
    monkeypatch.setattr(repo, "get_user", lambda cur, uid: {"email": "trader@example.invalid"})
    monkeypatch.setattr(repo, "credit_balance", lambda cur, uid: 32.5)
    monkeypatch.setattr(repo, "credit_spent_total", lambda cur, uid: 0.5)
    monkeypatch.setattr(repo, "credit_rows", lambda cur, uid, limit: _ledger())
    _kind, _name, _ctype, body = billing_routes.billing_receipt(_ctx())
    rows = list(csv.reader(io.StringIO(body)))
    table = rows[rows.index(billing_routes.RECEIPT_HEADER) + 1:]
    assert [r[3] for r in table] == ["Credits added by Tau support", "Credits adjusted by Tau support",
                                     "Research session · Claude Opus 4.6", "Welcome credits", ""]
    _no_leak(body, own_email="trader@example.invalid")


def test_the_billing_statement_never_names_staff_or_a_model_id(monkeypatch):
    rows = [dict(r, amount=r["amount_usd"], n=1, first_at=r["created_at"], last_at=r["created_at"], day="2026-10-25")
            for r in _ledger()]
    monkeypatch.setattr(repo, "credit_statement", lambda cur, uid, since, tz, limit: rows)
    totals = {"admin_grant": {"all": 3.0, "n": 2, "since": 3.0, "n_since": 2}}
    out = billing_routes._statement(object(), 7, datetime(2026, 9, 25), 0, totals, 32.5)
    assert [ln["memo"] for ln in out["ledger"]][:2] == ["Credits added by Tau support", "Credits adjusted by Tau support"]
    _no_leak(out)


# -- the bell, the autopilot panel, the research pages ---------------------------------------------

def test_notifications_never_carry_an_email_or_a_raw_error(monkeypatch):
    bodies = ["%s mentioned you." % OTHER, "%s shared the strategy “Fade” with you." % OTHER,
              "“Fade” was paused automatically. %s" % HOST, "Dana commented on your post."]
    monkeypatch.setattr(repo, "list_notifications", lambda cur, uid: [
        {"id": i, "kind": "x", "body": b, "link": "/community", "created_at": None, "read_at": None}
        for i, b in enumerate(bodies)])
    monkeypatch.setattr(repo, "count_unread_notifications", lambda cur, uid: 4)
    out = server.notifications(_ctx())
    assert [n["body"] for n in out["items"]] == [
        "someone mentioned you.", "someone shared the strategy “Fade” with you.",
        ct.NOTICE_FALLBACK, "Dana commented on your post."]
    _no_leak(out)


def test_the_autopilot_panel_cleans_the_lines_tau_wrote(monkeypatch):
    msgs = [{"id": 1, "role": "user", "content": "why did %s stop?" % "Fade"},
            {"id": 2, "role": "system", "content": "Paused deployment #4 automatically. %s" % TRACE},
            {"id": 3, "role": "system", "content": "Autopilot paused Fade."}]
    monkeypatch.setattr(repo, "active_agent_run", lambda cur, uid: None)
    monkeypatch.setattr(repo, "chat_messages", lambda cur, uid, after: [dict(m) for m in msgs])
    out = server.get_chat(_ctx())
    assert [m["content"] for m in out["messages"]] == [msgs[0]["content"], ct.CHAT_FALLBACK, "Autopilot paused Fade."]
    _no_leak(out)


def _run_reads(monkeypatch, run, events):
    monkeypatch.setattr(repo, "get_run", lambda cur, uid, rid: dict(run))
    monkeypatch.setattr(repo, "runs_spent", lambda *a: {})
    monkeypatch.setattr(repo, "list_strategies", lambda *a, **k: [])
    monkeypatch.setattr(repo, "get_policy", lambda *a: None)
    monkeypatch.setattr(repo, "latest_dream_event", lambda *a: None)
    monkeypatch.setattr(repo, "run_events", lambda *a: [dict(e, data=dict(e["data"]) if e["data"] else None)
                                                        for e in events])


def test_a_research_session_page_never_shows_a_raw_error_or_model_id(monkeypatch):
    run = {"id": 9, "kind": "research", "status": "failed", "error": RAW, "model": None, "created_at": None,
           "heartbeat_at": None, "finished_at": None}
    events = [{"id": 1, "kind": "error", "message": TRACE, "data": None},
              {"id": 2, "kind": "step", "message": "Asked %s for 3 ideas." % MODEL_ID, "data": {"model": MODEL_ID}},
              {"id": 3, "kind": "step", "message": "Froze 2 finalists", "data": None}]
    _run_reads(monkeypatch, run, events)
    out = server.get_run(_ctx(("9",)))
    assert out["run"]["error"] is None  # the page says "This session stopped on an error." itself
    assert [e["message"] for e in out["events"]] == [ct.EVENT_FALLBACK, "Asked the AI model for 3 ideas.",
                                                     "Froze 2 finalists"]
    _no_leak(out)


def test_the_agents_own_words_and_code_are_never_mistaken_for_an_error(monkeypatch):
    run = {"id": 9, "kind": "research", "status": "running", "error": None, "model": None, "created_at": None,
           "heartbeat_at": None, "finished_at": None}
    thought = "If the feature is missing this raises KeyError: 'spot_comp', so guard it in strategy.py."
    code = "def signal(row):\n    if row is None:\n        raise ValueError('no row')\n    return 1"
    events = [{"id": 1, "kind": "thinking", "message": thought, "data": {"block": 1}},
              {"id": 2, "kind": "hypothesis", "message": "Fade the open", "data": {"code": code}}]
    _run_reads(monkeypatch, run, events)
    out = server.get_run(_ctx(("9",)))
    assert out["events"][0]["message"] == thought
    assert out["events"][1]["data"]["code"] == code


def test_the_research_list_never_shows_a_raw_error(monkeypatch):
    monkeypatch.setattr(repo, "get_policy", lambda *a: None)
    monkeypatch.setattr(repo, "list_runs", lambda cur, uid: [
        {"id": 1, "status": "failed", "error": HOST, "direction": "x", "run_forever": 0},
        {"id": 2, "status": "stopped", "error": "The session was interrupted before it explored a hypothesis — start a new one.",
         "direction": "x", "run_forever": 0}])
    monkeypatch.setattr(repo, "runs_spent", lambda *a: {})
    monkeypatch.setattr(repo, "active_run_counts", lambda *a, **k: {})
    monkeypatch.setattr(repo, "list_runs_version", lambda *a, **k: [])
    monkeypatch.setattr(server, "_research_totals", lambda cur, uid: {})
    out = server.list_runs(_ctx())
    assert [r["error"] for r in out["runs"]][0] is None
    assert [r["stop_reason"] for r in out["runs"]] == ["error", "interrupted"]
    _no_leak(out)


@pytest.mark.parametrize("raw", [RAW, HOST, SECRET])
def test_a_deployment_never_says_why_in_raw_error_text(raw):
    assert server._status_why({"status": "paused", "status_reason": raw}) == "Paused automatically"
    assert server._status_why({"status": "stopped", "status_reason": raw}) == "Stopped automatically"
    assert server._plain_pause_reason(raw) == "it was paused"


def test_demo_refusals_never_quote_an_error_page_or_host():
    assert demo_record.refusal_reason({"http_status": 400, "message": HTML}) == "Kalshi said: HTTP 400"
    assert demo_record.refusal_reason({"http_status": 404, "code": "market_not_found", "message": HOST}) == \
        "Kalshi said: market_not_found"
    assert demo_record.refusal_reason({"http_status": 400, "message": "market is closed"}) == \
        "Kalshi said: market is closed"


# -- the community, in the app and in email --------------------------------------------------------

def test_a_name_that_is_an_email_never_shows_in_the_community(monkeypatch):
    post = {"id": 1, "body": "gm", "kind": "note", "likes_count": 0, "comments_count": 0, "created_at": None,
            "name": OTHER, "username": "someone", "picture_url": None}
    assert community._post_out(post)["author"] == "Trader"
    monkeypatch.setattr(repo, "list_comments", lambda cur, pid: [
        {"body": "nice", "name": OTHER, "username": "someone", "picture_url": None, "created_at": None}])
    assert community.post_comments(_ctx(("1",)))["comments"][0]["author"] == "Trader"
    monkeypatch.setattr(repo, "mention_candidates", lambda cur, q: [{"username": "someone", "name": OTHER}])
    assert community.mention_candidates(_ctx(query={"q": "so"}))["users"] == [{"username": "someone", "name": "someone"}]


def test_a_comment_notice_never_names_the_commenter_by_email(monkeypatch):
    sent, notes = [], []
    monkeypatch.setattr(notify, "_send", lambda to, subject, body, reply_to=None: sent.append((to, subject, body)) or True)
    monkeypatch.setattr(repo, "post_author", lambda cur, pid: {"user_id": 2, "email": "author@example.net",
                                                              "email_opt_out": 0, "name": "Ana", "preview": "gm"})
    monkeypatch.setattr(repo, "add_comment", lambda *a: None)
    monkeypatch.setattr(repo, "get_user", lambda cur, uid: {"id": 7, "name": OTHER})
    monkeypatch.setattr(repo, "users_by_usernames", lambda cur, names: [
        {"id": 3, "email": "mentioned@example.net", "email_opt_out": 0, "name": "Mo"}])
    monkeypatch.setattr(repo, "add_notification", lambda cur, uid, kind, body, link=None: notes.append(body))
    community.create_comment(_ctx(("1",), body={"body": "hey @mo"}))
    assert notes == ["Someone mentioned you.", "Someone commented on your post."]
    assert [s[0] for s in sent] == ["mentioned@example.net", "author@example.net"]
    for _to, subject, body in sent:
        _no_leak(subject + body.replace(notify.PUBLIC_URL, ""))
