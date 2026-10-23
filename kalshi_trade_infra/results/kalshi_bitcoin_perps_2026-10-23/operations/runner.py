"""Only a passive readiness operation; no release, install or apply mode."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import uuid
import zlib

import remote


HERE = Path(__file__).resolve().parent
PRODUCT = "kalshi_trade_infra/"
REGION = remote.REGION
BUCKET = remote.BUCKET
INSTANCE = "i-077d6f7873e7836ba"


class RunnerError(RuntimeError):
    pass


def emit(kind, value):
    print("TAU_PERPS_READINESS_" + kind + "=" + json.dumps(value, sort_keys=True), flush=True)


def git(*args):
    response = subprocess.run(["git", "-C", str(HERE.parents[3]), *args],
                              capture_output=True, check=True, timeout=30)
    return response.stdout


def aws(*args):
    response = subprocess.run(["aws", *args, "--region", REGION, "--output", "json"],
                              capture_output=True, timeout=45)
    if response.returncode:
        raise RunnerError("aws_request_failed") from None
    return json.loads(response.stdout) if response.stdout.strip() else {}


def references(ref):
    output = {}
    for record in git("ls-tree", "-r", "-z", ref + ":kalshi_trade_infra", "app", "data_pipeline").split(b"\0"):
        if not record:
            continue
        header, name = record.decode().split("\t", 1)
        mode, kind, object_id = header.split()
        if not remote.source_path_allowed(name):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise RunnerError("unsafe_reference_source")
        output[name] = remote.digest(git("cat-file", "blob", object_id))
    return output


def diagnostic_bundle():
    pins = json.loads((HERE / "pins.json").read_text())
    if (set(pins) != {"candidate_commit", "native_sha256"}
            or pins["candidate_commit"] != remote.CANDIDATE
            or set(pins["native_sha256"]) != set(remote.NATIVE)):
        raise RunnerError("invalid_candidate_pins")
    files = {name: git("show", remote.CANDIDATE + ":" + PRODUCT + name) for name in remote.NATIVE}
    if any(remote.digest(files[name]) != pins["native_sha256"][name] for name in remote.NATIVE):
        raise RunnerError("candidate_source_hash_mismatch")
    files.update({name: (HERE / name).read_bytes() for name in remote.HELPERS})
    payload = {"candidate": remote.CANDIDATE, "base": remote.BASE,
               "files": {name: base64.b64encode(raw).decode() for name, raw in files.items()},
               "reference_sha256": {"base": references(remote.BASE), "candidate": references(remote.CANDIDATE)}}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > remote.MAX_BUNDLE:
        raise RunnerError("diagnostic_bundle_limit")
    return raw, pins["native_sha256"]


def program(artifact, native):
    code = (HERE / "remote.py").read_text() + "\nexecute(" + repr(artifact) + "," + repr(native) + ")\n"
    packed = base64.b64encode(zlib.compress(code.encode())).decode()
    launcher = "import base64,zlib;exec(zlib.decompress(base64.b64decode(" + repr(packed) + ")))"
    command = remote.PYTHON + " -B -c " + shlex.quote(launcher)
    if len(command) > 24000:
        raise RunnerError("diagnostic_program_limit")
    return command


def decode_receipt(value):
    envelope = json.loads(value)
    if (set(envelope) != {"encoding", "sha256", "payload"} or envelope["encoding"] != "zlib+base64"
            or not re.fullmatch(r"[0-9a-f]{64}", envelope["sha256"])
            or len(envelope["payload"]) > 22000):
        raise RunnerError("invalid_receipt")
    inflater = zlib.decompressobj()
    raw = inflater.decompress(base64.b64decode(envelope["payload"], validate=True), 1024 * 1024 + 1)
    if len(raw) > 1024 * 1024 or not inflater.eof or remote.digest(raw) != envelope["sha256"]:
        raise RunnerError("invalid_receipt")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise RunnerError("invalid_receipt")
    return result


def inspect_target(artifact, native):
    response = aws("ssm", "send-command", "--instance-ids", INSTANCE,
                   "--document-name", "AWS-RunShellScript", "--comment", "Tau read-only perps readiness; no release",
                   "--parameters", json.dumps({"commands": [program(artifact, native)], "executionTimeout": ["300"]}))
    identifier = response["Command"]["CommandId"]
    emit("PHASE", {"ssm_command_id": identifier})
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        time.sleep(3)
        try:
            response = aws("ssm", "get-command-invocation", "--command-id", identifier, "--instance-id", INSTANCE)
        except RunnerError:
            continue
        if response.get("Status") in {"Success", "Failed", "TimedOut", "Cancelled"}:
            break
    if response.get("Status") != "Success":
        raise RunnerError("remote_inspection_failed")
    return decode_receipt(response.get("StandardOutputContent", ""))


def run():
    head = git("rev-parse", "HEAD").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head) or os.environ.get("GITHUB_SHA", head) != head:
        raise RunnerError("operations_head_mismatch")
    raw, native = diagnostic_bundle()
    emit("PREFLIGHT", {"operations_sha": head, "candidate_commit": remote.CANDIDATE,
                       "candidate_native_sha256": native, "no_release_path": True})
    key = "bundle/perps-readiness-" + remote.CANDIDATE + "-" + uuid.uuid4().hex + ".json"
    artifact = {"bucket": BUCKET, "key": key, "sha256": remote.digest(raw)}
    uploaded = False
    with tempfile.TemporaryDirectory(prefix="tau-perps-diagnostic-") as temporary:
        body = Path(temporary) / "public-source-bundle.json"
        body.write_bytes(raw)
        try:
            aws("s3api", "put-object", "--bucket", BUCKET, "--key", key, "--body", str(body),
                "--server-side-encryption", "AES256")
            uploaded = True
            receipt = inspect_target(artifact, native)
            emit("INVENTORY", receipt)
            if receipt.get("status") != "inspected" or receipt.get("error_code"):
                raise RunnerError("readiness_requires_inspection")
        finally:
            if uploaded:
                # Existing IAM permits Put/Get only. Clear the current diagnostic
                # object without expanding permissions; no private data was staged.
                body.write_bytes(b"")
                try:
                    aws("s3api", "put-object", "--bucket", BUCKET, "--key", key, "--body", str(body),
                        "--server-side-encryption", "AES256")
                    emit("CLEANUP", {"current_diagnostic_object_cleared": True,
                                     "historical_s3_versions_inspected": False})
                except Exception:
                    emit("CLEANUP", {"current_diagnostic_object_cleared": False,
                                     "error_code": "diagnostic_object_cleanup_failed"})
                    raise RunnerError("diagnostic_object_cleanup_failed") from None


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        emit("ERROR", {"status": "inspection_incomplete",
                       "error_code": str(exc) if isinstance(exc, RunnerError) else "readiness_operation_failed"})
        raise SystemExit(1)
