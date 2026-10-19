"""Synthetic offline tests: no actual keys, cloud, services or database."""
import contextlib
import copy
import io
import os
from pathlib import Path
import shlex
import stat
import tempfile
import unittest
from unittest.mock import patch

import paper_runtime_config as config


CREDENTIALS = {"ALPACA_OAUTH_CLIENT_ID": "synthetic-client-id-123456",
               "ALPACA_OAUTH_CLIENT_SECRET": "synthetic-secret_+/=-123456"}
INTERPRETER = "/opt/kalshi/.venv313/bin/python"
PROVIDER = (". /etc/tau/provider-data/market-data.env || exit $?; "
            ". /etc/tau/provider-data/research-data.env || exit $?; "
            + INTERPRETER + " -B -m app.market_data_config check >/dev/null || exit $?; ")


def body(service="recursive-agents", provider=False):
    tail = ("-m app.worker agents >> /opt/kalshi/logs/recursive_agents.log 2>&1"
            if service == "recursive-agents" else
            "-m app.server --host 127.0.0.1 --port 8090 >> /opt/kalshi/logs/recursive_web.log 2>&1")
    return ("set -a; . /opt/kalshi/.env.aws; . /opt/kalshi/.env.app; "
            + (PROVIDER if provider else "") + "set +a; unset AWS_PROFILE; exec "
            + INTERPRETER + " -u " + tail)


def fragment(service="recursive-agents"):
    return ("[Unit]\nDescription=synthetic service\n[Service]\n"
            "WorkingDirectory=/opt/kalshi\nExecStart=/bin/bash -c "
            + shlex.quote(body(service)) + "\nMemoryMax=400M\nNice=5\nRestart=always\n").encode()


def start_dropin(command):
    return ("[Service]\nExecStart=\nExecStart=/bin/bash -c " + shlex.quote(command) + "\n").encode()


class OverlayTests(unittest.TestCase):
    def test_only_fixed_authorized_settings_and_exact_pair_are_rendered(self):
        before = copy.deepcopy(CREDENTIALS)
        raw = config.build_overlay(CREDENTIALS)
        values = dict(shlex.split(line)[0].split("=", 1) for line in raw.decode().splitlines())
        self.assertEqual(values, {**config.SETTINGS, **CREDENTIALS})
        self.assertEqual(CREDENTIALS, before)
        self.assertEqual(values["TAU_ALPACA_PAPER_ENABLED"], "1")
        self.assertEqual(values["TAU_ALPACA_PAPER_MAX_ORDER_USD"], "500")
        self.assertNotIn("APP_SECRET_KEY", values)
        self.assertNotIn("APCA_API_KEY_ID", values)

    def test_unexpected_or_missing_fields_never_enter_overlay(self):
        for value in ({}, {"ALPACA_OAUTH_CLIENT_ID": "synthetic-client"},
                      {**CREDENTIALS, "APP_SECRET_KEY": "synthetic-protected"},
                      {**CREDENTIALS, "TAU_ALPACA_PAPER_MAX_ORDER_USD": "1000000"}, []):
            with self.subTest(fields=type(value).__name__):
                with self.assertRaisesRegex(config.ConfigError, "unexpected_credential_fields"):
                    config.build_overlay(value)

    def test_multiline_control_shell_syntax_and_unbounded_credentials_are_rejected(self):
        invalid = ("", "short", "secret\nAPP_SECRET_KEY=bad", "secret\rvalue", "secret\x00value",
                   "secret\tvalue", "secret with spaces", "$(touch /tmp/should-not-exist)",
                   "`id`-synthetic-secret", "secret';exit 0;#", "secret\"value", "é" * 16,
                   "synthetic" * 513, None, 123)
        for key in config.CREDENTIAL_KEYS:
            for bad in invalid:
                values = {**CREDENTIALS, key: bad}
                with self.subTest(key=key, case=type(bad).__name__):
                    with self.assertRaisesRegex(config.ConfigError, "invalid_oauth_credential") as caught:
                        config.build_overlay(values)
                    self.assertEqual(str(caught.exception), "invalid_oauth_credential")

    def test_protected_baseline_and_existing_provider_flags_survive(self):
        before = {"APP_SECRET_KEY": "synthetic-existing-vault-key", "TAU_MARKET_DATA_PRIMARY": "databento",
                  "TAU_DATABENTO_MAX_COST_USD": "0.10", "TAU_EXA_ENABLED": "1",
                  "TAU_EXA_HISTORICAL_ENABLED": "1", "LIVE_TRADING_PASSWORD": "synthetic-gate",
                  "KALSHI_LIVE_ENABLED": "0", "AWS_REGION": "us-east-1", "MYSQL_HOST": "synthetic-db",
                  "APP_PUBLIC_URL": "https://old.invalid", "TAU_ALPACA_PAPER_ENABLED": "0"}
        after = {**before, **config.SETTINGS, **CREDENTIALS}
        report = config.verify_protected_environment(before, after, CREDENTIALS)
        self.assertTrue(report["protected_settings_unchanged"])
        self.assertTrue(report["oauth_pair_present"])
        self.assertNotIn("synthetic", repr(report))
        for key in before.keys() - config.MANAGED_KEYS:
            modified = {**after, key: "unexpected-value"}
            with self.subTest(key=key):
                with self.assertRaisesRegex(config.ConfigError, "protected_environment_changed"):
                    config.verify_protected_environment(before, modified, CREDENTIALS)

    def test_protected_deletion_or_addition_is_also_a_conflict(self):
        before = {"APP_SECRET_KEY": "synthetic-key"}
        after = {**before, **config.SETTINGS, **CREDENTIALS}
        for changed in ({key: value for key, value in after.items() if key != "APP_SECRET_KEY"},
                        {**after, "LIVE_ENABLED": "1"}):
            with self.assertRaisesRegex(config.ConfigError, "protected_environment_changed"):
                config.verify_protected_environment(before, changed, CREDENTIALS)

    def test_absent_or_wrong_managed_value_cannot_claim_ready(self):
        desired = {**config.SETTINGS, **CREDENTIALS}
        for key in desired:
            with self.subTest(key=key):
                after = {name: value for name, value in desired.items() if name != key}
                with self.assertRaisesRegex(config.ConfigError, "paper_environment_not_ready"):
                    config.verify_protected_environment({}, after, CREDENTIALS)


class UnitTests(unittest.TestCase):
    def test_base_launcher_arguments_resources_and_logging_are_preserved_for_both_services(self):
        for service in config.SERVICES:
            with self.subTest(service=service):
                original = fragment(service)
                resource_path = "/etc/systemd/system/" + service + ".service.d/40-memory.conf"
                resources = b"[Service]\nMemoryMax=400M\nNice=5\nKillMode=mixed\nTimeoutStopSec=90\n"
                dropins = {resource_path: resources}
                plan = config.plan_unit(service, original, dropins)
                insertion = ". /etc/tau/alpaca-paper/paper.env || exit $?; "
                self.assertEqual(plan["body"], body(service).replace("set +a;", insertion + "set +a;"))
                self.assertFalse(plan["provider_preflight_preserved"])
                self.assertFalse(plan["resources_changed"])
                self.assertEqual(original, fragment(service))
                self.assertEqual(dropins[resource_path], resources)
                self.assertNotIn(b"MemoryMax", plan["drop_bytes"])
                self.assertEqual(plan["drop_path"].name, "99-tau-alpaca-paper.conf")

    def test_pending_provider_override_is_preserved_byte_for_byte(self):
        path = "/etc/systemd/system/recursive-agents.service.d/90-tau-provider-data.conf"
        provider_drop = start_dropin(body(provider=True))
        original = fragment()
        plan = config.plan_unit("recursive-agents", original, {path: provider_drop})
        insertion = ". /etc/tau/alpaca-paper/paper.env || exit $?; "
        self.assertTrue(plan["provider_preflight_preserved"])
        self.assertIn(PROVIDER + insertion + "set +a;", plan["body"])
        self.assertEqual(plan["body"].replace(insertion, ""), body(provider=True))
        self.assertEqual(provider_drop, start_dropin(body(provider=True)))

    def test_repeated_planning_is_idempotent_and_does_not_stack_sources(self):
        provider = "/etc/systemd/system/recursive-agents.service.d/90-tau-provider-data.conf"
        source = {provider: start_dropin(body(provider=True))}
        first = config.plan_unit("recursive-agents", fragment(), source)
        source[str(first["drop_path"])] = first["drop_bytes"]
        second = config.plan_unit("recursive-agents", fragment(), source)
        self.assertEqual(first["drop_bytes"], second["drop_bytes"])
        self.assertEqual(second["body"].count(str(config.OVERLAY)), 1)
        self.assertEqual(second["body"].count("app.market_data_config check"), 1)

    def test_same_basename_precedence_matches_systemd(self):
        lower = "/usr/lib/systemd/system/recursive-agents.service.d/90-provider.conf"
        higher = "/etc/systemd/system/recursive-agents.service.d/90-provider.conf"
        plan = config.plan_unit("recursive-agents", fragment(),
                                {lower: b"[Service]\nExecStart=/unknown/command\n",
                                 higher: start_dropin(body(provider=True))})
        self.assertTrue(plan["provider_preflight_preserved"])
        self.assertEqual(plan["source_paths"], [higher])

    def test_later_exec_override_is_rejected_even_when_its_body_is_recognized(self):
        path = "/etc/systemd/system/recursive-agents.service.d/override.conf"
        with self.assertRaisesRegex(config.ConfigError, "later_exec_start_override"):
            config.plan_unit("recursive-agents", fragment(), {path: start_dropin(body())})

    def test_existing_own_dropin_cannot_hide_added_resource_or_environment_changes(self):
        first = config.plan_unit("recursive-agents", fragment(), {})
        modified = first["drop_bytes"] + b"Environment=LIVE_ENABLED=1\n"
        with self.assertRaisesRegex(config.ConfigError, "existing_paper_dropin_changed"):
            config.plan_unit("recursive-agents", fragment(), {str(first["drop_path"]): modified})

    def test_unknown_shell_interpreter_arguments_control_syntax_or_preflight_are_rejected(self):
        commands = [body().replace(".env.app", ".env.unreviewed"),
                    body().replace(".venv313", ".venv"), body().replace("app.worker agents", "app.worker engine"),
                    body() + "; echo unreviewed", body().replace("set +a;", "set +a; set +a;"),
                    body().replace("set +a;", "curl https://unreviewed.invalid; set +a;"),
                    body(provider=True).replace("market_data_config check", "market_data_config configure"),
                    body().replace(".env.aws;", ".env.app;"),
                    body().replace("recursive_agents.log", "recursive_other.log")]
        for command in commands:
            with self.subTest(case=commands.index(command)):
                with self.assertRaises(config.ConfigError):
                    config.plan_unit("recursive-agents", start_dropin(command), {})
        with self.assertRaisesRegex(config.ConfigError, "unrecognized_launcher"):
            config.plan_unit("recursive-agents", start_dropin(body()).replace(b"/bin/bash", b"/bin/sh"), {})

    def test_unknown_service_dropin_path_multi_start_or_continuation_is_rejected(self):
        with self.assertRaisesRegex(config.ConfigError, "unsupported_service"):
            config.plan_unit("recursive-engine", fragment(), {})
        for path in ("90.conf", "/etc/systemd/system/recursive-engine.service.d/90.conf",
                     "/etc/systemd/system/recursive-agents.service.d/../90.conf"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(config.ConfigError, "unrecognized_dropin_path"):
                    config.plan_unit("recursive-agents", fragment(), {path: b"[Service]\nNice=5\n"})
        with self.assertRaisesRegex(config.ConfigError, "unexpected_exec_start_count"):
            config.plan_unit("recursive-agents", fragment() + b"ExecStart=/bin/true\n", {})
        with self.assertRaisesRegex(config.ConfigError, "unrecognized_exec_start"):
            config.plan_unit("recursive-agents", fragment().replace(b"/bin/bash", b"/bin/ba\\\nsh"), {})


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tau-paper-synthetic-")
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.config_root = self.root / "etc/tau/alpaca-paper"
        self.overlay = self.config_root / "paper.env"
        self.systemd = self.root / "etc/systemd/system"
        self.systemd.mkdir(parents=True, mode=0o755)
        self.patchers = [patch.object(config, "ROOT_UID", os.geteuid()),
                         patch.object(config, "CONFIG_ROOT", self.config_root),
                         patch.object(config, "OVERLAY", self.overlay),
                         patch.object(config, "drop_path", lambda service: self.systemd / (service + ".service.d") / config.DROP_NAME),
                         patch.object(config, "_directory_chain", self.chain)]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    def chain(self, path):
        # Actual file checks below a controlled synthetic root; production walks
        # and verifies every real ancestor from / with no such test substitution.
        relative = path.relative_to(self.root)
        return (self.root, *(self.root.joinpath(*relative.parts[:index])
                             for index in range(1, len(relative.parts) + 1)))

    def test_new_private_files_have_exact_permissions_and_rollback_removes_only_own_files(self):
        config.prepare_directories()
        self.assertEqual(stat.S_IMODE(self.config_root.stat().st_mode), 0o700)
        base = self.root / "opt/kalshi/.env.app"
        base.parent.mkdir(parents=True)
        base.write_bytes(b"APP_SECRET_KEY=synthetic-protected-vault\n")
        before = (base.read_bytes(), base.stat().st_mode, base.stat().st_mtime_ns)
        raw = config.build_overlay(CREDENTIALS)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            saved = config.atomic_write(self.overlay, raw, None)
        self.assertEqual(captured.getvalue(), "")
        self.assertEqual(self.overlay.read_bytes(), raw)
        self.assertEqual(stat.S_IMODE(self.overlay.stat().st_mode), 0o600)
        self.assertEqual(self.overlay.stat().st_uid, os.geteuid())
        self.assertIsNone(config.restore(self.overlay, None, saved))
        self.assertFalse(self.overlay.exists())
        self.assertEqual(before, (base.read_bytes(), base.stat().st_mode, base.stat().st_mtime_ns))

    def test_rollback_restores_prior_private_bytes_without_touching_pending_provider_dropin(self):
        config.prepare_directories()
        target = config.drop_path("recursive-agents")
        provider = target.parent / "90-tau-provider-data.conf"
        provider.write_bytes(start_dropin(body(provider=True)))
        prior_provider = provider.read_bytes()
        first = config.atomic_write(self.overlay, b"synthetic-before=value\n", None)
        installed = config.atomic_write(self.overlay, config.build_overlay(CREDENTIALS), first)
        restored = config.restore(self.overlay, first, installed)
        self.assertEqual(restored["raw"], first["raw"])
        self.assertEqual(provider.read_bytes(), prior_provider)
        self.assertEqual(stat.S_IMODE(self.overlay.stat().st_mode), 0o600)

    def test_own_dropin_apply_and_rollback_preserve_fragment_and_provider_override(self):
        config.prepare_directories()
        target = config.drop_path("recursive-agents")
        provider = target.parent / "90-tau-provider-data.conf"
        provider.write_bytes(start_dropin(body(provider=True)))
        original_provider = provider.read_bytes()
        original_fragment = fragment()
        # Pure plans require production unit paths; filesystem primitives below
        # are redirected only to this synthetic controlled root.
        production_provider = "/etc/systemd/system/recursive-agents.service.d/90-tau-provider-data.conf"
        plan = config.plan_unit("recursive-agents", original_fragment,
                                {production_provider: original_provider})
        saved = config.atomic_write(target, plan["drop_bytes"], None)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertIn(b"app.market_data_config check", target.read_bytes())
        self.assertEqual(provider.read_bytes(), original_provider)
        config.restore(target, None, saved)
        self.assertFalse(target.exists())
        self.assertEqual(provider.read_bytes(), original_provider)
        self.assertEqual(original_fragment, fragment())

    def test_concurrent_operator_change_is_not_overwritten_or_rolled_back(self):
        config.prepare_directories()
        first = config.atomic_write(self.overlay, b"synthetic-first=value\n", None)
        current = config.atomic_write(self.overlay, b"synthetic-operator=value\n", first)
        with self.assertRaisesRegex(config.ConfigError, "concurrent_managed_file_change"):
            config.atomic_write(self.overlay, b"synthetic-stale=value\n", first)
        with self.assertRaisesRegex(config.ConfigError, "concurrent_managed_file_change"):
            config.restore(self.overlay, None, first)
        self.assertEqual(config.snapshot(self.overlay), current)

    def test_symlinks_hardlinks_unsafe_modes_and_non_root_metadata_fail_closed(self):
        config.prepare_directories()
        target = self.config_root / "synthetic-target"
        target.write_bytes(b"synthetic-never-change\n")
        target.chmod(0o600)
        self.overlay.symlink_to(target)
        with self.assertRaisesRegex(config.ConfigError, "unsafe_managed_file"):
            config.snapshot(self.overlay)
        self.overlay.unlink()
        os.link(target, self.overlay)
        with self.assertRaisesRegex(config.ConfigError, "unsafe_managed_file"):
            config.snapshot(self.overlay)
        self.overlay.unlink()
        self.overlay.write_bytes(b"synthetic-private\n")
        self.overlay.chmod(0o644)
        with self.assertRaisesRegex(config.ConfigError, "unsafe_managed_file"):
            config.snapshot(self.overlay)
        self.overlay.chmod(0o600)
        self.config_root.chmod(0o755)
        with self.assertRaisesRegex(config.ConfigError, "unsafe_private_directory"):
            config.snapshot(self.overlay)
        self.config_root.chmod(0o700)
        with patch.object(config, "ROOT_UID", os.geteuid() + 1):
            with self.assertRaisesRegex(config.ConfigError, "unsafe_directory"):
                config.snapshot(self.overlay)
        self.assertEqual(target.read_bytes(), b"synthetic-never-change\n")

    def test_base_and_provider_files_cannot_be_read_or_written_by_helper(self):
        config.prepare_directories()
        for path in (self.root / "opt/kalshi/.env.app", self.root / "opt/kalshi/.env.aws",
                     self.root / "etc/tau/provider-data/market-data.env",
                     config.drop_path("recursive-agents").parent / "90-tau-provider-data.conf"):
            with self.subTest(path=path.name):
                with self.assertRaisesRegex(config.ConfigError, "unrecognized_managed_path"):
                    config.snapshot(path)
                with self.assertRaisesRegex(config.ConfigError, "unrecognized_managed_path"):
                    config.atomic_write(path, b"synthetic\n", None)


if __name__ == "__main__":
    unittest.main()
