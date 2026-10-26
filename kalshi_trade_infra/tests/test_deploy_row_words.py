"""What a Deploy row says about a paused deployment and an orphaned position (display only).

- A demo deployment the engine paused for a missing demo key stays paused once the key is added; its
  row still said "Add your Kalshi demo (sandbox) key on the Funds page" beside a Funds page saying the
  key is connected. It now says the key is back and it can be resumed.
- A loss-guard pause sums every closed trade the deployment ever made, after each decision, so Resume
  only pauses it again while that loss is still past the guard. The row now says so.
- An open position whose strategy was deleted came back with no title and showed a blank name on
  Deploy and the dashboard. It is named, and says nothing sells or settles it.
"""
from types import SimpleNamespace

import pytest

from app.web import views
from app.web.routes import deployments as dep_routes
from app.web.routes import strategies as strategy_routes

DEMO_KEY_REASON = "Add your Kalshi demo (sandbox) key on the Funds page to run this on demo."
GUARD_REASON = "Lost $12.40, more than the $10.00 guard (2x its worst backtest drawdown)."


def _dep(**over):
    d = {"id": 1, "strategy_id": 3, "title": "Dep", "direction": "momentum", "market": "btc15m", "mode": "paper",
         "status": "paused", "status_reason": "By you", "realized_pnl": 0.0, "closed_trades": 0, "wins": 0,
         "open_positions": 0, "created_at": None, "spec": {"sizing": {"stake": 5, "max_positions": 3}}, "result": {}}
    d.update(over)
    return d


def test_a_demo_key_pause_says_the_key_is_back_once_it_is_connected():
    paused = _dep(mode="demo", status_reason=DEMO_KEY_REASON)
    assert views._status_why(paused) == DEMO_KEY_REASON  # no key yet: the engine's own words
    back = views._status_why(paused, demo_key_back=True)
    assert back == "Your Kalshi demo key wasn't connected when it paused. It is now, so you can resume it"
    assert "Funds page" not in back
    # Any other pause keeps its own words when the key is connected.
    assert views._status_why(_dep(mode="demo"), demo_key_back=True) == "You paused it"
    assert views._deployment_out(paused, [], demo_key_back=True)["status_why"] == back
    assert views._deployment_out(paused, [])["status_why"] == DEMO_KEY_REASON


def test_demo_key_back_reads_the_key_only_for_a_demo_key_pause(monkeypatch):
    reads = []
    monkeypatch.setattr(views.repo, "get_kalshi_dev_key", lambda cur, uid: reads.append(uid) or {"key_id": "k"})
    assert views._demo_key_back(None, 7, [_dep(), _dep(mode="demo", status="running", status_reason=None)]) is False
    assert reads == []  # nothing paused for the key: no read
    assert views._demo_key_back(None, 7, [_dep(mode="demo", status_reason=DEMO_KEY_REASON)]) is True
    monkeypatch.setattr(views.repo, "get_kalshi_dev_key", lambda cur, uid: None)
    assert views._demo_key_back(None, 7, [_dep(mode="demo", status_reason=DEMO_KEY_REASON)]) is False
    # A stopped one is not offered a resume.
    assert views._demo_key_back(None, 7, [_dep(mode="demo", status="stopped", status_reason=DEMO_KEY_REASON)]) is False


@pytest.mark.parametrize("realized,still", [(-12.40, True), (-10.01, True), (-10.00, False), (-3.0, False), (None, False)])
def test_a_loss_guard_pause_says_resume_pauses_again_while_the_loss_is_past_the_guard(realized, still):
    why = views._status_why(_dep(status_reason=GUARD_REASON, realized_pnl=realized))
    assert why.startswith("Lost $12.40, more than the $10.00 guard (2x its worst backtest drawdown).")
    assert ("Resume would pause it again at its next check" in why) is still
    # A stopped deployment can't be resumed, so it is not told about Resume.
    assert "Resume" not in views._status_why(_dep(status="stopped", status_reason=GUARD_REASON, realized_pnl=-50.0))


def test_a_guard_figure_with_thousands_reads_as_a_number():
    raw = "Lost $1,240.00, more than the $1,000.00 guard (2x its worst backtest drawdown)."
    assert "Resume would" in views._status_why(_dep(status_reason=raw, realized_pnl=-1240.0))
    assert "Resume would" not in views._status_why(_dep(status_reason=raw, realized_pnl=-999.0))


def test_an_open_position_of_a_deleted_strategy_is_named_and_says_nothing_settles_it():
    rows = [{"id": 1, "deployment_id": 15, "status": "open", "title": None, "side": "yes", "qty": 5, "entry_price": 0.4},
            {"id": 2, "deployment_id": 1, "status": "open", "title": "Kept", "side": "yes", "qty": 5, "entry_price": 0.4}]
    out = strategy_routes._with_why(rows, [])
    assert out[0]["title"] == "Deleted strategy"
    assert out[0]["why"] == "Its strategy was deleted, so Tau no longer sells or settles this position."
    assert out[1]["title"] == "Kept" and "deleted" not in (out[1]["why"] or "")


def test_the_deploy_board_passes_the_demo_key_back_to_its_rows(monkeypatch):
    paused = _dep(id=14, mode="demo", status_reason=DEMO_KEY_REASON)
    monkeypatch.setattr(dep_routes.book_memo, "BookMemo", lambda cur, uid: None)
    monkeypatch.setattr(dep_routes.book_memo, "deployments_for_display", lambda memo: [dict(paused)])
    monkeypatch.setattr(dep_routes.book_memo, "deployment_curves", lambda memo, ids: {})
    monkeypatch.setattr(dep_routes.book_memo, "removed_deployments", lambda memo: [])
    monkeypatch.setattr(dep_routes, "_backtest_checks", lambda *a: {})
    monkeypatch.setattr(dep_routes, "_deploy_roads", lambda *a: {})
    monkeypatch.setattr(dep_routes, "_demo_health", lambda *a: None)
    monkeypatch.setattr(dep_routes.repo, "user_positions", lambda *a: [])
    monkeypatch.setattr(views.repo, "get_kalshi_dev_key", lambda cur, uid: {"key_id": "k"})
    monkeypatch.setattr(dep_routes.page_poll, "answer", lambda body, v: body)
    ctx = SimpleNamespace(cur=None, uid=7, query={})
    row = dep_routes.list_deployments(ctx)["deployments"][0]
    assert row["status_why"].startswith("Your Kalshi demo key wasn't connected when it paused")
