import json
import math
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from data_pipeline.common import get_db_conn, is_primary_micro_ticker, utc_now


def to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    return float(x)


def next_minute_plus_delay(delay_seconds: int = 5) -> datetime:
    now = utc_now()
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1, seconds=delay_seconds)


def asof_forward(cur, ticker: str, ts: datetime) -> Optional[Dict]:
    cur.execute(
        """
        SELECT snapshot_time_utc, yes_bid_dollars, yes_ask_dollars, yes_bid_size_fp, yes_ask_size_fp,
               volume_fp, open_interest_fp
        FROM forward_quotes
        WHERE market_ticker=%s AND snapshot_time_utc<=%s
        ORDER BY snapshot_time_utc DESC
        LIMIT 1
        """,
        (ticker, ts.replace(tzinfo=None)),
    )
    return cur.fetchone()


def asof_coinbase(cur, ts: datetime) -> Optional[Dict]:
    cur.execute(
        """
        SELECT snapshot_time_utc, price
        FROM coinbase_ticks
        WHERE status='ok' AND snapshot_time_utc<=%s
        ORDER BY snapshot_time_utc DESC
        LIMIT 1
        """,
        (ts.replace(tzinfo=None),),
    )
    return cur.fetchone()


def compute_ret(now_val: Optional[float], prev_val: Optional[float]) -> Optional[float]:
    if now_val is None or prev_val is None or prev_val == 0:
        return None
    return (now_val / prev_val) - 1.0


def compute_std(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _to_json_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            obj = json.loads(value)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


def _target_from_market_raw(raw: Dict[str, Any]) -> Optional[float]:
    floor = raw.get("floor_strike")
    strike = raw.get("strike_price")
    if floor is not None:
        return to_float(floor)
    if strike is not None:
        return to_float(strike)
    return None


def _resolve_target_btc_price(
    cur,
    ticker: Optional[str],
    event_ticker: Optional[str],
    minute_mark: datetime,
    target_cache: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    minute_naive = minute_mark.replace(tzinfo=None)
    if not ticker:
        return {"target_btc_price": None, "target_source": "missing_ticker", "close_time": None}

    if target_cache is not None:
        cached = target_cache.get(ticker)
        if cached:
            close_t = cached.get("close_time")
            cache_event = cached.get("event_ticker")
            if close_t and minute_naive < close_t and (not event_ticker or not cache_event or cache_event == event_ticker):
                return {
                    "target_btc_price": cached.get("target_btc_price"),
                    "target_source": "cache",
                    "close_time": close_t,
                }

    cur.execute(
        """
        SELECT close_time, raw_json
        FROM markets
        WHERE ticker=%s
        LIMIT 1
        """,
        (ticker,),
    )
    m = cur.fetchone()
    if not m:
        return {"target_btc_price": None, "target_source": "markets_missing", "close_time": None}

    close_t = m.get("close_time")
    raw = _to_json_obj(m.get("raw_json"))
    target = _target_from_market_raw(raw)
    source = "floor_strike" if raw.get("floor_strike") is not None else ("strike_price" if raw.get("strike_price") is not None else "missing")

    if target_cache is not None:
        target_cache[ticker] = {
            "target_btc_price": target,
            "close_time": close_t,
            "event_ticker": event_ticker,
        }
    return {"target_btc_price": target, "target_source": source, "close_time": close_t}


def missing_tq_row(minute_mark: datetime) -> Dict[str, Any]:
    return {
        "snapshot_minute_utc": minute_mark,
        "market_ticker": None,
        "event_ticker": None,
        "target_btc_price": None,
        "guard_status": "error",
        "guard_reasons": ["MISSING_TRADE_QUOTE_FEATURES"],
        "model_eligible": 0,
        "raw_json": {"reason": "missing_trade_quote_features"},
    }


def list_ok_tq_rows(cur, minute_mark: datetime) -> List[Dict[str, Any]]:
    """Every market that has an 'ok' trade/quote feature row for this minute. The
    feeder writes one per active series, so this is one row per (series, minute)."""
    cur.execute(
        """
        SELECT snapshot_minute_utc, market_ticker, event_ticker, trades_last_60s_count, trades_last_60s_volume_fp,
               trades_last_60s_vwap_yes, quote_change_events_60s, source_status
        FROM trade_quote_features_1m
        WHERE snapshot_minute_utc=%s AND source_status='ok' AND market_ticker IS NOT NULL
        """,
        (minute_mark.replace(tzinfo=None),),
    )
    return cur.fetchall()


def build_row(cur, minute_mark: datetime, tq: Dict[str, Any], target_cache: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    ticker = tq["market_ticker"]
    event_ticker = tq.get("event_ticker")
    # Only the primary (BTC) series feeds the live/sim models: it alone is
    # model_eligible and carries the Coinbase-spot (cb_*) features. Other series are
    # collected for research (order-flow features from the Kalshi book + trades) and
    # are forced model_eligible=0 so the eligible-gated BTC readers never see them.
    is_primary = is_primary_micro_ticker(ticker)

    guard_reasons: List[str] = []
    guard_status = "ok"
    model_eligible = 1

    f0 = asof_forward(cur, ticker, minute_mark)
    f1 = asof_forward(cur, ticker, minute_mark - timedelta(minutes=1))
    f3 = asof_forward(cur, ticker, minute_mark - timedelta(minutes=3))
    # Coinbase is BTC-USD spot only; it is meaningful solely for the BTC series, so
    # non-primary rows leave every cb_* feature NULL rather than fabricate a wrong one.
    if is_primary:
        c0 = asof_coinbase(cur, minute_mark)
        c1 = asof_coinbase(cur, minute_mark - timedelta(minutes=1))
        c3 = asof_coinbase(cur, minute_mark - timedelta(minutes=3))
        c5 = asof_coinbase(cur, minute_mark - timedelta(minutes=5))
    else:
        c0 = c1 = c3 = c5 = None

    if not f0:
        guard_reasons.append("MISSING_KALSHI_FORWARD")
    if is_primary and not c0:
        guard_reasons.append("MISSING_COINBASE_TICK")

    yes_bid = to_float(f0["yes_bid_dollars"]) if f0 else None
    yes_ask = to_float(f0["yes_ask_dollars"]) if f0 else None
    spread = (yes_ask - yes_bid) if (yes_ask is not None and yes_bid is not None) else None
    mid = (yes_ask + yes_bid) / 2.0 if (yes_ask is not None and yes_bid is not None) else None
    mid_1 = None
    mid_3 = None
    if f1 and f1.get("yes_bid_dollars") is not None and f1.get("yes_ask_dollars") is not None:
        mid_1 = (to_float(f1["yes_bid_dollars"]) + to_float(f1["yes_ask_dollars"])) / 2.0
    if f3 and f3.get("yes_bid_dollars") is not None and f3.get("yes_ask_dollars") is not None:
        mid_3 = (to_float(f3["yes_bid_dollars"]) + to_float(f3["yes_ask_dollars"])) / 2.0

    bid_size = to_float(f0["yes_bid_size_fp"]) if f0 else None
    ask_size = to_float(f0["yes_ask_size_fp"]) if f0 else None
    imbalance = None
    if bid_size is not None and ask_size is not None and (bid_size + ask_size) > 0:
        imbalance = (bid_size - ask_size) / (bid_size + ask_size)

    cb0 = to_float(c0["price"]) if c0 else None
    cb1 = to_float(c1["price"]) if c1 else None
    cb3 = to_float(c3["price"]) if c3 else None
    cb5 = to_float(c5["price"]) if c5 else None

    cb_ret_1m = compute_ret(cb0, cb1)
    cb_ret_3m = compute_ret(cb0, cb3)
    cb_ret_5m = compute_ret(cb0, cb5)

    cb_prices: List[float] = []
    if is_primary:
        for i in range(0, 6):
            ci = asof_coinbase(cur, minute_mark - timedelta(minutes=i))
            if ci and ci.get("price") is not None:
                cb_prices.append(to_float(ci["price"]))
    cb_prices = list(reversed(cb_prices))
    cb_returns = []
    for i in range(1, len(cb_prices)):
        if cb_prices[i - 1] != 0:
            cb_returns.append((cb_prices[i] / cb_prices[i - 1]) - 1.0)
    cb_vol_5m = compute_std(cb_returns)

    kalshi_age = None
    coinbase_age = None
    if f0 and f0.get("snapshot_time_utc"):
        kalshi_age = int((minute_mark.replace(tzinfo=None) - f0["snapshot_time_utc"]).total_seconds())
    if c0 and c0.get("snapshot_time_utc"):
        coinbase_age = int((minute_mark.replace(tzinfo=None) - c0["snapshot_time_utc"]).total_seconds())

    target_info = _resolve_target_btc_price(cur, ticker, event_ticker, minute_mark, target_cache)
    target_btc_price = target_info.get("target_btc_price")

    cur.execute("SELECT close_time FROM markets WHERE ticker=%s LIMIT 1", (ticker,))
    m = cur.fetchone()
    tte = None
    if m and m.get("close_time"):
        tte = max(0, int((m["close_time"] - minute_mark.replace(tzinfo=None)).total_seconds()))

    if yes_bid is None or yes_ask is None:
        guard_reasons.append("MISSING_BID_ASK")
    if yes_bid is not None and (yes_bid < 0 or yes_bid > 1):
        guard_reasons.append("YES_BID_OUT_OF_RANGE")
    if yes_ask is not None and (yes_ask < 0 or yes_ask > 1):
        guard_reasons.append("YES_ASK_OUT_OF_RANGE")
    if spread is not None and spread < 0:
        guard_reasons.append("NEGATIVE_SPREAD")
    if kalshi_age is not None and kalshi_age > 40:
        guard_reasons.append("STALE_KALSHI")
    if coinbase_age is not None and coinbase_age > 40:
        guard_reasons.append("STALE_COINBASE")

    # Non-primary series are research-only: never eligible for the BTC live/sim models,
    # regardless of how clean their order-flow data is.
    if not is_primary:
        guard_reasons.append("NON_PRIMARY_SERIES")

    if guard_reasons:
        model_eligible = 0
        guard_status = "error" if any(
            x in guard_reasons
            for x in ["MISSING_TRADE_QUOTE_FEATURES", "MISSING_KALSHI_FORWARD", "MISSING_COINBASE_TICK", "MISSING_BID_ASK", "NEGATIVE_SPREAD"]
        ) else "warn"

    return {
        "snapshot_minute_utc": minute_mark,
        "market_ticker": ticker,
        "event_ticker": event_ticker,
        "target_btc_price": target_btc_price,
        "yes_bid_dollars": yes_bid,
        "yes_ask_dollars": yes_ask,
        "spread_dollars": spread,
        "mid_dollars": mid,
        "yes_bid_size_fp": bid_size,
        "yes_ask_size_fp": ask_size,
        "orderbook_imbalance": imbalance,
        "mid_ret_1m": compute_ret(mid, mid_1),
        "mid_ret_3m": compute_ret(mid, mid_3),
        "trades_last_60s_count": tq.get("trades_last_60s_count"),
        "trades_last_60s_volume_fp": to_float(tq.get("trades_last_60s_volume_fp")),
        "trades_last_60s_vwap_yes": to_float(tq.get("trades_last_60s_vwap_yes")),
        "quote_change_events_60s": tq.get("quote_change_events_60s"),
        "time_to_expiry_sec": tte,
        "cb_price": cb0,
        "cb_ret_1m": cb_ret_1m,
        "cb_ret_3m": cb_ret_3m,
        "cb_ret_5m": cb_ret_5m,
        "cb_vol_5m": cb_vol_5m,
        "kalshi_data_age_sec": kalshi_age,
        "coinbase_data_age_sec": coinbase_age,
        "model_eligible": model_eligible,
        "guard_status": guard_status,
        "guard_reasons": guard_reasons,
        "raw_json": {
            "trade_quote": tq,
            "forward_asof": f0,
            "coinbase_asof": c0,
            "target_source": target_info.get("target_source"),
            "target_close_time": target_info.get("close_time").isoformat() if target_info.get("close_time") else None,
            "guard_reasons": guard_reasons,
        },
    }


def upsert_row(cur, row: Dict[str, Any]) -> None:
    cur.execute(
        """
        INSERT INTO model_features_1m
        (snapshot_minute_utc,market_ticker,event_ticker,target_btc_price,yes_bid_dollars,yes_ask_dollars,spread_dollars,mid_dollars,
         yes_bid_size_fp,yes_ask_size_fp,orderbook_imbalance,mid_ret_1m,mid_ret_3m,trades_last_60s_count,trades_last_60s_volume_fp,
         trades_last_60s_vwap_yes,quote_change_events_60s,time_to_expiry_sec,cb_price,cb_ret_1m,cb_ret_3m,cb_ret_5m,cb_vol_5m,
         kalshi_data_age_sec,coinbase_data_age_sec,model_eligible,guard_status,guard_reasons_json,raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          market_ticker=VALUES(market_ticker), event_ticker=VALUES(event_ticker), target_btc_price=VALUES(target_btc_price),
          yes_bid_dollars=VALUES(yes_bid_dollars), yes_ask_dollars=VALUES(yes_ask_dollars),
          spread_dollars=VALUES(spread_dollars), mid_dollars=VALUES(mid_dollars),
          yes_bid_size_fp=VALUES(yes_bid_size_fp), yes_ask_size_fp=VALUES(yes_ask_size_fp), orderbook_imbalance=VALUES(orderbook_imbalance),
          mid_ret_1m=VALUES(mid_ret_1m), mid_ret_3m=VALUES(mid_ret_3m),
          trades_last_60s_count=VALUES(trades_last_60s_count), trades_last_60s_volume_fp=VALUES(trades_last_60s_volume_fp),
          trades_last_60s_vwap_yes=VALUES(trades_last_60s_vwap_yes), quote_change_events_60s=VALUES(quote_change_events_60s),
          time_to_expiry_sec=VALUES(time_to_expiry_sec), cb_price=VALUES(cb_price),
          cb_ret_1m=VALUES(cb_ret_1m), cb_ret_3m=VALUES(cb_ret_3m), cb_ret_5m=VALUES(cb_ret_5m), cb_vol_5m=VALUES(cb_vol_5m),
          kalshi_data_age_sec=VALUES(kalshi_data_age_sec), coinbase_data_age_sec=VALUES(coinbase_data_age_sec),
          model_eligible=VALUES(model_eligible), guard_status=VALUES(guard_status),
          guard_reasons_json=VALUES(guard_reasons_json), raw_json=VALUES(raw_json)
        """,
        (
            row["snapshot_minute_utc"].replace(tzinfo=None),
            row.get("market_ticker"),
            row.get("event_ticker"),
            row.get("target_btc_price"),
            row.get("yes_bid_dollars"),
            row.get("yes_ask_dollars"),
            row.get("spread_dollars"),
            row.get("mid_dollars"),
            row.get("yes_bid_size_fp"),
            row.get("yes_ask_size_fp"),
            row.get("orderbook_imbalance"),
            row.get("mid_ret_1m"),
            row.get("mid_ret_3m"),
            row.get("trades_last_60s_count"),
            row.get("trades_last_60s_volume_fp"),
            row.get("trades_last_60s_vwap_yes"),
            row.get("quote_change_events_60s"),
            row.get("time_to_expiry_sec"),
            row.get("cb_price"),
            row.get("cb_ret_1m"),
            row.get("cb_ret_3m"),
            row.get("cb_ret_5m"),
            row.get("cb_vol_5m"),
            row.get("kalshi_data_age_sec"),
            row.get("coinbase_data_age_sec"),
            row.get("model_eligible"),
            row.get("guard_status"),
            json.dumps(row.get("guard_reasons", [])),
            json.dumps(row.get("raw_json", {}), default=str),
        ),
    )


def run_loop() -> None:
    conn = get_db_conn()
    target_cache: Dict[str, Dict[str, Any]] = {}
    with conn.cursor() as cur:
        print("model_features_1m builder started. Writing minute-sharp rows (+5s), one per active market.")
        while True:
            wake = next_minute_plus_delay(5)
            time.sleep(max(0.0, (wake - utc_now()).total_seconds()))
            minute_mark = wake.replace(second=0, microsecond=0)
            try:
                tq_rows = list_ok_tq_rows(cur, minute_mark)
                # The collector_state heartbeat tracks the PRIMARY (BTC) row, as before,
                # so the live-path health view is unchanged by the extra series.
                primary_row = missing_tq_row(minute_mark)
                if not tq_rows:
                    upsert_row(cur, primary_row)
                else:
                    for tq in tq_rows:
                        row = build_row(cur, minute_mark, tq, target_cache)
                        upsert_row(cur, row)
                        if is_primary_micro_ticker(row.get("market_ticker")):
                            primary_row = row
                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES (%s,%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    (
                        "model_features_1m_last_snapshot",
                        json.dumps(
                            {
                                "snapshot_minute_utc": minute_mark.isoformat(),
                                "market_ticker": primary_row.get("market_ticker"),
                                "guard_status": primary_row.get("guard_status"),
                                "model_eligible": primary_row.get("model_eligible"),
                                "markets_built": len(tq_rows),
                            }
                        ),
                        utc_now().replace(tzinfo=None),
                    ),
                )
                print(
                    f"model_features_1m snapshot {minute_mark.isoformat()} markets={len(tq_rows)} "
                    f"primary_ticker={primary_row.get('market_ticker')} eligible={primary_row.get('model_eligible')} "
                    f"status={primary_row.get('guard_status')}"
                )
            except Exception as e:
                print(f"model_features_1m error at {minute_mark.isoformat()}: {e}")
                # Re-raise so the outer loop tears down this connection/cursor and
                # acquires a fresh one, instead of retrying forever on a dead connection.
                raise


if __name__ == "__main__":
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f"[ERROR] model_features_1m builder crashed: {e}")
            time.sleep(5)
