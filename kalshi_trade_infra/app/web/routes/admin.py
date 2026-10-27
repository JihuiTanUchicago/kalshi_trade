"""Admin routes: the overview, system and code pages, grants, the waitlist, the kill switch,
execution latency/TCA and client error reports. Moved verbatim from app.server, which re-imports
every name for its route table."""
from __future__ import annotations

import json
import os
import re
from typing import Dict

from app import repository as repo
from app.services import customer_text
from app.web import auth, client_errors
from app.web.http import ApiError, Ctx, _num
from app.web.routes.research import uncleared_passes_at
from app.web.settings import ADMIN_EMAIL
from app.web.views import _with_gate_lines


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
    # Open positions whose strategy was deleted: the engine no longer settles or flattens them.
    return {"users": users, "waitlist": waitlist, "orphaned_open": repo.orphaned_open_positions(cur),
            # Broken pages: browser error reports from the last 24h, grouped by message and page.
            "client_errors": repo.client_error_groups(cur)}


def report_client_error(ctx: Ctx):
    """POST /api/client-errors: a page hit an uncaught error, an unhandled rejection, or an API call or
    bug it shows as an error (boot.js sends these, fire-and-forget). Signed in or out: the signed-out
    pages break too. Rate-limited in memory per address and per session, with one global cap, before
    anything is written; every field is cleaned and bounded (client_errors.clean). Stores no user id
    or address, only whether the visitor was signed in. The body cap is BODY_LIMITS."""
    keys = ["ip:" + client_errors.client_ip(ctx.handler)]
    read = getattr(ctx.handler, "cookies", None)
    token = read().get(auth.SESSION_COOKIE) if callable(read) else None
    if token:
        keys.append("s:" + auth.hash_token(token)[:16])
    if not client_errors.LIMITER.allow(keys):
        raise ApiError(429, "Too many error reports. Try again later.")
    try:
        report = client_errors.clean(ctx.body)
    except ValueError as e:
        raise ApiError(400, str(e))
    repo.insert_client_error(ctx.cur, report, signed_in=ctx.user is not None)
    return {"ok": True}


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
    from app.trading import tca
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

    # The research, backtest and engine boxes count every user's for the operator only. A customer gets their
    # own, flagged `mine`: fleet-wide they read as theirs ("7 strategies tested" beside one session of their
    # own), and a small fleet's figures say what other users run. Each is one count through the user's own
    # index (idx_runs_user, idx_strat_user, idx_dep_user), the seeded example left out as their Research and
    # Strategies pages leave it out; a finished session of theirs is done however it ended.
    if is_admin:
        cur.execute("SELECT status, COUNT(*) c FROM app_agent_runs GROUP BY status")
        runs = {r["status"]: int(r["c"]) for r in cur.fetchall()}
        done = runs.get("succeeded", 0) + runs.get("failed", 0)
        cur.execute("SELECT mode, COUNT(*) c FROM app_deployments WHERE status='running' GROUP BY mode")
        running = {r["mode"]: int(r["c"]) for r in cur.fetchall()}
        strategies = scalar("SELECT COUNT(*) c FROM app_strategies")
        mine = {}
    else:
        cur.execute("SELECT status, COUNT(*) c FROM app_agent_runs WHERE user_id=%s AND kind='research'"
                    " AND (direction IS NULL OR direction<>%s) GROUP BY status", (ctx.uid, repo.DEMO_DIRECTION))
        runs = {r["status"]: int(r["c"]) for r in cur.fetchall()}
        done = sum(n for s, n in runs.items() if s not in ("running", "queued", "paused"))
        cur.execute("SELECT mode, COUNT(*) c FROM app_deployments WHERE user_id=%s AND status='running' GROUP BY mode",
                    (ctx.uid,))
        running = {r["mode"]: int(r["c"]) for r in cur.fetchall()}
        strategies = scalar("SELECT COUNT(*) c FROM app_strategies WHERE user_id=%s AND direction<>%s",
                            ctx.uid, repo.DEMO_DIRECTION)
        mine = {"mine": True}

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
        "agents":    {"running": runs.get("running", 0), "queued": runs.get("queued", 0), "done": done, **mine},
        "backtest":  {"strategies": strategies, **mine},
        # One process (app/trading/engine.py) runs every mode, so its heartbeat is both boxes' age. Running
        # deployments are counted per mode: "N live" once counted paper and demo ones too.
        "sim_engine":  {"age": age.get("recursive_engine_last_tick"), "paper": running.get("paper", 0), **mine},
        "live_engine": {"age": age.get("recursive_engine_last_tick"), "live": running.get("live", 0),
                        "demo": running.get("demo", 0), **mine},
    }
    # Recent activity feed: fleet-wide for the operator, but a normal user only ever
    # sees their OWN agent events — never another user's private strategy names.
    if is_admin:
        cur.execute("""SELECT e.run_id, r.user_id, e.kind, e.message, e.data_json, e.created_at
                       FROM app_agent_events e JOIN app_agent_runs r ON r.id=e.run_id
                       ORDER BY e.id DESC LIMIT 14""")
    else:
        cur.execute("""SELECT e.run_id, r.user_id, e.kind, e.message, e.data_json, e.created_at
                       FROM app_agent_events e JOIN app_agent_runs r ON r.id=e.run_id
                       WHERE r.user_id=%s ORDER BY e.id DESC LIMIT 14""", (ctx.uid,))
    rows = list(cur.fetchall())
    fell = _feed_uncleared(cur, rows)
    events = [_system_event(r, fell.get(r.get("run_id"))) for r in rows]
    return {"now": now.isoformat() + "Z", "nodes": nodes, "events": events}


# A line whose count holds a pass: the agent's progress line ("N tested so far, M passed", M > 0) or its done line.
_COUNTS_A_PASS = re.compile(r"tested so far, [1-9]\d* passed\.|^[1-9]\d* of \d+ hypotheses passed")


def _feed_uncleared(cur, rows) -> Dict:
    """{run id: when each of its passes a later check left uncleared was made}, read only for the sessions
    whose progress or done line in the feed counts a pass: those lines count them apart, as the session
    page's do (research.uncleared_passes_at)."""
    out: Dict = {}
    for r in rows:
        rid = r.get("run_id")
        if (rid is not None and rid not in out and r.get("user_id") is not None and r.get("kind") in ("step", "done")
                and _COUNTS_A_PASS.search(r.get("message") or "")):
            out[rid] = uncleared_passes_at(cur, r["user_id"], rid)
    return out


def _system_event(r: Dict, fell_at=None) -> Dict:
    """One row of the system page's activity feed, in the session page's words. A verdict gains `data`
    {note, title} when the run page would show a plain note in place of its ledger message
    (_with_gate_lines, judged on the whole message before it is cut to 120 characters); nothing else of
    the event's data is sent. A step or done line written in the ledger's terms reads as the session
    page's note (gate_explain.step_note): the agent's "N tested so far, M passed" counts passes a later
    check left uncleared (`fell_at`, when each was made), which the note counts apart. An error line
    (a provider's raw failure) and any model id or email go through customer_text, as on the session page."""
    msg = r.get("message") or ""
    kind = r.get("kind")
    ev = {"kind": kind, "message": msg, "created_at": r.get("created_at")}
    if kind in ("step", "done"):
        noted = _with_gate_lines([dict(ev, data={})], len(fell_at or []), fell_at)[0]
        ev["message"] = (noted.get("data") or {}).get("note") or msg
    ev["message"] = (customer_text.event_rows([ev])[0]["message"] or "")[:120]
    if kind != "verdict":
        return ev
    raw = r.get("data_json")
    try:
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return ev
    data = _with_gate_lines([{"kind": "verdict", "message": msg, "data": data}])[0]["data"]
    if data.get("note"):
        ev["data"] = {"note": data["note"], "title": data.get("title") or None}
    return ev


def system_code(ctx: Ctx):
    """System-map drill-down: component -> module -> function source + call graph.

    Read-only static analysis of this repo's own source (app/ + data_pipeline/),
    the 'show the homework' proof the pipeline is real - so, like admin_system,
    it's open to any signed-in user. The module path is whitelisted in code_map
    so a request can never read outside the repo."""
    from app.web import code_map
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
