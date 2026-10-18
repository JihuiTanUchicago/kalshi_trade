# Isolated paper-trading staging

A repeatable offline test stack for Tau's Alpaca paper integration. It uses the
complete app/data_pipeline packages, its own MySQL 8.4 database and restricted
`tau_stage` user, fresh encryption/password secrets, an internal Docker network,
and no research worker, engine, collector or production credentials.

Run it on a laptop or a separate test machine with Docker Compose v2. Avoid
sharing the production machine's compute resources. All commands below run from
`kalshi_trade_infra`:

```bash
python3 staging/setup.py
docker compose --project-name tau-paper-staging --file staging/compose.yml build
docker compose --project-name tau-paper-staging --file staging/compose.yml up --detach --wait gateway
docker compose --project-name tau-paper-staging --file staging/compose.yml run --rm --no-deps -T verify
```

Open http://127.0.0.1:18090 for the web/static preview. This preview has development
login disabled and no external OAuth credentials; it does not provide an
interactive signed-in account. Authenticated order testing happens inside the
unpublished `verify` container with synthetic `.test` accounts and broker replies.
The app's existing login/bind guard is preserved. No public staging URL is created.

`setup.py` generates three independent secrets in ignored `staging/.state/`
(directory 0700, files 0600) and reuses a complete valid existing state. It never
reads a production `.env` or prints a secret. Docker's context allowlist excludes
these files; the image reads the mounted private files during a constrained
bootstrap, clears inherited configuration, and drops to uid/gid 10001 before app
imports. The app and database have no published host ports and remain on the
internal network. An uncredentialed read-only gateway publishes 127.0.0.1:18090,
allows only static/health/known page paths, and strips cookies and authorization.
It rejects API writes, auth and unsubscribe routes.

The full `python -m app.schema` runs before web/verification. Verification needs a
fresh database: repeated runs against already seeded fixture data fail closed.
To remove **this test stack and its test data only**:

```bash
docker compose --project-name tau-paper-staging --file staging/compose.yml down --volumes --remove-orphans
```

Start it again for another clean acceptance run. Keep the local private secrets
for the lifetime of a retained database volume; do not partially replace them.

## GitHub verification

The **Isolated paper staging** workflow runs on relevant pull requests/main
changes and can be run manually from Actions. Each job uses a unique project,
boots the same Compose stack, checks the actual private network/ports/non-root
process and served asset hashes, then executes the real-MySQL/HTTP harness.
It always removes its own containers/volume. Artifacts contain only sanitized
checks/counts, never secrets or raw broker responses.

A passing receipt has `status=passed`, mode `synthetic_broker_real_mysql_http`,
14 passed checks, zero active jobs/deployments and zero real provider calls.
It covers authenticated ownership, CSRF, encrypted synthetic grants, saved drafts,
explicit submit, replay/conflict handling, committed single-send claims,
cancellation, observed fills, accepted-then-timeout recovery, SQL uniqueness and
transaction rollback/concurrent claims. The existing full CI remains separate.

This proves the application/database integration with fixtures. It does not prove
Alpaca OAuth, entitlement, exchange responses/fills, data freshness or the agent's
proposal flow against a real account. No actual broker order is sent.

## Later: browser-accessible OAuth staging

A persistent interactive staging site needs a separate host/database and its own
hostname, Google/Alpaca OAuth app callbacks and dedicated test-account consent.
Its secrets and session encryption must remain separate from production; never
copy production users, grants or queues. Keep development login off and use HTTPS
secure cookies on a public hostname. The app and database intentionally have no
internet egress. The uncredentialed preview gateway joins a separate bridge and forwards only the read-only allowlist;
real OAuth requires an explicitly reviewed staging configuration.
A staging research worker would need this separate database/queue as well.

Merging source or running this isolated workflow does not deploy production.
Production still uses the separately manual deployment workflow and must preserve
active research through a suitable worker-maintenance procedure.
