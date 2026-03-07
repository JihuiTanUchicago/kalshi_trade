import json
from datetime import datetime

import numpy as np

from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.simulated_trading_engine import (
    FEATURE_COLS,
    MODELS,
    build_supervised,
    close_existing_position,
    coalesce_float,
    load_feature_rows,
    open_new_position,
    split_train_test,
    train_logistic,
    train_rf,
    upsert_equity,
    upsert_prediction,
)


def to_minute_ts(v) -> datetime:
    if isinstance(v, datetime):
        return v.replace(second=0, microsecond=0)
    return datetime.fromisoformat(str(v)).replace(second=0, microsecond=0)


def reset_sim_tables(cur) -> None:
    cur.execute("DELETE FROM sim_positions")
    cur.execute("DELETE FROM sim_trades")
    cur.execute("DELETE FROM sim_equity_1m")
    cur.execute("DELETE FROM sim_model_predictions_1m")
    cur.execute("DELETE FROM sim_portfolio_20s")


def recompute() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        rows = load_feature_rows(cur, limit=200000)
        if len(rows) < 30:
            print(f"[WARN] insufficient model_features_1m rows: {len(rows)}")
            return

        reset_sim_tables(cur)
        processed = 0

        # Rolling replay over historical model_feature rows.
        for i in range(21, len(rows)):
            subset = rows[: i + 1]
            latest = subset[-1]
            now_ts = to_minute_ts(latest["snapshot_minute_utc"])

            X, y = build_supervised(subset)
            if len(X) < 20:
                continue
            train_X, train_y, test_X, test_y = split_train_test(X, y)
            if len(train_X) < 10:
                continue

            x_latest = np.asarray([coalesce_float(latest.get(c)) for c in FEATURE_COLS], dtype=float)
            outputs = {
                "logistic": train_logistic(train_X, train_y, test_X, test_y, x_latest),
                "random_forest": train_rf(train_X, train_y, test_X, test_y, x_latest),
            }

            for model_name in MODELS:
                out = outputs[model_name]
                signal = 1 if out.prob >= 0.55 else 0
                edge = out.prob - float(latest.get("yes_ask_dollars") or 0.0)
                upsert_prediction(cur, now_ts, model_name, latest, out, signal, edge)
                realized = close_existing_position(cur, model_name, latest, now_ts)
                open_new_position(cur, model_name, latest, now_ts, out.prob)
                upsert_equity(cur, now_ts, model_name, realized)

            processed += 1

        cur.execute(
            """
            INSERT INTO collector_state (state_key,state_value,updated_at_utc)
            VALUES (%s,%s,%s)
            ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
            """,
            (
                "sim_recompute_last_run",
                json.dumps({"processed_minutes": processed, "feature_rows": len(rows)}),
                utc_now().replace(tzinfo=None),
            ),
        )
    conn.close()
    print(f"[OK] sim recompute complete: processed_minutes={processed}")


if __name__ == "__main__":
    recompute()
