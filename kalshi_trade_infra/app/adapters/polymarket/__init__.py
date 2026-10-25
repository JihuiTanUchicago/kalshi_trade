"""Polymarket: the first venue added under the venue-agnostic architecture (ARCHITECTURE.md).

Data only, read only: Polymarket's public keyless endpoints, recorded on the collector box by
data_pipeline/polymarket.py. No account, no key, no orders, so there is no Venue adapter.

    instruments  Polymarket outcome tokens as trading_core Instruments (BINARY, yes/no) and Quotes
    feed         SnapshotFeed: a MarketDataFeed over the recorder's latest snapshot
    features     PolymarketBook (the forecast-book interface backtest and engine already call) and
                 PolymarketFeatures (a trading_core FeatureProvider): pm_p_yes / pm_edge for a
                 Kalshi BTC contract, Polymarket's probability for the same event
    store        where the data comes from: the heartbeat snapshot (live), the history day files
                 and hourly archive in S3 (research)
"""
