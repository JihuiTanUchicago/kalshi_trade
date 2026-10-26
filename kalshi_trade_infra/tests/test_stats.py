"""Known-answer + edge-case checks for the statistical-validation toolkit (app/research/stats.py).

Shapes follow RESEARCH_PIPELINE_DESIGN.md §B.1 exactly (dict returns, string `stat`,
timestamp-based purging, plain-dict LORD++).
"""
import json
import math

import numpy as np

from app.research import stats


def test_norm_ppf_known_and_edges():
    assert abs(stats.norm_ppf(0.975) - 1.959963985) < 1e-6
    assert abs(stats.norm_ppf(0.5)) < 1e-9
    assert stats.norm_ppf(0.0) == float("-inf") and stats.norm_ppf(1.0) == float("inf")


def test_benjamini_hochberg_known_and_empty():
    # m=8, alpha=0.05: BH line p_(k) <= (k/8)*0.05 passes only at k=2.
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
    r = stats.benjamini_hochberg(p, 0.05)
    assert r["reject"] == [True, True, False, False, False, False, False, False]
    assert r["k"] == 2 and abs(r["threshold"] - 0.008) < 1e-12
    # Step-up reach-back: rank 2 fails its line but rank 3 passes -> ranks 1..3 all reject.
    su = stats.benjamini_hochberg([0.005, 0.03, 0.03, 0.9], 0.05)
    assert su["reject"] == [True, True, True, False] and su["k"] == 3
    # Edge: empty input.
    assert stats.benjamini_hochberg([], 0.05) == {"reject": [], "threshold": 0.0, "k": 0}


def test_benjamini_yekutieli_more_conservative():
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
    assert stats.benjamini_yekutieli(p, 0.05)["k"] <= stats.benjamini_hochberg(p, 0.05)["k"]
    assert stats.benjamini_yekutieli([], 0.05) == {"reject": [], "threshold": 0.0, "k": 0}


def test_lord_online_fdr_state_and_wealth():
    st = stats.lord_init(alpha=0.10)
    assert st == {"method": "LORD++", "alpha": 0.10, "w0": 0.05, "wealth": 0.05, "t": 0, "rejections": []}
    # Plain dict -> JSON-serializable for the app_fdr_state ledger.
    assert json.loads(json.dumps(st)) == st
    # Stream of tests: tiny p rejects test 1, never spend more than available wealth.
    state = st
    pvals = [1e-9, 0.9, 0.5, 1e-8, 0.4, 0.3]
    rejects = []
    for p in pvals:
        out = stats.lord_record(state, p)
        assert out["alpha_i"] <= state["wealth"] + 1e-12   # never overspend
        rejects.append(out["reject"])
        state = out["state"]
    assert rejects[0] is True                               # tiny p rejected early
    assert state["t"] == len(pvals) and state["rejections"][0] == 1
    # NaN consumes a slot but never rejects.
    assert stats.lord_record(state, float("nan"))["reject"] is False


def test_probabilistic_sharpe_ratio_half_and_edges():
    assert abs(stats.probabilistic_sharpe_ratio(0.0, 100, 0.0, 3.0) - 0.5) < 1e-12
    assert stats.probabilistic_sharpe_ratio(0.2, 500, 0.0, 3.0) > 0.5
    assert stats.probabilistic_sharpe_ratio(0.1, 1, 0.0, 3.0) == 0.5    # n<2 -> 0.5


def test_deflated_sharpe_below_psr_for_many_trials():
    psr = stats.probabilistic_sharpe_ratio(0.1, 250, 0.0, 3.0)
    dsr = stats.deflated_sharpe_ratio(0.1, 250, 0.0, 3.0, n_trials=100, var_trials=0.04)
    assert dsr < psr
    assert stats.expected_max_sharpe(1000, 0.04) > stats.expected_max_sharpe(10, 0.04)
    assert stats.expected_max_sharpe(100, 0.0) == 0.0                   # no variance -> no bar


def test_stationary_bootstrap_injected_edge_vs_null():
    # §B.1 runnable check: real edge -> p_value ~ 0; shuffled/null labels -> p_value ~ uniform.
    rng = np.random.default_rng(0)
    edge = list(rng.normal(0.05, 0.1, 300))     # mean clearly > 0
    null = list(rng.normal(0.0, 0.1, 300))      # mean ~ 0 (edge destroyed)
    r_edge = stats.stationary_bootstrap_ci(edge, "mean", n_boot=1000, seed=1)
    r_null = stats.stationary_bootstrap_ci(null, "mean", n_boot=1000, seed=1)
    assert set(r_edge) == {"point", "lo", "hi", "p_value", "se", "n_boot", "avg_block"}
    assert r_edge["p_value"] < 0.05 and r_edge["lo"] > 0.0   # significant, CI above 0
    assert r_null["p_value"] > 0.1                           # not significant
    assert r_edge["avg_block"] >= 2.0                        # Politis-White floored at 2


def test_bootstrap_edges_and_block_variant():
    # Constant series -> zero-width CI; empty -> NaNs.
    assert stats.stationary_bootstrap_ci([5.0, 5.0, 5.0, 5.0], "mean", seed=1)["lo"] == 5.0
    assert math.isnan(stats.stationary_bootstrap_ci([], "mean")["point"])
    # Fixed moving-block variant has the same shape and a usable p_value.
    rng = np.random.default_rng(2)
    r = stats.block_bootstrap_ci(list(rng.normal(0.05, 0.1, 300)), "mean", n_boot=800, block=5, seed=3)
    assert set(r) == {"point", "lo", "hi", "p_value", "se", "n_boot", "avg_block"}
    assert r["avg_block"] == 5.0 and r["p_value"] < 0.05
    # Sharpe stat is supported.
    assert "point" in stats.stationary_bootstrap_ci([0.01, -0.02, 0.03, 0.01, 0.02], "sharpe", seed=1)


def test_purged_walkforward_zero_settlement_overlap():
    # Hourly entries, each position settles 24h after entry -> long train/test overlap risk.
    entry = [i * 3600 for i in range(60)]
    settle = [e + 86400 for e in entry]
    splits = stats.purged_walkforward_splits(entry, settle, n_splits=4, embargo_seconds=7200)
    assert len(splits) == 4 and any(s["train_idx"] for s in splits)
    for s in splits:
        assert set(s["train_idx"]).isdisjoint(s["test_idx"])
        assert max(s["test_idx"]) < 60 and s["test_from_ts"] == entry[min(s["test_idx"])]
        for j in s["train_idx"]:
            # ZERO settlement overlap: no train sample settles at/after the test block entry.
            assert settle[j] < s["test_from_ts"]
            # Embargo respected: no train entry within embargo_seconds before the block.
            assert entry[j] < s["test_from_ts"] - 7200
    # Edge: too few samples for the requested folds -> no splits.
    assert stats.purged_walkforward_splits([0, 1, 2], [0, 1, 2], n_splits=5, embargo_seconds=0) == []


def test_demo_runs():
    stats.demo()
