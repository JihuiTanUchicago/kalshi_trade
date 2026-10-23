"""Capture exact-head deliberate release markers, never persist raw Actions logs."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

REPO = "JihuiTanUchicago/kalshi_trade"
MARKER = re.compile(r"TAU_PERPS_RELEASE_(PREFLIGHT|PHASE|INVENTORY|PREPARED|CDN_BEFORE|CDN_ROLLBACK|APPLY|PUBLIC|CLEANUP|ERROR)=(\{.*\})\s*$")


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError("receipt_request_failed")
    return result.stdout


def records(raw):
    result = []
    for line in raw.splitlines():
        match = MARKER.search(line)
        if match:
            value = json.loads(match[2])
            if not isinstance(value, dict):
                raise RuntimeError("invalid_deliberate_receipt")
            result.append({"type": match[1], "receipt": value})
    return result


def collect(run, expected, destination):
    if not re.fullmatch(r"[1-9][0-9]{0,19}", run) or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("exact_operations_head_required")
    metadata = json.loads(command("gh", "run", "view", run, "--repo", REPO,
                                  "--json", "databaseId,status,conclusion,headSha,url"))
    if metadata.get("headSha") != expected:
        raise RuntimeError("operations_head_mismatch")
    if metadata.get("status") != "completed":
        return {"workflow": metadata, "records": []}
    raw = command("gh", "run", "view", run, "--repo", REPO, "--log")
    output = {"workflow": metadata, "records": records(raw)}
    raw = None
    if not output["records"]:
        raise RuntimeError("deliberate_receipt_unavailable")
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    (destination / ("RELEASE_" + run + ".json")).write_text(json.dumps(output, indent=2) + "\n")
    return output


if __name__ == "__main__":
    try:
        if len(sys.argv) != 4:
            raise RuntimeError("arguments_required")
        print(json.dumps(collect(sys.argv[1], sys.argv[2], Path(sys.argv[3])), indent=2))
    except Exception:
        print(json.dumps({"status": "release_receipt_requires_inspection"}))
        raise SystemExit(1)
