"""DB access for the TAO (Bittensor subnet-token) research venue.

All TAO reads/writes live here (the *_repository.py pattern AGENTS.md mandates), so the
collector and the spot backtest path never inline SQL and the whole surface is testable against
tests/conftest.py's FakeCursor without a live DB. Price series go in the EXISTING spot_candles_1m
(symbol=TAO-SN{n} for subnet alpha priced in TAO, symbol=TAO-USD for the USD rate); the non-price
tokenomics/flow features + pool reserves go in tao_subnet_features. Every query is %s-parameterized.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.trading.markets import TAO_USD_SYMBOL, Market

# The feature columns carried into the spot backtest window (joined by ts, like model_features_1m).
_FEATURE_COLS = ("emission_weight", "tao_pool", "alpha_pool", "registrations", "net_stake_flow")


def netuid_of(symbol: str) -> int:
    """Parse the subnet id from a TAO-SN{n} symbol ('TAO-SN64' -> 64)."""
    tail = symbol.rsplit("SN", 1)[-1]
    return int(tail)


# -- writes (collector) --------------------------------------------------------


def upsert_spot_candle(cur, symbol: str, start_ts: int, open_: float, high: float, low: float,
                       close: float, volume: float) -> None:
    """Idempotent upsert of one 1m/aligned candle into spot_candles_1m. Used for both the subnet
    alpha series (symbol=TAO-SN{n}) and the TAO/USD rate series (symbol=TAO-USD)."""
    cur.execute(
        """INSERT INTO spot_candles_1m (symbol, start_ts, open, high, low, close, volume)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE open=VALUES(open), high=VALUES(high), low=VALUES(low),
             close=VALUES(close), volume=VALUES(volume)""",
        (symbol, int(start_ts), open_, high, low, close, volume),
    )


def upsert_subnet_features(cur, netuid: int, ts: int, emission_weight: Optional[float] = None,
                           tao_pool: Optional[float] = None, alpha_pool: Optional[float] = None,
                           registrations: Optional[int] = None, net_stake_flow: Optional[float] = None,
                           raw_json: Optional[str] = None) -> None:
    """Idempotent upsert of one subnet's non-price features at `ts` into tao_subnet_features."""
    cur.execute(
        """INSERT INTO tao_subnet_features
             (netuid, ts, emission_weight, tao_pool, alpha_pool, registrations, net_stake_flow, raw_json)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE emission_weight=VALUES(emission_weight), tao_pool=VALUES(tao_pool),
             alpha_pool=VALUES(alpha_pool), registrations=VALUES(registrations),
             net_stake_flow=VALUES(net_stake_flow), raw_json=VALUES(raw_json)""",
        (int(netuid), int(ts), emission_weight, tao_pool, alpha_pool, registrations, net_stake_flow, raw_json),
    )


# -- reads (backtest + partitions) ---------------------------------------------


def load_candles(cur, symbol: str, since_ts: int) -> List[Tuple[int, float]]:
    """(start_ts, close) for a spot symbol since `since_ts`, ascending."""
    cur.execute(
        "SELECT start_ts, close FROM spot_candles_1m WHERE symbol=%s AND start_ts >= %s ORDER BY start_ts",
        (symbol, int(since_ts)),
    )
    return [(int(r["start_ts"]), float(r["close"])) for r in cur.fetchall()]


def load_subnet_features(cur, netuid: int, since_ts: int) -> Dict[int, Dict[str, float]]:
    """{ts: {feature: value}} for a subnet since `since_ts`; NULL columns are dropped so a frame
    simply lacks a missing feature (a code strategy that reads it just gets None/KeyError-safe)."""
    cur.execute(
        "SELECT ts, emission_weight, tao_pool, alpha_pool, registrations, net_stake_flow "
        "FROM tao_subnet_features WHERE netuid=%s AND ts >= %s ORDER BY ts",
        (int(netuid), int(since_ts)),
    )
    out: Dict[int, Dict[str, float]] = {}
    for r in cur.fetchall():
        out[int(r["ts"])] = {c: float(r[c]) for c in _FEATURE_COLS if r.get(c) is not None}
    return out


def load_spot_history(cur, market: Market, since_ts: int) -> Dict[str, object]:
    """Everything build_spot_dataset needs for a spot market: the subnet alpha series (in TAO),
    the TAO/USD rate series, and the subnet features. The alpha-in-USD series is DERIVED per frame
    (alpha_tao * tao_usd), never stored."""
    return {
        "candles": load_candles(cur, market.underlying, since_ts),
        "tao_usd": load_candles(cur, TAO_USD_SYMBOL, since_ts),
        "features": load_subnet_features(cur, netuid_of(market.underlying), since_ts),
    }


def spot_candle_points(cur, market: Market, since: datetime) -> List[int]:
    """Sorted distinct candle timestamps for a spot market's alpha series since `since` - the time
    grid partitions.py snaps its Research/Validation/Holdout boundaries to (spot has no contracts
    whose open_time could anchor a boundary, so the candle grid plays that role)."""
    since_ts = int(since.replace(tzinfo=timezone.utc).timestamp()) if since.tzinfo is None else int(since.timestamp())
    return [t for t, _c in load_candles(cur, market.underlying, since_ts)]
