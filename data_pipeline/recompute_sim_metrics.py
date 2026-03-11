import json
from datetime import datetime

import numpy as np

from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.simulated_trading_engine import (
    ALL_MODELS,
    BASELINE_IDX,
    EDGE_THRESHOLD,
    FROZEN_MODELS,
    ModelOutput,
    PRED_THRESHOLD,
    train_walk_forward_outputs,
    build_feature_vector,
    close_existing_position,
    choose_effective_cutoff,
    fit_frozen_models,
    get_live_cutoff_utc,
    has_target,
    load_feature_rows,
    open_new_position,
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
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                """,
                ("sim_recompute_in_progress", json.dumps({"in_progress": True}), utc_now().replace(tzinfo=None)),
            )
            conn.commit()
            rows = load_feature_rows(cur, limit=200000)
            if len(rows) < 30:
                print(f"[WARN] insufficient model_features_1m rows: {len(rows)}")
                return

            cutoff = choose_effective_cutoff(rows, get_live_cutoff_utc(cur))
            frozen = fit_frozen_models(rows, cutoff)
            reset_sim_tables(cur)
            processed = 0

            for latest in rows:
                if not has_target(latest):
                    continue
                now_ts = to_minute_ts(latest["snapshot_minute_utc"])
                x_latest = np.asarray(build_feature_vector(latest), dtype=float)

                outputs = {}
                for model_name in FROZEN_MODELS:
                    fm = frozen[model_name]
                    px = x_latest if model_name != "naive_logistic_baseline" else x_latest[list(BASELINE_IDX)]
                    prob = float(fm.estimator.predict_proba([px])[0, 1])
                    outputs[model_name] = ModelOutput(
                        prob=prob,
                        train_rows=fm.train_rows,
                        test_rows=fm.test_rows,
                        brier=fm.brier,
                        ll=fm.ll,
                        rf_regime=fm.rf_regime,
                    )

                outputs.update(train_walk_forward_outputs(rows, latest["snapshot_minute_utc"], x_latest))

                for model_name in ALL_MODELS:
                    out = outputs[model_name]
                    signal = 1 if out.prob >= PRED_THRESHOLD else 0
                    edge = out.prob - float(latest.get("yes_ask_dollars") or 0.0)
                    upsert_prediction(cur, now_ts, model_name, latest, out, signal, edge)
                    should_close = (signal == 0) or (edge <= EDGE_THRESHOLD)
                    cur.execute("SELECT 1 FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
                    had_position = cur.fetchone() is not None
                    realized = close_existing_position(
                        cur,
                        model_name,
                        latest,
                        now_ts,
                        should_close_same_ticker=should_close,
                    )
                    cur.execute("SELECT 1 FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
                    has_position_after = cur.fetchone() is not None
                    closed_this_tick = had_position and not has_position_after
                    if not closed_this_tick:
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
                    json.dumps({"processed_minutes": processed, "feature_rows": len(rows), "frozen": True, "cutoff_utc": str(cutoff) if cutoff else None}),
                    utc_now().replace(tzinfo=None),
                ),
            )
            if cutoff:
                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES (%s,%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    ("sim_live_cutoff_utc", json.dumps({"cutoff_utc": cutoff.isoformat()}), utc_now().replace(tzinfo=None)),
                )
        print(f"[OK] sim recompute complete: processed_minutes={processed}")
    finally:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                """,
                ("sim_recompute_in_progress", json.dumps({"in_progress": False}), utc_now().replace(tzinfo=None)),
            )
        conn.commit()
        conn.close()


if __name__ == "__main__":
    recompute()
