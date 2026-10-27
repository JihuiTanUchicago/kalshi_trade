"""A research session the autopilot's research floor started is named for the customer, not by its
instruction to the agent ("Research floor: no research started for a while, so pick ..."), on the
research list, the session page and the billing line. The stored prompt is unchanged: the agent reads it."""
from types import SimpleNamespace

from app import server, worker
from app.web import views
from app.web.routes import research as research_routes


def test_a_floor_session_is_titled_by_what_it_set_out_to_do():
    assert views.session_title(worker.RESEARCH_FLOOR_IDEA, "btc15m") == "New idea picked by the autopilot for Bitcoin up or down in 15 minutes"
    assert views.session_title("  " + worker.RESEARCH_FLOOR_IDEA + "\n", "btc_daily") == \
        "New idea picked by the autopilot for Bitcoin above $X at 5pm ET"
    # Before the agent picked a market, and on a market no longer listed.
    assert views.session_title(worker.RESEARCH_FLOOR_IDEA, None).endswith("for the market it picks")
    assert views.session_title(worker.RESEARCH_FLOOR_IDEA, "gone_market").endswith("for the market it picks")


def test_an_idea_in_words_keeps_its_own_title():
    for prompt in ("Fade late YES takers in the last 3 minutes", "Angle: the 5pm ladder misprices far strikes", "", None):
        assert views.session_title(prompt, "btc15m") is None


def _ctx():
    return server.Ctx(SimpleNamespace(cursor=lambda: None), {"id": 7}, (), {}, {}, None)


def test_the_list_and_the_run_page_carry_the_title_and_leave_the_prompt(monkeypatch):
    rows = [{"id": 2, "status": "succeeded", "run_forever": 0, "direction": None, "brief": 1,
             "prompt": worker.RESEARCH_FLOOR_IDEA, "market": "btc15m"},
            {"id": 1, "status": "succeeded", "run_forever": 0, "direction": None, "prompt": "Fade late takers", "market": "btc15m"}]
    monkeypatch.setattr(server.repo, "get_policy", lambda cur, uid: None)
    monkeypatch.setattr(server.repo, "list_runs", lambda cur, uid: [dict(r) for r in rows])
    monkeypatch.setattr(server.repo, "runs_spent", lambda cur, uid, ids: {})
    monkeypatch.setattr(server.repo, "active_run_counts", lambda cur, uid, silent_before=None: {})
    monkeypatch.setattr(server.repo, "list_runs_version", lambda cur, uid: rows)
    monkeypatch.setattr(research_routes, "_research_totals", lambda cur, uid: {"tried": 0, "passed": 0})
    out = {r["id"]: r for r in server.list_runs(_ctx())["runs"]}
    assert out[2]["title"] == "New idea picked by the autopilot for Bitcoin up or down in 15 minutes"
    assert out[2]["prompt"] == worker.RESEARCH_FLOOR_IDEA
    assert out[1]["title"] is None

    monkeypatch.setattr(server.repo, "get_run", lambda cur, uid, rid: dict(rows[0], kind="research"))
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "run_events", lambda *a: [])
    monkeypatch.setattr(research_routes, "_last_dream", lambda cur, uid: None)
    ctx = _ctx()
    ctx.query["id"] = "2"
    monkeypatch.setattr(research_routes, "_int_param", lambda c: 2)
    assert server.get_run(ctx)["run"]["title"] == "New idea picked by the autopilot for Bitcoin up or down in 15 minutes"


def test_the_billing_line_names_a_floor_session_the_same_way(monkeypatch):
    from datetime import datetime
    from decimal import Decimal
    at = datetime(2026, 10, 25, 8, 50)
    row = {"kind": "usage", "amount": Decimal("-1.92"), "run_id": 3, "day": at.date(), "n": 12, "first_at": at, "last_at": at,
           "memo": "Agent usage", "stripe_ref": None, "run_kind": "research", "run_brief": 1,
           "run_prompt": worker.RESEARCH_FLOOR_IDEA, "run_market": "btc15m", "run_direction": None}
    monkeypatch.setattr(server.billing, "configured", lambda: False)
    monkeypatch.setattr(server.billing, "list_cards", lambda *a: [])
    monkeypatch.setattr(server.repo, "get_stripe_customer", lambda *a: None)
    monkeypatch.setattr(server.repo, "credit_spent_total", lambda *a: 1.92)
    monkeypatch.setattr(server.repo, "usage_by_source", lambda *a: {"autopilot_research": 1.92})
    monkeypatch.setattr(server.repo, "credit_totals", lambda *a: {"usage": {"all": -1.92, "n": 1, "since": -1.92, "n_since": 1}})
    monkeypatch.setattr(server.repo, "credit_statement", lambda *a: [row])
    session = server.billing_state(_ctx())["ledger"][0]["session"]
    assert session["title"] == "New idea picked by the autopilot for Bitcoin up or down in 15 minutes"
