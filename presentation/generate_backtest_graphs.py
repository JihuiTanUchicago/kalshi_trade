from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List
import re
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
    summary_rows: List[Dict[str, object]],
    output_path: Path,
) -> None:
    try:
        plt.style.use("seaborn-v0_8-whitegrid")
    except OSError:
        plt.style.use("seaborn-whitegrid")
    fig, (ax_curve, ax_stats) = plt.subplots(
        2,
        1,
        figsize=(12, 8),
        gridspec_kw={"height_ratios": [3.2, 1.2]},
    )
    palette = {
        "Random Forest Resolution Edge": "#1F5AA6",
        "HistGradientBoosting Resolution Edge": "#2E8B57",
    }
    line_styles = {
        "Random Forest Resolution Edge": "-",
        "HistGradientBoosting Resolution Edge": "-",
    }
    stats_by_model = {str(row["model"]): row for row in summary_rows}

    for column in [c for c in curve_table.columns if c != "timestamp"]:
        stats = stats_by_model.get(column, {})
        final_pnl = float(stats.get("plot_pnl", 0.0))
        win_rate = stats.get("plot_win_rate")
        legend_label = (
            f"{column} | PnL ${final_pnl:+.2f} | WR "
            f"{(100.0 * float(win_rate)):.1f}%"
            if win_rate is not None
            else f"{column} | PnL ${final_pnl:+.2f} | WR n/a"
        )
        ax_curve.plot(
            curve_table["timestamp"],
            curve_table[column] + 100.0,
            label=legend_label,
            linewidth=2.2,
            color=palette.get(column),
            linestyle=line_styles.get(column, "-"),
        )

    ax_curve.axhline(100.0, color="#444444", linewidth=1.0, linestyle=":")
    ax_curve.set_title(title, fontsize=15, weight="bold")
    ax_curve.set_xlabel("Timestamp (UTC)")
    ax_curve.set_ylabel("Equity ($)")
    ax_curve.text(
        0.01,
        0.02,
        subtitle,
        transform=ax_curve.transAxes,
        fontsize=10,
        color="#444444",
        va="bottom",
    )
    ax_curve.legend(frameon=True)

    labels = [str(row["model"]) for row in summary_rows]
    pnls = [float(row["plot_pnl"]) for row in summary_rows]
    win_rates = [
        (100.0 * float(row["plot_win_rate"])) if row["plot_win_rate"] is not None else 0.0
        for row in summary_rows
    ]
    x = range(len(labels))
    width = 0.36
    pnl_colors = [palette.get(label, "#666666") for label in labels]
    pnl_bars = ax_stats.bar(
        [i - width / 2 for i in x],
        pnls,
        width=width,
        color=pnl_colors,
        alpha=0.85,
        label="PnL ($)",
    )
    ax_stats.axhline(0.0, color="#444444", linewidth=1.0, linestyle=":")
    ax_stats.set_ylabel("PnL ($)")
    ax_stats.set_xticks(list(x))
    ax_stats.set_xticklabels(labels)

    ax_stats_wr = ax_stats.twinx()
    win_rate_bars = ax_stats_wr.bar(
        [i + width / 2 for i in x],
        win_rates,
        width=width,
        color=pnl_colors,
        alpha=0.35,
        label="Win Rate (%)",
    )
    ax_stats_wr.set_ylabel("Win Rate (%)")
    ax_stats_wr.set_ylim(0.0, 100.0)

    ax_stats.legend(
        [pnl_bars[0], win_rate_bars[0]],
        ["PnL ($)", "Win Rate (%)"],
        frameon=True,
        ncol=2,
        loc="upper right",
    )

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _slugify_model_name(name: str) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"[^a-z0-9]+", "_", spaced.lower()).strip("_")


def _plot_single_model_backtest(
    model_name: str,
    validation_curve: pd.DataFrame,
    test_curve: pd.DataFrame,
    summary_row: Dict[str, object],
    output_path: Path,
) -> None:
    try:
        plt.style.use("seaborn-v0_8-whitegrid")
    except OSError:
        plt.style.use("seaborn-whitegrid")

    palette = {
        "Random Forest Resolution Edge": "#1F5AA6",
        "HistGradientBoosting Resolution Edge": "#2E8B57",
    }
    color = palette.get(model_name, "#444444")

    fig, (ax_validation, ax_test) = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle(f"{model_name} Backtest (Starting Cash $100)", fontsize=16, weight="bold")

    plot_specs = [
        (
            ax_validation,
            validation_curve,
            "In-Sample / Validation Slice",
            "validation_pnl",
            "validation_trades",
            "validation_win_rate",
        ),
        (
            ax_test,
            test_curve,
            "Out-of-Sample / Held-Out Test Slice",
            "test_pnl",
            "test_trades",
            "test_win_rate",
        ),
    ]

    for ax, curve, split_label, pnl_key, trades_key, win_rate_key in plot_specs:
        ax.plot(curve["timestamp"], curve[model_name] + 100.0, color=color, linewidth=2.4)
        ax.axhline(100.0, color="#444444", linewidth=1.0, linestyle=":")
        ax.set_title(split_label, fontsize=12, loc="left")
        ax.set_ylabel("Equity ($)")
        ax.text(
            0.01,
            0.98,
            (
                f"PnL ${float(summary_row[pnl_key]):+.2f} | "
                f"Trades {int(summary_row[trades_key])} | "
                f"Win Rate {(100.0 * float(summary_row[win_rate_key])):.1f}%"
            ),
            transform=ax.transAxes,
            va="top",
            fontsize=10,
            color="#333333",
            bbox={
                "boxstyle": "round,pad=0.3",
                "facecolor": "white",
                "edgecolor": "#cccccc",
                "alpha": 0.9,
            },
        )

    ax_validation.text(
        0.01,
        0.03,
        (
            f"Buy rule: p_yes >= {float(summary_row['probability_threshold']):.2f} and "
            f"p_yes - ask >= {float(summary_row['edge_threshold']):.2f}"
        ),
        transform=ax_validation.transAxes,
        va="bottom",
        fontsize=10,
        color="#444444",
    )
    ax_test.set_xlabel("Timestamp (UTC)")

    fig.autofmt_xdate()
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.97])
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
        if spec.is_benchmark:
            continue
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
                "validation_win_rate": validation_result.win_rate,
                "test_pnl": test_result.pnl,
                "test_trades": test_result.trades,
                "test_win_rate": test_result.win_rate,
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
    validation_plot_rows = [
        {
            "model": row["model"],
            "plot_pnl": row["validation_pnl"],
            "plot_win_rate": row["validation_win_rate"],
        }
        for row in summary_rows
    ]
    test_plot_rows = [
        {
            "model": row["model"],
            "plot_pnl": row["test_pnl"],
            "plot_win_rate": row["test_win_rate"],
        }
        for row in summary_rows
    ]
    _plot_curve_table(
        validation_table,
        "In-Sample Backtest (Validation Slice, Starting Cash $100)",
        validation_subtitle,
        validation_plot_rows,
        validation_png,
    )
    _plot_curve_table(
        test_table,
        "Out-of-Sample Backtest (Held-Out Test Slice, Starting Cash $100)",
        test_subtitle,
        test_plot_rows,
        test_png,
    )

    model_pngs: List[Path] = []
    for row in summary_rows:
        model_name = str(row["model"])
        model_png = output_dir / f"{_slugify_model_name(model_name)}_backtest.png"
        _plot_single_model_backtest(
            model_name=model_name,
            validation_curve=validation_table.loc[:, ["timestamp", model_name]].copy(),
            test_curve=test_table.loc[:, ["timestamp", model_name]].copy(),
            summary_row=row,
            output_path=model_png,
        )
        model_pngs.append(model_png)

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
    for model_png in model_pngs:
        print(f"Saved: {model_png}")


if __name__ == "__main__":
    main()
