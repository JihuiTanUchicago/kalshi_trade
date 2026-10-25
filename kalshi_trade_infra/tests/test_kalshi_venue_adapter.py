"""Kalshi binaries behind the trading_core Venue port: same money math as the live kernel."""
from datetime import timedelta

import pytest

from app.adapters.kalshi.convert import from_trade_intent, instrument_id, to_domain_report, to_trade_intent
from app.adapters.kalshi.venue import KalshiBinaryVenue
from data_pipeline.architecture.contracts import ExecutionReport as KalshiReport
from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.common import utc_now
from data_pipeline.kalshi_fees import taker_fee_dollars
from data_pipeline.market_data import Quote
from trading_core.domain import InstrumentId, OrderIntent, Portfolio, Side
from trading_core.ports import Venue

TICKER = "KXBTC15M-26SEP271315-15"
YES, NO = instrument_id(TICKER, "yes"), instrument_id(TICKER, "no")


class Feed:
    def __init__(self, bid, ask, bid_size=50.0, ask_size=40.0):
        self.q = Quote(ticker=TICKER, yes_bid=bid, yes_ask=ask, yes_bid_size=bid_size, yes_ask_size=ask_size,
                       as_of=utc_now() - timedelta(seconds=0), source="websocket")

    def quote(self, ticker, max_age_seconds=None):
        return self.q


def test_simulated_kalshi_is_a_venue_that_sends_nothing_real():
    venue = KalshiBinaryVenue.simulated(Feed(0.40, 0.42))
    assert isinstance(venue, Venue)
    assert venue.capabilities.sends_real_orders is False and venue.capabilities.market_orders is False


def test_yes_buy_fills_at_the_ask_capped_by_touch_size_with_kalshi_fee():
    venue = KalshiBinaryVenue.simulated(Feed(0.40, 0.42, ask_size=30.0))
    rep = venue.submit(OrderIntent(YES, Side.BUY, 50), 0.43, "c-1")
    assert rep.status == "partial" and rep.filled_qty == 30
    assert rep.avg_price == pytest.approx(0.42)
    assert rep.fees == pytest.approx(taker_fee_dollars(30, 0.42), abs=1e-4)  # per-contract fee is a 6dp string
    assert venue.net_position(YES) == 30 and venue.net_position(NO) == -30


def test_no_buy_is_the_mirror_yes_sell_and_reports_the_no_cost_basis():
    venue = KalshiBinaryVenue.simulated(Feed(0.56, 0.58, bid_size=100.0))
    rep = venue.submit(OrderIntent(NO, Side.BUY, 10), 0.45, "c-2")
    assert rep.status == "filled" and rep.filled_qty == 10
    assert rep.avg_price == pytest.approx(0.44)  # 1 - yes_bid, never the YES price
    assert venue.net_position(NO) == 10
    book = Portfolio(cash=100.0)
    book.apply_all(rep.fills)
    assert book.cash == pytest.approx(100.0 - 4.4 - rep.fees)


def test_a_limit_that_does_not_reach_the_touch_is_unfilled_not_phantom():
    venue = KalshiBinaryVenue.simulated(Feed(0.40, 0.42))
    rep = venue.submit(OrderIntent(YES, Side.BUY, 5), 0.41, "c-3")
    assert rep.status == "unfilled" and rep.fills == [] and rep.avg_price is None


def test_filled_with_unreadable_price_falls_back_to_the_own_side_limit():
    sent = []

    def submitter(ticker, action, side, qty, price, client_order_id=None):
        sent.append((ticker, action, side, qty, price, client_order_id))
        return {"client_order_id": client_order_id, "resp": {"order_id": "o9", "fill_count": "3.00"}}

    venue = KalshiBinaryVenue(submitter, read_net=lambda t: 0)
    rep = venue.submit(OrderIntent(NO, Side.BUY, 3), 0.30, "c-4")
    assert sent == [(TICKER, "buy", "no", 3, 0.30, "c-4")]
    assert rep.avg_price == pytest.approx(0.30) and rep.order_ids == ["o9"]
    assert venue.capabilities.sends_real_orders is True and venue.cash() is None


def test_refuses_instruments_from_another_venue_before_sending():
    venue = KalshiBinaryVenue(lambda *a, **k: pytest.fail("must not send"))
    with pytest.raises(ValueError):
        venue.submit(OrderIntent(InstrumentId("polymarket", "0xabc", "yes"), Side.BUY, 1), 0.5, "c-5")
    with pytest.raises(RuntimeError):
        venue.net_position(YES)


def test_trade_intent_round_trip_keeps_order_economics():
    ti = TradeIntent(action="sell", side="no", ticker=TICKER, qty_contracts=7, limit_price_dollars=0.61,
                     model_name="dep-12", now_ts=None, metadata={"fair": 0.65, "min_edge": 0.02})
    intent = from_trade_intent(ti)
    assert intent.instrument == NO and intent.side is Side.SELL and intent.reduce_only
    assert intent.fair_value == 0.65 and intent.strategy_id == "dep-12"
    back = to_trade_intent(intent, 0.61)
    assert (back.action, back.side, back.ticker, back.qty_contracts, back.limit_price_dollars) == \
        ("sell", "no", TICKER, 7, 0.61)
    assert back.metadata["min_edge"] == 0.02
    with pytest.raises(ValueError):
        instrument_id(TICKER, "maybe")


def test_kernel_statuses_map_to_domain_statuses():
    intent = OrderIntent(YES, Side.BUY, 4)
    for kernel, domain in (("filled", "filled"), ("partially_filled", "partial"), ("unfilled", "unfilled"),
                           ("edge_gone_net", "rejected"), ("no_quote", "rejected")):
        filled = 4 if kernel == "filled" else (2 if kernel == "partially_filled" else 0)
        rep = to_domain_report(KalshiReport(filled > 0, kernel, 0.5 if filled else 0.0, filled, None, None), intent)
        assert rep.status == domain and rep.filled_qty == filled and rep.message == kernel
