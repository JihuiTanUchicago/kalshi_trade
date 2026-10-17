"""Production helper checks use synthetic secrets; no network or service changes."""
import importlib.util
import json
from pathlib import Path
import shlex
import stat
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "configure_market_data.py"
SPEC = importlib.util.spec_from_file_location("configure_market_data", SCRIPT)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
SECRET = "synthetic-databento-private-key"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in helper.ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Configuration helper attempted a provider request")

    monkeypatch.setattr("requests.sessions.Session.request", forbidden)


def profile(**changes):
    env = {"TAU_MARKET_DATA_PRIMARY": "databento", "TAU_DATABENTO_ENABLED": "1",
           "DATABENTO_API_KEY": SECRET, "TAU_DATABENTO_DATASETS": "EQUS.MINI",
           "TAU_DATABENTO_DEFAULT_DATASET": "EQUS.MINI", "TAU_DATABENTO_MAX_COST_USD": "0.05",
           "TAU_ALPACA_ENABLED": "0", "TAU_MASSIVE_ENABLED": "0"}
    env.update(changes)
    return env


def private_file(tmp_path, name="operator.env", env=None):
    path = tmp_path / name
    env = profile() if env is None else env
    path.write_text("".join(f"{key}={shlex.quote(value)}\n" for key, value in env.items()))
    path.chmod(0o600)
    return path


def report(capsys):
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    return json.loads(captured.out)


def test_default_validation_is_secret_safe_and_does_not_write(tmp_path, capsys):
    source = private_file(tmp_path)
    target = tmp_path / ".env.market-data"
    assert helper.main(["--env-file", str(source), "--output", str(target)]) == 0
    result = report(capsys)
    assert result["ready"] and result["applied"] is False
    assert result["network_requests"] == 0 and result["provider_validation"] == "not_performed"
    assert not target.exists()


def test_file_overrides_process_including_blanks_and_ignores_unrelated_environment(tmp_path):
    source = private_file(tmp_path, env={"DATABENTO_API_KEY": "", "TAU_ALPACA_ENABLED": "0"})
    result = helper.configuration_environment({"DATABENTO_API_KEY": SECRET, "TAU_ALPACA_ENABLED": "1",
                                               "APP_SECRET_KEY": "unrelated-private-value"}, source)
    assert result["DATABENTO_API_KEY"] == "" and result["TAU_ALPACA_ENABLED"] == "0"
    assert "APP_SECRET_KEY" not in result
    assert set(result) == set(helper.ENV_KEYS) == set(helper._configuration_module().ENV_DEFAULTS)


def test_export_literals_comments_and_empty_assignments():
    result = helper.parse_assignments("\n# comment\nexport DATABENTO_API_KEY='private # literal' # note\n"
                                      "TAU_DATABENTO_ENABLED=1\nMASSIVE_API_KEY= # fill privately\n")
    assert result == {"DATABENTO_API_KEY": "private # literal", "TAU_DATABENTO_ENABLED": "1", "MASSIVE_API_KEY": ""}


@pytest.mark.parametrize("contents", [
    "APP_SECRET_KEY=unrelated-private-value", "UNKNOWN_SETTING=sensitive", "DATABENTO_API_KEY=$(touch /tmp/unwanted)",
    "DATABENTO_API_KEY=`touch /tmp/unwanted`", "DATABENTO_API_KEY=${PRIVATE_KEY}", "DATABENTO_API_KEY=$PRIVATE_KEY",
    "DATABENTO_API_KEY=synthetic;touch /tmp/unwanted", "DATABENTO_API_KEY=one two", "DATABENTO_API_KEY='unterminated",
    "DATABENTO_API_KEY='one\ntwo'", "DATABENTO_API_KEY=one\\\nTAU_DATABENTO_ENABLED=1",
    "DATABENTO_API_KEY=one\nDATABENTO_API_KEY=two", "DATABENTO_API_KEY=synthetic\x00private",
])
def test_unsupported_syntax_and_expansions_are_rejected_without_echo(contents):
    with pytest.raises(helper.ConfigurationFileError) as exc:
        helper.parse_assignments(contents)
    assert "sensitive" not in str(exc.value) and "unwanted" not in str(exc.value)
    assert "unrelated-private-value" not in str(exc.value)


def test_apply_atomically_replaces_private_target_and_quotes_values(tmp_path, capsys, monkeypatch):
    source = private_file(tmp_path, env=profile(DATABENTO_API_KEY="synthetic'quoted#private"))
    target = tmp_path / ".env.market-data"
    target.write_text("old settings\n")
    target.chmod(0o600)
    previous_inode = target.stat().st_ino
    before = source.read_bytes()
    real_replace = helper.os.replace
    calls = []

    def checked_replace(temporary, destination):
        assert temporary.parent == target.parent
        assert stat.S_IMODE(temporary.stat().st_mode) == 0o600
        assert target.read_text() == "old settings\n"
        calls.append((temporary, destination))
        real_replace(temporary, destination)

    monkeypatch.setattr(helper.os, "replace", checked_replace)
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 0
    result = report(capsys)
    assert "synthetic'quoted#private" not in json.dumps(result)
    assert result["ready"] and result["applied"] and len(calls) == 1
    assert target.stat().st_ino != previous_inode and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert source.read_bytes() == before
    assert helper.parse_assignments(target.read_text()) == helper.configuration_environment({}, source)
    assert not list(tmp_path.glob(".market-data-*"))


def test_invalid_configuration_never_clobbers_output(tmp_path, capsys):
    source = private_file(tmp_path, env=profile(TAU_DATABENTO_MAX_COST_USD="0"))
    target = tmp_path / ".env.market-data"
    target.write_text("protected previous config\n")
    target.chmod(0o600)
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 2
    result = report(capsys)
    assert not result["ready"] and not result["applied"]
    assert target.read_text() == "protected previous config\n" and not list(tmp_path.glob(".market-data-*"))


@pytest.mark.parametrize("name", [".env", ".env.app", ".env.aws"])
def test_base_environment_files_cannot_be_overwritten(tmp_path, capsys, name):
    source = private_file(tmp_path)
    target = tmp_path / name
    before = b"export APP_SECRET_KEY=synthetic-preserved-encryption-key\n"
    target.write_bytes(before)
    target.chmod(0o600)
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 2
    result = report(capsys)
    assert not result["ready"] and not result["applied"]
    assert target.read_bytes() == before and not list(tmp_path.glob(".market-data-*"))
    assert "synthetic-preserved-encryption-key" not in json.dumps(result)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o620, 0o601])
def test_insecure_input_modes_are_refused(tmp_path, capsys, mode):
    source = private_file(tmp_path)
    source.chmod(mode)
    assert helper.main(["--env-file", str(source)]) == 2
    assert not report(capsys)["ready"]


def test_symlink_input_and_output_are_refused_without_clobber(tmp_path, capsys):
    source = private_file(tmp_path)
    linked_source = tmp_path / "linked.env"
    linked_source.symlink_to(source)
    assert helper.main(["--env-file", str(linked_source)]) == 2
    assert not report(capsys)["ready"]
    target = tmp_path / ".env.market-data"
    target.symlink_to(source)
    before = source.read_bytes()
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 2
    assert not report(capsys)["applied"]
    assert target.is_symlink() and source.read_bytes() == before


def test_dangling_output_symlink_and_same_input_output_are_refused(tmp_path, capsys):
    source = private_file(tmp_path)
    target = tmp_path / ".env.market-data"
    target.symlink_to(tmp_path / "missing")
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 2
    assert not report(capsys)["applied"] and target.is_symlink()
    assert helper.main(["--env-file", str(source), "--output", str(source), "--apply"]) == 2
    assert not report(capsys)["applied"]


def test_apply_requires_explicit_output_and_honors_environment_only(tmp_path, monkeypatch, capsys):
    for key, value in profile().items():
        monkeypatch.setenv(key, value)
    assert helper.main(["--apply"]) == 2
    assert not report(capsys)["applied"]
    assert helper.main([]) == 0
    assert report(capsys)["ready"]


def test_blank_file_credential_fails_even_when_process_has_a_key(tmp_path, monkeypatch, capsys):
    source = private_file(tmp_path, env=profile(DATABENTO_API_KEY=""))
    monkeypatch.setenv("DATABENTO_API_KEY", SECRET)
    target = tmp_path / ".env.market-data"
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 2
    assert not report(capsys)["ready"] and not target.exists()


def test_minimal_profile_materializes_defaults_before_old_service_environment(tmp_path, capsys):
    source = private_file(tmp_path, env={key: value for key, value in profile().items()
                                       if key not in {"TAU_ALPACA_ENABLED", "TAU_MASSIVE_ENABLED"}})
    target = tmp_path / ".env.market-data"
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 0
    checked = report(capsys)
    old_base = {"TAU_MARKET_DATA_PRIMARY": "alpaca", "TAU_ALPACA_ENABLED": "1", "TAU_MASSIVE_ENABLED": "1",
                "APCA_API_KEY_ID": "old-key", "APCA_API_SECRET_KEY": "old-private-secret", "MASSIVE_API_KEY": "old-massive-key",
                "TAU_ALPACA_FEED": "sip", "TAU_MASSIVE_FX_FEED": "realtime",
                "TAU_DATABENTO_DEFAULT_DATASET": "GLBX.MDP3"}
    overlay = helper.parse_assignments(target.read_text())
    runtime = helper._configuration_module().check_configuration({**old_base, **overlay})
    assert set(overlay) == set(helper.ENV_KEYS)
    assert runtime["ready"] and runtime["routing"] == checked["routing"]
    assert runtime["providers"] == checked["providers"]
    assert not runtime["providers"]["alpaca"]["enabled"] and not runtime["providers"]["massive"]["enabled"]
    assert overlay["APCA_API_KEY_ID"] == overlay["APCA_API_SECRET_KEY"] == overlay["MASSIVE_API_KEY"] == ""
    assert overlay["TAU_ALPACA_FEED"] == "iex" and overlay["TAU_MASSIVE_FX_FEED"] == "end_of_day"


def test_existing_insecure_output_and_writable_parent_are_refused(tmp_path, capsys):
    source = private_file(tmp_path)
    target = tmp_path / ".env.market-data"
    target.write_text("previous config\n")
    target.chmod(0o644)
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 2
    assert not report(capsys)["applied"] and target.read_text() == "previous config\n"
    target.unlink()
    tmp_path.chmod(0o777)
    try:
        assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 2
        assert not report(capsys)["applied"] and not target.exists()
    finally:
        tmp_path.chmod(0o700)


def test_output_appearing_as_symlink_during_installation_is_preserved(tmp_path, monkeypatch, capsys):
    source = private_file(tmp_path)
    target = tmp_path / ".env.market-data"
    real_mkstemp = helper.tempfile.mkstemp

    def inserted_symlink(*args, **kwargs):
        result = real_mkstemp(*args, **kwargs)
        target.symlink_to(source)
        return result

    monkeypatch.setattr(helper.tempfile, "mkstemp", inserted_symlink)
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 2
    assert not report(capsys)["applied"] and target.is_symlink()
    assert not list(tmp_path.glob(".market-data-*"))


def test_oversized_and_malformed_encoding_input_are_safe_errors(tmp_path, capsys):
    source = private_file(tmp_path)
    source.write_text("#" * (helper.MAX_FILE_BYTES + 1))
    assert helper.main(["--env-file", str(source)]) == 2
    assert not report(capsys)["ready"]
    source.write_bytes(b"DATABENTO_API_KEY=\xff")
    assert helper.main(["--env-file", str(source)]) == 2
    assert not report(capsys)["ready"]


def test_atomic_failure_preserves_previous_file_and_removes_temporary(tmp_path, monkeypatch, capsys):
    source = private_file(tmp_path)
    target = tmp_path / ".env.market-data"
    target.write_text("old settings\n")
    target.chmod(0o600)

    def failed_replace(*args):
        raise OSError("synthetic IO failure with " + SECRET)

    monkeypatch.setattr(helper.os, "replace", failed_replace)
    assert helper.main(["--env-file", str(source), "--output", str(target), "--apply"]) == 2
    assert not report(capsys)["applied"]
    assert target.read_text() == "old settings\n" and not list(tmp_path.glob(".market-data-*"))


def test_direct_script_execution_imports_product_without_pythonpath(tmp_path):
    source = private_file(tmp_path)
    completed = subprocess.run([sys.executable, str(SCRIPT), "--env-file", str(source)], cwd=tmp_path,
                               env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0 and json.loads(completed.stdout)["ready"]
    assert SECRET not in completed.stdout + completed.stderr
