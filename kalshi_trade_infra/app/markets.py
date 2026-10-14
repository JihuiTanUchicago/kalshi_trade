"""The two markets Tau trades, and the one feature snapshot both the
backtester and the live engine read.

Backtest and deployment must evaluate the identical rule on identical inputs,
or a passed backtest proves nothing about what gets deployed. So there is
exactly one place features are computed (`BtcSeries.features_at` +
`snapshot`), and both callers feed it the same shape of data: one-minute BTC
closes and a top-of-book quote for each contract.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9
    ZoneInfo = None  # type: ignore

NEW_YORK = ZoneInfo("America/New_York") if ZoneInfo else None


@dataclass(frozen=True)
class Market:
    key: str
    series: str
    label: str
    # Kalshi candle period the backtest replays, which is also how often a
    # deployment decides - deciding more often live than in the backtest
    # would trade a rule nobody tested.
    candle_minutes: int
    history_days: int
    close_hour_et: Optional[int] = None  # daily ladder: only the 5pm EDT event

    @property
    def decision_seconds(self) -> int:
        return self.candle_minutes * 60

    def is_target_event(self, close_time: datetime) -> bool:
        if self.close_hour_et is None:
            return True
        ct = close_time if close_time.tzinfo else close_time.replace(tzinfo=timezone.utc)
        return ct.astimezone(NEW_YORK).hour == self.close_hour_et


MARKETS: Dict[str, Market] = {
    "btc15m": Market("btc15m", "KXBTC15M", "Bitcoin 15-minute", candle_minutes=1, history_days=30),
    "btc_daily": Market(
        "btc_daily", "KXBTCD", "Bitcoin daily close, 5pm EDT", candle_minutes=60, history_days=60, close_hour_et=17
    ),
}

# A BTC price older than this cannot price a contract: no snapshot, no trade.
MAX_BTC_GAP_SECONDS = 180

FEATURES: Dict[str, str] = {
    "spot": "BTC price (USD)",
    "ret_1m": "BTC log return over the last 1 minute",
    "ret_5m": "BTC log return over the last 5 minutes",
    "ret_15m": "BTC log return over the last 15 minutes",
    "ret_60m": "BTC log return over the last 60 minutes",
    "vol_15m": "stdev of 1-minute BTC log returns over the last 15 minutes",
    "vol_60m": "stdev of 1-minute BTC log returns over the last 60 minutes",
    "tte_min": "minutes until the contract settles",
    "moneyness": "ln(spot / strike); positive means BTC is above the strike",
    "z_score": "moneyness / (vol_60m * sqrt(tte_min)); distance to strike in standard deviations",
    "yes_bid": "best YES bid (dollars)",
    "yes_ask": "best YES ask (dollars)",
    "spread": "yes_ask - yes_bid",
    "mid": "(yes_bid + yes_ask) / 2",
    "hour_et": "hour of day in New York (0-23)",
}


@dataclass(frozen=True)
class Contract:
    ticker: str
    strike: float
    close_time: datetime  # tz-aware UTC


@dataclass(frozen=True)
class Snapshot:
    """One contract's tradable state at one decision time."""

    contract: Contract
    ts: int  # unix seconds of the decision
    yes_bid: float
    yes_ask: float
    features: Dict[str, float]


class BtcSeries:
    """One-minute BTC closes with O(1) windowed returns and volatility.

    Prefix sums of log returns and their squares make every window a
    subtraction, so replaying 40k decision points is cheap.
    """

    def __init__(self, candles: Sequence[Tuple[int, float]]):
        rows = sorted((int(t), float(c)) for t, c in candles if c and float(c) > 0)
        self.ts: List[int] = [t for t, _ in rows]
        self.close: List[float] = [c for _, c in rows]
        self._s1 = [0.0]
        self._s2 = [0.0]
        for i in range(1, len(self.close)):
            r = math.log(self.close[i] / self.close[i - 1])
            self._s1.append(self._s1[-1] + r)
            self._s2.append(self._s2[-1] + r * r)

    def _index_at(self, ts: int) -> Optional[int]:
        """Index of the last candle that had closed by `ts`, if fresh enough."""
        # A one-minute candle starting at t closes at t+60.
        i = bisect.bisect_right(self.ts, ts - 60) - 1
        if i < 0 or ts - (self.ts[i] + 60) > MAX_BTC_GAP_SECONDS:
            return None
        return i

    def _vol(self, i: int, n: int) -> Optional[float]:
        if i < n:
            return None
        s1 = self._s1[i] - self._s1[i - n]
        s2 = self._s2[i] - self._s2[i - n]
        var = (s2 - s1 * s1 / n) / (n - 1)
        return math.sqrt(max(var, 0.0))

    def features_at(self, ts: int) -> Optional[Dict[str, float]]:
        i = self._index_at(ts)
        if i is None or i < 60:
            return None
        spot = self.close[i]
        out = {"spot": spot}
        for n in (1, 5, 15, 60):
            out["ret_%dm" % n] = math.log(spot / self.close[i - n])
        for n in (15, 60):
            out["vol_%dm" % n] = self._vol(i, n) or 0.0
        return out


def snapshot(
    series_features: Optional[Dict[str, float]],
    contract: Contract,
    ts: int,
    yes_bid: Optional[float],
    yes_ask: Optional[float],
) -> Optional[Snapshot]:
    """Combine BTC features with one contract's quote. None = not tradable."""
    if series_features is None or yes_ask is None or yes_bid is None:
        return None
    if not (0.0 < yes_ask < 1.0) or not (0.0 <= yes_bid < yes_ask):
        return None
    tte_min = (contract.close_time.timestamp() - ts) / 60.0
    if tte_min <= 0:
        return None
    f = dict(series_features)
    vol = f["vol_60m"]
    f["tte_min"] = tte_min
    f["moneyness"] = math.log(f["spot"] / contract.strike)
    f["z_score"] = f["moneyness"] / (vol * math.sqrt(tte_min)) if vol > 0 else 0.0
    f["yes_bid"] = yes_bid
    f["yes_ask"] = yes_ask
    f["spread"] = yes_ask - yes_bid
    f["mid"] = (yes_ask + yes_bid) / 2.0
    f["hour_et"] = float(datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(NEW_YORK).hour)
    return Snapshot(contract=contract, ts=ts, yes_bid=yes_bid, yes_ask=yes_ask, features=f)
