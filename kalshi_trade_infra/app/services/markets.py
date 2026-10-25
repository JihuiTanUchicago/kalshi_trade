"""Which markets research may run on, and whether each has a backtest surface yet.

Shared by the web picker (app.server) and the autopilot's own market pick (app.agent), so the
research agent no longer imports the web server to ask (ARCHITECTURE.md step 4).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from app import repository as repo
from app.markets import MARKETS


def researchable_markets(cur, ready_series: Optional[Set[str]] = None) -> List[Dict]:
    """Every market the research picker offers, each with its grouping category and a
    `has_data` flag: True once a backtest surface (collected candle history) exists,
    False while the collector is still backfilling. The whole deployable universe is
    returned either way — the frontend marks the not-yet-ready ones instead of hiding
    them, so the user sees everything Tau tracks rather than a mystery subset.

    Research-only spot venues (TAO subnet alpha, kind="spot") are the one exception:
    they appear only once their taostats feed has written candles, because that feed is
    a genuine capability gate (no collector keyed = nothing to research), not a backfill
    delay. Binaries always carry a Kalshi feed, so they are never hidden.

    ``ready_series`` lets a caller pass a cached ``repo.series_with_candles`` (the web server
    shares one across requests); None reads it now."""
    spot_underlyings = [m.underlying for m in MARKETS.values() if m.kind == "spot" and m.underlying]
    live_spot = repo.spot_symbols_with_data(cur, spot_underlyings)
    if ready_series is None:
        ready_series = repo.series_with_candles(cur)
    from app import kalshi_perps_repository as perps_repo
    from app.kalshi_perps_data import Config as PerpsConfig
    from app.market_data_common import MarketDataError
    try:
        perps_enabled = PerpsConfig.from_env().enabled
    except (ValueError, MarketDataError):
        perps_enabled = False
    out: List[Dict] = []
    for m in MARKETS.values():
        if m.kind == "perpetual":
            if not perps_enabled:
                continue
            has_data = perps_repo.ready(cur, m)
        elif m.kind == "spot":
            if m.underlying not in live_spot:
                continue
            has_data = True
        else:
            has_data = m.series in ready_series and m.tick_history_short() is None
        out.append({"key": m.key, "label": m.label, "series": m.series,
                    "category": m.category, "deployable": m.deployable, "has_data": has_data,
                    **({"kind": "perpetual", "research_only": True} if m.kind == "perpetual" else {})})
    return out
