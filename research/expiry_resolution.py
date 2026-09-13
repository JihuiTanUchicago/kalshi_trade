"""Research harness for an expiry-resolution-labeled strategy on the Kalshi
15-min BTC market.

Successor to a deleted ad-hoc `work/` research path that tested this same
idea on ~5 days of data (too little to trust: its best result was a random
forest at +$0.16 test PnL over 9 trades, 88.9% win rate). This repo now has
~6 months of `model_features_1m` history, enough to actually evaluate it.

Label: instead of the production next-minute-direction label, each row is
labeled by its OWN contract's eventual terminal outcome - y=1 if that
market_ticker's final observed YES bid was >= 0.90, else 0. This matches how
a binary contract actually resolves, which next-minute-direction does not.

This is a research/reporting tool only - it does not write to any DB table
or affect the live sim engine. Run it, read the report, and only wire a
candidate into simulated_trading_engine.py if it clears the bar described
in the report.
"""
import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_pipeline.common import get_db_conn
from data_pipeline.modeling_features import FEATURE_COLS, SOURCE_COLS, build_feature_vector, has_target

TERMINAL_YES_BID_THRESHOLD = 0.90
MIN_TTE_SEC = 120
TAKE_PROFIT_DOLLARS = 0.05


def fetch_rows(cur, end: Optional[str] = None) -> List[Dict]:
    where = ["model_eligible=1", "yes_ask_dollars IS NOT NULL", "time_to_expiry_sec >= %s"]
    params: List = [MIN_TTE_SEC]
    if end:
        where.append("snapshot_minute_utc <= %s")
        params.append(end)
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, event_ticker, yes_bid_dollars, {",".join(SOURCE_COLS)}
        FROM model_features_1m
        WHERE {" AND ".join(where)}
        ORDER BY snapshot_minute_utc ASC
        """,
        tuple(params),
    )
    rows = cur.fetchall()
    return [r for r in rows if has_target(r)]


def label_and_build_trade_path(rows: List[Dict]) -> List[Dict]:
    """Group by ticker, label every row of a ticker by that ticker's final
    observed YES bid, and precompute an executable exit price per row using
    only same-ticker future data (no lookahead across tickers, no lookahead
    within a ticker earlier than the row's own timestamp for entry)."""
    by_ticker: Dict[str, List[int]] = {}
    for i, r in enumerate(rows):
        by_ticker.setdefault(r["market_ticker"], []).append(i)

    for ticker, idxs in by_ticker.items():
        idxs.sort(key=lambda i: rows[i]["snapshot_minute_utc"])
        final_bid = rows[idxs[-1]].get("yes_bid_dollars")
        final_bid = float(final_bid) if final_bid is not None else 0.0
        label = 1 if final_bid >= TERMINAL_YES_BID_THRESHOLD else 0
        for pos, i in enumerate(idxs):
            r = rows[i]
            r["y_resolution"] = label
            entry_ask = float(r.get("yes_ask_dollars") or 0.0)
            target = entry_ask + TAKE_PROFIT_DOLLARS
            exit_px = final_bid
            exit_ts = rows[idxs[-1]]["snapshot_minute_utc"]
            for j in idxs[pos + 1:]:
                fut_bid = rows[j].get("yes_bid_dollars")
                if fut_bid is not None and float(fut_bid) >= target:
                    exit_px = float(fut_bid)
                    exit_ts = rows[j]["snapshot_minute_utc"]
                    break
            r["exit_price_if_entered"] = exit_px
            r["exit_ts_if_entered"] = exit_ts
            # Alternative trade-management style: hold to settlement instead
            # of scalping an early take-profit. A resolution-prediction model
            # is naturally monetized by holding to expiry (get paid ~$1 if
            # right, ~$0 if wrong) - scalping a small early profit while
            # still exposed to the full downside on losers is a mismatch
            # between signal and execution, not a flaw in the signal itself.
            r["hold_to_settlement_price"] = final_bid
            r["hold_to_settlement_ts"] = rows[idxs[-1]]["snapshot_minute_utc"]
    return rows


def chronological_split_by_ticker(rows: List[Dict], train_frac: float = 0.6, val_frac: float = 0.2) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """60/20/20 chronological split, adjusted to the nearest ticker boundary
    so a single 15-min contract's rows never straddle a split (the plain
    row-index split used by the old research script could put some rows of
    the same contract in train and others in test - leakage, since every
    row of a ticker shares the same label)."""
    n = len(rows)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))

    def snap_to_ticker_boundary(idx: int) -> int:
        if idx <= 0 or idx >= n:
            return idx
        ticker = rows[idx]["market_ticker"]
        while idx < n and rows[idx]["market_ticker"] == ticker:
            idx += 1
        return idx

    train_end = snap_to_ticker_boundary(train_end)
    val_end = snap_to_ticker_boundary(val_end)
    return rows[:train_end], rows[train_end:val_end], rows[val_end:]


@dataclass
class TradeSimResult:
    trades: int
    wins: int
    total_pnl: float
    avg_pnl: float

    @property
    def win_rate(self) -> Optional[float]:
        return (self.wins / self.trades) if self.trades > 0 else None


def simulate_trades(
    rows: List[Dict], probs: np.ndarray, prob_threshold: float, edge_threshold: float,
    exit_style: str = "take_profit",
) -> TradeSimResult:
    """Long-only, one position at a time (matches the original methodology):
    buy when p_yes >= prob_threshold and edge >= edge_threshold and no
    position is currently open. exit_style selects the precomputed exit
    price/timestamp fields: "take_profit" (original methodology: exit at
    entry+$0.05 if hit, else final settlement) or "hold_to_settlement"
    (always exit at the contract's final observed bid). If the exit would
    fall after this slice's own last row, the trade is skipped entirely -
    we can't verify the outcome without looking outside the slice."""
    px_field, ts_field = (
        ("exit_price_if_entered", "exit_ts_if_entered") if exit_style == "take_profit"
        else ("hold_to_settlement_price", "hold_to_settlement_ts")
    )
    trades = 0
    wins = 0
    total_pnl = 0.0
    slice_end_ts = rows[-1]["snapshot_minute_utc"] if rows else None
    open_until_ts: Optional[datetime] = None
    for r, p in zip(rows, probs):
        ts = r["snapshot_minute_utc"]
        if open_until_ts is not None and ts <= open_until_ts:
            continue
        ask = float(r.get("yes_ask_dollars") or 0.0)
        if ask <= 0:
            continue
        edge = p - ask
        if p < prob_threshold or edge < edge_threshold:
            continue
        exit_ts = r[ts_field]
        if slice_end_ts is not None and exit_ts > slice_end_ts:
            continue
        exit_px = r[px_field]
        pnl = exit_px - ask
        trades += 1
        total_pnl += pnl
        if pnl > 0:
            wins += 1
        open_until_ts = exit_ts
    avg_pnl = (total_pnl / trades) if trades > 0 else 0.0
    return TradeSimResult(trades=trades, wins=wins, total_pnl=total_pnl, avg_pnl=avg_pnl)


def build_matrix(rows: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
    X = np.asarray([build_feature_vector(r) for r in rows], dtype=float)
    y = np.asarray([r["y_resolution"] for r in rows], dtype=int)
    return X, y


def make_logistic() -> Pipeline:
    return Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(class_weight="balanced", C=0.5, max_iter=1000))])


def make_random_forest() -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=500, max_depth=10, min_samples_leaf=4, min_samples_split=12,
        max_features="sqrt", class_weight="balanced_subsample", random_state=42, n_jobs=-1,
    )


def make_hgb() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=0.03, max_depth=4, max_iter=250, min_samples_leaf=25,
        l2_regularization=0.01, max_leaf_nodes=63, random_state=42,
    )


THRESHOLD_GRID = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
EDGE_GRID = [0.00, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]


def tune_on_validation(val_rows: List[Dict], val_probs: np.ndarray, exit_style: str) -> Tuple[float, float, TradeSimResult]:
    best = (THRESHOLD_GRID[0], EDGE_GRID[0], TradeSimResult(0, 0, -1e9, 0.0))
    for pt in THRESHOLD_GRID:
        for et in EDGE_GRID:
            res = simulate_trades(val_rows, val_probs, pt, et, exit_style=exit_style)
            if res.total_pnl > best[2].total_pnl:
                best = (pt, et, res)
    return best


def evaluate_candidate(name: str, model_factory, train_X, train_y, val_rows, val_X, val_y, test_rows, test_X, test_y, trainval_rows, trainval_X, trainval_y, exit_style: str) -> Dict:
    model = model_factory()
    model.fit(train_X, train_y)
    val_probs = model.predict_proba(val_X)[:, 1]
    pt, et, val_result = tune_on_validation(val_rows, val_probs, exit_style)

    final_model = model_factory()
    final_model.fit(trainval_X, trainval_y)
    test_probs = final_model.predict_proba(test_X)[:, 1]
    ap = average_precision_score(test_y, test_probs) if len(set(test_y)) > 1 else float("nan")
    auc = roc_auc_score(test_y, test_probs) if len(set(test_y)) > 1 else float("nan")
    test_result = simulate_trades(test_rows, test_probs, pt, et, exit_style=exit_style)

    return {
        "name": name, "exit_style": exit_style, "prob_threshold": pt, "edge_threshold": et,
        "val_pnl": val_result.total_pnl, "val_trades": val_result.trades,
        "test_ap": ap, "test_auc": auc,
        "test_pnl": test_result.total_pnl, "test_trades": test_result.trades,
        "test_win_rate": test_result.win_rate, "test_avg_pnl": test_result.avg_pnl,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=None, help="Only use rows up to this UTC timestamp (YYYY-MM-DD HH:MM:SS)")
    args = parser.parse_args()

    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = fetch_rows(cur, end=args.end)
    conn.close()

    print(f"dataset rows: {len(rows)}")
    if not rows:
        print("[WARN] no rows fetched - nothing to do")
        return
    print(f"date range: {rows[0]['snapshot_minute_utc']} to {rows[-1]['snapshot_minute_utc']} UTC")

    rows = label_and_build_trade_path(rows)
    positive_rate = sum(r["y_resolution"] for r in rows) / len(rows)
    print(f"positive rate (final YES bid >= {TERMINAL_YES_BID_THRESHOLD}): {positive_rate:.4f}")

    train_rows, val_rows, test_rows = chronological_split_by_ticker(rows)
    print(f"train/val/test rows: {len(train_rows)}/{len(val_rows)}/{len(test_rows)}")
    if len(train_rows) < 200 or len(val_rows) < 50 or len(test_rows) < 50:
        print("[WARN] one or more splits is very small - results below are not trustworthy")

    train_X, train_y = build_matrix(train_rows)
    val_X, val_y = build_matrix(val_rows)
    test_X, test_y = build_matrix(test_rows)
    trainval_rows = train_rows + val_rows
    trainval_X, trainval_y = build_matrix(trainval_rows)

    candidates = [
        ("logistic_resolution_edge", make_logistic),
        ("random_forest_resolution_edge", make_random_forest),
        ("hist_gradient_boosting_resolution_edge", make_hgb),
    ]

    results = []
    for exit_style in ("take_profit", "hold_to_settlement"):
        print(f"\n=== Results: exit_style={exit_style} (validation-tuned rule, evaluated on held-out test) ===")
        for name, factory in candidates:
            r = evaluate_candidate(name, factory, train_X, train_y, val_rows, val_X, val_y, test_rows, test_X, test_y, trainval_rows, trainval_X, trainval_y, exit_style)
            results.append(r)
            print(
                f"{name}: pt={r['prob_threshold']} et={r['edge_threshold']} | "
                f"test AP={r['test_ap']:.4f} AUC={r['test_auc']:.4f} | "
                f"test trades={r['test_trades']} win_rate={r['test_win_rate']} | "
                f"test PnL total=${r['test_pnl']:.4f} avg=${r['test_avg_pnl']:.4f}"
            )

    print("\n=== Bar check (statistically defensible trade count, positive risk-adjusted OOS return) ===")
    for r in results:
        verdict = "CANDIDATE" if (r["test_trades"] >= 30 and r["test_pnl"] > 0 and (r["test_win_rate"] or 0) > 0.5) else "does not clear bar"
        print(f"{r['name']} [{r['exit_style']}]: {verdict} (trades={r['test_trades']}, pnl=${r['test_pnl']:.4f}, win_rate={r['test_win_rate']})")


if __name__ == "__main__":
    main()
