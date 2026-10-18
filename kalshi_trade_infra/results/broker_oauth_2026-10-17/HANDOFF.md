# Broker account OAuth integration

Workstream: `tau-broker-oauth-20261017`; 2026-10-17T22:21:26+08:00, Asia/Shanghai.
Status: implemented locally / offline verified; advisory reservation handed off before finishing.

Current owner: the user chose teammate deployment. See [teammate publication/handoff](teammate_handoff_2026-10-17/HANDOFF.md) and [operator guide](../../app/BROKER_OAUTH_DEPLOYMENT.md). Earlier desktop-access requests are superseded.

Latest rollout: [production preparation](production_2026-10-17/HANDOFF.md). User authorized deployment; OAuth pair is now encrypted in GitHub Secrets. No AWS/SSH access is available here, so actual runtime injection/migration/deployment/consent is pending. Prior scopes below describe historical milestones, not revocation of current deployment authorization.

Latest credential follow-up: [credentials check](credentials_2026-10-17/HANDOFF.md). The user has since supplied the Alpaca OAuth pair locally; prior missing-credential statements below describe the earlier implementation milestone. Public callback availability, persistent runtime encryption setup and real consent remain pending.

Scope: user-authorized broker-account connections in Alpaca → Robinhood → Interactive Brokers order. US individual user accounts; existing provider market-data keys are separate from OAuth app credentials.

Owned paths: additive app/broker_*.py and matching tests; narrow app/server.py and app/schema.py integration; shared broker-connections static module and narrow Settings Account integration in both themes; .env.example placeholders; app OAuth setup/deployment guide, README, PLAN.md, root mvp.md and this evidence directory. Root owns shared files. Subagents own isolated storage, provider adapters and frontend files.

No-touch: private .env secret values/activation flags, existing market-data adapters, engine/live guards, data_pipeline execution, trading_agent_new, historical evidence, unrelated worktrees, provider accounts and production infrastructure. No orders, deployment, live activation, production migration, commit or push authorized by this implementation workstream.

Plan: secure state/session binding and encrypted per-user grants; official provider protocols with honest app-registration gates; compact Settings connections; offline API/provider/storage/UI tests, full regression and auth review. No successful provider connection claimed until real user consent and account checks pass.

Applicable AGENTS.md asks for /ponytail, /impeccable, /security-review and /devlog-sync. Those commands are not installed in the available skill catalog or repository; use current primary provider docs, focused tests, review and manual tracker synchronization. This does not imply those named commands ran.

External gates: registered Alpaca app credentials and callback; Robinhood hosted-client eligibility/registration; IBKR vendor onboarding and signing/encryption/DH material; deployment-owner URL and secret injection. Work continues independently of these inputs.

User input received: Alpaca OAuth app is not registered. Production origin confirmed as `https://d1gfpzcosqrjya.cloudfront.net`. Only APP_PUBLIC_URL was added to ignored local .env (mode 0600); all existing secret assignments/flags preserved. No provider app credentials or APP_SECRET_KEY are present in this local product .env; the production service may inject its persistent encryption key separately. See LOCAL_CONFIGURATION.json (hashes/readiness only).

## Implemented and verified

All three official provider adapters are integrated with authenticated server
routes and both shipped Settings themes. Storage uses two additive DDL tables,
AES-256-GCM context-bound grants, hashed ten-minute session-bound state, a
consume/claim transition and per-user locking/latest-attempt fencing. No network
call runs under a repository transaction. No new order dispatcher or generic MCP
tool access is connected.

Full infrastructure: **1,020 passed / 9 skipped**; frontend: **55 passed**;
independent auth/protocol focused checks: **141 passed**, no actionable blocker.
Python compilation, JS syntax and whitespace pass. Synthetic broker-card browser
checks pass at 1280px and 390px in both themes; screenshots are labeled synthetic
in VERIFICATION.json. Root inspected desktop/mobile screenshots. Anonymous public
Robinhood metadata returned 200 twice; PUBLIC_DISCOVERY.json records only public
issuer/endpoints/scopes. No broker client registration, real consent, token,
account, order or paid/model call occurred.

Exact commands/results: VERIFICATION.json. Independent review: REVIEW.md.
SOURCE_MANIFEST.json records selected source hashes and zero private-value/full
private-key matches. Protected engine/data/sibling source and Polygon root env
are unchanged; Tau private env differs only by the user-confirmed public origin.
No new OAuth client credential is available locally.

## Remaining gates and handoff

Start with Alpaca: register the app with the documented exact CloudFront callback
and privately add ALPACA_OAUTH_CLIENT_ID / ALPACA_OAUTH_CLIENT_SECRET. Preserve the
production APP_SECRET_KEY; the local product env does not include that server key.
Then register/approve Robinhood’s hosted PKCE client and IBKR’s vendor consumer
with separate signing/encryption keys/DH parameters. IBKR must preserve state in
the registered redirect. BROKER_OAUTH.md gives exact callback URLs, environment
names, limits, safe status command and acceptance steps.

Deployment owner must inject settings, run the intended migration and deploy
the whole app before real consent testing. Existing GitHub data-provider secrets
and loader do not include new OAuth registration credentials. No production
service, migration, live flag, commit or GitHub publication occurred. Broker-side
revocation and token-renewal workers remain separate from immediate local
disconnect and reconnect. PLAN, root MVP queue/done, app README, deployment guide
and OAuth contract are synchronized. Public Dev Logs were not advanced to imply
production availability; /devlog-sync is unavailable and manual tracker changes
are recorded instead. Advisory ownership is handed off at this boundary.
