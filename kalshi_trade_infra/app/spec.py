"""The strategy language agents write in, and the one rule that executes it.

An agent never writes code. It writes a spec: a fair-value model with a few
parameters, entry conditions, exits and sizing. `validate` is the trust
boundary (the spec comes from an LLM), and `entries` / `exit_signal` are the
only decision logic - the backtester and the live engine both call them, so a
deployed strategy trades exactly the rule that passed its backtest.

Fair value is a drifted GBM digital:

    P(YES) = Phi( (ln(S/K) + mu*T) / (sigma*sqrt(T)) )
    sigma  = vol_scale * realised 1m vol over vol_window minutes
    mu     = drift_beta * (BTC return over drift_window minutes) / drift_window

drift_beta = 0 is the house `binary_theory` model; > 0 bets on momentum,
< 0 on mean reversion; vol_scale != 1 bets the market mis-prices volatility.
Filters on any FEATURES entry express regimes (time of day, vol, spread...).
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.markets import FEATURES, MARKETS, MICRO_FEATURES, Snapshot, compatible_cadence
from data_pipeline.kalshi_fees import taker_fee_per_contract_dollars

OPS = (">", ">=", "<", "<=")
MAX_FILTERS = 4

# Fair-value model families. "gbm" is the house drifted-GBM digital (below). "logistic" and
# "calibration" are LEARNED models whose parameters are FIT on the research fold and FROZEN into
# the spec (coef/intercept become part of the pre-registration hash), so the gatekeeper judges the
# exact frozen model on data it never saw - no re-fitting at validation, no leak. See fair_yes.
MODEL_KINDS = ("gbm", "logistic", "calibration")
MAX_MODEL_FEATURES = 6  # bounds a learned model's degrees of freedom (every coef is an implicit trial)
COEF_CAP = 1e7          # reject NaN/inf/absurd fitted coefficients (raw-feature scale spans ~1e-5..1e4)

# (min, max) for every numeric field; None-able fields are listed separately.
RANGES: Dict[str, Tuple[float, float]] = {
    "model.vol_scale": (0.3, 3.0),
    "model.drift_beta": (-3.0, 3.0),
    "entry.min_edge": (0.0, 0.5),
    "entry.min_price": (0.01, 0.99),
    "entry.max_price": (0.01, 0.99),
    "entry.min_tte_min": (0.0, 1500.0),
    "entry.max_tte_min": (1.0, 1500.0),
    "entry.max_spread": (0.01, 0.5),
    "exit.take_profit": (0.01, 0.99),
    "exit.stop_loss": (0.01, 0.99),
    "exit.min_edge_to_hold": (-0.5, 0.5),
    "sizing.stake": (1.0, 500.0),
    "sizing.max_positions": (1, 50),
}
CHOICES: Dict[str, Tuple] = {
    "side": ("yes", "no", "either"),
    "model.kind": MODEL_KINDS,
    "model.vol_window": (15, 60),
    "model.drift_window": (0, 5, 15, 60),
}
NULLABLE = {"exit.take_profit", "exit.stop_loss", "exit.min_edge_to_hold"}

DEFAULT_SPEC: Dict[str, Any] = {
    "market": "btc15m",
    "side": "either",
    # kind="gbm" -> the drifted-GBM digital below (vol_window/vol_scale/drift_window/drift_beta).
    # kind="logistic"/"calibration" -> a LEARNED model: `features` names its inputs, and `coef` +
    # `intercept` are FIT on research and frozen in (empty until fitted). The GBM params are then
    # ignored. See _validate_model and fair_yes.
    "model": {"vol_window": 60, "vol_scale": 1.0, "drift_window": 0, "drift_beta": 0.0,
              "kind": "gbm", "features": [], "coef": [], "intercept": 0.0},
    "entry": {
        "min_edge": 0.05,
        "min_price": 0.05,
        "max_price": 0.95,
        "min_tte_min": 1.0,
        "max_tte_min": 1500.0,
        "max_spread": 0.05,
        "filters": [],
    },
    "exit": {"take_profit": None, "stop_loss": None, "min_edge_to_hold": None},
    # Default book: $5 per trade, $100 of capital (20 positions x $5). The agent may
    # size differently (dynamic stake / fewer or more positions) when it has a reason;
    # absent that, every sim runs this standard $5/$100 book.
    "sizing": {"stake": 5.0, "max_positions": 20},
    # None = ordinary single-contract strategy (unchanged). An object turns the spec into a
    # relative-value PAIR: buy YES on the leg the model says is underpriced and NO on the leg it
    # says is overpriced, within a matched group, holding both legs to settlement. See CROSS.
    "cross": None,
}

CROSS_PAIRINGS = ("cross_sectional", "cross_strike", "calendar")
CROSS_RELATIONSHIPS = ("spread",)  # ponytail: ratio is a trivial variant; add it only when asked.
MAX_CROSS_LEGS = 3

SPEC_GUIDE = """A strategy spec is a JSON object:
{
  "market": "btc15m" | "btc_daily",
  "side": "yes" | "no" | "either",            // which leg it may buy
  "model": {                                   // the fair-value model; pick ONE kind
    "kind": "gbm" | "logistic" | "calibration",// default "gbm"
    // --- kind "gbm": drifted GBM digital (the house model) ---
    "vol_window": 15 | 60,                     // minutes of 1m returns for realised vol
    "vol_scale": 0.3..3.0,                     // 1.0 = trust realised vol
    "drift_window": 0 | 5 | 15 | 60,           // 0 = no drift
    "drift_beta": -3.0..3.0,                   // >0 momentum, <0 mean reversion
    // --- kind "logistic": a LEARNED model P(YES)=sigmoid(w.features) ---
    "features": [ <feature name>, ... ]        // 1..6 features it scores; the SYSTEM fits the
                                               // weights on the research fold and FREEZES them
                                               // (you do NOT write coef - leave it out). A real
                                               // learned classifier, not a hand-picked threshold.
    // --- kind "calibration": recalibrate the market's own mid (favorite-longshot) ---
    //   takes no features; the system fits a 1-parameter logit recalibration on research.
  },
  "entry": {
    "min_edge": 0..0.5,                        // fair prob minus price paid, in dollars
    "min_price": 0.01..0.99, "max_price": 0.01..0.99,   // price paid per contract
    "min_tte_min": 0..1500, "max_tte_min": 1..1500,     // minutes to settlement
    "max_spread": 0.01..0.5,
    "filters": [ {"feature": <name>, "op": ">"|">="|"<"|"<=", "value": <number>} ]  // up to 4, all must hold
  },
  "exit": {                                    // all null = hold to settlement
    "take_profit": null | 0.01..0.99,          // sell when price gained this much
    "stop_loss": null | 0.01..0.99,            // sell when price lost this much
    "min_edge_to_hold": null | -0.5..0.5       // sell when fair - sell price falls below this
  },
  "sizing": {"stake": 1..500, "max_positions": 1..50},  // $/trade & concurrent positions; DEFAULT $5 x 20 = $100 book. Only change for a real sizing reason.
  "cross": null | {                             // OPTIONAL relative-value pair (default null = single-contract)
    "pairing": "cross_sectional"|"cross_strike"|"calendar",  // how the two legs are matched
    "legs": [ {"market": <key>} ],              // up to 3 EXTRA markets; cross_sectional needs >=1 on a different market
    "relationship": "spread"                    // trade the spread of model edges (buy YES cheap leg, NO dear leg)
  }
}
cross.pairing: cross_sectional = two different markets (e.g. BTC vs ETH, matched per frame) - the
two markets MUST share a decision cadence (same candle_minutes AND close schedule: two 15-min
crypto markets, or two daily markets; never a 1-min market with a daily one);
cross_strike = same market+settlement, different strikes; calendar = same market+strike, different settlements.
Features for filters: """ + "; ".join("%s = %s" % kv for kv in FEATURES.items()) + """
Order-book / microstructure features (""" + ", ".join(MICRO_FEATURES) + """) come from the
collected 1-minute book; they may be NULL on some frames (and on markets without a feed), and a
filter on a missing feature simply does not match - condition on them when the mechanism needs the
book, not by default.
LEARNED MODELS (kind logistic/calibration): the system fits the coefficients ONCE on the research
fold and freezes them into the pre-registered spec, then the gatekeeper scores that frozen model on
data it never saw - so you do NOT and CAN NOT tune the weights by hand, and there is no re-fitting
at validation. Every fitted coefficient is an implicit TRIAL: a logistic over k features raises the
deflated-Sharpe bar as if you ran k+1 strategies, so name only the few features your MECHANISM
predicts matter (e.g. order-flow features for a flow model). A learned model with no mechanism for
each feature is overfitting, and the higher bar will reject it."""


# -- arbitrary-quant code strategies ----------------------------------------
# A strategy may instead be agent-authored Python (any pure-Python/numpy quant method). It is
# ONE spec field, `code`, that defines a `signals(window)` function run in app.sandbox's
# OS-isolated child interpreter (no network/DB/credentials/filesystem). The rest of the spec is
# just `market` and `sizing`; the backtester applies the SAME fee/sizing/settlement, and the
# gatekeeper judges it identically to a DSL spec (pre-registration hashes the code as the rule).
CODE_SPEC_KEYS = {"market", "sizing", "code", "datasets"}
MAX_CODE_CHARS = 20_000
# Free external datasets a code spec may request (Pillar 3). Resolved + as-of joined on the host
# into frame["external"] within the research fold; see app/freedata.py. These are the sources that
# resolve with no key/entitlement; an unknown source is a spec error.
DATASET_SOURCES = ("fred",)
MAX_DATASETS = 8

CODE_STRATEGY_GUIDE = """
As an ALTERNATIVE to the fields above, a strategy may be arbitrary Python you write. Send:
{
  "market": "btc15m" | ...,
  "sizing": {"stake": 1..500, "max_positions": 1..50},
  "code": "<python source>"      // instead of model/entry/exit/side/filters
}
Your code defines ONE function:
  def signals(window):
      # window = {"market": str, "frames": [ {"ts": int, "contracts": [
      #   {"ticker": str, "strike": float, "close_ts": int,
      #    "yes_bid": float, "yes_ask": float, "features": {<feature name>: float}} ]} ]}
      #   frames are ascending by ts; features are the same ones listed above.
      # Return a list PARALLEL to window["frames"]; element i is the book you want HELD at
      # frame i: a list of {"ticker": str, "side": "yes"|"no", "score": float (optional)}.
      # Open = a (ticker, side) you list that you do not already hold (score orders them when
      # more than max_positions compete). Exit = a held (ticker, side) you stop listing (sold at
      # the bid). Unlisted at settlement = held to settlement. You buy the ask / sell the bid and
      # pay Kalshi fees exactly like a DSL spec.
Allowed imports: math, cmath, statistics, random, itertools, functools, collections, heapq,
bisect, operator, decimal, fractions, array, pickle, base64, and the scientific stack numpy,
scipy, sklearn (scikit-learn), statsmodels, xgboost, lightgbm, arch - so you can write real
quant/ML/stat models, not just loops, and a full sklearn/xgboost FIT works end-to-end (these
libraries may pull in whatever standard-library helpers they need at runtime; an import of a
library that isn't installed fails closed). Extra model families are available too: regime-switching
via hmmlearn (HMM) and ruptures (change-point detection), sports/pairwise outcomes via choix
(Bradley-Terry), panel-data / IV / fixed-effects econometrics via linearmodels, auto-ARIMA via
pmdarima, and graphs / cross-market correlation structure via networkx. For Bayesian work, hand-roll
with scipy/numpy (no pymc/jax). NO
file/network/OS access, and no dunder access; the code runs sealed off from the DB and keys.
Heavier deep-learning libraries (torch/tensorflow) are not installed. Keep it deterministic
and pure over the window you are handed.

TRAINING A MODEL (ML) — fit once on research, freeze, then predict. If your edge needs a
LEARNED model (logistic/ridge, a random forest or gradient-boosted tree ensemble, an SVM/kernel,
a calibration map, engineered features), add a SECOND function:
  def fit(window):
      # same window shape as signals(). Train your model on THIS research window ONLY and
      # RETURN a JSON-serializable params object. A few numbers can go back directly
      # (coefficients/intercepts/thresholds); a whole fitted estimator that cannot round-trip as
      # numbers (random forest, GBM, ensemble, kernel) goes back pickled+base64'd into a string
      # (import pickle, base64 are permitted). Keep the serialized params under ~256 KB — so keep
      # a forest modest (n_estimators x max_depth small) or the freeze is rejected.
      return params
  def signals(window):
      params = window["params"]   # the FROZEN params fit() returned on the research window
      # rebuild your model from params and PREDICT. Do NOT re-fit here.
      ...
fit() runs exactly once, on the research fold; its output is frozen into your pre-registered
strategy and handed to signals() unchanged on every later (unseen) window. This is the only way
to use a trained model honestly: a model that fits inside signals() would re-fit on the held-out
data and its "edge" would be fake. There is NO storage that persists between fit() and signals()
other than the params you return — that is deliberate, so your model can never peek past the
research window. A pure-rule strategy omits fit() entirely (unchanged).
Example — a fitted RandomForest, frozen and reloaded (any sklearn/xgboost/lightgbm estimator
round-trips the same way; a few coefficients would skip the pickle and return numbers directly):
  import numpy as np, pickle, base64
  from sklearn.ensemble import RandomForestClassifier
  def fit(window):
      X, y = _rows(window)      # build (features, label) rows from the frames your mechanism uses
      model = RandomForestClassifier(n_estimators=60, max_depth=4, random_state=0).fit(X, y)
      return {"model": base64.b64encode(pickle.dumps(model)).decode()}
  def signals(window):
      model = pickle.loads(base64.b64decode(window["params"]["model"]))
      # ...model.predict_proba(features) per frame; emit picks where it beats the mid net of fees.
EVENT / NON-PRICE MARKETS (sports, weather, outcome-settled): the built-in `gbm` is a continuous-
price model and does NOT apply — `code` + fit() is the first-class tool, NOT a last resort. There
is no strike/spot; you have the contract's own price/book features and its result. A canonical
shape is a RECALIBRATION of the market's own mid (learn where the crowd is biased on the research
fold, then bet that correction out of sample):
  import numpy as np
  from sklearn.linear_model import LogisticRegression
  def fit(window):
      X, y = [], []
      for fr in window["frames"]:
          for c in fr["contracts"]:
              mid = (c["yes_bid"] + c["yes_ask"]) / 2.0            # the market's own probability
              X.append([mid, c["features"].get("tte_min", 0.0)])    # + any feature this market HAS
              y.append(1 if window.get("results", {}).get(c["ticker"]) == "yes" else 0)
      model = LogisticRegression().fit(np.array(X), np.array(y))    # P(YES) vs mid + regime
      return {"coef": model.coef_.tolist(), "intercept": model.intercept_.tolist()}
  def signals(window):
      w = np.array(window["params"]["coef"][0]); b = window["params"]["intercept"][0]
      # per frame: p = sigmoid(w·[mid, tte] + b); BUY yes where p - mid clears fees, no where mid - p does.
  # (Swap LogisticRegression for a Poisson/Bradley-Terry/RandomForest as the mechanism needs — same
  # fit→freeze→predict shape. A model is scored on data it never saw, so only real edge survives.)

FREE EXTERNAL DATA (optional) — if your edge needs an outside series (a macro series, a rate, a
correlated price), add a top-level "datasets" list to the spec:
  "datasets": [{"name": "dgs10", "source": "fred", "series": "DGS10", "lag_days": 1}]
Each series is fetched on the host from a FREE, keyless source (source "fred" = any FRED series
id) and AS-OF joined onto your frames: at a frame with time ts you see ONLY the latest value
known by then (observation date + lag_days), so no future value can leak into an earlier frame.
Read it in fit()/signals() as:  frame["external"]["dgs10"]  (a float; the key is ABSENT on
frames before the first value is known, so use frame.get("external", {}).get("dgs10")). A series
that cannot be resolved is simply skipped (its key never appears) — handle a missing value
gracefully. lag_days is the publication delay you assert; set it honestly (daily rates ~1, a
monthly macro release longer). The request is frozen into your pre-registered spec.
"""

# Every proposer that reads SPEC_GUIDE also learns it may write arbitrary quant code.
SPEC_GUIDE = SPEC_GUIDE + "\n" + CODE_STRATEGY_GUIDE


class SpecError(ValueError):
    pass


PERPETUAL_GUIDE = """Bitcoin Kalshi perpetual research uses a causal declarative rule:
{"market":"btc_perp","sizing":{"stake":100,"max_positions":1},
 "perpetual":{"signal":"momentum","lookback_minutes":60,"threshold":0.001,"side":"both"}}
signal is momentum, mean_reversion, or funding. Momentum follows the signed trailing price
return; mean_reversion takes its opposite. Funding shorts positive estimated funding and
buys negative estimated funding, only when a timestamped estimate was already observable.
threshold is an absolute fractional return/rate (0.001 = 0.1%), not dollars or percentage points.
side restricts the rule to both, long, or short. Lookback is 1..1440 completed minutes.
Stake is USD research capital; use enough for the verified native minimum contract size.
The host freezes 1x exposure, one position, maximum holding 1440 minutes, 12bps taker fees
per side and 5bps adverse slippage per fill. These are fixed research scenario assumptions,
not a verified account fee tier or executable fills; do not optimize costs or leverage.
Decisions use completed bars and execute at the next contiguous bar's open. Finalized funding
payments are charged as costs and cannot be used as earlier estimates. Missing data is unknown.
No YES/NO settlement, strike, GBM probability model, cross-market trades, arbitrary code or
learned models are available for this initial perpetuals research path. Live, demo and paper
deployment are disabled regardless of a successful statistical verdict. Propose mechanisms
and falsification tests within these rules; say when the available history cannot test an idea."""


def is_perpetual_spec(spec: Dict) -> bool:
    market = spec.get("market") if isinstance(spec, dict) else None
    return isinstance(market, str) and market in MARKETS and MARKETS[market].kind == "perpetual"


def has_perpetual_market(spec: Dict, market: Optional[str] = None) -> bool:
    names = [market, spec.get("market")]
    cross = spec.get("cross") or {}
    if isinstance(cross, dict):
        legs = cross.get("legs") or []
        if isinstance(legs, list):
            names.extend(leg.get("market") for leg in legs if isinstance(leg, dict))
    return any(isinstance(name, str) and name in MARKETS and MARKETS[name].kind == "perpetual"
               for name in names)


def research_guide(market: str) -> str:
    return PERPETUAL_GUIDE if market in MARKETS and MARKETS[market].kind == "perpetual" else SPEC_GUIDE


def _validate_perpetual_spec(raw: Dict) -> Dict[str, Any]:
    from app.kalshi_perps_backtest import normalize_assumptions

    extra = set(raw) - {"market", "sizing", "perpetual"}
    if extra:
        raise SpecError("Perpetual research does not support fields: %s" % ", ".join(sorted(extra)))
    sizing = raw.get("sizing", {})
    if not isinstance(sizing, dict) or set(sizing) - {"stake", "max_positions"}:
        raise SpecError("Perpetual sizing accepts stake and max_positions only.")
    stake, positions = sizing.get("stake", 100.0), sizing.get("max_positions", 1)
    if (isinstance(stake, bool) or not isinstance(stake, (int, float))
            or not math.isfinite(stake) or not 1 <= stake <= 500):
        raise SpecError("Perpetual stake must be a finite USD capital amount from 1 to 500.")
    if isinstance(positions, bool) or positions != 1:
        raise SpecError("Perpetual research permits exactly one position at 1x exposure.")
    try:
        assumptions = normalize_assumptions(raw.get("perpetual", {}))
    except ValueError as exc:
        raise SpecError(str(exc)) from None
    return {"market": raw["market"], "sizing": {"stake": float(stake), "max_positions": 1},
            "perpetual": assumptions}


def is_code_spec(spec: Dict) -> bool:
    return isinstance(spec, dict) and bool(spec.get("code"))


def _validate_code_spec(raw: Dict) -> Dict[str, Any]:
    """Validate an arbitrary-quant code strategy: market + sizing + a `signals(window)` body
    that passes the sandbox's static gate. Unknown top-level fields are errors (same strictness
    as the DSL path). The returned spec is minimal: {market, sizing, code}."""
    from app import sandbox  # local import: sandbox pulls in exploration/dataclasses
    errors: List[str] = []
    extra = set(raw) - CODE_SPEC_KEYS
    if extra:
        errors.append("unknown field(s) for a code strategy: %s" % ", ".join(sorted(extra)))

    market = raw.get("market", DEFAULT_SPEC["market"])
    if market not in MARKETS:
        errors.append("market must be one of %s" % ", ".join(MARKETS))

    sizing = copy.deepcopy(DEFAULT_SPEC["sizing"])
    raw_sizing = raw.get("sizing", {})
    if not isinstance(raw_sizing, dict):
        errors.append("sizing must be an object")
    else:
        for key, value in raw_sizing.items():
            if key not in sizing:
                errors.append("unknown field sizing.%s" % key)
            else:
                sizing[key] = value
    for key in ("stake", "max_positions"):
        lo, hi = RANGES["sizing.%s" % key]
        v = sizing[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            errors.append("sizing.%s must be a number" % key)
        elif not lo <= v <= hi:
            errors.append("sizing.%s=%s is outside %s..%s" % (key, v, lo, hi))
        else:
            sizing[key] = int(v) if key == "max_positions" else float(v)

    code = raw.get("code")
    try:
        sandbox.validate_strategy_code(code)
    except sandbox.StrategyCodeError as e:
        errors.append("code: %s" % e)

    datasets = _validate_datasets(raw.get("datasets"), errors)

    if errors:
        raise SpecError("; ".join(errors))
    out = {"market": market, "sizing": sizing, "code": code}
    if datasets:  # omit the key entirely when unused, so existing specs' hashes are unchanged
        out["datasets"] = datasets
    return out


def _validate_datasets(raw, errors: List[str]) -> List[Dict[str, Any]]:
    """Normalise spec['datasets'] (free external data requests) or append errors. Each becomes a
    canonical {name, source, series, lag_days} dict sorted by name, so the request hashes stably
    and pins the trial. Resolution/joining happens on the host (app/freedata.py), never here."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append("datasets must be a list")
        return []
    if len(raw) > MAX_DATASETS:
        errors.append("at most %d datasets" % MAX_DATASETS)
    out: List[Dict[str, Any]] = []
    seen = set()
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            errors.append("datasets[%d] must be an object" % i)
            continue
        extra = set(d) - {"name", "source", "series", "lag_days"}
        if extra:
            errors.append("datasets[%d] unknown field(s): %s" % (i, ", ".join(sorted(extra))))
        name, source, series = d.get("name"), d.get("source"), d.get("series")
        if not isinstance(name, str) or not name.replace("_", "").isalnum():
            errors.append("datasets[%d].name must be an alphanumeric/underscore string" % i)
            continue
        if name in seen:
            errors.append("datasets[%d].name %r is duplicated" % (i, name))
        seen.add(name)
        if source not in DATASET_SOURCES:
            errors.append("datasets[%d].source must be one of %s" % (i, ", ".join(DATASET_SOURCES)))
        if not isinstance(series, str) or not series.strip():
            errors.append("datasets[%d].series must be a non-empty string" % i)
        lag = d.get("lag_days", 1)
        if isinstance(lag, bool) or not isinstance(lag, int) or not 0 <= lag <= 3650:
            errors.append("datasets[%d].lag_days must be an int in 0..3650" % i)
            lag = 1
        out.append({"name": name, "source": source, "series": series, "lag_days": lag})
    out.sort(key=lambda x: x["name"])
    return out


def _get(spec: Dict, path: str):
    node = spec
    for part in path.split("."):
        node = node[part]
    return node


def _set(spec: Dict, path: str, value) -> None:
    parts = path.split(".")
    node = spec
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _merge_known(base: Dict, raw: Dict, prefix: str, errors: List[str]) -> None:
    for key, value in raw.items():
        path = prefix + key
        if key not in base:
            errors.append("unknown field %s" % path)
        elif isinstance(base[key], dict):
            if not isinstance(value, dict):
                errors.append("%s must be an object" % path)
            else:
                _merge_known(base[key], value, path + ".", errors)
        else:
            base[key] = value


def validate(raw: Any) -> Dict[str, Any]:
    """Return a complete, normalised spec or raise SpecError listing every problem.

    Missing fields take defaults; unknown fields, wrong types and out-of-range
    values are errors, never silently clamped - the agent should learn its
    spec was wrong, not have it quietly changed into a different strategy.
    """
    if not isinstance(raw, dict):
        raise SpecError("spec must be a JSON object")
    if is_perpetual_spec(raw):
        return _validate_perpetual_spec(raw)
    if "code" in raw:
        return _validate_code_spec(raw)
    spec = copy.deepcopy(DEFAULT_SPEC)
    errors: List[str] = []
    _merge_known(spec, raw, "", errors)

    if spec["market"] not in MARKETS:
        errors.append("market must be one of %s" % ", ".join(MARKETS))
    for path, choices in CHOICES.items():
        if _get(spec, path) not in choices:
            errors.append("%s must be one of %s" % (path, list(choices)))
    for path, (lo, hi) in RANGES.items():
        value = _get(spec, path)
        if value is None and path in NULLABLE:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append("%s must be a number" % path)
            continue
        if not lo <= value <= hi:
            errors.append("%s=%s is outside %s..%s" % (path, value, lo, hi))
            continue
        _set(spec, path, int(value) if path == "sizing.max_positions" else float(value))

    entry = spec["entry"]
    if not errors:
        if entry["min_price"] > entry["max_price"]:
            errors.append("entry.min_price must be <= entry.max_price")
        if entry["min_tte_min"] >= entry["max_tte_min"]:
            errors.append("entry.min_tte_min must be < entry.max_tte_min")
    filters = entry["filters"]
    if not isinstance(filters, list) or len(filters) > MAX_FILTERS:
        errors.append("entry.filters must be a list of at most %d filters" % MAX_FILTERS)
    else:
        clean = []
        for i, flt in enumerate(filters):
            if not isinstance(flt, dict) or set(flt) != {"feature", "op", "value"}:
                errors.append("entry.filters[%d] must have exactly feature, op, value" % i)
                continue
            if flt["feature"] not in FEATURES:
                errors.append("entry.filters[%d].feature %r is not a known feature" % (i, flt["feature"]))
            if flt["op"] not in OPS:
                errors.append("entry.filters[%d].op must be one of %s" % (i, list(OPS)))
            v = flt["value"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                errors.append("entry.filters[%d].value must be a number" % i)
            else:
                clean.append({"feature": flt["feature"], "op": flt["op"], "value": float(v)})
        entry["filters"] = clean
    _validate_model(spec, errors)
    _validate_cross(spec, errors)
    if errors:
        raise SpecError("; ".join(errors))
    return spec


def _num_ok(v) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and abs(v) <= COEF_CAP


def _validate_model(spec: Dict, errors: List[str]) -> None:
    """Validate the fair-value model's kind-specific fields, normalising in place. gbm takes no
    learned fields; logistic names 1..MAX_MODEL_FEATURES known features; calibration is a 1-param
    recalibration of the market mid. `coef` may be empty (NOT yet fit — the research pipeline fills
    it before pre-registration) or exactly as long as the feature vector (FROZEN, fit on research).
    Mirrors validate()'s strictness: unknown features, wrong lengths and non-finite numbers are
    errors, never clamped - a fitted model that silently changed shape is a different hypothesis."""
    m = spec["model"]
    kind = m.get("kind", "gbm")
    if kind not in MODEL_KINDS:
        return  # the CHOICES loop already recorded the bad kind; nothing more to check
    feats = m.get("features", [])
    coef = m.get("coef", [])
    intercept = m.get("intercept", 0.0)
    if not isinstance(feats, list) or not isinstance(coef, list):
        errors.append("model.features and model.coef must be lists")
        return

    if kind == "gbm":
        if feats or coef:
            errors.append("model.features/coef only apply to kind logistic or calibration")
        m["features"], m["coef"], m["intercept"] = [], [], 0.0
        return

    if kind == "calibration":
        # A favorite-longshot recalibration of the market's own implied probability: one engineered
        # input (the logit of the mid). The proposer need not name a feature; we fix it to "mid".
        if feats and feats != ["mid"]:
            errors.append("kind calibration takes no features (it recalibrates the market mid)")
        feats = ["mid"]
    else:  # logistic
        if not 1 <= len(feats) <= MAX_MODEL_FEATURES:
            errors.append("kind logistic needs 1..%d features" % MAX_MODEL_FEATURES)
        if len(set(feats)) != len(feats):
            errors.append("model.features must not repeat a feature")
        for name in feats:
            if name not in FEATURES:
                errors.append("model.features %r is not a known feature" % name)

    if not _num_ok(intercept):
        errors.append("model.intercept must be a finite number")
    if coef and len(coef) != len(feats):
        errors.append("model.coef must be empty (unfitted) or one value per feature")
    for c in coef:
        if not _num_ok(c):
            errors.append("model.coef values must be finite numbers")
            break
    if not any("model." in e for e in errors):  # only normalise a clean model
        m["features"] = list(feats)
        m["coef"] = [float(c) for c in coef]
        m["intercept"] = float(intercept)


def is_learned_model(spec: Dict) -> bool:
    """True for a logistic/calibration spec (a model whose coefficients are fit on research)."""
    return not is_code_spec(spec) and spec.get("model", {}).get("kind", "gbm") in ("logistic", "calibration")


def is_fitted(spec: Dict) -> bool:
    """A learned spec whose coefficients are already frozen in (ready to backtest). A gbm/code
    spec is always 'fitted' (nothing to fit)."""
    if not is_learned_model(spec):
        return True
    return bool(spec["model"].get("coef"))


def n_free_params(spec: Dict) -> int:
    """How many parameters this spec FITS from data - its degrees of freedom, used to make the
    DSR selection correction count every fitted coefficient as an implicit trial (more parameters
    => a higher statistical bar, never lower). A gbm/code spec is hand-specified, not fit, so it
    stays 1 (one hypothesis = one trial, exactly as before). A logistic model fits an intercept +
    one weight per feature; a calibration fits a slope + intercept."""
    if is_learned_model(spec):
        return 1 + len(spec["model"].get("features", []))  # intercept + one weight per feature
    return 1


def _validate_cross(spec: Dict, errors: List[str]) -> None:
    """Validate the optional `cross` relative-value block, normalising it in place. None stays
    None (ordinary single-contract spec). Mirrors the strictness of the rest of validate():
    unknown fields, bad pairing/relationship and unknown leg markets are errors, never clamped."""
    cross = spec.get("cross")
    if cross is None:
        return
    if not isinstance(cross, dict):
        errors.append("cross must be an object or null")
        return
    for key in set(cross) - {"legs", "pairing", "relationship"}:
        errors.append("unknown field cross.%s" % key)
    pairing = cross.get("pairing")
    if pairing not in CROSS_PAIRINGS:
        errors.append("cross.pairing must be one of %s" % list(CROSS_PAIRINGS))
    rel = cross.get("relationship", "spread")
    if rel not in CROSS_RELATIONSHIPS:
        errors.append("cross.relationship must be one of %s" % list(CROSS_RELATIONSHIPS))
    legs = cross.get("legs", [])
    clean_legs: List[Dict] = []
    if not isinstance(legs, list) or len(legs) > MAX_CROSS_LEGS:
        errors.append("cross.legs must be a list of at most %d legs" % MAX_CROSS_LEGS)
    else:
        for i, leg in enumerate(legs):
            if not isinstance(leg, dict) or set(leg) != {"market"}:
                errors.append("cross.legs[%d] must have exactly feature market" % i)
            elif leg["market"] not in MARKETS:
                errors.append("cross.legs[%d].market %r is not a known market" % (i, leg["market"]))
            else:
                clean_legs.append({"market": leg["market"]})
    involved = {spec["market"]} | {leg["market"] for leg in clean_legs}
    if any(k in MARKETS and MARKETS[k].kind == "perpetual" for k in involved):
        errors.append("Perpetual research cannot be a leg of a binary cross-contract strategy.")
    if pairing == "cross_sectional" and len(involved) < 2:
        errors.append("cross.pairing cross_sectional needs a leg on a different market than %s" % spec["market"])
    # A cross-MARKET pair must share one decision cadence, or its legs never co-occur on a frame
    # (merged backtest) and can't be ticked together live - never pair a 1-min market with a daily.
    if len(involved) > 1 and not compatible_cadence(involved):
        errors.append("cross legs span incompatible decision cadences (%s); pair only markets with "
                      "the same candle_minutes and close schedule" % ", ".join(sorted(involved)))
    if not errors:
        spec["cross"] = {"pairing": pairing, "legs": clean_legs, "relationship": rel}


def is_cross_contract(spec: Dict) -> bool:
    return bool(spec.get("cross"))


def involved_markets(spec: Dict) -> List[str]:
    """Every market a spec touches, sorted & deduped. A single-contract spec touches exactly
    one (== spec['market']); a cross spec touches spec['market'] plus its legs'."""
    markets = {spec["market"]}
    for leg in (spec.get("cross") or {}).get("legs", []):
        markets.add(leg["market"])
    return sorted(markets)


def stream_key(spec: Dict) -> str:
    """The FDR alpha-wealth stream a spec spends from. Single-contract -> its own market
    (per-market stream, unchanged). Cross-contract -> ONE shared stream across its legs
    ('btc_daily+eth_daily'), so a pair never double-spends its legs' separate budgets."""
    return "+".join(involved_markets(spec))


# -- the rule ---------------------------------------------------------------


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _sigmoid(z: float) -> float:
    z = 30.0 if z > 30.0 else -30.0 if z < -30.0 else z
    return 1.0 / (1.0 + math.exp(-z))


def _logit(p: float) -> float:
    p = min(1.0 - 1e-6, max(1e-6, p))
    return math.log(p / (1.0 - p))


def _fair_learned(m: Dict, f: Dict[str, float]) -> Optional[float]:
    """P(YES) from a FROZEN learned model: sigmoid(intercept + coef . features). Returns None when
    the model is not yet fit (no coef) or a required feature is missing on this frame (same 'no
    signal' contract as the GBM path - the caller skips, it never crashes a backtest)."""
    coef = m.get("coef") or []
    if not coef:
        return None  # unfitted: no signal until the research pipeline freezes coefficients in
    if m.get("kind") == "calibration":
        if "mid" not in f:
            return None
        return _sigmoid(m["intercept"] + coef[0] * _logit(f["mid"]))
    z = m["intercept"]
    for name, c in zip(m["features"], coef):
        v = f.get(name)
        if v is None:
            return None
        z += c * v
    return _sigmoid(z)


def fair_yes(spec: Dict, f: Dict[str, float]) -> Optional[float]:
    m = spec["model"]
    if m.get("kind", "gbm") in ("logistic", "calibration"):
        return _fair_learned(m, f)
    # The GBM-digital model needs an underlying (strike-vs-spot) path: moneyness + realised vol.
    # A sports market has neither, so there is no model fair value - return None and let the
    # caller skip (entries/pair_entries treat None as "no signal"). Such markets are researched
    # with code strategies, which never call fair_yes.
    if "moneyness" not in f or ("vol_%dm" % m["vol_window"]) not in f:
        return None
    sigma = m["vol_scale"] * f["vol_%dm" % m["vol_window"]]
    t = f["tte_min"]
    mu = 0.0
    if m["drift_window"]:
        mu = m["drift_beta"] * f["ret_%dm" % m["drift_window"]] / m["drift_window"]
    sigma_t = sigma * math.sqrt(t)
    x = f["moneyness"] + mu * t
    if sigma_t <= 1e-12:
        return 1.0 if x > 0 else 0.0 if x < 0 else 0.5
    return _phi(x / sigma_t)


def _passes(flt: Dict, f: Dict[str, float]) -> bool:
    v = f.get(flt["feature"])
    if v is None:
        return False
    op, ref = flt["op"], flt["value"]
    return v > ref if op == ">" else v >= ref if op == ">=" else v < ref if op == "<" else v <= ref


@dataclass(frozen=True)
class Entry:
    snapshot: Snapshot
    side: str  # "yes" | "no"
    price: float  # what one contract costs
    fair: float  # fair value of that side
    edge: float


def side_prices(snap: Snapshot) -> Dict[str, Tuple[float, float]]:
    """side -> (buy price, sell price). NO is the mirror of the YES book."""
    return {
        "yes": (snap.yes_ask, snap.yes_bid),
        "no": (1.0 - snap.yes_bid, 1.0 - snap.yes_ask),
    }


def entries(spec: Dict, snaps: List[Snapshot]) -> List[Entry]:
    """Every contract the rule would buy now, best edge first."""
    e = spec["entry"]
    stake = spec["sizing"]["stake"]
    sides = ("yes", "no") if spec["side"] == "either" else (spec["side"],)
    out: List[Entry] = []
    for snap in snaps:
        f = snap.features
        if not e["min_tte_min"] <= f["tte_min"] <= e["max_tte_min"]:
            continue
        if f["spread"] > e["max_spread"]:
            continue
        if not all(_passes(flt, f) for flt in e["filters"]):
            continue
        p_yes = fair_yes(spec, f)
        if p_yes is None:
            continue
        prices = side_prices(snap)
        best = None
        for side in sides:
            price = prices[side][0]
            if price <= 0 or price >= 1 or not e["min_price"] <= price <= e["max_price"]:
                continue
            fair = p_yes if side == "yes" else 1.0 - p_yes
            edge = fair - price
            # Net of Kalshi's actual taker fee at THIS fill price, for the order
            # this spec would place (contracts_for is exactly how engine.py and
            # backtest.py size, so backtest and live gate on the identical net
            # edge). The fee peaks at the 50c mid; a gross gate systematically
            # enters trades whose real edge is negative. Ranking stays on gross;
            # only the accept test is net, so this is strictly stricter.
            net = edge - taker_fee_per_contract_dollars(contracts_for(stake, price), price)
            if net >= e["min_edge"] and (best is None or edge > best.edge):
                best = Entry(snap, side, price, fair, edge)
        if best is not None:
            out.append(best)
    out.sort(key=lambda x: x.edge, reverse=True)
    return out


def exit_signal(spec: Dict, side: str, entry_price: float, snap: Snapshot) -> Optional[Tuple[str, float]]:
    """(reason, sell price) if the rule says sell now, else None (hold)."""
    x = spec["exit"]
    sell = side_prices(snap)[side][1]
    if sell <= 0:
        return None  # nobody to sell to; holding to settlement is the only option
    gain = sell - entry_price
    if x["take_profit"] is not None and gain >= x["take_profit"]:
        return "take_profit", sell
    if x["stop_loss"] is not None and -gain >= x["stop_loss"]:
        return "stop_loss", sell
    if x["min_edge_to_hold"] is not None:
        p_yes = fair_yes(spec, snap.features)
        if p_yes is not None:
            fair = p_yes if side == "yes" else 1.0 - p_yes
            if fair - sell < x["min_edge_to_hold"]:
                return "edge_gone", sell
    return None


def contracts_for(stake: float, price: float) -> int:
    # Not `stake // price`: in binary floating point 10 // 0.4 == 24.0.
    return int(math.floor(stake / price + 1e-9)) if price > 0 else 0


# Features the fair-value model always consumes, independent of the spec.
_MODEL_FEATURES = ("spot", "moneyness", "tte_min", "yes_bid", "yes_ask", "spread", "mid")


def features_used(spec: Dict) -> List[str]:
    """Every FEATURES key this spec reads: the model's always-on inputs, the vol/drift
    windows it picked, and whatever the entry filters condition on. This is the dataset-
    provenance record - 'any dataset, as long as we track it.'"""
    if is_perpetual_spec(spec):
        return ["funding_rate_estimate"] if spec["perpetual"]["signal"] == "funding" else [
            "close", "trailing_return_%dm" % spec["perpetual"]["lookback_minutes"]]
    if is_code_spec(spec):
        # A code strategy's signals(window) receives the full per-frame feature dict, so it may
        # read ANY feature. The honest provenance record is every feature we expose, not the DSL
        # model/filter fields a code spec does not have.
        return sorted(FEATURES)
    used = set(_MODEL_FEATURES)
    m = spec["model"]
    kind = m.get("kind", "gbm")
    if kind in ("logistic", "calibration"):
        # A learned model's provenance is exactly the features it scores (calibration reads mid).
        used.update(m.get("features") or [])
    else:
        used.add("vol_%dm" % m["vol_window"])
        if m["drift_window"]:
            used.add("ret_%dm" % m["drift_window"])
    for flt in spec["entry"]["filters"]:
        used.add(flt["feature"])
    return sorted(used)


def data_sources_for(spec: Dict) -> List[str]:
    """The DB tables this spec's features are drawn from: contract quotes + the BTC
    price path always, plus the order-book feature table iff a filter uses a micro
    feature. Recorded alongside features_used so the ledger shows what data was touched."""
    if is_perpetual_spec(spec):
        return ["kalshi_perps_batches", "kalshi_perps_partition_sources"]
    srcs = ["hist_markets", "market_candles", "spot_candles_1m"]
    model_feats = (spec.get("model", {}).get("features") or []) if not is_code_spec(spec) else []
    # A code spec gets the full window (micro features included), so record every source; a DSL spec
    # touches the order-book table iff a filter OR a learned-model feature reads a micro feature.
    if (is_code_spec(spec)
            or any(flt["feature"] in MICRO_FEATURES for flt in spec["entry"]["filters"])
            or any(name in MICRO_FEATURES for name in model_feats)):
        srcs.append("model_features_1m")
    # Free external data the spec requested (Pillar 3): record each as source:series@lagNd so the
    # ledger shows exactly what external data the hypothesis touched (resolved + joined point-in-
    # time on the host; the request itself is in the hashed spec, so the trial stays pinned).
    for d in spec.get("datasets") or []:
        srcs.append("%s:%s@lag%dd" % (d["source"], d["series"], d.get("lag_days", 1)))
    return srcs


# -- cross-contract relative value (pairs) ----------------------------------
#
# A pair buys YES on the most UNDER-priced leg and NO on the most OVER-priced leg within a
# matched group, so it profits on the relative mispricing rather than a directional view.
# It reuses the same GBM fair value and entry gates as the single-contract rule; only the
# selection (group + pick long/short) is new. The legs hold to settlement (the hedge stays
# intact until both resolve). ponytail: spread exits would need a live co-price both legs
# quote at the same frame; hold-to-settle is the honest default and matches single-contract.


@dataclass(frozen=True)
class PairEntry:
    long_snap: Snapshot    # buy YES here (underpriced)
    short_snap: Snapshot   # buy NO here (overpriced)
    long_price: float      # YES ask paid on the long leg
    short_price: float     # NO price paid on the short leg (= 1 - yes_bid)
    edge: float            # combined relative edge = long YES edge + short NO edge


def _pair_group_key(pairing: str, snap: Snapshot):
    """The key contracts must share to be comparable. cross_strike groups by settlement (so
    members differ only in strike); calendar groups by strike (members differ in settlement);
    cross_sectional puts the whole frame in one group (members differ by market/series)."""
    c = snap.contract
    if pairing == "cross_strike":
        return int(c.close_time.timestamp())
    if pairing == "calendar":
        return round(c.strike, 6)
    return 0  # cross_sectional: one group per decision frame


def _pair_distinct(pairing: str, a: Snapshot, b: Snapshot) -> bool:
    ca, cb = a.contract, b.contract
    if pairing == "cross_strike":
        return abs(ca.strike - cb.strike) > 1e-9
    if pairing == "calendar":
        return int(ca.close_time.timestamp()) != int(cb.close_time.timestamp())
    return (ca.series or "") != (cb.series or "")  # cross_sectional: different markets


def pair_entries(spec: Dict, snaps: List[Snapshot]) -> List[PairEntry]:
    """Every relative-value pair the cross spec would open now, best combined edge first.
    Returns [] for a non-cross spec. Each leg must independently pass the entry price/spread/
    tte/feature gates; the pair enters when (long YES edge + short NO edge) >= entry.min_edge."""
    cross = spec.get("cross")
    if not cross:
        return []
    pairing = cross["pairing"]
    e = spec["entry"]
    stake = spec["sizing"]["stake"]
    scored = []  # (snap, p_yes, yes_ask, yes_bid)
    for s in snaps:
        f = s.features
        if not e["min_tte_min"] <= f["tte_min"] <= e["max_tte_min"]:
            continue
        if f["spread"] > e["max_spread"]:
            continue
        if not all(_passes(flt, f) for flt in e["filters"]):
            continue
        p_yes = fair_yes(spec, f)
        if p_yes is None:
            continue
        scored.append((s, p_yes, s.yes_ask, s.yes_bid))

    groups: Dict = {}
    for tup in scored:
        groups.setdefault(_pair_group_key(pairing, tup[0]), []).append(tup)

    out: List[PairEntry] = []
    for members in groups.values():
        longs = [m for m in members if e["min_price"] <= m[2] <= e["max_price"] and 0 < m[2] < 1]
        shorts = [m for m in members if e["min_price"] <= 1 - m[3] <= e["max_price"] and 0 < 1 - m[3] < 1]
        if not longs or not shorts:
            continue
        lng = max(longs, key=lambda m: m[1] - m[2])              # YES edge = p_yes - yes_ask
        cand = [m for m in shorts if m[0] is not lng[0] and _pair_distinct(pairing, lng[0], m[0])]
        if not cand:
            continue
        srt = max(cand, key=lambda m: m[3] - m[1])               # NO edge = yes_bid - p_yes
        edge = (lng[1] - lng[2]) + (srt[3] - srt[1])
        long_price, short_price = lng[2], 1 - srt[3]
        # Both legs cross the book as takers, each paying a fee at its own fill
        # price (YES ask on the long leg, NO price = 1 - yes_bid on the short),
        # on the order this pair would place (contracts_for, as backtest/engine
        # size it). Gate on the combined edge NET of both fees - strictly stricter.
        qty = contracts_for(stake, long_price + short_price)
        net = edge - taker_fee_per_contract_dollars(qty, long_price) - taker_fee_per_contract_dollars(qty, short_price)
        if net < e["min_edge"]:
            continue
        out.append(PairEntry(lng[0], srt[0], long_price, short_price, edge))
    out.sort(key=lambda x: x.edge, reverse=True)
    return out


def describe(spec: Dict) -> List[str]:
    """Plain-language reading of a spec, for people who do not read JSON."""
    if is_perpetual_spec(spec):
        rule = spec["perpetual"]
        return ["Bitcoin perpetual %s research, %s directions." % (rule["signal"], rule["side"]),
                "Uses completed history and observed funding estimates; trades at the next bar open.",
                "One position at 1x; maximum 24 hours; fixed fee and slippage scenario costs.",
                "Research only: no broker paper, demo or live execution."]
    if is_code_spec(spec):
        s = spec["sizing"]
        return [
            "Agent-authored quant code (a custom signals() function), run in an isolated sandbox.",
            "The backtester applies the same fees, settlement and sizing as any other strategy.",
            "Stakes $%g per trade, at most %d open at once." % (s["stake"], s["max_positions"]),
        ]
    m, e, x, s = spec["model"], spec["entry"], spec["exit"], spec["sizing"]
    side = {"yes": "YES contracts", "no": "NO contracts", "either": "YES or NO (whichever has more edge)"}[spec["side"]]
    lines = ["Buys %s when its fair value beats the price by at least %d¢." % (side, round(e["min_edge"] * 100))]
    kind = m.get("kind", "gbm")
    if kind == "logistic":
        fit = "fit on the research window" if m.get("coef") else "not yet fit"
        lines.append("Fair value is a learned logistic model (%s) scoring %s."
                     % (fit, ", ".join(m.get("features") or []) or "its features"))
    elif kind == "calibration":
        fit = "fit on the research window" if m.get("coef") else "not yet fit"
        lines.append("Fair value recalibrates the market's own implied probability (%s) to correct the "
                     "favorite-longshot bias." % fit)
    else:
        view = "Fair value uses %d-minute realised volatility" % m["vol_window"]
        if abs(m["vol_scale"] - 1.0) > 1e-9:
            view += " scaled ×%.2f" % m["vol_scale"]
        if m["drift_window"] and m["drift_beta"]:
            view += ", leaning %s the last %d minutes (β %.2f)" % (
                "with" if m["drift_beta"] > 0 else "against",
                m["drift_window"],
                m["drift_beta"],
            )
        lines.append(view + ".")
    lines.append(
        "Pays %d¢–%d¢ per contract, %g–%g minutes before settlement, spread at most %d¢."
        % (round(e["min_price"] * 100), round(e["max_price"] * 100), e["min_tte_min"], e["max_tte_min"], round(e["max_spread"] * 100))
    )
    for flt in e["filters"]:
        lines.append("Only when %s %s %g." % (flt["feature"], flt["op"], flt["value"]))
    exits = []
    if x["take_profit"] is not None:
        exits.append("takes profit at +%d¢" % round(x["take_profit"] * 100))
    if x["stop_loss"] is not None:
        exits.append("stops out at −%d¢" % round(x["stop_loss"] * 100))
    if x["min_edge_to_hold"] is not None:
        exits.append("sells when its edge drops below %d¢" % round(x["min_edge_to_hold"] * 100))
    lines.append(("Exits: " + ", ".join(exits) + "; otherwise holds to settlement.") if exits else "Holds every position to settlement.")
    lines.append("Stakes $%g per trade, at most %d open at once." % (s["stake"], s["max_positions"]))
    cross = spec.get("cross")
    if cross:
        kind = {"cross_sectional": "two different markets (relative value)",
                "cross_strike": "two strikes of the same event",
                "calendar": "the same strike across two settlements"}.get(cross["pairing"], cross["pairing"])
        lines.append("Relative-value pair across %s: buys YES on the underpriced leg and NO on the "
                     "overpriced leg, holding both to settlement." % kind)
        labels = [MARKETS[m].label if m in MARKETS else m for m in involved_markets(spec)]
        lines.append("Legs: %s." % ", ".join(labels))
    return lines
