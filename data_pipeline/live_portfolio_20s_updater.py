import json
import time
from datetime import datetime, timedelta

from data_pipeline.common import get_db_conn, get_kalshi_cash_balance_dollars, utc_now
from data_pipeline.live_trading_engine import load_settings


def next_20s_mark(now: datetime = None) -> datetime:
    if now is None:
        now = utc_now()
    base = now.replace(microsecond=0)
    sec = base.second
    if sec < 20:
        return base.replace(second=20)
    if sec < 40:
        return base.replace(second=40)
    return (base + timedelta(minutes=1)).replace(second=0)


def latest_yes_bid(cur, ticker: str):
    cur.execute(
        """
        SELECT yes_bid_dollars
        FROM forward_quotes
        WHERE market_ticker=%s
        ORDER BY snapshot_time_utc DESC
        LIMIT 1
        """,
        (ticker,),
    )
    r = cur.fetchone()
    return float(r["yes_bid_dollars"]) if r and r.get("yes_bid_dollars") is not None else None


def compute_snapshot(cur):
    cfg = load_settings(cur)
    starting = float(cfg["starting_capital"])
    account_cash = get_kalshi_cash_balance_dollars()
    cur.execute("SELECT COALESCE(SUM(pnl_dollars),0) p FROM live_trades WHERE status='closed'")
    realized = float(cur.fetchone()["p"] or 0.0)
    cur.execute("SELECT * FROM live_positions")
    pos_rows = cur.fetchall()
    cost = 0.0
    value = 0.0
    pos_detail = []
    for p in pos_rows:
        qty = int(p["qty_contracts"])
        entry = float(p["entry_price_dollars"])
        bid = latest_yes_bid(cur, p["market_ticker"])
        if bid is None:
            bid = entry
        cost += entry * qty
        value += bid * qty
        pos_detail.append({"ticker": p["market_ticker"], "qty": qty, "entry": entry, "mark_bid": bid})
    if account_cash is not None:
        cash = float(account_cash)
        cash_source = "kalshi_api"
    else:
        cash = starting + realized - cost
        cash_source = "local_fallback"
    unreal = value - cost
    equity = cash + value
    cur.execute("SELECT MAX(peak_equity_dollars) mx FROM live_portfolio_20s")
    baseline = cash if account_cash is not None else starting
    peak_prev = float(cur.fetchone()["mx"] or baseline)
    peak = max(peak_prev, equity)
    drawdown = equity - peak
    risk_state = "GREEN"
    if realized <= -abs(float(cfg["max_daily_loss"])):
        risk_state = "RED"
    if -min(0.0, realized) >= abs(float(cfg["max_total_drawdown"])):
        risk_state = "RED"
    return {
        "cash": cash,
        "value": value,
        "realized": realized,
        "unreal": unreal,
        "equity": equity,
        "peak": peak,
        "drawdown": drawdown,
        "risk_state": risk_state,
        "positions": pos_detail,
        "cash_source": cash_source,
        "settings": cfg,
    }


def run_loop():
    conn = get_db_conn()
    with conn.cursor() as cur:
        print("live portfolio 20s updater started.")
        while True:
            mark = next_20s_mark()
            time.sleep(max(0.0, (mark - utc_now()).total_seconds()))
            try:
                s = compute_snapshot(cur)
                cur.execute(
                    """
                    INSERT INTO live_portfolio_20s
                    (snapshot_time_utc,cash_dollars,position_value_dollars,realized_pnl_dollars,unrealized_pnl_dollars,equity_dollars,peak_equity_dollars,drawdown_dollars,risk_state,raw_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      cash_dollars=VALUES(cash_dollars), position_value_dollars=VALUES(position_value_dollars),
                      realized_pnl_dollars=VALUES(realized_pnl_dollars), unrealized_pnl_dollars=VALUES(unrealized_pnl_dollars),
                      equity_dollars=VALUES(equity_dollars), peak_equity_dollars=VALUES(peak_equity_dollars),
                      drawdown_dollars=VALUES(drawdown_dollars), risk_state=VALUES(risk_state), raw_json=VALUES(raw_json)
                    """,
                    (
                        mark.replace(tzinfo=None),
                        s["cash"],
                        s["value"],
                        s["realized"],
                        s["unreal"],
                        s["equity"],
                        s["peak"],
                        s["drawdown"],
                        s["risk_state"],
                        json.dumps(s),
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES ('live_portfolio_20s_last_snapshot',%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    (json.dumps({"snapshot_time_utc": mark.isoformat(), "equity": s["equity"]}), utc_now().replace(tzinfo=None)),
                )
            except Exception as e:
                print(f"live_portfolio_20s error at {mark.isoformat()}: {e}")
                # Re-raise so the outer loop tears down this connection/cursor and
                # acquires a fresh one, instead of retrying forever on a dead connection.
                raise


if __name__ == "__main__":
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f"[ERROR] live_portfolio_20s updater crashed: {e}")
            time.sleep(5)
