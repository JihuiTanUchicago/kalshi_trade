from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import pandas as pd

from client_api import KalshiDataClient
from work.horizon_models import (
    DEFAULT_BASE_URL,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    MODEL_SPECS,
    ResearchConfig,
    backtest_edge_strategy_with_curve,
    build_expiry_resolution_dataset,
    build_feature_matrix,
    build_model,
    choose_trade_rule,
    load_model_features,
    split_dataset,
)


def _curve_table(curves: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    merged = None
    for label, curve in curves.items():
        part = curve.rename(columns={"cumulative_pnl": label}).copy()
        if merged is None:
            merged = part
        else:
            merged = merged.merge(part, on="timestamp", how="outer")
    if merged is None:
        return pd.DataFrame(columns=["timestamp"])
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    model_cols = [c for c in merged.columns if c != "timestamp"]
    merged[model_cols] = merged[model_cols].ffill().fillna(0.0)
    return merged


def _plot_curve_table(
    curve_table: pd.DataFrame,
    title: str,
    subtitle: str,
    output_path: Path,
) -> None:
    try:
        plt.style.use("seaborn-v0_8-whitegrid")
    except OSError:
        plt.style.use("seaborn-whitegrid")
    fig, ax = plt.subplots(figsize=(12, 6))
    palette = {
        "Logistic Resolution Edge (Benchmark)": "#8B5E3C",
        "Random Forest Resolution Edge": "#1F5AA6",
        "HistGradientBoosting Resolution Edge": "#2E8B57",
    }
    line_styles = {
        "Logistic Resolution Edge (Benchmark)": "--",
        "Random Forest Resolution Edge": "-",
        "HistGradientBoosting Resolution Edge": "-",
    }

    for column in [c for c in curve_table.columns if c != "timestamp"]:
        ax.plot(
            curve_table["timestamp"],
            curve_table[column],
            label=column,
            linewidth=2.2,
            color=palette.get(column),
            linestyle=line_styles.get(column, "-"),
        )

    ax.axhline(0.0, color="#444444", linewidth=1.0, linestyle=":")
    ax.set_title(title, fontsize=15, weight="bold")
    ax.set_xlabel("Timestamp (UTC)")
    ax.set_ylabel("Cumulative Realized PnL ($)")
    ax.text(
        0.01,
        0.02,
        subtitle,
        transform=ax.transAxes,
        fontsize=10,
        color="#444444",
        va="bottom",
    )
    ax.legend(frameon=True)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate in-sample and out-of-sample backtest graphs.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--take-profit-buffer", type=float, default=0.05)
    parser.add_argument("--min-time-to-expiry-sec", type=int, default=120)
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = KalshiDataClient(
        base_url=args.base_url,
        username=args.username,
        password=args.password,
    )
    config = ResearchConfig(
        take_profit_buffer_dollars=float(args.take_profit_buffer),
        min_time_to_expiry_sec=int(args.min_time_to_expiry_sec),
    )

    model_features = load_model_features(client, start=args.start, end=args.end)
    dataset = build_expiry_resolution_dataset(model_features, config)
    train, validation, test = split_dataset(dataset, config)
    y_train = train["resolution_label"].astype(int)
    y_validation = validation["resolution_label"].astype(int)

    validation_curves: Dict[str, pd.DataFrame] = {}
    test_curves: Dict[str, pd.DataFrame] = {}
    summary_rows: List[Dict[str, object]] = []

    for spec in MODEL_SPECS:
        label = spec.display_name + (" (Benchmark)" if spec.is_benchmark else "")
        model = build_model(spec)
        train_x = build_feature_matrix(train, spec.feature_columns)
        validation_x = build_feature_matrix(validation, spec.feature_columns)
        test_x = build_feature_matrix(test, spec.feature_columns)

        model.fit(train_x, y_train)
        validation_probs = model.predict_proba(validation_x)[:, 1]
        trade_rule, validation_backtest = choose_trade_rule(validation, validation_probs, config)
        validation_result, validation_curve = backtest_edge_strategy_with_curve(validation, validation_probs, trade_rule)

        train_validation_x = build_feature_matrix(
            pd.concat([train, validation], ignore_index=True),
            spec.feature_columns,
        )
        train_validation_y = pd.concat([y_train, y_validation], ignore_index=True)
        model = build_model(spec)
        model.fit(train_validation_x, train_validation_y)
        test_probs = model.predict_proba(test_x)[:, 1]
        test_result, test_curve = backtest_edge_strategy_with_curve(test, test_probs, trade_rule)

        validation_curves[label] = validation_curve
        test_curves[label] = test_curve
        summary_rows.append(
            {
                "model": label,
                "validation_pnl": validation_result.pnl,
                "validation_trades": validation_result.trades,
                "test_pnl": test_result.pnl,
                "test_trades": test_result.trades,
                "probability_threshold": trade_rule.probability_threshold,
                "edge_threshold": trade_rule.edge_threshold,
            }
        )

    validation_table = _curve_table(validation_curves)
    test_table = _curve_table(test_curves)

    validation_csv = output_dir / "in_sample_equity_curves.csv"
    test_csv = output_dir / "out_of_sample_equity_curves.csv"
    summary_csv = output_dir / "backtest_summary.csv"
    validation_png = output_dir / "in_sample_backtest.png"
    test_png = output_dir / "out_of_sample_backtest.png"

    validation_table.to_csv(validation_csv, index=False)
    test_table.to_csv(test_csv, index=False)
    pd.DataFrame(summary_rows).to_csv(summary_csv, index=False)

    validation_subtitle = (
        "Validation slice used for trade-rule selection after model fitting on the train slice. "
        f"Take-profit buffer = ${config.take_profit_buffer_dollars:.2f}, min entry TTE = {config.min_time_to_expiry_sec}s."
    )
    test_subtitle = (
        "Held-out test slice after refitting each model on train + validation with the validation-selected trade rule locked."
    )
    _plot_curve_table(validation_table, "In-Sample Backtest (Validation Slice)", validation_subtitle, validation_png)
    _plot_curve_table(test_table, "Out-of-Sample Backtest (Held-Out Test Slice)", test_subtitle, test_png)

    print(
        pd.DataFrame(summary_rows)
        .sort_values("test_pnl", ascending=False)
        .to_string(index=False)
    )
    print(f"\nSaved: {validation_png}")
    print(f"Saved: {test_png}")
    print(f"Saved: {validation_csv}")
    print(f"Saved: {test_csv}")
    print(f"Saved: {summary_csv}")


if __name__ == "__main__":
    main()
