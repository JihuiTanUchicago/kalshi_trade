import json
import time
from datetime import datetime, timedelta
from typing import Dict, List

from data_pipeline.common import next_20s_mark, get_db_conn, utc_now
from data_pipeline.sim_config import STARTING_CAPITAL
from data_pipeline.sim_repository import is_sim_recompute_in_progress
from data_pipeline.simulated_trading_engine import ALL_MODELS



def latest_yes_bid_and_size(cur, ticker: str):
    cur.execute(
        """
        SELECT yes_bid_dollars, yes_bid_size_fp
        FROM forward_quotes
        WHERE market_ticker=%s
        ORDER BY snapshot_time_utc DESC
        LIMIT 1
        """,
        (ticker,),
    )
    r = cur.fetchone()
    if not r or r.get("yes_bid_dollars") is None:
        return None, None
    bid = float(r["yes_bid_dollars"])
    size = float(r["yes_bid_size_fp"]) if r.get("yes_bid_size_fp") is not None else 0.0
    return bid, size


def compute_model_snapshot(cur, model_name: str) -> Dict:
    cur.execute(
        "SELECT COALESCE(SUM(pnl_dollars),0) p FROM sim_trades WHERE model_name=%s AND status='closed'",
        (model_name,),
    )
    realized = float(cur.fetchone()["p"] or 0.0)

    cur.execute("SELECT * FROM sim_positions WHERE model_name=%s", (model_name,))
    positions: List[Dict] = cur.fetchall()

    cost = 0.0
    pos_value = 0.0
    details = []
    for p in positions:
        qty = int(p["qty_contracts"])
        entry = float(p["entry_price_dollars"])
        bid, bid_size = latest_yes_bid_and_size(cur, p["market_ticker"])
        if bid is None:
            bid = 0.0
            bid_size = 0.0
        # Mark-to-market uses full qty at best bid for consistency with
        # the current conservative sim execution assumptions.
        value = float(qty) * bid
        cost += entry * qty
        pos_value += value
        details.append(
            {
                "ticker": p["market_ticker"],
                "qty": qty,
                "entry": entry,
                "mark_bid": bid,
                "mark_bid_size": bid_size,
                "value": value,
            }
        )

    cash = STARTING_CAPITAL + realized - cost
    unrealized = pos_value - cost
    equity = cash + pos_value

    cur.execute(
        """
        SELECT MAX(peak_equity_dollars) mx
        FROM sim_portfolio_20s
        WHERE model_name=%s
        """,
        (model_name,),
    )
    prev_peak = float(cur.fetchone()["mx"] or STARTING_CAPITAL)
    peak = max(prev_peak, equity)
    drawdown = equity - peak
    return {
        "model_name": model_name,
        "cash": cash,
        "position_value": pos_value,
        "realized": realized,
        "unrealized": unrealized,
        "equity": equity,
        "peak": peak,
        "drawdown": drawdown,
        "positions": details,
    }


def run_loop() -> None:
    conn = get_db_conn()
    cur = conn.cursor()
    print("sim portfolio 20s updater started.")
    while True:
        mark = next_20s_mark()
        time.sleep(max(0.0, (mark - utc_now()).total_seconds()))
        try:
            # Avoid writing while full sim recompute is rebuilding sim tables.
            if is_sim_recompute_in_progress(cur):
                continue
            for model_name in ALL_MODELS:
                row = compute_model_snapshot(cur, model_name)
                cur.execute(
                    """
                    INSERT INTO sim_portfolio_20s
                    (snapshot_time_utc,model_name,cash_dollars,position_value_dollars,realized_pnl_dollars,unrealized_pnl_dollars,equity_dollars,peak_equity_dollars,drawdown_dollars,raw_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      cash_dollars=VALUES(cash_dollars),
                      position_value_dollars=VALUES(position_value_dollars),
                      realized_pnl_dollars=VALUES(realized_pnl_dollars),
                      unrealized_pnl_dollars=VALUES(unrealized_pnl_dollars),
                      equity_dollars=VALUES(equity_dollars),
                      peak_equity_dollars=VALUES(peak_equity_dollars),
                      drawdown_dollars=VALUES(drawdown_dollars),
                      raw_json=VALUES(raw_json)
                    """,
                    (
                        mark.replace(tzinfo=None),
                        model_name,
                        row["cash"],
                        row["position_value"],
                        row["realized"],
                        row["unrealized"],
                        row["equity"],
                        row["peak"],
                        row["drawdown"],
                        json.dumps(row),
                    ),
                )
            cur.execute(
                """
                INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                """,
                (
                    "sim_portfolio_20s_last_snapshot",
                    json.dumps({"snapshot_time_utc": mark.isoformat()}),
                    utc_now().replace(tzinfo=None),
                ),
            )
        except Exception as e:
            print(f"sim_portfolio_20s error at {mark.isoformat()}: {e}")
            try:
                conn.close()
            except Exception:
                pass
            # If reconnecting also fails, let it propagate so the outer loop
            # (see __main__ below) tears down and retries after a backoff,
            # instead of looping here against a connection we know is dead.
            conn = get_db_conn()
            cur = conn.cursor()
            print("sim_portfolio_20s: reconnected to database")


if __name__ == "__main__":
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f"[ERROR] sim_portfolio_20s updater crashed: {e}")
            time.sleep(5)
