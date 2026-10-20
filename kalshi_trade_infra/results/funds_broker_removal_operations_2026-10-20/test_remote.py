"""Offline temp-directory and mocked-control tests. No DB/network/systemd use."""
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
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location('broker_removal_remote', Path(__file__).with_name('remote.py'))
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
        for name in remote.JS:
            self.put(name, b'// synthetic ' + name.encode() + b'\nconst html=`before' + remote.HOST + b'after`;\n' + remote.MOUNT + b'// preserved tail\n')
        for name in ('app/schema.py', 'app/server.py', 'app/static/index.html', 'app/static/app.css',
                     'data_pipeline/common.py', 'data_pipeline/utility.py', 'data_pipeline/dashboard_server.py.bak',
                     'app/static/._asset', 'app/static/.DS_Store', 'app/__pycache__/ignored.pyc'):
            self.put(name, ('synthetic unchanged ' + name).encode())
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
        return receipt['fingerprint'], receipt['source_sha256'], receipt['candidate_sha256']

    def execute(self):
        return remote.apply(*self.pins())

    def assert_code(self, code, fn):
        with self.assertRaisesRegex(remote.RemovalError, '^' + code + '$'):
            fn()

    def test_inventory_is_read_only_and_receipt_omits_private_data(self):
        before = remote.scan(self.root)
        receipt = remote.inventory()
        self.assertEqual(receipt['status'], 'ready')
        self.assertEqual(set(receipt['source_sha256']), set(remote.JS))
        self.assertEqual(set(receipt['candidate_sha256']), set(remote.JS))
        self.assertEqual(receipt['provider_calls'], 0)
        self.assertNotIn('private-never-print', json.dumps(receipt))
        self.assertNotIn('private-db-value', json.dumps(receipt))
        self.assertEqual(remote.scan(self.root), before)
        self.assertFalse(self.releases.exists())
        self.assertEqual(self.exchanges, [])
        remote.run_schema.assert_not_called()
        remote.origin_check.assert_not_called()

    def test_happy_whole_package_exchange_changes_only_two_js_files(self):
        baseline = remote.scan(self.root)
        data_inode = (self.root / 'data_pipeline').stat().st_ino
        pins = self.pins()
        receipt = remote.apply(*pins)
        self.assertEqual(receipt['status'], 'deployed')
        after = remote.scan(self.root)
        changed = [name for name, row in baseline.items() if row != after[name]]
        self.assertEqual(sorted(changed), sorted(remote.JS))
        for name in remote.JS:
            self.assertNotIn(remote.HOST, (self.root / name).read_bytes())
            self.assertNotIn(b'TauBrokerConnections.mount(', (self.root / name).read_bytes())
        self.assertEqual((self.root / 'data_pipeline').stat().st_ino, data_inode)
        self.assertEqual((self.root / 'data_pipeline/utility.py').stat().st_mode & 0o777, 0o750)
        self.assertEqual(sum(left == self.root / 'app' for left, _ in self.exchanges), 1)
        remote.run_schema.assert_called_once_with(self.env)
        remote.origin_check.assert_called_once_with(pins[2])
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
        self.assertIn(remote.HOST, (old_app / 'static/app.js').read_bytes())
        self.assertTrue(receipt['backend_bytes_unchanged'])
        self.assertTrue(receipt['non_js_assets_unchanged'])
        self.assertEqual(receipt['provider_calls'], 0)
        self.assertEqual(receipt['service_operations'], 0)
        self.assertFalse(receipt['rollback_performed'])

    def test_candidate_requires_both_exact_mount_literals_once(self):
        for raw in (remote.HOST, remote.MOUNT, remote.HOST * 2 + remote.MOUNT, remote.HOST + remote.MOUNT * 2):
            with self.subTest(raw=raw):
                self.assert_code('broker_mount_not_exactly_once', lambda: remote.patched(raw))

    def test_extra_mount_call_rejected_even_after_expected_literals_removed(self):
        self.assert_code('broker_mount_not_fully_removed', lambda: remote.patched(remote.HOST + remote.MOUNT + b'TauBrokerConnections.mount(other);'))

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
        for index in (1, 2):
            pins = list(self.pins())
            pins[index] = {**pins[index], remote.JS[0]: 'f' * 64}
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

    def test_source_or_control_change_during_schema_blocks_exchange(self):
        remote.run_schema.side_effect = lambda env: self.controls['units']['recursive-agents'].update(MainPID='999')
        receipt = self.execute()
        self.assertEqual(receipt['error_code'], 'source_or_controls_changed_before_exchange')
        self.assertFalse(receipt['source_exchanged'])

    def test_private_candidate_tamper_before_cutover_rejected(self):
        def tamper(env):
            candidate = next(self.releases.glob('broker-removal-*/candidate'))
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
        self.assertNotIn(remote.HOST, (self.root / remote.JS[0]).read_bytes())
        self.assertIn(remote.HOST, (Path(receipt['private_backup_directory']) / 'candidate' / remote.JS[0]).read_bytes())

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
        remote.origin_check.side_effect = lambda hashes: self.controls['units']['recursive-engine'].update(MainPID='999')
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
            with patch.object(remote.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'PRIVATE', b'PRIVATE')) as child:
                remote.run_schema(self.env)
            call = child.call_args
            self.assertEqual(call.kwargs['cwd'], self.root)
            self.assertEqual(call.kwargs['timeout'], 60)
            self.assertTrue(call.kwargs['capture_output'])
            self.assertEqual(call.kwargs['env']['MYSQL_PASSWORD'], self.env['MYSQL_PASSWORD'])
            self.assertEqual(call.kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
            self.assertNotIn('PYTHONDONTWRITEBYTECODE', self.env)
            self.assertIn('schema.main()', call.args[0][-1])
            self.assertIn('lock_wait_timeout=3', call.args[0][-1])
        finally:
            self.patches[-2].start()

    def test_schema_transport_exception_cannot_expose_private_values(self):
        self.patches[-2].stop()
        try:
            with patch.object(remote.subprocess, 'run', side_effect=RuntimeError('SECRET=private')):
                self.assert_code('full_schema_timeout_or_transport_failed', lambda: remote.run_schema(self.env))
        finally:
            self.patches[-2].start()

    def test_actual_exchange_syscall_errors_are_sanitized(self):
        self.patches[-3].stop()
        try:
            with patch.object(remote.ctypes, 'CDLL', side_effect=RuntimeError('PRIVATE')):
                self.assert_code('atomic_exchange_unavailable', lambda: remote.exchange('a', 'b'))
        finally:
            self.patches[-3].start()

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

    def test_actual_origin_checker_verifies_version_health_and_exact_js_bytes(self):
        self.patches[-1].stop()
        try:
            candidates = self.pins()[2]
            payloads = {'/': b'<html>synthetic</html>', '/healthz': b'{"ok":true}',
                        '/api/version': json.dumps({'v': candidates[remote.JS[0]][:10]}).encode(),
                        '/static/app.js': remote.patched((self.root / remote.JS[0]).read_bytes()),
                        '/static/app.meridian.js': remote.patched((self.root / remote.JS[1]).read_bytes())}
            calls = []
            def respond(url, **kwargs):
                self.assertTrue(url.startswith('http://127.0.0.1:8090/'))
                path = url.removeprefix('http://127.0.0.1:8090')
                calls.append(path)
                response = io.BytesIO(payloads[path])
                response.status = 200
                return response
            with patch.object(remote.urllib.request, 'urlopen', side_effect=respond):
                remote.origin_check(candidates)
                self.assertEqual(len(calls), 5)
                payloads['/api/version'] = b'{"v":"stale"}'
                self.assert_code('origin_version_mismatch', lambda: remote.origin_check(candidates))
                payloads['/api/version'] = json.dumps({'v': candidates[remote.JS[0]][:10]}).encode()
                payloads['/static/app.js'] = b'stale'
                self.assert_code('origin_asset_hash_mismatch', lambda: remote.origin_check(candidates))
                payloads['/healthz'] = b'{"ok":false}'
                self.assert_code('origin_unhealthy', lambda: remote.origin_check(candidates))
        finally:
            self.patches[-1].start()


if __name__ == '__main__':
    unittest.main()
