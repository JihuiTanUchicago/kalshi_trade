"""Offline harness guards/fixtures only; never opens MySQL or provider services."""
import base64
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch

import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    '_tau_paper_staging_smoke', Path(__file__).resolve().parents[1] / 'scripts/paper_staging_smoke.py')
smoke = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(smoke)


def environment():
    return {**smoke.FIXED_FLAGS,
            "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "3306", "MYSQL_DATABASE": smoke.DATABASE,
            "MYSQL_USER": smoke.DATABASE_USER, "MYSQL_PASSWORD": "synthetic-disposable-password",
            "APP_PUBLIC_URL": "http://127.0.0.1:8091",
            "APP_SECRET_KEY": base64.urlsafe_b64encode(bytes(range(32))).decode(),
            "AWS_EC2_METADATA_DISABLED": "true", "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "AWS_CONFIG_FILE": "/dev/null"}


class GuardTests(unittest.TestCase):
    def check(self, env, exists=lambda path: False):
        smoke.validate_environment(env, Path("/synthetic-checkout/kalshi_trade_infra"), path_exists=exists)

    def test_clean_disposable_environment_is_accepted_without_importing_app(self):
        before = {name for name in sys.modules if name == "app" or name.startswith("app.")}
        self.check(environment())
        self.assertEqual(before, {name for name in sys.modules if name == "app" or name.startswith("app.")})
        for host in ("localhost", "db"):
            self.check({**environment(), "MYSQL_HOST": host})
        self.check({**environment(), **smoke.FIXTURE_OAUTH})

    def test_every_required_isolation_flag_fails_closed_when_missing_or_wrong(self):
        for name in smoke.FIXED_FLAGS:
            for bad in (None, "unexpected", ""):
                with self.subTest(name=name):
                    env = environment()
                    if bad is None:
                        env.pop(name)
                    else:
                        env[name] = bad
                    with self.assertRaisesRegex(smoke.SmokeError, "isolation_flags_invalid"):
                        self.check(env)

    def test_db_name_user_host_and_port_cannot_select_production(self):
        for name, bad in (("MYSQL_DATABASE", "kalshi_trade"), ("MYSQL_USER", "root"),
                          ("MYSQL_HOST", "production-db.example"), ("MYSQL_HOST", "169.254.169.254"),
                          ("MYSQL_HOST", "/var/run/mysql.sock"), ("MYSQL_PORT", "0"),
                          ("MYSQL_PORT", "65536"), ("MYSQL_PORT", "3306;exit"), ("MYSQL_PASSWORD", "")):
            with self.subTest(name=name):
                with self.assertRaises(smoke.SmokeError):
                    self.check({**environment(), name: bad})

    def test_every_provider_flag_is_disabled(self):
        for name in smoke.DISABLED_FLAGS:
            with self.subTest(name=name):
                with self.assertRaisesRegex(smoke.SmokeError, "provider_flag_enabled"):
                    self.check({**environment(), name: "1"})

    def test_external_credentials_and_loading_hooks_are_rejected_without_values_in_error(self):
        private = "synthetic-sensitive-sentinel"
        for name in smoke.FORBIDDEN_KEYS:
            with self.subTest(name=name):
                with self.assertRaisesRegex(smoke.SmokeError, "external_credentials_forbidden") as caught:
                    self.check({**environment(), name: private})
                self.assertNotIn(private, str(caught.exception))

    def test_only_exact_synthetic_oauth_identifiers_are_accepted(self):
        for name in smoke.FIXTURE_OAUTH:
            with self.subTest(name=name):
                with self.assertRaisesRegex(smoke.SmokeError, "real_oauth_credentials_forbidden"):
                    self.check({**environment(), name: "anything-other-than-the-literal-fixture"})

    def test_aws_metadata_and_shared_credential_fallback_must_be_disabled(self):
        for name, bad in (("AWS_EC2_METADATA_DISABLED", "false"),
                          ("AWS_SHARED_CREDENTIALS_FILE", "/home/runner/.aws/credentials"),
                          ("AWS_CONFIG_FILE", "")):
            with self.subTest(name=name):
                with self.assertRaisesRegex(smoke.SmokeError, "aws_fallback_not_disabled"):
                    self.check({**environment(), name: bad})

    def test_production_public_origins_external_hosts_and_ambiguous_local_origins_are_rejected(self):
        for value in ("https://d1gfpzcosqrjya.cloudfront.net", "https://127.0.0.1:8091",
                      "http://127.0.0.1.attacker.test", "http://user@127.0.0.1:8091",
                      "http://127.0.0.1/path", "http://127.0.0.1?next=production",
                      "http://127.0.0.1#fragment", "http://127.0.0.1:65536", "http://127.0.0.1\n"):
            with self.subTest(case=value[:10]):
                with self.assertRaisesRegex(smoke.SmokeError, "public_origin_not_loopback"):
                    self.check({**environment(), "APP_PUBLIC_URL": value})

    def test_fresh_valid_vault_key_is_required_but_never_exposed(self):
        for value in ("", "synthetic-invalid-base64", base64.b64encode(b"too-short").decode()):
            with self.assertRaisesRegex(smoke.SmokeError, "disposable_vault_key_invalid"):
                self.check({**environment(), "APP_SECRET_KEY": value})

    def test_any_discovered_private_environment_or_production_config_path_stops_before_import(self):
        for name in (".env", ".env.app", ".env.aws", ".env.staging", "provider-data", "alpaca-paper"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(smoke.SmokeError, "private_production_files_present"):
                    self.check(environment(), exists=lambda path: path.name == name)

    def test_production_source_root_is_never_allowed(self):
        for root in (Path("/opt/kalshi"), Path("/opt/kalshi/nested")):
            with self.assertRaisesRegex(smoke.SmokeError, "production_source_root_forbidden"):
                smoke.validate_environment(environment(), root, path_exists=lambda path: False)

    def test_invalid_cli_environment_returns_only_a_sanitized_json_receipt(self):
        output = io.StringIO()
        with patch.dict(smoke.os.environ, {}, clear=True), contextlib.redirect_stdout(output):
            self.assertEqual(smoke.main(), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["error_code"], "isolation_flags_invalid")
        self.assertNotIn("Traceback", output.getvalue())

    def test_failure_receipt_keeps_fixed_stage_class_and_mysql_number_without_private_message(self):
        class SyntheticMySQLError(Exception):
            pass

        SyntheticMySQLError.__module__ = "pymysql.err"
        with patch.object(smoke, "_STAGE", "decimal_and_unique_ddl"), \
                patch.object(smoke, "_CHECKS", [{"name": "fresh_disposable_database", "passed": True}]), \
                patch.object(smoke, "_HTTP_FAILURE", {}):
            report = smoke.failure_result(SyntheticMySQLError(1062, "synthetic-private-SQL-session-user"))
        self.assertEqual(report["mysql_error_code"], 1062)
        self.assertEqual(report["exception_class"], "SyntheticMySQLError")
        self.assertEqual(report["stage"], "decimal_and_unique_ddl")
        self.assertEqual(report["last_completed_check"], "fresh_disposable_database")
        self.assertNotIn("synthetic-private", json.dumps(report))

    def test_http_failure_keeps_only_numeric_statuses(self):
        with patch.object(smoke, "_HTTP_FAILURE", {"expected": 200, "observed": 500}):
            report = smoke.failure_result(smoke.SmokeError("http_status_unexpected"))
        self.assertEqual(report["http_status"], {"expected": 200, "observed": 500})


class NetworkTests(unittest.TestCase):
    def test_only_selected_db_and_registered_loopback_http_port_are_allowed(self):
        lookup = Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 3306))])
        connect = Mock(return_value=None)
        with patch.object(socket, "getaddrinfo", lookup), patch.object(socket.socket, "connect", connect):
            ports = {8091}
            with smoke.isolated_network("127.0.0.1", 3306, ports):
                socket.socket.connect(None, ("127.0.0.1", 3306))
                socket.socket.connect(None, ("127.0.0.1", 8091))
                for address in (("127.0.0.1", 8090), ("1.1.1.1", 443), ("169.254.169.254", 80)):
                    with self.subTest(address=address):
                        with self.assertRaisesRegex(smoke.SmokeError, "external_connection_blocked"):
                            socket.socket.connect(None, address)
                with self.assertRaisesRegex(smoke.SmokeError, "external_dns_blocked"):
                    socket.getaddrinfo("paper-api.alpaca.markets", 443)
                ports.add(8092)
                socket.socket.connect(None, ("127.0.0.1", 8092))
        self.assertEqual(connect.call_count, 3)

    def test_db_alias_cannot_resolve_to_public_internet(self):
        lookup = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 3306))]
        with patch.object(socket, "getaddrinfo", return_value=lookup):
            with self.assertRaisesRegex(smoke.SmokeError, "database_address_not_private"):
                with smoke.isolated_network("db", 3306, set()):
                    self.fail("untrusted address entered network scope")


class FixtureTests(unittest.TestCase):
    def test_broker_fixture_is_owner_scoped_and_only_explicit_changes_create_fills(self):
        broker = smoke.SyntheticBroker()
        first, second = broker.add_account("synthetic-one"), broker.add_account("synthetic-two")
        request = {"client_order_id": "tau-paper-" + "a" * 32, "qty": "1", "limit_price": "100", "side": "buy"}
        with broker.client(first) as client:
            response = client.submit_order(request)
            self.assertEqual(response["filled_qty"], "0")
            self.assertEqual(response["status"], "new")
            self.assertEqual(broker.posts, 1)
            with broker.client(second) as other:
                self.assertIsNone(other.get_order(request["client_order_id"]))
                self.assertEqual(other.orders(), [])
            broker.fill(request["client_order_id"])
            self.assertEqual(client.get_order(request["client_order_id"])["status"], "filled")
            self.assertEqual(client.orders(), [])
            self.assertEqual(len(client.orders(status="all")), 1)

    def test_fake_grants_cannot_match_arbitrary_tokens_and_duplicates_are_refused(self):
        broker = smoke.SyntheticBroker()
        with self.assertRaisesRegex(smoke.SmokeError, "synthetic_grant_mismatch"):
            broker.client({"access_token": "not-a-fixture", "account_id": "anything"})
        credentials = broker.add_account("synthetic-one")
        with broker.client(credentials) as client:
            request = {"client_order_id": "tau-paper-" + "a" * 32, "qty": "1", "limit_price": "100"}
            client.submit_order(request)
            with self.assertRaisesRegex(smoke.SmokeError, "synthetic_duplicate_post"):
                client.submit_order(request)
        self.assertEqual(broker.posts, 1)

    def test_application_logs_are_discarded_without_retaining_values(self):
        null = smoke.NullLog()
        self.assertEqual(null.write("synthetic private log"), 21)
        self.assertIsNone(null.flush())
        self.assertFalse(hasattr(null, "getvalue"))


if __name__ == "__main__":
    unittest.main()
