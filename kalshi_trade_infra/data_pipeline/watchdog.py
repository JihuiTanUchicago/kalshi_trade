"""Heartbeat watchdog — recovers the *silent stall*.

systemd `Restart=always` only catches a process that EXITS. Our collectors and
engines can instead keep running while their inner loop wedges (stuck on a socket
read, a hung API call, a dead DB handle), so they stay "active" in systemd but
stop writing. That is the failure mode behind the recurring STALE alerts.

This watchdog reads each service's heartbeat age from `collector_state` and
`systemctl restart`s any service whose heartbeat is older than its threshold. A
per-service cooldown makes a restart-loop impossible: a service is restarted at
most once per COOLDOWN_S even if it comes back and stalls again immediately.

Config is per box via WATCHDOG_TARGETS — a JSON list of
`[state_key, service, max_age_seconds]`. Run from a systemd timer every ~60s as
root (so `systemctl restart` needs no sudo). Idempotent and side-effect-free when
everything is fresh.
"""
import json
import os
import subprocess
import time

from data_pipeline.common import get_db_conn

STATE_FILE = os.environ.get("WATCHDOG_STATE", "/opt/kalshi/.watchdog_state.json")
COOLDOWN_S = int(os.environ.get("WATCHDOG_COOLDOWN_S", "900"))  # >= 15 min between restarts of one service


def _heartbeat_ages(cur, keys):
    """state_key -> age in seconds (missing key omitted)."""
    placeholders = ",".join(["%s"] * len(keys))
    cur.execute(
        "SELECT state_key AS k, TIMESTAMPDIFF(SECOND, updated_at_utc, UTC_TIMESTAMP()) AS age "
        "FROM collector_state WHERE state_key IN (%s)" % placeholders,
        keys,
    )
    ages = {}
    for row in cur.fetchall():
        if isinstance(row, dict):
            ages[row["k"]] = row["age"]
        else:
            ages[row[0]] = row[1]
    return ages


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print("[watchdog] could not persist state: %s" % e)


def run_once(targets, now=None):
    """Check every target; restart the stale ones that aren't in cooldown.
    Returns the list of services restarted (for tests / logging)."""
    now = now if now is not None else time.time()
    last = _load_state()
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            ages = _heartbeat_ages(cur, [t[0] for t in targets])
    finally:
        conn.close()

    restarted = []
    for key, service, max_age in targets:
        age = ages.get(key)
        if age is not None and age <= max_age:
            continue  # fresh
        if now - float(last.get(service, 0)) < COOLDOWN_S:
            print("[watchdog] %s stale (%s=%ss) but within cooldown; leaving it" % (service, key, age))
            continue
        print("[watchdog] %s stale (%s=%ss > %ss) -> restart" % (service, key, age, max_age))
        subprocess.run(["systemctl", "restart", service], check=False)
        last[service] = now
        restarted.append(service)

    _save_state(last)
    return restarted


def main():
    targets = json.loads(os.environ.get("WATCHDOG_TARGETS", "[]"))
    if not targets:
        print("[watchdog] no WATCHDOG_TARGETS configured; nothing to do")
        return
    run_once(targets)


if __name__ == "__main__":
    main()
