# Execution Design — Tau order execution for Kalshi

How Tau turns a strategy's decision into contracts on (or off) the book, and how
risk control is welded to that path. This documents `MarketableLimitKernel`
(`data_pipeline/architecture/execution_kernel.py`), the live book feed
(`data_pipeline/market_data.py`), the simulated venue
(`data_pipeline/architecture/simulated_venue.py`), and how `app/engine.py` and
`data_pipeline/live_trading_engine.py` drive them.

The guiding rule, from the 2026-09-27 incident that this whole subsystem exists
to prevent: **an unfilled entry costs nothing; an unfilled (or part-filled) exit
is what costs real money.** Every control below is designed so it can only make
an order *smaller* or *abandon an entry* — and **no control can ever block or
shrink an exit's ability to get flat.**

---

## 1. Primitive: a marketable IOC limit, priced from the live book

Kalshi's v2 endpoint has no market order — a price is always mandatory — so
"cross the book" means an `immediate_or_cancel` limit priced *through* the touch.
IOC is deliberate: an order either crosses now or is gone, so there is never a
resting order whose state we must track, poll, or cancel. Every order Tau sends
is a **taker**.

The single most important input is therefore the quote the order is built from.
`MarketFeed` supplies it **websocket-first with a REST backstop and a measured
staleness guard** (`max_quote_age_seconds`, default 2.0s): a socket that silently
stops updating looks exactly like a calm market, so age is always measured, never
assumed. No fresh, tradable quote ⇒ no order (a valid, expected answer).

The kernel does three things a passthrough submitter did not:

1. **Re-prices against the live book** so the limit is on the correct side (the
   bar the model trained on is never used to price an order).
2. **Re-checks the edge at the price actually available.** If the live ask has
   run past the signal price by more than `max_entry_slippage`, the edge is gone
   — abandon, do not pay up. *Following the book must not become chasing it.*
3. **Escalates an exit through the book**, crossing one tick further each retry,
   until the position is flat or attempts are exhausted.

### Order / signal flow

```
 strategy decision (engine.decide / live_trading_engine.run_loop)
        │  TradeIntent(action, side, ticker, qty, own-side limit price)
        ▼
 MarketableLimitKernel.execute(intent)
        │
        │  for attempt in 0 .. max_attempts-1:
        │    ┌─────────────────────────────────────────────────────────┐
        │    │ 1. quote = feed.quote(ticker, max_age)                   │  stale/none ⇒ stop
        │    │ 2. [BUY] spread guard: touch spread > cap?        ⇒ abandon entry
        │    │ 3. limit = marketable price (own side, +attempt ticks)   │
        │    │    [BUY] edge gone (ask ran past signal)?         ⇒ abandon entry
        │    │ 4. child = participation cap vs remaining (floor 1 on SELL)
        │    │    [BUY] child rounds to 0?                        ⇒ abandon entry
        │    │ 5. [BUY] child*limit > notional cap?              ⇒ reject (loud)
        │    │ 6. submit(ticker, action, side, child, limit)  → IOC order
        │    │ 7. parse fill (YES wire → own-side cost basis for NO)    │
        │    │    accumulate filled / size-weighted price / fees        │
        │    │    BUY filled ⇒ stop (no chase).  SELL ⇒ loop till flat. │
        │    └─────────────────────────────────────────────────────────┘
        ▼
 ExecutionReport(accepted, status, fill_price, fill_qty, ids, fee, raw.attempts[])
        │  reports EXACTLY what Kalshi confirmed, never the requested size
        ▼
 engine books only the confirmed fill (phantom positions were the 09-27 bug)
```

The same kernel runs live and in simulation — only the *submitter* differs
(`place_limit_order` vs `SimulatedVenue`). That is what makes paper P&L
comparable to live P&L: identical pricing, crossing, edge re-check, escalation,
and now identical thin-book controls.

### NO-side money direction (unchanged, re-verified)

`order_wire_params` owns the one place that folds both legs onto the YES wire:
buy YES = bid, sell YES = ask; a NO order is its YES complement (buy NO = sell
YES = `ask` at `1 - no_price`). The kernel prices a NO order from the NO side of
the book (`no_ask = 1 - yes_bid`) and reports the fill back in NO terms.

---

## 2. Thin-book microstructure controls (new)

Prediction-market books are thin and spreads are a real cost, not a rounding
error. Four controls were added, each **opt-in and defaulting to OFF** (the
constructor arg is `None`), wired to env knobs in both kernel factories so ops
can tune them without a redeploy. Enabling any of them is a **strictly-stricter**
change: each can only shrink or abandon an order, never enlarge or speed one up.

| Control | Env knob | Applies to | Effect | Fail-safe |
|---|---|---|---|---|
| Participation cap `max_book_fraction` | `KALSHI_MAX_BOOK_FRACTION` | buy + sell | child ≤ fraction × resting touch size | SELL child floored at 1 (never traps); unknown depth not capped |
| Entry spread guard `max_entry_spread` | `KALSHI_MAX_ENTRY_SPREAD` | **buy only** | abandon entry if touch spread > cap | exits never checked |
| Per-order notional `max_order_notional` | `KALSHI_MAX_ORDER_NOTIONAL` | **buy only** | reject order if child×limit > cap | exits never checked; rejects loudly rather than silently resizing |
| Exit partial-fill continuation | (always on) | **sell only** | keep taking the remainder across escalating attempts | reports only what filled; size-weighted average price |

### Why these, grounded in the research

- **Participation cap.** Metaorder impact follows an approximately
  square-root law that is *~independent of how you slice it* **"so long as the
  participation rate is not too large"** — and the effective impact coefficient
  *grows as depth shrinks*, which is exactly the thin-touch regime a cap guards
  (Bouchaud et al. on the square-root law; TSE 2025 confirming it already holds
  at child-order level, [arXiv:2502.16246](https://arxiv.org/abs/2502.16246)).
  A naive market order "can walk through several price levels, so the average
  fill can sit well above the quoted price"
  ([DeFiRate order-book guide](https://defirate.com/learn/prediction-market-fees/)).
  The cap keeps a single taker from lifting a thin book up against itself; on a
  SELL it slices and continues, which *is* child-order slicing for liquidation.
- **Entry spread guard.** On thin Kalshi markets spreads run 5–10¢ or wider, and
  a practitioner estimate of entry cost is **taker fee + half the spread**
  ([NexusFi](https://nexusfi.com/a/prediction-markets/prediction-market-fees-costs)).
  A wide touch signals an illiquid/uncertain book; since a missed entry costs
  nothing, a non-urgent entry simply declines to pay into it. Exits must get out
  regardless, so they never check spread — the direct lesson of 09-27.
- **Exit partial-fill continuation.** General limit-order research says to cross
  the spread when waiting for a passive fill risks the position moving further
  against you (Almgren-Chriss impact-vs-timing-risk tradeoff; practitioner note
  to subtract adverse selection from spread capture). For a binary contract
  minutes from resolution, a part-filled exit still leaves contracts exposed to
  a jump to 0/1 — so the kernel now keeps taking the remainder, crossing one tick
  further each retry, instead of returning a partial and waiting a full engine
  tick (15s) for the next attempt. Entries never continue — chasing an entry up
  the book is the paying-up the edge re-check exists to prevent.
- **Per-order notional backstop.** Pre-trade notional limits enforced *in the
  execution path* are standard defence-in-depth. It sits behind the engine's own
  notional sizing and should essentially never trip in normal operation; if it
  does, a caller mis-sized, so it rejects loudly rather than masking the bug.

### What is still *not* modelled (deliberate)

- **Passive / maker posting and queue position.** Tau is taker-only by design
  (IOC, no resting-order lifecycle). Earning the maker rebate (≈¼ the taker fee;
  quoting both sides can roughly halve the effective fee —
  [botforkalshi](https://www.botforkalshi.com/blog/kalshi-vs-polymarket)) would
  require resting GTC orders, cancel/replace, queue tracking and fill polling —
  a market-making subsystem, not a tweak. **Follow-up**, scoped in §5.
- **Depth past the touch.** The ticker channel does not carry it. On BTC15m the
  touch is 2,000–3,000 contracts against orders of 25–33, so it is not the
  binding constraint there; the participation cap is the guard for the thinner
  sports/crypto venues now tradeable.

---

## 3. Risk control coupled to execution

Risk is enforced at three concentric layers; execution is the **innermost
backstop**, never the only line of defence.

```
 ┌─ portfolio / account layer (engine loop, every tick) ───────────────────┐
 │  • per-user caps: max_open_positions, max_open_notional (engine.decide)  │
 │  • loss guard: realized loss > 2× backtest worst DD ⇒ pause              │
 │  • drawdown force-sell: peak-to-now DD ≥ user limit ⇒ close + pause      │
 │  • live autopilot daily-loss kill switch ⇒ disable live + pause all      │
 │  ┌─ strategy layer (live_trading_engine) ─────────────────────────────┐  │
 │  │  • LiveSettingsRiskEngine: RED state, near-expiry, signal, caps     │  │
 │  │  ┌─ execution layer (MarketableLimitKernel) ─ innermost ─────────┐  │  │
 │  │  │  • quote staleness guard   • edge re-check at live price       │  │  │
 │  │  │  • participation cap        • entry spread guard               │  │  │
 │  │  │  • per-order notional cap   • bounded exit escalation          │  │  │
 │  │  │  • reports only confirmed fills (no phantom positions)         │  │  │
 │  │  └────────────────────────────────────────────────────────────────┘  │  │
 │  └──────────────────────────────────────────────────────────────────┘  │
 └──────────────────────────────────────────────────────────────────────────┘
```

Key coupling invariants:

- **Exits are sacrosanct at every layer.** The force-sell and the normal exit
  share one path (`_close_position_at`); the kernel's spread guard and notional
  cap are buy-only; the participation cap floors a sell child at 1. Nothing in
  the execution path can leave a position unable to get flat.
- **Book only what Kalshi confirmed.** `ExecutionReport` carries the *confirmed*
  fill qty/price/fee, never the request — a part-filled exit is booked as a
  partial and the remainder stays open for the next tick; an IOC that crossed
  nothing books nothing. This is the direct fix for the 09-27 phantom positions.
- **The live gate is untouched.** `APP_LIVE_TRADING_ENABLED` /
  `live_settings.live_enabled` and the demo/live kernel-factory gating are
  exactly as before. The new knobs cannot enable trading; set empty they are a
  no-op, set non-empty they only tighten.

---

## 4. Idempotency & latency

- **Idempotency.** Each submit carries a fresh `client_order_id`. With IOC there
  is no resting duplicate to reconcile — an order that does not cross is simply
  gone — so IOC does not need a dedup key the way a GTC order would. Each retry
  is intentionally a *distinct* cross at a new price, not a resend of the same
  order.
- **Latency.** The quote staleness guard (`max_quote_age_seconds`) bounds how old
  a price may be; a stale/missing quote stops the order rather than pricing from
  whatever was lying around. Lehalle–Mounjid note the value of liquidity
  prediction erodes with latency because there may be no time to cancel/reinsert
  — another reason Tau stays taker-only rather than managing resting quotes.

---

## 4.5 Cross-contract (relative-value pair) entry

A pair is two positions opened together — buy YES on the leg the model says is
underpriced, buy NO on the leg it says is overpriced — held to settlement as a
*relative-value* bet, not a directional one. The hedge only holds if the two legs
carry **equal contract counts**; an imbalance is a naked directional leg of real
money, the one thing a pair must never take.

On paper this is trivial (`_paper_buy_pair`: both legs in one transaction against
one balance check — both-or-neither). Real orders can't fill atomically, so the
live/demo path (`_kernel_buy_pair`) keeps the legs balanced by hand and flattens
any excess on the exchange immediately:

```
  buy YES qty                → f1 filled   ── f1 < 1 ? → return False (flat, no exposure)
  buy NO  f1                 → f2 filled   (kernel never over-fills, so f2 ≤ f1)
  hedged = min(f1, f2) = f2      excess = f1 − hedged
  excess > 0 ?  sell YES excess @ bid → u filled      residual = excess − u
  ───────────────────────────────────────────────────────────────── then record:
  hedged ≥ 1 : two OPEN rows at `hedged`  (YES fee pro-rated f_hedged, NO fee full)
  u ≥ 1      : one CLOSED row, the u-contract round-trip P&L booked (never held)
  residual≥1 : one OPEN row — the still-naked YES, TRACKED + logged loudly
  return  hedged ≥ 1
```

Every leg-1 fill is accounted for: `hedged + u + residual = f1`. Leg 1's actual
fill fee is split pro-rata across the three slices (the residual takes the exact
remainder, so there is no rounding drift), and the round-trip P&L
`u·(sell − buy) − fee_buy_slice − fee_sell` is booked so the loss/drawdown guards
see accurate realized cash.

Partial-fill cases, all handled, none left as untracked exposure:

| Case | Outcome |
|---|---|
| both legs fill fully | balanced pair recorded, no unwind, `True` |
| leg 2 under-fills | excess YES flattened, round-trip booked, pair recorded at `min` qty, `True` |
| leg 2 fills 0 | leg 1 fully unwound, round-trip booked, **flat**, `False` |
| leg 1 fills 0 | no second order sent, no exposure, `False` |
| **unwind sell under-fills** | the still-naked residual is recorded as a **tracked OPEN position** (the drawdown force-sell / loss guard closes it next tick) and logged loudly — never silently dropped |

Crash-safety: all exchange orders are sent **before** any DB write, so the
recorded state is the final, consistent picture, and the round-trip is one atomic
`insert_closed_position` INSERT (an autocommit connection can never leave a phantom
OPEN leg). The residual leg reuses the ordinary position machinery, so settlement,
marks and both guards handle it with no pair-specific code.

**Live scope — single-market only.** `cross_deploy_block` allows a cross pair on
live **iff `len(involved_markets(spec)) == 1`** (cross_strike / calendar): the
engine already ticks that one market and its frame carries every strike/settlement
leg, so both legs price off the same `tick_market` book read. A **multi-market**
pair (cross_sectional) needs a synchronized multi-market live feed the engine does
not run, so it stays research-only — refused in *every* mode (paper/demo included),
a separate future build. This gate decides only the single-vs-multi-market
question; the other live gates — gatekeeper deployment-candidate, the
`APP_LIVE_TRADING_ENABLED` switch, the Kalshi-key requirement, the `NO_SIDE_LIVE`
staged-rollout flag (a pair always buys a NO leg, so it stays subject to it) and
the typed-`LIVE` confirm — are unchanged and still run, in the same order, on top.

---

## 5. Follow-ups (deliberately out of scope)

1. **Maker/passive posting** to earn the rebate and halve effective fees — needs
   a resting-order lifecycle (GTC, cancel/replace, queue + fill polling). Largest
   and riskiest change; justify with measured fee drag first.
2. **Dynamic participation/spread defaults per venue.** Today the knobs are
   global env values defaulting OFF. A per-market default (tighter on thin
   sports/crypto, looser on deep BTC15m) would want a small liquidity profile
   per series. Recommend enabling `KALSHI_MAX_BOOK_FRACTION≈0.25` and
   `KALSHI_MAX_ENTRY_SPREAD≈0.05` on the thin venues first and measuring.
3. **Depth-aware sizing beyond the touch** once a full depth feed exists.

---

## References

- Square-root impact law and participation: TSE 2025, "The double square-root
  law" — [arXiv:2502.16246](https://arxiv.org/abs/2502.16246).
- Prediction-market fees / spreads / order-book mechanics:
  [DeFiRate](https://defirate.com/learn/prediction-market-fees/),
  [NexusFi](https://nexusfi.com/a/prediction-markets/prediction-market-fees-costs),
  [Arkm Kalshi vs Polymarket](https://info.arkm.com/research/polymarket-vs-kalshi-how-the-worlds-two-biggest-prediction-markets-compare),
  [botforkalshi](https://www.botforkalshi.com/blog/kalshi-vs-polymarket).
- Optimal execution / adverse selection background: Almgren–Chriss optimal
  execution; Lehalle–Mounjid on latency and limit-order value;
  [Passive vs. Aggressive Order Placement](https://www.tradermath.org/courses/markets-trading-and-risk/passive-vs-aggressive-order-placement).
- Kalshi fee schedule: `data_pipeline/kalshi_fees.py` (taker 0.07·C·P·(1−P),
  maker 0.0175·C·P·(1−P)).
