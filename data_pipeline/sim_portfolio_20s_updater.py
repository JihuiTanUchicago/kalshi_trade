import json
import time
from datetime import datetime, timedelta
from typing import Dict, List

from data_pipeline.common import get_db_conn, utc_now

BASE_MODELS = (
    "naive_logistic_baseline",
    "logistic",
    "random_forest",
    "walk_forward_logistic",
    "walk_forward_random_forest",
)
STARTING_CAPITAL = 100.0


def is_sim_recompute_in_progress(cur) -> bool:
    cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_recompute_in_progress' LIMIT 1")
    row = cur.fetchone()
    if not row:
        return False
    sv = row.get("state_value")
    if isinstance(sv, dict):
        return bool(sv.get("in_progress"))
    if isinstance(sv, str):
        try:
            j = json.loads(sv)
            if isinstance(j, dict):
                return bool(j.get("in_progress"))
        except Exception:
            return False
    return False


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


def runtime_models(cur) -> List[str]:
    models = list(BASE_MODELS)
    try:
        cur.execute(
            """
            SELECT model_name
            FROM sim_models_registry
            WHERE is_active=1 AND status='ready'
            ORDER BY created_at_utc ASC, model_name ASC
            """
        )
        for r in cur.fetchall():
            model_name = str(r["model_name"])
            if model_name not in models:
                models.append(model_name)
    except Exception:
        # If registry table is not initialized yet, keep base models running.
        pass
    return models


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
    with conn.cursor() as cur:
        print("sim portfolio 20s updater started.")
        while True:
            mark = next_20s_mark()
            time.sleep(max(0.0, (mark - utc_now()).total_seconds()))
            try:
                # Avoid writing while full sim recompute is rebuilding sim tables.
                if is_sim_recompute_in_progress(cur):
                    continue
                for model_name in runtime_models(cur):
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


if __name__ == "__main__":
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f"[ERROR] sim_portfolio_20s updater crashed: {e}")
            time.sleep(5)
