from typing import Callable, Dict, List, Optional, Tuple

from data_pipeline.architecture.contracts import ExecutionReport, TradeIntent


def order_wire_params(action: str, side: str, price_dollars: float) -> Tuple[str, float]:
    """Translate an order into the events/orders wire form: (``'bid'|'ask'`` on
    the YES leg, YES-leg limit price in dollars).

    The endpoint only speaks the YES leg - ``bid`` buys YES, ``ask`` sells a YES
    position (PLAN.md "Kalshi retired the order endpoint"). Buying NO *is* selling
    YES and selling NO *is* buying YES, and a NO price ``p`` is the YES price
    ``1 - p``. So the wire price is ALWAYS a YES price, and the fill Kalshi reports
    is a YES fill - callers translate a NO fill back to its own side (cost basis
    ``1 - yes_fill``). One place owns this money-direction math so the live and
    demo submitters cannot drift apart on it.
    """
    buying = str(action).lower() == "buy"
    if str(side).lower() == "no":
        return ("ask" if buying else "bid", 1.0 - float(price_dollars))
    return ("bid" if buying else "ask", float(price_dollars))


class DummyExecutionKernel:
    """
    Bypass execution kernel for MVP.
    It does not optimize routing/slicing/queue position; it forwards the
    limit order intent to the provided submitter and returns a normalized report.
    """

    def __init__(self, submitter: Callable[[str, str, str, int, float], dict]):
        self._submitter = submitter

    @staticmethod
    def _num(value, default: float = 0.0) -> float:
        """Kalshi v2 sends counts, prices and fees as fixed-point strings."""
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def execute(self, intent: TradeIntent) -> ExecutionReport:
        res = self._submitter(intent.ticker, intent.action, intent.side, intent.qty_contracts, intent.limit_price_dollars)
        resp = (res or {}).get("resp") or {}
        # The v2 create-order response is flat - there is no nested "order"
        # object, which is what this used to read. It therefore saw {} for
        # every order, defaulted the status to "submitted", and reported the
        # requested quantity at the requested price as though it had filled.
        # An immediate-or-cancel order that crosses nothing comes back with
        # fill_count "0.00" and no average_fill_price at all; believing those
        # were fills is what put phantom positions in the book on 2026-09-27.
        filled = int(self._num(resp.get("fill_count")))
        avg_px = self._num(resp.get("average_fill_price"))
        if filled > 0 and avg_px <= 0:
            # Filled but priced unreadably: the limit is the worst it can be,
            # so it is the honest fallback. Never the other way round.
            avg_px = float(intent.limit_price_dollars)
        order_id = resp.get("order_id")
        client_order_id = (res or {}).get("client_order_id")
        if filled <= 0:
            status = "unfilled"
        elif filled < int(intent.qty_contracts):
            status = "partially_filled"
        else:
            status = "filled"
        return ExecutionReport(
            accepted=filled > 0,
            status=status,
            fill_price_dollars=avg_px if filled > 0 else 0.0,
            fill_qty_contracts=filled,
            external_order_id=str(order_id) if order_id is not None else None,
            client_order_id=str(client_order_id) if client_order_id is not None else None,
            fee_dollars=self._num(resp.get("average_fee_paid")) * filled,
            raw_json=res or {},
        )


TICK = 0.01
MIN_PRICE = 0.01
MAX_PRICE = 0.99


class MarketableLimitKernel:
    """Prices every order from the live book at the moment it is submitted.

    Kalshi's v2 order endpoint has no market order - `type: "market"` is
    rejected with "invalid price", a price is always mandatory - so crossing
    the book means sending a limit priced through the touch. That makes the
    quote the order is built from the single most important input, and the
    engine used to take it from a one-minute bar up to 75 seconds old.

    Three things this does that the passthrough kernel did not:

    1. Re-prices against the live book, so the limit is on the correct side.
    2. Re-checks the edge at the price actually available. Following the book
       must not become chasing it: if the ask has run past the price the
       signal was computed at, the trade is abandoned, not paid up for.
    3. Escalates through the book on an exit that will not fill. An unfilled
       entry costs nothing - you simply do not trade. An unfilled exit is how
       27 contracts were carried into settlement for -$9.46.
    """

    def __init__(
        self,
        submitter: Callable[[str, str, str, int, float], dict],
        feed,
        entry_cross_ticks: int = 1,
        exit_cross_ticks: int = 2,
        max_entry_slippage: float = 0.02,
        max_attempts: int = 3,
        max_quote_age_seconds: float = 2.0,
    ) -> None:
        self._submitter = submitter
        self._feed = feed
        self.entry_cross_ticks = int(entry_cross_ticks)
        self.exit_cross_ticks = int(exit_cross_ticks)
        self.max_entry_slippage = float(max_entry_slippage)
        self.max_attempts = max(1, int(max_attempts))
        self.max_quote_age_seconds = float(max_quote_age_seconds)

    @staticmethod
    def _clamp(price: float) -> float:
        return max(MIN_PRICE, min(MAX_PRICE, round(price, 2)))

    @staticmethod
    def _rejected(status: str, detail: Dict) -> ExecutionReport:
        return ExecutionReport(
            accepted=False,
            status=status,
            fill_price_dollars=0.0,
            fill_qty_contracts=0,
            external_order_id=None,
            client_order_id=None,
            fee_dollars=0.0,
            raw_json={"rejected_by": "MarketableLimitKernel", **detail},
        )

    @staticmethod
    def _own_side_book(intent, quote) -> Tuple[Optional[float], Optional[float]]:
        """(best ask, best bid) in the ORDER'S OWN side price space, from the YES
        quote. NO is the mirror of the YES book: no_ask = 1 - yes_bid (cost to buy
        NO), no_bid = 1 - yes_ask (proceeds to sell NO)."""
        if str(intent.side).lower() == "no":
            ask = None if quote.yes_bid is None else 1.0 - quote.yes_bid
            bid = None if quote.yes_ask is None else 1.0 - quote.yes_ask
            return ask, bid
        return quote.yes_ask, quote.yes_bid

    def _limit_for(self, intent, quote, attempt: int) -> Optional[float]:
        """Marketable limit for this attempt, or None to abandon the order.

        In the order's own side price space (YES or NO). The submitter converts
        this to the YES-leg wire price via ``order_wire_params``.
        """
        buying = str(intent.action).lower() == "buy"
        # Each retry crosses one tick further, so a position cannot sit
        # unsellable while the market walks away from a stale price.
        cross = (self.entry_cross_ticks if buying else self.exit_cross_ticks) + attempt
        best_ask, best_bid = self._own_side_book(intent, quote)
        if buying:
            if best_ask is None:
                return None
            reference = float(intent.limit_price_dollars)
            # The signal was computed against some ask. If the live ask has
            # moved beyond tolerance, the edge that justified the trade is
            # gone - abandon rather than pay up.
            if best_ask > reference + self.max_entry_slippage:
                return None
            return self._clamp(best_ask + cross * TICK)
        if best_bid is None:
            return None
        return self._clamp(best_bid - cross * TICK)

    def execute(self, intent) -> ExecutionReport:
        attempts: List[Dict] = []
        for attempt in range(self.max_attempts):
            quote = self._feed.quote(intent.ticker, max_age_seconds=self.max_quote_age_seconds)
            if quote is None or not quote.tradable:
                attempts.append({"attempt": attempt, "outcome": "no_quote"})
                return self._rejected("no_quote", {"ticker": intent.ticker, "attempts": attempts})
            limit = self._limit_for(intent, quote, attempt)
            if limit is None:
                attempts.append(
                    {
                        "attempt": attempt,
                        "outcome": "edge_gone",
                        "live_ask": quote.yes_ask,
                        "signal_price": float(intent.limit_price_dollars),
                    }
                )
                return self._rejected(
                    "edge_gone",
                    {
                        "ticker": intent.ticker,
                        "live_ask": quote.yes_ask,
                        "signal_price": float(intent.limit_price_dollars),
                        "max_entry_slippage": self.max_entry_slippage,
                        "attempts": attempts,
                    },
                )
            res = self._submitter(
                intent.ticker, intent.action, intent.side, intent.qty_contracts, limit
            )
            # The submitter sent a YES-leg order (see order_wire_params), so the
            # fill it reports is a YES price. Parse against the YES wire price so
            # the "filled but unreadable price" fallback is in the same (YES) space,
            # then flip a NO fill back to its own cost basis (1 - yes_fill).
            _, wire_price = order_wire_params(intent.action, intent.side, limit)
            report = DummyExecutionKernel(lambda *a, **k: res).execute(
                _RepricedIntent(intent, wire_price)
            )
            fill_px = report.fill_price_dollars
            if str(intent.side).lower() == "no" and fill_px > 0:
                fill_px = round(1.0 - fill_px, 4)
            attempts.append(
                {
                    "attempt": attempt,
                    "limit": limit,
                    "wire_price": wire_price,
                    "quote_bid": quote.yes_bid,
                    "quote_ask": quote.yes_ask,
                    "quote_age_s": round(quote.age_seconds(), 3),
                    "quote_source": quote.source,
                    "filled": report.fill_qty_contracts,
                }
            )
            if report.fill_qty_contracts > 0:
                raw = dict(report.raw_json or {})
                raw["attempts"] = attempts
                return ExecutionReport(
                    accepted=True,
                    status=report.status,
                    fill_price_dollars=fill_px,
                    fill_qty_contracts=report.fill_qty_contracts,
                    external_order_id=report.external_order_id,
                    client_order_id=report.client_order_id,
                    fee_dollars=report.fee_dollars,
                    raw_json=raw,
                )
        return self._rejected("unfilled", {"ticker": intent.ticker, "attempts": attempts})


class _RepricedIntent:
    """The intent as actually sent: same order, live limit price.

    The fill parser falls back to the limit when a filled order comes back
    without a readable average price, so it has to see the price that was
    really on the wire, not the one the signal was computed at.
    """

    def __init__(self, intent, limit_price_dollars: float) -> None:
        self._intent = intent
        self.limit_price_dollars = limit_price_dollars

    def __getattr__(self, name):
        return getattr(self._intent, name)
