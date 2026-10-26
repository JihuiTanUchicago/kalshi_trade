"""Collector for the TAO (Bittensor subnet-token) research venue (TAO_VENUE_DESIGN.md §B).

Polls the taostats v1 API on a cron and writes, via app.adapters.tao.tao_repository (no inline SQL):
  * spot_candles_1m[symbol=TAO-SN{n}] - each subnet's alpha price in TAO (the AMM pool ratio),
  * spot_candles_1m[symbol=TAO-USD]   - the TAO/USD rate (alpha-in-USD is derived, not stored),
  * tao_subnet_features               - pool reserves (drive the fill model) + emission weight,
                                         registrations and net stake flow.

AUTH (design §B.1): base https://api.taostats.io; the API key goes in the `Authorization` header
with NO `Bearer` prefix. The key is read from the env var TAOSTATS_API_KEY, mirroring how the
other collectors read credentials from env (data_pipeline/common.py). WITHOUT the key the
collector is INERT: it logs a clear message and exits 0, so deploying it before James provisions a
key is harmless - it simply does nothing until the key is set.

Research-only: this writes price/feature history. It NEVER places an order (there is no order API
for alpha tokens; execution is a separate, blocked subsystem - design §D). The spot markets it
feeds are deployable=False, so the live engine can never tick them.

NOTE: taostats does not publish its exact v1 response shapes publicly and the real endpoints
cannot be exercised without a key, so the field extraction below is defensive (`.get`, skip on
missing) and written to the documented endpoint groups. Confirm field names + OHLC granularity
against the live API (and James's plan) on first run; the parsing is isolated in the `_extract_*`
helpers so it can be corrected without touching the write path.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, List, Optional

import requests

from app.adapters.tao import tao_repository
from app.trading.markets import MARKETS, TAO_USD_SYMBOL
from data_pipeline.common import get_db_conn, utc_now

API_BASE = os.getenv("TAOSTATS_API_BASE", "https://api.taostats.io").rstrip("/")
API_KEY = os.getenv("TAOSTATS_API_KEY")
POLL_SECONDS = int(os.getenv("TAOSTATS_POLL_SECONDS", str(3600)))  # hourly, matching OHLC granularity
_TIMEOUT = 30

# Documented v1 endpoint groups (design §B.2). Paths are the best current reading of the taostats
# v1 reference; verify on first authenticated call.
PRICE_LATEST_PATH = "/api/price/latest/v1"       # Price group: TAO/USD
SUBNET_OHLC_PATH = "/api/dtao/pool/ohlc/v1"       # Subnets group: alpha OHLC (price in TAO)
SUBNET_POOL_PATH = "/api/dtao/pool/latest/v1"     # Subnet pools: tau_pool / alpha_pool reserves


def _subnet_markets() -> List:
    """The kind=="spot" TAO markets we collect, each carrying its netuid via its symbol."""
    return [m for m in MARKETS.values() if m.kind == "spot"]


class Taostats:
    """Thin taostats v1 client. Auth is the raw API key in the Authorization header (no Bearer)."""

    def __init__(self, api_key: str, base: str = API_BASE):
        self.base = base
        self.session = requests.Session()
        self.session.headers.update({"Authorization": api_key, "accept": "application/json"})

    def get(self, path: str, params: Optional[Dict] = None) -> Dict:
        r = self.session.get(self.base + path, params=params or {}, timeout=_TIMEOUT)
        if r.status_code >= 400:
            raise RuntimeError("taostats %s %s: %s" % (path, r.status_code, r.text[:200]))
        return r.json()


def _rows(payload) -> List[Dict]:
    """taostats v1 wraps lists as {"data": [...]} (sometimes {"data": {"items": [...]}}); accept a
    bare list too. Returns [] for any shape we do not recognize, so a surprise payload is skipped,
    not crashed."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
    return []


def _num(row: Dict, *keys) -> Optional[float]:
    """First present, finite numeric value among `keys` (taostats field names vary by endpoint)."""
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _ts(row: Dict) -> Optional[int]:
    """Unix seconds for a row from its timestamp/block_timestamp field."""
    from data_pipeline.common import parse_iso_to_dt
    for k in ("timestamp", "block_timestamp", "time", "date"):
        v = row.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return int(v)
        dt = parse_iso_to_dt(str(v))
        if dt:
            return int(dt.timestamp())
    return None


def _extract_ohlc(row: Dict) -> Optional[Dict]:
    ts = _ts(row)
    close = _num(row, "close", "price", "alpha_price", "c")
    if ts is None or close is None:
        return None
    o = _num(row, "open", "o") or close
    h = _num(row, "high", "h") or close
    lo = _num(row, "low", "l") or close
    vol = _num(row, "volume", "v") or 0.0
    return {"ts": ts, "open": o, "high": h, "low": lo, "close": close, "volume": vol}


def collect_once(cur, client: Taostats) -> Dict[str, int]:
    """One poll: write the TAO/USD rate, then each subnet's alpha OHLC + pool/feature snapshot."""
    stats: Dict[str, int] = {}
    now_ts = int(utc_now().timestamp())

    # TAO/USD rate -> spot_candles_1m[TAO-USD].
    try:
        rows = _rows(client.get(PRICE_LATEST_PATH, {"asset": "tao"}))
        n = 0
        for row in rows:
            rate = _num(row, "price", "price_usd", "usd")
            ts = _ts(row) or now_ts
            if rate is not None:
                tao_repository.upsert_spot_candle(cur, TAO_USD_SYMBOL, ts, rate, rate, rate, rate, 0.0)
                n += 1
        stats["tao_usd"] = n
    except Exception as e:  # noqa: BLE001 - one series failing must not abort the others
        print("taostats TAO/USD fetch failed: %s" % e)

    for m in _subnet_markets():
        netuid = tao_repository.netuid_of(m.underlying)
        # Alpha OHLC (price in TAO) -> spot_candles_1m[TAO-SN{n}].
        try:
            rows = _rows(client.get(SUBNET_OHLC_PATH, {"netuid": netuid}))
            n = 0
            for row in rows:
                c = _extract_ohlc(row)
                if c:
                    tao_repository.upsert_spot_candle(cur, m.underlying, c["ts"], c["open"],
                                                      c["high"], c["low"], c["close"], c["volume"])
                    n += 1
            stats[m.underlying] = n
        except Exception as e:  # noqa: BLE001
            print("taostats OHLC netuid=%s failed: %s" % (netuid, e))
        # Pool reserves + tokenomics -> tao_subnet_features (one snapshot at the current ts).
        try:
            pool = _rows(client.get(SUBNET_POOL_PATH, {"netuid": netuid}))
            row = pool[0] if pool else {}
            tao_pool = _num(row, "tao_in", "tao_pool", "tao_reserve", "tao")
            alpha_pool = _num(row, "alpha_in", "alpha_pool", "alpha_reserve", "alpha")
            emission = _num(row, "emission", "emission_weight", "alpha_out_emission")
            registrations = _num(row, "registrations", "registrations_count")
            net_flow = _num(row, "net_stake_flow", "tao_staked", "net_flow")
            if any(v is not None for v in (tao_pool, alpha_pool, emission, registrations, net_flow)):
                tao_repository.upsert_subnet_features(
                    cur, netuid, now_ts, emission_weight=emission, tao_pool=tao_pool,
                    alpha_pool=alpha_pool,
                    registrations=int(registrations) if registrations is not None else None,
                    net_stake_flow=net_flow, raw_json=json.dumps(row)[:60000])
                stats["%s_features" % m.underlying] = 1
        except Exception as e:  # noqa: BLE001
            print("taostats pool netuid=%s failed: %s" % (netuid, e))
    return stats


def run_loop(once: bool = False) -> None:
    if not API_KEY:
        print("taostats collector INERT: TAOSTATS_API_KEY is not set. "
              "Set it to begin collecting TAO subnet history; doing nothing until then.")
        return
    client = Taostats(API_KEY)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            print("taostats collector started (base=%s, subnets=%s)."
                  % (API_BASE, [m.underlying for m in _subnet_markets()]))
            while True:
                try:
                    stats = collect_once(cur, client)
                    print("taostats poll at=%s wrote=%s" % (utc_now().isoformat(), stats))
                except Exception as e:  # noqa: BLE001
                    print("taostats poll error: %s" % e)
                if once:
                    return
                time.sleep(POLL_SECONDS)
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="taostats TAO subnet collector (research-only)")
    ap.add_argument("--once", action="store_true", help="poll once and exit")
    args = ap.parse_args()
    run_loop(once=args.once)


if __name__ == "__main__":
    main()
