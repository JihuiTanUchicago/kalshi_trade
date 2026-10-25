"""Real-data parity check for ARCHITECTURE.md step 8: replay recent research specs through both the
legacy backtest and trading_core's TradingLoop, under both fill models, and report any trade that
differs. Read-only: it loads datasets and specs from the DB and writes nothing.

Run on the web box (it needs the DB):
    python -m scripts.loop_parity --markets btc15m,eth15m --days 14 --limit 40
Prints one JSON summary. Exit code 1 when any case differs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time


def _row(t):
    return (t.ticker, t.side, t.qty, t.entry_ts, t.entry_price, t.exit_ts, t.exit_price, round(t.fees, 10), t.reason,
            t.edge)


def _specs(market: str, limit: int):
    from app import spec as specmod
    from data_pipeline.common import get_db_conn
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, spec_json FROM app_strategies WHERE market=%s ORDER BY id DESC LIMIT %s",
                        (market, limit * 4))
            rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            raw = json.loads(r["spec_json"]) if isinstance(r["spec_json"], str) else r["spec_json"]
            spec = specmod.validate(raw)
        except Exception:
            continue
        if specmod.is_code_spec(spec) or spec.get("cross") or specmod.is_pooled(spec) \
                or specmod.is_perpetual_spec(spec):
            continue
        out.append((r["id"], spec))
        if len(out) >= limit:
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default="btc15m")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args(argv)

    from app import backtest
    from app.adapters.kalshi.spec_strategy import simulate_on_loop

    summary = {"cases": 0, "legacy_trades": 0, "legacy_s": 0.0, "loop_s": 0.0, "diffs": [], "markets": {}}
    for market in [m.strip() for m in args.markets.split(",") if m.strip()]:
        t0 = time.time()
        ds = backtest.dataset(market, args.days)
        specs = _specs(market, args.limit)
        summary["markets"][market] = {"frames": len(ds.frames), "specs": len(specs),
                                      "load_s": round(time.time() - t0, 1)}
        for fill in ("next_bar", "signal_bar"):
            backtest.FILL_MODEL = fill
            for sid, spec in specs:
                t1 = time.perf_counter()
                legacy = sorted(backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1), key=_row)
                t2 = time.perf_counter()
                loop = sorted(simulate_on_loop(spec, ds, ds.start_ts, ds.end_ts + 1, fill_model=fill), key=_row)
                summary["legacy_s"] += t2 - t1
                summary["loop_s"] += time.perf_counter() - t2
                summary["cases"] += 1
                summary["legacy_trades"] += len(legacy)
                a, b = [_row(t) for t in legacy], [_row(t) for t in loop]
                if a != b:
                    i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
                    summary["diffs"].append({"market": market, "strategy_id": sid, "fill": fill,
                                             "legacy": len(a), "loop": len(b),
                                             "first": [a[i:i + 1], b[i:i + 1]]})
        summary["markets"][market]["total_s"] = round(time.time() - t0, 1)
    summary["legacy_s"], summary["loop_s"] = round(summary["legacy_s"], 2), round(summary["loop_s"], 2)
    print(json.dumps(summary, default=str))
    return 1 if summary["diffs"] else 0


if __name__ == "__main__":
    sys.exit(main())
