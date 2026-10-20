"""Capture-bound frontend removal; no service, queue, provider or order operation.

Only deliberate aggregate receipts leave this module. The installed whole app
and pipeline are archived privately; all backend and unrecognized regular files
are preserved. Current schema runs with short DB lock/read/process bounds.
"""
import ctypes
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import tarfile
import tempfile
import urllib.request


ROOT = Path('/opt/kalshi')
PROC = Path('/proc')
RELEASES = Path('/opt/tau-frontend-releases')
PYTHON = '/opt/kalshi/.venv313/bin/python'
ROOT_UID = 0
SERVICES = ('recursive-web', 'recursive-agents', 'recursive-engine', 'recursive-history', 'kalshi-live-engine')
UNIT_ROOTS = tuple(Path(p) for p in ('/etc/systemd/system', '/run/systemd/system', '/usr/lib/systemd/system', '/lib/systemd/system'))
CONFIG = (Path('/opt/kalshi/.env.aws'), Path('/opt/kalshi/.env.app'), Path('/opt/kalshi/.env'),
          Path('/etc/tau/provider-data/market-data.env'), Path('/etc/tau/provider-data/research-data.env'),
          Path('/etc/tau/alpaca-paper/paper.env'))
JS = ('app/static/app.js', 'app/static/app.meridian.js')
HOST = b'<section id="broker-connections" aria-label="Broker accounts"></section>'
MOUNT = (b"      const brokerHost = root.querySelector('#broker-connections');\n"
         b"      if (window.TauBrokerConnections && brokerHost) window.TauBrokerConnections.mount(brokerHost, {api, isCurrent: () => gen === S.gen});\n")
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
PROPERTIES = ('MainPID', 'ActiveState', 'FragmentPath', 'DropInPaths', 'NeedDaemonReload', 'Restart', 'RestartUSec',
              'TimeoutStartUSec', 'TimeoutStopUSec', 'MemoryHigh', 'MemoryMax', 'MemorySwapMax', 'Nice', 'KillMode',
              'KillSignal', 'WorkingDirectory', 'User', 'Group', 'EnvironmentFiles', 'Environment', 'ExecStart', 'Type')


class RemovalError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fail(code):
    raise RemovalError(code) from None


def digest(value):
    return hashlib.sha256(value).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def metadata(info):
    return {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}


def read_regular(path, limit=MAX_FILE, owners=None):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        first = os.fstat(descriptor)
        if (not stat.S_ISREG(first.st_mode) or first.st_nlink != 1 or first.st_uid not in (owners or {ROOT_UID})
                or first.st_mode & 0o022 or first.st_size > limit):
            fail('unsafe_regular_file')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            raw = stream.read(limit + 1)
            last = os.fstat(stream.fileno())
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode, s.st_uid, s.st_gid)
        if len(raw) != first.st_size or signature(first) != signature(last):
            fail('file_changed_while_reading')
        return raw, metadata(first)
    except RemovalError:
        raise
    except Exception:
        fail('regular_file_read_failed')
    finally:
        if descriptor is not None:
            os.close(descriptor)


def safe_directory(path, private=False, owners=None):
    try:
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (owners or {ROOT_UID}) or info.st_mode & 0o022
                or (private and stat.S_IMODE(info.st_mode) != 0o700)):
            fail('unsafe_directory')
        return info
    except RemovalError:
        raise
    except Exception:
        fail('directory_read_failed')


def layout():
    try:
        parent = safe_directory(ROOT.parent)
        owner = ROOT.lstat().st_uid
        source_root = safe_directory(ROOT, owners={ROOT_UID, owner})
        return {'root': metadata(source_root), 'parent': metadata(parent)}
    except RemovalError:
        raise
    except Exception:
        fail('deployment_root_read_failed')


def scan(root, owners=None):
    owners = owners or {ROOT_UID, ROOT.lstat().st_uid}
    entries = {}
    total = 0

    def visit(path):
        nonlocal total
        info = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISLNK(info.st_mode):
            fail('source_symlink_not_supported')
        if stat.S_ISDIR(info.st_mode):
            safe_directory(path, owners=owners)
            if path.name == '__pycache__':
                return
            entries[relative] = {'kind': 'directory', **metadata(info)}
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            raw, meta = read_regular(path, owners=owners)
            total += len(raw)
            entries[relative] = {'kind': 'file', 'bytes': len(raw), 'sha256': digest(raw), **meta}
        else:
            fail('source_entry_not_supported')
        if total > MAX_TOTAL or len(entries) > 8192:
            fail('source_package_too_large')

    try:
        for package in ('app', 'data_pipeline'):
            visit(root / package)
    except RemovalError:
        raise
    except Exception:
        fail('source_inventory_failed')
    for name in (*JS, 'app/schema.py', 'app/server.py', 'data_pipeline/common.py'):
        if entries.get(name, {}).get('kind') != 'file':
            fail('required_source_missing')
    return entries


def patched(raw):
    if raw.count(HOST) != 1 or raw.count(MOUNT) != 1:
        fail('broker_mount_not_exactly_once')
    after = raw.replace(HOST, b'', 1).replace(MOUNT, b'', 1)
    if HOST in after or b'TauBrokerConnections.mount(' in after or b"querySelector('#broker-connections')" in after:
        fail('broker_mount_not_fully_removed')
    return after


def unit_state():
    units, unit_files, process_hashes = {}, {}, {}
    web_env = None
    try:
        for service in SERVICES:
            response = subprocess.run(['systemctl', 'show', service, '--property=' + ','.join(PROPERTIES)],
                                      capture_output=True, check=True, timeout=15)
            values = dict(line.split('=', 1) for line in response.stdout.decode().splitlines() if '=' in line)
            values.setdefault('EnvironmentFiles', '')
            values['EnvironmentSHA256'] = digest(values.pop('Environment', '').encode())
            # Ignore only execution timestamps/status; MainPID is compared exactly.
            command = values.pop('ExecStart')
            stable = re.fullmatch(r'(\{ path=.*? ; argv\[\]=.*? ; ignore_errors=(?:yes|no))'
                                  r' ; start_time=\[[^\]]*\] ; stop_time=\[[^\]]*\] ; pid=\d+ ; code=[^;{}]+ ; status=[^;{}]+ \}', command)
            if not stable:
                fail('unrecognized_loaded_exec')
            values['ExecStartSHA256'] = digest(stable.group(1).encode())
            if not re.fullmatch(r'[0-9]{1,10}', values['MainPID']):
                fail('invalid_service_pid')
            pid = int(values['MainPID'])
            if service in ('recursive-web', 'recursive-agents') and (values['ActiveState'] != 'active' or pid == 0):
                fail('required_service_not_active')
            units[service] = values
            fragment = Path(values['FragmentPath'])
            if fragment not in {root / (service + '.service') for root in UNIT_ROOTS}:
                fail('unrecognized_unit_fragment')
            paths = {fragment, *(Path(p) for p in shlex.split(values['DropInPaths']))}
            for root in UNIT_ROOTS:
                candidate = root / (service + '.service')
                if candidate.exists() or candidate.is_symlink():
                    paths.add(candidate)
                names = [service + '.service.d', 'service.d'] + [service[:i + 1] + '.service.d'
                         for i, c in enumerate(service) if c == '-']
                for name in names:
                    directory = root / name
                    if directory.exists() or directory.is_symlink():
                        safe_directory(directory)
                        paths.update(directory.glob('*.conf'))
            for path in paths:
                raw, meta = read_regular(path, 262144)
                unit_files[str(path)] = {'sha256': digest(raw), **meta}
            if pid:
                proc = PROC / str(pid)
                args = [part.decode() for part in (proc / 'cmdline').read_bytes().split(b'\0') if part]
                raw_env = (proc / 'environ').read_bytes()
                env = dict(part.decode().split('=', 1) for part in raw_env.split(b'\0') if b'=' in part)
                if service in ('recursive-web', 'recursive-agents'):
                    wanted = ['-m', 'app.server'] if service == 'recursive-web' else ['-m', 'app.worker', 'agents']
                    if ((proc / 'cwd').resolve() != ROOT or not args or args[0] != PYTHON
                            or not any(args[i:i + len(wanted)] == wanted for i in range(len(args)))
                            or not env.get('APP_SECRET_KEY')):
                        fail('unexpected_application_process')
                # stat start ticks also fence PID reuse; raw environment stays private.
                start_ticks = (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]
                process_hashes[service] = {'cmdline_sha256': fingerprint(args), 'environment_sha256': digest(raw_env),
                                           'start_ticks': start_ticks, 'cwd_sha256': digest(str((proc / 'cwd').resolve()).encode())}
                if service == 'recursive-web':
                    web_env = env
        config = {}
        for path in CONFIG:
            if path.exists() or path.is_symlink():
                base = path.parent == ROOT
                owners = {ROOT_UID, ROOT.lstat().st_uid} if base else {ROOT_UID}
                raw, meta = read_regular(path, 1024 * 1024, owners=owners)
                if meta['mode'] != 0o600:
                    fail('private_environment_permissions_unsafe')
                config[str(path)] = {'sha256': digest(raw), **meta}
            elif path.name in ('.env.aws', '.env.app'):
                fail('base_environment_missing')
        if web_env is None:
            fail('web_environment_unavailable')
        return {'units': units, 'unit_files': unit_files, 'processes': process_hashes, 'config': config}, web_env
    except RemovalError:
        raise
    except Exception:
        fail('control_inventory_failed')


def snapshot():
    if os.geteuid() != ROOT_UID:
        fail('requires_root')
    root_layout = layout()
    owners = {ROOT_UID, root_layout['root']['uid']}
    source = scan(ROOT, owners=owners)
    controls, env = unit_state()
    candidates = {}
    for name in JS:
        raw, _ = read_regular(ROOT / name, owners=owners)
        if digest(raw) != source[name]['sha256']:
            fail('source_changed_during_inventory')
        candidates[name] = digest(patched(raw))
    return {'source': source, 'controls': controls, 'candidates': candidates, 'layout': root_layout}, env


def exchange(left, right):
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        operation = libc.renameat2
        operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        operation.restype = ctypes.c_int
        if operation(-100, os.fsencode(left), -100, os.fsencode(right), 2) != 0:
            fail('atomic_exchange_unavailable')
    except RemovalError:
        raise
    except Exception:
        fail('atomic_exchange_unavailable')


def exchange_available():
    try:
        return callable(ctypes.CDLL(None).renameat2)
    except Exception:
        return False


def inventory():
    state, _ = snapshot()
    return {'status': 'ready' if exchange_available() else 'atomic_exchange_unavailable', 'read_only': True,
            'fingerprint': fingerprint(state), 'source_files': sum(v['kind'] == 'file' for v in state['source'].values()),
            'source_sha256': {name: state['source'][name]['sha256'] for name in JS},
            'candidate_sha256': state['candidates'], 'schema_sha256': state['source']['app/schema.py']['sha256'],
            'controls_sha256': fingerprint(state['controls']),
            'service_pids': {s: int(v['MainPID']) for s, v in state['controls']['units'].items()},
            'provider_calls': 0, 'service_operations': 0, 'job_mutations': 0}


def clone_archive(state, directory):
    archive_path = directory / 'installed-whole-package.tar'
    descriptor = os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream, tarfile.open(fileobj=stream, mode='w') as archive:
        for name, row in sorted(state['source'].items()):
            item = tarfile.TarInfo(name)
            item.mode, item.uid, item.gid = row['mode'], row['uid'], row['gid']
            if row['kind'] == 'directory':
                item.type = tarfile.DIRTYPE
                archive.addfile(item)
            else:
                raw, meta = read_regular(ROOT / name, owners={ROOT_UID, state['layout']['root']['uid']})
                if digest(raw) != row['sha256'] or meta != {k: row[k] for k in ('mode', 'uid', 'gid')}:
                    fail('source_changed_while_archiving')
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
    candidate = directory / 'candidate'
    candidate.mkdir(mode=0o700)
    with tarfile.open(archive_path, mode='r:') as archive:
        archive.extractall(candidate, filter='data')
    # data_filter deliberately removes ownership/dir modes; restore exactly the
    # trusted captured metadata after extracting our own regular-only archive.
    for name, row in sorted(state['source'].items(), key=lambda item: item[0].count('/'), reverse=True):
        path = candidate / name
        os.chown(path, row['uid'], row['gid'], follow_symlinks=False)
        os.chmod(path, row['mode'], follow_symlinks=False)
    if scan(candidate, owners={ROOT_UID, state['layout']['root']['uid']}) != state['source']:
        fail('private_archive_verification_failed')
    return candidate


def run_schema(env):
    code = ('import pymysql; original=pymysql.connect\n'
            'def bounded(*a,**kw):\n'
            ' kw["connect_timeout"]=5;kw["read_timeout"]=10;kw["write_timeout"]=10\n'
            ' if kw.get("init_command"):raise RuntimeError("UnexpectedSchemaConnectionInitializer")\n'
            ' kw["init_command"]="SET SESSION lock_wait_timeout=3, innodb_lock_wait_timeout=3"\n'
            ' return original(*a,**kw)\n'
            'pymysql.connect=bounded\nfrom app import schema\nschema.main()\n')
    private_env = dict(env)
    private_env['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        response = subprocess.run([PYTHON, '-B', '-c', code], cwd=ROOT, env=private_env,
                                  capture_output=True, timeout=60)
        if response.returncode:
            fail('full_schema_failed')
    except RemovalError:
        raise
    except Exception:
        fail('full_schema_timeout_or_transport_failed')


def origin_check(candidates):
    try:
        for path in ('/', '/healthz', '/api/version', '/static/app.js', '/static/app.meridian.js'):
            with urllib.request.urlopen('http://127.0.0.1:8090' + path, timeout=10) as response:
                if response.status != 200:
                    fail('origin_http_failed')
                body = response.read(MAX_FILE + 1)
                if len(body) > MAX_FILE:
                    fail('origin_body_too_large')
                if path.startswith('/static/') and digest(body) != candidates['app' + path]:
                    fail('origin_asset_hash_mismatch')
                if path == '/api/version' and json.loads(body).get('v') != candidates['app/static/app.js'][:10]:
                    fail('origin_version_mismatch')
                if path == '/healthz' and json.loads(body).get('ok') is not True:
                    fail('origin_unhealthy')
    except RemovalError:
        raise
    except Exception:
        fail('origin_verification_failed')


def apply(expected_fingerprint, expected_sources, expected_candidates):
    if (not isinstance(expected_fingerprint, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_fingerprint)
            or not isinstance(expected_sources, dict) or set(expected_sources) != set(JS)
            or not isinstance(expected_candidates, dict) or set(expected_candidates) != set(JS)
            or any(not isinstance(v, str) or not re.fullmatch(r'[a-f0-9]{64}', v)
                   for v in (*expected_sources.values(), *expected_candidates.values()))):
        fail('invalid_apply_pin')
    state, env = snapshot()
    if (fingerprint(state) != expected_fingerprint or state['candidates'] != expected_candidates
            or {name: state['source'][name]['sha256'] for name in JS} != expected_sources):
        fail('inventory_pin_changed')
    safe_directory(RELEASES.parent)
    try:
        RELEASES.mkdir(mode=0o700)
    except FileExistsError:
        pass
    safe_directory(RELEASES, private=True)
    lock = os.open(RELEASES / '.operation.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    directory, exchanged = None, False
    result = {'provider_calls': 0, 'service_operations': 0, 'job_mutations': 0, 'rollback_performed': False,
              'schema_migrated': False, 'source_exchanged': False, 'private_backup_retained': False}
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            fail('unsafe_operation_lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('another_frontend_operation_active')
        directory = Path(tempfile.mkdtemp(prefix='broker-removal-', dir=RELEASES))
        os.chmod(directory, 0o700)
        result.update(private_backup_directory=str(directory), private_backup_retained=True)
        # Prove this mount/kernel supports EXCHANGE before touching installed source.
        left, right = directory / 'probe-a', directory / 'probe-b'
        left.mkdir(); right.mkdir()
        (left / 'a').write_bytes(b'a'); (right / 'b').write_bytes(b'b')
        exchange(left, right)
        if not (left / 'b').is_file() or not (right / 'a').is_file():
            fail('atomic_exchange_probe_failed')
        candidate = clone_archive(state, directory)
        planned = {name: dict(row) for name, row in state['source'].items()}
        for name in JS:
            raw, _ = read_regular(candidate / name, owners={ROOT_UID, state['layout']['root']['uid']})
            after = patched(raw)
            if digest(after) != expected_candidates[name]:
                fail('candidate_hash_mismatch')
            (candidate / name).write_bytes(after)
            planned[name].update(bytes=len(after), sha256=digest(after))
        if scan(candidate) != planned:
            fail('candidate_package_not_exact')
        current, current_env = snapshot()
        if current != state:
            fail('source_or_controls_changed_before_schema')
        run_schema(current_env)
        result['schema_migrated'] = True
        current, _ = snapshot()
        if current != state or scan(candidate) != planned:
            fail('source_or_controls_changed_before_exchange')
        if (ROOT / 'app').stat().st_dev != (candidate / 'app').stat().st_dev:
            fail('atomic_exchange_requires_same_filesystem')
        exchange(ROOT / 'app', candidate / 'app')
        exchanged = True
        result['source_exchanged'] = True
        # Once exchanged, preserve installed state on any drift or failure.
        # There are no blind rollback/restart paths in this operation.
        after_source = scan(ROOT)
        after_controls, _ = unit_state()
        old_app = {name: row for name, row in scan(candidate).items() if name.startswith('app/') or name == 'app'}
        baseline_app = {name: row for name, row in state['source'].items() if name.startswith('app/') or name == 'app'}
        if (after_source != planned or old_app != baseline_app or after_controls != state['controls']
                or layout() != state['layout']):
            fail('source_or_controls_changed_after_exchange')
        origin_check(expected_candidates)
        if scan(ROOT) != planned or unit_state()[0] != state['controls'] or layout() != state['layout']:
            fail('source_or_controls_changed_during_verification')
        result.update(status='deployed', backend_bytes_unchanged=True, non_js_assets_unchanged=True,
                      service_pids_unchanged=True, source_files=sum(v['kind'] == 'file' for v in planned.values()),
                      candidate_sha256=expected_candidates, origin_verified=True)
        return result
    except Exception as exc:
        result.update(status='installed_state_requires_inspection' if exchanged else 'failed_before_exchange',
                      error_code=exc.code if isinstance(exc, RemovalError) else 'operation_failed')
        return result
    finally:
        os.close(lock)
