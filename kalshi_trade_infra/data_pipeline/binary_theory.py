"""Closed-form fair-probability estimate for a Kalshi 15-min BTC binary
contract, derived from options theory rather than fit to historical data.

Model: BTC/USD follows a driftless geometric Brownian motion over the
contract's remaining life (mu=0 - predicting short-horizon crypto drift is
notoriously unreliable, so a random walk is the honest null). Under that
assumption, for a binary contract paying $1 if S_T >= K:

    P(YES) = Phi( ln(S_0/K) / (sigma * sqrt(T)) )

This is the same d2 term as Black-Scholes for a cash-or-nothing digital
option, minus the risk-neutral drift correction (-0.5*sigma^2*T) - this is
the physical-measure probability of an outcome, not a risk-neutral price.

Validated in research/binary_option_theory_check.py: standalone AUC 0.858 on
the expiry-resolution label with zero fitting, but with a systematic
overconfidence bias in calibration - predicted probabilities run well above
realized rates in the middle deciles. See research/binary_theory_robustness_check.py
for the trading-signal robustness/fee-sensitivity results this module's
threshold is based on. This module and the research script must stay in
sync - the whole point is that what's live is exactly what was tested.
"""
from typing import Dict, Optional

import numpy as np
from scipy.stats import norm


def theoretical_p_yes(row: Dict) -> Optional[float]:
    """P(YES) under a driftless GBM, using cb_vol_5m as the per-minute vol
    estimate scaled to the contract's remaining time-to-expiry. Returns None
    if required inputs are missing (caller should treat as "no signal")."""
    spot = row.get("cb_price")
    strike = row.get("target_btc_price")
    tte_sec = row.get("time_to_expiry_sec")
    vol_1m = row.get("cb_vol_5m")
    if spot is None or strike is None or tte_sec is None or vol_1m is None:
        return None
    spot = float(spot)
    strike = float(strike)
    tte_min = max(float(tte_sec), 1.0) / 60.0
    vol_1m = float(vol_1m)
    if spot <= 0 or strike <= 0 or vol_1m <= 0:
        return None
    sigma_t = vol_1m * np.sqrt(tte_min)
    if sigma_t <= 1e-9:
        return 1.0 if spot >= strike else 0.0
    d2 = np.log(spot / strike) / sigma_t
    return float(norm.cdf(d2))
