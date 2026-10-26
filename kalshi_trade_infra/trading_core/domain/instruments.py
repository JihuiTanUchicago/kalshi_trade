"""What can be traded, described without reference to any one venue.

An ``Instrument`` is one tradable thing on one venue. Its ``kind`` says which payoff math applies;
its ``terms`` carry the kind-specific contract terms. How the core sees today's markets:

    Kalshi BTC 15m contract, YES side   InstrumentId("kalshi", "KXBTC15M-...-T100000", "yes"), BINARY
    Polymarket outcome token            InstrumentId("polymarket", "<condition id>", "yes"),   BINARY
    Kalshi native BTC perpetual         InstrumentId("kalshi", "KXBTCPERP"),                    PERPETUAL
    Deribit BTC call                    InstrumentId("deribit", "BTC-27DEC26-100000-C"),        OPTION
    Coinbase BTC-USD / Alpaca AAPL      InstrumentId("coinbase", "BTC-USD") / ("alpaca", "AAPL"), SPOT

A binary's two outcomes are two instruments (``outcome`` "yes"/"no"), which is what Polymarket
lists natively; a venue whose wire only has a YES book (Kalshi) translates in its adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Optional, Union


class InstrumentKind(str, Enum):
    """Payoff family. Values match ``app.trading.markets.Market.kind`` so legacy configs map 1:1."""

    BINARY = "binary"        # pays ``payout`` if an event happens, else 0, at expiry
    SPOT = "spot"            # a continuously priced asset held long/flat (crypto, equity, TAO alpha)
    PERPETUAL = "perpetual"  # linear exposure to an underlying with periodic funding, no expiry
    OPTION = "option"        # vanilla call/put on an underlying
    FUTURE = "future"        # linear exposure to an underlying with an expiry


@dataclass(frozen=True, order=True)
class InstrumentId:
    """Globally unique key: venue + the venue's own symbol (+ outcome for a binary leg)."""

    venue: str
    symbol: str
    outcome: Optional[str] = None

    def __post_init__(self) -> None:
        # Hashed on every book, quote and risk lookup in a replay; computed once (it is immutable).
        object.__setattr__(self, "_hash", hash((self.venue, self.symbol, self.outcome)))

    def __hash__(self) -> int:
        return self._hash

    def __reduce__(self):
        # Rebuild through __init__ so another process recomputes the (salted) string hash.
        return (InstrumentId, (self.venue, self.symbol, self.outcome))

    def __str__(self) -> str:
        base = "%s:%s" % (self.venue, self.symbol)
        return "%s.%s" % (base, self.outcome) if self.outcome else base

    @classmethod
    def parse(cls, text: str) -> "InstrumentId":
        """Inverse of ``str()``: ``"kalshi:KXBTCD-X.yes"`` -> (kalshi, KXBTCD-X, yes)."""
        venue, sep, rest = text.partition(":")
        if not sep or not venue or not rest:
            raise ValueError("instrument id must look like venue:symbol[.outcome], got %r" % text)
        symbol, dot, outcome = rest.rpartition(".")
        if dot and outcome in ("yes", "no"):
            return cls(venue, symbol, outcome)
        return cls(venue, rest)


@dataclass(frozen=True)
class BinaryTerms:
    expiry: datetime                 # tz-aware UTC; the outcome is known at or after this
    strike: Optional[float] = None   # None for an event with no numeric threshold (sports, elections)
    payout: float = 1.0              # what one contract pays if it resolves in the money


@dataclass(frozen=True)
class OptionTerms:
    expiry: datetime
    strike: float
    right: str                       # "call" | "put"


@dataclass(frozen=True)
class PerpetualTerms:
    funding_interval_seconds: int = 3600


Terms = Union[BinaryTerms, OptionTerms, PerpetualTerms, None]


@dataclass(frozen=True)
class Instrument:
    id: InstrumentId
    kind: InstrumentKind
    quote_currency: str = "USD"
    tick_size: float = 0.01          # smallest price increment
    lot_size: float = 1.0            # smallest quantity increment
    multiplier: float = 1.0          # value of one unit of price move per contract
    underlying: Optional[str] = None  # e.g. "BTC-USD"; None for an event binary
    series: str = ""                  # venue-side family (Kalshi series, option chain root)
    terms: Terms = None
    meta: dict = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        expected = {InstrumentKind.BINARY: BinaryTerms, InstrumentKind.OPTION: OptionTerms,
                    InstrumentKind.PERPETUAL: PerpetualTerms}.get(self.kind)
        if expected is not None and not isinstance(self.terms, expected):
            raise ValueError("%s instrument %s needs %s terms" % (self.kind.value, self.id, expected.__name__))
        if self.kind is InstrumentKind.BINARY and self.id.outcome not in ("yes", "no"):
            raise ValueError("binary instrument %s needs outcome 'yes' or 'no'" % self.id)

    @property
    def expiry(self) -> Optional[datetime]:
        return getattr(self.terms, "expiry", None)

    def complement(self) -> "Instrument":
        """The other side of a binary: buying NO at p is economically selling YES at payout - p."""
        if self.kind is not InstrumentKind.BINARY:
            raise ValueError("only a binary has a complement, %s is %s" % (self.id, self.kind.value))
        other = "no" if self.id.outcome == "yes" else "yes"
        return replace(self, id=replace(self.id, outcome=other))

    def round_price(self, price: float) -> float:
        """Snap to the venue's price grid (nearest tick)."""
        ticks = round(price / self.tick_size)
        return round(ticks * self.tick_size, 10)
