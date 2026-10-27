"""Track record math (app/trading/track_record.py): pure functions over repo.track_record_rows output."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.trading import track_record as tr
from app.web.routes import dashboard as dashboard_routes


def _swap_track_cache(monkeypatch, value):
    """Swap the track-record cache everywhere it is bound: the dashboard routes read it, app.web.caches
    drops it, app.server keeps the name."""
    from app import server
    from app.web import caches
    from app.web.routes import dashboard
    for mod in (server, caches, dashboard):
        monkeypatch.setattr(mod, "_TRACK_RECORD", value)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def row(mode="paper", pnl=1.0, opened=None, closed=None, cost=10.0, fees=0.1, sid=1, title="S1",
        ref="sim:x", open_slices=0):
    closed = closed if closed is not None else NOW - timedelta(days=1)
    return {"mode": mode, "strategy_id": sid, "title": title, "market": "btc_15m", "order_ref": ref,
            "open_slices": open_slices, "pnl": pnl, "fees": fees, "cost": cost,
            "opened_at": (opened or closed - timedelta(minutes=10)).replace(tzinfo=None),
            "closed_at": closed.replace(tzinfo=None) if closed else None}


def test_empty_book_reports_no_trades_in_every_bucket():
    out = tr.build([], NOW)
    assert set(out["modes"]) == {"live", "demo", "paper"}
    for m in out["modes"].values():
        assert m["trades"] == 0 and m["sample"]["level"] == "none"
        assert m["sharpe"] is None and m["win_rate"] is None and m["curve"] == []
    assert out["default_mode"] == "paper"


def test_modes_never_mix_and_default_prefers_live():
    out = tr.build([row("paper", 5), row("live", -2, ref="k1"), row("demo", 1, ref="d1")], NOW)
    assert out["modes"]["paper"]["net_pnl"] == 5
    assert out["modes"]["live"]["net_pnl"] == -2
    assert out["modes"]["demo"]["net_pnl"] == 1
    assert out["default_mode"] == "live"


def test_default_tab_prefers_paper_over_a_demo_copy():
    """Without live trades the record opens on paper, the book that carries the evidence, even when the
    demo sandbox copy has trades too; demo opens only when it is the one book with a closed trade."""
    paper_and_demo = [row("paper", 5, ref="sim:%d" % i) for i in range(3)] + [row("demo", 1, ref="d1")]
    assert tr.build(paper_and_demo, NOW)["default_mode"] == "paper"
    assert tr.build([row("demo", 1, ref="d1")], NOW)["default_mode"] == "demo"
    # Only instant paper fills (left out of the record) leave paper with no trade: demo opens.
    assert tr.build([row("paper", 5, ref=None), row("demo", 1, ref="d1")], NOW)["default_mode"] == "demo"


def test_instant_paper_fills_are_excluded_but_counted():
    out = tr.build([row("paper", 3, ref="sim:a"), row("paper", 100, ref=None), row("paper", 100, ref="legacy")], NOW)
    p = out["modes"]["paper"]
    assert p["trades"] == 1 and p["net_pnl"] == 3 and p["excluded_instant_fills"] == 2


def test_live_without_order_ref_still_counts():
    assert tr.build([row("live", 2, ref=None)], NOW)["modes"]["live"]["trades"] == 1


def test_partly_open_trade_is_open_not_closed():
    out = tr.build([row("paper", 4, open_slices=1), row("paper", 1)], NOW)
    p = out["modes"]["paper"]
    assert p["trades"] == 1 and p["open_trades"] == 1 and p["net_pnl"] == 1
    # What its sold slice realized is reported beside the record, and only the held part is at cost.
    part = dict(row("paper", 4, cost=10.0, open_slices=1), open_cost=6.0)
    p = tr.build([part, row("paper", 1)], NOW)["modes"]["paper"]
    assert p["open_realized_pnl"] == 4 and p["open_cost"] == 6 and "open_at_cost" not in p
    assert p["net_pnl"] + p["open_realized_pnl"] == 5  # every closed row's P&L


def test_open_trades_are_at_cost_plus_fees_summed_exactly_then_rounded_once():
    # The repository's open_cost is contracts x entry price + entry fee for what is still held (the dashboard's
    # open_cost basis). Three trades of $0.3350 each: $1.0050 exactly, $1.01 rounded once. Rounded one by one
    # ($0.34 x 3) or added as floats it could read $1.02 or $1.00.
    held = [dict(row("paper", 0, cost=0.30, open_slices=1, ref="sim:o%d" % i), open_cost=Decimal("0.3350")) for i in range(3)]
    p = tr.build(held + [row("paper", 1)], NOW)["modes"]["paper"]
    assert p["open_trades"] == 3 and p["open_cost"] == 1.01
    # Floats from a cache that went through JSON add up the same.
    p = tr.build([dict(t, open_cost=0.335) for t in held] + [row("paper", 1)], NOW)["modes"]["paper"]
    assert p["open_cost"] == 1.01


def test_win_rate_drawdown_and_profit_factor():
    base = NOW - timedelta(days=5)
    pnls = [2, -1, -3, 4, 1]
    rows = [row("paper", p, closed=base + timedelta(hours=i)) for i, p in enumerate(pnls)]
    p = tr.build(rows, NOW)["modes"]["paper"]
    assert p["trades"] == 5 and p["wins"] == 3 and p["losses"] == 2
    assert p["win_rate"] == 0.6
    assert p["net_pnl"] == 3
    # cumulative: 2, 1, -2, 2, 3 -> worst drop from the 2 peak to -2
    assert p["max_drawdown"] == 4
    assert p["current_drawdown"] == 0
    assert p["profit_factor"] == round(7 / 4, 2)
    assert p["best"] == 4 and p["worst"] == -3
    lo, hi = p["win_rate_ci"]
    assert lo < 0.6 < hi
    assert [pt[1] for pt in p["curve"]] == [2, 1, -2, 2, 3]


def test_small_sample_is_labeled_too_early_and_hides_sharpe():
    p = tr.build([row("paper", 1)] * 5, NOW)["modes"]["paper"]
    assert p["sample"]["level"] == "thin"
    assert "Too early to judge" in p["sample"]["text"]
    assert p["sharpe"] is None and p["psr"] is None
    assert p["annualized_return"] is None


def test_sharpe_needs_variance_and_enough_days():
    start = NOW - timedelta(days=40)
    rows = [row("paper", 1.0 + (i % 3) * 0.5 - 0.4, closed=start + timedelta(days=i)) for i in range(40)]
    p = tr.build(rows, NOW)["modes"]["paper"]
    assert p["days"] >= tr.MIN_SHARPE_DAYS
    assert p["sharpe"] is not None and p["sharpe"] > 0
    assert 0.5 < p["psr"] <= 1.0
    assert p["sample"]["level"] == "early"
    assert p["sample"]["edge"] == "positive"
    assert p["annualized_return"] is None  # 40 days is too short to annualize


def test_flat_days_count_in_the_daily_series():
    start = NOW - timedelta(days=20)
    days = tr.daily_series([{"pnl": 1.0, "closed_ts": int(start.timestamp())}], NOW.date())
    assert len(days) == 21 and sum(days) == 1.0 and days.count(0.0) == 20


def test_peak_capital_counts_overlap_and_open_positions():
    # two overlapping $10 trades, then one after; plus a $5 position still open
    spans = [(0, 100, 10.0), (50, 150, 10.0), (200, 300, 10.0), (250, None, 5.0)]
    assert tr.peak_capital(spans) == 20.0
    # a close and an open at the same second do not stack
    assert tr.peak_capital([(0, 100, 10.0), (100, 200, 10.0)]) == 10.0


def test_return_and_drawdown_pct_use_required_capital():
    rows = [row("paper", 2, cost=50, closed=NOW - timedelta(days=2)), row("paper", -1, cost=50, closed=NOW - timedelta(days=1))]
    p = tr.build(rows, NOW)["modes"]["paper"]
    assert p["peak_at_risk"] == 50
    assert p["capital"] == 51  # peak at risk + the $1 worst drawdown
    assert p["return"] == pytest.approx(1 / 51, abs=1e-4)
    assert p["max_drawdown_pct"] == pytest.approx(1 / 51, abs=1e-4)


def test_by_strategy_and_monthly():
    rows = [row("paper", 5, sid=1, title="A", closed=datetime(2026, 9, 30, tzinfo=timezone.utc)),
            row("paper", -1, sid=2, title="B", closed=datetime(2026, 10, 2, tzinfo=timezone.utc)),
            row("paper", 2, sid=1, title="A", closed=datetime(2026, 10, 3, tzinfo=timezone.utc))]
    p = tr.build(rows, NOW)["modes"]["paper"]
    strat = p["strategies"]
    assert [s["title"] for s in strat] == ["A", "B"]
    assert strat[0]["trades"] == 2 and strat[0]["net_pnl"] == 7 and strat[0]["edge"] == "thin"
    assert [(m["month"], m["pnl"], m["trades"]) for m in p["monthly"]] == [("2026-10", 1, 2), ("2026-09", 5, 1)]


def test_a_month_with_no_trades_keeps_its_row_through_this_month():
    # July and September had no closes: they read as months with no trades, not as missing ones,
    # and the grid runs to this month (October) even when the last close was earlier.
    rows = [row("paper", 3, closed=datetime(2026, 6, 20, tzinfo=timezone.utc)),
            row("paper", -1, closed=datetime(2026, 8, 5, tzinfo=timezone.utc))]
    months = tr.build(rows, NOW)["modes"]["paper"]["monthly"]
    assert [(m["month"], m["trades"], m["pnl"], m["win_rate"]) for m in months] == [
        ("2026-10", 0, 0, None), ("2026-09", 0, 0, None), ("2026-08", 1, -1, 0), ("2026-07", 0, 0, None), ("2026-06", 1, 3, 1)]
    # A year boundary steps December into January; no trades at all means no rows.
    assert [m["month"] for m in tr.monthly([{"closed_ts": int(datetime(2025, 11, 3, tzinfo=timezone.utc).timestamp()), "pnl": 1}],
                                           date(2026, 1, 9))] == ["2026-01", "2025-12", "2025-11"]
    assert tr.monthly([], date(2026, 1, 9)) == []


def test_longest_drawdown_runs_to_now_when_still_under():
    base = NOW - timedelta(days=10)
    rows = [row("paper", 5, closed=base), row("paper", -3, closed=base + timedelta(days=1))]
    p = tr.build(rows, NOW)["modes"]["paper"]
    assert p["current_drawdown"] == 3
    assert p["longest_drawdown_days"] == pytest.approx(10.0, abs=0.1)


def test_curve_is_thinned_but_stats_use_every_trade():
    start = NOW - timedelta(days=30)
    rows = [row("paper", 1, closed=start + timedelta(minutes=i)) for i in range(1000)]
    p = tr.build(rows, NOW)["modes"]["paper"]
    assert p["trades"] == 1000 and p["net_pnl"] == 1000
    assert len(p["curve"]) == tr.CURVE_POINTS and p["curve"][-1][1] == 1000


def test_a_one_trade_crash_survives_thinning_and_the_end_is_exact():
    # A crash that recovers on the next trade. The old every-Nth thinner kept indexes 0, 2, 5, 7, ...
    # and stepped over it: the drawn curve showed no drawdown while max_drawdown (full series) said $800.
    start = NOW - timedelta(days=30)
    pnls = [1.0] * 999
    pnls[614], pnls[615] = -800.0, 800.0
    assert 614 not in [int(i * 999 / 399) for i in range(399)]  # the old rule's picks
    rows = [row("paper", p, closed=start + timedelta(minutes=i)) for i, p in enumerate(pnls)]
    p = tr.build(rows, NOW)["modes"]["paper"]
    curve = p["curve"]
    assert len(curve) <= tr.CURVE_POINTS
    bottom = [int((start + timedelta(minutes=614)).timestamp()), 614 - 800]
    assert bottom in curve and min(v for _, v in curve) == 614 - 800  # the crash, as the real point
    assert curve[-1] == [int((start + timedelta(minutes=998)).timestamp()), sum(pnls)]  # the end, exact
    assert curve[0] == [int(start.timestamp()), 1.0]
    assert [ts for ts, _ in curve] == sorted(ts for ts, _ in curve)  # still in time order
    # The stats come from every trade, never the thinned curve.
    assert p["max_drawdown"] == 800 and p["trades"] == 999 and p["net_pnl"] == sum(pnls)


def test_the_underwater_series_comes_from_every_trade_and_bottoms_at_max_drawdown():
    # A drop inside one run of the thinned equity curve: up $50, back down, then up $100. Thinning
    # keeps that run's low (the flat start) and high ($100), losing the $50 peak, so an underwater
    # chart derived from the thinned curve showed no drawdown at all. The server's series doesn't.
    start = NOW - timedelta(days=60)
    n, i0 = 5000, 1000
    pnls = [0.0] * n
    pnls[i0], pnls[i0 + 1], pnls[i0 + 2] = 50.0, -50.0, 100.0
    run = next(r for r in tr._runs(n, (tr.CURVE_POINTS - 2) // 2) if r[0] <= i0 < r[1])
    assert run[0] < i0 and i0 + 2 < run[1]  # all three trades sit inside one run
    rows = [row("paper", p, closed=start + timedelta(minutes=i)) for i, p in enumerate(pnls)]
    p = tr.build(rows, NOW)["modes"]["paper"]
    assert p["max_drawdown"] == 50
    peak, derived = float("-inf"), []
    for _, v in p["curve"]:  # what the browser used to do with the thinned curve
        peak = max(peak, v)
        derived.append(v - peak)
    assert min(derived) == 0  # the drawdown was invisible
    uw = p["underwater"]
    assert len(uw) <= tr.CURVE_POINTS
    assert min(v for _, v in uw) == -p["max_drawdown"]  # exactly the figure beside it
    assert [int((start + timedelta(minutes=i0 + 1)).timestamp()), -50.0] in uw
    assert uw[0] == [int(start.timestamp()), 0.0]
    assert uw[-1] == [int((start + timedelta(minutes=n - 1)).timestamp()), 0.0]


@pytest.mark.parametrize("pnls", [
    [-5.0, 2.0, 1.0],                          # under water from the first trade (the 0 before it counts)
    [1.2345, -0.0050, -1.2299, 3.0, -0.0001],  # odd cents: the deepest point still rounds like the figure
    [0.1] * 30 + [-0.3] * 7 + [0.2] * 900,     # a drawdown longer than one thinning run
])
def test_the_underwater_low_equals_max_drawdown_to_the_cent(pnls):
    start = NOW - timedelta(days=30)
    rows = [row("paper", p, closed=start + timedelta(minutes=i)) for i, p in enumerate(pnls)]
    p = tr.build(rows, NOW)["modes"]["paper"]
    assert min(v for _, v in p["underwater"]) == -p["max_drawdown"]
    assert all(v <= 0 for _, v in p["underwater"]) and len(p["underwater"]) <= tr.CURVE_POINTS


def test_thin_lows_keeps_the_ends_and_each_runs_lowest_point():
    s = [[i, v] for i, v in enumerate([0, -1, -4, -2, 0, -3, -3, -9, 0, -2])]
    assert tr.thin_lows(s, 10) is s
    assert tr.thin_lows(s, 4) == [[0, 0], [2, -4], [7, -9], [9, -2]]  # 2 runs of 4: [-1,-4,-2,0], [-3,-3,-9,0]
    with pytest.raises(ValueError):
        tr.thin_lows(s, 2)


def test_thin_min_max_keeps_each_runs_low_and_high():
    curve = [[i, v] for i, v in enumerate([0, 5, -3, 2, 9, 1, 4, -8, 6, 7])]
    assert tr.thin_min_max(curve, 10) is curve  # under the cap: untouched
    out = tr.thin_min_max(curve, 6)  # first, last, and 2 runs of 4 inner points: low + high each
    assert out == [[0, 0], [2, -3], [4, 9], [7, -8], [8, 6], [9, 7]]
    assert len(tr.thin_min_max([[i, 0.0] for i in range(1000)], 400)) <= 400  # a flat run gives one point
    for cap in (4, 5, 401, 400):
        out = tr.thin_min_max([[i, (i * 37) % 11] for i in range(1000)], cap)
        assert len(out) <= cap and out[0] == [0, 0] and out[-1] == [999, (999 * 37) % 11]
    with pytest.raises(ValueError):
        tr.thin_min_max(curve, 3)


def test_wilson_interval_is_bounded_and_sane():
    assert tr.wilson(0, 0) is None
    lo, hi = tr.wilson(0, 10)
    assert lo == 0.0 and 0 < hi < 0.35
    lo, hi = tr.wilson(10, 10)
    assert hi == 1.0 and lo > 0.65


# -- /api/track-record ---------------------------------------------------------------------

def _ctx(uid=7):
    from types import SimpleNamespace
    from app import server
    return server.Ctx(SimpleNamespace(cursor=lambda: object()), {"id": uid, "autopilot": 0}, (), {}, {}, None)


def test_endpoint_builds_from_repo_rows_and_caches_per_user(monkeypatch):
    from app import server
    calls = []
    _swap_track_cache(monkeypatch, {})
    monkeypatch.setattr(dashboard_routes, "_BOOK_SHAPE", {})
    monkeypatch.setattr(dashboard_routes, "TRACK_RECORD_CACHE_MIN_TRADES", 1)  # a busy book: one trade is enough here
    monkeypatch.setattr(server.book_memo, "track_record",
                        lambda cur, uid: calls.append(uid) or tr.build([row("live", 3, ref="k")]))
    out = server.get_track_record(_ctx(7))
    assert out["default_mode"] == "live" and out["modes"]["live"]["net_pnl"] == 3
    server.get_track_record(_ctx(7))
    server.get_track_record(_ctx(8))
    assert calls == [7, 8]  # second read for user 7 came from the cache
    monkeypatch.setattr(server.time, "time", lambda: 10 ** 10)  # past the TTL
    server.get_track_record(_ctx(7))
    assert calls == [7, 8, 7]


def test_a_new_users_record_is_read_fresh_so_the_first_trade_shows_at_once(monkeypatch):
    # Onboarding: the record was read empty, then the first trade closed. The cached empty record
    # stayed up for a minute under a board that already showed the trade.
    from app import server
    book = []
    _swap_track_cache(monkeypatch, {})
    monkeypatch.setattr(dashboard_routes, "_BOOK_SHAPE", {})
    monkeypatch.setattr(server.book_memo, "track_record", lambda cur, uid: tr.build(list(book)))
    assert server.get_track_record(_ctx(7))["modes"]["paper"]["trades"] == 0
    book.append(row("paper", 2.5))
    assert server.get_track_record(_ctx(7))["modes"]["paper"]["trades"] == 1


def test_a_busy_record_is_rebuilt_once_the_dashboard_sees_a_trade_it_predates(monkeypatch):
    from app import server
    calls = []
    _swap_track_cache(monkeypatch, {})
    monkeypatch.setattr(dashboard_routes, "_BOOK_SHAPE", {})
    monkeypatch.setattr(dashboard_routes, "TRACK_RECORD_CACHE_MIN_TRADES", 1)
    monkeypatch.setattr(server.book_memo, "track_record", lambda cur, uid: calls.append(uid) or tr.build([row("paper", 1)]))
    dashboard_routes._BOOK_SHAPE[7] = dashboard_routes._book_shape({"paper": 1}, 0)
    server.get_track_record(_ctx(7)); server.get_track_record(_ctx(7))
    assert calls == [7]
    dashboard_routes._BOOK_SHAPE[7] = dashboard_routes._book_shape({"paper": 1}, 1)  # the dashboard saw a trade open
    server.get_track_record(_ctx(7)); server.get_track_record(_ctx(7))
    assert calls == [7, 7]
    dashboard_routes._BOOK_SHAPE[7] = dashboard_routes._book_shape({"paper": 2}, 0)  # ... and close
    server.get_track_record(_ctx(7))
    assert calls == [7, 7, 7]


def test_the_users_own_deploy_and_stop_drop_their_cached_record(monkeypatch):
    from app import server
    _swap_track_cache(monkeypatch, {7: (10 ** 10, {}, 999, None), 8: (10 ** 10, {}, 999, None)})
    monkeypatch.setattr(server.repo, "get_deployment", lambda cur, uid, dep_id: {"id": dep_id, "status": "running", "mode": "paper", "spec": {}, "market": "btc15m"})
    monkeypatch.setattr(server.repo, "set_deployment_status", lambda *a: True)
    ctx = _ctx(7)
    ctx.params = ("5", "pause")
    assert server.deployment_action(ctx) == {"ok": True, "status": "paused"}
    assert 7 not in server._TRACK_RECORD and 8 in server._TRACK_RECORD


def test_endpoint_surfaces_a_db_failure_and_caches_nothing(monkeypatch):
    from app import server
    _swap_track_cache(monkeypatch, {})

    def boom(cur, uid):
        raise RuntimeError("db down")

    monkeypatch.setattr(server.book_memo, "track_record", boom)
    with pytest.raises(RuntimeError):
        server.get_track_record(_ctx(7))
    assert server._TRACK_RECORD == {}


def test_track_record_route_and_spa_path_are_registered():
    from app import server
    assert server.SPA_ROUTES.match("/track-record")
    assert any(m == "GET" and rx.match("/api/track-record") and fn is server.get_track_record
               for m, rx, fn, _ in server.ROUTES)


def test_a_thin_sample_makes_no_confidence_claim_about_the_average_trade():
    # Five wins in a row: a normal range on 5 trades excludes zero, and the page used to say
    # "above zero at 95% confidence" under "Too early to judge".
    p = tr.build([row("live", 1.5 + i * 0.1, ref="k%d" % i) for i in range(5)], NOW)["modes"]["live"]
    assert p["avg_trade_ci"][0] > 0
    assert p["sample"]["level"] == "thin" and p["sample"]["edge"] == "thin"
    assert "confidence" not in p["sample"]["text"] and "Too early to judge" in p["sample"]["text"]
    # From MIN_TRADES on, the read is made (a span under 14 days is still thin).
    rows = [row("paper", 1.0 + (i % 3) * 0.1, ref="sim:%d" % i, closed=NOW - timedelta(hours=i)) for i in range(tr.MIN_TRADES)]
    p = tr.build(rows, NOW)["modes"]["paper"]
    assert p["sample"]["level"] == "thin" and p["sample"]["edge"] == "positive"
    assert "above zero at 95% confidence" in p["sample"]["text"]


def test_stopped_and_removed_strategies_stay_in_and_say_so():
    rows = [dict(row("paper", 2, sid=1, title="Running one", ref="sim:a"), dep_status="running"),
            dict(row("paper", -5, sid=2, title="Stopped one", ref="sim:b"), dep_status="stopped"),
            # A strategy deleted after its deployment stopped: the strategy row is gone, its trades are not.
            dict(row("paper", -3, sid=3, title=None, ref="sim:c"), dep_status="stopped"),
            # Redeployed: one stopped deployment and one paused one read as paused.
            dict(row("paper", 1, sid=4, title="Twice", ref="sim:d"), dep_status="stopped"),
            dict(row("paper", 1, sid=4, title="Twice", ref="sim:e"), dep_status="paused")]
    p = tr.build(rows, NOW)["modes"]["paper"]
    assert p["trades"] == 5 and p["net_pnl"] == -4  # nothing dropped from the totals
    by = {s["strategy_id"]: s for s in p["strategies"]}
    assert (by[1]["status"], by[1]["removed"]) == ("running", False)
    assert by[2]["status"] == "stopped" and by[2]["net_pnl"] == -5
    assert by[3]["removed"] is True and by[3]["title"] == "Deleted strategy" and by[3]["trades"] == 1
    assert by[4]["status"] == "paused" and by[4]["trades"] == 2
    assert tr.build([row("paper", 1)], NOW)["modes"]["paper"]["strategies"][0]["status"] is None  # unknown stays unknown
    assert any("Stopped strategies" in line for line in tr.METHOD)
