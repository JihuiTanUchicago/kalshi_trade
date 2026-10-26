# Tau broker OAuth deployment handoff

Status: historical rollout preparation; the user has now assigned execution to their teammate.
Current canonical operator guide: [BROKER_OAUTH_DEPLOYMENT.md](../../../app/BROKER_OAUTH_DEPLOYMENT.md).
For the October 18 combined release, the broker-only migration and archive below
are superseded: current main requires the full reviewed `python -m app.schema`
migration and a rebuilt whole-app package from the chosen merged commit. Retain
the following as historical evidence, not instructions for the new release.
Local release candidate and encrypted GitHub credentials are prepared.
Production access and deployment have not been completed. Do not install the
candidate until the actual production source and dependencies are compared.

## Access and target

The user authorized the deployment. This desktop has no AWS credential source,
profile or Tau SSH target. The user chose teammate execution instead of configuring
access here; use the current operator guide above.
Never paste AWS secret keys, SSH private key contents or OAuth secrets into chat.

The documented target is Tau's CloudFront distribution `EEQ00Y93RTB1K`, public
origin `https://d1gfpzcosqrjya.cloudfront.net`, historical web instance
`i-077d6f7873e7836ba` in us-east-1. Freshly verify the distribution's origin and
instance before making changes. The separate dashboard/collector is outside scope.
No IAM/network changes or new cloud resources are required by this plan.

## Release files and preflight

- `tau-broker-oauth-app.tgz`: the whole app package, no private env/keys/cache.
- `APP_BUNDLE_MANIFEST.json`: exact SHA-256 per file and archive checksum.
- `broker-tables.sql`: exactly the two new additive broker tables.
- `GITHUB_SECRET_SYNC.json`: metadata-only proof of encrypted credential upload.

Compare the current production `app/` hashes against this candidate and preserve
any newer teammate change. Also check deployed `data_pipeline/common.py`, Python
3.12+, requests/cryptography/pymysql versions and the active web service config.
If they differ materially from the tested source, reconcile the whole staged app
and rerun focused/full tests before publishing an updated archive. The local
baseline is main a5d5528 plus the reviewed OAuth implementation. Do not overwrite
unreviewed production drift merely because the local suite passes.

Confirm that CloudFront forwards the callback's full query string and the rsid
session cookie, allows POST and disables dynamic-response caching (minimum TTL 0).
Google OAuth already needs equivalent forwarding, but inspect current policies.

## Secrets and backup

Both ALPACA_OAUTH_CLIENT_ID and ALPACA_OAUTH_CLIENT_SECRET are now repository
GitHub Actions Secrets. A trusted deployment job may read them; collaborators
cannot download their values from the GitHub UI/API. They also remain in the
ignored private local .env. No workflow was created or invoked here.

Before replacement, keep a protected whole-app backup and root-owned mode 0600
copy of `/opt/kalshi/.env.app` on the server. Record only hashes/status publicly.
Keep secret contents and encryption-key fingerprints out of shared logs/artifacts.

Inject only these entries into the web runtime through the existing protected
configuration/secret store:

- ALPACA_OAUTH_CLIENT_ID
- ALPACA_OAUTH_CLIENT_SECRET
- APP_PUBLIC_URL=https://d1gfpzcosqrjya.cloudfront.net

The checked-in web unit sources `/opt/kalshi/.env.aws` and `.env.app` through Bash.
Use shell-safe quoting and an atomic env-file replacement, preserve ownership and
mode, and privately compare all existing values before/after. APP_SECRET_KEY must
remain exactly equal and valid for AES-GCM, including an in-memory round trip on
synthetic payload; never regenerate it. Preserve Google callbacks, all other
credentials, provider/data activation flags and trading controls. The local .env
has no APP_SECRET_KEY and must not replace the server env.

Do not run load_app_secrets.sh for this operation: it omits the OAuth fields,
rewrites the Google callback and restarts agents as well as web.

## Scoped migration and install

Load the intended production environment without tracing or printing values.
Using the staged candidate's app module and the deployed configured database
connection, execute only the two statements from app.adapters.brokers.broker_repository.DDL (the
same text as broker-tables.sql). Check app_users exists first; inspect the two
broker table definitions/column sets and confirm InnoDB and pending_claimed_at.
CREATE IF NOT EXISTS does not repair a divergent prior table: stop/reconcile if
one already exists with a different definition. Do not drop or reset grants.

Do not run app.schema or shared init_schema: those also perform unrelated ALTERs,
waitlist deletion, username updates and historical backfills. This rollout only
needs app_broker_connections and app_broker_oauth_attempts.

Install the reviewed whole app package on the actual web box. Keep source
replacement and web restart brief; do not install individual app files. Preserve
running collector/house/agent/engine services and do not restart them. Restart
only `recursive-web.service`, then run the staged broker status command with the
actual service environment; Alpaca should be configured and execution false.

Invalidate `/*` on the freshly verified Tau distribution and wait for its result.
Do not invalidate or change the separate dashboard distribution.

## Public acceptance and real consent

Use GET requests, not HEAD (this stdlib app does not implement HEAD):

- `/healthz` returns 200 with ok=true.
- `/settings/account` returns 200, includes the versioned broker module, and has no
  unresolved asset placeholders; static broker JS/CSS return 200 and match hashes.
- Anonymous `/api/brokers` and `/auth/brokers/alpaca/callback` return 401.
- POST `/api/brokers/alpaca/connect` without X-Recursive returns 403.
- No secret/code/state is reflected in errors, logs or public metadata.

Do not forge a production session or insert a test user to simulate consent.
The actual user signs into Tau, opens Settings → Account, keeps Alpaca Paper
selected and starts Connect. The broker's consent and callback then validate the
real client pair and account read. Confirm masked account metadata and disconnect
in the user's browser. No orders, generic MCP tools or IBKR brokerage-session
initialization are included. Other users' live trading still requires approval.

## Rollback

If import/service/route/schema acceptance fails, restore the protected whole app
and prior .env.app, restart only web and invalidate the Tau distribution again.
Verify public health and original auth routes. Retain the additive broker tables
and any grants/states; do not delete customer data. Keep all live flags unchanged.
Report the exact failed check and rollback state without logging secrets.
