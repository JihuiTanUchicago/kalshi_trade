"""A venue that behaves like Kalshi but never sends an order.

The point of this module is that the simulator and the live engine run the
*same* execution policy. `MarketableLimitKernel` does not know or care which
venue it is talking to: it prices from the live book, crosses by the same
number of ticks, re-checks the same edge tolerance and escalates the same way.
Only the submitter differs.

    live:  MarketableLimitKernel(place_limit_order,        feed)
    sim:   MarketableLimitKernel(SimulatedVenue(feed),     feed)

That is what makes paper P&L comparable to live P&L. The old simulator paid
the quoted price for the full size, instantly, on both legs, every time - so
it could not miss an entry, could not fail an exit, and could not be left
holding a contract into settlement. All three happened live on 2026-09-27.

What is modelled here, and what is not:

  modelled     crossing the touch, partial fills against the resting size at
               the touch, Kalshi's taker fee, orders that do not fill, and the
               account's signed net position per ticker - including that a
               sell with nothing behind it opens a short, as it does on Kalshi
  not modelled queue position, depth past the touch (the ticker channel does
               not carry it), and market impact

Touch depth on these markets runs 2,000-3,000 contracts against orders of
25-33, so depth past the touch is not currently the binding constraint. Queue
position does not apply: every order this system sends is a taker.
"""
import uuid
from typing import Dict, Optional

from data_pipeline.architecture.execution_kernel import order_wire_params
from data_pipeline.kalshi_fees import taker_fee_dollars


class SimulatedVenue:
    """Callable with the same signature as `place_limit_order`.

    Returns Kalshi's flat v2 create-order response shape, so the same fill
    parser reads both venues and neither can drift from the other.
    """

    def __init__(self, feed, max_quote_age_seconds: float = 2.0,
                 positions: Optional[Dict[str, int]] = None) -> None:
        self._feed = feed
        self._max_age = float(max_quote_age_seconds)
        self.orders_sent = 0
        self.orders_filled = 0
        # Signed net per ticker, as /portfolio/positions reports it: + YES, - NO.
        self.positions: Dict[str, int] = dict(positions or {})

    def net_position(self, ticker: str) -> int:
        """The venue's truth about what is held - the sim's /portfolio/positions."""
        return int(self.positions.get(ticker, 0))

    @staticmethod
    def _response(order_id: str, filled: int, price: Optional[float], fee_per_contract: float) -> Dict:
        body = {"order_id": order_id, "fill_count": f"{filled}.00", "remaining_count": "0.00"}
        if filled > 0 and price is not None:
            body["average_fill_price"] = f"{price:.4f}"
            body["average_fee_paid"] = f"{fee_per_contract:.6f}"
        return body

    def __call__(self, ticker: str, action: str, side: str, qty: int, price_dollars: float,
                 client_order_id: Optional[str] = None) -> Dict:
        self.orders_sent += 1
        client_order_id = client_order_id or str(uuid.uuid4())
        order_id = str(uuid.uuid4())
        # Same wire translation as the real submitters: the exchange only has a YES book, so a NO
        # order is the mirror YES order (buy NO = sell YES at 1-p). The fill is reported as a YES
        # price, and the kernel flips it back to the NO cost basis, exactly as it does live.
        wire_side, wire_price = order_wire_params(action, side, price_dollars)
        body = {
            "ticker": ticker,
            "side": wire_side,
            "count": f"{int(qty)}.00",
            "price": f"{float(wire_price):.4f}",
            "time_in_force": "immediate_or_cancel",
        }
        empty = {"client_order_id": client_order_id, "body": body,
                 "resp": self._response(order_id, 0, None, 0.0)}

        quote = self._feed.quote(ticker, max_age_seconds=self._max_age)
        if quote is None or not quote.tradable:
            return empty

        if wire_side == "bid":
            # A YES bid only executes if its limit reaches the resting ask.
            if quote.yes_ask is None or float(wire_price) < quote.yes_ask - 1e-9:
                return empty
            fill_price = float(quote.yes_ask)
            available = quote.yes_ask_size
        else:
            if quote.yes_bid is None or float(wire_price) > quote.yes_bid + 1e-9:
                return empty
            fill_price = float(quote.yes_bid)
            available = quote.yes_bid_size

        # Only the size resting at the touch is available. Beyond it the order
        # would have to walk the book, and the ticker channel does not tell us
        # what is there - so it does not fill rather than inventing depth.
        capacity = int(available) if available is not None else int(qty)
        filled = max(0, min(int(qty), capacity))
        if filled <= 0:
            return empty

        self.orders_filled += 1
        # Kalshi nets the YES leg: a bid adds, an ask subtracts. Nothing stops
        # a sell going through zero - that is the point.
        delta = filled if wire_side == "bid" else -filled
        self.positions[ticker] = self.net_position(ticker) + delta
        fee_total = taker_fee_dollars(filled, fill_price)
        return {
            "client_order_id": client_order_id,
            "body": body,
            "resp": self._response(order_id, filled, fill_price, fee_total / filled),
        }
