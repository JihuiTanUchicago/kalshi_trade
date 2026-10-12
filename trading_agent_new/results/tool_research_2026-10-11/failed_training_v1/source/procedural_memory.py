"""Small evidence-checked procedural contexts; historical numbers stay in evidence."""
import json
import re

from .analysis_tools import CATALOG
from .common import GateError, canonical
from .memory import Memory, PROCEDURES
from .memory_selection import checked_record
from .task_verification import verify

PROCEDURE={'timing':'timing','features':'timing','corporate_actions':'operational_attribution',
           'controlled_experiments':'cost_attribution','cost_attribution':'cost_attribution',
           'exposures':'exposure_control','decisions':'uncertainty','execution':'operational_attribution'}


def verify_trace(store,key):
    trace=store.get(key,'operational_check')
    if trace.get('component')!='analytical_task' or trace.get('passed') is not True:raise GateError('Procedural memory needs a completed verified analytical task')
    job=store.get(trace['job'],'tool_task_job');checked={}
    for receipt_key in trace['receipts']:
        receipt=store.get(receipt_key,'analysis_result');source=receipt['source']
        if receipt['job']!=trace['job'] or source['job']!=trace['job'] or not receipt['independently_verified']:raise GateError('Analytical trace changed its source binding')
        if 'document' in source:
            original=job['documents'][source['document']];payload=original['payload'];kind=original['kind']
        elif source.get('receipt') in checked:
            original=checked[source['receipt']]['result'];payload=original['payload'];kind=original['kind']
        else:raise GateError('Analytical trace dependency is missing or out of order')
        if receipt['input_kind']!=kind or CATALOG[receipt['operation']]['input_kind']!=kind:raise GateError('Trace input kind differs from its verified source')
        verify(receipt['operation'],payload,receipt['result']);checked[receipt_key]=receipt
    if [r['operation'] for r in checked.values()]!=trace['operations'] or trace['quality']!=job['quality']:raise GateError('Trace operations/source scope changed')
    if set(trace['citations'])!=set(job['output_fields']) or set(trace['reported_values'])!=set(job['output_fields']):raise GateError('Trace omitted a requested field')
    for name,citation in trace['citations'].items():
        if citation['evidence'] not in checked or citation['pointer']!='/result/report/'+name:raise GateError('Final analytical citation is not verified')
        if canonical(checked[citation['evidence']]['result']['report'][name])!=canonical(trace['reported_values'][name]):raise GateError('Reported value differs from its evidence')
    return trace,job


def remember_trace(store,trace_hash):
    trace,job=verify_trace(store,trace_hash)
    claims=[{'pointer':'/operations/'+str(i),'equals':operation} for i,operation in enumerate(trace['operations'])]
    claims += [{'pointer':'/input_kinds/'+str(i),'equals':kind} for i,kind in enumerate(trace['input_kinds'])]
    claims += [{'pointer':'/passed','equals':True},{'pointer':'/alpha_claim','equals':False}]
    scope={'market':'US','frequency':'daily','quality':job['quality'],'task_kind':job['task_kind'],
           'original_input_kinds':sorted({d['kind'] for d in job['documents'].values()}),
           'transfer':'procedure_only','training_job':trace['job']}
    if job.get('dataset_id'):scope['source_dataset_id']=job['dataset_id']
    return Memory(store).add(trace_hash,claims,PROCEDURE[job['task_kind']],scope)


def records(store):
    return [checked_record(store,json.loads(row[0])) for row in store.db.execute("SELECT payload FROM memory WHERE status='verified' ORDER BY id")]


def task_context(store,job,snapshot=None):
    candidates=records(store) if snapshot is None else snapshot
    kinds=sorted({d['kind'] for d in job['documents'].values()});selected=[]
    for record in candidates:
        record=checked_record(store,record);scope=record['scope']
        if scope.get('transfer')!='procedure_only' or scope.get('task_kind')!=job['task_kind'] or scope.get('original_input_kinds')!=kinds:continue
        trace,_=verify_trace(store,record['evidence'])
        steps=[{'operation':op,'input_kind':kind} for op,kind in zip(trace['operations'],trace['input_kinds'])]
        if any(step['operation'] not in CATALOG or CATALOG[step['operation']]['input_kind']!=step['input_kind'] for step in steps):raise GateError('Learned procedure contains an unsupported tool step')
        projected={'procedure':record['procedure'],'method':PROCEDURES[record['procedure']],
                   'verified_tool_sequence':steps,'evidence':record['evidence'],'memory_id':record['id'],
                   'scope':scope,'uncertainty':'Verified on a prior task; bind to current handles and rules. No past numerical answers or profitability claim.'}
        if len(canonical(selected+[projected]).encode())<=1500:selected.append(projected)
        if len(selected)==2:break
    return selected


def research_context(store,query,dataset_id=None):
    words=set(re.findall(r'[a-z]+',query.lower()))
    stop={'the','and','for','from','with','this','that','use','daily','research','data','same','before','after'}
    words-=stop;ranked=[]
    for record in records(store):
        scope=record['scope']
        if dataset_id and scope.get('dataset_id') not in (None,dataset_id):continue
        method=PROCEDURES[record['procedure']]
        matched=words & set(re.findall(r'[a-z]+',record['procedure'].replace('_',' ')+' '+method.lower()))
        if len(matched)<2:continue
        ranked.append((-len(matched),record['id'],{'procedure':record['procedure'],'method':method,
                    'evidence':record['evidence'],'memory_id':record['id'],'scope':scope,
                    'uncertainty':'Methodological context only; current inputs and independent verification decide the result.'}))
    selected=[]
    for _,_,record in sorted(ranked):
        if len(canonical(selected+[record]).encode())<=1500:selected.append(record)
        if len(selected)==2:break
    return selected
