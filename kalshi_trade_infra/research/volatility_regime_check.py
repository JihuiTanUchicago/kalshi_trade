"""Cheap retrospective check before building anything new: do the existing
production models' ~24k historical closed trades show a volatility-regime
pattern? Joins each trade's entry to model_features_1m's cb_vol_5m at that
minute and buckets PnL by volatility quintile. If PnL is concentrated in
low-vol (or high-vol) buckets, that's a strong, cheap signal worth pursuing
with a real backtest; if it's flat across buckets, the existing models'
losses aren't a volatility-regime problem and this angle isn't worth more
time.
"""
import numpy as np

from data_pipeline.common import get_db_conn


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.model_name, t.pnl_dollars, m.cb_vol_5m
            FROM sim_trades t
            JOIN model_features_1m m
              ON m.market_ticker = t.market_ticker
             AND m.snapshot_minute_utc = t.opened_at_utc
            WHERE t.status='closed' AND t.pnl_dollars IS NOT NULL AND m.cb_vol_5m IS NOT NULL
            """
        )
        rows = cur.fetchall()
    conn.close()

    print(f"joined rows: {len(rows)}")
    if not rows:
        print("[WARN] no joined rows - check join condition")
        return

    by_model: dict = {}
    for r in rows:
        by_model.setdefault(r["model_name"], []).append((float(r["cb_vol_5m"]), float(r["pnl_dollars"])))

    for model_name, pairs in sorted(by_model.items()):
        vols = np.array([p[0] for p in pairs])
        pnls = np.array([p[1] for p in pairs])
        quintiles = np.quantile(vols, [0.2, 0.4, 0.6, 0.8])
        print(f"\n=== {model_name} (n={len(pairs)}) ===")
        edges = [-np.inf] + list(quintiles) + [np.inf]
        for i in range(5):
            mask = (vols > edges[i]) & (vols <= edges[i + 1])
            n = int(mask.sum())
            if n == 0:
                continue
            bucket_pnl = pnls[mask].sum()
            win_rate = float((pnls[mask] > 0).mean())
            print(f"  vol quintile {i+1}: n={n:5d}  total_pnl=${bucket_pnl:8.2f}  avg_pnl=${bucket_pnl/n:+.4f}  win_rate={win_rate:.3f}  vol_range=({edges[i]:.4f},{edges[i+1]:.4f})")


if __name__ == "__main__":
    main()
