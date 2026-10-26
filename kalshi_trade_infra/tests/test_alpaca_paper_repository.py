"""Paper order persistence contracts against synthetic rows, without a live DB."""
import copy
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.adapters.alpaca import alpaca_paper_repository as repo

NOW = datetime(2026, 10, 18, 18, 0, 0)
CONNECTION = hashlib.sha256(b"synthetic-account-one").hexdigest()
OTHER_CONNECTION = hashlib.sha256(b"synthetic-account-two").hexdigest()
BROKER_ID = "a326e020-0be0-46e0-aed9-2701d2974a26"


def request(number=1, **overrides):
    return dict(symbol="SPY", qty="2", side="buy", type="limit", limit_price="400.25",
                time_in_force="day", extended_hours=False,
                client_order_id="tau-paper-" + format(number, "032x"), **overrides)


class PaperCursor:
    def __init__(self):
        self.users = {1, 2}
        self.proposals = {10: (1, "alpaca_paper"), 11: (2, "alpaca_paper"), 12: (1, "deploy")}
        self.orders = {}
        self.calls = []
        self.rowcount = 0
        self.lastrowid = None
        self._rows = []

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        self.rowcount = 0
        self._rows = []
        if sql == "SELECT id FROM app_users WHERE id=%s FOR UPDATE":
            self._rows = [{"id": params[0]}] if params[0] in self.users else []
        elif sql.startswith("SELECT id FROM app_proposals"):
            proposal_id, uid = params
            self._rows = ([{"id": proposal_id}]
                          if self.proposals.get(proposal_id) == (uid, "alpaca_paper") else [])
        elif sql.startswith("SELECT COUNT(*) AS submission_count FROM app_alpaca_paper_orders"):
            uid, connection = params
            count = sum(row["user_id"] == uid and row["connection_hash"] == connection
                        and (row["status"] in ("submitting", "submitted", "unknown", "rejected", "cancel_pending")
                             or row["broker_order_id"] is not None or row["submitted_at"] is not None)
                        for row in self.orders.values())
            self._rows = [{"submission_count": count}]
        elif sql.startswith("SELECT") and "FROM app_alpaca_paper_orders" in sql:
            uid = params[0]
            rows = [row for row in self.orders.values() if row["user_id"] == uid]
            if "AND request_key=%s" in sql:
                rows = [row for row in rows if row["request_key"] == params[1]]
            elif "AND id=%s" in sql:
                rows = [row for row in rows if row["id"] == params[1]]
            elif "AND connection_hash=%s" in sql:
                rows = [row for row in rows if row["connection_hash"] == params[1]]
                rows = [row for row in rows if row["status"] in ("submitting", "unknown", "cancel_pending")
                        or ("OR (status='submitted'" in sql and row["status"] == "submitted"
                            and row["broker_status"] not in ("filled", "canceled", "expired", "rejected"))]
            rows = sorted(rows, key=lambda row: row["id"], reverse=True)
            if "LIMIT 501" in sql:
                rows = rows[:501]
            elif "LIMIT %s" in sql:
                rows = rows[:params[-1]]
            self._rows = rows
        elif sql.startswith("INSERT INTO app_alpaca_paper_orders"):
            uid, key, connection, client, payload, source, proposal, created, updated = params
            assert all((row["user_id"], row["request_key"]) != (uid, key)
                       and row["client_order_id"] != client for row in self.orders.values())
            self.lastrowid = max(self.orders, default=0) + 1
            self.orders[self.lastrowid] = dict(id=self.lastrowid, user_id=uid, request_key=key,
                connection_hash=connection, client_order_id=client, request_json=payload, source=source,
                proposal_id=proposal, status="draft", broker_order_id=None, broker_status=None,
                filled_qty=Decimal("0"), filled_avg_price=None, error_code=None,
                created_at=created, updated_at=updated, submitted_at=None)
            self.rowcount = 1
        elif sql.startswith("UPDATE app_alpaca_paper_orders SET proposal_id"):
            proposal, updated, uid, order_id, repeated = params
            row = self.orders.get(order_id)
            if (row and row["user_id"] == uid and row["status"] == "draft"
                    and row["proposal_id"] in (None, repeated)):
                row.update(proposal_id=proposal, updated_at=updated)
                self.rowcount = 1
        elif sql.startswith("UPDATE app_alpaca_paper_orders SET status='"):
            updated, uid, order_id = params
            row = self.orders.get(order_id)
            if row and row["user_id"] == uid and row["status"] == "draft":
                target = "submitting" if "SET status='submitting'" in sql else "canceled"
                row.update(status=target, error_code=None, updated_at=updated)
                self.rowcount = 1
        elif sql.startswith("UPDATE app_alpaca_paper_orders SET status=%s"):
            status, broker, broker_status, quantity, average, error, submitted, updated, uid, order_id, old = params
            row = self.orders.get(order_id)
            if row and row["user_id"] == uid and row["status"] == old:
                row.update(status=status, broker_order_id=broker, broker_status=broker_status,
                           filled_qty=quantity, filled_avg_price=average, error_code=error,
                           submitted_at=submitted, updated_at=updated)
                self.rowcount = 1
        else:
            raise AssertionError("Unexpected SQL shape: " + sql)

    def fetchone(self):
        return copy.deepcopy(self._rows[0]) if self._rows else None

    def fetchall(self):
        return copy.deepcopy(self._rows)


@pytest.fixture
def cur(monkeypatch):
    monkeypatch.setattr(repo, "now_utc", lambda: NOW)
    return PaperCursor()


def insert(cur, uid=1, key="request-1", connection=CONNECTION, number=1, **kwargs):
    return repo.insert_order(cur, uid, key, connection, request(number), **kwargs)


def submit(cur):
    row = insert(cur)
    assert repo.claim_submission(cur, 1, row["id"])
    assert repo.record_result(cur, 1, row["id"], status="submitted", broker_order_id=BROKER_ID,
                              broker_status="new")
    return row["id"]


def test_insert_freezes_normalized_payload_identity_and_utc_timestamps(cur):
    row = insert(cur)
    assert row["request"] == request() and row["status"] == "draft"
    assert row["client_order_id"] == request()["client_order_id"]
    assert row["created_at"] == row["updated_at"] == NOW
    assert row["submitted_at"] is None
    assert row["filled_qty"] == Decimal("0") and row["source"] == "user"
    assert "request_json" not in row
    assert json.loads(cur.orders[row["id"]]["request_json"]) == request()


def test_repeated_request_returns_original_id_and_payload_without_writes(cur):
    first = insert(cur)
    assert repo.claim_submission(cur, 1, first["id"])
    before = copy.deepcopy(cur.orders)
    cur.calls.clear()
    second = insert(cur, number=99)
    assert second["id"] == first["id"] and second["client_order_id"] == first["client_order_id"]
    assert second["status"] == "submitting" and cur.orders == before
    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in cur.calls)


@pytest.mark.parametrize("change", ["connection", "symbol", "qty", "limit_price", "side", "source"])
def test_same_request_key_cannot_replace_frozen_order(cur, change):
    first = insert(cur)
    before = copy.deepcopy(cur.orders)
    payload = request(2)
    options = {}
    if change in ("symbol", "qty", "limit_price", "side"):
        payload[change] = {"symbol": "QQQ", "qty": "3", "limit_price": "401", "side": "sell"}[change]
    if change == "source":
        options["source"] = "agent"
    with pytest.raises(ValueError, match="conflicts"):
        repo.insert_order(cur, 1, first["request_key"], OTHER_CONNECTION if change == "connection" else CONNECTION,
                          payload, **options)
    assert cur.orders == before


def test_request_keys_are_scoped_to_user_and_connection_hash_is_not_account_id(cur):
    first = insert(cur)
    second = insert(cur, uid=2, number=2)
    assert first["id"] != second["id"]
    assert repo.get_order(cur, 2, first["id"]) is None
    assert repo.get_order(cur, 1, first["id"], for_update=True)["id"] == first["id"]
    sql, params = cur.calls[-1]
    assert "WHERE user_id=%s AND id=%s FOR UPDATE" in sql and params == (1, first["id"])


def test_claim_is_compare_and_set_and_uncertain_replay_never_resubmits(cur):
    row = insert(cur)
    assert repo.claim_submission(cur, 1, row["id"])
    assert not repo.claim_submission(cur, 1, row["id"])
    assert repo.record_result(cur, 1, row["id"], status="unknown", error_code="submission_uncertain")
    assert not repo.claim_submission(cur, 1, row["id"])
    assert insert(cur, number=2)["status"] == "unknown"
    assert not repo.claim_submission(cur, 2, row["id"])


def test_cancel_draft_races_submission_without_reopening_it(cur):
    first = insert(cur)
    assert repo.cancel_draft(cur, 1, first["id"])
    assert not repo.claim_submission(cur, 1, first["id"])
    assert not repo.cancel_draft(cur, 1, first["id"])
    second = insert(cur, key="other", number=2)
    assert repo.claim_submission(cur, 1, second["id"])
    assert not repo.cancel_draft(cur, 1, second["id"])
    assert not repo.cancel_draft(cur, 2, second["id"])


def test_bind_proposal_requires_draft_correct_owner_kind_and_single_binding(cur):
    row = insert(cur, source="agent")
    assert repo.bind_proposal(cur, 1, row["id"], 10)
    assert repo.get_order(cur, 1, row["id"])["proposal_id"] == 10
    assert insert(cur, number=5, source="agent")["proposal_id"] == 10
    for proposal_id in (11, 12, 99):
        with pytest.raises(ValueError, match="does not belong"):
            repo.bind_proposal(cur, 1, row["id"], proposal_id)
    assert not repo.bind_proposal(cur, 2, row["id"], 11)
    cur.proposals[13] = (1, "alpaca_paper")
    assert not repo.bind_proposal(cur, 1, row["id"], 13)
    assert repo.claim_submission(cur, 1, row["id"])
    assert not repo.bind_proposal(cur, 1, row["id"], 10)


def test_insert_proposal_requires_same_owner_and_kind(cur):
    with pytest.raises(ValueError, match="does not belong"):
        insert(cur, source="agent", proposal_id=11)
    assert not cur.orders
    assert insert(cur, source="agent", proposal_id=10)["proposal_id"] == 10


def test_partial_fills_and_status_only_errors_preserve_observed_money(cur, monkeypatch):
    order_id = submit(cur)
    assert repo.record_result(cur, 1, order_id, status="submitted", broker_status="partially_filled",
                              filled_qty="1.25", filled_avg_price="400.12")
    monkeypatch.setattr(repo, "now_utc", lambda: NOW + timedelta(seconds=3))
    assert repo.record_result(cur, 1, order_id, status="cancel_pending", error_code="cancel_needs_reconciliation")
    row = repo.get_order(cur, 1, order_id)
    assert row["filled_qty"] == Decimal("1.25") and row["filled_avg_price"] == Decimal("400.12")
    assert row["broker_order_id"] == BROKER_ID and row["broker_status"] == "partially_filled"
    assert row["submitted_at"] == NOW and row["updated_at"] == NOW + timedelta(seconds=3)
    assert not repo.record_result(cur, 1, order_id, status="submitted", broker_status="new", filled_qty="0")
    assert repo.record_result(cur, 1, order_id, status="canceled", broker_status="canceled",
                              filled_qty="1.25", filled_avg_price="400.12")


@pytest.mark.parametrize("terminal", ["filled", "canceled", "expired", "rejected"])
def test_terminal_broker_observation_does_not_reopen_or_change_fills(cur, terminal):
    order_id = submit(cur)
    assert repo.record_result(cur, 1, order_id, status="submitted", broker_status=terminal,
                              filled_qty="2", filled_avg_price="400.12")
    before = copy.deepcopy(cur.orders)
    assert not repo.record_result(cur, 1, order_id, status="submitted", broker_status="new")
    assert not repo.record_result(cur, 1, order_id, status="unknown", error_code="submission_uncertain")
    assert not repo.record_result(cur, 1, order_id, status="submitted", broker_status=terminal,
                                  filled_qty="2", filled_avg_price="401")
    assert cur.orders == before
    assert repo.record_result(cur, 1, order_id, status="submitted", broker_status=terminal,
                              filled_qty="2", filled_avg_price="400.12")


def test_canceled_and_rejected_local_states_are_terminal(cur):
    row = insert(cur)
    assert repo.claim_submission(cur, 1, row["id"])
    assert repo.record_result(cur, 1, row["id"], status="rejected", error_code="broker_rejected")
    assert not repo.record_result(cur, 1, row["id"], status="unknown", error_code="submission_uncertain")
    assert not repo.record_result(cur, 2, row["id"], status="rejected")


@pytest.mark.parametrize("initial", ["submitted", "cancel_pending"])
def test_later_broker_rejection_finishes_an_acknowledged_order(cur, initial):
    order_id = submit(cur)
    if initial == "cancel_pending":
        assert repo.record_result(cur, 1, order_id, status="cancel_pending")
    assert repo.record_result(cur, 1, order_id, status="rejected", broker_status="rejected")
    assert repo.get_order(cur, 1, order_id)["status"] == "rejected"
    assert not repo.unsettled_orders(cur, 1, CONNECTION)


def test_cancel_can_begin_from_claimed_order_after_acknowledgement_lookup(cur):
    row = insert(cur)
    assert repo.claim_submission(cur, 1, row["id"])
    assert repo.record_result(cur, 1, row["id"], status="cancel_pending",
                              broker_status="new", broker_order_id=BROKER_ID)


def test_order_cannot_record_overfill_or_price_without_quantity(cur):
    order_id = submit(cur)
    before = copy.deepcopy(cur.orders)
    assert not repo.record_result(cur, 1, order_id, status="submitted", broker_status="filled",
                                  filled_qty="3", filled_avg_price="400.25")
    assert not repo.record_result(cur, 1, order_id, status="submitted", filled_avg_price="400.25")
    assert cur.orders == before


def test_submission_count_excludes_drafts_and_local_canceled_drafts(cur):
    assert repo.submission_count(cur, 1, CONNECTION) == 0
    first = insert(cur)
    second = insert(cur, key="second", number=2)
    assert repo.cancel_draft(cur, 1, first["id"])
    assert repo.submission_count(cur, 1, CONNECTION) == 0
    assert repo.claim_submission(cur, 1, second["id"])
    assert repo.submission_count(cur, 1, CONNECTION) == 1
    assert not repo.claim_submission(cur, 1, second["id"])
    assert repo.submission_count(cur, 1, CONNECTION) == 1


def test_fully_filled_intervening_claim_changes_count_when_unsettled_ids_do_not(cur):
    row = insert(cur)
    before_ids = repo.unsettled_orders(cur, 1, CONNECTION)
    before_count = repo.submission_count(cur, 1, CONNECTION)
    assert repo.claim_submission(cur, 1, row["id"])
    assert repo.record_result(cur, 1, row["id"], status="submitted", broker_order_id=BROKER_ID,
                              broker_status="filled", filled_qty="2", filled_avg_price="400.25")
    assert repo.unsettled_orders(cur, 1, CONNECTION) == before_ids == []
    assert repo.submission_count(cur, 1, CONNECTION) == before_count + 1


def test_claiming_older_draft_after_newer_terminal_order_increments_counter(cur):
    older = insert(cur)
    newer = insert(cur, key="newer", number=2)
    assert repo.claim_submission(cur, 1, newer["id"])
    assert repo.record_result(cur, 1, newer["id"], status="submitted", broker_order_id=BROKER_ID,
                              broker_status="filled", filled_qty="2", filled_avg_price="400.25")
    before_max_id = max(cur.orders)
    assert repo.submission_count(cur, 1, CONNECTION) == 1
    assert repo.claim_submission(cur, 1, older["id"])
    assert max(cur.orders) == before_max_id
    assert repo.submission_count(cur, 1, CONNECTION) == 2


@pytest.mark.parametrize("outcome", ["unknown", "rejected", "cancel_pending", "canceled"])
def test_submission_count_keeps_terminal_or_uncertain_claims(cur, outcome):
    row = insert(cur)
    assert repo.claim_submission(cur, 1, row["id"])
    options = {"broker_order_id": BROKER_ID, "broker_status": "canceled"} if outcome == "canceled" else {}
    assert repo.record_result(cur, 1, row["id"], status=outcome, **options)
    assert repo.submission_count(cur, 1, CONNECTION) == 1


def test_claimed_order_cannot_leave_counter_via_unproven_local_cancel(cur):
    row = insert(cur)
    assert repo.claim_submission(cur, 1, row["id"])
    assert not repo.record_result(cur, 1, row["id"], status="canceled")
    assert repo.submission_count(cur, 1, CONNECTION) == 1
    assert repo.get_order(cur, 1, row["id"])["status"] == "submitting"


def test_submission_count_is_owner_and_connection_scoped_and_sql_is_unbounded(cur):
    first = insert(cur)
    other_connection = insert(cur, key="other-connection", connection=OTHER_CONNECTION, number=2)
    other_owner = insert(cur, uid=2, number=3)
    for uid, order in ((1, first), (1, other_connection), (2, other_owner)):
        assert repo.claim_submission(cur, uid, order["id"])
    assert repo.submission_count(cur, 1, CONNECTION) == 1
    query, params = cur.calls[-1]
    assert params == (1, CONNECTION) and "WHERE user_id=%s AND connection_hash=%s" in query
    assert "OR broker_order_id IS NOT NULL OR submitted_at IS NOT NULL" in query
    assert "LIMIT" not in query and "MAX(" not in query
    assert repo.submission_count(cur, 1, OTHER_CONNECTION) == 1
    assert repo.submission_count(cur, 2, CONNECTION) == 1


@pytest.mark.parametrize("result", [None, {}, {"submission_count": True}, {"submission_count": -1},
                                    {"submission_count": "1"}])
def test_submission_count_fails_closed_when_aggregate_is_unavailable(cur, monkeypatch, result):
    monkeypatch.setattr(cur, "fetchone", lambda: result)
    with pytest.raises(ValueError, match="count is unavailable"):
        repo.submission_count(cur, 1, CONNECTION)


@pytest.mark.parametrize("uid,connection", [(True, CONNECTION), (0, CONNECTION), (1, "raw-account-id")])
def test_submission_count_rejects_bad_context_before_sql(cur, uid, connection):
    with pytest.raises(ValueError):
        repo.submission_count(cur, uid, connection)
    assert not cur.calls


def test_established_broker_identity_cannot_be_replaced(cur):
    order_id = submit(cur)
    assert not repo.record_result(cur, 1, order_id, status="submitted", broker_status="new",
                                  broker_order_id="00000000-0000-0000-0000-000000000001")
    assert repo.get_order(cur, 1, order_id)["broker_order_id"] == BROKER_ID


def test_reservations_include_uncertain_and_acknowledged_nonterminal_orders_only(cur):
    for index, (status, broker_status) in enumerate([
        ("draft", None), ("submitting", None), ("unknown", None), ("cancel_pending", "pending_cancel"),
        ("submitted", None), ("submitted", "new"), ("submitted", "partially_filled"),
        ("submitted", "filled"), ("submitted", "canceled"), ("submitted", "expired"),
        ("submitted", "rejected"), ("canceled", None), ("rejected", None),
    ], 1):
        row = insert(cur, key="row-" + str(index), number=index)
        cur.orders[row["id"]].update(status=status, broker_status=broker_status)
    other = insert(cur, key="other-account", connection=OTHER_CONNECTION, number=100)
    cur.orders[other["id"]]["status"] = "unknown"
    other_user = insert(cur, uid=2, key="other-owner", number=101)
    cur.orders[other_user["id"]]["status"] = "unknown"
    assert {row["id"] for row in repo.in_flight_orders(cur, 1, CONNECTION)} == {2, 3, 4}
    assert {row["id"] for row in repo.unsettled_orders(cur, 1, CONNECTION)} == {2, 3, 4, 5, 6, 7}
    assert repo.in_flight_orders(cur, 2, CONNECTION)[0]["id"] == other_user["id"]
    query = next(sql for sql, _ in reversed(cur.calls) if "OR (status='submitted'" in sql)
    assert "broker_status IS NULL" in query and "LIMIT 501" in query


def test_unsettled_limit_keeps_overflow_sentinel_and_listing_is_owner_bounded(cur):
    for index in range(1, 503):
        row = insert(cur, key="row-" + str(index), number=index)
        cur.orders[row["id"]]["status"] = "unknown"
    assert len(repo.unsettled_orders(cur, 1, CONNECTION)) == 501
    assert len(repo.in_flight_orders(cur, 1, CONNECTION)) == 501
    assert [row["id"] for row in repo.list_orders(cur, 1, 2)] == [502, 501]
    assert repo.list_orders(cur, 2) == []


def test_read_projection_drops_unexpected_raw_provider_and_secret_fields(cur):
    row = insert(cur)
    cur.orders[row["id"]].update(access_token="synthetic-private", raw_response={"account_id": "private"})
    actual = repo.get_order(cur, 1, row["id"])
    assert not {"access_token", "raw_response", "request_json"} & actual.keys()
    actual["request"]["qty"] = "999"
    assert repo.get_order(cur, 1, row["id"])["request"]["qty"] == "2"
    assert all("SELECT *" not in sql for sql, _ in cur.calls)


def test_all_mutations_start_with_same_owner_lock(cur):
    row = insert(cur)
    operations = [lambda: insert(cur, number=2),
                  lambda: repo.bind_proposal(cur, 1, row["id"], 10),
                  lambda: repo.claim_submission(cur, 1, row["id"]),
                  lambda: repo.record_result(cur, 1, row["id"], status="unknown"),
                  lambda: repo.cancel_draft(cur, 1, row["id"])]
    for operation in operations:
        cur.calls.clear()
        operation()
        assert cur.calls[0] == ("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (1,))
        for sql, _ in cur.calls:
            if sql.startswith("UPDATE"):
                assert "WHERE user_id=%s AND id=%s" in sql
                assert "status=" in sql


def test_missing_user_cannot_create_orphan_order(cur):
    with pytest.raises(ValueError, match="owner does not exist"):
        insert(cur, uid=99)
    assert not cur.orders


@pytest.mark.parametrize("uid", [True, 0, -1, "1", 1.2, 2**63])
def test_invalid_owner_is_rejected_before_sql(cur, uid):
    with pytest.raises(ValueError):
        insert(cur, uid=uid)
    assert not cur.calls


@pytest.mark.parametrize("limit", [True, 0, -1, 101, "50", 1.5])
def test_limit_is_strict_and_bounded_before_sql(cur, limit):
    with pytest.raises(ValueError):
        repo.list_orders(cur, 1, limit)
    assert not cur.calls


@pytest.mark.parametrize("key", ["", "a" * 81, "has space", "taü", "a\n", "'; DROP TABLE orders;", True])
def test_request_key_is_bounded_ascii_before_sql(cur, key):
    with pytest.raises(ValueError):
        insert(cur, key=key)
    assert not cur.calls


@pytest.mark.parametrize("changes", [
    {"type": "market"}, {"time_in_force": "gtc"}, {"extended_hours": True}, {"extended_hours": 0},
    {"symbol": "SPY\n"}, {"symbol": "spy"}, {"side": "BUY"}, {"qty": 1}, {"qty": "NaN"},
    {"qty": "1e2"}, {"qty": "0"}, {"qty": "0.000000001"}, {"qty": "1000000000000"},
    {"limit_price": 400.1}, {"limit_price": "Infinity"}, {"limit_price": "-1"},
    {"access_token": "synthetic-private"}, {"raw_response": {}}, {"stop_price": "390"},
    {"notional": "100"}, {"client_order_id": "arbitrary-raw-id"},
])
def test_only_normalized_limit_day_payload_can_be_stored(cur, changes):
    payload = request()
    payload.update(changes)
    with pytest.raises(ValueError):
        repo.insert_order(cur, 1, "request-1", CONNECTION, payload)
    assert not cur.calls


@pytest.mark.parametrize("kwargs", [
    {"status": "filled"}, {"status": []}, {"error_code": "sensitive broker error body"},
    {"error_code": "submission_uncertain\n"}, {"broker_status": "unrecognized"},
    {"broker_order_id": "private-account-identifier"}, {"filled_qty": 1.0},
    {"filled_qty": "-1"}, {"filled_qty": "NaN"}, {"filled_qty": "1e0"},
    {"filled_qty": "1000000000000"}, {"filled_qty": "0.000000001"},
    {"filled_qty": Decimal("1E+999999999")}, {"filled_qty": Decimal("0E+999999999")},
    {"filled_qty": Decimal("NaN")},
    {"filled_qty": "1"}, {"filled_qty": "0", "filled_avg_price": "400"},
    {"filled_qty": "1", "filled_avg_price": "0"},
])
def test_invalid_projection_or_money_is_rejected_before_sql(cur, kwargs):
    arguments = {"status": "unknown", **kwargs}
    with pytest.raises(ValueError):
        repo.record_result(cur, 1, 1, **arguments)
    assert not cur.calls


def test_decimal_zero_from_mysql_does_not_break_status_only_reconciliation(cur):
    order_id = submit(cur)
    cur.orders[order_id]["filled_qty"] = Decimal("0.00000000")
    assert repo.record_result(cur, 1, order_id, status="unknown", error_code="submission_uncertain")


def test_ddl_adds_durable_unique_identities_decimal_money_and_reservation_index():
    joined = " ".join(repo.DDL)
    assert len(repo.DDL) == 1 and "CREATE TABLE IF NOT EXISTS app_alpaca_paper_orders" in joined
    assert "UNIQUE KEY uq_alpaca_paper_request (user_id, request_key)" in joined
    assert "UNIQUE KEY uq_alpaca_paper_client_id (client_order_id)" in joined
    assert "request_key VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin" in joined
    assert "connection_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin" in joined
    assert "DECIMAL(20,8)" in joined and "FLOAT" not in joined
    assert "idx_alpaca_paper_unsettled (user_id, connection_hash, status)" in joined
    assert "request_json JSON NOT NULL" in joined and "AUTO_INCREMENT PRIMARY KEY" in joined
    assert "tokens_enc" not in joined and "raw_json" not in joined
