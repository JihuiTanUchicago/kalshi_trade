"""Tau's web server: the single-page app plus its JSON API.

    python -m app.server            # APP_PORT (default 8090)

Stdlib only, like the operator dashboard. Every request opens its own DB
connection, and every write route requires the session cookie AND the
`X-Recursive: 1` header - a header a cross-site form cannot send, which is
the CSRF defence (SameSite=Lax is the second layer).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from app.trading import backtest, engine
from app.adapters.ses import notify
from app.adapters.stripe import billing
from app.web import auth, devlog
from app.research import agent, dreaming
from app.adapters.kalshi import kalshi_account
from app.adapters.kalshi import kalshi_dev
from app.adapters.kalshi import kalshi_dev_exec
from app.adapters.kalshi_perps import kalshi_perps_trading
from app.adapters.alpaca import alpaca_paper
from app.adapters.brokers import broker_oauth  # noqa: F401  (tests patch server.broker_oauth)
from app.adapters.llm import models_catalog as catalog
from app import repository as repo
from app.research import research_repository as research_repo
from app.trading import spec as specmod
from app.services import backtest_check, bell, book_memo, customer_text, gate_explain, page_poll, paper_checks, research_list, run_stop, trade_why
from app.trading import track_record
from app.web import client_errors, webperf
from app import worker
from app.trading.markets import MARKETS
from app.services import markets as market_service
from data_pipeline.common import get_db_conn

PORT = int(os.getenv("APP_PORT", "8090"))
HOST = os.getenv("APP_HOST", "127.0.0.1")
# Canonical-host redirect: a top-level GET to any host in APP_REDIRECT_HOSTS (e.g. the old
# CloudFront URL, or www) is 301'd to APP_CANONICAL_HOST, so old links keep working after the
# custom-domain cutover. Empty APP_CANONICAL_HOST disables it entirely (the default), so this is
# inert until the new domain is actually live. /api and /auth are never redirected, so an in-flight
# request from an already-loaded old-host page still completes.
CANONICAL_HOST = os.getenv("APP_CANONICAL_HOST", "").strip().lower()
REDIRECT_HOSTS = {h.strip().lower() for h in os.getenv("APP_REDIRECT_HOSTS", "").split(",") if h.strip()}
STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY = 8 * 1024 * 1024  # allows a base64 image in a community post
# Routes with a smaller body cap, checked from Content-Length before the body is read.
BODY_LIMITS = {"/api/client-errors": client_errors.MAX_BODY}

CSP = (
    "default-src 'self'; script-src 'self' https://js.stripe.com https://pay.google.com; style-src 'self'; style-src-attr 'unsafe-inline'; "
    "font-src 'self'; img-src 'self' data: https://*.googleusercontent.com https://*.stripe.com; "
    "connect-src 'self' https://api.stripe.com https://*.stripe.com; frame-src https://js.stripe.com https://hooks.stripe.com https://*.stripe.com https://pay.google.com; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


from app.web.http import ApiError, Ctx, _int_param, _json_default, _num  # noqa: F401  (request types)
from app.web.caches import (  # noqa: F401  (shared read caches)
    _ROADS,
    _SHARED,
    _SHARED_LOCK,
    _TRACK_RECORD,
    _forget_own_change,
    _refresh_shared,
    _shared,
)
from app.web.views import (  # noqa: F401  (shared presenters)
    RUN_OVERDUE_SECONDS,
    _DEMO_KEY_PAUSE,
    _auto_reload_terms,
    _demo_health,
    _deployment_out,
    _gate_lines,
    _gate_tints,
    _live_balance,
    _needs_card,
    _open_book,
    _pause_clause,
    _plain_pause_reason,
    _require_billing_ready,
    _run_wait,
    _silent_before,
    _spec_sizing,
    _start_of_day_utc,
    _status_why,
    _usd,
    _with_gate_lines,
    credit_exact,
    credit_usd,
)
from app.web.settings import (  # noqa: F401  (server.py keeps the names for routing and tests)
    ADMIN_EMAIL,
    DEV_LOGIN,
    MAX_ACTIVE_DEPLOYMENTS,
    MAX_ACTIVE_RESEARCH,
    MAX_CHAT_PER_HOUR,
    MAX_PAPER_BALANCE,
    MAX_RESEARCH_PER_DAY,
    MAX_WAITLIST_PER_MINUTE,
    OPEN_SIGNUP,
    SECURE_COOKIES,
    SPA_ROUTES,
)


from app.web.routes.auth import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    UI_COOKIE,
    UI_THEMES,
    _sync_ui_cookie,
    _ui_cookie,
    dev_login,
    google_callback,
    google_start,
    logout,
    _start_session,
    _safe_next,
)
from app.web.routes.brokers import (  # noqa: F401  (routes registered in ROUTES below)
    broker_connections,
    broker_connect,
    broker_callback,
    broker_disconnect,
    _paper_call,
    alpaca_paper_account,
    alpaca_paper_draft,
    alpaca_paper_action,
    _perps_live_call,
    kalshi_perps_live_account,
    kalshi_perps_live_policy,
    kalshi_perps_live_draft,
    kalshi_perps_live_proposal,
    kalshi_perps_live_action,
)
from app.web.routes.community import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    community,
    community_image,
    create_comment,
    create_community_post,
    edit_community_post,
    like_post,
    mention_candidates,
    post_comments,
    react_post,
    _notify_mentions,
    _post_snapshot,
)
from app.web.routes.billing import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    _credits_running_low,
    billing_autoreload,
    billing_card_added,
    billing_receipt,
    billing_remove_card,
    billing_setup_intent,
    billing_state,
    billing_topup,
    trades_csv,
    TRADES_CSV_MAX_ROWS,
    TRADE_MODES,
    _csv_safe,
    _usd4,
)
from app.web.routes.funds import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    delete_kalshi_dev_key,
    delete_kalshi_key,
    demo_reload,
    funds,
    paper_transfer,
    save_kalshi_dev_key,
    save_kalshi_key,
    waitlist,
)
from app.web.routes.admin import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    admin_grant,
    admin_kill_switch,
    admin_kill_switch_set,
    admin_overview,
    admin_system,
    admin_waitlist,
    exec_latency,
    exec_tca,
    report_client_error,
    system_code,
    _require_admin,
    _system_event,
)
from app.web.routes.strategies import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    _BACKTEST_CHECKS,
    _backtest_checks,
    _delete_block,
    _experiment_block,
    _mark_fields,
    _owned_strategy,
    _strategy_card,
    _with_marks,
    _with_why,
    delete_strategy,
    get_strategy,
    list_strategies,
    share_strategy,
    strategy_dev_curve,
    what_if,
)
from app.web.routes.deployments import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    ROAD_TTL,
    _FAILING,
    _deploy_roads,
    _paper_strategy_ids,
    create_deployment,
    deployment_action,
    list_deployments,
    strategy_live_readiness,
)
from app.web.routes.chat import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    _UNKNOWN,
    _autopilot_now,
    _autopilot_story,
    _autopilot_week,
    _engine_age,
    _idle_reason,
    _paper_waiting,
    _paused_lines,
    _paused_recent,
    _research_activity,
    _stop_line,
    _tournament_line,
    autopilot_focus,
    autopilot_kill,
    autopilot_live,
    autopilot_model,
    autopilot_status,
    decide_proposal,
    get_chat,
    post_chat,
    settings,
)
from app.web.routes.explore import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    _EXPLORE_CACHE,
    _efloat,
    _explore_feed,
    _feed_mid,
    _fetch_explore_feed,
    _market_mine,
    _refresh_explore_feed,
    explore_hot,
    explore_list,
    explore_market,
)
from app.web.routes.research import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    LAST_DREAM_TTL,
    RUN_TOTALS_TTL,
    SCOREBOARD_TTL_S,
    SESSION_COST_MIN_OWN,
    SESSION_COST_MIN_TYPICAL,
    _LAST_DREAM,
    _RUN_TOTALS,
    _TYPICAL_FOREVER_RATE,
    _TYPICAL_SESSION_COST,
    _forever_hourly,
    _last_dream,
    _mark_example,
    _median,
    _require_research_capacity,
    _research_context,
    _research_scoreboard,
    _research_totals,
    _researchable_markets,
    _rsi_block,
    _typical_session_costs,
    _with_spent,
    cancel_run,
    create_run,
    dig_deeper,
    example_run,
    get_run,
    list_runs,
    models,
    pause_run,
    research_context,
    research_estimate,
    research_scoreboard,
    resume_run,
)


# -- read routes ---------------------------------------------------------------


def warm_shared() -> None:
    """Fill the shared reads at startup, so the first page after a deploy doesn't pay for them."""
    conn = None
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        _shared("series_with_candles", 120, lambda c: repo.series_with_candles(c), cur)
        _shared("history_freshness", 60, lambda c: repo.history_freshness(c), cur)
    except Exception:
        traceback.print_exc()
    finally:
        if conn is not None:
            conn.close()


WARM_BOARD_USERS = 50  # users whose Deploy board is read at startup, most recently signed in first
WARM_BOARD_SECONDS = 120.0  # and no more than this, all told


def warm_deploy_boards(limit: int = WARM_BOARD_USERS, budget: float = WARM_BOARD_SECONDS) -> int:
    """Read the Deploy board's road to live at startup, off the request path, for the users likely to
    open it (a paper strategy running or paused, most recently signed in first), so the first board
    after a deploy doesn't run every paper strategy's gate bootstrap cold (agent._paper_edge_p_value
    keeps it per process; ~6s for a busy account's nine). It fills the same caches a request would
    (paper_checks' answers, the bootstrap memo), on one connection of its own, a user at a time with a
    pause between, and stops at `limit` users or `budget` seconds. A failure is logged and skipped;
    the requests then read as they did. Returns the boards read."""
    conn, done, t0 = None, 0, time.time()
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        for uid in repo.paper_board_users(cur, limit):
            if time.time() - t0 > budget:
                break
            try:
                memo = book_memo.BookMemo(cur, uid)  # its position sums are kept too
                _deploy_roads(cur, uid, book_memo.deployments_for_display(memo), memo)
                done += 1
            except Exception as e:  # noqa: BLE001 - this board is read in its request instead
                _log_line("[app] warming user %d's Deploy board failed (%s)" % (uid, type(e).__name__))
            time.sleep(0.05)  # let requests in between
    except Exception as e:  # noqa: BLE001 - the boards are read in their requests instead
        _log_line("[app] warming the Deploy boards failed (%s)" % type(e).__name__)
    finally:
        if conn is not None:
            conn.close()
    _log_line("[app] warmed %d Deploy board(s) in %.1fs" % (done, time.time() - t0))
    return done


def me(ctx: Ctx):
    _sync_ui_cookie(ctx, ctx.user.get("ui_theme") if ctx.user.get("ui_theme") in UI_THEMES else "tau")
    reads = billing.Reads(ctx.cur, ctx.uid)  # needs_card, auto_reload and credit_balance share one read each
    return {
        "user": {
            "id": ctx.user["id"], "email": ctx.user["email"], "name": ctx.user["name"],
            "username": ctx.user.get("username"), "ui_theme": ctx.user.get("ui_theme") or "tau",
            "email_opt_out": bool(ctx.user.get("email_opt_out")),  # Settings' email switch reads this
            "picture": ctx.user["picture_url"], "autopilot": bool(ctx.user["autopilot"]),
            "autopilot_live": bool(ctx.user.get("autopilot_live")),
            "autopilot_daily_loss_limit": float(ctx.user.get("autopilot_daily_loss_limit") or 50),
        },
        "kalshi_connected": repo.get_kalshi_key(ctx.cur, ctx.uid) is not None,
        "kalshi_dev_connected": repo.get_kalshi_dev_key(ctx.cur, ctx.uid) is not None,
        "live_trading_available": engine.LIVE_TRADING_ENABLED,
        # Demo (sandbox) always supports NO/either; live NO is behind the staged-rollout flag.
        "no_side_live_enabled": engine.NO_SIDE_LIVE_ENABLED,
        "is_admin": (ctx.user["email"] or "").lower() == ADMIN_EMAIL.lower(),
        "billing_enabled": billing.configured(),
        "needs_card": _needs_card(ctx, reads),
        "auto_reload": _auto_reload_terms(ctx, reads),
        "free_bonus": float(billing.FREE_BONUS),
        "credit_balance": credit_exact(reads.balance()),
        "min_run_balance": float(billing.MIN_RUN_BALANCE),  # the headroom a research run needs to start
        "perps_live_available": kalshi_perps_trading.enabled(),  # hide the Funds perps box when live perps are off
        "markets": _researchable_markets(ctx.cur),
        "directions": [{"key": k, **v} for k, v in agent.DIRECTIONS.items()],
        # The research form's model list (the same as GET /api/models), so /research doesn't wait on
        # that read before it starts its own.
        "models": models(ctx),
    }


def _mode_bucket(cur, uid: int, mode: str, open_pos: List[Dict], deps: List[Dict], day,
                 realized: Optional[Tuple[float, float]] = None,
                 closed: Optional[Dict[str, int]] = None) -> Dict:
    """Money in one deployment-mode bucket (paper | demo | live), from that mode's own
    positions and deployments only — so the three buckets never double-count each other.
    `realized` is (all time, since `day`) when the caller read every book's at once.
    `closed` is the closed-trade counts of repo.closed_book_totals (read once for all three)."""
    if realized is None:
        realized = (repo.realized_pnl(cur, uid, mode), repo.realized_pnl(cur, uid, mode, day))
    total, today = realized
    return {
        "closed_trades": int((closed or {}).get(mode, 0)),  # > 0: the dashboard offers /api/trades.csv
        **_open_book(open_pos, mode),
        "running": sum(1 for d in deps if d["mode"] == mode and d["status"] == "running"),
        "realized_pnl": round(total, 2),
        "today_pnl": round(today, 2),
    }


def dashboard(ctx: Ctx):
    cur = ctx.cur
    day = _start_of_day_utc()
    open_pos = _with_marks(repo.user_positions(cur, ctx.uid, "open"))
    # Aggregate live mark-to-market unrealized P&L per deployment (from the marks just stamped), so
    # the Deployed table can show each strategy's current open P&L, not only its realized P&L.
    unreal_by_dep: Dict[int, float] = {}
    for p in open_pos:
        u = p.get("unrealized")
        if u is not None and p.get("deployment_id") is not None:
            unreal_by_dep[p["deployment_id"]] = round(unreal_by_dep.get(p["deployment_id"], 0.0) + u, 2)
    # The reads summed from the positions alone are kept until the positions change (services.book_memo).
    memo = book_memo.BookMemo(cur, ctx.uid)
    deps = book_memo.deployments_for_display(memo)
    # Curves only for the deployments the Deployed table shows (a stopped one's history is not drawn).
    curves = book_memo.deployment_curves(memo, [d["id"] for d in deps])
    ledger = book_memo.paper_ledger_summary(cur, ctx.uid)  # balance, deposits and reset: one read, kept until the ledger moves
    balance, deposited = ledger["balance"], ledger["deposited"]
    visit, first = _visit_since(ctx.query.get("since"))
    # Every book's realized P&L and closed-trade count (today and since the last visit), in one read.
    realized, closed, recent = book_memo.closed_book_totals(memo, day, visit)
    _BOOK_SHAPE[ctx.uid] = _book_shape(closed, len(open_pos))  # the track record's cache checks it
    # Three mode buckets, each self-contained (real / sandbox / simulation). Paper + demo both
    # carry an app-controlled cash layer on top of the shared fields; live carries the real
    # Kalshi balance (money we never hold).
    paper = _mode_bucket(cur, ctx.uid, "paper", open_pos, deps, day, realized["paper"], closed)
    equity = balance + paper["open_at_cost"]
    paper.update(
        cash=round(balance, 2),
        equity=round(equity, 2),
        deposited=round(deposited, 2),
        total_pnl=round(equity - deposited, 2),
        roi=round((equity - deposited) / deposited, 4) if deposited > 0 else None,
        daily=book_memo.daily_pnl(memo, "paper"),
        # total_pnl restarts at a reset (the ledger is wiped), so its label says "since reset", not
        # "all time", while the track record still counts every closed trade.
        reset_at=ledger["reset_at"],
    )
    # Demo: real fills applied to the capital WE set. Equity = capital + realized-since-reload,
    # and the displayed realized P&L is net of the reload baseline (so a reload reads as $X flat).
    demo = _mode_bucket(cur, ctx.uid, "demo", open_pos, deps, day, realized["demo"], closed)
    de = repo.demo_equity(cur, ctx.uid, realized=realized["demo"][0])
    demo.update(capital=de["capital"], equity=de["equity"], realized_pnl=de["realized"],
                total_pnl=de["realized"], roi=de["roi"], before_reload=de["before_reload"],
                health=_demo_health(cur, ctx.uid, deps))  # capital and P&L look fine while Kalshi refuses every order
    live = _mode_bucket(cur, ctx.uid, "live", open_pos, deps, day, realized["live"], closed)
    live.update(_live_balance(cur, ctx.uid))
    paper_sids = _paper_strategy_ids(deps)
    # The page polls every 15s with its last answer's version (?v=): an unchanged answer is sent as
    # "same" with only the marks and data ages, which move every tick (services.page_poll).
    return page_poll.answer({
        "paper": paper,
        "demo": demo,
        "live": live,
        "open_positions": _with_why(open_pos, deps),
        "recent_closed": _with_why(repo.user_positions(cur, ctx.uid, "closed", 12), deps),
        # Live book-vs-Kalshi reconciliation: empty list = book matches the exchange; any rows are
        # open discrepancies the reconciler flagged (shown as a trust badge on the Live bucket).
        "reconcile": repo.open_reconcile_rows(cur, ctx.uid),
        "deployments": [_deployment_out(d, curves.get(d["id"], []), unreal_by_dep.get(d["id"]), paper_sids) for d in deps],
        "agents": repo.active_run_counts(cur, ctx.uid, silent_before=_silent_before()),
        "freshness": _freshness(cur),
        "since": _since_visit(cur, ctx.uid, visit, first, recent),
    }, ctx.query.get("v"))


SINCE_MAX = timedelta(days=7)    # an older last visit reads as the last 7 days
SINCE_FIRST = timedelta(hours=24)  # no last visit known (first visit on this device): the last 24h


def _visit_since(raw) -> Tuple[datetime, bool]:
    """The start of "since your last visit" from the dashboard's ?since= (epoch seconds, kept in a
    cookie by the page), clamped to the last 7 days. Missing or unreadable: the last 24 hours, and
    `first` is True so the strip says "Last 24 hours" instead."""
    now = repo.now_utc()
    try:
        at = datetime.fromtimestamp(int(str(raw)), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return now - SINCE_FIRST, True
    return min(max(at, now - SINCE_MAX), now), False


def _since_visit(cur, uid: int, visit: datetime, first: bool, recent: Dict) -> Dict:
    """The dashboard's "since your last visit" strip: each book's realized P&L and closed trades
    since then (from the books' one pass; books are never added together), the strategies that
    passed, the autopilot's own changes and the research sessions started. Two reads. Credits spent
    (real money) ride apart from the books, and only while payments are on: with them off nothing
    is billed. `milestones` are the paper forward-gate passes and live-ready strategies since then."""
    act = repo.activity_since(cur, uid, visit)
    return {"at": visit, "first": first,
            "books": {m: {"pnl": round(pnl, 2), "trades": n} for m, (pnl, n) in recent.items()},
            "passed": repo.passed_since(cur, uid, visit),
            "autopilot": act["autopilot"], "runs": act["runs"], "own_sessions": bool(act.get("own_sessions")),
            "spent": {k: credit_usd(v) for k, v in act["spent"].items()} if billing.configured() and act.get("spent") else None,
            "milestones": act.get("milestones") or {"passed": [], "live_ready": []}}


TRACK_RECORD_TTL = 60.0  # seconds; the record moves only when a trade closes
# A book with fewer trades than this is read fresh on every request: its grouped read is a few rows
# through idx_pos_user, and a new user's first trade showed up only after the cached empty record
# expired (up to a minute after the board above it showed the trade).
TRACK_RECORD_CACHE_MIN_TRADES = 200
# {user id: the book's shape at the dashboard's last read} (_book_shape): one closed-trade count per
# mode and the open count. A busy book's cached record is rebuilt once the dashboard has seen a trade
# open or close that the record predates, so the two never disagree for the rest of the minute.
_BOOK_SHAPE: Dict[int, Tuple] = {}


def _book_shape(closed: Dict[str, int], open_count: int) -> Tuple:
    return tuple(sorted(closed.items())), int(open_count)


def get_track_record(ctx: Ctx):
    """The fund-grade track record: realized results per money bucket (live / demo / paper), from
    the user's own closed trades. A busy book is cached per user for TRACK_RECORD_TTL (never served
    stale past it, nor past a trade the dashboard has seen open or close, nor past the user's own
    deploy or stop), so a page left open costs one grouped scan a minute at most; a small one is
    read every time."""
    hit, shape = _TRACK_RECORD.get(ctx.uid), _BOOK_SHAPE.get(ctx.uid)
    if (hit and hit[2] >= TRACK_RECORD_CACHE_MIN_TRADES and time.time() - hit[0] < TRACK_RECORD_TTL
            and hit[3] == shape):
        return hit[1]
    val = book_memo.track_record(ctx.cur, ctx.uid)  # the trades and their buckets kept until the book changes
    n = sum(int(m.get("trades") or 0) for m in (val.get("modes") or {}).values())
    _TRACK_RECORD[ctx.uid] = (time.time(), val, n, shape)
    return val


def _freshness(cur) -> Dict:
    raw = _shared("history_freshness", 60, lambda c: repo.history_freshness(c), cur)
    now = int(datetime.now(timezone.utc).timestamp())
    out = {k: (now - int(v) if v else None) for k, v in raw.items()}
    # Engine liveness: seconds since the deployment engine's last tick (None = never/dead). A stalled
    # engine holding real positions is the worst silent failure, so it rides the same payload.
    try:
        out["engine"] = repo.engine_last_tick_age_seconds(cur)
    except Exception:
        out["engine"] = None
    return out


def notifications(ctx: Ctx):
    rows = customer_text.notification_rows(repo.list_notifications(ctx.cur, ctx.uid, limit=bell.READ_ROWS))
    return {"unread": repo.count_unread_notifications(ctx.cur, ctx.uid), "items": bell.grouped(rows)}


def mark_notifications_read(ctx: Ctx):
    repo.mark_notifications_read(ctx.cur, ctx.uid)
    return {"ok": True}


def set_ui_theme(ctx: Ctx):
    theme = str(ctx.body.get("theme") or "").strip()
    if theme not in ("tau", "meridian"):
        raise ApiError(400, "Unknown theme.")
    repo.set_ui_theme(ctx.cur, ctx.uid, theme)
    _sync_ui_cookie(ctx, theme)  # the reload that follows gets the new theme's shell
    return {"ok": True, "theme": theme}


def set_email_preferences(ctx: Ctx):
    """Settings' email switch, for the signed-in user only: optional email (community posts, replies,
    mentions, ready-for-live notices) off or back on. The unsubscribe link writes the same field;
    live-money safety alerts never read it."""
    opt_out = ctx.body.get("email_opt_out")
    if not isinstance(opt_out, bool):
        raise ApiError(400, "Choose whether Tau may send you optional email.")
    if not repo.set_email_opt_out(ctx.cur, ctx.uid, opt_out):
        raise ApiError(404, "Your account wasn't found. Sign in again.")
    return {"ok": True, "email_opt_out": opt_out}


def unsubscribe(ctx: Ctx):
    """Public one-click unsubscribe from optional email (HMAC-signed link, no login needed). It sets
    the same switch as Settings, so the page says what stopped and where to turn it back on."""
    try:
        uid = int(ctx.query.get("u") or 0)
    except ValueError:
        uid = 0
    ok = bool(uid) and notify.unsubscribe_token_valid(uid, ctx.query.get("t") or "") and repo.set_email_opt_out(ctx.cur, uid, True)
    msg = ("You're unsubscribed from Tau's optional email: new community posts, replies, mentions, and "
           "notices that a paper strategy is ready for live trading. Safety alerts about a Bitcoin perps "
           "account you trade through Tau still come, because they protect real money. You can turn "
           "optional email back on in <a href='/settings' style='color:#1a66c9'>Settings</a>." if ok
           else "This unsubscribe link isn't valid. If you keep getting emails, reply to one and we'll remove you.")
    page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Tau</title><body style='font-family:system-ui,-apple-system,sans-serif;max-width:520px;margin:12vh auto;padding:0 20px;color:#191B16'>"
            "<h1 style='font-size:20px;letter-spacing:.02em'>Tau</h1><p style='font-size:15px;line-height:1.55'>%s</p>"
            "<p style='font-size:13px;margin-top:20px'><a href='/' style='color:#1a66c9'>Back to Tau</a></p></body>") % msg
    return ("html", page)


# -- routing -----------------------------------------------------------------------

Route = Tuple[str, "re.Pattern[str]", Callable[[Ctx], Any], bool]
ROUTES: List[Route] = [
    (m, re.compile("^%s$" % p), fn, needs_user)
    for m, p, fn, needs_user in [
        ("GET", "/auth/google", google_start, False),
        ("GET", "/auth/google/callback", google_callback, False),
        ("GET", "/auth/dev", dev_login, False),
        ("POST", "/api/logout", logout, False),
        ("POST", "/api/waitlist", waitlist, False),
        ("GET", "/api/me", me, True),
        ("GET", "/api/brokers", broker_connections, True),
        ("GET", "/api/kalshi/perps/live", kalshi_perps_live_account, True),
        ("POST", "/api/kalshi/perps/live/policy", kalshi_perps_live_policy, True),
        ("POST", "/api/kalshi/perps/live/orders", kalshi_perps_live_draft, True),
        ("POST", r"/api/kalshi/perps/live/proposals/(\d+)/preview", kalshi_perps_live_proposal, True),
        ("POST", r"/api/kalshi/perps/live/orders/(\d+)/(submit|refresh|cancel)", kalshi_perps_live_action, True),
        ("GET", "/api/brokers/alpaca/paper", alpaca_paper_account, True),
        ("POST", "/api/brokers/alpaca/paper/orders", alpaca_paper_draft, True),
        ("POST", r"/api/brokers/alpaca/paper/orders/(\d+)/(submit|refresh|cancel)", alpaca_paper_action, True),
        ("POST", r"/api/brokers/(alpaca|robinhood|ibkr)/connect", broker_connect, True),
        ("POST", r"/api/brokers/(alpaca|robinhood|ibkr)/disconnect", broker_disconnect, True),
        ("GET", r"/auth/brokers/(alpaca|robinhood|ibkr)/callback", broker_callback, True),
        ("GET", "/api/dashboard", dashboard, True),
        ("GET", "/api/track-record", get_track_record, True),
        ("GET", "/api/explore", explore_list, True),
        ("GET", "/api/explore/hot", explore_hot, True),
        ("GET", "/api/explore/market", explore_market, True),
        ("GET", "/api/research/context", research_context, True),
        ("GET", "/api/research/estimate", research_estimate, True),
        ("GET", "/api/research/scoreboard", research_scoreboard, True),
        ("GET", "/api/models", models, True),
        ("GET", "/api/runs", list_runs, True),
        ("POST", "/api/runs", create_run, True),
        ("GET", "/api/runs/example", example_run, True),
        ("GET", r"/api/runs/(\d+)", get_run, True),
        ("POST", r"/api/runs/(\d+)/cancel", cancel_run, True),
        ("POST", r"/api/runs/(\d+)/pause", pause_run, True),
        ("POST", r"/api/runs/(\d+)/resume", resume_run, True),
        ("GET", "/api/strategies", list_strategies, True),
        ("GET", r"/api/strategies/(\d+)", get_strategy, True),
        ("POST", r"/api/strategies/(\d+)/whatif", what_if, True),
        ("GET", r"/api/strategies/(\d+)/live-readiness", strategy_live_readiness, True),
        ("POST", r"/api/strategies/(\d+)/share", share_strategy, True),
        ("POST", r"/api/strategies/(\d+)/dig-deeper", dig_deeper, True),
        ("GET", "/api/notifications", notifications, True),
        ("POST", "/api/notifications/read", mark_notifications_read, True),
        ("POST", "/api/ui-theme", set_ui_theme, True),
        ("POST", "/api/email-preferences", set_email_preferences, True),
        ("GET", "/unsubscribe", unsubscribe, False),
        ("GET", "/api/version", lambda ctx: {"v": _static_versions()["app.js"]}, False),
        ("GET", "/api/devlog", lambda ctx: devlog.as_json(), True),
        ("GET", "/api/users/mention", mention_candidates, True),
        ("GET", "/api/deployments", list_deployments, True),
        ("POST", "/api/deployments", create_deployment, True),
        ("POST", r"/api/deployments/(\d+)/(pause|resume|stop)", deployment_action, True),
        ("GET", "/api/chat", get_chat, True),
        ("POST", "/api/chat", post_chat, True),
        ("POST", r"/api/proposals/(\d+)/(approve|reject)", decide_proposal, True),
        ("POST", "/api/settings", settings, True),
        ("POST", "/api/autopilot/live", autopilot_live, True),
        ("POST", "/api/autopilot/kill", autopilot_kill, True),
        ("POST", "/api/autopilot/model", autopilot_model, True),
        ("POST", "/api/autopilot/focus", autopilot_focus, True),
        ("GET", "/api/autopilot/status", autopilot_status, True),
        ("GET", "/api/community", community, True),
        ("POST", "/api/community", create_community_post, True),
        ("POST", r"/api/community/(\d+)/like", like_post, True),
        ("POST", r"/api/community/(\d+)/react", react_post, True),
        ("POST", r"/api/community/(\d+)/edit", edit_community_post, True),
        ("GET", r"/api/community/image/(\d+)", community_image, True),
        ("GET", r"/api/community/(\d+)/comments", post_comments, True),
        ("POST", r"/api/community/(\d+)/comments", create_comment, True),
        ("GET", "/api/billing", billing_state, True),
        ("GET", "/api/billing/receipt", billing_receipt, True),
        ("GET", r"/api/trades\.csv", trades_csv, True),
        ("POST", "/api/billing/setup-intent", billing_setup_intent, True),
        ("POST", "/api/billing/card-added", billing_card_added, True),
        ("POST", "/api/billing/topup", billing_topup, True),
        ("POST", "/api/billing/auto-reload", billing_autoreload, True),
        ("POST", "/api/billing/remove-card", billing_remove_card, True),
        ("GET", "/api/admin", admin_overview, True),
        ("GET", "/api/admin/system", admin_system, True),
        ("POST", "/api/client-errors", report_client_error, False),
        ("GET", "/api/exec/latency", exec_latency, True),
        ("GET", "/api/exec/tca", exec_tca, True),
        ("GET", "/api/admin/kill-switch", admin_kill_switch, True),
        ("POST", "/api/admin/kill-switch", admin_kill_switch_set, True),
        ("GET", "/api/system/code", system_code, True),
        ("POST", "/api/admin/grant", admin_grant, True),
        ("POST", "/api/admin/waitlist", admin_waitlist, True),
        ("GET", "/api/funds", funds, True),
        ("POST", "/api/funds/paper", paper_transfer, True),
        ("POST", "/api/funds/demo", demo_reload, True),
        ("POST", "/api/kalshi-key", save_kalshi_key, True),
        ("POST", "/api/kalshi-key/delete", delete_kalshi_key, True),
        ("POST", "/api/kalshi-dev-key", save_kalshi_dev_key, True),
        ("POST", "/api/kalshi-dev-key/delete", delete_kalshi_dev_key, True),
        ("GET", r"/api/strategies/(\d+)/dev-curve", strategy_dev_curve, True),
        ("POST", r"/api/strategies/(\d+)/delete", delete_strategy, True),
    ]
]


_STATIC_NAMES = ("app.css", "app.js", "session-data.js", "session-chat.js", "research-artifacts.js", "alpaca-paper.js", "alpaca-paper.css", "kalshi-perps-live.js", "kalshi-perps-live.css", "broker-connections.js", "broker-connections.css", "icon.svg", "app.meridian.css", "app.meridian.js", "boot.js")
_VERSIONS_CACHE: Dict[str, Any] = {"sig": None, "out": None}


def _static_versions() -> Dict[str, str]:
    """Content hash per bundle, for the ?v= cache-busters. Re-hashed only when a file's mtime or size
    changes (a deploy), not on every page load and /api/version poll."""
    stats = []
    for name in _STATIC_NAMES:
        try:
            st = (STATIC_DIR / name).stat()
            stats.append((name, st.st_mtime_ns, st.st_size))
        except OSError:
            stats.append((name, 0, -1))
    sig = tuple(stats)
    if _VERSIONS_CACHE["sig"] == sig:
        return _VERSIONS_CACHE["out"]
    out = {}
    for name, _, size in stats:
        p = STATIC_DIR / name
        out[name] = hashlib.sha256(p.read_bytes()).hexdigest()[:10] if size >= 0 else "0"
    _VERSIONS_CACHE.update(sig=sig, out=out)
    return out


def warm_static() -> None:
    """Compress the bundles at startup, so the first request after a deploy (CloudFront filling its
    cache) doesn't wait on it: brotli at its best setting takes about a second for app.js."""
    def size(name: str) -> int:
        try:
            return (STATIC_DIR / name).stat().st_size
        except OSError:
            return 0
    for name in sorted(_STATIC_NAMES, key=size, reverse=True):  # the theme bundles first
        try:
            body = (STATIC_DIR / name).read_bytes()
            if not webperf.compressible("text/", len(body)):
                continue
            key = (name, hashlib.sha256(body).hexdigest()[:10])
            for coding in webperf.static_codings():
                webperf.compress(body, coding, key)
        except Exception as e:  # noqa: BLE001 - a request compresses it on demand instead
            _log_line("[app] warming %s failed (%s)" % (name, type(e).__name__))


def _log_line(line: str) -> None:
    """One write per access line. print() writes the text and its newline separately, so two request
    threads finishing together glued their lines into one ("...404 12ms ...Z[app] GET /api/...")."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


class Handler(BaseHTTPRequestHandler):
    server_version = "Tau"
    sys_version = ""
    # Keep-alive: CloudFront reuses its origin connection instead of paying a fresh TCP handshake
    # (one more edge-to-Virginia round trip) on every API call. Every response sets Content-Length.
    protocol_version = "HTTP/1.1"
    timeout = 75  # idle keep-alive sockets close after this; longer than CloudFront's origin keep-alive
    # Headers and body go out as separate unbuffered writes; on a reused connection Nagle held the
    # body until the client's delayed ACK, adding ~40ms to every response after the first. TCP_NODELAY.
    disable_nagle_algorithm = True

    def handle_one_request(self):
        # A client that resets an idle keep-alive socket raises here, while reading the next request
        # line; the stdlib only catches timeouts, so socketserver printed a traceback for it.
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def log_request(self, code="-", size="-"):
        self._status = code if isinstance(code, int) else int(getattr(code, "value", 0) or 0)

    def log_message(self, fmt, *args):  # errors from the stdlib (bad request line, 501); no query strings
        # Also reached on an idle keep-alive timeout, before any request line set command/path.
        _log_line("[app] %s %s %s" % (getattr(self, "command", None) or "-", urlparse(getattr(self, "path", None) or "").path,
                                      (fmt % args)[:120]))

    def _timed(self, method: str) -> None:
        """One access line per request, with its time: `[app] GET /api/x 200 12ms 2026-10-24T17:50:01Z`.
        No query strings (they can carry OAuth codes)."""
        t0 = time.perf_counter()
        self._status, self._spa = 0, False
        try:
            self._dispatch(method)
        finally:
            ms = (time.perf_counter() - t0) * 1000
            path = urlparse(self.path).path
            webperf.record(webperf.route_key(method, path, self._spa), self._status, ms)
            _log_line("[app] %s %s %s %dms %s" % (method, path, self._status, ms,
                                                  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))

    def cookies(self) -> Dict[str, str]:
        out = {}
        headers = getattr(self, "headers", None)
        for part in ((headers.get("Cookie") if headers else None) or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out[k] = v
        return out

    def _headers(self, status: int, ctype: str, length: int, extra: Optional[List[Tuple[str, str]]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        if self._unread_body():
            # Answered before the body was read (403, 413, 404): those bytes would be parsed as the
            # next request on a keep-alive socket, so tell the client and close it.
            self.send_header("Connection", "close")
            self.close_connection = True
        if SECURE_COOKIES:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for k, v in extra or []:
            self.send_header(k, v)
        self.end_headers()

    def _send(self, status: int, ctype: str, body: bytes, extra: Optional[List[Tuple[str, str]]] = None,
              z_key: Optional[Tuple[str, str]] = None) -> None:
        """Write a whole response, compressed when the client accepts it and it's worth it (JSON, HTML,
        JS, CSS): gzip, or brotli for a static file (z_key = (name, content hash): compressed once per
        version). CloudFront compresses none of it for us: its cache is off for the app, and on
        /static/* it passes on what we compressed. Its /static/* cache key holds the normalized
        Accept-Encoding (br,gzip | gzip | none), so a br body is only ever served to a br client."""
        req_headers = getattr(self, "headers", None)
        if webperf.compressible(ctype, len(body)):
            coding = webperf.pick_encoding(req_headers.get("Accept-Encoding") if req_headers else None,
                                           ctype, len(body), allow_br=z_key is not None)
            extra = list(extra or [])
            if coding is not None:
                body = webperf.compress(body, coding, z_key)
                extra.append(("Content-Encoding", coding))
            # The uncompressed answer varies too: without it a shared cache could keep one copy for all.
            extra.append(("Vary", "Accept-Encoding"))
        self._headers(status, ctype, len(body), extra)
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any, cookies: List[str]) -> None:
        body = json.dumps(payload, default=_json_default, separators=(",", ":")).encode("utf-8")
        extra = [("Cache-Control", "no-store")] + [("Set-Cookie", c) for c in cookies]
        self._send(status, "application/json; charset=utf-8", body, extra)

    def _shell_theme(self, path: str) -> Tuple[Optional[str], List[str]]:
        """The theme to link in the page shell, so a Meridian user never downloads Tau's stylesheet
        and bundle first, and a fresh device never reloads into its account's theme. From the
        tau_ui cookie (set by /api/me and /api/ui-theme), else, signed in on a device without it,
        one session read (and the cookie is set). None = unknown: boot.js goes by localStorage.
        Only Tau has the Terms and Privacy pages. Returns (theme, Set-Cookie headers)."""
        if path in ("/terms", "/privacy"):
            return "tau", []
        cookies = self.cookies()
        theme = cookies.get(UI_COOKIE)
        if theme in UI_THEMES:
            return theme, []
        token = cookies.get(auth.SESSION_COOKIE)
        if not token:
            return None, []
        conn = None
        try:
            conn = get_db_conn()
            user = repo.session_user(conn.cursor(), auth.hash_token(token))
        except Exception:  # noqa: BLE001 - the shell must never fail on this; boot.js falls back
            return None, []
        finally:
            if conn is not None:
                conn.close()
        if user is None:
            return None, []
        theme = user.get("ui_theme") if user.get("ui_theme") in UI_THEMES else "tau"
        return theme, [_ui_cookie(theme)]

    def _shell_boot(self, path: str) -> Tuple[Optional[str], List[str], Optional[Dict]]:
        """(theme, Set-Cookie headers, the account as /api/me answers it or None) for the page shell.

        Signed in, an app page's shell does /api/me's reads itself and carries the reply, so the app
        starts its page's data reads at once instead of after a /api/me round trip of its own: one
        serial round trip fewer on every full load. The account's saved theme picks the bundle (what
        /api/me would have reloaded into). The sign-in and legal pages don't use it, so they keep
        _shell_theme. Any failure falls back to the cookie's theme and the app's own /api/me read."""
        cookies = self.cookies()
        token = cookies.get(auth.SESSION_COOKIE)
        if not token or path in ("/signin", "/terms", "/privacy"):
            return self._shell_theme(path) + (None,)
        theme = cookies.get(UI_COOKIE) if cookies.get(UI_COOKIE) in UI_THEMES else None
        conn = None
        try:
            conn = get_db_conn()
            user = repo.session_user(conn.cursor(), auth.hash_token(token))
            if user is None:
                return theme, [], None
            theme = user.get("ui_theme") if user.get("ui_theme") in UI_THEMES else "tau"
            ctx = Ctx(conn, user, (), {}, {}, self)
            account = me(ctx)
            return theme, ctx.set_cookies, account
        except Exception as e:  # noqa: BLE001 - the shell must never fail on this; the app reads /api/me
            _log_line("[app] shell account read failed (%s); the app reads /api/me" % type(e).__name__)
            return theme, ([_ui_cookie(theme)] if theme and theme != cookies.get(UI_COOKIE) else []), None
        finally:
            if conn is not None:
                conn.close()

    def _send_static(self, path: str, query: str = "") -> None:
        if path == "/.well-known/apple-developer-merchantid-domain-association":
            f = STATIC_DIR / "apple-developer-merchantid-domain-association"
            if f.is_file():
                body = f.read_bytes()
                self._headers(200, "text/plain", len(body), [("Cache-Control", "public, max-age=86400")])
                self.wfile.write(body)
                return
        if SPA_ROUTES.match(path):
            versions = _static_versions()
            theme, cookies, account = self._shell_boot(path)
            # A data block, not a script: CSP's script-src never applies, and boot.js parses it.
            boot_me = "" if account is None else '\n<script type="application/json" id="tau-me">%s</script>' % (
                webperf.embed_json(json.dumps(account, default=_json_default, separators=(",", ":"))))
            css = ("/static/app.meridian.css?v=" + versions["app.meridian.css"] if theme == "meridian"
                   else "/static/app.css?v=" + versions["app.css"])
            bundle = ("" if theme is None else '\n<script src="/static/%s?v=%s" defer></script>' % (
                ("app.meridian.js", versions["app.meridian.js"]) if theme == "meridian" else ("app.js", versions["app.js"])))
            html = (STATIC_DIR / "index.html").read_text("utf-8")
            html = (html.replace("{{ui_css}}", css).replace("{{ui}}", theme or "").replace("{{ui_bundle}}", bundle)
                    .replace("{{boot_me}}", boot_me)
                    .replace("{{css_v}}", versions["app.css"])
                    .replace("{{js_v}}", versions["app.js"])
                    .replace("{{session_v}}", versions["session-data.js"])
                    .replace("{{chat_v}}", versions["session-chat.js"])
                    .replace("{{artifacts_v}}", versions["research-artifacts.js"])
                    .replace("{{brokers_v}}", versions["broker-connections.js"])
                    .replace("{{brokers_css_v}}", versions["broker-connections.css"])
                    .replace("{{paper_js_v}}", versions["alpaca-paper.js"])
                    .replace("{{paper_css_v}}", versions["alpaca-paper.css"])
                    .replace("{{perps_js_v}}", versions["kalshi-perps-live.js"])
                    .replace("{{perps_css_v}}", versions["kalshi-perps-live.css"])
                    .replace("{{icon_v}}", versions["icon.svg"])
                    .replace("{{meridian_css_v}}", versions["app.meridian.css"])
                    .replace("{{meridian_js_v}}", versions["app.meridian.js"])
                    .replace("{{boot_v}}", versions["boot.js"]))
            body = html.encode("utf-8")
            self._spa = True
            # Vary: the shell links the theme from the cookies, so no cache may serve one user's to another.
            # One that carries the account is private: no shared cache (CloudFront) may keep it at all.
            self._send(200, "text/html; charset=utf-8", body,
                       [("Cache-Control", "no-cache" if account is None else "private, no-cache"), ("Vary", "Cookie")]
                       + [("Set-Cookie", c) for c in cookies])
            return
        m = re.match(r"^/static/([a-z0-9_.-]+\.(css|js|svg|png|ico|woff2))$", path)
        f = STATIC_DIR / m.group(1) if m else None
        if f is None or not f.is_file():
            body = b"Not found"
            self._headers(404, "text/plain", len(body))
            self.wfile.write(body)
            return
        ctype = {"css": "text/css", "js": "text/javascript", "svg": "image/svg+xml", "png": "image/png",
                 "ico": "image/x-icon", "woff2": "font/woff2"}[m.group(2)]
        st = f.stat()
        current = _static_versions().get(f.name)
        cache = webperf.static_cache_control(f.name, query, current)
        tag = webperf.etag(current or "%x-%x" % (st.st_mtime_ns, st.st_size))
        req_headers = getattr(self, "headers", None)
        if webperf.etag_matches(req_headers.get("If-None-Match") if req_headers else None, tag):
            # Still the copy the browser holds (an unversioned or other-build URL revalidating): no body.
            self.send_response(304)
            for k, v in (("ETag", tag), ("Cache-Control", cache), ("Vary", "Accept-Encoding")):
                self.send_header(k, v)
            self.end_headers()
            return
        body = f.read_bytes()
        # The validator, the cache lifetime and the compressed copy all go by the bytes read here, so a
        # file replaced between the stat above and this read (a deploy extracting under a running server)
        # can't go out under the old version's ETag, or as the old version compressed.
        digest = hashlib.sha256(body).hexdigest()[:10]
        if current is not None and digest != current:
            cache = webperf.static_cache_control(f.name, query, digest)
            tag = webperf.etag(digest)
        self._send(200, ctype + ("; charset=utf-8" if m.group(2) in ("css", "js", "svg") else ""), body,
                   [("Cache-Control", cache), ("ETag", tag)], z_key=(f.name, digest))

    def _stripe_webhook(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self._body_read = True
        sig = self.headers.get("Stripe-Signature", "")
        try:
            event = billing.verify_webhook(raw, sig)
        except billing.StripeError as e:
            return self._send_json(400, {"error": str(e)}, [])
        try:
            if event.get("type") == "payment_intent.succeeded":
                pi = event["data"]["object"]
                md = pi.get("metadata") or {}
                uid = int(md.get("user_id") or 0)
                credits = md.get("credits")
                if uid and credits and md.get("purpose") in ("topup", "autoreload"):
                    conn = get_db_conn()
                    try:
                        with repo.transaction(conn) as cur:
                            added = repo.add_credit(cur, uid, md["purpose"], credits,
                                                    "Stripe %s" % md["purpose"], stripe_ref=pi["id"])
                        print("[stripe] credited %s to user %s (new=%s, pi=%s)" % (credits, uid, added, pi["id"]), flush=True)
                    finally:
                        conn.close()
        except Exception:
            traceback.print_exc()
        return self._send_json(200, {"received": True}, [])

    def do_GET(self):
        self._timed("GET")

    def do_POST(self):
        self._body_read = False
        self._timed("POST")

    def _unread_body(self) -> bool:
        if getattr(self, "command", None) != "POST" or getattr(self, "_body_read", True):
            return False
        try:
            return int(self.headers.get("Content-Length") or 0) > 0
        except ValueError:
            return True

    def _perf(self, query: str) -> None:
        """Rolling latency/error stats for the on-box watchdog. Loopback only: through CloudFront the
        peer is an edge address, so the public internet always gets the 404."""
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return self._send_json(404, {"error": "Not found"}, [])
        try:
            window = max(60.0, min(86400.0, float(parse_qs(query).get("window", ["900"])[0])))
        except ValueError:
            window = 900.0
        return self._send_json(200, webperf.summary(window), [])

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            return self._send_json(200, {"ok": True}, [])
        if path == "/internal/perf" and method == "GET":
            return self._perf(parsed.query)
        # Canonical-host redirect (old CloudFront URL / www -> the custom domain). Inert unless
        # APP_CANONICAL_HOST is set. Only top-level GETs move, so API/auth calls are never broken.
        if CANONICAL_HOST and method == "GET" and not path.startswith(("/api/", "/auth/")):
            host = (self.headers.get("Host") or "").split(":")[0].lower()
            if host in REDIRECT_HOSTS and host != CANONICAL_HOST:
                self.send_response(301)
                self.send_header("Location", "https://" + CANONICAL_HOST + self.path)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        if path == "/api/stripe/webhook" and method == "POST":
            return self._stripe_webhook()
        route = next(((fn, m.groups(), needs) for meth, m_, fn, needs in ROUTES
                      if meth == method for m in [m_.match(path)] if m), None)
        if route is None:
            if method == "GET" and not path.startswith(("/api/", "/auth/")):
                return self._send_static(path, parsed.query)
            return self._send_json(404, {"error": "Not found"}, [])
        fn, params, needs_user = route
        if method == "POST" and self.headers.get("X-Recursive") != "1":
            return self._send_json(403, {"error": "Missing request header."}, [])
        conn = None
        ctx = None
        try:
            body: Dict[str, Any] = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > BODY_LIMITS.get(path, MAX_BODY):
                    raise ApiError(413, "Request too large.")
                raw = self.rfile.read(length) if length else b""
                self._body_read = True
                body = json.loads(raw) if raw else {}
                if not isinstance(body, dict):
                    raise ApiError(400, "Expected a JSON object.")
            conn = get_db_conn()
            user = None
            token = self.cookies().get(auth.SESSION_COOKIE)
            if token:
                user = repo.session_user(conn.cursor(), auth.hash_token(token))
            if needs_user and user is None:
                raise ApiError(401, "Please sign in.")
            parsed_query = parse_qs(parsed.query, keep_blank_values=path.startswith("/auth/brokers/"))
            if path.startswith("/auth/brokers/") and any(len(v) != 1 for v in parsed_query.values()):
                raise ApiError(400, "Ambiguous brokerage callback. Please reconnect.")
            query = {k: v[0] for k, v in parsed_query.items()}
            ctx = Ctx(conn, user, params, query, body, self)
            result = fn(ctx)
            if isinstance(result, tuple) and result and result[0] == "image":
                _, ctype, data = result
                # Behind sign-in, so private: the browser keeps it, no shared cache serves it to anyone else.
                self._headers(200, ctype, len(data), [("Cache-Control", "private, max-age=31536000, immutable")])
                self.wfile.write(data)
                return
            if isinstance(result, tuple) and result[0] == "download":
                _, fname, ctype, data = result
                body = data.encode("utf-8") if isinstance(data, str) else data
                self._headers(200, ctype, len(body),
                              [("Content-Disposition", 'attachment; filename="%s"' % fname), ("Cache-Control", "no-store")])
                self.wfile.write(body)
                return
            if isinstance(result, tuple) and result[0] == "html":
                body = result[1].encode("utf-8")
                self._headers(200, "text/html; charset=utf-8", len(body), [("Cache-Control", "no-store")])
                self.wfile.write(body)
                return
            if isinstance(result, tuple) and result[0] == "redirect":
                self.send_response(302)
                self.send_header("Location", result[1])
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                for c in ctx.set_cookies:
                    self.send_header("Set-Cookie", c)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send_json(200, result, ctx.set_cookies)
        except ApiError as e:
            self._send_json(e.status, {"error": e.message}, ctx.set_cookies if ctx else [])
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Malformed JSON."}, [])
        except (BrokenPipeError, ConnectionResetError):
            # The browser left before the reply (a navigation, a closed tab). There is no one to send
            # a 500 to, and it isn't a server failure: log it as 499 so /internal/perf's 5xx count
            # only holds real errors, and skip the two tracebacks it used to print.
            self._status, self.close_connection = 499, True
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"error": "Something went wrong on our side. It's been logged."}, [])
        finally:
            if conn is not None:
                conn.close()


class Server(ThreadingHTTPServer):
    # The default listen backlog is 5: twenty pages polling at once had connections refused and
    # retried a second later, the 1.3-1.6s client spikes the server never saw.
    request_queue_size = 128
    daemon_threads = True


def main() -> None:
    if DEV_LOGIN and HOST not in ("127.0.0.1", "localhost"):
        raise SystemExit("APP_DEV_LOGIN=1 is only allowed when bound to localhost.")
    server = Server((HOST, PORT), Handler)
    threading.Thread(target=warm_shared, daemon=True).start()
    threading.Thread(target=warm_static, daemon=True).start()
    paper_checks.start()  # a lapsed paper check is read again in the background
    threading.Thread(target=warm_deploy_boards, name="warm-deploy-boards", daemon=True).start()
    print("Tau on http://%s:%d" % (HOST, PORT), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
