"""Synthetic crypto/files/process receipts only; no actual private key or network."""
from __future__ import annotations

import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import zlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


HERE = Path(__file__).resolve().parent
OPS_SHA = "a" * 40
CAPTURE_ID = "b" * 32


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


transfer = load("source_review_transfer", HERE / "transfer.py")
previous_transfer = sys.modules.get("transfer")
sys.modules["transfer"] = transfer
runner = load("source_review_runner", HERE / "runner.py")
collector = load("source_review_collector", HERE / "collect.py")
if previous_transfer is None:
    sys.modules.pop("transfer", None)
else:
    sys.modules["transfer"] = previous_transfer
capture = load("source_review_capture", HERE / "capture.py")
guard = load("source_review_reused_guard", HERE.parents[1] / "kalshi_bitcoin_perps_2026-10-23/operations/remote.py")


@pytest.fixture(scope="module")
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    private_pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return public, private_pem


@pytest.fixture
def synthetic(monkeypatch, keys):
    public, private = keys
    files = {name: ("SYNTHETIC-SOURCE-NEVER-LOG-" + name + "\n").encode() * 3 for name in transfer.PINS}
    pins = {name: {"bytes": len(raw), "sha256": transfer.digest(raw)} for name, raw in files.items()}
    monkeypatch.setattr(transfer, "PINS", pins)
    monkeypatch.setattr(transfer, "RECIPIENT_PEM_SHA256", transfer.digest(public))
    return files, public, private


def test_real_public_pem_and_exact_eight_production_source_pins():
    pem = (HERE / "recipient.pub.pem").read_bytes()
    assert transfer.digest(pem) == "24746c869bcda8ae3c177a0c0a355939a7504f3a795443492696acf0317ccec8"
    assert transfer.public_key(pem).key_size == 3072
    assert set(transfer.PINS) == {"app/agent.py", "app/billing.py", "app/devlog.py", "app/llm.py",
                                   "app/repository.py", "app/schema.py", "app/server.py", "app/static/app.js"}
    assert sum(pin["bytes"] for pin in transfer.PINS.values()) == 842077


def test_real_rsa_oaep_aesgcm_roundtrip_contains_no_plain_source(synthetic):
    files, public, private = synthetic
    encrypted = transfer.encrypt(files, public, CAPTURE_ID, OPS_SHA, {"running_research": 1})
    decoded, header = transfer.decrypt(encrypted, private, OPS_SHA)
    assert decoded == files and header["metadata"] == {"running_research": 1}
    assert b"SYNTHETIC-SOURCE-NEVER-LOG" not in encrypted
    assert all(base64.b64encode(raw) not in encrypted for raw in files.values())
    assert encrypted != transfer.encrypt(files, public, CAPTURE_ID, OPS_SHA, {"running_research": 1})


@pytest.mark.parametrize("field", ["ciphertext", "nonce", "wrapped_key", "metadata", "operations_sha"])
def test_tampered_ciphertext_nonce_key_or_authenticated_metadata_is_rejected(synthetic, field):
    files, public, private = synthetic
    value = json.loads(transfer.encrypt(files, public, CAPTURE_ID, OPS_SHA, {"running_research": 1}))
    if field in {"metadata", "operations_sha"}:
        value["header"][field] = {} if field == "metadata" else "f" * 40
    else:
        raw = bytearray(base64.b64decode(value[field]))
        raw[0] ^= 1
        value[field] = base64.b64encode(raw).decode()
    with pytest.raises(transfer.TransferError, match="^envelope_authentication_failed$"):
        transfer.decrypt(transfer.canonical(value), private, OPS_SHA)


def test_unapproved_paths_changed_size_hash_and_recipient_are_rejected(synthetic):
    files, public, _ = synthetic
    with pytest.raises(transfer.TransferError, match="source_paths_not_exact"):
        transfer.encrypt({**files, ".env": b"private"}, public, CAPTURE_ID, OPS_SHA, {})
    bad = dict(files)
    bad["app/agent.py"] += b"x"
    with pytest.raises(transfer.TransferError, match="source_pin_mismatch"):
        transfer.encrypt(bad, public, CAPTURE_ID, OPS_SHA, {})
    with pytest.raises(transfer.TransferError, match="recipient_key_mismatch"):
        transfer.encrypt(files, b"unreviewed public key", CAPTURE_ID, OPS_SHA, {})


def test_encrypted_size_cap_fails_before_temporary_file_creation(prepared, monkeypatch):
    _, public, _, _, staging = prepared
    monkeypatch.setattr(transfer, "MAX_ENVELOPE", 128)
    with pytest.raises(transfer.TransferError, match="encrypted_page_limit"):
        capture.capture(CAPTURE_ID, public, OPS_SHA, "", guard, transfer)
    assert list(staging.iterdir()) == []


def state():
    return {"source": {"files": copy.deepcopy(transfer.PINS)},
            "controls": {"units": {name: {"pid": i + 100, "perps": {"enabled": False}}
                                    for i, name in enumerate(("recursive-web", "recursive-agents", "recursive-engine"))},
                         "processes": {}, "protected_config": {}}}


@pytest.fixture
def prepared(tmp_path, monkeypatch, synthetic):
    files, public, private = synthetic
    installed = tmp_path / "installed"
    for name, raw in files.items():
        path = installed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o644)
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(capture, "TEMP_ROOT", staging)
    monkeypatch.setattr(capture, "ROOT_UID", os.geteuid())
    monkeypatch.setattr(guard, "ROOT", installed)
    before = state()
    monkeypatch.setattr(guard, "snapshot", Mock(side_effect=[(copy.deepcopy(before), {"recursive-agents": {}}),
                                                           (copy.deepcopy(before), {"recursive-agents": {}})]))
    monkeypatch.setattr(capture, "database_counts", Mock(return_value={"status": "checked", "research_counts": {"running": 1}}))
    return files, public, private, installed, staging


def test_capture_pages_decrypt_cleanup_and_installed_files_unchanged(prepared):
    files, public, private, installed, staging = prepared
    receipt = capture.capture(CAPTURE_ID, public, OPS_SHA, "synthetic repository helper", guard, transfer)
    directory = capture.directory(CAPTURE_ID)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / "envelope").stat().st_mode) == 0o600
    pages = [capture.page(CAPTURE_ID, i, receipt["envelope_sha256"], guard, transfer) for i in range(receipt["pages"])]
    encrypted = b"".join(base64.b64decode(page["data"]) for page in pages)
    decoded, header = transfer.decrypt(encrypted, private, OPS_SHA)
    assert decoded == files
    assert header["metadata"]["perps_off_in_all_active_services"] is True
    assert header["metadata"]["protected_environment_files_read"] is False
    assert b"SYNTHETIC-SOURCE-NEVER-LOG" not in encrypted
    assert "SYNTHETIC-SOURCE-NEVER-LOG" not in json.dumps(receipt)
    assert all((installed / name).read_bytes() == raw for name, raw in files.items())
    assert capture.cleanup(CAPTURE_ID)["temporary_directory_removed"] is True
    assert not directory.exists() and list(staging.iterdir()) == []


@pytest.mark.parametrize("service", ["recursive-web", "recursive-agents", "recursive-engine"])
def test_enabled_flags_stop_before_source_reads_database_or_staging(prepared, monkeypatch, service):
    _, public, _, _, staging = prepared
    before = state()
    before["controls"]["units"][service]["perps"]["enabled"] = True
    monkeypatch.setattr(guard, "snapshot", lambda: (before, {}))
    read = Mock(side_effect=AssertionError("must not read source"))
    monkeypatch.setattr(guard, "read_regular", read)
    with pytest.raises(capture.CaptureError, match="unexpected_perps_enabled"):
        capture.capture(CAPTURE_ID, public, OPS_SHA, "", guard, transfer)
    read.assert_not_called()
    capture.database_counts.assert_not_called()
    assert list(staging.iterdir()) == []


def test_source_pin_mismatch_stops_before_database_or_staging(prepared):
    _, public, _, installed, staging = prepared
    path = installed / "app/agent.py"
    raw = path.read_bytes()
    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises(transfer.TransferError, match="source_pin_mismatch"):
        capture.capture(CAPTURE_ID, public, OPS_SHA, "", guard, transfer)
    capture.database_counts.assert_not_called()
    assert list(staging.iterdir()) == []


def test_source_or_control_drift_prevents_encrypted_staging(prepared, monkeypatch):
    _, public, _, _, staging = prepared
    before, after = state(), state()
    after["controls"]["units"]["recursive-agents"]["pid"] += 1
    monkeypatch.setattr(guard, "snapshot", Mock(side_effect=[(before, {"recursive-agents": {}}), (after, {})]))
    with pytest.raises(capture.CaptureError, match="source_or_controls_changed"):
        capture.capture(CAPTURE_ID, public, OPS_SHA, "", guard, transfer)
    assert list(staging.iterdir()) == []


def test_page_hash_change_and_symlink_capture_directory_fail_closed(prepared):
    _, public, _, _, staging = prepared
    receipt = capture.capture(CAPTURE_ID, public, OPS_SHA, "", guard, transfer)
    with pytest.raises(capture.CaptureError, match="encrypted_page_mismatch"):
        capture.page(CAPTURE_ID, 0, "f" * 64, guard, transfer)
    capture.cleanup(CAPTURE_ID)
    capture.directory(CAPTURE_ID).symlink_to(staging, target_is_directory=True)
    with pytest.raises(capture.CaptureError, match="unsafe_capture_directory"):
        capture.cleanup(CAPTURE_ID)


def test_database_child_receives_only_mysql_env_and_no_raw_stderr(monkeypatch):
    seen = []

    def run(args, **kwargs):
        seen.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, b'{"status":"checked","research_counts":{"running":1}}', b"private logs")

    monkeypatch.setattr(capture.subprocess, "run", run)
    env = {"MYSQL_HOST": "private-db", "MYSQL_PASSWORD": "private-password", "APP_SECRET_KEY": "private-key",
           "PROD_KEYFILE": "/private/provider.pem", "HTTPS_PROXY": "http://private:secret@proxy.invalid"}
    result = capture.database_counts("reviewed helper source", env, guard)
    child_env = seen[0][1]["env"]
    assert set(child_env) == {"PATH", "LANG", "TZ", "PYTHONDONTWRITEBYTECODE", "MYSQL_HOST", "MYSQL_PASSWORD"}
    assert seen[0][0][:3] == [guard.PYTHON, "-B", "-c"]
    assert "private" not in json.dumps(result)


def test_actual_ssm_program_is_bounded_encryption_only_and_suppresses_config_file_reads():
    command = runner.program("capture", CAPTURE_ID, OPS_SHA)
    assert len(command) < 24000
    launcher = shlex.split(command)[-1]
    # Extract only the fixed packed bytes; never execute the target capture.
    encoded = launcher.split("base64.b64decode(", 1)[1].split(")", 1)[0]
    import ast
    source = zlib.decompress(base64.b64decode(ast.literal_eval(encoded))).decode()
    assert "g['CONFIG']=()" in source
    assert "load_pem_private_key" not in source
    assert "TAU_KALSHI_PERPS_PROXY_URL" in source  # hash/flag guard definition only
    assert "c['capture'](" in source and "c['inspect'](" not in source
    compile(source, "<source-capture-program>", "exec")


def test_runner_cleanup_occurs_on_capture_failure_without_s3(monkeypatch, capsys):
    calls = []

    def request(mode, capture_id, operations_sha, deadline, **kwargs):
        calls.append(mode)
        if mode == "capture":
            raise runner.RunnerError("source_pin_mismatch")
        return {"status": "cleaned", "temporary_directory_removed": True}

    monkeypatch.setattr(runner, "git", lambda *_: OPS_SHA.encode())
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setattr(runner, "request", request)
    with pytest.raises(runner.RunnerError, match="source_pin_mismatch"):
        runner.run()
    assert calls == ["capture", "cleanup"]
    assert "CLEANUP" in capsys.readouterr().out


def test_runner_rejects_excessive_page_count_and_still_cleans(monkeypatch):
    calls = []

    def request(mode, capture_id, operations_sha, deadline, **kwargs):
        calls.append(mode)
        if mode == "capture":
            return {"status": "captured", "capture_id": capture_id, "pages": 65, "envelope_sha256": "a" * 64}
        return {"status": "cleaned", "temporary_directory_removed": True}

    monkeypatch.setattr(runner, "git", lambda *_: OPS_SHA.encode())
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setattr(runner, "request", request)
    with pytest.raises(runner.RunnerError, match="invalid_capture_receipt"):
        runner.run()
    assert calls == ["capture", "cleanup"]


def test_transport_calls_only_ssm_and_retains_sanitized_remote_code(monkeypatch, capsys):
    responses = iter([{"Command": {"CommandId": "synthetic-command"}},
                      {"Status": "Success", "StandardOutputContent": '{"status":"error","error_code":"source_pin_mismatch"}',
                       "StandardErrorContent": "private stderr must never print"}])
    calls = []

    def aws(*args):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(runner, "aws", aws)
    monkeypatch.setattr(runner, "program", lambda *_a, **_k: "synthetic bounded program")
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    with pytest.raises(runner.RunnerError, match="^source_pin_mismatch$"):
        runner.request("capture", CAPTURE_ID, OPS_SHA, runner.time.monotonic() + 20)
    assert [args[:2] for args in calls] == [("ssm", "send-command"), ("ssm", "get-command-invocation")]
    assert "private" not in capsys.readouterr().out


def receipts(envelope, metadata, page_bytes=None):
    size = page_bytes or transfer.PAGE_BYTES
    count = (len(envelope) + size - 1) // size
    sha = transfer.digest(envelope)
    values = [
        {"type": "PREFLIGHT", "receipt": {"operations_sha": OPS_SHA, "capture_id": CAPTURE_ID,
            "selected_source_pins": transfer.PINS, "recipient_pem_sha256": transfer.RECIPIENT_PEM_SHA256}},
        {"type": "CAPTURE", "receipt": {"status": "captured", "capture_id": CAPTURE_ID,
            "pages": count, "envelope_bytes": len(envelope), "envelope_sha256": sha, "metadata": metadata}},
        {"type": "CLEANUP", "receipt": {"status": "cleaned", "capture_id": CAPTURE_ID, "temporary_directory_removed": True}},
    ]
    for index in range(count):
        raw = envelope[index * size:(index + 1) * size]
        values.append({"type": "PAGE", "receipt": {"status": "encrypted_page", "capture_id": CAPTURE_ID,
            "index": index, "pages": count, "envelope_sha256": sha, "page_sha256": transfer.digest(raw),
            "data": base64.b64encode(raw).decode()}})
    return values


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "hash", "cleanup", "error"])
def test_collector_rejects_incomplete_duplicate_tampered_or_uncleaned_pages(synthetic, mutation):
    files, public, _ = synthetic
    envelope = transfer.encrypt(files, public, CAPTURE_ID, OPS_SHA, {})
    items = receipts(envelope, {})
    if mutation == "missing":
        items = items[:-1]
    elif mutation == "duplicate":
        items.append(items[-1])
    elif mutation == "hash":
        items[-1]["receipt"]["page_sha256"] = "f" * 64
    elif mutation == "cleanup":
        items[2]["receipt"]["temporary_directory_removed"] = False
    else:
        items.append({"type": "ERROR", "receipt": {"status": "failed"}})
    with pytest.raises(collector.CollectionError):
        collector.assemble(items, OPS_SHA)


def test_multiple_encrypted_pages_reassemble_in_index_order(synthetic, monkeypatch):
    files, public, private = synthetic
    envelope = transfer.encrypt(files, public, CAPTURE_ID, OPS_SHA, {})
    monkeypatch.setattr(transfer, "PAGE_BYTES", 250)
    items = receipts(envelope, {}, 250)
    assembled, _ = collector.assemble(list(reversed(items)), OPS_SHA)
    assert transfer.decrypt(assembled, private, OPS_SHA)[0] == files


def test_local_collection_writes_only_validated_sources_to_private_outside_git(tmp_path, monkeypatch, synthetic):
    files, public, private = synthetic
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    key_path = private_root / "synthetic-private.pem"
    key_path.write_bytes(private)
    key_path.chmod(0o600)
    destination = private_root / "capture"
    monkeypatch.setattr(collector, "PRIVATE_ROOT", private_root)
    envelope = transfer.encrypt(files, public, CAPTURE_ID, OPS_SHA, {"running_research": 1})
    logs = "unretained raw Actions log\n" + "\n".join("step TAU_PERPS_SOURCE_" + item["type"] + "=" + json.dumps(item["receipt"])
                                                        for item in receipts(envelope, {"running_research": 1}))
    meta = {"headSha": OPS_SHA, "status": "completed", "conclusion": "success"}
    monkeypatch.setattr(collector, "command", Mock(side_effect=[json.dumps(meta), logs]))
    result = collector.collect("123", OPS_SHA, key_path, destination)
    assert result["status"] == "decrypted_locally"
    assert all((destination / name).read_bytes() == raw for name, raw in files.items())
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in destination.rglob("*") if path.is_file())
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in destination.rglob("*") if path.is_dir())
    assert "unretained raw" not in (destination / "CAPTURE_RECEIPT.json").read_text()
    assert "SYNTHETIC-SOURCE-NEVER-LOG" not in json.dumps(result)


def test_wrong_workflow_head_prevents_log_fetch_and_private_key_read(tmp_path, monkeypatch):
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    monkeypatch.setattr(collector, "PRIVATE_ROOT", private_root)
    command = Mock(return_value=json.dumps({"headSha": "f" * 40, "status": "completed", "conclusion": "success"}))
    monkeypatch.setattr(collector, "command", command)
    key = Mock(side_effect=AssertionError("must not read key"))
    monkeypatch.setattr(collector, "read_private_key", key)
    with pytest.raises(collector.CollectionError, match="operation_head_mismatch"):
        collector.collect("123", OPS_SHA, private_root / "key.pem", private_root / "capture")
    assert command.call_count == 1
    key.assert_not_called()


def test_nonprivate_output_and_permissive_private_key_are_rejected(tmp_path, monkeypatch):
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    monkeypatch.setattr(collector, "PRIVATE_ROOT", private_root)
    with pytest.raises(collector.CollectionError, match="private_output_location_rejected"):
        collector.collect("123", OPS_SHA, private_root / "key.pem", tmp_path / "public-output")
    key_path = private_root / "key.pem"
    key_path.write_text("synthetic key, never parsed")
    key_path.chmod(0o644)
    with pytest.raises(collector.CollectionError, match="unsafe_private_key"):
        collector.read_private_key(key_path)


def test_workflow_has_only_selected_source_runner_and_distinct_concurrency():
    workflow = (HERE.parents[3] / ".github/workflows/deploy.yml").read_text()
    assert "workflow_dispatch:" in workflow and "inputs:" not in workflow
    assert "group: kalshi-perps-selected-source-review" in workflow
    assert "group: deploy-web" not in workflow and "cancel-in-progress: false" in workflow
    assert "source_review/runner.py" in workflow
    assert "operations/runner.py" not in workflow and "deploy_web.sh" not in workflow
    assert "recipient" not in workflow and "PRIVATE_KEY" not in workflow
