"""Independent offline audit of the protected-tool campaign; no model calls."""
from collections import Counter
from datetime import datetime
from fractions import Fraction
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

from quant_agent.common import canonical
from quant_agent.store import Store

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/tool_research_2026-10-11'
SOURCE='ff68fae9bfcf4801807b1477e197742a'
OLD='bf2f3ccffd66f3bfcf37878465d18ee9b17f1c56093c95015b7a04c84f567808'
OLD_V2='9444d4dd151b844169b1d76a5dd74cc9b55c775fc7fa03a4ccd275a44967f29a'
KINDS={'select_asof':('market_history','asof_history'),'holding_return':('asof_history','return_report'),
       'account_actions':('action_account','action_report'),'compare_assumptions':('paired_assumptions','comparison_report'),
       'attribute_costs':('cost_controls','cost_report'),'summarize_exposure':('exposure_account','exposure_report'),
       'apply_research_gates':('research_evidence','gate_report'),'reconcile_fills':('execution_snapshot','execution_report')}
OPERATION={'timing':'select_asof','features':'holding_return','corporate_actions':'account_actions',
           'controlled_experiments':'compare_assumptions','cost_attribution':'attribute_costs','exposures':'summarize_exposure',
           'decisions':'apply_research_gates','execution':'reconcile_fills'}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def equal(want,got,tolerance=1e-6):
    if isinstance(want,dict):
        return isinstance(got,dict) and want.keys()==got.keys() and all(equal(v,got[k],tolerance) for k,v in want.items())
    if type(want) in (int,float,Fraction):
        return type(got) in (int,float) and math.isfinite(got) and abs(float(want)-got)<=tolerance*max(1,abs(float(want)))
    return type(got) is type(want) and want==got


def usable(x):
    at=datetime.fromisoformat(x['decision_at'].replace('Z','+00:00'))
    kept=[r for r in x['rows'] if all(datetime.fromisoformat(r[k].replace('Z','+00:00'))<=at for k in ('effective_at','available_at'))]
    return sorted(kept,key=lambda r:(datetime.fromisoformat(r['effective_at'].replace('Z','+00:00')),r['id']))


def compute(operation,x):
    """Reconstruct input facts; never import the tools, verifier, generator or grader."""
    f=lambda value:Fraction(str(value))
    if operation=='select_asof':return {'usable_ids':sorted(r['id'] for r in usable(x))}
    if operation=='holding_return':
        rows=x['rows'];hold=f(x['initial_shares']);distributions=Fraction(0)
        for r in rows[1:]:
            hold*=f(r['split']);distributions+=hold*f(r['dividend'])
        return {'ending_shares':int(hold),'total_return':(hold*f(rows[-1]['close'])+distributions)/(x['initial_shares']*f(rows[0]['close']))-1}
    if operation=='account_actions':
        opening=x['opening_shares'];quantity=Fraction(opening);accounts={True:Fraction(0),False:Fraction(0)}
        for event in x['events']:
            quantity*=f(event['split']);accounts[event['paid']]+=quantity*f(event['dividend'])
        return {'ending_shares':int(quantity),'cash_change':accounts[True],'unpaid_dividend_claim':accounts[False],
                'nav_change':quantity*f(x['ending_price'])+sum(accounts.values())-opening*f(x['opening_price'])}
    if operation=='compare_assumptions':
        base=x['baseline'];candidate=x['candidate'];missing=object()
        changed=sorted(k for k in set(base)|set(candidate) if base.get(k,missing) is missing or candidate.get(k,missing) is missing
                       or json.dumps(base[k],sort_keys=True,separators=(',',':'))!=json.dumps(candidate[k],sort_keys=True,separators=(',',':')))
        return {'comparable':len(changed)==0,'mismatched_assumptions':changed}
    if operation=='attribute_costs':
        spreads=[f(x['candidate_'+kind+'_sharpe'])-f(x['baseline_'+kind+'_sharpe']) for kind in ('net','cost_free')]
        return {'net_gain':spreads[0],'cost_free_gain':spreads[1],'modeled_cost_contribution':spreads[0]-spreads[1],
                'turnover_change':(f(x['candidate_traded_notional'])-f(x['baseline_traded_notional']))/f(x['average_nav'])}
    if operation=='summarize_exposure':
        values=[f(v) for v in x['signed_market_values']]
        return {'gross_weight':sum(abs(v) for v in values)/f(x['nav']),'net_weight':sum(values)/f(x['nav']),
                'free_cash':f(x['cash'])-f(x['restricted_collateral'])-f(x['short_dividend_obligation'])}
    if operation=='apply_research_gates':
        checks=(f(x['sharpe_gain'])>=Fraction(1,10),f(x['paired_lower'])>0,f(x['double_cost_gain'])>0,
                f(x['drawdown_deterioration'])<=Fraction(1,50),x['bootstrap_samples']>=2000,x['blocks']>=2,
                x['block_length']>=21,x['verification_passed'] is True)
        label='reject'
        if all(checks):label='advance_to_paper_qualification' if x['qualified_data'] else 'revise_data_qualification'
        return {'decision':label}
    if operation=='reconcile_fills':
        identities={};conflict=False
        for fill in x['executions']:
            if fill['id'] in identities and fill['quantity']!=identities[fill['id']]:conflict=True
            identities.setdefault(fill['id'],fill['quantity'])
        count=sum(identities.values())
        conflict=conflict or count>x['requested_quantity'] or x['status']=='filled' and count!=x['requested_quantity']
        action='pause' if conflict else 'closed' if x['status']=='filled' else 'wait' if x['status']=='acknowledged' else 'reconcile'
        return {'next_action':action,'resubmit':False,'filled_quantity':count}
    raise ValueError('Unknown calculation')


def answer(case):
    job=case['job'];payload=next(iter(job['documents'].values()))['payload'];operation=OPERATION[case['family']]
    if case['family']=='features':
        filtered={**payload,'rows':usable(payload)}
        report={**compute('select_asof',payload),**compute(operation,filtered)}
    else:report=compute(operation,payload)
    return {name:report[name] for name in job['output_fields']}


def trace_valid(store,key):
    trace=store.get(key,'operational_check');job=store.get(trace['job'],'tool_task_job');done={}
    if not (trace['passed'] is True and trace['component']=='analytical_task' and trace['quality']==job['quality']
            and trace['alpha_claim'] is False and trace['paper_eligible'] is False):return False
    for receipt_key in trace['receipts']:
        receipt=store.get(receipt_key,'analysis_result');source=receipt['source'];operation=receipt['operation']
        if receipt['job']!=trace['job'] or source['job']!=trace['job']:return False
        if 'document' in source:original=job['documents'][source['document']]
        elif source.get('receipt') in done:original=done[source['receipt']]['result']
        else:return False
        if original['kind']!=KINDS[operation][0] or receipt['input_kind']!=original['kind']:return False
        result=receipt['result'];want=compute(operation,original['payload'])
        if result['kind']!=KINDS[operation][1] or not equal(want,result['report'],1e-8):return False
        if operation=='select_asof':
            filtered={**original['payload'],'rows':usable(original['payload'])}
            if canonical(result['payload'])!=canonical(filtered):return False
        elif canonical(result['payload'])!=canonical(result['report']):return False
        if receipt['quality']!=job['quality'] or receipt['independently_verified'] is not True or receipt['paper_authority'] is not False:return False
        done[receipt_key]=receipt
    if trace['operations']!=[r['operation'] for r in done.values()] or set(trace['reported_values'])!=set(job['output_fields']):return False
    for name,citation in trace['citations'].items():
        if citation['evidence'] not in done or citation['pointer']!='/result/report/'+name:return False
        if not equal(done[citation['evidence']]['result']['report'][name],trace['reported_values'][name],1e-8):return False
    return set(trace['citations'])==set(job['output_fields'])


def pointer(document,path):
    for key in path[1:].split('/'):
        key=key.replace('~1','/').replace('~0','~')
        document=document[int(key)] if isinstance(document,list) else document[key]
    return document


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan');p.add_argument('--output',type=Path,default=OUT/'verification.json')
    args=p.parse_args(argv)
    if args.output.exists():raise ValueError('Use a fresh audit output; do not overwrite historical evidence')
    plan_hash=args.plan or json.loads((OUT/'prepare_evaluation_transport_revision.json').read_text())['plan']
    store=Store(ROOT/'.quant-agent');plan=store.get(plan_hash,'tool_evaluation_plan')
    result_hash=store.control('tool_evaluation_result:'+plan_hash)
    if not result_hash:raise ValueError('Complete the campaign before auditing its outcomes')
    report=store.get(result_hash,'tool_evaluation_result');suite=store.get(plan['suite']);snapshot=store.get(plan['context'])
    training=store.get(plan['training']);training_plan=store.get(training['plan']);cases={c['id']:c for c in suite['cases']}
    episodes=report['episodes_detail'];conditions=suite['conditions'];checks={}
    checks['all_240_unique_paired_episodes']=len(episodes)==240 and Counter((e['case'],e['condition'],e['repetition']) for e in episodes)==Counter((c,k,r) for c in cases for k in conditions for r in range(2))
    schedule=[(c,k,r) for c in cases for k in conditions for r in range(2)];random.Random(suite['seed']).shuffle(schedule)
    checks['episode_order_matches_preregistered_shuffle']=[(e['case'],e['condition'],e['repetition']) for e in episodes]==schedule
    immutable=[store.get(r[0]) for r in store.db.execute("SELECT hash FROM artifacts WHERE kind='tool_evaluation_episode'")]
    checks['immutable_episode_receipts_match_export']=Counter(canonical(d['episode']) for d in immutable if d['plan']==plan_hash)==Counter(canonical(e) for e in episodes)
    checks['all_answer_keys_independently_reconstructed']=all(equal(answer(c),c['expected']) for c in cases.values())
    checks['strict_grades_match_independent_answers']=all(equal(answer(cases[e['case']]),e['answer'])==e['passed'] for e in episodes)
    traces=[e['result'] for e in episodes if e['result']]+[c['result'] for c in training['cases'] if c['result']]
    checks['all_completed_receipt_chains_independently_valid']=all(trace_valid(store,key) for key in traces)
    checks['strict_schema_and_host_answer_keys_separate']=all('expected' not in c['job'] and set(c['job']['output_fields'])==set(c['expected']) and len(c['job']['output_fields'])==len(c['expected']) for c in cases.values())
    all_practice=[store.get(r[0]) for r in store.db.execute("SELECT hash FROM artifacts WHERE kind='tool_training_plan'")]
    known={canonical(c['job']) for t in all_practice for c in t['cases']}
    checks['forty_unique_jobs_disjoint_from_every_practice_plan']=len({canonical(c['job']) for c in cases.values()})==40 and not known&{canonical(c['job']) for c in cases.values()}
    reserved=[store.get(r[0]) for r in store.db.execute("SELECT hash FROM artifacts WHERE kind='tool_evaluation_suite' AND hash!=?",(plan['suite'],))]
    checks['disjoint_from_all_prior_reserved_tool_jobs']=not {canonical(c['job']) for other in reserved for c in other['cases']}&{canonical(c['job']) for c in cases.values()}
    checks['genuine_training_before_preregistration']=training['authentic_model'] is True and training['completed_at']<plan['prepared_at'] and training_plan['model_configuration']==plan['model_configuration'] and training_plan['source_hashes']==plan['source_hashes']
    first=min(store.control('tool_task_session:'+e['session'])['created_at'] for e in episodes)
    checks['preregistered_before_first_evaluation_session']=plan['prepared_at']<first
    checks['frozen_controller_case_and_grader_sources_unchanged']=all(sha(ROOT/'src/quant_agent'/name)==value for name,value in plan['source_hashes'].items())
    checks['same_model_prices_weights_and_original_gates']=json.loads((ROOT/'config/grok.local.json').read_text())==plan['model_configuration'] and plan['weights_changed'] is False and suite['thresholds']=={'no_learning_gain':.1,'raw_logs_gain':.05,'confidence_level':.95}
    compatible=True;bound=True;memory_free=True;states=[]
    for e in episodes:
        state=store.control('tool_task_session:'+e['session']);states.append(state);job=cases[e['case']]['job']
        expected_context=[] if e['condition']=='no_learning' else snapshot['raw_context'] if e['condition']=='raw_logs' else snapshot['selected'][e['case']]
        bound &= state['calls']<=4 and len(canonical(expected_context).encode())<=1500
        compatible &= canonical(state['context'])==canonical(expected_context) and canonical(store.get(state['job']))==canonical(job)
        if e['condition']=='verified_memory':
            for record in expected_context:
                kinds=sorted(d['kind'] for d in job['documents'].values())
                compatible &= record['scope']['task_kind']==job['task_kind'] and record['scope']['original_input_kinds']==kinds
                memory_free &= not any(k in record for k in ('reported_values','claims','answer','expected','observations'))
                memory_free &= all(set(step)=={'operation','input_kind'} for step in record['verified_tool_sequence'])
    checks['identical_session_jobs_frozen_contexts_and_call_limits']=compatible and suite['max_model_calls']==4 and suite['max_output_tokens']==600 and suite['max_request_bytes']==20000
    checks['both_contexts_within_1500_bytes']=bound and len(canonical(snapshot['raw_context']).encode())<=1500
    checks['bounded_repair_policy_preserved']=all(s['repairs']<=2 and (s['status']!='finished' or s['repairs']<=1) for s in states)
    checks['selected_procedures_do_not_carry_past_numerical_answers']=memory_free
    checks['same_underlying_training_trace_comparator']=set(r['evidence'] for r in snapshot['memory'])<=set(snapshot['underlying_evidence']) and set(r['evidence'] for r in snapshot['raw_context'])<=set(snapshot['underlying_evidence'])
    facts=True
    for record in snapshot['memory']:
        signed={k:record[k] for k in ('evidence','claims','procedure','scope')}
        facts &= hashlib.sha256(canonical(signed).encode()).hexdigest()==record['id'] and trace_valid(store,record['evidence'])
        evidence=store.get(record['evidence']);job=store.get(evidence['job'])
        facts &= record['scope']['quality']==job['quality'] and record['scope']['transfer']=='procedure_only' and record['scope']['training_job']==evidence['job']
        facts &= all(canonical(pointer(evidence,c['pointer']))==canonical(c['equals']) and type(c['equals']) in (str,bool) for c in record['claims'])
    checks['memory_exact_procedure_facts_and_original_quality']=facts and set(training['memory'])=={r['id'] for r in snapshot['memory']}
    checks['no_memory_changes_during_evaluation']=all(r[0]<plan['prepared_at'] for r in store.db.execute('SELECT created FROM memory')) and snapshot['memory_updates_during_campaign'] is False
    observed={(e['case'],e['condition'],e['repetition']):int(e['passed']) for e in episodes}
    rates={k:sum(observed[c,k,r] for c in cases for r in range(2))/80 for k in conditions}
    deltas=[statistics.mean(observed[c,'verified_memory',r]-observed[c,'no_learning',r] for r in range(2)) for c in cases]
    rng=random.Random(suite['seed']);distribution=sorted(statistics.mean(rng.choices(deltas,k=40)) for _ in range(5000));lower=distribution[int(.025*4999)]
    hard=sum(e['condition']=='verified_memory' and cases[e['case']]['family'] in {'timing','exposures','decisions','execution'} and not e['passed'] for e in episodes)
    gates={'authentic_model':True,'gain_vs_no_learning':rates['verified_memory']-rates['no_learning']>=.1,
           'gain_vs_raw_logs':rates['verified_memory']-rates['raw_logs']>=.05,'positive_paired_95_lower':lower>0,'zero_hard_errors':hard==0}
    checks['independent_statistics_and_acceptance_match']=rates==report['success_rates'] and equal(lower,report['paired_95_lower']) and gates==report['gates'] and all(gates.values())==report['learning_demonstrated'] and hard==report['memory_hard_failures']
    checks['tool_completion_and_repair_counts_match']=report['model_calls']==sum(s['calls'] for s in states) and all(report['blocked_attempts'][k]==sum(s['repairs'] for e,s in zip(episodes,states) if e['condition']==k) for k in conditions) and all(report['tool_completion_rates'][k]==sum(e['result'] is not None for e in episodes if e['condition']==k)/80 for k in conditions)
    baseline=json.loads((OUT/'source_baseline.json').read_text())['files']
    protected={name:value for name,value in baseline.items() if name.startswith(('src/quant_agent/','tests/')) and Path(name).name not in {'agent.py','cli.py','models.py'}}
    checks['prior_modules_and_graders_unchanged']=all(sha(ROOT/name)==value for name,value in protected.items())
    checks['prechange_source_copies_match_baseline']=all(sha(OUT/'source_before'/name)==value for name,value in baseline.items() if name.startswith(('src/quant_agent/','tests/')))
    original_model=(OUT/'source_before/src/quant_agent/models.py').read_text()
    limited_patch=original_model.replace('from urllib.error import HTTPError, URLError\n','from urllib.error import HTTPError, URLError\nfrom http.client import HTTPException\n').replace('except (TimeoutError, URLError):','except (OSError, HTTPException):')
    checks['provider_patch_only_normalizes_transport_exceptions']=(ROOT/'src/quant_agent/models.py').read_text()==limited_patch
    failed=OUT/'failed_training_v1';failed_pin=json.loads((failed/'TRAINING_PREREGISTRATION.json').read_text())['payload']
    checks['failed_training_and_pinned_source_preserved']=all(sha(failed/'source'/name)==value for name,value in failed_pin['source_hashes'].items()) and json.loads((failed/'TRAINING_RESULT.json').read_text())['passed']==0
    retired=OUT/'retired_connection_campaign';retirement=json.loads((retired/'RETIREMENT.json').read_text());retired_plan=store.get(retirement['plan'])
    checks['partial_connection_campaign_preserved_and_retired']=retirement['completed_episodes']==139 and retirement['learning_demonstrated'] is False and store.control('tool_evaluation_retired:'+retirement['plan'])==retirement['receipt'] and store.control('tool_evaluation_used:'+retirement['plan']) is True and all(sha(retired/'source'/name)==value for name,value in retired_plan['source_hashes'].items())
    checks['retired_campaign_not_replayed_or_rescored']=len([d for d in immutable if d['plan']==retirement['plan']])==139 and store.control('tool_evaluation_result:'+retirement['plan']) is None and 'retired' in json.loads((OUT/'retired_replay_rejection.json').read_text())['error']
    legacy=json.loads((ROOT/'results/agent_v1/legacy_baseline.json').read_text())
    checks['all_181_original_files_unchanged']=len(legacy)==181 and all(sha(ROOT/name)==value for name,value in legacy.items())
    preserved=json.loads((ROOT/'results/learning_revision_2026-10-11/evidence_manifest.json').read_text())['files']
    preserved={name:value for name,value in preserved.items() if not name.startswith(('src/quant_agent/','tests/','docs/')) and name!='README.md'}
    checks['prior_result_files_and_data_audit_unchanged']=all(sha(ROOT/name)==value for name,value in preserved.items())
    checks['prior_learning_controls_preserved']=store.control('first_episode_learning:'+SOURCE)==OLD and store.control('learning_revision_result:dcf4e8a36449bbb58f5d3fc32dcb8dd85b6941bfc08e3be6a643d8f062728389')==OLD_V2
    run=store.run(SOURCE)
    checks['original_rejected_strategy_run_unchanged']=run['state']=='finished' and run['result']=='79c012dc9b8047c505d5202287a7888752d79fcd4c538105abd36171283d0050' and run['challenge']=='0abe828db27a5f39958efd6ed7d61737f79ba03449bb09e4c159df0b968b0cf3' and run['decision']=='87bd4542c0ce8211e24f2aaa6e77fafea7f76d5081d24ecf0ece1bac895ff449'
    directory=ROOT/'data/agent_imports/alpaca_proxy_20261010';manifest=json.loads((directory/'manifest.json').read_text())
    checks['frozen_seven_table_proxy_unchanged']=hashlib.sha256(canonical(manifest).encode()).hexdigest()==store.get(run['result'])['dataset_id'] and all(sha(directory/d['path'])==d['sha256'] for d in manifest['files'].values())
    raw=ROOT/'data/alpaca_snapshots/20261010T140939.395972Z';raw_manifest=json.loads((raw/'manifest.json').read_text())
    checks['raw_snapshot_unchanged']=all(sha(raw/name)==value for name,value in raw_manifest['files'].items())
    phases=[dict(row) for row in store.db.execute('SELECT campaign,count(*) calls,sum(coalesce(actual,amount)) used FROM reservations GROUP BY campaign')]
    caps={row['campaign']:row['cap'] for row in store.db.execute('SELECT * FROM budgets')}
    checks['original_phase_and_aggregate_caps']=caps=={'v1-smoke':5,'v1-research-demo':10,'v1-benchmark':35} and sum(p['used'] for p in phases)<=50 and all(p['used']<=caps[p['campaign']] for p in phases)
    usage=[json.loads(row[0]) for row in store.db.execute("SELECT payload FROM events WHERE kind='model_usage'")]
    unknown=[dict(row) for row in store.db.execute("SELECT campaign,amount,status,created FROM reservations WHERE actual IS NULL")]
    checks['genuine_provider_usage_and_unknown_billing_match_reservations']=len(usage)+len(unknown)==sum(p['calls'] for p in phases) and all(u['served_model']==plan['model_configuration']['model'] for u in usage) and all(u['status']=='unknown' and u['amount']>0 for u in unknown)
    checks['provider_token_prices_independently_match_cost']=all(equal((u['input_tokens']*plan['model_configuration']['input_per_million']+u['output_tokens']*plan['model_configuration']['output_per_million'])/1e6,u['cost'],1e-10) for u in usage)
    checks['private_env_permissions_preserved']=(ROOT/'.env').stat().st_mode&0o777==0o600
    checks['no_broker_releases_intents_executions_or_paper_authority']=all(store.db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0 for table in ('releases','intents','executions')) and report['paper_eligible'] is False and plan['paper_authority'] is False
    families={family:{k:sum(e['passed'] for e in episodes if cases[e['case']]['family']==family and e['condition']==k) for k in conditions} for family in sorted({c['family'] for c in cases.values()})}
    family_deltas=[(counts['verified_memory']-counts['no_learning'])/10 for counts in families.values()]
    diagnostic_rng=random.Random(suite['seed']+777)
    clustered=sorted(statistics.mean(diagnostic_rng.choices(family_deltas,k=8)) for _ in range(5000))
    diagnostics={'family_cluster_bootstrap_95_lower':clustered[int(.025*4999)],'clusters':8,
        'cost_by_condition':{k:sum(e['cost'] for e in episodes if e['condition']==k) for k in conditions},
        'calls_by_condition':{k:sum(e['calls'] for e in episodes if e['condition']==k) for k in conditions},
        'largest_possible_gain_over_no_context':1-rates['no_learning'],
        'limits':'Known template families, two repetitions and correlated workflows limit generalization. Family bootstrap is diagnostic only and does not alter the preregistered task-bootstrap gates.'}
    result={'status':'passed' if all(checks.values()) else 'failed','checks':checks,'passed':sum(checks.values()),'total':len(checks),
        'plan':plan_hash,'evaluation':result_hash,'genuine_episodes':240,'genuine_evaluation_calls':report['model_calls'],
        'rates':rates,'gates':gates,'learning_demonstrated':report['learning_demonstrated'],'memory_hard_failures':hard,
        'family_correct_out_of_10':families,'diagnostics':diagnostics,'budget_phases':phases,'uncertain_billing_reservations':unknown,'total_configured_price_estimate':sum(p['used'] for p in phases),
        'scope':'Independent engineering audit; synthetic workflow competence is not investing alpha or data/broker qualification.',
        'paper_eligible':False}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));store.close();return 0 if result['status']=='passed' else 2


if __name__=='__main__':raise SystemExit(main())
