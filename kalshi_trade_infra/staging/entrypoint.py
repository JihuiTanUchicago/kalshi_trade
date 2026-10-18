"""Only schema, unauthenticated web preview, or isolated acceptance may run."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path("/srv/tau-paper-staging")
SECRET_ROOT = Path("/run/secrets")
PYTHON = "/usr/local/bin/python"
RUNTIME_UID = RUNTIME_GID = 10001
MODES = ("schema", "web", "verify")
SECRET_FILES = ("mysql_password", "app_secret_key")
_PASSWORD = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


class StagingError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise StagingError(code)


def read_secret(name: str) -> str:
    require(name in SECRET_FILES, "unrecognized_secret_file")
    path = SECRET_ROOT / name
    before = path.lstat()
    # Compose file-backed secrets retain host ownership. Root reads them only
    # during this bootstrap; never relax the host's private 0600 permissions.
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and stat.S_IMODE(before.st_mode) in (0o400, 0o600) and before.st_size <= 256,
            "unsafe_secret_file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        raw = os.read(descriptor, 257)
        after = os.fstat(descriptor)
        named = path.lstat()
        signature = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                                  info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        require(signature(before) == signature(after) == signature(named) and len(raw) == after.st_size,
                "secret_file_changed")
    finally:
        os.close(descriptor)
    try:
        value = raw.decode("ascii")
    except UnicodeError:
        raise StagingError("invalid_secret_encoding") from None
    require(value == value.strip() and bool(value), "invalid_secret_encoding")
    return value


def child_environment(mode: str, values: dict) -> dict[str, str]:
    require(mode in MODES and set(values) == set(SECRET_FILES), "invalid_staging_mode_or_secrets")
    password, key = values["mysql_password"], values["app_secret_key"]
    require(isinstance(password, str) and bool(_PASSWORD.fullmatch(password)), "invalid_database_secret")
    try:
        decoded = base64.b64decode(key + "=" * (-len(key) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        decoded = b""
    require(len(decoded) == 32, "invalid_vault_secret")
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "MYSQL_HOST": "db", "MYSQL_PORT": "3306", "MYSQL_DATABASE": "tau_paper_staging",
        "MYSQL_USER": "tau_stage", "MYSQL_PASSWORD": password, "APP_SECRET_KEY": key,
        "TAU_STAGING_DISPOSABLE_DB": "1", "APP_HOST": "127.0.0.1", "APP_PORT": "8091",
        "APP_PUBLIC_URL": "http://127.0.0.1:8091", "APP_DEV_LOGIN": "0", "APP_INSECURE_COOKIES": "1",
        "APP_LIVE_TRADING_ENABLED": "0", "APP_NO_SIDE_LIVE_ENABLED": "0",
        "TAU_ALPACA_PAPER_ENABLED": "1", "TAU_ALPACA_PAPER_MAX_ORDER_USD": "500",
        "TAU_DISABLE_CATALOG_MARKETS": "1", "TAU_ALPACA_ENABLED": "0", "TAU_MASSIVE_ENABLED": "0",
        "TAU_DATABENTO_ENABLED": "0", "TAU_EXA_ENABLED": "0", "TAU_EXA_HISTORICAL_ENABLED": "0",
        "TAU_WORLDMONITOR_ENABLED": "0", "TAU_FREE_CREDITS": "0",
        "TAU_ADMIN_EMAIL": "staging-admin@tau.test", "TAU_OPERATOR_EMAIL": "staging-admin@tau.test",
        "TAU_FROM_EMAIL": "staging@tau.test", "TAU_PUBLIC_URL": "http://127.0.0.1:18090",
        "AWS_EC2_METADATA_DISABLED": "true", "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
        "AWS_CONFIG_FILE": "/dev/null",
    }
    if mode == "web":
        # Preserve app.server.main's existing guard: a non-loopback bind always
        # has development sign-in OFF, even though Compose publishes loopback.
        env.update(APP_HOST="0.0.0.0", APP_PORT="8090", APP_PUBLIC_URL="http://127.0.0.1:18090")
    elif mode == "verify":
        env["APP_DEV_LOGIN"] = "1"  # No published port; the harness uses loopback.
    return env


def command(mode: str) -> list[str]:
    require(mode in MODES, "invalid_staging_mode_or_secrets")
    # -I ignores inherited Python paths; only this baked, reviewed package root
    # is explicitly inserted. No environment-provided module/arguments run.
    if mode == "verify":
        code = ("import runpy,sys; sys.path.insert(0," + repr(str(ROOT)) + "); "
                "runpy.run_path(" + repr(str(ROOT / "scripts/paper_staging_smoke.py")) + ",run_name='__main__')")
    else:
        module = "app.schema" if mode == "schema" else "app.server"
        code = ("import runpy,sys; sys.path.insert(0," + repr(str(ROOT)) + "); "
                "runpy.run_module(" + repr(module) + ",run_name='__main__')")
    return [PYTHON, "-I", "-B", "-u", "-c", code]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        require(len(args) == 1 and args[0] in MODES, "invalid_staging_mode_or_secrets")
        require(os.geteuid() == 0, "bootstrap_requires_root")
        require(os.environ.get("TAU_STAGING_CONTAINER") == "isolated-compose-v1", "compose_marker_missing")
        values = {name: read_secret(name) for name in SECRET_FILES}
        env = child_environment(args[0], values)
        invocation = command(args[0])
        os.chdir(ROOT)
        os.setgroups([])
        os.setgid(RUNTIME_GID)
        os.setuid(RUNTIME_UID)  # Clears bootstrap capabilities before app import.
        os.execve(PYTHON, invocation, env)
    except Exception:
        # No secret value, raw exception, child environment or argv is logged.
        print(json.dumps({"status": "failed", "check": "staging_bootstrap"}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
