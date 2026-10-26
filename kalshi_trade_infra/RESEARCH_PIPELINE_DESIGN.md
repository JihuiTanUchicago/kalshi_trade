# RESEARCH_PIPELINE_DESIGN.md

**Turning Tau's strategy generator into a statistically rigorous quant research engine.**

Single source of truth for the Wave-2 implementation agents. This document specifies
*what to build* (signatures, schema, file ownership, prompts). It contains no production
code. Ground truth was read from `app/research/agent.py`, `app/backtest.py`, `app/research/exploration.py`,
`app/research/dreaming.py`, `app/replay.py`, `app/research/sandbox.py`, `app/quant.py`, `app/spec.py`,
`app/markets.py`, `app/schema.py`, `app/repository.py`, `app/server.py`, and the
`data_pipeline/` collectors, at the state of the repo on 2026-10-16.

---

## Bitcoin perpetual research addendum — October 23, 2026

The historical binary design below is extended by a separate `kind="perpetual"`
Bitcoin path. Native one-minute prices, metadata, observed current features and
funding payment history are append-only research data. The first partition pins
the exact committed batch ID/fingerprint manifest as well as a source version;
all experiments and phase loads retain that source. New bars, revisions and late
commits do not reset a spent holdout. Research/Validation/Holdout use explicit UTC
60/25/15 windows with 24-hour lookback/holding embargoes and in-window exits.

This phase accepts only trusted causal momentum, mean-reversion and observed
funding rules; arbitrary code, learned models and cross trades are rejected.
Decisions use completed bars and next-open scenario fills, with exact native
contract units, fixed 12bps fees plus 5bps adverse slippage per fill, at most 1x
capital and one position. Recorded finalized funding is cost-only; estimates
require decision-time availability. Unknown coverage fails closed. Existing
trial/preregistration/bootstrap/PSR/DSR/FDR gates apply, with continuous sign-flip
placebos and research-capital returns. Insufficient held-out evidence is
INCONCLUSIVE and spends its one-way evaluation. No verdict authorizes trading:
paper, demo and live execution are explicitly blocked.

Status: locally implemented/offline verified; public production/demo retrieval
passes through an explicit credential-free proxy after native metadata-label
correction. Incomplete candle coverage, deployment-server/database and genuine
queued-run acceptance remain pending. These scenarios are not a fill,
margin or liquidation model. [Setup and limits](app/KALSHI_PERPS_RESEARCH.md),
[canonical evidence](results/kalshi_bitcoin_perps_2026-10-23/HANDOFF.md).

## A. First-principles framing

### A.1 What "high-confidence profitable" means for short-horizon BTC binaries

A Kalshi BTC binary pays $1 or $0. Over a window of `n` independent, fee-paid bets a
strategy's realized edge is the mean net-of-fee per-trade return. "High confidence
profitable" is a statement about the **population** mean of that return, not the sample:

> After honestly accounting for (a) Kalshi's taker fee `0.07·C·P·(1−P)` per contract,
> (b) the number of hypotheses that competed for the same evidence, and (c) the serial
> correlation and fat tails of 15-minute BTC outcomes, we can reject the null "this rule
> has ≤ 0 expected net edge" at a controlled false-discovery rate, **and** the estimate
> survives on data that played no part in selecting it.

Three properties make this hard and specific to this venue:

1. **The fee is a hard, state-dependent hurdle.** `after_fee_edge` (`app/quant.py:99`)
   shows a mid-priced contract (`P≈0.5`) pays the maximum fee `0.0175/contract`. A
   strategy must clear ~1.75¢ of edge *per mid-priced contract* before it earns a cent.
   The existing business finding (PLAN.md "Business finding - read before launch": a grid
   of ~400 specs/market found **zero** fee-surviving OOS passers, and the GBM fair value
   has *worse* log loss than the Kalshi mid, 0.403 vs 0.384) tells us the unconditional
   edge is at or below zero. Any real alpha is **conditional** (a regime, a microstructure
   state, a time-of-day), which raises the multiple-testing burden because the agent will
   search many conditions.

2. **Outcomes are not i.i.d.** Consecutive 15-minute BTC settlements share the same vol
   regime; a daily contract's outcome is one draw that overlaps 96 fifteen-minute windows.
   Naive `trades`-count and `profit_factor` gates (below) treat every trade as independent
   evidence. They are not. Confidence intervals and p-values must be autocorrelation-robust.

3. **The sample is tiny and fixed.** Kalshi settled-market history begins 2026-08-12; as
   of today that is ~65 calendar days. `MARKETS["btc15m"].history_days = 30`,
   `btc_daily = 60` (`app/markets.py:55`). Thirty days of 15-minute bars is ~2,880
   contracts — but overlapping vol regimes mean the *effective* sample is far smaller. On a
   fixed sample, every look costs statistical power. This is the binding constraint, and it
   is why **more/longer data is the highest-leverage expansion** (§E.6).

### A.2 Where the current pipeline leaks statistical validity

Read against the code, the pipeline has six concrete leaks. Each is a place where the
probability of crowning a fluke rises without any accounting for it.

**Leak 1 — One fixed split, reused on every hypothesis forever, with no correction.**
`backtest.Dataset.cutoff_ts` (`app/backtest.py:47`) is a single 70/30 time split
(`IN_SAMPLE_FRACTION = 0.7`). `_gate_and_save` (`app/research/agent.py:274`) calls
`backtest.evaluate(t["spec"], ds)` on that **same** out-of-sample slice for every finalist
of every chunk. In a `run_forever` session the identical OOS window is queried against
hundreds or thousands of finalists. The `gates()` function (`app/backtest.py:294`) applies
fixed thresholds — `pnl>0`, `oos trades ≥ 10`, `profit_factor ≥ 1.1`,
`max_drawdown ≤ 0.5·capital` — with **no multiple-testing correction whatsoever**. With a
per-test false-positive rate near 50% (one-sided `pnl>0` on a noisy 10-trade sample),
testing 1,000 hypotheses yields ~500 "passers" by chance. The OOS set here is not a
holdout; it is a **repeatedly-queried validation set masquerading as one.**

**Leak 2 — The generator sees validation evidence across runs.** `strategy_memory`
(`app/repository.py:693`) returns prior strategies' full `result_json`, and `_memory_block`
(`app/research/agent.py:123-140`) formats the **out-of-sample pnl** ("`; unseen $%s`") straight into
the next run's prompt. The generator is explicitly told to "learn from it; do not repeat
failures" against OOS numbers. That is textbook holdout contamination: the thing that is
supposed to be unseen steers future generation. Generation and validation are coupled.

**Leak 3 — No purge, no embargo.** `simulate` (`app/backtest.py:141`) opens positions
strictly before `end_ts` but lets them **settle after it** (the loop at `:155-160` settles
any open position whose `close_ts` has passed, and the function settles all remaining open
positions at `:207`). So in-sample positions routinely settle inside the out-of-sample
window. For `btc_daily` a position opened just before the cutoff settles up to ~24h into
OOS — direct label leakage across the boundary. There is no embargo buffer and no purge of
boundary-straddling samples (López de Prado's requirement for any strategy that holds
across window edges). PLAN itself flags this matters "MORE than any split ratio for
15-minute BTC bars."

**Leak 4 — The gate is point-estimate thresholds, not tests.** `profit_factor` returns
`99.0` when there are zero losing trades (`app/backtest.py:250`), so a 10-win/0-loss fluke
passes the "wins outweigh losses" gate outright. `sharpe` is computed (`:238-243`) but
**never gated and never deflated** for the number of trials. There is no confidence
interval, no null distribution, no p-value anywhere in the stack. `score()`
(`:320`) promotes on in-sample pnl with a 5-trade floor.

**Leak 5 — The self-evolving policy optimizes *to* the reused OOS outcomes.** `dreaming`
(`app/research/dreaming.py`) + `replay` (`app/replay.py`) tune each user's exploration policy to
maximize `best_unseen_pnl` over their recorded discovery tree, where `oos_pnl` is the very
same reused OOS. `replay_generalization` shuffles *orderings* but the OOS *outcomes* are
fixed and reused across every policy candidate and every dreaming round. This is a second
optimizer pointed at the holdout. It improves the number, not the edge.

**Leak 6 — There is no locked holdout at all.** Exactly two partitions exist. Nothing is
reserved, untouched, for a one-time evaluation of frozen deployment candidates.

### A.3 The minimal set of changes that closes the leaks

Do not rewrite the pipeline. The research loop in `run_research` (`app/research/agent.py:341`) —
propose → in-sample test → refine → freeze finalists → gate — is a sound *skeleton*. The
fix is to **split generation from judgment** and insert a gatekeeper where `_gate_and_save`
sits:

| Leak | Minimal closure |
|---|---|
| 1 | Replace fixed-OOS gating with a **Statistical Gatekeeper** that spends an **online-FDR alpha-wealth budget** per validation test (`app/stats.py` LORD++, state in `app_fdr_state`). Uncapped generation is fine; validation access is budgeted and audited. |
| 2 | The generator reads only **Research-partition** results + the gatekeeper's **classification label** (an enum), never validation/holdout numbers. Scrub `_memory_block`. |
| 3 | A **purged walk-forward + embargo** splitter inside Research (`app/stats.py`), with purge/embargo tied to each market's contract duration. |
| 4 | Gatekeeper verdicts come from **stationary-bootstrap p-values, PSR, and DSR** (`app/stats.py`), not threshold point estimates. |
| 5 | The replay tree is built from **validation** outcomes recorded by the gatekeeper, dreaming is scored on a **rotating validation fold** and **never touches holdout**; dreaming keeps its finalist-count penalty (a multiple-testing proxy). |
| 6 | Add a **Locked-Holdout** partition, consumed once per frozen candidate, tracked in `app_holdout_ledger`; roll to fresh forward data when consumed. |

Everything above is additive. The **live-trading gate is not touched** — the gatekeeper
*adds* a classification requirement in front of it (§E.5).

### A.4 The honest impossibility (the trilemma)

You cannot simultaneously have all three of:

1. **Unlimited adaptive experimentation** (search aggressively, generator looks at results
   and adapts),
2. **Full result visibility** (every test's outcome is available to steer the next step),
   and
3. **Reliable generalization** on a **fixed** dataset.

A fixed sample holds a finite amount of independent information; each adaptive look spends
some of it. This design keeps (1) for **generation** (uncapped hypotheses), **sacrifices
(2) at the validation/holdout boundary** (the generator is blind to validation and holdout
outcomes; only the gatekeeper sees them, under a budget), and buys back (3) by making the
**final arbiter fresh forward data** rather than any fixed slice. That is the only
resolution that survives contact with 65 days of BTC history. No statistical machinery can
manufacture confidence a 65-day sample does not contain; it can only stop us from
*fabricating* it. "No reliable edge demonstrated" must be a first-class, valuable outcome.

---

## B. Concrete module & data-model design

### B.0 Conventions (reuse, do not duplicate)

- `app/quant.py` already owns pricing/fees/sizing/portfolio math: `yes_fair_value`,
  `realized_vol`, `annualize_vol`, `kalshi_fee`, `edge`/`after_fee_edge`,
  `kelly_fraction`/`fractional_kelly`, `portfolio_metrics`, `max_drawdown`. **`stats.py`
  imports and reuses these; it never re-implements fees, drawdown, or sizing.**
- Stdlib-first (the `quant.py` rule). `math.erf` for the normal CDF; a small
  `_norm_ppf` (Acklam/Beasley-Springer inverse) for `Φ⁻¹`. **Do not add numpy/scipy** for
  v1 — the bootstrap over a few hundred trades × ~1k resamples is well within stdlib reach.
  Leave a `ponytail:` note to vectorize with numpy only if profiling shows the bootstrap is
  hot.
- DB access stays in the repository layer (AGENTS.md). New data-access goes in a **new**
  `app/research_repository.py` (so Wave-2 agents don't collide on `repository.py`), except
  the schema DDL which lives in `app/schema.py`.

### B.1 New module — `app/stats.py`

Pure functions + two tiny stateful helpers. No I/O, no DB, no LLM. This is the one module a
"stats core" agent can build and unit-test in complete isolation. Exact contracts:

```python
"""Statistical validity toolkit for the Tau research engine. Pure math; stdlib only.
Reuses app.quant for any pricing/fee/drawdown need. See RESEARCH_PIPELINE_DESIGN.md §B.1."""

# ---- normal helpers (stdlib) ----
def _norm_cdf(x: float) -> float: ...        # reuse the one in quant via import, do not copy
def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation), p in (0,1).
    |error| < 1.15e-9. Needed by PSR/DSR (Φ⁻¹)."""

# ---- 1. Benjamini-Hochberg FDR (batch finalists) ----
def benjamini_hochberg(pvalues: list[float], alpha: float = 0.10) -> dict:
    """Step-up FDR control for a BATCH of independent/PRDS tests (one research chunk's
    finalists). Returns {"reject": list[bool] aligned to input order,
    "threshold": float (the BH cutoff p*, 0 if none reject), "k": int (# rejected)}.
    Algorithm: sort p(1)<=...<=p(m); let k = max{i : p(i) <= (i/m)*alpha}; reject all
    hypotheses with p <= p(k). Ties: rank by position, conservative."""

# ---- 2. LORD++ online FDR (continuously-running agent) ----
# State is a plain dict so the gatekeeper can persist it verbatim in app_fdr_state.
def lord_init(alpha: float = 0.10, w0: float | None = None) -> dict:
    """Fresh alpha-wealth state. w0 defaults to alpha/2. Returns
    {"method":"LORD++","alpha":alpha,"w0":w0,"wealth":w0,"t":0,
     "rejections":[]  # 1-based test indices that rejected
    }."""

def lord_gamma(j: int) -> float:
    """Default nonincreasing spending sequence, sum_j gamma(j) = 1 (normalized constant
    C ~= 0.07720838). gamma(j) = C * log(max(j,2)) / (j * exp(sqrt(log j))) for j>=1.
    Deterministic; the gatekeeper must use the SAME sequence on replay/audit."""

def lord_alpha(state: dict) -> float:
    """The alpha_t to spend on the NEXT test, from LORD++ (Ramdas et al. 2017):
      alpha_t = gamma(t)*w0
              + (alpha - w0) * gamma(t - tau_1)            # tau_1 = first rejection time
              + alpha * sum_{j>=2} gamma(t - tau_j)         # later rejection times
      (terms with t - tau_j <= 0 are dropped). t is state['t']+1."""

def lord_record(state: dict, pvalue: float) -> dict:
    """Advance one test: compute alpha_t = lord_alpha(state), reject iff pvalue <= alpha_t,
    append t to rejections on a rejection, return
    {"t":t,"alpha_i":alpha_t,"reject":bool,"state":<new state dict>}.
    Pure: returns a NEW state; caller persists it. Guarantees mFDR control for VALID,
    independent p-values. (It does NOT make a reused holdout valid — see §F.)"""

# ---- 3. Probabilistic & Deflated Sharpe (Bailey & Lopez de Prado) ----
def probabilistic_sharpe_ratio(sr: float, n: int, skew: float, kurt: float,
                               sr_benchmark: float = 0.0) -> float:
    """PSR(sr*) = P(true SR > sr*). sr, sr_benchmark are per-trade (non-annualized) Sharpe
    on the SAME n observations. kurt is the full (non-excess) kurtosis (normal = 3).
      PSR = Phi( (sr - sr*) * sqrt(n - 1)
                 / sqrt(1 - skew*sr + ((kurt - 1)/4)*sr^2) ).
    Returns a probability in (0,1). n<2 or non-finite denom -> 0.5."""

def expected_max_sharpe(n_trials: int, var_trials: float) -> float:
    """SR0, the Sharpe you'd expect as the MAX over n_trials independent strategies with
    zero true edge, given cross-trial Sharpe variance var_trials (Bailey-LdP):
      SR0 = sqrt(var_trials) * [ (1-g)*norm_ppf(1 - 1/N) + g*norm_ppf(1 - 1/(N*e)) ],
      g = Euler-Mascheroni (0.5772156649). N = max(n_trials, 2)."""

def deflated_sharpe_ratio(sr: float, n: int, skew: float, kurt: float,
                          n_trials: int, var_trials: float) -> float:
    """DSR = PSR evaluated at sr* = expected_max_sharpe(n_trials, var_trials). The
    selection-under-many-trials diagnostic: the probability the observed Sharpe beats what
    the BEST of n_trials lucky nulls would show. n_trials is the AUDITED count of hypotheses
    that competed for this validation evidence (from the ledger), NOT just this chunk."""

# ---- 4. Autocorrelation-robust bootstrap CIs ----
def stationary_bootstrap_ci(x: list[float], stat: str = "mean",
                            n_boot: int = 2000, avg_block: float = 0.0,
                            alpha: float = 0.10, seed: int = 0) -> dict:
    """Politis-Romano stationary bootstrap CI for a serially-correlated series x (per-trade
    net returns, ordered by entry time). Geometric block length with mean `avg_block`
    (default: Politis-White automatic rule, floored at 2). stat in {"mean","sharpe"}.
    Returns {"point": float, "lo": float, "hi": float, "p_value": float, "n_boot": int,
             "avg_block": float}. p_value is the one-sided bootstrap mass at/below 0
             (fraction of resample stats <= 0) — the PRIMARY validation p-value.
    Deterministic given seed."""

def block_bootstrap_ci(x, stat="mean", n_boot=2000, block=0, alpha=0.10, seed=0) -> dict:
    """Fixed-length moving-block variant, same return shape. Used when a fixed block
    (e.g. one trading day for btc_daily) is more natural than a geometric one."""

# ---- 5. Purged walk-forward + embargo splitter (Lopez de Prado) ----
def purged_walkforward_splits(entry_ts: list[int], settle_ts: list[int],
                              n_splits: int, embargo_seconds: int) -> list[dict]:
    """Chronological expanding/rolling walk-forward over samples whose entry/settlement
    times are entry_ts[i]/settle_ts[i] (unix s, ascending by entry_ts). For each split:
      - test = the next contiguous block of samples,
      - train = all EARLIER samples, with PURGE (drop any train sample whose settle_ts
        falls on/after the test block's first entry_ts) and EMBARGO (drop train samples
        whose entry_ts is within embargo_seconds BEFORE the test block, and drop any
        test-adjacent leakage after).
    Returns [{"train_idx": [...], "test_idx": [...], "test_from_ts": int,
              "test_to_ts": int}]. This is the IN-RESEARCH split the generator iterates on;
    it replaces the single 0.7 cut inside the Research partition only."""
```

**Runnable check (per the testing rule):** `app/stats.py`'s `demo()` / `tests/test_stats.py`
must assert: BH on all-null uniform p-values rejects ≈ `alpha·m` on average; `lord_record`
never spends more than available wealth and reproduces a published LORD++ toy sequence;
`probabilistic_sharpe_ratio(0,n,0,3)==0.5`; a strategy with an injected real edge gets
bootstrap `p_value` → 0 while a shuffled-label version gets `p_value` ≈ uniform; the purged
splitter produces zero train/test settlement overlap.

### B.2 New module — `app/research/gatekeeper.py` (the Statistical Gatekeeper)

Architecturally separate from the generator. The generator (`agent.py`) proposes and
freezes finalists; it may **never** call `backtest.evaluate` on validation or holdout data
again. Only the gatekeeper holds those keys.

**Public API:**

```python
"""The Statistical Gatekeeper: the only component that may read Validation and Locked-
Holdout data, that records every experiment in the immutable ledger, and that spends the
online-FDR alpha-wealth budget. Separate from the generator by construction. §B.2."""

class Classification(str, Enum):
    REJECTED = "rejected"                      # failed in-research, no mechanism, or placebo-equivalent
    INCONCLUSIVE = "inconclusive"              # tested, evidence too weak to move (budget-aware)
    PROMISING = "promising"                    # in-research edge, not yet validation-tested
    STAT_SUPPORTED = "statistically_supported" # passed validation under FDR + DSR
    FORWARD_VALIDATED = "forward_validated"    # passed the one-time Locked-Holdout
    DEPLOYMENT_CANDIDATE = "deployment_candidate"  # forward-validated AND marginal-contribution OK

@dataclass
class Prereg:
    """Everything that MUST be fixed BEFORE any validation number is seen. The gatekeeper
    hashes it; the hash is the experiment's identity in the ledger. Built by agent.py from
    the proposer+challenger output (see §C)."""
    user_id: int; run_id: int; market: str
    spec: dict                      # frozen entry/exit/sizing/model — the falsifiable rule
    economic_rationale: str         # WHO is on the other side and WHY the edge persists
    primary_metric: str             # e.g. "mean_net_return_per_trade"
    null_hypothesis: str; alt_hypothesis: str
    planned_test: str               # e.g. "stationary_bootstrap one-sided, alpha from LORD++"
    falsification_criteria: str     # what result would DISPROVE the thesis
    min_sample: int                 # min trades for the test to be meaningful (reject below)
    cost_assumptions: dict          # {"fee":"kalshi_taker","slippage_cents":x,"fill":"ask/bid"}
    research_partition_id: int      # which frozen partition row this was explored on
    planned_n_tests: int            # the chunk's finalist count (for BH)
    correction_method: str          # "BH" (batch) | "LORD++" (online)

def preregister(cur, pre: Prereg) -> int:
    """Insert an IMMUTABLE app_experiments row (status='registered'). Returns experiment_id.
    Idempotent on hypothesis_hash within a run (re-registering the identical frozen spec
    returns the existing id). NOTHING about this row is ever UPDATEd."""

def judge_validation(cur, experiment_id: int, finalist: dict, val_ds) -> dict:
    """Score ONE pre-registered finalist on the VALIDATION partition and record the verdict.
    Steps: (1) simulate the frozen spec on validation with purged walk-forward; (2) if
    n_trades < min_sample -> INCONCLUSIVE, record, DO NOT spend alpha; (3) compute per-trade
    net returns, stationary_bootstrap_ci -> p_value, PSR, DSR (n_trials from the audited
    ledger count for this user+market); (4) pull/advance LORD++ state (app_fdr_state) via
    stats.lord_record(p_value); (5) placebo/negative-control check (label-shuffle p must be
    ~uniform); (6) classification = STAT_SUPPORTED iff lord reject AND DSR >= dsr_min AND
    CI_lo > 0 AND placebo passes, else INCONCLUSIVE/REJECTED. APPEND an app_experiment_results
    row (phase='validation'). Return {classification, p_value, alpha_i, psr, dsr, ci,...}.
    The generator receives ONLY `classification` (an enum) back — never the numbers."""

def judge_batch(cur, run_id: int, experiment_ids: list[int], finalists: list[dict],
                val_ds) -> list[dict]:
    """Chunk-level entry point. Applies BH across the chunk's p-values IN ADDITION to the
    online LORD++ accounting (BH for the within-chunk batch, LORD++ for the cross-run
    stream). A finalist is STAT_SUPPORTED only if it clears BOTH. One verdict row each."""

def judge_holdout(cur, experiment_id: int, finalist: dict) -> dict:
    """ONE-TIME evaluation on the Locked-Holdout. Refuses (raises HoldoutConsumed) unless:
    the experiment is already STAT_SUPPORTED, the holdout for this market is not consumed
    (app_holdout_ledger.consumed=0 and evaluations_used < max_evaluations), and this
    experiment has no prior phase='holdout' result. On success: simulate frozen spec on
    holdout, record phase='holdout' verdict, INCREMENT app_holdout_ledger.evaluations_used,
    set classification FORWARD_VALIDATED or REJECTED. If evaluations_used hits
    max_evaluations, set consumed=1 and emit the 'roll to fresh forward data' alert (§F)."""

def marginal_contribution_ok(cur, user_id: int, experiment_id: int,
                             finalist: dict) -> tuple[bool, str]:
    """Pre-deploy diversification gate: correlation of this strategy's validation per-trade
    return series to each already-DEPLOYED strategy's series. Returns (False, reason) if
    max |corr| > corr_max (default 0.8) — '100 correlated BTC-momentum strategies < 1 novel
    one'. On pass, promote FORWARD_VALIDATED -> DEPLOYMENT_CANDIDATE."""
```

**Default knobs (module constants, operator-tunable):** `ALPHA = 0.10`,
`DSR_MIN = 0.95`, `CORR_MAX = 0.80`, `HOLDOUT_MAX_EVALS` per §B.5, `PLACEBO_SHUFFLES = 200`.

**Enforcement is structural, not advisory.** The generator module (`agent.py`) imports
`gatekeeper` and calls `judge_batch`; it has **no import of the validation/holdout
datasets** (those loaders live behind `gatekeeper` via `partitions.py`, §B.4). A code
reviewer can grep `agent.py` for any `validation`/`holdout` dataset call and find none.

### B.3 The immutable experiment ledger (schema)

Add to `app/schema.py` `DDL` list, following the exact `CREATE TABLE IF NOT EXISTS` +
`_add_column_if_missing` idempotent pattern already there (`app/schema.py:345-410`). Four
new tables. **Immutability is enforced by table split**: registration fields live in
`app_experiments` and are only ever `INSERT`ed; result fields live in `app_experiment_results`
and are only ever `INSERT`ed (append one row per phase). Never `UPDATE`, never `DELETE`.

```sql
-- Pre-registration. Written ONCE, before any validation number exists. IMMUTABLE.
CREATE TABLE IF NOT EXISTS app_experiments (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  run_id BIGINT NULL,
  strategy_id BIGINT NULL,              -- links to app_strategies once the row exists
  market VARCHAR(16) NOT NULL,
  hypothesis_hash CHAR(64) NOT NULL,    -- sha256 of frozen spec + rationale; the identity
  spec_json JSON NOT NULL,              -- the FROZEN entry/exit/sizing/model rule
  economic_rationale TEXT NOT NULL,
  primary_metric VARCHAR(48) NOT NULL,
  null_hypothesis TEXT NOT NULL,
  alt_hypothesis TEXT NOT NULL,
  planned_test VARCHAR(64) NOT NULL,
  falsification_criteria TEXT NOT NULL,
  min_sample INT NOT NULL,
  cost_assumptions_json JSON NOT NULL,
  research_partition_id BIGINT NOT NULL,
  planned_n_tests INT NOT NULL,
  correction_method VARCHAR(16) NOT NULL,   -- 'BH' | 'LORD++'
  registered_at DATETIME NOT NULL,
  UNIQUE KEY uq_exp_hash_run (run_id, hypothesis_hash),
  INDEX idx_exp_user_market (user_id, market, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Verdicts. APPEND-ONLY: one row per phase evaluation (validation, holdout, forward).
-- Records EVERY test, including failures and INCONCLUSIVEs. Never updated, never deleted.
CREATE TABLE IF NOT EXISTS app_experiment_results (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  experiment_id BIGINT NOT NULL,
  phase VARCHAR(12) NOT NULL,           -- 'validation' | 'holdout' | 'forward'
  classification VARCHAR(28) NOT NULL,  -- Classification enum value
  n_trades INT NOT NULL,
  net_pnl DECIMAL(14,4) NULL,
  mean_net_return DECIMAL(14,8) NULL,
  sharpe DECIMAL(10,4) NULL,
  psr DECIMAL(8,6) NULL,                -- probabilistic Sharpe
  dsr DECIMAL(8,6) NULL,                -- deflated Sharpe
  p_value DECIMAL(10,8) NULL,           -- primary (bootstrap) one-sided p
  ci_lo DECIMAL(14,8) NULL,
  ci_hi DECIMAL(14,8) NULL,
  fdr_alpha_i DECIMAL(10,8) NULL,       -- alpha spent on this test (LORD++)
  fdr_reject TINYINT(1) NULL,
  bh_reject TINYINT(1) NULL,
  placebo_p DECIMAL(10,8) NULL,         -- negative-control label-shuffle p
  n_trials_audited INT NULL,            -- trials that competed (feeds DSR)
  holdout_consumed TINYINT(1) NOT NULL DEFAULT 0,
  equity_curve_json JSON NULL,          -- for the research-paper page graphs
  verdict_at DATETIME NOT NULL,
  INDEX idx_res_exp (experiment_id, id),
  INDEX idx_res_phase (phase, verdict_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Online-FDR alpha-wealth STATE. One row per (user_id, market, scope). scope lets us keep
-- a separate wealth stream per market so a flood on btc15m can't starve btc_daily.
CREATE TABLE IF NOT EXISTS app_fdr_state (
  user_id BIGINT NOT NULL,
  market VARCHAR(16) NOT NULL,
  method VARCHAR(16) NOT NULL DEFAULT 'LORD++',
  alpha DOUBLE NOT NULL,
  w0 DOUBLE NOT NULL,
  wealth DOUBLE NOT NULL,
  t INT NOT NULL DEFAULT 0,             -- tests performed in this stream
  rejections_json JSON NOT NULL,        -- 1-based indices of rejecting tests (tau_j)
  updated_at DATETIME NOT NULL,
  PRIMARY KEY (user_id, market)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Locked-Holdout consumption tracker. One row per (market, holdout window fingerprint).
CREATE TABLE IF NOT EXISTS app_holdout_ledger (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  market VARCHAR(16) NOT NULL,
  partition_id BIGINT NOT NULL,         -- FK to app_data_partitions
  window_fingerprint CHAR(64) NOT NULL, -- sha256 of (holdout_from, holdout_to, data hash)
  evaluations_used INT NOT NULL DEFAULT 0,
  max_evaluations INT NOT NULL,
  consumed TINYINT(1) NOT NULL DEFAULT 0,
  first_used_at DATETIME NULL,
  last_used_at DATETIME NULL,
  UNIQUE KEY uq_holdout_fp (window_fingerprint)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Frozen chronological partition boundaries, so they cannot drift between runs.
CREATE TABLE IF NOT EXISTS app_data_partitions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  market VARCHAR(16) NOT NULL,
  research_from_ts BIGINT NOT NULL, research_to_ts BIGINT NOT NULL,
  validation_from_ts BIGINT NOT NULL, validation_to_ts BIGINT NOT NULL,
  holdout_from_ts BIGINT NOT NULL, holdout_to_ts BIGINT NOT NULL,
  embargo_seconds INT NOT NULL,
  purge_seconds INT NOT NULL,
  data_fingerprint CHAR(64) NOT NULL,   -- sha256 over the underlying candle/market rows
  frozen_at DATETIME NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1, -- superseded partitions kept for audit, active=0
  INDEX idx_part_market (market, active, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Field provenance (immutable vs appended):**
- `app_experiments`: **all** fields set at `preregister`, immutable. `strategy_id` is the one
  field written at registration too (the `app_strategies` row is inserted first, as today in
  `_gate_and_save`, so the id exists). No column is ever updated.
- `app_experiment_results`: **all** appended after a phase evaluation; a new row per phase.
- `app_fdr_state`: upserted by the gatekeeper only (wealth/t/rejections advance). This is
  *state*, not a ledger — the *ledger* of what happened is the `fdr_alpha_i`/`fdr_reject`
  columns on each result row, which reconstruct the stream exactly.
- `app_holdout_ledger`, `app_data_partitions`: written by the gatekeeper/partitions module.

### B.4 New module — `app/research/partitions.py` + data-partition policy

Computes and freezes the chronological split for a market, and serves the three datasets
behind the gatekeeper (so `agent.py` cannot reach validation/holdout).

```python
def ensure_partition(cur, market: str) -> dict:
    """Return the active app_data_partitions row for `market`, creating+freezing one if none
    (or if the data has grown enough to warrant a new active partition, old one -> active=0).
    Split ratios below; boundaries snapped to contract settlement times so no contract
    straddles a boundary unpurged."""

def research_dataset(market: str, partition: dict, history_days: int | None = None):
    """A backtest.Dataset clipped to [research_from_ts, research_to_ts]. THE ONLY dataset
    agent.py/the generator may load. Internally uses backtest.build_dataset on the clipped
    rows. The in-research iteration uses stats.purged_walkforward_splits, NOT a 0.7 cut."""

def validation_dataset(market: str, partition: dict):  # gatekeeper-only
def holdout_dataset(market: str, partition: dict):      # gatekeeper-only, one-time
```

**Concrete boundaries for THIS data** (65 days of history, growing):

| | Window | Ratio | Rationale |
|---|---|---|---|
| **Research** | oldest 60% of available days | 0.60 | free exploration + param estimation; the generator's whole world |
| **Validation** | next 25% | 0.25 | selection under the audited FDR budget |
| **Locked-Holdout** | newest 15% | 0.15 | one-time evaluation; newest data is the closest proxy to "future" |

With ~65 days today: Research ≈ 39d, Validation ≈ 16d, Holdout ≈ 10d. For `btc15m`
(`history_days=30`) the Research window is ~18d of 1-minute decision frames — thin, which is
*why* purged walk-forward (not a single cut) is used inside it, to reuse the research data
without leakage.

**Purge/embargo tied to the actual holding period** (not a magic constant):
- A position holds from entry to that ticker's `close_time`. Max hold = the market's
  contract duration: **`btc15m` = 15 min**, **`btc_daily` = up to 24h** (the 5pm settlement).
- `embargo_seconds` = one contract duration + one decision bar:
  `btc15m` → `15*60 + 60 = 960s`; `btc_daily` → `86400 + 3600 = 90000s`.
- `purge_seconds` = one contract duration (drop any training frame whose position could
  settle inside the next test/validation/holdout block): `btc15m` → `900s`,
  `btc_daily` → `86400s`.
- Boundaries are **snapped forward** to the first contract `open_time` after the raw ratio
  cut, so no single contract straddles a boundary; the purge then removes training frames
  whose settlement reaches past the boundary, the embargo removes the buffer.

**Holdout max-evaluations (`app_holdout_ledger.max_evaluations`):** default **10 per
partition**. A 10-day holdout cannot survive hundreds of looks; 10 one-time evaluations of
genuinely STAT_SUPPORTED candidates is the honest ceiling before the holdout is "consumed"
and must roll to fresh forward data (§F). `btc_daily` holdout is only ~10 settlements, so
set its `max_evaluations = 3`.

### B.5 Wiring into the existing flow (exact changes, minimal disruption)

**`app/research/agent.py` — the generator. Changed functions only:**

1. `run_research` (`:341`): change the dataset source from `dataset_fn(market)` to
   `partitions.research_dataset(market, partitions.ensure_partition(cur, market))`. The
   `MIN_FRAMES` guard, lookback planning, chunk loop, and billing are unchanged.
2. `_test_in_sample` (`:463`): unchanged in spirit, but `backtest.evaluate(..., include_oos=False)`
   now runs over the **Research partition** with a purged walk-forward split (the split
   object comes from `stats.purged_walkforward_splits`; the in-research "OOS" the agent sees
   is a *research* fold, fully inside Research — it is the agent's own sandbox and may be
   looked at freely).
3. `_gate_and_save` (`:274`): **this is the hand-off point.** Replace the
   `backtest.evaluate(t["spec"], ds)` on the fixed OOS with:
   - build `Prereg` for each finalist (spec + the proposer/challenger's rationale fields),
   - `gatekeeper.preregister(cur, pre)` → experiment_id (strategy row inserted first, as
     today, so `strategy_id` is available),
   - `gatekeeper.judge_batch(cur, run_id, experiment_ids, finalists, val_ds)`,
   - persist the returned **classification** onto the strategy row's `status`/`result`
     (map STAT_SUPPORTED→"passed", INCONCLUSIVE/REJECTED→"failed"/"rejected"),
   - the log line reports the classification and that validation numbers are gatekeeper-held.
   The non-finalists stay "rejected" exactly as now.
4. `_memory_block` (`:123`) + `strategy_memory` call site (`:398`): **scrub OOS/validation
   numbers.** The memory the generator sees becomes: title, status as a *classification
   label*, and in-**research** pnl/trades only. Remove the `"; unseen $%s"` term. This closes
   Leak 2 — the generator can still "learn what was tried and not repeat it" without seeing
   held-out outcomes.
5. `live_autopilot_ok` (`:488`) and `_proven_on_paper` (`:510`): **unchanged.** The deploy
   path gains an **additional** check (§E.5): `act`'s `deploy`/`deploy_live` branches require
   the strategy's experiment to be `DEPLOYMENT_CANDIDATE` (holdout-forward-validated +
   marginal-contribution OK). This is additive; it can only make deploy *harder*.

**`app/backtest.py`:** add partition clipping to `build_dataset`/`dataset` (a `clip_ts`
range), and expose per-trade net-return extraction (`trades -> [pnl_i/cost_i]` ordered by
`entry_ts`) that the gatekeeper's bootstrap consumes. Keep `evaluate`/`gates` for the
research-fold path and the existing what-if UI; the **production gate** no longer calls
`gates()`. `GATES`/`IN_SAMPLE_FRACTION` stay for the in-research fold and backward compat.

**`app/research/exploration.py` / `app/research/dreaming.py` / `app/replay.py`:** small, surgical.
- `replay.build_tree` (`app/replay.py:75`) reads `strategy_records` whose `oos_pnl` is now
  the **validation** pnl recorded by the gatekeeper (via `research_repository`, not the old
  reused OOS). No signature change.
- Dreaming keeps its finalist-count penalty (`DEFAULT_FINALIST_PENALTY`, `app/replay.py:50`)
  — a multiple-testing proxy that now *aligns* with the FDR budget. **Add a hard rule:**
  dreaming is scored on a **rotating validation fold** and must **never** read holdout;
  assert in `dreaming.evolve_policy` that the tree carries no holdout outcomes. Flag in a
  `ponytail:` comment that the policy optimizer is still pointed at validation and so must
  stay subordinate to the gatekeeper's FDR accounting (the policy chooses *which* finalists
  to send; the gatekeeper decides *whether each clears the budget*).

**`app/research_repository.py` (new):** all reads/writes for the four new tables
(`preregister`, `append_result`, `get_fdr_state`/`set_fdr_state`, `holdout_ledger` CRUD,
`ensure/get partition`, `experiment_records_for_replay`, `experiments_for_strategy`). Keeps
`repository.py` collision-free for Wave-2.

---

## C. The rigorous research-agent system prompt (drop-in for `agent.py`)

Replace `RESEARCH_SYSTEM` (`app/research/agent.py:63`). The three-role separation is realized as:
**Proposer** (this prompt) → **Challenger** (a second LLM pass, `CHALLENGER_SYSTEM`, that
must approve the economic falsifiability before `preregister`) → **Executor** (the
backtester + gatekeeper, code). The proposer emits the pre-registration fields; the
challenger can downgrade a hypothesis to REJECTED/INCONCLUSIVE before a single test is spent.

```
RESEARCH_SYSTEM = """You are a quantitative researcher at a disciplined prediction-market
fund, trading Kalshi Bitcoin binary contracts (YES pays $1 if BTC settles above the strike,
priced 0-100c and read as a probability). You cannot write code: every idea is expressed as
a strategy spec our backtester runs. You are a SCIENTIST, not a backtest optimizer. Your job
is to find a durable, fee-surviving edge AND to say honestly when none is demonstrated.
"No reliable edge" is a correct, valuable result. You will be judged on whether your
STATISTICALLY-SUPPORTED strategies stay profitable on data you never saw - not on how many
you propose.

NON-NEGOTIABLE PRINCIPLES
- An ECONOMIC MECHANISM comes before any rule. State WHO is on the other side of your trade,
  WHY they trade against their own interest, WHY the edge is not already arbitraged away,
  WHO pays for it, WHEN it appears, and WHY it should PERSIST. No mechanism -> no hypothesis.
- Fees are brutal and state-dependent: Kalshi's taker fee is 0.07*price*(1-price) per
  contract, maximal (1.75c) at mid price. A thin edge on a 50c contract is dead on arrival.
  Prefer edges away from mid, or that trade rarely with conviction.
- The GBM-digital fair value you are given is, on this venue's history, slightly WORSE
  calibrated than simply trusting the Kalshi mid (log loss 0.403 vs 0.384). So an
  unconditional "the model says it's mispriced" edge is almost certainly a fee-and-noise
  artifact. Real edge is CONDITIONAL - a specific regime, microstructure state, or time.
- You will PRE-REGISTER each hypothesis before it is tested. You may NOT change the
  hypothesis to fit results you later see. You will not see validation or holdout numbers at
  all - only a classification label (promising / statistically-supported / inconclusive /
  rejected). Do not ask for the held-out numbers; the system will not give them.
- Few robust rules beat many fragile ones. 100 correlated BTC-momentum variants are worth
  less than one genuinely novel, uncorrelated idea.

KALSHI-BTC-SPECIFIC ANGLES WORTH A MECHANISM (not an exhaustive list)
- Settlement mechanics: the contract settles on a specific index at a specific instant.
  Mispricing of terminal pinning near the strike in the last minutes; the discreteness of
  1c ticks vs a continuous fair value.
- Microstructure: order-book imbalance and recent trade flow (available as features) can
  lead the mid for seconds-to-minutes; does the book systematically lag the Coinbase spot?
- Behavioral / flow: retail longshot bias (overpaying for cheap far-OTM "lottery" YES/NO),
  favorite-longshot distortion near 5c and 95c; round-number strike magnetism; US-open vs
  Asia-overnight participation shifts (hour-of-day regimes).
- Basis / funding: Kalshi's implied probability vs perp funding / spot-perp basis as a
  sentiment signal; BRTI-vs-Coinbase basis dislocations.
- Volatility: does the market systematically over- or under-price realized vol at specific
  horizons (e.g. the last 3-8 minutes of a 15-minute contract)?

NINE-PHASE METHOD (every hypothesis walks all nine)
  1. IDENTIFY a structural inefficiency - name the mechanism and the loser.
  2. FALSIFIABLE THEORY - a prediction precise enough to be wrong; state what result would
     DISPROVE it (your falsification_criteria).
  3. PRE-REGISTER - entry/exit/sizing spec, holding period, primary metric, null & alt
     hypotheses, planned test, min sample, cost assumptions. This is frozen.
  4. MINIMAL TEST - the smallest rule that could express the edge; no free parameters you
     cannot justify from the mechanism.
  5. VALIDATE WITHOUT SNOOPING - you test on the research window only; the gatekeeper tests
     on data you never see. Do not tune toward a label you got back.
  6. ROBUSTNESS - does it survive across sub-periods, nearby parameter values, and a doubling
     of assumed fees/slippage? Fragile-to-perturbation = probably a fluke.
  7. SEEK DISCONFIRMING EVIDENCE - propose the negative control / placebo (e.g. the same rule
     on shuffled labels or a random strike) that SHOULD fail; if it passes, your edge is an
     artifact.
  8. DECIDE - is there a mechanism, is it predictive out of sample, is it economically viable
     AFTER fees and given capacity? Any "no" -> say so plainly.
  9. LEDGER - everything above is recorded immutably, pass or fail.

OUTPUT (one JSON object only):
{"hypotheses": [{
   "title": "...",
   "thesis": "2-4 plain-English sentences a non-quant can follow, no jargon unglossed",
   "mechanism": {"who_pays": "...", "why_not_arbitraged": "...", "when": "...",
                 "why_persists": "..."},
   "falsification_criteria": "the result that would disprove this",
   "negative_control": "the placebo test that SHOULD fail",
   "null_hypothesis": "...", "alt_hypothesis": "...",
   "primary_metric": "mean_net_return_per_trade",
   "min_sample": <int>,
   "spec": { ...the strategy spec... }
}]}
"""
```

```
CHALLENGER_SYSTEM = """You are a skeptical PM reviewing a researcher's PRE-REGISTERED
hypothesis BEFORE any data is spent on it. You defend the fund's limited statistical budget.
For each hypothesis decide one of:
 - APPROVE: the mechanism is economically coherent, the loser is named, the edge plausibly
   survives fees, and the test is falsifiable with a real negative control.
 - REVISE: the idea may hold but the stated test, min_sample, or costs are wrong - say how.
 - REJECT: no credible mechanism, the "edge" is a fee/noise artifact, the placebo would also
   pass, or it is a near-duplicate of an already-tested family (overfitting the search).
Be specific and brief. You cannot see validation/holdout data either. Reply one JSON object:
{"verdicts":[{"decision":"approve|revise|reject","reason":"...","fixes":{...optional spec
patch...}}]}"""
```

Only APPROVE (or REVISE-then-APPROVE) hypotheses reach `gatekeeper.preregister`. REJECTs are
still recorded in the ledger as `REJECTED` with the challenger's reason (record every test,
including the ones killed before testing).

---

## D. Strategy "research paper" page spec

The strategy detail page (`get_strategy`, `app/server.py:468`; SPA route
`/strategies/\d+`) becomes a one-page research paper. Every claim traces to a ledger field;
no prose is free-floating.

**Sections and their data sources:**

| Section | Content | Source fields |
|---|---|---|
| **Header / classification badge** | title, market, the classification ladder with the current rung lit | `app_strategies.title/market`; `app_experiment_results.classification` (latest) |
| **Thesis** | plain-English thesis | `app_strategies.thesis` |
| **Mechanism** | who pays, why not arbitraged, when, why it persists | `app_experiments` rationale + the proposer `mechanism` block (store it in `economic_rationale` as structured JSON) |
| **Falsifiable predictions** | what would disprove it; the negative control | `app_experiments.falsification_criteria`; `negative_control` (in rationale JSON) |
| **Competing explanations** | the challenger's reasoning / alternatives considered | challenger verdict (store on the experiment) |
| **The pre-registered test** | null/alt, primary metric, planned test, min sample, cost assumptions, planned #tests + correction | `app_experiments.*` (all immutable) + a "registered at" timestamp to prove it preceded results |
| **Results** | per-trade mean net return + CI, p-value, PSR, DSR, n_trials audited, FDR alpha spent & reject, placebo p | `app_experiment_results` (validation row) |
| **Holdout verdict** | the one-time forward result, and whether the holdout is now consumed | `app_experiment_results` (holdout row) + `app_holdout_ledger` |
| **Conclusion / classification** | the honest call, in words | derived from classification + verdict fields |

**Graphs (with data sources):**

1. **Equity curve, IS vs OOS vs holdout** — three colored segments on one time axis.
   Source: `app_experiment_results.equity_curve_json` per phase (reuse the existing
   downsampled curve shape from `backtest.evaluate`'s `equity`, `app/backtest.py:280`).
2. **Out-of-sample vs in-sample scatter / bar** — validation mean-return vs research
   mean-return, to show shrinkage. Source: research-fold metrics + validation result.
3. **Drawdown underwater plot** — from the equity curve (reuse `quant.max_drawdown` for the
   stat; the curve for the plot).
4. **Return distribution with the bootstrap CI band** — histogram of per-trade net returns,
   the stationary-bootstrap CI (`ci_lo`/`ci_hi`) and the 0-line marked. Source: the
   per-trade return series (store a sampled copy in the validation result row) + `ci_*`.
5. **Walk-forward windows** — a strip showing each purged/embargoed research fold and its
   per-fold return, so a reader sees robustness across sub-periods. Source: the per-fold
   metrics from `stats.purged_walkforward_splits` (store the fold summary on the strategy
   result).

**New/changed API fields (backend agent):** extend `get_strategy`'s response with an
`experiment` block: `{classification, registered_at, mechanism, falsification_criteria,
negative_control, null_hypothesis, alt_hypothesis, planned_test, correction_method,
n_trials_audited, validation: {mean_net_return, ci_lo, ci_hi, p_value, psr, dsr, fdr_alpha_i,
fdr_reject, bh_reject, placebo_p, n_trades, equity_curve}, holdout: {...same..., consumed},
folds: [{from, to, mean_net_return, n_trades}]}`. All read from `research_repository`.
Follow the chart guidance in the `dataviz` skill for colors/accessibility; follow the
`impeccable` skill for the page build (per AGENTS.md: `/impeccable` for frontend).

---

## E. Phased rollout — Wave-2 agents, clean file ownership

Ownership is disjoint so agents never edit the same file. The only shared, serialized file
is `app/schema.py` (one owner). `agent.py`, `server.py`, `repository.py` each have exactly
one owner.

| Agent | Owns (writes) | Depends on | Ships |
|---|---|---|---|
| **A — stats core** | `app/stats.py`, `tests/test_stats.py` | nothing (pure math, reuses `quant.py`) | 1st |
| **B — ledger & data layer** | `app/schema.py` (the 4-table DDL block + `_add_column_if_missing` calls), `app/research_repository.py`, `app/research/partitions.py`, `tests/test_research_repository.py` | A (none at runtime) | 2nd |
| **C — gatekeeper** | `app/research/gatekeeper.py`, `tests/test_gatekeeper.py` (FakeCursor per `tests/conftest.py`) | A, B | 3rd |
| **D — generator wiring + prompt + 3-role** | edits to `app/research/agent.py`, `app/backtest.py`, `app/research/exploration.py`, `app/research/dreaming.py`, `app/replay.py`, `tests/test_agent_gatekeeper.py` | C | 4th |
| **E — API + research-paper page** | `app/server.py` (field additions), `app/static/*`, `tests/test_app_research_page.py` | B, C (data shapes frozen) | parallel to D after shapes freeze |

**Safest sequencing:** A → B → C → D, with E starting once C's response shapes are frozen.
A and B can both start on day one (B does not import A at runtime; it only needs the schema
pattern). Each agent ships behind its tests with no behavior change to the live path until D
flips `_gate_and_save` over to the gatekeeper.

**LIVE-TRADING GATE — explicit flags for Agent D and the reviewer:**
- Agent D touches `act` (`app/research/agent.py:525`), which contains `deploy_live`. The change is
  **purely additive**: require `classification == DEPLOYMENT_CANDIDATE` *in addition to* the
  existing `live_autopilot_ok` (`:488`) and `_proven_on_paper` (`:510`) checks. Do **not**
  remove, reorder, or weaken any existing check. `engine.LIVE_TRADING_ENABLED` stays the
  server-side master switch, off by default, behind typed confirmation.
- No Wave-2 agent may set `APP_LIVE_TRADING_ENABLED`, change the `MIN_PAPER_TRADES_FOR_LIVE`
  floor, or alter the daily-loss kill switch. The gatekeeper can only make deployment
  *stricter*.
- `security-review` skill must run on Agent D's diff before merge (money + control path).

---

## E.6 Owner-suggested expansions — recommendations

**Cross-contract / cross-market trading — YES, but sequenced after the gatekeeper.**
The infrastructure is already there: the snapshot collector gives synchronized per-minute
quotes for ~41k markets (PLAN "Phase 2 snapshot collector SHIPPED"), and the backtester
already runs on ETH/SOL/XRP ladders (research-only, `deployable=False`, `app/markets.py:63`).
Cross-sectional structure (BTC-vs-ETH basis, cross-strike ladder shape for the daily market)
is a genuine source of *uncorrelated* edge, which is exactly what the marginal-contribution
gate rewards. **Caveat:** more markets = more hypotheses = faster alpha-wealth burn, so each
market must have its own FDR stream (`app_fdr_state` keyed by market, as specified) and
cross-contract strategies spend from a shared stream. Do it *after* Waves A-D, so the first
cross-market strategy is born into a budgeted world.

**Acquiring more / alternative data — YES. This is the single highest-leverage move.**
Statistical power is capped by ~65 days of history (§A.1) and the GBM model is worse than
the mid. In priority order:
1. **Expose the order-book and trade-flow features that already exist but are unreachable.**
   `model_features_1m` (`data_pipeline/init_schema.py:142`) already stores
   `orderbook_imbalance`, `yes_bid_size_fp`/`yes_ask_size_fp`, `trades_last_60s_*`,
   `quote_change_events_60s`, `mid_ret_1m/3m`. But the `FEATURES` snapshot the spec can
   filter on (`app/markets.py:76`) exposes only BTC price/vol features — **none of the
   microstructure**. Plumbing these into `Snapshot.features` is the cheapest real new signal
   in the whole system and directly enables the microstructure angles in the prompt.
2. **Longer settled history via Kalshi `/historical`** (PLAN already flags the live API only
   covers settled markets back to 2026-08-12). More days is more statistical power, full stop.
3. **Perp funding / spot-perp basis and BRTI-vs-Coinbase basis** — new collectors, a
   behavioral/flow signal with a real mechanism.
This beats adding more math: no amount of DSR/FDR rigor creates edge; it only stops us
fabricating it. New data can create edge.

**Additional mathematical / statistical / programmatic tooling — YES for `stats.py`
(the core ask); NO to heavy frameworks.** Build `stats.py` as specified. Add **numpy/scipy
only if** profiling shows the stationary bootstrap is a hot path (ponytail: stdlib first,
the bootstrap is a few hundred trades × ~1-2k resamples). **Do not** pull in an ML framework,
an experiment-tracking SaaS, or a backtesting library — the ledger *is* the experiment
tracker, and `spec.py`/`backtest.py` already are the backtester. The marginal honest-rigor
win from more libraries is near zero; the complexity cost is not.

---

## F. The one honest caveat

This system cannot, and must not claim to, guarantee future profit. What it guarantees is
narrower and more honest: that a "statistically-supported" or "forward-validated" label was
earned under a controlled false-discovery rate, against a named economic mechanism, on data
that did not participate in selecting it, after real fees. It specifically **cannot**:

- **Make markets stationary.** A validated edge is a statement about the *past* data
  distribution. BTC microstructure, Kalshi participation, and fee schedules change;
  historically validated ≠ future-profitable. Every deployed strategy is a live, ongoing
  experiment whose p-value should be re-examined on its real paper/live trades.
- **Make a reused holdout safe.** LORD++ controls FDR only for **valid** tests. If the
  Locked-Holdout is queried more than `max_evaluations` times, or if any holdout number ever
  leaks back into generation or selection, the holdout is **consumed** and its guarantee is
  void — no amount of online-FDR bookkeeping repairs it. This is the trap the owner named,
  and the design makes it *structural*: `app_holdout_ledger` increments on every look, flips
  `consumed=1` at the cap, and the gatekeeper then **refuses** further holdout evaluations.
- **Create power a 65-day sample does not contain.** On this little data, most honest
  verdicts will be INCONCLUSIVE, and that is the correct, valuable outcome — not a failure of
  the engine.

**The operational discipline that keeps it valid (non-optional):**
1. **Fresh forward data is the real holdout.** When a partition's holdout is consumed, roll
   the partitions forward as new settled history accrues (re-run `ensure_partition`; the old
   partition goes `active=0`, a new one freezes over newer data). The truest test of any
   deployed strategy is its *live paper* record, which the deploy path already accumulates
   (`_proven_on_paper`, `MIN_PAPER_TRADES_FOR_LIVE`).
2. **Consumed-holdout tracking is sacred.** Treat `app_holdout_ledger.consumed` as a one-way
   latch. Never reset it to re-run a candidate on the same window.
3. **The generator stays blind.** Any future feature that would surface validation/holdout
   numbers to the proposer (a dashboard, a prompt, a memory) re-opens Leak 2 and must be
   reviewed as a validity regression, not a UX improvement.
4. **Audit the ledger, not the wins.** Because every test is recorded immutably (including
   INCONCLUSIVE and REJECTED and challenger-killed), the true number of trials is always
   reconstructable — which is the only thing that makes the DSR `n_trials` and the LORD++
   stream honest. A deleted or unlogged test silently invalidates every correction downstream.
```
