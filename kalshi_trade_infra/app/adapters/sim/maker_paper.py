"""Hourly paper track record for the liquidity-reward market maker (paper only, no orders).

    python -m app.adapters.sim.maker_paper hourly            # replay closed hours not yet scored
    python -m app.adapters.sim.maker_paper summary --days 7  # cumulative result per config

Each run replays every closed, archived hour of the last ``--lookback`` hours that has no result yet
(so a missed run backfills), for each config in CONFIGS, against the real reward programs from the
LIP snapshots, with positions marked at settlement where Kalshi has settled the contract. One JSON
per hour lands at ``{prefix}/v1/lip_maker_paper/date=YYYY-MM-DD/hour=HH.json.gz``. Replayed tick
files are removed from the local cache afterwards so the box's disk stays flat.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from app.adapters.sim.maker_replay import MakerFees, MakerReplay, fetch_results, load_programs
from trading_core.engine.quoting import MakerConfig

SERIES = [s for s in os.getenv("TAU_LIP_PAPER_SERIES", "KXCRYPTOLEAD15M").split(",") if s]
# Series that charge makers (fee_type quadratic_with_maker_fees); none of the crypto ones do.
MAKER_FEE_SERIES = [s for s in os.getenv("TAU_LIP_PAPER_MAKER_FEE_SERIES", "").split(",") if s]
CONFIGS: Dict[str, MakerConfig] = {
    "q100": MakerConfig(quote_size=100, max_inventory=500),
    "q1000": MakerConfig(quote_size=1000, max_inventory=1000),
}


def result_key(prefix: str, hour: datetime) -> str:
    return f"{prefix}/v1/lip_maker_paper/date={hour:%Y-%m-%d}/hour={hour:%H}.json.gz"


def _exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001 - 404 (or no access): treat as missing
        return False


def score_hour(store, s3, bucket: str, prefix: str, hour: datetime, get=None,
               configs: Optional[Dict[str, MakerConfig]] = None) -> Optional[dict]:
    """Replay one hour for every config. None when the hour has no book rows for SERIES."""
    end = hour + timedelta(hours=1)
    programs = load_programs(s3, bucket, prefix, hour, end)
    out = {"hour": hour.isoformat(), "series": SERIES, "configs": {}}
    results: Optional[Dict[str, float]] = None
    for name, cfg in (configs or CONFIGS).items():
        rep = MakerReplay(SERIES, cfg, programs, fees=MakerFees(MAKER_FEE_SERIES), tickers_from_markets=True)
        rep.run(store, hour, end)
        if not rep.last_mid:
            return None
        if results is None:
            results = fetch_results(sorted(rep.last_mid), get=get)
        out["configs"][name] = dict(rep.report(results), config=asdict(cfg))
    return out


def hourly(store, s3, bucket: str, prefix: str, now: datetime, lookback: int = 6, get=None) -> List[str]:
    """Score each closed hour in the lookback whose tick file is archived and result is missing."""
    done: List[str] = []
    last = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    for i in range(lookback - 1, -1, -1):
        hour = last - timedelta(hours=i)
        key = result_key(prefix, hour)
        if _exists(s3, bucket, key) or not _exists(s3, bucket, store.table_key("kalshi_book", hour)):
            continue
        doc = score_hour(store, s3, bucket, prefix, hour, get=get)
        _drop_cache(store, hour)
        if doc is None:
            continue
        s3.put_object(Bucket=bucket, Key=key, Body=gzip.compress(json.dumps(doc).encode()),
                      ContentType="application/json", ContentEncoding="gzip")
        done.append(key)
        print("[maker_paper] %s %s" % (hour.strftime("%Y-%m-%dT%H"), {n: c["total"] for n, c in doc["configs"].items()}),
              flush=True)
    return done


def _drop_cache(store, hour: datetime) -> None:
    if getattr(store, "local_root", None) is not None:
        return
    for table in ("kalshi_book", "kalshi_trades", "kalshi_markets"):
        d = os.path.join(store.cache_dir, os.path.dirname(store.table_key(table, hour)))
        shutil.rmtree(d, ignore_errors=True)


def summary(s3, bucket: str, prefix: str, now: datetime, days: int = 7) -> dict:
    """Cumulative rewards, trading P&L and total per config over the last ``days`` days."""
    agg: Dict[str, dict] = {}
    hours = 0
    for d in range(days - 1, -1, -1):
        day = (now - timedelta(days=d)).date()
        base = f"{prefix}/v1/lip_maker_paper/date={day:%Y-%m-%d}/"
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=base):
            for obj in page.get("Contents") or []:
                doc = json.loads(gzip.decompress(s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()))
                hours += 1
                for name, c in doc.get("configs", {}).items():
                    a = agg.setdefault(name, {"hours": 0, "rewards": 0.0, "trading_pnl": 0.0, "total": 0.0,
                                              "fills": 0, "peak_collateral": 0.0, "worst_hour": None})
                    a["hours"] += 1
                    for k in ("rewards", "trading_pnl", "total"):
                        a[k] = round(a[k] + c.get(k, 0.0), 2)
                    a["fills"] += c.get("fills", 0)
                    a["peak_collateral"] = max(a["peak_collateral"], c.get("peak_collateral", 0.0))
                    if a["worst_hour"] is None or c.get("total", 0.0) < a["worst_hour"]:
                        a["worst_hour"] = c.get("total", 0.0)
    return {"hours": hours, "configs": agg}


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["hourly", "summary"])
    ap.add_argument("--lookback", type=int, default=6)
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)
    import boto3
    from data_pipeline.tick_store import BUCKET, PREFIX, TickStore
    s3 = boto3.client("s3")
    now = datetime.now(timezone.utc)
    if a.cmd == "hourly":
        hourly(TickStore(s3=s3), s3, BUCKET, PREFIX, now, lookback=a.lookback)
    else:
        print(json.dumps(summary(s3, BUCKET, PREFIX, now, days=a.days), indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
