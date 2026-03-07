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

MODELS = ("logistic", "random_forest")
MIN_SAMPLES_DEFAULT_RF = 1000
PRED_THRESHOLD = 0.55
EDGE_THRESHOLD = 0.01
MAX_QTY = 10

FEATURE_COLS = [
    "yes_bid_dollars",
    "yes_ask_dollars",
    "spread_dollars",
    "mid_dollars",
    "orderbook_imbalance",
    "mid_ret_1m",
    "mid_ret_3m",
    "trades_last_60s_count",
    "trades_last_60s_volume_fp",
    "trades_last_60s_vwap_yes",
    "quote_change_events_60s",
    "time_to_expiry_sec",
    "cb_ret_1m",
    "cb_ret_3m",
    "cb_ret_5m",
    "cb_vol_5m",
]


@dataclass
class ModelOutput:
    prob: float
    train_rows: int
    test_rows: int
    brier: Optional[float]
    ll: Optional[float]
    rf_regime: Optional[str]


def next_minute_plus_delay(delay_seconds: int = 10) -> datetime:
    now = utc_now()
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1, seconds=delay_seconds)


def coalesce_float(v) -> float:
    if v is None:
        return 0.0
    return float(v)


def load_feature_rows(cur, limit: int = 8000) -> List[Dict]:
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, event_ticker, {",".join(FEATURE_COLS)}
        FROM model_features_1m
        WHERE model_eligible=1
        ORDER BY snapshot_minute_utc ASC
        LIMIT {limit}
        """
    )
    return cur.fetchall()


def build_supervised(rows: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
    X = []
    y = []
    for i in range(len(rows) - 1):
        r = rows[i]
        nxt = rows[i + 1]
        if r["market_ticker"] != nxt["market_ticker"]:
            continue
        if r.get("mid_dollars") is None or nxt.get("mid_dollars") is None:
            continue
        x = [coalesce_float(r.get(c)) for c in FEATURE_COLS]
        target = 1 if float(nxt["mid_dollars"]) > float(r["mid_dollars"]) else 0
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
    return X[:-test_n], y[:-test_n], X[-test_n:], y[-test_n:]


def train_logistic(train_X, train_y, test_X, test_y, x_latest) -> ModelOutput:
    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=500, class_weight="balanced", random_state=42)),
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


def choose_qty(edge: float) -> int:
    if edge <= EDGE_THRESHOLD:
        return 0
    scaled = int((edge / 0.03) * MAX_QTY)
    return max(1, min(MAX_QTY, scaled))


def impacted_buy_yes_price_dollars(ticker: str, qty: int, fallback_ask: float) -> Tuple[float, int, Dict]:
    # Conservative sim fill model: assume we cross at displayed ask.
    # This prevents optimistic fills from ambiguous orderbook snapshots.
    return fallback_ask, qty, {"mode": "quote_ask_conservative", "ticker": ticker}


def close_existing_position(cur, model_name: str, now_row: Dict, now_ts: datetime) -> float:
    cur.execute("SELECT * FROM sim_positions WHERE model_name=%s", (model_name,))
    pos = cur.fetchone()
    if not pos:
        return 0.0
    if pos["market_ticker"] != now_row["market_ticker"]:
        return 0.0
    exit_px = float(now_row["yes_bid_dollars"] or now_row["mid_dollars"] or 0.0)
    if exit_px <= 0:
        return 0.0
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
            json.dumps({"features": {k: float(row[k]) if row[k] is not None else None for k in FEATURE_COLS}}),
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
            prev_cum + realized_pnl,
            closed_count,
            win_rate,
            json.dumps({"wins": wins}),
        ),
    )


def run_loop() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        print("simulated trading engine started. Running minute-sharp (+10s).")
        while True:
            wake = next_minute_plus_delay(10)
            time.sleep(max(0.0, (wake - utc_now()).total_seconds()))
            now_ts = wake.replace(second=0, microsecond=0)
            try:
                rows = load_feature_rows(cur)
                X, y = build_supervised(rows)
                if len(X) < 20:
                    print(f"sim engine waiting: insufficient rows={len(X)}")
                    continue
                train_X, train_y, test_X, test_y = split_train_test(X, y)
                if len(train_X) < 10:
                    print(f"sim engine waiting: insufficient train rows={len(train_X)}")
                    continue

                latest = rows[-1]
                x_latest = np.asarray([coalesce_float(latest.get(c)) for c in FEATURE_COLS], dtype=float)

                outputs = {
                    "logistic": train_logistic(train_X, train_y, test_X, test_y, x_latest),
                    "random_forest": train_rf(train_X, train_y, test_X, test_y, x_latest),
                }

                for model_name in MODELS:
                    out = outputs[model_name]
                    signal = 1 if out.prob >= PRED_THRESHOLD else 0
                    edge = out.prob - float(latest.get("yes_ask_dollars") or 0.0)
                    upsert_prediction(cur, now_ts, model_name, latest, out, signal, edge)
                    realized = close_existing_position(cur, model_name, latest, now_ts)
                    open_meta = open_new_position(cur, model_name, latest, now_ts, out.prob)
                    upsert_equity(cur, now_ts, model_name, realized)
                    print(
                        f"sim {model_name} t={now_ts.isoformat()} p={out.prob:.4f} signal={signal} "
                        f"edge={edge:.4f} realized={realized:.4f} open={bool(open_meta)} rf_regime={out.rf_regime}"
                    )

                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES (%s,%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    (
                        "sim_trading_last_snapshot",
                        json.dumps({"snapshot_minute_utc": now_ts.isoformat(), "rows": len(X), "train_rows": len(train_X)}),
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
