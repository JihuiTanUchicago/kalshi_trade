"""Fixed encrypted selected-source capture over bounded SSM pages; no S3."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid
import zlib

import transfer


HERE = Path(__file__).resolve().parent
BASE = "0e2e79c30d13bab8dec41081ef4d273d826b127c"
REUSED = "kalshi_trade_infra/results/kalshi_bitcoin_perps_2026-10-23/operations/"
PYTHON = "/opt/kalshi/.venv313/bin/python"
INSTANCE = "i-077d6f7873e7836ba"
REGION = "us-east-1"


class RunnerError(RuntimeError):
    pass


def emit(kind, value):
    print("TAU_PERPS_SOURCE_" + kind + "=" + json.dumps(value, sort_keys=True), flush=True)


def git(*args):
    result = subprocess.run(["git", "-C", str(HERE.parents[3]), *args],
                            capture_output=True, check=True, timeout=30)
    return result.stdout


def aws(*args):
    result = subprocess.run(["aws", *args, "--region", REGION, "--output", "json"],
                            capture_output=True, timeout=45)
    if result.returncode:
        raise RunnerError("aws_request_failed") from None
    return json.loads(result.stdout) if result.stdout.strip() else {}


def program(mode, capture_id, operations_sha, *, index=None, envelope_sha=None):
    if mode not in {"capture", "page", "cleanup"}:
        raise RunnerError("invalid_source_operation")
    public = (HERE / "recipient.pub.pem").read_bytes()
    if transfer.digest(public) != transfer.RECIPIENT_PEM_SHA256:
        raise RunnerError("recipient_key_mismatch")
    guard_source = git("show", BASE + ":" + REUSED + "remote.py").decode()
    repository_source = git("show", BASE + ":" + REUSED + "readiness_repository.py").decode()
    # Only encryption definitions enter the remote program. Decryption stays local.
    encryption_source = (HERE / "transfer.py").read_text().split("\ndef decrypt(", 1)[0]
    source = ("import json,types\ng={};exec(" + repr(guard_source) + ",g);g['CONFIG']=()\n"
              "p={};exec(" + repr(encryption_source) + ",p)\n"
              "c={};exec(" + repr((HERE / "capture.py").read_text()) + ",c)\n"
              "guard=types.SimpleNamespace(**g);protocol=types.SimpleNamespace(**p)\ntry:\n")
    if mode == "capture":
        call = "c['capture'](" + ",".join(map(repr, (capture_id, public, operations_sha, repository_source))) + ",guard,protocol)"
    elif mode == "page":
        call = "c['page'](" + ",".join(map(repr, (capture_id, index, envelope_sha))) + ",guard,protocol)"
    else:
        call = "c['cleanup'](" + repr(capture_id) + ")"
    source += (" result=" + call + "\nexcept Exception as exc:\n"
               " code=str(exc) if isinstance(exc,(c['CaptureError'],p['TransferError'],g['InspectionError'])) else 'source_operation_failed'\n"
               " result={'status':'error','error_code':code}\nprint(json.dumps(result))\n")
    packed = base64.b64encode(zlib.compress(source.encode())).decode()
    command = PYTHON + " -B -c " + shlex.quote("import base64,zlib;exec(zlib.decompress(base64.b64decode(" + repr(packed) + ")))")
    if len(command) > 24000:
        raise RunnerError("source_program_limit")
    return command


def request(mode, capture_id, operations_sha, deadline, **kwargs):
    if time.monotonic() >= deadline:
        raise RunnerError("source_transfer_deadline")
    response = aws("ssm", "send-command", "--instance-ids", INSTANCE, "--document-name", "AWS-RunShellScript",
                   "--comment", "Tau encrypted read-only selected-source review",
                   "--parameters", json.dumps({"commands": [program(mode, capture_id, operations_sha, **kwargs)],
                                                "executionTimeout": ["180" if mode == "capture" else "30"]}))
    identifier = response["Command"]["CommandId"]
    emit("PHASE", {"operation": mode, "ssm_command_id": identifier})
    phase_deadline = min(deadline, time.monotonic() + (225 if mode == "capture" else 75))
    while time.monotonic() < phase_deadline:
        time.sleep(2)
        try:
            response = aws("ssm", "get-command-invocation", "--command-id", identifier, "--instance-id", INSTANCE)
        except RunnerError:
            continue
        if response.get("Status") in {"Success", "Failed", "TimedOut", "Cancelled"}:
            break
    if response.get("Status") != "Success":
        raise RunnerError("remote_source_operation_failed")
    raw = response.get("StandardOutputContent", "")
    if len(raw) > 24000:
        raise RunnerError("source_receipt_limit")
    result = json.loads(raw)
    if isinstance(result, dict) and result.get("status") == "error":
        code = result.get("error_code", "")
        raise RunnerError(code if re.fullmatch(r"[a-z0-9_]{1,80}", code) else "source_operation_requires_inspection")
    if not isinstance(result, dict):
        raise RunnerError("source_operation_requires_inspection")
    return result


def run():
    operations_sha = git("rev-parse", "HEAD").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", operations_sha) or os.environ.get("GITHUB_SHA", operations_sha) != operations_sha:
        raise RunnerError("operations_head_mismatch")
    capture_id = uuid.uuid4().hex
    deadline = time.monotonic() + 600
    emit("PREFLIGHT", {"operations_sha": operations_sha, "capture_id": capture_id,
                       "recipient_pem_sha256": transfer.RECIPIENT_PEM_SHA256,
                       "selected_source_pins": transfer.PINS, "max_pages": transfer.MAX_PAGES,
                       "no_release_or_provider_path": True})
    try:
        receipt = request("capture", capture_id, operations_sha, deadline)
        if (receipt.get("status") != "captured" or receipt.get("capture_id") != capture_id
                or type(receipt.get("pages")) is not int or not 1 <= receipt["pages"] <= transfer.MAX_PAGES
                or not re.fullmatch(r"[0-9a-f]{64}", receipt.get("envelope_sha256", ""))):
            raise RunnerError("invalid_capture_receipt")
        emit("CAPTURE", receipt)
        for index in range(receipt["pages"]):
            page = request("page", capture_id, operations_sha, deadline,
                           index=index, envelope_sha=receipt["envelope_sha256"])
            content = base64.b64decode(page.get("data", ""), validate=True)
            if (page.get("status") != "encrypted_page" or page.get("capture_id") != capture_id
                    or page.get("index") != index or page.get("pages") != receipt["pages"]
                    or page.get("envelope_sha256") != receipt["envelope_sha256"]
                    or not 1 <= len(content) <= transfer.PAGE_BYTES or page.get("page_sha256") != transfer.digest(content)):
                raise RunnerError("encrypted_page_mismatch")
            emit("PAGE", page)
    finally:
        cleanup = request("cleanup", capture_id, operations_sha, time.monotonic() + 120)
        emit("CLEANUP", cleanup)
        if cleanup.get("status") != "cleaned" or cleanup.get("temporary_directory_removed") is not True:
            raise RunnerError("encrypted_source_cleanup_failed")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        emit("ERROR", {"status": "source_capture_requires_inspection",
                       "error_code": str(exc) if isinstance(exc, RunnerError) else "source_operation_failed"})
        raise SystemExit(1)
