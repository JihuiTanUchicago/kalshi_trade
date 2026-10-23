"""Bounded aggregate reads and the explicit short job-admission barrier only."""
from __future__ import annotations

import time


STATUSES = ("queued", "running", "paused")
TABLES = ("kalshi_perps_batches", "kalshi_perps_partition_sources", "app_kalshi_perps_settings", "app_kalshi_perps_orders")


class DatabaseError(RuntimeError):
    pass


def connect(env, factory=None, *, admission=False):
    if factory is None:
        import pymysql
        factory, cursorclass = pymysql.connect, pymysql.cursors.DictCursor
    else:
        cursorclass = object
    if not all(env.get(key) for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")):
        raise DatabaseError("database_configuration_missing")
    return factory(host=env["MYSQL_HOST"], port=int(env.get("MYSQL_PORT", "3306")), user=env["MYSQL_USER"],
                   password=env["MYSQL_PASSWORD"], database=env["MYSQL_DATABASE"], autocommit=True,
                   charset="utf8mb4", cursorclass=cursorclass, connect_timeout=3,
                   read_timeout=0.5 if admission else 4, write_timeout=0.5 if admission else 4)


def counts(conn):
    # No kind filter: chat/review/autopilot/research all prevent an idle release.
    with conn.cursor() as cur:
        cur.execute("SELECT status,COUNT(*) AS n FROM app_agent_runs WHERE status IN (%s,%s,%s) GROUP BY status", STATUSES)
        result = dict.fromkeys(STATUSES, 0)
        for row in cur.fetchall():
            if row["status"] not in result or type(row["n"]) is not int or row["n"] < 0:
                raise DatabaseError("invalid_job_aggregate")
            result[row["status"]] = row["n"]
        return result


def idle(value):
    return set(value) == set(STATUSES) and all(type(n) is int and n == 0 for n in value.values())


def inspect(conn):
    with conn.cursor() as cur:
        cur.execute("SET SESSION MAX_EXECUTION_TIME=3000")
        cur.execute("SET SESSION lock_wait_timeout=3")
    result = {"job_counts": counts(conn)}
    with conn.cursor() as cur:
        cur.execute("SELECT TABLE_NAME AS name FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() "
                    "AND TABLE_NAME IN (%s,%s,%s,%s)", TABLES)
        present = {row["name"] for row in cur.fetchall()}
        if not present.issubset(TABLES):
            raise DatabaseError("invalid_schema_projection")
        result["tables_present"] = {name: name in present for name in TABLES}
        cur.execute("SELECT CHARACTER_MAXIMUM_LENGTH AS width_n FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_proposals' AND COLUMN_NAME='kind'")
        row = cur.fetchone()
        result["proposal_kind_width"] = None if row is None else row["width_n"]
        for table, key, where in (("app_kalshi_perps_settings", "enabled_policy_count", " WHERE enabled=1"),
                                  ("app_kalshi_perps_orders", "native_order_count", "")):
            result[key] = None
            if table in present:
                cur.execute("SELECT COUNT(*) AS n FROM " + table + where)
                value = cur.fetchone()["n"]
                if type(value) is not int or value < 0:
                    raise DatabaseError("invalid_schema_projection")
                result[key] = value
    return result


def require_schema(projection):
    if (not all(projection["tables_present"].values()) or type(projection["proposal_kind_width"]) is not int
            or projection["proposal_kind_width"] < 32 or projection["enabled_policy_count"] != 0
            or projection["native_order_count"] != 0):
        raise DatabaseError("full_schema_not_converged")


class AdmissionLock:
    """No transaction/DDL/reconnect is allowed on this dedicated locked session."""

    def __init__(self, conn, *, seconds=120, clock=time.monotonic):
        self.conn, self.seconds, self.clock = conn, seconds, clock
        self.connection_id, self.deadline, self.held = None, None, False

    def acquire(self):
        self.conn.ping(reconnect=False)
        with self.conn.cursor() as cur:
            cur.execute("SET SESSION lock_wait_timeout=3")
            cur.execute("SET SESSION innodb_lock_wait_timeout=3")
            cur.execute("SET SESSION MAX_EXECUTION_TIME=3000")
            cur.execute("SET autocommit=0")
            cur.execute("SELECT CONNECTION_ID() AS id")
            self.connection_id = cur.fetchone()["id"]
            if type(self.connection_id) is not int or self.connection_id <= 0:
                raise DatabaseError("admission_connection_invalid")
            cur.execute("LOCK TABLES app_agent_runs WRITE, app_kalshi_perps_settings WRITE, app_kalshi_perps_orders WRITE")
            self.held = True
            self.deadline = self.clock() + self.seconds
        value = counts(self.conn)
        if not idle(value):
            self.release()
            return value
        with self.conn.cursor() as cur:
            for table in ("app_kalshi_perps_settings", "app_kalshi_perps_orders"):
                cur.execute("SELECT COUNT(*) AS n FROM " + table)
                row = cur.fetchone()
                if type(row["n"]) is not int or row["n"] != 0:
                    self.release()
                    raise DatabaseError("native_state_requires_review")
        self.check()
        return value

    def check(self):
        if not self.held or self.clock() >= self.deadline:
            raise DatabaseError("admission_deadline_or_lock_unavailable")
        # PyMySQL query execution never reconnects; the explicit initial ping
        # also forbids reconnect. Every later proof is one bounded round trip.
        with self.conn.cursor() as cur:
            cur.execute("SELECT CONNECTION_ID() AS id")
            if cur.fetchone()["id"] != self.connection_id:
                raise DatabaseError("admission_connection_changed")
        if self.clock() >= self.deadline:
            raise DatabaseError("admission_deadline_or_lock_unavailable")

    def release(self):
        try:
            if self.held:
                with self.conn.cursor() as cur:
                    cur.execute("UNLOCK TABLES")
        finally:
            self.held = False

    def close(self):
        try:
            self.release()
        finally:
            self.conn.close()
