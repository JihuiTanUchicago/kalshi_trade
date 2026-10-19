import copy
import contextlib
import io
import json
import unittest
from unittest.mock import patch
import paper_release_runner as runner

class RunnerTests(unittest.TestCase):
    def test_inspection_does_not_build_bundle_read_credentials_or_create_receiver(self):
        with patch.object(runner,'module_program',return_value=''),patch.object(runner,'remote',return_value={'status':'ready_for_quiet_window'}),\
             patch.object(runner,'upload') as upload,patch.object(runner,'envelope_module') as envelope,\
             patch.object(runner.subprocess,'run') as subprocess,contextlib.redirect_stdout(io.StringIO()):
            runner.run('inspect')
        upload.assert_not_called();envelope.assert_not_called();subprocess.assert_not_called()

    def test_busy_activation_remains_read_only(self):
        with patch.object(runner,'module_program',return_value=''),patch.object(runner,'remote',return_value={'status':'waiting_for_idle','jobs':{'running':1}}) as remote,\
             patch.object(runner,'upload') as upload,patch.object(runner,'envelope_module') as envelope,\
             contextlib.redirect_stdout(io.StringIO()) as output:
            runner.run('activate')
        self.assertEqual(remote.call_count,1);upload.assert_not_called();envelope.assert_not_called()
        self.assertIn('"restart_performed": false',output.getvalue())

    def test_unrecognized_phase_fails_before_remote_calls(self):
        with patch.object(runner,'remote') as remote:
            with self.assertRaises(RuntimeError):runner.run('deploy-whatever')
        remote.assert_not_called()

    def test_failed_or_partial_inventory_does_not_start_mutation(self):
        for status in ('inspection_failed','already_installed','activation_requires_inspection'):
            with self.subTest(status=status),patch.object(runner,'module_program',return_value=''),\
                 patch.object(runner,'remote',return_value={'status':status}),patch.object(runner,'upload') as upload,\
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):runner.run('activate')
                upload.assert_not_called()

    def good_report(self):
        report={'credentials_source':'actual_worker_proc_environment','actual_worker_preflight':{'ready':True},
                'database_or_order_actions':False,'checks':[],'events':[],
                'actual_worker_settings':json.loads((runner.HERE/'manifest.json').read_text())['provider_settings']}
        for name in ('alpaca_completed_history','massive_fx_history','databento_bars_EQUS.MINI','databento_bars_GLBX.MDP3'):
            report['checks'].append({'name':name,'status':'available','bar_counts':{'SYNTHETIC':1}})
        for name in ('massive_treasury_yields','massive_funding_conditions'):
            report['checks'].append({'name':name,'status':'available','observation_count':1})
        for name in ('current_agent_tool_bridge','historical_agent_tool_bridge'):
            report['checks'].append({'name':name,'status':'protocol_completed','real_model_calls':0,
                'scripted_model_calls':5,'secret_in_model_context':False,'historical_current_data_blocked':True})
        for name in ('massive_options_chain','massive_current_fx'):
            report['checks'].append({'name':name,'status':'disabled_configuration'})
        for bridge,kind in (('current','search'),('current','publications'),('current','contents'),('historical','publications'),('historical','contents')):
            report['events'].append({'provider':'exa','bridge':bridge,'kind':kind,'status':'available','source_count':1})
        return report

    def test_all_supported_worker_checks_are_required(self):
        report=self.good_report();self.assertTrue(runner.provider_acceptance(report)['accepted'])
        for index in range(len(report['checks'])):
            candidate=copy.deepcopy(report);candidate['checks'].pop(index)
            self.assertFalse(runner.provider_acceptance(candidate)['accepted'])
        for index in range(len(report['events'])):
            candidate=copy.deepcopy(report);candidate['events'].pop(index)
            self.assertFalse(runner.provider_acceptance(candidate)['accepted'])

    def test_empty_receipts_guard_failure_and_temporary_credentials_cannot_pass(self):
        for mutation in ('empty','guard','secret','credentials','orders','cost'):
            report=self.good_report()
            if mutation=='empty':report['checks'][0]['bar_counts']={'SYNTHETIC':0}
            elif mutation=='guard':report['checks'][7]['historical_current_data_blocked']=False
            elif mutation=='secret':report['checks'][6]['secret_in_model_context']=True
            elif mutation=='credentials':report['credentials_source']='diagnostic_environment'
            elif mutation=='orders':report['database_or_order_actions']=True
            else:report['actual_worker_settings']['TAU_DATABENTO_MAX_COST_USD']='5.00'
            self.assertFalse(runner.provider_acceptance(report)['accepted'],mutation)

    def test_scripts_do_not_claim_genuine_model_or_open_market_acceptance(self):
        result=runner.provider_acceptance(self.good_report())
        self.assertFalse(result['authenticated_queued_model_run'])
        self.assertFalse(result['open_market_snapshot_freshness_verified'])

if __name__=='__main__':unittest.main()
