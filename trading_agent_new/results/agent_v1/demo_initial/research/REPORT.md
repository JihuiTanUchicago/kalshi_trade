# Quantitative research report

Run: 06e5e6e3f3254de5b624ca21858fab3e
Workflow: finished

Compare notional turnover and order counts; challenge cost attribution and retain rejected findings.

## Frozen specification

Hypothesis: A fixed two-percentage-point buffer reduces notional turnover without violating preregistered performance gates.
Baseline: equal_weight
Scored dates: 2026-06-29 to 2026-10-08

## Controlled results

Data quality: **synthetic**; qualified: False.
Historical evidence is exploratory. Synthetic fixtures measure engineering behavior.

| Trial | Excess Sharpe | Max drawdown | Annual notional turnover | Filled orders |
|---|---:|---:|---:|---:|
| baseline_0 | -1.3302 | 5.99% | 4.22 | 161 |
| baseline_1 | -1.4140 | 6.00% | 4.26 | 167 |
| baseline_2 | -1.4893 | 6.03% | 4.23 | 158 |
| candidate_0 | -1.2892 | 6.04% | 3.52 | 9 |
| candidate_1 | -1.3106 | 6.04% | 3.54 | 8 |
| candidate_2 | -1.3388 | 6.05% | 3.52 | 8 |

Paired Sharpe gain: +0.1034; one-sided 95% lower bound: +0.0592.
Gain with doubled transaction/borrow costs: +0.1504.
Gain in matched cost-free controls: +0.0409.

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

Artifact directory: /Users/jonathanzhang/Desktop/Polygon/results/agent_v1/demo/state/artifacts

- spec: db3040aeab7e6f091baf0408826a1b10e7a10d70aba65096d4adfd1859407eed
- strategy: 537bbb7a009d35977c1eca2704a3646b34bc550ee798f0475ca70b560b6436bc
- result: c0cbded0ade8550b7930cb154112c9a552cc33805325ee1b96be1dcfbd7ccf57
- challenge: c59c5dcd52d2053a8337e59801e8c31ffcf97fb48a5d580e66f7a93d5be476a8
- decision: 7eb13a3599cb5beadbdc81e99b4dc49fc712a07e29d5c9b464c33959bfc5ba35
