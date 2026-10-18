# OAuth and market-data PR integration

Workstream: `tau-open-pr-main-merge-20261018` · 2026-10-18 Asia/Shanghai.
Status: in progress; advisory reservation active.

User authorized pulling latest GitHub main, combining PR #10 (broker OAuth) and
PR #11 (Databento primary/setup), resolving conflicts, committing and merging on
GitHub. Tracked checkout was clean; preserve existing untracked evidence.

Owned paths: conflicts introduced by merging these branches, relevant app/test
contracts where required for compatibility, PLAN.md, root mvp.md, relevant README/
operator handoffs and this evidence directory. Root serializes shared-file edits.
Independent reviewers use immutable commit IDs and make no edits.

No-touch: private environments/key material, execution/order/live gates, schema
runtime/migrations, production services, unrelated sibling work and result archives.
Preserve upstream changes; do not revert newer main merely to remove conflicts.
No paid/provider/model calls, production deployment or trading activation.

Next: import current main, integrate both PRs locally, inspect compatibility and
run full offline/backend/frontend checks before committing and GitHub merges.
Record exact remote commit/tree checks and synchronize local main at completion.

## Latest-main import and compatibility findings

Git HTTPS transport timed out twice without updating refs. Read the GitHub Git
database through the authenticated API, reconstructed and hash-verified all 68
commits plus 251 trees and 200 missing blobs, then fast-forwarded local main to
`070043758f70011bfbd2ec139348c96745f81b30`. This preserves exact Git history.
Local baseline/private fingerprints stay in the private local BASELINE.json; do
not publish those fingerprints. MAIN_IMPORT.json contains only public metadata.

OAuth integration conflicts: PLAN.md, mvp.md, app/static/app.js and index.html.
Retained both progress histories and newer main Funds layout; restored broker
callback account route alias, generation-safe mount and late Funds read guard.
Kept latest main removal of unused session script tags, adding only broker assets.
Server/schema auto-merge retains all newer main migrations/routes and adds broker
logic; independent backend review found no session/schema contract collision.

The earlier canonical broker-only migration guide contradicted new main AGENTS.
Updated it to the full reviewed app.schema entry point and marked the older
archive/runbook superseded. No database command was executed.

First merged OAuth/backend regression: **16 failed, 1,110 passed, 9 skipped**.
Failures concern provider/copilot test fixtures missing the new upstream risk/exec
reads (12), /api/me fixture missing spot-availability data (3), and a stale CSS
font-location assertion (1). Test-only compatibility fixes are being checked; no
business control was removed to make tests pass.

Original frontend integration suite also fails on immutable latest main itself:
**0/12 pass**, all at VM setup referencing removed strategyDeploymentHtml and
related old workspace helpers. Reconciled tests exercise the current viewStrategy/
viewRun, actual typed-LIVE/demo gates, escaped output, saved-vs-what-if separation,
market-picker, run controls and late callback/navigation behavior. Together with
unchanged standalone broker/session modules: **58/58 Node tests pass**.

All source integration remains local pending final tests and exact-head GitHub
publication. Execution/risk/order source stays identical to latest main; private
environment and production services are unchanged.

## OAuth plus latest-main verification

Test-only fixture reconciliation passed 90 focused Python cases. Full current
OAuth+main regression: **1,126 passed / 9 skipped** (9.79 seconds). All **58 Node
tests pass**. Syntax and whitespace checks pass. Broker account route alias and
late-response tests exercise the real mounted controller, including an old host
that remains connected after navigation. Independent reviewers found no remaining
backend/frontend integration issue. Newer main's agent/engine/repository/worker/
execution source is byte-identical to imported main, apart from additive broker
server/schema changes already reviewed. Next: commit this tested merge and then
combine PR #11 locally before either GitHub merge.
