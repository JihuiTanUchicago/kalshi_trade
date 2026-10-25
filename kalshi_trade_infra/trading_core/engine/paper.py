"""A paper Venue for any market: a marketable limit fills in full at the touch, priced by a FeeModel.

It is the venue-neutral counterpart of ``SimulatedVenue`` (which stays the Kalshi paper venue, with
its depth and YES/NO wire rules). Use it to backtest or paper-trade a market that has no venue
adapter yet; it never sends anything anywhere.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from trading_core.domain import ExecutionReport, Fill, Instrument, InstrumentId, OrderIntent, Portfolio, Side
from trading_core.ports.fees import FeeModel
from trading_core.ports.market_data import MarketDataFeed
from trading_core.ports.venue import VenueCapabilities


class QuoteFillVenue:
    def __init__(self, feed: MarketDataFeed, fees: FeeModel, instruments: Mapping[InstrumentId, Instrument],
                 cash: float = 0.0, name: str = "paper", shorting: bool = False) -> None:
        self.name = name
        self.capabilities = VenueCapabilities(kinds=frozenset(i.kind for i in instruments.values()),
                                              market_orders=False, shorting=shorting, fractional_qty=True,
                                              sends_real_orders=False)
        self._feed, self._fees, self._instruments = feed, fees, instruments
        self.book = Portfolio(cash=cash)

    def submit(self, intent: OrderIntent, limit_price: float, client_order_id: str) -> ExecutionReport:
        q = self._feed.quote(intent.instrument)
        inst = self._instruments[intent.instrument]
        held = self.net_position(intent.instrument)
        if intent.side is Side.SELL and not self.capabilities.shorting and intent.qty > held + 1e-12:
            return ExecutionReport(intent, "rejected", message="sell %g > held %g" % (intent.qty, held))
        touch: Optional[float] = None
        if q is not None:
            touch = q.ask if intent.side is Side.BUY else q.bid
        crosses = touch is not None and (touch <= limit_price if intent.side is Side.BUY else touch >= limit_price)
        if not crosses:
            return ExecutionReport(intent, "unfilled", order_ids=[client_order_id])
        fee = self._fees.fee(inst, intent.qty, touch)
        fill = Fill(intent.instrument, intent.side, intent.qty, touch, fee=fee, ts=q.ts, order_id=client_order_id)
        self.book.apply(fill, multiplier=inst.multiplier)
        return ExecutionReport(intent, "filled", [fill], [client_order_id])

    def net_position(self, instrument: InstrumentId) -> float:
        pos = self.book.positions.get(instrument)
        return pos.qty if pos else 0.0

    def cash(self) -> Optional[float]:
        return self.book.cash

    def lookup(self, client_order_ids: Sequence[str]) -> Mapping[str, ExecutionReport]:
        return {}
