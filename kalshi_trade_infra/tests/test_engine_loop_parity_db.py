"""Paper and demo on the TradingLoop (TAU_ENGINE_LOOP=paper,demo) must book exactly what the legacy
decision path books: the same position rows, the same ledger lines, the same order intents, the same
counts, tick for tick. Two users run
the same deployment on the same random books, one per path, against a real MySQL (opt in as for
test_app_engine_db.py: APP_TEST_MYSQL=1 and the MYSQL_* variables).

Covered: entries and exits (take-profit, stop, edge-gone), slots, one position per ticker, re-entry
after an exit, the user's open-position and open-notional caps, shown depth, running out of paper
cash, and the paper kernel over the simulated venue (missed entries, part-filled exits). Demo runs the
same simulated venue as its exchange, so its order-intent log (written before each order, marked
unfilled or booked after) is compared too.
"""
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

SPECS = [
    {"side": "yes", "entry": {"min_edge": 0.05, "max_spread": 0.05}},
    {"side": "no", "entry": {"min_edge": 0.05}, "exit": {"take_profit": 0.1, "stop_loss": 0.1}},
    {"side": "either", "entry": {"min_edge": 0.03}, "exit": {"take_profit": 0.15},
     "sizing": {"stake": 25.0, "max_positions": 3}},
    {"side": "either", "entry": {"min_edge": 0.02}, "exit": {"min_edge_to_hold": 0.0, "stop_loss": 0.2},
     "sizing": {"stake": 10.0, "max_positions": 5}},
    {"side": "yes", "entry": {"min_edge": 0.1}, "exit": {"min_edge_to_hold": 0.05},
     "sizing": {"stake": 5.0, "max_positions": 2}},
]


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


def _user(conn, risk=None, cash=None):
    from app import repository as repo

    cur = conn.cursor()
    u = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "t@example.com", "T", None)
    if risk:
        repo.set_user_risk_config(cur, u["id"], risk)
    if cash is not None:
        repo.add_ledger(cur, u["id"], "withdrawal", cash - repo.paper_balance(cur, u["id"]), "test")
    return u


def _deployment(conn, user, raw, mode="paper"):
    from app import repository as repo
    from app.trading import spec as specmod

    spec = specmod.validate(dict(raw))
    sid = repo.insert_strategy(conn.cursor(), user["id"], None, None, "btc15m", "volatility", "T", "t", spec, "passed",
                               {"capital": 10, "out_of_sample": {"max_drawdown": 3}})
    did = repo.create_deployment(conn.cursor(), user["id"], sid, "btc15m", mode)
    return next(d for d in repo.running_deployments(conn.cursor(), "btc15m") if d["id"] == did)


def _ticks(seed, n=40, strikes=(98.0, 99.0, 100.0, 101.0, 102.0)):
    """(snapshots, sizes) per tick: one 15-minute event, a random-walk spot, noisy books and sizes."""
    from app.trading.markets import Contract, snapshot

    rng = random.Random(seed)
    base = int(datetime.now(timezone.utc).timestamp()) // 60 * 60
    tag = uuid.uuid4().hex[:6]
    close = datetime.fromtimestamp(base + 3600, tz=timezone.utc)
    contracts = [Contract("T%s-%d" % (tag, int(k)), k, close) for k in strikes]
    mids = {c.ticker: rng.uniform(0.15, 0.85) for c in contracts}
    spot, out = 100.0, []
    for i in range(n):
        spot *= 1.0 + rng.gauss(0, 0.002)
        ts = base + 60 * i
        feats = {"spot": spot, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0, "vol_15m": 0.002, "vol_60m": 0.002}
        snaps, sizes = [], {}
        for c in contracts:
            mids[c.ticker] = min(0.95, max(0.05, mids[c.ticker] + rng.gauss(0, 0.06)))
            spread = rng.choice((0.01, 0.02, 0.03, 0.05))
            bid = round(max(0.01, mids[c.ticker] - spread / 2), 2)
            ask = round(min(0.99, bid + spread), 2)
            snaps.append(snapshot(feats, c, ts, bid, ask))
            sizes[c.ticker], sizes[(c.ticker, "no")] = float(rng.randint(0, 40)), float(rng.randint(0, 40))
        out.append((snaps, sizes))
    return out


class _Feed:
    """The simulated venue's quote feed, pointed at the current tick's books."""

    def __init__(self, thin=False):
        self.snaps, self.sizes, self.thin = {}, {}, thin

    def set(self, snaps, sizes):
        self.snaps, self.sizes = {s.contract.ticker: s for s in snaps}, sizes

    def quote(self, ticker, max_age_seconds=None):
        from data_pipeline.common import utc_now
        from data_pipeline.market_data import Quote

        s = self.snaps.get(ticker)
        if s is None:
            return None
        bid_size, ask_size = self.sizes.get((ticker, "no")), self.sizes.get(ticker)
        if self.thin:   # the venue holds less than the engine was shown: unfilled entries, part-filled exits
            bid_size, ask_size = bid_size // 3, ask_size // 3
        return Quote(ticker=ticker, yes_bid=s.yes_bid, yes_ask=s.yes_ask, yes_bid_size=bid_size, yes_ask_size=ask_size,
                     as_of=utc_now() - timedelta(seconds=0.1), source="websocket")


def _kernel(feed):
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
    from data_pipeline.architecture.simulated_venue import SimulatedVenue

    return MarketableLimitKernel(SimulatedVenue(feed), feed, entry_cross_ticks=2, exit_cross_ticks=2,
                                 max_entry_slippage=0.10, max_attempts=3)


def _book(conn, user, dep):
    cur = conn.cursor()
    cur.execute("SELECT id, ticker, side, qty, entry_price, entry_fee, status, exit_price, exit_fee, pnl, close_reason, "
                "order_ref FROM app_positions WHERE deployment_id=%s ORDER BY id", (dep["id"],))
    rows = [tuple(r.values()) for r in cur.fetchall()]
    nth = {r[0]: i for i, r in enumerate(rows)}
    # sim order ids are random: keep paper's "sim" prefix, and only whether demo's is set
    rows = [r[1:-1] + ((r[-1].split(":")[0] if r[-1] and ":" in r[-1] else bool(r[-1])),) for r in rows]
    cur.execute("SELECT kind, amount, memo FROM app_ledger WHERE user_id=%s ORDER BY id", (user["id"],))
    ledger = [tuple(r.values()) for r in cur.fetchall()]
    cur.execute("SELECT position_id, mode, action, side, ticker, qty, limit_price, status, fill_qty, fill_price, fee, "
                "reason, market_close_time, external_order_id IS NOT NULL AS ext "
                "FROM app_order_intents WHERE deployment_id=%s", (dep["id"],))
    intents = sorted(((nth.get(r["position_id"], -1),) + tuple(r.values())[1:] for r in cur.fetchall()), key=repr)
    return rows, ledger, intents


def _stall(conn, deps, snaps):
    """An order on each of these tickers whose outcome is still unknown (sent, not yet resolved):
    nothing more may be bought or sold on them until it resolves."""
    from app import repository as repo

    for dep in deps:
        for s in snaps:
            iid = uuid.uuid4().hex
            repo.insert_order_intent(conn.cursor(), iid, dep["id"], dep["user_id"], dep["mode"], "buy", "yes",
                                     s.contract.ticker, 1, 0.5, iid)


def _run_both(conn, monkeypatch, raw, seed, risk=None, cash=None, sim=False, mode="paper", thin=False,
              stall=None):
    from app.trading import engine

    feed = _Feed(thin)
    legacy_user, loop_user = _user(conn, risk, cash), _user(conn, risk, cash)
    legacy, loop = _deployment(conn, legacy_user, raw, mode), _deployment(conn, loop_user, raw, mode)
    kernels = {legacy_user["id"]: _kernel(feed), loop_user["id"]: _kernel(feed)}
    kernel = lambda uid: kernels[uid]
    sources = (engine.Sources(demo_kernel=kernel) if mode == "demo"
               else engine.Sources(paper_kernel=kernel if sim else None))
    trades = 0
    for i, (snaps, sizes) in enumerate(_ticks(seed)):
        feed.set(snaps, sizes)
        if stall is not None and i == stall:
            _stall(conn, (legacy, loop), snaps[:2])
        monkeypatch.setattr(engine, "ENGINE_LOOP_MODES", frozenset())
        a = engine.decide(conn, legacy, snaps, sizes, sources)
        monkeypatch.setattr(engine, "ENGINE_LOOP_MODES", frozenset({mode}))
        b = engine.decide(conn, loop, snaps, sizes, sources)
        assert a == b
        assert _book(conn, legacy_user, legacy) == _book(conn, loop_user, loop)
        trades += a.get("entries", 0) + a.get("exits", 0)
    for d in (legacy, loop):
        conn.cursor().execute("UPDATE app_deployments SET status='stopped' WHERE id=%s", (d["id"],))
    return trades


@pytest.mark.parametrize("raw", SPECS)
@pytest.mark.parametrize("seed", [1, 2])
def test_paper_on_the_loop_books_what_the_legacy_path_books(conn, monkeypatch, raw, seed):
    assert _run_both(conn, monkeypatch, raw, seed) > 0


@pytest.mark.parametrize("raw", SPECS)
def test_paper_kernel_on_the_loop_books_what_the_legacy_path_books(conn, monkeypatch, raw):
    _run_both(conn, monkeypatch, raw, 7, sim=True)


@pytest.mark.parametrize("raw", SPECS)
@pytest.mark.parametrize("seed", [5, 6])
def test_demo_on_the_loop_books_and_logs_what_the_legacy_path_does(conn, monkeypatch, raw, seed):
    assert _run_both(conn, monkeypatch, raw, seed, mode="demo") > 0


@pytest.mark.parametrize("raw", SPECS)
def test_demo_on_the_loop_logs_unfilled_and_part_filled_orders_the_same(conn, monkeypatch, raw):
    _run_both(conn, monkeypatch, raw, 8, mode="demo", thin=True)
    _run_both(conn, monkeypatch, raw, 8, sim=True, thin=True)


@pytest.mark.parametrize("raw", SPECS)
def test_demo_on_the_loop_waits_on_unresolved_orders_the_same(conn, monkeypatch, raw):
    _run_both(conn, monkeypatch, raw, 10, mode="demo", stall=12)


@pytest.mark.parametrize("risk,cash", [({"max_open_positions": 1}, None), ({"max_open_notional": 12}, None),
                                       (None, 14.0)])
def test_user_caps_and_cash_bind_the_same_on_the_loop(conn, monkeypatch, risk, cash):
    from app.trading import engine

    monkeypatch.setattr(engine, "PAPER_CAP_MULTIPLE", 1.0)   # the user's caps as set, not 10x for paper
    raw = {"side": "either", "entry": {"min_edge": 0.02}, "exit": {"take_profit": 0.05},
           "sizing": {"stake": 10.0, "max_positions": 5}}
    for seed in (3, 4):
        free = _run_both(conn, monkeypatch, raw, seed)
        assert _run_both(conn, monkeypatch, raw, seed, risk=risk, cash=cash) < free, "the cap must bind"
        _run_both(conn, monkeypatch, raw, seed, risk=risk, cash=cash, sim=True)
        if cash is None:
            _run_both(conn, monkeypatch, raw, seed, risk=risk, mode="demo")


def test_two_open_rows_on_one_contract_stay_on_the_legacy_path(conn, monkeypatch):
    from app.trading import engine
    from app import repository as repo

    user = _user(conn)
    dep = _deployment(conn, user, SPECS[0])
    snaps, sizes = _ticks(9, n=1)[0]
    t = snaps[0].contract
    for _ in range(2):
        repo.insert_position(conn.cursor(), dep["id"], user["id"], "paper", t.ticker, "yes", 1, 0.5, 0.01,
                             t.close_time, None)
    called = []
    monkeypatch.setattr(engine, "ENGINE_LOOP_MODES", frozenset({"paper"}))
    real = engine._decide_on_loop
    monkeypatch.setattr(engine, "_decide_on_loop", lambda *a: called.append(real(*a)) or called[-1])
    engine.decide(conn, dep, snaps, sizes, engine.Sources())
    assert called == [None]
