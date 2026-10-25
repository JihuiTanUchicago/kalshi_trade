"""Time as a dependency, so the same decision loop runs live (wall clock) and in replay."""
from __future__ import annotations

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> float:
        """Unix seconds."""
        ...


class SystemClock:
    def now(self) -> float:
        return time.time()


class FixedClock:
    """A clock a backtest (or a test) moves by hand."""

    def __init__(self, ts: float) -> None:
        self.ts = float(ts)

    def now(self) -> float:
        return self.ts

    def advance(self, seconds: float) -> None:
        self.ts += float(seconds)
