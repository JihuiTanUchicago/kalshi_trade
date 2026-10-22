# Default header alignment operation — October 22, 2026, Asia/Shanghai

Implemented / offline verified / handed to root. Worktree `tau-header-alignment-operations-20261022` starts at local `1fe616a04322151219b71bf79a0485581f552101`. **Never merge this operations ref into main.** This task owns only this new directory and `.github/workflows/deploy.yml`; root owns `candidate.css`, all deployment pins, source/UI work, browser acceptance, shared progress records and publication/dispatch.

Only installed `app/static/app.css` may change. Candidate bytes must come from the fixed published path `kalshi_trade_infra/results/header_alignment_operations_2026-10-22/candidate.css` at exact `source_commit`, with the exact reviewed SHA256 and valid UTF8/CSS. Root builds this file from the actual installed stylesheet plus the reviewed alignment patch, preserving its 42 lines of unpublished boot/legal/autopilot styles. The operation rejects the Git-main `app/static/app.css` source path. Candidate creation and visual verification remain root-owned.

Whole installed `app/` and `data_pipeline/` are archived privately. The candidate clones those installed packages; only the allowlisted CSS bytes change, and whole `app/` is exchanged atomically. All non-target bytes and metadata must match. Explicit preservation pins bind current installed `app.js`, `boot.js`, raw `index.html`, `app.meridian.js` and `app.meridian.css`; these may differ from Git main and must stay exact. The installed boot/index and both JavaScript bundles retain theme selection behavior.

Eight original safety functions remain byte-identical to the accepted Meridian operation: `read_regular`, `safe_directory`, `layout`, `unit_state`, `exchange`, `exchange_available`, `clone_archive`, `run_schema`. Exact controls/configuration/PID fingerprints, private ownership/modes, lock, same-filesystem probe and no blind rollback/restart remain. Installed full `app.schema.main()` still runs before exchange with **120s process / 60s I/O / 3s DB lock** bounds. Schema failure may follow idempotent DB commands; it does not imply no DB command occurred. Post-exchange failure retains installed and prior state for inspection.

The runner uses the existing private encrypted S3 `bundle/*` permission through exact `bundle/header-alignment-<40hex-source>-<32hex-nonce>.json`. Remote validates bucket/key/payload hash, exactly one CSS path, UTF8 and candidate hash. No JavaScript parser runs for this CSS-only release. Explicit inventory/audit/repair/apply modes retain their prior boundaries; inventory never fetches candidates, uploads or runs schema. The metadata audit and exact-116 restrictive repair helpers are unchanged, require their own explicit phase, and never run automatically.

Rendered `/`, `/funds` and `/research` must use the new default CSS build plus the pinned unchanged Tau JS, Meridian JS/CSS and boot versions. Origin/public assets must hash exactly; `/api/version.v` must remain the installed Tau `app.js` hash prefix. CloudFront `/*` invalidation precedes canonical public 200/health/version/hash acceptance. Synthetic tests do not establish production acceptance.

## Offline evidence

**22 focused tests pass**, covering one-CSS replacement, installed extras, preservation of both themes/default JS/backend/PIDs, exact candidate path/commit/hash/UTF8, actual CSS parsing, private transfer namespace/encryption, HTML/API version separation, failure behavior and sanitized receipts. **86 unchanged Meridian tests pass in a separate process.** Python compilation, original-function equality and `git diff --check` pass. Root's final candidate `73bd0785301dff3a32df26a33f490b2e215ef066ce91fecc8f55819a81718d51` passes the actual CSS parser; this is observed evidence, not a deployment pin. No test failure preceded this passing focused run. [Receipt](OFFLINE_VERIFICATION.json).

From this repository root, with the existing pinned parser installation:

```bash
PYTHONPATH=/tmp/tau-meridian-ops-python-20261021 python3 -B -m unittest discover -s kalshi_trade_infra/results/header_alignment_operations_2026-10-22 -p 'test_*.py'
PYTHONPATH=/tmp/tau-meridian-ops-python-20261021 python3 -B -m unittest discover -s kalshi_trade_infra/results/meridian_workspace_operations_2026-10-21 -p 'test_*.py'
git diff --check
```

## Root acceptance gates

1. Review/freeze the exact installed-CSS candidate and publish it at the fixed path. Fill exact reviewed-main/source/before/after and all five preservation hashes; this handoff leaves every deployment pin null. Run the required full regression before root's commit/publication.
2. Publish an operations-only ref and obtain fresh inventory on its final exact head. Compare source/default/Meridian/schema hashes, configuration metadata, controls and PIDs with actual installed state. Use only that fingerprint for apply; any drift requires new inventory and review. Do not use a generic Git-package deploy or merge this operations ref.
3. Apply once through this workflow, require full-schema/archive/exchange success, CloudFront invalidation and canonical public hash/version/health acceptance. Complete browser verification of aligned default borders and preserved theme behavior before marking accepted.

Collect using `collect.py RUN_ID EXACT_OPERATIONS_SHA OUTPUT_DIRECTORY`. It checks the exact head before reading Actions logs and retains only `TAU_HEADER_ALIGNMENT_{PREFLIGHT,INVENTORY,RESULTS,PUBLIC,INVALIDATION,ERROR,PHASE}` JSON records. Never save or print raw Actions/SSM logs. No commit, push, network/production request, schema execution, service/job/configuration change or provider/order call occurred in this delegated task. Source/UI and shared project progress records remain root-owned.

Root review complete: full bounded delta reviewed, all8safety functions and4metadata helpers byte-identical. Root reproduced22focused tests and full1676Python/10skipped(24.78s); reviewer separately reproduced86old-operation tests. Candidate73bd0785 and unique four-rule patch reviewed against actual installeddd401217, preserving its42extra boot/legal/autopilot lines. Native default preview borders match50px at1280/1100/settled320; initial transition sample is retained as a harness diagnostic. Root filled reviewed mainbac51459 and observed CSS before/after pins for initial read-only inventory. Source/preserved pins remain null so apply fails closed until initial inventory and immutable candidate publication. No production change from this workstream yet. New code paths are the one-CSS transport/fixed candidate path/version checks only; no source/backend/control guards changed.
