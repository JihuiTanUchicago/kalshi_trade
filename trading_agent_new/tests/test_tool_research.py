"""Protected calculations and task loops; every provider in this file is a fixture."""
from copy import deepcopy
from http.client import RemoteDisconnected
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from quant_agent.agent import ResearchAgent
from quant_agent.analysis_tools import run_tool
from quant_agent.common import GateError,canonical,digest
from quant_agent.contracts import Action,ModelResponse
from quant_agent.evaluation import equal_answer
from quant_agent.fixtures import make_fixture
from quant_agent.models import ReplayModel,HTTPModel,ProviderError,Budget
from quant_agent.procedural_memory import remember_trace,task_context,verify_trace
from quant_agent.store import Store
from quant_agent.task_agent import act,execute_session,make_request,prepare_session,validate_job
from quant_agent.task_verification import verify
from quant_agent.tool_cases import cases
from quant_agent.tool_evaluation import prepare_training,train,prepare,preflight,run


class PlannerFixture:
    name='scripted-tool-planner'
    def __init__(self):self.calls=0
    def generate(self,request):
        self.calls+=1;data=json.loads(request.messages[-1]['content']);wanted=data['job']['output_fields'];receipts=data['receipts']
        references={name:{'receipt':r['handle'],'pointer':'/'+name} for name in wanted for r in receipts if name in r['report']}
        if len(references)==len(wanted):action={'tool':'finish','arguments':{'fields':references}}
        else:
            sources=[(r['handle'],r['kind']) for r in receipts]+[(h,d['kind']) for h,d in data['job']['documents'].items()]
            selected=None
            for handle,kind in sources:
                for operation,description in data['tools'].items():
                    if description['input_kind']==kind:
                        selected={'tool':operation,'arguments':{'input':handle}};break
                if selected:break
            action=selected
        return ModelResponse(json.dumps(action),100,80,{'fixture':True,'served_model':'fixture'})


class ToolResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.store=Store(self.root/'state');self.addCleanup(self.store.close)
        self.config={'adapter':'chat_completions','endpoint':'http://localhost:9999','model':'fixture','api_key_env':'FIXTURE_KEY',
                     'local_no_auth':True,'input_per_million':1.25,'output_per_million':2.5}
        for kind in ('json','workflow'):
            self.store.put('adapter_smoke',{'passed':True,'case':kind,'configuration':digest(self.config),'real_request':True,'test_fixture':True})

    def case(self,family):return next(c for c in cases() if c['family']==family)

    def session(self,family):
        case=self.case(family);session=prepare_session(self.store,case['job'])
        return case,session

    def training(self):
        p=prepare_training(self.store,self.config,self.root/'training')
        result=train(self.store,p['plan'],self.config,PlannerFixture())
        self.assertEqual(result['passed'],8);return p,result

    def prepared(self):
        training,_=self.training();p=prepare(self.store,training['plan'],self.config,self.root/'evaluation')
        return p

    def test_all_new_cases_complete_with_independently_verified_tool_values(self):
        planner=PlannerFixture()
        for case in cases():
            session=prepare_session(self.store,case['job']);result=execute_session(self.store,session,planner)
            self.assertTrue(equal_answer(case['expected'],result['reported_values']),case['id'])
            self.assertFalse(result['alpha_claim']);self.assertFalse(result['paper_eligible'])
            verify_trace(self.store,result['receipt'])

    def test_actual_timestamp_offsets_filter_future_effective_and_late_rows(self):
        _,session=self.session('timing');job=self.store.get(self.store.control('tool_task_session:'+session)['job'])
        handle=next(iter(job['documents']));answer=act(self.store,session,Action('select_asof',{'input':handle}))
        self.assertEqual(len(answer['report']['usable_ids']),4)
        self.assertTrue(all('late' not in v and 'future' not in v for v in answer['report']['usable_ids']))
        self.assertEqual(len(answer['payload']['rows']),4)

    def test_public_actions_bind_literal_handles_and_report_phase_without_past_payloads(self):
        case,session=self.session('features');handle=next(iter(case['job']['documents']))
        first=json.loads(make_request(self.store,session).messages[-1]['content'])
        self.assertEqual(first['phase'],'calculate')
        self.assertEqual(first['allowed_actions'][0]['arguments_schema']['properties']['input']['enum'],[handle])
        act(self.store,session,Action('select_asof',{'input':handle}))
        middle=json.loads(make_request(self.store,session).messages[-1]['content'])
        self.assertEqual([a['tool'] for a in middle['allowed_actions']],['holding_return'])
        self.assertEqual(middle['allowed_actions'][0]['arguments_schema']['properties']['input']['enum'],['r1'])
        self.assertNotIn('payload',middle['receipts'][0])
        act(self.store,session,Action('holding_return',{'input':'r1'}))
        final=json.loads(make_request(self.store,session).messages[-1]['content'])
        self.assertEqual(final['phase'],'report');self.assertEqual([a['tool'] for a in final['allowed_actions']],['finish'])
        fields=final['allowed_actions'][0]['arguments_schema']['properties']['fields']['properties']
        self.assertEqual(fields['total_return']['properties']['receipt']['enum'],['r2'])
        self.assertNotIn('"expected":',canonical(final))

    def test_return_cannot_bypass_host_produced_asof_history(self):
        case,session=self.session('features');handle=next(iter(case['job']['documents']))
        with self.assertRaisesRegex(GateError,'input kind'):act(self.store,session,Action('holding_return',{'input':handle}))
        forged=deepcopy(case['job']);forged['documents'][handle]['kind']='asof_history'
        with self.assertRaisesRegex(GateError,'host-produced'):validate_job(forged)

    def test_short_paid_and_unpaid_dividends_match_hand_cash_and_nav(self):
        payload={'opening_shares':-10,'opening_price':100,'ending_price':46.5,'events':[{'split':2,'dividend':1.5,'paid':True},{'split':1,'dividend':2,'paid':False}]}
        result=run_tool('account_actions','action_account',payload)
        self.assertEqual(result['report'],{'ending_shares':-20,'cash_change':-30.,'unpaid_dividend_claim':-40.,'nav_change':0.})
        verify('account_actions',payload,result)

    def test_nonfinite_boolean_money_fractional_splits_and_overrides_refused(self):
        c=self.case('corporate_actions');x=deepcopy(next(iter(c['job']['documents'].values()))['payload'])
        for bad in (True,float('nan'),float('inf')):
            y=deepcopy(x);y['opening_price']=bad
            with self.assertRaises(GateError):run_tool('account_actions','action_account',y)
        x['opening_shares']=1;x['events'][0]['split']=1.5
        with self.assertRaisesRegex(GateError,'Fractional'):run_tool('account_actions','action_account',x)
        c=self.case('decisions');x=deepcopy(next(iter(c['job']['documents'].values()))['payload']);x['minimum_sharpe_gain']=0
        with self.assertRaisesRegex(GateError,'fields'):run_tool('apply_research_gates','research_evidence',x)

    def test_qualified_flag_cannot_upgrade_actual_proxy_inputs(self):
        job=deepcopy(self.case('decisions')['job']);job['quality']='proxy'
        with self.assertRaisesRegex(GateError,'qualification'):validate_job(job)

    def test_conflicting_fills_and_inconsistent_filled_status_pause_without_submission(self):
        for executions,status in (([{'id':'a','quantity':3},{'id':'a','quantity':4}],'unknown'),([{'id':'a','quantity':3}],'filled')):
            result=run_tool('reconcile_fills','execution_snapshot',{'requested_quantity':10,'status':status,'executions':executions})
            self.assertEqual(result['report'],{'next_action':'pause','filled_quantity':3,'resubmit':False})
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM intents').fetchone()[0],0)

    def test_inputs_cannot_be_rewritten_and_finish_cannot_guess_or_relabel_values(self):
        case,session=self.session('exposures');handle=next(iter(case['job']['documents']))
        with self.assertRaises(GateError):act(self.store,session,Action('summarize_exposure',{'input':handle,'nav':1}))
        with self.assertRaises(GateError):act(self.store,session,Action('exec',{'input':handle}))
        a=act(self.store,session,Action('summarize_exposure',{'input':handle}));b=act(self.store,session,Action('summarize_exposure',{'input':handle}))
        self.assertEqual(a['evidence'],b['evidence']);self.assertEqual(len(self.store.control('tool_task_session:'+session)['receipts']),1)
        with self.assertRaises(GateError):act(self.store,session,Action('finish',{'fields':{k:0 for k in case['job']['output_fields']}}))
        fields={k:{'receipt':'r1','pointer':'/'+k} for k in case['job']['output_fields']};fields['free_cash']['pointer']='/gross_weight'
        with self.assertRaisesRegex(GateError,'same named'):act(self.store,session,Action('finish',{'fields':fields}))

    def test_one_repair_and_call_allowance_survive_failed_resume(self):
        _,session=self.session('timing');bad={'tool':'exec','arguments':{'input':'anything'}}
        with self.assertRaisesRegex(GateError,'bounded'):execute_session(self.store,session,ReplayModel([bad,bad]))
        state=self.store.control('tool_task_session:'+session);self.assertEqual(state['calls'],2);self.assertEqual(state['repairs'],2)
        with self.assertRaisesRegex(GateError,'reset'):execute_session(self.store,session,ReplayModel([]))

    def test_remote_disconnect_is_sanitized_and_charged_within_bounded_task_recovery(self):
        case,session=self.session('timing');provider=HTTPModel(self.config)
        with patch('quant_agent.models.urlopen',side_effect=RemoteDisconnected('private transport detail')):
            with self.assertRaisesRegex(ProviderError,'network_or_timeout') as caught:
                provider.generate(make_request(self.store,session))
        self.assertNotIn('private',str(caught.exception));planner=PlannerFixture()
        class DisconnectOnce:
            name='fixture-disconnecting-model'
            calls=0
            def generate(inner,request):
                inner.calls+=1
                if inner.calls==1:
                    with patch('quant_agent.models.urlopen',side_effect=RemoteDisconnected('private transport detail')):
                        return provider.generate(request)
                return planner.generate(request)
        from quant_agent.tool_evaluation import metered
        result=execute_session(self.store,session,metered(self.store,DisconnectOnce(),self.config,'v1-research-demo',session))
        self.assertTrue(equal_answer(case['expected'],result['reported_values']))
        self.assertEqual(result['calls'],3);self.assertEqual(result['repairs'],1)
        unknown=self.store.db.execute('SELECT amount,actual,status FROM reservations WHERE actual IS NULL').fetchall()
        self.assertEqual(len(unknown),1);self.assertEqual(unknown[0]['status'],'unknown')
        self.assertGreaterEqual(Budget(self.store,'v1-research-demo',10).used(),unknown[0]['amount'])

    def test_reopen_retains_verified_dependencies_and_cached_finish(self):
        case,session=self.session('features');handle=next(iter(case['job']['documents']))
        first=act(self.store,session,Action('select_asof',{'input':handle}))
        self.store.close();self.store=Store(self.root/'state');self.addCleanup(self.store.close)
        planner=PlannerFixture();result=execute_session(self.store,session,planner)
        self.assertEqual(planner.calls,2);self.assertTrue(equal_answer(case['expected'],result['reported_values']))
        self.assertEqual(self.store.control('tool_task_session:'+session)['receipts'][0],first['evidence'])
        cached=execute_session(self.store,session,ReplayModel([]));self.assertEqual(cached['receipt'],result['receipt'])

    def test_procedural_memory_transfers_verified_chain_without_old_numbers(self):
        case,session=self.session('features');result=execute_session(self.store,session,PlannerFixture());memory=remember_trace(self.store,result['receipt'])
        future=cases(seed=2026101129)[5]['job'];context=task_context(self.store,future)
        self.assertTrue(context);self.assertEqual(context[0]['memory_id'],memory)
        self.assertEqual([s['operation'] for s in context[0]['verified_tool_sequence']],['select_asof','holding_return'])
        self.assertNotIn('reported_values',canonical(context));self.assertNotIn(str(result['reported_values']['total_return']),canonical(context))
        self.assertEqual(task_context(self.store,self.case('execution')['job']),[])
        self.assertLessEqual(len(canonical(context).encode()),1500)

    def test_independent_receipt_tamper_is_not_a_verified_procedure(self):
        case,session=self.session('exposures');result=execute_session(self.store,session,PlannerFixture())
        trace=self.store.get(result['receipt']);fake=deepcopy(trace);fake['reported_values']['free_cash']+=5
        key=self.store.put('operational_check',fake)
        with self.assertRaisesRegex(GateError,'differs'):remember_trace(self.store,key)

    def test_disjoint_training_cases_and_frozen_contracts(self):
        training=cases(2026101101,True);evaluation=cases()
        self.assertFalse({digest(c['job']) for c in training}&{digest(c['job']) for c in evaluation})
        self.assertEqual(len({digest(c['job']) for c in evaluation}),40)
        p=self.prepared();plan=self.store.get(p['plan']);suite=self.store.get(plan['suite'])
        self.assertEqual(suite['thresholds'],{'no_learning_gain':.1,'raw_logs_gain':.05,'confidence_level':.95})
        self.assertEqual(suite['max_model_calls'],4);self.assertTrue(preflight(self.store,p['plan'],self.config)['can_run'])
        with patch('quant_agent.tool_evaluation.source_hashes',return_value={}):
            with self.assertRaisesRegex(GateError,'frozen'):preflight(self.store,p['plan'],self.config)
        for c in suite['cases']:
            session=prepare_session(self.store,c['job']);self.assertNotIn('"expected":',make_request(self.store,session).messages[-1]['content'])

    def test_full_fixture_study_cannot_claim_genuine_learning_or_rebill_replay(self):
        p=self.prepared();report=run(self.store,p['plan'],self.config,PlannerFixture())
        self.assertEqual(report['episodes'],240);self.assertEqual(report['model_calls'],510)
        self.assertEqual(report['success_rates'],{'no_learning':1.,'raw_logs':1.,'verified_memory':1.})
        self.assertFalse(report['gates']['authentic_model']);self.assertFalse(report['learning_demonstrated'])
        before=self.store.db.execute('SELECT count(*) FROM reservations').fetchone()[0]
        cached=run(self.store,p['plan'],self.config,ReplayModel([]));self.assertEqual(report['receipt'],cached['receipt'])
        self.assertEqual(before,self.store.db.execute('SELECT count(*) FROM reservations').fetchone()[0])

    def test_partial_campaign_cannot_reset_consumption(self):
        p=self.prepared();self.store.set_control('tool_evaluation_used:'+p['plan'],True)
        with self.assertRaisesRegex(GateError,'retired'):run(self.store,p['plan'],self.config,ReplayModel([]))

    def test_training_and_evaluation_cannot_silently_change_foundation_or_source(self):
        training,_=self.training()
        with patch('quant_agent.tool_evaluation.source_hashes',return_value={}):
            with self.assertRaisesRegex(GateError,'frozen'):prepare(self.store,training['plan'],self.config,self.root/'invalid')
            with self.assertRaisesRegex(GateError,'Consumed'):prepare_training(self.store,self.config,self.root/'invalid')

    def test_core_research_analysis_keeps_state_risk_and_dataset_binding(self):
        data=make_fixture(self.root/'fixture');run=self.store.new_run('analyze scoped data');agent=ResearchAgent(self.store,data)
        job=deepcopy(self.case('timing')['job']);job.update(dataset_id=data.id,quality=data.quality,research_run=run)
        key=self.store.put('tool_task_job',job);handle=next(iter(job['documents']))
        out=agent.act(run,Action('analyze',{'job':key,'operation':'select_asof','input':handle}))
        self.assertTrue(out['independently_verified']);self.assertEqual(self.store.run(run)['state'],'requested')
        job['dataset_id']='wrong';other=self.store.put('tool_task_job',job)
        with self.assertRaisesRegex(GateError,'dataset'):agent.act(run,Action('analyze',{'job':other,'operation':'select_asof','input':handle}))


if __name__=='__main__':unittest.main()
