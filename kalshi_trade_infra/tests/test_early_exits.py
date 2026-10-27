"""Early exits scored against holding to settlement: the engine fills hold_pnl once a stopped-out
(or take-profit) position's contract settles, and the panel and review read whether the stop helped."""
from datetime import datetime, timedelta, timezone

from app import server
from app.trading import engine
from app.research import agent
from app import repository as repo


def _pos(pid, ticker, side="no", qty=11, entry=0.19, fee=0.10):
    return {"id": pid, "ticker": ticker, "side": side, "qty": qty, "entry_price": entry, "entry_fee": fee}


def test_score_early_exits_fills_hold_pnl_once_settled_and_is_rate_limited(monkeypatch):
    # #74's first trade (2026-10-24): NO at 19c, the stop sold at 2.4c, and the contract settled YES.
    rows = [_pos(126, "KXSOL15M-A"), _pos(128, "KXSOL15M-A", side="yes", qty=5, entry=0.40, fee=0.05),
            _pos(129, "KXSOL15M-B")]
    monkeypatch.setattr(repo, "unscored_early_exits", lambda cur, market, now, **k: rows)
    scored = {}
    monkeypatch.setattr(repo, "score_early_exit", lambda cur, pid, result, hold: scored.setdefault(pid, (result, round(hold, 4))) and True)
    asked = []

    def result(t):
        asked.append(t)
        return "yes" if t == "KXSOL15M-A" else None  # B hasn't settled yet

    class Conn:
        def cursor(self):
            return None
    monkeypatch.setattr(engine, "_last_exit_score", {})
    now = datetime(2026, 10, 24, 20, 40, tzinfo=timezone.utc)
    src = engine.Sources(result=result)
    assert engine.score_early_exits(Conn(), engine.MARKETS["sol15m"], src, now) == 2
    assert scored == {126: ("yes", round(-11 * 0.19 - 0.10, 4)), 128: ("yes", round(5 - 5 * 0.40 - 0.05, 4))}
    assert asked == ["KXSOL15M-A", "KXSOL15M-B"]  # one lookup per ticker
    assert engine.score_early_exits(Conn(), engine.MARKETS["sol15m"], src, now + timedelta(seconds=60)) == 0
    assert asked == ["KXSOL15M-A", "KXSOL15M-B"]  # rate-limited: no new lookups


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def execute(self, sql, args=None):
        self.sql.append((sql, args))

    def fetchall(self):
        return self.rows


def test_scorecard_says_whether_selling_early_beat_holding():
    cur = _Cur([{"reason": "stop", "exits": 3, "scored": 2, "pnl": -7.0, "scored_pnl": -5.66, "hold_pnl": -7.19},
                {"reason": "take_profit", "exits": 1, "scored": 1, "pnl": 4.0, "scored_pnl": 4.0, "hold_pnl": 6.0}])
    out = repo.early_exit_scorecard(cur, 2, since=datetime(2026, 10, 17))
    assert out["stop"] == {"exits": 3, "scored": 2, "pnl": -7.0, "scored_pnl": -5.66, "hold_pnl": -7.19, "saved": 1.53}
    assert out["take_profit"]["saved"] == -2.0
    assert cur.sql[0][1] == [2, "paper", datetime(2026, 10, 17)] and "close_reason<>'settled'" in cur.sql[0][0]


def test_scorecard_splits_out_healthy_positions_the_stop_flattened():
    # A stop that fires on one position sells every position of the deployment. The ones sold above
    # the stop line are reported separately: they are what "close only the breacher" would change.
    cur = _Cur([{"reason": "stop", "exits": 7, "scored": 4, "pnl": -0.6, "scored_pnl": -0.6, "hold_pnl": -2.0,
                 "c_exits": 6, "c_scored": 3, "c_saved": -1.25}])
    out = repo.early_exit_scorecard(cur, 1)
    assert out["stop"]["collateral"] == {"exits": 6, "scored": 3, "saved": -1.25}
    assert "JOIN app_users" in cur.sql[0][0] and "position_stop_pct" in cur.sql[0][0]
    line = agent.early_exits_line(out)
    assert line.endswith("stop 4: $-0.60 vs $-2.00 held, saved $1.40 "
                         "(of which 3 healthy positions sold alongside a breach: COST $1.25)")


def test_panel_names_a_paused_strategy_and_what_the_stop_did():
    now = repo.now_utc()
    deps = [{"id": 74, "mode": "paper", "status": "paused", "updated_at": now - timedelta(hours=1),
             "title": "Sol 15m fade — late NO", "closed_trades": 2, "realized_pnl": -5.66,
             "status_reason": "force-closed: position down 64.0% >= stop 40.0% of cost"},
            {"id": 3, "mode": "paper", "status": "paused", "updated_at": now - timedelta(days=3), "title": "old",
             "closed_trades": 1, "realized_pnl": 1.0, "status_reason": "x"}]
    paused = server._paused_recent(deps)
    assert [p["deployment_id"] for p in paused] == [74]
    assert server._paused_lines(paused) == [
        "Sol 15m fade was paused after 2 paper trades (down $5.66 net of fees and spread): its safety stop sold a position that had lost 64% of its cost."]
    assert server._plain_pause_reason("force-closed: drawdown 30.0% >= limit 25.0%") == "it lost 30% of its money, past its 25% limit"
    exits = {"stop": {"exits": 2, "scored": 2, "pnl": -5.66, "scored_pnl": -5.66, "hold_pnl": -7.19, "saved": 1.53}}
    assert server._stop_line(exits) == ("This week the safety stop sold 2 positions on paper. Holding them to the end "
                                        "would have lost $7.19, so the stop saved $1.53.")
    exits["stop"].update(scored=1, hold_pnl=2.0, saved=-7.66)
    assert server._stop_line(exits).endswith("Holding the 1 that has settled to the end would have made $2.00, so the stop cost $7.66.")
    assert server._stop_line({"take_profit": {"exits": 1, "scored": 1, "hold_pnl": 1, "saved": 1}}) == ""
    assert server._stop_line({"stop": dict(exits["stop"], scored=0)}) == ""
    story = server._autopilot_story({"autopilot": True, "paper_running": 2, "paused_recent": paused,
                                     "early_exits_7d": {"stop": dict(exits["stop"], scored=2, hold_pnl=-7.19, saved=1.53)}})
    assert any(line.startswith("Sol 15m fade was paused") for line in story)
    assert any("the stop saved $1.53" in line for line in story)


def test_review_context_line_flags_exits_that_cost_money():
    exits = {"stop": {"exits": 12, "scored": 10, "scored_pnl": -100.0, "hold_pnl": -140.0, "saved": 40.0},
             "take_profit": {"exits": 2, "scored": 2, "scored_pnl": 14.93, "hold_pnl": 20.0, "saved": -5.07},
             "flatten": {"exits": 1, "scored": 0, "scored_pnl": 0.0, "hold_pnl": 0.0, "saved": 0.0}}
    line = agent.early_exits_line(exits)
    assert line.startswith("Early exits on paper vs holding to settlement (all time): stop 10: $-100.00 vs $-140.00 held, saved $40.00")
    assert "take_profit 2: $14.93 vs $20.00 held, COST $5.07" in line and "flatten 1 (none settled yet)" in line
    assert agent.early_exits_line({}) == ""


def test_story_counts_read_with_thousands_separators():
    story = server._autopilot_story({"autopilot": True, "research": {"tested_7d": 1708, "passed_7d": 0}})
    assert "This week it tested 1,708 ideas" in story[1]
