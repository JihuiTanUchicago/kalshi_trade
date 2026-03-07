import json
import uuid
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from data_pipeline.common import api_get, api_post_auth, get_db_conn, utc_now

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
]

DEFAULT_SETTINGS = {
    "live_enabled": False,
    "starting_capital": 30.0,
    "signal_threshold": 0.55,
    "edge_threshold": 0.01,
    "max_trade_cost": 2.0,
    "max_open_notional": 6.0,
    "max_concurrent_positions": 1,
    "max_daily_loss": 5.0,
    "max_total_drawdown": 10.0,
    "min_samples_default_rf": 1000,
}


def to_float(v):
    return 0.0 if v is None else float(v)


def next_minute_plus_delay(delay_seconds: int = 12) -> datetime:
    now = utc_now()
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1, seconds=delay_seconds)


def load_settings(cur) -> Dict:
    cur.execute("SELECT settings_json FROM live_settings WHERE settings_key='live_config' LIMIT 1")
    row = cur.fetchone()
    if not row:
        cur.execute(
            """
            INSERT INTO live_settings (settings_key, settings_json, updated_at_utc)
            VALUES ('live_config', %s, %s)
            """,
            (json.dumps(DEFAULT_SETTINGS), utc_now().replace(tzinfo=None)),
        )
        return dict(DEFAULT_SETTINGS)
    cfg = row["settings_json"] if isinstance(row["settings_json"], dict) else json.loads(row["settings_json"])
    out = dict(DEFAULT_SETTINGS)
    out.update(cfg or {})
    return out


def load_feature_rows(cur, limit=8000) -> List[Dict]:
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, {",".join(FEATURE_COLS)}
        FROM model_features_1m
        WHERE model_eligible=1
        ORDER BY snapshot_minute_utc ASC
        LIMIT {limit}
        """
    )
    return cur.fetchall()


def build_supervised(rows: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for i in range(len(rows) - 1):
        r, n = rows[i], rows[i + 1]
        if r["market_ticker"] != n["market_ticker"]:
            continue
        if r.get("mid_dollars") is None or n.get("mid_dollars") is None:
            continue
        X.append([to_float(r.get(c)) for c in FEATURE_COLS])
        y.append(1 if float(n["mid_dollars"]) > float(r["mid_dollars"]) else 0)
    if not X:
        return np.empty((0, len(FEATURE_COLS))), np.empty((0,))
    return np.asarray(X, dtype=float), np.asarray(y, dtype=int)


def train_rf_prob(rows: List[Dict], min_samples_default_rf: int) -> Optional[float]:
    X, y = build_supervised(rows)
    if len(X) < 20:
        return None
    x_latest = np.asarray([to_float(rows[-1].get(c)) for c in FEATURE_COLS], dtype=float)
    if len(X) >= min_samples_default_rf:
        params = dict(
            n_estimators=400,
            max_depth=8,
            min_samples_leaf=20,
            min_samples_split=50,
            max_features="sqrt",
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )
    else:
        params = dict(
            n_estimators=120,
            max_depth=5,
            min_samples_leaf=5,
            min_samples_split=20,
            max_features="sqrt",
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )
    clf = RandomForestClassifier(**params)
    clf.fit(X, y)
    return float(clf.predict_proba([x_latest])[0, 1])


def current_risk_state(cur, cfg: Dict) -> Tuple[str, Dict]:
    cur.execute("SELECT COALESCE(SUM(pnl_dollars),0) p FROM live_trades WHERE status='closed'")
    total_realized = float(cur.fetchone()["p"] or 0.0)
    cur.execute(
        "SELECT COALESCE(SUM(pnl_dollars),0) p FROM live_trades WHERE status='closed' AND DATE(closed_at_utc)=UTC_DATE()"
    )
    daily_realized = float(cur.fetchone()["p"] or 0.0)
    cur.execute("SELECT COUNT(*) c, COALESCE(SUM(entry_price_dollars*qty_contracts),0) n FROM live_positions")
    pos = cur.fetchone()
    open_count = int(pos["c"] or 0)
    open_notional = float(pos["n"] or 0.0)
    total_dd = -min(0.0, total_realized)
    risk = "GREEN"
    reasons = []
    if daily_realized <= -abs(float(cfg["max_daily_loss"])):
        reasons.append("MAX_DAILY_LOSS")
    if total_dd >= abs(float(cfg["max_total_drawdown"])):
        reasons.append("MAX_TOTAL_DD")
    if reasons:
        risk = "RED"
    return risk, {
        "daily_realized": daily_realized,
        "total_realized": total_realized,
        "open_count": open_count,
        "open_notional": open_notional,
        "reasons": reasons,
    }


def compute_buy_qty(prob: float, ask: float, cfg: Dict) -> int:
    edge = prob - ask
    if edge <= float(cfg["edge_threshold"]):
        return 0
    max_by_cost = int(float(cfg["max_trade_cost"]) / max(ask, 1e-6))
    scaled = int((edge / 0.03) * max_by_cost)
    return max(0, min(max_by_cost, max(1, scaled)))


def place_limit_order(ticker: str, action: str, side: str, qty: int, price_dollars: float) -> Dict:
    cents = max(1, min(99, int(round(price_dollars * 100))))
    client_order_id = str(uuid.uuid4())
    body = {
        "ticker": ticker,
        "action": action,
        "side": side,
        "count": qty,
        "type": "limit",
        "yes_price": cents,
        "client_order_id": client_order_id,
    }
    resp = api_post_auth("/trade-api/v2/portfolio/orders", body)
    return {"client_order_id": client_order_id, "body": body, "resp": resp}


def open_live_position(cur, ticker: str, qty: int, ask: float, prob: float, now_ts: datetime) -> None:
    res = place_limit_order(ticker, "buy", "yes", qty, ask)
    order = res.get("resp", {}).get("order", {})
    kalshi_order_id = order.get("order_id")
    status = order.get("status", "submitted")
    cur.execute(
        """
        INSERT INTO live_orders (created_at_utc,market_ticker,action,side,qty_contracts,limit_price_dollars,status,kalshi_order_id,client_order_id,raw_json)
        VALUES (%s,%s,'buy','yes',%s,%s,%s,%s,%s,%s)
        """,
        (
            now_ts.replace(tzinfo=None),
            ticker,
            qty,
            ask,
            status,
            kalshi_order_id,
            res["client_order_id"],
            json.dumps(res),
        ),
    )
    # Conservative assumption for MVP: treat accepted order as filled at limit price.
    cur.execute(
        """
        INSERT INTO live_positions (market_ticker,opened_at_utc,qty_contracts,entry_price_dollars,model_name,raw_json)
        VALUES (%s,%s,%s,%s,'random_forest',%s)
        ON DUPLICATE KEY UPDATE
          opened_at_utc=VALUES(opened_at_utc),
          qty_contracts=VALUES(qty_contracts),
          entry_price_dollars=VALUES(entry_price_dollars),
          raw_json=VALUES(raw_json)
        """,
        (ticker, now_ts.replace(tzinfo=None), qty, ask, json.dumps({"prob": prob, "order": res})),
    )
    cur.execute(
        """
        INSERT INTO live_trades (opened_at_utc,market_ticker,model_name,qty_contracts,entry_price_dollars,status,raw_json)
        VALUES (%s,%s,'random_forest',%s,%s,'open',%s)
        """,
        (now_ts.replace(tzinfo=None), ticker, qty, ask, json.dumps({"prob": prob, "order": res})),
    )


def close_live_position(cur, ticker: str, bid: float, now_ts: datetime) -> None:
    cur.execute("SELECT * FROM live_positions WHERE market_ticker=%s", (ticker,))
    pos = cur.fetchone()
    if not pos:
        return
    qty = int(pos["qty_contracts"])
    entry = float(pos["entry_price_dollars"])
    res = place_limit_order(ticker, "sell", "yes", qty, bid)
    order = res.get("resp", {}).get("order", {})
    kalshi_order_id = order.get("order_id")
    status = order.get("status", "submitted")
    cur.execute(
        """
        INSERT INTO live_orders (created_at_utc,market_ticker,action,side,qty_contracts,limit_price_dollars,status,kalshi_order_id,client_order_id,raw_json)
        VALUES (%s,%s,'sell','yes',%s,%s,%s,%s,%s,%s)
        """,
        (
            now_ts.replace(tzinfo=None),
            ticker,
            qty,
            bid,
            status,
            kalshi_order_id,
            res["client_order_id"],
            json.dumps(res),
        ),
    )
    pnl = (bid - entry) * qty
    cur.execute(
        """
        UPDATE live_trades
        SET closed_at_utc=%s, exit_price_dollars=%s, pnl_dollars=%s, status='closed'
        WHERE market_ticker=%s AND status='open'
        ORDER BY opened_at_utc DESC
        LIMIT 1
        """,
        (now_ts.replace(tzinfo=None), bid, pnl, ticker),
    )
    cur.execute("DELETE FROM live_positions WHERE market_ticker=%s", (ticker,))


def run_loop() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        print("live trading engine started (RF-only).")
        while True:
            wake = next_minute_plus_delay(12)
            time.sleep(max(0.0, (wake - utc_now()).total_seconds()))
            now_ts = wake.replace(second=0, microsecond=0)
            try:
                cfg = load_settings(cur)
                rows = load_feature_rows(cur)
                if len(rows) < 20:
                    continue
                latest = rows[-1]
                ticker = latest["market_ticker"]
                if not ticker:
                    continue
                bid = float(latest.get("yes_bid_dollars") or 0.0)
                ask = float(latest.get("yes_ask_dollars") or 0.0)
                if bid <= 0 or ask <= 0:
                    continue

                risk_state, risk_meta = current_risk_state(cur, cfg)
                prob = train_rf_prob(rows, int(cfg["min_samples_default_rf"]))
                if prob is None:
                    continue
                edge = prob - ask
                signal = prob >= float(cfg["signal_threshold"]) and edge > float(cfg["edge_threshold"])

                # Close stale positions when ticker rotates or signal collapses.
                cur.execute("SELECT market_ticker FROM live_positions LIMIT 1")
                pos = cur.fetchone()
                if pos and (pos["market_ticker"] != ticker or not signal):
                    close_live_position(cur, pos["market_ticker"], bid, now_ts)

                if not bool(cfg["live_enabled"]):
                    state = {"live_enabled": False, "risk_state": risk_state, "prob": prob, "signal": signal}
                    cur.execute(
                        """
                        INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                        VALUES ('live_trading_last_snapshot',%s,%s)
                        ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                        """,
                        (json.dumps(state), utc_now().replace(tzinfo=None)),
                    )
                    continue

                if risk_state == "RED":
                    continue
                if signal:
                    if risk_meta["open_count"] >= int(cfg["max_concurrent_positions"]):
                        continue
                    if risk_meta["open_notional"] >= float(cfg["max_open_notional"]):
                        continue
                    qty = compute_buy_qty(prob, ask, cfg)
                    if qty > 0:
                        open_live_position(cur, ticker, qty, ask, prob, now_ts)

                state = {
                    "live_enabled": True,
                    "risk_state": risk_state,
                    "risk": risk_meta,
                    "prob": prob,
                    "signal": signal,
                    "ticker": ticker,
                    "edge": edge,
                }
                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES ('live_trading_last_snapshot',%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    (json.dumps(state), utc_now().replace(tzinfo=None)),
                )
                print(f"live rf t={now_ts.isoformat()} ticker={ticker} p={prob:.4f} edge={edge:.4f} signal={int(signal)} risk={risk_state}")
            except Exception as e:
                print(f"live trading error at {now_ts.isoformat()}: {e}")


if __name__ == "__main__":
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f"[ERROR] live trading engine crashed: {e}")
            time.sleep(5)
