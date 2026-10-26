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
Contract selection: ``max_touch_size`` skips a side whose queue is too deep to win a useful share,
and ``contract_loss_limit`` benches a contract whose fills cost more than its rewards pay (it then
quotes only the side that unwinds its inventory).
``rewarded_only`` restricts it to instruments that carry a resting-liquidity reward
(pricing.depth_rewards), the reason to quote at all on a book with no edge.

The rest are the levers a researched quoting policy turns against adverse selection:
``offset_ticks`` rests behind the touch, ``back_off`` moves a side to the best price that still
clears ``min_edge`` instead of dropping it, ``skew_ticks`` backs off the side that would grow the
inventory in proportion to how full it is, ``mid_band`` and ``max_secs_to_close`` choose which
contracts to quote, and ``pull_move_bp`` pulls every quote on a contract for ``pull_cooldown_s``
after the underlying moves that many basis points (``Quote.features["spot_move_bp"]``).

No I/O: the venue (a QuotingVenue) and the book are injected; the replay simulator and a live
adapter plug in the same way.
"""
from __future__ import annotations

import math
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
    # Stop quoting a contract for good once rewards earned + its trading P&L (marked at the mid)
    # fall below -contract_loss_limit: a toxic book costs more in fills than its pool pays.
    contract_loss_limit: Optional[float] = None
    # Skip a side whose touch already rests more than this: we would join the back of a deep queue,
    # earn a sliver of the pool and get filled only when the whole level is swept.
    max_touch_size: Optional[float] = None
    offset_ticks: int = 0                # rest this many ticks behind the touch on both sides
    back_off: bool = False               # a side short of min_edge rests at fair - min_edge instead
    skew_ticks: int = 0                  # at full inventory, the side adding to it rests this much further back
    mid_band: Tuple[float, float] = (0.0, 1.0)   # quote only while lo <= mid <= hi (fraction of payout)
    max_secs_to_close: Optional[float] = None    # skip contracts further than this from their close
    pull_move_bp: Optional[float] = None         # pull a contract's quotes after an underlying move this big
    pull_cooldown_s: float = 10.0


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
    if secs_to_close is not None and cfg.max_secs_to_close is not None and secs_to_close > cfg.max_secs_to_close:
        return []
    payout = getattr(yes.terms, "payout", 1.0) or 1.0
    mid = (quote.bid + quote.ask) / 2
    if not cfg.mid_band[0] * payout - _EPS <= mid <= cfg.mid_band[1] * payout + _EPS:
        return []
    tick = yes.tick_size
    fv = quote.mid if fair is None else fair
    spread_ticks = int(round((quote.ask - quote.bid) / tick))
    step = tick if cfg.improve_min_spread_ticks >= 2 and spread_ticks >= cfg.improve_min_spread_ticks else 0.0
    step -= cfg.offset_ticks * tick
    out: List[DesiredQuote] = []
    cap = cfg.max_touch_size
    yes_ok = cap is None or step > 0 or (quote.bid_size or 0.0) <= cap      # improving starts a fresh level
    no_ok = cap is None or step > 0 or (quote.ask_size or 0.0) <= cap
    lean = 0
    if cfg.skew_ticks and cfg.max_inventory > _EPS:
        lean = int(round(cfg.skew_ticks * min(1.0, abs(inventory) / cfg.max_inventory)))
    yes_px = yes.round_price(quote.bid + step - (lean * tick if inventory > 0 else 0.0))
    no_px = yes.round_price(payout - quote.ask + step - (lean * tick if inventory < 0 else 0.0))
    if cfg.back_off:
        yes_px = min(yes_px, _floor_tick(fv - cfg.min_edge, tick))
        no_px = min(no_px, _floor_tick(payout - fv - cfg.min_edge, tick))
    room = cfg.max_inventory - inventory
    if yes_ok and room > _EPS and yes_px >= tick - _EPS and fv - yes_px >= cfg.min_edge - _EPS:
        out.append(DesiredQuote(yes.id, yes_px, min(cfg.quote_size, room)))
    room = cfg.max_inventory + inventory
    if no_ok and room > _EPS and no_px >= tick - _EPS and (payout - fv) - no_px >= cfg.min_edge - _EPS:
        out.append(DesiredQuote(replace(yes.id, outcome="no"), no_px, min(cfg.quote_size, room)))
    return out


def _floor_tick(price: float, tick: float) -> float:
    return round(math.floor(price / tick + 1e-9) * tick, 10)


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
        self.stopped: Set[InstrumentId] = set()   # YES ids benched by contract_loss_limit (unwind only)
        self.pulled_until: Dict[InstrumentId, float] = {}   # YES id -> time its pull_move_bp pause ends
        self._seq = 0

    def contract_pnl(self, yid: InstrumentId, mid: Optional[float]) -> float:
        """Trading P&L on one binary (YES and NO legs, fees paid), marked at the YES mid."""
        payout = getattr(self.instruments[yid].terms, "payout", 1.0) or 1.0
        out = 0.0
        for iid, mark in ((yid, mid), (replace(yid, outcome="no"), None if mid is None else payout - mid)):
            pos = self.book.positions.get(iid)
            if pos is not None:
                out += pos.realized + pos.unrealized(mark) - pos.fees
        return out

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
             universe: Optional[Sequence[InstrumentId]] = None,
             earned: Optional[Mapping[InstrumentId, float]] = None) -> QuoteStep:
        """One pass over the YES instruments in ``universe`` (default: every quoted one).
        ``earned``: rewards accrued so far per YES id, for ``contract_loss_limit``."""
        out = QuoteStep(now, fills=self.book_fills())
        fair, secs_to_close = fair or {}, secs_to_close or {}
        positions = self.book.open_positions()
        desired: List[DesiredQuote] = []
        for yid in (universe if universe is not None else list(quotes)):
            inst = self.instruments.get(yid)
            if inst is None:
                continue
            cfg = self.cfg
            q = quotes.get(yid)
            if cfg.contract_loss_limit is not None and yid not in self.stopped:
                net = self.contract_pnl(yid, q.mid if q is not None else None) + (earned or {}).get(yid, 0.0)
                if net < -cfg.contract_loss_limit:
                    self.stopped.add(yid)
            move = (q.features.get("spot_move_bp") if q is not None else None)
            if cfg.pull_move_bp is not None and move is not None and abs(move) >= cfg.pull_move_bp:
                self.pulled_until[yid] = now + cfg.pull_cooldown_s
            if now < self.pulled_until.get(yid, float("-inf")):
                continue
            if yid in self.stopped:
                # Benched: only the side that works the inventory back to flat (max_inventory 0),
                # since walking away leaves an outright bet on the outcome.
                cfg = replace(cfg, max_inventory=0.0)
            desired += maker_quotes(inst, q, fair.get(yid), net_yes(positions, yid),
                                    secs_to_close.get(yid), cfg,
                                    rewarded=True if rewarded is None else yid in rewarded)
        out.cancels, out.posts = reconcile(desired, self.venue.open_orders())
        for oid in out.cancels:
            self.venue.cancel(oid)
        for d in out.posts:
            self._seq += 1
            self.venue.post(d.instrument, Side.BUY, d.price, d.qty, "%s-%d-%d" % (self.strategy_id, int(now), self._seq))
        return out
