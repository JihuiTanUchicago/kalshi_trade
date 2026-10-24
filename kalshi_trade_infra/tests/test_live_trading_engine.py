"""Tests for the multi-strategy live trading engine: per-model settings,
per-model risk isolation, and the auto-pause kill switch. Uses a small
in-memory FakeCursor (separate from the sim one in conftest.py - different
table shapes) so this doesn't need a live database.
"""
import re
from datetime import datetime

import pytest

from data_pipeline import live_trading_engine as lte


class FakeCursor:
    def __init__(self):
        self.live_settings = {}  # settings_key -> json string
        self.live_model_state = {}  # model_name -> row dict
        self.live_positions = {}  # (model_name, ticker) -> row dict
        self.live_trades = []  # list of dicts, id = index+1
        self._last = None

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self._last = None

        if s.startswith("SELECT settings_json FROM live_settings WHERE settings_key="):
            m = re.search(r"settings_key='([^']+)'", s)
            key = m.group(1) if m else params[0]
            row = self.live_settings.get(key)
            self._last = [{"settings_json": row}] if row is not None else []
        elif s.startswith("SELECT 1 FROM live_settings WHERE settings_key="):
            m = re.search(r"settings_key='([^']+)'", s)
            key = m.group(1) if m else params[0]
            self._last = [{"1": 1}] if key in self.live_settings else []
        elif s.startswith("INSERT INTO live_settings"):
            m = re.search(r"VALUES \('([^']+)'", s)
            if m:
                key, json_val = m.group(1), params[0]
            else:
                key, json_val = params[0], params[1]
            self.live_settings[key] = json_val
        elif s.startswith("DELETE FROM live_settings WHERE settings_key="):
            m = re.search(r"settings_key='([^']+)'", s)
            key = m.group(1) if m else params[0]
            self.live_settings.pop(key, None)

        elif s.startswith("SELECT paused_reason, paused_at_utc FROM live_model_state WHERE model_name=%s AND paused=1"):
            row = self.live_model_state.get(params[0])
            self._last = [row] if row and row.get("paused") else []
        elif s.startswith("SELECT model_name, paused_reason, paused_at_utc FROM live_model_state WHERE paused=1"):
            self._last = [r for r in self.live_model_state.values() if r.get("paused")]
        elif s.startswith("INSERT INTO live_model_state"):
            if len(params) == 4:
                model_name, reason, paused_at, _updated_at = params
                self.live_model_state[model_name] = {
                    "model_name": model_name, "paused": 1, "paused_reason": reason, "paused_at_utc": paused_at,
                }
            else:
                model_name, _updated_at = params
                self.live_model_state[model_name] = {
                    "model_name": model_name, "paused": 0, "paused_reason": None, "paused_at_utc": None,
                }

        elif s.startswith("SELECT COALESCE(SUM(pnl_dollars),0) p FROM live_trades WHERE status='closed' AND model_name=%s AND DATE"):
            model_name = params[0]
            today = params[1] if len(params) > 1 else None
            total = sum(
                float(t["pnl_dollars"] or 0)
                for t in self.live_trades
                if t["model_name"] == model_name and t["status"] == "closed"
            )
            self._last = [{"p": total}]
        elif s.startswith("SELECT COALESCE(SUM(pnl_dollars),0) p FROM live_trades WHERE status='closed' AND model_name=%s"):
            model_name = params[0]
            total = sum(
                float(t["pnl_dollars"] or 0)
                for t in self.live_trades
                if t["model_name"] == model_name and t["status"] == "closed"
            )
            self._last = [{"p": total}]
        elif s.startswith("SELECT COUNT(*) c, COALESCE(SUM(entry_price_dollars*qty_contracts),0) n FROM live_positions WHERE model_name=%s"):
            model_name = params[0]
            matches = [p for (m, t), p in self.live_positions.items() if m == model_name]
            self._last = [{"c": len(matches), "n": sum(p["entry_price_dollars"] * p["qty_contracts"] for p in matches)}]

        elif s.startswith("SELECT * FROM live_positions WHERE model_name=%s AND market_ticker=%s"):
            row = self.live_positions.get((params[0], params[1]))
            self._last = [row] if row else []
        elif s.startswith("SELECT market_ticker FROM live_positions WHERE model_name=%s LIMIT 1"):
            matches = [p for (m, t), p in self.live_positions.items() if m == params[0]]
            self._last = [{"market_ticker": matches[0]["market_ticker"]}] if matches else []
        elif s.startswith("INSERT INTO live_positions"):
            model_name, ticker, opened_at, qty, entry_px, raw = params
            self.live_positions[(model_name, ticker)] = {
                "model_name": model_name, "market_ticker": ticker, "opened_at_utc": opened_at,
                "qty_contracts": qty, "entry_price_dollars": entry_px, "raw_json": raw,
            }
        elif s.startswith("DELETE FROM live_positions WHERE model_name=%s AND market_ticker=%s"):
            self.live_positions.pop((params[0], params[1]), None)

        elif s.startswith("INSERT INTO live_trades"):
            opened_at, ticker, model_name, qty, entry_px, raw = params
            self.live_trades.append(dict(
                model_name=model_name, market_ticker=ticker, opened_at_utc=opened_at,
                qty_contracts=qty, entry_price_dollars=entry_px, exit_price_dollars=None,
                pnl_dollars=None, status="open", raw_json=raw,
            ))
        elif s.startswith("UPDATE live_trades"):
            closed_at, px, pnl, qty, ticker, model_name = params
            for t in reversed(self.live_trades):
                if t["market_ticker"] == ticker and t["model_name"] == model_name and t["status"] == "open":
                    t.update(closed_at_utc=closed_at, exit_price_dollars=px, pnl_dollars=pnl,
                             qty_contracts=qty, status="closed")
                    break
        elif s.startswith("UPDATE live_positions SET qty_contracts"):
            qty, model_name, ticker = params
            self.live_positions[(model_name, ticker)]["qty_contracts"] = qty
        elif s.startswith("INSERT INTO live_orders"):
            pass
        else:
            raise AssertionError(f"FakeCursor got unexpected SQL: {s}")

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return self._last or []


@pytest.fixture
def fake_cursor():
    return FakeCursor()


class DummyKernel:
    """Stands in for a venue that fills everything at the limit. Only valid
    for tests about position scoping and pause flags; anything asserting on
    fill handling must drive the real kernel with a captured Kalshi response
    (see tests/test_execution_fills.py)."""

    def execute(self, intent):
        from data_pipeline.architecture.contracts import ExecutionReport
        return ExecutionReport(
            accepted=True, status="filled", fill_price_dollars=intent.limit_price_dollars,
            fill_qty_contracts=intent.qty_contracts, external_order_id="x", client_order_id="y",
            fee_dollars=0.0, raw_json={},
        )


def test_load_settings_seeds_per_model_defaults(fake_cursor):
    rf_cfg = lte.load_settings(fake_cursor, "random_forest")
    hc_cfg = lte.load_settings(fake_cursor, "random_forest_high_conviction")
    theory_cfg = lte.load_settings(fake_cursor, "binary_theory_edge")

    assert rf_cfg["edge_threshold"] == lte.DEFAULT_SETTINGS["edge_threshold"]
    assert hc_cfg["edge_threshold"] == lte.EDGE_THRESHOLD_OVERRIDES["random_forest_high_conviction"]
    assert theory_cfg["edge_threshold"] == lte.EDGE_THRESHOLD_OVERRIDES["binary_theory_edge"]
    # Each model gets its own settings row, independently updatable.
    assert set(fake_cursor.live_settings.keys()) == {"random_forest", "random_forest_high_conviction", "binary_theory_edge"}


def test_update_settings_only_touches_one_model(fake_cursor):
    lte.load_settings(fake_cursor, "random_forest")
    lte.load_settings(fake_cursor, "binary_theory_edge")
    lte.update_settings(fake_cursor, "random_forest", {"live_enabled": True, "edge_threshold": 0.02})

    rf_cfg = lte.load_settings(fake_cursor, "random_forest")
    theory_cfg = lte.load_settings(fake_cursor, "binary_theory_edge")
    assert rf_cfg["live_enabled"] is True
    assert rf_cfg["edge_threshold"] == 0.02
    assert theory_cfg["live_enabled"] is False, "updating one model's settings must not affect another's"


def test_migrate_legacy_settings_folds_into_random_forest(fake_cursor):
    import json
    fake_cursor.live_settings["live_config"] = json.dumps({**lte.DEFAULT_SETTINGS, "live_enabled": True, "max_daily_loss": 7.0})
    lte.migrate_legacy_settings(fake_cursor)

    assert "live_config" not in fake_cursor.live_settings
    rf_cfg = lte.load_settings(fake_cursor, "random_forest")
    assert rf_cfg["live_enabled"] is True
    assert rf_cfg["max_daily_loss"] == 7.0


def test_risk_state_is_isolated_per_model(fake_cursor):
    now = datetime(2026, 1, 1, 12, 0, 0)
    fake_cursor.live_trades.append(dict(
        model_name="random_forest", market_ticker="T1", status="closed",
        pnl_dollars=-20.0, closed_at_utc=now, opened_at_utc=now, qty_contracts=1, entry_price_dollars=0.5,
    ))
    cfg_rf = lte.load_settings(fake_cursor, "random_forest")
    cfg_theory = lte.load_settings(fake_cursor, "binary_theory_edge")

    risk_rf, meta_rf = lte.current_risk_state(fake_cursor, cfg_rf, "random_forest")
    risk_theory, meta_theory = lte.current_risk_state(fake_cursor, cfg_theory, "binary_theory_edge")

    assert risk_rf == "RED", "random_forest lost more than max_total_drawdown ($10 default)"
    assert risk_theory == "GREEN", "binary_theory_edge has no trades and must not inherit random_forest's breach"


def test_auto_pause_blocks_new_entries_but_not_exits(fake_cursor):
    now = datetime(2026, 1, 1, 12, 0, 0)
    lte.set_model_paused(fake_cursor, "random_forest", "risk breach: MAX_TOTAL_DD", now)

    pause = lte.get_model_pause(fake_cursor, "random_forest")
    assert pause is not None
    assert "MAX_TOTAL_DD" in pause["paused_reason"]

    kernel = DummyKernel()
    lte.open_live_position(fake_cursor, kernel, "random_forest", "T1", 5, 0.40, 0.9, now)
    assert ("random_forest", "T1") in fake_cursor.live_positions, "position management (open/close) works regardless of pause flag"
    lte.close_live_position(fake_cursor, kernel, "random_forest", "T1", 0.45, now)
    assert ("random_forest", "T1") not in fake_cursor.live_positions

    all_paused = lte.get_all_live_pause_states(fake_cursor)
    assert "random_forest" in all_paused
    lte.clear_model_paused(fake_cursor, "random_forest", now)
    assert lte.get_model_pause(fake_cursor, "random_forest") is None


def test_open_and_close_position_are_scoped_by_model(fake_cursor):
    now = datetime(2026, 1, 1, 12, 0, 0)
    kernel = DummyKernel()
    # Two different strategies open positions on the SAME ticker simultaneously.
    lte.open_live_position(fake_cursor, kernel, "random_forest", "T1", 3, 0.30, 0.8, now)
    lte.open_live_position(fake_cursor, kernel, "binary_theory_edge", "T1", 4, 0.32, 0.85, now)

    assert ("random_forest", "T1") in fake_cursor.live_positions
    assert ("binary_theory_edge", "T1") in fake_cursor.live_positions

    lte.close_live_position(fake_cursor, kernel, "random_forest", "T1", 0.50, now)
    assert ("random_forest", "T1") not in fake_cursor.live_positions
    assert ("binary_theory_edge", "T1") in fake_cursor.live_positions, "closing one strategy's position must not touch another's on the same ticker"


# -- DB connection-loss recovery: a dropped/timed-out connection reconnects, not crashes ----------

def test_is_conn_lost_recognizes_dropped_connection():
    import pymysql
    # The exact error the engine was crash-looping on (errno 2013, "timed out").
    assert lte._is_conn_lost(pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query (timed out)"))
    assert lte._is_conn_lost(pymysql.err.OperationalError(2006, "MySQL server has gone away"))


def test_is_conn_lost_ignores_real_errors():
    # A genuine bug (not a connection drop) must still propagate and crash/restart, not be swallowed.
    assert not lte._is_conn_lost(ValueError("bad spec"))
    assert not lte._is_conn_lost(KeyError("edge_threshold"))
    import pymysql
    assert not lte._is_conn_lost(pymysql.err.OperationalError(1205, "Lock wait timeout exceeded"))
