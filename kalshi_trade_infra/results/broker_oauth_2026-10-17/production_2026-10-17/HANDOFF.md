# Broker OAuth production rollout

Workstream: tau-broker-oauth-production-20261017; 2026-10-17T23:17:46+08:00, Asia/Shanghai.
Status: encrypted GitHub sync complete / local candidate verified / production access pending; advisory reservation handed off.

Authorization: user explicitly said go ahead with the prior next steps: production deployment/schema/runtime injection and Alpaca paper consent readiness. Initial commentary also states encrypted GitHub credential sync. OAuth authorization requires the user's actual browser login/consent; no impersonation/session forging or order placement.

Owned: whole-app deployment staging/backup manifest, two-table broker-only DDL, secure OAuth client-pair runtime injection preserving all prior environment and APP_SECRET_KEY, encrypted GitHub Secret upload, intended web-service restart, this evidence directory and narrow trackers/setup/handoff updates. Read-only review delegated. Root is sole infrastructure/mutation owner.

No-touch: live flags/risk/execution/data activation settings, house/collector/agent/engine service restarts, private local env bytes, existing production encryption key, unowned server/source drift, raw account data, other worktrees, credential values in logs/Git/SSM commands. Do not run the broad existing secret loader or broad schema migrations. Build/verify against actual web origin, retain rollback app/env backups on the server, invalidate the Tau CloudFront distribution only, and prove public HTTP success.

Initial facts: callback/static asset404; local pair present/private but local APP_SECRET_KEY absent. Historical documented web instance i-077d6f7873e7836ba / distribution EEQ00Y93RTB1K require fresh AWS verification before changes. No AWS CLI found in PATH; use configured SDK if available. Existing local feature full1020/9skip +55frontend tests passed, auth/protocol independently reviewed; recheck release payload after any reconciliation.

## Latest results — 2026-10-17T23:21:44+08:00

- New OAuth pair client-encrypted and uploaded through gh stdin to repository Actions Secrets. Both names/timestamps verified; all five earlier entries and private .env bytes unchanged. Seven names total. GITHUB_SECRET_SYNC.json contains metadata only, no values/arguments/plaintext. This is storage only, not server injection.
- SDK available but no configured profile/credentials; AWS CLI absent. No Tau/EC2 target in existing SSH config. No project .env.aws or relevant AWS fields in the two known private .env files. ACCESS_DISCOVERY.json stores presence booleans only. Asked user asynchronously for AWS/SSH configuration or teammate execution; response pending. Deployment permission is already explicit and persists; do not ask for it again once access is supplied.
- Repeated pre-release full checks: **1,020 Python passed / 9 skipped in 8.88s; 55 frontend passed**. Runtime source unchanged from prior independent OAuth review. New read-only deployment review found no source blocker and identified required remote drift/key/schema/CloudFront checks. REVIEW.md and DEPLOYMENT_RUNBOOK.md retain these requirements.
- Candidate whole app (68 files, 1,731,842 source bytes at first packaging) and two-table SQL prepared. Final size/hash are in APP_BUNDLE_MANIFEST.json; all .env/cache/private key material excluded, exact current private-value scan found no match. Do not install blindly: remote code/dependency/schema compatibility is not verified. Archive is local mode 0600, not published to GitHub.
- No production SSH/SSM operation, secret injection, key retrieval/change, schema mutation, service restart, invalidation, account/token/order, paid/model call, commit or source push occurred. Public callback remains the prior 404 observation; no deployment claim.

## Remaining work

Once AWS/SSH access is configured, verify the actual Tau origin, pull protected
remote manifests/source and preserve teammate drift; verify persistent encryption
key internally; back up whole app/env; securely inject only the pair/public
origin; migrate exactly two broker tables; deploy the reconciled whole app;
restart only recursive-web; invalidate Tau /* and accept public status/assets/
auth/CSRF behavior. Then the user completes actual Alpaca paper consent. Do not
forge a session or place orders. Other broker approval gates remain unchanged.

Trackers/README/broker and secret guides now state GitHub sync success plus the
access gate. Original credential-check evidence is historical and preserved.

## Deployment owner selected

The user selected teammate execution. Stop requesting this desktop AWS/SSH setup. Current operator guide is [BROKER_OAUTH_DEPLOYMENT.md](../../../app/BROKER_OAUTH_DEPLOYMENT.md); source publication and the final teammate handoff supersede the earlier access request. Production remains unchanged here.
