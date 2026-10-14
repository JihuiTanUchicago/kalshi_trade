# Research sessions and strategy artifacts frontend

October 15, 2026, Asia/Shanghai. **Implemented and offline/browser verified; ready
for review, not deployed.** Branch: `codex/research-artifact-workspace`, based on
upstream `e40d060a8b2fb0d159e030834e829e105d4cdc17`.

## Final behavior

- Research sessions have conversation, original hypothesis, activity and all-status
  strategy links on the left. Opened strategies appear as closable tabs on the right.
  Tabs retain identity, independent scenarios and reading position; keyboard arrows,
  Home/End and close/focus behavior are supported. Mobile switches panes and returns
  to conversation when the final artifact closes.
- Every artifact keeps the full strategy sheet: thesis, plain rules, exact spec,
  in-sample/unseen P&L and trades, return/capital/tries, equity curve, dataset/cutoff,
  latest trades, gates, what-if controls and deployment. Late responses cannot replace
  a different selection. Scenario errors restore saved evidence, and deployment uses
  the saved rule rather than the displayed scenario.
- Research owns the strategy library and filters; old `/strategies` URLs remain
  usable. Adjustments follow available ancestry; standalone/missing-ancestor records
  remain inspectable. Position adds passed candidates with the same deployment
  component, alongside its original board, positions, Pause/Stop, chat and autopilot.
- Session conversation has separate drafts/history per user and family, immutable
  message/proposal targets, cursor polling/deduplication, retries and manual revision
  comparison. Capability, current-target and passed-revision evidence guard actions.
  State survives SPA navigation and clears on sign-out/reload. The real scoped chat
  routes are still absent: show Not connected, retain drafts and disable writes.
  Account-wide Position chat is never used as a fallback.
- Remove redundant statuses/counts/headings, generic sample invitations, repeated
  message target labels and duplicate navigation. Preserve accessible labels and source
  target metadata. Position cards keep saved stakes, distinct paper/live actions and
  one platform-wide live notice, plus individual restrictions. Landing waitlist/sign-in
  actions, empty-dashboard research access, Account balances and Community copy are
  simplified. Distinct proposal and deployment actions remain.
- Synthetic conversations are labelled Sample conversation. Fixtures keep one current
  revision card and four chronological messages, including the earlier proposal/test
  stages; actual backend messages or candidate records are never merged or deleted.
- Content hashes/load order cover all three small vanilla-JS helpers. No dependency,
  framework, schema, worker, collector or execution feature is introduced.

## Upstream compatibility

The editing preview was based on `99a5399`; this branch incorporates the subsequent
18 upstream commits. Explore/Hot Markets, minute market data/CSV, 50-row library
pagination, automatic market selection, depth/run-forever controls, six research
markets, credit confirmations and welcome-credit behavior are retained. Run-scoped
queries keep upstream's 500-row limit and return candidates while research runs.
Repository, agents, schema and execution guards exactly match the current upstream.

Deployment controls preserve upstream's explicit passed/void/rejected choices and
unvalidated-result warnings. Position highlights passed candidates. Research-only
market restrictions, global live availability, account/YES-side checks and typed LIVE
confirmation are retained. This work never enables trading or changes risk caps.

An upstream mismatch was found in browser verification: public System navigation
still hit an obsolete frontend admin redirect. That redirect is removed. The existing
authenticated route and backend owner-scoped activity remain; Admin remains private.
The only server diff is static-asset versioning and the Account label in an error.

## Reproducible verification

From `kalshi_trade_infra/`, with its pinned Python environment configured:

```bash
node --check app/static/app.js
node --check app/static/session-data.js
node --check app/static/session-chat.js
node --check app/static/research-artifacts.js
node --test tests/test_app_sessions.mjs tests/test_session_chat.mjs tests/test_research_artifacts.mjs
APP_TEST_MYSQL=0 AWS_EC2_METADATA_DISABLED=true .venv/bin/python -m pytest tests/ -q
```

**157 Python passed, 7 opt-in MySQL skipped; 29 Node passed; 24 browser and 14 HTTP
checks passed.** [Verification](VERIFICATION.json), [Python](PYTEST.txt),
[Node](NODE_TESTS.txt), [browser](BROWSER_CHECKS.json), [HTTP](HTTP_CHECKS.json).
Tests use the existing pinned Python 3.12 environment. Browser/HTTP acceptance uses
actual GET handlers with explicitly synthetic repository/chat/Kalshi/S3 data; all
providers and financial writes are disabled. The only scenario POST is rejected to
verify saved-evidence error handling. No agent/research/deployment/payment action runs.

The initial suite had one obsolete System-is-admin-only assertion after upstream
made its API public. It now checks the actual Admin endpoint plus public System's
owner filter/user-count privacy, and the final suite passes. Selector/case, cross-realm
array and full-reload versus SPA probe corrections are recorded in
[diagnostics](PROBE_DIAGNOSTICS.json); corrected checks pass. The System redirect
failure above was an actual upstream frontend issue and is fixed in this branch.

Desktop and 360/760px layouts were checked. Inspected screenshots:
[desktop](WORKSPACE_DESKTOP.png), [phone conversation](WORKSPACE_MOBILE_CHAT.png),
[phone artifact](WORKSPACE_MOBILE_ARTIFACT.png). Normal viewport is restored; the
temporary 8096 server/tab is stopped. `contract_preview.py` can replay the synthetic
GET preview from this directory; profile flags live in `/tmp/tau-frontend-pr-profile.json`.
Default reads deliberately return 404 for scoped chat. `fixture_chat`, `many_strategies`,
`empty_deployments` and other labelled fixture switches never implement product APIs.

## Ownership and remaining gates

The isolated checkout contains only final frontend/helpers, focused tests, final
product/design/API/usage records and these compact synthetic receipts.
[Preservation](PRESERVATION.json) confirms shared main remains at `99a5399`, with
290 non-evidence source files unchanged and only the reserved PLAN entry edited.
The existing 8090 editing preview stays running. User MVP/its existing PR, Polygon
feed integration, standalone original, secrets, independent design prototype and
historical source backups are excluded. GitHub's upstream objects were recovered
through authenticated REST after direct Git transport failed; every object hash and
repository connectivity were verified.

Next boundary: implement `app/SESSION_CHAT_API.md` persistence, ownership, worker
context, idempotency and revision execution, then perform authenticated non-production
MySQL/account/provider acceptance. History beyond the existing list windows needs
pagination. Live integration, deployment and real trading remain separate work.
