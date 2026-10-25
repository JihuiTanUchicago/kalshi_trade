"""Adapters: the outside world behind trading_core.ports (ARCHITECTURE.md).

One subpackage per venue or system (kalshi/, coinbase/, deribit/, alpaca/, sim/, db/, s3/, llm/).
An adapter may import trading_core and data_pipeline; it never imports app.services or app.web.
"""
