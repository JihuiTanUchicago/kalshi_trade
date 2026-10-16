"""One-shot full rebuild of the sim tables from historical model_features_1m
rows. Reuses simulated_trading_engine.process_model_tick so the replay
follows the exact same rules (risk gate, near-expiry force-close, sizing) as
the live paper-trading loop - this used to hand-roll its own copy of that
logic and silently computed unused walk-forward outputs on every row."""
import json
from datetime import datetime

import numpy as np

from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.modeling_features import build_feature_vector
from data_pipeline.sim_repository import get_live_cutoff_utc, get_sim_risk_settings, load_feature_rows
from data_pipeline.simulated_trading_engine import (
    ALL_MODELS,
    choose_effective_cutoff,
    fit_frozen_models,
    has_target,
    process_model_tick,
    score_frozen_models,
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
    cur.execute("DELETE FROM sim_model_state")


def recompute() -> None:
    conn = get_db_conn()
    cutoff = None
    processed = 0
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
            risk = get_sim_risk_settings(cur)
            reset_sim_tables(cur)

            for latest in rows:
                if not has_target(latest):
                    continue
                now_ts = to_minute_ts(latest["snapshot_minute_utc"])
                x_latest = np.asarray(build_feature_vector(latest), dtype=float)
                outputs = score_frozen_models(frozen, x_latest, latest_row=latest)
                for model_name in ALL_MODELS:
                    process_model_tick(cur, model_name, latest, now_ts, outputs[model_name], risk)
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
