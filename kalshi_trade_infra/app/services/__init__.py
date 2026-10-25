"""Application services: research, backtest, gatekeeper, engine, autopilot (ARCHITECTURE.md).

A service orchestrates the trading core through its ports. It never imports an adapter: the
bootstrap wiring hands it a Venue, a MarketDataFeed, FeatureProviders and repositories.
"""
