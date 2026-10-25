"""Hourly paper track record for the liquidity-reward market maker (paper only, no orders).

    python -m app.adapters.sim.maker_paper hourly            # replay closed hours not yet scored
    python -m app.adapters.sim.maker_paper summary --days 7  # cumulative result per config

Series: data_pipeline.lip_programs.REWARD_SERIES (crypto lead plus the FX and commodity 15m books).
Each run replays every closed, archived hour of the last ``--lookback`` hours that has no result yet
(so a missed run backfills; an hour scored before a config was added is scored again), for each config in CONFIGS, against the real reward programs from the
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
from data_pipeline.lip_programs import REWARD_SERIES, load_latest
from trading_core.engine.quoting import MakerConfig

SERIES = [s for s in os.getenv("TAU_LIP_PAPER_SERIES", ",".join(REWARD_SERIES)).split(",") if s]
# Series that charge makers. Unset: every series whose fee_type in the latest LIP snapshot names maker
# fees (quadratic_with_maker_fees); the crypto ones are plain quadratic, no maker fee.
MAKER_FEE_SERIES = [s for s in os.getenv("TAU_LIP_PAPER_MAKER_FEE_SERIES", "").split(",") if s]
# The inventory cap drives the outcome noise: on KXCRYPTOLEAD15M 09:15-13:00Z 10-25 (15 windows) the
# per-window total had SD $408 at a 1,000 cap, $177 at 300 and $58 at 100.
CONFIGS: Dict[str, MakerConfig] = {
    "q100": MakerConfig(quote_size=100, max_inventory=500),
    "q1000": MakerConfig(quote_size=1000, max_inventory=1000),
    "q1000_i300": MakerConfig(quote_size=1000, max_inventory=300),
    "q1000_i100": MakerConfig(quote_size=1000, max_inventory=100),
}


def result_key(prefix: str, hour: datetime) -> str:
    return f"{prefix}/v1/lip_maker_paper/date={hour:%Y-%m-%d}/hour={hour:%H}.json.gz"


def _scored_configs(s3, bucket: str, key: str) -> Optional[set]:
    """Config names already scored in the hour file at ``key``, or None when there is none."""
    try:
        doc = json.loads(gzip.decompress(s3.get_object(Bucket=bucket, Key=key)["Body"].read()))
    except Exception:  # noqa: BLE001 - missing (or unreadable): score the hour
        return None
    return set(doc.get("configs") or {})


def _exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001 - 404 (or no access): treat as missing
        return False


def maker_fee_series(s3) -> List[str]:
    if MAKER_FEE_SERIES:
        return MAKER_FEE_SERIES
    try:
        fees = (load_latest(s3) or {}).get("series_fees") or {}
    except Exception as e:  # noqa: BLE001 - no snapshot: charge nobody, as for the crypto series
        print("[maker_paper] no fee snapshot: %r" % (e,), flush=True)
        return []
    return sorted(k for k, v in fees.items() if "maker" in str((v or {}).get("fee_type") or ""))


def by_series(per_contract: Dict[str, dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for t, d in per_contract.items():
        a = out.setdefault(t.split("-")[0], {"contracts": 0, "reward": 0.0, "pnl": 0.0})
        a["contracts"] += 1
        a["reward"] = round(a["reward"] + d.get("reward", 0.0), 2)
        a["pnl"] = round(a["pnl"] + d.get("pnl", 0.0), 2)
    return out


def score_hour(store, s3, bucket: str, prefix: str, hour: datetime, get=None,
               configs: Optional[Dict[str, MakerConfig]] = None) -> Optional[dict]:
    """Replay one hour for every config. None when the hour has no book rows for SERIES."""
    end = hour + timedelta(hours=1)
    programs = load_programs(s3, bucket, prefix, hour, end)
    charged = maker_fee_series(s3)
    out = {"hour": hour.isoformat(), "series": SERIES, "maker_fee_series": charged, "configs": {}}
    results: Optional[Dict[str, float]] = None
    for name, cfg in (configs or CONFIGS).items():
        rep = MakerReplay(SERIES, cfg, programs, fees=MakerFees(charged), tickers_from_markets=True)
        rep.run(store, hour, end)
        if not rep.last_mid:
            return None
        if results is None:
            results = fetch_results(sorted(rep.last_mid), get=get)
            out["results"] = results
        r = rep.report(results)
        out["configs"][name] = dict(r, config=asdict(cfg), by_series=by_series(r["per_contract"]))
    return out


def hourly(store, s3, bucket: str, prefix: str, now: datetime, lookback: int = 6, get=None) -> List[str]:
    """Score each closed hour in the lookback whose tick file is archived and result is missing."""
    done: List[str] = []
    last = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    for i in range(lookback - 1, -1, -1):
        hour = last - timedelta(hours=i)
        key = result_key(prefix, hour)
        done_cfgs = _scored_configs(s3, bucket, key)
        if (done_cfgs is not None and set(CONFIGS) <= done_cfgs) \
                or not _exists(s3, bucket, store.table_key("kalshi_book", hour)):
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
                                              "fills": 0, "peak_collateral": 0.0, "worst_hour": None,
                                              "by_series": {}})
                    a["hours"] += 1
                    for k in ("rewards", "trading_pnl", "total"):
                        a[k] = round(a[k] + c.get(k, 0.0), 2)
                    a["fills"] += c.get("fills", 0)
                    a["peak_collateral"] = max(a["peak_collateral"], c.get("peak_collateral", 0.0))
                    if a["worst_hour"] is None or c.get("total", 0.0) < a["worst_hour"]:
                        a["worst_hour"] = c.get("total", 0.0)
                    for ser, v in (c.get("by_series") or {}).items():
                        b = a["by_series"].setdefault(ser, {"reward": 0.0, "pnl": 0.0, "total": 0.0})
                        b["reward"] = round(b["reward"] + v["reward"], 2)
                        b["pnl"] = round(b["pnl"] + v["pnl"], 2)
                        b["total"] = round(b["reward"] + b["pnl"], 2)
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
