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
    # Coinbase spot product that prices this market's contracts (strike vs spot).
    # None = no underlying price series (e.g. sports): contracts settle on an event
    # outcome, so there is no strike/spot and the backtest trades on price/order-book
    # features alone (no moneyness/vol/z_score).
    underlying: Optional[str] = "BTC-USD"
    # True only for markets with a live feed + execution path, i.e. tradeable now.
    # Research can BACKTEST any market; the deploy engine ticks only deployable ones,
    # so adding a research-only crypto here never starts paper/live trading on it.
    deployable: bool = False
    # The instrument this market is. "binary" = a Kalshi digital-option contract (strike,
    # expiry, $0/$1 settlement - the whole spec.py/backtest.py binary path). "spot" = a
    # continuous price series (e.g. a TAO subnet alpha token) traded long/flat via
    # backtest.simulate_spot; it has no strike/expiry/settlement, so the binary feature and
    # fair-value math never runs on it. simulate() routes on this field exactly once.
    kind: str = "binary"

    @property
    def decision_seconds(self) -> int:
        return self.candle_minutes * 60

    def is_target_event(self, close_time: datetime) -> bool:
        if self.close_hour_et is None:
            return True
        ct = close_time if close_time.tzinfo else close_time.replace(tzinfo=timezone.utc)
        return ct.astimezone(NEW_YORK).hour == self.close_hour_et


MARKETS: Dict[str, Market] = {
    # Deployable: live feed + execution path exist, so the engine trades these.
    "btc15m": Market("btc15m", "KXBTC15M", "Bitcoin 15-minute", candle_minutes=1, history_days=30,
                     underlying="BTC-USD", deployable=True),
    "btc_daily": Market("btc_daily", "KXBTCD", "Bitcoin daily close, 5pm EDT", candle_minutes=60,
                        history_days=60, close_hour_et=17, underlying="BTC-USD", deployable=True),
    # Deployable crypto: same strike-ladder + spot-price model as BTC. The live engine prices
    # each from its own Coinbase product (engine.fetch_spot_series) and places orders on its
    # Kalshi series exactly like BTC - a strategy still only trades once a user deploys it.
    "eth15m": Market("eth15m", "KXETH15M", "Ethereum 15-minute", candle_minutes=1, history_days=30,
                     underlying="ETH-USD", deployable=True),
    "eth_daily": Market("eth_daily", "KXETHD", "Ethereum daily close, 5pm EDT", candle_minutes=60,
                        history_days=60, close_hour_et=17, underlying="ETH-USD", deployable=True),
    "sol_daily": Market("sol_daily", "KXSOLD", "Solana daily close, 5pm EDT", candle_minutes=60,
                        history_days=60, close_hour_et=17, underlying="SOL-USD", deployable=True),
    "xrp_daily": Market("xrp_daily", "KXXRPD", "XRP daily close, 5pm EDT", candle_minutes=60,
                        history_days=60, close_hour_et=17, underlying="XRP-USD", deployable=True),
    # Deployable SPORTS market. Kalshi's per-game NBA moneyline (series KXNBAGAME) is a binary
    # YES/NO that settles on the game result - structurally like the crypto binaries, but with NO
    # strike and NO underlying price feed (underlying=None). It trades on the contract's own
    # price/order-book features (the strike-vs-spot GBM model does not apply); the live engine
    # prices it from the Kalshi book alone (no Coinbase spot) and places orders the same way.
    # A strategy only reaches live after passing research AND proving on paper on this same feed.
    "nba_game": Market("nba_game", "KXNBAGAME", "NBA game winner (moneyline)", candle_minutes=1,
                       history_days=30, underlying=None, deployable=True),
    # Research-only SPOT markets (kind="spot", deployable=False): Bittensor subnet alpha tokens.
    # These are a continuous price series (alpha priced in TAO via the subnet's AMM pool ratio),
    # NOT a Kalshi binary - no strike, no expiry, no settlement. `underlying` is the token's own
    # row-symbol in spot_candles_1m (written by the taostats collector, NOT Coinbase/Kalshi); the
    # backtester routes them to simulate_spot. candle_minutes defaults to 60 (taostats OHLC is
    # hourly/daily, not 1-minute); drop it to 1 per market if a plan ever exposes minute data.
    # Execution is BLOCKED (on-chain AMM only, no order API, no native short) - research only.
    "tao_sn64": Market("tao_sn64", "TAO_SN64", "Bittensor SN64 (Chutes) alpha", candle_minutes=60,
                       history_days=180, underlying="TAO-SN64", deployable=False, kind="spot"),
    "tao_sn19": Market("tao_sn19", "TAO_SN19", "Bittensor SN19 (Nineteen) alpha", candle_minutes=60,
                       history_days=180, underlying="TAO-SN19", deployable=False, kind="spot"),
    "tao_sn8": Market("tao_sn8", "TAO_SN8", "Bittensor SN8 (PTN / Taoshi) alpha", candle_minutes=60,
                      history_days=180, underlying="TAO-SN8", deployable=False, kind="spot"),
    "tao_sn4": Market("tao_sn4", "TAO_SN4", "Bittensor SN4 (Targon) alpha", candle_minutes=60,
                      history_days=180, underlying="TAO-SN4", deployable=False, kind="spot"),
    "tao_sn56": Market("tao_sn56", "TAO_SN56", "Bittensor SN56 (Gradients) alpha", candle_minutes=60,
                       history_days=180, underlying="TAO-SN56", deployable=False, kind="spot"),
}

# The USD/TAO rate series (taostats Price group) every subnet alpha is denominated against, so
# alpha-in-USD = alpha-in-TAO * TAO-USD can be derived per frame without storing a third series.
TAO_USD_SYMBOL = "TAO-USD"

# A BTC price older than this cannot price a contract: no snapshot, no trade.
MAX_BTC_GAP_SECONDS = 180


def cadence_key(market_key: str) -> Tuple[int, Optional[int]]:
    """A market's decision-cadence identity: (candle_minutes, close_hour_et). Two markets can be
    paired cross-sectionally (relative value across DIFFERENT markets) only if these match - same
    decision frequency AND same close schedule, so one synchronized decision frame aligns both.
    This is what forbids pairing a 1-minute market with a daily one."""
    m = MARKETS[market_key]
    return (m.candle_minutes, m.close_hour_et)


def compatible_cadence(market_keys: Sequence[str]) -> bool:
    """True iff every market shares one decision cadence (see cadence_key) - the precondition for
    a cross-market pair to be backtested on one merged frame and ticked on one live frame."""
    return len({cadence_key(k) for k in market_keys}) <= 1

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

# Order-book / microstructure features the pipeline already collects into
# model_features_1m, keyed {feature name: (db column, description)}. They are joined
# onto each contract snapshot by (ticker, minute) in the backtester; every one is
# NULLABLE, so a frame without a feature-builder row simply lacks them and a filter
# that references one never matches (spec._passes) - it never crashes a backtest.
MICRO_FEATURES: Dict[str, Tuple[str, str]] = {
    "ob_imbalance": ("orderbook_imbalance",
                     "order-book imbalance (bid_size - ask_size)/(bid_size + ask_size), -1..1"),
    "yes_bid_size": ("yes_bid_size_fp", "resting contracts on the best YES bid"),
    "yes_ask_size": ("yes_ask_size_fp", "resting contracts on the best YES ask"),
    "trades_60s": ("trades_last_60s_count", "number of trades in the last 60 seconds"),
    "trade_vol_60s": ("trades_last_60s_volume_fp", "contracts traded in the last 60 seconds"),
    "trade_vwap_60s": ("trades_last_60s_vwap_yes", "VWAP (YES, dollars) of trades in the last 60 seconds"),
    "quote_changes_60s": ("quote_change_events_60s", "best-quote change events in the last 60 seconds"),
    "ob_mid_ret_1m": ("mid_ret_1m", "log return of the YES mid over the last 1 minute"),
    "ob_mid_ret_3m": ("mid_ret_3m", "log return of the YES mid over the last 3 minutes"),
}
# The micro features live in the same FEATURES namespace specs filter on.
FEATURES.update({name: desc for name, (_col, desc) in MICRO_FEATURES.items()})


@dataclass(frozen=True)
class Contract:
    ticker: str
    strike: float
    close_time: datetime  # tz-aware UTC
    # Which market/series this contract belongs to (e.g. "KXBTCD"). Defaulted so single-
    # contract callers (and the live engine) are unaffected; cross-contract pairing uses it
    # to tell a BTC leg from an ETH leg at the same decision frame.
    series: str = ""


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
    micro: Optional[Dict[str, float]] = None,
) -> Optional[Snapshot]:
    """Combine BTC features with one contract's quote. None = not tradable.

    `micro` is the contract's collected order-book/microstructure features (keyed by
    the MICRO_FEATURES names); None or missing values are simply skipped so a frame
    without them still trades on the core features."""
    if series_features is None or yes_ask is None or yes_bid is None:
        return None
    if not (0.0 < yes_ask < 1.0) or not (0.0 <= yes_bid < yes_ask):
        return None
    tte_min = (contract.close_time.timestamp() - ts) / 60.0
    if tte_min <= 0:
        return None
    f = dict(series_features)
    if micro:
        for k, v in micro.items():
            if v is not None:
                f[k] = float(v)
    f["tte_min"] = tte_min
    # Strike-vs-spot features only for underlying-priced markets (BTC/ETH/...). A sports
    # market has no spot, so series_features carries no "spot" and these are skipped -
    # the snapshot then trades on price/order-book features alone.
    if "spot" in f:
        vol = f["vol_60m"]
        f["moneyness"] = math.log(f["spot"] / contract.strike)
        f["z_score"] = f["moneyness"] / (vol * math.sqrt(tte_min)) if vol > 0 else 0.0
    f["yes_bid"] = yes_bid
    f["yes_ask"] = yes_ask
    f["spread"] = yes_ask - yes_bid
    f["mid"] = (yes_ask + yes_bid) / 2.0
    f["hour_et"] = float(datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(NEW_YORK).hour)
    return Snapshot(contract=contract, ts=ts, yes_bid=yes_bid, yes_ask=yes_ask, features=f)
