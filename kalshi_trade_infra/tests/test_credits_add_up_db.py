"""Every credit figure a customer sees adds up, end to end, against a real MySQL.

One carded user, with payments switched on in-process the way the billing tests do it (a test
Stripe key; every Stripe call is stubbed, and any other call fails the test). The user gets:
- the welcome bonus at signup;
- a $10 top-up through the top-up endpoint;
- two research sessions, each billed per model call through agent._bill, the function every run
  path bills with (billing.charge_usage, then the ledger, then auto-reload);
- one chat turn through agent.run_copilot with a stubbed model;
- an auto-reload, which fires inside the billing of the second session when the balance falls to
  the threshold.

Then every place that shows credits is read the way the app reads it and held to the ledger and to
the price list, to the cent: list price × USAGE_MARGIN at the model's catalog rates. Where two
figures differ by design (research cost leaves out chat and the seeded example session; the
estimate needs three sessions of your own), the relationship is asserted. No billing math is
touched. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import csv
import io
import json
import os
import uuid
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.web.routes import research as research_routes

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

SIX = Decimal("0.000001")


def _four(v) -> str:
    """The receipt's 4-place amount: half up from the exact decimal."""
    return str(Decimal(str(v)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


def _billed(choice, tokens_in, tokens_out):
    """What one model call must cost, worked out here from the catalog rates, not by usage_cost."""
    from app.adapters.stripe import billing

    list_usd = (Decimal(tokens_in) * choice.price_in + Decimal(tokens_out) * choice.price_out) / Decimal(1_000_000)
    return (list_usd * billing.USAGE_MARGIN).quantize(SIX, rounding=ROUND_HALF_UP), list_usd


def _cents(v):
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def test_every_credit_figure_adds_up_to_the_cent(conn, monkeypatch):
    from app import server
    from app.web.routes import billing as billing_routes
    from app.adapters.stripe import billing
    from app.research import agent
    from app.adapters.llm import models_catalog as catalog
    from app import repository as repo
    from app.adapters.llm.llm import Usage

    # -- payments on, in-process ----------------------------------------------------------------
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_credits_add_up")
    monkeypatch.setattr(billing, "FREE_BONUS", Decimal("20"))

    def no_network(*a, **k):
        raise AssertionError("a Stripe call escaped the stubs: %r" % (a,))

    charges = []

    def charge(customer_id, pm_id, amount_cents, off_session, idem, metadata=None):
        charges.append({"cents": amount_cents, "off_session": off_session, "idem": idem, "metadata": metadata})
        return {"id": "pi_" + idem, "status": "succeeded"}  # Stripe answers a repeated idempotency key with the same PI

    monkeypatch.setattr(billing, "_stripe", no_network)
    monkeypatch.setattr(billing, "charge", charge)
    customer = "cus_" + uuid.uuid4().hex[:14]  # Stripe customer ids are unique across users
    monkeypatch.setattr(billing, "get_or_create_customer", lambda user, existing: existing or customer)
    monkeypatch.setattr(billing, "set_default_card", lambda customer_id, pm: None)
    monkeypatch.setattr(billing, "list_cards", lambda customer_id: [{"id": "pm_credits", "brand": "visa", "last4": "4242"}])

    cur = conn.cursor()
    user = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "credits@example.com", "C", None)  # bonus + example session
    uid = user["id"]

    def ctx(params=(), query=None, body=None):
        return server.Ctx(conn, repo.get_user(cur, uid), tuple(str(p) for p in params), query or {}, body or {}, None)

    # -- card, top-up and auto-reload settings, through their endpoints ---------------------------
    assert server.me(ctx())["needs_card"] is True
    assert server.billing_card_added(ctx(body={"payment_method_id": "pm_credits"})) == {"ok": True}
    assert server.me(ctx())["needs_card"] is False
    top =server.billing_topup(ctx(body={"amount": 10}))
    assert charges[-1]["cents"] == billing.topup_charge_cents(Decimal("10")) == 1055 and charges[-1]["off_session"] is False
    assert top["balance"] == pytest.approx(30.0)
    assert top["charged"] == 10.55  # the confirmation states the card's charge, as charged
    server.billing_autoreload(ctx(body={"on": True, "amount": 25, "threshold": 8}))

    # -- two research sessions and one chat turn, billed per model call --------------------------
    opus, sonnet = catalog.get("opus-4-6"), catalog.get("sonnet-4-6")
    debits = []  # (run_id, model_id, expected debit, list price) per model call, in billing order

    def session(choice, calls, direction):
        run_id = repo.create_run(cur, uid, "research", "btc15m", direction, max_hypotheses=4, model=choice.key)
        cur.execute("UPDATE app_agent_runs SET status='running', started_at=%s WHERE id=%s", (repo.now_utc(), run_id))
        tin = tout = 0
        for tokens_in, tokens_out in calls:
            agent._bill(conn, uid, Usage(tokens_in, tokens_out), run_id, choice.model_id)
            debits.append((run_id, choice.model_id) + _billed(choice, tokens_in, tokens_out))
            tin, tout = tin + tokens_in, tout + tokens_out
        repo.finish_run(cur, run_id, "succeeded", None, 4, 0, tin, tout)
        return run_id

    first = session(opus, [(412_345, 38_765), (233_333, 51_111)], "momentum")
    assert not [c for c in charges if c["off_session"]], "no reload while the balance is above the threshold"
    second = session(sonnet, [(777_777, 66_666), (555_555, 44_444), (12_345, 6_789)], "volatility")

    chat_id = repo.create_run(cur, uid, "chat")
    cur.execute("UPDATE app_agent_runs SET status='running' WHERE id=%s", (chat_id,))
    repo.add_chat(cur, uid, "user", "How much have I spent?")
    calls = []

    def model(system, messages, on_delta=None):
        calls.append(1)
        return json.dumps({"reply": "About what the Billing page says.", "actions": []}), {"input_tokens": 4_321, "output_tokens": 567}

    cur.execute("SELECT * FROM app_agent_runs WHERE id=%s", (chat_id,))  # the full row, as the worker claims it
    agent.run_copilot(conn, cur.fetchone(), model=model)
    chat_choice = catalog.resolve(None)  # no autopilot model set: the default, as run_copilot resolves it
    debits.append((chat_id, chat_choice.model_id) + _billed(chat_choice, 4_321 * len(calls), 567 * len(calls)))
    assert repo.get_run(cur, uid, chat_id)["status"] == "succeeded"

    # -- the ledger ------------------------------------------------------------------------------
    cur.execute("SELECT id, kind, amount_usd, memo, stripe_ref, run_id FROM app_credit_ledger WHERE user_id=%s ORDER BY id", (uid,))
    ledger = cur.fetchall()
    usage = [r for r in ledger if r["kind"] == "usage"]
    assert [r["kind"] for r in ledger if r["kind"] != "usage"] == ["bonus", "topup", "autoreload"]
    bonus, topup, reload_row = (next(r for r in ledger if r["kind"] == k) for k in ("bonus", "topup", "autoreload"))
    assert Decimal(bonus["amount_usd"]) == Decimal("20") and Decimal(topup["amount_usd"]) == Decimal("10")

    # Every usage debit is list × USAGE_MARGIN at that model's catalog rates, one row per billed call.
    assert len(usage) == len(debits)
    for row, (run_id, model_id, expected, list_usd) in zip(usage, debits):
        assert row["run_id"] == run_id and row["memo"] == "Agent usage · %s" % model_id
        assert -Decimal(row["amount_usd"]) == expected
        assert expected == (list_usd * billing.USAGE_MARGIN).quantize(SIX, rounding=ROUND_HALF_UP) and expected > list_usd
    per_run = {}
    for run_id, _m, expected, _l in debits:
        per_run[run_id] = per_run.get(run_id, Decimal(0)) + expected
    spent_total = sum(per_run.values())

    # The auto-reload: once, off-session, the saved amount plus the top-up fee, when the second
    # session's billing took the balance to the threshold; later calls in that run never re-credit.
    reloads = [c for c in charges if c["off_session"]]
    assert len({c["idem"] for c in reloads}) == 1 and reloads[0]["idem"] == "reload-%s-run%s" % (uid, second)
    assert reloads[0]["cents"] == billing.topup_charge_cents(Decimal("25")) == 2638
    assert Decimal(reload_row["amount_usd"]) == Decimal("25") and reload_row["stripe_ref"] == "pi_reload-%s-run%s" % (uid, second)
    before_reload = [r for r in ledger if r["id"] < reload_row["id"]]
    assert sum(Decimal(r["amount_usd"]) for r in before_reload) <= Decimal("8")  # it fired at the threshold
    assert sum(Decimal(r["amount_usd"]) for r in before_reload[:-1]) > Decimal("8")  # and not a call earlier

    balance = Decimal(20) + Decimal(10) + Decimal(25) - spent_total
    assert Decimal(str(repo.credit_balance(cur, uid))).quantize(SIX) == balance

    # -- each run's spent_usd is that run's usage rows -------------------------------------------
    runs = {r["id"]: r for r in server.list_runs(ctx())["runs"]}
    for run_id in (first, second):
        rows = sum(-Decimal(r["amount_usd"]) for r in usage if r["run_id"] == run_id)
        assert rows == per_run[run_id]
        assert runs[run_id]["spent_usd"] == float(_cents(rows))  # to the cent, half up, as Billing rounds
        assert server.get_run(ctx(params=(run_id,)))["run"]["spent_usd"] == runs[run_id]["spent_usd"]
    [example] = [r for r in runs.values() if r["example"]]
    assert example["spent_usd"] == 0 and example["status"] == "succeeded"  # the seeded session cost nothing
    assert chat_id not in runs  # the research list shows research sessions only

    # -- the research form's estimate follows from those two sessions ----------------------------
    est = server.research_estimate(ctx())
    # Three finished research sessions exist, but the seeded random-walk example is left out, and
    # two of your own are fewer than SESSION_COST_MIN_OWN, so "yours" is not shown yet.
    assert est["sessions"] == 2 and est["yours"] is None and server.SESSION_COST_MIN_OWN > 2
    monkeypatch.setattr(research_routes, "SESSION_COST_MIN_OWN", 2)
    median = (per_run[first] + per_run[second]) / 2
    assert server.research_estimate(ctx())["yours"] == float(_cents(median))

    # -- research cost this week: research debits only, never chat ------------------------------
    research_usd = per_run[first] + per_run[second]
    since = repo.now_utc() - server.timedelta(days=7)
    assert Decimal(str(repo.research_spent_since(cur, uid, since))).quantize(SIX) == research_usd
    status = server.autopilot_status(ctx())
    # To the cent as Billing's week split shows its two research parts: the research total to the cent,
    # or one cent from it when each part's rounding moves the same way.
    assert abs(Decimal(str(status["research"]["cost_7d"])) - _cents(research_usd)) <= Decimal("0.01")
    assert server._autopilot_week(cur, uid, status["research"])["research_credits"] == status["research"]["cost_7d"]
    assert spent_total - research_usd == per_run[chat_id] > 0  # the chat turn is billed, just not as research

    # -- the autopilot chat's line under the composer: what your last message cost ---------------
    # The chat turn's own debits, to the cent: on the first read and on a read that brings its answer.
    assert repo.last_chat_turn_cost(cur, uid) == float(per_run[chat_id])
    first_read = server.get_chat(ctx())
    assert first_read["turn_cost"] == float(per_run[chat_id])
    answer = max(m["id"] for m in first_read["messages"] if m["role"] == "agent")
    assert server.get_chat(ctx(query={"after": str(answer - 1)}))["turn_cost"] == first_read["turn_cost"]
    assert "turn_cost" not in server.get_chat(ctx(query={"after": str(answer)}))  # a poll with nothing new reads nothing

    # -- the Billing page ------------------------------------------------------------------------
    state = server.billing_state(ctx())
    assert state["configured"] is True and state["default_pm"] == "pm_credits" and state["auto_reload"] is True
    assert state["balance"] == float(balance.quantize(SIX))  # as the ledger holds it; the page rounds half up
    assert state["spent"] == state["spent_7d"] == float(_cents(spent_total))
    # The statement: every row is inside its 30 days. A run's calls on one day with one model are one
    # line whose calls and amount are those rows'; every other row is its own line.
    lines = state["ledger"]
    assert state["ledger_cut"] is False
    assert sorted((r["kind"], round(r["amount"], 6)) for r in lines if r["kind"] != "usage") == \
        sorted((r["kind"], round(float(r["amount_usd"]), 6)) for r in ledger if r["kind"] != "usage")
    assert sum(r["calls"] for r in lines if r["kind"] == "usage") == len(usage)
    assert _cents(sum(Decimal(str(r["amount"])) for r in lines)) == _cents(balance)
    for run_id in (first, second):
        [line] = [r for r in lines if (r.get("session") or {}).get("id") == run_id]  # one model a session, one day
        assert Decimal(str(line["amount"])).quantize(SIX) == -per_run[run_id] and line["item"] == "Research session"
    assert not [r for r in lines if r.get("item") == "Chat" and r.get("session")]  # chat has no session page
    # Each card purchase: what the card paid (credits plus the fee, as charged) and the payment's id.
    for kind, cents in (("topup", 1055), ("autoreload", 2638)):
        [line] = [r for r in lines if r["kind"] == kind]
        row = next(r for r in ledger if r["kind"] == kind)
        assert round(line["card_charge"] * 100) == cents == next(c["cents"] for c in charges if c["metadata"]["purpose"] == kind)
        assert line["stripe_ref"] == row["stripe_ref"]
    # The sum on the page: nothing before the window, + $35 bought + the $20 welcome - usage = the balance.
    # The start takes the cents' rounding, so it reads $0.00 give or take a cent.
    math = dict(state["math"])
    assert abs(math.pop("start")) <= 0.01
    assert math == {"days": 30, "bought": 35.0, "purchases": 2, "other": 20.0,
                    "usage": float(_cents(spent_total)), "end": float(_cents(balance)),
                    "joined": True}  # a minutes-old account: the sum starts when it joined
    # A minutes-old account has no pace yet; a week-old one's runway is the balance above the research
    # floor over a week's spend (research pauses there, not at $0), and auto-reload, on with a card,
    # next charges it when the balance falls to its $8 trigger.
    assert state["pace_days"] < 1 and state["runway_days"] is None and state["reload_days"] is None
    cur.execute("UPDATE app_users SET created_at = created_at - INTERVAL 8 DAY WHERE id=%s", (uid,))
    aged = server.billing_state(ctx())
    assert aged["pace_days"] == 7.0 and aged["balance"] == state["balance"]
    per_day = float(spent_total) / 7
    assert aged["runway_days"] == round((float(balance) - float(billing.MIN_RUN_BALANCE)) / per_day, 1)
    assert balance > 8 and aged["reload_days"] == round((float(balance) - 8) / per_day, 1)
    assert aged["autoreload_charge"] == 26.38
    # The autopilot card counts to the same two points from the same ledger.
    aged_week = server._autopilot_week(cur, uid, status["research"], created_at=repo.get_user(cur, uid)["created_at"])
    assert (aged_week["runway_days"], aged_week["reload_days"]) == (aged["runway_days"], aged["reload_days"])
    # The week split by what spent it adds up to the week, and the chat turn is its own part.
    by = state["spent_7d_by"]
    assert _cents(sum(Decimal(str(v)) for v in by.values())) == _cents(state["spent_7d"])
    # The autopilot card's research is Billing's two research parts as shown, its check-ins Billing's part.
    assert Decimal(str(status["research"]["cost_7d"])) == Decimal(str(by["research"])) + Decimal(str(by["autopilot_research"]))
    assert server._autopilot_week(cur, uid, status["research"])["checkin_credits"] == by["autopilot_review"]
    assert _cents(by["research"]) == _cents(research_usd) and _cents(by["chat"]) == _cents(per_run[chat_id])
    assert state["spent_24h"] == state["spent_7d"]  # everything here happened just now
    # Each usage line says what it was for and the model's name; the invokable id never shows.
    used = [r for r in state["ledger"] if r["kind"] == "usage"]
    assert {r["item"] for r in used} == {"Research session", "Chat"}
    assert all(r["model"] and "anthropic" not in r["memo"] and "us." not in r["model"] for r in used)
    week = server._autopilot_week(cur, uid, status["research"])
    assert week["credits_left"] == float(_cents(balance)) and week["checkin_credits"] == 0.0

    # -- the receipt CSV -------------------------------------------------------------------------
    kind, fname, ctype, data = server.billing_receipt(ctx())
    assert kind == "download" and fname.startswith("tau-credits-") and ctype.startswith("text/csv")
    rows = list(csv.reader(io.StringIO(data)))
    head = {r[0]: r[1] for r in rows[:5] if len(r) == 2}
    assert head["Account"] == "credits@example.com"
    assert head["Current balance (USD)"] == _four(balance)
    assert head["Total spent (USD)"] == _four(spent_total)
    table = rows[rows.index(billing_routes.RECEIPT_HEADER) + 1:]
    assert len(table) == len(ledger)
    # Each card purchase names what the card paid and the payment; each debit names the run it billed.
    word = billing_routes.RECEIPT_TYPE  # the Type column says each kind in Billing's words
    assert sorted((r[1], r[5], r[6]) for r in table if r[1] in (word["topup"], word["autoreload"])) == sorted(
        (word[c["metadata"]["purpose"]], "%.2f" % (c["cents"] / 100), "pi_" + c["idem"]) for c in charges)
    # A research debit names its session as the Research list numbers it ("Session 2"), never the global run
    # id; the chat turn's debit says what it was in its memo, with no session.
    said = {"Session %d" % runs[r["run_id"]]["seq"] if r["run_id"] in (first, second) else "" for r in usage}
    assert sorted(r[4] for r in table if r[1] == word["usage"]) == sorted(
        "Session %d" % runs[r["run_id"]]["seq"] if r["run_id"] in (first, second) else "" for r in usage)
    assert {"Session %d" % runs[first]["seq"], "Session %d" % runs[second]["seq"], ""} == said
    assert runs[second]["seq"] == runs[first]["seq"] + 1
    assert sorted(r[1] for r in table) == sorted(word[r["kind"]] for r in ledger)
    # Each row is its ledger amount to 4 places, rounded half up from the exact decimal (-4.666650 -> -4.6667).
    assert sorted(r[2] for r in table) == sorted(_four(r["amount_usd"]) for r in ledger)
    assert _cents(sum(Decimal(r[2]) for r in table)) == _cents(balance)
    assert _cents(-sum(Decimal(r[2]) for r in table if r[1] == word["usage"])) == _cents(spent_total)

    # -- /api/me ---------------------------------------------------------------------------------
    me = server.me(ctx())
    assert me["credit_balance"] == state["balance"]
    assert me["auto_reload"] == {"amount": 25.0, "charge": 26.38, "threshold": 8.0}
    assert me["needs_card"] is False and me["free_bonus"] == 20.0


def test_an_admin_grant_never_shows_who_made_it(conn, monkeypatch):
    """An admin grant's stored memo names the admin ("Admin grant by <their email>"); the customer's
    Billing page and receipt say Tau support added the credits instead, for rows already stored too.
    The row keeps its memo (it is the record of who granted it) and its amount counts as before."""
    from app import server
    from app import repository as repo
    from app.adapters.stripe import billing
    from app.services import customer_text
    from app.web import settings
    from app.web.routes import billing as billing_routes

    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "")  # payments off: the page reads no card
    cur = conn.cursor()
    email = "grantee-%s@example.com" % uuid.uuid4().hex[:8]
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, email, "G", None)["id"]
    admin = {"id": 0, "email": settings.ADMIN_EMAIL, "name": "Admin"}
    server.admin_grant(server.Ctx(conn, admin, (), {}, {"email": email, "amount": 5}, None))
    server.admin_grant(server.Ctx(conn, admin, (), {}, {"email": email, "amount": -1.5}, None))
    cur.execute("SELECT amount_usd, memo FROM app_credit_ledger WHERE user_id=%s AND kind='admin_grant' ORDER BY id",
                (uid,))
    stored = cur.fetchall()
    assert [Decimal(r["amount_usd"]) for r in stored] == [Decimal("5"), Decimal("-1.5")]
    assert all(settings.ADMIN_EMAIL in r["memo"] for r in stored)  # the record still says who

    ctx = server.Ctx(conn, repo.get_user(cur, uid), (), {}, {}, None)
    state = server.billing_state(ctx)
    grants = [ln for ln in state["ledger"] if ln["kind"] == "admin_grant"]
    assert sorted(ln["memo"] for ln in grants) == sorted([billing_routes.ADMIN_GRANT_MEMO, billing_routes.ADMIN_DEBIT_MEMO])
    assert state["math"]["other"] == float(billing.FREE_BONUS) + 3.5  # the welcome credit and the grants
    page = json.dumps(state, default=str)
    assert settings.ADMIN_EMAIL not in page and customer_text.leaks(page) == []

    _kind, _name, _ctype, data = server.billing_receipt(ctx)
    rows = list(csv.reader(io.StringIO(data)))
    table = rows[rows.index(billing_routes.RECEIPT_HEADER) + 1:]
    assert sorted(r[3] for r in table if r[1] == billing_routes.RECEIPT_TYPE["admin_grant"]) == sorted(
        [billing_routes.ADMIN_GRANT_MEMO, billing_routes.ADMIN_DEBIT_MEMO])
    assert sorted(r[2] for r in table if r[1] == billing_routes.RECEIPT_TYPE["admin_grant"]) == ["-1.5000", "5.0000"]
    assert settings.ADMIN_EMAIL not in data
    assert customer_text.leaks(data.replace(email, "")) == []  # the account row is the customer's own address
