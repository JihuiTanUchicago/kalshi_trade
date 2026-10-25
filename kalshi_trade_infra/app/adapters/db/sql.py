"""Helpers every repository module shares. Datetimes are stored as naive UTC."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


@contextmanager
def transaction(conn) -> Iterator[Any]:
    """BEGIN..COMMIT on an autocommit connection; ROLLBACK on any error."""
    conn.begin()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _json(value) -> Optional[str]:
    return None if value is None else json.dumps(value, separators=(",", ":"))


def _loads(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)
