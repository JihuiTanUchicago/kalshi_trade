"""Hosted staging isolation/configuration contracts; no Docker, DB or provider calls."""
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parents[1]
HOSTED = HERE / "staging/hosted"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


entry = module("hosted_staging_entry_test", HOSTED / "entrypoint.py")
setup = module("hosted_staging_setup_test", HOSTED / "setup.py")


def runtime_fixture():
    # Shape fixtures, deliberately not accepted/provider-tested credentials.
    return {
        "APP_PUBLIC_URL": "https://d111111111111.cloudfront.net",
        "GOOGLE_CLIENT_ID": "1234567890-stageclient.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "GOCSPX-" + "a" * 24,
        "ALPACA_OAUTH_CLIENT_ID": "tauStageFixtureClient01",
        "ALPACA_OAUTH_CLIENT_SECRET": "tauStageFixtureSecret" + "b" * 24,
        "STRIPE_SECRET_KEY": "sk_test_" + "c" * 32,
        "STRIPE_PUBLISHABLE_KEY": "pk_test_" + "d" * 32,
        "STRIPE_WEBHOOK_SECRET": "whsec_" + "e" * 32,
        "TAU_ADMIN_EMAIL": "operator@tau-staging.test",
    }


def secret_fixture():
    return {"mysql_password": "synthetic-database-secret-" + "a" * 24,
            "app_secret_key": base64.urlsafe_b64encode(bytes(range(32))).decode()}


def private_write(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)


class RuntimeValidationTests(unittest.TestCase):
    def test_valid_runtime_is_a_pure_copy_and_normalizes_only_the_origin(self):
        values = runtime_fixture()
        values["APP_PUBLIC_URL"] += "/"
        values["STRIPE_PAYMENT_CONFIG"] = "pmc_123456789012"
        original = dict(values)
        with patch.dict(os.environ, {"MYSQL_HOST": "production-db", "APP_DEV_LOGIN": "1"}):
            result = entry.validate_runtime(values)
        self.assertEqual(values, original)
        self.assertIsNot(result, values)
        self.assertEqual(result["APP_PUBLIC_URL"], original["APP_PUBLIC_URL"].rstrip("/"))
        self.assertEqual(result["STRIPE_PAYMENT_CONFIG"], values["STRIPE_PAYMENT_CONFIG"])

    def test_every_required_field_must_be_present_nonempty_and_text(self):
        for key in entry.REQUIRED_RUNTIME:
            for replacement in (None, "", 1, False):
                with self.subTest(field=key, replacement=type(replacement).__name__):
                    values = runtime_fixture()
                    if replacement is None:
                        del values[key]
                    else:
                        values[key] = replacement
                    with self.assertRaisesRegex(entry.HostedError, "runtime_values_missing") as caught:
                        entry.validate_runtime(values)
                    self.assertIn(key, caught.exception.fields)

    def test_arbitrary_database_gate_provider_and_aws_overrides_are_rejected(self):
        extras = ("MYSQL_HOST", "MYSQL_PASSWORD", "APP_SECRET_KEY", "APP_DEV_LOGIN", "APP_INSECURE_COOKIES",
                  "APP_LIVE_TRADING_ENABLED", "TAU_ALPACA_ENABLED", "TAU_ALPACA_PAPER_MAX_ORDER_USD",
                  "ALPACA_API_KEY", "EXA_API_KEY", "OPENAI_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_PROFILE",
                  "TAU_HOSTED_STATE_DIR", "APP_GOOGLE_REDIRECT_URI", "TAU_PUBLIC_URL", "PYTHONPATH")
        for name in extras:
            with self.subTest(field=name), self.assertRaisesRegex(entry.HostedError, "unexpected_runtime_fields"):
                entry.validate_runtime({**runtime_fixture(), name: "forbidden-value"})

    def test_https_public_origin_cannot_target_production_localhost_or_another_path(self):
        invalid = (
            "http://staging.tau.ai", "https://localhost", "https://staging.localhost", "https://127.0.0.1",
            "https://10.0.0.3", "https://[::1]", "https://example.com", "https://stage.internal",
            "https://stage.test", "https://stage.invalid", "https://stage.example", "https://stage.local",
            "https://d1gfpzcosqrjya.cloudfront.net", "https://x.d1gfpzcosqrjya.cloudfront.net",
            "https://user:pass@stage.tau.ai", "https://stage.tau.ai/callback", "https://stage.tau.ai?secret=x",
            "https://stage.tau.ai#fragment", "https://stage.tau.ai:0", "https://stage.tau.ai:99999",
            "https://stage..tau.ai", "https://stage.tau.ai.", "https://stage.tau.ai\n",
        )
        for value in invalid:
            with self.subTest(origin=value), self.assertRaises(entry.HostedError):
                entry.validate_runtime({**runtime_fixture(), "APP_PUBLIC_URL": value})

    def test_oauth_credentials_reject_shell_control_and_obvious_placeholders(self):
        invalid = ("short", "placeholder-secret-key", "replace-this-secret", "your_client_secret",
                   "changeme-secret", "synthetic-secret", "a" * 8 + "\n", "$(cat private)",
                   "`cat-private`", "x;touch-private", "with whitespace", "secret\x00value", "x" * 513)
        for key in ("GOOGLE_CLIENT_SECRET", "ALPACA_OAUTH_CLIENT_ID", "ALPACA_OAUTH_CLIENT_SECRET"):
            for value in invalid:
                with self.subTest(field=key, value_type=len(value)), self.assertRaises(entry.HostedError):
                    entry.validate_runtime({**runtime_fixture(), key: value})
        with self.assertRaisesRegex(entry.HostedError, "google_client_id_invalid"):
            entry.validate_runtime({**runtime_fixture(), "GOOGLE_CLIENT_ID": "ordinary-client"})

    def test_all_sandbox_billing_credentials_are_required_and_live_keys_are_rejected(self):
        for key, invalid in (("STRIPE_SECRET_KEY", "sk_live_" + "x" * 32),
                             ("STRIPE_PUBLISHABLE_KEY", "pk_live_" + "x" * 32),
                             ("STRIPE_WEBHOOK_SECRET", "whsec_tooShort")):
            with self.subTest(field=key), self.assertRaisesRegex(entry.HostedError, "stripe_sandbox_configuration_invalid"):
                entry.validate_runtime({**runtime_fixture(), key: invalid})
        with self.assertRaisesRegex(entry.HostedError, "stripe_payment_config_invalid"):
            entry.validate_runtime({**runtime_fixture(), "STRIPE_PAYMENT_CONFIG": "pmc_short"})
        with self.assertRaisesRegex(entry.HostedError, "admin_email_invalid"):
            entry.validate_runtime({**runtime_fixture(), "TAU_ADMIN_EMAIL": "not-an-email"})

    def test_runtime_json_rejects_duplicate_fields_nonobjects_and_oversized_values(self):
        for raw in (b'{"APP_PUBLIC_URL":"first","APP_PUBLIC_URL":"second"}', b"[]", b"null",
                    b"not-json", b"\xff", b"{" + b" " * 16384 + b"}"):
            with self.subTest(length=len(raw)), self.assertRaises(entry.HostedError):
                entry.parse_runtime(raw)
        self.assertEqual(entry.parse_runtime(json.dumps(runtime_fixture()).encode()), runtime_fixture())
        with self.assertRaises(entry.HostedError):
            entry.validate_runtime({**runtime_fixture(), "STRIPE_PAYMENT_CONFIG": {"nested": "invalid"}})


class EnvironmentTests(unittest.TestCase):
    def test_normal_oauth_billing_and_secure_cookies_use_only_staging_database(self):
        env = entry.child_environment("web", secret_fixture(), runtime_fixture())
        self.assertEqual((env["MYSQL_HOST"], env["MYSQL_DATABASE"], env["MYSQL_USER"]),
                         ("db", "tau_preproduction_staging", "tau_preprod"))
        self.assertEqual((env["APP_HOST"], env["APP_DEV_LOGIN"], env["APP_INSECURE_COOKIES"]),
                         ("0.0.0.0", "0", "0"))
        self.assertEqual(env["APP_GOOGLE_REDIRECT_URI"], runtime_fixture()["APP_PUBLIC_URL"] + "/auth/google/callback")
        self.assertEqual(env["TAU_PUBLIC_URL"], runtime_fixture()["APP_PUBLIC_URL"])
        self.assertEqual(env["TAU_OPERATOR_EMAIL"], runtime_fixture()["TAU_ADMIN_EMAIL"])
        self.assertEqual(env["STRIPE_SECRET_KEY"], runtime_fixture()["STRIPE_SECRET_KEY"])
        self.assertEqual(env["ALPACA_OAUTH_CLIENT_SECRET"], runtime_fixture()["ALPACA_OAUTH_CLIENT_SECRET"])

    def test_inherited_production_files_credentials_and_feature_flags_cannot_enter_child(self):
        inherited = {"AWS_ACCESS_KEY_ID": "synthetic-private", "AWS_SECRET_ACCESS_KEY": "synthetic-private",
                     "AWS_PROFILE": "production", "EXA_API_KEY": "synthetic-private", "APCA_API_KEY_ID": "synthetic-private",
                     "OPENAI_API_KEY": "synthetic-private", "GOOGLE_CLIENT_SECRET": "inherited-private",
                     "APP_LIVE_TRADING_ENABLED": "1", "APP_NO_SIDE_LIVE_ENABLED": "1", "APP_DEV_LOGIN": "1",
                     "MYSQL_HOST": "production-db", "PYTHONPATH": "/unreviewed", "HOME": "/private/home",
                     "CODEX_HOME": "/private/codex", "TAU_HOSTED_STATE_DIR": "/production/state"}
        with patch.dict(os.environ, inherited):
            for mode in entry.MODES:
                env = entry.child_environment(mode, secret_fixture(), runtime_fixture() if mode == "web" else None)
                for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE", "EXA_API_KEY", "APCA_API_KEY_ID",
                            "OPENAI_API_KEY", "PYTHONPATH", "HOME", "CODEX_HOME", "TAU_HOSTED_STATE_DIR"):
                    self.assertNotIn(key, env)
                for key in ("APP_LIVE_TRADING_ENABLED", "APP_NO_SIDE_LIVE_ENABLED", "APP_DEV_LOGIN"):
                    self.assertEqual(env[key], "0")
                self.assertEqual(env["AWS_EC2_METADATA_DISABLED"], "true")
                self.assertEqual(env["AWS_SHARED_CREDENTIALS_FILE"], "/dev/null")
                self.assertEqual(env["AWS_CONFIG_FILE"], "/dev/null")
                for provider in ("ALPACA", "MASSIVE", "DATABENTO", "EXA", "EXA_HISTORICAL", "WORLDMONITOR"):
                    self.assertEqual(env["TAU_" + provider + "_ENABLED"], "0")
                self.assertEqual((env["TAU_ALPACA_PAPER_ENABLED"], env["TAU_ALPACA_PAPER_MAX_ORDER_USD"]), ("1", "500"))

    def test_schema_has_no_oauth_billing_credentials_and_web_cannot_start_without_them(self):
        schema = entry.child_environment("schema", secret_fixture())
        self.assertFalse(any(key in schema for key in entry.REQUIRED_RUNTIME + entry.OPTIONAL_RUNTIME))
        with self.assertRaisesRegex(entry.HostedError, "schema_runtime_credentials_forbidden"):
            entry.child_environment("schema", secret_fixture(), runtime_fixture())
        for runtime in (None, {}, {**runtime_fixture(), "STRIPE_SECRET_KEY": ""}):
            with self.assertRaises(entry.HostedError):
                entry.child_environment("web", secret_fixture(), runtime)

    def test_only_full_schema_and_web_commands_are_available(self):
        for mode, module_name in (("schema", "app.schema"), ("web", "app.server")):
            argv = entry.command(mode)
            self.assertEqual(argv[:5], [entry.PYTHON, "-I", "-B", "-u", "-c"])
            self.assertIn(repr(module_name), argv[-1])
            self.assertNotIn("app.worker", argv[-1])
            self.assertNotIn("app.engine", argv[-1])
            self.assertNotIn("data_pipeline.init_schema", argv[-1])
        for mode in ("agents", "worker", "engine", "verify", "bash", "web;evil", ""):
            with self.subTest(mode=mode), self.assertRaises(entry.HostedError):
                entry.command(mode)

    def test_database_password_and_vault_fields_are_exact_and_strongly_typed(self):
        for values in ({**secret_fixture(), "mysql_root_password": "unused"}, {},
                       {**secret_fixture(), "mysql_password": "short"},
                       {**secret_fixture(), "app_secret_key": "invalid"},
                       {**secret_fixture(), "app_secret_key": "-" * 32},
                       {**secret_fixture(), "mysql_password": None}):
            with self.subTest(fields=tuple(values)), self.assertRaises(entry.HostedError):
                entry.child_environment("schema", values)

    def test_bootstrap_drops_privileges_before_exec_and_passes_no_bootstrap_marker(self):
        order, captured = [], {}
        files = {name: value.encode() for name, value in secret_fixture().items()}
        files["hosted_runtime.json"] = json.dumps(runtime_fixture()).encode()

        def execute(path, argv, env):
            order.append("exec")
            captured.update(path=path, argv=argv, env=env)
            raise SystemExit(0)

        with patch.object(entry.os, "geteuid", return_value=0), \
                patch.dict(entry.os.environ, {"TAU_HOSTED_CONTAINER": "dedicated-preproduction-v1"}, clear=True), \
                patch.object(entry, "read_private", side_effect=lambda path, *args: files[path.name]), \
                patch.object(entry.os, "chdir"), \
                patch.object(entry.os, "setgroups", side_effect=lambda groups: order.append(("groups", groups))), \
                patch.object(entry.os, "setgid", side_effect=lambda gid: order.append(("gid", gid))), \
                patch.object(entry.os, "setuid", side_effect=lambda uid: order.append(("uid", uid))), \
                patch.object(entry.os, "execve", execute):
            with self.assertRaises(SystemExit):
                entry.main(["web"])
        self.assertEqual(order, [("groups", []), ("gid", 10001), ("uid", 10001), "exec"])
        self.assertEqual(captured["env"]["APP_DEV_LOGIN"], "0")
        self.assertNotIn("TAU_HOSTED_CONTAINER", captured["env"])

    def test_bootstrap_failures_never_include_exception_text_or_private_values(self):
        output = io.StringIO()
        with patch.object(entry.os, "geteuid", return_value=0), \
                patch.dict(entry.os.environ, {"TAU_HOSTED_CONTAINER": "dedicated-preproduction-v1"}, clear=True), \
                patch.object(entry, "read_private", side_effect=OSError("synthetic-private-failure")), \
                contextlib.redirect_stderr(output):
            self.assertEqual(entry.main(["web"]), 1)
        self.assertEqual(json.loads(output.getvalue()), {"status": "blocked", "check": "hosted_configuration",
                                                       "error_code": "private_configuration_unavailable"})


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tau-hosted-synthetic-")
        self.folder = Path(self.temporary.name).resolve() / "hosted"
        self.folder.mkdir(mode=0o700)

    def tearDown(self):
        self.temporary.cleanup()

    def test_initial_private_state_is_pending_and_independent_without_printing_credentials(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = setup.prepare(self.folder)
        state = self.folder / ".state"
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(result["status"], "created")
        self.assertFalse(result["readiness"]["ready"])
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
        values = []
        for name in (*setup.GENERATED, "hosted_runtime.json", ".gitignore"):
            self.assertEqual(stat.S_IMODE((state / name).stat().st_mode), 0o600)
            self.assertEqual((state / name).stat().st_uid, os.getuid())
        for name in setup.GENERATED:
            values.append((state / name).read_bytes())
        self.assertEqual(len(set(values)), 3)
        self.assertEqual(len(base64.urlsafe_b64decode(values[-1])), 32)
        self.assertFalse(any(value.decode() in json.dumps(result) for value in values))
        self.assertEqual((state / ".gitignore").read_bytes(), b"*\n")
        fence = setup.fence_path(state)
        self.assertEqual(fence.parent, state.parent)
        self.assertEqual(fence.read_bytes(), setup.INITIALIZATION_FENCE)
        self.assertEqual(stat.S_IMODE(fence.stat().st_mode), 0o600)
        self.assertEqual(fence.stat().st_uid, os.getuid())
        self.assertFalse((self.folder / ".env").exists())
        with self.assertRaisesRegex(setup.hosted.HostedError, "runtime_values_missing"):
            setup.check(self.folder)

    def test_ignore_rule_precedes_secret_generation(self):
        names, original = [], setup.write_new

        def tracked(path, raw):
            names.append(path.name)
            original(path, raw)

        with patch.object(setup, "write_new", tracked):
            setup.prepare(self.folder)
        self.assertEqual(names, [".gitignore", *setup.GENERATED, ".state.initialized", "hosted_runtime.json"])

    def test_persistent_state_is_reused_across_immutable_release_directories(self):
        state = self.folder.parent / "persistent-state"
        setup.prepare(self.folder, state)
        before = {name: ((state / name).read_bytes(), (state / name).stat().st_mtime_ns)
                  for name in setup.GENERATED}
        next_release = self.folder.parent / "new-release"
        next_release.mkdir(mode=0o700)
        result = setup.prepare(next_release, state)
        self.assertEqual(result["status"], "reused")
        for name in setup.GENERATED:
            self.assertEqual(before[name], ((state / name).read_bytes(), (state / name).stat().st_mtime_ns))
        self.assertFalse((next_release / ".state").exists())

    def test_initialized_state_cannot_regenerate_after_all_or_one_secret_disappears(self):
        for removed in ((setup.GENERATED[0],), setup.GENERATED):
            with self.subTest(removed=len(removed)):
                state = self.folder / ("private-state-" + str(len(removed)))
                setup.prepare(self.folder, state)
                for name in removed:
                    (state / name).unlink()
                before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
                          for path in state.iterdir()}
                fence = setup.fence_path(state)
                fence_before = (fence.read_bytes(), fence.stat().st_mtime_ns, fence.stat().st_ino)
                with patch.object(setup.secrets, "token_urlsafe") as generate, \
                        self.assertRaisesRegex(setup.hosted.HostedError, "initialized_hosted_state_incomplete"):
                    setup.prepare(self.folder, state)
                generate.assert_not_called()
                self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
                                          for path in state.iterdir()})
                self.assertEqual(fence_before, (fence.read_bytes(), fence.stat().st_mtime_ns, fence.stat().st_ino))

    def test_sibling_fence_survives_missing_directory_and_blocks_recreation(self):
        state = self.folder.parent / "persistent-state"
        setup.prepare(self.folder, state)
        fence = setup.fence_path(state)
        before = (fence.read_bytes(), fence.stat().st_mtime_ns, fence.stat().st_ino)
        shutil.rmtree(state)
        for operation in (setup.prepare, setup.check):
            with self.assertRaisesRegex(setup.hosted.HostedError, "initialized_hosted_state_incomplete"):
                operation(self.folder, state)
            self.assertFalse(state.exists())
            self.assertEqual(before, (fence.read_bytes(), fence.stat().st_mtime_ns, fence.stat().st_ino))

    def test_complete_legacy_state_gets_a_fence_only_after_validation_without_secret_rotation(self):
        setup.prepare(self.folder)
        state = self.folder / ".state"
        fence = setup.fence_path(state)
        fence.unlink()  # Simulate complete state created before the fence existed.
        before = {name: ((state / name).read_bytes(), (state / name).stat().st_mtime_ns) for name in setup.GENERATED}
        with self.assertRaisesRegex(setup.hosted.HostedError, "hosted_initialization_fence_missing"):
            setup.check(self.folder)
        self.assertEqual(setup.prepare(self.folder)["status"], "reused")
        self.assertEqual(fence.read_bytes(), setup.INITIALIZATION_FENCE)
        self.assertEqual(before, {name: ((state / name).read_bytes(), (state / name).stat().st_mtime_ns)
                                  for name in setup.GENERATED})

    def test_invalid_fence_is_not_followed_changed_or_replaced_before_state_creation(self):
        state = self.folder / "private-state"
        fence = setup.fence_path(state)
        for content, mode in ((b"changed\n", 0o600), (setup.INITIALIZATION_FENCE, 0o644)):
            private_write(fence, content)
            fence.chmod(mode)
            before = (fence.read_bytes(), fence.stat().st_mtime_ns, fence.stat().st_mode)
            with self.assertRaisesRegex(setup.hosted.HostedError, "unsafe_hosted_initialization_fence"):
                setup.prepare(self.folder, state)
            self.assertFalse(state.exists())
            self.assertEqual(before, (fence.read_bytes(), fence.stat().st_mtime_ns, fence.stat().st_mode))
        fence.unlink()
        target = self.folder / "untouched-record"
        private_write(target, setup.INITIALIZATION_FENCE)
        fence.symlink_to(target)
        with self.assertRaisesRegex(setup.hosted.HostedError, "unsafe_hosted_initialization_fence"):
            setup.prepare(self.folder, state)
        self.assertFalse(state.exists())
        self.assertTrue(fence.is_symlink())
        fence.unlink()
        os.link(target, fence)
        with self.assertRaisesRegex(setup.hosted.HostedError, "unsafe_hosted_initialization_fence"):
            setup.prepare(self.folder, state)
        self.assertFalse(state.exists())

    def test_invalid_existing_keys_do_not_create_ignore_file_fence_or_runtime(self):
        state = self.folder / ".state"
        state.mkdir(mode=0o700)
        for name, value in {"mysql_root_password": "r" * 40, **secret_fixture()}.items():
            private_write(state / name, value.encode())
        private_write(state / "app_secret_key", b"invalid-vault-key")
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in state.iterdir()}
        with self.assertRaisesRegex(setup.hosted.HostedError, "invalid_vault_secret"):
            setup.prepare(self.folder)
        self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in state.iterdir()})
        self.assertFalse(setup.fence_path(state).exists())
        ignore = (HOSTED / ".gitignore").read_text().splitlines()
        self.assertIn(".state/", ignore)
        self.assertIn(".state.initialized", ignore)

    def test_existing_invalid_runtime_is_preserved_but_existing_invalid_database_state_fails(self):
        setup.prepare(self.folder)
        state = self.folder / ".state"
        runtime = state / "hosted_runtime.json"
        for raw in (b"", b"not-json", json.dumps({"MYSQL_HOST": "production-db"}).encode()):
            private_write(runtime, raw)
            self.assertFalse(setup.prepare(self.folder)["readiness"]["ready"])
            self.assertEqual(runtime.read_bytes(), raw)
        database = state / "mysql_password"
        private_write(database, b"too-short")
        with self.assertRaisesRegex(setup.hosted.HostedError, "invalid_database_secret"):
            setup.prepare(self.folder)
        self.assertEqual(database.read_bytes(), b"too-short")

    def test_shape_ready_never_claims_provider_authentication_or_https_acceptance(self):
        setup.prepare(self.folder)
        private_write(self.folder / ".state/hosted_runtime.json", json.dumps(runtime_fixture()).encode())
        result = setup.check(self.folder)
        self.assertTrue(result["ready"])
        self.assertEqual((result["provider_authentication"], result["https_reachability"]), ("not_tested", "not_tested"))
        self.assertFalse(any(value in json.dumps(result) for value in runtime_fixture().values()))

    def test_partial_or_insecure_state_is_not_regenerated(self):
        state = self.folder / ".state"
        state.mkdir(mode=0o700)
        private_write(state / "mysql_password", b"synthetic-existing-password")
        with self.assertRaisesRegex(setup.hosted.HostedError, "partial_hosted_state_requires_inspection"):
            setup.prepare(self.folder)
        self.assertFalse((state / "mysql_root_password").exists())
        state.chmod(0o755)
        with self.assertRaisesRegex(setup.hosted.HostedError, "unsafe_hosted_state_directory"):
            setup.prepare(self.folder)

    def test_symlinked_relative_or_traversal_state_path_is_rejected(self):
        target = self.folder.parent / "untouched"
        target.mkdir(mode=0o700)
        link = self.folder / ".state"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(setup.hosted.HostedError, "unsafe_hosted_state_directory"):
            setup.prepare(self.folder)
        self.assertEqual(list(target.iterdir()), [])
        for path in (Path("relative-state"), self.folder / ".." / "traversal-state"):
            with self.assertRaisesRegex(setup.hosted.HostedError, "hosted_state_path_invalid"):
                setup.prepare(self.folder, path)

    def test_changed_ignore_file_and_linked_or_insecure_generated_files_are_rejected(self):
        setup.prepare(self.folder)
        state = self.folder / ".state"
        private_write(state / ".gitignore", b"changed\n")
        with self.assertRaisesRegex(setup.hosted.HostedError, "state_ignore_rule_changed"):
            setup.prepare(self.folder)
        private_write(state / ".gitignore", b"*\n")
        secret = state / "mysql_password"
        secret.chmod(0o644)
        with self.assertRaisesRegex(setup.hosted.HostedError, "unsafe_private_file"):
            setup.prepare(self.folder)
        secret.chmod(0o600)
        target = self.folder / "untouched-private"
        secret.rename(target)
        secret.symlink_to(target)
        with self.assertRaisesRegex(setup.hosted.HostedError, "unsafe_private_file"):
            setup.prepare(self.folder)
        secret.unlink()
        os.link(target, secret)
        with self.assertRaisesRegex(setup.hosted.HostedError, "unsafe_private_file"):
            setup.prepare(self.folder)

    def test_private_reader_rejects_oversized_and_changing_file(self):
        path = self.folder / "private"
        private_write(path, b"a" * 257)
        with self.assertRaisesRegex(entry.HostedError, "unsafe_private_file"):
            entry.read_private(path, 256)
        private_write(path, b"safe-fixture")
        original = entry.os.read

        def changed(descriptor, limit):
            raw = original(descriptor, limit)
            path.write_bytes(b"changed-fixture")
            return raw

        with patch.object(entry.os, "read", changed), self.assertRaisesRegex(entry.HostedError, "private_file_changed"):
            entry.read_private(path)

    def test_cli_runtime_validation_and_pending_check_output_no_values(self):
        output = io.StringIO()
        with patch.object(setup.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(runtime_fixture()).encode()))), \
                contextlib.redirect_stdout(output):
            self.assertEqual(setup.main(["--validate-runtime"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"status": "runtime_shape_valid", "provider_authentication": "not_tested"})
        setup.prepare(self.folder)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(setup.main(["--check", "--state-dir", str(self.folder / ".state")]), 1)
        result = json.loads(output.getvalue())
        self.assertFalse(result["ready"])
        self.assertEqual(result["error_code"], "runtime_values_missing")
        self.assertEqual(set(result["fields"]), set(entry.REQUIRED_RUNTIME))
        self.assertFalse(any(value in output.getvalue() for value in runtime_fixture().values()))


class StackContractTests(unittest.TestCase):
    def setUp(self):
        # Compose accepts JSON as YAML; no parser dependency is needed here.
        self.compose = json.loads((HOSTED / "compose.yml").read_text())

    def test_separate_persistent_database_is_private_and_gateway_is_the_only_published_port(self):
        services = self.compose["services"]
        self.assertEqual(set(services), {"db", "schema", "web", "gateway"})
        self.assertEqual(self.compose["networks"], {"private": {"internal": True}, "egress": {"driver": "bridge"}})
        self.assertEqual(self.compose["volumes"], {"hosted-mysql-data": {}})
        self.assertEqual(services["db"]["volumes"], ["hosted-mysql-data:/var/lib/mysql"])
        self.assertEqual(services["db"]["environment"]["MYSQL_DATABASE"], "tau_preproduction_staging")
        self.assertEqual(services["db"]["environment"]["MYSQL_USER"], "tau_preprod")
        for name, service in services.items():
            self.assertEqual(service["networks"], ["private", "egress"] if name in ("web", "gateway") else ["private"])
            self.assertEqual(service.get("ports", []), ["127.0.0.1:18091:8080"] if name == "gateway" else [])
            self.assertFalse(any(key in service for key in ("env_file", "network_mode", "privileged", "container_name")))

    def test_only_web_receives_oauth_runtime_and_no_service_receives_inherited_environment(self):
        services = self.compose["services"]
        self.assertEqual(services["db"]["secrets"], ["mysql_root_password", "mysql_password"])
        self.assertEqual(services["schema"]["secrets"], ["mysql_password", "app_secret_key"])
        self.assertEqual(services["web"]["secrets"], ["mysql_password", "app_secret_key", {"source": "hosted_runtime", "target": "hosted_runtime.json"}])
        self.assertNotIn("secrets", services["gateway"])
        for name in ("schema", "web"):
            self.assertEqual(services[name]["environment"], {"TAU_HOSTED_CONTAINER": "dedicated-preproduction-v1"})
            self.assertEqual(services[name]["command"], [name])
        for value in self.compose["secrets"].values():
            self.assertTrue(value["file"].startswith("${TAU_HOSTED_STATE_DIR:-./.state}/"))
        self.assertEqual(services["schema"]["depends_on"], {"db": {"condition": "service_healthy"}})
        self.assertEqual(services["web"]["depends_on"], {"schema": {"condition": "service_completed_successfully"}})
        self.assertEqual(services["gateway"]["depends_on"], {"web": {"condition": "service_healthy"}})

    def test_readonly_bootstrap_has_only_read_and_drop_capabilities_and_gateway_has_none(self):
        for name in ("schema", "web", "gateway"):
            service = self.compose["services"][name]
            self.assertTrue(service["read_only"])
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertIn("no-new-privileges:true", service["security_opt"])
            self.assertTrue(all(value.startswith("/tmp:rw,noexec,nosuid,") for value in service["tmpfs"]))
        for name in ("schema", "web"):
            self.assertEqual(set(self.compose["services"][name]["cap_add"]), {"DAC_OVERRIDE", "SETUID", "SETGID"})
        self.assertEqual(self.compose["services"]["gateway"]["user"], "101:101")
        self.assertNotIn("cap_add", self.compose["services"]["gateway"])
        self.assertEqual(self.compose["services"]["gateway"]["volumes"], ["./nginx.conf:/etc/nginx/hosted.conf:ro"])

    def test_image_uses_explicit_complete_product_copies_and_excludes_private_context(self):
        docker = (HOSTED / "Dockerfile").read_text()
        copies = [line for line in docker.splitlines() if line.startswith("COPY ")]
        self.assertEqual(copies, ["COPY requirements.txt requirements.txt", "COPY app/ app/",
                                  "COPY data_pipeline/ data_pipeline/",
                                  "COPY staging/hosted/entrypoint.py /usr/local/lib/tau-hosted/entrypoint.py"])
        self.assertNotIn(".env", docker)
        self.assertNotIn("credentials", docker)
        ignore = (HOSTED / "Dockerfile.dockerignore").read_text().splitlines()
        self.assertEqual(ignore[0], "**")
        self.assertTrue({"!app/**", "!data_pipeline/**", "**/.state/**", "**/.env*", "**/.aws/**", "**/.runtime/**"}.issubset(ignore))
        self.assertFalse(any(line.startswith("!") and (".state" in line or ".env" in line) for line in ignore))

    def test_hosted_proxy_preserves_real_auth_and_mutations_without_query_logs_or_dynamic_upstreams(self):
        nginx = (HOSTED / "nginx.conf").read_text()
        self.assertIn("proxy_pass http://web:8090;", nginx)
        self.assertIn("proxy_set_header Host $host;", nginx)
        self.assertIn("proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;", nginx)
        self.assertIn("map $request_method $hosted_upstream_method", nginx)
        self.assertIn("default $request_method;", nginx)
        self.assertIn("HEAD GET;", nginx)
        self.assertIn("proxy_method $hosted_upstream_method;", nginx)
        self.assertIn("access_log off;", nginx)
        self.assertIn("error_log /dev/null crit;", nginx)
        self.assertIn("pid /tmp/nginx.pid;", nginx)
        self.assertNotIn("proxy_pass $", nginx)
        self.assertNotIn("proxy_set_header Cookie", nginx)
        self.assertNotIn("proxy_set_header Authorization", nginx)
        self.assertNotIn("proxy_hide_header Set-Cookie", nginx)
        self.assertNotIn("limit_except", nginx)
        self.assertNotIn("return 401", nginx)
        self.assertNotIn("return 403", nginx)


if __name__ == "__main__":
    unittest.main()
