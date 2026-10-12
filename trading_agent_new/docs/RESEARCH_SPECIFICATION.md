This study tests whether a rebalancing buffer improves a daily ETF trend strategy after trading costs. The primary comparison holds the signal and portfolio construction rules constant and changes only the rule for executing small allocation adjustments. Separate controls test whether any apparent advantage comes from volatility scaling, cash exposure, or broad market exposure.

Specification version 1 was prepared on October 8, 2026, in Asia/Shanghai time. The confirmed scope is US listed equities and ETFs with daily data; the first experiment uses six ETFs. Status: literature reviewed and experiment specified before candidate performance analysis. No candidate backtests, return calculations, parameter searches, data purchases, or trades form part of this stage. The numerical settings and acceptance thresholds below are proposed experimental choices, not results taken from the papers.

## Literature and implications

Moskowitz, Ooi, and Pedersen document time series momentum in liquid futures across asset classes. This motivates testing an asset's own trailing return as a signal. A long or cash ETF implementation changes the instruments, leverage, shorting, and execution assumptions, so it is an adaptation rather than a replication of their strategy. [Time series momentum, 2012](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2019/09/TimeSeriesMomentum.pdf).

Moreira and Muir study portfolios that reduce exposure when recent variance is high. Their evidence motivates a volatility control, but their inverse variance factor portfolios differ from the inverse volatility ETF allocation specified here. [Volatility Managed Portfolios, working paper 2016 and published 2017](https://www.nber.org/papers/w22208).

Cederburg, O'Doherty, Wang, and Yan find that volatility management does not systematically improve direct portfolio comparisons and that historical regression benefits can fail to translate into implementable performance. Consequently, the experiment includes an otherwise identical portfolio without a trend filter and makes no assumption that volatility management is beneficial. [On the performance of volatility managed portfolios, 2020](https://www.lehigh.edu/~xuy219/research/COWY.pdf).

Gârleanu and Pedersen derive trading policies that account for the costs of moving toward changing portfolio targets. Their work motivates balancing tracking error against transaction costs. It does not establish that the particular two percentage point buffer below is optimal. [Dynamic Trading with Predictable Returns and Transaction Costs, published 2013](https://www.nber.org/papers/w15205).

Frazzini, Israel, and Moskowitz examine live institutional equity trading and find that implementation costs affect strategy families differently. Their setting motivates evaluating net results and turnover, rather than importing their cost estimates into this ETF experiment. [Trading Costs of Asset Pricing Anomalies, 2012 working paper](https://www.aqr.com/insights/research/working-paper/trading-costs-of-asset-pricing-anomalies).

Bailey and López de Prado show why selecting among many backtests inflates apparent performance. The study therefore fixes one primary candidate, records every attempted configuration, and prohibits replacing the primary candidate with the best robustness variant. [The Deflated Sharpe Ratio, 2014](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

## Market behavior and candidate ideas

The working mechanism is that a slow trend signal can remain unchanged while daily volatility estimates and price drift repeatedly change target weights. Small adjustments might consume trading costs without materially improving portfolio behavior. A buffer can save those costs, but can also delay risk reductions or let positions drift away from their intended exposure. Whether the saving outweighs this tracking error is the research question.

Gradual information adjustment and persistent flows are possible explanations for trends; this experiment does not identify their cause. Choppy markets, rapid reversals, and abrupt volatility changes are plausible failure conditions, rather than reasons to assume a trend strategy always works.

| Candidate | Hypothesis to investigate | Main execution or data constraint | Decision for this study |
| --- | --- | --- | --- |
| ETF time series momentum | An asset's own trailing return contains useful information for deciding when to hold it | Cash opportunity cost, whipsaws, and gaps between decisions and fills | Use as the fixed strategy background |
| Volatility managed ETF allocation | Adjusting exposure with lagged volatility improves the tradeoff between risk and return | Changing targets create turnover; forecasts can become stale | Include as a control, without assuming improvement |
| Short horizon equity reversal | Temporary liquidity pressure creates subsequent reversals | Greater sensitivity to spreads, timing, stock universes, and borrow if shorting | Defer to a separate specification |
| ETF trend with a rebalancing buffer | Skipping small target changes improves net performance while preserving risk behavior | Stale exposure can erase cost savings | Select as the single primary hypothesis |

The selected experiment is small enough to reproduce with daily prices, has a direct comparator, and exposes an important research-to-execution tradeoff. It tests an implementation improvement; it does not establish a novel alpha source or an agent's ability to improve itself.

## Hypothesis and estimands

Primary hypothesis H1: at a simulated starting capital of USD 100,000, a fixed two percentage point rebalancing buffer improves the net annualized Sharpe ratio of the specified ETF trend strategy by at least 0.10 relative to daily rebalancing without a buffer, and reduces traded notional relative to capital by at least 25%, without materially worsening return or risk.

The primary estimands are the candidate minus comparator Sharpe difference and the proportional reduction in turnover. Define turnover as the sum of the absolute dollar value of every filled buy and sell divided by portfolio NAV immediately before that fill, annualized over the measurement period. This is two-sided traded notional. Include initial purchases when they fall inside the scored interval. Carry portfolios across period boundaries and mark the final holdings to market; do not invent boundary or terminal liquidations.

Secondary question: does the complete trend strategy offer useful performance relative to a portfolio with identical volatility construction but no trend filter? This is a separate, descriptive attribution question. H1 can succeed even if the overall strategy is unsuitable for an investor.

The mechanism predicts that any gain will mainly arise through lower implementation costs. Report gross performance, explicit costs, target tracking error, exposure, and net performance separately so a change in risk taking is visible.

## Universe and datasets

The fixed universe is SPY, IWM, EFA, IEF, TLT, and GLD. It provides two US equity exposures, an international developed equity exposure, two Treasury duration exposures, and gold through US listed funds. These are predefined research instruments, not investment recommendations. Do not add or replace funds after inspecting returns.

Selecting surviving ETFs today limits historical generalization. A broad data provider does not remove this selection issue. Conclusions apply to these instruments under the stated assumptions; a later stock-universe or alternative-fund study needs a new specification.

| Input | Proposed source | Required fields and treatment |
| --- | --- | --- |
| Daily ETF prices | AlgoSeek US Equities dataset through QuantConnect or an equivalently licensed delivery of the same dataset | Raw open, high, low, close, volume, stable security identifiers, session date, and recorded availability time |
| Corporate actions | QuantConnect US Equity Security Master | Splits, dividends, symbol mappings, effective dates, and delistings |
| Dividend cash timing | Fund issuer distribution records where the price vendor lacks payable dates | Ex date, amount, and payable date; record the receivable separately from spendable cash |
| Reference interest rate | FRED DFF with ALFRED vintages | Annual percentage rate actually available at the decision time |
| Market calendar | Versioned US exchange calendar | Sessions, holidays, early closes, and America/New_York timezone rules |

[AlgoSeek dataset documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/algoseek/us-equities), [Security Master documentation](https://www.quantconnect.com/docs/v2/cloud-platform/datasets/quantconnect/auxiliary-data), [FRED DFF](https://fred.stlouisfed.org/series/DFF), [ALFRED vintages](https://alfred.stlouisfed.org/series/downloaddata?seid=DFF).

The requested extraction covers January 1, 2006, through September 30, 2026. Earlier observations provide warmup only. Verify actual coverage before admitting an instrument. Do not reconstruct a pre-inception ETF history using its index.

Create a dataset manifest with provider, license and permitted use, extraction time, file checksums, identifiers, coverage, corporate-action conventions, and revisions. Provider entitlement and an actual data snapshot remain prerequisites for running the experiment.

Construct a forward total-return index using only corporate actions effective by each historical decision date. Use this index for trailing returns and volatility. Use raw prices and share quantities for trading. Account for dividend entitlement and later cash payment once; do not also credit dividends through adjusted execution prices. ETF expenses embedded in market prices are not deducted a second time. [Corporate actions](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/corporate-actions).

Daily OHLCV does not reveal historical spreads, order queues, or attainable auction fills. The first backtest will use explicitly assumed cost scenarios, followed by prospective execution calibration before any deployment decision.

## Time partitions and information boundaries

| Period | Dates | Permitted use |
| --- | --- | --- |
| Warmup | January 1, 2006, through December 31, 2007 | Initialize trailing windows; no scored portfolio performance |
| Development | First US trading session in 2008 through December 31, 2015 | Data and accounting checks, implementation debugging, and declared development diagnostics |
| Validation | January 1, 2016, through December 31, 2020 | Evaluate the unchanged specification in five calendar-year folds and as one continuous portfolio |
| Final historical holdout | January 1, 2021, through September 30, 2026 | One evaluation after validation passes; inaccessible to strategy selection and tuning beforehand |
| Prospective observation | First eligible session after implementation and code/configuration freeze | Observe at least 12 months; no retrospective substitution for this period |

Windows contain the exchange sessions falling inside those dates. Before the final holdout is opened, freeze code, configuration, data manifest, and report templates with recorded hashes. Only validation data may determine whether to stop or proceed. Failure in validation ends this candidate's confirmatory path; the final holdout cannot rescue it.

Initialize each portfolio with USD 100,000 in cash at the first eligible development session in 2008. Evolve it chronologically and carry its NAV, holdings, cash, receivables, and pending settlement into validation and the holdout. Score each interval from its preceding closing NAV without resetting capital or forcing trades at a boundary. There are no fitted predictive labels in this experiment. A 252-session feature window may use earlier observations across a partition boundary because those prices were already available. It may not use later prices or a full-sample normalization.

The historical holdout is withheld from this workflow, but historical events and published strategies may already be known to the researcher or language model. It is therefore a retrospective generalization check, not proof of complete ignorance of the historical period. Prospective observation is required for evidence on genuinely later market outcomes.

Any economically meaningful amendment becomes a new numbered specification and remains visible beside version 1. If a bug invalidates an already inspected holdout, correct it transparently and use a fresh evaluation period; do not describe the inspected period as untouched.

## Fixed signal and portfolio rules

Evaluate once per session using the most recently completed session's data available before the order cutoff. For the proposed bulk provider, published documentation places daily updates in the following morning; the implementation must check actual arrival before submitting orders. No signal receives a same-close fill. [Data availability documentation](https://www.quantconnect.com/docs/v2/lean-cli/datasets/quantconnect/us-equity).

For each asset, the trend indicator is 1 when its own trailing 252-session total return is strictly positive and 0 otherwise. Zero means cash, rather than a short position. Estimate sample volatility and covariance from the last 63 completed daily total returns and annualize with 252. Use a 5% annual volatility floor for inverse-volatility allocation.

The following notation fixes the target calculation. Sigma is the annualized sample covariance matrix; all inputs use completed, available observations.

```text
signal_i = 1 if TR_i[t] / TR_i[t-252] - 1 > 0 else 0
score_i = signal_i / max(annual_vol_i, 0.05)

if sum(score) == 0:
    target_i = 0 for every asset
else:
    b_i = score_i / sum(score)
    forecast_vol = sqrt(b_transpose * Sigma * b)
    scale = min(0.95, 0.10 / max(forecast_vol, 0.01))
    target_i = min(0.25, scale * b_i)
```

Unallocated wealth remains cash. The 10% value is a forecast volatility reference, not a promise of realized volatility. Position and gross-exposure caps may reduce exposure below that reference. Do not redistribute cash left by the per-asset cap. No shorting, borrowing, options, futures, or leverage is included.

Comparator B0 refreshes every target daily, subject to integer-share rounding and the common execution constraints.

Candidate B2 refreshes an asset only when the absolute difference between its current weight and target weight is at least 0.02, meaning two percentage points of total portfolio NAV. A trend-state change overrides the buffer, including an exit to cash or a new entry. A zero target always triggers liquidation of any remaining shares. Any unfilled portion of an entry, exit, or risk override is reconsidered at the next decision using current information until resolved. A zero-share order is omitted.

Risk overrides also take precedence over the buffer. Cap provisional individual weights at 25%. If their total exceeds 95%, scale them proportionally down to 95%, without allocating the residual upward. Log every override. Before placing orders, compare both strategies using the same corporate-action handling, current holdings, NAV, and integer-share sizing method.

Compute desired shares from the last available raw close and current NAV, without using the future fill price to select weights. Apply known split adjustments before queued orders become executable. Orders remain fixed until execution checks accept, reduce, or reject them. Buffer decisions use actual holdings, not an assumed perfectly filled portfolio.

## Benchmarks and attribution controls

| Identifier | Strategy | Purpose |
| --- | --- | --- |
| B0 | Daily trend strategy with zero buffer | Primary comparator for H1 |
| B2 | Identical strategy with the fixed two percentage point buffer | Single primary candidate |
| B1 and B3 | Identical strategy with one and three percentage point buffers | Prespecified sensitivity; cannot replace B2 |
| Monthly | B0 targets refreshed on the final completed session of each calendar month and traded the next eligible session | Simpler scheduling alternative |
| NoTrend | B0 construction with all trend indicators fixed at 1 | Isolate the contribution of the trend filter |
| EqualWeight | Six ETFs at equal weights, 95% invested, rebalanced monthly | Diversified passive context |
| SPY | SPY bought at the first eligible fill and held with common dividend and cost accounting | Familiar equity-market context |

The 25% asset cap applies to the diversified strategy variants, while SPY is intentionally a concentrated descriptive benchmark. Benchmarks are evaluated on identical dates, capital, price snapshots, cash assumptions, and cost conventions.

All metrics are measured from the actual simulated portfolios. Do not apply a full-sample volatility rescaling to make a strategy look comparable. Report realized volatility, average gross exposure, cash weight, SPY beta, Treasury exposure, and gold exposure alongside returns. Correlated equity and Treasury funds are not six independent bets.

## Execution and cost assumptions

The primary simulated account starts with USD 100,000 and permits reinvestment of sale proceeds within the same session, with no borrowing and no negative cash. This is an account-model assumption to verify with a broker before any deployment; it is not a claim that every retail account has those permissions.

Use the next eligible session's raw open as a preliminary fill reference, with adverse slippage and commissions. Submit orders only after the previous session's complete data is available. Fill sells before buys. A common execution-side cash check rejects or reduces buys if opening gaps or fees would cause a cash deficit. Reduce eligible buy quantities proportionally, round down to whole shares, and leave rounding residuals in cash. The researcher cannot use opening prices to regenerate that day's signals or select new target weights.

Limit filled shares per asset per session to 0.1% of its preceding 20-session median raw share volume, rounded down. Unfilled quantities are canceled and reconsidered at the next decision; never fill them with hindsight using that day's eventual total volume. Missing or stale prices prevent new trades in the affected asset. A halt prevents fills; record the portfolio and data exceptions.

These are simulated liquidity and fill rules, not evidence of real execution quality. Report raw opening gaps, rejected orders, participation, partial fills, and realized cash or concentration breaches. Any negative-cash or short position caused by implementation invalidates the run.

| Item | Fixed assumption |
| --- | --- |
| Primary spread and slippage charge | 5 basis points of filled notional per side |
| Commission | Maximum of USD 1 per order and USD 0.005 per filled share |
| Adverse cost sensitivities | 10 and 25 basis points per side, retaining the same commission rule |
| Gross ledger attribution | Add modeled trading charges back to portfolio P&L while holding actual trades fixed; this is an attribution measure, not a separate self-financing strategy, and cannot be used for selection |
| Primary cash credit | Zero interest, to avoid assuming institutional cash economics |
| Cash sensitivity | Available DFF less 0.50 percentage points, floored at zero; a hypothetical credit rather than a broker quote |
| Capital sensitivities | USD 10,000 and USD 1,000,000 |
| Fixed service-cost sensitivity | USD 1,200 per year, debited USD 100 on the first session of each calendar month; explicitly hypothetical |

Use a reference rate known by the prior decision, retrieved from its vintage and lagged at least two US sessions. Convert its annual percentage rate to the calendar-day return between NAV observations using a 365-day compounded convention. Use the same reference risk-free return when calculating all excess-return Sharpe ratios.

A required settled-cash sensitivity permits purchases only from settled cash and models the historical settlement calendar: T+3 before September 5, 2017; T+2 until May 27, 2024; and T+1 from May 28, 2024. Include settlement holidays and dividend payable dates. [SEC T+2 implementation](https://www.sec.gov/newsroom/press-releases/2017-163), [SEC T+1 implementation](https://www.sec.gov/newsroom/press-releases/2024-62).

Do not infer investor-specific after-tax performance from this study. Record distributions and turnover so a later specification can apply a declared tax jurisdiction and account type. Access to adequate cash accounting, exchange data rights, and brokerage permissions remains a feasibility condition.

## Experiment sequence and evaluation

1. Record version 1 and the intended data source before examining candidate performance.

2. Obtain the authorized dataset and manifest. Validate schema, calendar alignment, corporate actions, missing data, dividend accounting, and information timestamps.

3. Verify the implementation on small accounting examples: splits preserve economic value, distributions are credited once, cash remains nonnegative, and a signal at t cannot fill at t. These checks establish correctness, not profitability.

4. Run development diagnostics with the frozen economic rules. Correct implementation errors with a visible change log; do not optimize the buffer, lookback, volatility window, or caps.

5. Run the primary validation comparison and all declared controls. Keep one continuous portfolio through 2016–2020; compute calendar-year diagnostics from that continuous run. Report each attempted variant.

6. Stop if validation fails practical criteria or remains statistically inconclusive. Only a validation pass opens the final historical holdout.

7. Apply exactly the same primary criteria to the final holdout. Report each calendar year, identifying 2026 as a partial year. No sensitivity variant can rescue a failed B2.

8. If historical evidence supports proceeding, prepare a separate prospective paper-trading implementation and execution-calibration plan. This specification does not itself launch or schedule it.

Primary Sharpe uses the sample mean of daily net excess returns divided by their sample standard deviation, multiplied by the square root of 252. Daily portfolio returns include weekend effects between session marks through the cash convention. Also report CAGR, annualized volatility, maximum peak-to-trough drawdown, downside deviation, turnover, cost drag, and exposure.

Estimate uncertainty in the paired Sharpe difference using 10,000 stationary block-bootstrap resamples of aligned candidate and comparator daily return/reference-rate vectors. Use the same resampled dates for both strategies, expected block length 21 sessions, and seed 20261008. Define the one-sided 95% lower confidence bound as the fifth percentile of the bootstrap differences. A 63-session expected block length is a reported sensitivity, not a substitute test chosen after viewing results.

Use calendar years and lagged SPY volatility quartiles for descriptive regime diagnostics. Quartile cutoffs are computed in the development period and frozen. No regime classification may use future return labels to change trades.

Maintain a trial register containing every strategy version, cost setting, account model, attempted run, error, and result. The sole confirmatory candidate is B2. Parameter, universe, or strategy-family changes require a new specification; do not claim that the best row among many controls was the original hypothesis.

## Acceptance and rejection criteria

The following thresholds are fixed design choices for this first study. They are not guarantees of power or universal investment thresholds.

H1 receives provisional support on validation only if all conditions hold:

- B2 net Sharpe minus B0 net Sharpe is at least 0.10 at the primary cost assumption.

- The paired bootstrap one-sided 95% lower bound is greater than zero.

- Turnover is at least 25% lower than B0.

- B2 realized annualized volatility is no more than 110% of B0 volatility; its maximum drawdown is no more than two percentage points worse; and CAGR is no more than 0.50 percentage points below B0.

- The Sharpe difference is positive in at least three of the five validation calendar years.

- The Sharpe difference remains positive at 25 basis points per side.

- Both the one and three percentage point buffers produce positive Sharpe differences under the primary cost assumption, indicating that the result is not restricted to an isolated two-point setting.

- Data and execution integrity checks pass.

Apply the same conditions to the final holdout, replacing the validation-year count with a majority of completed calendar years. Report the partial 2026 year separately and exclude it from that vote.

Reject the candidate for practical use if any fixed effect-size, turnover, risk, return, stability, or cost criterion fails. If practical criteria pass but the confidence bound includes zero, label the result statistically inconclusive and retain it without promotion. A data or accounting failure invalidates evidence rather than disproving the hypothesis.

Separately label the complete strategy economically unsuitable for a particular account scenario if it has nonpositive annualized mean excess return after declared trading and fixed service costs, or if the account cannot execute its orders under the specified constraints. Passing H1 alone cannot establish an attractive standalone investment.

Even full historical support advances the candidate only to prospective paper testing and fill calibration. It does not authorize live capital or establish market-wide alpha.

## Research deliverables and handoff

The next stage should produce a data manifest; a versioned strategy configuration; reproducible strategy and account ledgers; the full trial register; a report of all benchmarks, sensitivities, and confidence intervals; and a decision of supported, practically rejected, statistically inconclusive, or invalid.

Record every trade's decision timestamp, data availability, signal, target and current weights, submitted quantity, fill reference, charges, rejection or partial fill, and resulting holdings and cash. Preserve failed hypotheses and implementation failures as distinct outcomes.

For the proposed research-agent product, this task can later become a benchmark for reproducing a specification, detecting bad evidence, and making the correct accept or reject decision. Demonstrating agent self-improvement requires a separate study comparing agent versions on new research tasks with equal data access and compute budgets.

Completed at this stage: literature review, candidate comparison, primary hypothesis selection, datasets and benchmarks specified, experiment protocol, and rejection criteria. Remaining before performance analysis: obtain an authorized data snapshot and implement and verify the frozen rules. No project implementation or existing runtime has been changed.

