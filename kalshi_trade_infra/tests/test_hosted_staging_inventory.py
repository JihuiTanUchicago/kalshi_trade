"""Projection and non-mutation contracts for hosted staging discovery."""
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hosted_inventory", ROOT / "staging/hosted_inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def run_probe(denied=False, account=None, simulate_error=None):
    calls = []

    def invoke(arguments):
        calls.append(arguments)
        if arguments == ("sts", "get-caller-identity"):
            return {"Account": account or inventory.EXPECTED_ACCOUNT,
                    "Arn": "arn:aws:iam::" + inventory.EXPECTED_ACCOUNT + ":user/private-user", "UserId": "secret-identity"}, None
        if arguments[:2] == ("iam", "simulate-principal-policy"):
            if simulate_error:
                return None, simulate_error
            return {"EvaluationResults": [{"EvalActionName": action, "EvalDecision": "implicitDeny",
                                           "MatchedStatements": ["do-not-project"]}
                                          for action in inventory.SIMULATED_ACTIONS]}, None
        if denied:
            return None, "UnauthorizedOperation" if arguments[0] == "ec2" else "AccessDenied"
        if arguments[0] == "cloudformation":
            return None, "ValidationError"
        if arguments[0] == "cloudfront":
            return [{"Id": "private-distribution", "DomainName": "private-domain"}], None
        return {"Reservations": [{"Instances": [{"InstanceId": "private-instance", "PrivateIpAddress": "private-ip"}]}],
                "Vpcs": [{"VpcId": "private-vpc"}], "Subnets": [{"SubnetId": "private-subnet"}]}, None

    return inventory.discover(invoke), calls


def test_expected_account_is_required_before_any_inventory():
    result, calls = run_probe(account="000000000001")
    assert len(calls) == 1
    assert result["pending_gate"] == "valid_expected_aws_account"


def test_inventory_is_read_only_and_never_sends_remote_commands():
    result, calls = run_probe()
    assert {call[:2] for call in calls} == {
        ("sts", "get-caller-identity"), ("ec2", "describe-instances"), ("ec2", "describe-vpcs"),
        ("ec2", "describe-subnets"), ("cloudformation", "describe-stacks"),
        ("cloudfront", "list-distributions"), ("iam", "simulate-principal-policy"),
    }
    assert result["resource_creation_requested"] is False
    assert result["production_commands_sent"] is False
    assert result["hosted_staging_ready"] is False


def test_missing_stack_is_not_an_inventory_permission_failure():
    result, _ = run_probe()
    assert result["status"] == "inventory_complete"
    assert result["checks"]["staging_stack"]["status"] == "not_found"
    assert result["checks"]["staging_instances"]["count"] == 1


def test_denied_inventory_is_a_pending_gate_not_hosted_acceptance():
    result, _ = run_probe(denied=True, simulate_error="AccessDenied")
    assert result["status"] == "blocked"
    assert result["pending_gate"] == "staging_inventory_permissions"
    assert len(result["unavailable_inventory_checks"]) == 5


def test_private_responses_and_principal_are_never_projected():
    result, _ = run_probe()
    text = json.dumps(result)
    for private in (inventory.EXPECTED_ACCOUNT, "private-user", "secret-identity", "do-not-project",
                    "private-distribution", "private-domain", "private-instance", "private-ip", "private-vpc"):
        assert private not in text
    assert result["permission_simulation"]["decisions"]["ec2:RunInstances"] == "implicitDeny"


def test_cli_failure_never_returns_raw_credentials_or_error_details(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 255, "secret-response", "An error occurred (AccessDenied) leaked-private-value")
    monkeypatch.setattr(inventory.subprocess, "run", fake_run)
    assert inventory.aws(("ec2", "describe-vpcs")) == (None, "AccessDenied")


def test_unknown_cli_error_is_sanitized(monkeypatch):
    monkeypatch.setattr(inventory.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 255, "private-value", "unexpected leaked-private-value"))
    assert inventory.aws(("ec2", "describe-vpcs")) == (None, "aws_request_failed")
