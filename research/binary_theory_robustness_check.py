"""Robustness check for the binary_option_theory_check.py finding: is the
edge>0.15 profitability (test: +$2.16/84 trades) a real, time-stable effect,
or a lucky stretch like the earlier random_forest edge-magnitude finding
turned out to be (see PLAN.md - that one was entirely pre-incident, decaying
within its own window)? Also checks fee sensitivity, since every prior
"promising" result this session died there.
"""
import numpy as np

from data_pipeline.common import get_db_conn
from research.binary_option_theory_check import theoretical_p_yes
from research.expiry_resolution import fetch_rows, label_and_build_trade_path

EDGE_THRESHOLD = 0.15
PROB_THRESHOLD = 0.5


def collect_trades(rows):
    """Same one-at-a-time long-only logic as simulate_trades, but returns the
    individual trades (with timestamps) instead of just an aggregate, so we
    can slice by time afterward."""
    probs = np.array([theoretical_p_yes(r) for r in rows])
    slice_end_ts = rows[-1]["snapshot_minute_utc"] if rows else None
    open_until_ts = None
    trades = []
    for r, p in zip(rows, probs):
        ts = r["snapshot_minute_utc"]
        if open_until_ts is not None and ts <= open_until_ts:
            continue
        ask = float(r.get("yes_ask_dollars") or 0.0)
        if ask <= 0:
            continue
        edge = p - ask
        if p < PROB_THRESHOLD or edge < EDGE_THRESHOLD:
            continue
        exit_ts = r["hold_to_settlement_ts"]
        if slice_end_ts is not None and exit_ts > slice_end_ts:
            continue
        exit_px = r["hold_to_settlement_price"]
        trades.append({"ts": ts, "ask": ask, "exit_px": exit_px, "pnl": exit_px - ask})
        open_until_ts = exit_ts
    return trades


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = fetch_rows(cur)
    conn.close()

    rows = label_and_build_trade_path(rows)
    trades = collect_trades(rows)
    print(f"total trades with edge > {EDGE_THRESHOLD}: {len(trades)}")
    if not trades:
        return

    print(f"date range: {trades[0]['ts']} to {trades[-1]['ts']}")

    mid = len(trades) // 2
    for label, half in [("first half", trades[:mid]), ("second half", trades[mid:])]:
        pnls = [t["pnl"] for t in half]
        wins = sum(1 for p in pnls if p > 0)
        print(f"{label}: n={len(half)}  range=({half[0]['ts']} to {half[-1]['ts']})  total_pnl=${sum(pnls):.4f}  avg=${sum(pnls)/len(half):+.4f}  win_rate={wins/len(half):.3f}")

    print("\nby month:")
    by_month = {}
    for t in trades:
        key = t["ts"].strftime("%Y-%m")
        by_month.setdefault(key, []).append(t["pnl"])
    for month in sorted(by_month):
        pnls = by_month[month]
        wins = sum(1 for p in pnls if p > 0)
        print(f"  {month}: n={len(pnls):4d}  total_pnl=${sum(pnls):8.4f}  avg=${sum(pnls)/len(pnls):+.4f}  win_rate={wins/len(pnls):.3f}")

    print("\n=== fee sensitivity ===")
    print(f"{'fee_rate':>10}  {'gross_pnl':>10}  {'total_fees':>10}  {'net_pnl':>10}  {'net_avg':>10}")
    for rate in [0.0, 0.01, 0.02, 0.03, 0.05, 0.07]:
        gross = sum(t["pnl"] for t in trades)
        fees = sum(rate * t["ask"] * (1 - t["ask"]) + rate * t["exit_px"] * (1 - t["exit_px"]) for t in trades)
        net = gross - fees
        print(f"{rate:>10.2%}  {gross:>10.4f}  {fees:>10.4f}  {net:>10.4f}  {net/len(trades):>10.5f}")


if __name__ == "__main__":
    main()
