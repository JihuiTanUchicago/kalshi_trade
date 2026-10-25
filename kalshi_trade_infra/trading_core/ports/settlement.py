"""Who says what an expired instrument paid. Live: the venue's settled result. Replay: the dataset."""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from trading_core.domain.instruments import Instrument


@runtime_checkable
class SettlementSource(Protocol):
    def settlement_price(self, instrument: Instrument) -> Optional[float]:
        """The final price (a binary's 0 or payout), or None while it is not known yet."""
        ...
