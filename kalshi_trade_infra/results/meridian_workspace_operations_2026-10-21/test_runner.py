"""Offline wrapper, immutable-source, syntax, transfer and public acceptance cases."""
import base64
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import runner


class ProgramTest(unittest.TestCase):
    def execute(self, source, mode='inventory', before=None, after=None, pin=None, artifact=None, preserved=None):
        program = runner.build_program(source, mode, before or {}, after or {}, pin, artifact, preserved)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(compile(program, '<guarded-remote>', 'exec'), {})
        return json.loads(output.getvalue())

    def test_inventory_uses_read_only_api(self):
        self.assertEqual(self.execute('def inventory():return {"status":"ready","read_only":True}'),
                         {'status': 'ready', 'read_only': True})

    def test_apply_passes_exact_pins_without_interpolation(self):
        out = self.execute('def apply(pin,before,after,artifact,preserved):return {"pin":pin,"before":before,"after":after,"artifact":artifact,"preserved":preserved}',
                           'apply', {'app/static/app.meridian.js': 'a' * 64}, {'app/static/app.meridian.js': 'b' * 64},
                           'c' * 64, {'bucket': 'synthetic'}, {'app/static/app.js': 'd' * 64})
        self.assertEqual(out['pin'], 'c' * 64)
        self.assertEqual(out['before']['app/static/app.meridian.js'], 'a' * 64)
        self.assertEqual(out['after']['app/static/app.meridian.js'], 'b' * 64)
        self.assertEqual(out['preserved']['app/static/app.js'], 'd' * 64)

    def test_error_body_is_never_emitted(self):
        self.assertEqual(self.execute('def inventory():raise RuntimeError("private environment secret must not print")'),
                         {'status': 'error', 'error_code': 'RuntimeError'})

    def test_fixed_guard_code_survives(self):
        self.assertEqual(self.execute('class GuardError(Exception):code="source_changed"\ndef inventory():raise GuardError("private")'),
                         {'status': 'error', 'error_code': 'source_changed'})

    def test_code_containing_result_text_does_not_break_wrapper(self):
        self.assertEqual(self.execute('literal="result=never split code"\ndef inventory():return {"text":literal}')['text'],
                         'result=never split code')

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(runner.RunnerError):
            runner.build_program('', 'restart', {}, {})


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.assets = {'app/static/app.meridian.js': b'const syntheticMeridian = true;\n',
                       'app/static/app.meridian.css': b'/* synthetic */\nbody:not([hidden]) { color: rgb(0, 100, 0); }\n@media (max-width: 600px) { body { margin: 0; } }\n'}
        self.before = {p: hashlib.sha256(('synthetic old ' + p).encode()).hexdigest() for p in runner.ASSETS}
        self.after = {p: hashlib.sha256(raw).hexdigest() for p, raw in self.assets.items()}
        self.default_bytes = {p: ('synthetic preserved ' + p).encode() for p in runner.PRESERVED}
        self.preserved = {p: hashlib.sha256(raw).hexdigest() for p, raw in self.default_bytes.items()}
        self.value = {'reviewed_main': 'a' * 40, 'source_commit': 'b' * 40,
                      'frontend': {p: {'published_path': 'kalshi_trade_infra/' + p,
                                       'before_sha256': self.before[p], 'after_sha256': self.after[p]}
                                   for p in runner.ASSETS}, 'preserved_sha256': self.preserved}

    def read_manifest(self, value, mode='apply'):
        with patch.object(Path, 'read_text', return_value=json.dumps(value)):
            return runner.manifest(mode)

    def assert_code(self, code, fn):
        with self.assertRaises(runner.RunnerError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)

    def test_unfilled_or_moving_source_pins_cannot_apply(self):
        self.assertEqual(self.read_manifest(self.value), self.value)
        for key, wrong in (('source_commit', None), ('source_commit', 'main'), ('reviewed_main', None)):
            value = copy.deepcopy(self.value)
            value[key] = wrong
            self.assert_code('RequiredManifestPinsMissing', lambda: self.read_manifest(value))
        value = copy.deepcopy(self.value)
        value['frontend'][runner.ASSETS[1]]['after_sha256'] = None
        self.assert_code('RequiredManifestPinsMissing', lambda: self.read_manifest(value))

    def test_default_or_unpublished_candidate_paths_are_rejected(self):
        value = copy.deepcopy(self.value)
        value['frontend'][runner.ASSETS[1]]['published_path'] = 'unpublished/local/candidate.css'
        self.assert_code('PublishedCandidatePathInvalid', lambda: self.read_manifest(value))
        value = copy.deepcopy(self.value)
        value['frontend']['app/static/app.js'] = value['frontend'].pop(runner.ASSETS[0])
        self.assert_code('RequiredManifestPinsMissing', lambda: self.read_manifest(value))

    def test_reviewed_main_drift_blocks(self):
        with patch.object(runner, 'github', return_value=b'c' * 40 + b'\n'):
            self.assert_code('ReviewedMainChanged', lambda: runner.verify_main(self.value))

    def test_fetch_uses_only_fixed_published_paths_exact_commit_and_hashes(self):
        def github(*args):
            endpoint = args[-1]
            path = endpoint.split('/contents/', 1)[1].split('?ref=', 1)[0]
            self.assertTrue(endpoint.endswith('?ref=' + self.value['source_commit']))
            return self.assets[path.removeprefix('kalshi_trade_infra/')]
        with patch.object(runner, 'github', side_effect=github), patch.object(runner, 'validate_source_syntax') as syntax:
            self.assertEqual(runner.published_candidates(self.value), self.assets)
            syntax.assert_called_once_with(self.assets)
        with patch.object(runner, 'github', return_value=b'unreviewed source'):
            self.assert_code('PublishedCandidateHashMismatch', lambda: runner.published_candidates(self.value))

    def test_actual_css_parser_and_js_parser_accept_correct_languages(self):
        runner.validate_source_syntax(self.assets)

    def test_css_error_is_detected_before_any_js_syntax_check(self):
        assets = {**self.assets, runner.ASSETS[1]: b'} invalid CSS'}
        with patch.object(runner.subprocess, 'run') as node:
            self.assert_code('CandidateCssInvalid', lambda: runner.validate_source_syntax(assets))
        node.assert_not_called()

    def test_actual_js_parser_rejects_invalid_javascript(self):
        assets = {**self.assets, runner.ASSETS[0]: b'const = ;'}
        self.assert_code('CandidateJavaScriptInvalid', lambda: runner.validate_source_syntax(assets))

    def test_artifact_namespace_matches_existing_least_privilege_deployment_policy(self):
        policy = (runner.HERE.parents[1] / 'scripts/DEPLOY_WORKFLOW_SETUP.md').read_text()
        self.assertIn('/bundle/*', policy)
        with patch.object(runner, 'aws', return_value={}):
            artifact = runner.stage_candidates(self.value, self.assets)
        self.assertTrue(artifact['key'].startswith('bundle/'))
        self.assertFalse(artifact['key'].startswith('frontend/'))

    def test_aws_failure_reports_only_operation_and_safe_error_code(self):
        for stderr, expected in [('An error occurred (AccessDenied) when calling the PutObject operation: PRIVATE_SECRET', 'AccessDenied'),
                                 ('endpoint unavailable PRIVATE_SECRET', 'Unavailable')]:
            child = type('Child', (), {'returncode': 1, 'stdout': '', 'stderr': stderr})()
            with patch.object(runner.subprocess, 'run', return_value=child):
                with self.assertRaises(runner.RunnerError) as caught:
                    runner.aws('s3api', 'put-object', '--bucket', 'synthetic')
            self.assertEqual(caught.exception.code, 'AwsRequestFailed')
            self.assertEqual(caught.exception.details, {'service': 's3api', 'operation': 'put-object', 'aws_code': expected})
            self.assertNotIn('PRIVATE_SECRET', json.dumps(caught.exception.details))

    def test_private_transfer_contains_exact_js_css_only_and_content_hash(self):
        captured = {}
        def upload(*args):
            captured['args'] = args
            captured['raw'] = Path(args[args.index('--body') + 1]).read_bytes()
            return {}
        with patch.object(runner, 'aws', side_effect=upload):
            descriptor = runner.stage_candidates(self.value, self.assets)
        self.assertEqual(descriptor['bucket'], runner.BUCKET)
        self.assertRegex(descriptor['key'], r'^bundle/meridian-' + self.value['source_commit'] + r'-[0-9a-f]{32}\.json$')
        self.assertEqual(hashlib.sha256(captured['raw']).hexdigest(), descriptor['sha256'])
        payload = json.loads(captured['raw'])
        self.assertEqual(set(payload['assets']), set(runner.ASSETS))
        self.assertEqual({p: base64.b64decode(v) for p, v in payload['assets'].items()}, self.assets)
        self.assertIn('--server-side-encryption', captured['args'])
        self.assertIn('AES256', captured['args'])

    def html(self):
        return ('<link href="/static/app.css?v=' + self.preserved['app/static/app.css'][:10] + '">'
                '<div data-tau-js="/static/app.js?v=' + self.preserved['app/static/app.js'][:10] + '" '
                'data-tau-ver="' + self.preserved['app/static/app.js'][:10] + '" '
                'data-mer-css="/static/app.meridian.css?v=' + self.after['app/static/app.meridian.css'][:10] + '" '
                'data-mer-js="/static/app.meridian.js?v=' + self.after['app/static/app.meridian.js'][:10] + '" '
                'data-mer-ver="' + self.after['app/static/app.meridian.js'][:10] + '"></div>'
                '<script src="/static/boot.js?v=' + self.preserved['app/static/boot.js'][:10] + '"></script>').encode()

    def public(self, overrides=None):
        payloads = {p: self.html() for p in ('/', '/funds', '/research')}
        payloads.update({'/healthz': b'{"ok":true}', '/api/version': json.dumps({'v': self.preserved['app/static/app.js'][:10]}).encode()})
        payloads.update({'/' + p.removeprefix('app/'): raw for p, raw in {**self.assets, **self.default_bytes}.items() if not p.endswith('index.html')})
        payloads.update(overrides or {})
        class Response:
            status = 200
            def __init__(self, url):
                self.url = url
                self.raw = payloads[url.removeprefix(runner.DOMAIN).split('?', 1)[0]]
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size=None): return self.raw if size is None else self.raw[:size]
        with patch.object(runner.urllib.request, 'urlopen', side_effect=lambda request, timeout: Response(request.full_url if hasattr(request, 'full_url') else request)):
            return runner.public_checks(self.after, self.preserved)

    def test_public_acceptance_verifies_css_defaults_and_separate_builds(self):
        result = self.public()
        self.assertTrue(result['accepted'])
        self.assertEqual(len(result['assets']), 5)
        self.assertTrue(result['assets']['app/static/app.meridian.css']['sha256_matches'])
        self.assertTrue(result['assets']['app/static/app.css']['sha256_matches'])

    def test_public_acceptance_rejects_stale_css_and_any_default_drift(self):
        for path in ('/static/app.meridian.css', '/static/app.js', '/static/app.css', '/static/boot.js'):
            with self.subTest(path=path):
                self.assertFalse(self.public({path: b'drift'})['accepted'])

    def test_public_acceptance_requires_unchanged_default_api_version(self):
        self.assertFalse(self.public({'/api/version': json.dumps({'v': self.after[runner.ASSETS[0]][:10]}).encode()})['accepted'])

    def test_public_acceptance_requires_both_meridian_html_versions(self):
        for path in ('/', '/funds', '/research'):
            with self.subTest(path=path):
                stale = self.html().replace(self.after[runner.ASSETS[1]][:10].encode(), b'oldversion')
                self.assertFalse(self.public({path: stale})['accepted'])

    def test_real_remote_program_fits_ssm_bound_and_contains_no_candidate_bytes(self):
        source = (runner.HERE / 'remote.py').read_text()
        artifact = {'bucket': runner.BUCKET, 'key': 'bundle/meridian-' + 'b' * 40 + '-' + 'c' * 32 + '.json', 'sha256': 'd' * 64}
        program = runner.build_program(source, 'apply', self.before, self.after, 'e' * 64, artifact, self.preserved)
        with patch.object(runner, 'aws', side_effect=[{'Command': {'CommandId': 'synthetic'}}, {'Status': 'Success', 'StandardOutputContent': '{"status":"deployed"}'}]) as aws, patch.object(runner.time, 'sleep'):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.remote(program), {'status': 'deployed'})
        command = json.loads(aws.call_args_list[0].args[-1])['commands'][0]
        self.assertLessEqual(len(command), 24000)
        self.assertNotIn('syntheticMeridian', command)


if __name__ == '__main__':
    unittest.main()
