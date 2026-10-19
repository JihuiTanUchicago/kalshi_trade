"""Dedicated hosted pre-production bootstrap; no production or inherited config.

Runtime validation establishes configuration shape, never provider acceptance.
Only complete sandbox billing + real OAuth-shaped configuration enables web.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlsplit

ROOT = Path("/srv/tau-hosted-preproduction")
SECRET_ROOT = Path("/run/secrets")
PYTHON = "/usr/local/bin/python"
RUNTIME_UID = RUNTIME_GID = 10001
MODES = ("schema", "web")
DATABASE = "tau_preproduction_staging"
DATABASE_USER = "tau_preprod"
REQUIRED_RUNTIME = (
    "APP_PUBLIC_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "ALPACA_OAUTH_CLIENT_ID", "ALPACA_OAUTH_CLIENT_SECRET",
    "STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET", "TAU_ADMIN_EMAIL",
)
OPTIONAL_RUNTIME = ("STRIPE_PAYMENT_CONFIG",)
KNOWN_PRODUCTION_ORIGIN = "d1gfpzcosqrjya.cloudfront.net"
_PASSWORD = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_OAUTH_VALUE = re.compile(r"[A-Za-z0-9._~+/=-]{8,512}\Z")


class HostedError(RuntimeError):
    def __init__(self, code: str, fields=()):
        self.code = code
        self.fields = tuple(fields)
        super().__init__(code)


def require(condition: bool, code: str, fields=()) -> None:
    if not condition:
        raise HostedError(code, fields)


def read_private(path: Path, max_bytes: int = 16384) -> bytes:
    """Accept root/operator-owned bind secrets without relaxing host permissions."""
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and stat.S_IMODE(before.st_mode) in (0o400, 0o600) and before.st_size <= max_bytes,
            "unsafe_private_file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        raw = os.read(descriptor, max_bytes + 1)
        after, named = os.fstat(descriptor), path.lstat()
        signature = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                                  info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        require(signature(before) == signature(after) == signature(named) and len(raw) == after.st_size,
                "private_file_changed")
        return raw
    finally:
        os.close(descriptor)


def parse_runtime(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate_runtime_field")
            result[key] = value
        return result

    try:
        require(isinstance(raw, bytes) and len(raw) <= 16384, "runtime_json_invalid")
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError):
        raise HostedError("runtime_json_invalid") from None
    require(isinstance(result, dict), "runtime_json_invalid")
    return result


def _origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname or "", parsed.port
        valid = (parsed.scheme == "https" and not parsed.username and not parsed.password
                 and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                 and all(33 <= ord(char) <= 126 for char in value)
                 and (port is None or 1 <= port <= 65535)
                 and bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host))
                 and "." in host and not host.endswith(".") and ".." not in host)
        try:
            ipaddress.ip_address(host)
            valid = False
        except ValueError:
            pass
    except ValueError:
        valid, host = False, ""
    forbidden = (host == KNOWN_PRODUCTION_ORIGIN or host.endswith("." + KNOWN_PRODUCTION_ORIGIN)
                 or host in ("localhost", "example.com", "example.net", "example.org")
                 or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".example")))
    require(valid and not forbidden, "hosted_origin_invalid", ("APP_PUBLIC_URL",))
    return value.rstrip("/")


def validate_runtime(values: dict) -> dict[str, str]:
    require(isinstance(values, dict) and not set(values) - set(REQUIRED_RUNTIME + OPTIONAL_RUNTIME),
            "unexpected_runtime_fields")
    missing = [key for key in REQUIRED_RUNTIME if not isinstance(values.get(key), str) or not values[key]]
    require(not missing, "runtime_values_missing", missing)
    require(all(isinstance(value, str) and len(value) <= 2048
                and all(33 <= ord(char) <= 126 for char in value)
                for key, value in values.items() if value != ""), "runtime_value_invalid")
    result = dict(values)
    result["APP_PUBLIC_URL"] = _origin(values["APP_PUBLIC_URL"])
    require(bool(re.fullmatch(r"[A-Za-z0-9_-]{8,180}\.apps\.googleusercontent\.com", values["GOOGLE_CLIENT_ID"])),
            "google_client_id_invalid", ("GOOGLE_CLIENT_ID",))
    for key in ("GOOGLE_CLIENT_SECRET", "ALPACA_OAUTH_CLIENT_ID", "ALPACA_OAUTH_CLIENT_SECRET"):
        value = values[key]
        require(bool(_OAUTH_VALUE.fullmatch(value))
                and not value.lower().startswith(("synthetic", "placeholder", "replace", "your_", "changeme")),
                "oauth_value_invalid", (key,))
    for key, prefix in (("STRIPE_SECRET_KEY", "sk_test_"), ("STRIPE_PUBLISHABLE_KEY", "pk_test_"),
                        ("STRIPE_WEBHOOK_SECRET", "whsec_")):
        require(bool(re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_=-]{16,240}", values[key])),
                "stripe_sandbox_configuration_invalid", (key,))
    if result.get("STRIPE_PAYMENT_CONFIG"):
        require(bool(re.fullmatch(r"pmc_[A-Za-z0-9]{8,180}", result["STRIPE_PAYMENT_CONFIG"])),
                "stripe_payment_config_invalid", ("STRIPE_PAYMENT_CONFIG",))
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", values["TAU_ADMIN_EMAIL"])),
            "admin_email_invalid", ("TAU_ADMIN_EMAIL",))
    return result


def validate_database_secrets(values: dict) -> None:
    require(set(values) == {"mysql_password", "app_secret_key"}, "unexpected_database_secret_fields")
    require(isinstance(values["mysql_password"], str) and bool(_PASSWORD.fullmatch(values["mysql_password"])),
            "invalid_database_secret")
    key = values["app_secret_key"]
    try:
        decoded = base64.b64decode(key + "=" * (-len(key) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        decoded = b""
    require(len(decoded) == 32, "invalid_vault_secret")


def child_environment(mode: str, secrets: dict, runtime: dict | None = None) -> dict[str, str]:
    require(mode in MODES, "unsupported_hosted_mode")
    validate_database_secrets(secrets)
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "MYSQL_HOST": "db", "MYSQL_PORT": "3306", "MYSQL_DATABASE": DATABASE,
        "MYSQL_USER": DATABASE_USER, "MYSQL_PASSWORD": secrets["mysql_password"],
        "APP_SECRET_KEY": secrets["app_secret_key"], "APP_HOST": "0.0.0.0", "APP_PORT": "8090",
        "APP_DEV_LOGIN": "0", "APP_INSECURE_COOKIES": "0",
        "APP_LIVE_TRADING_ENABLED": "0", "APP_NO_SIDE_LIVE_ENABLED": "0",
        "TAU_ALPACA_PAPER_ENABLED": "1", "TAU_ALPACA_PAPER_MAX_ORDER_USD": "500",
        "TAU_DISABLE_CATALOG_MARKETS": "1", "TAU_ALPACA_ENABLED": "0", "TAU_MASSIVE_ENABLED": "0",
        "TAU_DATABENTO_ENABLED": "0", "TAU_EXA_ENABLED": "0", "TAU_EXA_HISTORICAL_ENABLED": "0",
        "TAU_WORLDMONITOR_ENABLED": "0", "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_SHARED_CREDENTIALS_FILE": "/dev/null", "AWS_CONFIG_FILE": "/dev/null",
    }
    if mode == "web":
        checked = validate_runtime(runtime)
        env.update(checked)
        env["APP_GOOGLE_REDIRECT_URI"] = checked["APP_PUBLIC_URL"] + "/auth/google/callback"
        env["TAU_PUBLIC_URL"] = checked["APP_PUBLIC_URL"]
        env["TAU_OPERATOR_EMAIL"] = checked["TAU_ADMIN_EMAIL"]
    else:
        require(runtime is None, "schema_runtime_credentials_forbidden")
    return env


def command(mode: str) -> list[str]:
    require(mode in MODES, "unsupported_hosted_mode")
    module = "app.schema" if mode == "schema" else "app.server"
    code = ("import runpy,sys;sys.path.insert(0," + repr(str(ROOT)) + ");"
            "runpy.run_module(" + repr(module) + ",run_name='__main__')")
    return [PYTHON, "-I", "-B", "-u", "-c", code]


def safe_error(exc: Exception) -> dict:
    result = {"status": "blocked", "check": "hosted_configuration",
              "error_code": exc.code if isinstance(exc, HostedError) else "private_configuration_unavailable"}
    if isinstance(exc, HostedError) and exc.fields:
        result["fields"] = list(exc.fields)
    return result


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        require(len(args) == 1 and args[0] in MODES, "unsupported_hosted_mode")
        require(os.geteuid() == 0 and os.environ.get("TAU_HOSTED_CONTAINER") == "dedicated-preproduction-v1",
                "hosted_bootstrap_context_invalid")
        secrets = {name: read_private(SECRET_ROOT / name, 256).decode("ascii")
                   for name in ("mysql_password", "app_secret_key")}
        runtime = parse_runtime(read_private(SECRET_ROOT / "hosted_runtime.json")) if args[0] == "web" else None
        env, invocation = child_environment(args[0], secrets, runtime), command(args[0])
        os.chdir(ROOT)
        os.setgroups([])
        os.setgid(RUNTIME_GID)
        os.setuid(RUNTIME_UID)
        os.execve(PYTHON, invocation, env)
    except Exception as exc:
        print(json.dumps(safe_error(exc), sort_keys=True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
