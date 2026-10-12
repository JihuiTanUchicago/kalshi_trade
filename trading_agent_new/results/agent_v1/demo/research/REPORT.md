# Quantitative research report

Run: 593ff84e8daf4c28bfdd3396dac8686b
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
| baseline_0 | -1.3272 | 5.99% | 4.23 | 164 |
| baseline_1 | -1.4093 | 6.00% | 4.26 | 167 |
| baseline_2 | -1.4807 | 6.01% | 4.20 | 154 |
| candidate_0 | -1.2831 | 6.04% | 3.53 | 8 |
| candidate_1 | -1.3059 | 6.04% | 3.54 | 8 |
| candidate_2 | -1.3342 | 6.05% | 3.52 | 8 |

Paired Sharpe gain: +0.1033; one-sided 95% lower bound: +0.0596.
Gain with doubled transaction/borrow costs: +0.1465.
Gain in matched cost-free controls: +0.0442.

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

- spec: c64edcae85114dbd786c124c97c5c055ee7001451dc308c6401310c4ce2b9c3a
- strategy: fd65b40e18100a722ee77275e4fd56eb7fce4ea653a7277c0f51011a373479fb
- result: ca7b034d8f9f022f4bbf7aad92620d537c6be93eb0296bda0f9928c05d479477
- challenge: 5761afa0c092408e19c231c2aebe9dbff70b41d7b75bf2ec0cc3914a39dd8688
- decision: d79f361855797eb53bd9eb7f023ea91e85b0c759c2a75d58904ed65618b09d89
