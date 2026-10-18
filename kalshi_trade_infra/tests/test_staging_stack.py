"""Offline stack contracts and private setup; no Docker, DB or provider calls."""
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


setup = module("tau_staging_setup", HERE / "staging/setup.py")
entry = module("tau_staging_entry", HERE / "staging/entrypoint.py")


def fixture_secrets():
    return {"mysql_password": "synthetic-staging-password-" + "a" * 24,
            "app_secret_key": base64.urlsafe_b64encode(bytes(range(32))).decode()}


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tau-staging-stack-synthetic-")
        self.staging = Path(self.temporary.name) / "staging"
        self.staging.mkdir(mode=0o700)

    def tearDown(self):
        self.temporary.cleanup()

    def test_generated_state_is_private_ignored_distinct_and_never_printed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = setup.prepare(self.staging)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(result["status"], "created")
        state = self.staging / ".state"
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
        values = []
        for name in setup.NAMES:
            path = state / name
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_uid, os.getuid())
            values.append(path.read_bytes())
        self.assertEqual(len(set(values)), 3)
        self.assertEqual(len(base64.urlsafe_b64decode(values[-1])), 32)
        self.assertTrue((state / ".gitignore").read_bytes() == b"*\n")
        self.assertFalse(any(value.decode() in json.dumps(result) for value in values))
        self.assertFalse((self.staging / ".env").exists())

    def test_ignore_rule_is_written_before_secrets(self):
        order = []
        original = setup._write_new

        def tracked(path, raw):
            order.append(path.name)
            original(path, raw)

        with patch.object(setup, "_write_new", tracked):
            setup.prepare(self.staging)
        self.assertEqual(order, [".gitignore", *setup.NAMES])

    def test_repeat_setup_reuses_bytes_and_metadata_instead_of_rotating_under_database(self):
        setup.prepare(self.staging)
        state = self.staging / ".state"
        before = {name: ((state / name).read_bytes(), (state / name).stat().st_mtime_ns) for name in setup.NAMES}
        self.assertEqual(setup.prepare(self.staging)["status"], "reused")
        self.assertTrue(all(before[name] == ((state / name).read_bytes(), (state / name).stat().st_mtime_ns)
                            for name in setup.NAMES))

    def test_partial_existing_state_fails_without_overwriting_private_bytes(self):
        state = self.staging / ".state"
        state.mkdir(mode=0o700)
        path = state / "mysql_password"
        path.write_bytes(b"synthetic-existing-private-password")
        path.chmod(0o600)
        before = path.read_bytes()
        with self.assertRaisesRegex(setup.SetupError, "partial_state_requires_inspection"):
            setup.prepare(self.staging)
        self.assertTrue(path.read_bytes() == before)
        self.assertFalse((state / "mysql_root_password").exists())

    def test_insecure_directory_or_changed_ignore_rule_is_rejected(self):
        state = self.staging / ".state"
        state.mkdir(mode=0o755)
        with self.assertRaisesRegex(setup.SetupError, "unsafe_state_directory"):
            setup.prepare(self.staging)
        state.chmod(0o700)
        (state / ".gitignore").write_bytes(b"different\n")
        (state / ".gitignore").chmod(0o600)
        with self.assertRaisesRegex(setup.SetupError, "state_ignore_rule_changed"):
            setup.prepare(self.staging)
        self.assertFalse((state / "mysql_password").exists())

    def test_symlink_and_hardlink_state_files_are_not_followed(self):
        setup.prepare(self.staging)
        target = self.staging / ".state/mysql_password"
        raw = target.read_bytes()
        alias = self.staging / "untouched"
        target.rename(alias)
        target.symlink_to(alias)
        with self.assertRaisesRegex(setup.SetupError, "unsafe_state_file"):
            setup.prepare(self.staging)
        target.unlink()
        os.link(alias, target)
        with self.assertRaisesRegex(setup.SetupError, "unsafe_state_file"):
            setup.prepare(self.staging)
        self.assertTrue(alias.read_bytes() == raw)


class EntrypointTests(unittest.TestCase):
    def test_web_keeps_existing_dev_login_bind_guard_and_verify_is_loopback_only(self):
        web = entry.child_environment("web", fixture_secrets())
        verify = entry.child_environment("verify", fixture_secrets())
        self.assertEqual((web["APP_HOST"], web["APP_DEV_LOGIN"], web["APP_PORT"]), ("0.0.0.0", "0", "8090"))
        self.assertEqual((verify["APP_HOST"], verify["APP_DEV_LOGIN"], verify["APP_PORT"]), ("127.0.0.1", "1", "8091"))
        self.assertEqual(verify["APP_PUBLIC_URL"], "http://127.0.0.1:8091")
        self.assertEqual(verify["TAU_STAGING_DISPOSABLE_DB"], "1")
        self.assertEqual((verify["MYSQL_HOST"], verify["MYSQL_DATABASE"], verify["MYSQL_USER"]),
                         ("db", "tau_paper_staging", "tau_stage"))

    def test_provider_live_and_aws_credentials_cannot_leak_from_parent_environment(self):
        inherited = {"AWS_ACCESS_KEY_ID": "synthetic-private", "AWS_PROFILE": "production",
                     "EXA_API_KEY": "synthetic-private", "ALPACA_OAUTH_CLIENT_SECRET": "synthetic-private",
                     "APP_LIVE_TRADING_ENABLED": "1", "APP_DEV_LOGIN": "1", "PYTHONPATH": "/unreviewed"}
        with patch.dict(os.environ, inherited):
            for mode in entry.MODES:
                env = entry.child_environment(mode, fixture_secrets())
                self.assertFalse(any(key in env for key in inherited if key not in ("APP_LIVE_TRADING_ENABLED", "APP_DEV_LOGIN")))
                self.assertEqual(env["APP_LIVE_TRADING_ENABLED"], "0")
                self.assertEqual(env["APP_NO_SIDE_LIVE_ENABLED"], "0")
                self.assertEqual(env["AWS_EC2_METADATA_DISABLED"], "true")
                self.assertEqual(env["AWS_SHARED_CREDENTIALS_FILE"], "/dev/null")
                self.assertEqual(env["AWS_CONFIG_FILE"], "/dev/null")
                for provider in ("ALPACA", "MASSIVE", "DATABENTO", "EXA", "EXA_HISTORICAL", "WORLDMONITOR"):
                    self.assertEqual(env["TAU_" + provider + "_ENABLED"], "0")
                self.assertEqual(env["TAU_ALPACA_PAPER_ENABLED"], "1")
                self.assertEqual(env["TAU_ALPACA_PAPER_MAX_ORDER_USD"], "500")

    def test_only_fixed_schema_server_and_verification_commands_are_available(self):
        for mode in entry.MODES:
            invocation = entry.command(mode)
            self.assertEqual(invocation[:5], [entry.PYTHON, "-I", "-B", "-u", "-c"])
            self.assertNotIn("app.worker", invocation[-1])
            self.assertNotIn("app.engine", invocation[-1])
        self.assertIn("'app.schema'", entry.command("schema")[-1])
        self.assertIn("'app.server'", entry.command("web")[-1])
        self.assertIn("paper_staging_smoke.py", entry.command("verify")[-1])
        for mode in ("engine", "agents", "bash", "web;evil", ""):
            with self.assertRaises(entry.StagingError):
                entry.command(mode)

    def test_private_secret_files_are_validated_without_following_symlinks(self):
        with tempfile.TemporaryDirectory(prefix="tau-entry-synthetic-") as directory:
            root = Path(directory)
            path = root / "mysql_password"
            path.write_text(fixture_secrets()["mysql_password"])
            path.chmod(0o600)
            with patch.object(entry, "SECRET_ROOT", root):
                self.assertTrue(entry.read_secret("mysql_password") == fixture_secrets()["mysql_password"])
                path.chmod(0o644)
                with self.assertRaisesRegex(entry.StagingError, "unsafe_secret_file"):
                    entry.read_secret("mysql_password")
                path.chmod(0o600)
                destination = root / "unchanged"
                path.rename(destination)
                path.symlink_to(destination)
                with self.assertRaisesRegex(entry.StagingError, "unsafe_secret_file"):
                    entry.read_secret("mysql_password")
                with self.assertRaisesRegex(entry.StagingError, "unrecognized_secret_file"):
                    entry.read_secret("mysql_root_password")

    def test_bootstrap_drops_groups_gid_uid_then_executes_clean_environment(self):
        order = []
        captured = {}

        def execute(path, argv, env):
            order.append("exec")
            captured.update(path=path, argv=argv, env=env)
            raise SystemExit(0)

        with patch.object(entry.os, "geteuid", return_value=0), \
                patch.dict(entry.os.environ, {"TAU_STAGING_CONTAINER": "isolated-compose-v1"}, clear=True), \
                patch.object(entry, "read_secret", side_effect=lambda name: fixture_secrets()[name]), \
                patch.object(entry.os, "chdir"), \
                patch.object(entry.os, "setgroups", side_effect=lambda groups: order.append(("groups", groups))), \
                patch.object(entry.os, "setgid", side_effect=lambda gid: order.append(("gid", gid))), \
                patch.object(entry.os, "setuid", side_effect=lambda uid: order.append(("uid", uid))), \
                patch.object(entry.os, "execve", execute):
            with self.assertRaises(SystemExit):
                entry.main(["verify"])
        self.assertEqual(order, [("groups", []), ("gid", 10001), ("uid", 10001), "exec"])
        self.assertEqual(captured["env"]["APP_DEV_LOGIN"], "1")
        self.assertNotIn("TAU_STAGING_CONTAINER", captured["env"])

    def test_invalid_mode_outputs_only_a_fixed_safe_failure(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(entry.main(["unreviewed-command"]), 1)
        self.assertEqual(json.loads(output.getvalue()), {"status": "failed", "check": "staging_bootstrap"})


class ComposeContractTests(unittest.TestCase):
    def setUp(self):
        # JSON is a YAML subset accepted by Compose; using it here allows exact
        # structural checks with stdlib, without another developer dependency.
        self.compose = json.loads((HERE / "staging/compose.yml").read_text())

    def test_only_private_project_network_volume_and_web_loopback_port_exist(self):
        services = self.compose["services"]
        self.assertEqual(set(services), {"db", "schema", "web", "verify"})
        self.assertEqual(self.compose["networks"], {"isolated": {"internal": True}})
        self.assertEqual(self.compose["volumes"], {"mysql-data": {}})
        for name, service in services.items():
            self.assertEqual(service["networks"], ["isolated"])
            self.assertEqual(service.get("ports", []), ["127.0.0.1:18090:8090"] if name == "web" else [])
            self.assertFalse(any(key in service for key in ("env_file", "network_mode", "privileged", "container_name")))
        self.assertEqual(services["db"]["volumes"], ["mysql-data:/var/lib/mysql"])
        self.assertEqual(services["db"]["image"], "mysql:8.4")

    def test_schema_gates_both_application_services_and_root_password_is_db_only(self):
        services = self.compose["services"]
        self.assertEqual(services["schema"]["depends_on"], {"db": {"condition": "service_healthy"}})
        for mode in ("schema", "web", "verify"):
            service = services[mode]
            self.assertEqual(service["command"], [mode])
            self.assertEqual(service["secrets"], ["mysql_password", "app_secret_key"])
            self.assertEqual(service["build"], {"context": "..", "dockerfile": "staging/Dockerfile"})
            self.assertTrue(service["read_only"])
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertEqual(service["cap_add"], ["DAC_OVERRIDE", "SETUID", "SETGID"])
            self.assertEqual(service["security_opt"], ["no-new-privileges:true"])
            if mode != "schema":
                self.assertEqual(service["depends_on"], {"schema": {"condition": "service_completed_successfully"}})
        for name, data in self.compose["secrets"].items():
            self.assertEqual(data, {"file": "./.state/" + name})

    def test_build_uses_explicit_complete_packages_and_ignores_private_context(self):
        dockerfile = (HERE / "staging/Dockerfile").read_text()
        copies = [line for line in dockerfile.splitlines() if line.startswith("COPY ")]
        self.assertEqual(copies, ["COPY requirements.txt requirements.txt", "COPY app/ app/",
                                 "COPY data_pipeline/ data_pipeline/",
                                 "COPY staging/entrypoint.py /usr/local/lib/tau-staging/entrypoint.py",
                                 "COPY scripts/paper_staging_smoke.py scripts/paper_staging_smoke.py"])
        ignored = (HERE / "staging/Dockerfile.dockerignore").read_text().splitlines()
        self.assertIn("**", ignored)
        for expected in ("!app/**", "!data_pipeline/**", "**/.env*", "**/.state/**",
                         "**/credentials/**", "**/*.pem", "**/*.key", "**/.aws/**"):
            self.assertIn(expected, ignored)
        self.assertGreater(ignored.index("**/.env*"), ignored.index("!app/**"))
        self.assertNotIn("/opt/kalshi", dockerfile)


if __name__ == "__main__":
    unittest.main()
