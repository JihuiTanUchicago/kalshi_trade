# Alpaca OAuth credential configuration check

Workstream: tau-alpaca-oauth-credential-check-20261017; 2026-10-17T23:06:35+08:00, Asia/Shanghai.
Status: credentials supplied / locally checked; advisory reservation handed off.

User supplied Alpaca client ID and secret in Tau's ignored local .env. Confirm configuration and authorization URL construction without disclosing values; run focused existing offline checks; anonymously check public callback readiness.

Owned: this evidence directory and narrow current-status updates in PLAN.md, root mvp.md, broker handoff/setup/README/deployment guide if facts change. No-touch: runtime source, private env bytes, existing encryption keys, all provider/data/trading flags, prior evidence, sibling code and infrastructure. No migration, deployment, service restart, real OAuth grant/token/account/order, paid call, commit, GitHub secret upload or push.

Initial finding: private .env contains both ALPACA_OAUTH_CLIENT_ID and ALPACA_OAUTH_CLIENT_SECRET plus APP_PUBLIC_URL; process env does not automatically load .env. APP_SECRET_KEY absent locally; do not invent or replace the production encryption key. Existing local OAuth source is uncommitted and other changes are preserved.

## Results — 2026-10-17T23:08:00+08:00

- Both exact OAuth variable names are nonempty in Tau's ignored .env, mode 0600. No duplicates. The invoking process does not automatically load that file; the check explicitly parsed the four allowed config names without executing it. All private env bytes and runtime source hashes are unchanged.
- Network-free use of the actual configured client ID builds the fixed Alpaca authorize endpoint, correct CloudFront callback, fresh state, paper environment and data-only scope. The client secret is absent from the URL. This verifies configuration shape, not authenticity of the ID/secret or broker app approval. No invalid-code token probe was attempted.
- Local end-to-end readiness is blocked by absent APP_SECRET_KEY. The checked-in server unit expects a persistent key from /opt/kalshi/.env.app; that is not proof of its current production value. No production key was retrieved or regenerated.
- Anonymous public checks: /healthz HTTP 200; /auth/brokers/alpaca/callback HTTP 404; /static/broker-connections.js HTTP 404. OAuth code is not available at the expected public routes yet. No cookies/credentials or raw response bodies were sent/stored.
- GitHub encrypted-secret metadata: ALPACA_OAUTH_CLIENT_ID and ALPACA_OAUTH_CLIENT_SECRET names are absent. Existing market-data/news secrets are separate. No upload/mutation occurred.
- Focused synthetic tests: **112 passed in 0.43s**. Existing unchanged-source full regression remains **1,020 passed / 9 skipped**, frontend 55; it was not needlessly repeated.

## Next action

Production deployment owner: publish/deploy the OAuth app update and apply the intended new broker-table migration; inject APP_PUBLIC_URL and the supplied OAuth pair securely into the web runtime while retaining its existing APP_SECRET_KEY. Do not replace production env with the local .env or rotate its encryption key. The existing SSM loader omits OAuth fields and restarts web+agents if invoked; it was not run. Once deployment is explicitly authorized and verified, the user completes genuine Alpaca paper consent in Settings → Account. Only that code exchange/account read can validate the real credentials. Other users' live access still depends on Alpaca approval. Robinhood/IBKR registration and live acceptance remain unchanged.

PLAN, root MVP, app README, OAuth/deployment setup guides and original broker handoff link this milestone. No live connection claimed; no production/deployment/paid/financial change or GitHub publication.
