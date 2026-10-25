"""Polymarket markets as trading_core domain objects.

A Polymarket binary has two outcome tokens, which map 1:1 to the two outcome instruments of a
BINARY: InstrumentId("polymarket", <condition id>, "yes"|"no"). "Up" is the YES outcome of an
up/down window. Prices are dollars per share paying $1.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from data_pipeline.polymarket import PmMarket
from trading_core.domain.instruments import BinaryTerms, Instrument, InstrumentId, InstrumentKind
from trading_core.domain.market_data import Quote

VENUE = "polymarket"


def instrument_id(m: PmMarket, outcome: str = "yes") -> InstrumentId:
    return InstrumentId(VENUE, m.condition_id or m.market_id, outcome)


def instrument(m: PmMarket, outcome: str = "yes") -> Optional[Instrument]:
    """The outcome instrument of a market, or None without a settlement time."""
    if m.end_ts is None:
        return None
    strike = m.strike_lo if m.strike_lo is not None else m.strike_hi
    return Instrument(
        id=instrument_id(m, outcome), kind=InstrumentKind.BINARY, tick_size=m.tick or 0.01, lot_size=1.0,
        underlying="BTC-USD", series=m.event_slug or m.kind,
        terms=BinaryTerms(expiry=datetime.fromtimestamp(m.end_ts, tz=timezone.utc), strike=strike),
        meta={"kind": m.kind, "strike_lo": m.strike_lo, "strike_hi": m.strike_hi, "start_ts": m.start_ts,
              "slug": m.slug, "token": m.yes_token if outcome == "yes" else m.no_token})


def quote(m: PmMarket, bid: Optional[float], ask: Optional[float], ts: float,
          bid_size: Optional[float] = None, ask_size: Optional[float] = None, outcome: str = "yes") -> Quote:
    """A YES quote, or the NO quote derived from it (NO bid = 1 - YES ask)."""
    if outcome == "no":
        bid, ask = (None if ask is None else round(1.0 - ask, 6)), (None if bid is None else round(1.0 - bid, 6))
        bid_size, ask_size = ask_size, bid_size
    return Quote(instrument_id(m, outcome), float(ts), bid, ask, bid_size, ask_size)


def snapshot_row_quote(row: Dict, outcome: str = "yes") -> Optional[Quote]:
    from data_pipeline.polymarket import MARKET_FIELDS
    try:
        m = PmMarket(**{f: row.get(f) for f in MARKET_FIELDS})
    except TypeError:
        return None
    return quote(m, row.get("bid"), row.get("ask"), row.get("ts") or 0, row.get("bid_size"), row.get("ask_size"),
                 outcome)
