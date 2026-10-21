"""One reviewed Meridian JS/CSS release; fixed, credential-free JSON markers."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zlib

import remote as release

HERE = Path(__file__).resolve().parent
REGION = 'us-east-1'
INSTANCE = 'i-077d6f7873e7836ba'
BUCKET = 'kalshi-trade-artifacts-568386354218-us-east-1'
DOMAIN = 'https://tau-trading.com'
REPO = 'JihuiTanUchicago/kalshi_trade'
ASSETS = release.ASSETS
PRESERVED = release.PRESERVED


class RunnerError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fail(code):
    raise RunnerError(code) from None


def emit(kind, value):
    print('TAU_MERIDIAN_' + kind + '=' + json.dumps(value), flush=True)


def aws(*args):
    response = subprocess.run(['aws', *args, '--region', REGION, '--output', 'json'],
                              capture_output=True, text=True, timeout=45)
    if response.returncode:
        error = RunnerError('AwsRequestFailed')
        match = re.search(r'An error occurred \(([A-Za-z0-9_.-]{1,80})\)', response.stderr or '')
        error.details = {'service': args[0], 'operation': args[1], 'aws_code': match[1] if match else 'Unavailable'}
        raise error from None
    return json.loads(response.stdout) if response.stdout.strip() else {}


def github(*args):
    response = subprocess.run(['gh', 'api', *args], capture_output=True, timeout=30)
    if response.returncode:
        fail('PublishedSourceUnavailable')
    return response.stdout


def manifest(mode):
    try:
        value = json.loads((HERE / 'manifest.json').read_text())
        if (not isinstance(value, dict) or set(value) != {'reviewed_main', 'source_commit', 'frontend', 'preserved_sha256'}
                or not re.fullmatch(r'[0-9a-f]{40}', value.get('reviewed_main') or '')
                or set(value['frontend']) != set(ASSETS) or set(value['preserved_sha256']) != set(PRESERVED)):
            fail('RequiredManifestPinsMissing')
        for path, row in value['frontend'].items():
            if (not isinstance(row, dict) or set(row) != {'published_path', 'before_sha256', 'after_sha256'}
                    or row['published_path'] != 'kalshi_trade_infra/' + path):
                fail('PublishedCandidatePathInvalid')
        if mode == 'apply':
            if (not re.fullmatch(r'[0-9a-f]{40}', value.get('source_commit') or '')
                    or any(not isinstance(pin, str) or not re.fullmatch(r'[0-9a-f]{64}', pin)
                           for pin in (*value['preserved_sha256'].values(),
                                       *(row[k] for row in value['frontend'].values()
                                         for k in ('before_sha256', 'after_sha256'))))):
                fail('RequiredManifestPinsMissing')
            if any(row['before_sha256'] == row['after_sha256'] for row in value['frontend'].values()):
                fail('BothMeridianAssetsMustChange')
        return value
    except RunnerError:
        raise
    except Exception:
        fail('ManifestInvalid')


def verify_main(value):
    actual = github(f'repos/{REPO}/git/ref/heads/main', '--jq', '.object.sha').decode().strip()
    if actual != value['reviewed_main']:
        fail('ReviewedMainChanged')


def validate_source_syntax(assets):
    # CSS is parsed as CSS; only the JavaScript bundle is sent to node --check.
    try:
        import tinycss2
        css = assets['app/static/app.meridian.css'].decode('utf-8')
        def walk(nodes):
            for node in nodes:
                if node.type == 'error':
                    fail('CandidateCssInvalid')
                for attr in ('prelude', 'arguments', 'value'):
                    child = getattr(node, attr, None)
                    if isinstance(child, (list, tuple)):
                        walk(child)
                content = getattr(node, 'content', None)
                if content is not None:
                    children = (tinycss2.parse_blocks_contents(content, skip_comments=True, skip_whitespace=True)
                                if node.type in ('qualified-rule', 'at-rule') else content)
                    walk(children)
        walk(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True))
        with tempfile.TemporaryDirectory(prefix='tau-meridian-syntax-') as directory:
            path = Path(directory) / 'app.meridian.js'
            path.write_bytes(assets['app/static/app.meridian.js'])
            response = subprocess.run(['node', '--check', str(path)], capture_output=True, timeout=30)
            if response.returncode:
                fail('CandidateJavaScriptInvalid')
    except RunnerError:
        raise
    except Exception:
        fail('CandidateSyntaxCheckUnavailable')


def published_candidates(value):
    assets = {}
    for path, row in value['frontend'].items():
        raw = github('-H', 'Accept: application/vnd.github.raw+json',
                     f"repos/{REPO}/contents/{row['published_path']}?ref={value['source_commit']}")
        if not raw or len(raw) > release.MAX_FILE or hashlib.sha256(raw).hexdigest() != row['after_sha256']:
            fail('PublishedCandidateHashMismatch')
        assets[path] = raw
    validate_source_syntax(assets)
    return assets


def stage_candidates(value, assets):
    raw = json.dumps({'assets': {p: base64.b64encode(assets[p]).decode() for p in ASSETS}},
                     sort_keys=True, separators=(',', ':')).encode()
    key = 'bundle/meridian-' + value['source_commit'] + '-' + uuid.uuid4().hex + '.json'
    with tempfile.TemporaryDirectory(prefix='tau-meridian-transfer-') as directory:
        path = Path(directory) / 'candidate-assets.json'
        path.write_bytes(raw)
        aws('s3api', 'put-object', '--bucket', BUCKET, '--key', key, '--body', str(path),
            '--server-side-encryption', 'AES256')
    return {'bucket': BUCKET, 'key': key, 'sha256': hashlib.sha256(raw).hexdigest()}


def remote(program, timeout=300):
    packed = base64.b64encode(zlib.compress(program.encode())).decode()
    launcher = 'import base64,zlib;exec(zlib.decompress(base64.b64decode(' + repr(packed) + ')))'
    command = '/opt/kalshi/.venv313/bin/python -B -c ' + shlex.quote(launcher)
    if len(command) > 24000:
        fail('ProgramTooLarge')
    result = aws('ssm', 'send-command', '--instance-ids', INSTANCE, '--document-name', 'AWS-RunShellScript',
                 '--comment', 'Tau reviewed no-restart Meridian frontend release',
                 '--parameters', json.dumps({'commands': [command], 'executionTimeout': [str(timeout)]}))
    identifier = result['Command']['CommandId']
    emit('PHASE', {'ssm_command_id': identifier})
    for _ in range(timeout // 3 + 8):
        time.sleep(3)
        try:
            result = aws('ssm', 'get-command-invocation', '--command-id', identifier, '--instance-id', INSTANCE)
        except RunnerError:
            continue
        if result['Status'] in ('Success', 'Failed', 'TimedOut', 'Cancelled'):
            break
    if result.get('Status') != 'Success':
        fail('RemotePhaseDidNotSucceed')
    try:
        output = json.loads(result.get('StandardOutputContent', '').strip())
    except ValueError:
        fail('SanitizedReceiptUnavailable')
    if not isinstance(output, dict):
        fail('InvalidReceipt')
    return output


def public_checks(candidates, preserved):
    result = {'pages': {}, 'assets': {}, 'version_matches': False, 'canonical_origin': DOMAIN, 'order_calls': 0}
    stamp = candidates['app/static/app.meridian.js'][:10]
    for path in ('/', '/funds', '/research', '/healthz'):
        request = urllib.request.Request(DOMAIN + path + '?meridian-release=' + stamp,
                                         headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(4194304)
            result['pages'][path] = {'status': response.status, 'canonical': response.url.startswith(DOMAIN + '/')}
            if path == '/healthz':
                result['pages'][path]['healthy'] = json.loads(raw).get('ok') is True
            else:
                result['pages'][path]['versions_match'] = release.html_versions_match(raw, candidates, preserved)
    assets = {**candidates, **{p: h for p, h in preserved.items() if not p.endswith('index.html')}}
    for path, expected in assets.items():
        request = urllib.request.Request(DOMAIN + '/' + path.removeprefix('app/') + '?v=' + expected[:10],
                                         headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(4194304)
            result['assets'][path] = {'status': response.status, 'sha256_matches': hashlib.sha256(raw).hexdigest() == expected}
    with urllib.request.urlopen(DOMAIN + '/api/version?meridian-release=' + stamp, timeout=20) as response:
        result['version_matches'] = json.load(response).get('v') == preserved['app/static/app.js'][:10]
    result['accepted'] = (all(p['status'] == 200 and p['canonical'] for p in result['pages'].values())
                          and all(p.get('versions_match') is True for path, p in result['pages'].items() if path != '/healthz')
                          and result['pages']['/healthz'].get('healthy') is True
                          and all(a['status'] == 200 and a['sha256_matches'] for a in result['assets'].values())
                          and result['version_matches'])
    return result


def build_program(source, mode, sources, candidates, pin=None, artifact=None, preserved=None):
    if mode == 'inventory':
        call = 'ns["inventory"]()'
    elif mode == 'repair-app-mode':
        call = 'ns["repair_app_mode"]()'
    elif mode == 'audit-source-modes':
        call = 'ns["audit_source_modes"]()'
    elif mode == 'apply':
        call = 'ns["apply"](' + ','.join(map(repr, (pin, sources, candidates, artifact, preserved))) + ')'
    else:
        fail('InvalidMode')
    return ('ns={};exec(' + repr(source) + ',ns)\ntry:\n    result=' + call + '\n'
            'except Exception as exc:\n    result={"status":"error","error_code":getattr(exc,"code",type(exc).__name__)}\n'
            '    if isinstance(exc,ns.get("RemovalError",())) and result["error_code"]=="unsafe_directory":\n'
            '        guard=ns.get("safe_directory");trace=exc.__traceback__\n'
            '        while guard is not None and trace is not None:\n'
            '            frame=trace.tb_frame\n'
            '            if frame.f_code is guard.__code__:\n'
            '                path=frame.f_locals.get("path");info=frame.f_locals.get("info")\n'
            '                if isinstance(path,ns.get("Path",())) and info is not None:\n'
            '                    result["directory"]={"path":str(path),"mode":format(ns["stat"].S_IMODE(info.st_mode),"04o"),"uid":int(info.st_uid),"gid":int(info.st_gid)}\n'
            '                break\n'
            '            trace=trace.tb_next\n'
            'print(__import__("json").dumps(result))\n')


def run():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'inventory'
    if mode not in ('inventory', 'audit-source-modes', 'repair-app-mode', 'apply', 'verify-main'):
        fail('InvalidMode')
    value = manifest(mode)
    verify_main(value)
    if mode == 'verify-main':
        emit('PREFLIGHT', {'reviewed_main_matches': True})
        return
    sources = {p: r['before_sha256'] for p, r in value['frontend'].items()}
    candidates = {p: r['after_sha256'] for p, r in value['frontend'].items()}
    preserved = value['preserved_sha256']
    fingerprint = os.environ.get('TAU_MERIDIAN_FINGERPRINT', '') if mode == 'apply' else None
    if mode == 'apply' and not re.fullmatch(r'[0-9a-f]{64}', fingerprint or ''):
        fail('InvalidFingerprint')
    artifact = stage_candidates(value, published_candidates(value)) if mode == 'apply' else None
    code = build_program((HERE / 'remote.py').read_text(), mode, sources, candidates, fingerprint, artifact, preserved)
    result = remote(code)
    emit('INVENTORY' if mode == 'inventory' else 'RESULTS', result)
    expected_status = {'inventory': 'ready', 'audit-source-modes': 'source_modes_audited',
                       'repair-app-mode': 'permissions_repaired', 'apply': 'deployed'}[mode]
    if result.get('status') != expected_status or result.get('error_code'):
        fail('RemoteInspectionRequired')
    if mode != 'apply':
        return
    invalidation = aws('cloudfront', 'create-invalidation', '--distribution-id', 'EEQ00Y93RTB1K', '--paths', '/*')
    emit('INVALIDATION', {'id': invalidation['Invalidation']['Id']})
    for attempt in range(5):
        try:
            checks = public_checks(candidates, preserved)
        except (urllib.error.URLError, TimeoutError, ValueError):
            checks = {'accepted': False, 'status': 'public_check_unavailable'}
        if checks.get('accepted'):
            break
        if attempt < 4:
            time.sleep(5)
    emit('PUBLIC', checks)
    if not checks.get('accepted'):
        fail('PublicVerificationIncomplete')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        report = {'status': 'operation_requires_inspection', 'error_class': type(exc).__name__,
                  'error_code': exc.code if isinstance(exc, RunnerError) else 'OperationFailed'}
        if isinstance(exc, RunnerError) and hasattr(exc, 'details'):
            report['aws'] = exc.details
        emit('ERROR', report)
        raise SystemExit(1)
