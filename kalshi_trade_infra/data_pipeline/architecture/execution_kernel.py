from typing import Callable, Dict, List, Optional, Tuple

from data_pipeline.architecture.contracts import ExecutionReport, TradeIntent
from data_pipeline.kalshi_fees import taker_fee_per_contract_dollars


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


def own_side_fill(intent, res: dict, limit: float, qty: int) -> Tuple[ExecutionReport, float, float]:
    """Parse one submitter response for an order sent at own-side ``limit`` for ``qty``.

    The submitter sent a YES-leg order (see order_wire_params), so the fill it reports is a
    YES price. Parse against the YES wire price so the "filled but unreadable price" fallback
    is in the same (YES) space, then flip a NO fill back to its own cost basis (1 - yes_fill).
    Returns (report, own-side fill price, wire price). Shared by MarketableLimitKernel and the
    Venue adapter (app/adapters/kalshi/venue.py) so neither can drift on money direction.
    """
    _, wire_price = order_wire_params(intent.action, intent.side, limit)
    report = DummyExecutionKernel(lambda *a, **k: res).execute(_RepricedIntent(intent, wire_price, qty))
    fill_px = report.fill_price_dollars
    if str(intent.side).lower() == "no" and fill_px > 0:
        fill_px = round(1.0 - fill_px, 4)
    return report, fill_px, wire_price


def child_client_order_id(base: str, attempt: int) -> str:
    """The client_order_id of the ``attempt``-th child order of one intent: ``base`` for the first
    send, ``base-1``, ``base-2``, ... for each escalating retry. Crash recovery rebuilds the same ids
    to find EVERY child on the exchange, so this is the one place the scheme is defined."""
    return base if int(attempt) == 0 else "%s-%d" % (base, int(attempt))


def reservation_price(fair: float, min_edge: float, qty: int) -> Optional[float]:
    """The most a BUY may pay per contract and still clear ``min_edge`` net of the taker fee.

    ``fair`` is the order's own-side fair value (YES fair for a YES buy, 1 - YES fair for a NO buy).
    Returns the highest whole-cent price ``p`` with ``fair - p - fee_per_contract(qty, p) >= min_edge``,
    or None when no price on the 1c..99c grid clears it. ``fair - p - fee(p)`` never increases with
    ``p`` (the fee's slope is at most 0.07 per dollar, and its cent-ceiling moves by at most 1c per 1c
    step), so scanning down from the top and taking the first price that clears is the maximum.
    """
    q = max(1, int(qty))
    for cents in range(int(round(MAX_PRICE * 100)), int(round(MIN_PRICE * 100)) - 1, -1):
        p = cents / 100.0
        if fair - p - taker_fee_per_contract_dollars(q, p) >= min_edge - 1e-9:
            return p
    return None


class MarketableLimitKernel:
    """Prices every order from the live book at the moment it is submitted.

    Kalshi's v2 order endpoint has no market order - `type: "market"` is
    rejected with "invalid price", a price is always mandatory - so crossing
    the book means sending a limit priced through the touch. That makes the
    quote the order is built from the single most important input, and the
    engine used to take it from a one-minute bar up to 75 seconds old.

    What this does that the passthrough kernel did not:

    1. Re-prices against the live book, so the limit is on the correct side.
    2. Re-checks the edge at the price actually available. Following the book
       must not become chasing it: if the ask has run past the price the
       signal was computed at, the trade is abandoned, not paid up for.
    3. Escalates through the book on an exit that will not fully fill. An
       unfilled entry costs nothing - you simply do not trade. An unfilled or
       part-filled exit is how 27 contracts were carried into settlement for
       -$9.46, so an exit keeps crossing (one tick further each retry) and
       keeps taking the remainder until it is flat or out of attempts.

    Microstructure controls for thin prediction-market books (all opt-in, each
    defaulting to OFF so behaviour is unchanged until a knob is set; every one
    can only make the order SMALLER or abandon it, never larger or more
    aggressive, and none of them can ever block an exit):

    * ``max_book_fraction`` - cap each child order to this fraction of the size
      resting at the touch, so a single taker cannot walk a thin book up
      against itself. Impact follows a square-root law that is ~independent of
      slicing "so long as the participation rate is not too large" (Bouchaud
      et al.; TSE 2025, arXiv:2502.16246), and the effective impact coefficient
      grows as depth shrinks - exactly the regime a cap guards. An exit's child
      is floored at 1 so a participation cap can never trap a position.
    * ``max_entry_spread`` - abandon a (non-urgent) ENTRY when the touch spread
      is wider than this. A wide touch is an illiquid/uncertain book and the
      entry cost is ~ taker fee + half the spread; a missed entry costs nothing.
      Exits never check it - they must get out regardless of spread.
    * reservation price - when the caller puts the entry's own-side ``fair``
      value (and optionally ``min_edge``) on ``intent.metadata``, every BUY limit
      is capped at the highest price whose edge still clears ``min_edge`` net of
      the taker fee, and the entry is abandoned when the live ask is already past
      it. The decision gate checked the net edge at the decision price; this
      re-checks it at the price actually paid, so slippage, cross ticks and retry
      escalation can never turn an edge-positive signal into a fee-negative fill.
      Absent ``fair``, behaviour is unchanged. Never applies to a sell.
    * ``max_order_notional`` - hard per-order notional backstop on BUYS only,
      enforced in the execution path as defence-in-depth behind the engine's
      own sizing. It rejects (loudly) rather than silently resizing, because a
      breach here means a caller mis-sized. It never applies to a sell, so it
      can never block an exit.
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
        max_book_fraction: Optional[float] = None,
        max_entry_spread: Optional[float] = None,
        max_order_notional: Optional[float] = None,
    ) -> None:
        self._submitter = submitter
        self._feed = feed
        self.entry_cross_ticks = int(entry_cross_ticks)
        self.exit_cross_ticks = int(exit_cross_ticks)
        self.max_entry_slippage = float(max_entry_slippage)
        self.max_attempts = max(1, int(max_attempts))
        self.max_quote_age_seconds = float(max_quote_age_seconds)
        self.max_book_fraction = None if max_book_fraction is None else float(max_book_fraction)
        self.max_entry_spread = None if max_entry_spread is None else float(max_entry_spread)
        self.max_order_notional = None if max_order_notional is None else float(max_order_notional)

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
            raw_json={"rejected_by": "MarketableLimitKernel", "status": status, **detail},
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

    @staticmethod
    def _touch_size(intent, quote) -> Optional[float]:
        """Contracts resting at the touch level this order would consume. A buy
        lifts an ask; a sell hits a bid; a NO order is the YES mirror (buy NO =
        sell YES, hits the YES bid; sell NO = buy YES, lifts the YES ask)."""
        buying = str(intent.action).lower() == "buy"
        if str(intent.side).lower() == "no":
            return quote.yes_bid_size if buying else quote.yes_ask_size
        return quote.yes_ask_size if buying else quote.yes_bid_size

    def _child_qty(self, intent, quote, remaining: int) -> int:
        """How many of the ``remaining`` contracts to send this attempt. With no
        participation cap, the whole remainder (unchanged behaviour). With a cap,
        at most ``max_book_fraction`` of the resting touch size - but an exit is
        floored at 1 so the cap can never trap a position, and unknown depth is
        never capped (you cannot size to depth you cannot see)."""
        if self.max_book_fraction is None:
            return remaining
        size = self._touch_size(intent, quote)
        if size is None or size <= 0:
            return remaining
        cap = int(size * self.max_book_fraction)
        if str(intent.action).lower() == "sell":
            cap = max(1, cap)
        return max(0, min(remaining, cap))

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
        buying = str(intent.action).lower() == "buy"
        # Durable, idempotent client_order_id (EXECUTION_RISK_HARDENING P0-1): when the caller
        # persisted an intent and threaded its id in via intent.metadata, every child order this
        # kernel sends carries a deterministic id derived from it (base, base-1, base-2, ... one per
        # escalating attempt), so a replay of the *same* intent is deduped by Kalshi's own
        # client_order_id uniqueness. Absent (legacy/sim callers), the submitter mints its own uuid
        # exactly as before — the extra kwarg is only ever passed when a base is present, so a
        # submitter that does not accept it is never called with it.
        meta = getattr(intent, "metadata", None) or {}
        coid_base = meta.get("client_order_id")
        # Own-side fair value + required net edge for the reservation-price cap (BUY only; see the
        # class docstring). Absent fair => no cap, exactly the old behaviour.
        fair = None if meta.get("fair") is None else float(meta["fair"])
        min_edge = float(meta.get("min_edge") or 0.0)
        # Transaction-cost-analysis context carried on every report (app/tca.py reads it back from
        # the order intent): the price the decision was made at and, for an entry, the fair value
        # and required edge, so realized slippage and edge capture are measurable per fill.
        tca: Dict = {"decision_price": float(intent.limit_price_dollars)}
        if fair is not None:
            tca.update(fair=fair, min_edge=min_edge)

        def reject(status: str, detail: Dict) -> ExecutionReport:
            return self._rejected(status, {**detail, **tca})
        attempts: List[Dict] = []
        remaining = int(intent.qty_contracts)
        filled_total = 0
        weighted_px = 0.0  # sum of own-side fill price * qty, for a size-weighted average
        fee_total = 0.0
        last = None  # last child that filled - its ids/status represent the order

        def _finish() -> ExecutionReport:
            # Any partial progress is kept and reported: a sell that got some of
            # the position out must never look like a total miss. Fail safe -
            # report exactly what Kalshi confirmed, never the requested size.
            if filled_total <= 0:
                return reject("unfilled", {"ticker": intent.ticker, "attempts": attempts})
            avg_px = round(weighted_px / filled_total, 4)
            status = "filled" if filled_total >= int(intent.qty_contracts) else "partially_filled"
            raw = dict((last.raw_json or {}) if last else {})
            raw["attempts"] = attempts
            raw.update(tca)
            return ExecutionReport(
                accepted=True,
                status=status,
                fill_price_dollars=avg_px,
                fill_qty_contracts=filled_total,
                external_order_id=last.external_order_id if last else None,
                client_order_id=last.client_order_id if last else None,
                fee_dollars=round(fee_total, 6),
                raw_json=raw,
            )

        for attempt in range(self.max_attempts):
            quote = self._feed.quote(intent.ticker, max_age_seconds=self.max_quote_age_seconds)
            if quote is None or not quote.tradable:
                attempts.append({"attempt": attempt, "outcome": "no_quote"})
                if filled_total > 0:
                    break  # keep what filled; no fresh quote to price the rest
                return reject("no_quote", {"ticker": intent.ticker, "attempts": attempts})

            # Entry-only spread guard: a wide touch is an illiquid/uncertain book
            # and entry cost is ~ taker fee + half the spread. A missed entry
            # costs nothing; an exit must get out, so it never checks this.
            if (
                buying
                and self.max_entry_spread is not None
                and quote.spread is not None
                and quote.spread > self.max_entry_spread + 1e-9
            ):
                detail = {
                    "attempt": attempt,
                    "outcome": "spread_too_wide",
                    "spread": quote.spread,
                    "max_entry_spread": self.max_entry_spread,
                }
                attempts.append(detail)
                return reject("spread_too_wide", {"ticker": intent.ticker, "attempts": attempts})

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
                if filled_total > 0:
                    break
                return reject(
                    "edge_gone",
                    {
                        "ticker": intent.ticker,
                        "live_ask": quote.yes_ask,
                        "signal_price": float(intent.limit_price_dollars),
                        "max_entry_slippage": self.max_entry_slippage,
                        "attempts": attempts,
                    },
                )

            child = self._child_qty(intent, quote, remaining)
            if child < 1:
                # Only a BUY lands here (a sell's child is floored at 1): the
                # participation cap left no room on this thin touch. A missed
                # entry costs nothing, so stop rather than chase a deeper level.
                attempts.append(
                    {
                        "attempt": attempt,
                        "outcome": "participation_capped",
                        "touch_size": self._touch_size(intent, quote),
                        "remaining": remaining,
                    }
                )
                return reject(
                    "participation_capped",
                    {"ticker": intent.ticker, "max_book_fraction": self.max_book_fraction, "attempts": attempts},
                )

            if buying and fair is not None:
                # Re-check the edge at the price actually available, net of the fee for the child
                # actually sent (a smaller child amortizes the fee's cent-ceiling over fewer
                # contracts, so it can only lower the cap). Cap the limit there, so even a
                # level-sweeping IOC never takes a contract whose edge is below min_edge.
                cap = reservation_price(fair, min_edge, child)
                best_ask = self._own_side_book(intent, quote)[0]
                if cap is None or best_ask is None or best_ask > cap + 1e-9:
                    attempts.append(
                        {
                            "attempt": attempt,
                            "outcome": "edge_gone_net",
                            "live_ask": best_ask,
                            "reservation": cap,
                            "fair": fair,
                            "min_edge": min_edge,
                        }
                    )
                    if filled_total > 0:
                        break
                    return reject(
                        "edge_gone_net",
                        {"ticker": intent.ticker, "fair": fair, "min_edge": min_edge,
                         "reservation": cap, "live_ask": best_ask, "attempts": attempts},
                    )
                limit = min(limit, cap)

            if buying and self.max_order_notional is not None and child * limit > self.max_order_notional + 1e-9:
                attempts.append(
                    {
                        "attempt": attempt,
                        "outcome": "order_notional_exceeded",
                        "notional": round(child * limit, 4),
                        "max_order_notional": self.max_order_notional,
                    }
                )
                return reject(
                    "order_notional_exceeded", {"ticker": intent.ticker, "attempts": attempts}
                )

            if coid_base is None:
                res = self._submitter(intent.ticker, intent.action, intent.side, child, limit)
            else:
                coid = child_client_order_id(coid_base, attempt)
                res = self._submitter(intent.ticker, intent.action, intent.side, child, limit, client_order_id=coid)
            report, fill_px, wire_price = own_side_fill(intent, res, limit, child)
            f = int(report.fill_qty_contracts)
            attempts.append(
                {
                    "attempt": attempt,
                    "limit": limit,
                    "wire_price": wire_price,
                    "child_qty": child,
                    "quote_bid": quote.yes_bid,
                    "quote_ask": quote.yes_ask,
                    "quote_age_s": round(quote.age_seconds(), 3),
                    "quote_source": quote.source,
                    "filled": f,
                }
            )
            if f > 0:
                filled_total += f
                weighted_px += fill_px * f
                fee_total += float(report.fee_dollars)
                remaining -= f
                last = report
                # An entry takes what the touch gives and stops - chasing the
                # remainder up the book is exactly the paying-up this avoids.
                # An exit keeps going until flat, crossing one tick further each
                # retry, because a part-filled exit still leaves money at risk.
                if buying or remaining <= 0:
                    break
        return _finish()


class _RepricedIntent:
    """The intent as actually sent: same order, live limit price and child size.

    The fill parser falls back to the limit when a filled order comes back
    without a readable average price, so it has to see the price that was
    really on the wire, not the one the signal was computed at; and it reads
    the sent quantity to classify a partial, so a sliced child passes its own
    size, not the parent's.
    """

    def __init__(self, intent, limit_price_dollars: float, qty_contracts: Optional[int] = None) -> None:
        self._intent = intent
        self.limit_price_dollars = limit_price_dollars
        self._qty = None if qty_contracts is None else int(qty_contracts)

    @property
    def qty_contracts(self):
        return self._intent.qty_contracts if self._qty is None else self._qty

    def __getattr__(self, name):
        return getattr(self._intent, name)
