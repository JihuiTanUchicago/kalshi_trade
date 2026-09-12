import json
import sys
from datetime import datetime

import numpy as np

from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.sim_model_registry import build_custom_frozen_models, list_custom_models, mark_custom_model_status
from data_pipeline.simulated_trading_engine import (
    BASELINE_IDX,
    FROZEN_MODELS,
    PRED_THRESHOLD,
    ModelOutput,
    build_feature_vector,
    choose_effective_cutoff,
    close_existing_position,
    fit_frozen_models,
    get_live_cutoff_utc,
    has_target,
    load_feature_rows,
    open_new_position,
    should_close_position,
    upsert_equity,
    upsert_prediction,
)


def to_minute_ts(v) -> datetime:
    if isinstance(v, datetime):
        return v.replace(second=0, microsecond=0)
    return datetime.fromisoformat(str(v)).replace(second=0, microsecond=0)


def _set_backfill_flag(cur, value: bool) -> None:
    cur.execute(
        """
        INSERT INTO collector_state (state_key,state_value,updated_at_utc)
        VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
        """,
        ("sim_recompute_in_progress", json.dumps({"in_progress": value}), utc_now().replace(tzinfo=None)),
    )


def _next_pending_model(cur):
    cur.execute(
        """
        SELECT model_name
        FROM sim_models_registry
        WHERE is_active=1 AND status IN ('pending','running')
        ORDER BY CASE WHEN status='running' THEN 0 ELSE 1 END, updated_at_utc ASC, created_at_utc ASC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    return row["model_name"] if row else None


def _delete_model_rows(cur, model_name: str) -> None:
    for table in ("sim_positions", "sim_trades", "sim_equity_1m", "sim_model_predictions_1m", "sim_portfolio_20s"):
        cur.execute(f"DELETE FROM {table} WHERE model_name=%s", (model_name,))


def backfill_one_model(cur, model_name: str) -> int:
    all_cfg = {m["model_name"]: m for m in list_custom_models(cur, include_inactive=False)}
    cfg = all_cfg.get(model_name)
    if not cfg:
        raise RuntimeError(f"custom model {model_name} not found")
    rows = load_feature_rows(cur, limit=200000)
    if len(rows) < 30:
        raise RuntimeError("insufficient feature rows")
    cutoff = choose_effective_cutoff(rows, get_live_cutoff_utc(cur))
    bundles = build_custom_frozen_models([cfg], rows, cutoff)
    bundle = bundles[model_name]
    _delete_model_rows(cur, model_name)
    processed = 0
    for latest in rows:
        if not has_target(latest):
            continue
        now_ts = to_minute_ts(latest["snapshot_minute_utc"])
        x_latest = np.asarray(build_feature_vector(latest), dtype=float)
        px = x_latest[list(bundle.feature_idx)]
        prob = float(bundle.estimator.predict_proba([px])[0, 1])
        out = ModelOutput(
            prob=prob,
            train_rows=bundle.train_rows,
            test_rows=bundle.test_rows,
            brier=bundle.brier,
            ll=bundle.ll,
            rf_regime=bundle.rf_regime,
        )
        signal = 1 if out.prob >= PRED_THRESHOLD else 0
        edge = out.prob - float(latest.get("yes_ask_dollars") or 0.0)
        upsert_prediction(cur, now_ts, model_name, latest, out, signal, edge)
        should_close = should_close_position(model_name, out.prob, edge)
        cur.execute("SELECT 1 FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
        had_position = cur.fetchone() is not None
        realized = close_existing_position(cur, model_name, latest, now_ts, should_close_same_ticker=should_close)
        cur.execute("SELECT 1 FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
        has_position_after = cur.fetchone() is not None
        closed_this_tick = had_position and not has_position_after
        if not closed_this_tick:
            open_new_position(cur, model_name, latest, now_ts, out.prob)
        upsert_equity(cur, now_ts, model_name, realized)
        processed += 1
    return processed


def backfill_frozen_models() -> None:
    """Clear and replay all built-in frozen models (naive_logistic_baseline, logistic, random_forest)
    using the hysteresis exit rule. Pauses the sim engine during recompute."""
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            _set_backfill_flag(cur, True)
            conn.commit()
            print("Recompute flag set — sim engine will pause.")

            rows = load_feature_rows(cur, limit=200000)
            print(f"Loaded {len(rows)} feature rows.")
            if len(rows) < 30:
                raise RuntimeError("insufficient feature rows for frozen model backfill")

            cutoff = choose_effective_cutoff(rows, get_live_cutoff_utc(cur))
            print(f"Cutoff UTC: {cutoff}")

            frozen = fit_frozen_models(rows, cutoff)
            print(
                f"Models fitted. logistic train={frozen['logistic'].train_rows}, "
                f"rf train={frozen['random_forest'].train_rows}"
            )

            for model_name in FROZEN_MODELS:
                _delete_model_rows(cur, model_name)
                print(f"Cleared old data for {model_name}.")
            conn.commit()

            processed = 0
            for latest in rows:
                if not has_target(latest):
                    continue
                now_ts = to_minute_ts(latest["snapshot_minute_utc"])
                x_latest = np.asarray(build_feature_vector(latest), dtype=float)

                for model_name in FROZEN_MODELS:
                    fm = frozen[model_name]
                    px = x_latest if model_name != "naive_logistic_baseline" else x_latest[list(BASELINE_IDX)]
                    prob = float(fm.estimator.predict_proba([px])[0, 1])
                    out = ModelOutput(
                        prob=prob,
                        train_rows=fm.train_rows,
                        test_rows=fm.test_rows,
                        brier=fm.brier,
                        ll=fm.ll,
                        rf_regime=fm.rf_regime,
                    )
                    signal = 1 if out.prob >= PRED_THRESHOLD else 0
                    edge = out.prob - float(latest.get("yes_ask_dollars") or 0.0)
                    upsert_prediction(cur, now_ts, model_name, latest, out, signal, edge)
                    should_close = should_close_position(model_name, out.prob, edge)
                    cur.execute("SELECT 1 FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
                    had_position = cur.fetchone() is not None
                    realized = close_existing_position(cur, model_name, latest, now_ts, should_close_same_ticker=should_close)
                    cur.execute("SELECT 1 FROM sim_positions WHERE model_name=%s LIMIT 1", (model_name,))
                    has_position_after = cur.fetchone() is not None
                    closed_this_tick = had_position and not has_position_after
                    if not closed_this_tick:
                        open_new_position(cur, model_name, latest, now_ts, out.prob)
                    upsert_equity(cur, now_ts, model_name, realized)

                processed += 1
                if processed % 500 == 0:
                    conn.commit()
                    print(f"  processed {processed} rows...")

            conn.commit()
            print(f"Backfill done. Processed {processed} rows.")

            for model_name in FROZEN_MODELS:
                cur.execute(
                    "SELECT COUNT(*), MAX(cumulative_pnl_dollars) FROM sim_equity_1m WHERE model_name=%s",
                    (model_name,),
                )
                r = cur.fetchone()
                print(f"  {model_name}: {r['COUNT(*)']} equity rows, final_pnl={r['MAX(cumulative_pnl_dollars)']}")

    finally:
        with conn.cursor() as cur:
            _set_backfill_flag(cur, False)
        conn.commit()
        conn.close()
        print("Recompute flag cleared — sim engine will resume.")


def run_pending_jobs() -> None:
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            _set_backfill_flag(cur, True)
            conn.commit()
            while True:
                model_name = _next_pending_model(cur)
                if not model_name:
                    break
                mark_custom_model_status(cur, model_name, "running", utc_now().replace(tzinfo=None))
                conn.commit()
                try:
                    processed = backfill_one_model(cur, model_name)
                    mark_custom_model_status(cur, model_name, "ready", utc_now().replace(tzinfo=None))
                    cur.execute(
                        """
                        INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                        VALUES (%s,%s,%s)
                        ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                        """,
                        (
                            "sim_custom_backfill_last_run",
                            json.dumps({"model_name": model_name, "processed_minutes": processed}),
                            utc_now().replace(tzinfo=None),
                        ),
                    )
                    conn.commit()
                except Exception as e:
                    mark_custom_model_status(cur, model_name, "error", utc_now().replace(tzinfo=None), last_error=str(e)[:2000])
                    conn.commit()
    finally:
        with conn.cursor() as cur:
            _set_backfill_flag(cur, False)
        conn.commit()
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "frozen":
        backfill_frozen_models()
    else:
        run_pending_jobs()
