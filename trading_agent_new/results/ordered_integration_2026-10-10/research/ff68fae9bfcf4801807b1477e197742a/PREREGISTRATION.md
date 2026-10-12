# First research episode: frozen specification

Run: ff68fae9bfcf4801807b1477e197742a
Exact specification hash: 8a512560a312ecdf8eff465bcdc88356bcc588772bef95227d37e6e13d0869ce

A fixed 63-session total-return filter improves excess Sharpe by at least 0.10 versus the same equal-weight ETF allocation, with positive paired uncertainty lower bound, no more than two percentage points worse drawdown, and positive improvement under doubled costs.

Dataset: `fe82dd1197dbcc5744028632f6368f1d1aa6243f8abda370b630588d5d3c487b`; SPY, QQQ, IWM; raw SIP daily observations.
Scored dates: 2016-04-05 through 2026-10-09. The first 63 sessions provide warmup.

Baseline: equal weights capped at 25% per ETF, with the remaining cash. Candidate: the same weight only when the fixed 63-observation compounded total return is strictly positive; otherwise zero. No shorts, parameter search or rebalance buffer. Both use the same data, capital, integer-share planner, preceding-close decisions, next-open simulated fills, participation limits and risk pauses.

Capital: $100,000. Fixed costs: 5 basis points plus $0.005/share with a $1 minimum. Controls: baseline and candidate at normal, zero, and doubled transaction/borrow costs. Zero-yield cash and no borrowing are explicit hypothetical account assumptions.

Rejection: Sharpe gain below 0.10; nonpositive paired one-sided 95% lower bound; fewer than two 21-session blocks; drawdown deterioration above two percentage points; nonpositive improvement under doubled costs; or failed independent accounting/prefix/future-perturbation verification. The bootstrap uses 2,000 draws and the frozen seed. Source qualification is additionally required before paper eligibility.

This retrospective period was already explored. It is not an untouched prospective holdout. The seven-table proxy contains 46 explicitly assumed dividend payment dates, a disputed same-day action, missing/disagreeing dividends, and 176 independently flagged close differences above the fixed 5bp tolerance. The largest difference is 2.79%. Current IDs/fixed membership, close+15-minute availability, historical revisions, commercial rights and financing are not independently qualified. Preserve these gaps with every result and memory record.

Status: specification frozen; no strategy performance computed and no Grok request made. A rejected or data-limited result is a valid output. The dated Grok route is a configurable adapter choice; it does not alter this specification.

Next: fill the private .env.grok file locally, then run `bash research/run_first_episode.sh`. It sequences smoke tests, this exact episode, a distinct memory-transfer proposal, the fixed 240-episode benchmark, and a read-only paper gate. It submits no broker order.
