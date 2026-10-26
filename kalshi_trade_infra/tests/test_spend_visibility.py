"""What a paying user is told about their spend: what each charge was for, how fast they spend,
what run-until-stopped research costs an hour, and that no customer copy names a model's internal id.
Read-only figures; nothing here changes what is charged."""
import csv
import io
from datetime import datetime
from types import SimpleNamespace

from app import models_catalog, server
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


def test_billing_says_what_each_charge_was_for_without_the_model_id(monkeypatch):
    monkeypatch.setattr(server.billing, "configured", lambda: False)
    monkeypatch.setattr(server.repo, "get_stripe_customer", lambda *a: None)
    monkeypatch.setattr(server.repo, "credit_balance", lambda *a: 9.32)
    monkeypatch.setattr(server.repo, "credit_spent_total", lambda *a: 0.68)
    monkeypatch.setattr(server.repo, "usage_by_source", lambda *a: {"research": 0.4, "autopilot_research": 0.25,
                                                                   "autopilot_review": 0.02, "chat": 0.01, "other": 0.0})
    monkeypatch.setattr(server.repo, "credit_rows", lambda *a: _rows())
    ledger = server.billing_state(_ctx())["ledger"]
    assert [(r.get("item"), r.get("model")) for r in ledger] == [
        ("Autopilot research", "Claude Opus 4.6"), ("Autopilot check-in", "Claude Sonnet 4.6"),
        ("Research session", "Claude Opus 4.6"), ("Chat", "Claude Haiku 4.5"), (None, None)]
    assert ledger[0]["memo"] == "Autopilot research · Claude Opus 4.6" and ledger[4]["memo"] == "Added $10 credits"
    assert not any("anthropic" in (r["memo"] or "") for r in ledger)
    assert [r["amount"] for r in ledger] == [-0.25, -0.02, -0.4, -0.01, 10.0]  # amounts are the ledger's


def test_the_receipt_names_the_model_not_its_id(monkeypatch):
    monkeypatch.setattr(server.repo, "get_user", lambda cur, uid: {"email": "t@example.invalid"})
    monkeypatch.setattr(server.repo, "credit_balance", lambda cur, uid: 9.32)
    monkeypatch.setattr(server.repo, "credit_spent_total", lambda cur, uid: 0.68)
    monkeypatch.setattr(server.repo, "credit_rows", lambda cur, uid, limit: _rows())
    _kind, _name, _ctype, body = server.billing_receipt(_ctx())
    rows = list(csv.reader(io.StringIO(body)))
    table = rows[rows.index(["Date (UTC)", "Type", "Amount (USD)", "Memo"]) + 1:]
    assert [r[3] for r in table] == ["Autopilot research · Claude Opus 4.6", "Autopilot check-in · Claude Sonnet 4.6",
                                     "Research session · Claude Opus 4.6", "Chat · Claude Haiku 4.5", "Added $10 credits"]
    assert [r[2] for r in table] == ["-0.2500", "-0.0200", "-0.4000", "-0.0100", "10.0000"]
    assert "anthropic" not in body


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
