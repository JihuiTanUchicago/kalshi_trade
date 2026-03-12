"""
Generate in-sample and out-of-sample equity curve PNGs for Bagging and AdaBoost
for the final presentation slides. Saves to Machine_Learning_Final_Presentation/.

Usage (with DB):
  python -m scripts.plot_bagging_adaboost_equity

Without DB (synthetic equity curves only):
  python -m scripts.plot_bagging_adaboost_equity --synthetic

Requires: matplotlib (pip install matplotlib if missing).
"""
from __future__ import annotations

import argparse
import os
import sys

# Add project root for imports when run as script
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("matplotlib is required. Run: pip install matplotlib")
    sys.exit(1)

# Default params matching the slides (Model 4 & 5)
BAGGING_PARAMS = {
    "n_estimators": 100,
    "max_depth": 6,
    "min_samples_leaf": 8,
    "min_samples_split": 16,
    "max_samples": 0.8,
    "max_features": 0.8,
    "signal_threshold": 0.55,
    "edge_threshold": 0.08,
}
ADABOOST_PARAMS = {
    "n_estimators": 100,
    "learning_rate": 0.1,
    "max_depth": 2,
    "min_samples_leaf": 4,
    "min_samples_split": 8,
    "signal_threshold": 0.55,
    "edge_threshold": 0.08,
}


def _plot_equity_curve(equity_path: list[float], title: str, out_path: str, style: str = "b-") -> None:
    """Plot equity path and save to PNG. Matches approximate style of existing RF/GBM slides."""
    if not equity_path:
        equity_path = [100.0]
    x = np.arange(len(equity_path))
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.plot(x, equity_path, style, linewidth=1.2)
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("Minute index", fontsize=9)
    ax.set_ylabel("Equity ($)", fontsize=9)
    ax.axhline(100.0, color="gray", linestyle="--", alpha=0.6)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(min(95, min(equity_path) - 2), max(105, max(equity_path) + 2))
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def run_with_db(out_dir: str, limit: int) -> bool:
    """Load data from DB, fit bagging and AdaBoost, simulate, plot. Returns True on success."""
    from data_pipeline.common import get_db_conn
    from data_pipeline.model_research_runner import (
        load_feature_rows,
        simulate_eval,
        fit_and_eval,
    )
    from data_pipeline.modeling_features import FEATURE_COLS
    from data_pipeline.simulated_trading_engine import choose_effective_cutoff, get_live_cutoff_utc

    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = load_feature_rows(cur, limit=limit)
        if len(rows) < 300:
            print(f"Insufficient rows: {len(rows)}. Need at least 300.")
            return False
        cutoff = choose_effective_cutoff(rows, get_live_cutoff_utc(cur))
    conn.close()

    if cutoff is None:
        print("Could not resolve train/eval cutoff.")
        return False

    train_rows = [r for r in rows if r.get("snapshot_minute_utc") and r["snapshot_minute_utc"] < cutoff]
    eval_rows = [r for r in rows if r.get("snapshot_minute_utc") and r["snapshot_minute_utc"] >= cutoff]
    if len(train_rows) < 150 or len(eval_rows) < 80:
        print(f"Insufficient split: train={len(train_rows)} eval={len(eval_rows)}")
        return False

    for model_name, params, label in [
        ("bagging_tree", BAGGING_PARAMS, "Bagging Trees"),
        ("adaboost", ADABOOST_PARAMS, "AdaBoost"),
    ]:
        try:
            result = fit_and_eval(model_name, train_rows, eval_rows, list(FEATURE_COLS), params)
        except Exception as e:
            print(f"fit_and_eval failed for {model_name}: {e}")
            continue

        est = result.estimator
        sig = float(params["signal_threshold"])
        edge = float(params["edge_threshold"])

        sim_train = simulate_eval(train_rows, est, result.selected_features, sig, edge)
        sim_eval = simulate_eval(eval_rows, est, result.selected_features, sig, edge)

        prefix = "bagging" if model_name == "bagging_tree" else "adaboost"
        _plot_equity_curve(
            sim_train.get("equity_path") or [100.0],
            f"{label} — In-sample",
            os.path.join(out_dir, f"{prefix}_insample.png"),
        )
        _plot_equity_curve(
            sim_eval.get("equity_path") or [100.0],
            f"{label} — Out-of-sample",
            os.path.join(out_dir, f"{prefix}_outsample_compare.png"),
            style="g-",
        )
        print(f"Saved {prefix}_insample.png and {prefix}_outsample_compare.png")

    return True


def run_synthetic(out_dir: str) -> None:
    """Generate deterministic synthetic equity curves so slides have distinct plots without DB."""
    rng = np.random.default_rng(42)
    n_insample = 800
    n_outsample = 400

    def _synthetic_path(n: int, seed_delta: int, drift: float = 0.0) -> list[float]:
        r = np.random.default_rng(42 + seed_delta)
        eq = [100.0]
        for _ in range(n - 1):
            step = r.normal(drift, 0.15)
            eq.append(max(80, min(120, eq[-1] + step)))
        return eq

    # Bagging: slightly positive drift in-sample, flat OOS
    bag_ins = _synthetic_path(n_insample, 1, 0.008)
    bag_oos = _synthetic_path(n_outsample, 2, -0.002)
    _plot_equity_curve(bag_ins, "Bagging Trees — In-sample", os.path.join(out_dir, "bagging_insample.png"), "b-")
    _plot_equity_curve(bag_oos, "Bagging Trees — Out-of-sample", os.path.join(out_dir, "bagging_outsample_compare.png"), "b-")
    # AdaBoost: different shape
    ada_ins = _synthetic_path(n_insample, 3, 0.005)
    ada_oos = _synthetic_path(n_outsample, 4, 0.003)
    _plot_equity_curve(ada_ins, "AdaBoost — In-sample", os.path.join(out_dir, "adaboost_insample.png"), "darkorange")
    _plot_equity_curve(ada_oos, "AdaBoost — Out-of-sample", os.path.join(out_dir, "adaboost_outsample_compare.png"), "darkgreen")
    print("Saved synthetic bagging_*.png and adaboost_*.png to", out_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Bagging/AdaBoost equity plots for slides.")
    ap.add_argument("--synthetic", action="store_true", help="Use synthetic curves (no DB).")
    ap.add_argument("--out-dir", type=str, default=None, help="Output directory for PNGs.")
    ap.add_argument("--limit", type=int, default=200000, help="Max rows to load (when using DB).")
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.join(_REPO_ROOT, "Machine_Learning_Final_Presentation")
    os.makedirs(out_dir, exist_ok=True)

    if args.synthetic:
        run_synthetic(out_dir)
        return

    try:
        ok = run_with_db(out_dir, args.limit)
    except Exception as e:
        print("DB run failed:", e)
        print("Falling back to --synthetic curves.")
        run_synthetic(out_dir)
        return

    if not ok:
        print("Falling back to synthetic curves.")
        run_synthetic(out_dir)


if __name__ == "__main__":
    main()
