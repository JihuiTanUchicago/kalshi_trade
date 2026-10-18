"""Narrow runtime overlay primitives; callers own deployment, schema and restarts.

Credential bytes and snapshots are private in-memory objects. Never serialize
them into evidence or command arguments. This module has no subprocess, network,
base-environment reader, service operation or implicit apply entry point.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import shlex
import stat


ROOT_UID = 0
CONFIG_ROOT = Path("/etc/tau/alpaca-paper")
OVERLAY = CONFIG_ROOT / "paper.env"
SERVICES = ("recursive-web", "recursive-agents")
DROP_NAME = "99-tau-alpaca-paper.conf"
INTERPRETER = "/opt/kalshi/.venv313/bin/python"
PUBLIC_URL = "https://d1gfpzcosqrjya.cloudfront.net"
CREDENTIAL_KEYS = ("ALPACA_OAUTH_CLIENT_ID", "ALPACA_OAUTH_CLIENT_SECRET")
SETTINGS = {
    "TAU_ALPACA_PAPER_ENABLED": "1",
    "TAU_ALPACA_PAPER_MAX_ORDER_USD": "500",
    "APP_PUBLIC_URL": PUBLIC_URL,
}
MANAGED_KEYS = frozenset((*CREDENTIAL_KEYS, *SETTINGS))
PROTECTED_PREFIXES = (
    "APP_", "MYSQL_", "PROD_", "KALSHI_", "LIVE_", "DASHBOARD_", "GOOGLE_", "STRIPE_",
    "AWS_", "TAU_", "ALPACA_", "APCA_", "IBKR_", "ROBINHOOD_", "ANTHROPIC_", "OPENAI_",
    "DATABENTO_", "EXA_", "MASSIVE_",
)
MAX_FILE_BYTES = 65536
_CREDENTIAL = re.compile(r"[A-Za-z0-9._~+/=-]{8,4096}\Z")
_INTERPRETER = re.compile(r"/opt/kalshi/\.venv313/bin/python(?:3(?:\.13)?)?\Z")


class ConfigError(RuntimeError):
    """A fixed error code only; no private values, paths or upstream body."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def build_overlay(credentials: dict) -> bytes:
    """Build exactly the authorized flags/public URL and encrypted-transport pair."""
    if not isinstance(credentials, dict) or set(credentials) != set(CREDENTIAL_KEYS):
        raise ConfigError("unexpected_credential_fields")
    values = dict(SETTINGS)
    for key in CREDENTIAL_KEYS:
        value = credentials[key]
        if not isinstance(value, str) or not _CREDENTIAL.fullmatch(value):
            raise ConfigError("invalid_oauth_credential")
        values[key] = value
    # Narrow alphabet plus literal shell quoting: sourcing never evaluates values.
    return ("".join(key + "=" + shlex.quote(value) + "\n" for key, value in values.items())).encode()


def verify_protected_environment(before: dict, after: dict, credentials: dict) -> dict:
    """Verify an offline child environment without exposing existing/new values."""
    build_overlay(credentials)
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ConfigError("invalid_environment_snapshot")
    protected = lambda env: {key: value for key, value in env.items()
                             if isinstance(key, str) and key.startswith(PROTECTED_PREFIXES)
                             and key not in MANAGED_KEYS}
    if protected(before) != protected(after):
        raise ConfigError("protected_environment_changed")
    desired = {**SETTINGS, **credentials}
    if any(after.get(key) != value for key, value in desired.items()):
        raise ConfigError("paper_environment_not_ready")
    return {"protected_settings_unchanged": True, "paper_enabled": True,
            "max_order_usd": SETTINGS["TAU_ALPACA_PAPER_MAX_ORDER_USD"],
            "public_url": PUBLIC_URL, "oauth_pair_present": True}


def _service(service: str) -> None:
    if service not in SERVICES:
        raise ConfigError("unsupported_service")


def drop_path(service: str) -> Path:
    _service(service)
    return Path("/etc/systemd/system") / (service + ".service.d") / DROP_NAME


def _directives(raw: bytes) -> list[str]:
    if not isinstance(raw, bytes) or len(raw) > MAX_FILE_BYTES:
        raise ConfigError("invalid_unit_bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise ConfigError("invalid_unit_bytes") from None
    if "\x00" in text or "\r" in text:
        raise ConfigError("invalid_unit_bytes")
    section = None
    starts = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        key, separator, value = line.partition("=")
        if key.strip() != "ExecStart":
            continue
        if not separator or section != "[Service]" or "\\" in value:
            raise ConfigError("unrecognized_exec_start")
        starts.append(value.strip())
    return starts


def _dropins(service: str, dropins: dict) -> list[tuple[str, bytes]]:
    if not isinstance(dropins, dict):
        raise ConfigError("invalid_dropin_inventory")
    selected = {}
    # Match systemd's same-basename precedence, then lexical ordering.
    roots = {"/usr/lib": 0, "/run": 1, "/etc": 2}
    expression = (r"(/etc|/run|/usr/lib)/systemd/system/" + re.escape(service)
                  + r"\.service\.d/([A-Za-z0-9_.-]+\.conf)\Z")
    for path, raw in dropins.items():
        if not isinstance(path, str):
            raise ConfigError("unrecognized_dropin_path")
        match = re.fullmatch(expression, path)
        if not match:
            raise ConfigError("unrecognized_dropin_path")
        root, name = match.groups()
        if name.startswith(".") or ".." in name:
            raise ConfigError("unrecognized_dropin_path")
        priority = roots[root]
        if name not in selected or priority > selected[name][0]:
            selected[name] = (priority, path, raw)
    return [(path, raw) for _, path, raw in sorted(selected.values(), key=lambda row: Path(row[1]).name)]


def plan_unit(service: str, fragment_bytes: bytes, dropins: dict[str, bytes],
              interpreter: str = INTERPRETER) -> dict:
    """Preserve the recognized effective command, including staged provider data.

    ``dropins`` must contain every applicable loaded/on-disk drop-in. The caller
    checks that inventory against systemctl DropInPaths and rechecks every input
    before apply/reload. No resources, base fragments or existing drop-ins change.
    """
    _service(service)
    if not isinstance(interpreter, str) or not _INTERPRETER.fullmatch(interpreter):
        raise ConfigError("unrecognized_interpreter")
    selected = _dropins(service, dropins)
    commands = []
    for path, raw in [("fragment", fragment_bytes), *selected]:
        directives = _directives(raw)
        if path != "fragment" and Path(path).name > DROP_NAME and directives:
            raise ConfigError("later_exec_start_override")
        for directive in directives:
            if not directive:
                commands.clear()
            else:
                commands.append(directive)
    if len(commands) != 1:
        raise ConfigError("unexpected_exec_start_count")
    try:
        args = shlex.split(commands[0])
    except ValueError:
        raise ConfigError("unrecognized_exec_start") from None
    if len(args) != 3 or args[0] != "/bin/bash" or args[1] not in ("-c", "-ec", "-ce"):
        raise ConfigError("unrecognized_launcher")
    body = args[2]
    insertion = ". " + str(OVERLAY) + " || exit $?; "
    if body.count(str(OVERLAY)) > 1:
        raise ConfigError("duplicate_paper_overlay")
    without_paper = body.replace(insertion, "", 1) if insertion in body else body
    if str(OVERLAY) in without_paper:
        raise ConfigError("unrecognized_paper_overlay")
    prefix = (r"set -a;\s*(?:\.|source) /opt/kalshi/\.env\.aws;\s*"
              r"(?:\.|source) /opt/kalshi/\.env\.app;\s*")
    provider = (r"\. /etc/tau/provider-data/market-data\.env \|\| exit \$\?;\s*"
                r"\. /etc/tau/provider-data/research-data\.env \|\| exit \$\?;\s*"
                + re.escape(interpreter)
                + r" -B -m app\.market_data_config check >/dev/null \|\| exit \$\?;\s*")
    if service == "recursive-agents":
        command = re.escape(interpreter) + r" -u -m app\.worker agents"
        output = r"\s*>>\s*/opt/kalshi/logs/recursive_agents\.log\s*2>&1"
    else:
        # Exact deployed web argv is required; unknown switches/servers fail closed.
        command = (re.escape(interpreter) + r" -u -m app\.server"
                   r"(?: --host (?:127\.0\.0\.1|0\.0\.0\.0))?(?: --port (?:8090|8080))?")
        output = r"\s*>>\s*/opt/kalshi/logs/recursive_web\.log\s*2>&1"
    layout = prefix + "(?:" + provider + ")?" + r"set \+a;\s*unset AWS_PROFILE;\s*exec " + command + output
    if not re.fullmatch(layout, without_paper) or without_paper.count("set +a;") != 1:
        raise ConfigError("unrecognized_launcher_body")
    if insertion in body and insertion + "set +a;" not in body:
        raise ConfigError("paper_overlay_in_wrong_position")
    patched = without_paper.replace("set +a;", insertion + "set +a;", 1)
    rendered = ("[Service]\nExecStart=\nExecStart=" + args[0] + " " + args[1] + " "
                + shlex.quote(patched) + "\n").encode()
    own = [(path, raw) for path, raw in selected if Path(path).name == DROP_NAME]
    if own and (own[0][0] != str(drop_path(service)) or own[0][1] != rendered):
        raise ConfigError("existing_paper_dropin_changed")
    return {"service": service, "drop_path": drop_path(service), "drop_bytes": rendered,
            "body": patched, "source_paths": [path for path, _ in selected],
            "provider_preflight_preserved": "app.market_data_config check" in body,
            "resources_changed": False}


def _directory_chain(path: Path) -> tuple[Path, ...]:
    return (Path("/"), *reversed(path.parents[:-1]), path)


def secure_directory(path: Path, private: bool = False) -> None:
    for directory in _directory_chain(path):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022:
            raise ConfigError("unsafe_directory")
        if private and directory == path and stat.S_IMODE(info.st_mode) != 0o700:
            raise ConfigError("unsafe_private_directory")


def _writable(path: Path) -> None:
    if path not in {OVERLAY, *(drop_path(service) for service in SERVICES)}:
        raise ConfigError("unrecognized_managed_path")


def prepare_directories() -> list[Path]:
    """Create only root-owned private config and the two own drop-in directories."""
    if os.geteuid() != ROOT_UID:
        raise ConfigError("requires_root")
    created = []
    for path, mode in ((CONFIG_ROOT.parent, 0o700), (CONFIG_ROOT, 0o700),
                       *((drop_path(service).parent, 0o755) for service in SERVICES)):
        secure_directory(path.parent)
        try:
            path.mkdir(mode=mode)
            created.append(path)
        except FileExistsError:
            pass
        secure_directory(path, private=path == CONFIG_ROOT)
    return created


def _signature(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def snapshot(path: Path) -> dict | None:
    """Private own-file snapshot; refuses base environments and provider overlays."""
    _writable(path)
    secure_directory(path.parent, private=path == OVERLAY)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != ROOT_UID or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > MAX_FILE_BYTES):
        raise ConfigError("unsafe_managed_file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        raw = os.read(descriptor, MAX_FILE_BYTES + 1)
        after = os.fstat(descriptor)
        named = path.lstat()
        if _signature(before) != _signature(after) or _signature(after) != _signature(named) or len(raw) != after.st_size:
            raise ConfigError("managed_file_changed_during_read")
        return {"raw": raw, "signature": _signature(after)}
    finally:
        os.close(descriptor)


def atomic_write(path: Path, raw: bytes, expected: dict | None) -> dict:
    """Compare before replace; new own files are always root-owned mode 0600."""
    _writable(path)
    if os.geteuid() != ROOT_UID:
        raise ConfigError("requires_root")
    if not isinstance(raw, bytes) or len(raw) > MAX_FILE_BYTES:
        raise ConfigError("invalid_managed_bytes")
    if snapshot(path) != expected:
        raise ConfigError("concurrent_managed_file_change")
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".tau-paper-" + secrets.token_hex(16)
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if snapshot(path) != expected:
            raise ConfigError("concurrent_managed_file_change")
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)
    return snapshot(path)


def restore(path: Path, original: dict | None, installed: dict) -> dict | None:
    """Rollback only an unchanged own file; never reload/restart a service."""
    _writable(path)
    if os.geteuid() != ROOT_UID:
        raise ConfigError("requires_root")
    if snapshot(path) != installed:
        raise ConfigError("concurrent_managed_file_change")
    if original is not None:
        return atomic_write(path, original["raw"], installed)
    path.unlink()
    return None
