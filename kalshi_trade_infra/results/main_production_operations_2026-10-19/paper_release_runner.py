"""Fresh current-main rollout; preserve active research and protected runtime state."""
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
            'BUNDLE_SHA256':bundle_digest,
            'RESEARCH_INTERRUPTION_AUTHORIZED':manifest.get('research_interruption_authorized') is True,
            'UNIT_CAPTURE_MANIFEST':manifest.get('unit_capture',{}),
            'UNIT_GUARD_SOURCE':(HERE/'unit_guard.py').read_text()}
    program='ns='+repr(values)+'\nexec('+repr((HERE/'paper_release_remote.py').read_text())+',ns)\n'
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

def envelope_module():
    namespace={}
    exec((HERE/'oauth_envelope.py').read_text(),namespace)
    return namespace

def cleanup(session=None):
    if session is None:
        if not STATE.is_file():return {'status':'no_receiver_created'}
        session=json.loads(STATE.read_text())['session']
    code='e={};exec('+repr((HERE/'oauth_envelope.py').read_text())+',e)\n'
    code+='e["destroy_session"]('+repr(session)+')\nprint(__import__("json").dumps({"ephemeral_private_key_removed":True}))\n'
    result=remote(code,'Tau paper receiver cleanup',90)
    STATE.unlink(missing_ok=True)
    return result

def public_checks():
    manifest=json.loads((HERE/'manifest.json').read_text())
    result={'http':{},'page_final_urls':{},'canonical_origin':'https://tau-trading.com','asset_hashes_match':True,'authenticated_user_verified':False,'order_calls':0}
    base='https://d1gfpzcosqrjya.cloudfront.net'
    for path in ('/','/research','/healthz','/static/alpaca-paper.js','/static/alpaca-paper.css',
                 '/static/broker-connections.js','/static/app.js','/static/app.meridian.js'):
        url=base+path+'?release='+manifest['release_sha'][:12]
        with urllib.request.urlopen(urllib.request.Request(url,headers={'Cache-Control':'no-cache'}),timeout=30) as response:
            result['http'][path]=response.status
            if path in ('/','/research'):result['page_final_urls'][path]=response.geturl().split('?')[0]
            raw=response.read(4*1024*1024)
            if path.startswith('/static/'):
                result['asset_hashes_match'] &= hashlib.sha256(raw).hexdigest()==manifest['release']['app'+path]
    try:
        urllib.request.urlopen(base+'/api/brokers/alpaca/paper',timeout=20)
        result['unauthenticated_paper_api_status']=200
    except urllib.error.HTTPError as exc:result['unauthenticated_paper_api_status']=exc.code
    result['accepted']=(all(v==200 for v in result['http'].values()) and result['asset_hashes_match']
                        and all(v.startswith('https://tau-trading.com/') for v in result['page_final_urls'].values())
                        and result['unauthenticated_paper_api_status']==401)
    return result

def provider_acceptance(report):
    expected=json.loads((HERE/'manifest.json').read_text())['provider_settings']
    checks={row.get('name'):row for row in report.get('checks',[]) if isinstance(row,dict)}
    good={'actual_worker_environment':report.get('credentials_source')=='actual_worker_proc_environment',
          'offline_preflight':report.get('actual_worker_preflight',{}).get('ready') is True,
          'no_database_or_order_actions':report.get('database_or_order_actions') is False}
    good['approved_settings']=all(report.get('actual_worker_settings',{}).get(k)==v for k,v in expected.items())
    for name in ('alpaca_completed_history','massive_fx_history','databento_bars_EQUS.MINI','databento_bars_GLBX.MDP3'):
        row=checks.get(name,{})
        good[name]=row.get('status')=='available' and any(v>0 for v in row.get('bar_counts',{}).values())
    for name in ('massive_treasury_yields','massive_funding_conditions'):
        row=checks.get(name,{})
        good[name]=row.get('status')=='available' and row.get('observation_count',0)>0
    for name in ('current_agent_tool_bridge','historical_agent_tool_bridge'):
        row=checks.get(name,{})
        good[name]=(row.get('status')=='protocol_completed' and row.get('real_model_calls')==0
                    and row.get('secret_in_model_context') is False and row.get('scripted_model_calls',0)>=4)
    good['historical_current_data_guard']=checks.get('historical_agent_tool_bridge',{}).get('historical_current_data_blocked') is True
    events=report.get('events',[])
    for bridge,kind in (('current','search'),('current','publications'),('current','contents'),
                        ('historical','publications'),('historical','contents')):
        good['exa_'+bridge+'_'+kind]=any(e.get('provider')=='exa' and e.get('bridge')==bridge
              and e.get('kind')==kind and e.get('status')=='available' and e.get('source_count',0)>0 for e in events)
    good['unsupported_massive_capabilities_remain_disabled']=all(checks.get(name,{}).get('status')=='disabled_configuration'
               for name in ('massive_options_chain','massive_current_fx'))
    return {'accepted':all(good.values()),'gates':good,'authenticated_queued_model_run':False,
            'open_market_snapshot_freshness_verified':False}

def run(phase):
    if phase not in ('inspect','activate'):raise RuntimeError('InvalidOperationPhase')
    program=module_program()+'print(__import__("json").dumps(ns["main_inspect"]()))\n'
    inventory=remote(program,'Tau paper release read-only inventory')
    print('TAU_PAPER_INVENTORY='+json.dumps(inventory),flush=True)
    if phase=='inspect':return
    if inventory['status']=='waiting_for_idle':
        print('TAU_PAPER_RESULTS='+json.dumps({'status':'waiting_for_idle','jobs':inventory['jobs'],
          'source_installed':False,'restart_performed':False,'receiver_created':False,'order_calls':0}),flush=True)
        return
    if inventory['status'] not in ('ready_for_quiet_window','ready_for_approved_restart'):raise RuntimeError('InventoryRequiresInspection')
    # New operations checkout is based on current main; manifest verifies the whole runtime tree.
    r=subprocess.run(['git','archive','--format=tar.gz','HEAD:kalshi_trade_infra','app','data_pipeline'],
                     capture_output=True,check=True,timeout=30)
    bundle=r.stdout;digest=hashlib.sha256(bundle).hexdigest()
    bundle_key='bundle/tau-paper-'+uuid.uuid4().hex+'.tgz'
    upload(bundle,bundle_key)
    e=envelope_module()
    credentials={name:os.environ.get(name,'') for name in e['FIELDS']}
    e['_credentials'](credentials)
    prepare='e={};exec('+repr((HERE/'oauth_envelope.py').read_text())+',e)\n'
    prepare+='print(__import__("json").dumps(e["create_session"]()))\n'
    receiver=remote(prepare,'Tau paper encrypted OAuth receiver',120)
    session=receiver['session']
    if not re.fullmatch(r'tau-provider-probe-[0-9a-f]{32}',session):raise RuntimeError('InvalidReceiverSession')
    try:
        descriptor=os.open(STATE,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream:json.dump({'session':session},stream)
        encrypted=e['encrypt_credentials'](receiver['public_key_pem'],session,credentials)
        program=module_program(digest)
        program+='e={};exec('+repr((HERE/'oauth_envelope.py').read_text())+',e)\n'
        program+='result={}\ntry:\n'
        program+='    credentials=e["decrypt_credentials"]('+repr(session)+','+repr(encrypted)+')\n'
        code=download_code(bundle_key,digest,'bundle')
        program+=''.join('    '+line+'\n' for line in code.splitlines())
        program+='    result=ns["activate"](credentials,bundle)\n'
        program+='except Exception as exc:\n    result={"status":"activation_requires_inspection","error_code":getattr(exc,"code",type(exc).__name__)}\n'
        program+='finally:\n    e["destroy_session"]('+repr(session)+')\n'
        program+='result["ephemeral_private_key_removed"]=True\nprint(__import__("json").dumps(result))\n'
        raw=program.encode()
        if any(v and v.encode() in raw for v in credentials.values()):raise RuntimeError('PlaintextCredentialInTransport')
        key='bundle/tau-paper-encrypted-'+uuid.uuid4().hex+'.py'
        upload(raw,key)
        bootstrap=download_code(key,hashlib.sha256(raw).hexdigest(),'program')+'exec(program)\n'
        result=remote(bootstrap,'Tau guarded paper whole-app schema and idle cutover',600)
        print('TAU_PAPER_RESULTS='+json.dumps(result),flush=True)
        if result.get('status')!='deployed':
            if result.get('status')!='waiting_for_idle':raise RuntimeError('DeploymentRequiresInspection')
            return
        invalidation=aws('cloudfront','create-invalidation','--distribution-id','EEQ00Y93RTB1K','--paths','/*')
        print('TAU_PAPER_INVALIDATION='+json.dumps({'id':invalidation['Invalidation']['Id']}),flush=True)
        checks=None
        for attempt in range(8):
            try:checks=public_checks()
            except (urllib.error.URLError,TimeoutError):checks={'accepted':False,'status':'public_check_temporarily_unavailable'}
            if checks['accepted']:break
            if attempt<7:time.sleep(5)
        print('TAU_PAPER_PUBLIC='+json.dumps(checks),flush=True)
        if not checks['accepted']:raise RuntimeError('PublicReleaseVerificationFailed')
        # Existing user-approved provider activation is loaded by this same worker start.
        verification='v={};exec('+repr((HERE/'verify_active_providers.py').read_text())+',v)\n'
        expected=json.loads((HERE/'manifest.json').read_text())['provider_settings']
        verification+='expected='+repr(expected)+'\noriginal=v["actual_worker_environment"]\n'
        verification+='def pinned_environment():\n pid,env=original()\n if any(env.get(k)!=value for k,value in expected.items()):raise RuntimeError("ApprovedProviderSettingsChanged")\n return pid,env\n'
        verification+='v["actual_worker_environment"]=pinned_environment\n'
        verification+='import json\ntry:\n r=v["run_checks"]()\nexcept Exception as exc:\n r={"status":"verification_error","error_class":type(exc).__name__}\nprint(json.dumps(r,default=str))\n'
        verified=remote(verification,'Tau actual-worker provider verification after paper rollout',600)
        print('TAU_PAPER_PROVIDERS='+json.dumps(verified),flush=True)
        acceptance=provider_acceptance(verified)
        print('TAU_PAPER_PROVIDER_ACCEPTANCE='+json.dumps(acceptance),flush=True)
        if not acceptance['accepted']:raise RuntimeError('ActualWorkerProviderChecksIncomplete')
    finally:
        print('TAU_PAPER_CLEANUP='+json.dumps(cleanup(session)),flush=True)

if __name__=='__main__':
    try:
        if '--cleanup' in sys.argv:print('TAU_PAPER_CLEANUP='+json.dumps(cleanup()),flush=True)
        else:run(sys.argv[1] if len(sys.argv)>1 else 'inspect')
    except Exception as exc:
        print('TAU_PAPER_ERROR='+json.dumps({'status':'operation_requires_inspection','error_class':type(exc).__name__}),flush=True)
        sys.exit(1)
