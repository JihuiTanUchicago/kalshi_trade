# Latest-main integration and release preparation

October 17, 2026, Asia/Shanghai. **Complete locally / combined tree verified.**
Workstream: `tau-main-integration-20261017`; advisory reservation released.

Shared repository: `/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/kalshi_trade`.
Local **main fast-forwarded from f8ff5e22fb65ca24e9407d8fcc75a9734262a487 to
0bd3bcf6ab80fd68d28594b63f11aad091326a19**, incorporating **67 upstream commits**.
GitHub's branch was independently rechecked at that SHA before applying the result.
**58 reconciled local source files remain unstaged/uncommitted on top.** No new
branch commit, remote push, PR mutation, deployment, migration, worker activation,
private-setting change, provider/model request or trading operation occurred.

## Preserved and reconciled

The original source/evidence snapshot contains **3,018 files** and is retained at
`/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-main-backup-20261017_170009`.
The tracked patch, original status and byte/mode hashes are there. Only hashes of
private configuration were recorded; real keys were not placed in examples/evidence.
The preservation stash **2efc7a7bec9cb125651fc25eee09ea5cf1cafd09** is retained. Do
not blindly pop it onto the integrated tree; it represents the older local state.
Other pre-existing stashes, PR branches/worktrees and historical results remain.

A detached integration checkout reconciled six conflicted files before shared main
was updated: `PLAN.md`, `mvp.md`, `app/agent.py`, `app/server.py`, Tau `app.js` and
`app.css`. All other local files applied cleanly, including sibling source changes.
The original source was compared with the snapshot immediately before the stash /
fast-forward / tested-file install. The completed main has no unmerged index entry
or conflict marker, and `git diff --check HEAD` passes. Five old MVP whitespace
warnings were normalized without changing their text.

- **Research:** retained upstream frozen partitions, trial ledger/gatekeeper,
  cross-contract/TAO/sports paths, pause/reconnect and streaming proposer. Exa and
  gated news wrap after the stream-capable model adapter, persist across continuous
  chunks and compose with existing market data. Cancellation blocks post-cancel
  actions; all consumed model usage is counted once; infra failures remain unbilled.
- **Frontend:** merged the local conversation/artifact workspace, compact dashboard,
  Strategy library and Settings with upstream live feed/cards, pause/resume, floating
  autopilot, demo/live transport and the three funding buckets. Preserved measured
  slippage/replay alignment, asynchronous navigation guards, escaped markdown and
  typed LIVE gates. Meridian stays on its upstream matching JS/CSS bundle.
- **Server:** local fonts/static modules and cache versions are retained. The
  deployment conflict retains upstream NO-side feature gate and guard ordering;
  no switch was enabled and no guard was weakened. Account guidance matches the
  consolidated settings UI. Authenticated-user ownership tests remain in place.
- **Docs:** upstream and local PLAN/MVP history is preserved; inherited live/deployed
  statements are not new production acceptance. Provider capabilities stay under
  planned rollout in public Dev Logs. [Release notes](RELEASE_NOTES.md) separate
  today's local changes from 67 fetched commits, older frontend/sibling work and
  World Monitor's still-active WIP status.

## Verification on actual shared main

```bash
cd /Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/kalshi_trade/kalshi_trade_infra
TAU_ALPACA_ENABLED=0 TAU_MASSIVE_ENABLED=0 TAU_DATABENTO_ENABLED=0 TAU_EXA_ENABLED=0 TAU_WORLDMONITOR_ENABLED=0 APP_TEST_MYSQL=0 AWS_EC2_METADATA_DISABLED=true .venv/bin/python -m pytest tests/ -q --tb=short
# 849 passed, 9 skipped in 6.10s
node --test tests/test_app_sessions.mjs tests/test_session_chat.mjs tests/test_research_artifacts.mjs tests/test_frontend_merge.mjs
# 39 passed; 31 existing + 8 new merge regressions
cd ../trading_agent_new
PYTHONPATH=src ../kalshi_trade_infra/.venv/bin/python -m pytest tests -q --tb=short
# 137 passed, 22 skipped in 9.96s
```

The same combined infrastructure suite passed first in the isolated checkout
(849/9); sibling 137/22 passed there too. Targeted agent/provider checks passed
198 tests and upstream research/billing compatibility checks passed 80 tests.
Python compilation for app/data_pipeline, JS parser checks for Tau/Meridian/boot,
secret-loader shell syntax and full diff whitespace pass. Test flags were temporary
process settings; private `.env` byte values and modes are unchanged.

**Synthetic browser checks:** 11 route/theme loads pass with no rendered error,
page exception or API-fixture failure: Tau Overview, Research, run workspace,
Strategy list/artifact, Positions, Funds redirect, Settings/Account, Dev Logs and
Meridian Overview. A focused request-interception check verifies streamed thought
assembly, single progressive hypothesis cards, stable feed nodes, pause/resume,
artifact/draft preservation and gated demo/live controls. These are read-only QA
fixtures; no account, real backend, DB, provider or trading action was exercised.
Broad checks (local archive: `BROWSER_SMOKE.json`) · Focused checks (local archive: `FOCUSED_BROWSER_SMOKE.json`).

Earlier checks are preserved transparently: initial collection preceded resolution
of agent.py markers; old fixtures lacked the new demo-key/heartbeat dependencies;
all those failures were fixed and superseded by the shared-main passes. The initial
browser harness under-checked rendered errors while its old fixtures lacked the
upstream demo bucket/autopilot status; it was tightened. A later replay-endpoint
fixture gap was also filled with the documented dev_curve:null response. The final
strict browser check passes; the earlier schema reports remain alongside it.

The upstream AGENTS references Claude slash-command skills that are absent from
configured local roots after search (ponytail/impeccable/devlog-sync/security-review).
No such command is claimed to have run. Disjoint-file review, manual control-path
review, public Dev Log synchronization and the runnable checks above were used.
This integration is not an exhaustive security audit of all upstream commits.

## Publication and remaining gates

Publication manifest (local archive: `UPLOAD_MANIFEST.json`) lists source paths and small release
records for a reviewable next commit. It excludes real `.env`/keys, virtualenvs,
raw provider/account data, generated caches, historical source snapshots and bulky
QA output. Do not use an indiscriminate git add of every results directory. Existing
README links to local historical evidence need an intentional documentation export
if they should also resolve in a public GitHub bundle.

No API/model/provider acceptance was newly purchased or re-run here. The earlier
real-provider receipts remain valid within their stated scope: Exa current and
Snapshot passed; Massive historical FX/macro passed while current FX/options were
403-blocked; Databento SPY/ES historical bars passed. Production worker/model
acceptance and relevant provider entitlements/accounting remain separate gates.
World Monitor is preserved behind its existing default-off gate and remains WIP.
Scoped research-chat backend persistence/idempotency is still an unfinished contract.

The detached integration checkout is retained for inspection at
`/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/kalshi_trade-integration-20261017`.
Only temporary read-only QA servers were started; they are stopped before handoff.
The shared main checkout above is the authoritative next-upload working tree.

[Verification](VERIFICATION.json) · Install manifest (local archive: `INSTALL_MANIFEST.json`) ·
Preservation (local archive: `PRESERVATION.json`) · [Daily release notes](RELEASE_NOTES.md).
