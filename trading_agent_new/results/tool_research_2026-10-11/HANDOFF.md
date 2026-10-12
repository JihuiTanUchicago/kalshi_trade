# Protected-tool research agent: development handoff

The provider-neutral analytical component is implemented, offline verified and genuinely exercised with Grok. It performs protected calculations, produces reports backed by independently verified receipts, and retains reusable procedures with their original scope. **Measured memory improvement failed. Accepted self-improving V1 and paper trading remain pending.**

## Delivered architecture and stage criteria

Eight trusted host tools cover as-of selection, holding returns, signed corporate actions, controlled assumptions, costs, exposure/free cash, protected research gates and fill reconciliation. Generated Python remains isolated in Docker; these allowlisted calculations have no file, network or broker access. Decimal results are separately reconstructed with rational arithmetic. A holding return requires a host-filtered history; both effective and available timestamps must pass.

The task controller exposes immutable document/receipt handles, exact current JSON action schemas and calculate/report phase. The model selects actions and final field citations. Host code copies verified values into the report. Four calls and one repair are allowed; counters persist before requests, duplicates are idempotent, failed sessions keep their allowance and completed sessions return cached evidence.

Procedural memory records independently reverified tool-name/input-kind facts under existing approved methodologies. Retrieval requires compatible task families and input kinds, retains original evidence/synthetic/proxy scope, and projects at most two records/1,500 bytes. Historical numerical answers remain in evidence. The ordinary research controller can invoke dataset-bound analytical jobs without advancing financial workflow state or changing policy.

Development steps and exit tests are specified in [AGENT_ACCEPTANCE.md](../../docs/AGENT_ACCEPTANCE.md#protected-tool-revision-development-gates): trusted calculations, durable task loop, scoped procedural memory, genuine practice, controlled evaluation, independent challenge and handoff. [AGENT_ARCHITECTURE.md](../../docs/AGENT_ARCHITECTURE.md#protected-analytical-task-loop) defines interfaces and authority. [DEVELOPMENT.md](DEVELOPMENT.md) retains the implementation history and limitations.

## Genuine controlled result

Final plan: `1976c09fe42d1ed13bcc409382ea9d1475416186e96d9432b16747c3d81235b4`. Frozen at 11:41:27 Asia/Shanghai before responses. Forty disjoint synthetic workflow jobs, three conditions, two repetitions: **240 complete episodes and 600 model requests**, including seven requests with uncertain billing. Every condition shares model/configuration, tools, action schemas, fixed gates, four-call/one-repair allowance and byte/token bounds. Memory stays frozen during evaluation. Sources and grading code are unchanged after preregistration.

| Condition | Correct completed reports | Strict success |
|---|---:|---:|
| No context | 67 / 80 | 83.75% |
| Raw training traces | 64 / 80 | 80.00% |
| Verified procedures | 65 / 80 | 81.25% |

Memory's gain is **-2.5pp** over no context and **+1.25pp** over raw traces. Paired task-bootstrap 95% lower bound: **-0.0875**. Memory has **13 hard outcome failures**, concentrated in execution (nine) and decisions (four). Both gain thresholds, the positive lower bound and zero-hard-error gate fail. The authentic-service gate passes. No criterion was relaxed.

Across conditions, 196 reports completed and all 196 match independently reconstructed answers; 44 tasks failed to produce a complete report. Failures include invalid final citations/action schemas, repeated completed tools and provider errors. Sixty repeated accepted actions are diagnosed. The protected calculation boundary worked for completed reports; workflow completion and memory benefit remain insufficient. [FAILURE_ANALYSIS.json](FAILURE_ANALYSIS.json) retains diagnostics without changing strict grading.

The independent family-cluster bootstrap lower bound is -0.0625, diagnostic only. Known template families, two repetitions, correlated workflows and common tool interfaces limit generalization. This evaluates analytical orchestration, not broad hypothesis discovery or investing alpha. The two prior direct-answer campaigns and the partial tool campaign remain preserved; absolute scores across protocols are not evidence of learning.

Evidence: [preregistration](campaign/PREREGISTRATION.md), [frozen inputs/contexts/source pins](campaign/PREREGISTRATION.json), [evaluation](campaign/EVALUATION.json), [report](campaign/REPORT.md), and [procedural memory snapshot](PROCEDURAL_MEMORY.json).

## Practice, interruptions and recovery

The first genuine nine-task practice plan produced zero final reports in 30 calls and saved no memories; its interface and pinned source remain in [failed_training_v1](failed_training_v1/TRAINING_RESULT.json). A separately seeded schema revision completed 7/9 in 22 calls and saved seven procedures.

Its first full comparison stopped after 139 completed episodes when RemoteDisconnected escaped the provider boundary. The incomplete campaign is explicitly retired; [retirement evidence](retired_connection_campaign/RETIREMENT.json), all episodes and source/preregistration are retained. The uncertain request remains charged. Replay is rejected and no aggregate learning decision is drawn from this partial comparison.

The narrowly scoped models.py patch normalizes HTTPException/OSError into sanitized ProviderError. Request bodies, headers, model, prices, financial policy and grading remain unchanged. A deliberate disconnect fixture verifies one bounded recovery, persistent counters and charged unknown billing. Fresh practice under the revised pinned source completes 7/9 in 23 calls and saves seven procedures (six synthetic, one proxy). The final comparison uses only this frozen practice snapshot. Fourteen procedural records have been added across the two successful practice plans; six previous records remain, giving 20 in the store.

The genuine proxy calculation covers SPY on October 5–9, 2026, with a descriptive return of **0.4826865%** and ten ending shares. The original imported prices and availability assumptions remain unchanged. [Job](SPY_ANALYTICAL_JOB.json), [current report](proxy_current_calculation.json) and [session](proxy_current_example_session.json) are inspectable. This calculation does not qualify the source or advance a strategy.

## Verification and costs

**122 offline tests pass**, including 19 new focused tests; 15 runtime-dependent container checks are skipped. Prior actual Docker evidence applies to the unchanged locked image/runtime. [Final regression](regression_release.log) and [disconnect test](transport_fault_test.log) retain evidence.

The [independent audit](verification_final.json) passes **39/39 checks**: answers, receipt chains, strict grades, original thresholds/statistics, frozen ordering/model/prices/source/contexts, scope, no campaign-time memory writes, original modules apart from declared changes, all 181 legacy files, financial runs/imports/raw snapshots, old controls/results, caps and no broker activity. Its first audit incorrectly compared dict field order against the ordered field list; the corrected set/uniqueness assertion passes without changing cases, source, grader or results. [Initial audit](verification.json) is preserved.

[Cached replay](resume_verification.json) adds **zero requests, episodes, memories or cost**. [Paper readiness](paper_gate.json) remains false; no broker connection or order was attempted.

| Budget phase | Cumulative requests | Recorded estimate |
|---|---:|---:|
| Smoke / $5 cap | 2 | $0.00053625 |
| Research/practice / $10 cap | 90 | $0.21322375 |
| Learning / $35 cap | 1,437 | $2.76155875 |
| Total / $50 cap | 1,529 | **$2.97531875** |

There are 1,521 returned usage receipts and eight uncertain-billing requests whose conservative reservations remain charged. This revision adds 1,032 request attempts and **$2.19861375** to the prior $0.776705 estimate. The final 240-episode campaign costs $1.31357750. All use the same persistent store and original caps; no resets. These are configured-token-price estimates, not reconciled invoices.

## Use and continuation

```bash
.agent-venv/bin/quant-agent research-task prepare --input examples/analytical_job.json
.agent-venv/bin/quant-agent --model-env .env research-task run \
  --session PREPARED_SESSION_ID --model-config config/grok.local.json
.agent-venv/bin/quant-agent research-task status --session PREPARED_SESSION_ID
```

The sample is synthetic. Genuine runs need both configuration-bound smoke receipts and use the existing research allocation. Credentials remain in the unchanged owner-only root .env.

Recheck this frozen campaign without model or broker calls, using a fresh output path:

```bash
PYTHONPATH=src:research .agent-venv/bin/python research/verify_tool_research.py \
  --output results/tool_research_audit_replay.json
```

Next development should address action adherence after a valid tool result and carefully verified error-based procedures, especially decisions and reconciliation. A new evaluation should require broader multistep research choices and remain disjoint from every retired/practice/reserved job, with identical controls and the original acceptance gates. Novel executable-procedure promotion and model-weight training remain later stages.

Licensed-source qualification, a qualified real-model/generated-code research episode and separate IBKR/five-session acceptance are still required for accepted V1. The original exploratory strategy remains rejected, with all financial rules and datasets preserved. No commits, deployment, purchases, subscriptions, unrelated-product changes or live orders were made.

Canonical tracker and handoff: [PROGRESS.md](../../docs/PROGRESS.md). Source and evidence hashes are in evidence_manifest.json; original source copies remain under source_before/ because the workspace is outside Git.
