# October 17, 2026 — local integration release candidate

Reporting date: **2026-10-17, Asia/Shanghai (UTC+08:00)**. This draft separates
today's local work from fetched upstream history and older uncommitted changes.
It is a preparation record; no new commit, push, GitHub release or deployment has
been performed by this integration workstream.

## Integration target and current state

- Local main baseline: `f8ff5e22fb65ca24e9407d8fcc75a9734262a487`.
- Fetched main target: `0bd3bcf6ab80fd68d28594b63f11aad091326a19`.
- The range contains **67 upstream commits, including merge commits**. The baseline
  is an ancestor of the target. These commits are upstream contributions, not 67
  locally authored changes in today's workstream.
- Local modified/untracked sources are reconciled against the target in an
  isolated checkout. The original snapshot and historical evidence are preserved
  in `tau-main-backup-20261017_170009` beside the shared repository.
- **Combined validation passed and shared local main is updated.** Main is at
  `0bd3bcf`; 58 reconciled local source files remain unstaged/uncommitted. Six
  overlap files are resolved. Shared-checkout tests: **849 infra Python passed /
  9 skipped; 137 sibling passed / 22 skipped; 39 frontend tests passed**. Eleven
  synthetic browser route/theme checks and focused streaming/control/artifact
  interactions pass with no page errors. Private files and historical evidence
  are preserved. No new commit, push, PR or deployment was made.
- [Integration handoff](HANDOFF.md) records the recovery boundary and final checks.

## Today's local source work and provider acceptance

| Work | Implemented and verified locally | Remaining acceptance |
| --- | --- | --- |
| **Massive FX, Treasury/funding and options** | Independent provider adapter and actual research/copilot data-loop integration alongside Alpaca. Completed historical FX bars respect training windows; current quotes/options and latest-vintage macro series are denied to historical research. Real-key checks returned **120 EUR/USD hourly bars, 20 Treasury observations and 31 funding observations**. Funding context now preserves each series' last non-null value, observation date, age and stale state. Final workstream regression: **383 Python passed / 7 opt-in MySQL skipped**. | Tested **SPY option chains and current EUR/USD quotes returned 403** for this key. Those endpoint permissions remain unaccepted. Persistent activation is off; secure worker configuration, commercial rights and a genuine queued worker/model canary remain pending. |
| **Databento historical stocks/ETFs and explicit futures** | Historical native OHLCV adapter, availability/provenance, completed-interval cutoffs, cost preflight and data-context reservations. **95 new offline tests**; implementation regression **478 passed / 7 MySQL skipped**. Real provider data reached `AgentMarketData.ask` with a scripted model: **10 SPY bars (EQUS.MINI) and 10 ESZ6 bars (GLBX.MDP3)** for October 16, 14:00–14:10 UTC. Repeated requests added no network call or reservation. | Persistent activation is off. Dataset/worker configuration, durable account/user/run-wide paid-data accounting and a genuine queued worker/model canary remain pending. Streaming and equity/futures execution/backtesting are separate scope. |
| **Exa current and historical web/publication research** | Native Search, Contents and publication-intent retrieval through the actual knowledge adapter, with host citations, provenance, cancellation and usage metering. The user requested removal of **all Exa app request/dollar/month/batch/round quotas and forced five-result sampling**; the unpublished quota DAO/schema dependency was removed. Existing transport/context and historical safeguards remain. **80 Exa tests**; quota-removal regression **558 passed / 7 MySQL skipped**. Current Search/Contents/publication checks returned **10 / 1 / 10** sources/pages. After pay-as-you-go activation, historical Snapshot also returned **10 / 1 / 10**, all HTTP 200 at cutoff **2026-10-10T08:53:56Z**; the cache repeat used no extra HTTP. | Both local flags are enabled, but the actual production worker must load the environment and pass a genuine queued worker/model acceptance run after authorized deployment. Snapshot's current discovery/ranking is explicitly not historical ranking or qualified executable backtest features. |

Provider reads used actual HTTP and **scripted validation models**. No real LLM
reasoning or queued production worker was accepted by those checks. Provider costs
are not inferred from test counts: Massive cost was not reconciled; Databento's
SPY estimate/reservation was **$0.000006258488**, futures **$0**; Exa current responses
reported **$0.015**, while successful historical Snapshot responses supplied no
cost telemetry. These figures are not reconciled vendor invoices.

Databento's user-authorized test had no spending ceiling; it remained a small,
bounded read and did not activate future autonomous spending. Its missing-key
interruption and recovery are retained. Exa's earlier 403 / `SNAPSHOT_NOT_ON_PLAN`
attempts and initial quota-based implementation are also retained as history;
the passing pay-as-you-go milestone supersedes the entitlement block and the
quota-removal milestone supersedes the old quota policy.

Evidence:

- Massive source integration (local archive: `../massive_integration_2026-10-17/HANDOFF.md`) and
  real-key endpoint checks (local archive: `../massive_integration_2026-10-17/live_2026-10-17/HANDOFF.md`).
- Databento source integration (local archive: `../databento_integration_2026-10-17/HANDOFF.md`) and
  real SPY/ES acceptance (local archive: `../databento_integration_2026-10-17/live_2026-10-17/HANDOFF.md`).
- Exa initial milestone (local archive: `../exa_integration_2026-10-17/HANDOFF.md`),
  quota removal/current reads (local archive: `../exa_integration_2026-10-17/unlimited_2026-10-17/HANDOFF.md`),
  earlier Snapshot activation attempt (local archive: `../exa_integration_2026-10-17/snapshot_activation_2026-10-17/HANDOFF.md`)
  and passing Snapshot acceptance (local archive: `../exa_integration_2026-10-17/paygo_acceptance_2026-10-17/HANDOFF.md`).

## Today's local frontend sync and unfinished news work

- An earlier local main sync reached `f8ff5e2`, incorporating the already merged
  Alpaca PR #8 and upstream Tau/Meridian theme switching. It preserved Tau's local
  Research artifacts and consolidated Settings, with the theme section added.
  That milestone passed **299 Python / 7 MySQL skipped, 31 Node and 8 synthetic
  browser checks**. Authenticated theme persistence still needs the configured
  backend and `ui_theme` schema migration. These are earlier results, not the
  final combined-tree results. Handoff (local archive: `../main_frontend_sync_2026-10-17/HANDOFF.md`).
- Full Tau restored separate library navigation between Research and Explore,
  then the user renamed its tab and page heading to **Strategy**. The routes,
  filters and Research artifact links remain. JavaScript syntax and six original
  navigation checks passed; the final label had a narrower browser check.
  Navigation and label history (local archive: `../strategy_library_nav_2026-10-17/HANDOFF.md`).
- **World Monitor is active work in progress.** The local snapshot contains an
  independent news client, local first-observed/versioned journal and agent news
  wrapper/tools under development. The active handoff plans HTTP/journal/cutoff,
  citation, coexistence and actual-entry-point verification; it does not record
  completed acceptance. Historical access must use locally observed evidence
  from before the cutoff. Hosted/self-hosted configuration and any required
  subscription remain operator choices. This release preparation preserves the
  WIP; it does not certify the feature complete or activate it.
  Active workstream (local archive: `../worldmonitor_integration_2026-10-17/HANDOFF.md`).

## Fetched upstream changes — 67 commits, separate attribution

The fetched range includes the statistically rigorous research pipeline and
gatekeeper, immutable experiment/pre-registration ledger, purged walk-forward
and locked-holdout partitions, multiple-testing correction and stricter deployment
candidate requirements. It also adds cross-contract research/evaluation,
order-book depth/provenance and kernel-sandboxed arbitrary-code research strategies.
Cross-contract live deployment and code-strategy live/paper execution remain gated.

Other upstream groups include demo-host-isolated per-user execution and separate
live/demo/paper funding buckets; NO-side execution behind a default-off live flag;
risk force-sell/portfolio caps and partial-fill accounting fixes; research streaming,
markdown, pause/resume and resilience; Bedrock timeout/retry handling; and community,
dashboard, strategy-curve and Dev Log changes.

Upstream expands Kalshi sports/NBA and crypto through a market-aware feed. Its
**TAO Phase 1 venue is research-only**, dormant without its key/data configuration,
with no wallet/order implementation. The upstream documentation's deployed/live
statements are preserved as inherited reports; this local integration did not
perform or independently verify those deployments. No local feature activation
or weakening of existing live-trading safeguards is implied.

Reproduce the fetched count/history without external calls:

```sh
git rev-list --count f8ff5e22fb65ca24e9407d8fcc75a9734262a487..0bd3bcf6ab80fd68d28594b63f11aad091326a19
git log --oneline f8ff5e22fb65ca24e9407d8fcc75a9734262a487..0bd3bcf6ab80fd68d28594b63f11aad091326a19
```

## Older uncommitted work carried forward

- **Tau frontend, October 14–16:** session-scoped conversation UI/API contract,
  Research strategy-artifact tabs/state and scenario handling, consolidated
  Settings, dashboard/Hot Markets presentation and supporting assets/tests.
  These predate today's provider integrations. The rejected broad line-cleanup
  redesign was reverted; it is not the candidate being released. Today's main
  sync and Strategy label update are recorded separately above.
  Artifact workspace (local archive: `../research_artifact_workspace_2026-10-14/HANDOFF.md`),
  session UI and backend boundary (local archive: `../session_chat_ui_2026-10-14/HANDOFF.md`),
  Settings (local archive: `../settings_integration_2026-10-15/HANDOFF.md`),
  revert (local archive: `../frontend_line_cleanup_revert_2026-10-16/HANDOFF.md`) and
  later Hot Markets alignment (local archive: `../hot_markets_alignment_2026-10-16/HANDOFF.md`).
- **Scoped chat remains incomplete at the backend boundary:** the UI correctly
  retains drafts and shows Not connected when scoped routes are absent. The
  contract's ownership/persistence, worker routing, idempotency, revision execution
  and configured non-production acceptance remain future work. Synthetic browser
  fixtures are not live backend acceptance.
- **Sibling `trading_agent_new`, October 13:** authenticated `/api/table` BTC
  reader/JSONL watch CLI, literal credential parser, examples and progress records.
  That workstream's historical regression was **144 passed / 15 Docker-dependent
  skipped**, including 22 focused reader tests. Real authenticated feed advancement
  remains pending dashboard credentials; research/model context, archive replay
  and trading execution were separate phases. These changes are preserved as
  older sibling work, not claimed as today's Tau provider implementation.
  Sibling handoff (local archive: `../../../trading_agent_new/results/market_data_integration_2026-10-13/HANDOFF.md`).

Final integration checks, compatibility findings and the prepared publication
manifest are in [HANDOFF.md](HANDOFF.md). No private environment contents,
credentials, raw account/order responses or bulky source backups belong in a
GitHub publication bundle.
