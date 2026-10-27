"""Research routes: the research list and session page, starting, digging deeper on, cancelling,
pausing and resuming a session, the model picker, the market context, the cost estimate and the
scoreboard. Moved verbatim from app.server, which re-imports every name for its route table."""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from app import repository as repo
from app.adapters.llm import models_catalog as catalog
from app.adapters.stripe import billing
from app.research import agent, dreaming
from app.services import customer_text, research_list, run_stop
from app.services import markets as market_service
from app.trading import spec as specmod
from app.trading.markets import MARKETS
from app.web.caches import _shared, _shared_kept
from app.web.http import ApiError, Ctx, _int_param
from app.web.routes.explore import _efloat, _explore_feed, _feed_mid, _ticker_close_at
from app.web.routes.strategies import _owned_strategy, _strategy_card, warm_dev_curves
from app.web.settings import MAX_ACTIVE_RESEARCH, MAX_RESEARCH_PER_DAY
from app.web.views import _require_billing_ready, _run_wait, _silent_before, _with_gate_lines, credit_usd


def _researchable_markets(cur) -> List[Dict]:
    """The research picker's markets (app.services.markets), with the shared series cache."""
    ready = _shared("series_with_candles", 120, lambda c: repo.series_with_candles(c), cur)
    return market_service.researchable_markets(cur, ready)


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
    _number_sessions(ctx.cur, ctx.uid, runs)
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


def _number_sessions(cur, uid: int, runs: List[Dict]) -> None:
    """Stamp each of the user's own sessions with `seq`, its number among their sessions (1 = their
    first), so the list says "Session 3" instead of the global run id ("Session 8" on a first session).
    The seeded example gets none. `runs` is the newest first; a full page is counted once, a short one
    already holds every session."""
    own = [r for r in runs if not r.get("example")]
    total = repo.count_own_research(cur, uid) if len(runs) >= repo.RUNS_LISTED else len(own)
    for k, r in enumerate(own):
        r["seq"] = total - k


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
    mine = [s for s in strategies if s["run_id"] == run["id"]]
    warm_dev_curves(mine)
    auto = _autopilot_puts_on_paper(ctx.cur, ctx.user, mine)
    return {
        "run": run,
        "events": customer_text.event_rows(_with_gate_lines(repo.run_events(ctx.cur, run["id"], after))),
        "strategies": [{**_strategy_card(s), **({"autopilot_next": True} if s["id"] in auto else {})} for s in mine],
        "rsi": _rsi_block(pol, dream),
    }


def _autopilot_puts_on_paper(cur, user: Optional[Dict], strategies: List[Dict]) -> set:
    """The session's passed strategies the autopilot puts on paper itself at its next check-in, by the
    tests agent.auto_paper_candidates applies: autopilot on, room under its cap, never on paper before,
    a deployable market inside the focus, not code, and a gatekeeper deployment candidate. Display
    only: the page said "Open it to deploy it on paper" while the autopilot was about to, and a copy
    deployed by hand as well doubles the positions."""
    if not (user or {}).get("autopilot"):
        return set()
    waiting = [s for s in strategies if s["status"] == "passed" and not s.get("active_deps")
               and s.get("direction") != repo.DEMO_DIRECTION]
    if not waiting:
        return set()
    deps = repo.list_deployments(cur, user["id"], include_stopped=True)
    if sum(1 for d in deps if d["status"] != "stopped") >= agent.AUTO_PAPER_MAX_ACTIVE:
        return set()
    tried = {d["strategy_id"] for d in deps if d["mode"] == "paper" or d["status"] != "stopped"}
    focus = agent.focus_tokens(user)
    out = set()
    for s in waiting:
        mkt = MARKETS.get(s["market"])
        if (s["id"] in tried or mkt is None or not mkt.deployable or not agent.in_focus(s["market"], focus)
                or specmod.is_code_spec(s["spec"])):
            continue
        if agent._is_deployment_candidate(cur, s["id"]):
            out.add(s["id"])
    return out


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
        if rows and mk.close_hour_et is not None:
            # The 5pm Bitcoin ladder shares KXBTCD with the hourly contracts research never trades:
            # its row's price and volume come from the 5pm contracts alone.
            rows = [r for r in rows if (at := _ticker_close_at(r.get("t"))) and mk.is_target_event(at)]
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
            "yours_by_model": _own_session_costs_by_model(ctx.cur, ctx.uid),
            "sessions": len(own), "typical": _typical_session_costs(ctx.cur),
            "per_hour": _forever_hourly(ctx.cur, ctx.uid)}


def _own_session_costs_by_model(cur, uid: int) -> Dict[str, float]:
    """{model key: the median of the user's newest 10 finished sessions on that model}, for a model
    with SESSION_COST_MIN_OWN of them. The form's hint follows the model picked: "yours" pooled every
    model, so a user whose sessions ran on the default read that figure beside the cheapest model too."""
    by_model: Dict[str, List[float]] = {}
    for model, cost in repo.finished_session_costs_by_model(cur, uid, 50):
        key = catalog.resolve(model).key  # a NULL model ran on the catalog default
        if len(by_model.setdefault(key, [])) < 10:
            by_model[key].append(cost)
    return {k: credit_usd(_median(v)) for k, v in by_model.items() if len(v) >= SESSION_COST_MIN_OWN}


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
    # The same, per model ("yours_by_model"), so the hint follows the model picked.
    pooled: Dict[str, List[float]] = {}
    for model, spent, h in mine:
        p = pooled.setdefault(catalog.resolve(model).key, [0.0, 0.0])
        p[0] += spent
        p[1] += h
    yours_by_model = {k: round(s / h, 2) for k, (s, h) in pooled.items() if h >= FOREVER_RATE_MIN_HOURS}
    at, typical = _TYPICAL_FOREVER_RATE
    if time.time() - at >= SESSION_COST_TTL:
        by_model: Dict[str, List[float]] = {}
        for model, spent, h in repo.forever_session_rates(cur, since):
            by_model.setdefault(catalog.resolve(model).key, []).append(spent / h)
        typical = {k: round(_median(v), 2) for k, v in by_model.items() if len(v) >= SESSION_COST_MIN_TYPICAL}
        _TYPICAL_FOREVER_RATE[:] = [time.time(), typical]
    return {"yours": yours, "yours_by_model": yours_by_model, "typical": typical}


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
    return _shared(_board_key(uid, days), SCOREBOARD_TTL_S,
                   lambda cur: _research_scoreboard(cur, uid, days), ctx.cur)


SCOREBOARD_TTL_S = 60.0


def _board_key(uid: int, days: int) -> str:
    return "rsi_board:%s:%s" % (uid, days)


def scoreboard_kept(uid: int, days: int) -> bool:
    """Whether research_scoreboard answers (uid, days) from memory now, without working the board out."""
    return _shared_kept(_board_key(uid, days))


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
