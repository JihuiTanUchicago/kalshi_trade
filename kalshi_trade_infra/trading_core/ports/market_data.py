"""The live (or replayed) top of book. The execution policy prices every order from this."""
from __future__ import annotations

from typing import Mapping, Optional, Protocol, Sequence, runtime_checkable

from trading_core.domain.instruments import InstrumentId
from trading_core.domain.market_data import Quote


@runtime_checkable
class MarketDataFeed(Protocol):
    def quote(self, instrument: InstrumentId) -> Optional[Quote]:
        """Freshest known quote, or None. Callers check ``Quote.age`` against their own limit."""
        ...

    def quotes(self, instruments: Sequence[InstrumentId]) -> Mapping[InstrumentId, Quote]:
        """Batch read; instruments with no quote are absent."""
        ...
