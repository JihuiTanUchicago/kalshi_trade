"""Prepare private hosted state; --check reports readiness without credentials."""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import sys

_SPEC = importlib.util.spec_from_file_location("tau_hosted_bootstrap", Path(__file__).with_name("entrypoint.py"))
hosted = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hosted)
GENERATED = ("mysql_root_password", "mysql_password", "app_secret_key")
INITIALIZATION_FENCE = b"tau-hosted-state-v1\n"


def write_new(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def fence_path(state: Path) -> Path:
    """Keep the initialization record outside replaceable private settings."""
    return state.with_name(state.name + ".initialized")


def initialized(state: Path) -> bool:
    fence = fence_path(state)
    if not fence.exists() and not fence.is_symlink():
        return False
    info = fence.lstat()
    hosted.require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                   and info.st_uid == os.getuid() and info.st_nlink == 1,
                   "unsafe_hosted_initialization_fence")
    hosted.require(hosted.read_private(fence, 128) == INITIALIZATION_FENCE,
                   "unsafe_hosted_initialization_fence")
    return True


def state_directory(folder: Path, *, create: bool, state_dir: Path | None = None) -> Path:
    hosted.require(folder.is_dir() and not folder.is_symlink(), "hosted_directory_invalid")
    state = folder / ".state" if state_dir is None else state_dir
    hosted.require(state.is_absolute() and ".." not in state.parts
                   and state.parent.is_dir() and not state.parent.is_symlink(), "hosted_state_path_invalid")
    if initialized(state):
        hosted.require(state.is_dir() and all((state / name).exists() for name in GENERATED),
                       "initialized_hosted_state_incomplete")
    if create:
        try:
            state.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = state.lstat()
    hosted.require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
                   and info.st_uid == os.getuid(), "unsafe_hosted_state_directory")
    return state


def validate_generated(state: Path) -> None:
    """Never regenerate or silently accept an invalid existing database/vault."""
    values = {name: hosted.read_private(state / name, 256).decode("ascii") for name in GENERATED}
    hosted.require(bool(hosted._PASSWORD.fullmatch(values["mysql_root_password"])), "invalid_database_root_secret")
    hosted.validate_database_secrets({key: values[key] for key in GENERATED[1:]})
    hosted.require(len(set(values.values())) == 3, "generated_secrets_not_independent")


def check(folder: Path, state_dir: Path | None = None) -> dict:
    state = state_directory(folder, create=False, state_dir=state_dir)
    validate_generated(state)
    hosted.require(initialized(state), "hosted_initialization_fence_missing")
    hosted.validate_runtime(hosted.parse_runtime(hosted.read_private(state / "hosted_runtime.json")))
    return {"status": "configuration_ready", "ready": True, "private_state": True,
            "runtime_configuration": True, "provider_authentication": "not_tested", "https_reachability": "not_tested"}


def prepare(folder: Path, state_dir: Path | None = None) -> dict:
    state = state_directory(folder, create=True, state_dir=state_dir)
    ignored = state / ".gitignore"
    if ignored.exists() or ignored.is_symlink():
        hosted.require(hosted.read_private(ignored, 256) == b"*\n", "state_ignore_rule_changed")
    present = [(state / name).exists() or (state / name).is_symlink() for name in GENERATED]
    hosted.require(not any(present) or all(present), "partial_hosted_state_requires_inspection")
    created = not any(present)
    if not created:
        validate_generated(state)
    if not ignored.exists():
        write_new(ignored, b"*\n")
    if created:
        values = {name: secrets.token_urlsafe(32) for name in GENERATED[:2]}
        values["app_secret_key"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        for name in GENERATED:
            write_new(state / name, values[name].encode("ascii"))
    validate_generated(state)
    if not initialized(state):
        write_new(fence_path(state), INITIALIZATION_FENCE)
    runtime = state / "hosted_runtime.json"
    if not runtime.exists() and not runtime.is_symlink():
        write_new(runtime, (json.dumps({key: "" for key in hosted.REQUIRED_RUNTIME}, indent=2) + "\n").encode())
    try:
        readiness = check(folder, state)
    except Exception as exc:
        readiness = {**hosted.safe_error(exc), "ready": False}
    return {"status": "created" if created else "reused", "state_directory": str(state.resolve()),
            "generated_secret_files": 3, "readiness": readiness}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare independent hosted staging state; no Docker/AWS/provider calls.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="Check private configuration; output fields/status only, exit 1 until ready.")
    modes.add_argument("--validate-runtime", action="store_true", help="Validate incoming runtime JSON from stdin without storing or printing its values.")
    parser.add_argument("--state-dir", type=Path, help="Persistent absolute private directory; default: hosted/.state. Never uses a symlink.")
    args = parser.parse_args(argv)
    try:
        folder = Path(__file__).resolve().parent
        if args.validate_runtime:
            hosted.validate_runtime(hosted.parse_runtime(sys.stdin.buffer.read(16385)))
            result = {"status": "runtime_shape_valid", "provider_authentication": "not_tested"}
        else:
            result = check(folder, args.state_dir) if args.check else prepare(folder, args.state_dir)
    except Exception as exc:
        print(json.dumps({**hosted.safe_error(exc), "ready": False}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
