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
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from app import agent, auth, backtest, billing, engine, kalshi_account, notify
from app import repository as repo
from app import spec as specmod
from app.markets import MARKETS
from data_pipeline.common import get_db_conn

PORT = int(os.getenv("APP_PORT", "8090"))
HOST = os.getenv("APP_HOST", "127.0.0.1")
DEV_LOGIN = os.getenv("APP_DEV_LOGIN") == "1"
SECURE_COOKIES = os.getenv("APP_INSECURE_COOKIES") != "1"
STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY = 8 * 1024 * 1024  # allows a base64 image in a community post

MAX_ACTIVE_RESEARCH = 2
MAX_RESEARCH_PER_DAY = 12
MAX_CHAT_PER_HOUR = 40
MAX_ACTIVE_DEPLOYMENTS = 10
MAX_PAPER_BALANCE = 1_000_000.0
MAX_WAITLIST_PER_MINUTE = 10
ADMIN_EMAIL = os.getenv("TAU_ADMIN_EMAIL", "tjhprivate0416@gmail.com")
SPA_ROUTES = re.compile(r"^/(?:|dashboard|research(?:/\d+)?|strategies(?:/\d+)?|deploy|community|billing|admin|funds|signin)$")

CSP = (
    "default-src 'self'; script-src 'self' https://js.stripe.com https://pay.google.com; style-src 'self' https://fonts.googleapis.com; style-src-attr 'unsafe-inline'; "
    "font-src https://fonts.gstatic.com; img-src 'self' data: https://*.googleusercontent.com https://*.stripe.com; "
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
    user = repo.upsert_google_user(ctx.cur, ident["sub"], ident["email"], ident["name"], ident["picture"])
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


# -- read routes ---------------------------------------------------------------


def me(ctx: Ctx):
    return {
        "user": {
            "id": ctx.user["id"], "email": ctx.user["email"], "name": ctx.user["name"],
            "picture": ctx.user["picture_url"], "autopilot": bool(ctx.user["autopilot"]),
        },
        "kalshi_connected": repo.get_kalshi_key(ctx.cur, ctx.uid) is not None,
        "live_trading_available": engine.LIVE_TRADING_ENABLED,
        "is_admin": (ctx.user["email"] or "").lower() == ADMIN_EMAIL.lower(),
        "billing_enabled": billing.configured(),
        "needs_card": _needs_card(ctx),
        "free_bonus": float(billing.FREE_BONUS),
        "credit_balance": round(repo.credit_balance(ctx.cur, ctx.uid), 4),
        "markets": [{"key": m.key, "label": m.label} for m in MARKETS.values()],
        "directions": [{"key": k, **v} for k, v in agent.DIRECTIONS.items()],
    }


def _start_of_day_utc() -> datetime:
    return repo.now_utc().replace(hour=0, minute=0, second=0)


def dashboard(ctx: Ctx):
    cur = ctx.cur
    balance = repo.paper_balance(cur, ctx.uid)
    deposited = repo.paper_deposits(cur, ctx.uid)
    open_pos = repo.user_positions(cur, ctx.uid, "open")
    at_cost = sum(float(p["qty"]) * float(p["entry_price"]) for p in open_pos if p["mode"] == "paper")
    equity = balance + at_cost
    deps = repo.list_deployments(cur, ctx.uid)
    curves = repo.deployment_curves(cur, ctx.uid)
    return {
        "paper": {
            "cash": round(balance, 2),
            "open_at_cost": round(at_cost, 2),
            "equity": round(equity, 2),
            "deposited": round(deposited, 2),
            "total_pnl": round(equity - deposited, 2),
            "roi": round((equity - deposited) / deposited, 4) if deposited > 0 else None,
            "today_pnl": round(repo.realized_pnl(cur, ctx.uid, "paper", _start_of_day_utc()), 2),
            "daily": repo.daily_pnl(cur, ctx.uid, "paper"),
        },
        "live": {
            "realized_pnl": round(repo.realized_pnl(cur, ctx.uid, "live"), 2),
            "today_pnl": round(repo.realized_pnl(cur, ctx.uid, "live", _start_of_day_utc()), 2),
        },
        "open_positions": open_pos,
        "recent_closed": repo.user_positions(cur, ctx.uid, "closed", 12),
        "deployments": [_deployment_out(d, curves.get(d["id"], [])) for d in deps],
        "agents": repo.active_run_counts(cur, ctx.uid),
        "freshness": _freshness(cur),
    }


def _freshness(cur) -> Dict:
    raw = repo.history_freshness(cur)
    now = int(datetime.now(timezone.utc).timestamp())
    return {k: (now - int(v) if v else None) for k, v in raw.items()}


def _deployment_out(d: Dict, curve: List) -> Dict:
    res = d.get("result") or {}
    return {
        "id": d["id"], "strategy_id": d["strategy_id"], "title": d["title"], "direction": d["direction"],
        "market": d["market"], "mode": d["mode"], "status": d["status"], "status_reason": d["status_reason"],
        "realized_pnl": round(float(d["realized_pnl"]), 2), "closed_trades": d["closed_trades"], "wins": d["wins"],
        "open_positions": d["open_positions"], "created_at": d["created_at"], "curve": curve,
        "stake": d["spec"]["sizing"]["stake"], "max_positions": d["spec"]["sizing"]["max_positions"],
        "backtest": {"out_of_sample": res.get("out_of_sample"), "capital": res.get("capital")},
    }


def list_runs(ctx: Ctx):
    return {"runs": repo.list_runs(ctx.cur, ctx.uid), "counts": repo.active_run_counts(ctx.cur, ctx.uid)}


def get_run(ctx: Ctx):
    run = repo.get_run(ctx.cur, ctx.uid, _int_param(ctx))
    if run is None or run["kind"] != "research":
        raise ApiError(404, "No such research run.")
    after = int(ctx.query.get("after") or 0)
    strategies = repo.list_strategies(ctx.cur, ctx.uid) if run["status"] == "succeeded" else []
    return {
        "run": run,
        "events": repo.run_events(ctx.cur, run["id"], after),
        "strategies": [_strategy_card(s) for s in strategies if s["run_id"] == run["id"]],
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
    market = ctx.body.get("market")
    idea = str(ctx.body.get("prompt") or "").strip()[:1000]
    # Optional angle tag; the idea itself is what drives the research now.
    direction = ctx.body.get("direction") or None
    if market not in MARKETS:
        raise ApiError(400, "Pick a market.")
    if not idea or len(idea) < 8:
        raise ApiError(400, "Describe your idea in a sentence or two first.")
    if direction is not None and direction not in agent.DIRECTIONS:
        direction = None
    cur = ctx.cur
    _require_billing_ready(ctx, "researching")
    if repo.count_runs(cur, ctx.uid, "research", active_only=True) >= MAX_ACTIVE_RESEARCH:
        raise ApiError(429, "You already have %d agents researching. Wait for one to finish." % MAX_ACTIVE_RESEARCH)
    if repo.count_runs(cur, ctx.uid, "research", since=repo.now_utc() - timedelta(days=1)) >= MAX_RESEARCH_PER_DAY:
        raise ApiError(429, "Daily research limit reached (%d). It resets over the next 24 hours." % MAX_RESEARCH_PER_DAY)
    run_id = repo.create_run(cur, ctx.uid, "research", market, direction, idea)
    return {"id": run_id}


def cancel_run(ctx: Ctx):
    if not repo.cancel_run(ctx.cur, ctx.uid, _int_param(ctx)):
        raise ApiError(409, "That run has already finished.")
    return {"ok": True}


def _strategy_card(s: Dict) -> Dict:
    res = s.get("result") or {}
    return {
        "id": s["id"], "run_id": s["run_id"], "parent_id": s["parent_id"], "market": s["market"],
        "direction": s["direction"], "title": s["title"], "thesis": s["thesis"], "status": s["status"],
        "created_at": s["created_at"], "hypotheses_tried": s.get("hypotheses_tried"),
        "in_sample": res.get("in_sample"), "out_of_sample": res.get("out_of_sample"),
        "equity": res.get("equity"), "capital": res.get("capital"),
        "stake": s["spec"]["sizing"]["stake"], "side": s["spec"]["side"],
    }


def list_strategies(ctx: Ctx):
    q = ctx.query
    rows = repo.list_strategies(ctx.cur, ctx.uid, q.get("direction") or None, q.get("status") or None, q.get("market") or None)
    return {"strategies": [_strategy_card(s) for s in rows]}


def _owned_strategy(ctx: Ctx) -> Dict:
    s = repo.get_strategy(ctx.cur, ctx.uid, _int_param(ctx))
    if s is None:
        raise ApiError(404, "No such strategy.")
    return s


def get_strategy(ctx: Ctx):
    s = _owned_strategy(ctx)
    out = _strategy_card(s)
    res = s.get("result") or {}
    out.update(
        spec=s["spec"], rules=specmod.describe(s["spec"]), gates=res.get("gates"), dataset=res.get("dataset"),
        recent_trades=res.get("recent_trades"),
        deployments=[_deployment_out(d, []) for d in repo.list_deployments(ctx.cur, ctx.uid) if d["strategy_id"] == s["id"]],
    )
    return out


def what_if(ctx: Ctx):
    s = _owned_strategy(ctx)
    if s["status"] == "rejected":
        raise ApiError(409, "This hypothesis was rejected in-sample; there is no full backtest to vary.")
    w = backtest.WhatIf(
        fee_multiplier=_num(ctx.body, "fee_multiplier", 0.0, 3.0, 1.0),
        slippage_cents=_num(ctx.body, "slippage_cents", 0.0, 5.0, 0.0),
        stake=_num(ctx.body, "stake", 1.0, 500.0, s["spec"]["sizing"]["stake"]),
    )
    try:
        res = backtest.evaluate(s["spec"], backtest.dataset(s["market"]), w)
    except Exception:
        raise ApiError(503, "Backtest data is not available right now.")
    return {k: res[k] for k in ("in_sample", "out_of_sample", "equity", "gates", "passed", "capital")}


# -- deployments ---------------------------------------------------------------


def list_deployments(ctx: Ctx):
    curves = repo.deployment_curves(ctx.cur, ctx.uid)
    return {
        "deployments": [_deployment_out(d, curves.get(d["id"], [])) for d in repo.list_deployments(ctx.cur, ctx.uid)],
        "open_positions": repo.user_positions(ctx.cur, ctx.uid, "open"),
        "recent_closed": repo.user_positions(ctx.cur, ctx.uid, "closed", 20),
    }


def create_deployment(ctx: Ctx):
    cur = ctx.cur
    s = repo.get_strategy(cur, ctx.uid, int(ctx.body.get("strategy_id") or 0))
    mode = ctx.body.get("mode")
    if s is None:
        raise ApiError(404, "No such strategy.")
    if s["status"] != "passed":
        raise ApiError(409, "Only strategies that passed every backtest gate can be deployed.")
    if mode not in ("paper", "live"):
        raise ApiError(400, "Choose paper or live.")
    if mode == "live":
        if not engine.LIVE_TRADING_ENABLED:
            raise ApiError(409, "Live trading isn't open yet. Deploy on paper for now.")
        if repo.get_kalshi_key(cur, ctx.uid) is None:
            raise ApiError(409, "Connect your Kalshi account on the Funds page first.")
        if s["spec"]["side"] != "yes":
            raise ApiError(409, "Live trading supports YES-only strategies in this version.")
        if ctx.body.get("confirm") != "LIVE":
            raise ApiError(400, "Type LIVE to confirm real-money trading.")
    if sum(1 for d in repo.list_deployments(cur, ctx.uid) if d["status"] != "stopped") >= MAX_ACTIVE_DEPLOYMENTS:
        raise ApiError(429, "You can run up to %d deployments at once." % MAX_ACTIVE_DEPLOYMENTS)
    dep_id = repo.create_deployment(cur, ctx.uid, s["id"], s["market"], mode)
    repo.add_chat(cur, ctx.uid, "system", "Deployed %s on %s." % (s["title"], "LIVE money" if mode == "live" else "paper"))
    return {"id": dep_id}


def deployment_action(ctx: Ctx):
    dep_id, action = _int_param(ctx), ctx.params[1]
    dep = repo.get_deployment(ctx.cur, ctx.uid, dep_id)
    if dep is None:
        raise ApiError(404, "No such deployment.")
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
        repo.set_autopilot(ctx.cur, ctx.uid, on)
        repo.add_chat(ctx.cur, ctx.uid, "system",
                      "Autopilot is %s." % ("ON: the agent may adjust and deploy paper strategies itself, and pause anything"
                                             if on else "OFF: the agent will only propose"))
    return {"ok": True}


# -- funds -------------------------------------------------------------------------


def funds(ctx: Ctx):
    cur = ctx.cur
    key = repo.get_kalshi_key(cur, ctx.uid)
    kalshi = {"connected": key is not None, "funding_url": kalshi_account.KALSHI_FUNDING_URL}
    if key is not None:
        kalshi["key_id"] = key["key_id"][:4] + "…" + key["key_id"][-4:]
        try:
            kalshi["balance"] = kalshi_account.balance(kalshi_account.credentials_from_row(ctx.uid, key))
        except Exception:
            kalshi["balance"] = None
    return {
        "paper": {"cash": round(repo.paper_balance(cur, ctx.uid), 2), "ledger": repo.ledger_rows(cur, ctx.uid)},
        "kalshi": kalshi,
    }


def paper_transfer(ctx: Ctx):
    kind = ctx.body.get("kind")
    if kind not in ("deposit", "withdraw"):
        raise ApiError(400, "Choose deposit or withdraw.")
    amount = round(_num(ctx.body, "amount", 1, 100000), 2)
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        bal = repo.paper_balance(tx, ctx.uid)
        if kind == "withdraw" and amount > bal:
            raise ApiError(409, "You only have $%.2f of paper cash free." % bal)
        if kind == "deposit" and bal + amount > MAX_PAPER_BALANCE:
            raise ApiError(409, "Paper accounts top out at $%s." % "{:,.0f}".format(MAX_PAPER_BALANCE))
        repo.add_ledger(tx, ctx.uid, "deposit" if kind == "deposit" else "withdrawal",
                        amount if kind == "deposit" else -amount,
                        "Paper %s" % ("deposit" if kind == "deposit" else "withdrawal"))
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
    repo.save_kalshi_key(ctx.cur, ctx.uid, key_id.strip(), blob)
    return {"ok": True, "balance": cash}


def delete_kalshi_key(ctx: Ctx):
    if any(d["mode"] == "live" and d["status"] == "running" for d in repo.list_deployments(ctx.cur, ctx.uid)):
        raise ApiError(409, "Pause or stop your live deployments before disconnecting Kalshi.")
    repo.delete_kalshi_key(ctx.cur, ctx.uid)
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
        "author": p.get("name") or "Trader", "picture": p.get("picture_url"),
        "mine": p.get("mine", False), "liked": p.get("liked", False),
        "image": ("/api/community/image/%d" % p["image_id"]) if p.get("image_id") else None,
        "edited": bool(p.get("edited_at")),
    }


def community(ctx: Ctx):
    before = int(ctx.query.get("before") or 0)
    return {"posts": [_post_out(p) for p in repo.list_posts(ctx.cur, ctx.uid, before)]}


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
    return {"id": pid}


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


def post_comments(ctx: Ctx):
    pid = _int_param(ctx)
    return {"comments": [{"body": c["body"], "author": c["name"] or "Trader", "picture": c["picture_url"], "created_at": c["created_at"]} for c in repo.list_comments(ctx.cur, pid)]}


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
    cid = billing.get_or_create_customer(ctx.user, cust["stripe_customer_id"] if cust else None)
    if not cust:
        repo.save_stripe_customer(ctx.cur, ctx.uid, cid)
    return cid


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
    return {
        "configured": billing.configured(),
        "publishable_key": billing.STRIPE_PUBLISHABLE_KEY,
        "balance": round(repo.credit_balance(cur, ctx.uid), 4),
        "spent": round(repo.credit_spent_total(cur, ctx.uid), 4),
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
    # Waitlist and users are mutually exclusive: hide anyone who already has an account.
    cur.execute("""SELECT w.email, w.note, w.created_at FROM app_waitlist w
                   WHERE NOT EXISTS (SELECT 1 FROM app_users u WHERE u.email=w.email)
                   ORDER BY w.id DESC LIMIT 100""")
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
        ("GET", "/api/dashboard", dashboard, True),
        ("GET", "/api/runs", list_runs, True),
        ("POST", "/api/runs", create_run, True),
        ("GET", r"/api/runs/(\d+)", get_run, True),
        ("POST", r"/api/runs/(\d+)/cancel", cancel_run, True),
        ("GET", "/api/strategies", list_strategies, True),
        ("GET", r"/api/strategies/(\d+)", get_strategy, True),
        ("POST", r"/api/strategies/(\d+)/whatif", what_if, True),
        ("GET", "/api/deployments", list_deployments, True),
        ("POST", "/api/deployments", create_deployment, True),
        ("POST", r"/api/deployments/(\d+)/(pause|resume|stop)", deployment_action, True),
        ("GET", "/api/chat", get_chat, True),
        ("POST", "/api/chat", post_chat, True),
        ("POST", r"/api/proposals/(\d+)/(approve|reject)", decide_proposal, True),
        ("POST", "/api/settings", settings, True),
        ("GET", "/api/community", community, True),
        ("POST", "/api/community", create_community_post, True),
        ("POST", r"/api/community/(\d+)/like", like_post, True),
        ("POST", r"/api/community/(\d+)/edit", edit_community_post, True),
        ("GET", r"/api/community/image/(\d+)", community_image, True),
        ("GET", r"/api/community/(\d+)/comments", post_comments, True),
        ("POST", r"/api/community/(\d+)/comments", create_comment, True),
        ("GET", "/api/billing", billing_state, True),
        ("POST", "/api/billing/setup-intent", billing_setup_intent, True),
        ("POST", "/api/billing/card-added", billing_card_added, True),
        ("POST", "/api/billing/topup", billing_topup, True),
        ("POST", "/api/billing/auto-reload", billing_autoreload, True),
        ("POST", "/api/billing/remove-card", billing_remove_card, True),
        ("GET", "/api/admin", admin_overview, True),
        ("POST", "/api/admin/grant", admin_grant, True),
        ("GET", "/api/funds", funds, True),
        ("POST", "/api/funds/paper", paper_transfer, True),
        ("POST", "/api/kalshi-key", save_kalshi_key, True),
        ("POST", "/api/kalshi-key/delete", delete_kalshi_key, True),
    ]
]


def _static_versions() -> Dict[str, str]:
    out = {}
    for name in ("app.css", "app.js", "icon.svg"):
        p = STATIC_DIR / name
        out[name] = hashlib.sha256(p.read_bytes()).hexdigest()[:10] if p.exists() else "0"
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "Tau"
    sys_version = ""

    def log_message(self, fmt, *args):  # one line per request, no query strings (they can carry OAuth codes)
        print("[app] %s %s %s" % (self.command, urlparse(self.path).path, args[1] if len(args) > 1 else ""), flush=True)

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
        if SECURE_COOKIES:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for k, v in extra or []:
            self.send_header(k, v)
        self.end_headers()

    def _send_json(self, status: int, payload: Any, cookies: List[str]) -> None:
        body = json.dumps(payload, default=_json_default, separators=(",", ":")).encode("utf-8")
        extra = [("Cache-Control", "no-store")] + [("Set-Cookie", c) for c in cookies]
        self._headers(status, "application/json; charset=utf-8", len(body), extra)
        self.wfile.write(body)

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
                    .replace("{{icon_v}}", versions["icon.svg"]))
            body = html.encode("utf-8")
            self._headers(200, "text/html; charset=utf-8", len(body), [("Cache-Control", "no-cache")])
            self.wfile.write(body)
            return
        m = re.match(r"^/static/([a-z0-9_.-]+\.(css|js|svg|png|ico))$", path)
        f = STATIC_DIR / m.group(1) if m else None
        if f is None or not f.is_file():
            body = b"Not found"
            self._headers(404, "text/plain", len(body))
            self.wfile.write(body)
            return
        ctype = {"css": "text/css", "js": "text/javascript", "svg": "image/svg+xml", "png": "image/png",
                 "ico": "image/x-icon"}[m.group(2)]
        body = f.read_bytes()
        self._headers(200, ctype + ("; charset=utf-8" if m.group(2) in ("css", "js", "svg") else ""), len(body),
                      [("Cache-Control", "public, max-age=31536000, immutable")])
        self.wfile.write(body)

    def _stripe_webhook(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
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
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            return self._send_json(200, {"ok": True}, [])
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
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            ctx = Ctx(conn, user, params, query, body, self)
            result = fn(ctx)
            if isinstance(result, tuple) and result and result[0] == "image":
                _, ctype, data = result
                self._headers(200, ctype, len(data), [("Cache-Control", "public, max-age=31536000, immutable")])
                self.wfile.write(data)
                return
            if isinstance(result, tuple) and result[0] == "redirect":
                self.send_response(302)
                self.send_header("Location", result[1])
                self.send_header("Cache-Control", "no-store")
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
    print("Tau on http://%s:%d" % (HOST, PORT), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
