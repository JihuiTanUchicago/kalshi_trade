"""Pinned, aggregate-only production paper rollout. No provider order requests."""
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path('/opt/kalshi')
PYTHON = '/opt/kalshi/.venv313/bin/python'
TARGETS = ('recursive-web', 'recursive-agents')
OTHERS = ('recursive-engine', 'recursive-history', 'kalshi-live-engine')
RESOURCES = ('Restart','RestartUSec','TimeoutStartUSec','TimeoutStopUSec','MemoryHigh',
             'MemoryMax','MemorySwapMax','Nice','KillMode','KillSignal')
PROVIDER_FILES = ('/etc/tau/provider-data/market-data.env','/etc/tau/provider-data/research-data.env')

class ReleaseError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def command(args, *, env=None, cwd=None, timeout=45, stdin=None):
    response = subprocess.run(args,env=env,cwd=cwd,capture_output=True,timeout=timeout,input=stdin)
    if response.returncode:
        raise ReleaseError('subprocess_failed')
    return response.stdout

def props(service):
    raw = command(['systemctl','show',service,'--property=MainPID,ActiveState,FragmentPath,DropInPaths,'+','.join(RESOURCES)])
    return dict(line.split('=',1) for line in raw.decode().splitlines() if '=' in line)

def process(service):
    values = props(service)
    pid = int(values.get('MainPID','0'))
    if pid <= 0 or values.get('ActiveState') != 'active':
        raise ReleaseError('required_service_not_active')
    path = Path('/proc')/str(pid)
    args = [v.decode() for v in (path/'cmdline').read_bytes().split(b'\0') if v]
    wanted = ['-m','app.server'] if service=='recursive-web' else ['-m','app.worker','agents']
    if ((path/'cwd').resolve()!=ROOT or not args or args[0]!=PYTHON
            or not any(args[i:i+len(wanted)]==wanted for i in range(len(args)))):
        raise ReleaseError('unexpected_process_layout')
    env = dict(v.decode().split('=',1) for v in (path/'environ').read_bytes().split(b'\0') if b'=' in v)
    return values,pid,env

def file_hash(path):
    if path.is_symlink() or not path.is_file():
        raise ReleaseError('source_file_missing_or_symlink')
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_check(manifest, root=ROOT):
    actual=set()
    for package in ('app','data_pipeline'):
        for path in (root/package).rglob('*'):
            if '__pycache__' in path.parts or path.suffix=='.pyc':continue
            if path.is_symlink():raise ReleaseError('source_tree_contains_symlink')
            if path.is_file():actual.add(str(path.relative_to(root)))
    return actual==set(manifest) and all(file_hash(root/name)==digest for name,digest in manifest.items())

def source_diagnostics(manifest, root=ROOT):
    actual=set()
    for package in ('app','data_pipeline'):
        for path in (root/package).rglob('*'):
            if '__pycache__' in path.parts or path.suffix=='.pyc':continue
            if path.is_file() or path.is_symlink():actual.add(str(path.relative_to(root)))
    missing=sorted(set(manifest)-actual)
    mismatched=[name for name in sorted(set(manifest)&actual)
                if (root/name).is_symlink() or file_hash(root/name)!=manifest[name]]
    extra=sorted(actual-set(manifest))
    public_suffixes={'.py','.md','.js','.css','.html','.svg','.png','.ico','.woff','.woff2','.map'}
    safe_extra=[name for name in extra if Path(name).suffix in public_suffixes
                and re.fullmatch(r'[A-Za-z0-9_./-]{1,200}',name)]
    artifacts={};retained={}
    known_research={'data_pipeline/research_expiry_resolution.py',
                    'data_pipeline/research_expiry_resolution_sensitivity.py','data_pipeline/research_fee_sensitivity.py'}
    for name in extra:
        path=root/name
        if path.is_symlink():continue
        if path.name.startswith('._') or path.name=='.DS_Store':
            with path.open('rb') as stream:header=stream.read(8)
            if path.name.startswith('._') and header==b'\x00\x05\x16\x07\x00\x02\x00\x00':artifacts[name]='verified_appledouble'
            elif path.name=='.DS_Store' and header==b'\x00\x00\x00\x01Bud1':artifacts[name]='verified_ds_store'
        elif name in known_research:retained[name]=file_hash(path)
    return {'missing_known_source':missing,'changed_known_source':mismatched,'extra_file_count':len(extra),
            'extra_source_paths':safe_extra,'withheld_extra_path_count':len(extra)-len(safe_extra),
            'verified_metadata_artifacts':artifacts,'research_utility_sha256':retained,
            'unclassified_extra_count':len(set(extra)-set(artifacts)-set(retained))}

def config_module():
    namespace = {'__name__':'paper_runtime_config'}
    exec(PAPER_CONFIG_SOURCE,namespace)
    return namespace

def unit_plan(service, helper):
    current = props(service)
    fragment = Path(current.get('FragmentPath',''))
    if not re.fullmatch(r'/(?:etc|usr/lib|lib|run)/systemd/system/'+re.escape(service)+r'\.service',str(fragment)):
        raise ReleaseError('unrecognized_unit_path')
    def read(path):
        info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022
                or info.st_size>262144):
            raise ReleaseError('unsafe_service_unit')
        return path.read_bytes()
    saved = {fragment:read(fragment)}
    dropins={}
    for parent in ('/etc/systemd/system','/run/systemd/system','/usr/lib/systemd/system','/lib/systemd/system'):
        directory=Path(parent)/(service+'.service.d')
        if not directory.exists():
            continue
        info=directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            raise ReleaseError('unsafe_service_dropin_directory')
        for path in directory.glob('*.conf'):
            raw=read(path)
            saved[path]=raw
            dropins[str(path)]=raw
    loaded=shlex.split(current.get('DropInPaths',''))
    if any(path not in dropins for path in loaded):raise ReleaseError('loaded_dropin_inventory_incomplete')
    known={'90-tau-provider-data.conf','99-tau-alpaca-paper.conf'}
    if any(Path(path).name not in known for path in dropins):raise ReleaseError('unreviewed_service_dropin')
    plan=helper['plan_unit'](service,saved[fragment],dropins,PYTHON)
    return plan,saved,current

def jobs(env):
    module={}
    exec(INVENTORY_SOURCE,module)
    previous, old_path = dict(os.environ),list(sys.path)
    connection=None
    old_logging=logging.root.manager.disable
    try:
        os.environ.clear();os.environ.update(env)
        sys.path.insert(0,str(ROOT))
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from data_pipeline.common import get_db_conn
            connection=get_db_conn()
            report=module['InventoryRepository'].job_summary(connection)
        if (report.get('status')!='available' or report.get('transaction')!='read_only'
                or any(type(report.get(k)) is not int or report[k]<0 for k in ('running','queued','paused'))):
            raise ReleaseError('job_inventory_unavailable')
        return {k:report[k] for k in ('status','transaction','running','queued','paused','seconds_since_latest_finished')}
    finally:
        if connection is not None:connection.close()
        os.environ.clear();os.environ.update(previous);sys.path[:]=old_path
        logging.disable(old_logging)

def idle(report):
    return all(report[key]==0 for key in ('running','queued','paused'))

def safe_literal(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>65536:
        raise ReleaseError('unsafe_private_overlay')
    result={}
    raw=path.read_text()
    if any(char in raw for char in ('$','`','\x00','\r')):raise ReleaseError('nonliteral_private_overlay')
    for line in raw.splitlines():
        if not line.strip() or line.startswith('#'):continue
        words=shlex.split(line)
        if words and words[0]=='export':words=words[1:]
        if len(words)!=1 or '=' not in words[0]:raise ReleaseError('nonliteral_private_overlay')
        key,value=words[0].split('=',1)
        if (not re.fullmatch(r'[A-Z][A-Z0-9_]*',key) or key in result
                or not re.fullmatch(r'[A-Za-z0-9._~+/=:,-]{1,4096}',value)):
            raise ReleaseError('invalid_private_overlay')
        result[key]=value
    return result

def provider_configuration():
    merged={}
    for name in PROVIDER_FILES:
        merged.update(safe_literal(Path(name)))
    allowed=set(EXPECTED_PROVIDER_SETTINGS)|{'APCA_API_KEY_ID','APCA_API_SECRET_KEY','MASSIVE_API_KEY','DATABENTO_API_KEY','EXA_API_KEY'}
    if set(merged)!=allowed or any(merged[k]!=v for k,v in EXPECTED_PROVIDER_SETTINGS.items()):
        raise ReleaseError('staged_provider_configuration_conflict')
    if any(not merged[k] for k in allowed-set(EXPECTED_PROVIDER_SETTINGS)):
        raise ReleaseError('staged_provider_credential_missing')
    return merged

def offline(root, env, *, paper=False):
    code = ('import json;from app.market_data_config import check_configuration;from app.exa_data import Config;'
            'a=check_configuration();b=Config.from_env();print(json.dumps({"market_ready":a["ready"],"exa_ready":__import__("os").getenv("TAU_EXA_ENABLED")=="1" and bool(b.api_key) and b.historical_enabled}))')
    actual=dict(env);actual['PYTHONDONTWRITEBYTECODE']='1';actual.pop('AWS_PROFILE',None)
    if paper:
        raw=command([PYTHON,'-B','-m','app.alpaca_paper','status'],env=actual,cwd=root)
        result=json.loads(raw)
        if result.get('ready_for_user_connection') is not True or result.get('live_equity_execution') is not False:
            raise ReleaseError('paper_offline_preflight_failed')
        return result
    result=json.loads(command([PYTHON,'-B','-c',code],env=actual,cwd=root))
    if result!={'market_ready':True,'exa_ready':True}:raise ReleaseError('provider_offline_preflight_failed')
    return result

def inspect():
    result={'mode':'paper_release_inventory','read_only':True,'provider_calls':0,'order_calls':0,
            'checked_at_utc':datetime.now(timezone.utc).isoformat(),'release_sha':RELEASE_SHA}
    helper=config_module()
    _,_,agent_env=process('recursive-agents')
    result['jobs']=jobs(agent_env)
    result['baseline_matches']=source_check(BASELINE_MANIFEST)
    result['release_matches']=source_check(RELEASE_MANIFEST) if (ROOT/'app/alpaca_paper.py').exists() else False
    result['runtimes']={}
    for service in TARGETS:
        values,pid,env=process(service)
        plan,_,_=unit_plan(service,helper)
        result['runtimes'][service]={'active':True,'main_pid':pid,
          'oauth_client_id_present':bool(env.get('ALPACA_OAUTH_CLIENT_ID')),
          'oauth_client_secret_present':bool(env.get('ALPACA_OAUTH_CLIENT_SECRET')),
          'app_secret_present':bool(env.get('APP_SECRET_KEY')),
          'paper_enabled':env.get('TAU_ALPACA_PAPER_ENABLED')=='1',
          'unit_plan_valid':bool(plan),'resources':{k:values[k] for k in RESOURCES}}
    provider_configuration()
    result['provider_staged_configuration_valid']=True
    result['status']='already_installed' if result['release_matches'] else ('ready_for_quiet_window' if idle(result['jobs']) else 'waiting_for_idle')
    if not result['baseline_matches'] and not result['release_matches']:
        result.update(status='inspection_failed',error_code='production_source_conflict',
                      source_diagnostics=source_diagnostics(BASELINE_MANIFEST))
    return result

def extract_bundle(bundle, directory):
    if hashlib.sha256(bundle).hexdigest()!=BUNDLE_SHA256:raise ReleaseError('release_bundle_integrity_failed')
    with tarfile.open(fileobj=io.BytesIO(bundle),mode='r:gz') as archive:
        members=archive.getmembers()
        if len(members)>4096:raise ReleaseError('release_bundle_too_large')
        for member in members:
            path=Path(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in ('app','data_pipeline'):
                raise ReleaseError('unsafe_archive_path')
            if not (member.isfile() or member.isdir()) or member.size>32*1024*1024:
                raise ReleaseError('unsafe_archive_member')
        archive.extractall(directory,filter='data')
    if not source_check(RELEASE_MANIFEST,directory):raise ReleaseError('staged_release_manifest_failed')

def quiet_window(env):
    report=None
    for sample in range(3):
        report=jobs(env)
        if not idle(report):return False,report
        if sample<2:time.sleep(15)
    tail=report['seconds_since_latest_finished']
    return (tail is None or tail>=30),report

PROTECTED_PREFIXES=('APP_','TAU_','LIVE_','KALSHI_','ALPACA_','APCA_','MASSIVE_','DATABENTO_','EXA_',
                    'ANTHROPIC_','OPENAI_','PROD_','DASHBOARD_','MYSQL_','GOOGLE_','STRIPE_','AWS_','IBKR_','ROBINHOOD_')

def verify_environment(before, after, managed):
    expected={**before,**managed}
    projection=lambda e:{k:v for k,v in e.items() if k.startswith(PROTECTED_PREFIXES) and k!='AWS_PROFILE'}
    if projection(expected)!=projection(after):raise ReleaseError('protected_runtime_environment_changed')
    if before.get('APP_SECRET_KEY')!=after.get('APP_SECRET_KEY') or not after.get('APP_SECRET_KEY'):
        raise ReleaseError('application_secret_changed')

def planned_startup(plan, before, expected):
    child=('import os,json,sys;want=json.load(sys.stdin);prefixes=tuple(want["prefixes"]);'
           'project=lambda e:{k:v for k,v in e.items() if k.startswith(prefixes) and k!="AWS_PROFILE"};'
           'print(json.dumps({"protected_environment_matches":project(dict(os.environ))==project(want["environment"])}))')
    tail=r'exec '+re.escape(PYTHON)+r' -u -m app\.(?:server|worker agents).*\Z'
    body,count=re.subn(tail,lambda _: 'exec '+shlex.join([PYTHON,'-B','-c',child]),plan['body'])
    if count!=1:raise ReleaseError('unrecognized_planned_startup_tail')
    raw=command(['/bin/bash','-ec',body],env=before,cwd=ROOT,
                stdin=json.dumps({'prefixes':PROTECTED_PREFIXES,'environment':expected}).encode())
    if json.loads(raw)!={'protected_environment_matches':True}:raise ReleaseError('planned_startup_environment_conflict')

def activate(credentials,bundle):
    result={'mode':'paper_release_activation','release_sha':RELEASE_SHA,'provider_calls':0,'order_calls':0,
            'restart_performed':False,'source_installed':False,'schema_migrated':False,'status':'started'}
    lock=os.open('/run/lock/tau-paper-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock);raise ReleaseError('another_paper_release_operation_active')
    helper=config_module()
    before={service:process(service) for service in TARGETS}
    others={service:props(service).get('MainPID') for service in OTHERS}
    base_hash={name:file_hash(ROOT/name) for name in ('.env.aws','.env.app')}
    provider_hash={name:file_hash(Path(name)) for name in PROVIDER_FILES}
    plans={service:unit_plan(service,helper) for service in TARGETS}
    provider=provider_configuration()
    overlay=helper['build_overlay'](credentials)
    paper={**credentials,'TAU_ALPACA_PAPER_ENABLED':'1','TAU_ALPACA_PAPER_MAX_ORDER_USD':'500',
           'APP_PUBLIC_URL':'https://d1gfpzcosqrjya.cloudfront.net'}
    for _,_,env in before.values():
        if not env.get('APP_SECRET_KEY'):raise ReleaseError('application_secret_missing')
        for field in credentials:
            if env.get(field) and env[field]!=credentials[field]:raise ReleaseError('installed_oauth_credential_conflict')
    first=jobs(before['recursive-agents'][2]);result['jobs']=first
    if not idle(first):result['status']='waiting_for_idle';return result
    if not source_check(BASELINE_MANIFEST):raise ReleaseError('production_source_conflict')
    release_root=Path('/opt/tau-releases')
    if release_root.exists() and (release_root.is_symlink() or release_root.stat().st_uid!=0 or release_root.stat().st_mode&0o022):
        raise ReleaseError('unsafe_release_directory')
    release_root.mkdir(mode=0o700,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='paper-'+RELEASE_SHA[:12]+'-',dir=release_root))
    os.chmod(staging,0o700)
    extract_bundle(bundle,staging)
    command([PYTHON,'-B','-c','import ast,pathlib;[ast.parse(p.read_bytes()) for d in ("app","data_pipeline") for p in pathlib.Path(d).rglob("*.py")]'],cwd=staging)
    expected_env={s:{**value[2],**(provider if s=='recursive-agents' else {}),**paper} for s,value in before.items()}
    for service in TARGETS:offline(staging,expected_env[service],paper=True)
    offline(staging,expected_env['recursive-agents'])
    ready,current=quiet_window(before['recursive-agents'][2]);result['jobs']=current
    if not ready:result.update(status='waiting_for_idle',staged_release=str(staging));return result
    for service,(plan,saved,values) in plans.items():
        if props(service)['MainPID']!=str(before[service][1]):raise ReleaseError('process_changed_before_cutover')
        for path,raw in saved.items():
            if path.read_bytes()!=raw:raise ReleaseError('unit_changed_before_cutover')
    if not source_check(BASELINE_MANIFEST):raise ReleaseError('source_changed_before_cutover')
    if any(file_hash(ROOT/name)!=digest for name,digest in base_hash.items()):raise ReleaseError('base_environment_changed')
    if any(file_hash(Path(name))!=digest for name,digest in provider_hash.items()):raise ReleaseError('provider_overlay_changed')
    if not idle(jobs(before['recursive-agents'][2])):result['status']='waiting_for_idle';return result
    saved_config={};installed_config={};attempted_config={};source_journal=[];stopped=False;installed=False;started=False
    backup=staging/'previous';backup.mkdir(mode=0o700)
    try:
        stopped=True
        command(['systemctl','stop',*TARGETS])
        if not idle(jobs(before['recursive-agents'][2])):raise ReleaseError('new_jobs_queued_during_cutover')
        helper['prepare_directories']()
        paths=[Path('/etc/tau/alpaca-paper/paper.env')]+[Path(plans[s][0]['drop_path']) for s in TARGETS]
        saved_config={path:helper['snapshot'](path) for path in paths}
        for index,(path,old) in enumerate(saved_config.items()):
            if old is not None:
                descriptor=os.open(backup/('config-'+str(index)),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(descriptor,'wb') as stream:stream.write(old['raw'])
        for name in ('app','data_pipeline'):
            os.rename(ROOT/name,backup/name)
            source_journal.append((name,False))
            os.rename(staging/name,ROOT/name)
            source_journal[-1]=(name,True)
        installed=True;result['source_installed']=True
        schema_env=dict(before['recursive-agents'][2]);schema_env.pop('AWS_PROFILE',None)
        schema_env['PYTHONDONTWRITEBYTECODE']='1'
        command([PYTHON,'-B','-m','app.schema'],env=schema_env,cwd=ROOT,timeout=180)
        result['schema_migrated']=True
        attempted_config[paths[0]]=overlay
        installed_config[paths[0]]=helper['atomic_write'](paths[0],overlay,saved_config[paths[0]])
        for service in TARGETS:
            path=Path(plans[service][0]['drop_path'])
            attempted_config[path]=plans[service][0]['drop_bytes']
            installed_config[path]=helper['atomic_write'](path,attempted_config[path],saved_config[path])
        # Execute only the planned shell sources and a boolean-only child, never the app.
        for service in TARGETS:planned_startup(plans[service][0],before[service][2],expected_env[service])
        command(['systemctl','daemon-reload'])
        started=True;result['restart_performed']=True
        command(['systemctl','start',*TARGETS])
        time.sleep(5)
        for service in TARGETS:
            values,pid,env=process(service)
            verify_environment(before[service][2],env,{**(provider if service=='recursive-agents' else {}),**paper})
            if any(values[k]!=before[service][0][k] for k in RESOURCES):raise ReleaseError('service_resources_changed')
            offline(ROOT,env,paper=True)
        if any(props(service).get('MainPID')!=pid for service,pid in others.items()):raise ReleaseError('unrelated_service_pid_changed')
        if any(file_hash(ROOT/name)!=digest for name,digest in base_hash.items()):raise ReleaseError('base_environment_changed_after_cutover')
        if any(file_hash(Path(name))!=digest for name,digest in provider_hash.items()):raise ReleaseError('provider_overlay_changed_after_cutover')
        with urllib.request.urlopen('http://127.0.0.1:8090/',timeout=15) as response:
            if response.status!=200:raise ReleaseError('origin_http_failed')
        result.update(status='deployed',ready_for_user_connection=True,origin_http_status=200,
                      unrelated_services_unchanged=True,protected_controls_unchanged=True,
                      app_secret_unchanged=True,base_environments_unchanged=True,backup_directory=str(backup),
                      authenticated_user_consent_verified=False,paper_order_verified=False)
        return result
    except Exception as exc:
        result['error_code']=exc.code if isinstance(exc,ReleaseError) else type(exc).__name__
        result['status']='deployment_requires_inspection'
        # Once the new worker can claim work, never roll it back or restart blindly.
        if started:
            result['rollback_performed']=False
            result['reason']='new_worker_may_have_claimed_jobs_preserve_installed_state'
            return result
        for path,intended in attempted_config.items():
            if path in installed_config:continue
            try:current=helper['snapshot'](path)
            except Exception:
                result.update(status='private_config_recovery_requires_inspection',rollback_performed=False)
                return result
            if current==saved_config[path]:continue
            if current is not None and current['raw']==intended:installed_config[path]=current
            else:
                result.update(status='private_config_recovery_requires_inspection',rollback_performed=False)
                return result
        for name,replaced in reversed(source_journal):
            if replaced:os.rename(ROOT/name,staging/('failed-'+name))
            os.rename(backup/name,ROOT/name)
        for path,saved in reversed(list(saved_config.items())):
            if path in installed_config:helper['restore'](path,saved,installed_config[path])
        if stopped:
            command(['systemctl','daemon-reload'])
            for service in TARGETS:
                state=props(service).get('ActiveState')
                if state=='inactive':command(['systemctl','start',service])
                elif state!='active':
                    result.update(status='service_recovery_requires_inspection',rollback_performed=True)
                    return result
        result.update(rollback_performed=True,status='failed_before_new_worker_start',
                      provider_activation_requires_verification=stopped,
                      original_process_environment_restored=False if stopped else True)
        return result
    finally:
        os.close(lock)

def main_inspect():
    try:return inspect()
    except Exception as exc:return {'mode':'paper_release_inventory','status':'inspection_failed',
        'error_code':exc.code if isinstance(exc,ReleaseError) else type(exc).__name__,
        'read_only':True,'provider_calls':0,'order_calls':0}
