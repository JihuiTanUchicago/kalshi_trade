"""Bounded aggregate-only SQL; no schema, job, setting, or application writes."""
from __future__ import annotations

import json
import os


TABLES = ("app_agent_runs", "kalshi_perps_batches", "kalshi_perps_partition_sources")
STATUSES = ("queued", "running", "paused")
COLUMN_TABLES = ("app_experiments", "app_fdr_state", "app_holdout_ledger", "app_data_partitions")


def inspect(cur) -> dict:
    cur.execute(
        "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (%s,%s,%s)", TABLES)
    present = {row["name"] for row in cur.fetchall()}
    if not present.issubset(TABLES):
        raise ValueError("UnexpectedTable")
    result = {"read_only_transaction": True,
              "tables_present": {name: name in present for name in TABLES},
              "research_counts": {status: 0 for status in STATUSES},
              "perps_row_counts": {}, "full_database_integration_verified": False}
    cur.execute(
        "SELECT TABLE_NAME AS name, COLUMN_TYPE AS column_type, IS_NULLABLE AS nullable, "
        "CHARACTER_MAXIMUM_LENGTH AS max_length, COLLATION_NAME AS collation "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME IN (%s,%s,%s,%s) AND COLUMN_NAME=%s",
        (*COLUMN_TABLES, "market"))
    result["market_column_signatures"] = {name: None for name in COLUMN_TABLES}
    for row in cur.fetchall():
        if row["name"] not in COLUMN_TABLES:
            raise ValueError("UnexpectedColumn")
        result["market_column_signatures"][row["name"]] = {
            "column_type": row["column_type"], "nullable": row["nullable"] == "YES",
            "max_length": row["max_length"], "collation": row["collation"]}
    if "app_agent_runs" in present:
        cur.execute(
            "SELECT status, COUNT(*) AS n FROM app_agent_runs "
            "WHERE kind=%s AND status IN (%s,%s,%s) GROUP BY status",
            ("research", *STATUSES))
        for row in cur.fetchall():
            if row["status"] not in STATUSES or type(row["n"]) is not int or row["n"] < 0:
                raise ValueError("UnexpectedAggregate")
            result["research_counts"][row["status"]] = row["n"]
    for name in TABLES[1:]:
        if name in present:
            # Identifiers come only from this fixed tuple, never input or DB rows.
            cur.execute("SELECT COUNT(*) AS n FROM " + name)
            n = cur.fetchone()["n"]
            if type(n) is not int or n < 0:
                raise ValueError("UnexpectedAggregate")
            result["perps_row_counts"][name] = n
    return result


def run(env=None, connect=None) -> dict:
    env = os.environ if env is None else env
    if connect is None:
        import pymysql
        connect = pymysql.connect
        cursorclass = pymysql.cursors.DictCursor
    else:
        cursorclass = object
    required = ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD")
    if not all(env.get(name) for name in required):
        return {"status": "unavailable", "error_code": "missing_database_configuration"}
    connection = None
    try:
        connection = connect(host=env["MYSQL_HOST"], port=int(env.get("MYSQL_PORT", "3306")),
                             user=env["MYSQL_USER"], password=env["MYSQL_PASSWORD"],
                             database=env.get("MYSQL_DATABASE", "kalshi_trade"),
                             autocommit=True, charset="utf8mb4", cursorclass=cursorclass,
                             connect_timeout=5, read_timeout=8, write_timeout=8)
        with connection.cursor() as cur:
            # These affect only this short-lived diagnostic session.
            cur.execute("SET SESSION MAX_EXECUTION_TIME=3000")
            cur.execute("SET SESSION lock_wait_timeout=3")
            cur.execute("START TRANSACTION READ ONLY")
            result = inspect(cur)
        result["status"] = "checked"
        return result
    except Exception:
        return {"status": "unavailable", "error_code": "database_read_failed"}
    finally:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True))
    except Exception:
        print(json.dumps({"status": "unavailable", "error_code": "database_read_failed"}))
