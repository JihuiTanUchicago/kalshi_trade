from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import pandas as pd
import requests
from requests.auth import HTTPBasicAuth

NUMERIC_COLUMNS_BY_TABLE = {
    "sim_model_predictions_1m": [
        "prob_yes",
        "signal_yes",
        "edge_est",
        "train_rows",
        "test_rows",
        "brier",
        "logloss",
    ],
    "sim_trades": [
        "id",
        "qty_contracts",
        "entry_price_dollars",
        "exit_price_dollars",
        "pnl_dollars",
    ],
    "sim_portfolio_20s": [
        "cash_dollars",
        "position_value_dollars",
        "realized_pnl_dollars",
        "unrealized_pnl_dollars",
        "equity_dollars",
        "peak_equity_dollars",
        "drawdown_dollars",
    ],
    "model_features_1m": [
        "yes_bid_dollars",
        "yes_ask_dollars",
        "spread_dollars",
        "mid_dollars",
        "yes_bid_size_fp",
        "yes_ask_size_fp",
        "orderbook_imbalance",
        "mid_ret_1m",
        "mid_ret_3m",
        "trades_last_60s_count",
        "trades_last_60s_volume_fp",
        "trades_last_60s_vwap_yes",
        "quote_change_events_60s",
        "time_to_expiry_sec",
        "cb_price",
        "cb_ret_1m",
        "cb_ret_3m",
        "cb_ret_5m",
        "cb_vol_5m",
        "kalshi_data_age_sec",
        "coinbase_data_age_sec",
        "model_eligible",
    ],
}


@dataclass
class KalshiDataClient:
    """
    Client-side API for loading project data tables as pandas DataFrames.
    Auth defaults match the dashboard basic auth.
    """

    base_url: str
    username: str = os.getenv("DASHBOARD_USER", "admin")
    password: str = os.getenv("DASHBOARD_PASSWORD", "")
    timeout_seconds: int = 30
    chunk_size: int = 5000

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._auth = HTTPBasicAuth(self.username, self.password)
        self._session = requests.Session()
        self._session.auth = self._auth

    def _get_json(self, path: str, params: Optional[Dict] = None) -> Dict:
        r = self._session.get(f"{self.base_url}{path}", params=params or {}, timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def list_tables(self) -> List[str]:
        payload = self._get_json("/api/tables")
        return list(payload.get("tables", []))

    def fetch_table(
        self,
        table: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        columns: Optional[Iterable[str]] = None,
        chunk_size: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Fetch full history (all chunks) into a single DataFrame.
        `start`/`end` are inclusive and interpreted against table's time column.
        """
        offset = 0
        limit = int(chunk_size or self.chunk_size)
        params: Dict[str, str] = {"name": table, "offset": "0", "limit": str(limit)}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if columns:
            params["columns"] = ",".join([str(c) for c in columns])

        rows = []
        schema_cols: List[str] = []
        while True:
            params["offset"] = str(offset)
            payload = self._get_json("/api/table", params=params)
            if payload.get("ok") is False:
                raise RuntimeError(payload.get("error", "api error"))
            if not schema_cols:
                schema_cols = list(payload.get("columns", []))
            batch = payload.get("rows", [])
            rows.extend(batch)
            if payload.get("done", False) or len(batch) == 0:
                break
            offset = int(payload.get("next_offset", offset + len(batch)))
        df = pd.DataFrame(rows, columns=(schema_cols or None))
        # Cast known numeric columns so downstream groupby stats work without manual coercion.
        for c in NUMERIC_COLUMNS_BY_TABLE.get(table, []):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    # Convenience wrappers
    def model_features(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_table("model_features_1m", start=start, end=end)

    def trade_quote_features(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_table("trade_quote_features_1m", start=start, end=end)

    def forward_quotes(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_table("forward_quotes", start=start, end=end)

    def coinbase_ticks(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_table("coinbase_ticks", start=start, end=end)

    def sim_predictions(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_table("sim_model_predictions_1m", start=start, end=end)

    def sim_trades(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_table("sim_trades", start=start, end=end)
