"""Synthetic transactional order-store checks; no broker, keys or live database."""
import copy
import hashlib
import json
from datetime import datetime
from decimal import Decimal

import pytest

from app import kalshi_perps_orders_repository as repo
from app.repository import transaction


NOW = datetime(2026, 10, 23, 3, 0)
KEY = hashlib.sha256(b"synthetic-key-revision").hexdigest()
OTHER_KEY = hashlib.sha256(b"rotated-synthetic-key").hexdigest()
BROKER_ID = "native/order:non-uuid-123"


def request(**overrides):
    body = dict(ticker="BTC-PERP", side="bid", count="10", price="6.123400",
                market_version=3, time_in_force="immediate_or_cancel",
                self_trade_prevention_type="taker_at_cross", cancel_order_on_pause=True,
                reduce_only=False, post_only=False, subaccount=0)
    body.update(overrides)
    return body


def instrument(**overrides):
    result = dict(ticker="BTC-PERP", verified_bitcoin=True, market_version=3,
                  environment="production", contract_size="0.0001", underlying_multiplier="1",
                  contract_multiplier="0.0001", price_unit="USD", price_basis="per_contract", tick_size="0.0001")
    result.update(overrides)
    return result


class PerpsCursor:
    """Exact query-shape fake, with independent compare-and-set row semantics."""
    def __init__(self):
        self.users = {1, 2}
        self.proposals = {10: (1, "kalshi_perps_live"), 11: (2, "kalshi_perps_live"), 12: (1, "research")}
        self.settings, self.orders = {}, {}
        self.calls, self._rows = [], []
        self.rowcount, self.lastrowid = 0, None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        self.rowcount, self._rows = 0, []
        if sql == "SELECT id FROM app_users WHERE id=%s FOR UPDATE":
            self._rows = [{"id": params[0]}] if params[0] in self.users else []
        elif sql.startswith("SELECT id FROM app_proposals"):
            pid, uid = params
            self._rows = [{"id": pid}] if self.proposals.get(pid) == (uid, "kalshi_perps_live") else []
        elif sql.startswith("SELECT") and "FROM app_kalshi_perps_settings" in sql:
            row = self.settings.get(tuple(params))
            self._rows = [row] if row else []
        elif sql.startswith("INSERT INTO app_kalshi_perps_settings"):
            uid, env, created, updated = params
            assert (uid, env) not in self.settings
            self.settings[(uid, env)] = dict(user_id=uid, environment=env, enabled=False,
                manual_confirmation_required=True, risk_mode="kalshi_limits", version=0,
                risk_revision=0, created_at=created, updated_at=updated)
            self.rowcount = 1
        elif sql.startswith("UPDATE app_kalshi_perps_settings SET enabled="):
            enabled, updated, uid, env, version = params
            row = self.settings.get((uid, env))
            if row and row["version"] == version:
                row.update(enabled=enabled, version=version + 1, risk_revision=row["risk_revision"] + 1,
                           updated_at=updated)
                self.rowcount = 1
        elif sql.startswith("UPDATE app_kalshi_perps_settings SET risk_revision="):
            updated, uid, env, risk = params
            row = self.settings.get((uid, env))
            if row and row["risk_revision"] == risk:
                row.update(risk_revision=risk + 1, updated_at=updated)
                self.rowcount = 1
        elif sql.startswith("SELECT") and "FROM app_kalshi_perps_orders" in sql:
            uid, env = params[:2]
            rows = [row for row in self.orders.values() if (row["user_id"], row["environment"]) == (uid, env)]
            if "COUNT(*) AS submission_count" in sql:
                self._rows = [{"submission_count": sum(row["claimed_at"] is not None for row in rows)}]
                return
            if "AND id=%s" in sql:
                rows = [row for row in rows if row["id"] == params[2]]
            elif "AND client_token=%s" in sql:
                rows = [row for row in rows if row["client_token"] == params[2]]
            elif "AND status IN" in sql:
                rows = [row for row in rows if row["status"] in ("claimed", "accepted", "unknown", "cancel_pending")]
            rows = sorted(rows, key=lambda row: row["id"], reverse=True)
            self._rows = rows[:501] if "LIMIT 501" in sql else rows[:params[-1]] if "LIMIT %s" in sql else rows
        elif sql.startswith("INSERT INTO app_kalshi_perps_orders"):
            uid, env, token, key, client, digest, body, ihash, source, proposal, preview, notional, reserved, created, updated = params
            assert all((row["user_id"], row["environment"], row["client_token"]) != (uid, env, token)
                       and (row["environment"], row["client_order_id"]) != (env, client)
                       for row in self.orders.values())
            self.lastrowid = max(self.orders, default=0) + 1
            self.orders[self.lastrowid] = dict(id=self.lastrowid, user_id=uid, environment=env,
                client_token=token, key_revision_hash=key, client_order_id=client, request_hash=digest,
                request_json=body, instrument_hash=ihash, source=source, notional_usd=notional,
                proposal_id=proposal, preview_json=preview,
                reserved_usd=reserved, status="draft", version=0, approved_by_user_id=None,
                approved_policy_version=None, approved_at=None, claimed_at=None, broker_order_id=None,
                filled_count=Decimal(0), remaining_count=None, filled_notional_usd=None,
                fees_paid_usd=None, error_code=None, created_at=created, updated_at=updated)
            self.rowcount = 1
        elif sql.startswith("UPDATE app_kalshi_perps_orders SET status='approved'"):
            actor, policy, approved, updated, uid, env, oid, version = params
            row = self.orders.get(oid)
            if self._matches(row, uid, env, version) and row["status"] == "draft":
                row.update(status="approved", version=version + 1, approved_by_user_id=actor,
                           approved_policy_version=policy, approved_at=approved, updated_at=updated)
                self.rowcount = 1
        elif sql.startswith("UPDATE app_kalshi_perps_orders SET status='claimed'"):
            claimed, updated, uid, env, oid, version = params
            row = self.orders.get(oid)
            if self._matches(row, uid, env, version) and row["status"] == "approved" and row["claimed_at"] is None:
                row.update(status="claimed", version=version + 1, claimed_at=claimed,
                           error_code=None, updated_at=updated)
                self.rowcount = 1
        elif sql.startswith("UPDATE app_kalshi_perps_orders SET status='canceled'"):
            updated, uid, env, oid, version = params
            row = self.orders.get(oid)
            if self._matches(row, uid, env, version) and row["status"] in ("draft", "approved") and row["claimed_at"] is None:
                row.update(status="canceled", version=version + 1, remaining_count=Decimal(0),
                           error_code="user_canceled", updated_at=updated)
                self.rowcount = 1
        elif sql.startswith("UPDATE app_kalshi_perps_orders SET status=%s"):
            status, broker, filled, remaining, cash, fees, error, updated, uid, env, oid, old, version = params
            row = self.orders.get(oid)
            if self._matches(row, uid, env, version) and row["status"] == old and row["claimed_at"] is not None:
                row.update(status=status, broker_order_id=broker, filled_count=filled, remaining_count=remaining,
                           filled_notional_usd=cash, fees_paid_usd=fees, error_code=error,
                           version=version + 1, updated_at=updated)
                self.rowcount = 1
        else:
            raise AssertionError("Unexpected SQL: " + sql)

    @staticmethod
    def _matches(row, uid, env, version):
        return row and (row["user_id"], row["environment"], row["version"]) == (uid, env, version)

    def fetchone(self):
        return copy.deepcopy(self._rows[0]) if self._rows else None

    def fetchall(self):
        return copy.deepcopy(self._rows)


class FakeConnection:
    def __init__(self, cur):
        self.cur, self.commits, self.rollbacks, self.backup = cur, 0, 0, None

    def begin(self):
        self.backup = copy.deepcopy((self.cur.settings, self.cur.orders))

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1
        self.backup = None

    def rollback(self):
        self.cur.settings, self.cur.orders = self.backup
        self.rollbacks += 1


@pytest.fixture
def cur(monkeypatch):
    monkeypatch.setattr(repo, "now_utc", lambda: NOW)
    return PerpsCursor()


def draft(cur, uid=1, env="production", token="draft-1", key=KEY, payload=None, metadata=None, **kwargs):
    return repo.insert_draft(cur, uid, env, token, key, payload or request(),
                             instrument=metadata or instrument(environment=env), **kwargs)


def enabled(cur, uid=1, env="production"):
    policy = repo.get_settings(cur, uid, env)
    return repo.save_settings(cur, uid, env, enabled=True, expected_version=policy["version"])


def approve(cur, row, **overrides):
    policy = repo.get_settings(cur, row["user_id"], row["environment"])
    options = dict(expected_version=row["version"], expected_policy_version=policy["version"],
                   expected_request_hash=row["request_hash"],
                   key_revision_hash=row["key_revision_hash"], actor_user_id=row["user_id"], confirmed=True)
    options.update(overrides)
    return repo.approve_order(cur, row["user_id"], row["environment"], row["id"], **options)


def claim(cur, row, **overrides):
    current = repo.get_order(cur, row["user_id"], row["environment"], row["id"])
    policy = repo.get_settings(cur, row["user_id"], row["environment"])
    options = dict(expected_version=current["version"], expected_policy_version=policy["version"],
                   expected_risk_revision=policy["risk_revision"], key_revision_hash=row["key_revision_hash"])
    options.update(overrides)
    return repo.claim_submission(cur, row["user_id"], row["environment"], row["id"], **options)


def claimed(cur, token="draft-1"):
    row = draft(cur, token=token)
    enabled(cur)
    assert approve(cur, row)
    assert claim(cur, row)
    return repo.get_order(cur, 1, "production", row["id"])


def test_defaults_manual_opt_out_native_limits_without_tau_financial_caps(cur):
    policy = repo.get_settings(cur, 1, "production")
    assert policy["enabled"] is False and policy["manual_confirmation_required"] is True
    assert policy["risk_mode"] == "kalshi_limits"
    assert not any("leverage" in name or "notional" in name or "cap" in name for name in policy)
    assert not cur.settings  # a read does not opt in or create rows
    saved = enabled(cur)
    assert saved["version"] == 1 and saved["risk_revision"] == 1
    assert repo.get_settings(cur, 1, "demo")["enabled"] is False
    assert repo.get_settings(cur, 2, "production")["enabled"] is False
    with pytest.raises(ValueError, match="changed"):
        repo.save_settings(cur, 1, "production", enabled=False, expected_version=0)


def test_draft_uses_server_uuid_frozen_digest_exact_usd_and_whole_count(cur):
    row = draft(cur, reserved_usd="3.5")
    assert row["status"] == "draft" and row["version"] == 0
    assert row["request"]["count"] == "10.00" and row["request"]["price"] == "6.1234"
    assert row["notional_usd"] == Decimal("61.234") and row["reserved_usd"] == Decimal("3.5")
    assert row["request"]["client_order_id"] == row["client_order_id"]
    encoded = json.dumps(row["request"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert row["request_hash"] == hashlib.sha256(encoded.encode()).hexdigest()
    assert row["claimed_at"] is None and row["approved_at"] is None
    assert "request_json" not in row
    assert repo.submission_count(cur, 1, "production") == 0


def test_identical_draft_replay_preserves_uuid_and_never_updates_it(cur):
    first = draft(cur)
    before = copy.deepcopy(cur.orders)
    cur.calls.clear()
    replay = draft(cur, payload=request(price="6.1234000", count="10.00"))
    assert replay == first and cur.orders == before
    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in cur.calls)


@pytest.mark.parametrize("change", ["key", "count", "price", "side", "source", "reserved", "reduce_only"])
def test_draft_token_cannot_change_an_immutable_order(cur, change):
    draft(cur)
    options, body = {}, request()
    if change == "key":
        options["key"] = OTHER_KEY
    elif change == "source":
        options["source"] = "agent"
        options["proposal_id"] = 10
    elif change == "reserved":
        options["reserved_usd"] = "1"
    else:
        body[change] = {"count": "11", "price": "6.12", "side": "ask", "reduce_only": True}[change]
    with pytest.raises(ValueError, match="conflicts"):
        draft(cur, payload=body, **options)


def test_all_order_lookups_are_owner_and_environment_scoped(cur):
    first = draft(cur)
    second = draft(cur, uid=2)
    demo = draft(cur, env="demo")
    assert len({first["id"], second["id"], demo["id"]}) == 3
    assert repo.get_order(cur, 2, "production", first["id"]) is None
    assert repo.get_order(cur, 1, "demo", first["id"]) is None
    assert [row["id"] for row in repo.list_orders(cur, 1, "production")] == [first["id"]]
    for sql, params in cur.calls:
        if sql.startswith("SELECT") and "FROM app_kalshi_perps_" in sql:
            assert "WHERE user_id=%s AND environment=%s" in sql


def test_each_agent_draft_requires_real_owner_confirmation(cur):
    row = draft(cur, source="agent", proposal_id=10)
    assert not approve(cur, row)  # no opt-in
    enabled(cur)
    assert not claim(cur, row)  # opt-in never sends an unconfirmed draft
    for changes in ({"confirmed": False}, {"confirmed": 1}, {"actor_user_id": 2}):
        with pytest.raises(ValueError, match="owner must explicitly confirm"):
            approve(cur, row, **changes)
    assert approve(cur, row)
    approved = repo.get_order(cur, 1, "production", row["id"])
    assert approved["approved_by_user_id"] == 1 and approved["approved_at"] == NOW
    assert claim(cur, approved)


def test_approval_and_claim_bind_current_policy_key_risk_and_order_version(cur):
    row = draft(cur)
    enabled(cur)
    assert not approve(cur, row, expected_policy_version=0)
    assert not approve(cur, row, key_revision_hash=OTHER_KEY)
    assert not approve(cur, row, expected_version=1)
    assert not approve(cur, row, expected_request_hash="0" * 64)
    assert approve(cur, row)
    assert not claim(cur, row, expected_version=0)
    assert not claim(cur, row, key_revision_hash=OTHER_KEY)
    assert not claim(cur, row, expected_risk_revision=0)
    policy = repo.get_settings(cur, 1, "production")
    repo.save_settings(cur, 1, "production", enabled=False, expected_version=policy["version"])
    assert not claim(cur, row)
    enabled(cur)  # previous approval cannot silently survive a policy change/re-enable
    assert not claim(cur, row)


def test_claim_commit_precedes_network_and_crash_recovery_never_claims_again(cur):
    row = draft(cur)
    enabled(cur)
    assert approve(cur, row)
    conn = FakeConnection(cur)
    with transaction(conn) as cursor:
        assert claim(cursor, row)
    assert conn.commits == 1
    sent = [repo.get_order(cur, 1, "production", row["id"])["request"]]
    # Process dies immediately after the committed irreversible claim. Recovery
    # may inspect/reconcile, but cannot acquire another send authorization.
    with transaction(conn) as cursor:
        assert not claim(cursor, row)
        assert repo.record_result(cursor, 1, "production", row["id"], status="unknown",
                                  error_code="submission_uncertain")
    assert len(sent) == 1 and not claim(cur, row)
    assert draft(cur)["status"] == "unknown"
    assert repo.submission_count(cur, 1, "production") == 1
    assert repo.reservation_orders(cur, 1, "production")[0]["id"] == row["id"]


def test_risk_revision_detects_intervening_fully_filled_order_and_key_rotation(cur):
    older = draft(cur, token="older")
    enabled(cur)
    assert approve(cur, older)
    risk = repo.get_settings(cur, 1, "production")["risk_revision"]
    newer = draft(cur, token="newer", key=OTHER_KEY)
    assert approve(cur, newer)
    assert claim(cur, newer)
    assert repo.record_result(cur, 1, "production", newer["id"], status="filled", broker_order_id=BROKER_ID,
                              filled_count="10", remaining_count="0", filled_notional_usd="60", fees_paid_usd="0.1")
    assert repo.reservation_orders(cur, 1, "production") == []
    assert not claim(cur, older, expected_risk_revision=risk)
    assert claim(cur, older)  # service must obtain a fresh broker/risk snapshot first
    assert repo.submission_count(cur, 1, "production") == 2


def test_risk_bump_failure_rolls_back_claim_with_its_policy_transaction(cur, monkeypatch):
    row = draft(cur)
    enabled(cur)
    assert approve(cur, row)
    conn = FakeConnection(cur)
    monkeypatch.setattr(repo, "_bump_risk", lambda *args: (_ for _ in ()).throw(ValueError("risk changed")))
    with pytest.raises(ValueError, match="risk changed"):
        with transaction(conn) as cursor:
            claim(cursor, row)
    saved = repo.get_order(cur, 1, "production", row["id"])
    assert conn.rollbacks == 1 and saved["status"] == "approved" and saved["claimed_at"] is None


def test_cancel_unsent_approval_races_claim_without_releasing_sent_order(cur):
    first = draft(cur)
    enabled(cur)
    assert approve(cur, first)
    assert repo.cancel_draft(cur, 1, "production", first["id"], expected_version=1)
    assert not claim(cur, first)
    assert repo.submission_count(cur, 1, "production") == 0
    second = draft(cur, token="second")
    assert approve(cur, second) and claim(cur, second)
    assert not repo.cancel_draft(cur, 1, "production", second["id"], expected_version=2)
    assert not repo.begin_cancel(cur, 1, "production", second["id"], expected_version=2)  # no broker ID
    assert repo.record_result(cur, 1, "production", second["id"], status="accepted", broker_order_id=BROKER_ID)
    current = repo.get_order(cur, 1, "production", second["id"])
    assert repo.begin_cancel(cur, 1, "production", second["id"], expected_version=current["version"])
    assert repo.record_result(cur, 1, "production", second["id"], status="unknown", error_code="cancel_uncertain")
    assert len(repo.reservation_orders(cur, 1, "production")) == 1


def test_missing_remaining_or_missing_money_never_implies_terminal_ioc(cur):
    row = claimed(cur)
    base = dict(broker_order_id=BROKER_ID, filled_count="3", filled_notional_usd="18", fees_paid_usd="0.1")
    assert not repo.record_result(cur, 1, "production", row["id"], status="partial", **base)
    assert not repo.record_result(cur, 1, "production", row["id"], status="partial", remaining_count="1", **base)
    incomplete = {key: value for key, value in base.items() if key != "fees_paid_usd"}
    assert not repo.record_result(cur, 1, "production", row["id"], status="partial", remaining_count="0", **incomplete)
    assert repo.record_result(cur, 1, "production", row["id"], status="partial", remaining_count="0", **base)
    saved = repo.get_order(cur, 1, "production", row["id"])
    assert saved["filled_count"] == Decimal(3) and saved["filled_notional_usd"] == Decimal(18)
    assert not repo.reservation_orders(cur, 1, "production")
    assert repo.submission_count(cur, 1, "production") == 1


def test_whole_contract_request_can_have_fractional_native_partial_fills(cur):
    row = claimed(cur)
    assert repo.record_result(cur, 1, "production", row["id"], status="partial", broker_order_id=BROKER_ID,
                              filled_count="0.01", remaining_count="0", filled_notional_usd="0.061234", fees_paid_usd="0.001")
    assert repo.get_order(cur, 1, "production", row["id"])["filled_count"] == Decimal("0.01")


def test_fill_money_cannot_regress_or_be_reused_for_larger_fill_count(cur):
    row = claimed(cur)
    assert repo.record_result(cur, 1, "production", row["id"], status="accepted", broker_order_id=BROKER_ID,
                              filled_count="3", filled_notional_usd="18", fees_paid_usd="0.1")
    for change in ({"filled_count": "2"}, {"filled_notional_usd": "17"}, {"fees_paid_usd": "0.01"},
                   {"filled_count": "11"}, {"remaining_count": "8"}):
        assert not repo.record_result(cur, 1, "production", row["id"], status="accepted", **change)
    assert not repo.record_result(cur, 1, "production", row["id"], status="filled", filled_count="10", remaining_count="0")
    assert repo.record_result(cur, 1, "production", row["id"], status="unknown", filled_count="4")
    saved = repo.get_order(cur, 1, "production", row["id"])
    assert saved["filled_notional_usd"] is None and saved["fees_paid_usd"] is None


@pytest.mark.parametrize("status,fill", [("filled", "10"), ("partial", "3"), ("canceled", "0"), ("rejected", "0")])
def test_terminal_observations_are_idempotent_and_never_reopen_or_resubmit(cur, status, fill):
    row = claimed(cur)
    options = dict(broker_order_id=BROKER_ID, filled_count=fill, remaining_count="0",
                   filled_notional_usd="60" if fill == "10" else "18" if fill == "3" else "0",
                   fees_paid_usd="0.1", error_code="broker_rejected" if status == "rejected" else None)
    assert repo.record_result(cur, 1, "production", row["id"], status=status, **options)
    before = copy.deepcopy(cur.orders)
    assert repo.record_result(cur, 1, "production", row["id"], status=status, **options)
    assert not repo.record_result(cur, 1, "production", row["id"], status="unknown", error_code="order_not_found")
    assert not claim(cur, row) and cur.orders == before
    assert repo.submission_count(cur, 1, "production") == 1


def test_not_found_after_ambiguous_send_is_not_proof_of_rejection(cur):
    row = claimed(cur)
    assert not repo.record_result(cur, 1, "production", row["id"], status="rejected", error_code="order_not_found")
    assert repo.record_result(cur, 1, "production", row["id"], status="unknown", error_code="order_not_found")
    assert repo.reservation_orders(cur, 1, "production") and not claim(cur, row)


def test_broker_identity_and_optimistic_result_version_are_immutable(cur):
    row = claimed(cur)
    assert repo.record_result(cur, 1, "production", row["id"], status="accepted", broker_order_id=BROKER_ID)
    assert not repo.record_result(cur, 1, "production", row["id"], status="accepted", broker_order_id="different")
    assert not repo.record_result(cur, 1, "production", row["id"], status="unknown", expected_version=row["version"])


def test_reservations_include_old_key_revisions_and_overflow_sentinel(cur):
    for index in range(503):
        row = draft(cur, token="r-%s" % index, key=KEY if index % 2 else OTHER_KEY)
        cur.orders[row["id"]].update(status="unknown", claimed_at=NOW)
    assert len(repo.reservation_orders(cur, 1, "production")) == 501
    assert repo.submission_count(cur, 1, "production") == 503
    assert not repo.reservation_orders(cur, 2, "production")
    assert not repo.reservation_orders(cur, 1, "demo")


def test_public_projection_drops_raw_broker_credentials_and_json_aliases(cur):
    row = draft(cur)
    cur.orders[row["id"]].update(raw_response={"private": "raw"}, private_key="secret", key_id="secret")
    fetched = repo.get_order(cur, 1, "production", row["id"])
    assert not {"raw_response", "private_key", "key_id", "request_json"} & fetched.keys()
    fetched["request"]["count"] = "100"
    assert repo.get_order(cur, 1, "production", row["id"])["request"]["count"] == "10.00"
    assert all("SELECT *" not in sql for sql, _ in cur.calls)


def test_corrupted_persisted_digest_cannot_become_a_send_body(cur):
    row = draft(cur)
    cur.orders[row["id"]]["request_hash"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        repo.get_order(cur, 1, "production", row["id"])


def test_mutations_take_stable_owner_lock_and_scope_all_updates(cur):
    row = claimed(cur)
    operations = [lambda: draft(cur, token="new"), lambda: enabled(cur),
                  lambda: approve(cur, row), lambda: claim(cur, row),
                  lambda: repo.cancel_draft(cur, 1, "production", row["id"], expected_version=row["version"]),
                  lambda: repo.record_result(cur, 1, "production", row["id"], status="unknown")]
    for operation in operations:
        cur.calls.clear()
        operation()
        # Wrapper helpers may read a current version, but the mutation itself
        # must acquire this stable owner lock before any SQL INSERT/UPDATE.
        mutation_index = next((i for i, (sql, _) in enumerate(cur.calls) if sql.startswith(("INSERT", "UPDATE"))), None)
        assert ("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (1,)) in cur.calls
        if mutation_index is not None:
            assert any(sql == "SELECT id FROM app_users WHERE id=%s FOR UPDATE" for sql, _ in cur.calls[:mutation_index])
        for sql, _ in cur.calls:
            if sql.startswith("UPDATE"):
                assert "WHERE user_id=%s AND environment=%s" in sql
                assert "version=" in sql or "risk_revision=" in sql


@pytest.mark.parametrize("change", [
    {"count": "0"}, {"count": "1.5"}, {"count": 1}, {"count": "1e3"}, {"count": "01"},
    {"price": 1.25}, {"price": "NaN"}, {"price": "Infinity"}, {"price": "1e-4"}, {"price": "0"},
    {"time_in_force": "day"}, {"side": "yes"}, {"reduce_only": 0}, {"post_only": True},
    {"cancel_order_on_pause": False}, {"self_trade_prevention_type": "none"}, {"subaccount": 1},
    {"market_version": True}, {"market_version": 0}, {"ticker": "BTC\n"}, {"client_order_id": "chosen-by-browser"},
    {"private_key": "synthetic-secret"}, {"raw_response": {}}, {"type": "limit"},
])
def test_invalid_or_extra_native_order_fields_rejected_before_sql(cur, change):
    with pytest.raises(ValueError):
        draft(cur, payload=request(**change))
    assert not cur.calls


@pytest.mark.parametrize("change", [{"verified_bitcoin": False}, {"ticker": "ETH-PERP"},
                                    {"contract_size": "1"}, {"market_version": 4}, {"environment": "demo"}])
def test_native_btc_metadata_must_bind_ticker_size_version_and_environment(cur, change):
    with pytest.raises(ValueError):
        repo.insert_draft(cur, 1, "production", "a", KEY, request(), instrument=instrument(**change))
    assert not cur.calls


@pytest.mark.parametrize("value", [1.0, "-1", "NaN", "1e2", "0.0000000000000000001",
                                   Decimal("1E+999999999"), Decimal("0E+999999999")])
def test_unrepresentable_or_float_money_rejected_before_sql(cur, value):
    with pytest.raises(ValueError):
        draft(cur, reserved_usd=value)
    assert not cur.calls


def test_native_precision_is_preserved_and_large_native_notional_has_no_tau_cap(cur):
    row = draft(cur, payload=request(count="10000", price="12.34567890123456789"), reserved_usd="2",
                metadata=instrument(tick_size="0.000000000000000001"))
    assert row["notional_usd"] == Decimal("123456.7890123456789")
    assert row["reserved_usd"] == 2  # native margin may be a fraction of gross notional
    assert row["request"]["price"] == "12.34567890123456789"


def test_agent_proposal_owner_kind_and_immutable_binding(cur):
    with pytest.raises(ValueError, match="agent proposal"):
        draft(cur, source="agent")
    for pid in (11, 12, 99):
        with pytest.raises(ValueError, match="owner/kind"):
            draft(cur, source="agent", proposal_id=pid)
    with pytest.raises(ValueError, match="cannot bind"):
        draft(cur, proposal_id=10)
    first = draft(cur, source="agent", proposal_id=10)
    assert first["proposal_id"] == 10
    cur.proposals[13] = (1, "kalshi_perps_live")
    with pytest.raises(ValueError, match="conflicts"):
        draft(cur, source="agent", proposal_id=13)


def test_safe_preview_is_first_frozen_capture_and_replay_ignores_fresh_snapshot(cur):
    preview = dict(contract_multiplier="0.0001", btc_quantity="0.001", notional_usd="61.234",
                   taker_fee_rate="0.0012", estimated_fee_usd="0.0734808", account_equity="-1",
                   available_balance="-0.1", account_leverage="20", quoted_at="2026-10-23T03:00:00Z")
    row = draft(cur, preview=preview)
    assert row["preview"] == preview
    replay = draft(cur, preview={**preview, "available_balance": "999", "quoted_at": "2026-10-23T03:01:00Z"})
    assert replay["preview"] == preview
    replay["preview"]["account_equity"] = "666"
    assert repo.get_order(cur, 1, "production", row["id"])["preview"] == preview
    assert "preview_json" not in replay


@pytest.mark.parametrize("preview", [{"raw_response": {}}, {"key_id": "private"},
                                       {"available_balance": 1.25}, {"quoted_at": "2026-10-23"},
                                       {"estimated_fee_usd": "NaN"}])
def test_untrusted_preview_fields_or_inexact_values_rejected_before_sql(cur, preview):
    with pytest.raises(ValueError):
        draft(cur, preview=preview)
    assert not cur.calls


def test_instrument_digest_binds_economics_and_excludes_dynamic_quote_fields(cur):
    body = request()
    first = repo.instrument_digest(instrument(), body, "production")
    same = repo.instrument_digest(instrument(quoted_at="2026-10-23T03:00:00Z", bid="6"), body, "production")
    assert first == same
    changed = repo.instrument_digest(instrument(contract_size="2", underlying_multiplier="0.00005"), body, "production")
    assert changed != first
    for metadata in (instrument(price_basis="per_underlying"), instrument(price_unit="cents"),
                     instrument(contract_multiplier="1"), instrument(tick_size="0.01")):
        with pytest.raises(ValueError):
            repo.instrument_digest(metadata, body, "production")


def test_native_metadata_adapter_factors_bridge_to_store_without_double_multiplier(cur):
    from app.kalshi_perps_data import normalize_instrument

    native = dict(ticker="BTC-PERP", title="Bitcoin", asset_class="crypto", status="active",
                  contract_size="1.000000", underlying_multiplier="0.0001", tick_size="0.0001",
                  fractional_trading_enabled=False, schedule=None, exchange_index=1, market_version=3,
                  funding_deadband="0.0001", funding_cap="0.02", funding_limit_unit="percentage",
                  funding_invalid_premium_handling="dampen")
    normalized = normalize_instrument(native, "production", "2026-10-23T03:00:00Z")
    row = draft(cur, metadata=normalized)
    assert row["notional_usd"] == Decimal("61.234")  # 10 contracts * 6.1234 USD/contract
    assert normalized["contract_multiplier"] == "0.0001000000"
    assert row["instrument_hash"] == repo.instrument_digest(normalized, row["request"], "production")


def test_limit_fill_cash_consistency_checks_native_units_for_both_sides(cur):
    buy = claimed(cur)
    assert not repo.record_result(cur, 1, "production", buy["id"], status="filled", broker_order_id=BROKER_ID,
                                  filled_count="10", remaining_count="0", filled_notional_usd="62", fees_paid_usd="0.1")
    sell = draft(cur, token="sell", payload=request(side="ask"))
    assert approve(cur, sell) and claim(cur, sell)
    assert not repo.record_result(cur, 1, "production", sell["id"], status="filled", broker_order_id="sell-order",
                                  filled_count="10", remaining_count="0", filled_notional_usd="60", fees_paid_usd="0.1")
    assert repo.record_result(cur, 1, "production", sell["id"], status="filled", broker_order_id="sell-order",
                              filled_count="10", remaining_count="0", filled_notional_usd="62", fees_paid_usd="0.1")


@pytest.mark.parametrize("uid,env", [(True, "production"), (0, "production"), (1, "live"), (1, "production\n")])
def test_invalid_context_rejected_before_sql(cur, uid, env):
    with pytest.raises(ValueError):
        draft(cur, uid=uid, env=env)
    assert not cur.calls


@pytest.mark.parametrize("options", [{"status": "draft"}, {"status": "claimed"},
                                     {"status": "unknown", "filled_count": 1.0},
                                     {"status": "unknown", "filled_count": "-1"},
                                     {"status": "unknown", "broker_order_id": "raw\nresponse"},
                                     {"status": "unknown", "error_code": "raw broker secret"}])
def test_result_projection_rejects_unknown_fields_and_untrusted_text_before_sql(cur, options):
    with pytest.raises(ValueError):
        repo.record_result(cur, 1, "production", 1, **options)
    assert not cur.calls


def test_missing_owner_cannot_create_orphan_order_or_enable_settings(cur):
    with pytest.raises(ValueError, match="owner does not exist"):
        draft(cur, uid=99)
    with pytest.raises(ValueError, match="owner does not exist"):
        enabled(cur, uid=99)
    assert not cur.orders and not cur.settings


def test_ddl_uses_dedicated_context_unique_decimal_tables_and_no_private_fields():
    ddl = " ".join(repo.DDL)
    assert len(repo.DDL) == 2 and "DECIMAL(38,18)" in ddl and "FLOAT" not in ddl
    assert "PRIMARY KEY (user_id, environment)" in ddl
    assert "UNIQUE KEY uq_kalshi_perps_token (user_id, environment, client_token)" in ddl
    assert "UNIQUE KEY uq_kalshi_perps_client (environment, client_order_id)" in ddl
    assert "request_json JSON NOT NULL" in ddl and "request_hash CHAR(64)" in ddl
    assert "risk_revision BIGINT" in ddl and "claimed_at DATETIME" in ddl
    assert not any(name in ddl for name in ("private_key", "key_id", "raw_response", "alpaca_paper", "max_leverage", "max_order"))
