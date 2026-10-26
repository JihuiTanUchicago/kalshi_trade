# Databento primary data and production configuration

Workstream: `tau-databento-primary-20261018` · 2026-10-18 00:01 Asia/Shanghai.
Status: implemented / offline verified / ready for review; advisory reservation released.

## Scope

Verify Databento against the market-data capabilities already connected to Tau;
make historical equity/futures routing configurable; provide a small, explicit
production configuration and validation path for the deployment owner. Databento
provider coverage and Tau's historical-only adapter are separate claims.

Branch: `codex/databento-primary-20261018`, based on GitHub main
`a5d55287faba9d0659186fa406afd4fe60191a4f` (remote checked before branching).
OAuth PR #10 stays separate and unmerged. Tracked files were clean; existing
untracked result archives belong to earlier work and are preserved.

Owned paths: `app/research/agent_market_data.py`, a focused market-data settings/preflight
module, related tests, `.env.example`, a production configuration template/helper,
the agent-worker systemd unit if required, `app/README.md`, provider/deployment
documentation, `PLAN.md`, `../mvp.md`, the planned data entries in `app/devlog.py`,
and this evidence directory. Independent coverage research is read-only.

No-touch paths: private `.env*` values, existing encryption/OAuth credentials,
`trading_agent_new/`, execution/order/live-gate code, schema/repositories, existing
service processes, unrelated result archives and OAuth PR #10. No provider or
model paid calls, AWS mutations, service restart, deployment or live activation
are part of local implementation.

## Acceptance

- Unsupported coverage is explicit; currency/rate futures are never relabelled
  OTC FX or published yield/funding observations.
- A configured primary routes unqualified historical-bar requests predictably;
  explicit providers stay explicit; no silent provider/feed fallback.
- Historical training cutoffs, completed bars and download cost preflight remain.
- Teammates can validate configuration without credentials or data in logs and
  without a paid download. Service environment loading is documented and tested.
- Full offline regression passes; provider/production acceptance is distinguished
  from synthetic tests. Canonical setup/handoff and trackers agree.

## Implemented

- `app.market_data_config.Routing` selects the historical-bar primary; existing
  installations default to Alpaca. Databento primary requires an explicit dataset
  from its allowlist. Explicit providers survive both validation passes; errors
  do not trigger fallback. Research skips duplicate automatic Alpaca history when
  Databento is primary, while the current copilot can retain Alpaca snapshots.
- `python -m app.market_data_config check` validates enabled providers, datasets,
  feeds, watchlists, flags and positive Databento estimate limit without network.
- `scripts/configure_market_data.py` merges effective defaults → recognized
  process values → private literal file. Validation is the default. Explicit apply
  writes all 17 effective settings to a separate atomic mode-0600 file, so old base
  flags/feed settings do not reappear. It refuses known base environment filenames,
  symlinks, unsafe permissions/directories and shell evaluation. No automatic restart.
- The agent systemd unit optionally loads `.env.market-data` last and preflights
  it before worker startup. Missing overlay preserves legacy startup; present
  invalid/unreadable configuration fails. Web, collectors and order units are unchanged.
- [Canonical operator guide](../../app/MARKET_DATA_DEPLOYMENT.md) records official
  provider coverage, private key delivery, complete commands, bounded availability
  estimate/download acceptance, real queued worker checks and rollback.

## Verification

From `kalshi_trade_infra`:

```bash
TAU_ALPACA_ENABLED=0 TAU_MASSIVE_ENABLED=0 TAU_DATABENTO_ENABLED=0 TAU_EXA_ENABLED=0 TAU_WORLDMONITOR_ENABLED=0 APP_TEST_MYSQL=0 AWS_EC2_METADATA_DISABLED=true .venv/bin/python -m pytest tests/ -q --tb=short
.venv/bin/python -m py_compile app/*.py data_pipeline/*.py scripts/configure_market_data.py
```

Full regression: **939 passed / 9 skipped** (7.43 seconds). Independent review:
**287 focused offline passed** with socket connections blocked; no remaining
actionable findings. Fixtures are synthetic, with no live DB. Root also checked
syntax and diff whitespace. New root routing tests are 26; helper tests are 35.

Review fixes: fully serialize checked defaults instead of allowing base-file
settings to reactivate omitted providers; reject `.env`, `.env.app` and `.env.aws`
as output targets before writing. Preservation/negative tests cover both.
See [review](REVIEW.md) and [verification receipt](VERIFICATION.json).

The project-named `/ponytail`, `/security-review` and `/devlog-sync` commands are
not installed. Independent manual control-path review and planned-only public
Dev Log synchronization were used; no claim that those commands ran.

## Deployment-owner acceptance and limits

Configure keys privately and select licensed datasets, feeds and a deliberate
positive estimate budget using the template; install complete reviewed source,
the helper and the updated unit. Drain existing jobs before restarting the worker.
Then check provider metadata, authorize a small bounded download and verify a
genuine queued worker/model request with redacted evidence. None of those
production/provider acceptance actions occurred in this workstream.

Databento provider live/OPRA capabilities are not this adapter's implemented
capabilities. Keep Alpaca for current snapshots until Databento live ingestion is
built, and Massive for spot FX, daily yield/funding series and ready-made options
analytics. A Databento-only profile intentionally lacks those tools. Data keys
and brokerage OAuth remain separate; OAuth PR #10 is not part of this branch.

Durable cross-context/provider cost accounting is not implemented here; the
existing estimate guard is not an invoice cap. Historical corrections remain
possible; training cutoffs and completed intervals are unchanged. The backtester
and live order engine do not gain new executable asset classes from this context.

Related records updated: `PLAN.md`, root `mvp.md`, `app/README.md`,
`app/DEPLOYMENT_SECRETS.md`, `.env.example`, and the relevant planned-only Dev Log.
The operator guide is the provider-decision/routing/production contract; no new
public HTTP API, schema, sibling project or deployed capability was introduced.
