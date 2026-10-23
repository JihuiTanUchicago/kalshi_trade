# Bitcoin perpetual data and research

Workstream: `tau-kalshi-bitcoin-perps-research-20261023` / October 23, 2026,
Asia/Shanghai. Status: **source merged on GitHub, offline/public-feed-read and
hosted full-schema/web checks verified; production rollout and activation pending**.
Advisory implementation ownership is handed off. Root owns publication evidence
and rollout preparation. The read-only production preflight has passed; installed
source reconciliation and a safe release window remain rollout gates. Usable
candle coverage, isolated perps persistence/replay and genuine queued research
remain activation gates.

Publication follow-up / October 23, 2026 / source merge complete: the user's "Ok go ahead"
authorizes publishing these reviewed changes and preparing their disabled-feature
release. Root owns the existing change set, publication receipts and fresh
read-only production preflight. PR21 merged source b7cf7c7 as main 33bfc957;
the separate dirty shared checkout is preserved. Native research remains opt-in
off and all perpetual execution is blocked. Existing research must not be
interrupted by an unconditional worker restart. Merge/release decisions require
passing CI and a fresh installed-state review; provider activation and unresolved
replay acceptance are not implied by source publication. CI39883215379 and hosted
isolated staging39883215499 passed. GitHub commit metadata proves feature b7cf7c7,
the staging synthetic merge b2f93c1 and main merge 33bfc957 share tree fde9305a.
The hosted workflow ran full app.schema on disposable MySQL and real HTTP with
synthetic broker checks; it did not test perps SQL/replay or production. See
publication/PUBLICATION.json and the sanitized hosted receipts. No production
restart, migration, source exchange or feature-flag change has occurred.

Production preflight / October 23, 2026 / inspected, rollout pending. Exact
operations commit 0e2e79c30d13bab8dec41081ef4d273d826b127c on the separate
codex/kalshi-perps-readiness-operations-20261023 branch ran once in workflow
39884723368. All five anonymous native production requests returned HTTP200
directly from the web box: 2,761 candles, six funding records and four current
observations. The 48-hour window has 120 absent minute bars; no gap explanation,
replay acceptance or activation is inferred. No production proxy change is needed
for the tested route. The bounded read-only DB session found one running research
job, zero queued/paused jobs, all four market columns already VARCHAR(48), and
both new perps tables absent. All active service perps flags are effectively off.
Source/control snapshots match before/after; temporary source and the current
public-source S3 diagnostic object were cleaned (historical S3 versions were not
inspected). No app/job/settings/schema/service mutation, private provider, model
or order call occurred. See publication/READINESS_39884723368.json and
publication/READINESS_ACCEPTANCE.json.

Fresh installed source has 120 regular source files; 21 differ from reviewed
base aa3664e, including backend and previously accepted styles. Offline classification found 11 exact known Git blob matches and 10 unresolved
exact local source copies. Eight unresolved paths are application files; the two
others are preserved diagnostic scripts. Several have accepted historical hash
receipts. Do not call all drift unpublished or replace it with a Git archive. The standard deployment
would restart workers and overwrite installed variants. It was not dispatched.
The separate operations branch contains only a read-only preflight and must not
merge into main. Its RELEASE_REVIEW.md records conditional rollout/rollback gates.

Timeout follow-up / October 23, 2026 / resolved locally, ownership handed off.
Direct requests bypassed the configured Mac proxy and failed for API and control
hosts. Explicit credential-free proxy routing returned HTTP200 for every control.
Config now accepts TAU_KALSHI_PERPS_PROXY_URL without ambient auth, cookies,
`.netrc`, redirects or TLS-verification changes. Actual native titles are
quantity-denominated BTC, with asset class Crypto; parsing now verifies the exact
title quantity against contract_size × underlying_multiplier instead of missing
the instrument. All 10 actual client/collector HTTP calls passed: 2,761 production
and 2,822 demo candles, six funding records and four observations each. Both
48-hour candle windows have gaps, so continuous replay is not accepted. No raw
prices/accounts or proxy URL/credentials were saved. No DB, service, flag, order,
commit or deployment operation occurred. See PUBLIC_FEED_CHECKS.json and
NETWORK_DIAGNOSIS.json. Deploying with perps disabled does not depend on this
feed; activation still requires server, DB, usable coverage and queued-run checks.

Initial implementation scope: integrate Kalshi perpetuals, starting with Bitcoin
market data and research, while keeping live trading disabled. That phase made
no account operation, paid/model call, commit, push, PR, migration, production
activation, job/service mutation or deployment. The later publication approval
above supersedes the original publication boundary. All perpetual paper/demo/live
execution remains blocked; existing binary trading flags are unchanged.

## Source and ownership

Worktree:
`/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-bitcoin-perps-research-20261023`

Branch: `codex/kalshi-bitcoin-perps-research-20261023`.
Base: `aa3664e420fe4fdf538cd434e4c91e73ee0875cf`, exact GitHub
main at the initial check. Published source HEAD: b7cf7c754e09a50e8f0bc6278dbf275f0f0f2a8b.
Managed worktree creation was unavailable for Polygon
(not a Git repository), so this is a regular linked worktree of the actual repo.
Initial network Git fetches failed; commit metadata and tree were imported with
SHA1 verification from GitHub. Publication repaired missing ancestor history by
an explicit credential-free proxy fetch with refetch/no-op negotiation, then
used a normal commit/push and head-matched PR merge. Do not reset or overwrite
the separate dirty shared checkout.

Owned: new `app/kalshi_perps_{data,repository,collector,backtest}.py`, new tests,
narrow research/API/schema/market integration, additive engine rejection,
functional guards and price/cost labels in both frontend bundles, setup docs,
PLAN/mvp/public planned-devlog and this evidence directory. Root serialized
shared files. Agents handled separate data/simulator/guard/integration/UI paths
under the repository's explicit parallel-work instruction.

Protected: binary pricing/order/risk mechanics, execution kernel, live engine,
broker/vault/OAuth/Alpaca services, credentials/environments, resources, existing
jobs/services, sibling products and unrelated progress. Of 16 baseline protected
files, only `app/engine.py` changes: explicit additive perpetual rejection before
data/order work. Its existing binary mechanics and flags remain unchanged.
See `BASELINE.json` and `PRESERVATION.json`.

The development-progress skill was applied. Named project ponytail, impeccable,
devlog-sync and security-review skills were searched in installed roots/cache
and unavailable. No use of those commands or a security scan is claimed.
Devlog's PLANNED entry was updated manually; independent manual control/code
review was performed.

## Implemented behavior

- `btc_perp` is a first-class research market, kind perpetual, underlying BTC-USD,
  with internal alias BTC_PERP. The real native ticker is discovered and verified
  from Bitcoin metadata; the alias never reaches the binary or margin API.
- Default-off public GET client has fixed production/demo hosts and no credentials,
  account, order, transfer or signer path. It collects completed one-minute bars,
  historical funding and current timestamped observations. Exact financial
  decimal strings survive client, append-only JSON storage and replay.
- A manual bounded collector supports count/hash-only checks and explicit
  `--persist` backfills. It installs no background schedule and performs no
  migration. App schema includes two additive perpetual tables; full schema now
  passes in hosted disposable MySQL. Actual perps persistence/replay and production
  migrations remain unverified. Production/demo batches and frozen source bindings cannot mix.
- The first partition freezes 60/25/15 Research/Validation/Holdout windows with
  24-hour holding/lookback embargoes. All phase loaders use the experiment's
  frozen source. Exact committed batch ID/fingerprint manifests exclude even
  lower AUTO_INCREMENT IDs committed after the freeze. Missing/changed pinned
  batches fail closed. New bars/revisions never reset holdout automatically.
- Trusted causal momentum, mean-reversion and observed-funding rules use completed
  bars and next contiguous opens. Arbitrary code, learned models and cross trades
  are explicitly rejected in this phase to avoid future-window access. One
  position, at most 1x available capital, fixed 24-hour max hold; default research
  capital is $100 (binary default remains $5).
- Decimal P&L respects native price/quantity units, signed funding, fractional
  steps and post-loss allocation. Costs are fixed 12bps taker plus 5bps adverse
  slippage per fill. These are uncalibrated scenario assumptions, not account fee
  or fill acceptance. No margin/liquidation model; short losses can exceed capital.
  Finalized funding is cost-only; estimates require decision-time observation.
  Missing funding/bars and delayed observations cannot generate fictitious trades.
- Preregistration, trial counting, bootstrap, PSR/DSR and multiple-testing gates
  reuse the existing pipeline, with continuous sign-flip controls and capital
  returns. An undersampled holdout remains INCONCLUSIVE and spends its one-way
  evaluation. Statistical success does not authorize execution promotion.
- Manual and agent research entry points reject disabled/malformed configuration
  before queuing work. API/agent/proposal/resume and direct engine guards reject
  primary, cross-leg and mismatched perpetual exposure in all execution modes.
  Pause/stop remain possible. Both themes label results Research only, use USD
  prices, explain the scenario, and hide trading/binary replay/what-if controls.

## Verification

Interpreter:
`/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/kalshi_trade/kalshi_trade_infra/.venv/bin/python`
(Python 3.12, existing prepared dependencies). Commands run from this worktree's
`kalshi_trade_infra/`:

```text
<interpreter> -m pytest tests/ -q
1899 passed, 10 skipped in 25.81s

node --test --test-reporter=dot tests/*.mjs
196 passed; exit 0

TAU_TEST_THEME=meridian node --test --test-reporter=tap tests/test_production_ui_reconciliation.mjs
8 passed, 0 failed

<interpreter> -m py_compile app/*.py data_pipeline/*.py
node --check app/static/app.js
node --check app/static/app.meridian.js
git diff --check
All pass
```

The full baseline was 1,676 passed / 10 skipped; this adds 223 Python cases.
The initial implementation milestone was 1,865 / 10; the timeout follow-up adds
28 transport/isolation cases and six native metadata-label cases. Eighteen focused
UI cases cover both themes; the 196+8 frontend results are carried forward from
the unchanged bundles. Synthetic native responses run
through actual client/collector, append-only repository, frozen phase loaders,
nonzero simulator trades and gatekeeper records. Independent golden P&L/funding,
quantity/cutoff/gap, source mutation and all-mode execution rejection cases pass.
Tests prohibit network/model/order methods where appropriate; they are not a real
provider or user-account acceptance run. UI evidence is VM behavior verification,
not a new visual/device acceptance claim.

Review found and fixed naive-UTC conversion under non-UTC hosts and late lower-ID
collection commits entering a high-water-only source. New tests reproduce both,
including UTC/Shanghai/New York hosts and exact committed manifests. Independent
manual final review found no remaining concrete blocker. Earlier wrong-runtime
collection failures (Python 3.7/no pytest) and draft fixture/boundary failures were
superseded by prepared-runtime passing checks, not treated as functionality proof.

## Pending acceptance and next boundary

Initial anonymous public production and demo probes reported ConnectTimeout;
this was superseded by the proxy diagnosis and successful actual public collector
checks above. Native size-title/asset-class compatibility and 48-hour public
retrieval now pass. Sample candle gaps, historical depth/version validity, actual
deployment-server routing now passes via the actual pinned client and collector.
Actual perps SQL/replay and genuine queued-model acceptance remain unverified.
Hosted full-schema MySQL and web compatibility pass;
that is a narrower check. No collector/worker persistent opt-in flag was changed.

Follow [setup and limitations](../../app/KALSHI_PERPS_RESEARCH.md): first obtain
the public count/schema check on the actual deployment host, then migrate,
resolve usable historical coverage and replay in an isolated database before
ordinary authenticated queued research. The manual public_feed_check.py is
read-only; --system-proxy is an explicit diagnostic-only opt-in. A successful
public feed check is not contiguous-replay or production activation acceptance.
No test user,
session, billing bypass or order was created here. The disabled-feature production
rollout is authorized within the scope above and is pending fresh installed-state
review; it has not occurred. Activation is a separate acceptance boundary.
Current observations cannot reconstruct missing historical estimates. The fixed
cost and next-open assumptions need calibration; future automatic window rotation
and arbitrary code/model research are separate work.

PLAN, mvp working queue, app README, research-design addendum, setup guide and
public PLANNED devlog agree on merged source versus pending production acceptance.
Other workstreams' historical status is preserved and is not advanced here.
See `VERIFICATION.json` for the final scoped receipt.


## Publication/preflight handoff boundary — October 23, 2026

Publication/merge and actual-server read-only readiness are complete; advisory
ownership of this milestone is handed off. This is not production deployment or
activation acceptance. Post-merge receipts and tracker/setup/devlog wording in
this worktree are local handoff updates; the immutable published source is b7cf7c7
merged as main33bfc957. The operations branch remains immutable at0e2e79c3 and must
not merge into main. Its later review documents are copied into publication/ here.

Next safe action: obtain a bounded read of the eight unresolved application files
listed in publication/SOURCE_COMPARISON_REVIEW.md and verify exact hashes before
reconciling the feature with installed source. Preserve unrelated billing, model,
repository, styles/bootstrap and diagnostic bytes. Prepare/test a complete
installed-variant candidate, full candidate schema with bounded lock/recovery
handling, retained whole-package backup and origin/public HTTP/hash acceptance.
Use a fresh job inventory; the single running count above is point-in-time,
not a claim that the job remains active indefinitely. Do not dispatch the normal
all-worker deployment, mutate jobs, or infer worker-loaded bytes from PID equality.
A worker upgrade/activation requires its own suitable idle boundary and completed
perps persistence/replay/queued-research gates. No automatic follow-up was created.
