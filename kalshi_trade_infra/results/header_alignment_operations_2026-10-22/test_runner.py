"""Offline fixed-source, CSS parser, transfer and public acceptance checks."""
import base64
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import runner


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.assets = {'app/static/app.css': b'/* synthetic installed extras */\nbody:not([hidden]) { color: rgb(1, 2, 3); }\n@media (max-width: 600px) { body { margin: 0; } }\n'}
        self.before = {'app/static/app.css': 'a' * 64}
        self.after = {path: hashlib.sha256(raw).hexdigest() for path, raw in self.assets.items()}
        self.preserved_bytes = {path: ('synthetic preserved ' + path).encode() for path in runner.PRESERVED}
        self.preserved = {path: hashlib.sha256(raw).hexdigest() for path, raw in self.preserved_bytes.items()}
        self.value = {'reviewed_main': 'b' * 40, 'source_commit': 'c' * 40,
                      'frontend': {'app/static/app.css': {'published_path': runner.CANDIDATE_PATH,
                                   'before_sha256': self.before['app/static/app.css'], 'after_sha256': self.after['app/static/app.css']}},
                      'preserved_sha256': self.preserved}

    def manifest(self, value, mode='apply'):
        with patch.object(Path, 'read_text', return_value=json.dumps(value)):
            return runner.manifest(mode)

    def assert_code(self, code, function):
        with self.assertRaisesRegex(runner.RunnerError, '^' + code + '$'):
            function()

    def test_apply_requires_complete_exact_one_css_and_all_preservation_pins(self):
        self.assertEqual(self.manifest(self.value), self.value)
        for key in ('reviewed_main', 'source_commit'):
            value = copy.deepcopy(self.value)
            value[key] = None
            self.assert_code('RequiredManifestPinsMissing', lambda: self.manifest(value))
        value = copy.deepcopy(self.value)
        value['preserved_sha256']['app/static/app.meridian.css'] = None
        self.assert_code('RequiredManifestPinsMissing', lambda: self.manifest(value))
        value = copy.deepcopy(self.value)
        value['frontend']['app/static/app.meridian.css'] = value['frontend']['app/static/app.css']
        self.assert_code('RequiredManifestPinsMissing', lambda: self.manifest(value))
        value = copy.deepcopy(self.value)
        value['frontend']['app/static/app.css']['after_sha256'] = value['frontend']['app/static/app.css']['before_sha256']
        self.assert_code('DefaultCssMustChange', lambda: self.manifest(value))

    def test_only_fixed_installed_css_candidate_path_is_allowed(self):
        self.assertEqual(runner.CANDIDATE_PATH, 'kalshi_trade_infra/results/header_alignment_operations_2026-10-22/candidate.css')
        for path in ('kalshi_trade_infra/app/static/app.css', 'candidate.css', 'unreviewed.css'):
            value = copy.deepcopy(self.value)
            value['frontend']['app/static/app.css']['published_path'] = path
            self.assert_code('PublishedCandidatePathInvalid', lambda: self.manifest(value))

    def test_fetch_is_bound_to_exact_commit_path_and_css_hash(self):
        with patch.object(runner, 'github', return_value=self.assets['app/static/app.css']) as github:
            self.assertEqual(runner.published_candidates(self.value), self.assets)
        self.assertEqual(github.call_args.args[-1], 'repos/' + runner.REPO + '/contents/' + runner.CANDIDATE_PATH + '?ref=' + self.value['source_commit'])
        with patch.object(runner, 'github', return_value=b'unreviewed main CSS'):
            self.assert_code('PublishedCandidateHashMismatch', lambda: runner.published_candidates(self.value))
        with patch.object(runner, 'github', return_value=b'd' * 40):
            self.assert_code('ReviewedMainChanged', lambda: runner.verify_main(self.value))

    def test_real_css_parser_never_invokes_javascript_parser_and_rejects_invalid_utf8_or_css(self):
        with patch.object(runner.subprocess, 'run') as process:
            runner.validate_source_syntax(self.assets)
            self.assert_code('CandidateCssInvalid', lambda: runner.validate_source_syntax({'app/static/app.css': b'} invalid CSS'}))
            self.assert_code('CandidateSyntaxCheckUnavailable', lambda: runner.validate_source_syntax({'app/static/app.css': b'\xff'}))
        process.assert_not_called()

    def test_private_transfer_contains_only_css_and_uses_matching_authorized_encrypted_namespace(self):
        captured = {}
        def upload(*args):
            captured['args'] = args
            captured['raw'] = Path(args[args.index('--body') + 1]).read_bytes()
            return {}
        with patch.object(runner, 'aws', side_effect=upload):
            artifact = runner.stage_candidates(self.value, self.assets)
        self.assertRegex(artifact['key'], '^bundle/header-alignment-' + self.value['source_commit'] + '-[0-9a-f]{32}\\.json$')
        self.assertEqual(artifact['sha256'], hashlib.sha256(captured['raw']).hexdigest())
        self.assertEqual({path: base64.b64decode(raw) for path, raw in json.loads(captured['raw'])['assets'].items()}, self.assets)
        self.assertIn('AES256', captured['args'])
        self.assertIn('/bundle/*', (runner.HERE.parents[1] / 'scripts/DEPLOY_WORKFLOW_SETUP.md').read_text())

    def html(self):
        return ('<link href="/static/app.css?v=' + self.after['app/static/app.css'][:10] + '">'
                '<div data-tau-js="/static/app.js?v=' + self.preserved['app/static/app.js'][:10] + '" '
                'data-tau-ver="' + self.preserved['app/static/app.js'][:10] + '" '
                'data-mer-css="/static/app.meridian.css?v=' + self.preserved['app/static/app.meridian.css'][:10] + '" '
                'data-mer-js="/static/app.meridian.js?v=' + self.preserved['app/static/app.meridian.js'][:10] + '" '
                'data-mer-ver="' + self.preserved['app/static/app.meridian.js'][:10] + '"></div>'
                '<script src="/static/boot.js?v=' + self.preserved['app/static/boot.js'][:10] + '"></script>').encode()

    def public(self, overrides=None):
        payloads = {path: self.html() for path in ('/', '/funds', '/research')}
        payloads.update({'/healthz': b'{"ok":true}', '/api/version': json.dumps({'v': self.preserved['app/static/app.js'][:10]}).encode()})
        payloads.update({'/' + path.removeprefix('app/'): raw for path, raw in {**self.assets, **self.preserved_bytes}.items()
                         if not path.endswith('index.html')})
        payloads.update(overrides or {})
        class Response:
            status = 200
            def __init__(self, url):
                self.url = url
                self.raw = payloads[url.removeprefix(runner.DOMAIN).split('?', 1)[0]]
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size=None): return self.raw if size is None else self.raw[:size]
        with patch.object(runner.urllib.request, 'urlopen', side_effect=lambda request, timeout:
                          Response(request.full_url if hasattr(request, 'full_url') else request)):
            return runner.public_checks(self.after, self.preserved)

    def test_public_acceptance_requires_new_default_css_and_both_exact_unchanged_themes(self):
        result = self.public()
        self.assertTrue(result['accepted'])
        self.assertEqual(len(result['assets']), 5)
        for path in ('/static/app.css', '/static/app.js', '/static/app.meridian.js', '/static/app.meridian.css', '/static/boot.js'):
            self.assertFalse(self.public({path: b'drift'})['accepted'])
        self.assertFalse(self.public({'/api/version': json.dumps({'v': self.after['app/static/app.css'][:10]}).encode()})['accepted'])
        for path in ('/', '/funds', '/research'):
            stale = self.html().replace(self.after['app/static/app.css'][:10].encode(), b'oldversion')
            self.assertFalse(self.public({path: stale})['accepted'])

    def execute_program(self, source, mode='inventory'):
        program = runner.build_program(source, mode, self.before, self.after, 'e' * 64, {}, self.preserved)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(compile(program, '<single-css-operation>', 'exec'), {})
        return json.loads(output.getvalue())

    def test_program_modes_are_explicit_and_exception_messages_never_leave_receipt(self):
        self.assertEqual(self.execute_program('def inventory():return {"read_only":True}'), {'read_only': True})
        self.assertEqual(self.execute_program('def inventory():raise RuntimeError("PRIVATE ENV SECRET")'),
                         {'status': 'error', 'error_code': 'RuntimeError'})
        self.assertEqual(self.execute_program('def audit_source_modes():return {"status":"source_modes_audited"}', 'audit-source-modes')['status'], 'source_modes_audited')
        self.assertEqual(self.execute_program('def repair_source_modes():return {"status":"source_modes_repaired"}', 'repair-source-modes')['status'], 'source_modes_repaired')
        self.assert_code('InvalidMode', lambda: runner.build_program('', 'restart', {}, {}))

    def test_inventory_never_fetches_uploads_candidates_or_invalidates(self):
        with patch.object(runner.sys, 'argv', ['runner.py', 'inventory']), patch.object(runner, 'manifest', return_value=self.value), \
             patch.object(runner, 'verify_main'), patch.object(runner, 'remote', return_value={'status': 'ready'}), \
             patch.object(runner, 'published_candidates') as fetch, patch.object(runner, 'stage_candidates') as stage, \
             patch.object(runner, 'aws') as aws, contextlib.redirect_stdout(io.StringIO()):
            runner.run()
        fetch.assert_not_called()
        stage.assert_not_called()
        aws.assert_not_called()

    def test_aws_errors_expose_only_fixed_operation_and_bounded_code(self):
        response = subprocess.CompletedProcess([], 1, '', 'An error occurred (AccessDenied) when calling PutObject: PRIVATE ENV SECRET')
        with patch.object(runner.subprocess, 'run', return_value=response):
            with self.assertRaises(runner.RunnerError) as caught:
                runner.aws('s3api', 'put-object', '--bucket', 'synthetic')
        self.assertEqual(caught.exception.details, {'service': 's3api', 'operation': 'put-object', 'aws_code': 'AccessDenied'})
        self.assertNotIn('PRIVATE', json.dumps(caught.exception.details))

    def test_full_remote_program_fits_ssm_bound_and_does_not_embed_css_bytes(self):
        artifact = {'bucket': runner.BUCKET, 'key': 'bundle/header-alignment-' + 'c' * 40 + '-' + 'd' * 32 + '.json', 'sha256': 'f' * 64}
        program = runner.build_program((runner.HERE / 'remote.py').read_text(), 'apply', self.before, self.after, 'e' * 64, artifact, self.preserved)
        with patch.object(runner, 'aws', side_effect=[{'Command': {'CommandId': 'synthetic'}}, {'Status': 'Success', 'StandardOutputContent': '{"status":"deployed"}'}]) as aws, \
             patch.object(runner.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.remote(program), {'status': 'deployed'})
        command = json.loads(aws.call_args_list[0].args[-1])['commands'][0]
        self.assertLessEqual(len(command), 24000)
        self.assertNotIn('synthetic installed extras', command)


if __name__ == '__main__':
    unittest.main()
