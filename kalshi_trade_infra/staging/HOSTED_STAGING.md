# Hosted pre-production staging: operator runbook

Status: hosted setup implemented and offline verified; AWS-owner bootstrap is
required. Reviewed starting point: `1bf2` on
`codex/hosted-preproduction-staging-20261019`. The actual read-only AWS check
[39189041708](https://github.com/JihuiTanUchicago/kalshi_trade/actions/runs/39189041708)
returned `UnauthorizedOperation` for EC2 and `AccessDenied` for CloudFormation,
CloudFront and IAM. The existing GitHub keys cannot provide the staging
infrastructure inventory; no provisioning was attempted. The user selected a
dedicated staging GitHub role. This guide does not establish a provisioned host,
deployed configuration or successful real OAuth.
`<staging-origin>` below means the actual independently provisioned HTTPS origin.

## AWS owner: one-time bootstrap

Use an AWS owner/admin session in the existing Tau account and region `us-east-1`,
with this reviewed source checked out. Do not change the production deploy user's
permissions or reuse its static keys for staging. Run from `kalshi_trade_infra`:

```bash
python3 staging/hosted/bootstrap_aws.py preview
python3 staging/hosted/bootstrap_aws.py plan
python3 staging/hosted/bootstrap_aws.py review --change-set-name <returned-name>
python3 staging/hosted/bootstrap_aws.py execute --change-set-name <returned-name>
```

`preview` makes no AWS call. `plan` creates a new, unexecuted CREATE change set.
Wait until it is prepared before `review`; use the same returned name for both
commands. The helper rejects a different account, an existing stack, changed
template/parameters, unsupported origin AZs and resource changes other than Add.
`execute` repeats those checks before executing the reviewed change set. The AWS
owner needs permission to create these new resources; the GitHub staging role
does not receive infrastructure-creation permissions.

The template creates a new VPC with a private application subnet and managed NAT
egress, a private t3.medium EC2 host, 16 GiB OS disk plus a retained encrypted
40 GiB data disk, SSM management, a private source/receipt bucket, and CloudFront
VPC origin with its own generated HTTPS hostname. There is no SSH listener,
public application IP or production network connection. Docker data, staging
database, state/key and releases live under `/opt/tau-staging` on the data disk.
The host forwards private origin requests to the loopback-only gateway.

This is billable infrastructure. The change-set output links current pricing;
NAT hourly/data, IPv4, disks and KMS charges continue even if EC2 is stopped.
Retained storage/key/bucket also survive stack deletion and need deliberate
later cleanup. Review [AWS VPC/NAT pricing](https://aws.amazon.com/vpc/pricing/)
and the other linked pricing pages before executing the change set.

After CloudFormation and host initialization finish:

```bash
python3 staging/hosted/bootstrap_aws.py outputs
```

Copy the returned deployment role ARN into the GitHub repository Actions
**variable** `AWS_STAGING_ROLE_ARN`. The manual hosted workflow runs in environment
`staging`; its OIDC trust admits only this repository/environment and STS audience.
No new long-lived AWS access key is needed. Its writes and secret permissions are
limited to this stack's resources. It has no `ssm:GetCommandInvocation` or EC2
inventory permission: collection reads only credential-free receipts under this
staging bucket's `receipts/` prefix. The instance may write those receipts, while
the deploy role may read them. Production command logs are inaccessible to it.

## Configure the independent application and deploy

Use the actual URL returned by `outputs` for the Google/Alpaca callbacks and
Stripe sandbox endpoint listed below. Create an operator-owned private JSON file
(mode 0600, outside Git) containing exactly the runtime names in the table:
`APP_PUBLIC_URL`, `TAU_ADMIN_EMAIL`, Google and Alpaca OAuth pairs, the three
Stripe sandbox values, and optional `STRIPE_PAYMENT_CONFIG`. No `MYSQL_*`,
vault key, model/data key, development-login or live-gate override is accepted.
Use real staging credentials here; synthetic values are for disposable CI only.
Never paste these values into chat, commit them, or put them in `.env.example`.

```bash
python3 staging/hosted/bootstrap_aws.py runtime --file /private/path/hosted_runtime.json
```

The helper validates configuration shape and the exact generated origin, then
writes only `/tau/staging/hosted-runtime` as SecureString with the dedicated
staging KMS key. Values never enter command arguments or receipts. This is not
provider authentication or a successful consent check.

Run **Deploy hosted pre-production staging** in GitHub Actions with the exact
reviewed 40-character source commit containing this setup. The workflow is
available in the standard Actions UI after this infrastructure change is merged
into the default branch. Before that, a deployment owner can run the same
reviewed workflow from an explicitly published operations ref; do not substitute
the production **Deploy web app** workflow.

The controller derives its target only from the new stack, requires the exact
staging OIDC role, rejects known production targets, verifies the on-host marker
and mounted data disk, checks whole-package archive contents/digest and existing
release hashes, then installs an immutable staging release. It preserves the
private DB/vault secrets and their independent initialization fence. If an
existing DB volume lacks its retained secrets, deployment stops rather than
generating replacements. It runs full schema against the private staging DB,
recreates web/gateway to load accepted settings, and checks actual public assets,
unauthenticated rejection and development login remaining disabled. Database
volume/key are retained; no research worker or engine is started.

If runtime configuration is missing, the receipt remains
`pending_staging_configuration`; this is not deployment acceptance. A receipt of
`staging_deployed_pending_user_acceptance` establishes web/schema/HTTPS checks,
while Google, billing, paper consent/order and actual research acceptance below
remain separate. SSM receipt timeouts require inspecting the existing operation;
do not blindly dispatch another deployment. This initial web-only deployment
does not implement seamless worker upgrades.

The separate **Check hosted staging containers** CI workflow exercises the same
profile using generated synthetic OAuth/billing-shaped values, real MySQL,
NGINX and the app, and removes its own unique project/volume. It makes no actual
provider request. A passing CI receipt is configuration/runtime evidence only;
it is neither a persistent public staging URL nor real brokerage acceptance.

## 1. Provision an independent environment

- [ ] Allocate a dedicated staging EC2 instance, security groups and storage;
  keep production instances, volumes, database, services and IAM role untouched.
  Record the staging instance ID, access method, storage ID and intended source
  commit before installation. Do not run staging on the production research box.
- [ ] Give the site a valid HTTPS endpoint and certificate. An independently
  provisioned AWS-generated HTTPS domain is acceptable if both OAuth applications
  accept its exact callback URLs. An EC2 public DNS name alone does not establish
  HTTPS or callback readiness. Record the actual origin; do not reuse the
  production CloudFront distribution/origin.
- [ ] Run a separate MySQL 8.4 instance/container with a persistent staging-only
  volume and database-scoped application user. Set every `MYSQL_*` value
  explicitly; the source otherwise defaults the database name to `kalshi_trade`.
  Publish no MySQL or application backend port to the internet.
- [ ] Generate independent database/root passwords and a fresh `APP_SECRET_KEY`
  containing 32 random bytes encoded with URL-safe base64. Retain this key with
  the staging database across releases; replacing it makes saved broker grants
  unreadable. Keep files private (directory 0700, files 0600), outside the image
  and build context. Never copy production users, sessions, grants, queues,
  payment customers or private environment files.

The minimum initial deployment is HTTPS ingress, web and MySQL, without an agent
worker, trading engine, collector or history daemon. Keep the database network
private. Web needs controlled outbound HTTPS for actual Google/Alpaca/Stripe
operations; the current offline application's internal-only network cannot do
this. Give only the intended application components outbound connectivity;
keep MySQL isolated. Do not grant the host production API/IAM access.

## 2. Prepare a hosted configuration, preserving offline tests

The current `compose.yml` is a disposable offline fixture stack, not an
interactive deployment. Its gateway rejects auth/API routes and mutations,
strips cookies and hides `Set-Cookie`. Its entrypoint discards inherited
credentials, fixes HTTP origins/insecure cookies and offers only
`schema`, `web`, `verify`. Changing a port or adding TLS will not enable login.

- [ ] Review and use `hosted/compose.yml`/`hosted/entrypoint.py` and HTTPS ingress;
  preserve the existing offline stack and harness. The hosted ingress must
  forward normal methods, query strings, bodies, `Cookie`, `Set-Cookie` and
  `X-Recursive` to the real application. Disable caching for auth/API responses.
  Avoid logging OAuth codes/state or cookie values.
- [ ] Load only explicit staging secrets/settings before Python imports;
  Google, database and several service settings are captured at import time.
  Retain the application's authentication, CSRF and existing bind guards.
- [ ] Keep development login disabled and secure cookies enabled. Do not mint
  sessions, seed authenticated users or reuse the harness's synthetic broker
  grants on the hosted database. Never run `verify` against this persistent DB.

| Runtime names | Required hosted values/purpose |
| --- | --- |
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` | Dedicated staging database and restricted staging user. |
| `APP_SECRET_KEY` | Fresh, persistent staging vault key; never the production key. |
| `APP_PUBLIC_URL` | Exact HTTPS `<staging-origin>`, with no path/query. |
| `APP_HOST`, `APP_PORT` | Private backend listener appropriate to the hosted runtime. |
| `APP_DEV_LOGIN=0`, `APP_INSECURE_COOKIES=0` | Normal sign-in and Secure/HttpOnly/SameSite cookies. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Separate staging Google OAuth application. |
| `APP_GOOGLE_REDIRECT_URI` | `<staging-origin>/auth/google/callback`. |
| `TAU_ADMIN_EMAIL` | Actual staging operator; other testers need Tau waitlist approval. |
| `ALPACA_OAUTH_CLIENT_ID`, `ALPACA_OAUTH_CLIENT_SECRET` | Prefer a separate staging Alpaca OAuth app. |
| `TAU_ALPACA_PAPER_ENABLED=1`, `TAU_ALPACA_PAPER_MAX_ORDER_USD=500` | Explicit paper order activation and current per-order ceiling. |
| `APP_LIVE_TRADING_ENABLED=0`, `APP_NO_SIDE_LIVE_ENABLED=0` | Preserve live execution gates; start no engine. |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` | Independent Stripe sandbox/test credentials; no live billing credentials. |
| `STRIPE_PAYMENT_CONFIG` | Optional matching sandbox configuration; never copy a live configuration ID. |

Register the exact Google callback above. If the Google application restricts
test users, its owner must also admit the intended testers. Tau independently
admits the configured admin or approved waitlist accounts; Google authorization
alone does not bypass that check. Do not extract or share production Google keys.

Register `<staging-origin>/auth/brokers/alpaca/callback` in the Alpaca application.
Using the existing Alpaca app requires its owner's approved staging redirect;
possessing its key does not establish that registration. Use a dedicated paper
test account and request `data trading` through genuine consent. Shared
`APCA_API_KEY_ID`/`APCA_API_SECRET_KEY` data keys cannot substitute for user OAuth.
The paper service fixes execution to the Alpaca paper host, independently of
the shared market-data enable flags.

Register `<staging-origin>/api/stripe/webhook` with the sandbox endpoint secret.
Keep normal card/credit flows: missing `STRIPE_SECRET_KEY` makes billing
unconfigured and bypasses its readiness checks in this source. Do not use that
state as acceptance of normal billing. Never insert payment methods/credits or
dummy secrets to manufacture a passing result.

## 3. Install and accept the actual site

- [ ] Package the complete reviewed `app/` and required `data_pipeline/`
  dependencies. Back up staging data/key before later migrations. Verify the
  destination database identity, then run the existing full
  `python -m app.schema` there; pipeline-only or broker-only migrations omit
  required app columns. This migration includes legacy maintenance, not just
  the new paper-order table.
- [ ] Verify HTTPS and served source/assets, plus an authenticated `/api/me`;
  `/healthz` alone always returns 200 without validating database access.
- [ ] Complete real Google login in a fresh browser context. Check staging-only
  `rsid` cookies, persistence after refresh, logout, tester access and
  `/auth/dev` remaining unavailable. Missing session/CSRF headers must still
  reject protected requests.
- [ ] Complete genuine Alpaca **Paper** consent with trading authorization.
  Confirm account/positions are actual paper observations. Review a small
  whole-share limit/DAY ticket, explicitly submit, check its observed order
  state, retry without creating a duplicate, then reconcile a fill or cancel.
  Acceptance and pending cancellation are not fills; closed-market resting
  orders are not proof of a failed connection. Verify another tester cannot
  read or submit the first user's ticket.
- [ ] Exercise Stripe sandbox through its normal UI/webhook paths. Research/chat
  must return 402 when card/credit requirements are unmet; satisfy those
  requirements through the genuine sandbox flow before testing a worker.
- [ ] Record source revision, sanitized checks, remaining gates and staging
  resource identities. Keep API keys, tokens, session values, raw account data
  and article text out of evidence. Production deployment remains a separate
  action after this acceptance.

## 4. Optional research worker, after web/OAuth acceptance

Use only this staging database/queue. The agent worker claims all queued runs
and reaps abandoned runs in its configured database, without an environment
namespace. It also starts an autopilot scheduler; keep test users' autopilot off
and initially use one worker (`APP_AGENT_CONCURRENCY=1`). No production worker
or active research may be stopped or repointed.

Add a reviewed hosted worker command for `python -m app.worker agents` only after
normal sandbox billing and explicit model/data configuration are ready. Use
`APP_LLM_PROVIDER` plus `ANTHROPIC_API_KEY`, or a separately scoped staging
Bedrock identity with `AWS_REGION`/`APP_BEDROCK_MODEL`; select a supported
`APP_AGENT_MODEL` as appropriate. Model/data requests can still incur actual
vendor charges even when Stripe operates in sandbox mode.

Keep shared data providers disabled until separately configured/accepted:
`TAU_ALPACA_ENABLED`, `TAU_MASSIVE_ENABLED`, `TAU_DATABENTO_ENABLED`,
`TAU_EXA_ENABLED`, `TAU_EXA_HISTORICAL_ENABLED`, `TAU_WORLDMONITOR_ENABLED`.
Paper account/order testing needs none of those shared data keys. Real research
also needs sufficient independently loaded history, its chosen provider keys,
and working strategy sandbox dependencies; an empty schema is not a research
dataset. Use separate `APP_STRATEGY_DATA_DIR` and, if enabled,
`TAU_WORLDMONITOR_JOURNAL` storage. Start with one finite real user-requested job
and inspect its actual worker/provider evidence. Never enable an execution
engine as part of this worker step.

## When provisioning is blocked, or staging is retired

Give the AWS/operator owner the reviewed source revision and request an
independent host, storage, HTTPS origin, scoped deployment access and staging
secret delivery. Separately request Google/Alpaca callback registration and
sandbox Stripe configuration from their owners. Record which capability is
missing; this guide claims no AWS provisioning, DNS, certificate or provider
registration permission. Keep the passing disposable CI tests available while
these dependencies are resolved.

On retirement, first confirm the recorded staging resource IDs and preserve any
needed staging evidence/backups. Remove only those staging services, storage,
secrets and callback registrations/grants. Do not apply the offline workflow's
automatic volume teardown to a retained interactive staging database, and do not
remove production callbacks or revoke a shared production application.

The AWS bootstrap deliberately retains the data disk, its KMS key, artifact
bucket and any newly created shared GitHub OIDC provider. Stop staging services
and unmount its data disk before owner-managed stack deletion. Retained disk,
key, source/receipt objects and `/tau/staging/hosted-runtime` require explicit
staging-only cleanup when no longer needed; do not delete a shared OIDC provider.

Architecture follows the documented [CloudFront VPC-origin requirements](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)
and [GitHub OIDC environment trust](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html).
