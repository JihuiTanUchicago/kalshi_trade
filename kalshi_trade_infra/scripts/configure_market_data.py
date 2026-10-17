"""Validate market-data settings and optionally install a separate private env file.

No provider requests, shell evaluation, service restart or deployment is performed.
Effective defaults are overlaid by recognized process variables, then by file
assignments (including blanks). Only literal, single-line assignments are accepted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile
from typing import Mapping

ENV_KEYS = (
    "TAU_MARKET_DATA_PRIMARY", "TAU_DATABENTO_DEFAULT_DATASET",
    "TAU_DATABENTO_ENABLED", "DATABENTO_API_KEY", "TAU_DATABENTO_DATASETS",
    "TAU_DATABENTO_MAX_COST_USD", "TAU_ALPACA_ENABLED", "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY", "TAU_ALPACA_FEED", "TAU_ALPACA_SYMBOLS",
    "ALPACA_DATA_ENDPOINT", "TAU_MASSIVE_ENABLED", "MASSIVE_API_KEY",
    "TAU_MASSIVE_FX_FEED", "TAU_MASSIVE_FX_SYMBOLS", "TAU_MASSIVE_DATASETS",
)
ASSIGNMENT = re.compile(r"(?:export[ \t]+)?([A-Z_][A-Z0-9_]*)=(.*)")
MAX_FILE_BYTES = 64 * 1024


class ConfigurationFileError(ValueError):
    """A safe operator-facing error that never contains a setting's value."""


def _configuration_module():
    # Direct script execution starts with scripts/ on sys.path, not the product root.
    product_root = str(Path(__file__).resolve().parents[1])
    if product_root not in sys.path:
        sys.path.insert(0, product_root)
    from app import market_data_config

    return market_data_config


def _check_value(value: str) -> None:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ConfigurationFileError("Settings must be single-line printable literals.")
    if "$" in value or "`" in value:
        raise ConfigurationFileError("Shell expansion and command substitution are not accepted.")


def parse_assignments(contents: str) -> dict[str, str]:
    """Parse literal KEY=VALUE or export KEY=VALUE; reject ambiguous assignments."""
    result = {}
    for line_number, line in enumerate(contents.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT.fullmatch(line)
        if match is None or match[1] not in ENV_KEYS:
            raise ConfigurationFileError(f"Unsupported assignment at line {line_number}.")
        key, raw_value = match.groups()
        if key in result:
            raise ConfigurationFileError(f"Duplicate assignment at line {line_number}.")
        try:
            lexer = shlex.shlex(raw_value, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            raise ConfigurationFileError(f"Invalid single-line quoting at line {line_number}.") from None
        if len(tokens) > 1 or (tokens and tokens[0] and all(char in ";&|<>" for char in tokens[0])):
            raise ConfigurationFileError(f"Expected one literal value at line {line_number}.")
        value = tokens[0] if tokens else ""
        _check_value(value)
        result[key] = value
    return result


def _private_regular_file(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode) and not (info.st_mode & 0o077)


def read_private_file(path: Path) -> dict[str, str]:
    """Open without following the final symlink, then validate the open file."""
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        if not _private_regular_file(os.fstat(descriptor)):
            raise ConfigurationFileError("Input must be a private regular file without group/other permissions.")
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            contents = stream.read(MAX_FILE_BYTES + 1)
        if len(contents.encode("utf-8")) > MAX_FILE_BYTES:
            raise ConfigurationFileError("Configuration file exceeds the supported size.")
        return parse_assignments(contents)
    except (OSError, UnicodeError):
        raise ConfigurationFileError("Cannot safely read the private configuration file.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def configuration_environment(env: Mapping[str, str], path: Path | None = None) -> dict[str, str]:
    """A supplied file overrides recognized process values, including empty strings."""
    result = dict(_configuration_module().ENV_DEFAULTS)
    result.update({key: env[key] for key in ENV_KEYS if key in env})
    if path is not None:
        result.update(read_private_file(path))
    for value in result.values():
        _check_value(value)
    return result


def _check_output(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not _private_regular_file(info):
        raise ConfigurationFileError("Existing output must be a private regular file, never a symlink.")
    return info


def install_environment(path: Path, env: Mapping[str, str], input_path: Path | None = None) -> None:
    """Atomically replace a private target; never source the generated shell file."""
    temp_path = None
    try:
        if path.name in {".env", ".env.app", ".env.aws"}:
            raise ConfigurationFileError("Output must be a separate market-data overlay, not a base environment file.")
        parent_info = path.parent.lstat()
        if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_mode & 0o022:
            raise ConfigurationFileError("Output directory must be a real directory without group/other write permission.")
        before = _check_output(path)
        if input_path is not None and before is not None and os.path.samestat(input_path.stat(), before):
            raise ConfigurationFileError("Output must be separate from the input file.")
        descriptor, temporary = tempfile.mkstemp(prefix=".market-data-", dir=path.parent)
        temp_path = Path(temporary)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write("# Installed by configure_market_data.py; private market-data settings only.\n")
            for key in ENV_KEYS:
                stream.write(f"export {key}={shlex.quote(env[key])}\n")
            stream.flush()
            os.fsync(stream.fileno())
        current = _check_output(path)
        if (before is None) != (current is None) or (before is not None and not os.path.samestat(before, current)):
            raise ConfigurationFileError("Output changed during installation; retry after checking the target.")
        os.replace(temp_path, path)
        temp_path = None
    except OSError:
        raise ConfigurationFileError("Cannot safely install the private configuration file.") from None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _invalid_report(message: str) -> dict:
    return {"ready": False, "status": "invalid", "applied": False,
            "errors": [{"field": "configuration_file", "code": "invalid_configuration", "message": message}],
            "provider_validation": "not_performed", "network_requests": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Private literal settings; overrides process variables, including blanks.")
    parser.add_argument("--output", type=Path, help="Separate protected env target; only written with --apply.")
    parser.add_argument("--apply", action="store_true", help="Install a ready configuration. Never restarts services.")
    args = parser.parse_args(argv)
    try:
        if args.apply and args.output is None:
            raise ConfigurationFileError("--apply requires an explicit --output path.")
        env = configuration_environment(os.environ, args.env_file)
        report = _configuration_module().check_configuration(env)
        report["applied"] = False
        if args.apply and report["ready"]:
            install_environment(args.output, env, args.env_file)
            report["applied"] = True
    except ConfigurationFileError as exc:
        report = _invalid_report(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
