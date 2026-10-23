"""Root-only local collection/decryption into the approved outside-Git directory."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

import transfer


REPO = "JihuiTanUchicago/kalshi_trade"
PRIVATE_ROOT = Path("/Users/jonathanzhang/Desktop/Polygon/.runtime/private/kalshi-perps-source-review-20261023")
MARKER = re.compile(r"TAU_PERPS_SOURCE_(PREFLIGHT|PHASE|CAPTURE|PAGE|CLEANUP|ERROR)=(\{.*\})\s*$")


class CollectionError(RuntimeError):
    pass


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise CollectionError("receipt_request_failed") from None
    return result.stdout


def records(raw):
    if len(raw) > 8 * 1024 * 1024:
        raise CollectionError("log_memory_limit")
    output = []
    for line in raw.splitlines():
        match = MARKER.search(line)
        if match:
            value = json.loads(match[2])
            if not isinstance(value, dict):
                raise CollectionError("invalid_fixed_receipt")
            output.append({"type": match[1], "receipt": value})
    return output


def assemble(items, expected_sha):
    def one(kind):
        values = [row["receipt"] for row in items if row["type"] == kind]
        if len(values) != 1:
            raise CollectionError("incomplete_capture_receipts")
        return values[0]

    preflight, capture, cleanup = one("PREFLIGHT"), one("CAPTURE"), one("CLEANUP")
    if (any(row["type"] == "ERROR" for row in items)
            or preflight.get("operations_sha") != expected_sha or preflight.get("selected_source_pins") != transfer.PINS
            or preflight.get("recipient_pem_sha256") != transfer.RECIPIENT_PEM_SHA256
            or capture.get("status") != "captured" or cleanup.get("status") != "cleaned"
            or cleanup.get("temporary_directory_removed") is not True
            or capture.get("capture_id") != preflight.get("capture_id")
            or capture.get("capture_id") != cleanup.get("capture_id")
            or type(capture.get("pages")) is not int or not 1 <= capture["pages"] <= transfer.MAX_PAGES):
        raise CollectionError("capture_receipts_rejected")
    pages = [row["receipt"] for row in items if row["type"] == "PAGE"]
    if len(pages) != capture["pages"]:
        raise CollectionError("encrypted_pages_incomplete")
    by_index = {}
    for page in pages:
        index = page.get("index")
        content = base64.b64decode(page.get("data", ""), validate=True)
        if (type(index) is not int or not 0 <= index < capture["pages"] or index in by_index
                or page.get("status") != "encrypted_page" or page.get("capture_id") != capture["capture_id"]
                or page.get("pages") != capture["pages"] or page.get("envelope_sha256") != capture.get("envelope_sha256")
                or not 1 <= len(content) <= transfer.PAGE_BYTES
                or index < capture["pages"] - 1 and len(content) != transfer.PAGE_BYTES
                or page.get("page_sha256") != transfer.digest(content)):
            raise CollectionError("encrypted_page_mismatch")
        by_index[index] = content
    envelope = b"".join(by_index[index] for index in range(capture["pages"]))
    if (len(envelope) != capture.get("envelope_bytes") or len(envelope) > transfer.MAX_ENVELOPE
            or transfer.digest(envelope) != capture.get("envelope_sha256")):
        raise CollectionError("encrypted_envelope_mismatch")
    return envelope, capture


def check_private_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise CollectionError("unsafe_private_directory")


def read_private_key(path):
    path = Path(path)
    if path.parent != PRIVATE_ROOT:
        raise CollectionError("private_key_location_rejected")
    check_private_directory(PRIVATE_ROOT)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16384):
            raise CollectionError("unsafe_private_key")
        return stream.read(16385)


def write_file(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def collect(run_id, expected_sha, private_key_path, destination):
    if not re.fullmatch(r"[1-9][0-9]{0,19}", run_id) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise CollectionError("exact_operation_pin_required")
    destination = Path(destination)
    if destination.parent != PRIVATE_ROOT or destination.exists() or destination.is_symlink():
        raise CollectionError("private_output_location_rejected")
    check_private_directory(PRIVATE_ROOT)
    meta = json.loads(command("gh", "run", "view", run_id, "--repo", REPO, "--json",
                              "databaseId,status,conclusion,headSha,url"))
    if meta.get("headSha") != expected_sha:
        raise CollectionError("operation_head_mismatch")
    if meta.get("status") != "completed" or meta.get("conclusion") != "success":
        raise CollectionError("operation_not_successful")
    raw = command("gh", "run", "view", run_id, "--repo", REPO, "--log")
    items = records(raw)
    raw = None
    envelope, receipt = assemble(items, expected_sha)
    files, header = transfer.decrypt(envelope, read_private_key(private_key_path), expected_sha)
    if header["capture_id"] != receipt["capture_id"] or header["metadata"] != receipt["metadata"]:
        raise CollectionError("authenticated_metadata_mismatch")
    destination.mkdir(mode=0o700)
    try:
        for name, content in files.items():
            path = destination / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_file(path, content)
        write_file(destination / "SOURCE.encrypted.json", envelope)
        safe = {"workflow": meta, "records": [row for row in items if row["type"] != "PAGE"]}
        write_file(destination / "CAPTURE_RECEIPT.json", json.dumps(safe, indent=2).encode() + b"\n")
    except Exception:
        shutil.rmtree(destination)
        raise
    return {"status": "decrypted_locally", "capture_id": header["capture_id"],
            "files": transfer.PINS, "source_bytes": sum(len(raw) for raw in files.values()),
            "private_files_mode": "0600", "private_directories_mode": "0700"}


if __name__ == "__main__":
    try:
        if len(sys.argv) != 5:
            raise CollectionError("arguments_required")
        print(json.dumps(collect(*sys.argv[1:]), sort_keys=True))
    except Exception:
        print(json.dumps({"status": "source_collection_requires_inspection"}))
        raise SystemExit(1)
