"""What the Deploy board and the strategy page say about removed deployments and paused demo copies
(display only).

- Deploy's "Realized" summed only the deployments it lists, beside a larger dashboard all-time figure
  that also counts removed ones, and didn't say so. Each book now carries its listed total, its removed
  deployments' total and count, and (paper, live) the two together: the dashboard's figure.
- A demo copy the demo-copy sync paused (its paper deployment not running) said "the demo copy stopped
  too" while it was paused, and offered a Resume the sync would undo. Its row now says paused and what
  it waits on, and Resume comes disabled with that reason while the paper deployment isn't running.
- A strategy whose deployments were removed lists them as past deployments.
"""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.trading import demo_twins
from app.web import views
from app.web.routes import deployments as dep_routes
from app.web.routes import strategies as strategy_routes

COPY = demo_twins.PAUSE_REASON


def _dep(**over):
    d = {"id": 1, "strategy_id": 3, "title": "Dep", "direction": "momentum", "market": "btc15m", "mode": "paper",
         "status": "running", "status_reason": None, "realized_pnl": 0.0, "closed_trades": 0, "wins": 0,
         "open_positions": 0, "created_at": None, "spec": {"sizing": {"stake": 5, "max_positions": 3}}, "result": {}}
    d.update(over)
    return d


def test_the_stored_copy_reason_still_reads_stopped_so_the_sync_keeps_matching_it():
    # The sync resumes a copy only when its stored reason is exactly PAUSE_REASON: the text is not changed.
    assert COPY == "Its paper strategy is no longer running, so the demo copy stopped too."


def test_paper_books_says_running_when_any_paper_deployment_runs():
    deps = [_dep(id=1, strategy_id=3, status="paused"), _dep(id=2, strategy_id=3, status="running"),
            _dep(id=3, strategy_id=4, status="paused"), _dep(id=4, strategy_id=5, mode="demo"),
            _dep(id=5, strategy_id=6, status="stopped")]
    assert views._paper_books(deps) == {3: "running", 4: "paused"}
    assert views._paper_books(list(reversed(deps))) == {3: "running", 4: "paused"}


@pytest.mark.parametrize("paper,why,block", [
    ("paused", "Waiting on its paper deployment, which is paused. Resume that one and this copy resumes with it",
     "Resume its paper deployment first: this demo copy resumes with it."),
    (None, "Waiting to run on paper again: a demo copy runs only while its paper deployment does",
     "Deploy it on paper first: this demo copy resumes with its paper deployment."),
    ("running", "Its paper deployment wasn't running when this paused. It is now, so you can resume it", None),
])
def test_a_paused_demo_copy_says_paused_and_what_it_waits_on(monkeypatch, paper, why, block):
    monkeypatch.setattr(demo_twins, "DEMO_TWINS", True)
    copy = _dep(id=2, mode="demo", status="paused", status_reason=COPY)
    deps = [copy] + ([_dep(id=1, status=paper)] if paper else [])
    out = views._deployment_out(copy, [], paper_sids=set(), paper_books=views._paper_books(deps))
    assert (out["status_why"], out["resume_block"]) == (why, block)
    assert "stopped" not in out["status_why"]
    assert out["status_reason"] == COPY  # the stored reason is sent as stored


def test_a_copy_reason_claims_nothing_about_paper_when_the_page_did_not_read_it_or_the_sync_is_off(monkeypatch):
    copy = _dep(id=2, mode="demo", status="paused", status_reason=COPY)
    monkeypatch.setattr(demo_twins, "DEMO_TWINS", True)
    out = views._deployment_out(copy, [])  # no paper_books: unknown
    assert (out["status_why"], out["resume_block"]) == ("Its paper deployment wasn't running, so this demo copy paused with it", None)
    monkeypatch.setattr(demo_twins, "DEMO_TWINS", False)  # nothing would pause it again
    out = views._deployment_out(copy, [], paper_books={})
    assert (out["status_why"], out["resume_block"]) == ("Its paper deployment wasn't running, so this demo copy paused with it", None)


def test_only_a_paused_demo_copy_gets_a_resume_block(monkeypatch):
    monkeypatch.setattr(demo_twins, "DEMO_TWINS", True)
    for d in (_dep(mode="demo", status="paused", status_reason="By you"),  # paused by you: Resume works
              _dep(mode="paper", status="paused", status_reason=COPY),
              _dep(mode="demo", status="stopped", status_reason=COPY),
              _dep(mode="demo", status="running")):
        out = views._deployment_out(d, [], paper_books={})
        assert out["resume_block"] is None, d
    assert views._deployment_out(_dep(mode="demo", status="paused", status_reason="By you"), [],
                                 paper_books={})["status_why"] == "You paused it"


def test_the_phone_panel_says_a_copy_paused_not_stopped():
    assert views._plain_pause_reason(COPY) == "its paper deployment wasn't running, so its demo copy paused with it"
    assert views._pause_clause(COPY) == "its paper deployment wasn't running, so its demo copy paused with it"


def test_realized_by_book_names_what_the_board_leaves_out_one_book_at_a_time():
    listed = [_dep(id=1, mode="paper", realized_pnl=Decimal("100.0049")), _dep(id=2, mode="paper", realized_pnl=Decimal("46.0349")),
              _dep(id=3, mode="live", realized_pnl=Decimal("2.5000")), _dep(id=4, mode="demo", realized_pnl=Decimal("-10.0000"))]
    removed = [{"id": 9, "mode": "paper", "realized_pnl": Decimal("5.7202")}, {"id": 8, "mode": "paper", "realized_pnl": Decimal("0")},
               {"id": 7, "mode": "demo", "realized_pnl": Decimal("4.0000")}]
    books = views._realized_by_book(listed, removed)
    assert books["paper"] == {"listed": 146.04, "removed": 5.72, "removed_deployments": 2, "all": 151.76}
    assert books["live"] == {"listed": 2.5, "removed": 0.0, "removed_deployments": 0, "all": 2.5}
    assert books["demo"] == {"listed": -10.0, "removed": 4.0, "removed_deployments": 1}  # no "all": demo counts from its reload
    # "all" is the exact sum rounded once, as the dashboard's SUM is: not the two rounded figures added.
    assert views._realized_by_book([_dep(realized_pnl=Decimal("0.0049"))], [{"mode": "paper", "realized_pnl": Decimal("0.0049")}])["paper"] == \
        {"listed": 0.0, "removed": 0.0, "removed_deployments": 1, "all": 0.01}
    assert views._realized_by_book([], []) == {}
    # A book with only removed deployments still says so.
    assert views._realized_by_book([], [{"mode": "live", "realized_pnl": Decimal("-3")}]) == \
        {"live": {"listed": 0.0, "removed": -3.0, "removed_deployments": 1, "all": -3.0}}


def test_the_deploy_board_sends_each_books_removed_total_and_its_copy_rows(monkeypatch):
    monkeypatch.setattr(demo_twins, "DEMO_TWINS", True)
    deps = [_dep(id=1, mode="paper", status="paused", status_reason="By you", realized_pnl=Decimal("146.04")),
            _dep(id=2, mode="demo", status="paused", status_reason=COPY)]
    removed = [{"id": 5, "strategy_id": 3, "mode": "paper", "realized_pnl": Decimal("5.72"), "closed_trades": 4}]
    monkeypatch.setattr(dep_routes.book_memo, "BookMemo", lambda cur, uid: "memo")
    monkeypatch.setattr(dep_routes.book_memo, "deployments_for_display", lambda memo: [dict(d) for d in deps])
    monkeypatch.setattr(dep_routes.book_memo, "deployment_curves", lambda memo, ids: {})
    monkeypatch.setattr(dep_routes.book_memo, "removed_deployments", lambda memo: removed)
    monkeypatch.setattr(dep_routes, "_backtest_checks", lambda *a: {})
    monkeypatch.setattr(dep_routes, "_deploy_roads", lambda *a: {})
    monkeypatch.setattr(dep_routes, "_demo_health", lambda *a: None)
    monkeypatch.setattr(dep_routes.repo, "user_positions", lambda *a: [])
    monkeypatch.setattr(dep_routes.page_poll, "answer", lambda body, v: body)
    out = dep_routes.list_deployments(SimpleNamespace(cur=None, uid=7, query={}))
    assert out["realized_by_book"] == {"paper": {"listed": 146.04, "removed": 5.72, "removed_deployments": 1, "all": 151.76},
                                       "demo": {"listed": 0.0, "removed": 0.0, "removed_deployments": 0}}
    copy = next(r for r in out["deployments"] if r["id"] == 2)
    assert copy["resume_block"] == "Resume its paper deployment first: this demo copy resumes with it."
    assert copy["status_why"].startswith("Waiting on its paper deployment, which is paused")
    assert next(r for r in out["deployments"] if r["id"] == 1)["resume_block"] is None


def test_the_strategy_page_lists_its_removed_deployments(monkeypatch):
    removed = [{"id": 9, "strategy_id": 4, "mode": "paper", "market": "btc15m", "created_at": datetime(2026, 10, 2),
                "removed_at": datetime(2026, 10, 20), "title": "Walk"},
               {"id": 8, "strategy_id": 4, "mode": "demo", "market": "btc15m", "created_at": datetime(2026, 9, 28),
                "removed_at": datetime(2026, 10, 1), "title": "Walk"}]
    reads = []
    monkeypatch.setattr(strategy_routes.repo, "removed_deployments", lambda cur, uid, sid: [dict(r) for r in removed])
    monkeypatch.setattr(strategy_routes.repo, "deployment_closed_totals",
                        lambda cur, ids: reads.append(ids) or {9: (14, Decimal("5.7249"))})
    rows = strategy_routes._removed_with_totals(None, 7, 4)
    assert reads == [[9, 8]]
    assert [views._past_deployment_out(r) for r in rows] == [
        {"id": 9, "mode": "paper", "created_at": datetime(2026, 10, 2), "removed_at": datetime(2026, 10, 20),
         "realized_pnl": 5.72, "closed_trades": 14},
        {"id": 8, "mode": "demo", "created_at": datetime(2026, 9, 28), "removed_at": datetime(2026, 10, 1),
         "realized_pnl": 0.0, "closed_trades": 0}]
    # None removed: no position read at all.
    monkeypatch.setattr(strategy_routes.repo, "removed_deployments", lambda cur, uid, sid: [])
    reads.clear()
    assert strategy_routes._removed_with_totals(None, 7, 4) == [] and reads == []
