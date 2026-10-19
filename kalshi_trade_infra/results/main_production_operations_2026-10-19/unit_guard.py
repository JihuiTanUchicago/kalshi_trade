"""Read-only, capture-bound systemd controls for this one reviewed rollout.

No service operation is performed here. Errors contain fixed codes only. The
returned baseline contains hashes and the already-sanitized systemd properties,
never inline Environment values or process-environment values.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess


TARGETS = ("recursive-web", "recursive-agents")
OTHERS = ("recursive-engine", "recursive-history", "kalshi-live-engine")
SERVICES = TARGETS + OTHERS
ROOTS = tuple(Path(p) for p in (
    "/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system"
))
INTERPRETER = "/opt/kalshi/.venv313/bin/python"
DROP_NAME = "99-tau-alpaca-paper.conf"
KNOWN_DROPS = {"90-tau-provider-data.conf", DROP_NAME}
RESOURCES = (
    "Restart", "RestartUSec", "TimeoutStartUSec", "TimeoutStopUSec", "MemoryHigh",
    "MemoryMax", "MemorySwapMax", "Nice", "KillMode", "KillSignal",
)
CONTROLS = RESOURCES + (
    "WorkingDirectory", "User", "Group", "EnvironmentFiles", "EnvironmentSHA256", "Type",
)
CAPTURED = RESOURCES + (
    "WorkingDirectory", "User", "Group", "EnvironmentFiles", "EnvironmentSHA256",
    "MainPID", "ActiveState", "FragmentPath", "DropInPaths", "NeedDaemonReload", "ExecStart",
)
SHOW_PROPERTIES = tuple(p for p in CAPTURED if p != "EnvironmentSHA256") + ("Environment", "Type")
EMPTY_ENV = hashlib.sha256(b"").hexdigest()
PROVIDER = (
    ". /etc/tau/provider-data/market-data.env || exit $?; "
    ". /etc/tau/provider-data/research-data.env || exit $?; "
    + INTERPRETER + " -B -m app.market_data_config check >/dev/null || exit $?; "
)
PAPER = ". /etc/tau/alpaca-paper/paper.env || exit $?; "


class UnitGuardError(RuntimeError):
    """Fixed, credential-free failure code."""

    def __init__(self, code, details=None):
        self.code = code
        self.details = details or {}
        super().__init__(code)


def _fail(code, details=None):
    raise UnitGuardError(code, details) from None


def _capture_details(service, captured, current, changed):
    def numeric_pid(value):
        return int(value) if isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value) else None

    return {"service": service, "fields_changed": sorted(changed),
            "previous_main_pid": numeric_pid(captured.get("MainPID")),
            "current_main_pid": numeric_pid(current.get("MainPID"))}


def _show(service):
    try:
        result = subprocess.run(
            ["systemctl", "show", service, "--property=" + ",".join(SHOW_PROPERTIES)],
            check=True, capture_output=True, timeout=15,
        )
        values = dict(line.split("=", 1) for line in result.stdout.decode().splitlines() if "=" in line)
        # Some systemd versions omit a requested empty list property entirely.
        # Disk Environment[File] directives are independently forbidden below.
        environment = values.pop("Environment", "")
        values.setdefault("EnvironmentFiles", "")
        values["EnvironmentSHA256"] = hashlib.sha256(environment.encode()).hexdigest()
        if any(p not in values for p in (*CAPTURED, "Type")):
            _fail("unit_property_missing")
        return values
    except UnitGuardError:
        raise
    except Exception:
        _fail("unit_property_read_failed")


def _read(path):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        first = os.fstat(descriptor)
        if (not stat.S_ISREG(first.st_mode) or first.st_uid != 0 or first.st_mode & 0o022
                or first.st_nlink != 1 or first.st_size > 262144):
            _fail("unsafe_unit_file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(262145)
            last = os.fstat(stream.fileno())
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode, s.st_uid)
        if len(raw) != first.st_size or signature(first) != signature(last):
            _fail("unit_file_changed_while_reading")
        return raw
    except UnitGuardError:
        raise
    except Exception:
        _fail("unit_file_read_failed")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _inventory(units):
    """Include inactive units and pending/unloaded drop-ins, not just loaded paths."""
    found = {}
    try:
        for service in SERVICES:
            fragment = Path(units[service]["FragmentPath"])
            if fragment not in {root / (service + ".service") for root in ROOTS}:
                _fail("unreviewed_unit_fragment_path")
            # A newly-created higher-priority fragment must not become effective
            # silently on daemon-reload. This operation has one fragment per unit.
            for root in ROOTS:
                candidate = root / (service + ".service")
                if candidate.exists() or candidate.is_symlink():
                    if candidate != fragment:
                        _fail("unreviewed_unit_fragment")
            found[str(fragment)] = _read(fragment)
            for root in ROOTS:
                directory = root / (service + ".service.d")
                if directory.exists() or directory.is_symlink():
                    info = directory.lstat()
                    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                        _fail("unsafe_unit_dropin_directory")
                    for path in directory.glob("*.conf"):
                        found[str(path)] = _read(path)
                # systemd also accepts type-wide and dash-prefix drop-ins.
                prefixes = ["service.d"] + [service[:i + 1] + ".service.d"
                                              for i, char in enumerate(service) if char == "-"]
                for name in prefixes:
                    inherited = root / name
                    if inherited.exists() and any(inherited.glob("*.conf")):
                        _fail("unreviewed_inherited_dropin")
        return found
    except UnitGuardError:
        raise
    except Exception:
        _fail("unit_inventory_failed")


def _directives(raw):
    try:
        text = raw.decode("utf-8")
    except (AttributeError, UnicodeError):
        _fail("invalid_unit_encoding")
    if len(raw) > 262144 or any(c in text for c in ("\x00", "\r", "\\")):
        _fail("unsupported_unit_syntax")
    section = None
    result = []
    for original in text.splitlines():
        line = original.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section not in {"Unit", "Service", "Install"}:
                _fail("unreviewed_unit_section")
            continue
        key, separator, value = line.partition("=")
        if not separator or section is None or key.strip() != key:
            _fail("unsupported_unit_syntax")
        result.append((section, key, value.strip()))
    return result


def _command(raw, dropin=False):
    rows = _directives(raw)
    if dropin:
        if len(rows) != 2 or [(s, k) for s, k, _ in rows] != [("Service", "ExecStart")] * 2 or rows[0][2]:
            _fail("dropin_changes_non_exec_controls")
        value = rows[1][2]
    else:
        values = [v for s, k, v in rows if s == "Service" and k == "ExecStart"]
        if len(values) != 1 or not values[0]:
            _fail("unexpected_exec_start_count")
        value = values[0]
    try:
        args = shlex.split(value)
    except ValueError:
        _fail("unrecognized_exec_start")
    if len(args) != 3 or args[0] != "/bin/bash" or args[1] not in {"-c", "-ec", "-ce"}:
        _fail("unrecognized_exec_start")
    return (args[0], " ".join(args), "no")


def _loaded_exec(value):
    # Shell-body semicolons are meaningful. Parse the stable systemctl fields,
    # not a split on every semicolon, and discard only execution metadata.
    if not isinstance(value, str):
        _fail("unrecognized_loaded_exec_start")
    match = re.fullmatch(
        r"\{ path=([^ ;]+) ; argv\[\]=(.*?) ; ignore_errors=(yes|no)"
        r" ; start_time=\[[^\]]*\] ; stop_time=\[[^\]]*\]"
        r" ; pid=\d+ ; code=[^;{}]+ ; status=[^;{}]+ \}", value,
    )
    if not match:
        _fail("unrecognized_loaded_exec_start")
    return match.group(1), match.group(2), match.group(3)


def _without_overlays(command):
    path, argv, ignore = command
    for block in (PROVIDER, PAPER):
        if argv.count(block) > 1:
            _fail("duplicate_exec_overlay")
        argv = argv.replace(block, "", 1)
    if "/etc/tau/provider-data/" in argv or "/etc/tau/alpaca-paper/" in argv:
        _fail("unrecognized_exec_overlay")
    return path, argv, ignore


def _disk_controls(service, raw, values):
    """This capture's base units have no Environment or EnvironmentFile keys.

    Unknown directives fail closed, rather than trusting that a pending unit
    edit is harmless. The historical StartLimit keys in [Service] are preserved
    byte-for-byte; systemd ignores them there, so they are not silently moved.
    """
    expected = {
        "Type": "simple", "WorkingDirectory": "/opt/kalshi", "Restart": "always",
        "RestartSec": "10", "StartLimitIntervalSec": "300", "StartLimitBurst": "10",
        "KillSignal": "SIGTERM", "TimeoutStopSec": "30",
    }
    if service != "kalshi-live-engine":
        expected.update(MemoryMax="400M" if service in TARGETS else "250M", Nice="5")
    got = {}
    allowed = {"Unit": {"Description", "After", "Wants"}, "Install": {"WantedBy"}}
    for section, key, value in _directives(raw):
        if section == "Service":
            if key == "ExecStart":
                continue
            if key in got:
                _fail("duplicate_unit_control")
            got[key] = value
        elif key not in allowed.get(section, set()):
            _fail("unreviewed_unit_directive")
    if got != expected:
        _fail("disk_unit_controls_not_reviewed")
    loaded_expected = {
        "Type": "simple", "WorkingDirectory": "/opt/kalshi", "User": "", "Group": "",
        "Restart": "always", "RestartUSec": "10s", "TimeoutStartUSec": "1min 30s",
        "TimeoutStopUSec": "30s", "MemoryHigh": "infinity", "MemorySwapMax": "infinity",
        "MemoryMax": ("419430400" if service in TARGETS else
                      "262144000" if service != "kalshi-live-engine" else "infinity"),
        "Nice": "0" if service == "kalshi-live-engine" else "5", "KillMode": "control-group",
        "KillSignal": "15", "EnvironmentFiles": "", "EnvironmentSHA256": EMPTY_ENV,
    }
    if any(values.get(key) != value for key, value in loaded_expected.items()):
        _fail("loaded_unit_controls_not_reviewed")


def _drops(service, files):
    selected = {}
    priority = {"/usr/lib/systemd/system": 0, "/lib/systemd/system": 0,
                "/run/systemd/system": 1, "/etc/systemd/system": 2}
    for path, raw in files.items():
        p = Path(path)
        if p.parent.name != service + ".service.d":
            continue
        if service not in TARGETS or p.name not in KNOWN_DROPS:
            _fail("unreviewed_unit_dropin")
        rank = priority.get(str(p.parent.parent))
        if rank is None:
            _fail("unreviewed_unit_dropin_path")
        _command(raw, dropin=True)
        if p.name not in selected or rank > selected[p.name][0]:
            selected[p.name] = rank, path, raw
        elif rank == selected[p.name][0] and raw != selected[p.name][2]:
            _fail("ambiguous_unit_dropin")
    return [(p, raw) for _, p, raw in (selected[name] for name in sorted(selected))]


def _hashes(files):
    return {str(path): hashlib.sha256(raw).hexdigest() for path, raw in files.items()}


def _plans(plans, files):
    if not isinstance(plans, dict) or set(plans) != set(TARGETS):
        _fail("invalid_unit_plan_set")
    desired = {}
    changes = {}
    for service in TARGETS:
        try:
            plan, saved, basic = plans[service]
            path = str(plan["drop_path"])
            raw = plan["drop_bytes"]
            expected_path = "/etc/systemd/system/" + service + ".service.d/" + DROP_NAME
            if path != expected_path or plan.get("service", service) != service:
                _fail("unrecognized_planned_dropin")
            desired[service] = _command(raw, dropin=True)
            args = shlex.split(next(v for s, k, v in _directives(raw) if s == "Service" and k == "ExecStart" and v))
            if plan["body"] != args[2] or plan["body"].count(PAPER) != 1:
                _fail("planned_exec_body_mismatch")
            expected_files = {p: r for p, r in files.items()
                              if p.endswith("/" + service + ".service") or Path(p).parent.name == service + ".service.d"}
            if {str(p): r for p, r in saved.items()} != expected_files:
                _fail("planned_unit_snapshot_changed")
            changes[path] = hashlib.sha256(raw).hexdigest()
        except UnitGuardError:
            raise
        except Exception:
            _fail("invalid_unit_plan")
    return desired, changes


def check_before(plans, manifest, agent_env):
    """Validate capture, actual loaded/disk controls and the private worker env."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("units"), dict) or set(manifest["units"]) != set(SERVICES):
        _fail("invalid_unit_capture")
    if not isinstance(agent_env, dict) or agent_env.get("APP_AGENT_CONCURRENCY") != "2":
        _fail("worker_concurrency_not_two")
    current = {service: _show(service) for service in SERVICES}
    for service, values in current.items():
        captured = {"EnvironmentFiles": "", **manifest["units"][service]}
        if any(key not in captured for key in CAPTURED):
            _fail("incomplete_unit_capture")
        # The capture pins configuration, not a process's lifetime. Bind PID
        # continuity to this fresh snapshot returned below; later cutover and
        # recovery checks continue to compare against these actual fresh PIDs.
        changed = [key for key in CAPTURED if key not in {"ExecStart", "MainPID"}
                   and values[key] != captured[key]]
        if changed:
            _fail("loaded_unit_changed_since_capture", _capture_details(service, captured, values, changed))
        if _loaded_exec(values["ExecStart"]) != _loaded_exec(captured["ExecStart"]):
            _fail("loaded_exec_changed_since_capture", _capture_details(service, captured, values, ["ExecStart"]))
        if service not in TARGETS and values["NeedDaemonReload"] != "no":
            _fail("unrelated_unit_pending_reload")
    files = _inventory(current)
    if _hashes(files) != manifest.get("unit_hashes"):
        _fail("unit_files_changed_since_capture")
    desired, changes = _plans(plans, files)
    for service, values in current.items():
        base = files[values["FragmentPath"]]
        _disk_controls(service, base, values)
        base_exec = _command(base)
        loaded = _loaded_exec(values["ExecStart"])
        drops = _drops(service, files)
        effective = _command(drops[-1][1], dropin=True) if drops else base_exec
        known_paths = {path for path, _ in drops}
        try:
            loaded_paths = shlex.split(values["DropInPaths"])
        except ValueError:
            _fail("invalid_loaded_dropin_paths")
        if any(path not in known_paths for path in loaded_paths):
            _fail("loaded_dropin_inventory_incomplete")
        if service in TARGETS:
            if (INTERPRETER + " -u -m app." not in base_exec[1]
                    or _without_overlays(loaded) != base_exec
                    or _without_overlays(effective) != base_exec
                    or _without_overlays(desired[service]) != base_exec):
                _fail("target_exec_changed_beyond_approved_overlays")
            if loaded != effective and (values["NeedDaemonReload"] != "yes" or not drops):
                _fail("unexplained_pending_exec_change")
        elif loaded != effective:
            _fail("unrelated_pending_exec_change")
    return {"units": current, "unit_hashes": _hashes(files), "desired_exec": desired,
            "drop_hashes": changes}


def _check_after(plans, baseline, started):
    current = {service: _show(service) for service in SERVICES}
    files = _inventory(current)
    expected_hashes = {**baseline["unit_hashes"], **baseline["drop_hashes"]}
    if _hashes(files) != expected_hashes:
        _fail("unit_files_changed_during_cutover")
    # Validate the caller has not replaced the already-approved plan in memory.
    for service in TARGETS:
        plan = plans[service][0]
        if (_command(plan["drop_bytes"], dropin=True) != baseline["desired_exec"][service]
                or hashlib.sha256(plan["drop_bytes"]).hexdigest() != baseline["drop_hashes"].get(str(plan["drop_path"]))):
            _fail("unit_plan_changed_during_cutover")
    for service, values in current.items():
        previous = baseline["units"][service]
        if any(values.get(key) != previous.get(key) for key in CONTROLS):
            _fail("loaded_unit_controls_changed_after_reload")
        if values["FragmentPath"] != previous["FragmentPath"] or values["NeedDaemonReload"] != "no":
            _fail("unit_reload_not_settled")
        expected_exec = (baseline["desired_exec"][service] if service in TARGETS
                         else _loaded_exec(previous["ExecStart"]))
        if _loaded_exec(values["ExecStart"]) != expected_exec:
            _fail("loaded_exec_not_approved_after_reload")
        drops = _drops(service, files)
        if shlex.split(values["DropInPaths"]) != [path for path, _ in drops]:
            _fail("loaded_dropins_not_approved_after_reload")
        if service not in TARGETS:
            if any(values[key] != previous[key] for key in ("MainPID", "ActiveState")):
                _fail("unrelated_service_state_changed")
        elif started:
            if values["ActiveState"] != "active" or not re.fullmatch(r"[1-9]\d*", values["MainPID"]):
                _fail("target_service_not_active")
        elif values["MainPID"] != "0" or values["ActiveState"] != "inactive":
            _fail("target_service_not_stopped")


def check_after_reload(plans, baseline_controls):
    """Run after daemon-reload, while targets are stopped and before starting."""
    _check_after(plans, baseline_controls, started=False)


def check_after_start(plans, baseline_controls):
    """Optional final loaded-control/non-target continuity check after startup."""
    _check_after(plans, baseline_controls, started=True)


def recovery_dependencies_unchanged(plans, baseline_controls, attempted_config):
    """Return whether pre-start recovery can safely reload/restart old source.

    A partial write may leave either original bytes or the exact attempted own99
    bytes. Every other unit/control must still match the pre-cutover baseline.
    This is a predicate only: no restoration, reload or service action occurs.
    """
    try:
        baseline = baseline_controls
        if set(plans) != set(TARGETS) or set(baseline["units"]) != set(SERVICES):
            return False
        attempts = {str(path): raw for path, raw in attempted_config.items()}
        managed = {str(plans[service][0]["drop_path"]) for service in TARGETS}
        if any(path not in managed | {"/etc/tau/alpaca-paper/paper.env"} for path in attempts):
            return False
        for service in TARGETS:
            plan = plans[service][0]
            path, raw = str(plan["drop_path"]), plan["drop_bytes"]
            if (path != "/etc/systemd/system/" + service + ".service.d/" + DROP_NAME
                    or _command(raw, dropin=True) != baseline["desired_exec"][service]
                    or hashlib.sha256(raw).hexdigest() != baseline["drop_hashes"].get(path)
                    or (path in attempts and attempts[path] != raw)):
                return False
        current = {service: _show(service) for service in SERVICES}
        files = _inventory(current)
        original = baseline["unit_hashes"]
        hashes = _hashes(files)
        if not set(original).issubset(hashes):
            return False
        for path, digest in hashes.items():
            if digest == original.get(path):
                continue
            if path not in managed or path not in attempts or files[path] != attempts[path]:
                return False
        for service, values in current.items():
            previous = baseline["units"][service]
            if (any(values.get(key) != previous.get(key) for key in CONTROLS)
                    or values["FragmentPath"] != previous["FragmentPath"]):
                return False
            loaded = _loaded_exec(values["ExecStart"])
            original_exec = _loaded_exec(previous["ExecStart"])
            loaded_paths = shlex.split(values["DropInPaths"])
            if service in OTHERS:
                if (loaded != original_exec or any(values[key] != previous[key]
                        for key in ("MainPID", "ActiveState", "DropInPaths", "NeedDaemonReload"))):
                    return False
            else:
                if values["ActiveState"] == "active":
                    if values["MainPID"] != previous["MainPID"]:
                        return False
                elif values["ActiveState"] == "inactive":
                    if values["MainPID"] != "0":
                        return False
                else:
                    return False
                if values["NeedDaemonReload"] not in {"yes", "no"}:
                    return False
                if loaded == original_exec:
                    if loaded_paths != shlex.split(previous["DropInPaths"]):
                        return False
                elif loaded == baseline["desired_exec"][service]:
                    if loaded_paths != [path for path, _ in _drops(service, files)]:
                        return False
                else:
                    return False
        return True
    except Exception:
        # Recovery must never guess after a failed read, parse or integrity gate.
        return False
