"""A genuinely different approach from the ML models tried so far: instead of
fitting a classifier to historical (feature, outcome) pairs, derive a fair
probability analytically from options theory and trade the gap between it
and Kalshi's actual market price. No training, no overfitting risk from
model selection - just a closed-form formula plus its assumptions.

Model: BTC/USD follows a driftless geometric Brownian motion over the
contract's remaining life (mu=0 - predicting short-horizon crypto drift is
notoriously unreliable, so a random walk is the honest null). Under that
assumption, for a binary contract paying $1 if S_T >= K:

    P(YES) = Phi( ln(S_0/K) / (sigma * sqrt(T)) )

This is the same d2 term as Black-Scholes for a cash-or-nothing digital
option, minus the risk-neutral drift correction (-0.5*sigma^2*T) - we want
the physical-measure probability of an outcome, not a risk-neutral price.
sigma is estimated from cb_vol_5m (already computed per-minute) scaled by
sqrt(T) to the contract's own remaining horizon (T in minutes).

Evaluated two ways against the expiry-resolution label (see
research/expiry_resolution.py for that label's definition and the
chronological-split-by-ticker harness reused here):
  1. Standalone predictive power (AUC/calibration) of the theoretical
     probability alone - no fitting at all.
  2. A trading signal: edge = p_yes_theory - yes_ask, backtested with the
     same validation-tuned threshold grid and fee-sensitivity check already
     used for every other candidate this session.
"""
import numpy as np

from data_pipeline.binary_theory import theoretical_p_yes as _theoretical_p_yes
from data_pipeline.common import get_db_conn
from research.expiry_resolution import (
    chronological_split_by_ticker,
    fetch_rows,
    label_and_build_trade_path,
    simulate_trades,
)


def theoretical_p_yes(row) -> float:
    """Thin wrapper: this research script evaluates a "no signal" case as
    p=0.5 (neutral) rather than None, since every downstream metric here
    expects a probability."""
    p = _theoretical_p_yes(row)
    return 0.5 if p is None else p


def evaluate_standalone(rows) -> None:
    from sklearn.metrics import average_precision_score, roc_auc_score

    p_theory = np.array([theoretical_p_yes(r) for r in rows])
    y = np.array([r["y_resolution"] for r in rows])
    print(f"\n=== Standalone predictive power of p_yes_theory (no fitting at all) ===")
    print(f"AUC:  {roc_auc_score(y, p_theory):.4f}")
    print(f"AP:   {average_precision_score(y, p_theory):.4f}")

    # Calibration: bucket by predicted probability, compare to realized rate.
    print("\ncalibration (predicted vs realized YES rate by decile):")
    order = np.argsort(p_theory)
    n = len(p_theory)
    for i in range(10):
        lo, hi = int(n * i / 10), int(n * (i + 1) / 10)
        idx = order[lo:hi]
        if len(idx) == 0:
            continue
        print(f"  decile {i+1}: n={len(idx):5d}  avg_predicted={p_theory[idx].mean():.3f}  realized_yes_rate={y[idx].mean():.3f}")


THRESHOLD_GRID = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
EDGE_GRID = [0.00, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]


def evaluate_trading_signal(train_rows, val_rows, test_rows) -> None:
    print(f"\n=== Trading signal: edge = p_yes_theory - yes_ask ===")
    val_probs = np.array([theoretical_p_yes(r) for r in val_rows])
    best = (THRESHOLD_GRID[0], EDGE_GRID[0], -1e9, 0)
    for pt in THRESHOLD_GRID:
        for et in EDGE_GRID:
            res = simulate_trades(val_rows, val_probs, pt, et, exit_style="hold_to_settlement")
            if res.total_pnl > best[2]:
                best = (pt, et, res.total_pnl, res.trades)
    pt, et, _, _ = best
    print(f"validation-selected rule: prob_threshold={pt}, edge_threshold={et}")

    test_probs = np.array([theoretical_p_yes(r) for r in test_rows])
    test_result = simulate_trades(test_rows, test_probs, pt, et, exit_style="hold_to_settlement")
    print(f"test: trades={test_result.trades}  total_pnl=${test_result.total_pnl:.4f}  avg_pnl=${test_result.avg_pnl:+.4f}  win_rate={test_result.win_rate}")

    # Also report the theory's own natural bar: trade only where the model is
    # highly confident of a real mispricing, regardless of validation tuning.
    print("\nfixed-rule sweep (no validation tuning - just theory vs market, pt=0.5 with varying edge):")
    for et in [0.02, 0.05, 0.08, 0.10, 0.15]:
        res = simulate_trades(test_rows, test_probs, 0.5, et, exit_style="hold_to_settlement")
        print(f"  edge>{et}: trades={res.trades:4d}  total_pnl=${res.total_pnl:8.4f}  avg_pnl=${res.avg_pnl:+.4f}  win_rate={res.win_rate}")


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = fetch_rows(cur)
    conn.close()

    print(f"dataset rows: {len(rows)}")
    rows = label_and_build_trade_path(rows)
    train_rows, val_rows, test_rows = chronological_split_by_ticker(rows)
    print(f"train/val/test: {len(train_rows)}/{len(val_rows)}/{len(test_rows)}")

    evaluate_standalone(rows)
    evaluate_trading_signal(train_rows, val_rows, test_rows)


if __name__ == "__main__":
    main()
