"""Cheap validation before touching the pipeline: do open_interest_fp and the
NO-side quotes (both already collected - open_interest_fp is queried by
model_features_1m_builder.py and then silently dropped; no_bid/no_ask live
unparsed inside forward_quotes.raw_json for every historical row) add real
predictive power for the next-minute-direction label, on top of the existing
FEATURE_COLS? If yes, worth wiring into the real pipeline. If not, this is a
cheap way to find out without any new collection or storage.
"""
import json

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_pipeline.common import get_db_conn
from data_pipeline.modeling_features import FEATURE_COLS, build_feature_vector, has_target


def fetch_joined_rows(cur, limit: int = 60000):
    cur.execute(
        f"""
        SELECT m.snapshot_minute_utc, m.market_ticker, {",".join("m." + c for c in _source_cols())},
               fq.raw_json, fq.open_interest_fp
        FROM model_features_1m m
        JOIN forward_quotes fq
          ON fq.market_ticker = m.market_ticker AND fq.snapshot_time_utc = m.snapshot_minute_utc
        WHERE m.model_eligible=1
        ORDER BY m.snapshot_minute_utc DESC
        LIMIT {limit}
        """
    )
    rows = cur.fetchall()
    rows.reverse()
    return rows


def _source_cols():
    from data_pipeline.modeling_features import SOURCE_COLS
    return SOURCE_COLS


def build_supervised_with_extra(rows, require_no_side: bool = True):
    X_base = []
    X_extra = []
    y = []
    for i in range(len(rows) - 1):
        r = rows[i]
        nxt = rows[i + 1]
        if r["market_ticker"] != nxt["market_ticker"]:
            continue
        if not has_target(r) or not has_target(nxt):
            continue
        ask_t = r.get("yes_ask_dollars")
        bid_t1 = nxt.get("yes_bid_dollars")
        if ask_t is None or bid_t1 is None:
            continue

        oi = r.get("open_interest_fp")
        oi_f = float(oi) if oi is not None else 0.0

        no_bid_f = no_ask_f = None
        if require_no_side:
            raw = r.get("raw_json")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            elif not isinstance(raw, dict):
                raw = {}
            no_bid = raw.get("no_bid_dollars")
            no_ask = raw.get("no_ask_dollars")
            if no_bid is None or no_ask is None:
                continue
            try:
                no_bid_f = float(no_bid)
                no_ask_f = float(no_ask)
            except (TypeError, ValueError):
                continue

        yes_ask_f = float(r.get("yes_ask_dollars") or 0.0)
        yes_bid_f = float(r.get("yes_bid_dollars") or 0.0)

        x_base = build_feature_vector(r)
        if require_no_side:
            x_extra = [(yes_ask_f + no_ask_f) - 1.0, (yes_bid_f + no_bid_f) - 1.0, oi_f]
        else:
            x_extra = [oi_f]
        target = 1 if float(bid_t1) > float(ask_t) else 0
        X_base.append(x_base)
        X_extra.append(x_extra)
        y.append(target)
    return np.asarray(X_base, dtype=float), np.asarray(X_extra, dtype=float), np.asarray(y, dtype=int)


def main() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = fetch_joined_rows(cur)
    conn.close()

    print(f"joined rows: {len(rows)}")

    X_base_ns, X_extra_ns, y_ns = build_supervised_with_extra(rows, require_no_side=True)
    print(f"usable rows WITH no_bid/no_ask requirement: {len(X_base_ns)} (too sparse for a reliable test - see below)")

    X_base, X_extra, y = build_supervised_with_extra(rows, require_no_side=False)
    print(f"usable rows for open_interest_fp only (no no_bid/no_ask requirement): {len(X_base)}")
    if len(X_base) < 500:
        print("[WARN] too few usable rows even for open_interest_fp alone")
        return

    # Standardize the extra columns separately since open_interest_fp is on a very different scale.
    X_full = np.hstack([X_base, X_extra])

    tscv = TimeSeriesSplit(n_splits=5)
    aucs_base = []
    aucs_full = []
    for train_idx, test_idx in tscv.split(X_full):
        pipe_base = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", C=0.5))])
        pipe_base.fit(X_base[train_idx], y[train_idx])
        p_base = pipe_base.predict_proba(X_base[test_idx])[:, 1]
        aucs_base.append(roc_auc_score(y[test_idx], p_base))

        pipe_full = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", C=0.5))])
        pipe_full.fit(X_full[train_idx], y[train_idx])
        p_full = pipe_full.predict_proba(X_full[test_idx])[:, 1]
        aucs_full.append(roc_auc_score(y[test_idx], p_full))

    print(f"\nAUC without open_interest_fp: {np.mean(aucs_base):.4f} (folds: {[f'{a:.4f}' for a in aucs_base]})")
    print(f"AUC WITH open_interest_fp:    {np.mean(aucs_full):.4f} (folds: {[f'{a:.4f}' for a in aucs_full]})")
    print(f"delta: {np.mean(aucs_full) - np.mean(aucs_base):+.4f}")

    print("\nraw correlation with next-minute-direction label:")
    print(f"  open_interest_fp: corr={np.corrcoef(X_extra[:, 0], y)[0,1]:+.4f}")


if __name__ == "__main__":
    main()
