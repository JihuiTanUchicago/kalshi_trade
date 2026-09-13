"""Cheap check on existing production trade history: does the model's edge
magnitude at entry (prob_yes - ask, stored in sim_trades.raw_json) predict
trade quality? All 3 models currently trade on any edge > EDGE_THRESHOLD
(0.01) - if bigger edges perform meaningfully better, that's immediately
actionable (raise the threshold) without training anything new.
"""
import json

import numpy as np

from data_pipeline.common import get_db_conn


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT model_name, pnl_dollars, raw_json FROM sim_trades WHERE status='closed' AND pnl_dollars IS NOT NULL"
        )
        rows = cur.fetchall()
    conn.close()

    by_model: dict = {}
    skipped = 0
    for r in rows:
        raw = r["raw_json"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                skipped += 1
                continue
        edge = raw.get("edge") if isinstance(raw, dict) else None
        if edge is None:
            skipped += 1
            continue
        by_model.setdefault(r["model_name"], []).append((float(edge), float(r["pnl_dollars"])))

    print(f"total rows={len(rows)}  usable(has edge)={sum(len(v) for v in by_model.values())}  skipped={skipped}")

    for model_name, pairs in sorted(by_model.items()):
        edges = np.array([p[0] for p in pairs])
        pnls = np.array([p[1] for p in pairs])
        quintiles = np.quantile(edges, [0.2, 0.4, 0.6, 0.8])
        edge_bounds = [-np.inf] + list(quintiles) + [np.inf]
        print(f"\n=== {model_name} (n={len(pairs)}, edge range [{edges.min():.4f}, {edges.max():.4f}]) ===")
        for i in range(5):
            mask = (edges > edge_bounds[i]) & (edges <= edge_bounds[i + 1])
            n = int(mask.sum())
            if n == 0:
                continue
            bucket_pnl = pnls[mask].sum()
            win_rate = float((pnls[mask] > 0).mean())
            print(
                f"  edge quintile {i+1} ({edge_bounds[i]:.4f},{edge_bounds[i+1]:.4f}]: "
                f"n={n:5d}  total_pnl=${bucket_pnl:8.2f}  avg_pnl=${bucket_pnl/n:+.4f}  win_rate={win_rate:.3f}"
            )
        # Correlation check: does higher edge correlate with higher pnl at all?
        corr = np.corrcoef(edges, pnls)[0, 1]
        print(f"  correlation(edge, pnl) = {corr:+.4f}")


if __name__ == "__main__":
    main()
