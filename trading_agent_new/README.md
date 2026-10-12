# Polygon quantitative research agent

Version **0.1.0 release candidate** implements the first architecture: an LLM-agnostic research agent with verified memory and protected IBKR paper execution. It proposes and implements hypotheses, freezes experiment rules, challenges results, and retains evidence-backed lessons for later work. Foundation-model weights stay fixed.

The offline workflow, actual Docker strategy execution and a genuine Grok research/memory episode run now. On October 11, **122 applicable offline tests passed**; 15 container checks were skipped in that command, with the unchanged image’s earlier actual validation retained. The earlier 10 enrichment/import checks remain applicable to unchanged modules. The exploratory reference strategy was rejected. Both prior full direct-answer learning campaigns failed and are preserved.

The protected-tool revision completed genuine practice and a separately frozen **240-episode Grok comparison**: 81.25% verified memory, 83.75% no context and 80.00% raw traces. All 196 completed reports match independent answers; 44 tasks failed to complete, including 13 memory hard failures. **The fixed memory-improvement gate failed.** A 139-episode interrupted comparison is separately retired. [Handoff and development stages](results/tool_research_2026-10-11/HANDOFF.md), [39-check independent audit](results/tool_research_2026-10-11/verification_final.json), [zero-cost replay](results/tool_research_2026-10-11/resume_verification.json) and [procedural snapshot](results/tool_research_2026-10-11/PROCEDURAL_MEMORY.json) retain evidence. Cumulative configured-price estimate: $2.9753 under the original $50 cap, including eight uncertain requests. Licensed source qualification and IBKR session acceptance remain pending; original research is preserved.

Current Docker evidence: [verification](results/docker_validation_2026-10-10/verification.json), [container checks](results/docker_validation_2026-10-10/container_tests.json), and [synthetic research report](results/docker_validation_2026-10-10/research_report/REPORT.md). Licensed-data candidates, coverage gaps and procurement questions: [data_candidates.json](results/docker_validation_2026-10-10/data_candidates.json). No provider has yet passed the source-qualification gate.

## Try the first version

From `/Users/jonathanzhang/Desktop/Polygon`:

```bash
.agent-venv/bin/quant-agent doctor
.agent-venv/bin/quant-agent --store results/agent_v1/demo/state demo
.agent-venv/bin/quant-agent --store results/agent_v1/demo/state memory "cost attribution"
```

The demo uses explicitly synthetic stocks/ETF data and a scripted model. It exercises a frozen specification, six paired trials, independent accounting and causality checks, a decision, persistent learning, and retrieval for a new task. It makes zero model API calls and submits zero broker orders. Output: `results/agent_v1/demo/research/REPORT.md` and `DEMO.json`.

Python 3.12 or newer is required. The core uses the standard library; it can also run without installation as `PYTHONPATH=src .venv/bin/python -m quant_agent`. An isolated `.agent-venv` now contains the editable package, the official IBKR SDK 10.50.2, and protobuf 5.29.5. The original research environment is unchanged.

## What is implemented

- A resumable workflow and immutable, hashed specifications, code, trial registers, ledgers, verification receipts and decisions.
- Protected analytical task tools for timing, returns, signed corporate actions, controlled assumptions, costs, exposure, research gates and fill reconciliation. Final values cite independently verified tool receipts; the model chooses actions through explicit current-handle schemas.
- Configurable chat-completions-compatible and native Anthropic adapters, with durable reservations, bounded repairs, and pricing/model pins. The workflow has no provider SDK dependency.
- Provider-neutral CSV imports with stable security IDs, dated eligibility, raw prices, availability times, actual corporate actions/pay dates, settlement dates and historical borrow/financing records.
- Docker-only generated Python execution, receiving one dated context at a time. There is no host execution fallback.
- Integer-share long/short accounting, restricted short collateral, settlement, dividends owed by shorts, borrow fees, financing, participation and cash limits.
- Fixed baseline/candidate, cost-free and double-transaction-and-borrow-cost controls; paired block uncertainty, annual instability and benchmark exposure diagnostics.
- Exact evidence-backed memory observations, approved research procedures, qualification scopes, conflict preservation and explicit supersession. Bounded post-episode consolidation selects exact scalar paths; task retrieval checks facts and scope before ranking relevance. Failures enter memory as errors with untrusted performance metrics.
- Smaller procedural task context transfers verified tool sequences and source scope, excluding old numerical answers. Separate practice and frozen tool-workflow evaluation preserve the original improvement gates.
- A frozen 40-task/240-episode comparison of no learning, raw-log context and verified memory, plus a separately frozen explicit-schema replacement protocol. Scripted evaluations cannot pass the measured-learning gate.
- A separate IBKR paper controller/worker, automatic release queue, broker margin/borrow checks, frozen daily order batches, durable intent identities, position/execution reconciliation and protective pauses.
- Operator-only one-share paper controls, broker statement attribution, and consistent evidence/database backups.

Architecture, stage criteria and limitations: [AGENT_ARCHITECTURE.md](docs/AGENT_ARCHITECTURE.md), [AGENT_ACCEPTANCE.md](docs/AGENT_ACCEPTANCE.md). Canonical implementation status/handoff: [PROGRESS.md](docs/PROGRESS.md).

## Run a protected analytical task

Use [analytical_job.json](examples/analytical_job.json) as a minimal synthetic example, or supply a bounded job with immutable input documents and requested report fields. The job's declared quality is preserved. Genuine model calls use the existing research allocation and persistent budget store.

```bash
.agent-venv/bin/quant-agent research-task prepare --input examples/analytical_job.json
.agent-venv/bin/quant-agent --model-env .env research-task run \
  --session PREPARED_SESSION_ID --model-config config/grok.local.json
.agent-venv/bin/quant-agent research-task status --session PREPARED_SESSION_ID
```

The model selects a tool and an existing document/receipt handle. Host calculations enforce input types and timing, independently reconstruct results, then copy cited values into a final report. Four calls and one repair are permitted. Completed runs return cached receipts; failed sessions retain their allowance. Successful complete traces save verified procedures for compatible later tasks, retaining their original evidence and scope. No historical numerical answer is copied into procedural context.

`tool-study prepare-training/train/prepare/preflight/run/status` separates declared practice from a new 40-task, three-condition, two-repetition evaluation. All conditions get the same tools, action schemas and caps. Memory is frozen before evaluation and cannot learn from its answers. The original two learning campaigns remain preserved. Analytical task competence and a five-session snapshot calculation do not establish a profitable strategy; financial, data qualification and broker gates remain separate.

## Qualified historical imports

Keep licensed data outside committed source; use an import directory containing `manifest.json` and seven CSV tables. The exact columns are listed in `src/quant_agent/data.py` and the architecture document. CSV is the dependency-free V1 interchange; a Parquet delivery adapter can be added without changing the dataset contract.

```bash
.agent-venv/bin/quant-agent import-data /ABSOLUTE/LICENSED/IMPORT
.agent-venv/bin/quant-agent qualify-data /ABSOLUTE/LICENSED/IMPORT \
  --attestation /ABSOLUTE/review.json --evidence-root /ABSOLUTE/review-documents
```

The second command is an operator action; the research model has no qualification tool. It requires a named reviewer, the exact manifest hash, every documented check, and supporting files. A license alone does not establish historical availability, corporate-action completeness or unbiased universe coverage. Synthetic/proxy imports cannot be promoted through this operation.

The six-ETF public study remains an exploratory proxy. Import its scoped lessons without rerunning or changing its results:

```bash
.agent-venv/bin/quant-agent memory --seed-legacy
```

Scored simulations start in 2016 or later. Earlier observations may supply warmup. Historical data already inspected is never represented as untouched confirmatory evidence.

## Alpaca exploratory historical snapshots

The auxiliary data client uses an isolated `.runtime/alpaca-venv` with Alpaca's official SDK and dotenv. The private root `.env` is ignored and was created with owner-only permissions; `.env.example` documents its fields. Keep `ALPACA_DATA_ENDPOINT=https://data.alpaca.markets` and fill `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` locally. The loader reads that file directly, without printing credentials or letting stale shell values override it. Historical data uses the same data endpoint with paper-account keys.

```bash
.agent-venv/bin/python -m venv .runtime/alpaca-venv
.runtime/alpaca-venv/bin/python -m pip install -r research/requirements-alpaca.txt
.runtime/alpaca-venv/bin/python research/fetch_alpaca.py --check-config
.runtime/alpaca-venv/bin/python research/fetch_alpaca.py
```

Configuration checking makes no network request and cannot prove authentication. The download defaults to SPY/QQQ/IWM from January 2016 through completed prior New York calendar dates, explicitly selecting SIP/raw daily bars and excluding the most recent 20 minutes. The SDK follows pagination; HTTP requests have a 30-second timeout. Only the fixed HTTPS data endpoint is permitted, and failures omit credential-bearing request/server details. A permission error stops rather than silently switching feeds. `--symbols SPY IWM EFA TLT IEF GLD` selects the legacy ETF scope; `--start YYYY-MM-DD` selects a later acquisition start.

Each successful acquisition writes a new `data/alpaca_snapshots/<UTC-timestamp>/` containing `daily_raw.csv`, SDK-combined provider bar objects and a hashed provenance manifest. Existing output directories are refused. The snapshot has `quality:proxy` and retrieval-time evidence only; it is not a seven-table agent import, qualified historical availability, independent source corroboration or commercial-rights approval. Original research, results and qualification gates are preserved. No trading endpoint is called.

Offline boundary checks: `.runtime/alpaca-venv/bin/python -m unittest discover -s research -p test_fetch_alpaca.py -v`. Setup status and installed dependency versions are recorded in `results/alpaca_setup_2026-10-10/`. On October 10, genuine authentication and a SIP/raw historical download succeeded: SPY/QQQ/IWM each have 2,708 daily bars from January 4, 2016 through October 9, 2026, including the complete October 5–9 week. All ten snapshot verification checks passed. Current [downloaded CSV](data/alpaca_snapshots/20261010T140939.395972Z/daily_raw.csv), [manifest](data/alpaca_snapshots/20261010T140939.395972Z/manifest.json) and [authentic verification](results/alpaca_setup_2026-10-10/live_api_20261010T140939Z/verification.json) establish exploratory access; full source qualification remains pending.

## Connect a model and run research

Copy a model example to an ignored `config/*.local.json`. Set the endpoint, pinned model identifier, credential environment-variable name and verified current input/output prices. Credentials belong in the environment. Hosted routes with missing/zero pricing are blocked.

For compatible endpoints, `token_limit_field` can be `max_tokens` or `max_completion_tokens`; `supports_temperature: false` omits that parameter. These are adapter configuration, not changes to the research controller.

```bash
.agent-venv/bin/quant-agent source-add /ABSOLUTE/source-excerpt.txt --title "Source title"
.agent-venv/bin/quant-agent research --dataset /ABSOLUTE/LICENSED/IMPORT \
  --model-config config/model.local.json --image sha256:PINNED_LOCAL_IMAGE_ID \
  --goal "Specify and test a falsifiable daily US stock/ETF hypothesis; retain negative findings."
```

Sources are imported excerpts in V1; automated academic/web acquisition is a future provider adapter. Generated Python must implement the interface in `examples/strategy.py`. The model proposes; the host freezes data, baseline, costs and gates before simulation. At most one schema/action repair and four experiment attempts are allowed per run. All six trials of an attempt share the declared assumptions; favorable controls cannot become a replacement candidate after results.

The model cannot relax the protected allocation/risk mandate or the default 5-basis-point, $0.005/share, $1-minimum cost policy. Automatic paper promotion also enforces >=0.10 Sharpe gain, a positive 95% lower bound, >=21-session blocks, >=2,000 bootstrap samples, drawdown deterioration <=2 percentage points and positive gain under doubled costs, alongside verification and qualified data. Smaller exploratory runs cannot pass that promotion gate.

`research --resume RUN_ID ...` retains frozen evidence and the same model/price configuration. `work --runs N ...` runs a bounded series of fresh hypotheses using prior memory and the research register. It stops at the configured budgets rather than creating a background automation. `--paper-config config/ibkr.local.json` queues an eligible release for the separate execution worker.

API validation is capped at **$50 total in the persistent store**: $5 adapter smoke, $35 learning benchmark, $10 research demonstration/feedback. Unknown billing retains its reservation. Keep that store across resumes/campaigns. Data subscriptions and broker permissions are external prerequisites. Genuine Grok validation started on October 10, 2026; current receipts and outcomes are recorded in [PROGRESS.md](docs/PROGRESS.md).

Validate each configured route with `quant-agent model-smoke --model-config config/model.local.json` before a research or learning campaign. Model configuration accepts only the documented fields; inline credential fields are rejected.

## Run the first real-model episode

All private API credentials use the root `.env`, including `XAI_API_KEY`; its public template is [.env.example](.env.example). Public provider endpoint, model and token prices remain configurable in [grok.example.json](config/grok.example.json). Copy that example to ignored `config/grok.local.json` when configuring a new installation. The harness uses the generic chat-completions adapter; changing providers does not change research or memory contracts. `--model-env .env` loads only the credential named by the model configuration, without executing the file or expanding its contents.

```bash
.agent-venv/bin/quant-agent --model-env .env model-smoke \
  --model-config config/grok.local.json --case json
.agent-venv/bin/quant-agent --model-env .env model-smoke \
  --model-config config/grok.local.json --case workflow
bash research/run_first_episode.sh
```

The sequence validates and preregisters the exact import before model calls, then requires both configuration-bound authentic smoke receipts. It runs a fixed 63-session trend reference against equal weight, records six matched cost trials and independent challenges, retains the decision in verified memory, proposes a distinct volatility-scaled allocation study, evaluates the unchanged 240-episode learning suite and reports paper readiness. Completed receipts are reused on resume; consumed benchmark suites remain protected. The script accepts model-configuration, private-env-file and dataset paths as its first three arguments. It does not connect a broker.

The current seven-table import is [alpaca_proxy_20261010](data/agent_imports/alpaca_proxy_20261010/manifest.json), covering SPY/QQQ/IWM through October 9, 2026. Its 46 assumed payment dates, zero-yield financing, assumed availability times, fixed current ETF basket and 176 cross-source close discrepancies are recorded in [IMPORT_AUDIT.json](data/agent_imports/alpaca_proxy_20261010/IMPORT_AUDIT.json) and [independent import verification](results/ordered_integration_2026-10-10/import_verification.json). It remains an exploratory proxy; the strict converter refuses unresolved actions/payment dates. Source qualification and paper release require a separately reviewed qualified dataset. The [frozen first specification](results/ordered_integration_2026-10-10/research/ff68fae9bfcf4801807b1477e197742a/PREREGISTRATION.md) preserves the economic rules selected before performance.

Current outcomes: [research report](results/ordered_integration_2026-10-10/research/ff68fae9bfcf4801807b1477e197742a/REPORT.md), [protected memory transfer](results/ordered_integration_2026-10-10/research/ff68fae9bfcf4801807b1477e197742a/TRANSFER.json), [learning evaluation](results/ordered_integration_2026-10-10/research/ff68fae9bfcf4801807b1477e197742a/LEARNING_EVALUATION.json), [failure analysis](results/ordered_integration_2026-10-10/learning_failure_analysis.json), [17-check authentic integration audit](results/ordered_integration_2026-10-10/first_episode_verification.json) and [idempotent resume](results/ordered_integration_2026-10-10/resume_verification.json). The research candidate's excess Sharpe was 0.7415 versus baseline 0.8394, with a -0.0979 paired gain and negative uncertainty lower bound. No financial gate was changed after seeing results.

The ordered deliverable is implemented and exercised: data import and limitations; two genuine model smokes; controlled research and rejection; verified-memory transfer; full learning evaluation and paper readiness. The failed learning gate and unqualified source prevent paper advancement. Token-based cost recorded at the configured public prices was approximately **$0.3313** for 253 genuine requests; this is a usage estimate, not a reconciled vendor bill. Replaying the completed sequence added zero requests, trials or benchmark episodes.

Recheck the preserved evidence without model or broker calls, using a fresh output filename:

```bash
.agent-venv/bin/python research/verify_first_episode.py \
  --output results/first_episode_audit_replay.json
```

## Use and validate the strategy sandbox

This Mac has a separate project-local Lima VM, rootless Docker, Docker CLI and Buildx. The VM has 2 CPUs, 3 GiB RAM and a sparse 12 GiB disk. Its only host mount is `.runtime/strategy-tmp`, read-only. The CLI/settings/VM live under ignored `.runtime/`; Lima also uses its normal user cache for downloaded VM images. It is running after validation, with no auto-start service installed.

From the workspace root, select that runtime before any generated-Python research command. `TMPDIR` makes strategy-file binds resolve inside the VM; it does not expose the data or evidence store.

```bash
source sandbox/environment.sh
.agent-venv/bin/quant-agent doctor
# If the VM was stopped:
limactl --tty=false start quant-docker
```

The exact tested arm64 image is recorded in [image.lock.json](sandbox/image.lock.json). Reproduce the container checks and the full scripted Docker workflow into new evidence files/directories:

```bash
.agent-venv/bin/python sandbox/validation/run.py \
  --image sha256:bc33f68b6b2439d2d6ecf7f94af043019448b865341ce6455d10b4841cb48a82 \
  --output results/docker_check_replay.json
.agent-venv/bin/python sandbox/validation/research.py \
  --image sha256:bc33f68b6b2439d2d6ecf7f94af043019448b865341ce6455d10b4841cb48a82 \
  --output results/docker_research_replay
```

For a rebuild, record the new immutable image ID and rerun validation before substituting it:

```bash
docker build -t polygon-research-v1 sandbox
docker image inspect --format '{{.Id}}' polygon-research-v1
# Stop the VM when it is no longer needed:
limactl stop quant-docker
```

Use an explicitly validated `sha256:...` ID for `--image`; runtime never pulls or installs packages. The build pins the Python base manifest digest and all installed NumPy/pandas dependencies. The runner seeds Python/NumPy, uses an unprivileged account, has no network, drops capabilities, limits memory/processes/output/time, and mounts only the strategy file read-only. It does not mount the evidence store, source data, grading answers, broker settings or credentials.

All 15 real checks passed on the locked Linux arm64 image: network/filesystem/credential boundaries, cgroup CPU/memory/process limits, file limits, output quotas, timeouts, invalid results, state validation, seeded repeatability and checkpoint replay. These checks validate the declared controls, without proving immunity to every kernel/container exploit. Other architectures or changed runtime/image builds need their own validation.

State is a finite JSON object <=64 KB. Histories arrive incrementally; future labels/bars cannot be read from a mounted dataset. A checkpoint restores explicit JSON state; authors must serialize any required random-generator state themselves. `doctor` detects runtime availability; its static `remaining_gates` list is a checklist, while the dated receipts establish completed validation.

## Measure self-improvement

```bash
.agent-venv/bin/quant-agent benchmark prepare
.agent-venv/bin/quant-agent benchmark preflight --suite SUITE_HASH --model-config config/model.local.json
.agent-venv/bin/quant-agent benchmark run --suite SUITE_HASH --model-config config/model.local.json
```

The complete reserved suite must fit its $35 allocation at configured prices before starting. It fixes model, context snapshots, token budgets, 40 distinct task cases, three conditions and two repetitions. Memory/answers cannot be learned during that campaign. The full paired campaign is required; a consumed suite is retired rather than reused after learning from its answers.

The release thresholds are +10 percentage points over no learning, +5 over raw logs, a positive 95% paired-bootstrap lower bound against no learning, and zero hard timing/evidence/execution failures. This suite grades structured research tasks; full-workflow integration is checked separately. Its outcome measures research competence, not trading alpha. The authentic October 10 campaign scored **23.75% without learning, 22.5% with raw logs and 21.25% with verified memory**, with paired lower bound -0.0875 and 35 hard contract failures in the memory condition. Improvement was not demonstrated. Some failures reflect exact schema/order requirements, while others contain substantive errors; [diagnostics](results/ordered_integration_2026-10-10/learning_failure_analysis.json) preserve that distinction. This inspected suite is retired. The October 11 replacement below tests explicit schemas and task-relevant retrieval on new scenarios; the original results are never retroactively rescored or reused as a fresh test.

October 11 adds richer verified-memory consolidation and a separate protocol with 40 new scenarios, explicit schemas/units/enums for all conditions, ranked verified retrieval, and a raw comparator drawn from the same underlying research evidence. Model, thresholds and original persistent budget caps remain fixed. The old campaign is preserved. New-protocol absolute scores cannot be compared to old scores as a learning gain. See [preregistration](results/learning_revision_2026-10-11/campaign/PREREGISTRATION.md) and the completed [report](results/learning_revision_2026-10-11/campaign/REPORT.md). The new learning gate also failed. All 240 replies met their output schema, but numerical/timing/decision errors remain. Five new memory findings contain 17 exactly verified observations; that coverage does not demonstrate improvement. Both inspected suites are retired.

The following commands refer to the completed source episode and the frozen replacement plan. Preparation is idempotent; completed evaluation replay returns saved results without new model requests. A partially consumed plan is retired.

```bash
.agent-venv/bin/quant-agent --model-env .env learning-revision consolidate \
  --run ff68fae9bfcf4801807b1477e197742a --model-config config/grok.local.json
.agent-venv/bin/quant-agent learning-revision prepare \
  --run ff68fae9bfcf4801807b1477e197742a --model-config config/grok.local.json
.agent-venv/bin/quant-agent learning-revision preflight \
  --plan dcf4e8a36449bbb58f5d3fc32dcb8dd85b6941bfc08e3be6a643d8f062728389 --model-config config/grok.local.json
.agent-venv/bin/quant-agent --model-env .env learning-revision run \
  --plan dcf4e8a36449bbb58f5d3fc32dcb8dd85b6941bfc08e3be6a643d8f062728389 --model-config config/grok.local.json
```

## Set up IBKR paper execution

1. Provision and sign into your IBKR **paper** account in local IB Gateway; enable socket API access at paper port **4002**, with USD base currency and the needed market-data/API permissions. Use a dedicated paper account. No account was created or changed during this build.
2. The project environment includes the official stable SDK **10.50.2** from the [IBKR download site](https://interactivebrokers.github.io/), archive SHA-256 recorded in `results/agent_v1/ibkr_sdk_download.json`. Match/validate the Gateway version using IBKR's instructions. The adapter rejects an unvalidated SDK version.
3. Copy `config/ibkr.example.json` to `config/ibkr.local.json`. Set the exact reported DU paper account, a unique client ID, and reviewed stable-ID to `conId` mappings. The port alone is insufficient identity validation.
4. For stock shorts, provide the configured current broker fee file: `{ "STABLE_ID": {"asof":"UTC_TIMESTAMP", "fee_rate":0.025} }`. Rates are annual fractions. The adapter independently requests realtime shortable share counts; both fee evidence and availability must be current within 15 minutes. Historical borrow records are required separately for research.
5. Provide current qualified daily inputs with the reviewed upcoming exchange session in the manifest. First activation requires a flat account. Later transitions preserve/reconcile the existing execution journal and risk history.

```bash
.agent-venv/bin/quant-agent paper status --config config/ibkr.local.json --dataset /ABSOLUTE/QUALIFIED/IMPORT
.agent-venv/bin/quant-agent paper activate --config config/ibkr.local.json --run ELIGIBLE_RUN
.agent-venv/bin/quant-agent paper watch --config config/ibkr.local.json \
  --dataset /ABSOLUTE/QUALIFIED/IMPORT --image sha256:PINNED_LOCAL_IMAGE_ID
```

`watch` is explicitly started by the operator, polls by default every 30 seconds, consumes the automatic release queue, and sends next-open orders only during the reviewed pre-auction window. It does not sign in, install a daemon or modify your account settings. The model is absent from the execution path; model outages/budget exhaustion cannot change a released strategy.

Paper order eligibility is prospective experimental permission. [IBKR's paper-execution limitations](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/tws-api-limitations) still apply. The broker adapter is checked against actual SDK objects/callbacks with sockets replaced by fixtures; no Gateway, real fill or five-session acceptance has been observed.

Use `paper pause` to stop new orders and cancel owned pending orders; positions remain. Unknown acknowledgements pause execution. Reconcile and use `paper resume` before proceeding; an absent unknown order is never blindly retried. After each session, `paper record-close --config ... --dataset ...` captures an independent broker close. `paper-audit /ABSOLUTE/normalized-statement.json --source-file /ABSOLUTE/raw-broker-export --dataset ... --paper-account DU...` checks opening/closing cash and positions, trade/commission matches, qualified corporate actions, and categorized borrow/interest/tax cash activity. Unsupported cash transfers block acceptance. Passing receipts enter operational memory with `strategy_alpha=false`; a new investigation is needed to change a strategy. Real statements and five consecutive sessions remain pending.

If research rejects every candidate, test infrastructure with an operator-created, one-share engineering control in a dedicated paper account:

```bash
.agent-venv/bin/quant-agent paper control --config config/ibkr.local.json \
  --dataset /ABSOLUTE/QUALIFIED/IMPORT --asset-id REVIEWED_STOCK_ID --target-shares 1
.agent-venv/bin/quant-agent paper cycle --config config/ibkr.local.json --dataset /ABSOLUTE/QUALIFIED/IMPORT
```

Advance the stock control targets `1 -> 0 -> -1 -> 0` and ETF targets `1 -> 0` across the session campaign, reconciling each fill before a transition. These releases bypass economic qualification only to prove execution; qualified inputs and risk checks still apply. They carry `alpha_claim=false`, and the research model cannot create them. Earlier sends must become terminal before unsent orders resume, and the remaining batch is checked again against settled cash and margin.

Defaults: $100,000 allocation, gross target <=100%, absolute target per security <=25%, integer quantities, 5% cash buffer, 150% restricted short collateral, 0.1% prior-volume participation. Protective daily loss and drawdown budgets are 2% and 10% of the configured allocation. New orders require both conservative settled cash and broker margin availability. These are V1 operating defaults, not recommendations about your portfolio.

## Verify and recover

```bash
.agent-venv/bin/python -m unittest discover -s tests -v
.venv/bin/python research/test_backtest_engine.py
.agent-venv/bin/quant-agent runs
.agent-venv/bin/quant-agent --store .quant-agent backup /ABSOLUTE/NEW_BACKUP_DIRECTORY
```

The backup command takes a consistent SQLite snapshot and copies/verifies its referenced artifacts into a new directory outside the running store. Restore with `--store /ABSOLUTE/NEW_BACKUP_DIRECTORY`; licensed inputs must be backed up separately under their data rights. Restarts retain frozen specifications, uncertain API reservations, memory, paper batches/intents and execution IDs. Schema migrations, multitenant sharing, model-weight training, automatic new procedure authoring, production/live-capital deployment and a web dashboard are outside V1.
