"""Interfaces the trading core needs from the outside world. Adapters implement them.

Each port is a ``typing.Protocol``: an adapter satisfies it structurally, with no inheritance
from the core and no import of it beyond the domain types it passes around.

    Venue             submit orders, report net positions and cash (Kalshi, Alpaca, sim)
    MarketDataFeed    the live top of book per instrument (REST poll, websocket, replay)
    FeatureProvider   point-in-time features keyed by name (Deribit surface, weather, odds)
    Strategy          quotes + positions + features in, order intents out
    FeeModel          venue fee for a hypothetical fill
    Clock             "now": wall clock live, the replay cursor in a backtest
"""
from trading_core.ports.clock import Clock, FixedClock, SystemClock
from trading_core.ports.features import FeatureProvider
from trading_core.ports.fees import FeeModel, ZeroFees
from trading_core.ports.market_data import MarketDataFeed
from trading_core.ports.strategy import DecisionContext, Strategy
from trading_core.ports.venue import Venue, VenueCapabilities

__all__ = [
    "Clock", "DecisionContext", "FeatureProvider", "FeeModel", "FixedClock", "MarketDataFeed", "Strategy",
    "SystemClock", "Venue", "VenueCapabilities", "ZeroFees",
]
