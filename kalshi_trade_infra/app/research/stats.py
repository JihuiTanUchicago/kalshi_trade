"""Statistical validity toolkit for the Tau research engine. Pure math; no I/O, no DB,
no LLM. Reuses app.trading.quant for the normal CDF (and any pricing/fee/drawdown need); it never
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

Normal CDF (Φ) is reused from app.trading.quant (math.erf). Φ⁻¹ is `norm_ppf` (Acklam, no scipy).
numpy is used for the bootstrap resampling/percentiles (already a pinned dependency; invisible
to callers — the public contract is pure python types).
ponytail: the stationary bootstrap reads numpy's draws off raw PCG64 words in bulk and walks only its
new blocks in python, since profiling showed it hot (_pcg64_stationary_blocks: same draws, ~15x faster
than the per-point numpy loop).
"""
from __future__ import annotations

import math

import numpy as np

from app.trading.quant import _norm_cdf  # reuse: standard normal CDF (math.erf), no duplication

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
        b = 0
        for rows in _pcg64_stationary_blocks(rng.bit_generator, n, p, n_boot):
            for idx in rows:
                boot[b] = _stat_value(arr[idx], stat)
                b += 1
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
_BLOCK_POINTS = 1 << 16  # resampled points worked out at a time (bounds a block's arrays to ~11MB)
_CHAIN_SQUARINGS = 5  # the chain is the states F**32 reaches (see _pcg64_stationary_blocks)


class _ShortOfWords(Exception):
    """A block read past the raw words fetched for it; it is worked out again with more."""


def _pcg64_stationary_blocks(bg: "np.random.PCG64", n: int, p: float, n_boot: int):
    """The stationary bootstrap's index rows, exactly as the loop above draws them from Generator(bg)
    (`rng.integers(0, n)` to start a block, `rng.random() < p` to continue one), as int64 arrays of up
    to _BLOCK_POINTS // n rows each. bg must be fresh.

    numpy's draws, off bg's raw 64-bit words: random() = (next64 >> 11) * 2**-53; integers(0, n) =
    Lemire's bounded draw on next32, rejecting while the product's low word is under (2**32 - n) % n,
    where next32 hands out the low then the high half of one word (PCG64's has_uint32 buffer, which
    random() leaves alone). So each point after a row's first reads one word, its coin (a new block
    when under p), and a new block also draws a 32-bit value: a fresh word when the buffer is empty
    (keeping its high half), the buffered half otherwise.

    The loop walked that per point in Python (~0.5s for 730 points x 2,000 resamples, on the Deploy
    board's request path). Here Python walks only the new blocks, and mostly skips those too: the next
    new block from word j is the next word whose coin says new (a cumsum lookup). After a new block at
    word x drawn with the buffer empty, the next one is at the first new coin from x+2 (the draw read
    x+1) and draws from the buffer; drawn from the buffer, the next is at the first new coin from x+1
    and draws a fresh word. That successor map over (word, buffer) states is fixed by the words alone,
    and walks from different states merge within a few steps (mean 3, max ~50 at p=0.5), so the states
    32 steps reach form one long chain: it is laid out once per block of words with each new block's
    drawn index, and a row follows it a slice at a time (one search for where the row ends). The
    Python walk does each row's start, the steps until it joins the chain, every break in the chain
    and every Lemire rejection (which takes an extra draw, so it leaves the chain). Same draws, so the
    same rows bit for bit (tests/test_stats_bootstrap_exact.py holds it to the loop and to numpy's own
    draws): 0.44s -> 0.13s for 730 points x 2,000 resamples (measured 2026-10-26)."""
    thr = ((_M32 + 1) - n) % n
    per = max(1, _BLOCK_POINTS // n)
    buf = np.empty(0, dtype=np.uint64)
    base = 0  # buf[k] is raw word base + k
    state = (0, False, 0)  # (next raw word, a half is buffered, that half)
    done = 0
    while done < n_boot:
        rows = min(per, n_boot - done)
        need = rows * (n + n // 2 + 2) + 256  # a row reads at most ~1.5n words, rejections aside
        while True:
            buf, base = buf[state[0] - base:], state[0]
            if len(buf) < need:
                more = bg.random_raw(need - len(buf))
                if not len(more):
                    raise RuntimeError("the bit generator gave no words")
                buf = np.concatenate([buf, more])
            try:
                block, state = _stationary_block(buf, base, state, rows, n, p, thr)
                break
            except _ShortOfWords:
                need *= 2
        yield block
        done += rows


def _stationary_chain(buf: np.ndarray, n: int, p: float, thr: int) -> dict:
    """The block's words laid out for _stationary_block: `cs[j]` new coins before word j, `nxt[r]` the
    word of the r-th new coin (len(buf) past the last), and the chain: for each chain state (word, buffer
    empty or not) in word order, `tidx` (state id 2*r + buffered -> chain position, or -1), its word
    `tpos`, `tbuf`, `c` (words that are coins up to it: a row's points between two chain states), `ti`
    (the index its draw gives), and `stops`, the positions a walk along the chain may not step onto
    (the link from the state before is not the successor map, or its draw is rejected)."""
    N = len(buf)
    isnew = ((buf >> np.uint64(11)) * _INV53) < p
    cs = np.zeros(N + 3, dtype=np.int64)
    np.cumsum(isnew, out=cs[1:N + 1])
    cs[N + 1:] = cs[N]
    pos = np.flatnonzero(isnew)
    M = len(pos)
    nxt = np.append(pos, N)
    # The successor map over state ids 2*r + buffered (r: the new coin's rank); 2M, 2M+1: past the end.
    F = np.empty(2 * M + 2, dtype=np.int64)
    F[0:2 * M:2] = 2 * cs[pos + 2] + 1
    F[1:2 * M:2] = 2 * cs[pos + 1]
    F[2 * M:] = (2 * M, 2 * M + 1)
    G = F
    for _ in range(_CHAIN_SQUARINGS):
        G = G[G]
    reached = np.zeros(2 * M + 2, dtype=bool)
    reached[G] = True
    ids = np.flatnonzero(reached[:2 * M])
    tidx = np.full(2 * M + 2, -1, dtype=np.int64)
    T = len(ids)
    if T == 0:
        return {"cs": cs, "nxt": nxt, "tidx": tidx, "T": 0}
    tidx[ids] = np.arange(T)
    tpos = pos[ids >> 1]
    tbuf = ids & 1
    # Words that are coins up to each state: its word, less the draw words read before it.
    drawn = np.zeros(T, dtype=np.int64)
    np.cumsum(tbuf[:-1] == 0, out=drawn[1:])
    c = tpos - drawn
    # The 32-bit value each state draws: the low half of the word after its coin, or (buffered) the
    # high half of the word the state before it read.
    word = np.minimum(tpos + 1, N - 1)
    before = np.concatenate([np.zeros(1, dtype=np.uint64), buf[word[:-1]]])
    x = np.where(tbuf == 0, buf[word] & np.uint64(_M32), before >> np.uint64(32))
    m = x * np.uint64(n)
    stop = np.ones(T, dtype=bool)
    stop[1:] = (F[ids[:-1]] != ids[1:]) | ((m[1:] & np.uint64(_M32)) < np.uint64(thr)) | (tpos[1:] + 1 >= N)
    return {"cs": cs, "nxt": nxt, "tidx": tidx, "T": T, "tpos": tpos, "tbuf": tbuf, "c": c,
            "ti": (m >> np.uint64(32)).astype(np.int64), "stops": np.flatnonzero(stop).tolist()}


def _stationary_block(buf: np.ndarray, base: int, state: tuple, rows: int, n: int, p: float, thr: int):
    """`rows` index rows from raw words buf (word `base` onward), starting from `state`; returns them
    with the state after them. Raises _ShortOfWords if they read past buf."""
    import bisect

    ch = _stationary_chain(buf, n, p, thr)
    cs, nxt, tidx, T = ch["cs"], ch["nxt"], ch["tidx"], ch["T"]
    if T:
        tpos, tbuf, c, stops = ch["tpos"], ch["tbuf"], ch["c"], ch["stops"]
    N = len(buf)
    j, has, half = state
    ev_k: list = []  # (point, index) of each new block the walk drew
    ev_i: list = []
    seg_lo: list = []  # chain slices a row followed: positions [lo, hi), point of position q = base + c[q]
    seg_hi: list = []
    seg_base: list = []
    for r in range(rows):
        kb = r * n
        t, q = 0, -1
        while True:
            # Draw this point's index: integers(0, n), with Lemire's rejection.
            if has:
                x, has = half, False
            else:
                if j - base >= N:
                    raise _ShortOfWords
                w = int(buf[j - base])
                j += 1
                half, x, has = w >> 32, w & _M32, True
            m = x * n
            rejected = (m & _M32) < thr
            while (m & _M32) < thr:
                if has:
                    x, has = half, False
                else:
                    if j - base >= N:
                        raise _ShortOfWords
                    w = int(buf[j - base])
                    j += 1
                    half, x, has = w >> 32, w & _M32, True
                m = x * n
            ev_k.append(kb + t)
            ev_i.append(m >> 32)
            if q >= 0 and not rejected:
                # On the chain: follow it to the last new block this row holds, short of a stop.
                s = bisect.bisect_right(stops, q)
                hi = stops[s] if s < len(stops) else T
                cq = int(c[q])
                q2 = q - 1 + int(np.searchsorted(c[q:hi], cq + (n - 1 - t), side="right"))
                if q2 > q:
                    seg_lo.append(q + 1)
                    seg_hi.append(q2 + 1)
                    seg_base.append(kb + t - cq)
                    t += int(c[q2]) - cq
                    at = int(tpos[q2])
                    if tbuf[q2]:
                        j, has = base + at + 1, False
                    else:
                        j, has, half = base + at + 2, True, int(buf[at + 1]) >> 32
            t += 1
            if t >= n:
                break
            # The next new block in this row: the next new coin, unless the row ends first.
            rk = int(cs[j - base]) if j - base <= N else -1
            if rk < 0:
                raise _ShortOfWords
            e = int(nxt[rk]) + base
            if t + (e - j) >= n:
                j += n - t
                if j - base > N:
                    raise _ShortOfWords
                break
            if e - base >= N:
                raise _ShortOfWords
            t += e - j
            j = e + 1
            q = int(tidx[2 * rk + has]) if T else -1
    K = rows * n
    idx = np.zeros(K, dtype=np.int64)
    new = np.zeros(K, dtype=bool)
    k = np.asarray(ev_k, dtype=np.int64)
    idx[k] = ev_i
    new[k] = True
    if seg_lo:
        lo = np.asarray(seg_lo, dtype=np.int64)
        ln = np.asarray(seg_hi, dtype=np.int64) - lo
        qs = np.repeat(lo - (np.cumsum(ln) - ln), ln) + np.arange(int(ln.sum()))
        k = np.repeat(np.asarray(seg_base, dtype=np.int64), ln) + c[qs]
        idx[k] = ch["ti"][qs]
        new[k] = True
    # Every other point continues the block before it: the previous index + 1, wrapping at n.
    at = np.arange(K)
    last = np.maximum.accumulate(np.where(new, at, 0))
    idx = idx[last] + (at - last)
    idx[idx >= n] -= n
    return idx.reshape(rows, n), (j, has, half)


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
