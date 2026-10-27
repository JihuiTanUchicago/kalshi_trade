"""What a paying user is told about their spend: what each charge was for, how fast they spend,
what run-until-stopped research costs an hour, and that no customer copy names a model's internal id.
Read-only figures; nothing here changes what is charged."""
import csv
import io
from datetime import datetime
from types import SimpleNamespace

import pytest

from app import server
from app.web.routes import research as research_routes
from app.web.routes import billing as billing_routes
from app.adapters.llm import models_catalog
from app.adapters.db import billing_repository
from tests.autopilot_status_parts import stub_merged_reads


def _ctx():
    return server.Ctx(SimpleNamespace(cursor=lambda: object()),
                      {'id': 7, 'email': 'trader@example.invalid', 'name': 'S', 'picture_url': None, 'autopilot': 1},
                      (), {}, {}, SimpleNamespace())


def test_a_model_id_reads_as_its_name_and_never_as_the_id():
    assert models_catalog.label_for_model_id("us.anthropic.claude-opus-4-6-v1") == "Claude Opus 4.6"
    assert models_catalog.label_for_model_id("global.anthropic.claude-opus-4-6-v1") == "Claude Opus 4.6"  # the quota twin
    assert models_catalog.label_for_model_id("us.anthropic.claude-sonnet-5-5") == "Claude Sonnet 5.5"  # access pending
    assert models_catalog.label_for_model_id("us.amazon.nova-lite-v1:0") == "Amazon Nova Lite"
    # A retired or legacy string names its family; anything else is a plain "AI model".
    assert models_catalog.label_for_model_id("anthropic.claude-3-5-sonnet-20240620-v1:0") == "Claude Sonnet"
    assert models_catalog.label_for_model_id("mystery-model") == "AI model"
    assert models_catalog.label_for_model_id(None) == "AI model"
    for m in list(models_catalog.MODELS.values()) + models_catalog.PENDING:
        label = models_catalog.label_for_model_id(m.model_id)
        assert "anthropic." not in label and "us." not in label and ":" not in label


def _rows():
    return [
        {"kind": "usage", "amount_usd": -0.25, "memo": "Agent usage · us.anthropic.claude-opus-4-6-v1",
         "created_at": datetime(2026, 10, 25, 9), "run_kind": "research", "run_brief": 1},
        {"kind": "usage", "amount_usd": -0.02, "memo": "Agent usage · us.anthropic.claude-sonnet-4-6",
         "created_at": datetime(2026, 10, 25, 8), "run_kind": "review", "run_brief": 0},
        {"kind": "usage", "amount_usd": -0.4, "memo": "Agent usage · us.anthropic.claude-opus-4-6-v1",
         "created_at": datetime(2026, 10, 25, 7), "run_kind": "research", "run_brief": 0},
        {"kind": "usage", "amount_usd": -0.01, "memo": "Agent usage · us.anthropic.claude-haiku-4-5-20251001-v1:0",
         "created_at": datetime(2026, 10, 25, 6), "run_kind": "chat", "run_brief": 0},
        {"kind": "topup", "amount_usd": 10, "memo": "Added $10 credits", "created_at": datetime(2026, 10, 24), "run_kind": None, "run_brief": None},
    ]


def _totals(**by_kind):
    """credit_totals' answer: each kind's all-time sum, all of it inside the statement's window."""
    return {k: {"all": v, "n": 1, "since": v, "n_since": 1} for k, v in by_kind.items()}


def _line(kind, amount, at, memo, n=1, run_id=None, run_kind=None, brief=0, ref=None, first=None, day=None, **run):
    """One credit_statement row: a usage group (one run's calls with one model on one day) or a single row."""
    return {"kind": kind, "amount": amount, "run_id": run_id, "day": day or at.date(), "n": n, "first_at": first or at,
            "last_at": at, "memo": memo, "stripe_ref": ref, "run_kind": run_kind, "run_brief": brief,
            "run_prompt": run.get("prompt"), "run_market": run.get("market"), "run_direction": run.get("direction")}


def _statement_rows():
    return [_line(r["kind"], r["amount_usd"], r["created_at"], r["memo"], run_kind=r["run_kind"], brief=r["run_brief"])
            for r in _rows()]


def _billing(monkeypatch, rows, totals, configured=False):
    monkeypatch.setattr(server.billing, "configured", lambda: configured)
    monkeypatch.setattr(server.billing, "list_cards", lambda *a: [])
    monkeypatch.setattr(server.repo, "get_stripe_customer", lambda *a: None)
    monkeypatch.setattr(server.repo, "credit_spent_total", lambda *a: 0.68)
    monkeypatch.setattr(server.repo, "usage_by_source", lambda *a: {"research": 0.4, "autopilot_research": 0.25,
                                                                   "autopilot_review": 0.02, "chat": 0.01, "other": 0.0})
    seen = []
    monkeypatch.setattr(server.repo, "credit_totals", lambda *a: totals)
    monkeypatch.setattr(server.repo, "credit_statement", lambda cur, uid, since, tz, limit: seen.append((tz, limit)) or rows)
    return seen


def test_billing_says_what_each_charge_was_for_without_the_model_id(monkeypatch):
    _billing(monkeypatch, _statement_rows(), _totals(topup=10.0, usage=-0.68))
    ledger = server.billing_state(_ctx())["ledger"]
    assert [(r.get("item"), r.get("model")) for r in ledger] == [
        ("Autopilot research", "Claude Opus 4.6"), ("Autopilot check-in", "Claude Sonnet 4.6"),
        ("Research session", "Claude Opus 4.6"), ("Chat", "Claude Haiku 4.5"), (None, None)]
    assert ledger[0]["memo"] == "Autopilot research · Claude Opus 4.6" and ledger[4]["memo"] == "Added $10 credits"
    assert not any("anthropic" in (r["memo"] or "") for r in ledger)
    assert [r["amount"] for r in ledger] == [-0.25, -0.02, -0.4, -0.01, 10.0]  # amounts are the ledger's


def test_billing_lists_a_session_day_as_one_line_and_each_card_charge_with_its_reference(monkeypatch):
    from decimal import Decimal
    at = datetime(2026, 10, 25, 8, 50)
    rows = [
        _line("usage", Decimal("-12.949380"), at, "Agent usage · us.anthropic.claude-opus-4-6-v1", n=57, run_id=108,
              run_kind="research", first=datetime(2026, 10, 25, 8, 1), prompt=None, market="btc15m", direction="momentum"),
        _line("autoreload", Decimal("25"), datetime(2026, 10, 25, 8, 1), "Auto-reload $25", ref="pi_3Reload"),
        _line("usage", Decimal("-0.012600"), datetime(2026, 10, 25, 4, 1), "Agent usage · us.anthropic.claude-haiku-4-5-20251001-v1:0",
              n=3, run_id=109, run_kind="review"),
        _line("topup", Decimal("40"), datetime(2026, 10, 24, 9), "Added $40 credits", ref="pi_3Topup"),
        _line("bonus", Decimal("20"), datetime(2026, 10, 24, 8), "Welcome credits"),
    ]
    _billing(monkeypatch, rows, _totals(bonus=20.0, topup=40.0, autoreload=25.0, usage=-12.96198), configured=True)
    ledger = server.billing_state(_ctx())["ledger"]
    research, reload_, checkin, topup, bonus = ledger
    assert research["calls"] == 57 and research["amount"] == -12.94938 and research["item"] == "Research session"
    assert research["session"] == {"id": 108, "prompt": None, "title": None, "market": "btc15m", "direction": "momentum"}
    assert research["first_at"] == datetime(2026, 10, 25, 8, 1) and research["created_at"] == at and research["day"] == "2026-10-25"
    assert checkin["calls"] == 3 and "session" not in checkin  # a check-in has no session page to open
    # What the card paid: the credits plus the purchase fee, the sum billing charges; and the payment's reference.
    assert reload_["card_charge"] == server.billing.topup_charge_cents(Decimal("25")) / 100 and reload_["stripe_ref"] == "pi_3Reload"
    assert topup["card_charge"] == server.billing.topup_charge_cents(Decimal("40")) / 100 and topup["stripe_ref"] == "pi_3Topup"
    assert "card_charge" not in bonus and "stripe_ref" not in bonus and "calls" not in bonus  # free credits: no card line
    # Only what was charged or debited: never a rate, a token count or the model's id.
    for line in ledger:
        assert set(line) <= {"kind", "amount", "memo", "created_at", "first_at", "day", "item", "model", "calls",
                             "session", "card_charge", "stripe_ref"}
        assert "anthropic" not in str(line)


def test_the_balance_sum_closes_to_the_cent(monkeypatch):
    # 30 days ago + bought + other - usage = now, each in cents; the start takes the rounding.
    totals = {"bonus": {"all": 20.0, "n": 1, "since": 0.0, "n_since": 0},
              "topup": {"all": 50.0, "n": 2, "since": 40.0, "n_since": 1},
              "autoreload": {"all": 50.0, "n": 2, "since": 25.0, "n_since": 1},
              "admin_grant": {"all": 5.0, "n": 1, "since": 5.0, "n_since": 1},
              "usage": {"all": -100.004999, "n": 900, "since": -61.115005, "n_since": 600}}
    _billing(monkeypatch, [], totals)
    data = server.billing_state(_ctx())
    m = data["math"]
    # The balance as the ledger holds it (the page rounds it half up: $25.00, the math's end); the
    # spend to the cent from its exact decimal. Through four places it read 100.005, then $100.01.
    assert data["balance"] == 24.995001 and data["spent"] == 100.0
    assert m == {"days": 30, "start": 16.12, "bought": 65.0, "purchases": 2, "other": 5.0, "usage": 61.12, "end": 25.0, "joined": False}
    cents = lambda v: round(v * 100)
    assert cents(m["start"]) + cents(m["bought"]) + cents(m["other"]) - cents(m["usage"]) == cents(m["end"])


def test_a_day_the_line_cap_cuts_is_left_out_whole(monkeypatch):
    rows = [_line("usage", -1.0, datetime(2026, 10, 25, h), "Agent usage · x", run_id=h, run_kind="chat") for h in (9, 8)]
    rows.append(_line("usage", -1.0, datetime(2026, 10, 24, 9), "Agent usage · x", run_id=1, run_kind="chat"))
    monkeypatch.setattr(billing_routes, "STATEMENT_LINES", 3)
    _billing(monkeypatch, rows, _totals(usage=-3.0))
    data = server.billing_state(_ctx())
    assert data["ledger_cut"] is True and [r["day"] for r in data["ledger"]] == ["2026-10-25", "2026-10-25"]
    monkeypatch.setattr(billing_routes, "STATEMENT_LINES", 4)
    data = server.billing_state(_ctx())
    assert data["ledger_cut"] is False and len(data["ledger"]) == 3


def test_the_statement_days_are_the_viewers(monkeypatch):
    seen = _billing(monkeypatch, [], {})
    for query, tz in (({"tz": "240"}, 240), ({"tz": "-330"}, -330), ({}, 0), ({"tz": "x"}, 0), ({"tz": "9999"}, 0)):
        ctx = _ctx()
        ctx.query = query
        server.billing_state(ctx)
        assert seen[-1] == (tz, billing_routes.STATEMENT_LINES)


def test_the_statement_sql_groups_usage_by_run_day_and_model_for_one_user():
    cur = _Cur([])
    billing_repository.credit_statement(cur, 7, "since", 240, 300)
    sql, params = cur.sql[0]
    assert "GROUP BY l.run_id, DATE(l.created_at - INTERVAL %s MINUTE), l.memo" in sql
    assert sql.count("l.user_id=%s") == 2 and "LIMIT %s" in sql
    assert params == (240, 7, "since", 240, 240, 7, "since", 300)


class _Counting:
    """Answers every read with nothing (an aggregate reads 0), and counts the statements."""

    def __init__(self):
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append((" ".join(sql.split()), tuple(params or ())))

    def fetchone(self):
        if "FROM app_notifications" in self.sql[-1][0]:
            return None  # no failed auto-reload to tell
        return {"s": 0, "b": 0, "stripe_customer_id": "cus_synthetic", "default_pm_id": None, "auto_reload": 0,
                "reload_amount": None, "reload_threshold": None}

    def fetchall(self):
        return []


def test_the_billing_page_reads_seven_statements(monkeypatch):
    # The card, the ledger's totals (balance, all-time spend, the sum), the 7-day and 24-hour spend, the
    # week by source, and the statement: one fewer than when the balance and all-time spend were read alone.
    # With a card on file, one more: the last failed auto-reload (the ledger's last auto-reload is read
    # only when there is one).
    cur = _Counting()
    monkeypatch.setattr(server.billing, "configured", lambda: True)
    monkeypatch.setattr(server.billing, "list_cards", lambda *a: [])
    ctx = server.Ctx(SimpleNamespace(cursor=lambda: cur), _ctx().user, (), {}, {}, SimpleNamespace())
    data = server.billing_state(ctx)
    assert len(cur.sql) == 7 and len(set(cur.sql)) == 7, cur.sql
    assert data["balance"] == 0 and data["ledger"] == [] and data["math"]["end"] == 0


def test_the_receipt_names_the_model_not_its_id(monkeypatch):
    monkeypatch.setattr(server.repo, "get_user", lambda cur, uid: {"email": "t@example.invalid"})
    monkeypatch.setattr(server.repo, "credit_balance", lambda cur, uid: 9.32)
    monkeypatch.setattr(server.repo, "credit_spent_total", lambda cur, uid: 0.68)
    monkeypatch.setattr(server.repo, "credit_rows", lambda cur, uid, limit: _rows())
    _kind, _name, _ctype, body = server.billing_receipt(_ctx())
    rows = list(csv.reader(io.StringIO(body)))
    table = rows[rows.index(billing_routes.RECEIPT_HEADER) + 1:]
    assert [r[3] for r in table] == ["Autopilot research · Claude Opus 4.6", "Autopilot check-in · Claude Sonnet 4.6",
                                     "Research session · Claude Opus 4.6", "Chat · Claude Haiku 4.5", "Added $10 credits"]
    assert [r[2] for r in table] == ["-0.2500", "-0.0200", "-0.4000", "-0.0100", "10.0000"]
    assert "anthropic" not in body


def test_the_receipt_says_each_card_charge_its_reference_and_each_debits_session(monkeypatch):
    from decimal import Decimal
    monkeypatch.setattr(server.repo, "get_user", lambda cur, uid: {"email": "t@example.invalid"})
    monkeypatch.setattr(server.repo, "credit_balance", lambda cur, uid: 9.32)
    monkeypatch.setattr(server.repo, "credit_spent_total", lambda cur, uid: 0.68)
    monkeypatch.setattr(server.repo, "credit_rows", lambda cur, uid, limit: [
        {"kind": "usage", "amount_usd": Decimal("-0.25"), "memo": "Agent usage · us.anthropic.claude-opus-4-6-v1",
         "created_at": datetime(2026, 10, 25, 9), "run_id": 41, "stripe_ref": None, "run_kind": "research", "run_brief": 0},
        {"kind": "autoreload", "amount_usd": Decimal("25"), "memo": "Auto-reload $25", "created_at": datetime(2026, 10, 25, 8),
         "run_id": None, "stripe_ref": "pi_3Reload", "run_kind": None, "run_brief": None},
        {"kind": "bonus", "amount_usd": Decimal("20"), "memo": "Welcome credits", "created_at": datetime(2026, 10, 24),
         "run_id": None, "stripe_ref": None, "run_kind": None, "run_brief": None},
    ])
    # Run 41 is the user's third research session: the receipt says "Session 3", as the Research list does,
    # never the global run id.
    numbers = []
    monkeypatch.setattr(server.repo, "research_session_numbers", lambda cur, uid: numbers.append(uid) or {12: 1, 30: 2, 41: 3})
    _kind, _name, _ctype, body = server.billing_receipt(_ctx())
    rows = list(csv.reader(io.StringIO(body)))
    head = rows.index(billing_routes.RECEIPT_HEADER)
    assert billing_routes.RECEIPT_HEADER[4:] == ["Session", "Card charged (USD)", "Stripe reference"]
    assert [r[4:] for r in rows[head + 1:]] == [["Session 3", "", ""], ["", "%.2f" % (server.billing.topup_charge_cents(Decimal("25")) / 100), "pi_3Reload"],
                                                ["", "", ""]]
    assert len(numbers) == 1  # one read of the numbers, only because a research debit is in the file


def test_the_receipts_type_column_says_each_line_in_billings_words_never_the_ledger_key(monkeypatch):
    # Walk 2026-10-27: the receipt's Type column read "usage", "topup", "autoreload", "bonus", "admin_grant",
    # the ledger's own keys, beside a statement that says "Agent usage", "Added credits", "Auto-reload".
    import json
    import re
    from decimal import Decimal
    from pathlib import Path
    monkeypatch.setattr(server.repo, "get_user", lambda cur, uid: {"email": "t@example.invalid"})
    monkeypatch.setattr(server.repo, "credit_balance", lambda cur, uid: 9.32)
    monkeypatch.setattr(server.repo, "credit_spent_total", lambda cur, uid: 0.68)
    line = lambda kind, amount, memo: {"kind": kind, "amount_usd": Decimal(amount), "memo": memo, "created_at": datetime(2026, 10, 25),
                                       "run_id": None, "stripe_ref": None, "run_kind": None, "run_brief": None}
    monkeypatch.setattr(server.repo, "credit_rows", lambda cur, uid, limit: [
        line("usage", "-0.25", "Agent usage · us.anthropic.claude-opus-4-6-v1"), line("autoreload", "25", "Auto-reload $25"),
        line("topup", "10", "Added $10 credits"), line("admin_grant", "5", "Admin grant by someone"), line("bonus", "20", "Welcome credits"),
        line("promo_credit", "3", "Promo")])
    _kind, _name, _ctype, body = server.billing_receipt(_ctx())
    rows = list(csv.reader(io.StringIO(body)))
    table = rows[rows.index(billing_routes.RECEIPT_HEADER) + 1:]
    assert [r[1] for r in table] == ["Agent usage", "Auto-reload", "Added credits", "Credits from Tau support", "Welcome credits",
                                     "Promo credit"]
    assert not {"usage", "autoreload", "topup", "admin_grant", "bonus"} & {r[1] for r in table}
    # The same words as Billing's statement in both bundles (their KIND_LABEL).
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    for bundle in ("app.js", "app.meridian.js"):
        found = re.search(r"const KIND_LABEL = (\{[^}]*\});", (static / bundle).read_text())
        assert found, bundle
        labels = json.loads(re.sub(r"(\w+):", r'"\1":', found.group(1)).replace("'", '"'))
        assert labels == billing_routes.RECEIPT_TYPE, bundle


def test_the_statement_of_an_account_younger_than_it_starts_when_the_account_joined(monkeypatch):
    # Walk 2026-10-27: a subscriber of a day read "Balance 30 days ago $0.00" for an account that didn't exist.
    monkeypatch.setattr(server.repo, "credit_statement", lambda cur, uid, since, tz, limit: [])
    since = datetime(2026, 9, 27)
    welcome = {"bonus": {"all": 20.0, "n": 1, "since": 20.0, "n_since": 1}}
    new = billing_routes._statement(object(), 7, since, 0, welcome, 20.0, datetime(2026, 10, 26))
    assert new["math"]["joined"] is True and new["math"]["start"] == 0.0
    old = billing_routes._statement(object(), 7, since, 0, welcome, 20.0, datetime(2026, 8, 1))
    assert old["math"]["joined"] is False
    # A balance before the window means it existed then: never "when you joined" over a non-zero start.
    carried = billing_routes._statement(object(), 7, since, 0, {"bonus": {"all": 20.0, "n": 1, "since": 0.0, "n_since": 0}},
                                        20.0, datetime(2026, 10, 26))
    assert carried["math"]["joined"] is False and carried["math"]["start"] == 20.0
    assert billing_routes._statement(object(), 7, since, 0, welcome, 20.0)["math"]["joined"] is False  # age unknown


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def execute(self, sql, params=()):
        self.sql.append((sql, params))

    def fetchall(self):
        return self.rows


def test_usage_by_source_splits_the_week_by_what_spent_it():
    cur = _Cur([{"run_kind": "research", "brief": 0, "s": 4.0}, {"run_kind": "research", "brief": 1, "s": 2.5},
                {"run_kind": "review", "brief": 0, "s": 0.5}, {"run_kind": "chat", "brief": 0, "s": 0.25},
                {"run_kind": None, "brief": 0, "s": 0.1}])
    out = billing_repository.usage_by_source(cur, 7, "since")
    assert out == {"research": 4.0, "autopilot_research": 2.5, "autopilot_review": 0.5, "chat": 0.25, "other": 0.1}
    sql, params = cur.sql[0]
    assert "l.kind='usage'" in sql and params == (7, "since")


def test_run_until_stopped_costs_an_hour_at_recent_rates(monkeypatch):
    # Yours: dollars over hours, pooled over your own such sessions once they add up to an hour.
    # Typical: the median session's rate per model, only with enough sessions behind it. Cached.
    mine = [[("opus-4-6", 1.0, 0.5)], [("opus-4-6", 1.0, 0.5), (None, 3.5, 2.0)]]
    everyone = [(None, 2.0, 1.0), (None, 3.0, 1.0), ("opus-4-6", 4.0, 1.0), (None, 6.0, 2.0), (None, 10.0, 2.0),
                ("haiku-4-5", 0.1, 1.0)]
    reads = []

    def rates(cur, since, user_id=None, limit=500):
        if user_id is None:
            reads.append(since)
            return everyone
        return mine[0]
    monkeypatch.setattr(server.repo, "forever_session_rates", rates)
    monkeypatch.setattr(research_routes, "_TYPICAL_FOREVER_RATE", [0.0, {}])
    out = server._forever_hourly(object(), 7)
    assert out == {"yours": None, "yours_by_model": {}, "typical": {server.catalog.DEFAULT_KEY: 3.0}}  # half an hour of your own is too little
    mine[0] = mine[1]
    assert server._forever_hourly(object(), 7)["yours"] == 1.8  # $4.50 over 2.5 hours
    assert server._forever_hourly(object(), 7)["yours_by_model"] == {server.catalog.DEFAULT_KEY: 1.8}  # NULL ran on the default
    assert len(reads) == 1


def test_forever_rates_read_only_sessions_that_billed_for_half_an_hour():
    cur = _Cur([{"model": "opus-4-6", "s": 3.0, "secs": 5400}, {"model": None, "s": 0, "secs": 3600}])
    assert billing_repository.forever_session_rates(cur, "since", 7) == [("opus-4-6", 3.0, 1.5)]
    sql, params = cur.sql[0]
    assert "r.run_forever=1" in sql and "secs >= 1800" in sql and params == ("since", 7, 500)


@pytest.mark.parametrize("charge,cents", [("0.105000", 0.11), ("0.104999", 0.10), ("1.005000", 1.01), ("0.115000", 0.12)])
def test_one_charge_reads_the_same_on_every_surface(monkeypatch, charge, cents):
    """A $0.105 research charge read $0.10 on the autopilot panel (float round()) and -$0.11 on Billing
    (Decimal, half up). Every figure that shows it is now the same cents, half up from the exact
    decimal; Billing's line keeps the ledger's exact amount, which the page rounds the same way.
    Credits only: no P&L is read or added here."""
    from decimal import Decimal
    from app.web import views

    usd = float(Decimal(charge))
    at = datetime(2026, 10, 25, 9)
    rows = [_line("usage", -Decimal(charge), at, "Agent usage · us.anthropic.claude-opus-4-6-v1", run_id=42,
                  run_kind="research", brief=1, prompt="Idea", market="btc15m", direction="momentum")]
    _billing(monkeypatch, rows, _totals(bonus=20.0, usage=-usd), configured=True)
    monkeypatch.setattr(server.repo, "credit_spent_total", lambda *a: usd)
    by_source = {"research": 0.0, "autopilot_research": usd, "autopilot_review": usd, "chat": 0.0, "other": 0.0}
    monkeypatch.setattr(server.repo, "usage_by_source", lambda *a: dict(by_source))
    run = {"id": 42, "kind": "research", "status": "succeeded", "run_forever": 0, "direction": "momentum", "market": "btc15m"}
    monkeypatch.setattr(server.repo, "runs_spent", lambda cur, uid, ids: {42: usd})
    monkeypatch.setattr(server.repo, "list_runs", lambda cur, uid, limit=50: [dict(run)])
    monkeypatch.setattr(server.repo, "get_run", lambda cur, uid, rid: dict(run))
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "get_policy", lambda *a: None)
    monkeypatch.setattr(server.repo, "latest_dream_event", lambda *a: None)
    monkeypatch.setattr(server.repo, "run_events", lambda *a: [])
    monkeypatch.setattr(server.repo, "active_run_counts", lambda *a, **k: {})
    monkeypatch.setattr(server.repo, "list_runs_version", lambda cur, uid: [dict(run)])
    monkeypatch.setattr(research_routes, "_research_totals", lambda *a: {})
    monkeypatch.setattr(server.repo, "research_week", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "strategies_passed_since", lambda *a: 0)
    monkeypatch.setattr(server.repo, "research_spent_since", lambda *a: usd)
    stub_merged_reads(monkeypatch)  # the autopilot panel's merged reads, from the single reads stubbed here
    monkeypatch.setattr(server.repo, "autopilot_paper_week", lambda *a: {"started": 0, "pnl": 0.0, "trades": 0})
    monkeypatch.setattr(server.repo, "activity_since", lambda *a: {"autopilot": {}, "runs": {}, "spent": {"since": usd, "week": usd}})
    monkeypatch.setattr(server.repo, "passed_since", lambda *a, **k: {})
    monkeypatch.setattr(server.repo, "finished_session_costs", lambda *a: [usd] * server.SESSION_COST_MIN_OWN)
    monkeypatch.setattr(server.repo, "finished_session_costs_by_model", lambda *a: [(None, usd)] * server.SESSION_COST_MIN_OWN)
    monkeypatch.setattr(research_routes, "_TYPICAL_SESSION_COST", [0.0, {}])
    monkeypatch.setattr(server.repo, "recent_session_costs", lambda *a: [("m", usd)] * server.SESSION_COST_MIN_TYPICAL)
    monkeypatch.setattr(research_routes, "_forever_hourly", lambda *a: {"yours": None, "typical": {}})
    balance = 20 - usd
    reads = SimpleNamespace(balance=lambda: balance, customer=lambda: None)

    state = server.billing_state(_ctx())
    research = server._research_activity(None, 7)
    week = server._autopilot_week(None, 7, research, reads)
    ctx = _ctx()
    ctx.params = ("42",)
    estimate = server.research_estimate(_ctx())
    seen = {
        "Billing: agent usage": state["math"]["usage"],
        "Billing: spent, last 7 days": state["spent_7d"],
        "Billing: last 24 hours": state["spent_24h"],
        "Billing: all time": state["spent"],
        "Billing: autopilot research this week": state["spent_7d_by"]["autopilot_research"],
        "Autopilot panel: research spent": research["cost_7d"],
        "Autopilot scorecard: credits spent on research": week["research_credits"],
        "Autopilot scorecard: check-ins": week["checkin_credits"],
        "Dashboard: spent since your last visit": server._since_visit(None, 7, at, False, {})["spent"]["since"],
        "Research list: session cost": server.list_runs(_ctx())["runs"][0]["spent_usd"],
        "Run page: session cost": server.get_run(ctx)["run"]["spent_usd"],
        "Research form: what your sessions usually cost": estimate["yours"],
        "Research form: what your sessions on this model usually cost": estimate["yours_by_model"][models_catalog.DEFAULT_KEY],
        "Research form: what a session usually costs": estimate["typical"][models_catalog.resolve("m").key],
    }
    assert seen == {k: cents for k in seen}
    # Billing's line is the ledger's exact amount; the page rounds it half up to the same cents.
    [line] = state["ledger"]
    assert line["amount"] == -usd and float(views.credit_cents(-line["amount"])) == cents
    # A balance is sent as the ledger holds it, for the page to round the same way.
    assert week["credits_left"] == float(views.credit_cents(balance)) == state["math"]["end"]


def test_credit_rounding_is_half_up_from_the_ledgers_decimal():
    from decimal import Decimal
    from app.web import views

    assert round(0.105, 2) == 0.1  # what the panel did
    assert views.credit_usd(0.105) == 0.11 and views.credit_usd(-0.105) == -0.11
    assert views.credit_usd(0.035 + 0.07) == 0.11  # 0.10500000000000001
    assert views.credit_usd(0.10499999999999998) == 0.11  # float noise past the ledger's six places
    assert views.credit_usd(0.104999) == 0.1 and views.credit_usd(None) == 0.0
    assert str(views.credit_usd(-0.001)) == "0.0"  # never "-0.0" in the JSON
    assert views.credit_exact(24.995001) == 24.995001 and views.credit_exact(0.1 + 0.2) == 0.3
    assert billing_routes._cents is views.credit_cents  # Billing's sum rounds the one way too
    assert views.credit_cents(Decimal("-100.004999")) == Decimal("-100.00")
