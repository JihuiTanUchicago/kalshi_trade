"""Paper execution lifecycle with a synthetic broker and durable-state boundary.

External I/O is forbidden inside a transaction. These tests model an accepted
POST followed by a timeout, not a pretend instant fill. SQL has its own contract
suite; this suite exercises the real service and pure broker payload validator.
"""
import copy
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.adapters.alpaca import alpaca_paper as paper

BROKER_ID = "00000000-1111-4222-8333-000000000001"


@pytest.fixture
def world(monkeypatch):
    state = SimpleNamespace(rows={}, proposals={}, chats=[], credentials={}, remote={}, posts=[], deletes=[], reads=[],
                            tx=0, post_error=None, malformed_ack=False, malformed_zero_average=False, during_account=None,
                            cash="1000", holdings="3", open_orders=[], account_flags={})
    state.credentials[1] = {"access_token": "synthetic-token-owner-one", "account_id": "synthetic-account-one", "scope": "data trading"}
    state.credentials[2] = {"access_token": "synthetic-token-owner-two", "account_id": "synthetic-account-two", "scope": "data trading"}
    state.grants = {uid: {"tokens_enc": ("synthetic-ciphertext-%s" % uid).encode()} for uid in (1, 2)}
    monkeypatch.setenv("TAU_ALPACA_PAPER_ENABLED", "1")
    monkeypatch.setenv("TAU_ALPACA_PAPER_MAX_ORDER_USD", "500")
    cur = SimpleNamespace()

    @contextmanager
    def cursor():
        yield cur

    state.conn = SimpleNamespace(cursor=cursor)

    @contextmanager
    def transaction(conn):
        assert state.tx == 0
        previous = copy.deepcopy((state.rows, state.proposals, state.chats))
        state.tx += 1
        try:
            yield cur
        except BaseException:
            state.rows, state.proposals, state.chats = previous
            raise
        finally:
            state.tx -= 1

    monkeypatch.setattr(paper.repo, "transaction", transaction)
    monkeypatch.setattr(paper.store, "lock_user", lambda cur, uid: None)
    monkeypatch.setattr(paper.connections, "get_connection", lambda cur, uid, provider, environment:
                        copy.deepcopy(state.grants.get(uid)) if (provider, environment) == ("alpaca", "paper") else None)
    monkeypatch.setattr(paper.vault, "decrypt", lambda uid, provider, environment, purpose, blob:
                        copy.deepcopy(state.credentials[uid]))

    def get(cur, uid, oid, for_update=False):
        row = state.rows.get(oid)
        return copy.deepcopy(row) if row and row["user_id"] == uid else None

    def insert(cur, uid, key, fingerprint, request, source="user", proposal_id=None):
        for row in state.rows.values():
            if row["user_id"] == uid and row["request_key"] == key:
                without_id = lambda obj: {k: v for k, v in obj.items() if k != "client_order_id"}
                if row["connection_hash"] != fingerprint or without_id(row["request"]) != without_id(request):
                    raise ValueError()
                return copy.deepcopy(row)
        oid = len(state.rows) + 1
        row = dict(id=oid, user_id=uid, request_key=key, connection_hash=fingerprint, request=request,
                   client_order_id=request["client_order_id"], source=source, proposal_id=proposal_id,
                   status="draft", broker_order_id=None, broker_status=None, filled_qty="0", filled_avg_price=None,
                   error_code=None, created_at=datetime(2026, 10, 18), updated_at=datetime(2026, 10, 18))
        state.rows[oid] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def claim(cur, uid, oid):
        row = state.rows[oid]
        assert state.tx == 1
        if row["user_id"] != uid or row["status"] != "draft":
            return False
        row["status"] = "submitting"
        return True

    def record(cur, uid, oid, **changes):
        assert state.tx == 1 and state.rows[oid]["user_id"] == uid
        state.rows[oid].update(changes)
        return True

    def unsettled(cur, uid, fingerprint):
        return [copy.deepcopy(row) for row in state.rows.values() if row["user_id"] == uid
                and row["connection_hash"] == fingerprint
                and (row["status"] in ("submitting", "unknown", "cancel_pending")
                     or row["status"] == "submitted" and row["broker_status"] not in paper.TERMINAL)]

    def cancel_draft(cur, uid, oid):
        row = state.rows[oid]
        if row["user_id"] != uid or row["status"] != "draft":
            return False
        row["status"] = "canceled"
        return True

    monkeypatch.setattr(paper.store, "get_order", get)
    monkeypatch.setattr(paper.store, "insert_order", insert)
    monkeypatch.setattr(paper.store, "claim_submission", claim)
    monkeypatch.setattr(paper.store, "record_result", record)
    monkeypatch.setattr(paper.store, "unsettled_orders", unsettled)
    monkeypatch.setattr(paper.store, "submission_count", lambda c, uid, f: sum(
        r["user_id"] == uid and r["connection_hash"] == f
        and (r["status"] in ("submitting", "submitted", "unknown", "rejected", "cancel_pending")
             or r.get("broker_order_id") is not None or r.get("submitted_at") is not None)
        for r in state.rows.values()))
    monkeypatch.setattr(paper.store, "in_flight_orders", lambda c, u, f: [r for r in unsettled(c, u, f) if r["status"] in ("submitting", "unknown", "cancel_pending")])
    monkeypatch.setattr(paper.store, "list_orders", lambda c, uid: [copy.deepcopy(r) for r in state.rows.values() if r["user_id"] == uid])
    monkeypatch.setattr(paper.store, "cancel_draft", cancel_draft)
    monkeypatch.setattr(paper.store, "bind_proposal", lambda c, u, oid, pid: state.rows[oid].update(proposal_id=pid))

    def create_proposal(cur, uid, kind, reason, **kwargs):
        pid = len(state.proposals) + 1
        state.proposals[pid] = dict(id=pid, user_id=uid, kind=kind, reason=reason, status="pending", **kwargs)
        return pid

    def decide(cur, pid, status):
        if state.proposals[pid]["status"] != "pending":
            return False
        state.proposals[pid]["status"] = status
        return True

    monkeypatch.setattr(paper.repo, "create_proposal", create_proposal)
    monkeypatch.setattr(paper.repo, "get_proposal", lambda c, uid, pid: copy.deepcopy(state.proposals.get(pid)) if state.proposals.get(pid, {}).get("user_id") == uid else None)
    monkeypatch.setattr(paper.repo, "decide_proposal", decide)
    monkeypatch.setattr(paper.repo, "add_chat", lambda *args: state.chats.append(args))

    class Client:
        def __init__(self, credentials):
            self.credentials = credentials

        def __enter__(self):
            assert state.tx == 0
            return self

        def __exit__(self, *args):
            pass

        def checked(self, name):
            assert state.tx == 0, "HTTP must never hold a user/DB transaction lock"
            state.reads.append(name)

        def account(self):
            self.checked("account")
            if state.during_account:
                callback, state.during_account = state.during_account, None
                callback()
            return dict(id=self.credentials["account_id"], currency="USD", status="ACTIVE", trading_blocked=False,
                        account_blocked=False, trade_suspended_by_user=False, cash=state.cash,
                        buying_power="4000", equity="1300", portfolio_value="1300", **state.account_flags)

        def positions(self):
            self.checked("positions")
            return [dict(symbol="AAPL", qty=state.holdings, avg_entry_price="100", market_value="300", unrealized_pl="0")]

        def asset(self, symbol):
            self.checked("asset")
            return {"symbol": symbol, "class": "us_equity", "status": "active", "tradable": True}

        def orders(self, **kwargs):
            self.checked("orders")
            if kwargs.get("status") == "all":
                return copy.deepcopy(list(state.remote.values()))
            return copy.deepcopy(state.open_orders)

        def get_order(self, cid):
            self.checked("get_order")
            return copy.deepcopy(state.remote.get(cid))

        def submit_order(self, request):
            self.checked("POST")
            assert any(r["status"] == "submitting" and r["client_order_id"] == request["client_order_id"] for r in state.rows.values())
            state.posts.append(copy.deepcopy(request))
            response = dict(request, id=BROKER_ID, status="new", filled_qty="0", filled_avg_price=None)
            state.remote[request["client_order_id"]] = response
            if state.post_error:
                raise state.post_error
            if state.malformed_ack:
                response = {**response, "symbol": "MSFT"}
            if state.malformed_zero_average:
                response = {**response, "filled_avg_price": "100"}
            return copy.deepcopy(response)

        def cancel_order(self, oid):
            self.checked("DELETE")
            state.deletes.append(oid)

    monkeypatch.setattr(paper.broker, "Client", Client)
    state.ticket = dict(request_key="stable-ticket-0001", symbol="AAPL", side="buy", qty="1", limit_price="100.00")
    return state


def draft(world, **changes):
    return paper.create_order(world.conn, 1, {**world.ticket, **changes})["order"]


def test_create_replay_conflict_and_projection(world):
    first, second = draft(world), draft(world)
    assert first == second and len(world.rows) == 1 and not world.posts and not world.reads
    assert not {"connection_hash", "tokens_enc", "user_id", "request_key", "account_id"} & first.keys()
    with pytest.raises(paper.Error, match="already used"):
        draft(world, qty="2")


def test_submit_is_claimed_committed_once_and_acceptance_is_not_fill(world):
    oid = draft(world)["id"]
    out = paper.submit_order(world.conn, 1, oid)["order"]
    assert out["status"] == "submitted" and out["broker_status"] == "new" and out["filled_qty"] == "0"
    assert len(world.posts) == 1
    assert paper.submit_order(world.conn, 1, oid)["order"] == out
    assert len(world.posts) == 1


def test_accepted_then_timeout_reconciles_without_repeating_post(world):
    world.post_error = paper.broker.Error("Paper broker unavailable.", 502, ambiguous=True)
    oid = draft(world)["id"]
    assert paper.submit_order(world.conn, 1, oid)["order"]["status"] == "unknown"
    paper.submit_order(world.conn, 1, oid)
    assert len(world.posts) == 1
    cid = world.rows[oid]["client_order_id"]
    world.remote[cid].update(status="partially_filled", filled_qty="0.5", filled_avg_price="99.5")
    out = paper.refresh_order(world.conn, 1, oid)["order"]
    assert (out["broker_status"], out["filled_qty"], out["filled_avg_price"]) == ("partially_filled", "0.5", "99.5")
    assert len(world.posts) == 1


def test_definitive_rejection_does_not_claim_fill_or_retry(world):
    world.post_error = paper.broker.Error("Alpaca rejected this paper order.", 400, rejected=True)
    oid = draft(world)["id"]
    out = paper.submit_order(world.conn, 1, oid)["order"]
    assert out["status"] == "rejected" and out["filled_qty"] == "0"
    paper.submit_order(world.conn, 1, oid)
    assert len(world.posts) == 1


def test_missing_after_timeout_stays_unknown_and_blocks_next_send(world):
    world.post_error = paper.broker.Error("Unavailable.", 502, ambiguous=True)
    oid = draft(world)["id"]
    paper.submit_order(world.conn, 1, oid)
    world.remote.clear()
    assert paper.refresh_order(world.conn, 1, oid)["order"]["status"] == "unknown"
    other = draft(world, request_key="another-ticket-0002")["id"]
    with pytest.raises(paper.Error, match="in-flight"):
        paper.submit_order(world.conn, 1, other)
    assert len(world.posts) == 1


@pytest.mark.parametrize("field,value", [("qty", "0.5"), ("qty", True), ("qty", "nan"), ("limit_price", "1.001"), ("environment", "live"), ("type", "market")])
def test_invalid_or_expanded_tickets_never_reach_provider(world, field, value):
    with pytest.raises(paper.Error):
        draft(world, **{field: value})
    assert not world.rows and not world.posts and not world.reads


@pytest.mark.parametrize("failure", ["disabled", "read_only", "expired", "disconnected", "oversized"])
def test_explicit_feature_grant_and_notional_controls(world, monkeypatch, failure):
    if failure == "disabled": monkeypatch.setenv("TAU_ALPACA_PAPER_ENABLED", "0")
    if failure == "read_only": world.credentials[1]["scope"] = "data"
    if failure == "expired": world.credentials[1]["expires_at"] = 1
    if failure == "disconnected": world.grants.pop(1)
    with pytest.raises(paper.Error):
        draft(world, qty="6" if failure == "oversized" else "1")
    assert not world.posts and not world.reads


@pytest.mark.parametrize("operation", [paper.submit_order, paper.refresh_order, paper.cancel_order])
def test_other_user_cannot_operate_order(world, operation):
    oid = draft(world)["id"]
    with pytest.raises(paper.Error) as exc:
        operation(world.conn, 2, oid)
    assert exc.value.status == 404 and not world.reads and not world.posts


@pytest.mark.parametrize("scenario", ["cash", "buy_reserved", "short", "sell_reserved"])
def test_cash_only_and_unreserved_long_share_checks(world, scenario):
    change = {}
    if scenario == "cash": world.cash = "50"
    if scenario == "buy_reserved":
        world.cash = "150"
        world.open_orders = [dict(side="buy", type="limit", qty="1", filled_qty="0", limit_price="100")]
    if scenario == "short": world.holdings = "0"; change["side"] = "sell"
    if scenario == "sell_reserved":
        change["side"] = "sell"
        world.open_orders = [dict(symbol="AAPL", side="sell", qty="3", filled_qty="0")]
    oid = draft(world, **change)["id"]
    with pytest.raises(paper.Error): paper.submit_order(world.conn, 1, oid)
    assert not world.posts and world.rows[oid]["status"] == "draft"


def test_reconnect_or_competing_ack_during_validation_prevents_send(world):
    oid = draft(world)["id"]
    world.during_account = lambda: world.grants[1].update(tokens_enc=b"new-connection-version")
    with pytest.raises(paper.Error, match="previous connection"):
        paper.submit_order(world.conn, 1, oid)
    assert not world.posts


def test_new_reservation_between_reads_and_claim_requires_revalidation(world):
    oid = draft(world)["id"]
    def competitor():
        prior = copy.deepcopy(world.rows[oid]); prior.update(id=99, status="submitted", broker_status="new", client_order_id="tau-paper-" + "f" * 32)
        world.rows[99] = prior
    world.during_account = competitor
    with pytest.raises(paper.Error, match="changed during validation"):
        paper.submit_order(world.conn, 1, oid)
    assert not world.posts


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_competing_fully_filled_send_is_detected_even_after_leaving_unsettled_set(world, side):
    oid = draft(world, side=side)["id"]
    def competitor():
        prior = copy.deepcopy(world.rows[oid])
        prior.update(id=99, status="submitted", broker_status="filled", filled_qty="1", filled_avg_price="100",
                     broker_order_id=BROKER_ID, client_order_id="tau-paper-" + "f" * 32)
        world.rows[99] = prior
    world.during_account = competitor
    with pytest.raises(paper.Error, match="changed during validation"):
        paper.submit_order(world.conn, 1, oid)
    assert not world.posts and world.rows[oid]["status"] == "draft"


def test_ack_mismatch_stays_unknown_without_second_post(world):
    world.malformed_ack = True
    oid = draft(world)["id"]
    assert paper.submit_order(world.conn, 1, oid)["order"]["status"] == "unknown"
    assert paper.refresh_order(world.conn, 1, oid)["order"]["status"] == "submitted"
    assert len(world.posts) == 1


def test_cancel_accepted_is_pending_until_broker_confirms_and_survives_kill_switch(world, monkeypatch):
    oid = draft(world)["id"]
    paper.submit_order(world.conn, 1, oid)
    monkeypatch.setenv("TAU_ALPACA_PAPER_ENABLED", "0")
    out = paper.cancel_order(world.conn, 1, oid)["order"]
    assert out["status"] == "cancel_pending" and world.deletes == [BROKER_ID]
    world.remote[out["client_order_id"]]["status"] = "canceled"
    assert paper.refresh_order(world.conn, 1, oid)["order"]["status"] == "canceled"


def test_filled_during_cancellation_is_observed_without_delete(world):
    oid = draft(world)["id"]
    paper.submit_order(world.conn, 1, oid)
    world.remote[world.rows[oid]["client_order_id"]].update(status="filled", filled_qty="1", filled_avg_price="99")
    out = paper.cancel_order(world.conn, 1, oid)["order"]
    assert out["broker_status"] == "filled" and out["filled_qty"] == "1" and not world.deletes


def test_agent_is_always_pending_until_user_approves_same_intent(world):
    with paper.repo.transaction(world.conn) as cur:
        message, pid = paper.propose_for_agent(cur, 1, {**world.ticket, "reason": "User requested a paper experiment."})
    assert "approval" in message and not world.posts and world.proposals[pid]["status"] == "pending"
    out = paper.decide_proposal(world.conn, 1, pid, "approve")
    assert out["order"]["broker_status"] == "new" and world.proposals[pid]["status"] == "applied" and len(world.posts) == 1
    paper.decide_proposal(world.conn, 1, pid, "approve")
    assert len(world.posts) == 1


def test_declined_agent_draft_cannot_be_submitted_from_account_panel(world):
    with paper.repo.transaction(world.conn) as cur:
        _, pid = paper.propose_for_agent(cur, 1, world.ticket)
    out = paper.decide_proposal(world.conn, 1, pid, "reject")
    assert out["order"]["status"] == "canceled"
    paper.submit_order(world.conn, 1, out["order"]["id"])
    assert not world.posts


def test_overview_and_agent_context_project_no_tokens_account_ids_or_ciphertext(world):
    draft(world)
    data = paper.overview(world.conn, 1)
    text = str(data) + paper.agent_context(world.conn, 1)
    assert data["account"]["cash"] == "1000" and data["positions"][0]["qty"] == "3"
    assert "synthetic-token" not in text and "synthetic-account" not in text and "synthetic-ciphertext" not in text
    assert "connection_hash" not in text


def test_account_and_agent_views_reconcile_observed_broker_fills(world):
    oid = draft(world)["id"]
    paper.submit_order(world.conn, 1, oid)
    world.remote[world.rows[oid]["client_order_id"]].update(status="filled", filled_qty="1", filled_avg_price="99")
    data = paper.overview(world.conn, 1)
    assert data["orders"][0]["broker_status"] == "filled"
    assert data["orders"][0]["filled_avg_price"] == "99"
    assert '"broker_status": "filled"' in paper.agent_context(world.conn, 1)
    assert len(world.posts) == 1


@pytest.mark.parametrize("value", ["1e-10000", "1e10000", "0.0000000000001", "9999999999999", "NaN", "Infinity"])
def test_bounded_decimal_parser_refuses_expansion_or_unrepresentable_values(value):
    with pytest.raises(paper.Error):
        paper._text_number(value)


def test_malformed_filled_status_does_not_release_order_reservations(world):
    oid = draft(world)["id"]
    paper.submit_order(world.conn, 1, oid)
    world.remote[world.rows[oid]["client_order_id"]].update(status="filled", filled_qty="0.5", filled_avg_price="99")
    with pytest.raises(paper.Error, match="completed fill quantity"):
        paper.refresh_order(world.conn, 1, oid)
    assert world.rows[oid]["broker_status"] == "new"
    assert len(world.posts) == 1


def test_malformed_zero_fill_average_uses_uncertainty_path_after_post(world):
    world.malformed_zero_average = True
    oid = draft(world)["id"]
    out = paper.submit_order(world.conn, 1, oid)["order"]
    assert out["status"] == "unknown" and out["error_code"] == "submission_uncertain"
    assert out["filled_qty"] == "0" and out["filled_avg_price"] is None
    paper.submit_order(world.conn, 1, oid)
    assert len(world.posts) == 1
