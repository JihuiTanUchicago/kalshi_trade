import ast
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.modeling_features import (
    BASELINE_FEATURE_COLS,
    FEATURE_COLS,
    SOURCE_COLS,
    build_feature_vector,
    coalesce_float,
    has_target,
)

FROZEN_MODELS = ("naive_logistic_baseline", "logistic", "random_forest")
WALK_FORWARD_MODELS = ("walk_forward_logistic", "walk_forward_random_forest")
ALL_MODELS = FROZEN_MODELS + WALK_FORWARD_MODELS
MIN_SAMPLES_DEFAULT_RF = 1000
PRED_THRESHOLD = 0.55
EDGE_THRESHOLD = 0.01
MAX_QTY = 10
MIN_INSAMPLE_HOURS = 48
WF_LOOKBACK_HOURS = 72
WF_MIN_SAMPLES = 120
# L1 regularization strength for logistic models.
# sklearn uses C = 1 / lambda, so lambda=2.0 => C=0.5.
LOGREG_L1_C = 0.5


@dataclass
class ModelOutput:
    prob: float
    train_rows: int
    test_rows: int
    brier: Optional[float]
    ll: Optional[float]
    rf_regime: Optional[str]


@dataclass
class FrozenModel:
    estimator: object
    train_rows: int
    test_rows: int
    brier: Optional[float]
    ll: Optional[float]
    rf_regime: Optional[str]


BASELINE_IDX = tuple(FEATURE_COLS.index(c) for c in BASELINE_FEATURE_COLS)


def next_minute_plus_delay(delay_seconds: int = 10) -> datetime:
    now = utc_now()
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1, seconds=delay_seconds)


def load_feature_rows(cur, limit: int = 8000) -> List[Dict]:
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, event_ticker, {",".join(SOURCE_COLS)}
        FROM model_features_1m
        WHERE model_eligible=1
        ORDER BY snapshot_minute_utc DESC
        LIMIT {limit}
        """
    )
    rows = cur.fetchall()
    rows.reverse()
    return rows


def build_supervised(rows: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
    X = []
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
        x = build_feature_vector(r)
        target = 1 if float(bid_t1) > float(ask_t) else 0
        X.append(x)
        y.append(target)
    if not X:
        return np.empty((0, len(FEATURE_COLS))), np.empty((0,))
    return np.asarray(X, dtype=float), np.asarray(y, dtype=int)


def split_train_test(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(X)
    if n < 30:
        return X, y, np.empty((0, X.shape[1])), np.empty((0,))
    test_n = max(20, int(n * 0.2))
    test_n = min(test_n, max(1, n // 3))
    return X[:-test_n], y[:-test_n], X[-test_n:], y[-test_n:]


def parse_iso_utc(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except Exception:
        return None


def get_live_cutoff_utc(cur) -> Optional[datetime]:
    cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_live_cutoff_utc' LIMIT 1")
    row = cur.fetchone()
    if not row:
        return None
    sv = row.get("state_value")
    if isinstance(sv, dict):
        return parse_iso_utc(sv.get("cutoff_utc"))
    try:
        j = json.loads(sv)
        if isinstance(j, dict):
            return parse_iso_utc(j.get("cutoff_utc"))
    except Exception:
        pass
    return parse_iso_utc(str(sv))


def is_sim_recompute_in_progress(cur) -> bool:
    cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_recompute_in_progress' LIMIT 1")
    row = cur.fetchone()
    if not row:
        return False
    sv = row.get("state_value")
    if isinstance(sv, dict):
        return bool(sv.get("in_progress"))
    try:
        j = json.loads(sv)
        if isinstance(j, dict):
            return bool(j.get("in_progress"))
    except Exception:
        pass
    return False


def choose_effective_cutoff(rows: List[Dict], requested_cutoff: Optional[datetime]) -> Optional[datetime]:
    if not rows:
        return requested_cutoff
    start_ts = rows[0].get("snapshot_minute_utc")
    end_ts = rows[-1].get("snapshot_minute_utc")
    if not start_ts or not end_ts:
        return requested_cutoff
    min_cutoff = start_ts + timedelta(hours=MIN_INSAMPLE_HOURS)
    cutoff = requested_cutoff or min_cutoff
    if cutoff < min_cutoff:
        cutoff = min_cutoff
    if cutoff > end_ts:
        cutoff = end_ts
    return cutoff


def train_logistic(train_X, train_y, test_X, test_y, x_latest) -> ModelOutput:
    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                    penalty="l1",
                    solver="liblinear",
                    C=LOGREG_L1_C,
                ),
            ),
        ]
    )
    pipe.fit(train_X, train_y)
    p = float(pipe.predict_proba([x_latest])[0, 1])
    brier = None
    ll = None
    if len(test_X) > 0:
        probs = pipe.predict_proba(test_X)[:, 1]
        brier = float(brier_score_loss(test_y, probs))
        ll = float(log_loss(test_y, probs, labels=[0, 1]))
    return ModelOutput(prob=p, train_rows=len(train_X), test_rows=len(test_X), brier=brier, ll=ll, rf_regime=None)


def train_naive_logistic_baseline(train_X, train_y, test_X, test_y, x_latest) -> ModelOutput:
    tx = train_X[:, BASELINE_IDX]
    vx = test_X[:, BASELINE_IDX] if len(test_X) > 0 else np.empty((0, len(BASELINE_IDX)))
    lx = x_latest[BASELINE_IDX]
    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                    penalty="l1",
                    solver="liblinear",
                    C=LOGREG_L1_C,
                ),
            ),
        ]
    )
    pipe.fit(tx, train_y)
    p = float(pipe.predict_proba([lx])[0, 1])
    brier = None
    ll = None
    if len(vx) > 0:
        probs = pipe.predict_proba(vx)[:, 1]
        brier = float(brier_score_loss(test_y, probs))
        ll = float(log_loss(test_y, probs, labels=[0, 1]))
    return ModelOutput(prob=p, train_rows=len(train_X), test_rows=len(test_X), brier=brier, ll=ll, rf_regime="baseline_linear")


def train_rf(train_X, train_y, test_X, test_y, x_latest) -> ModelOutput:
    regime = "small"
    if len(train_X) >= MIN_SAMPLES_DEFAULT_RF:
        regime = "default"
        params = dict(
            n_estimators=400,
            max_depth=8,
            min_samples_leaf=20,
            min_samples_split=50,
            max_features="sqrt",
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )
    else:
        params = dict(
            n_estimators=120,
            max_depth=5,
            min_samples_leaf=5,
            min_samples_split=20,
            max_features="sqrt",
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )
    clf = RandomForestClassifier(**params)
    clf.fit(train_X, train_y)
    p = float(clf.predict_proba([x_latest])[0, 1])
    brier = None
    ll = None
    if len(test_X) > 0:
        probs = clf.predict_proba(test_X)[:, 1]
        brier = float(brier_score_loss(test_y, probs))
        ll = float(log_loss(test_y, probs, labels=[0, 1]))
    return ModelOutput(prob=p, train_rows=len(train_X), test_rows=len(test_X), brier=brier, ll=ll, rf_regime=regime)


def fit_frozen_models(rows: List[Dict], cutoff_utc: Optional[datetime]) -> Dict[str, FrozenModel]:
    if cutoff_utc:
        train_rows = [r for r in rows if r.get("snapshot_minute_utc") and r["snapshot_minute_utc"] < cutoff_utc]
    else:
        split_idx = int(len(rows) * 0.7)
        train_rows = rows[: max(split_idx, 0)]
    X, y = build_supervised(train_rows)
    if len(X) < 20:
        raise RuntimeError(f"insufficient in-sample rows for frozen training: {len(X)}")
    train_X, train_y, test_X, test_y = split_train_test(X, y)
    if len(train_X) < 10:
        raise RuntimeError(f"insufficient frozen train rows: {len(train_X)}")

    log_pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                    penalty="l1",
                    solver="liblinear",
                    C=LOGREG_L1_C,
                ),
            ),
        ]
    )
    log_pipe.fit(train_X, train_y)
    log_brier = None
    log_ll = None
    if len(test_X) > 0:
        probs = log_pipe.predict_proba(test_X)[:, 1]
        log_brier = float(brier_score_loss(test_y, probs))
        log_ll = float(log_loss(test_y, probs, labels=[0, 1]))

    rf_regime = "small"
    if len(train_X) >= MIN_SAMPLES_DEFAULT_RF:
        rf_regime = "default"
        rf_params = dict(
            n_estimators=400,
            max_depth=8,
            min_samples_leaf=20,
            min_samples_split=50,
            max_features="sqrt",
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )
    else:
        rf_params = dict(
            n_estimators=120,
            max_depth=5,
            min_samples_leaf=5,
            min_samples_split=20,
            max_features="sqrt",
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )
    rf = RandomForestClassifier(**rf_params)
    rf.fit(train_X, train_y)
    rf_brier = None
    rf_ll = None
    if len(test_X) > 0:
        probs = rf.predict_proba(test_X)[:, 1]
        rf_brier = float(brier_score_loss(test_y, probs))
        rf_ll = float(log_loss(test_y, probs, labels=[0, 1]))

    base_pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                    penalty="l1",
                    solver="liblinear",
                    C=LOGREG_L1_C,
                ),
            ),
        ]
    )
    base_pipe.fit(train_X[:, BASELINE_IDX], train_y)
    base_brier = None
    base_ll = None
    if len(test_X) > 0:
        base_probs = base_pipe.predict_proba(test_X[:, BASELINE_IDX])[:, 1]
        base_brier = float(brier_score_loss(test_y, base_probs))
        base_ll = float(log_loss(test_y, base_probs, labels=[0, 1]))

    return {
        "naive_logistic_baseline": FrozenModel(
            estimator=base_pipe,
            train_rows=len(train_X),
            test_rows=len(test_X),
            brier=base_brier,
            ll=base_ll,
            rf_regime="baseline_linear",
        ),
        "logistic": FrozenModel(
            estimator=log_pipe,
            train_rows=len(train_X),
            test_rows=len(test_X),
            brier=log_brier,
            ll=log_ll,
            rf_regime=None,
        ),
        "random_forest": FrozenModel(
            estimator=rf,
            train_rows=len(train_X),
            test_rows=len(test_X),
            brier=rf_brier,
            ll=rf_ll,
            rf_regime=rf_regime,
        ),
    }


def train_walk_forward_outputs(rows: List[Dict], now_ts: datetime, x_latest: np.ndarray) -> Dict[str, ModelOutput]:
    lookback_start = now_ts - timedelta(hours=WF_LOOKBACK_HOURS)
    train_rows = [r for r in rows if r.get("snapshot_minute_utc") and (lookback_start <= r["snapshot_minute_utc"] < now_ts)]
    X, y = build_supervised(train_rows)
    if len(X) < WF_MIN_SAMPLES:
        neutral = ModelOutput(prob=0.5, train_rows=len(X), test_rows=0, brier=None, ll=None, rf_regime="wf_cold_start")
        return {
            "walk_forward_logistic": neutral,
            "walk_forward_random_forest": ModelOutput(
                prob=0.5, train_rows=len(X), test_rows=0, brier=None, ll=None, rf_regime="wf_cold_start"
            ),
        }
    train_X, train_y, test_X, test_y = split_train_test(X, y)
    if len(train_X) < 20:
        neutral = ModelOutput(prob=0.5, train_rows=len(train_X), test_rows=len(test_X), brier=None, ll=None, rf_regime="wf_small_train")
        return {
            "walk_forward_logistic": neutral,
            "walk_forward_random_forest": ModelOutput(
                prob=0.5, train_rows=len(train_X), test_rows=len(test_X), brier=None, ll=None, rf_regime="wf_small_train"
            ),
        }
    return {
        "walk_forward_logistic": train_logistic(train_X, train_y, test_X, test_y, x_latest),
        "walk_forward_random_forest": train_rf(train_X, train_y, test_X, test_y, x_latest),
    }


def _parse_orderbook_levels(raw_json: Optional[dict]) -> List[Tuple[float, float]]:
    if not raw_json:
        return []
    candidates = [
        raw_json.get("yes_bids"),
        raw_json.get("yes_bid_levels"),
        raw_json.get("orderbook_yes_bids"),
    ]
    ob = raw_json.get("orderbook")
    if isinstance(ob, dict):
        candidates.extend([ob.get("yes_bids"), ob.get("yes"), ob.get("bids")])
    levels: List[Tuple[float, float]] = []
    for cand in candidates:
        if not isinstance(cand, list):
            continue
        for lv in cand:
            p = None
            q = None
            if isinstance(lv, dict):
                p = (
                    lv.get("price")
                    or lv.get("yes_bid_dollars")
                    or lv.get("yes_bid")
                    or lv.get("p")
                    or lv.get("price_dollars")
                )
                q = (
                    lv.get("size")
                    or lv.get("size_fp")
                    or lv.get("yes_bid_size_fp")
                    or lv.get("qty")
                    or lv.get("quantity")
                    or lv.get("contracts")
                    or lv.get("count")
                    or lv.get("q")
                )
            elif isinstance(lv, (list, tuple)) and len(lv) >= 2:
                p, q = lv[0], lv[1]
            if p is None or q is None:
                continue
            try:
                pf = float(p)
                qf = float(q)
            except Exception:
                continue
            # Some payloads use cent units (0..100) instead of dollars (0..1).
            if pf > 1.0 and pf <= 100.0:
                pf = pf / 100.0
            if pf <= 0 or qf <= 0:
                continue
            levels.append((pf, qf))
        if levels:
            break
    levels.sort(key=lambda x: x[0], reverse=True)
    return levels


def _best_bid_snapshot(cur, ticker: str, as_of_ts: Optional[datetime] = None) -> Dict:
    if as_of_ts is None:
        cur.execute(
            """
            SELECT yes_bid_dollars, yes_bid_size_fp, raw_json
            FROM forward_quotes
            WHERE market_ticker=%s
            ORDER BY snapshot_time_utc DESC
            LIMIT 1
            """,
            (ticker,),
        )
    else:
        cur.execute(
            """
            SELECT yes_bid_dollars, yes_bid_size_fp, raw_json
            FROM forward_quotes
            WHERE market_ticker=%s AND snapshot_time_utc<=%s
            ORDER BY snapshot_time_utc DESC
            LIMIT 1
            """,
            (ticker, as_of_ts.replace(tzinfo=None)),
        )
    r = cur.fetchone() or {}
    raw = r.get("raw_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            try:
                raw = ast.literal_eval(raw)
            except Exception:
                raw = {}
    elif not isinstance(raw, dict):
        raw = {}
    bid = r.get("yes_bid_dollars")
    size = r.get("yes_bid_size_fp")
    levels = _parse_orderbook_levels(raw)
    if bid is not None:
        bid_f = float(bid)
        size_f = float(size) if size is not None else 0.0
        if bid_f > 0:
            if not levels:
                levels = [(bid_f, size_f)]
            elif levels[0][0] != bid_f:
                levels = [(bid_f, size_f)] + levels
    return {"bid": (float(bid) if bid is not None else None), "bid_size": (float(size) if size is not None else None), "levels": levels}


def estimate_sell_proceeds(snapshot: Dict, qty: int) -> Tuple[float, float]:
    if qty <= 0:
        return 0.0, 0.0
    remaining = float(qty)
    levels = list(snapshot.get("levels") or [])
    if levels:
        best_bid = float(levels[0][0])
        if best_bid > 0:
            proceeds = float(qty) * best_bid
            avg_px = proceeds / float(qty)
            return avg_px, proceeds
    bid = snapshot.get("bid")
    if bid is None or float(bid) <= 0:
        return 0.0, 0.0
    proceeds = float(qty) * float(bid)
    avg_px = proceeds / float(qty)
    return avg_px, proceeds


def latest_feature_row(cur) -> Optional[Dict]:
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, event_ticker, {",".join(SOURCE_COLS)}
        FROM model_features_1m
        WHERE model_eligible=1
        ORDER BY snapshot_minute_utc DESC
        LIMIT 1
        """
    )
    return cur.fetchone()


def choose_qty(edge: float) -> int:
    if edge <= EDGE_THRESHOLD:
        return 0
    scaled = int((edge / 0.03) * MAX_QTY)
    return max(1, min(MAX_QTY, scaled))


def impacted_buy_yes_price_dollars(ticker: str, qty: int, fallback_ask: float) -> Tuple[float, int, Dict]:
    # Conservative sim fill model: assume we cross at displayed ask.
    # This prevents optimistic fills from ambiguous orderbook snapshots.
    return fallback_ask, qty, {"mode": "quote_ask_conservative", "ticker": ticker}


def latest_yes_bid(cur, ticker: str, as_of_ts: Optional[datetime] = None) -> Optional[float]:
    snap = _best_bid_snapshot(cur, ticker, as_of_ts=as_of_ts)
    return snap.get("bid")


def close_existing_position(
    cur,
    model_name: str,
    now_row: Dict,
    now_ts: datetime,
    should_close_same_ticker: bool = False,
) -> float:
    cur.execute("SELECT * FROM sim_positions WHERE model_name=%s", (model_name,))
    pos = cur.fetchone()
    if not pos:
        return 0.0

    same_ticker = pos["market_ticker"] == now_row["market_ticker"]
    if same_ticker:
        if not should_close_same_ticker:
            return 0.0
        # Always source exits from forward_quotes snapshot path so bid ladder/size
        # is consistently used for both same-ticker and rollover closes.
        snap = _best_bid_snapshot(cur, pos["market_ticker"], as_of_ts=now_ts)
        exit_px, _ = estimate_sell_proceeds(snap, int(pos["qty_contracts"]))
    else:
        # Ticker rotated; close stale position using its own latest quote.
        stale_snap = _best_bid_snapshot(cur, pos["market_ticker"], as_of_ts=now_ts)
        exit_px, _ = estimate_sell_proceeds(stale_snap, int(pos["qty_contracts"]))

    entry_px = float(pos["entry_price_dollars"])
    qty = int(pos["qty_contracts"])
    pnl = (exit_px - entry_px) * qty
    cur.execute(
        """
        UPDATE sim_trades
        SET closed_at_utc=%s, exit_price_dollars=%s, pnl_dollars=%s, status='closed'
        WHERE id=%s
        """,
        (now_ts.replace(tzinfo=None), exit_px, pnl, pos["trade_id"]),
    )
    cur.execute("DELETE FROM sim_positions WHERE model_name=%s", (model_name,))
    return pnl


def open_new_position(cur, model_name: str, now_row: Dict, now_ts: datetime, prob: float) -> Optional[Dict]:
    cur.execute("SELECT 1 FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
    if cur.fetchone():
        return None
    tte = now_row.get("time_to_expiry_sec")
    if tte is not None and float(tte) <= 60:
        return None
    ask = float(now_row["yes_ask_dollars"] or 0.0)
    if ask <= 0:
        return None
    edge = prob - ask
    qty = choose_qty(edge)
    if qty <= 0 or prob < PRED_THRESHOLD:
        return None
    fill_px, filled_qty, fill_meta = impacted_buy_yes_price_dollars(now_row["market_ticker"], qty, ask)
    if filled_qty <= 0:
        return None
    raw = {"prob_yes": prob, "edge": edge, "qty_requested": qty, "fill": fill_meta}
    cur.execute(
        """
        INSERT INTO sim_trades
        (model_name, market_ticker, opened_at_utc, qty_contracts, entry_price_dollars, status, raw_json)
        VALUES (%s,%s,%s,%s,%s,'open',%s)
        """,
        (
            model_name,
            now_row["market_ticker"],
            now_ts.replace(tzinfo=None),
            filled_qty,
            fill_px,
            json.dumps(raw),
        ),
    )
    trade_id = cur.lastrowid
    cur.execute(
        """
        INSERT INTO sim_positions (model_name, opened_at_utc, market_ticker, qty_contracts, entry_price_dollars, trade_id, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          opened_at_utc=VALUES(opened_at_utc), market_ticker=VALUES(market_ticker),
          qty_contracts=VALUES(qty_contracts), entry_price_dollars=VALUES(entry_price_dollars),
          trade_id=VALUES(trade_id), raw_json=VALUES(raw_json)
        """,
        (
            model_name,
            now_ts.replace(tzinfo=None),
            now_row["market_ticker"],
            filled_qty,
            fill_px,
            trade_id,
            json.dumps(raw),
        ),
    )
    return {"edge": edge, "qty": filled_qty, "entry_price": fill_px}


def upsert_prediction(cur, now_ts: datetime, model_name: str, row: Dict, out: ModelOutput, signal: int, edge: float) -> None:
    vec = build_feature_vector(row)
    feature_payload = {k: float(vec[i]) for i, k in enumerate(FEATURE_COLS)}
    cur.execute(
        """
        INSERT INTO sim_model_predictions_1m
        (snapshot_minute_utc, model_name, market_ticker, prob_yes, signal_yes, edge_est, train_rows, test_rows, brier, logloss, rf_regime, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          market_ticker=VALUES(market_ticker), prob_yes=VALUES(prob_yes), signal_yes=VALUES(signal_yes),
          edge_est=VALUES(edge_est), train_rows=VALUES(train_rows), test_rows=VALUES(test_rows),
          brier=VALUES(brier), logloss=VALUES(logloss), rf_regime=VALUES(rf_regime), raw_json=VALUES(raw_json)
        """,
        (
            now_ts.replace(tzinfo=None),
            model_name,
            row["market_ticker"],
            out.prob,
            signal,
            edge,
            out.train_rows,
            out.test_rows,
            out.brier,
            out.ll,
            out.rf_regime,
            json.dumps({"features": feature_payload}),
        ),
    )


def upsert_equity(cur, now_ts: datetime, model_name: str, realized_pnl: float) -> None:
    cur.execute(
        """
        SELECT cumulative_pnl_dollars, closed_trades_count
        FROM sim_equity_1m
        WHERE model_name=%s
        ORDER BY snapshot_minute_utc DESC
        LIMIT 1
        """,
        (model_name,),
    )
    prev = cur.fetchone()
    prev_cum = float(prev["cumulative_pnl_dollars"]) if prev else 0.0
    cur.execute("SELECT COUNT(*) c, SUM(pnl_dollars > 0) w FROM sim_trades WHERE model_name=%s AND status='closed'", (model_name,))
    agg = cur.fetchone()
    closed_count = int(agg["c"] or 0)
    wins = int(agg["w"] or 0)
    win_rate = (wins / closed_count) if closed_count > 0 else None
    new_cum = prev_cum + realized_pnl
    unrealized = 0.0
    cur.execute("SELECT market_ticker, qty_contracts, entry_price_dollars FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
    pos = cur.fetchone()
    if pos:
        snap = _best_bid_snapshot(cur, pos["market_ticker"], as_of_ts=now_ts)
        mark_px, _ = estimate_sell_proceeds(snap, int(pos["qty_contracts"]))
        unrealized = (float(mark_px) - float(pos["entry_price_dollars"])) * int(pos["qty_contracts"])
    equity_dollars = 100.0 + new_cum + unrealized
    cur.execute(
        """
        INSERT INTO sim_equity_1m
        (snapshot_minute_utc, model_name, realized_pnl_dollars, cumulative_pnl_dollars, closed_trades_count, win_rate, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          realized_pnl_dollars=VALUES(realized_pnl_dollars),
          cumulative_pnl_dollars=VALUES(cumulative_pnl_dollars),
          closed_trades_count=VALUES(closed_trades_count),
          win_rate=VALUES(win_rate),
          raw_json=VALUES(raw_json)
        """,
        (
            now_ts.replace(tzinfo=None),
            model_name,
            realized_pnl,
            new_cum,
            closed_count,
            win_rate,
            json.dumps({"wins": wins, "unrealized_pnl_dollars": unrealized, "equity_dollars": equity_dollars}),
        ),
    )


def run_loop() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        print("simulated trading engine started. Running minute-sharp (+10s).")
        frozen_models: Dict[str, FrozenModel] = {}
        last_processed_minute: Optional[datetime] = None
        while True:
            wake = next_minute_plus_delay(10)
            time.sleep(max(0.0, (wake - utc_now()).total_seconds()))
            now_ts = wake.replace(second=0, microsecond=0)
            try:
                # Pause sim writers while historical recompute is rebuilding tables.
                # Auto-resume when the guard flips back to false.
                if is_sim_recompute_in_progress(cur):
                    if frozen_models:
                        print("sim engine pause: recompute in progress; will reload frozen models on resume")
                    frozen_models = {}
                    last_processed_minute = None
                    continue
                if not frozen_models:
                    rows = load_feature_rows(cur, limit=200000)
                    requested_cutoff = get_live_cutoff_utc(cur)
                    cutoff = choose_effective_cutoff(rows, requested_cutoff)
                    try:
                        frozen_models = fit_frozen_models(rows, cutoff)
                    except Exception as e:
                        print(f"sim engine waiting: frozen-train unavailable ({e})")
                        continue
                    print(
                        "sim frozen models ready: "
                        f"cutoff={cutoff.isoformat() if cutoff else 'none'} "
                        f"log_train={frozen_models['logistic'].train_rows} "
                        f"rf_train={frozen_models['random_forest'].train_rows} "
                        f"rf_regime={frozen_models['random_forest'].rf_regime}"
                    )
                    if cutoff:
                        cur.execute(
                            """
                            INSERT INTO collector_state (state_key, state_value, updated_at_utc)
                            VALUES (%s,%s,%s)
                            ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                            """,
                            (
                                "sim_live_cutoff_utc",
                                json.dumps({"cutoff_utc": cutoff.isoformat()}),
                                utc_now().replace(tzinfo=None),
                            ),
                        )

                latest = latest_feature_row(cur)
                if not latest:
                    print("sim engine waiting: no eligible model_features_1m row")
                    continue

                feature_minute = latest["snapshot_minute_utc"]
                if last_processed_minute and feature_minute <= last_processed_minute:
                    continue

                if not has_target(latest):
                    print(f"sim engine waiting: missing target_btc_price at {now_ts.isoformat()}")
                    continue
                x_latest = np.asarray(build_feature_vector(latest), dtype=float)
                outputs: Dict[str, ModelOutput] = {}
                for model_name in FROZEN_MODELS:
                    fm = frozen_models[model_name]
                    px = x_latest if model_name != "naive_logistic_baseline" else x_latest[list(BASELINE_IDX)]
                    p = float(fm.estimator.predict_proba([px])[0, 1])
                    outputs[model_name] = ModelOutput(
                        prob=p,
                        train_rows=fm.train_rows,
                        test_rows=fm.test_rows,
                        brier=fm.brier,
                        ll=fm.ll,
                        rf_regime=fm.rf_regime,
                    )
                wf_rows = load_feature_rows(cur, limit=12000)
                outputs.update(train_walk_forward_outputs(wf_rows, feature_minute, x_latest))

                for model_name in ALL_MODELS:
                    out = outputs[model_name]
                    signal = 1 if out.prob >= PRED_THRESHOLD else 0
                    edge = out.prob - float(latest.get("yes_ask_dollars") or 0.0)
                    upsert_prediction(cur, now_ts, model_name, latest, out, signal, edge)
                    should_close = (signal == 0) or (edge <= EDGE_THRESHOLD)
                    cur.execute("SELECT 1 FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
                    had_position = cur.fetchone() is not None
                    realized = close_existing_position(
                        cur,
                        model_name,
                        latest,
                        now_ts,
                        should_close_same_ticker=should_close,
                    )
                    cur.execute("SELECT 1 FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
                    has_position_after = cur.fetchone() is not None
                    closed_this_tick = had_position and not has_position_after
                    open_meta = None if closed_this_tick else open_new_position(cur, model_name, latest, now_ts, out.prob)
                    upsert_equity(cur, now_ts, model_name, realized)
                    print(
                        f"sim {model_name} t={now_ts.isoformat()} p={out.prob:.4f} signal={signal} "
                        f"edge={edge:.4f} realized={realized:.4f} open={bool(open_meta)} rf_regime={out.rf_regime}"
                    )

                last_processed_minute = feature_minute
                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES (%s,%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    (
                        "sim_trading_last_snapshot",
                        json.dumps(
                            {
                                "snapshot_minute_utc": now_ts.isoformat(),
                                "feature_snapshot_minute_utc": str(feature_minute),
                                "frozen": True,
                                "train_rows": frozen_models["logistic"].train_rows,
                            }
                        ),
                        utc_now().replace(tzinfo=None),
                    ),
                )
            except Exception as e:
                print(f"sim trading error at {now_ts.isoformat()}: {e}")


if __name__ == "__main__":
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f"[ERROR] simulated trading engine crashed: {e}")
            time.sleep(5)
