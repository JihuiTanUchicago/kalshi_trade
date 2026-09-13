"""How much of the logistic_resolution_edge + hold_to_settlement edge survives
plausible transaction costs? The backtest in research_expiry_resolution.py
models zero fees. Kalshi-style fee schedules are typically proportional to
price*(1-price) per contract (highest around $0.50, near-zero at the
extremes) - this is a scenario sweep over a RANGE of plausible fee rates,
not a claim about Kalshi's actual current published schedule, which this
session has not verified.
"""
from data_pipeline.common import get_db_conn
from research.expiry_resolution import (
    build_matrix, chronological_split_by_ticker, fetch_rows,
    label_and_build_trade_path, make_logistic,
)

FEE_RATE_SCENARIOS = [0.0, 0.01, 0.02, 0.03, 0.05, 0.07]
PT, ET = 0.65, 0.01  # the grid point research_expiry_resolution.py selected on validation


def fee_per_contract(price: float, rate: float) -> float:
    return rate * price * (1.0 - price)


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = fetch_rows(cur)
    conn.close()

    rows = label_and_build_trade_path(rows)
    train_rows, val_rows, test_rows = chronological_split_by_ticker(rows)
    trainval_rows = train_rows + val_rows
    trainval_X, trainval_y = build_matrix(trainval_rows)
    test_X, test_y = build_matrix(test_rows)

    model = make_logistic()
    model.fit(trainval_X, trainval_y)
    test_probs = model.predict_proba(test_X)[:, 1]

    slice_end_ts = test_rows[-1]["snapshot_minute_utc"]
    open_until_ts = None
    trades = []
    for r, p in zip(test_rows, test_probs):
        ts = r["snapshot_minute_utc"]
        if open_until_ts is not None and ts <= open_until_ts:
            continue
        ask = float(r.get("yes_ask_dollars") or 0.0)
        if ask <= 0:
            continue
        edge = p - ask
        if p < PT or edge < ET:
            continue
        exit_ts = r["hold_to_settlement_ts"]
        if exit_ts > slice_end_ts:
            continue
        exit_px = r["hold_to_settlement_price"]
        trades.append((ask, exit_px))
        open_until_ts = exit_ts

    print(f"trades={len(trades)}")
    print(f"{'fee_rate':>10}  {'gross_pnl':>10}  {'total_fees':>10}  {'net_pnl':>10}  {'net_avg':>10}")
    for rate in FEE_RATE_SCENARIOS:
        gross = sum(exit_px - ask for ask, exit_px in trades)
        fees = sum(fee_per_contract(ask, rate) + fee_per_contract(exit_px, rate) for ask, exit_px in trades)
        net = gross - fees
        net_avg = net / len(trades) if trades else 0.0
        print(f"{rate:>10.2%}  {gross:>10.4f}  {fees:>10.4f}  {net:>10.4f}  {net_avg:>10.5f}")


if __name__ == "__main__":
    main()
