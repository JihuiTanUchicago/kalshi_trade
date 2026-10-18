# Market data: provider choice and production setup

Databento is the recommended **primary historical stock/ETF and futures source**.
It does not replace every existing Alpaca/Massive tool. This setup keeps their
distinct capabilities available, with no automatic provider or feed fallback.
The source is merged to GitHub main through PRs #10 and #11; a production worker
and real queued model run still need deployment-owner acceptance. The market-data routing delta introduces
no schema or new dependency. The combined release also includes OAuth and newer
main migrations: follow current `AGENTS.md` and run the reviewed full
`python -m app.schema` before deploying that whole app; a broker-only migration or
`data_pipeline.init_schema` alone is insufficient.

## Coverage decision — checked October 18, 2026

| Data needed | Databento service | Tau route in this release |
| --- | --- | --- |
| Historical stock/ETF bars | Yes, dataset-dependent | Databento when configured as primary |
| Historical futures bars | Yes | Databento, explicit exchange dataset and raw contract |
| Latest equity trades/quotes | Yes, through its separate live service | Alpaca snapshots; Databento live ingestion is not implemented in Tau |
| OTC spot FX | No current published replacement | Massive FX bars/quotes |
| Daily Treasury yields and funding observations | Rate futures are different instruments; no documented equivalent to these series | Massive macro tools |
| Options quotes and contract universe | OPRA plus definitions/parent symbology can construct chains | Tau does not yet implement that Databento workflow |
| Options chain with pre-calculated Greeks/IV | Databento says it does not provide pre-calculated Greeks/IV | Massive chain snapshots, subject to entitlement |

Primary sources: [stock/ETF coverage and forex FAQ](https://databento.com/stocks),
[options and analytics FAQ](https://databento.com/options),
[interest-rate futures](https://databento.com/futures/interest-rate),
[OPRA chain example](https://databento.com/docs/examples/options/equity-options-introduction/using-parent-symbology-to-fetch-an-option-chain).
The macro conclusion is an inference from the published product catalog, not an
assertion that a currency or rate futures contract is interchangeable with spot
FX, a Treasury yield observation or SOFR itself.

`EQUS.MINI` blends component venues; its mini-NBBO and traded volume are not the
full U.S. SIP. [Mini specification](https://databento.com/docs/venues-and-datasets/equs-mini).
For consolidated daily equity OHLCV/volume, consider `EQUS.SUMMARY`, which supports
daily bars rather than native hourly/minute bars. [Summary specification](https://databento.com/docs/venues-and-datasets/equs-summary).
Select datasets and granularity for the intended research, rather than joining
incompatible feeds. Databento live subscriptions, external-model processing,
non-display use and customer redistribution require the relevant provider rights.

Alpaca brokerage/OAuth is separate from this market-data routing. Databento is a
data vendor; selecting it does not connect brokerage accounts or place orders.

## One protected configuration file

Use the dedicated [market-data template](../config/market-data/.env.example).
It selects Databento historical bars, retains Alpaca current snapshots and Massive
FX/macro/options tools. Its keys are blank and its Databento estimate limit is
zero: **it intentionally fails preflight until the operator completes it**.

On the target worker host, from the deployed `kalshi_trade_infra` root:

```bash
sudo install -m 600 config/market-data/.env.example /root/tau-market-data.env
sudoedit /root/tau-market-data.env
sudo .venv/bin/python scripts/configure_market_data.py --env-file /root/tau-market-data.env
```

Populate keys privately from the shared vault/provider console or an existing
trusted deployment job. GitHub Actions Secrets are not downloadable by a manual
operator. Never commit the completed file, print it, or upload it as an artifact.
File values override matching process-environment values, including blanks; remove
blank credential assignments if deliberately inheriting the process environment.
Unknown names, shell expansion and executable expressions are rejected. The
helper writes all effective market-data settings, including defaults for omitted
fields, so old enabled flags/feeds in `.env.app` cannot unexpectedly reappear.

Set these deliberately:

| Setting | Meaning |
| --- | --- |
| `TAU_MARKET_DATA_PRIMARY=databento` | Omitted-provider `bars` requests use Databento |
| `TAU_DATABENTO_ENABLED=1` | Make the Databento adapter available |
| `TAU_DATABENTO_DEFAULT_DATASET=EQUS.MINI` | Dataset for omitted-provider bars; explicitly licensed choice |
| `TAU_DATABENTO_DATASETS=EQUS.MINI,GLBX.MDP3` | Allowed datasets only; remove unlicensed examples |
| `TAU_DATABENTO_MAX_COST_USD` | Positive decimal estimated-download limit per agent-data context, chosen by the owner |
| `TAU_ALPACA_ENABLED=1` | Retain current equity snapshots with the server's data key pair |
| `TAU_MASSIVE_ENABLED=1` | Retain configured FX/macro/options tools |

The Databento limit is shared across requests in a context and reserved before
downloads; it resets with a new context/process. **It is not a durable account-wide
billing cap.** Vendor invoices/limits and durable cost accounting remain deployment
considerations before broad paid rollout. The newer main worker schedules
autopilot reviews for enabled users (600 seconds by default); each new copilot
context gets a fresh estimate limit. Include those recurring reviews, user count
and worker concurrency when accepting a paid pilot. The per-context guard does
not impose a daily or monthly ceiling. No Exa quota or credential changes are
included here.

Disable an optional provider with its `*_ENABLED=0` flag; its key is then optional.
Use `TAU_ALPACA_FEED=iex` or licensed `sip`. Use Massive `end_of_day` FX unless the
account is entitled to `realtime`. Remove Massive `options` if chain access is not
licensed; earlier local checks returned 403 for chains and current FX quotes.
Preflight validates local settings, not those commercial entitlements.

For a **Databento-only historical pilot**, set both `TAU_ALPACA_ENABLED=0` and
`TAU_MASSIVE_ENABLED=0` while keeping the Databento settings above. This intentionally
leaves live equity snapshots, spot FX, macro observations and options-chain
analytics unavailable. It does not implement Databento streaming or alter the
Kalshi/Coinbase historical collectors and backtest inputs.

## Install and load in the real worker

After the preflight succeeds, the operator applies the file:

```bash
sudo .venv/bin/python scripts/configure_market_data.py \
  --env-file /root/tau-market-data.env --apply --output /opt/kalshi/.env.market-data
```

The helper validates first, then writes only recognized market-data values to a
separate Bash-compatible, mode-0600 file using an atomic rename. It rejects
symlinks/insecure input and output files. It does not modify `.env.app`, OAuth,
encryption/auth/billing settings, AWS parameters, services or trading flags. Do not
use the broader `load_app_secrets.sh` just for this task: that script also changes
other app settings and restarts web and agents. The overlay is the worker's final
market-data configuration: rotate these keys by reapplying the focused helper,
rather than only updating an older `.env.app` value that the overlay overrides.

Deploy the **whole `app/` package**, the helper and the updated
[`recursive-agents.service`](../scripts/systemd/recursive-agents.service) using the
team's normal reviewed release. Preserve the target's existing `.env.aws`,
`.env.app`, `APP_SECRET_KEY`, dependencies and any service resource/custom settings.
The agent unit loads `.env.market-data` **after** the two existing environment files.
Missing overlay retains previous behavior; a present broken file fails startup.
The helper's successful exit does not deploy code or update an installed unit.

For an existing systemd installation, after reviewing the installed-unit diff:

```bash
sudo install -m 644 scripts/systemd/recursive-agents.service /etc/systemd/system/recursive-agents.service
sudo systemctl daemon-reload
sudo systemctl restart recursive-agents
```

Restarting the worker can interrupt active research jobs; drain or wait for them
first. Restart only the intended agent service for this configuration change.
For a whole-app release follow the existing web-box deployment procedure, Tau
CloudFront invalidation and HTTP-200 verification as well. No collector or order
engine restart is needed for this market-data overlay.

Containers/other hosts can inject the same names into the worker process and run
`.venv/bin/python -m app.market_data_config check` there before starting it. The CLI
prints only safe readiness/capability metadata, makes **zero network requests**,
and exits `0` for locally ready configuration or `2` for invalid/incomplete settings.
The application does not automatically read a developer's `.env` or infer secrets
from a GitHub clone.

## Verify availability before calling production accepted

In a privileged, private shell on the worker, load its exact trusted runtime files:

```bash
cd /opt/kalshi
set -a
. ./.env.aws
. ./.env.app
. ./.env.market-data
set +a
unset AWS_PROFILE
.venv/bin/python -m app.market_data_config check
```

Then use `app.databento_data estimate` against a small, known completed window,
the selected dataset and a symbol in that dataset. For example (replace the dates
with an entitled completed window):

```bash
.venv/bin/python -m app.databento_data estimate SPY --dataset EQUS.MINI \
  --start 2026-10-16T14:00:00Z --end 2026-10-16T14:10:00Z --timeframe 1Min
```

`estimate` contacts availability/cost metadata and starts **no time-series download**.
It does not prove that a paid download or live subscription will work. After the
owner accepts the estimate, the corresponding `bars` command performs a bounded
download with a fresh cost check. Neither command places orders. Do not publish
raw provider data or credentials as deployment evidence.

Finally run a genuine small queued copilot/research request. Confirm the agent
events show `provider=databento`, the intended dataset and actual completed bars;
inspect timestamps and any clipping/missing symbols. Check historical research
does not see bars after its training cutoff. Verify requested optional Alpaca and
Massive tools separately, including entitlement failures. Save redacted evidence
with deployed commit, worker configuration names, request/run IDs and outcomes.
Service-active or web-health checks alone do not establish worker/data acceptance.

## Routing contract and rollback

An omitted provider on `kind=bars` uses the configured primary; omitted dataset
then uses its default. Explicit `provider=alpaca` stays Alpaca through validation
and execution. Futures should name `provider=databento`, their exchange dataset and
an explicit raw contract, rather than relying on the equity default. Snapshots
remain Alpaca; FX/macro/options-chain requests specify Massive. There is no silent
fallback on missing keys, disabled providers, plan errors or missing datasets.

With Databento primary, historical research no longer downloads an automatic
duplicate Alpaca history watchlist. Databento remains on demand, announced in model
capabilities before the agent requests it. In the current copilot, Alpaca snapshots
can still initialize current context. The training start/cutoff and completed-bar,
cost and request checks stay in force. These are supplementary agent context, not
new executable equity/futures strategy features or historical options backtests.

Before applying, keep a mode-0600 local backup of any existing overlay and service
unit. To roll back configuration, restore the previous protected overlay and
restart only the agent worker. To remove a first-time overlay, restore the previous
unit and remove the overlay; the old `.env.app` provider configuration resumes.
Those base flags may have been disabled before this deployment. Never roll back
with a developer's entire `.env` or rotate the production encryption key.
