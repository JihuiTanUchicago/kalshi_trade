"""Paper fault injection and independently graded comparative learning checks."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import json
import unittest

from quant_agent.common import GateError,canonical,digest,utcnow
from quant_agent.contracts import Limits
from quant_agent.evaluation import CONDITIONS,benchmark_preflight,equal_answer,prepare_suite,summarize
from quant_agent.paper import PaperController
from quant_agent.store import Store


class FakeBroker:
    account="DU999999"
    def __init__(self):
        self.submissions=[];self.cancelled=[];self.lost_ack=False
        self.state={"account":self.account,"paper":True,"complete":True,"asof":utcnow(),"nav":100_000.,"cash":100_000.,
                    "available_funds":100_000.,"positions":{},"orders":[],"executions":[],"unmapped_positions":[],"foreign_orders":[]}
    def snapshot(self): self.state["asof"]=utcnow();return copy.deepcopy(self.state)
    def submit(self,intent):
        self.submissions.append(intent);key=len(self.submissions)
        self.state["orders"].append(dict(broker_id=key,perm_id=key+100,intent_id=intent["intent_id"],status="Submitted",filled=0))
        if self.lost_ack: raise TimeoutError("acknowledgement lost")
        return key
    def cancel(self,key): self.cancelled.append(key)
    def borrow(self,a): return {"asof":utcnow(),"shares":1000,"fee_rate":0.02,"realtime":True}
    def what_if(self,o): return {"passed":True,"initial_margin_change":100}


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root/"state");self.broker=FakeBroker()
        self.controller=PaperController(self.store,self.broker,self.broker.account)
        # Isolated controller fixture. This is not a qualified research release.
        self.release="controller-fixture-release"
        payload={"paper_account":self.broker.account,"limits":asdict(Limits())}
        with self.store.db: self.store.db.execute("INSERT INTO releases VALUES(?,?,1)",(self.release,canonical(payload)))
        self.order={"asset_id":"S-A","quantity":10,"expected_price":100.0,"asof":"2026-10-08T20:30:00Z","reason":"rebalance"}
    def tearDown(self): self.store.close();self.tmp.cleanup()
    def intent(self,**kwargs):
        receipt=self.store.put("paper_preflight",{"release":self.release,"session":"2026-10-09","orders":[self.order],**kwargs})
        return {**self.order,"release":self.release,"account":self.broker.account,"session":"2026-10-09","preflight":receipt}
    def test_unqualified_order_rejected(self):
        with self.assertRaises(GateError): self.controller.submit_intent(self.order)
        self.assertEqual(len(self.broker.submissions),0)
    def test_duplicate_intent_is_not_resubmitted(self):
        intent=self.intent();a=self.controller.submit_intent(intent);b=self.controller.submit_intent(intent)
        self.assertEqual(a,b);self.assertEqual(len(self.broker.submissions),1)
    def test_changed_preflight_does_not_change_order_identity(self):
        a=self.controller.submit_intent(self.intent(snapshot={"nav":100_000}))
        b=self.controller.submit_intent(self.intent(snapshot={"nav":100_001}))
        self.assertEqual(a,b);self.assertEqual(len(self.broker.submissions),1)
    def test_order_cannot_change_after_preflight(self):
        intent=self.intent();intent["quantity"]=100
        with self.assertRaises(GateError): self.controller.submit_intent(intent)
    def test_unknown_acknowledgement_recovered_across_restart(self):
        self.broker.lost_ack=True;intent=self.intent()
        with self.assertRaises(GateError): self.controller.submit_intent(intent)
        self.assertEqual(len(self.controller.unresolved()),1)
        self.store.close();self.store=Store(self.root/"state");self.controller=PaperController(self.store,self.broker,self.broker.account)
        self.controller.resume()
        self.assertFalse(self.controller.unresolved())
        self.controller.submit_intent(intent)
        self.assertEqual(len(self.broker.submissions),1)
    def test_unknown_absent_from_broker_never_blindly_retried(self):
        self.broker.lost_ack=True
        with self.assertRaises(GateError): self.controller.submit_intent(self.intent())
        self.broker.state["orders"]=[]
        with self.assertRaises(GateError): self.controller.resume()
        self.assertEqual(len(self.broker.submissions),1)
    def test_duplicate_broker_orders_pause_execution(self):
        key=self.controller.submit_intent(self.intent());self.broker.state["orders"].append(dict(broker_id=999,perm_id=1999,intent_id=key,status="Submitted",filled=0))
        with self.assertRaises(GateError): self.controller.reconcile()
        self.assertTrue(self.store.control("paper_pause"))
    def test_partial_fill_duplicate_execution_not_double_counted(self):
        key=self.controller.submit_intent(self.intent())
        e={"execution_id":"fill-1","intent_id":key,"asset_id":"S-A","quantity":4,"price":100.,"commission":1.}
        self.broker.state["executions"]=[e,e.copy()]
        self.controller.reconcile();self.controller.reconcile()
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM executions").fetchone()[0],1)
        self.assertEqual(self.store.db.execute("SELECT filled FROM intents").fetchone()[0],4)
    def test_execution_correction_does_not_silently_replace_quantity(self):
        key=self.controller.submit_intent(self.intent())
        e={"execution_id":"fill-1","intent_id":key,"asset_id":"S-A","quantity":4,"price":100.,"commission":1.}
        self.broker.state["executions"]=[e];self.controller.reconcile();e["quantity"]=5
        with self.assertRaises(GateError): self.controller.reconcile()
    def test_oversized_fill_rejected(self):
        key=self.controller.submit_intent(self.intent())
        self.broker.state["orders"][0]["filled"]=11
        with self.assertRaises(GateError): self.controller.reconcile()
    def test_wrong_broker_account_or_incomplete_snapshot_rejected(self):
        self.broker.state["account"]="U12345"
        with self.assertRaises(GateError): self.controller._snapshot()
        self.broker.state["account"]=self.broker.account;self.broker.state["complete"]=False
        with self.assertRaises(GateError): self.controller._snapshot()
    def test_paper_position_rollforward_matches_execution_journal(self):
        self.store.set_control("paper_initial_positions",{})
        key=self.controller.submit_intent(self.intent())
        self.broker.state["executions"]=[{"execution_id":"fill-1","intent_id":key,"asset_id":"S-A","quantity":4,"price":100.,"commission":1.}]
        self.broker.state["positions"]={"S-A":4};self.controller.reconcile()
        self.broker.state["positions"]={"S-A":8}
        with self.assertRaises(GateError): self.controller.reconcile()
    def test_pause_cancels_owned_orders_without_liquidating(self):
        self.controller.submit_intent(self.intent());self.controller.pause("test protective pause")
        self.assertEqual(self.broker.cancelled,[1]);self.assertEqual(len(self.broker.submissions),1)
    def test_partial_cancel_preserves_terminal_status(self):
        key=self.controller.submit_intent(self.intent())
        self.broker.state["orders"][0]["status"]="Cancelled"
        self.broker.state["executions"]=[{"execution_id":"partial","intent_id":key,"asset_id":"S-A","quantity":4,"price":100.,"commission":1.}]
        self.controller.reconcile()
        self.assertEqual(self.store.db.execute("SELECT status FROM intents").fetchone()[0],"cancelled")
    def test_intraday_loss_from_day_base_triggers_protective_pause(self):
        self.controller.poll();self.broker.state["nav"]=97_000
        with self.assertRaises(GateError): self.controller.poll()
        self.assertTrue(self.store.control("paper_pause"))


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.store=Store(self.tmp.name)
        self.key=prepare_suite(self.store);self.suite=self.store.get(self.key)
    def tearDown(self): self.store.close();self.tmp.cleanup()
    def episodes(self,verified=True):
        return [{"case":case["id"],"condition":condition,"repetition":r,"passed":verified if condition=="verified_memory" else False,"cost":0,"hard_error":False}
                for case in self.suite["cases"] for condition in CONDITIONS for r in range(2)]
    def test_reserved_suite_reproducible_and_all_families_present(self):
        self.assertEqual(prepare_suite(self.store),self.key)
        self.assertEqual(len(self.suite["cases"]),40)
        self.assertEqual(len({c["family"] for c in self.suite["cases"]}),8)
        self.assertEqual(len({canonical(c["prompt"]) for c in self.suite["cases"]}),40)
    def test_mock_improvement_cannot_pass_learning_gate(self):
        r=summarize(self.suite,self.episodes(),authentic_model=False)
        self.assertFalse(r["learning_demonstrated"])
    def test_equal_success_rates_do_not_claim_self_improvement(self):
        episodes=self.episodes()
        for e in episodes: e["passed"]=True
        r=summarize(self.suite,episodes,authentic_model=True)
        self.assertFalse(r["learning_demonstrated"]);self.assertEqual(r["gains"]["no_learning"],0)
    def test_hard_failure_blocks_apparent_improvement(self):
        episodes=self.episodes();episodes[4]["hard_error"]=True
        r=summarize(self.suite,episodes,authentic_model=True)
        self.assertFalse(r["learning_demonstrated"])
    def test_missing_or_duplicate_episode_rejected(self):
        episodes=self.episodes()
        with self.assertRaises(GateError): summarize(self.suite,episodes[:-1],True)
        with self.assertRaises(GateError): summarize(self.suite,episodes+[episodes[0]],True)
    def test_fixed_campaign_must_fit_budget_before_calling(self):
        cfg={"input_per_million":1000,"output_per_million":1000,"model":"expensive"}
        self.assertFalse(benchmark_preflight(self.store,self.key,cfg)["can_run"])
    def test_grader_rejects_nan_and_bool_in_numeric_answers(self):
        self.assertFalse(equal_answer({"result":1},{"result":True}))
        self.assertFalse(equal_answer({"result":1},{"result":float("nan")}))
        self.assertTrue(equal_answer({"result":0.10},{"result":0.100000001}))


if __name__=="__main__": unittest.main()
