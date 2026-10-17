"""Quant toolkit for Kalshi BTC binary-option trading.

Pure functions the research/RSI agent can call to price a contract, measure its
edge against the book after Kalshi's fee, size a bet, and watch portfolio risk.

Conventions matched to the rest of the system (do not diverge):
- A Kalshi contract is a cash-or-nothing BINARY: YES pays $1 if the underlying
  settles above (or below) the strike, else $0. Prices are dollars in (0, 1) and
  read as probabilities.
- Volatility features (`vol_15m`, `vol_60m`) are the stdev of **1-minute** BTC log
  returns (see app/markets.py). So they are a per-1-minute sigma; the horizon
  scaling is sigma * sqrt(minutes), exactly as markets.py's `z_score` does
  (moneyness / (vol_60m * sqrt(tte_min))).
- The fee is Kalshi's real taker fee, reused verbatim from data_pipeline.kalshi_fees
  (ceil-to-cent of 0.07 * C * P * (1-P)) — never approximated as a flat rate.

Modeling assumption to sanity-check: BTC is treated as lognormal/GBM (Black-Scholes
digital). BTC has fatter tails than lognormal, so near-the-money short-dated fair
values are reasonable but deep-OTM tails are under-priced by this model — a vol
smile or a t-distribution would price the wings better. See `yes_fair_value`.

Stdlib only (math.erf for the normal CDF) + the shared fee module; no numpy/scipy
needed for this. ponytail: add numpy only if a vectorized pricer is ever hot.
"""
from __future__ import annotations

import math
from typing import Dict, List

from data_pipeline.kalshi_fees import taker_fee_dollars

MINUTES_PER_YEAR = 365 * 24 * 60  # 525600 — BTC trades 24/7, so calendar-time annualization


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function (stdlib, no scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def yes_fair_value(spot: float, strike: float, minutes_to_expiry: float,
                   annualized_vol: float, side: str = "above") -> float:
    """Risk-neutral P(contract settles YES) for a cash-or-nothing binary under GBM.

    Black-Scholes digital: P(S_T > K) = N(d2), d2 = (ln(S/K) - 0.5 sigma^2 T) / (sigma sqrt(T)),
    with T in years and sigma the annualized vol. `side="below"` returns 1 - that.
    At/after expiry or with zero vol it collapses to certainty by moneyness.
    Returns a probability in [0, 1] (interior values are open (0,1)).
    """
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if side not in ("above", "below"):
        raise ValueError("side must be 'above' or 'below'")
    T = minutes_to_expiry / MINUTES_PER_YEAR
    if T <= 0 or annualized_vol <= 0:
        p_above = 0.5 if spot == strike else (1.0 if spot > strike else 0.0)
    else:
        d2 = (math.log(spot / strike) - 0.5 * annualized_vol ** 2 * T) / (annualized_vol * math.sqrt(T))
        p_above = _norm_cdf(d2)
    return p_above if side == "above" else 1.0 - p_above


def annualize_vol(sigma_window: float, minutes_per_window: float = 1.0) -> float:
    """Scale a per-step return stdev to an annualized sigma for the pricer.

    `sigma_window` is the stdev of log returns each spanning `minutes_per_window`
    minutes. Our vol_15m/vol_60m are stdev of 1-minute returns, so default = 1.
    """
    if minutes_per_window <= 0:
        raise ValueError("minutes_per_window must be positive")
    return sigma_window * math.sqrt(MINUTES_PER_YEAR / minutes_per_window)


def realized_vol(returns) -> float:
    """Population stdev of a sequence of log returns (matches markets.py's _vol)."""
    r = [float(x) for x in returns]
    if len(r) < 2:
        return 0.0
    m = sum(r) / len(r)
    var = sum((x - m) ** 2 for x in r) / len(r)  # population, as markets._vol computes
    return math.sqrt(max(var, 0.0))


def kalshi_fee(price: float, contracts: int) -> float:
    """Kalshi taker fee in dollars for `contracts` at `price` — the real schedule, reused."""
    return taker_fee_dollars(int(contracts), float(price))


def edge(fair_prob: float, market_price: float, side: str = "yes") -> float:
    """Expected value per contract vs the book (gross of fee).

    Buying YES at `market_price` wins $1 w.p. `fair_prob` for cost `market_price`
    -> EV = fair_prob - market_price. For NO, the win prob is (1 - fair_prob).
    `fair_prob` is always P(YES settles).
    """
    win = fair_prob if side == "yes" else 1.0 - fair_prob
    return win - market_price


def after_fee_edge(fair_prob: float, market_price: float, contracts: int, side: str = "yes") -> float:
    """Total expected value of the order net of Kalshi's taker fee (dollars)."""
    gross = edge(fair_prob, market_price, side) * contracts
    return gross - kalshi_fee(market_price, contracts)


def kelly_fraction(fair_prob: float, price: float) -> float:
    """Full-Kelly bankroll fraction for a binary bought at `price` with win prob
    `fair_prob`. Derivation: f* = (q - P)/(1 - P). 0 (no bet) when edge <= 0.
    Pass the side's own (win prob, price) — for NO use (1 - P_yes, no_price).
    """
    if price <= 0.0 or price >= 1.0:
        return 0.0
    return max(0.0, (fair_prob - price) / (1.0 - price))


def fractional_kelly(fair_prob: float, price: float, frac: float = 0.25, cap: float = 1.0) -> float:
    """Fractional Kelly (default quarter-Kelly) clamped to [0, cap] — the practical,
    lower-variance size. Full Kelly is too aggressive given model/estimate error."""
    return min(cap, max(0.0, frac) * kelly_fraction(fair_prob, price))


def portfolio_metrics(positions: List[Dict]) -> Dict:
    """Exposure summary for a set of open positions.

    Each position: {"cost": float, "market"|"ticker": str}. Returns total_exposure
    (sum of cost), concentration (largest single-market share of exposure, 0..1),
    and n_markets (distinct markets).
    """
    by_market: Dict[str, float] = {}
    total = 0.0
    for p in positions:
        c = float(p.get("cost", 0.0))
        k = p.get("market") or p.get("ticker") or "?"
        by_market[k] = by_market.get(k, 0.0) + c
        total += c
    conc = (max(by_market.values()) / total) if total > 0 else 0.0
    return {"total_exposure": round(total, 4), "concentration": round(conc, 4), "n_markets": len(by_market)}


def max_drawdown(equity) -> float:
    """Largest peak-to-trough drop (dollars, positive) over an equity curve."""
    peak = None
    mdd = 0.0
    for v in equity:
        v = float(v)
        if peak is None or v > peak:
            peak = v
        mdd = max(mdd, peak - v)
    return round(mdd, 4)


def demo() -> None:
    """Runnable self-check: assert the core relationships hold."""
    sig = annualize_vol(0.002)  # ~0.2% per-minute BTC vol -> annualized
    atm = yes_fair_value(100000, 100000, 60, sig, "above")
    assert abs(atm - 0.5) < 0.02, atm                                   # ATM ~ 0.5
    assert yes_fair_value(130000, 100000, 60, sig, "above") > 0.99      # deep ITM ~ 1
    assert yes_fair_value(70000, 100000, 60, sig, "above") < 0.01       # deep OTM ~ 0
    assert yes_fair_value(100000, 100000, 0, sig, "above") == 0.5       # settled, at strike
    # monotonic in moneyness
    a = yes_fair_value(99000, 100000, 60, sig); b = yes_fair_value(101000, 100000, 60, sig)
    assert a < atm < b
    assert abs(edge(0.60, 0.50, "yes") - 0.10) < 1e-9 and abs(edge(0.60, 0.50, "no") + 0.10) < 1e-9
    assert kelly_fraction(0.50, 0.50) == 0.0 and kelly_fraction(0.70, 0.50) > kelly_fraction(0.60, 0.50)
    assert kalshi_fee(0.50, 100) >= 0
    assert max_drawdown([100, 120, 90, 110, 80]) == 40.0
    pm = portfolio_metrics([{"cost": 30, "market": "a"}, {"cost": 10, "market": "a"}, {"cost": 10, "market": "b"}])
    assert pm["total_exposure"] == 50.0 and pm["n_markets"] == 2 and abs(pm["concentration"] - 0.8) < 1e-9
    print("quant demo OK")


if __name__ == "__main__":
    demo()
