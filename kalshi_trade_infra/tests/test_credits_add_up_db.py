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
        assert runs[run_id]["spent_usd"] == float(rows.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        assert server.get_run(ctx(params=(run_id,)))["run"]["spent_usd"] == runs[run_id]["spent_usd"]
    [example] = [r for r in runs.values() if r["example"]]
    assert example["spent_usd"] == 0 and example["status"] == "succeeded"  # the seeded session cost nothing
    assert chat_id not in runs  # the research list shows research sessions only

    # -- the research form's estimate follows from those two sessions ----------------------------
    est = server.research_estimate(ctx())
    # Three finished research sessions exist, but the seeded random-walk example is left out, and
    # two of your own are fewer than SESSION_COST_MIN_OWN, so "yours" is not shown yet.
    assert est["sessions"] == 2 and est["yours"] is None and server.SESSION_COST_MIN_OWN > 2
    monkeypatch.setattr(server, "SESSION_COST_MIN_OWN", 2)
    median = (per_run[first] + per_run[second]) / 2
    assert server.research_estimate(ctx())["yours"] == float(_cents(median))

    # -- research cost this week: research debits only, never chat ------------------------------
    research_usd = per_run[first] + per_run[second]
    since = repo.now_utc() - server.timedelta(days=7)
    assert Decimal(str(repo.research_spent_since(cur, uid, since))).quantize(SIX) == research_usd
    status = server.autopilot_status(ctx())
    assert status["research"]["cost_7d"] == float(_cents(research_usd))
    assert server._autopilot_week(cur, uid, status["research"])["research_credits"] == status["research"]["cost_7d"]
    assert spent_total - research_usd == per_run[chat_id] > 0  # the chat turn is billed, just not as research

    # -- the Billing page ------------------------------------------------------------------------
    state = server.billing_state(ctx())
    assert state["configured"] is True and state["default_pm"] == "pm_credits" and state["auto_reload"] is True
    assert state["balance"] == float(balance.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    assert state["spent"] == state["spent_7d"] == float(spent_total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    assert len(state["ledger"]) == len(ledger)  # under the page's 50-row window, so every row is listed
    assert sorted(round(r["amount"], 6) for r in state["ledger"]) == sorted(round(float(r["amount_usd"]), 6) for r in ledger)
    assert _cents(sum(Decimal(str(r["amount"])) for r in state["ledger"])) == _cents(balance)
    assert state["runway_days"] == round(state["balance"] / (state["spent_7d"] / 7), 1)
    # The week split by what spent it adds up to the week, and the chat turn is its own part.
    by = state["spent_7d_by"]
    assert _cents(sum(Decimal(str(v)) for v in by.values())) == _cents(state["spent_7d"])
    assert _cents(by["research"]) == _cents(research_usd) and _cents(by["chat"]) == _cents(per_run[chat_id])
    assert state["spent_24h"] == state["spent_7d"]  # everything here happened just now
    # Each usage line says what it was for and the model's name; the invokable id never shows.
    used = [r for r in state["ledger"] if r["kind"] == "usage"]
    assert {r["item"] for r in used} == {"Research session", "Chat"}
    assert all(r["model"] and "anthropic" not in r["memo"] and "us." not in r["model"] for r in used)
    week = server._autopilot_week(cur, uid, status["research"])
    assert week["credits_left"] == round(state["balance"], 2) and week["checkin_credits"] == 0.0

    # -- the receipt CSV -------------------------------------------------------------------------
    kind, fname, ctype, data = server.billing_receipt(ctx())
    assert kind == "download" and fname.startswith("tau-credits-") and ctype.startswith("text/csv")
    rows = list(csv.reader(io.StringIO(data)))
    head = {r[0]: r[1] for r in rows[:5] if len(r) == 2}
    assert head["Account"] == "credits@example.com"
    assert head["Current balance (USD)"] == _four(balance)
    assert head["Total spent (USD)"] == _four(spent_total)
    table = rows[rows.index(["Date (UTC)", "Type", "Amount (USD)", "Memo"]) + 1:]
    assert len(table) == len(ledger)
    assert sorted(r[1] for r in table) == sorted(r["kind"] for r in ledger)
    # Each row is its ledger amount to 4 places, rounded half up from the exact decimal (-4.666650 -> -4.6667).
    assert sorted(r[2] for r in table) == sorted(_four(r["amount_usd"]) for r in ledger)
    assert _cents(sum(Decimal(r[2]) for r in table)) == _cents(balance)
    assert _cents(-sum(Decimal(r[2]) for r in table if r[1] == "usage")) == _cents(spent_total)

    # -- /api/me ---------------------------------------------------------------------------------
    me = server.me(ctx())
    assert me["credit_balance"] == state["balance"]
    assert me["auto_reload"] == {"amount": 25.0, "charge": 26.38, "threshold": 8.0}
    assert me["needs_card"] is False and me["free_bonus"] == 20.0
