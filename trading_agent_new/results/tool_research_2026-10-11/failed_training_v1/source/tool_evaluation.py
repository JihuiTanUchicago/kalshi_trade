"""Disjoint training, then a preregistered comparison of tool-using task loops."""
from pathlib import Path
import json
import os
import random

from .common import GateError, canonical, digest, file_hash, utcnow
from .evaluation import CONDITIONS, equal_answer, summarize
from .first_episode import require_smokes
from .models import Budget, HTTPModel, MeteredModel
from .procedural_memory import remember_trace, records, task_context
from .task_agent import MAX_STEPS, MAX_REQUEST_BYTES, MAX_OUTPUT_TOKENS, prepare_session, execute_session
from .tool_cases import cases

TRAIN_SEED=2026101101
EVAL_SEED=2026101103


def source_hashes():
    root=Path(__file__).parent
    names=('analysis_tools.py','task_verification.py','task_agent.py','procedural_memory.py','tool_cases.py','tool_evaluation.py',
           'evaluation.py','models.py','contracts.py','memory.py','memory_selection.py','agent.py','cli.py')
    return {name:file_hash(root/name) for name in names}


def metered(store,provider,config,phase,session):
    return MeteredModel(provider,Budget(store,phase,10 if phase=='v1-research-demo' else 35),
            config['input_per_million'],config['output_per_million'],max_decisions=MAX_STEPS,
            max_input_tokens=(MAX_REQUEST_BYTES+2048)*MAX_STEPS,max_output_tokens=MAX_OUTPUT_TOKENS*MAX_STEPS,episode_id=session)


def worst_cost(config,episodes):
    return episodes*MAX_STEPS*((MAX_REQUEST_BYTES+2048)*config['input_per_million']+MAX_OUTPUT_TOKENS*config['output_per_million'])/1e6


def check_budget(store,config,phase,episodes):
    cap=10 if phase=='v1-research-demo' else 35;budget=Budget(store,phase,cap)
    total=store.db.execute('SELECT coalesce(sum(coalesce(actual,amount)),0) FROM reservations').fetchone()[0]
    maximum=worst_cost(config,episodes)
    return {'episodes':episodes,'maximum_calls':episodes*MAX_STEPS,'max_estimated_cost':maximum,
            'remaining_phase_cap':cap-budget.used(),'remaining_total_cap':50-total,
            'can_run':min(config['input_per_million'],config['output_per_million'])>0 and maximum<=cap-budget.used() and maximum<=50-total,
            'caps_unchanged':True}


def proxy_case(directory):
    from .data import Dataset
    from .task_verification import reconstruct
    data=Dataset(directory);data.verify_unchanged()
    asset=next(k for k,v in data.assets.items() if v['symbol']=='SPY')
    days=data.days[-5:];rows=[]
    for i,day in enumerate(days):
        split=1.;dividend=0.
        if i:
            for event in data.actions.get(day,[]):
                if event['asset_id']==asset:
                    if event['kind']=='split':split*=event['value']
                    elif event['kind']=='dividend':dividend+=event['value']
                    else:raise GateError('Proxy analysis example contains an unsupported action')
        row=data.bars[day,asset]
        rows.append({'id':asset+'-'+day,'effective_at':data.sessions[day]['close_at'],'available_at':row['available_at'],
                     'close':row['close'],'split':split,'dividend':dividend})
    from datetime import datetime,timedelta
    payload={'initial_shares':10,'decision_at':(datetime.fromisoformat(data.sessions[days[-1]]['close_at'])+timedelta(minutes=30)).isoformat(),'rows':rows}
    expected={**reconstruct('select_asof',payload),**reconstruct('holding_return',payload)}
    expected={k:float(v) if type(v).__name__=='Fraction' else v for k,v in expected.items()}
    job={'version':1,'goal':'Compute the five-session SPY buy-and-hold return, ending shares and usable observation identities from this imported snapshot; timing is an explicit provider-import assumption.',
         'task_kind':'features','quality':data.quality,'market':'US','frequency':'daily','dataset_id':data.id,
         'documents':{'snapshot':{'kind':'market_history','payload':payload}},'output_fields':list(expected),
         'provenance':{'mode':'proxy_training_example','directory':str(Path(directory).resolve()),'qualification_gaps':data.manifest.get('qualification_gaps',{})}}
    return {'id':'features-proxy-training','family':'features','job':job,'expected':expected}


def prepare_training(store,config,output,dataset=None):
    require_smokes(store,config);key='tool_training_plan:'+str(TRAIN_SEED)
    existing=store.control(key)
    if existing:
        old=store.get(existing)
        if old['source_hashes']==source_hashes() and old['model_configuration']==config:return {'plan':existing,**old}
        if store.control('tool_training_used:'+existing):raise GateError('Consumed training keeps its pinned source/configuration; never reset it')
        retirement=store.put('tool_training_plan_retirement',{'plan':existing,'reason':'Unconsumed source/configuration revision',
                       'model_calls_started':False,'retired_at':utcnow()})
        store.set_control('tool_training_retired:'+existing,retirement)
    training=cases(TRAIN_SEED,True)
    if dataset:training.append(proxy_case(dataset))
    from .task_agent import validate_job
    for item in training:validate_job(item['job'])
    plan=store.put('tool_training_plan',{'version':1,'cases':training,'model_configuration':config,
              'source_hashes':source_hashes(),'output':str(Path(output).resolve()),'prepared_at':utcnow(),
              'alpha_claim':False,'scope':'Declared training examples; model service can be genuine while market scenarios remain synthetic/proxy.'})
    store.set_control(key,plan);path=Path(output);path.mkdir(parents=True,exist_ok=True)
    (path/'TRAINING_PREREGISTRATION.json').write_text(json.dumps({'plan':plan,'payload':store.get(plan)},indent=2)+'\n')
    return {'plan':plan,'tasks':len(training),'prepared_at':store.get(plan)['prepared_at'],'output':str(path.resolve())}


def require_config_sources(plan,config):
    if config!=plan['model_configuration'] or source_hashes()!=plan['source_hashes']:raise GateError('Retain frozen tool-study source/model/prices')


def provider_for(config,model):
    if model is not None:return model,False
    if config.get('local_no_auth',False) or not os.environ.get(config['api_key_env']):raise GateError('Genuine tool study needs its configured local credential')
    return HTTPModel(config),True


def train(store,plan_hash,config,model=None):
    previous=store.control('tool_training_result:'+plan_hash)
    if previous:return {'receipt':previous,**store.get(previous)}
    plan=store.get(plan_hash,'tool_training_plan');require_smokes(store,config);require_config_sources(plan,config)
    if store.control('tool_training_used:'+plan_hash):raise GateError('Partial training plan is retained; never reset its consumed sessions')
    check=check_budget(store,config,'v1-research-demo',len(plan['cases']))
    if not check['can_run']:raise GateError('Training does not fit the original remaining research/aggregate caps')
    provider,authentic=provider_for(config,model);store.set_control('tool_training_used:'+plan_hash,True)
    outcomes=[];memory=[]
    for case in plan['cases']:
        session='train:'+digest({'plan':plan_hash,'case':case['id']});prepare_session(store,case['job'],session_id=session)
        before=Budget(store,'v1-research-demo',10).used();item={'case':case['id'],'session':session,'passed':False,'result':None,'error':None}
        try:
            result=execute_session(store,session,metered(store,provider,config,'v1-research-demo',session))
            item.update(passed=equal_answer(case['expected'],result['reported_values']),result=result['receipt'])
            if item['passed']:memory.append(remember_trace(store,result['receipt']))
        except GateError as error:item['error']=str(error)[:220]
        item['cost']=Budget(store,'v1-research-demo',10).used()-before;outcomes.append(item)
    report=store.put('tool_training_result',{'plan':plan_hash,'authentic_model':authentic,'cases':outcomes,'memory':memory,
            'passed':sum(c['passed'] for c in outcomes),'tasks':len(outcomes),'cost':sum(c['cost'] for c in outcomes),
            'scope':'Tool procedures from declared practice; no evaluated answers used as memory. Proxy/synthetic qualification preserved.',
            'alpha_claim':False,'completed_at':utcnow()})
    store.set_control('tool_training_result:'+plan_hash,report)
    path=Path(plan['output']);(path/'TRAINING_RESULT.json').write_text(json.dumps(store.get(report),indent=2)+'\n')
    return {'receipt':report,**store.get(report)}


def clip(records,limit=1500):
    selected=[]
    for record in records:
        if len(canonical(selected+[record]).encode())<=limit:selected.append(record)
    return selected


def prepare(store,training_plan,config,output):
    previous=store.control('tool_evaluation_plan:'+str(EVAL_SEED))
    if previous:return status(store,previous)
    require_smokes(store,config);training_result=store.control('tool_training_result:'+training_plan)
    if not training_result:raise GateError('Finish declared training before freezing its procedural context')
    training=store.get(training_result)
    if not training['authentic_model'] and not config.get('local_no_auth',False):raise GateError('Tool evaluation context must come from genuine training calls')
    evaluation=cases(EVAL_SEED);known=set()
    training_plan_payload=store.get(training_plan)
    require_config_sources(training_plan_payload,config)
    known.update(digest(c['job']) for c in training_plan_payload['cases'])
    for row in store.db.execute("SELECT hash FROM artifacts WHERE kind='tool_evaluation_suite'"):
        known.update(digest(c['job']) for c in store.get(row[0])['cases'])
    if any(digest(c['job']) in known for c in evaluation):raise GateError('Evaluation reuses a reserved/training job')
    memory=[r for r in records(store) if r['id'] in training['memory']]
    raw=[];evidence=[]
    for item in training['cases']:
        if item['result']:
            document=store.get(item['result']);evidence.append(item['result'])
            for field,value in document.items():raw.append({'evidence':item['result'],'field':field,'value':value})
    context=store.put('tool_evaluation_context',{'memory':memory,'selected':{c['id']:task_context(store,c['job'],memory) for c in evaluation},
             'raw_context':clip(raw),'underlying_evidence':evidence,'byte_bound':1500,'memory_updates_during_campaign':False})
    suite=store.put('tool_evaluation_suite',{'version':3,'seed':EVAL_SEED,'cases':evaluation,'conditions':list(CONDITIONS),'repetitions':2,
             'thresholds':{'no_learning_gain':.1,'raw_logs_gain':.05,'confidence_level':.95},'max_model_calls':MAX_STEPS,
             'max_request_bytes':MAX_REQUEST_BYTES,'max_output_tokens':MAX_OUTPUT_TOKENS,'scope':'40 new tool-using scenarios, known training families; not alpha or general research discovery.'})
    plan=store.put('tool_evaluation_plan',{'suite':suite,'context':context,'training':training_result,
              'model_configuration':config,'source_hashes':source_hashes(),'prepared_at':utcnow(),'output':str(Path(output).resolve()),
              'thresholds_changed':False,'weights_changed':False,'paper_authority':False})
    store.set_control('tool_evaluation_plan:'+str(EVAL_SEED),plan);path=Path(output);path.mkdir(parents=True,exist_ok=True)
    (path/'PREREGISTRATION.json').write_text(json.dumps({'plan_hash':plan,'plan':store.get(plan),'suite':store.get(suite),
               'contexts':store.get(context),'performance_inspected':False},indent=2)+'\n')
    (path/'PREREGISTRATION.md').write_text('# Protected-tool learning evaluation\n\n'
          f'Frozen {store.get(plan)["prepared_at"]}. Plan: {plan}.\n\n'
          '40 new synthetic workflow tasks × three contexts × two repetitions = 240 episodes. All conditions receive identical '
          'immutable jobs, public tools/guardrails, schemas, four-call/one-repair limits and per-call token/byte bounds. '
          'Every final number must cite independently reconstructed tool output. Memory contains verified practice tool sequences '
          'and original scopes; numerical practice answers are omitted. Raw context uses the same underlying practice traces. '
          'Both contexts are bounded to 1,500 bytes. Inputs/answer keys, ordering seed, contexts, model/prices and source hashes are pinned.\n\n'
          'Unchanged learning gates: >=10pp vs no context; >=5pp vs raw context; positive paired task-bootstrap 95% lower bound; '
          'zero hard failures on timing/exposure/decision/execution outcomes. Structural/action errors may consume the same one '
          'bounded repair for every condition; blocked attempts are additionally reported. No memory updates during evaluation. '
          'Complete all 240; partial consumption retires the plan. Direct-answer versions are preserved and never rescored.\n\n'
          'Tool reliability and memory improvement are separate results. A ceiling in the no-memory baseline can prevent '
          'the learning gain thresholds even when the tool workflow is reliable. Across-version scores are incomparable. '
          'Tasks are synthetic and broadly templated; training includes a separately labeled exploratory proxy example when supplied. '
          'No strategy or data qualification, alpha claim, broker connection or trading authority.\n')
    return status(store,plan)


def status(store,plan_hash):
    plan=store.get(plan_hash,'tool_evaluation_plan');result=store.control('tool_evaluation_result:'+plan_hash)
    return {'plan':plan_hash,'suite':plan['suite'],'prepared_at':plan['prepared_at'],'consumed':bool(store.control('tool_evaluation_used:'+plan_hash)),
            'result':result,'learning_demonstrated':store.get(result)['learning_demonstrated'] if result else False,'paper_eligible':False,'output':plan['output']}


def preflight(store,plan_hash,config):
    plan=store.get(plan_hash,'tool_evaluation_plan');require_config_sources(plan,config)
    return {'plan':plan_hash,**check_budget(store,config,'v1-benchmark',240)}


def run(store,plan_hash,config,model=None):
    previous=store.control('tool_evaluation_result:'+plan_hash)
    if previous:return {'receipt':previous,**store.get(previous)}
    if store.control('tool_evaluation_used:'+plan_hash):raise GateError('Partial tool evaluation is retired; do not replay inspected cases')
    plan=store.get(plan_hash,'tool_evaluation_plan');require_smokes(store,config);check=preflight(store,plan_hash,config)
    if not check['can_run']:raise GateError('Full tool campaign does not fit the original remaining caps')
    provider,authentic=provider_for(config,model);suite=store.get(plan['suite']);snapshot=store.get(plan['context'])
    schedule=[(c,condition,r) for c in suite['cases'] for condition in CONDITIONS for r in range(2)]
    random.Random(suite['seed']).shuffle(schedule);store.set_control('tool_evaluation_used:'+plan_hash,True);episodes=[]
    budget=Budget(store,'v1-benchmark',35)
    for case,condition,repetition in schedule:
        context=[] if condition=='no_learning' else snapshot['raw_context'] if condition=='raw_logs' else snapshot['selected'][case['id']]
        session='eval:'+digest({'plan':plan_hash,'case':case['id'],'condition':condition,'repetition':repetition})
        prepare_session(store,case['job'],context,session);before=budget.used();answer=None;error=None;receipt=None
        try:
            result=execute_session(store,session,metered(store,provider,config,'v1-benchmark',session));answer=result['reported_values'];receipt=result['receipt']
        except GateError as exc:error=str(exc)[:220]
        passed=equal_answer(case['expected'],answer);state=store.control('tool_task_session:'+session)
        episode={'case':case['id'],'condition':condition,'repetition':repetition,'session':session,'result':receipt,
                 'passed':passed,'hard_error':case['family'] in {'timing','exposures','decisions','execution'} and not passed,
                 'answer':answer,'error':error,'cost':budget.used()-before,'calls':state['calls'],'blocked_attempts':state['repairs']}
        episodes.append(episode);store.put('tool_evaluation_episode',{'plan':plan_hash,'episode':episode})
    report=summarize(suite,episodes,authentic)
    report.update({'protocol_version':3,'plan':plan_hash,'suite':plan['suite'],'context':plan['context'],'training':plan['training'],
       'episodes_detail':episodes,'model_calls':sum(e['calls'] for e in episodes),'blocked_attempts':{k:sum(e['blocked_attempts'] for e in episodes if e['condition']==k) for k in CONDITIONS},
       'memory_hard_failures':sum(e['hard_error'] for e in episodes if e['condition']=='verified_memory'),'paper_eligible':False,
       'tool_completion_rates':{k:sum(e['result'] is not None for e in episodes if e['condition']==k)/80 for k in CONDITIONS},
       'original_campaigns_overwritten':False,'scope':suite['scope'],'completed_at':utcnow()})
    receipt=store.put('tool_evaluation_result',report);store.set_control('tool_evaluation_result:'+plan_hash,receipt)
    output=Path(plan['output']);(output/'EVALUATION.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'REPORT.md').write_text('# Protected research tools: evaluation\n\n'
           f'240 genuine-model episodes: {authentic}. Learning demonstrated: **{report["learning_demonstrated"]}**.\n\n'
           '| Condition | Strict success | Completed verified report |\n|---|---:|---:|\n'+
           ''.join(f'| {k} | {report["success_rates"][k]:.2%} | {report["tool_completion_rates"][k]:.2%} |\n' for k in CONDITIONS)+
           f'\nPaired lower bound: {report["paired_95_lower"]:+.4f}; memory hard failures: {report["memory_hard_failures"]}. '
           f'Model calls: {report["model_calls"]}; configured-price estimate ${report["cost"]:.6f}.\n\n'
           'Tool reliability does not substitute for the fixed improvement gates. All prior campaigns are preserved and retired. '
           'Synthetic task competence does not establish investing alpha or broad research generalization. Paper remains gated.\n')
    return {'receipt':receipt,**report}
