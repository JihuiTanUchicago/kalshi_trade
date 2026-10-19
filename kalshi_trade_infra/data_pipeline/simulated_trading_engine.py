"""Simulated (paper) trading engine for the Kalshi 15-min BTC market.

Runs a fixed set of frozen models against live market_features_1m rows,
each with its own independent $STARTING_CAPITAL paper book (see sim_config.py)
so their forward performance can be compared fairly. All DB access lives in
sim_repository.py; this module owns the decision logic: which models to run,
how much to size a new position, when to force-close near expiry, and the
risk gate that pauses a model once its drawdown breaches the configured cap.
"""
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data_pipeline.binary_theory import theoretical_p_yes
from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.kalshi_fees import taker_fee_per_contract_dollars
from data_pipeline.modeling_features import (
    BASELINE_FEATURE_COLS,
    FEATURE_COLS,
    build_feature_vector,
    has_target,
)
from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
from data_pipeline.architecture.simulated_venue import SimulatedVenue
from data_pipeline.market_data import MarketFeed
from data_pipeline.sim_config import (
    BINARY_THEORY_EDGE_THRESHOLD,
    EDGE_THRESHOLD,
    FORCE_CLOSE_NEAR_EXPIRY_PRICE,
    HIGH_CONVICTION_EDGE_THRESHOLD,
    HOLD_1M_MODELS,
    HOLD_TO_SETTLEMENT_MODELS,
    LOGREG_L1_C,
    MAX_QTY,
    MIN_INSAMPLE_HOURS,
    MIN_SAMPLES_DEFAULT_RF,
    NEAR_EXPIRY_SEC,
    PRED_THRESHOLD,
    RF_PARAMS_DEFAULT,
    RF_PARAMS_SMALL,
    SimRiskSettings,
)
from data_pipeline.sim_repository import (
    reconcile_settled_sim_positions,
    close_existing_position,
    get_latest_drawdown_pct,
    get_live_cutoff_utc,
    get_model_equity,
    get_model_pause_state,
    get_open_position,
    get_sim_risk_settings,
    is_sim_recompute_in_progress,
    latest_feature_row,
    load_feature_rows,
    open_new_position,
    set_model_paused,
    upsert_equity,
    upsert_prediction,
)

FROZEN_MODELS = ("naive_logistic_baseline", "logistic", "random_forest")
# Research candidate (see sim_config.HIGH_CONVICTION_EDGE_THRESHOLD docstring):
# reuses random_forest's own estimator/probability output unchanged, but only
# trades when its edge clears a much higher bar. Not a separate trained
# model - see score_frozen_models(), which aliases its output to
# random_forest's, and EDGE_THRESHOLD_OVERRIDES below for its stricter bar.
HIGH_CONVICTION_MODELS = ("random_forest_high_conviction",)
# Research candidate (see sim_config.BINARY_THEORY_EDGE_THRESHOLD docstring):
# not a fitted model at all - a closed-form driftless-GBM probability from
# data_pipeline.binary_theory, computed fresh each tick in score_frozen_models().
# Validated with a hold-to-settlement exit style (see HOLD_TO_SETTLEMENT_MODELS),
# not the early-exit-on-signal-decay behavior every other model uses.
THEORY_MODELS = ("binary_theory_edge",)
ALL_MODELS = FROZEN_MODELS + HIGH_CONVICTION_MODELS + THEORY_MODELS
# Deliberately read from the same environment variables the live engine uses:
# a paper book run under a different execution policy is not a forecast of the
# live one. See data_pipeline/live_trading_engine.py.
SIM_ENTRY_CROSS_TICKS = int(os.getenv("KALSHI_ENTRY_CROSS_TICKS", "1"))
SIM_EXIT_CROSS_TICKS = int(os.getenv("KALSHI_EXIT_CROSS_TICKS", "2"))
SIM_MAX_ENTRY_SLIPPAGE = float(os.getenv("KALSHI_MAX_ENTRY_SLIPPAGE", "0.02"))
SIM_ORDER_MAX_ATTEMPTS = int(os.getenv("KALSHI_ORDER_MAX_ATTEMPTS", "3"))
SIM_MAX_QUOTE_AGE_SECONDS = float(os.getenv("KALSHI_MAX_QUOTE_AGE_SECONDS", "2.0"))

EDGE_THRESHOLD_OVERRIDES: Dict[str, float] = {
    "random_forest_high_conviction": HIGH_CONVICTION_EDGE_THRESHOLD,
    "binary_theory_edge": BINARY_THEORY_EDGE_THRESHOLD,
}


def should_close_position(model_name: str, prob: float, edge: float, edge_threshold: float = EDGE_THRESHOLD) -> bool:
    """1-minute-hold models (HOLD_1M_MODELS): always close after one tick.
    Hold-to-settlement models: never close early on signal decay (only
    near-expiry force-close or ticker rotation ends the position - both are
    handled elsewhere in process_model_tick/close_existing_position).
    Other models: symmetric threshold - buy >= PRED_THRESHOLD, sell < PRED_THRESHOLD."""
    if model_name in HOLD_1M_MODELS:
        return True
    if model_name in HOLD_TO_SETTLEMENT_MODELS:
        return False
    return (prob < PRED_THRESHOLD) or (edge <= edge_threshold)


@dataclass
class ModelOutput:
    prob: float
    train_rows: int
    test_rows: int
    brier: Optional[float]
    ll: Optional[float]
    rf_regime: Optional[str]


@dataclass
class FrozenModel:
    estimator: object
    train_rows: int
    test_rows: int
    brier: Optional[float]
    ll: Optional[float]
    rf_regime: Optional[str]


BASELINE_IDX = tuple(FEATURE_COLS.index(c) for c in BASELINE_FEATURE_COLS)


def next_minute_plus_delay(delay_seconds: int = 10) -> datetime:
    now = utc_now()
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1, seconds=delay_seconds)


def build_supervised(rows: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
    X = []
    y = []
    for i in range(len(rows) - 1):
        r = rows[i]
        nxt = rows[i + 1]
        if r["market_ticker"] != nxt["market_ticker"]:
            continue
        if not has_target(r) or not has_target(nxt):
            continue
        ask_t = r.get("yes_ask_dollars")
        bid_t1 = nxt.get("yes_bid_dollars")
        if ask_t is None or bid_t1 is None:
            continue
        x = build_feature_vector(r)
        target = 1 if float(bid_t1) > float(ask_t) else 0
        X.append(x)
        y.append(target)
    if not X:
        return np.empty((0, len(FEATURE_COLS))), np.empty((0,))
    return np.asarray(X, dtype=float), np.asarray(y, dtype=int)


def split_train_test(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(X)
    if n < 30:
        return X, y, np.empty((0, X.shape[1])), np.empty((0,))
    test_n = max(20, int(n * 0.2))
    test_n = min(test_n, max(1, n // 3))
    return X[:-test_n], y[:-test_n], X[-test_n:], y[-test_n:]


def choose_effective_cutoff(rows: List[Dict], requested_cutoff: Optional[datetime]) -> Optional[datetime]:
    if not rows:
        return requested_cutoff
    start_ts = rows[0].get("snapshot_minute_utc")
    end_ts = rows[-1].get("snapshot_minute_utc")
    if not start_ts or not end_ts:
        return requested_cutoff
    min_cutoff = start_ts + timedelta(hours=MIN_INSAMPLE_HOURS)
    cutoff = requested_cutoff or min_cutoff
    if cutoff < min_cutoff:
        cutoff = min_cutoff
    if cutoff > end_ts:
        cutoff = end_ts
    return cutoff


def _build_logistic_pipeline() -> Pipeline:
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                    penalty="l1",
                    solver="liblinear",
                    C=LOGREG_L1_C,
                ),
            ),
        ]
    )


def _build_rf(n_train: int) -> Tuple[RandomForestClassifier, str]:
    if n_train >= MIN_SAMPLES_DEFAULT_RF:
        return RandomForestClassifier(**RF_PARAMS_DEFAULT), "default"
    return RandomForestClassifier(**RF_PARAMS_SMALL), "small"


def _fit_and_score(estimator, train_X, train_y, test_X, test_y):
    estimator.fit(train_X, train_y)
    brier = None
    ll = None
    if len(test_X) > 0:
        probs = estimator.predict_proba(test_X)[:, 1]
        brier = float(brier_score_loss(test_y, probs))
        ll = float(log_loss(test_y, probs, labels=[0, 1]))
    return estimator, brier, ll


def fit_frozen_models(rows: List[Dict], cutoff_utc: Optional[datetime]) -> Dict[str, FrozenModel]:
    if cutoff_utc:
        train_rows = [r for r in rows if r.get("snapshot_minute_utc") and r["snapshot_minute_utc"] < cutoff_utc]
    else:
        split_idx = int(len(rows) * 0.7)
        train_rows = rows[: max(split_idx, 0)]
    X, y = build_supervised(train_rows)
    if len(X) < 20:
        raise RuntimeError(f"insufficient in-sample rows for frozen training: {len(X)}")
    train_X, train_y, test_X, test_y = split_train_test(X, y)
    if len(train_X) < 10:
        raise RuntimeError(f"insufficient frozen train rows: {len(train_X)}")

    log_pipe, log_brier, log_ll = _fit_and_score(_build_logistic_pipeline(), train_X, train_y, test_X, test_y)

    rf, rf_regime = _build_rf(len(train_X))
    rf, rf_brier, rf_ll = _fit_and_score(rf, train_X, train_y, test_X, test_y)

    base_test_X = test_X[:, BASELINE_IDX] if len(test_X) > 0 else test_X
    base_pipe, base_brier, base_ll = _fit_and_score(
        _build_logistic_pipeline(), train_X[:, BASELINE_IDX], train_y, base_test_X, test_y
    )

    return {
        "naive_logistic_baseline": FrozenModel(
            estimator=base_pipe, train_rows=len(train_X), test_rows=len(test_X),
            brier=base_brier, ll=base_ll, rf_regime="baseline_linear",
        ),
        "logistic": FrozenModel(
            estimator=log_pipe, train_rows=len(train_X), test_rows=len(test_X),
            brier=log_brier, ll=log_ll, rf_regime=None,
        ),
        "random_forest": FrozenModel(
            estimator=rf, train_rows=len(train_X), test_rows=len(test_X),
            brier=rf_brier, ll=rf_ll, rf_regime=rf_regime,
        ),
    }


def choose_qty(
    edge: float, notional_cap: Optional[float] = None, price: Optional[float] = None, edge_threshold: float = EDGE_THRESHOLD
) -> int:
    if edge <= edge_threshold:
        return 0
    scaled = int((edge / 0.03) * MAX_QTY)
    qty = max(1, min(MAX_QTY, scaled))
    if notional_cap is not None and price and price > 0:
        affordable = int(notional_cap / price)
        qty = max(0, min(qty, affordable))
    # Stricter net-of-fee gate at THIS order's actual per-contract taker fee (it
    # peaks at the 50c mid): the sim stops entering trades whose edge is positive
    # gross but negative once the fee is paid. Identical net-of-fee rule as
    # live_trading_engine.compute_buy_qty (lockstep). Sizing above is unchanged.
    if price and qty > 0 and edge - taker_fee_per_contract_dollars(qty, price) <= edge_threshold:
        return 0
    return qty


def decide_new_position(
    cur, model_name: str, now_row: Dict, prob: float, risk: SimRiskSettings, edge_threshold: float = EDGE_THRESHOLD
) -> Optional[Tuple[int, float]]:
    """Risk-aware sizing for a candidate new position. Returns (qty, entry_price) or None."""
    if get_open_position(cur, model_name):
        return None
    tte = now_row.get("time_to_expiry_sec")
    if tte is not None and float(tte) <= NEAR_EXPIRY_SEC:
        return None
    ask = float(now_row["yes_ask_dollars"] or 0.0)
    if ask <= 0 or prob < PRED_THRESHOLD:
        return None
    edge = prob - ask
    equity = get_model_equity(cur, model_name)
    if equity <= risk.min_equity_floor:
        return None
    notional_cap = equity * risk.max_position_fraction
    qty = choose_qty(edge, notional_cap=notional_cap, price=ask, edge_threshold=edge_threshold)
    if qty <= 0:
        return None
    return qty, ask


def process_model_tick(cur, model_name: str, latest: Dict, now_ts: datetime, out: ModelOutput, risk: SimRiskSettings, kernel=None, feed=None) -> Dict:
    """Manage one model's prediction/position/equity for a single tick.
    Returns a small summary dict for logging."""
    edge_threshold = EDGE_THRESHOLD_OVERRIDES.get(model_name, EDGE_THRESHOLD)
    signal = 1 if out.prob >= PRED_THRESHOLD else 0
    # Same split as the live engine: features from the bar, price from the
    # book. Scoring the edge against a one-minute-old ask is what made the
    # paper book and the account disagree.
    ask = float(latest.get("yes_ask_dollars") or 0.0)
    if feed is not None:
        live = feed.quote(latest["market_ticker"])
        if live is not None and live.tradable:
            ask = float(live.yes_ask)
            latest = dict(latest, yes_ask_dollars=ask, yes_bid_dollars=float(live.yes_bid))
    edge = out.prob - ask
    x_vec = np.asarray(build_feature_vector(latest), dtype=float)
    upsert_prediction(cur, now_ts, model_name, latest, x_vec, FEATURE_COLS, out, signal, edge)

    tte = latest.get("time_to_expiry_sec")
    near_expiry = tte is not None and float(tte) <= NEAR_EXPIRY_SEC
    should_close = should_close_position(model_name, out.prob, edge, edge_threshold) or near_expiry
    force_price = FORCE_CLOSE_NEAR_EXPIRY_PRICE if near_expiry else None

    had_position = get_open_position(cur, model_name) is not None
    realized = close_existing_position(
        cur, model_name, latest, now_ts, should_close_same_ticker=should_close,
        force_exit_price=force_price, kernel=kernel,
    )
    has_position_after = get_open_position(cur, model_name) is not None
    closed_this_tick = had_position and not has_position_after

    # Risk gate: refresh pause state before considering a new entry. Once
    # paused, a model stays paused until explicitly cleared - existing
    # positions still get managed/closed above, just no new risk is added.
    pause = get_model_pause_state(cur, model_name)
    if pause is None:
        drawdown_pct = get_latest_drawdown_pct(cur, model_name)
        if drawdown_pct is not None and drawdown_pct <= -risk.max_drawdown_pct:
            reason = f"drawdown {drawdown_pct:.1%} breached -{risk.max_drawdown_pct:.0%} cap"
            set_model_paused(cur, model_name, reason, now_ts)
            pause = {"paused_reason": reason}

    open_meta = None
    if not closed_this_tick and pause is None:
        decision = decide_new_position(cur, model_name, latest, out.prob, risk, edge_threshold)
        if decision:
            qty, entry_price = decision
            report = None
            if kernel is not None:
                report = kernel.execute(
                    TradeIntent(
                        action="buy", side="yes", ticker=latest["market_ticker"],
                        qty_contracts=qty, limit_price_dollars=entry_price,
                        model_name=model_name, now_ts=now_ts, metadata={"prob_yes": out.prob},
                    )
                )
            open_meta = open_new_position(
                cur, model_name, latest, now_ts, out.prob, edge, qty, entry_price, report=report
            )

    equity = upsert_equity(cur, now_ts, model_name, realized)
    return {
        "signal": signal,
        "edge": edge,
        "realized": realized,
        "open": bool(open_meta),
        "paused": pause is not None,
        "equity": equity,
    }


def score_frozen_models(frozen_models: Dict[str, FrozenModel], x_latest: np.ndarray, latest_row: Optional[Dict] = None) -> Dict[str, ModelOutput]:
    outputs = {}
    for model_name in FROZEN_MODELS:
        fm = frozen_models[model_name]
        px = x_latest if model_name != "naive_logistic_baseline" else x_latest[list(BASELINE_IDX)]
        p = float(fm.estimator.predict_proba([px])[0, 1])
        outputs[model_name] = ModelOutput(
            prob=p, train_rows=fm.train_rows, test_rows=fm.test_rows, brier=fm.brier, ll=fm.ll, rf_regime=fm.rf_regime,
        )
    # High-conviction variants reuse an existing model's probability output
    # unchanged (see EDGE_THRESHOLD_OVERRIDES) - they are a stricter entry/exit
    # filter on the same signal, not a separately trained model.
    outputs["random_forest_high_conviction"] = outputs["random_forest"]
    # Closed-form theory model: no fitting, computed fresh from the current
    # row's own spot/strike/vol/time-to-expiry. Falls back to a neutral 0.5
    # (no signal) if required inputs are missing, so it simply won't clear
    # any edge threshold rather than raising.
    theory_p = theoretical_p_yes(latest_row) if latest_row is not None else None
    outputs["binary_theory_edge"] = ModelOutput(
        prob=0.5 if theory_p is None else theory_p,
        train_rows=0, test_rows=0, brier=None, ll=None, rf_regime="theory",
    )
    return outputs


def _reload_frozen_models(cur) -> Tuple[Optional[Dict[str, FrozenModel]], Optional[datetime]]:
    rows = load_feature_rows(cur, limit=200000)
    requested_cutoff = get_live_cutoff_utc(cur)
    cutoff = choose_effective_cutoff(rows, requested_cutoff)
    try:
        frozen_models = fit_frozen_models(rows, cutoff)
    except Exception as e:
        print(f"sim engine waiting: frozen-train unavailable ({e})")
        return None, None
    print(
        "sim frozen models ready: "
        f"cutoff={cutoff.isoformat() if cutoff else 'none'} "
        f"log_train={frozen_models['logistic'].train_rows} "
        f"rf_train={frozen_models['random_forest'].train_rows} "
        f"rf_regime={frozen_models['random_forest'].rf_regime}"
    )
    if cutoff:
        cur.execute(
            """
            INSERT INTO collector_state (state_key, state_value, updated_at_utc)
            VALUES (%s,%s,%s)
            ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
            """,
            ("sim_live_cutoff_utc", json.dumps({"cutoff_utc": cutoff.isoformat()}), utc_now().replace(tzinfo=None)),
        )
    return frozen_models, cutoff


def _record_tick_snapshot(cur, now_ts: datetime, feature_minute, frozen_models: Dict[str, FrozenModel]) -> None:
    cur.execute(
        """
        INSERT INTO collector_state (state_key,state_value,updated_at_utc)
        VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
        """,
        (
            "sim_trading_last_snapshot",
            json.dumps(
                {
                    "snapshot_minute_utc": now_ts.isoformat(),
                    "feature_snapshot_minute_utc": str(feature_minute),
                    "frozen": True,
                    "train_rows": frozen_models["logistic"].train_rows,
                }
            ),
            utc_now().replace(tzinfo=None),
        ),
    )


def _is_conn_lost(e) -> bool:
    """True for a dropped/timed-out MySQL connection (errno 2006/2013) — the transient RDS/network
    failure the engine should recover from by reconnecting, not by crashing (mirrors the live engine)."""
    code = (getattr(e, "args", None) or [None])[0]
    return code in (2006, 2013) or "Lost connection" in str(e) or "gone away" in str(e)


def run_loop() -> None:
    conn = get_db_conn()
    cur = conn.cursor()
    # One execution policy, two venues. The kernel, the cross ticks, the edge
    # tolerance and the retry behaviour are identical to the live engine's -
    # only the submitter differs, so paper P&L is comparable to live P&L.
    feed = MarketFeed(max_quote_age_seconds=SIM_MAX_QUOTE_AGE_SECONDS)
    venue = SimulatedVenue(feed, max_quote_age_seconds=SIM_MAX_QUOTE_AGE_SECONDS)
    kernel = MarketableLimitKernel(
        venue, feed,
        entry_cross_ticks=SIM_ENTRY_CROSS_TICKS,
        exit_cross_ticks=SIM_EXIT_CROSS_TICKS,
        max_entry_slippage=SIM_MAX_ENTRY_SLIPPAGE,
        max_attempts=SIM_ORDER_MAX_ATTEMPTS,
        max_quote_age_seconds=SIM_MAX_QUOTE_AGE_SECONDS,
    )
    print("simulated trading engine started. Running minute-sharp (+10s).")
    print(
        "sim execution: marketable limit, entry_cross=%s exit_cross=%s max_slippage=%s attempts=%s"
        % (SIM_ENTRY_CROSS_TICKS, SIM_EXIT_CROSS_TICKS, SIM_MAX_ENTRY_SLIPPAGE, SIM_ORDER_MAX_ATTEMPTS)
    )
    frozen_models: Dict[str, FrozenModel] = {}
    last_processed_minute: Optional[datetime] = None
    while True:
        wake = next_minute_plus_delay(10)
        time.sleep(max(0.0, (wake - utc_now()).total_seconds()))
        now_ts = wake.replace(second=0, microsecond=0)
        try:
            # Pause sim writers while historical recompute is rebuilding tables.
            # Auto-resume when the guard flips back to false.
            if is_sim_recompute_in_progress(cur):
                if frozen_models:
                    print("sim engine pause: recompute in progress; will reload frozen models on resume")
                frozen_models = {}
                last_processed_minute = None
                continue

            if not frozen_models:
                frozen_models, _ = _reload_frozen_models(cur)
                if not frozen_models:
                    continue

            # A market that has expired cannot be sold, only booked. This has
            # to run before any exit is attempted, exactly as in the live engine.
            reconcile_settled_sim_positions(cur, now_ts)

            latest = latest_feature_row(cur)
            if not latest:
                print("sim engine waiting: no eligible model_features_1m row")
                continue

            feature_minute = latest["snapshot_minute_utc"]
            if last_processed_minute and feature_minute <= last_processed_minute:
                continue
            if not has_target(latest):
                print(f"sim engine waiting: missing target_btc_price at {now_ts.isoformat()}")
                continue

            risk = get_sim_risk_settings(cur)
            x_latest = np.asarray(build_feature_vector(latest), dtype=float)
            outputs = score_frozen_models(frozen_models, x_latest, latest_row=latest)

            for model_name in ALL_MODELS:
                out = outputs[model_name]
                summary = process_model_tick(cur, model_name, latest, now_ts, out, risk, kernel=kernel, feed=feed)
                print(
                    f"sim {model_name} t={now_ts.isoformat()} p={out.prob:.4f} signal={summary['signal']} "
                    f"edge={summary['edge']:.4f} realized={summary['realized']:.4f} open={summary['open']} "
                    f"paused={summary['paused']} equity={summary['equity']:.2f} rf_regime={out.rf_regime}"
                )

            last_processed_minute = feature_minute
            _record_tick_snapshot(cur, now_ts, feature_minute, frozen_models)
        except Exception as e:
            print(f"sim trading error at {now_ts.isoformat()}: {e}")
            if _is_conn_lost(e):
                # Transient DB connection drop: reconnect IN PLACE and continue to the next cycle
                # instead of crashing the process (which refits the frozen models from scratch).
                # The aborted cycle is not retried; next minute re-evaluates from fresh state.
                try:
                    conn.close()
                except Exception:
                    pass
                conn = get_db_conn()
                cur = conn.cursor()
                continue
            # Any non-connection error still tears down + restarts (unchanged recovery).
            raise


if __name__ == "__main__":
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f"[ERROR] simulated trading engine crashed: {e}")
            time.sleep(5)
