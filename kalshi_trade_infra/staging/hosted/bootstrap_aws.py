"""Owner-applied, stage-only AWS bootstrap. Importing it makes no AWS call.

`plan` inspects the owner's account and prepares a CREATE change set, never
executes it. `execute` accepts only that exact reviewed, add-only change set.
The GitHub deployment role has no permission to run this infrastructure bootstrap.
No production role, secret, network, database or running service is read or changed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

STACK_NAME = "tau-preproduction-staging"
REGION = "us-east-1"
EXPECTED_ACCOUNT = "568386354218"
REPOSITORY = "JihuiTanUchicago/kalshi_trade"
ENVIRONMENT = "staging"
ROLE_VARIABLE = "AWS_STAGING_ROLE_ARN"
RUNTIME_PARAMETER = "/tau/staging/hosted-runtime"
UBUNTU_AMI_PARAMETER = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
TEMPLATE = Path(__file__).with_name("aws_bootstrap.json")
TAGS = {"TauEnvironment": "staging", "TauProduct": "Tau", "TauManagedBy": "owner-bootstrap"}
PRICE_URLS = (
    "https://aws.amazon.com/vpc/pricing/",
    "https://aws.amazon.com/ec2/pricing/on-demand/",
    "https://aws.amazon.com/ebs/pricing/",
    "https://aws.amazon.com/cloudfront/pricing/",
    "https://aws.amazon.com/kms/pricing/",
    "https://aws.amazon.com/s3/pricing/",
)
COST_NOTICE = (
    "Creates billable dedicated staging resources, including one managed NAT Gateway "
    "(hourly and per-GB), its public IPv4 address, t3.medium (standard credits), "
    "16 GiB OS + retained 40 GiB gp3 data, retained KMS key, S3 and CloudFront. "
    "Stopping EC2 does not stop NAT, IPv4, EBS or KMS charges. "
    "Retained data volume, key and artifact bucket continue to incur charges after stack deletion. "
    "Review current us-east-1 pricing before executing; no price or spending cap is assumed."
)


class BootstrapError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class AwsError(BootstrapError):
    def __init__(self, code: str, *, missing: bool = False):
        super().__init__(code)
        self.missing = missing


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BootstrapError(code)


class Aws:
    """Capture CLI output in memory; never relay raw AWS errors or identity data."""

    def call(self, *args: str) -> dict:
        invocation = ["aws", "--region", REGION, "--output", "json", "--no-cli-pager", *args]
        env = dict(os.environ, AWS_PAGER="", AWS_CLI_AUTO_PROMPT="off")
        try:
            result = subprocess.run(invocation, capture_output=True, text=True, env=env,
                                    timeout=90, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise AwsError("aws_cli_unavailable_or_timed_out") from None
        if result.returncode:
            matched = re.search(r"An error occurred \(([A-Za-z0-9_.-]{1,80})\)", result.stderr)
            code = matched.group(1) if matched else "aws_cli_failed"
            missing = code == "NoSuchEntity" or (
                code == "ValidationError" and "does not exist" in result.stderr
            )
            raise AwsError(code, missing=missing)
        if not result.stdout.strip():
            return {}
        try:
            parsed = json.loads(result.stdout)
        except (ValueError, RecursionError):
            raise AwsError("aws_cli_response_invalid") from None
        require(isinstance(parsed, dict), "aws_cli_response_invalid")
        return parsed


def load_template() -> dict:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    scope = template.get("Metadata", {}).get("TauScope", {})
    require(scope.get("StackName") == STACK_NAME and scope.get("Region") == REGION
            and scope.get("GitHubRepository") == REPOSITORY
            and scope.get("GitHubEnvironment") == ENVIRONMENT
            and scope.get("NoProductionAccess") is True, "template_scope_invalid")
    require(len(TEMPLATE.read_bytes()) <= 51_200, "template_body_too_large")
    require(template.get("Parameters", {}).get("UbuntuAmi", {}).get("Default") == UBUNTU_AMI_PARAMETER,
            "canonical_ami_parameter_changed")
    return template


def template_digest(template: dict) -> str:
    raw = json.dumps(template, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def owner_account(aws: Aws) -> str:
    identity = aws.call("sts", "get-caller-identity")
    account = identity.get("Account", "")
    require(bool(re.fullmatch(r"[0-9]{12}", account)), "owner_account_invalid")
    require(account == EXPECTED_ACCOUNT, "owner_account_mismatch")
    require(str(identity.get("Arn", "")).startswith(f"arn:aws:"), "owner_partition_unsupported")
    return account


def private_origin_az(aws: Aws) -> str:
    zones = aws.call("ec2", "describe-availability-zones", "--filters", "Name=state,Values=available")
    choices = sorted(
        (zone["ZoneId"], zone["ZoneName"])
        for zone in zones.get("AvailabilityZones", [])
        if zone.get("State") == "available" and zone.get("ZoneType", "availability-zone") == "availability-zone"
        and re.fullmatch(r"us-east-1[a-z]", str(zone.get("ZoneName", "")))
        and re.fullmatch(r"use1-az[0-9]+", str(zone.get("ZoneId", "")))
        and zone.get("ZoneId") != "use1-az3"
    )
    require(bool(choices), "no_supported_cloudfront_vpc_origin_az")
    return choices[0][1]


def cloudfront_prefix_list(aws: Aws) -> str:
    result = aws.call("ec2", "describe-managed-prefix-lists", "--filters",
                      "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing")
    choices = [item["PrefixListId"] for item in result.get("PrefixLists", [])
               if item.get("OwnerId") == "AWS" and item.get("AddressFamily") == "IPv4"
               and item.get("PrefixListName") == "com.amazonaws.global.cloudfront.origin-facing"
               and re.fullmatch(r"pl-[a-f0-9]+", str(item.get("PrefixListId", "")))]
    require(len(choices) == 1, "cloudfront_prefix_list_ambiguous_or_missing")
    return choices[0]


def existing_oidc_provider(aws: Aws, account: str) -> str:
    arn = f"arn:aws:iam::{account}:oidc-provider/token.actions.githubusercontent.com"
    try:
        provider = aws.call("iam", "get-open-id-connect-provider", "--open-id-connect-provider-arn", arn)
    except AwsError as exc:
        if exc.code == "NoSuchEntity":
            return ""
        raise
    require(provider.get("Url") in ("token.actions.githubusercontent.com", "https://token.actions.githubusercontent.com")
            and "sts.amazonaws.com" in provider.get("ClientIDList", []), "existing_oidc_provider_incompatible")
    return arn


def require_new_stack(aws: Aws) -> None:
    try:
        aws.call("cloudformation", "describe-stacks", "--stack-name", STACK_NAME)
    except AwsError as exc:
        if exc.code == "ValidationError" and exc.missing:
            return
        raise
    raise BootstrapError("stack_already_exists_no_automatic_infrastructure_update")


def expected_parameters(aws: Aws, account: str) -> dict[str, str]:
    """Resolve owner-side choices again before execution, never trust user input."""
    return {
        "AvailabilityZone": private_origin_az(aws),
        "CloudFrontOriginFacingPrefixListId": cloudfront_prefix_list(aws),
        "ExistingGitHubOidcProviderArn": existing_oidc_provider(aws, account),
        "UbuntuAmi": UBUNTU_AMI_PARAMETER,
    }


def parameter_digest(values: dict[str, str]) -> str:
    raw = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def change_description(template_hash: str, parameters_hash: str) -> str:
    return (f"Tau staging owner-reviewed CREATE template_sha256={template_hash}; "
            f"parameters_sha256={parameters_hash}")


def reviewed_parameters(aws: Aws, account: str, response: dict) -> dict[str, str]:
    """Bind both the staged values and their fresh AWS-owned source metadata."""
    expected = expected_parameters(aws, account)
    parameters = response.get("Parameters")
    require(isinstance(parameters, list) and len(parameters) == len(expected),
            "change_set_parameters_missing_or_extra")
    values = {}
    for item in parameters:
        require(isinstance(item, dict) and item.get("ParameterKey") in expected,
                "change_set_parameter_unknown")
        key = item["ParameterKey"]
        require(key not in values and item.get("UsePreviousValue", False) is False,
                "change_set_parameter_reused_or_duplicate")
        require(isinstance(item.get("ParameterValue"), str), "change_set_parameter_value_invalid")
        values[key] = item["ParameterValue"]
        if key == "UbuntuAmi":
            # CloudFormation resolves this public Canonical SSM path when preparing
            # the change set; an arbitrary image parameter is never accepted.
            require(bool(re.fullmatch(r"ami-[a-f0-9]{8,17}", str(item.get("ResolvedValue", "")))),
                    "change_set_canonical_ami_resolution_invalid")
        else:
            require(not item.get("ResolvedValue"), "change_set_parameter_resolution_unexpected")
    require(values == expected, "change_set_parameter_choices_changed_or_invalid")
    return values


def plan(aws: Aws) -> dict:
    template = load_template()
    digest = template_digest(template)
    account = owner_account(aws)
    require_new_stack(aws)
    choices = expected_parameters(aws, account)
    parameters = [{"ParameterKey": key, "ParameterValue": value} for key, value in choices.items()]
    aws.call("cloudformation", "validate-template", "--template-body", f"file://{TEMPLATE.resolve()}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    change_set = f"tau-staging-{stamp}-{digest[:12]}"
    aws.call("cloudformation", "create-change-set", "--stack-name", STACK_NAME,
             "--change-set-name", change_set, "--change-set-type", "CREATE",
             "--description", change_description(digest, parameter_digest(choices)),
             "--template-body", f"file://{TEMPLATE.resolve()}",
             "--capabilities", "CAPABILITY_IAM", "--parameters", json.dumps(parameters),
             "--tags", json.dumps([{"Key": key, "Value": value} for key, value in TAGS.items()]))
    return {"status": "change_set_preparing_not_executed", "stack_name": STACK_NAME,
            "region": REGION, "change_set_name": change_set, "template_sha256": digest,
            "parameters_sha256": parameter_digest(choices),
            "cost_notice": COST_NOTICE, "pricing_references": PRICE_URLS,
            "review_command": f"python3 staging/hosted/bootstrap_aws.py review --change-set-name {change_set}",
            "execute_command": f"python3 staging/hosted/bootstrap_aws.py execute --change-set-name {change_set}",
            "application_status": "not_deployed", "production_changes": False}


def review(aws: Aws, change_set: str) -> dict:
    account = owner_account(aws)
    digest = template_digest(load_template())
    require(bool(re.fullmatch(r"tau-staging-[0-9]{8}-[0-9]{6}-" + digest[:12], change_set)),
            "change_set_name_or_template_digest_mismatch")
    response = aws.call("cloudformation", "describe-change-set", "--stack-name", STACK_NAME,
                        "--change-set-name", change_set)
    require(response.get("ChangeSetName") == change_set and response.get("StackName") == STACK_NAME,
            "change_set_scope_mismatch")
    require(response.get("Status") == "CREATE_COMPLETE" and response.get("ExecutionStatus") == "AVAILABLE",
            "change_set_not_available_for_review")
    choices = reviewed_parameters(aws, account, response)
    parameters_hash = parameter_digest(choices)
    require(response.get("Description") == change_description(digest, parameters_hash),
            "change_set_description_or_parameter_binding_mismatch")
    body = aws.call("cloudformation", "get-template", "--stack-name", STACK_NAME,
                    "--change-set-name", change_set, "--template-stage", "Original").get("TemplateBody")
    if isinstance(body, str):
        body = json.loads(body)
    require(isinstance(body, dict) and template_digest(body) == digest, "change_set_template_mismatch")
    require({item.get("Key"): item.get("Value") for item in response.get("Tags", [])} == TAGS,
            "change_set_tags_mismatch")
    changes = [item.get("ResourceChange", {}) for item in response.get("Changes", [])]
    require(bool(changes) and all(item.get("Action") == "Add" and not item.get("PhysicalResourceId")
                                  for item in changes), "change_set_must_only_add_new_staging_resources")
    # Initial CREATE has no prior app/volume to replace. Refuse UPDATE/IMPORT state.
    stacks = aws.call("cloudformation", "describe-stacks", "--stack-name", STACK_NAME).get("Stacks", [])
    require(len(stacks) == 1 and stacks[0].get("StackName") == STACK_NAME
            and stacks[0].get("StackStatus") == "REVIEW_IN_PROGRESS", "stack_not_new_review_placeholder")
    return {"status": "change_set_reviewed_not_executed", "stack_name": STACK_NAME,
            "change_set_name": change_set, "template_sha256": digest,
            "parameters_sha256": parameters_hash,
            "resources": [{"logical_id": item.get("LogicalResourceId"), "type": item.get("ResourceType"),
                           "action": item.get("Action")} for item in changes],
            "cost_notice": COST_NOTICE, "pricing_references": PRICE_URLS,
            "retained_resources": ["StagingDataVolume", "StagingRuntimeKmsKey", "StagingArtifactBucket",
                                   "GitHubOidcProvider (only if newly created)"],
            "production_changes": False}


def execute(aws: Aws, change_set: str) -> dict:
    reviewed = review(aws, change_set)
    aws.call("cloudformation", "execute-change-set", "--stack-name", STACK_NAME,
             "--change-set-name", change_set)
    return {"status": "infrastructure_creation_started", "stack_name": STACK_NAME,
            "template_sha256": reviewed["template_sha256"], "application_status": "not_deployed",
            "production_changes": False,
            "next_command": "python3 staging/hosted/bootstrap_aws.py outputs"}


def stack_outputs(aws: Aws) -> dict[str, str]:
    account = owner_account(aws)
    stacks = aws.call("cloudformation", "describe-stacks", "--stack-name", STACK_NAME).get("Stacks", [])
    require(len(stacks) == 1 and stacks[0].get("StackName") == STACK_NAME
            and stacks[0].get("StackStatus") in ("CREATE_COMPLETE", "UPDATE_COMPLETE"), "staging_stack_not_complete")
    require({item.get("Key"): item.get("Value") for item in stacks[0].get("Tags", [])} == TAGS,
            "staging_stack_identity_mismatch")
    values = {item.get("OutputKey"): item.get("OutputValue") for item in stacks[0].get("Outputs", [])}
    patterns = {
        "StagingInstanceId": r"i-[a-f0-9]{8,17}",
        "StagingArtifactBucket": r"tau-preproduction-staging-[a-z0-9-]{1,38}",
        "StagingDistributionId": r"[A-Z0-9]{8,24}",
        "StagingUrl": r"https://[a-z0-9]{8,40}\.cloudfront\.net",
        "StagingDeployRoleArn": rf"arn:aws:iam::{account}:role/tau-preproduction-staging-[A-Za-z0-9_-]+",
        "StagingRuntimeKmsKeyArn": rf"arn:aws:kms:{REGION}:{account}:key/[a-f0-9-]{{36}}",
    }
    require(all(isinstance(values.get(key), str) and re.fullmatch(pattern, values[key])
                for key, pattern in patterns.items()), "staging_stack_outputs_invalid")
    require(values.get("StagingRuntimeParameter") == RUNTIME_PARAMETER, "staging_runtime_parameter_mismatch")
    return {key: values[key] for key in (*patterns, "StagingRuntimeParameter")}


def outputs(aws: Aws) -> dict:
    values = stack_outputs(aws)
    return {"status": "infrastructure_only_not_application_ready", "outputs": values,
            "github_environment": ENVIRONMENT, "github_variable": ROLE_VARIABLE,
            "github_role_value": values["StagingDeployRoleArn"],
            "required_action": "Configure staging environment branch protection, dedicated OAuth callbacks and sandbox runtime; then run the staging-only workflow.",
            "production_changes": False}


def private_runtime(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) in (0o400, 0o600)
                and before.st_uid == os.getuid() and before.st_nlink == 1 and before.st_size <= 4096,
                "unsafe_operator_runtime_file")
        raw = os.read(descriptor, 4097)
        after = os.fstat(descriptor)
        signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        require(signature(before) == signature(after) and len(raw) == after.st_size,
                "operator_runtime_file_changed")
        return raw
    finally:
        os.close(descriptor)


def put_runtime(aws: Aws, path: Path) -> dict:
    """Validate dedicated sandbox configuration before its only secret-write API."""
    raw = private_runtime(path)
    spec = importlib.util.spec_from_file_location("tau_owner_hosted_runtime", Path(__file__).with_name("entrypoint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        values = module.validate_runtime(module.parse_runtime(raw))
    except Exception as exc:
        raise BootstrapError(getattr(exc, "code", "operator_runtime_invalid")) from None
    target = stack_outputs(aws)
    require(values["APP_PUBLIC_URL"] == target["StagingUrl"], "runtime_origin_does_not_match_staging_distribution")
    # Never put values in command arguments, a saved record, stdout or Actions logs.
    # The immutable private copy prevents a validated input being swapped before CLI reads it.
    descriptor, temporary = tempfile.mkstemp(prefix="tau-staging-runtime-", suffix=".json")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        result = aws.call("ssm", "put-parameter", "--name", RUNTIME_PARAMETER, "--type", "SecureString",
                          "--tier", "Standard", "--key-id", target["StagingRuntimeKmsKeyArn"],
                          "--data-type", "text", "--overwrite", "--value", f"file://{temporary}")
    finally:
        Path(temporary).unlink(missing_ok=True)
    require(isinstance(result.get("Version"), int), "runtime_parameter_receipt_invalid")
    return {"status": "staging_runtime_configured_not_provider_verified", "parameter": RUNTIME_PARAMETER,
            "version": result["Version"], "encrypted": True, "secret_values_printed": False,
            "production_changes": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preview", help="Offline scope/cost summary; makes no AWS call.")
    commands.add_parser("plan", help="Owner only: inspect account and prepare a CREATE change set without executing it.")
    for name in ("review", "execute"):
        command = commands.add_parser(name, help=f"Owner only: {name} an exact add-only CREATE change set.")
        command.add_argument("--change-set-name", required=True)
    commands.add_parser("outputs", help="Owner only: inspect the completed staging stack; no application-ready claim.")
    runtime = commands.add_parser("runtime", help="Owner only: put dedicated stage sandbox JSON into the exact SecureString parameter.")
    runtime.add_argument("--file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        aws = Aws()
        if args.command == "preview":
            result = {"status": "offline_preview", "stack_name": STACK_NAME, "region": REGION,
                      "template_sha256": template_digest(load_template()), "cost_notice": COST_NOTICE,
                      "pricing_references": PRICE_URLS, "aws_calls": 0, "production_changes": False}
        elif args.command == "plan":
            result = plan(aws)
        elif args.command == "review":
            result = review(aws, args.change_set_name)
        elif args.command == "execute":
            result = execute(aws, args.change_set_name)
        elif args.command == "outputs":
            result = outputs(aws)
        else:
            result = put_runtime(aws, args.file)
    except Exception as exc:
        code = exc.code if isinstance(exc, BootstrapError) else "owner_bootstrap_failed"
        print(json.dumps({"status": "blocked", "error_code": code,
                          "application_ready": False, "secret_values_printed": False}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
