"""Single-CSS release checks use disposable source trees and mocked controls only."""
import ast
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import remote


class CssReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tau-header-offline-')
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name).resolve()
        self.root, self.releases = parent / 'installed', parent / 'private-releases'
        self.root.mkdir(mode=0o755)
        self.before_css = b'/* synthetic installed */\n.hot-head { height: 49px; }\n.legal { color: black; }\n.autopilot { display: flex; }\n'
        self.after_css = self.before_css.replace(b'height: 49px', b'height: 50px')
        self.assets = {'app/static/app.css': self.after_css}
        self.preserved = {path: ('synthetic preserved ' + path).encode() for path in remote.PRESERVED}
        files = {**self.preserved, 'app/static/app.css': self.before_css,
                 'app/server.py': b'synthetic unchanged server', 'app/schema.py': b'synthetic full schema',
                 'data_pipeline/common.py': b'synthetic unchanged pipeline',
                 'app/static/unrecognized.override': b'synthetic preserved override',
                 'data_pipeline/utility.py.bak': b'synthetic preserved backup'}
        for name, raw in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o644)
        self.controls = {'units': {'recursive-web': {'MainPID': '123'}, 'recursive-agents': {'MainPID': '124'}},
                         'config': {'private': {'sha256': 'a' * 64}}}
        self.env = {'APP_SECRET_KEY': 'private environment must not print'}
        self.payload = json.dumps({'assets': {'app/static/app.css': base64.b64encode(self.after_css).decode()}}).encode()
        self.artifact = {'bucket': remote.BUCKET, 'key': 'bundle/header-alignment-' + 'a' * 40 + '-' + 'b' * 32 + '.json',
                         'sha256': remote.digest(self.payload)}
        self.real_origin = remote.origin_check
        self.exchanges = []
        self.schema, self.origin = unittest.mock.Mock(), unittest.mock.Mock()
        patches = [patch.object(remote, 'ROOT', self.root), patch.object(remote, 'ROOT_UID', os.geteuid()),
                   patch.object(remote, 'RELEASES', self.releases), patch.object(remote, 'exchange_available', return_value=True),
                   patch.object(remote, 'unit_state', side_effect=lambda: (copy.deepcopy(self.controls), dict(self.env))),
                   patch.object(remote, 'load_candidates', return_value=self.assets),
                   patch.object(remote, 'exchange', side_effect=self.exchange),
                   patch.object(remote, 'run_schema', self.schema), patch.object(remote, 'origin_check', self.origin)]
        for active in patches:
            active.start()
            self.addCleanup(active.stop)

    def exchange(self, left, right):
        self.exchanges.append((left, right))
        temporary = left.parent / '.offline-swap'
        left.rename(temporary)
        right.rename(left)
        temporary.rename(right)

    def pins(self):
        receipt = remote.inventory()
        return (receipt['fingerprint'], receipt['source_sha256'],
                {'app/static/app.css': remote.digest(self.after_css)}, self.artifact, receipt['preserved_sha256'])

    def assert_code(self, code, function):
        with self.assertRaisesRegex(remote.RemovalError, '^' + code + '$'):
            function()

    def test_inventory_is_read_only_and_pins_default_css_and_both_unchanged_themes(self):
        before = remote.scan(self.root)
        receipt = remote.inventory()
        self.assertEqual(set(receipt['source_sha256']), {'app/static/app.css'})
        self.assertEqual(set(receipt['preserved_sha256']), set(self.preserved))
        self.assertEqual(remote.scan(self.root), before)
        self.assertTrue(receipt['read_only'])
        self.assertFalse(self.releases.exists())
        self.assertEqual(self.exchanges, [])
        self.schema.assert_not_called()
        self.assertNotIn('private environment', json.dumps(receipt))

    def test_whole_package_exchange_changes_only_css_and_keeps_installed_unpublished_styles(self):
        before = remote.scan(self.root)
        pipeline_inode = (self.root / 'data_pipeline').stat().st_ino
        result = remote.apply(*self.pins())
        after = remote.scan(self.root)
        self.assertEqual(result['status'], 'deployed')
        self.assertEqual([name for name in before if before[name] != after[name]], ['app/static/app.css'])
        self.assertEqual((self.root / 'app/static/app.css').read_bytes(), self.after_css)
        self.assertIn(b'.legal', self.after_css)
        self.assertIn(b'.autopilot', self.after_css)
        for name, raw in self.preserved.items():
            self.assertEqual((self.root / name).read_bytes(), raw)
        self.assertEqual((self.root / 'data_pipeline').stat().st_ino, pipeline_inode)
        self.schema.assert_called_once_with(self.env)
        self.assertTrue(result['javascript_assets_unchanged'])
        self.assertTrue(result['meridian_assets_unchanged'])
        self.assertTrue(result['service_pids_unchanged'])
        self.assertFalse(result['rollback_performed'])
        private = Path(result['private_backup_directory'])
        self.assertEqual((private / 'candidate/app/static/app.css').read_bytes(), self.before_css)
        with tarfile.open(private / 'installed-whole-package.tar') as archive:
            self.assertIn('app/server.py', archive.getnames())
            self.assertIn('data_pipeline/utility.py.bak', archive.getnames())
        self.assertEqual(sum(left == self.root / 'app' for left, right in self.exchanges), 1)

    def test_transfer_rejects_every_path_except_single_default_css_and_requires_hash_utf8(self):
        pins = self.pins()[2]
        self.assertEqual(remote.validate_candidates(self.payload, pins), self.assets)
        for paths in ({}, {'app/static/app.js': 'YQ=='},
                      {**json.loads(self.payload)['assets'], 'app/static/app.meridian.css': 'YQ=='}):
            self.assert_code('candidate_paths_not_exact', lambda: remote.validate_candidates(json.dumps({'assets': paths}).encode(), pins))
        for raw, code in ((b'wrong hash', 'candidate_hash_mismatch'), (b'\xff', 'candidate_content_invalid'),
                          (b'\0', 'candidate_content_invalid')):
            payload = json.dumps({'assets': {'app/static/app.css': base64.b64encode(raw).decode()}}).encode()
            self.assert_code(code, lambda: remote.validate_candidates(payload, pins))

    def test_actual_transfer_download_requires_exact_private_namespace_and_content_hash(self):
        # The fixture replaces load_candidates for apply; invoke its original implementation directly.
        source = Path(remote.__file__).read_text()
        namespace = {}
        exec(compile(source, '<header-transfer-check>', 'exec'), namespace)
        load = namespace['load_candidates']
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, self.payload, b'PRIVATE')):
            self.assertEqual(load(self.artifact, self.pins()[2]), self.assets)
            for key in ('bundle/meridian-' + 'a' * 40 + '-' + 'b' * 32 + '.json', 'frontend/header-alignment-invalid.json'):
                with self.assertRaisesRegex(namespace['RemovalError'], '^invalid_candidate_artifact$'):
                    load({**self.artifact, 'key': key}, self.pins()[2])
            with self.assertRaisesRegex(namespace['RemovalError'], '^candidate_artifact_hash_mismatch$'):
                load({**self.artifact, 'sha256': 'f' * 64}, self.pins()[2])

    def test_any_theme_asset_or_pid_drift_blocks_before_schema_or_exchange(self):
        for name in ('app/static/app.css', *remote.PRESERVED):
            with self.subTest(path=name):
                pins = self.pins()
                path = self.root / name
                raw = path.read_bytes()
                path.write_bytes(b'concurrent drift')
                self.assert_code('inventory_pin_changed', lambda: remote.apply(*pins))
                path.write_bytes(raw)
        pins = self.pins()
        self.controls['units']['recursive-web']['MainPID'] = '999'
        self.assert_code('inventory_pin_changed', lambda: remote.apply(*pins))
        self.schema.assert_not_called()
        self.assertEqual(self.exchanges, [])

    def test_schema_failure_is_sanitized_and_keeps_original_package(self):
        error = remote.RemovalError('full_schema_failed')
        error.details = {'stage': 'schema_main', 'exception_class': 'OperationalError', 'mysql_code': 2013}
        self.schema.side_effect = error
        result = remote.apply(*self.pins())
        self.assertEqual(result['status'], 'failed_before_exchange')
        self.assertEqual(result['schema_details'], error.details)
        self.assertFalse(result['source_exchanged'])
        self.assertEqual((self.root / 'app/static/app.css').read_bytes(), self.before_css)
        self.assertNotIn('private environment', json.dumps(result))

    def test_origin_failure_after_exchange_retains_both_states_without_rollback(self):
        self.origin.side_effect = remote.RemovalError('origin_asset_hash_mismatch')
        result = remote.apply(*self.pins())
        self.assertEqual(result['status'], 'installed_state_requires_inspection')
        self.assertTrue(result['source_exchanged'])
        self.assertFalse(result['rollback_performed'])
        self.assertEqual((self.root / 'app/static/app.css').read_bytes(), self.after_css)
        self.assertEqual((Path(result['private_backup_directory']) / 'candidate/app/static/app.css').read_bytes(), self.before_css)

    def html(self, candidates, preserved):
        return ('<link href="/static/app.css?v=' + candidates['app/static/app.css'][:10] + '">'
                '<div data-tau-js="/static/app.js?v=' + preserved['app/static/app.js'][:10] + '" '
                'data-tau-ver="' + preserved['app/static/app.js'][:10] + '" '
                'data-mer-css="/static/app.meridian.css?v=' + preserved['app/static/app.meridian.css'][:10] + '" '
                'data-mer-js="/static/app.meridian.js?v=' + preserved['app/static/app.meridian.js'][:10] + '" '
                'data-mer-ver="' + preserved['app/static/app.meridian.js'][:10] + '"></div>'
                '<script src="/static/boot.js?v=' + preserved['app/static/boot.js'][:10] + '"></script>').encode()

    def test_origin_versions_pin_new_default_css_and_unchanged_default_js_and_meridian(self):
        candidates, preserved = self.pins()[2], self.pins()[4]
        html = self.html(candidates, preserved)
        payloads = {path: html for path in ('/', '/funds', '/research')}
        payloads.update({'/healthz': b'{"ok":true}', '/api/version': json.dumps({'v': preserved['app/static/app.js'][:10]}).encode()})
        payloads.update({'/' + path.removeprefix('app/'): raw for path, raw in {**self.assets, **self.preserved}.items()
                         if not path.endswith('index.html')})
        class Response:
            status = 200
            def __init__(self, raw): self.raw = raw
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return self.raw[:size]
        with patch.object(remote.urllib.request, 'urlopen', side_effect=lambda url, timeout:
                          Response(payloads[url.removeprefix('http://127.0.0.1:8090')])):
            self.real_origin(candidates, preserved)
            for path in ('/static/app.css', '/static/app.js', '/static/app.meridian.js', '/static/app.meridian.css', '/static/boot.js'):
                raw = payloads[path]
                payloads[path] = b'drift'
                self.assert_code('origin_asset_hash_mismatch', lambda: self.real_origin(candidates, preserved))
                payloads[path] = raw
            payloads['/api/version'] = json.dumps({'v': candidates['app/static/app.css'][:10]}).encode()
            self.assert_code('origin_version_mismatch', lambda: self.real_origin(candidates, preserved))
        for pin in (candidates['app/static/app.css'], preserved['app/static/app.js'],
                    preserved['app/static/app.meridian.js'], preserved['app/static/app.meridian.css']):
            self.assertFalse(remote.html_versions_match(html.replace(pin[:10].encode(), b'oldversion'), candidates, preserved))

    def test_original_safety_functions_and_explicit_mode_helpers_remain_byte_identical(self):
        here = Path(remote.__file__).resolve().parent
        old = (here.parent / 'meridian_workspace_operations_2026-10-21/remote.py').read_text()
        new = Path(remote.__file__).read_text()
        functions = lambda raw: {node.name: ast.get_source_segment(raw, node) for node in ast.parse(raw).body if isinstance(node, ast.FunctionDef)}
        before, after = functions(old), functions(new)
        for name in ('read_regular', 'safe_directory', 'layout', 'unit_state', 'exchange', 'exchange_available',
                     'clone_archive', 'run_schema', '_source_mode_metadata', '_source_mode_plan', 'audit_source_modes', 'repair_source_modes'):
            self.assertEqual(after[name], before[name], name)


if __name__ == '__main__':
    unittest.main()
