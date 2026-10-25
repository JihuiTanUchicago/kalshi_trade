"""Kalshi Liquidity Incentive Program (LIP): which markets pay for resting quotes, and how much.

Kalshi pays a fixed pool per market and Time Period, split by each account's share of the
resting size at (or, discounted per tick, near) the touch, sampled once a second; snapshots
without Target Size on both sides are excluded and shrink the payout. Terms: the October 14,
2026 filing (effective no earlier than 2026-10-28): Discount Factor 0.5 per tick, Time Periods of
1 to 7 days, pools up to $10,000 per business day per market, BTC / 15 min / Hourly crypto in
scope, eligible contracts posted on the Liquidity Rewards page at least 24h ahead.

The program list is public (GET /incentive_programs, no auth). Every run of the snapshot keeps
the active and upcoming liquidity programs verbatim:

  ticks/v1/lip_programs/date=YYYY-MM-DD/HHMM.json.gz   one snapshot per run
  ticks/lip_programs/latest.json.gz                    the newest snapshot (readers start here)

Each snapshot also keeps the fee terms of FEE_SERIES (GET /series/{ticker}: fee_type,
fee_multiplier), since whether a series charges makers decides the sign of a quote's edge.

Run:  python -m data_pipeline.lip_programs snapshot   (unit kalshi-lip-programs.timer, COLLECTOR box)
      python -m data_pipeline.lip_programs summary    (print the latest snapshot by series)
"""
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

BUCKET = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-568386354218-us-east-1")
PREFIX = os.getenv("TAU_TICK_PREFIX", "ticks")
LATEST_KEY = f"{PREFIX}/lip_programs/latest.json.gz"
STATUSES = ("active", "upcoming")
PAGE = 1000
# Short-dated series with liquidity pools we record books for and paper-quote (Todd 2026-10-25: crypto
# lead plus the FX and commodity 15m books, an exception to the sports/weather/crypto data rule).
REWARD_SERIES = [s for s in os.getenv("TAU_LIP_SERIES", ",".join([
    "KXCRYPTOLEAD15M",
    "KXEURUSD15M", "KXGBPUSD15M", "KXUSDJPY15M", "KXAUDUSD15M", "KXUSDCAD15M",
    "KXBRENT15M", "KXNATGAS15M", "KXCOPPER15M", "KXPLATINUM15M", "KXPALLADIUM15M",
])).split(",") if s]
FEE_SERIES = [s for s in os.getenv("TAU_LIP_FEE_SERIES", ",".join(
    ["KXBTC15M", "KXBTCD", "KXBTC", "KXETH15M", "KXETHD"] + REWARD_SERIES)).split(",") if s]
MAX_PAGES = 50


def snapshot_key(now: datetime) -> str:
    return f"{PREFIX}/v1/lip_programs/date={now:%Y-%m-%d}/{now:%H%M}.json.gz"


def fetch_programs(status: str, get: Optional[Callable] = None, kind: str = "liquidity") -> List[Dict[str, Any]]:
    """Every incentive program of one status, following next_cursor."""
    if get is None:
        from data_pipeline.common import api_get as get
    out: List[Dict[str, Any]] = []
    cursor = None
    for _ in range(MAX_PAGES):
        params: Dict[str, Any] = {"status": status, "type": kind, "limit": PAGE}
        if cursor:
            params["cursor"] = cursor
        page = get("/incentive_programs", params=params) or {}
        out.extend(page.get("incentive_programs") or [])
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return out


def _dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def series_of(p: Dict[str, Any]) -> str:
    return p.get("series_ticker") or (p.get("market_ticker") or "").split("-")[0]


def reward_usd(p: Dict[str, Any]) -> float:
    """period_reward is in centi-cents (1/10,000 of a dollar)."""
    return float(p.get("period_reward") or 0) / 10_000


def reward_per_day_usd(p: Dict[str, Any]) -> float:
    a, b = _dt(p.get("start_date")), _dt(p.get("end_date"))
    days = (b - a).total_seconds() / 86400 if a and b and b > a else 1.0
    return reward_usd(p) / max(days, 1e-9)


def summarize(programs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per series: programs, markets, total and top pool per day, target sizes, discount factors.
    Sorted by total $/day, largest first."""
    by: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"programs": 0, "markets": set(), "usd_per_day": 0.0,
                                                          "top_usd_per_day": 0.0, "targets": set(), "discounts": set()})
    for p in programs:
        s = by[series_of(p)]
        s["programs"] += 1
        s["markets"].add(p.get("market_ticker"))
        d = reward_per_day_usd(p)
        s["usd_per_day"] += d
        s["top_usd_per_day"] = max(s["top_usd_per_day"], d)
        if p.get("target_size_fp") is not None:
            s["targets"].add(float(p["target_size_fp"]))
        if p.get("discount_factor_bps") is not None:
            s["discounts"].add(int(p["discount_factor_bps"]))
    rows = []
    for name, s in by.items():
        rows.append({"series": name, "programs": s["programs"], "markets": len(s["markets"]),
                     "usd_per_day": round(s["usd_per_day"], 2), "top_usd_per_day": round(s["top_usd_per_day"], 2),
                     "target_sizes": sorted(s["targets"]), "discount_bps": sorted(s["discounts"])})
    return sorted(rows, key=lambda r: -r["usd_per_day"])


def series_fees(series: Iterable[str], get: Optional[Callable] = None) -> Dict[str, Dict[str, Any]]:
    """{series: {fee_type, fee_multiplier}} from GET /series/{ticker}; a failed series is skipped."""
    if get is None:
        from data_pipeline.common import api_get as get
    out: Dict[str, Dict[str, Any]] = {}
    for t in series:
        try:
            s = (get(f"/series/{t}", params=None) or {}).get("series") or {}
        except Exception as e:  # noqa: BLE001 - one bad series must not lose the program snapshot
            print(f"lip programs: series {t} failed: {e}", flush=True)
            continue
        out[t] = {"fee_type": s.get("fee_type"), "fee_multiplier": s.get("fee_multiplier")}
    return out


def snapshot(s3=None, get: Optional[Callable] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Fetch active + upcoming liquidity programs and write them to S3 (dated copy and latest)."""
    now = now or datetime.now(timezone.utc)
    doc: Dict[str, Any] = {"fetched_at": now.isoformat(), "programs": {}}
    for st in STATUSES:
        doc["programs"][st] = fetch_programs(st, get=get)
    doc["series_fees"] = series_fees(FEE_SERIES, get=get)
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    body = gzip.compress(json.dumps(doc, separators=(",", ":")).encode())
    for key in (snapshot_key(now), LATEST_KEY):
        s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType="application/json", ContentEncoding="gzip")
    active = doc["programs"]["active"]
    top = summarize(active)[:5]
    print("lip programs %s: active=%d upcoming=%d usd/day=%.0f top=%s" % (
        now.strftime("%Y-%m-%dT%H:%MZ"), len(active), len(doc["programs"]["upcoming"]),
        sum(reward_per_day_usd(p) for p in active), [(r["series"], r["usd_per_day"]) for r in top]), flush=True)
    return doc


def load_latest(s3=None) -> Optional[Dict[str, Any]]:
    """The newest snapshot written by snapshot(), or None if there is none yet."""
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=LATEST_KEY)
    except Exception as e:  # noqa: BLE001 - no snapshot yet
        if "NoSuchKey" in str(e) or "404" in str(e):
            return None
        raise
    return json.loads(gzip.decompress(obj["Body"].read()))


def main(argv: List[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "snapshot"
    if cmd == "snapshot":
        snapshot()
        return 0
    if cmd == "summary":
        doc = load_latest()
        if doc is None:
            print("no snapshot yet")
            return 1
        print("fetched_at", doc["fetched_at"])
        print("series_fees", json.dumps(doc.get("series_fees") or {}))
        for st in STATUSES:
            print(f"== {st}")
            for r in summarize(doc["programs"].get(st) or []):
                print(json.dumps(r))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
