"""Statement evidence, full paper-cycle recovery and consistent backup fixtures."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import json
import unittest

from quant_agent.common import GateError,canonical,utcnow
from quant_agent.contracts import Limits,ResearchSpec,StrategyArtifact
from quant_agent.data import Dataset,QUALIFICATION_CHECKS,qualify
from quant_agent.fixtures import make_fixture
from quant_agent.operations import audit_statement
from quant_agent.paper import PaperController
from quant_agent.store import Store
from test_paper_evaluation import FakeBroker


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root/"state")
        d=make_fixture(self.root/"data")
        # Test-only operator review fixture, never production source evidence.
        manifest=d.manifest|{"quality":"licensed_unqualified","availability_basis":"historical_asof",
                             "corporate_action_coverage":"complete","universe_coverage":"survivorship_free","borrow_basis":"historical"}
        (d.directory/"manifest.json").write_text(json.dumps(manifest));self.data=Dataset(d.directory)
        documents={}
        for name in QUALIFICATION_CHECKS:
            p=self.root/f"{name}.txt";p.write_text("Synthetic qualification-review fixture; not genuine licensed evidence.");documents[name]=p
        qualify(self.store,self.data,{"dataset_id":self.data.id,"reviewer":"test-only reviewer",
                "checks":{k:{"passed":True,"notes":"Operator-review contract fixture only"} for k in QUALIFICATION_CHECKS}},documents)
        self.broker=FakeBroker();self.broker.state["settled_cash"]=100_000.
        self.controller=PaperController(self.store,self.broker,self.broker.account)
        spec=ResearchSpec("Control fixture",self.data.id,"equal_weight",self.data.days[20],self.data.days[-1],bootstrap_samples=100)
        payload={"paper_account":self.broker.account,"spec":self.store.put("research_spec",asdict(spec)),
                 "strategy":self.store.put("strategy",asdict(StrategyArtifact("builtin","equal_weight",20,0.02))),"limits":asdict(Limits())}
        with self.store.db: self.store.db.execute("INSERT INTO releases VALUES(?,?,1)",("fixture",canonical(payload)))
    def tearDown(self): self.store.close();self.tmp.cleanup()
    def test_full_cycle_freezes_batch_and_does_not_recalculate_on_repeat(self):
        result=self.controller.cycle(self.data,now="2026-10-09T13:00:00Z")
        count=len(self.broker.submissions);self.assertGreater(count,0)
        self.broker.state["nav"]=99_900
        again=self.controller.cycle(self.data,now="2026-10-09T13:00:00Z")
        self.assertEqual(result["intents"],again["intents"]);self.assertEqual(count,len(self.broker.submissions))
    def test_stale_session_prevents_broker_submission(self):
        with self.assertRaises(GateError): self.controller.cycle(self.data,now="2026-10-10T13:00:00Z")
        self.assertFalse(self.broker.submissions)
    def test_all_batch_intents_persist_before_acknowledgement_failure(self):
        self.broker.lost_ack=True
        with self.assertRaises(GateError): self.controller.cycle(self.data,now="2026-10-09T13:00:00Z")
        rows=list(self.store.db.execute("SELECT status FROM intents"))
        self.assertGreater(len(rows),1);self.assertIn("planned",[r[0] for r in rows]);self.assertIn("unknown",[r[0] for r in rows])
    def test_insufficient_settled_cash_cannot_use_broker_margin_as_cash(self):
        self.broker.state["settled_cash"]=1000
        with self.assertRaises(GateError): self.controller.cycle(self.data,now="2026-10-09T13:00:00Z")
        self.assertFalse(self.broker.submissions)
    def test_recovery_rechecks_settled_cash_for_entire_unsent_batch(self):
        with patch.object(self.controller,"submit_intent",side_effect=GateError("Interrupted before send")):
            with self.assertRaises(GateError): self.controller.cycle(self.data,now="2026-10-09T13:00:00Z")
        self.broker.state["settled_cash"]=1000
        with self.assertRaisesRegex(GateError,"Recovered batch exceeds"):
            self.controller.cycle(self.data,now="2026-10-09T13:00:00Z")
        self.assertFalse(self.broker.submissions)
    def test_future_effective_actions_do_not_adjust_current_paper_positions(self):
        self.store.set_control("paper_activation_date","2026-06-01")
        with patch("quant_agent.paper.utcnow",return_value="2026-07-01T15:00:00Z"):
            self.controller.refresh_actions(self.data)
        self.assertTrue(all(a["session"]<="2026-07-01" for a in self.store.control("paper_actions")))
    def test_engineering_control_runs_one_share_without_alpha_promotion(self):
        key=self.controller.engineering_control(self.data,"S-A",1);self.controller.activate(key)
        receipt=self.controller.cycle(self.data,now="2026-10-09T13:00:00Z")
        self.assertEqual(len(self.broker.submissions),1);self.assertEqual(self.broker.submissions[0]["quantity"],1)
        row=self.store.db.execute("SELECT payload FROM releases WHERE id=?",(key,)).fetchone()
        self.assertFalse(json.loads(row[0])["alpha_claim"])
    def test_etf_short_control_rejected(self):
        with self.assertRaises(GateError): self.controller.engineering_control(self.data,"F-SPY",-1)
    def statement_fixture(self):
        day=self.data.days[-1];asset="S-A";price=self.data.bars[(day,asset)]["open"]
        intent={"session":day,"quantity":1,"asset_id":asset}
        execution={"execution_id":"fill","intent_id":"i","quantity":1,"asset_id":asset,"price":price,"commission":1.0}
        with self.store.db:
            self.store.db.execute("INSERT INTO intents(id,payload,status) VALUES(?,?,'filled')",("i",canonical(intent)))
            self.store.db.execute("INSERT INTO executions VALUES(?,?,?)",("fill","i",canonical(execution)))
        cash=100_000-price-1-2+0.5
        close={"account":self.broker.account,"positions":{asset:1},"cash":cash}
        key=self.store.put("broker_close",close);self.store.set_control(f"paper_close:{self.broker.account}:{day}",key)
        self.store.set_control("paper_initial_cash",100_000)
        source=self.root/"raw-broker-statement.csv";source.write_text("test-only synthetic export; no real account")
        statement={"account":self.broker.account,"currency":"USD","session":day,"complete_session":True,
                   "opening_cash":100_000,"closing_cash":cash,"opening_positions":{},"closing_positions":{asset:1},
                   "events":[{"event_id":"t","kind":"trade","execution_id":"fill","asset_id":asset,"quantity":1,"price":price,"amount":-price},
                             {"event_id":"c","kind":"commission","execution_id":"fill","amount":-1},
                             {"event_id":"b","kind":"borrow_fee","amount":-2},{"event_id":"r","kind":"interest","amount":0.5}]}
        return statement,source
    def test_statement_cash_fees_positions_and_operational_learning(self):
        s,p=self.statement_fixture();receipt=audit_statement(self.store,s,p,self.data,self.broker.account)
        evidence=self.store.get(receipt)
        self.assertTrue(evidence["cash_attributed"]);self.assertTrue(evidence["fees_matched"]);self.assertFalse(evidence["strategy_alpha"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM memory").fetchone()[0],1)
    def test_missing_fee_duplicate_and_unexplained_cash_rejected(self):
        s,p=self.statement_fixture();wrong=copy.deepcopy(s);wrong["events"].pop(1)
        with self.assertRaises(GateError): audit_statement(self.store,wrong,p,self.data,self.broker.account)
        wrong=copy.deepcopy(s);wrong["events"].append(wrong["events"][0].copy())
        with self.assertRaises(GateError): audit_statement(self.store,wrong,p,self.data,self.broker.account)
        wrong=copy.deepcopy(s);wrong["events"].append({"event_id":"x","kind":"transfer","amount":20})
        with self.assertRaises(GateError): audit_statement(self.store,wrong,p,self.data,self.broker.account)
    def test_backup_restores_artifacts_memory_and_pending_budget(self):
        from quant_agent.models import Budget
        s,p=self.statement_fixture();receipt=audit_statement(self.store,s,p,self.data,self.broker.account)
        Budget(self.store,"pending",5).reserve(1)
        self.store.backup(self.root/"backup")
        restored=Store(self.root/"backup")
        try:
            self.assertEqual(restored.get(receipt),self.store.get(receipt))
            self.assertEqual(Budget(restored,"pending",5).used(),1)
            self.assertEqual(restored.db.execute("SELECT COUNT(*) FROM memory").fetchone()[0],1)
        finally: restored.close()


if __name__=="__main__": unittest.main()
