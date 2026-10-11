import math
from typing import Dict, List, Optional


SOURCE_COLS = [
    "yes_bid_dollars",
    "yes_ask_dollars",
    "spread_dollars",
    "mid_dollars",
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
    "target_btc_price",
]


FEATURE_COLS = [
    "yes_bid_dollars",
    "yes_ask_dollars",
    "spread_dollars",
    "mid_dollars",
    "orderbook_imbalance",
    "mid_ret_1m",
    "mid_ret_3m",
    "trades_last_60s_count",
    "trades_last_60s_volume_fp",
    "trades_last_60s_vwap_yes",
    "quote_change_events_60s",
    "time_to_expiry_sec",
    "cb_ret_1m",
    "cb_ret_3m",
    "cb_ret_5m",
    "cb_vol_5m",
    "moneyness_abs",
    "moneyness_pct",
    "moneyness_vol_scaled",
    "moneyness_x_sqrt_tte",
    "moneyness_x_imbalance",
    "moneyness_x_qchg",
]


# Naive baseline uses a reduced linear subset (no interaction terms).
BASELINE_FEATURE_COLS = [
    "yes_bid_dollars",
    "yes_ask_dollars",
    "spread_dollars",
    "mid_dollars",
    "orderbook_imbalance",
    "mid_ret_1m",
    "mid_ret_3m",
    "trades_last_60s_count",
    "quote_change_events_60s",
    "time_to_expiry_sec",
    "cb_ret_1m",
    "cb_ret_3m",
    "moneyness_pct",
]


def coalesce_float(v) -> float:
    return 0.0 if v is None else float(v)


def has_target(row: Dict) -> bool:
    t = row.get("target_btc_price")
    return t is not None and float(t) > 0


def _safe_target_and_spot(row: Dict) -> Optional[tuple]:
    target = row.get("target_btc_price")
    spot = row.get("cb_price")
    if target is None or spot is None:
        return None
    target_f = float(target)
    spot_f = float(spot)
    if target_f <= 0:
        return None
    return target_f, spot_f


def build_feature_vector(row: Dict) -> List[float]:
    # Base microstructure/momentum features.
    base = [
        coalesce_float(row.get("yes_bid_dollars")),
        coalesce_float(row.get("yes_ask_dollars")),
        coalesce_float(row.get("spread_dollars")),
        coalesce_float(row.get("mid_dollars")),
        coalesce_float(row.get("orderbook_imbalance")),
        coalesce_float(row.get("mid_ret_1m")),
        coalesce_float(row.get("mid_ret_3m")),
        coalesce_float(row.get("trades_last_60s_count")),
        coalesce_float(row.get("trades_last_60s_volume_fp")),
        coalesce_float(row.get("trades_last_60s_vwap_yes")),
        coalesce_float(row.get("quote_change_events_60s")),
        coalesce_float(row.get("time_to_expiry_sec")),
        coalesce_float(row.get("cb_ret_1m")),
        coalesce_float(row.get("cb_ret_3m")),
        coalesce_float(row.get("cb_ret_5m")),
        coalesce_float(row.get("cb_vol_5m")),
    ]

    m_abs = 0.0
    m_pct = 0.0
    m_vol_scaled = 0.0
    m_x_sqrt_tte = 0.0
    m_x_imb = 0.0
    m_x_qchg = 0.0
    ts = _safe_target_and_spot(row)
    if ts is not None:
        target, spot = ts
        m_abs = spot - target
        m_pct = m_abs / target
        cb_vol = abs(coalesce_float(row.get("cb_vol_5m")))
        price_vol = max(spot * max(cb_vol, 1e-6), 1e-6)
        m_vol_scaled = m_abs / price_vol
        tte = max(coalesce_float(row.get("time_to_expiry_sec")), 1.0)
        m_x_sqrt_tte = m_pct * math.sqrt(tte)
        m_x_imb = m_pct * coalesce_float(row.get("orderbook_imbalance"))
        m_x_qchg = m_pct * coalesce_float(row.get("quote_change_events_60s"))

    return base + [m_abs, m_pct, m_vol_scaled, m_x_sqrt_tte, m_x_imb, m_x_qchg]
