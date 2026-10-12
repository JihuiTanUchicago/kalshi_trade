"""Reproduce the actual Docker research path without models, licensed data or orders."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from quant_agent.agent import ResearchAgent
from quant_agent.common import GateError, file_hash, utcnow
from quant_agent.contracts import ResearchSpec
from quant_agent.fixtures import make_fixture
from quant_agent.memory import Memory
from quant_agent.models import ReplayModel
from quant_agent.report import write_report
from quant_agent.store import Store


def validate(image: str, output: Path) -> dict:
    if output.exists():
        raise GateError("Use a new output directory; previous validation evidence is preserved")
    dataset = make_fixture(output / "synthetic_data")
    store = Store(output / "state")
    receipt = {"started_at": utcnow(), "image": image, "passed": False,
               "controller_model": "scripted ReplayModel", "data_quality": "synthetic",
               "strategy_execution": "actual Docker container", "paid_model_calls": 0,
               "broker_orders": 0, "learning_improvement_measured": False, "alpha_evidence": False,
               "validator_sha256": file_hash(Path(__file__)),
               "strategy_source_sha256": file_hash(PROJECT / "examples/strategy.py")}
    key = store.new_run("Validate the Docker strategy interface, six controls, causal challenges and verified memory on synthetic inputs.")
    receipt["run"] = key
    try:
        spec = ResearchSpec(
            "Engineering test: a causal capped daily trend rule versus equal weight, with frozen transaction/borrow controls.",
            dataset.id, "equal_weight", dataset.days[20], dataset.days[-1],
            buffer=0.0, bootstrap_samples=2000,
        )
        actions = [
            {"tool": "freeze_spec", "arguments": asdict(spec)},
            {"tool": "register_strategy", "arguments": {
                "kind": "python", "name": "causal_api_example", "lookback": spec.lookback,
                "buffer": spec.buffer, "code": (PROJECT / "examples/strategy.py").read_text(),
            }},
            *[{"tool": name, "arguments": {}} for name in ("evaluate", "challenge", "decide")],
            {"tool": "remember", "arguments": {
                "procedure": "cost_attribution",
                "claims": [{"pointer": "/paper_eligible", "equals": False}],
            }},
            {"tool": "finish", "arguments": {}},
        ]
        agent = ResearchAgent(store, dataset, ReplayModel(actions), image)
        agent.execute(key)
        run = store.run(key)
        result = store.get(run["result"])
        challenge = store.get(run["challenge"])
        decision = store.get(run["decision"])
        # Read each object through the store's hash/type verification boundary.
        for row in store.db.execute("SELECT hash FROM artifacts").fetchall():
            store.get(row[0])
        memory = Memory(store).retrieve("cost attribution research")
        report = write_report(store, key, output / "research_report")
        receipt.update({
            "state": run["state"], "dataset_id": dataset.id,
            "scored_start": spec.start, "scored_end": spec.end,
            "controlled_trials": len(result["ledgers"]),
            "independent_ledger": challenge["independent_ledger"]["passed"],
            "prefix_invariance": challenge["prefix_invariance"],
            "future_perturbation": challenge["future_perturbation"],
            "challenge_passed": challenge["passed"],
            "decision": decision["status"], "paper_eligible": decision["paper_eligible"],
            "memory_retrieved": bool(memory), "report": str(report.resolve()),
        })
        if (run["state"] != "finished" or len(result["ledgers"]) != 6
                or not challenge["passed"] or decision["paper_eligible"] or not memory):
            raise GateError("Synthetic integration did not meet its engineering acceptance checks")
        receipt["passed"] = True
    except Exception as exc:
        receipt.update({"error_type": type(exc).__name__, "error": str(exc)[:300],
                        "state": store.run(key)["state"]})
        raise
    finally:
        receipt["finished_at"] = utcnow()
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        store.close()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.image, Path(args.output)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
