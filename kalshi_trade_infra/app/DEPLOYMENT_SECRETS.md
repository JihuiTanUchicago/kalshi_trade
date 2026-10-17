# API credentials for the deployment owner

The repository is public. Keep real `.env` files out of Git. The committed
[`.env.example`](../.env.example) supplies variable names and safe defaults.

## What is available on GitHub

The following **repository GitHub Actions Secrets** were uploaded and their names
verified on October 17, 2026:

| Secret | Use |
| --- | --- |
| `MASSIVE_API_KEY` | FX, Treasury/funding context and entitled options endpoints |
| `EXA_API_KEY` | Current web/publication research and entitled historical Snapshot |
| `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` | Alpaca stock/ETF market-data credentials |
| `DATABENTO_API_KEY` | Entitled historical stock/ETF/futures datasets |
| `ALPACA_OAUTH_CLIENT_ID`, `ALPACA_OAUTH_CLIENT_SECRET` | Alpaca Connect application; separate from market-data keys |

Broker account OAuth requires separate application registration and credentials;
the market-data Alpaca pair above cannot configure Alpaca Connect. The Alpaca OAuth
client pair is present in the ignored local `.env` and is now stored as two
additional encrypted GitHub Actions Secrets: seven names total. Metadata verifies
the new pair and unchanged earlier entries; values were sent only through stdin.
Production injection/deployment is assigned to the teammate; follow the
[operator guide](BROKER_OAUTH_DEPLOYMENT.md). IBKR
key files and other broker registration credentials remain unprovisioned. Follow
[broker authorization setup](BROKER_OAUTH.md) for the confirmed CloudFront origin,
callback URLs and runtime variables. The existing SSM loader does not inject
these new OAuth settings.

Manage them in [Settings → Secrets and variables → Actions](https://github.com/JihuiTanUchicago/kalshi_trade/settings/secrets/actions).
GitHub encrypts these values; collaborators cannot read or download them from the
UI/API. A clone or `git pull` does not include them. This upload is a point-in-time
sync, not an automatic link to the developer's local `.env`.

The initial upload covered Massive/Exa. The user subsequently consolidated the
Alpaca pair in Tau’s private `.env`, restored Databento, and requested another
GitHub sync. All five named secrets are now listed and upload metadata is verified.
The private `.env` stays ignored and unchanged by the sync; activation flags and
production configuration were not copied or enabled. This is credential storage,
not a production provider-authentication test.

## If deployment uses GitHub Actions

Reference each secret explicitly in the trusted deployment step:

```yaml
env:
  MASSIVE_API_KEY: ${{ secrets.MASSIVE_API_KEY }}
  EXA_API_KEY: ${{ secrets.EXA_API_KEY }}
  APCA_API_KEY_ID: ${{ secrets.APCA_API_KEY_ID }}
  APCA_API_SECRET_KEY: ${{ secrets.APCA_API_SECRET_KEY }}
  DATABENTO_API_KEY: ${{ secrets.DATABENTO_API_KEY }}
  ALPACA_OAUTH_CLIENT_ID: ${{ secrets.ALPACA_OAUTH_CLIENT_ID }}
  ALPACA_OAUTH_CLIENT_SECRET: ${{ secrets.ALPACA_OAUTH_CLIENT_SECRET }}
  APP_PUBLIC_URL: https://d1gfpzcosqrjya.cloudfront.net
```

This fragment only supplies the runner's process environment. The deployment job
must still deliver the values to the server's secret store or runtime environment.
No deployment workflow was created or run by this handoff. Select the target and
authentication first; for AWS, GitHub's OIDC integration can avoid a stored AWS
access key. Do not print values or publish a generated `.env` as an artifact.

## If deployment is manual on the existing AWS server

Use the existing AWS SSM Parameter Store convention in **us-east-1**:

| SecureString parameter | Server variable |
| --- | --- |
| `/recursive/MASSIVE_API_KEY` | `MASSIVE_API_KEY` |
| `/recursive/EXA_API_KEY` | `EXA_API_KEY` |
| `/recursive/DATABENTO_API_KEY` | `DATABENTO_API_KEY` |

An authorized owner must populate these parameters from the original provider
credentials/a shared vault, or from a trusted GitHub Actions deployment step that
can access the encrypted GitHub secrets. A manual operator cannot recover the
values from GitHub Secrets. Give the server role the required SSM read/decryption
access; do not put AWS credentials in Git.

The current loader does **not** fetch Alpaca’s `APCA_API_KEY_ID` or
`APCA_API_SECRET_KEY`. The deployment owner must inject that pair through the
chosen server/runtime secret configuration; adding SSM parameters alone does not
make this loader read them. Its behavior was not changed by this credential sync.

After configuring the parameters, the deployment owner can run the existing
loader **from the deployed product root on the production box**:

```bash
sudo env REDIRECT_URI='https://your-production-host/auth/google/callback' \
  bash scripts/load_app_secrets.sh
```

Replace the example URL with the exact registered production OAuth callback. The
loader always rewrites `APP_GOOGLE_REDIRECT_URI`; without `REDIRECT_URI` it uses its
hardcoded CloudFront default. It also refreshes any configured Google, Anthropic,
Databento and Stripe values and provider settings, alongside Massive/Exa. Review
the intended parameters before running it; it is not a two-key-only operation.

That command is a production operation: it retrieves the configured app secrets,
writes `/opt/kalshi/.env.app` with root ownership and mode `0600`, and **restarts
`recursive-web` and `recursive-agents`**. It was not run during this handoff. It
skips missing parameters, so a successful exit does not prove every provider was
configured; check the named load/skip messages without displaying values.

The checked-in [web service](../scripts/systemd/recursive-web.service) and
[agent service](../scripts/systemd/recursive-agents.service) source `.env.aws` and
`.env.app` through Bash. If the teammate uses a different service/container setup,
configure that runtime's equivalent secret injection instead. Copying a file into
a clone does not configure an already running process.

## Provider activation and acceptance

Keys and provider activation settings are separate. This upload did **not** change
`TAU_MASSIVE_ENABLED`, `TAU_EXA_ENABLED`, `TAU_EXA_HISTORICAL_ENABLED`, or any trading
setting. Select the intended feed/datasets and enable only the licensed endpoints
in the actual agent-worker environment. The existing loader supports the matching
`/recursive/TAU_MASSIVE_*` and `/recursive/TAU_EXA_*` settings listed in its source.

After the deployment owner injects configuration and restarts the intended
processes, verify provider availability in that environment and run a small
authorized queued research/copilot canary. A stored GitHub secret, a healthy web
page, or prior local tests do not establish production worker/provider acceptance.
Massive current FX quotes/options previously returned entitlement errors for the
tested key; check those permissions before depending on those endpoints.

Keep database/auth/billing credentials and the production `APP_SECRET_KEY` under
their existing server configuration. Do not replace the complete production
environment with a development `.env`.

References: [GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets),
[AWS Parameter Store](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html),
[existing secret loader](../scripts/load_app_secrets.sh).
