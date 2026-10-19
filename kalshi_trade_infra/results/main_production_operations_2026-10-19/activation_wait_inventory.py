"""Read-only activation inventory. Never print raw environments, units or SQL errors."""
import contextlib
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys

ROOT = Path("/opt/kalshi")
CONFIG_ROOT = Path("/etc/tau/provider-data")
PROVIDER_DROP = Path("/etc/systemd/system/recursive-agents.service.d/90-tau-provider-data.conf")
SERVICE = "recursive-agents"
KEYS = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "MASSIVE_API_KEY", "DATABENTO_API_KEY", "EXA_API_KEY", "APP_SECRET_KEY", "ANTHROPIC_API_KEY")
ENUMS = {
    "TAU_MARKET_DATA_PRIMARY": {"alpaca", "databento"},
    "TAU_ALPACA_FEED": {"iex", "sip"},
    "TAU_MASSIVE_FX_FEED": {"end_of_day", "realtime"},
    "ALPACA_DATA_ENDPOINT": {"https://data.alpaca.markets"},
}
FLAGS = ("TAU_ALPACA_ENABLED", "TAU_MASSIVE_ENABLED", "TAU_DATABENTO_ENABLED", "TAU_EXA_ENABLED", "TAU_EXA_HISTORICAL_ENABLED", "TAU_WORLDMONITOR_ENABLED")
NUMBERS = ("APP_AGENT_CONCURRENCY", "APP_COPILOT_REVIEW_SECONDS", "APP_AUTOPILOT_MIN_REVIEW_SECONDS", "TAU_DATABENTO_MAX_COST_USD")
LISTS = ("TAU_DATABENTO_DATASETS", "TAU_DATABENTO_DEFAULT_DATASET", "TAU_MASSIVE_DATASETS", "TAU_ALPACA_SYMBOLS", "TAU_MASSIVE_FX_SYMBOLS")
SOURCE_FILES = ("app/agent_market_data.py", "app/market_data_config.py", "app/alpaca_data.py", "app/massive_data.py", "app/databento_data.py", "app/exa_data.py", "app/agent_knowledge.py", "app/worker.py", "scripts/configure_market_data.py")
MARKET_ASSIGNMENTS = set(ENUMS) | set(LISTS) | {
    "TAU_ALPACA_ENABLED", "TAU_MASSIVE_ENABLED", "TAU_DATABENTO_ENABLED", "TAU_DATABENTO_MAX_COST_USD",
    "APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "MASSIVE_API_KEY", "DATABENTO_API_KEY",
}
RESEARCH_ASSIGNMENTS = {"EXA_API_KEY", "TAU_EXA_ENABLED", "TAU_EXA_HISTORICAL_ENABLED"}


def _secret_values(env):
    return [value for key, value in env.items() if re.search(r"KEY|SECRET|TOKEN|PASSWORD", key)
            and isinstance(value, str) and len(value) >= 8]


def safe_settings(env):
    result, sensitive = {}, _secret_values(env)
    for name in (*FLAGS, *ENUMS, *NUMBERS, *LISTS):
        value = env.get(name)
        if value is None:
            result[name] = None
            continue
        valid = isinstance(value, str) and len(value) <= 256 and not any(secret in value for secret in sensitive)
        if valid and name in FLAGS:
            valid = value in {"0", "1"}
        elif valid and name in ENUMS:
            valid = value in ENUMS[name]
        elif valid and name in NUMBERS:
            try:
                amount = Decimal(value)
                valid = bool(re.fullmatch(r"[0-9.eE+-]{1,64}", value)) and amount.is_finite() and amount >= 0
            except Exception:
                valid = False
        elif valid:
            parts = [part.strip() for part in value.split(",")]
            if name.startswith("TAU_DATABENTO_"):
                valid = len(parts) <= 8 and all(re.fullmatch(r"[A-Z0-9]{3,8}\.[A-Z0-9]{2,16}", part) for part in parts)
            elif name == "TAU_MASSIVE_DATASETS":
                valid = len(parts) <= 4 and set(parts) <= {"fx", "treasury_yields", "funding_conditions", "options"}
            elif name == "TAU_ALPACA_SYMBOLS":
                valid = len(parts) <= 8 and all(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", part) for part in parts)
            else:
                valid = len(parts) <= 3 and all(re.fullmatch(r"(?:C:)?[A-Z]{3}/?[A-Z]{3}", part) for part in parts)
        result[name] = value if valid else "[invalid_or_redacted]"
    return {"credential_presence": {key: bool(env.get(key)) for key in KEYS}, "settings": result}


def classify_exec_start(text, interpreter=None):
    text = re.sub(r"\\x([0-9a-fA-F]{2})", lambda match: chr(int(match[1], 16)), text)
    sources = [match[1] for match in re.finditer(r"(?:^|[;\s'\"])(?:source|\.)\s+['\"]?/opt/kalshi/(\.env\.(?:aws|app|market-data|research-data))(?=['\";\s]|$)", text)]
    python = re.search(r"(/opt/kalshi/\.venv(?:313)?/bin/python(?:3(?:\.\d{1,2})?)?)(?=\s|['\"]|$)", text)
    result = {
        "uses_bash": "/bin/bash" in text,
        "uses_bash_c": bool(re.search(r"/bin/bash\s+-[a-zA-Z]*c[a-zA-Z]*(?=\s|['\"]|$)", text)),
        "module_app_worker_agents": bool(re.search(r"-m\s+app\.worker\s+agents(?=\s|[;'\"]|$)", text)),
        "sources_in_order": sources,
        "sources_base_aws_then_app": ".env.aws" in sources and ".env.app" in sources and sources.index(".env.aws") < sources.index(".env.app"),
        "uses_set_a": bool(re.search(r"(?:^|[;\s'\"])set\s+-a(?=\s|;|$)", text)),
        "unsets_aws_profile": bool(re.search(r"unset\s+AWS_PROFILE(?=\s|;|$)", text)),
        "logging_redirected": bool(re.search(r">{1,2}\s*/opt/kalshi/logs/recursive_agents\.log", text)),
        "stderr_joined_to_stdout": "2>&1" in text,
        "interpreter_matches_mainpid": bool(python and interpreter and python[1] == interpreter),
        "exec_start_mentions_market_preflight": "app.market_data_config" in text,
        "exec_start_resets_definition": bool(re.search(r"(?m)^ExecStart=\s*$", text)),
    }
    result["recognized_base_shell_layout"] = all(result[key] for key in ("uses_bash_c", "module_app_worker_agents", "sources_base_aws_then_app", "uses_set_a"))
    return result


def _directory(path):
    result = {"exists": False}
    try:
        info = path.lstat()
        result.update(exists=True, mode=format(stat.S_IMODE(info.st_mode), "04o"),
                      owner_is_root=info.st_uid == 0, symlink=stat.S_ISLNK(info.st_mode),
                      directory=stat.S_ISDIR(info.st_mode))
        result["parent_chain_secure"] = all(
            stat.S_ISDIR(parent.lstat().st_mode) and parent.lstat().st_uid == 0
            and not parent.lstat().st_mode & 0o022
            for parent in path.parents
        )
    except FileNotFoundError:
        pass
    except Exception:
        result["status"] = "metadata_read_failed"
    return result


def _no_unrecognized_pending_dropins():
    try:
        for directory in (Path('/etc/systemd/system/recursive-agents.service.d'),
                          Path('/run/systemd/system/recursive-agents.service.d'),
                          Path('/usr/lib/systemd/system/recursive-agents.service.d')):
            try:
                info = directory.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                return False
            if any(path != PROVIDER_DROP for path in directory.glob('*.conf')):
                return False
        return True
    except Exception:
        return False


def _staged_startup(fragment, interpreter):
    """Recompute the reviewed drop-in privately; return booleans and a code only."""
    result = {"status": "unrecognized", "provider_dropin_matches_expected": False}
    descriptor = None
    try:
        if not re.fullmatch(r"/(?:etc|run|usr/lib)/systemd/system/recursive-agents\.service", fragment):
            return result
        descriptor = os.open(fragment, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 262144:
            return result
        raw = os.read(descriptor, 262145)
        lines = [line.strip() for line in raw.decode().splitlines() if line.strip().startswith("ExecStart=")]
        if len(lines) != 1 or "\\" in lines[0]:
            return result
        args = shlex.split(lines[0].split("=", 1)[1])
        if len(args) != 3 or args[0] != "/bin/bash" or args[1] not in ("-c", "-ec", "-ce"):
            return result
        body = args[2]
        pattern = (r"set -a;\s*\. /opt/kalshi/\.env\.aws;\s*\. /opt/kalshi/\.env\.app;\s*"
                   r"set \+a;\s*unset AWS_PROFILE;\s*exec " + re.escape(interpreter)
                   + r" -u -m app\.worker agents\s*>>\s*/opt/kalshi/logs/recursive_agents\.log\s*2>&1")
        if not re.fullmatch(pattern, body) or body.count("set +a;") != 1:
            return result
        insertion = (". " + shlex.quote(str(CONFIG_ROOT / "market-data.env")) + " || exit $?; "
                     ". " + shlex.quote(str(CONFIG_ROOT / "research-data.env")) + " || exit $?; "
                     + interpreter + " -B -m app.market_data_config check >/dev/null || exit $?; ")
        patched = body.replace("set +a;", insertion + "set +a;", 1)
        expected = ("[Service]\nExecStart=\nExecStart=" + args[0] + " " + args[1] + " " + shlex.quote(patched) + "\n").encode()
        drop = _file(PROVIDER_DROP, hashed=True)
        matches = drop.get("sha256") == hashlib.sha256(expected).hexdigest()
        return {"status": "recognized", "fragment_launch_compatible": True,
                "provider_dropin_matches_expected": matches}
    except Exception:
        return result
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _file(path, *, hashed=False, overlay=False, secrets=()):
    result = {"exists": False}
    fd = None
    try:
        info = path.lstat()
        result.update(exists=True, mode=format(stat.S_IMODE(info.st_mode), "04o"),
                      size_bytes=info.st_size, owner_is_root=info.st_uid == 0,
                      symlink=stat.S_ISLNK(info.st_mode), regular_file=stat.S_ISREG(info.st_mode),
                      modified_at_utc=datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat())
        if not stat.S_ISREG(info.st_mode):
            return result
        if overlay and (stat.S_IMODE(info.st_mode) & 0o077):
            result["content_read"] = "withheld_insecure_permissions"
            return result
        if not (hashed or overlay):
            return result
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        if not os.path.samestat(info, os.fstat(fd)) or info.st_size > 1024 * 1024:
            result["content_read"] = "withheld_changed_or_large_file"
            return result
        raw = os.read(fd, 1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            result["content_read"] = "withheld_large_file"
            return result
        text = raw.decode("utf-8")
        if hashed:
            unit = path.suffix in {".service", ".conf"}
            sensitive = any(secret in text for secret in secrets) or (unit and bool(re.search(r"\b[A-Z_][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*\s*=", text)))
            result["sha256"] = None if sensitive else hashlib.sha256(raw).hexdigest()
            result["hash_withheld_sensitive_content"] = sensitive
            if path.suffix in {".service", ".conf"}:
                result["structure"] = classify_exec_start(text)
                result["environment_file_mentions"] = [name for name in (".env.aws", ".env.app", ".env.market-data", ".env.research-data") if name in text]
                result["has_exec_start"] = bool(re.search(r"(?m)^ExecStart=", text))
        if overlay:
            values, invalid, unexpected, duplicates = {}, 0, 0, 0
            allowed = RESEARCH_ASSIGNMENTS if path.name == "research-data.env" else MARKET_ASSIGNMENTS
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.fullmatch(r"(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)", line)
                if not match:
                    invalid += 1
                    continue
                try:
                    lexer = shlex.shlex(match[2], posix=True, punctuation_chars=";&|<>")
                    lexer.whitespace_split = True
                    tokens = list(lexer)
                    if (len(tokens) > 1 or "$" in match[2] or "`" in match[2]
                            or any(ord(char) < 32 or ord(char) == 127 for char in match[2])
                            or (tokens and tokens[0] and all(char in ";&|<>" for char in tokens[0]))):
                        raise ValueError()
                    unexpected += match[1] not in allowed
                    duplicates += match[1] in values
                    values[match[1]] = tokens[0] if tokens else ""
                except ValueError:
                    invalid += 1
            result.update(safe_settings(values))
            result["literal_parse_valid"] = invalid == 0 and duplicates == 0 and unexpected == 0
            result["invalid_assignment_count"] = invalid
            result["unexpected_assignment_count"] = unexpected
            result["duplicate_assignment_count"] = duplicates
        return result
    except FileNotFoundError:
        return result
    except Exception:
        result["status"] = "metadata_or_safe_read_failed"
        return result
    finally:
        if fd is not None:
            os.close(fd)


class InventoryRepository:
    """Aggregate-only queries, using the existing common DB connection layer."""
    @staticmethod
    def job_summary(connection):
        cursor = connection.cursor()
        try:
            cursor.execute("START TRANSACTION READ ONLY")
            cursor.execute("""SELECT CASE WHEN kind IN ('research','chat','review') THEN kind ELSE 'other' END AS run_kind,
                status, COUNT(*) AS n,
                MIN(TIMESTAMPDIFF(SECOND, heartbeat_at, UTC_TIMESTAMP())) AS newest_heartbeat_age_seconds,
                MAX(TIMESTAMPDIFF(SECOND, heartbeat_at, UTC_TIMESTAMP())) AS oldest_heartbeat_age_seconds,
                SUM(heartbeat_at IS NULL) AS missing_heartbeats
                FROM app_agent_runs WHERE status IN ('queued','running','paused')
                GROUP BY run_kind, status LIMIT 16""")
            groups = [{key: row[key] if key in {"run_kind", "status"} else (int(row[key]) if row[key] is not None else None)
                       for key in ("run_kind", "status", "n", "newest_heartbeat_age_seconds", "oldest_heartbeat_age_seconds", "missing_heartbeats")}
                      for row in cursor.fetchall()]
            cursor.execute("SELECT TIMESTAMPDIFF(SECOND, MAX(finished_at), UTC_TIMESTAMP()) AS seconds_since_latest_finished FROM app_agent_runs")
            latest = cursor.fetchone()["seconds_since_latest_finished"]
            return {"status": "available", "transaction": "read_only", "active_groups": groups,
                    "queued": sum(row["n"] for row in groups if row["status"] == "queued"),
                    "running": sum(row["n"] for row in groups if row["status"] == "running"),
                    "paused": sum(row["n"] for row in groups if row["status"] == "paused"),
                    "seconds_since_latest_finished": int(latest) if latest is not None else None}
        finally:
            connection.rollback()
            cursor.close()


def inventory():
    properties = ("MainPID,ActiveState,SubState,FragmentPath,DropInPaths,ExecStart,EnvironmentFiles,"
                  "MemoryMax,MemoryHigh,MemorySwapMax,MemoryCurrent,Nice,TimeoutStartUSec,TimeoutStopUSec,Restart,RestartUSec,KillMode,KillSignal")
    response = subprocess.run(["systemctl", "show", SERVICE, "--property=" + properties],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15, check=True)
    props = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
    result = {"mode": "activation_inventory", "read_only": True, "provider_calls": 0, "model_calls": 0,
              "checked_at_utc": datetime.now(timezone.utc).isoformat(), "service": SERVICE}
    pid = int(props.get("MainPID", "0"))
    result["main_pid"] = pid
    if pid <= 0:
        result["status"] = "no_running_worker"
        return result
    process = Path("/proc") / str(pid)
    env = dict(item.decode("utf-8", "replace").split("=", 1) for item in (process / "environ").read_bytes().split(b"\0") if b"=" in item)
    argv = [item.decode("utf-8", "replace") for item in (process / "cmdline").read_bytes().split(b"\0") if item]
    cwd_ok = (process / "cwd").resolve() == ROOT
    interpreter = argv[0] if argv and re.fullmatch(r"/opt/kalshi/\.venv(?:313)?/bin/python(?:3(?:\.\d{1,2})?)?", argv[0]) else None
    result.update(safe_settings(env))
    result.update(cwd=str(ROOT) if cwd_ok else "[unexpected]", interpreter=interpreter or "[unexpected]",
                  worker_module_argv=any(argv[index:index + 3] == ["-m", "app.worker", "agents"] for index in range(len(argv))))
    result["exec_start"] = classify_exec_start(props.get("ExecStart", ""), interpreter)
    result["environment_file_mentions"] = [name for name in (".env.aws", ".env.app", ".env.market-data", ".env.research-data") if name in props.get("EnvironmentFiles", "")]
    result["service_settings"] = {key: value if re.fullmatch(r"[a-z0-9 -]{1,64}", value) else "[invalid_or_redacted]"
                                  for key, value in props.items() if key in {"ActiveState", "SubState", "MemoryMax", "MemoryHigh", "MemorySwapMax", "MemoryCurrent", "Nice", "TimeoutStartUSec", "TimeoutStopUSec", "Restart", "RestartUSec", "KillMode", "KillSignal"}}
    sensitive = _secret_values(env)
    paths = [("fragment", props.get("FragmentPath", ""))]
    paths += [("drop_in_" + str(index), value) for index, value in enumerate(shlex.split(props.get("DropInPaths", ""))) ]
    result["drop_in_count"] = len(paths) - 1
    result["installed_unit_files"] = {}
    for label, value in paths[:33]:
        allowed = re.fullmatch(r"/(?:etc|run|usr/lib|lib)/systemd/system/recursive-agents\.service(?:\.d/[^/\x00-\x1f]+\.conf)?", value)
        result["installed_unit_files"][label] = _file(Path(value), hashed=True, secrets=sensitive) if allowed else {"status": "path_withheld_or_unrecognized"}
    result["provider_directory"] = _directory(CONFIG_ROOT)
    result["protected_overlays"] = {name: _file(CONFIG_ROOT / name, overlay=True) for name in ("market-data.env", "research-data.env")}
    result["staged_provider_dropin"] = _file(PROVIDER_DROP, hashed=True, secrets=sensitive)
    result["staged_startup"] = _staged_startup(props.get("FragmentPath", ""), interpreter or "")
    result["no_unrecognized_pending_dropins"] = _no_unrecognized_pending_dropins()
    result["app_source_files"] = {name: _file(ROOT / name, hashed=True, secrets=sensitive) for name in SOURCE_FILES}
    result["database_jobs"] = {"status": "not_checked_unexpected_process_layout"}
    if cwd_ok and interpreter and result["worker_module_argv"]:
        old_env, old_path, old_bytecode = dict(os.environ), list(sys.path), sys.dont_write_bytecode
        old_logging, connection = logging.root.manager.disable, None
        try:
            os.environ.clear()
            os.environ.update(env)
            sys.path.insert(0, str(ROOT))
            sys.dont_write_bytecode = True
            logging.disable(logging.CRITICAL)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                from data_pipeline.common import get_db_conn
                connection = get_db_conn()
                result["database_jobs"] = InventoryRepository.job_summary(connection)
        except Exception:
            result["database_jobs"] = {"status": "read_only_query_failed"}
        finally:
            if connection is not None:
                connection.close()
            os.environ.clear()
            os.environ.update(old_env)
            sys.path[:] = old_path
            sys.dont_write_bytecode = old_bytecode
            logging.disable(old_logging)
    serialized = json.dumps(result)
    if any(secret in serialized for secret in sensitive):
        raise RuntimeError("InventoryRedactionCheckFailed")
    result["status"] = "inspected"
    return result


def run_checks(credentials=None):
    """Compatibility with the encrypted runner; injected credentials are ignored."""
    return inventory()
