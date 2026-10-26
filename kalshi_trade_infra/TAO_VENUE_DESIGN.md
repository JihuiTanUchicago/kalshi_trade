# TAO Subnet Tokens as a Tau Venue — Design & Feasibility Spec

**Status:** design / feasibility only. Nothing here is built, committed, or deployed.
**Requested by:** James Chen (customer) — "can Tau research/trade Bittensor subnet tokens?"
**Author:** backend (ponytail mindset — minimal surface, reuse before build).
**Date:** 2026-10-17

---

## TL;DR verdict (read this first)

| Dimension | Verdict |
|---|---|
| **Research / backtest TAO signals in Tau** | **Achievable**, and it fits — *if* we add a parallel continuous-price backtest path and reuse the existing code-strategy spec surface + the gatekeeper's return-series stats. ~1–2 weeks after a 2–4 day spike. |
| **Live execution** | **Blocked, and out of scope for now.** There is no REST order API for alpha tokens. Buying = on-chain `stake` into a substrate AMM pool (wallet + extrinsics + slippage), not an order book. A separate subsystem, gated on wallet/key custody. |
| **Short** | **Not possible on-chain today.** "Coming soon" on taostats ≠ a mechanism exists. You cannot short an AMM-only asset without a borrow/perp venue, which Bittensor does not natively have. Design for long-only; leave a short hook, don't build it. |
| **Data** | **Achievable via the taostats API** (user must supply an API key). Main risk: **candle granularity is likely hourly/daily, not 1-minute** — which shrinks sample size and bites the gatekeeper's statistical power. |
| **Does it fit Tau's framework?** | **Mostly yes, via one specific seam** (the sandbox code-strategy path), **plus one genuinely new component** (a spot/price-series backtester). It does **not** fit the binary DSL, and we should not try to bend that. |

**Core finding:** Tau's binary machinery (digital-option fair value, strike/moneyness, YES/NO mirror, $0/$1 settlement) is *not adaptable* to a continuous-price instrument — those are baked into `spec.py` and `backtest.py`. But Tau already has an instrument-agnostic seam we can exploit: the **code-strategy sandbox** (`signals(window)` → target book → shared sizing/fee/settlement loop) and the **gatekeeper**, which judges a *per-trade net-return series* that doesn't care whether the trade was binary or spot. The right design reuses those two layers and adds exactly one new thing: a long/short price-series simulator.

---

## A. Instrument model decision

### A.1 Why the binary model can't stretch to TAO

A Kalshi contract and a TAO alpha token are different *kinds* of objects. The binary assumptions are not parameters — they are structural, and they live in specific lines:

| Binary assumption | Where it lives | Why TAO breaks it |
|---|---|---|
| Fair value = digital option `Φ((ln(S/K)+μT)/σ√T)` | `app/trading/spec.py::fair_yes` | No strike `K`, no expiry `T`, no settlement. An alpha token is just a price. |
| `moneyness = ln(spot/strike)`, `z_score`, `tte_min` | `app/trading/markets.py::snapshot` | There is no strike or time-to-expiry to compute. |
| NO is the mirror of YES: `(1-yes_bid, 1-yes_ask)` | `app/trading/spec.py::side_prices` | Long/short a token is not a 0–100¢ complement. |
| Settlement: `won = result == side`, payoff ∈ {$0,$1} | `app/trading/backtest.py::simulate` / `simulate_pairs` | A token never "settles". PnL = `qty·(exit_price − entry_price)`. |
| Placebo: win-value `1/entry_price` on cheap contracts | `app/research/gatekeeper.py::_placebo_pvalue` | Binary-specific; meaningless for a continuous price. |

Retrofitting these would mean a pile of `if instrument == "binary"` branches through the hottest, most-tested code in the repo. That is the fragile-hack path AGENTS.md warns against. Reject it.

### A.2 What *does* already generalize (reuse these verbatim)

Three layers are already instrument-agnostic and we pay nothing to reuse them:

1. **`spot_candles_1m`** (`app/schema.py:42`) — keyed by `(symbol, start_ts)`, already generalized beyond BTC ("so the backtester can price any crypto series off its own underlying"). A subnet alpha price series is just another `symbol` (e.g. `TAO-SN64`). **Zero schema change.**
2. **The code-strategy sandbox** (`app/trading/spec.py` `CODE_SPEC_KEYS`, `app/research/sandbox.py`, `app/trading/backtest.py::_code_book`) — an agent writes `signals(window)` returning a target book per frame; the shared `simulate()` loop does sizing/fees/settlement. The signal logic is *already* decoupled from the digital-option DSL. This is the seam.
3. **The gatekeeper + `app/research/stats.py`** — bootstrap CI, PSR/DSR, LORD++ FDR, Benjamini-Hochberg, cross-day folds all operate on `_per_trade` net returns (`pnl/cost`), which is instrument-agnostic. Only `_placebo_pvalue` is binary-specific.

### A.3 Recommended representation — opinionated

**Represent a TAO subnet token as a research-only `Market` whose `underlying` is its alpha-price series in `spot_candles_1m`, traded through a new continuous-price (spot) backtest path, with strategies expressed as sandbox code-strategies — not the digital-option DSL.**

Concretely:

```
Market("tao_sn64", series="TAO_SN64", label="Bittensor SN64 (Chutes) alpha",
       candle_minutes=60,          # match taostats granularity (see §B.4)
       underlying="TAO-SN64",      # its own row-symbol in spot_candles_1m
       deployable=False)           # research only; engine never ticks it
```

Add one discriminator to `Market` (the single minimal new field):

```python
kind: str = "binary"   # "binary" (Kalshi contracts) | "spot" (price-series long/short)
```

`backtest.simulate()` branches on `market.kind` **once** (same pattern it already uses for `spec.get("cross")` → `simulate_pairs`), routing spot markets to a new `simulate_spot()`. No binary code changes.

### A.4 The new component: `simulate_spot()`

This is the one genuinely new piece. It is small — it's `simulate()` minus settlement minus the contract bookkeeping:

```
┌────────────────────────── signal flow ──────────────────────────┐
│ taostats OHLC ─► spot_candles_1m[symbol=TAO-SN*]                  │
│        │                                                          │
│        ├─► BtcSeries-style price series (reuse windowed ret/vol)  │
│        │                                                          │
│   spec.code: signals(window) ──► target position per frame       │
│        │        (long / short / flat, size)                      │
│        ▼                                                          │
│   simulate_spot(): for each frame                                 │
│      • mark open positions to current price                       │
│      • apply stop/exit from the target book                       │
│      • open new positions at fill price = f(price, pool depth)    │ ← pool-impact fill
│      • PnL = qty·(exit−entry) − fees(swap/slippage)              │
│        ▼                                                          │
│   Trade list (same dataclass) ──► backtest.metrics ──► gatekeeper │ ← reused verbatim
└──────────────────────────────────────────────────────────────────┘
```

Key decisions inside `simulate_spot`:

- **Position, not contract.** `side ∈ {"long","short"}`. No strike, no `close_ts`. A position closes only on an exit signal (or end of window at mark price).
- **Fill price ≠ mid.** Alpha tokens trade against an AMM pool; the executed price moves with trade size vs pool reserves (`α_price = τ_pool / α_pool`; actual fills slip). **The backtest must apply a pool-impact fill model from the subnet's reserve depth**, not fill at the printed price. Filling at mid is the single most dangerous way this backtest could lie. (`# ponytail: linear depth-impact model from reserves first; upgrade to full constant-product curve only if fills prove materially off.`)
- **`Trade` reuse.** The existing `backtest.Trade` dataclass already carries `entry_price/exit_price/qty/fees/pnl` with `pnl = qty·(exit−entry) − fees`. For spot it works **unchanged** — no new return type.
- **Fees.** Not Kalshi's taker fee. Model: swap slippage (from depth) + any chain/tx cost. One small `tao_fees.py` mirroring `data_pipeline/kalshi_fees.py`.

### A.5 The spec surface: reuse the code path, skip a new DSL

**Do not invent a continuous-price DSL in phase 1.** The digital-option DSL (`model`/`entry`/`exit`/`side`) is meaningless without strikes. Instead:

- A TAO strategy is a **code-strategy** (`spec = {market, sizing, code}`), where `signals(window)` returns `{"side": "long"|"short", ...}` per frame. This path already exists, is sandboxed (no net/DB/FS), and already flows through sizing/fees via `_code_book`. We extend the allowed `side` values and the `window` contract (price frames instead of contract frames) — a contained change in `spec.py`/`sandbox.py`/`backtest.py::_code_entries`, not a new language.
- **If** a declarative DSL is wanted later, add a tiny spot DSL (`entry: {signal, threshold}`, `exit: {stop_loss_pct, take_profit_pct, trail}`) — but that's YAGNI until the spike proves the signals are real. Ship code-strategies first.

### A.6 Gatekeeper adaptation — one new function, everything else reused

`judge_validation` / `judge_batch` / `judge_holdout` and all of `stats.py` work on the net-return series unchanged. The **only** binary-specific thing is `_placebo_pvalue` (it assumes $0/$1 settlement and `1/entry_price` win values). For spot, add a spot negative control:

- **Spot placebo:** circular block-bootstrap / random sign-flip of the per-trade return series (or random-entry-time resampling against the same price path). Same intent — "is this edge distinguishable from noise on this price path?" `_classify` already takes `placebo_passed` as a bool, so wiring a `kind`-appropriate placebo in is a one-line dispatch.

Net gatekeeper change: ~1 new function + a dispatch. The statistical spine (CI, PSR/DSR, FDR, cross-day generalization) is reused as-is, which is exactly the property that makes TAO fit Tau at all.

---

## B. Data path

### B.1 Source: the taostats API

- **Base:** `https://api.taostats.io` (v1). Auth: an API key in the `Authorization` header, **no `Bearer` prefix** ([API reference](https://taostats.io/docs/api-reference)). The old `/api/…` paths **retire 2026-11-09** — build only on the new v1 reference.
- **Pricing/rate limits:** not published; "start free or upgrade." **The customer (James) must provision a taostats API key and tell us the plan's rate limit and candle granularity.** This is the single hard external dependency for the spike. (A self-hostable alternative exists — [OpenTaoAPI](https://github.com/RyanMercier/OpenTaoAPI) — and there's a [taostats MCP server](https://mcp.taostats.io/); fallback only.)

### B.2 Exactly what to pull

| Data | taostats surface | Tau use |
|---|---|---|
| **Subnet alpha price (OHLC history)** | Subnets group: *Get Price History* / *Get Price OHLC* | The price series → `spot_candles_1m[symbol=TAO-SN*]`. The backtest's underlying. |
| **Subnet pool reserves** (`τ_pool`, `α_pool`) | Subnet pools endpoint | **The pool-impact fill model** (§A.4). Depth = how much a trade moves price. Non-optional for honest fills. |
| **Emissions / emission weight per subnet** | Subnets group (24 endpoints) | Tokenomics signal (§C). |
| **Registration events / cost** | Subnet registration endpoint | Event signal (§C). |
| **Stake / staking flows per subnet** | Subnet stake endpoints | Flow signal + unstake-pressure risk (§C). |
| **TAO/USD price** | Price group (`/v1/price?asset=tao`) | Denominate alpha PnL in USD/TAO; cross-asset context. |

### B.3 Storage — reuse what exists, add one small table

- **Price series → `spot_candles_1m` unchanged** (symbol = `TAO-SN{n}`). No migration, no new reader — `repository.load_history` already selects by `symbol`.
- **One new table** `tao_subnet_features` keyed `(netuid, ts)` for the non-price signals (emission weight, pool reserves, registration flags, net stake flow). This mirrors the existing `model_features_1m` join-by-(key, minute) pattern, so the code-strategy `window` can carry these features exactly like micro-features are carried today. Keep it in a `tao_repository.py` (the `*_repository.py` pattern AGENTS.md mandates), not inline.
- **Collector:** one `data_pipeline/taostats_collector.py` polling the endpoints above on a cron (hourly, matching granularity), writing both tables. Mirrors `coinbase_collector.py` / `snapshot_collector.py`.

### B.4 The granularity landmine (call it out now)

taostats OHLC is very likely **hourly or daily**, not 1-minute (TAO itself prints daily candles on the old `/api/price/ohlc/v1`). Consequences:
- `Market.candle_minutes` becomes 60 or 1440, not 1.
- **Far fewer decision frames → far fewer trades → the gatekeeper's `min_sample=30`, `min_oos_trades=10`, and 4-fold cross-day generalization become hard to satisfy.** Statistical power is the real constraint, not code.
- This pushes the strategy design toward **lower-frequency, event-driven** signals (which is what the customer wants anyway) and away from intraday momentum.

**Action for James:** confirm the finest OHLC granularity his taostats plan exposes. It sizes the whole research design.

---

## C. Strategy space (concrete mechanisms)

All of these are price/flow/event signals — no fair-value model, because there's no settlement. These map cleanly onto `signals(window)` code-strategies.

1. **Momentum / trend on alpha price.** Standard; reuse the windowed return/vol machinery (`BtcSeries`-style). Weak at daily granularity but the baseline.
2. **Emission-weight shifts (tokenomics).** Under dTAO, emissions are redistributed across subnets by price/stake weight; emissions compound each ~24h era. A subnet gaining emission share has a structural tailwind. **Signal:** rising emission weight → long the alpha. Durable because it's mechanical, not sentiment.
3. **Subnet registration / churn events.** New registrations and registration-cost spikes signal attention/competition. **Signal:** registration surge in a theme → momentum precursor on related subnets.
4. **Staking-flow momentum & unstake-pressure risk.** Net TAO inflow to a pool raises alpha price (pool ratio); large unstakes crater thin pools. **Signal:** net-stake-flow z-score as a leading indicator; also a *risk filter* (avoid longs into heavy unstake flow).
5. **Revenue-buyback subnets.** Some subnets buy back their own alpha with product revenue (e.g. Chutes/SN64), creating organic, non-speculative demand. **Signal:** structural bid — favor longs on subnets with on-chain buyback + real usage. The most "alpha-durable" of the set.
6. **Relative value (cross-subnet).** Long a strengthening subnet / short a weakening one — *conceptually* reuses the cross-sectional pair idea, **but shorting is unavailable on-chain (§D)**, so RV is research-only until a short venue exists, or expressed as a long/flat rotation across subnets.

Sources for mechanics: [dTAO/alpha tokens](https://docs.taostats.io/docs/alpha-tokens), [subnet pools](https://docs.taostats.io/docs/subnet-pools), [dTAO ecosystem](https://www.coingecko.com/learn/top-bittensor-subnets-dtao), [dTAO beginner's guide](https://www.tao.media/the-complete-beginners-guide-to-dynamic-tao-dtao/). Treat all as untrusted/secondary — verify numbers against the API before trusting a signal.

---

## D. Execution feasibility (the blocker)

**There is no order-placement API for alpha tokens.** Unlike Kalshi (REST orders), buying alpha = submitting an on-chain **substrate extrinsic** that `stake`s TAO into the subnet's AMM pool; selling = `unstake`. This means:

- Execution needs a **Bittensor wallet (coldkey/hotkey) + signed extrinsics + a chain RPC node**, not an HTTP order client. Entirely different from `data_pipeline/architecture/` and the Kalshi exec path.
- **Fills are AMM swaps** — price impact scales with trade size vs pool depth. On thin subnets, even small size moves the price materially. No "limit order" in the Kalshi sense.
- **No native short.** You cannot borrow or perp an alpha token on-chain. taostats' "short coming soon" refers to some future product, not an existing mechanism. **Do not design execution around shorting.**
- **Key custody & authorization.** This touches real funds via a self-custodied wallet. Per AGENTS.md, live order placement requires explicit, separate authorization and must stay off by default — the same gate as `live_trading_engine.py`.

**Conclusion:** execution is a **separate subsystem**, not an extension of the Kalshi engine, and it's blocked until (a) James wants paper→live at all, (b) wallet/key custody is designed, and (c) a short venue exists if shorting matters. Research does **not** need any of this.

---

## E. Phased plan + effort

Research-only, long-only first. `deployable=False` throughout — the live engine never ticks a TAO market, so none of this can place an order.

### Phase 0 — Spike (2–4 days) — *can Tau even reason about TAO?*
- James provisions a taostats API key; confirm OHLC granularity + pool-reserve endpoint.
- Throwaway script: pull OHLC + pool reserves for ~5 subnets → load into `spot_candles_1m` + a scratch features table.
- Write `simulate_spot()` (long-only) + a depth-based fill model + one momentum `signals()` and one emission-weight `signals()`.
- Run through the **existing** `backtest.metrics`. **Deliverable: an equity curve + PnL/Sharpe for a TAO momentum and a TAO emission strategy on real history.**
- **Gate:** if signals look like noise at the available granularity, stop here and tell James the data doesn't support it. Cheap, honest kill switch.

### Phase 1 — Research integration (1–2 weeks) — *Tau researches TAO end-to-end*
- `Market.kind="spot"` + 3–5 subnet markets (`deployable=False`).
- `simulate_spot()` productionized; `simulate()` routes on `kind`.
- `taostats_collector.py` + `tao_repository.py` + `tao_subnet_features` table + `tao_fees.py` (slippage model).
- Extend the code-strategy `window`/`signals` contract to spot (`side ∈ {long, short-stub}`).
- Gatekeeper spot placebo (§A.6); everything else reused.
- Partitions/provenance: register TAO markets with the partition + FDR machinery so experiments are ledgered like BTC ones.
- **Deliverable: the agent proposes/validates TAO strategies through the normal research pipeline, with real statistical gating.** Long-only.

### Phase 2 — Execution (BLOCKED, separate subsystem, weeks+, needs authorization)
- Bittensor wallet + extrinsic signing + chain RPC; AMM-aware execution + slippage guards; paper mode first.
- **Do not start** without: explicit live-trading authorization (AGENTS.md), key-custody design, and a decision on whether shorting (unavailable on-chain) is a requirement.

```
Phase 0 spike ──pass?──► Phase 1 research pipeline ──James wants live?──► Phase 2 execution
   2–4d          │              1–2 weeks                 (blocked)         separate subsystem
                 └─fail──► report "data too thin", stop
```

---

## F. Honest feasibility verdict

- **Achievable now:** research + backtest of long-only TAO momentum/event/tokenomics signals, judged by Tau's real statistical gatekeeper. It fits Tau **through the code-strategy seam + a new spot simulator + reused stats** — *not* through the binary DSL, which we should leave untouched.
- **Fits the framework, with one new component.** We reuse `spot_candles_1m`, the sandbox, `Trade`/`metrics`, and the entire statistical spine. We add `simulate_spot()`, a spot placebo, a collector/repository/features table, and a `kind` flag. That's a bounded, DRY change — no fork of the binary engine.
- **Blocked on data specifics:** candle granularity (likely hourly/daily) caps statistical power and may make some strategies untestable. **This is the thing most likely to kill or shape the project — resolve it in Phase 0.** Also blocked on James providing an API key.
- **Blocked on execution:** no REST venue; on-chain AMM only; no native short. Execution is a separate, authorization-gated subsystem, not part of this spec.
- **Separate sub-system?** The *execution* side, yes (different venue, wallet, chain). The *research* side, no — it rides Tau's existing pipeline via the seam above. That split is the whole point of the design: ship the research value now, defer the hard/blocked execution cleanly.

**Recommendation:** approve the Phase 0 spike. It's a few days, costs only a taostats key, and its result (real equity curves or a clear "data too thin") is exactly the decision James is asking for — before we commit to any venue build.

---

### Key source files (grounding)
- `app/trading/markets.py` — `Market`, `Snapshot`, `snapshot()` (binary features: moneyness/z_score/strike).
- `app/trading/spec.py` — digital-option DSL (`fair_yes`, `side_prices`), and the reusable code-strategy surface (`CODE_SPEC_KEYS`, `signals(window)`).
- `app/trading/backtest.py` — `simulate()`/`simulate_pairs()` (binary settlement), `metrics()` (instrument-agnostic), `_code_book`/`_code_entries` (the seam).
- `app/research/gatekeeper.py` — `_per_trade`/`_net_returns` (instrument-agnostic), `_placebo_pvalue` (binary-specific — the one thing to replace).
- `app/research/stats.py` — bootstrap/PSR/DSR/LORD++/BH (all reusable on a return series).
- `app/schema.py:42` — `spot_candles_1m` (already generalized by `symbol`).
- `app/repository.py:1114` — `load_history` (selects price by `underlying` symbol).
- `data_pipeline/coinbase_collector.py`, `data_pipeline/kalshi_fees.py` — patterns for the new collector + fee model.
