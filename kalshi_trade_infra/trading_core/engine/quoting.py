"""Passive market making on binaries: decide the quotes to rest, then make the venue match them.

    fills    = venue.take_fills()            booked into the maker's own Book first
    desired  = maker_quotes(...)             per instrument: a YES bid and a NO bid (= YES offer)
    cancels, posts = reconcile(desired, venue.open_orders())
    venue.cancel(...) / venue.post(...)

The policy only ever JOINS the touch (or improves it by one tick when the spread is wide), never
crosses it, and keeps an order that is already at the right price so it keeps its place in the
queue. It quotes a side only while that side clears ``min_edge`` against the fair value, stays
inside ``max_inventory`` (YES held minus NO held, since one of each settles to the payout), and the
contract is more than ``pull_before_close_s`` from its close, when the price jumps to 0 or 1.
``rewarded_only`` restricts it to instruments that carry a resting-liquidity reward
(pricing.depth_rewards), the reason to quote at all on a book with no edge.

No I/O: the venue (a QuotingVenue) and the book are injected; the replay simulator and a live
adapter plug in the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from trading_core.domain import ExecutionReport, Fill, Instrument, InstrumentId, OrderIntent, Portfolio, Quote, Side
from trading_core.domain.orders import RestingOrder
from trading_core.ports.book import Book
from trading_core.ports.venue import QuotingVenue

_EPS = 1e-9


@dataclass(frozen=True)
class MakerConfig:
    quote_size: float = 100.0
    max_inventory: float = 500.0         # |YES held - NO held|, contracts
    min_edge: float = 0.0                # fair - our price, per contract, on each side
    pull_before_close_s: float = 60.0
    improve_min_spread_ticks: int = 0    # 0 = only join; N >= 2 = step one tick inside a spread of N+ ticks
    rewarded_only: bool = True


@dataclass(frozen=True)
class DesiredQuote:
    instrument: InstrumentId             # the YES or the NO instrument; we always BUY it
    price: float
    qty: float


def net_yes(positions: Mapping[InstrumentId, object], yes: InstrumentId) -> float:
    """YES held minus NO held: the maker's exposure to the outcome."""
    no = replace(yes, outcome="no")
    q = 0.0
    for iid, sign in ((yes, 1.0), (no, -1.0)):
        pos = positions.get(iid)
        if pos is not None:
            q += sign * getattr(pos, "qty", 0.0)
    return q


def maker_quotes(yes: Instrument, quote: Optional[Quote], fair: Optional[float], inventory: float,
                 secs_to_close: Optional[float], cfg: MakerConfig, rewarded: bool = True) -> List[DesiredQuote]:
    """The YES bid and NO bid to rest now on one binary (``quote`` is its YES book)."""
    if quote is None or quote.bid is None or quote.ask is None or quote.ask <= quote.bid:
        return []
    if cfg.rewarded_only and not rewarded:
        return []
    if secs_to_close is not None and secs_to_close < cfg.pull_before_close_s:
        return []
    payout = getattr(yes.terms, "payout", 1.0) or 1.0
    tick = yes.tick_size
    fv = quote.mid if fair is None else fair
    spread_ticks = int(round((quote.ask - quote.bid) / tick))
    step = tick if cfg.improve_min_spread_ticks >= 2 and spread_ticks >= cfg.improve_min_spread_ticks else 0.0
    out: List[DesiredQuote] = []
    yes_px = yes.round_price(quote.bid + step)
    room = cfg.max_inventory - inventory
    if room > _EPS and fv - yes_px >= cfg.min_edge - _EPS:
        out.append(DesiredQuote(yes.id, yes_px, min(cfg.quote_size, room)))
    no_px = yes.round_price(payout - quote.ask + step)
    room = cfg.max_inventory + inventory
    if room > _EPS and (payout - fv) - no_px >= cfg.min_edge - _EPS:
        out.append(DesiredQuote(replace(yes.id, outcome="no"), no_px, min(cfg.quote_size, room)))
    return out


def reconcile(desired: Iterable[DesiredQuote], resting: Iterable[RestingOrder]) -> Tuple[List[str], List[DesiredQuote]]:
    """(order ids to cancel, quotes to post). A resting order at the desired price is kept (it
    holds its queue place); a short one is topped up with a second order rather than replaced."""
    want: Dict[Tuple[InstrumentId, float], float] = {}
    for d in desired:
        k = (d.instrument, round(d.price, 10))
        want[k] = want.get(k, 0.0) + d.qty
    have: Dict[Tuple[InstrumentId, float], float] = {}
    cancels: List[str] = []
    for o in resting:
        k = (o.instrument, round(o.price, 10))
        if o.side is not Side.BUY or k not in want or have.get(k, 0.0) >= want[k] - _EPS:
            cancels.append(o.order_id)
            continue
        have[k] = have.get(k, 0.0) + o.qty
    posts = [DesiredQuote(k[0], k[1], q - have.get(k, 0.0)) for k, q in want.items() if q - have.get(k, 0.0) > _EPS]
    return cancels, posts


@dataclass
class QuoteStep:
    now: float
    fills: List[Fill] = field(default_factory=list)
    cancels: List[str] = field(default_factory=list)
    posts: List[DesiredQuote] = field(default_factory=list)


class QuotingLoop:
    def __init__(self, venue: QuotingVenue, instruments: Mapping[InstrumentId, Instrument], cfg: MakerConfig,
                 book: Optional[Book] = None, strategy_id: str = "maker") -> None:
        # Held by reference, not copied: a replay or live session adds contracts as they list.
        # Each binary needs both its YES and NO instrument in it (fills book against either).
        self.venue, self.instruments, self.cfg = venue, instruments, cfg
        self.book = book if book is not None else Portfolio()
        self.strategy_id = strategy_id
        self._seq = 0

    def book_fills(self) -> List[Fill]:
        fills = list(self.venue.take_fills())
        for f in fills:
            intent = OrderIntent(f.instrument, f.side, f.qty, limit_price=f.price, strategy_id=self.strategy_id,
                                 reason="maker fill")
            self.book.record(ExecutionReport(intent, "filled", [f], [f.order_id] if f.order_id else []),
                             self.instruments)
        return fills

    def step(self, now: float, quotes: Mapping[InstrumentId, Quote], fair: Mapping[InstrumentId, float] = None,
             secs_to_close: Mapping[InstrumentId, float] = None, rewarded: Optional[Set[InstrumentId]] = None,
             universe: Optional[Sequence[InstrumentId]] = None) -> QuoteStep:
        """One pass over the YES instruments in ``universe`` (default: every quoted one)."""
        out = QuoteStep(now, fills=self.book_fills())
        fair, secs_to_close = fair or {}, secs_to_close or {}
        positions = self.book.open_positions()
        desired: List[DesiredQuote] = []
        for yid in (universe if universe is not None else list(quotes)):
            inst = self.instruments.get(yid)
            if inst is None:
                continue
            desired += maker_quotes(inst, quotes.get(yid), fair.get(yid), net_yes(positions, yid),
                                    secs_to_close.get(yid), self.cfg,
                                    rewarded=True if rewarded is None else yid in rewarded)
        out.cancels, out.posts = reconcile(desired, self.venue.open_orders())
        for oid in out.cancels:
            self.venue.cancel(oid)
        for d in out.posts:
            self._seq += 1
            self.venue.post(d.instrument, Side.BUY, d.price, d.qty, "%s-%d-%d" % (self.strategy_id, int(now), self._seq))
        return out
