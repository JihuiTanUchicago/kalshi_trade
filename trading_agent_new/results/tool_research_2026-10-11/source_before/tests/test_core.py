"""Adversarial contracts, data timing, immutable evidence and durable budgets."""
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import csv
import json
import os
import unittest

from quant_agent.common import GateError,canonical,file_hash,timestamp
from quant_agent.contracts import Action,ModelRequest,ModelResponse,ResearchSpec,StrategyArtifact
from quant_agent.data import Dataset,QUALIFICATION_CHECKS,qualify
from quant_agent.fixtures import make_fixture
from quant_agent.models import Budget,HTTPModel,MeteredModel,ProviderError
from quant_agent.sandbox import DockerSandbox
from quant_agent.store import Store


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory();self.root = Path(self.tmp.name)
        self.store = Store(self.root/"state")
        self.data = make_fixture(self.root/"data")
    def tearDown(self): self.store.close();self.tmp.cleanup()
    def edit_table(self,name,edit):
        path = self.root/"data"/f"{name}.csv"
        with path.open(newline="") as f:
            r = csv.DictReader(f);columns = r.fieldnames;rows = list(r)
        edit(rows)
        with path.open("w",newline="") as f:
            w = csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(rows)
        mpath = self.root/"data/manifest.json";manifest = json.loads(mpath.read_text())
        manifest["files"][name]["sha256"] = file_hash(path);mpath.write_text(json.dumps(manifest))
    def spec(self,**overrides):
        fields = dict(hypothesis="A falsifiable hypothesis",dataset_id=self.data.id,baseline="equal_weight",
                      start=self.data.days[20],end=self.data.days[-1],bootstrap_samples=100)
        return ResearchSpec(**(fields|overrides))

    def test_artifact_tampering_detected(self):
        key = self.store.put("source",{"value":2})
        path = self.store.artifacts/f"{key}.json";path.chmod(0o644)
        path.write_text('{"kind":"source","payload":{"value":3}}')
        with self.assertRaises(GateError): self.store.get(key)
    def test_artifact_type_and_traversal_rejected(self):
        key = self.store.put("source",{"value":2})
        with self.assertRaises(GateError): self.store.get(key,"decision")
        with self.assertRaises(GateError): self.store.get("../secrets")
    def test_illegal_and_duplicate_transition_rejected(self):
        key = self.store.new_run("goal")
        with self.assertRaises(GateError): self.store.advance(key,"requested","evaluated")
        self.store.advance(key,"requested","specified","spec","hash")
        with self.assertRaises(GateError): self.store.advance(key,"requested","specified")
    def test_scoring_2006_and_mutable_baseline_rejected(self):
        with self.assertRaises(GateError): self.spec(start="2006-01-01")
        with self.assertRaises(GateError): self.spec(baseline="choose_after_results")
    def test_nan_bool_weights_contracts(self):
        with self.assertRaises(GateError): self.spec(transaction_bps=float("nan"))
        with self.assertRaises(GateError): StrategyArtifact("builtin","equal_weight",20,True)
    def test_action_schema_has_no_hidden_tool_fields(self):
        with self.assertRaises(GateError): Action.parse({"tool":"evaluate","arguments":{},"override_risk":True})

    def test_import_hash_mismatch(self):
        p = self.root/"data/bars.csv";p.write_text(p.read_text()+"\n")
        with self.assertRaises(GateError): Dataset(self.root/"data")
    def test_duplicate_bar_rejected(self):
        self.edit_table("bars",lambda rows:rows.append(rows[0].copy()))
        with self.assertRaises(GateError): Dataset(self.root/"data")
    def test_missing_eligible_bar_rejected(self):
        self.edit_table("bars",lambda rows:rows.pop(0))
        with self.assertRaises(GateError): Dataset(self.root/"data")
    def test_impossible_preclose_daily_bar_rejected(self):
        self.edit_table("bars",lambda rows:rows[0].update(available_at="2026-06-01T08:00:00-04:00"))
        with self.assertRaises(GateError): Dataset(self.root/"data")
    def test_dividend_without_paydate_rejected(self):
        self.edit_table("actions",lambda rows:next(r for r in rows if r["kind"]=="dividend").update(pay_date=""))
        with self.assertRaises(GateError): Dataset(self.root/"data")
    def test_unsupported_action_not_dropped(self):
        self.edit_table("actions",lambda rows:rows[0].update(kind="merger_unspecified"))
        with self.assertRaises(GateError): Dataset(self.root/"data")
    def test_leveraged_etf_rejected(self):
        self.edit_table("assets",lambda rows:next(r for r in rows if r["kind"]=="etf").update(leverage_factor=3))
        with self.assertRaises(GateError): Dataset(self.root/"data")
    def test_asof_excludes_late_bar_and_future_ipo(self):
        day = self.data.days[25]
        self.edit_table("bars",lambda rows:next(r for r in rows if r["session"]==day and r["asset_id"]=="S-A").update(available_at="2027-01-01T00:00:00Z"))
        data = Dataset(self.root/"data");context = data.context(25,20,True)
        ids = {x["asset_id"] for x in context["universe"]}
        self.assertNotIn("S-A",ids);self.assertNotIn("S-IPO",ids)
    def test_future_changes_do_not_change_earlier_context(self):
        after = copy.deepcopy(self.data)
        for (day,a),bar in after.bars.items():
            if day>after.days[40]: bar["close"] *= 10
        self.assertEqual(canonical(self.data.context(40,20,True)),canonical(after.context(40,20,True)))
    def test_synthetic_cannot_be_qualified(self):
        with self.assertRaises(GateError): qualify(self.store,self.data,{}, {})
    def test_license_alone_does_not_qualify_vintages(self):
        p = self.root/"data/manifest.json";m=json.loads(p.read_text());m["quality"]="licensed_unqualified";m["availability_basis"]="current_vintage";p.write_text(json.dumps(m))
        with self.assertRaises(GateError): qualify(self.store,Dataset(p.parent),{}, {})

    def test_budget_unknown_request_persists_after_restart(self):
        b = Budget(self.store,"test",5);key=b.reserve(4);b.finish(key,None)
        self.store.close();self.store=Store(self.root/"state")
        b = Budget(self.store,"test",5)
        self.assertEqual(b.used(),4)
        with self.assertRaises(GateError): b.reserve(2)
    def test_budget_raise_and_negative_release_rejected(self):
        b=Budget(self.store,"test",5)
        with self.assertRaises(GateError): Budget(self.store,"test",10)
        with self.assertRaises(GateError): b.reserve(-1)
        key=b.reserve(1)
        with self.assertRaises(GateError): b.finish(key,-1)
    def test_global_cap_spans_campaigns(self):
        a=Budget(self.store,"first",35);a.reserve(35)
        b=Budget(self.store,"second",20)
        with self.assertRaises(GateError): b.reserve(16)
    def test_no_provider_call_when_episode_budget_exhausted(self):
        class Fake:
            name="fake";calls=0
            def generate(s,r): s.calls+=1;return ModelResponse("{}",2,2,{})
        f=Fake();b=Budget(self.store,"test",5)
        m=MeteredModel(f,b,1,1,max_decisions=1,episode_id="episode")
        req=ModelRequest([{"role":"user","content":"test"}],10)
        m.generate(req)
        new=MeteredModel(f,b,1,1,max_decisions=1,episode_id="episode")
        with self.assertRaises(GateError): new.generate(req)
        self.assertEqual(f.calls,1)
    def test_timeout_keeps_reservation(self):
        class Fake:
            name="fake"
            def generate(s,r): raise ProviderError("timeout",True)
        b=Budget(self.store,"test",5);m=MeteredModel(Fake(),b,1,1)
        with self.assertRaises(ProviderError): m.generate(ModelRequest([{"role":"user","content":"test"}],10))
        self.assertGreater(b.used(),0)

    def test_both_adapters_have_normalized_conformance(self):
        request=ModelRequest([{"role":"system","content":"policy"},{"role":"user","content":"task"}],20)
        raws = {"chat_completions":{"choices":[{"message":{"content":"{}"}}],"usage":{"prompt_tokens":3,"completion_tokens":2}},
                "anthropic_messages":{"content":[{"type":"text","text":"{}"}],"usage":{"input_tokens":3,"output_tokens":2}}}
        for style in raws:
            captured=[]
            def send(url,body,headers): captured.append(body);return raws[style]
            config={"adapter":style,"model":"pinned","endpoint":"https://example.test/api","api_key_env":"TEST_QUANT_KEY"}
            with patch.dict(os.environ,{"TEST_QUANT_KEY":"fixture-secret"}): response=HTTPModel(config,send).generate(request)
            self.assertEqual((response.content,response.input_tokens,response.output_tokens),("{}",3,2))
            self.assertNotIn("fixture-secret",canonical(response.metadata))
            self.assertEqual(captured[0]["model"],"pinned")
    def test_adapter_rejects_usage_missing_and_secret_urls(self):
        cfg={"adapter":"chat_completions","model":"x","endpoint":"https://key:secret@example.com","api_key_env":"TEST_QUANT_KEY"}
        with self.assertRaises(GateError): HTTPModel(cfg)
        cfg["endpoint"]="https://example.test"
        with patch.dict(os.environ,{"TEST_QUANT_KEY":"fixture"}):
            with self.assertRaises(ProviderError): HTTPModel(cfg,lambda *a:{}).generate(ModelRequest([]))
    def test_sandbox_command_does_not_mount_store_or_keys(self):
        cmd=DockerSandbox.build_command("sha256:"+"a"*64,"/tmp/code.py","test")
        for required in ("--network=none","--read-only","--user=65534:65534","--cap-drop=ALL","--pids-limit=64","--pull=never"):
            self.assertIn(required,cmd)
        self.assertEqual(cmd.count("--mount"),1)
        self.assertFalse(any("state.sqlite" in s or "API_KEY" in s for s in cmd))
    def test_generated_code_cannot_fall_back_to_host(self):
        with patch("quant_agent.sandbox.shutil.which",return_value=None):
            with self.assertRaises(GateError): DockerSandbox("raise RuntimeError('would run')","sha256:"+"a"*64)


if __name__=="__main__": unittest.main()
