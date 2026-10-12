# Daily ETF research

This module explores a free public snapshot and runs the fixed six-ETF research experiment. The EDA scripts compute individual-asset distributions, data quality, timing, corporate-action reconciliation and relationships. The separate simulator measures actual integer-share portfolios, costs, dividends and cash constraints.

## Latest result: controlled experiments

The fixed two-percentage-point buffer is **practically rejected under the declared public-proxy assumptions**. From January 4, 2016 through October 7, 2026, its excess Sharpe gain is 0.0802 (required 0.10), and two-sided traded-notional turnover falls 13.05% (required 25%). The one-sided bootstrap lower bound is positive, but that does not override the failed practical gates. Both original historical panels fail the same thresholds. Formal point-in-time data qualification remains unsatisfied.

All 32 registered trials, costs/capital/service/cash/settlement/dividend/timing sensitivities, leakage challenges, 10,000-sample paired bootstrap inference and descriptive exposure attribution are saved in `../results/experiments_2026-10-07/EXPERIMENT_REPORT.md` and `experiment_summary.json`. Trial definitions, daily/order ledgers, annual metrics, turnover attribution, run history, hashes and independent verification are retained in the same directory. No best-performing control replaces the primary candidate.

To reproduce the frozen snapshot's experiment:

```bash
.venv/bin/python research/test_backtest_engine.py
.venv/bin/python research/run_experiments.py
.venv/bin/python research/verify_experiments.py
```

The experiment uses the separate price snapshot in `../data/experiments_2026-10-07/`, including unscored December 2014–December 2015 warmup and a saved FRED DFF CSV response with source URL/time/hash. `fetch_snapshot.py --protocol research/experiment_protocol.json` reuses the registered price snapshot. Reproduction uses the saved rate snapshot, avoiding silent vintage replacement. Economic rules and thresholds are frozen in `experiment_protocol.json` and the original specification. The exact preregistered amendment is `EXPERIMENT_NOTES.preregistered.md`; subsequent reporting/accounting evidence repairs are recorded in `EXPERIMENT_NOTES.md`. The trial register's amendment hash refers to the preregistered file.

Six synthetic/chronological accounting tests passed. The independent verifier imports no simulator code and checks raw-open fills, forward trend states, lagged liquidity/rates, dividend entitlement, integer holdings, cash releases, NAV, fees, turnover, Sharpe/drawdown and evidence hashes across all trials. These checks validate arithmetic and provenance, not independent market-source accuracy. All history remains exploratory; no live trading or prospective confirmation is delivered.

The specification is preserved in `../docs/RESEARCH_SPECIFICATION.md` and the online [research Page](https://chatgpt.com/space/page_86592798e8f0819194bbb9873d79d4ee). The current default protocol, `eda_protocol_current.json`, records the user-authorized horizon amendment before acquisition. Its main period is January 2016 through October 7, 2026, the latest completed session at the recorded run time. It includes separate 2021-onward, 2026-only and current-week summaries. Protocol and specification hashes are in `../data/through_2026-10-07/manifest.json`.

## Reproduce

Run from the project root using Python 3.12:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r research/requirements.txt
.venv/bin/python research/fetch_snapshot.py
.venv/bin/python research/explore_data.py
.venv/bin/python research/verify_evidence.py
```

The fetcher reuses saved raw responses. Current requests cover December 31, 2015, through October 7, 2026; the first date supplies only the preceding close for the January 2016 return. It fails if a returned bar falls outside the selected protocol interval. The current outputs include this week's completed sessions on October 5, 6 and 7. October 8 was not yet open in New York at the recorded run time. Do not remove saved responses to silently replace the evidence snapshot. A new acquisition should use a separate directory and manifest.

The prior 2006–2015 snapshot and results are retained. To reproduce the original scope, pass `--protocol research/eda_protocol.json` to each script. The current default supersedes the old scope; merely reusing the legacy files would not satisfy current coverage.

## Outputs

- `../data/through_2026-10-07/raw/`: original provider JSON responses.
- `../data/through_2026-10-07/normalized/`: session-labelled OHLCV and adjusted-close CSV files.
- `../data/through_2026-10-07/manifest.json`: source URLs, retrieval times, file hashes and specification/protocol hashes.
- `../results/through_2026-10-07/EDA_REPORT.md`: current report with figures.
- `../results/through_2026-10-07/eda_summary.json`: detailed machine-readable checks and descriptive statistics.
- `../results/through_2026-10-07/*.csv`: returns, distributions, flagged observations, correlations, lags, volume relationships, expected sessions, subperiod comparisons and current-week bars.
- `../results/through_2026-10-07/charts/`: full-period distribution/correlation/rolling-risk figures and a separate 2026 correlation figure.
- `../results/through_2026-10-07/evidence_checksums.json` and `verification.json`: output hashes and independent arithmetic/provenance checks.

## Interpretation boundaries

The public snapshot is an exploratory proxy. Its current adjustments are not historical point-in-time vintages. OHLC has not been qualified as unadjusted executable prices, and the dataset lacks dividend payment dates, historical release times, spreads and actual auction fills. Raw responses also include current quote metadata; analysis ignores those metadata fields and uses only the requested historical observations.

No prices or returns are forward filled. Extreme observations are retained and flagged for review. Same-session and lagged correlations are descriptive and are not evidence of a profitable strategy. At the user's request, previously held-out historical observations from 2016 onward are now explored. They must not be described as untouched confirmatory evidence. A future confirmatory test requires a newly designated prospective period. Data-access success does not establish commercial redistribution rights.

Formal strategy evaluation still requires the original data and execution gates in the specification. The research hypothesis and rejection criteria must not be changed in response to this exploration.
