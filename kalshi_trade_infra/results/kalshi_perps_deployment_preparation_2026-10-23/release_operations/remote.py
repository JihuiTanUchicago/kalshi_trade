"""Pinned whole-package release with an idle-only, bounded admission barrier.

No provider/account/order/model path exists here. SSM output is deliberately
reported by the runner's quiet bootstrap, never raw subprocess or environment.
"""
from __future__ import annotations

import base64
import ctypes
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import time
import types
import urllib.error
import urllib.request
import uuid

import release_database as database
import release_schema as schema


ROOT = Path("/opt/kalshi")
RELEASES = Path("/opt/tau-perps-releases")
PYTHON = "/opt/kalshi/.venv313/bin/python"
SERVICES = ("recursive-web", "recursive-agents")
ENV_PATH = Path("/etc/tau/kalshi-perps-live/live.env")
DROPINS = tuple(Path("/etc/systemd/system") / (name + ".service.d/zz-tau-kalshi-perps-live.conf") for name in SERVICES)
ENV_CONTENT = b"TAU_KALSHI_PERPS_LIVE_ENABLED=1\nTAU_KALSHI_PERPS_LIVE_ENVIRONMENT=production\n"
DROPIN_CONTENT = b"[Service]\nEnvironmentFile=/etc/tau/kalshi-perps-live/live.env\n"
ALLOWED_ENV_CHANGES = {"TAU_KALSHI_PERPS_LIVE_ENABLED", "TAU_KALSHI_PERPS_LIVE_ENVIRONMENT"}
DYNAMIC_ENV = {"INVOCATION_ID", "JOURNAL_STREAM", "SYSTEMD_EXEC_PID"}
ASSETS = ("app.js", "app.css", "app.meridian.js", "app.meridian.css", "boot.js", "kalshi-perps-live.js", "kalshi-perps-live.css")
PUBLIC = "https://tau-trading.com"
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_SOURCE = 256 * 1024 * 1024
LOCK_SECONDS = 120
FORWARD_SECONDS = 30
# One recovery SQL proof is at most 0.5s write + 0.5s read. The largest
# journal has six owned names and three newly created directories.
RECOVERY_BUDGET = {"sql_proofs": 28, "stop_and_checks": 10, "original_controls": 3,
                   "daemon_reload": 3, "start_and_health": 11, "snapshot": 6,
                   "final_health": 2, "unlock": 1, "local_filesystem_reserve": 10}
FORWARD_IO_OVERRUN = 5  # One 4s HTTP read plus the following <=1s SQL proof.
assert FORWARD_SECONDS + FORWARD_IO_OVERRUN + sum(RECOVERY_BUDGET.values()) <= LOCK_SECONDS
REJECTED_CANDIDATE = "58eb085889a4e1dead12940ab0e065e03399f0a7"


class ReleaseError(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise ReleaseError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def directory(release_id):
    require(isinstance(release_id, str) and re.fullmatch(r"[0-9a-f]{32}", release_id), "invalid_release_identity")
    return RELEASES / ("manual-perps-" + release_id)


def safe_directory(path, *, private=False):
    value = path.lstat()
    require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022
            and (not private or stat.S_IMODE(value.st_mode) == 0o700), "unsafe_release_directory")


def fixed_file(path, raw, *, mode=0o600, journal=None):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    created = os.fstat(descriptor)
    identity = {"path": str(path), "device": created.st_dev, "inode": created.st_ino, "uid": created.st_uid}
    if journal is not None:
        journal.append(identity)  # Record ownership before the first write can fail.
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(path, 0, 0, follow_symlinks=False)
        os.chmod(path, mode, follow_symlinks=False)
    except BaseException:
        # Remove only this attempt's newly created inode, including partial
        # writes. Never remove a replacement at the same pathname.
        current = path.lstat()
        if ((current.st_dev, current.st_ino, current.st_uid) == (created.st_dev, created.st_ino, created.st_uid)
                and stat.S_ISREG(current.st_mode) and current.st_nlink == 1):
            path.unlink()
        raise


def publish_flag(path, raw, journal):
    """Publish complete 0600 bytes atomically without replacing any old name."""
    temporary = path.with_name("." + path.name + ".tau-perps-" + uuid.uuid4().hex + ".tmp")
    fixed_file(temporary, raw, journal=journal)
    row = dict(journal[-1])
    info = temporary.lstat()
    require((info.st_dev, info.st_ino, info.st_uid) == (row["device"], row["inode"], 0)
            and stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "temporary_flag_changed")
    row["path"] = str(path)
    journal.append(row)  # Fence the destination inode before publication can fail.
    os.link(temporary, path, follow_symlinks=False)  # Atomic and fails if the name exists.
    temporary.unlink()  # The published regular file now has exactly one link.


def source_files(state):
    return state["source"]["files"]


def stable_state(state):
    # Bytecode cache counts are mutable diagnostics, not source versions.
    return {"source_files": source_files(state), "controls": state["controls"]}


def conflicts(state, pins):
    expected = pins["installed"]
    found = []
    if source_files(state) != source_files(expected):
        found.append("source")
    for name in ("units", "unit_files", "processes", "protected_config"):
        if state["controls"][name] != expected["controls"][name]:
            found.append(name)
    if any(row.get("need_daemon_reload") != "no" for row in state["controls"]["units"].values()):
        found.append("pending_daemon_reload")
    for path in (ENV_PATH, *DROPINS):
        if path.exists() or path.is_symlink():
            found.append("new_environment_path")
    return sorted(set(found))


def archive_files(raw, pins):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_ARCHIVE, "archive_size_invalid")
    result, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            name = member.name.rstrip("/")
            require(not name.startswith("/") and ".." not in Path(name).parts
                    and Path(name).parts[0] in ("app", "data_pipeline")
                    and not member.issym() and not member.islnk(), "archive_path_invalid")
            if member.isdir():
                continue
            require(member.isfile() and name in pins["candidate_files"] and name not in result
                    and member.size == pins["candidate_files"][name]["bytes"] and member.size <= 32 * 1024 * 1024,
                    "archive_member_invalid")
            content = archive.extractfile(member).read(member.size + 1)
            require(len(content) == member.size and digest(content) == pins["candidate_files"][name]["sha256"], "archive_hash_mismatch")
            result[name] = content
            total += len(content)
            require(total <= MAX_SOURCE and len(result) <= 2048, "archive_content_limit")
    require(set(result) == set(pins["candidate_files"]), "archive_incomplete")
    return result


def exchange(left, right):
    require(left.stat().st_dev == right.stat().st_dev, "exchange_filesystem_mismatch")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        operation = libc.renameat2
        operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        operation.restype = ctypes.c_int
        require(operation(-100, os.fsencode(left), -100, os.fsencode(right), 2) == 0, "atomic_exchange_failed")
    except ReleaseError:
        raise
    except Exception:
        raise ReleaseError("atomic_exchange_unavailable") from None


def command(args, *, timeout=12):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout)
        require(result.returncode == 0 and len(result.stdout) <= 1024 * 1024, "service_operation_failed")
        return result.stdout
    except ReleaseError:
        raise
    except Exception:
        raise ReleaseError("service_operation_failed") from None


def worker_health():
    """Project fixed systemd counters; never retain journal messages."""
    try:
        raw = command(["systemctl", "show", "recursive-agents", "--property=NRestarts,Result,ExecMainCode,ExecMainStatus,MemoryCurrent,MemoryPeak"], timeout=3)
        values = dict(line.split("=", 1) for line in raw.decode().splitlines() if "=" in line)
        result = values["Result"]
        require(result in {"success", "exit-code", "signal", "core-dump", "watchdog", "oom-kill", "timeout", "resources", "start-limit-hit", "protocol"}, "unsafe_health_projection")
        numbers = {}
        for name in ("NRestarts", "ExecMainCode", "ExecMainStatus", "MemoryCurrent", "MemoryPeak"):
            value = values.get(name, "[not set]")
            if value == "[not set]" and name.startswith("Memory"):
                numbers[name] = None
            else:
                require(re.fullmatch(r"[0-9]{1,20}", value) and int(value) <= 2**64 - 1, "unsafe_health_projection")
                numbers[name] = int(value)
        # Only service-manager records, never application/provider log lines.
        raw = command(["journalctl", "--unit=recursive-agents.service", "_PID=1", "--since=-30min", "--lines=80", "--no-pager", "--output=json", "--output-fields=__REALTIME_TIMESTAMP,MESSAGE"], timeout=3)
        events = {"oom_kill": 0, "process_exit": 0, "scheduled_restart": 0}
        for line in raw.decode().splitlines():
            row = json.loads(line)
            message = row.get("MESSAGE", "")
            require(isinstance(message, str), "unsafe_health_projection")
            message = message.lower()
            events["oom_kill"] += int("oom" in message and "kill" in message or "out of memory" in message)
            events["process_exit"] += int("main process exited" in message)
            events["scheduled_restart"] += int("scheduled restart job" in message)
        return {"status": "observed", "service_result": result, "systemd_counters": numbers, "manager_events_last_30m": events}
    except Exception:
        return {"status": "unavailable", "error_code": "worker_health_projection_failed"}


MEMORY_REPAIR_OBSERVATION_SINCE = "2026-10-23 05:14:41 UTC"


def kernel_oom_journal(*, since="-30min"):
    """Read the fixed bounded query; distinguish its exact no-match result.

    journalctl --grep returns one and a fixed marker when nothing matches. Other
    nonzero exits, warnings or malformed output remain unavailable, never zero.
    """
    require(since in {"-30min", MEMORY_REPAIR_OBSERVATION_SINCE}, "unsafe_memory_projection")
    args = ["journalctl", "--dmesg", "--since=" + since, "--lines=80",
            "--grep=recursive-agents\\.service", "--no-pager", "--output=json", "--output-fields=MESSAGE"]
    try:
        result = subprocess.run(args, capture_output=True, timeout=3, env={**os.environ, "LC_ALL": "C"})
        require(isinstance(result.stdout, bytes) and isinstance(result.stderr, bytes)
                and len(result.stdout) <= 1024 * 1024 and not result.stderr, "unsafe_memory_projection")
        if result.returncode == 1 and result.stdout == b"-- No entries --\n":
            return b""
        require(result.returncode == 0, "unsafe_memory_projection")
        return result.stdout
    except Exception:
        raise ReleaseError("kernel_journal_unavailable") from None


def memory_pressure(*, since="-30min"):
    """Read host capacity and classify kernel OOM records without retaining text."""
    report = {}
    try:
        with Path("/proc/meminfo").open("rb") as source:
            raw = source.read(65537)
        require(len(raw) <= 65536, "unsafe_memory_projection")
        fields = {}
        for line in raw.decode().splitlines():
            name, _, value = line.partition(":")
            if name in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                require(name not in fields, "unsafe_memory_projection")
                match = re.fullmatch(r"\s*([0-9]{1,17}) kB\s*", value)
                require(match and int(match[1]) * 1024 <= 2**64 - 1, "unsafe_memory_projection")
                fields[name] = int(match[1]) * 1024
        require(len(fields) == 4, "unsafe_memory_projection")
        require(0 < fields["MemTotal"] and fields["MemAvailable"] <= fields["MemTotal"]
                and fields["SwapFree"] <= fields["SwapTotal"], "unsafe_memory_projection")
        report["host_bytes"] = fields
    except Exception:
        report["host_error_code"] = "host_memory_projection_failed"
    try:
        raw = kernel_oom_journal() if since == "-30min" else kernel_oom_journal(since=since)
        events = {"cgroup_constraint": 0, "global_constraint": 0,
                  "worker_limit": 0, "ancestor_limit": 0, "unclassified_memcg": 0}
        for line in raw.decode().splitlines():
            row = json.loads(line)
            require(isinstance(row, dict) and "MESSAGE" in row and isinstance(row["MESSAGE"], str),
                    "unsafe_memory_projection")
            message = row["MESSAGE"]
            if re.search(r"/system\.slice/recursive-agents\.service(?=[,/\s]|$)", message):
                if "constraint=CONSTRAINT_MEMCG" in message:
                    events["cgroup_constraint"] += 1
                    scope = re.search(r"(?:^|,)oom_memcg=([^,\s]+)", message)
                    value = scope[1] if scope else ""
                    worker = "/system.slice/recursive-agents.service"
                    key = ("worker_limit" if value == worker else "ancestor_limit"
                           if value.startswith("/") and worker.startswith(value.rstrip("/") + "/")
                           else "unclassified_memcg")
                    events[key] += 1
                events["global_constraint"] += int("global_oom" in message and "constraint=CONSTRAINT_NONE" in message)
        if since == "-30min":
            report["kernel_events_last_30m"] = events
        else:
            report.update(kernel_events_since_repair=events,
                          observed_since_utc="2026-10-23T05:14:41Z",
                          kernel_rows_observed=len(raw.decode().splitlines()),
                          kernel_row_limit=80)
    except Exception:
        report["kernel_error_code"] = "kernel_memory_projection_failed"
    return report


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http_read(base, path, *, expected=200, limit=32 * 1024 * 1024, timeout=4):
    require(base in ("http://127.0.0.1:8090", PUBLIC), "http_host_not_fixed")
    request = urllib.request.Request(base + path, headers={"Cache-Control": "no-cache"}, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        require(response.code == expected, "http_status_failed")
        raw = response.read(limit + 1)
        require(len(raw) <= limit, "http_body_limit")
        return raw


def verify_http(base, pins, release_id, *, private_endpoint=False, check=None):
    suffix = "?tau_release=" + release_id
    for path in ("/", "/funds", "/research"):
        if check:
            check()
        raw = http_read(base, path + suffix)
        if check:
            check()
        require(b"<!doctype html" in raw.lower(), "http_html_missing")
        for name in ("kalshi-perps-live.js", "kalshi-perps-live.css"):
            value = pins["candidate_files"]["app/static/" + name]["sha256"][:10]
            require(("/static/" + name + "?v=" + value).encode() in raw, "http_html_version_mismatch")
    if check:
        check()
    http_read(base, "/healthz" + suffix)
    if check:
        check()
    for name in ASSETS:
        if check:
            check()
        expected = pins["candidate_files"]["app/static/" + name]["sha256"]
        raw = http_read(base, "/static/" + name + "?v=" + expected[:10] + "&tau_release=" + release_id)
        if check:
            check()
        require(digest(raw) == expected, "http_asset_hash_mismatch")
    if private_endpoint:
        if check:
            check()
        http_read(base, "/api/kalshi/perps/live", expected=401, limit=4096)
        if check:
            check()


class Backend:
    def __init__(self, guard, pins):
        self.guard, self.pins = guard, pins
        self.flag_journal = []

    def snapshot(self):
        # Bound the entire five-service control read, not five independent
        # 12-second waits inside a short admission/rollback window.
        original, deadline = self.guard.subprocess, time.monotonic() + 6
        def bounded(*args, **kwargs):
            remaining = deadline - time.monotonic()
            require(remaining > 0, "control_snapshot_deadline")
            kwargs["timeout"] = min(kwargs.get("timeout", remaining), remaining)
            return original.run(*args, **kwargs)
        self.guard.subprocess = types.SimpleNamespace(run=bounded)
        try:
            result = self.guard.snapshot()
            require(time.monotonic() < deadline, "control_snapshot_deadline")
            return result
        finally:
            self.guard.subprocess = original

    def inspect(self, env):
        conn = database.connect(env)
        try:
            return database.inspect(conn)
        finally:
            conn.close()

    def stage(self, release_id, raw, state):
        safe_directory(RELEASES.parent)
        if not RELEASES.exists():
            RELEASES.mkdir(mode=0o700)
        safe_directory(RELEASES, private=True)
        target = directory(release_id)
        target.mkdir(mode=0o700)
        # Operation lock covers preparation/apply/rollback, not app admission.
        candidate = target / "candidate"
        candidate.mkdir(mode=0o700)
        root_info = ROOT.lstat()
        os.chown(candidate, root_info.st_uid, root_info.st_gid, follow_symlinks=False)
        # Complete installed package backup, including caches, stays private.
        backup = target / "installed-whole-package.tar"
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream, tarfile.open(fileobj=stream, mode="w") as archive:
            for package in ("app", "data_pipeline"):
                for source in (ROOT / package, *sorted((ROOT / package).rglob("*"))):
                    name, info = source.relative_to(ROOT).as_posix(), source.lstat()
                    cache = "__pycache__" in source.parts or source.suffix in (".pyc", ".pyo")
                    require(self.guard.source_path_allowed(name) or cache, "private_package_entry_requires_review")
                    require(not stat.S_ISLNK(info.st_mode) and info.st_uid in (0, root_info.st_uid)
                            and not info.st_mode & 0o022, "unsafe_backup_entry")
                    member = tarfile.TarInfo(name)
                    member.uid, member.gid, member.mode, member.mtime = info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_mtime
                    if stat.S_ISDIR(info.st_mode):
                        member.type = tarfile.DIRTYPE
                        archive.addfile(member)
                    else:
                        content, meta = self.guard.read_regular(source, owners=(0, root_info.st_uid))
                        require(cache or {"sha256": digest(content), "bytes": len(content), **meta} == source_files(state)[name],
                                "source_changed_during_backup")
                        member.size = len(content)
                        archive.addfile(member, io.BytesIO(content))
                    require(stream.tell() <= MAX_SOURCE * 2, "backup_size_limit")
        planned = {}
        for package in ("app", "data_pipeline"):
            shutil.copytree(ROOT / package, candidate / package, copy_function=shutil.copy2,
                            ignore=lambda path, names: [name for name in names if name == "__pycache__" or name.endswith((".pyc", ".pyo"))])
        for name, row in source_files(state).items():
            os.chown(candidate / name, row["uid"], row["gid"], follow_symlinks=False)
            os.chmod(candidate / name, int(row["mode"], 8), follow_symlinks=False)
        replacements = archive_files(raw, self.pins)
        for name, content in replacements.items():
            path = candidate / name
            path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            old = source_files(state).get(name)
            mode = old["mode"] if old else self.pins["candidate_files"][name]["mode"]
            path.write_bytes(content)
            os.chown(path, old["uid"] if old else 0, old["gid"] if old else 0, follow_symlinks=False)
            os.chmod(path, int(mode, 8), follow_symlinks=False)
            planned[name] = {"sha256": digest(content), "bytes": len(content), "mode": mode,
                             "uid": old["uid"] if old else 0, "gid": old["gid"] if old else 0}
        for name in self.pins["preserved_extra_paths"]:
            planned[name] = source_files(state)[name]
        # Restore original directory metadata too; new directories stay root-owned.
        for package in ("app", "data_pipeline"):
            for source in (ROOT / package, *(p for p in (ROOT / package).rglob("*") if p.is_dir() and "__pycache__" not in p.parts)):
                info = source.lstat()
                destination = candidate / source.relative_to(ROOT)
                require(not stat.S_ISLNK(info.st_mode) and destination.is_dir(), "source_directory_changed")
                os.chown(destination, info.st_uid, info.st_gid, follow_symlinks=False)
                os.chmod(destination, stat.S_IMODE(info.st_mode), follow_symlinks=False)
        require(self.scan_candidate(candidate) == planned, "staged_candidate_not_exact")
        probe_a, probe_b = target / "probe-a", target / "probe-b"
        probe_a.mkdir(); probe_b.mkdir()
        fixed_file(probe_a / "a", b"a"); fixed_file(probe_b / "b", b"b")
        exchange(probe_a, probe_b)
        require((probe_a / "b").read_bytes() == b"b" and (probe_b / "a").read_bytes() == b"a", "exchange_probe_failed")
        return candidate, planned

    def scan_candidate(self, candidate):
        previous = self.guard.ROOT
        try:
            self.guard.ROOT = candidate
            return self.guard.scan()["files"]
        finally:
            self.guard.ROOT = previous

    def validate(self, candidate, env):
        return schema.run(PYTHON, candidate, env, migrate=False)

    def migrate(self, candidate, env):
        return schema.run(PYTHON, candidate, env, migrate=True)

    def lock(self, env):
        return database.AdmissionLock(database.connect(env, admission=True), seconds=LOCK_SECONDS)

    def stop(self):
        command(["systemctl", "stop", *SERVICES], timeout=6)
        for service in SERVICES:
            raw = command(["systemctl", "show", service, "--property=ActiveState,MainPID,TasksCurrent"], timeout=2)
            values = dict(line.split("=", 1) for line in raw.decode().splitlines() if "=" in line)
            require(values.get("ActiveState") == "inactive" and values.get("MainPID") == "0"
                    and values.get("TasksCurrent") in ("0", "[not set]"), "service_not_fully_stopped")

    def start(self):
        command(["systemctl", "start", *SERVICES], timeout=6)
        deadline = time.monotonic() + 5
        while True:
            try:
                remaining = deadline - time.monotonic()
                require(remaining > 0, "web_startup_health_failed")
                http_read("http://127.0.0.1:8090", "/healthz", limit=4096, timeout=min(1, remaining))
                return
            except Exception:
                require(time.monotonic() < deadline, "web_startup_health_failed")
                time.sleep(0.25)

    def flags(self, created, *, check):
        for path in (ENV_PATH, *DROPINS):
            check()
            require(not path.exists() and not path.is_symlink(), "new_environment_path_conflict")
            if not path.parent.exists():
                path.parent.mkdir(mode=0o700)
                created.append(str(path.parent))
            safe_directory(path.parent)
        check()
        publish_flag(ENV_PATH, ENV_CONTENT, self.flag_journal)
        for path in DROPINS:
            check()
            publish_flag(path, DROPIN_CONTENT, self.flag_journal)
        for path, expected in ((ENV_PATH, ENV_CONTENT), *((path, DROPIN_CONTENT) for path in DROPINS)):
            check()
            saved, meta = self.guard.read_regular(path, 4096)
            require(saved == expected and meta == {"uid": 0, "gid": 0, "mode": "0600"}, "new_flag_not_exact_before_reload")
        check()
        command(["systemctl", "daemon-reload"], timeout=3)
        check()

    def original_controls(self, state):
        for collection in ("unit_files", "protected_config"):
            for name, expected in state["controls"][collection].items():
                raw, meta = self.guard.read_regular(Path(name), owners=(0, ROOT.lstat().st_uid))
                require({"sha256": digest(raw), **meta} == expected, "protected_control_changed_before_rollback")
        for service, expected in state["controls"]["units"].items():
            if service in SERVICES:
                continue
            raw = command(["systemctl", "show", service, "--property=" + ",".join(self.guard.PROPERTIES)], timeout=1)
            values = dict(line.split("=", 1) for line in raw.decode().splitlines() if "=" in line)
            require(fingerprint(values) == expected["properties_sha256"], "non_target_service_changed")
            if expected["pid"]:
                proc = self.guard.PROC / str(expected["pid"])
                observed = {"environment_sha256": digest((proc / "environ").read_bytes()),
                            "cmdline_sha256": digest((proc / "cmdline").read_bytes()),
                            "start_ticks": (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]}
                require(observed == state["controls"]["processes"][service], "non_target_process_changed")

    def remove_flags(self, created, *, check):
        owned = {row["path"]: row for row in self.flag_journal}
        for path in (ENV_PATH, *DROPINS):
            check()
            if path.exists() or path.is_symlink():
                require(str(path) in owned, "new_environment_changed_before_rollback")
        # A link/unlink failure may leave both our temporary and final names.
        # Delete only journaled inodes whose entire link set is still ours.
        observed, links = {}, {}
        for name, row in owned.items():
            path = Path(name)
            if not path.exists() and not path.is_symlink():
                continue
            info = path.lstat()
            require((info.st_dev, info.st_ino, info.st_uid) == (row["device"], row["inode"], 0)
                    and stat.S_ISREG(info.st_mode), "new_environment_changed_before_rollback")
            observed[name] = info
            identity = (info.st_dev, info.st_ino)
            links[identity] = links.get(identity, 0) + 1
        for name, info in observed.items():
            check()
            current = Path(name).lstat()
            identity = (info.st_dev, info.st_ino)
            require((current.st_dev, current.st_ino, current.st_uid) == (*identity, 0)
                    and stat.S_ISREG(current.st_mode) and current.st_nlink == links[identity], "new_environment_has_unowned_links")
            Path(name).unlink()
            links[identity] -= 1
        for name in reversed(created):
            check()
            Path(name).rmdir()
        check()
        command(["systemctl", "daemon-reload"], timeout=3)
        check()

    def swap(self, candidate, packages):
        for package in packages:
            exchange(ROOT / package, candidate / package)

    def verify(self, pins, release_id, check):
        verify_http("http://127.0.0.1:8090", pins, release_id, private_endpoint=True, check=check)
        verify_http(PUBLIC, pins, release_id, check=check)


def inventory(backend, pins):
    state, env = backend.snapshot()
    projection = backend.inspect(env["recursive-agents"])
    differences = conflicts(state, pins)
    if (not env["recursive-web"].get("APP_SECRET_KEY")
            or env["recursive-web"].get("APP_SECRET_KEY") != env["recursive-agents"].get("APP_SECRET_KEY")):
        differences.append("vault_key_inconsistent")
    return {"status": "waiting" if differences or not database.idle(projection["job_counts"]) else "idle_inventory",
            "read_only": True, "candidate": pins["candidate"], "conflicts": differences,
            "installed_fingerprint": fingerprint(state), "source_fingerprint": fingerprint(source_files(state)),
            "observed_units": state["controls"]["units"],
            "observed_processes": state["controls"]["processes"],
            "worker_health": worker_health(),
            "memory_pressure": memory_pressure(),
            "job_counts": projection["job_counts"], "schema": projection,
            "application_changes": False, "service_operations": 0, "job_mutations": 0,
            "provider_calls_from_operations": 0}, state, env


def prepare(backend, pins, release_id, raw, *, sleep=time.sleep):
    report, state, env = inventory(backend, pins)
    if report["status"] != "idle_inventory":
        return report
    require(pins["candidate_ready"] is True, "candidate_acceptance_gate_closed")
    for _ in range(15):
        sleep(2)
        observed = backend.inspect(env["recursive-agents"])["job_counts"]
        if not database.idle(observed):
            return {**report, "status": "waiting", "job_counts": observed, "quiescence_passed": False}
    second, again, env = inventory(backend, pins)
    if second["status"] != "idle_inventory" or stable_state(again) != stable_state(state):
        return {**second, "status": "waiting", "quiescence_passed": False}
    candidate, planned = backend.stage(release_id, raw, state)
    report.update(backup_retained=True, release_id=release_id, quiescence_passed=True)
    backend.validate(candidate, env["recursive-agents"])
    current, private = backend.snapshot()
    require(stable_state(current) == stable_state(state), "state_changed_before_schema")
    require(database.idle(backend.inspect(private["recursive-agents"])["job_counts"]), "work_arrived_before_schema")
    backend.migrate(candidate, private["recursive-agents"])
    schema_projection = backend.inspect(private["recursive-agents"])
    database.require_schema(schema_projection)
    require(database.idle(schema_projection["job_counts"]), "work_arrived_after_schema")
    require(stable_state(backend.snapshot()[0]) == stable_state(state), "state_changed_after_schema")
    plan = {"candidate": pins["candidate"], "installed_fingerprint": fingerprint(state),
            "planned": planned, "schema_verified": True, "created_at": int(time.time())}
    fixed_file(directory(release_id) / "prepared.json", json.dumps(plan, sort_keys=True).encode())
    return {**report, "status": "prepared", "schema_verified": True, "planned_source_fingerprint": fingerprint(planned),
            "application_changes": True, "schema_may_have_committed": True}


def verify_controls(before, after, private_before, private_after):
    expected_files = dict(before["controls"]["unit_files"])
    for path in DROPINS:
        expected_files[str(path)] = {"sha256": digest(DROPIN_CONTENT), "uid": 0, "gid": 0, "mode": "0600"}
    require(after["controls"]["unit_files"] == expected_files, "unit_files_changed_unexpectedly")
    require(after["controls"]["protected_config"] == before["controls"]["protected_config"], "protected_configuration_changed")
    for service, old in before["controls"]["units"].items():
        new = after["controls"]["units"][service]
        if service not in SERVICES:
            require(new == old and after["controls"]["processes"].get(service) == before["controls"]["processes"].get(service),
                    "non_target_service_changed")
            continue
        require(new["active_state"] == "active" and new["pid"] > 0 and new["pid"] != old["pid"]
                and new["resources"] == old["resources"] and new["restart"] == old["restart"]
                and new["need_daemon_reload"] == "no", "target_service_not_verified")
        prior, actual = private_before[service], private_after[service]
        require(actual.get("TAU_KALSHI_PERPS_LIVE_ENABLED") == "1"
                and actual.get("TAU_KALSHI_PERPS_LIVE_ENVIRONMENT") == "production", "actual_live_flag_not_verified")
        remove = ALLOWED_ENV_CHANGES | DYNAMIC_ENV
        require({k: v for k, v in prior.items() if k not in remove} == {k: v for k, v in actual.items() if k not in remove},
                "unexpected_process_environment_change")
        require(after["controls"]["processes"][service]["cmdline_sha256"] == before["controls"]["processes"][service]["cmdline_sha256"],
                "target_command_changed")


def apply(backend, pins, release_id):
    report, state, private = inventory(backend, pins)
    if report["status"] != "idle_inventory":
        return report
    require(pins["candidate_ready"] is True, "candidate_acceptance_gate_closed")
    target = directory(release_id)
    safe_directory(target, private=True)
    raw, meta = backend.guard.read_regular(target / "prepared.json", 1024 * 1024)
    plan = json.loads(raw)
    require(meta["mode"] == "0600" and plan["candidate"] == pins["candidate"] and plan["schema_verified"] is True
            and plan["installed_fingerprint"] == fingerprint(state) and 0 <= time.time() - plan["created_at"] <= 600,
            "prepared_plan_not_current")
    candidate = target / "candidate"
    require(backend.scan_candidate(candidate) == plan["planned"], "prepared_source_changed")
    database.require_schema(backend.inspect(private["recursive-agents"]))
    barrier = backend.lock(private["recursive-agents"])
    swapped, stopped, created, flags_started = [], False, [], False
    report.update(release_id=release_id, backup_retained=True, schema_may_have_committed=True,
                  rollback_performed=False, admission_barrier=True)
    try:
        fresh = barrier.acquire()
        if not database.idle(fresh):
            return {**report, "status": "waiting", "job_counts": fresh, "application_changes": False}
        # 30 seconds forward, 90 seconds reserved for recovery. The forward
        # deadline is checked after each bounded operation as well as before.
        apply_deadline = min(time.monotonic() + FORWARD_SECONDS,
                             barrier.deadline - sum(RECOVERY_BUDGET.values()) - FORWARD_IO_OVERRUN)
        def check(seconds=0):
            barrier.check()
            require(time.monotonic() + seconds < apply_deadline, "apply_deadline_exceeded")
        check(6)
        require(stable_state(backend.snapshot()[0]) == stable_state(state), "state_changed_before_stop")
        check(10)
        stopped = True  # Even a partially successful stop must enter recovery.
        backend.stop()
        for package in ("app", "data_pipeline"):
            check()
            backend.swap(candidate, (package,))
            swapped.append(package)
        flags_started = True
        backend.flags(created, check=check)
        check(11)
        backend.start()
        check(6)
        after, actual = backend.snapshot()
        require(source_files(after) == plan["planned"], "installed_source_not_exact")
        verify_controls(state, after, private, actual)
        saved, meta = backend.guard.read_regular(ENV_PATH, 4096)
        require(saved == ENV_CONTENT and meta == {"uid": 0, "gid": 0, "mode": "0600"}, "new_environment_file_not_private")
        backend.verify(pins, release_id, check)
        check()
        report.update(status="installed_verified", application_changes=True, service_operations=4,
                      source_fingerprint=fingerprint(plan["planned"]), local_and_public_http_verified=True,
                      actual_live_flags_verified=True, old_binary_flags_and_secret_preserved=True,
                      per_user_manual_policies_default_off=True, non_target_services_preserved=True)
        return report
    except Exception as exc:
        report.update(status="failed_before_service_change" if not stopped else "recovery_requires_inspection",
                      error_code=safe_error(exc), application_changes=stopped)
        if stopped:
            try:
                # No reconnect/lockless recovery. Keep both versions and stop
                # for inspection if admission ownership cannot be established.
                barrier.check()
                backend.stop()
                barrier.check()
                expected_now = dict(source_files(state))
                for package in swapped:
                    expected_now = {name: row for name, row in expected_now.items() if not name.startswith(package + "/")}
                    expected_now.update({name: row for name, row in plan["planned"].items() if name.startswith(package + "/")})
                require(backend.scan_candidate(ROOT) == expected_now, "source_changed_before_rollback")
                backend.original_controls(state)
                barrier.check()
                if flags_started:
                    backend.remove_flags(created, check=barrier.check)
                for package in reversed(swapped):
                    barrier.check()
                    backend.swap(candidate, (package,))
                    barrier.check()
                barrier.check()
                require(backend.scan_candidate(ROOT) == source_files(state), "rollback_source_not_exact")
                barrier.check()
                backend.start()
                barrier.check()
                restored, restored_env = backend.snapshot()
                barrier.check()
                require(restored["controls"]["unit_files"] == state["controls"]["unit_files"]
                        and restored["controls"]["protected_config"] == state["controls"]["protected_config"], "rollback_controls_not_exact")
                for service in SERVICES:
                    require(restored["controls"]["units"][service]["resources"] == state["controls"]["units"][service]["resources"]
                            and {k: v for k, v in restored_env[service].items() if k not in DYNAMIC_ENV}
                            == {k: v for k, v in private[service].items() if k not in DYNAMIC_ENV}, "rollback_environment_not_exact")
                barrier.check()
                http_read("http://127.0.0.1:8090", "/healthz", limit=4096, timeout=2)
                barrier.check()
                report.update(status="rolled_back", rollback_performed=True, service_operations=8,
                              schema_rolled_back=False, backup_retained=True)
            except Exception:
                report.update(status="recovery_requires_inspection", automatic_recovery_safe=False)
        return report
    finally:
        # Closing the same connection releases even when UNLOCK itself fails.
        barrier.close()
        report["admission_released"] = True


def safe_error(exc):
    if isinstance(exc, (ReleaseError, database.DatabaseError, schema.SchemaError)):
        value = str(exc)
        if re.fullmatch(r"[a-z0-9_]{1,80}", value):
            return value
    return "operation_failed"


def execute(phase, release_id, bundle, guard):
    pins = bundle["pins"]
    backend = Backend(guard, pins)
    try:
        require(os.geteuid() == 0 and phase in {"inventory", "prepare", "apply", "capacity", "capacity_finalize"}, "invalid_operation_context")
        if phase == "inventory":
            return inventory(backend, pins)[0]
        current = inventory(backend, pins)[0]
        # The separately approved online ceiling increase never restarts or
        # changes jobs. Source/schema activation still requires full idleness.
        if phase == "capacity_finalize":
            # Only the exact reviewed pending-reload baseline enters this
            # no-restart completion. Original inventory/prepare/apply are strict.
            if (current["conflicts"] != ["pending_daemon_reload"]
                    or any(row["need_daemon_reload"] != ("yes" if name == "recursive-agents" else "no")
                           for name, row in current["observed_units"].items())):
                return current
        elif (current["conflicts"] if phase == "capacity" else current["status"] != "idle_inventory"):
            return current
        require(pins["candidate_ready"] is True and pins["candidate"] != REJECTED_CANDIDATE, "candidate_acceptance_gate_closed")
        safe_directory(RELEASES.parent)
        if not RELEASES.exists():
            RELEASES.mkdir(mode=0o700)
        safe_directory(RELEASES, private=True)
        descriptor = os.open(RELEASES / ".operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600,
                    "unsafe_operation_lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if phase == "prepare":
                return prepare(backend, pins, release_id, base64.b64decode(bundle["archive"], validate=True))
            if phase == "capacity":
                import capacity
                return capacity.run(backend, pins)
            if phase == "capacity_finalize":
                import capacity_finalize
                return capacity_finalize.run(backend, pins)
            return apply(backend, pins, release_id)
        finally:
            os.close(descriptor)
    except Exception as exc:
        result = {"status": "release_requires_inspection", "error_code": safe_error(exc),
                  "candidate": pins["candidate"], "provider_calls_from_operations": 0, "job_mutations": 0}
        if isinstance(exc, schema.SchemaError) and exc.details is not None:
            result["schema_details"] = exc.details
        return result
