"""Deployment routes: the Deploy board (list, roads to live, paper pace and record), creating a
deployment, pause/resume/stop and a strategy's live readiness. Moved verbatim from app.server,
which re-imports every name for its route table."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional

from app import repository as repo
from app.research import agent
from app.services import book_memo, page_poll, paper_checks
from app.trading import engine
from app.trading import spec as specmod
from app.trading.markets import MARKETS
from app.web.caches import _ROADS, _forget_own_change
from app.web.http import ApiError, Ctx, _int_param
from app.web.routes.strategies import _backtest_checks, _with_marks, _with_why
from app.web.settings import MAX_ACTIVE_DEPLOYMENTS
from app.web.views import _demo_health, _demo_key_back, _deployment_out, _paper_books, _realized_by_book


def _paper_strategy_ids(deps: List[Dict]) -> set:
    """The strategies with a paper deployment that isn't stopped (running, or paused with paper)."""
    return {d["strategy_id"] for d in deps if d["mode"] == "paper" and d["status"] != "stopped"}


def list_deployments(ctx: Ctx):
    # Display reads: the deployments' totals summed before their rows are joined, and curves only
    # for the deployments listed (not every stopped one's history). Same payload as before.
    memo = book_memo.BookMemo(ctx.cur, ctx.uid)  # position sums kept until the positions change
    deps = book_memo.deployments_for_display(memo)
    curves = book_memo.deployment_curves(memo, [d["id"] for d in deps])
    checks = _backtest_checks(ctx.cur, ctx.uid, {d["strategy_id"]: d for d in deps}, memo)
    roads = _deploy_roads(ctx.cur, ctx.uid, deps, memo)
    paper_sids = _paper_strategy_ids(deps)
    key_back = _demo_key_back(ctx.cur, ctx.uid, deps)
    books = _paper_books(deps)
    # The removed deployments it doesn't list, so its Realized can say what it leaves out (display only).
    removed = book_memo.removed_deployments(memo)
    # The board polls every 10s with its last answer's version (?v=): services.page_poll.
    return page_poll.answer({
        # Each row carries its own book's backtest comparison (same strategy, same mode), and a paper
        # row its strategy's paper record toward the live check (all its paper deployments, as the
        # strategy page counts it).
        "deployments": [{**_deployment_out(d, curves.get(d["id"], []), paper_sids=paper_sids, demo_key_back=key_back,
                                           paper_books=books),
                         "backtest_check": next((c for c in checks.get(d["strategy_id"], []) if c["mode"] == d["mode"]), None),
                         "road": roads.get(d["strategy_id"]) if d["mode"] == "paper" else None}
                        for d in deps],
        "demo_health": _demo_health(ctx.cur, ctx.uid, deps),
        # Each book's realized P&L: the listed deployments', the removed ones', and (paper, live) both,
        # which is the dashboard's all-time figure. One book at a time, never summed together.
        "realized_by_book": _realized_by_book(deps, removed),
        "open_positions": _with_why(_with_marks(repo.user_positions(ctx.cur, ctx.uid, "open")), deps),
        "recent_closed": _with_why(repo.user_positions(ctx.cur, ctx.uid, "closed", 20), deps),
        # The server's live switch, as /api/me says it: in the answer (and so its version), the 10s poll
        # carries a flip to an open board, which says a live deployment waits while it is closed.
        "live_trading_available": engine.LIVE_TRADING_ENABLED,
    }, ctx.query.get("v"))


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
    # With the board's kept position sums, their version is in the key: a trade that closed inside the
    # 30s showed "Realized +$5.63 · 1 trade" beside "Toward live: 0/30 trades" on the same row.
    key = (uid, tuple(sids), tuple(sorted((int(d["id"]), d["status"]) for d in deps if d["mode"] == "paper")),
           memo.version() if memo is not None else None)
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
