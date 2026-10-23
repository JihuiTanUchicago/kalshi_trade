"""Disposable MySQL + real loopback HTTP checks with an explicitly synthetic broker.

Run after the full app.schema and the separate Alpaca paper verifier. No broker
transport is constructed: encrypted, ephemeral per-user RSA fixtures are loaded
by the real service, then checked by the replacement client. Only a sanitized
receipt leaves this process. This is not real Kalshi order acceptance.
"""
from __future__ import annotations

import contextlib
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
from unittest.mock import patch
import uuid


# Reuse the reviewed credential, database, source-path, network and error guards.
# Loading this sibling imports no application module and opens no connection.
_SPEC = importlib.util.spec_from_file_location("tau_paper_staging_guards", Path(__file__).with_name("paper_staging_smoke.py"))
guards = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guards)
require = guards.require
SmokeError = guards.SmokeError
MODE = "synthetic_kalshi_perps_real_mysql_http"
PREFIX = "/api/kalshi/perps/live"
TICKER = "SYNTHBTC"
FIXED_FLAGS = {
    "TAU_KALSHI_PERPS_ENABLED": "0", "TAU_KALSHI_PERPS_LIVE_ENABLED": "1",
    "TAU_KALSHI_PERPS_ENVIRONMENT": "production", "TAU_KALSHI_PERPS_LIVE_ENVIRONMENT": "production",
}
FORBIDDEN_KEYS = (
    "TAU_KALSHI_PERPS_PROXY_URL", "TAU_KALSHI_PERPS_LIVE_TICKER", "TAU_KALSHI_PERPS_TICKER",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "NETRC",
    "KALSHI_PRIVATE_KEY", "KALSHI_PRIVATE_KEY_PATH", "KALSHI_API_KEY_ID",
    "KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY_PEM", "DEMO_KEYID", "DEMO_KEYFILE",
    "KALSHI_BASE_URL", "KALSHI_API_HOST", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
)
_HTTP_PORTS: set[int] = set()


def validate_environment(env: dict, source_root: Path, *, path_exists=None) -> None:
    guards.validate_environment(env, source_root, path_exists=path_exists)
    require(all(env.get(key) == value for key, value in FIXED_FLAGS.items()), "perps_isolation_flags_invalid")
    require(not any(env.get(key) for key in FORBIDDEN_KEYS), "perps_external_configuration_forbidden")


def failure_result(exc: Exception) -> dict:
    result = guards.failure_result(exc)
    result["mode"] = MODE
    return result


def stamp(**values) -> dict:
    return {"environment": "production", "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **values}


def instrument() -> dict:
    return stamp(ticker=TICKER, title="Synthetic Bitcoin 0.0001 BTC perpetual",
                 verified_bitcoin=True, status="active", schedule=None, market_version=3,
                 contract_size="1", underlying_multiplier="0.0001", contract_multiplier="0.0001",
                 price_unit="USD", price_basis="per_contract", tick_size="0.0001", quantity_step="1")


class SyntheticBroker:
    """Native-shaped fixture. Keys and order state are never written to receipts."""

    def __init__(self):
        self.accounts = {}
        self.posts = self.cancels = self.committed_claims = 0
        self.on_submit = None
        self.error_type = None
        self.uncertain_next = False
        self.stale_quote = False
        self.eligible = True

    def add_account(self, key_id: str, private_key) -> None:
        require(key_id.startswith("synthetic-perps-owner-"), "fixture_identity_required")
        self.accounts[key_id] = {"public_key": private_key.public_key().public_numbers(), "orders": {},
                                 "fills": [], "position": Decimal(0)}

    def client(self, credentials, environment="production", proxy_url=None):
        require(environment == "production" and proxy_url is None, "fixture_environment_mismatch")
        require(isinstance(credentials, tuple) and len(credentials) == 2, "fixture_credentials_missing")
        key_id, key = credentials
        require(key_id in self.accounts and hasattr(key, "public_key")
                and key.public_key().public_numbers() == self.accounts[key_id]["public_key"],
                "fixture_credentials_mismatch")
        fixture, state = self, self.accounts[key_id]

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def enabled_status(self):
                return stamp(enabled=fixture.eligible)

            def exchange_status(self):
                return stamp(exchange_active=True, trading_active=True)

            def market(self, ticker=None):
                require(ticker in (None, TICKER), "fixture_market_mismatch")
                return instrument()

            def orderbook(self, ticker):
                require(ticker == TICKER, "fixture_market_mismatch")
                result = stamp(orderbook={"bids": [["8.00", "5000.00"]], "asks": [["8.01", "5000.00"]]})
                if fixture.stale_quote:
                    result["retrieved_at"] = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
                return result

            def balance(self):
                return stamp(available_balance_computed=True, settled_funds="100",
                             subaccount_balances=[{"subaccount": 0, "account_equity": "100",
                                 "available_balance": "80", "initial_margin": "20", "maintenance_margin": "10"}])

            def risk(self):
                return stamp(account_leverage="25", total_position_notional="2500")

            def fee_tiers(self):
                return stamp(taker_fee_rates={TICKER: "0.0002"}, maker_fee_rates={TICKER: "0"})

            def positions(self, ticker=None):
                require(ticker in (None, TICKER), "fixture_market_mismatch")
                return stamp(positions=[{"market_ticker": TICKER, "subaccount": 0, "position": str(state["position"])}])

            def orders(self, ticker=None, min_ts=None):
                require(ticker in (None, TICKER), "fixture_market_mismatch")
                return stamp(orders=copy.deepcopy(list(state["orders"].values())), complete=True, cursor="")

            def fills(self, min_ts):
                return stamp(fills=copy.deepcopy(state["fills"]), complete=True, cursor="")

            def order(self, order_id):
                require(order_id in state["orders"], "fixture_order_missing")
                return stamp(order=copy.deepcopy(state["orders"][order_id]))

            def submit_order(self, body):
                # This callback observes a second, independent real DB connection.
                # Failure here occurs before even the synthetic POST counter moves.
                require(callable(fixture.on_submit), "commit_assertion_missing")
                fixture.on_submit(key_id, body)
                fixture.committed_claims += 1
                fixture.posts += 1
                order_id = "synthetic-native-order-%d" % fixture.posts
                count, price = Decimal(body["count"]), Decimal(body["price"])
                native = {"order_id": order_id, "client_order_id": body["client_order_id"],
                          "ticker": body["ticker"], "side": body["side"], "price": body["price"],
                          "fill_count": body["count"], "remaining_count": "0.00", "subaccount": 0}
                state["orders"][order_id] = native
                state["fills"].append({"fill_id": "synthetic-fill-%d" % fixture.posts,
                    "order_id": order_id, "ticker": body["ticker"], "side": body["side"],
                    "count": body["count"], "price": body["price"], "subaccount": 0,
                    "fees": str(count * price * Decimal("0.0002"))})
                state["position"] += count if body["side"] == "bid" else -count
                if fixture.uncertain_next:
                    fixture.uncertain_next = False
                    raise fixture.error_type("provider_unavailable", "Synthetic uncertain response.", uncertain=True)
                return stamp(**copy.deepcopy(native), average_fill_price=body["price"],
                             average_fee_paid=str(price * Decimal("0.0002")),
                             acknowledged_fee_total=str(count * price * Decimal("0.0002")))

            def cancel_order(self, order_id):
                fixture.cancels += 1
                require(order_id in state["orders"], "fixture_order_missing")
                return stamp(order_id=order_id, reduced_by="0.00")

        return Client()


class StagingRepository:
    """Harness-only assertions; business writes still use application repositories."""

    @staticmethod
    def assert_disposable_database(conn) -> None:
        with conn.cursor() as cur:
            cur.execute("SELECT DATABASE() AS db, SUBSTRING_INDEX(CURRENT_USER(),'@',1) AS db_user")
            row = cur.fetchone()
            require(row["db"] == guards.DATABASE and row["db_user"] == guards.DATABASE_USER,
                    "connected_database_mismatch")
            # The existing Alpaca verifier runs first. Its users/orders remain,
            # but this flow must begin with no keys, perps policies or perps orders.
            cur.execute("""SELECT (SELECT COUNT(*) FROM app_kalshi_keys) AS keys_n,
                (SELECT COUNT(*) FROM app_kalshi_dev_keys) AS demo_keys_n,
                (SELECT COUNT(*) FROM app_kalshi_perps_settings) AS settings_n,
                (SELECT COUNT(*) FROM app_kalshi_perps_orders) AS orders_n,
                (SELECT COUNT(*) FROM app_agent_runs WHERE status IN ('queued','running','paused')) AS active_runs,
                (SELECT COUNT(*) FROM app_deployments WHERE status='running') AS active_deployments,
                (SELECT COUNT(*) FROM app_users WHERE email NOT IN ('paper-owner-one@tau.test','paper-owner-two@tau.test')) AS other_users""")
            require(all(int(value) == 0 for value in cur.fetchone().values()), "perps_database_not_disposable")

    @staticmethod
    def assert_full_ddl(conn) -> None:
        with conn.cursor() as cur:
            cur.execute("""SELECT COLUMN_NAME AS name, DATA_TYPE AS kind, NUMERIC_PRECISION AS precision_n,
                NUMERIC_SCALE AS scale_n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_kalshi_perps_orders'
                AND COLUMN_NAME IN ('notional_usd','reserved_usd','filled_count','remaining_count','filled_notional_usd','fees_paid_usd')""")
            rows = cur.fetchall()
            require(len(rows) == 6 and all(row["kind"] == "decimal" and int(row["precision_n"]) == 38
                    and int(row["scale_n"]) == 18 for row in rows), "perps_decimal_schema_invalid")
            cur.execute("""SELECT INDEX_NAME AS name, COLUMN_NAME AS column_name, NON_UNIQUE AS non_unique
                FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
                AND TABLE_NAME='app_kalshi_perps_orders' ORDER BY INDEX_NAME, SEQ_IN_INDEX""")
            indices = {}
            for row in cur.fetchall():
                if int(row["non_unique"]) == 0:
                    indices.setdefault(row["name"], []).append(row["column_name"])
            require(["user_id", "environment", "client_token"] in indices.values()
                    and ["environment", "client_order_id"] in indices.values(), "perps_unique_schema_invalid")

    @staticmethod
    def assert_committed_claim(conn, key_id: str, body: dict, owners: dict) -> None:
        with conn.cursor() as cur:
            cur.execute("""SELECT user_id,status,approved_by_user_id,approved_at,claimed_at,request_json,
                proposal_id FROM app_kalshi_perps_orders WHERE environment='production' AND client_order_id=%s""",
                (body["client_order_id"],))
            row = cur.fetchone()
            require(row is not None and row["status"] == "claimed" and row["approved_at"] is not None
                    and row["claimed_at"] is not None and row["user_id"] == owners[key_id]
                    and row["approved_by_user_id"] == owners[key_id], "submission_claim_not_committed")
            saved = row["request_json"]
            require((json.loads(saved) if isinstance(saved, (str, bytes)) else saved) == body,
                    "submission_body_changed_after_confirmation")
            if row["proposal_id"] is not None:
                cur.execute("SELECT status FROM app_proposals WHERE id=%s", (row["proposal_id"],))
                require(cur.fetchone()["status"] == "applied", "proposal_claim_not_committed")

    @staticmethod
    def final_counts(conn) -> dict:
        with conn.cursor() as cur:
            cur.execute("""SELECT (SELECT COUNT(*) FROM app_users) AS fixture_users,
                (SELECT COUNT(*) FROM app_kalshi_perps_orders) AS perps_order_rows,
                (SELECT COUNT(*) FROM app_kalshi_perps_orders WHERE claimed_at IS NOT NULL) AS claimed_orders,
                (SELECT COUNT(*) FROM app_kalshi_perps_orders WHERE environment<>'production') AS wrong_environment_orders,
                (SELECT COUNT(*) FROM app_agent_runs WHERE status IN ('queued','running','paused')) AS active_runs,
                (SELECT COUNT(*) FROM app_deployments WHERE status='running') AS active_deployments""")
            return {key: int(value) for key, value in cur.fetchone().items()}


def confirmation(row: dict, **changes) -> dict:
    return {"confirmed": True, "expected_version": row["version"], "request_hash": row["request_hash"], **changes}


def run_acceptance() -> dict:
    guards.stage("application_import")
    import requests
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from pymysql.err import IntegrityError
    from app import agent, kalshi_account as account, kalshi_perps_trading as trading
    from app import kalshi_perps_orders_repository as store, repository as repo, server
    from data_pipeline.common import get_db_conn

    require(server.DEV_LOGIN and not server.SECURE_COOKIES and server.HOST == "127.0.0.1"
            and trading.enabled() and trading.environment() == "production", "imported_server_not_isolated")
    checks = guards._CHECKS
    passed = lambda name: checks.append({"name": name, "passed": True})
    fixture = SyntheticBroker()
    fixture.error_type = trading.broker.Error
    guards.stage("disposable_database_and_full_schema")
    conn = get_db_conn()
    try:
        StagingRepository.assert_disposable_database(conn)
        passed("disposable_database_without_active_jobs")
        StagingRepository.assert_full_ddl(conn)
        passed("full_schema_decimal_and_unique_constraints")
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    except BaseException:
        conn.close()
        raise
    http.daemon_threads = True
    _HTTP_PORTS.add(http.server_port)
    thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    base = "http://127.0.0.1:" + str(http.server_port)
    os.environ["APP_PUBLIC_URL"] = base
    sessions, owners = [], {}

    def call(session, method, path, body=None, *, expected=200, csrf=True):
        headers = {"X-Recursive": "1"} if method == "POST" and csrf else {}
        response = session.request(method, base + path, headers=headers, json=body, timeout=10, allow_redirects=True)
        if response.status_code != expected:
            guards._HTTP_FAILURE.update(expected=expected, observed=response.status_code)
        require(response.status_code == expected, "http_status_unexpected")
        return response

    def commit_assertion(key_id, body):
        independent = get_db_conn()
        try:
            require(independent.get_autocommit(), "independent_observer_not_autocommit")
            StagingRepository.assert_committed_claim(independent, key_id, body, owners)
        finally:
            independent.close()

    fixture.on_submit = commit_assertion
    try:
        with patch.object(trading.broker, "Client", fixture.client):
            thread.start()
            for _ in range(3):
                session = requests.Session()
                session.trust_env = False
                sessions.append(session)
            first, second, anonymous = sessions
            guards.stage("authentication_required")
            call(anonymous, "GET", PREFIX, expected=401)
            call(anonymous, "POST", PREFIX + "/orders", {}, expected=401)
            passed("authentication_required")
            guards.stage("real_owner_sessions_and_csrf")
            users = []
            for session, email in ((first, "perps-owner-one@tau.test"), (second, "perps-owner-two@tau.test")):
                call(session, "GET", "/auth/dev?email=" + email)
                me = call(session, "GET", "/api/me").json()
                require(not me["user"]["autopilot"] and not me["user"]["autopilot_live"]
                        and not me["live_trading_available"], "binary_live_defaults_changed")
                users.append(me["user"]["id"])
            require(users[0] != users[1], "fixture_owner_collision")
            call(first, "POST", PREFIX + "/policy", {}, csrf=False, expected=403)
            passed("real_owner_sessions_and_csrf")
            guards.stage("encrypted_per_user_synthetic_keys")
            balances, key_rows = [], []
            for index, uid in enumerate(users):
                key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()).decode()
                key_id = "synthetic-perps-owner-%d" % index
                fixture.add_account(key_id, key)
                owners[key_id] = uid
                encrypted = account.encrypt_private_key(uid, pem)
                require(pem.encode() not in encrypted, "synthetic_key_not_encrypted")
                with repo.transaction(conn) as cur:
                    repo.save_kalshi_key(cur, uid, key_id, encrypted)
                    key_rows.append(repo.get_kalshi_key(cur, uid))
                    balances.append(repo.paper_balance(cur, uid))
            try:
                account.credentials_from_row(users[1], key_rows[0])
            except Exception:
                pass
            else:
                raise SmokeError("synthetic_key_not_owner_bound")
            passed("encrypted_per_user_synthetic_keys")
            guards.stage("explicit_real_money_opt_in")
            payload = {"request_key": "perps-staging-first", "side": "bid", "count": "1000", "price": "8.0100", "reduce_only": False}
            overview = call(first, "GET", PREFIX).json()
            require(overview["eligible"] and overview["connected"] and not overview["policy"]["enabled"]
                    and overview["policy"]["manual_confirmation_required"]
                    and overview["policy"]["risk_mode"] == "kalshi_limits", "manual_policy_default_invalid")
            call(first, "POST", PREFIX + "/orders", payload, expected=409)
            call(first, "POST", PREFIX + "/policy", {"enabled": True, "expected_version": 0}, expected=400)
            for session in (first, second):
                policy = call(session, "POST", PREFIX + "/policy", {"enabled": True,
                    "acknowledge_real_money": True, "expected_version": 0}).json()["policy"]
                require(policy["enabled"] and policy["manual_confirmation_required"]
                        and policy["risk_mode"] == "kalshi_limits", "manual_opt_in_invalid")
            require(fixture.posts == 0, "opt_in_submitted_order")
            passed("explicit_real_money_opt_in_without_submission")
            guards.stage("preview_native_math_and_idempotency")
            draft = call(first, "POST", PREFIX + "/orders", payload).json()["order"]
            replay = call(first, "POST", PREFIX + "/orders", payload).json()["order"]
            preview = draft["preview"]
            require(draft["status"] == "draft" and draft["id"] == replay["id"] and fixture.posts == 0
                    and Decimal(preview["notional_usd"]) == Decimal("8010")
                    and Decimal(preview["btc_quantity"]) == Decimal("0.1")
                    and Decimal(preview["estimated_fee_usd"]) == Decimal("1.602")
                    and Decimal(preview["account_equity"]) == Decimal("100")
                    and Decimal(preview["account_leverage"]) == Decimal("25"), "native_preview_math_invalid")
            call(first, "POST", PREFIX + "/orders", {**payload, "price": "8.02"}, expected=409)
            passed("preview_no_post_native_usd_math_and_idempotency")
            guards.stage("owner_isolation_and_exact_confirmation")
            other = call(second, "POST", PREFIX + "/orders", payload).json()["order"]
            require(other["id"] != draft["id"], "draft_key_not_owner_scoped")
            for suffix in ("submit", "refresh", "cancel"):
                call(second, "POST", PREFIX + "/orders/%d/%s" % (draft["id"], suffix), confirmation(draft), expected=404)
            own_overview = call(second, "GET", PREFIX).json()
            require(all(row["id"] != draft["id"] for row in own_overview["orders"]), "overview_order_owner_leak")
            for altered in ({"confirmed": False}, {"expected_version": draft["version"] + 1}, {"request_hash": "0" * 64}):
                call(first, "POST", PREFIX + "/orders/%d/submit" % draft["id"], confirmation(draft, **altered), expected=409)
            require(fixture.posts == 0, "invalid_confirmation_submitted")
            passed("owner_isolation_and_exact_confirmation")
            guards.stage("committed_claim_before_single_post")
            filled = call(first, "POST", PREFIX + "/orders/%d/submit" % draft["id"], confirmation(draft)).json()["order"]
            require(filled["status"] == "filled" and fixture.posts == fixture.committed_claims == 1
                    and Decimal(filled["filled_count"]) == Decimal("1000")
                    and Decimal(filled["filled_avg_price"]) == Decimal("8.01")
                    and Decimal(filled["total_fees"]) == Decimal("1.602"), "native_fill_ledger_invalid")
            with conn.cursor() as cur:
                saved = store.get_order(cur, users[0], "production", draft["id"])
            require(Decimal(saved["filled_notional_usd"]) == Decimal("8010"), "native_notional_multiplied_twice")
            passed("committed_owner_claim_before_synthetic_post")
            guards.stage("duplicate_confirmation_never_resubmits")
            duplicate = call(first, "POST", PREFIX + "/orders/%d/submit" % draft["id"], confirmation(draft)).json()["order"]
            require(duplicate["status"] == "filled" and fixture.posts == 1, "duplicate_confirmation_resubmitted")
            passed("duplicate_confirmation_never_resubmits")
            guards.stage("unknown_submission_no_retry")
            uncertain = call(first, "POST", PREFIX + "/orders", {**payload, "request_key": "perps-staging-unknown", "count": "1"}).json()["order"]
            fixture.uncertain_next = True
            unknown = call(first, "POST", PREFIX + "/orders/%d/submit" % uncertain["id"], confirmation(uncertain)).json()["order"]
            require(unknown["status"] == "unknown" and fixture.posts == 2, "uncertain_submission_not_retained")
            call(first, "POST", PREFIX + "/orders/%d/submit" % uncertain["id"], confirmation(uncertain))
            call(first, "POST", PREFIX + "/orders", {**payload, "request_key": "perps-staging-blocked"}, expected=409)
            require(fixture.posts == 2, "uncertain_submission_retried")
            reconciled = call(first, "POST", PREFIX + "/orders/%d/refresh" % uncertain["id"], {}).json()["order"]
            require(reconciled["status"] == "filled" and fixture.posts == 2, "read_only_reconciliation_failed")
            passed("unknown_submission_no_retry_and_get_only_reconciliation")
            guards.stage("agent_proposal_review_only")
            with repo.transaction(conn) as cur:
                _, proposal_id = agent.act(cur, {"id": users[0]}, {"type": "kalshi_perps_order", "side": "bid", "count": "2",
                    "price": "8.01", "reduce_only": False, "reason": "Synthetic manual confirmation acceptance."}, autopilot=True)
            require(type(proposal_id) is int and proposal_id > 0 and fixture.posts == 2, "agent_proposal_submitted")
            review = call(first, "POST", "/api/proposals/%d/approve" % proposal_id, {}).json()
            require(review["review_required"] is True and fixture.posts == 2, "proposal_approval_submitted")
            with conn.cursor() as cur:
                require(repo.get_proposal(cur, users[0], proposal_id)["status"] == "pending", "proposal_review_marked_applied")
            call(second, "POST", PREFIX + "/proposals/%d/preview" % proposal_id,
                 {"request_key": "perps-other-proposal"}, expected=404)
            call(first, "POST", PREFIX + "/proposals/%d/preview" % proposal_id,
                 {"request_key": "perps-staging-proposal", "price": "7"}, expected=400)
            proposed = call(first, "POST", PREFIX + "/proposals/%d/preview" % proposal_id,
                            {"request_key": "perps-staging-proposal"}).json()["order"]
            require(proposed["source"] == "agent" and proposed["status"] == "draft" and fixture.posts == 2,
                    "proposal_preview_submitted")
            passed("agent_proposal_review_and_preview_only")
            guards.stage("proposal_exact_manual_confirmation")
            call(first, "POST", PREFIX + "/orders/%d/submit" % proposed["id"], confirmation(proposed, request_hash="f" * 64), expected=409)
            proposal_filled = call(first, "POST", PREFIX + "/orders/%d/submit" % proposed["id"], confirmation(proposed)).json()["order"]
            require(proposal_filled["status"] == "filled" and fixture.posts == 3 and fixture.committed_claims == 3,
                    "proposal_exact_confirmation_failed")
            with conn.cursor() as cur:
                require(repo.get_proposal(cur, users[0], proposal_id)["status"] == "applied", "proposal_not_applied_after_claim")
            call(first, "POST", PREFIX + "/orders/%d/submit" % proposed["id"], confirmation(proposed))
            require(fixture.posts == 3, "proposal_duplicate_resubmitted")
            passed("proposal_exact_confirmation_and_committed_application")
            guards.stage("cancel_draft_without_broker_post")
            canceled = call(second, "POST", PREFIX + "/orders/%d/cancel" % other["id"], confirmation(other)).json()["order"]
            require(canceled["status"] == "canceled" and fixture.cancels == 0 and fixture.posts == 3,
                    "draft_cancel_contacted_broker")
            passed("cancel_draft_without_broker_post")
            guards.stage("stale_or_ineligible_state_fails_closed")
            fixture.stale_quote = True
            call(first, "POST", PREFIX + "/orders", {**payload, "request_key": "perps-staging-stale"}, expected=409)
            fixture.stale_quote = False
            fixture.eligible = False
            call(first, "POST", PREFIX + "/orders", {**payload, "request_key": "perps-staging-ineligible"}, expected=409)
            fixture.eligible = True
            require(fixture.posts == 3, "failed_preflight_submitted")
            passed("stale_or_ineligible_state_fails_closed")
            guards.stage("database_rollback_preserves_manual_policy")
            with conn.cursor() as cur:
                before = store.get_settings(cur, users[0], "production")
            try:
                with repo.transaction(conn) as cur:
                    store.save_settings(cur, users[0], "production", enabled=False, expected_version=before["version"])
                    raise SmokeError("synthetic_rollback")
            except SmokeError:
                pass
            with conn.cursor() as cur:
                after = store.get_settings(cur, users[0], "production")
            require(after == before, "perps_policy_transaction_not_rolled_back")
            passed("real_database_policy_rollback")
            guards.stage("native_client_identity_unique_constraint")
            try:
                with repo.transaction(conn) as cur, patch.object(store.uuid, "uuid4", return_value=uuid.UUID(draft["client_order_id"])):
                    store.insert_draft(cur, users[0], "production", "perps-staging-duplicate-id",
                        saved["key_revision_hash"], {key: value for key, value in saved["request"].items() if key != "client_order_id"},
                        instrument=instrument(), preview=saved["preview"])
            except IntegrityError as exc:
                require(exc.args and exc.args[0] == 1062, "unexpected_unique_constraint_error")
            else:
                raise SmokeError("native_client_identity_not_unique")
            passed("real_database_native_identity_unique_constraint")
            guards.stage("per_user_opt_out_prevents_new_order")
            policy = call(first, "GET", PREFIX).json()["policy"]
            call(first, "POST", PREFIX + "/policy", {"enabled": False, "expected_version": policy["version"]})
            call(first, "POST", PREFIX + "/orders", {**payload, "request_key": "perps-staging-disabled"}, expected=409)
            require(fixture.posts == 3, "opt_out_submitted_order")
            passed("per_user_opt_out_prevents_new_order")
            guards.stage("no_jobs_binary_money_or_environment_changes")
            counts = StagingRepository.final_counts(conn)
            require(counts["active_runs"] == counts["active_deployments"] == counts["wrong_environment_orders"] == 0
                    and counts["claimed_orders"] == fixture.posts == fixture.committed_claims == 3, "unexpected_active_work_or_claim_count")
            with conn.cursor() as cur:
                require(all(repo.paper_balance(cur, uid) == balance for uid, balance in zip(users, balances)),
                        "binary_paper_ledger_changed")
            passed("no_active_jobs_or_binary_paper_ledger_changes")
            return {"status": "passed", "mode": MODE, "checks": list(checks),
                    "counts": {**counts, "synthetic_submissions": fixture.posts, "synthetic_cancellations": fixture.cancels,
                               "independent_committed_claims": fixture.committed_claims},
                    "real_provider_calls": 0, "real_kalshi_keys_used": False, "real_order_acceptance_tested": False,
                    "manual_confirmation_required": True, "production_changed": False,
                    "verification_http_loopback_only": True, "synthetic_client_only": True}
    finally:
        if thread.is_alive():
            http.shutdown()
        http.server_close()
        if thread.is_alive():
            thread.join(timeout=5)
        _HTTP_PORTS.discard(http.server_port)
        for session in sessions:
            session.close()
        conn.close()


def main() -> int:
    guards._CHECKS.clear()
    guards._HTTP_FAILURE.clear()
    guards.stage("isolation_environment")
    try:
        root = Path.cwd()
        validate_environment(dict(os.environ), root)
        require(not any(name == "app" or name.startswith("app.") for name in sys.modules), "app_imported_before_guard")
        require((root / "app/server.py").is_file(), "application_source_missing")
        sys.path.insert(0, str(root))
        with contextlib.redirect_stdout(guards.NullLog()), contextlib.redirect_stderr(guards.NullLog()), \
                guards.isolated_network(os.environ["MYSQL_HOST"], int(os.environ.get("MYSQL_PORT", "3306")), _HTTP_PORTS):
            result = run_acceptance()
    except Exception as exc:
        result = failure_result(exc)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
