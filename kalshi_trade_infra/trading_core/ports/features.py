"""A source of point-in-time features, live or historical.

Today the engine takes eight optional callables on ``app.engine.Sources`` (micro, forecasts,
odds, weather_actuals, options, ...) and the backtest joins the same data its own way. Each of
those becomes one FeatureProvider, used by both paths, so adding a data source is one adapter.
"""
from __future__ import annotations

from typing import Dict, Mapping, Protocol, Sequence, runtime_checkable

from trading_core.domain.instruments import Instrument, InstrumentId


@runtime_checkable
class FeatureProvider(Protocol):
    name: str

    def feature_names(self) -> Sequence[str]:
        """Every key ``features`` may return, for spec validation and research prompts."""
        ...

    def features(self, instruments: Sequence[Instrument], as_of: float) -> Mapping[InstrumentId, Dict[str, float]]:
        """Values known at ``as_of`` (unix seconds) and no later. Missing data is an absent key,
        never a guess: a strategy reading an absent feature must not trade on it."""
        ...
