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

from app import agent, engine
from app import repository as repo
from data_pipeline.common import get_db_conn

CONCURRENCY = int(os.getenv("APP_AGENT_CONCURRENCY", "4"))
IDLE_SECONDS = 2.0
# Longer than the worst single model call (4 retries x 180s, plus one repair).
ABANDONED_AFTER = timedelta(minutes=20)


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


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "agents":
        base = "%s:%d" % (socket.gethostname(), os.getpid())
        threads = [threading.Thread(target=agent_loop, args=("%s:%d" % (base, i),), daemon=True) for i in range(CONCURRENCY)]
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
