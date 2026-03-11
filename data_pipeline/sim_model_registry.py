import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_pipeline.modeling_features import FEATURE_COLS, build_feature_vector, has_target

BUILTIN_MODELS: Dict[str, Dict] = {
    "naive_logistic_baseline": {
        "model_name": "naive_logistic_baseline",
        "family": "builtin",
        "algo": "logistic",
        "mode": "frozen",
        "is_visible": True,
        "is_active": True,
        "status": "ready",
    },
    "logistic": {
        "model_name": "logistic",
        "family": "builtin",
        "algo": "logistic",
        "mode": "frozen",
        "is_visible": True,
        "is_active": True,
        "status": "ready",
    },
    "random_forest": {
        "model_name": "random_forest",
        "family": "builtin",
        "algo": "random_forest",
        "mode": "frozen",
        "is_visible": True,
        "is_active": True,
        "status": "ready",
    },
    "walk_forward_logistic": {
        "model_name": "walk_forward_logistic",
        "family": "builtin",
        "algo": "logistic",
        "mode": "walk_forward",
        "is_visible": True,
        "is_active": True,
        "status": "ready",
    },
    "walk_forward_random_forest": {
        "model_name": "walk_forward_random_forest",
        "family": "builtin",
        "algo": "random_forest",
        "mode": "walk_forward",
        "is_visible": True,
        "is_active": True,
        "status": "ready",
    },
}


@dataclass
class CustomFrozenModel:
    estimator: object
    feature_idx: Tuple[int, ...]
    train_rows: int
    test_rows: int
    brier: Optional[float]
    ll: Optional[float]
    rf_regime: Optional[str]


def slugify_model_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", (name or "").strip().lower()).strip("_")
    if not s:
        raise ValueError("model_name is required")
    if len(s) > 32:
        raise ValueError("model_name must be 32 chars or fewer")
    if s in BUILTIN_MODELS:
        raise ValueError("model_name conflicts with a built-in model")
    return s


def default_hyperparams(algo: str) -> Dict:
    if algo == "logistic":
        return {
            "penalty": "l1",
            "C": 0.5,
            "class_weight": "balanced",
            "max_iter": 1000,
            "solver": "liblinear",
        }
    if algo == "random_forest":
        return {
            "n_estimators": 300,
            "max_depth": 8,
            "min_samples_leaf": 10,
            "min_samples_split": 30,
            "max_features": "sqrt",
            "class_weight": "balanced_subsample",
            "random_state": 42,
            "n_jobs": -1,
        }
    raise ValueError(f"unsupported algo: {algo}")


def normalize_custom_model_payload(payload: Dict) -> Dict:
    algo = str(payload.get("algo") or "").strip()
    if algo not in ("logistic", "random_forest"):
        raise ValueError("algo must be logistic or random_forest")
    model_name = slugify_model_name(str(payload.get("model_name") or ""))
    feature_cols = payload.get("feature_cols") or []
    if isinstance(feature_cols, str):
        feature_cols = [x.strip() for x in feature_cols.split(",") if x.strip()]
    feature_cols = [str(x) for x in feature_cols if str(x)]
    if not feature_cols:
        raise ValueError("at least one feature is required")
    bad = [f for f in feature_cols if f not in FEATURE_COLS]
    if bad:
        raise ValueError(f"unknown features: {', '.join(sorted(bad))}")
    hyperparams = default_hyperparams(algo)
    raw_hyper = payload.get("hyperparams") or {}
    if isinstance(raw_hyper, str):
        raw_hyper = json.loads(raw_hyper or "{}")
    if not isinstance(raw_hyper, dict):
        raise ValueError("hyperparams must be a JSON object")
    hyperparams.update(raw_hyper)
    return {
        "model_name": model_name,
        "family": "custom",
        "algo": algo,
        "mode": "frozen",
        "feature_cols": feature_cols,
        "hyperparams": hyperparams,
        "is_active": True,
        "is_visible": True,
        "status": "pending",
        "notes": str(payload.get("notes") or ""),
    }


def _build_supervised(rows: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
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


def _split_train_test(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(X)
    if n < 30:
        return X, y, np.empty((0, X.shape[1])), np.empty((0,))
    test_n = max(20, int(n * 0.2))
    test_n = min(test_n, max(1, n // 3))
    return X[:-test_n], y[:-test_n], X[-test_n:], y[-test_n:]


def get_hidden_models(cur) -> List[str]:
    cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_hidden_models' LIMIT 1")
    row = cur.fetchone()
    if not row:
        return []
    sv = row.get("state_value")
    try:
        data = sv if isinstance(sv, list) else json.loads(sv or "[]")
        return [str(x) for x in data if str(x)]
    except Exception:
        return []


def save_hidden_models(cur, hidden_models: Sequence[str], now_ts: datetime) -> None:
    cur.execute(
        """
        INSERT INTO collector_state (state_key,state_value,updated_at_utc)
        VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
        """,
        ("sim_hidden_models", json.dumps(sorted(set(hidden_models))), now_ts),
    )


def upsert_custom_model(cur, cfg: Dict, now_ts: datetime) -> None:
    cur.execute(
        """
        INSERT INTO sim_models_registry
        (model_name, family, algo, mode, feature_cols_json, hyperparams_json, is_active, is_visible, status, notes, created_at_utc, updated_at_utc)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          family=VALUES(family),
          algo=VALUES(algo),
          mode=VALUES(mode),
          feature_cols_json=VALUES(feature_cols_json),
          hyperparams_json=VALUES(hyperparams_json),
          is_active=VALUES(is_active),
          is_visible=VALUES(is_visible),
          status=VALUES(status),
          notes=VALUES(notes),
          updated_at_utc=VALUES(updated_at_utc)
        """,
        (
            cfg["model_name"],
            cfg["family"],
            cfg["algo"],
            cfg["mode"],
            json.dumps(cfg["feature_cols"]),
            json.dumps(cfg["hyperparams"]),
            1 if cfg.get("is_active", True) else 0,
            1 if cfg.get("is_visible", True) else 0,
            cfg.get("status", "pending"),
            cfg.get("notes", ""),
            now_ts,
            now_ts,
        ),
    )


def list_custom_models(cur, include_inactive: bool = True) -> List[Dict]:
    sql = """
        SELECT model_name, family, algo, mode, feature_cols_json, hyperparams_json, is_active, is_visible, status, notes, last_error, created_at_utc, updated_at_utc
        FROM sim_models_registry
    """
    if not include_inactive:
        sql += " WHERE is_active=1"
    sql += " ORDER BY created_at_utc ASC, model_name ASC"
    cur.execute(sql)
    out = []
    for r in cur.fetchall():
        feat = r.get("feature_cols_json")
        params = r.get("hyperparams_json")
        try:
            feat = feat if isinstance(feat, list) else json.loads(feat or "[]")
        except Exception:
            feat = []
        try:
            params = params if isinstance(params, dict) else json.loads(params or "{}")
        except Exception:
            params = {}
        out.append(
            {
                "model_name": r["model_name"],
                "family": r["family"],
                "algo": r["algo"],
                "mode": r["mode"],
                "feature_cols": feat,
                "hyperparams": params,
                "is_active": bool(r["is_active"]),
                "is_visible": bool(r["is_visible"]),
                "status": r["status"],
                "notes": r.get("notes") or "",
                "last_error": r.get("last_error"),
                "created_at_utc": str(r.get("created_at_utc")) if r.get("created_at_utc") else None,
                "updated_at_utc": str(r.get("updated_at_utc")) if r.get("updated_at_utc") else None,
            }
        )
    return out


def list_ui_models(cur) -> List[Dict]:
    hidden = set(get_hidden_models(cur))
    models = []
    for model_name, meta in BUILTIN_MODELS.items():
        item = dict(meta)
        item["is_visible"] = model_name not in hidden
        models.append(item)
    for r in list_custom_models(cur, include_inactive=True):
        if not r.get("is_active"):
            continue
        models.append(r)
    return models


def visible_model_names(cur) -> List[str]:
    return [m["model_name"] for m in list_ui_models(cur) if m.get("is_visible")]


def active_custom_model_configs(cur) -> List[Dict]:
    return [m for m in list_custom_models(cur, include_inactive=False) if m.get("status") == "ready"]


def mark_custom_model_status(cur, model_name: str, status: str, now_ts: datetime, last_error: Optional[str] = None) -> None:
    cur.execute(
        """
        UPDATE sim_models_registry
        SET status=%s, last_error=%s, updated_at_utc=%s
        WHERE model_name=%s
        """,
        (status, last_error, now_ts, model_name),
    )


def set_model_visible(cur, model_name: str, visible: bool, now_ts: datetime) -> None:
    if model_name in BUILTIN_MODELS:
        hidden = set(get_hidden_models(cur))
        if visible:
            hidden.discard(model_name)
        else:
            hidden.add(model_name)
        save_hidden_models(cur, sorted(hidden), now_ts)
        return
    cur.execute(
        "UPDATE sim_models_registry SET is_visible=%s, updated_at_utc=%s WHERE model_name=%s",
        (1 if visible else 0, now_ts, model_name),
    )


def delete_custom_model(cur, model_name: str, now_ts: datetime) -> None:
    cur.execute(
        "UPDATE sim_models_registry SET is_active=0, is_visible=0, status='deleted', updated_at_utc=%s WHERE model_name=%s",
        (now_ts, model_name),
    )


def custom_model_stamp(configs: Sequence[Dict]) -> str:
    parts = []
    for c in sorted(configs, key=lambda x: x["model_name"]):
        parts.append(
            json.dumps(
                {
                    "model_name": c["model_name"],
                    "algo": c["algo"],
                    "feature_cols": c["feature_cols"],
                    "hyperparams": c["hyperparams"],
                    "status": c["status"],
                    "updated_at_utc": c.get("updated_at_utc"),
                },
                sort_keys=True,
            )
        )
    return "|".join(parts)


def build_custom_frozen_models(configs: Sequence[Dict], rows: List[Dict], cutoff_utc) -> Dict[str, CustomFrozenModel]:
    if cutoff_utc:
        train_rows = [r for r in rows if r.get("snapshot_minute_utc") and r["snapshot_minute_utc"] < cutoff_utc]
    else:
        train_rows = rows
    X, y = _build_supervised(train_rows)
    if len(X) < 20:
        raise RuntimeError(f"insufficient rows for custom frozen training: {len(X)}")
    train_X, train_y, test_X, test_y = _split_train_test(X, y)
    if len(train_X) < 10:
        raise RuntimeError(f"insufficient custom train rows: {len(train_X)}")

    out: Dict[str, CustomFrozenModel] = {}
    for cfg in configs:
        idx = tuple(FEATURE_COLS.index(f) for f in cfg["feature_cols"])
        tx = train_X[:, idx]
        vx = test_X[:, idx] if len(test_X) > 0 else np.empty((0, len(idx)))
        algo = cfg["algo"]
        hp = dict(cfg["hyperparams"])
        if algo == "logistic":
            pipe = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(**hp))])
            pipe.fit(tx, train_y)
            brier = None
            ll = None
            if len(vx) > 0:
                probs = pipe.predict_proba(vx)[:, 1]
                brier = float(brier_score_loss(test_y, probs))
                ll = float(log_loss(test_y, probs, labels=[0, 1]))
            out[cfg["model_name"]] = CustomFrozenModel(pipe, idx, len(train_X), len(test_X), brier, ll, "custom_logistic")
        elif algo == "random_forest":
            clf = RandomForestClassifier(**hp)
            clf.fit(tx, train_y)
            brier = None
            ll = None
            if len(vx) > 0:
                probs = clf.predict_proba(vx)[:, 1]
                brier = float(brier_score_loss(test_y, probs))
                ll = float(log_loss(test_y, probs, labels=[0, 1]))
            out[cfg["model_name"]] = CustomFrozenModel(clf, idx, len(train_X), len(test_X), brier, ll, "custom_rf")
        else:
            raise ValueError(f"unsupported algo: {algo}")
    return out
