"""Ordered workflow tests. Models/data are fixtures, not learning/alpha evidence."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, timedelta
import csv
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from quant_agent.agent import ResearchAgent
from quant_agent.cli import main
from quant_agent.common import GateError, digest, file_hash
from quant_agent.configuration import load_model_environment
from quant_agent.contracts import Action, ModelRequest, ModelResponse, ResearchSpec
from quant_agent.data import Dataset
from quant_agent.first_episode import benchmark, execute, paper_gate, prepare, require_smokes, status, transfer
from quant_agent.fixtures import make_fixture
from quant_agent.models import HTTPModel, ReplayModel
from quant_agent.store import Store


class FirstEpisodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "store");self.addCleanup(self.store.close)
        self.data = make_fixture(self.root / "data")
        # Extend the synthetic fixture with twenty warmup weekdays, without
        # consuming or inspecting any investment performance.
        warmup = [];day = date(2026, 5, 31)
        while len(warmup) < 20:
            if day.weekday() < 5:warmup.append(day.isoformat())
            day -= timedelta(days=1)
        warmup.reverse()
        manifest_path = self.root / "data/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        first = self.data.days[0]
        for name in ("sessions", "bars", "membership", "borrow", "financing"):
            path = self.root / "data" / (name + ".csv")
            with path.open(newline="") as f:
                reader = csv.DictReader(f);fields = reader.fieldnames;rows = list(reader)
            originals = [row for row in rows if row["session"] == first]
            additions = []
            for day in warmup:
                for original in originals:
                    row = {key: value.replace(first, day) for key, value in original.items()}
                    if "settlement_date" in row:row["settlement_date"] = day
                    additions.append(row)
            with path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields);writer.writeheader();writer.writerows(additions + rows)
            manifest["files"][name]["sha256"] = file_hash(path)
        manifest_path.write_text(json.dumps(manifest))
        self.data = Dataset(self.root / "data")
        self.config = {"adapter": "chat_completions", "endpoint": "https://api.x.ai/v1/chat/completions",
                       "model": "grok-4.20-0309-non-reasoning", "api_key_env": "XAI_API_KEY",
                       "input_per_million": 1.25, "output_per_million": 2.5, "supports_temperature": False}

    def plan(self):
        return prepare(self.store, self.data, self.root / "reports")

    def smoke_fixtures(self):
        # Operator fixture records live only in this temporary test store.
        for case in ("json", "workflow"):
            self.store.put("adapter_smoke", {"configuration": digest(self.config), "case": case,
                                            "passed": True, "real_request": True, "test_fixture": True})

    def completed_fixture(self):
        plan = self.plan();self.smoke_fixtures()
        actions = [{"tool": "register_strategy", "arguments": self.store.get(plan["plan"])["candidate"]},
                   *[{"tool": name, "arguments": {}} for name in ("evaluate", "challenge", "decide")],
                   {"tool": "remember", "arguments": {"procedure": "retain_rejections", "claims": [{"pointer": "/paper_eligible", "equals": False}]}},
                   {"tool": "finish", "arguments": {}}]
        outcome = execute(self.store, plan["plan"], self.data, self.config, ReplayModel(actions))
        self.assertTrue(outcome["research_complete"])
        self.assertFalse(outcome["learning_improvement_measured"])
        self.assertFalse(outcome["paper_eligible"])
        return plan

    def test_prepare_is_preregistered_idempotent_and_has_no_result(self):
        a = self.plan();b = self.plan()
        self.assertEqual(a["run"], b["run"])
        run = self.store.run(a["run"])
        self.assertEqual(run["state"], "specified")
        self.assertIsNone(run["result"])
        spec = self.store.get(run["spec"])
        self.assertEqual(spec["lookback"], 63)
        self.assertEqual(spec["bootstrap_samples"], 2000)
        self.assertFalse(spec["allow_short"])
        self.assertFalse(spec["prospective"])
        self.assertEqual(spec["minimum_sharpe_gain"], 0.10)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0], 0)

    def test_candidate_cannot_change_frozen_reference_rules(self):
        plan = self.plan()
        candidate = deepcopy(self.store.get(plan["plan"])["candidate"])
        candidate["name"] = "equal_weight"
        with self.assertRaisesRegex(GateError, "preregistered candidate"):
            ResearchAgent(self.store, self.data).act(plan["run"], Action("register_strategy", candidate))
        self.assertIsNone(self.store.run(plan["run"])["strategy"])

    def test_both_smoke_cases_and_exact_configuration_required_before_model_call(self):
        plan = self.plan()
        class NoCall:
            name = "uncalled"
            def generate(self, request):raise AssertionError("should not call")
        with self.assertRaisesRegex(GateError, "both real model-smoke"):
            execute(self.store, plan["plan"], self.data, self.config, NoCall())
        self.smoke_fixtures();require_smokes(self.store, self.config)
        with self.assertRaises(GateError):require_smokes(self.store, self.config | {"output_per_million": 3})
        with self.assertRaises(GateError):transfer(self.store, plan["plan"], NoCall())
        with patch("quant_agent.first_episode.run_benchmark") as evaluate, self.assertRaises(GateError):
            benchmark(self.store,plan["plan"],self.config)
        evaluate.assert_not_called()
        self.assertFalse(paper_gate(self.store,plan["plan"])["research_ready_for_separate_broker_preflight"])

    def test_dataset_account_constraints_cannot_be_ignored(self):
        self.data.manifest["data_constraints"] = {"allow_short": False, "maximum_scored_end": self.data.days[-2]}
        run = self.store.new_run("respect import scope")
        spec = ResearchSpec("hypothesis", self.data.id, "trend", self.data.days[63], self.data.days[-1])
        with self.assertRaisesRegex(GateError, "excludes shorts"):
            ResearchAgent(self.store, self.data).act(run, Action("freeze_spec", asdict(spec)))
        proposal = asdict(spec) | {"allow_short": False}
        with self.assertRaisesRegex(GateError, "scoring coverage"):
            ResearchAgent(self.store, self.data).act(run, Action("freeze_spec", proposal))
        self.assertEqual(self.store.run(run)["state"], "requested")

    def test_scripted_episode_transfer_cites_verified_evidence_without_learning_claim(self):
        plan = self.completed_fixture()
        decision = self.store.run(plan["run"])["decision"]
        proposal = {"hypothesis": "Fixed volatility scaling improves the declared risk-adjusted objective.",
                    "baseline": "Matched equal-weight allocation.",
                    "experiment": "Freeze scaling, timing and matched cost-free/doubled-cost controls before new results.",
                    "rejection_criteria": ["Reject failed fixed uncertainty/cost gates; proxy evidence stays unqualified."],
                    "evidence_hashes": [decision], "paper_eligible": False}
        proposal["research_spec"] = self.store.get(self.store.run(plan["run"])["spec"]) | {"hypothesis":proposal["hypothesis"],"lookback":20}
        result = transfer(self.store, plan["plan"], ReplayModel([proposal]))
        self.assertTrue(result["task_is_distinct"])
        self.assertFalse(result["learning_improvement_measured"])
        self.assertTrue(result["evidence_reference_checks_passed"])
        self.assertTrue(result["protected_specification_checks_passed"])
        # Resume never calls the model twice or rewrites learned memory.
        again = transfer(self.store, plan["plan"], ReplayModel([]))
        self.assertEqual(result["receipt"], again["receipt"])
        # A failed full learning evaluation is measured, not demonstrated.
        receipt=self.store.put("learning_evaluation",{"episodes":240,"learning_demonstrated":False,"cost":0,"test_fixture":True})
        self.store.set_control("first_episode_learning:"+plan["run"],receipt)
        state=status(self.store,plan["plan"])
        self.assertTrue(state["learning_improvement_measured"])
        self.assertFalse(state["learning_demonstrated"])
        self.assertFalse(paper_gate(self.store,plan["plan"])["research_ready_for_separate_broker_preflight"])

    def test_invalid_transfer_cannot_create_verified_claims(self):
        plan = self.completed_fixture()
        memory_before = self.store.db.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        with self.assertRaisesRegex(GateError, "Transfer proposal failed"):
            transfer(self.store, plan["plan"], ReplayModel([{"paper_eligible": True, "evidence_hashes": ["invented"]}]))
        self.assertIsNone(self.store.control("first_episode_transfer:" + plan["run"]))
        self.assertEqual(memory_before, self.store.db.execute("SELECT COUNT(*) FROM memory").fetchone()[0])

    def test_transfer_rejects_risk_drift_even_with_a_valid_memory_citation(self):
        plan = self.completed_fixture();run = self.store.run(plan["run"])
        hypothesis = "Volatility scaling improves the fixed objective."
        proposal = {"hypothesis":hypothesis,"baseline":"equal_weight","experiment":"Fixed volatility scaling.",
                    "rejection_criteria":["Apply the frozen criteria."],"evidence_hashes":[run["decision"]],"paper_eligible":False,
                    "research_spec":self.store.get(run["spec"]) | {"hypothesis":hypothesis,"lookback":20}}
        proposal["research_spec"]["limits"]["gross"] = 2.0
        with self.assertRaisesRegex(GateError,"protected-spec"):
            transfer(self.store,plan["plan"],ReplayModel([proposal]))
        self.assertFalse(status(self.store,plan["plan"])["verified_task_transfer"])

    def test_transfer_accepts_json_numeric_representation_without_relaxing_values(self):
        plan = self.completed_fixture();run = self.store.run(plan["run"])
        hypothesis = "Volatility scaling improves the fixed objective."
        spec = self.store.get(run["spec"]) | {"hypothesis":hypothesis,"lookback":20}
        spec["limits"]["gross"] = 1
        spec["minimum_commission"] = 1
        proposal = {"hypothesis":hypothesis,"baseline":"equal_weight","experiment":"Fixed volatility scaling.",
                    "rejection_criteria":["Apply the frozen criteria."],"evidence_hashes":[run["decision"]],
                    "paper_eligible":False,"research_spec":spec}
        result = transfer(self.store,plan["plan"],ReplayModel([proposal]))
        self.assertTrue(result["protected_specification_checks_passed"])
        self.assertTrue(status(self.store,plan["plan"])["verified_task_transfer"])

    def test_resumed_decision_exposes_exact_memory_evidence_without_rerunning_experiment(self):
        plan = self.plan();self.smoke_fixtures()
        agent = ResearchAgent(self.store,self.data)
        agent.act(plan["run"],Action("register_strategy",self.store.get(plan["plan"])["candidate"]))
        for tool in ("evaluate","challenge","decide"):agent.act(plan["run"],Action(tool,{}))
        before = self.store.run(plan["run"])
        expected_decision = before["decision"]
        class ResumeModel:
            name = "fixture-resumed-model"
            def generate(inner,request):
                info = json.loads(request.messages[-1]["content"])
                if info["state"] == "decided":
                    self.assertEqual(info["evidence_hashes"]["decision"],expected_decision)
                    self.assertIn("selected evidence artifact's root",request.messages[0]["content"])
                    action = {"tool":"remember","arguments":{"procedure":"retain_rejections",
                              "evidence":info["evidence_hashes"]["decision"],"claims":[{"pointer":"/status"}]}}
                else:action = {"tool":"finish","arguments":{}}
                return ModelResponse(json.dumps(action),100,30,{"test_fixture":True})
        outcome = execute(self.store,plan["plan"],self.data,self.config,ResumeModel())
        self.assertTrue(outcome["research_complete"])
        after = self.store.run(plan["run"])
        for key in ("spec","strategy","result","challenge","decision"):
            self.assertEqual(before[key],after[key])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND kind='experiment_attempt'",(plan["run"],)).fetchone()[0],1)

    def test_local_credential_is_literal_and_loads_only_configured_key(self):
        path = self.root / "model.env"
        literal = 'fixture-${UNCHANGED}-$(command)-`command`-#suffix'
        path.write_text("XAI_API_KEY='" + literal + "'\nUNRELATED_OPTION=changed\n")
        with patch.dict(os.environ, {"UNRELATED_OPTION": "original"}):
            self.assertTrue(load_model_environment(path, self.config))
            self.assertEqual(os.environ["XAI_API_KEY"], literal)
            self.assertEqual(os.environ["UNRELATED_OPTION"], "original")
        path.write_text("XAI_API_KEY=first\nXAI_API_KEY=secret-not-printed\n")
        with self.assertRaises(GateError) as error:load_model_environment(path, self.config)
        self.assertNotIn("secret-not-printed", str(error.exception))

    def test_missing_grok_key_stops_smoke_before_network(self):
        config = self.root / "model.json";config.write_text(json.dumps(self.config))
        env = self.root / "model.env";env.write_text("XAI_API_KEY=\n")
        output = io.StringIO()
        with patch.object(HTTPModel, "generate") as generate, redirect_stdout(output):
            code = main(["--store", str(self.root / "cli_store"), "--model-env", str(env), "model-smoke", "--model-config", str(config)])
        self.assertEqual(code, 2);generate.assert_not_called()

    def test_grok_uses_generic_adapter_and_retains_only_normalized_provenance(self):
        calls = []
        def transport(url, body, headers):
            calls.append((url, body, headers))
            return {"id": "test-fixture-request", "model": self.config["model"], "system_fingerprint": "test-fixture",
                    "choices": [{"message": {"content": '{"adapter_ok":true}', "reasoning_content": "PRIVATE-FIXTURE-TRACE"}}],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 8}}
        with patch.dict(os.environ, {"XAI_API_KEY": "fixture-secret"}):
            response = HTTPModel(self.config, transport).generate(ModelRequest([{"role": "user", "content": "JSON only"}]))
        self.assertEqual(calls[0][0], "https://api.x.ai/v1/chat/completions")
        self.assertNotIn("temperature", calls[0][1])
        self.assertEqual(response.metadata["served_model"], self.config["model"])
        self.assertNotIn("PRIVATE-FIXTURE-TRACE", json.dumps(response.metadata))
        self.assertNotIn("fixture-secret", json.dumps(response.metadata))
        with self.assertRaisesRegex(GateError, "local endpoint"):
            HTTPModel(self.config | {"local_no_auth": True})


if __name__ == "__main__":
    unittest.main()
