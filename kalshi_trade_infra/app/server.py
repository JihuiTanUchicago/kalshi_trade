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
from app.web.caches import _ROADS, _TRACK_RECORD, _forget_own_change  # noqa: F401  (shared read caches)
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


# -- read routes ---------------------------------------------------------------


# Global (not per-user) reads that scan big history tables, shared by every request. Prod 2026-10-24:
# history_freshness's GROUP BY over hist_markets made /api/dashboard take 12-14s, and /api/me paid
# for series_with_candles on every page load. Each value is computed once, then served from memory
# while ONE background thread recomputes it on its own connection after the TTL.
_SHARED: Dict[str, Dict[str, Any]] = {}
_SHARED_LOCK = threading.Lock()


def _shared(key: str, ttl: float, fn: Callable[[Any], Any], cur) -> Any:
    now = time.time()
    with _SHARED_LOCK:
        ent = _SHARED.setdefault(key, {"at": 0.0, "busy": False})
        cold = "val" not in ent
        stale = not cold and now - ent["at"] >= ttl and not ent["busy"]
        if stale:
            ent["busy"] = True
    if cold:
        val = fn(cur)
        with _SHARED_LOCK:
            ent.update(val=val, at=time.time())
        return val
    if stale:
        threading.Thread(target=_refresh_shared, args=(ent, fn), daemon=True).start()
    return ent["val"]


def _refresh_shared(ent: Dict[str, Any], fn: Callable[[Any], Any]) -> None:
    conn = None
    try:
        conn = get_db_conn()
        val = fn(conn.cursor())
        with _SHARED_LOCK:
            ent.update(val=val, at=time.time())
    except Exception:
        traceback.print_exc()  # keep serving the last good value; the next request retries
    finally:
        ent["busy"] = False
        if conn is not None:
            conn.close()


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


def _researchable_markets(cur) -> List[Dict]:
    """The research picker's markets (app.services.markets), with the shared series cache."""
    ready = _shared("series_with_candles", 120, lambda c: repo.series_with_candles(c), cur)
    return market_service.researchable_markets(cur, ready)


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


def models(ctx: Ctx):
    """The models a user can pick to run their research, for the dropdown."""
    return {"models": catalog.catalog_json(), "default": catalog.DEFAULT_KEY}


def list_runs(ctx: Ctx):
    # The page polls every 5s and sends back its last answer's version as `since`: while nothing it
    # shows has moved, two statements answer "same" (services.research_list).
    counts = repo.active_run_counts(ctx.cur, ctx.uid, silent_before=_silent_before())
    totals = _research_totals(ctx.cur, ctx.uid)
    v = research_list.version(repo.list_runs_version(ctx.cur, ctx.uid), counts, totals)
    if v is not None and ctx.query.get("since") == v:
        return {"v": v, "same": True}
    # The self-evolving exploration policy (Tau-RSI), summarized read-only for the research
    # index so the cockpit can show the engine getting smarter — same shape as get_run's rsi
    # block (minus the per-run dream line), so the client renders both the same way.
    pol = repo.get_policy(ctx.cur, ctx.uid)
    policy = {"evolved": bool(pol),
              "score": round(float(pol["score"]), 2) if pol else None,
              "base_score": round(pol["base_score"], 2) if (pol and pol.get("base_score") is not None) else None,
              "summary": pol.get("summary") if pol else None,
              "evolved_at": pol["updated_at"] if pol else None}
    runs = repo.list_runs(ctx.cur, ctx.uid)
    _with_spent(ctx.cur, ctx.uid, runs)
    _mark_example(runs)
    for r in runs:  # why a finished session stopped (out of credits, by you, an error, finished): services.run_stop
        r["stop_reason"] = run_stop.stop_reason(r)
        r.pop("out_of_credits", None)
        # A running session silent past the reaper's limit is left out of counts["research_running"]
        # (_silent_before): its row says "Silent", as the run page does, not "Researching" beside "Running 0".
        r["wait"] = _run_wait(r)
    customer_text.run_rows(runs)
    return {"runs": runs, "counts": counts, "policy": policy, "totals": totals, "v": v}


def example_run(ctx: Ctx):
    """{"id": the user's seeded example session, or None}: /example opens it however many sessions
    came after it (the runs list holds only the newest 50)."""
    return {"id": repo.example_run_id(ctx.cur, ctx.uid)}


def _mark_example(runs: List[Dict]) -> None:
    """Flag the example session every account is seeded with: the app ran it, not the user, and
    it cost them nothing, so the list marks it and the headline leaves it out."""
    for r in runs:
        r["example"] = r.get("direction") == repo.DEMO_DIRECTION


def _with_spent(cur, uid: int, runs: List[Dict]) -> None:
    """Stamp each run with `spent_usd`: what its usage debits took from credits so far (the ledger
    rows billed to that run), so a run-until-stopped session shows its running cost."""
    spent = repo.runs_spent(cur, uid, [r["id"] for r in runs])
    for r in runs:
        r["spent_usd"] = credit_usd(spent.get(r["id"], 0.0))


RUN_TOTALS_TTL = 30.0  # seconds; the Research page polls /api/runs every 5s
_RUN_TOTALS: Dict[int, Tuple[float, Dict]] = {}


def _research_totals(cur, uid: int) -> Dict:
    """All-time ideas tested and strategies that passed every gate, for the Research headline.
    The page summed its 50 newest runs, so a busy autopilot (250+ runs a week) read a fraction of
    its real total, and the runs' strategies_passed counter overcounts (it once held 68
    backtest-only rows). Same sources as the autopilot panel's week: research_week and
    strategies_passed_since. The seeded example session is left out: a new account read "Your engine
    has tested 2 hypotheses" for research it never ran; the list marks that row as an example
    instead. Cached per user like the track record."""
    hit = _RUN_TOTALS.get(uid)
    if hit and time.time() - hit[0] < RUN_TOTALS_TTL:
        return hit[1]
    since = repo.now_utc() - timedelta(days=365 * 50)
    val = {"tried": sum(int(r.get("tried") or 0) for r in repo.research_week(cur, uid, since)),
           "passed": repo.strategies_passed_since(cur, uid, since)}
    _RUN_TOTALS[uid] = (time.time(), val)
    return val


LAST_DREAM_TTL = 60.0  # seconds; the run page polls every 2s and a dream lands at most once per run
_LAST_DREAM: Dict[int, Tuple[float, Optional[Dict]]] = {}


def _last_dream(cur, uid: int) -> Optional[Dict]:
    """The run page's "Last check" line (repo.latest_dream_event), cached per user like the research
    totals. That read walked every event of every run the user has (~1s at 6,000 runs and 600k events;
    idx_events_message now narrows it to the dream lines, ~3ms) and the page asked for it on every 2s
    poll. The line can trail a new dream by up to a minute."""
    hit = _LAST_DREAM.get(uid)
    if hit and time.time() - hit[0] < LAST_DREAM_TTL:
        return hit[1]
    val = repo.latest_dream_event(cur, uid)
    _LAST_DREAM[uid] = (time.time(), val)
    return val


def get_run(ctx: Ctx):
    run = repo.get_run(ctx.cur, ctx.uid, _int_param(ctx))
    if run is None or run["kind"] != "research":
        raise ApiError(404, "No such research run.")
    after = int(ctx.query.get("after") or 0)
    # This run's gated strategies, live — so the Hypotheses table fills as each chunk clears
    # the gate (a run_forever run never reaches "succeeded", so we can't wait for it).
    strategies = repo.list_strategies(ctx.cur, ctx.uid, run_id=run["id"])
    pol = repo.get_policy(ctx.cur, ctx.uid)  # the self-evolving exploration policy (Tau-RSI)
    dream = _last_dream(ctx.cur, ctx.uid)
    _with_spent(ctx.cur, ctx.uid, [run])
    _mark_example([run])
    # How long it has waited for a research worker (or gone quiet), timed by the server so a reload
    # doesn't restart the count; once overdue, how many queued sessions a worker takes first.
    wait = _run_wait(run)
    if wait and wait["overdue"] and wait["state"] == "queued":
        wait["ahead"] = repo.research_queue_ahead(ctx.cur, run["id"])
    run["wait"] = wait
    run["stop_reason"] = run_stop.stop_reason(run)  # why it stopped, for a session that ended with nothing to list
    # The run stores the model's key, NULL for the default: the page names the model a customer picked.
    run["model_label"] = catalog.label_for_key(run.get("model"))
    customer_text.run_rows([run])
    return {
        "run": run,
        "events": customer_text.event_rows(_with_gate_lines(repo.run_events(ctx.cur, run["id"], after))),
        "strategies": [_strategy_card(s) for s in strategies if s["run_id"] == run["id"]],
        "rsi": _rsi_block(pol, dream),
    }


def _rsi_block(pol: Optional[Dict], dream: Optional[Dict]) -> Dict:
    """Shape the Tau-RSI exploration-policy panel for the research page: whether the
    user's search policy has evolved, its lineage (prior score -> new score, when it
    was adopted), the plain-English summary of what it changed, and the FULL policy
    SOURCE so the user can inspect the actual decision rules. Falls back to the default
    policy's source when none has evolved yet, so there is always something to inspect.
    The policy is pure, sandboxed Python over the user's own history — it holds no secrets."""
    return {
        "evolved": bool(pol),
        "score": round(float(pol["score"]), 2) if pol else None,
        "base_score": round(pol["base_score"], 2) if (pol and pol.get("base_score") is not None) else None,
        "summary": pol.get("summary") if pol else None,
        "evolved_at": pol["updated_at"] if pol else None,
        "code": pol["code"] if pol else dreaming.DEFAULT_POLICY_SRC,
        "last_dream": dream["message"] if dream else None,
        "last_dream_at": dream["created_at"] if dream else None,
        "min_history": dreaming.MIN_TREE,  # tested ideas the first policy check needs
    }


def create_run(ctx: Ctx):
    market = ctx.body.get("market") or None  # None = let the agent choose the market
    idea = str(ctx.body.get("prompt") or "").strip()[:1000]
    # Optional angle tag; the idea itself is what drives the research now.
    direction = ctx.body.get("direction") or None
    # Which LLM runs this research; None = the server's default model. Validated
    # against the registry so billing only ever meters a model with a known price.
    model = ctx.body.get("model") or None
    if model is not None and model not in catalog.MODELS:
        raise ApiError(400, "Pick a model from the list, or leave it on the default.")
    if market is not None and market not in MARKETS:
        raise ApiError(400, "Pick a market Tau can research, or let the agent choose.")
    unavailable = agent.research_unavailable_reason(market)
    if unavailable:
        raise ApiError(409, unavailable)
    if not idea or len(idea) < 8:
        raise ApiError(400, "Describe your idea in a sentence or two first.")
    if direction is not None and direction not in agent.DIRECTIONS:
        direction = None
    # How hard to search: the agent tests up to `max_hypotheses` (clamped 1..MAX_BUDGET),
    # or keeps going until stopped when `run_forever` is set.
    try:
        max_hyp = int(ctx.body.get("max_hypotheses") or agent.DEFAULT_HYPOTHESES)
    except (TypeError, ValueError):
        max_hyp = agent.DEFAULT_HYPOTHESES
    max_hyp = max(1, min(max_hyp, agent.MAX_BUDGET))
    run_forever = bool(ctx.body.get("run_forever"))
    cur = ctx.cur
    _require_research_capacity(ctx)
    run_id = repo.create_run(cur, ctx.uid, "research", market, direction, idea,
                             max_hypotheses=max_hyp, run_forever=run_forever, model=model)
    return {"id": run_id}


def _require_research_capacity(ctx: Ctx) -> None:
    """Billing + rate gates every research run must clear, whether it's a fresh idea or a
    'dig deeper' branch off a passed strategy. One place so the two paths can't diverge."""
    _require_billing_ready(ctx, "researching")
    # Headroom gate (research only): a session bills post-paid on actual tokens, so starting one on a
    # near-zero balance overshoots into the negative. Require one session's worth up front. Cheap chat
    # keeps the plain >0 gate in _require_billing_ready.
    if billing.configured() and repo.credit_balance(ctx.cur, ctx.uid) < float(billing.MIN_RUN_BALANCE):
        raise ApiError(402, "You need at least $%.2f in credits to start a research session. Add credits "
                            "on the Billing tab." % float(billing.MIN_RUN_BALANCE))
    if repo.count_runs(ctx.cur, ctx.uid, "research", active_only=True) >= MAX_ACTIVE_RESEARCH:
        # "Wait for one to finish" never came true for a session that runs until stopped (the default).
        raise ApiError(429, "You already have %d research sessions going (paused ones count). To start "
                            "another, cancel one from its session page." % MAX_ACTIVE_RESEARCH)
    if MAX_RESEARCH_PER_DAY and repo.count_runs(ctx.cur, ctx.uid, "research", since=repo.now_utc() - timedelta(days=1)) >= MAX_RESEARCH_PER_DAY:
        raise ApiError(429, "Daily research limit reached (%d). It resets over the next 24 hours." % MAX_RESEARCH_PER_DAY)


def dig_deeper(ctx: Ctx):
    """Continue research FROM a strategy the user already passed: branch a new pre-registered
    research line off it (refine parameters within its mechanism, stress-test, extend the thesis)
    instead of the passed strategy being a dead end. Same gates as any research run; the refined
    variants go through the normal gatekeeper."""
    s = _owned_strategy(ctx)
    if s["status"] != "passed":
        raise ApiError(409, "Only a strategy that passed its backtest can be researched deeper.")
    unavailable = agent.research_unavailable_reason(s["market"])
    if unavailable:
        raise ApiError(409, unavailable)
    model = ctx.body.get("model") or None
    if model is not None and model not in catalog.MODELS:
        raise ApiError(400, "Pick a model from the list, or leave it on the default.")
    try:
        max_hyp = int(ctx.body.get("max_hypotheses") or agent.DEFAULT_HYPOTHESES)
    except (TypeError, ValueError):
        max_hyp = agent.DEFAULT_HYPOTHESES
    max_hyp = max(1, min(max_hyp, agent.MAX_BUDGET))
    _require_research_capacity(ctx)
    run_id = agent.dig_deeper_run(ctx.cur, ctx.uid, s, model=model,
                                  max_hypotheses=max_hyp, run_forever=bool(ctx.body.get("run_forever")))
    return {"id": run_id}


def cancel_run(ctx: Ctx):
    if not repo.cancel_run(ctx.cur, ctx.uid, _int_param(ctx)):
        raise ApiError(409, "That run has already finished.")
    return {"ok": True}


def pause_run(ctx: Ctx):
    """Interrupt a running session; the agent holds its state until resumed or cancelled."""
    if not repo.pause_run(ctx.cur, ctx.uid, _int_param(ctx)):
        raise ApiError(409, "Only a running session can be paused.")
    return {"ok": True}


def resume_run(ctx: Ctx):
    """Continue a paused session exactly where it left off."""
    if not repo.resume_run(ctx.cur, ctx.uid, _int_param(ctx)):
        raise ApiError(409, "Only a paused session can be resumed.")
    return {"ok": True}


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
# -- research context, cost estimate and scoreboard -----------------------------


def _research_context(feed_markets: List[Dict]) -> List[Dict]:
    """Fold the cached explore feed down to just the markets research can target: per
    researchable series, the live activity (contracts live + 24h volume + open interest)
    and the most-active contract's mid + price trace. Read-only — no DB, no orders — so the
    dispatch picker shows what's liquid/moving instead of being chosen blind. Markets with
    nothing in the feed are simply omitted; as the market universe grows this needs no change."""
    by_series: Dict[str, List[Dict]] = {}
    for m in feed_markets:
        s = m.get("s")
        if s:
            by_series.setdefault(s, []).append(m)
    out: List[Dict] = []
    for mk in MARKETS.values():
        rows = by_series.get(mk.series)
        if not rows:
            continue
        top = max(rows, key=lambda r: _efloat(r.get("v24")))
        out.append({
            "key": mk.key, "series": mk.series, "label": mk.label,
            "contracts": len(rows),
            "vol24": round(sum(_efloat(r.get("v24")) for r in rows)),
            "oi": round(sum(_efloat(r.get("oi")) for r in rows)),
            "mid": _feed_mid(top), "trace": top.get("h") or [],
        })
    out.sort(key=lambda r: r["vol24"], reverse=True)
    return out


SESSION_COST_MIN_OWN = 3       # the user's own finished sessions needed before their median is used
SESSION_COST_MIN_TYPICAL = 5   # sessions on a model before the server-wide median is shown at all
SESSION_COST_TTL = 600.0       # seconds the server-wide medians are cached
_TYPICAL_SESSION_COST: List[Any] = [0.0, {}]


def _median(xs: List[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _typical_session_costs(cur) -> Dict[str, float]:
    """Median credits per finished research session for each model, over every user's sessions of
    the last 14 days. Only the per-model median leaves this function, and only for a model with
    SESSION_COST_MIN_TYPICAL sessions, so no single user's spend can be read off it. Cached."""
    at, val = _TYPICAL_SESSION_COST
    if time.time() - at < SESSION_COST_TTL:
        return val
    by_model: Dict[str, List[float]] = {}
    for model, cost in repo.recent_session_costs(cur, repo.now_utc() - timedelta(days=14)):
        key = catalog.resolve(model).key  # a NULL model ran on the catalog default
        if len(by_model.setdefault(key, [])) < 200:  # the newest 200 per model
            by_model[key].append(cost)
    val = {k: credit_usd(_median(v)) for k, v in by_model.items() if len(v) >= SESSION_COST_MIN_TYPICAL}
    _TYPICAL_SESSION_COST[:] = [time.time(), val]
    return val


def research_estimate(ctx: Ctx):
    """What a research session usually costs, for the hint beside Start session: the median credits
    of the user's own last 10 finished sessions, or (with fewer than 3) the server-wide median for
    each model. Read-only; what a run is charged does not change."""
    own = repo.finished_session_costs(ctx.cur, ctx.uid, 10)
    return {"yours": credit_usd(_median(own)) if len(own) >= SESSION_COST_MIN_OWN else None,
            "sessions": len(own), "typical": _typical_session_costs(ctx.cur),
            "per_hour": _forever_hourly(ctx.cur, ctx.uid)}


FOREVER_RATE_MIN_HOURS = 1.0  # hours of your own run-until-stopped research before your rate is used
_TYPICAL_FOREVER_RATE: List[Any] = [0.0, {}]


def _forever_hourly(cur, uid: int) -> Dict:
    """What a run-until-stopped session costs an hour at recent rates, for the line beside Start:
    {"yours": your own such sessions of the last 14 days, pooled (dollars over hours billed), once
    they add up to FOREVER_RATE_MIN_HOURS; "typical": {model key: the median session's hourly rate
    over every user's, for a model with SESSION_COST_MIN_TYPICAL sessions}}. Read-only, from what the
    ledger debited; cached server-wide like the typical session cost."""
    since = repo.now_utc() - timedelta(days=14)
    mine = repo.forever_session_rates(cur, since, uid, 50)
    hours = sum(h for _m, _s, h in mine)
    yours = round(sum(s for _m, s, _h in mine) / hours, 2) if hours >= FOREVER_RATE_MIN_HOURS else None
    at, typical = _TYPICAL_FOREVER_RATE
    if time.time() - at >= SESSION_COST_TTL:
        by_model: Dict[str, List[float]] = {}
        for model, spent, h in repo.forever_session_rates(cur, since):
            by_model.setdefault(catalog.resolve(model).key, []).append(spent / h)
        typical = {k: round(_median(v), 2) for k, v in by_model.items() if len(v) >= SESSION_COST_MIN_TYPICAL}
        _TYPICAL_FOREVER_RATE[:] = [time.time(), typical]
    return {"yours": yours, "typical": typical}


def research_context(ctx: Ctx):
    """Live book context for the researchable markets, for the Research cockpit's picker."""
    data = _explore_feed()
    return {"at": data.get("at"), "markets": _research_context(data.get("markets") or [])}


def research_scoreboard(ctx: Ctx):
    """How the user's research loop is doing: funnel, spend, efficiency and why ideas die, in total,
    per market family and per day (app/research/rsi.py). ?days= (1-60, default 7)."""
    try:
        days = min(max(int(ctx.query.get("days") or 7), 1), 60)
    except ValueError:
        days = 7
    uid = ctx.uid
    # 4.4s p50 on prod (every run's verdict events re-read and re-classified per request), so the
    # board is memoized per (user, days) and refreshed in the background: at most a minute stale.
    return _shared("rsi_board:%s:%s" % (uid, days), SCOREBOARD_TTL_S,
                   lambda cur: _research_scoreboard(cur, uid, days), ctx.cur)


SCOREBOARD_TTL_S = 60.0


def _research_scoreboard(cur, uid: int, days: int) -> Dict:
    from app.research import rsi, rsi_playbook
    board = rsi.load_scoreboard(cur, days, uid)
    try:
        board["autopilot"] = agent.autopilot_scorecard(board, agent.focus_tokens(repo.get_user(cur, uid)))
    except Exception:  # noqa: BLE001 - informational
        board["autopilot"] = None
    board["cards"] = board["cards"][-50:]
    board["playbooks"] = rsi_playbook.summary(cur, uid)
    from app import rsi_scout
    try:
        board["scout"] = rsi_scout.ranking(cur, 10)
    except Exception:  # noqa: BLE001 - the scan table may not exist before the first deploy's schema run
        board["scout"] = []
    try:
        board["paper"] = rsi.paper_outcomes(cur, uid)
    except Exception:  # noqa: BLE001 - informational; the research half of the board still renders
        board["paper"] = None
    from app.research import tournament
    try:
        board["tournament"] = tournament.standings(cur, uid)
    except Exception:  # noqa: BLE001 - informational; the table may not exist before the first schema run
        board["tournament"] = None
    try:
        board["early_exits"] = repo.early_exit_scorecard(cur, uid)
    except Exception:  # noqa: BLE001 - informational
        board["early_exits"] = None
    from app.research import rsi_repair
    board["data_requests"] = rsi_repair.summary(cur, uid)
    return board


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


def main() -> None:
    if DEV_LOGIN and HOST not in ("127.0.0.1", "localhost"):
        raise SystemExit("APP_DEV_LOGIN=1 is only allowed when bound to localhost.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    threading.Thread(target=warm_shared, daemon=True).start()
    threading.Thread(target=warm_static, daemon=True).start()
    paper_checks.start()  # a lapsed paper check is read again in the background
    threading.Thread(target=warm_deploy_boards, name="warm-deploy-boards", daemon=True).start()
    print("Tau on http://%s:%d" % (HOST, PORT), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
