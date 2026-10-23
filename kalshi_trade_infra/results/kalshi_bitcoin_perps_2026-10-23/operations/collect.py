"""Keep only exact-head readiness JSON markers; never save or print raw logs."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys


REPO = "JihuiTanUchicago/kalshi_trade"
MARKER = re.compile(r"TAU_PERPS_READINESS_(PREFLIGHT|PHASE|INVENTORY|CLEANUP|ERROR)=(\{.*\})\s*$")


def command(*args):
    response = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if response.returncode:
        raise RuntimeError("receipt_request_failed") from None
    return response.stdout


def records(raw):
    result = []
    for line in raw.splitlines():
        match = MARKER.search(line)
        if match:
            value = json.loads(match[2])
            if not isinstance(value, dict):
                raise RuntimeError("invalid_fixed_receipt")
            result.append({"type": match[1], "receipt": value})
    return result


def collect(run, expected, destination):
    if not re.fullmatch(r"[1-9][0-9]{0,19}", run) or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("exact_operation_pin_required")
    meta = json.loads(command("gh", "run", "view", run, "--repo", REPO, "--json",
                              "databaseId,status,conclusion,headSha,url"))
    if meta.get("headSha") != expected:
        raise RuntimeError("operation_head_mismatch")
    if meta.get("status") != "completed":
        return {"workflow": meta, "records": []}
    raw = command("gh", "run", "view", run, "--repo", REPO, "--log")
    result = {"workflow": meta, "records": records(raw)}
    raw = None
    if not result["records"]:
        raise RuntimeError("fixed_receipt_unavailable")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / ("READINESS_" + run + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    try:
        if len(sys.argv) != 4:
            raise RuntimeError("arguments_required")
        print(json.dumps(collect(sys.argv[1], sys.argv[2], Path(sys.argv[3])), indent=2))
    except Exception:
        print(json.dumps({"status": "receipt_collection_requires_inspection"}))
        raise SystemExit(1)
