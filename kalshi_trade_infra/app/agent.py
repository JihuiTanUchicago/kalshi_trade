"""The research agent and the deployment co-pilot.

Research (one run):

    data summary + direction + this user's past results
        -> round 1: propose 4 hypotheses (thesis + spec)
        -> backtest each IN-SAMPLE only
        -> round 2: see the in-sample table, propose 3 refinements
        -> backtest IN-SAMPLE
        -> freeze the best 3, only now run them out-of-sample + gates
        -> every hypothesis is saved, passed or not

The out-of-sample window stays hidden until candidates are frozen, so the
agent cannot tune itself onto it. Past results feed the next run's prompt,
which is the "recursive" part: each run starts from what the last ones learnt.

Co-pilot (chat and scheduled reviews): reads the user's deployments and
replies with prose plus at most three actions. Every action goes through
`act()`: adjustments are re-backtested and must pass the same gates, and on
autopilot the agent may apply them itself only if they do not raise risk and
never onto live money.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Callable, Dict, List, Optional, Tuple

from app import backtest, billing
from app import repository as repo
from app import spec as specmod
from app.llm import LLMError, ModelFn, Usage, ask_json, claude, current_model
from app.markets import MARKETS

DIRECTIONS: Dict[str, Dict[str, str]] = {
    "volatility": {
        "label": "Volatility mispricing",
        "brief": "Does the market over- or under-price how far BTC can move before settlement?",
    },
    "momentum": {"label": "Momentum", "brief": "Do recent BTC moves keep going into settlement?"},
    "mean_reversion": {"label": "Mean reversion", "brief": "Do sharp BTC moves snap back before settlement?"},
    "near_expiry": {"label": "Near expiry", "brief": "Are contracts mispriced in the last minutes before settlement?"},
    "longshots": {
        "label": "Favorites & longshots",
        "brief": "Are very cheap or very expensive contracts systematically mispriced?",
    },
    "time_of_day": {"label": "Time of day", "brief": "Do edges depend on the hour (US open, overnight, Asia)?"},
    "open": {"label": "Agent's choice", "brief": "Pick the most promising angle yourself and say why."},
}

BATCH = 4                 # hypotheses proposed per round; small so each round can LEARN from the last
DEFAULT_HYPOTHESES = 8    # when the user doesn't set a budget
MAX_BUDGET = 50           # hard ceiling a user can request for one run
FINALISTS = 3             # per chunk, only the best few are gated on unseen data (multiple-testing discipline)
FOREVER_CAP = 300         # safety ceiling for run_forever; credits exhausting also stops it
MAX_ACTIONS = 3
MIN_FRAMES = 200

RESEARCH_SYSTEM = """You are a quantitative researcher at a disciplined prediction-market fund.
You design trading rules for Kalshi Bitcoin binary contracts (pays $1 if BTC settles above the
strike). You cannot write code: every idea must be expressed as a strategy spec that our
backtester runs. Fees are charged: Kalshi's taker fee is 7% x price x (1 - price) per contract,
so thin edges on mid-priced contracts die after fees. Prefer few, robust, explainable rules over
many fragile ones; each hypothesis must have a mechanism a sceptical PM would accept.
Write theses in plain English a non-quant can follow (2-4 sentences, no jargon without a gloss).
Reply with ONE JSON object only."""

COPILOT_SYSTEM = """You are the trading co-pilot inside Tau. You watch the user's deployed
Kalshi Bitcoin strategies and talk with them in plain, brief English (no jargon without a gloss).
You can act through structured actions; the host re-backtests every adjustment and applies it
only if it still passes the deployment gates. Be honest about uncertainty and small samples:
a handful of live trades proves little either way. Never promise profit.
Reply with ONE JSON object only."""


# -- research ------------------------------------------------------------------


def _hypotheses_check(market: str, max_n: int) -> Callable[[Dict], List[Dict]]:
    def check(obj: Dict) -> List[Dict]:
        items = obj.get("hypotheses")
        if not isinstance(items, list) or not 1 <= len(items) <= max_n:
            raise ValueError("'hypotheses' must be a list of 1 to %d items" % max_n)
        out, problems = [], []
        for i, h in enumerate(items):
            if not isinstance(h, dict):
                problems.append("hypotheses[%d] must be an object" % i)
                continue
            title = str(h.get("title") or "").strip()
            thesis = str(h.get("thesis") or "").strip()
            raw = h.get("spec")
            if not title or not thesis:
                problems.append("hypotheses[%d] needs a title and a thesis" % i)
                continue
            if isinstance(raw, dict):
                raw = dict(raw)
                if raw.setdefault("market", market) != market:
                    problems.append("hypotheses[%d].spec.market must be %s" % (i, market))
                    continue
            try:
                spec = specmod.validate(raw)
            except specmod.SpecError as e:
                problems.append("hypotheses[%d].spec: %s" % (i, e))
                continue
            out.append({"title": title[:120], "thesis": thesis[:1500], "spec": spec})
        if problems:
            raise ValueError("; ".join(problems))
        return out

    return check


def _metrics_line(m: Dict) -> str:
    return "trades=%s win_rate=%s pnl=$%s fees=$%s profit_factor=%s max_dd=$%s" % (
        m["trades"], m["win_rate"], m["pnl"], m["fees"], m["profit_factor"], m["max_drawdown"],
    )


def _memory_block(memory: List[Dict]) -> str:
    if not memory:
        return "No earlier research on this market for this user."
    lines = []
    for s in memory:
        res = s.get("result") or {}
        ins = res.get("in_sample") or {}
        oos = res.get("out_of_sample") or {}
        # Compact (no spec) so we can show many prior results without bloating context —
        # enough for the agent to know what's been tried and not repeat it.
        lines.append(
            "- [%s] %s: in-sample $%s/%s trades%s"
            % (
                s["status"], s["title"], ins.get("pnl"), ins.get("trades"),
                ("; unseen $%s" % oos.get("pnl")) if oos else "",
            )
        )
    return "\n".join(lines)


_BRIEF_PATH = os.path.join(os.path.dirname(__file__), "research_brief.md")


def _brief() -> str:
    """The operator-editable research constitution (app/research_brief.md), read fresh each run
    so edits take effect without a deploy. Empty string if it's missing."""
    try:
        with open(_BRIEF_PATH) as f:
            return f.read().strip()
    except OSError:
        return ""


def _pick_market(run: Dict, model: ModelFn, usage: Usage, log) -> str:
    """When the user didn't pin a market, let the agent choose the one whose contracts best
    fit the idea (guided by the brief). One cheap call before the research loop."""
    idea = (run.get("prompt") or "").strip() or "any durable, fee-surviving edge"
    opts = "\n".join("- %s: %s" % (k, m.label) for k, m in MARKETS.items())
    msg = ("%s\n\nIdea: %s\nMarkets you can research:\n%s\n"
           "Pick the ONE market whose contracts best fit this idea. Reply exactly:\n"
           '{"market": "<key>", "why": "<one sentence>"}' % (_brief(), idea[:400], opts))

    def check(obj: Dict) -> Dict:
        k = obj.get("market")
        if k not in MARKETS:
            raise ValueError("market must be one of: " + ", ".join(MARKETS))
        return {"market": k, "why": str(obj.get("why") or "")[:200]}

    r = ask_json(model, RESEARCH_SYSTEM, [{"role": "user", "content": msg}], check, usage)
    log("step", "Chose to research %s. %s" % (MARKETS[r["market"]].label, r["why"]))
    return r["market"]


def _plan_lookback(run: Dict, market: str, model: ModelFn, usage: Usage, log) -> int:
    """Let the agent choose how much history to backtest on, guided by the brief and its thesis,
    clamped to what we actually have. One cheap call before the heavy research loop."""
    m = MARKETS[market]
    maxd = m.history_days
    idea = (run.get("prompt") or "").strip() or "any durable, fee-surviving edge"
    msg = ("%s\n\nIdea: %s\nMarket: %s. Up to %d days of history are available to backtest on.\n"
           "Pick how many days the backtest should replay for THIS idea. Reply exactly:\n"
           '{"lookback_days": <integer 5..%d>, "why": "<one sentence>"}'
           % (_brief(), idea[:400], m.label, maxd, maxd))

    def check(obj: Dict) -> Dict:
        d = obj.get("lookback_days")
        if not isinstance(d, (int, float)):
            raise ValueError("reply needs an integer lookback_days")
        return {"days": max(5, min(int(d), maxd)), "why": str(obj.get("why") or "")[:200]}

    r = ask_json(model, RESEARCH_SYSTEM, [{"role": "user", "content": msg}], check, usage)
    log("step", "Chose a %d-day backtest window for this idea. %s" % (r["days"], r["why"]))
    return r["days"]


def _research_prompt(run: Dict, ds: backtest.Dataset, memory: List[Dict], count: int) -> str:
    idea = (run.get("prompt") or "").strip() or "Find any durable, fee-surviving edge you can justify."
    brief = _brief()
    lens = ""
    if run.get("direction") and run["direction"] in DIRECTIONS:
        d = DIRECTIONS[run["direction"]]
        lens = "\nOptional lens to consider: %s - %s" % (d["label"], d["brief"])
    return """{brief}

The user's idea: {idea}{lens}

Turn this idea into concrete, testable trading strategies. Stay faithful to what the
user asked for; if the idea is vague, pick the most promising precise reading and say so.

Market: {market_label} (spec market "{market}").
In-sample data you can test on: {summary}

{guide}

What this user's earlier research found (learn from it; do not repeat failures):
{memory}

Propose {count} distinct hypotheses for this idea. Reply:
{{"hypotheses": [{{"title": "...", "thesis": "...", "spec": {{...}}}}]}}""".format(
        brief=brief,
        idea=idea[:1000],
        lens=lens,
        market_label=MARKETS[run["market"]].label,
        market=run["market"],
        summary=json.dumps(_in_sample_summary(ds)),
        guide=specmod.SPEC_GUIDE,
        memory=_memory_block(memory),
        count=count,
    )


def _in_sample_summary(ds: backtest.Dataset) -> Dict:
    """What the agent may know about the data: the in-sample window only."""
    s = ds.summary()
    s["end"] = s.pop("out_of_sample_from")
    s.pop("decision_points", None)
    return s


class Cancelled(Exception):
    pass


def _bill(conn, user_id, usage, run_id):
    """Meter the tokens this run spent against the user's credits."""
    if usage.input_tokens or usage.output_tokens:
        billing.charge_usage(conn, user_id, current_model(), usage.input_tokens, usage.output_tokens, run_id)


def _round_prompt(run: Dict, ds: backtest.Dataset, memory: List[Dict], want: int, chunk: List[Dict]) -> str:
    """Round 1 asks fresh; later rounds show the agent its own in-sample results so it
    refines — the loop is a conversation with the data, not a fixed two-shot."""
    base = _research_prompt(run, ds, memory, want)
    if not chunk:
        return base
    # Digest, not a dump: full detail for the best few to refine, bare titles for the rest so the
    # agent stays aware of what it tried (and doesn't repeat) without the prompt growing unbounded.
    ranked = sorted(chunk, key=lambda t: backtest.score(t["in_sample"]), reverse=True)
    detail = "\n".join(
        "- %s: %s; spec=%s" % (t["title"], _metrics_line(t["in_sample"]), json.dumps(t["spec"], separators=(",", ":")))
        for t in ranked[:12]
    )
    extra = ""
    if len(ranked) > 12:
        extra = "\nAlso already tested (do not repeat): " + "; ".join(t["title"] for t in ranked[12:])
    return (base + "\n\nResults so far this session (in-sample only; out-of-sample is held back):\n" + detail + extra
            + "\n\nPropose %d NEW, distinct hypotheses: refine what worked, drop what did not, "
              "and explain the change in each thesis." % want)


def _finalists(chunk: List[Dict]) -> List[Dict]:
    """The few best in-sample hypotheses that earn an unseen-data test. Kept small on
    purpose: testing every idea out-of-sample is multiple-testing and manufactures false edges."""
    ranked = sorted(chunk, key=lambda t: backtest.score(t["in_sample"]), reverse=True)
    n = min(max(FINALISTS, len(chunk) // 10), 8)
    return [t for t in ranked[:n] if t["in_sample"]["pnl"] > 0 and t["in_sample"]["trades"] >= 5]


def _gate_and_save(cur, run: Dict, ds: backtest.Dataset, chunk: List[Dict], log) -> int:
    """Freeze the finalists, test ONLY them on unseen data, and persist every hypothesis
    (finalists with their out-of-sample verdict, the rest as rejected). Returns passers."""
    user_id, run_id, market = run["user_id"], run["id"], run["market"]
    s = ds.summary()
    finalists = _finalists(chunk)
    log("step", "Froze %d finalist%s. Now testing on data the agent never saw."
        % (len(finalists), "" if len(finalists) == 1 else "s"))
    passed = 0
    for t in chunk:
        if t in finalists:
            result = backtest.evaluate(t["spec"], ds)
            status = "passed" if result["passed"] else "failed"
            passed += status == "passed"
            verdict = "PASSED" if status == "passed" else "VOID"
            log("verdict", "%s - %s: unseen-data pnl $%s over %s trades."
                % (verdict, t["title"], result["out_of_sample"]["pnl"], result["out_of_sample"]["trades"]),
                {"title": t["title"], "status": status, "gates": result["gates"]})
        else:
            result = {"capital": t["capital"], "dataset": s, "in_sample": t["in_sample"]}
            status = "rejected"
            ins = t["in_sample"] or {}
            log("verdict", "REJECTED - %s: not a finalist, so never tested on unseen data "
                "(in-sample pnl $%s over %s trades)." % (t["title"], ins.get("pnl"), ins.get("trades")),
                {"title": t["title"], "status": "rejected"})
        t["strategy_id"] = repo.insert_strategy(
            cur, user_id, run_id, None, market, run["direction"] or "custom", t["title"], t["thesis"], t["spec"],
            status, result,
        )
    return passed


def _explore_and_gate(cur, run, ds, memory, model, usage, log, checkpoint, budget, tried) -> Tuple[int, int]:
    """Explore up to `budget` NEW hypotheses in-sample (small refining rounds), then gate
    the finalists. Appends to the shared `tried` so progress survives a cancel/error."""
    market = run["market"]
    chunk: List[Dict] = []
    round_no = 0
    while len(chunk) < budget:
        checkpoint()
        round_no += 1
        want = min(BATCH, budget - len(chunk))
        batch = ask_json(model, RESEARCH_SYSTEM,
                         [{"role": "user", "content": _round_prompt(run, ds, memory, want, chunk)}],
                         _hypotheses_check(market, want), usage)
        if not batch:
            break  # agent is out of fresh ideas this chunk
        for h in batch:
            checkpoint()
            t = _test_in_sample(h, ds, log, round_no)
            chunk.append(t)
            tried.append(t)
    return len(chunk), _gate_and_save(cur, run, ds, chunk, log)


def run_research(
    conn,
    run: Dict,
    model: ModelFn = claude,
    dataset_fn: Callable[[str], backtest.Dataset] = backtest.dataset,
) -> None:
    cur = conn.cursor()
    usage = Usage()
    tried: List[Dict] = []
    run_id, user_id, market = run["id"], run["user_id"], run["market"]

    def log(kind: str, message: str, data: Optional[Dict] = None) -> None:
        repo.add_event(cur, run_id, kind, message, data)

    def checkpoint() -> None:
        if repo.heartbeat(cur, run_id) == "cancelled":
            raise Cancelled()

    try:
        if not market:  # user left it to the agent — it picks the market from the idea first
            checkpoint()
            market = _pick_market(run, model, usage, log)
            run = {**run, "market": market}
            repo.set_run_market(cur, run_id, market)
        ds = dataset_fn(market)  # full available window first — confirms data before any model spend
        if len(ds.frames) < MIN_FRAMES:
            raise LLMError("Not enough market history collected yet for %s." % MARKETS[market].label)
        # The agent picks the window that fits its thesis; re-load the narrower slice if it
        # chose less, and keep the fuller one if the slice is too thin to be worth it.
        checkpoint()  # a cancel must stop before we spend a model call on planning
        lookback = _plan_lookback(run, market, model, usage, log)
        if lookback < MARKETS[market].history_days:
            narrowed = dataset_fn(market, lookback)
            if len(narrowed.frames) >= MIN_FRAMES:
                ds = narrowed
        s = ds.summary()
        log("step", "Loaded %s of %s history: %s decision points over %s contracts."
            % (_span_words(ds), MARKETS[market].label, s["decision_points"], s["contracts"]), s)
        budget = max(1, min(int(run.get("max_hypotheses") or DEFAULT_HYPOTHESES), MAX_BUDGET))
        forever = bool(run.get("run_forever"))
        log("step", "Plan: explore %s, refining each round on the in-sample results, then gate the best on data never seen.%s"
            % ("hypotheses until you stop it" if forever else "up to %d hypotheses" % budget,
               " I'll keep going until you stop me." if forever else ""))

        total_passed, tot_in, tot_out = 0, 0, 0
        while True:
            checkpoint()
            # Reload memory each chunk so a run_forever loop learns from the strategies it
            # just saved, instead of re-proposing the same ideas.
            memory = repo.strategy_memory(cur, user_id, market)
            n, passed = _explore_and_gate(cur, run, ds, memory, model, usage, log, checkpoint, budget, tried)
            total_passed += passed
            # Meter per chunk: a run_forever session may never "finish", so bill as it goes
            # (and reset the counter) instead of only at the end — otherwise its tokens are free.
            tot_in += usage.input_tokens
            tot_out += usage.output_tokens
            _bill(conn, user_id, usage, run_id)
            usage.input_tokens = usage.output_tokens = 0
            repo.update_run_progress(cur, run_id, len(tried), total_passed)  # keep counts live
            conn.commit()
            if n == 0 or not forever or len(tried) >= FOREVER_CAP:
                break
            log("step", "Still running - %d tested so far, %d passed. Exploring more (stop anytime)."
                % (len(tried), total_passed))

        log("done", "%d of %d hypotheses passed every gate." % (total_passed, len(tried)),
            {"passed": total_passed, "tried": len(tried)})
        repo.finish_run(cur, run_id, "succeeded", None, len(tried), total_passed, tot_in, tot_out)
    except Cancelled:
        _bill(conn, user_id, usage, run_id)  # charge whatever was spent before the stop
        log("step", "Cancelled.")
    except Exception as e:  # the run fails visibly; the worker keeps going
        msg = str(e) if isinstance(e, LLMError) else "Unexpected error: %s" % e
        log("error", msg)
        repo.finish_run(cur, run_id, "failed", msg[:2000], len(tried), 0, usage.input_tokens, usage.output_tokens)
        _bill(conn, user_id, usage, run_id)
        if not isinstance(e, LLMError):
            raise


def _span_words(ds: backtest.Dataset) -> str:
    days = (ds.end_ts - ds.start_ts) / 86400.0
    return "%d days" % round(days)


def _test_in_sample(h: Dict, ds: backtest.Dataset, log, round_no: int) -> Dict:
    res = backtest.evaluate(h["spec"], ds, include_oos=False)
    ins = res["in_sample"]
    log("hypothesis", h["title"], {"thesis": h["thesis"], "in_sample": ins, "round": round_no})
    return dict(h, in_sample=ins, capital=res["capital"])


# -- co-pilot ------------------------------------------------------------------


def _deep_merge(base: Dict, patch: Dict) -> Dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def raises_risk(old: Dict, new: Dict) -> bool:
    return (new["sizing"]["stake"] > old["sizing"]["stake"]
            or new["sizing"]["max_positions"] > old["sizing"]["max_positions"])


def act(cur, user: Dict, action: Dict, autopilot: bool, dataset_fn=backtest.dataset) -> Tuple[str, Optional[int]]:
    """Turn one agent action into a proposal (or, on autopilot, an applied
    change). Returns (sentence for the chat, proposal id if one was made)."""
    kind = action.get("type")
    reason = str(action.get("reason") or "").strip()[:1000] or "No reason given."
    user_id = user["id"]
    if kind in ("adjust", "pause", "resume"):
        dep = repo.get_deployment(cur, user_id, int(action.get("deployment_id") or 0))
        if dep is None or dep["status"] == "stopped":
            return "I couldn't find that deployment, so I did nothing.", None
    if kind == "adjust":
        changes = action.get("changes")
        if not isinstance(changes, dict) or not changes:
            return "I meant to adjust %s but sent no changes." % dep["title"], None
        try:
            new_spec = specmod.validate(_deep_merge(dep["spec"], changes))
        except specmod.SpecError as e:
            return "My adjustment to %s was invalid (%s), so nothing changed." % (dep["title"], e), None
        if new_spec["market"] != dep["market"]:
            return "An adjustment cannot move a strategy to a different market.", None
        result = backtest.evaluate(new_spec, dataset_fn(dep["market"]))
        if not result["passed"]:
            failed = ", ".join(g["name"].lower() for g in result["gates"] if not g["ok"])
            return "I backtested a change to %s but it failed (%s), so I left it alone." % (dep["title"], failed), None
        sid = repo.insert_strategy(
            cur, user_id, None, dep["strategy_id"], dep["market"], dep["direction"], dep["title"] + " (adjusted)",
            reason, new_spec, "passed", result,
        )
        auto = autopilot and dep["mode"] == "paper" and not raises_risk(dep["spec"], new_spec)
        pid = repo.create_proposal(cur, user_id, "adjust", reason, dep["id"], sid, "applied" if auto else "pending")
        if auto:
            repo.set_deployment_strategy(cur, user_id, dep["id"], sid)
            return "Autopilot applied an adjustment to %s. It passed the backtest gates." % dep["title"], pid
        return "Proposed adjustment to %s. It passed the backtest gates." % dep["title"], pid
    if kind in ("pause", "resume"):
        target = "paused" if kind == "pause" else "running"
        if dep["status"] == target:
            return "%s is already %s." % (dep["title"], target), None
        # Pausing only lowers risk, so autopilot may do it even on live money.
        auto = autopilot and (kind == "pause" or dep["mode"] == "paper")
        pid = repo.create_proposal(cur, user_id, kind, reason, dep["id"], None, "applied" if auto else "pending")
        if auto:
            repo.set_deployment_status(cur, user_id, dep["id"], target, "Autopilot: " + reason[:200])
            return "Autopilot %s %s." % ("paused" if kind == "pause" else "resumed", dep["title"]), pid
        return "Proposed to %s %s." % (kind, dep["title"]), pid
    if kind == "deploy":
        strat = repo.get_strategy(cur, user_id, int(action.get("strategy_id") or 0))
        if strat is None or strat["status"] != "passed":
            return "Only strategies that passed their backtest can be deployed.", None
        pid = repo.create_proposal(cur, user_id, "deploy", reason, None, strat["id"], "applied" if autopilot else "pending")
        if autopilot:
            repo.create_deployment(cur, user_id, strat["id"], strat["market"], "paper")
            return "Autopilot deployed %s on paper." % strat["title"], pid
        return "Proposed deploying %s on paper." % strat["title"], pid
    return "I tried an action I'm not allowed to take (%s)." % kind, None


def apply_proposal(cur, user_id: int, proposal: Dict) -> None:
    """The user approved it: do what it says."""
    kind = proposal["kind"]
    if kind == "adjust":
        repo.set_deployment_strategy(cur, user_id, proposal["deployment_id"], proposal["strategy_id"])
    elif kind in ("pause", "resume"):
        repo.set_deployment_status(cur, user_id, proposal["deployment_id"], "paused" if kind == "pause" else "running",
                                   "Approved agent proposal")
    elif kind == "deploy":
        strat = repo.get_strategy(cur, user_id, proposal["strategy_id"])
        repo.create_deployment(cur, user_id, strat["id"], strat["market"], "paper")


def _copilot_context(cur, user: Dict) -> str:
    deps = repo.list_deployments(cur, user["id"])
    passed = [s for s in repo.list_strategies(cur, user["id"], status="passed", limit=20)]
    deployed_ids = {d["strategy_id"] for d in deps}
    lines = ["Autopilot is %s." % ("ON" if user.get("autopilot") else "OFF"), "", "Deployments:"]
    for d in deps:
        oos = ((d.get("result") or {}).get("out_of_sample") or {})
        lines.append(
            "- deployment_id=%s \"%s\" market=%s mode=%s status=%s live: %s closed trades, %s wins, realized $%.2f, %s open; "
            "backtest unseen-data: pnl $%s over %s trades, max drawdown $%s; spec=%s"
            % (d["id"], d["title"], d["market"], d["mode"], d["status"], d["closed_trades"], d["wins"],
               float(d["realized_pnl"]), d["open_positions"], oos.get("pnl"), oos.get("trades"), oos.get("max_drawdown"),
               json.dumps(d["spec"], separators=(",", ":")))
        )
    if not deps:
        lines.append("- none")
    lines += ["", "Passed strategies not deployed:"]
    spare = [s for s in passed if s["id"] not in deployed_ids][:10]
    for s in spare:
        oos = ((s.get("result") or {}).get("out_of_sample") or {})
        lines.append("- strategy_id=%s \"%s\" market=%s unseen-data pnl $%s over %s trades"
                     % (s["id"], s["title"], s["market"], oos.get("pnl"), oos.get("trades")))
    if not spare:
        lines.append("- none")
    return "\n".join(lines)


ACTIONS_GUIDE = """Reply: {"reply": "<what you tell the user>", "actions": [ ... at most 3 ... ]}
Actions:
  {"type": "adjust", "deployment_id": N, "changes": {<partial spec, e.g. {"entry": {"min_edge": 0.08}}>}, "reason": "..."}
  {"type": "pause",  "deployment_id": N, "reason": "..."}
  {"type": "resume", "deployment_id": N, "reason": "..."}
  {"type": "deploy", "strategy_id": N, "reason": "..."}     (paper only)
Use actions only when you have a concrete reason; an empty list is often right.
""" + specmod.SPEC_GUIDE


def _copilot_check(obj: Dict) -> Dict:
    reply = str(obj.get("reply") or "").strip()
    actions = obj.get("actions") or []
    if not reply:
        raise ValueError("'reply' is required")
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS or not all(isinstance(a, dict) for a in actions):
        raise ValueError("'actions' must be a list of at most %d objects" % MAX_ACTIONS)
    return {"reply": reply[:4000], "actions": actions}


def run_copilot(conn, run: Dict, model: ModelFn = claude, dataset_fn=backtest.dataset) -> None:
    """kind='chat' answers the user's latest message; kind='review' is the
    agent checking in on its own (run.prompt says why)."""
    cur = conn.cursor()
    usage = Usage()
    user = repo.get_user(cur, run["user_id"])
    try:
        history = repo.chat_messages(cur, user["id"], limit=20)
        transcript = "\n".join("%s: %s" % (m["role"], m["content"]) for m in history)
        if run["kind"] == "review":
            task = "Scheduled check-in. Why: %s\nAssess the deployments and tell the user what you see." % run.get("prompt")
        else:
            task = "Answer the user's latest message."
        prompt = "%s\n\nRecent conversation:\n%s\n\n%s\n\n%s" % (_copilot_context(cur, user), transcript or "(none)", task, ACTIONS_GUIDE)
        out = ask_json(model, COPILOT_SYSTEM, [{"role": "user", "content": prompt}], _copilot_check, usage)
        repo.add_chat(cur, user["id"], "agent", out["reply"])
        for action in out["actions"]:
            text, proposal_id = act(cur, user, action, bool(user.get("autopilot")), dataset_fn)
            repo.add_chat(cur, user["id"], "system", text, proposal_id)
        repo.finish_run(cur, run["id"], "succeeded", None, 0, 0, usage.input_tokens, usage.output_tokens)
        _bill(conn, user["id"], usage, run["id"])
    except Exception as e:
        print("[agents] copilot run %s failed: %r" % (run["id"], e), flush=True)
        repo.add_chat(cur, user["id"], "system",
                      "The agent hit an error and didn't answer. Send your message again, or try in a minute.")
        repo.finish_run(cur, run["id"], "failed", str(e)[:2000], 0, 0, usage.input_tokens, usage.output_tokens)
        if not isinstance(e, LLMError):
            raise
