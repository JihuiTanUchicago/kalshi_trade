"""Independent audit of frozen revised-learning evidence; makes no model calls."""
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

from quant_agent.common import canonical
from quant_agent.store import Store

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/learning_revision_2026-10-11'
PLAN='dcf4e8a36449bbb58f5d3fc32dcb8dd85b6941bfc08e3be6a643d8f062728389'
SOURCE='ff68fae9bfcf4801807b1477e197742a'
OLD='bf2f3ccffd66f3bfcf37878465d18ee9b17f1c56093c95015b7a04c84f567808'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def equal(want,got):
    if isinstance(want,dict):
        return isinstance(got,dict) and got.keys()==want.keys() and all(equal(v,got[k]) for k,v in want.items())
    if type(want) in (int,float):
        return type(got) in (int,float) and math.isfinite(got) and math.isclose(want,got,rel_tol=0,abs_tol=1e-6*max(1,abs(want)))
    return type(want) is type(got) and want==got


def recompute(case):
    """Reconstruct answers from the supplied task, without importing its generator."""
    family=case['family'];x=case['prompt']['inputs']
    if family=='timing':
        at=datetime.fromisoformat(x['decision_at'])
        return {'usable_ids':sorted(r['id'] for r in x['rows'] if all(datetime.fromisoformat(r[k])<=at for k in ('effective_at','available_at')))}
    if family=='features':
        starting=x['initial_shares']*x['raw_closes'][0]
        ending_shares=x['initial_shares']*x['split_before_first_interval_close']
        ending_value=ending_shares*x['raw_closes'][-1]+sum(ending_shares*d for d in x['dividend_per_post_split_share'])
        return {'ending_shares':ending_shares,'total_return':ending_value/starting-1}
    if family=='corporate_actions':
        ending=x['opening_shares']*x['split'];claim=ending*x['dividend_per_post_split_share']
        cash=claim if x['dividend_paid'] else 0;unpaid=claim-cash
        change=ending*x['ending_raw_price']+cash+unpaid-x['opening_shares']*x['opening_raw_price']
        return {'ending_shares':ending,'cash_change':cash,'unpaid_dividend_claim':unpaid,'nav_change':change}
    if family=='controlled_experiments':
        differences=sorted(k for k,v in x['baseline'].items() if x['candidate'][k]!=v)
        return {'comparable':not differences,'mismatched_assumptions':differences}
    if family=='cost_attribution':
        net=x['candidate_net_sharpe']-x['baseline_net_sharpe'];gross=x['candidate_cost_free_sharpe']-x['baseline_cost_free_sharpe']
        return {'net_gain':net,'cost_free_gain':gross,'modeled_cost_contribution':net-gross,
                'turnover_change':(x['candidate_traded_notional']-x['baseline_traded_notional'])/x['average_nav']}
    if family=='exposures':
        values=x['signed_position_market_values']
        return {'gross_weight':sum(map(abs,values))/x['nav'],'net_weight':sum(values)/x['nav'],
                'free_cash':x['cash_balance_including_short_proceeds']-x['restricted_short_collateral']-x['unpaid_short_dividend_obligation']}
    if family=='decisions':
        valid=(x['sharpe_gain']>=x['minimum_sharpe_gain'] and x['paired_95_lower']>0 and x['double_cost_gain']>0
               and x['drawdown_deterioration']<=x['maximum_drawdown_deterioration'] and x['verification_passed']
               and x['bootstrap_samples']>=x['minimum_bootstrap_samples'] and x['blocks']>=x['minimum_blocks'])
        return {'decision':'reject' if not valid else 'advance_to_paper_qualification' if x['qualified_data'] else 'revise_data_qualification'}
    if family=='execution':
        seen={};conflict=False
        for execution in x['executions']:
            if execution['id'] in seen:
                conflict |= seen[execution['id']]!=execution['quantity']
            else:seen[execution['id']]=execution['quantity']
        action='pause' if conflict else {'unknown':'reconcile','cancel_pending':'reconcile','acknowledged':'wait','filled':'closed'}[x['intent_status']]
        return {'next_action':action,'resubmit':False,'filled_quantity':sum(seen.values())}
    raise ValueError('Unknown task family')


def main():
    store=Store(ROOT/'.quant-agent');checks={};plan=store.get(PLAN,'learning_revision_plan')
    result_hash=store.control('learning_revision_result:'+PLAN)
    if not result_hash:raise ValueError('Complete the genuine campaign before its audit')
    report=store.get(result_hash,'learning_revision_evaluation');suite=store.get(plan['suite']);snapshot=store.get(plan['context'])
    cases={c['id']:c for c in suite['cases']};episodes=report['episodes_detail'];conditions=suite['conditions']
    checks['all_240_unique_paired_episodes']=len(episodes)==240 and Counter((e['case'],e['condition'],e['repetition']) for e in episodes)==Counter((c,k,r) for c in cases for k in conditions for r in range(2))
    artifact_matches=store.db.execute("SELECT hash FROM artifacts WHERE kind='learning_revision_episode'").fetchall()
    stored=[store.get(row[0]) for row in artifact_matches]
    checks['immutable_episode_receipts_match_export']=Counter(canonical(d['episode']) for d in stored if d['plan']==PLAN)==Counter(canonical(e) for e in episodes)
    checks['answers_independently_reconstructed']=all(equal(c['expected'],recompute(c)) for c in cases.values())
    checks['strict_grades_match_reconstruction']=all(equal(recompute(cases[e['case']]),e['answer'])==e['passed'] for e in episodes)
    checks['unchanged_improvement_thresholds']=suite['thresholds']=={'no_learning_gain':.1,'raw_logs_gain':.05,'confidence_level':.95}
    checks['all_conditions_same_explicit_contract']=all('output_schema' in c['prompt'] and 'units' in c['prompt'] for c in cases.values()) and all('expected' not in c['prompt'] for c in cases.values())
    previous=store.get(plan['retired_original_evaluation']);old_suite=store.get(previous['suite']) if 'suite' in previous else store.get('c32c142428fea4904d243f27c1939aef273f4aba8948d1fa74ff7b8df07e1e66')
    checks['no_original_prompt_reuse']=not ({canonical(c['prompt']) for c in old_suite['cases']} & {canonical(c['prompt']) for c in cases.values()})
    checks['original_result_control_preserved']=store.control('first_episode_learning:'+SOURCE)==OLD and previous['success_rates']=={'no_learning':.2375,'raw_logs':.225,'verified_memory':.2125}
    expected_hashes=plan['source_hashes']
    checks['frozen_evaluation_sources_unchanged']=all(sha(ROOT/'src/quant_agent'/name)==value for name,value in expected_hashes.items())
    checks['model_prices_config_unchanged']=json.loads((ROOT/'config/grok.local.json').read_text())==plan['model_configuration']
    first_created=min(row[0] for row in store.db.execute("SELECT created FROM artifacts WHERE kind='learning_revision_episode'"))
    checks['preregistered_before_first_result']=plan['prepared_at']<first_created
    observed={(e['case'],e['condition'],e['repetition']):int(e['passed']) for e in episodes}
    rates={k:sum(observed[c,k,r] for c in cases for r in range(2))/80 for k in conditions}
    deltas=[statistics.mean(observed[c,'verified_memory',r]-observed[c,'no_learning',r] for r in range(2)) for c in cases]
    rng=random.Random(suite['seed']);sample=sorted(statistics.mean(rng.choices(deltas,k=40)) for _ in range(5000))
    lower=sample[int(.025*4999)]
    hard=sum(e['condition']=='verified_memory' and e['case'].split('-v2-')[0] in {'timing','exposures','decisions','execution'} and not e['passed'] for e in episodes)
    gates={'authentic_model':True,'gain_vs_no_learning':rates['verified_memory']-rates['no_learning']>=.1,
           'gain_vs_raw_logs':rates['verified_memory']-rates['raw_logs']>=.05,'positive_paired_95_lower':lower>0,'zero_hard_errors':hard==0}
    checks['statistics_gates_independently_match']=rates==report['success_rates'] and equal(lower,report['paired_95_lower']) and gates==report['gates'] and all(gates.values())==report['learning_demonstrated']
    checks['context_byte_bounds']=len(canonical(snapshot['raw_context']).encode())<=4000 and all(len(canonical(v).encode())<=4000 for v in snapshot['selected_memory'].values())
    checks['same_underlying_evidence_comparator']=set(r['evidence'] for r in snapshot['memory'])<=set(snapshot['underlying_evidence']) and set(r['evidence'] for r in snapshot['raw_context'] if 'evidence' in r)<=set(snapshot['underlying_evidence'])
    facts_valid=True
    for record in snapshot['memory']:
        signed={k:record[k] for k in ('evidence','claims','procedure','scope')}
        facts_valid &= hashlib.sha256(canonical(signed).encode()).hexdigest()==record['id']
        evidence=store.get(record['evidence'])
        for claim in record['claims']:
            value=evidence
            for segment in claim['pointer'][1:].split('/'):
                name=segment.replace('~1','/').replace('~0','~')
                value=value[int(name)] if isinstance(value,list) else value[name]
            facts_valid &= canonical(value)==canonical(claim['equals']) and not isinstance(value,(dict,list))
        facts_valid &= record['scope']['quality']=='proxy' and record['scope']['market']=='US' and record['scope']['frequency']=='daily'
    checks['memory_exact_facts_and_original_scope']=facts_valid and len(snapshot['memory'])==6
    checks['no_memory_learning_during_campaign']=all(row[0]<plan['prepared_at'] for row in store.db.execute("SELECT created FROM memory"))
    old_manifest=json.loads((OUT/'source_baseline.json').read_text())
    protected={name:value for name,value in old_manifest['files'].items() if name.startswith('tests/test_') and name!='tests/test_learning_revision.py' or name.startswith('src/quant_agent/') and Path(name).name not in {'memory.py','agent.py','cli.py'}}
    checks['protected_original_modules_unchanged']=all(sha(ROOT/name)==value for name,value in protected.items())
    legacy=json.loads((ROOT/'results/agent_v1/legacy_baseline.json').read_text())
    checks['all_181_legacy_files_unchanged']=len(legacy)==181 and all(sha(ROOT/name)==value for name,value in legacy.items())
    preserved=json.loads((ROOT/'results/ordered_integration_2026-10-10/evidence_manifest.json').read_text())['files']
    preserved={name:value for name,value in preserved.items() if not name.startswith(('src/quant_agent/','tests/','docs/')) and name!='README.md'}
    checks['prior_research_outputs_unchanged']=all(sha(ROOT/name)==value for name,value in preserved.items())
    directory=ROOT/'data/agent_imports/alpaca_proxy_20261010';manifest=json.loads((directory/'manifest.json').read_text())
    checks['frozen_import_and_seven_tables_unchanged']=hashlib.sha256(canonical(manifest).encode()).hexdigest()==store.get(store.run(SOURCE)['result'])['dataset_id'] and all(sha(directory/d['path'])==d['sha256'] for d in manifest['files'].values())
    raw_directory=ROOT/'data/alpaca_snapshots/20261010T140939.395972Z';raw_manifest=json.loads((raw_directory/'manifest.json').read_text())
    checks['original_raw_snapshot_unchanged']=all(sha(raw_directory/name)==value for name,value in raw_manifest['files'].items())
    phases=[dict(row) for row in store.db.execute('SELECT campaign,count(*) calls,sum(coalesce(actual,amount)) used FROM reservations GROUP BY campaign')]
    caps={row['campaign']:row['cap'] for row in store.db.execute('SELECT * FROM budgets')}
    checks['original_phase_and_aggregate_caps']=caps=={'v1-smoke':5,'v1-research-demo':10,'v1-benchmark':35} and sum(p['used'] for p in phases)<=50 and all(p['used']<=caps[p['campaign']] for p in phases)
    genuine_calls=store.db.execute("SELECT count(*) FROM events WHERE kind='model_usage'").fetchone()[0]
    checks['genuine_call_usage_receipts']=genuine_calls==sum(p['calls'] for p in phases) and all(e['served_model'] for e in episodes)
    checks['no_releases_or_order_intents']=all(store.db.execute('SELECT count(*) FROM '+name).fetchone()[0]==0 for name in ('releases','intents','executions')) and report['paper_eligible'] is False
    families={family:{k:sum(e['passed'] for e in episodes if cases[e['case']]['family']==family and e['condition']==k) for k in conditions} for family in sorted({c['family'] for c in cases.values()})}
    receipt={'status':'passed' if all(checks.values()) else 'failed','checks':checks,'passed':sum(checks.values()),'total':len(checks),
             'plan':PLAN,'evaluation':result_hash,'episodes':240,'rates':rates,'gates':gates,'learning_demonstrated':report['learning_demonstrated'],
             'family_correct_out_of_10':families,'budget_phases':phases,'total_configured_price_estimate':sum(p['used'] for p in phases),
             'scope':'Engineering audit does not override failed learning, economic, qualification or broker gates; task scenarios are synthetic.',
             'paper_eligible':False}
    (OUT/'verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2));store.close()
    return 0 if receipt['status']=='passed' else 2


if __name__=='__main__':raise SystemExit(main())
