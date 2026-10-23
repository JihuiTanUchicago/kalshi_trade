"""Passive installed-state inspection plus isolated, hash-pinned diagnostics."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import tempfile
import zlib


ROOT = Path("/opt/kalshi")
PROC = Path("/proc")
PYTHON = "/opt/kalshi/.venv313/bin/python"
BUCKET = "kalshi-trade-artifacts-568386354218-us-east-1"
REGION = "us-east-1"
CANDIDATE = "b7cf7c754e09a50e8f0bc6278dbf275f0f0f2a8b"
BASE = "aa3664e420fe4fdf538cd434e4c91e73ee0875cf"
SERVICES = ("recursive-web", "recursive-agents", "recursive-engine", "recursive-history", "kalshi-live-engine")
UNIT_ROOTS = tuple(Path(p) for p in ("/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system"))
CONFIG = (ROOT / ".env.aws", ROOT / ".env.app", ROOT / ".env",
          Path("/etc/tau/provider-data/market-data.env"), Path("/etc/tau/provider-data/research-data.env"),
          Path("/etc/tau/alpaca-paper/paper.env"))
RESOURCES = ("MemoryHigh", "MemoryMax", "MemorySwapMax", "CPUQuotaPerSecUSec", "CPUWeight", "TasksMax", "Nice")
PROPERTIES = ("MainPID", "ActiveState", "SubState", "FragmentPath", "DropInPaths", "NeedDaemonReload",
              "Restart", "RestartUSec", "Environment", "EnvironmentFiles", "ExecStart", *RESOURCES)
NATIVE = ("app/__init__.py", "app/market_data_common.py", "app/kalshi_perps_data.py", "app/kalshi_perps_collector.py")
HELPERS = ("readiness_repository.py", "public_check.py")
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_BUNDLE = 1024 * 1024


class InspectionError(RuntimeError):
    pass


def fail(code):
    raise InspectionError(code) from None


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def source_path_allowed(relative):
    parts = Path(relative).parts
    private = {"__pycache__", ".git", ".pytest_cache", "credentials", "secrets", "private", "keys",
               ".ssh", ".aws", ".secrets", "node_modules"}
    return not (any(part.lower() in private or part.lower().startswith(".env") for part in parts)
                or Path(relative).name.lower() in {"credentials.json", "secrets.json", "token.json", "tokens.json", "private_key"}
                or Path(relative).suffix.lower() in {".pyc", ".pyo", ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".log", ".sqlite", ".db"}
                or any(part.lower().startswith(("id_rsa", "id_ed25519")) for part in parts))


def metadata(info):
    return {"uid": info.st_uid, "gid": info.st_gid, "mode": format(stat.S_IMODE(info.st_mode), "04o")}


def read_regular(path, limit=MAX_FILE, owners=(0,)):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        first = os.fstat(descriptor)
        if (not stat.S_ISREG(first.st_mode) or first.st_nlink != 1 or first.st_uid not in owners
                or first.st_mode & 0o022 or first.st_size > limit):
            fail("unsafe_regular_file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(limit + 1)
            last = os.fstat(stream.fileno())
        signature = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns,
                                 row.st_mode, row.st_uid, row.st_gid, row.st_nlink)
        if len(raw) != first.st_size or signature(first) != signature(last):
            fail("file_changed_during_read")
        return raw, metadata(first)
    except InspectionError:
        raise
    except Exception:
        fail("regular_file_read_failed")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def scan():
    owner = ROOT.lstat().st_uid
    files, total, omitted = {}, 0, 0

    def visit(path):
        nonlocal total, omitted
        info = path.lstat()
        relative = path.relative_to(ROOT).as_posix()
        if stat.S_ISLNK(info.st_mode):
            fail("source_symlink_not_supported")
        if not source_path_allowed(relative):
            omitted += 1
            return
        if info.st_uid not in {0, owner} or info.st_mode & 0o022:
            fail("unsafe_source_metadata")
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            raw, meta = read_regular(path, owners=(0, owner))
            total += len(raw)
            files[relative] = {"sha256": digest(raw), "bytes": len(raw), **meta}
        else:
            fail("source_type_not_supported")
        if total > MAX_TOTAL or len(files) > 2048:
            fail("source_inventory_limit")

    for path in (ROOT.parent, ROOT):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, owner} or info.st_mode & 0o022:
            fail("unsafe_source_root")
    for name in ("app", "data_pipeline"):
        visit(ROOT / name)
    return {"files": files, "omitted_private_or_cache_entries": omitted}


def perps_flag(env):
    raw = env.get("TAU_KALSHI_PERPS_ENABLED", "false").strip().lower()
    if raw not in {"0", "1", "true", "false"}:
        fail("invalid_perps_flag")
    return {"enabled": raw in {"1", "true"},
            "explicitly_configured": "TAU_KALSHI_PERPS_ENABLED" in env,
            "explicit_proxy_configured": bool(env.get("TAU_KALSHI_PERPS_PROXY_URL", "").strip())}


def unit_state():
    units, unit_files, process, private = {}, {}, {}, {}
    for service in SERVICES:
        response = subprocess.run(["systemctl", "show", service, "--property=" + ",".join(PROPERTIES)],
                                  capture_output=True, check=True, timeout=12)
        values = dict(line.split("=", 1) for line in response.stdout.decode().splitlines() if "=" in line)
        if not re.fullmatch(r"[0-9]{1,10}", values.get("MainPID", "")):
            fail("invalid_service_pid")
        pid = int(values["MainPID"])
        if service in SERVICES[:2] and (not pid or values.get("ActiveState") != "active"):
            fail("required_service_not_active")
        units[service] = {"pid": pid, "active_state": values.get("ActiveState"),
                          "sub_state": values.get("SubState"), "restart": values.get("Restart"),
                          "need_daemon_reload": values.get("NeedDaemonReload"),
                          "resources": {name: values.get(name) for name in RESOURCES},
                          "properties_sha256": fingerprint(values)}
        fragment = Path(values.get("FragmentPath", ""))
        if fragment not in {root / (service + ".service") for root in UNIT_ROOTS}:
            fail("unrecognized_unit_fragment")
        paths = {fragment, *(Path(p) for p in shlex.split(values.get("DropInPaths", "")))}
        for path in paths:
            if not any(path.is_relative_to(root) for root in UNIT_ROOTS):
                fail("unrecognized_unit_file")
            raw, meta = read_regular(path, 262144)
            unit_files[str(path)] = {"sha256": digest(raw), **meta}
        if pid:
            proc = PROC / str(pid)
            raw_env = (proc / "environ").read_bytes()
            raw_args = (proc / "cmdline").read_bytes()
            if len(raw_env) > MAX_BUNDLE or len(raw_args) > MAX_BUNDLE:
                fail("process_metadata_limit")
            env = dict(item.decode().split("=", 1) for item in raw_env.split(b"\0") if b"=" in item)
            args = [part.decode() for part in raw_args.split(b"\0") if part]
            units[service]["perps"] = perps_flag(env)
            if service in SERVICES[:2]:
                wanted = ["-m", "app.server"] if service == SERVICES[0] else ["-m", "app.worker", "agents"]
                if ((proc / "cwd").resolve() != ROOT or not args or args[0] != PYTHON
                        or not any(args[index:index + len(wanted)] == wanted for index in range(len(args)))):
                    fail("unexpected_application_process")
                private[service] = env
            process[service] = {"environment_sha256": digest(raw_env), "cmdline_sha256": digest(raw_args),
                                "start_ticks": (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]}
    config = {}
    for path in CONFIG:
        if path.exists() or path.is_symlink():
            raw, meta = read_regular(path, MAX_BUNDLE, owners=(0, ROOT.lstat().st_uid))
            config[str(path)] = {"sha256": digest(raw), **meta}
        elif path.name in {".env.aws", ".env.app"}:
            fail("base_configuration_missing")
    return {"units": units, "unit_files": unit_files, "processes": process, "protected_config": config}, private


def snapshot():
    if os.geteuid() != 0:
        fail("requires_root")
    source = scan()
    controls, private = unit_state()
    return {"source": source, "controls": controls}, private


def load_bundle(artifact, expected_native):
    if (set(artifact) != {"bucket", "key", "sha256"} or artifact["bucket"] != BUCKET
            or not re.fullmatch(r"bundle/perps-readiness-" + CANDIDATE + r"-[0-9a-f]{32}\.json", artifact["key"])
            or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])):
        fail("invalid_diagnostic_artifact")
    response = subprocess.run(["aws", "s3", "cp", "s3://" + BUCKET + "/" + artifact["key"], "-",
                               "--region", REGION, "--no-progress", "--only-show-errors"],
                              capture_output=True, timeout=30)
    raw = response.stdout
    if response.returncode or len(raw) > MAX_BUNDLE or digest(raw) != artifact["sha256"]:
        fail("diagnostic_artifact_unavailable")
    payload = json.loads(raw)
    if (set(payload) != {"candidate", "base", "files", "reference_sha256"}
            or payload["candidate"] != CANDIDATE or payload["base"] != BASE
            or set(payload["files"]) != {*NATIVE, *HELPERS}
            or set(expected_native) != set(NATIVE)):
        fail("diagnostic_artifact_invalid")
    files = {path: base64.b64decode(value, validate=True) for path, value in payload["files"].items()}
    if any(digest(files[path]) != expected_native[path] for path in NATIVE):
        fail("candidate_source_hash_mismatch")
    return files, payload["reference_sha256"]


def child(path, env, timeout):
    private_env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": str(path.parent), **env}
    try:
        response = subprocess.run([PYTHON, "-B", str(path)], cwd=path.parent, env=private_env,
                                  capture_output=True, timeout=timeout)
        if response.returncode or len(response.stdout) > 65536:
            return {"status": "unavailable", "error_code": "diagnostic_process_failed"}
        result = json.loads(response.stdout)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "error_code": "diagnostic_timeout"}
    except Exception:
        return {"status": "unavailable", "error_code": "diagnostic_process_failed"}


def inspect(artifact, expected_native):
    state, private = snapshot()
    receipt = {"status": "inspection_incomplete", "read_only": True,
               "observed_at_utc": datetime.now(timezone.utc).isoformat(),
               "candidate_commit": CANDIDATE, "base_commit": BASE,
               "installed": state, "installed_fingerprint": fingerprint(state),
               "application_writes": 0, "service_operations": 0, "job_mutations": 0,
               "private_provider_calls": 0, "model_calls": 0,
               "full_database_integration_verified": False, "replay_accepted": False,
               "production_release_accepted": False}
    if any(row.get("perps", {}).get("enabled") for row in state["controls"]["units"].values()):
        receipt["error_code"] = "unexpected_perps_enabled"
        return receipt
    receipt["perps_off_in_all_active_services"] = True
    files, references = load_bundle(artifact, expected_native)
    source = state["source"]["files"]
    receipt["schema_sha256"] = source.get("app/schema.py", {}).get("sha256")
    receipt["source_files"] = len(source)
    receipt["source_comparison"] = {
        name: {"matches_base": row["sha256"] == references.get("base", {}).get(name),
               "matches_candidate": row["sha256"] == references.get("candidate", {}).get(name)}
        for name, row in source.items()}
    receipt["missing_candidate_files"] = sorted(set(references.get("candidate", {})) - set(source))
    receipt["candidate_native_sha256"] = expected_native
    with tempfile.TemporaryDirectory(prefix="tau-perps-readiness-") as temporary:
        directory = Path(temporary)
        os.chmod(directory, 0o700)
        for name, raw in files.items():
            path = directory / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o600)
        worker_env = private["recursive-agents"]
        db_env = {name: worker_env[name] for name in
                  ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE") if name in worker_env}
        receipt["database"] = child(directory / "readiness_repository.py", db_env, 35)
        proxy = worker_env.get("TAU_KALSHI_PERPS_PROXY_URL", "").strip()
        public_env = {"TAU_KALSHI_PERPS_PROXY_URL": proxy} if proxy else {}
        receipt["public_feed"] = child(directory / "public_check.py", public_env, 100)
    after, _ = snapshot()
    receipt["temporary_source_cleaned"] = not directory.exists()
    receipt["source_and_controls_unchanged"] = after == state
    if after != state:
        receipt["error_code"] = "installed_state_changed_during_inspection"
    elif (receipt["database"].get("status") == "checked"
          and receipt["database"].get("tables_present", {}).get("app_agent_runs") is True
          and receipt["public_feed"].get("readable_history_and_funding") is True):
        receipt["status"] = "inspected"
    return receipt


def execute(artifact, expected_native):
    try:
        result = inspect(artifact, expected_native)
    except Exception as exc:
        result = {"status": "inspection_incomplete", "read_only": True,
                  "error_code": str(exc) if isinstance(exc, InspectionError) else "inspection_failed"}
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    packed = base64.b64encode(zlib.compress(raw)).decode()
    if len(packed) > 22000:
        result = {"status": "inspection_incomplete", "read_only": True, "error_code": "receipt_size_limit"}
        raw = json.dumps(result).encode()
        packed = base64.b64encode(zlib.compress(raw)).decode()
    print(json.dumps({"encoding": "zlib+base64", "sha256": digest(raw), "payload": packed}))
