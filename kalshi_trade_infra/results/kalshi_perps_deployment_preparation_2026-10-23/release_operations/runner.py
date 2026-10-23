"""Fixed candidate/archive/pins transport; deliberate receipts only, never raw logs."""
from __future__ import annotations

import base64
import hashlib
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
REPO = HERE.parents[3]
REGION = "us-east-1"
BUCKET = "kalshi-trade-artifacts-568386354218-us-east-1"
INSTANCE = "i-077d6f7873e7836ba"
DISTRIBUTION = "EEQ00Y93RTB1K"
GUARD_COMMIT = "0e2e79c30d13bab8dec41081ef4d273d826b127c"
GUARD_PATH = "kalshi_trade_infra/results/kalshi_bitcoin_perps_2026-10-23/operations/remote.py"
MAX_BUNDLE = 24 * 1024 * 1024


class RunnerError(RuntimeError):
    pass


def emit(kind, value):
    print("TAU_PERPS_RELEASE_" + kind + "=" + json.dumps(value, sort_keys=True), flush=True)


def git(*args):
    response = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, timeout=40)
    if response.returncode:
        raise RunnerError("git_reference_unavailable")
    return response.stdout


def aws(*args):
    response = subprocess.run(["aws", *args, "--region", REGION, "--output", "json"], capture_output=True, timeout=45)
    if response.returncode:
        raise RunnerError("aws_request_failed")
    return json.loads(response.stdout) if response.stdout.strip() else {}


def pins():
    value = json.loads((HERE / "pins.json").read_text())
    if (value.get("format") != 1 or not re.fullmatch(r"[0-9a-f]{40}", value.get("candidate", ""))
            or type(value.get("candidate_ready")) is not bool
            or remote.fingerprint(value["installed"]) != value["installed_fingerprint"]
            or not value["evidence"]["capture_reconstruction_proved"]):
        raise RunnerError("invalid_release_pins")
    if value["candidate_ready"]:
        accepted = value.get("acceptance", {})
        if (value["candidate"] == remote.REJECTED_CANDIDATE or accepted.get("candidate") != value["candidate"]
                or any(accepted.get(kind, {}).get("head_sha") != value["candidate"]
                       or accepted.get(kind, {}).get("conclusion") != "success" for kind in ("ci", "staging"))
                or not accepted.get("security", {}).get("root_confirmed_clean")):
            raise RunnerError("candidate_acceptance_gate_closed")
        if (not re.fullmatch(r"[0-9a-f]{40}", accepted.get("source_tree", ""))
                or not re.fullmatch(r"[0-9a-f]{40}", accepted.get("merged_main", {}).get("commit", ""))
                or any(accepted.get(kind, {}).get("tree") != accepted["source_tree"]
                       for kind in ("merged_main", "tested_synthetic_merge"))):
            raise RunnerError("source_provenance_not_pinned")
    return value


def bundle(value):
    # Git emits both complete packages, never the dirty operations checkout.
    tree = git("rev-parse", value["candidate"] + "^{tree}").decode().strip()
    if tree != value["acceptance"]["source_tree"]:
        raise RunnerError("candidate_tree_mismatch")
    archive = git("archive", "--format=tar.gz", value["candidate"] + ":kalshi_trade_infra", "app", "data_pipeline")
    remote.archive_files(archive, value)
    modules = {name: (HERE / (name + ".py")).read_text() for name in ("release_database", "release_schema", "remote", "capacity", "capacity_finalize")}
    modules["release_guard"] = git("show", GUARD_COMMIT + ":" + GUARD_PATH).decode()
    payload = {"format": 1, "pins": value, "archive": base64.b64encode(archive).decode(), "modules": modules}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_BUNDLE:
        raise RunnerError("release_bundle_limit")
    return raw


def program(artifact, phase, release_id):
    if (artifact["bucket"] != BUCKET or not re.fullmatch(r"bundle/manual-perps-[0-9a-f]{40}-[0-9a-f]{32}\.json", artifact["key"])
            or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) or phase not in {"inventory", "prepare", "apply", "capacity", "capacity_finalize"}
            or not re.fullmatch(r"[0-9a-f]{32}", release_id)):
        raise RunnerError("invalid_release_transport")
    code = '''import os,sys,json,types,subprocess,hashlib,base64,zlib
receipt_fd=os.dup(1);quiet=os.open(os.devnull,os.O_WRONLY)
os.dup2(quiet,1);os.dup2(quiet,2);os.close(quiet)
result={"status":"release_requires_inspection","error_code":"remote_bootstrap_failed"}
try:
 r=subprocess.run(["aws","s3","cp",S3,"-","--region","us-east-1","--no-progress","--only-show-errors"],capture_output=True,timeout=30)
 if r.returncode or len(r.stdout)>MAXIMUM or hashlib.sha256(r.stdout).hexdigest()!=SHA:raise ValueError()
 b=json.loads(r.stdout)
 if set(b)!={"format","pins","archive","modules"} or b["format"]!=1:raise ValueError()
 if set(b["modules"])!={"release_guard","release_database","release_schema","remote","capacity","capacity_finalize"}:raise ValueError()
 loaded={}
 for name in ("release_guard","release_database","release_schema","remote","capacity","capacity_finalize"):
  module=types.ModuleType(name);sys.modules[name]=module;exec(b["modules"][name],module.__dict__);loaded[name]=module
 loaded["capacity"].install_guard_exception(loaded["release_guard"])
 result=loaded["remote"].execute(PHASE,IDENTITY,b,loaded["release_guard"])
 if PHASE=="inventory":result["capacity_probe"]=loaded["capacity"].compatibility_probe(loaded["release_guard"])
except BaseException:pass
raw=json.dumps(result,sort_keys=True,separators=(",",":")).encode()
if len(raw)>65536:raw=b'{"status":"release_requires_inspection","error_code":"receipt_limit"}'
envelope={"encoding":"zlib+base64","sha256":hashlib.sha256(raw).hexdigest(),"payload":base64.b64encode(zlib.compress(raw)).decode()}
os.write(receipt_fd,(json.dumps(envelope)+"\\n").encode());os.close(receipt_fd)
'''.replace("S3", repr("s3://" + BUCKET + "/" + artifact["key"])).replace("MAXIMUM", str(MAX_BUNDLE)).replace("SHA", repr(artifact["sha256"]))
    code = code.replace("PHASE", repr(phase)).replace("IDENTITY", repr(release_id))
    return remote.PYTHON + " -I -B -c " + shlex.quote(code)


def decode(raw):
    if not isinstance(raw, str) or len(raw) > 24000:
        raise RunnerError("invalid_remote_receipt")
    value = json.loads(raw)
    if set(value) != {"encoding", "sha256", "payload"} or value["encoding"] != "zlib+base64":
        raise RunnerError("invalid_remote_receipt")
    inflater = zlib.decompressobj()
    content = inflater.decompress(base64.b64decode(value["payload"], validate=True), 65537)
    if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail or len(content) > 65536 or remote.digest(content) != value["sha256"]:
        raise RunnerError("invalid_remote_receipt")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise RunnerError("invalid_remote_receipt")
    return result


def request(artifact, phase, release_id):
    response = aws("ssm", "send-command", "--instance-ids", INSTANCE, "--document-name", "AWS-RunShellScript",
        "--comment", "Tau guarded manual perpetual release: " + phase,
        "--parameters", json.dumps({"commands": [program(artifact, phase, release_id)],
                                    "executionTimeout": ["480" if phase == "prepare" else "420" if phase == "apply" else "180"]}))
    command_id = response["Command"]["CommandId"]
    emit("PHASE", {"phase": phase, "ssm_command_id": command_id})
    deadline = time.monotonic() + (540 if phase == "prepare" else 480 if phase == "apply" else 240)
    while time.monotonic() < deadline:
        time.sleep(3)
        try:
            response = aws("ssm", "get-command-invocation", "--command-id", command_id, "--instance-id", INSTANCE)
        except RunnerError:
            continue
        if response.get("Status") in {"Success", "Failed", "TimedOut", "Cancelled"}:
            break
    if response.get("Status") != "Success":
        raise RunnerError("remote_release_outcome_requires_inspection")
    # Raw SSM stdout/stderr never enters Actions logs or artifact files.
    return decode(response.get("StandardOutputContent", ""))


def invalidate():
    result = aws("cloudfront", "create-invalidation", "--distribution-id", DISTRIBUTION, "--paths", "/*")
    identifier = result["Invalidation"]["Id"]
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = aws("cloudfront", "get-invalidation", "--distribution-id", DISTRIBUTION, "--id", identifier)
        if state["Invalidation"]["Status"] == "Completed":
            return {"completed": True, "invalidation_id": identifier, "path": "/*"}
        time.sleep(3)
    raise RunnerError("cdn_invalidation_pending")


def run(phase, expected_candidate=None, expected_fingerprint=None):
    value = pins()
    head = git("rev-parse", "HEAD").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head) or os.environ.get("GITHUB_SHA", head) != head:
        raise RunnerError("operations_head_mismatch")
    if phase not in {"inventory", "apply", "capacity", "capacity_finalize"}:
        raise RunnerError("invalid_release_phase")
    if phase in {"apply", "capacity", "capacity_finalize"} and (not value["candidate_ready"] or expected_candidate != value["candidate"]
                              or expected_fingerprint != value["installed_fingerprint"]):
        raise RunnerError("candidate_acceptance_gate_closed")
    if phase in {"apply", "capacity", "capacity_finalize"} and git("rev-parse", "refs/remotes/origin/main").decode().strip() != value["acceptance"]["merged_main"]["commit"]:
        raise RunnerError("reviewed_main_reference_changed")
    raw = bundle(value)
    release_id = uuid.uuid4().hex
    key = "bundle/manual-perps-" + value["candidate"] + "-" + release_id + ".json"
    artifact = {"bucket": BUCKET, "key": key, "sha256": remote.digest(raw)}
    emit("PREFLIGHT", {"operations_sha": head, "candidate": value["candidate"], "phase": phase,
        "expected_main_commit": value["acceptance"]["merged_main"]["commit"], "source_tree": value["acceptance"]["source_tree"],
        "release_id": release_id, "candidate_ready": value["candidate_ready"], "installed_fingerprint": value["installed_fingerprint"],
        "bundle_sha256": artifact["sha256"], "provider_calls_from_operations": 0})
    uploaded, committed, capacity_dispatched, capacity_verified = False, False, False, False
    finalize_dispatched, finalize_verified = False, False
    try:
        with tempfile.TemporaryDirectory(prefix="tau-perps-release-") as temporary:
            path = Path(temporary) / "public-source-bundle.json"
            path.write_bytes(raw)
            path.chmod(0o600)
            uploaded = True  # Even an uncertain Put must be cleared in finally.
            aws("s3api", "put-object", "--bucket", BUCKET, "--key", key, "--body", str(path), "--server-side-encryption", "AES256")
            if phase == "inventory":
                result = request(artifact, "inventory", release_id)
                emit("INVENTORY", result)
                return result
            if phase == "capacity":
                capacity_dispatched = True
                result = request(artifact, "capacity", release_id)
                capacity_verified = result.get("status") == "capacity_verified"
                emit("CAPACITY", result)
                return result
            if phase == "capacity_finalize":
                finalize_dispatched = True
                result = request(artifact, "capacity_finalize", release_id)
                finalize_verified = result.get("status") == "capacity_finalize_verified"
                emit("CAPACITY_FINALIZE", result)
                return result
            prepared = request(artifact, "prepare", release_id)
            emit("PREPARED", prepared)
            if prepared.get("status") != "prepared":
                return prepared
            emit("CDN_BEFORE", invalidate())
            result = request(artifact, "apply", release_id)
            emit("APPLY", result)
            if result.get("status") != "installed_verified" or result.get("admission_released") is not True:
                if result.get("status") == "rolled_back":
                    emit("CDN_ROLLBACK", invalidate())
                return result
            committed = True
            # New research can now start. Later edge failure never restarts or
            # rolls back services without another locked idle acceptance.
            try:
                cdn = invalidate()
                remote.verify_http(remote.PUBLIC, value, release_id)
                emit("PUBLIC", {"status": "accepted", "canonical": remote.PUBLIC,
                    "assets_match": True, "cdn": cdn, "production_provider_acceptance_tested": False})
                return {**result, "status": "accepted"}
            except Exception:
                partial = {"status": "partial_acceptance_requires_inspection", "candidate": value["candidate"],
                           "origin_and_onbox_public_verified": True, "admission_released": True,
                           "automatic_rollback_attempted": False, "error_code": "post_release_public_or_cdn_failed"}
                emit("PUBLIC", partial)
                return partial
    finally:
        if uploaded:
            # Existing IAM has Put/Get, not DeleteObject. Only public source is
            # transported; clear the current object without widening IAM.
            try:
                with tempfile.TemporaryDirectory(prefix="tau-perps-release-clear-") as temporary:
                    empty = Path(temporary) / "empty"
                    empty.write_bytes(b"")
                    aws("s3api", "put-object", "--bucket", BUCKET, "--key", key, "--body", str(empty), "--server-side-encryption", "AES256")
                head = aws("s3api", "head-object", "--bucket", BUCKET, "--key", key)
                if head.get("ContentLength") != 0 or head.get("ServerSideEncryption") != "AES256":
                    raise RunnerError("transport_cleanup_not_verified")
                emit("CLEANUP", {"current_transport_object_cleared": True, "historical_versions_deleted": False,
                                 "release_committed": committed, "capacity_action_dispatched": capacity_dispatched,
                                 "capacity_change_verified": capacity_verified,
                                 "capacity_finalize_dispatched": finalize_dispatched,
                                 "capacity_finalize_verified": finalize_verified})
            except Exception:
                emit("CLEANUP", {"current_transport_object_cleared": False, "historical_versions_deleted": False,
                                 "release_committed": committed, "capacity_action_dispatched": capacity_dispatched,
                                 "capacity_change_verified": capacity_verified,
                                 "capacity_finalize_dispatched": finalize_dispatched,
                                 "capacity_finalize_verified": finalize_verified})
                raise RunnerError("transport_cleanup_requires_inspection") from None


if __name__ == "__main__":
    try:
        phase = os.environ.get("TAU_PERPS_RELEASE_PHASE", "inventory")
        result = run(phase, os.environ.get("TAU_PERPS_RELEASE_CANDIDATE"), os.environ.get("TAU_PERPS_RELEASE_FINGERPRINT"))
        raise SystemExit(0 if result.get("status") in {"idle_inventory", "waiting", "accepted", "capacity_verified", "capacity_finalize_verified"} else 1)
    except SystemExit:
        raise
    except Exception as exc:
        emit("ERROR", {"status": "release_requires_inspection",
             "error_code": str(exc) if isinstance(exc, RunnerError) and re.fullmatch(r"[a-z0-9_]{1,80}", str(exc)) else "release_transport_failed"})
        raise SystemExit(1)
