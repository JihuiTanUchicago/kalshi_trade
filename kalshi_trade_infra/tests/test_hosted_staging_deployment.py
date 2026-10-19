"""Fail-closed target, archive, secret-update and receipt controls for staging."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1] / "staging/hosted"


def load(name):
    spec = importlib.util.spec_from_file_location("test_hosted_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


control, remote = load("deploy_aws"), load("deploy_remote")
SOURCE = "a" * 40
DIGEST = "b" * 64
ROLE = "tau-preproduction-staging-GitHubRole-example"
ORIGIN = "https://d1234567890stage.cloudfront.net"


def fixture_target():
    values = {"StagingInstanceId": "i-0123456789abcdef0", "StagingArtifactBucket": "tau-preproduction-staging-artifacts-1234",
              "StagingDistributionId": "E123456789STAGE", "StagingUrl": ORIGIN,
              "StagingDeployRoleArn": "arn:aws:iam::" + control.ACCOUNT + ":role/" + ROLE}
    stack = {"Stacks": [{"StackName": control.STACK, "StackStatus": "CREATE_COMPLETE",
                         "Outputs": [{"OutputKey": key, "OutputValue": value} for key, value in values.items()]}]}
    identity = {"Account": control.ACCOUNT, "Arn": "arn:aws:sts::" + control.ACCOUNT + ":assumed-role/" + ROLE + "/test"}
    return stack, identity


def fixture_context():
    return {"source_sha": SOURCE, "bundle_sha256": DIGEST, "bucket": "tau-preproduction-staging-artifacts-1234",
            "key": "releases/" + SOURCE + "/" + DIGEST + ".tgz", "origin": ORIGIN,
            "receipt_key": "receipts/" + "c" * 32 + ".json"}


@pytest.mark.parametrize("key,value", [
    ("StagingInstanceId", control.PRODUCTION_INSTANCE), ("StagingArtifactBucket", control.PRODUCTION_BUCKET),
    ("StagingDistributionId", control.PRODUCTION_DISTRIBUTION), ("StagingUrl", control.PRODUCTION_ORIGIN),
])
def test_actual_production_targets_cannot_be_selected(key, value):
    stack, identity = fixture_target()
    for row in stack["Stacks"][0]["Outputs"]:
        if row["OutputKey"] == key:
            row["OutputValue"] = value
    with pytest.raises(control.DeployError, match="production_or_invalid"):
        control.stack_target(stack, identity)


def test_static_production_credentials_cannot_replace_staging_oidc():
    stack, identity = fixture_target()
    identity["Arn"] = "arn:aws:iam::" + control.ACCOUNT + ":user/existing-production-deployer"
    with pytest.raises(control.DeployError, match="dedicated_staging_role_required"):
        control.stack_target(stack, identity)


def test_staging_target_requires_the_single_scoped_cloudformation_stack():
    stack, identity = fixture_target()
    stack["Stacks"][0]["StackName"] = "production"
    with pytest.raises(control.DeployError, match="incorrect_staging_stack"):
        control.stack_target(stack, identity)


@pytest.mark.parametrize("edit", [{"bucket": control.PRODUCTION_BUCKET}, {"origin": control.PRODUCTION_ORIGIN},
                                  {"key": "releases/../../production.tgz"}, {"source_sha": "main"}])
def test_remote_context_rejects_production_and_unpinned_release(edit):
    with pytest.raises(remote.StageError):
        remote.validate_context({**fixture_context(), **edit})


def archive(extra_name=None, link=False):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as output:
        for path in ("app/server.py", "app/schema.py", "app/worker.py", "requirements.txt",
                     "staging/hosted/entrypoint.py", "staging/hosted/compose.yml", "staging/hosted/setup.py"):
            item = tarfile.TarInfo(path)
            item.size = 1
            output.addfile(item, io.BytesIO(b"x"))
        if extra_name:
            item = tarfile.TarInfo(extra_name)
            if link:
                item.type, item.linkname = tarfile.SYMTYPE, "/opt/kalshi/.env.app"
            output.addfile(item)
    return tarfile.open(fileobj=io.BytesIO(stream.getvalue()), mode="r:gz")


@pytest.mark.parametrize("name,link", [("../outside", False), ("app/.env.app", False),
                                        ("staging/hosted/.state/runtime.json", False),
                                        ("app/credentials/key.pem", False), ("app/symlink.py", True)])
def test_archive_cannot_escape_or_ship_private_files(name, link):
    with archive(name, link) as package, pytest.raises(remote.StageError):
        remote.validate_members(package)


def test_complete_code_archive_is_accepted_without_mutation():
    with archive() as package:
        assert len(remote.validate_members(package)) == 7


def pending_receipt():
    return {"status": "pending_staging_configuration", "source_sha": SOURCE,
            "production_changed": False, "research_worker_started": False, "provider_calls": 0,
            "real_oauth_or_paper_order_accepted": False, "pending_gate": "staging_runtime_parameter"}


def test_receipt_never_treats_pending_as_deployed_or_accepts_unprojected_values():
    result = control.validated_receipt(pending_receipt(), SOURCE)
    assert result["status"] == "pending_staging_configuration"
    for edit in ({"pending_gate": "private-secret-value"}, {"source_sha": "c" * 40},
                 {"provider_calls": 1}, {"environment": {"TOKEN": "private-secret-value"}},
                 {"real_oauth_or_paper_order_accepted": True}):
        with pytest.raises(control.DeployError):
            control.validated_receipt({**pending_receipt(), **edit}, SOURCE)


def test_invalid_new_runtime_preserves_existing_private_staging_settings(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    settings = state / "hosted_runtime.json"
    settings.write_bytes(b"previously-accepted-private-config")
    settings.chmod(0o600)
    monkeypatch.setattr(remote, "STATE", state)
    raw = json.dumps({"Parameter": {"Value": json.dumps({"APP_PUBLIC_URL": ORIGIN,
                      "STRIPE_SECRET_KEY": "sk_live_private-value"})}}).encode()
    monkeypatch.setattr(remote.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, raw, b""))
    with pytest.raises(remote.StageError, match="invalid_staging_runtime_configuration"):
        remote.install_runtime(ORIGIN, HERE.parents[1])
    assert settings.read_bytes() == b"previously-accepted-private-config"
    assert capsys.readouterr().out == ""


def test_missing_staging_parameter_is_pending_without_raw_error_output(monkeypatch, capsys):
    monkeypatch.setattr(remote.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 255, b"", b"ParameterNotFound private-identity"))
    assert remote.install_runtime(ORIGIN, HERE.parents[1]) is False
    assert capsys.readouterr().out == ""


def test_host_guard_prevents_any_download_or_service_mutation(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(remote, "verify_host", lambda: (_ for _ in ()).throw(remote.StageError("incorrect_staging_host_marker")))
    monkeypatch.setattr(remote, "install_release", lambda context: calls.append(context))
    monkeypatch.setattr(remote, "publish_receipt", lambda *args: calls.append("receipt-mutation"))
    assert remote.main(fixture_context()) == 1
    assert not calls
    output = json.loads(capsys.readouterr().out.removeprefix("TAU_HOSTED_REMOTE="))
    assert output["error_code"] == "incorrect_staging_host_marker"
    assert output["production_changed"] is False


def test_raw_child_failure_is_never_returned_or_printed(monkeypatch, capsys):
    monkeypatch.setattr(remote.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 1, b"private-env", b"private-runtime-secret"))
    with pytest.raises(remote.StageError, match="staging_command_failed"):
        remote.checked(["docker", "compose", "build"])
    assert capsys.readouterr().out == ""


def test_container_fixture_refuses_non_actions_or_remote_docker_context(monkeypatch):
    checker = load("check_container")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(checker.CheckError, match="actions_fixture_context_required"):
        checker.check()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote-target:2375")
    with pytest.raises(checker.CheckError, match="actions_fixture_context_required"):
        checker.check()


def test_existing_release_must_match_all_code_not_only_its_digest_marker(tmp_path):
    target = tmp_path / "release"
    target.mkdir()
    with archive() as package:
        members = remote.validate_members(package)
        package.extractall(target, filter="data")
        (target / ".bundle-sha256").write_text(DIGEST)
        remote.verify_installed_release(target, package, members, DIGEST)
        (target / "app/server.py").write_text("changed-code")
        with pytest.raises(remote.StageError, match="staging_release_changed"):
            remote.verify_installed_release(target, package, members, DIGEST)


def test_existing_database_cannot_regenerate_missing_crypto_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, "STATE", tmp_path / "lost-state")
    calls = []
    def inspect(arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, b"staging-only-volume", b"")
    monkeypatch.setattr(remote.subprocess, "run", inspect)
    with pytest.raises(remote.StageError, match="existing_staging_database_secrets_missing"):
        remote.verify_existing_database_secrets()
    assert calls == [remote.DOCKER + ["volume", "inspect", "tau-preproduction_hosted-mysql-data"]]
    assert not remote.STATE.exists()


def test_docker_is_explicitly_local_even_when_a_client_context_was_persisted():
    arguments = remote.compose_arguments(remote.ROOT / "releases" / SOURCE)
    assert arguments[:4] == ["docker", "--host", "unix:///var/run/docker.sock", "compose"]
    assert load("check_container").DOCKER == remote.DOCKER


def test_same_source_runtime_rotation_refreshes_serving_processes_but_not_database(tmp_path, monkeypatch):
    release = tmp_path / "releases" / SOURCE
    release.mkdir(parents=True)
    monkeypatch.setattr(remote, "ROOT", tmp_path)
    monkeypatch.setattr(remote, "STATE", tmp_path / "state")
    monkeypatch.setattr(remote, "deployment_lock", nullcontext)
    monkeypatch.setattr(remote, "install_release", lambda context: release)
    monkeypatch.setattr(remote, "verify_existing_database_secrets", lambda: None)
    monkeypatch.setattr(remote, "install_runtime", lambda origin, source: True)
    calls = []
    monkeypatch.setattr(remote, "checked", lambda arguments, **kwargs:
                        (calls.append(arguments) or subprocess.CompletedProcess(arguments, 0, b"", b"")))
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(remote.urllib.request, "urlopen", lambda *a, **k: Response())
    assert remote.deploy_verified(fixture_context())["status"] == "staging_deployed_pending_user_acceptance"
    serving = [call for call in calls if call[-1] in ("web", "gateway")]
    assert len(serving) == 2 and all("--force-recreate" in call for call in serving)
    assert all("--force-recreate" not in call for call in calls if call[-1] == "db")
    assert all("down" not in call for call in calls)


def test_privileged_deploy_lock_cannot_follow_a_symlink_and_truncate_a_file(tmp_path, monkeypatch):
    protected = tmp_path / "do-not-truncate"
    protected.write_text("preserved")
    lock = tmp_path / "deploy.lock"
    lock.symlink_to(protected)
    class Operations:
        def mkdir(self, **kwargs): pass
        def lstat(self): return SimpleNamespace(st_mode=0o40700, st_uid=0)
        def __truediv__(self, name): return lock
    class Root:
        def __truediv__(self, name): return Operations()
    monkeypatch.setattr(remote, "ROOT", Root())
    with pytest.raises(OSError):
        with remote.deployment_lock():
            pytest.fail("symlinked lock accepted")
    assert protected.read_text() == "preserved"


def test_receipt_poll_waits_for_exact_staging_object_without_reading_ssm_logs(monkeypatch):
    target = control.stack_target(*fixture_target())
    context = fixture_context()
    calls, polls = [], []
    def invoke(*arguments):
        calls.append(arguments)
        if arguments[:2] == ("ssm", "send-command"):
            return {"Command": {"CommandId": "01234567-89ab-cdef-0123-456789abcdef"}}
        if arguments[:2] == ("s3api", "list-objects-v2"):
            polls.append(True)
            return {} if len(polls) == 1 else {"Contents": [{"Key": context["receipt_key"]}]}
        if arguments[:2] == ("s3api", "get-object"):
            assert len(polls) == 2
            Path(arguments[-1]).write_text(json.dumps(pending_receipt()))
            return {}
        pytest.fail("unexpected AWS call")
    monkeypatch.setattr(control, "aws", invoke)
    monkeypatch.setattr(control.time, "sleep", lambda duration: None)
    assert control.remote(target, context)["status"] == "pending_staging_configuration"
    assert [call[:2] for call in calls] == [("ssm", "send-command"), ("s3api", "list-objects-v2"),
                                            ("s3api", "list-objects-v2"), ("s3api", "get-object")]
