"""Generate host-private disposable staging secrets; Docker is not required."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

NAMES = ("mysql_root_password", "mysql_password", "app_secret_key")
_PASSWORD = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


class SetupError(RuntimeError):
    pass


def private_file(path: Path) -> bytes:
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > 256):
        raise SetupError("unsafe_state_file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        raw = os.read(descriptor, 257)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise SetupError("state_file_changed")
        return raw
    finally:
        os.close(descriptor)


def _write_new(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def prepare(staging_dir: Path) -> dict:
    if staging_dir.is_symlink() or not staging_dir.is_dir():
        raise SetupError("invalid_staging_directory")
    state = staging_dir / ".state"
    try:
        state.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = state.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise SetupError("unsafe_state_directory")
    # Install the ignore rule before creating any secret, including during a
    # concurrent source-publication session. No secret is temporarily unignored.
    ignored = state / ".gitignore"
    if ignored.exists() or ignored.is_symlink():
        if private_file(ignored) != b"*\n":
            raise SetupError("state_ignore_rule_changed")
    else:
        _write_new(ignored, b"*\n")
    present = [(state / name).exists() or (state / name).is_symlink() for name in NAMES]
    if any(present) and not all(present):
        raise SetupError("partial_state_requires_inspection")
    if all(present):
        values = {name: private_file(state / name).decode("ascii") for name in NAMES}
        if any(not _PASSWORD.fullmatch(values[name]) for name in NAMES[:2]):
            raise SetupError("invalid_existing_state")
        key = values["app_secret_key"]
        if len(base64.b64decode(key + "=" * (-len(key) % 4), altchars=b"-_", validate=True)) != 32:
            raise SetupError("invalid_existing_state")
        status = "reused"
    else:
        values = {name: secrets.token_urlsafe(32) for name in NAMES[:2]}
        values["app_secret_key"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        for name in NAMES:
            _write_new(state / name, values[name].encode("ascii"))
        status = "created"
    if len(set(values.values())) != len(NAMES):
        raise SetupError("state_values_must_be_distinct")
    return {"status": status, "state_directory": str(state.resolve()), "secret_files": len(NAMES)}


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise SetupError("arguments_not_supported")
        result = prepare(Path(__file__).resolve().parent)
    except Exception:
        print(json.dumps({"status": "failed", "check": "private_staging_setup"}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
