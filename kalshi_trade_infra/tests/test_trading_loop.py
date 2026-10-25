"""trading_core.engine: one loop for backtest, paper and live, across venues (ARCHITECTURE.md step 8)."""
from datetime import datetime, timezone

import pytest

from app.adapters.kalshi.fees import KalshiBinaryFees
from trading_core.domain import (BinaryTerms, Instrument, InstrumentId, InstrumentKind, OrderIntent, Portfolio,
                                 Quote, Side)
from trading_core.engine import (CrossTheTouch, QuoteFillVenue, RiskChain, TradingLoop, kill_switch,
                                 max_open_positions, max_order_notional, max_position)
from trading_core.ports import FeesByVenue, FixedClock, NotionalRateFees

EXPIRY = datetime(2026, 10, 26, 21, 0, tzinfo=timezone.utc)
YES = InstrumentId("kalshi", "KXBTCD-26OCT2617-T100000", "yes")
AAPL = InstrumentId("alpaca", "AAPL")
INSTRUMENTS = {
    YES: Instrument(YES, InstrumentKind.BINARY, terms=BinaryTerms(expiry=EXPIRY, strike=100_000.0)),
    AAPL: Instrument(AAPL, InstrumentKind.SPOT, lot_size=0.0001),
}
FEES = FeesByVenue({"kalshi": KalshiBinaryFees(), "alpaca": NotionalRateFees(0.0)})


class ReplayFeed:
    """Bars replayed against a FixedClock: the backtest's MarketDataFeed."""

    def __init__(self, clock, bars):
        self.clock, self.bars = clock, bars          # {ts: {iid: (bid, ask)}}

    def quote(self, iid):
        bar = self.bars.get(self.clock.now(), {}).get(iid)
        return None if bar is None else Quote(iid, self.clock.now(), bar[0], bar[1])

    def quotes(self, iids):
        return {i: q for i in iids if (q := self.quote(i)) is not None}


class BuyBelowSellAbove:
    """One rule, every market: buy 10 when the ask is under ``lo`` x mark, exit when the bid is over ``hi`` x."""

    strategy_id = "bbsa"

    def __init__(self, marks):
        self.marks = marks

    def decide(self, ctx):
        out = []
        for iid, q in ctx.quotes.items():
            mark, pos = self.marks[iid], ctx.positions.get(iid)
            if pos and q.bid is not None and q.bid > 1.1 * mark:
                out.append(OrderIntent(iid, Side.SELL, pos.qty, reduce_only=True, strategy_id=self.strategy_id))
            elif not pos and q.ask is not None and q.ask < 0.9 * mark:
                out.append(OrderIntent(iid, Side.BUY, 10, limit_price=q.ask + 0.02 * mark,
                                       strategy_id=self.strategy_id))
        return out


def _run(bars, **kw):
    clock = FixedClock(0.0)
    feed = ReplayFeed(clock, bars)
    venue = QuoteFillVenue(feed, FEES, INSTRUMENTS, cash=10_000.0)
    loop = TradingLoop(BuyBelowSellAbove({YES: 0.50, AAPL: 200.0}), INSTRUMENTS, feed, venue, clock,
                       book=Portfolio(cash=10_000.0), execution=CrossTheTouch(max_quote_age_seconds=60), **kw)
    results = []
    for ts in sorted(bars):
        clock.ts = ts
        results.append(loop.step())
    return loop, venue, results


BARS = {
    60.0: {YES: (0.38, 0.40), AAPL: (170.0, 170.1)},     # both cheap -> buy both
    120.0: {YES: (0.45, 0.47), AAPL: (190.0, 190.1)},    # hold
    180.0: {YES: (0.58, 0.60), AAPL: (225.0, 225.1)},    # both rich -> exit both
}


def test_one_strategy_trades_a_kalshi_binary_and_a_stock_through_the_same_loop():
    loop, venue, results = _run(BARS)
    entries, _, exits = results
    assert sorted(str(r.intent.instrument) for r in entries.reports) == ["alpaca:AAPL", str(YES)]
    assert all(r.status == "filled" for r in entries.reports + exits.reports)
    assert loop.book.open_positions() == {} and venue.book.open_positions() == {}
    # P&L: YES 10 x (0.58 - 0.40) minus Kalshi fees; AAPL 10 x (225 - 170.1) commission-free
    kalshi_fees = KalshiBinaryFees().fee(INSTRUMENTS[YES], 10, 0.40) + KalshiBinaryFees().fee(INSTRUMENTS[YES], 10, 0.58)
    assert loop.book.cash - 10_000.0 == pytest.approx(10 * 0.18 + 10 * 54.9 - kalshi_fees)
    assert venue.book.cash == pytest.approx(loop.book.cash)


def test_client_order_ids_are_deterministic_for_replay():
    _, _, first = _run(BARS)
    _, _, second = _run(BARS)
    ids = lambda rs: [r.order_ids for res in rs for r in res.reports]
    assert ids(first) == ids(second) and ids(first)[0] == ["bbsa-60-1"]


def test_risk_refuses_entries_but_never_exits():
    halted = {"on": False}
    chain = RiskChain([kill_switch(lambda: halted["on"])])
    clock = FixedClock(60.0)
    feed = ReplayFeed(clock, BARS)
    venue = QuoteFillVenue(feed, FEES, INSTRUMENTS, cash=10_000.0)
    loop = TradingLoop(BuyBelowSellAbove({YES: 0.50, AAPL: 200.0}), INSTRUMENTS, feed, venue, clock, risk=chain,
                       execution=CrossTheTouch(max_quote_age_seconds=60), book=Portfolio(cash=10_000.0))
    assert len(loop.step().reports) == 2
    halted["on"] = True
    clock.ts = 180.0                                      # exits under a kill switch
    res = loop.step()
    assert len(res.reports) == 2 and not res.refused and loop.book.open_positions() == {}
    clock.ts = 60.0                                       # the cheap bar again: entries are refused
    res = loop.step()
    assert [d.rule for _, d in res.refused] == ["kill_switch", "kill_switch"] and not res.reports


def test_limit_checks():
    book = Portfolio()
    buy = OrderIntent(YES, Side.BUY, 10, limit_price=0.40)
    assert max_order_notional(3.0, INSTRUMENTS)(buy).allowed is False
    assert max_order_notional(5.0, INSTRUMENTS)(buy).allowed is True
    assert max_order_notional(5.0, INSTRUMENTS)(OrderIntent(YES, Side.BUY, 1)).allowed is False  # unbounded
    assert max_position(5, book)(buy).allowed is False
    assert max_open_positions(0, book)(buy).allowed is False and max_open_positions(1, book)(buy).allowed


def test_execution_refuses_stale_or_one_sided_books_and_respects_the_limit():
    policy, inst = CrossTheTouch(max_quote_age_seconds=2), INSTRUMENTS[YES]
    buy = OrderIntent(YES, Side.BUY, 1, limit_price=0.45)
    assert policy.price(buy, inst, None, 10)[1] == "no quote"
    assert "old" in policy.price(buy, inst, Quote(YES, 0, 0.40, 0.42), 10)[1]
    assert policy.price(buy, inst, Quote(YES, 10, 0.40, None), 10)[1] == "no ask"
    assert policy.price(buy, inst, Quote(YES, 10, 0.40, 0.42), 10) == (0.43, None)       # ask + 1 tick
    assert policy.price(buy, inst, Quote(YES, 10, 0.43, 0.445), 10) == (0.45, None)      # capped at limit
    assert policy.price(buy, inst, Quote(YES, 10, 0.44, 0.46), 10)[0] is None            # ask through the limit
    sell = OrderIntent(YES, Side.SELL, 1, reduce_only=True)
    assert policy.price(sell, inst, Quote(YES, 10, 0.40, 0.42), 10) == (0.38, None)      # bid - 2 ticks on exit


def test_feature_providers_merge_onto_quotes_before_the_strategy_sees_them():
    seen = {}

    class Spy:
        strategy_id = "spy"

        def decide(self, ctx):
            seen.update({i: dict(q.features) for i, q in ctx.quotes.items()})
            return []

    class Vol:
        name = "vol"

        def feature_names(self):
            return ["vol_60m"]

        def features(self, instruments, as_of):
            return {i.id: {"vol_60m": 0.5} for i in instruments if i.kind is InstrumentKind.BINARY}

    clock = FixedClock(60.0)
    feed = ReplayFeed(clock, BARS)
    TradingLoop(Spy(), INSTRUMENTS, feed, QuoteFillVenue(feed, FEES, INSTRUMENTS), clock, features=[Vol()]).step()
    assert seen == {YES: {"vol_60m": 0.5}, AAPL: {}}


def test_paper_venue_will_not_sell_what_it_does_not_hold():
    clock = FixedClock(60.0)
    venue = QuoteFillVenue(ReplayFeed(clock, BARS), FEES, INSTRUMENTS)
    rep = venue.submit(OrderIntent(AAPL, Side.SELL, 1, reduce_only=True), 160.0, "x")
    assert rep.status == "rejected" and venue.net_position(AAPL) == 0
    assert venue.submit(OrderIntent(AAPL, Side.BUY, 1), 160.0, "y").status == "unfilled"  # limit under the ask


def test_position_stop_uses_the_current_holdings_fees_and_skips_unmarkable_books():
    from trading_core.engine import position_stop
    from trading_core.domain import Fill
    book = Portfolio()
    book.apply(Fill(YES, Side.BUY, 10, 0.50, fee=0.50))
    book.apply(Fill(YES, Side.SELL, 10, 0.50, fee=0.50))           # round trip: lifetime fees 1.00
    book.apply(Fill(YES, Side.BUY, 10, 0.50, fee=0.10))            # new holding: cost 5.10
    pos = book.positions[YES]
    assert pos.fees == pytest.approx(1.10) and pos.open_fees == pytest.approx(0.10)
    rule = position_stop(40)
    assert rule(book, {YES: Quote(YES, 0, 0.31, 0.33)}, 0) == []   # loss 1.99 / 5.10 = 39%
    out = rule(book, {YES: Quote(YES, 0, 0.30, 0.33)}, 0)          # loss 2.10 / 5.10 = 41%
    assert [(i.side, i.qty, i.reduce_only, i.reason) for i in out] == [(Side.SELL, 10, True, "stop")]
    assert rule(book, {YES: Quote(YES, 0, None, 0.33)}, 0) == [] and rule(book, {}, 0) == []
    assert position_stop(0)(book, {YES: Quote(YES, 0, 0.01, 0.33)}, 0) == []


def test_next_step_fills_decide_now_and_fill_on_the_next_quote():
    clock = FixedClock(60.0)
    feed = ReplayFeed(clock, BARS)
    venue = QuoteFillVenue(feed, FEES, INSTRUMENTS, cash=10_000.0)
    loop = TradingLoop(BuyBelowSellAbove({YES: 0.50, AAPL: 200.0}), INSTRUMENTS, feed, venue, clock,
                       execution=CrossTheTouch(max_quote_age_seconds=60), book=Portfolio(cash=10_000.0),
                       next_step_fills=True, pending_ttl=90)
    first = loop.step()
    assert len(first.intents) == 2 and first.reports == []         # decided on the cheap bar, nothing sent
    clock.ts = 120.0
    second = loop.step()        # the next bar's asks ran past both limits: the latency cost, refused not chased
    assert [r.status for r in second.reports] == ["rejected", "rejected"]
    assert all("above limit" in r.message for r in second.reports) and loop.book.open_positions() == {}


def test_one_position_per_symbol_blocks_the_other_outcome():
    from trading_core.domain import Fill
    from trading_core.engine import one_position_per_symbol
    book = Portfolio()
    book.apply(Fill(YES, Side.BUY, 1, 0.40))
    no = InstrumentId("kalshi", YES.symbol, "no")
    assert one_position_per_symbol(book)(OrderIntent(no, Side.BUY, 1)).allowed is False
    assert one_position_per_symbol(book)(OrderIntent(AAPL, Side.BUY, 1)).allowed is True
