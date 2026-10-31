"""Run the market-making research loop once (paper only): app.services.maker_lab wired to the tick
replay (app.adapters.sim.maker_eval), the run's model, and the S3 ledger. The result lands at
s3://<datalake>/research-watch/maker/runs/<UTC time>_<series>.json.

    python -m app.maker_lab_run --series KXBTCD --hours 24 --holdout 12
    python -m app.maker_lab_run --series auto       # the timer: rotates the series every 4 hours

``--series auto`` takes KXBTCD, KXBTC15M, KXBTC in turn by the 4-hour slot of the day, so each
series runs every 12 hours and, with a 12-hour holdout, its held-out windows never overlap. Each run
shows the model the summaries of that series' last PRIOR_RUNS runs.

Before its own search, a run judges up to FORWARD_PER_RUN earlier finalists of its series on the 24
hours after their holdout (maker_lab.forward_due); ``--forward-only`` does just that, for every series.
"""
from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from app.adapters.sim.maker_eval import evaluate
from app.adapters.llm.llm import Usage
from app.services.maker_lab import S3ForwardBook, S3Ledger, forward_due, judge_forward, run_lab, split, summary_lines
from trading_core.engine.maker_policy import MAKER_SERIES

PREFIX = "research-watch/maker/runs/"
STATUS = "research-watch/maker/status/"   # <UTC time>_<series>.json: started, then done or failed
PRIOR_RUNS = 3
ROTATION = ("KXBTCD", "KXBTC15M", "KXBTC")
# (rounds, policies per round) per series, sized to finish inside the 4-hour slot: a KXBTCD hour
# replays in 20-40s, so it stays at 3x4 (~2h20m); KXBTC (~10s/hour) and KXBTC15M search wider.
# Todd moved taker research spend to the maker lane on 2026-10-30.
SEARCH = {"KXBTCD": (3, 4), "KXBTC15M": (4, 5), "KXBTC": (5, 6)}
# Forward judgments per run: 24 replayed hours each; KXBTCD's search already takes ~2h20m of the 4h slot.
FORWARD_PER_RUN = {"KXBTCD": 1, "KXBTC15M": 2, "KXBTC": 2}


def auto_series(now: datetime) -> str:
    return ROTATION[(now.hour // 4) % len(ROTATION)]


def search_size(series: str, rounds: Optional[int] = None, per_round: Optional[int] = None):
    r, n = SEARCH.get(series, (3, 4))
    return (r if rounds is None else rounds), (n if per_round is None else per_round)


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


def run_docs(s3, bucket: str, series: Optional[str] = None) -> List[dict]:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX):
        keys += [o["Key"] for o in page.get("Contents") or []
                 if o["Key"].endswith(".json") and (series is None or o["Key"].endswith("_%s.json" % series))]
    out = []
    for key in sorted(keys):
        try:
            out.append(json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read()))
        except Exception as e:  # noqa: BLE001
            print("[maker_lab] skip %s: %r" % (key, e), flush=True)
    return out


def forward(s3, bucket: str, archived_to: datetime, series: Optional[str], limit: int, workers: int) -> List[dict]:
    book = S3ForwardBook(s3, bucket)
    return [judge_forward(c, book, evaluate, workers) for c in forward_due(run_docs(s3, bucket, series), book,
                                                                           archived_to, limit)]


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--series", default="auto", choices=MAKER_SERIES + ("auto",))
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--holdout", type=int, default=12)
    ap.add_argument("--end", default=None, help="exclusive end hour (default: the last archived hour)")
    ap.add_argument("--rounds", type=int, default=None, help="default: SEARCH[series]")
    ap.add_argument("--per-round", type=int, default=None, help="default: SEARCH[series]")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--model", default=None, help="models_catalog key (default: the catalog default)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--forward-only", action="store_true", help="judge due forward windows, every series, no search")
    a = ap.parse_args(argv)
    import boto3
    from app.adapters.llm import models_catalog as catalog
    from app.adapters.llm.llm import claude
    from data_pipeline.tick_store import BUCKET
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) if a.end else \
        datetime.now(timezone.utc) - timedelta(minutes=30)
    research, holdout = split(end, a.hours, a.holdout)
    archived_to = holdout[-1] + timedelta(hours=1)
    if a.forward_only:
        import boto3
        from data_pipeline.tick_store import BUCKET
        done = forward(boto3.client("s3"), BUCKET, archived_to, None, 10, a.workers)
        print(json.dumps(done, indent=1))
        return 0
    series = auto_series(datetime.now(timezone.utc)) if a.series == "auto" else a.series
    rounds, per_round = search_size(series, a.rounds, a.per_round)
    choice = catalog.resolve(a.model)
    model = lambda system, messages, on_delta=None: claude(system, messages, choice.model_id)  # noqa: E731
    s3 = boto3.client("s3")
    # Nobody can read the box log from outside, so the run's fate is written next to its results: a
    # status that stays "started" means the process was killed (out of memory or the unit timeout).
    started = datetime.now(timezone.utc)
    status_key = "%s%s_%s.json" % (STATUS, started.strftime("%Y%m%dT%H%M"), series)

    def status(state: str, **extra) -> None:
        doc = dict(state=state, series=series, started=started.isoformat(), at=datetime.now(timezone.utc).isoformat(),
                   workers=a.workers, rounds=rounds, per_round=per_round, **extra)
        s3.put_object(Bucket=BUCKET, Key=status_key, Body=json.dumps(doc, default=str).encode())

    status("started")
    fwd: List[dict] = []
    try:
        fwd = forward(s3, BUCKET, archived_to, series, FORWARD_PER_RUN.get(series, 1), a.workers)
        if fwd:
            status("started", forward=fwd)
    except Exception:  # noqa: BLE001 - a forward failure must not cost the run its search
        print("[maker_lab] forward step failed: %s" % traceback.format_exc()[-2000:], flush=True)
    try:
        out = run_lab(series, research, holdout, model, Usage(), S3Ledger(s3, BUCKET), evaluate, rounds,
                      per_round, a.workers, prior=prior_lines(s3, BUCKET, series))
    except Exception:
        status("failed", error=traceback.format_exc()[-4000:])
        raise
    out["model"] = choice.model_id
    out["forward"] = fwd
    body = json.dumps(out, indent=1, default=str)
    key = "research-watch/maker/runs/%s_%s.json" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M"), series)
    s3.put_object(Bucket=BUCKET, Key=key, Body=body.encode())
    if a.out:
        with open(a.out, "w") as f:
            f.write(body)
    status("done", result=key, forward=fwd)
    print("saved s3://%s/%s" % (BUCKET, key))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
