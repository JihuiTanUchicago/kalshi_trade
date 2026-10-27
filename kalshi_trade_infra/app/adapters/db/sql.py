"""Helpers every repository module shares. Datetimes are stored as naive UTC.

Split modules bind ``now_utc`` from here at import time, so ``monkeypatch.setattr(repo,
"now_utc", ...)`` does NOT reach a moved function (tests/test_repository_split.py refuses a test
that does this and calls one directly). To freeze time in a test, patch ``now_utc`` on the module that defines the function
under test, e.g. ``app.adapters.db.order_intent_repository``."""
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


def contract_fills_sql(col: str = "") -> str:
    """SQL for one closed position row's contracts times taker fills (trading_core.domain.slippage.
    contract_fills): its entry fill and its exit fill, or the entry alone when it was held to settlement
    (close_reason 'settled', which the engine's settle_due writes; settlement is not a fill). `col` is the
    table alias with its dot ("p."). The caller keeps it to closed rows. Display only: the paper
    after-slippage estimate reads it, no gate does."""
    return "%sqty * (CASE WHEN %sclose_reason='settled' THEN 1 ELSE 2 END)" % (col, col)
