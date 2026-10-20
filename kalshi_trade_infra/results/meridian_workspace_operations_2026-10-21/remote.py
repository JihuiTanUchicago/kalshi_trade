"""Capture-bound Meridian asset publication; no service, queue, provider or order operation.

Only deliberate aggregate receipts leave this module. The installed whole app
and pipeline are archived privately; all backend and unrecognized regular files
are preserved. Current schema runs with short DB lock/read/process bounds.
"""
import base64
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
ASSETS = ('app/static/app.meridian.js', 'app/static/app.meridian.css')
PRESERVED = ('app/static/app.js', 'app/static/app.css', 'app/static/boot.js', 'app/static/index.html')
BUCKET = 'kalshi-trade-artifacts-568386354218-us-east-1'
REGION = 'us-east-1'
MAX_TRANSFER = 2 * 48 * 1024 * 1024
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
    for name in (*ASSETS, *PRESERVED, 'app/schema.py', 'app/server.py', 'data_pipeline/common.py'):
        if entries.get(name, {}).get('kind') != 'file':
            fail('required_source_missing')
    return entries


def validate_candidates(raw, expected_candidates):
    try:
        if len(raw) > MAX_TRANSFER:
            fail('candidate_transfer_too_large')
        payload = json.loads(raw)
        if (not isinstance(payload, dict) or set(payload) != {'assets'}
                or not isinstance(payload['assets'], dict) or set(payload['assets']) != set(ASSETS)):
            fail('candidate_paths_not_exact')
        assets = {}
        for name in ASSETS:
            encoded = payload['assets'][name]
            if not isinstance(encoded, str):
                fail('candidate_encoding_invalid')
            data = base64.b64decode(encoded, validate=True)
            if not data or len(data) > MAX_FILE or b'\0' in data:
                fail('candidate_content_invalid')
            data.decode('utf-8')
            if digest(data) != expected_candidates[name]:
                fail('candidate_hash_mismatch')
            assets[name] = data
        return assets
    except RemovalError:
        raise
    except Exception:
        fail('candidate_content_invalid')


def load_candidates(artifact, expected_candidates):
    if (not isinstance(artifact, dict) or set(artifact) != {'bucket', 'key', 'sha256'}
            or artifact['bucket'] != BUCKET
            or not isinstance(artifact['key'], str)
            or not re.fullmatch(r'frontend/meridian-[0-9a-f]{40}-[0-9a-f]{32}\.json', artifact['key'])
            or not isinstance(artifact['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', artifact['sha256'])):
        fail('invalid_candidate_artifact')
    try:
        response = subprocess.run(['aws', 's3', 'cp', 's3://' + BUCKET + '/' + artifact['key'], '-',
                                   '--region', REGION, '--no-progress', '--only-show-errors'],
                                  capture_output=True, timeout=45)
        if response.returncode != 0:
            fail('candidate_download_failed')
        raw = response.stdout
        if len(raw) > MAX_TRANSFER or digest(raw) != artifact['sha256']:
            fail('candidate_artifact_hash_mismatch')
        return validate_candidates(raw, expected_candidates)
    except RemovalError:
        raise
    except Exception:
        fail('candidate_download_failed')


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
                # Preserve the pinned legacy base-file permissions. The root
                # overlays created by our operations retain their exact 0600
                # contract; neither class is written by this frontend rollout.
                if not base and meta['mode'] != 0o600:
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
    # Retain the original selected-file reread fence; bind the unchanged defaults too.
    for name in (*ASSETS, *PRESERVED):
        raw, meta = read_regular(ROOT / name, owners=owners)
        if (digest(raw) != source[name]['sha256']
                or meta != {k: source[name][k] for k in ('mode', 'uid', 'gid')}):
            fail('source_changed_during_inventory')
    return {'source': source, 'controls': controls, 'layout': root_layout}, env


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
            'source_sha256': {name: state['source'][name]['sha256'] for name in ASSETS},
            'preserved_sha256': {name: state['source'][name]['sha256'] for name in PRESERVED}, 'schema_sha256': state['source']['app/schema.py']['sha256'],
            'controls_sha256': fingerprint(state['controls']),
            'configuration_file_metadata': {
                path: {'uid': row['uid'], 'gid': row['gid'], 'mode': format(row['mode'], '04o')}
                for path, row in state['controls']['config'].items() if path in {str(p) for p in CONFIG}},
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
    classes = {'Error', 'Warning', 'InterfaceError', 'DatabaseError', 'DataError', 'OperationalError',
               'IntegrityError', 'InternalError', 'ProgrammingError', 'NotSupportedError',
               'RuntimeError', 'ValueError', 'TypeError', 'AttributeError', 'ImportError', 'ModuleNotFoundError',
               'OSError', 'PermissionError', 'FileNotFoundError', 'TimeoutError', 'ConnectionError',
               'AssertionError', 'KeyError', 'IndexError', 'MemoryError', 'SyntaxError', 'NameError',
               'UnicodeError', 'UnicodeDecodeError', 'UnicodeEncodeError', 'EOFError', 'SystemExit',
               'KeyboardInterrupt', 'OtherError'}
    # Keep a private copy of the receipt pipe, then discard stdout/stderr at FD
    # level. Even C-level writes/logging can never enter the deliberate report.
    code = '''import os,json
receipt_fd=os.dup(1)
quiet=os.open(os.devnull,os.O_WRONLY)
os.dup2(quiet,1);os.dup2(quiet,2);os.close(quiet)
report={"ok":False,"stage":"schema_bootstrap","exception_class":None,"mysql_code":None}
pymysql=None
try:
 import pymysql
 original=pymysql.connect
 def bounded(*a,**kw):
  kw["connect_timeout"]=5;kw["read_timeout"]=60;kw["write_timeout"]=60
  if kw.get("init_command"):raise RuntimeError("UnexpectedSchemaConnectionInitializer")
  kw["init_command"]="SET SESSION lock_wait_timeout=3, innodb_lock_wait_timeout=3"
  return original(*a,**kw)
 pymysql.connect=bounded
 report["stage"]="schema_import"
 from app import schema
 report["stage"]="schema_main"
 schema.main()
 report["ok"]=True
except BaseException as exc:
 name=type(exc).__name__
 report["exception_class"]=name if name in ALLOWED_CLASSES else "OtherError"
 current=exc
 for unused in range(4):
  if current is None:break
  if pymysql is not None and isinstance(current,pymysql.err.Error):
   args=current.args
   if args and type(args[0]) is int and 0<=args[0]<=65535:
    report["mysql_code"]=args[0];break
  current=current.__cause__ or current.__context__
os.write(receipt_fd,(json.dumps(report,separators=(",",":"))+"\\n").encode())
os.close(receipt_fd)
raise SystemExit(0 if report["ok"] else 1)
'''.replace('ALLOWED_CLASSES', repr(sorted(classes)))
    private_env = dict(env)
    private_env['PYTHONDONTWRITEBYTECODE'] = '1'

    def failure(code, stage, exception_class, mysql_code=None):
        error = RemovalError(code)
        error.details = {'stage': stage, 'exception_class': exception_class, 'mysql_code': mysql_code}
        raise error from None

    try:
        response = subprocess.run([PYTHON, '-B', '-c', code], cwd=ROOT, env=private_env,
                                  capture_output=True, timeout=120)
        try:
            if len(response.stdout) > 4096:
                raise ValueError
            report = json.loads(response.stdout)
            if (not isinstance(report, dict) or set(report) != {'ok', 'stage', 'exception_class', 'mysql_code'}
                    or type(report['ok']) is not bool
                    or report['stage'] not in {'schema_bootstrap', 'schema_import', 'schema_main'}
                    or (report['exception_class'] is not None and report['exception_class'] not in classes)
                    or (report['mysql_code'] is not None and
                        (type(report['mysql_code']) is not int or not 0 <= report['mysql_code'] <= 65535))
                    or (report['ok'] and (report['stage'] != 'schema_main' or report['exception_class'] is not None
                                         or report['mysql_code'] is not None))
                    or (not report['ok'] and report['exception_class'] is None)):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            failure('full_schema_failed', 'child_report', 'ChildReportUnavailable')
        if response.returncode != 0 or not report['ok']:
            failure('full_schema_failed', report['stage'], report['exception_class'] or 'ChildProcessFailed', report['mysql_code'])
    except RemovalError:
        raise
    except subprocess.TimeoutExpired:
        failure('full_schema_timeout_or_transport_failed', 'child_process', 'TimeoutExpired')
    except Exception:
        failure('full_schema_timeout_or_transport_failed', 'child_process', 'ChildTransportError')


def html_versions_match(raw, candidates, preserved):
    text = raw.decode('utf-8')
    return all(fragment in text for fragment in (
        '/static/app.css?v=' + preserved['app/static/app.css'][:10],
        'data-tau-js="/static/app.js?v=' + preserved['app/static/app.js'][:10] + '"',
        'data-tau-ver="' + preserved['app/static/app.js'][:10] + '"',
        'data-mer-css="/static/app.meridian.css?v=' + candidates['app/static/app.meridian.css'][:10] + '"',
        'data-mer-js="/static/app.meridian.js?v=' + candidates['app/static/app.meridian.js'][:10] + '"',
        'data-mer-ver="' + candidates['app/static/app.meridian.js'][:10] + '"',
        '/static/boot.js?v=' + preserved['app/static/boot.js'][:10],
    ))


def origin_check(candidates, preserved):
    try:
        assets = {**candidates, **{p: h for p, h in preserved.items() if not p.endswith('index.html')}}
        paths = ('/', '/funds', '/research', '/healthz', '/api/version',
                 *('/' + name.removeprefix('app/') for name in assets))
        for path in paths:
            with urllib.request.urlopen('http://127.0.0.1:8090' + path, timeout=10) as response:
                if response.status != 200:
                    fail('origin_http_failed')
                body = response.read(MAX_FILE + 1)
                if len(body) > MAX_FILE:
                    fail('origin_body_too_large')
                if path.startswith('/static/') and digest(body) != assets['app' + path]:
                    fail('origin_asset_hash_mismatch')
                if path == '/api/version' and json.loads(body).get('v') != preserved['app/static/app.js'][:10]:
                    fail('origin_version_mismatch')
                if path in ('/', '/funds', '/research') and not html_versions_match(body, candidates, preserved):
                    fail('origin_html_version_mismatch')
                if path == '/healthz' and json.loads(body).get('ok') is not True:
                    fail('origin_unhealthy')
    except RemovalError:
        raise
    except Exception:
        fail('origin_verification_failed')


def apply(expected_fingerprint, expected_sources, expected_candidates, artifact, expected_preserved):
    if (not isinstance(expected_fingerprint, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_fingerprint)
            or not isinstance(expected_sources, dict) or set(expected_sources) != set(ASSETS)
            or not isinstance(expected_candidates, dict) or set(expected_candidates) != set(ASSETS)
            or not isinstance(expected_preserved, dict) or set(expected_preserved) != set(PRESERVED)
            or any(not isinstance(v, str) or not re.fullmatch(r'[a-f0-9]{64}', v)
                   for v in (*expected_sources.values(), *expected_candidates.values(), *expected_preserved.values()))):
        fail('invalid_apply_pin')
    state, env = snapshot()
    if (fingerprint(state) != expected_fingerprint
            or {name: state['source'][name]['sha256'] for name in ASSETS} != expected_sources
            or {name: state['source'][name]['sha256'] for name in PRESERVED} != expected_preserved):
        fail('inventory_pin_changed')
    replacements = load_candidates(artifact, expected_candidates)
    if any(expected_candidates[name] == expected_sources[name] for name in ASSETS):
        fail('candidate_asset_not_changed')
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
        directory = Path(tempfile.mkdtemp(prefix='meridian-workspace-', dir=RELEASES))
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
        for name in ASSETS:
            after = replacements[name]
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
        origin_check(expected_candidates, expected_preserved)
        if scan(ROOT) != planned or unit_state()[0] != state['controls'] or layout() != state['layout']:
            fail('source_or_controls_changed_during_verification')
        result.update(status='deployed', backend_bytes_unchanged=True, non_target_assets_unchanged=True, default_assets_unchanged=True,
                      service_pids_unchanged=True, source_files=sum(v['kind'] == 'file' for v in planned.values()),
                      candidate_sha256=expected_candidates, preserved_sha256=expected_preserved, origin_verified=True)
        return result
    except Exception as exc:
        result.update(status='installed_state_requires_inspection' if exchanged else 'failed_before_exchange',
                      error_code=exc.code if isinstance(exc, RemovalError) else 'operation_failed')
        if isinstance(exc, RemovalError) and isinstance(getattr(exc, 'details', None), dict):
            result['schema_details'] = exc.details
        return result
    finally:
        os.close(lock)
