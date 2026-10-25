"""Exit rules that apply to every position whatever the strategy says (``TradingLoop.exit_rules``)."""
from __future__ import annotations

from typing import List, Mapping

from trading_core.domain import InstrumentId, OrderIntent, Quote, Side
from trading_core.ports.book import Book


def position_stop(pct: float, reason: str = "stop"):
    """Sell a position marked down ``pct`` percent or more of its cost (qty x entry x multiplier plus
    the fees this holding paid, ``Position.open_fees``), marked where it could exit now: the bid for a
    long, the ask for a short. No quote, or no bid/ask to trade against, means it cannot be closed
    now, so it is left alone.
    ``pct <= 0`` disables the rule. This is the position stop paper and live enforce
    (``engine.force_sell_if_drawn_down``) and the backtest applies."""
    def rule(book: Book, quotes: Mapping[InstrumentId, Quote], now: float) -> List[OrderIntent]:
        if pct <= 0:
            return []
        out = []
        for iid, pos in book.open_positions().items():
            q = quotes.get(iid)
            if q is None:
                continue
            long_ = pos.qty > 0
            mark = q.bid if long_ else q.ask
            qty = abs(pos.qty)
            cost = qty * pos.avg_price * pos.multiplier + pos.open_fees
            if mark is None or mark <= 0 or cost <= 0:
                continue
            if long_:
                loss = cost - qty * mark * pos.multiplier
            else:
                loss = qty * (mark - pos.avg_price) * pos.multiplier + pos.open_fees
            if 100.0 * loss / cost >= pct:
                out.append(OrderIntent(iid, Side.SELL if long_ else Side.BUY, qty, reduce_only=True, reason=reason))
        return out
    return rule
