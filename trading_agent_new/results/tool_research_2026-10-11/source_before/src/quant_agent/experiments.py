"""Controlled comparisons, independent challenges, and deterministic decisions."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import copy

from .common import GateError, canonical, file_hash
from .contracts import ResearchSpec, StrategyArtifact
from .data import Dataset
from .ledger import simulate
from .metrics import compare, metrics
from .store import Store
from .verify import verify_ledger


def run_experiment(store: Store, dataset: Dataset, spec: ResearchSpec, strategy: StrategyArtifact,
                   spec_hash: str, strategy_hash: str, sandbox_image: str | None = None) -> str:
    # All six trial identities are recorded before the first result.
    baseline = StrategyArtifact("builtin", spec.baseline, spec.lookback)
    trials = [{"id":f"{name}_{factor:g}","strategy":asdict(artifact),"cost_multiplier":factor}
              for factor in (1.0,2.0,0.0) for name,artifact in (("baseline",baseline),("candidate",strategy))]
    source_root = Path(__file__).parent
    environment = {"python":sys.version.split()[0],"sandbox_image":sandbox_image,
                   "host_source_hashes":{p.name:file_hash(p) for p in sorted(source_root.glob("*.py"))}}
    register_hash = store.put("trial_register", {"spec":spec_hash,"strategy":strategy_hash,"trials":trials,"environment":environment})
    ledgers, summaries, receipts = {}, {}, {}
    for trial in trials:
        name = trial["id"]
        ledger = simulate(dataset,spec,StrategyArtifact(**trial["strategy"]),trial["cost_multiplier"],sandbox_image)
        verification = verify_ledger(dataset,spec,ledger)
        ledgers[name] = store.put("ledger",ledger)
        summaries[name] = metrics(ledger,spec.limits["capital"])
        receipts[name] = verification
    primary = compare(store.get(ledgers["candidate_1"]),store.get(ledgers["baseline_1"]),
                      spec.bootstrap_samples,spec.block_length,spec.seed)
    stress = summaries["candidate_2"]["excess_sharpe"]-summaries["baseline_2"]["excess_sharpe"]
    no_cost = summaries["candidate_0"]["excess_sharpe"]-summaries["baseline_0"]["excess_sharpe"]
    qualification = dataset.qualification(store)
    return store.put("experiment_result", {"spec":spec_hash,"strategy":strategy_hash,"dataset_id":dataset.id,
                   "data_constraints":dataset.manifest.get("data_constraints",{}),
                   "qualification_gaps":dataset.manifest.get("qualification_gaps",{}),
                   "qualification":qualification,"trial_register":register_hash,"ledgers":ledgers,"metrics":summaries,
                   "verification":receipts,"comparison":primary,"stress_sharpe_gain":stress,
                   "no_cost_sharpe_gain":no_cost,"gross_net_gain_difference":primary["sharpe_gain"]-no_cost,
                   "alpha_claim":False,"observations":"Historical selection is exploratory; paper eligibility is separate."})


def challenge_result(store: Store, dataset: Dataset, result_hash: str, sandbox_image: str | None = None) -> str:
    result = store.get(result_hash,"experiment_result")
    spec = ResearchSpec(**store.get(result["spec"],"research_spec"))
    strategy = StrategyArtifact(**store.get(result["strategy"],"strategy"))
    full = store.get(result["ledgers"]["candidate_1"],"ledger")
    receipt = verify_ledger(dataset,spec,full)
    midpoint = full["daily"][len(full["daily"])//2]["session"]
    prefix = simulate(dataset,spec,strategy,1.0,sandbox_image,stop=midpoint)
    altered = copy.deepcopy(dataset)
    for (day,asset),row in altered.bars.items():
        if day > midpoint:
            for field in ("open","close","high","low"): row[field] *= 7.0
            row["volume"] *= 11
    for day,events in altered.actions.items():
        if day > midpoint:
            for e in events:
                if e["kind"] == "dividend": e["value"] *= 3
    for (day,asset),row in altered.borrow.items():
        if day > midpoint: row["fee_rate"] += 0.15
    perturbed = simulate(altered,spec,strategy,1.0,sandbox_image,stop=midpoint)
    reference = {key:[r for r in full[key] if r["session"] <= midpoint] for key in ("daily","fills","targets")}
    prefix_passed = all(canonical(reference[k]) == canonical(prefix[k]) for k in reference)
    perturb_passed = all(canonical(prefix[k]) == canonical(perturbed[k]) for k in reference)
    if not prefix_passed or not perturb_passed:
        raise GateError("Strategy failed prefix/future-perturbation invariance")
    return store.put("challenge", {"result":result_hash,"passed":True,"independent_ledger":receipt,
                   "prefix_invariance":prefix_passed,"future_perturbation":perturb_passed,"boundary":midpoint,
                   "limits":"Empirical invariance and container isolation do not prove arbitrary Python causality.",
                   "diagnostics":{"cost_attribution":True,"exposures":True,"annual_instability":True,"paired_bootstrap":True}})


def decide(store: Store, result_hash: str, challenge_hash: str) -> str:
    result = store.get(result_hash,"experiment_result")
    challenge = store.get(challenge_hash,"challenge")
    if challenge["result"] != result_hash or not challenge["passed"]:
        raise GateError("A verified challenge for this exact result is required")
    spec = ResearchSpec(**store.get(result["spec"],"research_spec"))
    primary = result["comparison"]
    baseline,candidate = result["metrics"]["baseline_1"],result["metrics"]["candidate_1"]
    gates = {"minimum_sharpe_gain":primary["sharpe_gain"] >= spec.minimum_sharpe_gain,
             "positive_uncertainty_lower_bound":primary["lower_95_one_sided"] > 0,
             "sufficient_blocks":primary["sufficient_blocks"],
             "drawdown":candidate["max_drawdown"]-baseline["max_drawdown"] <= spec.maximum_drawdown_deterioration,
             "double_transaction_and_borrow_costs":result["stress_sharpe_gain"] > 0,
             "verified_accounting_causality":True}
    practical = all(gates.values())
    qualified = result["qualification"]["qualified"]
    status = "advance_to_paper_qualification" if practical and qualified else "revise_data_qualification" if practical else "reject"
    return store.put("decision", {"result":result_hash,"challenge":challenge_hash,"status":status,
                   "gates":gates,"practical_passed":practical,"data_qualified":qualified,
                   "paper_eligible":practical and qualified,"live_capital_eligible":False,
                   "reason":"Fixed preregistered gates; no outcome-driven changes. Rejection is a retained research output."})
