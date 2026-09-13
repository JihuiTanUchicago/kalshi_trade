# kalshi_trade

Kalshi BTC 15-minute pipeline for ingestion, feature engineering, simulation, live trading controls, and observability.

## Setup

```bash
pip install -r requirements.txt
python -m data_pipeline.init_schema
```

## Architecture

### Active architecture (target-aligned)

```text
[Connectors]
  Kalshi REST/WS, Coinbase
      |
      v
[Ingestion Workers]
  forward_collector
  feature_1m_collector
  coinbase_collector
      |
      v
[MySQL / RDS]
  raw + derived stores
      |
      +--> model_features_1m_builder
      |
      +--> simulated_trading_engine (frozen models)
      |       |
      |       +--> risk_engine (adapter; dummy or settings-backed)
      |       +--> execution_kernel (dummy passthrough)
      |
      +--> live_trading_engine
      |       |
      |       +--> risk_engine (adapter; dummy or settings-backed)
      |       +--> execution_kernel (dummy passthrough)
      |
      +--> sim_portfolio_20s_updater
      +--> live_portfolio_20s_updater
      +--> dashboard_server (CloudFront)
              \--> /api/table for client_api (pandas)
```

### Key separation-of-concerns modules

- `data_pipeline/architecture/risk_engine.py` (live only):
  - `LiveSettingsRiskEngine` (current policy adapter).
  - `DummyRiskEngine` (bypass mode).
- `data_pipeline/architecture/execution_kernel.py` (live only):
  - `DummyExecutionKernel` (pass-through limit order submit; no execution optimization).
- `data_pipeline/live_trading_engine.py`: uses the risk engine + execution kernel abstractions above.
- `data_pipeline/sim_repository.py`: DB access layer for the sim engine (all SQL lives here, not
  inline in trading logic - this is what makes `simulated_trading_engine.py`'s decision logic
  testable against a mocked cursor, see `tests/`).
- `data_pipeline/sim_config.py`: centralized sim thresholds/constants and `SimRiskSettings`.

### Current behavior notes

- Data storage remains UTC.
- Dashboard renders timestamps in New York time (ET) for readability.
- Simulation uses **frozen models** (no per-minute retraining).
- Each sim model runs its own independent $100 paper book (see Risk Management below) so their
  forward performance can be compared fairly - they are not a shared portfolio.

## Model Training & Backtest Methodology

### Current production label

- Base table: `model_features_1m` where `model_eligible=1`.
- Binary next-minute direction label:
  - `y_t = 1` if `mid_{t+1} > mid_t`, else `0`.
- Adjacent row pairs must share the same `market_ticker`.

### Train/Test split for simulation

- A live cutoff is read from `collector_state.sim_live_cutoff_utc`.
- Effective cutoff enforces a minimum in-sample span of 48 hours.
- Models are fit once on in-sample and then held fixed.
- Out-of-sample is cutoff to latest available row.

### Execution assumptions (simulation)

- Entry fill model: conservative quote-ask fill (`quote_ask_conservative`).
- Exit pricing:
  - same ticker: sell against available YES bid ladder only (no midpoint fallback).
  - ticker rotation: stale ticker bid ladder as-of replay timestamp (no lookahead).
  - if bid liquidity is insufficient for full size, consume next bid levels when available.
  - if no quote at all is available at the exit timestamp, fall back to the last quote ever
    recorded for that ticker (rather than pricing the exit at `0.00`, which would misprice a
    contract that actually settled in-the-money).
  - near expiry (`time_to_expiry_sec <= 60`): force close at `0.99` (blocks new entries too).

### PnL

- Trade PnL: `(exit - entry) * qty`.
- `sim_equity_1m` includes realized cumulative PnL and mark-to-market context in `raw_json`.
- `sim_portfolio_20s` tracks cash, position value, equity, and drawdown over time.

### Risk management

Each model's position sizing and continued eligibility is gated by `sim_config.SimRiskSettings`
(persisted in the `sim_settings` table, key `risk_config`):

- `max_position_fraction` (default `0.20`): a new position's notional (`qty * entry price`) is
  capped to this fraction of the model's *current* equity - sizing shrinks automatically as a
  model's own book gets smaller.
- `max_drawdown_pct` (default `0.30`): once a model's drawdown from its own peak realized equity
  (tracked via `sim_equity_1m`, not a separate process) exceeds this fraction, the model is
  **paused** - it stops opening new positions but still manages/closes any position it already
  holds. A paused model stays paused until explicitly cleared via `POST /sim_risk/resume
  {"model_name": ...}`; there is no silent auto-resume. Pause state is visible in `/health`'s
  `sim_summary.models[].paused`/`paused_reason`.
- `min_equity_floor` (default `$10`): hard floor - never open a new position once a model's
  equity has fallen to or below this, regardless of the drawdown math above.

## Models (Current)

Shared feature vector used by production models:

```text
x_t = [
  yes_bid_dollars,
  yes_ask_dollars,
  spread_dollars,
  mid_dollars,
  orderbook_imbalance,
  mid_ret_1m,
  mid_ret_3m,
  trades_last_60s_count,
  trades_last_60s_volume_fp,
  trades_last_60s_vwap_yes,
  quote_change_events_60s,
  time_to_expiry_sec,
  cb_ret_1m,
  cb_ret_3m,
  cb_ret_5m,
  cb_vol_5m,
  moneyness_abs,
  moneyness_pct,
  moneyness_vol_scaled,
  moneyness_x_sqrt_tte,
  moneyness_x_imbalance,
  moneyness_x_qchg
]
```

Current live/sim trade trigger rule:

- Predict `p_yes = P(Y=1 | x_t)`.
- Compute `edge = p_yes - yes_ask_dollars`.
- Trigger BUY YES only if:
  - `p_yes >= signal_threshold`
  - `edge > edge_threshold`

Configured thresholds in code/settings:

- `signal_threshold = 0.55`
- `edge_threshold = 0.01`

### 1) `naive_logistic_baseline` (baseline definition)

- Purpose: anchor for model-comparison discipline.
- Form: plain logistic regression:
  - `p_yes = sigmoid(w^T x_t + b)`
  - baseline feature subset:
    - `yes_bid_dollars`
    - `yes_ask_dollars`
    - `spread_dollars`
    - `mid_dollars`
    - `orderbook_imbalance`
    - `mid_ret_1m`
    - `mid_ret_3m`
    - `trades_last_60s_count`
    - `quote_change_events_60s`
    - `time_to_expiry_sec`
    - `cb_ret_1m`
    - `cb_ret_3m`
    - `moneyness_pct`
- Use: benchmark expected for in-sample/out-of-sample comparison.
- Note: baseline is included in simulation/dashboard comparisons.

### 2) `logistic`

- Regularized logistic regression (scaled features, balanced class weights).
- Prediction form:
  - `p_yes = sigmoid(w^T x_t + b)` using full `x_t` above.
- Trade trigger:
  - simulation: `signal_threshold=0.55`, `edge_threshold=0.01`
  - live: `signal_threshold` and `edge_threshold` loaded from `live_settings` (default same values).
- Frozen in simulation after in-sample fit.

### 3) `random_forest`

- Random Forest classifier with two parameter regimes:
  - small-sample regime.
  - default regime once `min_samples_default_rf` threshold is met.
- Prediction form:
  - `p_yes = RF(x_t)` where `x_t` is the full feature vector above.
- Trade trigger:
  - simulation: `signal_threshold=0.55`, `edge_threshold=0.01`
  - live: `signal_threshold` and `edge_threshold` loaded from `live_settings` (default same values).
- Frozen in simulation after in-sample fit.
- Used for live trading decisions.

## Feature Set Used by Models

Full model feature set from `data_pipeline/modeling_features.py` (`FEATURE_COLS`):

- `yes_bid_dollars`
- `yes_ask_dollars`
- `spread_dollars`
- `mid_dollars`
- `orderbook_imbalance`
- `mid_ret_1m`
- `mid_ret_3m`
- `trades_last_60s_count`
- `trades_last_60s_volume_fp`
- `trades_last_60s_vwap_yes`
- `quote_change_events_60s`
- `time_to_expiry_sec`
- `cb_ret_1m`
- `cb_ret_3m`
- `cb_ret_5m`
- `cb_vol_5m`
- `moneyness_abs`
- `moneyness_pct`
- `moneyness_vol_scaled`
- `moneyness_x_sqrt_tte`
- `moneyness_x_imbalance`
- `moneyness_x_qchg`

Input source columns include `target_btc_price` and `cb_price` for moneyness construction.

Derived/interaction feature formulas:

- `spread_dollars = yes_ask_dollars - yes_bid_dollars`
- `mid_dollars = (yes_ask_dollars + yes_bid_dollars) / 2`
- `orderbook_imbalance = (yes_bid_size_fp - yes_ask_size_fp) / (yes_bid_size_fp + yes_ask_size_fp)` (if denominator > 0, else 0)
- `mid_ret_1m = (mid_t / mid_{t-1m}) - 1`
- `mid_ret_3m = (mid_t / mid_{t-3m}) - 1`
- `cb_ret_1m = (cb_t / cb_{t-1m}) - 1`
- `cb_ret_3m = (cb_t / cb_{t-3m}) - 1`
- `cb_ret_5m = (cb_t / cb_{t-5m}) - 1`
- `moneyness_abs = cb_price - target_btc_price`
- `moneyness_pct = (cb_price - target_btc_price) / target_btc_price`
- `moneyness_vol_scaled = moneyness_abs / max(cb_price * max(cb_vol_5m, 1e-6), 1e-6)`
- `moneyness_x_sqrt_tte = moneyness_pct * sqrt(max(time_to_expiry_sec, 1.0))`
- `moneyness_x_imbalance = moneyness_pct * orderbook_imbalance`
- `moneyness_x_qchg = moneyness_pct * quote_change_events_60s`

## Core Tables

- `forward_quotes`: 20-second top-of-book snapshots for active contract context.
- `coinbase_ticks`: 20-second BTC spot context.
- `trade_quote_features_1m`: minute trade intensity and quote-change aggregates.
- `model_features_1m`: canonical minute feature table for ML.
- `sim_model_predictions_1m`: model probabilities/signals per minute.
- `sim_trades`, `sim_positions`, `sim_equity_1m`, `sim_portfolio_20s`: simulation ledger and equity state.
- `sim_settings`: risk-config JSON blob (see Risk Management above).
- `sim_model_state`: per-model pause flag/reason set by the drawdown risk gate.
- `live_orders`, `live_positions`, `live_trades`, `live_portfolio_20s`: live execution and portfolio tracking.
- `collector_state`: runtime checkpoints/config keys (`sim_live_cutoff_utc`, last snapshot states, etc.).

## Runtime Processes

Typical workers on EC2:

- `python -m data_pipeline.forward_collector`
- `python -m data_pipeline.feature_1m_collector`
- `python -m data_pipeline.coinbase_collector`
- `python -m data_pipeline.model_features_1m_builder`
- `python -m data_pipeline.simulated_trading_engine`
- `python -m data_pipeline.sim_portfolio_20s_updater`
- `python -m data_pipeline.live_trading_engine`
- `python -m data_pipeline.live_portfolio_20s_updater`
- `python -m data_pipeline.dashboard_server`

Helper script:

```bash
bash scripts/start_aws_collectors.sh
```

## Client API (Pandas)

`client_api` exposes full-history DataFrame fetch helpers (internal pagination hidden).

```python
from client_api import KalshiDataClient

client = KalshiDataClient(base_url="https://dehiuraiut9ro.cloudfront.net")
df_features = client.model_features()
df_preds = client.sim_predictions()
```

Notebook examples: `client_api/example.ipynb`.

## Security / Ops Notes

- Keep API keys and private key files out of git.
- Use `.env.aws` / environment variables for DB + API credentials.
- Live tab has an additional password gate.
- `dashboard_server` runs under systemd (`kalshi-dashboard.service`, `Restart=always`) so a crash
  or wedged process recovers automatically. The other processes run via `nohup`/`setsid`; all of
  them re-raise on a DB error so the outer retry loop reacquires a fresh connection rather than
  silently looping against a dead one (see PLAN.md for the incident this fixed).
