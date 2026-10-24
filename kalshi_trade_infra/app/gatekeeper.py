"""The Statistical Gatekeeper: the only component that may read Validation and Locked-
Holdout data, that records every experiment in the immutable ledger, and that spends the
online-FDR alpha-wealth budget. Separate from the generator by construction
(RESEARCH_PIPELINE_DESIGN.md §B.2).

STRUCTURAL SEPARATION (the whole point): this module imports the validation/holdout dataset
loaders (`partitions.validation_dataset` is fed in as `val_ds`; `partitions.holdout_dataset`
is called directly here). agent.py imports NEITHER — grep agent.py for a validation/holdout
dataset call and you find none. The generator only ever gets a `Classification` enum back; it
never sees a p-value, a CI, or a held-out pnl.

Verdicts are tests, not threshold point estimates: a stationary-bootstrap one-sided p-value
(the PRIMARY validation p-value, autocorrelation-robust), PSR/DSR (Sharpe corrected for
non-normality and for selection across the AUDITED number of competing trials), an online
LORD++ alpha-wealth budget (cross-run stream) plus Benjamini-Hochberg within a chunk, and a
label-shuffle negative control. All stats math lives in app.stats; this module only wires it
to the ledger and classifies.

ponytail: per-trade returns, moments, and the placebo are plain-python loops over a few
hundred trades — well within reach without numpy here. Vectorize only if profiling says so.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import random
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from app import backtest, partitions, quant, stats
from app import research_repository as rr
from app import spec as specmod

log = logging.getLogger(__name__)

# -- operator-tunable knobs (§B.2) ---------------------------------------------
ALPHA = 0.10            # FDR / CI / p-value level
# Deflated-Sharpe floor for STAT_SUPPORTED. 0.5 = the observed Sharpe beats the expected best of
# the competing zero-edge trials (a selection check). Significance is LORD++'s job: a 0.95 floor
# stacked on the online-FDR budget corrected twice for the same multiplicity and blocked most
# realistic 5-8c edges (Todd's decision, 2026-10-24).
DSR_MIN = 0.5
CORR_MAX = 0.80         # marginal-contribution: max |corr| to a deployed peer
PLACEBO_SHUFFLES = 200  # label-shuffle negative-control resamples
_BOOT_SEED = 12345      # base seed; per-experiment offset keeps verdicts deterministic

# Cross-day generalization gate (§E.6 / beta-tester ask): a "passed" strategy must hold as a
# PATTERN across days/folds, not a one-window fluke. This can only make STAT_SUPPORTED harder.
CROSS_DAY_SPLITS = 4           # purged walk-forward folds over the validation trades
CROSS_DAY_MIN_FOLDS = 3        # need at least this many folds to judge generalization
CROSS_DAY_MIN_POS_FRACTION = 0.5   # a majority of folds must be net-positive
CROSS_DAY_MAX_DAY_SHARE = 0.90     # no single day may carry >90% of the positive edge

# Validation-budget pre-screen: a finalist is sent to validation (and spends LORD++ alpha) only if
# its leak-free research-fold edge, projected onto the validation window's expected trade count,
# gives at least this probability of clearing the NEXT alpha level. Hopeless tests otherwise
# decay the stream's alpha toward zero and starve the real candidates behind them.
POWER_MIN = 0.20
POWER_MIN_RESEARCH_TRADES = 10


class HoldoutConsumed(Exception):
    """Raised when a one-time Locked-Holdout evaluation is refused: the experiment is not yet
    STAT_SUPPORTED, the holdout window is consumed / at its evaluation cap, or this experiment
    already has a holdout verdict. The one-way latch the design (§F) calls sacred."""


class Classification(str, Enum):
    REJECTED = "rejected"                          # failed in-research, no mechanism, or placebo-equivalent
    INCONCLUSIVE = "inconclusive"                  # tested, evidence too weak to move (budget-aware)
    PROMISING = "promising"                        # in-research edge, not yet validation-tested
    STAT_SUPPORTED = "statistically_supported"     # passed validation under FDR + DSR
    FORWARD_VALIDATED = "forward_validated"        # passed the one-time Locked-Holdout
    DEPLOYMENT_CANDIDATE = "deployment_candidate"  # forward-validated AND marginal-contribution OK


@dataclass
class Prereg:
    """Everything fixed BEFORE any validation number is seen. The hash of (frozen spec +
    rationale) is the experiment's identity in the ledger. Built by agent.py from the
    proposer+challenger output (§C)."""
    user_id: int
    run_id: Optional[int]
    market: str
    spec: dict
    economic_rationale: str
    primary_metric: str = "mean_net_return_per_trade"
    null_hypothesis: str = ""
    alt_hypothesis: str = ""
    planned_test: str = "stationary_bootstrap one-sided, alpha from LORD++"
    falsification_criteria: str = ""
    min_sample: int = 30
    cost_assumptions: dict = field(default_factory=dict)
    # What data this hypothesis looked at: {"features": [...], "sources": [...]}. Keeps the
    # "any dataset" freedom auditable - every strategy records the features/tables it used.
    data_provenance: dict = field(default_factory=dict)
    research_partition_id: int = 0
    planned_n_tests: int = 1
    correction_method: str = "LORD++"
    strategy_id: Optional[int] = None

    def hypothesis_hash(self) -> str:
        """sha256 of the frozen spec (canonical JSON) + economic rationale. Identical frozen
        hypotheses hash equal, so re-registration is idempotent."""
        h = hashlib.sha256()
        h.update(json.dumps(self.spec, sort_keys=True, separators=(",", ":")).encode())
        h.update(b"\x00")
        h.update((self.economic_rationale or "").encode())
        return h.hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """The plain dict research_repository.preregister consumes, with the hash filled in."""
        d = asdict(self)
        d["hypothesis_hash"] = self.hypothesis_hash()
        return d


def preregister(cur, pre: Prereg) -> int:
    """Insert the IMMUTABLE pre-registration row; returns experiment_id. Idempotent on
    (run_id, hypothesis_hash) via the repository layer."""
    return rr.preregister(cur, pre.to_dict())


# -- per-trade return extraction + moments -------------------------------------


def _per_trade(trades) -> List[Tuple[int, int, float]]:
    """(entry_ts, exit_ts, net_return) per trade, ordered by entry time, skipping zero-cost
    trades. net_return = pnl / (qty * entry_price). The one place the trade -> return series is
    built, so the bootstrap, PSR/DSR and the cross-day folds all score the same quantity."""
    out: List[Tuple[int, int, float]] = []
    for t in sorted(trades, key=lambda x: x.entry_ts):
        cost = getattr(t, "capital_at_risk", t.qty * t.entry_price)
        if cost <= 0:
            continue
        out.append((int(t.entry_ts), int(t.exit_ts), t.pnl / cost))
    return out


def _net_returns(trades) -> List[Tuple[int, float]]:
    """(entry_ts, net_return) series the bootstrap and PSR/DSR consume."""
    return [(ets, r) for ets, _x, r in _per_trade(trades)]


def _cross_day(trades) -> Tuple[bool, List[Dict[str, Any]], float]:
    """Cross-day generalization check. Splits the validation trades into purged walk-forward
    folds (stats.purged_walkforward_splits; embargo only trims TRAIN, so the test blocks we score
    are unaffected and embargo=0 is fine) and also buckets per-trade returns by calendar day.
    The edge GENERALIZES only if a majority of folds are net-positive AND no single day carries
    almost all of the positive return. Returns (ok, folds, max_day_share). Too few trades for
    CROSS_DAY_MIN_FOLDS folds -> ok=False (we cannot establish generalization, so we do not pass
    it). ok feeds _classify: it can only block STAT_SUPPORTED, never grant it."""
    rows = _per_trade(trades)
    folds: List[Dict[str, Any]] = []
    if len(rows) >= CROSS_DAY_SPLITS + 1:
        splits = stats.purged_walkforward_splits([r[0] for r in rows], [r[1] for r in rows],
                                                 CROSS_DAY_SPLITS, 0)
        for sp in splits:
            vals = [rows[i][2] for i in sp["test_idx"]]
            if not vals:
                continue
            folds.append({
                "from_ts": int(sp["test_from_ts"]), "to_ts": int(sp["test_to_ts"]),
                "n_trades": len(vals),
                "mean_net_return": round(sum(vals) / len(vals), 8),
                "net_return": round(sum(vals), 8),
            })
    by_day: Dict[int, float] = {}
    for ets, _x, r in rows:
        by_day[ets // 86400] = by_day.get(ets // 86400, 0.0) + r
    positive = [v for v in by_day.values() if v > 0]
    total_pos = sum(positive)
    day_share = (max(positive) / total_pos) if total_pos > 0 else 1.0
    n_folds = len(folds)
    pos_folds = sum(1 for f in folds if f["net_return"] > 0)
    ok = (n_folds >= CROSS_DAY_MIN_FOLDS
          and pos_folds / n_folds >= CROSS_DAY_MIN_POS_FRACTION
          and day_share <= CROSS_DAY_MAX_DAY_SHARE)
    return ok, folds, day_share


def _sharpe(rets: List[float]) -> float:
    """Per-trade (non-annualized) Sharpe = mean / sample std (ddof=1). Matches stats'
    "sharpe" bootstrap stat so PSR/DSR are computed on the same quantity."""
    n = len(rets)
    if n < 2:
        return 0.0
    m = sum(rets) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (n - 1))
    return m / sd if sd > 0 else 0.0


def _moments(rets: List[float]) -> Tuple[float, float]:
    """Sample skewness and FULL (non-excess, normal=3) kurtosis of the return series, for
    PSR's non-normality correction. Returns (skew, kurt); a degenerate (zero-variance) series
    collapses to the normal case (0, 3)."""
    n = len(rets)
    if n < 2:
        return 0.0, 3.0
    m = sum(rets) / n
    var = sum((r - m) ** 2 for r in rets) / n  # population normalization (standard for PSR)
    if var <= 0:
        return 0.0, 3.0
    sd = math.sqrt(var)
    skew = sum(((r - m) / sd) ** 3 for r in rets) / n
    kurt = sum(((r - m) / sd) ** 4 for r in rets) / n
    return skew, kurt


def _equity(trades) -> List[Tuple[int, float]]:
    """Cumulative pnl curve ordered by exit time, for the drawdown stat and §D graphs."""
    cum = 0.0
    out: List[Tuple[int, float]] = []
    for t in sorted(trades, key=lambda x: x.exit_ts):
        cum += t.pnl
        out.append((int(t.exit_ts), round(cum, 4)))
    return out


def _placebo_pvalue(trades, seed: int) -> float:
    """Market-implied-null negative control for a binary. The null "this rule has no edge over
    the price it paid" says each settled contract wins with probability equal to its entry price
    (a calibrated market: buying at p is worth exactly p). So redraw every settled trade's outcome
    as Bernoulli(entry_price) `PLACEBO_SHUFFLES` times and count how often the simulated gross
    payoff sum(win/entry) is >= the observed one. A genuine edge (winning more often than the
    price implies, at ANY price level) makes the observed payoff extreme -> small p; a rule that
    merely pays the price -> p ~ uniform.

    This replaces a winner-subset label shuffle that only rewarded edges concentrated in CHEAP
    contracts: under that test, a uniform real edge (true prob = price + e) skews winners toward
    the dear contracts and scored p ~ 1, so the gate REJECTED essentially every non-longshot edge.

    Gross, not net: fees are the bootstrap test's job; this asks only "is there signal beyond the
    price?". Outcomes are drawn independently, which ignores same-event correlation across strikes
    (the autocorrelation-robust bootstrap remains the primary test). Early exits carry no
    settlement draw and are left out. <2 settled trades -> 1.0 (no discrimination possible)."""
    prices: List[float] = []
    won: List[bool] = []
    for t in sorted(trades, key=lambda x: x.entry_ts):
        if t.reason != "settled" or not 0.0 < t.entry_price < 1.0:
            continue
        prices.append(float(t.entry_price))
        won.append(t.exit_price >= 0.5)  # settled winners carry exit_price 1.0
    if len(prices) < 2:
        return 1.0
    observed = sum(1.0 / p for p, w in zip(prices, won) if w)
    rng = random.Random(seed)
    ge = 0
    for _ in range(PLACEBO_SHUFFLES):
        sim = sum(1.0 / p for p in prices if rng.random() < p)
        if sim >= observed - 1e-12:
            ge += 1
    return ge / PLACEBO_SHUFFLES


def _spot_placebo_pvalue(trades, seed: int) -> float:
    """Negative control for a continuous-price (spot) strategy. A spot trade has no $0/$1
    settlement and no 1/entry win value, so the binary label-shuffle is meaningless. The null
    here is instead "the per-trade returns are symmetric noise around zero": random sign-flip of
    the net-return series (TAO_VENUE_DESIGN.md §A.6). We flip each trade's return sign with prob
    1/2 `PLACEBO_SHUFFLES` times and count how often the resampled mean >= the observed mean.

    A genuine positive edge makes the observed mean extreme among sign-flips -> small p. A null
    (returns centered on zero) -> p ~ 0.5. Degenerate (<2 trades) -> 1.0 (no discrimination)."""
    rets = [r for _, r in _net_returns(trades)]
    n = len(rets)
    if n < 2:
        return 1.0
    observed = sum(rets) / n
    rng = random.Random(seed)
    ge = 0
    for _ in range(PLACEBO_SHUFFLES):
        s = sum(r if rng.random() < 0.5 else -r for r in rets)
        if s / n >= observed - 1e-12:
            ge += 1
    return ge / PLACEBO_SHUFFLES


# -- numeric verdict (no I/O) --------------------------------------------------


def _primary_p(boot: Dict[str, Any]) -> float:
    """The PRIMARY one-sided validation p-value: H0 mean net return <= 0, z = mean / bootstrap SE,
    p = 1 - Phi(z). The SE comes from the stationary bootstrap, so it is autocorrelation-robust.

    Why not the raw bootstrap mass at/below zero: it moves in steps of 1/n_boot (5e-4 at 2,000
    resamples), while the LORD++ level falls below 5e-4 by the third test in a stream and below
    5e-5 after ~50. A step p-value then cannot reject at all unless every resample is positive, so
    a real edge stops being judgeable. The normal tail is continuous and agrees with the empirical
    mass where both are resolvable. Degenerate SE (constant or tiny series) -> the empirical mass."""
    point, se = boot.get("point"), boot.get("se")
    if point is None or se is None or not math.isfinite(point) or not math.isfinite(se) or se <= 0:
        return boot["p_value"]
    return 1.0 - stats._norm_cdf(point / se)




def _compute(trades, n_trials: int, lord_state: Dict[str, Any], seed: int,
             kind: str = "binary") -> Dict[str, Any]:
    """The full numeric verdict for one finalist's trade list, advancing a LORD++ state by
    one test. Pure w.r.t. the DB (callers persist). Returns every number plus the new LORD++
    state; classification is applied separately so judge_batch can fold in BH."""
    series = _net_returns(trades)
    rets = [r for _, r in series]
    n = len(rets)
    boot = stats.stationary_bootstrap_ci(rets, stat="mean", alpha=ALPHA, seed=seed)
    p_value = _primary_p(boot)
    sr = _sharpe(rets)
    skew, kurt = _moments(rets)
    psr = stats.probabilistic_sharpe_ratio(sr, n, skew, kurt)
    var_trials = 1.0 / (n - 1) if n > 1 else 0.0  # Var(SR_hat) under the null = dispersion of equal-length zero-edge trials
    dsr = stats.deflated_sharpe_ratio(sr, n, skew, kurt, n_trials, var_trials)
    # The placebo is the one instrument-specific stat: binary uses the 1/entry label shuffle,
    # spot a sign-flip of the return series. Everything else (CI, PSR/DSR, LORD++, cross-day) is
    # identical. One-line dispatch on market kind, exactly as the design prescribes (§A.6).
    placebo_p = _spot_placebo_pvalue(trades, seed) if kind in ("spot", "perpetual") else _placebo_pvalue(trades, seed)
    rec = stats.lord_record(lord_state, p_value)
    rec["state"]["epoch_to_ts"] = lord_state.get("epoch_to_ts")  # the epoch rides along with the stream
    equity = _equity(trades)
    cross_day_ok, folds, day_share = _cross_day(trades)
    return {
        "n_trades": n,
        "cross_day_ok": cross_day_ok,
        "folds": folds,
        "cross_day_max_day_share": day_share,
        "p_value": p_value,
        "p_value_empirical": boot["p_value"],
        "ci_lo": boot["lo"],
        "ci_hi": boot["hi"],
        "mean_net_return": boot["point"],
        "sharpe": sr,
        "psr": psr,
        "dsr": dsr,
        "placebo_p": placebo_p,
        "placebo_passed": placebo_p < ALPHA,
        "lord_reject": rec["reject"],
        "alpha_i": rec["alpha_i"],
        "lord_state": rec["state"],
        "net_pnl": sum(t.pnl for t in trades),
        "max_drawdown": quant.max_drawdown([v for _, v in equity]),
        "ret_series": [[ts, round(r, 8)] for ts, r in series],
        "bh_reject": None,
    }


def _classify(lord_reject: bool, bh_reject: Optional[bool], dsr: float,
              ci_lo: float, ci_hi: float, placebo_passed: bool,
              cross_day_ok: bool = True) -> Classification:
    """The STAT_SUPPORTED decision rule. STAT_SUPPORTED iff the online FDR budget rejects AND
    (within a chunk) BH rejects AND DSR >= DSR_MIN AND the bootstrap CI lower bound is above 0
    AND the negative control passes AND the edge generalizes across days/folds (cross_day_ok).
    A placebo-equivalent or flatly-negative result is REJECTED; anything real-looking but short
    of the bar - including a one-window edge that fails cross-day - is INCONCLUSIVE (the honest,
    valuable outcome)."""
    bh_ok = True if bh_reject is None else bh_reject
    if lord_reject and bh_ok and dsr >= DSR_MIN and ci_lo > 0 and placebo_passed and cross_day_ok:
        return Classification.STAT_SUPPORTED
    if not placebo_passed:
        return Classification.REJECTED          # edge indistinguishable from a label shuffle -> artifact
    if ci_hi is not None and ci_hi <= 0:
        return Classification.REJECTED          # whole CI at/below zero -> actively no edge
    return Classification.INCONCLUSIVE


def _n_trials(cur, user_id: int, market: str, including: int,
              window_from_ts: Optional[int] = None) -> int:
    """Audited number of hypotheses that competed for this validation evidence, plus the
    `including` being judged right now. Feeds DSR's selection correction (§B.1/§F).

    With `window_from_ts` (validation judging) only experiments whose validation window OVERLAPS
    the current one count: a hypothesis judged on an older window that has fully rolled out of
    validation never saw this evidence, so it cannot have been selected on it. Read straight off
    the immutable ledger (experiment -> its frozen partition), so it is reconstructable by audit.
    Without it (holdout) the all-time count is used, as before.

    `including` is a DEGREES-OF-FREEDOM count, not a bare hypothesis count: a learned model that
    fits k coefficients from data counts as k implicit trials (specmod.n_free_params), a hand-
    specified gbm/code spec as 1. This only ever RAISES the trial count, so a richer model faces a
    strictly HIGHER deflated-Sharpe bar - fitting more parameters can never make the gate easier."""
    if window_from_ts is None:
        prior = len(rr.experiment_records_for_replay(cur, user_id, market))
    else:
        prior = rr.validated_trials_overlapping(cur, user_id, market, int(window_from_ts))
    return prior + max(including, 0)


def _judged_trials(finalists: List[dict]) -> int:
    """Degrees of freedom the finalists being judged NOW contribute to the trial count: the sum of
    each spec's fitted-parameter count (>=1 each)."""
    return sum(specmod.n_free_params(f.get("spec") or {}) for f in finalists)


def _lord_state(cur, user_id: int, market: str, window_from_ts: int, window_to_ts: int) -> Dict[str, Any]:
    """Load the LORD++ alpha-wealth state for this (user, market) stream, or a fresh one.

    EVIDENCE EPOCHS. A stream is tied to the validation evidence it spends on. It carries
    `epoch_to_ts`, the end of the validation window of the stream's first test. Partitions slide
    forward as contracts settle, and once the current validation window starts at/after
    `epoch_to_ts` every test in the old stream was run on data this window does not contain: the
    new window is fresh, disjoint evidence, so a fresh LORD++ stream (full w0) starts on it. While
    windows still overlap, the stream continues and keeps decaying, so re-freezing a partition can
    never be used to refill the budget on the same data. A legacy stream (no epoch recorded) is
    continued and stamped with the current window's end, so it too ends only once that data has
    fully rolled out of validation.

    Returns a plain dict with exactly the keys stats.lord_record expects, plus `epoch_to_ts`."""
    st = rr.get_fdr_state(cur, user_id, market)
    epoch_to = st.get("epoch_to_ts") if st else None
    if st is None or (epoch_to is not None and int(window_from_ts) >= int(epoch_to)):
        fresh = stats.lord_init(ALPHA)
        fresh["epoch_to_ts"] = int(window_to_ts)
        return fresh
    return {
        "method": st.get("method", "LORD++"),
        "alpha": float(st["alpha"]),
        "w0": float(st["w0"]),
        "wealth": float(st["wealth"]),
        "t": int(st["t"]),
        "rejections": list(st.get("rejections") or []),
        "epoch_to_ts": int(epoch_to) if epoch_to is not None else int(window_to_ts),
    }


def _result_metrics(v: Dict[str, Any], n_trials: int, holdout_consumed: int = 0) -> Dict[str, Any]:
    """Map a computed verdict to the append_result column dict."""
    return {
        "net_pnl": round(v["net_pnl"], 4),
        "mean_net_return": v["mean_net_return"],
        "sharpe": v["sharpe"],
        "psr": v["psr"],
        "dsr": v["dsr"],
        "p_value": v["p_value"],
        "ci_lo": v["ci_lo"],
        "ci_hi": v["ci_hi"],
        "fdr_alpha_i": v["alpha_i"],
        "fdr_reject": v["lord_reject"],
        "bh_reject": v.get("bh_reject"),
        "placebo_p": v["placebo_p"],
        "n_trials_audited": n_trials,
        "holdout_consumed": holdout_consumed,
    }


def _verdict_dict(v: Dict[str, Any], cls: Classification, n_trials: int) -> Dict[str, Any]:
    """The FULL numeric verdict returned to the gatekeeper's caller. NOTE: the generator
    (agent.py) must receive ONLY `classification` out of this — never the p-value/CI/pnl."""
    return {
        "classification": cls.value,
        "n_trades": v["n_trades"],
        "alpha_spent": True,
        "p_value": v["p_value"],
        "alpha_i": v["alpha_i"],
        "fdr_reject": v["lord_reject"],
        "bh_reject": v.get("bh_reject"),
        "psr": v["psr"],
        "dsr": v["dsr"],
        "ci": {"lo": v["ci_lo"], "hi": v["ci_hi"]},
        "mean_net_return": v["mean_net_return"],
        "placebo_p": v["placebo_p"],
        "max_drawdown": v["max_drawdown"],
        "n_trials_audited": n_trials,
        "cross_day_ok": v.get("cross_day_ok"),
        "cross_day_max_day_share": v.get("cross_day_max_day_share"),
        "folds": v.get("folds", []),
    }


# -- validation (§B.2 steps) ---------------------------------------------------


def _assert_perpetual_source(cur, experiment_id: int, dataset) -> None:
    if getattr(dataset.market, "kind", "binary") != "perpetual":
        return
    from app import kalshi_perps_repository as perps
    experiment = rr.experiment_row_by_id(cur, experiment_id)
    if not experiment or int(experiment["research_partition_id"]) != getattr(dataset, "partition_id", None):
        raise ValueError("Perpetual evaluation must use the experiment's frozen partition.")
    source = perps.partition_source(cur, int(experiment["research_partition_id"]))
    if not source or source["source_version"] != getattr(dataset, "source_version", None):
        raise ValueError("Perpetual evaluation data differ from the frozen source version.")


def judge_validation(cur, experiment_id: int, finalist: dict, val_ds) -> dict:
    """Score ONE pre-registered finalist on the VALIDATION partition and record the verdict.

    Steps (§B.2): simulate the frozen spec on the (leak-free, self-contained) validation
    window; if n_trades < min_sample -> INCONCLUSIVE and DO NOT spend alpha; else per-trade
    net returns -> stationary-bootstrap p-value + CI, PSR, DSR (n_trials = audited ledger
    count), advance the LORD++ stream, run the label-shuffle negative control, and classify.
    Appends one phase='validation' row. Returns the full numeric verdict dict; the generator
    must consume ONLY `classification`.

    `finalist` carries at least {spec, user_id, min_sample}; market comes from val_ds."""
    _assert_perpetual_source(cur, experiment_id, val_ds)
    market = val_ds.market.key
    user_id = int(finalist["user_id"])
    min_sample = int(finalist.get("min_sample", 0))
    n_trials = _n_trials(cur, user_id, market, including=_judged_trials([finalist]),
                         window_from_ts=val_ds.start_ts)

    trades = backtest.simulate(finalist["spec"], val_ds, val_ds.start_ts, val_ds.end_ts + 1)
    n_trades = len(trades)
    if n_trades < min_sample:
        cls = Classification.INCONCLUSIVE
        rr.append_result(cur, experiment_id, "validation", cls.value, n_trades,
                         metrics={"n_trials_audited": n_trials})
        return {"classification": cls.value, "n_trades": n_trades, "alpha_spent": False,
                "n_trials_audited": n_trials}

    v = _compute(trades, n_trials, _lord_state(cur, user_id, market, val_ds.start_ts, val_ds.end_ts),
                 seed=_BOOT_SEED + int(experiment_id),
                 kind=getattr(val_ds.market, "kind", "binary"))
    rr.set_fdr_state(cur, user_id, market, v["lord_state"])  # alpha spent only once sample is adequate
    cls = _classify(v["lord_reject"], None, v["dsr"], v["ci_lo"], v["ci_hi"], v["placebo_passed"],
                    v["cross_day_ok"])
    rr.append_result(cur, experiment_id, "validation", cls.value, n_trades,
                     metrics=_result_metrics(v, n_trials), equity_curve=v["ret_series"], folds=v["folds"])
    return _verdict_dict(v, cls, n_trials)


def judge_batch(cur, run_id: int, experiment_ids: List[int], finalists: List[dict],
                val_ds) -> List[dict]:
    """Chunk-level entry point. Applies Benjamini-Hochberg across the chunk's p-values IN
    ADDITION to the online LORD++ stream: a finalist is STAT_SUPPORTED only if it clears BOTH.
    Each finalist advances the shared LORD++ state in order; the final state is persisted once.
    Below-min-sample finalists are INCONCLUSIVE and spend no alpha and take no BH slot."""
    if not finalists:
        return []
    market = val_ds.market.key
    user_id = int(finalists[0]["user_id"])
    n_trials = _n_trials(cur, user_id, market, including=_judged_trials(finalists),
                         window_from_ts=val_ds.start_ts)
    lord_state = _lord_state(cur, user_id, market, val_ds.start_ts, val_ds.end_ts)

    computed: List[Dict[str, Any]] = []
    for exp_id, fin in zip(experiment_ids, finalists):
        _assert_perpetual_source(cur, exp_id, val_ds)
        trades = backtest.simulate(fin["spec"], val_ds, val_ds.start_ts, val_ds.end_ts + 1)
        n = len(trades)
        if n < int(fin.get("min_sample", 0)):
            computed.append({"exp_id": exp_id, "n_trades": n, "insufficient": True})
            continue
        v = _compute(trades, n_trials, lord_state, seed=_BOOT_SEED + int(exp_id), kind=getattr(val_ds.market, "kind", "binary"))
        lord_state = v["lord_state"]  # advance the stream
        v["exp_id"] = exp_id
        v["insufficient"] = False
        computed.append(v)

    tested = [c for c in computed if not c["insufficient"]]
    bh = stats.benjamini_hochberg([c["p_value"] for c in tested], alpha=ALPHA)
    for c, rej in zip(tested, bh["reject"]):
        c["bh_reject"] = bool(rej)
    if tested:
        rr.set_fdr_state(cur, user_id, market, lord_state)

    out: List[dict] = []
    for c in computed:
        if c["insufficient"]:
            cls = Classification.INCONCLUSIVE
            rr.append_result(cur, c["exp_id"], "validation", cls.value, c["n_trades"],
                             metrics={"n_trials_audited": n_trials})
            out.append({"classification": cls.value, "n_trades": c["n_trades"],
                        "alpha_spent": False, "n_trials_audited": n_trials})
            continue
        cls = _classify(c["lord_reject"], c["bh_reject"], c["dsr"], c["ci_lo"], c["ci_hi"],
                        c["placebo_passed"], c["cross_day_ok"])
        rr.append_result(cur, c["exp_id"], "validation", cls.value, c["n_trades"],
                         metrics=_result_metrics(c, n_trials), equity_curve=c["ret_series"],
                         folds=c["folds"])
        out.append(_verdict_dict(c, cls, n_trials))
    return out


# -- validation-budget pre-screen (research data only) -----------------------


def validation_power(cur, user_id: int, market: str, spec: dict, research_ds, partition: Dict[str, Any],
                     min_sample: int = 0) -> Dict[str, Any]:
    """Is this finalist worth a validation test? Reads ONLY the Research partition (which the
    generator may inspect freely) plus the partition's frozen validation boundaries and the
    stream's next alpha level, so it leaks no held-out number.

    Projection: the research-fold mean net return mu and its stationary-bootstrap SE over n fold
    trades; the validation window is expected to hold n_val = n * validation_days / fold_days
    trades, so its SE is se * sqrt(n / n_val). Power = Phi(mu / se_val - z_req), z_req the normal
    quantile of the next LORD++ alpha. The research estimate is optimistic (it is also what the
    finalist was selected on), so this only screens out the hopeless; it never grants anything.

    Returns {"ok", "power", "mu", "n_research", "n_val_expected", "alpha_next", "reason"}."""
    if partition.get("validation_from_ts") is None or partition.get("validation_to_ts") is None:
        # No frozen validation window to project onto: nothing to screen, let validation judge.
        return {"ok": True, "power": None, "mu": None, "n_research": None, "n_val_expected": None,
                "alpha_next": None, "reason": "no validation window to project onto"}
    rows = _per_trade(backtest.research_fold_trades(spec, research_ds, int(partition.get("embargo_seconds") or 0)))
    out: Dict[str, Any] = {"ok": False, "power": 0.0, "mu": None, "n_research": len(rows),
                           "n_val_expected": 0.0, "alpha_next": None, "reason": ""}
    if len(rows) < POWER_MIN_RESEARCH_TRADES:
        out["reason"] = ("only %d research-fold trades (need %d) to project validation power"
                         % (len(rows), POWER_MIN_RESEARCH_TRADES))
        return out
    rets = [r for _e, _x, r in rows]
    boot = stats.stationary_bootstrap_ci(rets, stat="mean", n_boot=500, alpha=ALPHA, seed=_BOOT_SEED)
    mu, se = float(boot["point"]), float(boot.get("se") or 0.0)
    out["mu"] = mu
    if mu <= 0:
        out["reason"] = "research-fold mean net return %.4f is not positive" % mu
        return out
    fold_days = max((rows[-1][1] - rows[0][0]) / 86400.0, 1.0 / 24)
    val_from, val_to = int(partition["validation_from_ts"]), int(partition["validation_to_ts"])
    n_val = len(rows) * max(val_to - val_from, 0) / 86400.0 / fold_days
    out["n_val_expected"] = round(n_val, 1)
    if n_val < max(int(min_sample), 2):
        out["reason"] = ("validation window is expected to hold ~%.0f trades, below the pre-registered "
                         "min_sample %d" % (n_val, min_sample))
        return out
    alpha_next = stats.lord_alpha(_lord_state(cur, user_id, market, val_from, val_to))
    out["alpha_next"] = alpha_next
    if se <= 0 or not math.isfinite(se):
        power = 1.0  # a zero-variance positive edge: nothing to project, let validation judge it
    else:
        z_proj = mu / (se * math.sqrt(len(rows) / n_val))
        power = stats._norm_cdf(z_proj - stats.norm_ppf(1.0 - alpha_next))
    out["power"] = round(power, 4)
    out["ok"] = power >= POWER_MIN
    if not out["ok"]:
        out["reason"] = ("projected validation power %.0f%% < %.0f%%: a research-fold edge of %.2f%%/trade "
                         "over ~%.0f validation trades is unlikely to clear the next alpha %.1e"
                         % (100 * power, 100 * POWER_MIN, 100 * mu, n_val, alpha_next))
    return out


# -- locked holdout (one-time) -------------------------------------------------


def _holdout_fingerprint(partition: Dict[str, Any]) -> str:
    base = "%s|%s|%s" % (partition["holdout_from_ts"], partition["holdout_to_ts"],
                         partition.get("data_fingerprint", ""))
    return hashlib.sha256(base.encode()).hexdigest()


def _latest_classification(cur, experiment_id: int, phase: str) -> Optional[str]:
    rows = rr.results_for_experiment(cur, experiment_id, phase)
    return rows[-1]["classification"] if rows else None


def judge_holdout(cur, experiment_id: int, finalist: dict,
                  run_load: Optional[Callable[[Callable], Any]] = None) -> dict:
    """ONE-TIME evaluation on the Locked-Holdout. Refuses (raises HoldoutConsumed) unless the
    experiment is already STAT_SUPPORTED, the holdout for this market is not consumed and has
    evaluations left, and this experiment has no prior phase='holdout' result. On success:
    simulate the frozen spec on the holdout, record a phase='holdout' verdict, spend one
    holdout evaluation, and set FORWARD_VALIDATED (edge holds on untouched data) or REJECTED.
    At the evaluation cap the holdout ledger flips consumed=1 and we emit the roll-to-fresh-
    data alert (§F).

    A cross-contract finalist is judged on the MERGED holdout of its legs (each clipped to its own
    frozen window): its market/FDR stream and holdout ledger are keyed by the shared stream key
    (involved markets joined), and the merged partition is frozen the same way validation freezes
    it. Single-market flow is unchanged.

    `run_load` (optional) runs the holdout dataset load: the caller passes a wrapper that bounds it
    with a timeout + heartbeat (so a slow RDS fails fast instead of tripping the watchdog). It only
    affects HOW the load is driven — never which rows are read or any statistic — and defaults to
    running the loader inline (unchanged behaviour)."""
    run_load = run_load or (lambda fn: fn())
    spec = finalist.get("spec") or {}
    cross = specmod.is_cross_contract(spec)
    markets = specmod.involved_markets(spec) if cross else None
    market = specmod.stream_key(spec) if cross else finalist["market"]
    user_id = int(finalist["user_id"])

    if _latest_classification(cur, experiment_id, "validation") != Classification.STAT_SUPPORTED.value:
        raise HoldoutConsumed("experiment is not statistically_supported; holdout refused")
    if rr.results_for_experiment(cur, experiment_id, "holdout"):
        raise HoldoutConsumed("experiment already has a holdout verdict; holdout is one-time")

    if cross:
        partition = partitions.ensure_merged_partition(cur, markets)
        max_evals = min(partitions.holdout_max_evaluations(m) for m in markets)
    elif specmod.is_perpetual_spec(spec):
        experiment = rr.experiment_row_by_id(cur, experiment_id)
        partition = rr.partition_by_id(cur, int(experiment["research_partition_id"])) if experiment else None
        max_evals = partitions.holdout_max_evaluations(market)
    else:
        partition = rr.get_active_partition(cur, market)
        max_evals = partitions.holdout_max_evaluations(market)
    if not partition:
        raise HoldoutConsumed("no active partition for market %r" % market)
    ledger = rr.ensure_holdout_ledger(cur, market, int(partition["id"]),
                                      _holdout_fingerprint(partition), max_evals)
    if int(ledger["consumed"]) == 1 or int(ledger["evaluations_used"]) >= int(ledger["max_evaluations"]):
        raise HoldoutConsumed("holdout consumed for market %r (%s/%s)" % (
            market, ledger["evaluations_used"], ledger["max_evaluations"]))
    # Partitions re-freeze whenever new contracts settle, and each frozen window gets its own
    # ledger row, so the per-row cap alone could be sidestepped by churn: ten looks, one new
    # settlement, ten more on almost the same data. Count every look whose holdout window still
    # overlaps this one against the cap.
    overlapping = rr.holdout_evaluations_overlapping(cur, market, int(partition["holdout_from_ts"]))
    if overlapping >= int(max_evals):
        raise HoldoutConsumed("holdout data for market %r already viewed %s times across re-frozen "
                              "windows (cap %s); wait for fresh settled history" % (
                                  market, overlapping, max_evals))

    # Resolve the partition(s) on THIS thread (cursor work), then build the dataset off-cursor via
    # run_load so the optional timeout worker never shares the run cursor.
    if cross:
        legs = partitions.merged_partitions(cur, markets)
        hds = run_load(lambda: partitions.merged_dataset_from(legs, "holdout"))
    else:
        hds = run_load(lambda: partitions.holdout_dataset(market, partition))
    _assert_perpetual_source(cur, experiment_id, hds)
    trades = backtest.simulate(finalist["spec"], hds, hds.start_ts, hds.end_ts + 1)
    n_trades = len(trades)
    n_trials = _n_trials(cur, user_id, market, including=_judged_trials([finalist]))
    v = _compute(trades, n_trials, stats.lord_init(ALPHA), seed=_BOOT_SEED + int(experiment_id),
                 kind=getattr(hds.market, "kind", "binary"))

    use = rr.record_holdout_use(cur, int(ledger["id"]))  # authoritative one-way spend
    if not use.get("ok"):
        raise HoldoutConsumed(use.get("reason", "holdout_consumed"))
    consumed = int(use.get("consumed", 0))

    forward = v["ci_lo"] > 0 and v["p_value"] <= ALPHA
    cls = Classification.FORWARD_VALIDATED if forward else Classification.REJECTED
    if specmod.is_perpetual_spec(spec) and n_trades < int(finalist.get("min_sample", 0)):
        # The held-out evidence was viewed, so its one-way use is still spent.
        cls = Classification.INCONCLUSIVE
    rr.append_result(cur, experiment_id, "holdout", cls.value, n_trades,
                     metrics=_result_metrics(v, n_trials, holdout_consumed=consumed),
                     equity_curve=v["ret_series"], folds=v["folds"])
    if consumed:
        _alert("holdout for market %r is consumed (%s evaluations) — roll partitions forward "
               "onto fresh settled history before any further holdout look (§F)." % (
                   market, use.get("evaluations_used")))
    verdict = _verdict_dict(v, cls, n_trials)
    verdict["holdout_consumed"] = consumed
    return verdict


# -- marginal contribution (pre-deploy diversification gate) -------------------


def _latest_validation_series(cur, experiment_id: int) -> Optional[List[List[float]]]:
    rows = rr.results_for_experiment(cur, experiment_id, "validation")
    return rows[-1].get("equity_curve") if rows else None


def _bucketed(series: List[List[float]]) -> Dict[int, float]:
    """Sum per-trade returns into daily buckets (entry_ts // 86400). ponytail: a day bucket is
    the coarse common index two strategies trading different contracts can be aligned on; a
    finer co-return would need matched decision frames."""
    out: Dict[int, float] = {}
    for ts, r in series:
        day = int(ts) // 86400
        out[day] = out.get(day, 0.0) + float(r)
    return out


def _daily_corr(a: List[List[float]], b: List[List[float]]) -> float:
    da, db = _bucketed(a), _bucketed(b)
    days = sorted(set(da) | set(db))
    xs = [da.get(d, 0.0) for d in days]
    ys = [db.get(d, 0.0) for d in days]
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx <= 0 or sy <= 0:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(sx * sy)


def marginal_contribution_ok(cur, user_id: int, experiment_id: int,
                             finalist: dict) -> Tuple[bool, str]:
    """Pre-deploy diversification gate: correlate this strategy's validation per-trade return
    series (daily-bucketed) against each already-DEPLOYED strategy's. '100 correlated BTC-
    momentum strategies < 1 novel one.' Fails (False, reason) if max |corr| > CORR_MAX. On a
    pass, promotes FORWARD_VALIDATED -> DEPLOYMENT_CANDIDATE (appends a phase='forward' row)."""
    if specmod.has_perpetual_market(finalist.get("spec") or {}, finalist.get("market")):
        return False, "Bitcoin perpetuals remain research-only; trading promotion is disabled."
    market = finalist["market"]
    if _latest_classification(cur, experiment_id, "holdout") != Classification.FORWARD_VALIDATED.value:
        return False, "experiment is not forward_validated; nothing to promote"
    mine = _latest_validation_series(cur, experiment_id)
    if not mine:
        return False, "no validation return series recorded for this experiment"

    worst = 0.0
    worst_peer: Optional[int] = None
    for rec in rr.experiment_records_for_replay(cur, user_id, market):
        eid = int(rec["experiment_id"])
        if eid == int(experiment_id):
            continue
        fwd = rr.results_for_experiment(cur, eid, "forward")
        if not fwd or fwd[-1]["classification"] != Classification.DEPLOYMENT_CANDIDATE.value:
            continue  # only already-deployed peers count
        peer = _latest_validation_series(cur, eid)
        if not peer:
            continue
        c = abs(_daily_corr(mine, peer))
        if c > worst:
            worst, worst_peer = c, eid

    if worst > CORR_MAX:
        return False, "max |corr| %.2f to deployed experiment %s exceeds %.2f" % (worst, worst_peer, CORR_MAX)
    rr.append_result(cur, experiment_id, "forward", Classification.DEPLOYMENT_CANDIDATE.value, len(mine))
    return True, "max |corr| %.2f within %.2f" % (worst, CORR_MAX)


def _alert(msg: str) -> None:
    log.warning("GATEKEEPER HOLDOUT ALERT: %s", msg)
