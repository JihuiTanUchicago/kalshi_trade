"""cb_vol_5m (the only volatility feature models see) is computed from just 5
once-per-minute Coinbase price samples (model_features_1m_builder.py's
asof_coinbase loop), despite coinbase_ticks already being collected every 20
seconds - about 15 samples/minute, ~74 in a 5-minute window, all sitting in
the DB unused for this purpose. Zero new data collection needed to fix this.

Tests two proper realized-volatility estimators from the quantitative finance
literature (not a model swap - this is a feature-engineering question, and
the standard tools for it are statistical, not ML):
  - Realized volatility (RV): sqrt(sum(r_i^2)) over the high-frequency returns
    in the window - the standard high-frequency vol estimator (Andersen-
    Bollerslev), deliberately not demeaned since intraday returns are ~zero-mean
    and demeaning only adds noise at this frequency.
  - EWMA (RiskMetrics-style): exponentially-weighted realized variance, more
    responsive to a recent vol regime shift than a flat window.
against the existing coarse cb_vol_5m, for the production next-minute-
direction label.
"""
import sys
import time as time_mod

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_pipeline.common import get_db_conn
from data_pipeline.modeling_features import FEATURE_COLS, SOURCE_COLS, build_feature_vector, has_target

EWMA_LAMBDA = 0.90  # ~7-tick half-life at 20s sampling (~2.3 minutes) - tuned for intraday, not RiskMetrics' daily 0.94


def fetch_rows(cur, limit: int = 20000):
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, {",".join(SOURCE_COLS)}
        FROM model_features_1m
        WHERE model_eligible=1
        ORDER BY snapshot_minute_utc DESC
        LIMIT {limit}
        """
    )
    rows = cur.fetchall()
    rows.reverse()
    return rows


def fetch_all_ticks(cur, start, end):
    cur.execute(
        """
        SELECT snapshot_time_utc, price
        FROM coinbase_ticks
        WHERE status='ok' AND snapshot_time_utc BETWEEN %s AND %s
        ORDER BY snapshot_time_utc ASC
        """,
        (start, end),
    )
    ticks = cur.fetchall()
    times = np.array([t["snapshot_time_utc"] for t in ticks])
    prices = np.array([float(t["price"]) for t in ticks])
    return times, prices


def window_returns(times, prices, ts, window_minutes=5):
    """O(log n) window lookup via searchsorted instead of a full boolean scan
    (the first version of this script did that and timed out against 820k
    ticks x 60k rows)."""
    from datetime import timedelta
    lo = ts - timedelta(minutes=window_minutes)
    lo_idx = np.searchsorted(times, lo, side="right")
    hi_idx = np.searchsorted(times, ts, side="right")
    window_prices = prices[lo_idx:hi_idx]
    if len(window_prices) < 5:
        return None
    return np.diff(window_prices) / window_prices[:-1]


def realized_vol(returns: np.ndarray) -> float:
    """RV = sqrt(sum(r_i^2)) - standard high-frequency realized-vol estimator,
    deliberately not demeaned (Andersen-Bollerslev convention for intraday
    returns, which are ~zero-mean at this frequency)."""
    return float(np.sqrt(np.sum(returns**2)))


def ewma_vol(returns: np.ndarray, lam: float = EWMA_LAMBDA) -> float:
    """Exponentially-weighted realized variance, most recent return weighted
    highest - more responsive to a recent regime shift than a flat window."""
    n = len(returns)
    weights = lam ** np.arange(n - 1, -1, -1)  # oldest->smallest, newest->largest
    weights = weights / weights.sum()
    var = np.sum(weights * returns**2)
    return float(np.sqrt(var))


def build_dataset(rows, times, prices):
    X_base = []
    rv_vals = []
    ewma_vals = []
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
        rets = window_returns(times, prices, r["snapshot_minute_utc"])
        if rets is None or len(rets) < 3:
            continue
        x = build_feature_vector(r)
        target = 1 if float(bid_t1) > float(ask_t) else 0
        X_base.append(x)
        rv_vals.append(realized_vol(rets))
        ewma_vals.append(ewma_vol(rets))
        y.append(target)
    return np.asarray(X_base, dtype=float), np.asarray(rv_vals, dtype=float), np.asarray(ewma_vals, dtype=float), np.asarray(y, dtype=int)


def cv_auc(X, y, n_splits=5):
    tscv = TimeSeriesSplit(n_splits=n_splits)
    aucs = []
    for train_idx, test_idx in tscv.split(X):
        pipe = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", C=0.5))])
        pipe.fit(X[train_idx], y[train_idx])
        p = pipe.predict_proba(X[test_idx])[:, 1]
        aucs.append(roc_auc_score(y[test_idx], p))
    return np.mean(aucs), aucs


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    t0 = time_mod.time()
    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = fetch_rows(cur, limit=limit)
        start = rows[0]["snapshot_minute_utc"]
        end = rows[-1]["snapshot_minute_utc"]
        print(f"model_features_1m rows: {len(rows)}, range {start} to {end}", flush=True)
        print(f"[{time_mod.time()-t0:.1f}s] fetched model_features_1m rows", flush=True)
        times, prices = fetch_all_ticks(cur, start, end)
        print(f"coinbase_ticks in range: {len(prices)}", flush=True)
        print(f"[{time_mod.time()-t0:.1f}s] fetched coinbase_ticks", flush=True)
    conn.close()

    X_base, rv_vals, ewma_vals, y = build_dataset(rows, times, prices)
    print(f"usable rows: {len(X_base)}", flush=True)
    print(f"[{time_mod.time()-t0:.1f}s] built dataset", flush=True)
    if len(X_base) < 1000:
        print("[WARN] too few usable rows")
        return

    vol_idx = FEATURE_COLS.index("cb_vol_5m")
    coarse_vol = X_base[:, vol_idx]
    print(f"\ncorrelation(coarse cb_vol_5m, label) = {np.corrcoef(coarse_vol, y)[0,1]:+.4f}")
    print(f"correlation(realized_vol, label)     = {np.corrcoef(rv_vals, y)[0,1]:+.4f}")
    print(f"correlation(ewma_vol, label)         = {np.corrcoef(ewma_vals, y)[0,1]:+.4f}")
    print(f"correlation(coarse, realized_vol)    = {np.corrcoef(coarse_vol, rv_vals)[0,1]:+.4f}  (how similar the two are)")

    X_rv_added = np.hstack([X_base, rv_vals.reshape(-1, 1)])
    X_ewma_added = np.hstack([X_base, ewma_vals.reshape(-1, 1)])
    X_rv_replaced = X_base.copy(); X_rv_replaced[:, vol_idx] = rv_vals
    X_ewma_replaced = X_base.copy(); X_ewma_replaced[:, vol_idx] = ewma_vals

    auc_base, _ = cv_auc(X_base, y)
    auc_rv_added, _ = cv_auc(X_rv_added, y)
    auc_ewma_added, _ = cv_auc(X_ewma_added, y)
    auc_rv_replaced, _ = cv_auc(X_rv_replaced, y)
    auc_ewma_replaced, _ = cv_auc(X_ewma_replaced, y)

    print(f"\nAUC baseline (coarse cb_vol_5m only):         {auc_base:.4f}")
    print(f"AUC + realized_vol added:                     {auc_rv_added:.4f}  (delta {auc_rv_added-auc_base:+.4f})")
    print(f"AUC + ewma_vol added:                         {auc_ewma_added:.4f}  (delta {auc_ewma_added-auc_base:+.4f})")
    print(f"AUC realized_vol REPLACING coarse cb_vol_5m:  {auc_rv_replaced:.4f}  (delta {auc_rv_replaced-auc_base:+.4f})")
    print(f"AUC ewma_vol REPLACING coarse cb_vol_5m:      {auc_ewma_replaced:.4f}  (delta {auc_ewma_replaced-auc_base:+.4f})")


if __name__ == "__main__":
    main()
