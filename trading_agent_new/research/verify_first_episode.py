#!/usr/bin/env python3
"""Read-only audit of authentic ordered integration; no model or broker calls.

Recheck stored ledger receipts with the independent raw-price verifier, immutable
evidence, preregistration, scoped memory, paired learning coverage and spend.
Source market-data qualification remains a separate failed gate.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import statistics

from quant_agent.configuration import load_model_environment
from quant_agent.contracts import ResearchSpec
from quant_agent.data import Dataset
from quant_agent.verify import verify_ledger


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def matches(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and expected.keys() == actual.keys() and all(matches(v, actual[k]) for k, v in expected.items())
    if type(expected) in (int, float):
        return type(actual) in (int, float) and math.isfinite(actual) and abs(actual-expected) <= 1e-6*max(1, abs(expected))
    return type(expected) is type(actual) and expected == actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', default='.quant-agent')
    parser.add_argument('--run', default='ff68fae9bfcf4801807b1477e197742a')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    store = (root / args.store).resolve()
    db = sqlite3.connect((store / 'state.sqlite3').as_uri()+'?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    def artifact(key):
        path = store / 'artifacts' / (key+'.json')
        if sha(path) != key:raise ValueError('Immutable artifact hash mismatch')
        return json.loads(path.read_text())['payload']
    def control(key):
        row = db.execute('SELECT value FROM controls WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None
    checks = []
    def check(name, passed, details=None):
        checks.append({'name':name, 'passed':bool(passed), 'details':details})

    run = dict(db.execute('SELECT * FROM runs WHERE id=?', (args.run,)).fetchone())
    plan = artifact(control('first_episode_run:'+args.run))
    output = Path(plan['output']) / args.run
    prereg = json.loads((output / 'PREREGISTRATION.json').read_text())
    spec = artifact(run['spec'])
    dataset = Dataset(plan['directory']);dataset.verify_unchanged()
    check('frozen_inputs_and_completed_workflow', run['state']=='finished' and
          prereg['spec_hash']==run['spec'] and prereg['specification']==spec and
          prereg['candidate']==artifact(run['strategy']) and prereg['performance_computed'] is False and
          dataset.id==spec['dataset_id']==plan['dataset_id'])
    usages = list(db.execute("SELECT payload,created FROM events WHERE kind='model_usage'"))
    check('preregistration_precedes_authentic_model_calls', bool(usages) and
          prereg['recorded_at'] < min(r['created'] for r in usages))
    checked_artifacts = list(db.execute('SELECT hash FROM artifacts'))
    for row in checked_artifacts:artifact(row[0])
    check('immutable_evidence_hashes', True, {'artifacts':len(checked_artifacts)})
    config = json.loads((root / 'config/grok.local.json').read_text())
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    smokes = [artifact(r[0]) for r in db.execute("SELECT hash FROM artifacts WHERE kind='adapter_smoke'")]
    valid_smokes = [s for s in smokes if s.get('configuration')==config_hash and s.get('passed') is True and s.get('real_request') is True and not s.get('test_fixture')]
    check('two_authentic_configuration_bound_smokes', {'json','workflow'} <= {s.get('case') for s in valid_smokes})
    result, challenge, decision = (artifact(run[k]) for k in ('result','challenge','decision'))
    register = artifact(result['trial_register'])
    check('six_preregistered_trials_and_single_attempt', len(register['trials'])==6 and
          db.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND kind='experiment_attempt'",(args.run,)).fetchone()[0]==1)
    receipts = {name:verify_ledger(dataset, ResearchSpec(**spec), artifact(key)) for name,key in result['ledgers'].items()}
    check('six_independently_reverified_ledgers', len(receipts)==6 and all(r['passed'] for r in receipts.values()), receipts)
    check('challenge_and_rejection_qualification_retained', challenge['passed'] and challenge['prefix_invariance'] and
          challenge['future_perturbation'] and decision['result']==run['result'] and decision['challenge']==run['challenge'] and
          result['qualification']['quality']=='proxy' and result['qualification']['qualified'] is False and
          decision['paper_eligible'] is False and decision['live_capital_eligible'] is False)
    memory = [json.loads(row[0]) for row in db.execute("SELECT payload FROM memory WHERE status='verified'")]
    scoped = [m for m in memory if m['evidence'] in {run[k] for k in ('result','challenge','decision')}]
    memory_ok = bool(scoped)
    for entry in scoped:
        document = artifact(entry['evidence'])
        for claim in entry['claims']:
            value = document
            for part in claim['pointer'].split('/')[1:]:
                key = part.replace('~1','/').replace('~0','~')
                value = value[int(key)] if isinstance(value,list) else value[key]
            memory_ok = memory_ok and matches(claim['equals'],value) and not isinstance(value,(dict,list))
        memory_ok = memory_ok and entry['scope']['dataset_id']==dataset.id and entry['scope']['quality']=='proxy'
    check('scoped_memory_exact_observations', memory_ok, {'records':len(scoped)})
    transfer = artifact(control('first_episode_transfer:'+args.run))
    proposal = transfer['proposal']
    expected_spec = spec | {'hypothesis':proposal['hypothesis'],'lookback':20}
    check('distinct_transfer_preserves_protected_specification', transfer.get('validation_version')==2 and
          transfer['protected_specification_checks_passed'] and asdict(ResearchSpec(**proposal['research_spec']))==expected_spec and
          proposal['paper_eligible'] is False and set(proposal['evidence_hashes']) <= {m['evidence'] for m in scoped})
    review = artifact(control('first_episode_transfer_review:'+args.run))
    check('failed_proposals_and_action_attempts_retained', review['accepted'] is False and
          (output / 'TRANSFER_CITATION_ONLY.json').exists() and
          db.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND kind='action_rejected'",(args.run,)).fetchone()[0]>=2 and
          db.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND kind='transfer_rejected'",(args.run,)).fetchone()[0]>=1)
    learning = artifact(control('first_episode_learning:'+args.run))
    suite = artifact(plan['learning_suite'])
    cases = {case['id']:case for case in suite['cases']}
    expected_pairs = {(case,condition,rep) for case in cases for condition in ('no_learning','raw_logs','verified_memory') for rep in range(2)}
    episodes = learning['episodes_detail']
    actual_pairs = [(e['case'],e['condition'],e['repetition']) for e in episodes]
    check('complete_frozen_authentic_learning_campaign', learning['suite']==plan['learning_suite'] and
          len(cases)==40 and len(actual_pairs)==240 and len(set(actual_pairs))==240 and set(actual_pairs)==expected_pairs and
          learning['gates']['authentic_model'] is True)
    correctly_graded = all(matches(cases[e['case']]['expected'],e['answer']) == e['passed'] for e in episodes)
    means = {c:statistics.mean(e['passed'] for e in episodes if e['condition']==c) for c in suite['conditions']}
    outcomes = {(e['case'],e['condition'],e['repetition']):float(e['passed']) for e in episodes}
    differences = [statistics.mean(outcomes[case['id'],'verified_memory',r]-outcomes[case['id'],'no_learning',r] for r in range(2)) for case in suite['cases']]
    rng = random.Random(suite['seed'])
    distribution = sorted(statistics.mean(rng.choices(differences,k=40)) for _ in range(5000))
    lower = distribution[int(.025*4999)]
    hard_errors = sum(not e['passed'] for e in episodes if e['condition']=='verified_memory' and cases[e['case']]['family'] in {'timing','exposures','decisions','execution'})
    demonstrated = means['verified_memory']-means['no_learning'] >= .10 and means['verified_memory']-means['raw_logs'] >= .05 and lower>0 and hard_errors==0
    check('learning_outcomes_and_uncertainty_recomputed', correctly_graded and means==learning['success_rates'] and
          lower==learning['paired_95_lower'] and demonstrated==learning['learning_demonstrated'],
          {'success_rates':means,'paired_95_lower':lower,'hard_errors':hard_errors,'learning_demonstrated':demonstrated})
    costs = [dict(row) for row in db.execute('SELECT campaign,COUNT(*) AS requests,SUM(COALESCE(actual,amount)) AS usd FROM reservations GROUP BY campaign')]
    caps = dict(db.execute('SELECT campaign,cap FROM budgets'))
    total = sum(c['usd'] for c in costs)
    check('original_durable_spend_caps', total<=50 and all(c['usd']<=caps[c['campaign']] for c in costs) and
          caps=={'v1-smoke':5,'v1-research-demo':10,'v1-benchmark':35}, {'usd':total,'campaigns':costs})
    legacy = json.loads((root / 'results/agent_v1/legacy_baseline.json').read_text())
    check('legacy_research_preserved', len(legacy)==181 and all(sha(root/path)==value for path,value in legacy.items()), {'files':len(legacy)})
    baseline = json.loads((root / 'results/ordered_integration_2026-10-10/source_baseline.json').read_text())['files']
    changed = [p for p,value in baseline.items() if sha(root/p)!=value]
    allowed = {'src/quant_agent/agent.py','src/quant_agent/cli.py','src/quant_agent/experiments.py','src/quant_agent/memory.py','src/quant_agent/models.py','src/quant_agent/report.py'}
    check('protected_engine_grader_and_broker_sources_preserved', set(changed)<=allowed, {'changed_original_sources':changed})
    check('no_execution_intents_or_releases', db.execute('SELECT COUNT(*) FROM intents').fetchone()[0]==0 and db.execute('SELECT COUNT(*) FROM releases').fetchone()[0]==0)
    secrets = []
    for key in ('XAI_API_KEY','APCA_API_KEY_ID','APCA_API_SECRET_KEY'):
        load_model_environment(root / '.env', {'api_key_env':key})
        value = os.environ.get(key,'')
        if value:secrets.append(value.encode())
    inspected = [p for base in ('src','tests','config','docs','results/ordered_integration_2026-10-10','data/agent_imports/alpaca_proxy_20261010','data/alpaca_enrichment/20261010_ordered_build') for p in (root/base).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    inspected += [root/'README.md',root/'.env.example',root/'research/run_first_episode.sh',Path(__file__)]
    check('private_credentials_excluded_from_artifacts_and_source', bool(secrets) and all(not any(value in path.read_bytes() for value in secrets) for path in inspected) and
          (root/'.env').stat().st_mode & 0o777 == 0o600, {'files_checked':len(inspected),'credential_values_logged':False})
    db.close()
    report = {'status':'passed' if all(c['passed'] for c in checks) else 'failed','checks_passed':sum(c['passed'] for c in checks),
              'checks_total':len(checks),'run':args.run,'dataset_id':dataset.id,'checks':checks,
              'data_qualified':False,'learning_demonstrated':demonstrated,'paper_eligible':False,'model_usage_cost_usd':total,
              'limitations':'Verification proves the stated engineering/provenance checks. It does not resolve market-data disagreements, original availability, rights, generalized learning or investment alpha.'}
    with Path(args.output).open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps({k:report[k] for k in ('status','checks_passed','checks_total','model_usage_cost_usd','learning_demonstrated')}))
    return 0 if report['status']=='passed' else 2


if __name__=='__main__':
    raise SystemExit(main())
