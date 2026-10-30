"""The agent-run queue (app_agent_runs + app_agent_events): create, claim, heartbeat, checkpoint,
reap, finish and list the research/chat/review sessions the workers execute."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.adapters.db.sql import _json, _loads, now_utc, transaction
from app.adapters.db.strategy_repository import DEMO_DIRECTION

# How many times a broken research run may be reclaimed + resumed from its checkpoint before it
# fails for good. Caps a run that keeps wedging at the same spot (a hanging data load) so it can't
# loop forever re-spending the user's model budget. Env-tunable.
MAX_RESUMES = int(os.getenv("TAU_RUN_MAX_RESUMES", "3"))

RUN_ACTIVE = ("queued", "running")


def create_run(
    cur, user_id: int, kind: str, market: Optional[str] = None, direction: Optional[str] = None,
    prompt: Optional[str] = None, deployment_id: Optional[int] = None,
    max_hypotheses: Optional[int] = None, run_forever: bool = False, model: Optional[str] = None,
    seed_strategy_id: Optional[int] = None, brief: bool = False,
) -> int:
    cur.execute(
        """INSERT INTO app_agent_runs (user_id, kind, market, direction, prompt, deployment_id, status,
             max_hypotheses, run_forever, model, seed_strategy_id, brief, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s,%s,%s)""",
        (user_id, kind, market, direction, prompt, deployment_id, max_hypotheses, 1 if run_forever else 0,
         model, seed_strategy_id, 1 if brief else 0, now_utc()),
    )
    return cur.lastrowid


def set_run_market(cur, run_id: int, market: str) -> None:
    """Record the market the agent chose for a run that was created without one."""
    cur.execute("UPDATE app_agent_runs SET market=%s WHERE id=%s", (market, run_id))


def update_run_progress(cur, run_id: int, tried: int, passed: int) -> None:
    """Keep hypotheses_tried/strategies_passed current as a run_forever session runs, so the
    counts are right even for a run that's still going or gets cancelled (finish_run only fires
    on a clean end, and only while status='running')."""
    cur.execute(
        "UPDATE app_agent_runs SET hypotheses_tried=%s, strategies_passed=%s WHERE id=%s",
        (tried, passed, run_id),
    )


def save_checkpoint(cur, run_id: int, checkpoint: Dict[str, Any]) -> None:
    """Persist a research run's exploration progress so a reclaim resumes from here instead of
    re-spending the model credits already explored. One compact JSON blob per run (overwritten);
    the event log already holds the gated hypotheses/verdicts, so this carries only what ISN'T
    recoverable from events: the in-progress (not-yet-gated) developed theses + the round/chunk
    cursor + the resolved market/lookback."""
    cur.execute("UPDATE app_agent_runs SET checkpoint_json=%s WHERE id=%s", (_json(checkpoint), run_id))


def load_checkpoint(cur, run_id: int) -> Optional[Dict[str, Any]]:
    """The saved checkpoint for a run, or None if it never checkpointed (a fresh, never-resumed run)."""
    cur.execute("SELECT checkpoint_json FROM app_agent_runs WHERE id=%s", (run_id,))
    row = cur.fetchone()
    return _loads(row["checkpoint_json"]) if row and row["checkpoint_json"] is not None else None


def count_runs(cur, user_id: int, kind: str, since: Optional[datetime] = None, active_only: bool = False) -> int:
    sql = "SELECT COUNT(*) AS n FROM app_agent_runs WHERE user_id=%s AND kind=%s"
    params: List[Any] = [user_id, kind]
    if active_only:
        sql += " AND status IN ('queued','running','paused')"  # a paused run still holds a worker slot
    if since is not None:
        sql += " AND created_at >= %s"
        params.append(since)
    cur.execute(sql, params)
    return int(cur.fetchone()["n"])


def count_active_research(cur) -> int:
    """GLOBAL count (all users) of research runs that hold or await a worker slot — for autopilot
    backpressure: when the shared queue is already saturated, don't launch more. Uses the
    idx_runs_status(status, created_at) index on the bounded status set."""
    cur.execute("SELECT COUNT(*) AS n FROM app_agent_runs "
                "WHERE kind='research' AND status IN ('queued','running','paused')")
    return int(cur.fetchone()["n"])


def claim_run(conn, worker_id: str, skip_research: bool = False) -> Optional[Dict]:
    """Take the oldest queued run. SKIP LOCKED lets any number of workers
    share the queue without two of them taking the same run. `skip_research` is the
    interactive lane: it takes only chats and reviews."""
    with transaction(conn) as cur:
        cur.execute(
            "SELECT * FROM app_agent_runs WHERE status='queued'%s ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
            % (" AND kind <> 'research'" if skip_research else "")
        )
        run = cur.fetchone()
        if not run:
            return None
        now = now_utc()
        cur.execute(
            "UPDATE app_agent_runs SET status='running', worker_id=%s, started_at=%s, heartbeat_at=%s WHERE id=%s",
            (worker_id, now, now, run["id"]),
        )
        run.update(status="running", worker_id=worker_id, started_at=now)
        return run


def _has_progress(checkpoint: Optional[Dict[str, Any]]) -> bool:
    """Real exploration worth resuming: a chunk already gated, or developed theses in hand."""
    return bool(checkpoint) and bool(
        checkpoint.get("chunks_done") or checkpoint.get("tried") or checkpoint.get("chunk"))


def fail_abandoned_runs(cur, stale_after: timedelta, max_resumes: int = MAX_RESUMES) -> int:
    """A run whose worker stopped heart-beating (crash, deploy restart, a frozen step the watchdog
    reaps) is RECLAIMED, not discarded, when it's a research run that made real progress and still
    has resume budget: re-queued so a worker picks it up and resumes from its checkpoint (the
    model credits already spent exploring aren't thrown away). A run with no checkpointed progress,
    or one that has exhausted its resume budget (keeps wedging at the same spot), still FAILS with a
    clear reason. Returns how many runs were reaped (re-queued or failed).

    Leak-safe: re-queuing only flips status/worker/resume_count — it never touches the gatekeeper
    ledger. The checkpoint's gate cursor (written atomically with each chunk's judging) is what makes
    the resume itself honest; this function just routes a reaped run to that path or to failure."""
    stale_cut = now_utc() - stale_after
    cur.execute(
        "SELECT id, kind, resume_count, checkpoint_json FROM app_agent_runs "
        "WHERE status='running' AND heartbeat_at < %s",
        (stale_cut,),
    )
    reaped = 0
    for r in cur.fetchall():
        ck = _loads(r["checkpoint_json"])
        progressed = r["kind"] == "research" and _has_progress(ck)
        # A research run killed before its first checkpoint (most often the whole worker process
        # dying under it) restarts from the top on the same budget: there is nothing to lose, and
        # stopping it left the user a dead card for a crash that wasn't theirs. Reviews and chats
        # still stop, since re-running one could repeat actions it already took.
        if r["kind"] == "research" and int(r["resume_count"]) < max_resumes:
            cur.execute(
                """UPDATE app_agent_runs SET status='queued', worker_id=NULL,
                     resume_count=resume_count+1, heartbeat_at=%s
                   WHERE id=%s AND status='running' AND heartbeat_at < %s""",
                (now_utc(), r["id"], stale_cut),
            )
            if cur.rowcount:
                add_event(cur, r["id"], "step",
                          ("Session interrupted — reclaiming it to resume from the last checkpoint "
                           if progressed else "Session interrupted before its first checkpoint — restarting it ")
                          + "(attempt %d of %d)." % (int(r["resume_count"]) + 1, max_resumes))
                reaped += 1
        else:
            # Being interrupted/abandoned is NOT a failure — it's a STOPPED run that reports how far it
            # got. Only a genuine external/infra error (caught in run_research) is `failed`. The card
            # shows "Explored N hypotheses" in neutral, not a red FAILED. Carry the explored/passed
            # counts off the checkpoint so that readout is accurate even though finish_run never ran.
            # explored = developed + dropped, as run_research reports it (most theses are dropped)
            tried_n = len(ck.get("tried") or []) + int(ck.get("dropped_n") or 0) if ck else 0
            passed_n = int(ck.get("total_passed") or 0) if ck else 0
            msg = ("Explored %d hypothes%s, then the session was interrupted and stopped — start a new "
                   "one to keep going." % (tried_n, "is" if tried_n == 1 else "es")) if tried_n \
                else "The session was interrupted before it explored a hypothesis — start a new one."
            cur.execute(
                """UPDATE app_agent_runs SET status='stopped', error=%s, hypotheses_tried=%s,
                     strategies_passed=%s, finished_at=%s
                   WHERE id=%s AND status='running' AND heartbeat_at < %s""",
                (msg, tried_n, passed_n, now_utc(), r["id"], stale_cut),
            )
            reaped += cur.rowcount
    return reaped


def yield_run(cur, run_id: int, worker_id: str) -> bool:
    """Hand a running run back to the queue on a CLEAN worker stop (a deploy's SIGTERM), without
    spending its resume budget: a restart is not a wedge, so it must not count toward the
    MAX_RESUMES that fail_abandoned_runs enforces for crashes. Only the run this worker holds."""
    cur.execute("UPDATE app_agent_runs SET status='queued', worker_id=NULL, heartbeat_at=%s "
                "WHERE id=%s AND status='running' AND worker_id=%s", (now_utc(), run_id, worker_id))
    if cur.rowcount:
        add_event(cur, run_id, "step", "Paused for a server update; resuming from the last checkpoint.")
    return bool(cur.rowcount)


def heartbeat(cur, run_id: int) -> Optional[str]:
    """Touch the run and return its status (so a cancel is noticed)."""
    cur.execute("UPDATE app_agent_runs SET heartbeat_at=%s WHERE id=%s", (now_utc(), run_id))
    cur.execute("SELECT status FROM app_agent_runs WHERE id=%s", (run_id,))
    row = cur.fetchone()
    return row["status"] if row else None


def run_worker(cur, run_id: int) -> Optional[str]:
    """The worker that currently owns a run (None once it's re-queued or finished by the reaper)."""
    cur.execute("SELECT worker_id FROM app_agent_runs WHERE id=%s", (run_id,))
    row = cur.fetchone()
    return row["worker_id"] if row else None


def finish_run(
    cur, run_id: int, status: str, error: Optional[str] = None, tried: int = 0, passed: int = 0,
    input_tokens: int = 0, output_tokens: int = 0,
) -> None:
    cur.execute(
        """UPDATE app_agent_runs SET status=%s, error=%s, hypotheses_tried=%s, strategies_passed=%s,
             input_tokens=%s, output_tokens=%s, finished_at=%s
           WHERE id=%s AND status='running'""",
        (status, error, tried, passed, input_tokens, output_tokens, now_utc(), run_id),
    )


def cancel_run(cur, user_id: int, run_id: int) -> bool:
    cur.execute(
        """UPDATE app_agent_runs SET status='cancelled', finished_at=%s
           WHERE id=%s AND user_id=%s AND status IN ('queued','running','paused')""",
        (now_utc(), run_id, user_id),
    )
    return cur.rowcount == 1


def pause_run(cur, user_id: int, run_id: int) -> bool:
    """Interrupt a running session: the worker holds its exact in-memory state at the next
    checkpoint until it's resumed (or cancelled). Only a currently-running run can be paused."""
    cur.execute(
        "UPDATE app_agent_runs SET status='paused' WHERE id=%s AND user_id=%s AND status='running'",
        (run_id, user_id),
    )
    return cur.rowcount == 1


def resume_run(cur, user_id: int, run_id: int) -> bool:
    """Continue a paused session right where it left off. Reset the heartbeat so the resumed run
    is never mistaken for abandoned in the gap before its next checkpoint."""
    cur.execute(
        "UPDATE app_agent_runs SET status='running', heartbeat_at=%s WHERE id=%s AND user_id=%s AND status='paused'",
        (now_utc(), run_id, user_id),
    )
    return cur.rowcount == 1


def add_event(cur, run_id: int, kind: str, message: str, data: Optional[Dict] = None) -> None:
    now = now_utc()
    cur.execute(
        "INSERT INTO app_agent_events (run_id, kind, message, data_json, created_at) VALUES (%s,%s,%s,%s,%s)",
        (run_id, kind, message, _json(data), now),
    )
    # An event IS proof of life: bump the run's heartbeat on every one so a run that emits phase
    # events (or streams thinking tokens) during a long, step-less phase never looks abandoned to
    # the watchdog. Scoped by run_id; a no-op row for a finished run. This is why observability
    # events double as the liveness signal — the laziest root fix for "heartbeat only advances
    # between steps". ponytail: one extra UPDATE per event, negligible beside the backtests.
    cur.execute("UPDATE app_agent_runs SET heartbeat_at=%s WHERE id=%s AND status='running'", (now, run_id))


# The start of the step agent.run_research logs when a run-until-stopped session runs out of credits,
# just before it finishes the run `succeeded` (tests/test_run_stop.py checks the agent still writes
# it). Its 23 characters sit inside idx_events_message's 24-character prefix.
OUT_OF_CREDITS_STEP = "Paused \u2014 out of credits"


RUNS_LISTED = 50  # the newest research sessions the Research list shows


def list_runs(cur, user_id: int, limit: int = RUNS_LISTED) -> List[Dict]:
    """The user's newest research sessions. `by_autopilot` is 1 for a session the autopilot started
    (a brief run, which Billing calls "Autopilot research"), so the list can say whose it is.
    `out_of_credits` is 1 for a run-until-stopped session that finished because the credits ran out
    (its log holds OUT_OF_CREDITS_STEP), so the list can say why it stopped (services.run_stop). Still one statement: the log is probed only for a finished
    run-until-stopped session, through idx_events_run_kind."""
    cur.execute(
        """SELECT r.id, r.market, r.direction, r.prompt, r.status, r.hypotheses_tried, r.strategies_passed,
                  r.error, r.run_forever, r.created_at, r.started_at, r.finished_at, r.heartbeat_at,
                  r.brief AS by_autopilot,
                  CASE WHEN r.status='succeeded' AND r.run_forever=1 THEN EXISTS(
                    SELECT 1 FROM app_agent_events e WHERE e.run_id=r.id AND e.kind='step' AND e.message LIKE %s)
                  ELSE 0 END AS out_of_credits
           FROM app_agent_runs r WHERE r.user_id=%s AND r.kind='research' ORDER BY r.id DESC LIMIT %s""",
        (OUT_OF_CREDITS_STEP + "%", user_id, limit),
    )
    return cur.fetchall()


def list_runs_version(cur, user_id: int, limit: int = 50) -> List[Dict]:
    """Every field of the newest sessions that the research list derives what it shows from, except
    the prompt and direction (never rewritten), and with the error as its CRC32; each row also carries
    the user's newest credit-ledger id (a debit moves a session's spend) and their policy's fields. One
    statement through idx_runs_user, idx_credit_user and the policy key: no log probe, no ledger sum.
    services.research_list hashes it into the version the list's 5s poll sends back."""
    cur.execute(
        """SELECT r.id, r.status, r.market, r.hypotheses_tried, r.strategies_passed, r.run_forever,
                  r.started_at, r.finished_at, CRC32(r.error) AS err,
                  (SELECT MAX(l.id) FROM app_credit_ledger l WHERE l.user_id=%s) AS ledger_top,
                  (SELECT CONCAT_WS('|', p.updated_at, p.score, p.base_score, CRC32(p.summary))
                     FROM app_policies p WHERE p.user_id=%s) AS policy
           FROM app_agent_runs r WHERE r.user_id=%s AND r.kind='research' ORDER BY r.id DESC LIMIT %s""",
        (user_id, user_id, user_id, limit),
    )
    return cur.fetchall()


def count_own_research(cur, user_id: int) -> int:
    """How many research sessions the user has, the seeded example left out: the newest one's number in
    the Research list ("Session 3"), which counts the user's own sessions instead of showing the global
    run id ("Session 8" on a first session). One count through idx_runs_user."""
    cur.execute(
        "SELECT COUNT(*) AS n FROM app_agent_runs WHERE user_id=%s AND kind='research' "
        "AND (direction IS NULL OR direction<>%s)",
        (user_id, DEMO_DIRECTION),
    )
    return int((cur.fetchone() or {}).get("n") or 0)


def research_session_numbers(cur, user_id: int) -> Dict[int, int]:
    """{run id: its number among the user's own research sessions}, 1 their first, the seeded example
    left out: the "Session 3" the Research list shows (count_own_research numbers the newest the same
    way), for a download that names the session a charge billed instead of its global run id. One
    read of ids through idx_runs_user."""
    cur.execute(
        "SELECT id FROM app_agent_runs WHERE user_id=%s AND kind='research' "
        "AND (direction IS NULL OR direction<>%s) ORDER BY id",
        (user_id, DEMO_DIRECTION),
    )
    return {int(r["id"]): k for k, r in enumerate(cur.fetchall(), 1)}


def example_run_id(cur, user_id: int) -> Optional[int]:
    """The id of the user's seeded example session (repository.seed_demo_session; the newest if there
    are several), or None. What /example opens: it looked for the example in list_runs, which holds only
    the newest 50 sessions, so a user with more landed on /research. One row through idx_runs_user."""
    cur.execute(
        "SELECT id FROM app_agent_runs WHERE user_id=%s AND kind='research' AND direction=%s ORDER BY id DESC LIMIT 1",
        (user_id, DEMO_DIRECTION),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None


def research_week(cur, user_id: int, since, include_demo: bool = False) -> List[Dict]:
    """The user's research runs created since `since`, totalled per model (for pricing): runs,
    ideas tried, strategies passed, tokens. One indexed aggregate, cheap enough for the panel poll.
    The demo session every new account is seeded with (direction 'random_walk', see
    repository.seed_demo_session) is left out unless `include_demo`: a brand-new autopilot read
    "2 tested" it never ran, but the Research page lists the demo and its headline must agree."""
    demo = "" if include_demo else " AND (direction IS NULL OR direction <> 'random_walk')"  # strategy_repository.DEMO_DIRECTION
    cur.execute(
        """SELECT model, COUNT(*) AS runs, COALESCE(SUM(hypotheses_tried),0) AS tried,
                  COALESCE(SUM(strategies_passed),0) AS passed, COALESCE(SUM(input_tokens),0) AS input_tokens,
                  COALESCE(SUM(output_tokens),0) AS output_tokens
           FROM app_agent_runs WHERE user_id=%s AND kind='research' AND created_at>=%s""" + demo + " GROUP BY model",
        (user_id, since),
    )
    return cur.fetchall()


def get_run(cur, user_id: int, run_id: int) -> Optional[Dict]:
    cur.execute(
        """SELECT id, kind, market, direction, prompt, status, hypotheses_tried, strategies_passed, error,
                  max_hypotheses, run_forever, model, created_at, started_at, finished_at, heartbeat_at,
                  brief AS by_autopilot
           FROM app_agent_runs WHERE id=%s AND user_id=%s""",
        (run_id, user_id),
    )
    return cur.fetchone()


def research_queue_ahead(cur, run_id: int) -> int:
    """GLOBAL count of queued research runs that a worker will take before this one (claim_run takes
    the lowest id first), so a long wait can say how many sessions are ahead of it."""
    cur.execute("SELECT COUNT(*) AS n FROM app_agent_runs WHERE kind='research' AND status='queued' AND id<%s",
                (run_id,))
    return int(cur.fetchone()["n"])


def set_run_counts(cur, run_id: int, tried: int, passed: int) -> None:
    cur.execute("UPDATE app_agent_runs SET hypotheses_tried=%s, strategies_passed=%s WHERE id=%s",
                (tried, passed, run_id))


def forward_verdicts(cur, run_id: int) -> Dict[str, Dict]:
    """{title: the newest diversification verdict the run logged for it} (agent._promote_if_forward_validated's
    phase 'forward' event: marginal_ok and the gatekeeper's reason), every strategy of the run in one read
    through idx_events_run_kind; the run's verdict rows are sorted here, as _newest_events does."""
    cur.execute(
        "SELECT id, data_json FROM app_agent_events WHERE run_id=%s AND kind='verdict' "
        "AND message LIKE %s", (run_id, "%: diversification gate %"),
    )
    out: Dict[str, Dict] = {}
    for r in sorted(cur.fetchall(), key=lambda r: r.get("id") or 0, reverse=True):
        data = _loads(r.get("data_json")) or {}
        if data.get("phase") == "forward" and data.get("title") is not None:
            out.setdefault(data["title"], data)
    return out


def forward_verdict(cur, run_id: int, title: str) -> Optional[Dict]:
    """The diversification verdict a run logged for one of its strategies (forward_verdicts), or None."""
    return forward_verdicts(cur, run_id).get(title)


# The steps the session page reads a flag from (it ran out of credits; the loop tuned its search): the only
# steps run_events' tally reads.
TALLY_STEPS = (OUT_OF_CREDITS_STEP + "%", "Dreaming:%", "Research policy evolved:%")


def run_events(cur, run_id: int, after_id: int = 0, limit: int = 0, before_id: int = 0,
               tally: bool = False) -> List[Dict]:
    """The run's events with id > after_id, oldest first: every one (the session page's poll after its last
    line, the agent's own reads). With `limit`, only the newest `limit` of them, and with `before_id` only
    those older than it: one backward range read of idx_events_run (run_id, id) that stops at `limit` rows.
    A run-until-stopped session logs thousands of lines, and its page loaded every one to show the latest.
    The index is named: on a small table the planner walked the primary key down from `before_id` instead,
    through every other run's lines below it.

    `tally` (with `limit`, for the page's first read, which sends the newest limit-1 and reads one more to
    know whether older ones remain) adds, in the same statement and marked `tally`, the lines older than
    those limit-1 that the page counts or reads a flag from: each hypothesis (its id and kind alone), each
    verdict (with its message and data), each skeptic's review, pause and resume, and the steps TALLY_STEPS
    names; never the thinking lines, usually most of a long session. Through idx_events_run_kind, bounded
    by an index-only read of the newest limit-1 ids."""
    if not limit:
        cur.execute(
            "SELECT id, kind, message, data_json, created_at FROM app_agent_events WHERE run_id=%s AND id>%s ORDER BY id",
            (run_id, after_id),
        )
        rows = cur.fetchall()
    else:
        bounds = [("id>%s", after_id), ("id<%s", before_id)]
        page = ("SELECT id, kind, message, data_json, created_at, 0 AS tally FROM app_agent_events "
                "FORCE INDEX (idx_events_run) WHERE run_id=%s" + "".join(" AND " + sql for sql, v in bounds if v)
                + " ORDER BY id DESC LIMIT %s")
        args = [run_id, *(v for _, v in bounds if v), limit]
        if tally:
            page = "(" + page + ") UNION ALL (" + (
                "SELECT id, kind, CASE WHEN kind IN ('verdict','step') THEN message END, "
                "CASE WHEN kind='verdict' THEN data_json END, created_at, 1 FROM app_agent_events "
                "FORCE INDEX (idx_events_run_kind) WHERE run_id=%s "
                "AND kind IN ('hypothesis','challenger','verdict','paused','resumed','step') "
                "AND (kind<>'step' OR message LIKE %s OR message LIKE %s OR message LIKE %s) "
                "AND id<(SELECT MIN(id) FROM (SELECT id FROM app_agent_events FORCE INDEX (idx_events_run) "
                "WHERE run_id=%s ORDER BY id DESC LIMIT %s) AS newest))")
            args += [run_id, *TALLY_STEPS, run_id, limit - 1]
        cur.execute(page, tuple(args))
        rows = sorted(cur.fetchall(), key=lambda r: r["id"])
    for r in rows:
        r["data"] = _loads(r.pop("data_json"))
        if r.pop("tally", 0):
            r["tally"] = True
    return rows


def research_verdicts_after(cur, user_id: int, markets: List[str], after_run_id: int, include_run_id: int = 0,
                            max_runs: int = 200) -> List[Dict]:
    """Verdict events of this user's FINISHED research runs on `markets` with id > after_run_id (plus
    include_run_id, the run that is finishing now), oldest run first, as {run_id, market, day, message,
    data}. At most the newest max_runs runs; the rsi_sleep consolidation reads these. Each run's rows come
    through idx_events_run_kind, never a scan of the event table."""
    if not markets:
        return []
    cur.execute(
        "SELECT id, market, created_at FROM app_agent_runs WHERE user_id=%%s AND kind='research' "
        "AND market IN (%s) AND id>%%s AND (status NOT IN ('queued','running','paused') OR id=%%s) "
        "ORDER BY id DESC LIMIT %%s" % ",".join(["%s"] * len(markets)),
        (user_id, *markets, after_run_id, include_run_id, max_runs))
    runs = {r["id"]: r for r in cur.fetchall()}
    if not runs:
        return []
    cur.execute(
        "SELECT id, run_id, message, data_json FROM app_agent_events WHERE run_id IN (%s) AND kind='verdict'"
        % ",".join(["%s"] * len(runs)), tuple(runs))
    out = []
    for r in sorted(cur.fetchall(), key=lambda r: (r["run_id"], r.get("id") or 0)):
        run = runs[r["run_id"]]
        created = run.get("created_at")
        out.append({"run_id": r["run_id"], "market": run["market"],
                    "day": created.strftime("%Y-%m-%d") if hasattr(created, "strftime") else str(created or "")[:10],
                    "message": r.get("message") or "", "data": _loads(r.get("data_json")) or {}})
    return out
