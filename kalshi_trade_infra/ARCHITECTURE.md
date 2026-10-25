# Architecture: a venue-agnostic trading system

Target design for the codebase and the order we migrate in. Kalshi is one adapter, not the
shape of the system: a new market (Polymarket, a crypto exchange, equities) plugs in by writing
adapters against the core's ports, with **no change to the core, the engine or research**.

Migration is strangler-style: one module per small PR, behaviour unchanged, full suite green,
import boundaries checked in CI (`.importlinter`, run by `lint-imports`). No big-bang rewrite:
live and paper engines run from `main` and several threads merge into `app/` every hour.

## Where we start (measured 2026-10-25)

| Problem | Evidence |
|---|---|
| God modules | `agent.py` 4,158 lines, `server.py` 2,814, `repository.py` 2,753 (208 free functions over ~15 aggregates), `engine.py` 2,132 |
| Kalshi baked into the core | YES/NO and the 1c grid in `spec.py`/`backtest.py`/`engine.py`; `kalshi_fees` imported by `quant`, `spec`, `backtest`, the kernel; `Market`/`Contract` assume a strike + expiry binary |
| Backtest and live share signals but not plumbing | Both call `spec.entries`/`exit_signal` and the same feature math (`options_fair`/`sports_odds`/`weather_fcst.book_for_series`), but each wires its data sources its own way (backtest loaders vs 8 optional callables on `engine.Sources`), and fills are modelled twice |
| A seam that already works | `MarketableLimitKernel(submitter, feed)` runs unchanged against the real Kalshi submitter or `SimulatedVenue`. The design generalises this pattern everywhere |
| Layer cycles | `agent -> server` (lazy import of `_researchable_markets`) |
| Two deploy targets | the collector box ships **only** `data_pipeline/`, so `data_pipeline` must never import `app` |

## Layers

```
            ┌───────────────────────────────────────────────────────────────┐
            │ app.web          HTTP routes, DTOs, auth. Calls services only.     │
            ├───────────────────────────────────────────────────────────────┤
            │ app.bootstrap    composition root: builds adapters, injects them   │
            │                  into services (one per process: web, engine, worker)│
            ├────────────────────────────────┬──────────────────────────────┤
            │ app.services                   │ app.adapters                  │
            │ research agent, backtest,      │ kalshi/ coinbase/ deribit/    │
            │ gatekeeper, engine, autopilot, │ alpaca/ sim/ db/ s3/ llm/     │
            │ tournament, reconcile          │ implement trading_core.ports  │
            ├────────────────────────────────┴──────────────────────────────┤
            │ trading_core.engine   (planned) the I/O-free decision loop, execution  │
            │                       policy and risk chain shared by backtest/paper/live│
            │ trading_core.ports    Protocols: Venue, MarketDataFeed, FeatureProvider, │
            │                       Strategy, FeeModel, Clock                         │
            │ trading_core.domain   Instrument, Quote, OrderIntent, Fill, Position,   │
            │                       Portfolio, RiskDecision. Stdlib only.             │
            └───────────────────────────────────────────────────────────────┘
  data_pipeline   ingest tier (collectors, tick recorders, archiver). May import trading_core,
                  never app. It is itself an adapter layer that writes raw data the db/s3
                  adapters read.
```

Dependency rule: arrows point down only. `trading_core` imports nothing from `app`,
`data_pipeline` or any I/O library, so it ships to both boxes and is trivially testable.
`services` and `adapters` are siblings and never import each other; `bootstrap` wires them.

## Key abstractions (`trading_core`)

| Concept | Type | Replaces / generalises |
|---|---|---|
| What is traded | `Instrument(id, kind, tick_size, lot_size, multiplier, underlying, series, terms)` with `InstrumentKind` BINARY / SPOT / PERPETUAL / OPTION / FUTURE and `BinaryTerms` / `OptionTerms` / `PerpetualTerms` | `markets.Contract`, `Market.kind`, the YES/NO special cases |
| Its key | `InstrumentId(venue, symbol, outcome)`, text form `kalshi:KXBTCD-X.yes` | bare tickers that are only unique within Kalshi |
| Market state | `Quote(instrument, ts, bid, ask, sizes, features)` | `markets.Snapshot`, `engine.LiveQuote` |
| What a strategy wants | `OrderIntent(instrument, side, qty, limit_price, reduce_only, fair_value)` | `contracts.TradeIntent` (`action`+`side` YES/NO) |
| What happened | `ExecutionReport(intent, status, fills)`, `Fill(qty, price, fee, ts)` | `contracts.ExecutionReport`, Kalshi response dicts |
| Holdings | `Position` (signed qty, avg price, realized, fees, settle) and `Portfolio` (cash + positions, one per book) | position math spread across `repository`, `engine`, `backtest` |
| Pre-trade risk | `RiskDecision`, `first_refusal(intent, checks)`: exits (`reduce_only`) skip every check, enforced once | the invariant re-implemented in `execution/guard.py`, `position_guard.py` |
| Where orders go | `Venue` port: `submit`, `net_position`, `cash`, `lookup` + `VenueCapabilities` (kinds, market orders, shorting, fractional qty, sends_real_orders) | Kalshi submitter callables, `SimulatedVenue`, perps client, Alpaca client |
| Live book | `MarketDataFeed` port: `quote`, `quotes` | `WsTickerFeed`, `engine.fetch_quotes` |
| Extra data | `FeatureProvider` port: `feature_names`, `features(instruments, as_of)` (point-in-time, absent beats guessed) | `Sources.micro/forecasts/odds/weather_actuals/options`, backtest's own joins |
| Decision logic | `Strategy` port: `decide(DecisionContext) -> [OrderIntent]`, no I/O, no clock reads | `spec.entries`/`exit_signal`/`pair_entries`, code strategies |
| Fees | `FeeModel` port | `kalshi_fees` imported directly by core math |
| Time | `Clock` port (`SystemClock` live, `FixedClock` replay) | `datetime.now()` scattered through engine and backtest |

In `trading_core.engine` (step 8a shipped the loop; 8b/8c move the engine and backtest onto it): `ExecutionPolicy` (today's `MarketableLimitKernel`,
venue-neutral via `VenueCapabilities`), `RiskChain` (kill switch, fat finger, rate limit, circuit
breaker, drawdown, exposure as `RiskCheck`s), and `TradingLoop`:

```
every decision slot (clock):
    quotes   = feed.quotes(universe)                      # live REST/ws or replayed bars
    quotes  += features from every FeatureProvider        # same providers in backtest and live
    intents  = strategy.decide(DecisionContext(...))
    for intent in intents:
        refusal = first_refusal(intent, risk_chain)       # exits always pass
        report  = execution_policy.execute(intent, venue, feed)
        book.apply(report.fills); repository.save(report)
```

Backtest = `TradingLoop(FixedClock, ReplayFeed, SimulatedVenue)`. Paper = `TradingLoop(SystemClock,
LiveFeed, SimulatedVenue)`. Live = `TradingLoop(SystemClock, LiveFeed, KalshiVenue)`. One code path;
the only difference is which adapters the bootstrap plugs in.

## The fit test: every market we touch, as adapters

| Market | Instrument | Venue adapter | Feed / features | FeeModel | Core change |
|---|---|---|---|---|---|
| Kalshi binaries (today's product) | BINARY, two outcome instruments per ticker | `adapters/kalshi/venue.py` wraps the signed submitter; owns the YES-only wire translation (`order_wire_params`) | `WsTickerFeed`; micro features from `model_features_1m` | `KalshiBinaryFees` | none |
| Kalshi native BTC perps (`kalshi_perps_*`) | PERPETUAL, `PerpetualTerms(funding)` | `adapters/kalshi/perps_venue.py` wraps `kalshi_perps_trading_client.Client`; the approve-then-send flow stays an app service | perps book + funding as a FeatureProvider | `kalshi_perps_fees(fee_tiers)` | none |
| Deribit BTC options (`deribit_options`, `options_surface`) | OPTION (data only today) | none yet; a venue later if we trade options | `DeribitSurfaceFeatures` provider: `opt_p_yes`, `opt_edge`, `opt_iv` for any BTC instrument | n/a | none |
| Coinbase spot / BRTI venues | SPOT | none (data only) | spot series provider; `spot_comp` composite | n/a | none |
| Bittensor TAO alpha tokens (`tao_*`) | SPOT | TAO venue adapter when traded | taostats provider | `TaoSwapFees` (impact stays in the fill price) | none |
| Alpaca equities paper (`alpaca_paper*`) | SPOT, fractional | `adapters/alpaca/venue.py` wraps `alpaca_paper_client.Client` | Alpaca/Databento/Massive bars | `NotionalRateFees(0.0)` | none |
| Polymarket (data since 2026-10-25) | BINARY: its outcome tokens map 1:1 to `outcome` yes/no (`adapters/polymarket/instruments.py`) | none (read-only, keyless; a CLOB order adapter only if we ever trade it) | `data_pipeline/polymarket.py` recorder; `SnapshotFeed`; `PolymarketFeatures` provider: `pm_p_yes`/`pm_edge` for any BTC binary, with strike ladders read by `trading_core.pricing.binary_curve` | `NotionalRateFees` | none |
| A crypto perp exchange (new) | PERPETUAL | REST/ws order adapter, `shorting=True` | exchange book + funding | `NotionalRateFees` with per-symbol tiers | none |

Strategy and research code read `Instrument.kind` and `Quote.features`, never a venue name.
Venue-specific quirks (Kalshi has no market orders, only a YES book, a 1c grid) live in the
adapter and in `VenueCapabilities`, which the execution policy reads instead of `if kalshi`.

## Deploy constraint

`trading_core/` is a third top-level package next to `app/` and `data_pipeline/`. Both
`deploy_web.sh` and `deploy_collector.sh` ship it in the tarball, back it up, roll it back and
byte-compile it (step 2), so any module on either box may import it.

## Migration order (ranked by payoff per unit of risk)

Each step is one or a few small PRs. "Proof" is what shows behaviour did not change.

| # | Step | Payoff | Risk | Proof |
|---|---|---|---|---|
| 1 | `trading_core` domain + ports, `.importlinter` + CI, `app/adapters`, `app/services` landing zones, this doc | the target becomes concrete and enforced | none (additive) | new tests, 7 contracts kept |
| 2 | Venues: `app/adapters/kalshi/venue.py` `KalshiBinaryVenue` (live, demo, and `.simulated(feed)` over `SimulatedVenue`) implements `Venue`; `convert.py` maps `contracts.TradeIntent/ExecutionReport` to the domain; `own_side_fill` is the one shared fill parser; ship `trading_core` in both deploys | the paper=live seam becomes venue-neutral | low | existing kernel/venue tests unchanged + adapter tests |
| 3 | `FeeModel`: `KalshiBinaryFees` over `kalshi_fees`, `kalshi_perps_fees(fee_tiers)`, `TaoSwapFees`, generic `NotionalRateFees` and the `FeesByVenue` router (unknown venue raises, never free). Done as models; `engine`/`backtest`/`spec` take a FeeModel when they move onto the step 8 loop, since every call site today is a Kalshi binary and rewiring them alone changes no number | fees stop being Kalshi-only | low | fee golden tests |
| 4 | Market readiness out of `server` into `app.services.markets` | removes the `agent -> server` cycle (delete its ignore line) | low | existing picker tests |
| 5 | FeatureProviders: options, weather forecast, sports odds, micro, cross-asset; `engine.Sources` takes `features: [FeatureProvider]`, backtest uses the same providers | one data source = one adapter instead of two wirings (the feature math is already shared, so this is lower payoff than it looks; do it alongside step 8) | medium | golden test: feature dicts identical before/after on a fixed fixture |
| 6 | Split `repository.py` into `app/adapters/db/<aggregate>_repository.py`, one aggregate per PR, `app.repository` re-exports so no caller changes. Order: community/social, users/auth, research runs/strategies, deployments/positions, order intents | the 2,753-line hotspot stops causing merge conflicts | low per PR, conflict-prone (do in quiet windows) | suite green, re-export keeps every import path |
| 7 | Instrument mapping: `app/adapters/kalshi/instruments.py` maps `markets.Market/Contract/Snapshot` to `Instrument/Quote` (`binary`, `perpetual`, `quotes` deriving the NO book, `contract` for the way back); new code uses the domain types. Done as the mapper; the legacy engine/backtest switch over in step 8 | venue-neutral identity everywhere | medium | round-trip tests |
| 8 | `trading_core.engine`: `TradingLoop`, `ExecutionPolicy` (`CrossTheTouch`), `RiskChain` (+ `kill_switch`, `max_order_notional`, `max_position`, `max_open_positions`), `QuoteFillVenue` (paper for any market, priced by a FeeModel). 8a (the loop, additive, one strategy trading a Kalshi binary and a stock in one test) is done. 8b: `app/adapters/kalshi/spec_strategy.py` runs DSL specs as a `Strategy`, and `simulate_on_loop` books trade-for-trade identical results to `backtest.simulate` under both fill models: signal-bar, and the default next-bar (`KalshiNextBarFill`: decide bar t, fill bar t+1 within the reservation price and displayed size; `position_stop` as a loop exit rule; exits rest until stale). CI fixtures cover gaps and sizes; offline, 480 random spec/dataset cases and ~100k trades show 0 differences. Real data (`scripts/loop_parity.py` on the web box, 2026-10-25): 40 btc15m cases, 8,609 trades, 0 differences. 8c: the gate's cost-stress what-ifs (slippage, fee multiplier, stake, stop) run on the loop too (`QuoteFillVenue(slippage=)`, `ScaledFees`), and `TAU_BACKTEST_ENGINE=loop` routes every DSL `backtest.simulate` call through it (default `legacy` until real-data parity covers more markets and its speed cost is measured; code strategies stay legacy). 8d, paper: `TAU_ENGINE_LOOP=paper` (the default since 2026-10-25, Todd; `off` reverts) runs a single-contract paper decision as one loop step: `SpecStrategy(sizing_at_fill=True)`, `EntryBudget` (slots, user caps read after exits, shown depth, out of cash) as risk check and sizer, `KalshiEngineExecution` (the paper kernel, or a fill at the limit without one) and `DeploymentBook` over `app_positions`, booking through the same `_paper_book_buy`/`_paper_book_exit` as the legacy path. `tests/test_engine_loop_parity_db.py` (MySQL CI job) checks rows, ledger lines and counts tick for tick; offline, 600 random cases and 6,300 bookings are identical. Pairs and code specs stay legacy. 8d, demo (flag-off: `TAU_ENGINE_LOOP=paper,demo`): the same step with the sandbox kernel, `KalshiEngineExecution` given an `OrderLog` (in-flight block, durable intent before the order, unfilled mark) and the book booking through `_book_entry`/`_book_kernel_exit` keyed to the intent; the parity test compares the order-intent log too, including unfilled entries, part-filled exits and orders left unresolved. Then live (reconcile halts, size ramp) | backtest = paper = live by construction | highest | parity harness: replay N days through old and new paths, trade lists identical, before switching either |
| 9 | Split `server.py` into `app/web/routes/*` + DTOs over services; add the `web -> adapters` forbidden contract | readable API layer | low | API tests |
| 10 | Split `agent.py` into `app/services/research/` (prompts, market picker, runner, focus, scorecard) | the research loop becomes evolvable | medium | agent tests |
| 11 | Perps and Alpaca behind `Venue`; their manual approval flows stay app services | proves the fit test in production | low (both flag-off) | their suites |

## Rules for every thread, starting now

- New venue or data-source code goes in `app/adapters/<venue>/`, implementing a `trading_core.ports`
  protocol. New pure trading logic goes in `trading_core`. New orchestration goes in `app/services/`.
- Do not grow `repository.py`, `server.py`, `agent.py` or `engine.py` with new concerns; put the new
  concern in its own module in the right layer and call it from there.
- New strategy, backtest or sizing code takes a `FeeModel` and reads `Instrument.kind`, not
  `kalshi_fees` and not a venue name.
- `data_pipeline` never imports `app` (the collector box would crash). CI enforces it.
- When a migration removes an import listed under `ignore_imports` in `.importlinter`, delete that line
  so the contract tightens. Never add an ignore line to get a PR green without saying why in the PR.
