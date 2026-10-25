"""Several external fair-value books on one market, seen as one.

backtest.build_dataset and the engine's decision frames take one forecast book per market and
call ``book.features(ticker, strike, ts, yes_bid, yes_ask, frame_feats, close_ts=...)``. A Bitcoin
strike series has two (Deribit options, Polymarket), so they are merged here: each book adds its
own feature names, and one book failing or knowing nothing leaves the others' features intact.

Legacy glue at the app top level (not app.services: backtest imports it, and an adapter imports
backtest). It goes away with ARCHITECTURE.md step 5, when frames take a list of FeatureProviders.
"""
from __future__ import annotations

from typing import Dict, List, Optional


class CombinedBook:
    def __init__(self, books: List[object]) -> None:
        self.books = books

    def __len__(self) -> int:
        return sum(len(b) for b in self.books)

    def features(self, ticker: str, strike: float, ts: int, yes_bid: Optional[float], yes_ask: Optional[float],
                 frame_feats: Optional[Dict[str, float]] = None, close_ts: Optional[int] = None) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for b in self.books:
            out.update(b.features(ticker, strike, ts, yes_bid, yes_ask, frame_feats, close_ts=close_ts))
        return out


def combine(*books) -> Optional[object]:
    """None when no book, the book itself when one, else a CombinedBook."""
    live = [b for b in books if b is not None]
    if not live:
        return None
    return live[0] if len(live) == 1 else CombinedBook(live)
