"""A MarketDataFeed over the Polymarket recorder's latest snapshot (collector heartbeat)."""
from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional, Sequence

from app.adapters.polymarket.instruments import snapshot_row_quote
from trading_core.domain.instruments import InstrumentId
from trading_core.domain.market_data import Quote


class SnapshotFeed:
    """trading_core.ports.MarketDataFeed: both outcome quotes of every market in one snapshot."""

    def __init__(self, rows: Iterable[Dict]) -> None:
        self._quotes: Dict[InstrumentId, Quote] = {}
        for r in rows or []:
            for outcome in ("yes", "no"):
                q = snapshot_row_quote(r, outcome)
                if q is not None:
                    self._quotes[q.instrument] = q

    def quote(self, instrument: InstrumentId) -> Optional[Quote]:
        return self._quotes.get(instrument)

    def quotes(self, instruments: Sequence[InstrumentId]) -> Mapping[InstrumentId, Quote]:
        return {i: self._quotes[i] for i in instruments if i in self._quotes}
