"""Revised evaluation contracts; every model in this file is an offline fixture."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_first_episode as episode_fixtures
from quant_agent.common import GateError, canonical, digest
from quant_agent.contracts import ModelResponse
from quant_agent.evaluation import prepare_suite
from quant_agent.learning_revision import prepare, preflight, requests, run, schema_valid, status
from quant_agent.memory_consolidation import consolidate
from quant_agent.memory_selection import checked_record, select_records
from quant_agent.models import ReplayModel
from quant_agent.research_cases_v2 import build_cases


class LearningRevisionTests(unittest.TestCase):
    def setUp(self):
        fixture=episode_fixtures.FirstEpisodeTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.store=fixture.store;self.root=fixture.root;self.config=fixture.config
        self.first=fixture.completed_fixture();self.source=self.store.run(self.first['run'])

    def proposal(self):
        result='result'
        return {'findings':[
            {'procedure':'cost_attribution','evidence':result,'claims':[{'pointer':'/comparison/sharpe_gain'},{'pointer':'/no_cost_sharpe_gain'}]},
            {'procedure':'notional_turnover','evidence':result,'claims':[{'pointer':'/metrics/candidate_1/annualized_turnover'},{'pointer':'/metrics/baseline_1/annualized_turnover'}]},
            {'procedure':'uncertainty','evidence':result,'claims':[{'pointer':'/comparison/lower_95_one_sided'}]}]}

    def consolidated(self):
        return consolidate(self.store,self.source['id'],ReplayModel([self.proposal()]))

    def prepared(self):
        self.consolidated()
        return prepare(self.store,self.source['id'],self.config,self.root/'revision')

    def test_consolidation_copies_exact_facts_and_resume_never_calls_twice(self):
        a=self.consolidated();self.assertEqual(a['observations'],5)
        self.assertEqual(a['source_quality_preserved'],'synthetic')
        self.assertFalse(a['alpha_claim'])
        b=consolidate(self.store,self.source['id'],ReplayModel([]));self.assertEqual(a['receipt'],b['receipt'])
        for row in self.store.db.execute("SELECT payload FROM memory WHERE status='verified'"):
            self.assertTrue(checked_record(self.store,json.loads(row[0]))['observations'])

    def test_invalid_consolidation_does_not_write_partial_findings(self):
        before=self.store.db.execute('SELECT COUNT(*) FROM memory').fetchone()[0]
        bad=self.proposal();bad['findings'][-1]['claims']=[{'pointer':'/nonexistent'}]
        with self.assertRaisesRegex(GateError,'bounded repair'):
            consolidate(self.store,self.source['id'],ReplayModel([bad,bad]))
        self.assertEqual(before,self.store.db.execute('SELECT COUNT(*) FROM memory').fetchone()[0])
        self.assertIsNone(self.store.control('memory_consolidation:'+self.source['id']))

    def test_memory_identity_and_source_scope_cannot_be_forged(self):
        self.consolidated()
        record=json.loads(self.store.db.execute('SELECT payload FROM memory LIMIT 1').fetchone()[0])
        record['claims'][0]['equals']='forged'
        with self.assertRaisesRegex(GateError,'identity'):checked_record(self.store,record)
        record['id']=digest({k:record[k] for k in ('evidence','claims','procedure','scope')})
        with self.assertRaisesRegex(GateError,'observation'):checked_record(self.store,record)

    def test_retrieval_ranks_by_task_and_skips_oversized_findings(self):
        self.consolidated()
        records=[checked_record(self.store,json.loads(r[0])) for r in self.store.db.execute("SELECT payload FROM memory WHERE status='verified'")]
        relevant=next(r for r in records if r['procedure']=='notional_turnover')
        giant=deepcopy(relevant);giant['id']='000';giant['observations']=['x'*10000]
        chosen=select_records([giant,*records],'traded notional turnover',('notional_turnover',),max_bytes=2000)
        self.assertTrue(chosen);self.assertEqual(chosen[0]['procedure'],'notional_turnover')
        self.assertNotIn(giant,chosen);self.assertLessEqual(len(canonical(chosen).encode()),2000)
        self.assertEqual(select_records(records,'turnover',('notional_turnover',),dataset_id='different'),[])

    def test_new_cases_have_explicit_valid_contracts_and_do_not_reuse_v1_prompts(self):
        old=prepare_suite(self.store);old_prompts={digest(c['prompt']) for c in self.store.get(old)['cases']}
        cases=build_cases();self.assertEqual(len(cases),40)
        self.assertEqual(len({c['id'] for c in cases}),40)
        for case in cases:
            self.assertNotIn(digest(case['prompt']),old_prompts)
            self.assertTrue(schema_valid(case['prompt']['output_schema'],case['expected']))
            self.assertNotIn('expected',case['prompt'])

    def test_prepare_freezes_memory_model_source_and_original_thresholds_before_calls(self):
        a=self.prepared();b=prepare(self.store,self.source['id'],self.config,self.root/'other')
        self.assertEqual(a['plan'],b['plan']);self.assertFalse(a['consumed'])
        plan=self.store.get(a['plan']);suite=self.store.get(plan['suite'])
        self.assertEqual(suite['thresholds'],{'no_learning_gain':.1,'raw_logs_gain':.05,'confidence_level':.95})
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0],0)
        self.assertTrue(preflight(self.store,a['plan'],self.config)['can_run'])
        with self.assertRaisesRegex(GateError,'pinned'):
            preflight(self.store,a['plan'],self.config | {'output_per_million':3})
        with patch('quant_agent.learning_revision.source_hashes',return_value={}):
            with self.assertRaisesRegex(GateError,'source changed'):preflight(self.store,a['plan'],self.config)
        for _,_,request in requests(self.store,plan):self.assertNotIn('"expected":',request.messages[-1]['content'])

    def test_output_contract_rejects_extra_fields_boolean_numbers_and_wrong_enums(self):
        decision=next(c for c in build_cases() if c['family']=='decisions')
        schema=decision['prompt']['output_schema']
        self.assertFalse(schema_valid(schema,{'decision':'reject','reason':'extra'}))
        self.assertFalse(schema_valid(schema,{'decision':'accept'}))
        numeric=next(c for c in build_cases() if c['family']=='features')
        answer=dict(numeric['expected']);answer['total_return']=True
        self.assertFalse(schema_valid(numeric['prompt']['output_schema'],answer))

    def test_complete_fixture_evaluation_is_not_genuine_learning_and_cached_resume_is_free(self):
        prepared=self.prepared();plan=self.store.get(prepared['plan'])
        answers={digest(c['prompt']):c['expected'] for c in self.store.get(plan['suite'])['cases']}
        class Fixture:
            name='scripted-evaluation-fixture'
            def generate(inner,request):
                task=json.loads(request.messages[-1]['content'])['task']
                return ModelResponse(json.dumps(answers[digest(task)]),100,50,{'test_fixture':True})
        report=run(self.store,prepared['plan'],self.config,Fixture())
        self.assertEqual(report['episodes'],240)
        self.assertEqual(report['success_rates'],{'no_learning':1.,'raw_logs':1.,'verified_memory':1.})
        self.assertFalse(report['gates']['authentic_model']);self.assertFalse(report['learning_demonstrated'])
        self.assertFalse(report['paper_eligible'])
        count=self.store.db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0]
        cached=run(self.store,prepared['plan'],self.config,ReplayModel([]))
        self.assertEqual(report['receipt'],cached['receipt'])
        self.assertEqual(count,self.store.db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0])

    def test_partial_campaign_is_retired_without_new_calls(self):
        prepared=self.prepared()
        self.store.set_control('learning_revision_used:'+prepared['plan'],True)
        with self.assertRaisesRegex(GateError,'Partially consumed'):
            run(self.store,prepared['plan'],self.config,ReplayModel([]))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0],0)


if __name__=='__main__':unittest.main()
