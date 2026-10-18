# Broker OAuth: teammate deployment

Source merged: [PR #10](https://github.com/JihuiTanUchicago/kalshi_trade/pull/10)
and [PR #11](https://github.com/JihuiTanUchicago/kalshi_trade/pull/11) are on main.
The combined release includes the newer main research/risk/schema changes;
production deployment remains the teammate's separate acceptance work.

The user has assigned production deployment to their teammate. This source is
locally verified; no production migration, configuration, restart or real broker
consent has been completed. The original OAuth milestone had **1,020 Python passed
/ 9 skipped; 55 frontend passed**; those are historical results, not the combined
release's test count. See the [current integration evidence](../results/open_pr_merge_2026-10-18/HANDOFF.md)
and [provider setup/API contract](BROKER_OAUTH.md).

## 1. Obtain the reviewed source and compare production

Review the merged release and select a main commit. For a separate checkout:

```bash
git fetch origin main
git worktree add --detach /tmp/tau-oauth-release FETCH_HEAD
cd /tmp/tau-oauth-release/kalshi_trade_infra
git -C .. archive --format=tar.gz --output=/tmp/tau-oauth-app.tgz HEAD:kalshi_trade_infra app
shasum -a 256 /tmp/tau-oauth-app.tgz
```

This packages the **whole `app/`** from the chosen commit. It contains no ignored
`.env`, Python cache or private keys. Do not replace a dirty production checkout.
Compare the installed app, `data_pipeline/common.py`, Python 3.12+ and required
libraries with the release before installation; preserve/reconcile any newer
teammate changes. If reconciled code changes, repeat the tests and rebuild.

Verify the actual CloudFront origin. The documented Tau distribution is
`EEQ00Y93RTB1K`, public URL `https://d1gfpzcosqrjya.cloudfront.net`, historical
web instance `i-077d6f7873e7836ba` in us-east-1. These identifiers have not been
freshly verified from AWS in this handoff. Deploy to the actual web box.
Confirm callbacks forward all query parameters and the `rsid` cookie, POST is
allowed, and dynamic caching is disabled with minimum TTL 0.

## 2. Obtain credentials and preserve server configuration

Repository Actions Secrets already contain:

```text
ALPACA_OAUTH_CLIENT_ID
ALPACA_OAUTH_CLIENT_SECRET
```

**GitHub does not let a collaborator download these values.** For manual SSH
deployment, obtain the original pair from the app owner through the team's
private password manager or authorized Alpaca account access. Alternatively,
an existing trusted deployment workflow can reference the two GitHub Secrets
and deliver them to the server. No such workflow was created by this change.
Do not print them, upload a plaintext artifact, or commit an `.env`.

Back up the entire deployed `app/` and `/opt/kalshi/.env.app` on the server in a
root-only rollback directory. Update only the following entries in the web
service's protected configuration, replacing any existing assignment once:

```dotenv
ALPACA_OAUTH_CLIENT_ID=YOUR_PRIVATE_VALUE
ALPACA_OAUTH_CLIENT_SECRET=YOUR_PRIVATE_VALUE
APP_PUBLIC_URL=https://d1gfpzcosqrjya.cloudfront.net
```

The checked-in service sources `/opt/kalshi/.env.aws` and `.env.app` through Bash;
use shell-safe quoting. Preserve ownership/mode 0600 and every other setting.
Privately compare `APP_SECRET_KEY` before/after: it must be exactly equal, valid
32-byte urlsafe-base64 key material, and never displayed or regenerated. Preserve
Google callbacks, existing credentials and all data/trading flags. The developer's
local `.env` has no production encryption key and must not replace the server file.

Do **not** run `load_app_secrets.sh`: it omits the OAuth pair, rewrites the Google
callback and restarts agents as well as web.

## 3. Apply the reviewed full application schema

The combined release must follow current `AGENTS.md`: run `python -m app.schema`,
which includes pipeline tables, app-level column migrations and the two broker
tables. Neither `data_pipeline.init_schema` alone nor broker-only DDL migrates the
new main's required risk, execution and research columns. Earlier broker-only
rollout notes/archives are superseded for this combined release.

Review `app/schema.py` and `data_pipeline/init_schema.py` at the chosen commit and
back up the database before migration. This entry point also contains legacy data
maintenance (including waitlist/username work); its full scope must be reviewed by
the deployment owner. This source-merge task has not run it on any database.

Before migration, confirm `app_users` exists and inspect any existing
`app_broker_connections` / `app_broker_oauth_attempts` definitions against
`app.broker_repository.DDL`. Stop if an existing definition differs; `IF NOT
EXISTS` does not fix it. Both tables must be InnoDB; connections must include
`pending_claimed_at`. Keep existing grants and other data.

Run the following on the web server, using the reviewed checkout's source and
the existing server environment. Set `TAU_OAUTH_SOURCE` to that checkout's
`kalshi_trade_infra` directory first; the path below is an example:

```bash
sudo env TAU_OAUTH_SOURCE=/tmp/tau-oauth-release/kalshi_trade_infra /bin/bash <<'SHELL'
set +x
set -euo pipefail
set -a
. /opt/kalshi/.env.aws
. /opt/kalshi/.env.app
set +a
unset AWS_PROFILE
cd "$TAU_OAUTH_SOURCE"
/opt/kalshi/.venv/bin/python - <<'PY'
from app import broker_repository, broker_vault, schema

if not broker_vault.configured():
    raise SystemExit("Existing APP_SECRET_KEY is missing or invalid; stop without changing it.")
assert len(broker_repository.DDL) == 2
schema.main()
print("Full application schema completed; verify app migrations and broker definitions before installing the app.")
PY
SHELL
```

Inspect the resulting definitions/columns before proceeding. The exact generated
SQL is also retained in the [historical broker-only DDL evidence](../results/broker_oauth_2026-10-17/production_2026-10-17/broker-tables.sql);
that file documents the two broker tables and is not the complete migration for
the combined release. Confirm the app-level `exec_*`, risk, experiment and order-
intent migrations required by the selected source as well.

## 4. Install, restart web and verify

Transfer/install the reviewed **whole app** on the actual web box, retaining the
rollback copy. Keep replacement/restart brief. Restart only:

```bash
sudo systemctl restart recursive-web.service
```

For OAuth alone, do not restart collector, house, agent, engine or history services.
If also applying the market-data overlay, follow the separate
[market-data guide](MARKET_DATA_DEPLOYMENT.md) to drain/restart the agent worker.
With the
actual web environment loaded, `python -m app.broker_oauth status` should report
Alpaca configured and Tau execution disabled. Robinhood/IBKR can remain awaiting
their separate approvals. Invalidate `/*` on the verified Tau CloudFront
distribution and wait for completion; leave the dashboard distribution unchanged.

Verify using GET requests (HEAD is unsupported):

| Request | Expected |
| --- | --- |
| `/healthz` | 200 and `ok=true` |
| `/settings/account` | 200; resolved, versioned broker JS/CSS references |
| Broker JS/CSS assets | 200; bytes match the deployed release |
| Anonymous `/api/brokers` and broker callback | 401 |
| POST broker connect without `X-Recursive` | 403 |

Then the actual user signs into Tau, opens **Funds → Alpaca** (or
**Settings → Account** in Meridian), keeps
**Paper** selected and completes broker consent. Confirm the masked account,
callback, cancellation and disconnect behavior. Do not forge a user/session to
test this. This consent/account read is what verifies the real client pair;
the offline suite does not. No order or live-trading activation is required.

## 5. Rollback and return evidence

On import/service/route/schema failure, restore the protected **whole app** and
previous `.env.app`, restart only web, invalidate Tau `/*`, and verify health and
the original auth flow. Retain the additive broker tables and their data.

Return the deployed commit/hash, nonsecret migration/configuration status,
public HTTP checks and paper-consent outcome. Include no credentials, session
cookies, callback codes/state or raw account responses. Production acceptance
remains pending until those checks are actually completed.
