# kalshi_trade

Kalshi BTC 15-minute pipeline for data collection, feature engineering, simulation, model lab, and live trading controls.

## Setup

```bash
pip install -r requirements.txt
python -m data_pipeline.init_schema
```

## Data Dictionary (Complete)

All timestamps are UTC. Prices are in dollars unless noted. `raw_json` columns preserve source/debug payloads.

### 1) `markets` (Kalshi market metadata)
- `ticker`: unique market identifier.
- `event_ticker`: parent event identifier.
- `series_ticker`: market series identifier.
- `title`, `subtitle`: market text metadata.
- `status`: market status from Kalshi.
- `open_time`, `close_time`, `expiration_time`: lifecycle timestamps.
- `last_seen_utc`: collector last-seen timestamp.
- `raw_json`: full source payload.

### 2) `market_trades` (raw trade tape)
- `trade_id`: unique trade id.
- `ticker`: market ticker.
- `created_time`: trade timestamp.
- `yes_price_dollars`, `no_price_dollars`: executed prices.
- `count_fp`: trade size/contracts.
- `taker_side`: aggressor side.
- `collected_at_utc`: ingestion timestamp.
- `raw_json`: full source payload.

### 3) `market_candles` (raw candle bars)
- `ticker`: market ticker.
- `end_period_ts`: candle end epoch.
- `period_interval_minutes`: candle interval length.
- `yes_bid_open`, `yes_bid_close`, `yes_ask_open`, `yes_ask_close`: top-of-book bar values.
- `price_open`, `price_close`: canonical price bar values from source.
- `volume_fp`, `open_interest_fp`: market activity fields.
- `collected_at_utc`: ingestion timestamp.
- `raw_json`: full source payload.

### 4) `forward_quotes` (20-second forward snapshot stream)
- `id`: auto id.
- `snapshot_time_utc`: quote snapshot timestamp.
- `market_ticker`, `event_ticker`: identifiers.
- `yes_bid_dollars`, `yes_ask_dollars`: top-of-book YES prices.
- `yes_bid_size_fp`, `yes_ask_size_fp`: top-of-book sizes.
- `volume_fp`, `open_interest_fp`: market state fields.
- `status`: collector state (`active`, fallback/N/A reason codes, etc).
- `raw_json`: source/debug payload.

### 5) `collector_state` (collector checkpoints)
- `state_key`: named state record (collector watermark, run id, cutoff, champion, etc).
- `state_value`: JSON/text payload for the state.
- `updated_at_utc`: last update timestamp.

### 6) `coinbase_ticks` (Coinbase context feed)
- `id`: auto id.
- `snapshot_time_utc`: tick snapshot time.
- `product_id`: product symbol (e.g., BTC-USD).
- `price`, `bid`, `ask`: Coinbase quotes.
- `volume_24h`: 24h rolling volume from source.
- `status`: collector status (`ok`/error).
- `raw_json`: source/debug payload.

### 7) `trade_quote_features_1m` (derived minute aggregates)
- `snapshot_minute_utc`: minute bucket key.
- `market_ticker`, `event_ticker`: active market/event chosen for minute.
- `trades_last_60s_count`: count of Kalshi trades with `created_time` in `(t-60s, t]`.
- `trades_last_60s_volume_fp`: sum of `count_fp` over `(t-60s, t]`.
- `trades_last_60s_vwap_yes`: `sum(yes_price_dollars * count_fp) / sum(count_fp)` over `(t-60s, t]`.
- `quote_change_events_60s`: number of bid/ask updates in last 60s (prefer websocket table; fallback from 20s snapshots).
- `source_status`: aggregation outcome (`ok`, `no_open_market`, `no_active_market`, `error`, etc).
- `raw_json`: debug payload for aggregation inputs/results.

### 8) `ws_quote_change_1m` (derived websocket quote-change counts)
- `snapshot_minute_utc`: minute bucket.
- `market_ticker`, `event_ticker`: identifiers.
- `quote_change_events`: count of quote-change events in that minute.
- `last_yes_bid_dollars`, `last_yes_ask_dollars`: last seen top-of-book for bucket.
- `updated_at_utc`: updater timestamp.

### 9) `model_features_1m` (derived canonical ML feature table)
- `snapshot_minute_utc`, `market_ticker`, `event_ticker`: row key/context.
- `yes_bid_dollars`, `yes_ask_dollars`: as-of forward quote at minute mark.
- `spread_dollars`: `yes_ask_dollars - yes_bid_dollars`.
- `mid_dollars`: `(yes_ask_dollars + yes_bid_dollars) / 2`.
- `yes_bid_size_fp`, `yes_ask_size_fp`: as-of top-of-book sizes.
- `orderbook_imbalance`: `(bid_size - ask_size) / (bid_size + ask_size)` if denominator > 0.
- `mid_ret_1m`: `(mid_t / mid_{t-1m}) - 1`.
- `mid_ret_3m`: `(mid_t / mid_{t-3m}) - 1`.
- `trades_last_60s_count`, `trades_last_60s_volume_fp`, `trades_last_60s_vwap_yes`, `quote_change_events_60s`: copied from `trade_quote_features_1m`.
- `time_to_expiry_sec`: `max(0, close_time - snapshot_minute_utc)` in seconds.
- `cb_price`: as-of Coinbase price.
- `cb_ret_1m`, `cb_ret_3m`, `cb_ret_5m`: `(cb_t / cb_{t-k}) - 1`.
- `cb_vol_5m`: sample std-dev of minute Coinbase returns across recent 5-minute window.
- `kalshi_data_age_sec`: seconds between feature minute and as-of forward quote timestamp.
- `coinbase_data_age_sec`: seconds between feature minute and as-of Coinbase tick timestamp.
- `model_eligible`: binary eligibility flag after guards.
- `guard_status`: `ok` / `warn` / `error`.
- `guard_reasons_json`: explicit guard failures/warnings (missing feed, stale data, negative spread, out-of-range prices, etc).
- `raw_json`: trace payload with as-of inputs and guard context.

### 10) `sim_model_predictions_1m` (simulation model outputs)
- `snapshot_minute_utc`, `model_name`: key.
- `market_ticker`: ticker predicted at that minute.
- `prob_yes`: predicted YES probability.
- `signal_yes`: binary trade signal.
- `edge_est`: estimated edge used by strategy logic.
- `train_rows`, `test_rows`: training/test sample counts used for that model update.
- `brier`, `logloss`: prediction-quality diagnostics.
- `rf_regime`: RF training regime label if applicable.
- `raw_json`: model run payload.

### 11) `sim_positions` (simulation open positions)
- `model_name`: model id (one open position row per model).
- `opened_at_utc`, `market_ticker`: open timestamp and ticker.
- `qty_contracts`: position size.
- `entry_price_dollars`: fill entry price.
- `trade_id`: linking id to trade table.
- `raw_json`: execution context.

### 12) `sim_trades` (simulation trade ledger)
- `id`: trade row id.
- `model_name`, `market_ticker`: model and ticker.
- `opened_at_utc`, `closed_at_utc`: lifecycle timestamps.
- `qty_contracts`, `entry_price_dollars`, `exit_price_dollars`: execution fields.
- `pnl_dollars`: realized pnl for closed trades.
- `status`: `open`/`closed`.
- `raw_json`: execution metadata.

### 13) `sim_equity_1m` (simulation minute equity)
- `snapshot_minute_utc`, `model_name`: key.
- `realized_pnl_dollars`: realized pnl at minute.
- `cumulative_pnl_dollars`: cumulative realized pnl.
- `closed_trades_count`: number of closed trades.
- `win_rate`: win ratio on closed trades.
- `raw_json`: debug payload.

### 14) `sim_portfolio_20s` (simulation 20s portfolio marks)
- `snapshot_time_utc`, `model_name`: key.
- `cash_dollars`, `position_value_dollars`: cash and marked position value.
- `realized_pnl_dollars`, `unrealized_pnl_dollars`: pnl decomposition.
- `equity_dollars`: cash + position value.
- `peak_equity_dollars`: running peak equity.
- `drawdown_dollars`: `equity - peak_equity`.
- `raw_json`: mark context.

### 15) `sim_model_lab_runs` (model-lab run registry)
- `run_id`: run identifier.
- `run_time_utc`: run timestamp.
- `cutoff_utc`: segmentation cutoff used by run.
- `sample_rows`: number of samples used.
- `notes_json`: run metadata (variant count, etc).

### 16) `sim_model_lab_results` (variant evaluation outputs)
- `id`, `run_id`, `variant_id`, `model_family`, `horizon_min`: variant identity.
- `pred_threshold`, `edge_threshold`: chosen thresholds.
- `segment`: `in_sample`, `out_of_sample`, `live_forward`.
- `n_samples`, `n_trades`, `trade_rate`: sample/trade counts and trade rate.
- `win_rate`, `total_pnl`, `avg_pnl`, `pnl_per_trade`: pnl stats.
- `brier`, `logloss`: predictive quality metrics.
- `max_drawdown`, `sharpe_like`: risk-adjusted diagnostics.
- `meta_json`: variant params and metadata.

### 17) `live_settings` (live runtime configuration)
- `settings_key`: config namespace.
- `settings_json`: strategy/risk settings.
- `updated_at_utc`: last config update.

### 18) `live_orders` (live order log)
- `id`, `created_at_utc`: order id/time.
- `market_ticker`, `action`, `side`: order intent/context.
- `qty_contracts`, `limit_price_dollars`: order quantity and price.
- `status`: order status.
- `kalshi_order_id`, `client_order_id`: external/internal ids.
- `raw_json`: order payload.

### 19) `live_positions` (live open positions)
- `market_ticker`: primary key.
- `opened_at_utc`, `qty_contracts`, `entry_price_dollars`: live position fields.
- `model_name`: model responsible for position.
- `raw_json`: execution context.

### 20) `live_trades` (live realized trade ledger)
- `id`: trade id.
- `opened_at_utc`, `closed_at_utc`: lifecycle timestamps.
- `market_ticker`, `model_name`: context.
- `qty_contracts`, `entry_price_dollars`, `exit_price_dollars`: execution fields.
- `pnl_dollars`: realized pnl.
- `status`: `open`/`closed`.
- `raw_json`: execution payload.

### 21) `live_portfolio_20s` (live marked portfolio)
- `snapshot_time_utc`: key timestamp.
- `cash_dollars`, `position_value_dollars`, `realized_pnl_dollars`, `unrealized_pnl_dollars`, `equity_dollars`.
- `peak_equity_dollars`, `drawdown_dollars`: running risk state.
- `risk_state`: risk gate state.
- `raw_json`: mark context.

## Client API (Pandas)

Use `client_api` to pull full-history DataFrames (pagination hidden in client loop).

```python
from client_api import KalshiDataClient
client = KalshiDataClient(base_url="https://dehiuraiut9ro.cloudfront.net")
df = client.model_features()
```

Notebook examples: `client_api/example.ipynb`
