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
import logging
import math
import os
import re
import threading
import time
from contextlib import contextmanager
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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
from app import stats
from app.llm import LLMError, ModelFn, Usage, ask_json, claude, current_model
from app.markets import MARKETS
from app.services import markets as market_service
from app.services import research_memory
from app.services import research_leads
from app.services import research_screen
from app.agent_market_data import AgentMarketData, DataScope
from app.agent_knowledge import AgentKnowledge
from app.agent_news import AgentNews

_LOG = logging.getLogger(__name__)

DIRECTIONS: Dict[str, Dict[str, str]] = {
    "volatility": {
        "label": "Volatility mispricing",
        "brief": "Does the market over- or under-price how far the underlying can move before settlement?",
    },
    "momentum": {"label": "Momentum", "brief": "Do recent moves in the underlying keep going into settlement?"},
    "mean_reversion": {"label": "Mean reversion", "brief": "Do sharp moves snap back before settlement?"},
    "near_expiry": {"label": "Near expiry", "brief": "Are contracts mispriced in the last minutes before settlement?"},
    "longshots": {
        "label": "Favorites & longshots",
        "brief": "Are very cheap or very expensive contracts systematically mispriced?",
    },
    "time_of_day": {"label": "Time of day", "brief": "Do edges depend on the hour (US open, overnight, Asia)?"},
    "open": {"label": "Agent's choice", "brief": "Pick the most promising angle yourself and say why."},
}

# A SEED PALETTE of strategy angles — NOT a closed menu and NOT a checklist to fill. Its only jobs
# are to break the "buy when feature > X" default and to show that most angles map to a learned/
# statistical model, not a cutoff. The proposer is explicitly told it may (and should) invent angles
# that AREN'T here — a well-motivated mechanism off this list is worth MORE, not less. Learned/ML is
# a DIMENSION that crosses every row (any angle can be expressed as a fitted model), not a single row.
# Single source of truth: rendered into RESEARCH_SYSTEM + every proposer prompt, asserted by
# test_proposer_explores_diverse_families. Add rows freely; never let the prompt imply it's exhaustive.
STRATEGY_FAMILIES = (
    ("Momentum / trend", "underlying keeps moving into settlement — GBM model with drift_beta>0 "
                         "(drift_window 5/15/60), or a code momentum estimator"),
    ("Mean reversion", "sharp moves snap back before settlement — GBM model with drift_beta<0, or a "
                       "code reversion estimator"),
    ("Volatility / regime", "the market mis-prices realised vol — GBM vol_scale/vol_window conditioned "
                            "on a vol_15m/vol_60m band, or a GARCH forecast (arch) in `code`"),
    ("Calibration / favorite-longshot", "a documented price-level bias (cheap longshots overpriced, "
                                        "favorites underpriced) — model.kind=\"calibration\" on a price band"),
    ("Microstructure / order-flow", "order-book imbalance & trade flow lead the mid — "
                                    "model.kind=\"logistic\" over flow features, or a code classifier"),
    ("Cross-market relative value", "a RELATIVE mispricing between legs — the `cross` block "
                                    "(cross_sectional / cross_strike / calendar), not a directional view"),
    ("Event-driven / near-expiry", "terminal pinning and tick discreteness in the last minutes — "
                                   "min_tte/max_tte filters plus the settlement mechanism"),
    ("Seasonality / time-of-day", "edge concentrates in a session (US open, overnight, Asia) — "
                                  "hour_et regime filters, with a participation-shift mechanism"),
    ("News / event reaction", "a scheduled or breaking event moves the underlying before the mid "
                              "re-prices — news features (the news tool) as inputs to a `code`/logistic model"),
    ("Liquidity / spread capture", "earn the bid-ask by providing where flow is balanced, conditioned "
                                   "on book depth/spread state — a code rule over microstructure features"),
    ("Cross-asset basis / funding", "spot-perp basis, perp funding, or a correlated asset leads the "
                                    "Kalshi implied probability — those as features in a `code`/logistic model"),
    ("Ensemble / meta-model", "combine several weak, uncorrelated sub-signals into one fitted model — "
                              "a stacked/averaged estimator in `code` + fit(), judged on its net edge"),
    ("Learned / statistical (open)", "ANY model your mechanism needs — `code` + fit(window): "
                                     "ridge/tree/forest/GBM/kernel/quantile/NN estimators (scikit-learn, "
                                     "statsmodels, arch, numpy), engineered features, ensembles — your choice"),
)


def _family_menu() -> str:
    return "\n".join(" - %s: %s." % (name, how) for name, how in STRATEGY_FAMILIES)


DEFAULT_HYPOTHESES = 8    # when the user doesn't set a budget
MAX_BUDGET = 1000         # hard ceiling a user can request for one finite run (run-forever is uncapped)
# Batch width and finalist selection now live in app/exploration.py (the exploration policy).
MAX_ACTIONS = 3
MIN_FRAMES = 200
DREAM_EVERY_CHUNKS = max(1, int(os.getenv("TAU_DREAM_EVERY_CHUNKS", "2")))  # dream every N explore chunks in a forever run
# Cross-run dream cadence: the Dream-RSI tree is built from the user's ACCUMULATED validation
# history, so a 1-chunk autopilot run can dream usefully too — but dreaming on every single
# completion is wasteful. Dream when they've never dreamed, or every N research runs since the
# last dream (see _should_dream). Decouples dreaming from the within-run DREAM_EVERY_CHUNKS gate.
DREAM_EVERY_RUNS = max(1, int(os.getenv("TAU_DREAM_EVERY_RUNS", "3")))
# Fail-fast ceiling for the startup dataset load (history query + in-memory Dataset build). The
# load runs before the first heartbeat/event, so a wedged query or a pathological build used to
# sit silent until the 20-min watchdog; this bounds it to minutes with a CLEAR error instead.
# 300s, not 180s: btc15m's history alone took 127s with one other load running (2026-10-25), so
# two concurrent loads timed out a healthy run (2858) on the focus market.
DATA_LOAD_TIMEOUT = max(30, int(os.getenv("TAU_DATA_LOAD_TIMEOUT", "300")))
# Pillar 2 — per-thesis DEPTH: how many research-fold steps the agent may spend developing ONE
# thesis (explore -> backtest -> read prior failures -> critique -> refine) BEFORE it commits the
# single frozen spec that becomes exactly one candidate (= one pre-registration). 1 = legacy
# one-shot; prod default is deep (20) so the agent takes as long as a thesis needs. The real bound
# is the per-step CREDIT gate, not the cap — the loop reads the RESEARCH FOLD only, so a deeper
# thesis never touches held-out data, never inflates the trial count, and stays bounded by spend.
THESIS_MAX_STEPS = max(1, int(os.getenv("TAU_THESIS_MAX_STEPS", "20")))

# Uniform anti-stuck: a per-run background beater keeps the DB heartbeat fresh every
# RUN_HEARTBEAT_EVERY seconds through any legitimately long SILENT phase (a big backtest, one model
# call) so the tightened watchdog (worker.ABANDONED_AFTER) never false-kills a working run — but
# only while the MAIN thread showed progress within RUN_STALL_SECONDS, so a genuinely frozen run
# stops being beaten and IS reaped. Together they bound time-to-kill a wedged run to about
# RUN_STALL_SECONDS + ABANDONED_AFTER regardless of WHERE it froze (load, model, backtest). Env-tunable.
RUN_HEARTBEAT_EVERY = max(5, int(os.getenv("TAU_RUN_HEARTBEAT_EVERY", "15")))
RUN_STALL_SECONDS = max(30, int(os.getenv("TAU_RUN_STALL_SECONDS", "150")))
# A model call is not a frozen main thread: it is bounded by its own timeouts (stream stall guard,
# read_timeout, retries) and a non-streaming one (a throttle/daily-quota fallback) is legitimately
# silent for minutes. Proposals went 240-310s without a token and the run was reaped mid-call while
# healthy, so a call in flight counts as progress for up to this long.
MODEL_CALL_GRACE_SECONDS = max(60, int(os.getenv("TAU_MODEL_CALL_GRACE_SECONDS", "900")))
# Same for one research-fold test: a pooled code strategy loads a merged multi-market window and runs
# the sandbox (fit + signals, each wall-killed at 120s) over it, silent for minutes. Prod run 2908 was
# reaped at its resume cap mid-backtest on 2026-10-25 while healthy. Keyed by run id (see _busy).
BACKTEST_GRACE_SECONDS = max(60, int(os.getenv("TAU_BACKTEST_GRACE_SECONDS", "600")))
_BUSY_UNTIL: Dict[int, float] = {}
# The slot-freeing guard is the ATTEMPT bound below (work done), NOT a wall clock: a research session
# has no time limit — a long run that keeps making progress is fine, and being stopped is never a
# "failure" (see the `stopped` terminal status), so there is deliberately no RUN_MAX_SECONDS here.
# Root-cause backstop for the unbounded proposing loop: it stops on survivors reaching `budget`, but
# an all-abandon market never adds a survivor, so cap theses ATTEMPTED (developed, not just kept) at
# this multiple of budget. A healthy market hits the survivor cap long before this; only a doomed
# surface trips it, failing fast instead of spinning. Env-tunable.
EXPLORE_ATTEMPT_MULT = max(1, int(os.getenv("TAU_EXPLORE_ATTEMPT_MULT", "4")))
# Spend backstop under the attempt cap: stop proposing once this many developed theses IN A ROW were
# dropped on the research fold. Each drop is several Opus calls, and a market that has rejected the
# last N ideas (with the drops fed back into every prompt) rarely yields the N+1th; measured runs
# 2541 (btc15m) and 2548 (high_ny) dropped 28 and 18 in a row for ~$10 each with nothing gated.
# Survivors already kept still go to the gate. 0 disables. Env-tunable.
EXPLORE_MAX_DROP_STREAK = max(0, int(os.getenv("TAU_EXPLORE_MAX_DROP_STREAK", "8")))
# Bounded in-place retry for a TRANSIENT RDS drop during a data load (read-only, idempotent, its own
# connection). Absorbs a blip without the retry-storm risk of re-queuing the whole run. Env-tunable.
LOAD_RETRIES = max(0, int(os.getenv("TAU_LOAD_RETRIES", "2")))
LOAD_RETRY_BACKOFF = max(0.1, float(os.getenv("TAU_LOAD_RETRY_BACKOFF", "1.5")))

RESEARCH_SYSTEM = """You are a quantitative researcher at a disciplined prediction-market
fund, trading Kalshi binary contracts (YES pays $1 if the event settles, NO pays $1 if it does
not, priced 0-100c and read as a probability of the event). The SPECIFIC market you are
researching - what its contracts settle on, how settlement works, which signals matter - is
described in the user message under "Market profile"; read it and build for THAT market, not for
any other. Every idea is expressed as a strategy spec our backtester runs - and the spec language
is richer than a threshold rule: you can propose a LEARNED model (a logistic score fit on the
research data, or a favorite-longshot recalibration of the market's own price) as well as the
house GBM model (for strike-vs-underlying markets), and for anything those cannot express you may
write an arbitrary pure-Python/ML strategy (the `code` field). You are a SCIENTIST, not
a backtest optimizer. Your job is to find a durable, fee-surviving edge AND to say honestly when
none is demonstrated. "No reliable edge" is a correct, valuable result. You will be judged on
whether your STATISTICALLY-SUPPORTED strategies stay profitable on data you never saw - not on
how many you propose.

HOW TO EXPLORE — AN OPEN SEED PALETTE, NOT A CLOSED MENU
A spec is NOT just "buy when feature > X", and ten "buy when feature > X" variants are ONE idea,
not ten. The list below is a SEED PALETTE to spark breadth — it is NOT exhaustive and NOT a
checklist to tick off. You are EXPECTED to invent approaches that are not listed: a well-motivated
mechanism we never named is worth MORE, not less. Every intellectual lens is welcome as long as it
rests on a real, falsifiable mechanism:
  - an ECONOMIC / structural thesis — who supplies the mispricing, why they trade against their own
    interest, why it is not arbitraged away, and why it should PERSIST;
  - an ACADEMIC, literature-grounded idea — replicate or extend a documented market anomaly or a
    published method, and name it;
  - a TRADITIONAL / hardcore STATISTICAL or econometric method — classical time-series (ARIMA/GARCH/
    VAR), hypothesis tests, cointegration / error-correction, regime-switching (Markov), extreme-value
    theory, Bayesian inference — NOT only machine learning;
  - a modern MACHINE-LEARNING model;
  - or any combination of the above.
Each batch should SPAN genuinely different mechanisms and model structures rather than drilling one.
Pick the structure that matches YOUR mechanism — most mechanisms are not a single threshold:
""" + _family_menu() + """

LEARNED / STATISTICAL MODELS ARE FIRST-CLASS — classical statistics AND machine learning, your
choice of method; these exist precisely so your ideas need not be if-else rules:
 - model.kind="logistic" (name 1-6 `features`): a real classifier P(YES)=sigmoid(w.features)
   whose weights the system FITS on the research fold and FREEZES. The classic ML entry point and
   the natural home for a microstructure/order-flow model (ob_imbalance, trade flow, quote
   changes). Name only features your mechanism predicts matter — each coefficient raises the bar.
 - model.kind="calibration": the system fits a 1-parameter recalibration of the Kalshi mid on
   research (favorite-longshot, Bürgi-Deng-Whelan); pair it with a price-band + side.
 - `code` + fit(window): ANY pure-Python/stat/ML method the two kinds above cannot express — a
   classical econometric model (statsmodels OLS/GLS/logit/probit, ARIMA/SARIMAX/VAR, a GARCH/EGARCH
   vol forecast via arch, a Markov regime switch, a cointegration / error-correction or Kalman
   filter, an extreme-value or Bayesian estimator) OR a machine-learning model (ridge/tree/forest/
   gradient-boosted/kernel/quantile/NN via scikit-learn), an ensemble, engineered features. Extra
   libraries are installed for this: hmmlearn/ruptures (regime-switching & change-point), choix
   (Bradley-Terry / pairwise, for game outcomes), linearmodels (panel/IV/fixed-effects), pmdarima
   (auto-ARIMA), networkx (cross-market/correlation graphs). Classical hardcore statistics is as
   welcome as ML — reach for whichever your mechanism actually calls for.
   fit() TRAINS ONCE on the research fold and its params are FROZEN into the pre-registered spec;
   signals() rebuilds
   from those frozen params and PREDICTS. NEVER fit inside signals() on the window you are handed —
   at validation that window IS the held-out data, so fitting there is a leak. Fit in fit();
   predict in signals(). (The house GBM drift_window/drift_beta still expresses momentum/reversion
   directly — use it for those rather than a return threshold.)
A learned model is pre-registered WITH its frozen coefficients and judged on data you never see,
exactly like any other spec. More free parameters = a strictly higher deflated-Sharpe bar, so a
kitchen-sink model with no per-feature mechanism will be REJECTED, not rewarded.

NON-NEGOTIABLE PRINCIPLES
- An ECONOMIC MECHANISM comes before any rule. State WHO is on the other side of your trade,
  WHY they trade against their own interest, WHY the edge is not already arbitraged away,
  WHO pays for it, WHEN it appears, and WHY it should PERSIST. No mechanism -> no hypothesis.
- Fees are brutal and state-dependent: Kalshi's taker fee is 0.07*price*(1-price) per
  contract, maximal (1.75c) at mid price. A thin edge on a 50c contract is dead on arrival.
  Prefer edges away from mid, or that trade rarely with conviction.
- The market's own mid is a STRONG baseline. Any "fair value" you compute (a model price, a
  recalibration) has to beat the mid out of sample, and on this venue an unconditional "the model
  says it's mispriced" edge is almost certainly a fee-and-noise artifact. Real edge is CONDITIONAL
  - a specific regime, microstructure state, or time. (The Market profile notes how well the house
  model is calibrated on THIS market, when that is known.)
- You will PRE-REGISTER each hypothesis before it is tested. You may NOT change the
  hypothesis to fit results you later see. You will not see validation or holdout numbers at
  all - only a classification label (promising / statistically-supported / inconclusive /
  rejected). Do not ask for the held-out numbers; the system will not give them.
- Few robust rules beat many fragile ones. 100 correlated variants of one momentum rule are
  worth less than one genuinely novel, uncorrelated idea.

MARKET-SPECIFIC ANGLES: the "Market profile" block in the user message lists the settlement
mechanics and the angles that actually apply to THIS market (its underlying if any, which
features it populates, the behavioral/microstructure/seasonal effects that fit it). Ground your
mechanism in that profile — do not reach for signals the profile says this market does not have.

CROSS-CONTRACT RELATIVE VALUE (optional — single-contract is the default)
Most edges are single-contract. But when the mechanism is a RELATIVE mispricing between two
legs, you MAY propose a relative-value PAIR via the spec's `cross` block (shape in the spec
guide): it buys YES on the leg the model says is underpriced and NO on the overpriced leg,
holding both to settlement, so it profits on the spread rather than a directional view. Only
propose one with a real relative mechanism and name it:
  - cross_sectional: two DIFFERENT markets (e.g. a BTC-vs-ETH basis dislocation — one coin's
    ladder lags the other's move). Add the other market as a leg; records BOTH markets.
  - cross_strike: two strikes of the SAME event (the ladder's implied-probability shape is
    locally inconsistent — adjacent strikes misprice relative to each other).
  - calendar: the SAME strike across two settlements (near vs far expiry mispriced relative).
A pair spends from ONE shared statistical budget across its legs and still walks all nine phases
with its own falsifiable spread mechanism and negative control. Prefer a single-contract rule
unless the relative structure is the actual source of edge.

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

COPILOT_SYSTEM = """You are the trading co-pilot inside Tau. You manage the whole trading
operation for the user — not just pausing things — and talk with them in plain, brief English
(no jargon without a gloss). Within hard safety bounds you MAY, through structured actions:
  - research anything: start a fresh research line on any market, or dig deeper on a passed
    strategy. Both run the SAME RSI pipeline (pre-registration, gatekeeper, one-time holdout) —
    you have the same freedom a manual research run has.
  - tune a deployment's strategy/model parameters (the `adjust` action edits the spec; the host
    re-backtests it and keeps it only if it still passes every gate).
  - tune the user's RISK controls (drawdown limit, max open positions, max open notional) and the
    live EXECUTION controls (book participation, entry spread, per-order notional). You can only
    set these WITHIN a safe envelope — the host CLAMPS every value, so you can tighten freely but
    can never disable a stop, exceed a cap, or loosen past a safe maximum.
  - deploy a proven paper strategy of ANY side (YES or NO) to paper, or to real money once it has
    proved itself on paper and the user has turned on live autopilot.
You can NEVER flip the live-trading switch, bypass a deploy/live/risk gate, or weaken the loss
budget — those are fixed. Be honest about uncertainty and small samples: a handful of live trades
proves little either way. Never promise profit.
TRUST THE LIVE STATE in the context below over anything you said in earlier messages — your prior
replies are STALE. If the context says 0 research runs are active, research is NOT running (any
threads you mentioned before have FINISHED — see their outcomes in 'Recent research lines'); never
tell the user research is 'still running' or to 'be patient and wait' when nothing is actually
running. With an empty deck (no deployments and no active research), waiting is a FAILURE — launch
research this turn. Reply with ONE JSON object only.

Your north star is DURABLE, NET-OF-FEE, STATISTICALLY-VALIDATED profit on REAL money — not a full
pipeline, not a busy feed, not a strategy that merely passed once. Fees are a hard, state-dependent
hurdle (worst near 50c); an edge that doesn't clear them net is not an edge. Treat a deployment that
is bleeding, flat after enough trades, or decaying vs its backtest as a dead end: tune it, or pause
it and move the capital to a better idea — do not let a loser ride. Be your own harshest skeptic
about overfitting: the gatekeeper's held-out numbers are the only truth, so never talk yourself into
an idea the gates didn't clear, and never shade a result to look better than it is. Finding "nothing
worth trading right now" is a valid, honest outcome."""


# -- research ------------------------------------------------------------------


# The proposer generates every hypothesis in one multi-minute LLM call. Without streaming the
# feed sits silent at "Researching…" the whole time. We ask the model to THINK OUT LOUD in prose
# first (its intuition / mechanism, the way a quant reasons at a whiteboard), then emit the JSON.
# extract_json reads the fenced JSON regardless of the prose before it. ponytail: the prose adds
# some output tokens, but it's the whole point (watch it think) and it's good chain-of-thought;
# it does NOT add extra LLM calls, so cost stays ~flat vs one-hypothesis-per-call.
THINK_ALOUD = (
    "\n\nThink OUT LOUD first, in plain prose — a few sentences per idea: your intuition for the "
    "edge, who is on the other side and why they keep paying, why it isn't already arbitraged away, "
    "and what result would kill it. Reason like you're at a whiteboard. Do NOT use braces {{ }} or "
    "JSON in this thinking part. THEN, after the reasoning, output the single JSON object inside a "
    "```json code fence.")


class _StreamSink:
    """Persists the proposer's live tokens to the run log as `thinking` events so the feed shows
    the agent writing in real time. Flushes on a cadence (time OR size), never per token, to bound
    DB writes: a multi-minute call becomes a few hundred small rows, not a few thousand. Each model
    call is a new `block` the feed coalesces into one growing card; an `end` marker seals it.
    ponytail: fixed 0.7s / 350-char flush — token-exact smoothness would need SSE, which the CSP
    (`script-src 'self'`) rules out, so the feed stays on the existing 2s poll."""
    FLUSH_SECONDS = 0.7
    FLUSH_CHARS = 350

    def __init__(self, log: Callable):
        self._log = log
        self._pending = ""
        self._last = 0.0
        self._block = 0
        self._streamed = False

    def start(self) -> None:
        self._block += 1
        self._pending = ""
        self._last = time.monotonic()

    def feed(self, delta: str) -> None:
        if not delta:
            return
        self._streamed = True
        self._pending += delta
        if len(self._pending) >= self.FLUSH_CHARS or (time.monotonic() - self._last) >= self.FLUSH_SECONDS:
            self._emit()

    def _emit(self) -> None:
        if not self._pending:
            return
        self._log("thinking", self._pending, {"block": self._block})
        self._pending = ""
        self._last = time.monotonic()

    def finish(self) -> None:
        self._emit()
        if self._streamed:
            self._log("thinking", "", {"block": self._block, "end": True})
            self._streamed = False


def _can_stream(model: ModelFn) -> bool:
    """True if `model` accepts the optional on_delta arg (the prod default does; injected/test
    models take only (system, messages) and run without live tokens)."""
    import inspect
    try:
        params = list(inspect.signature(model).parameters.values())
    except (TypeError, ValueError):
        return False
    return len(params) >= 3 or any(p.kind == p.VAR_POSITIONAL for p in params)


def _alive_during_calls(model: ModelFn, progress: List[float]) -> ModelFn:
    """Wrap the model so the heartbeat beater treats a call in flight as progress (see
    MODEL_CALL_GRACE_SECONDS). Keeps the wrapped model's streaming signature, so _can_stream sees
    the same thing it would on the bare model."""
    def busy() -> None:
        progress[0] = time.monotonic() + MODEL_CALL_GRACE_SECONDS - RUN_STALL_SECONDS

    if _can_stream(model):
        def m(system: str, messages: List[Dict], on_delta=None) -> "tuple[str, Dict]":
            busy()
            try:
                return model(system, messages, on_delta)
            finally:
                progress[0] = time.monotonic()
    else:
        def m(system: str, messages: List[Dict]) -> "tuple[str, Dict]":  # type: ignore[misc]
            busy()
            try:
                return model(system, messages)
            finally:
                progress[0] = time.monotonic()
    return m


def _stream_proposer(model: ModelFn, sink: _StreamSink) -> ModelFn:
    """Wrap the model so the proposer's generation streams its tokens into the feed. A model that
    can't stream (test/injected, or the Anthropic-direct fallback) just runs normally."""
    streams = _can_stream(model)

    def m(system: str, messages: List[Dict]) -> "tuple[str, Dict]":
        sink.start()
        out = model(system, messages, sink.feed) if streams else model(system, messages)
        sink.finish()
        return out

    return m


def _hypotheses_check(market: str, max_n: int) -> Callable[[Dict], List[Dict]]:
    """Validate a proposer batch. An invalid spec gets ONE repair round (the errors go back to the
    model); after that the valid ideas go ahead and each still-invalid one is kept on
    check.invalid ({title, why}) for the caller to log as a dropped idea, so one bad spec can no
    longer sink the whole batch. Only a batch with no valid idea at all fails the attempt."""
    state = {"calls": 0}

    def check(obj: Dict) -> List[Dict]:
        state["calls"] += 1
        check.invalid = []
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
                check.invalid.append({"title": title[:120], "why": "spec invalid: %s" % e})
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
        if problems and (not out or state["calls"] == 1):
            raise ValueError("; ".join(problems))
        return out

    check.invalid = []
    return check


def _metrics_line(m: Dict) -> str:
    return "trades=%s win_rate=%s pnl=$%s fees=$%s profit_factor=%s max_dd=$%s" % (
        m["trades"], m["win_rate"], m["pnl"], m["fees"], m["profit_factor"], m["max_drawdown"],
    )


def _attribution_line(attr: Optional[Dict]) -> str:
    """One compact line per hypothesis showing WHERE its research-fold net edge concentrates
    (mean net return per trade, by price band / side / ET session). This is the conditional-edge
    hint that lets the agent sharpen a real mechanism (e.g. the documented favorite-longshot bias
    is in the cheap band) instead of guessing filters. Research-fold only (leak-free); every
    refinement is still judged on unseen data and counts against the statistical trial budget."""
    if not attr:
        return ""
    parts = []
    for group in ("price", "side", "session"):
        buckets = attr.get(group) or {}
        if not buckets:
            continue
        inner = ", ".join("%s %+.4f (n=%d)" % (k, v["mean_net"], v["n"])
                          for k, v in sorted(buckets.items(), key=lambda kv: kv[1]["mean_net"], reverse=True))
        parts.append("%s[%s]" % (group, inner))
    return ("  edge-by-regime (mean net/trade): " + "; ".join(parts)) if parts else ""


def _failure_digest_line(d: Dict) -> str:
    """Render research_memory.distill_failures output as one skeptical steering line for the proposer."""
    cls = ", ".join("%d %s" % (c, k)
                    for k, c in sorted(d["classifications"].items(), key=lambda kv: -kv[1]))
    regions = ("; ".join("%s (%d×)" % (dim, c) for dim, c in d["patterns"][:8])
               or "no single region dominates yet — vary the mechanism, not just the parameters")
    return ("What has repeatedly FAILED here (treat as dead ends — do NOT re-propose these or near-"
            "variants; if you revisit one, state what is materially different and why it should work "
            "now): %d failed strategies (%s). Recurring dead regions: %s."
            % (d["n_failed"], cls, regions))


def _memory_block(memory: List[Dict]) -> str:
    if not memory:
        return "No earlier research on this market for this user."
    # Passed/pending rows stay raw (few, and useful: refine winners, don't repeat them). The pile
    # of individually-useless FAILED rows is distilled into ONE leak-safe signal of what keeps
    # failing, so the generator explores AWAY from dead ground. Both carry only research-fold
    # numbers + classification LABELS — no held-out number ever appears (Leak 2 stays closed).
    lines = []
    for s in memory:
        if s.get("status") in research_memory.FAILED_STATUSES:
            continue
        ins = (s.get("result") or {}).get("in_sample") or {}
        lines.append(
            "- [%s] %s: research $%s/%s trades"
            % (s["status"], s["title"], ins.get("pnl"), ins.get("trades"))
        )
    out = lines or ["(no strategies have passed yet)"]
    digest = research_memory.distill_failures(memory)
    if digest:
        out.append(_failure_digest_line(digest))
    return "\n".join(out)


_BRIEF_PATH = os.path.join(os.path.dirname(__file__), "research_brief.md")


def _brief() -> str:
    """The operator-editable research constitution (app/research_brief.md), read fresh each run
    so edits take effect without a deploy. Empty string if it's missing."""
    try:
        with open(_BRIEF_PATH) as f:
            return f.read().strip()
    except OSError:
        return ""


# -- the user's market focus ---------------------------------------------------------------
# Prod 2026-10-24: Todd told the autopilot "Research and trade only crypto", and it kept launching
# sports research, because the instruction lived only in chat while the prompt pushed it to
# diversify. The focus is now stored (app_users.autopilot_focus) and enforced in code: research,
# deploys and the paper funnel refuse anything outside it, and the research picker only offers it.
FOCUS_ALIASES = {"bitcoin": "btc", "ethereum": "eth", "solana": "sol", "ripple": "xrp",
                 "dogecoin": "doge", "weather": "weather-high", "temperature": "weather-high"}


def _underlying_tag(market: str) -> str:
    m = MARKETS.get(market or "")
    return ((m.underlying or "").split("-")[0].lower()) if m is not None and m.underlying else ""


def focus_tokens(user: Optional[Dict]) -> List[str]:
    """The user's focus tokens (family names, market keys or coin tickers); [] = no focus."""
    raw = (user or {}).get("autopilot_focus")
    if not raw:
        return []
    try:
        vals = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    return [str(v).strip().lower() for v in vals if str(v).strip()] if isinstance(vals, list) else []


def in_focus(market: Optional[str], tokens: List[str]) -> bool:
    """True when `market` is inside the focus (or there is no focus, or no market yet)."""
    if not tokens or not market:
        return True
    from app import rsi  # local: rsi reads agent lazily too
    fam, key, coin = rsi.family(market), market.lower(), _underlying_tag(market)
    return any(t == key or t == fam or fam.startswith(t + "-") or (coin and t == coin) for t in tokens)


def normalize_focus(values) -> List[str]:
    """Validate a focus the user (via chat or the API) asked for: each token must name a market
    family, a market key or a coin. Raises ValueError naming what isn't recognised."""
    from app import rsi
    if isinstance(values, str):
        values = re.split(r"[,\s]+", values)
    known = set(MARKETS) | {rsi.family(k) for k in MARKETS} | {_underlying_tag(k) for k in MARKETS} - {""}
    out, bad = [], []
    for v in values or []:
        t = FOCUS_ALIASES.get(str(v).strip().lower(), str(v).strip().lower())
        if not t:
            continue
        (out if t in known else bad).append(t)
    if bad:
        raise ValueError("I don't recognise %s as a market, coin or category. Try e.g. crypto, btc, "
                         "sports, weather-high." % ", ".join(repr(b) for b in bad))
    return list(dict.fromkeys(out))


def focus_keys(cur, user_id: int, keys: List[str]) -> List[str]:
    """`keys` filtered to the user's focus (unchanged when no focus is set)."""
    try:
        tokens = focus_tokens(repo.get_user(cur, user_id))
    except Exception:  # noqa: BLE001 - a read hiccup (or a test stub) must not stop research
        tokens = []
    return [k for k in keys if in_focus(k, tokens)] if tokens else list(keys)


def focus_refusal(user: Dict, market: Optional[str]) -> Optional[str]:
    """The chat line refusing an action on `market` outside the user's focus, else None."""
    tokens = focus_tokens(user)
    if in_focus(market, tokens):
        return None
    label = MARKETS[market].label if market in MARKETS else market
    return ("You asked me to focus on %s, so I won't touch %s. Tell me in chat if you want to "
            "change the focus." % (", ".join(tokens), label))


# -- the autopilot's own scorecard -------------------------------------------------------------
# The research scoreboard (app.rsi) grades the research pipeline; this grades the autopilot as the
# manager that spends on it: did it follow the user's focus, and did its spend go where ideas reach
# the gate. It feeds back into every review (so the next decision improves on the last) and is
# shared on /api/research/scoreboard as "autopilot".
SCORECARD_DAYS = 3
BURN_USD = float(os.getenv("APP_AUTOPILOT_BURN_USD", "15"))


def autopilot_scorecard(board: Dict, focus: List[str]) -> Dict:
    """From a user's rsi.load_scoreboard: focus adherence and research spend vs gate reach per family."""
    cards = board.get("cards") or []
    placed = [c for c in cards if c.get("market")]
    inside = sum(1 for c in placed if in_focus(c["market"], focus))
    fams = []
    for fam, r in (board.get("families") or {}).items():
        cost, gated = float(r.get("cost_usd") or 0), int(r.get("gated") or 0)
        fams.append({"family": fam, "runs": int(r.get("runs") or 0), "cost_usd": round(cost, 2), "gated": gated,
                     "passed": int(r.get("passed") or 0),
                     "usd_per_gated": round(cost / gated, 2) if gated else None})
    fams.sort(key=lambda f: -f["cost_usd"])
    t = board.get("total") or {}
    return {"runs": int(t.get("runs") or 0), "cost_usd": round(float(t.get("cost_usd") or 0), 2),
            "gated": int(t.get("gated") or 0), "passed": int(t.get("passed") or 0),
            "focus": focus, "in_focus": inside if focus else None, "placed": len(placed),
            "adherence": round(inside / len(placed), 3) if (focus and placed) else None,
            "families": fams,
            "burning": [f["family"] for f in fams if f["cost_usd"] >= BURN_USD and not f["gated"]]}


def autopilot_scorecard_lines(card: Dict, days: int = SCORECARD_DAYS) -> List[str]:
    if not card.get("runs"):
        return []
    out = ["YOUR OWN SCORECARD as the manager (last %d days). Use it to do this job better than last time:" % days,
           "- research: %d runs, $%.2f, %d reached the gate, %d passed." % (
               card["runs"], card["cost_usd"], card["gated"], card["passed"])]
    if card.get("adherence") is not None:
        out.append("- following the user: %d of %d runs were inside their focus (%s) = %.0f%%.%s" % (
            card["in_focus"], card["placed"], ", ".join(card["focus"]), 100 * card["adherence"],
            "" if card["adherence"] >= 1 else " Every run outside it ignored the user; it must be 100%."))
    out.append("- spend by family: " + "; ".join(
        "%s %d runs $%.2f, gate reached %d%s" % (f["family"], f["runs"], f["cost_usd"], f["gated"],
                                                ", $%.2f per gated idea" % f["usd_per_gated"] if f["usd_per_gated"] else "")
        for f in card["families"][:6]) + ".")
    if card["burning"]:
        out.append("- burning money with nothing reaching the gate: %s. Don't fund the same angles there again; "
                   "change the angle or move the spend." % ", ".join(card["burning"]))
    out.append("Act on it: put the next research where ideas reach the gate for the least money (inside the "
               "user's focus), and say in your plan what you changed because of this scorecard.")
    return out


def set_focus_action(cur, user: Dict, action: Dict, run_kind: str) -> str:
    """Apply a set_focus action. Only a chat run (the user just wrote) may change the focus; a
    scheduled review can't drift it away from what the user asked."""
    if run_kind == "review":
        try:
            same = normalize_focus(action.get("focus") or []) == focus_tokens(user)
        except ValueError:
            same = False
        # A review restating the focus it was given is a no-op, not a refusal worth a chat line
        # (prod 21:27Z: the first review after the fix echoed set_focus and Todd saw "Only you can…").
        return "" if same else "Only you can change the market focus. Tell me in chat."
    try:
        tokens = normalize_focus(action.get("focus") or [])
    except ValueError as e:
        return str(e)
    repo.set_autopilot_focus(cur, user["id"], tokens)
    if not tokens:
        return "Market focus cleared: autopilot may research and trade any market again."
    return ("Market focus set to %s. Autopilot will research, deploy and trade only these from now on."
            % ", ".join(tokens))


def research_unavailable_reason(market: Optional[str]) -> Optional[str]:
    """Reject disabled native research before a manual/agent action queues paid work."""
    if market in MARKETS and MARKETS[market].tick_history_short():
        return MARKETS[market].tick_history_short()
    if market in MARKETS and MARKETS[market].kind == "perpetual":
        from app.kalshi_perps_data import Config
        from app.market_data_common import MarketDataError
        try:
            Config.from_env().require_enabled()
        except MarketDataError as exc:
            return str(exc)
    return None


def _researchable_keys(cur) -> List[str]:
    """Market keys the autopilot may pick for its OWN choice: only those with a real backtest
    surface (collected candle history / a live spot feed), so it stops picking data-less markets
    that just fail at load — the proactive complement to the reactive fail-fast/backoff. Reuses the
    server picker's tested readiness logic (app.services.markets). Empty -> fail open (offer
    all), so a cold/edge DB never blocks research entirely."""
    try:
        ready = [m["key"] for m in market_service.researchable_markets(cur) if m["has_data"]]
    except Exception:  # noqa: BLE001 - a readiness-lookup hiccup must never block research
        return list(MARKETS)
    return ready or list(MARKETS)


def _research_history_line(cur, user_id: int) -> str:
    """One-line CROSS-market summary of what this user already researched (per market: tried/passed),
    so the agent's own market pick builds on history instead of re-choosing blind. Empty for a user
    with no research yet."""
    try:
        rows = repo.research_summary(cur, user_id)
    except Exception:  # noqa: BLE001 - a history-lookup hiccup must never block/fail research
        return ""
    if not rows:
        return ""
    parts = ["%s (%d tried, %d passed)"
             % (MARKETS[r["market"]].label if r["market"] in MARKETS else r["market"],
                r["tried"], r["passed"]) for r in rows]
    return "Your past research across markets — " + "; ".join(parts) + "."


def _pick_market(run: Dict, model: ModelFn, usage: Usage, log, keys: Optional[List[str]] = None, history: str = "") -> str:
    """When the user didn't pin a market, let the agent choose the one whose contracts best
    fit the idea (guided by the brief + the user's cross-market research history), from the
    data-ready `keys` only. One cheap call before the research loop."""
    idea = (run.get("prompt") or "").strip() or "any durable, fee-surviving edge"
    from app.kalshi_perps_data import Config as PerpsConfig
    from app.market_data_common import MarketDataError
    try:
        perps_enabled = PerpsConfig.from_env().enabled
    except (ValueError, MarketDataError):
        perps_enabled = False
    choices = {k: m for k, m in MARKETS.items()
               if (keys is None or k in keys) and (m.kind != "perpetual" or perps_enabled)}
    opts = "\n".join("- %s: %s" % (k, MARKETS[k].label) for k in choices)
    hist = ("\n\n%s Build on what's worked or deliberately explore somewhere new — your call, but "
            "don't blindly repeat a market that keeps failing." % history) if history else ""
    msg = ("%s\n\nIdea: %s%s\nMarkets you can research:\n%s\n"
           "Pick the ONE market whose contracts best fit this idea. Reply exactly:\n"
           '{"market": "<key>", "why": "<one sentence>"}' % (_brief(), idea[:400], hist, opts))

    by_label = {m.label.strip().lower(): k for k, m in choices.items()}

    def check(obj: Dict) -> Dict:
        raw = str(obj.get("market") or "").strip()
        k = raw if raw in choices else raw.lower() if raw.lower() in choices else by_label.get(raw.lower())
        if k is None:
            # Prod run 2674: the model kept naming a market outside the list. Say WHY it was refused
            # (a known market that isn't ready or is on cooldown reads like a typo otherwise).
            why = ("%r is not open for research right now (no data yet, or on cooldown)" % raw
                   if raw in MARKETS else "%r is not a market key" % raw)
            raise ValueError("%s. Reply with one key exactly as listed: %s" % (why, ", ".join(choices)))
        # Full reasoning, not a clipped fragment: this `why` is shown verbatim as the first
        # agent-log line, so cap it at the same 1000 chars as every other reason field (the
        # message column is TEXT) — the old 200 clipped the sentence mid-word.
        return {"market": k, "why": str(obj.get("why") or "")[:1000]}

    try:
        r = ask_json(model, RESEARCH_SYSTEM, [{"role": "user", "content": msg}], check, usage)
    except LLMError as e:
        if "could not be used" not in str(e) or not choices:
            raise
        # Never fail a run over the pick: take the listed market whose name best matches the idea.
        words = set(re.findall(r"[a-z0-9]+", idea.lower()))
        k = max(choices, key=lambda c: len(words & set(re.findall(r"[a-z0-9]+", (c + " " + choices[c].label).lower()))))
        r = {"market": k, "why": "The pick reply was unusable, so I took the market that best matches the idea."}
    log("step", "Chose to research %s. %s" % (MARKETS[r["market"]].label, r["why"]),
        {"phase": "pick_market", "market": r["market"]})
    return r["market"]


def _plan_lookback(run: Dict, market: str, model: ModelFn, usage: Usage, log) -> int:
    """Let the agent choose how much history to backtest on, guided by the brief and its thesis,
    clamped to what we actually have. One cheap call before the heavy research loop."""
    m = MARKETS[market]
    maxd = m.history_days
    if not m.underlying and m.candle_minutes >= 60 and m.kind == "binary":
        # A daily-settling series (weather) has one independent event per day, so every day cut is
        # lost power, and its full year loads in seconds (+120MB). Run 2613 chose 156 of 365 days.
        log("step", "Using all %d days of history: each day is one independent settlement here." % maxd,
            {"phase": "plan", "lookback_days": maxd})
        return maxd
    idea = (run.get("prompt") or "").strip() or "any durable, fee-surviving edge"
    msg = ("%s\n\nIdea: %s\nMarket: %s. Up to %d days of history are available to backtest on.\n"
           "Pick how many days the backtest should replay for THIS idea. Reply exactly:\n"
           '{"lookback_days": <integer 5..%d>, "why": "<one sentence>"}'
           % (_brief(), idea[:400], m.label, maxd, maxd))

    def check(obj: Dict) -> Dict:
        d = obj.get("lookback_days")
        if not isinstance(d, (int, float)):
            raise ValueError("reply needs an integer lookback_days")
        return {"days": max(5, min(int(d), maxd)), "why": str(obj.get("why") or "")[:1000]}

    r = ask_json(model, _research_system(market), [{"role": "user", "content": msg}], check, usage)
    log("step", "Chose a %d-day backtest window for this idea. %s" % (r["days"], r["why"]),
        {"phase": "plan", "lookback_days": r["days"]})
    return r["days"]


def _cross_market_options(market: str) -> str:
    """Surface the markets that can be a cross-SECTIONAL leg for `market` - those sharing its
    decision cadence (markets.compatible_cadence). Without this the proposer only knows its single
    run market, so it can propose same-market cross_strike/calendar but never a cross-MARKET pair.
    Empty when nothing shares the cadence (then cross_sectional isn't offered)."""
    from app.markets import compatible_cadence
    if MARKETS[market].kind == "perpetual":
        return ""
    peers = [k for k in MARKETS if k != market and MARKETS[k].kind != "perpetual"
             and compatible_cadence([market, k])]
    if not peers:
        return ""
    labels = ", ".join('"%s" (%s)' % (k, MARKETS[k].label) for k in peers)
    return ("\nCross-MARKET relative value: these markets share %s's decision cadence, so you MAY add "
            "ONE as a cross_sectional leg (cross.pairing=\"cross_sectional\", "
            "cross.legs=[{\"market\":\"<key>\"}]) when the edge is a RELATIVE mispricing between the two "
            "markets (lead-lag, basis dislocation), not a directional view: %s. Only do so with a real "
            "relative mechanism; otherwise stay single-contract.\n"
            "POOLED evidence: a STRUCTURAL mechanism that should hold on all of these markets (fee/price-"
            "band effects, settlement mechanics, favorite-longshot overpricing) can instead be judged on "
            "their POOLED trades: add \"pool\": [<keys>] (no cross). The same rule runs on every pooled "
            "market, so validation sees ~N times the trades and the detectable edge shrinks ~sqrt(N) times; "
            "it trades only on %s if it passes. The mechanism must apply to every pooled market."
            % (market, labels, market))


# Shared tail for every NON-PRICE (event-settled) market profile. The built-in gbm model is a
# continuous-price model, so it genuinely can't price these — but that is NOT a dead end: `code` +
# fit(window) is the first-class tool here, and these are the model families that fit event markets.
# (This kills the live failure where the agent rejected gbm for an NHL market and then gave up on
# `code` as an unknown last resort instead of writing a Poisson/logit/Bradley-Terry fit.)
_EVENT_MODEL_NOTE = """
MODELS FOR THIS MARKET: the built-in `gbm` fair value is a continuous-underlying-price model, so it
does NOT apply here — do NOT try to force it, and its absence is NOT a reason to call a thesis dead.
Your FIRST-CLASS tool is a `code` + fit(window) strategy (fit() TRAINS on the research fold and
returns frozen params; signals() rebuilds and PREDICTS — never refits). `code` is not an unknown
last resort: it is where event models live. Reach for a family that matches the mechanism, e.g.:
 - a Poisson / negative-binomial rate model on scoring or event counts (statsmodels);
 - a logistic / Bradley-Terry / paired-comparison model of the outcome (statsmodels/sklearn);
 - a recalibration of the market's OWN moneyline/mid (favorite-longshot), fit on research;
 - any sklearn/xgboost estimator (logit, random forest, gradient boosting) over the features this
   market actually populates.
Build only on features the coverage below shows are non-null for THIS market; `model.kind`
logistic/calibration also work when their features are populated, but gbm does not."""


def _tick_profile(m) -> str:
    """Extra profile for a market replayed from the per-second tick archive (tick_dataset.py)."""
    from app.markets import TICK_FEATURES
    return ("\nPER-SECOND DATA: this dataset is replayed from the tick archive, one decision every %ds "
            "(not 1-minute candles). Every value is as of the end of that second, from events before it; "
            "orders fill at the NEXT decision's quote (%ds later), capped by the shown size. vol_15m, "
            "vol_60m, ret_15m, ret_60m and z_score are rebuilt from minute closes and are absent in the "
            "first hour of each data stretch. Extra features: %s. History is short (the archive began %s), so "
            "prefer simple, structural rules that need few trades: second-scale lead-lag of the book "
            "behind spot, taker-flow bursts, stale quotes (book_age_s) after a spot move."
            % (m.decision_seconds, m.decision_seconds,
               "; ".join("%s = %s" % (k, v.replace("per-second data only: ", "")) for k, v in TICK_FEATURES.items()),
               datetime.fromtimestamp(m.data_from_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%MZ")))


def _market_profile(market: str) -> str:
    """The per-run, market-AWARE half of the research brief: what THIS Kalshi market settles on,
    how settlement works, and the angles/features that actually apply to it. Injected into the
    proposer prompt so a non-BTC run is never told it trades Bitcoin (the old hardcoded framing)
    and a BTC run reads exactly as richly as before. Branches on the market's own metadata
    (kind / underlying / category), the single source of truth in markets.py."""
    m = MARKETS[market]
    head = 'Market profile — "%s" (spec market "%s", series %s, %s).' % (
        m.label, m.key, m.series, m.category or "uncategorized")
    if m.kind == "perpetual":
        return head + ("\nA continuous Bitcoin perpetual with native Kalshi prices and recorded funding. "
                       "This run is research-only. Available mechanisms are causal momentum, "
                       "mean reversion and funding estimates observed at the decision time. "
                       "A successful research verdict does not enable trading.")
    if m.kind == "spot":
        return head + """
This is a CONTINUOUS-PRICE instrument (a Bittensor subnet alpha token priced in TAO), NOT a
binary: there is no strike, expiry or YES/NO settlement. The backtest trades it long/flat on the
price series itself. Angles that fit: momentum/trend and mean-reversion on the token's own
returns, volatility regimes, and basis vs the TAO/USD rate. There is no order book or Kalshi
mid here, so microstructure/longshot angles do NOT apply. (Execution is research-only.)"""
    if m.underlying:   # strike-vs-spot crypto binary (BTC/ETH/SOL/…)
        coin = m.underlying.split("-")[0]
        gbm = ("The GBM-digital fair value you get is, on BTC history, slightly WORSE calibrated "
               "than the Kalshi mid (log loss 0.403 vs 0.384), so an unconditional 'the model says "
               "it's mispriced' edge is a fee/noise artifact." if market.startswith("btc")
               else "A house GBM-digital fair value is available (strike vs %s spot), but treat the "
                    "Kalshi mid as the baseline to beat — an unconditional model-mispricing edge is "
                    "usually fee/noise." % coin)
        from app.markets import CROSS_FEATURES, cross_feature_names, cross_product
        xprod, xnames = cross_product(m), cross_feature_names(m)
        cross = ("\nCross-asset: every frame also carries %s's moves as of the decision (%s), so lead-lag "
                 "ideas (does %s's move lead %s's ladder?) are testable as filters, models or code."
                 % (xprod.split("-")[0], ", ".join(k for k in CROSS_FEATURES if k in xnames), xprod.split("-")[0], coin)
                 ) if xprod else ""
        return head + """
YES pays $1 if %s settles above the strike at the contract's settlement instant. Contracts are
priced strike-vs-spot off %s's Coinbase feed, so you have spot, returns, realised vol, moneyness
and z_score, PLUS order-book/microstructure features. %s%s
Angles worth a mechanism (not exhaustive):
- Settlement mechanics: terminal pinning near the strike in the last minutes; 1c tick discreteness
  vs a continuous fair value.
- Microstructure: order-book imbalance and recent trade flow can lead the mid for seconds-to-
  minutes; does the book lag %s spot?
- Behavioral / flow: retail longshot bias (overpaying for cheap far-OTM lottery YES/NO), favorite-
  longshot distortion near 5c/95c, round-number strike magnetism, US-open vs Asia-overnight regimes.
- Basis / funding: implied probability vs perp funding / spot-perp basis; cross-coin ladder lead-lag.
- Volatility: does the market over/under-price realised vol at specific horizons (e.g. the last
  3-8 minutes of a 15-minute contract)?""" % (coin, coin, gbm, cross, coin) + (_tick_profile(m) if m.source == "ticks" else "")
    cat = (m.category or "").lower()
    if "sport" in cat:
        return head + """
Every contract here is a YES/NO binary on one game outcome, settled on the RESULT: a moneyline
(YES = the named team/side wins) or ONE STRIKE of a ladder (YES = the team covers spread X, the
total goes over X, the player reaches X yards/points/TDs) - the market label says which. Even on a
spread, total or prop market the price is the market's PROBABILITY of YES for that strike, never a
handicap in points, so calibration and favorite-longshot ideas apply exactly as on a moneyline.
A ladder's strikes on one game are linked (P(over 41.5) >= P(over 44.5)); a code strategy's window
gives each contract its "strike" and its "event" (one game: group by it), no ticker parsing needed. There is NO underlying price feed, moneyness or vol —
the spot/GBM model does NOT apply. It trades on the contract's OWN price and order-book/trade-flow features
only (many micro features may be sparse — build only on what the coverage shows is populated).
Angles worth a mechanism: favorite-longshot bias (heavy favorites vs longshots systematically
mis-priced), in-game momentum as the price walks toward 0/100 near the final whistle, over-reaction
to a scoring swing, and liquidity/spread capture when flow is balanced. News of lineups/injuries
re-prices the line before settlement.""" + _EVENT_MODEL_NOTE
    if "weather" in cat or "climate" in cat:
        return head + """
This is a daily weather binary (e.g. "high temperature >= X"): YES pays $1 if the observed daily
figure clears the threshold. It settles on the published observation, so there is NO tradable spot
series or vol feature. It trades on the contract's own price plus built-in weather features: the
strike (strike_lo_f/strike_hi_f), the station's observed extreme so far (obs_*), the NWS forecast
and its probability for this contract (fcst_*), and margins to the YES range. Angles worth a mechanism: the market's implied probability vs the
public forecast and its diurnal update, seasonal/climatological base rates for the date, favorite-
longshot bias on near-certain vs tail thresholds, and drift as the settlement day approaches.""" + _EVENT_MODEL_NOTE
    # Any other outcome-settled catalog binary (Economics, Companies, Health, World, …).
    return head + """
This is an outcome-settled YES/NO binary: it pays $1 if the published event occurs. There is NO
underlying price feed, strike or vol — the spot/GBM model does NOT apply; it trades on the
contract's own price and whatever order-book features the coverage shows are populated. Angles
worth a mechanism: favorite-longshot / calibration bias (cheap tails overpriced, near-certain
underpriced), drift and information flow as the resolution date approaches, and over-reaction to
scheduled releases. Ground the mechanism in who misprices this specific event and why.""" + _EVENT_MODEL_NOTE


_DETECT_TRADES_PER_DAY = (2, 10, 40, 150)


def _detectability_block(ds: backtest.Dataset) -> str:
    """What edge size is even testable here, so the proposer stops spending trials on rules the
    gate cannot confirm however real they are. Uses only the research window's length and the
    gatekeeper's public constants, never a held-out number.

    Validation spans VALIDATION_FRAC/RESEARCH_FRAC of the research window. A per-trade net return
    is detectable at ~50% power when mean >= z * sd / sqrt(n_val), z the validation level
    (gatekeeper._validation_level; LORD++'s first-test level if the fixed alpha is off) and sd ~= 1
    for a mid-priced binary (a $1/$0 payoff on a 50c stake)."""
    research_days = max((ds.end_ts - ds.start_ts) / 86400.0, 0.0)
    if research_days <= 0:
        return ""
    val_days = research_days * partitions.VALIDATION_FRAC / partitions.RESEARCH_FRAC
    z = stats.norm_ppf(1.0 - gatekeeper._validation_level(stats.lord_init(gatekeeper.ALPHA)))
    rows = []
    for per_day in _DETECT_TRADES_PER_DAY:
        n_val = per_day * val_days
        mde = z / n_val ** 0.5
        rows.append("~%d trades/day -> ~%.0f validation trades -> needs >= %.1f%% net per trade "
                    "(~%.1fc per contract at a 50c price)" % (per_day, n_val, 100 * mde, 50 * mde))
    return ("DETECTABILITY (what the gate can confirm here): the held-out validation window will span "
            "~%.0f days. At the best case (first test of a fresh budget, independent trades), a rule needs "
            "roughly:\n  %s\nRules below these thresholds cannot pass however real they are; positions on "
            "several strikes of the SAME event are one bet, not several. Prefer mechanisms that either trade "
            "often or carry a large per-trade edge, and say in each thesis which row of this table it "
            "targets." % (val_days, "\n  ".join(rows)))


_CALIB_BINS = (0.0, 0.10, 0.25, 0.40, 0.60, 0.75, 0.90, 1.0)
_CALIB_MIN_CONTRACTS = 20
_CALIB_FEE_QTY = 10  # amortize Kalshi's per-order fee cent over a typical order
_CALIB_LEAD_SE = 2.0  # a cell is a lead only when its best net edge clears this many standard errors


def _calibration_block(ds: backtest.Dataset) -> str:
    """Where the market's own prices have been mis-calibrated, net of the taker fee, on the RESEARCH
    window only (never validation or holdout), so the proposer aims at measured mispricing (favorite-
    longshot, terminal pinning) instead of guessing. Each settled contract counts once per (time
    band, price bin), priced at its FIRST quote in that cell: what a rule that enters when the
    condition turns true and holds to settlement actually pays. (An average quote understates it:
    a contract sliding to NO through 9c..1c averages ~5c but a rule buys it at 9c, which printed a
    +1.1c "lead" on btc15m cheap YES that every backtest of it lost.) Descriptive only: whatever it
    suggests still has to pass the held-out gate."""
    rows = calibration_cells(ds)
    if not rows:
        return ""
    leads = sum(r["lead"] for r in rows)
    lines = ["%-5s ask %2d-%2dc: n=%4d  avg ask %.2f  YES settled %.2f (+-%.2f)  "
             "buy-YES net %+.1fc  buy-NO net %+.1fc  %s"
             % (r["band"], r["lo_c"], r["hi_c"], r["n"], r["ask"], r["rate"], r["se"], 100 * r["yes_edge"],
                100 * r["no_edge"], "LEAD (buy-%s)" % r["side"].upper() if r["lead"] else "noise") for r in rows]
    verdict = ("%d cell(s) marked LEAD clear %gx their +- after fees: a calibration mechanism may target "
               "ONLY those cells." % (leads, _CALIB_LEAD_SE) if leads else
               "NO cell clears %gx its +- after fees: this market's prices are calibrated within noise. "
               "Do NOT propose unconditional favorite-longshot / price-recalibration theses "
               "here; they cannot beat the fee on this market." % _CALIB_LEAD_SE)
    return ("CALIBRATION on the research window (per settled contract, at its FIRST quote in each cell, "
            "i.e. what a rule entering on that condition pays; 'late' = last third of its life; net = "
            "settled rate minus that quote, after the taker fee). %s Descriptive only:\n  %s"
            % (verdict, "\n  ".join(lines)))


def calibration_cells(ds: backtest.Dataset) -> List[Dict]:
    """The calibration table's cells as data (see _calibration_block): one dict per (band, price bin)
    with at least _CALIB_MIN_CONTRACTS settled contracts."""
    from data_pipeline.kalshi_fees import taker_fee_per_contract_dollars as fee_per

    cells: Dict[Tuple[str, int, str], Tuple[float, float]] = {}
    max_tte: Dict[str, float] = {}
    for _, snaps in ds.frames:
        for sn in snaps:
            t = sn.features.get("tte_min")
            if t is not None and t > max_tte.get(sn.contract.ticker, 0.0):
                max_tte[sn.contract.ticker] = t
    for _, snaps in ds.frames:
        for sn in snaps:
            tk = sn.contract.ticker
            t = sn.features.get("tte_min")
            if ds.results.get(tk) not in ("yes", "no") or t is None or not max_tte.get(tk):
                continue
            band = "late" if t <= max_tte[tk] / 3.0 else "early"
            b = next(i for i in range(len(_CALIB_BINS) - 1) if sn.yes_ask < _CALIB_BINS[i + 1])
            cells.setdefault((band, b, tk), (sn.yes_ask, sn.yes_bid))  # frames ascend: first touch
    agg: Dict[Tuple[str, int], List] = defaultdict(list)
    for (band, b, tk), (ask, bid) in cells.items():
        agg[(band, b)].append((ask, bid, 1.0 if ds.results[tk] == "yes" else 0.0))
    rows = []
    for band in ("early", "late"):
        for b in range(len(_CALIB_BINS) - 1):
            obs = agg.get((band, b), [])
            n = len(obs)
            if n < _CALIB_MIN_CONTRACTS:
                continue
            ask = sum(o[0] for o in obs) / n
            bid = sum(o[1] for o in obs) / n
            rate = sum(o[2] for o in obs) / n
            se = (max(rate * (1 - rate), 1.0 / n) / n) ** 0.5
            yes_edge = rate - ask - fee_per(_CALIB_FEE_QTY, ask)
            no_px = 1.0 - bid
            no_edge = (1.0 - rate) - no_px - fee_per(_CALIB_FEE_QTY, no_px)
            best = max(yes_edge, no_edge)
            rows.append({"band": band, "lo_c": round(100 * _CALIB_BINS[b]), "hi_c": round(100 * _CALIB_BINS[b + 1]),
                         "n": n, "ask": ask, "bid": bid, "rate": rate, "se": se, "yes_edge": yes_edge,
                         "no_edge": no_edge, "best": best, "z": best / se if se else 0.0,
                         "lead": best > _CALIB_LEAD_SE * se, "side": "yes" if yes_edge >= no_edge else "no"})
    return rows


def _rsi_choose(cur, user_id: int, market: str, run_id: int, log) -> str:
    """Draw this run's research playbook (rsi_playbook.choose) and return its prompt block, "" for
    the empty version 0. Best-effort: a playbook hiccup never blocks research."""
    from app import rsi, rsi_playbook
    fam = rsi.family(market)
    try:
        pb = rsi_playbook.choose(cur, user_id, fam, run_id)
    except Exception:  # noqa: BLE001
        _LOG.exception("rsi playbook choice failed for run %s", run_id)
        return ""
    if pb and (pb.get("text") or "").strip():
        log("step", "Using research playbook v%s for %s markets (%s)."
            % (pb["version"], fam, "on trial against the current one" if pb["status"] == "candidate" else "current"),
            {"phase": "playbook", "family": fam, "version": pb["version"], "status": pb["status"]})
    return rsi_playbook.prompt_block(pb, fam)


def _rsi_learn(conn, cur, run: Dict, ds, explored: int, tokens_in: int, tokens_out: int, model, usage,
               log) -> None:
    """After a run: credit its ideas to the playbook it drew, settle the candidate-vs-active trial,
    and (with no candidate pending) have the model rewrite the active playbook from this run's
    verdicts into the next candidate. Research-window evidence and gate labels only."""
    from app import rsi, rsi_playbook
    user_id, market, run_id = run["user_id"], run["market"], run["id"]
    fam = rsi.family(market)
    try:
        events = repo.run_events(cur, run_id)
        card = rsi.run_card(dict(run, hypotheses_tried=explored, input_tokens=tokens_in,
                                 output_tokens=tokens_out), events)
        rsi_playbook.score_run(cur, run_id, card)
        verdict = rsi_playbook.decide(cur, user_id, fam,
                                      paper_of=lambda: rsi.paper_outcomes(cur, user_id)["by_playbook"])
        if verdict:
            log("step", "Research playbook for %s markets: %s." % (fam, verdict),
                {"phase": "playbook", "family": fam, "decision": verdict})
        conn.commit()
        if rsi_playbook.candidate(cur, user_id, fam):
            return  # one rewrite on trial at a time, so the A/B stays readable
        current = rsi_playbook.active(cur, user_id, fam)
        facts = "\n".join(b for b in (_feature_block(ds), _fair_value_block(ds)) if b)
        new = rsi_playbook.reflect(model, usage, fam, MARKETS[market].label, current, card,
                                   rsi_playbook.idea_lines(events), facts[:6000])
        version = rsi_playbook.add_candidate(cur, user_id, fam, current, new["playbook"], new["changes"], run_id)
        conn.commit()
        log("step", "Wrote research playbook v%d for %s markets from this run's verdicts; it now runs on "
                    "trial against v%s. %s" % (version, fam, current["version"], new["changes"]),
            {"phase": "playbook", "family": fam, "version": version, "changes": new["changes"]})
    except Exception as e:  # noqa: BLE001 - learning is best-effort; the run's results are already saved
        _LOG.exception("rsi learn step failed for run %s", run_id)
        log("step", "Playbook update skipped (%s)." % str(e)[:200])


_FV_BANDS_H = ((24.0, None, ">24h"), (12.0, 24.0, "12-24h"), (4.0, 12.0, "4-12h"), (0.0, 4.0, "<4h"))
_FV_MIN_EVENTS = 10   # per half: fewer events than this and a band says nothing
_FV_MIN_EDGE = 0.02   # the probe trades only when its probability clears the quote + fee by 2c
_FV_LEAD_SE = 2.0


def _is_fair_value(name: str) -> bool:
    """A built-in external probability for the contract's YES (weather fcst_p_yes[_cal], sports
    book_p_yes): the features a market's own mid can be tested against."""
    return name.endswith("_p_yes") or name.endswith("_p_yes_cal")


def _logit(p: float) -> float:
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1.0 - p))


def _fv_probe(rows: List[Tuple], fee_per) -> Optional[Dict]:
    """Walk-forward test of one fair-value feature in one time band. rows are (first_ts, event, bid,
    ask, p, y), one per settled contract. The earlier half of the EVENTS fits y ~ logit(mid) +
    logit(p); the later half scores it. Strikes of one event settle together, so the SE is
    clustered by event."""
    start: Dict[str, int] = {}
    for r in rows:
        start[r[1]] = min(start.get(r[1], r[0]), r[0])
    events = sorted(start, key=start.get)
    if len(events) < 2 * _FV_MIN_EVENTS:
        return None
    train_ev = set(events[:len(events) // 2])
    train = [r for r in rows if r[1] in train_ev]
    test = [r for r in rows if r[1] not in train_ev]
    X = [[_logit((r[2] + r[3]) / 2.0), _logit(r[4])] for r in train]
    coef, b0 = stats.fit_logistic(X, [r[5] for r in train], l2=1.0)

    def blend(r):
        z = b0 + coef[0] * _logit((r[2] + r[3]) / 2.0) + coef[1] * _logit(r[4])
        return 1.0 / (1.0 + math.exp(-max(min(z, 30.0), -30.0)))

    def brier(prob):
        return sum((prob(r) - r[5]) ** 2 for r in test) / len(test)

    out = {"n": len(test), "events": len(events) - len(train_ev),
           "brier_mid": brier(lambda r: (r[2] + r[3]) / 2.0), "brier_fv": brier(lambda r: r[4]),
           "brier_blend": brier(blend), "w_mid": coef[0], "w_fv": coef[1]}
    for label, prob in (("raw", lambda r: r[4]), ("blend", blend)):
        by_ev: Dict[str, List[float]] = defaultdict(list)
        for r in test:
            q, bid, ask, y = prob(r), r[2], r[3], r[5]
            no_px = 1.0 - bid
            if q - ask - fee_per(_CALIB_FEE_QTY, ask) >= _FV_MIN_EDGE:
                by_ev[r[1]].append(y - ask - fee_per(_CALIB_FEE_QTY, ask))
            elif (1.0 - q) - no_px - fee_per(_CALIB_FEE_QTY, no_px) >= _FV_MIN_EDGE:
                by_ev[r[1]].append((1.0 - y) - no_px - fee_per(_CALIB_FEE_QTY, no_px))
        n = sum(len(v) for v in by_ev.values())
        mean = sum(sum(v) for v in by_ev.values()) / n if n else 0.0
        se = (sum((sum(v) - len(v) * mean) ** 2 for v in by_ev.values()) ** 0.5 / n
              if len(by_ev) > 1 else float("inf"))
        out[label] = (n, len(by_ev), mean, se)
    return out


_FV_BLOCK: Dict[str, object] = {"ds": None, "text": ""}


def _fair_value_block(ds: backtest.Dataset) -> str:
    """Cached per dataset (every proposing round of a run asks again); never fails a run."""
    if _FV_BLOCK["ds"] is ds:
        return _FV_BLOCK["text"]
    try:
        text = _fair_value_table(ds)
    except Exception:
        _LOG.exception("fair-value block failed; prompting without it")
        text = ""
    _FV_BLOCK.update(ds=ds, text=text)
    return text


def _fair_value_table(ds: backtest.Dataset) -> str:
    """Does a built-in fair value (weather forecast, sportsbook odds) know anything the market's own
    mid doesn't? Measured on the RESEARCH window only, per time-to-close band, at each settled
    contract's first quote in the band: a walk-forward logistic blend of mid + fair value, fit on
    the earlier events and scored on the later ones, plus the net P&L of buying wherever that blend
    (or the raw fair value) beats the quote by 2c after the fee. Descriptive, like the calibration
    table: it points the proposer at the band where the information is, or says there is none."""
    lines, leads = [], []
    for r in fair_value_rows(ds):
        name, band, got = r["name"], r["band"], r
        parts = []
        for label in ("raw", "blend"):
            n, n_ev, mean, se = got[label]
            lead = n and mean > _FV_LEAD_SE * se
            if lead:
                leads.append("%s %s %s" % (name, band, label))
            parts.append("%s: %d trades/%d events %+.1fc +-%.1fc%s" % (
                label, n, n_ev, 100 * mean, 100 * se, " LEAD" if lead else "") if n else "%s: no trades" % label)
        lines.append("%-15s %-6s n=%4d (%d events)  Brier mid %.3f  %s %.3f  blend %.3f (w_mid %.2f, "
                     "w_fv %.2f)  |  %s" % (
                         name, band, got["n"], got["events"], got["brier_mid"], name, got["brier_fv"],
                         got["brier_blend"], got["w_mid"], got["w_fv"], "  ".join(parts)))
    if not lines:
        return ""
    verdict = ("LEAD in: %s. Build on those bands; the others are noise." % "; ".join(leads) if leads else
               "NO band clears %gx its +- out of sample: on this window the mid already prices these fair "
               "values. A thesis that just trades the fair value against the mid needs a mechanism the "
               "table cannot see (a feature it lacks, a narrower condition) and should say which." % _FV_LEAD_SE)
    return ("FAIR VALUE vs MID on the research window (first quote per contract per time-to-close band; "
            "blend = logistic of logit(mid) + logit(fair value) fit on the earlier half of events, scored on "
            "the later half; trades where the probability beats the quote by %dc after the fee, net per "
            "contract, SE clustered by event). %s\n  %s"
            % (round(100 * _FV_MIN_EDGE), verdict, "\n  ".join(lines)))


def fair_value_rows(ds: backtest.Dataset) -> List[Dict]:
    """The fair-value table's rows as data: one _fv_probe result per (feature, band) with enough
    events, plus "name" and "band"."""
    from data_pipeline.kalshi_fees import taker_fee_per_contract_dollars as fee_per

    first: Dict[Tuple[str, str, str], Tuple] = {}
    for ts, snaps in getattr(ds, "frames", None) or []:
        for sn in snaps:
            tk = sn.contract.ticker
            y = ds.results.get(tk)
            t = sn.features.get("tte_min")
            if y not in ("yes", "no") or t is None or t < 0 or sn.yes_bid is None or sn.yes_ask is None:
                continue
            if not 0.0 <= sn.yes_bid < sn.yes_ask <= 1.0:
                continue
            band = next(lab for lo, hi, lab in _FV_BANDS_H if t / 60.0 >= lo and (hi is None or t / 60.0 < hi))
            for name, v in sn.features.items():
                if v is None or not _is_fair_value(name):
                    continue
                first.setdefault((name, band, tk), (ts, tk.rsplit("-", 1)[0], sn.yes_bid, sn.yes_ask,
                                                    float(v), 1.0 if y == "yes" else 0.0))
    groups: Dict[Tuple[str, str], List[Tuple]] = defaultdict(list)
    for (name, band, _tk), row in first.items():
        groups[(name, band)].append(row)
    rows = []
    for name in sorted({k[0] for k in groups}):
        for _lo, _hi, band in _FV_BANDS_H:
            got = _fv_probe(groups.get((name, band), []), fee_per)
            if got is not None:
                rows.append(dict(got, name=name, band=band))
    return rows


def _research_prompt(run: Dict, ds: backtest.Dataset, memory: List[Dict], count: int) -> str:
    idea = (run.get("prompt") or "").strip() or "Find any durable, fee-surviving edge you can justify."
    brief = _brief()
    lens = ""
    if run.get("direction") and run["direction"] in DIRECTIONS:
        d = DIRECTIONS[run["direction"]]
        lens = "\nOptional lens to consider: %s - %s" % (d["label"], d["brief"])
    # A co-pilot-delegated run (brief=True) carries a high-level ANGLE, not a finished thesis: the
    # operation manager delegates thesis-writing to this specialist. A Research-page run carries the
    # user's own idea, which we stay faithful to. Same pipeline either way — only the framing differs.
    if run.get("brief"):
        idea_label = "Angle to explore (a high-level BRIEF from the operation manager, NOT a finished thesis)"
        idea_framing = (
            "This is a DIRECTION, not a specification. The manager has delegated the thesis-writing "
            "to you: treat the angle as a starting lens and GENERATE the concrete, testable "
            "hypotheses yourself — the specific mechanisms, features, and spec are YOURS to invent. "
            "Do not merely restate the angle as one strategy; explore the most promising precise "
            "readings of it that THIS market's data can actually support, and say what you chose.")
    else:
        idea_label = "The user's idea"
        idea_framing = (
            "Turn this idea into concrete, testable trading strategies. Stay faithful to what the "
            "user asked for; if the idea is vague, pick the most promising precise reading and say so.")
    return """{brief}

{profile}

{idea_label}: {idea}{lens}{cross_options}

{idea_framing}

Market: {market_label} (spec market "{market}").
In-sample data you can test on: {summary}
{detect}
{calibration}
`feature_coverage_pct` is the non-null coverage of each feature ON THIS MARKET: only build models
and filters on features that are actually populated here. A feature at or near 0% is empty on this
market (e.g. order-book/microstructure features on sports/NEAR) — a model or filter that needs it
will fit nothing and take 0 trades, so pick a different signal. `feature_p10_p50_p90` is where each
populated feature's values actually sit here: put filter cuts inside that range (a cut past p10..p90
keeps under 10% of snapshots, and one past the min/max keeps none).

{guide}

{playbook}What this user's earlier research found (learn from it; do not repeat failures):
{memory}

Propose {count} distinct hypotheses for this idea, each walking the nine-phase method.
MAKE THE SET GENUINELY DIVERSE: span at least {span} DIFFERENT mechanisms and model structures,
NOT {count} variants of one threshold rule. The seed palette in your instructions is a starting
point, not a checklist — a well-motivated angle that is NOT on that list (an economic/structural
thesis, a literature-grounded academic idea, a classical statistical/econometric method, or a
novel mechanism of your own) counts for MORE, not less. Economic reasoning, academic rigor,
traditional hardcore statistics and modern ML are ALL welcome. Unless every sound mechanism here
is genuinely a pure rule, include at least one FITTED model (model.kind logistic or calibration,
or a `code` strategy with fit(window) — classical stat or ML, your choice).
Reply with the ONE JSON object specified in your instructions (the full "hypotheses" list with
mechanism, falsification_criteria, negative_control, null/alt hypotheses, min_sample and spec).""".format(
        brief=brief,
        profile=_market_profile(run["market"]),
        idea_label=idea_label,
        idea_framing=idea_framing,
        idea=idea[:1000],
        lens=lens,
        cross_options=_cross_market_options(run["market"]),
        market_label=MARKETS[run["market"]].label,
        market=run["market"],
        summary=json.dumps(_in_sample_summary(ds)),
        detect=_detectability_block(ds),
        calibration="\n".join(b for b in (_calibration_block(ds), _fair_value_block(ds), run.get("_leads"),
                                          research_leads.COUNTERPARTY_RULE if run.get("_leads_arm") else "")
                              if b),
        guide=specmod.research_guide(run["market"]),
        memory=_memory_block(memory),
        playbook=(run.get("_playbook") + "\n\n") if run.get("_playbook") else "",
        count=count,
        span=min(count, len(STRATEGY_FAMILIES)),
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
# Scheduled autopilot REVIEWS run on this catalog model, whatever the user's autopilot model. A
# review is ~26k input tokens every few minutes; on Opus that alone ate most of Bedrock's
# non-adjustable Opus tokens-per-day quota, pushing research (where model quality matters) down
# to Sonnet/Haiku. Chats and research keep the user's model. Empty or unknown = the user's model.
REVIEW_MODEL_KEY = os.getenv("APP_REVIEW_MODEL", "sonnet-4-5")
# Mirrors server.MAX_RESEARCH_PER_DAY. The manual Research endpoint enforces this per-user daily
# cap, but the autopilot — the biggest source of research volume — did not, so an operator's cap
# silently didn't apply where most runs come from. 0 = unlimited (preserves today's behavior).
MAX_RESEARCH_PER_DAY = int(os.getenv("APP_MAX_RESEARCH_PER_DAY", "0"))
# GLOBAL (all-user) backpressure: only CONCURRENCY runs execute at once, so when many autopilot users
# all launch research the shared queue piles deep and every run ages. Above this many active research
# runs, the autopilot stops launching MORE (reviews still run, so risk/position management is
# unaffected) until a slot frees. 0 = off (preserves today's behavior); set it for many-user load.
MAX_GLOBAL_ACTIVE_RESEARCH = int(os.getenv("APP_MAX_GLOBAL_ACTIVE_RESEARCH", "0"))


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
    """What the agent may know about the data: the in-sample window only, plus per-feature non-null
    coverage for THIS market so the proposer only reaches for features the market populates (a
    micro feature at 0% is empty here — proposing a model/filter on it just yields 0 trades)."""
    s = ds.summary()
    s["end"] = s.pop("out_of_sample_from")
    s.pop("decision_points", None)
    s["feature_coverage_pct"] = backtest.feature_coverage(ds)
    s["feature_p10_p50_p90"] = backtest.feature_ranges(ds)
    return s


def _research_system(market: str) -> str:
    if market in MARKETS and MARKETS[market].kind == "perpetual":
        # Keep the shared pre-registration/falsification/JSON instructions, while
        # removing binary settlement and model-family instructions for this instrument.
        return ("You are a disciplined quantitative researcher studying Bitcoin perpetuals.\n"
                + RESEARCH_SYSTEM[RESEARCH_SYSTEM.find("The SPECIFIC market"):]
                + "\nINSTRUMENT OVERRIDE: This run uses only the Bitcoin perpetual causal rule spec below. "
                  "Binary settlement, GBM/logistic/calibration and code strategies mentioned in shared "
                  "examples are unavailable. Never invent data or claim execution readiness.\n"
                + specmod.PERPETUAL_GUIDE)
    return RESEARCH_SYSTEM


class Cancelled(Exception):
    pass


class Superseded(Exception):
    """This worker no longer owns the run: the watchdog reaped it (re-queued or stopped) or another
    worker reclaimed it. The thread stops quietly instead of racing the owner as a zombie."""


# How long the run loop holds a paused session before giving up (frees the worker so a
# forgotten pause can't tie up a slot forever). Matches the worker's abandoned-run window.
PAUSE_POLL_SECONDS = 1.5
PAUSE_MAX_SECONDS = 20 * 60

def _reconnect(conn, cur):
    """A single model call can run for minutes; an idle DB connection can be dropped out from
    under it (RDS/idle timeout), so the next cursor use throws 'Packet sequence number wrong'
    and the whole run dies — and gets billed. Ping-reconnect in place before the writes that
    follow each LLM call and hand back a fresh cursor, so a dropped idle connection heals
    transparently instead. Best-effort: if the DB is genuinely down, the stale cursor is
    returned and the next execute raises, failing the run (which is still billed for work done)."""
    if conn is None:
        return cur
    try:
        conn.ping(reconnect=True)
        return conn.cursor()
    except Exception:
        return cur


def _bill(conn, user_id, usage, run_id, model=None):
    """Meter the tokens this run spent against the user's credits, at the price of
    the model that actually ran (`model` is its invokable modelId)."""
    if usage.input_tokens or usage.output_tokens:
        billing.charge_usage(conn, user_id, model or current_model(), usage.input_tokens, usage.output_tokens, run_id)


_DROPPED_SHOWN = 15


_SIBLING_MIN_DROPS, _SIBLING_MIN_MARKETS, _SIBLING_SHOWN = 3, 2, 6


def _recent_drops(cur, user_id: int, market: str) -> List[Dict]:
    """This market's recent drops, then its siblings' (same family; rows carry "market").
    Advisory only: a failed read just means the proposer isn't warned off old dead ends."""
    try:
        own = repo.dropped_theses(cur, user_id, market)
    except Exception:
        return []
    from app import rsi
    fam = rsi.family(market)
    siblings = [k for k in MARKETS if k != market and fam not in ("other", "unknown") and rsi.family(k) == fam]
    try:
        return own + repo.sibling_dropped_theses(cur, user_id, siblings)
    except Exception:
        return own


def _mechanism_of(h: Dict) -> Optional[str]:
    from app import rsi
    return rsi.mechanism(h.get("title"))


def _sibling_dead(rows: List[Dict], min_drops: int = _SIBLING_MIN_DROPS,
                  min_markets: int = _SIBLING_MIN_MARKETS) -> List[Tuple[str, List[Dict]]]:
    """(mechanism, its sibling drops newest first) for each mechanism dropped at least `min_drops`
    times on at least `min_markets` sibling markets, most-dropped first. Rows without "market"
    (this market's own drops) are ignored."""
    from app import rsi
    by: Dict[str, List[Dict]] = defaultdict(list)
    for d in rows:
        mech = d.get("market") and rsi.mechanism(d["title"])
        if mech:
            by[mech].append(d)
    return sorted(((m, v) for m, v in by.items()
                   if len(v) >= min_drops and len({d["market"] for d in v}) >= min_markets),
                  key=lambda kv: -len(kv[1]))


# A mechanism this dead on the siblings gets ONE developed idea per chunk; further proposals of it
# are set aside untested. Prod 2026-10-24 22:24Z (xrp15m, run 2721): with the sibling list in the
# prompt, 6 of 9 ideas were still calibration / mean reversion / vol mispricing, and all died.
_RATION_MIN_DROPS, _RATION_MIN_MARKETS = 6, 3
_NEVER_RATIONED = ("generic learned recalibration (logistic / multi-factor)",)


def _rationed_mechanisms(dropped: Optional[List[Dict]], run: Dict) -> Dict[str, int]:
    """{mechanism: sibling drops} for the mechanisms to ration on this run, leaving out the catch-all
    bucket and whatever the run's own prompt asks to study."""
    from app import rsi
    asked = rsi.mechanism(run.get("prompt") or "")
    return {m: len(v) for m, v in _sibling_dead(dropped or [], _RATION_MIN_DROPS, _RATION_MIN_MARKETS)
            if m not in _NEVER_RATIONED and m != asked}


def _sibling_block(rows: List[Dict], market: str) -> str:
    """Mechanisms that died again and again on this market's SIBLINGS, so a run on one crypto
    ladder stops re-testing what the other ladders already killed. Advice, not a ban: the market
    may differ, but the proposer has to say how."""
    dead = _sibling_dead(rows)[:_SIBLING_SHOWN]
    if not dead:
        return ""
    lines = []
    for mech, v in dead:
        ex = v[0]   # newest
        lines.append("- %s: dropped %d times on %d sibling markets (e.g. %s on %s: %s)" % (
            mech, len(v), len({d["market"] for d in v}), ex["title"], ex["market"],
            " ".join((ex.get("why") or "").split())[:160]))
    return ("\n\nMECHANISMS ALREADY DEAD ON SIBLING MARKETS (same family as %s, research fold only). These "
            "markets share its structure, so the same idea under a new name will most likely die the same way. "
            "Spend this run on mechanisms NOT in this list. Propose one of these only if you name the concrete "
            "way %s differs from the siblings that answers why it died there:\n" % (market, market)
            + "\n".join(lines))


def _dropped_block(dropped: Optional[List[Dict]], market: Optional[str] = None) -> str:
    """Theses already abandoned on this market (this run and recent ones), so the proposer stops
    re-proposing the same dead idea under a new title, then the mechanisms its siblings keep
    killing (rows with a "market"). Research-fold reasons only."""
    if not dropped:
        return ""
    sib = _sibling_block([d for d in dropped if d.get("market")], market or "this market")
    dropped = [d for d in dropped if not d.get("market")]
    if not dropped:
        return sib
    seen, lines = set(), []
    for d in dropped:
        key = d["title"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append("- %s: %s" % (d["title"], " ".join((d.get("why") or "").split())[:240]))
        if len(lines) >= _DROPPED_SHOWN:
            break
    return ("\n\nAlready ABANDONED on this market (dead on arrival on the research fold). Do NOT "
            "re-propose these or near-variants under a new name, including the same mechanism with a "
            "different model or threshold. Revisit one only if you name the specific new data or "
            "mechanism that answers the reason it died:\n" + "\n".join(lines) + sib)


def _round_prompt(run: Dict, ds: backtest.Dataset, memory: List[Dict], want: int, chunk: List[Dict],
                  dropped: Optional[List[Dict]] = None) -> str:
    """Round 1 asks fresh; later rounds show the agent its own in-sample results so it
    refines — the loop is a conversation with the data, not a fixed two-shot."""
    base = _research_prompt(run, ds, memory, want) + _dropped_block(dropped, run.get("market"))
    if not chunk:
        return base + THINK_ALOUD
    # Digest, not a dump: full detail for the best few to refine, bare titles for the rest so the
    # agent stays aware of what it tried (and doesn't repeat) without the prompt growing unbounded.
    ranked = sorted(chunk, key=lambda t: backtest.score(t["in_sample"]), reverse=True)
    detail = "\n".join(
        ("- %s: %s; spec=%s%s" % (t["title"], _metrics_line(t["in_sample"]),
                                  json.dumps(t["spec"], separators=(",", ":")),
                                  ("\n" + _attribution_line(t.get("attribution")))
                                  if _attribution_line(t.get("attribution")) else ""))
        for t in ranked[:12]
    )
    extra = ""
    if len(ranked) > 12:
        extra = "\nAlso already tested (do not repeat): " + "; ".join(t["title"] for t in ranked[12:])
    return (base + "\n\nResults so far this session (in-sample only; out-of-sample is held back):\n" + detail + extra
            + "\n\nThe 'edge-by-regime' line shows WHERE each rule's in-sample net edge sat (by price "
              "band, side, time-of-day). Use it to STRENGTHEN the economic mechanism — if the edge "
              "lives in one regime, say WHY it should (e.g. favorite-longshot overpricing lives in the "
              "cheap band) and condition on it. Do NOT bolt on filters that merely fit the strongest "
              "in-sample bucket: every refinement is re-judged on data you never see and spends from "
              "your statistical trial budget."
            + "\n\nPropose %d NEW, distinct hypotheses: refine what worked, drop what did not, "
              "and explain the change in each thesis." % want + THINK_ALOUD)


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


def _result_block(dataset_summary: Dict, t: Dict, classification: str, reason: Optional[str] = None,
                  reason_key: str = "challenger_reason") -> Dict:
    """The strategy.result the generator persists: research-fold metrics + the classification
    LABEL only. It deliberately carries NO held-out (validation/holdout) numbers, because
    strategy_memory feeds this straight back into the next prompt (closes Leak 2)."""
    block = {"capital": t.get("capital"), "dataset": dataset_summary,
             "in_sample": t.get("in_sample"), "classification": classification}
    if reason:
        block[reason_key] = reason[:500]
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
    # A cross-contract spec's experiment is keyed by its SHARED FDR stream (involved markets
    # joined), not the single run market — so its validation/holdout/n_trials all account on the
    # same stream the gatekeeper spends from. stream_key == the run market for a single-contract
    # spec, so that path is unchanged. The involved markets are recorded in data provenance.
    return gatekeeper.Prereg(
        user_id=run["user_id"], run_id=run["id"], market=specmod.stream_key(spec), spec=spec,
        economic_rationale=rationale,
        primary_metric=t.get("primary_metric") or "mean_net_return_per_trade",
        null_hypothesis=t.get("null_hypothesis", ""), alt_hypothesis=t.get("alt_hypothesis", ""),
        falsification_criteria=t.get("falsification_criteria", ""),
        min_sample=int(t.get("min_sample") or 30),
        cost_assumptions=(dict(spec["perpetual"], fill="next_open", funding="finalized_payments_as_cost_only",
                               scenario="one_times_notional_research_not_execution") if specmod.is_perpetual_spec(spec)
                          else {"fee": "kalshi_taker", "fill": "ask/bid"}),
        data_provenance={"features": specmod.features_used(spec),
                         "sources": specmod.data_sources_for(spec),
                         "markets": specmod.involved_markets(spec),
                         **({"source_version": partition.get("source_version"),
                              "data_fingerprint": partition.get("source_data_fingerprint", partition.get("data_fingerprint"))}
                            if specmod.is_perpetual_spec(spec) else {})},
        research_partition_id=int(partition.get("id") or 0),
        planned_n_tests=n_tests, correction_method="BH", strategy_id=strategy_id,
    )


def _promote_if_forward_validated(cur, user_id: int, experiment_id: int, finalist: Dict, t: Dict,
                                  log, run_id: Optional[int] = None) -> None:
    """§E.5 promotion. A finalist classified STAT_SUPPORTED on validation now gets the ONE-TIME
    Locked-Holdout evaluation; if it forward-validates, the marginal-contribution (diversification)
    gate promotes it FORWARD_VALIDATED -> DEPLOYMENT_CANDIDATE. This is the only path that mints a
    deployment candidate, so the deploy gate can finally clear.

    The holdout is a locked, single-use resource: `gatekeeper.judge_holdout` itself refuses
    (HoldoutConsumed) if the experiment is not STAT_SUPPORTED, already has a holdout verdict, or the
    window is at its evaluation cap — so a re-run never re-judges or burns it twice; we just log the
    skip. Anti-leak (Leak 2): exactly like the validation path, every held-out number goes to the
    FEED and the ledger ONLY — never into `_result_block`/strategy_memory — so the generator stays
    blind to holdout data. The strategy row keeps its validation status ("passed"); the deployment
    candidacy lives in the gatekeeper ledger, which is what `_is_deployment_candidate` reads."""
    # Bound the one-time holdout load the same way as the other data loads (timeout + heartbeat), so
    # a slow RDS fails fast with a clean error instead of tripping the watchdog mid-promotion.
    run_load = (lambda fn: _load("Loading holdout data", fn, beat=lambda: repo.heartbeat(cur, run_id))) \
        if (cur is not None and run_id is not None) else None
    try:
        verdict = gatekeeper.judge_holdout(cur, experiment_id, finalist, run_load=run_load)
    except gatekeeper.HoldoutConsumed as e:
        log("verdict", "%s: the one-time holdout was not evaluated (%s)." % (t["title"], e),
            {"title": t["title"], "phase": "holdout", "skipped": True})
        return
    hcls = verdict["classification"]
    log("verdict", "%s: one-time holdout verdict is gatekeeper-held (classification=%s, %s trades); "
                   "the numbers never return to the generator."
        % (t["title"], hcls, verdict.get("n_trades", 0)),
        {"title": t["title"], "phase": "holdout", "classification": hcls,
         "holdout_consumed": verdict.get("holdout_consumed"),
         "stats": {"n_trades": verdict.get("n_trades"), "p_value": verdict.get("p_value"),
                   "dsr": verdict.get("dsr"), "psr": verdict.get("psr"),
                   "ci": verdict.get("ci"), "mean_net_return": verdict.get("mean_net_return")}})
    if hcls != gatekeeper.Classification.FORWARD_VALIDATED.value:
        return
    ok, why = gatekeeper.marginal_contribution_ok(cur, user_id, experiment_id, finalist)
    final = (gatekeeper.Classification.DEPLOYMENT_CANDIDATE if ok
             else gatekeeper.Classification.FORWARD_VALIDATED).value
    log("verdict", "%s: diversification gate %s — %s." % (
            t["title"], "PASSED, promoted to DEPLOYMENT_CANDIDATE" if ok
            else "blocked (stays forward-validated, not deployable)", why),
        {"title": t["title"], "phase": "forward", "marginal_ok": ok, "classification": final})


@contextmanager
def _gate_tx(conn):
    """One atomic transaction for a chunk's ENTIRE write-section: freeze/pre-register the finalists,
    the gatekeeper's validation judging (which advances the LORD++ FDR stream + appends verdict
    rows), the strategy outcomes, and — last — the checkpoint's gate-cursor advance. All of it
    commits together or rolls back together, so a reclaim NEVER sees a half-judged chunk: either the
    whole chunk is gated AND the cursor moved past it (resume skips it), or nothing landed and the
    cursor still points at it (resume re-gates from the saved theses, re-pre-register being
    idempotent and the never-judged experiments invisible to the trial count). This is what proves
    resuming can't double-count a trial or double-spend alpha — it contains NO long model calls (the
    challenger ran before it), only fast DB writes + the in-memory validation backtests.

    On a real pymysql connection this is BEGIN..COMMIT/ROLLBACK. On a stub/None connection (unit
    tests, which stub the ledger writes and tolerate per-statement commits) it degrades to the plain
    cursor — the atomicity only matters against a real crash mid-commit, which tests don't exercise."""
    if conn is not None and hasattr(conn, "begin"):
        try:
            conn.ping(reconnect=True)  # heal a connection the minutes-long challenger may have idled out
        except Exception:
            pass
        with repo.transaction(conn) as cur:
            yield cur
    else:
        yield conn.cursor() if conn is not None else None


def _gate_and_save(cur, run: Dict, ds: backtest.Dataset, partition: Dict, chunk: List[Dict], log,
                   policy: exploration.ExplorationPolicy, model: ModelFn, usage: Usage, conn=None,
                   mark_gated=None) -> int:
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
    # Everything below is the chunk's one atomic write-section (see _gate_tx): the pre-registrations,
    # the gatekeeper's validation judging (which spends FDR alpha) and the gate-cursor advance all
    # commit together, so a reclaim can never re-judge a chunk that was already (fully or partly)
    # judged. The challenger above ran OUTSIDE it — it's the only minutes-long call here.
    with _gate_tx(conn) as cur:
        log("step", "Froze %d finalist%s; the challenger reviewed each before any validation budget was spent."
            % (len(finalists), "" if len(finalists) == 1 else "s"),
            {"phase": "gating", "finalists": len(finalists)})

        approved: List[Dict] = []
        exp_ids: List[int] = []
        payload: List[Dict] = []
        for t, verdict in zip(finalists, verdicts):
            spec = t["spec"]
            if verdict["decision"] == "revise" and verdict.get("fixes"):
                # Strip any frozen params before re-validating (validate() rejects unknown fields and
                # params is system-set, never agent-set), then RE-FREEZE: the revise may have changed
                # the code, so the model must be re-fit on research to stay consistent with the frozen
                # spec that gets pre-registered. No-op freeze for DSL / pure-rule code specs.
                base = {k: v for k, v in spec.items() if k != "params"}
                try:
                    revised = specmod.validate(_deep_merge(base, verdict["fixes"]))
                    spec = backtest.freeze_code_model(revised, ds) if specmod.is_code_spec(revised) else revised
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
            # Surface the challenger's APPROVE/REVISE call too (reject already logs above), so the
            # live feed shows the skeptic's verdict on every finalist, not only the kills.
            if verdict.get("reason"):
                log("challenger", "Challenger %s - %s: %s"
                    % ("revised" if verdict["decision"] == "revise" else "approved", t["title"], verdict["reason"]),
                    {"title": t["title"], "decision": verdict["decision"]})
            # Validation-budget pre-screen (research data only): a finalist whose research-fold edge
            # cannot plausibly clear the next alpha level is NOT pre-registered and spends nothing, so
            # it neither decays the LORD++ stream nor inflates the DSR trial count for real candidates.
            # Cross-contract and perpetual specs judge on their own windows and skip this screen.
            if not (specmod.is_cross_contract(spec) or specmod.is_multi_market(spec)
                    or specmod.is_perpetual_spec(spec)):
                pw = gatekeeper.validation_power(cur, user_id, market, spec, ds, partition,
                                                 int(t.get("min_sample") or 30))
                if not pw["ok"]:
                    t["strategy_id"] = repo.insert_strategy(
                        cur, user_id, run_id, parent, market, direction, t["title"], t["thesis"], spec,
                        "rejected", _result_block(s, t, "underpowered", pw["reason"], "gate_reason"))
                    log("verdict", "NOT TESTED - %s: %s. No validation budget spent."
                        % (t["title"], pw["reason"]),
                        {"title": t["title"], "status": "rejected", "strategy_id": t["strategy_id"],
                         "power": pw["power"]})
                    continue
            # Insert the strategy row FIRST (provisional) so the immutable experiment can carry its
            # strategy_id, then pre-register the frozen hypothesis.
            sid = repo.insert_strategy(cur, user_id, run_id, parent, market, direction, t["title"],
                                       t["thesis"], spec, "pending", _result_block(s, t, "promising"))
            t["strategy_id"] = sid
            # A multi-market spec (cross-market pair or pooled rule) pre-registers against the MERGED
            # partition of its markets; a single-market spec (including a same-market cross_strike /
            # calendar pair) against the run's partition.
            part = partitions.ensure_merged_partition(cur, specmod.involved_markets(spec)) \
                if specmod.is_multi_market(spec) else partition
            exp_ids.append(gatekeeper.preregister(cur, _prereg(t, spec, run, part, len(finalists), verdict, sid)))
            payload.append({"spec": spec, "user_id": user_id, "market": market,
                            "min_sample": int(t.get("min_sample") or 30)})
            approved.append(t)

        passed = 0
        if approved:
            # Judge per FDR stream: single-contract finalists share the run market's validation
            # window (one group, one BH family — unchanged); each cross-contract stream is judged on
            # its OWN merged validation window and spends its own shared budget.
            by_stream: Dict[str, List[int]] = defaultdict(list)
            for i, pay in enumerate(payload):
                by_stream[specmod.stream_key(pay["spec"])].append(i)
            for idxs in by_stream.values():
                spec0 = payload[idxs[0]]["spec"]
                # Bound the validation load like the startup load: beat the heartbeat while it runs
                # and fail fast with a clean LLMError if the (possibly slow) RDS wedges it, instead
                # of going silent until the watchdog reaps the run. Partitions are resolved on THIS
                # thread; the timeout worker only runs an off-cursor load, so it never shares `cur`.
                if specmod.is_multi_market(spec0):
                    legs = partitions.merged_partitions(cur, specmod.involved_markets(spec0))
                    val_ds = _load("Loading validation data", partitions.merged_dataset_from, legs,
                                   "validation", beat=lambda: repo.heartbeat(cur, run_id))
                else:
                    val_ds = _load("Loading validation data", backtest.partition_dataset, market,
                                   partition, "validation", beat=lambda: repo.heartbeat(cur, run_id))
                outcomes = gatekeeper.judge_batch(cur, run_id, [exp_ids[i] for i in idxs],
                                                  [payload[i] for i in idxs], val_ds)
                for i, outcome in zip(idxs, outcomes):
                    t = approved[i]
                    cls = outcome["classification"]
                    status = _status_for(cls)
                    passed += status == "passed"
                    repo.set_strategy_outcome(cur, t["strategy_id"], status, _result_block(s, t, cls), exp_ids[i])
                    # The stats go to the FEED (the user's own results, same as the strategy page) — NOT
                    # into _result_block, which feeds strategy_memory back to the GENERATOR. The generator
                    # stays blind to the held-out numbers (closes Leak 2); the human watching does not.
                    log("verdict", "%s - %s: validation verdict is gatekeeper-held (classification=%s, "
                                   "%s trades); the numbers never return to the generator."
                        % (status.upper(), t["title"], cls, outcome.get("n_trades", 0)),
                        {"title": t["title"], "status": status, "classification": cls,
                         "strategy_id": t["strategy_id"], "stats": {
                             "n_trades": outcome.get("n_trades"), "p_value": outcome.get("p_value"),
                             "dsr": outcome.get("dsr"), "psr": outcome.get("psr"),
                             "sharpe": outcome.get("sharpe"), "ci": outcome.get("ci"),
                             "mean_net_return": outcome.get("mean_net_return"),
                             "placebo_p": outcome.get("placebo_p"),
                             "max_drawdown": outcome.get("max_drawdown"),
                             "cross_day_ok": outcome.get("cross_day_ok")}})
                    # §E.5 promotion: a validation pass earns the ONE-TIME Locked-Holdout look and,
                    # if it forward-validates, the diversification gate that mints a DEPLOYMENT_CANDIDATE.
                    # Like validation, every number stays gatekeeper-held (feed + ledger only).
                    if cls == gatekeeper.Classification.STAT_SUPPORTED.value:
                        _promote_if_forward_validated(cur, user_id, exp_ids[i], payload[i], t, log, run_id)

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
        # LAST statement in the transaction: advance the checkpoint past this now-fully-gated chunk.
        # Atomic with the judging above — commit together or roll back together — which is what makes
        # a resume unable to re-judge a chunk (see _gate_tx / run_research.mark_gated).
        if mark_gated is not None:
            mark_gated(cur, passed)
    return passed


def _explore_and_gate(cur, run, ds, partition, memory, model, usage, log, checkpoint, budget, tried,
                      policy: exploration.ExplorationPolicy, conn=None, knowledge=None, news=None,
                      resume_chunk=None, resume_round=0, save_progress=None, mark_gated=None,
                      dropped: Optional[List[Dict]] = None, screen=None,
                      resume_pending=None) -> Tuple[int, int]:
    """Explore NEW hypotheses on the Research partition (small refining rounds the policy
    sizes), then hand the finalists to the challenger + gatekeeper. Appends to the shared
    `tried` so progress survives a cancel/error.

    On a RESUME, `resume_chunk` seeds the already-developed (not-yet-gated) theses and `resume_round`
    the round cursor, so this picks up proposing where it left off instead of re-developing them —
    the policy's `proposed=len(chunk)` then sizes the remaining batches toward `budget` exactly as an
    uninterrupted run would. `save_progress(chunk, round_no, pending)` persists the in-progress chunk
    and the proposed-but-undeveloped rest of the round (`pending`) before each thesis is developed,
    so a deploy restart or crash discards at most the thesis in flight; a resume develops
    `resume_pending` before proposing anything new (about 9 in 10 theses are dropped, so a run used to
    lose every proposal and drop of a chunk that had no survivor yet); `mark_gated` advances the
    checkpoint cursor atomically inside the gate transaction. `dropped` (newest first) seeds the
    theses recent runs abandoned; this chunk's own drops are added as they happen. A `screen` that
    is on (services.research_screen) writes the proposals and screens each thesis with its cheaper
    model; the run's model develops the survivors and challenges the finalists."""
    market = run["market"]
    dropped = dropped if dropped is not None else []
    chunk: List[Dict] = list(resume_chunk) if resume_chunk else []
    round_no = int(resume_round or 0)
    pending: List[Dict] = list(resume_pending or [])
    merged_cache: Dict[str, Tuple] = {}  # stream_key -> (merged research ds, embargo) for cross specs
    market_data = AgentMarketData(DataScope.research(ds.start_ts, ds.cutoff_ts), log, checkpoint)
    # Stream the proposer's generation into the feed so the multi-minute call isn't a silent gap.
    proposer = _stream_proposer(model, _StreamSink(log))
    # Wrap after streaming is configured: the knowledge adapter has the ordinary two-argument
    # model contract, but every underlying proposer call must still receive its live token sink.
    if news is not None:
        proposer = news.wrap(proposer, usage)
    if knowledge is not None:
        proposer = knowledge.wrap(proposer, usage)
    screener = None
    if screen is not None and screen.on:
        screener = _stream_proposer(screen.model, _StreamSink(log))
        if news is not None:
            screener = news.wrap(screener, screen.usage)
        if knowledge is not None:
            screener = knowledge.wrap(screener, screen.usage)
    attempts = 0  # theses DEVELOPED this chunk (survivors + abandoned), the real cost
    streak = 0  # consecutive drops, reset by any survivor
    bad_rounds = 0  # proposing rounds whose every spec failed validation
    spent: set = set()  # rationed mechanisms this chunk already developed one idea of
    aside_rounds = 0  # proposing rounds whose every idea was a rationed repeat
    while True:
        checkpoint()
        if pending:  # a resumed round: develop what was already proposed before proposing more
            batch, pending = pending, []
            log("step", "Resuming round %d with %d proposed hypothes%s not yet developed."
                % (round_no, len(batch), "is" if len(batch) == 1 else "es"),
                {"phase": "proposing", "round": round_no, "resumed": len(batch)})
        else:
            round_no += 1
            state = exploration.PolicyState(proposed=len(chunk), budget=budget, round=round_no)
            want = policy.next_batch(state).width
            if want <= 0:
                break  # policy decided to stop proposing this chunk
            if attempts >= budget * EXPLORE_ATTEMPT_MULT:
                # All-abandon backstop: survivors never reached `budget`, but we've already developed a
                # generous multiple of it. Stop burning the slot on a market with no tradeable surface.
                log("step", "No tradeable surface after %d attempts — stopping to free the worker." % attempts,
                    {"phase": "proposing", "attempts": attempts, "kept": len(chunk)})
                break
            if EXPLORE_MAX_DROP_STREAK and streak >= EXPLORE_MAX_DROP_STREAK:
                log("step", "Last %d theses all dropped on the research fold. Stopping proposals; %d kept go "
                    "to the gate." % (streak, len(chunk)),
                    {"phase": "proposing", "attempts": attempts, "kept": len(chunk), "drop_streak": streak})
                break
            # Announce each proposing round so the (multi-minute, token-streamed) generation call is
            # never a silent gap: the feed shows "Proposing round k" before the first token arrives.
            log("step", "Proposing round %d — generating up to %d hypothes%s…"
                % (round_no, want, "is" if want == 1 else "es"),
                {"phase": "proposing", "round": round_no, "width": want})
            check = _hypotheses_check(market, want)
            try:
                batch = market_data.ask(screener or proposer, _research_system(market),
                                        [{"role": "user", "content": _round_prompt(run, ds, memory, want, chunk, dropped)}],
                                        check, screen.usage if screener else usage)
            except LLMError as e:
                if "could not be used" not in str(e):
                    raise  # the model call itself failed (timeout, API): not a spec problem
                # Every idea in the batch stayed invalid through the repair rounds. That is a proposer or
                # schema bug, not evidence: log it as a dropped idea (the scoreboard counts it as
                # spec_invalid) and try one fresh round before giving up on proposing.
                bad_rounds += 1
                _abandon(log, {"title": "Proposing round %d" % round_no}, "spec invalid: %s" % e, None)
                if bad_rounds < 2:
                    continue
                if chunk:
                    break  # gate what this chunk already developed
                raise
            for bad in check.invalid:
                _abandon(log, bad, bad["why"], None)  # not added to `dropped`: the idea itself was never tested
            if not batch:
                break  # agent is out of fresh ideas this chunk
        rationed = _rationed_mechanisms(dropped, run)
        developed = attempts
        for i, h in enumerate(batch):
            checkpoint()
            if save_progress is not None:
                save_progress(chunk, round_no, batch[i:])  # this thesis and the rest, until each lands
            mech = _mechanism_of(h) if rationed else None
            if mech in rationed:
                if mech in spent:
                    why = ("not developed: %s already died %d times on sibling markets and this run spent "
                           "its one try on it" % (mech, rationed[mech]))
                    log("step", "Set aside untested: %s (%s)" % (h.get("title"), why),
                        {"phase": "proposing", "rationed": mech})
                    dropped.insert(0, {"title": h.get("title") or "", "why": why})
                    continue
                spent.add(mech)
            attempts += 1
            # Pillar 2: develop each thesis in depth on the RESEARCH FOLD (backtest -> critique ->
            # refine, up to THESIS_MAX_STEPS) before committing its single frozen spec. One candidate
            # out per hypothesis, so finalist selection + pre-registration are unchanged.
            t = _develop_thesis(h, run, ds, partition, memory, proposer, market_data,
                                 usage, log, checkpoint, round_no, cur, run["user_id"], merged_cache,
                                 dropped, screen, screener)
            if t is None:
                if save_progress is not None:
                    save_progress(chunk, round_no, batch[i + 1:])  # its drop is logged: never redevelop it
                streak += 1
                if EXPLORE_MAX_DROP_STREAK and streak >= EXPLORE_MAX_DROP_STREAK:
                    break  # don't develop the rest of this batch either
                continue  # abandoned (dead-on-arrival) thesis: no candidate, no trial spent
            streak = 0
            t["score"] = backtest.score(t["in_sample"])  # attach once, so the policy needs no backtester
            chunk.append(t)
            tried.append(t)
            # Durable checkpoint: persist the developed theses + round cursor as they land, so a
            # reclaim re-uses this (expensive) model work instead of re-exploring from scratch.
            if save_progress is not None:
                save_progress(chunk, round_no, batch[i + 1:])
        if save_progress is not None:
            save_progress(chunk, round_no, [])  # the round is done (or its rest deliberately skipped)
        if attempts == developed and batch:
            # Every idea this round was set aside: the proposer is stuck on rationed mechanisms.
            aside_rounds += 1
            if aside_rounds >= 2:
                log("step", "The proposer keeps returning mechanisms the sibling markets already killed. "
                    "Stopping proposals; %d kept go to the gate." % len(chunk),
                    {"phase": "proposing", "kept": len(chunk)})
                break
    challenger = news.wrap(model, usage) if news is not None else model
    if knowledge is not None:
        challenger = knowledge.wrap(challenger, usage)
    return len(chunk), _gate_and_save(cur, run, ds, partition, chunk, log, policy, challenger, usage,
                                      conn, mark_gated=mark_gated)


def _call_with_timeout(label: str, seconds: float, fn, *args, beat=None, beat_every: float = 5.0, **kwargs):
    """Run `fn` in a daemon thread and fail FAST with a clear LLMError if it hasn't returned within
    `seconds`, so a wedged startup step surfaces in minutes instead of sitting silent until the
    20-min watchdog. The worker runs in a thread (no SIGALRM available), so a thread+join is the
    portable guard. `beat` (if given) is called every `beat_every`s while we wait, to keep the run's
    heartbeat fresh during the long step. ponytail: a timed-out thread is a daemon left to unwind on
    its own — safe ONLY because the things we wrap here (the dataset load) hold their OWN resources
    (a separate DB connection they close themselves), never the run's cursor, so an abandoned thread
    can't corrupt the caller's connection; it dies with the worker. Upgrade path: cooperative
    cancellation if a wrapped call ever shares mutable state with the caller."""
    box: Dict = {}

    def _run():
        try:
            box["v"] = fn(*args, **kwargs)
        except BaseException as e:  # propagate the real error to the caller's thread
            box["e"] = e

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    waited = 0.0
    while waited < seconds:
        th.join(min(beat_every, seconds - waited))
        if not th.is_alive():
            break
        waited += beat_every
        if beat is not None:
            try:
                beat()
            except Exception:
                pass  # a heartbeat hiccup must not turn into a spurious timeout
    if th.is_alive():
        raise LLMError("%s timed out after %ds and was abandoned — the step is stuck; start the "
                       "session again." % (label, int(seconds)))
    if "e" in box:
        raise box["e"]
    return box.get("v")


def _load(label: str, fn, *args, beat=None):
    """Run a data load under the fail-fast DATA_LOAD_TIMEOUT (heartbeat beaten throughout), then
    relabel a RECOGNIZED load failure into a clean, specific LLMError (see _classify_load_error):
    a no-settled-contracts market or a transient RDS drop. An unrecognized error — a genuine bug —
    propagates unchanged, so this only ever classifies the two known cases."""
    for attempt in range(LOAD_RETRIES + 1):
        try:
            return _call_with_timeout(label, DATA_LOAD_TIMEOUT, fn, *args, beat=beat)
        except Exception as e:
            # A transient RDS drop is retryable in place (the load holds its own connection and is
            # read-only): back off briefly and try again before surfacing "data store was busy".
            if _is_transient_db_error(e) and attempt < LOAD_RETRIES:
                time.sleep(LOAD_RETRY_BACKOFF * (attempt + 1))
                if beat is not None:
                    try:
                        beat()  # keep the run's heartbeat fresh across the backoff
                    except Exception:
                        pass
                continue
            err = _classify_load_error(e)
            if err is not None:
                raise err from e
            raise


def _timeout_self_check() -> None:
    assert _call_with_timeout("fast", 5, lambda: 42) == 42, "returns the value of a fast call"
    try:
        _call_with_timeout("slow", 0.2, lambda: time.sleep(5), beat_every=0.05)
    except LLMError:
        pass
    else:
        raise AssertionError("a call that overruns must raise LLMError")
    try:
        _call_with_timeout("boom", 5, lambda: (_ for _ in ()).throw(ValueError("x")))
    except ValueError:
        pass
    else:
        raise AssertionError("the wrapped call's own exception must propagate")


class NoData(LLMError):
    """The chosen market has no backtest surface yet (no settled contracts / not enough history).
    This is NOT a failure — there is simply nothing to research there yet — so a run that ends this
    way finishes `stopped`, not `failed` (no red FAILED card for a dataless market)."""


def _classify_load_error(e: BaseException) -> Optional[LLMError]:
    """Turn a RECOGNIZED data-load failure into a clean, specific, user-facing LLMError so it stops
    surfacing as the generic 'unexpected error'. Returns None for anything unrecognized, so a genuine
    programming bug still propagates with its full traceback — this only relabels two known cases:
      - partitions.ensure_partition's 'no settled contracts' ValueError (a sports/un-settled market
        with no backtest surface yet), keeping the market in the message; and
      - a transient RDS drop (pymysql OperationalError 2006/2013 or a lost-connection / packet-
        sequence message), which is retryable, so we say so instead of failing opaque."""
    if isinstance(e, ValueError) and "no settled contracts" in str(e):
        m = re.search(r"market\s+'?([^'\s]+)'?", str(e))
        return NoData("%s has no settled contracts / backtest surface yet — pick a market with data."
                      % (m.group(1) if m else "That market"))
    if _is_transient_db_error(e):
        return LLMError("The data store was busy; please start the session again.")
    return None


def _is_transient_db_error(e: BaseException) -> bool:
    """A retryable DB drop: pymysql OperationalError with errno 2006 (server gone away) / 2013 (lost
    connection), or whose message names a lost connection / a packet-sequence desync."""
    import pymysql
    if not isinstance(e, pymysql.err.OperationalError):
        return False
    errno = e.args[0] if e.args else None
    if errno in (2006, 2013):
        return True
    msg = str(e).lower()
    return any(s in msg for s in ("lost connection", "gone away", "packet sequence number wrong"))


def _classify_self_check() -> None:
    import pymysql
    v = _classify_load_error(ValueError("no settled contracts for market 'kxnflgame' since X"))
    assert v is not None and "kxnflgame" in str(v), "no-settled-contracts keeps the market"
    assert _classify_load_error(pymysql.err.OperationalError(2013, "Lost connection")) is not None, \
        "a 2013 OperationalError is relabelled retryable"
    assert _classify_load_error(KeyError("boom")) is None, "a genuine bug is NOT swallowed"


def _should_dream(cur, user_id: int) -> bool:
    """Cross-run cadence for the end-of-run policy dream (Dream-RSI). Dreaming builds its tree from
    the user's ACCUMULATED validation history, so even a 1-chunk autopilot run can evolve the policy
    — but dreaming on every completion is wasteful. Dream when the user has never dreamed yet, or
    when >= DREAM_EVERY_RUNS research runs have completed since their last dream. Leak-safe: reads
    only run/event metadata, never a gatekeeper/holdout number, and touches nothing the gatekeeper,
    pre-registration or ledger own."""
    last = repo.latest_dream_event(cur, user_id)
    if last is None:
        return True
    return repo.count_runs(cur, user_id, "research", since=last["created_at"]) >= DREAM_EVERY_RUNS


def _dream_cadence_self_check() -> None:
    import app.agent as A
    orig_latest, orig_count = A.repo.latest_dream_event, A.repo.count_runs
    try:
        A.repo.latest_dream_event = lambda cur, uid: None
        assert _should_dream(None, 1), "a user who never dreamed should dream once there is a tree"
        A.repo.latest_dream_event = lambda cur, uid: {"created_at": 0}
        A.repo.count_runs = lambda cur, uid, kind, since=None, **k: 1
        assert not _should_dream(None, 1), "one run since the last dream is below the cadence"
        A.repo.count_runs = lambda cur, uid, kind, since=None, **k: DREAM_EVERY_RUNS
        assert _should_dream(None, 1), "hitting the cadence dreams again"
    finally:
        A.repo.latest_dream_event, A.repo.count_runs = orig_latest, orig_count


def _heartbeat_pump(run_id: int, progress: List[float], stop: threading.Event) -> None:
    """Background liveness beater for one research run (see RUN_HEARTBEAT_EVERY/RUN_STALL_SECONDS).
    Beats the run's DB heartbeat on a fixed cadence AS LONG AS the main thread has made progress
    within RUN_STALL_SECONDS, so a long legit phase stays alive while a frozen one goes quiet and is
    reaped. Uses its OWN DB connection — never the run's cursor, which belongs to the main thread and
    would desync if two threads shared it. Best-effort end to end: if it can't open a connection
    (e.g. unit tests with no DB) it simply exits, and the main thread's event/checkpoint beats still
    cover the common case. ponytail: one extra connection + daemon per run, negligible beside a run's
    backtests/model calls; it's the one place that makes 'no session ever stuck' uniform."""
    try:
        from data_pipeline.common import get_db_conn
        hb_conn = get_db_conn()
    except Exception:
        return
    try:
        while not stop.wait(RUN_HEARTBEAT_EVERY):
            last = max(progress[0], _BUSY_UNTIL.get(run_id, 0.0) - RUN_STALL_SECONDS)
            if time.monotonic() - last > RUN_STALL_SECONDS:
                continue  # main thread silent too long -> stop beating so the watchdog reaps it
            try:
                with hb_conn.cursor() as c:
                    repo.heartbeat(c, run_id)
                hb_conn.commit()
            except Exception:
                try:
                    hb_conn.rollback()
                except Exception:
                    pass
    finally:
        try:
            hb_conn.close()
        except Exception:
            pass


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
    sim0, wall0 = backtest.sim_seconds(), time.monotonic()

    def timing() -> Tuple[float, float]:
        return backtest.sim_seconds() - sim0, time.monotonic() - wall0
    # The run's model drives every LLM call it makes and the price it's billed at. An autopilot
    # research run is stamped with the user's autopilot_model at creation (act); a manual run
    # carries the model the user picked; NULL resolves to the catalog default. Tests pass `model`.
    choice = catalog.resolve(run.get("model"))
    # Model tiering A/B (services.research_screen): a screen-arm run proposes and screens on a
    # cheaper model. An injected model (tests) always runs unscreened, on that one model.
    screen_pick = research_screen.screen_choice(run_id, run.get("model")) if model is None else None
    leads_on = model is None and research_leads.in_leads_arm(run_id)  # data-first A/B, same rule
    if model is None:
        # on_delta=None keeps the ordinary (system, messages) calls working everywhere; the
        # proposer wraps this to pass a sink so its generation streams live into the feed.
        model = lambda system, messages, on_delta=None: claude(system, messages, choice.model_id, on_delta)  # noqa: E731
    # Tau-RSI: use the user's self-evolved exploration policy (sandboxed), or the
    # default if they have none yet. A new run then dreams up a better one (below).
    policy = dreaming.current_policy(cur, user_id)

    # Emergency recovery: a reclaimed run (worker crash / deploy restart / watchdog reap) re-enters
    # here with its exploration already persisted. Load the checkpoint so we resume from the saved
    # cursor instead of re-spending the model credits already explored; a fresh run has none.
    _ck = repo.load_checkpoint(cur, run_id)
    resuming = _ck is not None
    if resuming:
        tried = list(_ck.get("tried") or [])
    resume_chunk = list(_ck.get("chunk") or []) if resuming else []
    resume_round = int(_ck.get("round_no") or 0) if resuming else 0
    # Live mirror of what's persisted; save_progress / mark_gated mutate it and flush. `tried` is the
    # SAME list object _explore_and_gate appends to, so ckpt["tried"] always reflects the latest.
    ckpt = {
        "chunks_done": int((_ck or {}).get("chunks_done") or 0),
        "total_passed": int((_ck or {}).get("total_passed") or 0),
        "tried": tried, "chunk": resume_chunk, "round_no": resume_round,
        "market": (_ck or {}).get("market"), "lookback": (_ck or {}).get("lookback"),
        "dropped_n": int((_ck or {}).get("dropped_n") or 0),
        "pending": list((_ck or {}).get("pending") or []),
    }
    resume_pending = list(ckpt["pending"])

    def explored() -> int:
        """Every thesis the run worked on: developed ones (`tried`) plus those dropped on the research
        fold. The run's hypotheses_tried shows this, so an all-drop run reads "0 of 8", not "0 of 0"."""
        return len(tried) + ckpt["dropped_n"]

    def save_progress(chunk: List[Dict], round_no: int, pending: List[Dict] = ()) -> None:
        """Persist the in-progress (not-yet-gated) chunk as each thesis develops, so a reclaim
        re-uses that model work. An autocommit write OUTSIDE the gate transaction — ckpt["chunk"] is
        the 'un-gated work' marker that mark_gated clears atomically once the chunk is judged."""
        ckpt["chunk"], ckpt["round_no"], ckpt["tried"], ckpt["pending"] = chunk, round_no, tried, list(pending)
        repo.save_checkpoint(cur, run_id, ckpt)

    def mark_gated(gate_cur, passed: int) -> None:
        """The LAST write inside the gate transaction: advance the cursor past a now-fully-gated
        chunk and clear the in-progress chunk, atomically with that chunk's judging. A resume then
        either skips the chunk (cursor moved) or re-gates it from the saved theses (rolled back) —
        it can never re-judge, so no trial is double-counted and no FDR alpha double-spent."""
        ckpt["chunks_done"] += 1
        ckpt["total_passed"] += passed
        ckpt["chunk"], ckpt["round_no"], ckpt["tried"], ckpt["pending"] = [], 0, tried, []
        repo.save_checkpoint(gate_cur, run_id, ckpt)

    paused_at = [0.0]  # when the current pause began (0 = not paused); list so the closure can mutate it
    # Liveness clock for the background beater: the main thread stamps it on every real step so the
    # beater knows the run is progressing (and a frozen main thread lets it go stale -> reaped).
    progress = [time.monotonic()]
    model = _alive_during_calls(model, progress)
    screen = research_screen.Screen(run_id)
    if screen_pick is not None:
        screen.choice = screen_pick
        screen.model = _alive_during_calls(
            lambda system, messages, on_delta=None: claude(system, messages, screen_pick.model_id, on_delta),
            progress)

    def bill_screen() -> Tuple[int, int]:
        """Bill the screen model's tokens at its own price; returns (input, output) for the totals."""
        spent = screen.drain()
        if screen_pick is not None:
            _bill(conn, user_id, Usage(**spent), run_id, screen_pick.model_id)
        return spent["input_tokens"], spent["output_tokens"]

    verdicts: Dict[str, int] = defaultdict(int)  # gatekeeper verdicts this run, for the outcome line

    def log(kind: str, message: str, data: Optional[Dict] = None) -> None:
        progress[0] = time.monotonic()
        if kind == "verdict" and data and data.get("classification"):
            verdicts["%s:%s" % (data.get("phase") or "validation", data["classification"])] += 1
        elif kind == "verdict" and data and data.get("status") == "abandoned":
            verdicts["research:dropped"] += 1  # died on the research fold, never gated (tried excludes it)
            ckpt["dropped_n"] += 1
        repo.add_event(cur, run_id, kind, message, data)

    def checkpoint() -> None:
        """Called at every safe point between/after LLM calls. It (1) ping-reconnects the DB so a
        write that follows a minutes-long model call never dies on a dropped idle connection
        (ponytail: one COM_PING per checkpoint, negligible beside the backtests), (2) stops on a
        cancel, and (3) holds here while the user has the session paused — resuming picks up exactly
        where it left off (same in-memory state, same worker)."""
        nonlocal cur
        progress[0] = time.monotonic()
        cur = _reconnect(conn, cur)
        status = repo.heartbeat(cur, run_id)
        if status == "cancelled":
            raise Cancelled()
        owner = run.get("worker_id")
        if status not in ("running", "paused") or (owner and repo.run_worker(cur, run_id) != owner):
            raise Superseded()
        while status == "paused":
            if not paused_at[0]:
                paused_at[0] = time.monotonic()
                log("paused", "Paused — holding here. Resume and I pick up exactly where I left off.")
            if time.monotonic() - paused_at[0] > PAUSE_MAX_SECONDS:
                log("step", "Paused too long — stopping to free the worker. Start a new session to continue.")
                raise Cancelled()
            time.sleep(PAUSE_POLL_SECONDS)
            cur = _reconnect(conn, cur)
            status = repo.heartbeat(cur, run_id)  # keeps heartbeat_at fresh so the run isn't reaped
            if status == "cancelled":
                raise Cancelled()
        if paused_at[0]:
            paused_at[0] = 0.0
            log("resumed", "Resumed.")

    # Start the background liveness beater: keeps the heartbeat fresh through long silent phases so
    # the tight watchdog only reaps a genuinely frozen run (see _heartbeat_pump). Stopped in finally.
    _hb_stop = threading.Event()
    threading.Thread(target=_heartbeat_pump, args=(run_id, progress, _hb_stop),
                     name="research-heartbeat-%s" % run_id, daemon=True).start()
    try:
        # Emit the INSTANT the run is claimed, before any expensive work, so a healthy startup and a
        # hung one no longer look identical (both used to be silent until the first "Loaded" event,
        # minutes later). This event also bumps the heartbeat (repo.add_event), so the run reads as
        # alive the moment it starts.
        log("step", "%s %s…"
            % ("Resuming — re-using %d explored hypotheses, preparing" % len(tried) if resuming
               else "Research started — preparing",
               MARKETS[market].label if market in MARKETS else "the chosen market"),
            {"phase": "start", "market": market or None, "resumed": resuming,
             "screen_model": screen_pick.key if screen_pick else None})
        if market and market not in MARKETS and run.get("brief") and not ckpt.get("market"):
            # The autopilot named a catalog market that dropped out of the universe before the run
            # started (catalog refresh / restart). Keep the angle and let the picker choose instead
            # of failing the run; a user-pinned market still fails cleanly below.
            log("step", "%s is no longer in the market list — picking another market for this angle." % market)
            market = None
        if (market and run.get("brief") and not ckpt.get("market")
                and not focus_keys(cur, user_id, [market])):
            # A delegated run queued on a market outside the user's focus (an older queue entry, or
            # another path): keep the angle, let the picker choose inside the focus.
            log("step", "%s is outside your autopilot focus — picking a market inside it for this angle."
                % (MARKETS[market].label if market in MARKETS else market))
            market = None
        if not market:  # user left it to the agent — it picks the market from the idea first
            if resuming and ckpt.get("market"):
                market = ckpt["market"]  # already chosen on the first attempt; don't re-spend the pick
            else:
                checkpoint()
                blocked = _research_blocked_markets(cur, user_id)
                ready = focus_keys(cur, user_id, _researchable_keys(cur))
                if not ready:
                    raise RuntimeError("No market inside your autopilot focus is open for research right now.")
                keys = [k for k in ready if k not in blocked] or ready
                market = _pick_market(run, model, usage, log, keys, _research_history_line(cur, user_id))
            run = {**run, "market": market}
            repo.set_run_market(cur, run_id, market)
        # A pinned market that has left the live universe (a retired/renamed catalog series) would
        # otherwise surface as a bare KeyError the instant the first MARKETS[market] lookup runs in
        # setup — the useless "Unexpected error: '<key>'" this very guard replaces. Fail cleanly
        # here, the one place every research run funnels through before that lookup. (A market the
        # agent PICKED is already validated against MARKETS in _pick_market; this catches the pin.)
        if market not in MARKETS:
            raise LLMError("The market %r is no longer available for research. Pick another market "
                           "and start a new session." % market)
        ckpt["market"] = market  # persisted with the first save_progress, so a resume keeps this market
        # Freeze the Research/Validation/Holdout split once for the run; the generator may load
        # ONLY the Research window (partitions.research_dataset), and the gatekeeper keeps the
        # validation/holdout keys. Tests inject dataset_fn to supply a synthetic research set.
        partition = partitions.ensure_partition(cur, market)
        load = dataset_fn or (lambda mk, hd=None: partitions.research_dataset(mk, partition, hd))
        # The dataset load (history query + in-memory build) is the one step that runs BEFORE the
        # first heartbeat/event — the proven startup-hang site (prod run 397/407: claimed, then
        # zero events/heartbeat for 20 min). Announce it (so a stall is visible to the phase), beat
        # the heartbeat while it runs, and hard-bound it so a wedge fails fast with a clear error.
        log("step", "Loading %s market data…" % MARKETS[market].label, {"phase": "loading", "market": market})
        ds = _load("Loading %s data" % MARKETS[market].label, load, market,
                   beat=lambda: repo.heartbeat(cur, run_id))
        if len(ds.frames) < MIN_FRAMES:
            raise NoData("Not enough market history collected yet for %s." % MARKETS[market].label)
        # The agent picks the window that fits its thesis; re-load the narrower slice if it
        # chose less, and keep the fuller one if the slice is too thin to be worth it.
        checkpoint()  # a cancel must stop before we spend a model call on planning
        if resuming and ckpt.get("lookback") is not None:
            lookback = int(ckpt["lookback"])  # chosen on the first attempt; don't re-spend the plan call
        else:
            lookback = _plan_lookback(run, market, model, usage, log)
        ckpt["lookback"] = lookback
        repo.save_checkpoint(cur, run_id, ckpt)  # a restart reuses the market and lookback plan
        if lookback < MARKETS[market].history_days:
            # Drop the full set before loading the slice: holding both doubled the peak, and a
            # 1-minute sports market is ~0.5-1GB of snapshots on its own. A too-thin slice (rare)
            # pays one more load of the full set instead.
            ds = None
            narrowed = _load("Loading %s data" % MARKETS[market].label, load, market, lookback,
                             beat=lambda: repo.heartbeat(cur, run_id))
            if len(narrowed.frames) >= MIN_FRAMES:
                ds = narrowed
            else:
                narrowed = None
                ds = _load("Loading %s data" % MARKETS[market].label, load, market,
                           beat=lambda: repo.heartbeat(cur, run_id))
        s = ds.summary()
        log("step", "Loaded %s of %s history: %s decision points over %s contracts."
            % (_span_words(ds), MARKETS[market].label, s["decision_points"], s["contracts"]),
            dict(s, phase="data_loaded"))
        playbook = _rsi_choose(cur, user_id, market, run_id, log)
        if playbook:
            run = {**run, "_playbook": playbook}
        # Data-first A/B (services.research_leads): a leads-arm run scans every feature cell for
        # measured mispricing before the first proposal, and its prompts build on what it finds.
        scan = None
        if leads_on:
            log("step", "Scanning every feature x life x price cell for measured mispricing…",
                {"phase": "scanning"})
            try:
                scan = research_leads.scan_dataset(ds)
                run = {**run, "_leads": research_leads.block(scan), "_leads_arm": True}
            except Exception as e:  # noqa: BLE001 - the scan is an aid; the run goes on without it
                _LOG.exception("lead scan failed on run %s", run_id)
                log("step", "Lead scan skipped (%s)." % e)
        log("verdict", ("Lead scan: %d of %d cells survive the false-discovery control."
                        % (len(scan["leads"]), scan["tests"])) if scan else
            "Lead scan: control arm, hypotheses first.", research_leads.summary(bool(scan), scan))
        budget = max(1, min(int(run.get("max_hypotheses") or DEFAULT_HYPOTHESES), MAX_BUDGET))
        knowledge = AgentKnowledge(DataScope.research(ds.start_ts, ds.cutoff_ts), log, checkpoint)
        news = AgentNews(DataScope.research(ds.start_ts, ds.cutoff_ts), log, checkpoint)
        forever = bool(run.get("run_forever"))
        log("step", "Plan: explore %s, refining each round on the in-sample results, then gate the best on data never seen.%s"
            % ("hypotheses until you stop it" if forever else "up to %d hypotheses" % budget,
               " I'll keep going until you stop me." if forever else ""))

        # Counters seed FROM the checkpoint so a resume continues the tally rather than restarting it.
        total_passed, tot_in, tot_out, chunks = ckpt["total_passed"], 0, 0, ckpt["chunks_done"]
        # A reclaimed BOUNDED run whose single chunk already gated (cursor moved, no in-progress
        # chunk) has nothing left to explore — go straight to finish so we never re-gate it.
        already_complete = (not forever) and chunks >= 1 and not resume_chunk and not resume_pending
        while not already_complete:
            checkpoint()
            # Reload memory each chunk so a run_forever loop learns from the strategies it
            # just saved, instead of re-proposing the same ideas.
            memory = repo.strategy_memory(cur, user_id, market)
            dropped = _recent_drops(cur, user_id, market)
            n, passed = _explore_and_gate(cur, run, ds, partition, memory, model, usage, log, checkpoint,
                                          budget, tried, policy, conn, knowledge, news,
                                          resume_chunk=resume_chunk, resume_round=resume_round,
                                          save_progress=save_progress, mark_gated=mark_gated,
                                          dropped=dropped, screen=screen, resume_pending=resume_pending)
            resume_chunk, resume_round, resume_pending = [], 0, []  # only the first iteration resumes
            # mark_gated advanced these atomically with the chunk's judging; read them back.
            total_passed, chunks = ckpt["total_passed"], ckpt["chunks_done"]
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
            s_in, s_out = bill_screen()
            tot_in, tot_out = tot_in + s_in, tot_out + s_out
            repo.update_run_progress(cur, run_id, explored(), total_passed)  # keep counts live
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
                % (explored(), total_passed))

        # Dreaming: learn a better exploration policy from the user's accumulated history, validated
        # on the replay simulator (no new backtests). Gated by a CROSS-RUN cadence (_should_dream),
        # not the within-run DREAM_EVERY_CHUNKS gate, so even a 1-chunk autopilot run evolves the
        # policy on a regular schedule while bounded runs stay cheap. Bill its tokens; never let a
        # dreaming hiccup fail the run.
        try:
            if _should_dream(cur, user_id) and dreaming.evolve_policy(conn, user_id, market, model, usage, log):
                tot_in += usage.input_tokens
                tot_out += usage.output_tokens
                _bill(conn, user_id, usage, run_id, choice.model_id)
                usage.input_tokens = usage.output_tokens = 0
                conn.commit()
        except Exception as e:  # dreaming is best-effort; the run still succeeds
            log("step", "Policy-evolution step skipped (%s)." % e)

        # Research RSI: score this run against the playbook it drew, settle the A/B, and rewrite the
        # playbook from this run's verdicts. Billed like dreaming; a hiccup never fails the run.
        if explored():
            _rsi_learn(conn, cur, run, ds, explored(), tot_in, tot_out, model, usage, log)
            if usage.input_tokens or usage.output_tokens:
                tot_in += usage.input_tokens
                tot_out += usage.output_tokens
                _bill(conn, user_id, usage, run_id, choice.model_id)
                usage.input_tokens = usage.output_tokens = 0
            conn.commit()

        log("verdict", screen.message(), screen.summary())
        log("done", "%d of %d hypotheses passed every gate%s." % (
            total_passed, explored(), " (%d dropped on research data)" % ckpt["dropped_n"] if ckpt["dropped_n"] else ""),
            {"passed": total_passed, "tried": explored(), "dropped": ckpt["dropped_n"]})
        repo.finish_run(cur, run_id, "succeeded", None, explored(), total_passed, tot_in, tot_out)
        print(research_outcome_line(run_id, user_id, market, "succeeded", explored(), total_passed,
                                    tot_in, tot_out, choice.model_id, verdicts, timing=timing()), flush=True)
    except Superseded:
        # No event and no finish_run: the run's new owner (or the reaper) holds its record now.
        _bill(conn, user_id, usage, run_id, choice.model_id)  # tokens this thread spent are still real
        bill_screen()
        print("[research] run=%s superseded on worker %s; stopping this copy" % (run_id, run.get("worker_id")),
              flush=True)
    except Cancelled:
        _bill(conn, user_id, usage, run_id, choice.model_id)  # charge whatever was spent before the stop
        bill_screen()
        log("step", "Cancelled.")
    except Exception as e:  # the run fails visibly; the worker keeps going
        # The user-facing msg below stays clean, but a bare str(e) (e.g. a KeyError prints just its
        # missing key) throws the stack away and makes the next mystery crash undiagnosable. Dump
        # the full traceback to the PROCESS log (stderr -> the worker's logfile) so it survives.
        _LOG.exception("research run %s failed", run_id)
        # Relabel the unambiguous no-settled-contracts ValueError (raised by partitions.ensure_*,
        # which the _load wrapper doesn't cover) into a clean, specific LLMError so it stops reading
        # as the generic 'unexpected error'. A transient RDS OperationalError is classified only at
        # the _load boundary (so a drop on a NON-load DB call still propagates for worker reclaim,
        # unchanged); anything else is left untouched and still propagates below.
        if isinstance(e, ValueError):
            e = _classify_load_error(e) or e
        # A no-data market (no settled contracts / not enough history) is NOT a failure — there's just
        # nothing to research there yet — so it finishes `stopped` (neutral), never a red FAILED. Only a
        # genuine error (API/DB/unexpected) is `failed`, matching the watchdog-reap semantics.
        no_data = isinstance(e, NoData)
        msg = (str(e) if isinstance(e, LLMError) else "The session hit an unexpected error and stopped.")
        cur = _reconnect(conn, cur)  # the error may have been the drop itself — heal it so we can record the outcome
        log("step" if no_data else "error", msg)
        repo.finish_run(cur, run_id, "stopped" if no_data else "failed", msg[:2000],
                        explored(), 0, usage.input_tokens, usage.output_tokens)
        print(research_outcome_line(run_id, user_id, market, "stopped" if no_data else "failed", explored(), 0,
                                    usage.input_tokens, usage.output_tokens, choice.model_id, verdicts,
                                    type(e).__name__, timing=timing()), flush=True)
        _bill(conn, user_id, usage, run_id, choice.model_id)  # charge for the work done regardless of the failure cause
        bill_screen()
        if not isinstance(e, LLMError):
            raise
    finally:
        _hb_stop.set()  # stop the background heartbeat beater on every exit path


def research_outcome_line(run_id, user_id, market, status: str, tried: int, passed: int, tokens_in: int,
                          tokens_out: int, model_id: str, verdicts: Dict[str, int], error: str = "",
                          timing: Optional[Tuple[float, float]] = None) -> str:
    """One greppable process-log line per finished research run, so the funnel (hypotheses tried,
    gatekeeper verdicts, passes) and its token cost can be read from the worker log alone. The
    tokens_in/out are what was billed at finish (a failed run's are the unbilled remainder).
    ``timing`` is (seconds in backtest.simulate, run wall seconds), logged with the backtest engine."""
    v = ",".join("%s=%d" % (k, n) for k, n in sorted(verdicts.items())) or "none"
    t = (" backtest_s=%.1f run_s=%.1f engine=%s" % (timing[0], timing[1], backtest.ENGINE)) if timing else ""
    return ("[research] run=%s user=%s market=%s status=%s tried=%d passed=%d tokens_in=%d tokens_out=%d "
            "model=%s verdicts=%s%s%s" % (run_id, user_id, market, status, tried, passed, tokens_in, tokens_out,
                                          model_id, v, t, (" error=%s" % error) if error else ""))


def _span_words(ds: backtest.Dataset) -> str:
    days = (ds.end_ts - ds.start_ts) / 86400.0
    return "%d days" % round(days)


@contextmanager
def _busy(run_id: Optional[int], seconds: float):
    """The run's main thread is in a bounded long step: the heartbeat pump keeps beating up to
    `seconds` without progress stamps (a wedge inside it is still reaped after that)."""
    if run_id is None:
        yield
        return
    _BUSY_UNTIL[run_id] = time.monotonic() + seconds
    try:
        yield
    finally:
        _BUSY_UNTIL.pop(run_id, None)


def _test_in_sample(h: Dict, ds: backtest.Dataset, partition: Dict, log, round_no: int,
                    cur=None, merged_cache: Optional[Dict] = None, run_id: Optional[int] = None) -> Dict:
    with _busy(run_id, BACKTEST_GRACE_SECONDS):
        return _test_in_sample_inner(h, ds, partition, log, round_no, cur, merged_cache, run_id)


def _test_in_sample_inner(h: Dict, ds: backtest.Dataset, partition: Dict, log, round_no: int,
                          cur=None, merged_cache: Optional[Dict] = None, run_id: Optional[int] = None) -> Dict:
    # The in-research "OOS" the agent iterates on is a PURGED walk-forward research fold (fully
    # inside Research) — a leak-free sandbox it may look at freely, not the held-out validation
    # window. Purge/embargo come from the frozen partition's contract-duration horizon (§B.5).
    spec = h["spec"]
    rds, embargo = ds, int(partition["embargo_seconds"])
    # A cross-SECTIONAL pair spans >1 market, so its legs aren't in the single-market research
    # dataset — test it on the MERGED research window of its legs (cached per stream for the run).
    # cross_strike / calendar stay on one market, so the single-market dataset already has every
    # strike/settlement and this branch is skipped.
    if cur is not None and specmod.is_multi_market(spec):
        inv = specmod.involved_markets(spec)
        key = specmod.stream_key(spec)
        if merged_cache is not None and key in merged_cache:
            rds, embargo = merged_cache[key]
        else:
            try:
                embargo = int(partitions.ensure_merged_partition(cur, inv)["embargo_seconds"])
                # Same fail-fast wrap as the other data loads: resolve the legs on this thread, then
                # run the off-cursor merged build under the timeout so a slow RDS can't wedge it.
                legs = partitions.merged_partitions(cur, inv)
                beat = (lambda: repo.heartbeat(cur, run_id)) if run_id is not None else None
                rds = _load("Loading %s research data" % key, partitions.merged_dataset_from, legs,
                            "research", beat=beat)
            except NoData as e:
                rds = e  # cached too, so a re-proposal of the same set doesn't re-query
            except ValueError as e:
                if _classify_load_error(e) is None:
                    raise
                rds = _classify_load_error(e)
            if merged_cache is not None:
                merged_cache[key] = (rds, embargo)
        if isinstance(rds, NoData):
            # A pool/cross leg with no settled history (a freshly catalogued city still backfilling)
            # fails THIS hypothesis with a reason the agent can act on, not the whole run (run 2599).
            return _no_surface(h, spec, log, round_no, "a pooled/cross market has no history yet (%s) — "
                               "drop it and use only markets with data" % rds)
    # Fit-on-research-and-FREEZE before the hypothesis is tested or pre-registered, so the spec
    # handed to the gatekeeper IS the frozen model — scored on validation/holdout it never saw,
    # with no re-fit at test time. Two complementary freezers, each a no-op for the other's spec
    # type: (1) a DSL learned model (logistic/calibration) freezes its coefficients; (2) a `code`
    # strategy that defines fit(window) freezes its trained params into the spec. gbm / pure-rule
    # specs pass through untouched. Carry the frozen spec forward on `h`.
    diag: Dict = {}
    spec = backtest.fit_spec_on_research(spec, rds, diag)
    spec = backtest.freeze_code_model(spec, rds, diag)
    h = dict(h, spec=spec)
    res = backtest.research_fold_metrics(spec, rds, embargo)
    ins = res["in_sample"]
    diagnosis = _diagnose(spec, rds, ins, diag)  # "" when the spec fit and traded fine
    # Carry the whole pre-registration (thesis, mechanism, the actual spec/code, falsification
    # criteria, negative control) so the live feed can tell the full story of each hypothesis —
    # intuition -> spec/code -> critique -> verdict — not just its name. `diagnosis` tells the
    # user (run page) and the agent (develop prompt) WHY a model was left unfitted or took 0
    # trades, so a dead-on-arrival thesis is visible instead of a silent "coef:[] / 0 trades".
    log("hypothesis", h["title"], {
        "thesis": h["thesis"], "mechanism": h.get("mechanism") or {},
        "falsification": h.get("falsification_criteria") or "",
        "negative_control": h.get("negative_control") or "",
        "primary_metric": h.get("primary_metric") or "",
        "spec": h["spec"], "in_sample": ins, "round": round_no,
        "diagnosis": diagnosis or None})
    return dict(h, in_sample=ins, capital=res["capital"], attribution=res.get("attribution"),
                diagnosis=diagnosis)


def _no_surface(h: Dict, spec: Dict, log, round_no: int, diagnosis: str) -> Dict:
    """A 0-trade result for a hypothesis whose data can't be loaded; _develop_thesis then refines
    it (e.g. drops the dataless leg) or drops it, and finalist selection never sees 0 trades."""
    capital = spec["sizing"]["stake"] * spec["sizing"]["max_positions"]
    ins = backtest.metrics([], capital, 1e-9)
    ins.pop("_curve", None)
    log("hypothesis", h["title"], {"thesis": h.get("thesis"), "spec": spec, "in_sample": ins,
                                   "round": round_no, "diagnosis": diagnosis})
    return dict(h, in_sample=ins, capital=capital, attribution={}, diagnosis=diagnosis)


def _diagnose(spec: Dict, rds: backtest.Dataset, ins: Dict, diag: Dict) -> str:
    """One concrete sentence for a no-edge outcome, or "" when the spec fit and traded. An unfit
    learned model (its feature is null for this market) wins over the 0-trade reason — that is the
    root cause the agent must see to stop loosening thresholds that can never fire."""
    if diag.get("reason") and not specmod.is_fitted(spec):
        return "model left UNFITTED: " + diag["reason"]
    if diag.get("code_fit_failed"):
        # A code strategy's fit() raised, so it ran WITHOUT a frozen model (likely ~0 trades). Give
        # the agent the actual cause instead of a silent 0-trade result — a single-class training
        # window (all wins or all losses) is the usual one.
        return ("your fit() raised and the strategy ran WITHOUT a frozen model: %s — a single-class "
                "training window (all wins or all losses) is the usual cause; fit on a market/window "
                "with both outcomes, or drop fit() for a rule-based signal." % diag["code_fit_failed"])
    if not ins.get("trades"):
        return backtest.zero_trade_reason(spec, rds)
    return ""


_FEATURE_BLOCK: Dict[str, object] = {"ds": None, "text": ""}


def _feature_block(ds) -> str:
    """The populated features on this market with coverage and p10/p50/p90, for the develop turn.
    Run 2613 abandoned 5 of 8 weather theses believing obs_high_f / fcst_high_f were unavailable
    (both populated) because only the proposing round showed coverage. Cached per dataset."""
    if ds is None or not getattr(ds, "frames", None):
        return ""
    if _FEATURE_BLOCK["ds"] is ds:
        return _FEATURE_BLOCK["text"]
    try:
        cov = backtest.feature_coverage(ds)
        rng = backtest.feature_ranges(ds)
    except Exception:  # noqa: BLE001 - a summary hiccup must not stop development
        return ""
    rows = ["%s %d%% %s" % (n, c, rng.get(n, "")) for n, c in sorted(cov.items()) if c > 0]
    text = ("\nFeatures populated on THIS market (name, % of snapshots, [p10, p50, p90]) - anything "
            "listed IS available to filters/models/code; anything missing is not:\n" + "\n".join(rows)
            ) if rows else ""
    if text:
        text += _contract_fields_line(ds)
    _FEATURE_BLOCK.update(ds=ds, text=text)
    return text


def _contract_fields_line(ds) -> str:
    """The per-contract fields a code window carries beside the features, measured. Without it
    "anything missing is not" read as "no strike, no game grouping": runs 2761/2772/2775 dropped
    sports ladder theses as missing_context although every ladder row has a real strike."""
    strikes, events = {}, {}
    for _ts, snaps in ds.frames:
        for sn in snaps:
            t = sn.contract.ticker
            if t not in strikes:
                strikes[t] = float(sn.contract.strike or 0.0)
                ev = t.rsplit("-", 1)[0]
                events[ev] = events.get(ev, 0) + 1
    if not strikes:
        return ""
    real = sorted(v for v in strikes.values() if v)
    sizes = sorted(events.values())
    strike_txt = ("strike (nonzero on %d%% of contracts, p10/p50/p90 %g/%g/%g)"
                  % (100 * len(real) // len(strikes), real[len(real) // 10], real[len(real) // 2],
                     real[9 * len(real) // 10]) if real else "strike (0.0 on every contract: no thresholds)")
    return ("\nPer-contract fields in a code window (not features): ticker, %s, event (%d events, median "
            "%d contracts each: contracts sharing an event are one ladder / one game), close_ts."
            % (strike_txt, len(sizes), sizes[len(sizes) // 2]))


def _develop_prompt(run: Dict, t: Dict, memory: List[Dict], step: int, ds=None) -> str:
    """One per-thesis refine turn (Pillar 2). Shows ONLY the research fold: this thesis's current
    spec, its research-fold metrics + edge-by-regime, and the user's prior-research LABELS — the
    same leak-free surface the batch rounds use. Never a validation/holdout number."""
    attr = _attribution_line(t.get("attribution"))
    diag = t.get("diagnosis")
    if t.get("power_line"):
        attr = (attr + "\n" if attr else "") + t["power_line"]
    diag_line = ("\nWHY IT HAS NO EDGE YET: %s\nThis is the real reason — if it names a feature "
                 "that is null/unavailable on THIS market, do NOT loosen thresholds (they can never "
                 "fire): either rebuild the mechanism on features this market actually has, or "
                 "ABANDON this thesis." % diag) if diag else ""
    return (
        "Develop THIS one thesis in depth before committing it — you may take several steps to get "
        "the mechanism right, OR exit early at any step if it clearly can't work here.\n"
        "Thesis: %s\nCurrent spec: %s\nResearch-fold result (a leak-free sandbox you may study "
        "freely — NOT the held-out data): %s%s%s%s\n\n"
        "What this market's earlier research found (learn from it; do not repeat failures):\n%s\n\n%s"
        "This is step %d of at most %d for this thesis — the cap is a ceiling, NOT a target: there "
        "is no reward for staying, and dropping a dead line to hunt a better one elsewhere is the "
        "right call. Decide ONE of three:\n"
        "- REFINE: a concrete change would STRENGTHEN THE ECONOMIC MECHANISM (condition on a regime "
        "you can justify, prototype a fitted/code model, drop a leg that only fit noise). Do NOT "
        "bolt on filters that merely fit the strongest in-sample bucket.\n"
        "- COMMIT: it is ready to gate (it trades and the mechanism holds). Every version is re-judged "
        "later on data you never see and the committed one spends exactly ONE statistical trial, so "
        "never commit a spec that takes ~0 trades — that just wastes a trial.\n"
        "- ABANDON: this thesis is dead on arrival for this market (its model can't be fit because a "
        "feature is unavailable, or it genuinely can't trade) and you have no better angle for it. "
        "Drop it with a reason — it costs no trial and frees you to explore elsewhere.\n"
        "Reply ONE JSON object: "
        '{\"decision\":\"refine\",\"spec\":{...the full revised spec...},\"change\":\"<what and why>\"} '
        "(optionally also \"thesis\" and \"mechanism\" if the story changed) OR "
        '{\"decision\":\"commit\",\"why\":\"<why it is ready to gate>\"} OR '
        '{\"decision\":\"abandon\",\"why\":\"<why it cannot work here>\"}.'
        % (t["thesis"], json.dumps(t["spec"], separators=(",", ":")),
           _metrics_line(t["in_sample"]), ("\n" + attr) if attr else "", diag_line, _feature_block(ds),
           _memory_block(memory), (run.get("_playbook") + "\n\n") if run.get("_playbook") else "",
           step + 1, THESIS_MAX_STEPS)
    ) + THINK_ALOUD


def _develop_check(market: str) -> Callable[[Dict], Dict]:
    def check(obj: Dict) -> Dict:
        decision = str(obj.get("decision") or "").strip().lower()
        if decision == "commit":
            return {"decision": "commit"}
        if decision in ("abandon", "skip", "drop"):
            return {"decision": "abandon", "why": str(obj.get("why") or obj.get("change") or "")[:1000]}
        if decision != "refine":
            raise ValueError('decision must be "refine", "commit", or "abandon"')
        raw = obj.get("spec")
        if isinstance(raw, dict):
            raw = dict(raw)
            if raw.setdefault("market", market) != market:
                raise ValueError("spec.market must be %s" % market)
        try:
            spec = specmod.validate(raw)
        except specmod.SpecError as e:
            raise ValueError("spec: %s" % e)  # let ask_json's repair round see it
        out: Dict = {"decision": "refine", "spec": spec, "change": str(obj.get("change") or "")[:1000]}
        if obj.get("thesis"):
            out["thesis"] = str(obj["thesis"])[:1500]
        if isinstance(obj.get("mechanism"), dict):
            out["mechanism"] = obj["mechanism"]
        return out

    return check


def _develop_thesis(h: Dict, run: Dict, ds: backtest.Dataset, partition: Dict, memory: List[Dict],
                    proposer: ModelFn, market_data, usage: Usage, log, checkpoint, round_no: int,
                    cur, user_id: int, merged_cache: Optional[Dict] = None,
                    dropped: Optional[List[Dict]] = None, screen=None,
                    screener: Optional[ModelFn] = None) -> Optional[Dict]:
    """Pillar 2 — spend as long as THIS thesis needs on the RESEARCH FOLD before committing it, or
    ABANDON it early when it's dead on arrival for this market.

    Backtest the freshly proposed spec, then up to THESIS_MAX_STEPS-1 times let the agent read its
    own research-fold result (+ the concrete no-edge diagnosis + prior-failure labels) and either
    REFINE the spec, COMMIT it, or ABANDON it. Only the research fold is ever read; the single
    returned candidate is what goes to finalist selection, so a deeper thesis still pre-registers
    exactly ONE frozen spec (no trial inflation).

    Returns None for an abandoned thesis — the caller drops it from the chunk, so a dead line
    costs NO gatekeeper trial. The step cap is a ceiling, not a target: the agent may exit at any
    step, and a spec that still takes 0 trades (or whose model can't be fit) is never committed —
    that would only waste a trial.

    Bounded three ways: the step cap, a per-step credit check (depth stays inside the budget), and
    fail-OPEN — any bad/empty/unavailable reply keeps the spec we already have, so a reviewer hiccup
    can never halt research or spend unbounded. Each refine re-freezes via _test_in_sample, so the
    committed spec is always a fit-on-research-and-frozen model, never re-fit at gate time."""
    t = _with_power(_test_in_sample(h, ds, partition, log, round_no, cur, merged_cache, run.get("id")),
                    run, ds, partition, cur, user_id)
    market = run["market"]
    committed = developed = False
    limit = THESIS_MAX_STEPS - 1
    # Model tiering (services.research_screen): on a screen-arm run the cheaper model walks this
    # loop until it wants to commit (or reaches its own step cap), then the developer takes over
    # with at least DEVELOPER_MIN_STEPS steps of its own. A screen abandon is final unless audited.
    screening = screen is not None and screen.on
    screen_limit = max(1, limit - research_screen.DEVELOPER_MIN_STEPS)
    step = 0
    while step < limit:
        checkpoint()
        if cur is not None and repo.credit_balance(cur, user_id) <= 0:
            break  # deeper thesis work stays inside the credit budget
        if screening and step >= screen_limit:
            screening = _hand_over(log, t, screen, "the screen used its steps")
        # Pillar 2 can spend up to THESIS_MAX_STEPS model calls on ONE thesis before the first
        # commit — surface the per-thesis step so that long, deep development is never silent.
        log("step", "Developing \"%s\" (step %d/%d)…" % (t["title"], step + 2, THESIS_MAX_STEPS),
            {"phase": "developing", "title": t["title"], "step": step + 2, "max_steps": THESIS_MAX_STEPS})
        msgs = [{"role": "user", "content": _develop_prompt(run, t, memory, step, ds)}]
        try:
            if screening:
                reply = market_data.ask(screener, _research_system(market), msgs, _develop_check(market),
                                        screen.usage)
            else:
                reply = market_data.ask(proposer, _research_system(market), msgs, _develop_check(market), usage)
        except LLMError:
            if screening:  # a screen hiccup hands the thesis to the developer instead of committing it
                screening = _hand_over(log, t, screen, "the screen call failed")
                continue
            break  # fail-open: keep the spec we already have
        if screening and reply.get("decision") == "abandon":
            if not screen.audit(t["title"]):
                screen.tally["screened_out"] += 1
                return _abandon(log, t, reply.get("why"), dropped, {"screened": True})
            # Audit: the developer re-judges the same prompt. Agreeing confirms the drop; disagreeing
            # rescues the thesis, which goes on with the developer from the developer's own reply.
            screen.tally["audits"] += 1
            try:
                second = market_data.ask(proposer, _research_system(market), msgs, _develop_check(market), usage)
            except LLMError:
                second = {"decision": "abandon", "why": reply.get("why")}
            log("step", "Screen audit on \"%s\": screen abandoned, developer says %s."
                % (t["title"], second.get("decision")),
                {"phase": "screen_audit", "title": t["title"], "developer": second.get("decision"),
                 "screen_why": (reply.get("why") or "")[:300]})
            if second.get("decision") == "abandon":
                return _abandon(log, t, reply.get("why"), dropped, {"screened": True, "audited": True})
            screen.tally["rescued"] += 1
            screening, reply = False, second
        elif screening and (reply.get("decision") != "refine" or not reply.get("spec")):
            screening = _hand_over(log, t, screen, "the screen would commit it")
            continue  # the developer judges the same result before anything is committed
        if reply.get("decision") == "abandon":
            return _abandon(log, t, reply.get("why"), dropped)  # dead on arrival — no candidate, no trial
        if reply.get("decision") != "refine" or not reply.get("spec"):
            committed = True
            break  # agent is satisfied — commit the current spec
        refined = dict(h, spec=reply["spec"])
        if reply.get("thesis"):
            refined["thesis"] = reply["thesis"]
        if reply.get("mechanism"):
            refined["mechanism"] = reply["mechanism"]
        log("step", "Refining \"%s\": %s" % (t["title"], reply.get("change") or "sharpening the mechanism"))
        developed = True
        t = _with_power(_test_in_sample(refined, ds, partition, log, round_no, cur, merged_cache, run.get("id")),
                        run, ds, partition, cur, user_id)
        step += 1
    # Anti-grind backstop: if the agent REFINED this thesis (really worked it) yet never committed
    # and the spec still can't trade (unfit model / 0 research-fold trades), drop it as dead on
    # arrival rather than grind the rest of the step cap. The no-develop path (THESIS_MAX_STEPS=1)
    # and any explicit commit are untouched; a committed 0-trade spec is harmless anyway — finalist
    # selection requires >=5 trades, so it never reaches the gatekeeper or spends a trial.
    if developed and not committed and not t["in_sample"].get("trades"):
        return _abandon(log, t, t.get("diagnosis"), dropped)
    return t


def _with_power(t: Dict, run: Dict, ds, partition: Dict, cur, user_id: int) -> Dict:
    """On a leads-arm run, attach the gate's projected validation power to the develop turn, so
    the agent sees whether the gate could ever confirm this thesis before it spends a trial."""
    if not run.get("_leads_arm") or cur is None or specmod.is_multi_market(t["spec"]):
        return t
    try:
        p = gatekeeper.validation_power(cur, user_id, run["market"], t["spec"], ds, partition)
    except Exception:  # noqa: BLE001 - an aid only; the turn goes on without it
        _LOG.exception("validation power failed on run %s", run.get("id"))
        return t
    return dict(t, power_line=research_leads.power_line(p))


def _hand_over(log, t: Dict, screen, why: str) -> bool:
    """The screen passes this thesis to the developer; returns the new `screening` flag (False)."""
    screen.tally["handed_over"] += 1
    log("step", "Handing \"%s\" to the developer model (%s)." % (t["title"], why),
        {"phase": "screen_handover", "title": t["title"], "why": why})
    return False


def _abandon(log, t: Dict, why: Optional[str], dropped: Optional[List[Dict]] = None,
             extra: Optional[Dict] = None) -> None:
    """Log a dropped thesis (no candidate reaches the chunk, so no statistical trial is spent), and
    remember it in `dropped` so later rounds don't re-propose the same dead idea."""
    why = why or "mechanism can't trade on this market"
    log("verdict", "DROPPED \"%s\" (no candidate) — %s" % (t["title"], why),
        dict({"title": t["title"], "status": "abandoned", "why": why[:600],
              "diagnosis": t.get("diagnosis") or None}, **(extra or {})))
    if dropped is not None:
        dropped.insert(0, {"title": t["title"], "why": why})
    return None


def _develop_self_check() -> None:
    """One runnable check: the per-thesis loop refines-then-commits exactly ONE spec reading only
    the research fold; abandons to None on the agent's call; and never commits an untradeable spec
    (0-trade DOA with no explicit commit -> dropped, no trial)."""
    import app.agent as A
    ds = type("DS", (), {"start_ts": 0, "cutoff_ts": 1, "frames": []})()
    calls = {"backtests": 0, "asks": 0}

    def make_test(trades):
        def fake_test(h, *a, **k):
            calls["backtests"] += 1
            return dict(h, in_sample={"trades": trades, "win_rate": 0.5, "pnl": 1.0, "fees": 0.1,
                                      "profit_factor": 1.2, "max_drawdown": 0.5}, capital=100.0,
                        attribution=None, diagnosis="" if trades else "0 trades: binding filter")
        return fake_test

    class MD:  # stand-in for AgentMarketData.ask: returns scripted (already-checked) develop replies
        def __init__(self, replies):
            self.replies = replies
        def ask(self, model, system, messages, check, usage):
            calls["asks"] += 1
            return self.replies.pop(0)  # loop logic only; spec validation is covered by the pytest test

    orig = A._test_in_sample
    try:
        A.THESIS_MAX_STEPS = 3
        base = {"title": "H", "thesis": "t", "spec": {"market": "m", "side": "yes"}}

        A._test_in_sample = make_test(10)
        md = MD([{"decision": "refine", "spec": {"market": "m", "side": "no"}, "change": "flip"},
                 {"decision": "commit", "why": "ready"}])
        out = _develop_thesis(dict(base), {"market": "m"}, ds, {}, [], lambda *a, **k: None, md,
                              Usage(), lambda *a, **k: None, lambda: None, 1, cur=None, user_id=1)
        assert out["spec"]["side"] == "no", "committed the refined spec"
        assert calls["asks"] == 2 and calls["backtests"] == 2, "one ask+backtest per refine, then commit"

        # Agent abandons a dead line -> None (no candidate, no trial).
        md = MD([{"decision": "abandon", "why": "feature null here"}])
        assert _develop_thesis(dict(base), {"market": "m"}, ds, {}, [], lambda *a, **k: None, md,
                               Usage(), lambda *a, **k: None, lambda: None, 1, cur=None, user_id=1) is None

        # Step cap reached on a 0-trade candidate with no explicit commit -> dropped, not committed.
        A._test_in_sample = make_test(0)
        md = MD([{"decision": "refine", "spec": {"market": "m", "side": "no"}, "change": "x"}] * 5)
        assert _develop_thesis(dict(base), {"market": "m"}, ds, {}, [], lambda *a, **k: None, md,
                               Usage(), lambda *a, **k: None, lambda: None, 1, cur=None, user_id=1) is None
    finally:
        A._test_in_sample = orig


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
# Evidence bar on REALISTIC paper fills (the live kernel over SimulatedVenue, order_ref 'sim:').
# Legacy instant paper fills overstate live results, so they count toward nothing below.
MIN_REALISTIC_PAPER_TRADES = 30   # closed round trips: fewer cannot tell edge from luck
MIN_PAPER_SPAN_HOURS = 48.0       # first entry to last exit: one quiet afternoon is not a track record
MAX_PAPER_EDGE_P_VALUE = 0.10     # one-sided stationary-bootstrap p that mean P&L per trade <= 0
# Separate events (contracts of one event settle on one outcome): five strikes of one 15-minute BTC
# event are one bet, not five, so the record needs this many events and the edge test runs on
# per-event P&L. Validation went to a fixed 0.05 alpha (#167), so paper is now the stricter filter.
MIN_PAPER_EVENTS = 20


def _trip_event_key(trip: Dict, i: int) -> str:
    """A trip's event: its ticker minus the last segment (KXBTC15M-26OCT241515-15 ->
    KXBTC15M-26OCT241515); a trip with no ticker (index `i`) counts as its own event."""
    tk = trip.get("ticker")
    return tk.rsplit("-", 1)[0] if tk and "-" in tk else "trip:%d:%s" % (i, tk or "")


def _trip_events(trips: List[Dict]) -> List[float]:
    """Net P&L per event (`_trip_event_key`), in the order each event was first traded."""
    sums: Dict[str, float] = {}
    for i, t in enumerate(trips):
        key = _trip_event_key(t, i)
        sums[key] = sums.get(key, 0.0) + float(t["pnl"])
    return list(sums.values())


def paper_evidence(cur, user_id: int, strategy_id: int) -> Dict:
    """The paper -> live evidence for one strategy, check by check, in gate order. `ready` is True
    only when every check passes; `why` names the FIRST failing check (the gate's refusal text).

    The legacy check (8+ closed paper trades of any kind, not net negative) runs first and is kept
    unchanged. Then, on realistic fills only (the live kernel over SimulatedVenue): enough round
    trips, net up after fees, spread over time, a bootstrap test that rejects 'no edge', and the
    newer half of the record up on its own (an edge that has faded stays on paper). Each
    check can only refuse; none relaxes the one before it. Also feeds the app's Road-to-live view."""
    paper = [d for d in repo.list_deployments(cur, user_id, include_stopped=True)
             if d["strategy_id"] == strategy_id and d["mode"] == "paper"]
    legacy_trades = sum(int(d.get("closed_trades") or 0) for d in paper)
    legacy_pnl = sum(float(d.get("realized_pnl") or 0) for d in paper)
    trips = repo.paper_round_trips(cur, user_id, strategy_id)
    pnls = [t["pnl"] for t in trips]
    net = sum(pnls)
    span_h = 0.0
    if trips:
        start = trips[0].get("opened_at")
        end = max((t.get("closed_at") for t in trips if t.get("closed_at")), default=None)
        if start and end:
            span_h = max(0.0, (end - start).total_seconds() / 3600.0)
    # Recent form: the newer half of the record (trips are oldest first) must be up on its own, so
    # an early winning streak can't carry a strategy whose edge has since faded into live money.
    recent = pnls[len(pnls) // 2:]
    recent_net = sum(recent)
    events = _trip_events(trips)
    p_value = None
    if len(pnls) >= MIN_REALISTIC_PAPER_TRADES and len(events) >= MIN_PAPER_EVENTS:
        from app import stats  # local: numpy-backed, only needed once there is enough evidence
        p_value = float(stats.stationary_bootstrap_ci(events, stat="mean", alpha=0.10)["p_value"])
    checks = [
        ("legacy_trades", legacy_trades >= MIN_PAPER_TRADES_FOR_LIVE,
         "it needs %d+ closed paper trades first (has %d)" % (MIN_PAPER_TRADES_FOR_LIVE, legacy_trades)),
        ("legacy_pnl", legacy_pnl >= 0, "it's still down $%.2f on paper" % (-legacy_pnl)),
        ("realistic_trades", len(trips) >= MIN_REALISTIC_PAPER_TRADES,
         "it needs %d+ closed paper trades on realistic fills first (has %d)" % (MIN_REALISTIC_PAPER_TRADES, len(trips))),
        ("events", len(events) >= MIN_PAPER_EVENTS,
         "its %d paper trades come from only %d separate events; it needs %d+ (strikes of one event are one bet)"
         % (len(trips), len(events), MIN_PAPER_EVENTS)),
        ("net_pnl", net > 0, "it isn't up on realistic paper fills ($%.2f net after fees)" % net),
        ("span", span_h >= MIN_PAPER_SPAN_HOURS,
         "its paper record covers only %.0fh; it needs %.0fh+ so one market mood can't carry it"
         % (span_h, MIN_PAPER_SPAN_HOURS)),
        ("edge", p_value is not None and p_value <= MAX_PAPER_EDGE_P_VALUE,
         "its paper edge isn't statistically clear yet (p=%s, needs %.2f or lower)"
         % ("n/a" if p_value is None else "%.2f" % p_value, MAX_PAPER_EDGE_P_VALUE)),
        ("recent", bool(recent) and recent_net > 0,
         "its newer %d paper trades are %s, so the edge may be fading" % (
             len(recent), ("down $%.2f" % -recent_net) if recent_net < 0 else "flat")),
    ]
    failing = next((why for _k, ok, why in checks if not ok), "")
    # Realization: realistic paper P&L per trade as a fraction of the backtest's unseen-data P&L
    # per trade. Informational (never gates): well under 1 means the backtest's fills or the edge
    # itself did not survive contact with the live book, which is the signal research should learn from.
    paper_mean = (net / len(pnls)) if pnls else None
    backtest_mean = None
    try:
        strat = repo.get_strategy(cur, user_id, strategy_id) or {}
        oos = (strat.get("result") or {}).get("out_of_sample") or {}
        if int(oos.get("trades") or 0) > 0:
            backtest_mean = float(oos.get("pnl") or 0) / int(oos["trades"])
    except Exception:
        backtest_mean = None
    realization = (paper_mean / backtest_mean) if (paper_mean is not None and backtest_mean and backtest_mean > 0) else None
    return {
        "ready": not failing, "why": failing,
        "checks": {k: ok for k, ok, _why in checks},
        "trades": len(trips), "trades_needed": MIN_REALISTIC_PAPER_TRADES,
        "net_pnl": round(net, 4), "span_hours": round(span_h, 1), "span_needed_hours": MIN_PAPER_SPAN_HOURS,
        "p_value": None if p_value is None else round(p_value, 4), "p_value_needed": MAX_PAPER_EDGE_P_VALUE,
        "recent_trades": len(recent), "recent_net_pnl": round(recent_net, 4),
        "events": len(events), "events_needed": MIN_PAPER_EVENTS,
        "legacy_trades": legacy_trades, "legacy_pnl": round(legacy_pnl, 4),
        "paper_mean_pnl": None if paper_mean is None else round(paper_mean, 4),
        "backtest_mean_pnl": None if backtest_mean is None else round(backtest_mean, 4),
        "realization": None if realization is None else round(realization, 3),
    }


def early_exits_line(exits: Dict[str, Dict]) -> str:
    """Paper exits before settlement vs holding to the end (repo.early_exit_scorecard), for the
    review: whether the stop and take-profit rules are adding or destroying value on the live book."""
    parts = []
    for reason, r in sorted(exits.items(), key=lambda kv: -kv[1]["exits"]):
        if not r["scored"]:
            parts.append("%s %d (none settled yet)" % (reason, r["exits"]))
            continue
        part = "%s %d: $%.2f vs $%.2f held, %s $%.2f" % (
            reason, r["scored"], r["scored_pnl"], r["hold_pnl"], "saved" if r["saved"] >= 0 else "COST", abs(r["saved"]))
        c = r.get("collateral")
        if c and c["scored"]:
            part += " (of which %d healthy positions sold alongside a breach: %s $%.2f)" % (
                c["scored"], "saved" if c["saved"] >= 0 else "COST", abs(c["saved"]))
        parts.append(part)
    return ("Early exits on paper vs holding to settlement (all time): " + "; ".join(parts)) if parts else ""


def paper_evidence_line(ev: Dict) -> str:
    """One-line summary of `paper_evidence` for the autopilot's review context."""
    parts = ["%d/%d realistic paper trades" % (ev["trades"], ev["trades_needed"]),
             "net $%.2f" % ev["net_pnl"], "%.0fh of record" % ev["span_hours"]]
    if ev.get("p_value") is not None:
        parts.append("edge p=%.2f" % ev["p_value"])
    if ev.get("realization") is not None:
        parts.append("paper earns %.0f%% of backtest per trade" % (100 * ev["realization"]))
    return "; ".join(parts) + ("; LIVE-READY on paper" if ev["ready"] else "; not live-ready: " + ev["why"])


def _proven_on_paper(cur, user_id: int, strategy_id: int) -> Tuple[bool, str]:
    """Enforce the research -> PAPER -> live loop in code: a strategy may go live only after its
    paper record clears every check in `paper_evidence`. Backs the model's 'proven on paper'
    judgment with a hard rule so autopilot can't jump a fresh pass straight to real money."""
    ev = paper_evidence(cur, user_id, strategy_id)
    return ev["ready"], ev["why"]


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


# -- the agent's safe-tuning envelope ------------------------------------------
# The co-pilot may TUNE risk and execution controls, but every value it sets is CLAMPED into
# [min, max] here before it is ever persisted. A TIGHTEN (safer: a lower cap / lower drawdown
# limit) is allowed down to the min; a LOOSEN is capped at the max. The min is strictly > 0 for a
# stop, so the agent can never DISABLE a stop, and the max is the user's hard ceiling, so it can
# never exceed a cap or loosen past a safe maximum. This envelope is the whole point of bounded
# autonomy. It is NOT the backstop: the loss budget, the autopilot daily-loss kill switch, and the
# drawdown/portfolio force-sell in engine.py remain the immutable backstop regardless of what the
# agent sets here, and this layer never touches the live-enable flags or any deploy/live gate.
RISK_BOUNDS = {
    # % of a deployment's capital it may draw down before the engine force-closes + pauses it.
    # >0 so a stop is never disabled; <=50 so the stop always bites well before capital is gone.
    "drawdown_limit_pct": (1.0, 50.0),
    # Hard ceiling on concurrent open positions per user (portfolio cap on NEW entries).
    "max_open_positions": (1, 50),
    # Hard ceiling on total open entry notional per user, in dollars.
    "max_open_notional": (1.0, 5000.0),
}
EXEC_BOUNDS = {
    # Fraction of the resting touch size a single child order may take (market-impact cap).
    "exec_max_book_fraction": (0.01, 0.50),
    # Widest touch spread (dollars) an entry will cross before it is abandoned (thin-book cap).
    "exec_max_entry_spread": (0.01, 0.25),
    # Hard per-order notional backstop on buys, in dollars.
    "exec_max_order_notional": (1.0, 500.0),
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clamp_into(changes: Dict, bounds: Dict, ints: Tuple[str, ...] = ()) -> Dict:
    """Keep only the known keys in `changes`, coerce to number, clamp each into its [lo, hi].
    Everything the agent sends is filtered through this, so an unknown key, a non-number or an
    out-of-range value can never reach the DB. Returns {} if nothing valid remained."""
    out: Dict = {}
    for key, (lo, hi) in bounds.items():
        if key not in changes or changes[key] is None:
            continue
        try:
            v = float(changes[key])
        except (TypeError, ValueError):
            continue
        v = _clamp(v, lo, hi)
        out[key] = int(round(v)) if key in ints else round(v, 4)
    return out


def _fmt_changes(changes: Dict) -> str:
    return ", ".join("%s=%s" % (k, v) for k, v in changes.items())


# Per-market research dedup. The autopilot review fires every few minutes; MAX_ACTIVE_RESEARCH caps
# concurrency, but it does NOT stop the review re-launching the SAME market line ("NFL", "NBA") on
# consecutive reviews while that line is still running or just failed — that's the observed thrash,
# credits burned re-spamming a dead idea. One cooldown window at the single choke point (act's
# research branch) blocks it, so the loop hunts a DIFFERENT market instead.
# ponytail: a flat per-market window, not per-idea NLP — the thrash is same-market; add idea-level
# matching only if the model starts spamming distinct ideas on one market.
RESEARCH_MARKET_COOLDOWN = timedelta(hours=6)
# A market that FAILS repeatedly is chronically bad for research (ephemeral event that closes
# mid-run, an illiquid contract whose data times out, no tradeable surface) — backing it off well
# past the ordinary cooldown stops the autopilot bleeding runs on it and steers it to markets that
# actually complete. Self-regulating: a market with a clean record is never affected.
RESEARCH_FAIL_WINDOW = timedelta(hours=24)
RESEARCH_FAIL_LIMIT = int(os.getenv("TAU_RESEARCH_FAIL_LIMIT", "3"))


def _market_research_recent(cur, user_id: int, market: str, runs: Optional[List[Dict]] = None) -> Optional[str]:
    """Why the autopilot should NOT open a fresh research line on `market` right now, or None if it's
    clear. Blocks a market that already has an active research run, or one that finished (passed or
    failed) within RESEARCH_MARKET_COOLDOWN, so the review hunts a different market instead of
    re-spamming a dead/running line. Best-effort: any read error returns None (allow) so a context
    hiccup never blocks legitimate research."""
    if runs is None:
        try:
            runs = repo.list_runs(cur, user_id, limit=30)
        except Exception:
            return None
    now = repo.now_utc()
    recent_fails = 0
    for r in runs:
        if r.get("market") != market:
            continue
        if r.get("status") in ("queued", "running", "paused"):
            return "a research line is already running on %s (run #%s)" % (market, r.get("id"))
        fin = r.get("finished_at")
        if fin and (now - fin) < RESEARCH_MARKET_COOLDOWN:
            return ("%s was just researched (run #%s, %s) and is on a short cooldown"
                    % (market, r.get("id"), r.get("status")))
        if r.get("status") == "failed" and fin and (now - fin) < RESEARCH_FAIL_WINDOW:
            recent_fails += 1
    if recent_fails >= RESEARCH_FAIL_LIMIT:
        return ("%s has failed %d times in the last day — it's backed off (chronically bad for "
                "research); hunt a different market" % (market, recent_fails))
    return None


def _cooldown_line(cur, user_id: int) -> str:
    blocked = _research_blocked_markets(cur, user_id)
    if not blocked:
        return "Research cooldown: none, every market is open for a fresh research line."
    return ("Research cooldown, do NOT propose these markets now (pick others, or omit market to let the "
            "specialist choose): %s." % ", ".join(sorted(blocked)))


def _research_blocked_markets(cur, user_id: int) -> Dict[str, str]:
    """{market: why} for every market `_market_research_recent` blocks right now, from one read.
    Shown to the review so it stops proposing them, and kept out of the research pick."""
    try:
        runs = repo.list_runs(cur, user_id, limit=30)
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for m in {r.get("market") for r in runs if r.get("market")}:
        why = _market_research_recent(cur, user_id, m, runs)
        if why:
            out[m] = why
    return out


# Deterministic funnel step: paper costs nothing and the live gate needs a long realistic paper
# record, so every gatekeeper-cleared candidate should start earning evidence at once instead of
# waiting for a review to think of it. Bounded per review and in total; never touches live.
AUTO_PAPER_MAX_NEW = 3
AUTO_PAPER_MAX_ACTIVE = 20


def auto_paper_candidates(cur, user: Dict) -> List[str]:
    """Put each gatekeeper DEPLOYMENT_CANDIDATE that has never run on paper onto paper, through
    act()'s own deploy path (so every deploy check applies). Autopilot-on users only. A strategy
    that already had a paper deployment, even a stopped one, is left to the review: stopping it was
    a decision. Returns the chat lines for what it did."""
    if not user.get("autopilot"):
        return []
    deps = repo.list_deployments(cur, user["id"], include_stopped=True)
    active = sum(1 for d in deps if d["status"] != "stopped")
    tried = {d["strategy_id"] for d in deps if d["mode"] == "paper" or d["status"] != "stopped"}
    out: List[str] = []
    for s in repo.list_strategies(cur, user["id"], status="passed", limit=50):
        if len(out) >= AUTO_PAPER_MAX_NEW or active >= AUTO_PAPER_MAX_ACTIVE:
            break
        mkt = MARKETS.get(s["market"])
        if s["id"] in tried or mkt is None or not mkt.deployable or not in_focus(s["market"], focus_tokens(user)):
            continue
        if specmod.is_code_spec(s["spec"]) or not _is_deployment_candidate(cur, s["id"]):
            continue
        text, pid = act(cur, user, {"type": "deploy", "strategy_id": s["id"],
                                    "reason": "Gatekeeper cleared it; paper builds the realistic record the live gate needs."},
                        autopilot=True)
        if pid is not None:
            out.append(text)
            active += 1
    return out


# Forward paper probation (off unless APP_PAPER_PROBATION=1): the gatekeeper has never cleared a
# strategy, so paper never trades and the realistic-fill engine has no record. Paper costs no money,
# so a few validation near misses (positive on unseen data, p <= PROBATION_MAX_P) run on paper as a
# forward test. Live is untouched: deploy_live and the manual live path still require a gatekeeper
# DEPLOYMENT_CANDIDATE, which a probation strategy is not.
PAPER_PROBATION = os.getenv("APP_PAPER_PROBATION", "0") == "1"
# Autopilot may not pause a paper deployment younger than this (live pauses are never held back).
REPEAT_NOTE_WINDOW = timedelta(hours=2)
PAPER_MIN_AGE = timedelta(hours=int(os.getenv("APP_PAPER_MIN_AGE_HOURS", "24")))
# 0.35, not 0.25 (Todd 2026-10-25: "Yes" to near misses on paper only): his best near misses were
# kxrain at p=0.30 and 0.34. Paper risks no money; live still needs a DEPLOYMENT_CANDIDATE.
PROBATION_MAX_P = float(os.getenv("APP_PROBATION_MAX_P", "0.35"))
PROBATION_MIN_TRADES = int(os.getenv("APP_PROBATION_MIN_TRADES", "20"))
# 20, not 4: the paper tournament (app/tournament.py) runs every near miss at once so the pooled
# forward sample reaches the gate's 400+ trades in days, and it retires losers to free slots.
PROBATION_MAX_ACTIVE = int(os.getenv("APP_PROBATION_MAX_ACTIVE", "20"))
# Validation verdicts with no p-value (under the gate's min sample) are unmeasured, not rejected:
# they enter too when their backtest made money on unseen data over at least this many trades.
UNDERPOWERED_MIN_TRADES = int(os.getenv("APP_PROBATION_UNDERPOWERED_MIN_TRADES", "10"))


def _backtest_net_positive(strat: Dict) -> bool:
    # A research-made strategy stores only its research-fold metrics (`in_sample`: the purged
    # walk-forward TEST folds inside Research, never validation/holdout; see _result_block), so it
    # had no `out_of_sample` and no underpowered verdict ever qualified (runs 2907 and 3002).
    res = strat.get("result") or {}
    oos = res.get("out_of_sample") or res.get("in_sample") or {}
    try:
        return int(oos.get("trades") or 0) >= UNDERPOWERED_MIN_TRADES and float(oos.get("pnl") or 0) > 0
    except (TypeError, ValueError):
        return False


def auto_paper_probation(cur, user: Dict) -> List[str]:
    """Put validation near misses that never ran on paper onto paper, at most PROBATION_MAX_ACTIVE
    running at once. Autopilot-on users only. Returns the chat lines for what it did."""
    if not (PAPER_PROBATION and user.get("autopilot")):
        return []
    from app import engine as _engine  # local import: engine imports agent (circular)
    deps = repo.list_deployments(cur, user["id"], include_stopped=True)
    tried = {d["strategy_id"] for d in deps}
    active = sum(1 for d in deps if d["status"] != "stopped" and d["mode"] == "paper"
                 and not _is_deployment_candidate(cur, d["strategy_id"]))
    out: List[str] = []
    cands = list(rr.probation_candidates(cur, user["id"], PROBATION_MAX_P, PROBATION_MIN_TRADES))
    cands += rr.underpowered_candidates(cur, user["id"], UNDERPOWERED_MIN_TRADES)
    for c in cands:
        if active >= PROBATION_MAX_ACTIVE:
            break
        sid = c["strategy_id"]
        if sid in tried:
            continue
        strat = repo.get_strategy(cur, user["id"], sid)
        # A pooled spec's experiment is filed under its whole stream ("btc_daily+eth_daily+..."); it
        # trades as the plain rule on its own market, which must be one of the stream's markets.
        if strat is None or strat.get("market") not in c["market"].split("+") or specmod.is_code_spec(strat["spec"]):
            continue
        mkt = MARKETS.get(strat["market"])
        # No autopilot_focus check: probation is paper only (no money), and Todd approved it for his
        # out-of-focus kxrain near misses while his research stays on crypto.
        if mkt is None or not mkt.deployable:
            continue
        if _engine.cross_deploy_block(strat["spec"], "paper"):
            continue
        if c["p_value"] is None and not _backtest_net_positive(strat):
            continue
        tried.add(sid)
        if c["p_value"] is None:
            why = "had too few validation trades to score (%d), and its backtest was up on unseen data" % c["n_trades"]
        else:
            why = "narrowly missed validation (p=%.3f, $%.2f over %d unseen trades)" % (
                c["p_value"], c["net_pnl"], c["n_trades"])
        repo.create_proposal(cur, user["id"], "deploy", "Paper probation: %s." % why, None, sid, "applied")
        repo.create_deployment(cur, user["id"], sid, strat["market"], "paper")
        active += 1
        out.append("[probation #%d] Put “%s” on paper as a forward test: it %s. Paper only; it can't go "
                   "live unless the gatekeeper clears it." % (sid, strat["title"], why))
    return out


def _tournament_hold(cur, user_id: int, dep: Dict) -> str:
    """Why autopilot may not pause this paper tournament entrant yet, or ''. A probation entrant is
    retired by the tournament's own rule (app/tournament.py) once it has enough round trips to judge;
    a review pausing it on a few bad trades cuts the forward sample the gate needs. Any read error
    allows the pause (pausing paper risks nothing)."""
    from app import tournament
    try:
        if _is_deployment_candidate(cur, dep["strategy_id"]):
            return ""
        events = _trip_events(repo.paper_round_trips(cur, user_id, dep["strategy_id"]))
    except Exception:
        return ""
    trips, net = len(events), sum(events)
    if trips >= tournament.TOURNAMENT_MIN_TRIPS:
        return ""
    return ("I left %s running: it is a paper tournament entrant with %d of %d independent events (net $%.2f), and "
            "the tournament retires it on its own once the data can judge it. Paper costs nothing; a pause now "
            "only shrinks the forward sample." % (dep["title"], trips, tournament.TOURNAMENT_MIN_TRIPS, net))


# Kalshi accepts orders in these categories only while the account's location verification is
# current (it lapses and is renewed in the Kalshi mobile app). Paper never needs it; live does.
ATTESTATION_CATEGORIES = frozenset({"Sports", "Elections", "Politics", "Entertainment"})


def location_attestation_note(market_key: Optional[str]) -> str:
    """A warning for a live-ready notice when the market's live orders need a current Kalshi
    location verification, else ''. Unknown markets get no note (the alerter tracks expiry)."""
    m = MARKETS.get(market_key or "")
    if not m or m.category not in ATTESTATION_CATEGORIES:
        return ""
    return ("Kalshi only accepts %s orders while your location verification is current, so re-verify "
            "your location in the Kalshi mobile app before going live." % m.category)


def pause_notice(cur, user: Dict, run: Dict) -> bool:
    """Ring the bell when a deployment was paused automatically (the engine's loss guard and
    force-close both queue a review carrying the deployment id). The chat line alone reaches only
    someone who opens the autopilot panel, and a paused strategy is exactly what needs them.
    Read-only toward trading. True when a notice was added."""
    dep_id = run.get("deployment_id")
    if not dep_id:
        return False
    d = repo.get_deployment(cur, user["id"], dep_id)
    if not d or d.get("status") != "paused":
        return False  # already resumed or stopped by the time the review ran
    title = (d.get("title") or "Strategy %d" % d["strategy_id"])[:120]
    why = (d.get("status_reason") or "").strip()
    repo.add_notification(cur, user["id"], "paused",
                          "“%s” was paused automatically.%s" % (title, (" " + why[:200]) if why else ""),
                          "/strategies/%d" % d["strategy_id"])
    return True


def live_ready_notices(cur, user: Dict) -> List[str]:
    """Once per strategy, tell the user (chat line + email) when a running paper strategy first
    clears every `paper_evidence` check. Read-only toward trading: going live stays a separate step
    (the user's promote or live autopilot, which re-run every gate). Returns the chat lines added."""
    from app import notify
    out: List[str] = []
    seen = set()
    for d in repo.list_deployments(cur, user["id"]):
        sid = d["strategy_id"]
        if d["mode"] != "paper" or d["status"] != "running" or sid in seen:
            continue
        seen.add(sid)
        marker = "[live-ready #%d]" % sid
        if repo.chat_contains(cur, user["id"], "system", marker):
            continue
        ev = paper_evidence(cur, user["id"], sid)
        if not ev["ready"]:
            continue
        title = d.get("title") or "Strategy %d" % sid
        if not _is_deployment_candidate(cur, sid):
            # A probation strategy: strong forward paper, but no live path. Say so instead of
            # inviting a promote that the live gate would refuse.
            marker = "[paper-standout #%d]" % sid
            if repo.chat_contains(cur, user["id"], "system", marker):
                continue
            line = ("%s “%s” cleared every paper-to-live check on forward paper (%s) even though "
                    "the gatekeeper rejected it in research. It can't go live as is; ask me to re-test it "
                    "on fresh data." % (marker, title, paper_evidence_line(ev)))
            repo.add_chat(cur, user["id"], "system", line)
            out.append(line)
            continue
        note = location_attestation_note(d.get("market"))
        line = ("%s “%s” cleared every paper-to-live check: %s. Going live is your call: promote it, or "
                "turn on live autopilot." % (marker, title, paper_evidence_line(ev)))
        if note:
            line += " " + note
        repo.add_chat(cur, user["id"], "system", line)
        # The bell too: the chat line only reaches someone who opens the autopilot panel.
        repo.add_notification(cur, user["id"], "live_ready",
                              "“%s” is ready for live trading. Going live is your call." % title[:120],
                              "/strategies/%d" % sid)
        out.append(line)
        if user.get("email"):
            notify.live_ready_notice(user["email"], user.get("name"), title, paper_evidence_line(ev),
                                     "%s/strategies/%d" % (notify.PUBLIC_URL, sid), note)
    return out


def act(cur, user: Dict, action: Dict, autopilot: bool, dataset_fn=backtest.dataset) -> Tuple[str, Optional[int]]:
    """Turn one agent action into a proposal (or, on autopilot, an applied
    change). Returns (sentence for the chat, proposal id if one was made)."""
    # Normalize the action type: the model sometimes emits "Research"/"research "/"research\n"
    # (or puts it under "kind"), and an exact `== "research"` miss made every handler fall through
    # to the "not allowed" fallback even though research IS allowed. Strip + lowercase the single
    # read point so a whitespace/casing variant can't silently kill an action. All handler literals
    # below are lowercase, so this never changes a correct match.
    kind = str(action.get("type") or action.get("kind") or "").strip().lower()
    reason = str(action.get("reason") or "").strip()[:1000] or "No reason given."
    user_id = user["id"]
    if kind == "kalshi_perps_order":
        from app import kalshi_perps_trading
        try:
            return kalshi_perps_trading.propose_for_agent(
                cur, user_id, {k: v for k, v in action.items() if k not in ("type", "kind")})
        except kalshi_perps_trading.Error as exc:
            return "I could not propose that Bitcoin perps order: %s" % exc, None
    if kind == "alpaca_paper_order":
        from app import alpaca_paper
        try:
            return alpaca_paper.propose_for_agent(cur, user_id, action)
        except alpaca_paper.Error as exc:
            return "I could not propose that Alpaca paper order: %s" % exc, None
    if kind in ("adjust", "pause", "resume"):
        dep = repo.get_deployment(cur, user_id, int(action.get("deployment_id") or 0))
        if dep is None or dep["status"] == "stopped":
            # The agent referenced a deployment that's gone (removed/stopped) — usually one it
            # named in an earlier message. Don't dead-end with a vague "couldn't find"; tell it
            # exactly what exists so the next review acts on a real one instead of repeating the miss.
            live = repo.list_deployments(cur, user_id)
            have = ("; ".join("#%d %s (%s, %s)" % (d["id"], d["title"], d["market"], d["status"]) for d in live)
                    or "none — you have no active deployments, so research a new edge or deploy a proven one instead of adjusting")
            return ("Deployment #%s no longer exists (removed or stopped). Your current deployments are: %s."
                    % (action.get("deployment_id"), have), None)
        if kind != "pause" and specmod.has_perpetual_market(dep.get("spec") or {}, dep.get("market")):
            return "Bitcoin perpetuals are research-only; their deployments cannot be resumed or adjusted.", None
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
            # Gate names read as goals ("Makes money on unseen data"), so a bare list after "failed"
            # read as praise. Name them as the checks it did not pass.
            failed = ", ".join('"%s"' % g["name"].lower() for g in result["gates"] if not g["ok"])
            return ("I backtested a change to %s, but it didn't pass these checks: %s. I left it alone."
                    % (dep["title"], failed)), None
        # NOT "passed": an adjustment is only a re-backtest — it never pre-registers, is never
        # judged by the Statistical Gatekeeper, and carries no experiment. "passed" is reserved
        # for the full-pipeline outcome (set_strategy_outcome <-> STAT_SUPPORTED <-> a linked
        # experiment), so an adjustment gets the non-deployable "backtest-only" status. This is
        # strictly stricter: the deploy/deploy_live gates require status=="passed" (AND a
        # deployment candidate), so a backtest-only row can never be deployed afresh. The
        # adjustment still applies to its existing deployment via the adjust proposal below
        # (set_deployment_strategy), which never routes through the status=="passed" deploy gate.
        sid = repo.insert_strategy(
            cur, user_id, None, dep["strategy_id"], dep["market"], dep["direction"], dep["title"] + " (adjusted)",
            reason, new_spec, "backtest-only", result,
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
        if (autopilot and kind == "pause" and dep["mode"] == "paper" and dep.get("created_at")
                and repo.now_utc() - dep["created_at"] < PAPER_MIN_AGE):
            # Paper risks no money, and the live gate needs a long realistic record. A review once
            # paused a probation deployment minutes after it started for "zero fills after hours".
            age_h = (repo.now_utc() - dep["created_at"]).total_seconds() / 3600
            return ("I left %s running: it has been on paper for only %.1f hours, and paper costs nothing "
                    "while it builds the record the live gate needs (at least %d hours before I pause it)."
                    % (dep["title"], age_h, PAPER_MIN_AGE.total_seconds() // 3600), None)
        if autopilot and kind == "pause" and dep["mode"] == "paper":
            held = _tournament_hold(cur, user_id, dep)
            if held:
                return held, None
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
        refusal = focus_refusal(user, strat["market"])
        if refusal:
            return refusal, None
        if specmod.is_code_spec(strat["spec"]):
            # The live/paper engine evaluates the DSL rule (specmod.entries); arbitrary agent
            # code runs ONLY in the research sandbox and is never executed in the trading loop.
            return ("%s is an agent-authored code strategy; those are research-only and can't be "
                    "deployed to the trading engine." % strat["title"], None)
        from app import engine as _engine  # local import: engine imports agent (circular)
        cross_block = _engine.cross_deploy_block(strat["spec"], "paper")
        if cross_block:
            return cross_block, None
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
        refusal = focus_refusal(user, strat["market"])
        if refusal:
            return refusal, None
        if specmod.is_code_spec(strat["spec"]):
            return ("%s is an agent-authored code strategy; those are research-only and never "
                    "run in the live engine." % strat["title"], None)
        from app import engine as _engine  # local import: engine imports agent (circular)
        cross_block = _engine.cross_deploy_block(strat["spec"], "live")
        if cross_block:
            return cross_block, None
        if (strat["spec"].get("side") or "yes").lower() != "yes" and not _engine.NO_SIDE_LIVE_ENABLED:
            # Staged rollout: NO-side live mechanics are validated on the demo sandbox first.
            return ("NO-side live trading is still being validated on the demo sandbox, so %s "
                    "stays on paper for now — deploy it on demo to exercise the NO path." % strat["title"], None)
        # Additive gatekeeper gate (§E.5): required ON TOP OF the live_autopilot_ok
        # and _proven_on_paper checks below — none of which are removed, reordered or weakened.
        # Side is no longer gated: live execution now places the correct YES or NO leg (a NO
        # strategy places a NO order), so any validated side may go live.
        if not _is_deployment_candidate(cur, strat["id"]):
            return ("I can't take %s live — the gatekeeper hasn't cleared it as a deployment "
                    "candidate (holdout forward-validation + diversification), so it stays on "
                    "paper." % strat["title"], None)
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
        # stake, per-user key and the loss guard. Autopilot cannot raise any of these.
        cap = float(strat["spec"]["sizing"]["stake"]) * int(strat["spec"]["sizing"]["max_positions"])
        pid = repo.create_proposal(cur, user_id, "deploy", reason, None, strat["id"], "applied")
        repo.create_deployment(cur, user_id, strat["id"], strat["market"], "live")
        return ("Autopilot deployed %s to LIVE within your $%.0f cap (your own Kalshi key, loss guard on)."
                % (strat["title"], cap)), pid
    if kind == "set_risk":
        # Tune the user's risk controls within the safe envelope. Every value is CLAMPED, so a
        # tighten is applied freely and a loosen is capped at the hard ceiling — the agent can
        # never disable a stop or exceed a cap. Applied on autopilot, else a pending proposal.
        changes = _clamp_into(action.get("changes") or {}, RISK_BOUNDS, ints=("max_open_positions",))
        if not changes:
            return "I meant to tune your risk controls but sent nothing I can set.", None
        pid = repo.create_proposal(cur, user_id, "set_risk", reason, None, None,
                                   "applied" if autopilot else "pending", payload=changes)
        if autopilot:
            repo.set_user_risk_config(cur, user_id, changes)
            return "Autopilot updated your risk controls (within safe bounds): %s." % _fmt_changes(changes), pid
        return "Proposed a risk-control change (within safe bounds): %s." % _fmt_changes(changes), pid
    if kind == "set_exec":
        # Tune the live execution controls within the safe envelope (same clamp discipline). These
        # caps can only shrink or abandon an order and never block an exit, so a set value never
        # weakens safety; the clamp keeps even a loosen inside the safe maximum.
        changes = _clamp_into(action.get("changes") or {}, EXEC_BOUNDS)
        if not changes:
            return "I meant to tune the execution controls but sent nothing I can set.", None
        pid = repo.create_proposal(cur, user_id, "set_exec", reason, None, None,
                                   "applied" if autopilot else "pending", payload=changes)
        if autopilot:
            repo.set_user_execution_config(cur, user_id, changes)
            return "Autopilot adjusted your execution controls (within safe bounds): %s." % _fmt_changes(changes), pid
        return "Proposed an execution-control change (within safe bounds): %s." % _fmt_changes(changes), pid
    if kind == "research":
        # Run the agent through the SAME RSI pipeline a manual run uses: repo.create_run(kind=
        # "research") -> a worker claims it -> run_research -> proposer -> gatekeeper -> one-time
        # holdout. No narrowing: the autopilot agent has the same market/idea freedom. Two modes:
        #   - strategy_id given  -> "dig deeper": branch off a PASSED strategy (same market/dir).
        #   - market + idea given -> a FRESH research line, identical to the Research page endpoint.
        # No money and no proposal (research spends only model credits), but it honours the same
        # active-research cap the Research page enforces. Validate the intent FIRST so a bad action
        # is rejected without consuming the capacity check.
        sid = int(action.get("strategy_id") or 0)
        market = action.get("market") or None
        idea = str(action.get("idea") or action.get("reason") or "").strip()[:1000]
        if sid:
            strat = repo.get_strategy(cur, user_id, sid)
            if strat is None or strat["status"] != "passed":
                return "I can only dig deeper on a strategy that already passed its backtest.", None
        else:
            if market is not None and market not in MARKETS:
                return "I can't research that market — pick one Tau supports, or let me choose.", None
            if len(idea) < 8:
                return "Tell me the idea to research in a sentence or two.", None
        refusal = focus_refusal(user, strat["market"] if sid else market)
        if refusal:
            return refusal, None
        unavailable = research_unavailable_reason(strat["market"] if sid else market)
        if unavailable:
            return unavailable, None
        if repo.count_runs(cur, user_id, "research", active_only=True) >= MAX_ACTIVE_RESEARCH:
            return "You already have a couple of research sessions running — let one finish and I'll start this then.", None
        if MAX_RESEARCH_PER_DAY and repo.count_runs(
                cur, user_id, "research", since=repo.now_utc() - timedelta(days=1)) >= MAX_RESEARCH_PER_DAY:
            return ("You've hit the daily research limit (%d) — it resets over the next 24 hours, "
                    "and I'll resume then." % MAX_RESEARCH_PER_DAY), None
        if MAX_GLOBAL_ACTIVE_RESEARCH and repo.count_active_research(cur) >= MAX_GLOBAL_ACTIVE_RESEARCH:
            return ("The research queue is full right now — I'll start this once a slot frees up.", None)
        if sid:
            dig_deeper_run(cur, user_id, strat)
            return ("Started a new research session digging deeper into “%s”: I'll refine and "
                    "stress-test its mechanism, and every variant still has to pass the same gates. "
                    "Follow it on the Research page." % strat["title"], None)
        # Dedup/cooldown: don't re-launch a line on a market that's already running or just finished
        # — the review should hunt a DIFFERENT market, not re-spam the same dead/running idea. Only
        # when a market is named; market=None lets the proposer pick, so there's nothing to dedup yet.
        if market is not None:
            why = _market_research_recent(cur, user_id, market)
            if why and (not autopilot or why.startswith("a research line is already running")):
                return ("I didn't start that — %s. I'll hunt a different market instead of "
                        "re-running the same line." % why), None
            if why:
                # Prod 2026-10-24: reviews kept proposing the same three cooldown markets every few
                # minutes, so for an hour no research started at all. On autopilot keep the angle and
                # let the research specialist pick a market that is off cooldown (run_research
                # excludes blocked markets from its pick). The active/daily caps above still apply.
                repo.create_run(cur, user_id, "research", None, None, idea, brief=True,
                                model=user.get("autopilot_model"))
                return ("%s is on cooldown (%s), so I started this angle on a market the research "
                        "specialist picks from the ones off cooldown." % (market, why)), None
        direction = action.get("direction") if action.get("direction") in DIRECTIONS else None
        # brief=True: the co-pilot is DELEGATING, not authoring. `idea` is a high-level angle/lens,
        # and the proposer turns it into the actual hypotheses (see _research_prompt's brief branch).
        # Stamp the user's autopilot model so the run uses it (NULL = catalog default).
        repo.create_run(cur, user_id, "research", market, direction, idea, brief=True,
                        model=user.get("autopilot_model"))
        return ("Started a fresh research session on %s — same gates as any run (pre-registration, "
                "holdout, diversification). Follow it on the Research page."
                % (market or "a market I'll choose"), None)
    # Should be unreachable for a well-formed action. Log the raw dict so a genuinely new/malformed
    # action kind is diagnosable from the agents journal instead of only this opaque chat line.
    print("[agents] copilot emitted an unhandled action: %r" % (action,), flush=True)
    return "I tried an action I'm not allowed to take (%s)." % (kind or "unknown"), None


def apply_proposal(cur, user_id: int, proposal: Dict) -> None:
    """The user approved it: do what it says."""
    kind = proposal["kind"]
    if kind == "kalshi_perps_live":
        raise ValueError("A native perps order requires separate exact-ticket confirmation by its owner.")
    if kind == "alpaca_paper":
        raise ValueError("Alpaca paper approval must use the durable broker order service.")
    if kind in ("adjust", "deploy"):
        strategy = repo.get_strategy(cur, user_id, proposal["strategy_id"])
        if strategy and specmod.has_perpetual_market(strategy.get("spec") or {}, strategy.get("market")):
            raise ValueError("Bitcoin perpetual research cannot be deployed or applied to a deployment.")
    if kind in ("adjust", "resume"):
        deployment = repo.get_deployment(cur, user_id, proposal["deployment_id"])
        if deployment and specmod.has_perpetual_market(deployment.get("spec") or {}, deployment.get("market")):
            raise ValueError("Bitcoin perpetual deployments cannot be resumed or adjusted.")
    if kind == "adjust":
        repo.set_deployment_strategy(cur, user_id, proposal["deployment_id"], proposal["strategy_id"])
    elif kind in ("pause", "resume"):
        repo.set_deployment_status(cur, user_id, proposal["deployment_id"], "paused" if kind == "pause" else "running",
                                   "Approved agent proposal")
    elif kind == "deploy":
        strat = strategy
        repo.create_deployment(cur, user_id, strat["id"], strat["market"], "paper")
    elif kind == "set_risk":
        # payload is the already-clamped change set from act(); re-clamp defensively so an approval
        # can never apply a value outside the safe envelope even if the stored row were tampered.
        repo.set_user_risk_config(cur, user_id, _clamp_into(proposal.get("payload") or {}, RISK_BOUNDS, ints=("max_open_positions",)))
    elif kind == "set_exec":
        repo.set_user_execution_config(cur, user_id, _clamp_into(proposal.get("payload") or {}, EXEC_BOUNDS))


def _deployment_age_text(d: Dict) -> str:
    # How long the deployment has been up, so a review doesn't call a 20-minute-old paper
    # deployment "zero fills for days" and pause it before it has seen a trading window.
    created = d.get("created_at")
    if not created:
        return ""
    hours = max(0.0, (repo.now_utc() - created).total_seconds() / 3600)
    age = "%.1f hours" % hours if hours < 48 else "%.1f days" % (hours / 24)
    note = ""
    if d.get("mode") == "paper" and hours < PAPER_MIN_AGE.total_seconds() / 3600:
        note = " (too new to judge; leave it running until it has been up %d hours)" % (PAPER_MIN_AGE.total_seconds() // 3600)
    return "deployed %s ago%s; " % (age, note)


def _copilot_context(cur, user: Dict) -> str:
    deps = repo.list_deployments(cur, user["id"])
    passed = [s for s in repo.list_strategies(cur, user["id"], status="passed", limit=20)]
    deployed_ids = {d["strategy_id"] for d in deps}
    risk = repo.user_risk_config(cur, user["id"]) or {}
    xc = repo.user_execution_config(cur, user["id"]) or {}
    try:
        active_research = repo.count_runs(cur, user["id"], "research", active_only=True)
    except Exception:
        active_research = 0
    try:
        plan = repo.autopilot_plan(cur, user["id"])
    except Exception:
        plan = {}
    running = [d for d in deps if d["status"] == "running"]
    focus = focus_tokens(user)
    lines = [
        "Autopilot is %s." % ("ON" if user.get("autopilot") else "OFF"),
        ("USER'S MARKET FOCUS (binding, set by the user): %s. Research and deploy ONLY markets inside it: "
         "the host refuses anything else, so don't propose it. Diversify WITHIN the focus." % ", ".join(focus))
        if focus else
        ("USER'S MARKET FOCUS: none set. If the user's messages ask you to focus on or stick to some "
         "markets (e.g. 'only crypto', 'focus on bitcoin'), emit a set_focus action so it binds."),
        # Counted here so the review's status line can't contradict the list below (a review once
        # opened with "0 deployments live/paper" while two paper deployments were running).
        "DEPLOYMENTS RUNNING RIGHT NOW: %d on paper%s, %d live%s." % (
            sum(1 for d in running if d["mode"] == "paper"),
            " (%s)" % ", ".join("#%s" % d["id"] for d in running if d["mode"] == "paper") if any(d["mode"] == "paper" for d in running) else "",
            sum(1 for d in running if d["mode"] == "live"),
            " (%s)" % ", ".join("#%s" % d["id"] for d in running if d["mode"] == "live") if any(d["mode"] == "live" for d in running) else ""),
        "RESEARCH RUNNING RIGHT NOW: %d.%s" % (active_research, "" if active_research else
            " NONE is running — any research you mentioned in earlier messages has ALREADY FINISHED "
            "(its outcome is listed below). Do NOT tell the user research is 'still running'."),
        "Risk controls: drawdown_limit_pct=%s, max_open_positions=%s, max_open_notional=%s."
        % (risk.get("drawdown_limit_pct"), risk.get("max_open_positions"), risk.get("max_open_notional")),
        _cooldown_line(cur, user["id"]),
        "Execution controls (null = server default): exec_max_book_fraction=%s, exec_max_entry_spread=%s, exec_max_order_notional=%s."
        % (xc.get("exec_max_book_fraction"), xc.get("exec_max_entry_spread"), xc.get("exec_max_order_notional")),
    ]
    # OPERATING PLAN: your own standing brief from last review — goals, research agenda + why,
    # how each deployment is doing, capital posture. This is what makes reviews COHERENT across
    # time instead of independent one-shots. Read it, act consistently with it, and REWRITE it
    # this turn (the "plan" field of your reply) to reflect what you just learned and decided.
    lines += ["", "Your operating plan (from last review — update it this turn):"]
    if plan:
        for k in ("goals", "agenda", "deployments", "posture"):
            if plan.get(k):
                lines.append("- %s: %s" % (k, plan[k]))
    else:
        lines.append("- none yet — SET one this review (goals + research agenda + capital posture).")
    lines += ["", "Deployments:"]
    try:
        tally = repo.scan_tally(cur, [d["id"] for d in deps])
    except Exception:
        tally = {}
    for d in deps:
        oos = ((d.get("result") or {}).get("out_of_sample") or {})
        lines.append(
            "- deployment_id=%s \"%s\" market=%s mode=%s status=%s live: %s closed trades, %s wins, realized $%.2f, %s open; "
            "backtest unseen-data: pnl $%s over %s trades, max drawdown $%s; %sspec=%s"
            % (d["id"], d["title"], d["market"], d["mode"], d["status"], d["closed_trades"], d["wins"],
               float(d["realized_pnl"]), d["open_positions"], oos.get("pnl"), oos.get("trades"), oos.get("max_drawdown"),
               _deployment_age_text(d), json.dumps(d["spec"], separators=(",", ":")))
        )
        scan = d.get("scan") or {}
        if scan.get("why"):
            # The engine's latest entry scan: which entry check stopped it, so a review can tell a
            # rule that never fires on the live book (a spec problem) from one waiting on a setup.
            lines.append("    last entry check: %s" % scan["why"])
        t = tally.get(d["id"]) or {}
        if t:
            # Today's decisions by outcome: a rule that never reaches 'qualified' over a whole
            # day of checks is a spec the live book doesn't produce, not a setup still to come.
            lines.append("    entry checks today: %d decisions, qualified %d; stopped at: %s" % (
                sum(t.values()), t.get("qualified", 0),
                ", ".join("%s (%d)" % kv for kv in sorted(((k, n) for k, n in t.items() if k != "qualified"),
                                                          key=lambda kv: -kv[1])) or "nothing"))
        if d["mode"] == "paper":
            # Realistic-fill evidence for the paper -> live gate, so reviews promote, keep or stop
            # paper deployments on what live would actually earn. Best-effort (test stub -> skip).
            try:
                lines.append("    paper evidence: " + paper_evidence_line(paper_evidence(cur, user["id"], d["strategy_id"])))
            except Exception:
                pass
    if not deps:
        lines.append("- none")
    # Research's track record on the live book, per market family: the backtest gate says what
    # passed, this says what held up on realistic paper fills. Steer research toward families whose
    # passes survive paper, away from ones whose passes bleed or never fire. Best-effort.
    try:
        from app import rsi
        paper_lines = rsi.paper_outcomes_lines(rsi.paper_outcomes(cur, user["id"]))
    except Exception:
        paper_lines = []
    if paper_lines:
        lines += ["", "How research's passes did on paper, by market family (all paper deployments, including stopped):"]
        lines += paper_lines
    try:
        from app import tournament
        t_lines = tournament.context_lines(tournament.standings(cur, user["id"]))
    except Exception:
        t_lines = []
    if t_lines:
        lines += [""] + t_lines
    try:
        from app import rsi
        lines += [""] + autopilot_scorecard_lines(autopilot_scorecard(
            rsi.load_scoreboard(cur, days=SCORECARD_DAYS, user_id=user["id"]), focus))
    except Exception:
        pass
    try:
        exit_line = early_exits_line(repo.early_exit_scorecard(cur, user["id"]))
    except Exception:
        exit_line = ""
    if exit_line:
        lines += ["", exit_line]
    lines += ["", "Passed strategies not deployed:"]
    spare = [s for s in passed if s["id"] not in deployed_ids][:10]
    any_candidate = False
    for s in spare:
        oos = ((s.get("result") or {}).get("out_of_sample") or {})
        # Honest, per-strategy deploy-readiness: the `deploy` action only clears a strategy the
        # gatekeeper promoted to DEPLOYMENT-CANDIDATE, so say which are actually promotable now —
        # otherwise the review keeps proposing deploys that get refused. Best-effort (test stub -> skip).
        try:
            cand = _is_deployment_candidate(cur, s["id"])
        except Exception:
            cand = False
        any_candidate = any_candidate or cand
        lines.append("- strategy_id=%s \"%s\" market=%s unseen-data pnl $%s over %s trades — %s"
                     % (s["id"], s["title"], s["market"], oos.get("pnl"), oos.get("trades"),
                        "DEPLOYMENT-CANDIDATE: ready to promote to PAPER now" if cand else
                        "not yet a deployment candidate (dig deeper before it can deploy)"))
    if not spare:
        lines.append("- none")
    if any_candidate:
        lines.append("ACT ON RESULTS: a DEPLOYMENT-CANDIDATE above is ready — PROMOTE it to paper this "
                     "review with a `deploy` action. Closing the research->paper loop on a proven edge "
                     "beats launching yet another exploratory line; only open fresh research if nothing "
                     "is ready to promote.")
    # Memory + situational awareness so a review doesn't repeat dead ends, double-launch research,
    # or spend blind to its budget. Each block is best-effort: a context-read hiccup must never fail
    # the whole review. ponytail: in tests `cur` is a stub, so these simply omit — no prompt churn.
    try:
        runs = repo.list_runs(cur, user["id"], limit=6)
    except Exception:
        runs = []
    if runs:
        lines += ["", "Recent research lines (don't re-launch one that is still active or just failed on the same idea):"]
        for r in runs:
            # "succeeded" only means the run FINISHED. Reviews read it as "found an edge" and told
            # the user two finished runs were "proven strategies ready for paper", then tried to
            # deploy strategies that had failed. Say what came out of it instead.
            st, passed = r["status"], int(r.get("strategies_passed") or 0)
            if st == "succeeded":
                st = "finished, %s" % ("%d strategy passed" % passed if passed == 1 else
                                       "%d strategies passed" % passed if passed else "NOTHING passed, no new strategy")
            lines.append("- run #%s on %s [%s]: %s tried, %s passed — \"%s\""
                         % (r["id"], r["market"], st, r.get("hypotheses_tried") or 0,
                            passed, (r.get("prompt") or "").strip()[:100]))
        # Per-market dedup, spelled out: a fresh `research` action on a market that is running or on
        # cooldown is REFUSED by act(), so name those markets here and tell the review to hunt a
        # different one — it wastes the whole turn otherwise. Mirrors _market_research_recent.
        busy = sorted({r["market"] for r in runs if r.get("status") in ("queued", "running", "paused") and r.get("market")})
        if busy:
            lines.append("OFF-LIMITS this review (a line is already running on them — pick a DIFFERENT market): "
                         + ", ".join(busy))
    dead: List[Dict] = []
    for st in ("failed", "rejected"):
        try:
            dead += repo.list_strategies(cur, user["id"], status=st, limit=10)
        except Exception:
            pass
    if dead:
        lines += ["", "Dead ends already tested and killed for this user — do NOT re-propose the same idea; "
                      "refine the mechanism or hunt elsewhere:"]
        for s in dead[:12]:
            lines.append('- "%s" (%s) — %s' % (s["title"], s["market"], s["status"]))
    try:
        paper = repo.paper_balance(cur, user["id"])
        demo = repo.demo_equity(cur, user["id"]).get("equity")
        credits = repo.credit_balance(cur, user["id"])
        lines += ["", "Account & budget: paper cash $%.2f, demo equity $%s, research credits $%.2f left. Real, "
                      "fee-surviving money is the goal — a validated edge only counts once it holds up on a live book."
                  % (paper, demo, credits)]
    except Exception:
        pass
    # PORTFOLIO VIEW: aggregate open exposure vs the user's caps, so the review manages the whole
    # book (concentration, headroom) and not one deployment at a time.
    try:
        expo = repo.user_open_exposure(cur, user["id"])
        lines.append("Aggregate open exposure: %s open positions, $%.2f entry notional (caps: max_open_positions=%s, "
                     "max_open_notional=%s). Manage the book as a whole — don't let exposure concentrate in one market."
                     % (expo.get("n"), float(expo.get("notional") or 0), risk.get("max_open_positions"),
                        risk.get("max_open_notional")))
    except Exception:
        pass
    try:
        ready = repo.series_with_candles(cur)
    except Exception:
        ready = None  # can't check (e.g. a test stub) -> don't filter
    # Only offer markets with a real backtest surface: a deployable market with NO collected history
    # (e.g. a freshly-catalogued series) crashes research with "no settled contracts". `not ready`
    # (None or empty) means we can't tell, so show everything rather than hide the whole list.
    deployable = [k for k, m in MARKETS.items() if m.deployable and (not ready or m.series in ready)
                  and in_focus(k, focus)]
    lines += ["", ("Markets you can research AND deploy RIGHT NOW (each has collected history, so it has a "
                   "backtest surface — research ONLY markets on this list; others have no settled contracts "
                   "and will crash). You are NOT limited to the one you've been trading: if a market has gone "
                   "quiet (no fills, no edges for days), HUNT A DIFFERENT one from this list, don't wait: "
                   + ", ".join("%s (%s)" % (k, MARKETS[k].label[:40]) for k in deployable))]
    try:
        from app import rsi_scout
        scan = rsi_scout.prompt_lines(cur, 8)
    except Exception:  # noqa: BLE001 - no scan table yet / a read hiccup: offer the list alone
        scan = ""
    if focus and scan:  # each line starts "- <market key> (": keep only leads inside the focus
        scan = "\n".join(l for l in scan.splitlines()
                          if in_focus((l[2:].split(" ", 1) or [""])[0], focus))
    if scan:
        lines += ["", ("FREE MISPRICING SCAN (each market's research window, no model spend; strongest measured "
                       "leads first). Some leads are luck across many markets, so the gate still decides, but "
                       "prefer researching a market with a lead over one without, and brief the mechanism the "
                       "lead points at:\n" + scan)]
    # PORTFOLIO-LEVEL direction: run the operation like a book, not a stream of one-off actions.
    lines += ["", ("RUN IT AS A PORTFOLIO: (1) DIVERSIFY research across different markets AND different "
                   "mechanisms — don't pile variants of one angle on one market. (2) STEER TOWARD DATA: "
                   "order-flow / microstructure features exist only on the BTC markets; sports and event "
                   "markets are feature-thin, so brief them on price/time/structure angles, not order-book "
                   "signals that would fit nothing. (3) PROMOTE OVER EXPLORE: a proven edge reaching paper "
                   "beats opening yet another exploratory line. (4) MANAGE AGGREGATE RISK, not one deployment "
                   "in isolation. Spend this review on COHERENT operation, and record the plan you're following.")]
    open_deps = [d for d in deps if d.get("status") != "stopped"]
    if not open_deps and not active_research:
        lines += ["", ("EMPTY DECK: you have ZERO running deployments and ZERO research in flight. Idling now "
                       "is a FAILURE — you MUST launch at least one new research line THIS review (a market "
                       "from the list above + a concrete mechanism). Do NOT reply 'waiting' or 'nothing to do' "
                       "with an empty deck: the loop only keeps moving if you keep research running.")]
    return "\n".join(lines)


ACTIONS_GUIDE = """Reply: {"reply": "<what you tell the user>", "actions": [ ... at most 3 ... ], "plan": {"goals": "...", "agenda": "...", "deployments": "...", "posture": "..."}}
"plan" is your durable OPERATING PLAN (optional on a chat reply; UPDATE IT on every scheduled review). It is how your reviews stay coherent across time instead of being independent one-shots. Keep each field to a sentence or two: goals = what this session is pursuing; agenda = the research portfolio you're running across markets/mechanisms and WHY; deployments = how each one is doing + your plan for it; posture = capital/risk stance. Rewrite it to reflect what you just learned and decided; it is shown back to you next review.
Actions:
  {"type": "adjust", "deployment_id": N, "changes": {<partial spec>}, "reason": "..."}   (TUNE a deployment's strategy/model PARAMETERS — any field of its spec, e.g. {"entry": {"min_edge": 0.08}}, {"sizing": {"stake": 4}}. The host re-backtests the new spec and applies it only if it still passes every gate. This is your main lever for improving a running strategy.)
  {"type": "set_risk", "changes": {"drawdown_limit_pct": 15, "max_open_positions": 10, "max_open_notional": 500}, "reason": "..."}   (Tune the user's RISK controls. Any subset of those three keys. Values are CLAMPED to a safe range — you can tighten freely; you can never set a limit to 0 or above the hard ceiling.)
  {"type": "set_exec", "changes": {"exec_max_book_fraction": 0.2, "exec_max_entry_spread": 0.05, "exec_max_order_notional": 100}, "reason": "..."}   (Tune the live EXECUTION controls. Any subset. Also clamped to a safe range. These only ever make an order smaller/safer and never block an exit.)
  {"type": "pause",  "deployment_id": N, "reason": "..."}
  {"type": "resume", "deployment_id": N, "reason": "..."}
  {"type": "research", "strategy_id": N, "reason": "..."}     (DIG DEEPER off a PASSED strategy — refine its parameters, stress-test it, extend the thesis. Each variant still has to pass the gates.)
  {"type": "research", "market": "<market key or omit to let me choose>", "idea": "<a short ANGLE/lens, NOT a full thesis>", "reason": "..."}   (FRESH research line. DELEGATE, don't author: `idea` is a high-level DIRECTION — a market + a short angle (e.g. "favorite-longshot on this sports market", "order-flow if this market has microstructure data") — and the research specialist writes the actual hypotheses and specs from it. Do NOT hand it a fully-formed strategy ("buy when implied>65%..."); that is the research pipeline's job, not yours. One or two sentences of angle is enough.)
  {"type": "deploy", "strategy_id": N, "reason": "..."}       (paper; any side)
  {"type": "set_focus", "focus": ["crypto"], "reason": "..."}   (ONLY when the USER asks in chat to focus on / stick to some markets: family names like crypto, sports, weather-high; coins like btc, eth; or market keys. [] clears it. It then binds every research and deploy. A scheduled review can't set it.)
  {"type": "alpaca_paper_order", "symbol": "AAPL", "side": "buy", "qty": "1", "limit_price": "100.00", "reason": "..."} (A separate Alpaca broker PAPER stock/ETF experiment. Whole shares, limit DAY only. Creates a ticket for explicit USER APPROVAL even when autopilot is on; it never executes from this action. Use the current paper account/positions and the user's instruction; do not infer a fill or convert a Kalshi binary strategy into an equity strategy. This is not live equity execution.)
  {"type": "kalshi_perps_order", "side": "bid", "count": "1", "price": "7.00", "reduce_only": false, "reason": "..."} (Native Kalshi BTC perps REAL-MONEY order proposal only. Whole contracts; price is USD PER CONTRACT, not BTC spot price. Bid buys/longs, ask sells/shorts; reduce_only must only reduce the current position. Kalshi determines account/product margin and leverage; there is no order leverage field or Tau financial cap. Always requires the owner to review a fresh exact order ticket and explicitly confirm, even with autopilot on. Never submit, approve, retry or claim execution yourself. Do not infer fills, access, buying power or liquidation safety. Research-only perps strategies remain ineligible for automatic deployment.)
  {"type": "deploy_live", "strategy_id": N, "reason": "..."}  (REAL money; any side (YES or NO) that already proved itself on PAPER, and only when the user turned on live autopilot. If live autopilot is off or any safety gate fails it is refused and stays on paper. Never the first step for a new idea: research -> paper -> live.)
Back your words with actions. If your reply says you ARE doing something — starting/launching research, tuning, pausing, promoting, deploying — you MUST include the matching action(s) in `actions`. A reply that merely DESCRIBES an action without emitting it does NOTHING (no research is launched, nothing changes) and is a failure: e.g. saying "I'll launch three research threads now" requires three `research` actions in this same response, not a promise to do it later. Conversely, never invent actions you have no concrete reason for — if the right move is to wait and watch, say so plainly and return an empty list. EXCEPTION: if the context says EMPTY DECK (zero deployments and zero research in flight), waiting is NOT allowed — you must emit at least one `research` action this turn.
The host may REFUSE any action (a paper strategy younger than its minimum age can't be paused, the live gate, cooldowns, limits); each action's result is posted as its own line right after your reply. So write actions as what you are ASKING for ("asking to pause #78"), never as done ("paused #78", "released 8 positions"), and quote dollar amounts, trade counts and position counts exactly as the context above states them: never estimate, round or infer one.
CLOSE THE LOOP: research only pays off when a proven edge reaches the book. If a passed strategy is a DEPLOYMENT-CANDIDATE, promoting it to paper (a `deploy` action) takes priority over opening a new exploratory research line — don't explore forever while a ready edge sits undeployed. And don't re-launch research on a market that is already running or just finished: that line is refused; hunt a DIFFERENT market from the list.
""" + specmod.SPEC_GUIDE


# Action kinds whose act() branch returns a proposal id whenever it did or proposed something,
# so None means the host refused it. research and set_focus return None on success too.
PROPOSAL_ACTIONS = frozenset({"adjust", "pause", "resume", "deploy", "deploy_live", "set_risk", "set_exec"})


def _action_kind(action: Dict) -> str:
    return str(action.get("type") or action.get("kind") or "").strip().lower()


def _copilot_check(obj: Dict) -> Dict:
    reply = str(obj.get("reply") or "").strip()
    actions = obj.get("actions") or []
    if not reply:
        raise ValueError("'reply' is required")
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS or not all(isinstance(a, dict) for a in actions):
        raise ValueError("'actions' must be a list of at most %d objects" % MAX_ACTIONS)
    plan = obj.get("plan")  # optional operating plan; repository.set_autopilot_plan bounds/sanitizes it
    return {"reply": reply[:4000], "actions": actions, "plan": plan if isinstance(plan, dict) else None}


def run_copilot(conn, run: Dict, model: Optional[ModelFn] = None, dataset_fn=backtest.dataset) -> None:
    """kind='chat' answers the user's latest message; kind='review' is the
    agent checking in on its own (run.prompt says why)."""
    cur = conn.cursor()
    usage = Usage()
    billing_attempted = False
    user = repo.get_user(cur, run["user_id"])
    # Honor the user's autopilot model (NULL = catalog default) so a review/chat runs on — and is
    # billed at — the model they picked, not always the global default. Tests pass their own `model`.
    choice = catalog.resolve(run.get("model") or (user or {}).get("autopilot_model"))
    if run["kind"] == "review" and catalog.get(REVIEW_MODEL_KEY):
        choice = catalog.get(REVIEW_MODEL_KEY)
    if model is None:
        model = lambda system, messages, on_delta=None: claude(system, messages, choice.model_id, on_delta)  # noqa: E731

    def checkpoint() -> None:
        nonlocal cur
        cur = _reconnect(conn, cur)
        if repo.heartbeat(cur, run["id"]) == "cancelled":
            raise Cancelled()

    try:
        checkpoint()
        history = repo.chat_messages(cur, user["id"], limit=20)
        # A scheduled REVIEW must reason from the LIVE state below, NOT its own prior chat narrative:
        # feeding back its last "research still running" replies made it parrot them and never act.
        # Keep only the USER's recent messages (their directives persist) and drop the co-pilot's own
        # stale output. A real chat run keeps the full transcript to answer the user's message.
        if run["kind"] == "review":
            history = [m for m in history if m.get("role") == "user"][-3:]
            # Funnel first, so the review below already sees the new paper deployments.
            try:
                for line in auto_paper_candidates(cur, user):
                    repo.add_chat(cur, user["id"], "system", line)
            except Exception as e:  # best-effort: never block the review itself
                print("[agent] auto-paper failed for user %s: %r" % (user["id"], e), flush=True)
            try:
                for line in auto_paper_probation(cur, user):
                    repo.add_chat(cur, user["id"], "system", line)
            except Exception as e:  # best-effort, like the funnel above
                print("[agent] paper probation failed for user %s: %r" % (user["id"], e), flush=True)
            try:
                from app import tournament
                for line in tournament.rebalance(cur, user):
                    repo.add_chat(cur, user["id"], "system", line)
            except Exception as e:  # best-effort, like the funnel above
                print("[agent] tournament rebalance failed for user %s: %r" % (user["id"], e), flush=True)
            try:
                live_ready_notices(cur, user)  # adds its own chat lines
            except Exception as e:  # best-effort, like the funnel above
                print("[agent] live-ready notice failed for user %s: %r" % (user["id"], e), flush=True)
            try:
                pause_notice(cur, user, run)
            except Exception as e:  # best-effort, like the funnel above
                print("[agent] pause notice failed for user %s: %r" % (user["id"], e), flush=True)
        transcript = "\n".join("%s: %s" % (m["role"], m["content"]) for m in history)
        if run["kind"] == "review":
            task = ("Scheduled autopilot review. Why: %s\n"
                    "You are the OPERATION MANAGER. MANAGE the operation coherently — don't author strategies yourself. "
                    "When you decide to research, DELEGATE: hand the research specialist a market + a short ANGLE and let it "
                    "write the hypotheses; do not spell out a full thesis/spec (that is its job, and it has the deep per-thesis "
                    "loop + market-aware data you don't). Follow and REWRITE your operating plan above (the 'plan' field of your "
                    "reply) so this review builds on the last one. "
                    "You are running on your own now — PROACTIVELY MANAGE the operation within your mandate, don't just describe it. "
                    "Assess every deployment and open position, then take the actions that improve results: start a research run to "
                    "explore a promising angle (same RSI pipeline as a manual run), promote a proven strategy (paper, or live within caps "
                    "when live autopilot is on), tune model/risk/execution parameters, or pause/flatten if risk warrants. "
                    "Only adjust/pause/resume deployments that appear in the Deployments list above, by their exact deployment_id — "
                    "ones you named in earlier messages may have been removed and no longer exist. If the market you've been trading has "
                    "gone quiet for days (no fills, no passing edges), that is NOT a reason to wait or 'step aside' — research a DIFFERENT "
                    "market from the list (other coins, sports, weather; inside the user's market focus when one is set); a dead regime in one market is not a dead regime everywhere, and "
                    "sitting idle while 18 other markets are open is as passive as forcing a bad trade. If there is genuinely nothing worth "
                    "doing, say so briefly. Use the context above: don't re-launch a research line that is still active or "
                    "just failed, and don't re-propose an idea already in the dead-ends list — refine its mechanism or hunt "
                    "elsewhere. Pull capital out of a deployment that is bleeding or flat-after-enough-trades instead of letting "
                    "a loser ride. Every money/risk value you set is clamped and the loss budget / kill switch / live gate still bound you." % run.get("prompt"))
        else:
            task = "Answer the user's latest message."
        prompt = "%s\n\nRecent conversation:\n%s\n\n%s\n\n%s" % (_copilot_context(cur, user), transcript or "(none)", task, ACTIONS_GUIDE)
        from app import alpaca_paper
        if alpaca_paper.enabled():
            prompt += "\n\n" + alpaca_paper.agent_context(conn, user["id"])
        from app import kalshi_perps_trading
        if kalshi_perps_trading.enabled():
            prompt += "\n\n" + kalshi_perps_trading.agent_context(conn, user["id"])
        market_data = AgentMarketData(DataScope(), lambda kind, message, data=None:
                                     repo.add_event(cur, run["id"], kind, message, data), checkpoint)
        knowledge = AgentKnowledge(DataScope(), lambda kind, message, data=None:
                                   repo.add_event(cur, run["id"], kind, message, data), checkpoint)
        news = AgentNews(DataScope(), lambda kind, message, data=None:
                        repo.add_event(cur, run["id"], kind, message, data), checkpoint)
        out = market_data.ask(knowledge.wrap(news.wrap(model, usage), usage), COPILOT_SYSTEM,
                              [{"role": "user", "content": prompt}], _copilot_check, usage)
        checkpoint()
        # A scheduled REVIEW speaks only when it ACTS (user's choice): a no-op review still runs,
        # updates its plan and bills, but posts nothing — otherwise every idle review drops a
        # "nothing to change" line that reads as noise and makes a working autopilot look idle. A
        # chat run (the user asked) always answers; an acting review posts its reply + action lines.
        # Persist the updated operating plan so the next review reasons from it (coherent across
        # time). set_autopilot_plan bounds + sanitizes it, so a huge/garbage value can't bloat the row.
        if out.get("plan"):
            repo.set_autopilot_plan(cur, user["id"], out["plan"])
        # The actions run BEFORE the reply posts, so a review whose every action the host refused
        # can stay quiet: its reply narrates things that didn't happen. Todd's 04:03Z review said
        # "Paused both paper deployments... Released 8 stuck positions" while both pauses were
        # refused (too young) and 7 positions were still open (2026-10-25). The refusal lines say it.
        notes, refused = [], 0
        for action in out["actions"]:
            checkpoint()
            if str(action.get("type") or action.get("kind") or "").strip().lower() == "set_focus":
                text, proposal_id = set_focus_action(cur, user, action, run["kind"]), None
                user = repo.get_user(cur, user["id"]) or user  # later actions in this reply honour it
                if not text:
                    continue
            elif str(action.get("type") or action.get("kind") or "").strip().lower() in ("alpaca_paper_order", "kalshi_perps_order"):
                with repo.transaction(conn) as tx:
                    text, proposal_id = act(tx, user, action, bool(user.get("autopilot")), dataset_fn)
            else:
                text, proposal_id = act(cur, user, action, bool(user.get("autopilot")), dataset_fn)
            if proposal_id is None and _action_kind(action) in PROPOSAL_ACTIONS:
                refused += 1  # these kinds return a proposal id whenever they did (or proposed) something
            notes.append((text, proposal_id))
        if run["kind"] != "review" or (out["actions"] and refused < len(out["actions"])):
            repo.add_chat(cur, user["id"], "agent", out["reply"])
        for text, proposal_id in notes:
            # A scheduled review that keeps hitting the same refusal ("you already have research
            # running") posted it every 10 minutes. Say it once per REPEAT_NOTE_WINDOW; anything
            # that did something (a proposal) or that the user asked for always posts.
            if (run["kind"] == "review" and proposal_id is None
                    and repo.recent_chat_same(cur, user["id"], "system", text, repo.now_utc() - REPEAT_NOTE_WINDOW)):
                continue
            repo.add_chat(cur, user["id"], "system", text, proposal_id)
        repo.finish_run(cur, run["id"], "succeeded", None, 0, 0, usage.input_tokens, usage.output_tokens)
        # Same greppable shape as research_outcome_line, so review vs research token cost can be
        # split from the worker log (reviews outnumber research runs about 3:2 in prod).
        print("[copilot] run=%s user=%s kind=%s status=succeeded actions=%d tokens_in=%d tokens_out=%d model=%s"
              % (run["id"], user["id"], run["kind"], len(out["actions"]), usage.input_tokens,
                 usage.output_tokens, choice.model_id), flush=True)
        billing_attempted = True
        _bill(conn, user["id"], usage, run["id"], choice.model_id)
    except Cancelled:
        repo.add_event(cur, run["id"], "step", "Cancelled.")
        if not billing_attempted:
            billing_attempted = True
            _bill(conn, user["id"], usage, run["id"], choice.model_id)
    except Exception as e:
        print("[agents] copilot run %s failed: %r" % (run["id"], e), flush=True)
        cur = _reconnect(conn, cur)
        repo.add_chat(cur, user["id"], "system",
                      "The agent hit an error and didn't answer. Send your message again, or try in a minute.")
        repo.finish_run(cur, run["id"], "failed", str(e)[:2000], 0, 0, usage.input_tokens, usage.output_tokens)
        if not billing_attempted:
            billing_attempted = True
            _bill(conn, user["id"], usage, run["id"], choice.model_id)  # charge for the work done regardless of the failure cause
        if not isinstance(e, LLMError):
            raise
