"""Where the paper "after typical live slippage" estimate rides, and where it never goes.

Beside paper realized P&L on the three pages that make it a headline (the dashboard's paper figure, the
strategy page's "Since deploying", the track record's paper tab), from data those pages already read:
the same pass that sums each book's P&L sums its closed rows' contract fills. It never replaces or
changes a figure, never appears for live or demo, and no gate, gate input or engine module reads it.
"""
import ast
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app import server
from app.adapters.db import deployment_repository, position_repository
from app.research import agent, gatekeeper
from app.services import forward_gate
from app.trading import engine
from app.trading import track_record as tr
from app.web import views
from app.web.routes import dashboard as dashboard_routes
from app.web.routes import deployments as deployment_routes
from app.web.routes import strategies as strategy_routes
from tests.test_app_auth_and_api import ctx

ROOT = Path(__file__).resolve().parents[1]


class _Rows:
    """A cursor that answers one read with `rows` and logs every statement."""

    def __init__(self, rows):
        self.rows, self.log = rows, []

    def execute(self, sql, params=()):
        self.log.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows


def _book_rows():
    # closed_book_totals' grouped pass: per (book, deployment), the P&L sums and now `f`, the contract fills.
    return [{"mode": "paper", "deployment_id": 1, "p_all": Decimal("3.2000"), "p_since": Decimal("0"), "n": 3, "f": 20},
            {"mode": "paper", "deployment_id": 2, "p_all": Decimal("-0.5000"), "p_since": Decimal("0"), "n": 1, "f": 4},
            {"mode": "live", "deployment_id": 3, "p_all": Decimal("9.0000"), "p_since": Decimal("0"), "n": 2, "f": 40},
            {"mode": "demo", "deployment_id": 4, "p_all": Decimal("1.0000"), "p_since": Decimal("0"), "n": 1, "f": 2}]


def test_the_books_pass_sums_each_books_fills_in_the_same_read():
    cur = _Rows(_book_rows())
    day = datetime(2026, 10, 27)
    realized, closed, recent, by_dep, fills = position_repository.closed_book_totals(cur, 7, day, day, split=True, fills=True)
    assert len(cur.log) == 1  # one read, as before
    sql = cur.log[0][0]
    assert "qty * (CASE WHEN close_reason='settled' THEN 1 ELSE 2 END)" in sql and "FORCE INDEX (idx_pos_user)" in sql
    assert fills == {"paper": 24, "live": 40, "demo": 2}  # each book's own, never added together
    assert realized["paper"][0] == 2.7 and closed == {"paper": 4, "live": 2, "demo": 1}
    # Callers that don't ask for fills get the shapes they always had.
    assert len(position_repository.closed_book_totals(_Rows(_book_rows()), 7, day)) == 3
    assert len(position_repository.closed_book_totals(_Rows(_book_rows()), 7, day, day, split=True)) == 4


def _dashboard(monkeypatch, fills):
    zero = {m: (0.0, 0.0) for m in ("paper", "demo", "live")}
    realized = dict(zero, paper=(2.7, 0.0), live=(9.0, 0.0), demo=(1.0, 0.0))
    for name, fn in {
        "user_positions": lambda *a, **k: [], "list_deployments_for_display": lambda *a, **k: [], "deployment_curves": lambda *a, **k: {},
        "paper_ledger_summary": lambda cur, uid: {"balance": 1002.7, "deposited": 1000.0, "reset_at": None},
        "paper_ledger_version": lambda cur, uid: (2, 9),
        "closed_book_totals": lambda cur, uid, since, visit=None, split=False, fills=False: (
            realized, {"paper": 4, "live": 2, "demo": 1}, {m: (0.0, 0) for m in ("paper", "demo", "live")})
        + (({},) if split else ()) + ((fills_by_book,) if fills else ()),
        "daily_pnl": lambda *a, **k: [],
        "activity_since": lambda cur, uid, since: {"autopilot": {}, "runs": {}},
        "passed_since": lambda cur, uid, since, **k: {"n": 0, "items": []},
        "demo_equity": lambda cur, uid, realized=None: {"capital": 500.0, "equity": 501.0, "realized": 1.0, "roi": .002, "before_reload": 0},
        "get_kalshi_key": lambda cur, uid: None, "open_reconcile_rows": lambda cur, uid: [],
        "active_run_counts": lambda cur, uid, **kw: {},
    }.items():
        monkeypatch.setattr(server.repo, name, fn)
    fills_by_book = fills
    monkeypatch.setattr(dashboard_routes, "_freshness", lambda cur: {})
    monkeypatch.setattr(server.book_memo, "_LEDGER", {})
    return server.dashboard(ctx())


def test_the_dashboard_shows_it_beside_paper_realized_pnl_only(monkeypatch):
    out = _dashboard(monkeypatch, {"paper": 24, "live": 40, "demo": 2})
    paper = out["paper"]
    # Realized P&L is exactly what it was; the estimate rides beside it: $2.70 less 24 fills x 0.5c.
    assert paper["realized_pnl"] == 2.7
    assert paper["slippage_estimate"] == {"pnl": 2.58, "per_fill_cents": 0.5}
    assert "slippage_estimate" not in out["live"] and "slippage_estimate" not in out["demo"]
    assert out["live"]["realized_pnl"] == 9.0
    # No closed paper fill yet: nothing to estimate.
    assert _dashboard(monkeypatch, {"live": 40})["paper"]["slippage_estimate"] is None


def _dep(sid, mode, pnl, trades, fills, dep_id):
    return {"id": dep_id, "strategy_id": sid, "mode": mode, "status": "running", "realized_pnl": Decimal(pnl),
            "closed_trades": trades, "open_positions": 0, "contract_fills": fills}


def test_since_deploying_sums_each_books_fills_and_estimates_paper_only():
    deps = [_dep(7, "paper", "1.2000", 2, 8, 1), _dep(7, "paper", "2.0000", 3, 12, 2),
            _dep(7, "live", "5.0000", 4, 16, 3), _dep(7, "demo", "0.4000", 1, 2, 4), _dep(8, "paper", "-0.3000", 1, 1, 5)]
    books = strategy_routes._book_totals(deps)
    # Paper: $3.20 over 20 contract fills (both its deployments, never the live or demo ones) = $3.10.
    assert books[7]["paper"]["pnl"] == 3.2
    assert books[7]["paper"]["slippage_estimate"] == {"pnl": 3.10, "per_fill_cents": 0.5}
    assert "slippage_estimate" not in books[7]["live"] and "slippage_estimate" not in books[7]["demo"]
    assert books[7]["live"]["pnl"] == 5.0
    # Another strategy's paper book is its own: -$0.30 less half a cent, rounded once half up.
    assert books[8]["paper"]["slippage_estimate"]["pnl"] == -0.31
    # A paper book with no closed trade carries none.
    assert "slippage_estimate" not in strategy_routes._book_totals([_dep(9, "paper", "0", 0, 0, 6)])[9]["paper"]


def test_the_strategies_lists_paper_card_carries_its_books_estimate_and_a_live_card_none(monkeypatch):
    # The list's card shows one book (live, else paper, else demo) from _book_totals: a paper card carries its
    # paper book's estimate; a live card shows live and carries none; a paper card's demo beside it, none.
    deps = [_dep(7, "paper", "1.2000", 2, 8, 1), _dep(7, "demo", "0.4000", 1, 2, 2),
            _dep(8, "live", "5.0000", 4, 16, 3), _dep(8, "paper", "2.0000", 3, 12, 4)]
    monkeypatch.setattr(strategy_routes.book_memo, "deployments_for_display", lambda memo: [dict(d) for d in deps])
    monkeypatch.setattr(strategy_routes.book_memo, "realistic_paper_closed", lambda memo, ids: {i: 99 for i in ids})
    cards = [{"id": 7, "deployed": True}, {"id": 8, "deployed": True}]
    strategy_routes._attach_real_records(object(), 1, cards)
    assert cards[0]["real"]["mode"] == "paper" and cards[0]["real"]["slippage_estimate"] == {"pnl": 1.16, "per_fill_cents": 0.5}
    assert "slippage_estimate" not in cards[0]["real"]["demo"]
    assert cards[1]["real"]["mode"] == "live" and "slippage_estimate" not in cards[1]["real"]


def test_the_deploy_boards_paper_realized_carries_the_listed_deployments_estimate_only():
    deps = [_dep(7, "paper", "1.2000", 2, 8, 1), _dep(8, "paper", "2.0000", 3, 12, 2),
            _dep(7, "live", "5.0000", 4, 16, 3), _dep(7, "demo", "0.4000", 1, 2, 4)]
    removed = [{"mode": "paper", "realized_pnl": Decimal("-0.3000")}, {"mode": "live", "realized_pnl": Decimal("1.0000")}]
    books = deployment_routes._realized_with_estimate(deps, removed)
    # Beside `listed` ($3.20 over 20 fills), never in place of it; the removed and "in all" figures are as before.
    assert books["paper"] == {"listed": 3.2, "removed": -0.3, "removed_deployments": 1, "all": 2.9,
                              "slippage_estimate": {"pnl": 3.10, "per_fill_cents": 0.5}}
    assert "slippage_estimate" not in books["live"] and "slippage_estimate" not in books["demo"]
    assert books["live"]["listed"] == 5.0
    # No listed paper deployment, or none with a closed trade: no estimate.
    assert "slippage_estimate" not in deployment_routes._realized_with_estimate([], removed)["paper"]
    assert "slippage_estimate" not in deployment_routes._realized_with_estimate([_dep(7, "paper", "0", 0, 0, 1)], [])["paper"]


def test_a_backtest_only_strategys_deploy_row_says_so_from_its_own_read():
    row = dict(_dep(7, "paper", "1.2000", 2, 8, 1), title="t", direction=None, market="btc15m", status_reason=None, wins=1,
               created_at=None, result={"out_of_sample": {"pnl": 6.0, "trades": 40}})
    assert views._deployment_out(dict(row, strategy_status="backtest-only"), [])["backtest_only"] is True
    assert views._deployment_out(dict(row, strategy_status="passed"), [])["backtest_only"] is False
    assert views._deployment_out(row, [])["backtest_only"] is False  # a read without it (the gates') claims nothing


def test_a_passed_strategy_with_no_gatekeeper_record_says_later_period_like_its_page():
    """Its page calls the backtest's later slice "Later-period P&L"; the row's own read says it has no record
    (no_gatekeeper_record, MySQL's 1/0), so the row's details say the same, not "Unseen P&L"."""
    row = dict(_dep(7, "paper", "1.2000", 2, 8, 1), title="t", direction=None, market="btc15m", status_reason=None, wins=1,
               created_at=None, result={"out_of_sample": {"pnl": 6.0, "trades": 40}})
    assert views._deployment_out(dict(row, strategy_status="passed", no_gatekeeper_record=1), [])["backtest_only"] is True
    assert views._deployment_out(dict(row, strategy_status="passed", no_gatekeeper_record=0), [])["backtest_only"] is False
    assert views._deployment_out(dict(row, strategy_status="passed", no_gatekeeper_record=None), [])["backtest_only"] is False


def test_the_autopilots_day_and_week_sum_their_fills_in_the_reads_they_already_make():
    cur = _Rows([{"mode": "paper", "p": Decimal("1.2340"), "f": 12}, {"mode": "live", "p": Decimal("-2.0000"), "f": 40}])
    pnl, fills = position_repository.realized_pnl_by_mode(cur, 7, ("live", "paper"), datetime(2026, 10, 27), fills=True)
    assert len(cur.log) == 1 and "qty * (CASE WHEN close_reason='settled' THEN 1 ELSE 2 END)" in cur.log[0][0]
    assert pnl == {"live": -2.0, "paper": 1.234} and fills == {"live": 40, "paper": 12}
    # Without `fills`, the read and its answer are as before.
    plain = _Rows([{"mode": "paper", "p": Decimal("1.2340")}])
    assert position_repository.realized_pnl_by_mode(plain, 7, ("live", "paper"), datetime(2026, 10, 27)) == {"live": 0.0, "paper": 1.234}
    assert "close_reason" not in plain.log[0][0]

    class _One(_Rows):
        def fetchone(self):
            return self.rows[0]

    week = _One([{"started": 1, "pnl": Decimal("3.2000"), "trades": 4, "fills": 30}])
    assert deployment_repository.autopilot_paper_week(week, 7, datetime(2026, 10, 20)) == {"started": 1, "pnl": 3.2, "trades": 4, "fills": 30}
    assert len(week.log) == 1 and "p.qty * (CASE WHEN p.close_reason='settled'" in week.log[0][0]


def _trade(mode, pnl, fills, ref="sim:1", open_slices=0, closed=True):
    now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
    return {"mode": mode, "strategy_id": 1, "title": "Fade", "market": "btc15m", "order_ref": ref, "open_slices": open_slices,
            "pnl": pnl, "fees": 0.1, "cost": 4.0, "contract_fills": fills,
            "opened_at": (now - timedelta(hours=1)).replace(tzinfo=None), "closed_at": now.replace(tzinfo=None) if closed else None}


def test_the_track_records_paper_tab_estimates_the_trades_in_its_record():
    rows = [_trade("paper", 2.0, 20), _trade("paper", 1.2, 4, ref="sim:2"),
            # Left out of the record, so out of its estimate too: an instant fill and a trade still part-open.
            _trade("paper", 9.0, 50, ref=None), _trade("paper", 0.5, 2, ref="sim:3", open_slices=1),
            _trade("live", 5.0, 10, ref="live:1"), _trade("demo", 1.0, 2, ref="demo:1")]
    out = tr.finish(tr.prepare(rows), datetime(2026, 10, 27, tzinfo=timezone.utc))
    paper = out["modes"]["paper"]
    assert paper["net_pnl"] == 3.2  # unchanged
    assert paper["slippage_estimate"] == {"pnl": 3.08, "per_fill_cents": 0.5}  # $3.20 less 24 x 0.5c
    assert out["modes"]["live"]["slippage_estimate"] is None and out["modes"]["demo"]["slippage_estimate"] is None
    assert out["modes"]["live"]["net_pnl"] == 5.0


def test_the_track_records_read_carries_each_trades_fills_from_the_same_grouped_read():
    cur = _Rows([{"mode": "paper", "deployment_id": 5, "order_ref": "sim:1", "v": "0,2.0000,0.1400,4.0000,0.0000,1761390000,1761390900,30"},
                 {"mode": "paper", "deployment_id": 5, "order_ref": "sim:2", "v": "1,0.0000,0.0700,4.0000,4.0700,1761390000,,0"}])
    trades = deployment_repository.track_record_trades(cur, 7)
    assert len(cur.log) == 1 and "CASE WHEN p.status='closed' THEN p.qty * (CASE WHEN p.close_reason='settled'" in cur.log[0][0]
    assert [t["contract_fills"] for t in trades] == [30, 0] and trades[1]["closed_s"] is None


# -- the gates never see it ----------------------------------------------------------------------------


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            yield from (a.name for a in node.names)


def test_only_the_three_display_pages_read_the_estimate():
    readers = sorted(str(p.relative_to(ROOT)) for top in ("app", "data_pipeline", "trading_core") for p in (ROOT / top).rglob("*.py")
                     if "trading_core.domain.slippage" in set(_imports(p)))
    # Display routes only: the dashboard, the strategy list and page, the Deploy board (deployments) and the
    # autopilot panel's status (chat), plus the track record's summary. No gate, engine or research module.
    assert readers == ["app/trading/track_record.py", "app/web/routes/chat.py", "app/web/routes/dashboard.py",
                       "app/web/routes/deployments.py", "app/web/routes/strategies.py"]


def test_the_gate_inputs_and_the_engine_never_read_it():
    # The paper -> live gate (agent.paper_evidence), its inputs (paper_round_trips, paper_fills_for_gate, the
    # engine/gate list_deployments), the forward gate, the gatekeeper and the engine: none reads the estimate,
    # the assumption or the contract fills, so promotion counts and trade decisions are exactly as before.
    gate_code = [inspect.getsource(f) for f in (agent.paper_evidence, deployment_repository.paper_round_trips,
                                                 deployment_repository.paper_fills_for_gate, deployment_repository.list_deployments,
                                                 deployment_repository.paper_round_trips_by_strategy)]
    gate_code += [deployment_repository._DEPLOYMENT_SELECT]
    gate_code += [inspect.getsource(m) for m in (forward_gate, gatekeeper, engine)]
    for src in gate_code:
        for word in ("slippage_estimate", "contract_fills", "LIVE_SLIPPAGE", "paper_estimate", "after_live_slippage"):
            assert word not in src
