"""Small, deterministic primitives shared by protected host components."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import math


class AgentError(Exception):
    """An actionable, user-facing failure without secret-bearing provider logs."""


class GateError(AgentError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise GateError(f"Invalid timestamp: {value!r}") from exc
    if result.tzinfo is None:
        raise GateError("Availability timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise GateError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GateError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise GateError(f"{name} must be finite")
    return result


def integer(value: Any, name: str, minimum: int = 0) -> int:
    result = finite(value, name)
    if result != int(result) or result < minimum:
        raise GateError(f"{name} must be an integer >= {minimum}")
    return int(result)


def pointer(document: Any, path: str) -> Any:
    if path == "":
        return document
    if not path.startswith("/"):
        raise GateError("Evidence paths must be JSON pointers")
    result = document
    try:
        for part in path[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            result = result[int(part)] if isinstance(result, list) else result[part]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise GateError(f"Evidence path does not exist: {path}") from exc
    return result
