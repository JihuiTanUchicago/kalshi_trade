# BTC 15-Minute YES-Only Kalshi Trading Masterplan (Revised)

## 1. Objective

Build a production-minded micro-strategy for Kalshi BTC 15-minute contracts that can:

- generate calibrated `P(YES)` forecasts,
- convert forecasts into executable YES-side decisions,
- survive real frictions (fees, spread, liquidity, latency),
- protect a small bankroll with strict risk and operational controls.

Success is not classification accuracy. Success is **out-of-sample net expected value and controlled drawdown**.

---

## 2. Scope and Constraints (MVP)

- Market family: **Kalshi BTC 15-minute** contracts.
- Side: **YES only** (buy YES, sell YES).
- Capital: initial `$100`.
- Hard drawdown stop: `$20`.
- Daily stop: `$10`.
- One active contract bucket for decisioning at a time.

Design principle: minimal abstractions, explicit state, deterministic behavior at 15-minute boundaries.

---

## 3. API Capability Reality Check (Live-Probe Verified on 2026-03-06)

### 3.1 What is available and usable now

Verified with live endpoint calls:

- Exchange status endpoint works (`/trade-api/v2/exchange/status`).
- Historical market discovery works (`/trade-api/v2/historical/markets`).
- Public market trades for historical tickers work (`/trade-api/v2/markets/trades?ticker=...`).
- Historical candle-style market summaries work via batch endpoint:
  - `/trade-api/v2/markets/candlesticks`
  - requires `market_tickers`, `start_ts`, `end_ts`, `period_interval`.

### 3.2 What is not available as a historical backfill API

No documented/working historical full orderbook replay endpoint was found in probing:

- `/trade-api/v2/historical/orderbook` -> 404
- related guessed historical orderbook paths -> 404

### 3.3 Rate-limit observation

- Pagination-heavy crawling hit `429 too_many_requests` during broad scans.
- Data collection must include backoff and paced pagination.

### 3.4 Decision

- We can maximize historical depth with Kalshi historical markets + trades + candlesticks.
- We still need a **forward orderbook collector** if we want L2 microstructure features beyond candle/trade aggregates.

---

## 4. Data Strategy (Max Historical Depth, Then Forward Fill)

## 4.1 Historical Backfill (Priority)

Primary goal: collect as much historical BTC-15m data as possible before live trading.

Backfill tables:

- `markets_history` from `/historical/markets`
- `trades_history` from `/markets/trades` per market ticker
- `candles_history` from `/markets/candlesticks` per ticker/time range
- `coinbase_candles` from Coinbase public candles (60/300/900 sec)

## 4.2 Conditional Forward Collector

Run forward collector for:

- full orderbook deltas/snapshots (required for L2 features),
- low-latency consistency checks,
- fill-to-book slippage analytics.

If strategy v1 uses only candles + trades + top-of-book snapshots, forward collector can be phase-gated.

## 4.3 Data Contracts (Must-Have)

For every row used in training or backtest:

- `event_time_utc`
- `event_time_et`
- `decision_time_utc`
- `feature_cutoff_time_utc`
- `source_lag_ms`
- `market_ticker`
- `bucket_id`

This prevents accidental lookahead leakage.

---

## 5. Market-Time and Contract Routing

Use `America/New_York` as canonical business clock for:

- bucket routing,
- market handoff,
- risk/day boundaries,
- operator dashboards.

### 5.1 Boundary protocol (`:00/:15/:30/:45`)

At boundary:

1. stop new entries in old contract,
2. cancel stale resting buys,
3. switch old contract to closing-only,
4. attempt YES liquidation (target `0.99`, with fallback ladder),
5. switch signal routing to new contract,
6. do not block engine on old settlement completion.

### 5.2 Transition lock

- Lock window starts a few seconds pre-boundary.
- Entries re-enable only after:
  - new ticker resolved,
  - new market data heartbeat confirmed,
  - risk engine green.

---

## 6. Core State Model

Maintain explicit state separation:

- `cash_available`
- `cash_pending_settlement`
- `inventory_by_ticker`
- `open_orders_by_ticker`
- `equity_estimate`
- `realized_pnl_today`
- `realized_pnl_total`

Never treat unsettled economic value as immediately tradable cash.

---

## 7. Feature, Label, and Leakage-Safe Dataset Design

## 7.1 Labels

Target at decision time `t`:

- `y_t = 1` if active contract settles YES, else `0`.

## 7.2 MVP features

Kalshi:

- yes bid/ask/spread,
- top sizes,
- mid changes over short windows,
- trade intensity and price change,
- time-to-expiry.

Coinbase:

- returns (1m/3m/5m/15m),
- short volatility and range,
- moving average gaps.

## 7.3 Leakage controls (mandatory)

- as-of joins only (no future bars, no post-decision trades),
- fixed inference-to-order latency assumption in backtest,
- stale feed guard: if data age > threshold, no signal.

---

## 8. Model Stack and Promotion Policy

Model ladder:

- `Model 0`: market baseline (`p_market` from Kalshi price).
- `Model 1`: logistic regression (strong simple baseline).
- `Model 2`: random forest + probability calibration.

Promotion rule:

- promote only if out-of-sample utility and calibration both improve against incumbent.

Retraining policy:

- periodic rebuilds are allowed,
- but gated by `min_new_rows` and performance decay triggers,
- not clock-only retraining.

---

## 9. Signal Policy and Dynamic Position Sizing (MVP)

## 9.1 Entry gate

Enter YES only when all pass:

1. correct active contract,
2. no transition lock,
3. model probability available and calibrated,
4. spread/liquidity filters pass,
5. risk and kill-switch state = GREEN,
6. **net edge** > threshold.

Net edge approximation:

- `edge_net = p_hat - ask_price - fee_est - slippage_est`.

## 9.2 Exit policy

Exit YES on any of:

- edge reversal,
- boundary liquidation,
- risk-forced flatten,
- stale-data or ops kill-switch activation.

## 9.3 Dynamic sizing formula (MVP)

Use capped fractional sizing by net edge:

- `risk_budget = min(max_trade_cost, risk_fraction * equity_estimate)`
- `size_dollars = clip(risk_budget * (edge_net / edge_ref), min_ticket, max_trade_cost)`
- enforce integer contract conversion + cash/risk constraints.

Default conservative config:

- `risk_fraction = 0.10`
- `max_trade_cost = $10`
- `min_ticket = $1`
- `edge_ref = 0.03`

This keeps sizing adaptive while bounded for bankroll survival.

---

## 10. Execution Simulation and Backtest Realism

Backtest engine must model:

- partial fills,
- queue/priority proxy,
- cancel/replace latency,
- missed fills,
- liquidation failure probability near boundary,
- explicit fees + spread crossing + slippage buffer.

No optimistic assumption that target `0.99` liquidation always fills.

---

## 11. Risk Management and Kill Switches

## 11.1 Financial constraints

- `max_total_drawdown = $20`
- `max_daily_loss = $10`
- `max_trade_cost <= $10`
- no new entry if available cash below threshold

## 11.2 Operational kill switches

Immediate halt on:

- stale market data heartbeat,
- repeated order rejects above threshold,
- auth/signing failures,
- repeated reconciliation mismatch,
- time sync drift beyond tolerance.

## 11.3 Recovery mode

When halted:

- flatten if possible,
- cancel outstanding orders,
- switch strategy to SAFE mode,
- require manual resume.

---

## 12. Order Lifecycle Reliability

Use explicit order state machine:

- `INTENT_CREATED`
- `SUBMITTED`
- `ACKED`
- `PARTIALLY_FILLED`
- `FILLED`
- `CANCEL_REQUESTED`
- `CANCELED`
- `REJECTED`
- `UNKNOWN_RECONCILE_REQUIRED`

Rules:

- idempotent `client_order_id` for retries,
- exponential backoff on transient errors,
- periodic reconciliation with portfolio endpoints.

---

## 13. Evaluation Framework

## 13.1 Forecast quality

- Brier score
- log loss
- calibration by bucket/time-to-expiry

## 13.2 Trading quality (primary)

- net PnL after friction
- drawdown profile
- EV by edge bucket
- forced-liquidation hit rate
- fill rate and slippage
- transition error count

## 13.3 Stability and drift

- rolling degradation vs baseline
- feature missingness/staleness
- model promotion/reversion history

---

## 14. Dashboards and Logging

Required dashboards:

- strategy/risk health,
- execution quality,
- model calibration and edge realization,
- boundary handoff correctness.

Structured logs must include:

- ET + UTC timestamps,
- active ticker + bucket,
- model version,
- prediction + market price + net edge,
- order/fill IDs,
- reason code,
- risk state.

---

## 15. Revised Phased Implementation Plan (with Acceptance Criteria)

## Phase 1: Historical data pipeline

Tasks:

- build historical market crawler (paced pagination + resume cursor),
- backfill BTC 15m tickers,
- backfill trades per ticker,
- backfill candlesticks with time windows,
- merge with Coinbase candles,
- produce leakage-safe training table.

Acceptance criteria:

- reproducible backfill job,
- deterministic row counts/checksums,
- explicit leakage tests pass.

## Phase 2: Baseline modeling and realistic backtest

Tasks:

- implement market baseline + logistic + RF,
- calibrate probabilities,
- run walk-forward,
- include realistic fill/friction simulation.

Acceptance criteria:

- baseline comparison report,
- calibration plots,
- net EV and drawdown statistics out-of-sample.

## Phase 3: Live router + risk core

Tasks:

- ET router,
- transition lock,
- boundary liquidation policy,
- kill switches and SAFE mode.

Acceptance criteria:

- deterministic boundary tests,
- stale-feed and reject-burst simulations,
- reconciliation invariants proven.

## Phase 4: Paper trading

Tasks:

- live data ingestion,
- real-time inference,
- hypothetical order simulation,
- full observability.

Acceptance criteria:

- 1-2 weeks stable run,
- no unresolved reconciliation errors,
- transition error rate near zero.

## Phase 5: Micro live trading

Tasks:

- enable authenticated execution,
- start with conservative dynamic sizing,
- strict risk gating,
- post-trade journaling.

Acceptance criteria:

- hard stops never breached,
- ops incidents and recovery documented,
- edge-vs-realization analysis produced.

## Phase 6: Hardening and iteration

Tasks:

- tune thresholds/sizing,
- simplify features when stability improves,
- improve liquidation and execution quality.

Acceptance criteria:

- stable month-long paper/live behavior,
- controlled drawdown,
- documented model governance loop.

---

## 16. Final MVP Doctrine

MVP is successful only if it is:

- leakage-safe,
- settlement-aware,
- boundary-correct,
- risk-bounded,
- execution-realistic,
- and empirically better than naive market baseline after friction.

---

## 17. References

- Kalshi API docs: [https://docs.kalshi.com/](https://docs.kalshi.com/)
- Kalshi historical endpoint migration notes (March 2026 context): [https://docs.kalshi.com/getting_started/quick_start_historical_data](https://docs.kalshi.com/getting_started/quick_start_historical_data)
- Coinbase Exchange API docs: [https://docs.cdp.coinbase.com/exchange/](https://docs.cdp.coinbase.com/exchange/)
- Kalshi fee schedule: [https://kalshi.com/docs/kalshi-fee-schedule.pdf](https://kalshi.com/docs/kalshi-fee-schedule.pdf)

