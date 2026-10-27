"""Run the market-making research loop once (paper only): app.services.maker_lab wired to the tick
replay (app.adapters.sim.maker_eval), the run's model, and the S3 ledger. The result lands at
s3://<datalake>/research-watch/maker/runs/<UTC time>_<series>.json.

    python -m app.maker_lab_run --series KXBTCD --hours 24 --holdout 12
    python -m app.maker_lab_run --series auto       # the timer: rotates the series every 4 hours

``--series auto`` takes KXBTCD, KXBTC15M, KXBTC in turn by the 4-hour slot of the day, so each
series runs every 12 hours and, with a 12-hour holdout, its held-out windows never overlap. Each run
shows the model the summaries of that series' last PRIOR_RUNS runs.
"""
from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from app.adapters.sim.maker_eval import evaluate
from app.adapters.llm.llm import Usage
from app.services.maker_lab import S3Ledger, run_lab, split, summary_lines
from trading_core.engine.maker_policy import MAKER_SERIES

PREFIX = "research-watch/maker/runs/"
STATUS = "research-watch/maker/status/"   # <UTC time>_<series>.json: started, then done or failed
PRIOR_RUNS = 3
ROTATION = ("KXBTCD", "KXBTC15M", "KXBTC")


def auto_series(now: datetime) -> str:
    return ROTATION[(now.hour // 4) % len(ROTATION)]


def prior_lines(s3, bucket: str, series: str, n: int = PRIOR_RUNS) -> List[str]:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX):
        keys += [o["Key"] for o in page.get("Contents") or [] if o["Key"].endswith("_%s.json" % series)]
    out: List[str] = []
    for key in sorted(keys)[-n:]:
        try:
            out += summary_lines(json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read()))
        except Exception as e:  # noqa: BLE001 - one unreadable run must not stop the next
            print("[maker_lab] skip %s: %r" % (key, e), flush=True)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--series", default="auto", choices=MAKER_SERIES + ("auto",))
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--holdout", type=int, default=12)
    ap.add_argument("--end", default=None, help="exclusive end hour (default: the last archived hour)")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--per-round", type=int, default=4)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--model", default=None, help="models_catalog key (default: the catalog default)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    import boto3
    from app.adapters.llm import models_catalog as catalog
    from app.adapters.llm.llm import claude
    from data_pipeline.tick_store import BUCKET
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) if a.end else \
        datetime.now(timezone.utc) - timedelta(minutes=30)
    research, holdout = split(end, a.hours, a.holdout)
    series = auto_series(datetime.now(timezone.utc)) if a.series == "auto" else a.series
    choice = catalog.resolve(a.model)
    model = lambda system, messages, on_delta=None: claude(system, messages, choice.model_id)  # noqa: E731
    s3 = boto3.client("s3")
    # Nobody can read the box log from outside, so the run's fate is written next to its results: a
    # status that stays "started" means the process was killed (out of memory or the unit timeout).
    started = datetime.now(timezone.utc)
    status_key = "%s%s_%s.json" % (STATUS, started.strftime("%Y%m%dT%H%M"), series)

    def status(state: str, **extra) -> None:
        doc = dict(state=state, series=series, started=started.isoformat(), at=datetime.now(timezone.utc).isoformat(),
                   workers=a.workers, **extra)
        s3.put_object(Bucket=BUCKET, Key=status_key, Body=json.dumps(doc, default=str).encode())

    status("started")
    try:
        out = run_lab(series, research, holdout, model, Usage(), S3Ledger(s3, BUCKET), evaluate, a.rounds,
                      a.per_round, a.workers, prior=prior_lines(s3, BUCKET, series))
    except Exception:
        status("failed", error=traceback.format_exc()[-4000:])
        raise
    out["model"] = choice.model_id
    body = json.dumps(out, indent=1, default=str)
    key = "research-watch/maker/runs/%s_%s.json" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M"), series)
    s3.put_object(Bucket=BUCKET, Key=key, Body=body.encode())
    if a.out:
        with open(a.out, "w") as f:
            f.write(body)
    status("done", result=key)
    print("saved s3://%s/%s" % (BUCKET, key))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
