"""Each trade on the book says why it was entered and why it exited (app.services.trade_why), and
the dashboard, Deploy board and strategy page carry that line without sending another statement."""
from datetime import datetime

import pytest

from app.trading import spec as specmod
from app.services.trade_why import trade_why
from tests.test_hot_endpoint_query_budget import _board_rows, _call, production  # noqa: F401 (fixture)

SPEC = specmod.validate({"side": "yes", "entry": {"min_edge": 0.03, "filters": [
    {"feature": "ret_5m", "op": "<", "value": -0.002}, {"feature": "z_score", "op": ">=", "value": 2}]},
    "exit": {"take_profit": 0.2, "stop_loss": 0.1}})
ENTRY = "Entered at 41¢: the 5-minute return < −0.002, the z-score ≥ 2, edge ≥ 3¢ after fees"


def _closed(reason, exit_price, **kw):
    return dict({"status": "closed", "entry_price": 0.41, "exit_price": exit_price, "close_reason": reason,
                 "order_ref": None}, **kw)


@pytest.mark.parametrize("reason,exit_price,said", [
    ("take_profit", 0.62, "Exited at 62¢: take-profit (+21¢ vs +20¢ target)"),
    ("stop_loss", 0.30, "Exited at 30¢: stop-loss (−11¢ vs −10¢ stop)"),
    ("settled", 1.0, "Held to settlement: paid $1"),
    ("settled", 0.0, "Held to settlement: expired worthless"),
    ("edge_gone", 0.5, "Exited at 50¢: the model's edge fell below its hold line"),
    ("stop", 0.38, "Exited at 38¢: your loss stop closed this strategy's positions"),
    ("drawdown", 0.2, "Exited at 20¢: your drawdown limit closed this strategy's positions"),
    ("flatten", 0.45, "Exited at 45¢: sold when the strategy was paused or stopped"),
    ("pair_unwind", 0.4, "Exited at 40¢: the unhedged pair leg was sold straight back"),
    ("something_new", 0.4, "Exited at 40¢ (something new)"),
])
def test_a_closed_trade_says_the_rule_it_entered_on_and_why_it_exited(reason, exit_price, said):
    assert trade_why(_closed(reason, exit_price), SPEC) == ENTRY + " · " + said


def test_an_open_trade_says_its_rule_and_how_it_will_exit():
    pos = {"status": "open", "entry_price": 0.41, "order_ref": None}
    assert trade_why(pos, SPEC) == ENTRY + " · Exits: +20¢ take-profit, −10¢ stop, else settlement"
    hold = specmod.validate({"side": "no", "entry": {"min_edge": 0}, "exit": {"min_edge_to_hold": -0.01}})
    assert trade_why(pos, hold) == ("Entered at 41¢: fair value at or above the price after fees"
                                    " · Exits: sells if edge drops below −1¢, else settlement")
    assert trade_why(pos, specmod.validate({"side": "yes"})).endswith(" · Holds to settlement")


def test_without_the_strategy_spec_only_what_the_row_stores_is_said():
    # A stopped deployment's spec isn't read: the exit reason still comes from the row, with no target.
    assert trade_why(_closed("take_profit", 0.62), None) == "Exited at 62¢: take-profit (+21¢)"
    assert trade_why({"status": "open", "entry_price": 0.41}, None) is None  # nothing stored to say
    adopted = {"status": "open", "entry_price": 0.5, "order_ref": "reconcile-adopt"}
    assert trade_why(adopted, SPEC) == "Adopted from your Kalshi account (Tau did not place it) · " \
                                       "Exits: +20¢ take-profit, −10¢ stop, else settlement"
    code = {"market": "btc15m", "code": "def signals(w): return []", "sizing": {"stake": 5, "max_positions": 2}}
    assert trade_why(_closed("settled", 1.0), code) == \
        "Entered at 41¢: the strategy's code signalled a buy · Held to settlement: paid $1"


def _positions(dep_id, unknown_dep):
    at = datetime(2026, 10, 24)
    row = {"user_id": 7, "mode": "paper", "ticker": "KXBTC15M-T1", "side": "yes", "qty": 3, "entry_price": 0.41,
           "entry_fee": 0.02, "market_close_time": at, "opened_at": at, "order_ref": None, "mark_price": None,
           "mark_ts": None, "title": "Fade tails"}
    return {
        "WHERE p.user_id=%s AND p.status=%s ORDER BY p.id DESC": [dict(row, id=1, deployment_id=dep_id, status="open")],
        "s.id IS NOT NULL AS _listed": [
            dict(row, id=2, deployment_id=dep_id, status="closed", exit_price=1.0, exit_fee=0, pnl=1.75,
                 close_reason="settled", closed_at=at, _listed=1),
            dict(row, id=3, deployment_id=unknown_dep, status="closed", exit_price=0.62, exit_fee=0.01, pnl=0.6,
                 close_reason="take_profit", closed_at=at, _listed=1)],
    }


@pytest.mark.parametrize("name", ["dashboard", "list_deployments"])
def test_the_dashboard_and_deploy_board_carry_each_trades_reason_without_another_statement(production, name):
    import app.server as server

    server._BACKTEST_CHECKS.clear()
    server._ROADS.clear(); server._FAILING.clear()
    bare = _call(name, 10.0, extra=_board_rows())
    out = {}
    real = getattr(server, name)
    try:
        setattr(server, name, lambda ctx: out.update(real(ctx)))
        server._BACKTEST_CHECKS.clear()
        server._ROADS.clear(); server._FAILING.clear()
        log = _call(name, 10.0, extra=dict(_board_rows(), **_positions(5, 99)))
    finally:
        setattr(server, name, real)
    assert len(log) == len(bare)  # the reasons come from rows already read (demo deployments add their own reads)
    entry = "Entered at 41¢: edge ≥ 5¢ after fees"  # _board_rows' strategy: min_edge 0.05, no exits
    assert [p["why"] for p in out["open_positions"]] == [entry + " · Holds to settlement"]
    assert [p["why"] for p in out["recent_closed"]] == [
        entry + " · Held to settlement: paid $1",
        "Exited at 62¢: take-profit (+21¢)"]  # deployment 99 isn't listed (stopped): its exit only


def test_the_strategy_page_holdings_say_why_each_was_bought(production):
    import app.server as server

    server._BACKTEST_CHECKS.clear()
    rows = _board_rows()
    rows["SELECT p.*, d.mode FROM app_positions p"] = [
        {"id": 1, "deployment_id": 5, "status": "open", "mode": "paper", "ticker": "KXBTC15M-T1", "side": "yes",
         "qty": 3, "entry_price": 0.41, "entry_fee": 0.02, "market_close_time": datetime(2026, 10, 24),
         "order_ref": None, "mark_price": None}]
    out = {}
    real = server.get_strategy
    try:
        server.get_strategy = lambda ctx: out.update(real(ctx))
        _call("get_strategy", 10.0, extra=rows, params=("9",))
    finally:
        server.get_strategy = real
    assert [h["why"] for h in out["holdings"]] == ["Entered at 41¢: edge ≥ 5¢ after fees · Holds to settlement"]


def test_a_spec_it_cannot_read_never_fails_the_page():
    broken = {"side": "yes", "entry": {"filters": [{"op": "<"}]}, "exit": {"take_profit": "lots"}}
    assert trade_why(_closed("take_profit", 0.62), broken) == "Exited at 62¢: take-profit (+21¢)"
    assert trade_why({"status": "open", "entry_price": 0.41}, ["not", "a", "spec"]) is None
