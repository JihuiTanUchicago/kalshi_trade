"""Load only a configured model credential from a local file, without evaluation."""
from pathlib import Path
import os
import re
import shlex

from .common import GateError


def load_model_environment(path: str | Path, config: dict) -> bool:
    name = config.get("api_key_env", "")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", name):
        raise GateError("Model configuration needs a valid credential environment-variable name")
    source = Path(path)
    if not source.is_file() or source.stat().st_size > 32_000:
        raise GateError("Model credential file is missing or exceeds the declared size limit")
    matches = []
    for line in source.read_text().splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.strip().removeprefix("export ").strip() == name:
            try:
                pieces = shlex.split(value, comments=True, posix=True)
            except ValueError:
                raise GateError("Invalid quoted model credential; its value is omitted") from None
            if len(pieces) > 1:
                raise GateError("Quote a model credential containing spaces; its value is omitted")
            matches.append(pieces[0] if pieces else "")
    if len(matches) != 1:
        raise GateError("Model credential file must contain the configured field exactly once")
    # Literal parse: no expansion, subprocess, eval, or unrelated environment keys.
    os.environ[name] = matches[0]
    return bool(matches[0])
