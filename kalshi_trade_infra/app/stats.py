"""Statistical validity toolkit for the Tau research engine. Pure math; no I/O, no DB,
no LLM. Reuses app.quant for the normal CDF (and any pricing/fee/drawdown need); it never
re-implements fees, drawdown, or sizing. See RESEARCH_PIPELINE_DESIGN.md §B.1 — that spec is
the contract the gatekeeper is written against, so signatures/return shapes here are exact.

What each tool is for and its key assumption (the gatekeeper needs to pick the right one):
- `benjamini_hochberg` / `benjamini_yekutieli`: FDR control for a BATCH of finalists. BH
  assumes independent / positively-dependent (PRDS) tests; BY is valid under ARBITRARY
  dependence (lower power — correlated strategies).
- `lord_*`: LORD++ online FDR for the CONTINUOUSLY-running agent; plain-dict state so the
  gatekeeper persists it verbatim.
- `probabilistic_sharpe_ratio` / `deflated_sharpe_ratio`: Sharpe significance corrected for
  non-normality (PSR) and for selection across many trials (DSR). Assume IID observations.
- `stationary_bootstrap_ci` / `block_bootstrap_ci`: autocorrelation-robust CIs + the PRIMARY
  one-sided validation p-value. Assume (weak) stationarity.
- `purged_walkforward_splits`: leak-free time-series CV. Purges train samples that settle into
  the test block and embargoes the run-up; it does NOT fix lookahead baked into a feature.

VALIDITY CAVEAT (§F): online-FDR / a p-value budget bounds the error RATE across a stream, it
does not sanitize a leaked or reused holdout. A budget does not un-leak a contaminated test.

Normal CDF (Φ) is reused from app.quant (math.erf). Φ⁻¹ is `norm_ppf` (Acklam, no scipy).
numpy is used for the bootstrap resampling/percentiles (already a pinned dependency; invisible
to callers — the public contract is pure python types).
ponytail: the stationary bootstrap is still an O(n_boot·n) python loop, over raw PCG64 words read in
bulk since profiling showed it hot (_pcg64_stationary_rows: same draws, ~5x faster).
"""
from __future__ import annotations

import math

import numpy as np

from app.quant import _norm_cdf  # reuse: standard normal CDF (math.erf), no duplication

EULER_MASCHERONI = 0.5772156649015329

# LORD++ decaying spending sequence normalizer: makes sum_{j>=1} gamma(j) = 1 for
# gamma(j) = C*log(max(j,2))/(j*exp(sqrt(log j))) (onlineFDR default, Robertson et al.).
_LORD_GAMMA_C = 0.07720838

__all__ = [
    "norm_ppf",
    "benjamini_hochberg",
    "benjamini_yekutieli",
    "lord_init",
    "lord_gamma",
    "lord_alpha",
    "lord_record",
    "probabilistic_sharpe_ratio",
    "expected_max_sharpe",
    "deflated_sharpe_ratio",
    "stationary_bootstrap_ci",
    "block_bootstrap_ci",
    "purged_walkforward_splits",
    "fit_logistic",
]


# ---- normal helpers -------------------------------------------------------------------

def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Φ⁻¹) via Acklam's rational approximation, p in (0,1).

    Peter Acklam (2003). |error| < 1.15e-9 over the full range. Returns -inf at p<=0 and
    +inf at p>=1. Needed by PSR/DSR.
    """
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
           ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


# ---- 1. Benjamini-Hochberg / -Yekutieli FDR (batch finalists) ------------------------

def benjamini_hochberg(pvalues: list[float], alpha: float = 0.10) -> dict:
    """Step-up FDR control for a BATCH of independent/PRDS tests.

    Sort p(1)<=...<=p(m); let k = max{i : p(i) <= (i/m)*alpha}; reject all hypotheses with
    p <= p(k). Returns {"reject": list[bool] (input order), "threshold": p(k) cutoff (0 if
    none reject), "k": # rejected}. NaN p-values are treated as 1.0 (never rejected).
    """
    m = len(pvalues)
    if m == 0:
        return {"reject": [], "threshold": 0.0, "k": 0}
    clean = [1.0 if (p is None or math.isnan(p)) else float(p) for p in pvalues]
    order = sorted(range(m), key=lambda i: clean[i])  # ascending by p-value
    k_max = 0  # largest 1-indexed rank passing the BH line = number rejected
    threshold = 0.0
    for rank, idx in enumerate(order, start=1):
        if clean[idx] <= (rank / m) * alpha:
            k_max = rank
            threshold = clean[idx]
    reject = [False] * m
    for rank, idx in enumerate(order, start=1):
        if rank <= k_max:
            reject[idx] = True
    return {"reject": reject, "threshold": threshold, "k": k_max}


def benjamini_yekutieli(pvalues: list[float], alpha: float = 0.10) -> dict:
    """BH under ARBITRARY dependence: divide alpha by the harmonic number H_m = sum 1/i,
    then run the step-up. Same dict shape as `benjamini_hochberg`. More conservative."""
    m = len(pvalues)
    if m == 0:
        return {"reject": [], "threshold": 0.0, "k": 0}
    harmonic = sum(1.0 / i for i in range(1, m + 1))
    return benjamini_hochberg(pvalues, alpha / harmonic)


# ---- 2. LORD++ online FDR (continuously-running agent) -------------------------------
# State is a plain dict so the gatekeeper persists it verbatim in app_fdr_state
# (columns method / alpha / w0 / wealth / t / rejections_json).

def lord_init(alpha: float = 0.10, w0: float | None = None) -> dict:
    """Fresh alpha-wealth state. w0 defaults to alpha/2."""
    w0 = alpha / 2.0 if w0 is None else float(w0)
    return {"method": "LORD++", "alpha": float(alpha), "w0": w0,
            "wealth": w0, "t": 0, "rejections": []}


def lord_gamma(j: int) -> float:
    """Nonincreasing spending sequence, sum_j gamma(j) = 1 (C ≈ 0.07720838).
    gamma(j) = C*log(max(j,2))/(j*exp(sqrt(log j))) for j>=1, else 0. Deterministic — the
    gatekeeper must use the SAME sequence on replay/audit."""
    if j < 1:
        return 0.0
    return _LORD_GAMMA_C * math.log(max(j, 2)) / (j * math.exp(math.sqrt(math.log(j))))


def lord_alpha(state: dict) -> float:
    """The alpha_t to spend on the NEXT test (t = state['t']+1), LORD++ (Ramdas et al. 2017):
      alpha_t = gamma(t)*w0 + (alpha-w0)*gamma(t-tau_1) + alpha*sum_{j>=2} gamma(t-tau_j),
    dropping terms with (t - tau_j) <= 0."""
    t = state["t"] + 1
    alpha = state["alpha"]
    w0 = state["w0"]
    rej = state["rejections"]
    level = lord_gamma(t) * w0
    if rej:
        tau1 = rej[0]
        if t - tau1 > 0:
            level += (alpha - w0) * lord_gamma(t - tau1)
        for tau in rej[1:]:
            if t - tau > 0:
                level += alpha * lord_gamma(t - tau)
    return level


def lord_record(state: dict, pvalue: float) -> dict:
    """Advance one test: reject iff pvalue <= lord_alpha(state). Pure — returns a NEW state.

    Returns {"t", "alpha_i", "reject", "state": <new state dict>}. Wealth bookkeeping
    (spend alpha_t, earn back (alpha - w0) on the first rejection, alpha on later ones) keeps
    the persisted `wealth` field meaningful; the LORD++ level itself is computed directly from
    the rejection times. A NaN p-value consumes a test slot but never rejects.
    """
    t = state["t"] + 1
    alpha_t = lord_alpha(state)
    reject = pvalue is not None and not math.isnan(pvalue) and float(pvalue) <= alpha_t
    payout = 0.0
    if reject:
        payout = (state["alpha"] - state["w0"]) if not state["rejections"] else state["alpha"]
    new_state = {
        "method": state["method"],
        "alpha": state["alpha"],
        "w0": state["w0"],
        "wealth": state["wealth"] - alpha_t + payout,
        "t": t,
        "rejections": state["rejections"] + ([t] if reject else []),
    }
    return {"t": t, "alpha_i": alpha_t, "reject": bool(reject), "state": new_state}


# ---- 3. Probabilistic & Deflated Sharpe (Bailey & Lopez de Prado) --------------------

def probabilistic_sharpe_ratio(sr: float, n: int, skew: float, kurt: float,
                               sr_benchmark: float = 0.0) -> float:
    """PSR(sr*) = P(true SR > sr*). sr, sr_benchmark per-trade (non-annualized) on the SAME n
    observations; kurt is full (non-excess) kurtosis (normal = 3).
      PSR = Φ( (sr - sr*)*sqrt(n-1) / sqrt(1 - skew*sr + ((kurt-1)/4)*sr^2) ).
    Returns a probability in (0,1). n<2 or non-positive/non-finite denom -> 0.5."""
    if n < 2:
        return 0.5
    denom = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denom <= 0.0 or not math.isfinite(denom):
        return 0.5
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom)
    return _norm_cdf(z)


def expected_max_sharpe(n_trials: int, var_trials: float) -> float:
    """SR0 = the Sharpe expected as the MAX over n_trials zero-edge strategies with cross-trial
    Sharpe variance var_trials (Bailey-LdP):
      SR0 = sqrt(var_trials)*[ (1-g)*norm_ppf(1 - 1/N) + g*norm_ppf(1 - 1/(N*e)) ],
      g = Euler-Mascheroni, N = max(n_trials, 2). Returns 0.0 if var_trials <= 0."""
    N = max(int(n_trials), 2)
    sigma = math.sqrt(max(var_trials, 0.0))
    if sigma == 0.0:
        return 0.0
    g = EULER_MASCHERONI
    return sigma * ((1.0 - g) * norm_ppf(1.0 - 1.0 / N) + g * norm_ppf(1.0 - 1.0 / (N * math.e)))


def deflated_sharpe_ratio(sr: float, n: int, skew: float, kurt: float,
                          n_trials: int, var_trials: float) -> float:
    """DSR = PSR evaluated at sr* = expected_max_sharpe(n_trials, var_trials): the probability
    the observed Sharpe beats the best of n_trials lucky nulls. n_trials is the AUDITED count
    of hypotheses that competed for this validation evidence (from the ledger)."""
    sr0 = expected_max_sharpe(n_trials, var_trials)
    return probabilistic_sharpe_ratio(sr, n, skew, kurt, sr_benchmark=sr0)


# ---- logistic regression (ridge, pure python) ----------------------------------------
#
# A learned linear classifier is the classic ML entry point for a strategy: fit P(outcome |
# features) on the RESEARCH fold, freeze the coefficients, judge the frozen model on held-out
# data. This is the fitter the spec's `logistic`/`calibration` model kinds use. Pure python +
# L2 (ridge): the regularizer is a principled shrinkage prior that keeps a small fit from
# memorizing noise, and it bounds the coefficients so a near-separable research fold cannot blow
# them up. Features are standardized internally (so one learning rate works across BTC's wildly
# different feature scales), then the weights are folded back onto the RAW features so the stored
# spec reads `intercept + sum(coef_i * feature_i)` with nothing else to carry.
# ponytail: full-batch gradient descent, fixed iters — O(iters*n*d) python, sub-second for a few
# features over a research window; swap in numpy/IRLS only if a much larger feature set is ever fit.


def fit_logistic(X: "list[list[float]]", y: "list[float]", l2: float = 1.0,
                 iters: int = 400, lr: float = 0.5) -> "tuple[list[float], float]":
    """Ridge logistic regression P(y=1) = sigmoid(intercept + coef . x), fit by gradient descent.

    X is n rows of d features, y is n labels in {0,1}. Returns (coef, intercept) on the RAW
    (un-standardized) feature scale, so the caller stores exactly those d+1 numbers. l2 is the
    ridge strength on the STANDARDIZED weights (0 = unregularized). Deterministic: no randomness,
    so the same research fold always yields the same frozen model (a pre-registration must be
    reproducible). Raises ValueError on empty/ragged input or a width mismatch."""
    n = len(X)
    if n == 0:
        raise ValueError("fit_logistic needs at least one row")
    if len(y) != n:
        raise ValueError("X and y must have the same length")
    d = len(X[0])
    if any(len(row) != d for row in X):
        raise ValueError("every row of X must have the same width")
    yv = [1.0 if v else 0.0 for v in y]

    # Standardize each column (population mean/std); a constant column gets std=1 so it drops out.
    mean = [sum(row[j] for row in X) / n for j in range(d)]
    std = []
    for j in range(d):
        var = sum((row[j] - mean[j]) ** 2 for row in X) / n
        std.append(math.sqrt(var) if var > 1e-18 else 1.0)
    Xs = [[(row[j] - mean[j]) / std[j] for j in range(d)] for row in X]

    w = [0.0] * d
    b = 0.0
    for _ in range(max(1, iters)):
        gw = [0.0] * d
        gb = 0.0
        for i in range(n):
            z = b + sum(w[j] * Xs[i][j] for j in range(d))
            z = 30.0 if z > 30.0 else -30.0 if z < -30.0 else z
            err = 1.0 / (1.0 + math.exp(-z)) - yv[i]
            gb += err
            xi = Xs[i]
            for j in range(d):
                gw[j] += err * xi[j]
        gb /= n
        b -= lr * gb
        for j in range(d):
            w[j] = w[j] - lr * (gw[j] / n + l2 * w[j] / n)

    # Fold standardization back into raw-feature coefficients: z = b + sum(w_j*(x_j-mean_j)/std_j)
    # = (b - sum(w_j*mean_j/std_j)) + sum((w_j/std_j)*x_j).
    coef = [w[j] / std[j] for j in range(d)]
    intercept = b - sum(w[j] * mean[j] / std[j] for j in range(d))
    return coef, intercept


# ---- 4. Autocorrelation-robust bootstrap CIs -----------------------------------------

def _stat_value(a: np.ndarray, stat: str) -> float:
    """Point statistic of a return series: "mean" or per-trade "sharpe" (mean / sample std)."""
    if stat == "mean":
        return float(np.mean(a))
    if stat == "sharpe":
        if len(a) < 2:
            return 0.0
        sd = float(np.std(a, ddof=1))
        return float(np.mean(a) / sd) if sd > 0.0 else 0.0
    raise ValueError(f"stat must be 'mean' or 'sharpe', got {stat!r}")


def _flat_top(s: np.ndarray) -> np.ndarray:
    """Politis-White flat-top lag kernel: 1 for |s|<=1/2, 2(1-|s|) for 1/2<|s|<=1, else 0."""
    s = np.abs(s)
    return np.where(s <= 0.5, 1.0, np.where(s <= 1.0, 2.0 * (1.0 - s), 0.0))


def _politis_white_avg_block(x: np.ndarray) -> float:
    """Politis-White (2004) automatic block length for the stationary bootstrap, floored at 2.

    b_opt = (2*G^2 / D_sb)^(1/3) * n^(1/3), with G = sum_k lam(k/M)*|k|*R(k),
    D_sb = 2*(sum_k lam(k/M)*R(k))^2, R = autocovariance, M = 2*m_hat from the flat-top rule.
    """
    n = len(x)
    if n < 4:
        return 2.0
    e = x - x.mean()
    kn = max(5, int(math.ceil(math.log10(n))))
    m_max = min(int(math.ceil(math.sqrt(n))) + kn, n - 1)
    acv = np.array([float(np.sum(e[k:] * e[:n - k])) / n for k in range(m_max + 1)])
    if acv[0] <= 0.0:
        return 2.0
    rho = acv / acv[0]
    cv = 2.0 * math.sqrt(math.log10(n) / n)
    m_hat = m_max
    for m in range(1, m_max - kn + 1):
        if np.all(np.abs(rho[m:m + kn]) < cv):
            m_hat = m - 1
            break
    M = min(2 * max(m_hat, 1), m_max)
    ks = np.arange(-M, M + 1)
    lam = _flat_top(ks / M)
    ac = acv[np.abs(ks)]
    G = float(np.sum(lam * np.abs(ks) * ac))
    g = float(np.sum(lam * ac))
    d_sb = 2.0 * g * g
    if d_sb <= 0.0 or G <= 0.0:
        return 2.0
    b = (2.0 * G * G / d_sb) ** (1.0 / 3.0) * n ** (1.0 / 3.0)
    return max(2.0, min(b, math.ceil(3.0 * math.sqrt(n))))


def _ci_result(boot: np.ndarray, point: float, alpha: float, n_boot: int, avg_block: float) -> dict:
    """Assemble the common bootstrap result dict (percentile CI + one-sided p-value at 0)."""
    return {
        "point": float(point),
        "lo": float(np.percentile(boot, 100.0 * (alpha / 2.0))),
        "hi": float(np.percentile(boot, 100.0 * (1.0 - alpha / 2.0))),
        "p_value": float(np.mean(boot <= 0.0)),  # one-sided mass at/below 0
        # Bootstrap standard error of the statistic (autocorrelation-robust via the resampling
        # scheme). Lets a caller form a continuous normal-tail p-value when the empirical
        # mass above is pinned at its 1/n_boot resolution floor.
        "se": float(np.std(boot, ddof=1)) if len(boot) > 1 else float("nan"),
        "n_boot": int(n_boot),
        "avg_block": float(avg_block),
    }


def _degenerate_result(x: np.ndarray, stat: str, n_boot: int, avg_block: float) -> dict | None:
    """Handle empty (NaNs) and single-sample (zero-width) series; None if non-degenerate."""
    n = len(x)
    if n == 0:
        return {"point": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "p_value": float("nan"), "se": float("nan"), "n_boot": int(n_boot),
                "avg_block": float(avg_block)}
    if n == 1:
        pt = _stat_value(x, stat)
        return {"point": pt, "lo": pt, "hi": pt, "p_value": float(pt <= 0.0), "se": 0.0,
                "n_boot": int(n_boot), "avg_block": float(avg_block)}
    return None


def stationary_bootstrap_ci(x: list[float], stat: str = "mean", n_boot: int = 2000,
                            avg_block: float = 0.0, alpha: float = 0.10, seed: int = 0) -> dict:
    """Politis-Romano stationary bootstrap CI for a serially-correlated return series (ordered
    by entry time). Geometric block length with mean `avg_block` (wrap-around); avg_block<=0
    (or <2) selects the Politis-White automatic rule, floored at 2. stat in {"mean","sharpe"}.

    Returns {"point","lo","hi","p_value","n_boot","avg_block"}. p_value is the one-sided
    bootstrap mass at/below 0 — the PRIMARY validation p-value. Deterministic given seed.
    """
    arr = np.asarray(x, dtype=float)
    n = len(arr)
    ab = avg_block if avg_block and avg_block >= 2.0 else _politis_white_avg_block(arr) if n >= 2 else 2.0
    degenerate = _degenerate_result(arr, stat, n_boot, ab)
    if degenerate is not None:
        return degenerate
    p = 1.0 / ab  # geometric block-continuation probability
    rng = np.random.default_rng(seed)
    boot = np.empty(n_boot, dtype=float)
    if isinstance(rng.bit_generator, np.random.PCG64) and n < 2 ** 32:
        for b, idx in enumerate(_pcg64_stationary_rows(rng.bit_generator, n, p, n_boot)):
            boot[b] = _stat_value(arr[idx], stat)
        return _ci_result(boot, _stat_value(arr, stat), alpha, n_boot, ab)
    for b in range(n_boot):
        idx = np.empty(n, dtype=np.int64)
        i = int(rng.integers(0, n))
        idx[0] = i
        for t in range(1, n):
            if rng.random() < p:
                i = int(rng.integers(0, n))  # start a new block
            else:
                i = (i + 1) % n              # continue block, wrap around
            idx[t] = i
        boot[b] = _stat_value(arr[idx], stat)
    return _ci_result(boot, _stat_value(arr, stat), alpha, n_boot, ab)


_M32 = 0xFFFFFFFF
_INV53 = 1.0 / 9007199254740992.0  # 2**-53: numpy's next_double scale
_RAW_CHUNK = 1 << 16  # raw words fetched at a time


def _pcg64_stationary_rows(bg: "np.random.PCG64", n: int, p: float, n_boot: int):
    """The stationary bootstrap's index rows, exactly as the loop above draws them from
    Generator(bg) (`rng.integers(0, n)` to start a block, `rng.random() < p` to continue one), read
    off bg's raw 64-bit words fetched in bulk instead of ~3 numpy calls per resampled point (~5x
    faster: 2.4s -> 0.47s for 800 points x 2,000 resamples, measured 2026-10-26; that is a paper
    strategy's live-readiness check, on the Deploy board's request path). Same draws, so the same
    p-values bit for bit (tests/test_stats_bootstrap_exact.py holds it to the loop). The emulation is
    numpy's own:
    random() = (next64 >> 11) * 2**-53; integers(0, n) = Lemire's bounded draw on next32, where next32
    hands out the low then the high half of one 64-bit word (PCG64's has_uint32 buffer, which random()
    leaves alone), rejecting while the product's low word is under (2**32 - n) % n. bg must be fresh."""
    chunk = max(_RAW_CHUNK, 4 * n + 64)

    def fetch(w, isnew, j):
        raw = bg.random_raw(chunk)
        return w[j:] + raw.tolist(), isnew[j:] + (((raw >> np.uint64(11)) * _INV53) < p).tolist()

    w: list = []
    isnew: list = []
    j, has, half = 0, False, 0
    thr = ((_M32 + 1) - n) % n
    for _b in range(n_boot):
        if len(w) - j < 2 * n + 2:  # a resample takes at most 2n words, short of rejections
            w, isnew = fetch(w, isnew, j)
            j = 0
        row = [0] * n
        for t in range(n):
            if t:
                new = isnew[j]
                j += 1
                if not new:
                    i += 1
                    if i == n:
                        i = 0
                    row[t] = i
                    continue
            if has:
                x, has = half, False
            else:
                x = w[j]
                j += 1
                half, x, has = x >> 32, x & _M32, True
            m = x * n
            if (m & _M32) < thr:  # Lemire rejection: ~n / 2**32 of draws
                while (m & _M32) < thr:
                    if has:
                        x, has = half, False
                    else:
                        if j >= len(w):
                            w, isnew = fetch(w, isnew, j)
                            j = 0
                        x = w[j]
                        j += 1
                        half, x, has = x >> 32, x & _M32, True
                    m = x * n
                if len(w) - j < 2 * n + 2:
                    w, isnew = fetch(w, isnew, j)
                    j = 0
            i = m >> 32
            row[t] = i
        yield row


def block_bootstrap_ci(x: list[float], stat: str = "mean", n_boot: int = 2000, block: int = 0,
                       alpha: float = 0.10, seed: int = 0) -> dict:
    """Fixed-length moving-block bootstrap, same return shape as `stationary_bootstrap_ci`.
    `block`<=0 selects the Politis-White rule rounded to an integer (floored at 2). Natural
    when a fixed block (e.g. one trading day) is preferred over a geometric one."""
    arr = np.asarray(x, dtype=float)
    n = len(arr)
    L = int(block) if block and block >= 1 else max(2, int(round(_politis_white_avg_block(arr)))) if n >= 2 else 2
    L = min(L, max(n, 1))
    degenerate = _degenerate_result(arr, stat, n_boot, L)
    if degenerate is not None:
        return degenerate
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / L)
    starts_max = n - L + 1  # moving-block start positions 0..n-L (no wrap)
    offsets = np.arange(L)
    boot = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        starts = rng.integers(0, starts_max, size=n_blocks)
        idx = (starts[:, None] + offsets[None, :]).ravel()[:n]
        boot[b] = _stat_value(arr[idx], stat)
    return _ci_result(boot, _stat_value(arr, stat), alpha, n_boot, float(L))


# ---- 5. Purged walk-forward + embargo splitter (Lopez de Prado) ----------------------

def purged_walkforward_splits(entry_ts: list[int], settle_ts: list[int], n_splits: int,
                              embargo_seconds: int) -> list[dict]:
    """Chronological EXPANDING walk-forward over samples whose entry/settlement times are
    entry_ts[i]/settle_ts[i] (unix seconds, ascending by entry_ts).

    For each of n_splits contiguous test blocks (built from n_splits+1 equal segments; the
    first segment is train-only):
      - test = the next contiguous block of samples,
      - train = all EARLIER samples, with PURGE (drop any train sample whose settle_ts falls
        ON/AFTER the test block's first entry_ts — this handles positions that settle up to
        24h past the boundary) and EMBARGO (drop train samples whose entry_ts is within
        embargo_seconds BEFORE the test block).

    Returns [{"train_idx":[...], "test_idx":[...], "test_from_ts":int, "test_to_ts":int}],
    where test_from_ts / test_to_ts are the entry_ts of the first / last test sample. Yields
    an empty list if there are too few samples for one test block.
    """
    n = len(entry_ts)
    if len(settle_ts) != n:
        raise ValueError("entry_ts and settle_ts must have equal length")
    if n <= 0 or n_splits < 1:
        return []
    test_size = n // (n_splits + 1)
    if test_size == 0:
        return []
    splits: list[dict] = []
    for i in range(1, n_splits + 1):
        test_start = i * test_size
        test_end = n if i == n_splits else (i + 1) * test_size
        test_first_entry = entry_ts[test_start]
        embargo_cutoff = test_first_entry - embargo_seconds
        train_idx = [
            j for j in range(test_start)
            if settle_ts[j] < test_first_entry        # purge: no settlement into the test block
            and entry_ts[j] < embargo_cutoff          # embargo: no run-up adjacent to the block
        ]
        splits.append({
            "train_idx": train_idx,
            "test_idx": list(range(test_start, test_end)),
            "test_from_ts": int(test_first_entry),
            "test_to_ts": int(entry_ts[test_end - 1]),
        })
    return splits


def demo() -> None:
    """Runnable self-check: assert the core relationships hold."""
    # BH: known vector; at alpha=0.05 the step-up line passes only through rank 2.
    bh = benjamini_hochberg([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205], 0.05)
    assert bh["k"] == 2 and bh["reject"][:2] == [True, True] and abs(bh["threshold"] - 0.008) < 1e-12
    assert benjamini_yekutieli([0.001, 0.008, 0.039], 0.05)["k"] <= benjamini_hochberg([0.001, 0.008, 0.039], 0.05)["k"]
    # LORD++: tiny p rejects test 1; alpha_i never exceeds available wealth; plain-dict state.
    st = lord_init(alpha=0.10)
    r = lord_record(st, 1e-12)
    assert r["reject"] and r["alpha_i"] <= st["wealth"] + 1e-12 and r["t"] == 1
    assert r["state"]["rejections"] == [1]
    # PSR / DSR.
    assert abs(probabilistic_sharpe_ratio(0.0, 100, 0.0, 3.0) - 0.5) < 1e-12
    psr = probabilistic_sharpe_ratio(0.1, 250, 0.0, 3.0)
    dsr = deflated_sharpe_ratio(0.1, 250, 0.0, 3.0, n_trials=100, var_trials=0.04)
    assert dsr < psr
    assert abs(norm_ppf(0.975) - 1.959963985) < 1e-6
    # Bootstrap: injected edge -> p_value ~ 0; null -> p_value not significant.
    rng = np.random.default_rng(0)
    edge = list(rng.normal(0.05, 0.1, 300))
    null = list(rng.normal(0.0, 0.1, 300))
    assert stationary_bootstrap_ci(edge, "mean", n_boot=1000, seed=1)["p_value"] < 0.05
    assert stationary_bootstrap_ci(null, "mean", n_boot=1000, seed=1)["p_value"] > 0.1
    assert stationary_bootstrap_ci([3.0, 3.0, 3.0], "mean")["lo"] == 3.0
    # Purged splitter: zero settlement overlap (24h settle vs hourly entries).
    entry = [i * 3600 for i in range(60)]
    settle = [e + 86400 for e in entry]
    splits = purged_walkforward_splits(entry, settle, n_splits=4, embargo_seconds=7200)
    assert splits and any(s["train_idx"] for s in splits)
    for s in splits:
        for j in s["train_idx"]:
            assert settle[j] < s["test_from_ts"] and entry[j] < s["test_from_ts"] - 7200
    # Logistic: a feature that perfectly separates the label gets a positive coefficient, and the
    # fitted model predicts the right side; a pure-noise constant column stays near zero.
    Xf = [[x, 1.0] for x in (-3.0, -2.0, -1.0, 1.0, 2.0, 3.0)]
    yf = [0, 0, 0, 1, 1, 1]
    coef, intercept = fit_logistic(Xf, yf, l2=0.01)
    assert coef[0] > 0 and abs(coef[1]) < coef[0]
    p_hi = 1.0 / (1.0 + math.exp(-(intercept + coef[0] * 3.0 + coef[1])))
    p_lo = 1.0 / (1.0 + math.exp(-(intercept + coef[0] * -3.0 + coef[1])))
    assert p_hi > 0.5 > p_lo
    print("stats demo OK")


if __name__ == "__main__":
    demo()
