"""What a paying user is told about their spend: what each charge was for, how fast they spend,
what run-until-stopped research costs an hour, and that no customer copy names a model's internal id.
Read-only figures; nothing here changes what is charged."""
import csv
import io
from datetime import datetime
from types import SimpleNamespace

from app import server
from app.web.routes import billing as billing_routes
from app.adapters.llm import models_catalog
from app.adapters.db import billing_repository


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
    assert research["session"] == {"id": 108, "prompt": None, "market": "btc15m", "direction": "momentum"}
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
    assert data["balance"] == 24.995 and data["spent"] == 100.005
    assert m == {"days": 30, "start": 16.12, "bought": 65.0, "purchases": 2, "other": 5.0, "usage": 61.12, "end": 25.0}
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
        return {"s": 0, "b": 0, "stripe_customer_id": "cus_synthetic", "default_pm_id": None, "auto_reload": 0,
                "reload_amount": None, "reload_threshold": None}

    def fetchall(self):
        return []


def test_the_billing_page_reads_six_statements(monkeypatch):
    # The card, the ledger's totals (balance, all-time spend, the sum), the 7-day and 24-hour spend, the
    # week by source, and the statement: one fewer than when the balance and all-time spend were read alone.
    cur = _Counting()
    monkeypatch.setattr(server.billing, "configured", lambda: True)
    monkeypatch.setattr(server.billing, "list_cards", lambda *a: [])
    ctx = server.Ctx(SimpleNamespace(cursor=lambda: cur), _ctx().user, (), {}, {}, SimpleNamespace())
    data = server.billing_state(ctx)
    assert len(cur.sql) == 6 and len(set(cur.sql)) == 6, cur.sql
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
    _kind, _name, _ctype, body = server.billing_receipt(_ctx())
    rows = list(csv.reader(io.StringIO(body)))
    head = rows.index(billing_routes.RECEIPT_HEADER)
    assert billing_routes.RECEIPT_HEADER[4:] == ["Session", "Card charged (USD)", "Stripe reference"]
    assert [r[4:] for r in rows[head + 1:]] == [["41", "", ""], ["", "%.2f" % (server.billing.topup_charge_cents(Decimal("25")) / 100), "pi_3Reload"],
                                                ["", "", ""]]


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
    monkeypatch.setattr(server, "_TYPICAL_FOREVER_RATE", [0.0, {}])
    out = server._forever_hourly(object(), 7)
    assert out == {"yours": None, "typical": {server.catalog.DEFAULT_KEY: 3.0}}  # half an hour of your own is too little
    mine[0] = mine[1]
    assert server._forever_hourly(object(), 7)["yours"] == 1.8  # $4.50 over 2.5 hours
    assert len(reads) == 1


def test_forever_rates_read_only_sessions_that_billed_for_half_an_hour():
    cur = _Cur([{"model": "opus-4-6", "s": 3.0, "secs": 5400}, {"model": None, "s": 0, "secs": 3600}])
    assert billing_repository.forever_session_rates(cur, "since", 7) == [("opus-4-6", 3.0, 1.5)]
    sql, params = cur.sql[0]
    assert "r.run_forever=1" in sql and "secs >= 1800" in sql and params == ("since", 7, 500)
