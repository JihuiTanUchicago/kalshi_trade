"""Manual live-perps business rules with synthetic clients and transactional rows."""
import copy
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import requests

from app import kalshi_perps_trading as trading
from app import kalshi_perps_trading_client as broker
from app import repository as repo
from tests.test_kalshi_perps_orders_repository import FakeConnection, PerpsCursor, instrument


class Connection(FakeConnection):
    def __init__(self):
        super().__init__(PerpsCursor())
        self.active = False
        self.keys = {(1, "production"): {"key_id": "synthetic-user-key", "private_key_enc": b"synthetic-ciphertext"}}
        self.proposal_rows = {}

    def begin(self):
        assert not self.active
        super().begin()
        self.active = True
        self.proposal_backup = copy.deepcopy(self.proposal_rows)

    def commit(self):
        super().commit()
        self.active = False

    def rollback(self):
        super().rollback()
        self.proposal_rows = self.proposal_backup
        self.active = False


class NativeClient:
    def __init__(self, conn, clock):
        self.conn, self.clock = conn, clock
        self.calls, self.sent, self.cancels, self.hooks = [], [], [], {}
        self.env = "production"
        self.metadata = instrument(contract_size="1.000000", underlying_multiplier="0.0001",
                                   title="Bitcoin", status="active", schedule=None)
        self.rate, self.leverage, self.available = "0.0012", "50", "1"
        self.eligible, self.exchange_open, self.computed_balance = True, True, True
        self.position_rows, self.fill_rows, self.order_rows = [], [], []
        self.book = {"bids": [["6.12", "100"]], "asks": [["6.13", "100"]]}
        self.fill_count, self.remaining_count = "10", "0"
        self.submit_error, self.cancel_error = None, None
        self.orders_complete, self.fills_complete, self.crash = True, True, False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def _call(self, name):
        assert not self.conn.active, "Broker I/O must never run while a SQL transaction is open"
        self.calls.append(name)
        hook = self.hooks.pop(name, None)
        if hook:
            hook()

    def response(self, **values):
        return {**copy.deepcopy(values), "environment": self.env,
                "retrieved_at": self.clock["now"].replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")}

    def enabled_status(self):
        self._call("enabled")
        return self.response(enabled=self.eligible)

    def exchange_status(self):
        self._call("exchange")
        return self.response(exchange_active=self.exchange_open, trading_active=self.exchange_open)

    def market(self, ticker=None):
        self._call("market")
        return self.response(**{**self.metadata, "environment": self.env})

    def orderbook(self, ticker):
        self._call("book")
        return self.response(orderbook=self.book)

    def balance(self):
        self._call("balance")
        return self.response(available_balance_computed=self.computed_balance, settled_funds="2",
            subaccount_balances=[dict(subaccount=0, account_equity="2", available_balance=self.available,
                                      position_value="100", initial_margin="1", maintenance_margin="0.5",
                                      resting_orders_margin="0")])

    def risk(self):
        self._call("risk")
        return self.response(account_leverage=self.leverage, total_position_notional="100", positions=[])

    def fee_tiers(self):
        self._call("fees")
        return self.response(taker_fee_rates={"BTC-PERP": self.rate}, maker_fee_rates={"BTC-PERP": "0"})

    def positions(self):
        self._call("positions")
        return self.response(positions=self.position_rows)

    def orders(self, ticker=None, min_ts=None):
        self._call("orders")
        return self.response(orders=self.order_rows, complete=self.orders_complete, cursor="")

    def order(self, order_id):
        self._call("order")
        matches = [row for row in self.order_rows if row["order_id"] == order_id]
        if len(matches) != 1:
            raise broker.Error("not_found", "Synthetic lookup unavailable", 404)
        return self.response(order=matches[0])

    def fills(self, min_ts):
        self._call("fills")
        return self.response(fills=self.fill_rows, complete=self.fills_complete, cursor="")

    def submit_order(self, body):
        self._call("POST")
        self.sent.append(copy.deepcopy(body))
        matching = [row for row in self.conn.cur.orders.values() if row["client_order_id"] == body["client_order_id"]]
        assert len(matching) == 1 and matching[0]["status"] == "claimed"
        assert matching[0]["claimed_at"] is not None and self.conn.backup is None
        if self.crash:
            raise KeyboardInterrupt("synthetic process loss after irreversible claim")
        if self.submit_error:
            raise self.submit_error
        order_id = "native-order-1"
        self.order_rows = [{"order_id": order_id, "client_order_id": body["client_order_id"],
                           "ticker": body["ticker"], "side": body["side"], "price": body["price"],
                           "fill_count": self.fill_count, "remaining_count": self.remaining_count, "subaccount": 0}]
        self.fill_rows = ([] if Decimal(self.fill_count) == 0 else [
            {"fill_id": "native-fill-1", "order_id": order_id, "ticker": body["ticker"], "side": body["side"],
             "count": self.fill_count, "price": body["price"], "fees": "0.0734808", "subaccount": 0}])
        return self.response(order_id=order_id, client_order_id=body["client_order_id"], fill_count=self.fill_count,
                             remaining_count=self.remaining_count, average_fill_price=body["price"],
                             average_fee_paid="0.00734808")

    def cancel_order(self, order_id):
        self._call("DELETE")
        self.cancels.append(order_id)
        if self.cancel_error:
            raise self.cancel_error
        for row in self.order_rows:
            if row["order_id"] == order_id:
                row["remaining_count"] = "0"
        return self.response(order_id=order_id, reduced_by="1")


@pytest.fixture
def rig(monkeypatch):
    clock, conn = {"now": datetime(2026, 10, 23, 3)}, Connection()
    client = NativeClient(conn, clock)
    monkeypatch.setenv("TAU_KALSHI_PERPS_LIVE_ENABLED", "1")
    monkeypatch.delenv("TAU_KALSHI_PERPS_LIVE_ENVIRONMENT", raising=False)
    monkeypatch.setattr(repo, "now_utc", lambda: clock["now"])
    monkeypatch.setattr(trading.store, "now_utc", lambda: clock["now"])
    monkeypatch.setattr(repo, "get_kalshi_key", lambda cur, uid: copy.deepcopy(conn.keys.get((uid, "production"))))
    monkeypatch.setattr(repo, "get_kalshi_dev_key", lambda cur, uid: copy.deepcopy(conn.keys.get((uid, "demo"))))
    monkeypatch.setattr(trading, "_client", lambda uid, key, env: client)
    def create_proposal(cur, uid, kind, reason, **kwargs):
        pid = max(conn.proposal_rows, default=0) + 1
        conn.proposal_rows[pid] = dict(id=pid, user_id=uid, kind=kind, reason=reason,
                                      status="pending", payload=copy.deepcopy(kwargs.get("payload")))
        cur.proposals[pid] = (uid, kind)
        return pid
    def get_proposal(cur, uid, pid):
        row = conn.proposal_rows.get(pid)
        return copy.deepcopy(row) if row and row["user_id"] == uid else None
    def decide(cur, pid, status):
        row = conn.proposal_rows.get(pid)
        if row and row["status"] == "pending":
            row["status"] = status
            return True
        return False
    monkeypatch.setattr(repo, "create_proposal", create_proposal)
    monkeypatch.setattr(repo, "get_proposal", get_proposal)
    monkeypatch.setattr(repo, "decide_proposal", decide)
    def forbidden(*args, **kwargs):
        raise AssertionError("No real provider HTTP is allowed in these tests")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    return conn, client, clock


def policy(conn):
    with conn.cursor() as cur:
        version = trading.store.get_settings(cur, 1, trading.environment())["version"]
    return trading.save_policy(conn, 1, dict(enabled=True, acknowledge_real_money=True, expected_version=version))


def preview(conn, **changes):
    body = dict(request_key="preview-0001", side="bid", count="10", price="6.1234", reduce_only=False)
    body.update(changes)
    return trading.create_order(conn, 1, body)["order"]


def confirm(row):
    return dict(confirmed=True, expected_version=row["version"], request_hash=row["request_hash"])


def test_global_default_off_separate_from_binary_flags_and_no_global_key_fallback(rig, monkeypatch):
    conn, client, _ = rig
    monkeypatch.delenv("TAU_KALSHI_PERPS_LIVE_ENABLED")
    monkeypatch.setenv("APP_LIVE_ENABLED", "1")
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENABLED", "true")
    assert trading.enabled() is False
    result = trading.overview(conn, 1)
    assert result["enabled"] is False and client.calls == []
    with pytest.raises(trading.Error, match="disabled"):
        preview(conn)
    conn.keys.clear()
    monkeypatch.setenv("PROD_KEYID", "must-never-be-used")
    assert trading.overview(conn, 1)["connected"] is False
    assert client.calls == []


def test_explicit_manual_opt_in_requires_real_money_ack_and_sends_nothing(rig):
    conn, client, _ = rig
    with pytest.raises(trading.Error, match="Acknowledge"):
        trading.save_policy(conn, 1, dict(enabled=True, expected_version=0))
    result = policy(conn)["policy"]
    assert result == dict(enabled=True, version=1, manual_confirmation_required=True, risk_mode="kalshi_limits")
    assert not client.calls


def test_preview_shows_native_units_effective_fees_and_no_added_financial_caps(rig):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn, count="10000")
    assert row["preview"]["notional_usd"] == "61234"
    assert Decimal(row["preview"]["btc_quantity"]) == 1
    assert row["preview"]["available_balance"] == "1" and row["preview"]["account_leverage"] == "50"
    assert Decimal(row["preview"]["estimated_fee_usd"]) == Decimal("73.4808")
    assert row["request"]["count"] == "10000"
    stored = conn.cur.orders[row["id"]]
    assert json.loads(stored["request_json"])["count"] == "10000.00"
    assert row["request_hash"] == stored["request_hash"]
    assert client.sent == [] and client.cancels == []
    assert set(row) == {"id", "environment", "client_order_id", "source", "status", "version", "request_hash",
                        "request", "filled_count", "remaining_count", "filled_avg_price", "total_fees", "created_at",
                        "expires_at", "preview", "error_code"}


def test_commit_single_send_then_exact_fill_ledger_and_repeat_confirmation_no_second_post(rig):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    result = trading.submit_order(conn, 1, row["id"], confirm(row))["order"]
    assert result["status"] == "filled" and result["filled_count"] == "10"
    assert result["filled_avg_price"] == "6.1234" and result["total_fees"] == "0.0734808"
    assert client.calls.count("POST") == 1
    assert client.calls.index("POST") < client.calls.index("fills")
    replay = trading.submit_order(conn, 1, row["id"], confirm(row))["order"]
    assert replay == result and len(client.sent) == 1


@pytest.mark.parametrize("bodychange", [{"confirmed": False}, {"confirmed": 1}, {"expected_version": 9},
                                       {"request_hash": "0" * 64}, {"environment": "demo"}])
def test_exact_manual_digest_and_version_are_required_before_any_submit_http(rig, bodychange):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    client.calls.clear()
    with pytest.raises(trading.Error, match="exact current"):
        trading.submit_order(conn, 1, row["id"], {**confirm(row), **bodychange})
    assert client.calls == []


def test_expired_ticket_cannot_be_refreshed_by_replaying_same_request_key(rig):
    conn, client, clock = rig
    policy(conn)
    row = preview(conn)
    clock["now"] += timedelta(seconds=120)
    calls = len(client.calls)
    repeated = preview(conn)
    assert repeated == row and len(client.calls) == calls
    with pytest.raises(trading.Error, match="expired"):
        trading.submit_order(conn, 1, row["id"], confirm(row))
    assert not client.sent


@pytest.mark.parametrize("field,value", [("eligible", False), ("exchange_open", False), ("computed_balance", False)])
def test_entitlement_exchange_or_uncomputed_margin_blocks_preview(rig, field, value):
    conn, client, _ = rig
    policy(conn)
    setattr(client, field, value)
    with pytest.raises(trading.Error):
        preview(conn)
    assert not conn.cur.orders and not client.sent


@pytest.mark.parametrize("schedule", [{"is_open": False}, {"timezone": "UTC"}, {"is_open": True, "next_close_ts": 1}])
def test_closed_unknown_or_stale_explicit_native_schedule_blocks_preview(rig, schedule):
    conn, client, _ = rig
    policy(conn)
    client.metadata["schedule"] = schedule
    with pytest.raises(trading.Error, match="schedule"):
        preview(conn)


def test_positive_schedule_allows_future_reopen_after_next_close(rig):
    conn, client, clock = rig
    policy(conn)
    now = int(clock["now"].replace(tzinfo=timezone.utc).timestamp())
    client.metadata["schedule"] = dict(is_open=True, next_close_ts=now + 100, next_open_ts=now + 200)
    assert preview(conn)["status"] == "draft"


def test_crossed_or_empty_book_is_unknown_not_free_fill(rig):
    conn, client, _ = rig
    policy(conn)
    for bids, asks in (([], [["6", "1"]]), ([["7", "1"]], [["6", "1"]])):
        client.book = {"bids": bids, "asks": asks}
        with pytest.raises(trading.Error, match="uncrossed"):
            preview(conn)
    assert not conn.cur.orders


@pytest.mark.parametrize("change", ["key", "policy", "risk", "disable", "fees", "market"])
def test_fresh_preflight_is_rechecked_under_owner_lock_before_claim(rig, monkeypatch, change):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    if change == "fees":
        client.rate = "0.002"
    elif change == "market":
        client.metadata["tick_size"] = "0.00001"
    else:
        def mutate():
            if change == "key":
                conn.keys[(1, "production")]["private_key_enc"] = b"new-synthetic-ciphertext"
            elif change == "policy":
                policy(conn)
            elif change == "risk":
                conn.cur.settings[(1, "production")]["risk_revision"] += 1
            else:
                monkeypatch.setenv("TAU_KALSHI_PERPS_LIVE_ENABLED", "0")
        client.hooks["positions"] = mutate
    with pytest.raises(trading.Error):
        trading.submit_order(conn, 1, row["id"], confirm(row))
    assert not client.sent
    assert conn.cur.orders[row["id"]]["claimed_at"] is None


def test_sql_lock_wait_that_stales_quote_is_checked_before_irreversible_claim(rig, monkeypatch):
    conn, client, clock = rig
    policy(conn)
    row = preview(conn)
    original = trading.store.lock_user
    def delayed(cur, uid, env):
        clock["now"] += timedelta(seconds=11)
        return original(cur, uid, env)
    monkeypatch.setattr(trading.store, "lock_user", delayed)
    with pytest.raises(trading.Error, match="fresh"):
        trading.submit_order(conn, 1, row["id"], confirm(row))
    assert not client.sent and conn.cur.orders[row["id"]]["claimed_at"] is None


@pytest.mark.parametrize("error", [broker.Error("provider_unavailable", "Synthetic timeout", uncertain=True),
                                  broker.Error("invalid_response", "Synthetic malformed response", 201, uncertain=True),
                                  broker.Error("provider_unavailable", "Synthetic 503", 503, uncertain=True)])
def test_ambiguous_post_is_unknown_blocks_new_orders_and_never_retries(rig, error):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    client.submit_error = error
    result = trading.submit_order(conn, 1, row["id"], confirm(row))["order"]
    assert result["status"] == "unknown" and len(client.sent) == 1
    trading.submit_order(conn, 1, row["id"], confirm(row))
    trading.refresh_order(conn, 1, row["id"])
    assert len(client.sent) == 1
    with pytest.raises(trading.Error, match="prior perpetual"):
        preview(conn, request_key="preview-0002")


def test_crash_after_committed_claim_remains_uncertain_without_second_send(rig):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    client.crash = True
    with pytest.raises(KeyboardInterrupt):
        trading.submit_order(conn, 1, row["id"], confirm(row))
    assert conn.cur.orders[row["id"]]["status"] == "claimed" and not conn.active
    assert trading.submit_order(conn, 1, row["id"], confirm(row))["order"]["status"] == "claimed"
    assert trading.refresh_order(conn, 1, row["id"])["order"]["status"] == "unknown"
    assert len(client.sent) == 1


def test_definitive_rejection_is_terminal_without_resize_or_retry(rig):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn, count="10000")
    client.submit_error = broker.Error("provider_rejected", "Synthetic native margin rejection", 422, rejected=True)
    result = trading.submit_order(conn, 1, row["id"], confirm(row))["order"]
    assert result["status"] == "rejected" and result["error_code"] == "broker_rejected"
    assert client.sent[0]["count"] == "10000.00" and len(client.sent) == 1


@pytest.mark.parametrize("count,status", [("0", "canceled"), ("4", "partial"), ("10", "filled")])
def test_ioc_terminal_states_require_complete_ledger_economics(rig, count, status):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    client.fill_count = count
    result = trading.submit_order(conn, 1, row["id"], confirm(row))["order"]
    assert result["status"] == status and result["remaining_count"] == "0"
    assert Decimal(result["filled_count"]) == Decimal(count)
    assert result["filled_avg_price"] == (None if count == "0" else "6.1234")


def test_incomplete_ledger_or_wrong_subaccount_never_releases_reservation(rig):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    client.fills_complete = False
    result = trading.submit_order(conn, 1, row["id"], confirm(row))["order"]
    assert result["status"] == "unknown" and result["total_fees"] is None
    client.fills_complete = True
    client.fill_rows[0]["subaccount"] = 1
    assert trading.refresh_order(conn, 1, row["id"])["order"]["status"] == "unknown"
    client.fill_rows[0]["subaccount"] = 0
    assert trading.refresh_order(conn, 1, row["id"])["order"]["status"] == "filled"
    assert len(client.sent) == 1


def test_reconciliation_never_adopts_other_orders_or_fills(rig):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    client.fills_complete = False
    trading.submit_order(conn, 1, row["id"], confirm(row))
    client.fills_complete = True
    client.order_rows[0]["client_order_id"] = "foreign-client"
    assert trading.refresh_order(conn, 1, row["id"])["order"]["status"] == "unknown"
    client.order_rows[0]["client_order_id"] = row["client_order_id"]
    client.fill_rows.append({**client.fill_rows[0], "fill_id": "foreign-fill", "order_id": "outside-app", "count": "999"})
    assert trading.refresh_order(conn, 1, row["id"])["order"]["filled_count"] == "10"
    assert not client.cancels


def test_reduce_only_uses_signed_native_position_and_cannot_flip(rig):
    conn, client, _ = rig
    policy(conn)
    client.position_rows = [dict(subaccount=0, market_ticker="BTC-PERP", position="3")]
    for side, count in (("bid", "1"), ("ask", "4")):
        with pytest.raises(trading.Error, match="reduce-only"):
            preview(conn, side=side, count=count, reduce_only=True)
    assert preview(conn, side="ask", count="3", reduce_only=True)["request"]["reduce_only"] is True


def test_cancel_unsent_draft_sends_no_delete_and_cancel_uncertainty_never_retries(rig):
    conn, client, _ = rig
    policy(conn)
    first = preview(conn)
    assert trading.cancel_order(conn, 1, first["id"], confirm(first))["order"]["status"] == "canceled"
    assert not client.cancels
    second = preview(conn, request_key="preview-0002")
    client.fills_complete = False
    active = trading.submit_order(conn, 1, second["id"], confirm(second))["order"]
    client.cancel_error = broker.Error("provider_unavailable", "Synthetic cancel timeout", uncertain=True)
    canceled = trading.cancel_order(conn, 1, second["id"], confirm(active))["order"]
    assert canceled["status"] == "unknown" and len(client.cancels) == 1
    trading.cancel_order(conn, 1, second["id"], confirm(canceled))
    assert len(client.cancels) == 1
    unresolved = trading.refresh_order(conn, 1, second["id"])["order"]
    assert unresolved["error_code"] == "cancel_uncertain"
    trading.cancel_order(conn, 1, second["id"], confirm(unresolved))
    assert len(client.cancels) == 1


def test_cancel_racing_fill_reconciles_native_partial_instead_of_fabricating_zero(rig):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    client.fill_count, client.fills_complete = "4", False
    unknown = trading.submit_order(conn, 1, row["id"], confirm(row))["order"]
    client.fills_complete = True
    result = trading.cancel_order(conn, 1, row["id"], confirm(unknown))["order"]
    assert result["status"] == "partial" and result["filled_count"] == "4"
    assert len(client.cancels) == 1 and len(client.sent) == 1


def test_demo_uses_only_explicit_operator_demo_key_context_and_does_not_fall_back(rig, monkeypatch):
    conn, client, _ = rig
    monkeypatch.setenv("TAU_KALSHI_PERPS_LIVE_ENVIRONMENT", "demo")
    policy(conn)
    with pytest.raises(trading.Error, match="own Kalshi key"):
        preview(conn)
    assert not client.calls
    conn.keys[(1, "demo")] = {"key_id": "demo-key", "private_key_enc": b"demo-cipher"}
    client.env, client.metadata["environment"] = "demo", "demo"
    row = preview(conn)
    assert row["environment"] == "demo"
    with pytest.raises(trading.Error, match="owner and environment"):
        trading.submit_order(conn, 2, row["id"], confirm(row))


def test_agent_only_proposes_generic_approve_requires_funds_review_and_each_proposal_sends_once(rig):
    conn, client, _ = rig
    policy(conn)
    action = dict(side="bid", count="10", price="6.1234", reduce_only=False, reason="Synthetic hypothesis")
    with repo.transaction(conn) as cur:
        message, pid = trading.propose_for_agent(cur, 1, action)
    assert not client.calls and "confirm" in message
    approved = trading.decide_proposal(conn, 1, pid, "approve")
    assert approved["review_required"] is True and approved["review_url"] == "/funds?perps_proposal=%d" % pid
    assert conn.proposal_rows[pid]["status"] == "pending" and not client.sent
    first = trading.preview_proposal(conn, 1, pid, {"request_key": "proposal-review-1"})["order"]
    second = trading.preview_proposal(conn, 1, pid, {"request_key": "proposal-review-2"})["order"]
    assert first["source"] == second["source"] == "agent"
    assert trading.submit_order(conn, 1, first["id"], confirm(first))["order"]["status"] == "filled"
    assert conn.proposal_rows[pid]["status"] == "applied"
    with pytest.raises(trading.Error, match="proposal was already"):
        trading.submit_order(conn, 1, second["id"], confirm(second))
    assert len(client.sent) == 1


def test_agent_proposal_ownership_rejection_and_immutable_payload(rig):
    conn, client, _ = rig
    policy(conn)
    with repo.transaction(conn) as cur:
        _, pid = trading.propose_for_agent(cur, 1, dict(side="bid", count="10", price="6.1234", reduce_only=False))
    with pytest.raises(trading.Error, match="owner and environment"):
        trading.decide_proposal(conn, 2, pid, "approve")
    with pytest.raises(trading.Error, match="Only a request key"):
        trading.preview_proposal(conn, 1, pid, {"request_key": "proposal-review-1", "count": "1000"})
    assert trading.decide_proposal(conn, 1, pid, "reject")["status"] == "rejected"
    with pytest.raises(trading.Error, match="already decided"):
        trading.preview_proposal(conn, 1, pid, {"request_key": "proposal-review-1"})
    assert not client.sent


def test_agent_context_never_contains_key_revision_digest_tokens_or_account_identifiers(rig):
    conn, client, _ = rig
    assert trading.agent_context(conn, 1) == "" and not client.calls
    policy(conn)
    preview(conn)
    context = trading.agent_context(conn, 1)
    assert "separate manual" in context and '"account_leverage":"50"' in context
    assert all(value not in context for value in ("synthetic-user-key", "synthetic-ciphertext", "request_hash", "client_order_id", "key_revision_hash"))
    state = trading.overview(conn, 1)
    assert state["eligible"] is True and state["risk"]["account_leverage"] == "50"
    assert state["account"]["available_balance"] == "1"


def test_signed_native_fee_credit_is_never_clamped(rig):
    conn, client, _ = rig
    policy(conn)
    client.rate = "-0.001"
    row = preview(conn)
    assert Decimal(row["preview"]["estimated_fee_usd"]) == Decimal("-0.061234")
    client.hooks["fills"] = lambda: client.fill_rows[0].update(fees="-0.1")
    result = trading.submit_order(conn, 1, row["id"], confirm(row))["order"]
    assert result["status"] == "filled" and result["total_fees"] == "-0.1"


@pytest.mark.parametrize("side,bad,good", [("bid", "7", "6"), ("ask", "5", "7")])
def test_each_native_fill_must_obey_limit_even_when_weighted_average_looks_valid(rig, side, bad, good):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn, side=side)
    def contradictory_fills():
        original = client.fill_rows[0]
        client.fill_rows = [{**original, "fill_id": "bad-fill", "count": "1", "price": bad},
                            {**original, "fill_id": "good-fill", "count": "9", "price": good}]
    client.hooks["fills"] = contradictory_fills
    result = trading.submit_order(conn, 1, row["id"], confirm(row))["order"]
    assert result["status"] == "unknown" and result["filled_avg_price"] is None
    assert trading.store.reservation_orders(conn.cur, 1, "production")
    assert len(client.sent) == 1


def test_key_change_guard_locks_claim_owner_and_blocks_inflight_even_when_disabled(rig, monkeypatch):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    client.submit_error = broker.Error("provider_unavailable", "Synthetic timeout", uncertain=True)
    trading.submit_order(conn, 1, row["id"], confirm(row))
    monkeypatch.setenv("TAU_KALSHI_PERPS_LIVE_ENABLED", "0")
    conn.cur.calls.clear()
    with pytest.raises(trading.Error, match="Reconcile open or uncertain"):
        with repo.transaction(conn) as cur:
            trading.guard_key_change(cur, 1, "production")
    assert conn.cur.calls[0] == ("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (1,))
    with repo.transaction(conn) as cur:
        trading.guard_key_change(cur, 1, "demo")
        trading.guard_key_change(cur, 2, "production")
    assert len(client.sent) == 1


def test_key_change_guard_allows_unsent_draft_and_terminal_proven_order(rig):
    conn, client, _ = rig
    policy(conn)
    row = preview(conn)
    with repo.transaction(conn) as cur:
        trading.guard_key_change(cur, 1, "production")
    trading.submit_order(conn, 1, row["id"], confirm(row))
    with repo.transaction(conn) as cur:
        trading.guard_key_change(cur, 1, "production")
    assert conn.cur.orders[row["id"]]["status"] == "filled"


def test_exact_estimated_fee_product_can_exceed_settled_cash_fractional_scale(rig):
    conn, client, _ = rig
    policy(conn)
    client.rate = "0.000000000000000001"
    row = preview(conn)
    assert row["preview"]["estimated_fee_usd"] == "0.000000000000000061234"
