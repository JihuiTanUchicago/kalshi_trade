"""A kill switch you can flip in seconds, without a restart.

``APP_KILL_SWITCH=1`` halts every new BUY, but it is a process environment variable: flipping it
means editing an env file and restarting the engine, which is minutes in an incident. This adds a
second, DB-backed switch: one row in ``collector_state`` (key ``exec_kill_switch``) that every
order guard re-reads at most every ``CACHE_SECONDS``. Either switch being on halts new BUYS.
SELLS are never touched (see guard.py: an exit must always be able to get flat).

    python -m app.execution.kill_switch on --reason "bad fills on KXBTC15M"
    python -m app.execution.kill_switch off
    python -m app.execution.kill_switch status

A read error keeps the last value seen (default off before the first good read): the engine
cannot trade without the database anyway, and a DB blip must not silently UN-halt a halted
system, nor halt a healthy one.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from typing import Callable, Dict, Optional

STATE_KEY = "exec_kill_switch"
CACHE_SECONDS = float(os.getenv("APP_KILL_SWITCH_CACHE_SECONDS", "5"))


def read_state(cur) -> Dict:
    """The stored switch state, {} when never set."""
    cur.execute("SELECT state_value, updated_at_utc FROM collector_state WHERE state_key=%s", (STATE_KEY,))
    row = cur.fetchone()
    if not row:
        return {}
    try:
        val = json.loads(row["state_value"]) if isinstance(row["state_value"], str) else dict(row["state_value"] or {})
    except (TypeError, ValueError):
        val = {}
    val["updated_at_utc"] = row.get("updated_at_utc")
    return val


def write_state(cur, on: bool, reason: str = "", by: str = "") -> None:
    from app.repository import now_utc

    cur.execute(
        """INSERT INTO collector_state (state_key,state_value,updated_at_utc) VALUES (%s,%s,%s)
           ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)""",
        (STATE_KEY, json.dumps({"on": bool(on), "reason": reason, "by": by}), now_utc()),
    )


class DbKillSwitch:
    """Cached reader of the DB switch. ``connect`` returns a fresh DB connection (lazily, on the
    first read and after any error)."""

    def __init__(self, connect: Optional[Callable[[], object]] = None, cache_seconds: float = CACHE_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._connect = connect
        self._cache_seconds = float(cache_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._conn = None
        self._on = False
        self._read_at: Optional[float] = None

    def is_on(self) -> bool:
        with self._lock:
            now = self._clock()
            if self._read_at is not None and now - self._read_at < self._cache_seconds:
                return self._on
            self._read_at = now
            try:
                if self._conn is None:
                    self._conn = (self._connect or _default_connect)()
                with self._conn.cursor() as cur:
                    self._on = bool(read_state(cur).get("on"))
            except Exception as e:
                self._conn = None
                print("[kill-switch] read failed, keeping last value on=%s: %r" % (self._on, e), flush=True)
            return self._on


def _default_connect():
    """A connection with SHORT timeouts: this read sits on the BUY path of a single-threaded engine,
    so a hung database must cost a buy a couple of seconds, never stall exits for minutes (the
    shared get_db_conn allows 600s reads for long research queries)."""
    import pymysql

    from data_pipeline import common as c

    if not all([c.MYSQL_HOST, c.MYSQL_USER, c.MYSQL_PASSWORD, c.MYSQL_DATABASE]):
        raise RuntimeError("Missing MySQL env vars")
    return pymysql.connect(host=c.MYSQL_HOST, port=c.MYSQL_PORT, user=c.MYSQL_USER, password=c.MYSQL_PASSWORD,
                           database=c.MYSQL_DATABASE, autocommit=True, charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor, connect_timeout=2, read_timeout=2,
                           write_timeout=2)


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="DB-backed execution kill switch (halts new BUYS).")
    ap.add_argument("cmd", choices=("on", "off", "status"))
    ap.add_argument("--reason", default="")
    ap.add_argument("--by", default=os.getenv("USER", ""))
    args = ap.parse_args()
    conn = _default_connect()
    try:
        with conn.cursor() as cur:
            if args.cmd != "status":
                write_state(cur, args.cmd == "on", args.reason, args.by)
                conn.commit()
            print(json.dumps(read_state(cur), default=str))
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    main()
