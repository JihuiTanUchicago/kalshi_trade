"""Paper, demo and live never mix: one user, three deployments at once, every figure its own mode's.

One user runs a paper, a demo and a live deployment of three autopilot strategies at the same time,
on the SAME contracts (so a figure that filters by ticker or user instead of mode would leak), each
with a different stake so every mode's P&L is a different number. All three trade through the real
engine path: paper on the TradingLoop over the simulated venue, demo on the TradingLoop through its
kernel and order-intent log, live on the legacy kernel path with its order intents. Every kernel is
the live execution kernel over a SimulatedVenue: no real client exists in this test. Live is enabled
with the monkeypatch the existing live tests use (engine.LIVE_TRADING_ENABLED), never in code.

Each mode gets settlements (a win, a loss), a stop, and an open position; demo is reloaded between
its settlements and its stop. Then every money figure is read the way the app reads it and held to
its own mode's position rows, to the cent. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import csv
import io
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

MODES = ("paper", "demo", "live")
STAKES = {"paper": 10.0, "demo": 20.0, "live": 16.0}  # live trades a quarter of its size while new (the ramp)
STRIKE = 98.0


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.cursor().execute("UPDATE app_deployments SET status='stopped' WHERE user_id IN "
                       "(SELECT id FROM app_users WHERE google_sub LIKE 'test:%%')")
    c.close()


class _Feed:
    """The simulated venue's quotes: whatever book the current tick shows."""

    def __init__(self):
        self.snaps, self.sizes = {}, {}

    def set(self, snaps, sizes):
        self.snaps, self.sizes = {s.contract.ticker: s for s in snaps}, sizes

    def quote(self, ticker, max_age_seconds=None):
        from data_pipeline.common import utc_now
        from data_pipeline.market_data import Quote

        s = self.snaps.get(ticker)
        if s is None:
            return None
        return Quote(ticker=ticker, yes_bid=s.yes_bid, yes_ask=s.yes_ask, yes_bid_size=self.sizes[(ticker, "no")],
                     yes_ask_size=self.sizes[ticker], as_of=utc_now() - timedelta(seconds=0.1), source="websocket")


def _money(v):
    return round(float(v) + 1e-9, 2)


def test_paper_demo_and_live_figures_never_mix(conn, monkeypatch):
    from app import engine, server
    from app import repository as repo
    from app import spec as specmod
    from app.markets import Contract, snapshot
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
    from data_pipeline.architecture.simulated_venue import SimulatedVenue

    cur = conn.cursor()
    user = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "modes@example.com", "M", None)
    uid = user["id"]
    cur.execute("UPDATE app_users SET autopilot=1 WHERE id=%s", (uid,))
    deps = {}
    for mode in MODES:
        spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "exit": {"stop_loss": 0.1},
                                 "sizing": {"stake": STAKES[mode], "max_positions": 4}})
        sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Modes " + mode, "t", spec, "passed",
                                   {"capital": 4 * STAKES[mode]})
        repo.create_proposal(cur, uid, "deploy", "Autopilot", None, sid, "applied")  # the autopilot's own
        did = repo.create_deployment(cur, uid, sid, "btc15m", mode)
        deps[mode] = next(d for d in repo.running_deployments(cur, "btc15m") if d["id"] == did)

    tag = uuid.uuid4().hex[:6].upper()
    close = datetime.now(timezone.utc) + timedelta(minutes=10)
    W, L, S, H = ("MIX%s-%s" % (tag, k) for k in ("WIN", "LOSS", "STOP", "HOLD"))
    contracts = {t: Contract(t, STRIKE, close) for t in (W, L, S, H)}
    feed = _Feed()

    def kernel():
        return MarketableLimitKernel(SimulatedVenue(feed), feed, entry_cross_ticks=2, exit_cross_ticks=2,
                                     max_entry_slippage=0.10, max_attempts=1)

    kernels = {m: kernel() for m in MODES}
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)  # test-only, as the existing live tests do
    sources = engine.Sources(paper_kernel=lambda u: kernels["paper"], demo_kernel=lambda u: kernels["demo"],
                             live_kernel=lambda u: kernels["live"])

    def tick(books, spot):
        now = int(datetime.now(timezone.utc).timestamp())
        feats = {"spot": spot, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0, "vol_15m": 0.0005, "vol_60m": 0.0005}
        snaps, sizes = [], {}
        for t, (bid, ask) in books.items():
            snaps.append(snapshot(feats, contracts[t], now, bid, ask))
            sizes[t], sizes[(t, "no")] = 500.0, 500.0
        feed.set(snaps, sizes)
        out = {}
        for mode in MODES:  # every mode sees the same market at the same moment
            deps[mode]["last_decision_ts"] = None
            out[mode] = engine.decide(conn, deps[mode], snaps, sizes, sources)
        return out

    # Each mode buys all four contracts at 40c (BTC 2% above every strike).
    entries = tick({t: (0.38, 0.40) for t in contracts}, 100.0)
    assert {m: entries[m].get("entries") for m in MODES} == {"paper": 4, "demo": 4, "live": 4}, entries
    # WIN settles YES and LOSS settles NO, in every mode.
    cur.execute("UPDATE app_positions SET market_close_time=%s WHERE user_id=%s AND ticker IN (%s,%s)",
                (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1), uid, W, L))
    assert engine.settle_due(conn, engine.MARKETS["btc15m"], engine.Sources(result={W: "yes", L: "no"}.get),
                             datetime.now(timezone.utc)) >= 6
    # Demo is reloaded: its shown P&L restarts here (the track record keeps counting).
    repo.reload_demo(cur, uid, 750.0)
    # STOP falls 15c under the entry with BTC under the strike: every mode stops out of it.
    exits = tick({S: (0.25, 0.27)}, 96.0)
    assert {m: exits[m].get("exits") for m in MODES} == {"paper": 1, "demo": 1, "live": 1}, exits
    repo.update_marks(cur, "btc15m", {H: 0.30}, datetime.now(timezone.utc))  # the engine's mark on HOLD

    # -- each mode's own book --------------------------------------------------------------------
    cur.execute("SELECT * FROM app_positions WHERE user_id=%s ORDER BY id", (uid,))
    rows = cur.fetchall()
    book = {}
    for mode in MODES:
        mine = [r for r in rows if r["mode"] == mode]
        assert {r["deployment_id"] for r in mine} == {deps[mode]["id"]}  # every row is its deployment's mode
        closed = [r for r in mine if r["status"] == "closed"]
        [held] = [r for r in mine if r["status"] == "open"]
        book[mode] = {
            "closed": closed, "ids": sorted(r["id"] for r in closed), "held": held,
            "realized": sum(float(r["pnl"]) for r in closed),
            "before_stop": sum(float(r["pnl"]) for r in closed if r["close_reason"] == "settled"),
            "open_cost": float(held["qty"]) * float(held["entry_price"]),
            "unrealized": _money(round(float(held["qty"]) * 0.30, 2) - float(held["qty"]) * float(held["entry_price"])
                                 - float(held["entry_fee"])),
        }
        assert sorted(r["close_reason"] for r in closed) == ["settled", "settled", "stop_loss"]
    # Demo and live went through the order-intent log (written before each order, booked after); paper never does.
    cur.execute("SELECT mode, action, status, COUNT(*) AS n FROM app_order_intents WHERE user_id=%s "
                "GROUP BY mode, action, status", (uid,))
    assert sorted((r["mode"], r["action"], r["status"], r["n"]) for r in cur.fetchall()) == [
        ("demo", "buy", "booked", 4), ("demo", "sell", "booked", 1),
        ("live", "buy", "booked", 4), ("live", "sell", "booked", 1)]
    qty = {m: int(book[m]["held"]["qty"]) for m in MODES}
    assert len(set(qty.values())) == 3, qty  # three different sizes, so three different P&Ls
    realized = {m: book[m]["realized"] for m in MODES}
    assert len({_money(v) for v in realized.values()}) == 3, realized

    # The paper ledger moved only with paper's trades: demo and live money is never paper cash.
    paper_cash = repo.paper_balance(cur, uid)
    p = book["paper"]
    assert _money(paper_cash) == _money(repo.STARTING_PAPER_BALANCE + p["realized"] - p["open_cost"]
                                        - float(p["held"]["entry_fee"]))

    # -- the dashboard ---------------------------------------------------------------------------
    monkeypatch.setattr(server, "_freshness", lambda c: {})
    ctx = server.Ctx(conn, repo.get_user(cur, uid), (), {}, {}, None)
    dash = server.dashboard(ctx)
    for mode in MODES:
        b, mine = dash[mode], book[mode]
        assert b["open_positions"] == 1 and b["open_at_cost"] == _money(mine["open_cost"]), mode
        assert b["closed_trades"] == len(mine["closed"]) and b["running"] == 1, mode
        assert b["today_pnl"] == _money(mine["realized"]), mode
        if mode != "demo":
            assert b["realized_pnl"] == _money(mine["realized"]), mode
    assert dash["paper"]["cash"] == _money(paper_cash)
    assert _money(sum(float(r["pnl"]) for r in dash["paper"]["daily"])) == _money(realized["paper"])
    # Demo equity: the reload's capital plus demo's own P&L since the reload, and what came before it.
    demo, d = dash["demo"], book["demo"]
    assert demo["capital"] == 750.0
    assert demo["before_reload"] == _money(d["before_stop"])
    assert demo["realized_pnl"] == _money(d["realized"] - d["before_stop"])
    assert demo["equity"] == _money(750.0 + d["realized"] - d["before_stop"])
    funds = server.funds(ctx)["demo"]
    assert (funds["equity"], funds["realized"], funds["before_reload"]) == (demo["equity"], demo["realized_pnl"],
                                                                            demo["before_reload"])
    # Each deployment: its own trades, its own curve, its own open P&L.
    for mode in MODES:
        [dd] = [x for x in dash["deployments"] if x["id"] == deps[mode]["id"]]
        assert dd["mode"] == mode and dd["realized_pnl"] == _money(realized[mode])
        assert dd["closed_trades"] == 3 and dd["open_positions"] == 1
        assert _money(dd["curve"][-1][1]) == _money(realized[mode])
        assert dd["unrealized_pnl"] == book[mode]["unrealized"]
    for op in dash["open_positions"]:
        assert op["mode"] == next(m for m in MODES if deps[m]["id"] == op["deployment_id"])
        assert op["unrealized"] == book[op["mode"]]["unrealized"]

    # -- the track record, per mode --------------------------------------------------------------
    # An empty record cached a moment ago (read before these trades): a book this small is read fresh,
    # so the stale empty one is never served.
    from app import track_record
    server._TRACK_RECORD[uid] = (time.time(), track_record.build([]), 0, server._BOOK_SHAPE.get(uid))
    record = server.get_track_record(ctx)["modes"]
    for mode in MODES:
        t = record[mode]
        assert t["trades"] == 3 and t["open_trades"] == 1, mode
        assert t["net_pnl"] == _money(realized[mode]), mode     # demo's too: the record ignores the reload
        assert _money(t["curve"][-1][1]) == _money(realized[mode]), mode
        assert t["open_at_cost"] == _money(book[mode]["open_cost"]), mode
        assert t["excluded_instant_fills"] == 0, mode

    # -- each CSV ----------------------------------------------------------------------------------
    for mode in MODES:
        _, _, _, data = server.trades_csv(server.Ctx(conn, ctx.user, (), {"mode": mode}, {}, None))
        lines = list(csv.DictReader(io.StringIO(data)))
        assert {r["mode"] for r in lines} == {mode}
        assert sorted(int(r["position_id"]) for r in lines) == book[mode]["ids"]
        assert _money(sum(float(r["realized_pnl"]) for r in lines)) == _money(realized[mode])

    # -- the autopilot: the scorecard is paper only; the panel's day figures are each their own ---------
    week = server._autopilot_week(cur, uid, {})
    assert week["paper_pnl"] == _money(realized["paper"]) and week["paper_trades"] == 3
    assert week["paper_started"] == 1  # the demo and live deployments are not paper starts
    status = server.autopilot_status(ctx)
    assert status["today_paper_pnl"] == _money(realized["paper"])
    assert status["today_live_pnl"] == _money(realized["live"])
    limit = float(status["daily_loss_limit"])
    assert status["loss_headroom"] == _money(max(0.0, limit + min(0.0, realized["live"])))
    assert (status["paper_running"], status["demo_running"], status["live_running"]) == (1, 1, 1)
    assert status["week"]["paper_pnl"] == week["paper_pnl"]
    # The safety-stop readout says "on paper": only paper's stop counts, not demo's or live's.
    [paper_stop] = [r for r in book["paper"]["closed"] if r["close_reason"] == "stop_loss"]
    assert status["early_exits_7d"]["stop_loss"]["exits"] == 1
    assert status["early_exits_7d"]["stop_loss"]["pnl"] == _money(paper_stop["pnl"])

    # -- the strategy list: each card shows its own deployment's book --------------------------------
    cards = {c["id"]: c for c in server.list_strategies(server.Ctx(conn, ctx.user, (), {}, {}, None))["strategies"]}
    for mode in MODES:
        real = cards[deps[mode]["strategy_id"]]["real"]
        assert real["mode"] == mode and real["pnl"] == _money(realized[mode]) and real["trades"] == 3, mode
        assert "demo" not in real, mode
