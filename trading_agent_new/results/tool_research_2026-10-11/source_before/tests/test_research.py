"""Hand accounts, experiment invariance, verified memory and research recovery."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import json
import unittest

from quant_agent.agent import ResearchAgent
from quant_agent.common import GateError,canonical
from quant_agent.contracts import Action,ResearchSpec,StrategyArtifact
from quant_agent.experiments import challenge_result,decide,run_experiment
from quant_agent.fixtures import make_fixture
from quant_agent.ledger import simulate
from quant_agent.memory import Memory
from quant_agent.models import ReplayModel
from quant_agent.store import Store
from quant_agent.strategy import plan_orders,validate_weights
from quant_agent.verify import verify_ledger


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root/"state");self.data=make_fixture(self.root/"data")
        self.spec=ResearchSpec("Fixed buffer hypothesis",self.data.id,"equal_weight",self.data.days[20],self.data.days[-1],bootstrap_samples=100)
    def tearDown(self): self.store.close();self.tmp.cleanup()
    def artifact(self,name="equal_weight",buffer=0.02): return StrategyArtifact("builtin",name,20,buffer)
    def toy(self,short=False,split=False,dividend=False):
        d=copy.deepcopy(self.data)
        d.assets={"S-A":d.assets["S-A"]}
        for key in list(d.bars):
            if key[1]!="S-A": del d.bars[key];continue
            row=d.bars[key];row.update(open=100.,close=100.,high=100.,low=100.,volume=1_000_000)
        d.actions={}
        day=d.days[21]
        if split:
            d.actions[day]=[{"session":day,"asset_id":"S-A","kind":"split","value":2.0,"pay_date":"","available_at":d.sessions[d.days[19]]["close_at"]}]
            for (date,asset),row in d.bars.items():
                if date>=day: row.update(open=50.,close=50.,high=50.,low=50.)
        if dividend:
            d.actions[day]=[{"session":day,"asset_id":"S-A","kind":"dividend","value":2.0,"pay_date":d.days[23],"available_at":d.sessions[d.days[19]]["close_at"]}]
            for (date,asset),row in d.bars.items():
                if date>=day: row.update(open=98.,close=98.,high=98.,low=98.)
        return d
    def run_toy(self,d,weight,end=24):
        spec=ResearchSpec(**(asdict(self.spec)|{"end":d.days[end],"transaction_bps":0,"minimum_commission":0,"commission_per_share":0}))
        with patch("quant_agent.ledger.reference_weights",return_value={"S-A":weight}): r=simulate(d,spec,self.artifact(buffer=0.24))
        verify_ledger(d,spec,r)
        return r
    def test_split_hand_account_preserves_equity(self):
        r=self.run_toy(self.toy(split=True),0.25)
        self.assertEqual(r["daily"][0]["positions"]["S-A"],250)
        self.assertEqual(r["daily"][1]["positions"]["S-A"],500)
        # Cash yield belongs to financing; zero it in the hand equity assertion.
        self.assertAlmostEqual(r["daily"][1]["nav"]-r["daily"][0]["nav"],r["daily"][1]["cash_interest"])
    def test_long_dividend_receivable_paid_once(self):
        r=self.run_toy(self.toy(dividend=True),0.25)
        self.assertEqual(r["daily"][1]["receivables"],500)
        self.assertEqual(r["daily"][3]["receivables"],0)
        pays=[e for row in r["daily"] for e in row["cash_events"] if e["kind"]=="dividend_pay"]
        self.assertEqual(len(pays),1);self.assertEqual(pays[0]["amount"],500)
    def test_short_dividend_is_a_debt_not_income(self):
        r=self.run_toy(self.toy(dividend=True),-0.25)
        self.assertEqual(r["daily"][1]["positions"]["S-A"],-250)
        self.assertEqual(r["daily"][1]["receivables"],-500)
        self.assertEqual(r["daily"][3]["receivables"],0)
        self.assertGreater(r["daily"][1]["borrow_fee"],0)
    def test_short_sale_proceeds_collateral_and_settlement(self):
        r=self.run_toy(self.toy(),-0.25)
        first=r["daily"][0]
        self.assertEqual(first["cash"],125_000)
        self.assertEqual(first["short_collateral"],37_500)
        self.assertEqual(first["unsettled"],25_000)
        self.assertEqual(first["available_cash"],62_500)
    def test_borrow_recall_forces_cover_even_with_buffer(self):
        d=self.toy();prior=d.days[21];d.borrow[(prior,"S-A")]["shares"]=0
        r=self.run_toy(d,-0.25)
        self.assertEqual(r["daily"][2]["positions"].get("S-A",0),0)
        self.assertTrue(any(f["reason"]=="borrow_recall" for f in r["fills"]))
    def test_fractional_split_blocks_the_experiment(self):
        d=self.toy(split=True);d.actions[d.days[21]][0]["value"]=0.3333
        with self.assertRaises(GateError): self.run_toy(d,0.25)
    def test_independent_verifier_rejects_cash_and_fill_tampering(self):
        r=simulate(self.data,self.spec,self.artifact())
        wrong=copy.deepcopy(r);wrong["daily"][5]["cash"]+=1
        with self.assertRaises(GateError): verify_ledger(self.data,self.spec,wrong)
        wrong=copy.deepcopy(r);wrong["fills"][0]["price"]+=1
        with self.assertRaises(GateError): verify_ledger(self.data,self.spec,wrong)
        wrong=copy.deepcopy(r);wrong["daily"][1]["return"]+=0.001
        with self.assertRaises(GateError): verify_ledger(self.data,self.spec,wrong)
    def test_shared_planner_and_cap_rejection(self):
        from quant_agent.contracts import Limits
        c=self.data.context(25,20,True)
        with self.assertRaises(GateError): validate_weights({"S-A":0.3},c,Limits(),True)
        with self.assertRaises(GateError): validate_weights({"F-SPY":-0.2},c,Limits(),True)
        with self.assertRaises(GateError): validate_weights({"S-A":float("inf")},c,Limits(),True)
        orders=plan_orders(c,{},100_000,{"S-A":0.2},Limits())
        self.assertEqual(orders[0]["expected_price"],c["history"]["S-A"][-1]["close"])
    def test_prefix_future_perturbation_invariance_and_cost_stress(self):
        spec_hash=self.store.put("research_spec",asdict(self.spec));strategy_hash=self.store.put("strategy",asdict(self.artifact()))
        key=run_experiment(self.store,self.data,self.spec,self.artifact(),spec_hash,strategy_hash)
        challenge=self.store.get(challenge_result(self.store,self.data,key))
        self.assertTrue(challenge["prefix_invariance"]);self.assertTrue(challenge["future_perturbation"])
        result=self.store.get(key)
        self.assertEqual(len(result["ledgers"]),6)
        self.assertGreaterEqual(result["metrics"]["candidate_2"]["transaction_cost"],result["metrics"]["candidate_1"]["transaction_cost"])
        decision=self.store.get(decide(self.store,key,self.store.put("challenge",challenge)))
        self.assertFalse(decision["paper_eligible"])

    def test_spec_is_frozen_and_resume_is_not_duplicate(self):
        run=self.store.new_run("fixed controlled research");agent=ResearchAgent(self.store,self.data)
        agent.act(run,Action("freeze_spec",asdict(self.spec)))
        with self.assertRaises(GateError): agent.act(run,Action("freeze_spec",asdict(self.spec)))
        agent.act(run,Action("register_strategy",asdict(self.artifact())))
        with self.assertRaises(GateError): agent.act(run,Action("evaluate",{"cost_bps":0}))
        agent.act(run,Action("evaluate",{}))
        with self.assertRaises(GateError): agent.act(run,Action("evaluate",{}))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM events WHERE kind='experiment_attempt'").fetchone()[0],1)
    def test_generated_code_failure_has_no_trusted_metrics(self):
        run=self.store.new_run("python research");agent=ResearchAgent(self.store,self.data)
        agent.act(run,Action("freeze_spec",asdict(self.spec)))
        agent.act(run,Action("register_strategy",dict(kind="python",name="candidate",lookback=20,buffer=0.02,code="raise RuntimeError()")))
        with self.assertRaises(GateError): agent.act(run,Action("evaluate",{}))
        self.assertEqual(self.store.run(run)["state"],"implemented")
        self.assertIsNone(self.store.run(run)["result"])
        row=self.store.db.execute("SELECT hash FROM artifacts WHERE kind='error_receipt'").fetchone()
        self.assertFalse(self.store.get(row[0])["metrics_trusted"])

    def memory_fact(self,value=3,quality="proxy"):
        key=self.store.put("legacy_observation",{"quality":quality,"cost":value})
        return key
    def test_memory_rejects_hallucinated_fact_and_quality_upgrade(self):
        m=Memory(self.store);e=self.memory_fact()
        with self.assertRaises(GateError): m.add(e,[{"pointer":"/cost","equals":4}],"cost_attribution",{"market":"US","frequency":"daily","quality":"proxy"})
        with self.assertRaises(GateError): m.add(e,[{"pointer":"/cost","equals":3}],"cost_attribution",{"market":"US","frequency":"daily","quality":"qualified"})
    def test_memory_is_persistent_idempotent_and_transfers_procedure(self):
        m=Memory(self.store);e=self.memory_fact();scope={"market":"US","frequency":"daily","quality":"proxy"}
        first=m.add(e,[{"pointer":"/cost","equals":3}],"cost_attribution",scope)
        self.assertEqual(first,m.add(e,[{"pointer":"/cost","equals":3}],"cost_attribution",scope))
        self.store.close();self.store=Store(self.root/"state")
        records=Memory(self.store).retrieve("cost signal quality")
        self.assertEqual(records[0]["evidence"],e);self.assertIn("cost-free",records[0]["procedure_text"])
    def test_memory_conflicts_preserved_and_supersession_scoped(self):
        m=Memory(self.store);scope={"market":"US","frequency":"daily","quality":"proxy"}
        a=m.add(self.memory_fact(3),[{"pointer":"/cost","equals":3}],"cost_attribution",scope)
        b=m.add(self.memory_fact(5),[{"pointer":"/cost","equals":5}],"cost_attribution",scope)
        records=m.retrieve("cost")
        self.assertTrue(all(r["conflicts"] for r in records))
        c=m.add(self.memory_fact(6),[{"pointer":"/cost","equals":6}],"cost_attribution",scope,supersedes=a)
        self.assertNotIn(a,[r["id"] for r in m.retrieve("cost")])
    def test_model_cannot_place_orders_or_qualify_data(self):
        run=self.store.new_run("unsafe tool request");agent=ResearchAgent(self.store,self.data)
        for tool in ("submit_order","qualify_data","change_risk","delete_memory"):
            with self.assertRaises(GateError): agent.act(run,Action(tool,{}))
    def test_model_cannot_relax_mandate_or_cost_policy_before_freezing(self):
        run=self.store.new_run("unsafe mandate proposal");agent=ResearchAgent(self.store,self.data)
        proposal=asdict(self.spec);proposal["limits"]["position"]=1.0
        with self.assertRaises(GateError): agent.act(run,Action("freeze_spec",proposal))
        proposal=asdict(self.spec);proposal["transaction_bps"]=0.0
        with self.assertRaises(GateError): agent.act(run,Action("freeze_spec",proposal))
        self.assertEqual(self.store.run(run)["state"],"requested")


if __name__=="__main__": unittest.main()
