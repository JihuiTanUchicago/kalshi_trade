"""One approved online worker MemoryMax increase; never restart, retry or lower."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import re
import shlex
import stat

import remote


SERVICE = "recursive-agents"
UNIT = SERVICE + ".service"
OLD_MAX = 419430400
NEW_MAX = 1073741824
MIN_TOTAL = 12 * 1024**3
MIN_AVAILABLE = 8 * 1024**3
CGROUP = "/system.slice/" + UNIT
CGROUP_ROOT = Path("/sys/fs/cgroup")
OVERRIDE = Path("/etc/systemd/system.control") / (UNIT + ".d/50-MemoryMax.conf")
HEADER = (b'# This is a drop-in unit file extension, created via "systemctl set-property"\n'
          b"# or an equivalent operation. Do not edit.\n")
BODY = b"[Service]\nMemoryMax=1073741824\n"
VALID_CONTENTS = (HEADER + BODY, HEADER + BODY + b"\n")
# Inventory 39903498965 proves only these requested properties are omitted.
# Preserve omission in the raw dictionary; never manufacture empty hash inputs.
OPTIONAL_PROPERTIES = frozenset({"EnvironmentFiles", "EffectiveMemoryMax"})
ERRORS = frozenset({
    "capacity_baseline_conflict", "capacity_override_already_present", "capacity_override_unsafe",
    "capacity_override_body_unrecognized", "capacity_override_descendant_rejected",
    "capacity_worker_not_active", "capacity_old_limit_not_exact", "capacity_cgroup_not_fixed",
    "capacity_oom_evidence_not_exact", "capacity_host_headroom_insufficient",
    "capacity_projection_invalid", "capacity_state_changed_before_command",
    "capacity_command_uncertain", "capacity_post_state_not_exact", "capacity_new_limit_not_exact",
    "capacity_override_missing_after_command", "capacity_command_context_invalid",
    "capacity_worker_property_generation_changed",
    "capacity_ancestor_limit_insufficient",
})


class CapacityError(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise CapacityError(code)


def _original_reader(guard):
    return getattr(guard, "_capacity_original_read_regular", guard.read_regular)


def _safe_parents(path):
    for parent in reversed(path.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            return
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_gid == 0
                and not info.st_mode & 0o022, "capacity_override_unsafe")


def override_metadata(guard):
    """Validate the exact path, full bytes and metadata; return no file contents."""
    _safe_parents(OVERRIDE)
    try:
        before = OVERRIDE.lstat()
    except FileNotFoundError:
        return None
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_uid == 0 and before.st_gid == 0
            and stat.S_IMODE(before.st_mode) in (0o600, 0o644), "capacity_override_unsafe")
    raw, meta = _original_reader(guard)(OVERRIDE, 4096, owners=(0,))
    signature = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns,
                             row.st_mode, row.st_uid, row.st_gid, row.st_nlink)
    require(signature(before) == signature(OVERRIDE.lstat()) and len(raw) == before.st_size
            and meta == {"uid": 0, "gid": 0, "mode": format(stat.S_IMODE(before.st_mode), "04o")},
            "capacity_override_unsafe")
    require(raw in VALID_CONTENTS, "capacity_override_body_unrecognized")
    return {"sha256": remote.digest(raw), "bytes": len(raw), **meta}


def install_guard_exception(guard):
    """Add one validated regular-file root, never its directory or descendants.

    The unchanged guard still checks every source, unit and protected file. Its
    reader is fenced so a later replacement cannot turn this file into a tree.
    Call again after the single command and before snapshots in later phases.
    """
    if not hasattr(guard, "_capacity_original_read_regular"):
        guard._capacity_original_read_regular = guard.read_regular
        guard._capacity_original_unit_roots = tuple(guard.UNIT_ROOTS)

        def read_regular(path, *args, **kwargs):
            path = Path(path)
            if path == OVERRIDE:
                expected = override_metadata(guard)
                require(expected is not None, "capacity_override_unsafe")
                raw, meta = guard._capacity_original_read_regular(path, *args, **kwargs)
                require(remote.digest(raw) == expected["sha256"] and len(raw) == expected["bytes"]
                        and meta == {key: expected[key] for key in ("uid", "gid", "mode")},
                        "capacity_override_unsafe")
                return raw, meta
            require(not path.is_relative_to(OVERRIDE), "capacity_override_descendant_rejected")
            return guard._capacity_original_read_regular(path, *args, **kwargs)

        guard.read_regular = read_regular
    result = override_metadata(guard)
    guard.UNIT_ROOTS = guard._capacity_original_unit_roots + (() if result is None else (OVERRIDE,))
    return result


def _small_kernel_file(path):
    """Bounded read of fixed proc/cgroup files whose reported size can be zero."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                "capacity_projection_invalid")
        raw = stream.read(4097)
        require(len(raw) <= 4096, "capacity_projection_invalid")
        return raw.decode("ascii")


def _physical_total():
    values = []
    with Path("/proc/meminfo").open("rb") as stream:
        raw = stream.read(65537)
    require(len(raw) <= 65536, "capacity_projection_invalid")
    for line in raw.decode("ascii").splitlines():
        if line.startswith("MemTotal:"):
            match = re.fullmatch(r"MemTotal:\s*([0-9]{1,17}) kB\s*", line)
            require(match is not None, "capacity_projection_invalid")
            values.append(int(match[1]) * 1024)
    require(len(values) == 1 and 0 < values[0] < 2**64, "capacity_projection_invalid")
    return values[0]


def observe_limits(guard, command, *, physical_total=None):
    """Keep the full worker property projection private; expose numeric limits only."""
    names = tuple(dict.fromkeys((*guard.PROPERTIES, "ControlGroup", "EffectiveMemoryMax")))
    raw = command(["systemctl", "show", UNIT, "--property=" + ",".join(names)], timeout=3)
    require(isinstance(raw, bytes) and len(raw) <= 1024 * 1024, "capacity_projection_invalid")
    values = {}
    for line in raw.decode().splitlines():
        name, delimiter, value = line.partition("=")
        require(delimiter and name in names and name not in values, "capacity_projection_invalid")
        values[name] = value
    require(set(names) - OPTIONAL_PROPERTIES <= set(values) <= set(names), "capacity_projection_invalid")
    require(values["ControlGroup"] == CGROUP, "capacity_cgroup_not_fixed")
    for key in ("MemoryMax", "MainPID"):
        require(re.fullmatch(r"[0-9]{1,20}", values[key]) and int(values[key]) < 2**64,
                "capacity_projection_invalid")
    pid = int(values["MainPID"])
    require(pid > 0, "capacity_worker_not_active")
    group = CGROUP_ROOT / CGROUP.lstrip("/")
    _safe_parents(group / "memory.max")
    identity = group.lstat()
    raw_max = _small_kernel_file(group / "memory.max")
    require(re.fullmatch(r"[0-9]{1,20}\n?", raw_max) and int(raw_max) < 2**64, "capacity_projection_invalid")
    ancestor = group.parent
    ancestor_identity = ancestor.lstat()
    raw_parent = _small_kernel_file(ancestor / "memory.max")
    require(re.fullmatch(r"(?:max|[0-9]{1,20})\n?", raw_parent), "capacity_projection_invalid")
    parent_max = None if raw_parent.strip() == "max" else int(raw_parent)
    require(parent_max is None or NEW_MAX <= parent_max < 2**64, "capacity_ancestor_limit_insufficient")
    total = _physical_total() if physical_total is None else physical_total
    require(type(total) is int and MIN_TOTAL <= total < 2**64, "capacity_projection_invalid")
    effective = min([int(raw_max), total] + ([] if parent_max is None else [parent_max]))
    systemd_effective = values.get("EffectiveMemoryMax", "")
    if systemd_effective:
        require(re.fullmatch(r"[0-9]{1,20}", systemd_effective) and int(systemd_effective) == effective,
                "capacity_projection_invalid")
    require(_small_kernel_file(guard.PROC / str(pid) / "cgroup") == "0::" + CGROUP + "\n",
            "capacity_cgroup_not_fixed")
    return {"configured_max": int(values["MemoryMax"]), "effective_max": effective,
            "cgroup_max": int(raw_max), "pid": pid, "cgroup_identity": (identity.st_dev, identity.st_ino),
            "ancestor_max": parent_max, "ancestor_identity": (ancestor_identity.st_dev, ancestor_identity.st_ino),
            "physical_total": total, "effective_source": "kernel_hierarchy_and_systemd" if systemd_effective else "kernel_hierarchy",
            "private_properties": values}


def _counts(projection):
    value = projection.get("job_counts")
    require(isinstance(value, dict) and set(value) == {"queued", "running", "paused"}
            and all(type(n) is int and n >= 0 for n in value.values()), "capacity_projection_invalid")
    return dict(value)


def _pressure(report, pins):
    value = report.get("memory_pressure", {})
    host, events = value.get("host_bytes", {}), value.get("kernel_events_last_30m", {})
    require("host_error_code" not in value and all(type(host.get(key)) is int for key in ("MemTotal", "MemAvailable"))
            and host["MemTotal"] >= MIN_TOTAL and MIN_AVAILABLE <= host["MemAvailable"] <= host["MemTotal"],
            "capacity_host_headroom_insufficient")
    names = ("worker_limit", "ancestor_limit", "global_constraint", "unclassified_memcg", "cgroup_constraint")
    require("kernel_error_code" not in value and all(type(events.get(key)) is int and events[key] >= 0 for key in names)
            and events["cgroup_constraint"] >= events["worker_limit"]
            and all(events[key] == 0 for key in ("ancestor_limit", "global_constraint", "unclassified_memcg")),
            "capacity_oom_evidence_not_exact")
    evidence = {"host_bytes": {key: host[key] for key in ("MemTotal", "MemAvailable")},
                "kernel_events_last_30m": {key: events[key] for key in names},
                "cause_source": "current_kernel_window"}
    if events["worker_limit"] == 0:
        # Only this reviewed cause receipt survives its rolling journal window.
        # Missing/unavailable current evidence never becomes a zero-event result.
        prior = pins.get("capacity_approved_oom_evidence")
        expected = {"worker_limit": 2, "cgroup_constraint": 2, "ancestor_limit": 0,
                    "global_constraint": 0, "unclassified_memcg": 0}
        observed = report.get("observed_units", {}).get(SERVICE, {}).get("pid")
        baseline = pins.get("installed", {}).get("controls", {}).get("units", {}).get(SERVICE, {}).get("pid")
        require(isinstance(prior, dict) and set(prior) == {"run_id", "receipt_sha256", "worker_pid", "kernel_events_last_30m"}
                and type(prior.get("run_id")) is int and prior["run_id"] == 39901486782
                and prior.get("receipt_sha256") == "510b943f8b0f0b03cae635d10406839d7479fea9b96633ae2e2a4771c4f0abb4"
                and type(prior.get("worker_pid")) is int and type(observed) is int and type(baseline) is int
                and prior["worker_pid"] == observed == baseline == 507858
                and isinstance(prior.get("kernel_events_last_30m"), dict)
                and set(prior["kernel_events_last_30m"]) == set(expected)
                and all(type(prior["kernel_events_last_30m"][key]) is int
                        and prior["kernel_events_last_30m"][key] == expected[key] for key in expected)
                and events["cgroup_constraint"] == 0, "capacity_oom_evidence_not_exact")
        evidence.update(cause_source="approved_prior_receipt", approved_prior_oom_evidence=copy.deepcopy(prior))
    return evidence


def _bind_worker_properties(state, limits, guard):
    properties = limits["private_properties"]
    require(set(guard.PROPERTIES) - OPTIONAL_PROPERTIES <= set(properties), "capacity_projection_invalid")
    projection = {name: properties[name] for name in guard.PROPERTIES if name in properties}
    require(remote.fingerprint(projection) == state["controls"]["units"][SERVICE]["properties_sha256"],
            "capacity_worker_property_generation_changed")


def _old_worker(state, limits, guard):
    _bind_worker_properties(state, limits, guard)
    worker = state["controls"]["units"][SERVICE]
    require(worker["active_state"] == "active" and worker["sub_state"] == "running"
            and type(worker["pid"]) is int and worker["pid"] > 0 and worker["pid"] == limits["pid"],
            "capacity_worker_not_active")
    require(worker["resources"]["MemoryMax"] == str(OLD_MAX)
            and all(limits[key] == OLD_MAX for key in ("configured_max", "effective_max", "cgroup_max")),
            "capacity_old_limit_not_exact")


def _public_limits(value):
    return {key: value[key] for key in ("configured_max", "effective_max", "cgroup_max", "pid", "ancestor_max",
                                      "physical_total", "effective_source")}


def _verify_after(before, private_before, after, private_after, old_limits, new_limits, override, guard):
    _bind_worker_properties(after, new_limits, guard)
    require(remote.source_files(after) == remote.source_files(before) and private_after == private_before,
            "capacity_post_state_not_exact")
    expected = copy.deepcopy(before["controls"])
    worker = expected["units"][SERVICE]
    observed = after["controls"]["units"][SERVICE]
    require(re.fullmatch(r"[0-9a-f]{64}", observed["properties_sha256"])
            and observed["properties_sha256"] != worker["properties_sha256"], "capacity_post_state_not_exact")
    worker["properties_sha256"] = observed["properties_sha256"]
    worker["resources"]["MemoryMax"] = str(NEW_MAX)
    expected["unit_files"][str(OVERRIDE)] = {key: override[key] for key in ("sha256", "uid", "gid", "mode")}
    require(after["controls"] == expected, "capacity_post_state_not_exact")
    require(new_limits["pid"] == old_limits["pid"] and new_limits["cgroup_identity"] == old_limits["cgroup_identity"]
            and all(new_limits[key] == old_limits[key] for key in ("ancestor_max", "ancestor_identity", "physical_total"))
            and all(new_limits[key] == NEW_MAX for key in ("configured_max", "effective_max", "cgroup_max")),
            "capacity_new_limit_not_exact")
    properties = dict(old_limits["private_properties"])
    properties["MemoryMax"] = str(NEW_MAX)
    if properties.get("EffectiveMemoryMax", ""):
        properties["EffectiveMemoryMax"] = str(NEW_MAX)
    prior_paths = shlex.split(properties["DropInPaths"])
    actual_paths = shlex.split(new_limits["private_properties"]["DropInPaths"])
    require(str(OVERRIDE) not in prior_paths and len(actual_paths) == len(prior_paths) + 1
            and set(actual_paths) == {*prior_paths, str(OVERRIDE)}, "capacity_post_state_not_exact")
    properties["DropInPaths"] = new_limits["private_properties"]["DropInPaths"]
    require(properties == new_limits["private_properties"], "capacity_post_state_not_exact")


def run(backend, pins, *, command=None):
    """Apply once online when all gates match; jobs may continue unmodified."""
    command = command or remote.command
    result = {"status": "capacity_requires_inspection", "candidate": pins["candidate"],
              "mutation_may_have_applied": False, "override_added": False, "resource_change_verified": False,
              "no_service_restart": False, "service_restart_requested": False, "property_command_attempts": 0,
              "resource_property_commands": 0,
              "application_changes": False, "service_operations": 0, "service_restart_operations": 0, "job_mutations": 0,
              "provider_calls_from_operations": 0, "stability_observation_required_seconds": 900,
              "stability_observation_completed": False, "perps_release_activated": False}
    attempted, command_failed = False, False
    try:
        report, before, private_before = remote.inventory(backend, pins)
        require(not report["conflicts"], "capacity_baseline_conflict")
        result["job_counts_before"] = _counts(report)
        require(override_metadata(backend.guard) is None, "capacity_override_already_present")
        result["evidence"] = _pressure(report, pins)
        limits = observe_limits(backend.guard, command, physical_total=result["evidence"]["host_bytes"]["MemTotal"])
        _old_worker(before, limits, backend.guard)
        # A live increase does not interrupt work. Count changes are recorded,
        # never blocked by modifying jobs or disabling admission/autopilot.
        fresh, current, private_current = remote.inventory(backend, pins)
        require(not fresh["conflicts"] and remote.stable_state(current) == remote.stable_state(before)
                and private_current == private_before, "capacity_state_changed_before_command")
        result["evidence"] = _pressure(fresh, pins)
        latest_limits = observe_limits(backend.guard, command, physical_total=result["evidence"]["host_bytes"]["MemTotal"])
        _old_worker(current, latest_limits, backend.guard)
        require(latest_limits == limits, "capacity_state_changed_before_command")
        result["job_counts_immediately_before"] = _counts(backend.inspect(private_current[SERVICE]))
        require(override_metadata(backend.guard) is None, "capacity_override_already_present")
        result["before_fingerprint"] = remote.fingerprint(current)
        result["limits_before"] = _public_limits(latest_limits)
        attempted = True
        result.update(mutation_may_have_applied=True, property_command_attempts=1, resource_property_commands=1,
                      service_operations=1)
        try:
            command(["systemctl", "set-property", UNIT, "MemoryMax=" + str(NEW_MAX)], timeout=8)
        except Exception:
            command_failed = True
        # Reinspect even a timeout: runtime and persistence may differ. Nothing
        # here retries the write, deletes its override or restores a lower cap.
        override_error = False
        try:
            override = install_guard_exception(backend.guard)
            result["override_added"] = override is not None
            if override is not None:
                result["override"] = override
        except Exception:
            override_error, override = True, None
        new_limits = observe_limits(backend.guard, command)
        result["limits_after"] = _public_limits(new_limits)
        require(not override_error and override is not None, "capacity_override_missing_after_command")
        after, private_after = backend.snapshot()
        _verify_after(before, private_before, after, private_after, limits, new_limits, override, backend.guard)
        result["job_counts_after"] = _counts(backend.inspect(private_after[SERVICE]))
        result.update(resource_change_verified=True, no_service_restart=True,
                      after_fingerprint=remote.fingerprint(after), observed_controls=after["controls"],
                      source_fingerprint=remote.fingerprint(remote.source_files(after)))
        require(not command_failed, "capacity_command_uncertain")
        result["status"] = "capacity_verified"
        return result
    except Exception as exc:
        result["error_code"] = str(exc) if isinstance(exc, CapacityError) and str(exc) in ERRORS else "capacity_operation_failed"
        result["mutation_may_have_applied"] = attempted
        return result


def compatibility_probe(guard, command=None):
    """Read-only diagnosis of observer gates; never expose raw property/mapping values.

    Deliberately retain the original query without --all. This probe neither
    repairs omitted properties nor relaxes any capacity write precondition.
    """
    command = command or remote.command
    known = ("MainPID", "ActiveState", "SubState", "FragmentPath", "DropInPaths", "NeedDaemonReload",
             "Restart", "RestartUSec", "Environment", "EnvironmentFiles", "ExecStart", "MemoryHigh",
             "MemoryMax", "MemorySwapMax", "CPUQuotaPerSecUSec", "CPUWeight", "TasksMax", "Nice",
             "ControlGroup", "EffectiveMemoryMax")
    result = {"status": "capacity_compatibility_observed", "diagnostic_only": True, "read_only": True,
              "application_changes": False, "service_operations": 0, "job_mutations": 0,
              "provider_calls_from_operations": 0, "property_command_attempts": 0,
              "mutation_may_have_applied": False}
    systemd = {"command_succeeded": False, "response_within_limit": False, "utf8_valid": False,
               "rows_valid": False, "unexpected_rows_present": False, "duplicate_rows_present": False,
               "required_properties_present": False, "control_group_matches_fixed": False,
               "properties": {name: {"requested": False, "present": False, "row_valid": False} for name in known},
               "numeric_valid": {name: False for name in ("MainPID", "MemoryMax", "EffectiveMemoryMax")},
               "numeric_values": {}, "effective_property_nonempty": False}
    result["systemd"] = systemd
    values, duplicated = {}, set()
    try:
        names = tuple(dict.fromkeys((*guard.PROPERTIES, "ControlGroup", "EffectiveMemoryMax")))
        if not names or not set(names) <= set(known):
            systemd["error_code"] = "capacity_probe_guard_projection_unsupported"
        else:
            for name in names:
                systemd["properties"][name]["requested"] = True
            raw = command(["systemctl", "show", UNIT, "--property=" + ",".join(names)], timeout=3)
            systemd["command_succeeded"] = True
            if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
                systemd["error_code"] = "capacity_probe_response_invalid"
            else:
                systemd["response_within_limit"] = True
                text = raw.decode("utf-8")
                systemd["utf8_valid"] = True
                rows_valid = True
                for line in text.splitlines():
                    name, delimiter, value = line.partition("=")
                    if not delimiter or name not in names or "\x00" in value:
                        rows_valid = False
                        systemd["unexpected_rows_present"] = True
                        continue
                    systemd["properties"][name]["present"] = True
                    if name in values:
                        rows_valid = False
                        duplicated.add(name)
                        systemd["duplicate_rows_present"] = True
                    else:
                        values[name] = value
                        systemd["properties"][name]["row_valid"] = True
                for name in duplicated:
                    systemd["properties"][name]["row_valid"] = False
                systemd["rows_valid"] = rows_valid
                systemd["required_properties_present"] = set(names) - OPTIONAL_PROPERTIES <= set(values)
    except Exception:
        systemd["error_code"] = "capacity_probe_systemd_read_failed"
    for name in ("MainPID", "MemoryMax", "EffectiveMemoryMax"):
        value = values.get(name, "")
        if name not in duplicated and re.fullmatch(r"[0-9]{1,20}", value) and int(value) < 2**64:
            systemd["numeric_valid"][name] = True
            systemd["numeric_values"][name] = int(value)
    systemd["effective_property_nonempty"] = bool(values.get("EffectiveMemoryMax", ""))
    systemd["control_group_matches_fixed"] = "ControlGroup" not in duplicated and values.get("ControlGroup") == CGROUP

    def file_probe(path, kind):
        item = {"exists": False, "metadata_observed": False, "regular_file": False,
                "root_owner": False, "root_group": False, "not_group_or_other_writable": False,
                "parents_no_symlinks": True, "parents_root_safe": True, "read_succeeded": False,
                "metadata_stable": False, "read_format_valid": False, "observer_metadata_accepted": False}
        try:
            for parent in reversed(path.parents):
                info = parent.lstat()
                directory = stat.S_ISDIR(info.st_mode)
                item["parents_no_symlinks"] &= directory
                item["parents_root_safe"] &= directory and info.st_uid == 0 and info.st_gid == 0 and not info.st_mode & 0o022
            first = path.lstat()
            item.update(exists=True, metadata_observed=True, regular_file=stat.S_ISREG(first.st_mode),
                        root_owner=first.st_uid == 0, root_group=first.st_gid == 0,
                        not_group_or_other_writable=not bool(first.st_mode & 0o022))
            if not item["regular_file"] or not item["parents_no_symlinks"]:
                item["error_code"] = "capacity_probe_file_type_rejected"
                return item
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode):
                    item["error_code"] = "capacity_probe_file_type_rejected"
                    return item
                content = stream.read(4097)
                last = os.fstat(stream.fileno())
            identity = lambda info: (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)
            item["metadata_stable"] = identity(first) == identity(opened) == identity(last) == identity(path.lstat())
            if len(content) > 4096:
                item["error_code"] = "capacity_probe_file_read_invalid"
                return item
            text = content.decode("ascii")
            item["read_succeeded"] = True
            item["observer_metadata_accepted"] = (item["metadata_stable"] and item["root_owner"]
                and item["not_group_or_other_writable"] and (kind == "proc" or item["parents_root_safe"]))
            if kind in ("worker", "parent"):
                numeric = re.fullmatch(r"[0-9]{1,20}\n?", text)
                unlimited = text in ("max", "max\n")
                item["unlimited"] = unlimited
                item["read_format_valid"] = bool(numeric and int(text) < 2**64 or kind == "parent" and unlimited)
                if numeric and int(text) < 2**64:
                    item["limit_bytes"] = int(text)
                if kind == "parent":
                    item["permits_new_limit"] = unlimited or bool(numeric and NEW_MAX <= int(text) < 2**64)
            else:
                item.update(unified_mapping_present=False, v1_memory_mapping_present=False,
                            unified_worker_membership=False, v1_memory_worker_membership=False,
                            exact_observer_membership=text == "0::" + CGROUP + "\n")
                lines = text.splitlines()
                item["read_format_valid"] = bool(lines)
                for line in lines:
                    match = re.fullmatch(r"([0-9]{1,10}):([A-Za-z0-9_,.=-]*):(/[^\x00\r\n]*)", line)
                    if not match:
                        item["read_format_valid"] = False
                        continue
                    unified = match[1] == "0" and match[2] == ""
                    memory_v1 = match[1] != "0" and "memory" in match[2].split(",")
                    item["unified_mapping_present"] |= unified
                    item["v1_memory_mapping_present"] |= memory_v1
                    item["unified_worker_membership"] |= unified and match[3] == CGROUP
                    item["v1_memory_worker_membership"] |= memory_v1 and match[3] == CGROUP
            return item
        except FileNotFoundError:
            item["error_code"] = "capacity_probe_file_missing"
        except Exception:
            item["error_code"] = "capacity_probe_file_read_failed"
        return item

    group = CGROUP_ROOT / CGROUP.lstrip("/")
    files = {"worker_memory_max": file_probe(group / "memory.max", "worker"),
             "parent_memory_max": file_probe(group.parent / "memory.max", "parent")}
    pid = systemd["numeric_values"].get("MainPID", 0)
    if 0 < pid < 2**31:
        files["worker_proc_cgroup"] = file_probe(guard.PROC / str(pid) / "cgroup", "proc")
    else:
        files["worker_proc_cgroup"] = {"probed": False, "error_code": "capacity_probe_pid_invalid"}
    result["files"] = files
    physical = {"read_succeeded": False, "minimum_total_met": False}
    try:
        physical["total_bytes"] = _physical_total()
        physical["read_succeeded"] = True
        physical["minimum_total_met"] = physical["total_bytes"] >= MIN_TOTAL
    except Exception:
        physical["error_code"] = "capacity_probe_physical_read_failed"
    result["physical_memory"] = physical
    worker, parent = files["worker_memory_max"], files["parent_memory_max"]
    if worker.get("read_format_valid") and parent.get("read_format_valid") and physical["read_succeeded"]:
        limits = [worker["limit_bytes"], physical["total_bytes"]]
        if not parent["unlimited"]:
            limits.append(parent["limit_bytes"])
        result["computed_effective_limit_bytes"] = min(limits)
        result["reported_effective_limit_matches"] = (not systemd["effective_property_nonempty"] or
            systemd["numeric_values"].get("EffectiveMemoryMax") == result["computed_effective_limit_bytes"])
    return result
