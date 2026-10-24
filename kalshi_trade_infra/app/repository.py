"""Every SQL statement the customer app runs. Business logic (server, agent,
engine) takes a cursor and calls these, so it can be tested with a fake.

Datetimes are stored as naive UTC, like the rest of this database.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

STARTING_PAPER_BALANCE = 1000.0

# How many times a broken research run may be reclaimed + resumed from its checkpoint before it
# fails for good. Caps a run that keeps wedging at the same spot (a hanging data load) so it can't
# loop forever re-spending the user's model budget. Env-tunable.
MAX_RESUMES = int(os.getenv("TAU_RUN_MAX_RESUMES", "3"))


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


# -- users & sessions ----------------------------------------------------------


def ensure_welcome_bonus(cur, user_id: int) -> bool:
    """Grant the one-time welcome bonus if this user never received it.

    Idempotent and self-healing: the kind='bonus' check skips anyone who already
    has it (including backfilled rows), and the per-user stripe_ref makes concurrent
    logins race-safe via the uq_credit_stripe unique key. Called on EVERY login, so a
    grant that silently failed at signup (or predates the feature) is repaired for free.
    """
    from app import billing
    cur.execute("SELECT 1 FROM app_credit_ledger WHERE user_id=%s AND kind='bonus' LIMIT 1", (user_id,))
    if cur.fetchone():
        return False
    return add_credit(cur, user_id, "bonus", billing.FREE_BONUS, "Welcome credits",
                      stripe_ref="welcome-%d" % user_id)


def is_waitlist_approved(cur, email: str) -> bool:
    """True if this email was approved off the waitlist (case/space-insensitive)."""
    if not email:
        return False
    cur.execute(
        "SELECT 1 FROM app_waitlist WHERE LOWER(TRIM(email))=LOWER(TRIM(%s)) AND status='approved' LIMIT 1",
        (email,),
    )
    return cur.fetchone() is not None


def set_waitlist_status(cur, email: str, status: str) -> bool:
    cur.execute("UPDATE app_waitlist SET status=%s WHERE LOWER(TRIM(email))=LOWER(TRIM(%s))", (status, email))
    return cur.rowcount > 0


def remove_waitlist(cur, email: str) -> bool:
    cur.execute("DELETE FROM app_waitlist WHERE LOWER(TRIM(email))=LOWER(TRIM(%s))", (email,))
    return cur.rowcount > 0


def upsert_google_user(cur, sub: str, email: str, name: Optional[str], picture: Optional[str],
                       allow_new: bool = True) -> Optional[Dict]:
    """Create on first sign-in (with the starting paper balance), refresh profile after.
    Invite-only: a brand-new account is created only when `allow_new` (admin or an
    approved waitlist email); otherwise the request is waitlisted and None is returned."""
    now = now_utc()
    cur.execute("SELECT id FROM app_users WHERE google_sub=%s", (sub,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE app_users SET email=%s, name=%s, picture_url=%s, last_login_at=%s WHERE id=%s",
            (email, name, picture, now, row["id"]),
        )
        ensure_welcome_bonus(cur, row["id"])  # self-heal a missed grant on return
        return get_user(cur, row["id"])
    if not allow_new:
        if email:
            add_waitlist(cur, email, None)  # record the access request
        return None
    cur.execute(
        """INSERT INTO app_users (google_sub, email, name, picture_url, created_at, last_login_at)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (sub, email, name, picture, now, now),
    )
    user_id = cur.lastrowid
    assign_username(cur, user_id, email, name)  # unique @handle for community mentions
    # Once they're in, they're off the waitlist — the two lists are exclusive.
    if email:
        cur.execute("DELETE FROM app_waitlist WHERE LOWER(TRIM(email))=LOWER(TRIM(%s))", (email,))
    add_ledger(cur, user_id, "deposit", STARTING_PAPER_BALANCE, "Starting paper balance")
    ensure_welcome_bonus(cur, user_id)
    seed_demo_session(cur, user_id)
    return get_user(cur, user_id)


_USERNAME_RE = re.compile(r"[^a-z0-9]")
MENTION_RE = re.compile(r"(?<![\w@])@([a-z0-9_]{2,32})")  # @handle tokens in a post/comment


def _slug_username(base: str) -> str:
    s = _USERNAME_RE.sub("", (base or "").lower())[:20]
    return s or "trader"


def assign_username(cur, user_id: int, email: Optional[str], name: Optional[str]) -> str:
    """Give the user a unique @handle derived from their email/name. Idempotent-ish:
    uniqueness is checked against every other row, so a re-run picks a free handle."""
    base = _slug_username((email.split("@")[0] if email else "") or name or "trader")
    candidate, n = base, 1
    while True:
        cur.execute("SELECT id FROM app_users WHERE username=%s AND id<>%s", (candidate, user_id))
        if not cur.fetchone():
            break
        n += 1
        candidate = ("%s%d" % (base, n))[:32]
    cur.execute("UPDATE app_users SET username=%s WHERE id=%s", (candidate, user_id))
    return candidate


def mention_candidates(cur, q: str, limit: int = 8) -> List[Dict]:
    """Users whose handle or name matches `q`, for the @-autocomplete."""
    like = (q or "").lower() + "%"
    namelike = "%" + (q or "").lower() + "%"
    cur.execute(
        """SELECT username, name FROM app_users
           WHERE username IS NOT NULL AND (LOWER(username) LIKE %s OR LOWER(name) LIKE %s)
           ORDER BY (LOWER(username) LIKE %s) DESC, username LIMIT %s""",
        (like, namelike, like, limit),
    )
    return cur.fetchall()


def users_by_usernames(cur, usernames: List[str]) -> List[Dict]:
    if not usernames:
        return []
    marks = ",".join(["%s"] * len(usernames))
    cur.execute("SELECT id, username, name, email FROM app_users WHERE username IN (%s)" % marks, tuple(usernames))
    return cur.fetchall()


def get_user(cur, user_id: int) -> Optional[Dict]:
    cur.execute(
        "SELECT id, email, name, username, picture_url, autopilot, autopilot_live, autopilot_daily_loss_limit, autopilot_model, ui_theme, created_at FROM app_users WHERE id=%s", (user_id,)
    )
    return cur.fetchone()


def lock_user(cur, user_id: int) -> None:
    """Serialise every cash-moving write for one user (inside a transaction)."""
    cur.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (user_id,))


def set_autopilot(cur, user_id: int, on: bool) -> None:
    cur.execute("UPDATE app_users SET autopilot=%s WHERE id=%s", (1 if on else 0, user_id))


def set_autopilot_live(cur, user_id: int, on: bool) -> None:
    cur.execute("UPDATE app_users SET autopilot_live=%s WHERE id=%s", (1 if on else 0, user_id))


def autopilot_user_ids(cur) -> List[int]:
    """Every user with the autopilot toggle ON. The scheduler enqueues a periodic 'review' run for
    each, which is the only thing that makes the co-pilot act on its own (otherwise it runs only on chat)."""
    cur.execute("SELECT id FROM app_users WHERE autopilot=1")
    return [(r["id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()]


def autopilot_on(cur, user_id: int) -> bool:
    """Whether one user has the autopilot toggle ON — the per-user check the research-completion
    event hook needs (the scheduler uses autopilot_user_ids for the whole set)."""
    cur.execute("SELECT autopilot FROM app_users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    if not row:
        return False
    return bool(row["autopilot"] if isinstance(row, dict) else row[0])


def autopilot_live_over_limit(cur, day_start) -> List[Dict]:
    """Users with live autopilot ON whose live realized loss since `day_start` has hit their
    daily loss limit. The kill switch / loss guard reads this each engine loop."""
    cur.execute(
        """SELECT u.id, u.autopilot_daily_loss_limit AS lim,
                  COALESCE((SELECT SUM(p.pnl) FROM app_positions p
                            WHERE p.user_id=u.id AND p.mode='live' AND p.status='closed' AND p.closed_at >= %s), 0) AS realized
           FROM app_users u
           WHERE u.autopilot_live=1
           HAVING realized <= -lim""",
        (day_start,),
    )
    return cur.fetchall()


def users_for_equity_guard(cur) -> List[Dict]:
    """Users with a live key who can open live positions right now (live autopilot on,
    or a running live deployment), with their daily loss limit."""
    cur.execute(
        """SELECT u.id, u.autopilot_live, u.autopilot_daily_loss_limit AS lim
           FROM app_users u JOIN app_kalshi_keys k ON k.user_id=u.id
           WHERE u.autopilot_live=1
              OR EXISTS (SELECT 1 FROM app_deployments d
                         WHERE d.user_id=u.id AND d.mode='live' AND d.status='running')
           ORDER BY u.id"""
    )
    return cur.fetchall()


def equity_day_start(cur, user_id: int, day: str, equity: float) -> float:
    """This user's first Kalshi account equity reading of the UTC `day`."""
    from data_pipeline.common import day_start_value

    return day_start_value(cur, "app_equity_day_start:%d" % int(user_id), day, equity)


def create_session(cur, user_id: int, token_hash: str, ttl: timedelta) -> None:
    now = now_utc()
    cur.execute(
        "INSERT INTO app_sessions (token_hash, user_id, created_at, expires_at) VALUES (%s,%s,%s,%s)",
        (token_hash, user_id, now, now + ttl),
    )


def session_user(cur, token_hash: str) -> Optional[Dict]:
    cur.execute(
        """SELECT u.id, u.email, u.name, u.username, u.picture_url, u.autopilot, u.autopilot_live, u.autopilot_daily_loss_limit, u.ui_theme, u.created_at
           FROM app_sessions s JOIN app_users u ON u.id=s.user_id
           WHERE s.token_hash=%s AND s.expires_at > %s""",
        (token_hash, now_utc()),
    )
    return cur.fetchone()


def delete_session(cur, token_hash: str) -> None:
    cur.execute("DELETE FROM app_sessions WHERE token_hash=%s", (token_hash,))


def save_oauth_state(cur, state: str, nonce: str, verifier: str) -> None:
    now = now_utc()
    cur.execute("DELETE FROM app_oauth_states WHERE created_at < %s", (now - timedelta(minutes=10),))
    cur.execute(
        "INSERT INTO app_oauth_states (state, nonce, code_verifier, created_at) VALUES (%s,%s,%s,%s)",
        (state, nonce, verifier, now),
    )


def pop_oauth_state(cur, state: str) -> Optional[Dict]:
    """Single use: whoever deletes the row owns it, so a replayed callback fails."""
    cur.execute(
        "SELECT nonce, code_verifier, created_at FROM app_oauth_states WHERE state=%s", (state,)
    )
    row = cur.fetchone()
    if not row:
        return None
    cur.execute("DELETE FROM app_oauth_states WHERE state=%s", (state,))
    if cur.rowcount != 1 or row["created_at"] < now_utc() - timedelta(minutes=10):
        return None
    return row


# -- Kalshi keys ---------------------------------------------------------------


def save_kalshi_key(cur, user_id: int, key_id: str, private_key_enc: bytes) -> None:
    cur.execute(
        """INSERT INTO app_kalshi_keys (user_id, key_id, private_key_enc, created_at) VALUES (%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE key_id=VALUES(key_id), private_key_enc=VALUES(private_key_enc),
             created_at=VALUES(created_at)""",
        (user_id, key_id, private_key_enc, now_utc()),
    )


def get_kalshi_key(cur, user_id: int) -> Optional[Dict]:
    cur.execute("SELECT key_id, private_key_enc, created_at FROM app_kalshi_keys WHERE user_id=%s", (user_id,))
    return cur.fetchone()


def delete_kalshi_key(cur, user_id: int) -> None:
    cur.execute("DELETE FROM app_kalshi_keys WHERE user_id=%s", (user_id,))


# -- Kalshi DEMO (sandbox) keys ------------------------------------------------
# Exact mirror of the live-key accessors above, against app_kalshi_dev_keys. The
# demo execution path reads ONLY these, so a user's demo orders can never pick up
# their live key.


def set_kalshi_dev_key(cur, user_id: int, key_id: str, private_key_enc: bytes) -> None:
    cur.execute(
        """INSERT INTO app_kalshi_dev_keys (user_id, key_id, private_key_enc, created_at) VALUES (%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE key_id=VALUES(key_id), private_key_enc=VALUES(private_key_enc),
             created_at=VALUES(created_at)""",
        (user_id, key_id, private_key_enc, now_utc()),
    )


def get_kalshi_dev_key(cur, user_id: int) -> Optional[Dict]:
    cur.execute("SELECT key_id, private_key_enc, created_at FROM app_kalshi_dev_keys WHERE user_id=%s", (user_id,))
    return cur.fetchone()


def delete_kalshi_dev_key(cur, user_id: int) -> None:
    cur.execute("DELETE FROM app_kalshi_dev_keys WHERE user_id=%s", (user_id,))


# -- paper ledger --------------------------------------------------------------


def add_ledger(cur, user_id: int, kind: str, amount: float, memo: str, position_id: Optional[int] = None) -> None:
    cur.execute(
        "INSERT INTO app_ledger (user_id, kind, amount, position_id, memo, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (user_id, kind, round(amount, 4), position_id, memo[:255], now_utc()),
    )


def paper_balance(cur, user_id: int) -> float:
    cur.execute("SELECT COALESCE(SUM(amount),0) AS b FROM app_ledger WHERE user_id=%s", (user_id,))
    return float(cur.fetchone()["b"])


def paper_deposits(cur, user_id: int) -> float:
    """Net money the user put in - the denominator of account ROI."""
    cur.execute(
        "SELECT COALESCE(SUM(amount),0) AS b FROM app_ledger WHERE user_id=%s AND kind IN ('deposit','withdrawal')",
        (user_id,),
    )
    return float(cur.fetchone()["b"])


def ledger_rows(cur, user_id: int, limit: int = 50) -> List[Dict]:
    cur.execute(
        "SELECT id, kind, amount, memo, created_at FROM app_ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    return cur.fetchall()


def reset_paper_account(cur, user_id: int, amount: float) -> None:
    """Wipe the paper ledger and start fresh at `amount`. Only safe with no open paper
    positions (the caller guards this) — otherwise their debited cost would be orphaned."""
    cur.execute("DELETE FROM app_ledger WHERE user_id=%s", (user_id,))
    add_ledger(cur, user_id, "deposit", amount, "Paper account reset")


# -- demo (sandbox) app-controlled capital -------------------------------------
# Demo places REAL orders on Kalshi's sandbox for real fills, but the money is ours: P&L from
# those fills is applied to a capital we set, not the real demo-account balance.


def demo_account(cur, user_id: int) -> tuple:
    """(capital, pnl_base) for the user's app-controlled demo account."""
    cur.execute("SELECT demo_capital, demo_pnl_base FROM app_users WHERE id=%s", (user_id,))
    r = cur.fetchone()
    if not r:
        return (STARTING_PAPER_BALANCE, 0.0)
    return (float(r["demo_capital"]), float(r["demo_pnl_base"]))


def reload_demo(cur, user_id: int, amount: float) -> None:
    """Set demo starting capital to `amount` and snapshot current realized P&L as the new
    baseline, so demo P&L shown resets to 0 and future fills accrue from there."""
    base = realized_pnl(cur, user_id, "demo")
    cur.execute(
        "UPDATE app_users SET demo_capital=%s, demo_pnl_base=%s WHERE id=%s",
        (round(amount, 4), round(base, 4), user_id),
    )


def demo_equity(cur, user_id: int) -> Dict:
    """Demo money as cost-basis equity: capital + realized P&L since the last reload. Mirrors
    paper's equity convention (open positions valued at cost), so the three buckets line up."""
    capital, base = demo_account(cur, user_id)
    net = realized_pnl(cur, user_id, "demo") - base
    return {
        "capital": round(capital, 2),
        "realized": round(net, 2),
        "equity": round(capital + net, 2),
        "roi": round(net / capital, 4) if capital > 0 else None,
    }


# -- agent runs ----------------------------------------------------------------

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


def largest_tables(cur, limit: int = 5) -> List[Dict]:
    """The biggest tables by on-disk size (data+index), for admin storage visibility — so the
    operator SEES which table is eating the volume (e.g. `markets.raw_json`) before it fills the
    disk again. Read-only information_schema query; returns [] if it can't run (older/edge DBs)."""
    try:
        cur.execute(
            "SELECT table_name AS t, ROUND((data_length + index_length) / 1048576) AS mb "
            "FROM information_schema.tables WHERE table_schema = DATABASE() "
            "ORDER BY (data_length + index_length) DESC LIMIT %s",
            (int(limit),),
        )
        return [{"table": r["t"], "mb": int(r["mb"] or 0)} for r in cur.fetchall()]
    except Exception:  # noqa: BLE001 - telemetry must never break the admin page
        return []


def count_active_research(cur) -> int:
    """GLOBAL count (all users) of research runs that hold or await a worker slot — for autopilot
    backpressure: when the shared queue is already saturated, don't launch more. Uses the
    idx_runs_status(status, created_at) index on the bounded status set."""
    cur.execute("SELECT COUNT(*) AS n FROM app_agent_runs "
                "WHERE kind='research' AND status IN ('queued','running','paused')")
    return int(cur.fetchone()["n"])


def claim_run(conn, worker_id: str) -> Optional[Dict]:
    """Take the oldest queued run. SKIP LOCKED lets any number of workers
    share the queue without two of them taking the same run."""
    with transaction(conn) as cur:
        cur.execute(
            "SELECT * FROM app_agent_runs WHERE status='queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
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
        if progressed and int(r["resume_count"]) < max_resumes:
            cur.execute(
                """UPDATE app_agent_runs SET status='queued', worker_id=NULL,
                     resume_count=resume_count+1, heartbeat_at=%s
                   WHERE id=%s AND status='running' AND heartbeat_at < %s""",
                (now_utc(), r["id"], stale_cut),
            )
            if cur.rowcount:
                add_event(cur, r["id"], "step",
                          "Session interrupted — reclaiming it to resume from the last checkpoint "
                          "(attempt %d of %d)." % (int(r["resume_count"]) + 1, max_resumes))
                reaped += 1
        else:
            # Being interrupted/abandoned is NOT a failure — it's a STOPPED run that reports how far it
            # got. Only a genuine external/infra error (caught in run_research) is `failed`. The card
            # shows "Explored N hypotheses" in neutral, not a red FAILED. Carry the explored/passed
            # counts off the checkpoint so that readout is accurate even though finish_run never ran.
            tried_n = len(ck.get("tried") or []) if ck else 0
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


def list_runs(cur, user_id: int, limit: int = 50) -> List[Dict]:
    cur.execute(
        """SELECT id, market, direction, prompt, status, hypotheses_tried, strategies_passed, error,
                  created_at, started_at, finished_at
           FROM app_agent_runs WHERE user_id=%s AND kind='research' ORDER BY id DESC LIMIT %s""",
        (user_id, limit),
    )
    return cur.fetchall()


def get_run(cur, user_id: int, run_id: int) -> Optional[Dict]:
    cur.execute(
        """SELECT id, kind, market, direction, prompt, status, hypotheses_tried, strategies_passed, error,
                  max_hypotheses, run_forever, model, created_at, started_at, finished_at
           FROM app_agent_runs WHERE id=%s AND user_id=%s""",
        (run_id, user_id),
    )
    return cur.fetchone()


def set_run_counts(cur, run_id: int, tried: int, passed: int) -> None:
    cur.execute("UPDATE app_agent_runs SET hypotheses_tried=%s, strategies_passed=%s WHERE id=%s",
                (tried, passed, run_id))


def run_events(cur, run_id: int, after_id: int = 0) -> List[Dict]:
    cur.execute(
        "SELECT id, kind, message, data_json, created_at FROM app_agent_events WHERE run_id=%s AND id>%s ORDER BY id",
        (run_id, after_id),
    )
    rows = cur.fetchall()
    for r in rows:
        r["data"] = _loads(r.pop("data_json"))
    return rows


# -- strategies ----------------------------------------------------------------


def insert_strategy(
    cur, user_id: int, run_id: Optional[int], parent_id: Optional[int], market: str, direction: str,
    title: str, thesis: str, spec: Dict, status: str, result: Optional[Dict],
) -> int:
    cur.execute(
        """INSERT INTO app_strategies
             (user_id, run_id, parent_id, market, direction, title, thesis, spec_json, status, result_json, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (user_id, run_id, parent_id, market, direction, title[:200], thesis, _json(spec), status, _json(result), now_utc()),
    )
    return cur.lastrowid


def set_strategy_outcome(cur, strategy_id: int, status: str, result: Optional[Dict],
                         experiment_id: Optional[int] = None) -> None:
    """Record a strategy's final status/result after the gatekeeper's verdict. The research loop
    inserts the row first (so the immutable experiment can carry its strategy_id), then writes
    the classification-derived outcome here once judging returns. `experiment_id` is the robust
    link back to the pre-registration this strategy was validated under — the research-paper page
    resolves by it first (surviving a re-hit re-point). Status/result/experiment_id only — the
    row's identity fields are never touched."""
    cur.execute(
        "UPDATE app_strategies SET status=%s, result_json=%s, experiment_id=%s WHERE id=%s",
        (status, _json(result), experiment_id, strategy_id),
    )


def _strategy_row(r: Dict) -> Dict:
    r["spec"] = _loads(r.pop("spec_json"))
    if "result_json" in r:
        r["result"] = _loads(r.pop("result_json"))
    return r


NOISE_STATUSES = ("rejected", "failed")  # the un-kept outcomes the default list view hides


def _strategy_filter_sql(direction, status, market, run_id, q, deployed, hide_noise=False) -> tuple:
    """Shared WHERE clause for list/count so the headline figures and the page agree.
    `hide_noise` (default list view only) drops rejected/void rows — they stay in the DB (the
    immutable ledger counts every tested hypothesis for DSR/FDR), just out of the default page.
    Ignored when an explicit `status` is selected (that exact-match already scopes the view)."""
    sql, params = " WHERE s.user_id=%s", []  # caller prepends user_id
    for col, val in (("s.direction", direction), ("s.status", status), ("s.market", market), ("s.run_id", run_id)):
        if val:
            sql += " AND %s=%%s" % col
            params.append(val)
    if hide_noise and not status:
        sql += " AND s.status NOT IN (%s)" % ",".join(["%s"] * len(NOISE_STATUSES))
        params.extend(NOISE_STATUSES)
    if q:
        sql += " AND (s.title LIKE %s OR s.thesis LIKE %s)"
        like = "%" + q + "%"
        params.extend((like, like))
    if deployed:
        sql += " AND EXISTS (SELECT 1 FROM app_deployments d WHERE d.strategy_id=s.id AND d.status<>'stopped')"
    return sql, params


def list_strategies(
    cur, user_id: int, direction: Optional[str] = None, status: Optional[str] = None, market: Optional[str] = None,
    run_id: Optional[int] = None, limit: int = 500, offset: int = 0, q: Optional[str] = None, deployed: bool = False,
    hide_noise: bool = False,
) -> List[Dict]:
    where, fparams = _strategy_filter_sql(direction, status, market, run_id, q, deployed, hide_noise)
    sql = ("""SELECT s.id, s.run_id, s.parent_id, s.market, s.direction, s.title, s.thesis, s.spec_json, s.status,
                    s.result_json, s.experiment_id, s.created_at, r.hypotheses_tried, s.shared_from_user_id, su.name AS shared_from_name,
                    (SELECT COUNT(*) FROM app_deployments d WHERE d.strategy_id=s.id AND d.status<>'stopped') AS active_deps,
                    (SELECT COUNT(*) FROM app_deployments d WHERE d.strategy_id=s.id AND d.status<>'stopped' AND d.mode='live') AS live_deps
             FROM app_strategies s LEFT JOIN app_agent_runs r ON r.id=s.run_id
                  LEFT JOIN app_users su ON su.id=s.shared_from_user_id""" + where)
    params: List[Any] = [user_id] + fparams
    # Non-rejected (passed/void) first, then newest: in a big run the passed finalists are
    # found early (oldest ids), so a plain id-DESC fetch past the limit would drop them.
    sql += " ORDER BY (s.status='rejected'), s.id DESC LIMIT %s OFFSET %s"
    params.extend((limit, offset))
    cur.execute(sql, params)
    return [_strategy_row(r) for r in cur.fetchall()]


def count_strategies(
    cur, user_id: int, direction: Optional[str] = None, market: Optional[str] = None,
    q: Optional[str] = None, deployed: bool = False,
) -> Dict[str, int]:
    """Status histogram for the user's strategies via COUNT(*), so the headline figures
    reflect the true total rather than a capped page. Keys are the status values plus
    "total" (their sum). Narrowed by direction/market/search/deployed, matching list_strategies
    (status is left open so every status bucket is counted)."""
    where, fparams = _strategy_filter_sql(direction, None, market, None, q, deployed)
    sql = "SELECT s.status, COUNT(*) AS n FROM app_strategies s" + where + " GROUP BY s.status"
    params: List[Any] = [user_id] + fparams
    cur.execute(sql, params)
    counts: Dict[str, int] = {r["status"]: int(r["n"]) for r in cur.fetchall()}
    counts["total"] = sum(counts.values())
    return counts


def delete_strategy(cur, user_id: int, strategy_id: int) -> bool:
    """Remove a strategy from the user's inventory. Caller ensures it isn't deployed."""
    cur.execute("DELETE FROM app_strategies WHERE id=%s AND user_id=%s", (strategy_id, user_id))
    return cur.rowcount > 0


def share_strategy(cur, src_id: int, from_uid: int, to_uid: int) -> Optional[int]:
    """Copy strategy `src_id` (owned by `from_uid`) into `to_uid`'s inventory so it is theirs
    to deploy and cannot be revoked. Returns the new strategy id, or None if the source doesn't
    exist / isn't the sender's, or the recipient already has this exact share."""
    cur.execute(
        "SELECT market, direction, title, thesis, spec_json, status, result_json FROM app_strategies WHERE id=%s AND user_id=%s",
        (src_id, from_uid),
    )
    src = cur.fetchone()
    if not src:
        return None
    cur.execute("SELECT id FROM app_strategies WHERE user_id=%s AND shared_src_id=%s", (to_uid, src_id))
    if cur.fetchone():
        return None  # already shared to this user — idempotent, no duplicate copy
    cur.execute(
        """INSERT INTO app_strategies
             (user_id, run_id, parent_id, market, direction, title, thesis, spec_json, status, result_json,
              created_at, shared_from_user_id, shared_src_id)
           VALUES (%s,NULL,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (to_uid, src["market"], src["direction"], src["title"], src["thesis"], src["spec_json"],
         src["status"], src["result_json"], now_utc(), from_uid, src_id),
    )
    return cur.lastrowid


def community_email_recipients(cur, exclude_uid: int, cooldown_hours: int = 4) -> List[Dict]:
    """Users to email about new community activity: opted-in, with an email, not the author,
    and not emailed within the cooldown (so a burst of posts can't flood anyone)."""
    cutoff = now_utc() - timedelta(hours=cooldown_hours)
    cur.execute(
        """SELECT id, email, name FROM app_users
           WHERE id<>%s AND email IS NOT NULL AND email<>'' AND COALESCE(email_opt_out,0)=0
                 AND (last_community_email_at IS NULL OR last_community_email_at < %s)""",
        (exclude_uid, cutoff),
    )
    return cur.fetchall()


def mark_community_emailed(cur, user_ids: List[int]) -> None:
    if not user_ids:
        return
    placeholders = ",".join(["%s"] * len(user_ids))
    cur.execute("UPDATE app_users SET last_community_email_at=%s WHERE id IN (%s)" % ("%s", placeholders),
                [now_utc()] + list(user_ids))


def set_ui_theme(cur, user_id: int, theme: str) -> None:
    cur.execute("UPDATE app_users SET ui_theme=%s WHERE id=%s", (theme, user_id))


def set_email_opt_out(cur, user_id: int, opt_out: bool) -> bool:
    cur.execute("UPDATE app_users SET email_opt_out=%s WHERE id=%s", (1 if opt_out else 0, user_id))
    return cur.rowcount == 1


def add_notification(cur, user_id: int, kind: str, body: str, link: Optional[str] = None) -> int:
    cur.execute(
        "INSERT INTO app_notifications (user_id, kind, body, link, created_at) VALUES (%s,%s,%s,%s,%s)",
        (user_id, kind, body[:400], link, now_utc()),
    )
    return cur.lastrowid


def list_notifications(cur, user_id: int, limit: int = 20) -> List[Dict]:
    cur.execute(
        "SELECT id, kind, body, link, created_at, read_at FROM app_notifications WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    return cur.fetchall()


def count_unread_notifications(cur, user_id: int) -> int:
    cur.execute("SELECT COUNT(*) AS c FROM app_notifications WHERE user_id=%s AND read_at IS NULL", (user_id,))
    return int(cur.fetchone()["c"])


def mark_notifications_read(cur, user_id: int) -> int:
    cur.execute("UPDATE app_notifications SET read_at=%s WHERE user_id=%s AND read_at IS NULL", (now_utc(), user_id))
    return cur.rowcount


def get_strategy(cur, user_id: int, strategy_id: int) -> Optional[Dict]:
    cur.execute(
        """SELECT s.id, s.run_id, s.parent_id, s.market, s.direction, s.title, s.thesis, s.spec_json, s.status,
                  s.result_json, s.experiment_id, s.created_at, r.hypotheses_tried, s.shared_from_user_id, su.name AS shared_from_name
           FROM app_strategies s LEFT JOIN app_agent_runs r ON r.id=s.run_id
                LEFT JOIN app_users su ON su.id=s.shared_from_user_id
           WHERE s.id=%s AND s.user_id=%s""",
        (strategy_id, user_id),
    )
    row = cur.fetchone()
    return _strategy_row(row) if row else None


def strategy_records(cur, user_id: int, market: str, limit: int = 500) -> List[Dict]:
    """Raw discovery-tree records for one user+market, OLDEST first: each tested
    hypothesis with its in-sample metrics, (if it was gated) its out-of-sample
    outcome, and its id/parent_id lineage (a dig-deeper strategy points back at the
    strategy it refined). Feeds the Tau-RSI replay simulator (app/replay.py)."""
    cur.execute(
        """SELECT id, parent_id, status, result_json FROM app_strategies
           WHERE user_id=%s AND market=%s ORDER BY id ASC LIMIT %s""",
        (user_id, market, limit),
    )
    out: List[Dict] = []
    for r in cur.fetchall():
        res = _loads(r["result_json"]) or {}
        ins = res.get("in_sample") or {}
        oos = res.get("out_of_sample")
        out.append({
            "id": r.get("id"), "parent_id": r.get("parent_id"),
            "in_sample": {"pnl": ins.get("pnl") or 0, "trades": ins.get("trades") or 0},
            "tested": oos is not None,
            "oos_pnl": (oos or {}).get("pnl") or 0.0,
            "passed": r["status"] == "passed",
        })
    return out


def engine_heartbeat(cur, live_enabled: bool) -> None:
    """Per-tick liveness marker for the deployment engine, so a stalled-but-not-crashed
    engine (which `Restart=always` can't catch) is detectable by the watchdog. Critical
    with live orders on."""
    cur.execute(
        """INSERT INTO collector_state (state_key,state_value,updated_at_utc)
           VALUES ('recursive_engine_last_tick',%s,%s)
           ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)""",
        ('{"live": %s}' % ("true" if live_enabled else "false"), now_utc()),
    )


def engine_last_tick_age_seconds(cur) -> Optional[int]:
    """Seconds since the deployment engine's last heartbeat tick, or None if it has never ticked.
    A large or None value means the engine is stalled/dead — surfaced so a stuck engine still
    holding real positions is visible, not silent. Reads the same `collector_state` liveness row
    `engine_heartbeat` writes (the pattern the live_alerter watchdog uses for every other writer)."""
    cur.execute(
        "SELECT TIMESTAMPDIFF(SECOND, updated_at_utc, UTC_TIMESTAMP()) AS a FROM collector_state "
        "WHERE state_key='recursive_engine_last_tick' LIMIT 1"
    )
    row = cur.fetchone() or {}
    return int(row["a"]) if row.get("a") is not None else None


def get_policy(cur, user_id: int) -> Optional[Dict]:
    """The user's current self-evolved exploration policy, or None (= DefaultPolicy)."""
    cur.execute("SELECT code, score, summary, base_score, updated_at FROM app_policies WHERE user_id=%s", (user_id,))
    r = cur.fetchone()
    return {"code": r["code"], "score": float(r["score"]), "summary": r.get("summary"),
            "base_score": (float(r["base_score"]) if r.get("base_score") is not None else None),
            "updated_at": r["updated_at"]} if r else None


def latest_dream_event(cur, user_id: int) -> Optional[Dict]:
    """The user's most recent dreaming log line, across all their runs, so any run page
    can show the Tau-RSI loop is active even when the current run hasn't dreamed yet."""
    cur.execute(
        """SELECT e.message, e.created_at FROM app_agent_events e
           JOIN app_agent_runs r ON r.id=e.run_id
           WHERE r.user_id=%s AND (e.message LIKE 'Dreaming:%%' OR e.message LIKE 'Research policy evolved%%')
           ORDER BY e.id DESC LIMIT 1""",
        (user_id,),
    )
    return cur.fetchone()


def set_policy(cur, user_id: int, code: str, score: float,
               summary: Optional[str] = None, base_score: Optional[float] = None) -> None:
    """Store (upsert) the user's current exploration policy, its replay score, a plain-English
    description of what it changed, and the score it beat."""
    cur.execute(
        """INSERT INTO app_policies (user_id, code, score, summary, base_score, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE code=VALUES(code), score=VALUES(score),
             summary=VALUES(summary), base_score=VALUES(base_score), updated_at=VALUES(updated_at)""",
        (user_id, code, float(score), (summary or "")[:400] or None,
         (float(base_score) if base_score is not None else None), now_utc()),
    )


def research_summary(cur, user_id: int, limit: int = 12) -> List[Dict]:
    """A compact CROSS-market tally of what this user has already researched — per market: how many
    strategies were tried and how many passed, most-recently-touched first. Feeds the agent's own
    market pick (and the fresh-session prompt) so it builds on the user's history across markets
    instead of re-choosing blind. Cheap GROUP-BY on the small app_strategies table."""
    cur.execute(
        """SELECT market,
                  COUNT(*) AS tried,
                  SUM(status = 'passed') AS passed,
                  MAX(id) AS recent
           FROM app_strategies WHERE user_id=%s
           GROUP BY market ORDER BY recent DESC LIMIT %s""",
        (user_id, limit),
    )
    return [{"market": r["market"], "tried": int(r["tried"] or 0), "passed": int(r["passed"] or 0)}
            for r in cur.fetchall()]


def strategy_memory(cur, user_id: int, market: str, limit: int = 40) -> List[Dict]:
    """What this user's agents already tried on this market, newest first."""
    cur.execute(
        """SELECT title, direction, spec_json, status, result_json FROM app_strategies
           WHERE user_id=%s AND market=%s ORDER BY id DESC LIMIT %s""",
        (user_id, market, limit),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


# -- leak-safe failure distillation (learn from dead ends) ---------------------
# A failed strategy's row status. REJECTED (no mechanism / not a finalist / rejected on
# validation) and INCONCLUSIVE map here (see agent._status_for); "passed"/"pending" don't.
FAILED_STATUSES = ("rejected", "failed")


def _failure_dims(s: Dict) -> List[str]:
    """The leak-safe dimensions of a failed strategy — ONLY its own spec + direction, which the
    generator already proposed and is always allowed to see. No held-out number is read."""
    spec = s.get("spec") or {}
    model = spec.get("model") or {}
    entry = spec.get("entry") or {}
    dims: List[str] = []
    if spec.get("side"):
        dims.append("side=%s" % spec["side"])
    if s.get("direction"):
        dims.append("lens=%s" % s["direction"])
    if spec.get("code"):
        dims.append("mechanism=custom-code")
    else:
        beta = model.get("drift_beta") or 0
        if beta > 0:
            dims.append("mechanism=momentum")
        elif beta < 0:
            dims.append("mechanism=mean-reversion")
        if (model.get("vol_scale") or 1.0) != 1.0:
            dims.append("mechanism=vol-mispricing")
    lo, hi = entry.get("min_price"), entry.get("max_price")
    if lo is not None and hi is not None:
        dims.append("price-band=%.2f-%.2f" % (float(lo), float(hi)))
    return dims


def distill_failures(memory: List[Dict], min_recurrence: int = 2) -> Optional[Dict]:
    """Distill the FAILED strategies in a strategy_memory list into ONE compact, leak-safe
    summary of what keeps failing — recurring spec/mechanism regions and the classification
    tally — so the generator explores AWAY from proven-dead ground instead of re-reading a pile
    of individually-useless rejected rows. Returns None when there's nothing to learn from yet
    (so the caller is a no-op on a fresh market).

    LEAK SAFETY (Leak 2 stays closed): reads ONLY what the generator may already see — the
    classification/status LABELS and the hypotheses' own specs/direction. It never reads a
    validation/holdout P&L/Sharpe/return — those are gatekeeper-held and are not even present on
    these rows (_result_block stores research-fold numbers + the label only). So nothing here can
    leak held-out evidence back into generation; it can only make the generator more skeptical.
    """
    failed = [s for s in memory if s.get("status") in FAILED_STATUSES]
    if not failed:
        return None
    classifications: Dict[str, int] = {}
    dim_counts: Dict[str, int] = {}
    for s in failed:
        cls = (s.get("result") or {}).get("classification") or s.get("status")
        classifications[cls] = classifications.get(cls, 0) + 1
        for d in _failure_dims(s):
            dim_counts[d] = dim_counts.get(d, 0) + 1
    patterns = sorted(((d, c) for d, c in dim_counts.items() if c >= min_recurrence),
                      key=lambda dc: (-dc[1], dc[0]))
    return {"n_failed": len(failed), "classifications": classifications, "patterns": patterns}


# -- deployments & positions ---------------------------------------------------


def create_deployment(cur, user_id: int, strategy_id: int, market: str, mode: str) -> int:
    now = now_utc()
    cur.execute(
        """INSERT INTO app_deployments (user_id, strategy_id, market, mode, status, created_at, updated_at)
           VALUES (%s,%s,%s,%s,'running',%s,%s)""",
        (user_id, strategy_id, market, mode, now, now),
    )
    return cur.lastrowid


_DEPLOYMENT_SELECT = """
    SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.status, d.status_reason, d.last_decision_ts,
           d.created_at, d.updated_at, s.title, s.direction, s.spec_json, s.result_json,
           COALESCE(SUM(CASE WHEN p.status='closed' THEN p.pnl END),0) AS realized_pnl,
           COUNT(CASE WHEN p.status='closed' THEN 1 END) AS closed_trades,
           COUNT(CASE WHEN p.status='closed' AND p.pnl > 0 THEN 1 END) AS wins,
           COUNT(CASE WHEN p.status='open' THEN 1 END) AS open_positions
    FROM app_deployments d
    JOIN app_strategies s ON s.id=d.strategy_id
    LEFT JOIN app_positions p ON p.deployment_id=d.id
"""


def list_deployments(cur, user_id: int, include_stopped: bool = False) -> List[Dict]:
    sql = _DEPLOYMENT_SELECT + " WHERE d.user_id=%s"
    if not include_stopped:
        sql += " AND d.status <> 'stopped'"
    sql += " GROUP BY d.id ORDER BY d.id DESC"
    cur.execute(sql, (user_id,))
    return [_strategy_row(r) for r in cur.fetchall()]


def get_deployment(cur, user_id: int, deployment_id: int) -> Optional[Dict]:
    cur.execute(_DEPLOYMENT_SELECT + " WHERE d.id=%s AND d.user_id=%s GROUP BY d.id", (deployment_id, user_id))
    row = cur.fetchone()
    return _strategy_row(row) if row else None


def deployment_closed_stats(cur, deployment_id: int) -> Tuple[int, float]:
    """(closed position rows, their summed P&L) for one deployment."""
    cur.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(pnl),0) AS p FROM app_positions WHERE deployment_id=%s AND status='closed'",
        (deployment_id,),
    )
    row = cur.fetchone() or {}
    return int(row.get("n") or 0), float(row.get("p") or 0)


def paper_round_trips(cur, user_id: int, strategy_id: int, ref_prefix: str = "sim:") -> List[Dict]:
    """Closed PAPER round trips of one strategy that filled through the simulated venue, oldest
    first. One row per entry fill (a part-filled exit's slices share the entry's order_ref and are
    summed), so a single trade is never counted twice. Legacy instant fills (no order_ref) are
    excluded: they are not evidence of what live execution would earn."""
    cur.execute(
        """SELECT p.order_ref, SUM(p.pnl) AS pnl, MIN(p.opened_at) AS opened_at, MAX(p.closed_at) AS closed_at
           FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
           WHERE p.user_id=%s AND d.strategy_id=%s AND p.mode='paper' AND p.order_ref LIKE %s
           GROUP BY p.order_ref
           HAVING SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END)=0
           ORDER BY MIN(p.opened_at)""",
        (user_id, strategy_id, ref_prefix + "%"),
    )
    return [{"pnl": float(r["pnl"] or 0), "opened_at": r["opened_at"], "closed_at": r["closed_at"]}
            for r in cur.fetchall()]


def paper_progress(cur, user_id: int, strategy_ids: List[int], ref_prefix: str = "sim:") -> Dict[int, Tuple[int, float]]:
    """{strategy_id: (closed realistic paper round trips, their net P&L)} for the given strategies,
    in one query. Same counting as `paper_round_trips` (one row per order_ref, still-open slices
    excluded); a cheap progress readout for the autopilot panel, which polls often."""
    if not strategy_ids:
        return {}
    marks = ",".join(["%s"] * len(strategy_ids))
    cur.execute(
        """SELECT t.strategy_id, COUNT(*) AS trips, COALESCE(SUM(t.pnl),0) AS pnl FROM (
             SELECT d.strategy_id, p.order_ref, SUM(p.pnl) AS pnl
             FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id
             WHERE p.user_id=%s AND p.mode='paper' AND p.order_ref LIKE %s AND d.strategy_id IN (""" + marks + """)
             GROUP BY d.strategy_id, p.order_ref
             HAVING SUM(CASE WHEN p.status='open' THEN 1 ELSE 0 END)=0) t
           GROUP BY t.strategy_id""",
        (user_id, ref_prefix + "%", *strategy_ids),
    )
    return {int(r["strategy_id"]): (int(r["trips"] or 0), float(r["pnl"] or 0)) for r in cur.fetchall()}


def running_deployments(cur, market: str) -> List[Dict]:
    cur.execute(
        """SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.last_decision_ts, s.spec_json, s.result_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.status='running' AND d.market=%s ORDER BY d.id""",
        (market,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def deployments_with_open_positions(cur, market: str) -> List[Dict]:
    """Paused deployments still need their open positions settled."""
    cur.execute(
        """SELECT DISTINCT d.id, d.user_id, d.mode, s.spec_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           JOIN app_positions p ON p.deployment_id=d.id AND p.status='open'
           WHERE d.market=%s""",
        (market,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def paused_deployments_with_open_positions(cur, market: str) -> List[Dict]:
    """Paused/stopped deployments that still hold open positions — the auto-flatten sweep closes
    these so a non-running deployment never keeps exposure nothing is actively managing. (Running
    deployments manage their own exits via the spec + force-sell, so they are excluded here.)"""
    cur.execute(
        """SELECT DISTINCT d.id, d.user_id, d.mode, s.spec_json, s.result_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           JOIN app_positions p ON p.deployment_id=d.id AND p.status='open'
           WHERE d.market=%s AND d.status IN ('paused','stopped')""",
        (market,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def set_deployment_status(cur, user_id: int, deployment_id: int, status: str, reason: Optional[str] = None) -> bool:
    cur.execute(
        "UPDATE app_deployments SET status=%s, status_reason=%s, updated_at=%s WHERE id=%s AND user_id=%s AND status<>'stopped'",
        (status, reason, now_utc(), deployment_id, user_id),
    )
    return cur.rowcount == 1


def set_deployment_strategy(cur, user_id: int, deployment_id: int, strategy_id: int) -> bool:
    cur.execute(
        "UPDATE app_deployments SET strategy_id=%s, updated_at=%s WHERE id=%s AND user_id=%s",
        (strategy_id, now_utc(), deployment_id, user_id),
    )
    return cur.rowcount == 1


def claim_decision(cur, deployment_id: int, decision_ts: int) -> bool:
    """At most one decision per deployment per slot, however many engines
    run: whoever moves last_decision_ts forward owns the slot."""
    cur.execute(
        "UPDATE app_deployments SET last_decision_ts=%s WHERE id=%s AND status='running' AND last_decision_ts < %s",
        (decision_ts, deployment_id, decision_ts),
    )
    return cur.rowcount == 1


def open_positions(cur, deployment_id: int) -> List[Dict]:
    cur.execute("SELECT * FROM app_positions WHERE deployment_id=%s AND status='open' ORDER BY id", (deployment_id,))
    return cur.fetchall()


def deployment_realized_series(cur, deployment_id: int) -> List[float]:
    """Realized P&L of each closed position, oldest first — the engine folds this into a
    cumulative equity curve for the drawdown force-sell. Same `status='closed'` definition
    the loss guard uses, so the two agree on what counts as realized."""
    cur.execute(
        "SELECT COALESCE(pnl,0) AS pnl FROM app_positions WHERE deployment_id=%s AND status='closed' ORDER BY closed_at, id",
        (deployment_id,),
    )
    return [float(r["pnl"]) for r in cur.fetchall()]


def update_marks(cur, market: str, marks: Dict[str, float], now: datetime) -> int:
    """Stamp the current YES bid on every open position whose ticker is in `marks`.
    Called from the engine tick, which already holds the live book — no extra API calls.
    `market` scopes the update so one market's tick can't touch another's rows."""
    if not marks:
        return 0
    ts = now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now
    n = 0
    for ticker, mark in marks.items():
        if mark is None:
            continue
        cur.execute(
            """UPDATE app_positions p JOIN app_deployments d ON d.id=p.deployment_id
               SET p.mark_price=%s, p.mark_ts=%s
               WHERE p.status='open' AND p.ticker=%s AND d.market=%s""",
            (round(float(mark), 4), ts, ticker, market),
        )
        n += cur.rowcount
    return n


def market_has_open_positions(cur, market: str) -> bool:
    """Whether any deployment on `market` holds an open position — so the engine knows to refresh
    marks (unrealized P&L + the drawdown guard read them) every tick, not only when a decision is due."""
    cur.execute(
        "SELECT 1 FROM app_positions p JOIN app_deployments d ON d.id=p.deployment_id "
        "WHERE p.status='open' AND d.market=%s LIMIT 1", (market,))
    return cur.fetchone() is not None


def user_positions(cur, user_id: int, status: str = "open", limit: int = 100) -> List[Dict]:
    cur.execute(
        """SELECT p.*, s.title FROM app_positions p
           JOIN app_deployments d ON d.id=p.deployment_id JOIN app_strategies s ON s.id=d.strategy_id
           WHERE p.user_id=%s AND p.status=%s ORDER BY p.id DESC LIMIT %s""",
        (user_id, status, limit),
    )
    return cur.fetchall()


def positions_for_strategy(cur, user_id: int, strategy_id: int, status: str = "open") -> List[Dict]:
    """Open positions a strategy is holding right now, across its deployments."""
    cur.execute(
        """SELECT p.*, d.mode FROM app_positions p
           JOIN app_deployments d ON d.id=p.deployment_id
           WHERE d.strategy_id=%s AND p.user_id=%s AND p.status=%s ORDER BY p.id DESC""",
        (strategy_id, user_id, status),
    )
    return cur.fetchall()


def insert_position(
    cur, deployment_id: int, user_id: int, mode: str, ticker: str, side: str, qty: int, entry_price: float,
    entry_fee: float, market_close_time: datetime, order_ref: Optional[str] = None,
) -> int:
    cur.execute(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
             market_close_time, opened_at, status, order_ref)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s)""",
        (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
         market_close_time.astimezone(timezone.utc).replace(tzinfo=None) if market_close_time.tzinfo else market_close_time,
         now_utc(), order_ref),
    )
    return cur.lastrowid


def close_position(cur, position_id: int, exit_price: float, exit_fee: float, pnl: float, reason: str) -> bool:
    """Idempotent: only an open position closes, so a retried tick cannot
    book the same exit twice."""
    cur.execute(
        """UPDATE app_positions SET status='closed', exit_price=%s, exit_fee=%s, pnl=%s, close_reason=%s, closed_at=%s
           WHERE id=%s AND status='open'""",
        (exit_price, exit_fee, round(pnl, 4), reason, now_utc(), position_id),
    )
    return cur.rowcount == 1


def book_partial_exit(cur, pos: Dict, fill_qty: int, exit_price: float, exit_fee: float, pnl: float,
                      reason: str) -> bool:
    """Record a PARTIAL exit fill: shrink the open position to the un-filled remainder and book the
    `fill_qty` sold contracts as their own closed position row (so the realized P&L is counted by the
    loss/drawdown guards and settlement never re-counts the sold contracts). The open row's entry fee
    is split pro-rata with the sold slice.

    Reduce-then-book ordering + the `status='open'` guard make it idempotent and crash-safe: a retried
    tick reads the already-shrunk qty, and a crash between the two statements can only LEAVE a slice
    un-booked, never DOUBLE-count or re-sell. MUST run inside a transaction (see repo.transaction) so
    the two statements commit together. Returns False (books nothing) if the row is no longer open."""
    total_qty = int(pos["qty"])
    fill_qty = int(fill_qty)
    if not 0 < fill_qty < total_qty:
        raise ValueError("partial fill must be between 1 and qty-1, got %d of %d" % (fill_qty, total_qty))
    entry_fee = float(pos["entry_fee"])
    filled_entry_fee = round(entry_fee * fill_qty / total_qty, 4)
    cur.execute(
        "UPDATE app_positions SET qty=%s, entry_fee=%s WHERE id=%s AND status='open'",
        (total_qty - fill_qty, round(entry_fee - filled_entry_fee, 4), pos["id"]),
    )
    if cur.rowcount != 1:
        return False  # already closed/shrunk by another tick — book nothing (idempotent)
    cur.execute(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price,
             entry_fee, market_close_time, opened_at, status, exit_price, exit_fee, pnl, close_reason,
             closed_at, order_ref)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'closed',%s,%s,%s,%s,%s,%s)""",
        (pos["deployment_id"], pos["user_id"], pos["mode"], pos["ticker"], pos["side"], fill_qty,
         pos["entry_price"], filled_entry_fee, pos["market_close_time"], pos["opened_at"],
         exit_price, exit_fee, round(pnl, 4), reason, now_utc(), pos.get("order_ref")),
    )
    return True


def insert_closed_position(
    cur, deployment_id: int, user_id: int, mode: str, ticker: str, side: str, qty: int,
    entry_price: float, entry_fee: float, exit_price: float, exit_fee: float, pnl: float,
    reason: str, market_close_time: datetime, order_ref: Optional[str] = None,
) -> int:
    """Record a round-trip (bought then immediately sold again) as a single CLOSED position row.

    ONE atomic INSERT, so an autocommit connection can never leave a phantom OPEN leg if it dies
    mid-write (an open-then-close pair of statements could). Used by the cross-pair unwind: the
    excess leg that was flattened on the exchange must count toward realized P&L (the loss and
    drawdown guards sum closed-row pnl) without ever becoming a held position."""
    close = (market_close_time.astimezone(timezone.utc).replace(tzinfo=None)
             if market_close_time.tzinfo else market_close_time)
    cur.execute(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price,
             entry_fee, market_close_time, opened_at, status, exit_price, exit_fee, pnl, close_reason,
             closed_at, order_ref)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'closed',%s,%s,%s,%s,%s,%s)""",
        (deployment_id, user_id, mode, ticker, side, qty, entry_price, round(entry_fee, 4), close,
         now_utc(), exit_price, round(exit_fee, 4), round(pnl, 4), reason, now_utc(), order_ref),
    )
    return cur.lastrowid


# -- live position reconciliation ----------------------------------------------
# All DB access for app/reconcile.py lives here (repository layer), so the
# reconcile/classify logic stays testable against a fake cursor.


# How long after a user's last live close they are still reconciled. A sell booked
# against a position Kalshi no longer held leaves the book FLAT and the account
# SHORT - the 2026-09-27 failure - so "has open positions" alone would skip
# exactly the account that most needs checking.
RECONCILE_RECENT_DAYS = 3


def users_to_reconcile(cur) -> List[int]:
    """Every user with a live Kalshi key whose book could diverge from the
    exchange: an open live position, a live close in the last few days, or a
    discrepancy that is still open (so it can resolve and lift its halt)."""
    since = now_utc() - timedelta(days=RECONCILE_RECENT_DAYS)
    cur.execute(
        """SELECT DISTINCT k.user_id FROM app_kalshi_keys k
           WHERE EXISTS (SELECT 1 FROM app_positions p WHERE p.user_id=k.user_id AND p.mode='live'
                           AND (p.status='open' OR p.closed_at >= %s))
              OR EXISTS (SELECT 1 FROM app_position_reconcile r
                           WHERE r.user_id=k.user_id AND r.status='open')
           ORDER BY k.user_id""",
        (since,),
    )
    return [int(r["user_id"]) for r in cur.fetchall()]


def legacy_live_book_rows(cur) -> List[Dict]:
    """The legacy engine's open positions (live_positions, YES only), shaped like
    live_book_by_ticker_side rows. They sit on the operator's Kalshi account, so
    reconciling that account without them reads every one as untracked."""
    cur.execute(
        "SELECT market_ticker AS ticker, 'yes' AS side, COALESCE(SUM(qty_contracts),0) AS qty "
        "FROM live_positions GROUP BY market_ticker"
    )
    return cur.fetchall()


def live_book_by_ticker_side(cur, user_id: int) -> List[Dict]:
    """This user's open LIVE positions, summed by (ticker, side). The caller folds
    these into a signed net per ticker (YES positive, NO negative)."""
    cur.execute(
        """SELECT ticker, side, COALESCE(SUM(qty),0) AS qty FROM app_positions
           WHERE user_id=%s AND mode='live' AND status='open'
           GROUP BY ticker, side""",
        (user_id,),
    )
    return cur.fetchall()


def get_position(cur, position_id: int) -> Optional[Dict]:
    """One position row by id (used by crash-recovery to book/close an intent's own position)."""
    cur.execute("SELECT * FROM app_positions WHERE id=%s", (position_id,))
    return cur.fetchone()


# -- durable order-intent log (EXECUTION_RISK_HARDENING P0-1) -------------------
# A row is written and COMMITTED before every real exchange order and updated after, so every
# order has a durable, idempotent identity. client_order_id == intent_id, reused on any retry.


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def insert_order_intent(
    cur, intent_id: str, deployment_id: int, user_id: int, mode: str, action: str, side: str,
    ticker: str, qty: int, limit_price: float, client_order_id: str, position_id: Optional[int] = None,
    reason: Optional[str] = None, market_close_time: Optional[datetime] = None,
) -> None:
    """Record an order intent as 'sent' BEFORE the exchange POST. The caller commits this (its own
    transaction) so the intent is durable even if the process dies the instant after the order is
    placed — recovery then reconciles it against the exchange."""
    now = now_utc()
    cur.execute(
        """INSERT INTO app_order_intents
             (intent_id, deployment_id, user_id, position_id, mode, action, side, ticker, qty,
              limit_price, client_order_id, status, reason, market_close_time, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'sent',%s,%s,%s,%s)""",
        (intent_id, deployment_id, user_id, position_id, mode, action, side, ticker, int(qty),
         limit_price, client_order_id, reason, _naive_utc(market_close_time), now, now),
    )


def mark_order_intent(
    cur, intent_id: str, status: str, external_order_id: Optional[str] = None, fill_qty: Optional[int] = None,
    fill_price: Optional[float] = None, fee: Optional[float] = None, raw_json: Optional[dict] = None,
) -> bool:
    """Update an intent's status/outcome (e.g. 'unfilled', 'error'). Fill fields are only overwritten
    when provided (COALESCE), so a status-only update keeps whatever was recorded."""
    cur.execute(
        """UPDATE app_order_intents
             SET status=%s, external_order_id=COALESCE(%s,external_order_id), fill_qty=COALESCE(%s,fill_qty),
                 fill_price=COALESCE(%s,fill_price), fee=COALESCE(%s,fee), raw_json=COALESCE(%s,raw_json),
                 updated_at=%s
           WHERE intent_id=%s""",
        (status, external_order_id, fill_qty, fill_price, fee, _json(raw_json), now_utc(), intent_id),
    )
    return cur.rowcount == 1


def claim_intent_booking(
    cur, intent_id: str, external_order_id: Optional[str] = None, fill_qty: Optional[int] = None,
    fill_price: Optional[float] = None, fee: Optional[float] = None, raw_json: Optional[dict] = None,
) -> bool:
    """Atomically transition an intent to 'booked' (recording the fill), only if it is not ALREADY
    booked. Returns True iff THIS caller won the transition — the single-booking guard that makes the
    live path and crash-recovery race-safe: whoever books first wins, the loser books nothing. Must
    run inside the same transaction as the position/ledger write it guards (see repo.transaction)."""
    cur.execute(
        """UPDATE app_order_intents
             SET status='booked', external_order_id=COALESCE(%s,external_order_id), fill_qty=COALESCE(%s,fill_qty),
                 fill_price=COALESCE(%s,fill_price), fee=COALESCE(%s,fee), raw_json=COALESCE(%s,raw_json),
                 updated_at=%s
           WHERE intent_id=%s AND status<>'booked'""",
        (external_order_id, fill_qty, fill_price, fee, _json(raw_json), now_utc(), intent_id),
    )
    return cur.rowcount == 1


def open_sent_intents(cur, older_than_seconds: int = 30, limit: int = 200) -> List[Dict]:
    """Intents still 'sent' (POST issued, outcome unknown) older than a grace window — the
    unresolved in-flight orders a crash/lost-response can leave (the F1/F2 smoke alarm)."""
    cutoff = now_utc() - timedelta(seconds=int(older_than_seconds))
    cur.execute(
        "SELECT * FROM app_order_intents WHERE status='sent' AND created_at <= %s ORDER BY created_at LIMIT %s",
        (cutoff, int(limit)),
    )
    return cur.fetchall()


def ticker_has_inflight_intent(cur, user_id: int, ticker: str, within_seconds: int) -> bool:
    """True when this user has an order on ``ticker`` still 'sent' (outcome unknown) from the last
    ``within_seconds``. The exchange position is per account, so this spans every deployment."""
    cutoff = now_utc() - timedelta(seconds=int(within_seconds))
    cur.execute(
        "SELECT 1 AS x FROM app_order_intents WHERE user_id=%s AND ticker=%s AND status='sent' "
        "AND created_at >= %s LIMIT 1",
        (int(user_id), ticker, cutoff),
    )
    return cur.fetchone() is not None


def order_intents_between(cur, since: datetime, until: Optional[datetime] = None,
                          modes=("live", "demo")) -> List[Dict]:
    """Real-order intents (live/demo) created in [since, until), oldest first, for TCA."""
    until = until or now_utc()
    marks = ",".join(["%s"] * len(modes))
    cur.execute(
        "SELECT * FROM app_order_intents WHERE created_at >= %s AND created_at < %s "
        "AND mode IN (" + marks + ") ORDER BY created_at",
        (_naive_utc(since), _naive_utc(until), *modes),
    )
    return cur.fetchall()


def yes_quote_at(cur, ticker: str, ts: datetime, max_lag_seconds: int = 30) -> Optional[Dict]:
    """The first recorded YES top-of-book for ``ticker`` at or after ``ts`` (within ``max_lag_seconds``):
    the websocket tick table first, the REST snapshot table as the fallback. None if neither has one."""
    start = _naive_utc(ts)
    end = start + timedelta(seconds=int(max_lag_seconds))
    for sql in (
        "SELECT yes_bid_dollars, yes_ask_dollars, observed_at_utc AS at FROM forward_quote_ticks "
        "WHERE market_ticker=%s AND observed_at_utc >= %s AND observed_at_utc < %s "
        "ORDER BY observed_at_utc LIMIT 1",
        "SELECT yes_bid_dollars, yes_ask_dollars, snapshot_time_utc AS at FROM forward_quotes "
        "WHERE market_ticker=%s AND snapshot_time_utc >= %s AND snapshot_time_utc < %s "
        "ORDER BY snapshot_time_utc LIMIT 1",
    ):
        cur.execute(sql, (ticker, start, end))
        row = cur.fetchone()
        if row and row.get("yes_bid_dollars") is not None and row.get("yes_ask_dollars") is not None:
            return {"yes_bid": float(row["yes_bid_dollars"]), "yes_ask": float(row["yes_ask_dollars"]), "at": row["at"]}
    return None


# -- execution latency / observability (Execution P2) --------------------------


def insert_order_latency(
    cur, mode: str, ticker: str, action: str, side: str, qty: int, fill_qty: int,
    encode_sign_ms: Optional[float], roundtrip_ms: Optional[float], total_ms: float,
    http_status: Optional[int], outcome: str,
) -> None:
    """One row per real exchange POST (live & demo). Written off the send path by the background
    recorder — no secrets, no order body. Pure observability."""
    cur.execute(
        """INSERT INTO app_order_latency
             (mode, ticker, action, side, qty, fill_qty, encode_sign_ms, roundtrip_ms, total_ms,
              http_status, outcome, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (mode, ticker, action, side, int(qty), int(fill_qty), encode_sign_ms, roundtrip_ms,
         float(total_ms), http_status, outcome, now_utc()),
    )


def _pct(values: List[float], q: float) -> Optional[float]:
    """Nearest-rank percentile of a list (q in 0..1). None for an empty list. Stdlib only —
    ponytail: the window holds tens/hundreds of orders, no numpy needed."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return round(s[k], 2)


def order_latency_stats(cur, window_seconds: int = 3600, mode: Optional[str] = None) -> Dict:
    """Lag + error observability over a trailing window: p50/p95/p99 of round-trip and total
    latency, the encode+sign cost, error/fill rates by outcome, and feed/mark staleness (from the
    marks the engine stamps from the same live book orders are priced against). All read-only."""
    cutoff = now_utc() - timedelta(seconds=int(window_seconds))
    where = "created_at >= %s" + ("" if mode is None else " AND mode=%s")
    args = (cutoff,) if mode is None else (cutoff, mode)
    cur.execute(
        "SELECT outcome, roundtrip_ms, total_ms, encode_sign_ms FROM app_order_latency WHERE " + where,
        args,
    )
    rows = cur.fetchall()
    rt = [float(r["roundtrip_ms"]) for r in rows if r["roundtrip_ms"] is not None]
    tot = [float(r["total_ms"]) for r in rows if r["total_ms"] is not None]
    sign = [float(r["encode_sign_ms"]) for r in rows if r["encode_sign_ms"] is not None]
    by_outcome: Dict[str, int] = {}
    for r in rows:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    n = len(rows)
    errors = by_outcome.get("error", 0)
    filled = by_outcome.get("filled", 0) + by_outcome.get("partial", 0)

    # Feed/mark staleness: how old are the live marks the engine stamps each tick (same book the
    # kernel prices orders from), so a lagging feed shows up here as rising mark age.
    cur.execute(
        "SELECT TIMESTAMPDIFF(SECOND, mark_ts, UTC_TIMESTAMP()) AS age FROM app_positions "
        "WHERE status='open' AND mark_ts IS NOT NULL"
    )
    ages = [float(r["age"]) for r in cur.fetchall() if r["age"] is not None]

    return {
        "window_seconds": int(window_seconds),
        "mode": mode or "all",
        "orders": {
            "count": n,
            "errors": errors,
            "error_rate": round(errors / n, 4) if n else 0.0,
            "fill_rate": round(filled / n, 4) if n else 0.0,
            "by_outcome": by_outcome,
        },
        "roundtrip_ms": {"p50": _pct(rt, 0.50), "p95": _pct(rt, 0.95), "p99": _pct(rt, 0.99),
                         "max": round(max(rt), 2) if rt else None},
        "total_ms": {"p50": _pct(tot, 0.50), "p95": _pct(tot, 0.95), "p99": _pct(tot, 0.99)},
        "encode_sign_ms": {"p50": _pct(sign, 0.50), "p95": _pct(sign, 0.95)},
        "feed_staleness_s": {"p50": _pct(ages, 0.50), "p95": _pct(ages, 0.95),
                             "max": round(max(ages), 2) if ages else None, "open_marks": len(ages)},
    }


def open_reconcile_rows(cur, user_id: int) -> List[Dict]:
    cur.execute(
        "SELECT ticker, kind, exchange_qty, book_qty, detected_at, updated_at FROM app_position_reconcile "
        "WHERE user_id=%s AND status='open'",
        (user_id,),
    )
    return cur.fetchall()


def live_entry_halts(cur, user_id: int) -> List[Dict]:
    """Open discrepancies that have survived at least one later sweep
    (updated_at moved past detected_at). While any exist, the engine opens no new
    LIVE position for this user. One sighting is not enough: a fill booked a beat
    after the sweep, or a settlement Kalshi zeroes before we book it, looks like
    a mismatch exactly once. The row resolving lifts the halt by itself."""
    cur.execute(
        "SELECT ticker, kind, exchange_qty, book_qty FROM app_position_reconcile "
        "WHERE user_id=%s AND status='open' AND updated_at > detected_at ORDER BY ticker",
        (user_id,),
    )
    return cur.fetchall()


def upsert_reconcile(cur, user_id: int, ticker: str, kind: str, exchange_qty: int, book_qty: int) -> None:
    """Record (or refresh) an open discrepancy. detected_at is preserved on an
    existing open row so the audit shows when the divergence first appeared; a row
    that had been marked resolved reopens with a fresh detected_at."""
    now = now_utc()
    cur.execute(
        """INSERT INTO app_position_reconcile
             (user_id, ticker, kind, exchange_qty, book_qty, status, detected_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,'open',%s,%s)
           ON DUPLICATE KEY UPDATE
             kind=VALUES(kind), exchange_qty=VALUES(exchange_qty), book_qty=VALUES(book_qty),
             updated_at=VALUES(updated_at),
             detected_at=IF(status='open', detected_at, VALUES(detected_at)),
             status='open', resolved_at=NULL""",
        (user_id, ticker, kind, int(exchange_qty), int(book_qty), now, now),
    )


def resolve_reconcile_except(cur, user_id: int, active_tickers: List[str]) -> int:
    """Mark resolved any still-open discrepancy for this user whose ticker is no
    longer divergent. Empty active set resolves them all."""
    if active_tickers:
        placeholders = ",".join(["%s"] * len(active_tickers))
        sql = ("UPDATE app_position_reconcile SET status='resolved', resolved_at=%s, updated_at=%s "
               "WHERE user_id=%s AND status='open' AND ticker NOT IN (" + placeholders + ")")
        params = [now_utc(), now_utc(), user_id, *active_tickers]
    else:
        sql = ("UPDATE app_position_reconcile SET status='resolved', resolved_at=%s, updated_at=%s "
               "WHERE user_id=%s AND status='open'")
        params = [now_utc(), now_utc(), user_id]
    cur.execute(sql, params)
    return cur.rowcount


def reconcile_deployment_id(cur, user_id: int, market: str) -> int:
    """The user's dedicated, PAUSED reconciliation deployment for `market`, created
    once on demand. Adopted orphans are booked under it so they appear in the user's
    positions and settle at expiry. It is paused (not running) deliberately: the
    engine's decision loop only trades running deployments, so an adopted orphan is
    never acted on by a synthetic spec — adoption records a row, nothing more."""
    cur.execute(
        """SELECT d.id FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.user_id=%s AND d.market=%s AND s.direction='reconcile' LIMIT 1""",
        (user_id, market),
    )
    row = cur.fetchone()
    if row:
        return int(row["id"])
    now = now_utc()
    spec = {"sizing": {"stake": 0.0, "max_positions": 0}, "rules": {}}
    cur.execute(
        """INSERT INTO app_strategies
             (user_id, market, direction, title, thesis, spec_json, status, created_at)
           VALUES (%s,%s,'reconcile',%s,%s,%s,'archived',%s)""",
        (user_id, market, "Reconciliation holdings",
         "System container for adopted untracked exchange positions. Not a tradable strategy.",
         _json(spec), now),
    )
    strategy_id = cur.lastrowid
    cur.execute(
        """INSERT INTO app_deployments (user_id, strategy_id, market, mode, status, status_reason, created_at, updated_at)
           VALUES (%s,%s,%s,'live','paused','Reconciliation container (adopted orphans)',%s,%s)""",
        (user_id, strategy_id, market, now, now),
    )
    return cur.lastrowid


def claim_position_close(cur, position_id: int, claimant: str, lease_seconds: int = 300) -> bool:
    """Single-actor guard for the order-PLACING risk sweeps (drawdown force-sell): at most one engine
    may send a real close for a given open position within the lease, so two engines can never both
    sell it into an unintended short. Mirrors claim_decision. The owner can re-claim its own lease
    (so a failed close retries next tick); a different engine only after the lease expires."""
    cutoff = now_utc() - timedelta(seconds=int(lease_seconds))
    cur.execute(
        """UPDATE app_positions SET close_claim=%s, close_claim_ts=%s
           WHERE id=%s AND status='open' AND (close_claim IS NULL OR close_claim=%s OR close_claim_ts < %s)""",
        (claimant, now_utc(), position_id, claimant, cutoff),
    )
    return cur.rowcount == 1


def realized_pnl(cur, user_id: int, mode: str, since: Optional[datetime] = None) -> float:
    sql = "SELECT COALESCE(SUM(pnl),0) AS p FROM app_positions WHERE user_id=%s AND mode=%s AND status='closed'"
    params: List[Any] = [user_id, mode]
    if since is not None:
        sql += " AND closed_at >= %s"
        params.append(since)
    cur.execute(sql, params)
    return float(cur.fetchone()["p"])


def user_risk_config(cur, user_id: int) -> Dict:
    """Per-user risk limits for the force-sell / portfolio-cap layer (conservative DB defaults)."""
    cur.execute(
        "SELECT drawdown_limit_pct, position_stop_pct, max_open_positions, max_open_notional "
        "FROM app_users WHERE id=%s",
        (user_id,),
    )
    return cur.fetchone()


def set_user_risk_config(cur, user_id: int, changes: Dict) -> None:
    """Update a user's risk controls. Only the three enforced columns are writable; callers
    (agent.act) pass already-clamped values, so this layer just persists them (DRY: one UPDATE,
    no business logic). Unknown keys are ignored so a bad agent action can't touch other columns."""
    cols = {k: changes[k] for k in ("drawdown_limit_pct", "max_open_positions", "max_open_notional") if k in changes}
    if not cols:
        return
    sql = "UPDATE app_users SET " + ", ".join("%s=%%s" % k for k in cols) + " WHERE id=%s"
    cur.execute(sql, [*cols.values(), user_id])


PLAN_KEYS = ("goals", "agenda", "deployments", "posture")
_PLAN_FIELD_MAX = 800   # chars per field; keeps the plan a bounded briefing, not a growing journal


def autopilot_plan(cur, user_id: int) -> Dict:
    """The autopilot's durable operating plan (goals/agenda/deployments/posture), or {} if none yet.
    Read by _copilot_context each review so reviews are coherent across time."""
    cur.execute("SELECT autopilot_plan FROM app_users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    plan = _loads((row or {}).get("autopilot_plan")) if row else None
    return plan if isinstance(plan, dict) else {}


def set_autopilot_plan(cur, user_id: int, plan: Dict) -> None:
    """Persist the review's updated operating plan. Only the four known string fields are kept and
    each is truncated, so the stored plan stays a small bounded briefing no matter what the model
    emits (a bad/huge value can't bloat the row or leak other keys)."""
    if not isinstance(plan, dict):
        return
    kept = {k: str(plan[k])[:_PLAN_FIELD_MAX] for k in PLAN_KEYS if plan.get(k)}
    cur.execute("UPDATE app_users SET autopilot_plan=%s WHERE id=%s", (_json(kept) if kept else None, user_id))


def set_autopilot_model(cur, user_id: int, model_key: Optional[str]) -> None:
    """Set the model the autopilot's own runs use (NULL = catalog default). The caller validates
    model_key against models_catalog so only a known key (or None) is ever stored."""
    cur.execute("UPDATE app_users SET autopilot_model=%s WHERE id=%s", (model_key or None, user_id))


def user_execution_config(cur, user_id: int) -> Dict:
    """Per-user execution-control overrides (NULL = use the global KALSHI_MAX_* env default).
    The live kernel factory reads this and falls back to env when a column is NULL."""
    cur.execute(
        "SELECT exec_max_book_fraction, exec_max_entry_spread, exec_max_order_notional FROM app_users WHERE id=%s",
        (user_id,),
    )
    return cur.fetchone() or {}


def set_user_execution_config(cur, user_id: int, changes: Dict) -> None:
    """Persist already-clamped per-user execution overrides (agent.act clamps to EXEC_BOUNDS)."""
    cols = {k: changes[k] for k in ("exec_max_book_fraction", "exec_max_entry_spread", "exec_max_order_notional") if k in changes}
    if not cols:
        return
    sql = "UPDATE app_users SET " + ", ".join("%s=%%s" % k for k in cols) + " WHERE id=%s"
    cur.execute(sql, [*cols.values(), user_id])


def user_open_exposure(cur, user_id: int) -> Dict:
    """Live, cross-deployment open exposure for the per-user portfolio caps: how many open
    positions the user holds and their total entry notional (qty * entry_price), in dollars."""
    cur.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(qty*entry_price),0) AS notional "
        "FROM app_positions WHERE user_id=%s AND status='open'",
        (user_id,),
    )
    return cur.fetchone()


def daily_pnl(cur, user_id: int, mode: str, days: int = 60) -> List[Dict]:
    cur.execute(
        """SELECT DATE(closed_at) AS d, SUM(pnl) AS pnl FROM app_positions
           WHERE user_id=%s AND mode=%s AND status='closed' AND closed_at >= %s
           GROUP BY DATE(closed_at) ORDER BY d""",
        (user_id, mode, now_utc() - timedelta(days=days)),
    )
    return cur.fetchall()


# -- chat & proposals ----------------------------------------------------------


def last_autopilot_action(cur, user_id: int) -> Optional[Dict]:
    """Most recent agent/system line about autopilot, for the floating status window."""
    cur.execute(
        """SELECT content, created_at FROM app_chat_messages
           WHERE user_id=%s AND role='system'
                 AND (content LIKE '%%utopilot%%' OR content LIKE '%%LIVE%%' OR content LIKE '%%Kill%%')
           ORDER BY id DESC LIMIT 1""",
        (user_id,),
    )
    r = cur.fetchone()
    return {"text": r["content"], "at": r["created_at"]} if r else None


def last_review_at(cur, user_id: int):
    """Timestamp of the most recent autopilot REVIEW run (whether or not it acted), for the panel's
    liveness readout. A quiet review takes no action and posts nothing, so without this a working
    autopilot looks dead between actions; this shows it is alive and on cadence."""
    cur.execute(
        "SELECT created_at FROM app_agent_runs WHERE user_id=%s AND kind='review' ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    r = cur.fetchone()
    return r["created_at"] if r else None


def add_chat(cur, user_id: int, role: str, content: str, proposal_id: Optional[int] = None) -> int:
    cur.execute(
        "INSERT INTO app_chat_messages (user_id, role, content, proposal_id, created_at) VALUES (%s,%s,%s,%s,%s)",
        (user_id, role, content, proposal_id, now_utc()),
    )
    return cur.lastrowid


def chat_contains(cur, user_id: int, role: str, needle: str) -> bool:
    """True if the user already has a chat line of `role` containing `needle` (a one-time marker)."""
    cur.execute("SELECT 1 FROM app_chat_messages WHERE user_id=%s AND role=%s AND content LIKE %s LIMIT 1",
                (user_id, role, "%" + needle + "%"))
    return cur.fetchone() is not None


def chat_messages(cur, user_id: int, after_id: int = 0, limit: int = 100) -> List[Dict]:
    cur.execute(
        """SELECT m.id, m.role, m.content, m.created_at, m.proposal_id,
                  p.kind AS proposal_kind, p.status AS proposal_status, p.deployment_id, p.strategy_id
           FROM app_chat_messages m LEFT JOIN app_proposals p ON p.id=m.proposal_id
           WHERE m.user_id=%s AND m.id>%s ORDER BY m.id DESC LIMIT %s""",
        (user_id, after_id, limit),
    )
    return list(reversed(cur.fetchall()))


def create_proposal(
    cur, user_id: int, kind: str, reason: str, deployment_id: Optional[int] = None,
    strategy_id: Optional[int] = None, status: str = "pending", payload: Optional[Dict] = None,
) -> int:
    cur.execute(
        """INSERT INTO app_proposals (user_id, kind, deployment_id, strategy_id, reason, status, payload, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (user_id, kind, deployment_id, strategy_id, reason, status, _json(payload), now_utc()),
    )
    return cur.lastrowid


def get_proposal(cur, user_id: int, proposal_id: int) -> Optional[Dict]:
    cur.execute("SELECT * FROM app_proposals WHERE id=%s AND user_id=%s", (proposal_id, user_id))
    p = cur.fetchone()
    if p is not None and "payload" in p:
        p["payload"] = _loads(p["payload"])
    return p


def decide_proposal(cur, proposal_id: int, status: str) -> bool:
    cur.execute(
        "UPDATE app_proposals SET status=%s, decided_at=%s WHERE id=%s AND status='pending'",
        (status, now_utc(), proposal_id),
    )
    return cur.rowcount == 1


# -- dataset ---------------------------------------------------------------------


def _stream_rows(cur, sql: str, params) -> Iterator:
    """Rows one at a time from an unbuffered server-side cursor, so a multi-million-row
    read is never materialised as a list of dicts (a 1-minute sports series is ~1.6M
    candles: ~1GB as dicts of Decimals, the agents worker's OOM on 2026-10-24). Falls back
    to an ordinary execute/fetchall on cursors without a pymysql connection (test fakes)."""
    conn = getattr(cur, "connection", None)
    if conn is None or not hasattr(conn, "cursor"):
        cur.execute(sql, params)
        yield from cur.fetchall()
        return
    import pymysql

    ss = conn.cursor(pymysql.cursors.SSCursor)
    try:
        ss.execute(sql, params)
        yield from ss
    finally:
        ss.close()


def _num(v) -> Optional[float]:
    return float(v) if v is not None else None


def load_history(cur, series: str, candle_minutes: int, since: datetime,
                 underlying: str = "BTC-USD", tickers: Optional[set] = None) -> Dict[str, List]:
    """markets as dicts; candles as compact (ticker, end_period_ts, bid, ask) tuples.
    `tickers` keeps only those contracts' candles and microstructure (a partition window),
    so rows for contracts outside it are dropped as they stream instead of held."""
    cur.execute(
        """SELECT ticker, strike, close_time, result FROM hist_markets
           WHERE series_ticker=%s AND close_time >= %s AND candles_done=1""",
        (series, since),
    )
    markets = cur.fetchall()
    if tickers is not None:
        markets = [m for m in markets if m["ticker"] in tickers]
    names = {m["ticker"]: m["ticker"] for m in markets}  # one shared str per ticker, not one per row
    candles = []
    for r in _stream_rows(
        cur,
        """SELECT c.ticker, c.end_period_ts, c.yes_bid_close, c.yes_ask_close
           FROM market_candles c JOIN hist_markets h ON h.ticker=c.ticker
           WHERE h.series_ticker=%s AND h.close_time >= %s AND h.candles_done=1
             AND c.period_interval_minutes=%s""",
        (series, since, candle_minutes),
    ):
        if isinstance(r, dict):
            r = (r["ticker"], r["end_period_ts"], r["yes_bid_close"], r["yes_ask_close"])
        name = names.get(r[0])
        if name is None:
            continue
        candles.append((name, int(r[1]), _num(r[2]), _num(r[3])))
    start_ts = int(since.replace(tzinfo=timezone.utc).timestamp()) - 2 * 86400
    # The underlying price path for THIS market's series (BTC-USD, ETH-USD, …).
    cur.execute(
        "SELECT start_ts, close FROM spot_candles_1m WHERE symbol=%s AND start_ts >= %s ORDER BY start_ts",
        (underlying, start_ts),
    )
    btc = [(int(r["start_ts"]), float(r["close"])) for r in cur.fetchall()]
    return {"markets": markets, "candles": candles, "btc": btc,
            "micro": _load_micro(cur, series, since, tickers)}


_MICRO_COLS_TTL = 600.0
_micro_cols_cache: Dict[str, Any] = {"at": 0.0, "fields": None}


def _micro_select(cur, prefix: str = "") -> Tuple[str, List[str]]:
    """The MICRO_FEATURES select list restricted to columns that exist in model_features_1m now,
    plus their names. A feature is added to MICRO_FEATURES before (or without) its migration on
    some box; selecting a missing column would fail the whole query, and both loaders treat a
    failure as "no micro at all", silently dropping every order-book feature from research and
    live alike. Columns are re-read every _MICRO_COLS_TTL seconds; if they can't be read, all of
    MICRO_FEATURES is used, as before."""
    import time as _time
    from app.markets import MICRO_FEATURES
    fields = _micro_cols_cache["fields"]
    if fields is None or _time.time() - _micro_cols_cache["at"] > _MICRO_COLS_TTL:
        try:
            cur.execute("SHOW COLUMNS FROM model_features_1m")
            rows = cur.fetchall() or []
            got = {r.get("Field") for r in rows if isinstance(r, dict)} - {None}
        except Exception:  # noqa: BLE001 - unreadable schema: fall back to the full list
            got = set()
        fields = got or None
        if fields:
            _micro_cols_cache.update(at=_time.time(), fields=fields)
    items = [(n, c) for n, (c, _d) in MICRO_FEATURES.items() if fields is None or c in fields]
    return ", ".join("%s%s AS %s" % (prefix, c, n) for n, c in items), [n for n, _c in items]


def _load_micro(cur, series: str, since: datetime,
                tickers: Optional[set] = None) -> Dict[tuple, Dict[str, Any]]:
    """Collected order-book/microstructure features for this series' contracts since
    `since`, keyed (ticker, minute_unix_ts) so build_dataset can join them onto the
    matching contract snapshot. Columns are aliased to their MICRO_FEATURES names; a
    missing table just yields no rows (older DBs that predate the feature builder)."""
    cols, names = _micro_select(cur, "f.")
    if not names:
        return {}
    try:
        cur.execute(
            "SELECT f.market_ticker, f.snapshot_minute_utc, " + cols +
            """ FROM model_features_1m f JOIN hist_markets h ON h.ticker=f.market_ticker
               WHERE h.series_ticker=%s AND h.close_time >= %s AND h.candles_done=1
                 AND f.snapshot_minute_utc >= %s""",
            (series, since, since),
        )
    except Exception:  # noqa: BLE001 - table absent on legacy DBs; micro is optional
        return {}
    out: Dict[tuple, Dict[str, Any]] = {}
    for r in cur.fetchall():
        if tickers is not None and r["market_ticker"] not in tickers:
            continue
        dt = r["snapshot_minute_utc"]
        ts = int(dt.replace(tzinfo=timezone.utc).timestamp()) if dt.tzinfo is None else int(dt.timestamp())
        out[(r["market_ticker"], ts)] = {n: r[n] for n in names if r.get(n) is not None}
    return out


def latest_micro(cur, tickers, as_of_ts: int, max_age_seconds: int = 120) -> Dict[str, Dict[str, Any]]:
    """The live counterpart of _load_micro: per ticker, the newest model_features_1m row at or
    before ``as_of_ts`` and no older than ``max_age_seconds``, aliased to MICRO_FEATURES names.
    A ticker with no fresh row is absent, exactly as a missing row leaves research's snapshot
    without the features (and a filter on one then never matches)."""
    tickers = sorted({t for t in tickers if t})
    if not tickers:
        return {}
    as_of = datetime.fromtimestamp(int(as_of_ts), tz=timezone.utc).replace(tzinfo=None)
    cols, names = _micro_select(cur)
    if not names:
        return {}
    cur.execute(
        "SELECT market_ticker, snapshot_minute_utc, " + cols + " FROM model_features_1m "
        "WHERE market_ticker IN (" + ",".join(["%s"] * len(tickers)) + ") "
        "AND snapshot_minute_utc <= %s AND snapshot_minute_utc >= %s ORDER BY snapshot_minute_utc",
        tuple(tickers) + (as_of, as_of - timedelta(seconds=int(max_age_seconds))),
    )
    out: Dict[str, Dict[str, Any]] = {}
    for r in cur.fetchall():
        out[r["market_ticker"]] = {n: r[n] for n in names if r.get(n) is not None}  # newest row wins
    return out


def spot_symbols_with_data(cur, symbols) -> set:
    """Which of the given spot symbols already have price candles collected.

    The research-only TAO subnet-alpha markets (kind="spot") carry no feed until
    their taostats collector is keyed, so the research picker must hide them until
    then. This is that gate: a spot market is researchable only if its symbol is in
    the returned set. An empty `symbols` short-circuits to no query and no reveal.
    Kept index-friendly by querying the bounded set of known spot symbols, never a
    full DISTINCT scan of spot_candles_1m (which also holds BTC/ETH/... history)."""
    syms = [s for s in symbols if s]
    if not syms:
        return set()
    placeholders = ",".join(["%s"] * len(syms))
    cur.execute(
        "SELECT DISTINCT symbol FROM spot_candles_1m WHERE symbol IN (" + placeholders + ")",
        tuple(syms),
    )
    return {r["symbol"] for r in cur.fetchall()}


def series_with_candles(cur) -> set:
    """Series tickers that already have collected candle history — i.e. a real backtest
    surface the research agent can actually test against. Used to flag which deployable
    markets are ready to research versus still backfilling, so the picker can show the
    whole universe and mark (never hide) the not-yet-ready ones. One bounded GROUP-BY,
    same shape as history_freshness's."""
    cur.execute("SELECT DISTINCT series_ticker FROM hist_markets WHERE candles_done=1")
    return {r["series_ticker"] for r in cur.fetchall()}


def history_freshness(cur) -> Dict[str, Optional[int]]:
    """Unix seconds of the newest BTC spot candle and newest settled market per series."""
    cur.execute("SELECT MAX(start_ts) AS t FROM spot_candles_1m WHERE symbol='BTC-USD'")
    out = {"btc": (cur.fetchone() or {}).get("t")}
    cur.execute("SELECT series_ticker, MAX(close_time) AS t FROM hist_markets WHERE candles_done=1 GROUP BY series_ticker")
    for r in cur.fetchall():
        out[r["series_ticker"]] = int(r["t"].replace(tzinfo=timezone.utc).timestamp()) if r["t"] else None
    return out


def deployment_curves(cur, user_id: int) -> Dict[int, List[List]]:
    """Cumulative realized P&L per deployment, oldest first, for sparklines."""
    cur.execute(
        """SELECT deployment_id, closed_at, pnl FROM app_positions
           WHERE user_id=%s AND status='closed' ORDER BY closed_at, id""",
        (user_id,),
    )
    out: Dict[int, List[List]] = {}
    totals: Dict[int, float] = {}
    for r in cur.fetchall():
        dep = r["deployment_id"]
        totals[dep] = totals.get(dep, 0.0) + float(r["pnl"])
        out.setdefault(dep, []).append([int(r["closed_at"].replace(tzinfo=timezone.utc).timestamp()), round(totals[dep], 4)])
    return out


def active_run_counts(cur, user_id: int) -> Dict[str, int]:
    cur.execute(
        """SELECT kind, status, COUNT(*) AS n FROM app_agent_runs
           WHERE user_id=%s AND status IN ('queued','running','paused') GROUP BY kind, status""",
        (user_id,),
    )
    out = {"research_running": 0, "research_queued": 0, "chat_active": 0}
    for r in cur.fetchall():
        if r["kind"] == "research":
            # A paused research run is still working for the user (a held worker slot), so it
            # counts under "running" for the at-a-glance busy indicator.
            out["research_running" if r["status"] in ("running", "paused") else "research_queued"] += int(r["n"])
        else:
            out["chat_active"] += int(r["n"])
    return out


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def add_waitlist(cur, email: str, note: Optional[str]) -> bool:
    """Record a waitlist request. Returns True if this is a new email."""
    cur.execute(
        """INSERT INTO app_waitlist (email, note, status, created_at) VALUES (%s,%s,'requested',%s)
           ON DUPLICATE KEY UPDATE note=COALESCE(VALUES(note), note)""",
        (email[:320], (note or None) and note[:500], now_utc()),
    )
    return cur.rowcount == 1  # 1 = inserted, 2 = updated an existing row


def count_waitlist(cur) -> int:
    cur.execute("SELECT COUNT(*) AS n FROM app_waitlist")
    return int(cur.fetchone()["n"])


def recent_waitlist_from(cur, ip_bucket: str, since: datetime) -> int:
    # No per-IP column; rate-limit waitlist globally by recent inserts instead.
    cur.execute("SELECT COUNT(*) AS n FROM app_waitlist WHERE created_at >= %s", (since,))
    return int(cur.fetchone()["n"])


DEMO_IDEA = "Generate a Todd's random walk strategy that walks +0.01 and -0.01 with 50% equal chances"


def seed_demo_session(cur, user_id: int) -> None:
    """A complete, pre-populated demo on every account so the end-to-end flow is
    visible without doing anything: the idea the user would type, the session it
    becomes, the agent log, and the strategies it discovers. The star is a
    coin-flip 'random walk' with no edge. Idempotent per user."""
    import random

    cur.execute("SELECT 1 FROM app_agent_runs WHERE user_id=%s AND kind='research' AND prompt=%s", (user_id, DEMO_IDEA))
    if cur.fetchone():
        return
    now = now_utc()
    started = now - timedelta(minutes=3)
    cur.execute(
        """INSERT INTO app_agent_runs (user_id, kind, market, direction, prompt, status, hypotheses_tried,
             strategies_passed, created_at, started_at, heartbeat_at, finished_at)
           VALUES (%s,'research','btc15m','random_walk',%s,'succeeded',2,0,%s,%s,%s,%s)""",
        (user_id, DEMO_IDEA, started, started, now, now),
    )
    run_id = cur.lastrowid

    def event(kind, message, data=None, at=None):
        cur.execute(
            "INSERT INTO app_agent_events (run_id, kind, message, data_json, created_at) VALUES (%s,%s,%s,%s,%s)",
            (run_id, kind, message, _json(data), at or now),
        )

    rng = random.Random(user_id * 2654435761 & 0xFFFFFFFF)

    def walk(p_up):
        steps, cum, curve, wins = 120, 0.0, [], 0
        base = int((now - timedelta(minutes=steps * 15)).timestamp())
        for i in range(steps):
            step = 0.01 if rng.random() < p_up else -0.01
            cum += step
            wins += step > 0
            curve.append([base + i * 900, round(cum, 4)])
        pnl = round(cum, 2)
        m = {"trades": steps, "win_rate": round(wins / steps, 3), "pnl": pnl, "fees": round(steps * 0.01, 2),
             "roi": round(pnl / 10.0, 4), "profit_factor": 1.0, "max_drawdown": round(abs(min(c[1] for c in curve)), 2),
             "sharpe": None, "avg_edge": 0.0, "days": round(steps * 900 / 86400, 1), "trades_per_day": None}
        return m, curve

    event("step", "Loaded 30 days of Bitcoin 15-minute history: 16,800 decision points.", at=started)
    event("step", "Read the idea: a coin flip with no information. Testing it honestly anyway.", at=started)
    cands = [("Todd's random walk", 0.50,
              "Each step is +1¢ or −1¢ with equal odds — a pure coin flip with no information. "
              "Tested faithfully to show what no edge looks like."),
             ("Todd's random walk, biased coin", 0.52,
              "The same walk, but nudged to land heads 52% of the time to see how thin an edge the fee wall still eats.")]
    for i, (title, p_up, thesis) in enumerate(cands):
        m, curve = walk(p_up)
        event("hypothesis", title, {"thesis": thesis, "in_sample": m, "round": 1}, at=started)
        result = {"capital": 10.0, "demo": True,
                  "dataset": {"start": "2026-09-13T00:00Z", "end": now.strftime("%Y-%m-%dT%H:%MZ"),
                              "out_of_sample_from": datetime.fromtimestamp(curve[60][0], tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")},
                  "in_sample": dict(m), "out_of_sample": dict(m), "equity": curve,
                  "gates": [{"name": "Makes money on unseen data", "value": m["pnl"], "threshold": "> $0", "ok": m["pnl"] > 0},
                            {"name": "Has a real edge, not a coin flip", "value": "coin flip", "threshold": "an actual signal", "ok": False}],
                  "passed": False, "recent_trades": []}
        insert_strategy(cur, user_id, run_id, None, "btc15m", "random_walk", title, thesis,
                        json.loads(json.dumps(_demo_spec())), "rejected", result)
        event("verdict", "VOID — %s: no edge, so nothing to deploy." % title,
              {"title": title, "status": "rejected"}, at=now)
    event("done", "0 of 2 hypotheses passed. Random really does wander nowhere — now describe a real idea.",
          {"passed": 0, "tried": 2}, at=now)


def _demo_spec():
    from app import spec as _spec
    return _spec.DEFAULT_SPEC


# -- community -------------------------------------------------------------------


def store_image(cur, user_id: int, content_type: str, data: bytes) -> int:
    cur.execute(
        "INSERT INTO app_images (user_id, content_type, data, created_at) VALUES (%s,%s,%s,%s)",
        (user_id, content_type, data, now_utc()),
    )
    return cur.lastrowid


def get_image(cur, image_id: int) -> Optional[Dict]:
    cur.execute("SELECT content_type, data FROM app_images WHERE id=%s", (image_id,))
    return cur.fetchone()


def create_post(cur, user_id: int, body: str, kind: str, snapshot: Optional[Dict], image_id: Optional[int] = None) -> int:
    cur.execute(
        "INSERT INTO app_posts (user_id, body, kind, snapshot_json, image_id, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (user_id, body[:2000], kind, _json(snapshot), image_id, now_utc()),
    )
    return cur.lastrowid


def edit_post(cur, post_id: int, user_id: int, body: str) -> bool:
    """Edit own post body, stamping edited_at. Returns False if not the owner."""
    cur.execute(
        "UPDATE app_posts SET body=%s, edited_at=%s WHERE id=%s AND user_id=%s",
        (body[:2000], now_utc(), post_id, user_id),
    )
    return cur.rowcount == 1


def list_posts(cur, viewer_id: int, before_id: int = 0, limit: int = 30, mine_only: bool = False) -> List[Dict]:
    cur.execute(
        """SELECT p.id, p.body, p.kind, p.snapshot_json, p.image_id, p.edited_at, p.likes_count, p.comments_count, p.created_at,
                  u.name, u.username, u.picture_url, (p.user_id = %s) AS mine,
                  EXISTS(SELECT 1 FROM app_post_likes l WHERE l.post_id=p.id AND l.user_id=%s) AS liked
           FROM app_posts p JOIN app_users u ON u.id=p.user_id
           WHERE (%s = 0 OR p.id < %s) AND (%s = 0 OR p.user_id = %s) ORDER BY p.id DESC LIMIT %s""",
        (viewer_id, viewer_id, before_id, before_id, 1 if mine_only else 0, viewer_id, limit),
    )
    rows = cur.fetchall()
    for r in rows:
        r["snapshot"] = _loads(r.pop("snapshot_json"))
        r["mine"] = bool(r["mine"]); r["liked"] = bool(r["liked"])
    by_post = reactions_for(cur, [r["id"] for r in rows], viewer_id)
    for r in rows:
        r["reactions"] = by_post.get(r["id"], [])
    return rows


def reactions_for(cur, post_ids: List[int], viewer_id: int) -> Dict[int, List[Dict]]:
    """Per-post emoji counts (+ whether the viewer added each, + up to 8 reactor
    names and @handles for the hover tooltip), most-used first. The names/handles ride
    along in the feed payload so the tooltip renders from already-loaded data with no
    per-hover round-trip. One grouped query for the whole page of posts (no N+1)."""
    if not post_ids:
        return {}
    marks = ",".join(["%s"] * len(post_ids))
    # SEPARATOR is the unit-separator char (never in a name); SUBSTRING_INDEX caps the list.
    cur.execute(
        "SELECT r.post_id, r.emoji, COUNT(*) AS n, MAX(r.user_id=%s) AS mine, "
        "SUBSTRING_INDEX(GROUP_CONCAT(u.name ORDER BY r.created_at SEPARATOR 0x1f), 0x1f, 8) AS names, "
        "SUBSTRING_INDEX(GROUP_CONCAT(COALESCE(u.username,'') ORDER BY r.created_at SEPARATOR 0x1f), 0x1f, 8) AS handles "
        "FROM app_post_reactions r JOIN app_users u ON u.id=r.user_id "
        "WHERE r.post_id IN (%s) GROUP BY r.post_id, r.emoji "
        "ORDER BY n DESC, r.emoji" % ("%s", marks),
        tuple([viewer_id] + list(post_ids)),
    )
    out: Dict[int, List[Dict]] = {}
    for r in cur.fetchall():
        names = [n for n in (r.get("names") or "").split("\x1f") if n]
        handles = [h for h in (r.get("handles") or "").split("\x1f") if h]
        out.setdefault(r["post_id"], []).append(
            {"emoji": r["emoji"], "count": int(r["n"]), "mine": bool(r["mine"]),
             "names": names, "handles": handles})
    return out


def toggle_reaction(cur, post_id: int, user_id: int, emoji: str) -> bool:
    """Add/remove one emoji reaction. Returns True if now reacted."""
    cur.execute("DELETE FROM app_post_reactions WHERE post_id=%s AND user_id=%s AND emoji=%s", (post_id, user_id, emoji))
    if cur.rowcount:
        return False
    cur.execute("INSERT INTO app_post_reactions (post_id, user_id, emoji, created_at) VALUES (%s,%s,%s,%s)",
                (post_id, user_id, emoji, now_utc()))
    return True


def toggle_like(cur, post_id: int, user_id: int) -> bool:
    """Returns True if now liked, False if unliked. Keeps likes_count in sync."""
    cur.execute("DELETE FROM app_post_likes WHERE post_id=%s AND user_id=%s", (post_id, user_id))
    if cur.rowcount:
        cur.execute("UPDATE app_posts SET likes_count=GREATEST(likes_count-1,0) WHERE id=%s", (post_id,))
        return False
    cur.execute("INSERT INTO app_post_likes (post_id, user_id, created_at) VALUES (%s,%s,%s)", (post_id, user_id, now_utc()))
    cur.execute("UPDATE app_posts SET likes_count=likes_count+1 WHERE id=%s", (post_id,))
    return True


def post_exists(cur, post_id: int) -> bool:
    cur.execute("SELECT 1 FROM app_posts WHERE id=%s", (post_id,))
    return cur.fetchone() is not None


def post_author(cur, post_id: int) -> Optional[Dict]:
    """The post's author (user_id, email, name) plus a short body preview, for
    reply notifications."""
    cur.execute(
        """SELECT p.user_id, u.email, u.name, LEFT(p.body, 140) AS preview
           FROM app_posts p JOIN app_users u ON u.id=p.user_id WHERE p.id=%s""",
        (post_id,),
    )
    return cur.fetchone()


def add_comment(cur, post_id: int, user_id: int, body: str) -> int:
    cur.execute(
        "INSERT INTO app_post_comments (post_id, user_id, body, created_at) VALUES (%s,%s,%s,%s)",
        (post_id, user_id, body[:1000], now_utc()),
    )
    cur.execute("UPDATE app_posts SET comments_count=comments_count+1 WHERE id=%s", (post_id,))
    return cur.lastrowid


def list_comments(cur, post_id: int, limit: int = 100) -> List[Dict]:
    cur.execute(
        """SELECT c.id, c.body, c.created_at, u.name, u.username, u.picture_url
           FROM app_post_comments c JOIN app_users u ON u.id=c.user_id
           WHERE c.post_id=%s ORDER BY c.id LIMIT %s""",
        (post_id, limit),
    )
    return cur.fetchall()


def recent_posts_count(cur, user_id: int, since: datetime) -> int:
    cur.execute("SELECT COUNT(*) AS n FROM app_posts WHERE user_id=%s AND created_at >= %s", (user_id, since))
    return int(cur.fetchone()["n"])


# -- credits & billing -----------------------------------------------------------


def credit_balance(cur, user_id: int) -> float:
    cur.execute("SELECT COALESCE(SUM(amount_usd),0) AS b FROM app_credit_ledger WHERE user_id=%s", (user_id,))
    return float(cur.fetchone()["b"])


def add_credit(cur, user_id: int, kind: str, amount_usd, memo: str,
               stripe_ref: Optional[str] = None, run_id: Optional[int] = None) -> bool:
    """Append a credit ledger row. Returns False if a row with this stripe_ref
    already exists (idempotent replay), True if inserted."""
    try:
        cur.execute(
            """INSERT INTO app_credit_ledger (user_id, kind, amount_usd, memo, stripe_ref, run_id, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (user_id, kind, str(amount_usd), (memo or "")[:255], stripe_ref, run_id, now_utc()),
        )
        return True
    except Exception as e:  # duplicate stripe_ref -> already credited
        if "uq_credit_stripe" in str(e) or "Duplicate" in str(e):
            return False
        raise


def credit_rows(cur, user_id: int, limit: int = 50) -> List[Dict]:
    cur.execute(
        "SELECT kind, amount_usd, memo, created_at FROM app_credit_ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    return cur.fetchall()


def credit_spent_total(cur, user_id: int) -> float:
    cur.execute(
        "SELECT COALESCE(-SUM(amount_usd),0) AS s FROM app_credit_ledger WHERE user_id=%s AND kind='usage'",
        (user_id,),
    )
    return float(cur.fetchone()["s"])


def get_stripe_customer(cur, user_id: int) -> Optional[Dict]:
    cur.execute(
        "SELECT user_id, stripe_customer_id, default_pm_id, auto_reload, reload_amount, reload_threshold "
        "FROM app_stripe_customers WHERE user_id=%s",
        (user_id,),
    )
    return cur.fetchone()


def save_stripe_customer(cur, user_id: int, customer_id: str) -> None:
    cur.execute(
        """INSERT INTO app_stripe_customers (user_id, stripe_customer_id, created_at) VALUES (%s,%s,%s)
           ON DUPLICATE KEY UPDATE stripe_customer_id=VALUES(stripe_customer_id), default_pm_id=NULL""",
        (user_id, customer_id, now_utc()),
    )


def set_default_pm(cur, user_id: int, pm_id: Optional[str]) -> None:
    cur.execute("UPDATE app_stripe_customers SET default_pm_id=%s WHERE user_id=%s", (pm_id, user_id))


def set_auto_reload(cur, user_id: int, on: bool, amount=None, threshold=None) -> None:
    sets, params = ["auto_reload=%s"], [1 if on else 0]
    if amount is not None:
        sets.append("reload_amount=%s"); params.append(str(amount))
    if threshold is not None:
        sets.append("reload_threshold=%s"); params.append(str(threshold))
    params.append(user_id)
    cur.execute("UPDATE app_stripe_customers SET %s WHERE user_id=%%s" % ", ".join(sets), tuple(params))


def user_by_email(cur, email: str) -> Optional[Dict]:
    cur.execute("SELECT id, email, name FROM app_users WHERE email=%s", (email,))
    return cur.fetchone()
