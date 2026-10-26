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
from app.services import backtest_check, book_memo, customer_text, gate_explain, paper_checks, research_list, run_stop, trade_why
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
from app.web.views import _gate_lines, _live_balance, _open_book, _with_gate_lines  # noqa: F401  (shared presenters)
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
        "credit_balance": round(reads.balance(), 4),
        "min_run_balance": float(billing.MIN_RUN_BALANCE),  # the headroom a research run needs to start
        "perps_live_available": kalshi_perps_trading.enabled(),  # hide the Funds perps box when live perps are off
        "markets": _researchable_markets(ctx.cur),
        "directions": [{"key": k, **v} for k, v in agent.DIRECTIONS.items()],
        # The research form's model list (the same as GET /api/models), so /research doesn't wait on
        # that read before it starts its own.
        "models": models(ctx),
    }


def _start_of_day_utc() -> datetime:
    return repo.now_utc().replace(hour=0, minute=0, second=0)


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


# The engine pauses a demo deployment with this in its reason when the user has no demo key.
_DEMO_KEY_PAUSE = "demo (sandbox) key"


def _demo_health(cur, uid: int, deps: List[Dict], stake: Optional[float] = None) -> Optional[Dict]:
    """Why the demo book can't trade, as one plain line and the one thing to do, or None when nothing
    known stops it. A demo deployment looks healthy (running, capital, a P&L) while every order it
    sends is refused, so the pages that show demo say this instead:
      - demo_key: a demo deployment is on (or the engine paused it for the key) and no demo key is saved;
      - demo_funds: the Kalshi demo account holds less than one stake, so Kalshi refuses its orders.
    `deps` are deployment rows (with spec). `stake` asks about a strategy that could go on demo but
    isn't there yet (the strategy page's next rung), so funds are checked even with nothing running.
    The balance read is the cached demo GET (demo_twins.balance_cached); unknown is never a problem."""
    from app.trading import demo_twins

    demo = [d for d in deps if d["mode"] == "demo"]
    active = [d for d in demo if d["status"] == "running"
              or (d["status"] == "paused" and _DEMO_KEY_PAUSE in (d.get("status_reason") or ""))]
    if not active and stake is None:
        return None
    if repo.get_kalshi_dev_key(cur, uid) is None:
        if not active:
            return None  # nothing on demo; the deploy button already says to add the key
        return {"code": "demo_key", "need": "your Kalshi demo key",
                "line": "Demo isn't trading: your Kalshi demo key isn't connected. Add it on the Funds page.",
                "action": {"label": "Add demo key", "href": "/funds"}}
    stakes = [float(_spec_sizing(d)["stake"]) for d in active
              if d["status"] == "running" and _spec_sizing(d).get("stake") is not None]
    if stake is not None:
        stakes.append(float(stake))
    if not stakes:
        return None
    cash = demo_twins.balance_cached(cur, uid)
    least = min(stakes)
    if cash is None or cash >= least:
        return None
    has = "has $0.00" if cash < 0.005 else "has %s, less than one %s stake" % (_usd(cash), _usd(least))
    return {"code": "demo_funds", "need": "demo funds: your Kalshi demo account %s" % has,
            "line": "Demo isn't trading: your Kalshi demo account %s. Add demo funds on Kalshi's demo site." % has,
            "action": {"label": "Open Kalshi demo", "href": demo_twins.KALSHI_DEMO_SITE}}


def _spec_sizing(row: Dict) -> Dict:
    """A strategy or deployment row's spec sizing, {} when an older or seeded spec has none (display only)."""
    spec = row.get("spec")
    sizing = spec.get("sizing") if isinstance(spec, dict) else None
    return sizing if isinstance(sizing, dict) else {}


def _usd(v: float) -> str:
    return "$%s" % format(round(float(v), 2), ",.2f")


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
    ledger = repo.paper_ledger_summary(cur, ctx.uid)  # balance, deposits and reset: one read
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
    return {
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
    }


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
            "spent": act.get("spent") if billing.configured() else None,
            "milestones": act.get("milestones") or {"passed": [], "live_ready": []}}


TRACK_RECORD_TTL = 60.0  # seconds; the record moves only when a trade closes
# A book with fewer trades than this is read fresh on every request: its grouped read is a few rows
# through idx_pos_user, and a new user's first trade showed up only after the cached empty record
# expired (up to a minute after the board above it showed the trade).
TRACK_RECORD_CACHE_MIN_TRADES = 200
# (built at, payload, trades read, the book's shape the dashboard had seen when it was built)
_TRACK_RECORD: Dict[int, Tuple[float, Dict, int, Optional[Tuple]]] = {}
# {user id: the book's shape at the dashboard's last read} (_book_shape): one closed-trade count per
# mode and the open count. A busy book's cached record is rebuilt once the dashboard has seen a trade
# open or close that the record predates, so the two never disagree for the rest of the minute.
_BOOK_SHAPE: Dict[int, Tuple] = {}


def _book_shape(closed: Dict[str, int], open_count: int) -> Tuple:
    return tuple(sorted(closed.items())), int(open_count)


def _forget_own_change(uid: int, strategy_id: Optional[int] = None) -> None:
    """Drop the user's cached reads after a change the web app made itself (a deploy, a pause, resume
    or stop, an approved proposal, the kill switch, a removed strategy): the track record, whose
    by-strategy rows carry each deployment's status, and the Deploy board's road to live and paper
    checks (services.paper_checks), so the board never shows a check from before the change. A change
    to one strategy's deployment passes `strategy_id`: only that strategy's paper evidence reads it."""
    _TRACK_RECORD.pop(uid, None)
    paper_checks.forget(uid, strategy_id)
    for key in [k for k in _ROADS if k[0] == uid]:
        _ROADS.pop(key, None)


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


def _paper_strategy_ids(deps: List[Dict]) -> set:
    """The strategies with a paper deployment that isn't stopped (running, or paused with paper)."""
    return {d["strategy_id"] for d in deps if d["mode"] == "paper" and d["status"] != "stopped"}


def _deployment_out(d: Dict, curve: List, unrealized: Optional[float] = None, paper_sids: Optional[set] = None) -> Dict:
    res = d.get("result") or {}
    return {
        # A demo deployment of a strategy that is also on paper is its demo copy (app.trading.demo_twins makes
        # them): the row says what it copies and why its fills differ from paper's.
        "demo_copy": d["mode"] == "demo" and d["strategy_id"] in (paper_sids or ()),
        "id": d["id"], "strategy_id": d["strategy_id"], "title": d["title"], "direction": d["direction"],
        "market": d["market"], "mode": d["mode"], "status": d["status"], "status_reason": d["status_reason"],
        "status_why": _status_why(d),
        "realized_pnl": round(float(d["realized_pnl"]), 2), "closed_trades": d["closed_trades"], "wins": d["wins"],
        "unrealized_pnl": unrealized, "open_positions": d["open_positions"], "created_at": d["created_at"], "curve": curve,
        "stake": _spec_sizing(d).get("stake"), "max_positions": _spec_sizing(d).get("max_positions"),
        "backtest": {"out_of_sample": res.get("out_of_sample"), "capital": res.get("capital")},
    }


def _status_why(d: Dict) -> Optional[str]:
    """Why a deployment isn't running, in plain words, for its row and its strategy page. The stored
    reason read "By you", "Kill switch" or an engine line ("force-closed: position down 33.0% >= stop
    30.0%") after the stake, and "By you" didn't say whether you paused it or removed it. A reason
    that is already a sentence is kept as written."""
    raw = (d.get("status_reason") or "").strip()
    if d.get("status") == "running" or not raw:
        return None
    if raw == "By you" and d.get("status") == "stopped":
        return "You removed it"
    if raw not in ("By you", "Approved agent proposal", "Kill switch") and not re.search(r"% >= (?:stop|limit) ", raw):
        return customer_text.clean(raw, "Stopped automatically" if d.get("status") == "stopped" else "Paused automatically")
    clause = _pause_clause(raw)
    return clause[:1].upper() + clause[1:]


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
        r["spent_usd"] = round(spent.get(r["id"], 0.0), 4)


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
    # The run stores the model's key, NULL for the default: the page names the model a customer picked.
    run["model_label"] = catalog.label_for_key(run.get("model"))
    customer_text.run_rows([run])
    return {
        "run": run,
        "events": customer_text.event_rows(_with_gate_lines(repo.run_events(ctx.cur, run["id"], after))),
        "strategies": [_strategy_card(s) for s in strategies if s["run_id"] == run["id"]],
        "rsi": _rsi_block(pol, dream),
    }


def _gate_tints(status: Optional[str], exp: Dict) -> Dict:
    """services.gate_explain's per-figure pass/fail, or none (every figure neutral) for a record it can't read."""
    try:
        return gate_explain.strategy_tints(status, exp)
    except (TypeError, ValueError, KeyError, AttributeError):
        return {}


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


def _needs_card(ctx: Ctx, reads: Optional[billing.Reads] = None) -> bool:
    """True when payments are live but the user has no card on file. Agent usage
    is metered per token, so we require a card before any run — the free credits
    unlock the moment one is saved."""
    if not billing.configured():
        return False
    cust = (reads or billing.Reads(ctx.cur, ctx.uid)).customer()
    return not (cust and cust.get("default_pm_id"))


def _auto_reload_terms(ctx: Ctx, reads: Optional[billing.Reads] = None) -> Optional[Dict]:
    """What auto-reload will charge the saved card, for the autopilot card's cost line: the credits
    added, the card charge (credits plus the top-up fee) and the balance that triggers it. The same
    floors billing.auto_reload applies. None when payments are off, no card is saved, or it is off."""
    if not billing.configured():
        return None
    cust = (reads or billing.Reads(ctx.cur, ctx.uid)).customer()
    if not (cust and cust.get("default_pm_id") and cust.get("auto_reload")):
        return None
    amount = max(billing.AUTORELOAD_AMOUNT, Decimal(str(cust.get("reload_amount") or billing.AUTORELOAD_AMOUNT)))
    threshold = max(billing.AUTORELOAD_THRESHOLD, Decimal(str(cust.get("reload_threshold") or billing.AUTORELOAD_THRESHOLD)))
    return {"amount": float(amount), "charge": billing.topup_charge_cents(amount) / 100, "threshold": float(threshold)}


def _require_billing_ready(ctx: Ctx, gerund: str) -> None:
    if _needs_card(ctx):
        raise ApiError(402, "Add a payment method on the Billing tab before %s. Your $%d in free credits "
                            "unlock the moment a card is on file — you won't be charged until they run out."
                            % (gerund, int(billing.FREE_BONUS)))
    if billing.configured() and repo.credit_balance(ctx.cur, ctx.uid) <= 0:
        raise ApiError(402, "You're out of credits. Add credits on the Billing tab to keep %s." % gerund)


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


def _strategy_card(s: Dict) -> Dict:
    res = s.get("result") or {}
    return {
        "id": s["id"], "run_id": s["run_id"], "parent_id": s["parent_id"], "market": s["market"],
        "direction": s["direction"], "title": s["title"], "thesis": s["thesis"], "status": s["status"],
        "created_at": s["created_at"], "hypotheses_tried": s.get("hypotheses_tried"),
        "in_sample": res.get("in_sample"), "out_of_sample": res.get("out_of_sample"),
        "equity": res.get("equity"), "capital": res.get("capital"),
        "stake": _spec_sizing(s).get("stake"),
        "side": (s["spec"].get("perpetual") or {}).get("side") if specmod.is_perpetual_spec(s["spec"]) else s["spec"].get("side"),
        **({"kind": "perpetual", "research_only": True} if specmod.is_perpetual_spec(s["spec"]) else {}),
        "deployed": bool(s.get("active_deps")), "deploy_live": bool(s.get("live_deps")),
        "shared_from": s.get("shared_from_name") if s.get("shared_from_user_id") else None,
        "example": s.get("direction") == repo.DEMO_DIRECTION,  # from the seeded example session
    }


def _mark_fields(p: Dict) -> Dict:
    """Live mark-to-market for one open position from the engine-stamped mark_price (the YES bid
    on a YES position, the YES ask on a NO one). None until the engine's first mark after entry."""
    qty = int(p["qty"])
    cost = qty * float(p["entry_price"]) + float(p.get("entry_fee") or 0)
    mark = p.get("mark_price")
    if mark is None:
        return {"mark": None, "value": None, "unrealized": None, "mark_ts": None}
    mark = float(mark)
    # A YES contract sells at the YES bid (mark); a NO contract at its own bid, 1 - yes_ask (1 - mark).
    value = round(qty * (mark if p["side"] == "yes" else 1.0 - mark), 2)
    return {"mark": mark, "value": value, "unrealized": round(value - cost, 2), "mark_ts": p.get("mark_ts")}


def _with_marks(rows: List[Dict]) -> List[Dict]:
    for p in rows:
        p.update(_mark_fields(p))
    return rows


def _with_why(rows: List[Dict], deps: List[Dict]) -> List[Dict]:
    """Each position's one-line entry/exit reason (app.services.trade_why), from the strategy specs
    of the deployments the request already read: no extra statement. A position of a stopped
    deployment (not in `deps`) gets its exit reason only."""
    specs = {d["id"]: d.get("spec") for d in deps}
    for p in rows:
        p["why"] = trade_why.trade_why(p, specs.get(p.get("deployment_id")))
    return rows


def list_strategies(ctx: Ctx):
    q = ctx.query
    direction, status, market = q.get("direction") or None, q.get("status") or None, q.get("market") or None
    search = (q.get("q") or "").strip()[:80] or None  # cap: a search box, not a query language
    deployed = q.get("deployed") in ("1", "true")
    try:
        page = max(0, int(q.get("page") or 0))
    except ValueError:
        page = 0
    per = 50
    counts = repo.count_strategies(ctx.cur, ctx.uid, direction, market, search, deployed)  # true per-status totals, not a capped page
    # Default ("Kept") view hides rejected/void — the big-run noise — but keeps every row in the
    # DB (the ledger counts them for DSR/FDR). An explicit status chip overrides and shows it.
    hide_noise = status is None
    noise = sum(counts.get(s, 0) for s in repo.NOISE_STATUSES)
    # The seeded example's strategies are out of the counts but still listed (marked "example").
    ex = counts.get("examples") or {}
    shown_ex = ex.get(status, 0) if status else sum(n for s, n in ex.items() if s not in repo.NOISE_STATUSES)
    matched = (counts.get(status, 0) if status else counts["total"] - noise) + shown_ex
    rows = repo.list_strategies(ctx.cur, ctx.uid, direction, status, market, limit=per, offset=page * per,
                                q=search, deployed=deployed, hide_noise=hide_noise)
    cards = [_strategy_card(s) for s in rows]
    _attach_real_records(ctx.cur, ctx.uid, cards)
    return {"strategies": cards, "counts": counts,
            "matched": matched, "page": page, "per": per, "pages": (matched + per - 1) // per}


def _attach_real_records(cur, uid: int, cards: List[Dict]) -> None:
    """Stamp each deployed card with what it has actually done since deploying (realized P&L and
    closed trades across its active deployments), so the list shows reality next to the backtest.
    Money books are never summed: a strategy with a live deployment reports its live deployments
    only (beside its Live badge), otherwise its paper ones, with its demo (sandbox) book beside them
    under "demo" rather than added in. One query, and only when the page has a deployed strategy."""
    if not any(c.get("deployed") for c in cards):
        return
    real: Dict[int, Dict[str, Dict]] = {}
    for d in book_memo.deployments_for_display(book_memo.BookMemo(cur, uid)):
        r = real.setdefault(d["strategy_id"], {}).setdefault(d["mode"], {"pnl": 0.0, "trades": 0, "open": 0, "paused": False})
        r["paused"] = r["paused"] or d.get("status") == "paused"  # often auto-paused; the list flags it
        r["pnl"] += float(d["realized_pnl"] or 0)
        r["trades"] += int(d["closed_trades"] or 0)
        r["open"] += int(d["open_positions"] or 0)
    for c in cards:
        books = real.get(c["id"]) if c.get("deployed") else None
        if books:
            mode = next((m for m in ("live", "paper", "demo") if m in books), None)
            if mode is None:  # only a mode this list doesn't show
                continue
            r = books[mode]
            c["real"] = {**r, "pnl": round(r["pnl"], 2), "live": mode == "live", "mode": mode}
            if mode == "paper" and "demo" in books:
                dm = books["demo"]
                c["real"]["demo"] = {"pnl": round(dm["pnl"], 2), "trades": dm["trades"], "open": dm["open"]}


def _owned_strategy(ctx: Ctx) -> Dict:
    s = repo.get_strategy(ctx.cur, ctx.uid, _int_param(ctx))
    if s is None:
        raise ApiError(404, "No such strategy.")
    return s


DELETE_MODES = ("paper", "demo", "live")


def _delete_block(open_positions: List[Dict]) -> Optional[str]:
    """Why a strategy can't be deleted yet, from its open positions (every deployment, stopped ones
    included, any mode), or None. Stopping a deployment leaves its positions open, and the engine
    settles and flattens positions through their strategy row: deleting the strategy first would
    leave them open for good, with paper cash already paid for them."""
    if not open_positions:
        return None
    n = len(open_positions)
    by_mode = {m: sum(1 for p in open_positions if p["mode"] == m) for m in DELETE_MODES}
    parts = ", ".join("%s: %d" % (m, k) for m, k in by_mode.items() if k)
    return ("This strategy still holds %d open position%s (%s). They'll close at settlement; delete it after that."
            % (n, "" if n == 1 else "s", parts))


def delete_strategy(ctx: Ctx):
    """Remove a strategy from the user's inventory. Blocked while it's deployed (stop the deployment
    first) and while any of its deployments, in any mode, still holds an open position."""
    s = _owned_strategy(ctx)
    if any(d["strategy_id"] == s["id"] for d in repo.list_deployments(ctx.cur, ctx.uid, include_stopped=False)):
        raise ApiError(409, "Stop this strategy's deployment before deleting it.")
    block = _delete_block(repo.positions_for_strategy(ctx.cur, ctx.uid, s["id"], "open"))
    if block:
        raise ApiError(409, block)
    repo.delete_strategy(ctx.cur, ctx.uid, s["id"])
    _forget_own_change(ctx.uid, s["id"])
    return {"ok": True}


def share_strategy(ctx: Ctx):
    """Share a strategy with another Tau user by email. Copies it into their inventory
    (not revocable) and notifies them. The recipient must already have an account."""
    s = _owned_strategy(ctx)
    email = str(ctx.body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise ApiError(400, "Enter the email your friend signs in with.")
    recipient = repo.user_by_email(ctx.cur, email)
    if not recipient:
        raise ApiError(404, "No Tau account uses that email yet — they need to sign in first.")
    if recipient["id"] == ctx.uid:
        raise ApiError(400, "That's your own account.")
    new_id = repo.share_strategy(ctx.cur, s["id"], ctx.uid, recipient["id"])
    if new_id is None:
        return {"ok": True, "already": True}  # idempotent: they already have this one
    sender = (repo.get_user(ctx.cur, ctx.uid) or {}).get("name") or "A friend"
    repo.add_notification(ctx.cur, recipient["id"], "share",
                          "%s shared the strategy “%s” with you." % (sender, s["title"]),
                          "/strategies/%d" % new_id)
    return {"ok": True}


def notifications(ctx: Ctx):
    rows = customer_text.notification_rows(repo.list_notifications(ctx.cur, ctx.uid))
    return {
        "unread": repo.count_unread_notifications(ctx.cur, ctx.uid),
        "items": [{"id": r["id"], "kind": r["kind"], "body": r["body"], "link": r["link"],
                   "created_at": r["created_at"], "read": r["read_at"] is not None} for r in rows],
    }


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


def _exp_num(row: Dict, key: str) -> Optional[float]:
    v = row.get(key)
    return None if v is None else float(v)


def _exp_bool(row: Dict, key: str) -> Optional[bool]:
    v = row.get(key)
    return None if v is None else bool(v)


def _exp_int(row: Dict, key: str) -> Optional[int]:
    v = row.get(key)
    return None if v is None else int(v)


def _phase_block(row: Optional[Dict], holdout: bool = False) -> Optional[Dict]:
    """Shape one app_experiment_results row (validation or holdout) into the §D block."""
    if not row:
        return None
    out = {
        "classification": row.get("classification"),
        "n_trades": _exp_int(row, "n_trades"),
        "mean_net_return": _exp_num(row, "mean_net_return"),
        "ci_lo": _exp_num(row, "ci_lo"),
        "ci_hi": _exp_num(row, "ci_hi"),
        "p_value": _exp_num(row, "p_value"),
        "psr": _exp_num(row, "psr"),
        "dsr": _exp_num(row, "dsr"),
        "sharpe": _exp_num(row, "sharpe"),
        "net_pnl": _exp_num(row, "net_pnl"),
        "fdr_alpha_i": _exp_num(row, "fdr_alpha_i"),
        "fdr_reject": _exp_bool(row, "fdr_reject"),
        "bh_reject": _exp_bool(row, "bh_reject"),
        "placebo_p": _exp_num(row, "placebo_p"),
        "n_trials_audited": _exp_int(row, "n_trials_audited"),
        "equity_curve": row.get("equity_curve"),
    }
    if holdout:
        out["consumed"] = bool(row.get("holdout_consumed"))
    return out


def _rationale(raw) -> Dict:
    """economic_rationale is a TEXT column the gatekeeper stores as structured JSON (§D:
    mechanism / negative_control / competing_explanations / folds). Fall back to treating
    it as a plain mechanism string for anything older or free-form."""
    try:
        d = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else None)
    except (ValueError, TypeError):
        d = None
    if not isinstance(d, dict):
        return {"mechanism": raw or None, "negative_control": None,
                "competing_explanations": None, "folds": []}
    return {
        "mechanism": d.get("mechanism") or raw,
        "negative_control": d.get("negative_control"),
        "competing_explanations": d.get("competing_explanations") or d.get("challenger"),
        "folds": d.get("folds") or [],
    }


def _experiment_block(cur, strategy_id: int, experiment_id: Optional[int] = None) -> Optional[Dict]:
    """The §D research-paper `experiment` block for a strategy, or None when the strategy
    predates the rigorous-research pipeline (no ledger row). Resolves by the strategy's stored
    experiment_id first (robust link), falling back to the legacy strategy_id lookup. Additive by
    design: a None here leaves the rest of the detail page intact — never a regression."""
    rec = research_repo.experiments_for_strategy(cur, strategy_id, experiment_id)
    if not rec:
        return None
    exp = rec["experiment"]
    results = rec["results"] or []
    latest = lambda phase: next((r for r in reversed(results) if r.get("phase") == phase), None)
    val_row = latest("validation")
    val = _phase_block(val_row)
    hold = _phase_block(latest("holdout"), holdout=True)
    rat = _rationale(exp.get("economic_rationale"))
    overall = results[-1]["classification"] if results else None
    return {
        "classification": overall,
        "registered_at": exp.get("registered_at"),
        "mechanism": rat["mechanism"],
        "negative_control": rat["negative_control"],
        "competing_explanations": rat["competing_explanations"],
        "falsification_criteria": exp.get("falsification_criteria"),
        "null_hypothesis": exp.get("null_hypothesis"),
        "alt_hypothesis": exp.get("alt_hypothesis"),
        "primary_metric": exp.get("primary_metric"),
        "planned_test": exp.get("planned_test"),
        "min_sample": _exp_int(exp, "min_sample"),
        "cost_assumptions": exp.get("cost_assumptions"),
        "planned_n_tests": _exp_int(exp, "planned_n_tests"),
        "correction_method": exp.get("correction_method"),
        "n_trials_audited": (val or {}).get("n_trials_audited"),
        "validation": val,
        "holdout": hold,
        # Prefer the gatekeeper's recorded cross-day folds (validation phase); fall back to any
        # folds embedded in the older rationale JSON so pre-pipeline experiments still render.
        "folds": (val_row or {}).get("folds") or rat["folds"],
    }


def get_strategy(ctx: Ctx):
    s = _owned_strategy(ctx)
    out = _strategy_card(s)
    res = s.get("result") or {}
    deps = repo.list_deployments_for_display(ctx.cur, ctx.uid, strategy_id=s["id"])
    held = repo.positions_for_strategy(ctx.cur, ctx.uid, s["id"], "open")
    exp = _experiment_block(ctx.cur, s["id"], s.get("experiment_id"))
    if exp:
        # Which research-paper figures their gate passed or missed, by the same checks as
        # why_failed, so a figure is red exactly when its line says it missed (display only).
        exp = dict(exp, gate_tints=_gate_tints(s.get("status"), exp))
    out.update(
        spec=s["spec"], rules=specmod.describe(s["spec"]), gates=res.get("gates"), dataset=res.get("dataset"),
        recent_trades=res.get("recent_trades"),
        # The backtest columns' "too few trades to tell skill from luck" caution (display only): the app's
        # one noise level for a trade count, deliberately stricter than the gate's floor, which it names.
        sample_caution={"min_trades": track_record.MIN_TRADES, "gate_min_oos_trades": backtest.GATES["min_oos_trades"]},
        experiment=exp,
        # One plain line per gate it missed: measured, needed, and what to try next (display only).
        why_failed=_gate_lines(gate_explain.for_strategy, s.get("status"), res, exp),
        deployments=[_deployment_out(d, []) for d in deps],
        holdings=[{
            "ticker": p["ticker"], "side": p["side"], "qty": int(p["qty"]), "mode": p["mode"],
            "entry_price": float(p["entry_price"]),
            "cost": round(int(p["qty"]) * float(p["entry_price"]) + float(p["entry_fee"] or 0), 2),
            "market_close_time": p["market_close_time"], **_mark_fields(p), "why": trade_why.trade_why(p, s["spec"]),
        } for p in held],
        # The Remove button's reason while any deployment of it still holds a position (delete_strategy's guard).
        delete_block=_delete_block(held),
        # The ladder's demo rung: why its demo book can't trade, or (not on demo yet) what demo needs.
        demo_health=None if specmod.has_perpetual_market(s["spec"], s.get("market")) else
        _demo_health(ctx.cur, ctx.uid, deps, stake=(s["spec"].get("sizing") or {}).get("stake")),
        # Each book's realized per-trade P&L against the backtest's, one line per book (display only).
        # The page shows them under its current deployments, so with none there is nothing to read.
        backtest_checks=_backtest_checks(ctx.cur, ctx.uid, {s["id"]: s}).get(s["id"], []) if deps else [],
    )
    return out


BACKTEST_CHECK_TTL = 60.0  # seconds; a book's figures move only when one of its trades closes
_BACKTEST_CHECKS: Dict[Tuple[int, Tuple[int, ...]], Tuple[float, Dict[int, List[Dict]]]] = {}


def _backtest_checks(cur, uid: int, strategies: Dict[int, Dict],
                     memo: Optional[book_memo.BookMemo] = None) -> Dict[int, List[Dict]]:
    """{strategy_id: [one comparison per book]} (services.backtest_check) for {strategy_id: a row with
    the strategy's spec and result}: each book's realized per-trade P&L and win rate against the
    strategy's backtest, never summed across books. A per-user TTL cache, since the Deploy board
    polls; display only."""
    if not strategies:
        return {}
    key = (uid, tuple(sorted(strategies)))
    hit = _BACKTEST_CHECKS.get(key)
    if hit and time.time() - hit[0] < BACKTEST_CHECK_TTL:
        return hit[1]
    # The Deploy board's sums for every strategy it lists are kept (book_memo); one strategy's are cheap.
    stats = (book_memo.book_trade_stats(memo, list(strategies)) if memo is not None
             else repo.book_trade_stats(cur, uid, list(strategies)))
    val = {sid: backtest_check.checks(stats.get(sid, {}), s.get("result"),
                                      ((s.get("spec") or {}).get("sizing") or {}).get("stake"))
           for sid, s in strategies.items()}
    if len(_BACKTEST_CHECKS) > 5000:
        _BACKTEST_CHECKS.clear()
    _BACKTEST_CHECKS[key] = (time.time(), val)
    return val


def what_if(ctx: Ctx):
    s = _owned_strategy(ctx)
    if specmod.has_perpetual_market(s["spec"], s.get("market")):
        raise ApiError(409, "Bitcoin perpetual research uses fixed scenario costs; binary slippage controls do not apply.")
    if s["status"] == "rejected":
        raise ApiError(409, "This hypothesis was rejected in-sample; there is no full backtest to vary.")
    # Default the slippage knob to the real demo-book slippage measured for this
    # market (clamped to the knob's bounds), so omitting it scores against the
    # measured cost rather than 0. The frontend still sends the dial's value.
    measured = kalshi_dev.measured_slippage_cents(s["market"])
    default_slip = 0.0 if measured is None else max(0.0, min(5.0, measured))
    w = backtest.WhatIf(
        fee_multiplier=_num(ctx.body, "fee_multiplier", 0.0, 3.0, 1.0),
        slippage_cents=_num(ctx.body, "slippage_cents", 0.0, 5.0, default_slip),
        stake=_num(ctx.body, "stake", 1.0, 500.0, _spec_sizing(s).get("stake")),
    )
    try:
        res = backtest.evaluate(s["spec"], backtest.dataset(s["market"]), w)
    except Exception:
        raise ApiError(503, "Backtest data is not available right now.")
    return {k: res[k] for k in ("in_sample", "out_of_sample", "equity", "gates", "passed", "capital")}


def strategy_dev_curve(ctx: Ctx):
    """Realized out-of-sample curve replayed READ-ONLY against the Kalshi DEMO
    (dev) environment, for the sim-vs-real second line on the equity chart.
    Degrades to {"dev_curve": None} (no second line) when dev replay is
    unconfigured or the demo host/data is unavailable - it never errors the page."""
    s = _owned_strategy(ctx)
    if specmod.has_perpetual_market(s["spec"], s.get("market")):
        return {"dev_curve": None, "reason": "Bitcoin perpetuals are research-only; event-contract demo replay is unavailable."}
    if not (s.get("result") or {}).get("out_of_sample"):
        return {"dev_curve": None, "reason": "This hypothesis has no out-of-sample backtest to replay."}
    out = kalshi_dev.dev_curve_for_strategy(s["id"], s["spec"], s["market"])
    if out is None:
        return {"dev_curve": None, "reason": kalshi_dev.unavailable_reason()}
    return out


# -- deployments ---------------------------------------------------------------


def list_deployments(ctx: Ctx):
    # Display reads: the deployments' totals summed before their rows are joined, and curves only
    # for the deployments listed (not every stopped one's history). Same payload as before.
    memo = book_memo.BookMemo(ctx.cur, ctx.uid)  # position sums kept until the positions change
    deps = book_memo.deployments_for_display(memo)
    curves = book_memo.deployment_curves(memo, [d["id"] for d in deps])
    checks = _backtest_checks(ctx.cur, ctx.uid, {d["strategy_id"]: d for d in deps}, memo)
    roads = _deploy_roads(ctx.cur, ctx.uid, deps, memo)
    paper_sids = _paper_strategy_ids(deps)
    return {
        # Each row carries its own book's backtest comparison (same strategy, same mode), and a paper
        # row its strategy's paper record toward the live check (all its paper deployments, as the
        # strategy page counts it).
        "deployments": [{**_deployment_out(d, curves.get(d["id"], []), paper_sids=paper_sids),
                         "backtest_check": next((c for c in checks.get(d["strategy_id"], []) if c["mode"] == d["mode"]), None),
                         "road": roads.get(d["strategy_id"]) if d["mode"] == "paper" else None}
                        for d in deps],
        "demo_health": _demo_health(ctx.cur, ctx.uid, deps),
        "open_positions": _with_why(_with_marks(repo.user_positions(ctx.cur, ctx.uid, "open")), deps),
        "recent_closed": _with_why(repo.user_positions(ctx.cur, ctx.uid, "closed", 20), deps),
    }


def create_deployment(ctx: Ctx):
    cur = ctx.cur
    s = repo.get_strategy(cur, ctx.uid, int(ctx.body.get("strategy_id") or 0))
    mode = ctx.body.get("mode")
    if s is None:
        raise ApiError(404, "No such strategy.")
    if s["status"] not in ("passed", "failed", "rejected"):
        raise ApiError(409, "This strategy isn't ready to deploy.")
    if specmod.is_code_spec(s["spec"]):
        # Arbitrary agent-authored code runs ONLY in the research sandbox; the paper/live/demo
        # engine evaluates the DSL rule (specmod.entries), so code strategies are research-only.
        # Matches the same guard on agent.act's deploy/deploy_live path.
        raise ApiError(409, "This is an agent-authored code strategy — those are research-only and "
                            "can't be deployed to the trading engine.")
    mkt = MARKETS.get(s["market"])
    if mkt is not None and not mkt.deployable:
        raise ApiError(409, "%s is research-only for now — you can backtest it, but live/paper "
                            "deployment isn't open for it yet." % mkt.label)
    if mode not in ("paper", "live", "demo"):
        raise ApiError(400, "Choose paper, demo or live.")
    # Cross-contract deploy gate. Single-market cross (cross_strike/calendar) deploys on paper/demo.
    # Multi-market cross (relative value across DIFFERENT markets) deploys in any mode only when
    # every leg is deployable and the legs share a cadence (it rides engine.tick_cross_markets).
    # Additive and fail-closed — every real-money live guard below still runs, in order, unweakened.
    cross_block = engine.cross_deploy_block(s["spec"], mode)
    if cross_block:
        raise ApiError(409, cross_block)
    if mode == "live":
        # §E.5: the manual live path must clear the SAME gatekeeper gate as the autopilot path
        # (agent.act "deploy_live"), so a manual deploy can't bypass it. Additive and fail-closed —
        # every existing live guard below is kept, in order, unweakened.
        if not agent._is_deployment_candidate(cur, s["id"]):
            raise ApiError(409, "This strategy isn't cleared for live yet — the gatekeeper must promote it to a "
                                "deployment candidate (validation, one-time holdout, diversification) first.")
        # Same paper record the autopilot's deploy_live needs (agent._proven_on_paper): realistic
        # fills, net up, 48h+ of record, a clear bootstrap edge. Additive and fail-closed.
        proven, why = agent._proven_on_paper(cur, ctx.uid, s["id"])
        if not proven:
            raise ApiError(409, "This strategy hasn't proven itself on paper yet: %s." % why)
        # The global live switch, the Kalshi-key requirement and the typed confirmation are the
        # other guardrails.
        if not engine.LIVE_TRADING_ENABLED:
            raise ApiError(409, "Live trading isn't open yet. Deploy on paper for now.")
        if repo.get_kalshi_key(cur, ctx.uid) is None:
            raise ApiError(409, "Connect your Kalshi account on the Account page first.")
        if ((s.get("spec") or {}).get("side") or "yes").lower() != "yes" and not engine.NO_SIDE_LIVE_ENABLED:
            # Staged rollout: NO-side live mechanics are validated on the demo sandbox first.
            raise ApiError(409, "NO-side live trading is still being validated on the demo sandbox — "
                                "deploy this on demo or paper for now.")
        if ctx.body.get("confirm") != "LIVE":
            raise ApiError(400, "Type LIVE to confirm real-money trading.")
    elif mode == "demo":
        # Demo = Kalshi's sandbox exchange, no real money. It only needs the user's own demo key;
        # the demo kernel's host guard makes the production exchange structurally unreachable.
        if repo.get_kalshi_dev_key(cur, ctx.uid) is None:
            raise ApiError(409, "Add your Kalshi demo (sandbox) key on the Funds page first.")
    if sum(1 for d in repo.list_deployments(cur, ctx.uid) if d["status"] != "stopped") >= MAX_ACTIVE_DEPLOYMENTS:
        raise ApiError(429, "You can run up to %d deployments at once." % MAX_ACTIVE_DEPLOYMENTS)
    dep_id = repo.create_deployment(cur, ctx.uid, s["id"], s["market"], mode)
    _forget_own_change(ctx.uid, s["id"])
    where = {"live": "LIVE money", "demo": "the demo (sandbox) exchange"}.get(mode, "paper")
    repo.add_chat(cur, ctx.uid, "system", "Deployed %s on %s." % (s["title"], where))
    return {"id": dep_id}


def _paper_pace(deps: List[Dict], strategy_id: int, trades: int, events: int, span_hours: float) -> Dict:
    """When this strategy's paper record could hold the trades, events and hours the live check counts,
    at the pace it trades (rsi.paper_eta_days, as the autopilot panel estimates it, with the record's
    own first-to-last span). Counted from its oldest running paper deployment; a strategy with none
    running is not adding to its record, so it has no estimate. Display only: it says nothing about
    whether the record will be up or clear the edge and demo checks by then, and it gates nothing."""
    from app.research import rsi
    running = [d for d in deps if int(d["strategy_id"]) == int(strategy_id) and d["mode"] == "paper"
               and d["status"] == "running" and isinstance(d.get("created_at"), datetime)]
    if not running:
        return {"running": False, "eta_days": None, "trades_per_day": None, "rate_from": None}
    dep = min(running, key=lambda d: d["created_at"])
    rate = rsi.paper_trade_rate(dep, trades)
    return {"running": True, "eta_days": rsi.paper_eta_days(dep, trades, events=events, span_hours=span_hours),
            "trades_per_day": round(rate["per_day"], 1) if rate else None, "rate_from": rate["source"] if rate else None}


def _paper_record(trips: List[Dict]) -> Dict:
    """Trades, separate events and first-to-last hours of a strategy's realistic paper round trips,
    counted as agent.paper_evidence counts them, for the Deploy board's road-to-live line."""
    span_h = 0.0
    if trips:
        start = trips[0].get("opened_at")
        end = max((t.get("closed_at") for t in trips if t.get("closed_at")), default=None)
        if start and end:
            span_h = max(0.0, (end - start).total_seconds() / 3600.0)
    return {"trades": len(trips), "events": len(agent._trip_events(trips)), "span_hours": round(span_h, 1)}


ROAD_TTL = 30.0  # seconds; the Deploy board polls every 10s and a record moves only when a trade closes
_ROADS: Dict[Tuple, Tuple[float, Dict]] = {}
# Each strategy's `failing` is kept until its record changes (services.paper_checks).
_FAILING = paper_checks.KEPT


def _deploy_roads(cur, uid: int, deps: List[Dict], memo: Optional[book_memo.BookMemo] = None) -> Dict[int, Dict]:
    """{strategy_id: its paper record toward the live check} for the strategies running or paused on
    paper: the counts the strategy page's Road to live shows (trades, events, hours, each with what
    the check needs) and when they could be met at its pace. Once those are in, `failing` lists the
    checks still refusing it (agent.paper_evidence's keys, "candidate" for the gatekeeper); empty means
    its record clears every check, which never moves it to live money by itself. Display only, cached
    per user for ROAD_TTL."""
    sids = sorted({int(d["strategy_id"]) for d in deps if d["mode"] == "paper"})
    if not sids:
        return {}
    key = (uid, tuple(sids), tuple(sorted((int(d["id"]), d["status"]) for d in deps if d["mode"] == "paper")))
    hit = _ROADS.get(key)
    if hit and time.time() - hit[0] < ROAD_TTL:
        return hit[1]
    # The Deploy board passes its request's kept position sums (book_memo).
    trips = (book_memo.paper_round_trips_by_strategy(memo, sids) if memo is not None
             else repo.paper_round_trips_by_strategy(cur, uid, sids))
    out = {}
    for sid in sids:
        rec = _paper_record(trips.get(sid, []))
        road = {**rec, "trades_needed": agent.MIN_REALISTIC_PAPER_TRADES, "events_needed": agent.MIN_PAPER_EVENTS,
                "span_needed_hours": agent.MIN_PAPER_SPAN_HOURS,
                **_paper_pace(deps, sid, rec["trades"], rec["events"], rec["span_hours"])}
        if (rec["trades"] >= agent.MIN_REALISTIC_PAPER_TRADES and rec["events"] >= agent.MIN_PAPER_EVENTS
                and rec["span_hours"] >= agent.MIN_PAPER_SPAN_HOURS):
            # Once the counts are in, the rest of the check decides: the same reads as Road to live, so
            # the board can say it clears (or which checks are left) without the user opening each page.
            road["failing"] = paper_checks.failing(cur, uid, sid, (rec["trades"], rec["events"], rec["span_hours"]))
        out[sid] = road
    if len(_ROADS) > 5000:
        _ROADS.clear()
    _ROADS[key] = (time.time(), out)
    return out


def strategy_live_readiness(ctx: Ctx):
    """Road to live: every gate between this strategy and real money, with progress. Read-only;
    the same functions the deploy paths enforce, so this view can never disagree with them.
    `pace` (display only) says when the record could hold enough trades, events and hours."""
    s = repo.get_strategy(ctx.cur, ctx.uid, _int_param(ctx))
    if s is None:
        raise ApiError(404, "No such strategy.")
    candidate = bool(agent._is_deployment_candidate(ctx.cur, s["id"]))
    paper = agent.paper_evidence(ctx.cur, ctx.uid, s["id"])
    pace = _paper_pace(repo.list_deployments_brief(ctx.cur, ctx.uid), s["id"], int(paper["trades"]),
                       int(paper.get("events") or 0), float(paper.get("span_hours") or 0))
    live_ok, live_why = agent.live_autopilot_ok(ctx.cur, ctx.user)
    blocking = ("" if candidate else "the gatekeeper hasn't cleared it as a deployment candidate") \
        or paper["why"] or live_why
    return {
        "strategy_id": s["id"], "status": s["status"],
        "deployment_candidate": candidate,
        "paper": paper,
        "live_autopilot": {"ok": live_ok, "why": live_why},
        "ready": candidate and paper["ready"] and live_ok,
        "blocking": blocking,
        "pace": pace,
    }


def deployment_action(ctx: Ctx):
    dep_id, action = _int_param(ctx), ctx.params[1]
    dep = repo.get_deployment(ctx.cur, ctx.uid, dep_id)
    if dep is None:
        raise ApiError(404, "No such deployment.")
    if action == "resume" and specmod.has_perpetual_market(dep.get("spec") or {}, dep.get("market")):
        raise ApiError(409, "Bitcoin perpetuals are research-only and cannot be resumed for trading.")
    status = {"pause": "paused", "resume": "running", "stop": "stopped"}[action]
    if dep["status"] == "stopped":
        raise ApiError(409, "This deployment is stopped.")
    if action == "resume" and dep["mode"] == "live" and not engine.LIVE_TRADING_ENABLED:
        raise ApiError(409, "Live trading isn't open yet.")
    repo.set_deployment_status(ctx.cur, ctx.uid, dep_id, status, "By you")
    _forget_own_change(ctx.uid, dep.get("strategy_id"))  # unknown: all of theirs
    return {"ok": True, "status": status}


# -- chat ------------------------------------------------------------------------


def get_chat(ctx: Ctx):
    after = int(ctx.query.get("after") or 0)
    run = repo.active_agent_run(ctx.cur, ctx.uid)
    wait = _run_wait(run)
    # agent_wait: the oldest chat/review in flight has waited or gone quiet past the reaper's limit,
    # so the panel's pulse says that instead of "working" for as long as it lasts.
    return {"messages": customer_text.chat_rows(repo.chat_messages(ctx.cur, ctx.uid, after)), "agent_busy": run is not None,
            "agent_wait": wait if wait and wait["overdue"] else None}


def post_chat(ctx: Ctx):
    content = str(ctx.body.get("content") or "").strip()
    if not content:
        raise ApiError(400, "Say something first.")
    if len(content) > 2000:
        raise ApiError(400, "Keep messages under 2,000 characters.")
    cur = ctx.cur
    _require_billing_ready(ctx, "chatting with the agent")
    if repo.count_runs(cur, ctx.uid, "chat", since=repo.now_utc() - timedelta(hours=1)) >= MAX_CHAT_PER_HOUR:
        raise ApiError(429, "That's a lot of messages this hour. Give the agent a minute.")
    msg_id = repo.add_chat(cur, ctx.uid, "user", content)
    cur.execute("SELECT COUNT(*) AS n FROM app_agent_runs WHERE user_id=%s AND kind='chat' AND status='queued'", (ctx.uid,))
    if int(cur.fetchone()["n"]) == 0:  # a queued run will read this message too
        repo.create_run(cur, ctx.uid, "chat")
    return {"id": msg_id}


def decide_proposal(ctx: Ctx):
    pid, decision = _int_param(ctx), ctx.params[1]
    conn = ctx.conn
    # Broker execution commits its durable claim before HTTP. Do not hold the
    # generic proposal transaction around a network request or bypass the
    # paper service's scope, ownership, cash and duplicate-send checks.
    candidate = repo.get_proposal(ctx.cur, ctx.uid, pid)
    if candidate and candidate["kind"] == "kalshi_perps_live":
        return _perps_live_call(kalshi_perps_trading.decide_proposal, conn, ctx.uid, pid, decision)
    if candidate and candidate["kind"] == "alpaca_paper":
        return _paper_call(alpaca_paper.decide_proposal, conn, ctx.uid, pid, decision)
    with repo.transaction(conn) as tx:
        p = repo.get_proposal(tx, ctx.uid, pid)
        if p is None:
            raise ApiError(404, "No such proposal.")
        if not repo.decide_proposal(tx, pid, "applied" if decision == "approve" else "rejected"):
            raise ApiError(409, "This proposal was already decided.")
        if decision == "approve":
            agent.apply_proposal(tx, ctx.uid, p)
        repo.add_chat(tx, ctx.uid, "system", "You %s the proposal." % ("approved" if decision == "approve" else "declined"))
    _forget_own_change(ctx.uid)
    return {"ok": True}


def settings(ctx: Ctx):
    if "autopilot" in ctx.body:
        on = ctx.body["autopilot"] is True
        was_on = bool(ctx.user.get("autopilot"))
        repo.set_autopilot(ctx.cur, ctx.uid, on)
        repo.add_chat(ctx.cur, ctx.uid, "system",
                      "Autopilot is %s." % ("ON: the agent may research, deploy and tune paper strategies, pause anything, "
                                             "and adjust your risk and execution controls itself — all within safe bounds"
                                             if on else "OFF: the agent will only propose; you approve every change"))
        if not on:  # turning off autopilot also turns off live autopilot (it depends on it)
            repo.set_autopilot_live(ctx.cur, ctx.uid, False)
        elif not was_on:  # first move now, not on the next heartbeat
            worker.enqueue_review_on_switch_on(ctx.cur, ctx.uid)
    return {"ok": True}


def autopilot_live(ctx: Ctx):
    """Enable/disable LIVE autopilot. Enabling needs a typed confirmation AND the server live
    switch + a connected Kalshi key; disabling is one click."""
    on = ctx.body.get("on") is True
    if on:
        if ctx.body.get("confirm") != "LIVE AUTOPILOT":
            raise ApiError(400, "Type LIVE AUTOPILOT to let the agent trade real money on its own.")
        if not engine.LIVE_TRADING_ENABLED:
            raise ApiError(403, "Live trading isn't enabled on this server yet.")
        if repo.get_kalshi_key(ctx.cur, ctx.uid) is None:
            raise ApiError(400, "Connect your Kalshi key on the Funds page first.")
        if not ctx.user.get("autopilot"):
            raise ApiError(400, "Live autopilot can only be turned on after autopilot (paper) is on. It moves "
                           "a strategy to real money only after the strategy has proven itself on paper, "
                           "and autopilot is what runs it there.")
    repo.set_autopilot_live(ctx.cur, ctx.uid, on)
    if on:
        sides = "paper strategies of any side (YES or NO)" if engine.NO_SIDE_LIVE_ENABLED else \
                "proven YES-side paper strategies (NO-side is still being validated)"
        msg = "LIVE autopilot is ON — the agent may promote %s to real money, and tune your risk, " \
              "execution and strategy parameters, all within your caps and loss guard." % sides
    else:
        msg = "LIVE autopilot is OFF."
    repo.add_chat(ctx.cur, ctx.uid, "system", msg)
    return {"ok": True, "autopilot_live": on}


def autopilot_kill(ctx: Ctx):
    """Kill switch: turn live autopilot off and pause every running live deployment now."""
    repo.set_autopilot_live(ctx.cur, ctx.uid, False)
    paused = 0
    for d in repo.list_deployments(ctx.cur, ctx.uid):
        if d["mode"] == "live" and d["status"] == "running":
            repo.set_deployment_status(ctx.cur, ctx.uid, d["id"], "paused", "Kill switch")
            paused += 1
    _forget_own_change(ctx.uid)
    repo.add_chat(ctx.cur, ctx.uid, "system", "Kill switch: live autopilot off, %d live deployment(s) paused." % paused)
    return {"ok": True, "paused": paused}


def _research_activity(cur, uid: int) -> Dict:
    """What research is doing for the autopilot float: the markets being researched now and the
    last 7 days' tested/passed counts, so a quiet panel reads as working, not stuck. One bounded read."""
    since = repo.now_utc() - timedelta(days=7)
    # Researching now means a run queued for a worker or one that is beating. A run the user paused
    # isn't researching, and a running run silent past the reaper's limit (its worker died) left
    # "Right now it's researching Bitcoin" on every page for hours after the work stopped.
    active = [r for r in repo.list_runs(cur, uid, limit=50) if r.get("status") == "queued"
              or (r.get("status") == "running" and not (_run_wait(r) or {}).get("overdue"))]
    # The week's totals come from one aggregate, not the 50 newest runs: a busy autopilot starts
    # 250+ runs a week, and the capped list told Todd it had tested 73 ideas when it was hundreds.
    # Passed counts strategies that cleared every gate: an old run's counter held 68 backtest-only.
    week = repo.research_week(cur, uid, since)
    return {"active": [MARKETS[r["market"]].label if r.get("market") in MARKETS else (r.get("market") or "a market it's still picking")
                       for r in active],
            "tested_7d": sum(int(r.get("tried") or 0) for r in week),
            "passed_7d": repo.strategies_passed_since(cur, uid, since),
            "runs_7d": sum(int(r.get("runs") or 0) for r in week),
            # What research actually debited this week (the credit ledger), not tokens re-priced:
            # re-pricing billed a screen-arm run's screen tokens at the developer model's rate.
            "cost_7d": round(repo.research_spent_since(cur, uid, since), 2)}


def _plural(n: int, one: str, many: str = "") -> str:
    return "{:,} {}".format(n, one if n == 1 else (many or one + "s"))


def _autopilot_story(d: Dict) -> List[str]:
    """The autopilot panel's plain-language summary: what it's doing now, why there may be no
    trades yet, and what has to happen before real money. Built only from the status payload
    `d` (no extra reads), so it can never disagree with the figures shown under it."""
    if not d.get("autopilot"):
        return ["Autopilot is off. Turn it on and it researches, tests and runs strategies on paper by itself, "
                "with no real money."]
    if d.get("billing_blocked"):
        return []  # the panel's billing warning already says why it's paused
    research = d.get("research") or {}
    idle = (d.get("idle") or {}).get("code")
    lines = [_autopilot_now(d)]
    if d.get("focus"):
        lines.append("It sticks to the focus you set: %s." % ", ".join(d["focus"]))
    tested, passed = int(research.get("tested_7d") or 0), int(research.get("passed_7d") or 0)
    if tested:
        cost = float(research.get("cost_7d") or 0)
        lines.append("This week it tested %s%s and %s." % (
            _plural(tested, "idea"), " for ${:,.2f}".format(cost) if cost >= 0.01 else "",
            "none has passed its tests yet. That's normal: most ideas fail. Each session's page names the test "
            "each idea missed and what to try next" if not passed else "{:,} passed".format(passed)))
    paper, prog = int(d.get("paper_running") or 0), d.get("paper_progress")
    if idle and (idle == "engine" or not paper):
        pass  # the idle line (shown above the story) says why nothing trades; this one would repeat or contradict it
    elif not paper:
        lines.append("Nothing is trading on paper yet. A strategy has to pass the research tests first.")
    elif prog and int(prog.get("trades") or 0) > 0:
        lines.append("%s on paper (pretend money). The furthest along has %d of %d trades and is %s." % (
            _plural(paper, "strategy is", "strategies are"), int(prog["trades"]), int(prog["trades_needed"]),
            ("up $%.2f" % prog["net_pnl"]) if prog["net_pnl"] >= 0 else ("down $%.2f" % -prog["net_pnl"])))
    elif int(d.get("paper_open") or 0):
        # Bought but not yet settled: "none has traded yet" told Todd nothing happened while his
        # first four rain contracts sat open (2026-10-25).
        lines.append("%s on paper (pretend money). %s open, waiting to settle; none has closed yet." % (
            _plural(paper, "strategy is", "strategies are"),
            _plural(int(d["paper_open"]), "position is", "positions are")))
    elif d.get("paper_waiting"):
        lines.append("%s on paper (pretend money), but none has traded yet." % _plural(paper, "strategy is", "strategies are"))
    else:
        lines.append("%s on paper (pretend money), but none has traded yet. Each one waits for its own "
                     "setup, which can take hours." % _plural(paper, "strategy is", "strategies are"))
    if paper and prog and prog.get("soonest_days") is not None:
        # "When could this make real money?" is the question behind the panel; answer it with the
        # pace each one actually trades at, and say it only counts if the record is up by then.
        days = float(prog["soonest_days"])
        when = "about a day" if days < 1.5 else "about %d days" % round(days)
        lines.append("At the pace they trade, the soonest one could have enough for the live check is %s "
                     "(%s), and only if it's up by then." % (when, _short_title(prog.get("soonest_title"))))
    t_line = _tournament_line(d.get("tournament"))
    if t_line:
        lines.append(t_line)
    # A stalled engine left last decision's waits on screen as if they were current.
    lines += _waiting_lines(d.get("paper_waiting") or []) if paper and idle != "engine" else []
    lines += _paused_lines(d.get("paused_recent") or [])
    stop_line = _stop_line(d.get("early_exits_7d") or {})
    if stop_line:
        lines.append(stop_line)
    limit = float(d.get("daily_loss_limit") or 0)
    if int(d.get("live_running") or 0):
        lines.append("%s trading real money." % _plural(int(d["live_running"]), "strategy is", "strategies are"))
    elif limit > 0 and float(d.get("today_live_pnl") or 0) <= -limit:
        # The kill switch turned live autopilot off and paused live deployments; the panel used to
        # go back to "Nothing trades real money until..." as if live had never run.
        lines.append("Live trading stopped for today: today's live loss of $%.2f reached your $%.2f daily limit, "
                     "so live autopilot switched itself off and live strategies were paused. Paper keeps running."
                     % (-float(d["today_live_pnl"]), limit))
    else:
        lines.append("Nothing trades real money until a strategy makes money on paper over at least %d trades "
                     "from %d separate events and %d hours, and you turn on live autopilot." % (
                         agent.MIN_REALISTIC_PAPER_TRADES, agent.MIN_PAPER_EVENTS, int(agent.MIN_PAPER_SPAN_HOURS)))
    return lines


def _autopilot_now(d: Dict) -> str:
    """The story's first line: what the autopilot is doing right now."""
    active = (d.get("research") or {}).get("active") or []
    if active:
        names = [n for n in dict.fromkeys(active) if n != "a market it's still picking"]  # two runs on one market read as one
        now = ("Right now it's researching %s." % (
            names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1])) if names \
            else "Right now it's picking a market to research."
    elif d.get("reviewing"):
        now = "Right now it's reviewing the markets to pick its next move. Each move shows up in its activity feed."
    elif d.get("review_wait"):
        w = d["review_wait"]
        mins = max(1, int(w.get("seconds") or 0) // 60)
        now = ("Its next review has waited %s for a free worker, longer than usual. It starts when one frees up."
               % _span(mins)) if w.get("state") == "queued" else \
              ("Its review hasn't checked in for %s. A review that quiet is normally stopped, and the next one "
               "starts on schedule." % _span(mins))
    else:
        now = "Right now it's between research runs. It checks in about every %d minutes." % max(1, COPILOT_REVIEW_MINUTES)
        quiet = _quiet_minutes(d.get("last_review_at"))
        if quiet:
            # A stalled worker would leave "checks in every 10 minutes" on screen for hours; say how long it's been.
            # Same steps as the "Last reviewed" figure beside it (sinceMin), so the two never disagree.
            now = "Right now it's between research runs. Its last check-in was %s ago, longer than usual." % _span(quiet)
    return now


def _scan_tally(cur, deps: List[Dict]) -> Dict[int, Dict[str, int]]:
    try:
        return repo.scan_tally(cur, [d["id"] for d in deps])
    except Exception:  # noqa: BLE001 - a readout; the table may not exist before the first schema run
        return {}


def _early_exits(cur, uid: int) -> Dict[str, Dict]:
    try:
        return repo.early_exit_scorecard(cur, uid, since=repo.now_utc() - timedelta(days=7))
    except Exception:  # noqa: BLE001 - a readout; the columns may not exist before the first schema run
        return {}


def _short_title(title: str) -> str:
    return (title or "").split(" — ")[0].strip() or "A strategy"


def _paper_waiting(paper_run: List[Dict], tally: Optional[Dict[int, Dict[str, int]]] = None) -> List[Dict]:
    """What each running paper strategy that bought nothing last decision is waiting for, from the
    engine's entry scan (spec.entry_scan): the first entry check no open contract cleared, plus
    today's tally of its decisions (repo.scan_tally) so 'waiting' and 'never fires' look different."""
    out = []
    for d in paper_run:
        sc = d.get("scan") or {}
        if sc.get("why") and not sc.get("entered") and not sc.get("qualifying"):
            t = (tally or {}).get(d["id"]) or {}
            out.append({"deployment_id": d["id"], "title": _short_title(d.get("title")), "why": sc["why"],
                        "blocked_at": sc.get("blocked_at"), "at": d.get("last_scan_at"),
                        "checks_today": sum(t.values()), "qualified_today": t.get("qualified", 0)})
    return out[:5]


def _waiting_lines(waiting: List[Dict]) -> List[str]:
    """One line per distinct reason, naming every strategy stuck on it (two strategies on the same
    market usually wait on the same thing, and a phone shouldn't read it twice)."""
    groups: Dict[str, List[Dict]] = {}
    for w in waiting:
        groups.setdefault(w["why"], []).append(w)
    out = []
    for why, ws in list(groups.items())[:3]:
        names = [w["title"] for w in ws]
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        line = "%s %s waiting: %s." % (who, "is" if len(names) == 1 else "are", why[0].upper() + why[1:])
        checks = sum(int(w.get("checks_today") or 0) for w in ws)
        if checks:
            found = sum(int(w.get("qualified_today") or 0) for w in ws)
            # scan_tally counts the UTC day, so the sentence names it (a US evening is already "tomorrow").
            line += " Since 00:00 UTC, %s of %d checks found a contract worth buying." % (found or "none", checks)
        out.append(line)
    return out


def _money(x: float) -> str:
    return ("up $%.2f" % x) if x >= 0 else ("down $%.2f" % -x)


def _plain_pause_reason(why: str) -> str:
    """The engine's pause reason in plain words, for the phone panel."""
    why = (why or "").strip()
    m = re.search(r"position down ([\d.]+)% >= stop ([\d.]+)%", why)
    if m:
        return "its safety stop sold a position that had lost %.0f%% of its cost" % float(m.group(1))
    m = re.search(r"drawdown ([\d.]+)% >= limit ([\d.]+)%", why)
    if m:
        return "it lost %.0f%% of its money, past its %.0f%% limit" % (float(m.group(1)), float(m.group(2)))
    if why.lower().startswith("lost $"):
        return "it hit its loss guard"
    return (customer_text.clean(why, "") or "").rstrip(".")[:120] or "it was paused"


def _tournament_summary(cur, uid: int, deps: List[Dict]) -> Optional[Dict]:
    from app.research import tournament
    try:
        return tournament.panel_summary(cur, uid, {int(d["strategy_id"]): _short_title(d.get("title")) for d in deps})
    except Exception:  # noqa: BLE001 - a readout; the table may not exist before the first schema run
        return None


def _tournament_line(t: Optional[Dict]) -> str:
    """One line for the whole paper tournament, instead of a line per entrant."""
    if not t:
        return ""
    lead, book = t["leader"], "${:,.0f}".format(t["capital"])
    if t["cash_weight"] >= lead["weight"]:
        where = "it keeps %d%% of its %s practice book in cash until an entrant proves it beats zero" % (
            round(100 * t["cash_weight"]), book)
    else:
        where = "it has %d%% of its %s practice book on %s" % (
            round(100 * lead["weight"]), book, lead["title"] or "its leader")
    return ("The paper tournament runs %s at once, with %d of the %d independent bets the research gate needs so far; %s." % (
        _plural(t["entrants"], "strategy", "strategies"), t["trips"], t["target"], where))


def _paused_recent(deps: List[Dict], hours: int = 24, cur=None) -> List[Dict]:
    """Paper deployments paused in the last `hours`: they leave the 'running' count, so without
    this a stopped-out strategy simply vanishes from the panel. Deployments listed without their
    position totals (list_deployments_brief) get them from one read of just these, through `cur`."""
    since = repo.now_utc() - timedelta(hours=hours)
    picked = [d for d in deps if d["mode"] == "paper" and d["status"] == "paused"
              and d.get("updated_at") is not None and d["updated_at"] >= since][:3]
    totals = {}
    if cur is not None and any("closed_trades" not in d for d in picked):
        totals = repo.deployment_closed_totals(cur, [d["id"] for d in picked])
    out = []
    for d in picked:
        trades, pnl = ((d.get("closed_trades"), d.get("realized_pnl")) if "closed_trades" in d
                       else totals.get(int(d["id"]), (0, 0)))
        out.append({"deployment_id": d["id"], "title": _short_title(d.get("title")),
                    "trades": int(trades or 0), "pnl": round(float(pnl or 0), 2),
                    "why": _plain_pause_reason(d.get("status_reason"))})
    return out


def _paused_lines(paused: List[Dict]) -> List[str]:
    return ["%s was paused after %s (%s): %s." % (p["title"], _plural(p["trades"], "paper trade"), _money(p["pnl"]), p["why"])
            for p in paused]


def _stop_line(exits: Dict[str, Dict]) -> str:
    """This week's safety-stop exits against holding to settlement, once their contracts settled."""
    rows = [exits[r] for r in repo.STOP_EXIT_REASONS if r in exits]
    n, scored = sum(r["exits"] for r in rows), sum(r["scored"] for r in rows)
    if not scored:
        return ""
    hold, saved = sum(r["hold_pnl"] for r in rows), sum(r["saved"] for r in rows)
    held = ("lost $%.2f" % -hold) if hold < 0 else ("made $%.2f" % hold)
    verdict = ("so the stop saved $%.2f" % saved) if saved >= 0 else ("so the stop cost $%.2f" % -saved)
    return "This week the safety stop sold %s on paper. Holding %s to the end would have %s, %s." % (
        _plural(n, "position"), ("it" if n == 1 else "them") if scored == n else
        "the %d that %s settled" % (scored, "has" if scored == 1 else "have"),
        held, verdict)


COPILOT_REVIEW_MINUTES = int(os.getenv("APP_COPILOT_REVIEW_SECONDS", "600")) // 60
# The worker spaces idle reviews up to APP_IDLE_REVIEW_SECONDS apart, so only a gap well past that is late.
QUIET_AFTER_MINUTES = max(COPILOT_REVIEW_MINUTES, int(os.getenv("APP_IDLE_REVIEW_SECONDS", "1800")) // 60) * 3 // 2


# A queued or silent run reads as overdue once it passes the reaper's limit (worker.ABANDONED_AFTER,
# TAU_RUN_ABANDONED_SECONDS): a running run that hasn't beaten for that long is one the reaper stops,
# and a queued run is never reaped, so without this a backed-up or dead worker showed a spinner forever.
RUN_OVERDUE_SECONDS = int(worker.ABANDONED_AFTER.total_seconds())


def _silent_before() -> datetime:
    """A running run whose last beat is older than this has gone quiet past the reaper's limit."""
    return repo.now_utc() - timedelta(seconds=RUN_OVERDUE_SECONDS)


def _run_wait(run: Optional[Dict]) -> Optional[Dict]:
    """How long a run has been waiting for a worker, or silent while running: {"state": "queued" |
    "silent", "seconds": n, "overdue": bool}. A queued run always reports its wait, measured from its
    last re-queue (heartbeat_at) or its creation; a running one only once its heartbeat is overdue.
    None for anything else."""
    if not run:
        return None
    if run.get("status") == "queued":
        since, state = run.get("heartbeat_at") or run.get("created_at"), "queued"
    elif run.get("status") == "running":
        since, state = run.get("heartbeat_at") or run.get("started_at"), "silent"
    else:
        return None
    if not isinstance(since, datetime):
        return None
    secs = max(0, int((repo.now_utc() - since).total_seconds()))
    overdue = secs > RUN_OVERDUE_SECONDS
    if state == "silent" and not overdue:
        return None
    return {"state": state, "seconds": secs, "overdue": overdue}


def _span(mins: int) -> str:
    """Minutes as the panel says them: "6 minutes", "2 hours", "3 days"."""
    return (_plural(mins, "minute") if mins < 90 else _plural(int(mins / 60 + .5), "hour") if mins < 2880
            else _plural(int(mins / 1440 + .5), "day"))


def _quiet_minutes(last_review_at) -> int:
    """Minutes since the last autopilot review when that's later than the worker's cadence, else 0."""
    if not isinstance(last_review_at, datetime):
        return 0
    mins = int((repo.now_utc() - last_review_at).total_seconds() // 60)
    return mins if mins > QUIET_AFTER_MINUTES else 0


# The deployment engine beats every TICK_SECONDS (15s); a beat older than this means paper strategies
# aren't being decided at all, whatever their own last scan said.
ENGINE_STALE_SECONDS = int(os.getenv("TAU_ENGINE_STALE_SECONDS", "300"))
_UNKNOWN = object()


def _engine_age(cur):
    """Seconds since the engine's last tick (None = it has never ticked), or _UNKNOWN when it can't be read."""
    try:
        return repo.engine_last_tick_age_seconds(cur)
    except Exception:  # noqa: BLE001 - a readout; never fail the panel over it
        return _UNKNOWN


def _passed_undeployed(cur, uid: int, focus: List[str]) -> List[Dict]:
    """The user's passed strategies that never ran on paper (the example left out), each with whether
    it is inside the focus and, for the first few inside it, whether the gatekeeper made it a
    deployment candidate: the same tests agent.auto_paper_candidates applies before it deploys one."""
    try:
        rows = repo.list_strategies(cur, uid, status="passed", limit=100)
        tried = {d["strategy_id"] for d in repo.list_deployments(cur, uid, include_stopped=True)}
    except Exception:  # noqa: BLE001 - a readout
        return []
    out = [{"id": r["id"], "market": r.get("market"), "title": _short_title(r.get("title")),
            "in_focus": agent.in_focus(r.get("market"), focus), "candidate": False, "retired": r["id"] in tried}
           for r in rows if r.get("direction") != repo.DEMO_DIRECTION]
    for x in [x for x in out if x["in_focus"] and not x["retired"]][:5]:
        try:
            x["candidate"] = agent._is_deployment_candidate(cur, x["id"])
        except Exception:  # noqa: BLE001 - a readout
            pass
    return out


def _pause_clause(raw: Optional[str]) -> str:
    """Why a deployment is paused, as the end of a sentence."""
    raw = (raw or "").strip()
    return {"By you": "you paused it", "Approved agent proposal": "you approved the agent's proposal to pause it",
            "Kill switch": "you pressed Kill"}.get(raw) or _plain_pause_reason(raw)


def _idle(code: str, line: str, action: Optional[Dict] = None) -> Dict:
    return {"code": code, "line": line, "action": action}


def _idle_reason(d: Dict, paper_run: List[Dict], paused: List[Dict], engine_age, passed: List[Dict]) -> Optional[Dict]:
    """Why the autopilot places no paper trades right now, as one plain line plus the action to take
    (if there is one): {"code", "line", "action": {"label", "href"} or {"label", "do"} or None}. None
    when it's off or something is trading (an open position, or a contract that cleared every entry
    check). Built from the status payload `d` and the reads passed in, so it can't disagree with them.
    `paused` is every paused paper deployment, newest first; `passed` the passed strategies with no
    deployment; `engine_age` the engine's last beat (None = never, _UNKNOWN = couldn't read)."""
    if not d.get("autopilot"):
        return None
    running = sum(int(d.get(k) or 0) for k in ("paper_running", "demo_running", "live_running"))
    if running and engine_age is not _UNKNOWN and (engine_age is None or engine_age > ENGINE_STALE_SECONDS):
        when = ("isn't running" if engine_age is None
                else "last checked the markets %s ago" % _span(max(1, int(engine_age) // 60)))
        return _idle("engine", "Nothing is trading right now: Tau's trading engine %s, so %s. There's nothing for "
                               "you to do; %s when it's back." % (
                                   when, "your strategy can't buy or sell" if running == 1
                                   else "your %d strategies can't buy or sell" % running,
                                   "it carries on" if running == 1 else "they carry on"))
    if running:
        if not paper_run or int(d.get("paper_open") or 0):
            return None
        scans = [dep.get("scan") or {} for dep in paper_run]
        if any(sc.get("entered") or sc.get("qualifying") for sc in scans):
            return None
        n = len(paper_run)
        if not any(sc.get("why") for sc in scans):
            # No scan record says nothing about the trades: a strategy that has already closed paper
            # trades read "No trades yet ... hasn't had its first look" when its scan row was missing.
            # paper_progress is the running strategy with the most closed paper trades.
            prog = d.get("paper_progress") or {}
            done = int(prog.get("trades") or 0)
            if done:
                who = _short_title(prog.get("title") or paper_run[0].get("title"))
                line = ("Nothing open right now: %s has closed %s on paper and holds no position. It checks "
                        "again at its market's next decision time." % (who, _plural(done, "trade"))) if n == 1 else \
                       ("Nothing open right now: none of your %d paper strategies holds a position (the furthest "
                        "along, %s, has closed %s). Each checks again at its market's next decision time."
                        % (n, who, _plural(done, "trade")))
                return _idle("flat", line)
            line = ("No trades yet: %s went on paper and hasn't had its first look at the market. It checks at its "
                    "market's next decision time." % _short_title(paper_run[0].get("title"))) if n == 1 else \
                   ("No trades yet: your %d paper strategies haven't had their first look at the market. Each checks "
                    "at its market's next decision time." % n)
            return _idle("starting", line)
        waiting = d.get("paper_waiting") or []
        closed = [w for w in waiting if w["why"].startswith("no open contracts")]
        if waiting and len(closed) == len(waiting):
            who = "the market for %s has" % waiting[0]["title"] if n == 1 else "the markets for your %d paper strategies have" % n
            return _idle("market_closed", "Nothing is trading right now: %s no open contracts (closed, or between "
                                          "events). Trading picks up when new contracts list." % who)
        if waiting:
            w = next(w for w in waiting if w not in closed)
            lead = ("%s is waiting for a contract that fits its entry rules" % w["title"]) if n == 1 else \
                   ("none of your %d paper strategies has found a contract that fits its entry rules" % n)
            return _idle("waiting", "No trades right now: %s. %s: %s." % (
                lead, "Its last check" if n == 1 else "Last check for %s" % w["title"], w["why"]))
        return None
    card = d.get("billing_reason") == "card"
    if d.get("billing_blocked"):
        return _idle("billing", "Nothing is on paper, and it can't research new strategies until you %s." % (
            "add a payment method" if card else "add credits"),
            {"label": "Add a payment method" if card else "Add credits", "href": "/billing"})
    now = _autopilot_now(d).split(". ")[0].rstrip(".") + "."  # its first sentence
    doing = (now[len("Right now "):] if now.startswith("Right now ") else now)
    doing = doing[0].upper() + doing[1:]
    if paused:
        p = paused[0]
        lead = ("%s is paused" % _short_title(p.get("title")) if len(paused) == 1
                else "your %d paper strategies are paused (the latest, %s" % (len(paused), _short_title(p.get("title"))))
        why = _pause_clause(p.get("status_reason"))
        line = ("Nothing is trading: %s: %s." % (lead, why)) if len(paused) == 1 else \
               ("Nothing is trading: %s: %s)." % (lead, why))
        return _idle("stopped", line + " Resume one, or let the autopilot find new ones.",
                     {"label": "Open Deploy", "href": "/deploy"})
    focus = d.get("focus") or []
    retired = [x for x in passed if x["retired"]]
    passed = [x for x in passed if not x["retired"]]
    inside = [x for x in passed if x["in_focus"]]
    if focus and passed and not inside:
        k = len(passed)
        return _idle("focus", "Nothing is on paper: your focus is %s, and %s outside it, so it won't deploy %s. "
                              "It researches inside the focus to find new ones." % (
                                  ", ".join(focus), ("your passed strategy, %s, is" % passed[0]["title"]) if k == 1
                                  else "both your passed strategies are" if k == 2 else "all %d of your passed strategies are" % k, "it" if k == 1 else "them"),
                     {"label": "Change focus", "do": "focus"})
    ready = [x for x in inside if x["candidate"]]
    if ready:
        return _idle("to_deploy", "Nothing is on paper yet: %s cleared every check, and the next review puts %s on "
                                  "paper. %s" % (ready[0]["title"] if len(ready) == 1 else "%d strategies" % len(ready),
                                                 "it" if len(ready) == 1 else "them", doing))
    if inside:
        return _idle("no_candidate", "Nothing is on paper yet: %s passed the research tests, but %s cleared the last "
                                     "check before paper (the holdout test). %s" % (
                                         inside[0]["title"] if len(inside) == 1 else "%d strategies" % len(inside),
                                         "it hasn't" if len(inside) == 1 else "none has", doing))
    code = ("researching" if (d.get("research") or {}).get("active") else "reviewing" if d.get("reviewing")
            else "review_wait" if d.get("review_wait") else "no_strategies")
    if retired:
        return _idle(code, "Nothing is on paper: %s that passed %s stopped on paper, and no new one has passed since. %s" % (
            "the strategy" if len(retired) == 1 else "the %d strategies" % len(retired),
            "was" if len(retired) == 1 else "were", doing))
    return _idle(code, "Nothing is on paper yet: no strategy has passed its research tests. %s" % doing)


def autopilot_status(ctx: Ctx):
    """Lightweight status for the floating autopilot window."""
    cur, u = ctx.cur, ctx.user
    # Without the per-deployment position totals: this polls, and only _paused_recent needs them.
    deps = repo.list_deployments_brief(cur, ctx.uid)
    live_run = [d for d in deps if d["mode"] == "live" and d["status"] == "running"]
    paper_run = [d for d in deps if d["mode"] == "paper" and d["status"] == "running"]
    demo_run = [d for d in deps if d["mode"] == "demo" and d["status"] == "running"]
    kalshi_connected = repo.get_kalshi_key(cur, ctx.uid) is not None  # read once: the live gate and the badge
    gates_ok = bool(engine.LIVE_TRADING_ENABLED and kalshi_connected)
    live_on = bool(u.get("autopilot_live")) and gates_ok and bool(u.get("autopilot"))
    mode = "live" if (live_on and live_run) else ("live-armed" if live_on else ("paper" if u.get("autopilot") else "off"))
    today_live = round(repo.realized_pnl(cur, ctx.uid, "live", _start_of_day_utc()), 2)
    limit = float(u.get("autopilot_daily_loss_limit") or 50)
    # When autopilot is ON but can't spend (no card, or balance below the per-run floor), the worker
    # silently skips the user via billing.is_ready — the SAME gate, read here only to surface WHY the
    # panel is quiet so it doesn't look broken. Never changes the gate; purely a status readout.
    reads = billing.Reads(cur, ctx.uid)  # the readout below reuses the gate's card and balance reads
    billing_blocked = bool(u.get("autopilot")) and billing.configured() and not billing.is_ready(cur, ctx.uid, reads)
    review = repo.active_agent_run(cur, ctx.uid, "review") if u.get("autopilot") else None
    review_wait = _run_wait(review) or {"overdue": False}
    # Paper -> live progress: the running paper strategy closest to the realistic-trade gate, so a
    # user on autopilot can see the funnel moving. Counts only (no bootstrap): this endpoint polls.
    paper_progress = None
    if paper_run:
        sids = sorted({int(d["strategy_id"]) for d in paper_run})
        # Both readouts are kept until the positions (or which deployments count toward them) change.
        prog, events = book_memo.paper_readouts(book_memo.BookMemo(cur, ctx.uid), sids)
        titles = {int(d["strategy_id"]): d.get("title") or "" for d in paper_run}
        best = max(sids, key=lambda s: (prog.get(s, (0, 0.0))[0], prog.get(s, (0, 0.0))[1]))
        trades, net = prog.get(best, (0, 0.0))
        paper_progress = {"strategy_id": best, "title": titles[best], "trades": trades,
                          "trades_needed": agent.MIN_REALISTIC_PAPER_TRADES, "net_pnl": round(net, 2),
                          "strategies": len(sids)}
        # When the soonest one could have a full record for the live check, at the pace each trades.
        from app.research import rsi
        dep_of = {int(d["strategy_id"]): d for d in reversed(paper_run)}  # oldest deployment per strategy
        etas = {s: rsi.paper_eta_days(dep_of[s], prog.get(s, (0, 0.0))[0], events=events.get(s)) for s in sids}
        etas = {s: v for s, v in etas.items() if v is not None}
        if etas:
            soon = min(etas, key=etas.get)
            paper_progress.update(soonest_days=etas[soon], soonest_title=titles[soon])
    out = {
        "research": _research_activity(cur, ctx.uid),
        "autopilot": bool(u.get("autopilot")),
        "autopilot_live": bool(u.get("autopilot_live")),
        "live_enabled": bool(engine.LIVE_TRADING_ENABLED),
        "kalshi_connected": kalshi_connected,
        "mode": mode,
        "live_running": len(live_run), "paper_running": len(paper_run), "demo_running": len(demo_run),
        "today_live_pnl": today_live,
        # The paper book's day, so a paper-only panel shows its own money instead of a live $0.00.
        "today_paper_pnl": round(repo.realized_pnl(cur, ctx.uid, "paper", _start_of_day_utc()), 2),
        "daily_loss_limit": limit,
        "loss_headroom": round(max(0.0, limit + min(0.0, today_live)), 2),  # how much loss budget is left today
        "last_action": repo.last_autopilot_action(cur, ctx.uid),
        "last_review_at": repo.last_review_at(cur, ctx.uid),  # liveness: a quiet review posts nothing, this still shows it ran
        # A review queued or running now. Switching on queues the first one at once, and the panel said
        # "between research runs, checks in every 10 minutes" over a "Working" pulse while it waited.
        "reviewing": bool(review) and not review_wait["overdue"],
        # Set once that review has waited or gone quiet past the reaper's limit, so the panel says so
        # instead of "reviewing" forever.
        "review_wait": review_wait if review_wait["overdue"] else None,
        "model": u.get("autopilot_model") or catalog.DEFAULT_KEY,  # the model the autopilot's own runs use
        "focus": agent.focus_tokens(u),  # the user's binding market focus ([] = any market)
        "billing_blocked": billing_blocked,
        "billing_reason": (("card" if _needs_card(ctx, reads) else "credits") if billing_blocked else None),
        # Warn before the pause, not after: days of credit left when that's under three.
        "credits_low_days": (_credits_running_low(cur, ctx.uid, reads)
                             if u.get("autopilot") and billing.configured() and not billing_blocked else None),
        "paper_progress": paper_progress,
        "paper_open": int(repo.user_open_exposure(cur, ctx.uid, "paper")["n"]) if paper_run else 0,
        "paper_waiting": _paper_waiting(paper_run, _scan_tally(cur, paper_run)),
        "paused_recent": _paused_recent(deps, cur=cur),
        "early_exits_7d": _early_exits(cur, ctx.uid),
        "tournament": _tournament_summary(cur, ctx.uid, deps),
    }
    if u.get("autopilot"):
        out["week"] = _autopilot_week(cur, ctx.uid, out["research"], reads)
        # Why nothing is trading right now (None while something is). Each read is skipped unless
        # its state can be the answer, since this endpoint polls.
        running = len(paper_run) + len(demo_run) + len(live_run)
        paused = sorted((d for d in deps if d["mode"] == "paper" and d["status"] == "paused"),
                        key=lambda d: d.get("updated_at") or datetime.min, reverse=True)
        out["idle"] = _idle_reason(out, paper_run, paused, _engine_age(cur) if running else _UNKNOWN,
                                   _passed_undeployed(cur, ctx.uid, out["focus"]) if not running and not paused
                                   and not billing_blocked else [])
        # A demo copy whose every order Kalshi refuses is what isn't trading when paper is fine, and
        # the truer line when nothing is on paper (only the engine or billing outrank it there).
        idle = out["idle"]
        if idle is None or (not paper_run and idle["code"] not in ("engine", "billing")):
            out["idle"] = _demo_health(cur, ctx.uid, deps) or idle
    else:
        out["idle"] = None
    out["story"] = _autopilot_story(out)
    return out


def _autopilot_week(cur, uid: int, research: Dict, reads: Optional[billing.Reads] = None) -> Dict:
    """The autopilot's last 7 days, for its scorecard. Research reuses the panel's week (every
    research session, the user's and the autopilot's; credits are what the ledger debited). Paper
    covers only the strategies the autopilot put on paper itself. Credits are real money and paper
    P&L is not, so they are separate fields the page shows apart and never adds up."""
    since = repo.now_utc() - timedelta(days=7)
    paper = repo.autopilot_paper_week(cur, uid, since)
    out = {"research_credits": research.get("cost_7d", 0.0), "tested": research.get("tested_7d", 0),
           "passed": research.get("passed_7d", 0), "paper_started": paper["started"],
           "paper_pnl": round(paper["pnl"], 2), "paper_trades": paper["trades"],
           "checkin_credits": None, "credits_left": None, "runway_days": None}
    if billing.configured():
        # What else the week cost and how long the balance lasts at that pace, read-only: the
        # autopilot's check-ins bill too, and the runway is the Billing page's (every usage debit of
        # the week). With payments off nothing pauses it, so there is no limit to show.
        used = repo.usage_by_source(cur, uid, since)
        spent_7d = sum(used.values())
        balance = (reads or billing.Reads(cur, uid)).balance()
        out.update(checkin_credits=round(used["autopilot_review"], 2), credits_left=round(balance, 2),
                   runway_days=round(balance / (spent_7d / 7), 1) if spent_7d > 0 and balance > 0 else None)
    return out


def autopilot_focus(ctx: Ctx):
    """Set or clear the autopilot's market focus (family names, coins or market keys)."""
    try:
        tokens = agent.normalize_focus(ctx.body.get("focus") or [])
    except ValueError as e:
        raise ApiError(400, str(e))
    repo.set_autopilot_focus(ctx.cur, ctx.uid, tokens)
    repo.add_chat(ctx.cur, ctx.uid, "system", ("Market focus set to %s." % ", ".join(tokens)) if tokens
                  else "Market focus cleared.")
    return {"ok": True, "focus": tokens}


def autopilot_model(ctx: Ctx):
    """Pick the model the autopilot's own research/review/chat runs use (manual runs still choose
    per-run). Validated against the catalog; empty/unknown clears back to the catalog default."""
    key = (ctx.body.get("model") or "").strip() or None
    if key is not None and catalog.get(key) is None:
        raise ApiError(400, "Unknown model.")
    repo.set_autopilot_model(ctx.cur, ctx.uid, key)
    return {"ok": True, "model": key or catalog.DEFAULT_KEY}


# -- routing -----------------------------------------------------------------------

Route = Tuple[str, "re.Pattern[str]", Callable[[Ctx], Any], bool]
# -- explore (market browser + hot-markets sidebar) ------------------------------
# The collector writes a small gzipped feed of the hottest collected markets to S3; the
# web app reads + caches it, so browsing ~41k markets never touches the data lake per request.
_EXPLORE_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_EXPLORE_BUCKET = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-568386354218-us-east-1")
_EXPLORE_KEY = os.getenv("DATALAKE_EXPLORE_KEY", "explore/latest.json.gz")
_EXPLORE_SORTS = ("v24", "oi", "last")


_EXPLORE_LOCK = threading.Lock()
_S3: Dict[str, Any] = {}


def _fetch_explore_feed() -> Dict:
    try:
        import gzip as _gzip
        if "c" not in _S3:
            import boto3
            _S3["c"] = boto3.client("s3")
        raw = _S3["c"].get_object(Bucket=_EXPLORE_BUCKET, Key=_EXPLORE_KEY)["Body"].read()
        return json.loads(_gzip.decompress(raw))
    except Exception:  # feed not written yet, or S3 unreachable -> empty, not an error
        return None


def _refresh_explore_feed() -> None:
    try:
        data = _fetch_explore_feed()
        if data is not None or _EXPLORE_CACHE["data"] is None:
            _EXPLORE_CACHE.update(data=data or {"at": None, "total": 0, "shown": 0, "markets": []})
        _EXPLORE_CACHE["at"] = time.time()
    finally:
        _EXPLORE_CACHE["refreshing"] = False


def _explore_feed() -> Dict:
    """The Explore feed from S3, cached 45s. Once warm, a stale copy is served while ONE background
    thread refetches, so no request waits on S3 and concurrent misses don't each download the feed.
    A failed fetch keeps the last good copy rather than blanking the page."""
    now = time.time()
    if _EXPLORE_CACHE["data"] is None:
        with _EXPLORE_LOCK:
            if _EXPLORE_CACHE["data"] is None:
                _EXPLORE_CACHE["refreshing"] = True
                _refresh_explore_feed()
        return _EXPLORE_CACHE["data"]
    if now - _EXPLORE_CACHE["at"] >= 45 and not _EXPLORE_CACHE.get("refreshing"):
        with _EXPLORE_LOCK:
            if not _EXPLORE_CACHE.get("refreshing"):
                _EXPLORE_CACHE["refreshing"] = True
                threading.Thread(target=_refresh_explore_feed, daemon=True).start()
    return _EXPLORE_CACHE["data"]


def _efloat(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def explore_list(ctx: Ctx):
    data = _explore_feed()
    q = (ctx.query.get("q") or "").strip().lower()
    sort = ctx.query.get("sort") if ctx.query.get("sort") in _EXPLORE_SORTS else "v24"
    try:
        page = max(0, int(ctx.query.get("page") or 0))
    except ValueError:
        page = 0
    per = 40
    markets = data.get("markets") or []
    if q:
        markets = [m for m in markets
                   if q in ((m.get("ti") or "") + " " + (m.get("t") or "") + " " + (m.get("s") or "")).lower()]
    markets = sorted(markets, key=lambda m: _efloat(m.get(sort)), reverse=True)
    matched = len(markets)
    return {"at": data.get("at"), "total": data.get("total"), "shown": data.get("shown"),
            "matched": matched, "page": page, "per": per, "sort": sort,
            "markets": [{k: v for k, v in m.items() if k != "h"} for m in markets[page * per:(page + 1) * per]]}


def explore_hot(ctx: Ctx):
    """Top markets that carry a price trace, for the Hot Markets sidebar."""
    data = _explore_feed()
    hot = [m for m in (data.get("markets") or []) if m.get("h")][:16]
    return {"at": data.get("at"), "markets": hot}


def _feed_mid(m: Dict) -> Optional[float]:
    """Mid (0..1 probability) for one explore-feed contract: the bid/ask midpoint, else last."""
    b, a = _efloat(m.get("bid")), _efloat(m.get("ask"))
    if b > 0 and a > 0:
        return round((b + a) / 2, 4)
    last = _efloat(m.get("last"))
    return round(last, 4) if last > 0 else None


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
    val = {k: round(_median(v), 2) for k, v in by_model.items() if len(v) >= SESSION_COST_MIN_TYPICAL}
    _TYPICAL_SESSION_COST[:] = [time.time(), val]
    return val


def research_estimate(ctx: Ctx):
    """What a research session usually costs, for the hint beside Start session: the median credits
    of the user's own last 10 finished sessions, or (with fewer than 3) the server-wide median for
    each model. Read-only; what a run is charged does not change."""
    own = repo.finished_session_costs(ctx.cur, ctx.uid, 10)
    return {"yours": round(_median(own), 2) if len(own) >= SESSION_COST_MIN_OWN else None,
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


def _cnum(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


_MINE_FIELDS = ("id", "mode", "side", "qty", "entry_price", "status", "title", "strategy_id", "market_close_time",
                "opened_at", "closed_at", "exit_price", "pnl", "close_reason")


def _market_mine(ctx: Ctx, ticker: str, open_ts: Optional[int]) -> Optional[Dict]:
    """The reader's own positions in one contract, for its market page: open ones marked to market,
    and those settled since the contract opened (30 days back when its open time is unknown). Each
    row keeps its mode; the page totals each money book apart. None when the read failed, so the
    page says so instead of showing an empty book."""
    since = datetime.fromtimestamp(open_ts, timezone.utc) if open_ts else datetime.now(timezone.utc) - timedelta(days=30)
    try:
        rows = repo.user_positions_in_ticker(ctx.cur, ctx.uid, ticker, since.replace(tzinfo=None))
    except Exception as e:
        print("[explore] market %s positions failed: %r" % (ticker, e), flush=True)
        return None
    pick = lambda p: {**{k: p.get(k) for k in _MINE_FIELDS},
                      "cost": round(int(p["qty"]) * float(p["entry_price"]) + float(p.get("entry_fee") or 0), 2)}
    return {"open": [{**pick(p), **_mark_fields(p)} for p in rows["open"]], "closed": [pick(p) for p in rows["closed"]]}


def _market_terms(m: Dict) -> Dict:
    """How a contract settles, from Kalshi's market record: its rules, when the result is expected,
    and the result once it has one."""
    return {"rules": m.get("rules_primary") or "", "rules_more": m.get("rules_secondary") or "",
            "settles_at": m.get("expected_expiration_time") or m.get("expiration_time"), "result": m.get("result") or ""}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def explore_market(ctx: Ctx):
    """One market's dataset for the Explore detail view: its metadata, how it settles, the price
    history Kalshi has for it (the same candlesticks the backtester trains on), and the reader's
    own positions in it. Fetched on demand from Kalshi's public API — no lake query, no new storage.
    `as_of` is when the figures were read: now for Kalshi's record, the feed's time for its snapshot."""
    from data_pipeline.common import api_get, parse_iso_to_dt
    import time as _time
    ticker = (ctx.query.get("ticker") or "").strip()
    if not ticker:
        raise ApiError(400, "No market given.")
    series = ticker.split("-", 1)[0]
    m: Dict = {}
    open_ts = None
    try:
        m = (api_get("/markets/%s" % ticker) or {}).get("market") or {}
        open_ts = int(parse_iso_to_dt(m.get("open_time")).timestamp()) if m.get("open_time") else None
        close_ts = int(parse_iso_to_dt(m.get("close_time")).timestamp()) if m.get("close_time") else None
        now = int(_time.time())
        start = open_ts or (now - 30 * 86400)
        end = min(close_ts or now, now)
        span = max(1, end - start)
        # Prefer minute resolution; fall back to coarser only when the span would blow past
        # Kalshi's per-request candle cap (minute for <=2 days, hourly to ~2 months, else daily).
        period = 1 if span <= 2 * 86400 else (60 if span <= 60 * 86400 else 1440)  # minutes
        cs = api_get("/series/%s/markets/%s/candlesticks" % (series, ticker),
                     {"start_ts": start, "end_ts": end, "period_interval": period}).get("candlesticks") or []
    except Exception as e:
        # The raw error named the proxy and Kalshi's host to the user; keep that in the log.
        if " failed 404:" in str(e):  # api_get's RuntimeError carries the status in its text
            raise ApiError(404, "Kalshi has no market %s." % ticker)
        print("[explore] market %s history failed: %r" % (ticker, e), flush=True)
        # Still show the market: Kalshi's own record if that call got through, else the Explore
        # feed's snapshot of it. Only the chart waits for Kalshi (history_unavailable).
        snap = m and {"title": m.get("title"), "sub": m.get("yes_sub_title") or m.get("subtitle"), "yes_bid": m.get("yes_bid_dollars"),
                      "yes_ask": m.get("yes_ask_dollars"), "last": m.get("last_price_dollars"), "volume_24h": m.get("volume_24h_fp"),
                      "open_interest": m.get("open_interest_fp"), "status": m.get("status"), "close_time": m.get("close_time"),
                      **_market_terms(m), "as_of": _iso_now()}
        if not snap:
            feed = _explore_feed()
            f = next((x for x in (feed.get("markets") or []) if x.get("t") == ticker), None)
            snap = f and {"title": f.get("ti"), "sub": f.get("su"), "yes_bid": f.get("bid"), "yes_ask": f.get("ask"),
                          "last": f.get("last"), "volume_24h": f.get("v24"), "open_interest": f.get("oi"),
                          "status": f.get("st"), "close_time": None, "as_of": feed.get("at"), "snapshot": True}
        if not snap:
            raise ApiError(502, "Kalshi didn't send this market's history just now. Try again in a minute.")
        return {**snap, "ticker": ticker, "series": series, "title": snap["title"] or ticker, "sub": snap["sub"] or "",
                "period_min": None, "points": [], "history_unavailable": True, "mine": _market_mine(ctx, ticker, open_ts)}
    points = []
    for c in cs:
        price = (c.get("price") or {})
        yb, ya = (c.get("yes_bid") or {}), (c.get("yes_ask") or {})
        yes = _cnum(price.get("close_dollars"))
        if yes is None:
            b, a = _cnum(yb.get("close_dollars")), _cnum(ya.get("close_dollars"))
            yes = (b + a) / 2 if b is not None and a is not None else None
        if yes is not None:
            points.append({"t": int(c["end_period_ts"]), "yes": round(yes, 4), "vol": _cnum(c.get("volume_fp")) or 0})
    return {
        "ticker": ticker, "series": series,
        "title": m.get("title") or ticker, "sub": m.get("yes_sub_title") or m.get("subtitle") or "",
        "yes_bid": m.get("yes_bid_dollars"), "yes_ask": m.get("yes_ask_dollars"), "last": m.get("last_price_dollars"),
        "volume_24h": m.get("volume_24h_fp"), "open_interest": m.get("open_interest_fp"),
        "status": m.get("status"), "close_time": m.get("close_time"), "period_min": period, "points": points,
        **_market_terms(m), "as_of": _iso_now(), "mine": _market_mine(ctx, ticker, open_ts),
    }


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
