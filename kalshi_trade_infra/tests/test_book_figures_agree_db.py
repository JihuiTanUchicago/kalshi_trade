"""Every page that shows a book's money agrees with every other page, to the cent, against a real MySQL.

One user holds three books at once: paper, demo and live. Each book has its own strategy and stake, so
each book's P&L is a different number, and all three trade the SAME contracts. A figure that filtered
by ticker or by user instead of by mode would leak another book's money. The current trades go
through the real engine path, as in test_modes_never_mix_db.py: decide on the TradingLoop, the
execution kernel over a SimulatedVenue, and settle_due. Live is enabled only by the monkeypatch the
live tests use. Each book gets:
  - a win and a loss (settled);
  - a stop that part-fills and then sells the rest (a part-sold round trip, now complete);
  - a stop that part-fills and keeps the remainder (a part-sold trade still open, marked).
Older history is booked with its own close times, so the windows split:
  - 3 days ago: before the last visit;
  - 30 hours ago: since the last visit, but not today.
Paper's history is on a deployment that was then stopped. It holds a part-sold round trip and an
instant fill (no simulated venue). After that history the paper account is reset, and the strategy
is deployed again. Demo is reloaded between its settlements and its stops.

Then every page is read the way the app reads it, and each figure is held to its own book's position
rows, for the same window: the dashboard's buckets, its "Since your last visit" strip (#397) and its
deployments; the Funds page (each book's realized P&L, closed trades, open positions and balance);
the Deploy board and the strategy page (#400); each book's backtest line (#398); the trades CSV; and
the track record. Where two pages count differently on purpose, the test asserts
the documented relationship instead:
  - closed position rows (dashboard, CSV, Deploy board) against completed round trips (track
    record, backtest line);
  - instant paper fills left out of the evidence;
  - demo's shown P&L since its reload;
  - paper's equity P&L since its reset;
  - stopped deployments, which leave the board but stay in the book.
Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import csv
import io
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

MODES = ("paper", "demo", "live")
STAKES = {"paper": 10.0, "demo": 20.0, "live": 16.0}  # live trades a quarter of its size while new (the ramp)
STRIKE = 98.0
RESET_TO = 500.0
RELOAD_TO = 750.0
# The strategies' unseen-data backtest: +$0.15 a trade over 40 trades, 61% won.
RESULT = {"capital": 40.0, "out_of_sample": {"trades": 40, "pnl": 6.0, "win_rate": 0.61},
          "in_sample": {"trades": 90, "pnl": 30.0, "win_rate": 0.7}}


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


def _trips(rows, mode):
    """A book's trades as the track record and the backtest line count them: one per (deployment,
    entry fill), part-exit slices summed. Returns (completed trips, trips with a slice still open,
    instant paper fills left out). Paper's completed trips are only fills through the simulated venue."""
    groups = {}
    for r in rows:
        if r["mode"] != mode:
            continue
        key = (r["deployment_id"], r["order_ref"] or "row:%d" % r["id"])
        groups.setdefault(key, []).append(r)
    done, still_open, instant = [], [], []
    for (dep, ref), slices in groups.items():
        trip = {"deployment_id": dep, "ref": ref, "pnl": sum(float(s["pnl"] or 0) for s in slices),
                "slices": len(slices), "open": any(s["status"] == "open" for s in slices)}
        if trip["open"]:
            still_open.append(trip)
        elif mode == "paper" and not str(ref).startswith("sim:"):
            instant.append(trip)
        else:
            done.append(trip)
    return done, still_open, instant


def test_every_page_shows_the_same_book_to_the_cent(conn, monkeypatch):
    from app import server
    from app.trading import engine
    from app import repository as repo
    from app.trading import spec as specmod
    from app.trading.markets import Contract, snapshot
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
    from data_pipeline.architecture.simulated_venue import SimulatedVenue

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "books@example.com", "B", None)["id"]
    sids = {}
    for mode in MODES:
        spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "exit": {"stop_loss": 0.1},
                                 "sizing": {"stake": STAKES[mode], "max_positions": 4}})
        sids[mode] = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Books " + mode, "t", spec,
                                          "passed", dict(RESULT))

    # -- history, booked with its own close times --------------------------------------------------
    now = repo.now_utc()
    old, lately = now - timedelta(days=3), now - timedelta(hours=30)
    visit = now - timedelta(hours=48)  # the last visit: after `old`, before `lately`
    tag = uuid.uuid4().hex[:6].upper()

    def booked(did, mode, pnl, ref, at, qty=10, price=0.40):
        repo.insert_closed_position(cur, did, uid, mode, "BKH%s-%s" % (tag, mode.upper()), "yes", qty, price, 0.07,
                                    round(price + (pnl + 0.14) / qty, 4), 0.07, pnl, "settled", at,
                                    order_ref=ref, opened_at=at - timedelta(hours=1), closed_at=at)

    # Paper's first deployment of its strategy: a trade before the visit, a part-sold round trip since
    # the visit (two slices, one entry fill), and an instant fill. Then it is stopped and the account reset.
    p_old = repo.create_deployment(cur, uid, sids["paper"], "btc15m", "paper")
    booked(p_old, "paper", 1.10, "sim:hist-1", old)
    booked(p_old, "paper", -0.30, "sim:hist-2", lately, qty=6)
    booked(p_old, "paper", -0.25, "sim:hist-2", lately + timedelta(minutes=5), qty=4)
    booked(p_old, "paper", 2.00, None, lately)  # instant fill: in the book, not in the evidence
    assert repo.set_deployment_status(cur, uid, p_old, "stopped")
    repo.reset_paper_account(cur, uid, RESET_TO)  # no paper position is open, as the reset requires

    deps = {"paper": repo.create_deployment(cur, uid, sids["paper"], "btc15m", "paper"),
            "demo": repo.create_deployment(cur, uid, sids["demo"], "btc15m", "demo"),
            "live": repo.create_deployment(cur, uid, sids["live"], "btc15m", "live")}
    booked(deps["demo"], "demo", -0.70, "demo:hist-1", old)
    booked(deps["live"], "live", -0.20, "live:hist-0", old)
    booked(deps["live"], "live", 0.45, "live:hist-1", lately)
    running = {m: next(d for d in repo.running_deployments(cur, "btc15m") if d["id"] == deps[m]) for m in MODES}

    # -- the current trades, through the engine -----------------------------------------------------
    close = datetime.now(timezone.utc) + timedelta(minutes=10)
    W, L, P, H = ("BKS%s-%s" % (tag, k) for k in ("WIN", "LOSS", "PART", "HOLD"))
    contracts = {t: Contract(t, STRIKE, close) for t in (W, L, P, H)}
    feed = _Feed()
    kernels = {m: MarketableLimitKernel(SimulatedVenue(feed), feed, entry_cross_ticks=2, exit_cross_ticks=2,
                                        max_entry_slippage=0.10, max_attempts=1) for m in MODES}
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)  # test-only, as the existing live tests do
    sources = engine.Sources(paper_kernel=lambda u: kernels["paper"], demo_kernel=lambda u: kernels["demo"],
                             live_kernel=lambda u: kernels["live"])

    def tick(books, spot):
        """books = {ticker: (bid, ask, bid_size)}: every book sees the same market at the same moment."""
        stamp = int(datetime.now(timezone.utc).timestamp())
        feats = {"spot": spot, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0, "vol_15m": 0.0005, "vol_60m": 0.0005}
        snaps, sizes = [], {}
        for t, (bid, ask, bid_size) in books.items():
            snaps.append(snapshot(feats, contracts[t], stamp, bid, ask))
            sizes[t], sizes[(t, "no")] = 500.0, float(bid_size)
        feed.set(snaps, sizes)
        out = {}
        for mode in MODES:
            running[mode]["last_decision_ts"] = None
            out[mode] = engine.decide(conn, running[mode], snaps, sizes, sources)
        return out

    entries = tick({t: (0.38, 0.40, 500) for t in contracts}, 100.0)  # BTC 2% over every strike: buy all four
    assert {m: entries[m].get("entries") for m in MODES} == {"paper": 4, "demo": 4, "live": 4}, entries
    cur.execute("UPDATE app_positions SET market_close_time=%s WHERE user_id=%s AND ticker IN (%s,%s)",
                (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1), uid, W, L))
    assert engine.settle_due(conn, engine.MARKETS["btc15m"], engine.Sources(result={W: "yes", L: "no"}.get),
                             datetime.now(timezone.utc)) >= 6
    repo.reload_demo(cur, uid, RELOAD_TO)  # demo's shown P&L restarts here; the track record keeps counting
    # BTC under the strike and both prices 15c under the entry: stops, with only 8 contracts bid.
    # A part fill sells 8 and keeps the rest open, so it is not counted as an exit.
    tick({P: (0.25, 0.27, 8), H: (0.25, 0.27, 8)}, 96.0)
    exits = tick({P: (0.25, 0.27, 500)}, 96.0)  # P's remainder sells in full; H keeps what is left
    assert {m: exits[m].get("exits") for m in MODES} == {"paper": 1, "demo": 1, "live": 1}, exits
    repo.update_marks(cur, "btc15m", {H: 0.30}, datetime.now(timezone.utc))

    # -- each book, from its own position rows ------------------------------------------------------
    cur.execute("SELECT * FROM app_positions WHERE user_id=%s ORDER BY id", (uid,))
    rows = cur.fetchall()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    book = {}
    for mode in MODES:
        mine = [r for r in rows if r["mode"] == mode]
        closed = [r for r in mine if r["status"] == "closed"]
        [held] = [r for r in mine if r["status"] == "open"]
        done, still_open, instant = _trips(rows, mode)
        book[mode] = {
            "closed": closed, "ids": sorted(r["id"] for r in closed), "held": held,
            "realized": sum(float(r["pnl"]) for r in closed),
            "today": [r for r in closed if r["closed_at"] >= day],
            "visit": [r for r in closed if r["closed_at"] >= visit],
            "open_cost": float(held["qty"]) * float(held["entry_price"]),
            "unrealized": _money(round(float(held["qty"]) * 0.30, 2) - float(held["qty"]) * float(held["entry_price"])
                                 - float(held["entry_fee"])),
            "done": done, "still_open": still_open, "instant": instant,
            "by_dep": {d: [r for r in closed if r["deployment_id"] == d] for d in {r["deployment_id"] for r in mine}},
        }
        # The fixture holds what it says: part-sold trades in every book, one complete and one still open.
        [part] = [t for t in done if t["slices"] >= 2 and t["deployment_id"] == deps[mode]]
        assert part["ref"] == next(r["order_ref"] for r in mine if r["ticker"] == P) and part["ref"]
        assert len(still_open) == 1 and still_open[0]["slices"] == 2, (mode, still_open)
        assert held["ticker"] == H and 0 < int(held["qty"])
        assert {r["close_reason"] for r in closed if r["ticker"] in (P, H)} == {"stop_loss"}, mode
        # The windows really split: paper and live closed trades 30 hours ago (since the visit, not
        # today), and every book has a trade from before the visit.
        today, since_visit = len(book[mode]["today"]), len(book[mode]["visit"])
        assert 0 < today <= since_visit < len(closed), mode
        assert (since_visit > today) == (mode != "demo"), mode
    assert len({_money(book[m]["realized"]) for m in MODES}) == 3, {m: book[m]["realized"] for m in MODES}
    assert len(book["paper"]["instant"]) == 1 and not book["demo"]["instant"] and not book["live"]["instant"]
    assert len({int(book[m]["held"]["qty"]) for m in MODES}) == 3  # three sizes, so a leak shows as a wrong number

    paper, demo = book["paper"], book["demo"]
    since_reset = sum(float(r["pnl"]) for r in paper["closed"] if r["deployment_id"] == deps["paper"])
    # Demo's reload snapshotted every demo trade closed before it: the history and the two settlements.
    before_reload = sum(float(r["pnl"]) for r in demo["closed"] if r["ticker"] not in (P, H))

    from app.web.routes import dashboard as dashboard_routes
    monkeypatch.setattr(dashboard_routes, "_freshness", lambda c: {})
    server._TRACK_RECORD.pop(uid, None)
    server._BACKTEST_CHECKS.clear()
    user = repo.get_user(cur, uid)

    def ctx(*params, **query):
        return server.Ctx(conn, user, tuple(str(p) for p in params), {k: str(v) for k, v in query.items()}, {}, None)

    since = int(visit.replace(tzinfo=timezone.utc).timestamp())
    dash = server.dashboard(ctx(since=since))
    page = server.funds(ctx())
    funds = {"paper": page["paper"], "demo": page["demo"], "live": page["kalshi"]}
    board = server.list_deployments(ctx())
    record = server.get_track_record(ctx())["modes"]
    csvs = {}
    for mode in MODES:
        _, _, _, data = server.trades_csv(ctx(mode=mode))
        csvs[mode] = list(csv.DictReader(io.StringIO(data)))
    pages = {m: server.get_strategy(ctx(sids[m])) for m in MODES}

    def csv_sum(lines, start=None):
        """The CSV's realized P&L for a window, read back from the file's own close times."""
        keep = [r for r in lines if start is None or datetime.fromisoformat(r["closed_at_utc"].rstrip("Z")) >= start]
        return _money(sum(float(r["realized_pnl"]) for r in keep)), len(keep)

    for mode in MODES:
        b, lines, bucket = book[mode], csvs[mode], dash[mode]
        realized, n_closed = _money(b["realized"]), len(b["closed"])

        # -- the trades CSV: every closed row of this book, and nothing else --
        assert {r["mode"] for r in lines} == {mode}
        assert sorted(int(r["position_id"]) for r in lines) == b["ids"]
        assert csv_sum(lines) == (realized, n_closed), mode

        # -- the dashboard bucket, the same rows (demo's shown P&L is since its reload) --
        assert bucket["closed_trades"] == n_closed, mode
        if mode == "demo":
            assert bucket["before_reload"] == _money(before_reload)
            assert bucket["realized_pnl"] == _money(b["realized"] - before_reload)
            assert bucket["equity"] == _money(RELOAD_TO + b["realized"] - before_reload)
            assert _money(bucket["realized_pnl"] + bucket["before_reload"]) == csv_sum(lines)[0]
        else:
            assert bucket["realized_pnl"] == realized == csv_sum(lines)[0], mode
        assert bucket["open_positions"] == 1 and bucket["open_at_cost"] == _money(b["open_cost"]), mode
        # Today: the same rows the CSV dates today.
        assert bucket["today_pnl"] == csv_sum(lines, day)[0] == _money(sum(float(r["pnl"]) for r in b["today"])), mode

        # -- Funds: the dashboard's figure for each book, its own rows only (demo's since its reload) --
        fb = funds[mode]
        assert fb["closed_trades"] == n_closed, mode
        assert (fb["open_positions"], fb["open_at_cost"]) == (1, _money(b["open_cost"])), mode
        if mode == "demo":
            assert (fb["realized"], fb["before_reload"], fb["equity"]) == \
                (bucket["realized_pnl"], bucket["before_reload"], bucket["equity"])
        else:
            assert fb["realized_pnl"] == bucket["realized_pnl"] == realized, mode

        # -- "Since your last visit": each book on its own, the CSV's rows since then --
        assert dash["since"]["books"][mode] == {"pnl": csv_sum(lines, visit)[0], "trades": csv_sum(lines, visit)[1]}, mode
        assert dash["since"]["books"][mode]["trades"] == len(b["visit"])

        # -- the track record: completed round trips; a part-sold trade still open waits --
        t = record[mode]
        assert t["trades"] == len(b["done"]), mode
        assert t["net_pnl"] == _money(sum(x["pnl"] for x in b["done"])), mode
        assert t["open_trades"] == len(b["still_open"]) == 1, mode
        assert t["open_realized_pnl"] == _money(sum(x["pnl"] for x in b["still_open"])), mode
        assert t["open_at_cost"] == _money(b["open_cost"]), mode  # what is still held, not the whole entry
        assert t["excluded_instant_fills"] == len(b["instant"]), mode
        # Round trips and closed rows are two counts of one book: they add back up to the CSV.
        left_out = _money(sum(x["pnl"] for x in b["instant"]))
        assert _money(t["net_pnl"] + t["open_realized_pnl"] + left_out) == csv_sum(lines)[0], mode
        assert _money(sum(m["pnl"] for m in t["monthly"])) == t["net_pnl"], mode
        assert _money(t["curve"][-1][1]) == t["net_pnl"], mode

        # -- each book's backtest line (#398): the strategy page's and the Deploy board row's --
        [check] = pages[mode]["backtest_checks"]
        assert check["mode"] == mode and check["trades"] == t["trades"], mode
        assert abs(check["per_trade"] * check["trades"] - sum(x["pnl"] for x in b["done"])) < 0.0001 * check["trades"]
        assert check["win_rate"] == round(sum(1 for x in b["done"] if x["pnl"] > 0) / check["trades"], 3)
        [row] = [r for r in t["strategies"] if r["strategy_id"] == sids[mode]]  # the record's strategy row
        assert row["trades"] == check["trades"] and row["net_pnl"] == t["net_pnl"], mode
        [board_row] = [r for r in board["deployments"] if r["id"] == deps[mode]]
        assert board_row["backtest_check"] == check, mode

        # -- the deployment rows: the dashboard's, the Deploy board's and the strategy page's --
        own = b["by_dep"][deps[mode]]
        [dash_row] = [r for r in dash["deployments"] if r["id"] == deps[mode]]
        [page_row] = pages[mode]["deployments"]
        for r in (dash_row, board_row, page_row):
            assert r["mode"] == mode and r["status"] == "running", mode
            assert r["realized_pnl"] == _money(sum(float(x["pnl"]) for x in own)), mode
            assert r["closed_trades"] == len(own) and r["open_positions"] == 1, mode
            assert r["wins"] == sum(1 for x in own if float(x["pnl"]) > 0), mode
        assert dash_row["curve"] == board_row["curve"] and _money(board_row["curve"][-1][1]) == board_row["realized_pnl"]
        assert dash_row["unrealized_pnl"] == b["unrealized"], mode
        # The strategy page's holdings are this book's open position, at cost plus its fee.
        [hold] = pages[mode]["holdings"]
        assert hold["mode"] == mode and hold["qty"] == int(b["held"]["qty"])
        assert hold["cost"] == _money(b["open_cost"] + float(b["held"]["entry_fee"]))

    # -- the stopped deployment: off the board and the dashboard, still in the book -----------------
    for listed in (dash["deployments"], board["deployments"], pages["paper"]["deployments"]):
        assert p_old not in {r["id"] for r in listed}
    shown = sum(r["realized_pnl"] for r in dash["deployments"] if r["mode"] == "paper")
    stopped = _money(sum(float(r["pnl"]) for r in paper["by_dep"][p_old]))
    assert _money(shown + stopped) == dash["paper"]["realized_pnl"]
    # The backtest line counts every deployment of the strategy, the stopped one included.
    assert {x["deployment_id"] for x in paper["done"]} == {p_old, deps["paper"]}
    # The strategy list's card shows its active deployments only.
    cards = {c["id"]: c for c in server.list_strategies(ctx())["strategies"]}
    for mode in MODES:
        real = cards[sids[mode]]["real"]
        assert real["mode"] == mode and real["pnl"] == _money(sum(float(x["pnl"]) for x in book[mode]["by_dep"][deps[mode]]))

    # -- the paper account: its equity P&L restarts at the reset; realized P&L keeps every trade --------
    cash = repo.paper_balance(cur, uid)
    fee = float(paper["held"]["entry_fee"])
    assert _money(cash) == _money(RESET_TO + since_reset - paper["open_cost"] - fee)
    pb = dash["paper"]
    assert pb["cash"] == _money(cash) and pb["deposited"] == RESET_TO and pb["reset_at"] is not None
    assert pb["equity"] == _money(cash + paper["open_cost"])
    assert (page["paper"]["cash"], page["paper"]["equity"]) == (pb["cash"], pb["equity"])  # Funds' paper figure
    assert pb["total_pnl"] == _money(since_reset - fee)  # since the reset, the held position's fee in
    assert _money(sum(float(r["pnl"]) for r in pb["daily"])) == pb["realized_pnl"]  # every day, before the reset too
    # Open positions on the dashboard and the board: the same rows, each its own book's mark.
    assert sorted(p["id"] for p in dash["open_positions"]) == sorted(p["id"] for p in board["open_positions"])
    for op in dash["open_positions"]:
        assert op["unrealized"] == book[op["mode"]]["unrealized"]


def test_a_deleted_strategys_open_position_stays_in_the_book(conn, monkeypatch):
    """A strategy could be deleted once its deployment was stopped, and stopping leaves its positions
    open (the engine flattens them later). The money stays in the book after the delete: paper cash
    paid for the held position. Every page has to keep counting it. The dashboard and the Deploy
    board used to drop it, because they read open positions through the strategy row. Paper equity
    then fell by the position's cost while the track record still held it at cost. The reset guard
    also stopped seeing it, so a reset could orphan the cost it had already debited."""
    from app import server
    from app.trading import engine
    from app import repository as repo
    from app.trading import spec as specmod
    from app.trading.markets import Contract, snapshot
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
    from data_pipeline.architecture.simulated_venue import SimulatedVenue

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "orphan@example.com", "O", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "exit": {"stop_loss": 0.1},
                             "sizing": {"stake": 10.0, "max_positions": 1}})
    sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Deleted later", "t", spec, "passed",
                               dict(RESULT))
    did = repo.create_deployment(cur, uid, sid, "btc15m", "paper")
    dep = next(d for d in repo.running_deployments(cur, "btc15m") if d["id"] == did)
    ticker = "BKO%s" % uuid.uuid4().hex[:8].upper()
    contract = Contract(ticker, STRIKE, datetime.now(timezone.utc) + timedelta(minutes=10))
    feed = _Feed()
    feats = {"spot": 100.0, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0, "vol_15m": 0.0005, "vol_60m": 0.0005}
    snaps = [snapshot(feats, contract, int(datetime.now(timezone.utc).timestamp()), 0.38, 0.40)]
    sizes = {ticker: 500.0, (ticker, "no"): 500.0}
    feed.set(snaps, sizes)
    kernel = MarketableLimitKernel(SimulatedVenue(feed), feed, entry_cross_ticks=2, exit_cross_ticks=2,
                                   max_entry_slippage=0.10, max_attempts=1)
    dep["last_decision_ts"] = None
    assert engine.decide(conn, dep, snaps, sizes, engine.Sources(paper_kernel=lambda u: kernel))["entries"] == 1
    [held] = repo.open_positions(cur, did)
    cost, fee = float(held["qty"]) * float(held["entry_price"]), float(held["entry_fee"])

    user = repo.get_user(cur, uid)

    def ctx(*params, body=None):
        return server.Ctx(conn, user, tuple(str(p) for p in params), {}, body or {}, None)

    server.deployment_action(ctx(did, "stop"))
    # delete_strategy now refuses while the position is open (test_delete_strategy_guard_db.py). Strategies
    # deleted before that guard left exactly this behind, so the row is deleted directly here.
    with pytest.raises(server.ApiError) as kept:
        server.delete_strategy(ctx(sid))
    assert kept.value.status == 409
    assert repo.delete_strategy(cur, uid, sid)
    from app.web.routes import dashboard as dashboard_routes
    monkeypatch.setattr(dashboard_routes, "_freshness", lambda c: {})
    server._TRACK_RECORD.pop(uid, None)
    dash = server.dashboard(ctx())
    board = server.list_deployments(ctx())
    record = server.get_track_record(ctx())["modes"]["paper"]

    cash = repo.paper_balance(cur, uid)
    assert _money(cash) == _money(repo.STARTING_PAPER_BALANCE - cost - fee)  # the ledger paid for it
    assert [p["id"] for p in dash["open_positions"]] == [held["id"]] == [p["id"] for p in board["open_positions"]]
    assert dash["paper"]["open_positions"] == 1 and dash["paper"]["open_at_cost"] == _money(cost)
    assert dash["paper"]["open_at_cost"] == record["open_at_cost"] and record["open_trades"] == 1
    assert dash["paper"]["equity"] == _money(cash + cost) == _money(repo.STARTING_PAPER_BALANCE - fee)
    assert dash["paper"]["total_pnl"] == _money(-fee)  # it lost only the fee, not the whole position
    # The reset still sees the open paper position, so it can't wipe the cost it already paid.
    with pytest.raises(server.ApiError) as refused:
        server.paper_transfer(ctx(body={"kind": "reset", "amount": 1000}))
    assert refused.value.status == 409
    assert _money(repo.paper_balance(cur, uid)) == _money(cash)
