"""Track record math (app/track_record.py): pure functions over repo.track_record_rows output."""
from datetime import datetime, timedelta, timezone

import pytest

from app import track_record as tr

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
    monkeypatch.setattr(server, "_TRACK_RECORD", {})
    monkeypatch.setattr(server.repo, "track_record_rows", lambda cur, uid: calls.append(uid) or [row("live", 3, ref="k")])
    out = server.get_track_record(_ctx(7))
    assert out["default_mode"] == "live" and out["modes"]["live"]["net_pnl"] == 3
    server.get_track_record(_ctx(7))
    server.get_track_record(_ctx(8))
    assert calls == [7, 8]  # second read for user 7 came from the cache
    monkeypatch.setattr(server.time, "time", lambda: 10 ** 10)  # past the TTL
    server.get_track_record(_ctx(7))
    assert calls == [7, 8, 7]


def test_endpoint_surfaces_a_db_failure_and_caches_nothing(monkeypatch):
    from app import server
    monkeypatch.setattr(server, "_TRACK_RECORD", {})

    def boom(cur, uid):
        raise RuntimeError("db down")

    monkeypatch.setattr(server.repo, "track_record_rows", boom)
    with pytest.raises(RuntimeError):
        server.get_track_record(_ctx(7))
    assert server._TRACK_RECORD == {}


def test_track_record_route_and_spa_path_are_registered():
    from app import server
    assert server.SPA_ROUTES.match("/track-record")
    assert any(m == "GET" and rx.match("/api/track-record") and fn is server.get_track_record
               for m, rx, fn, _ in server.ROUTES)
