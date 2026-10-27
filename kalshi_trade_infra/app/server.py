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
from app.web import client_errors, page_modules, shell_reads, static_strip, webperf
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
    delete_community_post,
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
    billing_figures,
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
    funds_cash,
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
    explore_spot,
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
from app.web.routes.dashboard import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    _BOOK_SHAPE,
    SINCE_FIRST,
    SINCE_MAX,
    TRACK_RECORD_CACHE_MIN_TRADES,
    TRACK_RECORD_TTL,
    _book_shape,
    _freshness,
    _mode_bucket,
    _since_visit,
    _visit_since,
    dashboard,
    get_track_record,
)
from app.web.routes.account import (  # noqa: F401  (moved; server.py keeps the names for routing and tests)
    mark_notifications_read,
    me,
    notifications,
    set_email_preferences,
    set_ui_theme,
    unsubscribe,
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
        ("GET", "/api/explore/spot", explore_spot, True),
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
        ("GET", "/api/version", lambda ctx: {"v": page_modules.build_version("tau", _static_versions())}, False),
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
        ("POST", r"/api/community/(\d+)/delete", delete_community_post, True),
        ("GET", r"/api/community/image/(\d+)", community_image, True),
        ("GET", r"/api/community/(\d+)/comments", post_comments, True),
        ("POST", r"/api/community/(\d+)/comments", create_comment, True),
        ("GET", "/api/billing", billing_state, True),
        ("GET", "/api/billing/figures", billing_figures, True),
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
        ("GET", "/api/funds/cash", funds_cash, True),
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


_STATIC_NAMES = ("app.css", "app.js", "session-data.js", "session-chat.js", "research-artifacts.js", "alpaca-paper.js", "alpaca-paper.css", "kalshi-perps-live.js", "kalshi-perps-live.css", "broker-connections.js", "broker-connections.css", "icon.svg", "app.meridian.css", "app.meridian.js", "boot.js") + page_modules.FILES
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
            body = static_strip.served(name, body, key[1])
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

    def _shell_boot(self, path: str, query: str = "") -> Tuple[Optional[str], List[str], Optional[Dict], List[Dict]]:
        """(theme, Set-Cookie headers, the account as /api/me answers it or None, the page's first reads
        as [{url, body}]: app.web.shell_reads) for the page shell.

        Signed in, an app page's shell does /api/me's reads itself and carries the reply, so the app
        starts its page's data reads at once instead of after a /api/me round trip of its own: one
        serial round trip fewer on every full load. The account's saved theme picks the bundle (what
        /api/me would have reloaded into). The sign-in and legal pages don't use it, so they keep
        _shell_theme. Any failure falls back to the cookie's theme and the app's own /api/me read."""
        cookies = self.cookies()
        token = cookies.get(auth.SESSION_COOKIE)
        if not token or path in ("/signin", "/terms", "/privacy"):
            return self._shell_theme(path) + (None, [])
        theme = cookies.get(UI_COOKIE) if cookies.get(UI_COOKIE) in UI_THEMES else None
        conn = None
        try:
            conn = get_db_conn()
            user = repo.session_user(conn.cursor(), auth.hash_token(token))
            if user is None:
                return theme, [], None, []
            theme = user.get("ui_theme") if user.get("ui_theme") in UI_THEMES else "tau"
            ctx = Ctx(conn, user, (), {}, {}, self)
            account = me(ctx)
            first, first_cookies = shell_reads.first_reads(path, query, cookies, lambda params, q: Ctx(conn, user, params, q, {}, self))
            return theme, ctx.set_cookies + first_cookies, account, first
        except Exception as e:  # noqa: BLE001 - the shell must never fail on this; the app reads /api/me
            _log_line("[app] shell account read failed (%s); the app reads /api/me" % type(e).__name__)
            return theme, ([_ui_cookie(theme)] if theme and theme != cookies.get(UI_COOKIE) else []), None, []
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
            theme, cookies, account, first = self._shell_boot(path, query)
            # A data block, not a script: CSP's script-src never applies, and boot.js parses it.
            boot_me = "" if account is None else '\n<script type="application/json" id="tau-me">%s</script>' % (
                webperf.embed_json(json.dumps(account, default=_json_default, separators=(",", ":"))))
            # After the scripts, so the browser finds and starts the bundles before these bytes arrive.
            boot_first = "" if not first else '\n<script type="application/json" id="tau-first">%s</script>' % (
                webperf.embed_json(json.dumps(first, default=_json_default, separators=(",", ":"))))
            css = ("/static/app.meridian.css?v=" + versions["app.meridian.css"] if theme == "meridian"
                   else "/static/app.css?v=" + versions["app.css"])
            bundle = ("" if theme is None else '\n<script src="/static/%s?v=%s" defer></script>' % (
                ("app.meridian.js", versions["app.meridian.js"]) if theme == "meridian" else ("app.js", versions["app.js"])))
            html = (STATIC_DIR / "index.html").read_text("utf-8")
            html = (html.replace("{{ui_css}}", css).replace("{{ui}}", theme or "").replace("{{ui_bundle}}", bundle)
                    .replace("{{boot_me}}", boot_me).replace("{{boot_first}}", boot_first)
                    .replace("{{page_preload}}", page_modules.preload(theme, path, versions, account is not None))
                    .replace("{{tau_pages}}", page_modules.versions_attr("tau", versions))
                    .replace("{{mer_pages}}", page_modules.versions_attr("meridian", versions))
                    .replace("{{page_assets}}", page_modules.assets_attr(versions))
                    .replace("{{tau_build}}", page_modules.build_version("tau", versions))
                    .replace("{{mer_build}}", page_modules.build_version("meridian", versions))
                    .replace("{{css_v}}", versions["app.css"])
                    .replace("{{js_v}}", versions["app.js"])
                    .replace("{{session_v}}", versions["session-data.js"])
                    .replace("{{chat_v}}", versions["session-chat.js"])
                    .replace("{{artifacts_v}}", versions["research-artifacts.js"])
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
        body = static_strip.served(f.name, body, digest)  # the bundles and stylesheets without their comments
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
