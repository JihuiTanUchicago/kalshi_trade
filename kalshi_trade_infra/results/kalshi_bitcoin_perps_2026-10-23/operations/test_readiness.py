"""Offline operations checks; no real AWS, DB, provider or service call."""
from __future__ import annotations

import base64
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import zlib

import pytest
import requests


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


remote = load("perps_readiness_remote", HERE / "remote.py")
previous_remote = sys.modules.get("remote")
sys.modules["remote"] = remote
runner = load("perps_readiness_runner", HERE / "runner.py")
if previous_remote is None:
    sys.modules.pop("remote", None)
else:
    sys.modules["remote"] = previous_remote
repository = load("perps_readiness_repository", HERE / "readiness_repository.py")
collector = load("perps_readiness_collect", HERE / "collect.py")
public = load("perps_readiness_public", HERE / "public_check.py")


class Cursor:
    def __init__(self, present=repository.TABLES):
        self.present = present
        self.queries = []
        self.rows = []

    def execute(self, sql, args=None):
        self.queries.append((sql, args))
        if "information_schema.TABLES" in sql:
            self.rows = [{"name": name} for name in self.present]
        elif "information_schema.COLUMNS" in sql:
            self.rows = [{"name": name, "column_type": "varchar(48)", "nullable": "NO",
                          "max_length": 48, "collation": "utf8mb4_0900_ai_ci"} for name in repository.COLUMN_TABLES]
        elif "GROUP BY status" in sql:
            self.rows = [{"status": "running", "n": 7}, {"status": "paused", "n": 2}]
        elif sql.startswith("SELECT COUNT(*)"):
            self.rows = [{"n": 3}]
        else:
            assert sql in {"SET SESSION MAX_EXECUTION_TIME=3000", "SET SESSION lock_wait_timeout=3",
                           "START TRANSACTION READ ONLY"}

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_repository_only_reports_aggregates_and_correct_four_column_signatures():
    cursor = Cursor()
    result = repository.inspect(cursor)
    assert result["research_counts"] == {"queued": 0, "running": 7, "paused": 2}
    assert set(result["market_column_signatures"]) == {
        "app_experiments", "app_fdr_state", "app_holdout_ledger", "app_data_partitions"}
    assert all(row["max_length"] == 48 for row in result["market_column_signatures"].values())
    assert result["full_database_integration_verified"] is False
    assert all(sql.startswith("SELECT ") for sql, _ in cursor.queries)
    assert all("FOR UPDATE" not in sql for sql, _ in cursor.queries)
    assert all("user_id" not in sql and "SELECT *" not in sql for sql, _ in cursor.queries)


def test_missing_tables_are_reported_without_count_queries():
    cursor = Cursor(present=())
    result = repository.inspect(cursor)
    assert not any(result["tables_present"].values())
    assert result["perps_row_counts"] == {}
    assert not any("COUNT(*)" in sql for sql, _ in cursor.queries)


def test_database_session_read_only_limits_and_credentials_not_in_receipt():
    cursor = Cursor()
    connection = SimpleNamespace(cursor=lambda: cursor, rollback=Mock(), close=Mock())
    connect = Mock(return_value=connection)
    result = repository.run({"MYSQL_HOST": "private-host", "MYSQL_USER": "private-user",
                             "MYSQL_PASSWORD": "private-password"}, connect)
    assert result["status"] == "checked"
    assert [sql for sql, _ in cursor.queries][:3] == ["SET SESSION MAX_EXECUTION_TIME=3000",
        "SET SESSION lock_wait_timeout=3", "START TRANSACTION READ ONLY"]
    assert connect.call_args.kwargs["connect_timeout"] == 5
    assert connect.call_args.kwargs["read_timeout"] == 8
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    assert "private-" not in json.dumps(result)


def test_database_errors_do_not_reveal_connection_or_query_details():
    result = repository.run({"MYSQL_HOST": "private", "MYSQL_USER": "private", "MYSQL_PASSWORD": "private"},
                            Mock(side_effect=RuntimeError("private password and rows")))
    assert result == {"status": "unavailable", "error_code": "database_read_failed"}
    assert repository.run({}, Mock())["error_code"] == "missing_database_configuration"


@pytest.mark.parametrize("value,enabled", [(None, False), ("false", False), ("0", False), ("true", True), ("1", True)])
def test_effective_flags_are_booleans_and_never_return_values(value, enabled):
    env = {"APP_SECRET_KEY": "never-retained"}
    if value is not None:
        env["TAU_KALSHI_PERPS_ENABLED"] = value
    assert remote.perps_flag(env) == {"enabled": enabled, "explicitly_configured": value is not None,
                                      "explicit_proxy_configured": False}


def test_invalid_flag_fails_closed_without_echo():
    with pytest.raises(remote.InspectionError, match="^invalid_perps_flag$"):
        remote.perps_flag({"TAU_KALSHI_PERPS_ENABLED": "private invalid value"})


@pytest.mark.parametrize("name", ["app/__pycache__/x.pyc", "app/credentials/key.json", "app/.env.prod",
                                 "data_pipeline/key.pem", "data_pipeline/secrets/secret", "app/server.log"])
def test_private_and_cache_paths_are_omitted(name):
    assert not remote.source_path_allowed(name)


def test_whole_source_scan_hashes_all_regular_files_omits_private_and_rejects_symlink(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    for name in ("app/server.py", "app/schema.py", "app/static/unrecognized.css", "data_pipeline/common.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic source")
        path.chmod(0o644)
    (root / "app/.env").write_text("never hash this private value")
    (root / "app/__pycache__").mkdir()
    (root / "app/__pycache__/x.pyc").write_bytes(b"cache")
    monkeypatch.setattr(remote, "ROOT", root)
    result = remote.scan()
    assert set(result["files"]) == {"app/server.py", "app/schema.py", "app/static/unrecognized.css", "data_pipeline/common.py"}
    assert result["omitted_private_or_cache_entries"] == 2
    assert all(row["sha256"] == remote.digest(b"synthetic source") for row in result["files"].values())
    (root / "app/link").symlink_to(root / "app/server.py")
    with pytest.raises(remote.InspectionError, match="source_symlink_not_supported"):
        remote.scan()


def state():
    units = {name: {"pid": index + 10, "perps": {"enabled": False}} for index, name in enumerate(remote.SERVICES[:2])}
    return {"source": {"files": {"app/schema.py": {"sha256": "a" * 64}}}, "controls": {"units": units}}


def prepare_inspection(monkeypatch, after=None):
    before = state()
    private = {name: {"MYSQL_HOST": "db-private", "MYSQL_USER": "private-user", "MYSQL_PASSWORD": "private-password",
                      "APP_SECRET_KEY": "private-key", "PROD_KEYFILE": "/private/provider.key",
                      "TAU_KALSHI_PERPS_PROXY_URL": "http://127.0.0.1:7890"} for name in remote.SERVICES[:2]}
    snapshots = iter([(copy.deepcopy(before), private), (copy.deepcopy(after or before), private)])
    monkeypatch.setattr(remote, "snapshot", lambda: next(snapshots))
    files = {name: b"synthetic disposable source" for name in (*remote.NATIVE, *remote.HELPERS)}
    monkeypatch.setattr(remote, "load_bundle", lambda *_: (files, {"base": {}, "candidate": {"app/schema.py": "b" * 64, "app/missing.py": "c" * 64}}))
    calls = []

    def child(path, env, timeout):
        assert path.exists()
        calls.append((path, env, timeout))
        if path.name == "readiness_repository.py":
            return {"status": "checked", "tables_present": {"app_agent_runs": True}, "research_counts": {"running": 7}}
        return {"status": "checked", "readable_history_and_funding": True, "partial_candle_warning": True}

    monkeypatch.setattr(remote, "child", child)
    return calls


def test_real_temp_source_cleanup_separate_child_environments_and_no_acceptance_claim(monkeypatch):
    calls = prepare_inspection(monkeypatch)
    result = remote.inspect({}, {})
    assert result["status"] == "inspected"
    assert len(calls) == 2 and all(not path.exists() for path, _, _ in calls)
    assert set(calls[0][1]) == {"MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD"}
    assert set(calls[1][1]) == {"TAU_KALSHI_PERPS_PROXY_URL"}
    assert result["temporary_source_cleaned"] is True
    assert result["source_and_controls_unchanged"] is True
    assert result["missing_candidate_files"] == ["app/missing.py"]
    assert result["schema_sha256"] == "a" * 64
    assert not result["replay_accepted"] and not result["production_release_accepted"]
    assert "private-" not in json.dumps(result) and "/private/" not in json.dumps(result)


@pytest.mark.parametrize("service", ["recursive-agents", "recursive-web", "recursive-engine"])
def test_enabled_installed_perps_stops_before_bundle_database_or_public_calls(monkeypatch, service):
    before = state()
    before["controls"]["units"][service] = {"pid": 123, "perps": {"enabled": True}}
    monkeypatch.setattr(remote, "snapshot", lambda: (before, {}))
    bundle = Mock(side_effect=AssertionError("must not fetch"))
    monkeypatch.setattr(remote, "load_bundle", bundle)
    result = remote.inspect({}, {})
    assert result["error_code"] == "unexpected_perps_enabled"
    bundle.assert_not_called()


def test_source_drift_fails_closed_after_diagnostics(monkeypatch):
    changed = state()
    changed["source"]["files"]["app/schema.py"]["sha256"] = "b" * 64
    prepare_inspection(monkeypatch, changed)
    result = remote.inspect({}, {})
    assert result["error_code"] == "installed_state_changed_during_inspection"
    assert not result["source_and_controls_unchanged"]


def test_child_has_no_ambient_keys_or_proxy_and_sanitizes_stderr(monkeypatch, tmp_path):
    monkeypatch.setenv("PROD_KEYFILE", "/private/key.pem")
    monkeypatch.setenv("HTTPS_PROXY", "http://private:secret@proxy.invalid")
    seen = []

    def run(args, **kwargs):
        seen.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, b'{"status":"checked"}', b"private raw logs")

    monkeypatch.setattr(remote.subprocess, "run", run)
    result = remote.child(tmp_path / "public_check.py", {}, 100)
    assert result == {"status": "checked"}
    env = seen[0][1]["env"]
    assert set(env) == {"PATH", "LANG", "TZ", "PYTHONDONTWRITEBYTECODE", "PYTHONPATH"}
    assert seen[0][0][:2] == [remote.PYTHON, "-B"]
    monkeypatch.setattr(remote.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("private", 1)))
    assert remote.child(tmp_path / "public_check.py", {}, 1)["error_code"] == "diagnostic_timeout"


def test_exact_candidate_bundle_and_remote_command_are_bounded_and_network_free():
    raw, native = runner.diagnostic_bundle()
    payload = json.loads(raw)
    assert payload["candidate"] == remote.CANDIDATE
    assert set(payload["files"]) == {*remote.NATIVE, *remote.HELPERS}
    assert payload["reference_sha256"]["candidate"]["app/kalshi_perps_data.py"] == native["app/kalshi_perps_data.py"]
    assert len(raw) < remote.MAX_BUNDLE
    command = runner.program({"bucket": remote.BUCKET, "key": "public-source", "sha256": "a" * 64}, native)
    assert len(command) < 24000 and command.startswith(remote.PYTHON + " -B -c ")
    assert "systemctl restart" not in (HERE / "remote.py").read_text()


def test_compressed_sanitized_receipt_roundtrip_and_hash_validation(monkeypatch, capsys):
    result = {"status": "inspected", "installed": {"files": {"app/server.py": "a" * 64}}}
    monkeypatch.setattr(remote, "inspect", lambda *_: result)
    remote.execute({}, {})
    encoded = capsys.readouterr().out
    assert runner.decode_receipt(encoded) == result
    envelope = json.loads(encoded)
    envelope["sha256"] = "f" * 64
    with pytest.raises(runner.RunnerError, match="invalid_receipt"):
        runner.decode_receipt(json.dumps(envelope))


def test_unit_inventory_retains_resources_hashes_flags_and_never_env_values(monkeypatch, tmp_path):
    proc_root, unit_root, installed = tmp_path / "proc", tmp_path / "units", tmp_path / "installed"
    installed.mkdir()
    unit_root.mkdir()
    configured = installed / ".env.app"
    configured.write_text("APP_SECRET_KEY=private-unit-secret")
    monkeypatch.setattr(remote, "ROOT", installed)
    monkeypatch.setattr(remote, "PROC", proc_root)
    monkeypatch.setattr(remote, "UNIT_ROOTS", (unit_root,))
    monkeypatch.setattr(remote, "CONFIG", (configured,))
    monkeypatch.setattr(remote, "read_regular", lambda path, *a, **k:
                        (path.read_bytes(), {"uid": 0, "gid": 0, "mode": "0600"}))
    outputs = []
    for index, service in enumerate(remote.SERVICES):
        pid = index + 100 if index < 2 else 0
        unit = unit_root / (service + ".service")
        unit.write_text("Environment=APP_SECRET_KEY=private-unit-secret")
        values = {name: "" for name in remote.PROPERTIES}
        values.update(MainPID=str(pid), ActiveState="active" if pid else "inactive", FragmentPath=str(unit),
                      Environment="APP_SECRET_KEY=private-unit-secret", ExecStart="private args",
                      MemoryMax="4294967296", MemoryHigh="3221225472", Restart="on-failure")
        outputs.append(subprocess.CompletedProcess([], 0, "\n".join(k + "=" + v for k, v in values.items()).encode()))
        if pid:
            path = proc_root / str(pid)
            path.mkdir(parents=True)
            (path / "cwd").symlink_to(installed, target_is_directory=True)
            args = [remote.PYTHON, "-m", "app.server"] if index == 0 else [remote.PYTHON, "-m", "app.worker", "agents"]
            (path / "cmdline").write_bytes(b"\0".join(item.encode() for item in args))
            (path / "environ").write_bytes(b"APP_SECRET_KEY=private-unit-secret\0TAU_KALSHI_PERPS_ENABLED=false\0")
            (path / "stat").write_text(str(pid) + " (python) " + " ".join(["0"] * 19 + ["12345"]))
    monkeypatch.setattr(remote.subprocess, "run", Mock(side_effect=outputs))
    controls, private = remote.unit_state()
    assert controls["units"]["recursive-agents"]["resources"]["MemoryMax"] == "4294967296"
    assert controls["units"]["recursive-web"]["perps"]["enabled"] is False
    assert private["recursive-web"]["APP_SECRET_KEY"] == "private-unit-secret"
    assert "private-unit-secret" not in json.dumps(controls) and "private args" not in json.dumps(controls)


def test_diagnostic_artifact_rejects_changed_content_before_writing(monkeypatch):
    artifact = {"bucket": remote.BUCKET,
                "key": "bundle/perps-readiness-" + remote.CANDIDATE + "-" + "a" * 32 + ".json",
                "sha256": "b" * 64}
    process = Mock(return_value=subprocess.CompletedProcess([], 0, b"changed public source", b"private stderr"))
    monkeypatch.setattr(remote.subprocess, "run", process)
    with pytest.raises(remote.InspectionError, match="diagnostic_artifact_unavailable"):
        remote.load_bundle(artifact, {})
    artifact["bucket"] = "unreviewed-bucket"
    with pytest.raises(remote.InspectionError, match="invalid_diagnostic_artifact"):
        remote.load_bundle(artifact, {})
    assert process.call_count == 1


def test_full_candidate_source_receipt_fits_inline_ssm_transport(monkeypatch, capsys):
    references = runner.references(remote.CANDIDATE)
    files = {name: {"sha256": sha, "uid": 0, "gid": 0, "mode": "0644", "bytes": 1234}
             for name, sha in references.items()}
    receipt = {"status": "inspected", "installed": {"source": {"files": files}},
               "source_comparison": {name: {"matches_base": False, "matches_candidate": True} for name in files}}
    monkeypatch.setattr(remote, "inspect", lambda *_: receipt)
    remote.execute({}, {})
    raw = capsys.readouterr().out
    assert len(raw) < 24000
    assert runner.decode_receipt(raw) == receipt


def test_remote_failure_message_never_leaves_receipt(monkeypatch, capsys):
    monkeypatch.setattr(remote, "inspect", Mock(side_effect=RuntimeError("private password and row")))
    remote.execute({}, {})
    result = runner.decode_receipt(capsys.readouterr().out)
    assert result["error_code"] == "inspection_failed" and "private" not in json.dumps(result)


def test_runner_clears_current_public_bundle_even_on_inspection_failure(monkeypatch, capsys):
    uploads = []

    def aws(*args):
        assert args[:2] == ("s3api", "put-object")
        uploads.append(Path(args[args.index("--body") + 1]).read_bytes())
        assert args[args.index("--server-side-encryption") + 1] == "AES256"
        return {}

    monkeypatch.setattr(runner, "git", lambda *_: b"a" * 40)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setattr(runner, "diagnostic_bundle", lambda: (b"public source only", {}))
    monkeypatch.setattr(runner, "aws", aws)
    monkeypatch.setattr(runner, "inspect_target", Mock(side_effect=runner.RunnerError("remote_inspection_failed")))
    with pytest.raises(runner.RunnerError, match="remote_inspection_failed"):
        runner.run()
    assert uploads == [b"public source only", b""]
    assert "current_diagnostic_object_cleared" in capsys.readouterr().out


def test_collector_checks_head_before_logs_and_retains_markers_only(monkeypatch, tmp_path):
    meta = {"headSha": "a" * 40, "status": "completed", "conclusion": "success"}
    command = Mock(return_value=json.dumps(meta))
    monkeypatch.setattr(collector, "command", command)
    with pytest.raises(RuntimeError, match="operation_head_mismatch"):
        collector.collect("123", "b" * 40, tmp_path)
    assert command.call_count == 1
    command.side_effect = [json.dumps(meta), 'PRIVATE RAW LOG\nstep TAU_PERPS_READINESS_INVENTORY={"status":"inspected"}\n']
    result = collector.collect("123", "a" * 40, tmp_path)
    assert len(result["records"]) == 1
    assert "PRIVATE" not in (tmp_path / "READINESS_123.json").read_text()


def test_actual_native_client_and_collector_keep_partial_warning_without_raw_prices(monkeypatch):
    from app import kalshi_perps_data as data
    from tests.test_kalshi_perps_data import END, NOW, Response, candle_row, instrument_row

    responses = iter([Response({"markets": [instrument_row()]}),
                      Response({"ticker": "SYNTHBTC", "candlesticks": [candle_row()]}),
                      Response({"funding_rates": [{"market_ticker": "SYNTHBTC", "funding_time": END - 3600,
                                                   "funding_rate": "0.0001", "mark_price": "7.1500"}]}),
                      Response({"market": instrument_row()}), Response({})])
    calls = []

    def get(session, url, **kwargs):
        calls.append((session, url, kwargs))
        return next(responses)

    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setattr(public.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(public, "KalshiPerpsDataClient", lambda cfg, session:
                        data.KalshiPerpsDataClient(cfg, session=session, clock=lambda: NOW, sleep=lambda _: None))
    monkeypatch.setenv("TAU_KALSHI_PERPS_PROXY_URL", "http://127.0.0.1:7890")
    monkeypatch.setenv("PROD_KEYFILE", "/private/key.pem")
    result = public.run()
    assert result["status"] == "checked" and result["candle_count"] == 1 and result["funding_count"] == 1
    assert result["partial_candle_warning"] is True and not result["replay_accepted"]
    assert result["readable_history_and_funding"] is True
    assert len(calls) == 5 and len(result["http_events"]) == 5
    assert all(url.startswith(data.BASE_URLS["production"] + "/margin/") for _, url, _ in calls)
    assert all(kwargs["auth"] == () and kwargs["cookies"] == {} and not kwargs["allow_redirects"] for _, _, kwargs in calls)
    assert all(kwargs["proxies"] == {"https": "http://127.0.0.1:7890"} for _, _, kwargs in calls)
    encoded = json.dumps(result)
    assert "7.1500" not in encoded and "/private/" not in encoded and "SYNTHBTC" not in encoded


def test_workflow_is_dispatch_only_and_has_no_release_inputs_or_deploy_concurrency():
    root = HERE.parents[3]
    workflow = (root / ".github/workflows/deploy.yml").read_text()
    assert "workflow_dispatch:" in workflow and "inputs:" not in workflow
    assert "group: kalshi-perps-readiness" in workflow and "group: deploy-web" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert "deploy_web.sh" not in workflow and "schema" not in workflow and "restart" not in workflow
