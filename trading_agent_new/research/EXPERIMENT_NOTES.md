# Experiment amendment recorded before reading strategy performance

Recorded October 8, 2026. The economic hypothesis and acceptance thresholds in
`docs/RESEARCH_SPECIFICATION.md` remain frozen. `experiment_protocol.json` was
written and hashed before any candidate performance was calculated.

The user requested current history rather than the earlier 2006–2015 snapshot.
Accounts therefore begin with cash in January 2016 and continue through October
7, 2026; December 2014–December 2015 is unscored feature warmup. Both the
2016–2020 and 2021–current partitions have already undergone exploratory data
analysis. They are historical diagnostic panels, not untouched holdouts.

Thirty primary/control/sensitivity trials are enumerated in the protocol.
Two additional **declared attribution diagnostics**, `costfree_B0` and
`costfree_B2`, use identical assumptions with zero spread and no commission.
They are not candidates and cannot replace the primary two-point buffer.
All 32 definitions are saved to the trial register before the first performance
run. Bootstrap inference is reported for the full interval, 2016–2020 and
2021–current, using both declared block lengths. Calendar-year votes exclude
partial 2026. The original 2016–2020 three-of-five vote is retained, alongside
a strict majority vote across the ten completed 2016–2025 years.

The original regime cutoffs required 2008–2015 development observations. That
dataset is outside the user's revised scored scope. A separate descriptive
regime diagnostic freezes lagged SPY volatility quartiles using **2015 unscored
warmup** only; it does not feed back into trades or substitute for the original
regime rule. No lookback, buffer, cap or threshold is selected from performance.

The public chart snapshot is not qualified point-in-time execution data.
Dividends use source ex dates; payment is assumed 30 calendar days later, at
the next session, with zero- and 60-day sensitivities. Historical release
timestamps and revision vintages are unavailable. Feature availability is
assumed one minute after the recorded session close, including early closes.
FRED DFF is a current-vintage snapshot, lagged two exchange sessions. The
settled-cash trial uses the historical T+3/T+2/T+1 transitions and an approximate
calendar that intersects exchange sessions with federal business dates.

Forward total returns use `(close + dividend) * split / previous_close`, then
compound chronologically. Adjusted-close signals are compared as a diagnostic
only. Shares and receivables are separately accounted for. No split occurs in
the real snapshot; a synthetic split checks conservation of account value.

Orders are fixed using prior closes before today's corporate actions, interest,
payment releases and simulated open. Such cash releases can affect execution
affordability, but cannot change that day's signals or intended orders. Sells
precede buys. The primary permits sale-proceeds reuse; the sensitivity does not.
Monthly targets refresh after the final session of a month, with daily risk caps.
Equal weight uses the same caps; the SPY buy-and-hold descriptive control invests
95% initially and is exempt from diversified portfolio caps thereafter.

Simulator validity and formal source qualification are separate. Valid proxy
simulations can identify a failure of the declared practical thresholds under
these assumptions. They cannot establish a formally validated, deployable edge.

## Implementation repair log

- Before performance: factored chronological feature derivation into a shared
  pure function to permit future-price/event perturbation checks.
- Before performance: six accounting/timing tests cover charges, proportional
  cash reduction, dividend entitlement and payment, splits, settlement dates,
  and future-information invariance. All six passed.

Any later corrections must be recorded here. Failed runs and output attempts
remain in the run history. No parameter tuning is authorized in this experiment.

- After first results: restored explicit original historical-panel gate reporting
  for 2016–2020 and 2021–current, including the latter's 2021–2025 majority vote.
  The pooled ten-year vote is only an additional diagnostic. This reporting fix
  does not change orders, economic rules or thresholds. Both original panels
  fail the same two practical thresholds as the pooled panel.
- After first results: added per-order pre-fill NAV to support independent
  turnover attribution. Replaced three-day annualized statistics with simple
  current-week returns. These are evidence/reporting fixes; no trading changes.
  The exact pre-performance amendment is preserved as
  `EXPERIMENT_NOTES.preregistered.md` and matches the trial register's hash.
