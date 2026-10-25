"""The venue-agnostic trading core: domain model + ports. See ARCHITECTURE.md.

Nothing in here knows what Kalshi, Coinbase, Deribit, MySQL or S3 is. A venue or data source
plugs in from the outside by implementing a port (``trading_core.ports``) in an adapter, so a new
market (Polymarket, a crypto exchange, equities) needs a new adapter and no core change.

    trading_core.domain   entities and value objects (Instrument, Order, Fill, Position, ...)
                          and pure rules on them. Imports only the stdlib.
    trading_core.ports    typing.Protocol interfaces the core needs from the outside world
                          (Venue, MarketDataFeed, FeatureProvider, Strategy, FeeModel, Clock).

``.importlinter`` enforces the direction: the core imports neither ``app`` nor
``data_pipeline`` nor any I/O library, and ``domain`` never imports ``ports``.
"""
