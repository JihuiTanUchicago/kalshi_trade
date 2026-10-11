"""Robustness check for the random_forest high-edge-quintile finding in
edge_magnitude_check.py: does filtering to edge > EDGE_FILTER hold up
consistently across time (first half vs second half of history), or is the
aggregate +$89.40/1449-trade result driven by one lucky stretch?
"""
import json

from data_pipeline.common import get_db_conn

EDGE_FILTER = 0.167  # top quintile boundary found in edge_magnitude_check.py


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT opened_at_utc, pnl_dollars, raw_json
            FROM sim_trades
            WHERE model_name='random_forest' AND status='closed' AND pnl_dollars IS NOT NULL
            ORDER BY opened_at_utc ASC
            """
        )
        rows = cur.fetchall()
    conn.close()

    filtered = []
    for r in rows:
        raw = r["raw_json"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                continue
        edge = raw.get("edge") if isinstance(raw, dict) else None
        if edge is None or float(edge) <= EDGE_FILTER:
            continue
        filtered.append((r["opened_at_utc"], float(r["pnl_dollars"])))

    print(f"total trades with edge > {EDGE_FILTER}: {len(filtered)}")
    if not filtered:
        return

    mid = len(filtered) // 2
    first_half = filtered[:mid]
    second_half = filtered[mid:]

    for label, half in [("first half (chronological)", first_half), ("second half (chronological)", second_half)]:
        pnls = [p for _, p in half]
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        print(f"{label}: n={len(half)}  date_range=({half[0][0]} to {half[-1][0]})  total_pnl=${total:.2f}  avg_pnl=${total/len(half):+.4f}  win_rate={wins/len(half):.3f}")

    # Also split by calendar month for a finer-grained view.
    print("\nby month:")
    by_month: dict = {}
    for ts, pnl in filtered:
        key = ts.strftime("%Y-%m")
        by_month.setdefault(key, []).append(pnl)
    for month in sorted(by_month):
        pnls = by_month[month]
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        print(f"  {month}: n={len(pnls):4d}  total_pnl=${total:8.2f}  avg_pnl=${total/len(pnls):+.4f}  win_rate={wins/len(pnls):.3f}")


if __name__ == "__main__":
    main()
