"""Validate and select scoped findings from a frozen memory snapshot."""
import re
from .common import GateError, canonical, digest, pointer
from .memory import PROCEDURES


def checked_record(store, record):
    """Copy trusted fields only; do not promote mutable memory prose to policy."""
    required = {k:record[k] for k in ('evidence','claims','procedure','scope')}
    if record.get('id') != digest(required) or required['procedure'] not in PROCEDURES:
        raise GateError('Memory identity/procedure does not match its verified facts')
    scope = required['scope']
    if scope.get('market')!='US' or scope.get('frequency')!='daily':
        raise GateError('Memory lacks the protected market/frequency scope')
    row = store.db.execute('SELECT kind FROM artifacts WHERE hash=?',(required['evidence'],)).fetchone()
    if not row:raise GateError('Memory evidence is missing')
    from .memory import TRUSTED_KINDS
    if row[0] not in TRUSTED_KINDS:raise GateError('Memory evidence was not verifier-produced')
    document = store.get(required['evidence'],row[0])
    source = document
    if row[0] in {'decision','challenge'}:
        source = store.get(document['result'],'experiment_result')
    quality = source.get('qualification',{}).get('quality',source.get('quality'))
    if quality and scope.get('quality') != quality:raise GateError('Memory source qualification changed')
    if row[0]=='experiment_result' and not all(v['passed'] for v in document['verification'].values()):
        raise GateError('Memory performance was not independently verified')
    if row[0] in {'challenge','operational_check'} and document.get('passed') is not True:
        raise GateError('Memory verifier did not pass')
    observations = []
    for claim in required['claims']:
        if set(claim)!={'pointer','equals'}:raise GateError('Invalid memory claim fields')
        value = pointer(document,claim['pointer'])
        if isinstance(value,(dict,list)) or canonical(value)!=canonical(claim['equals']):
            raise GateError('Memory observation no longer matches evidence')
        observations.append(claim['pointer']+' = '+canonical(value))
    if not observations:raise GateError('Memory has no verified observations')
    return {**required,'id':record['id'],'procedure_text':PROCEDURES[required['procedure']],
            'observations':observations,'uncertainty':'Scoped past observation; current task inputs and protected rules remain authoritative.'}


def select_records(records, query, procedures=(), dataset_id=None, max_bytes=4000, limit=5):
    """Rank relevance before applying a byte limit; skip oversized records."""
    if not 0 <= max_bytes <= 8000 or not 1 <= limit <= 10:
        raise GateError('Invalid bounded memory selection limits')
    if not set(procedures)<=set(PROCEDURES):raise GateError('Unknown memory procedure hint')
    words = lambda text:set(re.findall(r'[a-z]+',text.lower().replace('_',' ')))
    stop = {'the','and','with','from','this','that','for','use','return','same','task','data','true','false','daily','us'}
    tokens = words(query)-stop
    ranked = []
    for record in records:
        scope = record['scope']
        if scope.get('market')!='US' or scope.get('frequency')!='daily':continue
        if dataset_id and scope.get('dataset_id') not in (None,dataset_id):continue
        overlap = len(tokens & words(record['procedure']+' '+record['procedure_text']+' '+' '.join(record['observations'])))
        score = overlap + (100 if record['procedure'] in procedures else 0)
        if score:ranked.append((-score,record['id'],record))
    selected = []
    for _,_,record in sorted(ranked):
        if len(canonical(selected+[record]).encode())>max_bytes:continue
        selected.append(record)
        if len(selected)==limit:break
    return selected
