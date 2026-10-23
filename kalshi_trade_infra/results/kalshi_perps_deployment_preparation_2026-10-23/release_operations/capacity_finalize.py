"""Finalize one already applied worker limit with one bounded manager reload.

No property write, service restart, job write, file change or automatic recovery
exists here. Raw unit properties and actual environments remain private in RAM.
"""
from __future__ import annotations

import copy
import shlex

import capacity
import remote


EXPECTED_APPROVAL = {
    "capacity_run_id": 39904624559,
    "capacity_receipt_sha256": "98811b3c603173748498043827bd457441ec28056dcd60a3869300b7c4742e7a",
    "inventory_run_id": 39904754786,
    "inventory_receipt_sha256": "ed13fb6e54b85c2804dd60433b43d9f936346b491cbd36b3cfcd8035c18b0572",
    "before_worker_properties_sha256": "6655e1ab35e68436fc8f202ea7266f8e00bb92ec9c44c024676bf5ca04f669f1",
    "worker_pid": 509844,
    "worker_start_ticks": "50358518",
    "override_sha256": "8714f37da811546b5c7bc1babb7172cc7a42b27eb0cea820a323ef1b6d07eb44",
}
OVERRIDE_METADATA = {"sha256": EXPECTED_APPROVAL["override_sha256"], "bytes": 152,
                     "uid": 0, "gid": 0, "mode": "0644"}
ERRORS = frozenset({
    "capacity_finalize_approval_not_exact", "capacity_finalize_baseline_conflict",
    "capacity_finalize_override_not_exact", "capacity_finalize_worker_not_exact",
    "capacity_finalize_limit_not_exact", "capacity_finalize_host_headroom_insufficient",
    "capacity_finalize_current_evidence_invalid", "capacity_finalize_original_properties_not_exact",
    "capacity_finalize_state_changed_before_command", "capacity_finalize_post_state_not_exact",
    "capacity_finalize_command_uncertain",
})


class FinalizeError(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise FinalizeError(code)


def _approval(pins):
    actual = pins.get("capacity_finalize_approval")
    require(isinstance(actual, dict) and set(actual) == set(EXPECTED_APPROVAL)
            and all(type(actual[key]) is type(value) and actual[key] == value
                    for key, value in EXPECTED_APPROVAL.items()), "capacity_finalize_approval_not_exact")


def _pressure(report):
    """Fresh typed current evidence; zero recent events is allowed after repair."""
    pressure = report.get("memory_pressure", {})
    host = pressure.get("host_bytes", {})
    events = pressure.get("kernel_events_last_30m", {})
    require("host_error_code" not in pressure
            and all(type(host.get(key)) is int for key in ("MemTotal", "MemAvailable"))
            and capacity.MIN_TOTAL <= host["MemTotal"] < 2**64
            and capacity.MIN_AVAILABLE <= host["MemAvailable"] <= host["MemTotal"],
            "capacity_finalize_host_headroom_insufficient")
    names = ("worker_limit", "ancestor_limit", "global_constraint", "unclassified_memcg", "cgroup_constraint")
    require("kernel_error_code" not in pressure
            and all(type(events.get(key)) is int and 0 <= events[key] < 2**64 for key in names)
            and events["cgroup_constraint"] == events["worker_limit"]
            and all(events[key] == 0 for key in ("ancestor_limit", "global_constraint", "unclassified_memcg")),
            "capacity_finalize_current_evidence_invalid")
    return {"host_bytes": {key: host[key] for key in ("MemTotal", "MemAvailable")},
            "kernel_events_last_30m": {key: events[key] for key in names},
            "evidence_source": "current_kernel_window"}


def _paths(properties):
    value = shlex.split(properties["DropInPaths"])
    require(len(value) == len(set(value)) and value.count(str(capacity.OVERRIDE)) == 1,
            "capacity_finalize_original_properties_not_exact")
    return value


def _override(guard, state):
    actual = capacity.install_guard_exception(guard)
    require(actual == OVERRIDE_METADATA, "capacity_finalize_override_not_exact")
    expected = {key: OVERRIDE_METADATA[key] for key in ("sha256", "uid", "gid", "mode")}
    require(state["controls"]["unit_files"].get(str(capacity.OVERRIDE)) == expected,
            "capacity_finalize_override_not_exact")
    return actual


def _worker(state, limits, guard, *, pending):
    capacity._bind_worker_properties(state, limits, guard)
    worker = state["controls"]["units"][capacity.SERVICE]
    process = state["controls"]["processes"][capacity.SERVICE]
    require(type(worker["pid"]) is int and worker["pid"] == limits["pid"] == EXPECTED_APPROVAL["worker_pid"]
            and worker["active_state"] == "active" and worker["sub_state"] == "running"
            and process["start_ticks"] == EXPECTED_APPROVAL["worker_start_ticks"]
            and worker["need_daemon_reload"] == ("yes" if pending else "no")
            and all(row["need_daemon_reload"] == "no" for name, row in state["controls"]["units"].items()
                    if name != capacity.SERVICE), "capacity_finalize_worker_not_exact")
    require(worker["resources"]["MemoryMax"] == str(capacity.NEW_MAX)
            and all(type(limits[key]) is int and limits[key] == capacity.NEW_MAX
                    for key in ("configured_max", "effective_max", "cgroup_max")),
            "capacity_finalize_limit_not_exact")


def _original_properties(limits, guard):
    properties = dict(limits["private_properties"])
    require(properties["NeedDaemonReload"] == "yes" and properties["MemoryMax"] == str(capacity.NEW_MAX),
            "capacity_finalize_original_properties_not_exact")
    paths = _paths(properties)
    properties["DropInPaths"] = " ".join(path for path in paths if path != str(capacity.OVERRIDE))
    properties["NeedDaemonReload"] = "no"
    properties["MemoryMax"] = str(capacity.OLD_MAX)
    # EffectiveMemoryMax is not part of the original guard property projection.
    # Preserve actual present keys; no --all query or fabricated empty inputs.
    projected = {key: properties[key] for key in guard.PROPERTIES if key in properties}
    require(remote.fingerprint(projected) == EXPECTED_APPROVAL["before_worker_properties_sha256"],
            "capacity_finalize_original_properties_not_exact")


def _verify_after(before, private_before, after, private_after, prior_limits, limits, guard):
    _worker(after, limits, guard, pending=False)
    require(remote.source_files(before) == remote.source_files(after) and private_before == private_after,
            "capacity_finalize_post_state_not_exact")
    expected = copy.deepcopy(before["controls"])
    worker = expected["units"][capacity.SERVICE]
    worker["need_daemon_reload"] = "no"
    worker["properties_sha256"] = after["controls"]["units"][capacity.SERVICE]["properties_sha256"]
    require(after["controls"] == expected, "capacity_finalize_post_state_not_exact")
    previous = prior_limits["private_properties"]
    current = limits["private_properties"]
    prior_paths, paths = _paths(previous), _paths(current)
    require(set(paths) == set(prior_paths), "capacity_finalize_post_state_not_exact")
    permitted = dict(previous)
    permitted["NeedDaemonReload"] = "no"
    permitted["DropInPaths"] = current["DropInPaths"]
    require(current == permitted, "capacity_finalize_post_state_not_exact")
    require({key: value for key, value in limits.items() if key != "private_properties"}
            == {key: value for key, value in prior_limits.items() if key != "private_properties"},
            "capacity_finalize_post_state_not_exact")


def run(backend, pins, *, command=None):
    """One daemon-reload for the exact accepted partial state; never retry."""
    command = command or remote.command
    result = {"status": "capacity_finalize_requires_inspection", "candidate": pins["candidate"],
              "mutation_may_have_applied": False, "property_command_attempts": 0,
              "resource_property_commands": 0, "manager_reload_attempts": 0,
              "resource_change_already_existing": True, "resource_change_verified": False,
              "no_service_restart": False, "service_restart_requested": False,
              "service_operations": 0, "service_restart_operations": 0,
              "application_changes": False, "job_mutations": 0, "provider_calls_from_operations": 0,
              "stability_observation_required_seconds": 900, "stability_observation_completed": False,
              "perps_release_activated": False}
    attempted, command_failed = False, False
    try:
        _approval(pins)
        report, before, private_before = remote.inventory(backend, pins)
        require(report["conflicts"] == ["pending_daemon_reload"], "capacity_finalize_baseline_conflict")
        _override(backend.guard, before)
        result["job_counts_before"] = capacity._counts(report)
        result["evidence_before"] = _pressure(report)
        limits = capacity.observe_limits(backend.guard, command,
            physical_total=result["evidence_before"]["host_bytes"]["MemTotal"])
        _worker(before, limits, backend.guard, pending=True)
        _original_properties(limits, backend.guard)
        fresh, current, private_current = remote.inventory(backend, pins)
        require(fresh["conflicts"] == ["pending_daemon_reload"]
                and remote.stable_state(current) == remote.stable_state(before) and private_current == private_before,
                "capacity_finalize_state_changed_before_command")
        result["evidence_immediately_before"] = _pressure(fresh)
        latest = capacity.observe_limits(backend.guard, command,
            physical_total=result["evidence_immediately_before"]["host_bytes"]["MemTotal"])
        _worker(current, latest, backend.guard, pending=True)
        _original_properties(latest, backend.guard)
        require(latest == limits, "capacity_finalize_state_changed_before_command")
        result["job_counts_immediately_before"] = capacity._counts(backend.inspect(private_current[capacity.SERVICE]))
        _override(backend.guard, current)
        result["limits_before"] = capacity._public_limits(latest)
        result["before_fingerprint"] = remote.fingerprint(current)
        attempted = True
        result.update(mutation_may_have_applied=True, manager_reload_attempts=1, service_operations=1)
        try:
            require(command(["systemctl", "daemon-reload"], timeout=8) == b"", "capacity_finalize_command_uncertain")
        except Exception:
            command_failed = True
        # A timeout may have applied. Inspect exactly once, never repeat or undo.
        actual_override = capacity.install_guard_exception(backend.guard)
        require(actual_override == OVERRIDE_METADATA, "capacity_finalize_override_not_exact")
        new_limits = capacity.observe_limits(backend.guard, command)
        result["limits_after"] = capacity._public_limits(new_limits)
        after, private_after = backend.snapshot()
        _override(backend.guard, after)
        _verify_after(before, private_before, after, private_after, limits, new_limits, backend.guard)
        result["job_counts_after"] = capacity._counts(backend.inspect(private_after[capacity.SERVICE]))
        # Public evidence is not a substitute for the separate 15-minute gate.
        result["evidence_after"] = _pressure({"memory_pressure": remote.memory_pressure()})
        require(not command_failed, "capacity_finalize_command_uncertain")
        result.update(status="capacity_finalize_verified", resource_change_verified=True, no_service_restart=True,
                      after_fingerprint=remote.fingerprint(after), observed_controls=after["controls"],
                      source_fingerprint=remote.fingerprint(remote.source_files(after)),
                      override=actual_override, worker_health_after=remote.worker_health())
        return result
    except Exception as exc:
        result["error_code"] = (str(exc) if isinstance(exc, FinalizeError) and str(exc) in ERRORS
                                else "capacity_finalize_operation_failed")
        result["mutation_may_have_applied"] = attempted
        return result
