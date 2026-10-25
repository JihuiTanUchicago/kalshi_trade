"""Kalshi markets and contracts as domain ``Instrument``s and ``Quote``s (ARCHITECTURE.md step 7).

``app.markets`` keeps its Kalshi-shaped types (Market, Contract, Snapshot) for the legacy engine
and backtest; new code takes the domain types and gets them from here. One Kalshi ticker is two
instruments, ``kalshi:<ticker>.yes`` and ``kalshi:<ticker>.no``. The book is quoted YES-only, so the
NO side is derived: NO bid = 1 - YES ask, NO ask = 1 - YES bid.
"""
from __future__ import annotations

from datetime import timezone
from typing import Optional, Tuple

from app.adapters.kalshi.convert import VENUE, instrument_id
from trading_core.domain import (BinaryTerms, Instrument, InstrumentId, InstrumentKind, PerpetualTerms,
                                 Quote)

# app.markets.Market.kind -> the domain kind. "spot" markets are TAO alpha tokens priced by taostats.
KINDS = {"binary": InstrumentKind.BINARY, "perpetual": InstrumentKind.PERPETUAL, "spot": InstrumentKind.SPOT}


def market_kind(market) -> InstrumentKind:
    try:
        return KINDS[market.kind]
    except KeyError:
        raise ValueError("unknown market kind %r for %s" % (market.kind, market.key)) from None


def binary(contract, outcome: str = "yes", market=None) -> Instrument:
    """The domain instrument for one outcome of an ``app.markets.Contract``. A strike of 0 (or
    below) is the legacy "no numeric threshold" marker (sports, events) and maps to None."""
    strike = float(contract.strike) if contract.strike and contract.strike > 0 else None
    series = contract.series or (market.series if market is not None else "")
    return Instrument(
        id=instrument_id(contract.ticker, outcome), kind=InstrumentKind.BINARY,
        underlying=market.underlying if market is not None else None, series=series,
        terms=BinaryTerms(expiry=contract.close_time.astimezone(timezone.utc), strike=strike),
    )


def perpetual(ticker: str, underlying: Optional[str] = "BTC-USD", multiplier: float = 0.0001,
              tick_size: float = 0.01) -> Instrument:
    """A Kalshi native perp (``kalshi_perps_*``). The multiplier is the exchange's
    ``contract_multiplier`` (0.0001 BTC today, asserted by kalshi_perps_trading)."""
    return Instrument(id=InstrumentId(VENUE, ticker), kind=InstrumentKind.PERPETUAL, underlying=underlying,
                      multiplier=multiplier, tick_size=tick_size, terms=PerpetualTerms())


def contract(instrument: Instrument):
    """Back to ``app.markets.Contract`` for code that still speaks it (the round trip of binary)."""
    from app.markets import Contract
    if instrument.kind is not InstrumentKind.BINARY or instrument.id.venue != VENUE:
        raise ValueError("not a Kalshi binary: %s" % instrument.id)
    strike = instrument.terms.strike
    return Contract(instrument.id.symbol, strike if strike is not None else 0.0, instrument.terms.expiry,
                    series=instrument.series)


def quotes(snapshot) -> Tuple[Quote, Quote]:
    """(YES quote, NO quote) from an ``app.markets.Snapshot``. A YES bid of 0 is "no bid", so the
    YES bid and the NO ask are None there. Both quotes carry the snapshot's features."""
    ticker, ts = snapshot.contract.ticker, float(snapshot.ts)
    yes_bid = snapshot.yes_bid if snapshot.yes_bid and snapshot.yes_bid > 0 else None
    yes_ask = snapshot.yes_ask if snapshot.yes_ask and snapshot.yes_ask < 1 else None
    no_bid = round(1.0 - yes_ask, 10) if yes_ask is not None else None
    no_ask = round(1.0 - yes_bid, 10) if yes_bid is not None else None
    features = dict(snapshot.features)
    return (Quote(instrument_id(ticker, "yes"), ts, yes_bid, yes_ask, features=features),
            Quote(instrument_id(ticker, "no"), ts, no_bid, no_ask, features=features))
