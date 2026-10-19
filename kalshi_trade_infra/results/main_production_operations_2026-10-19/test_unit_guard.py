"""Synthetic systemd fixtures only; never executes systemctl or touches /opt."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import shlex
import subprocess
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("reviewed_unit_guard", Path(__file__).with_name("unit_guard.py"))
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def unit_bytes(service):
    commands = {
        "recursive-web": "app.server >> /opt/kalshi/logs/recursive_web.log 2>&1",
        "recursive-agents": "app.worker agents >> /opt/kalshi/logs/recursive_agents.log 2>&1",
        "recursive-engine": "app.worker engine >> /opt/kalshi/logs/recursive_engine.log 2>&1",
        "recursive-history": "app.market_history >> /opt/kalshi/logs/recursive_history.log 2>&1",
        "kalshi-live-engine": "data_pipeline.live_trading_engine >> /opt/kalshi/live_trading_engine.log 2>&1",
    }
    if service == "kalshi-live-engine":
        body = ("set -a; . /opt/kalshi/.env.aws; [ -f /opt/kalshi/.env ] && . /opt/kalshi/.env; "
                "set +a; exec /opt/kalshi/.venv/bin/python -u -m " + commands[service])
    else:
        body = ("set -a; . /opt/kalshi/.env.aws; . /opt/kalshi/.env.app; set +a; "
                "unset AWS_PROFILE; exec " + guard.INTERPRETER + " -u -m " + commands[service])
    result = ("[Unit]\nDescription=Synthetic unit\nAfter=network-online.target\nWants=network-online.target\n"
              "[Service]\nType=simple\nWorkingDirectory=/opt/kalshi\n"
              "ExecStart=/bin/bash -c " + shlex.quote(body) + "\nRestart=always\nRestartSec=10\n"
              "StartLimitIntervalSec=300\nStartLimitBurst=10\nKillSignal=SIGTERM\nTimeoutStopSec=30\n")
    if service != "kalshi-live-engine":
        result += "MemoryMax=" + ("400M" if service in guard.TARGETS else "250M") + "\nNice=5\n"
    return (result + "[Install]\nWantedBy=multi-user.target\n").encode()


def drop_bytes(command):
    # Only these synthetic fixtures contain commands, not private environment.
    path, argv, ignore = command
    launcher, flag, body = argv.split(" ", 2)
    return ("[Service]\nExecStart=\nExecStart=" + launcher + " " + flag + " " + shlex.quote(body) + "\n").encode()


def shown(command, pid="100", stamp="Mon 2026-10-19 10:31:04 UTC"):
    path, argv, ignore = command
    return ("{ path=" + path + " ; argv[]=" + argv + " ; ignore_errors=" + ignore
            + " ; start_time=[" + stamp + "] ; stop_time=[n/a] ; pid=" + pid
            + " ; code=(null) ; status=0/0 }")


class UnitGuardTests(unittest.TestCase):
    def setUp(self):
        self.files = {}
        self.units = {}
        self.plans = {}
        self.env = {"APP_AGENT_CONCURRENCY": "2", "APP_SECRET_KEY": "private-process-value"}
        for number, service in enumerate(guard.SERVICES, 101):
            raw = unit_bytes(service)
            path = "/etc/systemd/system/" + service + ".service"
            self.files[path] = raw
            inactive = service == "kalshi-live-engine"
            self.units[service] = {
                "Type": "simple", "MainPID": "0" if inactive else str(number),
                "ActiveState": "inactive" if inactive else "active", "FragmentPath": path,
                "DropInPaths": "", "NeedDaemonReload": "no", "Restart": "always", "RestartUSec": "10s",
                "TimeoutStartUSec": "1min 30s", "TimeoutStopUSec": "30s", "MemoryHigh": "infinity",
                "MemoryMax": "infinity" if inactive else "419430400" if service in guard.TARGETS else "262144000",
                "MemorySwapMax": "infinity", "Nice": "0" if inactive else "5", "KillMode": "control-group",
                "KillSignal": "15", "WorkingDirectory": "/opt/kalshi", "User": "", "Group": "",
                "EnvironmentFiles": "", "EnvironmentSHA256": guard.EMPTY_ENV,
                "ExecStart": shown(guard._command(raw), "0" if inactive else str(number)),
            }
        service = "recursive-agents"
        base = guard._command(self.files[self.units[service]["FragmentPath"]])
        provider = (base[0], base[1].replace("set +a;", guard.PROVIDER + "set +a;", 1), base[2])
        self.files["/etc/systemd/system/recursive-agents.service.d/90-tau-provider-data.conf"] = drop_bytes(provider)
        self.units[service]["NeedDaemonReload"] = "yes"
        self.refresh_manifest()
        for service in guard.TARGETS:
            saved = {Path(p): r for p, r in self.files.items()
                     if p == self.units[service]["FragmentPath"] or Path(p).parent.name == service + ".service.d"}
            selected = guard._drops(service, self.files)
            command = guard._command(selected[-1][1], dropin=True) if selected else guard._command(saved[Path(self.units[service]["FragmentPath"])])
            desired = (command[0], command[1].replace("set +a;", guard.PAPER + "set +a;", 1), command[2])
            raw = drop_bytes(desired)
            body = desired[1].split(" ", 2)[2]
            self.plans[service] = ({"service": service, "body": body, "drop_bytes": raw,
                                    "drop_path": Path("/etc/systemd/system/" + service + ".service.d/" + guard.DROP_NAME)},
                                   saved, copy.deepcopy(self.units[service]))
        self.show_patch = patch.object(guard, "_show", side_effect=lambda s: copy.deepcopy(self.units[s]))
        self.inventory_patch = patch.object(guard, "_inventory", side_effect=lambda units: copy.deepcopy(self.files))
        self.show_patch.start()
        self.inventory_patch.start()
        self.addCleanup(self.show_patch.stop)
        self.addCleanup(self.inventory_patch.stop)

    def refresh_manifest(self):
        self.manifest = {"units": copy.deepcopy(self.units), "unit_hashes": guard._hashes(self.files)}
        for values in self.manifest["units"].values():
            values.pop("Type")

    def before(self):
        return guard.check_before(self.plans, self.manifest, self.env)

    def reload(self):
        for service in guard.TARGETS:
            plan = self.plans[service][0]
            self.files[str(plan["drop_path"])] = plan["drop_bytes"]
            self.units[service].update(
                MainPID="0", ActiveState="inactive", NeedDaemonReload="no",
                ExecStart=shown(guard._command(plan["drop_bytes"], dropin=True), "0", "n/a"),
                DropInPaths=" ".join(p for p, _ in guard._drops(service, self.files)),
            )

    def assert_code(self, code, operation=None):
        with self.assertRaisesRegex(guard.UnitGuardError, "^" + code + "$"):
            (operation or self.before)()

    def test_capture_pending_provider_and_post_reload_accepted(self):
        baseline = self.before()
        self.assertEqual(baseline["units"]["recursive-agents"]["MemoryMax"], "419430400")
        self.assertNotIn("APP_SECRET_KEY", repr(baseline))
        self.assertNotIn(self.env["APP_SECRET_KEY"], repr(baseline))
        self.reload()
        guard.check_after_reload(self.plans, baseline)

    def test_optional_final_check_keeps_non_targets_and_accepts_new_target_pids(self):
        baseline = self.before()
        self.reload()
        for service in guard.TARGETS:
            self.units[service].update(MainPID="300", ActiveState="active")
        guard.check_after_start(self.plans, baseline)

    def test_fresh_pid_replaces_historical_capture_pid_in_continuity_baseline(self):
        self.units["recursive-history"]["MainPID"] = "999"
        baseline = self.before()
        self.assertEqual(baseline["units"]["recursive-history"]["MainPID"], "999")
        self.assertNotEqual(self.manifest["units"]["recursive-history"]["MainPID"], "999")
        self.reload()
        guard.check_after_reload(self.plans, baseline)
        self.units["recursive-history"]["MainPID"] = "1000"
        self.assert_code("unrelated_service_state_changed", lambda: guard.check_after_reload(self.plans, baseline))

    def test_fresh_target_pid_accepted_but_recovery_rejects_a_later_new_pid(self):
        self.units["recursive-web"]["MainPID"] = "999"
        baseline = self.before()
        self.assertEqual(baseline["units"]["recursive-web"]["MainPID"], "999")
        self.assertTrue(self.recovery(baseline))
        self.units["recursive-web"]["MainPID"] = "1000"
        self.assertFalse(self.recovery(baseline))

    def test_nonvolatile_control_drift_still_rejected_with_safe_diagnostic_fields(self):
        service = "recursive-history"
        old_pid = int(self.units[service]["MainPID"])
        self.units[service].update(MainPID="999", MemoryMax="infinity", User="private-user-value")
        with self.assertRaises(guard.UnitGuardError) as caught:
            self.before()
        error = caught.exception
        self.assertEqual(error.code, "loaded_unit_changed_since_capture")
        self.assertEqual(error.details, {"service": service, "fields_changed": ["MemoryMax", "User"],
                                        "previous_main_pid": old_pid, "current_main_pid": 999})
        self.assertNotIn("private-user-value", repr(error.details))

    def test_environment_hash_and_active_state_remain_capture_bound(self):
        service = "recursive-web"
        for key, value in (("EnvironmentSHA256", "private-hash-value"), ("ActiveState", "inactive")):
            with self.subTest(key=key):
                original = self.units[service][key]
                self.units[service][key] = value
                with self.assertRaises(guard.UnitGuardError) as caught:
                    self.before()
                self.assertEqual(caught.exception.details["fields_changed"], [key])
                self.assertNotIn(value, repr(caught.exception.details))
                self.units[service][key] = original

    def test_exec_drift_diagnostic_omits_command_and_private_values(self):
        service = "recursive-web"
        self.units[service]["ExecStart"] = self.units[service]["ExecStart"].replace("app.server", "app.server --private-value")
        with self.assertRaises(guard.UnitGuardError) as caught:
            self.before()
        self.assertEqual(caught.exception.code, "loaded_exec_changed_since_capture")
        self.assertEqual(caught.exception.details["fields_changed"], ["ExecStart"])
        self.assertNotIn("private-value", repr(caught.exception.details))
        self.assertNotIn("/bin/bash", repr(caught.exception.details))

    def test_diagnostic_pid_values_are_numeric_or_absent(self):
        self.manifest["units"]["recursive-web"]["MainPID"] = "SECRET=not-a-pid"
        self.units["recursive-web"]["MemoryMax"] = "infinity"
        with self.assertRaises(guard.UnitGuardError) as caught:
            self.before()
        self.assertIsNone(caught.exception.details["previous_main_pid"])
        self.assertIsInstance(caught.exception.details["current_main_pid"], int)
        self.assertNotIn("SECRET", repr(caught.exception.details))

    def test_different_volatile_exec_metadata_ignored(self):
        service = "recursive-web"
        self.units[service]["ExecStart"] = shown(guard._command(self.files[self.units[service]["FragmentPath"]]), "999", "other time")
        self.before()

    def test_worker_concurrency_must_be_explicit_two(self):
        for value in (None, "1", "3", 2):
            with self.subTest(value=value):
                self.env["APP_AGENT_CONCURRENCY"] = value
                self.assert_code("worker_concurrency_not_two")

    def test_agent_resource_cannot_adopt_larger_memory_even_if_capture_matches(self):
        self.units["recursive-agents"]["MemoryMax"] = "838860800"
        self.refresh_manifest()
        self.assert_code("loaded_unit_controls_not_reviewed")

    def test_fragment_resource_edit_rejected_against_loaded_baseline(self):
        path = self.units["recursive-agents"]["FragmentPath"]
        self.files[path] = self.files[path].replace(b"MemoryMax=400M", b"MemoryMax=800M")
        self.manifest["unit_hashes"] = guard._hashes(self.files)
        self.plans["recursive-agents"][1][Path(path)] = self.files[path]
        self.assert_code("disk_unit_controls_not_reviewed")

    def test_removing_resource_directive_also_rejected(self):
        path = self.units["recursive-web"]["FragmentPath"]
        self.files[path] = self.files[path].replace(b"MemoryMax=400M\n", b"")
        self.manifest["unit_hashes"] = guard._hashes(self.files)
        self.plans["recursive-web"][1][Path(path)] = self.files[path]
        self.assert_code("disk_unit_controls_not_reviewed")

    def test_pending_environment_in_known_dropin_rejected(self):
        path = "/etc/systemd/system/recursive-agents.service.d/90-tau-provider-data.conf"
        self.files[path] += b"Environment=APP_AGENT_CONCURRENCY=3\n"
        self.manifest["unit_hashes"] = guard._hashes(self.files)
        self.plans["recursive-agents"][1][Path(path)] = self.files[path]
        self.assert_code("dropin_changes_non_exec_controls")

    def test_pending_environment_in_fragment_rejected(self):
        path = self.units["recursive-web"]["FragmentPath"]
        self.files[path] = self.files[path].replace(b"[Service]\n", b"[Service]\nEnvironment=SECRET=private\n")
        self.manifest["unit_hashes"] = guard._hashes(self.files)
        self.plans["recursive-web"][1][Path(path)] = self.files[path]
        self.assert_code("disk_unit_controls_not_reviewed")

    def test_unrelated_pending_reload_rejected(self):
        self.units["recursive-history"]["NeedDaemonReload"] = "yes"
        self.refresh_manifest()
        self.assert_code("unrelated_unit_pending_reload")

    def test_changed_file_and_unexpected_extra_file_rejected(self):
        self.files["/etc/systemd/system/recursive-web.service.d/95-new.conf"] = b"[Service]\nNice=-5\n"
        self.assert_code("unit_files_changed_since_capture")

    def test_unreviewed_dropin_rejected_even_if_hash_added(self):
        self.files["/etc/systemd/system/recursive-engine.service.d/90-tau-provider-data.conf"] = b"[Service]\nExecStart=\nExecStart=/bin/true\n"
        self.manifest["unit_hashes"] = guard._hashes(self.files)
        self.assert_code("unreviewed_unit_dropin")

    def test_saved_plan_snapshot_must_match_actual_disk(self):
        self.plans["recursive-web"][1].clear()
        self.assert_code("planned_unit_snapshot_changed")

    def test_desired_interpreter_cannot_change(self):
        plan = self.plans["recursive-web"][0]
        plan["drop_bytes"] = plan["drop_bytes"].replace(b".venv313/", b".venv/")
        plan["body"] = plan["body"].replace(".venv313/", ".venv/")
        self.assert_code("target_exec_changed_beyond_approved_overlays")

    def test_house_inactive_original_interpreter_remains_accepted(self):
        baseline = self.before()
        self.assertIn("/opt/kalshi/.venv/bin/python", baseline["units"]["kalshi-live-engine"]["ExecStart"])

    def test_captured_empty_environment_file_property_may_be_omitted(self):
        for values in self.manifest["units"].values():
            values.pop("EnvironmentFiles")
        self.before()

    def test_non_target_pid_change_after_reload_rejected(self):
        baseline = self.before()
        self.reload()
        self.units["recursive-engine"]["MainPID"] = "900"
        self.assert_code("unrelated_service_state_changed", lambda: guard.check_after_reload(self.plans, baseline))

    def test_inactive_house_must_stay_inactive_after_reload(self):
        baseline = self.before()
        self.reload()
        self.units["kalshi-live-engine"].update(MainPID="900", ActiveState="active")
        self.assert_code("unrelated_service_state_changed", lambda: guard.check_after_reload(self.plans, baseline))

    def test_non_target_resource_adoption_after_reload_rejected(self):
        baseline = self.before()
        self.reload()
        self.units["recursive-history"]["Nice"] = "0"
        self.assert_code("loaded_unit_controls_changed_after_reload", lambda: guard.check_after_reload(self.plans, baseline))

    def test_environment_hash_adoption_after_reload_rejected_without_value(self):
        baseline = self.before()
        self.reload()
        self.units["recursive-agents"]["EnvironmentSHA256"] = hashlib.sha256(b"SECRET=private").hexdigest()
        self.assert_code("loaded_unit_controls_changed_after_reload", lambda: guard.check_after_reload(self.plans, baseline))

    def test_changed_desired_loaded_exec_rejected_before_start(self):
        baseline = self.before()
        self.reload()
        self.units["recursive-web"]["ExecStart"] = self.units["recursive-web"]["ExecStart"].replace("app.server", "app.worker")
        self.assert_code("loaded_exec_not_approved_after_reload", lambda: guard.check_after_reload(self.plans, baseline))

    def test_missing_provider_loaded_dropin_rejected_before_start(self):
        baseline = self.before()
        self.reload()
        self.units["recursive-agents"]["DropInPaths"] = str(self.plans["recursive-agents"][0]["drop_path"])
        self.assert_code("loaded_dropins_not_approved_after_reload", lambda: guard.check_after_reload(self.plans, baseline))

    def test_target_must_remain_stopped_until_after_reload_guard(self):
        baseline = self.before()
        self.reload()
        self.units["recursive-agents"].update(MainPID="500", ActiveState="active")
        self.assert_code("target_service_not_stopped", lambda: guard.check_after_reload(self.plans, baseline))

    def test_cutover_file_drift_rejected(self):
        baseline = self.before()
        self.reload()
        self.files[self.units["recursive-engine"]["FragmentPath"]] += b"# concurrent edit\n"
        self.assert_code("unit_files_changed_during_cutover", lambda: guard.check_after_reload(self.plans, baseline))

    def test_in_memory_plan_mutation_rejected(self):
        baseline = self.before()
        self.reload()
        self.plans["recursive-web"][0]["drop_bytes"] = self.plans["recursive-web"][0]["drop_bytes"].replace(b"app.server", b"app.worker")
        self.assert_code("unit_plan_changed_during_cutover", lambda: guard.check_after_reload(self.plans, baseline))

    def test_loaded_exec_ignores_only_metadata_and_keeps_semicolons(self):
        command = guard._command(unit_bytes("recursive-web"))
        self.assertEqual(guard._loaded_exec(shown(command)), command)
        self.assertNotEqual(command, guard._loaded_exec(shown(command).replace("set -a;", "set +a;", 1)))

    def test_duplicate_exec_or_hidden_directive_not_accepted(self):
        for extra in (b"Nice=0\n", b"[Unit]\nAfter=evil.service\n", b"ExecStart=/bin/true\n"):
            with self.subTest(extra=extra):
                with self.assertRaises(guard.UnitGuardError):
                    guard._command(self.plans["recursive-web"][0]["drop_bytes"] + extra, dropin=True)

    def test_show_hashes_environment_and_never_retains_it(self):
        values = copy.deepcopy(self.units["recursive-web"])
        values.pop("EnvironmentSHA256")
        values["Environment"] = "SECRET=hidden-test-value"
        raw = ("\n".join(k + "=" + v for k, v in values.items()) + "\n").encode()
        self.show_patch.stop()
        with patch.object(guard.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, b"")) as run:
            actual = guard._show("recursive-web")
        self.show_patch.start()
        self.assertNotIn("Environment", actual)
        self.assertNotIn("hidden-test-value", repr(actual))
        self.assertIn("EnvironmentSHA256", actual)
        self.assertEqual(run.call_args.args[0][:3], ["systemctl", "show", "recursive-web"])

    def test_show_exception_sanitized(self):
        self.show_patch.stop()
        with patch.object(guard.subprocess, "run", side_effect=RuntimeError("SECRET=hidden-test-value")):
            self.assert_code("unit_property_read_failed", lambda: guard._show("recursive-web"))
        self.show_patch.start()

    def test_show_omitted_empty_environment_properties_normalized(self):
        values = copy.deepcopy(self.units["recursive-web"])
        values.pop("EnvironmentSHA256")
        values.pop("EnvironmentFiles")
        raw = ("\n".join(k + "=" + v for k, v in values.items()) + "\n").encode()
        self.show_patch.stop()
        with patch.object(guard.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, b"")):
            actual = guard._show("recursive-web")
        self.show_patch.start()
        self.assertEqual(actual["EnvironmentFiles"], "")
        self.assertEqual(actual["EnvironmentSHA256"], guard.EMPTY_ENV)

    def recovery(self, baseline, attempts=None):
        return guard.recovery_dependencies_unchanged(self.plans, baseline, attempts or {})

    def attempted_drops(self):
        return {plan["drop_path"]: plan["drop_bytes"] for plan, _, _ in self.plans.values()}

    def test_recovery_before_reload_allows_partial_stop_and_no_writes(self):
        baseline = self.before()
        self.units["recursive-web"].update(MainPID="0", ActiveState="inactive")
        self.assertTrue(self.recovery(baseline))

    def test_recovery_before_reload_allows_one_exact_attempted_dropin(self):
        baseline = self.before()
        plan = self.plans["recursive-web"][0]
        self.files[str(plan["drop_path"])] = plan["drop_bytes"]
        self.units["recursive-web"].update(MainPID="0", ActiveState="inactive", NeedDaemonReload="yes")
        self.assertTrue(self.recovery(baseline, {plan["drop_path"]: plan["drop_bytes"]}))

    def test_recovery_after_reload_accepts_exact_own_writes_and_stopped_targets(self):
        baseline = self.before()
        self.reload()
        attempts = self.attempted_drops()
        attempts[Path("/etc/tau/alpaca-paper/paper.env")] = b"PRIVATE=not-retained-by-guard\n"
        self.assertTrue(self.recovery(baseline, attempts))

    def test_recovery_rejects_unrecorded_own_dropin(self):
        baseline = self.before()
        self.reload()
        self.assertFalse(self.recovery(baseline))

    def test_recovery_rejects_original_unit_drift_even_if_attempt_claims_it(self):
        baseline = self.before()
        path = self.units["recursive-engine"]["FragmentPath"]
        self.files[path] += b"# concurrent edit\n"
        self.assertFalse(self.recovery(baseline))
        self.assertFalse(self.recovery(baseline, {path: self.files[path]}))

    def test_recovery_rejects_unrelated_resource_environment_pid_or_state_drift(self):
        baseline = self.before()
        original = copy.deepcopy(self.units)
        for service, key, value in (
            ("recursive-engine", "MemoryMax", "infinity"),
            ("recursive-history", "EnvironmentSHA256", "changed"),
            ("recursive-engine", "MainPID", "900"),
            ("kalshi-live-engine", "ActiveState", "active"),
            ("recursive-history", "NeedDaemonReload", "yes"),
        ):
            with self.subTest(service=service, key=key):
                self.units = copy.deepcopy(original)
                self.units[service][key] = value
                self.assertFalse(self.recovery(baseline))

    def test_recovery_rejects_partial_stopping_or_failed_targets(self):
        baseline = self.before()
        for state in ("deactivating", "failed", "activating", "reloading"):
            with self.subTest(state=state):
                self.units["recursive-web"]["ActiveState"] = state
                self.assertFalse(self.recovery(baseline))

    def test_recovery_rejects_target_resource_or_fresh_active_pid_change(self):
        baseline = self.before()
        self.units["recursive-web"]["MemoryMax"] = "infinity"
        self.assertFalse(self.recovery(baseline))
        self.units["recursive-web"]["MemoryMax"] = "419430400"
        self.units["recursive-web"]["MainPID"] = "900"
        self.assertFalse(self.recovery(baseline))

    def test_recovery_rejects_extra_dropin_and_missing_original_file(self):
        baseline = self.before()
        extra = "/etc/systemd/system/recursive-web.service.d/95-concurrent.conf"
        self.files[extra] = b"[Service]\nMemoryMax=infinity\n"
        self.assertFalse(self.recovery(baseline))
        self.files.pop(extra)
        self.files.pop(self.units["recursive-history"]["FragmentPath"])
        self.assertFalse(self.recovery(baseline))

    def test_recovery_rejects_wrong_own_bytes_even_if_attempt_matches_them(self):
        baseline = self.before()
        self.reload()
        attempts = self.attempted_drops()
        path = self.plans["recursive-web"][0]["drop_path"]
        self.files[str(path)] += b"Environment=SECRET=private\n"
        attempts[path] = self.files[str(path)]
        self.assertFalse(self.recovery(baseline, attempts))

    def test_recovery_rejects_unapproved_loaded_exec_or_dropin_paths(self):
        baseline = self.before()
        self.units["recursive-web"]["ExecStart"] = self.units["recursive-web"]["ExecStart"].replace("app.server", "app.worker")
        self.assertFalse(self.recovery(baseline))
        self.units["recursive-web"] = copy.deepcopy(baseline["units"]["recursive-web"])
        self.units["recursive-web"]["DropInPaths"] = "/run/systemd/system/recursive-web.service.d/50-other.conf"
        self.assertFalse(self.recovery(baseline))

    def test_recovery_returns_false_on_failed_reads_without_private_error(self):
        baseline = self.before()
        with patch.object(guard, "_inventory", side_effect=RuntimeError("SECRET=private")):
            self.assertFalse(self.recovery(baseline))


if __name__ == "__main__":
    unittest.main()
