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
from app import dreaming
from app import exploration
from app import gatekeeper
from app import models_catalog as catalog
from app import partitions
from app import repository as repo
from app import research_repository as rr
from app import spec as specmod
from app.llm import LLMError, ModelFn, Usage, ask_json, claude, current_model
from app.markets import MARKETS
from app.agent_market_data import AgentMarketData, DataScope

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

DEFAULT_HYPOTHESES = 8    # when the user doesn't set a budget
MAX_BUDGET = 1000         # hard ceiling a user can request for one finite run (run-forever is uncapped)
# Batch width and finalist selection now live in app/exploration.py (the exploration policy).
MAX_ACTIONS = 3
MIN_FRAMES = 200
DREAM_EVERY_CHUNKS = max(1, int(os.getenv("TAU_DREAM_EVERY_CHUNKS", "2")))  # dream every N explore chunks in a forever run

RESEARCH_SYSTEM = """You are a quantitative researcher at a disciplined prediction-market
fund, trading Kalshi Bitcoin binary contracts (YES pays $1 if BTC settles above the strike,
priced 0-100c and read as a probability). You cannot write code: every idea is expressed as
a strategy spec our backtester runs. You are a SCIENTIST, not a backtest optimizer. Your job
is to find a durable, fee-surviving edge AND to say honestly when none is demonstrated.
"No reliable edge" is a correct, valuable result. You will be judged on whether your
STATISTICALLY-SUPPORTED strategies stay profitable on data you never saw - not on how many
you propose.

NON-NEGOTIABLE PRINCIPLES
- An ECONOMIC MECHANISM comes before any rule. State WHO is on the other side of your trade,
  WHY they trade against their own interest, WHY the edge is not already arbitraged away,
  WHO pays for it, WHEN it appears, and WHY it should PERSIST. No mechanism -> no hypothesis.
- Fees are brutal and state-dependent: Kalshi's taker fee is 0.07*price*(1-price) per
  contract, maximal (1.75c) at mid price. A thin edge on a 50c contract is dead on arrival.
  Prefer edges away from mid, or that trade rarely with conviction.
- The GBM-digital fair value you are given is, on this venue's history, slightly WORSE
  calibrated than simply trusting the Kalshi mid (log loss 0.403 vs 0.384). So an
  unconditional "the model says it's mispriced" edge is almost certainly a fee-and-noise
  artifact. Real edge is CONDITIONAL - a specific regime, microstructure state, or time.
- You will PRE-REGISTER each hypothesis before it is tested. You may NOT change the
  hypothesis to fit results you later see. You will not see validation or holdout numbers at
  all - only a classification label (promising / statistically-supported / inconclusive /
  rejected). Do not ask for the held-out numbers; the system will not give them.
- Few robust rules beat many fragile ones. 100 correlated BTC-momentum variants are worth
  less than one genuinely novel, uncorrelated idea.

KALSHI-BTC-SPECIFIC ANGLES WORTH A MECHANISM (not an exhaustive list)
- Settlement mechanics: the contract settles on a specific index at a specific instant.
  Mispricing of terminal pinning near the strike in the last minutes; the discreteness of
  1c ticks vs a continuous fair value.
- Microstructure: order-book imbalance and recent trade flow (available as features) can
  lead the mid for seconds-to-minutes; does the book systematically lag the Coinbase spot?
- Behavioral / flow: retail longshot bias (overpaying for cheap far-OTM "lottery" YES/NO),
  favorite-longshot distortion near 5c and 95c; round-number strike magnetism; US-open vs
  Asia-overnight participation shifts (hour-of-day regimes).
- Basis / funding: Kalshi's implied probability vs perp funding / spot-perp basis as a
  sentiment signal; BRTI-vs-Coinbase basis dislocations.
- Volatility: does the market systematically over- or under-price realized vol at specific
  horizons (e.g. the last 3-8 minutes of a 15-minute contract)?

NINE-PHASE METHOD (every hypothesis walks all nine)
  1. IDENTIFY a structural inefficiency - name the mechanism and the loser.
  2. FALSIFIABLE THEORY - a prediction precise enough to be wrong; state what result would
     DISPROVE it (your falsification_criteria).
  3. PRE-REGISTER - entry/exit/sizing spec, holding period, primary metric, null & alt
     hypotheses, planned test, min sample, cost assumptions. This is frozen.
  4. MINIMAL TEST - the smallest rule that could express the edge; no free parameters you
     cannot justify from the mechanism.
  5. VALIDATE WITHOUT SNOOPING - you test on the research window only; the gatekeeper tests
     on data you never see. Do not tune toward a label you got back.
  6. ROBUSTNESS - does it survive across sub-periods, nearby parameter values, and a doubling
     of assumed fees/slippage? Fragile-to-perturbation = probably a fluke.
  7. SEEK DISCONFIRMING EVIDENCE - propose the negative control / placebo (e.g. the same rule
     on shuffled labels or a random strike) that SHOULD fail; if it passes, your edge is an
     artifact.
  8. DECIDE - is there a mechanism, is it predictive out of sample, is it economically viable
     AFTER fees and given capacity? Any "no" -> say so plainly.
  9. LEDGER - everything above is recorded immutably, pass or fail.

OUTPUT (one JSON object only):
{"hypotheses": [{
   "title": "...",
   "thesis": "2-4 plain-English sentences a non-quant can follow, no jargon unglossed",
   "mechanism": {"who_pays": "...", "why_not_arbitraged": "...", "when": "...",
                 "why_persists": "..."},
   "falsification_criteria": "the result that would disprove this",
   "negative_control": "the placebo test that SHOULD fail",
   "null_hypothesis": "...", "alt_hypothesis": "...",
   "primary_metric": "mean_net_return_per_trade",
   "min_sample": <int>,
   "spec": { ...the strategy spec... }
}]}"""

CHALLENGER_SYSTEM = """You are a skeptical PM reviewing a researcher's PRE-REGISTERED
hypothesis BEFORE any data is spent on it. You defend the fund's limited statistical budget.
For each hypothesis decide one of:
 - APPROVE: the mechanism is economically coherent, the loser is named, the edge plausibly
   survives fees, and the test is falsifiable with a real negative control.
 - REVISE: the idea may hold but the stated test, min_sample, or costs are wrong - say how.
 - REJECT: no credible mechanism, the "edge" is a fee/noise artifact, the placebo would also
   pass, or it is a near-duplicate of an already-tested family (overfitting the search).
Be specific and brief. You cannot see validation/holdout data either. Reply one JSON object:
{"verdicts":[{"decision":"approve|revise|reject","reason":"...","fixes":{...optional spec
patch...}}]}"""

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
            # The §C pre-registration fields are OPTIONAL (older callers/tests send only
            # title/thesis/spec): the challenger and the gatekeeper's Prereg fall back to
            # sane defaults when a proposer omits them.
            out.append({
                "title": title[:120], "thesis": thesis[:1500], "spec": spec,
                "mechanism": h.get("mechanism") if isinstance(h.get("mechanism"), dict) else {},
                "falsification_criteria": str(h.get("falsification_criteria") or "")[:1000],
                "negative_control": str(h.get("negative_control") or "")[:1000],
                "null_hypothesis": str(h.get("null_hypothesis") or "")[:1000],
                "alt_hypothesis": str(h.get("alt_hypothesis") or "")[:1000],
                "primary_metric": str(h.get("primary_metric") or "mean_net_return_per_trade")[:48],
                "min_sample": int(h["min_sample"]) if isinstance(h.get("min_sample"), (int, float)) else 30,
            })
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
        # The generator learns ONLY from what it is allowed to see: the title, the
        # classification LABEL (the strategy status), and in-RESEARCH pnl/trades. It must NEVER
        # see a validation or holdout number — those are gatekeeper-held (closes Leak 2 of the
        # design: generation stays blind to the held-out evidence). No "unseen $..." term here.
        lines.append(
            "- [%s] %s: research $%s/%s trades"
            % (s["status"], s["title"], ins.get("pnl"), ins.get("trades"))
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

Propose {count} distinct hypotheses for this idea, each walking the nine-phase method.
Reply with the ONE JSON object specified in your instructions (the full "hypotheses" list with
mechanism, falsification_criteria, negative_control, null/alt hypotheses, min_sample and spec).""".format(
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


def dig_deeper_prompt(strat: Dict) -> str:
    """Turn a PASSED strategy into the idea prompt for a new research line that branches off it:
    keep its economic mechanism, but refine parameters, stress-test and extend the thesis. The
    full spec is carried as the explicit starting point. The branched variants still go through the
    normal gatekeeper — each is a NEW pre-registration (a different spec hashes differently), never
    a mutation of the frozen original."""
    spec = json.dumps(strat.get("spec") or {}, separators=(",", ":"))
    return (
        "Dig deeper on a strategy that already passed every gate: \"%s\".\n"
        "Its thesis: %s\n"
        "Its starting spec: %s\n\n"
        "Keep the SAME economic mechanism, but push it further: refine the parameters within that "
        "mechanism, stress-test it (nearby parameter values, sub-periods, doubled fees/slippage), "
        "and extend the thesis into adjacent conditional edges it implies. Propose distinct REFINED "
        "variants, each pre-registered as a new hypothesis in its own right — do not just resubmit "
        "the original." % (strat.get("title") or "it", (strat.get("thesis") or "").strip()[:800], spec)
    )


MAX_ACTIVE_RESEARCH = 2   # mirrors server.MAX_ACTIVE_RESEARCH (not imported, to avoid a cycle)


def dig_deeper_run(cur, user_id: int, strat: Dict, model: Optional[str] = None,
                   max_hypotheses: Optional[int] = None, run_forever: bool = False) -> int:
    """Create a QUEUED research run that branches off a PASSED strategy (the 'dig deeper' flow):
    same market/direction, a prompt seeded from its thesis + starting spec, and seed_strategy_id
    set so every branched strategy links back to it. A worker claims it like any research run; the
    refined variants go through the normal gatekeeper (no bypass). Shared by the server endpoint
    and the co-pilot's `research` action so both seed a run the same way."""
    return repo.create_run(
        cur, user_id, "research", strat["market"], strat.get("direction"),
        dig_deeper_prompt(strat), max_hypotheses=max_hypotheses, run_forever=run_forever,
        model=model, seed_strategy_id=strat["id"],
    )


def _in_sample_summary(ds: backtest.Dataset) -> Dict:
    """What the agent may know about the data: the in-sample window only."""
    s = ds.summary()
    s["end"] = s.pop("out_of_sample_from")
    s.pop("decision_points", None)
    return s


class Cancelled(Exception):
    pass


def _bill(conn, user_id, usage, run_id, model=None):
    """Meter the tokens this run spent against the user's credits, at the price of
    the model that actually ran (`model` is its invokable modelId)."""
    if usage.input_tokens or usage.output_tokens:
        billing.charge_usage(conn, user_id, model or current_model(), usage.input_tokens, usage.output_tokens, run_id)


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


def _challenger_check(n: int) -> Callable[[Dict], List[Dict]]:
    def check(obj: Dict) -> List[Dict]:
        vs = obj.get("verdicts")
        if not isinstance(vs, list) or len(vs) != n:
            raise ValueError("'verdicts' must be a list of exactly %d items, in order" % n)
        out: List[Dict] = []
        for i, v in enumerate(vs):
            if not isinstance(v, dict):
                raise ValueError("verdicts[%d] must be an object" % i)
            d = str(v.get("decision") or "").strip().lower()
            if d not in ("approve", "revise", "reject"):
                raise ValueError("verdicts[%d].decision must be approve, revise, or reject" % i)
            fixes = v.get("fixes")
            out.append({"decision": d, "reason": str(v.get("reason") or "")[:1000],
                        "fixes": fixes if isinstance(fixes, dict) else None})
        return out

    return check


def _challenge(finalists: List[Dict], run: Dict, model: ModelFn, usage: Usage, log) -> List[Dict]:
    """Role 2 — the Challenger: ONE skeptical LLM pass that APPROVE/REVISE/REJECTs each
    finalist's pre-registration BEFORE any statistical budget is spent (§C). Returns a list
    aligned to `finalists`. It can only make deployment harder — at worst it kills a finalist
    before a single validation test is spent. Fails OPEN (approve as-is) on any LLM error so a
    reviewer hiccup can't silently halt research; the gatekeeper remains the binding budget."""
    if not finalists:
        return []
    items = [{"title": t.get("title"), "thesis": t.get("thesis"),
              "mechanism": t.get("mechanism") or {},
              "falsification_criteria": t.get("falsification_criteria", ""),
              "negative_control": t.get("negative_control", ""),
              "spec": t["spec"]} for t in finalists]
    msg = ("Review these %d PRE-REGISTERED hypotheses for Kalshi %s before any statistical "
           "budget is spent on them.\n%s\n\nReply one JSON object with exactly %d verdicts in "
           "order: {\"verdicts\":[{\"decision\":\"approve|revise|reject\",\"reason\":\"...\","
           "\"fixes\":{optional partial spec patch}}]}"
           % (len(items), run["market"], json.dumps(items, separators=(",", ":")), len(items)))
    try:
        return ask_json(model, CHALLENGER_SYSTEM, [{"role": "user", "content": msg}],
                        _challenger_check(len(finalists)), usage)
    except LLMError as e:
        log("step", "Challenger unavailable (%s); approving finalists as-is — the gatekeeper still gates." % e)
        return [{"decision": "approve", "reason": "", "fixes": None} for _ in finalists]


def _result_block(dataset_summary: Dict, t: Dict, classification: str, reason: Optional[str] = None) -> Dict:
    """The strategy.result the generator persists: research-fold metrics + the classification
    LABEL only. It deliberately carries NO held-out (validation/holdout) numbers, because
    strategy_memory feeds this straight back into the next prompt (closes Leak 2)."""
    block = {"capital": t.get("capital"), "dataset": dataset_summary,
             "in_sample": t.get("in_sample"), "classification": classification}
    if reason:
        block["challenger_reason"] = reason[:500]
    return block


def _status_for(classification: str) -> str:
    """Map the gatekeeper's Classification enum onto the strategy row's status: REJECTED ->
    rejected, INCONCLUSIVE -> failed, STAT_SUPPORTED and better -> passed (§B.5)."""
    if classification == gatekeeper.Classification.REJECTED.value:
        return "rejected"
    if classification == gatekeeper.Classification.INCONCLUSIVE.value:
        return "failed"
    return "passed"


def _prereg(t: Dict, spec: Dict, run: Dict, partition: Dict, n_tests: int,
            verdict: Dict, strategy_id: int) -> gatekeeper.Prereg:
    """Build the immutable pre-registration from the proposer+challenger output. The mechanism,
    negative control and challenger reason are stored as structured JSON in economic_rationale
    (the research-paper page reads them back); the gatekeeper hashes spec+rationale as the
    experiment identity."""
    rationale = json.dumps({
        "thesis": t.get("thesis", ""),
        "mechanism": t.get("mechanism") or {},
        "negative_control": t.get("negative_control", ""),
        "challenger": verdict.get("reason", ""),
    }, separators=(",", ":"))
    return gatekeeper.Prereg(
        user_id=run["user_id"], run_id=run["id"], market=run["market"], spec=spec,
        economic_rationale=rationale,
        primary_metric=t.get("primary_metric") or "mean_net_return_per_trade",
        null_hypothesis=t.get("null_hypothesis", ""), alt_hypothesis=t.get("alt_hypothesis", ""),
        falsification_criteria=t.get("falsification_criteria", ""),
        min_sample=int(t.get("min_sample") or 30),
        cost_assumptions={"fee": "kalshi_taker", "fill": "ask/bid"},
        research_partition_id=int(partition.get("id") or 0),
        planned_n_tests=n_tests, correction_method="BH", strategy_id=strategy_id,
    )


def _gate_and_save(cur, run: Dict, ds: backtest.Dataset, partition: Dict, chunk: List[Dict], log,
                   policy: exploration.ExplorationPolicy, model: ModelFn, usage: Usage) -> int:
    """The HAND-OFF (§B.5 step 3): freeze the finalists, let the Challenger review them, then
    hand the approved ones to the Statistical Gatekeeper for validation. The generator never
    runs a backtest on validation data and only ever receives a classification LABEL back — the
    p-values/CIs/held-out pnl stay inside the gatekeeper. Returns the count classified as passed.
    Finalist selection (multiple-testing discipline) stays in the exploration policy; non-
    finalists are rejected exactly as before, untested."""
    user_id, run_id, market = run["user_id"], run["id"], run["market"]
    direction = run["direction"] or "custom"
    # Discovery-tree lineage: on a "dig deeper" run every branched strategy points back at the
    # passed strategy it refines, so the research tree records the branch (NULL on a fresh run).
    parent = run.get("seed_strategy_id")
    s = ds.summary()
    state = exploration.PolicyState(proposed=len(chunk), budget=len(chunk), round=0)
    finalists = policy.select_finalists(chunk, state)
    verdicts = _challenge(finalists, run, model, usage, log)
    log("step", "Froze %d finalist%s; the challenger reviewed each before any validation budget was spent."
        % (len(finalists), "" if len(finalists) == 1 else "s"))

    approved: List[Dict] = []
    exp_ids: List[int] = []
    payload: List[Dict] = []
    for t, verdict in zip(finalists, verdicts):
        spec = t["spec"]
        if verdict["decision"] == "revise" and verdict.get("fixes"):
            try:
                spec = specmod.validate(_deep_merge(spec, verdict["fixes"]))
            except specmod.SpecError:
                spec = t["spec"]  # keep the frozen original if the patch is invalid
        if verdict["decision"] == "reject":
            # Killed before testing. Recorded in the ledger (as a rejected strategy row with the
            # challenger's reason); NEVER pre-registered and NEVER validation-tested — the
            # statistical budget is untouched (§C).
            t["strategy_id"] = repo.insert_strategy(
                cur, user_id, run_id, parent, market, direction, t["title"], t["thesis"], spec,
                "rejected", _result_block(s, t, "challenger_rejected", verdict.get("reason")))
            log("verdict", "REJECTED (challenger) - %s: %s"
                % (t["title"], verdict.get("reason") or "no credible mechanism"),
                {"title": t["title"], "status": "rejected", "strategy_id": t["strategy_id"]})
            continue
        # Insert the strategy row FIRST (provisional) so the immutable experiment can carry its
        # strategy_id, then pre-register the frozen hypothesis.
        sid = repo.insert_strategy(cur, user_id, run_id, parent, market, direction, t["title"],
                                   t["thesis"], spec, "pending", _result_block(s, t, "promising"))
        t["strategy_id"] = sid
        exp_ids.append(gatekeeper.preregister(cur, _prereg(t, spec, run, partition, len(finalists), verdict, sid)))
        payload.append({"spec": spec, "user_id": user_id, "market": market,
                        "min_sample": int(t.get("min_sample") or 30)})
        approved.append(t)

    passed = 0
    if approved:
        val_ds = backtest.partition_dataset(market, partition, "validation")
        for t, outcome in zip(approved, gatekeeper.judge_batch(cur, run_id, exp_ids, payload, val_ds)):
            cls = outcome["classification"]
            status = _status_for(cls)
            passed += status == "passed"
            repo.set_strategy_outcome(cur, t["strategy_id"], status, _result_block(s, t, cls))
            log("verdict", "%s - %s: validation verdict is gatekeeper-held (classification=%s, "
                           "%s trades); the numbers never return to the generator."
                % (status.upper(), t["title"], cls, outcome.get("n_trades", 0)),
                {"title": t["title"], "status": status, "classification": cls,
                 "strategy_id": t["strategy_id"]})

    for t in chunk:
        if t in finalists:
            continue
        ins = t["in_sample"] or {}
        t["strategy_id"] = repo.insert_strategy(
            cur, user_id, run_id, parent, market, direction, t["title"], t["thesis"], t["spec"],
            "rejected", _result_block(s, t, "not_finalist"))
        log("verdict", "REJECTED - %s: not a finalist, so never tested on unseen data "
                       "(research pnl $%s over %s trades)." % (t["title"], ins.get("pnl"), ins.get("trades")),
            {"title": t["title"], "status": "rejected", "strategy_id": t["strategy_id"]})
    return passed


def _explore_and_gate(cur, run, ds, partition, memory, model, usage, log, checkpoint, budget, tried,
                      policy: exploration.ExplorationPolicy) -> Tuple[int, int]:
    """Explore NEW hypotheses on the Research partition (small refining rounds the policy
    sizes), then hand the finalists to the challenger + gatekeeper. Appends to the shared
    `tried` so progress survives a cancel/error."""
    market = run["market"]
    chunk: List[Dict] = []
    round_no = 0
    market_data = AgentMarketData(DataScope.research(ds.start_ts, ds.cutoff_ts), log, checkpoint)
    while True:
        checkpoint()
        round_no += 1
        state = exploration.PolicyState(proposed=len(chunk), budget=budget, round=round_no)
        want = policy.next_batch(state).width
        if want <= 0:
            break  # policy decided to stop proposing this chunk
        batch = market_data.ask(model, RESEARCH_SYSTEM,
                         [{"role": "user", "content": _round_prompt(run, ds, memory, want, chunk)}],
                         _hypotheses_check(market, want), usage)
        if not batch:
            break  # agent is out of fresh ideas this chunk
        for h in batch:
            checkpoint()
            t = _test_in_sample(h, ds, partition, log, round_no)
            t["score"] = backtest.score(t["in_sample"])  # attach once, so the policy needs no backtester
            chunk.append(t)
            tried.append(t)
    return len(chunk), _gate_and_save(cur, run, ds, partition, chunk, log, policy, model, usage)


def run_research(
    conn,
    run: Dict,
    model: Optional[ModelFn] = None,
    dataset_fn: Optional[Callable[..., backtest.Dataset]] = None,
) -> None:
    cur = conn.cursor()
    usage = Usage()
    tried: List[Dict] = []
    run_id, user_id, market = run["id"], run["user_id"], run["market"]
    # The user's chosen model (NULL = default Sonnet) drives every LLM call this
    # run makes and the price it's billed at. Tests pass their own `model`.
    choice = catalog.resolve(run.get("model"))
    if model is None:
        model = lambda system, messages: claude(system, messages, choice.model_id)  # noqa: E731
    # Tau-RSI: use the user's self-evolved exploration policy (sandboxed), or the
    # default if they have none yet. A new run then dreams up a better one (below).
    policy = dreaming.current_policy(cur, user_id)

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
        # Freeze the Research/Validation/Holdout split once for the run; the generator may load
        # ONLY the Research window (partitions.research_dataset), and the gatekeeper keeps the
        # validation/holdout keys. Tests inject dataset_fn to supply a synthetic research set.
        partition = partitions.ensure_partition(cur, market)
        load = dataset_fn or (lambda mk, hd=None: partitions.research_dataset(mk, partition, hd))
        ds = load(market)  # full available window first — confirms data before any model spend
        if len(ds.frames) < MIN_FRAMES:
            raise LLMError("Not enough market history collected yet for %s." % MARKETS[market].label)
        # The agent picks the window that fits its thesis; re-load the narrower slice if it
        # chose less, and keep the fuller one if the slice is too thin to be worth it.
        checkpoint()  # a cancel must stop before we spend a model call on planning
        lookback = _plan_lookback(run, market, model, usage, log)
        if lookback < MARKETS[market].history_days:
            narrowed = load(market, lookback)
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

        total_passed, tot_in, tot_out, chunks = 0, 0, 0, 0
        while True:
            checkpoint()
            # Reload memory each chunk so a run_forever loop learns from the strategies it
            # just saved, instead of re-proposing the same ideas.
            memory = repo.strategy_memory(cur, user_id, market)
            n, passed = _explore_and_gate(cur, run, ds, partition, memory, model, usage, log, checkpoint, budget, tried, policy)
            total_passed += passed
            chunks += 1
            # Tau-RSI: dream periodically DURING a long session (not only at the end), so the
            # agent self-improves as its history grows — and the evolved policy drives the very
            # next chunk. Billed with the chunk below; a hiccup never fails the run.
            if forever and n > 0 and chunks % DREAM_EVERY_CHUNKS == 0:
                try:
                    if dreaming.evolve_policy(conn, user_id, market, model, usage, log):
                        policy = dreaming.current_policy(cur, user_id)  # explore smarter from here on
                except Exception as e:
                    log("step", "Dreaming hiccup (kept current policy): %s" % e)
            # Meter per chunk: a run_forever session may never "finish", so bill as it goes
            # (and reset the counter) instead of only at the end — otherwise its tokens are free.
            tot_in += usage.input_tokens
            tot_out += usage.output_tokens
            _bill(conn, user_id, usage, run_id, choice.model_id)
            usage.input_tokens = usage.output_tokens = 0
            repo.update_run_progress(cur, run_id, len(tried), total_passed)  # keep counts live
            conn.commit()
            if n == 0 or not forever:
                break
            # True no-stop: a run_forever session runs until the user cancels — the only automatic
            # stop is running out of money (auto-reload, if on, already ran inside the billing above).
            if repo.credit_balance(cur, user_id) <= 0:
                log("step", "Paused — out of credits. Add more (or turn on auto-reload) and start a new "
                            "session to keep researching.")
                break
            log("step", "Still running - %d tested so far, %d passed. Exploring more (stop anytime)."
                % (len(tried), total_passed))

        # Dreaming: learn a better exploration policy from the user's accumulated
        # history, validated on the replay simulator (no new backtests). Bill its
        # tokens; never let a dreaming hiccup fail the run.
        try:
            if dreaming.evolve_policy(conn, user_id, market, model, usage, log):
                tot_in += usage.input_tokens
                tot_out += usage.output_tokens
                _bill(conn, user_id, usage, run_id, choice.model_id)
                usage.input_tokens = usage.output_tokens = 0
                conn.commit()
        except Exception as e:  # dreaming is best-effort; the run still succeeds
            log("step", "Policy-evolution step skipped (%s)." % e)

        log("done", "%d of %d hypotheses passed every gate." % (total_passed, len(tried)),
            {"passed": total_passed, "tried": len(tried)})
        repo.finish_run(cur, run_id, "succeeded", None, len(tried), total_passed, tot_in, tot_out)
    except Cancelled:
        _bill(conn, user_id, usage, run_id, choice.model_id)  # charge whatever was spent before the stop
        log("step", "Cancelled.")
    except Exception as e:  # the run fails visibly; the worker keeps going
        msg = str(e) if isinstance(e, LLMError) else "Unexpected error: %s" % e
        log("error", msg)
        repo.finish_run(cur, run_id, "failed", msg[:2000], len(tried), 0, usage.input_tokens, usage.output_tokens)
        _bill(conn, user_id, usage, run_id, choice.model_id)
        if not isinstance(e, LLMError):
            raise


def _span_words(ds: backtest.Dataset) -> str:
    days = (ds.end_ts - ds.start_ts) / 86400.0
    return "%d days" % round(days)


def _test_in_sample(h: Dict, ds: backtest.Dataset, partition: Dict, log, round_no: int) -> Dict:
    # The in-research "OOS" the agent iterates on is a PURGED walk-forward research fold (fully
    # inside Research) — a leak-free sandbox it may look at freely, not the held-out validation
    # window. Purge/embargo come from the frozen partition's contract-duration horizon (§B.5).
    res = backtest.research_fold_metrics(h["spec"], ds, int(partition["embargo_seconds"]))
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


def live_autopilot_ok(cur, user: Dict) -> Tuple[bool, str]:
    """ALL gates that must hold before autopilot may touch live money. Returns (allowed, why_not).
    Keeping this in one place means no caller can go live by skipping a check."""
    from app import engine  # local import keeps module load order simple
    if not user.get("autopilot"):
        return False, "autopilot is off"
    if not user.get("autopilot_live"):
        return False, "live autopilot is off"
    if not engine.LIVE_TRADING_ENABLED:
        return False, "live trading is not enabled on this server"
    if repo.get_kalshi_key(cur, user["id"]) is None:
        return False, "no Kalshi key is connected"
    from datetime import datetime, timezone
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    if repo.realized_pnl(cur, user["id"], "live", day_start) <= -float(user.get("autopilot_daily_loss_limit") or 50):
        return False, "today's live loss hit your daily limit"
    return True, ""


MIN_PAPER_TRADES_FOR_LIVE = 8


def _proven_on_paper(cur, user_id: int, strategy_id: int) -> Tuple[bool, str]:
    """Enforce the research -> PAPER -> live loop in code: a strategy may go live only after it has
    actually run on paper with enough closed trades and hasn't lost money there. Backs the model's
    'proven on paper' judgment with a hard rule so autopilot can't jump a fresh pass straight to real money."""
    paper = [d for d in repo.list_deployments(cur, user_id, include_stopped=True)
             if d["strategy_id"] == strategy_id and d["mode"] == "paper"]
    trades = sum(int(d.get("closed_trades") or 0) for d in paper)
    realized = sum(float(d.get("realized_pnl") or 0) for d in paper)
    if trades < MIN_PAPER_TRADES_FOR_LIVE:
        return False, "it needs %d+ closed paper trades first (has %d)" % (MIN_PAPER_TRADES_FOR_LIVE, trades)
    if realized < 0:
        return False, "it's still down $%.2f on paper" % (-realized)
    return True, ""


def _is_deployment_candidate(cur, strategy_id: int) -> bool:
    """True only if the Statistical Gatekeeper promoted this strategy's experiment all the way
    to DEPLOYMENT_CANDIDATE (validation-supported -> one-time holdout forward-validated ->
    marginal-contribution OK). The deploy path requires this IN ADDITION to every existing
    gate (§E.5): a purely additive check that can only make deployment harder, never easier."""
    rec = rr.experiments_for_strategy(cur, strategy_id)
    if not rec:
        return False
    return any(r.get("classification") == gatekeeper.Classification.DEPLOYMENT_CANDIDATE.value
               for r in rec.get("results", []))


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
        # Additive gatekeeper gate (§E.5): never weakens the existing check above.
        if not _is_deployment_candidate(cur, strat["id"]):
            return ("I can't deploy %s yet — the gatekeeper hasn't cleared it as a deployment "
                    "candidate (it must pass validation, the one-time holdout, and the "
                    "diversification check first)." % strat["title"], None)
        pid = repo.create_proposal(cur, user_id, "deploy", reason, None, strat["id"], "applied" if autopilot else "pending")
        if autopilot:
            repo.create_deployment(cur, user_id, strat["id"], strat["market"], "paper")
            return "Autopilot deployed %s on paper." % strat["title"], pid
        return "Proposed deploying %s on paper." % strat["title"], pid
    if kind == "deploy_live":
        strat = repo.get_strategy(cur, user_id, int(action.get("strategy_id") or 0))
        if strat is None or strat["status"] != "passed":
            return "Only strategies that passed their backtest can go live.", None
        # Additive gatekeeper gate (§E.5): required ON TOP OF the YES-side, live_autopilot_ok
        # and _proven_on_paper checks below — none of which are removed, reordered or weakened.
        if not _is_deployment_candidate(cur, strat["id"]):
            return ("I can't take %s live — the gatekeeper hasn't cleared it as a deployment "
                    "candidate (holdout forward-validation + diversification), so it stays on "
                    "paper." % strat["title"], None)
        if (strat["spec"].get("side") or "").lower() != "yes":
            return "Live supports YES-side strategies only, so I kept %s on paper." % strat["title"], None
        ok, why = live_autopilot_ok(cur, user)
        if not (autopilot and ok):
            # Gate failed: never go live silently — stays on paper (safeguard 2).
            return "I can't move %s to live (%s); it stays on paper until live autopilot is enabled." % (strat["title"], why or "live autopilot is off"), None
        proven, pwhy = _proven_on_paper(cur, user_id, strat["id"])
        if not proven:
            # research -> PAPER -> live: must prove on paper before real money.
            return "I'm keeping %s on paper a while longer — %s." % (strat["title"], pwhy), None
        # Deploy to live WITHIN the user's own caps. create_deployment copies the strategy's spec
        # sizing (stake x max_positions = the book cap); the engine enforces max_positions, per-trade
        # stake, YES-only, per-user key and the loss guard. Autopilot cannot raise any of these.
        cap = float(strat["spec"]["sizing"]["stake"]) * int(strat["spec"]["sizing"]["max_positions"])
        pid = repo.create_proposal(cur, user_id, "deploy", reason, None, strat["id"], "applied")
        repo.create_deployment(cur, user_id, strat["id"], strat["market"], "live")
        return ("Autopilot deployed %s to LIVE within your $%.0f cap (YES-only, your own Kalshi key, loss guard on)."
                % (strat["title"], cap)), pid
    if kind == "research":
        # "Dig deeper": branch a NEW research line off a passed strategy. No money and no proposal —
        # the user asked for it in chat — but it spends model credits, so honour the same
        # active-research cap the Research page enforces, and only ever branch a strategy that passed.
        strat = repo.get_strategy(cur, user_id, int(action.get("strategy_id") or 0))
        if strat is None or strat["status"] != "passed":
            return "I can only dig deeper on a strategy that already passed its backtest.", None
        if repo.count_runs(cur, user_id, "research", active_only=True) >= MAX_ACTIVE_RESEARCH:
            return "You already have a couple of research sessions running — let one finish and I'll dig deeper then.", None
        dig_deeper_run(cur, user_id, strat)
        return ("Started a new research session digging deeper into “%s”: I'll refine and "
                "stress-test its mechanism, and every variant still has to pass the same gates. "
                "Follow it on the Research page." % strat["title"], None)
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
  {"type": "research", "strategy_id": N, "reason": "..."}     (DIG DEEPER: start a new research session that branches off a strategy the user already PASSED — refine its parameters, stress-test it, extend the thesis. Use this whenever the user wants to explore, refine, improve, or build further on a passed strategy, instead of letting it be a dead end. Each refined variant still has to pass the gates. It is NOT a deployment; it just queues research.)
  {"type": "deploy", "strategy_id": N, "reason": "..."}       (paper)
  {"type": "deploy_live", "strategy_id": N, "reason": "..."}  (REAL money; only a YES-side strategy that already proved itself on PAPER, and only when the user turned on live autopilot. If live autopilot is off or any safety gate fails it is refused and stays on paper. Never the first step for a new idea: research -> paper -> live.)
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
        market_data = AgentMarketData(DataScope(), lambda kind, message, data=None:
                                     repo.add_event(cur, run["id"], kind, message, data))
        out = market_data.ask(model, COPILOT_SYSTEM, [{"role": "user", "content": prompt}], _copilot_check, usage)
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
