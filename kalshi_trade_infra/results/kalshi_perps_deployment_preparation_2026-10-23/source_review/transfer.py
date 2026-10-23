"""Fixed eight-file envelope: AES-256-GCM and RSA-OAEP-SHA256, no file I/O."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import zlib


SCHEMA = "tau-selected-source-aesgcm-rsaoaep-v1"
RECIPIENT_PEM_SHA256 = "24746c869bcda8ae3c177a0c0a355939a7504f3a795443492696acf0317ccec8"
PAGE_BYTES = 12000
MAX_PAGES = 64
MAX_ENVELOPE = PAGE_BYTES * MAX_PAGES
MAX_PLAINTEXT = 2 * 1024 * 1024
PINS = {
    "app/agent.py": {"bytes": 173625, "sha256": "c78ee13f989b038e4bafc24da684a851bf2121dc8ac70827f9c442ef9902c4da"},
    "app/billing.py": {"bytes": 13576, "sha256": "0fd9b234d03df7db3c83ac0c45f487063f8eaa37f677fcfa37971708d3d3baef"},
    "app/devlog.py": {"bytes": 101322, "sha256": "913520e1fd7686a689b4738ed8a7d8eb14540b9497131cccdea80075cc80fab7"},
    "app/llm.py": {"bytes": 22318, "sha256": "1ce41cbc588c116d26adc33c041b4576ed793fe188146229cb1367cfd7129444"},
    "app/repository.py": {"bytes": 102323, "sha256": "2cb1037da11b513f6389cbfd5eb139e9861b718e37de09b0ef64fcdc962fc5c7"},
    "app/schema.py": {"bytes": 39642, "sha256": "6738460234b7e46ff230cb64e287354e2e3e0f46a548f8fb504ef17c476c1084"},
    "app/server.py": {"bytes": 107139, "sha256": "8d93c845e51c7b46696725f99ab18e20c2b5ce0041f52ac56d81a0410e7cea68"},
    "app/static/app.js": {"bytes": 282132, "sha256": "6d290678e2b9b96887f83a7f0fd8a095d95c3df002846c656f58c6febd1742e7"},
}


class TransferError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_files(files):
    if set(files) != set(PINS):
        raise TransferError("source_paths_not_exact")
    for name, raw in files.items():
        if not isinstance(raw, bytes) or len(raw) != PINS[name]["bytes"] or digest(raw) != PINS[name]["sha256"]:
            raise TransferError("source_pin_mismatch")


def public_key(pem):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    if digest(pem) != RECIPIENT_PEM_SHA256:
        raise TransferError("recipient_key_mismatch")
    try:
        key = serialization.load_pem_public_key(pem)
        if not isinstance(key, rsa.RSAPublicKey) or not 3072 <= key.key_size <= 4096 or key.public_numbers().e != 65537:
            raise ValueError()
        return key
    except Exception:
        raise TransferError("invalid_recipient_key") from None


def encrypt(files, pem, capture_id, operations_sha, metadata):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    validate_files(files)
    recipient = public_key(pem)
    if not re.fullmatch(r"[0-9a-f]{32}", capture_id) or not re.fullmatch(r"[0-9a-f]{40}", operations_sha):
        raise TransferError("invalid_capture_identity")
    if len(canonical(metadata)) > 16000:
        raise TransferError("metadata_limit")
    header = {"schema": SCHEMA, "capture_id": capture_id, "operations_sha": operations_sha,
              "recipient_pem_sha256": RECIPIENT_PEM_SHA256, "files": PINS, "metadata": metadata}
    plaintext = canonical({"files": {name: base64.b64encode(raw).decode() for name, raw in files.items()}})
    if len(plaintext) > MAX_PLAINTEXT:
        raise TransferError("source_size_limit")
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, zlib.compress(plaintext), canonical(header))
    wrapped = recipient.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                algorithm=hashes.SHA256(), label=SCHEMA.encode()))
    envelope = canonical({"header": header, "nonce": base64.b64encode(nonce).decode(),
                          "wrapped_key": base64.b64encode(wrapped).decode(),
                          "ciphertext": base64.b64encode(ciphertext).decode()})
    if len(envelope) > MAX_ENVELOPE:
        raise TransferError("encrypted_page_limit")
    return envelope


def decrypt(envelope, private_pem, expected_operations_sha):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        if len(envelope) > MAX_ENVELOPE:
            raise ValueError()
        value = json.loads(envelope)
        if set(value) != {"header", "nonce", "wrapped_key", "ciphertext"}:
            raise ValueError()
        header = value["header"]
        if (set(header) != {"schema", "capture_id", "operations_sha", "recipient_pem_sha256", "files", "metadata"}
                or header["schema"] != SCHEMA or header["operations_sha"] != expected_operations_sha
                or header["recipient_pem_sha256"] != RECIPIENT_PEM_SHA256 or header["files"] != PINS
                or not re.fullmatch(r"[0-9a-f]{32}", header["capture_id"])):
            raise ValueError()
        private = serialization.load_pem_private_key(private_pem, password=None)
        if not isinstance(private, rsa.RSAPrivateKey):
            raise ValueError()
        public_pem = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        public_key(public_pem)
        nonce = base64.b64decode(value["nonce"], validate=True)
        if len(nonce) != 12:
            raise ValueError()
        key = private.decrypt(base64.b64decode(value["wrapped_key"], validate=True),
                              padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=SCHEMA.encode()))
        if len(key) != 32:
            raise ValueError()
        packed = AESGCM(key).decrypt(nonce, base64.b64decode(value["ciphertext"], validate=True), canonical(header))
        inflater = zlib.decompressobj()
        raw = inflater.decompress(packed, MAX_PLAINTEXT + 1)
        if len(raw) > MAX_PLAINTEXT or not inflater.eof or inflater.unused_data:
            raise ValueError()
        payload = json.loads(raw)
        if set(payload) != {"files"}:
            raise ValueError()
        files = {name: base64.b64decode(value, validate=True) for name, value in payload["files"].items()}
        validate_files(files)
        return files, header
    except Exception:
        raise TransferError("envelope_authentication_failed") from None
