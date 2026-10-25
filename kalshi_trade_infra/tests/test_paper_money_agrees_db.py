"""Every money figure a paper account shows agrees, end to end, against a real MySQL.

One autopilot paper deployment trades through the real engine path (engine.decide on the
TradingLoop, the paper kernel over the simulated venue, engine.settle_due): two settlements (a
win and a loss), a take-profit, a stop, a part-filled stop whose remainder stays open, and an
engine mark on that remainder. Then every place that shows the money is read the way the app
reads it and held to the book, to the cent. Where two figures differ by design, the documented
relationship is asserted instead. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import csv
import io
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

SPEC = {"side": "yes", "entry": {"min_edge": 0.05}, "exit": {"take_profit": 0.3, "stop_loss": 0.1},
        "sizing": {"stake": 10.0, "max_positions": 5}}
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


def _tick(feed, contracts, books, spot):
    """Snapshots and depth for one decision: books = {ticker: (bid, ask, bid_size)}."""
    from app.markets import snapshot

    now = int(datetime.now(timezone.utc).timestamp())
    feats = {"spot": spot, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0, "vol_15m": 0.0005, "vol_60m": 0.0005}
    snaps, sizes = [], {}
    for t, (bid, ask, bid_size) in books.items():
        snaps.append(snapshot(feats, contracts[t], now, bid, ask))
        sizes[t], sizes[(t, "no")] = 100.0, float(bid_size)
    feed.set(snaps, sizes)
    return snaps, sizes


def _money(v):
    return round(float(v) + 1e-9, 2)


def test_every_paper_money_figure_agrees_to_the_cent(conn, monkeypatch):
    from app import engine, server
    from app import repository as repo
    from app import spec as specmod
    from app.markets import Contract
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
    from data_pipeline.architecture.simulated_venue import SimulatedVenue

    cur = conn.cursor()
    user = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "money@example.com", "M", None)
    uid = user["id"]
    sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Money check", "t", specmod.validate(SPEC),
                               "passed", {"capital": 50})
    repo.create_proposal(cur, uid, "deploy", "Autopilot", None, sid, "applied")  # the autopilot put it on paper
    did = repo.create_deployment(cur, uid, sid, "btc15m", "paper")
    dep = next(d for d in repo.running_deployments(cur, "btc15m") if d["id"] == did)

    tag = uuid.uuid4().hex[:6].upper()
    close = datetime.now(timezone.utc) + timedelta(minutes=10)
    names = {k: "MNY%s-%s" % (tag, k) for k in "ABCDE"}
    contracts = {t: Contract(t, STRIKE, close) for t in names.values()}
    A, B, C, D, E = (names[k] for k in "ABCDE")
    feed = _Feed()
    kernel = MarketableLimitKernel(SimulatedVenue(feed), feed, entry_cross_ticks=2, exit_cross_ticks=2,
                                   max_entry_slippage=0.10, max_attempts=1)
    sources = engine.Sources(paper_kernel=lambda u: kernel)
    monkeypatch.setattr(engine, "ENGINE_LOOP_MODES", frozenset({"paper"}))

    def decide(books, spot):
        snaps, sizes = _tick(feed, contracts, books, spot)
        dep["last_decision_ts"] = None
        return engine.decide(conn, dep, snaps, sizes, sources)

    # Five entries at 40c (BTC 2% above every strike, so YES is worth ~$1).
    assert decide({t: (0.38, 0.40, 100) for t in contracts}, 100.0)["entries"] == 5
    # With BTC under the strikes nothing is worth buying again, so each tick only exits.
    assert decide({C: (0.25, 0.27, 100)}, 96.0)["exits"] == 1          # stop: 15c under entry
    assert decide({E: (0.75, 0.77, 100)}, 96.0)["exits"] == 1          # take-profit: 35c over entry
    decide({D: (0.25, 0.27, 10)}, 96.0)                                # stop, but only 10 bid: a part fill
    # A settles YES (a win) and B settles NO (a loss); D's remainder stays open.
    cur.execute("UPDATE app_positions SET market_close_time=%s WHERE deployment_id=%s AND ticker IN (%s,%s)",
                (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1), did, A, B))
    result = {A: "yes", B: "no"}
    assert engine.settle_due(conn, engine.MARKETS["btc15m"], engine.Sources(result=result.get),
                             datetime.now(timezone.utc)) >= 2
    repo.update_marks(cur, "btc15m", {D: 0.30}, datetime.now(timezone.utc))  # the engine's mark on what's left

    # -- the book itself -----------------------------------------------------------------------
    cur.execute("SELECT * FROM app_positions WHERE deployment_id=%s ORDER BY id", (did,))
    rows = cur.fetchall()
    closed = [r for r in rows if r["status"] == "closed"]
    [still_open] = [r for r in rows if r["status"] == "open"]
    assert sorted(r["close_reason"] for r in closed) == ["settled", "settled", "stop_loss", "stop_loss", "take_profit"]
    assert still_open["ticker"] == D and still_open["qty"] == 15  # 10 of 25 sold, 15 held
    assert sum(1 for r in closed if float(r["pnl"]) > 0) == 2 and sum(1 for r in closed if float(r["pnl"]) < 0) == 3
    realized = sum(float(r["pnl"]) for r in closed)
    open_cost = float(still_open["qty"]) * float(still_open["entry_price"])
    open_fee = float(still_open["entry_fee"])
    slice_pnl = sum(float(r["pnl"]) for r in closed if r["ticker"] == D)  # realized on the part-sold trade
    value = round(15 * 0.30, 2)
    unrealized = _money(value - open_cost - open_fee)

    # The paper ledger: every debit and credit the trades made, from the $1,000 start.
    cash = repo.paper_balance(cur, uid)
    assert _money(cash) == _money(repo.STARTING_PAPER_BALANCE + realized - open_cost - open_fee)

    # -- the dashboard ---------------------------------------------------------------------------
    monkeypatch.setattr(server, "_freshness", lambda c: {})
    ctx = server.Ctx(conn, repo.get_user(cur, uid), (), {}, {}, None)
    dash = server.dashboard(ctx)
    paper = dash["paper"]
    assert paper["realized_pnl"] == _money(realized)
    assert paper["today_pnl"] == _money(realized)              # every trade closed today (UTC)
    assert paper["cash"] == _money(cash)
    assert paper["open_at_cost"] == _money(open_cost)
    assert paper["equity"] == _money(cash + open_cost)         # open positions at cost, not marked
    assert paper["closed_trades"] == len(closed)
    # By design: "P&L all time / since reset" is equity minus deposits, so it already counts the fee
    # paid to open the position still held, which realized P&L leaves out until that position closes.
    assert paper["total_pnl"] == _money(realized - open_fee)
    assert paper["deposited"] == _money(repo.STARTING_PAPER_BALANCE)

    [d] = [x for x in dash["deployments"] if x["id"] == did]
    assert d["realized_pnl"] == _money(realized)
    assert d["closed_trades"] == len(closed) and d["open_positions"] == 1
    assert _money(d["curve"][-1][1]) == _money(realized)       # the sparkline ends on the realized total
    # Open P&L: the open position's mark, the deployment's sum, and marked equity all say the same.
    [op] = [p for p in dash["open_positions"] if p["deployment_id"] == did]
    assert op["unrealized"] == unrealized and op["value"] == value
    assert d["unrealized_pnl"] == unrealized
    assert _money(cash + op["value"]) == _money(repo.STARTING_PAPER_BALANCE + realized + unrealized)

    # -- the track record ------------------------------------------------------------------------
    server._TRACK_RECORD.pop(uid, None)
    tr = server.get_track_record(ctx)["modes"]["paper"]
    # By design it counts finished round trips: the part-sold trade joins when its remainder closes,
    # and the panel says how much it already realized ("open_realized_pnl").
    assert tr["excluded_instant_fills"] == 0                   # every fill came through the simulated venue
    assert tr["trades"] == len(closed) - 1 and tr["open_trades"] == 1
    assert tr["net_pnl"] == _money(realized - slice_pnl)
    assert tr["open_realized_pnl"] == _money(slice_pnl)
    assert _money(tr["net_pnl"] + tr["open_realized_pnl"]) == _money(realized)
    assert tr["open_at_cost"] == _money(open_cost)             # what is still held, not the whole entry

    # -- the trades CSV --------------------------------------------------------------------------
    kind, _, _, data = server.trades_csv(server.Ctx(conn, ctx.user, (), {"mode": "paper"}, {}, None))
    lines = list(csv.DictReader(io.StringIO(data)))
    assert len(lines) == len(closed)
    assert _money(sum(float(r["realized_pnl"]) for r in lines)) == _money(realized)

    # -- the autopilot ---------------------------------------------------------------------------
    week = server._autopilot_week(cur, uid, {})
    assert week["paper_pnl"] == _money(realized) and week["paper_trades"] == len(closed)
    assert week["paper_started"] == 1
    status = server.autopilot_status(ctx)
    assert status["today_paper_pnl"] == _money(realized)
