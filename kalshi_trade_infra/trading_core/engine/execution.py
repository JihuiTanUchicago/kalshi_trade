"""How an approved intent becomes an order: priced from the live quote, never from a stale bar.

``CrossTheTouch`` is the venue-neutral core of ``MarketableLimitKernel``: buy at the ask plus N
ticks, sell at the bid minus N, never through the strategy's own limit, and refuse a stale or
one-sided book instead of guessing. Kalshi's retries, client-order-id derivation and reservation
cap stay in the Kalshi adapter until the live engine moves onto this loop.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from trading_core.domain import ExecutionReport, Instrument, OrderIntent, Quote, Side
from trading_core.ports.venue import Venue

# A limit snapped to the tick grid can sit a float ulp off the touch (1 - 0.7 = 0.30000000000000004).
_PRICE_EPS = 1e-9


@runtime_checkable
class ExecutionPolicy(Protocol):
    def execute(self, intent: OrderIntent, instrument: Instrument, quote: Optional[Quote], venue: Venue,
                client_order_id: str, now: float) -> ExecutionReport:
        ...


class CrossTheTouch:
    def __init__(self, entry_cross_ticks: int = 1, exit_cross_ticks: int = 2,
                 max_quote_age_seconds: float = 2.0) -> None:
        self.entry_cross_ticks = entry_cross_ticks
        self.exit_cross_ticks = exit_cross_ticks
        self.max_quote_age_seconds = max_quote_age_seconds

    def price(self, intent: OrderIntent, instrument: Instrument, quote: Optional[Quote], now: float):
        """(limit price, None) or (None, reason the order must not be sent)."""
        if quote is None:
            return None, "no quote"
        if quote.age(now) > self.max_quote_age_seconds:
            return None, "quote %.1fs old" % quote.age(now)
        ticks = self.exit_cross_ticks if intent.reduce_only else self.entry_cross_ticks
        if intent.side is Side.BUY:
            if quote.ask is None:
                return None, "no ask"
            px = instrument.round_price(quote.ask + ticks * instrument.tick_size)
            if intent.limit_price is not None:
                px = min(px, intent.limit_price)
            if px < quote.ask:
                if quote.ask - px > _PRICE_EPS:
                    return None, "ask %.4f above limit %.4f" % (quote.ask, px)
                px = quote.ask
        else:
            if quote.bid is None:
                return None, "no bid"
            px = instrument.round_price(quote.bid - ticks * instrument.tick_size)
            if intent.limit_price is not None:
                px = max(px, intent.limit_price)
            if px > quote.bid:
                if px - quote.bid > _PRICE_EPS:
                    return None, "bid %.4f below limit %.4f" % (quote.bid, px)
                px = quote.bid
        return px, None

    def execute(self, intent: OrderIntent, instrument: Instrument, quote: Optional[Quote], venue: Venue,
                client_order_id: str, now: float) -> ExecutionReport:
        px, why = self.price(intent, instrument, quote, now)
        if px is None:
            return ExecutionReport(intent, "rejected", message=why)
        return venue.submit(intent, px, client_order_id)
