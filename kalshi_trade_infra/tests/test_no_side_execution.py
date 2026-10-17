"""Live/demo execution must place the CORRECT leg.

Before this, live execution was hardcoded to YES: a NO-side strategy would have
placed a YES order - betting the opposite direction with real money. These tests
pin the NO path end to end:

  * the wire order for a NO leg is its YES complement (buy NO = sell YES = an
    ``ask`` at ``1 - no_price``), never a YES buy;
  * the kernel prices a NO order from the NO side of the book and reports the
    fill in NO terms (cost basis ``1 - yes_fill``);
  * ``engine.decide`` on a live NO strategy sends an intent with ``side="no"``
    and books a NO position at the NO fill price.
"""
from datetime import datetime, timedelta, timezone

import pytest

from data_pipeline.architecture.contracts import ExecutionReport, TradeIntent
from data_pipeline.architecture.execution_kernel import MarketableLimitKernel, order_wire_params
from data_pipeline.common import utc_now
from data_pipeline.market_data import Quote

TICKER = "KXBTC15M-26SEP271315-15"


# -- the money-direction core ---------------------------------------------------


def test_order_wire_params_yes_is_unchanged():
    assert order_wire_params("buy", "yes", 0.30) == ("bid", 0.30)
    assert order_wire_params("sell", "yes", 0.30) == ("ask", 0.30)


def test_order_wire_params_no_is_the_yes_complement():
    # Buy NO = sell YES (ask) at 1 - no_price; sell NO = buy YES (bid) at 1 - no_price.
    side, price = order_wire_params("buy", "no", 0.30)
    assert side == "ask" and price == pytest.approx(0.70)
    side, price = order_wire_params("sell", "no", 0.30)
    assert side == "bid" and price == pytest.approx(0.70)


def test_live_submitter_sends_a_no_order_as_a_yes_ask(monkeypatch):
    """A NO buy must hit the wire as sell-YES at 1 - no_price, not a YES buy."""
    from data_pipeline import live_trading_engine as lte

    sent = {}
    monkeypatch.setattr(lte, "api_post_auth",
                        lambda path, body, credentials=None: sent.update(body) or {"fill_count": "0.00"})
    lte.place_limit_order(TICKER, "buy", "no", 5, 0.30)
    assert sent["side"] == "ask", "buy NO must be sell-YES, never a YES bid"
    assert sent["price"] == "0.7000", "NO price 0.30 -> YES wire price 0.70"
    # And YES is untouched: a YES buy is still a bid at its own price.
    lte.place_limit_order(TICKER, "buy", "yes", 5, 0.30)
    assert sent["side"] == "bid" and sent["price"] == "0.3000"


# -- kernel: price the NO book, report the NO fill ------------------------------


def _quote(bid, ask, age_s=0.0):
    return Quote(ticker=TICKER, yes_bid=bid, yes_ask=ask, yes_bid_size=3000.0, yes_ask_size=3000.0,
                 as_of=utc_now() - timedelta(seconds=age_s), source="websocket")


class _Feed:
    def __init__(self, q):
        self._q = q

    def quote(self, ticker, max_age_seconds=None):
        return self._q


class _NoWireSubmitter:
    """Stands in for place_limit_order: given an own-side (NO) order it fills at
    the NO ask/bid and returns the Kalshi resp in YES terms, as the real wire does."""

    def __init__(self, q):
        self._q = q
        self.sent = []

    def __call__(self, ticker, action, side, qty, price):
        self.sent.append({"action": action, "side": side, "price": price})
        v2_side, wire = order_wire_params(action, side, price)
        q = self._q
        crosses = wire <= q.yes_bid if v2_side == "ask" else wire >= q.yes_ask
        if not crosses:
            return {"client_order_id": "c", "body": {}, "resp": {"fill_count": "0.00", "order_id": "o"}}
        yes_fill = q.yes_bid if v2_side == "ask" else q.yes_ask
        return {"client_order_id": "c", "body": {},
                "resp": {"fill_count": f"{qty}.00", "average_fill_price": f"{yes_fill:.4f}",
                         "average_fee_paid": "0.0100", "order_id": "o"}}


def _no_intent(action, qty, no_price):
    return TradeIntent(action=action, side="no", ticker=TICKER, qty_contracts=qty,
                       limit_price_dollars=no_price, model_name="m", now_ts=None, metadata={})


def test_kernel_buys_no_from_the_no_side_of_the_book():
    # YES book 0.70/0.71 -> NO ask = 1 - 0.70 = 0.30. Signal NO price 0.30.
    q = _quote(bid=0.70, ask=0.71)
    sub = _NoWireSubmitter(q)
    k = MarketableLimitKernel(sub, _Feed(q), entry_cross_ticks=1, max_entry_slippage=0.20)
    rep = k.execute(_no_intent("buy", 10, 0.30))
    assert sub.sent[0]["side"] == "no", "the kernel must pass the NO leg to the submitter"
    assert sub.sent[0]["price"] == pytest.approx(0.31), "NO ask 0.30 + 1 tick, in NO price space"
    assert rep.fill_qty_contracts == 10
    # YES filled at 0.70 -> NO cost basis 1 - 0.70 = 0.30.
    assert rep.fill_price_dollars == pytest.approx(0.30)


def test_kernel_sells_no_from_the_no_bid():
    # YES book 0.70/0.71 -> NO bid = 1 - 0.71 = 0.29.
    q = _quote(bid=0.70, ask=0.71)
    sub = _NoWireSubmitter(q)
    k = MarketableLimitKernel(sub, _Feed(q), exit_cross_ticks=2)
    rep = k.execute(_no_intent("sell", 10, 0.40))
    assert sub.sent[0]["side"] == "no"
    assert sub.sent[0]["price"] == pytest.approx(0.27), "NO bid 0.29 - 2 ticks"
    # YES filled at 0.71 -> NO proceeds 1 - 0.71 = 0.29.
    assert rep.fill_price_dollars == pytest.approx(0.29)


def test_kernel_abandons_a_no_entry_when_the_no_ask_has_run_away():
    # YES book 0.60/0.61 -> live NO ask = 0.40, but the signal NO price was 0.30.
    q = _quote(bid=0.60, ask=0.61)
    sub = _NoWireSubmitter(q)
    k = MarketableLimitKernel(sub, _Feed(q), max_entry_slippage=0.02)
    rep = k.execute(_no_intent("buy", 10, 0.30))
    assert rep.status == "edge_gone" and rep.accepted is False
    assert sub.sent == [], "no order once the NO edge is gone"


# -- engine.decide: a live NO strategy places a NO order, books a NO position ----


class _Cur:
    """Just the app_positions queries engine.decide hits for a fresh live entry."""

    def __init__(self):
        self.inserted = []
        self._last = []
        self.lastrowid = 1

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SELECT * FROM app_positions WHERE deployment_id=%s AND status='open'"):
            self._last = []
        elif s.startswith("INSERT INTO app_positions"):
            self.inserted.append(params)
            self.lastrowid = len(self.inserted)
        elif s.startswith("SELECT COALESCE(SUM(pnl),0) AS p FROM app_positions"):
            self._last = [{"p": 0.0}]
        elif s.startswith("SELECT drawdown_limit_pct, max_open_positions, max_open_notional FROM app_users"):
            self._last = [{"drawdown_limit_pct": 25.0, "max_open_positions": 20, "max_open_notional": 1000.0}]
        elif s.startswith("SELECT COUNT(*) AS n, COALESCE(SUM(qty*entry_price),0) AS notional FROM app_positions"):
            self._last = [{"n": 0, "notional": 0.0}]
        else:
            raise AssertionError("unexpected SQL in decide NO path: %s" % s[:90])

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return self._last


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


class _RecordingKernel:
    def __init__(self):
        self.intents = []

    def execute(self, intent):
        self.intents.append(intent)
        # Fill the whole order at the signalled (own-side) price.
        return ExecutionReport(accepted=True, status="filled",
                               fill_price_dollars=float(intent.limit_price_dollars),
                               fill_qty_contracts=int(intent.qty_contracts),
                               external_order_id="ord-1", client_order_id="c", fee_dollars=0.05)


def _no_snapshot():
    from app.markets import Contract, snapshot

    now = int(datetime.now(timezone.utc).timestamp())
    # Strike far above spot -> P(YES) ~ 0 -> NO is the high-edge side.
    contract = Contract(TICKER, 110.0, datetime.fromtimestamp(now + 5 * 60, tz=timezone.utc))
    feats = {"spot": 100.0, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0,
             "vol_15m": 0.0005, "vol_60m": 0.0005}
    return snapshot(feats, contract, now, 0.40, 0.42)  # NO ask = 1 - 0.40 = 0.60


def test_decide_live_places_a_no_order_and_books_a_no_position(monkeypatch):
    from app import engine
    from app import spec as specmod

    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", True)
    cur = _Cur()
    conn = _Conn(cur)
    kernel = _RecordingKernel()
    spec = specmod.validate({"side": "no", "entry": {"min_edge": 0.1}})
    dep = {"id": 1, "user_id": 1, "market": "btc15m", "mode": "live", "spec": spec,
           "result": {"capital": 10, "out_of_sample": {"max_drawdown": 3}}}
    snap = _no_snapshot()
    sources = engine.Sources(live_kernel=lambda uid: kernel)

    out = engine.decide(conn, dep, [snap], {snap.contract.ticker: 1000.0}, sources)

    assert out["entries"] == 1
    assert kernel.intents, "a live NO strategy must place an order"
    intent = kernel.intents[0]
    assert intent.action == "buy" and intent.side == "no", "it must place a NO order, not YES"
    assert intent.limit_price_dollars == pytest.approx(0.60), "priced at the NO ask (1 - yes_bid)"
    # Position row: INSERT params are (dep_id, user_id, mode, ticker, side, qty, entry_price, ...).
    params = cur.inserted[0]
    assert params[4] == "no" and params[2] == "live"
    assert float(params[6]) == pytest.approx(0.60), "booked at the NO fill price"
