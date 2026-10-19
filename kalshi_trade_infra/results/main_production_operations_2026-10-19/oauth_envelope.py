"""Ephemeral RSA-OAEP credential transport; only ciphertext leaves the sender.

The receiver keeps its private key in a private directory under /run.  Credentials
and decrypted chunks are passed to OpenSSL through pipes, never command arguments
or plaintext files.  All public operations expose one fixed error message.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess


FIELDS = ("ALPACA_OAUTH_CLIENT_ID", "ALPACA_OAUTH_CLIENT_SECRET")
CHUNK_BYTES = 400
MAX_FIELD_BYTES = 4096
MAX_CHUNKS = (MAX_FIELD_BYTES + CHUNK_BYTES - 1) // CHUNK_BYTES
MAX_ENVELOPE_BYTES = 65536
KEY_FILE = "private_key.pem"
_SESSION = re.compile(r"tau-provider-probe-[0-9a-f]{32}\Z")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


class EnvelopeError(RuntimeError):
    def __init__(self):
        super().__init__("Credential envelope operation failed.")


def _session(value):
    if not isinstance(value, str) or not _SESSION.fullmatch(value):
        raise EnvelopeError()
    return value


def _root_fd(root):
    """Walk every directory with O_NOFOLLOW, without path-resolution races."""
    path = Path(root)
    if not path.is_absolute() or ".." in path.parts or len(str(path)) > 4096:
        raise EnvelopeError()
    fd = os.open("/", _DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _private_stat(fd, mode, directory=False):
    info = os.fstat(fd)
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode:
        raise EnvelopeError()
    if not directory and (info.st_nlink != 1 or not 1 <= info.st_size <= 16384):
        raise EnvelopeError()


def _session_fd(root_fd, session):
    fd = os.open(_session(session), _DIR_FLAGS, dir_fd=root_fd)
    try:
        _private_stat(fd, 0o700, directory=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _run(args, data=None, *, pass_fds=(), output_fd=None, timeout=30):
    result = subprocess.run(
        ["openssl", *args], input=data,
        stdout=subprocess.PIPE if output_fd is None else output_fd,
        stderr=subprocess.PIPE, pass_fds=pass_fds, timeout=timeout,
        check=False, close_fds=True,
    )
    if result.returncode or (result.stdout is not None and len(result.stdout) > 16384):
        raise EnvelopeError()
    return result.stdout


def _credentials(credentials):
    if not isinstance(credentials, dict) or set(credentials) != set(FIELDS):
        raise EnvelopeError()
    encoded = {}
    for field in FIELDS:
        value = credentials[field]
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_FIELD_BYTES or not value.strip():
            raise EnvelopeError()
        raw = value.encode("utf-8")
        if not 1 <= len(raw) <= MAX_FIELD_BYTES:
            raise EnvelopeError()
        encoded[field] = raw
    return encoded


def _options(session, field, index, count):
    label = "\0".join(("tau-provider-envelope-v1", session, field, str(index), str(count))).encode("ascii")
    return [
        "-pkeyopt", "rsa_padding_mode:oaep",
        "-pkeyopt", "rsa_oaep_md:sha256",
        "-pkeyopt", "rsa_mgf1_md:sha256",
        "-pkeyopt", "rsa_oaep_label:" + label.hex(),
    ]


def create_session(root: Path = Path("/run")) -> dict:
    root_fd = directory_fd = key_fd = None
    session = None
    created = False
    try:
        root_fd = _root_fd(root)
        session = "tau-provider-probe-" + secrets.token_hex(16)
        os.mkdir(session, 0o700, dir_fd=root_fd)
        created = True
        directory_fd = os.open(session, _DIR_FLAGS, dir_fd=root_fd)
        os.fchmod(directory_fd, 0o700)
        key_fd = os.open(KEY_FILE, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory_fd)
        os.fchmod(key_fd, 0o600)
        _run(["genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:4096"],
             output_fd=key_fd, timeout=60)
        _private_stat(key_fd, 0o600)
        os.lseek(key_fd, 0, os.SEEK_SET)
        public = _run(["pkey", "-in", "/dev/fd/%d" % key_fd, "-pubout"], pass_fds=(key_fd,))
        return {"session": session, "public_key_pem": public.decode("ascii")}
    except Exception:
        if directory_fd is not None:
            try:
                os.unlink(KEY_FILE, dir_fd=directory_fd)
            except OSError:
                pass
        if root_fd is not None and created:
            try:
                os.rmdir(session, dir_fd=root_fd)
            except OSError:
                pass
        raise EnvelopeError() from None
    finally:
        for fd in (key_fd, directory_fd, root_fd):
            if fd is not None:
                os.close(fd)


def encrypt_credentials(public_key_pem, session, credentials: dict) -> dict:
    try:
        _session(session)
        encoded = _credentials(credentials)
        if not isinstance(public_key_pem, str) or not 1 <= len(public_key_pem) <= 4096:
            raise EnvelopeError()
        public = public_key_pem.encode("ascii")
        if not re.fullmatch(rb"-----BEGIN PUBLIC KEY-----\n[A-Za-z0-9+/=\n]+\n-----END PUBLIC KEY-----\n?", public):
            raise EnvelopeError()
        modulus = _run(["rsa", "-pubin", "-modulus", "-noout"], public)
        if not re.fullmatch(rb"Modulus=[89A-Fa-f][0-9A-Fa-f]{1023}\n", modulus):
            raise EnvelopeError()
        fields = {}
        for field, raw in encoded.items():
            chunks = [raw[i:i + CHUNK_BYTES] for i in range(0, len(raw), CHUNK_BYTES)]
            fields[field] = []
            for index, chunk in enumerate(chunks):
                read_fd, write_fd = os.pipe()
                try:
                    os.write(write_fd, public)
                    os.close(write_fd)
                    write_fd = None
                    ciphertext = _run(
                        ["pkeyutl", "-encrypt", "-pubin", "-inkey", "/dev/fd/%d" % read_fd,
                         *_options(session, field, index, len(chunks))], chunk, pass_fds=(read_fd,),
                    )
                    if len(ciphertext) != 512:
                        raise EnvelopeError()
                    fields[field].append(base64.b64encode(ciphertext).decode("ascii"))
                finally:
                    os.close(read_fd)
                    if write_fd is not None:
                        os.close(write_fd)
        return {"version": 1, "session": session, "fields": fields}
    except Exception:
        raise EnvelopeError() from None


def decrypt_credentials(session, envelope, root: Path = Path("/run")) -> dict:
    root_fd = directory_fd = key_fd = None
    try:
        _session(session)
        if not isinstance(envelope, dict) or set(envelope) != {"version", "session", "fields"}:
            raise EnvelopeError()
        if type(envelope["version"]) is not int or envelope["version"] != 1 or envelope["session"] != session:
            raise EnvelopeError()
        fields = envelope["fields"]
        if not isinstance(fields, dict) or set(fields) != set(FIELDS):
            raise EnvelopeError()
        # Validate bounds before serializing or invoking a subprocess.
        for chunks in fields.values():
            if not isinstance(chunks, list) or not 1 <= len(chunks) <= MAX_CHUNKS:
                raise EnvelopeError()
            if any(not isinstance(chunk, str) or len(chunk) != 684 for chunk in chunks):
                raise EnvelopeError()
        if len(json.dumps(envelope).encode("utf-8")) > MAX_ENVELOPE_BYTES:
            raise EnvelopeError()
        root_fd = _root_fd(root)
        directory_fd = _session_fd(root_fd, session)
        key_fd = os.open(KEY_FILE, _FILE_FLAGS, dir_fd=directory_fd)
        _private_stat(key_fd, 0o600)
        credentials = {}
        for field in FIELDS:
            plaintext = []
            chunks = fields[field]
            for index, chunk in enumerate(chunks):
                ciphertext = base64.b64decode(chunk, validate=True)
                if len(ciphertext) != 512 or base64.b64encode(ciphertext).decode("ascii") != chunk:
                    raise EnvelopeError()
                os.lseek(key_fd, 0, os.SEEK_SET)
                raw = _run(
                    ["pkeyutl", "-decrypt", "-inkey", "/dev/fd/%d" % key_fd,
                     *_options(session, field, index, len(chunks))], ciphertext, pass_fds=(key_fd,),
                )
                if not 1 <= len(raw) <= CHUNK_BYTES:
                    raise EnvelopeError()
                plaintext.append(raw)
            credentials[field] = b"".join(plaintext).decode("utf-8")
        _credentials(credentials)
        return credentials
    except Exception:
        raise EnvelopeError() from None
    finally:
        for fd in (key_fd, directory_fd, root_fd):
            if fd is not None:
                os.close(fd)


def destroy_session(session, root: Path = Path("/run")) -> None:
    root_fd = directory_fd = key_fd = None
    try:
        _session(session)
        root_fd = _root_fd(root)
        try:
            directory_fd = _session_fd(root_fd, session)
        except FileNotFoundError:
            return
        if set(os.listdir(directory_fd)) - {KEY_FILE}:
            raise EnvelopeError()
        try:
            key_fd = os.open(KEY_FILE, _FILE_FLAGS, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        else:
            _private_stat(key_fd, 0o600)
            os.unlink(KEY_FILE, dir_fd=directory_fd)
        os.rmdir(session, dir_fd=root_fd)
    except Exception:
        raise EnvelopeError() from None
    finally:
        for fd in (key_fd, directory_fd, root_fd):
            if fd is not None:
                os.close(fd)
