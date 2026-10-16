"""One-off robustness check for the logistic_resolution_edge + hold_to_settlement
candidate flagged by research_expiry_resolution.py: is the positive test PnL a
broad plateau across nearby thresholds, or a narrow spike at exactly the grid
point chosen on validation? A narrow spike is much more likely to be noise
that happened to look good on this particular validation slice.
"""
from data_pipeline.common import get_db_conn
from research.expiry_resolution import (
    EDGE_GRID, THRESHOLD_GRID, build_matrix, chronological_split_by_ticker,
    fetch_rows, label_and_build_trade_path, make_logistic, simulate_trades,
)


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = fetch_rows(cur)
    conn.close()

    rows = label_and_build_trade_path(rows)
    train_rows, val_rows, test_rows = chronological_split_by_ticker(rows)
    train_X, train_y = build_matrix(train_rows)
    val_X, val_y = build_matrix(val_rows)
    test_X, test_y = build_matrix(test_rows)
    trainval_rows = train_rows + val_rows
    trainval_X, trainval_y = build_matrix(trainval_rows)

    model = make_logistic()
    model.fit(trainval_X, trainval_y)
    test_probs = model.predict_proba(test_X)[:, 1]

    val_model = make_logistic()
    val_model.fit(train_X, train_y)
    val_probs = val_model.predict_proba(val_X)[:, 1]

    print("=== validation PnL surface (exit_style=hold_to_settlement) ===")
    print("prob_threshold\\edge_threshold  " + "  ".join(f"{et:.2f}" for et in EDGE_GRID))
    for pt in THRESHOLD_GRID:
        row_vals = []
        for et in EDGE_GRID:
            res = simulate_trades(val_rows, val_probs, pt, et, exit_style="hold_to_settlement")
            row_vals.append(f"{res.total_pnl:+.2f}({res.trades})")
        print(f"{pt:.2f}  " + "  ".join(row_vals))

    print("\n=== test PnL surface (exit_style=hold_to_settlement) - same grid, held-out data ===")
    print("prob_threshold\\edge_threshold  " + "  ".join(f"{et:.2f}" for et in EDGE_GRID))
    positive_count = 0
    total_count = 0
    for pt in THRESHOLD_GRID:
        row_vals = []
        for et in EDGE_GRID:
            res = simulate_trades(test_rows, test_probs, pt, et, exit_style="hold_to_settlement")
            row_vals.append(f"{res.total_pnl:+.2f}({res.trades})")
            if res.trades >= 10:
                total_count += 1
                if res.total_pnl > 0:
                    positive_count += 1
        print(f"{pt:.2f}  " + "  ".join(row_vals))

    print(f"\nOf grid points with >=10 test trades, {positive_count}/{total_count} are PnL-positive.")
    print("If this fraction is well above 50%, the edge looks like a real (if thin) effect.")
    print("If it's close to 50% or below, the single validated point was likely a lucky grid cell.")


if __name__ == "__main__":
    main()
