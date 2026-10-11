"""Mean-reversion of the binary_theory mispricing residual - a physics/
stat-arb angle, deliberately different in kind from every other candidate
tried so far. binary_theory_edge trades on the STATIC magnitude of
(theory_p - market_price) and holds to settlement. This script asks a
different question: does the residual itself behave like an Ornstein-
Uhlenbeck process (mean-reverting, with a characteristic half-life), and if
so, is a z-score mean-reversion rule (entry on a statistically anomalous
residual, exit on reversion or expiry) a distinct, exploitable signal - one
whose trade selection and PnL series should differ from a flat-threshold
rule, since it's driven by *relative* deviation from a local baseline, not
*absolute* edge magnitude.

Method:
  1. residual_t = mid_price_t - theoretical_p_yes(row_t) for every eligible
     row (data_pipeline.binary_theory - the exact production formula, kept
     in sync intentionally per that module's docstring).
  2. AR(1) test for mean reversion, pooled across all tickers: regress
     delta_residual_t = residual_{t+1} - residual_t on residual_t. A
     mean-reverting process has a significantly negative slope (= -theta in
     the OU discretization); a random walk has slope ~0.
  3. If reversion is real, fit theta/mu/sigma on a TRAIN window only, then
     backtest a z-score entry rule on VAL/TEST windows (out-of-sample theta,
     no lookahead): enter when |residual - mu| / sigma_eq exceeds a
     threshold, direction betting on reversion toward mu, exit on
     reversion-to-mu or contract expiry, fee-adjusted using the real Kalshi
     taker formula.
  4. Correlate this strategy's per-day PnL against binary_theory_edge's
     actual deployed sim_trades PnL (if enough history exists) - the whole
     point of this angle is to be uncorrelated, so this is the report's
     headline number, not an afterthought.

Reporting-only: writes no DB rows, does not touch the live sim engine.
"""
from typing import Dict, List, Tuple

import numpy as np

from data_pipeline.binary_theory import theoretical_p_yes
from data_pipeline.common import get_db_conn
from data_pipeline.kalshi_fees import taker_fee_dollars
from research.expiry_resolution import chronological_split_by_ticker, fetch_rows

Z_ENTRY_THRESHOLDS = (1.5, 2.0, 2.5)
MIN_TTE_FOR_EXIT_SEC = 30
ROLL_WINDOW = 60  # rows (~60 minutes pooled) for the local mu/sigma baseline


def compute_residuals(rows: List[Dict]) -> np.ndarray:
    out = np.full(len(rows), np.nan)
    for i, r in enumerate(rows):
        p = theoretical_p_yes(r)
        bid = r.get("yes_bid_dollars")
        ask = r.get("yes_ask_dollars")
        if p is None or bid is None or ask is None:
            continue
        mid = (float(bid) + float(ask)) / 2.0
        out[i] = mid - p
    return out


def ar1_reversion_test(rows: List[Dict], residual: np.ndarray) -> Tuple[float, float, int]:
    """Pooled AR(1) slope on same-ticker consecutive pairs only (never
    regress across a ticker boundary - that's not a real one-step
    transition). Returns (slope, half_life_minutes, n_pairs)."""
    xs, ys = [], []
    for i in range(len(rows) - 1):
        if rows[i]["market_ticker"] != rows[i + 1]["market_ticker"]:
            continue
        x, y = residual[i], residual[i + 1]
        if np.isnan(x) or np.isnan(y):
            continue
        xs.append(x)
        ys.append(y - x)
    if len(xs) < 100:
        return 0.0, float("nan"), len(xs)
    xs = np.asarray(xs)
    ys = np.asarray(ys)
    xs_c = xs - xs.mean()
    slope = float(np.dot(xs_c, ys) / np.dot(xs_c, xs_c))
    half_life = float("nan") if slope >= 0 else float(np.log(0.5) / np.log(1 + slope))
    return slope, half_life, len(xs)


def rolling_baseline(residual: np.ndarray, window: int = ROLL_WINDOW) -> Tuple[np.ndarray, np.ndarray]:
    """Trailing-only rolling mean/std (no lookahead - uses residual[:i] only
    for the baseline at position i)."""
    n = len(residual)
    mu = np.full(n, np.nan)
    sigma = np.full(n, np.nan)
    valid = residual[~np.isnan(residual)]
    for i in range(n):
        lo = max(0, i - window)
        window_vals = residual[lo:i]
        window_vals = window_vals[~np.isnan(window_vals)]
        if len(window_vals) >= 20:
            mu[i] = float(np.mean(window_vals))
            sigma[i] = float(np.std(window_vals))
    return mu, sigma


def backtest_zscore_reversion(rows: List[Dict], residual: np.ndarray, mu: np.ndarray, sigma: np.ndarray, z_entry: float) -> List[Dict]:
    """Long-only: enter YES when residual is anomalously negative (market
    underprices YES relative to theory, betting the gap closes upward), exit
    on reversion to mu or expiry. Entering NO-side (short-YES-equivalent) is
    symmetric via bid instead of ask but omitted here for simplicity - a
    clean, honest scope-cut, noted as a follow-up, not silently assumed."""
    by_ticker: Dict[str, List[int]] = {}
    for i, r in enumerate(rows):
        by_ticker.setdefault(r["market_ticker"], []).append(i)

    trades = []
    for ticker, idxs in by_ticker.items():
        idxs.sort(key=lambda i: rows[i]["snapshot_minute_utc"])
        open_until_pos = -1
        for pos, i in enumerate(idxs):
            if pos <= open_until_pos:
                continue
            r = rows[i]
            if np.isnan(residual[i]) or np.isnan(mu[i]) or np.isnan(sigma[i]) or sigma[i] <= 1e-6:
                continue
            z = (residual[i] - mu[i]) / sigma[i]
            if z > -z_entry:
                continue
            ask = float(r.get("yes_ask_dollars") or 0.0)
            if ask <= 0:
                continue
            tte = r.get("time_to_expiry_sec")
            if tte is None or float(tte) < MIN_TTE_FOR_EXIT_SEC:
                continue
            entry_px = ask
            exit_px, exit_pos = None, None
            for pos2 in range(pos + 1, len(idxs)):
                j = idxs[pos2]
                if np.isnan(residual[j]):
                    continue
                if residual[j] >= mu[i]:
                    bid_j = rows[j].get("yes_bid_dollars")
                    if bid_j is not None:
                        exit_px, exit_pos = float(bid_j), pos2
                        break
            if exit_px is None:
                final_bid = rows[idxs[-1]].get("yes_bid_dollars")
                exit_px = float(final_bid) if final_bid is not None else 0.0
                exit_pos = len(idxs) - 1
            fee = taker_fee_dollars(1, entry_px) + taker_fee_dollars(1, exit_px)
            trades.append({
                "ts": r["snapshot_minute_utc"], "ticker": ticker, "z": z,
                "entry": entry_px, "exit": exit_px, "gross_pnl": exit_px - entry_px,
                "net_pnl": (exit_px - entry_px) - fee,
            })
            open_until_pos = exit_pos
    return trades


def report_trades(label: str, trades: List[Dict]) -> None:
    n = len(trades)
    if n == 0:
        print(f"{label}: n=0 trades")
        return
    gross = sum(t["gross_pnl"] for t in trades)
    net = sum(t["net_pnl"] for t in trades)
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    print(
        f"{label}: n={n}  range=({trades[0]['ts']} to {trades[-1]['ts']})  "
        f"gross=${gross:+.4f}  net=${net:+.4f}  avg_net=${net/n:+.5f}  win_rate={wins/n:.3f}"
    )


def daily_pnl_series(trades: List[Dict]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for t in trades:
        day = t["ts"].strftime("%Y-%m-%d")
        out[day] = out.get(day, 0.0) + t["net_pnl"]
    return out


def correlate_with_deployed_model(cur, trades: List[Dict], model_name: str = "binary_theory_edge") -> None:
    cur.execute(
        "SELECT closed_at_utc, pnl_dollars FROM sim_trades WHERE model_name=%s AND status='closed' AND pnl_dollars IS NOT NULL",
        (model_name,),
    )
    deployed = cur.fetchall()
    if len(deployed) < 20:
        print(f"correlation vs {model_name}: skipped - only {len(deployed)} deployed closed trades, too few")
        return
    deployed_daily: Dict[str, float] = {}
    for r in deployed:
        day = r["closed_at_utc"].strftime("%Y-%m-%d")
        deployed_daily[day] = deployed_daily.get(day, 0.0) + float(r["pnl_dollars"])
    mine_daily = daily_pnl_series(trades)
    common_days = sorted(set(deployed_daily) & set(mine_daily))
    if len(common_days) < 10:
        print(f"correlation vs {model_name}: only {len(common_days)} overlapping days, too few to report")
        return
    x = np.array([mine_daily[d] for d in common_days])
    y = np.array([deployed_daily[d] for d in common_days])
    corr = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 and y.std() > 0 else float("nan")
    print(f"correlation vs {model_name} daily PnL (n_days={len(common_days)}): {corr:+.3f}")


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = fetch_rows(cur)
        print(f"loaded {len(rows)} eligible rows")
        residual = compute_residuals(rows)
        n_valid = int(np.sum(~np.isnan(residual)))
        print(f"residual computable for {n_valid}/{len(rows)} rows (binary_theory needs cb_price/target_btc_price/tte/cb_vol_5m)")

        train_rows, val_rows, test_rows = chronological_split_by_ticker(rows)
        train_end = len(train_rows)
        val_end = train_end + len(val_rows)

        print("\n=== AR(1) mean-reversion test (pooled, same-ticker consecutive pairs) ===")
        slope, half_life, n_pairs = ar1_reversion_test(train_rows, residual[:train_end])
        print(f"train window: slope={slope:+.4f}  half_life={half_life:.2f} min  n_pairs={n_pairs}")
        slope_v, half_life_v, n_pairs_v = ar1_reversion_test(rows[train_end:val_end], residual[train_end:val_end])
        print(f"val window (holdout, same test):   slope={slope_v:+.4f}  half_life={half_life_v:.2f} min  n_pairs={n_pairs_v}")
        if slope >= -0.02:
            print("\nSlope is ~0 or positive in-sample: no meaningful mean-reversion signal. Stopping here - a clean negative result.")
            return

        mu_all, sigma_all = rolling_baseline(residual)

        print("\n=== z-score reversion strategy, val window (in-sample threshold tuning) ===")
        best_z, best_net = None, -1e18
        for z in Z_ENTRY_THRESHOLDS:
            trades_val = backtest_zscore_reversion(val_rows, residual[train_end:val_end], mu_all[train_end:val_end], sigma_all[train_end:val_end], z)
            net = sum(t["net_pnl"] for t in trades_val)
            report_trades(f"z>={z}", trades_val)
            if net > best_net:
                best_net, best_z = net, z

        print(f"\n=== best val threshold z>={best_z}, evaluated out-of-sample on TEST window ===")
        trades_test = backtest_zscore_reversion(test_rows, residual[val_end:], mu_all[val_end:], sigma_all[val_end:], best_z)
        report_trades("test", trades_test)

        if trades_test:
            print("\n=== fee sensitivity (test window) ===")
            gross = sum(t["gross_pnl"] for t in trades_test)
            for rate_label, rate in [("0%", 0.0), ("taker (real, 7%)", 0.07)]:
                if rate == 0.0:
                    net = gross
                else:
                    fees = sum(taker_fee_dollars(1, t["entry"]) + taker_fee_dollars(1, t["exit"]) for t in trades_test)
                    net = gross - fees
                print(f"  {rate_label}: net=${net:+.4f}  avg=${net/len(trades_test):+.5f}")

            print("\n=== correlation with already-deployed binary_theory_edge (decorrelation check) ===")
            correlate_with_deployed_model(cur, trades_test)
    conn.close()


if __name__ == "__main__":
    main()
