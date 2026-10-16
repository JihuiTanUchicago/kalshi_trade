"""Execution prices from the live book, never from a stale bar.

On 2026-09-27 the engine built every order from model_features_1m rows[-1],
a completed one-minute bar. Measured live, that bar read bid 0.58 / ask 0.59
while Kalshi's book was 0.70 / 0.71. Buys priced under the real ask never
crossed; sells priced under the real bid crossed instantly and gave away the
difference. Top-of-book depth was 2,000-3,000 contracts against orders of
25-33, so liquidity was never the constraint.
"""
from datetime import timedelta

import pytest

from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
from data_pipeline.common import utc_now
from data_pipeline.market_data import Quote

TICKER = "KXBTC15M-26SEP271315-15"


def quote(bid, ask, age_s=0.0, source="websocket"):
    return Quote(
        ticker=TICKER, yes_bid=bid, yes_ask=ask, yes_bid_size=3080.0, yes_ask_size=2406.0,
        as_of=utc_now() - timedelta(seconds=age_s), source=source,
    )


class FakeFeed:
    def __init__(self, *quotes):
        self._quotes = list(quotes)
        self.calls = 0

    def quote(self, ticker, max_age_seconds=None):
        self.calls += 1
        q = self._quotes[min(self.calls - 1, len(self._quotes) - 1)]
        return q


class RecordingSubmitter:
    """Fills only when the limit actually crosses the book."""

    def __init__(self, feed_quotes, fee="0.0100"):
        self._quotes = feed_quotes
        self.sent = []
        self._fee = fee

    def __call__(self, ticker, action, side, qty, price):
        self.sent.append({"action": action, "qty": qty, "price": price})
        q = self._quotes[min(len(self.sent) - 1, len(self._quotes) - 1)]
        crosses = price >= q.yes_ask if action == "buy" else price <= q.yes_bid
        if not crosses:
            return {"client_order_id": "c", "body": {}, "resp": {"fill_count": "0.00", "order_id": "o"}}
        fill_px = q.yes_ask if action == "buy" else q.yes_bid
        return {"client_order_id": "c", "body": {},
                "resp": {"fill_count": f"{qty}.00", "average_fill_price": f"{fill_px:.4f}",
                         "average_fee_paid": self._fee, "order_id": "o"}}


def intent(action, qty, signal_price):
    return TradeIntent(action=action, side="yes", ticker=TICKER, qty_contracts=qty,
                       limit_price_dollars=signal_price, model_name="m", now_ts=None, metadata={})


def test_buy_is_priced_from_the_live_book_not_the_signal_price():
    """The exact 2026-09-27 case: bar said 0.59, book was 0.71."""
    q = quote(bid=0.70, ask=0.71)
    feed, sub = FakeFeed(q), RecordingSubmitter([q])
    k = MarketableLimitKernel(sub, feed, entry_cross_ticks=1, max_entry_slippage=0.20)
    rep = k.execute(intent("buy", 27, 0.59))
    assert sub.sent[0]["price"] == pytest.approx(0.72)  # live ask + 1 tick, not 0.59
    assert rep.fill_qty_contracts == 27
    assert rep.fill_price_dollars == pytest.approx(0.71)


def test_sell_crosses_down_from_the_live_bid():
    q = quote(bid=0.38, ask=0.39)
    feed, sub = FakeFeed(q), RecordingSubmitter([q])
    k = MarketableLimitKernel(sub, feed, exit_cross_ticks=2)
    rep = k.execute(intent("sell", 25, 0.29))
    assert sub.sent[0]["price"] == pytest.approx(0.36)  # live bid - 2 ticks
    assert rep.fill_price_dollars == pytest.approx(0.38)


def test_entry_is_abandoned_when_the_ask_has_run_past_the_signal():
    """Following the book must not become chasing it."""
    q = quote(bid=0.44, ask=0.45)
    feed, sub = FakeFeed(q), RecordingSubmitter([q])
    k = MarketableLimitKernel(sub, feed, max_entry_slippage=0.02)
    rep = k.execute(intent("buy", 25, 0.30))
    assert rep.status == "edge_gone"
    assert rep.accepted is False
    assert sub.sent == [], "no order may be sent once the edge is gone"


def test_exit_escalates_through_the_book_until_it_fills():
    """An unfilled exit is what carried 27 contracts into settlement.

    The book here falls one tick between each quote and the order landing, so
    an exit priced at the touch keeps just missing - exactly the pattern that
    produced six consecutive cancelled sells on KXBTC15M-26SEP271315-15.
    """
    seen = [quote(bid=0.30, ask=0.31), quote(bid=0.28, ask=0.29), quote(bid=0.26, ask=0.27)]
    # What the book actually is by the time each order arrives: one step later.
    on_arrival = seen[1:] + [seen[-1]]
    sub = RecordingSubmitter(on_arrival)
    k = MarketableLimitKernel(sub, FakeFeed(*seen), exit_cross_ticks=0, max_attempts=3)
    rep = k.execute(intent("sell", 27, 0.30))
    assert [round(x["price"], 2) for x in sub.sent] == [0.30, 0.27, 0.24], "each retry crosses one tick further"
    assert rep.fill_qty_contracts == 27, "escalation must eventually get the position out"
    assert rep.fill_price_dollars == pytest.approx(0.26)


def test_exit_gives_up_rather_than_selling_at_any_price():
    """Escalation is bounded: max_attempts caps how far it will walk down."""
    q = quote(bid=0.30, ask=0.31)

    def never_fills(ticker, action, side, qty, price):
        return {"client_order_id": "c", "body": {}, "resp": {"fill_count": "0.00", "order_id": "o"}}

    rep = MarketableLimitKernel(never_fills, FakeFeed(q), exit_cross_ticks=1, max_attempts=3).execute(
        intent("sell", 27, 0.30)
    )
    assert rep.status == "unfilled"
    assert rep.fill_qty_contracts == 0
    assert len(rep.raw_json["attempts"]) == 3


def test_no_quote_means_no_order():
    class Empty:
        def quote(self, ticker, max_age_seconds=None):
            return None

    sent = []
    k = MarketableLimitKernel(lambda *a: sent.append(a), Empty(), max_attempts=3)
    rep = k.execute(intent("buy", 10, 0.30))
    assert rep.status == "no_quote"
    assert rep.accepted is False
    assert sent == []


def test_an_untradable_quote_is_not_a_quote():
    q = quote(bid=0.0, ask=0.0)
    sent = []
    k = MarketableLimitKernel(lambda *a: sent.append(a), FakeFeed(q))
    assert k.execute(intent("buy", 10, 0.30)).status == "no_quote"
    assert sent == []


def test_limits_stay_inside_kalshis_price_bounds():
    q = quote(bid=0.99, ask=0.99)
    feed, sub = FakeFeed(q), RecordingSubmitter([q])
    k = MarketableLimitKernel(sub, feed, entry_cross_ticks=5, max_entry_slippage=1.0)
    k.execute(intent("buy", 5, 0.99))
    assert sub.sent[0]["price"] <= 0.99
    q2 = quote(bid=0.01, ask=0.02)
    feed2, sub2 = FakeFeed(q2), RecordingSubmitter([q2])
    k2 = MarketableLimitKernel(sub2, feed2, exit_cross_ticks=5)
    k2.execute(intent("sell", 5, 0.01))
    assert sub2.sent[0]["price"] >= 0.01


def test_reported_fill_never_exceeds_what_kalshi_confirmed():
    q = quote(bid=0.50, ask=0.51)
    feed = FakeFeed(q)

    def partial(ticker, action, side, qty, price):
        return {"client_order_id": "c", "body": {},
                "resp": {"fill_count": "6.00", "average_fill_price": "0.5100", "order_id": "o"}}

    rep = MarketableLimitKernel(partial, feed, max_entry_slippage=1.0).execute(intent("buy", 20, 0.50))
    assert rep.fill_qty_contracts == 6
    assert rep.status == "partially_filled"
