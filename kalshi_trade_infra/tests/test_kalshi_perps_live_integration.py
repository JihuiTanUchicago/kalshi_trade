"""Authenticated adapter and agent boundaries; no credentials or provider calls."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import schema, server
from app.adapters.llm import llm
from app.adapters.stripe import billing
from app.research import agent
from app.adapters.kalshi_perps import kalshi_perps_trading as live


def ctx(body=None, params=()):
    return server.Ctx(SimpleNamespace(cursor=lambda: object()), {"id": 17}, params, {}, body or {}, None)


@pytest.mark.parametrize("name,body,params,args", [
    ("account", None, (), ()),
    ("policy", {"enabled": False}, (), ({"enabled": False},)),
    ("draft", {"count": "1"}, (), ({"count": "1"},)),
    ("proposal", {"request_key": "synthetic"}, ("4",), (4, {"request_key": "synthetic"})),
])
def test_read_and_preview_routes_bind_authenticated_owner(monkeypatch, name, body, params, args):
    method = {"account": "overview", "policy": "save_policy", "draft": "create_order",
              "proposal": "preview_proposal"}[name]
    seen = []
    monkeypatch.setattr(live, method, lambda *a: seen.append(a) or {"synthetic": True})
    context = ctx(body, params)
    assert getattr(server, "kalshi_perps_live_" + name)(context) == {"synthetic": True}
    assert seen == [(context.conn, 17, *args)]


@pytest.mark.parametrize("action", ["submit", "refresh", "cancel"])
def test_order_actions_are_owner_scoped_and_do_not_implicitly_confirm(monkeypatch, action):
    seen = []
    monkeypatch.setattr(live, action + "_order", lambda *a: seen.append(a) or {"order": {}})
    context = ctx({}, ("9", action))
    assert server.kalshi_perps_live_action(context) == {"order": {}}
    expected = (context.conn, 17, 9) if action == "refresh" else (context.conn, 17, 9, {})
    assert seen == [expected]


def test_live_service_errors_preserve_safe_status(monkeypatch):
    def denied(*args):
        raise live.Error("Explicit confirmation required.", status=409, code="confirmation_required")
    monkeypatch.setattr(live, "submit_order", denied)
    with pytest.raises(server.ApiError, match="confirmation") as error:
        server.kalshi_perps_live_action(ctx({}, ("9", "submit")))
    assert error.value.status == 409


def test_all_new_routes_require_login_and_mutations_use_existing_post_csrf_boundary():
    routes = [r for r in server.ROUTES if "/api/kalshi/perps/live" in r[1].pattern]
    assert len(routes) == 5
    assert all(r[3] is True for r in routes)
    assert [r[0] for r in routes].count("GET") == 1
    assert [r[0] for r in routes].count("POST") == 4
    assert any("app_kalshi_perps_settings" in ddl for ddl in schema.DDL)
    assert any("app_kalshi_perps_orders" in ddl for ddl in schema.DDL)


@pytest.mark.parametrize("autopilot", [False, True])
def test_agent_can_only_propose_a_live_order_even_with_autopilot(monkeypatch, autopilot):
    seen = []
    monkeypatch.setattr(live, "propose_for_agent", lambda *args: seen.append(args) or ("Review order", 3))
    action = {"type": "kalshi_perps_order", "side": "bid", "count": "1", "price": "7"}
    cursor = object()
    assert agent.act(cursor, {"id": 17}, action, autopilot) == ("Review order", 3)
    assert seen == [(cursor, 17, {k: v for k, v in action.items() if k != "type"})]
    with pytest.raises(ValueError, match="exact-ticket confirmation"):
        agent.apply_proposal(cursor, 17, {"kind": "kalshi_perps_live"})


def test_generic_approve_routes_to_review_instead_of_broker_submission(monkeypatch):
    monkeypatch.setattr(server.repo, "get_proposal", lambda *args: {"kind": "kalshi_perps_live"})
    seen = []
    monkeypatch.setattr(live, "decide_proposal", lambda *args: seen.append(args) or {
        "review_required": True, "review_url": "/funds?perps_proposal=4"})
    monkeypatch.setattr(agent, "apply_proposal", lambda *args: pytest.fail("Generic apply bypassed exact ticket"))
    context = ctx({}, ("4", "approve"))
    assert server.decide_proposal(context)["review_required"] is True
    assert seen == [(context.conn, 17, 4, "approve")]


def test_preserved_production_stall_falls_back_without_daily_quota_cooldown(monkeypatch):
    from app.adapters.llm import models_catalog
    monkeypatch.setattr(models_catalog, "fallback_chain_from", lambda *args: ["synthetic-a", "synthetic-b"])
    monkeypatch.setattr(llm, "_MODEL_COOLDOWN", {})
    seen = []
    def once(system, messages, model, on_delta):
        seen.append(model)
        if model == "synthetic-a":
            raise llm.LLMStalled("Synthetic stall")
        return "recovered", {"input_tokens": 0, "output_tokens": 0}
    monkeypatch.setattr(llm, "_bedrock_once", once)
    assert llm._bedrock("synthetic", [], model="synthetic-a")[0] == "recovered"
    assert seen == ["synthetic-a", "synthetic-b"]
    assert llm._MODEL_COOLDOWN == {}


@pytest.mark.parametrize("balance,ready", [("0.99", False), ("1.00", True)])
def test_preserved_production_billing_headroom(monkeypatch, balance, ready):
    from app import repository
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "synthetic")
    monkeypatch.setattr(billing, "MIN_RUN_BALANCE", Decimal("1.00"))
    monkeypatch.setattr(repository, "get_stripe_customer", lambda *args: {"default_pm_id": "synthetic"})
    monkeypatch.setattr(repository, "credit_balance", lambda *args: Decimal(balance))
    assert billing.is_ready(object(), 17) is ready


@pytest.mark.parametrize("autopilot", [False, True])
def test_actual_agent_envelope_creates_only_a_reviewable_owned_proposal(monkeypatch, autopilot):
    monkeypatch.setenv("TAU_KALSHI_PERPS_LIVE_ENABLED", "1")
    monkeypatch.setenv("TAU_KALSHI_PERPS_LIVE_ENVIRONMENT", "production")
    monkeypatch.setattr(live.store, "lock_user", lambda *args: None)
    monkeypatch.setattr(live.store, "get_settings", lambda *args: {"enabled": True})
    monkeypatch.setattr(live.repo, "get_kalshi_key", lambda *args: {
        "key_id": "synthetic", "private_key_enc": b"synthetic"})
    monkeypatch.setattr(live, "_client", lambda *args: pytest.fail("Agent proposal made broker I/O"))
    seen = []
    monkeypatch.setattr(live.repo, "create_proposal", lambda *args, **kw: seen.append((args, kw)) or 44)
    cursor = object()
    message, proposal_id = agent.act(cursor, {"id": 17}, {
        "type": "kalshi_perps_order", "side": "bid", "count": "1", "price": "7.00",
        "reduce_only": False, "reason": "Synthetic owner request"}, autopilot)
    assert proposal_id == 44 and "confirm it separately" in message
    assert seen[0][0][:3] == (cursor, 17, "kalshi_perps_live")
    assert seen[0][1]["payload"]["order"] == {
        "side": "bid", "count": "1.00", "price": "7", "reduce_only": False}


@pytest.mark.parametrize("operation,env", [
    ("save_kalshi_key", "production"), ("delete_kalshi_key", "production"),
    ("save_kalshi_dev_key", "demo"), ("delete_kalshi_dev_key", "demo"),
])
@pytest.mark.parametrize("unresolved", [False, True])
def test_key_writers_serialize_with_claims_and_refuse_unresolved_orders(monkeypatch, operation, env, unresolved):
    from contextlib import contextmanager
    seen, cursor = [], object()
    @contextmanager
    def transaction(conn):
        seen.append("begin")
        try:
            yield cursor
        except Exception:
            seen.append("rollback")
            raise
        else:
            seen.append("commit")
    monkeypatch.setattr(server.repo, "transaction", transaction)
    monkeypatch.setattr(server.repo, "lock_user", lambda cur, uid: seen.append("owner_lock"))
    monkeypatch.setattr(server.repo, "list_deployments", lambda *args: [])
    def guard(cur, uid, actual_env):
        assert cur is cursor and uid == 17 and actual_env == env
        seen.append("claim_guard")
        if unresolved:
            raise live.Error("Reconcile the pending submission before changing keys.", 409, "reconciliation_required")
    monkeypatch.setattr(live, "guard_key_change", guard)
    for name in ("save_kalshi_key", "set_kalshi_dev_key", "delete_kalshi_key", "delete_kalshi_dev_key"):
        monkeypatch.setattr(server.repo, name, lambda cur, uid, *args: seen.append("write"))
    monkeypatch.setattr(server.kalshi_account, "verify", lambda *args: seen.append("verify") or 1)
    monkeypatch.setattr(server.kalshi_account, "parse_private_key", lambda *args: "synthetic")
    monkeypatch.setattr(server.kalshi_account, "encrypt_private_key", lambda *args: b"synthetic-cipher")
    monkeypatch.setattr(server.kalshi_dev_exec, "demo_fills", lambda *args: seen.append("verify"))
    context = ctx({"key_id": "synthetic", "private_key": "synthetic"})
    if unresolved:
        with pytest.raises(server.ApiError) as error:
            getattr(server, operation)(context)
        assert error.value.status == 409 and "write" not in seen and seen[-1] == "rollback"
    else:
        assert getattr(server, operation)(context)["ok"] is True
        assert seen.index("claim_guard") < seen.index("write") < seen.index("commit")
    if operation.startswith("save"):
        assert seen.index("verify") < seen.index("begin")
