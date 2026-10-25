"""A QuotingVenue over replayed order books: our virtual resting orders queue behind the real ones.

Fill model (the one lip_sim calibrated on 11h of BTC ticks, 2026-10-25):
  * a new order joins the BACK of its price level: ``ahead`` = the level's size when it is posted;
  * a print at our price eats ``ahead`` first, then fills us; a print through our price (a worse
    price for the maker) fills all of us, since the taker swept our level on the way;
  * a size decrease at our level with no print at that price within 50 ms is a cancel, spread pro
    rata over the queue ahead of and behind us (deltas usually arrive ~0.2 ms BEFORE their print,
    so the print, not the delta, moves the queue when they are the same event).

Books follow Kalshi's two-ladder shape: YES bids and NO bids (a YES ask at p is a NO bid at 1 - p).
A YES order rests on the YES ladder, a NO order on the NO ladder, each in its own price terms.
Posts are post-only: one that would cross is not rested.
"""
from __future__ import annotations

import bisect
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from trading_core.domain import Fill, InstrumentId, Side
from trading_core.domain.orders import RestingOrder
from trading_core.ports.fees import FeeModel, ZeroFees
from trading_core.ports.venue import VenueCapabilities

TRADE_WINDOW_NS = 50_000_000


class _Order:
    __slots__ = ("order_id", "iid", "price", "qty", "ahead", "coid", "placed_at")

    def __init__(self, order_id, iid, price, qty, ahead, coid, placed_at):
        self.order_id, self.iid, self.price, self.qty = order_id, iid, price, qty
        self.ahead, self.coid, self.placed_at = ahead, coid, placed_at


class QueueReplayVenue:
    name = "replay"
    capabilities = VenueCapabilities(sends_real_orders=False)

    def __init__(self, venue: str = "kalshi", fees: Optional[FeeModel] = None,
                 instruments: Optional[Mapping[InstrumentId, object]] = None) -> None:
        self.venue = venue
        self.fees = fees or ZeroFees()
        self.instruments = instruments or {}
        self.books: Dict[str, Dict[str, Dict[float, float]]] = {}      # ticker -> {"yes"|"no": {price: size}}
        self._orders: Dict[str, _Order] = {}
        self._by_ladder: Dict[Tuple[str, str], Dict[str, _Order]] = {}  # (ticker, ladder) -> {order id: order}
        self._fills: List[Fill] = []
        self._trade_rts: Dict[Tuple[str, str, float], List[int]] = {}  # (ticker, ladder, price) -> print rts
        self._now_ns = 0
        self._seq = 0

    # --- replay inputs -------------------------------------------------------------------------
    def set_trade_index(self, index: Dict[Tuple[str, str, float], List[int]]) -> None:
        """Print times per (ticker, ladder, price) for the replayed span, sorted, to tag deltas."""
        self._trade_rts = index

    def reset_book(self, ticker: str) -> None:
        self.books[ticker] = {"yes": {}, "no": {}}

    def set_level(self, ticker: str, ladder: str, price: float, size: float) -> None:
        self.books.setdefault(ticker, {"yes": {}, "no": {}})[ladder][price] = size

    def on_delta(self, rt_ns: int, ticker: str, ladder: str, price: float, delta: float) -> None:
        self._now_ns = rt_ns
        lv = self.books.setdefault(ticker, {"yes": {}, "no": {}})[ladder]
        old = lv.get(price, 0.0)
        new = old + delta
        if new <= 1e-9:
            lv.pop(price, None)
            new = 0.0
        else:
            lv[price] = new
        if new >= old:
            return
        mine = self._by_ladder.get((ticker, ladder))
        if not mine:
            return
        traded = self._printed_near(ticker, ladder, price, rt_ns)
        for o in mine.values():
            if abs(o.price - price) > 1e-9:
                continue
            if not traded and old > 0:
                o.ahead = max(0.0, o.ahead - (old - new) * o.ahead / old)
            if not traded:
                o.ahead = min(o.ahead, new)

    def on_trade(self, rt_ns: int, ticker: str, taker_side: str, yes_price: float, count: float) -> None:
        """A print. taker_side "no" sold YES into the YES bids; "yes" bought YES from the NO bids."""
        self._now_ns = rt_ns
        ladder = "yes" if taker_side == "no" else "no"
        px = yes_price if ladder == "yes" else round(1.0 - yes_price, 4)
        ts = rt_ns / 1e9
        for o in list((self._by_ladder.get((ticker, ladder)) or {}).values()):
            if o.qty <= 0:
                continue
            if px < o.price - 1e-9:
                self._fill(o, o.qty, ts)
            elif abs(px - o.price) < 1e-9:
                take = count
                if o.ahead > 0:
                    d = min(o.ahead, take)
                    o.ahead -= d
                    take -= d
                if take > 0:
                    self._fill(o, min(take, o.qty), ts)

    # --- book views for the strategy and the reward scorer -------------------------------------
    def best(self, ticker: str, ladder: str) -> Optional[float]:
        lv = self.books.get(ticker, {}).get(ladder) or {}
        return max(lv) if lv else None

    def ladder(self, ticker: str, ladder: str, with_ours: bool = True) -> List[Tuple[float, float]]:
        """(price, size) best first; with_ours adds our resting size (a real order would be in the book)."""
        lv = dict(self.books.get(ticker, {}).get(ladder) or {})
        if with_ours:
            for p, q in self.ours(ticker, ladder).items():
                lv[p] = lv.get(p, 0.0) + q
        return sorted(lv.items(), reverse=True)

    def ours(self, ticker: str, ladder: str) -> Dict[float, float]:
        out: Dict[float, float] = {}
        for o in (self._by_ladder.get((ticker, ladder)) or {}).values():
            if o.qty > 0:
                out[o.price] = out.get(o.price, 0.0) + o.qty
        return out

    # --- QuotingVenue --------------------------------------------------------------------------
    def post(self, instrument: InstrumentId, side: Side, price: float, qty: float, client_order_id: str) -> str:
        self._seq += 1
        oid = "r%d" % self._seq
        if side is not Side.BUY or qty <= 0:
            return oid
        other = "no" if instrument.outcome == "yes" else "yes"
        opp = self.best(instrument.symbol, other)
        if opp is not None and price + opp >= 1.0 - 1e-9:
            return oid                                   # post-only: would cross, not rested
        ahead = (self.books.get(instrument.symbol, {}).get(instrument.outcome) or {}).get(price, 0.0)
        o = _Order(oid, instrument, price, qty, ahead, client_order_id, self._now_ns / 1e9)
        self._orders[oid] = o
        self._by_ladder.setdefault((instrument.symbol, instrument.outcome), {})[oid] = o
        return oid

    def cancel(self, order_id: str) -> None:
        o = self._orders.pop(order_id, None)
        if o is not None:
            self._by_ladder.get((o.iid.symbol, o.iid.outcome), {}).pop(order_id, None)

    def open_orders(self) -> Sequence[RestingOrder]:
        return [RestingOrder(o.order_id, o.iid, Side.BUY, o.price, o.qty, o.coid, o.placed_at)
                for o in self._orders.values() if o.qty > 0]

    def take_fills(self) -> Sequence[Fill]:
        out, self._fills = self._fills, []
        return out

    def cancel_all(self, ticker: Optional[str] = None) -> None:
        for oid in [k for k, o in self._orders.items() if ticker is None or o.iid.symbol == ticker]:
            self.cancel(oid)

    # --- internals -----------------------------------------------------------------------------
    def _printed_near(self, ticker: str, ladder: str, price: float, rt_ns: int) -> bool:
        rts = self._trade_rts.get((ticker, ladder, round(price, 4)))
        if not rts:
            return False
        j = bisect.bisect_left(rts, rt_ns)
        return any(0 <= x < len(rts) and abs(rts[x] - rt_ns) < TRADE_WINDOW_NS for x in (j - 1, j))

    def _fill(self, o: _Order, qty: float, ts: float) -> None:
        if qty <= 0:
            return
        inst = self.instruments.get(o.iid)
        fee = self.fees.fee(inst, qty, o.price, maker=True) if inst is not None else 0.0
        self._fills.append(Fill(o.iid, Side.BUY, qty, o.price, fee=fee, ts=ts, order_id=o.order_id))
        o.qty -= qty
        if o.qty <= 1e-9:
            self.cancel(o.order_id)
