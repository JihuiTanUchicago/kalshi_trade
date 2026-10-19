"""Offline owner-bootstrap and IAM boundary checks. No AWS or provider request."""
from __future__ import annotations

from copy import deepcopy
import fnmatch
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

FOLDER = Path(__file__).resolve().parents[1] / "staging" / "hosted"
SPEC = importlib.util.spec_from_file_location("tau_test_hosted_aws_bootstrap", FOLDER / "bootstrap_aws.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)

ACCOUNT = bootstrap.EXPECTED_ACCOUNT
RUNTIME_ARN = f"arn:aws:ssm:us-east-1:{ACCOUNT}:parameter/tau/staging/hosted-runtime"
KEY_ARN = f"arn:aws:kms:us-east-1:{ACCOUNT}:key/12345678-1234-1234-1234-123456789abc"
STAGE_URL = "https://d0123456789abc.cloudfront.net"


class FakeAws:
    def __init__(self, overrides=None):
        self.calls = []
        self.overrides = overrides or {}

    def call(self, *args):
        self.calls.append(args)
        action = args[:2]
        if action in self.overrides:
            result = self.overrides[action]
            if isinstance(result, Exception):
                raise result
            return deepcopy(result(args) if callable(result) else result)
        if action == ("sts", "get-caller-identity"):
            return {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/fixture-owner"}
        if action == ("cloudformation", "describe-stacks"):
            raise bootstrap.AwsError("ValidationError", missing=True)
        if action == ("ec2", "describe-availability-zones"):
            return {"AvailabilityZones": [
                {"ZoneName": "us-east-1a", "ZoneId": "use1-az3", "State": "available"},
                {"ZoneName": "us-east-1b", "ZoneId": "use1-az2", "State": "available"},
            ]}
        if action == ("ec2", "describe-managed-prefix-lists"):
            return {"PrefixLists": [{"PrefixListId": "pl-123abc", "OwnerId": "AWS", "AddressFamily": "IPv4",
                                     "PrefixListName": "com.amazonaws.global.cloudfront.origin-facing"}]}
        if action == ("iam", "get-open-id-connect-provider"):
            return {"Url": "token.actions.githubusercontent.com", "ClientIDList": ["sts.amazonaws.com"]}
        if action in (("cloudformation", "validate-template"), ("cloudformation", "create-change-set"),
                      ("cloudformation", "execute-change-set")):
            return {}
        if action == ("ssm", "put-parameter"):
            return {"Version": 1}
        raise AssertionError(f"Unexpected offline AWS operation: {action}")


def output_fixture():
    values = {
        "StagingInstanceId": "i-0123456789abcdef0",
        "StagingArtifactBucket": "tau-preproduction-staging-artifacts-fixture",
        "StagingDistributionId": "E123456789ABC",
        "StagingUrl": STAGE_URL,
        "StagingDeployRoleArn": f"arn:aws:iam::{ACCOUNT}:role/tau-preproduction-staging-DeployRole-fixture",
        "StagingRuntimeKmsKeyArn": KEY_ARN,
        "StagingRuntimeParameter": "/tau/staging/hosted-runtime",
    }
    return {"Stacks": [{"StackName": bootstrap.STACK_NAME, "StackStatus": "CREATE_COMPLETE",
                        "Tags": [{"Key": key, "Value": value} for key, value in bootstrap.TAGS.items()],
                        "Outputs": [{"OutputKey": key, "OutputValue": value} for key, value in values.items()]}]}


def review_fixture():
    digest = bootstrap.template_digest(bootstrap.load_template())
    name = f"tau-staging-20261019-120000-{digest[:12]}"
    choices = {
        "AvailabilityZone": "us-east-1b", "CloudFrontOriginFacingPrefixListId": "pl-123abc",
        "ExistingGitHubOidcProviderArn": f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com",
        "UbuntuAmi": bootstrap.UBUNTU_AMI_PARAMETER,
    }
    response = {
        "StackName": bootstrap.STACK_NAME, "ChangeSetName": name,
        "Description": bootstrap.change_description(digest, bootstrap.parameter_digest(choices)),
        "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE",
        "Parameters": [{"ParameterKey": key, "ParameterValue": value,
                        **({"ResolvedValue": "ami-0123456789abcdef0"} if key == "UbuntuAmi" else {})}
                       for key, value in choices.items()],
        "Tags": [{"Key": key, "Value": value} for key, value in bootstrap.TAGS.items()],
        "Changes": [{"ResourceChange": {"Action": "Add", "LogicalResourceId": "Vpc", "ResourceType": "AWS::EC2::VPC"}}],
    }
    return name, response


def review_aws(response=None, template=None):
    name, original = review_fixture()
    return name, FakeAws({
        ("cloudformation", "describe-change-set"): response or original,
        ("cloudformation", "get-template"): {"TemplateBody": template or bootstrap.load_template()},
        ("cloudformation", "describe-stacks"): {"Stacks": [{"StackName": bootstrap.STACK_NAME, "StackStatus": "REVIEW_IN_PROGRESS"}]},
    })


def test_plan_prepares_new_resources_but_never_executes_or_changes_existing_oidc():
    aws = FakeAws()
    result = bootstrap.plan(aws)
    assert result["status"] == "change_set_preparing_not_executed"
    assert result["production_changes"] is False
    actions = [args[:2] for args in aws.calls]
    assert ("cloudformation", "create-change-set") in actions
    assert ("cloudformation", "execute-change-set") not in actions
    assert not any(service == "iam" and operation != "get-open-id-connect-provider" for service, operation in actions)
    create = next(args for args in aws.calls if args[:2] == ("cloudformation", "create-change-set"))
    parameters = {item["ParameterKey"]: item["ParameterValue"] for item in json.loads(create[create.index("--parameters") + 1])}
    assert parameters["AvailabilityZone"] == "us-east-1b"  # AZ name alone cannot establish support.
    assert parameters["ExistingGitHubOidcProviderArn"].endswith("oidc-provider/token.actions.githubusercontent.com")
    assert parameters["UbuntuAmi"] == bootstrap.UBUNTU_AMI_PARAMETER
    assert create[create.index("--change-set-type") + 1] == "CREATE"


def test_only_no_such_entity_allows_new_oidc_provider():
    aws = FakeAws({("iam", "get-open-id-connect-provider"): bootstrap.AwsError("NoSuchEntity", missing=True)})
    bootstrap.plan(aws)
    create = next(args for args in aws.calls if args[:2] == ("cloudformation", "create-change-set"))
    parameters = {item["ParameterKey"]: item["ParameterValue"] for item in json.loads(create[create.index("--parameters") + 1])}
    assert parameters["ExistingGitHubOidcProviderArn"] == ""
    denied = FakeAws({("iam", "get-open-id-connect-provider"): bootstrap.AwsError("AccessDenied")})
    with pytest.raises(bootstrap.AwsError, match="AccessDenied"):
        bootstrap.plan(denied)
    assert not any(args[:2] == ("cloudformation", "create-change-set") for args in denied.calls)


@pytest.mark.parametrize("response", [
    {"Url": "token.actions.githubusercontent.com", "ClientIDList": ["other-audience"]},
    {"Url": "unrelated.invalid", "ClientIDList": ["sts.amazonaws.com"]},
])
def test_existing_oidc_incompatibility_never_updates_that_provider(response):
    aws = FakeAws({("iam", "get-open-id-connect-provider"): response})
    with pytest.raises(bootstrap.BootstrapError, match="existing_oidc_provider_incompatible"):
        bootstrap.plan(aws)
    assert all(args[:2] != ("cloudformation", "create-change-set") for args in aws.calls)


def test_existing_stack_cannot_be_overwritten_by_bootstrap():
    aws = FakeAws({("cloudformation", "describe-stacks"): output_fixture()})
    with pytest.raises(bootstrap.BootstrapError, match="stack_already_exists"):
        bootstrap.plan(aws)
    assert [args[:2] for args in aws.calls] == [("sts", "get-caller-identity"), ("cloudformation", "describe-stacks")]


def test_wrong_owner_account_fails_before_provisioning_or_secret_mutation():
    aws = FakeAws({("sts", "get-caller-identity"): {
        "Account": "111111111111", "Arn": "arn:aws:iam::111111111111:user/wrong-account",
    }})
    with pytest.raises(bootstrap.BootstrapError, match="owner_account_mismatch"):
        bootstrap.plan(aws)
    assert [args[:2] for args in aws.calls] == [("sts", "get-caller-identity")]


@pytest.mark.parametrize("operation", ["review", "execute", "outputs", "runtime"])
def test_every_owner_operation_rejects_wrong_profile_before_mutation(tmp_path, operation):
    aws = FakeAws({("sts", "get-caller-identity"): {
        "Account": "111111111111", "Arn": "arn:aws:iam::111111111111:user/wrong-account",
    }})
    name, _ = review_fixture()
    with pytest.raises(bootstrap.BootstrapError, match="owner_account_mismatch"):
        if operation in ("review", "execute"):
            getattr(bootstrap, operation)(aws, name)
        elif operation == "outputs":
            bootstrap.outputs(aws)
        else:
            bootstrap.put_runtime(aws, write_runtime(tmp_path / "runtime.json"))
    assert [args[:2] for args in aws.calls] == [("sts", "get-caller-identity")]


def test_access_denied_is_not_treated_as_resource_absence():
    aws = FakeAws({("cloudformation", "describe-stacks"): bootstrap.AwsError("AccessDenied")})
    with pytest.raises(bootstrap.AwsError, match="AccessDenied"):
        bootstrap.plan(aws)
    assert not any(args[:2] == ("cloudformation", "create-change-set") for args in aws.calls)


def test_vpc_origin_requires_supported_az_id_and_aws_owned_ipv4_prefix_list():
    aws = FakeAws({("ec2", "describe-availability-zones"): {"AvailabilityZones": [
        {"ZoneName": "us-east-1a", "ZoneId": "use1-az3", "State": "available"},
        {"ZoneName": "us-east-1b", "ZoneId": "use1-az2", "State": "unavailable"},
    ]}})
    with pytest.raises(bootstrap.BootstrapError, match="no_supported_cloudfront"):
        bootstrap.private_origin_az(aws)
    malicious = FakeAws({("ec2", "describe-managed-prefix-lists"): {"PrefixLists": [
        {"PrefixListId": "pl-123abc", "OwnerId": ACCOUNT, "AddressFamily": "IPv4",
         "PrefixListName": "com.amazonaws.global.cloudfront.origin-facing"},
    ]}})
    with pytest.raises(bootstrap.BootstrapError, match="prefix_list"):
        bootstrap.cloudfront_prefix_list(malicious)


def test_execution_requires_reviewed_unchanged_add_only_create():
    name, aws = review_aws()
    result = bootstrap.execute(aws, name)
    assert result["status"] == "infrastructure_creation_started"
    assert result["application_status"] == "not_deployed"
    assert aws.calls[-1][:2] == ("cloudformation", "execute-change-set")


@pytest.mark.parametrize("mutation,expected", [
    (lambda response: response.update(StackName="production"), "scope_mismatch"),
    (lambda response: response.update(ExecutionStatus="EXECUTE_COMPLETE"), "not_available"),
    (lambda response: response.update(Tags=[]), "tags_mismatch"),
    (lambda response: response["Changes"][0]["ResourceChange"].update(Action="Modify"), "only_add"),
    (lambda response: response["Changes"][0]["ResourceChange"].update(PhysicalResourceId="existing-resource"), "only_add"),
])
def test_execute_rejects_conflicting_or_non_create_change_set(mutation, expected):
    name, response = review_fixture()
    mutation(response)
    _, aws = review_aws(response=response)
    with pytest.raises(bootstrap.BootstrapError, match=expected):
        bootstrap.execute(aws, name)
    assert not any(args[:2] == ("cloudformation", "execute-change-set") for args in aws.calls)


def test_change_set_template_and_new_stack_state_are_verified_before_execution():
    altered = bootstrap.load_template()
    altered["Description"] = "Changed after review"
    name, aws = review_aws(template=altered)
    with pytest.raises(bootstrap.BootstrapError, match="template_mismatch"):
        bootstrap.execute(aws, name)
    name, aws = review_aws()
    aws.overrides[("cloudformation", "describe-stacks")] = output_fixture()
    with pytest.raises(bootstrap.BootstrapError, match="not_new_review_placeholder"):
        bootstrap.execute(aws, name)


@pytest.mark.parametrize("field,value", [
    ("AvailabilityZone", "us-east-1a"),  # Stable ID use1-az3 is unsupported, even though name looks ordinary.
    ("CloudFrontOriginFacingPrefixListId", "pl-999aaa"),
    ("ExistingGitHubOidcProviderArn", "arn:aws:iam::111111111111:oidc-provider/token.actions.githubusercontent.com"),
    ("ExistingGitHubOidcProviderArn", ""),  # An existing provider must be reused, never recreated.
    ("UbuntuAmi", "/untrusted/ami"),
])
def test_execution_revalidates_actual_change_set_parameter_choices(field, value):
    name, response = review_fixture()
    for parameter in response["Parameters"]:
        if parameter["ParameterKey"] == field:
            parameter["ParameterValue"] = value
    _, aws = review_aws(response=response)
    with pytest.raises(bootstrap.BootstrapError, match="parameter_choices_changed_or_invalid"):
        bootstrap.execute(aws, name)
    assert not any(args[:2] == ("cloudformation", "execute-change-set") for args in aws.calls)


@pytest.mark.parametrize("mutation,expected", [
    (lambda parameters: parameters.pop(), "missing_or_extra"),
    (lambda parameters: parameters.append({"ParameterKey": "ProductionVpc", "ParameterValue": "vpc-123"}), "missing_or_extra"),
    (lambda parameters: parameters[0].update(UsePreviousValue=True), "reused_or_duplicate"),
    (lambda parameters: parameters[1].update(ParameterKey=parameters[0]["ParameterKey"]), "reused_or_duplicate"),
    (lambda parameters: parameters[-1].update(ResolvedValue="ami-untrusted"), "ami_resolution_invalid"),
])
def test_parameters_cannot_be_missing_extra_reused_duplicate_or_unresolved(mutation, expected):
    name, response = review_fixture()
    mutation(response["Parameters"])
    _, aws = review_aws(response=response)
    with pytest.raises(bootstrap.BootstrapError, match=expected):
        bootstrap.execute(aws, name)
    assert not any(args[:2] == ("cloudformation", "execute-change-set") for args in aws.calls)


def test_parameters_are_cryptographically_bound_to_the_prepared_change_set_description():
    name, response = review_fixture()
    response["Description"] = bootstrap.change_description(
        bootstrap.template_digest(bootstrap.load_template()), "0" * 64,
    )
    _, aws = review_aws(response=response)
    with pytest.raises(bootstrap.BootstrapError, match="parameter_binding_mismatch"):
        bootstrap.execute(aws, name)


def test_owner_execution_rechecks_aws_metadata_before_executing():
    name, aws = review_aws()
    aws.overrides[("ec2", "describe-managed-prefix-lists")] = {"PrefixLists": [{
        "PrefixListId": "pl-123abc", "OwnerId": ACCOUNT, "AddressFamily": "IPv4",
        "PrefixListName": "com.amazonaws.global.cloudfront.origin-facing",
    }]}
    with pytest.raises(bootstrap.BootstrapError, match="prefix_list_ambiguous_or_missing"):
        bootstrap.execute(aws, name)
    assert not any(args[:2] == ("cloudformation", "execute-change-set") for args in aws.calls)


def test_missing_oidc_provider_is_checked_again_and_must_match_create_choice():
    name, response = review_fixture()
    for parameter in response["Parameters"]:
        if parameter["ParameterKey"] == "ExistingGitHubOidcProviderArn":
            parameter["ParameterValue"] = ""
    choices = {item["ParameterKey"]: item["ParameterValue"] for item in response["Parameters"]}
    response["Description"] = bootstrap.change_description(
        bootstrap.template_digest(bootstrap.load_template()), bootstrap.parameter_digest(choices),
    )
    _, aws = review_aws(response=response)
    aws.overrides[("iam", "get-open-id-connect-provider")] = bootstrap.AwsError("NoSuchEntity", missing=True)
    assert bootstrap.execute(aws, name)["status"] == "infrastructure_creation_started"


def runtime_fixture():
    return {
        "APP_PUBLIC_URL": STAGE_URL, "GOOGLE_CLIENT_ID": "0123456789-abcdefghijklmnopqrstuvwxyz.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "GOCSPX_abcdefghijklmno", "ALPACA_OAUTH_CLIENT_ID": "FixtureClient123456789",
        "ALPACA_OAUTH_CLIENT_SECRET": "FixtureSecret123456789", "TAU_ADMIN_EMAIL": "fixture@example.com",
        "STRIPE_SECRET_KEY": "sk_test_" + "x" * 24, "STRIPE_PUBLISHABLE_KEY": "pk_test_" + "y" * 24,
        "STRIPE_WEBHOOK_SECRET": "whsec_" + "z" * 24,
    }


def write_runtime(path, values=None, mode=0o600):
    path.write_text(json.dumps(values or runtime_fixture()))
    path.chmod(mode)
    return path


def test_runtime_write_uses_private_immutable_file_not_cli_value_and_cleans_up(tmp_path):
    path = write_runtime(tmp_path / "runtime.json")
    captured = []

    def capture(args):
        raw_arg = args[args.index("--value") + 1]
        assert raw_arg.startswith("file://")
        temporary = Path(raw_arg.removeprefix("file://"))
        assert temporary != path
        assert stat_mode(temporary) == 0o600
        assert json.loads(temporary.read_bytes()) == runtime_fixture()
        assert not any(value in " ".join(args) for value in runtime_fixture().values())
        captured.append(temporary)
        return {"Version": 4}

    aws = FakeAws({("cloudformation", "describe-stacks"): output_fixture(), ("ssm", "put-parameter"): capture})
    result = bootstrap.put_runtime(aws, path)
    assert result["version"] == 4 and result["encrypted"] is True
    assert result["status"] == "staging_runtime_configured_not_provider_verified"
    assert all(not temporary.exists() for temporary in captured)
    assert "FixtureSecret" not in json.dumps(result)


def stat_mode(path):
    return path.stat().st_mode & 0o777


@pytest.mark.parametrize("kind", ["permissive", "symlink", "hardlink", "oversize"])
def test_unsafe_runtime_files_make_no_aws_call(tmp_path, kind):
    path = write_runtime(tmp_path / "runtime.json")
    if kind == "permissive":
        path.chmod(0o644)
    elif kind == "symlink":
        link = tmp_path / "runtime-link.json"
        link.symlink_to(path)
        path = link
    elif kind == "hardlink":
        os.link(path, tmp_path / "other.json")
    else:
        path.write_bytes(b"x" * 4097)
    aws = FakeAws()
    with pytest.raises((bootstrap.BootstrapError, OSError)):
        bootstrap.put_runtime(aws, path)
    assert aws.calls == []


@pytest.mark.parametrize("field,value", [
    ("APP_PUBLIC_URL", "https://d1gfpzcosqrjya.cloudfront.net"),
    ("APP_PUBLIC_URL", "https://different1234.cloudfront.net"),
    ("STRIPE_SECRET_KEY", "sk_live_" + "x" * 24),
    ("APP_DEV_LOGIN", "1"),
    ("MYSQL_HOST", "production-host"),
])
def test_runtime_cannot_target_production_or_activate_live_billing_or_inherit_database(tmp_path, field, value):
    values = runtime_fixture()
    values[field] = value
    path = write_runtime(tmp_path / "runtime.json", values)
    aws = FakeAws({("cloudformation", "describe-stacks"): output_fixture()})
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.put_runtime(aws, path)
    assert not any(args[:2] == ("ssm", "put-parameter") for args in aws.calls)


def test_outputs_from_other_stack_or_role_are_rejected():
    response = output_fixture()
    response["Stacks"][0]["Tags"] = []
    aws = FakeAws({("cloudformation", "describe-stacks"): response})
    with pytest.raises(bootstrap.BootstrapError, match="identity_mismatch"):
        bootstrap.outputs(aws)
    response = output_fixture()
    for item in response["Stacks"][0]["Outputs"]:
        if item["OutputKey"] == "StagingDeployRoleArn":
            item["OutputValue"] = f"arn:aws:iam::{ACCOUNT}:role/ProductionDeploy"
    with pytest.raises(bootstrap.BootstrapError, match="outputs_invalid"):
        bootstrap.outputs(FakeAws({("cloudformation", "describe-stacks"): response}))


def resolve(value):
    refs = {"AWS::Partition": "aws", "AWS::Region": "us-east-1", "AWS::AccountId": ACCOUNT,
            "AWS::StackName": bootstrap.STACK_NAME, "StagingInstance": "i-0123456789abcdef0",
            "StagingDistribution": "E123456789ABC"}
    attributes = {"StagingArtifactBucket.Arn": "arn:aws:s3:::tau-preproduction-staging-artifacts-fixture",
                  "StagingRuntimeKmsKey.Arn": KEY_ARN}
    if isinstance(value, list):
        return [resolve(item) for item in value]
    if isinstance(value, dict):
        if "Ref" in value:
            return refs[value["Ref"]]
        if "Fn::GetAtt" in value:
            return attributes[".".join(value["Fn::GetAtt"])]
        if "Fn::Sub" in value:
            return re.sub(r"\$\{([^}]+)\}", lambda match: {**refs, **attributes}[match.group(1)], value["Fn::Sub"])
        return {key: resolve(item) for key, item in value.items()}
    return value


def allows(statements, action, resource, context=None):
    context = context or {}
    for statement in statements:
        actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        resources = statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]
        if not any(fnmatch.fnmatchcase(action, item) for item in actions):
            continue
        if not any(fnmatch.fnmatchcase(resource, item) for item in resources):
            continue
        matches = True
        for operator, checks in statement.get("Condition", {}).items():
            for key, expected in checks.items():
                permitted = expected if isinstance(expected, list) else [expected]
                actual = context.get(key, "")
                if operator == "StringEquals":
                    matches &= actual in permitted
                elif operator == "StringLike":
                    matches &= any(fnmatch.fnmatchcase(actual, item) for item in permitted)
                else:
                    raise AssertionError(f"Test evaluator must handle new IAM condition {operator}")
        if matches and statement["Effect"] == "Allow":
            return True
    return False


def role_permissions(role):
    resources = bootstrap.load_template()["Resources"]
    return resolve(resources[role]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"])


def test_deployment_role_allows_exact_stage_targets_and_denies_production_or_provisioning():
    statements = role_permissions("StagingDeployRole")
    stage_instance = f"arn:aws:ec2:us-east-1:{ACCOUNT}:instance/i-0123456789abcdef0"
    context = {"ssm:resourceTag/TauEnvironment": "staging", "ssm:resourceTag/TauProduct": "Tau"}
    assert allows(statements, "ssm:SendCommand", stage_instance, context)
    assert not allows(statements, "ssm:SendCommand", stage_instance)
    assert not allows(statements, "ssm:SendCommand", f"arn:aws:ec2:us-east-1:{ACCOUNT}:instance/i-077d6f7873e7836ba", context)
    assert allows(statements, "ssm:GetParameter", RUNTIME_ARN)
    assert allows(statements, "ssm:PutParameter", RUNTIME_ARN)
    assert not allows(statements, "ssm:GetParameter", f"arn:aws:ssm:us-east-1:{ACCOUNT}:parameter/tau/production/runtime")
    assert allows(statements, "s3:PutObject", "arn:aws:s3:::tau-preproduction-staging-artifacts-fixture/releases/commit.tar.gz")
    assert not allows(statements, "s3:PutObject", "arn:aws:s3:::production-artifacts/releases/commit.tar.gz")
    assert not allows(statements, "s3:PutObject", "arn:aws:s3:::tau-preproduction-staging-artifacts-fixture/secrets/runtime.json")
    assert allows(statements, "cloudfront:CreateInvalidation", f"arn:aws:cloudfront::{ACCOUNT}:distribution/E123456789ABC")
    assert not allows(statements, "cloudfront:CreateInvalidation", f"arn:aws:cloudfront::{ACCOUNT}:distribution/EEQ00Y93RTB1K")
    for action in ("iam:PassRole", "iam:CreateRole", "sts:AssumeRole", "ec2:RunInstances", "cloudformation:CreateStack",
                   "cloudformation:ExecuteChangeSet", "ssm:StartSession", "ssm:GetParametersByPath",
                   "ssm:GetCommandInvocation", "ec2:DescribeInstances"):
        assert not allows(statements, action, "*")
    stage_stack = f"arn:aws:cloudformation:us-east-1:{ACCOUNT}:stack/tau-preproduction-staging/fixture"
    assert allows(statements, "cloudformation:DescribeStacks", stage_stack)
    assert not allows(statements, "cloudformation:DescribeStacks", stage_stack.replace("tau-preproduction-staging", "production"))


def test_host_role_and_kms_cannot_read_production_parameters_or_decrypt_other_contexts():
    host = role_permissions("StagingInstanceRole")
    deploy = role_permissions("StagingDeployRole")
    context = {"kms:ViaService": "ssm.us-east-1.amazonaws.com", "kms:EncryptionContext:PARAMETER_ARN": RUNTIME_ARN}
    for statements in (host, deploy):
        assert allows(statements, "kms:Decrypt", KEY_ARN, context)
        assert not allows(statements, "kms:Decrypt", KEY_ARN)
        assert not allows(statements, "kms:Decrypt", KEY_ARN, {**context, "kms:EncryptionContext:PARAMETER_ARN": "production"})
        assert not allows(statements, "ssm:GetParameter", RUNTIME_ARN.replace("/staging/", "/production/"))
        assert not allows(statements, "ssm:GetParametersByPath", "*")
        assert not allows(statements, "s3:GetObject", "arn:aws:s3:::production-artifacts/releases/test.tar.gz")
    assert not allows(host, "ssm:PutParameter", RUNTIME_ARN)
    assert not allows(host, "ssm:SendCommand", "*")


def test_receipt_permissions_allow_host_writes_and_deployment_reads_only_within_stage_bucket():
    host, deploy = role_permissions("StagingInstanceRole"), role_permissions("StagingDeployRole")
    receipt = "arn:aws:s3:::tau-preproduction-staging-artifacts-fixture/receipts/" + "a" * 32 + ".json"
    assert allows(host, "s3:PutObject", receipt)
    assert not allows(host, "s3:GetObject", receipt)
    assert allows(deploy, "s3:GetObject", receipt)
    assert not allows(deploy, "s3:PutObject", receipt)
    assert not allows(host, "s3:PutObject", receipt.replace("tau-preproduction-staging-artifacts-fixture", "production-artifacts"))
    assert not allows(deploy, "s3:GetObject", receipt.replace("tau-preproduction-staging-artifacts-fixture", "production-artifacts"))
    bucket = "arn:aws:s3:::tau-preproduction-staging-artifacts-fixture"
    exact_receipt_key = "receipts/" + "a" * 32 + ".json"
    assert allows(deploy, "s3:ListBucket", bucket, {"s3:prefix": exact_receipt_key})
    assert allows(deploy, "s3:ListBucket", bucket, {"s3:prefix": "releases/commit.tar.gz"})
    assert not allows(deploy, "s3:ListBucket", bucket)
    assert not allows(deploy, "s3:ListBucket", bucket, {"s3:prefix": ""})
    assert not allows(deploy, "s3:ListBucket", bucket, {"s3:prefix": "secrets/"})
    assert not allows(deploy, "s3:ListBucket", "arn:aws:s3:::production-artifacts", {"s3:prefix": exact_receipt_key})
    assert not allows(host, "s3:ListBucket", bucket, {"s3:prefix": exact_receipt_key})
    for statements in (host, deploy):
        assert not allows(statements, "ssm:GetCommandInvocation", "*")
        assert not allows(statements, "ec2:DescribeInstances", "*")


def test_oidc_trust_is_exact_repo_environment_and_audience_without_wildcards():
    trust = bootstrap.load_template()["Resources"]["StagingDeployRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert len(trust) == 1
    assert trust[0]["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert trust[0]["Condition"] == {"StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:JihuiTanUchicago/kalshi_trade:environment:staging",
    }}


def test_network_has_private_origin_no_ssh_no_production_links_and_retained_encrypted_data():
    resources = bootstrap.load_template()["Resources"]
    instance = resources["StagingInstance"]["Properties"]
    assert instance["InstanceType"] == "t3.medium" and instance["CreditSpecification"]["CPUCredits"] == "standard"
    assert "KeyName" not in instance
    nic = instance["NetworkInterfaces"][0]
    assert nic["AssociatePublicIpAddress"] is False and nic["SubnetId"] == {"Ref": "PrivateAppSubnet"}
    assert instance["MetadataOptions"]["HttpTokens"] == "required"
    assert instance["MetadataOptions"]["HttpPutResponseHopLimit"] == 1
    ingress = resources["StagingSecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert len(ingress) == 1
    assert ingress[0]["FromPort"] == ingress[0]["ToPort"] == 80
    assert "CidrIp" not in ingress[0] and "CidrIpv6" not in ingress[0]
    assert ingress[0]["SourcePrefixListId"] == {"Ref": "CloudFrontOriginFacingPrefixListId"}
    assert resources["PrivateDefaultRoute"]["Properties"]["NatGatewayId"] == {"Ref": "NatGateway"}
    assert not any("Peering" in resource["Type"] or "TransitGateway" in resource["Type"] for resource in resources.values())
    disk, key = resources["StagingDataVolume"], resources["StagingRuntimeKmsKey"]
    assert disk["Properties"]["Encrypted"] is True and disk["Properties"]["Size"] == 40
    assert disk["Properties"]["KmsKeyId"] == {"Fn::GetAtt": ["StagingRuntimeKmsKey", "Arn"]}
    assert disk["DeletionPolicy"] == disk["UpdateReplacePolicy"] == "Retain"
    assert key["DeletionPolicy"] == key["UpdateReplacePolicy"] == "Retain"


def test_authenticated_and_callback_traffic_never_caches_or_loses_viewer_state():
    resources = bootstrap.load_template()["Resources"]
    distribution = resources["StagingDistribution"]["Properties"]["DistributionConfig"]
    behavior = distribution["DefaultCacheBehavior"]
    assert behavior["ViewerProtocolPolicy"] == "https-only"
    assert set(behavior["AllowedMethods"]) == {"GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"}
    assert "Logging" not in distribution and "Aliases" not in distribution
    assert distribution["ViewerCertificate"] == {"CloudFrontDefaultCertificate": True}
    assert set(distribution["Origins"][0]) == {"Id", "DomainName", "VpcOriginConfig"}
    assert distribution["Origins"][0]["DomainName"] == {"Fn::GetAtt": ["StagingInstance", "PrivateDnsName"]}
    config = resources["StagingCachePolicy"]["Properties"]["CachePolicyConfig"]
    assert config["MinTTL"] == config["DefaultTTL"] == config["MaxTTL"] == 0
    origin_request = resources["StagingOriginRequestPolicy"]["Properties"]["OriginRequestPolicyConfig"]
    assert origin_request["CookiesConfig"]["CookieBehavior"] == "all"
    assert origin_request["QueryStringsConfig"]["QueryStringBehavior"] == "all"
    assert origin_request["HeadersConfig"]["HeaderBehavior"] == "allViewer"
    assert all(item["ErrorCachingMinTTL"] == 0 for item in distribution["CustomErrorResponses"])


def test_userdata_is_valid_bash_has_no_secret_or_app_checkout_and_has_true_health_semantics():
    resources = bootstrap.load_template()["Resources"]
    userdata = resources["StagingInstance"]["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"]
    assert set(re.findall(r"\$\{([^}]+)\}", userdata)) == {"StagingDataVolume"}
    rendered = userdata.replace("${StagingDataVolume}", "vol-0123456789abcdef0")
    result = subprocess.run(["bash", "-n"], input=rendered, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "/opt/kalshi" not in userdata and "git clone" not in userdata and "get-parameter" not in userdata
    assert "\"data-root\":\"/opt/tau-staging/docker\"" in userdata
    assert "access_log off" in userdata and "error_log /dev/null crit" in userdata
    assert "proxy_pass http://127.0.0.1:18091" in userdata and "return 503" in userdata
    assert "return 200" not in userdata
    assert userdata.index("/etc/tau-staging-host.json") > userdata.index("systemctl restart nginx.service")


def test_offline_preview_never_invokes_aws(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline preview must not spawn AWS")

    monkeypatch.setattr(bootstrap.subprocess, "run", forbidden)
    assert bootstrap.main(["preview"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["aws_calls"] == 0 and receipt["production_changes"] is False
    assert "NAT Gateway" in receipt["cost_notice"]


def test_raw_aws_identity_errors_and_secrets_are_not_forwarded(monkeypatch, capsys):
    def fail(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "sensitive-stdout", "An error occurred (AccessDenied) owner=private-key")

    monkeypatch.setattr(bootstrap.subprocess, "run", fail)
    assert bootstrap.main(["outputs"]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["error_code"] == "AccessDenied"
    assert "private-key" not in output and "sensitive-stdout" not in output
