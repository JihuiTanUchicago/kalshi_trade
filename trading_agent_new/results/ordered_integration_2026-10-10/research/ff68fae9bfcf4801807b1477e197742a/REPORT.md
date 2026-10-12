# Quantitative research report

Run: ff68fae9bfcf4801807b1477e197742a
Workflow: finished

Test the preregistered 63-session total-return trend filter against equal-weight allocation. Keep matched costs, capital, execution timing and risk controls; challenge uncertainty and exposures, preserve source qualification limits, and retain rejected findings in verified memory.

## Frozen specification

Hypothesis: A fixed 63-session total-return filter improves excess Sharpe by at least 0.10 versus the same equal-weight ETF allocation, with positive paired uncertainty lower bound, no more than two percentage points worse drawdown, and positive improvement under doubled costs.
Baseline: equal_weight
Scored dates: 2016-04-05 to 2026-10-09

## Controlled results

Data quality: **proxy**; qualified: False.
Historical evidence is exploratory. Synthetic fixtures measure engineering behavior.

| Trial | Excess Sharpe | Max drawdown | Annual notional turnover | Filled orders |
|---|---:|---:|---:|---:|
| baseline_0 | 0.8538 | 26.57% | 0.60 | 3218 |
| baseline_1 | 0.8394 | 26.58% | 0.58 | 3064 |
| baseline_2 | 0.8258 | 26.61% | 0.57 | 2936 |
| candidate_0 | 0.8088 | 19.96% | 8.93 | 2229 |
| candidate_1 | 0.7415 | 20.54% | 8.92 | 2112 |
| candidate_2 | 0.6746 | 21.11% | 8.95 | 2096 |

Paired Sharpe gain: -0.0979; one-sided 95% lower bound: -0.4409.
Gain with doubled transaction/borrow costs: -0.1511.
Gain in matched cost-free controls: -0.0450.

## Data assumptions and unresolved source checks

These observations do not establish source qualification or profitable live trading.
The machine-readable report retains every source disagreement and assumption.

```json
{
  "constraints": {
    "allow_short": false,
    "exploratory_only": true,
    "historical_availability": "assumed; not evidence of original publication",
    "maximum_scored_end": "2026-10-09",
    "paper_eligible": false,
    "pay_date_policy": "provider date, otherwise ex-date + 30 calendar days",
    "price_precedence": "raw Alpaca SIP; independent prices never replace bars"
  },
  "qualification_gaps": {
    "action_amount_disagreements": [
      {
        "independent": 0.378,
        "key": [
          "QQQ",
          "2018-06-18",
          "dividend"
        ],
        "primary": 0.37638
      },
      {
        "independent": 1.633,
        "key": [
          "SPY",
          "2021-12-17",
          "dividend"
        ],
        "primary": 1.636431
      }
    ],
    "ambiguous_same_day_primary_actions": [
      {
        "additional": {
          "cusip": "46090E103",
          "ex_date": "2022-09-19",
          "foreign": false,
          "id": "1966d92d-c3ae-4da1-8daa-483789298533",
          "payable_date": "2022-10-31",
          "process_date": "2022-10-31",
          "rate": 0.51856,
          "record_date": "2022-09-20",
          "special": false,
          "symbol": "QQQ"
        },
        "first": {
          "basis": "Alpaca current-vintage",
          "pay_date": "2022-09-23",
          "provider_id": "d0409c14-2b32-4cdb-9d5d-57a8a9a0818f",
          "source_file": "actions_000.json",
          "value": 0.51856
        },
        "key": [
          "QQQ",
          "2022-09-19",
          "dividend"
        ],
        "proxy_policy": "one independently corroborated amount; payment date assumed"
      }
    ],
    "assumed_dividend_pay_dates": 46,
    "commercial_rights_reviewed": false,
    "current_security_master_is_historical": false,
    "independent_price_checks": {
      "IWM": {
        "matched_closes": 2708,
        "maximum_relative_close_difference": 0.017912967997516575,
        "present": true,
        "within_fixed_5bp_tolerance": false
      },
      "QQQ": {
        "matched_closes": 2708,
        "maximum_relative_close_difference": 0.0009302277511115007,
        "present": true,
        "within_fixed_5bp_tolerance": false
      },
      "SPY": {
        "matched_closes": 2708,
        "maximum_relative_close_difference": 0.027934490634886563,
        "present": true,
        "within_fixed_5bp_tolerance": false
      }
    },
    "missing_independent_actions": [
      [
        "QQQ",
        "2020-09-21",
        "dividend"
      ]
    ],
    "missing_primary_actions": [
      [
        "SPY",
        "2016-03-18",
        "dividend"
      ],
      [
        "SPY",
        "2018-06-15",
        "dividend"
      ]
    ],
    "original_availability_proven": false,
    "survivorship_free_universe": false
  }
}
```

## Independent challenges

Ledger passed: True; prefix invariant: True; future perturbation invariant: True.

## Decision

**reject**

Paper eligible: False; live-capital eligible: false.

- double_transaction_and_borrow_costs: fail
- drawdown: pass
- minimum_sharpe_gain: fail
- positive_uncertainty_lower_bound: fail
- sufficient_blocks: pass
- verified_accounting_causality: pass

## Evidence

Artifact directory: /Users/jonathanzhang/Desktop/Polygon/.quant-agent/artifacts

- spec: 8a512560a312ecdf8eff465bcdc88356bcc588772bef95227d37e6e13d0869ce
- strategy: 9f540c45ae58d1ff490a6fa81b533444702d6b25d81a0c61284e72003446ffaa
- result: 79c012dc9b8047c505d5202287a7888752d79fcd4c538105abd36171283d0050
- challenge: 0abe828db27a5f39958efd6ed7d61737f79ba03449bb09e4c159df0b968b0cf3
- decision: 87bd4542c0ce8211e24f2aaa6e77fafea7f76d5081d24ecf0ece1bac895ff449
