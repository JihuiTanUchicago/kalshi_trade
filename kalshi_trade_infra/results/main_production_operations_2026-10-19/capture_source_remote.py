"""Read reviewed source paths only; export ciphertext, never raw source or env."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import shlex
import zlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def capture(public_key, expected_hashes, object_key, root=Path('/opt/kalshi')):
    files = {}
    for name, digest in expected_hashes.items():
        if not (name.startswith('app/') or name.startswith('data_pipeline/')) or '..' in Path(name).parts:
            raise RuntimeError('UnreviewedCapturePath')
        path = root / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4 * 1024 * 1024:
            raise RuntimeError('UnsafeCaptureSource')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError('SourceChangedSincePreflight')
        files[name] = base64.b64encode(raw).decode()
    units = {}
    unit_files = {}
    unit_hashes = {}
    properties = ('MainPID,ActiveState,FragmentPath,DropInPaths,NeedDaemonReload,Restart,RestartUSec,'
                  'TimeoutStartUSec,TimeoutStopUSec,MemoryHigh,MemoryMax,MemorySwapMax,Nice,KillMode,KillSignal,'
                  'WorkingDirectory,User,Group,EnvironmentFiles,Environment,ExecStart')
    for service in ('recursive-web', 'recursive-agents', 'recursive-engine', 'recursive-history', 'kalshi-live-engine'):
        raw = subprocess.check_output(['systemctl', 'show', service, '--property=' + properties], timeout=10)
        values = dict(line.split('=', 1) for line in raw.decode().splitlines() if '=' in line)
        environment = values.pop('Environment', '')
        values['EnvironmentSHA256'] = hashlib.sha256(environment.encode()).hexdigest()
        units[service] = values
        paths = [Path(values['FragmentPath'])] if values.get('FragmentPath') else []
        for parent in ('/etc/systemd/system', '/run/systemd/system', '/usr/lib/systemd/system', '/lib/systemd/system'):
            directory = Path(parent) / (service + '.service.d')
            if directory.exists():
                paths.extend(directory.glob('*.conf'))
        for path in paths:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise RuntimeError('UnsafeUnitCapture')
            content = path.read_bytes()
            unit_hashes[str(path)] = hashlib.sha256(content).hexdigest()
            safe_lines = []
            for line in content.decode().splitlines():
                if line.strip().startswith('Environment='):
                    assignments = shlex.split(line.strip().split('=', 1)[1])
                    keys = [word.partition('=')[0] for word in assignments]
                    safe_lines.append('# Environment keys=' + ','.join(keys) + '; original line sha256=' + hashlib.sha256(line.encode()).hexdigest())
                elif line.strip().startswith(('SetCredential=', 'LoadCredential=')):
                    raise RuntimeError('CredentialUnitRequiresSanitizedReview')
                else:
                    safe_lines.append(line)
            unit_files[str(path)] = base64.b64encode(('\n'.join(safe_lines) + '\n').encode()).decode()
    payload = zlib.compress(json.dumps({'files': files, 'unit_files': unit_files, 'unit_hashes': unit_hashes, 'units': units}).encode())
    symmetric = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(symmetric).encrypt(nonce, payload, object_key.encode())
    public = serialization.load_pem_public_key(public_key.encode())
    wrapped = public.encrypt(symmetric, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                             algorithm=hashes.SHA256(), label=b'tau-source-review-v1'))
    envelope = json.dumps({'key': base64.b64encode(wrapped).decode(), 'nonce': base64.b64encode(nonce).decode(),
                           'ciphertext': base64.b64encode(ciphertext).decode(), 'object_key': object_key}).encode()
    directory = Path(tempfile.mkdtemp(prefix='tau-encrypted-source-', dir='/run'))
    os.chmod(directory, 0o700)
    target = directory / 'source.enc.json'
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(envelope)
    return {'status': 'captured_encrypted', 'object_key': object_key,
            'cipher_path': str(target), 'cipher_bytes': len(envelope),
            'cipher_sha256': hashlib.sha256(envelope).hexdigest(), 'source_files': len(files),
            'unit_files': len(unit_files), 'base_environment_files_read': False,
            'application_or_service_changes': False, 'provider_calls': 0, 'order_calls': 0}
