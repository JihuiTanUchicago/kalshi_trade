"""Offline temp-directory and mocked-control tests. No DB/network/systemd use."""
import base64
import copy
import contextlib
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location('meridian_publication_remote', Path(__file__).with_name('remote.py'))
remote = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(remote)


class RemovalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='tau-removal-offline-')
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name).resolve()
        self.root = self.parent / 'installed'
        self.root.mkdir(mode=0o755)
        self.releases = self.parent / 'private-releases'
        self.old_assets = {
            'app/static/app.meridian.js': b'// synthetic installed Meridian JS\nconst previous = true;\n',
            'app/static/app.meridian.css': b'/* synthetic installed Meridian CSS */\n.previous { color: red; }\n',
        }
        self.candidate_assets = {
            'app/static/app.meridian.js': b'// synthetic reviewed Meridian JS\nconst replacement = true;\n',
            'app/static/app.meridian.css': b'/* synthetic reviewed Meridian CSS */\n.replacement { color: green; }\n',
        }
        for name, raw in self.old_assets.items():
            self.put(name, raw)
        for name in ('app/schema.py', 'app/server.py', *remote.PRESERVED,
                     'data_pipeline/common.py', 'data_pipeline/utility.py', 'data_pipeline/dashboard_server.py.bak',
                     'app/static/._asset', 'app/static/.DS_Store', 'app/__pycache__/ignored.pyc'):
            self.put(name, ('synthetic unchanged ' + name).encode())
        self.payload = json.dumps({'assets': {p: base64.b64encode(raw).decode()
                                            for p, raw in self.candidate_assets.items()}}).encode()
        self.artifact = {'bucket': remote.BUCKET, 'key': 'bundle/meridian-' + 'a' * 40 + '-' + 'b' * 32 + '.json',
                         'sha256': remote.digest(self.payload)}
        os.chmod(self.root / 'data_pipeline/utility.py', 0o750)
        self.env = {'APP_SECRET_KEY': 'private-never-print', 'MYSQL_PASSWORD': 'private-db-value',
                    'MYSQL_HOST': 'synthetic-db', 'MYSQL_USER': 'synthetic-user'}
        self.controls = {'units': {service: {'MainPID': str(i + 1) if i < 4 else '0',
                                                   'ActiveState': 'active' if i < 4 else 'inactive'}
                                   for i, service in enumerate(remote.SERVICES)},
                         'unit_files': {'safe-unit': {'sha256': 'a' * 64}},
                         'processes': {}, 'config': {'safe-config': {'sha256': 'b' * 64}}}
        self.exchanges = []
        self.exchange_callback = None
        self.patches = [patch.object(remote, 'ROOT', self.root), patch.object(remote, 'RELEASES', self.releases),
                        patch.object(remote, 'ROOT_UID', os.geteuid()),
                        patch.object(remote, 'unit_state', side_effect=lambda: (copy.deepcopy(self.controls), dict(self.env))),
                        patch.object(remote, 'exchange_available', return_value=True),
                        patch.object(remote, 'exchange', side_effect=self.fake_exchange),
                        patch.object(remote, 'load_candidates', return_value=self.candidate_assets),
                        patch.object(remote, 'run_schema'), patch.object(remote, 'origin_check')]
        self.started = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.chmod(path, 0o644)

    def fake_exchange(self, left, right):
        # Tests emulate exchange only in disposable paths; production uses one syscall.
        self.exchanges.append((left, right))
        temporary = left.parent / '.synthetic-swap'
        os.rename(left, temporary)
        os.rename(right, left)
        os.rename(temporary, right)
        if self.exchange_callback and left == self.root / 'app':
            self.exchange_callback()

    def pins(self):
        receipt = remote.inventory()
        return (receipt['fingerprint'], receipt['source_sha256'],
                {p: remote.digest(raw) for p, raw in self.candidate_assets.items()}, self.artifact, receipt['preserved_sha256'])

    def execute(self):
        return remote.apply(*self.pins())

    def assert_code(self, code, fn):
        with self.assertRaisesRegex(remote.RemovalError, '^' + code + '$'):
            fn()

    def test_inventory_is_read_only_and_receipt_omits_private_data(self):
        before = remote.scan(self.root)
        receipt = remote.inventory()
        self.assertEqual(receipt['status'], 'ready')
        self.assertEqual(set(receipt['source_sha256']), set(remote.ASSETS))
        self.assertEqual(set(receipt['preserved_sha256']), set(remote.PRESERVED))
        self.assertEqual(receipt['provider_calls'], 0)
        self.assertNotIn('private-never-print', json.dumps(receipt))
        self.assertNotIn('private-db-value', json.dumps(receipt))
        self.assertEqual(remote.scan(self.root), before)
        self.assertFalse(self.releases.exists())
        self.assertEqual(self.exchanges, [])
        remote.run_schema.assert_not_called()
        remote.origin_check.assert_not_called()

    def test_happy_whole_package_exchange_changes_only_meridian_js_and_css(self):
        baseline = remote.scan(self.root)
        data_inode = (self.root / 'data_pipeline').stat().st_ino
        pins = self.pins()
        receipt = remote.apply(*pins)
        self.assertEqual(receipt['status'], 'deployed')
        after = remote.scan(self.root)
        changed = [name for name, row in baseline.items() if row != after[name]]
        self.assertEqual(sorted(changed), sorted(remote.ASSETS))
        for name in remote.ASSETS:
            self.assertEqual((self.root / name).read_bytes(), self.candidate_assets[name])
        self.assertEqual((self.root / 'data_pipeline').stat().st_ino, data_inode)
        self.assertEqual((self.root / 'data_pipeline/utility.py').stat().st_mode & 0o777, 0o750)
        self.assertEqual(sum(left == self.root / 'app' for left, _ in self.exchanges), 1)
        remote.run_schema.assert_called_once_with(self.env)
        remote.origin_check.assert_called_once_with(pins[2], pins[4])
        private = Path(receipt['private_backup_directory'])
        self.assertEqual(private.stat().st_mode & 0o777, 0o700)
        archive = private / 'installed-whole-package.tar'
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        with tarfile.open(archive) as saved:
            names = saved.getnames()
            self.assertIn('app/server.py', names)
            self.assertIn('data_pipeline/utility.py', names)
            self.assertIn('data_pipeline/dashboard_server.py.bak', names)
            self.assertIn('app/static/._asset', names)
            self.assertFalse(any('__pycache__' in name for name in names))
        old_app = private / 'candidate/app'
        for name, raw in self.old_assets.items():
            self.assertEqual((old_app / name.removeprefix('app/')).read_bytes(), raw)
        for name in remote.PRESERVED:
            self.assertEqual(after[name], baseline[name])
        self.assertTrue(receipt['backend_bytes_unchanged'])
        self.assertTrue(receipt['non_target_assets_unchanged'])
        self.assertEqual(receipt['provider_calls'], 0)
        self.assertEqual(receipt['service_operations'], 0)
        self.assertFalse(receipt['rollback_performed'])

    def test_candidate_paths_reject_missing_extra_and_default_assets(self):
        for assets in ({}, {'app/static/app.js': 'YQ=='},
                       {**json.loads(self.payload)['assets'], 'app/static/app.css': 'YQ=='}):
            with self.subTest(paths=list(assets)):
                self.assert_code('candidate_paths_not_exact', lambda: remote.validate_candidates(
                    json.dumps({'assets': assets}).encode(), self.pins()[2]))

    def test_candidate_bytes_require_both_exact_hashes_and_utf8(self):
        self.assertEqual(remote.validate_candidates(self.payload, self.pins()[2]), self.candidate_assets)
        pins = {**self.pins()[2], remote.ASSETS[1]: 'f' * 64}
        self.assert_code('candidate_hash_mismatch', lambda: remote.validate_candidates(self.payload, pins))
        payload = json.loads(self.payload)
        payload['assets'][remote.ASSETS[1]] = base64.b64encode(b'\xff').decode()
        self.assert_code('candidate_content_invalid', lambda: remote.validate_candidates(json.dumps(payload).encode(), pins))

    def test_source_drift_before_apply_fails_before_private_or_schema_work(self):
        pins = self.pins()
        self.put('app/server.py', b'concurrent backend')
        self.assert_code('inventory_pin_changed', lambda: remote.apply(*pins))
        self.assertFalse(self.releases.exists())
        remote.run_schema.assert_not_called()

    def test_control_or_pid_drift_before_apply_rejected(self):
        pins = self.pins()
        self.controls['units']['recursive-agents']['MainPID'] = '999'
        self.assert_code('inventory_pin_changed', lambda: remote.apply(*pins))

    def test_wrong_source_or_candidate_hash_is_never_adopted(self):
        for index in (1, 4):
            pins = list(self.pins())
            name = remote.ASSETS[0] if index == 1 else remote.PRESERVED[0]
            pins[index] = {**pins[index], name: 'f' * 64}
            self.assert_code('inventory_pin_changed', lambda: remote.apply(*pins))

    def test_incomplete_or_non_literal_pins_rejected(self):
        pins = list(self.pins())
        pins[1] = {'app/server.py': 'a' * 64}
        self.assert_code('invalid_apply_pin', lambda: remote.apply(*pins))

    def test_backend_drift_during_clone_blocks_before_schema_and_exchange(self):
        clone = remote.clone_archive
        def drift(*args):
            result = clone(*args)
            self.put('app/server.py', b'new concurrent source')
            return result
        with patch.object(remote, 'clone_archive', side_effect=drift):
            receipt = self.execute()
        self.assertEqual(receipt['status'], 'failed_before_exchange')
        self.assertEqual(receipt['error_code'], 'source_or_controls_changed_before_schema')
        self.assertFalse(receipt['source_exchanged'])
        remote.run_schema.assert_not_called()

    def test_schema_failure_leaves_original_source_running(self):
        original = remote.scan(self.root)
        remote.run_schema.side_effect = remote.RemovalError('full_schema_failed')
        receipt = self.execute()
        self.assertEqual(receipt['status'], 'failed_before_exchange')
        self.assertEqual(remote.scan(self.root), original)
        self.assertTrue(receipt['private_backup_retained'])
        self.assertFalse(receipt['source_exchanged'])

    def test_schema_failure_receipt_preserves_only_deliberate_diagnostics(self):
        original = remote.scan(self.root)
        error = remote.RemovalError('full_schema_failed')
        error.details = {'stage': 'schema_main', 'exception_class': 'OperationalError', 'mysql_code': 2013}
        remote.run_schema.side_effect = error
        receipt = self.execute()
        self.assertEqual(receipt['status'], 'failed_before_exchange')
        self.assertEqual(receipt['schema_details'], error.details)
        self.assertFalse(receipt['source_exchanged'])
        self.assertFalse(receipt['schema_migrated'])
        self.assertEqual(remote.scan(self.root), original)
        self.assertNotIn('private-db-value', json.dumps(receipt))
        remote.origin_check.assert_not_called()

    def test_source_or_control_change_during_schema_blocks_exchange(self):
        remote.run_schema.side_effect = lambda env: self.controls['units']['recursive-agents'].update(MainPID='999')
        receipt = self.execute()
        self.assertEqual(receipt['error_code'], 'source_or_controls_changed_before_exchange')
        self.assertFalse(receipt['source_exchanged'])

    def test_private_candidate_tamper_before_cutover_rejected(self):
        def tamper(env):
            candidate = next(self.releases.glob('meridian-workspace-*/candidate'))
            (candidate / 'app/server.py').write_bytes(b'candidate drift')
        remote.run_schema.side_effect = tamper
        receipt = self.execute()
        self.assertEqual(receipt['error_code'], 'source_or_controls_changed_before_exchange')

    def test_failed_exchange_probe_never_touches_installed_source(self):
        remote.exchange.side_effect = remote.RemovalError('atomic_exchange_unavailable')
        receipt = self.execute()
        self.assertEqual(receipt['error_code'], 'atomic_exchange_unavailable')
        self.assertFalse(receipt['source_exchanged'])
        remote.run_schema.assert_not_called()

    def test_post_exchange_source_drift_preserves_installed_and_old_app(self):
        self.exchange_callback = lambda: self.put('app/server.py', b'concurrent post-exchange source')
        receipt = self.execute()
        self.assertEqual(receipt['status'], 'installed_state_requires_inspection')
        self.assertEqual(receipt['error_code'], 'source_or_controls_changed_after_exchange')
        self.assertTrue(receipt['source_exchanged'])
        self.assertFalse(receipt['rollback_performed'])
        self.assertEqual((self.root / remote.ASSETS[0]).read_bytes(), self.candidate_assets[remote.ASSETS[0]])
        self.assertEqual((Path(receipt['private_backup_directory']) / 'candidate' / remote.ASSETS[0]).read_bytes(),
                         self.old_assets[remote.ASSETS[0]])

    def test_post_exchange_control_drift_never_restarts_or_rolls_back(self):
        self.exchange_callback = lambda: self.controls['units']['recursive-history'].update(MainPID='999')
        receipt = self.execute()
        self.assertEqual(receipt['status'], 'installed_state_requires_inspection')
        self.assertFalse(receipt['rollback_performed'])
        remote.origin_check.assert_not_called()

    def test_origin_failure_after_exchange_is_reported_without_rollback(self):
        remote.origin_check.side_effect = remote.RemovalError('origin_asset_hash_mismatch')
        receipt = self.execute()
        self.assertEqual(receipt['status'], 'installed_state_requires_inspection')
        self.assertTrue(receipt['source_exchanged'])
        self.assertFalse(receipt['rollback_performed'])

    def test_verification_drift_after_origin_check_is_detected(self):
        remote.origin_check.side_effect = lambda hashes, preserved: self.controls['units']['recursive-engine'].update(MainPID='999')
        receipt = self.execute()
        self.assertEqual(receipt['error_code'], 'source_or_controls_changed_during_verification')

    def test_symlink_or_writable_source_rejected(self):
        link = self.root / 'app/static/leak.js'
        link.symlink_to('/etc/passwd')
        self.assert_code('source_symlink_not_supported', remote.inventory)
        link.unlink()
        os.chmod(self.root / 'app/server.py', 0o666)
        self.assert_code('unsafe_regular_file', remote.inventory)

    def test_hardlinked_source_rejected(self):
        os.link(self.root / 'app/server.py', self.root / 'app/server-copy.py')
        self.assert_code('unsafe_regular_file', remote.inventory)

    def test_root_and_parent_metadata_are_bound_in_fingerprint(self):
        pins = self.pins()
        os.chmod(self.root, 0o700)
        self.assert_code('inventory_pin_changed', lambda: remote.apply(*pins))

    def test_private_release_directory_cannot_be_non_private(self):
        self.releases.mkdir(mode=0o755)
        self.assert_code('unsafe_directory', lambda: self.execute())

    def test_full_schema_transport_is_bounded_and_discards_output(self):
        # Call the actual wrapper, with only the child process replaced.
        self.patches[-2].stop()
        try:
            report = json.dumps({'ok': True, 'stage': 'schema_main', 'exception_class': None, 'mysql_code': None}).encode()
            with patch.object(remote.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, report, b'PRIVATE')) as child:
                remote.run_schema(self.env)
            call = child.call_args
            self.assertEqual(call.kwargs['cwd'], self.root)
            self.assertEqual(call.kwargs['timeout'], 120)
            self.assertTrue(call.kwargs['capture_output'])
            self.assertEqual(call.kwargs['env']['MYSQL_PASSWORD'], self.env['MYSQL_PASSWORD'])
            self.assertEqual(call.kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
            self.assertNotIn('PYTHONDONTWRITEBYTECODE', self.env)
            self.assertIn('schema.main()', call.args[0][-1])
            self.assertIn('lock_wait_timeout=3', call.args[0][-1])
            self.assertIn('kw["connect_timeout"]=5', call.args[0][-1])
            self.assertIn('kw["read_timeout"]=60;kw["write_timeout"]=60', call.args[0][-1])
        finally:
            self.patches[-2].start()

    def test_schema_transport_exception_cannot_expose_private_values(self):
        self.patches[-2].stop()
        try:
            with patch.object(remote.subprocess, 'run', side_effect=RuntimeError('SECRET=private')):
                self.assert_code('full_schema_timeout_or_transport_failed', lambda: remote.run_schema(self.env))
        finally:
            self.patches[-2].start()

    def schema_child_code(self):
        report = json.dumps({'ok': True, 'stage': 'schema_main', 'exception_class': None, 'mysql_code': None}).encode()
        self.patches[-2].stop()
        try:
            with patch.object(remote.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, report, b'')) as child:
                remote.run_schema(self.env)
            return child.call_args.args[0][-1]
        finally:
            self.patches[-2].start()

    def test_schema_mysql_error_reports_only_class_code_and_fixed_stage(self):
        report = {'ok': False, 'stage': 'schema_main', 'exception_class': 'OperationalError', 'mysql_code': 2013}
        self.patches[-2].stop()
        try:
            with patch.object(remote.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, json.dumps(report).encode(), b'SQL=private-account')):
                with self.assertRaises(remote.RemovalError) as caught:
                    remote.run_schema(self.env)
            self.assertEqual(caught.exception.code, 'full_schema_failed')
            self.assertEqual(caught.exception.details, {key: report[key] for key in ('stage', 'exception_class', 'mysql_code')})
            self.assertNotIn('SQL', repr(caught.exception.details))
        finally:
            self.patches[-2].start()

    def test_schema_process_timeout_reports_no_captured_stdout_or_stderr(self):
        self.patches[-2].stop()
        try:
            failure = subprocess.TimeoutExpired(['synthetic'], 120, output=b'PRIVATE_OUTPUT', stderr=b'PRIVATE_ERROR')
            with patch.object(remote.subprocess, 'run', side_effect=failure):
                with self.assertRaises(remote.RemovalError) as caught:
                    remote.run_schema(self.env)
            self.assertEqual(caught.exception.code, 'full_schema_timeout_or_transport_failed')
            self.assertEqual(caught.exception.details, {'stage': 'child_process', 'exception_class': 'TimeoutExpired', 'mysql_code': None})
            self.assertNotIn('PRIVATE', repr(caught.exception.details))
        finally:
            self.patches[-2].start()

    def test_schema_receipt_rejects_messages_unknown_classes_stages_and_noninteger_codes(self):
        good = {'ok': False, 'stage': 'schema_main', 'exception_class': 'OperationalError', 'mysql_code': 2013}
        forged = [b'SQL=private-account', json.dumps({**good, 'message': 'PRIVATE'}).encode(),
                  json.dumps({**good, 'exception_class': 'PRIVATE'}).encode(),
                  json.dumps({**good, 'stage': 'PRIVATE'}).encode(),
                  json.dumps({**good, 'mysql_code': True}).encode()]
        self.patches[-2].stop()
        try:
            for raw in forged:
                with self.subTest(raw=raw):
                    with patch.object(remote.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, raw, b'PRIVATE')):
                        with self.assertRaises(remote.RemovalError) as caught:
                            remote.run_schema(self.env)
                    self.assertEqual(caught.exception.details, {'stage': 'child_report', 'exception_class': 'ChildReportUnavailable', 'mysql_code': None})
        finally:
            self.patches[-2].start()

    def test_schema_child_calls_full_main_and_suppresses_python_and_fd_logs(self):
        code = self.schema_child_code()
        prelude = '''import sys,types,os,pathlib
mysql=types.ModuleType("pymysql")
class OperationalError(Exception):pass
mysql.err=types.SimpleNamespace(Error=OperationalError)
def connect(*a,**kw):
 assert kw["connect_timeout"]==5 and kw["read_timeout"]==60 and kw["write_timeout"]==60
 assert kw["init_command"]=="SET SESSION lock_wait_timeout=3, innodb_lock_wait_timeout=3"
mysql.connect=connect
app=types.ModuleType("app");schema=types.ModuleType("app.schema")
def main():
 print("PRIVATE_SQL_LOG")
 os.write(1,b"PRIVATE_FD_STDOUT");os.write(2,b"PRIVATE_FD_STDERR")
 mysql.connect()
 pathlib.Path("full-main-proof").write_text("called")
schema.main=main;app.schema=schema
sys.modules.update({"pymysql":mysql,"app":app,"app.schema":schema})
'''
        # Actual disposable child, fake schema/PyMySQL modules: no DB/network.
        completed = subprocess.run([sys.executable, '-B', '-c', prelude + code], cwd=self.parent,
                                   capture_output=True, timeout=5)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout), {'ok': True, 'stage': 'schema_main', 'exception_class': None, 'mysql_code': None})
        self.assertEqual(completed.stderr, b'')
        self.assertEqual((self.parent / 'full-main-proof').read_text(), 'called')
        self.assertNotIn(b'PRIVATE', completed.stdout)
        failed_prelude = prelude.replace('pathlib.Path("full-main-proof").write_text("called")', 'raise OperationalError(2013,"PRIVATE_SQL_ERROR")')
        completed = subprocess.run([sys.executable, '-B', '-c', failed_prelude + code], cwd=self.parent,
                                   capture_output=True, timeout=5)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(json.loads(completed.stdout), {'ok': False, 'stage': 'schema_main', 'exception_class': 'OperationalError', 'mysql_code': 2013})
        self.assertEqual(completed.stderr, b'')
        self.assertNotIn(b'PRIVATE', completed.stdout)

    def test_actual_exchange_syscall_errors_are_sanitized(self):
        self.patches[-4].stop()
        try:
            with patch.object(remote.ctypes, 'CDLL', side_effect=RuntimeError('PRIVATE')):
                self.assert_code('atomic_exchange_unavailable', lambda: remote.exchange('a', 'b'))
        finally:
            self.patches[-4].start()

    def test_explicit_deploy_owner_allowed_for_source_but_not_unit_or_private_paths(self):
        path = self.root / 'app/server.py'
        original_fstat = remote.os.fstat
        original_lstat = Path.lstat
        inode = path.stat().st_ino
        directory_inode = self.root.stat().st_ino
        def with_owner(info):
            if info.st_ino not in {inode, directory_inode}:
                return info
            fields = {key: getattr(info, key) for key in dir(info) if key.startswith('st_')}
            fields['st_uid'] = 1000
            return SimpleNamespace(**fields)
        with patch.object(remote.os, 'fstat', side_effect=lambda fd: with_owner(original_fstat(fd))), \
             patch.object(Path, 'lstat', side_effect=lambda p: with_owner(original_lstat(p)), autospec=True):
            self.assertEqual(remote.layout()['root']['uid'], 1000)
            self.assertEqual(remote.read_regular(path, owners={os.geteuid(), 1000})[0], path.read_bytes())
            self.assert_code('unsafe_regular_file', lambda: remote.read_regular(path))
            self.assert_code('unsafe_directory', lambda: remote.safe_directory(self.root, private=True))
            self.assertEqual(remote.scan(self.root)['app/server.py']['uid'], 1000)

    @contextlib.contextmanager
    def actual_unit_fixture(self, owner_map=None):
        unit_root, proc_root = self.parent / 'unit-root', self.parent / 'proc-root'
        unit_root.mkdir()
        proc_root.mkdir()
        aws_env, app_env = self.root / '.env.aws', self.root / '.env.app'
        overlay = self.parent / 'root-provider.env'
        for path in (aws_env, app_env, overlay):
            path.write_bytes(b'PRIVATE=never-export\n')
            os.chmod(path, 0o600)
        properties = {}
        for i, service in enumerate(remote.SERVICES, 11):
            pid = i if service != 'kalshi-live-engine' else 0
            unit = unit_root / (service + '.service')
            unit.write_bytes(b'[Service]\nType=simple\n')
            os.chmod(unit, 0o644)
            values = {key: '' for key in remote.PROPERTIES}
            values.update(MainPID=str(pid), ActiveState='active' if pid else 'inactive',
                          FragmentPath=str(unit), DropInPaths='', NeedDaemonReload='no', Type='simple',
                          WorkingDirectory=str(self.root), Environment='PRIVATE_INLINE=never-export-inline',
                          MemoryMax='419430400', Restart='always', Nice='5', KillMode='control-group', KillSignal='15',
                          ExecStart='{ path=/bin/bash ; argv[]=/bin/bash -c exec python ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=' + str(pid) + ' ; code=(null) ; status=0/0 }')
            values.pop('EnvironmentFiles')  # Actual host omits this empty list property.
            properties[service] = values
            if pid:
                proc = proc_root / str(pid)
                proc.mkdir()
                suffix = {'recursive-web': ['-m', 'app.server'], 'recursive-agents': ['-m', 'app.worker', 'agents'],
                          'recursive-engine': ['-m', 'app.worker', 'engine'], 'recursive-history': ['-m', 'app.market_history']}[service]
                (proc / 'cmdline').write_bytes(b'\0'.join(v.encode() for v in [remote.PYTHON, '-u', *suffix]) + b'\0')
                (proc / 'environ').write_bytes(b'\0'.join((k + '=' + v).encode() for k, v in self.env.items()) + b'\0')
                (proc / 'stat').write_text(str(pid) + ' (python) ' + ' '.join(['S', *(['0'] * 18), '9988']))
                (proc / 'cwd').symlink_to(self.root, target_is_directory=True)
        calls = []
        def show(args, **kwargs):
            calls.append(args)
            raw = '\n'.join(k + '=' + v for k, v in properties[args[2]].items()).encode()
            return subprocess.CompletedProcess(args, 0, raw, b'')
        native_fstat, native_lstat = os.fstat, Path.lstat
        owner_map = owner_map or {}
        inode_owners = {path.stat().st_ino: owner for path, owner in owner_map.items()}
        def selected_owner(info):
            if info.st_ino not in inode_owners:
                return info
            fields = {key: getattr(info, key) for key in dir(info) if key.startswith('st_')}
            fields['st_uid'] = inode_owners[info.st_ino]
            return SimpleNamespace(**fields)
        self.patches[3].stop()
        try:
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(remote, 'UNIT_ROOTS', (unit_root,)))
                stack.enter_context(patch.object(remote, 'PROC', proc_root))
                stack.enter_context(patch.object(remote, 'CONFIG', (aws_env, app_env, overlay)))
                stack.enter_context(patch.object(remote.subprocess, 'run', side_effect=show))
                stack.enter_context(patch.object(remote.os, 'fstat', side_effect=lambda fd: selected_owner(native_fstat(fd))))
                stack.enter_context(patch.object(Path, 'lstat', side_effect=lambda p: selected_owner(native_lstat(p)), autospec=True))
                yield properties, calls, overlay, inode_owners
        finally:
            self.patches[3].start()

    def test_actual_unit_parser_reads_all_five_without_exporting_env_or_commands(self):
        with self.actual_unit_fixture() as (props, calls, overlay, owners):
            controls, private_env = remote.unit_state()
            self.assertEqual(len(controls['units']), 5)
            self.assertEqual(len(controls['unit_files']), 5)
            self.assertEqual(len(controls['processes']), 4)
            self.assertEqual(private_env, self.env)
            self.assertEqual(controls['units']['kalshi-live-engine']['MainPID'], '0')
            self.assertEqual(controls['units']['recursive-web']['EnvironmentFiles'], '')
            serialized = json.dumps(controls)
            for private in ('never-export-inline', 'never-export', 'private-never-print', 'private-db-value', 'argv[]='):
                self.assertNotIn(private, serialized)
            self.assertEqual(len(calls), 5)
            self.assertTrue(all(call[:2] == ['systemctl', 'show'] for call in calls))
            props['recursive-web']['ExecStart'] = 'private-malformed-command'
            self.assert_code('unrecognized_loaded_exec', remote.unit_state)

    def test_actual_base_env_accepts_pinned_deploy_owner_but_overlay_stays_root_only(self):
        # Files are created inside actual_unit_fixture; pin the ROOT inode now,
        # then add the freshly-created base file and overlay in the yielded map.
        with self.actual_unit_fixture({self.root: 1000}) as (props, calls, overlay, owners):
            owners[(self.root / '.env.aws').stat().st_ino] = 1000
            controls, _ = remote.unit_state()
            self.assertEqual(controls['config'][str(self.root / '.env.aws')]['uid'], 1000)
            self.assertEqual(controls['config'][str(overlay)]['uid'], os.geteuid())
            owners[overlay.stat().st_ino] = 1000
            self.assert_code('unsafe_regular_file', remote.unit_state)

    def test_legacy_read_only_and_readable_base_modes_are_preserved(self):
        with self.actual_unit_fixture() as (props, calls, overlay, owners):
            before, _ = remote.unit_state()
            for name, mode in (('.env.aws', 0o400), ('.env.app', 0o644)):
                path = self.root / name
                os.chmod(path, mode)
                controls, _ = remote.unit_state()
                self.assertEqual(controls['config'][str(path)]['mode'], mode)
                self.assertEqual(path.stat().st_mode & 0o777, mode)
                self.assertNotEqual(remote.fingerprint(controls), remote.fingerprint(before))

    def test_writable_base_and_non_private_root_overlays_still_rejected(self):
        with self.actual_unit_fixture() as (props, calls, overlay, owners):
            path = self.root / '.env.aws'
            os.chmod(path, 0o660)
            self.assert_code('unsafe_regular_file', remote.unit_state)
            os.chmod(path, 0o600)
            for mode in (0o400, 0o644):
                with self.subTest(mode=mode):
                    os.chmod(overlay, mode)
                    self.assert_code('private_environment_permissions_unsafe', remote.unit_state)

    def test_inventory_reports_only_fixed_config_owners_and_modes_not_values_or_hashes(self):
        with self.actual_unit_fixture() as (props, calls, overlay, owners):
            os.chmod(self.root / '.env.aws', 0o400)
            os.chmod(self.root / '.env.app', 0o644)
            receipt = remote.inventory()
            expected = {str(self.root / '.env.aws'): '0400', str(self.root / '.env.app'): '0644', str(overlay): '0600'}
            self.assertEqual(set(receipt['configuration_file_metadata']), set(expected))
            for path, row in receipt['configuration_file_metadata'].items():
                self.assertEqual(set(row), {'uid', 'gid', 'mode'})
                self.assertEqual(row['mode'], expected[path])
                self.assertEqual(row['uid'], os.geteuid())
                self.assertEqual(row['gid'], Path(path).stat().st_gid)
            self.assertNotIn('never-export', json.dumps(receipt))
            self.assertNotIn('private-db-value', json.dumps(receipt))
            self.assertFalse(self.releases.exists())

    def test_base_metadata_drift_after_inventory_still_blocks_apply(self):
        with self.actual_unit_fixture() as (props, calls, overlay, owners):
            pins = self.pins()
            os.chmod(self.root / '.env.aws', 0o400)
            self.assert_code('inventory_pin_changed', lambda: remote.apply(*pins))
            self.assertFalse(self.releases.exists())

    def html(self, candidates, preserved):
        return ('<link href="/static/app.css?v=' + preserved['app/static/app.css'][:10] + '">'
                '<div data-tau-js="/static/app.js?v=' + preserved['app/static/app.js'][:10] + '" '
                'data-tau-ver="' + preserved['app/static/app.js'][:10] + '" '
                'data-mer-css="/static/app.meridian.css?v=' + candidates['app/static/app.meridian.css'][:10] + '" '
                'data-mer-js="/static/app.meridian.js?v=' + candidates['app/static/app.meridian.js'][:10] + '" '
                'data-mer-ver="' + candidates['app/static/app.meridian.js'][:10] + '"></div>'
                '<script src="/static/boot.js?v=' + preserved['app/static/boot.js'][:10] + '"></script>').encode()

    def test_actual_origin_checker_verifies_meridian_css_default_bytes_and_distinct_versions(self):
        self.patches[-1].stop()
        try:
            candidates, preserved = self.pins()[2], self.pins()[4]
            html = self.html(candidates, preserved)
            payloads = {p: html for p in ('/', '/funds', '/research')}
            payloads.update({'/healthz': b'{"ok":true}',
                             '/api/version': json.dumps({'v': preserved['app/static/app.js'][:10]}).encode()})
            payloads.update({'/' + p.removeprefix('app/'): raw for p, raw in self.candidate_assets.items()})
            payloads.update({'/' + p.removeprefix('app/'): (self.root / p).read_bytes()
                             for p in remote.PRESERVED if not p.endswith('index.html')})
            class Response:
                status = 200
                def __init__(self, raw): self.raw = raw
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self, size): return self.raw[:size]
            with patch.object(remote.urllib.request, 'urlopen', side_effect=lambda url, timeout: Response(payloads[url.removeprefix('http://127.0.0.1:8090')])):
                remote.origin_check(candidates, preserved)
                payloads['/api/version'] = json.dumps({'v': candidates[remote.ASSETS[0]][:10]}).encode()
                self.assert_code('origin_version_mismatch', lambda: remote.origin_check(candidates, preserved))
                payloads['/api/version'] = json.dumps({'v': preserved['app/static/app.js'][:10]}).encode()
                payloads['/static/app.meridian.css'] = b'wrong css'
                self.assert_code('origin_asset_hash_mismatch', lambda: remote.origin_check(candidates, preserved))
                payloads['/static/app.meridian.css'] = self.candidate_assets['app/static/app.meridian.css']
                payloads['/static/app.css'] = b'default css drift'
                self.assert_code('origin_asset_hash_mismatch', lambda: remote.origin_check(candidates, preserved))
                payloads['/static/app.css'] = (self.root / 'app/static/app.css').read_bytes()
                payloads['/funds'] = html.replace(candidates[remote.ASSETS[1]][:10].encode(), b'wrong-css')
                self.assert_code('origin_html_version_mismatch', lambda: remote.origin_check(candidates, preserved))
                payloads['/funds'] = html
                payloads['/healthz'] = b'{"ok":false}'
                self.assert_code('origin_unhealthy', lambda: remote.origin_check(candidates, preserved))
        finally:
            self.patches[-1].start()

    def test_transfer_rejects_unauthorized_former_prefix(self):
        wrong = {**self.artifact, 'key': self.artifact['key'].replace('bundle/', 'frontend/', 1)}
        self.patches[-3].stop()
        try:
            self.assert_code('invalid_candidate_artifact', lambda: remote.load_candidates(wrong, self.pins()[2]))
        finally:
            self.patches[-3].start()

    def test_actual_candidate_download_is_bound_to_private_artifact_and_exact_paths(self):
        self.patches[-3].stop()
        try:
            response = subprocess.CompletedProcess([], 0, self.payload, b'PRIVATE STDERR')
            with patch.object(remote.subprocess, 'run', return_value=response) as child:
                self.assertEqual(remote.load_candidates(self.artifact, self.pins()[2]), self.candidate_assets)
                self.assertEqual(child.call_args.kwargs['timeout'], 45)
                self.assertTrue(child.call_args.kwargs['capture_output'])
                self.assertIn('s3://' + remote.BUCKET + '/' + self.artifact['key'], child.call_args.args[0])
                self.assert_code('invalid_candidate_artifact', lambda: remote.load_candidates(
                    {**self.artifact, 'bucket': 'unreviewed'}, self.pins()[2]))
                self.assert_code('candidate_artifact_hash_mismatch', lambda: remote.load_candidates(
                    {**self.artifact, 'sha256': 'f' * 64}, self.pins()[2]))
        finally:
            self.patches[-3].start()

    def test_wrong_candidate_bytes_fail_before_schema_exchange(self):
        pins = list(self.pins())
        pins[2] = {**pins[2], remote.ASSETS[1]: 'f' * 64}
        receipt = remote.apply(*pins)
        self.assertEqual(receipt['error_code'], 'candidate_hash_mismatch')
        self.assertFalse(receipt['source_exchanged'])
        remote.run_schema.assert_not_called()

    def test_unchanged_candidate_file_is_rejected(self):
        self.candidate_assets[remote.ASSETS[1]] = self.old_assets[remote.ASSETS[1]]
        self.assert_code('candidate_asset_not_changed', self.execute)



class AppModeRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tau-app-mode-offline-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'installed'
        self.app = self.root / 'app'
        (self.app / 'static').mkdir(parents=True)
        self.app.chmod(0o775)
        self.files = [self.root / '.env.aws', self.root / '.env.app',
                      *(self.root / path for path in remote.PRESERVED), self.app / 'server.py']
        for path in self.files:
            path.write_bytes(('synthetic unchanged private ' + path.name).encode())
            path.chmod(0o600 if path.name.startswith('.env') else 0o644)
        self.native_fstat, self.native_lstat = os.fstat, Path.lstat
        self.native_fchmod, self.native_close = os.fchmod, os.close
        patches = [patch.object(remote, 'ROOT', self.root), patch.object(remote, 'ROOT_UID', os.geteuid()),
                   patch.object(remote.os, 'fstat', side_effect=lambda fd: self.owned(self.native_fstat(fd))),
                   patch.object(Path, 'lstat', autospec=True, side_effect=lambda path:
                                self.owned(self.native_lstat(path)) if path == self.app else self.native_lstat(path))]
        for active in patches:
            active.start()
            self.addCleanup(active.stop)

    def owned(self, info, **changes):
        values = {key: getattr(info, key) for key in ('st_mode', 'st_uid', 'st_gid', 'st_dev', 'st_ino')}
        values['st_gid'] = 0  # Synthetic root-group metadata; tests never chown.
        values.update(changes)
        return SimpleNamespace(**values)

    def file_state(self):
        return {str(path): (path.read_bytes(), remote.metadata(self.native_lstat(path)), self.native_lstat(path).st_ino)
                for path in self.files}

    def test_exact_app_directory_repair_preserves_files_config_and_other_metadata(self):
        files = self.file_state()
        directories = {path: (remote.metadata(self.native_lstat(path)), self.native_lstat(path).st_ino)
                       for path in (self.root, self.root.parent, self.app / 'static')}
        inode = self.native_lstat(self.app).st_ino
        with patch.object(remote.os, 'fchmod', wraps=self.native_fchmod) as chmod, \
             patch.object(remote.os, 'close', wraps=self.native_close) as close, \
             patch.object(remote, 'layout', wraps=remote.layout) as layout:
            result = remote.repair_app_mode()
        layout.assert_called_once_with()
        chmod.assert_called_once()
        self.assertEqual(chmod.call_args.args[1], 0o755)
        close.assert_called_once_with(chmod.call_args.args[0])
        self.assertEqual(result, {'status': 'permissions_repaired', 'path': str(self.app),
                                 'before_mode': '0775', 'after_mode': '0755', 'content_changes': 0,
                                 'service_operations': 0, 'provider_calls': 0, 'job_mutations': 0})
        self.assertEqual(stat.S_IMODE(self.native_lstat(self.app).st_mode), 0o755)
        self.assertEqual(self.native_lstat(self.app).st_ino, inode)
        self.assertEqual(self.file_state(), files)
        self.assertEqual({path: (remote.metadata(self.native_lstat(path)), self.native_lstat(path).st_ino)
                          for path in directories}, directories)
        self.assertNotIn('private', json.dumps(result))

    def test_wrong_mode_owner_or_group_never_chmod(self):
        for changes in ({'st_mode': stat.S_IFDIR | 0o755}, {'st_mode': stat.S_IFDIR | 0o777},
                        {'st_uid': remote.ROOT_UID + 1}, {'st_gid': 1}):
            with self.subTest(changes=changes), \
                 patch.object(remote.os, 'fstat', side_effect=lambda fd: self.owned(self.native_fstat(fd), **changes)), \
                 patch.object(remote.os, 'fchmod') as chmod, \
                 patch.object(remote.os, 'close', wraps=self.native_close) as close:
                with self.assertRaisesRegex(remote.RemovalError, '^app_mode_repair_precondition_changed$'):
                    remote.repair_app_mode()
                chmod.assert_not_called()
                close.assert_called_once()
            self.assertEqual(stat.S_IMODE(self.native_lstat(self.app).st_mode), 0o775)

    def test_symlink_never_follows_target_or_chmod(self):
        original = self.root / 'original-app'
        self.app.rename(original)
        self.app.symlink_to(original, target_is_directory=True)
        with patch.object(remote.os, 'fchmod') as chmod:
            with self.assertRaisesRegex(remote.RemovalError, '^app_mode_repair_failed$'):
                remote.repair_app_mode()
        chmod.assert_not_called()
        self.assertEqual(stat.S_IMODE(self.native_lstat(original).st_mode), 0o775)

    def test_path_identity_mismatch_never_chmod(self):
        with patch.object(Path, 'lstat', new=lambda path:
                          self.owned(self.native_lstat(path), st_ino=self.native_lstat(path).st_ino + 1)
                          if path == self.app else self.native_lstat(path)), \
             patch.object(remote.os, 'fchmod') as chmod:
            with self.assertRaisesRegex(remote.RemovalError, '^app_mode_repair_path_changed$'):
                remote.repair_app_mode()
        chmod.assert_not_called()

    def test_post_chmod_drift_fails_without_a_second_mutation(self):
        reads = 0
        def changing_stat(fd):
            nonlocal reads
            reads += 1
            return self.owned(self.native_fstat(fd), st_gid=0 if reads == 1 else 1)
        with patch.object(remote.os, 'fstat', side_effect=changing_stat), \
             patch.object(remote.os, 'fchmod', wraps=self.native_fchmod) as chmod, \
             patch.object(remote.os, 'close', wraps=self.native_close) as close:
            with self.assertRaisesRegex(remote.RemovalError, '^app_mode_repair_verification_failed$'):
                remote.repair_app_mode()
        chmod.assert_called_once()
        close.assert_called_once()

    def test_non_root_stops_before_layout_or_open(self):
        with patch.object(remote.os, 'geteuid', return_value=remote.ROOT_UID + 1), \
             patch.object(remote, 'layout') as layout, patch.object(remote.os, 'open') as opened:
            with self.assertRaisesRegex(remote.RemovalError, '^requires_root$'):
                remote.repair_app_mode()
        layout.assert_not_called()
        opened.assert_not_called()

    def test_unsafe_existing_layout_stops_before_open(self):
        self.root.chmod(0o775)
        with patch.object(remote.os, 'open') as opened, patch.object(remote.os, 'fchmod') as chmod:
            with self.assertRaisesRegex(remote.RemovalError, '^unsafe_directory$'):
                remote.repair_app_mode()
        opened.assert_not_called()
        chmod.assert_not_called()


class SourceModeAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tau-source-modes-offline-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'installed'
        (self.root / 'app/static').mkdir(parents=True)
        (self.root / 'data_pipeline').mkdir()
        self.source = self.root / 'app/static/app.js'
        self.source.write_bytes(b'synthetic source content must not print')
        (self.root / 'data_pipeline/worker.py').write_bytes(b'synthetic pipeline content')
        (self.root / '.env.aws').write_bytes(b'private config must not print')
        for active in (patch.object(remote, 'ROOT', self.root), patch.object(remote, 'ROOT_UID', os.geteuid())):
            active.start()
            self.addCleanup(active.stop)

    def state(self):
        return {str(path): (remote.metadata(path.lstat()), path.lstat().st_ino,
                            path.read_bytes() if stat.S_ISREG(path.lstat().st_mode) else None)
                for path in (self.root, *self.root.rglob('*'))}

    def test_metadata_only_audit_preserves_all_state_and_skips_cache_and_symlink_contents(self):
        (self.root / 'app').chmod(0o775)
        self.source.chmod(0o664)
        cache = self.root / 'app/__pycache__'
        cache.mkdir()
        cache.chmod(0o775)
        (cache / 'not-audited').write_bytes(b'private cache content')
        (cache / 'not-audited').chmod(0o777)
        (self.root / 'app/escape').symlink_to(self.root.parent, target_is_directory=True)
        before = self.state()
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('file content read')), \
             patch.object(remote, 'read_regular', side_effect=AssertionError('file content read')), \
             patch.object(remote.os, 'fchmod', side_effect=AssertionError('permission mutation')), \
             patch.object(remote.os, 'chown', side_effect=AssertionError('ownership mutation')), \
             patch.object(remote, 'unit_state', side_effect=AssertionError('service inspection')), \
             patch.object(remote, 'run_schema', side_effect=AssertionError('schema execution')):
            result = remote.audit_source_modes()
        self.assertEqual(result['status'], 'source_modes_audited')
        self.assertTrue(result['read_only'])
        self.assertFalse(result['truncated'])
        rows = {row['path']: row for row in result['unsafe_entries']}
        self.assertEqual(set(rows), {'app', 'app/static/app.js', 'app/__pycache__', 'app/escape'})
        self.assertEqual(rows['app/static/app.js']['mode'], '0664')
        self.assertEqual(rows['app/escape']['type'], 'symlink')
        self.assertEqual(result['unsafe_count'], 4)
        self.assertEqual(self.state(), before)
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('source content', json.dumps(result))
        with self.assertRaisesRegex(remote.RemovalError, '^unsafe_directory$'):
            remote.scan(self.root)

    def test_unexpected_owner_types_and_hardlinks_are_reported_without_following(self):
        foreign = self.root / 'app/foreign.py'
        foreign.write_bytes(b'unchanged')
        os.link(self.source, self.root / 'app/hardlink.js')
        os.mkfifo(self.root / 'app/pipe')
        native_stat = os.stat
        def source_stat(path, *args, **kwargs):
            info = native_stat(path, *args, **kwargs)
            if path == 'foreign.py':
                values = {key: getattr(info, key) for key in ('st_mode', 'st_uid', 'st_gid', 'st_dev', 'st_ino', 'st_nlink')}
                values['st_uid'] = remote.ROOT_UID + 1
                return SimpleNamespace(**values)
            return info
        with patch.object(remote.os, 'stat', side_effect=source_stat):
            result = remote.audit_source_modes()
        rows = {row['path']: row for row in result['unsafe_entries']}
        self.assertIn('unexpected_owner', rows['app/foreign.py']['issues'])
        self.assertIn('unsupported_type', rows['app/pipe']['issues'])
        self.assertEqual(rows['app/pipe']['type'], 'other')
        self.assertIn('hardlinked_file', rows['app/hardlink.js']['issues'])
        self.assertIn('hardlinked_file', rows['app/static/app.js']['issues'])

    def test_result_cap_retains_complete_counts(self):
        for index in range(51):
            path = self.root / 'app' / ('unsafe-' + str(index))
            path.touch()
            path.chmod(0o666)
        result = remote.audit_source_modes()
        self.assertEqual(result['unsafe_count'], 51)
        self.assertEqual(len(result['unsafe_entries']), 50)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['entries'], 56)

    def test_traversal_limit_fails_closed(self):
        (self.root / 'app/repeated').touch()
        native_scandir = os.scandir
        class Entries:
            def __enter__(self): return (SimpleNamespace(name='repeated') for _ in range(8192))
            def __exit__(self, *args): return False
        app_inode = (self.root / 'app').stat().st_ino
        with patch.object(remote.os, 'scandir', side_effect=lambda fd:
                          Entries() if os.fstat(fd).st_ino == app_inode else native_scandir(fd)):
            with self.assertRaisesRegex(remote.RemovalError, '^source_modes_audit_limit$'):
                remote.audit_source_modes()

    def test_unsafe_layout_stops_before_source_open(self):
        self.root.chmod(0o775)
        with patch.object(remote.os, 'open') as opened:
            with self.assertRaisesRegex(remote.RemovalError, '^unsafe_directory$'):
                remote.audit_source_modes()
        opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
