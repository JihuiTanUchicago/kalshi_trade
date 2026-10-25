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
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from app import agent, auth, backtest, billing, devlog, dreaming, engine, kalshi_account, notify
from app import kalshi_dev
from app import kalshi_dev_exec
from app import broker_oauth, alpaca_paper, kalshi_perps_trading
from app import models_catalog as catalog
from app import repository as repo
from app import research_repository as research_repo
from app import spec as specmod
from app import track_record
from app import webperf
from app import worker
from app.markets import MARKETS
from app.services import markets as market_service
from data_pipeline.common import get_db_conn

PORT = int(os.getenv("APP_PORT", "8090"))
HOST = os.getenv("APP_HOST", "127.0.0.1")
DEV_LOGIN = os.getenv("APP_DEV_LOGIN") == "1"
# Canonical-host redirect: a top-level GET to any host in APP_REDIRECT_HOSTS (e.g. the old
# CloudFront URL, or www) is 301'd to APP_CANONICAL_HOST, so old links keep working after the
# custom-domain cutover. Empty APP_CANONICAL_HOST disables it entirely (the default), so this is
# inert until the new domain is actually live. /api and /auth are never redirected, so an in-flight
# request from an already-loaded old-host page still completes.
# Open signup: when APP_OPEN_SIGNUP=1, ANY Google account can create a Tau account (no waitlist
# approval). Default off = invite-only (operator + approved waitlist emails). Spend is still bounded
# downstream (billing-readiness gate, bounded free credits), and the live-trading gate is untouched.
OPEN_SIGNUP = os.getenv("APP_OPEN_SIGNUP") == "1"
CANONICAL_HOST = os.getenv("APP_CANONICAL_HOST", "").strip().lower()
REDIRECT_HOSTS = {h.strip().lower() for h in os.getenv("APP_REDIRECT_HOSTS", "").split(",") if h.strip()}
SECURE_COOKIES = os.getenv("APP_INSECURE_COOKIES") != "1"
STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY = 8 * 1024 * 1024  # allows a base64 image in a community post

MAX_ACTIVE_RESEARCH = 2
MAX_RESEARCH_PER_DAY = int(os.getenv("APP_MAX_RESEARCH_PER_DAY", "0"))  # 0 = unlimited (no daily cap)
MAX_CHAT_PER_HOUR = 40
MAX_ACTIVE_DEPLOYMENTS = 100
MAX_PAPER_BALANCE = 1_000_000.0
MAX_WAITLIST_PER_MINUTE = 10
ADMIN_EMAIL = os.getenv("TAU_ADMIN_EMAIL", "tjhprivate0416@gmail.com")
SPA_ROUTES = re.compile(r"^/(?:|dashboard|research(?:/\d+)?|strategies(?:/\d+)?|deploy|community|billing|admin|system|funds|explore|devlog|track-record|settings(?:/(?:account|billing|system|theme))?|signin|terms|privacy)$")

CSP = (
    "default-src 'self'; script-src 'self' https://js.stripe.com https://pay.google.com; style-src 'self' https://fonts.googleapis.com; style-src-attr 'unsafe-inline'; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://*.googleusercontent.com https://*.stripe.com; "
    "connect-src 'self' https://api.stripe.com https://*.stripe.com; frame-src https://js.stripe.com https://hooks.stripe.com https://*.stripe.com https://pay.google.com; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Ctx:
    conn: Any
    user: Optional[Dict]
    params: Tuple[str, ...]
    query: Dict[str, str]
    body: Dict[str, Any]
    handler: "Handler"
    set_cookies: List[str] = field(default_factory=list)

    @property
    def cur(self):
        return self.conn.cursor()

    @property
    def uid(self) -> int:
        return self.user["id"]


def _json_default(v):
    if isinstance(v, (datetime, date)):
        return (v.replace(tzinfo=timezone.utc) if isinstance(v, datetime) and v.tzinfo is None else v).isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return None
    raise TypeError(type(v))


def _num(body: Dict, key: str, lo: float, hi: float, default: Optional[float] = None) -> float:
    v = body.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(400, "%s must be a number" % key)
    if not lo <= v <= hi:
        raise ApiError(400, "%s must be between %g and %g" % (key, lo, hi))
    return float(v)


def _int_param(ctx: Ctx, i: int = 0) -> int:
    return int(ctx.params[i])


# -- auth routes ---------------------------------------------------------------


def _session_cookie(token: str, max_age: int) -> str:
    return "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (
        auth.SESSION_COOKIE, token, max_age, "; Secure" if SECURE_COOKIES else ""
    )


def _start_session(ctx: Ctx, user_id: int) -> None:
    token = auth.new_session_token()
    repo.create_session(ctx.cur, user_id, auth.hash_token(token), auth.SESSION_TTL)
    ctx.set_cookies.append(_session_cookie(token, int(auth.SESSION_TTL.total_seconds())))


def google_start(ctx: Ctx):
    if not auth.google_configured():
        raise ApiError(503, "Google sign-in is not configured on this server.")
    login = auth.new_login()
    repo.save_oauth_state(ctx.cur, login["state"], login["nonce"], login["verifier"])
    return ("redirect", auth.authorize_url(login))


def google_callback(ctx: Ctx):
    if ctx.query.get("error"):
        return ("redirect", "/signin?error=cancelled")
    state = repo.pop_oauth_state(ctx.cur, ctx.query.get("state", ""))
    if not state or not ctx.query.get("code"):
        return ("redirect", "/signin?error=expired")
    try:
        ident = auth.exchange_code(ctx.query["code"], state["code_verifier"], state["nonce"])
    except auth.AuthError:
        return ("redirect", "/signin?error=google")
    # Account creation gate: open to anyone when APP_OPEN_SIGNUP=1, else invite-only (operator or an
    # approved waitlist email). Existing users always sign in regardless (upsert finds them).
    email = ident["email"] or ""
    allow_new = OPEN_SIGNUP or email.lower() == ADMIN_EMAIL.lower() or repo.is_waitlist_approved(ctx.cur, email)
    user = repo.upsert_google_user(ctx.cur, ident["sub"], email, ident["name"], ident["picture"], allow_new=allow_new)
    if user is None:
        return ("redirect", "/signin?pending=1")  # request recorded; awaiting approval
    _start_session(ctx, user["id"])
    return ("redirect", "/")


def dev_login(ctx: Ctx):
    if not DEV_LOGIN:
        raise ApiError(404, "Not found")
    email = ctx.query.get("email") or "jonathan@example.com"
    user = repo.upsert_google_user(ctx.cur, "dev:" + email, email, email.split("@")[0].title(), None)
    _start_session(ctx, user["id"])
    nxt = ctx.query.get("next") or "/"
    return ("redirect", nxt if SPA_ROUTES.match(nxt) else "/")


def logout(ctx: Ctx):
    token = ctx.handler.cookies().get(auth.SESSION_COOKIE)
    if token:
        repo.delete_session(ctx.cur, auth.hash_token(token))
    ctx.set_cookies.append(_session_cookie("", 0))
    return {"ok": True}


def _broker_session_hash(ctx: Ctx) -> str:
    token = ctx.handler.cookies().get(auth.SESSION_COOKIE) if ctx.handler else None
    if not token:
        raise ApiError(401, "Please sign in again before connecting a brokerage.")
    return auth.hash_token(token)


def _broker_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except broker_oauth.Error as exc:
        raise ApiError(exc.status, str(exc)) from None


def broker_connections(ctx: Ctx):
    return _broker_call(broker_oauth.list_brokers, ctx.cur, ctx.uid)


def broker_connect(ctx: Ctx):
    provider = ctx.params[0]
    environment = ctx.body.get("environment", broker_oauth.PROVIDERS[provider]["default_environment"])
    return _broker_call(broker_oauth.connect, ctx.conn, ctx.uid, provider, environment,
                        _broker_session_hash(ctx), permission=ctx.body.get("permission", "read"))


def broker_callback(ctx: Ctx):
    provider = ctx.params[0]
    result = _broker_call(broker_oauth.callback, ctx.conn, ctx.uid, provider, ctx.query,
                          _broker_session_hash(ctx))
    # Only fixed provider/status identifiers enter the return URL. Provider
    # errors, codes, request tokens and state are never reflected into the SPA.
    return ("redirect", "/settings/account?broker=%s&broker_status=%s" % (provider, result))


def broker_disconnect(ctx: Ctx):
    return _broker_call(broker_oauth.disconnect, ctx.conn, ctx.uid, ctx.params[0],
                        ctx.body.get("environment"))


def _paper_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except alpaca_paper.Error as exc:
        raise ApiError(exc.status, str(exc)) from None


def alpaca_paper_account(ctx: Ctx):
    return _paper_call(alpaca_paper.overview, ctx.conn, ctx.uid)


def alpaca_paper_draft(ctx: Ctx):
    return _paper_call(alpaca_paper.create_order, ctx.conn, ctx.uid, ctx.body)


def alpaca_paper_action(ctx: Ctx):
    operation = {"submit": alpaca_paper.submit_order, "refresh": alpaca_paper.refresh_order,
                 "cancel": alpaca_paper.cancel_order}[ctx.params[1]]
    return _paper_call(operation, ctx.conn, ctx.uid, _int_param(ctx))


def _perps_live_call(fn, *args):
    try:
        return fn(*args)
    except kalshi_perps_trading.Error as exc:
        raise ApiError(exc.status, str(exc)) from None


def kalshi_perps_live_account(ctx: Ctx):
    return _perps_live_call(kalshi_perps_trading.overview, ctx.conn, ctx.uid)


def kalshi_perps_live_policy(ctx: Ctx):
    return _perps_live_call(kalshi_perps_trading.save_policy, ctx.conn, ctx.uid, ctx.body)


def kalshi_perps_live_draft(ctx: Ctx):
    return _perps_live_call(kalshi_perps_trading.create_order, ctx.conn, ctx.uid, ctx.body)


def kalshi_perps_live_proposal(ctx: Ctx):
    return _perps_live_call(kalshi_perps_trading.preview_proposal,
                            ctx.conn, ctx.uid, _int_param(ctx), ctx.body)


def kalshi_perps_live_action(ctx: Ctx):
    operation = {"submit": kalshi_perps_trading.submit_order,
                 "refresh": kalshi_perps_trading.refresh_order,
                 "cancel": kalshi_perps_trading.cancel_order}[ctx.params[1]]
    args = (ctx.conn, ctx.uid, _int_param(ctx))
    return _perps_live_call(operation, *args) if ctx.params[1] == "refresh" else _perps_live_call(operation, *args, ctx.body)


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


def _researchable_markets(cur) -> List[Dict]:
    """The research picker's markets (app.services.markets), with the shared series cache."""
    ready = _shared("series_with_candles", 120, lambda c: repo.series_with_candles(c), cur)
    return market_service.researchable_markets(cur, ready)


def me(ctx: Ctx):
    return {
        "user": {
            "id": ctx.user["id"], "email": ctx.user["email"], "name": ctx.user["name"],
            "username": ctx.user.get("username"), "ui_theme": ctx.user.get("ui_theme") or "tau",
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
        "needs_card": _needs_card(ctx),
        "free_bonus": float(billing.FREE_BONUS),
        "credit_balance": round(repo.credit_balance(ctx.cur, ctx.uid), 4),
        "min_run_balance": float(billing.MIN_RUN_BALANCE),  # the headroom a research run needs to start
        "perps_live_available": kalshi_perps_trading.enabled(),  # hide the Funds perps box when live perps are off
        "markets": _researchable_markets(ctx.cur),
        "directions": [{"key": k, **v} for k, v in agent.DIRECTIONS.items()],
    }


def _start_of_day_utc() -> datetime:
    return repo.now_utc().replace(hour=0, minute=0, second=0)


def _mode_bucket(cur, uid: int, mode: str, open_pos: List[Dict], deps: List[Dict], day) -> Dict:
    """Money in one deployment-mode bucket (paper | demo | live), from that mode's own
    positions and deployments only — so the three buckets never double-count each other."""
    pos = [p for p in open_pos if p["mode"] == mode]
    return {
        "open_at_cost": round(sum(float(p["qty"]) * float(p["entry_price"]) for p in pos), 2),
        "open_positions": len(pos),
        "running": sum(1 for d in deps if d["mode"] == mode and d["status"] == "running"),
        "realized_pnl": round(repo.realized_pnl(cur, uid, mode), 2),
        "today_pnl": round(repo.realized_pnl(cur, uid, mode, day), 2),
    }


def _live_balance(cur, uid: int) -> Dict:
    """The user's REAL Kalshi cash (cached, best-effort) + where to deposit. We can't mint
    real money, so an unconnected key or a failed fetch degrades to a connect/unavailable
    state. The live key is never logged or echoed — only the resulting balance is surfaced."""
    key = repo.get_kalshi_key(cur, uid)
    out = {"connected": key is not None, "balance": None, "funding_url": kalshi_account.KALSHI_FUNDING_URL}
    if key is not None:
        try:
            out["balance"] = kalshi_account.balance_cached(uid, kalshi_account.credentials_from_row(uid, key))
        except Exception:
            out["balance"] = None
    return out


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
    deps = repo.list_deployments(cur, ctx.uid)
    curves = repo.deployment_curves(cur, ctx.uid)
    balance = repo.paper_balance(cur, ctx.uid)
    deposited = repo.paper_deposits(cur, ctx.uid)
    # Three mode buckets, each self-contained (real / sandbox / simulation). Paper + demo both
    # carry an app-controlled cash layer on top of the shared fields; live carries the real
    # Kalshi balance (money we never hold).
    paper = _mode_bucket(cur, ctx.uid, "paper", open_pos, deps, day)
    equity = balance + paper["open_at_cost"]
    paper.update(
        cash=round(balance, 2),
        equity=round(equity, 2),
        deposited=round(deposited, 2),
        total_pnl=round(equity - deposited, 2),
        roi=round((equity - deposited) / deposited, 4) if deposited > 0 else None,
        daily=repo.daily_pnl(cur, ctx.uid, "paper"),
    )
    # Demo: real fills applied to the capital WE set. Equity = capital + realized-since-reload,
    # and the displayed realized P&L is net of the reload baseline (so a reload reads as $X flat).
    demo = _mode_bucket(cur, ctx.uid, "demo", open_pos, deps, day)
    de = repo.demo_equity(cur, ctx.uid)
    demo.update(capital=de["capital"], equity=de["equity"], realized_pnl=de["realized"],
                total_pnl=de["realized"], roi=de["roi"])
    live = _mode_bucket(cur, ctx.uid, "live", open_pos, deps, day)
    live.update(_live_balance(cur, ctx.uid))
    return {
        "paper": paper,
        "demo": demo,
        "live": live,
        "open_positions": open_pos,
        "recent_closed": repo.user_positions(cur, ctx.uid, "closed", 12),
        # Live book-vs-Kalshi reconciliation: empty list = book matches the exchange; any rows are
        # open discrepancies the reconciler flagged (shown as a trust badge on the Live bucket).
        "reconcile": repo.open_reconcile_rows(cur, ctx.uid),
        "deployments": [_deployment_out(d, curves.get(d["id"], []), unreal_by_dep.get(d["id"])) for d in deps],
        "agents": repo.active_run_counts(cur, ctx.uid),
        "freshness": _freshness(cur),
    }


TRACK_RECORD_TTL = 60.0  # seconds; the record moves only when a trade closes
_TRACK_RECORD: Dict[int, Tuple[float, Dict]] = {}


def get_track_record(ctx: Ctx):
    """The fund-grade track record: realized results per money bucket (live / demo / paper), from
    the user's own closed trades. A plain per-user TTL cache (never served stale past the TTL), so
    a page that is reloaded or left open costs one grouped scan a minute at most."""
    hit = _TRACK_RECORD.get(ctx.uid)
    if hit and time.time() - hit[0] < TRACK_RECORD_TTL:
        return hit[1]
    val = track_record.build(repo.track_record_rows(ctx.cur, ctx.uid))
    _TRACK_RECORD[ctx.uid] = (time.time(), val)
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


def _deployment_out(d: Dict, curve: List, unrealized: Optional[float] = None) -> Dict:
    res = d.get("result") or {}
    return {
        "id": d["id"], "strategy_id": d["strategy_id"], "title": d["title"], "direction": d["direction"],
        "market": d["market"], "mode": d["mode"], "status": d["status"], "status_reason": d["status_reason"],
        "realized_pnl": round(float(d["realized_pnl"]), 2), "closed_trades": d["closed_trades"], "wins": d["wins"],
        "unrealized_pnl": unrealized, "open_positions": d["open_positions"], "created_at": d["created_at"], "curve": curve,
        "stake": d["spec"]["sizing"]["stake"], "max_positions": d["spec"]["sizing"]["max_positions"],
        "backtest": {"out_of_sample": res.get("out_of_sample"), "capital": res.get("capital")},
    }


def models(ctx: Ctx):
    """The models a user can pick to run their research, for the dropdown."""
    return {"models": catalog.catalog_json(), "default": catalog.DEFAULT_KEY}


def list_runs(ctx: Ctx):
    # The self-evolving exploration policy (Tau-RSI), summarized read-only for the research
    # index so the cockpit can show the engine getting smarter — same shape as get_run's rsi
    # block (minus the per-run dream line), so the client renders both the same way.
    pol = repo.get_policy(ctx.cur, ctx.uid)
    policy = {"evolved": bool(pol),
              "score": round(float(pol["score"]), 2) if pol else None,
              "base_score": round(pol["base_score"], 2) if (pol and pol.get("base_score") is not None) else None,
              "summary": pol.get("summary") if pol else None,
              "evolved_at": pol["updated_at"] if pol else None}
    return {"runs": repo.list_runs(ctx.cur, ctx.uid), "counts": repo.active_run_counts(ctx.cur, ctx.uid),
            "policy": policy}


def get_run(ctx: Ctx):
    run = repo.get_run(ctx.cur, ctx.uid, _int_param(ctx))
    if run is None or run["kind"] != "research":
        raise ApiError(404, "No such research run.")
    after = int(ctx.query.get("after") or 0)
    # This run's gated strategies, live — so the Hypotheses table fills as each chunk clears
    # the gate (a run_forever run never reaches "succeeded", so we can't wait for it).
    strategies = repo.list_strategies(ctx.cur, ctx.uid, run_id=run["id"])
    pol = repo.get_policy(ctx.cur, ctx.uid)  # the self-evolving exploration policy (Tau-RSI)
    dream = repo.latest_dream_event(ctx.cur, ctx.uid)
    return {
        "run": run,
        "events": repo.run_events(ctx.cur, run["id"], after),
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
    }


def _needs_card(ctx: Ctx) -> bool:
    """True when payments are live but the user has no card on file. Agent usage
    is metered per token, so we require a card before any run — the free credits
    unlock the moment one is saved."""
    if not billing.configured():
        return False
    cust = repo.get_stripe_customer(ctx.cur, ctx.uid)
    return not (cust and cust.get("default_pm_id"))


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
        raise ApiError(429, "You already have %d agents researching. Wait for one to finish." % MAX_ACTIVE_RESEARCH)
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
        "stake": s["spec"]["sizing"]["stake"],
        "side": s["spec"]["perpetual"]["side"] if specmod.is_perpetual_spec(s["spec"]) else s["spec"].get("side"),
        **({"kind": "perpetual", "research_only": True} if specmod.is_perpetual_spec(s["spec"]) else {}),
        "deployed": bool(s.get("active_deps")), "deploy_live": bool(s.get("live_deps")),
        "shared_from": s.get("shared_from_name") if s.get("shared_from_user_id") else None,
    }


def _mark_fields(p: Dict) -> Dict:
    """Live mark-to-market for one open position from the engine-stamped mark_price
    (the current YES bid). None until the engine's first mark after entry."""
    qty = int(p["qty"])
    cost = qty * float(p["entry_price"]) + float(p.get("entry_fee") or 0)
    mark = p.get("mark_price")
    if mark is None:
        return {"mark": None, "value": None, "unrealized": None, "mark_ts": None}
    mark = float(mark)
    # mark is the YES bid. A YES contract liquidates ~yes_bid; a NO contract ~1-yes_ask, which we
    # don't store — estimate NO as 1-yes_bid (slightly high). Same estimate across paper/sim/live
    # (and the UI labels it "est."); NO positions now occur live too.
    value = round(qty * (mark if p["side"] == "yes" else 1.0 - mark), 2)
    return {"mark": mark, "value": value, "unrealized": round(value - cost, 2), "mark_ts": p.get("mark_ts")}


def _with_marks(rows: List[Dict]) -> List[Dict]:
    for p in rows:
        p.update(_mark_fields(p))
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
    matched = counts.get(status, 0) if status else counts["total"] - noise
    rows = repo.list_strategies(ctx.cur, ctx.uid, direction, status, market, limit=per, offset=page * per,
                                q=search, deployed=deployed, hide_noise=hide_noise)
    cards = [_strategy_card(s) for s in rows]
    _attach_real_records(ctx.cur, ctx.uid, cards)
    return {"strategies": cards, "counts": counts,
            "matched": matched, "page": page, "per": per, "pages": (matched + per - 1) // per}


def _attach_real_records(cur, uid: int, cards: List[Dict]) -> None:
    """Stamp each deployed card with what it has actually done since deploying (realized P&L and
    closed trades across its active deployments), so the list shows reality next to the backtest.
    Real money is never summed with practice money: a strategy with a live deployment reports its
    live deployments only (beside its Live badge), otherwise its paper/demo ones. One query, and
    only when the page has a deployed strategy."""
    if not any(c.get("deployed") for c in cards):
        return
    real: Dict[int, Dict[bool, Dict]] = {}
    for d in repo.list_deployments(cur, uid):
        r = real.setdefault(d["strategy_id"], {}).setdefault(d["mode"] == "live", {"pnl": 0.0, "trades": 0, "open": 0})
        r["pnl"] += float(d["realized_pnl"] or 0)
        r["trades"] += int(d["closed_trades"] or 0)
        r["open"] += int(d["open_positions"] or 0)
    for c in cards:
        books = real.get(c["id"]) if c.get("deployed") else None
        if books:
            live = True in books
            r = books[live]
            c["real"] = {**r, "pnl": round(r["pnl"], 2), "live": live}


def _owned_strategy(ctx: Ctx) -> Dict:
    s = repo.get_strategy(ctx.cur, ctx.uid, _int_param(ctx))
    if s is None:
        raise ApiError(404, "No such strategy.")
    return s


def delete_strategy(ctx: Ctx):
    """Remove a strategy from the user's inventory. Blocked while it's deployed —
    stop the deployment first."""
    s = _owned_strategy(ctx)
    if any(d["strategy_id"] == s["id"] for d in repo.list_deployments(ctx.cur, ctx.uid, include_stopped=False)):
        raise ApiError(409, "Stop this strategy's deployment before deleting it.")
    repo.delete_strategy(ctx.cur, ctx.uid, s["id"])
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
    rows = repo.list_notifications(ctx.cur, ctx.uid)
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
    return {"ok": True, "theme": theme}


def unsubscribe(ctx: Ctx):
    """Public one-click unsubscribe from community emails (HMAC-signed link, no login needed)."""
    try:
        uid = int(ctx.query.get("u") or 0)
    except ValueError:
        uid = 0
    ok = bool(uid) and notify.unsubscribe_token_valid(uid, ctx.query.get("t") or "") and repo.set_email_opt_out(ctx.cur, uid, True)
    msg = ("You're unsubscribed from Tau community emails." if ok
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
    out.update(
        spec=s["spec"], rules=specmod.describe(s["spec"]), gates=res.get("gates"), dataset=res.get("dataset"),
        recent_trades=res.get("recent_trades"),
        experiment=_experiment_block(ctx.cur, s["id"], s.get("experiment_id")),
        deployments=[_deployment_out(d, []) for d in repo.list_deployments(ctx.cur, ctx.uid) if d["strategy_id"] == s["id"]],
        holdings=[{
            "ticker": p["ticker"], "side": p["side"], "qty": int(p["qty"]), "mode": p["mode"],
            "entry_price": float(p["entry_price"]),
            "cost": round(int(p["qty"]) * float(p["entry_price"]) + float(p["entry_fee"] or 0), 2),
            "market_close_time": p["market_close_time"], **_mark_fields(p),
        } for p in repo.positions_for_strategy(ctx.cur, ctx.uid, s["id"], "open")],
    )
    return out


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
        stake=_num(ctx.body, "stake", 1.0, 500.0, s["spec"]["sizing"]["stake"]),
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
    curves = repo.deployment_curves(ctx.cur, ctx.uid)
    return {
        "deployments": [_deployment_out(d, curves.get(d["id"], [])) for d in repo.list_deployments(ctx.cur, ctx.uid)],
        "open_positions": _with_marks(repo.user_positions(ctx.cur, ctx.uid, "open")),
        "recent_closed": repo.user_positions(ctx.cur, ctx.uid, "closed", 20),
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
    where = {"live": "LIVE money", "demo": "the demo (sandbox) exchange"}.get(mode, "paper")
    repo.add_chat(cur, ctx.uid, "system", "Deployed %s on %s." % (s["title"], where))
    return {"id": dep_id}


def strategy_live_readiness(ctx: Ctx):
    """Road to live: every gate between this strategy and real money, with progress. Read-only;
    the same functions the deploy paths enforce, so this view can never disagree with them."""
    s = repo.get_strategy(ctx.cur, ctx.uid, _int_param(ctx))
    if s is None:
        raise ApiError(404, "No such strategy.")
    candidate = bool(agent._is_deployment_candidate(ctx.cur, s["id"]))
    paper = agent.paper_evidence(ctx.cur, ctx.uid, s["id"])
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
    return {"ok": True, "status": status}


# -- chat ------------------------------------------------------------------------


def get_chat(ctx: Ctx):
    after = int(ctx.query.get("after") or 0)
    counts = repo.active_run_counts(ctx.cur, ctx.uid)
    return {"messages": repo.chat_messages(ctx.cur, ctx.uid, after), "agent_busy": counts["chat_active"] > 0}


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
            raise ApiError(400, "Turn on autopilot first — live autopilot builds on it.")
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
    repo.add_chat(ctx.cur, ctx.uid, "system", "Kill switch: live autopilot off, %d live deployment(s) paused." % paused)
    return {"ok": True, "paused": paused}


def _research_activity(cur, uid: int) -> Dict:
    """What research is doing for the autopilot float: the markets being researched now and the
    last 7 days' tested/passed counts, so a quiet panel reads as working, not stuck. One bounded read."""
    from app import rsi
    since = repo.now_utc() - timedelta(days=7)
    active = [r for r in repo.list_runs(cur, uid, limit=50) if r.get("status") in ("queued", "running", "paused")]
    # The week's totals come from one aggregate, not the 50 newest runs: a busy autopilot starts
    # 250+ runs a week, and the capped list told Todd it had tested 73 ideas when it was hundreds.
    # Passed counts strategies that cleared every gate: an old run's counter held 68 backtest-only.
    week = repo.research_week(cur, uid, since)
    return {"active": [MARKETS[r["market"]].label if r.get("market") in MARKETS else (r.get("market") or "a market it's still picking")
                       for r in active],
            "tested_7d": sum(int(r.get("tried") or 0) for r in week),
            "passed_7d": repo.strategies_passed_since(cur, uid, since),
            "runs_7d": sum(int(r.get("runs") or 0) for r in week),
            "cost_7d": round(sum(rsi.run_cost_usd(r) for r in week), 2)}


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
    active = research.get("active") or []
    if active:
        names = [n for n in dict.fromkeys(active) if n != "a market it's still picking"]  # two runs on one market read as one
        now = ("Right now it's researching %s." % (
            names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1])) if names \
            else "Right now it's picking a market to research."
    else:
        now = "Right now it's between research runs. It checks in about every %d minutes." % max(1, COPILOT_REVIEW_MINUTES)
    lines = [now]
    if d.get("focus"):
        lines.append("It sticks to the focus you set: %s." % ", ".join(d["focus"]))
    tested, passed = int(research.get("tested_7d") or 0), int(research.get("passed_7d") or 0)
    if tested:
        cost = float(research.get("cost_7d") or 0)
        lines.append("This week it tested %s%s and %s." % (
            _plural(tested, "idea"), " for ${:,.2f}".format(cost) if cost >= 0.01 else "",
            "none has passed its tests yet. That's normal: most ideas fail" if not passed else "{:,} passed".format(passed)))
    paper, prog = int(d.get("paper_running") or 0), d.get("paper_progress")
    if not paper:
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
    t_line = _tournament_line(d.get("tournament"))
    if t_line:
        lines.append(t_line)
    lines += _waiting_lines(d.get("paper_waiting") or []) if paper else []
    lines += _paused_lines(d.get("paused_recent") or [])
    stop_line = _stop_line(d.get("early_exits_7d") or {})
    if stop_line:
        lines.append(stop_line)
    if int(d.get("live_running") or 0):
        lines.append("%s trading real money." % _plural(int(d["live_running"]), "strategy is", "strategies are"))
    else:
        lines.append("Nothing trades real money until a strategy makes money on paper over at least %d trades "
                     "from %d separate events and %d hours, and you turn on live autopilot." % (
                         agent.MIN_REALISTIC_PAPER_TRADES, agent.MIN_PAPER_EVENTS, int(agent.MIN_PAPER_SPAN_HOURS)))
    return lines


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
            line += " Today %s of %d checks found a contract worth buying." % (found or "none", checks)
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
    return why.rstrip(".")[:120] or "it was paused"


def _tournament_summary(cur, uid: int, deps: List[Dict]) -> Optional[Dict]:
    from app import tournament
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


def _paused_recent(deps: List[Dict], hours: int = 24) -> List[Dict]:
    """Paper deployments paused in the last `hours`: they leave the 'running' count, so without
    this a stopped-out strategy simply vanishes from the panel."""
    since = repo.now_utc() - timedelta(hours=hours)
    out = []
    for d in deps:
        at = d.get("updated_at")
        if d["mode"] == "paper" and d["status"] == "paused" and at is not None and at >= since:
            out.append({"deployment_id": d["id"], "title": _short_title(d.get("title")),
                        "trades": int(d.get("closed_trades") or 0), "pnl": round(float(d.get("realized_pnl") or 0), 2),
                        "why": _plain_pause_reason(d.get("status_reason"))})
    return out[:3]


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


def autopilot_status(ctx: Ctx):
    """Lightweight status for the floating autopilot window."""
    cur, u = ctx.cur, ctx.user
    deps = repo.list_deployments(cur, ctx.uid)
    live_run = [d for d in deps if d["mode"] == "live" and d["status"] == "running"]
    paper_run = [d for d in deps if d["mode"] == "paper" and d["status"] == "running"]
    demo_run = [d for d in deps if d["mode"] == "demo" and d["status"] == "running"]
    gates_ok = bool(engine.LIVE_TRADING_ENABLED and repo.get_kalshi_key(cur, ctx.uid) is not None)
    live_on = bool(u.get("autopilot_live")) and gates_ok and bool(u.get("autopilot"))
    mode = "live" if (live_on and live_run) else ("live-armed" if live_on else ("paper" if u.get("autopilot") else "off"))
    today_live = round(repo.realized_pnl(cur, ctx.uid, "live", _start_of_day_utc()), 2)
    limit = float(u.get("autopilot_daily_loss_limit") or 50)
    # When autopilot is ON but can't spend (no card, or balance below the per-run floor), the worker
    # silently skips the user via billing.is_ready — the SAME gate, read here only to surface WHY the
    # panel is quiet so it doesn't look broken. Never changes the gate; purely a status readout.
    billing_blocked = bool(u.get("autopilot")) and billing.configured() and not billing.is_ready(cur, ctx.uid)
    # Paper -> live progress: the running paper strategy closest to the realistic-trade gate, so a
    # user on autopilot can see the funnel moving. Counts only (no bootstrap): this endpoint polls.
    paper_progress = None
    if paper_run:
        sids = sorted({int(d["strategy_id"]) for d in paper_run})
        prog = repo.paper_progress(cur, ctx.uid, sids)
        titles = {int(d["strategy_id"]): d.get("title") or "" for d in paper_run}
        best = max(sids, key=lambda s: (prog.get(s, (0, 0.0))[0], prog.get(s, (0, 0.0))[1]))
        trades, net = prog.get(best, (0, 0.0))
        paper_progress = {"strategy_id": best, "title": titles[best], "trades": trades,
                          "trades_needed": agent.MIN_REALISTIC_PAPER_TRADES, "net_pnl": round(net, 2),
                          "strategies": len(sids)}
    out = {
        "research": _research_activity(cur, ctx.uid),
        "autopilot": bool(u.get("autopilot")),
        "autopilot_live": bool(u.get("autopilot_live")),
        "live_enabled": bool(engine.LIVE_TRADING_ENABLED),
        "kalshi_connected": repo.get_kalshi_key(cur, ctx.uid) is not None,
        "mode": mode,
        "live_running": len(live_run), "paper_running": len(paper_run), "demo_running": len(demo_run),
        "today_live_pnl": today_live,
        # The paper book's day, so a paper-only panel shows its own money instead of a live $0.00.
        "today_paper_pnl": round(repo.realized_pnl(cur, ctx.uid, "paper", _start_of_day_utc()), 2),
        "daily_loss_limit": limit,
        "loss_headroom": round(max(0.0, limit + min(0.0, today_live)), 2),  # how much loss budget is left today
        "last_action": repo.last_autopilot_action(cur, ctx.uid),
        "last_review_at": repo.last_review_at(cur, ctx.uid),  # liveness: a quiet review posts nothing, this still shows it ran
        "model": u.get("autopilot_model") or catalog.DEFAULT_KEY,  # the model the autopilot's own runs use
        "focus": agent.focus_tokens(u),  # the user's binding market focus ([] = any market)
        "billing_blocked": billing_blocked,
        "billing_reason": (("card" if _needs_card(ctx) else "credits") if billing_blocked else None),
        # Warn before the pause, not after: days of credit left when that's under three.
        "credits_low_days": (_credits_running_low(cur, ctx.uid)
                             if u.get("autopilot") and billing.configured() and not billing_blocked else None),
        "paper_progress": paper_progress,
        "paper_open": int(repo.user_open_exposure(cur, ctx.uid, "paper")["n"]) if paper_run else 0,
        "paper_waiting": _paper_waiting(paper_run, _scan_tally(cur, paper_run)),
        "paused_recent": _paused_recent(deps),
        "early_exits_7d": _early_exits(cur, ctx.uid),
        "tournament": _tournament_summary(cur, ctx.uid, deps),
    }
    out["story"] = _autopilot_story(out)
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


# -- funds -------------------------------------------------------------------------


def funds(ctx: Ctx):
    cur = ctx.cur
    key = repo.get_kalshi_key(cur, ctx.uid)
    kalshi = _live_balance(cur, ctx.uid)
    if key is not None:
        kalshi["key_id"] = key["key_id"][:4] + "…" + key["key_id"][-4:]
    dev = repo.get_kalshi_dev_key(cur, ctx.uid)
    kalshi_dev_key = {"connected": dev is not None}
    if dev is not None:
        kalshi_dev_key["key_id"] = dev["key_id"][:4] + "…" + dev["key_id"][-4:]
    de = repo.demo_equity(cur, ctx.uid)
    return {
        "paper": {"cash": round(repo.paper_balance(cur, ctx.uid), 2), "ledger": repo.ledger_rows(cur, ctx.uid)},
        "demo": {"capital": de["capital"], "equity": de["equity"], "realized": de["realized"]},
        "kalshi": kalshi,
        "kalshi_dev": kalshi_dev_key,
    }


def paper_transfer(ctx: Ctx):
    kind = ctx.body.get("kind")
    if kind not in ("deposit", "withdraw", "reset"):
        raise ApiError(400, "Choose deposit, withdraw or reset.")
    amount = round(_num(ctx.body, "amount", 1, MAX_PAPER_BALANCE), 2)
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        if kind == "reset":
            # Start fresh at `amount`. Blocked with open paper positions: wiping the ledger would
            # orphan their already-debited cost and the equity math would double-count.
            if any(p["mode"] == "paper" for p in repo.user_positions(tx, ctx.uid, "open")):
                raise ApiError(409, "Close your open paper positions before resetting the account.")
            repo.reset_paper_account(tx, ctx.uid, amount)
            return {"ok": True}
        bal = repo.paper_balance(tx, ctx.uid)
        if kind == "withdraw" and amount > bal:
            raise ApiError(409, "You only have $%.2f of paper cash free." % bal)
        if kind == "deposit" and bal + amount > MAX_PAPER_BALANCE:
            raise ApiError(409, "Paper accounts top out at $%s." % "{:,.0f}".format(MAX_PAPER_BALANCE))
        repo.add_ledger(tx, ctx.uid, "deposit" if kind == "deposit" else "withdrawal",
                        amount if kind == "deposit" else -amount,
                        "Paper %s" % ("deposit" if kind == "deposit" else "withdrawal"))
    return {"ok": True}


def demo_reload(ctx: Ctx):
    """Set the app-controlled demo starting capital. Demo places real sandbox orders but the money
    is ours, so this never touches the real Kalshi demo-account balance — it just resets the
    capital that real fills are applied to, and zeroes the displayed demo P&L from here."""
    amount = round(_num(ctx.body, "amount", 1, MAX_PAPER_BALANCE), 2)
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        repo.reload_demo(tx, ctx.uid, amount)
    return {"ok": True}


def save_kalshi_key(ctx: Ctx):
    key_id = str(ctx.body.get("key_id") or "")
    pem = str(ctx.body.get("private_key") or "")
    try:
        cash = kalshi_account.verify(key_id, pem)
        blob = kalshi_account.encrypt_private_key(ctx.uid, pem.strip())
    except kalshi_account.KalshiKeyError as e:
        raise ApiError(400, str(e))
    except RuntimeError:
        raise ApiError(503, "This server can't store keys yet (encryption key not configured).")
    with repo.transaction(ctx.conn) as tx:
        _perps_live_call(kalshi_perps_trading.guard_key_change, tx, ctx.uid, "production")
        repo.save_kalshi_key(tx, ctx.uid, key_id.strip(), blob)
    return {"ok": True, "balance": cash}


def delete_kalshi_key(ctx: Ctx):
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        if any(d["mode"] == "live" and d["status"] == "running" for d in repo.list_deployments(tx, ctx.uid)):
            raise ApiError(409, "Pause or stop your live deployments before disconnecting Kalshi.")
        _perps_live_call(kalshi_perps_trading.guard_key_change, tx, ctx.uid, "production")
        repo.delete_kalshi_key(tx, ctx.uid)
    return {"ok": True}


def save_kalshi_dev_key(ctx: Ctx):
    """Store the user's own Kalshi DEMO (sandbox) key, encrypted at rest. Mirrors
    save_kalshi_key, but proves the key against the SANDBOX exchange (never production) and
    stores it in the separate app_kalshi_dev_keys table, so demo orders can never pick up a
    live key. The raw private key is used only to verify + encrypt here; it is never logged or echoed."""
    key_id = str(ctx.body.get("key_id") or "").strip()
    pem = str(ctx.body.get("private_key") or "")
    if not key_id or len(key_id) > 128:
        raise ApiError(400, "Enter the API key ID from your Kalshi demo account settings.")
    try:
        creds = (key_id, kalshi_account.parse_private_key(pem))
    except kalshi_account.KalshiKeyError as e:
        raise ApiError(400, str(e))
    try:
        kalshi_dev_exec.demo_fills(creds)  # authenticate against the sandbox only — proves the key works
    except kalshi_dev_exec.DemoHostError:
        raise ApiError(503, "The demo (sandbox) exchange isn't configured on this server yet.")
    except Exception:
        raise ApiError(400, "Kalshi's demo exchange rejected this key. Check the key ID matches the private key, "
                            "and that it's a DEMO key from demo.kalshi.co — not your live key.")
    try:
        blob = kalshi_account.encrypt_private_key(ctx.uid, pem.strip())
    except RuntimeError:
        raise ApiError(503, "This server can't store keys yet (encryption key not configured).")
    with repo.transaction(ctx.conn) as tx:
        _perps_live_call(kalshi_perps_trading.guard_key_change, tx, ctx.uid, "demo")
        repo.set_kalshi_dev_key(tx, ctx.uid, key_id, blob)
    return {"ok": True}


def delete_kalshi_dev_key(ctx: Ctx):
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        if any(d["mode"] == "demo" and d["status"] == "running" for d in repo.list_deployments(tx, ctx.uid)):
            raise ApiError(409, "Pause or stop your demo deployments before removing your demo key.")
        _perps_live_call(kalshi_perps_trading.guard_key_change, tx, ctx.uid, "demo")
        repo.delete_kalshi_dev_key(tx, ctx.uid)
    return {"ok": True}


def waitlist(ctx: Ctx):
    email = str(ctx.body.get("email") or "").strip().lower()
    note = str(ctx.body.get("note") or "").strip()[:500]
    if not repo.EMAIL_RE.match(email) or len(email) > 320:
        raise ApiError(400, "Enter a valid email address.")
    cur = ctx.cur
    if repo.recent_waitlist_from(cur, "", repo.now_utc() - timedelta(minutes=1)) >= MAX_WAITLIST_PER_MINUTE:
        raise ApiError(429, "We're getting a lot of requests right now. Try again in a minute.")
    is_new = repo.add_waitlist(cur, email, note or None)
    if is_new:
        notify.waitlist_request(email, note or None, repo.count_waitlist(cur))
    return {"ok": True}


# -- community -------------------------------------------------------------------

MAX_POSTS_PER_HOUR = 30


def _post_snapshot(cur, user_id: int, kind: str, ref_id: int) -> Optional[Dict]:
    """Build a self-contained, denormalized snapshot from the user's OWN strategy
    or deployment, so a post never exposes another user's data or a live spec."""
    if kind == "strategy":
        strat = repo.get_strategy(cur, user_id, ref_id)
        if strat is None:
            raise ApiError(404, "That strategy isn't yours or doesn't exist.")
        oos = (strat.get("result") or {}).get("out_of_sample") or {}
        return {"kind": "strategy", "id": strat["id"], "title": strat["title"], "market": strat["market"],
                "status": strat["status"], "pnl": oos.get("pnl"), "trades": oos.get("trades"), "win_rate": oos.get("win_rate")}
    if kind == "deployment":
        dep = repo.get_deployment(cur, user_id, ref_id)
        if dep is None:
            raise ApiError(404, "That deployment isn't yours or doesn't exist.")
        return {"kind": "deployment", "id": dep["id"], "title": dep["title"], "market": dep["market"],
                "mode": dep["mode"], "realized_pnl": round(float(dep["realized_pnl"]), 2), "closed_trades": dep["closed_trades"]}
    if kind == "pnl":
        paper = repo.realized_pnl(cur, user_id, "paper")
        live = repo.realized_pnl(cur, user_id, "live")
        return {"kind": "pnl", "paper_pnl": round(paper, 2), "live_pnl": round(live, 2)}
    return None


def _post_out(p: Dict) -> Dict:
    return {
        "id": p["id"], "body": p["body"], "kind": p["kind"], "snapshot": p.get("snapshot"),
        "likes": p["likes_count"], "comments": p["comments_count"], "created_at": p["created_at"],
        "author": p.get("name") or "Trader", "username": p.get("username"), "picture": p.get("picture_url"),
        "mine": p.get("mine", False), "liked": p.get("liked", False),
        "reactions": p.get("reactions", []),
        "image": ("/api/community/image/%d" % p["image_id"]) if p.get("image_id") else None,
        "edited": bool(p.get("edited_at")),
    }


def community(ctx: Ctx):
    before = int(ctx.query.get("before") or 0)
    mine_only = str(ctx.query.get("mine") or "") in ("1", "true")
    return {"posts": [_post_out(p) for p in repo.list_posts(ctx.cur, ctx.uid, before, mine_only=mine_only)]}


IMAGE_MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}
MAX_IMAGE_BYTES = 3 * 1024 * 1024


def _decode_image(data_url: str):
    import base64 as _b64
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        raw = _b64.b64decode(data_url, validate=True)
    except Exception:
        raise ApiError(400, "That image couldn't be read.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ApiError(413, "Images must be under 3 MB.")
    ctype = next((t for magic, t in IMAGE_MAGIC.items() if raw.startswith(magic)), None)
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        ctype = "image/webp"
    if not ctype:
        raise ApiError(400, "Only PNG, JPEG, WebP, or GIF images are allowed.")
    return ctype, raw


def _notify_mentions(cur, author_uid: int, author_name: str, body: str, link: str) -> None:
    """Notify every @-mentioned user (in-app + email), skipping the author. Best-effort."""
    handles = {h.lower() for h in repo.MENTION_RE.findall(body or "")}
    if not handles:
        return
    for u in repo.users_by_usernames(cur, list(handles)):
        if u["id"] == author_uid:
            continue
        try:
            repo.add_notification(cur, u["id"], "mention", "%s mentioned you." % author_name, link)
        except Exception as e:
            print("[mention] in-app notice failed: %r" % e, flush=True)
        if u.get("email"):
            try:
                notify.mention_notice(u["email"], u.get("name"), author_name, body)
            except Exception as e:
                print("[mention] email failed: %r" % e, flush=True)


def mention_candidates(ctx: Ctx):
    q = (ctx.query.get("q") or "").strip()[:32]
    return {"users": [{"username": u["username"], "name": u["name"]} for u in repo.mention_candidates(ctx.cur, q)]}


def create_community_post(ctx: Ctx):
    body = str(ctx.body.get("body") or "").strip()
    kind = ctx.body.get("kind") or "note"
    image = ctx.body.get("image")
    if kind not in ("note", "strategy", "deployment", "pnl"):
        raise ApiError(400, "Unknown post type.")
    if not body and kind == "note" and not image:
        raise ApiError(400, "Write something or attach a photo first.")
    if len(body) > 2000:
        raise ApiError(400, "Keep posts under 2,000 characters.")
    cur = ctx.cur
    if repo.recent_posts_count(cur, ctx.uid, repo.now_utc() - timedelta(hours=1)) >= MAX_POSTS_PER_HOUR:
        raise ApiError(429, "You've posted a lot this hour. Give it a minute.")
    image_id = None
    if image:
        ctype, raw = _decode_image(str(image))
        image_id = repo.store_image(cur, ctx.uid, ctype, raw)
    snapshot = _post_snapshot(cur, ctx.uid, kind, int(ctx.body.get("ref_id") or 0)) if kind != "note" else None
    pid = repo.create_post(cur, ctx.uid, body or _default_share_text(kind, snapshot), kind, snapshot, image_id)
    author = (repo.get_user(cur, ctx.uid) or {}).get("name") or "A trader"
    _notify_mentions(cur, ctx.uid, author, body, "/community")
    _email_community_post_async(ctx.uid, author, body or _default_share_text(kind, snapshot))
    return {"id": pid}


def _email_community_post_async(author_uid: int, author: str, preview: str) -> None:
    """Email opted-in users about a new post, off the request thread so posting stays snappy.
    Cooldown + opt-out are enforced per recipient; SES sandbox silently no-ops unverified sends."""
    def run():
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            recipients = repo.community_email_recipients(cur, author_uid)
            for r in recipients:
                notify.community_post_notice(r["email"], r.get("name"), author, preview, notify.unsubscribe_url(r["id"]))
            repo.mark_community_emailed(cur, [r["id"] for r in recipients])  # cooldown applies even to sandbox-skipped
        except Exception as e:
            print("[community] post email dispatch failed: %r" % e, flush=True)
    threading.Thread(target=run, daemon=True).start()


def edit_community_post(ctx: Ctx):
    body = str(ctx.body.get("body") or "").strip()
    if not body:
        raise ApiError(400, "A post can't be empty.")
    if len(body) > 2000:
        raise ApiError(400, "Keep posts under 2,000 characters.")
    if not repo.edit_post(ctx.cur, _int_param(ctx), ctx.uid, body):
        raise ApiError(403, "You can only edit your own posts.")
    return {"ok": True}


def community_image(ctx: Ctx):
    img = repo.get_image(ctx.cur, _int_param(ctx))
    if not img:
        raise ApiError(404, "Image not found.")
    return ("image", img["content_type"], bytes(img["data"]))


def _default_share_text(kind: str, snap: Optional[Dict]) -> str:
    if kind == "pnl" and snap:
        return "Sharing my results so far."
    if snap:
        return "Sharing a %s." % kind
    return ""


def like_post(ctx: Ctx):
    pid = _int_param(ctx)
    if not repo.post_exists(ctx.cur, pid):
        raise ApiError(404, "No such post.")
    return {"liked": repo.toggle_like(ctx.cur, pid, ctx.uid)}


# A fixed emoji palette — reactions are restricted to these so stored values stay
# small and safe (no arbitrary input).
REACTION_EMOJI = ["tau", "👍", "❤️", "🔥", "🚀", "😂", "🎉", "💯", "👀", "🤔", "😮",
                  "😢", "🙌", "🧠", "📈", "📉", "💸", "✅", "❌", "🐂", "🐻",
                  "🐐", "🦍", "🐳", "💎", "🤡", "💀", "🫡", "🌙"]


def react_post(ctx: Ctx):
    pid = _int_param(ctx)
    emoji = str(ctx.body.get("emoji") or "")
    if emoji not in REACTION_EMOJI:
        raise ApiError(400, "Unsupported reaction.")
    if not repo.post_exists(ctx.cur, pid):
        raise ApiError(404, "No such post.")
    repo.toggle_reaction(ctx.cur, pid, ctx.uid, emoji)
    return {"reactions": repo.reactions_for(ctx.cur, [pid], ctx.uid).get(pid, [])}


def post_comments(ctx: Ctx):
    pid = _int_param(ctx)
    return {"comments": [{"body": c["body"], "author": c["name"] or "Trader", "username": c.get("username"), "picture": c["picture_url"], "created_at": c["created_at"]} for c in repo.list_comments(ctx.cur, pid)]}


def create_comment(ctx: Ctx):
    pid = _int_param(ctx)
    body = str(ctx.body.get("body") or "").strip()
    if not body:
        raise ApiError(400, "Write a comment first.")
    if len(body) > 1000:
        raise ApiError(400, "Keep comments under 1,000 characters.")
    author = repo.post_author(ctx.cur, pid)
    if not author:
        raise ApiError(404, "No such post.")
    repo.add_comment(ctx.cur, pid, ctx.uid, body)
    commenter = (repo.get_user(ctx.cur, ctx.uid) or {}).get("name") or "Someone"
    _notify_mentions(ctx.cur, ctx.uid, commenter, body, "/community")
    if author["user_id"] != ctx.uid:  # don't notify yourself
        try:
            repo.add_notification(ctx.cur, author["user_id"], "comment",
                                  "%s commented on your post." % commenter, "/community")
        except Exception as e:
            print("[community] in-app notice failed for post %s: %r" % (pid, e), flush=True)
    if author["user_id"] != ctx.uid and author.get("email"):  # don't email yourself
        try:
            commenter = (repo.get_user(ctx.cur, ctx.uid) or {}).get("name") or "Someone"
            notify.comment_notice(author["email"], author.get("name"), commenter, author.get("preview") or "", body)
        except Exception as e:
            print("[community] reply notice failed for post %s: %r" % (pid, e), flush=True)
    return {"ok": True}


# -- billing ---------------------------------------------------------------------


def _customer_id(ctx: Ctx) -> str:
    cust = repo.get_stripe_customer(ctx.cur, ctx.uid)
    existing = cust["stripe_customer_id"] if cust else None
    cid = billing.get_or_create_customer(ctx.user, existing)
    if cid != existing:  # new or re-created (stale id) -> persist, drop stale default card
        repo.save_stripe_customer(ctx.cur, ctx.uid, cid)
    return cid


def _credit_runway(cur, uid: int):
    """(balance, last-7-day usage spend, days the balance lasts at that pace). Research pauses at
    zero, so this is how long autopilot keeps working; None when there is no recent usage."""
    balance = repo.credit_balance(cur, uid)
    spent_7d = repo.credit_spent_total(cur, uid, repo.now_utc() - timedelta(days=7))
    runway = round(balance / (spent_7d / 7), 1) if spent_7d > 0 and balance > 0 else None
    return balance, spent_7d, runway


CREDIT_RUNWAY_WARN_DAYS = 3


def _credits_running_low(cur, uid: int):
    """Days of credit left when autopilot will pause within CREDIT_RUNWAY_WARN_DAYS and auto-reload
    won't top it up; None otherwise. A readout for the panel, never a gate."""
    cust = repo.get_stripe_customer(cur, uid)
    if cust and cust.get("auto_reload") and cust.get("default_pm_id"):
        return None
    runway = _credit_runway(cur, uid)[2]
    return runway if runway is not None and runway < CREDIT_RUNWAY_WARN_DAYS else None


def billing_state(ctx: Ctx):
    cur = ctx.cur
    cust = repo.get_stripe_customer(cur, ctx.uid)
    cards, default_pm, auto_reload = [], None, True
    reload_amount, reload_threshold = float(billing.AUTORELOAD_AMOUNT), float(billing.AUTORELOAD_THRESHOLD)
    if cust and billing.configured():
        try:
            cards = billing.list_cards(cust["stripe_customer_id"])
        except billing.StripeError:
            cards = []
        default_pm = cust.get("default_pm_id")
        auto_reload = bool(cust.get("auto_reload"))
        if cust.get("reload_amount") is not None:
            reload_amount = float(cust["reload_amount"])
        if cust.get("reload_threshold") is not None:
            reload_threshold = float(cust["reload_threshold"])
    balance, spent_7d, runway = _credit_runway(cur, ctx.uid)
    return {
        "configured": billing.configured(),
        "publishable_key": billing.STRIPE_PUBLISHABLE_KEY,
        "balance": round(balance, 4),
        "spent": round(repo.credit_spent_total(cur, ctx.uid), 4),
        "spent_7d": round(spent_7d, 4),
        "runway_days": runway,
        "free_bonus": float(billing.FREE_BONUS),
        "topup_fee_pct": float(billing.TOPUP_FEE) * 100,
        "autoreload_threshold": reload_threshold,
        "autoreload_amount": reload_amount,
        "min_reload_amount": float(billing.AUTORELOAD_AMOUNT),
        "min_reload_threshold": float(billing.AUTORELOAD_THRESHOLD),
        "min_topup": float(billing.MIN_TOPUP), "max_topup": float(billing.MAX_TOPUP),
        "cards": cards, "default_pm": default_pm, "auto_reload": auto_reload,
        "ledger": [{"kind": r["kind"], "amount": float(r["amount_usd"]), "memo": r["memo"], "created_at": r["created_at"]}
                   for r in repo.credit_rows(cur, ctx.uid)],
    }


def billing_receipt(ctx: Ctx):
    """Full Credits & Usage history as a downloadable CSV receipt."""
    import csv
    import io
    cur = ctx.cur
    user = repo.get_user(cur, ctx.uid) or {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Tau - Credits & Usage receipt"])
    w.writerow(["Account", user.get("email", "")])
    w.writerow(["Generated (UTC)", repo.now_utc().replace(microsecond=0).isoformat()])
    w.writerow(["Current balance (USD)", "%.4f" % repo.credit_balance(cur, ctx.uid)])
    w.writerow(["Total spent (USD)", "%.4f" % repo.credit_spent_total(cur, ctx.uid)])
    w.writerow([])
    w.writerow(["Date (UTC)", "Type", "Amount (USD)", "Memo"])
    for r in repo.credit_rows(cur, ctx.uid, 100000):  # full history, newest first
        w.writerow([r["created_at"], r["kind"], "%.4f" % float(r["amount_usd"]), r["memo"] or ""])
    fname = "tau-credits-%s.csv" % repo.now_utc().strftime("%Y%m%d")
    return ("download", fname, "text/csv; charset=utf-8", buf.getvalue())


def billing_setup_intent(ctx: Ctx):
    if not billing.configured():
        raise ApiError(503, "Payments aren't enabled yet.")
    try:
        return billing.create_setup_intent(_customer_id(ctx))
    except billing.StripeError as e:
        raise ApiError(502, str(e))


def billing_card_added(ctx: Ctx):
    pm = str(ctx.body.get("payment_method_id") or "")
    if not pm.startswith("pm_"):
        raise ApiError(400, "No card to save.")
    cust = repo.get_stripe_customer(ctx.cur, ctx.uid)
    cid = cust["stripe_customer_id"] if cust else _customer_id(ctx)
    try:
        billing.set_default_card(cid, pm)
    except billing.StripeError as e:
        raise ApiError(502, str(e))
    repo.set_default_pm(ctx.cur, ctx.uid, pm)
    return {"ok": True}


def billing_topup(ctx: Ctx):
    if not billing.configured():
        raise ApiError(503, "Payments aren't enabled yet.")
    amount = _num(ctx.body, "amount", float(billing.MIN_TOPUP), float(billing.MAX_TOPUP))
    cust = repo.get_stripe_customer(ctx.cur, ctx.uid)
    if not cust or not cust.get("default_pm_id"):
        raise ApiError(409, "Add a card first.")
    from decimal import Decimal as _D
    credits = _D(str(amount))
    idem = "topup-%s-%d" % (ctx.uid, int(repo.now_utc().timestamp()))
    try:
        pi = billing.charge(cust["stripe_customer_id"], cust["default_pm_id"],
                            billing.topup_charge_cents(credits), off_session=False, idem=idem,
                            metadata={"user_id": ctx.uid, "credits": str(credits), "purpose": "topup"})
    except billing.StripeError as e:
        raise ApiError(402, str(e))
    if pi["status"] != "succeeded":
        raise ApiError(402, "The card didn't complete the charge (status: %s)." % pi["status"])
    with repo.transaction(ctx.conn) as tx:
        repo.add_credit(tx, ctx.uid, "topup", credits, "Added $%s credits" % credits, stripe_ref=pi["id"])
    return {"ok": True, "balance": round(repo.credit_balance(ctx.cur, ctx.uid), 4)}


def billing_autoreload(ctx: Ctx):
    on = ctx.body.get("on") is True
    if on and not (repo.get_stripe_customer(ctx.cur, ctx.uid) or {}).get("default_pm_id"):
        raise ApiError(409, "Add a card before turning on auto-reload.")
    from decimal import Decimal as _D
    amount = threshold = None
    if ctx.body.get("amount") is not None:
        amount = _D(str(_num(ctx.body, "amount", float(billing.AUTORELOAD_AMOUNT), float(billing.MAX_TOPUP))))
    if ctx.body.get("threshold") is not None:
        threshold = _D(str(_num(ctx.body, "threshold", float(billing.AUTORELOAD_THRESHOLD), float(billing.MAX_TOPUP))))
    repo.set_auto_reload(ctx.cur, ctx.uid, on, amount=amount, threshold=threshold)
    return {"ok": True}


def billing_remove_card(ctx: Ctx):
    pm = str(ctx.body.get("payment_method_id") or "")
    cust = repo.get_stripe_customer(ctx.cur, ctx.uid)
    if not cust:
        raise ApiError(404, "No card on file.")
    try:
        cards = billing.list_cards(cust["stripe_customer_id"])
    except billing.StripeError as e:
        raise ApiError(502, str(e))
    if len(cards) <= 1:
        raise ApiError(409, "You can't remove your only card. Add another first.")
    if not any(c["id"] == pm for c in cards):
        raise ApiError(404, "That card isn't on file.")
    try:
        billing.detach_card(pm)
    except billing.StripeError as e:
        raise ApiError(502, str(e))
    if cust.get("default_pm_id") == pm:
        other = next(c["id"] for c in cards if c["id"] != pm)
        billing.set_default_card(cust["stripe_customer_id"], other)
        repo.set_default_pm(ctx.cur, ctx.uid, other)
    return {"ok": True}


# -- admin -----------------------------------------------------------------------


def _require_admin(ctx: Ctx) -> None:
    if (ctx.user["email"] or "").lower() != ADMIN_EMAIL.lower():
        raise ApiError(403, "Admins only.")


def admin_overview(ctx: Ctx):
    _require_admin(ctx)
    cur = ctx.cur
    cur.execute("""SELECT u.id, u.email, u.name, u.created_at,
                     COALESCE((SELECT SUM(amount_usd) FROM app_credit_ledger l WHERE l.user_id=u.id),0) AS balance
                   FROM app_users u ORDER BY u.id DESC LIMIT 100""")
    users = [{"id": r["id"], "email": r["email"], "name": r["name"], "created_at": r["created_at"],
              "balance": round(float(r["balance"]), 2)} for r in cur.fetchall()]
    # Waitlist and users are mutually exclusive: hide anyone who already has an account
    # (case/space-insensitive — Google emails and typed waitlist emails can differ in case).
    cur.execute("""SELECT w.email, w.note, w.status, w.created_at FROM app_waitlist w
                   WHERE NOT EXISTS (SELECT 1 FROM app_users u
                                     WHERE LOWER(TRIM(u.email))=LOWER(TRIM(w.email)))
                   ORDER BY (w.status='approved'), w.id DESC LIMIT 200""")
    waitlist = cur.fetchall()
    return {"users": users, "waitlist": waitlist}


def admin_grant(ctx: Ctx):
    _require_admin(ctx)
    email = str(ctx.body.get("email") or "").strip().lower()
    amount = _num(ctx.body, "amount", -100000, 100000)
    target = repo.user_by_email(ctx.cur, email)
    if not target:
        raise ApiError(404, "No Tau user with that email (they must sign in first).")
    from decimal import Decimal as _D
    repo.add_credit(ctx.cur, target["id"], "admin_grant", _D(str(amount)),
                    "Admin grant by %s" % ctx.user["email"])
    return {"ok": True, "email": email, "balance": round(repo.credit_balance(ctx.cur, target["id"]), 2)}


def admin_waitlist(ctx: Ctx):
    """Approve a waitlist request (so that email can sign in) or remove it."""
    _require_admin(ctx)
    email = str(ctx.body.get("email") or "").strip()
    action = ctx.body.get("action")
    if not email or action not in ("approve", "remove"):
        raise ApiError(400, "Pick an email and action (approve or remove).")
    ok = repo.set_waitlist_status(ctx.cur, email, "approved") if action == "approve" \
        else repo.remove_waitlist(ctx.cur, email)
    if not ok:
        raise ApiError(404, "That email isn't on the waitlist.")
    return {"ok": True, "email": email, "action": action}


def admin_kill_switch(ctx: Ctx):
    """The DB-backed execution kill switch. While on, every engine process refuses new BUYS
    within ~5s (no restart); SELLS always run. Admin-only."""
    _require_admin(ctx)
    from app.execution import kill_switch as ks
    st = ks.read_state(ctx.cur)
    return {"on": bool(st.get("on")), "reason": st.get("reason") or "", "by": st.get("by") or "",
            "updated_at": st.get("updated_at_utc"), "env_on": os.getenv("APP_KILL_SWITCH") == "1"}


def admin_kill_switch_set(ctx: Ctx):
    """POST {on: bool, reason}: flip the DB-backed execution kill switch, then return its state."""
    _require_admin(ctx)
    from app.execution import kill_switch as ks
    on = ctx.body.get("on")
    if not isinstance(on, bool):
        raise ApiError(400, "Send on: true or false.")
    ks.write_state(ctx.cur, on, str(ctx.body.get("reason") or "")[:200], ctx.user["email"])
    return admin_kill_switch(ctx)


def exec_tca(ctx: Ctx):
    """Transaction cost analysis of real orders over a trailing window (admin-only). Read-only."""
    _require_admin(ctx)
    from app import tca
    try:
        days = float(ctx.query.get("days", "7"))
    except (TypeError, ValueError):
        days = 7.0
    return tca.report(ctx.cur, days=max(0.1, min(days, 90.0)))


def exec_latency(ctx: Ctx):
    """Execution P2: order-path lag + error observability over a trailing window (admin-only —
    operational money-path telemetry). p50/p95/p99 round-trip + total latency, encode/sign cost,
    error/fill rates by outcome, and feed/mark staleness. Read-only."""
    _require_admin(ctx)
    try:
        window = int(ctx.query.get("window", "3600"))
    except (TypeError, ValueError):
        window = 3600
    window = max(60, min(window, 7 * 24 * 3600))
    mode = ctx.query.get("mode")
    mode = mode if mode in ("live", "demo") else None
    return repo.order_latency_stats(ctx.cur, window_seconds=window, mode=mode)


def admin_system(ctx: Ctx):
    """Live telemetry for the system map: per-node freshness + volume, so the
    graph shows what the running codebase is actually doing right now. Open to every
    signed-in user (it's the product's 'show the homework' proof the pipeline is real);
    fleet-wide specifics stay admin-only below."""
    is_admin = (ctx.user["email"] or "").lower() == ADMIN_EMAIL.lower()
    cur = ctx.cur

    # Heartbeats: each collector/engine writes collector_state on every tick.
    cur.execute("SELECT state_key, updated_at_utc FROM collector_state")
    now = repo.now_utc().replace(tzinfo=None)
    age = {}
    for r in cur.fetchall():
        if r["updated_at_utc"]:
            age[r["state_key"]] = max(0, int((now - r["updated_at_utc"]).total_seconds()))

    def approx_rows(table):
        cur.execute("SELECT table_rows AS n FROM information_schema.tables "
                    "WHERE table_schema=DATABASE() AND table_name=%s", (table,))
        r = cur.fetchone()
        return int(r["n"]) if r and r["n"] is not None else 0

    def scalar(q, *a):
        cur.execute(q, a); r = cur.fetchone()
        return (list(r.values())[0] if r else 0) or 0

    cur.execute("SELECT status, COUNT(*) c FROM app_agent_runs GROUP BY status")
    runs = {r["status"]: r["c"] for r in cur.fetchall()}

    def safe_scalar(q, *a):
        try:
            cur.execute(q, a); r = cur.fetchone()
            return (list(r.values())[0] if r else 0) or 0
        except Exception:
            return None

    nodes = {
        "kalshi":    {"kind": "ext", "series": safe_scalar("SELECT COUNT(DISTINCT series_ticker) c FROM hist_markets"),
                      "markets": safe_scalar("SELECT COUNT(*) c FROM hist_markets")},
        "coinbase":  {"kind": "ext"},
        "bedrock":   {"kind": "ext"},
        "stripe":    {"kind": "ext"},
        "forward":   {"age": age.get("forward_collector_last_snapshot"), "rows": approx_rows("forward_quotes"), "unit": "quote rows"},
        "cb_coll":   {"age": age.get("coinbase_collector_last_snapshot"), "rows": approx_rows("spot_candles_1m"), "unit": "1m candles"},
        "features":  {"age": age.get("model_features_1m_last_snapshot"), "rows": approx_rows("model_features_1m"), "unit": "feature rows"},
        "db":        {"rows": approx_rows("forward_quotes") + approx_rows("market_candles"), "size_mb": scalar("SELECT ROUND(SUM(data_length+index_length)/1048576) m FROM information_schema.tables WHERE table_schema=DATABASE()"),
                      **({"top_tables": repo.largest_tables(cur)} if is_admin else {})},
        "web":       {"up": True, **({"users": scalar("SELECT COUNT(*) c FROM app_users")} if is_admin else {})},
        "agents":    {"running": runs.get("running", 0), "queued": runs.get("queued", 0), "done": runs.get("succeeded", 0) + runs.get("failed", 0)},
        "backtest":  {"strategies": scalar("SELECT COUNT(*) c FROM app_strategies")},
        "sim_engine":  {"age": age.get("sim_trading_last_snapshot"), "trades": safe_scalar("SELECT COUNT(*) c FROM sim_trades")},
        "live_engine": {"age": age.get("live_trading_last_snapshot"), "deployments": scalar("SELECT COUNT(*) c FROM app_deployments WHERE status='running'")},
    }
    # Recent activity feed: fleet-wide for the operator, but a normal user only ever
    # sees their OWN agent events — never another user's private strategy names.
    if is_admin:
        cur.execute("""SELECT e.kind, e.message, e.created_at FROM app_agent_events e
                       ORDER BY e.id DESC LIMIT 14""")
    else:
        cur.execute("""SELECT e.kind, e.message, e.created_at
                       FROM app_agent_events e JOIN app_agent_runs r ON r.id=e.run_id
                       WHERE r.user_id=%s ORDER BY e.id DESC LIMIT 14""", (ctx.uid,))
    events = [{"kind": r["kind"], "message": (r["message"] or "")[:120], "created_at": r["created_at"]} for r in cur.fetchall()]
    return {"now": now.isoformat() + "Z", "nodes": nodes, "events": events}


def system_code(ctx: Ctx):
    """System-map drill-down: component -> module -> function source + call graph.

    Read-only static analysis of this repo's own source (app/ + data_pipeline/),
    the 'show the homework' proof the pipeline is real - so, like admin_system,
    it's open to any signed-in user. The module path is whitelisted in code_map
    so a request can never read outside the repo."""
    from app import code_map
    try:
        module = (ctx.query.get("module") or "").strip()
        func = (ctx.query.get("func") or "").strip()
        if func:
            return code_map.function_detail(module, func)
        if module:
            return code_map.module_symbols(module)
        return code_map.component_modules((ctx.query.get("component") or "").strip())
    except code_map.CodeMapError as e:
        raise ApiError(404, str(e))


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


def research_context(ctx: Ctx):
    """Live book context for the researchable markets, for the Research cockpit's picker."""
    data = _explore_feed()
    return {"at": data.get("at"), "markets": _research_context(data.get("markets") or [])}


def research_scoreboard(ctx: Ctx):
    """How the user's research loop is doing: funnel, spend, efficiency and why ideas die, in total,
    per market family and per day (app/rsi.py). ?days= (1-60, default 7)."""
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
    from app import rsi, rsi_playbook
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
    from app import tournament
    try:
        board["tournament"] = tournament.standings(cur, uid)
    except Exception:  # noqa: BLE001 - informational; the table may not exist before the first schema run
        board["tournament"] = None
    try:
        board["early_exits"] = repo.early_exit_scorecard(cur, uid)
    except Exception:  # noqa: BLE001 - informational
        board["early_exits"] = None
    from app import rsi_repair
    board["data_requests"] = rsi_repair.summary(cur, uid)
    return board


def _cnum(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def explore_market(ctx: Ctx):
    """One market's dataset for the Explore detail view: its metadata plus the price
    history Kalshi has for it (the same candlesticks the backtester trains on). Fetched
    on demand from Kalshi's public API — no lake query, no new storage."""
    from data_pipeline.common import api_get, parse_iso_to_dt
    import time as _time
    ticker = (ctx.query.get("ticker") or "").strip()
    if not ticker:
        raise ApiError(400, "No market given.")
    series = ticker.split("-", 1)[0]
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
        raise ApiError(502, "Couldn't load this market's history: %s" % e)
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
        ("GET", "/api/research/scoreboard", research_scoreboard, True),
        ("GET", "/api/models", models, True),
        ("GET", "/api/runs", list_runs, True),
        ("POST", "/api/runs", create_run, True),
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
        ("POST", "/api/billing/setup-intent", billing_setup_intent, True),
        ("POST", "/api/billing/card-added", billing_card_added, True),
        ("POST", "/api/billing/topup", billing_topup, True),
        ("POST", "/api/billing/auto-reload", billing_autoreload, True),
        ("POST", "/api/billing/remove-card", billing_remove_card, True),
        ("GET", "/api/admin", admin_overview, True),
        ("GET", "/api/admin/system", admin_system, True),
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


class Handler(BaseHTTPRequestHandler):
    server_version = "Tau"
    sys_version = ""
    # Keep-alive: CloudFront reuses its origin connection instead of paying a fresh TCP handshake
    # (one more edge-to-Virginia round trip) on every API call. Every response sets Content-Length.
    protocol_version = "HTTP/1.1"
    timeout = 75  # idle keep-alive sockets close after this; longer than CloudFront's origin keep-alive

    def log_request(self, code="-", size="-"):
        self._status = code if isinstance(code, int) else int(getattr(code, "value", 0) or 0)

    def log_message(self, fmt, *args):  # errors from the stdlib (bad request line, 501); no query strings
        # Also reached on an idle keep-alive timeout, before any request line set command/path.
        print("[app] %s %s %s" % (getattr(self, "command", None) or "-", urlparse(getattr(self, "path", None) or "").path,
                                  (fmt % args)[:120]), flush=True)

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
            print("[app] %s %s %s %dms %s" % (method, path, self._status, ms,
                                              datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")), flush=True)

    def cookies(self) -> Dict[str, str]:
        out = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
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
              gz_key: Optional[Tuple[str, int, int]] = None) -> None:
        """Write a whole response, gzipped when the client accepts it and it's worth it (JSON, HTML,
        JS, CSS). CloudFront's cache is off for the app, so it never compresses for us."""
        req_headers = getattr(self, "headers", None)
        if webperf.wants_gzip(req_headers.get("Accept-Encoding") if req_headers else None, ctype, len(body)):
            body = webperf.gzip_bytes(body, gz_key)
            extra = list(extra or []) + [("Content-Encoding", "gzip"), ("Vary", "Accept-Encoding")]
        self._headers(status, ctype, len(body), extra)
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any, cookies: List[str]) -> None:
        body = json.dumps(payload, default=_json_default, separators=(",", ":")).encode("utf-8")
        extra = [("Cache-Control", "no-store")] + [("Set-Cookie", c) for c in cookies]
        self._send(status, "application/json; charset=utf-8", body, extra)

    def _send_static(self, path: str) -> None:
        if path == "/.well-known/apple-developer-merchantid-domain-association":
            f = STATIC_DIR / "apple-developer-merchantid-domain-association"
            if f.is_file():
                body = f.read_bytes()
                self._headers(200, "text/plain", len(body), [("Cache-Control", "public, max-age=86400")])
                self.wfile.write(body)
                return
        if SPA_ROUTES.match(path):
            versions = _static_versions()
            html = (STATIC_DIR / "index.html").read_text("utf-8")
            html = (html.replace("{{css_v}}", versions["app.css"])
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
            self._send(200, "text/html; charset=utf-8", body, [("Cache-Control", "no-cache")])
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
        body = f.read_bytes()
        st = f.stat()
        self._send(200, ctype + ("; charset=utf-8" if m.group(2) in ("css", "js", "svg") else ""), body,
                   [("Cache-Control", "public, max-age=31536000, immutable")], gz_key=(f.name, st.st_mtime_ns, st.st_size))

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
                return self._send_static(path)
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
                if length > MAX_BODY:
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
                self._headers(200, ctype, len(data), [("Cache-Control", "public, max-age=31536000, immutable")])
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
    print("Tau on http://%s:%d" % (HOST, PORT), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
