"""Small readable reports referencing immutable evidence."""
from __future__ import annotations

from pathlib import Path
import json

from .store import Store


def write_report(store: Store, run_id: str, output: str | Path) -> Path:
    run = store.run(run_id)
    output = Path(output);output.mkdir(parents=True,exist_ok=True)
    bundle = {"run":run}
    lines = ["# Quantitative research report","",f"Run: {run_id}",f"Workflow: {run['state']}","",run["goal"],""]
    for field in ("spec","strategy","result","challenge","decision"):
        if not run[field]: continue
        data = store.get(run[field])
        bundle[field] = data
        if field=="spec": lines += ["## Frozen specification","",f"Hypothesis: {data['hypothesis']}",f"Baseline: {data['baseline']}",f"Scored dates: {data['start']} to {data['end']}",""]
        if field=="result":
            lines += ["## Controlled results","",f"Data quality: **{data['qualification']['quality']}**; qualified: {data['qualification']['qualified']}.",
                      "Historical evidence is exploratory. Synthetic fixtures measure engineering behavior.","",
                      "| Trial | Excess Sharpe | Max drawdown | Annual notional turnover | Filled orders |",
                      "|---|---:|---:|---:|---:|"]
            for trial,m in data["metrics"].items():
                lines.append(f"| {trial} | {m['excess_sharpe']:.4f} | {m['max_drawdown']:.2%} | {m['annualized_turnover']:.2f} | {m['orders_filled']} |")
            c = data["comparison"]
            lines += ["",f"Paired Sharpe gain: {c['sharpe_gain']:+.4f}; one-sided 95% lower bound: {c['lower_95_one_sided']:+.4f}.",
                      f"Gain with doubled transaction/borrow costs: {data['stress_sharpe_gain']:+.4f}.",
                      f"Gain in matched cost-free controls: {data['no_cost_sharpe_gain']:+.4f}.",""]
            if data.get("data_constraints") or data.get("qualification_gaps"):
                lines += ["## Data assumptions and unresolved source checks","",
                          "These observations do not establish source qualification or profitable live trading.",
                          "The machine-readable report retains every source disagreement and assumption.","",
                          "```json",json.dumps({"constraints":data.get("data_constraints",{}),
                                                "qualification_gaps":data.get("qualification_gaps",{})},indent=2),"```",""]
        if field=="challenge": lines += ["## Independent challenges","",f"Ledger passed: {data['independent_ledger']['passed']}; prefix invariant: {data['prefix_invariance']}; future perturbation invariant: {data['future_perturbation']}.",""]
        if field=="decision":
            lines += ["## Decision","",f"**{data['status']}**","",f"Paper eligible: {data['paper_eligible']}; live-capital eligible: false.",""]
            lines.extend(f"- {name}: {'pass' if passed else 'fail'}" for name,passed in data["gates"].items())
            lines.append("")
    lines += ["## Evidence","",f"Artifact directory: {store.artifacts}",""]
    lines.extend(f"- {field}: {run[field]}" for field in ("spec","strategy","result","challenge","decision") if run[field])
    (output/"report.json").write_text(json.dumps(bundle,indent=2,allow_nan=False)+"\n")
    path = output/"REPORT.md";path.write_text("\n".join(lines)+"\n")
    return path
