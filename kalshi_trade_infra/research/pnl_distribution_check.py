"""random_forest shows win_rate > 50% in every volatility quintile yet loses
money in every one (see volatility_regime_check.py) - classic signature of
small wins offset by occasional large losses. If true, a stop-loss (pure
risk management, no new signal needed) might fix an otherwise-working model.
If losses are NOT fat-tailed/outlier-driven, a stop-loss won't help and the
problem is systematic (average loss size, not a few bad trades).
"""
import numpy as np

from data_pipeline.common import get_db_conn


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pnl_dollars FROM sim_trades WHERE model_name='random_forest' AND status='closed' AND pnl_dollars IS NOT NULL"
        )
        pnls = np.array([float(r["pnl_dollars"]) for r in cur.fetchall()])
    conn.close()

    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    print(f"n_trades={len(pnls)}  n_wins={len(wins)}  n_losses={len(losses)}")
    print(f"avg_win=${wins.mean():.4f}  avg_loss=${losses.mean():.4f}  loss/win_ratio={abs(losses.mean())/wins.mean():.2f}x")
    print(f"total_pnl=${pnls.sum():.2f}")
    print()
    print("loss percentiles (more negative = worse):")
    for p in [1, 5, 10, 25, 50]:
        print(f"  p{p}: ${np.percentile(pnls, p):.4f}")
    print()
    print("win percentiles:")
    for p in [50, 75, 90, 95, 99]:
        print(f"  p{p}: ${np.percentile(pnls, p):.4f}")
    print()
    # How much of total loss comes from the worst 1%/5%/10% of trades?
    sorted_pnls = np.sort(pnls)
    total_loss = losses.sum()
    for frac in [0.01, 0.05, 0.10]:
        k = max(1, int(len(sorted_pnls) * frac))
        worst_k_sum = sorted_pnls[:k].sum()
        print(f"worst {frac:.0%} of trades ({k} trades) account for ${worst_k_sum:.2f} of ${total_loss:.2f} total losses ({worst_k_sum/total_loss:.1%})")


if __name__ == "__main__":
    main()
