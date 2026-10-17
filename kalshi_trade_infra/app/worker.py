"""Background processes for the customer app.

    python -m app.worker agents   # research + chat + review runs (APP_AGENT_CONCURRENCY threads)
    python -m app.worker engine   # deployed strategies, every market

Both scale out by running more copies: agent runs are claimed with
SKIP LOCKED and engine decisions with a per-slot claim.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from datetime import timedelta

from app import agent, billing, engine
from app import repository as repo
from data_pipeline.common import get_db_conn

CONCURRENCY = int(os.getenv("APP_AGENT_CONCURRENCY", "4"))
IDLE_SECONDS = 2.0
# Longer than the worst single model call (4 retries x 180s, plus one repair).
ABANDONED_AFTER = timedelta(minutes=20)
# Autopilot heartbeat: how often each autopilot-on user gets a scheduled 'review' run (the only thing
# that makes the co-pilot act on its own; without it the agent runs only when the user chats).
COPILOT_REVIEW_SECONDS = int(os.getenv("APP_COPILOT_REVIEW_SECONDS", "600"))


def agent_loop(worker_id: str) -> None:
    while True:
        try:
            conn = get_db_conn()
            try:
                while True:
                    repo.fail_abandoned_runs(conn.cursor(), ABANDONED_AFTER)
                    run = repo.claim_run(conn, worker_id)
                    if run is None:
                        time.sleep(IDLE_SECONDS)
                        continue
                    print("[agents] %s took run %s (%s)" % (worker_id, run["id"], run["kind"]), flush=True)
                    if run["kind"] == "research":
                        agent.run_research(conn, run)
                    else:
                        agent.run_copilot(conn, run)
            finally:
                conn.close()
        except Exception as e:
            print("[agents] %s ERROR %s" % (worker_id, e), flush=True)
            time.sleep(5)


def due_autopilot_users(cur) -> list:
    """Autopilot-on users who have no co-pilot run already queued/running — each is due a scheduled
    review. Deduping on an in-flight review/chat keeps reviews from piling up (and absorbs the rare
    double-check if more than one agents process runs the scheduler)."""
    due = []
    for uid in repo.autopilot_user_ids(cur):
        if repo.count_runs(cur, uid, "review", active_only=True) or repo.count_runs(cur, uid, "chat", active_only=True):
            continue
        # Money guard: an autonomous review bills Opus to this user. If they have no card / no
        # credits, skip them — otherwise the heartbeat would run up an uncollectable negative
        # balance every COPILOT_REVIEW_SECONDS. Manual paths already gate via _require_billing_ready;
        # this is the same bar for the path that has no request to 402.
        if not billing.is_ready(cur, uid):
            continue
        due.append(uid)
    return due


def autopilot_scheduler() -> None:
    """The autopilot heartbeat: every COPILOT_REVIEW_SECONDS, enqueue a 'review' run for each due
    autopilot user. This is what makes the co-pilot act on its own — assess deployments, run research,
    promote/tune/flatten — instead of only when the user chats. The clamps, loss budget, daily-loss
    kill switch and live gate in act()/agent still bound everything it does.
    ponytail: single in-process scheduler; the due-check dedupe is the only cross-process guard."""
    time.sleep(15)  # let the worker threads claim first so a fresh boot doesn't double-enqueue
    while True:
        try:
            conn = get_db_conn()
            try:
                cur = conn.cursor()
                for uid in due_autopilot_users(cur):
                    repo.create_run(cur, uid, "review", prompt="scheduled autopilot review")
                    print("[agents] scheduled autopilot review for user %s" % uid, flush=True)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print("[agents] scheduler ERROR %s" % e, flush=True)
        time.sleep(COPILOT_REVIEW_SECONDS)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "agents":
        base = "%s:%d" % (socket.gethostname(), os.getpid())
        threads = [threading.Thread(target=agent_loop, args=("%s:%d" % (base, i),), daemon=True) for i in range(CONCURRENCY)]
        threads.append(threading.Thread(target=autopilot_scheduler, daemon=True))  # the autopilot heartbeat
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    elif mode == "engine":
        engine.run_forever()
    else:
        sys.exit("usage: python -m app.worker agents|engine")


if __name__ == "__main__":
    main()
