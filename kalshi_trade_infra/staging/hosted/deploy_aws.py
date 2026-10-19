"""Deploy only the independently bootstrapped staging stack using its OIDC role."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zlib

STACK = "tau-preproduction-staging"
REGION = "us-east-1"
ACCOUNT = "568386354218"
PRODUCTION_INSTANCE = "i-077d6f7873e7836ba"
PRODUCTION_BUCKET = "kalshi-trade-artifacts-568386354218-us-east-1"
PRODUCTION_DISTRIBUTION = "EEQ00Y93RTB1K"
PRODUCTION_ORIGIN = "https://d1gfpzcosqrjya.cloudfront.net"
HERE = Path(__file__).resolve().parent
RECEIPT = Path("hosted-staging-deploy.json")
ERROR_CODES = frozenset({"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "ValidationError",
                         "NoSuchKey", "InvalidInstanceId", "ParameterNotFound", "ThrottlingException"})


class DeployError(RuntimeError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise DeployError(code)


def aws(*arguments: str) -> dict:
    try:
        result = subprocess.run(["aws", *arguments, "--region", REGION, "--output", "json", "--no-cli-pager"],
                                capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        raise DeployError("aws_command_unavailable_or_timeout") from None
    if result.returncode:
        match = re.search(r"An error occurred \(([A-Za-z][A-Za-z0-9_.-]*)\)", result.stderr)
        code = match.group(1) if match and match.group(1) in ERROR_CODES else "request_failed"
        raise DeployError("aws_" + code)
    try:
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except ValueError:
        raise DeployError("invalid_aws_response") from None


def stack_target(stack: dict, identity: dict) -> dict:
    require(identity.get("Account") == ACCOUNT, "unexpected_aws_account")
    rows = stack.get("Stacks", [])
    require(len(rows) == 1 and rows[0].get("StackName") == STACK, "incorrect_staging_stack")
    require(rows[0].get("StackStatus") in ("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"),
            "staging_stack_not_stable")
    values = {item["OutputKey"]: item["OutputValue"] for item in rows[0].get("Outputs", [])}
    required = {"StagingInstanceId", "StagingArtifactBucket", "StagingDistributionId", "StagingUrl", "StagingDeployRoleArn"}
    require(required <= set(values), "missing_staging_stack_outputs")
    target = {"instance": values["StagingInstanceId"], "bucket": values["StagingArtifactBucket"],
              "distribution": values["StagingDistributionId"], "origin": values["StagingUrl"]}
    require(bool(re.fullmatch(r"i-[0-9a-f]{8,17}", target["instance"]))
            and target["instance"] != PRODUCTION_INSTANCE, "production_or_invalid_instance")
    require(bool(re.fullmatch(r"tau-preproduction-staging-[a-z0-9-]{3,40}", target["bucket"]))
            and target["bucket"] != PRODUCTION_BUCKET, "production_or_invalid_bucket")
    require(bool(re.fullmatch(r"[A-Z0-9]{8,32}", target["distribution"]))
            and target["distribution"] != PRODUCTION_DISTRIBUTION, "production_or_invalid_distribution")
    require(bool(re.fullmatch(r"https://[a-z0-9]+\.cloudfront\.net", target["origin"]))
            and target["origin"] != PRODUCTION_ORIGIN, "production_or_invalid_origin")
    role = values["StagingDeployRoleArn"]
    require(bool(re.fullmatch(r"arn:aws:iam::" + ACCOUNT + r":role/[A-Za-z0-9_+=,.@-]+", role)),
            "invalid_staging_deployment_role")
    role_name = role.rsplit("/", 1)[1]
    require(role_name.startswith("tau-preproduction-staging-"), "invalid_staging_deployment_role")
    require(identity.get("Arn", "").startswith("arn:aws:sts::" + ACCOUNT + ":assumed-role/" + role_name + "/"),
            "dedicated_staging_role_required")
    return target


def source_archive(source_sha: str) -> tuple[bytes, dict]:
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source_sha)), "exact_source_commit_required")
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15, check=True)
    require(result.stdout.strip() == source_sha, "checkout_source_mismatch")
    payload = subprocess.run(["git", "archive", "--format=tar.gz", source_sha + ":kalshi_trade_infra",
                              "app", "data_pipeline", "requirements.txt", "staging/hosted"],
                             capture_output=True, timeout=60, check=True).stdout
    import importlib.util
    import tarfile
    spec = importlib.util.spec_from_file_location("tau_staging_remote_guards", HERE / "deploy_remote.py")
    guards = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guards)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        guards.validate_members(archive)
        hashes = {}
        for path in ("app/static/app.js", "app/static/app.meridian.js", "app/static/alpaca-paper.js"):
            stream = archive.extractfile(path)
            require(stream is not None, "missing_frontend_asset")
            hashes["/static/" + Path(path).name] = hashlib.sha256(stream.read()).hexdigest()
    return payload, hashes


def upload(target: dict, key: str, payload: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="tau-staging-source-") as directory:
        path = Path(directory) / "source.tgz"
        path.write_bytes(payload)
        result = subprocess.run(["aws", "s3", "cp", str(path), "s3://" + target["bucket"] + "/" + key,
                                 "--region", REGION, "--sse", "AES256", "--only-show-errors"],
                                capture_output=True, timeout=120)
        require(result.returncode == 0, "staging_source_upload_failed")


def validated_receipt(receipt: dict, source_sha: str) -> dict:
    allowed = {"status", "source_sha", "production_changed", "research_worker_started", "provider_calls",
               "real_oauth_or_paper_order_accepted", "pending_gate", "full_schema_passed", "gateway_http_200",
               "secure_cookie_configuration", "development_login"}
    require(isinstance(receipt, dict) and not set(receipt) - allowed, "invalid_staging_remote_receipt")
    require(receipt.get("source_sha") == source_sha and receipt.get("production_changed") is False
            and receipt.get("research_worker_started") is False and receipt.get("provider_calls") == 0
            and receipt.get("real_oauth_or_paper_order_accepted") is False, "invalid_staging_remote_receipt")
    if receipt.get("status") == "pending_staging_configuration":
        require(receipt.get("pending_gate") == "staging_runtime_parameter", "invalid_staging_remote_receipt")
    elif receipt.get("status") == "staging_deployed_pending_user_acceptance":
        require(all(receipt.get(key) is True for key in
                    ("full_schema_passed", "gateway_http_200", "secure_cookie_configuration"))
                and receipt.get("development_login") is False and "pending_gate" not in receipt,
                "invalid_staging_remote_receipt")
    else:
        raise DeployError("staging_remote_operation_failed")
    require(all(isinstance(value, (str, bool, int)) for value in receipt.values()), "invalid_staging_remote_receipt")
    return receipt


def remote(target: dict, context: dict) -> dict:
    program = "TAU_STAGING_CONTEXT=" + repr(context) + "\n" + (HERE / "deploy_remote.py").read_text()
    # A future import must remain the first statement in the remote module.
    program = program.replace("from __future__ import annotations\n", "")
    packed = base64.b64encode(zlib.compress(program.encode())).decode()
    launcher = "import base64,zlib;exec(zlib.decompress(base64.b64decode(" + repr(packed) + ")))"
    command = "python3 -I -B -c " + shlex.quote(launcher)
    require(len(command) <= 16000, "staging_ssm_program_too_large")
    sent = aws("ssm", "send-command", "--instance-ids", target["instance"], "--document-name", "AWS-RunShellScript",
               "--comment", "Tau dedicated staging web deployment", "--parameters",
               json.dumps({"commands": [command], "executionTimeout": ["1800"]}))
    identifier = sent["Command"]["CommandId"]
    require(bool(re.fullmatch(r"[0-9a-f-]{36}", identifier)), "invalid_staging_command_identifier")
    # GetCommandInvocation cannot be scoped to staging and could expose production
    # command output. This role has no such permission: read only a fixed-schema
    # receipt from the private staging bucket instead.
    with tempfile.TemporaryDirectory(prefix="tau-staging-result-") as directory:
        path = Path(directory) / "receipt.json"
        for _ in range(360):
            time.sleep(5)
            listed = aws("s3api", "list-objects-v2", "--bucket", target["bucket"],
                         "--prefix", context["receipt_key"], "--max-keys", "1")
            if not any(row.get("Key") == context["receipt_key"] for row in listed.get("Contents", [])):
                continue
            aws("s3api", "get-object", "--bucket", target["bucket"], "--key", context["receipt_key"], str(path))
            require(path.stat().st_size <= 8192, "invalid_staging_remote_receipt")
            return validated_receipt(json.loads(path.read_text()), context["source_sha"])
    raise DeployError("staging_receipt_pending_inspect_existing_command_do_not_redispatch")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def public_checks(origin: str, expected_hashes: dict) -> dict:
    opener = urllib.request.build_opener(NoRedirect)
    statuses, hashes = {}, True
    for path in ("/", "/research", "/healthz", "/api/me", "/auth/dev", *expected_hashes):
        request = urllib.request.Request(origin + path, headers={"Cache-Control": "no-cache"})
        try:
            response = opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            statuses[path] = response.code
            if path in expected_hashes:
                hashes = hashes and hashlib.sha256(response.read(4 * 1024 * 1024)).hexdigest() == expected_hashes[path]
    accepted = (all(statuses[path] == 200 for path in ("/", "/research", "/healthz", *expected_hashes))
                and statuses["/api/me"] == 401 and statuses["/auth/dev"] in (403, 404) and hashes)
    return {"accepted": accepted, "http_statuses": statuses, "served_asset_hashes_match": hashes,
            "real_oauth_or_paper_order_accepted": False}


def deploy(source_sha: str) -> dict:
    # Build/validate source before touching the control plane.
    payload, hashes = source_archive(source_sha)
    target = stack_target(aws("cloudformation", "describe-stacks", "--stack-name", STACK), aws("sts", "get-caller-identity"))
    digest = hashlib.sha256(payload).hexdigest()
    context = {"source_sha": source_sha, "bundle_sha256": digest, "bucket": target["bucket"],
               "key": "releases/" + source_sha + "/" + digest + ".tgz", "origin": target["origin"],
               "receipt_key": "receipts/" + uuid.uuid4().hex + ".json"}
    upload(target, context["key"], payload)
    receipt = remote(target, context)
    if receipt["status"] == "pending_staging_configuration":
        return receipt
    aws("cloudfront", "create-invalidation", "--distribution-id", target["distribution"], "--paths", "/*")
    public = {"accepted": False}
    for attempt in range(6):
        try:
            public = public_checks(target["origin"], hashes)
        except (urllib.error.URLError, TimeoutError):
            public = {"accepted": False}
        if public["accepted"]:
            break
        if attempt < 5:
            time.sleep(7)
    require(public["accepted"], "public_staging_verification_failed")
    return {**receipt, "public_url": target["origin"], "public_checks": public}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy the independent Tau staging stack; never production.")
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args(argv)
    try:
        result = deploy(args.source_sha)
    except Exception as error:
        result = {"status": "staging_deployment_requires_inspection", "production_changed": False,
                  "error_code": str(error) if isinstance(error, DeployError) else "staging_operation_failed",
                  "real_oauth_or_paper_order_accepted": False}
    RECEIPT.write_text(json.dumps(result, indent=2) + "\n")
    print("TAU_HOSTED_STAGING_DEPLOY=" + json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "staging_deployed_pending_user_acceptance" else 1


if __name__ == "__main__":
    raise SystemExit(main())
