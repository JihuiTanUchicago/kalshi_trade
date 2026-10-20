"""One guarded frontend-only release; credential-free receipts, no service controls."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib

HERE=Path(__file__).resolve().parent
REGION='us-east-1'
INSTANCE='i-077d6f7873e7836ba'
BUCKET='kalshi-trade-artifacts-568386354218-us-east-1'
DOMAIN='https://tau-trading.com'

def emit(kind,value):
    print('TAU_FUNDS_'+kind+'='+json.dumps(value),flush=True)

def aws(*args):
    p=subprocess.run(['aws',*args,'--region',REGION,'--output','json'],capture_output=True,text=True,timeout=45)
    if p.returncode:raise RuntimeError('AwsRequestFailed')
    return json.loads(p.stdout) if p.stdout.strip() else {}

def remote(program,timeout=240):
    packed=base64.b64encode(zlib.compress(program.encode())).decode()
    launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(packed)+')))'
    command='/opt/kalshi/.venv313/bin/python -B -c '+shlex.quote(launcher)
    if len(command)>24000:raise RuntimeError('ProgramTooLarge')
    r=aws('ssm','send-command','--instance-ids',INSTANCE,'--document-name','AWS-RunShellScript',
          '--comment','Tau reviewed no-restart Funds frontend release',
          '--parameters',json.dumps({'commands':[command],'executionTimeout':[str(timeout)]}))
    identifier=r['Command']['CommandId'];emit('PHASE',{'ssm_command_id':identifier})
    for _ in range(timeout//3+8):
        time.sleep(3)
        try:r=aws('ssm','get-command-invocation','--command-id',identifier,'--instance-id',INSTANCE)
        except RuntimeError:continue
        if r['Status'] in ('Success','Failed','TimedOut','Cancelled'):break
    if r.get('Status')!='Success':raise RuntimeError('RemotePhaseDidNotSucceed')
    try:out=json.loads(r.get('StandardOutputContent','').strip())
    except ValueError:raise RuntimeError('SanitizedReceiptUnavailable') from None
    if not isinstance(out,dict):raise RuntimeError('InvalidReceipt')
    return out

def public_checks(candidates):
    result={'pages':{},'assets':{},'version_matches':False,'canonical_origin':DOMAIN,'order_calls':0}
    stamp=candidates['app/static/app.js'][:10]
    for path in ('/','/funds','/research','/healthz'):
        req=urllib.request.Request(DOMAIN+path+'?funds-release='+stamp,headers={'Cache-Control':'no-cache'})
        with urllib.request.urlopen(req,timeout=20) as r:
            raw=r.read(4194304)
            result['pages'][path]={'status':r.status,'canonical':r.url.startswith(DOMAIN+'/')}
            if path=='/healthz':result['pages'][path]['healthy']=json.loads(raw).get('ok') is True
            if path=='/funds':
                text=raw.decode()
                result['page_version_matches']=all('/static/'+name+'?v='+candidates['app/static/'+name][:10] in text for name in ('app.js','app.meridian.js'))
    for path,digest in candidates.items():
        req=urllib.request.Request(DOMAIN+'/'+path.removeprefix('app/')+'?v='+digest[:10],headers={'Cache-Control':'no-cache'})
        with urllib.request.urlopen(req,timeout=20) as r:
            raw=r.read(4194304)
            result['assets'][path]={'status':r.status,'sha256_matches':hashlib.sha256(raw).hexdigest()==digest,
               'broker_host_absent':b'id="broker-connections"' not in raw,'broker_mount_absent':b'TauBrokerConnections.mount' not in raw}
    with urllib.request.urlopen(DOMAIN+'/api/version?funds-release='+stamp,timeout=20) as r:
        result['version_matches']=json.load(r).get('v')==stamp
    result['accepted']=(all(p['status']==200 and p['canonical'] for p in result['pages'].values())
      and result['pages']['/healthz'].get('healthy') is True and result.get('page_version_matches') is True
      and all(a['status']==200 and a['sha256_matches'] and a['broker_host_absent'] and a['broker_mount_absent'] for a in result['assets'].values())
      and result['version_matches'])
    return result

def build_program(source, mode, sources, candidates, pin=None):
    if mode=='inventory':call='ns["inventory"]()'
    elif mode=='apply':call='ns["apply"]('+repr(pin)+','+repr(sources)+','+repr(candidates)+')'
    else:raise RuntimeError('InvalidMode')
    return ('ns={};exec('+repr(source)+',ns)\ntry:\n    result='+call+'\n'
            'except Exception as exc:\n    result={"status":"error","error_code":getattr(exc,"code",type(exc).__name__)}\n'
            'print(__import__("json").dumps(result))\n')

def run():
    mode=sys.argv[1] if len(sys.argv)>1 else 'inventory'
    if mode not in ('inventory','apply'):raise RuntimeError('InvalidMode')
    m=json.loads((HERE/'manifest.json').read_text())
    sources={p:r['before_sha256'] for p,r in m['frontend'].items()}
    candidates={p:r['after_sha256'] for p,r in m['frontend'].items()}
    fingerprint=os.environ.get('TAU_FUNDS_FINGERPRINT','') if mode=='apply' else None
    if mode=='apply' and not re.fullmatch('[0-9a-f]{64}',fingerprint or ''):raise RuntimeError('InvalidFingerprint')
    code=build_program((HERE/'remote.py').read_text(),mode,sources,candidates,fingerprint)
    result=remote(code)
    emit('INVENTORY' if mode=='inventory' else 'RESULTS',result)
    if result.get('status') in ('failed','error','requires_inspection','deployment_requires_inspection') or result.get('error_code'):
        raise RuntimeError('RemoteInspectionRequired')
    if mode=='inventory':return
    if result.get('status') not in ('deployed','applied'):raise RuntimeError('DeploymentNotConfirmed')
    inv=aws('cloudfront','create-invalidation','--distribution-id','EEQ00Y93RTB1K','--paths','/*')
    emit('INVALIDATION',{'id':inv['Invalidation']['Id']})
    for attempt in range(5):
        try:checks=public_checks(candidates)
        except (urllib.error.URLError,TimeoutError,ValueError):checks={'accepted':False,'status':'public_check_unavailable'}
        if checks.get('accepted'):break
        if attempt<4:time.sleep(5)
    emit('PUBLIC',checks)
    if not checks.get('accepted'):raise RuntimeError('PublicVerificationIncomplete')

if __name__=='__main__':
    try:run()
    except Exception as exc:
        emit('ERROR',{'status':'operation_requires_inspection','error_class':type(exc).__name__})
        raise SystemExit(1)
