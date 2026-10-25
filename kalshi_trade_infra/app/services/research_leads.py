"""Data-first research: a systematic scan finds measured leads before the model writes a thesis.

The proposer used to imagine a thesis and then test it; about 95% of ideas died, often the same
few mechanisms rediscovered. This scan runs first, on the RESEARCH window only, at no model cost:

  every populated feature x life band (early / late third of a contract's life) x price band
  (cheap / mid / rich) x feature tercile, buying YES or NO at the contract's FIRST quote in that
  cell and holding to settlement, net of the taker fee and the gate's 1c cost stress.

Contracts that settle together (one event: same series and close time) are one bet, so the mean
and SE are taken across events, not contracts. Thousands of cells are tested, so a lead must
survive Benjamini-Hochberg at LEAD_FDR over all of them. Each lead carries the entry filters that
reproduce it and its projected validation power, so the proposer can build on it directly and
skip what the gate could never confirm. A scan with no lead is a fact too: the simple conditional
mispricings on this market are priced, so ideas must bring information the features don't carry.

Runs split by run id into the LEADS arm (the scan's table, a named counterparty for every idea,
and projected validation power on every develop turn) and the control arm (prompts as before).
Each run logs one `leads` verdict with its arm; rsi.run_card reads it and the research watch
compares the arms. Env: APP_LEADS_SHARE (0..1 of runs in the leads arm, 0 = off).
"""
from __future__ import annotations

import heapq
import math
import os
import random
import zlib
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

# 0, not 0.5: stopped 2026-10-25 10:00Z. The leads arm developed 0 of 43 ideas against 8 of 56 in
# control (at least 35 of the 43 outside the screen arm, P < 0.01), and the prod probe found no
# surviving lead cell on any crypto market. Likely the power line and counterparty rule talked the
# developer out of every thesis. Research is judged on ideas that reach the gate.
LEADS_SHARE = min(1.0, max(0.0, float(os.getenv("APP_LEADS_SHARE", "0"))))
LEAD_FDR = 0.10
MIN_EVENTS = 30          # a cell needs this many settled events to be tested
MAX_SNAPSHOTS = 150_000  # decision frames are strided down to about this many snapshots
RESERVOIR = 3000         # values sampled per (cell, feature) to place the tercile cuts
MAX_SHOWN = 8
FEE_QTY = 10             # amortize Kalshi's per-order fee cent over a typical order

# Prices, the life clock and raw levels (non-stationary, or the price itself) are the cell's axes
# or carry no conditional signal; everything else that is populated is scanned.
_SKIP = {"yes_bid", "yes_ask", "mid", "microprice", "trade_vwap_60s", "tte_min", "spot",
         "strike_lo_f", "strike_hi_f", "obs_high_f", "obs_low_f", "obs_temp_f", "fcst_high_f",
         "fcst_low_f", "book_n"}
_PRICE_BANDS = ((0.0, 0.25, "cheap"), (0.25, 0.75, "mid"), (0.75, 1.0, "rich"))
_TERCILES = ("bottom", "middle", "top")


def in_leads_arm(run_id: int) -> bool:
    return (zlib.crc32(("leads|%s" % run_id).encode()) % 10000) / 10000.0 < LEADS_SHARE


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    i = min(len(sorted_vals) - 1, max(0, int(q * len(sorted_vals))))
    return sorted_vals[i]


def _bh(pvalues: List[float], q: float) -> List[bool]:
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    k = 0
    for rank, i in enumerate(order, start=1):
        if pvalues[i] <= rank / m * q:
            k = rank
    keep = [False] * m
    for rank, i in enumerate(order, start=1):
        keep[i] = rank <= k
    return keep


def scan(ds, fee_per, cost_stress: float, val_days: float, z_req: float) -> Dict:
    """The lead table for one research dataset. `fee_per(qty, price)` is the per-contract taker
    fee in dollars, `cost_stress` the gate's per-contract slippage in dollars, `val_days` the
    validation window's expected length and `z_req` the validation test's one-sided z.

    Streams the frames (they ascend in time) and folds each event into running per-cell sums once
    its close passes, so memory stays bounded by the open events, not the window."""
    research_days = max((ds.end_ts - ds.start_ts) / 86400.0, 1e-9)
    total = sum(len(s) for _, s in ds.frames)
    stride = max(1, total // MAX_SNAPSHOTS)
    frames = ds.frames[::stride]
    max_tte: Dict[str, float] = {}
    present: Dict[str, int] = defaultdict(int)
    n_snaps = 0
    for _, snaps in frames:
        for sn in snaps:
            n_snaps += 1
            t = sn.features.get("tte_min")
            if t is not None and t > max_tte.get(sn.contract.ticker, 0.0):
                max_tte[sn.contract.ticker] = t
            for k, v in sn.features.items():
                if v is not None and k not in _SKIP:
                    present[k] += 1
    feats = sorted(k for k, c in present.items() if n_snaps and c >= 0.3 * n_snaps)

    def cell_of(sn) -> Optional[Tuple[str, str]]:
        tk = sn.contract.ticker
        t = sn.features.get("tte_min")
        if ds.results.get(tk) not in ("yes", "no") or t is None or not max_tte.get(tk):
            return None
        mid = (sn.yes_bid + sn.yes_ask) / 2.0
        band = next((b for lo, hi, b in _PRICE_BANDS if mid < hi), "rich")
        return ("late" if t <= max_tte[tk] / 3.0 else "early"), band

    # Pass 1: tercile cuts per (life band, price band, feature), from a reservoir sample.
    rng = random.Random(0)
    values: Dict[Tuple, List[float]] = defaultdict(list)
    seen_n: Dict[Tuple, int] = defaultdict(int)
    for _, snaps in frames:
        for sn in snaps:
            c = cell_of(sn)
            if c is None:
                continue
            for f in feats:
                v = sn.features.get(f)
                if v is None or not math.isfinite(v):
                    continue
                key = c + (f,)
                seen_n[key] += 1
                vals = values[key]
                if len(vals) < RESERVOIR:
                    vals.append(v)
                else:
                    r = rng.randrange(seen_n[key])
                    if r < RESERVOIR:
                        vals[r] = v
    cuts: Dict[Tuple, Tuple[float, float]] = {}
    for key, vals in values.items():
        if len(vals) >= 3 * MIN_EVENTS:
            vals.sort()
            lo, hi = _quantile(vals, 1 / 3), _quantile(vals, 2 / 3)
            if hi > lo:
                cuts[key] = (lo, hi)
    values.clear()

    # Pass 2: each contract's FIRST quote in each (cell, feature, tercile), as a rule entering
    # when the condition turns true would pay it. Contracts that settle at the same time in the
    # same series are one event (one bet): an event's per-cell means fold into running sums.
    # sums[cell] = [events, sum yes, sum yes^2, sum no, sum no^2, sum yes price, sum no price, contracts]
    sums: Dict[Tuple, List[float]] = defaultdict(lambda: [0.0] * 8)
    open_ev: Dict[Tuple, Dict] = {}
    closing: List[Tuple[float, Tuple]] = []

    def fold(ev_key) -> None:
        for cell, (sy, sno, sa, snp, cnt) in open_ev.pop(ev_key)["cells"].items():
            acc = sums[cell]
            y, n = sy / cnt, sno / cnt
            acc[0] += 1
            acc[1] += y
            acc[2] += y * y
            acc[3] += n
            acc[4] += n * n
            acc[5] += sa / cnt
            acc[6] += snp / cnt
            acc[7] += cnt

    for ts, snaps in frames:
        while closing and closing[0][0] < ts:
            fold(heapq.heappop(closing)[1])
        for sn in snaps:
            c = cell_of(sn)
            if c is None:
                continue
            con = sn.contract
            ev_key = (con.series, con.close_time)
            ev = open_ev.get(ev_key)
            if ev is None:
                ev = open_ev[ev_key] = {"cells": {}, "seen": set()}
                heapq.heappush(closing, (con.close_time.timestamp(), ev_key))
            y = 1.0 if ds.results[con.ticker] == "yes" else 0.0
            for f in feats:
                cut = cuts.get(c + (f,))
                v = sn.features.get(f)
                if cut is None or v is None or not math.isfinite(v):
                    continue
                cell = c + (f, 0 if v <= cut[0] else (2 if v > cut[1] else 1))
                if (con.ticker, cell) in ev["seen"]:
                    continue
                ev["seen"].add((con.ticker, cell))
                ask, no_px = sn.yes_ask, 1.0 - sn.yes_bid
                yes_net = y - ask - fee_per(FEE_QTY, ask) - cost_stress
                no_net = (1.0 - y) - no_px - fee_per(FEE_QTY, no_px) - cost_stress
                acc = ev["cells"].get(cell)
                if acc is None:
                    ev["cells"][cell] = [yes_net, no_net, ask, no_px, 1]
                else:
                    acc[0] += yes_net
                    acc[1] += no_net
                    acc[2] += ask
                    acc[3] += no_px
                    acc[4] += 1
    for ev_key in list(open_ev):
        fold(ev_key)

    tests: List[Dict] = []
    for (life, band, f, terc), acc in sums.items():
        n_ev = int(acc[0])
        if n_ev < MIN_EVENTS:
            continue
        for side, s1, s2, sp in (("yes", acc[1], acc[2], acc[5]), ("no", acc[3], acc[4], acc[6])):
            mean = s1 / n_ev
            var = max(s2 - n_ev * mean * mean, 0.0) / max(n_ev - 1, 1)
            se = math.sqrt(var / n_ev) if var > 0 else 0.0
            z = mean / se if se > 0 else 0.0
            tests.append({"life": life, "band": band, "feature": f, "tercile": _TERCILES[terc],
                          "side": side, "events": n_ev, "contracts": int(acc[7]),
                          "net_c": 100 * mean, "se_c": 100 * se, "z": z, "p": _norm_sf(z),
                          "price": sp / n_ev, "cut": cuts[(life, band, f)]})
    keep = _bh([t["p"] for t in tests], LEAD_FDR) if tests else []
    leads = [t for t, k in zip(tests, keep) if k and t["net_c"] > 0]
    scale = math.sqrt(max(val_days, 0.0) / research_days)
    for t in leads:
        z_val = t["z"] * scale  # the same edge over validation's fewer events
        t["power"] = 0.5 * math.erfc(-(z_val - z_req) / math.sqrt(2.0))
        t["val_events"] = t["events"] * val_days / research_days
    leads.sort(key=lambda t: -t["z"])
    late_cut = _median(list(max_tte.values())) / 3.0 if max_tte else None
    return {"tests": len(tests), "features": len(feats), "leads": leads, "late_tte_min": late_cut,
            "research_days": research_days, "val_days": val_days}


def _median(xs: List[float]) -> float:
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def _filters(t: Dict) -> str:
    lo, hi = t["cut"]
    f = t["feature"]
    if t["tercile"] == "bottom":
        return "%s <= %.4g" % (f, lo)
    if t["tercile"] == "top":
        return "%s > %.4g" % (f, hi)
    return "%.4g < %s <= %.4g" % (lo, f, hi)


def block(result: Dict) -> str:
    """The LEADS table for the proposer prompt."""
    leads = result["leads"]
    late = result.get("late_tte_min")
    head = ("LEADS (a systematic scan of %d cells on the research window: %d populated features x early/late "
            "life x cheap/mid/rich price x feature tercile, buying YES or NO at each contract's first quote in "
            "the cell and holding to settlement, net of the taker fee AND the gate's 1c cost stress; contracts "
            "of one event count once; Benjamini-Hochberg at %.0f%% over every cell). 'late' = last third of a "
            "contract's life%s." % (result["tests"], result["features"], 100 * LEAD_FDR,
                                   " (about tte_min <= %.0f here)" % late if late else ""))
    if not leads:
        return (head + "\nNO cell survives. The single-feature conditional mispricings on this market are "
                "priced within noise after costs. Do NOT propose a one-feature threshold rule here: it is "
                "already measured dead. Propose only ideas that bring information these cells cannot see: a "
                "fitted model combining several features, a cross-market or settlement-mechanics signal, or a "
                "path/timing condition.")
    lines = []
    for i, t in enumerate(leads[:MAX_SHOWN], start=1):
        lines.append("L%d: %s life, %s price, %s -> buy %s at ~%.0fc: %d events (%d contracts), net %+.1fc "
                     "+-%.1f (z %.1f); projected validation ~%.0f events, power %.0f%%"
                     % (i, t["life"], t["band"], _filters(t), t["side"].upper(), 100 * t["price"], t["events"],
                        t["contracts"], t["net_c"], t["se_c"], t["z"], t["val_events"], 100 * t["power"]))
    more = len(leads) - MAX_SHOWN
    return (head + "\n  " + "\n  ".join(lines) + ("\n  (+%d more leads)" % more if more > 0 else "") +
            "\nA lead is a measured fact, not a mechanism. Build at least half of your hypotheses on a lead: "
            "cite its id (e.g. \"L2\") in the thesis, start from its filters, side and price band, and explain "
            "WHY it persists. Leads with power under 50% need a sharper condition or more volume, not a "
            "looser one. A refinement may only add a condition you can justify economically.")


COUNTERPARTY_RULE = ("COUNTERPARTY RULE: every hypothesis must name its counterparty in the thesis: who is on "
                     "the losing side of this trade, and why they keep losing (late retail chasing, quotes left "
                     "stale after the underlying moved, ignorance of the settlement rule, hedgers paying for "
                     "insurance). An idea with no identifiable loser is an idea the market already priced; do "
                     "not propose it.")


def power_line(p: Dict) -> str:
    """One develop-turn line from gatekeeper.validation_power: will the gate be able to see this?"""
    if not p or p.get("power") is None:
        return ""
    if p.get("mu") is None or (p.get("mu") or 0) <= 0:
        return ("PROJECTED VALIDATION: the research-fold mean net return (after the gate's 1c cost stress) is "
                "not positive, so the gate will skip it as underpowered.")
    return ("PROJECTED VALIDATION: ~%.0f validation trades at the research-fold edge of %.2f%%/trade (after the "
            "gate's 1c cost stress) gives %.0f%% power; under 20%% the gate skips it without a test. Raise power "
            "with more independent trades or a larger edge per trade, not by fitting the strongest bucket."
            % (p.get("n_val_expected") or 0, 100 * p["mu"], 100 * p["power"]))


def summary(arm: bool, result: Optional[Dict]) -> Dict:
    """The run's `leads` verdict payload (rsi.run_card reads its arm)."""
    return {"phase": "leads", "arm": "leads" if arm else "control",
            "tests": (result or {}).get("tests"), "n_leads": len((result or {}).get("leads") or [])}


def scan_dataset(ds) -> Dict:
    """scan() with the live gate's costs and validation level, for a research dataset."""
    from app import gatekeeper, partitions, stats
    from data_pipeline.kalshi_fees import taker_fee_per_contract_dollars
    research_days = max((ds.end_ts - ds.start_ts) / 86400.0, 0.0)
    val_days = research_days * partitions.VALIDATION_FRAC / partitions.RESEARCH_FRAC
    z_req = stats.norm_ppf(1.0 - gatekeeper._validation_level(stats.lord_init(gatekeeper.ALPHA)))
    return scan(ds, taker_fee_per_contract_dollars, gatekeeper.COST_STRESS_CENTS / 100.0, val_days, z_req)


def main() -> None:
    """Probe the scan on prod research windows (read-only) and write the leads to S3:

        python -m app.services.research_leads --market btc15m --market eth15m [--no-s3]
    """
    import argparse
    import gc
    import json
    import time

    ap = argparse.ArgumentParser(description="data-first lead scan probe")
    ap.add_argument("--market", action="append", required=True)
    ap.add_argument("--no-s3", action="store_true")
    a = ap.parse_args()
    from app import partitions, rsi_scout
    from data_pipeline.common import get_db_conn
    conn = get_db_conn()
    out = {}
    try:
        cur = conn.cursor()
        for market in a.market:
            t0 = time.time()
            try:
                ds = partitions.research_dataset(market, rsi_scout.research_window(cur, market))
                t1 = time.time()
                res = scan_dataset(ds)
                out[market] = {"load_s": round(t1 - t0, 1), "scan_s": round(time.time() - t1, 1),
                               "snapshots": sum(len(s) for _, s in ds.frames), "tests": res["tests"],
                               "features": res["features"], "n_leads": len(res["leads"]),
                               "block": block(res),
                               "leads": [{k: v for k, v in t.items() if k != "p"} for t in res["leads"][:20]]}
                del ds
                gc.collect()
            except Exception as e:  # noqa: BLE001 - one market's failure never stops the probe
                out[market] = {"error": repr(e)[:300]}
            print("[leads] %s %s" % (market, json.dumps({k: v for k, v in out[market].items()
                                                         if k not in ("leads", "block")})), flush=True)
    finally:
        conn.close()
    body = json.dumps(out, indent=1, default=str)
    if not a.no_s3:
        import boto3
        bucket = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-568386354218-us-east-1")
        boto3.client("s3").put_object(Bucket=bucket, Key="research-watch/dumps/leads_probe.json",
                                      Body=body.encode(), ContentType="application/json")
        print("[leads] wrote s3://%s/research-watch/dumps/leads_probe.json" % bucket, flush=True)
    else:
        print(body)


if __name__ == "__main__":
    main()
