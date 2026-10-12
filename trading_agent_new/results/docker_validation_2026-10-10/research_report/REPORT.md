# Quantitative research report

Run: 67e97b7dbedc417da5c383936ca404e9
Workflow: finished

Validate the actual isolated Python strategy interface, six controlled trials, causal challenges and evidence-backed learning on synthetic inputs.

## Frozen specification

Hypothesis: Engineering test: a causal capped daily trend rule versus equal weight, with frozen transaction/borrow controls.
Baseline: equal_weight
Scored dates: 2026-06-29 to 2026-10-08

## Controlled results

Data quality: **synthetic**; qualified: False.
Historical evidence is exploratory. Synthetic fixtures measure engineering behavior.

| Trial | Excess Sharpe | Max drawdown | Annual notional turnover | Filled orders |
|---|---:|---:|---:|---:|
| baseline_0 | -1.3272 | 5.99% | 4.23 | 164 |
| baseline_1 | -1.4093 | 6.00% | 4.26 | 167 |
| baseline_2 | -1.4807 | 6.01% | 4.20 | 154 |
| candidate_0 | 8.2219 | 0.62% | 12.35 | 128 |
| candidate_1 | 7.9221 | 0.63% | 12.34 | 124 |
| candidate_2 | 7.6103 | 0.65% | 12.34 | 123 |

Paired Sharpe gain: +9.3313; one-sided 95% lower bound: +5.6298.
Gain with doubled transaction/borrow costs: +9.0910.
Gain in matched cost-free controls: +9.5491.

## Independent challenges

Ledger passed: True; prefix invariant: True; future perturbation invariant: True.

## Decision

**revise_data_qualification**

Paper eligible: False; live-capital eligible: false.

- double_transaction_and_borrow_costs: pass
- drawdown: pass
- minimum_sharpe_gain: pass
- positive_uncertainty_lower_bound: pass
- sufficient_blocks: pass
- verified_accounting_causality: pass

## Evidence

Artifact directory: /Users/jonathanzhang/Desktop/Polygon/results/docker_validation_2026-10-10/research_state/artifacts

- spec: 310b9f25e5b6b02afb5a8e84aa1209e4c5caf7f064299531aa982e7852ed2769
- strategy: 42b4c6c882b9dc78fea6e304abc6603155ec62c4267e8e7d06ba2fa7b8b1ba4a
- result: 68214fe4a030b631fe99168a84c4c2fd5e3fd042be067e13c4dec939df83e1f7
- challenge: 0d3816bcf8dded863dfca61b5c047058e64d39703a7f188787338b12c85bfd88
- decision: f276e8b2cfb3d90b3aeab17ba0d6da60cd385ec24e8bc0ca9c49d1f0df2b0f95
