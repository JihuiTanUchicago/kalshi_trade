"""No sell may take the account past flat.

The strategy only ever buys YES, yet it ended up short: sells were sized from
our own live_positions row, the row was wrong, and on Kalshi a YES sell with
nothing behind it opens a short instead of failing. These tests run the real
kernel against SimulatedVenue - which now nets positions the way Kalshi does -
and pin that the guard sizes every sell to what the venue says is held.
"""
from datetime import timedelta

import pytest

from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.architecture.execution_kernel import DummyExecutionKernel, MarketableLimitKernel
from data_pipeline.architecture.position_guard import (
    PositionGuard,
    net_from_positions_response,
    position_guarded_submitter,
)
from data_pipeline.architecture.simulated_venue import SimulatedVenue
from data_pipeline.common import utc_now
from data_pipeline.market_data import Quote

TICKER = "KXBTC15M-26SEP271315-15"


def quote(bid, ask, bid_size=3080.0, ask_size=2406.0):
    return Quote(ticker=TICKER, yes_bid=bid, yes_ask=ask, yes_bid_size=bid_size,
                 yes_ask_size=ask_size, as_of=utc_now() - timedelta(seconds=0), source="websocket")


class Feed:
    def __init__(self, q):
        self.q = q

    def quote(self, ticker, max_age_seconds=None):
        return self.q


def intent(action, qty, price, side="yes"):
    return TradeIntent(action=action, side=side, ticker=TICKER, qty_contracts=qty,
                       limit_price_dollars=price, model_name="m", now_ts=None, metadata={})


def kernel(submit, feed, attempts=3):
    return MarketableLimitKernel(submit, feed, max_attempts=attempts)


def test_unguarded_sell_of_a_phantom_position_opens_a_short():
    """The bug, reproduced: our book says 25, Kalshi holds nothing, the sell goes through."""
    feed = Feed(quote(0.70, 0.71))
    venue = SimulatedVenue(feed)
    rep = kernel(venue, feed).execute(intent("sell", 25, 0.70))
    assert rep.fill_qty_contracts == 25
    assert venue.net_position(TICKER) == -25  # short, though we only ever bought YES


def test_guarded_sell_of_a_phantom_position_is_refused():
    feed = Feed(quote(0.70, 0.71))
    venue = SimulatedVenue(feed)
    rep = kernel(position_guarded_submitter(venue, venue.net_position), feed).execute(intent("sell", 25, 0.70))
    assert not rep.accepted and rep.fill_qty_contracts == 0
    assert venue.orders_sent == 0
    assert venue.net_position(TICKER) == 0


def test_book_overcounts_sell_is_shrunk_to_what_is_held():
    """Book says 25, Kalshi holds 10: sell 10, get flat, never cross zero on the retries."""
    feed = Feed(quote(0.70, 0.71))
    venue = SimulatedVenue(feed, positions={TICKER: 10})
    rep = kernel(position_guarded_submitter(venue, venue.net_position), feed).execute(intent("sell", 25, 0.70))
    assert rep.fill_qty_contracts == 10 and rep.status == "partially_filled"
    assert venue.net_position(TICKER) == 0
    assert venue.orders_sent == 1  # the escalating retries for the other 15 were refused, not sent


def test_correctly_sized_exit_is_untouched():
    feed = Feed(quote(0.70, 0.71))
    venue = SimulatedVenue(feed, positions={TICKER: 25})
    rep = kernel(position_guarded_submitter(venue, venue.net_position), feed).execute(intent("sell", 25, 0.70))
    assert rep.status == "filled" and rep.fill_qty_contracts == 25
    assert venue.net_position(TICKER) == 0


def test_entry_then_exit_round_trip_ends_flat():
    feed = Feed(quote(0.30, 0.31))
    venue = SimulatedVenue(feed)
    k = kernel(position_guarded_submitter(venue, venue.net_position), feed)
    assert k.execute(intent("buy", 25, 0.31)).fill_qty_contracts == 25
    assert venue.net_position(TICKER) == 25
    assert k.execute(intent("sell", 25, 0.30)).fill_qty_contracts == 25
    assert venue.net_position(TICKER) == 0


def test_buys_are_never_gated_even_when_positions_cannot_be_read():
    feed = Feed(quote(0.30, 0.31))
    venue = SimulatedVenue(feed)

    def broken(ticker):
        raise RuntimeError("positions 503")

    rep = kernel(position_guarded_submitter(venue, broken), feed).execute(intent("buy", 25, 0.31))
    assert rep.fill_qty_contracts == 25


def test_sell_fails_closed_when_positions_cannot_be_read():
    feed = Feed(quote(0.70, 0.71))
    venue = SimulatedVenue(feed, positions={TICKER: 25})

    def broken(ticker):
        raise RuntimeError("positions 503")

    rep = kernel(position_guarded_submitter(venue, broken), feed).execute(intent("sell", 25, 0.70))
    assert rep.fill_qty_contracts == 0 and venue.orders_sent == 0
    assert venue.net_position(TICKER) == 25  # position kept; the next tick tries again


def test_lagging_position_read_cannot_oversell_across_retries():
    """Kalshi's positions read lags our fills, and the exit sends children back to back.
    Book says 40, Kalshi holds 25, the touch takes 10 at a time, and the read keeps
    answering 25. Trusting it on every child would sell 30 and go 5 short."""
    feed = Feed(quote(0.70, 0.71, bid_size=10.0))
    venue = SimulatedVenue(feed, positions={TICKER: 25})
    stale = lambda ticker: 25  # noqa: E731 - never reflects our own fills
    rep = kernel(position_guarded_submitter(venue, stale), feed, attempts=5).execute(intent("sell", 40, 0.70))
    assert rep.fill_qty_contracts == 25
    assert venue.net_position(TICKER) == 0


def test_fill_memory_expires_so_a_later_rebuy_can_be_sold():
    now = {"t": 0.0}
    feed = Feed(quote(0.70, 0.71))
    venue = SimulatedVenue(feed, positions={TICKER: 5})
    g = PositionGuard(venue.net_position, memory_seconds=30.0, clock=lambda: now["t"])
    sub = g.wrap(venue)
    assert sub(TICKER, "sell", "yes", 5, 0.60)["resp"]["fill_count"] == "5.00"
    venue.positions[TICKER] = 8  # bought again later
    now["t"] = 31.0
    assert sub(TICKER, "sell", "yes", 8, 0.60)["resp"]["fill_count"] == "8.00"
    assert venue.net_position(TICKER) == 0


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, ticker, action, side, qty, price, **kw):
        self.calls.append((action, side, qty, kw))
        return {"resp": {"fill_count": "%d.00" % qty}}


@pytest.mark.parametrize("net,side,qty,sent", [
    (-12, "no", 20, 12),    # holding 12 NO: sell 12 NO
    (-12, "no", 5, 5),
    (5, "no", 3, None),     # holding YES, selling NO would open a YES-side flip
    (-5, "yes", 3, None),   # holding NO, selling YES would deepen the short
    (0, "yes", 1, None),
])
def test_sides_follow_kalshis_signed_net(net, side, qty, sent):
    rec = Recorder()
    res = position_guarded_submitter(rec, lambda t: net)(TICKER, "sell", side, qty, 0.40)
    if sent is None:
        assert rec.calls == [] and res["position_guard_blocked"] == "nothing_held"
    else:
        assert rec.calls[0][2] == sent


def test_client_order_id_passes_through_only_when_given():
    rec = Recorder()
    sub = position_guarded_submitter(rec, lambda t: 10)
    sub(TICKER, "sell", "yes", 1, 0.40)
    sub(TICKER, "buy", "yes", 1, 0.40, client_order_id="abc")
    assert rec.calls[0][3] == {} and rec.calls[1][3] == {"client_order_id": "abc"}


def test_manual_close_path_kernel_reads_a_shrunk_sell_as_partial():
    """dashboard /live_position/close uses DummyExecutionKernel; a shrunk sell must read as partial."""
    feed = Feed(quote(0.70, 0.71))
    venue = SimulatedVenue(feed, positions={TICKER: 4})
    rep = DummyExecutionKernel(position_guarded_submitter(venue, venue.net_position)).execute(
        intent("sell", 10, 0.70))
    assert rep.status == "partially_filled" and rep.fill_qty_contracts == 4
    assert venue.net_position(TICKER) == 0


def test_positions_response_parsing():
    body = {"market_positions": [{"ticker": "OTHER", "position_fp": "7.00"},
                                 {"ticker": TICKER, "position_fp": "-12.00"}]}
    assert net_from_positions_response(body, TICKER) == -12
    assert net_from_positions_response(body, "MISSING") == 0
    assert net_from_positions_response({"market_positions": [{"ticker": TICKER, "position": 3}]}, TICKER) == 3
    assert net_from_positions_response({}, TICKER) == 0
