# Benchmark

## Tau Quant Investing Capability Benchmark

- **Version:** 0.1 — public question bank and evaluation specification.
- **Updated:** October 18, 2026, Asia/Shanghai.
- **Scope:** 72 starter tasks across nine categories; seven market tracks plus cross-market problems.

This benchmark assesses a model or agent's ability to carry out the quantitative investing process: understand instruments, prepare data, discover and validate signals, develop models, construct portfolios, implement trading logic, and make evidence-backed investment decisions.

The allocation is **80% individual workflow tasks and 20% end-to-end research projects**. There is no self-improvement, persistent-learning, or firm-management score. Training a financial prediction model within an assigned task remains in scope. The evaluated agent starts each independent case from its declared initial configuration and does not carry new experience between cases.

**Release status:** This file supplies questions, fixture requirements, deliverables, and assessment criteria. Executable task packets, licensed or synthetic datasets, private reference solutions, automated graders, calibrated difficulty, and model results still need to be built. The market tracks describe the benchmark's intended coverage; they do not assert that every instrument or venue is already implemented in Tau. This document does not replace existing runtime acceptance criteria or historical evaluations.

## Category weights

Percentages are shares of the total score. Question count does not determine category weight.

| ID | Category | Weight | Questions |
|---|---|---:|---:|
| FIN | [Financial reasoning and instrument mechanics](#fin) | 5% | 8 |
| DATA | [Data preparation and integrity](#data) | 10% | 8 |
| ALPHA | [Hypothesis formation and alpha discovery](#alpha) | 10% | 8 |
| STAT | [Experimental design and statistical validation](#stat) | 15% | 8 |
| MODEL | [Feature engineering and model development](#model) | 10% | 8 |
| PORT | [Portfolio construction and risk](#port) | 10% | 8 |
| EXEC | [Execution and trading performance](#exec) | 10% | 8 |
| CODE | [Quant development and software engineering](#code) | 10% | 8 |
| E2E | [End-to-end quant research projects](#e2e) | 20% | 8 |
| **Total** | | **100%** | **72** |

## Market coverage

| Track | Product family | Examples of required distinctions |
|---|---|---|
| EQ | Global cash equities and ETFs | Corporate actions, historical membership, delistings, short borrow, auctions, regional calendars. |
| FI | Fixed income, rates, and credit | Cash-flow schedules, clean/dirty prices, curves, duration, credit events, applicable financing and collateral conventions. |
| FX | Foreign exchange | Quote direction, bid/ask conversion, cross rates, forwards, currency exposure, settlement calendars. |
| FUT | Futures and commodities | Multipliers, contract rolls, expiry/delivery, basis, margin cash flows, seasonality. |
| OPT | Options and volatility products | Exercise/settlement style, surfaces, Greeks, nonlinear exposure, hedging, assignment. |
| CRYPTO | Crypto markets | Spot, linear/inverse derivatives, funding, liquidation, venue-specific collateral; on-chain features when included in a packet. |
| PRED | Prediction markets | Outcome semantics, event grouping, fees, resolution, settlement, collateral, executable depth. |

Each category has one starter task for each of these seven tracks and one `CROSS` task. `CROSS` is a task tag, not an eighth asset class. Each instrument belongs to one primary scoring track; additional underlying exposures can be recorded as secondary tags. Add venue, region, horizon, and regime variants without increasing that template's scoring weight.

All numerical examples below are synthetic. Binding venue rules, fees, calendars, margin policies, exercise instructions, and resolution terms must be supplied in the task packet, with their effective dates. Do not grade against unstated conventions or assume one venue's rules apply globally.

## Evaluation contract

### What a runnable task packet must contain

Every question is a **template**. Its fixture description below is a requirement for the future task author, not a statement that files already exist. A released packet must provide:

1. A case/template ID, version, primary track, provisional difficulty, objective, and permitted actions.
2. Immutable input files with hashes, schemas, units, instrument IDs, and data-quality labels. Economic observations need observation, publication/availability, and revision timestamps where applicable.
3. A decision clock, information boundary, train/validation/test boundaries, and any permitted chronological refitting schedule.
4. Contract specifications, cost/financing assumptions, capital and risk constraints, allowed tools, environment versions, and resource limits.
5. Required outputs, scoring points, numerical tolerances, baselines, and failure rules frozen before evaluation.
6. Runner-private reference calculations/tests or an independently adjudicated rubric. Private labels and grader code must remain outside the agent's readable environment.

Keep models and complete agents on separate leaderboards. Model comparisons use a common harness and tool interface; agent comparisons identify their own fixed scaffolding. Pin the evaluated model, initial memory/corpus, code, prompts, tools, and budgets for each run. Ordinary within-task planning, model fitting, debugging, and retries are allowed within the packet's limits. Reset writable state before the next independent case.

Use existing input snapshots or approved synthetic fixtures; no task requires placing live orders. External downloads or research, if permitted, need a frozen information cutoff and retained source evidence. Store observable tool actions, code, outputs, and concise decision rationales; private model reasoning is not a required artifact.

### Grading and aggregation

The proposed default rubric is **40 points for answer/artifact correctness, 30 for methodological validity, 20 for reproducible evidence, and 10 for decision quality and uncertainty**. Each packet must translate these blocks into explicit checks before a scored run. Objective calculations and code use independent numerical references and tests; expert judgment is reserved for genuinely open-ended criteria. Writing style alone earns no points.

For economic tasks, predeclare the primary out-of-sample metric, reference strategy, score anchors, risk/capital denominator, costs, and uncertainty method. Report financial performance separately from methodological correctness. A well-supported rejection can earn strong process marks; it does not earn positive-alpha credit. Include seeded no-edge cases, flawed backtests, and infeasible requests, with a correct reject/inconclusive response defined in advance.

The score for each task is 0–100. Average repeated runs and fixture variants **within their starter template first**, then give the eight templates equal weight within their category:

```text
category_score = mean(score of the eight starter templates)
overall_score  = sum(category_weight / 100 * category_score)
```

For example, DATA contributes at most 10 points and E2E at most 20. Publish market-track scores separately; do not count a cross-market result again in every constituent track. Missing required templates make a run incomplete: publish its partial results and coverage rather than silently renormalizing an official overall score. Agent failures/timeouts receive their preregistered score; evaluator infrastructure faults must be diagnosed and handled consistently, not quietly dropped.

Use independent chronological holdouts for market-performance tests and structurally fresh private variants for capability tests. A public question bank is not itself an uncontaminated held-out test. Freeze budgets, selection criteria, and grading before outcomes; retain all attempted experiments, not only the winning strategy. Repeat runs and report uncertainty over independent tasks/events/time blocks as appropriate, rather than treating correlated bars or parameter variants as independent observations.

Using future information invalidates the affected predictive/economic evidence. Altering grader inputs or fabricating provenance invalidates the affected run. Ordinary errors should receive their rubric penalties, not be conflated with evaluator tampering. Never translate a good historical score into an unsupported claim of deployable alpha.

Difficulty labels below are provisional: **Foundation** means a bounded numerical/semantic problem; **Applied** requires an executable analysis; **Advanced** requires open-ended design, diagnosis, or multiple coupled decisions.

<a id="fin"></a>

## FIN — Financial reasoning and instrument mechanics — 5%

### FIN-01 — Equity cash flows through a split and dividend

- **Track / level:** EQ / Foundation.
- **Question:** You buy 100 shares at 80, the stock undergoes a 2-for-1 split, pays a 1-per-post-split-share cash dividend, and you sell at a raw price of 41. Entry and exit fees are 10 each. Reconstruct shares, cash flows, net P&L, and return without double-counting the adjustment.
- **Fixture:** Dated raw prices, split/ex-dividend/payment events, trade confirmations, and the evaluation cutoff.
- **Deliverable:** A cash/share ledger, net-return calculation, and distinction between dividend receivable and received cash.
- **Assess:** Correct units and event ordering, fee treatment, accounting identity, and dependence on the cutoff date.

### FIN-02 — Bond prices and accrued interest

- **Track / level:** FI / Foundation.
- **Question:** A bond has face value 1,000, a 4% annual coupon paid semiannually, a clean quote of 99.50 per 100 face, and 60 elapsed days in a specified 180-day accrual period. Calculate accrued interest, dirty consideration, and the next coupon. Explain why the coupon rate is not the investment's yield.
- **Fixture:** Coupon schedule, explicit accrual convention, settlement date, and quoted-price units.
- **Deliverable:** Calculations and a dated cash-flow table.
- **Assess:** Quote scaling, clean/dirty distinction, accrued-interest calculation, and recognition of inputs needed to determine yield.

### FIN-03 — FX quote inversion and conversion

- **Track / level:** FX / Foundation.
- **Question:** EUR/USD is 1.1000/1.1002 and USD/JPY is 150.00/150.03. Construct executable inverse and EUR/JPY bid/ask quotes. Calculate the JPY proceeds from selling EUR 100,000 through the supplied route.
- **Fixture:** Simultaneous firm quotes, sufficient displayed size, zero additional fees, and explicit quote conventions.
- **Deliverable:** Bid/ask arithmetic, currency amounts at each leg, and resulting exposure.
- **Assess:** Correct sides of both books, inverse bid/ask ordering, dimensional consistency, and absence of midpoint execution assumptions.

### FIN-04 — Futures variation and capital denominators

- **Track / level:** FUT / Foundation.
- **Question:** Three long futures contracts have multiplier 50, entry 5,000, and subsequent daily settlements of 5,020 and 4,990. Calculate each variation payment and total P&L. Explain returns measured against notional, posted margin, and total allocated capital.
- **Fixture:** Contract specification, margin requirements, account cash, settlement policy, and fee schedule.
- **Deliverable:** Daily cash ledger and clearly labeled return denominators.
- **Assess:** Multiplier/sign arithmetic, settlement timing, margin versus expense, and consistent capital accounting.

### FIN-05 — Option payoff and physical settlement

- **Track / level:** OPT / Foundation.
- **Question:** Two short European calls have strike 100, multiplier 100, premium 3 per underlying unit, and terminal underlying price 105. Reconcile option P&L with the cash and stock obligations under the supplied physical-settlement instructions. How would a cash-settled contract differ?
- **Fixture:** Contract/exercise rules, premium timing, opening inventory/cash, and fees.
- **Deliverable:** Payoff calculations and both settlement ledgers.
- **Assess:** Short-position signs, premium versus intrinsic value, delivery obligations, and contract-specific treatment.

### FIN-06 — Linear and inverse crypto contracts

- **Track / level:** CRYPTO / Applied.
- **Question:** Compare a linear USD-settled perpetual and an inverse BTC-settled perpetual using the same declared entry exposure. Calculate P&L, funding, fees, and collateral value at the supplied exit price. Explain why their native-unit balances and liquidation behavior can differ.
- **Fixture:** Exact payoff formulas, multipliers, prices, funding observations, collateral rules, and timestamps.
- **Deliverable:** Native-currency and common-currency ledgers plus exposure calculations.
- **Assess:** Payoff units, conversion timing, funding signs, and use of supplied rather than assumed contract rules.

### FIN-07 — Binary-market payout and apparent arbitrage

- **Track / level:** PRED / Foundation.
- **Question:** YES and NO ask prices are 0.46 and 0.50, with a 0.01 fee per purchased contract on each side. Under which supplied resolution and payout rules does buying both lock in a return? Re-evaluate when cancellation and delayed settlement are introduced.
- **Fixture:** Complementary-outcome mapping, sizes, payout/cancellation terms, fees, capital, and settlement horizon.
- **Deliverable:** State-by-state payoff and cash-lockup table.
- **Assess:** Exhaustive outcomes, executable costs/sizes, refund handling, and conditional rather than blanket arbitrage claims.

### FIN-08 — Cross-market instrument normalization

- **Track / level:** CROSS / Applied.
- **Question:** Normalize an equity share, ETF, futures contract, option, FX position, perpetual, and binary event contract into comparable price, exposure, and cash-flow records. Identify which apparently similar exposures cannot be treated as interchangeable.
- **Fixture:** A typed instrument master, quote samples, currencies, multipliers, lifecycle rules, and available hedge mappings.
- **Deliverable:** A normalization table with conversions and explicit limits of equivalence.
- **Assess:** Distinction among price/notional/risk, native cash flows, nonlinear/contingent payoffs, and preservation of economically material terms.

<a id="data"></a>

## DATA — Data preparation and integrity — 10%

### DATA-01 — Point-in-time equity research panel

- **Track / level:** EQ / Applied.
- **Question:** Build an eligible daily equity panel from historical membership, raw prices, corporate actions, filings, and delisting records. Ensure every feature and universe decision uses information available at that decision time.
- **Fixture:** Stable security IDs, changing tickers/membership, publication/revision times, action records, and missing/delisted observations.
- **Deliverable:** Executable transformation, quality report, provenance, and timestamp assertions.
- **Assess:** Survivor inclusion, as-of joins, correct adjustments, explicit missingness, and prevention of revised-data leakage.

### DATA-02 — Bond panel with asynchronous observations

- **Track / level:** FI / Applied.
- **Question:** Reconcile trades, executable quotes, evaluated marks, coupon schedules, and issuer metadata into a bond panel without treating stale or indicative observations as contemporaneous executable prices.
- **Fixture:** Observation types, event/receipt times, accrued-interest fields, issuer IDs, and staleness limits.
- **Deliverable:** Normalized panel, observation-quality flags, and reconciliation exceptions.
- **Assess:** Clean/dirty consistency, stale-data handling, source hierarchy, and preservation of unavailable values rather than invented liquidity.

### DATA-03 — Multi-venue FX synchronization

- **Track / level:** FX / Applied.
- **Question:** Construct decision-time FX features from asynchronous venue quotes across a daylight-saving transition and holiday boundary. Define which quotes are admissible and identify apparent spreads caused only by timing.
- **Fixture:** UTC event/receipt timestamps, venue calendars, quote directions, sequence IDs, and maximum quote age.
- **Deliverable:** A causal join pipeline, admissibility flags, and timing diagnostics.
- **Assess:** Availability-time filtering, timezone correctness, bid/ask integrity, and no interpolation from later quotes.

### DATA-04 — Continuous futures versus tradable contracts

- **Track / level:** FUT / Applied.
- **Question:** Build research features from a continuous futures series while reconstructing executable P&L using actual contracts and a declared roll schedule. Demonstrate how a roll discontinuity or backward adjustment can create a false signal.
- **Fixture:** Individual contract bars, expiry/roll dates, adjustment factors, volumes, and multipliers.
- **Deliverable:** Research series, contract mapping, and a raw-contract reconciliation.
- **Assess:** Separation of feature and execution prices, causal roll selection, roll costs, and correct treatment of adjustment artifacts.

### DATA-05 — Options-chain quality and contract identity

- **Track / level:** OPT / Applied.
- **Question:** Prepare an options chain for surface estimation, resolving identifier changes, adjusted deliverables, stale/crossed quotes, missing strikes, and expiry-time differences without silently selecting favorable observations.
- **Fixture:** Instrument master, bid/ask/size snapshots, underlying quotes, exercise style, calendars, and filter policy.
- **Deliverable:** Cleaned chain, retained/excluded-row audit, and synchronized underlying mapping.
- **Assess:** Contract identity, time-to-expiry units, transparent filters, causal alignment, and distinguishable missing versus zero values.

### DATA-06 — Crypto book reconstruction with feed gaps

- **Track / level:** CRYPTO / Applied.
- **Question:** Reconstruct order-book features from a snapshot and sequenced updates containing duplicates, missing messages, reconnects, and exchange/receipt clock differences. Decide when features become invalid and when reconstruction may resume.
- **Fixture:** Snapshot/delta schemas, sequence rules, event/receipt times, reconnect snapshots, and trade prints.
- **Deliverable:** Reconstructed books, gap flags, and a valid-feature mask.
- **Assess:** Sequence integrity, correct level updates/deletions, causal recovery, and no backfilling an earlier decision with a later snapshot.

### DATA-07 — Prediction-market lifecycle and labels

- **Track / level:** PRED / Applied.
- **Question:** Build a research dataset linking events, markets, outcome tokens, rule revisions, trades, and resolution records. Preserve open/unresolved examples and prevent the same event from leaking across training and evaluation.
- **Fixture:** Versioned metadata, token IDs, availability times, event groups, lifecycle states, and settlement evidence.
- **Deliverable:** Canonical mappings, causal features, event-grouped splits, and label-quality flags.
- **Assess:** Correct outcome direction, historically valid terms, separation of resolution from tradability, and explicit censored labels.

### DATA-08 — Mixed-source availability audit

- **Track / level:** CROSS / Advanced.
- **Question:** Audit a panel combining market data, economic releases, earnings, news, and crypto events. Find every feature that uses a publication revision, timezone conversion, or delivery delay unavailable at the stated decision time.
- **Fixture:** Original/revised vintages, receipt logs, calendars, decision clocks, and seeded timestamp defects.
- **Deliverable:** Defect inventory, corrected causal joins, and executable timing checks.
- **Assess:** Fault localization, preservation of original vintages, justified uncertainty, and rejection of unverifiable historical availability.

<a id="alpha"></a>

## ALPHA — Hypothesis formation and alpha discovery — 10%

### ALPHA-01 — Equity reversal beyond known exposures

- **Track / level:** EQ / Advanced.
- **Question:** Propose three distinct short-horizon equity hypotheses motivated by an economic mechanism. Select one, preregister its test, and determine whether it adds value beyond the supplied momentum, size, volatility, and liquidity baselines.
- **Fixture:** Causal development panel, eligible universe, baseline signals, borrow/cost assumptions, and a fixed experiment budget.
- **Deliverable:** Hypothesis register, executable signal, controls, and proceed/revise/reject recommendation.
- **Assess:** Falsifiability, distinctness from supplied factors, feasible trading assumptions, and incremental evidence rather than a persuasive narrative alone.

### ALPHA-02 — Credit spread convergence or stale marking

- **Track / level:** FI / Advanced.
- **Question:** Investigate whether observed spread convergence between comparable bonds is an exploitable relative-value signal or a consequence of stale evaluated prices, issuer risk, maturity differences, or illiquidity.
- **Fixture:** Bond characteristics, executable quotes/trades, evaluated marks, financing, benchmark curves, and issuer events.
- **Deliverable:** Mechanism, matched comparison, tradable signal specification, and falsification tests.
- **Assess:** Confounder treatment, execution feasibility, appropriate spread/risk units, and willingness to reject apparent alpha unsupported by executable observations.

### ALPHA-03 — FX carry under changing risk conditions

- **Track / level:** FX / Advanced.
- **Question:** Design and test a conditional carry hypothesis using only forward points and state information available before entry. Explain the expected compensation, crash exposure, and evidence required to call the result incremental alpha.
- **Fixture:** Spot/forward quotes, funding conventions, macro vintages, risk-state features, calendars, and carry baselines.
- **Deliverable:** Frozen signal/sizing/exit rules, cost model, controls, and evidence summary.
- **Assess:** Return construction, economic mechanism, risk exposure attribution, and avoidance of selecting favorable regimes after observing results.

### ALPHA-04 — Commodity curve and seasonality hypothesis

- **Track / level:** FUT / Advanced.
- **Question:** Investigate whether a commodity-curve signal predicts subsequent tradable returns after accounting for seasonality, contract rolls, trend, and transaction costs. Identify a result that would falsify the mechanism.
- **Fixture:** Individual contract histories, curve snapshots, seasonal variables, roll policy, multipliers, and existing signals.
- **Deliverable:** Candidate mechanism, causal feature definition, preregistered evaluation, and executable contract selection.
- **Assess:** Tradable targets, separation from known exposures, seasonal controls, and honest accounting of all experiments.

### ALPHA-05 — Volatility forecast versus selling tail risk

- **Track / level:** OPT / Advanced.
- **Question:** Formulate a volatility strategy and determine whether its expected value comes from forecasting realized volatility, relative-value mispricing, or compensation for convexity and tail exposure. Specify a hedge and falsification plan.
- **Fixture:** Causal option chains, underlying paths, volatility forecasts, costs, exercise rules, and reference strategies.
- **Deliverable:** Hypothesis, selected contracts, hedging rules, stress scenarios, and exposure-adjusted comparison.
- **Assess:** Distinction between forecast skill and risk premia, realistic option execution, path-dependent losses, and incremental evidence.

### ALPHA-06 — Crypto funding and basis opportunity

- **Track / level:** CRYPTO / Advanced.
- **Question:** Investigate a spot/perpetual basis or funding strategy. Determine whether the prospective edge survives fees, collateral requirements, liquidation exposure, funding uncertainty, and venue-specific financing constraints.
- **Fixture:** Timestamped executable quotes, historical funding information as available at entry, contract rules, balances, and venue limits.
- **Deliverable:** Entry/exit rules, funding forecast or bounds, capital ledger, and opportunity/rejection analysis.
- **Assess:** Prospective information use, feasible hedge construction, full cost/capital treatment, and no assumption of known future funding.

### ALPHA-07 — Prediction-market probability edge

- **Track / level:** PRED / Advanced.
- **Question:** Propose a causal probability-estimation or cross-contract hypothesis for a supplied event family. Determine whether its predictions offer an executable edge after fees and resolution uncertainty, beyond the market-price baseline.
- **Fixture:** Anonymized event groups, decision-time prices/depth, available external evidence, contract terms, and historical resolved examples.
- **Deliverable:** Hypothesis, event-selection policy, forecast/signal implementation, and falsification criteria.
- **Assess:** Probability calibration, semantic contract alignment, independence of evaluation events, and separation of predictive accuracy from tradable value.

### ALPHA-08 — Cross-market hypothesis selection

- **Track / level:** CROSS / Advanced.
- **Question:** Given a fixed research budget and heterogeneous datasets, select two competing hypotheses to investigate. Include a mechanism-based idea and a negative control, and justify why the selected experiments are informative.
- **Fixture:** Data dictionary, availability constraints, baseline library, permissible strategy families, and trial budget.
- **Deliverable:** Ranked research plan, frozen tests, experiment ledger, and bounded conclusions.
- **Assess:** Information value, falsifiability, exposure/cost awareness, and rejection of spurious discoveries in seeded no-edge variants.

<a id="stat"></a>

## STAT — Experimental design and statistical validation — 15%

### STAT-01 — Audit an impressive equity backtest

- **Track / level:** EQ / Applied.
- **Question:** Audit a supplied high-performing backtest containing temporal, universe, corporate-action, execution, or selection defects. Locate the defects, repair the evaluation, and explain which original conclusions remain supportable.
- **Fixture:** Research notebook/code, raw inputs, information timestamps, experiment history, and independent accounting references.
- **Deliverable:** Defect report, corrected executable evaluation, and before/after attribution.
- **Assess:** Substantive fault detection, causal repairs, preservation of unfavorable results, and invalidation of unsupported performance claims.

### STAT-02 — Overlapping bond-return labels

- **Track / level:** FI / Applied.
- **Question:** Evaluate a bond-return predictor trained on overlapping forward-return labels and observations clustered by issuer. Design a split and uncertainty estimate that account for both temporal overlap and common issuer exposures.
- **Fixture:** Label horizons, publication times, issuer groups, calendar boundaries, and baseline predictions.
- **Deliverable:** Split-generation code, purge/embargo rationale where needed, and grouped uncertainty estimates.
- **Assess:** Leakage prevention, appropriate unit of independence, sufficient evaluation coverage, and justified conclusions from sparse data.

### STAT-03 — Paired FX strategy comparison

- **Track / level:** FX / Applied.
- **Question:** Determine whether one FX strategy improves on another when both trade the same periods and currency universe. Account for serial dependence, common shocks, turnover, and financing differences.
- **Fixture:** Aligned position/return/cost records, account currency, matched risk budget, and sampling conventions.
- **Deliverable:** Paired comparison, uncertainty intervals, sensitivity checks, and decision.
- **Assess:** Use of paired rather than unrelated observations, correct return units, dependence-aware inference, and practical as well as statistical significance.

### STAT-04 — Best-of-many futures strategies

- **Track / level:** FUT / Advanced.
- **Question:** A researcher selects the highest-Sharpe futures strategy from a large parameter search. Assess how much evidence remains after accounting for selection, correlated trials, non-normal returns, and untouched evaluation data.
- **Fixture:** Complete trial register, strategy-return series, dependencies among candidates, and a protected evaluation interface.
- **Deliverable:** Selection-aware analysis, validation plan, and defensible deploy/research/reject conclusion.
- **Assess:** Full trial accounting, justified multiplicity treatment, uncertainty, and resistance to presenting the selected in-sample score as established alpha.

### STAT-05 — Option-strategy tail-risk evaluation

- **Track / level:** OPT / Advanced.
- **Question:** Assess an option strategy with a high win rate and smooth ordinary-period returns but occasional large losses. Compare it with a risk-matched reference and test sensitivity to gaps, volatility shifts, costs, and sample boundaries.
- **Fixture:** Full position/payoff histories, hedge records, scenario paths, and option execution assumptions.
- **Deliverable:** Distribution/tail diagnostics, stress results, uncertainty estimates, and exposure attribution.
- **Assess:** Economic relevance of tail losses, nonlinear risk recognition, honest sampling uncertainty, and avoidance of win-rate-only conclusions.

### STAT-06 — Crypto walk-forward evaluation

- **Track / level:** CRYPTO / Applied.
- **Question:** Design a walk-forward evaluation for highly correlated crypto assets with overlapping targets, exchange duplicates, and repeated hyperparameter search. Identify which reported improvement comes from leakage or validation reuse.
- **Fixture:** Time-stamped features/labels, venue mappings, refit schedule, tuning logs, and fixed baselines.
- **Deliverable:** Reproducible fold policy, leakage audit, search accounting, and protected-test procedure.
- **Assess:** Chronological separation, grouped duplicate handling, transformation fitting boundaries, and no repeated tuning against final test outcomes.

### STAT-07 — Prediction calibration and event dependence

- **Track / level:** PRED / Applied.
- **Question:** Evaluate probability forecasts when many contracts concern the same event, positive outcomes are rare, and some markets remain unresolved. Compare forecast quality and trading value with appropriate baselines.
- **Fixture:** Event groups, historical forecasts, prices, labels with resolution times, censoring flags, fees, and depths.
- **Deliverable:** Proper-score/calibration analysis, event-grouped uncertainty, and separately reported trading results.
- **Assess:** No false independence across related contracts, explicit unresolved cases, sensible base-rate comparisons, and no confusion between accuracy and profitability.

### STAT-08 — Cross-market evidence and annualization

- **Track / level:** CROSS / Advanced.
- **Question:** Audit a comparison of strategies spanning exchange-session assets, 24/7 crypto, and event-settled contracts. Correct incompatible annualization, capital denominators, benchmark exposures, and selection decisions before ranking evidence.
- **Fixture:** Equity curves, cash/positions, sampling calendars, costs, selected/unselected trials, and reference mandates.
- **Deliverable:** Comparable metrics, dependence-aware intervals, cost sensitivity, and an evidence-strength assessment.
- **Assess:** Consistent risk/capital treatment, appropriate observation units, preserved adverse results, and explicit limits to cross-market comparisons.

<a id="model"></a>

## MODEL — Feature engineering and model development — 10%

### MODEL-01 — Cross-sectional equity predictor

- **Track / level:** EQ / Applied.
- **Question:** Build a predictor of the supplied forward excess-return target using a causal equity panel. Compare simple and more flexible models, tune on development folds, and explain each retained feature's incremental contribution.
- **Fixture:** Eligible panel, target definition, baseline forecasts, publication times, split policy, and training budget.
- **Deliverable:** Training/inference code, fitted artifact, ablations, validation results, and frozen final predictions.
- **Assess:** Leakage-free transforms/tuning, baseline comparisons, generalization, and evidence supporting model complexity.

### MODEL-02 — Bond spread forecasting with sparse data

- **Track / level:** FI / Advanced.
- **Question:** Forecast a specified tradable spread-change target in an irregular bond panel. Handle issuer dependence, maturity effects, missing quotes, and heteroskedastic risk without turning non-executable marks into training truth.
- **Fixture:** Bond characteristics, reliable target flags, quote/trade records, issuer groups, curves, and chronological splits.
- **Deliverable:** Target/feature pipeline, regularized model, uncertainty estimates, and stratified validation.
- **Assess:** Target quality, risk-unit consistency, appropriate regularization, issuer/time separation, and calibrated uncertainty in sparse segments.

### MODEL-03 — FX event-conditioned forecast

- **Track / level:** FX / Applied.
- **Question:** Build an event-conditioned forecast for a supplied FX return or volatility target around macro releases. Decide whether the available information improves on unconditional and simple event baselines.
- **Fixture:** First-release macro vintages, expectations known beforehand, spot/forward data, event times, and target horizon.
- **Deliverable:** Causal features, model selection, calibration/forecast diagnostics, and an ablation of event information.
- **Assess:** Release-time discipline, correct target/loss choice, chronological validation, and incremental value rather than event-name memorization.

### MODEL-04 — Futures curve and seasonal features

- **Track / level:** FUT / Applied.
- **Question:** Predict a specified futures or calendar-spread target using curve and seasonal information. Compare against trend/carry baselines and explain whether gains survive different roll and contract-selection choices.
- **Fixture:** Tradable contracts, curve snapshots, seasonal inputs, roll mappings, target definition, and costs.
- **Deliverable:** Feature code, fitted model, controlled ablations, and frozen predictions.
- **Assess:** Causal contract handling, target/price consistency, appropriate model complexity, and robustness to representation artifacts.

### MODEL-05 — Constrained option-surface calibration

- **Track / level:** OPT / Advanced.
- **Question:** Fit a volatility or option-price surface to the supplied chain while respecting the packet's no-arbitrage constraints. Evaluate interpolation, extrapolation, Greek stability, and uncertainty at sparse strikes/expiries.
- **Fixture:** Cleaned quotes/weights, forwards/discount factors, exercise conventions, calibration bounds, and private evaluation points.
- **Deliverable:** Calibration/inference implementation, fitted parameters, residual diagnostics, and constraint tests.
- **Assess:** Pricing consistency, stable optimization, out-of-sample error, constraint satisfaction, and honest extrapolation limits.

### MODEL-06 — Crypto microstructure prediction

- **Track / level:** CRYPTO / Applied.
- **Question:** Predict a short-horizon return or order-flow target from reconstructed books and trades. Compare a regularized linear model with a flexible alternative, accounting for feature latency, overlap, and venue differences.
- **Fixture:** Valid causal book/trade features, target definition, receipt times, grouped walk-forward folds, and compute budget.
- **Deliverable:** Training pipeline, inference artifact, latency-aware feature ablations, and frozen predictions.
- **Assess:** Baseline discipline, time-valid features, stable cross-period/venue behavior, and no selection against private test labels.

### MODEL-07 — Event-level probability model

- **Track / level:** PRED / Applied.
- **Question:** Estimate binary outcome probabilities from the supplied pre-resolution evidence. Compare market-price and base-rate baselines, calibrate forecasts, and evaluate whether any improvement is economically actionable.
- **Fixture:** Anonymized event groups, causal features, historical resolved labels, price snapshots, private event holdouts, and fees.
- **Deliverable:** Probability model, grouped calibration analysis, baseline comparison, and trading-threshold rationale.
- **Assess:** Proper scoring, bounded probabilities, event separation, resolution semantics, and distinction between forecast improvement and executable edge.

### MODEL-08 — Heterogeneous features and ablation

- **Track / level:** CROSS / Advanced.
- **Question:** Determine whether adding news, macro, order-flow, or cross-asset inputs improves a supplied baseline model. Choose transformations and losses appropriate to the targets, and isolate incremental benefit under matched budgets.
- **Fixture:** Source availability records, modality schemas, baseline artifacts, chronological splits, and a fixed search allowance.
- **Deliverable:** Reproducible feature/model comparison, ablations, uncertainty estimates, and final selection.
- **Assess:** Fair comparisons, correct fitting boundaries, non-redundant feature contribution, and justified rejection of unhelpful complexity.

<a id="port"></a>

## PORT — Portfolio construction and risk — 10%

### PORT-01 — Constrained equity signal portfolio

- **Track / level:** EQ / Applied.
- **Question:** Convert forecasts into a long/short portfolio subject to capital, sector, factor, concentration, turnover, and borrow constraints. Compare it with a simple eligible baseline and explain binding constraints.
- **Fixture:** Forecasts, covariance/exposures, borrow availability/cost, holdings, prices, and explicit risk limits.
- **Deliverable:** Reproducible allocation code, target shares, cost estimate, and constraint report.
- **Assess:** Feasibility after rounding, distinction between forecast strength and exposure, covariance sensitivity, and correct handling of unavailable shorts.

### PORT-02 — Rates and credit risk decomposition

- **Track / level:** FI / Applied.
- **Question:** Construct a bond portfolio with declared rate and credit exposures, then hedge specified key-rate risks without violating liquidity or funding constraints. Assess non-parallel curve and spread shocks.
- **Fixture:** Cash flows, curves, key-rate sensitivities, credit exposures, hedge instruments, executable sizes, and financing assumptions.
- **Deliverable:** Holdings, hedge calculation, residual risk table, and stress P&L.
- **Assess:** DV01/credit-unit consistency, executable hedge sizes, convexity limitations, and explicit infeasibility when constraints cannot all be satisfied.

### PORT-03 — Multi-currency exposure and hedging

- **Track / level:** FX / Applied.
- **Question:** Reconstruct currency exposures from overlapping spot and forward positions, including non-base-currency cash. Design a hedge under the supplied limits and evaluate joint FX shocks.
- **Fixture:** Currency ledgers, quote directions, forward contracts, settlement dates, covariance/scenarios, and base currency.
- **Deliverable:** Net currency vector, hedge positions, settlement cash needs, and scenario results.
- **Assess:** Correct base/quote signs, no double-counted cash, feasible funding, and recognition of correlated rather than isolated pair risks.

### PORT-04 — Futures sizing with discrete contracts

- **Track / level:** FUT / Applied.
- **Question:** Allocate across futures using the supplied forecasts and risk estimates while respecting discrete contracts, margin, cash buffers, position limits, and roll deadlines. Compare with naive notional weighting.
- **Fixture:** Multipliers, volatilities/correlations, initial positions/cash, margin schedules, liquidity, and expiry rules.
- **Deliverable:** Integer contract targets, residual allocations, risk/margin report, and stress cash flows.
- **Assess:** Feasible rounding, total-capital denominator, variation-margin liquidity, and differences between margin usage and economic risk.

### PORT-05 — Nonlinear options portfolio

- **Track / level:** OPT / Advanced.
- **Question:** Size and hedge an options portfolio under delta, gamma, vega, loss, and liquidity constraints. Explain when Greek-based approximations break down and evaluate full repricing under the specified scenarios.
- **Fixture:** Positions, pricing model, surface scenarios, underlying hedges, contract rules, costs, and capital limits.
- **Deliverable:** Proposed trades, before/after sensitivities, repriced stress losses, and limitations.
- **Assess:** Nonlinear and path-dependent exposure, hedge feasibility, scenario consistency, and treatment of exercise/settlement changes.

### PORT-06 — Crypto hedge with segmented collateral

- **Track / level:** CRYPTO / Advanced.
- **Question:** Allocate and hedge spot/perpetual positions across venues with separate collateral pools. Stress a funding reversal, stablecoin depeg, price gap, and unavailable transfer route.
- **Fixture:** Native balances, contract formulas, margin/liquidation rules, transfer delays, fees, and scenarios.
- **Deliverable:** Position and collateral allocation, per-venue solvency checks, stress P&L, and reduction plan.
- **Assess:** Actual collateral accessibility, linear/inverse exposures, liquidation buffers, and no assumption that portfolio neutrality guarantees venue-level funding sufficiency.

### PORT-07 — Correlated event-contract allocation

- **Track / level:** PRED / Advanced.
- **Question:** Size positions across related event contracts using supplied probabilities and admissible joint outcome states. Compare an independence-based allocation with one respecting logical dependence, liquidity, and collateral lockup.
- **Fixture:** Contract terms, joint-state constraints or probability scenarios, quotes/depth, fees, resolution horizons, and capital.
- **Deliverable:** Allocation, state-by-state payout/loss table, cash requirements, and sensitivity to probability error.
- **Assess:** Logical consistency, bounded downside, feasible sizes, and avoidance of treating correlated bets as independent diversification.

### PORT-08 — Cross-asset allocation under stress

- **Track / level:** CROSS / Advanced.
- **Question:** Combine seven market sleeves under a common capital and risk mandate. Determine whether apparent diversification survives shared macro exposures, correlation shifts, liquidity reductions, and collateral constraints.
- **Fixture:** Sleeve forecasts/positions, risk mappings, native accounting, benchmark mandates, costs, and stress scenarios.
- **Deliverable:** Allocation method, feasible holdings, risk attribution, stress results, and rejected alternatives.
- **Assess:** Comparable risk/capital measures, financing/collateral feasibility, concentration after aggregation, and principled treatment of infeasible requests.

<a id="exec"></a>

## EXEC — Execution and trading performance — 10%

### EXEC-01 — Equity execution under participation limits

- **Track / level:** EQ / Applied.
- **Question:** Execute a supplied equity target in replay while respecting participation, price, time, and inventory limits. Compare a simple schedule with an adaptive policy using only information available at each decision.
- **Fixture:** Book/trade replay, arrival price, order types, fees, latency, queue/fill assumptions, and target deadline.
- **Deliverable:** Executable policy, order/fill trace, unfilled quantity, and implementation-shortfall report.
- **Assess:** Feasible fills, limit compliance, adverse-selection/cost attribution, and no assumption that touching a quote guarantees execution.

### EXEC-02 — Bond execution from firm and indicative quotes

- **Track / level:** FI / Applied.
- **Question:** Choose an execution plan for a bond order when available observations mix firm quotes, indicative prices, evaluated marks, and size-dependent dealer responses. Determine whether the intended trade remains economically justified.
- **Fixture:** Time-stamped quote types/sizes, RFQ response rules, accrued interest, fees, deadline, and urgency objective.
- **Deliverable:** Routing/acceptance policy, transaction ledger, and cost/opportunity analysis.
- **Assess:** Executability, staleness, full consideration, size effects, and defensible non-execution when no admissible trade exists.

### EXEC-03 — Executable FX triangular opportunity

- **Track / level:** FX / Advanced.
- **Question:** Evaluate an apparent triangular FX opportunity across venues and implement a bounded replay policy. Account for bid/ask sides, size, fees, latency, leg risk, and accessible balances.
- **Fixture:** Asynchronous books, venue balances, fee/latency rules, settlement constraints, and a deterministic execution simulator.
- **Deliverable:** Opportunity calculation, order sequence or rejection, fill trace, and residual-currency reconciliation.
- **Assess:** Executable rather than midpoint profitability, volume constraints, causal quotes, and management of incomplete multi-leg execution.

### EXEC-04 — Futures roll with partial fills

- **Track / level:** FUT / Applied.
- **Question:** Roll a futures position before the packet's cutoff when the two legs have different liquidity and may fill partially. Compare a permitted spread order with sequential execution.
- **Fixture:** Contract books, positions, expiry/delivery rules, spread-order semantics, margin, fees, and replay timing.
- **Deliverable:** Roll policy, leg-level fills, residual exposure, cash/margin path, and completion status.
- **Assess:** Deadline handling, temporary exposure, executable liquidity, correct multipliers, and honest treatment of an incomplete roll.

### EXEC-05 — Multi-leg option execution and hedge costs

- **Track / level:** OPT / Advanced.
- **Question:** Trade an option spread and its underlying hedge under a fixed risk mandate. Compare package execution with legging when quotes move, fills are partial, and hedging incurs costs.
- **Fixture:** Option/underlying books, package-order rules, fees, latency, exercise conventions, and scenario paths.
- **Deliverable:** Execution policy, fill/hedge trace, realized costs, and residual-risk report.
- **Assess:** Atomicity assumptions, contract multipliers, nonlinear leg risk, hedge slippage, and economically valid cost comparisons.

### EXEC-06 — Crypto order-state recovery

- **Track / level:** CRYPTO / Applied.
- **Question:** An order request times out after a partial fill and the stream reconnects with duplicate events. Reconcile the actual order state and complete or cancel the target according to the packet's objective.
- **Fixture:** Exchange API/event simulator, idempotency semantics, order/fill IDs, balances, sequence rules, and position limits.
- **Deliverable:** Executable state-handling logic, action trace, and reconciled final balances.
- **Assess:** No duplicate economic order, correct handling of unknown acknowledgments, deduplicated fills, and limit compliance during recovery.

### EXEC-07 — Prediction-market edge after execution costs

- **Track / level:** PRED / Applied.
- **Question:** Convert supplied probability forecasts into orders on a binary-contract book. Determine which sizes and prices retain positive expected value after fees, partial fills, and the specified settlement risks.
- **Fixture:** Forecasts, timestamped depth, native fee/payout rules, collateral, lifecycle events, and replay assumptions.
- **Deliverable:** Order/no-order policy, fill ledger, expected-value calculation, and settlement-aware P&L.
- **Assess:** Correct YES/NO direction, feasible depth, economic sizing, cash lockup, and no use of final outcomes before their availability.

### EXEC-08 — Cross-market transaction-cost attribution

- **Track / level:** CROSS / Applied.
- **Question:** Explain why simulated and realized returns differ across the seven market tracks. Attribute the gap to spread, delay, impact, fees, funding/borrow, conversion, and model assumptions without counting any item twice.
- **Fixture:** Decision quotes, intended orders, fills, native cash ledgers, financing, conversion rates, and reference executions.
- **Deliverable:** Reconciled cost bridge in native and common units, with uncertainty and residual exceptions.
- **Assess:** Comparable denominators, identifiable versus estimated costs, exact ledger reconciliation, and no attribution of unexplained residuals to alpha.

<a id="code"></a>

## CODE — Quant development and software engineering — 10%

### CODE-01 — Repair an equity backtest engine

- **Track / level:** EQ / Applied.
- **Question:** Fix a small backtester that mishandles a supplied combination of signal timing, splits/dividends, short cash flows, settlement, or fees. Preserve its documented interface and demonstrate the repair.
- **Fixture:** Defective code, interface specification, raw events, small accounting examples, and private regression cases.
- **Deliverable:** Patch, meaningful tests, reproducible ledger, and concise defect explanation.
- **Assess:** Correct accounting/timing, coverage of failure cases, no hardcoded fixture answers, and no unrelated behavior changes.

### CODE-02 — Robust fixed-income valuation

- **Track / level:** FI / Applied.
- **Question:** Implement a cash-flow valuation and sensitivity routine using the supplied schedule/day-count/curve interfaces. Handle irregular coupons, negative yields, near-maturity cases, and invalid input explicitly.
- **Fixture:** Cash-flow schedules, discount-curve contract, numerical tolerances, reference examples, and input-validation rules.
- **Deliverable:** Pricing/sensitivity code, numerical checks, error handling, and runnable tests.
- **Assess:** Numerical stability, units, derivative checks, schedule handling, and reproducibility against independent reference calculations.

### CODE-03 — Currency-safe conversion library

- **Track / level:** FX / Applied.
- **Question:** Implement conversions that preserve currency units and executable bid/ask direction. Support inverse quotes, crosses, lot/tick rounding, and multi-currency P&L, while rejecting incompatible or stale inputs.
- **Fixture:** Typed quote/amount interfaces, precision rules, calendars, staleness policy, and reference conversion cases.
- **Deliverable:** Library functions, boundary/property tests, and a conversion audit trace.
- **Assess:** Dimensional correctness, inversion symmetry where applicable, executable sides, deterministic rounding, and explicit failure behavior.

### CODE-04 — Event-driven futures ledger

- **Track / level:** FUT / Applied.
- **Question:** Implement a replay ledger for futures fills, daily settlements, fees, margin movements, and rolls. Make it deterministic under replay and robust to duplicate event delivery.
- **Fixture:** Event schema/order rules, multipliers, cash accounts, settlement/margin policy, and reference identities.
- **Deliverable:** Ledger implementation, cash/position outputs, duplicate-handling tests, and checkpoint replay.
- **Assess:** No double-counted P&L, correct variation cash, integer positions, preserved identities, and consistent replay from identical inputs.

### CODE-05 — Numerically reliable option pricing

- **Track / level:** OPT / Applied.
- **Question:** Implement or repair the supplied option-pricing/Greek interface and improve its runtime under a fixed resource limit. Verify limiting cases, bounds, convergence, and sensitivities before claiming a speedup.
- **Fixture:** Specified pricing model, contract conventions, parameter grid, independent reference values, and pinned performance environment.
- **Deliverable:** Correct implementation, convergence/property tests, benchmark script, and accuracy/runtime results.
- **Assess:** Accuracy across edge cases, stable Greeks, correctness-preserving optimization, and measured rather than asserted performance.

### CODE-06 — Reliable crypto order-book implementation

- **Track / level:** CRYPTO / Applied.
- **Question:** Implement a streaming book reconstructor and feature interface from the supplied venue protocol. Handle deletions, duplicates, sequence gaps, reconnection, and decimal precision within resource limits.
- **Fixture:** Protocol specification, snapshot/delta stream, allowed recovery actions, price/size precision, and adversarial edge cases.
- **Deliverable:** Implementation, event tests, valid/invalid-state indicators, and resource measurements.
- **Assess:** Correct state transitions, deterministic results, no silent gap repair from future data, and reliable precision/resource behavior.

### CODE-07 — Prediction-contract lifecycle engine

- **Track / level:** PRED / Applied.
- **Question:** Implement the supplied outcome-token and lifecycle specification, including trading, pending resolution, resolution changes, cancellation/refund, and settlement. Compute contract balances and cash flows without prematurely releasing collateral.
- **Fixture:** Explicit event/state grammar, transition rules, payout formulas, fees, token mappings, and reference state sequences.
- **Deliverable:** State engine, payout ledger, invalid-transition handling, and replay tests.
- **Assess:** Semantic direction, unresolved-state handling, exact payout arithmetic, legal transitions under the supplied rules, and deterministic reconciliation.

### CODE-08 — Optimize a causal cross-asset feature pipeline

- **Track / level:** CROSS / Advanced.
- **Question:** Optimize a slow rolling-feature pipeline while preserving its specified results and information boundaries. Prove that changing future rows cannot alter earlier outputs, and prevent leakage across instruments or folds.
- **Fixture:** Baseline implementation, schemas, causal feature definitions, tolerances, private data variants, and pinned CPU/memory limits.
- **Deliverable:** Optimized code, equivalence/prefix-perturbation tests, profile, and reproducible resource comparison.
- **Assess:** Correctness before speed, instrument isolation, causal transforms, bounded memory, and no fixture-specific shortcuts.

<a id="e2e"></a>

## E2E — End-to-end quant research projects — 20%

These are standalone projects with their own development data and protected evaluation. Do not reuse a workflow task's inspected private answers as fresh project evidence. Each project should return a data audit, preregistered research plan/trial register, executable pipeline, any fitted artifacts, causal forecasts/signals, position/order/cash records, reproducibility instructions, and a concise final decision. A justified negative or inconclusive finding is an admissible conclusion.

### E2E-01 — Equity research from raw data to investment decision

- **Track / level:** EQ / Advanced.
- **Question:** Investigate an equity-return hypothesis using the supplied raw market and fundamental data. Build a causal research panel, compare reference signals/models, choose a portfolio policy, simulate executable returns, and decide whether the evidence supports further development.
- **Fixture:** Historical universe and delistings, raw/action data, first-available fundamentals, borrow/financing, execution policy, fixed research budget, and hidden time/universe holdouts.
- **Deliverable:** Complete project artifacts, exposure-adjusted baseline comparison, cost/robustness analysis, and reproducible decision report.
- **Assess:** End-to-end information integrity, sound model selection, correct accounting/execution, incremental after-cost evidence, and conclusions proportional to uncertainty.

### E2E-02 — Fixed-income relative-value research

- **Track / level:** FI / Advanced.
- **Question:** Research a rates or credit relative-value strategy from irregular bond/curve observations. Define reliable targets, separate genuine convergence from stale marks and known exposures, construct feasible hedges, and evaluate the resulting strategy.
- **Fixture:** Cash flows, executable observations and marks with quality flags, curves, issuer histories, financing/collateral, liquidity, scenarios, and protected evaluation periods.
- **Deliverable:** Causal dataset, model/signal, risk-aware allocation, native cash ledger, stress/cost analysis, and proceed/revise/reject recommendation.
- **Assess:** Observation quality, rate/credit decomposition, valuation and financing correctness, tradable evidence, and honest treatment of sparse independent observations.

### E2E-03 — FX macro and carry research

- **Track / level:** FX / Advanced.
- **Question:** Determine whether macro information or conditional carry improves a supplied FX baseline. Design causal features and validation, implement portfolio and execution rules, and reconcile performance in the declared base currency.
- **Fixture:** Spot/forward quotes, first-release macro vintages and expectations, calendars, costs/funding, common risk mandate, research budget, and hidden periods/currencies.
- **Deliverable:** Complete research pipeline, forecast/model comparison, position and settlement records, uncertainty analysis, and final recommendation.
- **Assess:** Publication-time discipline, currency arithmetic, fair baseline/risk comparisons, complete costs, and generalization beyond selected events or currencies.

### E2E-04 — Futures trend/carry portfolio

- **Track / level:** FUT / Advanced.
- **Question:** Develop and test a diversified futures hypothesis using trend, carry, or curve information. Link research features to tradable contracts, enforce a fixed roll policy, size discrete positions, and evaluate costs, cash requirements, and sensitivity to market regimes.
- **Fixture:** Individual contract histories/curves, specifications, margin/settlement, expiry/delivery rules, volume/depth, reference strategies, and protected contract/time holdouts.
- **Deliverable:** Research plan, causal features/models, integer allocation, execution and variation-margin ledger, stress results, and decision report.
- **Assess:** Roll/adjustment integrity, feasible capital/contract sizing, valid statistical evidence, and reproducible after-cost results without hidden delivery assumptions.

### E2E-05 — Option volatility research and hedging

- **Track / level:** OPT / Advanced.
- **Question:** Investigate whether a volatility forecast or relative-value hypothesis improves a supplied option-strategy baseline. Calibrate the required models, specify contract selection and hedging, and evaluate executable performance and nonlinear losses.
- **Fixture:** Synchronized option/underlying observations, discount/forward inputs, exercise/settlement rules, transaction costs, capital constraints, event scenarios, and hidden evaluation paths.
- **Deliverable:** Clean chain/surface, forecasts and strategy code, hedge/fill ledger, repriced stresses, attribution, and evidence-backed recommendation.
- **Assess:** Numerical/model correctness, distinction between forecast skill and risk compensation, realistic hedging/exercise, tail exposure, and validated incremental value.

### E2E-06 — Crypto strategy with funding and venue constraints

- **Track / level:** CRYPTO / Advanced.
- **Question:** Research a directional or hedged crypto strategy using supplied market and funding information. Choose and validate the model, implement the trading policy, and test whether its economics survive costs, segmented collateral, and declared execution disruptions.
- **Fixture:** Causal spot/perpetual books/trades, funding availability, native payoff/margin rules, per-venue balances, API replay faults, research budget, and hidden periods/venues.
- **Deliverable:** Complete research artifacts, executable strategy, per-venue balance/fill ledgers, disruption/stress results, and final decision.
- **Assess:** Information integrity, correct linear/inverse accounting, collateral feasibility, order-state correctness, and robust after-cost evidence rather than assumed future funding.

### E2E-07 — Prediction-market forecasting and trading

- **Track / level:** PRED / Advanced.
- **Question:** Investigate a forecasting or cross-contract strategy over the supplied event family. Establish semantic comparability, build causal forecasts, choose executable orders, and evaluate calibration, returns, and resolution-aware outcomes on unseen events.
- **Fixture:** Anonymized event groups, versioned rules and external evidence, market depth, fee/payout/lifecycle rules, unresolved examples, capital, and protected event/time holdouts.
- **Deliverable:** Canonical event/outcome mapping, research plan, forecast/strategy code, order and settlement ledger, grouped evaluation, and decision report.
- **Assess:** Contract fidelity, proper probability evaluation, executable liquidity, independent event evidence, and correct handling of disputed or incomplete resolution.

### E2E-08 — Cross-asset research and allocation challenge

- **Track / level:** CROSS / Advanced.
- **Question:** Given development datasets from the seven tracks and a fixed research budget, select a limited number of candidate signals, compare them fairly, and produce a feasible combined investment policy. Explain rejected candidates and whether any incremental economic value is established.
- **Fixture:** Typed instruments, source-availability records, per-track reference strategies, costs/financing, common capital/risk mandate, private holdouts, and seeded no-edge/constraint variants.
- **Deliverable:** Research/trial register, reusable code, selected models/signals, common-currency allocation/ledger, per-track and aggregate evidence, and final decision.
- **Assess:** Informed experiment selection, causal cross-asset features, comparable risk/capital, correct mechanics, robustness, and evidence-backed abstention where opportunities are unsupported.

## Results to publish

Publish the following for every completed benchmark edition:

- **Identity and coverage:** Model/agent/harness versions; template and fixture versions; all 72 template outcomes; tracks, venues, regions, horizons, regimes, and missing coverage.
- **Capability:** Nine category scores and the weighted overall score, with rubric-level failures and confidence estimates. Publish partial/invalid runs with explicit status rather than an apparently complete score.
- **Predictive/economic evidence:** Appropriate forecast losses, IC/calibration, net P&L, risk-adjusted and benchmark-relative performance, drawdown/tail risk, costs, turnover/capacity, and uncertainty. Use only metrics meaningful for the task and disclose their definitions.
- **Correctness and reproducibility:** Independent accounting/test results, causal-data checks, immutable artifact hashes, complete experiment counts, and reproducible output instructions.
- **Resources:** Wall time, compute, tokens/tool calls where measurable, data/research expenses, retry counts, and observed versus estimated cost.

Do not merge forecasting quality, numerical correctness, and profitability into one undocumented judgment. Report raw economic metrics alongside the composite so a high capability score cannot be read as proof of a profitable investment strategy.

## Implementation milestones

| Milestone | Required work | Status in this release |
|---|---|---|
| Question bank | Nine agreed weights, 72 task templates, fixture/deliverable/assessment requirements | Documented |
| Task packets | Versioned synthetic or appropriately licensed inputs, native rules, resource limits, and output schemas | Pending |
| Independent grading | Reference implementations, hidden tests/labels, numerical tolerances, open-task rubrics, and error-injection checks | Pending |
| Runner | Frozen model/agent configurations, isolated private evaluation, state resets, artifact collection, and reproducible replay | Pending |
| Pilot calibration | Reference solutions and simple baselines, expert review, difficulty checks, repeated runs, and rubric calibration | Pending |
| Scored release | Complete coverage report, paired comparisons/uncertainty, economic evidence, and retained execution records | Pending |

Implement and audit reference solutions before scoring evaluated agents. An oracle/reference check establishes a fixture/grader's consistency, not model capability or market alpha. Keep runtime/provider integration, dataset qualification, and previous experimental acceptance decisions separate from this document's milestones.

## Methodological references

- [QFBench](https://github.com/QF-Bench/QuantitativeFinance-Bench): Quantitative coding and verifiable numerical tasks.
- [AlphaForgeBench](https://github.com/finbrain-lab-hkustgz/AlphaForgeBench): Executable factor/strategy generation and backtest-based evaluation.
- [AlphaBench](https://github.com/CityU-MLO/AlphaBench): Formulaic alpha generation, evaluation, and search.
- [StockBench](https://github.com/ChenYXxxx/stockbench): Sequential investment decisions with market information.
- [PredictionMarketBench](https://github.com/Oddpool/PredictionMarketBench): Event-driven prediction-market replay and execution evaluation.
- [The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf): Selection bias, backtest overfitting, and non-normality in performance evidence.

These references inform evaluation design. The tasks above are newly authored starter templates; this file does not bundle those projects' datasets or evaluation implementations.
