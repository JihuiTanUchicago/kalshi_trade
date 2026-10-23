"""Read pinned source into RAM; stage only encrypted bounded inline pages."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess


TEMP_ROOT = Path("/tmp")
ROOT_UID = 0


class CaptureError(RuntimeError):
    pass


def directory(capture_id):
    if not isinstance(capture_id, str) or not re.fullmatch(r"[0-9a-f]{32}", capture_id):
        raise CaptureError("invalid_capture_identity")
    return TEMP_ROOT / ("tau-perps-selected-source-" + capture_id)


def check_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != ROOT_UID or stat.S_IMODE(info.st_mode) != 0o700:
        raise CaptureError("unsafe_capture_directory")


def database_counts(repository_source, worker_env, guard):
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1"}
    env.update({name: worker_env[name] for name in
                ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE") if name in worker_env})
    try:
        response = subprocess.run([guard.PYTHON, "-B", "-c", repository_source], cwd=TEMP_ROOT,
                                  env=env, capture_output=True, timeout=35)
        if response.returncode or len(response.stdout) > 16000:
            raise ValueError()
        value = json.loads(response.stdout)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except Exception:
        return {"status": "unavailable", "error_code": "database_read_failed"}


def capture(capture_id, public_pem, operations_sha, repository_source, guard, protocol):
    if os.geteuid() != ROOT_UID:
        raise CaptureError("requires_root")
    # Config is empty in the reused guard namespace: no protected env file reads.
    before, private = guard.snapshot()
    if any(row.get("perps", {}).get("enabled") for row in before["controls"]["units"].values()):
        raise CaptureError("unexpected_perps_enabled")
    files = {}
    for name, pin in protocol.PINS.items():
        raw, _ = guard.read_regular(guard.ROOT / name, limit=pin["bytes"], owners=(ROOT_UID,))
        files[name] = raw
    protocol.validate_files(files)
    metadata = {"observed_at_utc": datetime.now(timezone.utc).isoformat(),
                "read_only": True, "source_and_controls_unchanged": True,
                "snapshot_fingerprint": guard.fingerprint(before),
                "controls_sha256": guard.fingerprint(before["controls"]),
                "units": before["controls"]["units"],
                "processes": before["controls"]["processes"],
                "protected_environment_files_read": False, "perps_off_in_all_active_services": True,
                "database": database_counts(repository_source, private["recursive-agents"], guard),
                "provider_calls": 0, "model_calls": 0, "application_writes": 0,
                "service_operations": 0, "job_mutations": 0}
    after, _ = guard.snapshot()
    if after != before:
        raise CaptureError("source_or_controls_changed")
    envelope = protocol.encrypt(files, public_pem, capture_id, operations_sha, metadata)
    path = directory(capture_id)
    path.mkdir(mode=0o700)
    try:
        check_directory(path)
        descriptor = os.open(path / "envelope", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(envelope)
        pages = (len(envelope) + protocol.PAGE_BYTES - 1) // protocol.PAGE_BYTES
        return {"status": "captured", "capture_id": capture_id, "pages": pages,
                "envelope_bytes": len(envelope), "envelope_sha256": protocol.digest(envelope),
                "recipient_pem_sha256": protocol.RECIPIENT_PEM_SHA256,
                "source_sha256": {name: pin["sha256"] for name, pin in protocol.PINS.items()},
                "metadata": metadata}
    except Exception:
        cleanup(capture_id)
        raise


def page(capture_id, index, expected_sha, guard, protocol):
    path = directory(capture_id)
    check_directory(path)
    raw, _ = guard.read_regular(path / "envelope", limit=protocol.MAX_ENVELOPE, owners=(ROOT_UID,))
    pages = (len(raw) + protocol.PAGE_BYTES - 1) // protocol.PAGE_BYTES
    if (protocol.digest(raw) != expected_sha or type(index) is not int or not 0 <= index < pages
            or not 1 <= pages <= protocol.MAX_PAGES):
        raise CaptureError("encrypted_page_mismatch")
    content = raw[index * protocol.PAGE_BYTES:(index + 1) * protocol.PAGE_BYTES]
    return {"status": "encrypted_page", "capture_id": capture_id, "index": index, "pages": pages,
            "envelope_sha256": expected_sha, "page_sha256": protocol.digest(content),
            "data": base64.b64encode(content).decode()}


def cleanup(capture_id):
    path = directory(capture_id)
    if path.exists() or path.is_symlink():
        check_directory(path)
        if set(child.name for child in path.iterdir()) - {"envelope"}:
            raise CaptureError("unexpected_capture_entries")
        if (path / "envelope").exists() or (path / "envelope").is_symlink():
            info = (path / "envelope").lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_nlink != 1:
                raise CaptureError("unsafe_capture_file")
            (path / "envelope").unlink()
        path.rmdir()
    return {"status": "cleaned", "capture_id": capture_id, "temporary_directory_removed": True}
