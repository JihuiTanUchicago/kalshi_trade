"""Stored Bitcoin spot and a contract's stored strike, for a market page's "Bitcoin vs the strike".

Both are reads of what the collector box already wrote, so the request path never calls an exchange
or Kalshi: coinbase_ticks is data_pipeline/coinbase_collector.py's 20-second Coinbase BTC-USD snapshot
(the series model_features_1m_builder prices cb_price from), and markets is the forward collector's
record of each contract it tracks, whose slimmed raw_json keeps the strike fields.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, Optional

from app.adapters.db.sql import _loads


def latest_spot(cur, product: str, since: datetime) -> Optional[Dict]:
    """The newest good snapshot of `product` taken at or after `since` (naive UTC): {"at", "price"}, or
    None when there is none. It reads idx_coinbase_product_time (product_id, snapshot_time_utc)
    backwards from the newest row; `since` bounds how far a run of failed snapshots (status
    'api_error', price NULL) can make it walk."""
    cur.execute(
        """SELECT snapshot_time_utc, price FROM coinbase_ticks
           WHERE product_id=%s AND snapshot_time_utc>=%s AND status='ok' AND price IS NOT NULL
           ORDER BY snapshot_time_utc DESC LIMIT 1""",
        (product, since),
    )
    r = cur.fetchone()
    return {"at": r["snapshot_time_utc"], "price": float(r["price"])} if r else None


def market_strike(cur, ticker: str) -> Optional[Dict]:
    """A contract's strike as the collector stored it (primary-key read of markets): {"floor_strike",
    "cap_strike", "strike_type", "close_time"}, or None when the collector hasn't recorded it."""
    cur.execute("SELECT close_time, raw_json FROM markets WHERE ticker=%s", (ticker,))
    r = cur.fetchone()
    return _strike_rec(r) if r else None


def market_strikes(cur, tickers: Iterable[str]) -> Dict[str, Dict]:
    """market_strike for several contracts in one primary-key read: {ticker: record} for the ones the
    collector has recorded (one it hasn't is left out). Explore's list reads a page's Bitcoin rows with it."""
    tickers = sorted(set(tickers))
    if not tickers:
        return {}
    cur.execute("SELECT ticker, close_time, raw_json FROM markets WHERE ticker IN (" + ",".join(["%s"] * len(tickers)) + ")",
                tuple(tickers))
    return {r["ticker"]: _strike_rec(r) for r in cur.fetchall()}


def _strike_rec(r: Dict) -> Dict:
    raw = _loads(r.get("raw_json")) or {}
    return {"floor_strike": raw.get("floor_strike"), "cap_strike": raw.get("cap_strike"),
            "strike_type": raw.get("strike_type"), "close_time": r.get("close_time")}
