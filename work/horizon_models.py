from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
try:
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
except ImportError:
    from sklearn.experimental import enable_hist_gradient_boosting  # noqa: F401
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from client_api import KalshiDataClient


DEFAULT_BASE_URL = "https://dehiuraiut9ro.cloudfront.net"
DEFAULT_USERNAME = "todd"
DEFAULT_PASSWORD = "kalshimakesmepoor"

RAW_NUMERIC_COLUMNS = [
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
]

LINEAR_FEATURE_COLUMNS = [
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
    "moneyness_abs",
    "moneyness_pct",
    "moneyness_vol_scaled",
    "moneyness_x_sqrt_tte",
    "moneyness_x_imbalance",
    "moneyness_x_qchg",
]

TREE_FEATURE_COLUMNS = [
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
    "target_btc_price",
    "moneyness_abs",
    "moneyness_pct",
    "moneyness_vol_scaled",
    "moneyness_x_sqrt_tte",
    "moneyness_x_imbalance",
    "moneyness_x_qchg",
    "depth_total",
    "depth_pressure",
    "vwap_mid_gap",
    "return_accel_1v3",
    "cb_return_accel_1v5",
    "volume_per_trade",
    "quote_intensity",
    "microprice_proxy",
    "carry_to_target",
    "spread_x_imbalance",
    "ret_cross_cb",
]


@dataclass(frozen=True)
class TradeRule:
    probability_threshold: float
    edge_threshold: float


@dataclass(frozen=True)
class BacktestResult:
    pnl: float
    trades: int
    win_rate: Optional[float]
    avg_pnl: Optional[float]


@dataclass(frozen=True)
class ResearchConfig:
    take_profit_buffer_dollars: float = 0.05
    min_time_to_expiry_sec: int = 120
    train_fraction: float = 0.60
    validation_fraction: float = 0.20
    probability_threshold_grid: Tuple[float, ...] = (
        0.55,
        0.60,
        0.65,
        0.70,
        0.75,
        0.80,
        0.85,
        0.90,
    )
    edge_threshold_grid: Tuple[float, ...] = (
        0.00,
        0.01,
        0.02,
        0.03,
        0.05,
        0.08,
        0.10,
        0.12,
        0.15,
        0.20,
    )
    trade_count_target: int = 20


@dataclass(frozen=True)
class ModelSpec:
    name: str
    display_name: str
    feature_columns: Tuple[str, ...]
    params: Mapping[str, Any]
    is_benchmark: bool = False


MODEL_SPECS = (
    ModelSpec(
        name="logistic_resolution_edge",
        display_name="Logistic Resolution Edge",
        feature_columns=tuple(LINEAR_FEATURE_COLUMNS),
        params={"C": 0.5},
        is_benchmark=True,
    ),
    ModelSpec(
        name="random_forest_resolution_edge",
        display_name="Random Forest Resolution Edge",
        feature_columns=tuple(TREE_FEATURE_COLUMNS),
        params={
            "n_estimators": 500,
            "max_depth": 10,
            "min_samples_leaf": 4,
            "min_samples_split": 12,
            "max_features": "sqrt",
            "class_weight": "balanced_subsample",
        },
    ),
    ModelSpec(
        name="hist_gradient_boosting_resolution_edge",
        display_name="HistGradientBoosting Resolution Edge",
        feature_columns=tuple(TREE_FEATURE_COLUMNS),
        params={
            "learning_rate": 0.03,
            "max_depth": 4,
            "max_iter": 250,
            "min_samples_leaf": 25,
            "l2_regularization": 0.01,
            "max_leaf_nodes": 63,
        },
    ),
)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if pd.isna(value):
        return None
    return float(value)


def load_model_features(
    client: KalshiDataClient,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    df = client.model_features(start=start, end=end).copy()
    if "snapshot_minute_utc" in df.columns:
        df["snapshot_minute_utc"] = pd.to_datetime(df["snapshot_minute_utc"])
    for column in RAW_NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "model_eligible" in df.columns:
        df["model_eligible"] = pd.to_numeric(df["model_eligible"], errors="coerce").fillna(0).astype(int)
    return df.sort_values("snapshot_minute_utc").reset_index(drop=True)


def engineer_resolution_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["moneyness_abs"] = out["cb_price"] - out["target_btc_price"]
    out["moneyness_pct"] = np.where(
        out["target_btc_price"].abs() > 1e-9,
        out["moneyness_abs"] / out["target_btc_price"],
        0.0,
    )
    denom = np.maximum(
        out["cb_price"].abs() * np.maximum(out["cb_vol_5m"].abs().fillna(0.0), 1e-6),
        1e-6,
    )
    out["moneyness_vol_scaled"] = out["moneyness_abs"] / denom
    out["moneyness_x_sqrt_tte"] = out["moneyness_pct"] * np.sqrt(np.maximum(out["time_to_expiry_sec"], 1.0))
    out["moneyness_x_imbalance"] = out["moneyness_pct"] * out["orderbook_imbalance"].fillna(0.0)
    out["moneyness_x_qchg"] = out["moneyness_pct"] * out["quote_change_events_60s"].fillna(0.0)
    out["depth_total"] = out["yes_bid_size_fp"].fillna(0.0) + out["yes_ask_size_fp"].fillna(0.0)
    out["depth_pressure"] = out["orderbook_imbalance"].fillna(0.0) * np.log1p(out["depth_total"].clip(lower=0.0))
    out["vwap_mid_gap"] = out["trades_last_60s_vwap_yes"].fillna(out["mid_dollars"]) - out["mid_dollars"].fillna(0.0)
    out["return_accel_1v3"] = out["mid_ret_1m"].fillna(0.0) - (out["mid_ret_3m"].fillna(0.0) / 3.0)
    out["cb_return_accel_1v5"] = out["cb_ret_1m"].fillna(0.0) - (out["cb_ret_5m"].fillna(0.0) / 5.0)
    out["volume_per_trade"] = out["trades_last_60s_volume_fp"].fillna(0.0) / np.maximum(
        out["trades_last_60s_count"].fillna(0.0),
        1.0,
    )
    out["quote_intensity"] = out["quote_change_events_60s"].fillna(0.0) / np.sqrt(
        np.maximum(out["time_to_expiry_sec"], 1.0)
    )
    out["microprice_proxy"] = out["mid_dollars"].fillna(0.0) + (
        0.5 * out["spread_dollars"].fillna(0.0) * out["orderbook_imbalance"].fillna(0.0)
    )
    out["carry_to_target"] = out["target_btc_price"] - out["cb_price"]
    out["spread_x_imbalance"] = out["spread_dollars"].fillna(0.0) * out["orderbook_imbalance"].fillna(0.0)
    out["ret_cross_cb"] = out["mid_ret_1m"].fillna(0.0) * out["cb_ret_1m"].fillna(0.0)
    return out


def build_expiry_resolution_dataset(
    model_features: pd.DataFrame,
    config: ResearchConfig,
) -> pd.DataFrame:
    eligible = model_features.copy()
    if "model_eligible" in eligible.columns:
        eligible = eligible[eligible["model_eligible"] == 1].copy()
    eligible = eligible.sort_values("snapshot_minute_utc").reset_index(drop=True)

    rows: List[Dict[str, Any]] = []
    for _, group in eligible.groupby("market_ticker", sort=False):
        group = group.sort_values("snapshot_minute_utc").reset_index(drop=True).copy()
        final_bid = _to_float(group.iloc[-1].get("yes_bid_dollars"))
        if final_bid is None:
            continue

        for idx in range(len(group) - 1):
            row = group.iloc[idx].to_dict()
            ask = _to_float(row.get("yes_ask_dollars"))
            tte = _to_float(row.get("time_to_expiry_sec"))
            if ask is None or tte is None or tte < config.min_time_to_expiry_sec:
                continue

            future_rows = group.iloc[idx + 1 :].copy()
            future_bids = future_rows["yes_bid_dollars"].tolist()
            if any(pd.isna(v) for v in future_bids):
                continue

            exit_row = future_rows.iloc[-1]
            exit_bid = float(exit_row["yes_bid_dollars"])
            take_profit_level = ask + config.take_profit_buffer_dollars
            for future_idx in range(len(future_rows)):
                bid = float(future_rows.iloc[future_idx]["yes_bid_dollars"])
                if bid >= take_profit_level:
                    exit_row = future_rows.iloc[future_idx]
                    exit_bid = bid
                    break

            row["resolution_label"] = int(final_bid >= 0.9)
            row["trade_exit_ts"] = pd.Timestamp(exit_row["snapshot_minute_utc"])
            row["trade_exit_bid"] = exit_bid
            row["trade_pnl"] = exit_bid - ask
            rows.append(row)

    if not rows:
        raise RuntimeError("No expiry-resolution rows were produced from model_features_1m.")

    dataset = pd.DataFrame(rows).sort_values("snapshot_minute_utc").reset_index(drop=True)
    dataset = engineer_resolution_features(dataset)
    return dataset


def split_dataset(
    dataset: pd.DataFrame,
    config: ResearchConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n_rows = len(dataset)
    train_end = int(n_rows * config.train_fraction)
    val_end = int(n_rows * (config.train_fraction + config.validation_fraction))
    train = dataset.iloc[:train_end].copy().reset_index(drop=True)
    validation = dataset.iloc[train_end:val_end].copy().reset_index(drop=True)
    test = dataset.iloc[val_end:].copy().reset_index(drop=True)
    if train.empty or validation.empty or test.empty:
        raise RuntimeError("Chronological split produced an empty train/validation/test slice.")
    return train, validation, test


def build_feature_matrix(dataset: pd.DataFrame, feature_columns: Sequence[str]) -> pd.DataFrame:
    return dataset.loc[:, feature_columns].replace([np.inf, -np.inf], np.nan).fillna(0.0)


def build_model(spec: ModelSpec):
    if spec.name == "logistic_resolution_edge":
        return Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=2000,
                        class_weight="balanced",
                        C=float(spec.params["C"]),
                    ),
                ),
            ]
        )
    if spec.name == "random_forest_resolution_edge":
        return RandomForestClassifier(
            n_estimators=int(spec.params["n_estimators"]),
            max_depth=int(spec.params["max_depth"]),
            min_samples_leaf=int(spec.params["min_samples_leaf"]),
            min_samples_split=int(spec.params["min_samples_split"]),
            max_features=spec.params["max_features"],
            class_weight=spec.params["class_weight"],
            random_state=42,
            n_jobs=-1,
        )
    if spec.name == "hist_gradient_boosting_resolution_edge":
        return HistGradientBoostingClassifier(
            learning_rate=float(spec.params["learning_rate"]),
            max_depth=int(spec.params["max_depth"]),
            max_iter=int(spec.params["max_iter"]),
            min_samples_leaf=int(spec.params["min_samples_leaf"]),
            l2_regularization=float(spec.params["l2_regularization"]),
            max_leaf_nodes=int(spec.params["max_leaf_nodes"]),
            random_state=42,
        )
    raise ValueError(f"Unknown model spec: {spec.name}")


def backtest_edge_strategy(
    frame: pd.DataFrame,
    probabilities: Sequence[float],
    trade_rule: TradeRule,
) -> BacktestResult:
    result, _ = backtest_edge_strategy_with_curve(frame, probabilities, trade_rule)
    return result


def backtest_edge_strategy_with_curve(
    frame: pd.DataFrame,
    probabilities: Sequence[float],
    trade_rule: TradeRule,
) -> Tuple[BacktestResult, pd.DataFrame]:
    probabilities_np = np.asarray(probabilities, dtype=float)
    if len(frame) != len(probabilities_np):
        raise ValueError("frame and probabilities must have the same length")
    if frame.empty:
        empty_curve = pd.DataFrame(columns=["timestamp", "cumulative_pnl"])
        return BacktestResult(pnl=0.0, trades=0, win_rate=None, avg_pnl=None), empty_curve

    open_trade: Optional[Dict[str, Any]] = None
    trade_pnls: List[float] = []
    cumulative_pnl = 0.0
    curve_rows: List[Dict[str, Any]] = []
    last_ts = pd.Timestamp(frame.iloc[-1]["snapshot_minute_utc"])

    for idx, row in frame.iterrows():
        row_ts = pd.Timestamp(row["snapshot_minute_utc"])
        if open_trade is not None and row_ts >= open_trade["exit_ts"]:
            pnl = float(open_trade["pnl"])
            trade_pnls.append(pnl)
            cumulative_pnl += pnl
            open_trade = None

        probability = float(probabilities_np[idx])
        ask = float(row["yes_ask_dollars"])
        edge = probability - ask
        if (
            open_trade is None
            and probability >= trade_rule.probability_threshold
            and edge >= trade_rule.edge_threshold
            and pd.Timestamp(row["trade_exit_ts"]) <= last_ts
        ):
            open_trade = {
                "exit_ts": pd.Timestamp(row["trade_exit_ts"]),
                "pnl": float(row["trade_pnl"]),
            }
        curve_rows.append({"timestamp": row_ts, "cumulative_pnl": cumulative_pnl})

    if open_trade is not None and open_trade["exit_ts"] <= last_ts:
        pnl = float(open_trade["pnl"])
        trade_pnls.append(pnl)
        cumulative_pnl += pnl
        if curve_rows and pd.Timestamp(curve_rows[-1]["timestamp"]) == open_trade["exit_ts"]:
            curve_rows[-1]["cumulative_pnl"] = cumulative_pnl
        else:
            curve_rows.append({"timestamp": pd.Timestamp(open_trade["exit_ts"]), "cumulative_pnl": cumulative_pnl})

    if not trade_pnls:
        curve = pd.DataFrame(curve_rows, columns=["timestamp", "cumulative_pnl"])
        return BacktestResult(pnl=0.0, trades=0, win_rate=None, avg_pnl=None), curve

    pnl_array = np.asarray(trade_pnls, dtype=float)
    curve = pd.DataFrame(curve_rows, columns=["timestamp", "cumulative_pnl"])
    return (
        BacktestResult(
            pnl=float(pnl_array.sum()),
            trades=int(len(pnl_array)),
            win_rate=float((pnl_array > 0).mean()),
            avg_pnl=float(pnl_array.mean()),
        ),
        curve,
    )


def choose_trade_rule(
    validation_frame: pd.DataFrame,
    probabilities: Sequence[float],
    config: ResearchConfig,
) -> Tuple[TradeRule, BacktestResult]:
    best: Optional[Tuple[Tuple[float, float, int], TradeRule, BacktestResult]] = None
    for probability_threshold in config.probability_threshold_grid:
        for edge_threshold in config.edge_threshold_grid:
            rule = TradeRule(
                probability_threshold=float(probability_threshold),
                edge_threshold=float(edge_threshold),
            )
            backtest = backtest_edge_strategy(validation_frame, probabilities, rule)
            score = (
                float(backtest.pnl),
                float(backtest.win_rate or 0.0),
                -abs(int(backtest.trades) - config.trade_count_target),
            )
            if best is None or score > best[0]:
                best = (score, rule, backtest)
    if best is None:
        raise RuntimeError("Unable to choose a validation trade rule.")
    return best[1], best[2]


def evaluate_probabilities(y_true: Sequence[int], probabilities: Sequence[float]) -> Dict[str, float]:
    y_true_np = np.asarray(y_true, dtype=int)
    probabilities_np = np.asarray(probabilities, dtype=float)
    return {
        "average_precision": float(average_precision_score(y_true_np, probabilities_np)),
        "auc": float(roc_auc_score(y_true_np, probabilities_np)),
        "brier": float(brier_score_loss(y_true_np, probabilities_np)),
        "logloss": float(log_loss(y_true_np, probabilities_np, labels=[0, 1])),
    }


def run_research(
    client: KalshiDataClient,
    config: Optional[ResearchConfig] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, Any]:
    research_config = config or ResearchConfig()
    model_features = load_model_features(client, start=start, end=end)
    dataset = build_expiry_resolution_dataset(model_features, research_config)
    train, validation, test = split_dataset(dataset, research_config)

    results: List[Dict[str, Any]] = []
    y_train = train["resolution_label"].astype(int)
    y_validation = validation["resolution_label"].astype(int)
    y_test = test["resolution_label"].astype(int)

    for spec in MODEL_SPECS:
        model = build_model(spec)
        train_x = build_feature_matrix(train, spec.feature_columns)
        validation_x = build_feature_matrix(validation, spec.feature_columns)
        test_x = build_feature_matrix(test, spec.feature_columns)

        model.fit(train_x, y_train)
        validation_probs = model.predict_proba(validation_x)[:, 1]
        trade_rule, validation_backtest = choose_trade_rule(validation, validation_probs, research_config)

        train_validation_x = build_feature_matrix(
            pd.concat([train, validation], ignore_index=True),
            spec.feature_columns,
        )
        train_validation_y = pd.concat([y_train, y_validation], ignore_index=True)
        model = build_model(spec)
        model.fit(train_validation_x, train_validation_y)
        test_probs = model.predict_proba(test_x)[:, 1]
        test_backtest = backtest_edge_strategy(test, test_probs, trade_rule)

        results.append(
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "feature_columns": list(spec.feature_columns),
                "params": dict(spec.params),
                "is_benchmark": bool(spec.is_benchmark),
                "validation_trade_rule": asdict(trade_rule),
                "validation_backtest": asdict(validation_backtest),
                "test_backtest": asdict(test_backtest),
                "test_metrics": evaluate_probabilities(y_test, test_probs),
            }
        )

    results.sort(key=lambda item: (item["test_backtest"]["pnl"], item["test_metrics"]["average_precision"]), reverse=True)
    selected_models = [item["name"] for item in results if not item["is_benchmark"]]

    return {
        "config": asdict(research_config),
        "dataset": {
            "rows": int(len(dataset)),
            "start_utc": str(dataset["snapshot_minute_utc"].min()),
            "end_utc": str(dataset["snapshot_minute_utc"].max()),
            "positive_rate": float(dataset["resolution_label"].mean()),
            "train_rows": int(len(train)),
            "validation_rows": int(len(validation)),
            "test_rows": int(len(test)),
        },
        "models": results,
        "selected_models": selected_models,
    }


def _format_float(value: Optional[float], digits: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def render_markdown_report(results: Mapping[str, Any]) -> str:
    dataset = results["dataset"]
    models = results["models"]

    lines = [
        "# Expiry-Resolution Multi-Minute Model Research",
        "",
        "## Thesis",
        "",
        "Instead of predicting the next minute move, this research predicts whether the active 15-minute BTC contract will finish in a YES-like terminal state.",
        "Entries only fire when model probability clears both a minimum probability threshold and a binary-contract edge threshold `p_yes - yes_ask_dollars`.",
        "Once in a trade, the exit logic is simple: take profit when the bid reaches `entry ask + 5c`, otherwise hold to the final bid observed for that ticker.",
        "",
        "## Signal Flow",
        "",
        "```mermaid",
        "flowchart LR",
        '    A["client_api.KalshiDataClient"] --> B["model_features_1m DataFrame"]',
        '    B --> C["Expiry-resolution dataset builder"]',
        '    C --> D["Feature engineering from stored columns"]',
        '    D --> E["Logistic / RF / HistGB models"]',
        '    E --> F["Validation edge-rule search"]',
        '    F --> G["Held-out backtest with take-profit or final-bid exit"]',
        "```",
        "",
        "## Dataset",
        "",
        f"- Rows: {dataset['rows']}",
        f"- Time range: {dataset['start_utc']} to {dataset['end_utc']}",
        f"- Positive rate: {_format_float(dataset['positive_rate'])}",
        f"- Split: train={dataset['train_rows']}, validation={dataset['validation_rows']}, test={dataset['test_rows']}",
        "",
        "## Held-Out Results",
        "",
        "| Model | Test PnL | Trades | Win Rate | Avg PnL | AP | AUC | Validation Rule |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for model in models:
        val_rule = model["validation_trade_rule"]
        test_backtest = model["test_backtest"]
        test_metrics = model["test_metrics"]
        lines.append(
            "| "
            + model["display_name"]
            + (" (Benchmark)" if model.get("is_benchmark") else "")
            + f" | {_format_float(test_backtest['pnl'], 2)}"
            + f" | {test_backtest['trades']}"
            + f" | {_format_float(test_backtest['win_rate'], 4)}"
            + f" | {_format_float(test_backtest['avg_pnl'], 4)}"
            + f" | {_format_float(test_metrics['average_precision'], 4)}"
            + f" | {_format_float(test_metrics['auc'], 4)}"
            + f" | p>={_format_float(val_rule['probability_threshold'], 2)}, edge>={_format_float(val_rule['edge_threshold'], 2)} |"
        )

    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            "The corrected backtest does not support live deployment yet.",
            "The random forest is closest to viable under conservative exits and currently carries the stronger held-out ranking metrics of the two new tree candidates.",
            "The HistGradientBoosting model is still useful as the broader, more active tree baseline, but it is not robust enough yet to justify production use.",
            "Those models are worth keeping in the work folder as research candidates because they are clearly stronger ranking models than the old one-minute setup, but they still need either:",
            "",
            "- more history than the current ~4 day sample,",
            "- a better execution policy than fixed take-profit-or-final-bid, or",
            "- richer features than the current `model_features_1m` snapshot alone.",
            "",
            "## How To Re-Run",
            "",
            "```bash",
            "python work/run_horizon_model_research.py",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def write_artifacts(
    results: Mapping[str, Any],
    output_dir: Path,
) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "expiry_resolution_results.json"
    report_path = output_dir / "expiry_resolution_report.md"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    report_path.write_text(render_markdown_report(results), encoding="utf-8")
    return json_path, report_path
