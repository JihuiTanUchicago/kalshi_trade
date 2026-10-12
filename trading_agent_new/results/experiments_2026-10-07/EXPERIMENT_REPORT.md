# Controlled ETF experiments and decision — October 8, 2026

Decision: **PRACTICALLY REJECTED UNDER PROXY ASSUMPTIONS**.

Six ETFs; continuous integer-share accounts January 4, 2016–October 7, 2026 (2,706 sessions). Primary capital $100,000; five basis points adverse cost per side, commissions max($1/order, $0.005/share); cash earns zero. B0 and B2 share signals, target construction, source prices and execution accounting. B2 adds a two-percentage-point buffer, with trend and risk overrides. All 32 trials were registered before performance evaluation.

This is historical exploratory evidence. The periods were already explored. Current-vintage public data, assumed dividend payment dates and an approximate settlement calendar do not satisfy the original formal data gate.

## Matched baseline and candidate

| Strategy | Net excess Sharpe | CAGR | Volatility | Max drawdown | Annual two-sided turnover |
|---|---:|---:|---:|---:|---:|
| B0 | 0.140 | 3.02% | 6.85% | 19.20% | 10.57× |
| B1 | 0.212 | 3.53% | 6.85% | 18.82% | 9.64× |
| B2 | 0.220 | 3.59% | 6.86% | 18.79% | 9.19× |
| B3 | 0.230 | 3.65% | 6.84% | 18.79% | 8.72× |
| Monthly | 0.248 | 3.85% | 7.19% | 15.79% | 2.28× |
| NoTrend | 0.355 | 4.62% | 7.08% | 20.20% | 2.32× |
| EqualWeight | 0.595 | 7.76% | 9.56% | 22.71% | 0.37× |
| SPY | 0.749 | 13.70% | 15.85% | 30.57% | 0.09× |

B2 minus B0: Sharpe +0.0802; turnover reduction 13.05%; CAGR difference +0.568 percentage points; volatility ratio 1.002; drawdown deterioration -0.408 percentage points.

## Sampling uncertainty and time stability

| Period | B0 Sharpe | B2 Sharpe | Gain | 21-session bootstrap 5th percentile | 63-session 5th percentile |
|---|---:|---:|---:|---:|---:|
| full | 0.140 | 0.220 | +0.0802 | +0.0575 | +0.0581 |
| 2016_2020 | 0.349 | 0.439 | +0.0895 | +0.0511 | +0.0534 |
| 2021_current | -0.003 | 0.071 | +0.0740 | +0.0467 | +0.0451 |
| 2026_partial | -0.222 | -0.098 | +0.1240 | not tested | not tested |

10,000 paired stationary bootstrap samples per panel and block length; seed 20261008. The fifth percentile is the one-sided 95% lower bound; the reported fifth-to-95th range is a central 90% interval. Sampling uncertainty conditional on this history does not account for all prior idea selection or make these periods independent holdouts.

Positive annual differences: 5/5 in 2016–2020; 9/10 completed years. 2026 does not vote. Leave-one-year-out gain range: +0.0764 to +0.0856. Those diagnostics drop scoring observations and do not re-run the trading path.

The original panel gates are also retained: 2016–2020 and 2021–current each fail the 0.10 Sharpe gain and 25% notional-turnover thresholds; their remaining practical and sampling gates pass. The 2021–2025 completed-year vote passes with 4/5 positive years. The formal source gate fails in both.

## Costs and operational sensitivities

| Assumption | B2 − B0 Sharpe | Turnover reduction |
|---|---:|---:|
| primary | +0.0802 | 13.1% |
| cost10 | +0.0944 | 13.0% |
| cost25 | +0.1281 | 12.9% |
| capital10000 | +0.1607 | 13.4% |
| capital1000000 | +0.0348 | 13.4% |
| service | +0.0886 | 13.2% |
| cashyield | +0.0936 | 13.0% |
| settled | +0.0755 | 13.6% |
| dividend0 | +0.0802 | 13.1% |
| dividend60 | +0.0802 | 13.1% |
| lag | +0.0864 | 13.1% |
| nocommission | +0.0262 | 13.0% |
| costfree | +0.0096 | 13.1% |

Total commissions: B0 $6,841.68, B2 $1,329.21. Simulated slippage: B0 $6,299.50, B2 $5,601.80. Dollar cost sums occur on different account wealth paths and are not a causal return decomposition. Zero-cost counterparts separate exposure drift from the broad cost-saving mechanism.

Order count falls from 6,781 to 1,263 (81.4%), whereas notional turnover falls only 13.1%. Trend-change exits and entries still require large trades; the buffer mainly removes small resizing orders. This distinction explains why commission savings are much larger than notional-turnover savings. Without commissions, the Sharpe gain drops to 0.0262; with all modeled trading costs removed it is 0.0096. The observed advantage is primarily a friction-saving mechanism in these simulations.

B2's 2021–current excess Sharpe is 0.071, and its 2026 partial-year excess Sharpe is -0.098. A $1,200 annual service charge reduces full-period B2 CAGR to 2.44%. Relative improvement over a costly baseline is not evidence of an attractive standalone strategy.

## Hidden exposures and implementation challenges

| Portfolio | Average cash and claims | Equity | Treasury | Gold | SPY factor beta | Annual intercept, HAC 95% interval |
|---|---:|---:|---:|---:|---:|---|
| B0 | 28.0% | 38.9% | 21.0% | 12.2% | 0.191 | -2.92% [-5.86%, 0.02%] |
| B2 | 28.3% | 38.9% | 20.7% | 12.1% | 0.192 | -2.40% [-5.36%, 0.55%] |
| NoTrend | 12.9% | 35.6% | 38.5% | 13.0% | 0.295 | -2.40% [-3.73%, -1.08%] |
| EqualWeight | 5.4% | 47.4% | 31.4% | 15.8% | 0.447 | -1.91% [-3.49%, -0.32%] |

Factor regression uses contemporaneous SPY, TLT and GLD total excess returns. It is in-sample exposure attribution, not an investable alpha estimate. IEF/TLT overlap and correlated equity funds remain concentrated economic exposures.

B0 closing asset/gross cap breach days: 771/0; B2: 186/0. Prior-close caps cannot prevent price moves or fills from producing small closing breaches; the next decision applies caps. B0/B2 partial or rejected orders: 0/0. All ledgers have nonnegative cash, no shorts and independently reconciled daily P&L.

Settlement constraints reduce eligible buys on 139 B0 sessions and 123 B2 sessions; the declared settlement sensitivity retains a positive incremental Sharpe gain but still misses the practical thresholds. Immediate versus 60-day dividend payments produce the same primary trading path because cash is not binding under those scenarios. This does not establish that assumed payable dates are accurate.

Prefix and future-price/dividend/volume perturbation checks passed for B0 and B2 through 2021. An additional decision-day lag is reported above. These checks address implementation leakage; they do not prove that revised source prices or corporate actions were historically available. Forward versus vendor-adjusted trend-state differences by symbol: {'SPY': 1, 'IWM': 0, 'EFA': 1, 'IEF': 0, 'TLT': 0, 'GLD': 0}.

Assumed dividend payments are tested at 0/30/60 calendar days. The settled-cash trial uses historical T+3/T+2/T+1 with an approximate holiday calendar. Cash yield uses lagged current-vintage DFF less 0.50 percentage points. Service sensitivity deducts $100 on the first session of each month. No tax estimate or observed fill calibration is supplied.

## Fixed decision gates

| Gate | Result |
|---|---|
| sharpe_gain_at_least_0_10 | FAIL |
| turnover_reduction_at_least_25pct | FAIL |
| volatility_ratio_at_most_1_10 | PASS |
| drawdown_deterioration_at_most_2pp | PASS |
| cagr_shortfall_at_most_0_5pp | PASS |
| positive_in_at_least_3_of_5_2016_2020_years | PASS |
| positive_in_majority_completed_2016_2025_years | PASS |
| positive_at_25bps | PASS |
| both_neighbor_buffers_positive | PASS |
| simulator_accounting_and_timing_valid | PASS |
| Positive bootstrap lower bound | PASS |
| Original formal source qualification | FAIL |

Decision: **PRACTICALLY REJECTED UNDER PROXY ASSUMPTIONS**. Failed practical gates: sharpe_gain_at_least_0_10, turnover_reduction_at_least_25pct.

A practical rejection applies to this fixed candidate under the declared proxy assumptions. A formal source failure leaves the original qualified-data claim unvalidated rather than definitively disproving it. The buffer is not retuned, and another control is not promoted because it performed better. A defensible next experiment requires a new specification, qualified data and a genuinely prospective observation period.

Positive annual mean excess after costs: B0 True, B2 True, B2 with service fee True. This is the declared standalone economic screen, separate from the relative buffer hypothesis.

## Reproducible evidence

`trial_register.json`, `all_trial_metrics.csv`, `paired_sensitivity_comparisons.csv`, `annual_metrics.csv`, `experiment_summary.json`, per-trial daily/order ledgers, `run_history.jsonl` and `evidence_checksums.json`. Run `.venv/bin/python research/test_backtest_engine.py`, then `.venv/bin/python research/run_experiments.py`.

Rate source: [FRED DFF](https://fred.stlouisfed.org/series/DFF). Settlement transitions: [SEC T+2](https://www.sec.gov/newsroom/press-releases/2017-163) and [SEC T+1](https://www.sec.gov/newsroom/press-releases/2024-62).
