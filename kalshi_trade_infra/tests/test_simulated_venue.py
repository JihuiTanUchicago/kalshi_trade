"""The simulator must be able to fail the way the live engine fails.

The old paper book paid the quoted price for the full size, instantly, on both
legs, every time. It therefore could not miss an entry, could not fail an exit
and could not be left holding a contract into settlement - all three of which
happened live on 2026-09-27. These tests pin the failures back in.
"""
from datetime import timedelta

import pytest

from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
from data_pipeline.architecture.simulated_venue import SimulatedVenue
from data_pipeline.common import utc_now
from data_pipeline.kalshi_fees import taker_fee_dollars
from data_pipeline.market_data import Quote

TICKER = "KXBTC15M-26SEP271315-15"


def quote(bid, ask, bid_size=3080.0, ask_size=2406.0, age_s=0.0):
    return Quote(ticker=TICKER, yes_bid=bid, yes_ask=ask, yes_bid_size=bid_size,
                 yes_ask_size=ask_size, as_of=utc_now() - timedelta(seconds=age_s),
                 source="websocket")


class Feed:
    def __init__(self, q):
        self.q = q

    def quote(self, ticker, max_age_seconds=None):
        return self.q


def intent(action, qty, price):
    return TradeIntent(action=action, side="yes", ticker=TICKER, qty_contracts=qty,
                       limit_price_dollars=price, model_name="m", now_ts=None, metadata={})


def test_venue_returns_kalshis_response_shape():
    """Both venues must be read by the same fill parser, or they will drift."""
    v = SimulatedVenue(Feed(quote(0.30, 0.31)))
    resp = v(TICKER, "buy", "yes", 25, 0.32)["resp"]
    assert set(resp) >= {"order_id", "fill_count", "average_fill_price", "average_fee_paid"}
    assert resp["fill_count"] == "25.00"
    assert float(resp["average_fill_price"]) == pytest.approx(0.31)


def test_a_limit_that_does_not_reach_the_ask_does_not_fill():
    v = SimulatedVenue(Feed(quote(0.30, 0.31)))
    assert v(TICKER, "buy", "yes", 25, 0.29)["resp"]["fill_count"] == "0.00"


def test_a_sell_below_the_bid_fills_at_the_bid_not_at_the_limit():
    v = SimulatedVenue(Feed(quote(0.38, 0.39)))
    resp = v(TICKER, "sell", "yes", 25, 0.36)["resp"]
    assert float(resp["average_fill_price"]) == pytest.approx(0.38)


def test_fill_is_capped_by_the_size_resting_at_the_touch():
    v = SimulatedVenue(Feed(quote(0.30, 0.31, ask_size=8.0)))
    assert v(TICKER, "buy", "yes", 25, 0.35)["resp"]["fill_count"] == "8.00"


def test_no_quote_means_no_fill():
    class Empty:
        def quote(self, ticker, max_age_seconds=None):
            return None

    assert SimulatedVenue(Empty())(TICKER, "buy", "yes", 25, 0.35)["resp"]["fill_count"] == "0.00"


def test_venue_charges_kalshis_taker_fee():
    v = SimulatedVenue(Feed(quote(0.30, 0.31)))
    resp = v(TICKER, "buy", "yes", 25, 0.35)["resp"]
    total = float(resp["average_fee_paid"]) * 25
    assert total == pytest.approx(taker_fee_dollars(25, 0.31), abs=1e-6)
    assert total > 0


def test_sim_and_live_run_the_identical_policy():
    """The kernel cannot tell the venues apart: same limits, same decisions."""
    q = quote(0.30, 0.31)
    sent_live = []

    def live_submitter(ticker, action, side, qty, price):
        sent_live.append(price)
        return {"client_order_id": "c", "body": {},
                "resp": {"fill_count": f"{qty}.00", "average_fill_price": "0.3100",
                         "average_fee_paid": "0.0100", "order_id": "o"}}

    venue = SimulatedVenue(Feed(q))
    sim_kernel = MarketableLimitKernel(venue, Feed(q), entry_cross_ticks=1, max_entry_slippage=0.05)
    live_kernel = MarketableLimitKernel(live_submitter, Feed(q), entry_cross_ticks=1, max_entry_slippage=0.05)

    sim_rep = sim_kernel.execute(intent("buy", 25, 0.30))
    live_rep = live_kernel.execute(intent("buy", 25, 0.30))

    assert sim_rep.fill_qty_contracts == live_rep.fill_qty_contracts == 25
    assert sim_rep.fill_price_dollars == pytest.approx(live_rep.fill_price_dollars)
    assert sent_live[0] == pytest.approx(0.32), "both crossed the live ask by one tick"


def test_the_simulator_can_now_miss_an_entry_the_way_live_does():
    """Under the old sim this entry was unconditionally filled at the ask."""
    q = quote(0.44, 0.45)
    venue = SimulatedVenue(Feed(q))
    kernel = MarketableLimitKernel(venue, Feed(q), max_entry_slippage=0.02)
    rep = kernel.execute(intent("buy", 25, 0.30))
    assert rep.status == "edge_gone"
    assert venue.orders_sent == 0


def test_the_simulator_can_now_fail_an_exit_the_way_live_does():
    """No bid at all: six consecutive live sells were cancelled like this."""
    q = quote(None, 0.05)
    venue = SimulatedVenue(Feed(q))
    kernel = MarketableLimitKernel(venue, Feed(q), exit_cross_ticks=2, max_attempts=3)
    rep = kernel.execute(intent("sell", 27, 0.32))
    assert rep.fill_qty_contracts == 0
    assert rep.accepted is False
