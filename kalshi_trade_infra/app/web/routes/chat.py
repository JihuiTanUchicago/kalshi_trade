"""Chat and autopilot routes: the chat panel, agent proposals, autopilot settings, status, focus,
model, live and the kill switch, plus the story lines the status card tells. Moved verbatim from
app.server, which re-imports every name for its route table."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from app import repository as repo
from app import worker
from app.adapters.alpaca import alpaca_paper
from app.adapters.kalshi_perps import kalshi_perps_trading
from app.adapters.llm import models_catalog as catalog
from app.adapters.stripe import billing
from app.research import agent
from app.services import book_memo, customer_text
from app.trading import engine
from app.trading.markets import MARKETS
from app.web.caches import _forget_own_change
from app.web.http import ApiError, Ctx, _int_param
from app.web.routes.billing import (
    _credits_running_low,
    pace_days,
    pause_at,
    reload_days,
    reload_failed_now,
    runway_days,
)
from app.web.routes.brokers import _paper_call, _perps_live_call
from app.web.routes.strategies import _research_pass_verdicts
from app.web.settings import MAX_CHAT_PER_HOUR
from app.web.views import (
    demo_health_memo,
    credit_cents,
    credit_exact,
    credit_split,
    credit_usd,
    _needs_card,
    _pause_clause,
    _plain_pause_reason,
    _require_billing_ready,
    _run_wait,
    _start_of_day_utc,
)
from trading_core.domain.money import cents


def get_chat(ctx: Ctx):
    after = int(ctx.query.get("after") or 0)
    run = repo.active_agent_run(ctx.cur, ctx.uid)
    wait = _run_wait(run)
    rows = repo.chat_messages(ctx.cur, ctx.uid, after)
    # The engine's automatic pause names a deployment by its row number: the feed says it by name.
    paused_ids = customer_text.auto_paused_ids(rows)
    messages = customer_text.chat_rows(rows, repo.deployment_names(ctx.cur, ctx.uid, paused_ids) if paused_ids else None,
                                       agent.focus_words)  # an older "Market focus set to btc." says "Bitcoin"
    # agent_wait: the oldest chat/review in flight has waited or gone quiet past the reaper's limit,
    # so the panel's pulse says that instead of "working" for as long as it lasts.
    out = {"messages": messages, "agent_busy": run is not None, "agent_wait": wait if wait and wait["overdue"] else None}
    # What the newest answered message cost, for the line under the composer: read on the first load
    # and when a read brings an answer (or a failed one), not on every 3s poll in between.
    if billing.configured() and (not after or any(_answer_line(m) for m in messages)):
        cost = repo.last_chat_turn_cost(ctx.cur, ctx.uid)
        # Exact, as the ledger holds it: a turn under half a cent rounded to $0.00 read as free.
        out["turn_cost"] = credit_exact(cost) if cost is not None else None
    return out


def _answer_line(m: Dict) -> bool:
    """A chat line that ends a turn: the agent's reply, or the note that it failed to answer."""
    return m.get("role") == "agent" or (m.get("role") == "system"
                                        and customer_text.curly(str(m.get("content") or "")).startswith(NO_ANSWER))


NO_ANSWER = customer_text.NO_ANSWER


def post_chat(ctx: Ctx):
    content = str(ctx.body.get("content") or "").strip()
    if not content:
        raise ApiError(400, "Say something first.")
    if len(content) > 2000:
        raise ApiError(400, "Keep messages under 2,000 characters.")
    cur = ctx.cur
    _require_billing_ready(ctx, "chatting with the agent")
    if repo.count_runs(cur, ctx.uid, "chat", since=repo.now_utc() - timedelta(hours=1)) >= MAX_CHAT_PER_HOUR:
        raise ApiError(429, "That’s a lot of messages this hour. Give the agent a minute.")
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
        repo.add_chat(tx, ctx.uid, "system", _decision_line(tx, ctx.uid, p, decision == "approve"))
    _forget_own_change(ctx.uid)
    return {"ok": True}


# What each kind of proposal asks, and what is true once it is approved. "You approved the proposal."
# named neither the proposal nor the change, and with two pending there was no telling which one.
_ASKED = {"pause": "to pause %s", "resume": "to resume %s", "adjust": "to tune %s", "deploy": "to put %s on paper",
          "set_risk": "to change your risk limits", "set_exec": "to change your execution limits"}
_BOOK = {"paper": "on paper, with practice money", "demo": "on demo, Kalshi’s sandbox",
         "live": "LIVE, with real money"}
# A live deployment's decision while live trading is closed (engine.LIVE_TRADING_ENABLED off).
_LIVE_WAITING_AFTER = {
    "pause": "It is paused. Live trading isn’t open yet, so Tau can’t sell what it holds in your Kalshi account; "
             "that stays open until its market settles.",
    "resume": "It is set to run again on live, but live trading isn’t open yet, so it places no orders.",
    "adjust": "It now runs the tuned version on live, but live trading isn’t open yet, so it places no orders.",
}


def _decision_line(cur, uid: int, p: Dict, approved: bool) -> str:
    """The feed's line for the user's decision: the proposal it answers, and what changed (or that
    nothing did). Starts "You approved the proposal" / "You declined the proposal", which the panel
    heads as Your decision. Read after apply_proposal, so the deployment is as it now stands."""
    kind, verb = p.get("kind"), "approved" if approved else "declined"
    asked = _ASKED.get(kind)
    title, mode = "", None
    try:
        if p.get("deployment_id") and kind in ("pause", "resume", "adjust"):
            dep = repo.get_deployment(cur, uid, p["deployment_id"]) or {}
            title, mode = dep.get("title") or "", dep.get("mode")
        elif p.get("strategy_id") and kind == "deploy":
            title = (repo.get_strategy(cur, uid, p["strategy_id"]) or {}).get("title") or ""
    except Exception:  # noqa: BLE001 - a readout; the decision itself is already made
        title = ""
    if not asked or ("%s" in asked and not title):
        return "You %s the proposal." % verb
    head = "You %s the proposal %s." % (verb, asked % title if "%s" in asked else asked)
    if not approved:
        return head + " Nothing changed."
    book = _BOOK.get(mode or "", "")
    changes = customer_text.control_changes(p.get("payload") or {}) if kind in ("set_risk", "set_exec") else ""
    if mode == "live" and not engine.LIVE_TRADING_ENABLED and kind in _LIVE_WAITING_AFTER:
        # The server's live switch is closed: a live deployment places no orders and can't sell what it
        # holds, so the line says it waits, as Deploy does, never that it trades real money.
        return (head + " " + _LIVE_WAITING_AFTER[kind]).strip()
    after = {
        "pause": "It is paused, and anything it holds%s is sold." % (" in your Kalshi account" if mode == "live" else ""),
        "resume": "It is running again%s." % (", " + book if book else ""),
        "adjust": "It now trades the tuned version%s." % (", " + book if book else ""),
        "deploy": "It is on paper now. Nothing trades real money.",
        "set_risk": ("Now: %s. These apply to every strategy you run." % changes) if changes else "",
        "set_exec": ("Now: %s. These apply to every strategy you run." % changes) if changes else "",
    }[kind]
    return (head + " " + after).strip()


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


def _research_activity(cur, uid: int, pulse: Optional[Dict] = None, spent: Optional[float] = None,
                       exact: Optional[float] = None) -> Dict:
    """What research is doing for the autopilot float: the markets being researched now and the
    last 7 days' tested/passed counts, so a quiet panel reads as working, not stuck. Made from the
    panel's pulse (repo.autopilot_pulse) and its credit read (repo.credit_week); each is read here
    when the caller has none. `exact` is the week's research debit unrounded, when `spent` is the caller's
    rounded figure, so a week under half a cent says so (cost_7d_under_cent) instead of reading as nothing."""
    since = repo.now_utc() - timedelta(days=7)
    pulse = pulse if pulse is not None else repo.autopilot_pulse(cur, uid, since)
    # Researching now means a run queued for a worker or one that is beating, among the 50 newest. A
    # run the user paused isn't researching, and a running run silent past the reaper's limit (its
    # worker died) left "Right now it's researching Bitcoin" on every page for hours after it stopped.
    active = [r for r in pulse["research_live"] if r.get("status") == "queued"
              or (r.get("status") == "running" and not (_run_wait(r) or {}).get("overdue"))]
    # The week's totals come from one aggregate, not the 50 newest runs: a busy autopilot starts
    # 250+ runs a week, and the capped list told Todd it had tested 73 ideas when it was hundreds.
    # Passed counts strategies that cleared every gate: an old run's counter held 68 backtest-only.
    # Of those, the ones a later check left uncleared count apart (_week_not_cleared).
    not_cleared = _week_not_cleared(cur, uid, since, pulse["passed_7d"])
    if spent is None:
        spent = repo.credit_week(cur, uid, since)["research"]
    return {"active": [MARKETS[r["market"]].label if r.get("market") in MARKETS else (r.get("market") or "a market it’s still picking")
                       for r in active],
            "tested_7d": pulse["tested_7d"],
            "passed_7d": pulse["passed_7d"] - not_cleared,
            "not_cleared_7d": not_cleared,
            "runs_7d": pulse["runs_7d"],
            # What research actually debited this week (the credit ledger), not tokens re-priced:
            # re-pricing billed a screen-arm run's screen tokens at the developer model's rate.
            "cost_7d": credit_usd(spent),
            # Research that debited something but rounds to $0.00 reads "under $0.01", as Billing's week does
            # (spent_7d_under_cent): the panel left it out, as if research had cost nothing.
            "cost_7d_under_cent": credit_exact(spent if exact is None else exact) > 0 and not credit_usd(spent)}


WEEK_PASSES_TTL = 30.0  # seconds; the panel polls every 20s


_WEEK_PASSES: Dict[int, Tuple[float, int, int]] = {}  # {user id: (when, the week's stored passes, not cleared)}


def _week_not_cleared(cur, uid: int, since, stored: int) -> int:
    """How many of the week's passes (the pulse's passed_7d, strategies_passed_since's count) a later check
    left uncleared: the one-time holdout then failed, or the diversification check held it back, stamped
    Missed final test and Held back on its page, the session rows and the Strategies list. The panel read
    "3 passed" this week beside sessions reading "1 passed, 2 not cleared". Judged as the Research
    headline judges them (strategies._research_pass_verdicts: one read of the passes, one of their
    experiments' later rows), only when something passed, and kept per user for WEEK_PASSES_TTL while
    the stored count holds: the holdout and the diversification check are judged in the pass's own
    gating transaction, so a new verdict comes with a new pass. Display only."""
    if stored <= 0:
        return 0
    hit = _WEEK_PASSES.get(uid)
    if hit and hit[1] == stored and time.time() - hit[0] < WEEK_PASSES_TTL:
        return hit[2]
    _, got = _research_pass_verdicts(cur, uid, since)
    n = min(stored, len(got))
    _WEEK_PASSES[uid] = (time.time(), stored, n)
    return n


def _research_cents(credits: Dict) -> float:
    """The week's research credits (repo.credit_week) as Billing's week split shows them: "your research
    sessions" plus "autopilot research", each as Billing's split rounds it (credit_split: the parts add up
    to the week), so the autopilot card's research is the sum of the two figures Billing shows. Rounded
    once, $40.936666 + $59.066899 read $100.00 on the card beside Billing's $40.94 and $59.07. The seeded
    example session is left out of research; it debits nothing, and if it ever did, the figure is the
    research total to the cent."""
    if not credits["research"]:
        return 0.0  # no research debits this week: nothing to split
    by = credits["by_source"]
    if abs(by["research"] + by["autopilot_research"] - credits["research"]) > 1e-9:
        return credit_usd(credits["research"])
    split = credit_split(by)
    return credit_usd(credit_cents(split["research"]) + credit_cents(split["autopilot_research"]))


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
        lines.append("It sticks to the focus you set: %s." % agent.focus_words(d["focus"]))  # "Bitcoin", never "btc"
    tested, passed = int(research.get("tested_7d") or 0), int(research.get("passed_7d") or 0)
    # passed_7d counts only passes cleared to trade; one a later check left uncleared (Missed final test,
    # Held back) is said apart, as the session rows and the Strategies list say it.
    fell = int(research.get("not_cleared_7d") or 0)
    if tested:
        cost = float(research.get("cost_7d") or 0)
        if passed:
            outcome = "{:,} passed".format(passed) + (
                ", and {:,} more passed but {} cleared to trade".format(fell, "wasn’t" if fell == 1 else "weren’t")
                if fell else "")
        elif fell:
            outcome = ("none has been cleared to trade yet: %s, but a later check didn’t clear %s. Each one’s "
                       "page says which check" % (_plural(fell, "passed", "passed"), "it" if fell == 1 else "them"))
        else:
            outcome = ("none has passed its tests yet. That’s normal: most ideas fail. Each session’s page names "
                       "the test each idea missed and what to try next")
        lines.append("This week it tested %s%s and %s." % (
            _plural(tested, "idea"), " for ${:,.2f}".format(cost) if cost >= 0.01
            else " for under $0.01" if research.get("cost_7d_under_cent") else "", outcome))
    paper, prog = int(d.get("paper_running") or 0), d.get("paper_progress")
    if idle and (idle == "engine" or not paper):
        pass  # the idle line (shown above the story) says why nothing trades; this one would repeat or contradict it
    elif not paper:
        lines.append("Nothing is trading on paper yet. A strategy has to pass the research tests first.")
    elif prog and int(prog.get("trades") or 0) > 0:
        # Its count and net are the realistic paper record across all its paper runs (the road to live's),
        # not one deployment's realized P&L: said so, since the Deploy row beside it shows that one.
        lines.append("%s on paper (pretend money). The furthest along has %d of the %d realistic paper trades live "
                     "needs and is %s on them %s, across all its paper runs." % (
            _plural(paper, "strategy is", "strategies are"), int(prog["trades"]), int(prog["trades_needed"]),
            ("up $%.2f" % prog["net_pnl"]) if prog["net_pnl"] >= 0 else ("down $%.2f" % -prog["net_pnl"]),
            customer_text.PAPER_NET_SHORT))
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
                     "(%s), and only if it’s up by then." % (when, _short_title(prog.get("soonest_title"))))
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
    # While the server's live switch is closed (live_enabled, engine.LIVE_TRADING_ENABLED) a running live
    # strategy places no orders: it waits, in the words Deploy and the badges use.
    live_open = bool(d.get("live_enabled"))
    if int(d.get("live_running") or 0) and not live_open:
        n = int(d["live_running"])
        lines.append("%s live but waiting: live trading isn’t open yet, so %s no orders." % (
            _plural(n, "strategy is", "strategies are"), "it places" if n == 1 else "they place"))
    elif int(d.get("live_running") or 0):
        lines.append("%s trading real money." % _plural(int(d["live_running"]), "strategy is", "strategies are"))
    elif limit > 0 and float(d.get("today_live_pnl") or 0) <= -limit:
        # The kill switch turned live autopilot off and paused live deployments; the panel used to
        # go back to "Nothing trades real money until..." as if live had never run.
        lines.append("Live trading stopped for today: today’s live loss of $%.2f reached your $%.2f daily limit, "
                     "so live autopilot switched itself off and live strategies were paused. Paper keeps running."
                     % (-float(d["today_live_pnl"]), limit))
    else:
        lines.append("Nothing trades real money until a strategy makes money on paper over at least %d trades "
                     "from %d separate events and %d hours, and you turn on live autopilot.%s" % (
                         agent.MIN_REALISTIC_PAPER_TRADES, agent.MIN_PAPER_EVENTS, int(agent.MIN_PAPER_SPAN_HOURS),
                         "" if live_open else " Live trading isn’t open yet."))
    return lines


def _autopilot_now(d: Dict) -> str:
    """The story's first line: what the autopilot is doing right now."""
    active = (d.get("research") or {}).get("active") or []
    if active:
        names = [n for n in dict.fromkeys(active) if n != "a market it’s still picking"]  # two runs on one market read as one
        now = ("Right now it’s researching %s." % (
            names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1])) if names \
            else "Right now it’s picking a market to research."
    elif d.get("reviewing"):
        now = "Right now it’s reviewing the markets to pick its next move. Each move shows up in its activity feed."
    elif d.get("review_wait"):
        w = d["review_wait"]
        mins = max(1, int(w.get("seconds") or 0) // 60)
        now = ("Its next review has waited %s for a free worker, longer than usual. It starts when one frees up."
               % _span(mins)) if w.get("state") == "queued" else \
              ("Its review hasn’t checked in for %s. A review that quiet is normally stopped, and the next one "
               "starts on schedule." % _span(mins))
    else:
        now = "Right now it’s between research runs. It checks in about every %d minutes." % max(1, COPILOT_REVIEW_MINUTES)
        quiet = _quiet_minutes(d.get("last_review_at"))
        if quiet:
            # A stalled worker would leave "checks in every 10 minutes" on screen for hours; say how long it's been.
            # Same steps as the "Last reviewed" figure beside it (sinceMin), so the two never disagree.
            now = "Right now it’s between research runs. Its last check-in was %s ago, longer than usual." % _span(quiet)
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
            out.append({"deployment_id": d["id"], "title": _short_title(d.get("title")), "why": customer_text.curly(sc["why"]),
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
        where = "it keeps %d%% of its %s practice book in cash until a strategy shows it makes money" % (
            round(100 * t["cash_weight"]), book)
    else:
        where = "it has %d%% of its %s practice book on %s" % (
            round(100 * lead["weight"]), book, lead["title"] or "its leader")
    return ("The paper tournament runs %s at once, with %d of the %d separate bets it takes to judge them so far; %s." % (
        _plural(t["entrants"], "strategy", "strategies"), t["trips"], t["target"], where))


def _paused_recent(deps: List[Dict], hours: int = 24, cur=None, memo: Optional[book_memo.BookMemo] = None) -> List[Dict]:
    """Paper deployments paused in the last `hours`: they leave the 'running' count, so without
    this a stopped-out strategy simply vanishes from the panel. Deployments listed without their
    position totals (list_deployments_brief) get them from one read of just these, through `cur`,
    or through `memo`, which keeps them while the positions are unchanged."""
    since = repo.now_utc() - timedelta(hours=hours)
    picked = [d for d in deps if d["mode"] == "paper" and d["status"] == "paused"
              and d.get("updated_at") is not None and d["updated_at"] >= since][:3]
    totals = {}
    if any("closed_trades" not in d for d in picked):
        ids = [d["id"] for d in picked]
        if memo is not None:
            totals = book_memo.closed_totals(memo, ids)
        elif cur is not None:
            totals = repo.deployment_closed_totals(cur, ids)
    out = []
    for d in picked:
        trades, pnl = ((d.get("closed_trades"), d.get("realized_pnl")) if "closed_trades" in d
                       else totals.get(int(d["id"]), (0, 0)))
        out.append({"deployment_id": d["id"], "title": _short_title(d.get("title")),
                    "trades": int(trades or 0), "pnl": cents(pnl),
                    "why": _plain_pause_reason(d.get("status_reason"))})
    return out


def _paused_lines(paused: List[Dict]) -> List[str]:
    return ["%s was paused after %s (%s %s): %s." % (p["title"], _plural(p["trades"], "paper trade"), _money(p["pnl"]),
                                                     customer_text.PAPER_NET_SHORT, p["why"])
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


# The autopilot's last move, kept per user against their chat's version (rows, highest id) from the
# panel's pulse. The line is read from the newest chat rows, and chat rows are only ever added (none is
# rewritten or removed), so the same version means the same rows and the same line. The row count
# catches a row committed after a higher id was already read.
_LAST_ACTION: Dict[int, Tuple[Tuple[int, int], Optional[Dict]]] = {}
_LAST_ACTION_MAX = 4096


def _last_action(cur, uid: int, chat: Optional[Tuple[int, int]]) -> Optional[Dict]:
    """repo.last_autopilot_action, read again only after the user's chat moved. No chat, no line."""
    if chat is None:
        return repo.last_autopilot_action(cur, uid)
    if not chat[0]:
        return None
    hit = _LAST_ACTION.get(uid)
    if hit is None or hit[0] != chat:
        if len(_LAST_ACTION) >= _LAST_ACTION_MAX:
            _LAST_ACTION.clear()
        hit = _LAST_ACTION[uid] = (chat, repo.last_autopilot_action(cur, uid))
    return dict(hit[1]) if hit[1] is not None else None


def _last_move(la: Optional[Dict], deps: List[Dict]) -> Optional[Dict]:
    """The last move as the panel shows it: the engine's "Paused deployment #N automatically" line said
    with the strategy's name (customer_text.auto_pause_line), and, as "titles", the names of the
    user's strategies in the line that hold " — " ("Fade tails — v2"). The panel cuts a line at " — " to
    its first clause, and cut inside a name it read "I left Fade tails."."""
    if la is None:
        return None
    # A once-only line's marker ("[live-ready #12]") names a row number: the panel never gets it.
    out = {"text": customer_text.unmarked(la["text"]), "at": la["at"]}
    if "deployment" in la:
        out["text"] = customer_text.auto_pause_line(la["text"], la["deployment"])
    names = {(la.get("deployment") or {}).get("title") or ""} | {d.get("title") or "" for d in deps}
    titles = sorted((t for t in names if " — " in t and t in out["text"]), key=len, reverse=True)
    if titles:
        out["titles"] = titles
    return out


class _PanelReads(billing.Reads):
    """billing.Reads whose balance came with the panel's credit read (repo.credit_week, the same SUM)."""

    def __init__(self, cur, uid: int, balance: Optional[float]):
        super().__init__(cur, uid)
        self._known = balance

    def balance(self) -> float:
        return self._known if self._known is not None else super().balance()


def _passed_undeployed(cur, uid: int, focus: List[str], deployed: Optional[Dict[int, int]] = None) -> List[Dict]:
    """The user's passed strategies that never ran on paper (the example left out), each with whether
    it is inside the focus and, for the first few inside it, whether the gatekeeper made it a
    deployment candidate: the same tests agent.auto_paper_candidates applies before it deploys one.
    `deployed` is {deployment_id: strategy_id} for every deployment, stopped ones too, when the caller
    has it (the panel's pulse); without it the deployments are listed here."""
    try:
        rows = repo.list_strategies(cur, uid, status="passed", limit=100)
        tried = (set(deployed.values()) if deployed is not None
                 else {d["strategy_id"] for d in repo.list_deployments(cur, uid, include_stopped=True)})
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
        when = ("isn’t running" if engine_age is None
                else "last checked the markets %s ago" % _span(max(1, int(engine_age) // 60)))
        return _idle("engine", "Nothing is trading right now: Tau’s trading engine %s, so %s. There’s nothing for "
                               "you to do; %s when it’s back." % (
                                   when, "your strategy can’t buy or sell" if running == 1
                                   else "your %d strategies can’t buy or sell" % running,
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
                        "again at its market’s next decision time." % (who, _plural(done, "trade"))) if n == 1 else \
                       ("Nothing open right now: none of your %d paper strategies holds a position (the furthest "
                        "along, %s, has closed %s). Each checks again at its market’s next decision time."
                        % (n, who, _plural(done, "trade")))
                return _idle("flat", line)
            line = ("No trades yet: %s went on paper and hasn’t had its first look at the market. It checks at its "
                    "market’s next decision time." % _short_title(paper_run[0].get("title"))) if n == 1 else \
                   ("No trades yet: your %d paper strategies haven’t had their first look at the market. Each checks "
                    "at its market’s next decision time." % n)
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
        if not card and d.get("reload_failed"):  # auto-reload is on and the card it charges was refused
            return _idle("billing", "Nothing is on paper, and it can’t research new strategies: auto-reload couldn’t "
                                    "charge your card. Update it on Billing, then add credits.",
                         {"label": "Update card", "href": "/billing"})
        return _idle("billing", "Nothing is on paper, and it can’t research new strategies until you %s." % (
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
        return _idle("focus", "Nothing is on paper: your focus is %s, and %s outside it, so it won’t deploy %s. "
                              "It researches inside the focus to find new ones." % (
                                  agent.focus_words(focus), ("your passed strategy, %s, is" % passed[0]["title"]) if k == 1
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
                                         "it hasn’t" if len(inside) == 1 else "none has", doing))
    code = ("researching" if (d.get("research") or {}).get("active") else "reviewing" if d.get("reviewing")
            else "review_wait" if d.get("review_wait") else "no_strategies")
    if retired:
        return _idle(code, "Nothing is on paper: %s that passed %s stopped on paper, and no new one has passed since. %s" % (
            "the strategy" if len(retired) == 1 else "the %d strategies" % len(retired),
            "was" if len(retired) == 1 else "were", doing))
    return _idle(code, "Nothing is on paper yet: no strategy has passed its research tests. %s" % doing)


def autopilot_status(ctx: Ctx):
    """Lightweight status for the floating autopilot window, polled on every page. It never waits on Kalshi:
    a demo-funds idle line that would read the demo cash is left out and marked
    idle_pending, and the page asks /api/funds/cash?book=demo, then the status again once that cash is read."""
    cur, u = ctx.cur, ctx.user
    on = bool(u.get("autopilot"))
    # Without the per-deployment position totals: this polls, and only _paused_recent needs them.
    deps = repo.list_deployments_brief(cur, ctx.uid)
    live_run = [d for d in deps if d["mode"] == "live" and d["status"] == "running"]
    paper_run = [d for d in deps if d["mode"] == "paper" and d["status"] == "running"]
    demo_run = [d for d in deps if d["mode"] == "demo" and d["status"] == "running"]
    running = len(paper_run) + len(demo_run) + len(live_run)
    since = repo.now_utc() - timedelta(days=7)
    # The small reads in one statement (repo.autopilot_pulse), the positions' version among them, so it
    # is read before any read kept against it. The engine's beat only when the idle line can use it.
    pulse = _pulse(cur, ctx.uid, since, review=on, engine=on and running > 0)
    memo = book_memo.BookMemo(cur, ctx.uid, version=pulse["positions"], strategies=pulse["dep_strategies"])
    kalshi_connected = pulse["kalshi_key"]  # read once: the live gate and the badge
    gates_ok = bool(engine.LIVE_TRADING_ENABLED and kalshi_connected)
    live_on = bool(u.get("autopilot_live")) and gates_ok and on
    mode = "live" if (live_on and live_run) else ("live-armed" if live_on else ("paper" if on else "off"))
    # Each book's day, summed apart (never together) and kept until a position moves.
    today = book_memo.realized_since(memo, ("live", "paper"), _start_of_day_utc())
    today_live = cents(today["live"])
    limit = float(u.get("autopilot_daily_loss_limit") or 50)
    # The week's credit figures and, when a figure below needs it, the balance: one read of the ledger.
    payments = billing.configured()
    credits = repo.credit_week(cur, ctx.uid, since, balance=on and payments)
    # When autopilot is ON but can't spend (no card, or balance below the per-run floor), the worker
    # silently skips the user via billing.is_ready — the SAME gate, read here only to surface WHY the
    # panel is quiet so it doesn't look broken. Never changes the gate; purely a status readout.
    reads = _PanelReads(cur, ctx.uid, credits["balance"])  # the readout below reuses the gate's card and balance reads
    billing_blocked = on and payments and not billing.is_ready(cur, ctx.uid, reads)
    review = pulse["review"] if on else None
    review_wait = _run_wait(review) or {"overdue": False}
    # The story is the only reader of the paused, early-exit and tournament lines, and it says one fixed
    # line while autopilot is off and nothing while billing blocks it: read them only when it tells them.
    story = on and not billing_blocked
    # Paper -> live progress: the running paper strategy closest to the realistic-trade gate, so a
    # user on autopilot can see the funnel moving. Counts only (no bootstrap): this endpoint polls.
    paper_progress = None
    if paper_run:
        sids = sorted({int(d["strategy_id"]) for d in paper_run})
        # Both readouts are kept until the positions (or which deployments count toward them) change.
        prog, events = book_memo.paper_readouts(memo, sids)
        titles = {int(d["strategy_id"]): d.get("title") or "" for d in paper_run}
        best = max(sids, key=lambda s: (prog.get(s, (0, 0.0))[0], prog.get(s, (0, 0.0))[1]))
        trades, net = prog.get(best, (0, 0.0))
        paper_progress = {"strategy_id": best, "title": titles[best], "trades": trades,
                          "trades_needed": agent.MIN_REALISTIC_PAPER_TRADES, "net_pnl": cents(net),
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
        "research": _research_activity(cur, ctx.uid, pulse, _research_cents(credits), credits["research"]),
        "autopilot": on,
        "autopilot_live": bool(u.get("autopilot_live")),
        "live_enabled": bool(engine.LIVE_TRADING_ENABLED),
        "kalshi_connected": kalshi_connected,
        "mode": mode,
        "live_running": len(live_run), "paper_running": len(paper_run), "demo_running": len(demo_run),
        "today_live_pnl": today_live,
        # The paper book's day, so a paper-only panel shows its own money instead of a live $0.00.
        "today_paper_pnl": cents(today["paper"]),
        "daily_loss_limit": limit,
        "loss_headroom": cents(max(0.0, limit + min(0.0, today_live))),  # how much loss budget is left today
        "last_action": _last_move(_last_action(cur, ctx.uid, pulse["chat"]), deps),
        "last_review_at": pulse["last_review_at"],  # liveness: a quiet review posts nothing, this still shows it ran
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
        "credits_low_days": (_credits_running_low(cur, ctx.uid, reads, spent_7d=credits["spent"], created_at=u.get("created_at"))
                             if on and payments and not billing_blocked else None),
        # The last auto-reload failed (Billing's banner text: what it tried to add and why), read only
        # when it can be why credits are short: auto-reload on with a card, the balance at its trigger.
        "reload_failed": reload_failed_now(cur, ctx.uid, reads) if on and payments else None,
        "paper_progress": paper_progress,
        # Read by the story and the idle line, both of which say nothing of paper while autopilot is off.
        "paper_open": book_memo.open_count(memo, "paper") if paper_run and on else 0,
        "paper_waiting": _paper_waiting(paper_run, _scan_tally(cur, paper_run)) if on else [],
        "paused_recent": _paused_recent(deps, memo=memo) if story else [],
        "early_exits_7d": _early_exits(cur, ctx.uid) if story else {},
        "tournament": _tournament_summary(cur, ctx.uid, deps) if story else None,
    }
    if on:
        out["week"] = _autopilot_week(cur, ctx.uid, out["research"], reads, credits, u.get("created_at"))
        # Why nothing is trading right now (None while something is). Each read is skipped unless
        # its state can be the answer, since this endpoint polls.
        paused = sorted((d for d in deps if d["mode"] == "paper" and d["status"] == "paused"),
                        key=lambda d: d.get("updated_at") or datetime.min, reverse=True)
        out["idle"] = _idle_reason(out, paper_run, paused, pulse["engine_age"] if running else _UNKNOWN,
                                   _passed_undeployed(cur, ctx.uid, out["focus"], pulse["dep_strategies"]) if not running and not paused
                                   and not billing_blocked else [])
        # A demo copy whose every order Kalshi refuses is what isn't trading when paper is fine, and
        # the truer line when nothing is on paper (only the engine or billing outrank it there).
        idle = out["idle"]
        if idle is None or (not paper_run and idle["code"] not in ("engine", "billing")):
            # From the demo cash memo alone: pending when it isn't kept, the page then reading the status again
            # once the demo cash is in (a line from a figure read under two minutes ago stands meanwhile).
            health, pending = demo_health_memo(cur, ctx.uid, deps)
            if pending:
                out["idle_pending"] = True
            out["idle"] = health or idle
    else:
        out["idle"] = None
    out["story"] = _autopilot_story(out)
    return out


def _pulse(cur, uid: int, since, review: bool, engine: bool) -> Dict:
    """repo.autopilot_pulse; when the engine's beat can't be read (its table isn't there before the
    first schema run), everything else is read without it and the beat is unknown."""
    try:
        return repo.autopilot_pulse(cur, uid, since, review=review, engine=engine)
    except Exception:  # noqa: BLE001 - only the engine's beat may fail; anything else fails again below
        if not engine:
            raise
    return dict(repo.autopilot_pulse(cur, uid, since, review=review), engine_age=_UNKNOWN)


def _autopilot_week(cur, uid: int, research: Dict, reads: Optional[billing.Reads] = None,
                    credits: Optional[Dict] = None, created_at=None) -> Dict:
    """The autopilot's last 7 days, for its scorecard. Research reuses the panel's week (every
    research session, the user's and the autopilot's; credits are what the ledger debited). Paper
    covers only the strategies the autopilot put on paper itself. Credits are real money and paper
    P&L is not, so they are separate fields the page shows apart and never adds up. `credits` is the
    panel's repo.credit_week, when it has read it. The runway is per day of the account's age while
    it is under a week old (`created_at`), as on Billing, and `pace_days` says how many days it covers."""
    since = repo.now_utc() - timedelta(days=7)
    paper = repo.autopilot_paper_week(cur, uid, since)
    out = {"research_credits": research.get("cost_7d", 0.0), "tested": research.get("tested_7d", 0),
           "passed": research.get("passed_7d", 0), "not_cleared": research.get("not_cleared_7d", 0),
           "paper_started": paper["started"],
           "paper_pnl": cents(paper["pnl"]), "paper_trades": paper["trades"],
           "checkin_credits": None, "credits_left": None, "runway_days": None, "reload_days": None, "pace_days": None,
           # Whether a card was ever charged for credits (the panel's credit read, with the balance): until
           # then every credit spent was a free one, and the page says so beside the spend, not "real money".
           "card_charged": credits.get("card_charged") if credits is not None else None,
           # A figure that spent something but shows $0.00 (Billing's spent_7d_under_cent): the page says
           # "under $0.01", as Billing does, instead of $0.00 beside it. The figures themselves stay Billing's.
           "research_under_cent": bool(credits is not None and credit_exact(credits.get("research") or 0) > 0
                                       and not research.get("cost_7d")),
           "checkin_under_cent": False}
    if billing.configured():
        # What else the week cost and how long the balance lasts at that pace, read-only: the
        # autopilot's check-ins bill too, and the runway is the Billing page's (every usage debit of
        # the week). With payments off nothing pauses it, so there is no limit to show.
        used = credits["by_source"] if credits is not None else repo.usage_by_source(cur, uid, since)
        spent_7d = sum(used.values())
        reads = reads or billing.Reads(cur, uid)
        balance = reads.balance()
        days = pace_days(created_at)
        # Billing's two countdowns: until research pauses, and until auto-reload next charges the card.
        checkins = credit_split(used)["autopilot_review"]
        out.update(checkin_credits=checkins, checkin_under_cent=credit_exact(used["autopilot_review"]) > 0 and not checkins,
                   credits_left=credit_usd(balance),
                   runway_days=runway_days(balance, spent_7d, days, stop_at=pause_at()),
                   reload_days=reload_days(reads.customer(), balance, spent_7d, days), pace_days=days)
    return out


def autopilot_focus(ctx: Ctx):
    """Set or clear the autopilot's market focus (family names, coins or market keys)."""
    try:
        tokens = agent.normalize_focus(ctx.body.get("focus") or [])
    except ValueError as e:
        raise ApiError(400, str(e))
    repo.set_autopilot_focus(ctx.cur, ctx.uid, tokens)
    repo.add_chat(ctx.cur, ctx.uid, "system", ("Market focus set to %s." % agent.focus_words(tokens)) if tokens
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
