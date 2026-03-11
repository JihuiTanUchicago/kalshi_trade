import argparse
import json
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
try:
    import optuna
except Exception:
    optuna = None
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.modeling_features import BASELINE_FEATURE_COLS, FEATURE_COLS, SOURCE_COLS, build_feature_vector, has_target
from data_pipeline.simulated_trading_engine import choose_effective_cutoff, get_live_cutoff_utc


TOPK_BY_MODEL = {
    "naive_logistic_baseline": 10,
    "logistic": 14,
    "random_forest": 16,
}


@dataclass
class TrialResult:
    model_name: str
    params: Dict
    selected_features: List[str]
    objective_pnl: float
    metrics: Dict
    estimator: object


def load_feature_rows(cur, limit: int = 200000) -> List[Dict]:
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
    x, y = [], []
    for i in range(len(rows) - 1):
        r = rows[i]
        nxt = rows[i + 1]
        if r["market_ticker"] != nxt["market_ticker"]:
            continue
        if not has_target(r) or not has_target(nxt):
            continue
        if r.get("mid_dollars") is None or nxt.get("mid_dollars") is None:
            continue
        x.append(build_feature_vector(r))
        y.append(1 if float(nxt["mid_dollars"]) > float(r["mid_dollars"]) else 0)
    if not x:
        return np.empty((0, len(FEATURE_COLS))), np.empty((0,))
    return np.asarray(x, dtype=float), np.asarray(y, dtype=int)


def build_eval_labels(rows: List[Dict]) -> Dict[Tuple[datetime, str], int]:
    labels = {}
    for i in range(len(rows) - 1):
        r = rows[i]
        nxt = rows[i + 1]
        if r["market_ticker"] != nxt["market_ticker"]:
            continue
        if r.get("mid_dollars") is None or nxt.get("mid_dollars") is None:
            continue
        labels[(r["snapshot_minute_utc"], r["market_ticker"])] = 1 if float(nxt["mid_dollars"]) > float(r["mid_dollars"]) else 0
    return labels


def feature_idx(selected_features: Sequence[str]) -> List[int]:
    idx = []
    for f in selected_features:
        if f in FEATURE_COLS:
            idx.append(FEATURE_COLS.index(f))
    return idx


def choose_qty(edge: float, max_qty: int = 10) -> int:
    if edge <= 0:
        return 0
    scaled = int((edge / 0.03) * max_qty)
    return max(1, min(max_qty, scaled))


def simulate_eval(
    rows_eval: List[Dict],
    estimator,
    selected_features: Sequence[str],
    signal_threshold: float,
    edge_threshold: float,
) -> Dict:
    idx = feature_idx(selected_features)
    if not idx:
        return {"total_pnl": 0.0, "closed_trades": 0, "win_rate": None, "equity": 100.0}

    open_pos = None
    realized = 0.0
    closed = 0
    wins = 0
    probs = []
    minute_eq = []

    for row in rows_eval:
        if not has_target(row):
            continue
        ask = float(row.get("yes_ask_dollars") or 0.0)
        bid = float(row.get("yes_bid_dollars") or 0.0)
        ticker = row.get("market_ticker")
        if not ticker or ask <= 0:
            continue
        x = np.asarray(build_feature_vector(row), dtype=float)[idx]
        prob = float(estimator.predict_proba([x])[0, 1])
        edge = prob - ask
        signal = (prob >= signal_threshold) and (edge > edge_threshold)
        probs.append((row["snapshot_minute_utc"], ticker, prob))

        closed_this_tick = False
        if open_pos is not None:
            should_close = (open_pos["ticker"] != ticker) or (not signal)
            if should_close:
                exit_px = max(0.0, bid)
                pnl = (exit_px - open_pos["entry"]) * open_pos["qty"]
                realized += pnl
                closed += 1
                if pnl > 0:
                    wins += 1
                open_pos = None
                closed_this_tick = True

        if open_pos is None and (not closed_this_tick) and signal:
            qty = choose_qty(edge, max_qty=10)
            if qty > 0:
                open_pos = {"ticker": ticker, "qty": qty, "entry": ask}

        unrealized = 0.0
        if open_pos is not None and open_pos["ticker"] == ticker:
            unrealized = (max(0.0, bid) - open_pos["entry"]) * open_pos["qty"]
        minute_eq.append(100.0 + realized + unrealized)

    if open_pos is not None and rows_eval:
        tail_bid = float(rows_eval[-1].get("yes_bid_dollars") or 0.0)
        pnl = (max(0.0, tail_bid) - open_pos["entry"]) * open_pos["qty"]
        realized += pnl
        closed += 1
        if pnl > 0:
            wins += 1

    return {
        "total_pnl": float(realized),
        "closed_trades": int(closed),
        "win_rate": (wins / closed) if closed > 0 else None,
        "equity": 100.0 + float(realized),
        "equity_path": minute_eq,
        "preds": probs,
    }


def _safe_logloss(y_true: np.ndarray, p: np.ndarray) -> Optional[float]:
    if len(y_true) == 0:
        return None
    try:
        return float(log_loss(y_true, p, labels=[0, 1]))
    except Exception:
        return None


def build_estimator(model_name: str, params: Dict):
    if model_name in ("naive_logistic_baseline", "logistic"):
        return Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=800,
                        C=float(params["C"]),
                        penalty=params["penalty"],
                        solver=params["solver"],
                        class_weight=params["class_weight"],
                        random_state=42,
                    ),
                ),
            ]
        )
    return RandomForestClassifier(
        n_estimators=int(params["n_estimators"]),
        max_depth=(None if params["max_depth"] is None else int(params["max_depth"])),
        min_samples_leaf=int(params["min_samples_leaf"]),
        min_samples_split=int(params["min_samples_split"]),
        max_features=params["max_features"],
        class_weight=params["class_weight"],
        random_state=42,
        n_jobs=-1,
    )


def sample_params(model_name: str, rng: random.Random) -> Dict:
    if model_name in ("naive_logistic_baseline", "logistic"):
        penalty = rng.choice(["l1", "l2"])
        solver = "liblinear" if penalty == "l1" else rng.choice(["liblinear", "lbfgs"])
        c = 10 ** rng.uniform(-2, 1.2)
        return {
            "C": c,
            "penalty": penalty,
            "solver": solver,
            "class_weight": rng.choice([None, "balanced"]),
            "signal_threshold": rng.uniform(0.52, 0.72),
            "edge_threshold": rng.uniform(0.0, 0.03),
        }
    max_feat = rng.choice(["sqrt", "log2", round(rng.uniform(0.3, 1.0), 2)])
    return {
        "n_estimators": rng.randint(80, 220),
        "max_depth": rng.choice([4, 5, 6, 7, 8, 10]),
        "min_samples_leaf": rng.randint(3, 24),
        "min_samples_split": rng.randint(6, 50),
        "max_features": max_feat,
        "class_weight": rng.choice([None, "balanced", "balanced_subsample"]),
        "signal_threshold": rng.uniform(0.52, 0.72),
        "edge_threshold": rng.uniform(0.0, 0.03),
    }


def suggest_params_optuna(model_name: str, trial) -> Dict:
    if model_name in ("naive_logistic_baseline", "logistic"):
        penalty = trial.suggest_categorical("penalty", ["l1", "l2"])
        solver = "liblinear" if penalty == "l1" else trial.suggest_categorical("solver", ["liblinear", "lbfgs"])
        class_weight_tok = trial.suggest_categorical("class_weight", ["none", "balanced"])
        return {
            "C": trial.suggest_float("C", 1e-2, 16.0, log=True),
            "penalty": penalty,
            "solver": solver,
            "class_weight": None if class_weight_tok == "none" else class_weight_tok,
            "signal_threshold": trial.suggest_float("signal_threshold", 0.52, 0.72),
            "edge_threshold": trial.suggest_float("edge_threshold", 0.0, 0.03),
        }
    class_weight_tok = trial.suggest_categorical("class_weight", ["none", "balanced", "balanced_subsample"])
    max_features_tok = trial.suggest_categorical("max_features_mode", ["sqrt", "log2", "float"])
    if max_features_tok == "float":
        max_features = round(float(trial.suggest_float("max_features_float", 0.3, 1.0)), 2)
    else:
        max_features = max_features_tok
    return {
        "n_estimators": int(trial.suggest_int("n_estimators", 80, 220)),
        "max_depth": int(trial.suggest_int("max_depth", 4, 10)),
        "min_samples_leaf": int(trial.suggest_int("min_samples_leaf", 3, 24)),
        "min_samples_split": int(trial.suggest_int("min_samples_split", 6, 50)),
        "max_features": max_features,
        "class_weight": None if class_weight_tok == "none" else class_weight_tok,
        "signal_threshold": trial.suggest_float("signal_threshold", 0.52, 0.72),
        "edge_threshold": trial.suggest_float("edge_threshold", 0.0, 0.03),
    }


def estimate_shapley_mc(estimator, x_ref: np.ndarray, x_samples: np.ndarray, n_perm: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n_features = x_ref.shape[0]
    phi = np.zeros(n_features, dtype=float)

    def pred(v: np.ndarray) -> float:
        return float(estimator.predict_proba([v])[0, 1])

    for x in x_samples:
        for _ in range(n_perm):
            perm = rng.permutation(n_features)
            cur = x_ref.copy()
            prev_pred = pred(cur)
            for j in perm:
                cur[j] = x[j]
                new_pred = pred(cur)
                phi[j] += (new_pred - prev_pred)
                prev_pred = new_pred

    denom = float(max(1, len(x_samples) * n_perm))
    return phi / denom


def compute_importance(
    estimator,
    x_train: np.ndarray,
    selected_features: Sequence[str],
    seed: int = 42,
    shap_samples: int = 120,
    shap_perms: int = 16,
) -> List[Dict]:
    if len(x_train) == 0:
        return []
    sample_n = min(max(20, int(shap_samples)), len(x_train))
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(x_train), size=sample_n, replace=False)
    x_samples = x_train[idx]
    x_ref = np.mean(x_train, axis=0)
    phi = estimate_shapley_mc(estimator, x_ref, x_samples, n_perm=max(4, int(shap_perms)), seed=seed)
    rows = []
    for i, f in enumerate(selected_features):
        rows.append(
            {
                "feature_name": f,
                "importance_abs_mean": abs(float(phi[i])),
                "importance_signed_mean": float(phi[i]),
                "method": "shapley_mc",
            }
        )
    rows.sort(key=lambda r: r["importance_abs_mean"], reverse=True)
    for i, r in enumerate(rows, start=1):
        r["rank_order"] = i
    return rows


def fit_and_eval(
    model_name: str,
    train_rows: List[Dict],
    eval_rows: List[Dict],
    selected_features: Sequence[str],
    params: Dict,
) -> TrialResult:
    x_train, y_train = build_supervised(train_rows)
    fidx = feature_idx(selected_features)
    if len(x_train) < 40 or not fidx:
        raise RuntimeError("insufficient training rows for tuning")
    x_train_sub = x_train[:, fidx]
    est = build_estimator(model_name, params)
    est.fit(x_train_sub, y_train)

    labels = build_eval_labels(eval_rows)
    sim = simulate_eval(
        eval_rows,
        est,
        selected_features,
        signal_threshold=float(params["signal_threshold"]),
        edge_threshold=float(params["edge_threshold"]),
    )

    y_eval = []
    p_eval = []
    for ts, ticker, p in sim["preds"]:
        y = labels.get((ts, ticker))
        if y is None:
            continue
        y_eval.append(y)
        p_eval.append(p)
    y_eval_np = np.asarray(y_eval, dtype=int)
    p_eval_np = np.asarray(p_eval, dtype=float)
    brier = float(brier_score_loss(y_eval_np, p_eval_np)) if len(y_eval_np) > 0 else None
    ll = _safe_logloss(y_eval_np, p_eval_np)

    metrics = {
        "brier": brier,
        "logloss": ll,
        "oos_total_pnl": sim["total_pnl"],
        "oos_equity": sim["equity"],
        "oos_closed_trades": sim["closed_trades"],
        "oos_win_rate": sim["win_rate"],
        "signal_threshold": float(params["signal_threshold"]),
        "edge_threshold": float(params["edge_threshold"]),
    }
    return TrialResult(
        model_name=model_name,
        params=params,
        selected_features=list(selected_features),
        objective_pnl=float(sim["total_pnl"]),
        metrics=metrics,
        estimator=est,
    )


def run_search(
    model_name: str,
    train_rows: List[Dict],
    eval_rows: List[Dict],
    selected_features: Sequence[str],
    trials: int,
    seed: int,
    optimizer: str = "optuna",
) -> TrialResult:
    if optimizer == "optuna" and optuna is not None:
        def objective(trial):
            params = suggest_params_optuna(model_name, trial)
            try:
                r = fit_and_eval(model_name, train_rows, eval_rows, selected_features, params)
                trial.set_user_attr("params", params)
                return float(r.objective_pnl)
            except Exception:
                return -1e12

        sampler = optuna.samplers.TPESampler(seed=seed)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=max(1, int(trials)))
        best_params = study.best_trial.user_attrs.get("params") if study.best_trial else None
        if not best_params:
            best_params = suggest_params_optuna(model_name, study.best_trial)
        return fit_and_eval(model_name, train_rows, eval_rows, selected_features, best_params)

    rng = random.Random(seed)
    best = None
    for _ in range(trials):
        params = sample_params(model_name, rng)
        try:
            r = fit_and_eval(model_name, train_rows, eval_rows, selected_features, params)
        except Exception:
            continue
        if best is None or r.objective_pnl > best.objective_pnl:
            best = r
    if best is None:
        raise RuntimeError(f"no successful trials for {model_name}")
    return best


def save_run(cur, run: TrialResult, stage: str, n_train: int, n_eval: int, notes: str = "") -> int:
    cur.execute(
        """
        INSERT INTO model_research_runs
        (created_at_utc, model_name, stage, objective_pnl_dollars, n_train, n_eval, params_json, selected_features_json, metrics_json, status, notes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'success',%s)
        """,
        (
            utc_now().replace(tzinfo=None),
            run.model_name,
            stage,
            run.objective_pnl,
            n_train,
            n_eval,
            json.dumps(run.params),
            json.dumps(run.selected_features),
            json.dumps(run.metrics),
            notes,
        ),
    )
    return int(cur.lastrowid)


def save_importance(cur, run_id: int, model_name: str, imp_rows: List[Dict]) -> None:
    now = utc_now().replace(tzinfo=None)
    for r in imp_rows:
        cur.execute(
            """
            INSERT INTO model_research_feature_importance
            (run_id, model_name, feature_name, importance_abs_mean, importance_signed_mean, rank_order, method, created_at_utc)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                run_id,
                model_name,
                r["feature_name"],
                float(r["importance_abs_mean"]),
                float(r["importance_signed_mean"]),
                int(r["rank_order"]),
                r["method"],
                now,
            ),
        )


def main():
    ap = argparse.ArgumentParser(description="Hyperparameter tuning + Shapley-style feature selection for sim models.")
    ap.add_argument("--trials", type=int, default=32)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=200000)
    ap.add_argument("--shap-samples", type=int, default=120)
    ap.add_argument("--shap-perms", type=int, default=16)
    ap.add_argument("--optimizer", type=str, default="optuna", choices=["optuna", "random"])
    args = ap.parse_args()

    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = load_feature_rows(cur, limit=args.limit)
        if len(rows) < 300:
            raise RuntimeError(f"insufficient rows for research: {len(rows)}")

        cutoff = choose_effective_cutoff(rows, get_live_cutoff_utc(cur))
        if cutoff is None:
            raise RuntimeError("unable to resolve cutoff for research")
        train_rows = [r for r in rows if r.get("snapshot_minute_utc") and r["snapshot_minute_utc"] < cutoff]
        eval_rows = [r for r in rows if r.get("snapshot_minute_utc") and r["snapshot_minute_utc"] >= cutoff]
        if len(train_rows) < 150 or len(eval_rows) < 120:
            raise RuntimeError(f"insufficient split sizes train={len(train_rows)} eval={len(eval_rows)} cutoff={cutoff}")

        model_order = ["naive_logistic_baseline", "logistic", "random_forest"]
        default_features = {
            "naive_logistic_baseline": list(BASELINE_FEATURE_COLS),
            "logistic": list(FEATURE_COLS),
            "random_forest": list(FEATURE_COLS),
        }
        outputs = []

        for i, model_name in enumerate(model_order):
            base_feats = default_features[model_name]
            stage1 = run_search(
                model_name,
                train_rows,
                eval_rows,
                base_feats,
                trials=args.trials,
                seed=args.seed + 100 * i,
                optimizer=args.optimizer,
            )
            x_train, _ = build_supervised(train_rows)
            x_train_sub = x_train[:, feature_idx(stage1.selected_features)]
            imp = compute_importance(
                stage1.estimator,
                x_train_sub,
                stage1.selected_features,
                seed=args.seed + i,
                shap_samples=args.shap_samples,
                shap_perms=args.shap_perms,
            )
            topk = TOPK_BY_MODEL.get(model_name, min(12, len(base_feats)))
            selected = [r["feature_name"] for r in imp[:topk]]
            if len(selected) < 5:
                selected = base_feats
            stage2 = run_search(
                model_name,
                train_rows,
                eval_rows,
                selected,
                trials=max(6, args.trials // 2),
                seed=args.seed + 500 * i,
                optimizer=args.optimizer,
            )
            x_train2_sub = x_train[:, feature_idx(stage2.selected_features)]
            imp2 = compute_importance(
                stage2.estimator,
                x_train2_sub,
                stage2.selected_features,
                seed=args.seed + 2000 + i,
                shap_samples=args.shap_samples,
                shap_perms=args.shap_perms,
            )

            rid1 = save_run(cur, stage1, "full", n_train=len(train_rows), n_eval=len(eval_rows), notes=f"cutoff={cutoff.isoformat()}")
            save_importance(cur, rid1, model_name, imp)
            rid2 = save_run(cur, stage2, "selected", n_train=len(train_rows), n_eval=len(eval_rows), notes=f"cutoff={cutoff.isoformat()}")
            save_importance(cur, rid2, model_name, imp2)

            outputs.append(
                {
                    "model_name": model_name,
                    "best_stage_full_run_id": rid1,
                    "best_stage_selected_run_id": rid2,
                    "full_oos_pnl": stage1.objective_pnl,
                    "selected_oos_pnl": stage2.objective_pnl,
                    "selected_features": stage2.selected_features,
                }
            )

        cur.execute(
            """
            INSERT INTO collector_state (state_key,state_value,updated_at_utc)
            VALUES (%s,%s,%s)
            ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
            """,
            (
                "model_research_last_run",
                json.dumps(
                    {
                        "ran_at_utc": utc_now().isoformat(),
                        "cutoff_utc": cutoff.isoformat(),
                        "train_rows": len(train_rows),
                        "eval_rows": len(eval_rows),
                        "trials": args.trials,
                        "optimizer": args.optimizer,
                        "optuna_available": optuna is not None,
                        "models": outputs,
                    }
                ),
                utc_now().replace(tzinfo=None),
            ),
        )

    conn.close()
    print(json.dumps({"ok": True, "models": outputs}, indent=2))


if __name__ == "__main__":
    main()
