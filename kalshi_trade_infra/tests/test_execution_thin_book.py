"""Thin-book microstructure controls in MarketableLimitKernel.

Four opt-in, fail-safe controls for low-liquidity prediction-market books,
each covered happy-path and adversarial here:

  * participation cap (``max_book_fraction``) - a child order can't walk a thin
    touch against itself; an exit slices and keeps going, never traps;
  * exit partial-fill continuation - a part-filled EXIT keeps taking the
    remainder across escalating attempts, size-weighting the reported price;
  * entry spread guard (``max_entry_spread``) - a wide touch abandons a
    non-urgent entry but never an exit;
  * per-order notional backstop (``max_order_notional``) - a BUY over the cap
    is rejected in the execution path; a SELL is never blocked.

Every control can only SHRINK or ABANDON an order, never enlarge it, and none
may ever block an exit - the 2026-09-27 lesson that an unfilled exit is the
expensive failure.
"""
from datetime import timedelta

import pytest

from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
from data_pipeline.common import utc_now
from data_pipeline.market_data import Quote

TICKER = "KXBTC15M-26SEP271315-15"


def quote(bid, ask, bid_size=3000.0, ask_size=3000.0, age_s=0.0):
    return Quote(ticker=TICKER, yes_bid=bid, yes_ask=ask, yes_bid_size=bid_size,
                 yes_ask_size=ask_size, as_of=utc_now() - timedelta(seconds=age_s), source="websocket")


class FakeFeed:
    def __init__(self, *quotes):
        self._quotes = list(quotes)
        self.calls = 0

    def quote(self, ticker, max_age_seconds=None):
        self.calls += 1
        return self._quotes[min(self.calls - 1, len(self._quotes) - 1)]


class CappedSubmitter:
    """Fills min(requested child, resting touch size) at the touch when the
    limit crosses - a venue that will not hand out more than is on the book."""

    def __init__(self, feed_quotes, fee="0.0100"):
        self._quotes = feed_quotes
        self.sent = []
        self._fee = fee

    def __call__(self, ticker, action, side, qty, price):
        self.sent.append({"action": action, "qty": qty, "price": price})
        q = self._quotes[min(len(self.sent) - 1, len(self._quotes) - 1)]
        if action == "buy":
            crosses, touch, size = price >= q.yes_ask, q.yes_ask, q.yes_ask_size
        else:
            crosses, touch, size = price <= q.yes_bid, q.yes_bid, q.yes_bid_size
        if not crosses:
            return {"client_order_id": "c", "body": {}, "resp": {"fill_count": "0.00", "order_id": "o"}}
        filled = min(int(qty), int(size)) if size is not None else int(qty)
        if filled <= 0:
            return {"client_order_id": "c", "body": {}, "resp": {"fill_count": "0.00", "order_id": "o"}}
        return {"client_order_id": "c", "body": {},
                "resp": {"fill_count": f"{filled}.00", "average_fill_price": f"{touch:.4f}",
                         "average_fee_paid": self._fee, "order_id": "o"}}


def intent(action, qty, signal_price, side="yes"):
    return TradeIntent(action=action, side=side, ticker=TICKER, qty_contracts=qty,
                       limit_price_dollars=signal_price, model_name="m", now_ts=None, metadata={})


# -- participation cap ----------------------------------------------------------


def test_buy_child_is_capped_to_a_fraction_of_the_touch():
    # Thin touch of 40; fraction 0.25 -> at most 10 contracts sent on a 100 order.
    q = quote(bid=0.30, ask=0.31, ask_size=40.0)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, max_entry_slippage=1.0, max_book_fraction=0.25)
    rep = k.execute(intent("buy", 100, 0.30))
    assert sub.sent[0]["qty"] == 10, "child must be floor(0.25 * 40)"
    assert rep.fill_qty_contracts == 10
    assert rep.status == "partially_filled", "an entry takes what the touch gives and stops"
    assert len(sub.sent) == 1, "an entry does not chase the remainder up the book"


def test_sell_slices_and_keeps_going_until_flat():
    # Exit of 30 into a 10-deep touch, fraction 0.5 -> child floored at 5 each
    # attempt (0.5*10); it must keep taking the remainder across attempts.
    q = quote(bid=0.40, ask=0.41, bid_size=10.0)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, exit_cross_ticks=0, max_attempts=10, max_book_fraction=0.5)
    rep = k.execute(intent("sell", 30, 0.40))
    assert rep.fill_qty_contracts == 30, "an exit must keep slicing until flat"
    assert all(s["qty"] == 5 for s in sub.sent), "each exit child is floor(0.5 * 10) = 5"
    assert rep.fill_price_dollars == pytest.approx(0.40)


def test_participation_cap_never_traps_an_exit_on_a_tiny_touch():
    # A touch so thin the fraction rounds to zero: floor(0.1 * 3) = 0. A buy
    # would stop; an exit is floored at 1 so it can always make progress out.
    q = quote(bid=0.40, ask=0.41, bid_size=3.0, ask_size=3.0)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, exit_cross_ticks=0, max_attempts=5, max_book_fraction=0.1)
    rep = k.execute(intent("sell", 2, 0.40))
    assert rep.fill_qty_contracts == 2, "exit child floored at 1 -> gets out one at a time"
    assert all(s["qty"] == 1 for s in sub.sent)


def test_buy_abandoned_when_participation_cap_leaves_no_room():
    q = quote(bid=0.40, ask=0.41, ask_size=3.0)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, max_entry_slippage=1.0, max_book_fraction=0.1)
    rep = k.execute(intent("buy", 5, 0.40))
    assert rep.status == "participation_capped" and rep.accepted is False
    assert sub.sent == [], "no order when the cap rounds the child to zero"


def test_unknown_touch_depth_is_not_capped():
    q = quote(bid=0.40, ask=0.41, ask_size=None)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, max_entry_slippage=1.0, max_book_fraction=0.25)
    k.execute(intent("buy", 50, 0.40))
    assert sub.sent[0]["qty"] == 50, "cannot size to depth we cannot see -> send the full order"


# -- exit partial-fill continuation ---------------------------------------------


def test_exit_partial_fill_continues_and_size_weights_the_price():
    # Touch #1 fills 10 @ 0.40, then the book drops and touch #2 fills the
    # remaining 10 @ 0.38. The reported exit is the size-weighted average.
    seen = [quote(bid=0.40, ask=0.41, bid_size=10.0), quote(bid=0.38, ask=0.39, bid_size=1000.0)]
    feed, sub = FakeFeed(*seen), CappedSubmitter(seen)
    k = MarketableLimitKernel(sub, feed, exit_cross_ticks=0, max_attempts=3)
    rep = k.execute(intent("sell", 20, 0.40))
    assert rep.fill_qty_contracts == 20
    assert rep.fill_price_dollars == pytest.approx((10 * 0.40 + 10 * 0.38) / 20)
    assert rep.status == "filled"


def test_exit_keeps_a_partial_when_attempts_run_out():
    # Only 10 ever available before attempts exhaust: report the 10 that sold,
    # never the 20 requested - a partial exit must never look like a full one.
    q = quote(bid=0.40, ask=0.41, bid_size=10.0)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, exit_cross_ticks=0, max_attempts=1)
    rep = k.execute(intent("sell", 20, 0.40))
    assert rep.fill_qty_contracts == 10
    assert rep.status == "partially_filled" and rep.accepted is True


def test_fees_accumulate_across_sliced_exit_children():
    q = quote(bid=0.50, ask=0.51, bid_size=5.0)
    feed = FakeFeed(q)
    sub = CappedSubmitter([q], fee="0.0100")  # $0.01 per contract
    k = MarketableLimitKernel(sub, feed, exit_cross_ticks=0, max_attempts=5, max_book_fraction=1.0)
    rep = k.execute(intent("sell", 15, 0.50))
    assert rep.fill_qty_contracts == 15
    assert rep.fee_dollars == pytest.approx(0.15), "3 children of 5 @ $0.01/contract = $0.15"


# -- entry spread guard ---------------------------------------------------------


def test_wide_spread_abandons_a_non_urgent_entry():
    q = quote(bid=0.30, ask=0.45)  # 15c spread
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, max_entry_slippage=1.0, max_entry_spread=0.05)
    rep = k.execute(intent("buy", 10, 0.45))
    assert rep.status == "spread_too_wide" and rep.accepted is False
    assert sub.sent == [], "a wide, uncertain book is not worth paying half the spread into"


def test_spread_guard_never_blocks_an_exit():
    q = quote(bid=0.30, ask=0.45)  # same 15c spread
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, exit_cross_ticks=1, max_attempts=1, max_entry_spread=0.05)
    rep = k.execute(intent("sell", 10, 0.30))
    assert rep.fill_qty_contracts == 10, "an exit must get out regardless of the spread"


def test_narrow_spread_passes_the_entry_through():
    q = quote(bid=0.30, ask=0.31)  # 1c spread
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, max_entry_slippage=1.0, max_entry_spread=0.05)
    rep = k.execute(intent("buy", 10, 0.31))
    assert rep.fill_qty_contracts == 10


# -- per-order notional backstop ------------------------------------------------


def test_buy_over_the_notional_cap_is_rejected_in_the_execution_path():
    # 100 contracts * ~0.52 limit = ~$52 notional, cap $10 -> rejected before send.
    q = quote(bid=0.50, ask=0.51)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, entry_cross_ticks=1, max_entry_slippage=1.0, max_order_notional=10.0)
    rep = k.execute(intent("buy", 100, 0.51))
    assert rep.status == "order_notional_exceeded" and rep.accepted is False
    assert sub.sent == [], "the backstop rejects a mis-sized order before it reaches the wire"


def test_notional_backstop_never_blocks_an_exit():
    q = quote(bid=0.50, ask=0.51)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, exit_cross_ticks=1, max_attempts=1, max_order_notional=1.0)
    rep = k.execute(intent("sell", 100, 0.50))
    assert rep.fill_qty_contracts == 100, "a notional cap must never trap a position"


def test_buy_within_the_notional_cap_goes_through():
    q = quote(bid=0.50, ask=0.51)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, entry_cross_ticks=1, max_entry_slippage=1.0, max_order_notional=100.0)
    rep = k.execute(intent("buy", 10, 0.51))
    assert rep.fill_qty_contracts == 10


# -- controls are off by default ------------------------------------------------


def test_all_controls_default_off_preserves_prior_behaviour():
    # No knobs set: full size sent in one shot, no spread/notional/participation gate.
    q = quote(bid=0.30, ask=0.31, ask_size=5.0)
    feed, sub = FakeFeed(q), CappedSubmitter([q])
    k = MarketableLimitKernel(sub, feed, max_entry_slippage=1.0)
    k.execute(intent("buy", 100, 0.31))
    assert sub.sent[0]["qty"] == 100, "without a participation cap the full order is sent"
