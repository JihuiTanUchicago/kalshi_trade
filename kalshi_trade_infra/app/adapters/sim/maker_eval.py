"""Score a market-making policy on the per-second tick archive (paper only; nothing here sends orders).

Each UTC hour is replayed on its own with the queue-aware MakerReplay (starting flat, from the
hour's book checkpoint), rewards paid at $1 per contract-hour so they read as a pool share; the
scoring rule is trading_core.engine.maker_policy.hour_stats.

    python -m app.adapters.sim.maker_eval grid --series KXBTCD --start 2026-10-25T00 --end 2026-10-26T00 --workers 4
    python -m app.adapters.sim.maker_eval eval --policy '{"series":"KXBTCD","fair_source":"spot","min_edge":0.02}' ...
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from app.adapters.sim.maker_replay import MakerFees, MakerReplay
from trading_core.engine.maker_policy import BASELINES, TARGET_SIZE, hour_stats, to_config, validate_policy

def hours_in(start: datetime, end: datetime) -> List[datetime]:
    h = start.replace(minute=0, second=0, microsecond=0)
    out = []
    while h < end:
        out.append(h)
        h += timedelta(hours=1)
    return out


def evaluate_hour(policy: Dict, hour: datetime, store=None, target_size: float = TARGET_SIZE) -> Dict:
    """One replayed UTC hour of ``policy``: fills, markouts and reward share, rewards per $1 pool."""
    if store is None:
        from data_pipeline.tick_store import TickStore
        store = TickStore()
    rep = MakerReplay([policy["series"]], to_config(policy), pool_per_hour=1.0, target_size=target_size,
                      fees=MakerFees(), fair_source=policy.get("fair_source", "mid"),
                      move_window_s=int(policy.get("move_window_s", 10)),
                      tickers_from_markets=policy["series"] != "KXBTC15M")
    rep.run(store, hour, hour + timedelta(hours=1))
    out = rep.report()
    row = next((r for r in out["hours"] if r["hour"] == int(hour.timestamp())), None)
    base = {"hour": int(hour.timestamp()), "fills": 0, "qty": 0.0, "reward": 0.0, "m10": 0.0, "m60": 0.0, "fees": 0.0,
            "fee_stress": 0.0}
    if row:
        base.update({k: row[k] for k in base if k in row and k != "hour"})
    # Markouts of fills near the hour's end resolve on the last mid seen; rewards land in their own hour.
    base["reward"] = round(sum(r["reward"] for r in out["hours"]), 4)
    base["max_abs_inventory"] = out["max_abs_inventory"]
    base["peak_collateral"] = out["peak_collateral"]
    base["trading_pnl"] = out["trading_pnl"]
    return base


def _eval_args(a):
    policy, hour_ts, target = a
    return evaluate_hour(policy, datetime.fromtimestamp(hour_ts, timezone.utc), target_size=target)


def evaluate(policy: Dict, hours: Sequence[datetime], workers: int = 1, target_size: float = TARGET_SIZE) -> List[Dict]:
    jobs = [(policy, int(h.timestamp()), target_size) for h in hours]
    if workers <= 1:
        return [_eval_args(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(_eval_args, jobs))


def _utc(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("grid", "eval"))
    ap.add_argument("--series", default="KXBTCD")
    ap.add_argument("--policy", default=None, help="JSON policy (eval)")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--pools", default="0,10,50", help="pool per contract-hour to score at")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    hours = hours_in(_utc(a.start), _utc(a.end))
    pools = [float(x) for x in a.pools.split(",") if x]
    if a.cmd == "eval":
        named = {"policy": validate_policy(json.loads(a.policy))}
    else:
        named = {k: validate_policy(dict(v, series=a.series)) for k, v in BASELINES.items()}
    result = {}
    for name, pol in named.items():
        rows = evaluate(pol, hours, workers=a.workers)
        result[name] = {"policy": pol, "rows": rows, "stats": {str(p): hour_stats(rows, p) for p in pools}}
        s0 = result[name]["stats"][str(pools[0])]
        print("%-20s hours %3d fills %6d markout/contract %s mean/h %s t %s breakeven pool %s" % (
            name, s0["hours"], s0["fills"], s0["markout_per_contract"], s0["mean"], s0["t"], s0["breakeven_pool"]),
            flush=True)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(result, f, indent=1)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
