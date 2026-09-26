"""Tests for the Portfolio Manager scorecards built by dashboard_server.

The panel prints equity and total PnL on the same card, so the two must come
from the same source of truth: equity used to be read from the latest
sim_portfolio_20s snapshot, which is written by a separate process and goes
stale while total_pnl keeps moving.
"""
import pytest

from data_pipeline.dashboard_server import build_scorecards
from data_pipeline.sim_config import STARTING_CAPITAL


def _score_row(model_name, total_pnl, closed_trades=10, paused=False):
    return {
        "model_name": model_name,
        "closed_trades": closed_trades,
        "total_pnl": total_pnl,
        "avg_trade_pnl": (total_pnl / closed_trades) if closed_trades else 0.0,
        "win_rate": 0.5,
        "paused": paused,
        "paused_reason": "drawdown breach" if paused else None,
    }


def _open_position(model_name, qty, entry, mark):
    return {
        "model_name": model_name,
        "market_ticker": "TICK",
        "qty_contracts": qty,
        "entry_price": entry,
        "mark_bid": mark,
        "unrealized_pnl": (mark - entry) * qty,
        "opened_at_utc": "2026-03-12 00:00:00",
    }


def _rec(model_name, paused):
    return {"status": "paused" if paused else "promising", "label": model_name}


def test_equity_reconciles_with_total_pnl_and_open_position():
    cards = build_scorecards(
        {"alpha": _score_row("alpha", 521.66, closed_trades=376)},
        [_open_position("alpha", qty=10, entry=0.40, mark=0.55)],
        {},
        _rec,
    )

    assert len(cards) == 1
    card = cards[0]
    assert card["unrealized_pnl"] == pytest.approx(1.5)
    assert card["equity"] == pytest.approx(STARTING_CAPITAL + 521.66 + 1.5)
    assert card["return_pct"] == pytest.approx(((card["equity"] / STARTING_CAPITAL) - 1.0) * 100.0)
    assert card["position_value"] == pytest.approx(5.5)
    assert card["recommendation"] == {"status": "promising", "label": "alpha"}


def test_flat_model_equity_is_starting_capital_plus_pnl():
    cards = build_scorecards(
        {"beta": _score_row("beta", -719.46, closed_trades=8394, paused=True)},
        [],
        {"beta": {"paused_reason": "drawdown breach"}},
        _rec,
    )

    card = cards[0]
    assert card["unrealized_pnl"] == pytest.approx(0.0)
    assert card["position_value"] == pytest.approx(0.0)
    assert card["equity"] == pytest.approx(STARTING_CAPITAL - 719.46)
    assert card["recommendation"] == {"status": "paused", "label": "beta"}


def test_model_with_open_position_but_no_closed_trades_still_gets_a_card():
    cards = build_scorecards(
        {},
        [_open_position("gamma", qty=4, entry=0.50, mark=0.45)],
        {},
        _rec,
    )

    card = cards[0]
    assert card["model_name"] == "gamma"
    assert card["closed_trades"] == 0
    assert card["total_pnl"] == 0.0
    assert card["win_rate"] is None
    assert card["equity"] == pytest.approx(STARTING_CAPITAL - 0.2)
    assert card["paused"] is False


def test_paused_state_is_carried_onto_a_model_with_no_trades_yet():
    cards = build_scorecards(
        {},
        [_open_position("delta", qty=1, entry=0.50, mark=0.50)],
        {"delta": {"paused_reason": "drawdown -30% breached"}},
        _rec,
    )

    card = cards[0]
    assert card["paused"] is True
    assert card["paused_reason"] == "drawdown -30% breached"
    assert card["equity"] == pytest.approx(STARTING_CAPITAL)


def test_cards_are_ordered_by_model_name():
    cards = build_scorecards(
        {"zeta": _score_row("zeta", 1.0), "alpha": _score_row("alpha", 2.0)},
        [_open_position("mid", qty=1, entry=0.5, mark=0.5)],
        {},
        _rec,
    )

    assert [c["model_name"] for c in cards] == ["alpha", "mid", "zeta"]


def test_score_map_rows_are_not_mutated():
    row = _score_row("alpha", 10.0)
    build_scorecards({"alpha": row}, [], {}, _rec)

    assert "equity" not in row
