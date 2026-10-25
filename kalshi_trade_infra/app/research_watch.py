"""Research watch: a health report on active and recent research sessions, every 20 minutes.

The research loop runs unattended, so its failures have to surface by themselves. This reads the
runs of the last few hours (plus everything still queued or running) and their events, and flags:

  failed        a run that failed, with its error tagged like a drop (spec_invalid = our bug)
  stalled       running with no event or heartbeat for STALL_MIN minutes
  queued_long   queued for QUEUE_MIN minutes (no worker slot, or the worker is down)
  burn          a finished run that spent >= BURN_USD and gated nothing
  bug_deaths    ideas the validator/parser killed (spec_invalid): never acceptable
  pipeline      most of a run's drops were the pipeline's fault (missing feature / data)
  wrong_fit     the proposer spent several ideas on mechanisms the market cannot support
  unclassified  many drops the classifier can't tag (rsi._DROP_RULES needs rules)
  repeat        one market researched again and again with nothing gated

The report goes to S3 (datalake research-watch/latest.json plus one file per run of the watch), so
it can be read without database access, and to stdout. Read-only on the database.

    python -m app.research_watch --hours 3 [--no-s3]
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app import rsi

STALL_MIN = float(os.getenv("TAU_WATCH_STALL_MIN", "20"))
QUEUE_MIN = float(os.getenv("TAU_WATCH_QUEUE_MIN", "45"))
BURN_USD = float(os.getenv("TAU_WATCH_BURN_USD", "5"))
# A finished run's flags drop to "low" (stale) once it ended this long ago: the watch runs every 20
# minutes, so by then they were reported at their real severity, and repeating a handled failure as
# "high" for the whole 3h window buries the new ones.
FRESH_MIN = float(os.getenv("TAU_WATCH_FRESH_MIN", "60"))
BUCKET = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-568386354218-us-east-1")
PREFIX = "research-watch"
_RUN_COLS = ("id, user_id, market, status, error, model, prompt, hypotheses_tried, strategies_passed, "
             "input_tokens, output_tokens, created_at, started_at, heartbeat_at, finished_at")


def _naive(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


def _minutes(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    return round((b - a).total_seconds() / 60.0, 1) if a and b else None


def run_summary(run: Dict, events: List[Dict], now: datetime) -> Dict:
    """One run's line in the report: its funnel card, timing, last phase and tagged drops."""
    card = rsi.run_card(run, [e for e in events if e.get("kind") == "verdict"])
    created, started = _naive(run.get("created_at")), _naive(run.get("started_at"))
    last_ev = max((_naive(e["created_at"]) for e in events if e.get("created_at")), default=None)
    beat = max([t for t in (last_ev, _naive(run.get("heartbeat_at")), started) if t], default=None)
    phase = next((e["data"].get("phase") for e in reversed(events)
                  if e.get("kind") == "step" and (e.get("data") or {}).get("phase")), None)
    drops = []
    for e in events:
        d = e.get("data") or {}
        if e.get("kind") == "verdict" and d.get("status") == "abandoned":
            why = d.get("why") or e.get("message") or ""
            drops.append({"tag": rsi.classify_drop(why)[0], "title": (d.get("title") or "")[:100],
                          "why": " ".join(why.split())[:220]})
    end = _naive(run.get("finished_at")) or now
    return {
        "run_id": run["id"], "user_id": run.get("user_id"), "market": run.get("market"),
        "status": run.get("status"), "model": run.get("model"), "prompt": (run.get("prompt") or "")[:160],
        "error": (run.get("error") or "")[:300] or None,
        "error_tag": rsi.classify_drop(run.get("error"))[0] if run.get("error") else None,
        "created_at": str(created or ""), "queued_min": _minutes(created, started or now),
        "run_min": _minutes(started, end) if started else None,
        "idle_min": _minutes(beat, now) if run.get("status") == "running" else None,
        "ended_min_ago": _minutes(_naive(run.get("finished_at")), now),
        "phase": phase, "cost_usd": card["cost_usd"], "explored": card["explored"],
        "dropped": card["dropped"], "gated": card["gated"], "passed": card["passed"],
        "deaths": card["deaths"], "death_kinds": card["death_kinds"], "drops": drops[-12:],
    }


def _flag(out: List[Dict], severity: str, kind: str, s: Optional[Dict], detail: str) -> None:
    out.append({"severity": severity, "kind": kind, "run_id": s and s["run_id"],
                "market": s and s["market"], "detail": detail})


def anomalies(summaries: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    finished = ("succeeded", "stopped", "failed")
    for s in summaries:
        first = len(out)
        deaths = s["deaths"]
        if s["status"] == "failed":
            bug = s["error_tag"] == "spec_invalid"
            _flag(out, "high" if bug else "medium", "failed", s,
                  "%s%s" % ("our bug: " if bug else "", s["error"] or "no error recorded"))
        if s["status"] == "running" and (s["idle_min"] or 0) >= STALL_MIN:
            _flag(out, "high", "stalled", s, "no progress for %.0f min (phase %s)" % (s["idle_min"], s["phase"]))
        if s["status"] == "queued" and (s["queued_min"] or 0) >= QUEUE_MIN:
            _flag(out, "medium", "queued_long", s, "queued for %.0f min" % s["queued_min"])
        if s["status"] in finished and s["cost_usd"] >= BURN_USD and not s["gated"]:
            _flag(out, "medium", "burn", s, "$%.2f, %d ideas, nothing gated" % (s["cost_usd"], s["explored"]))
        if deaths.get("spec_invalid"):
            _flag(out, "high", "bug_deaths", s, "%d idea(s) killed by spec validation" % deaths["spec_invalid"])
        n = s["dropped"]
        if n >= 4 and s["death_kinds"].get("pipeline", 0) * 2 >= n:
            _flag(out, "medium", "pipeline", s, "%d of %d drops were the pipeline's fault: %s" % (
                s["death_kinds"]["pipeline"], n, ", ".join("%s %d" % kv for kv in sorted(deaths.items()))))
        if deaths.get("wrong_fit", 0) >= 3:
            _flag(out, "low", "wrong_fit", s, "%d ideas did not fit the market's structure" % deaths["wrong_fit"])
        if n >= 4 and deaths.get("other", 0) * 10 >= 3 * n:
            _flag(out, "low", "unclassified", s, "%d of %d drops unclassified" % (deaths["other"], n))
        if (s["ended_min_ago"] or 0) > FRESH_MIN:
            for a in out[first:]:
                a.update(severity="low", stale=True)
    by_market: Dict[str, List[Dict]] = defaultdict(list)
    for s in summaries:
        if s["status"] in finished:
            by_market[s["market"]].append(s)
    for market, runs in by_market.items():
        if len(runs) >= 3 and not any(r["gated"] for r in runs):
            _flag(out, "low", "repeat", None, "%s: %d runs, $%.2f, nothing gated" % (
                market, len(runs), sum(r["cost_usd"] for r in runs)))
            out[-1]["market"] = market
    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda a: rank[a["severity"]])


def build_report(runs: List[Dict], events: Dict[int, List[Dict]], now: datetime, hours: float) -> Dict:
    summaries = [run_summary(r, events.get(r["id"], []), now) for r in runs]
    finished = [s for s in summaries if s["status"] in ("succeeded", "stopped", "failed")]
    cards = [rsi.run_card(r, [e for e in events.get(r["id"], []) if e.get("kind") == "verdict"])
             for r in runs if r.get("status") in ("succeeded", "stopped", "failed")]
    return {
        "generated_at": now.replace(tzinfo=timezone.utc).isoformat(), "hours": hours,
        "status_counts": dict(Counter(s["status"] for s in summaries)),
        "totals": rsi._rollup(cards) if cards else None,
        "models": {m: {"runs": len(v), "cost_usd": round(sum(s["cost_usd"] for s in v), 2),
                       "gated": sum(s["gated"] for s in v)}
                   for m, v in _group(finished, "model").items()},
        "screen_ab": screen_ab(cards),
        "leads_ab": screen_ab(cards, "leads_arm"),
        "anomalies": anomalies(summaries),
        "runs": sorted(summaries, key=lambda s: -s["run_id"]),
    }


def screen_ab(cards: List[Dict], key: str = "arm") -> Dict[str, Dict]:
    """An A/B by arm: the model tiering (services.research_screen, key "arm") or the data-first
    scan (services.research_leads, key "leads_arm"). Ideas tested per dollar, how many reached the
    gate, and for the screen arm how often the developer overturned an audited screen drop."""
    out: Dict[str, Dict] = {}
    for arm, rows in _group([c for c in cards if c.get(key)], key).items():
        cost = sum(c["cost_usd"] for c in rows)
        explored = sum(c["explored"] for c in rows)
        gated = sum(c["gated"] for c in rows)
        tally = Counter()
        for c in rows:
            tally.update({k: v or 0 for k, v in (c.get("screen") or {}).items() if k != "screen_model"})
        out[arm] = {"runs": len(rows), "cost_usd": round(cost, 2), "explored": explored,
                    "developed": sum(c["developed"] for c in rows), "gated": gated,
                    "passed": sum(c["passed"] for c in rows),
                    "ideas_per_usd": round(explored / cost, 2) if cost > 0 else None,
                    "gate_reach_rate": round(gated / explored, 3) if explored else None,
                    **({"screened_out": tally["screened_out"], "handed_over": tally["handed_over"],
                        "audits": tally["audits"], "rescued": tally["rescued"]} if arm == "screen" else {})}
    return out


def _group(rows: List[Dict], key: str) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        out[str(r.get(key))].append(r)
    return out


def load(cur, hours: float) -> tuple:
    cur.execute("SELECT %s FROM app_agent_runs WHERE kind='research' AND (status IN ('queued','running') "
                "OR created_at >= UTC_TIMESTAMP() - INTERVAL %%s MINUTE OR finished_at >= UTC_TIMESTAMP() "
                "- INTERVAL %%s MINUTE) ORDER BY id" % _RUN_COLS, (int(hours * 60), int(hours * 60)))
    runs = list(cur.fetchall())
    events: Dict[int, List[Dict]] = defaultdict(list)
    ids = [r["id"] for r in runs]
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        cur.execute("SELECT run_id, kind, message, data_json, created_at FROM app_agent_events WHERE "
                    "kind IN ('verdict','step','error') AND run_id IN (%s) ORDER BY id"
                    % ",".join(["%s"] * len(chunk)), chunk)
        for r in cur.fetchall():
            data = r.get("data_json")
            if isinstance(data, (bytes, str)):
                try:
                    data = json.loads(data)
                except ValueError:
                    data = None
            events[r["run_id"]].append({"kind": r["kind"], "message": r["message"], "data": data or {},
                                        "created_at": r["created_at"]})
    return runs, events


def publish(report: Dict, s3=None) -> str:
    """latest.json plus a dated copy; returns the dated key."""
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    body = json.dumps(report, default=str, separators=(",", ":")).encode()
    ts = report["generated_at"][:16].replace(":", "")
    key = "%s/date=%s/%s.json" % (PREFIX, ts[:10], ts[11:])
    for k in (key, PREFIX + "/latest.json"):
        s3.put_object(Bucket=BUCKET, Key=k, Body=body, ContentType="application/json")
    return key


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float, default=3.0)
    ap.add_argument("--no-s3", action="store_true")
    a = ap.parse_args()
    from data_pipeline.common import get_db_conn
    conn = get_db_conn()
    try:
        runs, events = load(conn.cursor(), a.hours)
    finally:
        conn.close()
    report = build_report(runs, events, datetime.now(timezone.utc).replace(tzinfo=None), a.hours)
    print(json.dumps({k: report[k] for k in ("generated_at", "status_counts", "anomalies")}, default=str), flush=True)
    if not a.no_s3:
        try:
            print("[watch] wrote s3://%s/%s" % (BUCKET, publish(report)), flush=True)
        except Exception as e:  # noqa: BLE001 - the stdout log still carries the anomalies
            print("[watch] s3 write failed: %r" % e, flush=True)


if __name__ == "__main__":
    main()
