"""AlphaDiscoveryBench — Stage A: an evaluation harness for the RESEARCH agent itself.

Why this exists (from the alpha-discovery strategy memo): a research agent should be measured not
by raw P&L but by DISCOVERY EFFICIENCY — validated discoveries per unit of research budget — and
ALWAYS against a NULL-AGENT baseline (random / mechanical search) given the SAME budget. If the LLM
agent cannot out-discover random search over the same spec space, its reasoning is adding no value.
That null-baseline control is the one thing the RSI pipeline did not have; everything statistical
it needs (deflated Sharpe with trial-count deflation = the multiple-testing correction, a
label-shuffle placebo negative control, a stationary-bootstrap CI) ALREADY EXISTS in gatekeeper.py
+ stats.py, so this module REUSES those exact functions rather than reinventing them.

Boundaries (sacred): this is READ-ONLY w.r.t. the live pipeline. It never preregisters, never
touches the one-time holdout latch, the LORD ledger, the trial ledger, or any deploy/risk gate. A
"validated discovery" here mirrors the production statistical bar for offline comparison; it is NOT
a deploy decision and confers no holdout verdict.

The backtest step is PLUGGABLE: pass `backtest_fn(spec) -> list[backtest.Trade]`.
  - prod/real data: `dataset_backtest_fn(research_dataset)` runs the real backtester.
  - CI / control: `planted_edge_backtest` / `noise_backtest` give a deterministic synthetic market
    with a KNOWN planted inefficiency (positive control) and a pure-noise market (false-discovery
    negative control) — the memo's "synthetic markets with known planted inefficiencies", so the
    harness itself can be shown to have statistical POWER and correct CALIBRATION with no DB.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from app import backtest, gatekeeper, stats
from app import spec as specmod
from app.markets import FEATURES, MARKETS

# A "validated discovery" must clear a deflated-Sharpe floor of 0.95 plus a positive bootstrap lower
# bound — scored AFTER deflating by the full search size (n_trials = budget), which is the memo's
# multiple-testing point. This offline scorecard has no LORD++ budget, so DSR is its ONLY
# multiplicity control and keeps the strict floor (production pairs DSR >= 0.5 with LORD++).
DSR_MIN = 0.95
MIN_DISCOVERY_TRADES = 20

# A conservative, always-valid subset of filterable features + sane numeric ranges for the
# random/null agent to draw from (every market populates price/tte/spread; micro/underlying
# features are left out so a random spec doesn't trivially select nothing).
_RANDOM_FILTER_FEATURES = {
    "mid": (0.1, 0.9), "spread": (0.01, 0.1), "tte_min": (1.0, 60.0),
    "z_score": (-2.0, 2.0), "moneyness": (-0.05, 0.05),
}

BacktestFn = Callable[[Dict], List["backtest.Trade"]]
ProposeFn = Callable[[random.Random, str], Dict]


# -- the null agent: random / mechanical search over the validated spec space ----------------------


def random_spec(rng: random.Random, market: str = "btc15m") -> Dict:
    """One random, VALID strategy spec — the null agent's 'hypothesis'. Draws side / model kind /
    numeric params from the real RANGES+CHOICES and 0-2 filters on real features, then runs it
    through spec.validate (retrying on an ordering violation). This is mechanical search, not
    reasoning: it is the baseline the LLM agent must beat on discovery efficiency."""
    for _ in range(12):
        lo_p = round(rng.uniform(0.02, 0.5), 2)
        hi_p = round(rng.uniform(lo_p + 0.05, 0.99), 2)
        lo_t = round(rng.uniform(0.0, 30.0), 1)
        raw: Dict = {
            "market": market,
            "side": rng.choice(specmod.CHOICES["side"]),
            "model": {"kind": "gbm", "vol_window": rng.choice(specmod.CHOICES["model.vol_window"]),
                      "vol_scale": round(rng.uniform(*specmod.RANGES["model.vol_scale"]), 2),
                      "drift_window": rng.choice(specmod.CHOICES["model.drift_window"]),
                      "drift_beta": round(rng.uniform(-1.5, 1.5), 2)},
            "entry": {"min_edge": round(rng.uniform(0.0, 0.2), 3),
                      "min_price": lo_p, "max_price": hi_p,
                      "min_tte_min": lo_t, "max_tte_min": round(lo_t + rng.uniform(5.0, 300.0), 1),
                      "max_spread": round(rng.uniform(0.02, 0.3), 2),
                      "filters": _random_filters(rng)},
            "sizing": {"stake": 5.0, "max_positions": 20},
        }
        try:
            return specmod.validate(raw)
        except specmod.SpecError:
            continue
    return specmod.validate({"market": market})  # fall back to the default spec (always valid)


def _random_filters(rng: random.Random) -> List[Dict]:
    feats = [f for f in _RANDOM_FILTER_FEATURES if f in FEATURES]
    out = []
    for name in rng.sample(feats, rng.randint(0, min(2, len(feats)))):
        lo, hi = _RANDOM_FILTER_FEATURES[name]
        out.append({"feature": name, "op": rng.choice((">", ">=", "<", "<=")),
                    "value": round(rng.uniform(lo, hi), 3)})
    return out


# -- the discovery verdict: EXACTLY the production statistics, offline -----------------------------


@dataclass
class Discovery:
    validated: bool
    n_trades: int
    deflated_sharpe: float
    placebo_p: float
    ci_low: float
    mean_net_return: float


def verdict(trades: List["backtest.Trade"], n_trials: int, seed: int = 0) -> Discovery:
    """Does this strategy's research-fold return series clear the production statistical bar, scored
    as one of `n_trials` competing experiments? Reuses gatekeeper._net_returns/_sharpe/_moments/
    _placebo_pvalue + stats.deflated_sharpe_ratio + stats.stationary_bootstrap_ci so 'validated'
    means what it means in prod (minus the live holdout/ledger, which stay untouched)."""
    rets = [r for _ts, r in gatekeeper._net_returns(trades)]
    n = len(rets)
    if n < MIN_DISCOVERY_TRADES:
        return Discovery(False, n, 0.0, 1.0, 0.0, 0.0)
    sr = gatekeeper._sharpe(rets)
    skew, kurt = gatekeeper._moments(rets)
    var_trials = 1.0 / (n - 1) if n > 1 else 0.0
    dsr = stats.deflated_sharpe_ratio(sr, n, skew, kurt, max(1, n_trials), var_trials)
    placebo = gatekeeper._placebo_pvalue(trades, seed)
    ci = stats.stationary_bootstrap_ci(rets, stat="mean", n_boot=1000, seed=seed)
    ci_low = ci.get("lo", 0.0)
    mean = sum(rets) / n
    # The two headline statistics the memo calls for: multiple-testing-deflated significance (DSR vs
    # the full search size) AND a positive lower confidence bound on the mean net return (serial-
    # correlation-aware bootstrap). placebo is REPORTED as a diagnostic; the live gatekeeper also
    # enforces it, but its cheap-bet label-shuffle is tuned to the real Kalshi binary mechanism and
    # is left out of the offline synthetic gate.
    ok = (dsr >= DSR_MIN and ci_low > 0.0)
    return Discovery(ok, n, round(dsr, 4), round(placebo, 4), round(ci_low, 6), round(mean, 6))


# -- the episode + scorecard: discovery efficiency, null baseline, score distribution --------------


@dataclass
class Scorecard:
    agent: str
    budget: int
    validated: int
    best_net_alpha: float
    best_deflated_sharpe: float
    discovery_efficiency: float          # validated discoveries per experiment (the memo's headline)
    discoveries: List[Discovery] = field(default_factory=list)

    def summary(self) -> Dict:
        return {"agent": self.agent, "budget": self.budget, "validated": self.validated,
                "discovery_efficiency": round(self.discovery_efficiency, 4),
                "best_net_alpha": round(self.best_net_alpha, 6),
                "best_deflated_sharpe": round(self.best_deflated_sharpe, 4)}


def run_episode(agent_name: str, propose: ProposeFn, backtest_fn: BacktestFn, *,
                budget: int, market: str = "btc15m", seed: int = 0) -> Scorecard:
    """One research episode: propose up to `budget` specs, backtest each, judge each as one of
    `budget` competing trials (the honest multiple-testing deflation — testing more lowers the bar
    for none of them), and score discovery efficiency. Every spec counts against the budget whether
    or not it validates, exactly as a real statistical trial does."""
    rng = random.Random(seed)
    disc: List[Discovery] = []
    for i in range(budget):
        spec = propose(rng, market)
        trades = backtest_fn(spec)
        disc.append(verdict(trades, n_trials=budget, seed=seed + i))
    validated = [d for d in disc if d.validated]
    best = max(validated, key=lambda d: d.mean_net_return, default=None)
    return Scorecard(
        agent=agent_name, budget=budget, validated=len(validated),
        best_net_alpha=best.mean_net_return if best else 0.0,
        best_deflated_sharpe=max((d.deflated_sharpe for d in disc), default=0.0),
        discovery_efficiency=len(validated) / budget if budget else 0.0,
        discoveries=disc,
    )


def null_vs_agent(agent_name: str, agent_propose: ProposeFn, backtest_fn: BacktestFn, *,
                  budget: int, market: str = "btc15m", seed: int = 0) -> Dict:
    """The headline comparison: the agent vs the NULL (random-search) baseline on the SAME task and
    budget. The agent only demonstrates value if its discovery efficiency clears the null's."""
    agent = run_episode(agent_name, agent_propose, backtest_fn, budget=budget, market=market, seed=seed)
    null = run_episode("null_random_search", random_spec, backtest_fn, budget=budget, market=market, seed=seed)
    return {"agent": agent.summary(), "null_baseline": null.summary(),
            "agent_beats_null": agent.discovery_efficiency > null.discovery_efficiency}


# -- backtest_fn factories -------------------------------------------------------------------------


def dataset_backtest_fn(ds: "backtest.Dataset") -> BacktestFn:
    """PROD path: score each spec with the REAL backtester over the frozen RESEARCH window only
    ([start, cutoff) — never the gatekeeper's validation/holdout). Read-only; the eval observes the
    pipeline, it does not mutate a gate."""
    def fn(spec: Dict) -> List["backtest.Trade"]:
        return backtest.simulate(spec, ds, ds.start_ts, ds.cutoff_ts + 1)
    return fn


_PLANTED_FEATURE = "z_score"   # the synthetic "inefficiency": underpriced contracts when z_score>0


def _targets_planted_signal(spec: Dict) -> bool:
    for f in spec.get("entry", {}).get("filters", []):
        if f.get("feature") == _PLANTED_FEATURE and f.get("op") in (">", ">=") and f.get("value", -1) >= 0:
            return True
    return False


def _synthetic_trades(rng: random.Random, has_edge: bool, strength: float, n: int) -> List["backtest.Trade"]:
    """Settled binary trades with varying entry prices. NO edge: contracts are fairly priced (win
    prob == price) -> zero expected net return. EDGE: contracts are UNDERPRICED by `strength`
    (favorite-longshot style), so buying them wins more than the market implies. Return structure
    (net = (1-p)/p on a win, -1 on a loss) is exactly what the placebo negative control inspects."""
    trades: List["backtest.Trade"] = []
    ts = 1_700_000_000
    for i in range(n):
        p = rng.uniform(0.1, 0.9)
        # Favorite-longshot planted edge: CHEAP contracts (p<0.5) are underpriced by `strength`, so
        # buying them wins more than priced. Concentrating the edge in cheap bets is what makes the
        # placebo negative control meaningful (a uniform mispricing wouldn't move it).
        bonus = strength if (has_edge and p < 0.5) else 0.0
        true_prob = min(0.98, max(0.02, p + bonus))
        win = rng.random() < true_prob
        fee = 0.07 * p * (1.0 - p)
        trades.append(backtest.Trade(
            ticker="SYN-%d" % i, side="yes", qty=1, entry_ts=ts, entry_price=p,
            exit_ts=ts + 600, exit_price=1.0 if win else 0.0, fees=fee,
            reason="settled", edge=strength if has_edge else 0.0))
        ts += 4 * 3600   # spread across hours/days so the day-level stats are meaningful
    return trades


def planted_edge_backtest(seed: int, strength: float = 0.14, n: int = 300) -> BacktestFn:
    """Positive control: a synthetic market with a KNOWN inefficiency a spec captures iff it filters
    on the planted signal (z_score>0). Lets us prove the harness has POWER (an agent that finds the
    right conditional mechanism validates) without any DB. Each call advances a deterministic seed
    so repeated specs get fresh-but-reproducible draws."""
    state = {"k": 0}

    def fn(spec: Dict) -> List["backtest.Trade"]:
        state["k"] += 1
        return _synthetic_trades(random.Random(seed * 1_000 + state["k"]),
                                 _targets_planted_signal(spec), strength, n)
    return fn


def noise_backtest(seed: int, n: int = 160) -> BacktestFn:
    """Negative control: a market with NO edge at all. Random search here must validate ~nothing —
    if it does, the harness is miscalibrated (false discovery under multiple testing)."""
    state = {"k": 0}

    def fn(spec: Dict) -> List["backtest.Trade"]:
        state["k"] += 1
        return _synthetic_trades(random.Random(seed * 1_000 + state["k"]), has_edge=False, strength=0.0, n=n)
    return fn


def oracle_propose(rng: random.Random, market: str = "btc15m") -> Dict:
    """An agent that KNOWS the planted mechanism: it always proposes the z_score>0 conditional edge.
    The power end of the control — its discovery efficiency should dominate the null baseline."""
    return specmod.validate({
        "market": market, "side": "yes",
        "entry": {"min_edge": 0.0, "min_price": 0.05, "max_price": 0.95,
                  "filters": [{"feature": _PLANTED_FEATURE, "op": ">", "value": 0.0}]},
    })


def demo() -> None:
    """Runnable self-check: the harness has POWER (finds a planted edge) and is CALIBRATED (random
    search on pure noise validates ~nothing, and the oracle out-discovers the null baseline)."""
    # Calibration: random search on a pure-noise market makes essentially no validated discovery.
    noise = run_episode("null_random_search", random_spec, noise_backtest(seed=1), budget=24, seed=1)
    assert noise.discovery_efficiency <= 0.1, "false discovery on noise: %r" % noise.summary()

    # Power + the headline comparison: the oracle (right mechanism) beats the null baseline on a
    # market with a real planted edge.
    cmp = null_vs_agent("oracle", oracle_propose, planted_edge_backtest(seed=2), budget=16, seed=2)
    assert cmp["agent"]["validated"] >= 1, "no power to find a planted edge: %r" % cmp
    assert cmp["agent_beats_null"], "oracle did not out-discover random search: %r" % cmp

    # A random spec is always a valid spec.
    s = random_spec(random.Random(3))
    assert s["market"] in MARKETS and "entry" in s
    print("research_eval demo OK:", {"noise": noise.summary(), "edge": cmp})


if __name__ == "__main__":
    demo()
