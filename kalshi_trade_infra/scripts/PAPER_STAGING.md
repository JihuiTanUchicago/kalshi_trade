# Disposable paper-trading acceptance

This operations-only branch tests merged Tau main in an isolated GitHub Actions
container and MySQL 8.4 service. It does not deploy to AWS, change production,
restart services, run a research worker, or use a real broker grant/API key.
The database, users, vault key, balances and broker observations are synthetic.
The database is reachable only in the job network; HTTP binds to loopback.
Nothing persists as a public test site after the run.

The branch intentionally replaces `deploy.yml` with the isolated test workflow.
Do not merge this operations branch. On main, that filename remains the separately
manual production workflow; always select the exact test branch below.

```bash
gh workflow run deploy.yml --repo JihuiTanUchicago/kalshi_trade \
  --ref codex/paper-staging-20261019
```

The job runs all regression/frontend tests, applies the full `app.schema` to
`tau_paper_staging` using the `tau_stage` database-only user, then starts the real
HTTP handler in the acceptance harness. Legitimate local dev sign-in creates
synthetic test sessions. The actual broker-vault, paper-service and persistence
paths use an in-process synthetic broker; outbound sockets are restricted to
this disposable DB and loopback test HTTP. No worker/engine/history/collector
process starts, so there is no queue connection to production.

Inspect the workflow conclusion and the fixed-name acceptance checks separately.
A passing HTTP health check alone does not prove database or order correctness.
The JSON receipt must say passed, real_mysql=true, synthetic_broker=true and
production_mutations=false. A fixture broker cannot prove Alpaca entitlement,
actual OAuth consent, real broker order acceptance or a fill.

## Persistent staging later

A browser-accessible staging service needs its own host or isolated containers,
separate database plus DB-restricted credentials, independent APP_SECRET_KEY,
separate hostname/cookies, and staged Google/Alpaca OAuth callback registration.
Keep APP_DEV_LOGIN=0 and secure cookies on any public staging hostname; the
loopback dev-login configuration in this disposable test job must not be reused
behind a public proxy or tunnel. Do not copy production user/grant tables or
source protected production environment files. Use explicit normal test-account
consent when connecting a dedicated Alpaca Paper account.

A separate port with the production database is insufficient: the worker claims
jobs globally within its configured database. Web-only manual paper testing
requires no research worker. A future staging worker must use only its separate
database and fresh queue; never reuse production service names or drop-ins.

No real user consent or broker order has been performed by these tests.
