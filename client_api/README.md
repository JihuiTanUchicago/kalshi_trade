# Client API

Simple Python client to load project data as pandas DataFrames without manual paging.

## Install

```bash
pip install pandas requests
```

## Usage

```python
from client_api import KalshiDataClient

client = KalshiDataClient(
    base_url="https://dehiuraiut9ro.cloudfront.net",
    username="todd",
    password="kalshimakesmepoor",
)

# Full history (auto-paginated under the hood)
df_features = client.model_features()

# Time-bounded pull
df_quotes = client.forward_quotes(start="2026-03-01 00:00:00", end="2026-03-07 23:59:59")

# Generic table pull
df_trades = client.fetch_table("sim_trades")
```

## Available Tables (v1)

- `model_features_1m`
- `trade_quote_features_1m`
- `forward_quotes`
- `coinbase_ticks`
- `sim_model_predictions_1m`
- `sim_trades`
- `sim_portfolio_20s`
