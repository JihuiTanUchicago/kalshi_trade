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

import uuid

import urllib.error

import urllib.request

import zlib

HERE=Path(__file__).resolve().parent

REGION='us-east-1'

INSTANCE='i-077d6f7873e7836ba'

BUCKET='kalshi-trade-artifacts-568386354218-us-east-1'

STATE=Path(os.environ.get('TAU_PAPER_RELEASE_STATE','/tmp/tau-paper-release-state.json'))

def aws(*args):
    r=subprocess.run(['aws',*args,'--region',REGION,'--output','json'],capture_output=True,text=True,timeout=45)
    if r.returncode:
        match=re.search(r'An error occurred \(([A-Za-z0-9_.-]+)\)',r.stderr)
        raise RuntimeError('AwsRequestFailed_'+(match[1] if match else 'AwsCliError'))
    return json.loads(r.stdout) if r.stdout.strip() else {}

def remote(program,comment,timeout=180):
    packed=base64.b64encode(zlib.compress(program.encode())).decode()
    launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(packed)+')))'
    cmd='/opt/kalshi/.venv313/bin/python -B -c '+shlex.quote(launcher)
    if len(cmd)>16000:
        raw=program.encode();key='bundle/tau-paper-program-'+uuid.uuid4().hex+'.py'
        upload(raw,key)
        bootstrap=download_code(key,hashlib.sha256(raw).hexdigest(),'program')+'exec(program)\n'
        packed=base64.b64encode(zlib.compress(bootstrap.encode())).decode()
        launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(packed)+')))'
        cmd='/opt/kalshi/.venv313/bin/python -B -c '+shlex.quote(launcher)
    sent=aws('ssm','send-command','--instance-ids',INSTANCE,'--document-name','AWS-RunShellScript',
             '--comment',comment,'--parameters',json.dumps({'commands':[cmd],'executionTimeout':[str(timeout)]}))
    identifier=sent['Command']['CommandId']
    print('TAU_PAPER_PHASE='+json.dumps({'phase':comment,'ssm_command_id':identifier}),flush=True)
    r=None
    for _ in range(timeout//3+5):
        time.sleep(3)
        try:r=aws('ssm','get-command-invocation','--command-id',identifier,'--instance-id',INSTANCE)
        except RuntimeError as exc:
            if 'InvocationDoesNotExist' in str(exc):continue
            raise
        if r['Status'] in ('Success','Failed','TimedOut','Cancelled'):break
    if r is None:raise RuntimeError('SsmResultUnavailable')
    try:body=json.loads(r.get('StandardOutputContent','').strip())
    except (ValueError,TypeError):raise RuntimeError('SsmSanitizedJsonUnavailable') from None
    if not isinstance(body,dict):raise RuntimeError('SsmInvalidReceipt')
    if r['Status']!='Success':raise RuntimeError('SsmPhaseFailed_'+r['Status'])
    return body

def module_program(bundle_digest=None):
    manifest=json.loads((HERE/'manifest.json').read_text())
    values={'RELEASE_SHA':manifest['release_sha'],'BASELINE_MANIFEST':manifest['baseline'],
            'RELEASE_MANIFEST':manifest['release'],'EXPECTED_PROVIDER_SETTINGS':manifest['provider_settings'],
            'INVENTORY_SOURCE':(HERE/'activation_wait_inventory.py').read_text(),
            'PAPER_CONFIG_SOURCE':(HERE/'paper_runtime_config.py').read_text(),
            'PRESERVED_ON_HOST':manifest.get('preserved_on_host',{}),
            'ARCHIVE_ONLY_ON_HOST':manifest.get('archive_only_on_host',{}),
            'BUNDLE_SHA256':bundle_digest}
    program='ns='+repr(values)+'\nexec('+repr((HERE/'readiness_remote.py').read_text())+',ns)\n'
    return program

def upload(data,key):
    with tempfile.TemporaryDirectory(prefix='tau-paper-encrypted-') as temporary:
        path=Path(temporary)/'payload'
        path.write_bytes(data)
        r=subprocess.run(['aws','s3','cp',str(path),'s3://'+BUCKET+'/'+key,'--sse','AES256',
                          '--region',REGION,'--only-show-errors'],capture_output=True,timeout=90)
        if r.returncode:raise RuntimeError('EncryptedPayloadUploadFailed')

def download_code(key,digest,var):
    return (var+'=__import__("subprocess").check_output('+repr(['aws','s3','cp','s3://'+BUCKET+'/'+key,
            '-','--region',REGION,'--only-show-errors'])+')\n'
            +'assert __import__("hashlib").sha256('+var+').hexdigest()=='+repr(digest)+'\n')

if __name__=="__main__":
    try:
        result=remote(module_program()+'print(__import__("json").dumps(ns["main_inspect"]()))\n',"Tau current-main read-only source and runtime preflight")
        print("TAU_PAPER_INVENTORY="+json.dumps(result),flush=True)
        if result.get("status") not in ("waiting_for_idle","ready_for_quiet_window","already_installed"):raise RuntimeError("PreflightRequiresInspection")
    except Exception as exc:
        print("TAU_PAPER_ERROR="+json.dumps({"status":"preflight_requires_inspection","error_class":type(exc).__name__}),flush=True)
        raise SystemExit(1)
