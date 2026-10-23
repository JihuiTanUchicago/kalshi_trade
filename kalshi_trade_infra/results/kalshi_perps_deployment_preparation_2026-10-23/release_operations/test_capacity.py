"""Offline capacity gates, exact guard exception, one-write and redaction checks."""
import copy
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest.mock import patch

import capacity
import remote


HERE = Path(__file__).resolve().parent
COUNTS = {"queued": 0, "running": 0, "paused": 0}
PRIVATE = "synthetic-private-value-must-never-be-reported"


def pressure():
    return {"host_bytes": {"MemTotal": 16 * 1024**3, "MemAvailable": 12 * 1024**3},
            "kernel_events_last_30m": {"cgroup_constraint": 2, "worker_limit": 2,
                                        "ancestor_limit": 0, "global_constraint": 0, "unclassified_memcg": 0}}


class Backend:
    def __init__(self, pins):
        # Capacity fixtures model the old cap even after a later reviewed
        # production baseline legitimately records the accepted new override.
        pins["installed"]["controls"]["units"][capacity.SERVICE]["resources"]["MemoryMax"] = str(capacity.OLD_MAX)
        pins["installed"]["controls"]["unit_files"].pop(str(capacity.OVERRIDE), None)
        self.state = copy.deepcopy(pins["installed"])
        self.guard = types.SimpleNamespace()
        self.private = {name: {"APP_SECRET_KEY": PRIVATE, "OTHER_PRIVATE": PRIVATE} for name in remote.SERVICES}
        self.counts, self.calls, self.snapshots = dict(COUNTS), [], 0
        self.override = None
        pid = self.state["controls"]["units"][capacity.SERVICE]["pid"]
        self.limits = {"configured_max": capacity.OLD_MAX, "effective_max": capacity.OLD_MAX,
                       "cgroup_max": capacity.OLD_MAX, "pid": pid, "cgroup_identity": (1, 234),
                       "ancestor_max": None, "ancestor_identity": (1, 200), "physical_total": 16 * 1024**3,
                       "effective_source": "kernel_hierarchy_and_systemd",
                       "private_properties": {"MemoryMax": str(capacity.OLD_MAX),
                           "EffectiveMemoryMax": str(capacity.OLD_MAX), "DropInPaths": "/etc/systemd/system/old.conf",
                           "Environment": PRIVATE, "ExecStart": "/fixed/python -m app.worker agents",
                           "MainPID": str(pid), "ControlGroup": capacity.CGROUP}}
        self.guard.PROPERTIES = ("MemoryMax", "DropInPaths", "Environment", "ExecStart", "MainPID")
        value = remote.fingerprint({name: self.limits["private_properties"][name] for name in self.guard.PROPERTIES})
        self.state["controls"]["units"][capacity.SERVICE]["properties_sha256"] = value
        pins["installed"]["controls"]["units"][capacity.SERVICE]["properties_sha256"] = value
        self.fault, self.after_change = None, lambda: None

    def snapshot(self):
        self.snapshots += 1
        return copy.deepcopy(self.state), copy.deepcopy(self.private)

    def inspect(self, env):
        return {"job_counts": dict(self.counts)}

    def mutate(self, args, *, timeout):
        self.calls.append((args, timeout))
        if self.fault == "before":
            raise TimeoutError(PRIVATE)
        self.override = {"sha256": hashlib.sha256(capacity.VALID_CONTENTS[0]).hexdigest(),
                         "bytes": len(capacity.VALID_CONTENTS[0]), "uid": 0, "gid": 0, "mode": "0644"}
        self.state["controls"]["unit_files"][str(capacity.OVERRIDE)] = {
            key: self.override[key] for key in ("sha256", "uid", "gid", "mode")}
        worker = self.state["controls"]["units"][capacity.SERVICE]
        worker["resources"]["MemoryMax"] = str(capacity.NEW_MAX)
        for key in ("configured_max", "effective_max", "cgroup_max"):
            self.limits[key] = capacity.NEW_MAX
        self.limits["private_properties"]["MemoryMax"] = str(capacity.NEW_MAX)
        if self.limits["private_properties"].get("EffectiveMemoryMax", ""):
            self.limits["private_properties"]["EffectiveMemoryMax"] = str(capacity.NEW_MAX)
        self.limits["private_properties"]["DropInPaths"] += " " + str(capacity.OVERRIDE)
        worker["properties_sha256"] = remote.fingerprint({name: self.limits["private_properties"][name] for name in self.guard.PROPERTIES})
        self.after_change()
        if self.fault == "after":
            raise TimeoutError(PRIVATE)
        return b""


class CapacityRunTests(unittest.TestCase):
    def setUp(self):
        self.pins = json.loads((HERE / "pins.json").read_text())
        self.backend = Backend(self.pins)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(remote, "worker_health", return_value={"status": "observed"}))
        self.memory = self.stack.enter_context(patch.object(remote, "memory_pressure", side_effect=lambda: pressure()))
        self.stack.enter_context(patch.object(capacity, "override_metadata", side_effect=lambda guard: self.backend.override))
        self.install = self.stack.enter_context(patch.object(capacity, "install_guard_exception", side_effect=lambda guard: self.backend.override))
        self.observe = self.stack.enter_context(patch.object(capacity, "observe_limits", side_effect=lambda *args, **kwargs: copy.deepcopy(self.backend.limits)))

    def tearDown(self):
        self.stack.close()

    def run_capacity(self):
        return capacity.run(self.backend, self.pins, command=self.backend.mutate)

    def assert_no_write(self, result):
        self.assertEqual(result["status"], "capacity_requires_inspection")
        self.assertFalse(result["mutation_may_have_applied"])
        self.assertEqual(self.backend.calls, [])
        self.assertNotIn(PRIVATE, json.dumps(result))

    def test_online_increase_with_running_or_queued_work_never_restarts_or_mutates_jobs(self):
        for status in COUNTS:
            with self.subTest(status=status):
                self.backend = Backend(self.pins)
                self.backend.counts[status] = 1
                result = self.run_capacity()
                self.assertEqual(result["status"], "capacity_verified", result)
                self.assertEqual(result["job_counts_immediately_before"][status], 1)
                self.assertTrue(result["override_added"] and result["resource_change_verified"] and result["no_service_restart"])
                self.assertFalse(result["stability_observation_completed"] or result["perps_release_activated"])
                self.assertEqual(result["stability_observation_required_seconds"], 900)
                self.assertEqual(result["job_mutations"], 0)
                self.assertEqual(result["service_operations"], 1)
                self.assertEqual(result["service_restart_operations"], 0)
                self.assertEqual(result["resource_property_commands"], 1)
                self.assertEqual(result["provider_calls_from_operations"], 0)
                self.assertEqual(self.backend.calls, [(["systemctl", "set-property", "recursive-agents.service", "MemoryMax=1073741824"], 8)])
                self.assertNotIn(PRIVATE, json.dumps(result))

    def test_legitimate_run_completion_is_recorded_without_an_idle_gate(self):
        self.backend.counts["running"] = 1
        self.backend.after_change = lambda: self.backend.counts.update(running=0)
        result = self.run_capacity()
        self.assertEqual(result["status"], "capacity_verified")
        self.assertEqual(result["job_counts_before"]["running"], 1)
        self.assertEqual(result["job_counts_after"]["running"], 0)

    def test_older_systemd_without_optional_effective_property_can_apply(self):
        for representation in (None, ""):
            with self.subTest(representation=representation):
                self.backend = Backend(self.pins)
                if representation is None:
                    del self.backend.limits["private_properties"]["EffectiveMemoryMax"]
                else:
                    self.backend.limits["private_properties"]["EffectiveMemoryMax"] = ""
                self.backend.limits["effective_source"] = "kernel_hierarchy"
                result = self.run_capacity()
                self.assertEqual(result["status"], "capacity_verified", result)
                self.assertEqual(result["limits_after"]["effective_source"], "kernel_hierarchy")

    def test_every_source_control_or_process_conflict_blocks_before_command(self):
        for target in ("source", "units", "unit_files", "processes", "protected_config"):
            with self.subTest(target=target):
                self.backend = Backend(self.pins)
                mapping = self.backend.state["source"]["files"] if target == "source" else self.backend.state["controls"][target]
                mapping["unexpected"] = {}
                self.assert_no_write(self.run_capacity())

    def test_worker_pid_rollover_is_not_automatically_adopted(self):
        self.backend.state["controls"]["units"][capacity.SERVICE]["pid"] += 1
        result = self.run_capacity()
        self.assert_no_write(result)
        self.assertEqual(result["error_code"], "capacity_baseline_conflict")

    def test_existing_override_is_never_overwritten(self):
        self.backend.override = {"sha256": "f" * 64}
        result = self.run_capacity()
        self.assert_no_write(result)
        self.assertEqual(result["error_code"], "capacity_override_already_present")

    def test_host_and_exact_oom_scope_are_required(self):
        cases = [pressure() for _ in range(8)]
        cases[0]["host_bytes"]["MemTotal"] = capacity.MIN_TOTAL - 1
        cases[1]["host_bytes"]["MemAvailable"] = capacity.MIN_AVAILABLE - 1
        for i, name in enumerate(("worker_limit", "ancestor_limit", "global_constraint", "unclassified_memcg"), 2):
            cases[i]["kernel_events_last_30m"][name] = 0 if name == "worker_limit" else 1
        cases[6]["kernel_events_last_30m"]["worker_limit"] = True
        cases[7] = {"host_error_code": PRIVATE, "kernel_error_code": PRIVATE}
        for data in cases:
            with self.subTest(data=data):
                self.memory.side_effect = lambda data=data: data
                self.assert_no_write(self.run_capacity())

    def test_changed_fresh_headroom_or_oom_evidence_prevents_the_one_command(self):
        bad = pressure()
        bad["host_bytes"]["MemAvailable"] = 0
        self.memory.side_effect = [pressure(), bad]
        self.assert_no_write(self.run_capacity())

    def test_configured_effective_and_cgroup_caps_must_all_be_exact_old_value(self):
        for name in ("configured_max", "effective_max", "cgroup_max"):
            with self.subTest(name=name):
                self.backend = Backend(self.pins)
                self.backend.limits[name] -= 1
                self.assert_no_write(self.run_capacity())

    def test_disjoint_private_property_generation_is_rejected_before_or_after_command(self):
        self.backend.limits["private_properties"]["Environment"] = "changed-" + PRIVATE
        result = self.run_capacity()
        self.assert_no_write(result)
        self.assertEqual(result["error_code"], "capacity_worker_property_generation_changed")
        self.backend = Backend(self.pins)
        self.backend.after_change = lambda: self.backend.limits["private_properties"].update(Environment="changed-" + PRIVATE)
        result = self.run_capacity()
        self.assertEqual(result["status"], "capacity_requires_inspection")
        self.assertEqual(result["error_code"], "capacity_worker_property_generation_changed")
        self.assertTrue(result["mutation_may_have_applied"])
        self.assertEqual(len(self.backend.calls), 1)
        self.assertNotIn(PRIVATE, json.dumps(result))

    def test_state_or_actual_environment_change_between_preflight_reads_blocks_command(self):
        for kind in ("source", "private"):
            with self.subTest(kind=kind):
                self.backend = Backend(self.pins)
                snapshot = self.backend.snapshot
                calls = [0]
                def changed():
                    calls[0] += 1
                    if calls[0] == 2:
                        if kind == "source":
                            self.backend.state["source"]["files"]["unexpected"] = {}
                        else:
                            self.backend.private[capacity.SERVICE]["OTHER_PRIVATE"] = "changed-" + PRIVATE
                    return snapshot()
                with patch.object(self.backend, "snapshot", side_effect=changed):
                    self.assert_no_write(self.run_capacity())

    def test_timeout_before_or_after_apply_is_inspection_without_retry_or_lowering(self):
        for where in ("before", "after"):
            with self.subTest(where=where):
                self.backend = Backend(self.pins)
                self.backend.fault = where
                result = self.run_capacity()
                self.assertEqual(result["status"], "capacity_requires_inspection")
                self.assertTrue(result["mutation_may_have_applied"])
                self.assertEqual(len(self.backend.calls), 1)
                self.assertEqual(result["property_command_attempts"], 1)
                self.install.assert_called()
                self.assertNotIn(PRIVATE, json.dumps(result))
                if where == "after":
                    self.assertEqual(result["error_code"], "capacity_command_uncertain")
                    self.assertTrue(result["resource_change_verified"])
                    self.assertEqual(self.backend.limits["cgroup_max"], capacity.NEW_MAX)

    def test_unavailable_post_command_limit_or_override_read_never_retries_the_write(self):
        for stage in ("limits", "override"):
            with self.subTest(stage=stage):
                self.backend = Backend(self.pins)
                if stage == "limits":
                    calls = [0]
                    def observed(*args, **kwargs):
                        calls[0] += 1
                        if calls[0] == 3:
                            raise RuntimeError(PRIVATE)
                        return copy.deepcopy(self.backend.limits)
                    self.observe.side_effect = observed
                else:
                    self.observe.side_effect = lambda *a, **kw: copy.deepcopy(self.backend.limits)
                    self.install.side_effect = RuntimeError(PRIVATE)
                result = self.run_capacity()
                self.assertEqual(result["status"], "capacity_requires_inspection")
                self.assertTrue(result["mutation_may_have_applied"])
                self.assertEqual(len(self.backend.calls), 1)
                self.assertIsNotNone(self.backend.override)
                self.assertEqual(self.backend.limits["configured_max"], capacity.NEW_MAX)
                self.assertNotIn(PRIVATE, json.dumps(result))

    def test_every_unapproved_post_change_requires_inspection_and_never_reverses(self):
        def change(kind):
            if kind == "source":
                self.backend.state["source"]["files"]["unexpected"] = {}
            elif kind == "private":
                self.backend.private[capacity.SERVICE]["OTHER_PRIVATE"] = "changed-" + PRIVATE
            elif kind == "protected_config":
                self.backend.state["controls"]["protected_config"]["unexpected"] = {}
            elif kind == "non_target":
                self.backend.state["controls"]["units"]["recursive-engine"]["pid"] += 1
            elif kind == "worker_pid":
                self.backend.state["controls"]["units"][capacity.SERVICE]["pid"] += 1
            elif kind == "worker_start":
                self.backend.state["controls"]["processes"][capacity.SERVICE]["start_ticks"] = "999999999"
            elif kind == "worker_cpu":
                self.backend.state["controls"]["units"][capacity.SERVICE]["resources"]["CPUWeight"] = "999"
            elif kind == "worker_flag":
                self.backend.state["controls"]["units"][capacity.SERVICE]["perps"]["enabled"] = True
            elif kind == "extra_file":
                self.backend.state["controls"]["unit_files"]["unexpected"] = {}
            elif kind == "exec_property":
                self.backend.limits["private_properties"]["ExecStart"] = "changed-" + PRIVATE
            elif kind == "configured_environment":
                self.backend.limits["private_properties"]["Environment"] = "changed-" + PRIVATE
            elif kind == "effective_limit":
                self.backend.limits["effective_max"] = capacity.OLD_MAX
            elif kind == "cgroup_identity":
                self.backend.limits["cgroup_identity"] = (1, 999)
            elif kind == "ancestor_limit":
                self.backend.limits["ancestor_max"] = 2 * capacity.NEW_MAX
            elif kind == "ancestor_identity":
                self.backend.limits["ancestor_identity"] = (1, 999)
            elif kind == "physical_total":
                self.backend.limits["physical_total"] += 1
            elif kind == "optional_property_presence":
                del self.backend.limits["private_properties"]["EffectiveMemoryMax"]
        for kind in ("source", "private", "protected_config", "non_target", "worker_pid", "worker_start", "worker_cpu",
                     "worker_flag", "extra_file", "exec_property", "configured_environment", "effective_limit", "cgroup_identity",
                     "ancestor_limit", "ancestor_identity", "physical_total", "optional_property_presence"):
            with self.subTest(kind=kind):
                self.backend = Backend(self.pins)
                self.backend.after_change = lambda kind=kind: change(kind)
                result = self.run_capacity()
                self.assertEqual(result["status"], "capacity_requires_inspection")
                self.assertTrue(result["mutation_may_have_applied"])
                self.assertEqual(len(self.backend.calls), 1)
                self.assertNotIn(PRIVATE, json.dumps(result))


class RootInfo:
    def __init__(self, original):
        self.original = original
    def __getattr__(self, name):
        return 0 if name in ("st_uid", "st_gid") else getattr(self.original, name)


class GuardExceptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE)
        self.root = Path(self.temp.name)
        self.path = self.root / "system.control/recursive-agents.service.d/50-MemoryMax.conf"
        self.path.parent.mkdir(parents=True)
        self.stack = ExitStack()
        original_lstat = Path.lstat
        self.stack.enter_context(patch.object(capacity, "OVERRIDE", self.path))
        self.stack.enter_context(patch.object(capacity.Path, "lstat", lambda path: RootInfo(original_lstat(path))))
        def read_regular(path, limit=4096, owners=(0,)):
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError(PRIVATE)
            return path.read_bytes(), {"uid": 0, "gid": 0, "mode": format(stat.S_IMODE(info.st_mode), "04o")}
        self.reader = read_regular
        self.guard = types.SimpleNamespace(UNIT_ROOTS=(Path("/etc/systemd/system"),), read_regular=read_regular)

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def write(self, raw=None, mode=0o644):
        self.path.write_bytes(capacity.VALID_CONTENTS[0] if raw is None else raw)
        self.path.chmod(mode)

    def test_absence_adds_no_root_and_exact_file_is_the_only_new_root(self):
        self.assertIsNone(capacity.install_guard_exception(self.guard))
        self.assertEqual(self.guard.UNIT_ROOTS, (Path("/etc/systemd/system"),))
        self.write()
        meta = capacity.install_guard_exception(self.guard)
        self.assertEqual(self.guard.UNIT_ROOTS, (Path("/etc/systemd/system"), self.path))
        self.assertEqual(meta["sha256"], hashlib.sha256(capacity.VALID_CONTENTS[0]).hexdigest())
        self.assertEqual(self.guard.read_regular(self.path)[0], capacity.VALID_CONTENTS[0])
        with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_descendant_rejected"):
            self.guard.read_regular(self.path / "recursive-web.service")
        self.assertNotIn(self.path.parent, self.guard.UNIT_ROOTS)

    def test_other_files_still_use_the_unchanged_original_reader(self):
        other = self.root / "other.conf"
        other.write_bytes(b"original-check-path")
        capacity.install_guard_exception(self.guard)
        self.assertEqual(self.guard.read_regular(other), self.reader(other))

    def test_complete_body_rejects_other_directives_comments_sections_and_wrong_values(self):
        bad = [capacity.HEADER + capacity.BODY + b"Environment=SECRET=value\n",
               capacity.HEADER + capacity.BODY + b"[Service]\nCPUWeight=999\n",
               capacity.VALID_CONTENTS[0].replace(b"1073741824", b"2147483648"),
               capacity.BODY, b"# unrelated\n" + capacity.HEADER + capacity.BODY,
               capacity.VALID_CONTENTS[0].replace(b"\n", b"\r\n"),
               capacity.HEADER + b"[Service]\nMemoryMax=1073741824\nMemoryMax=1073741824\n"]
        for raw in bad:
            with self.subTest(raw_hash=hashlib.sha256(raw).hexdigest()):
                self.write(raw)
                with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_body_unrecognized"):
                    capacity.install_guard_exception(self.guard)
                self.assertEqual(self.path.read_bytes(), raw)
                self.assertNotIn(self.path, self.guard.UNIT_ROOTS)

    def test_group_writable_executable_hardlinked_symlink_or_symlink_parent_is_rejected(self):
        for mode in (0o664, 0o666, 0o700, 0o755):
            self.write(mode=mode)
            with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_unsafe"):
                capacity.override_metadata(self.guard)
        self.write()
        other = self.root / "hardlink"
        os.link(self.path, other)
        with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_unsafe"):
            capacity.override_metadata(self.guard)
        other.unlink()
        self.path.unlink()
        self.path.symlink_to(other)
        with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_unsafe"):
            capacity.override_metadata(self.guard)
        self.path.unlink()
        self.path.parent.rmdir()
        self.path.parent.symlink_to(self.root)
        with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_unsafe"):
            capacity.override_metadata(self.guard)

    def test_foreign_inode_replacement_during_read_is_not_adopted_or_deleted(self):
        self.write()
        hold = self.root / "old-inode"
        def replaced(path, *args, **kwargs):
            result = self.reader(path, *args, **kwargs)
            path.rename(hold)
            self.write()
            return result
        self.guard.read_regular = replaced
        with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_unsafe"):
            capacity.override_metadata(self.guard)
        self.assertTrue(self.path.exists() and hold.exists())

    def test_later_same_path_replacement_by_directory_never_allows_descendants(self):
        self.write()
        capacity.install_guard_exception(self.guard)
        self.path.unlink()
        self.path.mkdir()
        child = self.path / "recursive-web.service"
        child.write_bytes(b"foreign")
        with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_descendant_rejected"):
            self.guard.read_regular(child)
        with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_unsafe"):
            self.guard.read_regular(self.path)

    def test_unchanged_real_guard_accepts_only_the_exact_override_exception(self):
        source = HERE.parents[1] / "kalshi_bitcoin_perps_2026-10-23/operations/remote.py"
        guard = types.ModuleType("capacity_test_original_guard")
        exec(compile(source.read_text(), str(source), "exec"), guard.__dict__)
        guard.ROOT, guard.PROC = self.root / "installed", self.root / "proc"
        guard.ROOT.mkdir()
        guard.PYTHON, guard.SERVICES, guard.CONFIG = "/python", ("recursive-web", capacity.SERVICE), ()
        unit_root = self.root / "system"
        unit_root.mkdir()
        guard.UNIT_ROOTS = (unit_root,)
        self.write()
        properties = {}
        for service, pid, module in (("recursive-web", 11, "app.server"), (capacity.SERVICE, 12, "app.worker")):
            fragment = unit_root / (service + ".service")
            fragment.write_bytes(b"[Service]\nExecStart=/fixed\n")
            proc = guard.PROC / str(pid)
            proc.mkdir(parents=True)
            (proc / "environ").write_bytes(b"A=B\0")
            (proc / "cmdline").write_bytes(("/python\0-m\0" + module + ("\0agents" if service == capacity.SERVICE else "") + "\0").encode())
            (proc / "stat").write_text(str(pid) + " (python) S" + " 0" * 25)
            (proc / "cwd").symlink_to(guard.ROOT, target_is_directory=True)
            properties[service] = {name: "0" for name in guard.PROPERTIES}
            properties[service].update(MainPID=str(pid), ActiveState="active", SubState="running", Restart="always",
                NeedDaemonReload="no", FragmentPath=str(fragment), DropInPaths=str(self.path) if service == capacity.SERVICE else "")
        def command(args, **kwargs):
            values = properties[args[2]]
            return types.SimpleNamespace(stdout="\n".join(k + "=" + v for k, v in values.items()).encode())
        guard.subprocess = types.SimpleNamespace(run=command)
        original_fstat = os.fstat
        with patch.object(os, "fstat", side_effect=lambda fd: RootInfo(original_fstat(fd))):
            with self.assertRaisesRegex(guard.InspectionError, "unrecognized_unit_file"):
                guard.unit_state()
            capacity.install_guard_exception(guard)
            state, private = guard.unit_state()
            self.assertIn(str(self.path), state["unit_files"])
            self.assertEqual(private[capacity.SERVICE], {"A": "B"})
            foreign = self.path.parent / "other.conf"
            foreign.write_bytes(capacity.VALID_CONTENTS[0])
            properties[capacity.SERVICE]["DropInPaths"] += " " + str(foreign)
            with self.assertRaisesRegex(guard.InspectionError, "unrecognized_unit_file"):
                guard.unit_state()
            properties[capacity.SERVICE]["DropInPaths"] = str(self.path)
            properties[capacity.SERVICE]["FragmentPath"] = str(self.path / (capacity.UNIT))
            with self.assertRaisesRegex(capacity.CapacityError, "capacity_override_descendant_rejected"):
                guard.unit_state()


class LimitProjectionTests(unittest.TestCase):
    def test_fixed_cgroup_pid_and_all_requested_properties_are_required(self):
        guard = types.SimpleNamespace(PROPERTIES=("MainPID", "MemoryMax", "DropInPaths", "Environment"), PROC=Path("/proc"))
        values = {"MainPID": "123", "MemoryMax": str(capacity.OLD_MAX), "EffectiveMemoryMax": str(capacity.OLD_MAX),
                  "ControlGroup": capacity.CGROUP, "DropInPaths": "", "Environment": PRIVATE}
        def command(args, *, timeout):
            self.assertEqual(args[:3], ["systemctl", "show", "recursive-agents.service"])
            self.assertEqual(timeout, 3)
            return "\n".join(k + "=" + v for k, v in values.items()).encode()
        def kernel(path):
            if path.name == "memory.max":
                return str(capacity.OLD_MAX) + "\n" if path.parent.name == capacity.UNIT else "max\n"
            return "0::" + capacity.CGROUP + "\n"
        with patch.object(capacity, "_safe_parents"), patch.object(capacity, "_small_kernel_file", side_effect=kernel), \
                patch.object(capacity.Path, "lstat", return_value=types.SimpleNamespace(st_dev=1, st_ino=2)), \
                patch.object(capacity, "_physical_total", return_value=16 * 1024**3):
            observed = capacity.observe_limits(guard, command)
            self.assertEqual(capacity._public_limits(observed)["cgroup_max"], capacity.OLD_MAX)
            self.assertNotIn(PRIVATE, json.dumps(capacity._public_limits(observed)))
            values["ControlGroup"] = "/system.slice/another.service"
            with self.assertRaisesRegex(capacity.CapacityError, "capacity_cgroup_not_fixed"):
                capacity.observe_limits(guard, command)
            values["ControlGroup"] = capacity.CGROUP
            del values["EffectiveMemoryMax"]
            self.assertEqual(capacity.observe_limits(guard, command)["effective_source"], "kernel_hierarchy")
            values["EffectiveMemoryMax"] = ""
            self.assertEqual(capacity.observe_limits(guard, command)["effective_max"], capacity.OLD_MAX)
            for invalid in ("[not set]", "infinity", "999", "private"):
                values["EffectiveMemoryMax"] = invalid
                with self.assertRaisesRegex(capacity.CapacityError, "capacity_projection_invalid"):
                    capacity.observe_limits(guard, command)

    def test_limiting_ancestor_is_rejected_even_when_old_worker_effective_limit_matches(self):
        guard = types.SimpleNamespace(PROPERTIES=("MainPID", "MemoryMax", "DropInPaths"), PROC=Path("/proc"))
        values = {"MainPID": "123", "MemoryMax": str(capacity.OLD_MAX), "ControlGroup": capacity.CGROUP, "DropInPaths": ""}
        command = lambda *a, **kw: "\n".join(k + "=" + v for k, v in values.items()).encode()
        def kernel(path):
            return str(capacity.OLD_MAX if path.parent.name == capacity.UNIT else capacity.NEW_MAX - 1) + "\n"
        with patch.object(capacity, "_safe_parents"), patch.object(capacity, "_small_kernel_file", side_effect=kernel), \
                patch.object(capacity.Path, "lstat", return_value=types.SimpleNamespace(st_dev=1, st_ino=2)):
            with self.assertRaisesRegex(capacity.CapacityError, "capacity_ancestor_limit_insufficient"):
                capacity.observe_limits(guard, command, physical_total=16 * 1024**3)


class CompatibilityProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE)
        self.root = Path(self.temp.name)
        self.groups, self.proc = self.root / "cgroup", self.root / "proc"
        self.worker = self.groups / capacity.CGROUP.lstrip("/") / "memory.max"
        self.parent = self.worker.parent.parent / "memory.max"
        self.mapping = self.proc / "123/cgroup"
        self.worker.parent.mkdir(parents=True)
        self.mapping.parent.mkdir(parents=True)
        self.worker.write_text(str(capacity.OLD_MAX) + "\n")
        self.parent.write_text("max\n")
        self.mapping.write_text("0::" + capacity.CGROUP + "\n")
        self.guard = types.SimpleNamespace(PROPERTIES=("MainPID", "MemoryMax", "Environment", "ExecStart", "CPUWeight", "DropInPaths"), PROC=self.proc)
        self.values = {"MainPID": "123", "MemoryMax": str(capacity.OLD_MAX), "Environment": PRIVATE,
                       "ExecStart": "/python " + PRIVATE, "CPUWeight": "100", "DropInPaths": "",
                       "ControlGroup": capacity.CGROUP, "EffectiveMemoryMax": ""}
        self.calls, self.uid = [], 0
        self.original_lstat, self.original_fstat = Path.lstat, os.fstat
        self.inode = self.mapping.stat().st_ino
        owner = self
        class Info(RootInfo):
            def __getattr__(inner, name):
                if name == "st_uid" and inner.original.st_ino == owner.inode:
                    return owner.uid
                return super().__getattr__(name)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(capacity, "CGROUP_ROOT", self.groups))
        self.stack.enter_context(patch.object(capacity.Path, "lstat", lambda path, *a, **kw: Info(self.original_lstat(path, *a, **kw))))
        self.stack.enter_context(patch.object(os, "fstat", side_effect=lambda fd: Info(self.original_fstat(fd))))
        self.stack.enter_context(patch.object(capacity, "_physical_total", return_value=16 * 1024**3))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def command(self, args, *, timeout):
        self.calls.append((args, timeout))
        return "\n".join(k + "=" + v for k, v in self.values.items()).encode()

    def probe(self, command=None):
        result = capacity.compatibility_probe(self.guard, command or self.command)
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assertTrue(result["diagnostic_only"] and result["read_only"])
        for field in ("service_operations", "job_mutations", "provider_calls_from_operations", "property_command_attempts"):
            self.assertEqual(result[field], 0)
        self.assertFalse(result["mutation_may_have_applied"])
        return result

    def test_one_fixed_show_read_and_bounded_read_only_file_opens(self):
        original_open, opened = os.open, []
        def read_only(path, flags, *args, **kwargs):
            opened.append((Path(path), flags))
            self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)
            self.assertFalse(flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            self.assertTrue(flags & os.O_NOFOLLOW)
            return original_open(path, flags, *args, **kwargs)
        with patch.object(os, "open", side_effect=read_only):
            result = self.probe()
        self.assertEqual(len(self.calls), 1)
        args, timeout = self.calls[0]
        self.assertEqual(args[:3], ["systemctl", "show", "recursive-agents.service"])
        self.assertEqual(timeout, 3)
        self.assertNotIn("--all", args)
        self.assertEqual({path for path, flags in opened}, {self.worker, self.parent, self.mapping})
        self.assertTrue(result["systemd"]["required_properties_present"])
        self.assertEqual(result["computed_effective_limit_bytes"], capacity.OLD_MAX)
        self.assertTrue(result["files"]["worker_proc_cgroup"]["exact_observer_membership"])

    def test_missing_required_empty_properties_are_distinguished_from_optional_absence(self):
        del self.values["Environment"]
        del self.values["DropInPaths"]
        del self.values["EffectiveMemoryMax"]
        result = self.probe()
        fields = result["systemd"]["properties"]
        self.assertFalse(fields["Environment"]["present"] or fields["DropInPaths"]["present"])
        self.assertFalse(result["systemd"]["required_properties_present"])
        self.assertFalse(fields["EffectiveMemoryMax"]["present"])
        self.assertTrue(result["files"]["worker_memory_max"]["read_format_valid"])
        self.values["Environment"] = self.values["DropInPaths"] = ""
        result = self.probe()
        self.assertTrue(result["systemd"]["required_properties_present"])
        self.assertFalse(result["systemd"]["effective_property_nonempty"])

    def test_nonroot_proc_owner_is_reported_without_relaxing_the_observer(self):
        self.uid = 1001
        result = self.probe()
        proc = result["files"]["worker_proc_cgroup"]
        self.assertTrue(proc["exists"] and proc["regular_file"] and proc["read_format_valid"])
        self.assertFalse(proc["root_owner"] or proc["observer_metadata_accepted"])
        self.assertTrue(proc["exact_observer_membership"])

    def test_unified_v1_hybrid_and_wrong_membership_never_return_mapping_text(self):
        cases = [("0::" + capacity.CGROUP + "\n", True, False, True),
                 ("5:memory:" + capacity.CGROUP + "\n", False, True, False),
                 ("0::" + capacity.CGROUP + "\n5:memory:" + capacity.CGROUP + "\n", True, True, False),
                 ("0::/user.slice/" + PRIVATE + "\n", True, False, False)]
        for text, unified, memory_v1, exact in cases:
            with self.subTest(unified=unified, memory_v1=memory_v1, exact=exact):
                self.mapping.write_text(text)
                proc = self.probe()["files"]["worker_proc_cgroup"]
                self.assertEqual(proc["unified_mapping_present"], unified)
                self.assertEqual(proc["v1_memory_mapping_present"], memory_v1)
                self.assertEqual(proc["exact_observer_membership"], exact)

    def test_private_malformed_unknown_or_duplicate_property_rows_are_redacted(self):
        for raw in (b"Environment=secret\x00value\n", b"\xff" + PRIVATE.encode(),
                    ("PRIVATE_TOKEN=" + PRIVATE + "\nMainPID=123\nMainPID=124\n").encode()):
            with self.subTest(raw_length=len(raw)):
                result = self.probe(lambda *a, **kw: raw)
                self.assertFalse(result["systemd"]["rows_valid"])
                self.assertNotIn("PRIVATE_TOKEN", json.dumps(result))
                self.assertFalse(result["systemd"]["numeric_valid"]["MainPID"])

    def test_invalid_numeric_pid_or_control_group_cannot_select_an_arbitrary_file(self):
        self.values["MainPID"] = "../../" + PRIVATE
        self.values["MemoryMax"] = PRIVATE
        self.values["ControlGroup"] = "/" + PRIVATE
        result = self.probe()
        self.assertFalse(result["systemd"]["control_group_matches_fixed"])
        self.assertEqual(result["systemd"]["numeric_values"], {})
        self.assertFalse(result["files"]["worker_proc_cgroup"]["probed"])

    def test_missing_symlink_and_bad_format_files_have_only_safe_metadata(self):
        self.worker.unlink()
        self.parent.write_text(PRIVATE)
        result = self.probe()
        self.assertFalse(result["files"]["worker_memory_max"]["exists"])
        self.assertEqual(result["files"]["worker_memory_max"]["error_code"], "capacity_probe_file_missing")
        self.assertFalse(result["files"]["parent_memory_max"]["read_format_valid"])
        self.worker.symlink_to(self.parent)
        result = self.probe()
        self.assertTrue(result["files"]["worker_memory_max"]["exists"])
        self.assertFalse(result["files"]["worker_memory_max"]["regular_file"])
        self.assertFalse(result["files"]["worker_memory_max"]["read_succeeded"])

    def test_bounded_response_and_command_exceptions_never_reveal_raw_errors(self):
        for source in (lambda *a, **kw: PRIVATE.encode() * (1024 * 1024),
                       lambda *a, **kw: (_ for _ in ()).throw(RuntimeError(PRIVATE))):
            result = self.probe(source)
            self.assertIn(result["systemd"]["error_code"],
                          ("capacity_probe_response_invalid", "capacity_probe_systemd_read_failed"))
            self.assertFalse(result["systemd"]["required_properties_present"])

    def test_effective_value_is_numeric_only_and_must_agree_with_kernel_bound(self):
        self.values["EffectiveMemoryMax"] = "123"
        result = self.probe()
        self.assertTrue(result["systemd"]["numeric_valid"]["EffectiveMemoryMax"])
        self.assertFalse(result["reported_effective_limit_matches"])
        self.values["EffectiveMemoryMax"] = PRIVATE
        result = self.probe()
        self.assertFalse(result["systemd"]["numeric_valid"]["EffectiveMemoryMax"])
        self.assertFalse(result["reported_effective_limit_matches"])


if __name__ == "__main__":
    unittest.main()
