"""Synthetic finalization proofs; no systemd, database, provider or network I/O."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch

import capacity
import capacity_finalize as finalize
import remote


HERE = Path(__file__).resolve().parent
PRIVATE = "synthetic-private-property-and-environment-must-not-escape"
PROPERTIES = ("MainPID", "ActiveState", "SubState", "FragmentPath", "DropInPaths", "NeedDaemonReload",
              "Restart", "RestartUSec", "Environment", "EnvironmentFiles", "ExecStart", "MemoryHigh",
              "MemoryMax", "MemorySwapMax", "CPUQuotaPerSecUSec", "CPUWeight", "TasksMax", "Nice")
OLD_PATHS = ("/etc/systemd/system/recursive-agents.service.d/90-tau-provider-data.conf",
             "/etc/systemd/system/recursive-agents.service.d/99-tau-alpaca-paper.conf")


def pressure():
    return {"host_bytes": {"MemTotal": 16 * 1024**3, "MemAvailable": 12 * 1024**3},
            "kernel_events_last_30m": dict.fromkeys(("worker_limit", "ancestor_limit", "global_constraint",
                                                     "unclassified_memcg", "cgroup_constraint"), 0)}


class Backend:
    def __init__(self, pins):
        self.state = copy.deepcopy(pins["installed"])
        self.guard = types.SimpleNamespace(PROPERTIES=PROPERTIES)
        self.private = {name: {"APP_SECRET_KEY": PRIVATE, "OTHER_PRIVATE": PRIVATE} for name in remote.SERVICES}
        self.counts = {"running": 0, "queued": 0, "paused": 0}
        self.calls, self.snapshots = [], 0
        self.fault, self.before_latest, self.after_reload = None, lambda: None, lambda: None
        self.override = copy.deepcopy(finalize.OVERRIDE_METADATA)
        worker = self.state["controls"]["units"][capacity.SERVICE]
        worker.update(pid=509844, active_state="active", sub_state="running", need_daemon_reload="yes")
        worker["resources"]["MemoryMax"] = str(capacity.NEW_MAX)
        for name, row in self.state["controls"]["units"].items():
            if name != capacity.SERVICE:
                row["need_daemon_reload"] = "no"
        self.state["controls"]["processes"][capacity.SERVICE]["start_ticks"] = "50358518"
        self.state["controls"]["unit_files"][str(capacity.OVERRIDE)] = {
            key: self.override[key] for key in ("sha256", "uid", "gid", "mode")}
        properties = {"MainPID": "509844", "ActiveState": "active", "SubState": "running",
                      "FragmentPath": "/etc/systemd/system/recursive-agents.service",
                      "DropInPaths": " ".join((*OLD_PATHS, str(capacity.OVERRIDE))),
                      "NeedDaemonReload": "yes", "Restart": "always", "RestartUSec": "5s",
                      "Environment": PRIVATE, "ExecStart": PRIVATE, **worker["resources"],
                      "ControlGroup": capacity.CGROUP}
        self.limits = {"configured_max": capacity.NEW_MAX, "effective_max": capacity.NEW_MAX,
                       "cgroup_max": capacity.NEW_MAX, "pid": 509844, "cgroup_identity": (1, 234),
                       "ancestor_max": None, "ancestor_identity": (1, 200), "physical_total": 16 * 1024**3,
                       "effective_source": "kernel_hierarchy", "private_properties": properties}
        original = dict(properties, MemoryMax=str(capacity.OLD_MAX), NeedDaemonReload="no",
                        DropInPaths=" ".join(OLD_PATHS))
        self.approval = copy.deepcopy(finalize.EXPECTED_APPROVAL)
        self.approval["before_worker_properties_sha256"] = self.hash_properties(original)
        self.bind_hash()
        pins["installed"] = copy.deepcopy(self.state)
        pins["capacity_finalize_approval"] = copy.deepcopy(self.approval)

    def hash_properties(self, properties):
        return remote.fingerprint({key: properties[key] for key in self.guard.PROPERTIES if key in properties})

    def bind_hash(self):
        self.state["controls"]["units"][capacity.SERVICE]["properties_sha256"] = self.hash_properties(
            self.limits["private_properties"])

    def snapshot(self):
        self.snapshots += 1
        if self.snapshots == 2:
            self.before_latest()
        return copy.deepcopy(self.state), copy.deepcopy(self.private)

    def inspect(self, env):
        return {"job_counts": dict(self.counts)}

    def command(self, args, *, timeout):
        self.calls.append((args, timeout))
        if args != ["systemctl", "daemon-reload"] or timeout != 8:
            raise AssertionError("unapproved command")
        if self.fault == "before":
            raise TimeoutError(PRIVATE)
        self.limits["private_properties"]["NeedDaemonReload"] = "no"
        self.limits["private_properties"]["DropInPaths"] = " ".join((str(capacity.OVERRIDE), *OLD_PATHS))
        self.state["controls"]["units"][capacity.SERVICE]["need_daemon_reload"] = "no"
        self.bind_hash()
        self.after_reload()
        if self.fault == "after":
            raise TimeoutError(PRIVATE)
        return PRIVATE.encode() if self.fault == "unexpected_output" else b""


class FinalizeTests(unittest.TestCase):
    def setUp(self):
        self.pins = json.loads((HERE / "pins.json").read_text())
        self.backend = Backend(self.pins)
        self.stack = ExitStack()
        # Synthetic hash fixture only: production exact receipt remains fixed.
        self.stack.enter_context(patch.object(finalize, "EXPECTED_APPROVAL", self.backend.approval))
        self.stack.enter_context(patch.object(remote, "worker_health", return_value={"status": "observed"}))
        self.memory = self.stack.enter_context(patch.object(remote, "memory_pressure", side_effect=lambda: pressure()))
        self.install = self.stack.enter_context(patch.object(capacity, "install_guard_exception",
            side_effect=lambda guard: copy.deepcopy(self.backend.override)))
        self.observe = self.stack.enter_context(patch.object(capacity, "observe_limits",
            side_effect=lambda *args, **kwargs: copy.deepcopy(self.backend.limits)))

    def tearDown(self):
        self.stack.close()

    def run_finalizer(self):
        result = finalize.run(self.backend, self.pins, command=self.backend.command)
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assertEqual(result["property_command_attempts"], 0)
        self.assertEqual(result["service_restart_operations"], 0)
        self.assertEqual(result["job_mutations"], 0)
        self.assertFalse(result["application_changes"] or result["perps_release_activated"])
        return result

    def assert_blocked(self, result):
        self.assertEqual(result["status"], "capacity_finalize_requires_inspection", result)
        self.assertFalse(result["mutation_may_have_applied"])
        self.assertEqual(self.backend.calls, [])
        self.assertNotIn("observed_controls", result)
        self.assertNotIn("source_fingerprint", result)

    def assert_post_blocked(self, result):
        self.assertEqual(result["status"], "capacity_finalize_requires_inspection", result)
        self.assertTrue(result["mutation_may_have_applied"])
        self.assertFalse(result["no_service_restart"])
        self.assertEqual(self.backend.calls, [(["systemctl", "daemon-reload"], 8)])
        self.assertNotIn("observed_controls", result)
        self.assertNotIn("source_fingerprint", result)

    def update_baseline(self):
        self.backend.bind_hash()
        self.pins["installed"] = copy.deepcopy(self.backend.state)

    def test_exact_partial_state_one_reload_no_resource_write_or_restart(self):
        result = self.run_finalizer()
        self.assertEqual(result["status"], "capacity_finalize_verified", result)
        self.assertEqual(self.backend.calls, [(["systemctl", "daemon-reload"], 8)])
        self.assertEqual(result["manager_reload_attempts"], 1)
        self.assertEqual(result["service_operations"], 1)
        self.assertTrue(result["resource_change_already_existing"] and result["resource_change_verified"])
        self.assertTrue(result["no_service_restart"])
        self.assertFalse(result["stability_observation_completed"])
        self.assertEqual(result["stability_observation_required_seconds"], 900)
        self.assertEqual(result["observed_controls"], self.backend.state["controls"])
        self.assertEqual(result["source_fingerprint"], remote.fingerprint(remote.source_files(self.backend.state)))
        self.assertEqual(self.backend.snapshots, 3)

    def test_all_kinds_active_work_and_legitimate_completion_are_observed_without_job_writes(self):
        self.backend.counts = {"running": 2, "queued": 1, "paused": 3}
        self.backend.after_reload = lambda: self.backend.counts.update(running=1)
        result = self.run_finalizer()
        self.assertEqual(result["status"], "capacity_finalize_verified", result)
        self.assertEqual(result["job_counts_before"]["running"], 2)
        self.assertEqual(result["job_counts_after"]["running"], 1)

    def test_exact_approval_types_fields_and_receipt_hashes_are_required(self):
        original = copy.deepcopy(self.pins["capacity_finalize_approval"])
        for field in original:
            with self.subTest(field=field):
                self.pins["capacity_finalize_approval"] = dict(original)
                self.pins["capacity_finalize_approval"][field] = None
                self.assert_blocked(self.run_finalizer())
        self.pins["capacity_finalize_approval"] = dict(original, extra=PRIVATE)
        self.assert_blocked(self.run_finalizer())
        self.pins.pop("capacity_finalize_approval")
        self.assert_blocked(self.run_finalizer())

    def test_any_other_source_or_control_conflict_blocks_before_reload(self):
        for area in ("source", "units", "unit_files", "processes", "protected_config"):
            with self.subTest(area=area):
                original = copy.deepcopy(self.backend.state)
                target = self.backend.state["source"]["files"] if area == "source" else self.backend.state["controls"][area]
                target["unexpected"] = {"sha256": "e" * 64}
                self.assert_blocked(self.run_finalizer())
                self.backend.state = original

    def test_worker_only_pending_and_exact_pid_start_are_mandatory_even_with_matching_pins(self):
        mutations = [lambda: self.backend.state["controls"]["units"][capacity.SERVICE].update(need_daemon_reload="no"),
                     lambda: self.backend.state["controls"]["units"]["recursive-web"].update(need_daemon_reload="yes"),
                     lambda: self.backend.state["controls"]["units"][capacity.SERVICE].update(pid=509845),
                     lambda: self.backend.state["controls"]["processes"][capacity.SERVICE].update(start_ticks="50358519")]
        for change in mutations:
            with self.subTest(change=change):
                previous, pin = copy.deepcopy(self.backend.state), copy.deepcopy(self.pins["installed"])
                change(); self.pins["installed"] = copy.deepcopy(self.backend.state)
                self.assert_blocked(self.run_finalizer())
                self.backend.state, self.pins["installed"] = previous, pin

    def test_exact_complete_override_bytes_owner_mode_and_hash_are_required(self):
        for key, value in (("sha256", "d" * 64), ("bytes", 151), ("uid", 1), ("gid", 1), ("mode", "0600")):
            with self.subTest(key=key):
                original = dict(self.backend.override)
                self.backend.override[key] = value
                self.assert_blocked(self.run_finalizer())
                self.backend.override = original

    def test_bad_or_unavailable_current_pressure_and_headroom_never_use_prior_proof(self):
        self.pins["capacity_approved_oom_evidence"] = {"arbitrary": PRIVATE}
        for field in ("worker_limit", "ancestor_limit", "global_constraint", "unclassified_memcg", "cgroup_constraint"):
            for value in (True, -1, None):
                data = pressure(); data["kernel_events_last_30m"][field] = value
                self.memory.side_effect = lambda data=data: data
                self.assert_blocked(self.run_finalizer())
        for data in ({"kernel_error_code": PRIVATE}, {**pressure(), "kernel_error_code": PRIVATE},
                     {**pressure(), "host_error_code": PRIVATE}):
            self.memory.side_effect = lambda data=data: data
            self.assert_blocked(self.run_finalizer())
        for key, value in (("MemTotal", capacity.MIN_TOTAL - 1), ("MemAvailable", capacity.MIN_AVAILABLE - 1)):
            data = pressure(); data["host_bytes"][key] = value
            self.memory.side_effect = lambda data=data: data
            self.assert_blocked(self.run_finalizer())

    def test_present_positive_exact_worker_evidence_is_allowed(self):
        data = pressure(); data["kernel_events_last_30m"].update(worker_limit=1, cgroup_constraint=1)
        self.memory.side_effect = lambda: data
        self.assertEqual(self.run_finalizer()["status"], "capacity_finalize_verified")

    def test_bad_scope_or_unattributed_current_events_block(self):
        for scope in ("ancestor_limit", "global_constraint", "unclassified_memcg", "cgroup_constraint"):
            data = pressure(); data["kernel_events_last_30m"][scope] = 1
            self.memory.side_effect = lambda data=data: data
            self.assert_blocked(self.run_finalizer())

    def test_raw_snapshot_hash_binding_rejects_another_property_generation(self):
        self.backend.limits["private_properties"]["Environment"] += "changed"
        self.assert_blocked(self.run_finalizer())

    def test_original_hash_proof_rejects_hidden_config_or_old_path_order_change(self):
        for key, value in (("ExecStart", PRIVATE + "changed"), ("Environment", PRIVATE + "changed"),
                           ("DropInPaths", " ".join((*reversed(OLD_PATHS), str(capacity.OVERRIDE))))):
            with self.subTest(key=key):
                original = copy.deepcopy(self.backend.limits)
                state = copy.deepcopy(self.backend.state)
                pin = copy.deepcopy(self.pins["installed"])
                self.backend.limits["private_properties"][key] = value
                self.update_baseline()
                self.assert_blocked(self.run_finalizer())
                self.backend.limits, self.backend.state, self.pins["installed"] = original, state, pin

    def test_duplicate_or_missing_override_path_blocks(self):
        original = self.backend.limits["private_properties"]["DropInPaths"]
        for value in (" ".join(OLD_PATHS), original + " " + str(capacity.OVERRIDE),
                      original + " " + OLD_PATHS[0]):
            self.backend.limits["private_properties"]["DropInPaths"] = value
            self.update_baseline()
            self.assert_blocked(self.run_finalizer())

    def test_missing_sensitive_mandatory_properties_are_not_invented(self):
        for key in ("Environment", "ExecStart", "DropInPaths", "NeedDaemonReload", "MainPID", "MemoryMax"):
            with self.subTest(key=key):
                original = copy.deepcopy(self.backend.limits)
                state = copy.deepcopy(self.backend.state)
                pin = copy.deepcopy(self.pins["installed"])
                del self.backend.limits["private_properties"][key]
                self.update_baseline()
                self.assert_blocked(self.run_finalizer())
                self.backend.limits, self.backend.state, self.pins["installed"] = original, state, pin

    def test_private_environment_change_before_reload_stops_without_mutation(self):
        self.backend.before_latest = lambda: self.backend.private[capacity.SERVICE].update(OTHER_PRIVATE=PRIVATE + "changed")
        self.assert_blocked(self.run_finalizer())

    def test_latest_limit_identity_change_blocks_before_reload(self):
        def changed():
            self.backend.limits["ancestor_identity"] = (1, 201)
        self.backend.before_latest = changed
        self.assert_blocked(self.run_finalizer())

    def test_pre_command_fresh_pressure_is_required(self):
        data = pressure(); data["host_bytes"]["MemAvailable"] = 0
        self.memory.side_effect = [pressure(), data]
        self.assert_blocked(self.run_finalizer())

    def test_timeout_before_or_after_reload_is_never_retried_or_accepted(self):
        for fault in ("before", "after", "unexpected_output"):
            with self.subTest(fault=fault):
                self.backend.fault = fault
                result = self.run_finalizer()
                self.assert_post_blocked(result)
                self.assertEqual(self.backend.snapshots, 3)
                self.backend = Backend(self.pins)

    def test_post_source_private_files_or_private_environment_drift_requires_inspection(self):
        for area in ("source", "protected_config", "unit_files", "private"):
            with self.subTest(area=area):
                def changed(area=area):
                    if area == "private":
                        self.backend.private[capacity.SERVICE]["OTHER_PRIVATE"] += "changed"
                    else:
                        target = self.backend.state["source"]["files"] if area == "source" else self.backend.state["controls"][area]
                        target["unexpected"] = {"sha256": "e" * 64}
                self.backend.after_reload = changed
                self.assert_post_blocked(self.run_finalizer())
                self.backend = Backend(self.pins)

    def test_post_any_process_or_non_target_unit_change_requires_inspection(self):
        for area, service, field in (("processes", capacity.SERVICE, "environment_sha256"),
                                     ("processes", capacity.SERVICE, "start_ticks"),
                                     ("processes", "recursive-web", "cmdline_sha256"),
                                     ("units", "recursive-web", "restart")):
            with self.subTest(area=area, service=service, field=field):
                self.backend.after_reload = lambda area=area, service=service, field=field: self.backend.state["controls"][area][service].update({field: "changed"})
                self.assert_post_blocked(self.run_finalizer())
                self.backend = Backend(self.pins)

    def test_post_pid_resource_raw_property_or_path_membership_change_requires_inspection(self):
        cases = [("MainPID", "509845"), ("MemoryMax", str(capacity.OLD_MAX)), ("Environment", PRIVATE + "changed"),
                 ("DropInPaths", " ".join((str(capacity.OVERRIDE), OLD_PATHS[0]))),
                 ("DropInPaths", " ".join((str(capacity.OVERRIDE), *OLD_PATHS, OLD_PATHS[0])))]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                def changed(key=key, value=value):
                    self.backend.limits["private_properties"][key] = value
                    self.backend.bind_hash()
                self.backend.after_reload = changed
                self.assert_post_blocked(self.run_finalizer())
                self.backend = Backend(self.pins)

    def test_after_optional_property_presence_change_is_blocked(self):
        for key in ("EnvironmentFiles", "EffectiveMemoryMax"):
            with self.subTest(key=key):
                def changed(key=key):
                    self.backend.limits["private_properties"][key] = ""
                    self.backend.bind_hash()
                self.backend.after_reload = changed
                self.assert_post_blocked(self.run_finalizer())
                self.backend = Backend(self.pins)

    def test_post_kernel_hierarchy_or_physical_identity_change_is_blocked(self):
        for key, value in (("ancestor_max", 2 * capacity.NEW_MAX), ("ancestor_identity", (1, 201)),
                           ("cgroup_identity", (1, 235)), ("physical_total", 17 * 1024**3),
                           ("effective_max", capacity.OLD_MAX), ("cgroup_max", capacity.OLD_MAX)):
            with self.subTest(key=key):
                self.backend.after_reload = lambda key=key, value=value: self.backend.limits.update({key: value})
                self.assert_post_blocked(self.run_finalizer())
                self.backend = Backend(self.pins)

    def test_after_override_replacement_and_read_failure_are_not_repaired(self):
        self.backend.after_reload = lambda: self.backend.override.update(sha256="f" * 64)
        self.assert_post_blocked(self.run_finalizer())
        self.assertEqual(self.observe.call_count, 2)

    def test_exceptions_never_leak_private_error_messages(self):
        self.observe.side_effect = RuntimeError(PRIVATE)
        result = self.run_finalizer()
        self.assert_blocked(result)
        self.assertEqual(result["error_code"], "capacity_finalize_operation_failed")


if __name__ == "__main__":
    unittest.main()
