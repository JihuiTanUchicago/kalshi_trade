"""Centralized configuration and constants for the simulated trading engine.

Collecting thresholds here (instead of scattering literals through
simulated_trading_engine.py) makes the actual trading rules auditable at a
glance, and gives the risk layer one place to read tunables from.
"""
from dataclasses import asdict, dataclass
from typing import Dict

STARTING_CAPITAL = 100.0

# Signal / exit threshold shared by the frozen models. Applied symmetrically:
# a position opens when prob >= PRED_THRESHOLD and closes when prob drops
# below it (no separate hysteresis band currently implemented).
PRED_THRESHOLD = 0.55
EDGE_THRESHOLD = 0.01

# Research finding (2026-09-12, see research/binary_option_theory_check.py):
# a pure closed-form driftless-GBM binary-option probability (zero fitting -
# see data_pipeline/binary_theory.py) matched ML-level standalone AUC (0.858)
# and, filtered to only its largest mispricings (edge > 0.15), showed
# positive PnL that held up across the whole available window (not decaying
# like the random_forest finding below) and survived up to ~3% simulated
# fees. Still only ~7-8 weeks of real coverage (same pre-incident data gap
# affects this dataset too) - binary_theory_edge (see ALL_MODELS) tests this
# forward on genuinely new data rather than mining the same window further.
BINARY_THEORY_EDGE_THRESHOLD = 0.15

# Models that should never close early due to signal decay (only near-expiry
# force-close or ticker rotation ends their position) - this is what the
# binary_theory_edge research validated (hold_to_settlement exit style), a
# fundamentally different exit rule from every other model's early-exit-on-
# signal-decay behavior.
HOLD_TO_SETTLEMENT_MODELS: frozenset = frozenset({"binary_theory_edge"})

# Research finding (2026-09-12, see research/edge_magnitude_check.py): among
# random_forest's historical trades (Mar-Apr 2026, before the connection-drop
# incident), PnL rose monotonically with edge magnitude at entry - the top
# quintile (edge > ~0.167) was the only one clearly profitable (+$0.062/trade
# avg vs -$0.01 to -$0.15 for the other four). That result is from a limited
# window with a visible within-window decay (Mar +$0.125/trade -> Apr
# +$0.006/trade) and zero out-of-sample evidence since, so it is NOT treated
# as validated - random_forest_high_conviction (see ALL_MODELS below) exists
# to test this filter forward, on genuinely new data, rather than mining the
# same historical window further.
HIGH_CONVICTION_EDGE_THRESHOLD = 0.17

# Position sizing.
MAX_QTY = 10

# Frozen-model training window.
MIN_INSAMPLE_HOURS = 48
MIN_SAMPLES_DEFAULT_RF = 1000

# L1 regularization strength for logistic models. sklearn uses C = 1/lambda,
# so lambda=2.0 => C=0.5.
LOGREG_L1_C = 0.5

# Near-expiry handling: block new entries this close to expiry, and mark any
# position that cannot be sold at all in the contract's final seconds.
#
# This was 0.99, which assumed the position WON whenever the bid ladder was
# empty - and an empty ladder is exactly the illiquid case where live gets
# nothing. On 2026-09-27 the live engine had 27 contracts it could not sell
# (six consecutive exit orders cancelled, no bid); the market settled "no" and
# the position went to $0.00. The simulator's own record of that same market
# was a small gain. An unsellable position is worth what settlement pays,
# which a forward-running simulator does not know yet, so the honest mark is
# the conservative one: no bid means no exit.
NEAR_EXPIRY_SEC = 60
FORCE_CLOSE_NEAR_EXPIRY_PRICE = 0.0

RF_PARAMS_DEFAULT = dict(
    n_estimators=400,
    max_depth=8,
    min_samples_leaf=20,
    min_samples_split=50,
    max_features="sqrt",
    class_weight="balanced_subsample",
    random_state=42,
    n_jobs=-1,
)
RF_PARAMS_SMALL = dict(
    n_estimators=120,
    max_depth=5,
    min_samples_leaf=5,
    min_samples_split=20,
    max_features="sqrt",
    class_weight="balanced_subsample",
    random_state=42,
    n_jobs=-1,
)

# Models designed for a pure 1-minute round-trip (always close after one tick).
# The current frozen models don't use this - they hold using the symmetric
# PRED_THRESHOLD check above. Add a model here only if it is explicitly
# designed for 1-minute-hold evaluation.
HOLD_1M_MODELS: frozenset = frozenset()


@dataclass
class SimRiskSettings:
    """Risk caps applied per model, sized as fractions of that model's own
    starting capital (each model runs its own independent $STARTING_CAPITAL
    paper book so they can be compared fairly)."""

    # Cap a new position's notional (qty * entry price) to this fraction of
    # the model's current equity.
    max_position_fraction: float = 0.20
    # Once a model's drawdown from its own peak equity exceeds this fraction,
    # pause it (stop opening new positions; existing ones still get managed
    # down normally). Stays paused until explicitly cleared.
    max_drawdown_pct: float = 0.30
    # Hard floor: never open a new position once equity has fallen to or
    # below this dollar amount, regardless of drawdown_pct math.
    min_equity_floor: float = 10.0


DEFAULT_SIM_RISK_SETTINGS = SimRiskSettings()


def sim_risk_settings_to_dict(s: SimRiskSettings) -> Dict:
    return asdict(s)


def sim_risk_settings_from_dict(d: Dict) -> SimRiskSettings:
    base = asdict(DEFAULT_SIM_RISK_SETTINGS)
    base.update({k: v for k, v in (d or {}).items() if k in base})
    return SimRiskSettings(**base)
