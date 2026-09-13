"""Shared fixtures for the test suite.

FakeCursor is a minimal in-memory stand-in for a pymysql DictCursor, covering
only the exact query shapes used by sim_repository.py / simulated_trading_engine.py.
It's deliberately not a general SQL engine - if a new query shape is added to
the repository layer, extend the pattern-matching in execute() rather than
reaching for a real database in these tests. That's the point of the DAO
extraction from Phase 3: engine/risk logic should be testable without a live
MySQL connection.
"""
import pytest


class FakeCursor:
    def __init__(self):
        self.sim_positions = {}  # model_name -> row dict
        self.sim_trades = []  # list of dicts, id = index+1
        self.sim_equity_1m = {}  # model_name -> list of rows (append order)
        self.sim_portfolio_20s = {}  # model_name -> drawdown_dollars
        self.sim_model_state = {}  # model_name -> {"paused":..., "paused_reason":...}
        self.forward_quotes = {}  # ticker -> yes_bid_dollars
        self.sim_settings = {}
        self.lastrowid = None
        self._last = None

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self._last = None
        if s.startswith("SELECT * FROM sim_positions WHERE model_name=%s"):
            m = params[0]
            self._last = [self.sim_positions[m]] if m in self.sim_positions else []
        elif s.startswith("UPDATE sim_trades"):
            closed_at, exit_px, pnl, trade_id = params
            self.sim_trades[trade_id - 1].update(
                closed_at_utc=closed_at, exit_price_dollars=exit_px, pnl_dollars=pnl, status="closed"
            )
        elif s.startswith("DELETE FROM sim_positions WHERE model_name=%s"):
            self.sim_positions.pop(params[0], None)
        elif s.startswith("SELECT yes_bid_dollars, yes_bid_size_fp, raw_json"):
            ticker = params[0]
            bid = self.forward_quotes.get(ticker)
            self._last = [{"yes_bid_dollars": bid, "yes_bid_size_fp": 100.0, "raw_json": None}] if bid is not None else [{}]
        elif s.startswith("INSERT INTO sim_trades"):
            model_name, ticker, opened_at, qty, entry_px, raw = params
            self.sim_trades.append(
                dict(
                    model_name=model_name, market_ticker=ticker, opened_at_utc=opened_at,
                    qty_contracts=qty, entry_price_dollars=entry_px, status="open", raw_json=raw,
                )
            )
            self.lastrowid = len(self.sim_trades)
        elif s.startswith("INSERT INTO sim_positions"):
            model_name, opened_at, ticker, qty, entry_px, trade_id, raw = params
            self.sim_positions[model_name] = dict(
                model_name=model_name, opened_at_utc=opened_at, market_ticker=ticker,
                qty_contracts=qty, entry_price_dollars=entry_px, trade_id=trade_id, raw_json=raw,
            )
        elif s.startswith("INSERT INTO sim_model_predictions_1m"):
            pass
        elif s.startswith("SELECT COALESCE(SUM(pnl_dollars),0) p FROM sim_trades"):
            model_name = params[0]
            total = sum(
                t["pnl_dollars"] for t in self.sim_trades
                if t["model_name"] == model_name and t["status"] == "closed" and t.get("pnl_dollars") is not None
            )
            self._last = [{"p": total}]
        elif s.startswith("SELECT COUNT(*) c, SUM(pnl_dollars > 0) w FROM sim_trades"):
            model_name = params[0]
            closed = [t for t in self.sim_trades if t["model_name"] == model_name and t["status"] == "closed"]
            self._last = [{"c": len(closed), "w": sum(1 for t in closed if t["pnl_dollars"] > 0)}]
        elif s.startswith("SELECT cumulative_pnl_dollars, closed_trades_count"):
            model_name = params[0]
            hist = self.sim_equity_1m.get(model_name, [])
            self._last = [hist[-1]] if hist else []
        elif s.startswith("INSERT INTO sim_equity_1m"):
            (now_ts, model_name, realized, new_cum, closed_count, win_rate, raw) = params
            self.sim_equity_1m.setdefault(model_name, []).append(
                {"cumulative_pnl_dollars": new_cum, "closed_trades_count": closed_count}
            )
        elif s.startswith("SELECT cumulative_pnl_dollars FROM sim_equity_1m WHERE model_name=%s ORDER BY snapshot_minute_utc DESC LIMIT 1"):
            model_name = params[0]
            hist = self.sim_equity_1m.get(model_name, [])
            self._last = [hist[-1]] if hist else []
        elif s.startswith("SELECT MAX(cumulative_pnl_dollars) AS peak FROM sim_equity_1m"):
            model_name = params[0]
            hist = self.sim_equity_1m.get(model_name, [])
            peak = max((h["cumulative_pnl_dollars"] for h in hist), default=None)
            self._last = [{"peak": peak}]
        elif s.startswith("SELECT paused, paused_reason, paused_at_utc FROM sim_model_state"):
            model_name = params[0]
            st = self.sim_model_state.get(model_name)
            self._last = [st] if st else [{"paused": 0, "paused_reason": None, "paused_at_utc": None}]
        elif s.startswith("INSERT INTO sim_model_state"):
            model_name = params[0]
            self.sim_model_state[model_name] = {"paused": 1, "paused_reason": params[1], "paused_at_utc": params[2]}
        elif s.startswith("SELECT settings_json FROM sim_settings"):
            row = self.sim_settings.get("risk_config")
            self._last = [{"settings_json": row}] if row else []
        elif s.startswith("INSERT INTO sim_settings"):
            self.sim_settings["risk_config"] = params[0]
        else:
            raise NotImplementedError(f"unhandled SQL in FakeCursor: {s[:100]}")

    def fetchone(self):
        if not self._last:
            return None
        return self._last[0]

    def fetchall(self):
        return self._last or []


@pytest.fixture
def fake_cursor():
    return FakeCursor()
