"""Every SQL statement the customer app runs. Business logic (server, agent,
engine) takes a cursor and calls these, so it can be tested with a fake.

Datetimes are stored as naive UTC, like the rest of this database.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

# Shared SQL helpers and the aggregates already split out of this module (ARCHITECTURE.md step 6).
# Re-exported so every `repo.<name>` caller and monkeypatch keeps working unchanged.
from app.adapters.db.sql import _json, _loads, now_utc, transaction  # noqa: F401
from app.adapters.db.billing_repository import (  # noqa: F401
    add_credit, credit_balance, credit_rows, credit_spent_total, credit_statement, credit_totals, get_stripe_customer,
    finished_session_costs, finished_session_costs_by_model, forever_session_rates, recent_session_costs, research_spent_since, runs_spent,
    last_credit_at, usage_by_source, save_stripe_customer, set_auto_reload, set_default_pm, user_by_email,
    credit_week, _usage_key,
)
from app.adapters.db.autopilot_pulse_repository import _pulse_at, _pulse_list, _pulse_secs, autopilot_pulse  # noqa: F401
from app.adapters.db.kalshi_keys_repository import (  # noqa: F401
    delete_kalshi_key, get_kalshi_key, save_kalshi_key,
)
from app.adapters.db.kalshi_dev_keys_repository import (  # noqa: F401
    delete_kalshi_dev_key, get_kalshi_dev_key, set_kalshi_dev_key,
)
from app.adapters.db.chat_repository import (  # noqa: F401
    active_agent_run, add_chat, chat_contains, chat_lines_like, chat_messages, create_proposal, decide_proposal,
    deployment_names, get_proposal,
    last_autopilot_action, last_chat_turn_cost, last_review_at, recent_chat_same, REVIEW_AT_SQL,
)
from app.adapters.db.order_intent_repository import (  # noqa: F401
    _naive_utc, claim_intent_booking, insert_order_intent, mark_order_intent, open_sent_intents,
    order_intents_between, ticker_has_inflight_intent, yes_quote_at,
)
from app.adapters.db.agent_run_repository import (  # noqa: F401
    MAX_RESUMES, OUT_OF_CREDITS_STEP, RUN_ACTIVE, _has_progress, add_event, cancel_run, claim_run, count_active_research,
    count_runs, create_run, example_run_id, fail_abandoned_runs, finish_run, forward_verdict, forward_verdicts, get_run,
    heartbeat, list_runs, list_runs_version,
    load_checkpoint, pause_run, research_queue_ahead, research_week, resume_run, run_events, run_worker, save_checkpoint,
    set_run_counts, set_run_market, update_run_progress, yield_run, count_own_research, RUNS_LISTED,
)
from app.adapters.db.strategy_repository import (  # noqa: F401
    DEMO_DIRECTION, NOISE_STATUSES, count_strategies, delete_strategy, get_strategy,
    insert_strategy, list_strategies, passed_since, set_strategy_outcome, share_strategy, strategies_passed_since,
    _strategy_filter_sql, strategy_records, _strategy_row,
)
from app.adapters.db.client_error_repository import (  # noqa: F401
    client_error_groups, insert_client_error,
)
from app.adapters.db.order_latency_repository import (  # noqa: F401
    _pct, insert_order_latency, order_latency_stats,
)
from app.adapters.db.reconcile_repository import (  # noqa: F401
    RECONCILE_RECENT_DAYS, get_position, legacy_live_book_rows, live_book_by_ticker_side,
    live_entry_halts, open_reconcile_rows, reconcile_deployment_id, resolve_reconcile_except,
    upsert_reconcile, users_to_reconcile,
)
from app.adapters.db.user_config_repository import (  # noqa: F401
    PLAN_KEYS, _PLAN_FIELD_MAX, autopilot_plan, set_autopilot_focus, set_autopilot_model,
    set_autopilot_plan, set_user_execution_config, set_user_risk_config, user_execution_config,
    user_risk_config,
)
from app.adapters.db.position_repository import (  # noqa: F401
    STOP_EXIT_REASONS, _newest_closed, book_partial_exit, claim_position_close, close_position, closed_book_totals,
    closed_trade_counts, closed_trades_for_export, daily_pnl,
    deployment_realized_series, early_exit_scorecard, insert_closed_position, insert_position,
    market_has_open_positions, open_positions, orphaned_open_positions, positions_for_strategy, positions_version,
    realized_pnl, realized_pnl_between, realized_pnl_by_mode,
    score_early_exit, unscored_early_exits, update_marks, user_open_exposure, user_positions, user_positions_in_ticker,
)
from app.adapters.db.paper_ledger_repository import (  # noqa: F401
    STARTING_PAPER_BALANCE, add_ledger, ledger_rows, lock_user, paper_balance, paper_deposits, paper_ledger_summary,
    paper_ledger_version, paper_reset_at, reset_paper_account,
)
from app.adapters.db.demo_capital_repository import (  # noqa: F401
    demo_account, demo_equity, reload_demo,
)
from app.adapters.db.demo_record_repository import (  # noqa: F401
    demo_book_by_ticker_side, demo_key_users, demo_order_outcomes, demo_sweeps_since, has_demo_activity,
    insert_demo_sweep,
)
from app.adapters.db.deployment_repository import (  # noqa: F401
    DISPLAY_TOTALS, _DEPLOYMENT_SELECT, _PAPER_SOURCE, activity_since, autopilot_paper_week, claim_decision, create_deployment, deployment_closed_stats,
    deployment_closed_totals, deployment_order_refs, deployments_with_open_positions, get_deployment, list_deployments,
    deployment_rows_for_display, deployment_strategies, list_deployments_brief, list_deployments_for_display, paper_event_counts,
    book_trade_stats, paper_fills_for_gate, paper_progress, paper_round_trips, paper_round_trips_by_strategy, paused_deployments_with_open_positions,
    removed_deployments, removed_totals_by_strategy, running_code_paper_deployments, running_deployments, scan_outcome, scan_tally, set_deployment_scan, set_deployment_status,
    set_deployment_strategy,
    track_record_deployments, track_record_join, track_record_rows, track_record_trades,
)
from app.adapters.db.deployment_repository import paper_board_users  # noqa: F401
from app.adapters.db.email_prefs_repository import (  # noqa: F401
    community_email_recipients, mark_community_emailed, optional_email_address, set_email_opt_out,
)
from app.adapters.db.community_repository import (  # noqa: F401
    add_comment, create_post, delete_post, edit_post, get_image, list_comments, list_posts, post_author, post_exists,
    reactions_for, recent_posts_count, store_image, toggle_like, toggle_reaction,
)
from app.adapters.db.spot_repository import latest_spot, market_strike  # noqa: F401


# -- users & sessions ----------------------------------------------------------


def ensure_welcome_bonus(cur, user_id: int) -> bool:
    """Grant the one-time welcome bonus if this user never received it.

    Idempotent and self-healing: the kind='bonus' check skips anyone who already
    has it (including backfilled rows), and the per-user stripe_ref makes concurrent
    logins race-safe via the uq_credit_stripe unique key. Called on EVERY login, so a
    grant that silently failed at signup (or predates the feature) is repaired for free.
    """
    from app.adapters.stripe import billing
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
    cur.execute("SELECT id, username, name, email, email_opt_out FROM app_users WHERE username IN (%s)" % marks, tuple(usernames))
    return cur.fetchall()


def get_user(cur, user_id: int) -> Optional[Dict]:
    cur.execute(
        "SELECT id, email, name, username, picture_url, autopilot, autopilot_live, autopilot_daily_loss_limit, autopilot_model, autopilot_focus, ui_theme, created_at FROM app_users WHERE id=%s", (user_id,)
    )
    return cur.fetchone()


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
        """SELECT u.id, u.email, u.name, u.username, u.picture_url, u.autopilot, u.autopilot_live, u.autopilot_daily_loss_limit,
                  u.autopilot_model, u.autopilot_focus, u.ui_theme, u.email_opt_out, u.created_at
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


# -- Kalshi keys: app/adapters/db/kalshi_keys_repository.py (re-exported at the top) ----


# -- Kalshi DEMO (sandbox) keys: app/adapters/db/kalshi_dev_keys_repository.py (re-exported at the top) ----


# -- paper ledger: app/adapters/db/paper_ledger_repository.py (re-exported at the top) ----


# -- demo (sandbox) capital: app/adapters/db/demo_capital_repository.py (re-exported at the top) ----


# -- agent runs: app/adapters/db/agent_run_repository.py (re-exported at the top) ----


# -- admin storage ----------------------------------------------------------------


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


# -- strategies: app/adapters/db/strategy_repository.py (re-exported at the top) ----


# -- user prefs, notifications, engine heartbeat, research policy + memory reads --------
# (the email opt-out lives in app/adapters/db/email_prefs_repository.py, re-exported at the top)


def set_ui_theme(cur, user_id: int, theme: str) -> None:
    cur.execute("UPDATE app_users SET ui_theme=%s WHERE id=%s", (theme, user_id))


def add_notification(cur, user_id: int, kind: str, body: str, link: Optional[str] = None) -> int:
    cur.execute(
        "INSERT INTO app_notifications (user_id, kind, body, link, created_at) VALUES (%s,%s,%s,%s,%s)",
        (user_id, kind, body[:400], link, now_utc()),
    )
    return cur.lastrowid


def add_notification_collapsed(cur, user_id: int, kind: str, body: str, link: str,
                               repeat_hours: float = 6) -> Optional[int]:
    """A notice about something that can be told more than once (a deployment paused again, the same
    pause seen by a retried review): the same words about the same page within `repeat_hours` are
    the same event, so nothing is added; an unread notice about that page the user hasn't seen is
    replaced by this one, so the bell holds one line with the latest reason. Returns the new id, or
    None when nothing was added."""
    cur.execute(
        "SELECT id, body, created_at, read_at FROM app_notifications WHERE user_id=%s AND kind=%s AND link=%s "
        "ORDER BY id DESC LIMIT 1",
        (user_id, kind, link),
    )
    last = cur.fetchone()
    if last and last["body"] == body[:400] and last["created_at"] >= now_utc() - timedelta(hours=repeat_hours):
        return None
    if last and last["read_at"] is None:
        cur.execute("DELETE FROM app_notifications WHERE user_id=%s AND kind=%s AND link=%s AND read_at IS NULL",
                    (user_id, kind, link))
    return add_notification(cur, user_id, kind, body, link)


def list_notifications(cur, user_id: int, limit: int = 20) -> List[Dict]:
    cur.execute(
        "SELECT id, kind, body, link, created_at, read_at FROM app_notifications WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    return cur.fetchall()


def latest_notification(cur, user_id: int, kind: str) -> Optional[Dict]:
    """The user's newest notice of one kind (body, created_at, read_at), or None."""
    cur.execute(
        "SELECT id, body, created_at, read_at FROM app_notifications WHERE user_id=%s AND kind=%s ORDER BY id DESC LIMIT 1",
        (user_id, kind),
    )
    return cur.fetchone()


def delete_notifications(cur, user_id: int, kind: str) -> int:
    """Drop the user's notices of one kind: what they said is no longer so (a failed auto-reload
    once a new card is saved)."""
    cur.execute("DELETE FROM app_notifications WHERE user_id=%s AND kind=%s", (user_id, kind))
    return cur.rowcount


def count_unread_notifications(cur, user_id: int) -> int:
    cur.execute("SELECT COUNT(*) AS c FROM app_notifications WHERE user_id=%s AND read_at IS NULL", (user_id,))
    return int(cur.fetchone()["c"])


def mark_notifications_read(cur, user_id: int) -> int:
    cur.execute("UPDATE app_notifications SET read_at=%s WHERE user_id=%s AND read_at IS NULL", (now_utc(), user_id))
    return cur.rowcount


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
    can show the Tau-RSI loop is active even when the current run hasn't dreamed yet. The two
    message prefixes range-scan idx_events_message (message(24)) instead of every event the user's
    runs logged."""
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


DROPPED_RECENT_RUNS = 10


def _newest_events(rows, limit: int) -> List[Dict]:
    """Newest-first slice of a few hundred verdict rows, sorted here rather than with ORDER BY id
    DESC LIMIT in SQL: that ordering tempts MySQL into walking the whole event table backwards by
    primary key (a 4s full scan in the 2026-10-25 slow log) instead of the (run_id, kind) index."""
    return sorted(rows, key=lambda r: r.get("id") or 0, reverse=True)[:limit]


def dropped_theses(cur, user_id: int, market: str, limit: int = 20) -> List[Dict]:
    """Theses this user's recent research on this market abandoned before they ever became a
    strategy (DOA: wrong mechanism, missing feed, 0 research-fold trades), newest first, as
    {title, why}. They never reach app_strategies, so strategy_memory can't warn the proposer off
    them and every run re-proposes the same dead idea. Reasons are research-fold only (leak-safe)."""
    cur.execute(
        "SELECT id FROM app_agent_runs WHERE user_id=%s AND kind='research' AND market=%s "
        "ORDER BY id DESC LIMIT %s", (user_id, market, DROPPED_RECENT_RUNS))
    ids = [r["id"] for r in cur.fetchall()]
    if not ids:
        return []
    cur.execute(
        "SELECT id, message, data_json FROM app_agent_events WHERE run_id IN (%s) AND kind='verdict' "
        "AND message LIKE 'DROPPED %%%%'" % ",".join(["%s"] * len(ids)), ids)
    out = []
    for r in _newest_events(cur.fetchall(), limit):
        data = _loads(r.get("data_json")) or {}
        title, why = data.get("title"), data.get("why")
        m = re.match(r'DROPPED "(.*)" \(no candidate\) \S* (.*)', r["message"] or "", re.S)
        if m:
            title, why = title or m.group(1), why or m.group(2)
        if title and not (why or "").startswith("spec invalid"):   # never tested: not a dead end
            out.append({"title": title, "why": (why or "").strip()})
    return out


SIBLING_RECENT_RUNS = 40


def sibling_dropped_theses(cur, user_id: int, markets: List[str], limit: int = 400) -> List[Dict]:
    """dropped_theses across this user's recent runs on SIBLING markets (same family), as
    {market, title, why}. Each run used to rediscover alone that, say, favorite-longshot calibration
    is dead on every crypto 15m strike ladder; this is what lets one market learn from the others."""
    if not markets:
        return []
    cur.execute(
        "SELECT id, market FROM app_agent_runs WHERE user_id=%%s AND kind='research' AND market IN (%s) "
        "ORDER BY id DESC LIMIT %%s" % ",".join(["%s"] * len(markets)), (user_id, *markets, SIBLING_RECENT_RUNS))
    runs = {r["id"]: r["market"] for r in cur.fetchall()}
    if not runs:
        return []
    cur.execute(
        "SELECT id, run_id, message, data_json FROM app_agent_events WHERE run_id IN (%s) AND kind='verdict' "
        "AND message LIKE 'DROPPED %%%%'" % ",".join(["%s"] * len(runs)), tuple(runs))
    out = []
    for r in _newest_events(cur.fetchall(), limit):
        data = _loads(r.get("data_json")) or {}
        title, why = data.get("title"), data.get("why")
        m = re.match(r'DROPPED "(.*)" \(no candidate\) \S* (.*)', r["message"] or "", re.S)
        if m:
            title, why = title or m.group(1), why or m.group(2)
        if title and not (why or "").startswith("spec invalid"):
            out.append({"market": runs.get(r["run_id"]), "title": title, "why": (why or "").strip()})
    return out


# -- deployments: app/adapters/db/deployment_repository.py (positions: position_repository.py), re-exported at the top ----


# -- live position reconciliation: app/adapters/db/reconcile_repository.py (re-exported at the top) ----


# -- durable order-intent log: app/adapters/db/order_intent_repository.py (re-exported at the top) ----


# -- execution latency: app/adapters/db/order_latency_repository.py; per-user risk, execution and autopilot
# settings: user_config_repository.py; P&L reads: position_repository.py (all re-exported at the top) ----


# -- chat & proposals: app/adapters/db/chat_repository.py (re-exported at the top) ----


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
                 underlying: str = "BTC-USD", tickers: Optional[set] = None,
                 until: Optional[datetime] = None, cross: Optional[str] = None) -> Dict[str, List]:
    """markets as dicts; candles as compact (ticker, end_period_ts, bid, ask) tuples.
    `cross` (a spot symbol, markets.cross_product) also loads that coin's closes as "cross".
    `tickers` keeps only those contracts' candles and microstructure (a partition window),
    so rows for contracts outside it are dropped as they stream instead of held. `until` (a
    close_time upper bound) keeps the database from scanning contracts past the window at all."""
    upto, upto_args = (" AND close_time <= %s", (until,)) if until is not None else ("", ())
    cur.execute(
        """SELECT ticker, strike, close_time, result FROM hist_markets
           WHERE series_ticker=%s AND close_time >= %s AND candles_done=1""" + upto,
        (series, since) + upto_args,
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
             AND c.period_interval_minutes=%s""" + upto.replace("close_time", "h.close_time"),
        (series, since, candle_minutes) + upto_args,
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
    out = {"markets": markets, "candles": candles, "btc": btc,
           "micro": _load_micro(cur, series, since, tickers, until)}
    if cross:
        cur.execute("SELECT start_ts, close FROM spot_candles_1m WHERE symbol=%s AND start_ts >= %s ORDER BY start_ts",
                    (cross, start_ts))
        out["cross"] = [(int(r["start_ts"]), float(r["close"])) for r in cur.fetchall()]
    return out


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
    from app.trading.markets import MICRO_FEATURES
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
                tickers: Optional[set] = None, until: Optional[datetime] = None) -> Dict[tuple, Dict[str, Any]]:
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
                 AND f.snapshot_minute_utc >= %s""" + (" AND h.close_time <= %s" if until is not None else ""),
            (series, since, since) + ((until,) if until is not None else ()),
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


def load_weather_forecasts(cur, station: str, kind: str, since_day,
                           as_of_ts: Optional[int] = None) -> List[Tuple[int, Any, str, float, Optional[float]]]:
    """Issued forecasts for one station's daily max/min with target_day >= since_day, as the
    (known_at_ts, target_day, model, value_f, sd_f) rows app/adapters/data/weather_fcst.ForecastBook takes.
    as_of_ts (live) also drops rows not yet known, though the book's as-of lookup does that too."""
    sql = ("SELECT known_at_utc, target_day, model, value_f, sd_f FROM weather_forecasts "
           "WHERE station=%s AND kind=%s AND target_day >= %s")
    args: Tuple = (station, kind, since_day)
    if as_of_ts is not None:
        sql += " AND known_at_utc <= %s"
        args += (datetime.fromtimestamp(int(as_of_ts), tz=timezone.utc).replace(tzinfo=None),)
    cur.execute(sql, args)
    return [(int(r["known_at_utc"].replace(tzinfo=timezone.utc).timestamp()), r["target_day"], r["model"],
             float(r["value_f"]), _num(r["sd_f"])) for r in cur.fetchall()]


# A settled value is published some time after the market closes; count it known this long after.
WEATHER_ACTUAL_LAG_S = 2 * 3600


def load_weather_actuals(cur, series: str, since: datetime) -> List[Tuple[int, Any, float]]:
    """Settled daily values of a weather series since `since`, as (known_at_ts, day, value_f) for
    app/adapters/data/weather_fcst's trailing bias: one per event, known WEATHER_ACTUAL_LAG_S after it closed.
    An event is kept only when its value lies in the contract that settled YES: Kalshi's
    historical endpoint returns 0.0 for some older events' expiration_value, which would
    otherwise read as a 60F forecast bias."""
    from app.adapters.data.weather_fcst import parse_contract
    cur.execute(
        "SELECT event_ticker, ticker, strike, close_time, result, expiration_value FROM hist_markets "
        "WHERE series_ticker=%s AND close_time >= %s AND expiration_value IS NOT NULL",
        (series, since))
    events: Dict[str, Dict[str, Any]] = {}
    for r in cur.fetchall():
        e = events.setdefault(r["event_ticker"], {"closed": r["close_time"], "v": float(r["expiration_value"]),
                                                  "ok": None, "day": None})
        e["closed"] = max(e["closed"], r["close_time"])
        if (r.get("result") or "").lower() == "yes":
            terms = parse_contract(r["ticker"], float(r["strike"] or 0))
            if terms is not None:
                day, lo, hi = terms
                v = int(round(float(r["expiration_value"])))
                e["day"], e["ok"] = day, (lo is None or lo <= v) and (hi is None or v <= hi)
    return [(int(e["closed"].replace(tzinfo=timezone.utc).timestamp()) + WEATHER_ACTUAL_LAG_S, e["day"], e["v"])
            for e in events.values() if e["ok"]]


def latest_options_surface(cur, as_of_ts: int) -> Optional[List[Dict[str, Any]]]:
    """The newest Deribit surface rows (options_surface.SURFACE_FIELDS) the collector box's
    recorder fitted, from its heartbeat (collector_state tick_recorder_deribit), or None. Rows
    from after as_of_ts are dropped; the book's as-of lookup also drops a surface that is too old."""
    import json
    cur.execute("SELECT state_value FROM collector_state WHERE state_key='tick_recorder_deribit' LIMIT 1")
    row = cur.fetchone() or {}
    try:
        state = json.loads(row.get("state_value") or "{}")
    except (TypeError, ValueError):
        return None
    rows = [r for r in (state.get("surface") or []) if int(r.get("snap_ts") or 0) <= int(as_of_ts)]
    return rows or None


def load_sports_odds(cur, sport: str, since: datetime,
                     as_of_ts: Optional[int] = None) -> List[Tuple[int, int, str, str, str, float]]:
    """Collected sportsbook snapshots for one league since `since` (UTC naive), as the
    (collected_ts, commence_ts, home_code, away_code, book, p_home) rows app/adapters/data/sports_odds.OddsBook
    takes. as_of_ts (live) also drops snapshots collected after it."""
    sql = ("SELECT collected_at_utc, commence_utc, home_code, away_code, book, p_home FROM sports_odds "
           "WHERE sport=%s AND collected_at_utc >= %s")
    args: Tuple = (sport, since)
    if as_of_ts is not None:
        sql += " AND collected_at_utc <= %s"
        args += (datetime.fromtimestamp(int(as_of_ts), tz=timezone.utc).replace(tzinfo=None),)
    cur.execute(sql, args)

    def _ts(d):
        return int(d.replace(tzinfo=timezone.utc).timestamp())
    return [(_ts(r["collected_at_utc"]), _ts(r["commence_utc"]), r["home_code"], r["away_code"], r["book"],
             float(r["p_home"])) for r in cur.fetchall()]


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


CURVE_MAX_POINTS = 120  # per deployment: plenty for a sparkline


def deployment_curves(cur, user_id: int, max_points: int = CURVE_MAX_POINTS,
                      deployment_ids: Optional[List[int]] = None) -> Dict[int, List[List]]:
    """Cumulative realized P&L per deployment, oldest first, for sparklines: [[unix_ts, cum], ...].

    A curve with more than `max_points` trades is cut down in SQL. The first and last points are
    kept exactly, so the curve ends on the deployment's realized P&L to the cent. The trades between
    them are split into (max_points - 2) // 2 runs by trade count, and each run keeps its lowest and
    highest point, so every drawdown and peak still shows. Every point kept is a real trade's
    cumulative P&L. The dashboard used to receive one point per closed trade (433KB at 20k trades)
    and spent ~150ms turning those rows into Python. Ties keep the earlier trade.

    `deployment_ids` limits the read to the deployments a page lists (the Deploy board shows only
    the ones not stopped); each curve is its own deployment's, so a listed curve is the same either
    way. A busy trader's stopped deployments hold much of their history, which the full read sorted
    for curves nobody shows. The timestamp is computed in SQL from the naive-UTC DATETIME
    (TIMESTAMPDIFF, which no session time zone touches), the same integer the Python conversion
    gave, without decoding thousands of datetimes.

    Each deployment's kept points come back as one JSON array row ([rn, ts, cum] per point), sorted
    by rn here: pymysql decodes a row at a time in Python, and a busy board's ~3,000 point rows were
    most of this read (33 -> 19ms at 30 deployments and 3,000 closed trades). JSON_ARRAYAGG takes no
    ORDER BY on MySQL, hence rn. cum is the DECIMAL's own text in the array, so float() of it is the
    float the DECIMAL gave."""
    buckets = max(1, (max_points - 2) // 2)
    ids: Tuple = ()
    where = "user_id=%s AND status='closed'"
    if deployment_ids is not None:
        ids = tuple(sorted({int(i) for i in deployment_ids}))
        if not ids:
            return {}
        where = "deployment_id IN (" + ",".join(["%s"] * len(ids)) + ") AND " + where
    cur.execute(
        """SELECT deployment_id,
                  JSON_ARRAYAGG(JSON_ARRAY(rn, TIMESTAMPDIFF(SECOND, '1970-01-01 00:00:00', closed_at), cum)) AS pts FROM (
             SELECT deployment_id, closed_at, cum, rn,
                    ROW_NUMBER() OVER (PARTITION BY deployment_id, b ORDER BY cum, rn) AS lo,
                    ROW_NUMBER() OVER (PARTITION BY deployment_id, b ORDER BY cum DESC, rn) AS hi
             FROM (
               SELECT deployment_id, closed_at, cum, rn,
                      CASE WHEN n <= %s THEN rn WHEN rn = 1 THEN -1 WHEN rn = n THEN %s
                           ELSE FLOOR((rn - 2) * %s / (n - 2)) END AS b
               FROM (
                 SELECT deployment_id, closed_at,
                        SUM(pnl) OVER (PARTITION BY deployment_id ORDER BY closed_at, id ROWS UNBOUNDED PRECEDING) AS cum,
                        CAST(ROW_NUMBER() OVER (PARTITION BY deployment_id ORDER BY closed_at, id) AS SIGNED) AS rn,
                        COUNT(*) OVER (PARTITION BY deployment_id) AS n
                 FROM app_positions WHERE """ + where + """
               ) ordered
             ) bucketed
           ) ranked
           WHERE lo = 1 OR hi = 1
           GROUP BY deployment_id
           ORDER BY deployment_id""",
        (max_points, buckets, buckets, *ids, user_id),
    )
    out: Dict[int, List[List]] = {}
    for r in cur.fetchall():
        pts = r["pts"]
        pts = sorted(json.loads(pts.decode() if isinstance(pts, (bytes, bytearray)) else pts))
        out[r["deployment_id"]] = [[int(ts), round(float(cum), 4)] for _, ts, cum in pts]
    return out


def active_run_counts(cur, user_id: int, silent_before=None) -> Dict[str, int]:
    """Queued, running and paused runs by kind, paused research apart from running. With
    `silent_before`, a running run whose last beat (or start) is older than it is left out: its
    worker died, and the reaper that would stop it runs in that worker, so "1 agent researching"
    stayed up for hours beside an autopilot card saying it was between research runs."""
    silent = ("" if silent_before is None else
              " AND NOT (status='running' AND COALESCE(heartbeat_at, started_at, created_at) < %s)")
    cur.execute(
        """SELECT kind, status, COUNT(*) AS n FROM app_agent_runs
           WHERE user_id=%s AND status IN ('queued','running','paused')""" + silent + " GROUP BY kind, status",
        (user_id,) if silent_before is None else (user_id, silent_before),
    )
    out = {"research_running": 0, "research_paused": 0, "research_queued": 0, "chat_active": 0}
    for r in cur.fetchall():
        if r["kind"] == "research":
            # A paused run still holds one of the user's session slots (count_runs active_only), but
            # it isn't researching: counted under "running", one running and one paused read
            # "Researching now 2". The pages say running and paused apart.
            out["research_" + r["status"]] += int(r["n"])
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
    from app.trading import spec as _spec
    return _spec.DEFAULT_SPEC


# -- community: app/adapters/db/community_repository.py (re-exported at the top) ----


# -- credits & billing: app/adapters/db/billing_repository.py (re-exported at the top) ----
