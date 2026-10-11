"""Tests for the sim engine's decision logic: position sizing, near-expiry
force-close, and the drawdown risk gate. Uses FakeCursor (see conftest.py)
instead of a live database - this is exactly what the Phase 3 repository
extraction was for."""
from datetime import datetime, timedelta

from data_pipeline.kalshi_fees import taker_fee_dollars
from data_pipeline.sim_config import STARTING_CAPITAL, SimRiskSettings
from data_pipeline.simulated_trading_engine import ModelOutput, process_model_tick


def _row(ticker, ask, tte):
    return {"market_ticker": ticker, "yes_ask_dollars": ask, "time_to_expiry_sec": tte}


def _strong_signal():
    return ModelOutput(prob=0.9, train_rows=100, test_rows=20, brier=0.1, ll=0.2, rf_regime="default")


def test_open_position_respects_notional_cap(fake_cursor):
    risk = SimRiskSettings(max_position_fraction=0.20, max_drawdown_pct=0.30, min_equity_floor=10.0)
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    summary = process_model_tick(fake_cursor, "random_forest", _row("TICK-1", 0.50, 500), now_ts, _strong_signal(), risk)

    assert summary["open"] is True
    pos = fake_cursor.sim_positions["random_forest"]
    notional = pos["qty_contracts"] * pos["entry_price_dollars"]
    cap = STARTING_CAPITAL * risk.max_position_fraction
    assert notional <= cap + 1e-9


def test_near_expiry_marks_an_unsellable_position_at_zero(fake_cursor):
    risk = SimRiskSettings()
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    process_model_tick(fake_cursor, "random_forest", _row("TICK-1", 0.50, 500), now_ts, _strong_signal(), risk)
    entry_px = fake_cursor.sim_positions["random_forest"]["entry_price_dollars"]

    # Next tick: near expiry with an empty bid ladder. There is no bid, so the
    # position cannot be sold at any price. This used to be marked at $0.99 -
    # assumed to win - which is precisely the illiquid case where the live
    # engine gets nothing: on 2026-09-27 six consecutive exit orders on such a
    # contract were cancelled and it settled at $0.00.
    fake_cursor.forward_quotes["TICK-1"] = 0.0
    summary = process_model_tick(
        fake_cursor, "random_forest", _row("TICK-1", 0.50, 30), now_ts + timedelta(minutes=1), _strong_signal(), risk
    )

    assert "random_forest" not in fake_cursor.sim_positions
    closed = [t for t in fake_cursor.sim_trades if t["status"] == "closed"][0]
    assert closed["exit_price_dollars"] == 0.0
    qty = closed["qty_contracts"]
    fees = taker_fee_dollars(qty, entry_px) + taker_fee_dollars(qty, 0.0)
    assert closed["pnl_dollars"] == (0.0 - entry_px) * qty - fees
    assert summary["realized"] == closed["pnl_dollars"]


def test_sim_pnl_is_net_of_taker_fees_on_both_legs(fake_cursor):
    """Paper P&L must be comparable to the live column, which is necessarily
    net. Recording gross overstated random_forest_high_conviction by $154 on
    $469 of reported profit."""
    risk = SimRiskSettings()
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    process_model_tick(fake_cursor, "random_forest", _row("TICK-1", 0.50, 500), now_ts, _strong_signal(), risk)
    pos = fake_cursor.sim_positions["random_forest"]
    entry_px, qty = pos["entry_price_dollars"], pos["qty_contracts"]

    fake_cursor.forward_quotes["TICK-1"] = 0.60
    process_model_tick(
        fake_cursor, "random_forest", _row("TICK-1", 0.50, 400), now_ts + timedelta(minutes=1),
        ModelOutput(prob=0.1, train_rows=0, test_rows=0, brier=None, ll=None, rf_regime="rf"), risk,
    )
    closed = [t for t in fake_cursor.sim_trades if t["status"] == "closed"][0]
    gross = (0.60 - entry_px) * qty
    fees = taker_fee_dollars(qty, entry_px) + taker_fee_dollars(qty, 0.60)
    assert fees > 0
    assert closed["pnl_dollars"] == gross - fees
    assert closed["pnl_dollars"] < gross


def test_drawdown_breach_pauses_model_and_blocks_new_entries(fake_cursor):
    risk = SimRiskSettings(max_position_fraction=0.20, max_drawdown_pct=0.30, min_equity_floor=10.0)
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    # Peak cumulative PnL was 0 (starting capital); now down -40 => -40% drawdown > -30% cap.
    fake_cursor.sim_equity_1m["random_forest"] = [
        {"cumulative_pnl_dollars": 0.0, "closed_trades_count": 0},
        {"cumulative_pnl_dollars": -40.0, "closed_trades_count": 3},
    ]

    summary = process_model_tick(fake_cursor, "random_forest", _row("TICK-1", 0.50, 500), now_ts, _strong_signal(), risk)

    assert summary["paused"] is True
    assert summary["open"] is False
    assert fake_cursor.sim_model_state["random_forest"]["paused"] == 1


def test_paused_model_stays_paused_without_explicit_clear(fake_cursor):
    risk = SimRiskSettings(max_drawdown_pct=0.30)
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    fake_cursor.sim_equity_1m["random_forest"] = [
        {"cumulative_pnl_dollars": 0.0, "closed_trades_count": 0},
        {"cumulative_pnl_dollars": -40.0, "closed_trades_count": 3},
    ]
    process_model_tick(fake_cursor, "random_forest", _row("TICK-1", 0.50, 500), now_ts, _strong_signal(), risk)

    # Drawdown "recovers" on paper, but the model must not silently auto-resume.
    fake_cursor.sim_equity_1m["random_forest"].append({"cumulative_pnl_dollars": -5.0, "closed_trades_count": 3})
    summary = process_model_tick(
        fake_cursor, "random_forest", _row("TICK-1", 0.50, 500), now_ts + timedelta(minutes=1), _strong_signal(), risk
    )

    assert summary["paused"] is True
    assert summary["open"] is False


def test_no_double_open_while_position_held(fake_cursor):
    risk = SimRiskSettings()
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    process_model_tick(fake_cursor, "random_forest", _row("TICK-1", 0.50, 500), now_ts, _strong_signal(), risk)
    process_model_tick(
        fake_cursor, "random_forest", _row("TICK-1", 0.50, 440), now_ts + timedelta(minutes=1), _strong_signal(), risk
    )

    assert len(fake_cursor.sim_positions) == 1
    assert len([t for t in fake_cursor.sim_trades if t["status"] == "open"]) == 1


def test_high_conviction_variant_requires_larger_edge_than_base_model(fake_cursor):
    risk = SimRiskSettings()
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    # edge = 0.9 - 0.80 = 0.10: clears the base EDGE_THRESHOLD (0.01) but not
    # HIGH_CONVICTION_EDGE_THRESHOLD (0.17).
    row = _row("TICK-1", ask=0.80, tte=500)
    summary_base = process_model_tick(fake_cursor, "random_forest", row, now_ts, _strong_signal(), risk)
    assert summary_base["open"] is True

    summary_hc = process_model_tick(fake_cursor, "random_forest_high_conviction", row, now_ts, _strong_signal(), risk)
    assert summary_hc["open"] is False


def test_high_conviction_variant_opens_on_large_edge(fake_cursor):
    risk = SimRiskSettings()
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    # edge = 0.9 - 0.50 = 0.40: clears HIGH_CONVICTION_EDGE_THRESHOLD (0.17).
    row = _row("TICK-1", ask=0.50, tte=500)
    summary_hc = process_model_tick(fake_cursor, "random_forest_high_conviction", row, now_ts, _strong_signal(), risk)
    assert summary_hc["open"] is True


def test_hold_to_settlement_model_does_not_close_on_signal_decay(fake_cursor):
    risk = SimRiskSettings()
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    strong = ModelOutput(prob=0.9, train_rows=0, test_rows=0, brier=None, ll=None, rf_regime="theory")
    weak = ModelOutput(prob=0.1, train_rows=0, test_rows=0, brier=None, ll=None, rf_regime="theory")

    # Open with a strong signal (edge = 0.9-0.50 = 0.40 clears BINARY_THEORY_EDGE_THRESHOLD).
    summary1 = process_model_tick(fake_cursor, "binary_theory_edge", _row("TICK-1", ask=0.50, tte=500), now_ts, strong, risk)
    assert summary1["open"] is True

    # Next tick: signal has completely flipped (prob=0.1), same ticker, still
    # plenty of time to expiry - a normal model would close here, but this
    # model must hold regardless (only near-expiry or rotation ends it).
    summary2 = process_model_tick(
        fake_cursor, "binary_theory_edge", _row("TICK-1", ask=0.50, tte=440), now_ts + timedelta(minutes=1), weak, risk
    )
    assert "binary_theory_edge" in fake_cursor.sim_positions, "hold-to-settlement model closed early on signal decay"
    assert summary2["realized"] == 0.0


def test_hold_to_settlement_model_still_force_closes_near_expiry(fake_cursor):
    risk = SimRiskSettings()
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    strong = ModelOutput(prob=0.9, train_rows=0, test_rows=0, brier=None, ll=None, rf_regime="theory")

    process_model_tick(fake_cursor, "binary_theory_edge", _row("TICK-1", ask=0.50, tte=500), now_ts, strong, risk)
    assert "binary_theory_edge" in fake_cursor.sim_positions

    summary2 = process_model_tick(
        fake_cursor, "binary_theory_edge", _row("TICK-1", ask=0.50, tte=30), now_ts + timedelta(minutes=1), strong, risk
    )
    assert "binary_theory_edge" not in fake_cursor.sim_positions, "should still force-close near expiry"
    closed = [t for t in fake_cursor.sim_trades if t["status"] == "closed"][0]
    # No bid at all near expiry means the position cannot be sold. It used to
    # be marked at $0.99 - i.e. assumed to win - which is the optimism that
    # made the paper book disagree with the live account on exactly the
    # illiquid contracts where live got nothing.
    assert closed["exit_price_dollars"] == 0.0


def test_equity_floor_blocks_new_entries(fake_cursor):
    risk = SimRiskSettings(min_equity_floor=10.0)
    now_ts = datetime(2026, 1, 1, 12, 0, 0)
    # Simulate a model that has already lost almost everything via closed trades.
    fake_cursor.sim_trades.append(
        dict(model_name="random_forest", market_ticker="OLD", status="closed", pnl_dollars=-(STARTING_CAPITAL - 5.0))
    )
    summary = process_model_tick(fake_cursor, "random_forest", _row("TICK-1", 0.50, 500), now_ts, _strong_signal(), risk)
    assert summary["open"] is False
