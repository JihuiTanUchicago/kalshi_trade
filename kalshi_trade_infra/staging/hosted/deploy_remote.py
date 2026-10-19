"""Staging-only SSM operation. Emits a small receipt, never child output or secrets."""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request

ROOT = Path("/opt/tau-staging")
MARKER = Path("/etc/tau-staging-host.json")
STATE = ROOT / "state"
PROJECT = "tau-preproduction"
PARAMETER = "/tau/staging/hosted-runtime"
REGION = "us-east-1"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]


class StageError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(ok: bool, code: str) -> None:
    if not ok:
        raise StageError(code)


def verify_host(path: Path = MARKER) -> None:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
            and not (info.st_mode & 0o022) and info.st_size < 4096, "unsafe_staging_host_marker")
    marker = json.loads(path.read_text())
    require(marker.get("schema_version") == 1 and marker.get("environment") == "staging"
            and marker.get("product") == "Tau" and marker.get("stack_name") == "tau-preproduction-staging"
            and marker.get("root") == str(ROOT), "incorrect_staging_host_marker")
    require(Path("/opt/kalshi").exists() is False, "production_layout_detected")
    require(os.geteuid() == 0, "staging_bootstrap_requires_root")
    require(os.path.ismount(ROOT) and not ROOT.is_symlink(), "staging_data_volume_not_mounted")
    root_info = ROOT.stat()
    require(root_info.st_uid == 0 and not (root_info.st_mode & 0o022), "unsafe_staging_volume_permissions")


def checked(arguments: list[str], timeout: int = 120, env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(arguments, capture_output=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise StageError("staging_command_unavailable_or_timeout") from None
    require(result.returncode == 0, "staging_command_failed")
    return result


def validate_context(context: dict) -> None:
    require(set(context) == {"source_sha", "bundle_sha256", "bucket", "key", "origin", "receipt_key"}, "invalid_staging_context")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", context["source_sha"])), "invalid_source_revision")
    require(bool(re.fullmatch(r"[0-9a-f]{64}", context["bundle_sha256"])), "invalid_bundle_digest")
    require(bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,62}", context["bucket"]))
            and context["bucket"].startswith("tau-preproduction-staging-"), "invalid_staging_bucket")
    require(context["key"] == "releases/" + context["source_sha"] + "/" + context["bundle_sha256"] + ".tgz",
            "invalid_staging_bundle_key")
    require(bool(re.fullmatch(r"receipts/[0-9a-f]{32}\.json", context["receipt_key"])), "invalid_staging_receipt_key")
    require(bool(re.fullmatch(r"https://[a-z0-9]+\.cloudfront\.net", context["origin"]))
            and context["origin"] != "https://d1gfpzcosqrjya.cloudfront.net", "invalid_staging_origin")


def validate_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    require(0 < len(members) <= 4000, "invalid_staging_archive_size")
    total = 0
    seen = set()
    for item in members:
        parts = Path(item.name).parts
        require(bool(parts) and not item.name.startswith("/") and ".." not in parts
                and "\\" not in item.name and item.name not in seen, "unsafe_staging_archive_path")
        require(item.isfile() or item.isdir(), "staging_archive_links_disallowed")
        allowed = (parts[0] in ("app", "data_pipeline")
                   or item.name == "requirements.txt"
                   or (parts[0] == "staging" and (len(parts) == 1 or parts[1] == "hosted")))
        require(allowed, "staging_archive_unexpected_package")
        require(not any(part.startswith(".env") or part in (".state", "credentials", ".git", "__pycache__")
                        for part in parts), "private_file_in_staging_archive")
        require(not item.name.endswith((".pem", ".key", ".p12")), "private_file_in_staging_archive")
        total += item.size
        require(total <= 64 * 1024 * 1024, "staging_archive_too_large")
        seen.add(item.name)
    require({"app/server.py", "app/schema.py", "app/worker.py", "requirements.txt",
             "staging/hosted/entrypoint.py", "staging/hosted/compose.yml", "staging/hosted/setup.py"} <= seen,
            "incomplete_staging_archive")
    return members


def verify_installed_release(target: Path, archive: tarfile.TarFile,
                             members: list[tarfile.TarInfo], digest: str) -> None:
    expected_files = {".bundle-sha256": hashlib.sha256(digest.encode()).digest()}
    expected_dirs = set()
    for member in members:
        relative = Path(member.name)
        expected_dirs.update(parent.as_posix() for parent in relative.parents if parent.as_posix() != ".")
        if member.isdir():
            expected_dirs.add(relative.as_posix())
        else:
            expected_files[relative.as_posix()] = hashlib.sha256(archive.extractfile(member).read()).digest()
    seen_files, seen_dirs = set(), set()
    for path in target.rglob("*"):
        info = path.lstat()
        relative = path.relative_to(target).as_posix()
        require(not path.is_symlink(), "staging_release_changed")
        if stat.S_ISDIR(info.st_mode):
            seen_dirs.add(relative)
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and relative in expected_files
                    and hashlib.sha256(path.read_bytes()).digest() == expected_files[relative], "staging_release_changed")
            seen_files.add(relative)
    require(seen_files == set(expected_files) and seen_dirs == expected_dirs, "staging_release_changed")


def install_release(context: dict) -> Path:
    releases = ROOT / "releases"
    require(not ROOT.is_symlink() and not releases.is_symlink(), "unsafe_staging_release_root")
    releases.mkdir(parents=True, exist_ok=True, mode=0o755)
    target = releases / context["source_sha"]
    payload = checked(["aws", "s3", "cp", "s3://" + context["bucket"] + "/" + context["key"], "-",
                       "--region", REGION, "--only-show-errors"], timeout=120).stdout
    require(hashlib.sha256(payload).hexdigest() == context["bundle_sha256"], "staging_bundle_digest_mismatch")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = validate_members(archive)
        if target.exists():
            require(not target.is_symlink() and target.is_dir(), "unsafe_existing_staging_release")
            verify_installed_release(target, archive, members, context["bundle_sha256"])
            return target
        temporary = Path(tempfile.mkdtemp(prefix="unpack-", dir=releases))
        try:
            archive.extractall(temporary, members=members, filter="data")
            (temporary / ".bundle-sha256").write_text(context["bundle_sha256"])
            verify_installed_release(temporary, archive, members, context["bundle_sha256"])
            temporary.rename(target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return target


def install_runtime(origin: str, release: Path) -> bool:
    # Only this staging parameter is fetched; no production env or GitHub secret
    # is read. The raw JSON stays in memory and one private staging file.
    result = subprocess.run(["aws", "ssm", "get-parameter", "--name", PARAMETER, "--with-decryption",
                             "--region", REGION, "--output", "json", "--no-cli-pager"],
                            capture_output=True, timeout=60)
    if result.returncode:
        if b"ParameterNotFound" in result.stderr:
            return False
        raise StageError("staging_runtime_parameter_unavailable")
    try:
        raw = json.loads(result.stdout)["Parameter"]["Value"].encode("utf-8")
    except (ValueError, KeyError, TypeError):
        raise StageError("invalid_staging_runtime_parameter") from None
    spec = importlib.util.spec_from_file_location("tau_hosted_validator", release / "staging/hosted/entrypoint.py")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    try:
        values = validator.validate_runtime(validator.parse_runtime(raw))
    except Exception:
        raise StageError("invalid_staging_runtime_configuration") from None
    require(values.get("APP_PUBLIC_URL") == origin, "staging_runtime_origin_mismatch")
    require(not STATE.is_symlink(), "unsafe_staging_state_directory")
    info = STATE.stat()
    require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == 0,
            "unsafe_staging_state_directory")
    descriptor, temporary = tempfile.mkstemp(prefix="runtime-", dir=STATE)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(values, stream)
            stream.flush()
            os.fsync(stream.fileno())
        target = STATE / "hosted_runtime.json"
        require(not target.is_symlink(), "unsafe_staging_runtime_file")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def compose_arguments(release: Path) -> list[str]:
    require(release.parent == ROOT / "releases" and bool(re.fullmatch(r"[0-9a-f]{40}", release.name)),
            "invalid_staging_release_directory")
    return DOCKER + ["compose", "--project-name", PROJECT, "--file", str(release / "staging/hosted/compose.yml")]


def verify_existing_database_secrets() -> None:
    result = subprocess.run(DOCKER + ["volume", "inspect", PROJECT + "_hosted-mysql-data"],
                            capture_output=True, timeout=30)
    if result.returncode == 0:
        require(all((STATE / name).is_file() and not (STATE / name).is_symlink()
                    for name in ("mysql_root_password", "mysql_password", "app_secret_key")),
                "existing_staging_database_secrets_missing")
    else:
        require(b"no such volume" in result.stderr.lower(), "staging_database_volume_inventory_failed")


@contextmanager
def deployment_lock():
    operations = ROOT / ".operations"
    operations.mkdir(mode=0o700, exist_ok=True)
    info = operations.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700,
            "unsafe_staging_operations_directory")
    descriptor = os.open(operations / "deploy.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        info = os.fstat(lock.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600, "unsafe_staging_lock_file")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StageError("staging_deployment_already_running") from None
        yield


def deploy_verified(context: dict) -> dict:
    with deployment_lock():
        release = install_release(context)
        verify_existing_database_secrets()
        setup = ["python3", "-I", "-B", str(release / "staging/hosted/setup.py"), "--state-dir", str(STATE)]
        checked(setup)
        receipt = {"status": "pending_staging_configuration", "source_sha": context["source_sha"],
                   "production_changed": False, "research_worker_started": False, "provider_calls": 0,
                   "real_oauth_or_paper_order_accepted": False}
        if not install_runtime(context["origin"], release):
            return {**receipt, "pending_gate": "staging_runtime_parameter"}
        checked(setup + ["--check"])
        invocation = compose_arguments(release)
        environment = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                       "LANG": "C.UTF-8", "TAU_HOSTED_STATE_DIR": str(STATE)}
        checked(invocation + ["build"], timeout=1200, env=environment)
        checked(invocation + ["up", "--detach", "--wait", "db"], timeout=180, env=environment)
        checked(invocation + ["run", "--rm", "--no-deps", "-T", "schema"], timeout=300, env=environment)
        # Schema was run explicitly above. Start each dependent service after
        # its predecessor is healthy without running that migration twice.
        checked(invocation + ["up", "--detach", "--wait", "--no-deps", "--force-recreate", "web"], timeout=180, env=environment)
        checked(invocation + ["up", "--detach", "--wait", "--no-deps", "--force-recreate", "gateway"], timeout=120, env=environment)
        with urllib.request.urlopen("http://127.0.0.1:18091/healthz", timeout=20) as response:
            require(response.status == 200, "staging_gateway_health_failed")
        current = ROOT / "current"
        require(not current.exists() or current.is_symlink(), "unexpected_staging_current_path")
        temporary_link = ROOT / "current.pending"
        require(not temporary_link.exists() and not temporary_link.is_symlink(), "staging_current_link_conflict")
        temporary_link.symlink_to(release)
        os.replace(temporary_link, current)
        return {**receipt, "status": "staging_deployed_pending_user_acceptance", "full_schema_passed": True,
                "gateway_http_200": True, "secure_cookie_configuration": True, "development_login": False}


def publish_receipt(context: dict, receipt: dict) -> None:
    validate_context(context)
    with tempfile.TemporaryDirectory(prefix="tau-staging-receipt-") as directory:
        path = Path(directory) / "receipt.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(receipt, stream)
        checked(["aws", "s3", "cp", str(path), "s3://" + context["bucket"] + "/" + context["receipt_key"],
                 "--region", REGION, "--sse", "AES256", "--only-show-errors"], timeout=60)


def main(context: dict) -> int:
    host_verified = False
    try:
        validate_context(context)
        verify_host()
        host_verified = True
        receipt = deploy_verified(context)
    except Exception as error:
        receipt = {"status": "staging_deployment_requires_inspection",
                   "error_code": error.code if isinstance(error, StageError) else "staging_operation_failed",
                   "production_changed": False, "provider_calls": 0,
                   "real_oauth_or_paper_order_accepted": False}
    if host_verified:
        try:
            publish_receipt(context, receipt)
        except Exception:
            receipt = {"status": "staging_deployment_requires_inspection", "error_code": "staging_receipt_upload_failed",
                       "production_changed": False, "provider_calls": 0}
    print("TAU_HOSTED_REMOTE=" + json.dumps(receipt, separators=(",", ":")), flush=True)
    return 1 if receipt["status"] == "staging_deployment_requires_inspection" else 0


if __name__ == "__main__":
    raise SystemExit(main(globals().get("TAU_STAGING_CONTEXT", {})))
