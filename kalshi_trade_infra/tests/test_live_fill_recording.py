"""open_live_position / close_live_position must follow the fill.

The 2026-09-27 incident in one sentence: an unfilled order became a position
in the book, and the sell that later "closed" it opened a real short instead.
"""
from datetime import datetime

import pytest

from data_pipeline.architecture.execution_kernel import DummyExecutionKernel
from data_pipeline.live_trading_engine import close_live_position, open_live_position
from tests.test_execution_fills import FILLED, UNFILLED

NOW = datetime(2026, 9, 27, 7, 1)
TICKER = "KXBTC15M-26SEP270315-15"
MODEL = "random_forest_high_conviction"


class LiveCursor:
    """The live_* query shapes these two functions use, nothing more."""

    def __init__(self):
        self.live_orders = []
        self.live_positions = {}  # (model, ticker) -> row
        self.live_trades = []
        self._last = None

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self._last = None
        if s.startswith("INSERT INTO live_orders"):
            self.live_orders.append(params)
        elif s.startswith("INSERT INTO live_positions"):
            model, ticker, opened, qty, px, raw = params
            self.live_positions[(model, ticker)] = dict(
                model_name=model, market_ticker=ticker, opened_at_utc=opened,
                qty_contracts=qty, entry_price_dollars=px, raw_json=raw,
            )
        elif s.startswith("INSERT INTO live_trades"):
            opened, ticker, model, qty, px, raw = params
            self.live_trades.append(dict(
                opened_at_utc=opened, market_ticker=ticker, model_name=model,
                qty_contracts=qty, entry_price_dollars=px, status="open",
                exit_price_dollars=None, pnl_dollars=None, raw_json=raw,
            ))
        elif s.startswith("SELECT * FROM live_positions"):
            row = self.live_positions.get((params[0], params[1]))
            self._last = [row] if row else []
        elif s.startswith("UPDATE live_trades"):
            closed_at, exit_px, pnl, qty, ticker, model = params
            for t in reversed(self.live_trades):
                if t["market_ticker"] == ticker and t["model_name"] == model and t["status"] == "open":
                    t.update(closed_at_utc=closed_at, exit_price_dollars=exit_px,
                             pnl_dollars=pnl, qty_contracts=qty, status="closed")
                    break
        elif s.startswith("UPDATE live_positions SET qty_contracts"):
            qty, model, ticker = params
            self.live_positions[(model, ticker)]["qty_contracts"] = qty
        elif s.startswith("DELETE FROM live_positions"):
            self.live_positions.pop((params[0], params[1]), None)
        else:
            raise AssertionError("unhandled query: " + s[:90])

    def fetchone(self):
        return self._last[0] if self._last else None


def kernel_for(resp):
    return DummyExecutionKernel(lambda *a: {"client_order_id": resp.get("client_order_id"),
                                            "body": {}, "resp": resp})


def test_unfilled_buy_records_no_position_and_no_trade():
    cur = LiveCursor()
    open_live_position(cur, kernel_for(UNFILLED), MODEL, TICKER, 24, 0.41, 0.72, NOW)
    assert cur.live_positions == {}
    assert cur.live_trades == []
    # The attempt is still audited.
    assert len(cur.live_orders) == 1


def test_filled_buy_records_the_real_price_not_the_limit():
    cur = LiveCursor()
    open_live_position(cur, kernel_for(FILLED), MODEL, TICKER, 18, 0.82, 0.9, NOW)
    pos = cur.live_positions[(MODEL, TICKER)]
    assert pos["qty_contracts"] == 18
    assert pos["entry_price_dollars"] == pytest.approx(0.74)
    assert cur.live_trades[0]["entry_price_dollars"] == pytest.approx(0.74)


def test_partial_buy_records_only_the_filled_quantity():
    cur = LiveCursor()
    resp = dict(FILLED, fill_count="7.00", remaining_count="11.00")
    open_live_position(cur, kernel_for(resp), MODEL, TICKER, 18, 0.82, 0.9, NOW)
    assert cur.live_positions[(MODEL, TICKER)]["qty_contracts"] == 7


def test_close_cannot_run_without_a_position():
    """The naked sell that created the shorts. No position row, no sell."""
    cur = LiveCursor()
    close_live_position(cur, kernel_for(FILLED), MODEL, TICKER, 0.55, NOW)
    assert cur.live_orders == []


def test_unfilled_exit_keeps_the_position():
    cur = LiveCursor()
    open_live_position(cur, kernel_for(FILLED), MODEL, TICKER, 18, 0.82, 0.9, NOW)
    close_live_position(cur, kernel_for(UNFILLED), MODEL, TICKER, 0.55, NOW)
    assert (MODEL, TICKER) in cur.live_positions
    assert cur.live_trades[0]["status"] == "open"


def test_closed_pnl_uses_real_fills_and_subtracts_fees():
    cur = LiveCursor()
    open_live_position(cur, kernel_for(FILLED), MODEL, TICKER, 18, 0.82, 0.9, NOW)
    exit_resp = dict(FILLED, average_fill_price="0.9030", average_fee_paid="0.0062")
    close_live_position(cur, kernel_for(exit_resp), MODEL, TICKER, 0.9030, NOW)
    t = cur.live_trades[0]
    assert t["status"] == "closed"
    assert t["exit_price_dollars"] == pytest.approx(0.9030)
    gross = (0.9030 - 0.74) * 18
    fees = 0.0062 * 18 + 0.0134 * 18
    assert t["pnl_dollars"] == pytest.approx(gross - fees)
    assert cur.live_positions == {}


def test_partial_exit_carries_the_remainder_forward():
    cur = LiveCursor()
    open_live_position(cur, kernel_for(FILLED), MODEL, TICKER, 18, 0.82, 0.9, NOW)
    exit_resp = dict(FILLED, fill_count="5.00", average_fill_price="0.9030")
    close_live_position(cur, kernel_for(exit_resp), MODEL, TICKER, 0.9030, NOW)
    assert cur.live_positions[(MODEL, TICKER)]["qty_contracts"] == 13
    closed = [t for t in cur.live_trades if t["status"] == "closed"]
    still_open = [t for t in cur.live_trades if t["status"] == "open"]
    assert closed[0]["qty_contracts"] == 5
    assert still_open[0]["qty_contracts"] == 13
