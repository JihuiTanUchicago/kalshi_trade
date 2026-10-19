"""Read-only AWS readiness discovery. Never runs SSM commands or creates resources."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

REGION = "us-east-1"
EXPECTED_ACCOUNT = "568386354218"
STACK = "tau-preproduction-staging"
ALLOWED_ERRORS = frozenset({
    "AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "AuthFailure",
    "InvalidClientTokenId", "ExpiredToken", "ValidationError", "ResourceNotFoundException",
    "NoSuchEntity", "UnrecognizedClientException", "Throttling", "ThrottlingException",
})
SIMULATED_ACTIONS = (
    "ec2:RunInstances", "ec2:CreateVpc", "ec2:CreateSubnet", "ec2:CreateSecurityGroup",
    "ec2:CreateTags", "iam:CreateRole", "iam:PassRole", "cloudformation:CreateStack",
    "cloudformation:DescribeStacks", "cloudfront:CreateDistribution", "ssm:GetParameter",
)
READS = (
    ("staging_instances", ("ec2", "describe-instances", "--filters",
                           "Name=tag:TauEnvironment,Values=staging")),
    ("default_vpc", ("ec2", "describe-vpcs", "--filters", "Name=is-default,Values=true")),
    ("default_subnets", ("ec2", "describe-subnets", "--filters", "Name=default-for-az,Values=true")),
    ("staging_stack", ("cloudformation", "describe-stacks", "--stack-name", STACK)),
    ("staging_distributions", ("cloudfront", "list-distributions", "--query",
                              "DistributionList.Items[?Comment == 'Tau pre-production staging']")),
)


def aws(arguments: tuple[str, ...]) -> tuple[object | None, str | None]:
    """Keep all raw identity, metadata and error output private to this process."""
    try:
        result = subprocess.run(
            ["aws", *arguments, "--region", REGION, "--output", "json", "--no-cli-pager"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "AWS_PAGER": "", "AWS_CLI_AUTO_PROMPT": "off"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "aws_cli_unavailable_or_timeout"
    if result.returncode:
        match = re.search(r"An error occurred \(([A-Za-z][A-Za-z0-9_.-]*)\)", result.stderr)
        code = match.group(1) if match else "aws_request_failed"
        return None, code if code in ALLOWED_ERRORS else "aws_request_failed"
    try:
        return json.loads(result.stdout), None
    except (TypeError, ValueError):
        return None, "invalid_aws_response"


def count_items(name: str, value: object) -> int:
    if name == "staging_distributions":
        return len(value) if isinstance(value, list) else 0
    if not isinstance(value, dict):
        return 0
    if name == "staging_instances":
        return sum(len(item.get("Instances", [])) for item in value.get("Reservations", []))
    key = {"default_vpc": "Vpcs", "default_subnets": "Subnets", "staging_stack": "Stacks"}[name]
    return len(value.get(key, []))


def discover(invoke=aws) -> dict:
    receipt = {
        "schema": "tau.hosted_staging_inventory.v1", "mode": "read_only_control_plane",
        "region": REGION, "resource_creation_requested": False, "production_commands_sent": False,
        "provider_calls": 0, "credentials_or_identity_retained": False,
        "checks": {}, "permission_simulation": {}, "hosted_staging_ready": False,
    }
    identity, error = invoke(("sts", "get-caller-identity"))
    if error or not isinstance(identity, dict) or identity.get("Account") != EXPECTED_ACCOUNT:
        receipt.update(status="blocked", pending_gate="valid_expected_aws_account")
        receipt["checks"]["identity"] = {"status": "failed", "code": error or "unexpected_account"}
        return receipt
    receipt["checks"]["identity"] = {"status": "passed", "expected_account_matches": True}
    blocked = []
    for name, arguments in READS:
        value, error = invoke(arguments)
        if error:
            absent = name == "staging_stack" and error == "ValidationError"
            receipt["checks"][name] = {"status": "not_found" if absent else "unavailable", "code": error}
            if not absent:
                blocked.append(name)
        else:
            receipt["checks"][name] = {"status": "readable", "count": count_items(name, value)}
    principal = identity.get("Arn", "")
    # The IAM simulation requires an IAM principal ARN, not an STS session ARN.
    if re.fullmatch(r"arn:aws:iam::[0-9]{12}:user/[A-Za-z0-9+=,.@_/-]+", principal):
        value, error = invoke(("iam", "simulate-principal-policy", "--policy-source-arn", principal,
                               "--action-names", *SIMULATED_ACTIONS, "--resource-arns", "*"))
        if error:
            receipt["permission_simulation"] = {"status": "unavailable", "code": error}
        elif isinstance(value, dict):
            decisions = {}
            for row in value.get("EvaluationResults", []):
                action, decision = row.get("EvalActionName"), row.get("EvalDecision")
                if action in SIMULATED_ACTIONS and decision in ("allowed", "implicitDeny", "explicitDeny"):
                    decisions[action] = decision
            receipt["permission_simulation"] = {
                "status": "observed", "decisions": decisions,
                "scope": "wildcard_resource_simulation_not_actual_provisioning_acceptance",
            }
    else:
        receipt["permission_simulation"] = {"status": "not_supported_for_session_principal"}
    receipt.update(
        status="blocked" if blocked else "inventory_complete",
        pending_gate="staging_inventory_permissions" if blocked else "reviewed_staging_provisioning_and_configuration",
        unavailable_inventory_checks=blocked,
    )
    return receipt


def main() -> int:
    receipt = discover()
    # This fixed file contains deliberately projected fields only; no raw API
    # response, subprocess output, ARN, account id, secret, IP or environment.
    Path("hosted-staging-inventory.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("TAU_HOSTED_STAGING_INVENTORY=" + json.dumps(receipt, separators=(",", ":")))
    return 0 if receipt["checks"].get("identity", {}).get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
