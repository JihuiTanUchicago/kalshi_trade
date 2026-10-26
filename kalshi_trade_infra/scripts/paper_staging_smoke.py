"""One-shot disposable-MySQL/real-HTTP acceptance with a synthetic paper broker.

Run from kalshi_trade_infra after app.schema, in a clean allowlisted environment.
This is test infrastructure: it does not exercise real OAuth, market data,
Alpaca's exchange, a model worker or production. Never use a production database.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
from http.server import ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import threading
from unittest.mock import patch
from urllib.parse import urlsplit
import uuid


DATABASE = "tau_paper_staging"
DATABASE_USER = "tau_stage"
FIXTURE_OAUTH = {"ALPACA_OAUTH_CLIENT_ID": "synthetic-staging-client",
                 "ALPACA_OAUTH_CLIENT_SECRET": "synthetic-staging-secret"}
FIXED_FLAGS = {
    "TAU_STAGING_DISPOSABLE_DB": "1", "APP_DEV_LOGIN": "1", "APP_HOST": "127.0.0.1",
    "APP_INSECURE_COOKIES": "1", "TAU_DISABLE_CATALOG_MARKETS": "1",
    "TAU_ALPACA_PAPER_ENABLED": "1", "TAU_ALPACA_PAPER_MAX_ORDER_USD": "500",
    "APP_LIVE_TRADING_ENABLED": "0", "APP_NO_SIDE_LIVE_ENABLED": "0",
}
DISABLED_FLAGS = ("TAU_ALPACA_ENABLED", "TAU_MASSIVE_ENABLED", "TAU_DATABENTO_ENABLED",
                  "TAU_EXA_ENABLED", "TAU_EXA_HISTORICAL_ENABLED", "TAU_WORLDMONITOR_ENABLED")
FORBIDDEN_KEYS = (
    "APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
    "MASSIVE_API_KEY", "DATABENTO_API_KEY", "EXA_API_KEY", "WORLDMONITOR_API_KEY",
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET",
    "PROD_KEYID", "PROD_KEYFILE", "KALSHI_WS_KEY_ID", "KALSHI_WS_PRIVATE_KEY_PATH",
    "KALSHI_API_KEY", "KALSHI_API_SECRET", "IBKR_OAUTH_CONSUMER_KEY", "ROBINHOOD_CLIENT_ID",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "BASH_ENV", "ENV", "ENV_FILE", "DOTENV_PATH",
)
_STAGE = "isolation_environment"
_CHECKS: list[dict] = []
_HTTP_FAILURE: dict[str, int] = {}


class SmokeError(RuntimeError):
    """Only a fixed machine-readable check code leaves this harness."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SmokeError(code)


def stage(name: str) -> None:
    global _STAGE
    _STAGE = name  # Call sites use fixed names; no external input reaches this.


def failure_result(exc: Exception) -> dict:
    name = type(exc).__name__
    safe_name = name if name.isascii() and name.replace("_", "").isalnum() and len(name) <= 64 else "Exception"
    code = str(exc) if isinstance(exc, SmokeError) else "unexpected_acceptance_failure"
    if not code.isascii() or not code.replace("_", "").isalnum() or len(code) > 80:
        code = "unexpected_acceptance_failure"
    result = {"status": "failed", "mode": "synthetic_broker_real_mysql_http", "error_code": code,
              "stage": _STAGE, "exception_class": safe_name,
              "last_completed_check": _CHECKS[-1]["name"] if _CHECKS else None,
              "passed_check_count": len(_CHECKS)}
    if type(exc).__module__.startswith("pymysql") and exc.args and type(exc.args[0]) is int:
        result["mysql_error_code"] = exc.args[0]
    if _HTTP_FAILURE:
        result["http_status"] = dict(_HTTP_FAILURE)
    return result


def validate_environment(env: dict, source_root: Path, *, path_exists=None) -> None:
    """Run before importing any app module or opening a connection."""
    exists = (lambda path: path.exists() or path.is_symlink()) if path_exists is None else path_exists
    require(all(env.get(key) == value for key, value in FIXED_FLAGS.items()), "isolation_flags_invalid")
    require(env.get("MYSQL_HOST") in ("127.0.0.1", "localhost", "db"), "database_host_not_isolated")
    require(env.get("MYSQL_DATABASE") == DATABASE and env.get("MYSQL_USER") == DATABASE_USER,
            "database_identity_not_isolated")
    require(isinstance(env.get("MYSQL_PASSWORD"), str) and bool(env["MYSQL_PASSWORD"]), "database_password_missing")
    require(str(env.get("MYSQL_PORT", "3306")).isdigit()
            and 1 <= int(env.get("MYSQL_PORT", "3306")) <= 65535, "database_port_invalid")
    require(all(env.get(key, "0") == "0" for key in DISABLED_FLAGS), "provider_flag_enabled")
    require(not any(env.get(key) for key in FORBIDDEN_KEYS), "external_credentials_forbidden")
    require(all(not env.get(key) or env[key] == value for key, value in FIXTURE_OAUTH.items()),
            "real_oauth_credentials_forbidden")
    require(env.get("AWS_EC2_METADATA_DISABLED") == "true"
            and env.get("AWS_SHARED_CREDENTIALS_FILE") == "/dev/null"
            and env.get("AWS_CONFIG_FILE") == "/dev/null", "aws_fallback_not_disabled")
    try:
        origin_text = env.get("APP_PUBLIC_URL", "")
        origin = urlsplit(origin_text)
        local_origin = (origin.scheme == "http" and origin.hostname in ("127.0.0.1", "localhost")
                        and not origin.username and not origin.password and origin.path in ("", "/")
                        and not origin.query and not origin.fragment
                        and all(33 <= ord(char) <= 126 for char in origin_text)
                        and (origin.port is None or 1 <= origin.port <= 65535))
    except ValueError:
        local_origin = False
    require(local_origin, "public_origin_not_loopback")
    try:
        raw_key = env.get("APP_SECRET_KEY", "")
        key = base64.b64decode(raw_key + "=" * (-len(raw_key) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        key = b""
    require(len(key) == 32, "disposable_vault_key_invalid")
    root = source_root.resolve()
    require(root != Path("/opt/kalshi") and Path("/opt/kalshi") not in root.parents,
            "production_source_root_forbidden")
    require((root / "app").resolve().parent == root, "application_path_escapes_checkout")
    private_paths = [root / name for name in (".env", ".env.app", ".env.aws", ".env.staging")]
    private_paths += [root.parent / name for name in (".env", ".env.app", ".env.aws")]
    private_paths += [Path("/opt/kalshi") / name for name in (".env", ".env.app", ".env.aws")]
    private_paths += [Path("/etc/tau/provider-data"), Path("/etc/tau/alpaca-paper")]
    require(not any(exists(path) for path in private_paths), "private_production_files_present")


class NullLog:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


@contextlib.contextmanager
def isolated_network(db_host: str, db_port: int, http_ports: set[int]):
    """Permit only the chosen DB and this harness's loopback HTTP server."""
    original_lookup = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    db_ips = {item[4][0] for item in original_lookup(db_host, db_port, type=socket.SOCK_STREAM)}
    require(bool(db_ips) and all(ipaddress.ip_address(value).is_private for value in db_ips),
            "database_address_not_private")

    def allowed(address):
        if not isinstance(address, tuple) or len(address) < 2:
            return False
        host, port = address[:2]
        return ((host in db_ips and port == db_port)
                or (host in ("127.0.0.1", "::1") and port in http_ports))

    def lookup(host, port, *args, **kwargs):
        require(host in (db_host, "127.0.0.1", "localhost", "::1"), "external_dns_blocked")
        return original_lookup(host, port, *args, **kwargs)

    def connect(sock, address):
        require(allowed(address), "external_connection_blocked")
        return original_connect(sock, address)

    def connect_ex(sock, address):
        require(allowed(address), "external_connection_blocked")
        return original_connect_ex(sock, address)

    with patch.object(socket, "getaddrinfo", lookup), patch.object(socket.socket, "connect", connect), \
            patch.object(socket.socket, "connect_ex", connect_ex):
        yield


class StagingRepository:
    """Harness-only database assertions; all business writes use app repositories."""

    @staticmethod
    def assert_fresh_database(conn) -> None:
        with conn.cursor() as cur:
            cur.execute("SELECT DATABASE() AS db, SUBSTRING_INDEX(CURRENT_USER(),'@',1) AS db_user")
            row = cur.fetchone()
            require(row["db"] == DATABASE and row["db_user"] == DATABASE_USER, "connected_database_mismatch")
            cur.execute("""SELECT
                (SELECT COUNT(*) FROM app_users) AS users,
                (SELECT COUNT(*) FROM app_sessions) AS sessions,
                (SELECT COUNT(*) FROM app_agent_runs) AS runs,
                (SELECT COUNT(*) FROM app_broker_connections) AS connections,
                (SELECT COUNT(*) FROM app_alpaca_paper_orders) AS orders,
                (SELECT COUNT(*) FROM app_deployments) AS deployments""")
            require(all(int(value) == 0 for value in cur.fetchone().values()), "database_not_fresh")

    @staticmethod
    def assert_paper_ddl(conn) -> None:
        with conn.cursor() as cur:
            cur.execute("""SELECT COLUMN_NAME AS name, DATA_TYPE AS kind, NUMERIC_PRECISION AS precision_n,
                           NUMERIC_SCALE AS scale_n FROM information_schema.COLUMNS
                           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_alpaca_paper_orders'
                           AND COLUMN_NAME IN ('filled_qty','filled_avg_price')""")
            columns = cur.fetchall()
            require(len(columns) == 2 and all(row["kind"] == "decimal" and int(row["precision_n"]) == 20
                    and int(row["scale_n"]) == 8 for row in columns), "paper_decimal_schema_invalid")
            cur.execute("""SELECT INDEX_NAME AS name, COLUMN_NAME AS column_name, NON_UNIQUE AS non_unique,
                           SEQ_IN_INDEX AS ordinal_n FROM information_schema.STATISTICS
                           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_alpaca_paper_orders'
                           ORDER BY INDEX_NAME, SEQ_IN_INDEX""")
            indices = {}
            for row in cur.fetchall():
                if int(row["non_unique"]) == 0:
                    indices.setdefault(row["name"], []).append(row["column_name"])
            require(["user_id", "request_key"] in indices.values()
                    and ["client_order_id"] in indices.values(), "paper_unique_schema_invalid")

    @staticmethod
    def final_counts(conn) -> dict:
        with conn.cursor() as cur:
            cur.execute("""SELECT
                (SELECT COUNT(*) FROM app_users) AS fixture_users,
                (SELECT COUNT(*) FROM app_alpaca_paper_orders) AS paper_order_rows,
                (SELECT COUNT(*) FROM app_agent_runs WHERE status IN ('queued','running','paused')) AS active_runs,
                (SELECT COUNT(*) FROM app_deployments WHERE status='running') AS active_deployments""")
            return {key: int(value) for key, value in cur.fetchone().items()}


class SyntheticBroker:
    """Explicit fixture; neither simulates provider freshness nor accepts real tokens."""

    def __init__(self):
        self.accounts = {}
        self.posts = 0
        self.cancels = 0
        self.timeout_next = False
        self.on_submit = None
        self.error_type = None

    def add_account(self, account_id: str) -> dict:
        token = "synthetic-staging-token-" + uuid.uuid4().hex
        self.accounts[token] = {"id": account_id, "orders": {}}
        return {"access_token": token, "account_id": account_id, "scope": "data trading", "token_type": "Bearer"}

    def client(self, credentials: dict):
        owner = self.accounts.get(credentials.get("access_token"))
        require(owner is not None and owner["id"] == credentials.get("account_id"), "synthetic_grant_mismatch")
        world = self

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def account(self):
                return {"id": owner["id"], "status": "ACTIVE", "currency": "USD",
                        "trading_blocked": False, "account_blocked": False,
                        "cash": "10000", "buying_power": "10000", "equity": "10000", "portfolio_value": "10000"}

            def positions(self):
                return []

            def asset(self, symbol):
                return {"symbol": symbol, "class": "us_equity", "status": "active", "tradable": True}

            def orders(self, status="open", limit=500):
                rows = list(owner["orders"].values())
                if status == "open":
                    rows = [row for row in rows if row["status"] not in ("filled", "canceled", "rejected", "expired")]
                return copy.deepcopy(rows[:limit])

            def submit_order(self, request):
                if world.on_submit:
                    world.on_submit(request)
                require(request["client_order_id"] not in owner["orders"], "synthetic_duplicate_post")
                world.posts += 1
                row = {**copy.deepcopy(request), "id": str(uuid.uuid4()), "status": "new",
                       "filled_qty": "0", "filled_avg_price": None, "order_class": "simple"}
                owner["orders"][request["client_order_id"]] = row
                if world.timeout_next:
                    world.timeout_next = False
                    raise world.error_type("Synthetic accepted request timed out.", 502, ambiguous=True)
                return copy.deepcopy(row)

            def get_order(self, client_order_id):
                return copy.deepcopy(owner["orders"].get(client_order_id))

            def cancel_order(self, broker_order_id):
                row = next((row for row in owner["orders"].values() if row["id"] == broker_order_id), None)
                require(row is not None, "synthetic_cancel_missing")
                world.cancels += 1
                row["status"] = "canceled"

        return Client()

    def fill(self, client_order_id: str) -> None:
        for account in self.accounts.values():
            if client_order_id in account["orders"]:
                row = account["orders"][client_order_id]
                row.update(status="filled", filled_qty=row["qty"], filled_avg_price=row["limit_price"])
                return
        raise SmokeError("synthetic_fill_missing")


def run_acceptance() -> dict:
    """Actual imports/DB/HTTP occur only here, after main's isolation guard."""
    stage("application_import")
    import requests
    from pymysql.err import IntegrityError
    from app.adapters.alpaca import alpaca_paper as paper, alpaca_paper_repository as store
    from app import repository as repo, server
    from app.adapters.brokers import broker_repository as connections, broker_vault as vault
    from data_pipeline.common import get_db_conn

    require(server.DEV_LOGIN and not server.SECURE_COOKIES and server.HOST == "127.0.0.1", "imported_server_not_isolated")
    checks = _CHECKS
    passed = lambda name: checks.append({"name": name, "passed": True})
    fixture = SyntheticBroker()
    fixture.error_type = paper.broker.Error
    stage("fresh_disposable_database")
    conn = get_db_conn()
    try:
        StagingRepository.assert_fresh_database(conn)
        passed("fresh_disposable_database")
        stage("decimal_and_unique_ddl")
        StagingRepository.assert_paper_ddl(conn)
        passed("decimal_and_unique_ddl")
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    except BaseException:
        conn.close()
        raise
    http.daemon_threads = True
    ports = _HTTP_PORTS
    ports.add(http.server_port)
    thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    base = "http://127.0.0.1:" + str(http.server_port)
    os.environ["APP_PUBLIC_URL"] = base
    sessions = []

    def call(session, method, path, body=None, *, expected=200, csrf=True):
        headers = {"X-Recursive": "1"} if method == "POST" and csrf else {}
        response = session.request(method, base + path, headers=headers, json=body, timeout=10,
                                   allow_redirects=True)
        if response.status_code != expected:
            _HTTP_FAILURE.update(expected=expected, observed=response.status_code)
        require(response.status_code == expected, "http_status_unexpected")
        return response

    try:
        with patch.object(paper.broker, "Client", fixture.client):
            thread.start()
            for _ in range(3):
                session = requests.Session()
                session.trust_env = False
                sessions.append(session)
            first, second, anonymous = sessions
            stage("unauthenticated_requests_rejected")
            call(anonymous, "GET", "/api/brokers/alpaca/paper", expected=401)
            call(anonymous, "POST", "/api/brokers/alpaca/paper/orders", {}, expected=401)
            passed("unauthenticated_requests_rejected")
            stage("real_database_sessions_and_local_login")
            users = []
            for session, email in ((first, "paper-owner-one@tau.test"), (second, "paper-owner-two@tau.test")):
                call(session, "GET", "/auth/dev?email=" + email)
                me = call(session, "GET", "/api/me").json()
                require(not me["user"]["autopilot"] and not me["live_trading_available"], "user_defaults_not_isolated")
                users.append(me["user"]["id"])
            require(users[0] != users[1], "fixture_owner_collision")
            passed("real_database_sessions_and_local_login")
            stage("csrf_live_route_and_versioned_assets")
            call(first, "POST", "/api/brokers/alpaca/paper/orders", {}, csrf=False, expected=403)
            call(first, "POST", "/api/brokers/alpaca/live/orders", {}, expected=404)
            page = call(first, "GET", "/settings/account").text
            require("{{paper_" not in page and "/static/alpaca-paper.css?v=" in page
                    and page.index("/static/alpaca-paper.js?v=") < page.index("/static/broker-connections.js?v="),
                    "paper_assets_not_integrated")
            call(first, "GET", "/static/alpaca-paper.js")
            call(first, "GET", "/static/alpaca-paper.css")
            passed("csrf_live_route_and_versioned_assets")
            stage("encrypted_synthetic_grants_and_account_projection")
            balances = []
            for index, uid in enumerate(users):
                credentials = fixture.add_account("synthetic-paper-account-" + str(index))
                state = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
                session_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
                with repo.transaction(conn) as cur:
                    connections.save_attempt(cur, uid, "alpaca", "paper", state, session_hash,
                                             vault.encrypt(uid, "alpaca", "paper", "state", {"synthetic": True}))
                    require(connections.consume_attempt(cur, uid, "alpaca", state, session_hash) is not None,
                            "fixture_state_claim_failed")
                    require(connections.complete_attempt(cur, uid, "alpaca", "paper", state,
                            vault.encrypt(uid, "alpaca", "paper", "tokens", credentials),
                            {"scopes": ["data", "trading"], "account_label": "Synthetic paper fixture"}),
                            "fixture_grant_persistence_failed")
                    balances.append(repo.paper_balance(cur, uid))
            overview = call(first, "GET", "/api/brokers/alpaca/paper").json()
            require(overview["environment"] == "paper" and overview["connected"] and overview["trading_authorized"],
                    "synthetic_account_unavailable")
            passed("encrypted_synthetic_grants_and_account_projection")
            stage("draft_idempotency_conflicts_and_owner_separation")
            endpoint = "/api/brokers/alpaca/paper/orders"
            payload = {"request_key": "staging_order_one", "symbol": "SPY", "side": "buy", "qty": "1", "limit_price": "100"}
            draft = call(first, "POST", endpoint, payload).json()["order"]
            replay = call(first, "POST", endpoint, payload).json()["order"]
            require(draft["id"] == replay["id"] and draft["client_order_id"] == replay["client_order_id"]
                    and draft["status"] == "draft" and fixture.posts == 0, "draft_replay_not_durable")
            call(first, "POST", endpoint, {**payload, "limit_price": "101"}, expected=409)
            other = call(second, "POST", endpoint, payload).json()["order"]
            require(other["id"] != draft["id"], "request_key_not_owner_scoped")
            call(second, "POST", endpoint + "/%s/submit" % draft["id"], {}, expected=404)
            call(second, "POST", endpoint + "/%s/refresh" % draft["id"], {}, expected=404)
            passed("draft_idempotency_conflicts_and_owner_separation")
            stage("committed_claim_explicit_submit_and_cancellation")

            def assert_claim_committed(request):
                observer = get_db_conn()
                try:
                    rows = store.list_orders(observer.cursor(), users[0])
                    row = next((row for row in rows if row["client_order_id"] == request["client_order_id"]), None)
                    require(row is not None and row["status"] == "submitting", "claim_not_committed_before_broker")
                finally:
                    observer.close()

            fixture.on_submit = assert_claim_committed
            submitted = call(first, "POST", endpoint + "/%s/submit" % draft["id"], {}).json()["order"]
            require(submitted["status"] == "submitted" and submitted["filled_qty"] == "0" and fixture.posts == 1,
                    "submission_claim_failed")
            call(first, "POST", endpoint + "/%s/submit" % draft["id"], {})
            require(fixture.posts == 1, "repeat_submit_reached_broker")
            pending = call(first, "POST", endpoint + "/%s/cancel" % draft["id"], {}).json()["order"]
            require(pending["status"] == "cancel_pending", "cancel_acceptance_fabricated_terminal")
            canceled = call(first, "POST", endpoint + "/%s/refresh" % draft["id"], {}).json()["order"]
            require(canceled["status"] == "canceled" and fixture.cancels == 1, "cancel_reconciliation_failed")
            call(second, "POST", endpoint + "/%s/cancel" % other["id"], {})
            require(fixture.cancels == 1, "draft_cancel_reached_broker")
            passed("committed_claim_explicit_submit_and_cancellation")
            stage("observed_fill_reconciliation")
            filled = call(first, "POST", endpoint, {**payload, "request_key": "staging_order_fill"}).json()["order"]
            call(first, "POST", endpoint + "/%s/submit" % filled["id"], {})
            fixture.fill(filled["client_order_id"])
            result = call(first, "POST", endpoint + "/%s/refresh" % filled["id"], {}).json()["order"]
            require(result["broker_status"] == "filled" and result["filled_qty"] == "1"
                    and result["filled_avg_price"] == "100", "fill_reconciliation_failed")
            passed("observed_fill_reconciliation")
            stage("accepted_timeout_never_resubmitted")
            uncertain = call(first, "POST", endpoint, {**payload, "request_key": "staging_order_timeout"}).json()["order"]
            fixture.timeout_next = True
            unknown = call(first, "POST", endpoint + "/%s/submit" % uncertain["id"], {}).json()["order"]
            require(unknown["status"] == "unknown" and fixture.posts == 3, "uncertain_submit_not_preserved")
            call(first, "POST", endpoint + "/%s/submit" % uncertain["id"], {})
            require(fixture.posts == 3, "uncertain_submit_repeated")
            found = call(first, "POST", endpoint + "/%s/refresh" % uncertain["id"], {}).json()["order"]
            require(found["status"] == "submitted", "uncertain_lookup_not_reconciled")
            call(first, "POST", endpoint + "/%s/cancel" % uncertain["id"], {})
            call(first, "POST", endpoint + "/%s/refresh" % uncertain["id"], {})
            passed("accepted_timeout_never_resubmitted")
            stage("real_transaction_rollback")
            with repo.transaction(conn) as cur:
                base_row = store.get_order(cur, users[0], draft["id"])
            rolled_id = None
            try:
                with repo.transaction(conn) as cur:
                    request = {**base_row["request"], "client_order_id": "tau-paper-" + uuid.uuid4().hex}
                    rolled_id = store.insert_order(cur, users[0], "staging_rollback", base_row["connection_hash"], request)["id"]
                    raise SmokeError("synthetic_transaction_rollback")
            except SmokeError as exc:
                require(str(exc) == "synthetic_transaction_rollback", "rollback_setup_failed")
            require(rolled_id is not None and store.get_order(conn.cursor(), users[0], rolled_id) is None,
                    "transaction_rollback_failed")
            passed("real_transaction_rollback")
            stage("database_rejects_duplicate_broker_identity")
            duplicate_refused = False
            try:
                with repo.transaction(conn) as cur:
                    store.insert_order(cur, users[0], "staging_duplicate_identity", base_row["connection_hash"],
                                       base_row["request"])
            except IntegrityError as exc:
                duplicate_refused = bool(exc.args and exc.args[0] == 1062)
            require(duplicate_refused, "database_unique_identity_not_enforced")
            passed("database_rejects_duplicate_broker_identity")
            stage("independent_transactions_claim_exactly_once")
            with repo.transaction(conn) as cur:
                claim_request = {**base_row["request"], "client_order_id": "tau-paper-" + uuid.uuid4().hex}
                claim_row = store.insert_order(cur, users[0], "staging_claim_race", base_row["connection_hash"], claim_request)
            gate = threading.Barrier(2)
            claims, failures = [], []

            def competing_claim():
                independent = None
                try:
                    independent = get_db_conn()
                    gate.wait(timeout=5)
                    with repo.transaction(independent) as cur:
                        claims.append(store.claim_submission(cur, users[0], claim_row["id"]))
                except Exception:
                    failures.append(True)
                finally:
                    if independent is not None:
                        independent.close()

            claimers = [threading.Thread(target=competing_claim, daemon=True) for _ in range(2)]
            for claimer in claimers:
                claimer.start()
            for claimer in claimers:
                claimer.join(timeout=15)
            require(not failures and not any(claimer.is_alive() for claimer in claimers)
                    and sorted(claims) == [False, True], "concurrent_submission_claim_not_unique")
            with repo.transaction(conn) as cur:
                require(store.record_result(cur, users[0], claim_row["id"], status="rejected", error_code="broker_rejected"),
                        "claim_fixture_cleanup_failed")
            passed("independent_transactions_claim_exactly_once")
            stage("no_background_work_or_kalshi_balance_changes")
            counts = StagingRepository.final_counts(conn)
            require(counts["fixture_users"] == 2 and counts["paper_order_rows"] == 5
                    and counts["active_runs"] == counts["active_deployments"] == 0, "unexpected_background_work")
            require(all(repo.paper_balance(conn.cursor(), uid) == balance for uid, balance in zip(users, balances)),
                    "kalshi_paper_ledger_changed")
            passed("no_background_work_or_kalshi_balance_changes")
            return {"status": "passed", "mode": "synthetic_broker_real_mysql_http", "checks": checks,
                    "counts": {**counts, "synthetic_submissions": fixture.posts, "synthetic_cancellations": fixture.cancels},
                    "real_provider_calls": 0, "real_oauth_tested": False, "production_changed": False}
    finally:
        if thread.is_alive():
            http.shutdown()
        http.server_close()
        if thread.is_alive():
            thread.join(timeout=5)
        ports.discard(http.server_port)
        for session in sessions:
            session.close()
        conn.close()


_HTTP_PORTS: set[int] = set()


def main() -> int:
    _CHECKS.clear()
    _HTTP_FAILURE.clear()
    stage("isolation_environment")
    try:
        root = Path.cwd()
        validate_environment(dict(os.environ), root)
        require(not any(name == "app" or name.startswith("app.") for name in sys.modules), "app_imported_before_guard")
        require((root / "app/server.py").is_file(), "application_source_missing")
        sys.path.insert(0, str(root))
        for name, value in FIXTURE_OAUTH.items():
            os.environ[name] = value
        with contextlib.redirect_stdout(NullLog()), contextlib.redirect_stderr(NullLog()), \
                isolated_network(os.environ["MYSQL_HOST"], int(os.environ.get("MYSQL_PORT", "3306")), _HTTP_PORTS):
            result = run_acceptance()
    except Exception as exc:
        result = failure_result(exc)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
