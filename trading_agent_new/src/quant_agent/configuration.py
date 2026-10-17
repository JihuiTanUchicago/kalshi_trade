"""Load only named credentials from a local file, without evaluation."""
from pathlib import Path
import os
import re
import shlex

from .common import GateError


def load_environment(path: str | Path, names: list[str]) -> bool:
    if not names or any(
        not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", name)
        for name in names
    ) or len(set(names)) != len(names):
        raise GateError("Configure valid, distinct credential environment-variable names")
    source = Path(path)
    if not source.is_file() or source.stat().st_size > 32_000:
        raise GateError("Credential file is missing or exceeds the declared size limit")
    matches = {name: [] for name in names}
    for line in source.read_text().splitlines():
        key, separator, value = line.strip().partition("=")
        name = key.strip().removeprefix("export ").strip()
        if separator and name in matches:
            try:
                pieces = shlex.split(value, comments=True, posix=True)
            except ValueError:
                raise GateError("Invalid quoted credential; its value is omitted") from None
            if len(pieces) > 1:
                raise GateError("Quote a credential containing spaces; its value is omitted")
            matches[name].append(pieces[0] if pieces else "")
    if any(len(values) != 1 for values in matches.values()):
        raise GateError("Credential file must contain each configured field exactly once")
    # Literal parse: no expansion, subprocess, eval, or unrelated environment keys.
    values = {name: entries[0] for name, entries in matches.items()}
    os.environ.update(values)
    return all(values.values())


def load_model_environment(path: str | Path, config: dict) -> bool:
    return load_environment(path, [config.get("api_key_env", "")])
