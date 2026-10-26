"""Research RSI, part 3: a free scan of every market for measured mispricing, so research goes where
the data says the money is before a single model token is spent.

For each researchable binary market it loads the RESEARCH window only (the market's frozen partition,
or the boundaries a first run would freeze, computed without saving) and runs the two descriptive
tables the proposer already reads:

  calibration   settled rate vs first quote per (life band, price bin), net of the fee
                (agent.calibration_cells)
  fair value    walk-forward forecast/odds blend vs the mid per time-to-close band
                (agent.fair_value_rows)

It stores how many cells clear 2 SE after fees and the strongest one. Many markets are scanned, so
some leads are luck. That only decides where research looks first; anything found still has to
pass the held-out gate.

    python -m app.rsi_scout [--max-markets 50] [--stale-hours 24] [--market high_ny]
"""
from __future__ import annotations

import argparse
import gc
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from app.trading.markets import MARKETS

_LOG = logging.getLogger(__name__)

DDL = [
    """
    CREATE TABLE IF NOT EXISTS app_rsi_scout (
      market VARCHAR(64) PRIMARY KEY,
      family VARCHAR(48) NOT NULL,
      scanned_at DATETIME NOT NULL,
      contracts INT NOT NULL DEFAULT 0,
      research_days DOUBLE NOT NULL DEFAULT 0,
      cal_leads INT NOT NULL DEFAULT 0,
      fv_leads INT NOT NULL DEFAULT 0,
      best_z DOUBLE NULL,
      best_net_c DOUBLE NULL,                -- net edge per contract of the strongest lead, cents
      best_what VARCHAR(200) NULL,
      error VARCHAR(255) NULL,
      INDEX idx_scout_z (best_z)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

LEAD_SE = 2.0


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def scan_dataset(ds) -> Dict:
    """Leads in one research dataset: counts, and the strongest by z = net edge / SE."""
    from app.research import agent
    leads = []
    for c in agent.calibration_cells(ds):
        if c["lead"]:
            leads.append((c["z"], c["best"], "calibration %s %d-%dc buy-%s" % (
                c["band"], c["lo_c"], c["hi_c"], c["side"].upper())))
    cal = len(leads)
    for r in agent.fair_value_rows(ds):
        for label in ("raw", "blend"):
            n, _n_ev, mean, se = r[label]
            if n and se and se != float("inf") and mean > LEAD_SE * se:
                leads.append((mean / se, mean, "%s %s %s vs mid" % (r["name"], r["band"], label)))
    best = max(leads) if leads else None
    span = max((getattr(ds, "end_ts", 0) or 0) - (getattr(ds, "start_ts", 0) or 0), 0) / 86400.0
    return {"contracts": len(getattr(ds, "results", {}) or {}), "research_days": round(span, 1),
            "cal_leads": cal, "fv_leads": len(leads) - cal,
            "best_z": round(best[0], 2) if best else None,
            "best_net_c": round(100 * best[1], 2) if best else None,
            "best_what": best[2][:200] if best else None}


def research_window(cur, market: str) -> Dict:
    """The market's research window WITHOUT freezing anything: its active partition if one exists,
    else the boundaries a first research run would freeze."""
    from app.research import partitions
    from app import research_repository as rr
    active = rr.get_active_partition(cur, market)
    if active:
        return active
    m = MARKETS[market]
    from datetime import timedelta
    contracts = rr.partition_contracts(cur, m, _now() - timedelta(days=m.history_days))
    if not contracts:
        raise ValueError("no settled contracts")
    return partitions._compute_boundaries(m, contracts, min_research_to=None)


def scan_market(cur, market: str) -> Dict:
    from app.research import partitions
    window = research_window(cur, market)
    ds = partitions.research_dataset(market, window)
    try:
        return scan_dataset(ds)
    finally:
        del ds
        gc.collect()


def save(cur, market: str, row: Dict) -> None:
    from app.research import rsi
    cur.execute(
        "REPLACE INTO app_rsi_scout (market, family, scanned_at, contracts, research_days, cal_leads, fv_leads, "
        "best_z, best_net_c, best_what, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (market, rsi.family(market), _now(), row.get("contracts", 0), row.get("research_days", 0),
         row.get("cal_leads", 0), row.get("fv_leads", 0), row.get("best_z"), row.get("best_net_c"),
         row.get("best_what"), (row.get("error") or None) and str(row["error"])[:255]))


def candidates(cur, stale_hours: float) -> List[str]:
    """Researchable binary markets with candles, least recently scanned first, skipping fresh scans."""
    from app import repository as repo
    ready = repo.series_with_candles(cur)
    # A tick-sourced twin (btc15m_tick) shares its candle market's contracts; the candle one is scanned.
    keys = [k for k, m in MARKETS.items() if m.kind == "binary" and m.source == "candles" and m.series in ready]
    cur.execute("SELECT market, scanned_at FROM app_rsi_scout")
    seen = {r["market"]: r["scanned_at"] for r in cur.fetchall()}
    cutoff = _now().timestamp() - stale_hours * 3600
    keep = [k for k in keys if k not in seen or seen[k].timestamp() < cutoff]
    return sorted(keep, key=lambda k: seen[k].timestamp() if k in seen else 0.0)


def run(conn, markets: Optional[Iterable[str]] = None, max_markets: int = 50, stale_hours: float = 24.0) -> int:
    """Scan up to max_markets markets (committing each) and return how many were scanned."""
    cur = conn.cursor()
    todo = list(markets) if markets else candidates(cur, stale_hours)
    done = 0
    for market in todo[:max_markets]:
        t0 = time.time()
        try:
            row = scan_market(cur, market)
        except Exception as e:  # noqa: BLE001 - one bad market never stops the pass
            _LOG.warning("scout %s failed: %s", market, e)
            row = {"error": "%s: %s" % (type(e).__name__, e)}
        save(cur, market, row)
        conn.commit()
        done += 1
        print("[scout] %s %.1fs %s" % (market, time.time() - t0,
                                       row.get("best_what") or row.get("error") or "no leads"), flush=True)
    return done


def ranking(cur, limit: int = 10) -> List[Dict]:
    """Markets with at least one lead, strongest first."""
    cur.execute("SELECT market, family, scanned_at, contracts, research_days, cal_leads, fv_leads, best_z, "
                "best_net_c, best_what FROM app_rsi_scout WHERE error IS NULL AND best_z IS NOT NULL "
                "ORDER BY best_z DESC LIMIT %s", (int(limit),))
    return [r for r in cur.fetchall() if r["market"] in MARKETS]


def prompt_lines(cur, limit: int = 8) -> str:
    """The ranking as a few lines for the autopilot's market choice ("" when nothing is known)."""
    rows = ranking(cur, limit)
    if not rows:
        return ""
    return "\n".join("- %s (%s): %s, %+.1fc net per contract, z=%.1f; %d calibration + %d fair-value lead(s)"
                     % (r["market"], MARKETS[r["market"]].label[:40], r["best_what"], r["best_net_c"] or 0.0,
                        r["best_z"], r["cal_leads"], r["fv_leads"]) for r in rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-markets", type=int, default=50)
    ap.add_argument("--stale-hours", type=float, default=24.0)
    ap.add_argument("--market", action="append", help="scan only these market keys")
    a = ap.parse_args()
    from data_pipeline.common import get_db_conn
    conn = get_db_conn()
    try:
        n = run(conn, a.market, a.max_markets, a.stale_hours)
        print("[scout] scanned %d market(s)" % n, flush=True)
        from app.research import rsi_repair   # same cadence: ask for missing data, re-test ideas whose data arrived
        try:
            print("[scout] data repair %s" % rsi_repair.run(conn), flush=True)
        except Exception as e:  # noqa: BLE001 - the scan's results are already committed
            print("[scout] data repair failed: %r" % e, flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
