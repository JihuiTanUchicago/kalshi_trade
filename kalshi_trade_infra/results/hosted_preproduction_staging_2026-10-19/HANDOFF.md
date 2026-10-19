# Hosted pre-production staging

Workstream tau-hosted-preproduction-staging-20261019 / 2026-10-19T10:11:22.199425+08:00 / in progress.

User requested hosted pre-production staging before production deployment. Baseline GitHub main 1bf2b13e8d8b277dcc6ddf4bd0a71123c18ab65c; runtime matches previously tested e7c7fde (only Benchmark.md was added). Reuse the isolated staging checkout, preserving its progress/evidence edits and the shared checkout's concurrent work. Own additive staging/hosted operations/configuration, tests, documentation and narrow PLAN/mvp entries.

No-touch: production instance/source/services, production DB/users/queues, running/queued/paused research, private base environments/APP_SECRET_KEY, live trading/autopilot/billing gates, old pinned operations branch and PAUSED heartbeat, sibling source and concurrent frontend work. No production SSM command or provider call is needed for infrastructure discovery.

Existing CI staging has passed 1,645 Python and 71 frontend tests plus 14 real MySQL/HTTP checks with a synthetic broker. It deliberately has no public interactive ingress, normal OAuth credentials or research worker. Those checks do not prove a hosted environment or real Alpaca consent/order.

Next: read-only AWS control-plane inventory and permission check through GitHub credentials. Collect only deliberate credential-free receipts; do not retain raw AWS/Actions logs, identities, environments, account responses, article text or prices. Resource creation, if permitted, must be staging-only, use separate persistent DB/vault credentials and HTTPS, and retain normal login/billing checks. Exact actual-broker paper order requires explicit tester confirmation.

## Prepared implementation; owner gate

Prepared / offline verified / independent review cleared. User selected a dedicated staging AWS role. The read-only inventory run39189041708 on exactbb05e0d3 found expected AWS authentication but EC2 UnauthorizedOperation and CloudFormation/CloudFront/IAM AccessDenied; no SSM command, new resource, provider call or production mutation. Its green workflow only means receipt collection succeeded; receipt.status remains blocked.

Implemented a separate hosted profile (fresh private DB/vault secrets, persistent initialization fence, normal Google/Alpaca OAuth, secure cookies, mandatory Stripe sandbox configuration, uid/capability drop, no worker/engine/provider/model keys), owner-applied new private EC2/NAT/CloudFront VPC-origin stack with retained data disk/CMK/bucket, and manual staging OIDC deployment. This role cannot read production SSM command output or general EC2 metadata. Collection uses private stage-only S3 nonce receipts; absence is polled through scoped listing, and AccessDenied is never silently retried.

Review fixes include complete installed-release content checks against exact archived source, missing-key fencing even if a DB volume survives, same-source runtime reload via web/gateway recreation, explicit local Docker socket, private nontruncating nofollow deploy lock, owner-account/actual parameter binding and pre-host receipt gating. Early focused failures during interface changes were corrected; final full regression is1,766 passed/10skipped and independent121focused passed. CloudFormation cfn-lint1.57.2 and userdata shell syntax checks pass. Existing app/data_pipeline and production deploy workflow are byte-unchanged.

Next publish the reviewed source, collect real hosted-profile container CI, then give AWS owner staging/HOSTED_STAGING.md. Owner must create/execute the add-only stage change set, configure repository variable AWS_STAGING_ROLE_ARN and staging SecureString runtime (normal OAuth and Stripe sandbox callbacks). No AWS creation or public URL is accepted until actual receipts exist. No Google/Alpaca consent, billing transaction or paper order has been performed. The paused production heartbeat remains paused; do not resume the old pinned production operations.

This new hosted profile is web/API only. It does not add graceful research-worker draining, production zero-downtime deployment or a real stage research worker. Those remain explicit future acceptance work. Persistent staging database and key must not be torn down by the disposable fixture workflow. Owner applies known new billable resources; retained storage/key/bucket need deliberate later teardown.
