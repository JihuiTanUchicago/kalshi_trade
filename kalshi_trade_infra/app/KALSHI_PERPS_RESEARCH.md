# Bitcoin perpetual research

This first phase adds Kalshi's native Bitcoin perpetual market data to Tau's
research pipeline. Source is merged through PR #21 and remains default off. After resolving a
local proxy-routing issue and matching native Bitcoin metadata labels, the real
client/collector retrieved production and demo candles, funding and observations
on October 23. The pinned client and collector also passed five public requests
directly from the production server. Hosted full-schema MySQL/HTTP staging passed.
The 48-hour sample has candle gaps; continuous replay, actual perps persistence and
queued-model acceptance remain pending. Nothing in this change has been deployed
or activated on the production worker. Public data access is not account access.

`btc_perp` is a research market with `kind="perpetual"` and underlying `BTC-USD`.
Its `BTC_PERP` series is an internal alias. The client discovers and verifies the
native ticker from Bitcoin market metadata rather than guessing an exchange ID.
Existing binary and spot research keep their existing data and execution paths.

## Data and controls

The dedicated client uses public GET requests on the fixed Kalshi margin API
hosts. It collects verified instrument metadata, completed one-minute candles,
historical funding payments, and current book, mark/index and funding-estimate
observations when those fields are available. Observations carry retrieval and
availability timestamps. Current quotes or estimates cannot be backdated into an
older research window. It has no API-key, account, order, transfer or signing path.

The only configuration is:

| Setting | Default | Purpose |
| --- | --- | --- |
| `TAU_KALSHI_PERPS_ENABLED` | `0` | Opt in to native Bitcoin data and research. Accepts `0`, `1`, `false`, `true`. |
| `TAU_KALSHI_PERPS_ENVIRONMENT` | `production` | Public `production` or `demo` data, stored separately. This does not enable trading. |
| `TAU_KALSHI_PERPS_TICKER` | Unset | Optional native ticker; Bitcoin metadata is still verified. |
| `TAU_KALSHI_PERPS_PROXY_URL` | Unset; direct connection | Optional explicit HTTP(S) proxy without credentials, path, query or fragment. TLS verification stays enabled. |

No new secret is required for this public-data path. Custom URL/host overrides
are rejected. Set these fields in the actual collector and Tau web/worker process
environments; merely editing an unused `.env` file does not load them. With the
flag off, the picker hides this market and direct manual/agent requests are
rejected before research is queued.

Use separate research databases/workers when evaluating production and demo.
Their stored batches are distinct, but the active `btc_perp` partition remains
frozen; changing the environment flag cannot replace its source or reset holdout.

The client deliberately ignores ambient proxy settings, `.netrc` and browser
credentials. If a host requires a proxy, configure the explicit proxy URL in that
host's process environment. Do not copy a Mac's loopback proxy address to AWS:
loopback there refers to the server. A server with direct outbound HTTPS leaves
this field unset. Provider hosts remain fixed and redirects remain blocked.

All perpetual paper, demo and live deployments are blocked in API, agent,
proposal, resume and engine paths, including perpetual cross legs or mismatched
stored strategy/market records. A successful statistical verdict cannot promote
this instrument into execution. Existing binary trading settings are unchanged.

## Try the public feed before installation

Use Python 3.12+ with the project's dependencies installed. From
`kalshi_trade_infra/`, export the opt-in fields in a test process, then request a
small completed interval:

```bash
export TAU_KALSHI_PERPS_ENABLED=1
export TAU_KALSHI_PERPS_ENVIRONMENT=production
.venv/bin/python -m app.kalshi_perps_collector \
  --start 2026-10-21T00:00:00Z --end 2026-10-22T00:00:00Z
```

Dates without a time mean midnight UTC; `--end` is inclusive. The command prints
counts, coverage status and fingerprints, without prices or account payloads.
It does not write to a database unless `--persist` is supplied. Funding retrieval
failure is recorded separately from a successful empty response. An error or
zero candles is a failed availability gate, not proof that research works.

For a reproducible public-only check on a Mac already using a system proxy:

```bash
PYTHONPATH=. .venv/bin/python \
  results/kalshi_bitcoin_perps_2026-10-23/public_feed_check.py --system-proxy
```

`--system-proxy` explicitly selects that route for this diagnostic process only;
it rejects proxy credentials. Without this option, the diagnostic uses the
explicit proxy variable or a direct connection. It never loads provider keys,
DB settings or accounts, and prints counts/status/fingerprints instead of prices.
Its success establishes readable public data, not continuous replay readiness.
Run the ordinary collector from the actual deployment environment before enabling
research. Current evidence: **2,761 production / 2,822 demo candles, six funding
records and four observations per environment; all ten HTTP responses 200**.
Both sample windows have gaps; missing bars remain unknown.

## Install and collect in an isolated environment

Choose an isolated test database and configure the normal Tau DB environment
for that process. The following are operator steps; they were **not run** on a
real database during this implementation:

1. Run `.venv/bin/python -m app.schema` against that isolated database. The full
   app migration includes the two new `kalshi_perps_*` tables. Running only
   `data_pipeline.init_schema` is insufficient.
2. Repeat the small feed check with `--persist`. It appends immutable batches and
   commits them; it does not migrate tables or start a background service.
3. Backfill available completed history, for example:

   ```bash
   .venv/bin/python -m app.kalshi_perps_collector \
     --start 2026-09-01T00:00:00Z --end 2026-10-22T00:00:00Z --persist
   ```

   One invocation is bounded to 90 days, split into sequential seven-day
   requests. This is a request bound, not a claim that Kalshi retains 90 days.
   There is no installed daemon or automatic polling schedule in this phase.
   Re-run collection explicitly as needed; `--no-observations` omits current
   observations when only historical bars and funding are wanted.
4. Load the same opt-in fields into the test web and research worker. In Research,
   select **Bitcoin perpetual** (`btc_perp`). Start a normal authenticated
   research run after checking data readiness. Account access, billing,
   cancellation and worker queue controls are unchanged.

The picker distinguishes collected history from missing history. A few candles
are not sufficient for statistical research: the first freeze requires at least
600 completed points and enough elapsed time for all three windows and two
24-hour embargoes. Funding and bar gaps can still make an otherwise populated
interval unusable. Such results remain inconclusive or are rejected with an
explicit reason; missing values are not replaced with zero funding or fake fills.

## Supported research rules

The agent can propose, preregister and test causal momentum, mean-reversion and
observed-funding rules through the existing research loop. A normalized example:

```json
{
  "market": "btc_perp",
  "sizing": {"stake": 100, "max_positions": 1},
  "perpetual": {
    "signal": "momentum",
    "lookback_minutes": 60,
    "threshold": 0.001,
    "side": "both",
    "max_holding_minutes": 1440,
    "leverage": 1,
    "taker_fee_bps": 12,
    "slippage_bps": 5
  }
}
```

`signal` is `momentum`, `mean_reversion` or `funding`; `side` is `both`, `long` or
`short`. Thresholds are fractions: `0.001` means 0.1%. Lookbacks are 1–1440
completed minutes. Stake is USD research capital, defaults to $100 and is bounded
to $1–$500. The verified native quantity step can prevent a small stake from
buying even one contract. Binary-model fields, cross trades, arbitrary strategy
code and learned models are rejected in this initial perpetual path.

The trusted simulator makes decisions from completed bars and fills at the next
contiguous open. Exact decimal cashflows respect native contract units and
quantity steps. There is one position and at most 1x available capital; losses
reduce subsequent allocation. Funding at `entry < payment <= exit` is charged
with the appropriate long/short sign, using the recorded payment mark. Finalized
payments are a cost ledger, never an earlier funding predictor. Funding signals
need estimates actually observed at or before the decision time; a backfill
cannot reconstruct uncollected historical estimates.

Costs are fixed **12bps taker fee plus 5bps adverse slippage per fill**, and the
maximum holding period is fixed at 24 hours. These are uncalibrated research
scenario assumptions, not a verified account fee tier, executable order-book
fills or a margin/liquidation model. Next-open execution assumes the prior bar
is published before that open; real latency is not measured. Short losses can
exceed starting capital. The two frontends label this as Research only, show
prices in USD per native contract, and omit unavailable trading and binary
replay/what-if controls.

## Frozen evidence and statistical gates

The first research run freezes chronological 60/25/15 Research, Validation and
Holdout windows with holding/lookback embargoes. UTC conversions are explicit,
independent of the host timezone. Each partition binds the source high-water
version **and the exact committed batch ID/fingerprint manifest**. Later batches,
corrections and lower-ID transactions committed after the freeze cannot enter
that source. Missing or changed pinned batches fail closed.

New data does not automatically rotate the active partition or reset the one-way
holdout allowance. Experiments and all phase loaders use the experiment's own
frozen source. Research-only access for the generator, preregistration/trial
counting, bootstrap intervals, PSR/DSR, multiple-testing controls and continuous
return sign-flip controls reuse the existing pipeline. Returns use research
capital rather than binary entry-price probability. A too-small holdout remains
INCONCLUSIVE and still spends its one-way evaluation. A reviewed future window
rotation policy is separate work; disabling/reactivating this flag does not
create fresh holdout evidence.

## Acceptance still required

Offline tests cover synthetic native responses through collection, storage,
frozen phases, nonzero trades and gatekeeper records; golden P&L/funding and
execution rejection cases are separate. They do not establish a real provider,
production MySQL migration or authenticated queued model run. Hosted full-schema
MySQL/HTTP compatibility and public native retrieval now pass. This Mac uses an
explicit proxy; the production server passed with direct HTTPS, including native
size-title and asset-class handling. Before activation, validate usable candle
coverage, historical contract-version validity and retained history,
real DB persistence and
source replay, then a normal research run in an isolated hosted environment.
Do not interpret synthetic profit as evidence of a tradable edge.

Implementation evidence: [handoff](../results/kalshi_bitcoin_perps_2026-10-23/HANDOFF.md).
Official sources: [Perps API](https://docs.kalshi.com/margin),
[candlesticks](https://docs.kalshi.com/margin-rest/market/get-market-candlesticks),
[historical funding](https://docs.kalshi.com/margin-rest/funding/get-historical-funding-rates),
[Bitcoin contract specifications](https://help.kalshi.com/en/articles/15357587-btc-perpetual-futures-contract-specifications).
