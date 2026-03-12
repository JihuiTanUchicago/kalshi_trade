from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from sklearn.ensemble import HistGradientBoostingClassifier
except ImportError:
    from sklearn.experimental import enable_hist_gradient_boosting  # noqa: F401
    from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.ensemble import AdaBoostClassifier, BaggingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from client_api import KalshiDataClient
from data_pipeline.modeling_features import BASELINE_FEATURE_COLS, FEATURE_COLS


DEFAULT_BASE_URL = "https://dehiuraiut9ro.cloudfront.net"
DEFAULT_USERNAME = "todd"
DEFAULT_PASSWORD = "kalshimakesmepoor"
DEFAULT_OUTPUT_DIR = os.path.join(_REPO_ROOT, "Machine_Learning_Final_Presentation")
RESULTS_JSON_PATH = os.path.join(DEFAULT_OUTPUT_DIR, "latest_model_results.json")

MODEL_FEATURE_COLUMNS = [
    "snapshot_minute_utc",
    "market_ticker",
    "event_ticker",
    "target_btc_price",
    "yes_bid_dollars",
    "yes_ask_dollars",
    "spread_dollars",
    "mid_dollars",
    "yes_bid_size_fp",
    "yes_ask_size_fp",
    "orderbook_imbalance",
    "mid_ret_1m",
    "mid_ret_3m",
    "trades_last_60s_count",
    "trades_last_60s_volume_fp",
    "trades_last_60s_vwap_yes",
    "quote_change_events_60s",
    "time_to_expiry_sec",
    "cb_price",
    "cb_ret_1m",
    "cb_ret_3m",
    "cb_ret_5m",
    "cb_vol_5m",
    "kalshi_data_age_sec",
    "coinbase_data_age_sec",
    "model_eligible",
]

NUMERIC_COLUMNS = [
    "target_btc_price",
    "yes_bid_dollars",
    "yes_ask_dollars",
    "spread_dollars",
    "mid_dollars",
    "yes_bid_size_fp",
    "yes_ask_size_fp",
    "orderbook_imbalance",
    "mid_ret_1m",
    "mid_ret_3m",
    "trades_last_60s_count",
    "trades_last_60s_volume_fp",
    "trades_last_60s_vwap_yes",
    "quote_change_events_60s",
    "time_to_expiry_sec",
    "cb_price",
    "cb_ret_1m",
    "cb_ret_3m",
    "cb_ret_5m",
    "cb_vol_5m",
    "kalshi_data_age_sec",
    "coinbase_data_age_sec",
    "model_eligible",
]

TREE_EXTRA_FEATURES = [
    "yes_bid_size_fp",
    "yes_ask_size_fp",
    "depth_total",
    "depth_pressure",
    "vwap_mid_gap",
    "volume_per_trade",
    "quote_intensity",
    "microprice_proxy",
    "return_accel_1v3",
    "cb_return_accel_1v5",
    "ret_cross_cb",
    "spread_x_imbalance",
    "cb_price",
    "target_btc_price",
    "carry_to_target",
    "kalshi_data_age_sec",
    "coinbase_data_age_sec",
]

TREE_FEATURE_COLS = list(FEATURE_COLS) + TREE_EXTRA_FEATURES
PROBABILITY_GRID = [round(x, 2) for x in np.arange(0.55, 0.91, 0.05)]
EDGE_GRID = [0.00, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
TAKE_PROFIT_DOLLARS = 0.05
DEFAULT_MIN_VALIDATION_TRADES = 10
BASELINE_PARAMS = {
    "C": 0.5,
    "penalty": "l1",
    "solver": "liblinear",
    "class_weight": "balanced",
    "signal_threshold": 0.55,
    "edge_threshold": 0.01,
}
LINEAR_PARAMS = dict(BASELINE_PARAMS)

GBM_PARAMS = {
    "learning_rate": 0.03,
    "max_depth": 4,
    "max_iter": 250,
    "min_samples_leaf": 25,
    "l2_regularization": 0.01,
    "max_leaf_nodes": 63,
}
RF_PARAMS = {
    "n_estimators": 500,
    "max_depth": 10,
    "min_samples_leaf": 4,
    "min_samples_split": 12,
    "max_features": "sqrt",
    "class_weight": "balanced_subsample",
}
BAGGING_PARAMS = {
    "n_estimators": 100,
    "max_depth": 6,
    "min_samples_leaf": 8,
    "min_samples_split": 16,
    "max_samples": 0.8,
    "max_features": 0.8,
}
ADABOOST_PARAMS = {
    "n_estimators": 100,
    "learning_rate": 0.1,
    "max_depth": 2,
    "min_samples_leaf": 4,
    "min_samples_split": 8,
}


@dataclass
class SliceSummary:
    start_utc: str
    end_utc: str
    rows: int


@dataclass
class EvaluationSummary:
    total_pnl: float
    equity: float
    closed_trades: int
    win_rate: Optional[float]
    average_precision: Optional[float]
    auc: Optional[float]
    probability_threshold: float
    edge_threshold: float


@dataclass
class ThresholdSelectionSummary:
    min_validation_trades_requested: int
    min_validation_trades_effective: int
    fallback_used: bool


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _build_feature_vector(row: Dict) -> List[float]:
    yes_bid = _safe_float(row.get("yes_bid_dollars"))
    yes_ask = _safe_float(row.get("yes_ask_dollars"))
    spread = _safe_float(row.get("spread_dollars"))
    mid = _safe_float(row.get("mid_dollars"))
    imbalance = _safe_float(row.get("orderbook_imbalance"))
    mid_ret_1m = _safe_float(row.get("mid_ret_1m"))
    mid_ret_3m = _safe_float(row.get("mid_ret_3m"))
    trade_count = _safe_float(row.get("trades_last_60s_count"))
    trade_volume = _safe_float(row.get("trades_last_60s_volume_fp"))
    trade_vwap = _safe_float(row.get("trades_last_60s_vwap_yes"))
    quote_changes = _safe_float(row.get("quote_change_events_60s"))
    tte = _safe_float(row.get("time_to_expiry_sec"))
    cb_ret_1m = _safe_float(row.get("cb_ret_1m"))
    cb_ret_3m = _safe_float(row.get("cb_ret_3m"))
    cb_ret_5m = _safe_float(row.get("cb_ret_5m"))
    cb_vol_5m = _safe_float(row.get("cb_vol_5m"))
    cb_price = _safe_float(row.get("cb_price"))
    target = _safe_float(row.get("target_btc_price"))

    m_abs = 0.0
    m_pct = 0.0
    m_vol_scaled = 0.0
    m_x_sqrt_tte = 0.0
    m_x_imb = 0.0
    m_x_qchg = 0.0
    if target > 0.0:
        m_abs = cb_price - target
        m_pct = m_abs / target
        price_vol = max(abs(cb_price) * max(abs(cb_vol_5m), 1e-6), 1e-6)
        m_vol_scaled = m_abs / price_vol
        m_x_sqrt_tte = m_pct * math.sqrt(max(tte, 1.0))
        m_x_imb = m_pct * imbalance
        m_x_qchg = m_pct * quote_changes

    return [
        yes_bid,
        yes_ask,
        spread,
        mid,
        imbalance,
        mid_ret_1m,
        mid_ret_3m,
        trade_count,
        trade_volume,
        trade_vwap,
        quote_changes,
        tte,
        cb_ret_1m,
        cb_ret_3m,
        cb_ret_5m,
        cb_vol_5m,
        m_abs,
        m_pct,
        m_vol_scaled,
        m_x_sqrt_tte,
        m_x_imb,
        m_x_qchg,
    ]


def _has_linear_target(row: Dict) -> bool:
    return _safe_float(row.get("target_btc_price")) > 0.0


def _build_supervised_linear(rows: Sequence[Dict]) -> tuple[np.ndarray, np.ndarray]:
    features: List[List[float]] = []
    labels: List[int] = []
    for idx in range(len(rows) - 1):
        row = rows[idx]
        nxt = rows[idx + 1]
        if row.get("market_ticker") != nxt.get("market_ticker"):
            continue
        if not _has_linear_target(row) or not _has_linear_target(nxt):
            continue
        ask_t = row.get("yes_ask_dollars")
        bid_t1 = nxt.get("yes_bid_dollars")
        if ask_t is None or bid_t1 is None:
            continue
        features.append(_build_feature_vector(row))
        labels.append(1 if _safe_float(bid_t1) > _safe_float(ask_t) else 0)
    if not features:
        return np.empty((0, len(FEATURE_COLS))), np.empty((0,))
    return np.asarray(features, dtype=float), np.asarray(labels, dtype=int)


def _build_eval_labels_linear(rows: Sequence[Dict]) -> Dict[tuple, int]:
    labels: Dict[tuple, int] = {}
    for idx in range(len(rows) - 1):
        row = rows[idx]
        nxt = rows[idx + 1]
        if row.get("market_ticker") != nxt.get("market_ticker"):
            continue
        if row.get("mid_dollars") is None or nxt.get("mid_dollars") is None:
            continue
        labels[(row["snapshot_minute_utc"], row["market_ticker"])] = 1 if _safe_float(nxt["mid_dollars"]) > _safe_float(row["mid_dollars"]) else 0
    return labels


def _feature_indices(selected_features: Sequence[str]) -> List[int]:
    return [FEATURE_COLS.index(col) for col in selected_features if col in FEATURE_COLS]


def _linear_position_size(edge: float, max_qty: int = 10) -> int:
    if edge <= 0.0:
        return 0
    scaled = int((edge / 0.03) * max_qty)
    return max(1, min(max_qty, scaled))


def _build_linear_estimator(model_name: str, params: Dict):
    if model_name not in ("naive_logistic_baseline", "logistic"):
        raise ValueError(f"Unsupported linear model: {model_name}")
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    C=float(params["C"]),
                    penalty=str(params["penalty"]),
                    solver=str(params["solver"]),
                    class_weight=params["class_weight"],
                    random_state=42,
                ),
            ),
        ]
    )


def _simulate_linear(rows_eval: Sequence[Dict], estimator, selected_features: Sequence[str], signal_threshold: float, edge_threshold: float) -> Dict:
    idx = _feature_indices(selected_features)
    if not idx:
        return {"total_pnl": 0.0, "closed_trades": 0, "win_rate": None, "equity": 100.0, "equity_path": [100.0], "preds": []}

    open_position: Optional[Dict] = None
    realized = 0.0
    closed = 0
    wins = 0
    preds: List[tuple] = []
    equity_path: List[float] = []

    for row in rows_eval:
        if not _has_linear_target(row):
            continue
        ask = _safe_float(row.get("yes_ask_dollars"), default=np.nan)
        bid = _safe_float(row.get("yes_bid_dollars"), default=np.nan)
        ticker = row.get("market_ticker")
        if ticker is None or math.isnan(ask) or ask <= 0.0:
            continue

        x = np.asarray(_build_feature_vector(row), dtype=float)[idx]
        prob = float(estimator.predict_proba([x])[0, 1])
        edge = prob - ask
        signal = prob >= float(signal_threshold) and edge > float(edge_threshold)
        preds.append((row["snapshot_minute_utc"], ticker, prob))

        closed_this_tick = False
        if open_position is not None:
            should_close = open_position["ticker"] != ticker or not signal
            if should_close:
                exit_px = 0.0 if math.isnan(bid) else max(0.0, bid)
                pnl = (exit_px - open_position["entry"]) * open_position["qty"]
                realized += pnl
                closed += 1
                if pnl > 0:
                    wins += 1
                open_position = None
                closed_this_tick = True

        if open_position is None and not closed_this_tick and signal:
            qty = _linear_position_size(edge, max_qty=10)
            if qty > 0:
                open_position = {"ticker": ticker, "qty": qty, "entry": ask}

        unrealized = 0.0
        if open_position is not None and open_position["ticker"] == ticker and not math.isnan(bid):
            unrealized = (max(0.0, bid) - open_position["entry"]) * open_position["qty"]
        equity_path.append(100.0 + realized + unrealized)

    if open_position is not None and rows_eval:
        tail_bid = _safe_float(rows_eval[-1].get("yes_bid_dollars"))
        pnl = (max(0.0, tail_bid) - open_position["entry"]) * open_position["qty"]
        realized += pnl
        closed += 1
        if pnl > 0:
            wins += 1

    return {
        "total_pnl": float(realized),
        "closed_trades": int(closed),
        "win_rate": (wins / closed) if closed > 0 else None,
        "equity": 100.0 + float(realized),
        "equity_path": equity_path,
        "preds": preds,
    }


def _split_sequence(seq: Sequence) -> tuple[Sequence, Sequence, Sequence]:
    n = len(seq)
    if n < 30:
        raise RuntimeError(f"Need at least 30 rows, found {n}")
    train_end = max(1, int(n * 0.6))
    valid_end = max(train_end + 1, int(n * 0.8))
    valid_end = min(valid_end, n - 1)
    train = seq[:train_end]
    valid = seq[train_end:valid_end]
    test = seq[valid_end:]
    if not train or not valid or not test:
        raise RuntimeError(f"Invalid split sizes train={len(train)} valid={len(valid)} test={len(test)}")
    return train, valid, test


def _slice_summary_from_rows(rows: Sequence[dict]) -> SliceSummary:
    return SliceSummary(
        start_utc=pd.Timestamp(rows[0]["snapshot_minute_utc"]).strftime("%Y-%m-%d %H:%M"),
        end_utc=pd.Timestamp(rows[-1]["snapshot_minute_utc"]).strftime("%Y-%m-%d %H:%M"),
        rows=len(rows),
    )


def _slice_summary_from_df(df: pd.DataFrame) -> SliceSummary:
    return SliceSummary(
        start_utc=df["snapshot_minute_utc"].iloc[0].strftime("%Y-%m-%d %H:%M"),
        end_utc=df["snapshot_minute_utc"].iloc[-1].strftime("%Y-%m-%d %H:%M"),
        rows=int(len(df)),
    )


def _classification_metrics(eval_labels: Dict[tuple[datetime, str], int], preds: Sequence[tuple]) -> tuple[Optional[float], Optional[float]]:
    y_true: List[int] = []
    y_score: List[float] = []
    for ts, ticker, prob in preds:
        label = eval_labels.get((ts, ticker))
        if label is None:
            continue
        y_true.append(int(label))
        y_score.append(float(prob))
    if not y_true or len(set(y_true)) < 2:
        return None, None
    ap = float(average_precision_score(y_true, y_score))
    auc = float(roc_auc_score(y_true, y_score))
    return ap, auc


def _finalize_sim_summary(sim: Dict, probability_threshold: float, edge_threshold: float, average_precision: Optional[float], auc: Optional[float]) -> EvaluationSummary:
    return EvaluationSummary(
        total_pnl=float(sim["total_pnl"]),
        equity=float(sim["equity"]),
        closed_trades=int(sim["closed_trades"]),
        win_rate=None if sim["win_rate"] is None else float(sim["win_rate"]),
        average_precision=average_precision,
        auc=auc,
        probability_threshold=float(probability_threshold),
        edge_threshold=float(edge_threshold),
    )


def _clean_equity_path(path: Optional[Sequence[float]], final_equity: float) -> List[float]:
    equity = [float(x) for x in (path or [])]
    if not equity:
        return [100.0, float(final_equity)]
    if abs(equity[-1] - float(final_equity)) > 1e-9:
        equity.append(float(final_equity))
    return equity


def _plot_equity_curve(equity_path: Sequence[float], title: str, out_path: str, color: str) -> None:
    curve = list(equity_path) or [100.0]
    x = np.arange(len(curve))
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.plot(x, curve, color=color, linewidth=1.4)
    ax.axhline(100.0, color="#8c8c8c", linestyle="--", linewidth=1.0, alpha=0.7)
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("Minute index", fontsize=9)
    ax.set_ylabel("Equity ($)", fontsize=9)
    ax.grid(True, alpha=0.25)
    ymin = min(curve)
    ymax = max(curve)
    ax.set_ylim(min(95.0, ymin - 2.0), max(105.0, ymax + 2.0))
    fig.tight_layout()
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _load_live_features(base_url: str, username: str, password: str, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    client = KalshiDataClient(base_url=base_url, username=username, password=password)
    df = client.fetch_table("model_features_1m", start=start, end=end, columns=MODEL_FEATURE_COLUMNS, chunk_size=5000)
    if df.empty:
        raise RuntimeError("Fetched 0 model feature rows from the live API")
    df["snapshot_minute_utc"] = pd.to_datetime(df["snapshot_minute_utc"], utc=False)
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["snapshot_minute_utc"].notna()].copy()
    df = df.sort_values(["snapshot_minute_utc", "market_ticker"]).reset_index(drop=True)
    df = df[df["model_eligible"] == 1].reset_index(drop=True)
    if df.empty:
        raise RuntimeError("No eligible model rows were returned by the live API")
    return df


def _build_linear_result(model_name: str, display_name: str, rows: List[dict], selected_features: Sequence[str], params: Dict, output_dir: str, insample_plot_name: str, oos_plot_name: str, insample_color: str, oos_color: str) -> Dict:
    train_rows, valid_rows, test_rows = _split_sequence(rows)
    train_x, train_y = _build_supervised_linear(list(train_rows))
    if len(train_x) < 40:
        raise RuntimeError(f"Insufficient supervised train rows for {model_name}: {len(train_x)}")
    selected_idx = _feature_indices(selected_features)
    if not selected_idx:
        raise RuntimeError(f"No valid features selected for {model_name}")
    estimator = _build_linear_estimator(model_name, params)
    estimator.fit(train_x[:, selected_idx], train_y)

    valid_sim = _simulate_linear(list(valid_rows), estimator, selected_features, params["signal_threshold"], params["edge_threshold"])
    valid_labels = _build_eval_labels_linear(list(valid_rows))
    valid_ap, valid_auc = _classification_metrics(valid_labels, valid_sim["preds"])

    test_sim = _simulate_linear(list(test_rows), estimator, selected_features, params["signal_threshold"], params["edge_threshold"])
    test_labels = _build_eval_labels_linear(list(test_rows))
    test_ap, test_auc = _classification_metrics(test_labels, test_sim["preds"])

    valid_curve = _clean_equity_path(valid_sim.get("equity_path"), valid_sim["equity"])
    test_curve = _clean_equity_path(test_sim.get("equity_path"), test_sim["equity"])
    _plot_equity_curve(valid_curve, f"{display_name} - In-sample", os.path.join(output_dir, insample_plot_name), insample_color)
    _plot_equity_curve(test_curve, f"{display_name} - Out-of-sample", os.path.join(output_dir, oos_plot_name), oos_color)

    return {
        "display_name": display_name,
        "label_type": "next_minute",
        "features": list(selected_features),
        "model_params": params,
        "splits": {
            "train": asdict(_slice_summary_from_rows(train_rows)),
            "validation": asdict(_slice_summary_from_rows(valid_rows)),
            "test": asdict(_slice_summary_from_rows(test_rows)),
        },
        "validation": asdict(_finalize_sim_summary(valid_sim, params["signal_threshold"], params["edge_threshold"], valid_ap, valid_auc)),
        "test": asdict(_finalize_sim_summary(test_sim, params["signal_threshold"], params["edge_threshold"], test_ap, test_auc)),
        "plots": {
            "validation": insample_plot_name,
            "test": oos_plot_name,
        },
    }


def _build_expiry_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in NUMERIC_COLUMNS:
        if col in out.columns:
            out[col] = out[col].fillna(0.0)

    target = out["target_btc_price"].where(out["target_btc_price"] > 0.0, np.nan)
    spot = out["cb_price"]
    imbalance = out["orderbook_imbalance"]
    quote_changes = out["quote_change_events_60s"]
    tte = out["time_to_expiry_sec"].clip(lower=1.0)
    cb_vol = out["cb_vol_5m"].abs().clip(lower=1e-6)

    out["moneyness_abs"] = (spot - target).fillna(0.0)
    out["moneyness_pct"] = ((spot - target) / target).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    price_vol = (spot.abs().clip(lower=1e-6) * cb_vol).clip(lower=1e-6)
    out["moneyness_vol_scaled"] = (out["moneyness_abs"] / price_vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out["moneyness_x_sqrt_tte"] = out["moneyness_pct"] * np.sqrt(tte)
    out["moneyness_x_imbalance"] = out["moneyness_pct"] * imbalance
    out["moneyness_x_qchg"] = out["moneyness_pct"] * quote_changes

    out["depth_total"] = out["yes_bid_size_fp"] + out["yes_ask_size_fp"]
    out["depth_pressure"] = ((out["yes_bid_size_fp"] - out["yes_ask_size_fp"]) / out["depth_total"].clip(lower=1e-6)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out["vwap_mid_gap"] = (out["trades_last_60s_vwap_yes"] - out["mid_dollars"]).fillna(0.0)
    out["volume_per_trade"] = (out["trades_last_60s_volume_fp"] / out["trades_last_60s_count"].clip(lower=1.0)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out["quote_intensity"] = (quote_changes / 60.0).fillna(0.0)
    microprice = (
        (out["yes_ask_dollars"] * out["yes_bid_size_fp"]) + (out["yes_bid_dollars"] * out["yes_ask_size_fp"])
    ) / out["depth_total"].clip(lower=1e-6)
    out["microprice_proxy"] = microprice.replace([np.inf, -np.inf], np.nan).fillna(out["mid_dollars"]).fillna(0.0)
    out["return_accel_1v3"] = (out["mid_ret_1m"] - (out["mid_ret_3m"] / 3.0)).fillna(0.0)
    out["cb_return_accel_1v5"] = (out["cb_ret_1m"] - (out["cb_ret_5m"] / 5.0)).fillna(0.0)
    out["ret_cross_cb"] = (out["mid_ret_1m"] * out["cb_ret_1m"]).fillna(0.0)
    out["spread_x_imbalance"] = (out["spread_dollars"] * imbalance).fillna(0.0)
    out["carry_to_target"] = ((out["target_btc_price"] - out["cb_price"]) / np.sqrt(tte)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def _attach_expiry_outcomes(full_df: pd.DataFrame, modeling_df: pd.DataFrame) -> pd.DataFrame:
    outcome_df = modeling_df.copy()
    outcome_df["resolution_label"] = 0
    outcome_df["exit_time_utc"] = pd.NaT
    outcome_df["exit_price_dollars"] = np.nan

    full_groups = {
        ticker: grp.sort_values("snapshot_minute_utc").reset_index(drop=True)
        for ticker, grp in full_df.groupby("market_ticker", sort=False)
    }

    for ticker, idxs in outcome_df.groupby("market_ticker", sort=False).groups.items():
        full_group = full_groups.get(ticker)
        if full_group is None or full_group.empty:
            continue

        full_bids = full_group["yes_bid_dollars"].fillna(method="ffill").fillna(0.0).to_numpy(dtype=float)
        full_times = full_group["snapshot_minute_utc"].to_numpy()
        full_final_bid = float(full_bids[-1])
        full_final_ts = pd.Timestamp(full_times[-1])
        label = 1 if full_final_bid >= 0.90 else 0

        for row_idx in idxs:
            row = outcome_df.loc[row_idx]
            entry_ts = row["snapshot_minute_utc"]
            entry_ask = _safe_float(row["yes_ask_dollars"], default=np.nan)
            if math.isnan(entry_ask):
                continue

            future_mask = full_group["snapshot_minute_utc"] > entry_ts
            future_group = full_group.loc[future_mask, ["snapshot_minute_utc", "yes_bid_dollars"]]
            exit_time = full_final_ts
            exit_price = full_final_bid
            if not future_group.empty:
                hits = future_group[future_group["yes_bid_dollars"].fillna(-np.inf) >= (entry_ask + TAKE_PROFIT_DOLLARS)]
                if not hits.empty:
                    exit_time = pd.Timestamp(hits.iloc[0]["snapshot_minute_utc"])
                    exit_price = _safe_float(hits.iloc[0]["yes_bid_dollars"])

            outcome_df.at[row_idx, "resolution_label"] = label
            outcome_df.at[row_idx, "exit_time_utc"] = exit_time
            outcome_df.at[row_idx, "exit_price_dollars"] = exit_price

    return outcome_df


def _build_expiry_estimator(model_key: str):
    if model_key == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            learning_rate=GBM_PARAMS["learning_rate"],
            max_depth=GBM_PARAMS["max_depth"],
            max_iter=GBM_PARAMS["max_iter"],
            min_samples_leaf=GBM_PARAMS["min_samples_leaf"],
            l2_regularization=GBM_PARAMS["l2_regularization"],
            max_leaf_nodes=GBM_PARAMS["max_leaf_nodes"],
            random_state=42,
        )
    if model_key == "random_forest":
        return RandomForestClassifier(
            n_estimators=RF_PARAMS["n_estimators"],
            max_depth=RF_PARAMS["max_depth"],
            min_samples_leaf=RF_PARAMS["min_samples_leaf"],
            min_samples_split=RF_PARAMS["min_samples_split"],
            max_features=RF_PARAMS["max_features"],
            class_weight=RF_PARAMS["class_weight"],
            n_jobs=-1,
            random_state=42,
        )
    if model_key == "bagging":
        base = DecisionTreeClassifier(
            max_depth=BAGGING_PARAMS["max_depth"],
            min_samples_leaf=BAGGING_PARAMS["min_samples_leaf"],
            min_samples_split=BAGGING_PARAMS["min_samples_split"],
            random_state=42,
        )
        try:
            return BaggingClassifier(
                estimator=base,
                n_estimators=BAGGING_PARAMS["n_estimators"],
                max_samples=BAGGING_PARAMS["max_samples"],
                max_features=BAGGING_PARAMS["max_features"],
                bootstrap=True,
                n_jobs=-1,
                random_state=42,
            )
        except TypeError:
            return BaggingClassifier(
                base_estimator=base,
                n_estimators=BAGGING_PARAMS["n_estimators"],
                max_samples=BAGGING_PARAMS["max_samples"],
                max_features=BAGGING_PARAMS["max_features"],
                bootstrap=True,
                n_jobs=-1,
                random_state=42,
            )
    if model_key == "adaboost":
        base = DecisionTreeClassifier(
            max_depth=ADABOOST_PARAMS["max_depth"],
            min_samples_leaf=ADABOOST_PARAMS["min_samples_leaf"],
            min_samples_split=ADABOOST_PARAMS["min_samples_split"],
            random_state=42,
        )
        try:
            return AdaBoostClassifier(
                estimator=base,
                n_estimators=ADABOOST_PARAMS["n_estimators"],
                learning_rate=ADABOOST_PARAMS["learning_rate"],
                random_state=42,
            )
        except TypeError:
            return AdaBoostClassifier(
                base_estimator=base,
                n_estimators=ADABOOST_PARAMS["n_estimators"],
                learning_rate=ADABOOST_PARAMS["learning_rate"],
                random_state=42,
            )
    raise ValueError(f"Unsupported expiry model key: {model_key}")


def _feature_matrix(df: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    return df.loc[:, list(columns)].fillna(0.0).to_numpy(dtype=float)


def _simulate_expiry(df: pd.DataFrame, probabilities: np.ndarray, probability_threshold: float, edge_threshold: float) -> Dict:
    realized = 0.0
    closed = 0
    wins = 0
    equity_path: List[float] = []
    active_trade: Optional[Dict] = None
    slice_end = df["snapshot_minute_utc"].iloc[-1]

    for row, prob in zip(df.itertuples(index=False), probabilities):
        ts = row.snapshot_minute_utc
        closed_this_tick = False
        if active_trade is not None and ts >= active_trade["exit_time"]:
            pnl = active_trade["pnl"]
            realized += pnl
            closed += 1
            if pnl > 0:
                wins += 1
            active_trade = None
            closed_this_tick = True

        if active_trade is None:
            ask = _safe_float(row.yes_ask_dollars, default=np.nan)
            edge = float(prob) - ask if not math.isnan(ask) else -1e9
            should_open = (
                not closed_this_tick
                and not math.isnan(ask)
                and float(prob) >= float(probability_threshold)
                and edge >= float(edge_threshold)
                and pd.notna(row.exit_time_utc)
                and pd.Timestamp(row.exit_time_utc) <= slice_end
            )
            if should_open:
                active_trade = {
                    "exit_time": pd.Timestamp(row.exit_time_utc),
                    "pnl": _safe_float(row.exit_price_dollars) - ask,
                }

        equity_path.append(100.0 + realized)

    if active_trade is not None and active_trade["exit_time"] <= slice_end:
        realized += active_trade["pnl"]
        closed += 1
        if active_trade["pnl"] > 0:
            wins += 1
        equity_path.append(100.0 + realized)

    return {
        "total_pnl": float(realized),
        "equity": 100.0 + float(realized),
        "closed_trades": int(closed),
        "win_rate": (wins / closed) if closed > 0 else None,
        "equity_path": equity_path,
    }


def _threshold_objective(sim: Dict, probability_threshold: float, edge_threshold: float) -> tuple:
    return (
        float(sim["total_pnl"]),
        -int(sim["closed_trades"]),
        0.0 if sim["win_rate"] is None else float(sim["win_rate"]),
        float(probability_threshold),
        float(edge_threshold),
    )


def _choose_thresholds(validation_df: pd.DataFrame, probabilities: np.ndarray, min_closed_trades: int = 0) -> Dict:
    best_choice: Optional[Dict] = None
    for probability_threshold in PROBABILITY_GRID:
        for edge_threshold in EDGE_GRID:
            sim = _simulate_expiry(validation_df, probabilities, probability_threshold, edge_threshold)
            if int(sim["closed_trades"]) < int(min_closed_trades):
                continue
            score = _threshold_objective(sim, probability_threshold, edge_threshold)
            choice = {
                "probability_threshold": float(probability_threshold),
                "edge_threshold": float(edge_threshold),
                "score": score,
                "simulation": sim,
                "selection": asdict(
                    ThresholdSelectionSummary(
                        min_validation_trades_requested=int(min_closed_trades),
                        min_validation_trades_effective=int(min_closed_trades),
                        fallback_used=False,
                    )
                ),
            }
            if best_choice is None or choice["score"] > best_choice["score"]:
                best_choice = choice

    if best_choice is not None:
        return best_choice

    if int(min_closed_trades) > 0:
        fallback_choice = _choose_thresholds(validation_df, probabilities, min_closed_trades=0)
        fallback_choice["selection"] = asdict(
            ThresholdSelectionSummary(
                min_validation_trades_requested=int(min_closed_trades),
                min_validation_trades_effective=0,
                fallback_used=True,
            )
        )
        return fallback_choice

    raise RuntimeError("Failed to choose expiry thresholds")


def _fit_expiry_model(model_key: str, display_name: str, dataset: pd.DataFrame, feature_columns: Sequence[str], output_dir: str, insample_plot_name: str, oos_plot_name: str, insample_color: str, oos_color: str, model_params: Dict, min_validation_trades: int) -> Dict:
    train_df, validation_df, test_df = _split_sequence([r for _, r in dataset.iterrows()])
    train_df = pd.DataFrame(train_df).reset_index(drop=True)
    validation_df = pd.DataFrame(validation_df).reset_index(drop=True)
    test_df = pd.DataFrame(test_df).reset_index(drop=True)

    train_x = _feature_matrix(train_df, feature_columns)
    train_y = train_df["resolution_label"].to_numpy(dtype=int)
    validation_x = _feature_matrix(validation_df, feature_columns)
    validation_y = validation_df["resolution_label"].to_numpy(dtype=int)

    estimator = _build_expiry_estimator(model_key)
    estimator.fit(train_x, train_y)
    validation_prob = estimator.predict_proba(validation_x)[:, 1]
    thresholds = _choose_thresholds(validation_df, validation_prob, min_closed_trades=min_validation_trades)
    validation_ap = float(average_precision_score(validation_y, validation_prob)) if len(set(validation_y.tolist())) > 1 else None
    validation_auc = float(roc_auc_score(validation_y, validation_prob)) if len(set(validation_y.tolist())) > 1 else None

    refit_df = pd.concat([train_df, validation_df], ignore_index=True)
    refit_x = _feature_matrix(refit_df, feature_columns)
    refit_y = refit_df["resolution_label"].to_numpy(dtype=int)
    final_estimator = _build_expiry_estimator(model_key)
    final_estimator.fit(refit_x, refit_y)

    test_x = _feature_matrix(test_df, feature_columns)
    test_y = test_df["resolution_label"].to_numpy(dtype=int)
    test_prob = final_estimator.predict_proba(test_x)[:, 1]
    test_sim = _simulate_expiry(test_df, test_prob, thresholds["probability_threshold"], thresholds["edge_threshold"])
    test_ap = float(average_precision_score(test_y, test_prob)) if len(set(test_y.tolist())) > 1 else None
    test_auc = float(roc_auc_score(test_y, test_prob)) if len(set(test_y.tolist())) > 1 else None

    validation_curve = _clean_equity_path(thresholds["simulation"]["equity_path"], thresholds["simulation"]["equity"])
    test_curve = _clean_equity_path(test_sim["equity_path"], test_sim["equity"])
    _plot_equity_curve(validation_curve, f"{display_name} - In-sample", os.path.join(output_dir, insample_plot_name), insample_color)
    _plot_equity_curve(test_curve, f"{display_name} - Out-of-sample", os.path.join(output_dir, oos_plot_name), oos_color)

    return {
        "display_name": display_name,
        "label_type": "expiry_resolution",
        "features": list(feature_columns),
        "model_params": model_params,
        "threshold_selection": thresholds["selection"],
        "splits": {
            "train": asdict(_slice_summary_from_df(train_df)),
            "validation": asdict(_slice_summary_from_df(validation_df)),
            "test": asdict(_slice_summary_from_df(test_df)),
        },
        "validation": asdict(
            EvaluationSummary(
                total_pnl=float(thresholds["simulation"]["total_pnl"]),
                equity=float(thresholds["simulation"]["equity"]),
                closed_trades=int(thresholds["simulation"]["closed_trades"]),
                win_rate=None if thresholds["simulation"]["win_rate"] is None else float(thresholds["simulation"]["win_rate"]),
                average_precision=validation_ap,
                auc=validation_auc,
                probability_threshold=float(thresholds["probability_threshold"]),
                edge_threshold=float(thresholds["edge_threshold"]),
            )
        ),
        "test": asdict(
            EvaluationSummary(
                total_pnl=float(test_sim["total_pnl"]),
                equity=float(test_sim["equity"]),
                closed_trades=int(test_sim["closed_trades"]),
                win_rate=None if test_sim["win_rate"] is None else float(test_sim["win_rate"]),
                average_precision=test_ap,
                auc=test_auc,
                probability_threshold=float(thresholds["probability_threshold"]),
                edge_threshold=float(thresholds["edge_threshold"]),
            )
        ),
        "plots": {
            "validation": insample_plot_name,
            "test": oos_plot_name,
        },
    }


def _format_money(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}${value:.2f}"


def _format_rate(value: Optional[float]) -> str:
    if value is None:
        return "--"
    return f"{value * 100:.1f}%"


def _print_summary(results: Dict) -> None:
    print(f"Data window: {results['data_window']['start_utc']} to {results['data_window']['end_utc']} UTC ({results['data_window']['rows']} rows)")
    for key in ("benchmark", "model_1", "model_2", "model_3", "model_4", "model_5"):
        model = results["models"][key]
        test = model["test"]
        ap_text = "--" if test["average_precision"] is None else f"{test['average_precision']:.3f}"
        auc_text = "--" if test["auc"] is None else f"{test['auc']:.3f}"
        print(
            f"{key}: pnl={_format_money(test['total_pnl'])} "
            f"trades={test['closed_trades']} win_rate={_format_rate(test['win_rate'])} "
            f"ap={ap_text} "
            f"auc={auc_text} "
            f"thresholds=({test['probability_threshold']:.2f}, {test['edge_threshold']:.2f})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild benchmark and Models 1-5 from live data for the presentation.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--start", default=None, help="Optional inclusive UTC start bound, e.g. 2026-03-07 00:00:00")
    parser.add_argument("--end", default=None, help="Optional inclusive UTC end bound, e.g. 2026-03-12 00:00:00")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-validation-trades", type=int, default=DEFAULT_MIN_VALIDATION_TRADES)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    live_df = _load_live_features(args.base_url, args.username, args.password, args.start, args.end)
    data_window = {
        "start_utc": live_df["snapshot_minute_utc"].iloc[0].strftime("%Y-%m-%d %H:%M"),
        "end_utc": live_df["snapshot_minute_utc"].iloc[-1].strftime("%Y-%m-%d %H:%M"),
        "rows": int(len(live_df)),
    }

    linear_rows = live_df.to_dict(orient="records")
    benchmark_result = _build_linear_result(
        model_name="naive_logistic_baseline",
        display_name="Naive Logistic Baseline",
        rows=linear_rows,
        selected_features=BASELINE_FEATURE_COLS,
        params=BASELINE_PARAMS,
        output_dir=args.output_dir,
        insample_plot_name="equity_insample.png",
        oos_plot_name="equity_outsample.png",
        insample_color="#8b1e3f",
        oos_color="#1d4e89",
    )
    model_1_result = _build_linear_result(
        model_name="logistic",
        display_name="Logistic Regression",
        rows=linear_rows,
        selected_features=FEATURE_COLS,
        params=LINEAR_PARAMS,
        output_dir=args.output_dir,
        insample_plot_name="logistic_insample.png",
        oos_plot_name="logistic_outsample_compare.png",
        insample_color="#b45309",
        oos_color="#047857",
    )

    expiry_full_df = _build_expiry_features(live_df)
    expiry_model_df = expiry_full_df[
        (expiry_full_df["yes_ask_dollars"].notna())
        & (expiry_full_df["target_btc_price"] > 0.0)
        & (expiry_full_df["time_to_expiry_sec"] >= 120.0)
    ].copy()
    expiry_model_df = _attach_expiry_outcomes(expiry_full_df, expiry_model_df)
    expiry_model_df = expiry_model_df.sort_values(["snapshot_minute_utc", "market_ticker"]).reset_index(drop=True)
    if len(expiry_model_df) < 90:
        raise RuntimeError(f"Insufficient expiry-resolution rows: {len(expiry_model_df)}")

    model_2_result = _fit_expiry_model(
        model_key="hist_gradient_boosting",
        display_name="Gradient Boosting",
        dataset=expiry_model_df,
        feature_columns=TREE_FEATURE_COLS,
        output_dir=args.output_dir,
        insample_plot_name="gbm_insample.png",
        oos_plot_name="gbm_outsample_compare.png",
        insample_color="#7c3aed",
        oos_color="#0f766e",
        model_params=GBM_PARAMS,
        min_validation_trades=args.min_validation_trades,
    )
    model_3_result = _fit_expiry_model(
        model_key="random_forest",
        display_name="Random Forest",
        dataset=expiry_model_df,
        feature_columns=TREE_FEATURE_COLS,
        output_dir=args.output_dir,
        insample_plot_name="rf_insample.png",
        oos_plot_name="rf_outsample_compare.png",
        insample_color="#1d4ed8",
        oos_color="#0f766e",
        model_params=RF_PARAMS,
        min_validation_trades=args.min_validation_trades,
    )
    model_4_result = _fit_expiry_model(
        model_key="bagging",
        display_name="Bagging Trees",
        dataset=expiry_model_df,
        feature_columns=FEATURE_COLS,
        output_dir=args.output_dir,
        insample_plot_name="bagging_insample.png",
        oos_plot_name="bagging_outsample_compare.png",
        insample_color="#2563eb",
        oos_color="#1d4ed8",
        model_params=BAGGING_PARAMS,
        min_validation_trades=args.min_validation_trades,
    )
    model_5_result = _fit_expiry_model(
        model_key="adaboost",
        display_name="AdaBoost",
        dataset=expiry_model_df,
        feature_columns=FEATURE_COLS,
        output_dir=args.output_dir,
        insample_plot_name="adaboost_insample.png",
        oos_plot_name="adaboost_outsample_compare.png",
        insample_color="#ea580c",
        oos_color="#166534",
        model_params=ADABOOST_PARAMS,
        min_validation_trades=args.min_validation_trades,
    )

    results = {
        "generated_at_utc": utcnow_iso(),
        "data_window": data_window,
        "models": {
            "benchmark": benchmark_result,
            "model_1": model_1_result,
            "model_2": model_2_result,
            "model_3": model_3_result,
            "model_4": model_4_result,
            "model_5": model_5_result,
        },
    }

    with open(os.path.join(args.output_dir, "latest_model_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    _print_summary(results)


if __name__ == "__main__":
    main()
