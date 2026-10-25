"""The venue-agnostic core: instruments, position math, risk invariant, ports (ARCHITECTURE.md)."""
from datetime import datetime, timezone

import pytest

from trading_core.domain import (BinaryTerms, ExecutionReport, Fill, Instrument, InstrumentId, InstrumentKind,
                                 OptionTerms, OrderIntent, PerpetualTerms, Portfolio, Position, Quote, RiskDecision,
                                 Side, first_refusal)
from trading_core.ports import (Clock, DecisionContext, FeatureProvider, FeeModel, FixedClock, MarketDataFeed,
                                Strategy, Venue, VenueCapabilities, ZeroFees)

EXPIRY = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)
KALSHI_YES = InstrumentId("kalshi", "KXBTCD-26OCT2517-T100000", "yes")


def _binary(iid=KALSHI_YES):
    return Instrument(iid, InstrumentKind.BINARY, underlying="BTC-USD", series="KXBTCD",
                      terms=BinaryTerms(expiry=EXPIRY, strike=100_000.0))


def test_instrument_id_round_trips_through_text():
    for iid in (KALSHI_YES, InstrumentId("alpaca", "BRK.B"), InstrumentId("deribit", "BTC-27DEC26-100000-C")):
        assert InstrumentId.parse(str(iid)) == iid
    assert str(KALSHI_YES) == "kalshi:KXBTCD-26OCT2517-T100000.yes"
    with pytest.raises(ValueError):
        InstrumentId.parse("no-venue")


def test_binary_needs_terms_and_outcome_and_has_a_complement():
    yes = _binary()
    no = yes.complement()
    assert no.id.outcome == "no" and no.complement() == yes
    assert yes.expiry == EXPIRY
    with pytest.raises(ValueError):
        Instrument(InstrumentId("kalshi", "X"), InstrumentKind.BINARY, terms=BinaryTerms(expiry=EXPIRY))
    with pytest.raises(ValueError):
        Instrument(KALSHI_YES, InstrumentKind.BINARY)
    with pytest.raises(ValueError):
        Instrument(InstrumentId("coinbase", "BTC-USD"), InstrumentKind.SPOT).complement()


def test_every_market_we_touch_fits_the_same_instrument_model():
    perp = Instrument(InstrumentId("kalshi", "KXBTCPERP"), InstrumentKind.PERPETUAL, underlying="BTC-USD",
                      terms=PerpetualTerms(funding_interval_seconds=8 * 3600))
    call = Instrument(InstrumentId("deribit", "BTC-27DEC26-100000-C"), InstrumentKind.OPTION, underlying="BTC-USD",
                      tick_size=0.0005, terms=OptionTerms(expiry=EXPIRY, strike=100_000.0, right="call"))
    poly = _binary(InstrumentId("polymarket", "0xabc", "yes"))
    aapl = Instrument(InstrumentId("alpaca", "AAPL"), InstrumentKind.SPOT, lot_size=0.0001)
    assert {i.kind for i in (perp, call, poly, aapl)} == {InstrumentKind.PERPETUAL, InstrumentKind.OPTION,
                                                         InstrumentKind.BINARY, InstrumentKind.SPOT}
    assert call.round_price(0.12341) == pytest.approx(0.1235)
    assert perp.expiry is None


def test_position_averages_in_realizes_out_and_flips():
    p = Position(KALSHI_YES)
    p.apply(Fill(KALSHI_YES, Side.BUY, 10, 0.40, fee=0.07))
    p.apply(Fill(KALSHI_YES, Side.BUY, 10, 0.50))
    assert p.qty == 20 and p.avg_price == pytest.approx(0.45)
    p.apply(Fill(KALSHI_YES, Side.SELL, 5, 0.60))
    assert p.qty == 15 and p.realized == pytest.approx(0.75) and p.avg_price == pytest.approx(0.45)
    p.apply(Fill(KALSHI_YES, Side.SELL, 20, 0.50))  # through flat: 5 short at 0.50
    assert p.qty == -5 and p.avg_price == 0.50 and p.realized == pytest.approx(0.75 + 15 * 0.05)
    assert p.unrealized(0.40) == pytest.approx(0.5)
    assert p.fees == pytest.approx(0.07)
    with pytest.raises(ValueError):
        p.apply(Fill(InstrumentId("kalshi", "OTHER", "yes"), Side.BUY, 1, 0.5))


def test_binary_settlement_books_payout_minus_cost():
    p = Position(KALSHI_YES, qty=10, avg_price=0.30)
    assert p.settle(1.0) == pytest.approx(7.0)
    assert p.is_flat and p.realized == pytest.approx(7.0)


def test_portfolio_cash_and_equity_across_venues():
    perp = InstrumentId("kalshi", "KXBTCPERP")
    pf = Portfolio(cash=1000.0)
    pf.apply(Fill(KALSHI_YES, Side.BUY, 100, 0.40, fee=1.0))
    pf.apply(Fill(perp, Side.BUY, 2, 50.0), multiplier=0.01)
    assert pf.cash == pytest.approx(1000 - 40 - 1 - 1.0)
    assert pf.equity({KALSHI_YES: 0.55, perp: 60.0}) == pytest.approx(958 + 55 + 2 * 60 * 0.01)
    assert pf.equity({}) == pytest.approx(958 + 40 + 1.0)  # unmarked: at cost
    assert set(pf.open_positions()) == {KALSHI_YES, perp}


def test_open_positions_index_follows_fills_settlement_and_seeding():
    other = InstrumentId("kalshi", "KXBTCD-26OCT2517-T101000", "no")
    pf = Portfolio(positions={other: Position(other, qty=3, avg_price=0.2), KALSHI_YES: Position(KALSHI_YES)})
    assert set(pf.open_positions()) == {other}
    pf.apply(Fill(KALSHI_YES, Side.BUY, 5, 0.40))
    assert set(pf.open_positions()) == {other, KALSHI_YES}
    pf.apply(Fill(KALSHI_YES, Side.SELL, 5, 0.50))
    pf.settle(other, 1.0)
    assert pf.open_positions() == {} and set(pf.positions) == {other, KALSHI_YES}  # flat ones keep their P&L
    pf.open_positions()[KALSHI_YES] = Position(KALSHI_YES, qty=1)  # a copy: callers can't corrupt the index
    assert pf.open_positions() == {}


def test_exits_skip_every_risk_check():
    def refuse_all(_intent):
        return RiskDecision.refuse("kill_switch", "halted")

    entry = OrderIntent(KALSHI_YES, Side.BUY, 5)
    exit_ = OrderIntent(KALSHI_YES, Side.SELL, 5, reduce_only=True)
    assert first_refusal(entry, [lambda i: RiskDecision.allow(), refuse_all]).rule == "kill_switch"
    assert first_refusal(exit_, [refuse_all]) is None
    assert first_refusal(entry, []) is None
    with pytest.raises(ValueError):
        OrderIntent(KALSHI_YES, Side.BUY, 0)


def test_quote_and_report_helpers():
    q = Quote(KALSHI_YES, ts=100.0, bid=0.41, ask=0.44)
    assert q.mid == pytest.approx(0.425) and q.spread == pytest.approx(0.03) and q.age(103.5) == 3.5
    assert Quote(KALSHI_YES, 1.0, None, 0.5).mid is None
    intent = OrderIntent(KALSHI_YES, Side.BUY, 10)
    rep = ExecutionReport(intent, "partial", fills=[Fill(KALSHI_YES, Side.BUY, 4, 0.40, fee=0.03),
                                                    Fill(KALSHI_YES, Side.BUY, 2, 0.43, fee=0.02)])
    assert rep.filled_qty == 6 and rep.avg_price == pytest.approx(0.41) and rep.fees == pytest.approx(0.05)
    assert ExecutionReport(intent, "unfilled").avg_price is None


class _PaperVenue:
    """A complete Venue in a dozen lines: what an adapter for a new market has to provide."""

    name = "toy"
    capabilities = VenueCapabilities(kinds=frozenset(InstrumentKind), fractional_qty=True)

    def __init__(self):
        self.book = Portfolio()

    def submit(self, intent, limit_price, client_order_id):
        fill = Fill(intent.instrument, intent.side, intent.qty, limit_price, order_id=client_order_id)
        self.book.apply(fill)
        return ExecutionReport(intent, "filled", [fill], [client_order_id])

    def net_position(self, instrument):
        pos = self.book.positions.get(instrument)
        return pos.qty if pos else 0.0

    def cash(self):
        return self.book.cash

    def lookup(self, client_order_ids):
        return {}


class _BuyCheap:
    strategy_id = "buy-cheap"

    def decide(self, ctx):
        return [OrderIntent(i, Side.BUY, 1, limit_price=q.ask) for i, q in ctx.quotes.items()
                if q.ask is not None and q.ask < 0.5 and i not in ctx.positions]


class _Feed:
    def __init__(self, quotes):
        self._q = {q.instrument: q for q in quotes}

    def quote(self, instrument):
        return self._q.get(instrument)

    def quotes(self, instruments):
        return {i: self._q[i] for i in instruments if i in self._q}


class _ConstFeature:
    name = "const"

    def feature_names(self):
        return ["one"]

    def features(self, instruments, as_of):
        return {i.id: {"one": 1.0} for i in instruments}


def test_ports_are_structural_and_compose_into_a_decision_loop():
    venue, strat, clock = _PaperVenue(), _BuyCheap(), FixedClock(1_000.0)
    poly = InstrumentId("polymarket", "0xabc", "yes")
    feed = _Feed([Quote(KALSHI_YES, 999.0, 0.40, 0.42), Quote(poly, 999.0, 0.60, 0.62)])
    assert isinstance(venue, Venue) and isinstance(strat, Strategy) and isinstance(clock, Clock)
    assert isinstance(feed, MarketDataFeed) and isinstance(_ConstFeature(), FeatureProvider)
    assert isinstance(ZeroFees(), FeeModel) and ZeroFees().fee(_binary(), 10, 0.5) == 0.0

    ctx = DecisionContext(now=clock.now(), instruments={}, quotes=feed.quotes([KALSHI_YES, poly]))
    for intent in strat.decide(ctx):
        venue.submit(intent, intent.limit_price, "c1")
    assert venue.net_position(KALSHI_YES) == 1 and venue.net_position(poly) == 0
    assert venue.cash() == pytest.approx(-0.42)
    clock.advance(60)
    assert clock.now() == 1_060.0


def test_instrument_id_hash_is_cached_but_stays_consistent_across_copies_and_processes():
    import copy
    import pickle
    from dataclasses import replace
    a = InstrumentId("kalshi", "KXBTCD-X", "yes")
    b = InstrumentId("kalshi", "KXBTCD-X", "yes")
    assert a == b and hash(a) == hash(b) and {a: 1}[b] == 1
    no = replace(a, outcome="no")
    assert no != a and hash(no) == hash(InstrumentId("kalshi", "KXBTCD-X", "no"))
    for clone in (pickle.loads(pickle.dumps(a)), copy.deepcopy(a), copy.copy(a)):
        assert clone == a and hash(clone) == hash(a)
    assert sorted([no, a]) == [no, a]  # order=True still compares the fields
