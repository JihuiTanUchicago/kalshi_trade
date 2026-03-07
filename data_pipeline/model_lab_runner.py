import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_pipeline.common import get_db_conn, utc_now

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
class Variant:
    variant_id: str
    family: str
    horizon_min: int
    params: Dict


def _f(v) -> float:
    return 0.0 if v is None else float(v)


def _to_dt(v) -> datetime:
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)


def load_feature_rows(cur, limit: int = 300000) -> List[Dict]:
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, yes_ask_dollars, yes_bid_dollars, mid_dollars, {",".join(FEATURE_COLS)}
        FROM model_features_1m
        WHERE model_eligible=1
        ORDER BY snapshot_minute_utc ASC
        LIMIT {limit}
        """
    )
    return cur.fetchall()


def load_cutoff(cur) -> Optional[datetime]:
    cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_live_cutoff_utc' LIMIT 1")
    r = cur.fetchone()
    if not r:
        return None
    sv = r["state_value"]
    try:
        obj = sv if isinstance(sv, dict) else json.loads(sv)
        c = obj.get("cutoff_utc")
        return _to_dt(c) if c else None
    except Exception:
        return None


def build_samples(rows: List[Dict], horizon_min: int) -> List[Dict]:
    out = []
    h = max(1, int(horizon_min))
    for i in range(len(rows) - h):
        a = rows[i]
        b = rows[i + h]
        if a["market_ticker"] != b["market_ticker"]:
            continue
        if a.get("mid_dollars") is None or b.get("mid_dollars") is None:
            continue
        x = [_f(a.get(c)) for c in FEATURE_COLS]
        y = 1 if float(b["mid_dollars"]) > float(a["mid_dollars"]) else 0
        out.append(
            {
                "t": _to_dt(a["snapshot_minute_utc"]),
                "x": x,
                "y": y,
                "ask": _f(a.get("yes_ask_dollars")),
                "future_bid": _f(b.get("yes_bid_dollars")),
            }
        )
    return out


def fit_model(variant: Variant, x_train: np.ndarray, y_train: np.ndarray):
    if variant.family == "logistic":
        c = float(variant.params.get("C", 1.0))
        m = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(max_iter=600, class_weight="balanced", C=c, random_state=42)),
            ]
        )
        m.fit(x_train, y_train)
        return m
    p = dict(variant.params)
    p.setdefault("random_state", 42)
    p.setdefault("n_jobs", -1)
    clf = RandomForestClassifier(**p)
    clf.fit(x_train, y_train)
    return clf


def probs(model, x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return np.empty((0,), dtype=float)
    return model.predict_proba(x)[:, 1]


def pnl_stats(segment: List[Dict], p: np.ndarray, pred_thr: float, edge_thr: float) -> Dict:
    pnl = []
    n_samples = len(segment)
    for i, s in enumerate(segment):
        ask = float(s["ask"])
        bid_f = float(s["future_bid"])
        if ask <= 0 or bid_f <= 0:
            continue
        pr = float(p[i])
        edge = pr - ask
        if pr < pred_thr or edge < edge_thr:
            continue
        qty = max(1, min(10, int((edge / 0.03) * 10)))
        pnl.append((bid_f - ask) * qty)
    n_trades = len(pnl)
    total = float(sum(pnl)) if pnl else 0.0
    avg = (total / n_trades) if n_trades > 0 else 0.0
    win = (sum(1 for x in pnl if x > 0) / n_trades) if n_trades > 0 else None
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in pnl:
        cum += x
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
    sharpe = None
    if n_trades > 1:
        arr = np.asarray(pnl, dtype=float)
        sd = float(arr.std(ddof=1))
        if sd > 1e-12:
            sharpe = float(arr.mean() / sd * math.sqrt(n_trades))
    return {
        "n_samples": n_samples,
        "n_trades": n_trades,
        "trade_rate": (n_trades / n_samples) if n_samples > 0 else 0.0,
        "win_rate": win,
        "total_pnl": total,
        "avg_pnl": avg,
        "pnl_per_trade": avg,
        "max_drawdown": float(max_dd),
        "sharpe_like": sharpe,
    }


def pred_stats(y_true: np.ndarray, p: np.ndarray) -> Dict:
    if len(y_true) == 0:
        return {"brier": None, "logloss": None}
    brier = float(brier_score_loss(y_true, p))
    ll = float(log_loss(y_true, p, labels=[0, 1]))
    return {"brier": brier, "logloss": ll}


def split_segments(samples: List[Dict], cutoff: Optional[datetime]):
    if not samples:
        return [], [], []
    if cutoff is not None:
        pre = [s for s in samples if s["t"] < cutoff]
        live = [s for s in samples if s["t"] >= cutoff]
    else:
        pre = list(samples)
        live = []
    if len(pre) < 20:
        return pre, [], live
    k = max(10, int(len(pre) * 0.3))
    return pre[:-k], pre[-k:], live


def objective(stats: Dict) -> float:
    return float(stats["total_pnl"]) - 0.5 * abs(float(stats["max_drawdown"]))


def row_objective(row: Dict) -> float:
    pnl = float(row.get("total_pnl") or 0.0)
    dd = abs(float(row.get("max_drawdown") or 0.0))
    brier = row.get("brier")
    calib_pen = 0.0 if brier is None else 2.0 * max(0.0, float(brier) - 0.25)
    return pnl - 0.5 * dd - calib_pen


def choose_thresholds(train_seg: List[Dict], p_train: np.ndarray) -> Tuple[float, float]:
    best = (0.55, 0.01, -1e18)
    for pt in (0.52, 0.55, 0.58, 0.60):
        for et in (0.005, 0.01, 0.015, 0.02):
            s = pnl_stats(train_seg, p_train, pt, et)
            score = objective(s)
            if s["n_trades"] < 5:
                score -= 9999.0
            if score > best[2]:
                best = (pt, et, score)
    return float(best[0]), float(best[1])


def variants() -> List[Variant]:
    out = []
    for h in (1, 2, 3):
        out.extend(
            [
                Variant(f"logit_c03_h{h}", "logistic", h, {"C": 0.3}),
                Variant(f"logit_c10_h{h}", "logistic", h, {"C": 1.0}),
                Variant(f"logit_c30_h{h}", "logistic", h, {"C": 3.0}),
                Variant(
                    f"rf_shallow_h{h}",
                    "rf",
                    h,
                    {
                        "n_estimators": 120,
                        "max_depth": 5,
                        "min_samples_leaf": 5,
                        "min_samples_split": 20,
                        "max_features": "sqrt",
                        "class_weight": "balanced_subsample",
                    },
                ),
                Variant(
                    f"rf_default_h{h}",
                    "rf",
                    h,
                    {
                        "n_estimators": 400,
                        "max_depth": 8,
                        "min_samples_leaf": 20,
                        "min_samples_split": 50,
                        "max_features": "sqrt",
                        "class_weight": "balanced_subsample",
                    },
                ),
            ]
        )
    return out


def run_once() -> None:
    conn = get_db_conn()
    now = utc_now().replace(tzinfo=None)
    with conn.cursor() as cur:
        rows = load_feature_rows(cur)
        cutoff = load_cutoff(cur)
        cutoff_sql = cutoff.replace(tzinfo=None) if cutoff else None
        cur.execute(
            """
            INSERT INTO sim_model_lab_runs (run_time_utc, cutoff_utc, sample_rows, notes_json)
            VALUES (%s,%s,%s,%s)
            """,
            (now, cutoff_sql, len(rows), json.dumps({"variant_count": len(variants())})),
        )
        run_id = int(cur.lastrowid)

        for v in variants():
            s_all = build_samples(rows, v.horizon_min)
            s_train, s_oos, s_live = split_segments(s_all, cutoff)
            if len(s_train) < 25:
                continue
            x_train = np.asarray([s["x"] for s in s_train], dtype=float)
            y_train = np.asarray([s["y"] for s in s_train], dtype=int)
            model = fit_model(v, x_train, y_train)

            def eval_seg(seg: List[Dict], name: str, pred_thr: float, edge_thr: float):
                if not seg:
                    return
                x = np.asarray([s["x"] for s in seg], dtype=float)
                y = np.asarray([s["y"] for s in seg], dtype=int)
                p = probs(model, x)
                ps = pred_stats(y, p)
                ts = pnl_stats(seg, p, pred_thr, edge_thr)
                cur.execute(
                    """
                    INSERT INTO sim_model_lab_results
                    (run_id,variant_id,model_family,horizon_min,pred_threshold,edge_threshold,segment,n_samples,n_trades,trade_rate,win_rate,total_pnl,avg_pnl,pnl_per_trade,brier,logloss,max_drawdown,sharpe_like,meta_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        run_id,
                        v.variant_id,
                        v.family,
                        v.horizon_min,
                        pred_thr,
                        edge_thr,
                        name,
                        ts["n_samples"],
                        ts["n_trades"],
                        ts["trade_rate"],
                        ts["win_rate"],
                        ts["total_pnl"],
                        ts["avg_pnl"],
                        ts["pnl_per_trade"],
                        ps["brier"],
                        ps["logloss"],
                        ts["max_drawdown"],
                        ts["sharpe_like"],
                        json.dumps({"params": v.params}),
                    ),
                )

            p_train = probs(model, x_train)
            pred_thr, edge_thr = choose_thresholds(s_train, p_train)
            eval_seg(s_train, "in_sample", pred_thr, edge_thr)
            eval_seg(s_oos, "out_of_sample", pred_thr, edge_thr)
            eval_seg(s_live, "live_forward", pred_thr, edge_thr)

        cur.execute(
            """
            INSERT INTO collector_state (state_key,state_value,updated_at_utc)
            VALUES ('sim_model_lab_last_run',%s,%s)
            ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
            """,
            (json.dumps({"run_id": run_id, "run_time_utc": now.isoformat()}), now),
        )

        # Champion promotion rule: prefer live_forward, fallback out_of_sample.
        min_trades = int(os.getenv("MODEL_LAB_CHAMPION_MIN_TRADES", "6"))
        cur.execute(
            """
            SELECT variant_id, model_family, horizon_min, pred_threshold, edge_threshold, segment,
                   n_trades, total_pnl, win_rate, brier, logloss, max_drawdown, sharpe_like
            FROM sim_model_lab_results
            WHERE run_id=%s
            ORDER BY
              CASE segment WHEN 'live_forward' THEN 1 WHEN 'out_of_sample' THEN 2 ELSE 3 END,
              total_pnl DESC
            """,
            (run_id,),
        )
        rows = cur.fetchall()
        pool = [r for r in rows if r["segment"] == "live_forward" and int(r["n_trades"] or 0) >= min_trades]
        if not pool:
            pool = [r for r in rows if r["segment"] == "out_of_sample" and int(r["n_trades"] or 0) >= min_trades]
        champ = None
        if pool:
            pool.sort(key=lambda r: row_objective(r), reverse=True)
            champ = dict(pool[0])
            champ["objective"] = row_objective(champ)
            cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_model_lab_champion' LIMIT 1")
            prev = cur.fetchone()
            prev_obj = None
            if prev:
                try:
                    pj = prev["state_value"] if isinstance(prev["state_value"], dict) else json.loads(prev["state_value"])
                    prev_obj = float(pj.get("objective"))
                except Exception:
                    prev_obj = None
            margin = float(os.getenv("MODEL_LAB_PROMOTE_MARGIN", "0.25"))
            promote = (prev_obj is None) or (champ["objective"] >= (prev_obj + margin))
            champ_payload = {
                "run_id": run_id,
                "run_time_utc": now.isoformat(),
                "promoted": bool(promote),
                "min_trades": min_trades,
                "margin": margin,
                "variant_id": champ["variant_id"],
                "model_family": champ["model_family"],
                "horizon_min": int(champ["horizon_min"]),
                "pred_threshold": float(champ["pred_threshold"]),
                "edge_threshold": float(champ["edge_threshold"]),
                "segment": champ["segment"],
                "n_trades": int(champ["n_trades"]),
                "total_pnl": float(champ["total_pnl"] or 0.0),
                "win_rate": float(champ["win_rate"]) if champ["win_rate"] is not None else None,
                "brier": float(champ["brier"]) if champ["brier"] is not None else None,
                "logloss": float(champ["logloss"]) if champ["logloss"] is not None else None,
                "max_drawdown": float(champ["max_drawdown"] or 0.0),
                "sharpe_like": float(champ["sharpe_like"]) if champ["sharpe_like"] is not None else None,
                "objective": float(champ["objective"]),
            }
            cur.execute(
                """
                INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                VALUES ('sim_model_lab_champion',%s,%s)
                ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                """,
                (json.dumps(champ_payload), now),
            )
    conn.close()
    print(f"model lab run complete: run_id={run_id}")


if __name__ == "__main__":
    run_once()
