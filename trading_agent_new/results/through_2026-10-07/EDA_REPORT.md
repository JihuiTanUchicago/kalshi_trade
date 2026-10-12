# Current-horizon ETF data exploration

Completed October 8, 2026 (Asia/Shanghai). The hypothesis and rejection rules were fixed before these checks. No strategy backtest or parameter search was performed.

Source: Yahoo Finance public daily chart snapshot. Requested bars: 2015-12-31 through 2026-10-07. Statistical summaries: 2016-01-01 to 2026-10-07. Latest common available session: 2026-10-07.

Historical validation/holdout periods are now exploratory at the user's request; they are not untouched confirmatory evidence.

Calendar: 2,707 expected sessions; 2,706 analysis sessions; 21 half days. Known historical closures are checked explicitly.

## Missingness and structural checks

| ETF | Rows | Missing sessions | Missing cells | OHLC violations | Zero-volume days |
| --- | ---: | ---: | ---: | ---: | ---: |
| SPY | 2707 | 0 | 0 | 0 | 0 |
| IWM | 2707 | 0 | 0 | 0 | 0 |
| EFA | 2707 | 0 | 0 | 0 | 0 |
| IEF | 2707 | 0 | 0 | 0 | 0 |
| TLT | 2707 | 0 | 0 | 0 | 0 |
| GLD | 2707 | 0 | 0 | 0 | 0 |

No forward filling, winsorization, or deletion of flagged market extremes was applied.

## Return distributions

| ETF | Annualized volatility | 1st percentile daily return | 99th percentile daily return | Skewness | Excess kurtosis |
| --- | ---: | ---: | ---: | ---: | ---: |
| SPY | 17.70% | -3.20% | 2.64% | -0.31 | 14.71 |
| IWM | 22.73% | -3.64% | 3.59% | -0.48 | 7.68 |
| EFA | 17.24% | -2.83% | 2.71% | -0.80 | 13.80 |
| IEF | 6.54% | -1.04% | 1.14% | 0.18 | 3.31 |
| TLT | 14.67% | -2.26% | 2.36% | 0.12 | 5.19 |
| GLD | 16.45% | -3.03% | 2.77% | -0.50 | 6.76 |

![Return distributions](charts/return_distributions.png)

These are distributions of individual ETF adjusted-close returns, not strategy returns. Tail flags are review candidates, not proof of bad data.

SPY excess kurtosis is 14.71; EFA is 13.80. This sample has substantial tails and is not well described by a fixed Gaussian return model. No extreme-value cleaning is justified by distribution shape alone.

## Outliers and volume checks

The prespecified checks flagged 31 asset/session observations. All remain in the evidence. Examples include SPY +10.50% on 2025-04-09, IWM -13.27% on 2020-03-16, and GLD -10.27% on 2026-01-30. These large moves require independent corroboration before formal evidence qualification.

IEF has 4 observations above ten times its preceding 20-session median volume. These flags could reflect actual trading or data problems; this single-source snapshot cannot decide between them. Median shares traded per session and return/relative-volume relationships are in volume_relationships.csv.

## Relationships

| ETF | SPY | IWM | EFA | IEF | TLT | GLD |
| --- | --- | --- | --- | --- | --- | --- |
| SPY | 1.00 | 0.86 | 0.84 | -0.12 | -0.15 | 0.08 |
| IWM | 0.86 | 1.00 | 0.79 | -0.10 | -0.13 | 0.09 |
| EFA | 0.84 | 0.79 | 1.00 | -0.06 | -0.11 | 0.19 |
| IEF | -0.12 | -0.10 | -0.06 | 1.00 | 0.91 | 0.34 |
| TLT | -0.15 | -0.13 | -0.11 | 0.91 | 1.00 | 0.26 |
| GLD | 0.08 | 0.09 | 0.19 | 0.34 | 0.26 | 1.00 |

![Return correlations](charts/return_correlations.png)

SPY/IWM correlation is 0.86, SPY/EFA is 0.84, and IEF/TLT is 0.91. Multiple ETF tickers do not imply independent exposures. SPY/TLT is -0.15 and SPY/GLD is 0.08 over this sample, but their rolling correlations vary materially.

Same-session relationships are descriptive. Annual and rolling correlations, Spearman correlations, sample counts, within-asset lags, and volume relationships are exported separately. They do not establish predictive ability.

![Rolling risk](charts/rolling_risk.png)

## Timing and adjustments

Daily timestamps are converted to America/New_York before assigning session dates. A bar labelled 09:30 represents a full daily bar; it was not available at 09:30. Features based on its close require completed-session data and a later eligible execution session.

Yahoo adjusted close incorporates splits and dividends. Event/adjustment checks are descriptive reconciliation against the same provider, not an independent validation. The raw response can contain dynamic current quote metadata; that metadata is excluded from all analysis.

Across dividend-paying ETFs, adjustment-factor changes reconcile with the reported distributions to a maximum difference of 0.0091 basis points. No significant factor changes lack a reported dividend. Closing-price and adjusted-close daily returns differ by up to 2.12 percentage points for EFA, showing why dividend handling matters. This does not verify dividend payment dates or historical adjustment vintages.

## Qualification decision

Structural checks pass: True. The snapshot is suitable for this descriptive exploration only. The original formal-data requirements remain outstanding: point-in-time revisions, qualified raw execution prices, dividend payment dates, historical release timing, independent source checks, and applicable data rights.

No hypothesis, window, threshold, universe, cost assumption, or rejection criterion was changed after exploration.

Sources: [Yahoo adjusted-close definition](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html); [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars); [NYSE trading calendar](https://www.nyse.com/trade/hours-calendars); [Nasdaq Sandy closure notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2012-44).

Detailed evidence: eda_summary.json, flagged_observations.csv, largest_moves.csv, return_distributions.csv, correlation_*.csv, annual_correlations.csv, rolling_correlation_summary.csv, lagged_correlations.csv, volume_relationships.csv, expected_sessions.csv, and data/through_2026-10-07/manifest.json.

## Current year and recent sessions

The 2026 summary runs through 2026-10-07. Recent windows use the same return, distribution and relationship definitions as the main study. This week has only 3 completed sessions; its bars are a freshness check, not enough observations for a reliable distribution or Sharpe estimate.

| ETF | 2026 observations | 2026 annualized volatility | 2026 daily 1st percentile | 2026 daily 99th percentile |
| --- | ---: | ---: | ---: | ---: |
| SPY | 192 | 13.05% | -1.81% | 1.98% |
| IWM | 192 | 18.14% | -2.30% | 3.04% |
| EFA | 192 | 17.18% | -2.61% | 3.12% |
| IEF | 192 | 5.08% | -0.82% | 0.68% |
| TLT | 192 | 9.67% | -1.58% | 1.33% |
| GLD | 192 | 30.81% | -4.17% | 3.90% |

![2026 correlations](charts/return_correlations_2026.png)

| ETF | Latest session | Latest daily asset return | Week-to-date asset return | Trailing 63-session volatility |
| --- | --- | ---: | ---: | ---: |
| SPY | 2026-10-07 | -0.24% | +0.98% | 10.96% |
| IWM | 2026-10-07 | -1.29% | -1.36% | 13.12% |
| EFA | 2026-10-07 | -1.07% | -0.83% | 12.81% |
| IEF | 2026-10-07 | -0.02% | +0.07% | 5.14% |
| TLT | 2026-10-07 | -0.17% | -0.43% | 9.78% |
| GLD | 2026-10-07 | -1.67% | -1.12% | 24.52% |

Week-to-date returns compound the completed daily adjusted-close returns from the preceding week's last close. These are asset observations, not simulated trading-strategy profits. Full weekly OHLCV bars are in current_week_bars.csv. Detailed window comparisons are in subperiod_distributions.csv and subperiod_correlations.csv.
