"""Background processes for the customer app.

    python -m app.worker agents   # research + chat + review runs (APP_AGENT_CONCURRENCY threads)
    python -m app.worker engine   # deployed strategies, every market

Both scale out by running more copies: agent runs are claimed with
SKIP LOCKED and engine decisions with a per-slot claim.
"""
from __future__ import annotations

import os
import signal
import socket
import sys
import threading
import time
from datetime import timedelta

from app import agent, billing, engine
from app import repository as repo
from data_pipeline.common import get_db_conn

CONCURRENCY = int(os.getenv("APP_AGENT_CONCURRENCY", "4"))
# Extra threads that take only chats and reviews. Research runs last an hour or more, so with every
# CONCURRENCY thread on research a user's chat (and the autopilot review) used to wait for one to end.
INTERACTIVE_LANES = max(0, int(os.getenv("APP_AGENT_INTERACTIVE_LANES", "1")))
IDLE_SECONDS = 2.0
# A frozen run is reaped this long after its LAST heartbeat. A HEALTHY run now beats continuously:
# every event bumps the heartbeat, a wrapped data-load beats every ~5s, the streaming proposer beats
# on every token flush, and a per-run background beater (agent._heartbeat_pump) refreshes it every
# ~15s through any legitimately long silent phase (a big backtest, one model call). So a run that
# goes silent for minutes is genuinely stuck, and 20 min was far too slow to notice. Tight + env-
# tunable; paired with agent.RUN_STALL_SECONDS (how long the beater tolerates a silent main thread),
# total time-to-kill a wedged run ≈ RUN_STALL_SECONDS + ABANDONED_AFTER (~6.5 min by default).
# 240s, not 90: on 2026-10-24/25 a swap-thrashing box stalled the whole process for 90s+ and the
# reaper stopped ten LIVE runs (each beat again after its finished_at). Deploys yield on SIGTERM, so
# the window only delays recovery from a real crash.
ABANDONED_AFTER = timedelta(seconds=int(os.getenv("TAU_RUN_ABANDONED_SECONDS", "240")))
# Autopilot heartbeat: how often each autopilot-on user gets a scheduled 'review' run (the only thing
# that makes the co-pilot act on its own; without it the agent runs only when the user chats).
COPILOT_REVIEW_SECONDS = int(os.getenv("APP_COPILOT_REVIEW_SECONDS", "600"))
# Minimum spacing between auto-enqueued reviews per user. The event hook (research-completion ->
# review) makes the loop continuous; this floor keeps it PACED, not a runaway: a research run that
# fails in 2s can't spin a tight research->review->research storm burning API/credits, because a
# review created within this window blocks the next auto-enqueue. Only binds when runs fail fast —
# a real Opus review takes longer than this, so an active user is never throttled by it.
MIN_REVIEW_SECONDS = int(os.getenv("APP_AUTOPILOT_MIN_REVIEW_SECONDS", "90"))


# Runs this process is executing, by worker id, so a clean stop can hand research runs back.
_HELD: dict = {}
_STOPPING = threading.Event()


def _yield_on_sigterm(signum, frame) -> None:
    """Deploys restart this worker several times a day. Without this, each restart left research
    runs to the 90s reaper, which spends one of MAX_RESUMES (3) per restart, so a run restarted
    four times was stopped for good. Stop claiming, re-queue held research runs at full resume
    budget (their checkpoint already holds the work), then exit. Reviews and chats are left to the
    reaper: re-running one could repeat actions it already took. A SIGKILL (OOM) skips all this and
    still counts as a crash."""
    _STOPPING.set()
    try:
        conn = get_db_conn()
        try:
            cur = conn.cursor()
            for wid, run in list(_HELD.items()):
                if run.get("kind") == "research" and repo.yield_run(cur, run["id"], wid):
                    print("[agents] yielded research run %s on shutdown" % run["id"], flush=True)
        finally:
            conn.close()
    except Exception as e:
        print("[agents] shutdown yield ERROR %s" % e, flush=True)
    os._exit(0)


def agent_loop(worker_id: str, skip_research: bool = False) -> None:
    while True:
        try:
            conn = get_db_conn()
            try:
                while True:
                    if _STOPPING.is_set():
                        time.sleep(IDLE_SECONDS)  # shutting down: claim nothing new
                        continue
                    repo.fail_abandoned_runs(conn.cursor(), ABANDONED_AFTER)
                    run = repo.claim_run(conn, worker_id, skip_research=skip_research)
                    if run is None:
                        time.sleep(IDLE_SECONDS)
                        continue
                    print("[agents] %s took run %s (%s)" % (worker_id, run["id"], run["kind"]), flush=True)
                    _HELD[worker_id] = run
                    try:
                        if run["kind"] == "research":
                            agent.run_research(conn, run)
                            # Keystone of the continuous loop: the instant research ends (win OR fail),
                            # drive the co-pilot to act on the fresh results instead of waiting up to
                            # COPILOT_REVIEW_SECONDS. Bounded by the same gate the heartbeat uses.
                            enqueue_review_after_research(conn, run["user_id"])
                        else:
                            agent.run_copilot(conn, run)
                    finally:
                        _HELD.pop(worker_id, None)
            finally:
                conn.close()
        except Exception as e:
            print("[agents] %s ERROR %s" % (worker_id, e), flush=True)
            time.sleep(5)


def autopilot_review_ok(cur, uid: int) -> bool:
    """The single gate for every autonomous 'review' enqueue — heartbeat AND research-completion
    event hook — so dedup, pacing and the billing bound are enforced identically on both paths.
    (Does NOT check the autopilot toggle: the scheduler pre-filters via autopilot_user_ids and the
    event hook checks autopilot_on, so each caller only reaches here for an autopilot-on user.)"""
    # Dedup: at most one review/chat in flight per user — never stack reviews. (Also absorbs the
    # rare double-check if more than one agents process runs the scheduler.)
    if repo.count_runs(cur, uid, "review", active_only=True) or repo.count_runs(cur, uid, "chat", active_only=True):
        return False
    # Pace: a review created within the floor means we just acted — don't re-spin the loop.
    if MIN_REVIEW_SECONDS > 0 and repo.count_runs(
        cur, uid, "review", since=repo.now_utc() - timedelta(seconds=MIN_REVIEW_SECONDS)
    ):
        return False
    # Money guard: an autonomous review bills Opus to this user. If they have no card / no credits,
    # skip them — otherwise we'd run up an uncollectable negative balance. Manual paths already gate
    # via _require_billing_ready; this is the same bar for the paths that have no request to 402.
    if not billing.is_ready(cur, uid):
        return False
    return True


# A heartbeat review with nothing to act on: every research slot is busy and nothing is running, so
# the review can only re-propose research the cap refuses. Space those out; research completion
# still enqueues a review at once (enqueue_review_after_research), so no result waits on this.
IDLE_REVIEW_SECONDS = int(os.getenv("APP_IDLE_REVIEW_SECONDS", "1800"))


def _idle_review_skip(cur, uid: int) -> bool:
    if IDLE_REVIEW_SECONDS <= COPILOT_REVIEW_SECONDS:
        return False
    if repo.count_runs(cur, uid, "research", active_only=True) < agent.MAX_ACTIVE_RESEARCH:
        return False
    if any(d["status"] == "running" for d in repo.list_deployments(cur, uid)):
        return False
    return bool(repo.count_runs(cur, uid, "review", since=repo.now_utc() - timedelta(seconds=IDLE_REVIEW_SECONDS)))


# The heartbeat is the fallback: a review an event already ran (research finished, a force-close)
# within this window covers it. Two reviews three minutes apart said the same thing twice and
# billed twice (2026-10-24: a force-close review at 19:57, the heartbeat at 20:00).
HEARTBEAT_RECENT_SECONDS = int(os.getenv("APP_HEARTBEAT_RECENT_SECONDS", str(COPILOT_REVIEW_SECONDS // 2)))


def _recent_review(cur, uid: int) -> bool:
    return HEARTBEAT_RECENT_SECONDS > 0 and bool(repo.count_runs(
        cur, uid, "review", since=repo.now_utc() - timedelta(seconds=HEARTBEAT_RECENT_SECONDS)))


def due_autopilot_users(cur) -> list:
    """Autopilot-on users who may be enqueued a scheduled heartbeat review right now."""
    return [uid for uid in repo.autopilot_user_ids(cur)
            if autopilot_review_ok(cur, uid) and not _recent_review(cur, uid) and not _idle_review_skip(cur, uid)]


def enqueue_review_after_research(conn, user_id: int) -> None:
    """Event hook: a research run just ended, so act on the fresh results NOW. Review launches
    research, research completion enqueues the next review -> a self-sustaining loop while there's
    work to do, paced by autopilot_review_ok so it stays continuous without ever becoming a runaway.
    Own transaction: the research result is already committed, so a failed enqueue only rolls back
    the enqueue, and a crash here just reconnects on the next loop (no double-enqueue, no wedge)."""
    try:
        with repo.transaction(conn) as cur:
            if repo.autopilot_on(cur, user_id) and autopilot_review_ok(cur, user_id):
                repo.create_run(cur, user_id, "review", prompt="autopilot: research completed, act on results")
                print("[agents] research-completion review enqueued for user %s" % user_id, flush=True)
    except Exception as e:
        # Never let a hook failure kill the worker loop or lose the committed research result.
        print("[agents] research-completion hook ERROR for user %s: %s" % (user_id, e), flush=True)


def autopilot_scheduler() -> None:
    """The autopilot heartbeat — now a FALLBACK floor, not the driver. The event hook
    (enqueue_review_after_research) keeps an active user moving continuously; this catches idle
    users and any missed event, enqueueing a 'review' for each due autopilot user every
    COPILOT_REVIEW_SECONDS. The clamps, loss budget, daily-loss kill switch and live gate in
    act()/agent still bound everything it does.
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
        threads += [threading.Thread(target=agent_loop, args=("%s:chat%d" % (base, i), True), daemon=True)
                    for i in range(INTERACTIVE_LANES)]
        threads.append(threading.Thread(target=autopilot_scheduler, daemon=True))  # the autopilot heartbeat
        signal.signal(signal.SIGTERM, _yield_on_sigterm)
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
