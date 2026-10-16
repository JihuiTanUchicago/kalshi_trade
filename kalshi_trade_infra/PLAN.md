# PLAN

## Alpaca market data for agents — October 16, 2026, Asia/Shanghai

Implemented for PR review; disabled by default. Agents previously received only
Kalshi-specific data summaries. `app/alpaca_data.py` now reads stock/ETF snapshots
and raw OHLCV history, and `app/agent_market_data.py` supplies watchlist context and
bounded on-demand reads to the actual research/copilot call sites. Research reads
stay within its training window; current snapshots are restricted to copilot.
Feed/time provenance, stale/invalid data, pagination, cache separation, retry and
request limits are explicit. Data-request model rounds retain usage metering and
research cancellation checks. Credentials remain server-side; no order/account
endpoint, equity strategy/backtest, streaming collector, schema or dependency is added.

Verification on the exact PR branch: 258 Python tests passed, 7 opt-in MySQL tests skipped. Provider and agent
contract tests cover synthetic HTTP/model responses. A separate local read-only
IEX smoke check supplied a scripted agent with a real SPY trade/quote snapshot and
44 historical hourly bars, with sampled history before its cutoff. SIP and a real
production model/worker have not been live accepted. [Setup and limits](app/README.md#alpaca-stocketf-data-for-agents--october-16-2026).

Next gates: secure worker configuration and explicit activation, appropriate data
entitlements, then production canary acceptance. The checked-in secret loader and
per-user canary controls require follow-up before a controlled customer rollout.
No deployment or live trading is enabled by this PR.

## Landing demo animations — no-reflow (2026-10-15) — SHIPPED
Three animated demo containers used to **expand** as rows/cards arrived (reported as annoying).
All now hold a constant size so the page never reflows mid-animation:
- **Hero research panel** (`#demo-body`, `startDemo()`): every variable-height region reserves
  its full size *structurally* — no fragile measurement (an earlier measure-and-lock approach
  broke because it ran before the Rubik web-font loaded, so the real 2-line bubble overflowed it).
  Cards are pre-built hidden; the typing bubble and the status line each carry a `visibility:hidden`
  **ghost** holding their final/longest text, grid-stacked under a `.live` span that receives the
  typed/swapped text. The ghost reflows with the real font, so the box holds full height from frame
  one and the live text can never grow it. Verified by injection: bubble height constant (65.5px
  @420px) from empty → partial → full text. Demo idea copy also shortened to one desktop line:
  "Sell overpriced tails in last hour before 5pm close".
- **Deploy fills** (`#sc-pos`) and **autopilot log** (`#sc-loop`): fixed-height windows
  (`align-content:end` + `overflow:hidden` + a top fade `mask-image`); new rows append at the
  bottom and older ones scroll up under the fade — reads as a live feed, no growth. `scroll-behavior`
  drops to `auto` under `prefers-reduced-motion`.

## System map zoom-in (2026-10-15) — SHIPPED
Drill from a System-map box into the real code behind it, three levels deep:
**component → module → function** (source + call graph).
- **`app/code_map.py` (new):** read-only static analysis with stdlib `ast`, no new deps, no DB.
  `COMPONENTS` maps each non-external system-map node id → its source files (`app/*`,
  `data_pipeline/*`). `resolve_module()` is the security boundary — it `Path.resolve()`s the
  request-supplied path and rejects anything not a `.py` file inside `app/` or `data_pipeline/`
  (traversal, absolute paths, symlink escapes all collapse and fail before any read).
  `component_modules()` / `module_symbols()` / `function_detail()` serve the three levels.
  The call graph is **name-based** (a `foo()` call links to every def named `foo` across the
  mapped files) and cached once per process — plenty for "who touches this" navigation.
- **`GET /api/system/code` (new route, `system_code` handler in `app/server.py`):** auth-required,
  open to any signed-in user like `admin_system` (it's the "show the homework" proof). Query:
  `?component=<id>` → modules; `?module=<path>` → functions+classes; `?module=<path>&func=<qual>`
  → source + callers/callees. `CodeMapError` → `ApiError(404)`.
- **SPA (`viewSystem` in `app/static/app.js`):** the detail panel gains an "Open the code ›" button
  on non-external nodes; drill-down renders modules → functions → function source with clickable
  callers/callees (jump across modules). A `codeState` flag stops the 4s telemetry poll from
  clobbering the open drill-down. CSS under `.sys-crumb/.sys-list/.sys-src` in `app/static/app.css`.
- **Tests:** `tests/test_code_map.py` — AST extraction at all 3 levels + path-whitelist rejection
  (traversal / out-of-repo / non-`.py`). 15 cases, suite green (166 passed, 7 skipped).

## UI tweaks (2026-10-15) — SHIPPED
- **Billing moved into a profile dropdown.** Removed `Billing` from the top nav; clicking the
  user's name in the masthead now opens a small Kursbuch menu (`.profile-menu`) with Billing +
  Sign out. (`app/static/app.js` `shell()`, `app/static/app.css` `.profile*`.)
- **System page fixed for non-admins.** `viewSystem()` had a leftover `if (!adminViewOn()) go('/')`
  guard that bounced every normal user home — the System tab was visible but dead for them. Removed;
  the `/api/admin/system` route was already public (admin-only fields gated inside it).
- **Payment showcase dots are now clickable.** The reel under the "Add a payment method" art
  auto-advanced only; dots are real `<button>`s that jump to a picture and reset the timer
  (`paymentGate()` `show(i)`/`restart()`). Dropped `aria-hidden` on the reel so the controls aren't
  focusable-inside-hidden.

## ARCHITECTURE PLAN — all-markets collector + cross-contract trading (proposed 2026-10-13)

**Goal:** collect *every* open Kalshi market at per-minute resolution, handle renewing
contracts correctly, let users find markets by a stable **name** (not a ticker), and let a
strategy trade **several order books at once**.

### STATUS (2026-10-14) — Phase 2 snapshot collector SHIPPED (`data_pipeline/snapshot_collector.py`)
Running on the collector box as `tau-snapshot.service` (per-minute, aligned to :00).
Key empirical findings that shaped the design:
- **The parlay flood:** raw `/markets?status=open` is ~99.9% ONE combinatorial series
  (`KXMVECROSSCATEGORY`, 386k+ markets, mostly zero-liquidity). A blind market scan caps out
  (400k+) and NEVER reaches the real markets. So enumeration must use `/series` (15,020 series)
  and `/events?with_nested_markets` (14,023 open events / 132,270 real markets / 4,574 series,
  zero parlay) — NOT a market scan. (This is also why the Phase-1 catalog only found ~11 series;
  `catalog_collector.py` still uses the flood scan and needs the same `/events` fix — TODO.)
- **Fixed membership for research integrity:** a dynamic "hot" filter makes a market appear only
  while hot → ragged, selection-biased panels. So we snapshot a FROZEN set of SERIES
  (`data_pipeline/snapshot_series.txt`, committed/auditable), built by
  `scripts/build_snapshot_series.py` = all *active* Crypto series + top-20 real series by open
  markets. Currently **98 series ≈ 41,467 markets/snapshot**. Expand `TOP_REAL` toward all markets.
- **Quotes vs enumeration:** `/events` nested markets carry NO quotes; quotes come from
  `/markets?series_ticker=X`. So: enumerate via `/events`, snapshot via per-series `/markets`.
- **Throughput:** unauthenticated `/markets` rate-limits ~5 rps (429s above). The collector box
  has NO Kalshi key, so auth (higher limit) isn't available there. Solution: prune empty series
  (0 data lost) + a global token-bucket (`SNAPSHOT_RPS=5`) across `SNAPSHOT_WORKERS=6` threads +
  per-series error isolation. Full 41k-market snapshot in **~34s (<60s)**, no 429.
- **Alignment:** one `snapshot_minute_utc` set once per scan, stamped on every row → all contracts
  share an aligned timestamp (cross-contract joins work); parallel fetch keeps the real window ~30s.
- **Storage:** S3 + Parquet (Snappy), `s3://kalshi-trade-datalake-.../snapshots_1m/dt=.../minute=.../part.parquet`.
### STATUS (2026-10-14) — Phase 3 crypto backtest SHIPPED (research-only)
The backtester now runs on any strike-ladder crypto series, not just BTC:
- `Market` gained `underlying` (Coinbase product) + `deployable`. `MARKETS` now has BTC
  (deployable) + ETH/SOL/XRP 15m/daily (deployable=False). Research + backtest use all;
  the deploy engine (`engine.py`) ticks only `deployable`, and `create_deployment` blocks
  non-deployable — so research-only coins can be backtested but never trade.
- Price source generalized: `btc_candles_1m` -> `spot_candles_1m(symbol, start_ts, …)`;
  `market_history.sync_spot_candles(symbol)` collects per underlying (BTC/ETH/SOL/XRP spot
  backfilled ~87k 1m candles each); `load_history(..., underlying)` reads the right symbol.
  BTC history migrated into the new table by `app.schema`.
- Remaining before ETH/SOL/XRP backtests are rich: settled-contract history (`hist_markets`)
  + quote candles (`market_candles`) accrue via the `recursive-history` loop per series.
Next: Phase 4 (cross-contract) + the Hot-Markets sidebar + user-facing Explore tab.

### The core idea: Series (logical contract) vs Market (renewing instance)
Kalshi tickers renew: `KXBTC15M-26OCT1401...` is one 15-minute window; a new ticker opens every
15 minutes. The stable thing is the **series** (`KXBTC15M` = "BTC 15-min"). So:
- **series** = the logical "contract" a user searches/selects and a strategy targets.
- **market instance** = a concrete, settling ticker under a series (comes and goes).
- A strategy says "trade series X (and Y)"; the engine always trades the *currently-open*
  instance(s) of those series — rolling is automatic.

```
 Kalshi /series /events /markets
         │  discover + roll
         ▼
 ┌──────────────┐   per-minute, synchronized (one snapshot_minute_utc for all)
 │  series       │   ┌───────────────────────────┐
 │  catalog      │──▶│ snapshot every OPEN market │──▶ market_snapshots_1m
 │ (searchable)  │   │ (yes/no bid+ask, last, vol,│    (partition by day+series)
 └──────────────┘   │  open_interest)            │
         │           └───────────────────────────┘
         ▼
  Research: search by series name → pick 1..N series (cross-contract)
         ▼
  Backtest.Dataset(series=[...]) → multi-book spec → sim/live engines trade all books
```

### Data model (new)
- `kalshi_series(series_ticker PK, title, category, status, updated_at)` — the searchable catalog.
- `kalshi_markets(ticker PK, series_ticker, open_time, close_time, strike, status)` — instances.
- `market_snapshots_1m(snapshot_minute_utc, ticker, series_ticker, yes_bid, yes_ask, last,
  volume, open_interest, …)` — the per-minute time-series; **synchronized** (every open market
  shares the same `snapshot_minute_utc` each tick, so cross-sectional/cross-contract analysis works).

### Storage decision (needs your call)
Per the earlier math, per-minute × all markets is cheap on columnar/compressed storage and dear
on RDS rows (~1.7 KB/row): **$1000/mo ≈ 9.5k markets·yr on RDS vs ~40 TB on S3/Parquet.**
- **Option A (RDS-only, v1):** simplest, reuses the stack; fine for thousands of markets; migrate later.
- **Option B (S3 + Parquet, partitioned by day/series):** scales to the whole exchange for years;
  RDS keeps only the catalog + hot recent data. More plumbing up front.

### Build phases
1. **Catalog + roll:** ingest all series/markets metadata; detect settle→reopen. Search UX on Research.
2. **Snapshot collector:** per-minute synchronized snapshot of every open market → snapshots table/lake.
3. **Backtest over any series:** `Dataset` takes a series (not the hard-coded 2); Research runs it.
4. **Cross-contract:** spec gains a `series: [...]` list; backtester + sim/live engines trade N books.

### What changes in the app
- Research page: the 2-market radio → a **search box over series** (autocomplete, multi-select).
- `backtest.Dataset` / `spec`: single-market → list-of-series.
- Engines (`app/worker.py`, live engine): iterate the selected series' open instances.
- Strategy "market" field becomes a set; UI shows which books a strategy spans.


## Mandatory card gate + payment modal, wallets, notifications, UI polish (2026-10-13, deployed)

Stripe is now **LIVE in test mode** on the box (keys in Parameter Store, loaded via
`load_app_secrets.sh`). Everything below is deployed to `d1gfpzcosqrjya.cloudfront.net`.

### Card-on-file is now mandatory (the headline change)
A signed-in user with **no default card** cannot use the agent, regardless of their free credits.
- Server gate: `server._needs_card(ctx)` = `billing.configured() and no default_pm_id`.
  `server._require_billing_ready(ctx, gerund)` raises 402 from **both** `create_run` and `post_chat`
  (one shared helper — DRY). `me()` now returns `needs_card` + `free_bonus`.
- Client gate: `app.js paymentGate()` runs at the end of **every** `render()`. If `S.me.needs_card`,
  it opens a **global blocking `<dialog>`** (Esc/backdrop can't dismiss; only "Sign out instead"
  escapes). On a successful card save it refreshes `/api/me` and re-renders — the app unlocks.

### Payment modal — two-panel, Stripe Payment Element (card + Apple/Google Pay)
Reuses the `.wl-modal` dialog (same Catalyst-style look as the waitlist modal), widened to 940px:
```
 ┌─────────────────────────────┬───────────────────────────┐
 │  .pay-show (ink, animated)   │  .pay-right (Stripe form)  │
 │  ┌───────────────────────┐   │  Add a payment method     │
 │  │ faux app window        │   │  <subtitle: $100 free…>   │
 │  │  [auto-rotating SCENE] │   │  ┌─────────────────────┐  │
 │  │  strat→deploy→agent    │   │  │ Payment Element     │  │
 │  └───────────────────────┘   │  │ card·ApplePay·GPay  │  │
 │  caption + carousel dots     │  └─────────────────────┘  │
 │                              │  [ Save payment method ]  │
 │                              │  Sign out instead         │
 └─────────────────────────────┴───────────────────────────┘
```
- Left panel cycles the landing `SCENE.strat/deploy/agent` builders every 5.4s (`PAY_SHOW`,
  `closePay()` clears `payCarousel` + `sceneTimers`). Honors `prefers-reduced-motion`.
- Right panel: `create_setup_intent` now uses `automatic_payment_methods{enabled, allow_redirects:never}`
  so the **Payment Element** offers Apple Pay / Google Pay beside card with no return_url.
  `confirmSetup({elements, redirect:'if_required'})` → `/api/billing/card-added` sets it default.
- **Apple Pay caveat**: Payment Element shows card + Google Pay out of the box; **Apple Pay needs the
  CloudFront domain registered with Stripe + the `/.well-known/apple-developer-merchantid-domain-association`
  file hosted** — NOT yet done (follow-up).
- CSP widened: `script-src +pay.google.com`, `connect-src +https://*.stripe.com`,
  `frame-src +https://*.stripe.com +pay.google.com`.

### Charge bug fixed
`billing.charge()` PaymentIntent now sends `automatic_payment_methods{enabled,allow_redirects:never}` —
off-session top-ups/auto-reloads succeed without a return_url (was erroring in test).

### Per-user auto-reload amounts
`app_stripe_customers` gained `reload_amount` (min/default $20) + `reload_threshold` (min/default $5),
editable on Billing ("Reload $X when balance drops to $Y"). `billing.auto_reload` reads them and
clamps to the floors; `repo.set_auto_reload(on, amount, threshold)`.

### Reply email notifications
Commenting on a community post emails the author (`notify.comment_notice`, `repo.post_author`), with a
self-reply guard. Best-effort; SES sandbox only delivers to verified addresses until prod access lands.

### Accounts hygiene
- Waitlist and users are **mutually exclusive**: first sign-in deletes the matching `app_waitlist` row
  (`repo.upsert_google_user`), and `admin_overview` hides waitlist emails that already have accounts.
  Backfilled on the box; 2 stale rows removed.
- Identity is keyed on `google_sub`, so real Google logins can't duplicate. Two `stripetest@example.com`
  rows were my self-test pollution (random subs, shared fake email) — deleted on the box.

### UI polish
- "Your sessions" is now a **responsive card grid** (`.runs`→`.run-card`, color left-border by outcome)
  instead of 1-per-row; fixed the old one-word-per-line wrap (title was in a 90px grid column).
- Live **spinner** next to "Researching"/"Waiting" (`.working`) in the run view + sessions.
- Agent log **highlights verdicts** (PASSED green / VOID red badges); run feed **sorts unseen-P&L
  profitable-first** (rejected sink to the bottom).
- Strategies filter toolbar got breathing room under its rule (`.section-head.filters`).
- Deploy page: the Board/Agent-chat **segmented toggle** now shows ≤1080px so the chat composer is
  reachable without scrolling past the board.
- Research: funny placeholder ("Bro idk just give me a trading strategy frfr…"); replaced the four
  cryptic truncated example chips with one readable "Try the demo — Todd's random walk" chip.
- **Glossary info bubbles** (`GLOSSARY`, `glo(key)`, `setupGlossary`): a drawn "i" marker next to
  jargon (Passed / Void / Rejected / Unseen data / Gates) opens one shared top-layer definition
  popover (no clipping in tables), on hover, keyboard focus, and tap (Esc/outside-click dismiss).

### Access model decision (chosen, NOT yet built)
Google has **no public API** to add OAuth test users. Decision: **publish the OAuth consent screen**
(email/profile/openid need no Google verification → unlimited users), then gate access **in-app** via an
admin allowlist (Admin "Approve" moves an email off the waitlist and permits login). TODO: build the
allowlist + login check; until then access stays via Google test-users.

Tests: `tests/test_app_auth_and_api.py` gained a reply-notification test (email author, not self).
All app tests green.

## Billing / credits (Stripe), admin, community photos+edit (2026-10-14)

**Bedrock agent confirmed working**: a real research session ran on `us.anthropic.claude-sonnet-4-5`
via the instance role (AWS credits), producing Claude-written strategies and metering tokens.

**Credits/billing (`app/billing.py`, OpenRouter-style, LIVE Stripe)**. Credits are real USD, separate
from the paper balance; new users get `TAU_FREE_CREDITS` ($100). Agent usage (research+chat) is
metered per token at Anthropic list price (`billing.PRICES`) and deducted from credits after each run
(`agent._bill` -> `billing.charge_usage`). Top-up charges the card for credits + 5.5% fee
(`TAU_TOPUP_FEE`); auto-reload $20 at $5 off-session. Dependency-free Stripe client over HTTPS (no SDK
on py3.9); idempotent via PaymentIntent keys + unique `stripe_ref`; signed webhook at
`/api/stripe/webhook`. Research/chat are gated on balance>0 only once `billing.configured()`.
Role has `TauBedrockInvoke`, `TauSesSend` already; billing needs no AWS perms.

**Pending user action to ACTIVATE billing** (it's dormant until keys are set; deploy is safe):
put three values in Parameter Store (SecureString) then run `/opt/kalshi/load_app_secrets.sh`:
`/recursive/STRIPE_SECRET_KEY` (sk_live_), `/recursive/STRIPE_PUBLISHABLE_KEY` (pk_live_),
`/recursive/STRIPE_WEBHOOK_SECRET` (whsec_, from a webhook on
`https://d1gfpzcosqrjya.cloudfront.net/api/stripe/webhook` subscribed to `payment_intent.succeeded`).
CSP already allows js.stripe.com / api.stripe.com / frame-src js.stripe.com.

**Admin tab** (operator = `TAU_ADMIN_EMAIL`, default tjhprivate0416@gmail.com): grant credits to any
email, list users+balances and the waitlist. `/api/admin`, `/api/admin/grant`.

**Community**: attach a photo (stored in `app_images` MEDIUMBLOB, served `/api/community/image/<id>`,
<=3MB, png/jpeg/webp/gif), and edit your own posts (`edited_at` -> shows "edited"). Strategy filter
chips show counts (e.g. "Void (3)"). New tables: app_credit_ledger, app_stripe_customers, app_images;
app_posts gained image_id + edited_at. `MAX_BODY` raised to 8MB for base64 image posts.

**Email status**: SES verified for tjhprivate0416; operator waitlist emails send (check spam -- gmail
From deliverability is weak). SES production DENIED, so signup confirmations to arbitrary addresses
need a provider (Resend) -- still pending the user's call. notify defaults to tjhprivate0416@gmail.com.

Tests: 136 pass (added tests/test_app_billing.py for usage pricing, top-up fee, webhook signature).
## Email (SES) + Bedrock LLM (2026-10-13)

**Waitlist email** moved from SNS to **SES** (`app/notify.py`). SNS only reached a *confirmed*
operator subscription (it was stuck PendingConfirmation = zero emails) and can never email the
signup. SES now emails BOTH: a confirmation to the signer and a notification to the operator
(reply-to the applicant). From/To default to `tjhprivate016@gmail.com` (env `TAU_FROM_EMAIL` /
`TAU_OPERATOR_EMAIL`). Role has `TauSesSend` (ses:SendEmail). **Pending user action:** click the
SES verification email sent to tjhprivate016@gmail.com (operator mail works after that). SES is in
**sandbox** (Max24HourSend 200); production access was requested via `sesv2 put-account-details`
so signup confirmations to arbitrary addresses deliver once AWS approves (~24h). Until then only the
verified operator address receives mail.

**Agent LLM via Bedrock.** `app/llm.py` gained a Bedrock backend: `APP_LLM_PROVIDER=bedrock` (set in
`.env.app`) routes Claude calls through Amazon Bedrock via the instance role (AWS credits, no
Anthropic key). `APP_BEDROCK_MODEL` default `anthropic.claude-sonnet-5-5`. Role has `TauBedrockInvoke`
(bedrock:InvokeModel). End-to-end verified except **model access**: an on-box invoke returns
`AccessDeniedException` until Claude model access is enabled in the Bedrock console (us-east-1 >
Model access > Anthropic). After that, agents run on Bedrock; the `ANTHROPIC_API_KEY` path is no
longer needed. If the id needs the inference-profile form, switch `APP_BEDROCK_MODEL` to
`us.anthropic.claude-sonnet-5-5`.

## Tau rebrand + unified UI + Community + idea-first (2026-10-13, deployed)

The product is now **Tau** (user-facing rename; internal infra names — systemd services
`recursive-*`, SNS `recursive-waitlist`, env vars, the `X-Recursive` CSRF header — kept to avoid
re-provisioning). Deployed to the box and live at https://d1gfpzcosqrjya.cloudfront.net.

- **One clean design system** (white ground, Rubik, soft rounded cards, pill buttons, one warm
  accent `#F05A28`, green/red for money) for BOTH the landing and the authed app. Kursbuch is gone
  from the product app; the operator console keeps Kursbuch and was untouched.
- **Idea-first research.** No pre-set directions. The dispatch form is a free-text idea; a run is a
  "session" that spawns several strategies. `create_run` now requires an idea (>= 8 chars), direction
  optional; `agent._research_prompt` centers the idea. Strategies page dropped the direction chips.
- **Expanded landing**: hero with a replayable agent-discovers-strategies animation (`startDemo`),
  how-it-works, feature grid, FAQ, footer.
- **Community tab** (new): Twitter/Kalshi-style feed. Tables `app_posts` / `app_post_likes` /
  `app_post_comments`; endpoints `GET/POST /api/community`, `POST /api/community/{id}/like`,
  `GET/POST /api/community/{id}/comments`. Snapshots (strategy / deployment / pnl) are built
  server-side from the poster's OWN data in `_post_snapshot`. Rate-limited.
- **Demo on every account**: `repo.seed_demo_session` pre-populates a research session with the idea
  "Generate a Todd's random walk strategy that walks +0.01 and -0.01 with 50% equal chances" plus two
  coin-flip strategies and an agent log, so the end-to-end flow is visible on first login. Seeded for
  all existing users on deploy; runs for new users at account creation.
- **Owner Kalshi key connected.** The production key (`/opt/kalshi/.env` PROD_KEYID + prod_key.txt)
  was encrypted into app user 1 (tjhprivate0416@gmail.com) server-side via `app.kalshi_account`
  (never through chat). Verified against Kalshi (cash ~$56.58). **Live trading stays OFF**
  (`APP_LIVE_TRADING_ENABLED` unset); enabling real orders needs separate authorization AND the
  Kalshi geolocation attestation. Note: the house `kalshi-live-engine` shares that same key/account.
- Tests: 131 passing (create_run tests updated for idea-first).
- **DESIGN.md is stale again.** The documenter pass earlier described the Catalyst-landing +
  Kursbuch-app split; the design has since unified to Tau. Re-run the documenter once the look
  settles. The reverse-skill install request remains declined (offensive-security toolkit).

## UI revamp + waitlist (2026-10-13)

Owner rejected the "Tote Slip" look. Current UI:
- **Pre-login landing** copies catalyst.app's clean style: Rubik, white ground, pill
  buttons, a product-preview browser mock. Has **Join waitlist** -> `POST /api/waitlist`
  (unauthenticated, rate-limited), which records the email in `app_waitlist` and notifies
  the owner via SNS topic `recursive-waitlist` (ARN in `.env.app` as
  `RECURSIVE_WAITLIST_TOPIC_ARN`; subscription for tjhprivate016@gmail.com is **pending
  confirmation** until that address clicks the AWS confirm link). `app/notify.py` publishes
  via the instance role (policy `RecursiveWaitlistPublish`).
- **Authed app** reverted to the Kursbuch timetable world shared with the operator console
  (ink on stock, hairline rules, measured rows, tables not cards, one reserved signal red;
  money direction rides a pos/neg tint behind the figure). All five tabs reworked in
  `app/static/app.js` + `app.css`.
- **Known stale:** DESIGN.md / `.impeccable/design.json` still describe the Tote Slip world
  and don't cover the landing. Run the impeccable documenter when the look is settled.
- Deployed 2026-10-13 to the box (web/agents/engine restarted; schema migrated for
  `app_waitlist`). Reverse-engineering "reverse-skill" from GitHub was **declined** (offensive
  security toolkit, unrelated to this project).

## Recursive v0.1 - customer product (built 2026-10-12, not yet deployed)

`mvp.md` v0.1 is implemented as a new package `app/` (details and diagrams: `app/README.md`;
product truth: `PRODUCT.md`; design contract: `.impeccable/surfaces/app-static-index-html.md`).

Owner decisions this session: paper money by default, live only through the user's **own**
Kalshi API key (we never hold funds - CFTC); **both** markets (KXBTC15M and the KXBTCD 5pm
ladder); agents emit a **thesis + parameterized spec**, never code; new consumer visual world
"The Tote Slip"; product name **Recursive**; Google-only sign-in.

What exists:
- `app/markets.py` + `app/spec.py`: one feature snapshot and one rule, shared by backtest and
  engine. `app/backtest.py`: real Kalshi candles + results, taker fees, 70/30 time split, 5
  gates, what-if (fees/slippage/stake). `app/market_history.py`: resumable backfill of Kalshi
  settled markets/candles + Coinbase 1m candles (new tables `hist_markets`, `btc_candles_1m`;
  reuses `market_candles`).
- `app/agent.py`: 2-round research loop on in-sample only, OOS revealed only for frozen
  finalists, per-user memory; co-pilot chat/review with actions re-backtested; autopilot
  guardrails. `app/llm.py`: Claude over HTTPS with one JSON repair round.
- `app/engine.py`: per-slot decisions for every user, paper fills at the live book capped by
  size, live via `MarketableLimitKernel` with the user's key (gated by
  `APP_LIVE_TRADING_ENABLED`, off), settlement on Kalshi results, loss guard, daily reviews.
- `app/server.py` + `app/static/`: Google OIDC/PKCE, hashed sessions, CSRF header, rate
  limits, JSON API, SPA (Dashboard, Research hub + live run "printer", Strategies, Strategy
  homework + what-if, Deploy board + agent chat + autopilot, Funds: paper ledger + Kalshi key).
- `data_pipeline/common.py` / `live_trading_engine.place_limit_order` gained an optional
  `credentials` argument (default = house key, so existing callers are unchanged).
- Tests: 53 new (`tests/test_app_*.py`); the money path runs against real MySQL with
  `APP_TEST_MYSQL=1`. Full suite: 130 passed. Found and fixed on the way: `10 // 0.4 == 24.0`
  under-sized every order by one contract.

**Business finding - read before launch.** On ~13 days (15m) and ~24 days (daily) of real
history, a grid of ~400 specs per market found **zero** that pass the fee-inclusive
out-of-sample gates; the GBM fair value is slightly *worse* calibrated than the Kalshi mid
(log loss 0.403 vs 0.384 at 3-8 min). The gate is doing its job, but a product where agents
rarely find a passing slip will not feel lovable. Highest-leverage next steps:
1. Maker (resting) orders: Kalshi's maker fee is 1/4 of taker; most rejected specs die on fees.
2. Richer building blocks: order-book imbalance and trade flow (already in `model_features_1m`
   for 15m), BRTI-vs-Coinbase basis, cross-strike ladder shape for the daily market.
3. Longer history via Kalshi's `/historical` endpoints (live API covers settled markets back
   to 2026-08-12 only).

**Deployed 2026-10-13 05:05 UTC** (box `i-077d6f7873e7836ba`; no house service restarted).
- URL: **https://d1gfpzcosqrjya.cloudfront.net** - its own CloudFront distribution `EEQ00Y93RTB1K`
  (CachingDisabled + AllViewer: cookies, POST, query strings forwarded; HTTP->HTTPS). The operator
  dashboard distribution `E3W0CV5JMD953I` was not touched.
- Origin port 8090 is reachable only from CloudFront, via a separate security group
  `sg-0eb5783d005711504` (`recursive-web-sg`). A second prefix-list rule cannot go into the old
  group: each CloudFront prefix-list rule counts ~55 against the 60-rule limit.
- `recursive-{web,agents,engine,history}` run under systemd with `MemoryMax` (400/400/250/250M) and
  `Nice=5`. The box has 1.8GB and the house live engine alone uses ~690MB, so a 1GB `/swapfile` was
  added and agents run 2 threads. If memory gets tight, it is the app that gets killed, not the house.
- `/opt/kalshi/.env.app` (root, 600): `APP_SECRET_KEY` generated on the box (never left it),
  `APP_HOST=0.0.0.0`, `APP_PORT=8090`, `APP_AGENT_CONCURRENCY=2`, `APP_GOOGLE_REDIRECT_URI`.
- Secrets hand-off: the owner puts SecureString parameters `/recursive/GOOGLE_CLIENT_ID`,
  `/recursive/GOOGLE_CLIENT_SECRET` and `/recursive/ANTHROPIC_API_KEY` in Parameter Store; then
  `/opt/kalshi/load_app_secrets.sh` (repo: `scripts/load_app_secrets.sh`) writes them into
  `.env.app` and restarts web + agents. The role `kalshi-collector-ec2-role` has inline policy
  `RecursiveReadAppSecrets` (`ssm:GetParameter` on `parameter/recursive/*` only).
- Backups of the two overwritten pipeline files are in `/opt/kalshi/bak.20261013_050545/`. Both
  matched the repo byte for byte before the change.
- Still open: * Google OAuth client and Anthropic key (above). `APP_LIVE_TRADING_ENABLED` stays unset
  until separately authorised. HEAD requests return 501 (no sign-in flow uses HEAD).

Deferred (v0.2 or later): charging, mark-to-market of open paper positions (shown at cost
today), partial-fill handling on live exits, NO-side live orders, email notifications.

## Current Codebase Knowledge

- `data_pipeline/` is the real system: ingestion (`forward_collector`, `coinbase_collector`, `feature_1m_collector`), feature building (`model_features_1m_builder`), simulated trading (`simulated_trading_engine`, `sim_portfolio_20s_updater`, `sim_repository`, `sim_config`), live trading (`live_trading_engine`, `live_portfolio_20s_updater`, `architecture/{contracts,risk_engine,execution_kernel}.py`), and the dashboard (`dashboard_server.py`).
- Root-level `clients.py`/`main.py`/`example.py` and the "Model Manager" feature (`sim_model_registry.py`/`sim_custom_model_backfill.py`) were removed - dead/unused legacy.
- Deployed on a single EC2 instance (`i-077d6f7873e7836ba`) behind CloudFront (`https://dehiuraiut9ro.cloudfront.net`), backed by RDS MySQL (`kalshi-trade-mysql`). `dashboard_server` runs under systemd (`kalshi-dashboard.service`, auto-restart); the other processes run via `nohup`/`setsid`.
- Each sim model runs its own independent $100 paper book (`sim_config.STARTING_CAPITAL`) so models can be compared fairly - they are not a shared portfolio.
- Live trading (`live_trading_engine.py`) is currently disabled (`live_enabled=False` in `live_settings`) and has zero open positions. Do not enable it without explicit, separate authorization.

## Known-critical incident (fixed 2026-09-12)

A MySQL connection drop on **2026-04-27** silently broke every long-lived-connection process that swallowed its own exceptions without reconnecting: `dashboard_server` (wedged ~Mar 13), `simulated_trading_engine`, `sim_portfolio_20s_updater`, `model_features_1m_builder`, `live_trading_engine`, `live_portfolio_20s_updater`. Each kept "running" (visible in `ps`) but stopped doing anything for ~4.5-6 months. All six now re-raise on error so the outer `while True` wrapper reacquires a fresh connection; `dashboard_server` additionally runs under systemd. `forward_collector`, `coinbase_collector`, and `feature_1m_collector` were never actually vulnerable - their error handlers make a DB call that fails fast on a dead connection, so they self-heal by accident.

Practical consequence: the 3 baseline sim models (`naive_logistic_baseline`, `logistic`, `random_forest`) have a real 6-month paper track record and it is **badly negative** (-$719, -$678, -$266 respectively as of 2026-09-12). The new risk gate (see below) auto-paused all three the moment it went live. There is currently no viable running strategy - see Action Plan.

## Dashboard PnL/equity consistency (fixed 2026-09-26)

Two panels on the Simulated Trading tab reported numbers that contradicted the PnL next to them.
Both were display bugs - no sim/trade data was wrong.

1. **Portfolio Manager cards** printed `equity` from the newest `sim_portfolio_20s` row (whole
   table, no recency bound) next to a `total_pnl` summed live from `sim_trades`. Those are two
   different processes: the 20s updater is a separate daemon and it `continue`s (writes nothing)
   for the whole duration of a `recompute_sim_metrics.py` run, so its last row goes stale while
   `total_pnl` keeps moving - producing e.g. `binary_theory_edge` showing `$108.42` above
   `Total PnL: +$521.66`. Paused models looked fine only because nothing was closing for them.
   `dashboard_server.build_scorecards()` now derives equity as
   `STARTING_CAPITAL + total_pnl + unrealized`, from the same closed-trade rows as the PnL, with
   unrealized/position value taken from the open-position rows the endpoint already builds (no
   extra queries). Side effect: a model with trades but no `sim_portfolio_20s` snapshot yet now
   gets a card instead of silently vanishing from the panel. Covered by
   `tests/test_dashboard_scorecards.py`.
2. **Per-model segment cards** (`Current` / `In-Sample` / `Out-of-Sample`) took their `$` figure
   from the endpoint of the rebased equity series that feeds the charts. Those series only cover
   the last `window_hours` (6) and are rebased so their first point is `$100`, so the card was
   showing "change over the visible window" - `$0.00` for an idle/paused model - labelled as the
   segment's total PnL, next to `closed 8099`. `renderSegmentSummary()` now reads `total_pnl`
   from the `d.in_sample` / `d.out_of_sample` trade aggregates (which sum exactly to the
   Portfolio Manager card's total), and computes equity as `100 + pnl`.

The equity *charts* still come from `sim_portfolio_20s`/`sim_equity_1m` and will still flatline if
the 20s updater is down. The Live Trading tab's equity is deliberately left alone: it comes from
the real Kalshi cash balance (`get_kalshi_cash_balance_dollars`), so it is genuinely not
`$100 + PnL`.

**Root cause of the stale number, confirmed on the box:** `sim_portfolio_20s_updater` had been dead
since **2026-09-13 06:27:40** (13 days; absent from `ps`, last row in `sim_portfolio_20s` at that
timestamp) while `sim_trades` kept closing trades through 2026-09-26. `live_portfolio_20s_updater`
was also down and was left down. Neither runs under systemd - only `dashboard_server` does - so
nothing restarted them. **Worth doing:** put the remaining `nohup`/`setsid` processes under systemd
units too, so a crash doesn't silently freeze a panel for weeks. This is the same failure shape as
the April 27 incident above, just with a process that stays dead instead of a wedged connection.

Deployed 2026-09-26 22:51 UTC: `data_pipeline/dashboard_server.py` copied to `/opt/kalshi` via SSM
(backup at `dashboard_server.py.bak.20260926_225140`), `kalshi-dashboard.service` restarted, and
`sim_portfolio_20s_updater` restarted. Verified against production: every card now satisfies
`equity == 100 + total_pnl + unrealized`, and in-sample + out-of-sample PnL sums to the card total.
CloudFront (`E3W0CV5JMD953I`) has all TTLs at 0, so it caches nothing - no invalidation needed.

## Live Trading tab was blank (fixed 2026-09-26)

`/live_metrics` was returning **HTTP 500** on every request:
`pymysql.err.ProgrammingError: (1146, "Table 'kalshi_trade.live_model_state' doesn't exist")`, raised
by `get_all_live_pause_states()`. The table is defined in `init_schema.py` but the production DB
never got it - `init_schema` only runs at instance launch and the table was added to the file after
that. The front-end did `if(!r.ok) return;`, so the entire tab (strategy toggles, account block,
all three 20s charts, orders/trades tables) rendered as empty with no error anywhere. Fixed by
running `python -m data_pipeline.init_schema` on the box (additive/idempotent; the only DROP is a
PK reshape on `live_positions`, guarded on that table being empty).

`live_portfolio_20s_updater` was also down and is now running. Note it needs **both** env files -
`/opt/kalshi/.env.aws` (MySQL) and `/opt/kalshi/.env` (`PROD_KEYID`/`PROD_KEYFILE`) - or
`get_kalshi_cash_balance_dollars()` returns None and the snapshot silently falls back to
`cash_source=local_fallback` (an estimate, not the real balance). The currently-running
`live_trading_engine` has only the MySQL vars in its environment, so it is in that fallback state
too. Real account cash as of 2026-09-26 23:02 UTC: **$90.26**, `cash_source=kalshi_api`.

Both metrics endpoints now surface failures instead of swallowing them: `setFetchError()` paints a
banner at the top of the tab naming the endpoint and status, and distinguishes the legitimate 403
live-password gate from a real server error. A blank tab reading as "no data yet" is exactly what
hid this 500.

## Dashboard access control (closed 2026-09-26)

The whole dashboard was world-readable: `DASHBOARD_PASSWORD` was unset and `_authorized()` returns
True when it is unset, and the EC2 security group exposed port 8080 to `0.0.0.0/0`, so both the
CloudFront URL and the raw origin `http://54.156.90.14:8080` answered 200 to anyone. Now:

- **Basic auth on every route.** `_authorized()` is the first statement of both `do_GET` and
  `do_POST`, so one password covers pages, `/sim_metrics`, `/live_metrics`, `/health`, `/table`,
  `/api/table` and every POST. A 24-char random password now lives in `/opt/kalshi/.env.dashboard`
  (root:root, `chmod 600`) and the systemd `ExecStart` sources it alongside `.env.aws`. It is
  deliberately NOT in the unit file, which is world-readable in `/etc`, and not in this repo.
  To rotate: edit that file and `systemctl restart kalshi-dashboard`.
- **Origin no longer public.** Port 8080 ingress is now AWS's managed CloudFront prefix list
  (`pl-3b927c52`, `com.amazonaws.global.cloudfront.origin-facing`) plus the owner's `73.186.198.44/32`;
  the `0.0.0.0/0` rule is revoked. Normal traffic is HTTPS via CloudFront, so Basic credentials no
  longer cross plain HTTP in the open. CloudFront already forwards the `Authorization` header.
- Verified: unauthenticated `-> 401`, wrong password `-> 401`, wrong user `-> 401`, correct `-> 200`;
  the separate live-execution gate still returns 403 without `live_password`, so live controls keep
  their second factor.

**Consequence:** `client_api/client.py` defaults to `password="kalshimakesmepoor"` and now gets 401.
Pass the new dashboard password (or better, read it from an env var) when using that client.

## Live strategy settings were not in force (fixed 2026-09-26)

The Live Trading tab's per-strategy settings form was writing to rows nothing read. Three causes,
all in the deployment rather than the code:

1. **The running engine was the pre-multi-strategy build.** PID 2099628 started `Sun Sep 13
   05:11:53`; the new `live_trading_engine.py` landed at `06:16:20` - an hour later. Python had the
   old module in memory, and the outer `while True` retry wrapper re-enters `run_loop()` without
   re-importing, so the file update never took effect. Tell-tale: it logged
   `live trading engine started (RF-only).` where current code logs `(multi-strategy: ...)`.
2. **The old build read a different row.** `load_settings(cur)` there was
   `SELECT ... WHERE settings_key='live_config'` - one global row, last updated 2026-03-07 - while
   the UI writes per-model rows. So the UI showed `edge_threshold 0.15` for `binary_theory_edge`
   while the engine was using `0.01` from `live_config`, plus `max_trade_cost 8.0` vs the UI's 2.0.
3. **The old build hardcoded `model_name="random_forest"`**, so the other two strategies were not
   live-traded at all and their cards controlled nothing.

Restarted the engine (with **both** env files, same lesson as the 20s updater). It now logs
`multi-strategy: random_forest, random_forest_high_conviction, binary_theory_edge`, ticks all three,
and `migrate_legacy_settings()` dropped the stale `live_config` row. All `live_enabled` remain
`false` - nothing trades. Confirmed in force on the first tick: `binary_theory_edge` prob 0.847,
edge 0.097 against its `edge_threshold` 0.15 -> `signal=False`.

Settings wiring in current code, verified end to end - every field on the form is consumed, and
`cfg = load_settings(cur, model_name)` sits inside the per-tick per-model loop, so saves take
effect on the next tick with no restart:

| field | consumed at |
|---|---|
| `signal_threshold` | `live_trading_engine.py:414` (signal) |
| `edge_threshold` | `:414` signal, `:217` sizing gate, `should_close_position` |
| `max_trade_cost` | `:219` `compute_buy_qty` |
| `max_concurrent_positions` | `architecture/risk_engine.py:26` |
| `max_open_notional` | `architecture/risk_engine.py:28` |
| `max_daily_loss` | `:200` -> RED -> auto-pause |
| `max_total_drawdown` | `:202` -> RED -> auto-pause |

`LiveSettingsRiskEngine` (not `DummyRiskEngine`) is the active one: `RISK_ENGINE_MODE` is unset
anywhere in the repo or on the box, and defaults to `live_settings`.

**Standing lesson:** a file copy is not a deploy for anything long-running. After updating
`data_pipeline/*.py` on the box, restart the process that imports it, and confirm by its startup
line rather than by the file's mtime.

Live strategy cards now also show that strategy's **Sim PnL** (`sim_total_pnl`/`sim_closed_trades`/
`sim_win_rate` on each `/live_metrics` `models` entry), read from `sim_trades` with the same query
shape as the Portfolio Manager so the two panels cannot disagree.

## Dashboard redesign: Kursbuch (2026-09-26)

The dashboard was rebuilt as a replacement visual world, not a polish pass. Product truth is now
recorded in `PRODUCT.md`; the durable route strategy lives in
`.impeccable/surfaces/data-pipeline-dashboard-server-py.md` (direction contract, seed key
`abd048b8`). Visitor mode: **Operate**. Confirmed by the owner: the primary job is *watching real
money move*, the audience is *only him*, and ultrawide, laptop and phone are all first-class.

**World.** A Swiss station timetable, not a trading terminal. Grey newsprint stock (`#E9EBE5`), ink
that is never pure black (`#191B16`), hairline rules at one weight, tabular lining figures
everywhere, and **no monospace anywhere** - the terminal look was the category rut and it was also
the incumbent. One reserved signal red (`#C8102E`) that appears nowhere except "this needs you";
money direction rides a desaturated tint field behind the figure, never the reserved red. The live
surface prints on a tinted stock (`#EFE4E7`) with a red head rule, the way a timetable tints a
different service, so real money can never be mistaken for the simulator. Archivo / Archivo Narrow,
two weights. Cards are gone: every panel is a ruled table, because cards at equal weight were why
nothing told you where to look.

**Signature interaction - the as-of rule.** Every section states the age of the writer behind it.
When that writer stops, the rule under its heading breaks to dashed red, the figures strike through
and mute, and a red `STALE 13d` mark states the age. This is the direct structural answer to the
failure that opened this session: two writers dead for 13 days while the UI rendered their last
values as current. It needed new server data - `/sim_metrics` and `/live_metrics` now return a
`writers` map (`last_utc`, `age_sec`, `expect_sec`, measured against the **database** clock so a
skewed server cannot invent freshness) plus `generated_at_utc`. Staleness is declared at
`WRITER_CADENCE_SECONDS` x `STALE_CADENCE_MULTIPLE` (6).

**Other structural changes.**
- `/` now defaults to **live-trading**, not data-pipeline. Live execution is the front page because
  that is the operator's first question.
- A status line above every page states the dominant answer in words before any figure is read
  ("Live trading off / No open positions / All writers current"), red only when it needs him.
- The pipeline tab's expensive queries (`table_counts`, `forward_feed_health`, `latest_model_guard`)
  no longer run on every page load, only on the tab that shows them. The unused `sim_summary()` call
  was dropped from the request path entirely.
- Responsive: tables restack into labelled rows below 640px; plates go 2-up at 1500px and 3-up at
  2200px; the page runs to 2560px instead of 1200px so an ultrawide is not a column in a void.

**Verification.** Built code-led (no image generation in this harness). Inspected in one batched
round at ultrawide, laptop and 390px phone, plus a deliberately-aged fixture to audit the stale
path. The mechanical detector went 166 -> 4 findings; the four that remain are the detector summing
sibling micro-labels on the `.measure` and `.plates` rows, where each label is 8-27 characters, and
were a deliberate keep. Contrast was computed, not eyeballed: muted ink clears 4.5:1 on all three
grounds.

**Two traps worth remembering.**
1. The production box runs **Python 3.9**: an f-string expression cannot contain a backslash there.
   Local Python 3.14 accepts it silently. The deploy's `py_compile` step caught it before install.
2. A local harness (`scratchpad/harness.py`) serves the real handler against captured production
   JSON with auth disabled. That is how this was inspected without pointing a browser at the live
   box or triggering a basic-auth modal. Fixtures come from SSM, which truncates output at ~24KB, so
   they are subsampled and fetched in two chunks.

## Strategy dossiers + finish-review fixes (2026-09-26)

**Strategy dossiers.** Each book on the Simulation tab now links to `/?tab=strategy&name=<model>`,
a Read-mode page inside the Operate app (`.reading`, 1060px measure) that states what the strategy
actually is. Content lives in `STRATEGY_DOSSIER` / `SHARED_LABEL` / `SHARED_LIFECYCLE` in
`dashboard_server.py`, written from the engine source rather than from memory: the tradeable label
(`1 if next_minute_yes_bid > this_minute_yes_ask else 0`, from `build_supervised()`), the exact
feature subsets, the real estimator hyper-parameters, the per-strategy edge thresholds, and the
research finding behind each candidate. **If the engine changes, this dossier must change with it —
a dossier that has drifted from the engine is worse than none.**

Worth knowing, because the dossiers now say it out loud: `random_forest_high_conviction` is not a
separate model at all (it re-uses `random_forest`'s probability and only raises the entry bar to
edge > 0.17), and `binary_theory_edge` fits nothing (closed-form driftless-GBM
`P(YES) = Phi(ln(S0/K) / (sigma*sqrt(T)))`, and it holds to settlement rather than exiting on
signal decay).

**Finish review.** The shipped `impeccable-finish-reviewer` refused the first pass outright because
it was given source instead of rendered pixels — correctly. Captures now live in
`.impeccable/review/`. Of its eight material findings, seven were real and are fixed:

1. The stale strike shipped invisible — 1px in `--rule-2` over a muted glyph. Now 2px in `--ink-2`.
   Half the signature interaction was not reaching the eye.
2. **The Data Pipeline tab had no as-of rule at all**, and hardcoded captions ("last 120 minutes")
   sat in the exact slot every other tab uses for writer age — so the one surface whose job is
   "confirm the pipeline is alive" was the only one that could not go stale. `/health` now returns
   `writers` via `pipeline_writer_freshness()`, and the feed and guard sections are wired to it.
   The masthead clock on that tab is fixed too (it read `READING...` forever).
3. Drawdown axes printed raw unitless floats (`-2848.6229`). Both now pass `unit:'$'`.
4. `--neg` was invisible on the rose live stock: money read in one direction only, on the one
   surface where a loss is the fact that matters. `body.live-service` now overrides both tints.
5. The status line was capped at 104ch, so the "full-width" promise broke; the rule now spans and
   only the sentence is capped. `.measure` tracks are capped so figures spread rather than stranding.
6. **No more `window.confirm` / `window.alert` anywhere.** A browser dialog states no recovery and
   belongs to no design system. Destructive live actions now arm in place (click once to arm, again
   within 6s to fire) and every outcome reports through an in-page `.notice`.
7. On phone the strategy rows exploded into eight label/value lines with the switch at the bottom.
   The switch is now lifted directly under the name, prob/edge/signal are hidden behind the
   existing disclosure, and rows carry **leader dots** — the timetable device that ties a label to
   its figure across a gap, and one of the FORM block's own named donations.

The eighth finding — a duplicated disclosure row — was **not** a bug. It was an artifact of my own
stitched full-page capture: I screenshotted at `scrollY=840` with an 840px viewport, so the boundary
row appeared at the bottom of segment 1 and the top of segment 2. Verified in the DOM: 6 rows, 3
disclosures, stable across re-renders. Recorded here so nobody "fixes" it later.

Still open from the ceiling check, honestly: bar-length-as-duration is unbuilt, and the tint-field
wash (the one authored motion moment) is coded but never captured, so it stands unverified.

DESIGN.md is now written from the shipped build by the shipped documenter, with `.impeccable/design.json`
alongside it.

## Two live-path bugs found by the over-engineering review (fixed 2026-09-26)

Found while counting duplication, not while looking for bugs:

- **The Close button on a live position always 403'd for a URL-password session.**
  `/live_position/close` was the only live route calling `self._live_authorized()` with no `parsed`,
  and `closeLivePosition()` was the only live POST that did not append `?live_password=`. The two
  defects hid each other: closing worked only if the `live_gate` cookie happened to be set. This is
  the control that manually exits a real-money position, so it is the last one that should be
  unreliable. Both halves fixed; no bare `_live_authorized()` call remains.
- `_authorized()` compared the dashboard password with `==`. Now `secrets.compare_digest`.

## CloudFront was rejecting every POST (fixed 2026-09-26)

**No control on the dashboard had ever worked through the public URL.** The distribution
(`E3W0CV5JMD953I`) was configured `AllowedMethods: [HEAD, GET]`, so CloudFront rejected every POST
with its own 403 - "This distribution is not configured to allow the HTTP request method that was
used for this request" - before the origin ever saw it. That silently disabled: save caps, the live
on/off switch, clear-halt, resume a paused sim book, close a live position, and manual orders.

Fixed by setting `AllowedMethods` to the full seven-method set while leaving `CachedMethods` at
`[GET, HEAD]` and all TTLs at 0. The pre-change config is preserved for revert. Verified: a POST
probe with a deliberately invalid `model_name` went 403 -> 400, meaning auth now passes and the
handler is the thing rejecting it; a real no-op save of `binary_theory_edge`'s existing caps
returned `ok: true` with `live_enabled` untouched.

Related and still true: the distribution also sets `Cookies: Forward: none`, so the `live_gate`
cookie is stripped and can never authorize anything in production. Only `?live_password=` in the
query string works - which is what the front-end sends. Do not "simplify" the live gate down to the
cookie path; through CloudFront it does not exist.

**Config panel no longer disappears mid-edit.** `renderLiveStrategyCards` re-renders every 10s so
prob/edge stay live, which was wiping an open settings panel and anything half-typed in it. Open
state, edited values and the caret are now captured and restored around the re-render, and a
successful save clears the pending-edit record. Reading `selectionStart` is guarded: number inputs
do not support selection and throw.

**Strategy dossiers now carry the math and the algorithm.** Formulas are native MathML - no KaTeX,
no CDN, nothing to load, so they render on a page whose job is telling you when things are broken.
Each dossier carries its decision formula, the probability step in pseudocode, and a shared
"one tick, end to end" block in the order `process_model_tick` actually runs it. A separate block
records that **live sizing is not paper sizing**: live has no `MAX_QTY` and no cash check, so the
cost cap is the only bound and a $0.05 ask buys 40 contracts for the same $2.

Monospace is used in those pseudocode blocks, which DESIGN.md's No-Monospace rule otherwise bars.
The rule is about monospace as technical costume; pseudocode is code, where indentation carries the
structure. Scoped exception, recorded rather than silently broken.

## Push alerts for live trading (added 2026-09-26)

`data_pipeline/live_alerter.py` runs on the box under a **systemd timer**
(`kalshi-alerter.timer`, every 5 minutes) and publishes to SNS topic
`arn:aws:sns:us-east-1:568386354218:kalshi-live-alerts`. Alerts on: a strategy halting itself, a
position opening (loudly if it cost more than $20), each closed trade, a switch flipping, the day's
realised loss passing a floor, cash under $70, the balance falling back to an estimate, and any
writer going stale. Two rules keep it usable: it fires **only on change** (state in
`/opt/kalshi/.alerter_state.json`), and it sends **one heartbeat a day** so silence can be
distinguished from a dead alerter - the exact failure mode this system has already suffered twice.

Permissions are deliberately narrow: a `KalshiLiveAlertsPublish` policy granting `sns:Publish` on
that one topic, attached to `kalshi-collector-ec2-role`. The alerter never writes to a trading
table and never places an order.

Two traps found deploying it. **`crontab` does not exist on this AMI** - use a systemd timer, which
is the better fit anyway. And **`/opt/kalshi/.env.aws` sets `AWS_PROFILE`**, which is right for a
laptop and fatal on the box: boto3 then looks for a credentials file that is not there instead of
falling through to the instance role. `run_alerter.sh` unsets it after sourcing.

## Read-only monitor token (added 2026-09-26)

`MONITOR_TOKEN` in `/opt/kalshi/.env.dashboard` unlocks `GET /health`, `/live_metrics` and
`/sim_metrics` and nothing else - verified refused for pages, `/table`, and every POST including the
live switch. It exists so anything off-box that must store a credential stores the least valuable
one available, rather than `DASHBOARD_PASSWORD`.

**Cloud routines cannot monitor this system.** A scheduled Claude cloud session was built, run, and
disabled: its sandbox egress proxy refuses connections to the CloudFront host
(`connect_rejected ... organization policy`), and `user_declared_urls` is dropped by the server.
The routine is kept disabled at `trig_01RdZe7mQyrWJaXnx9JFUmZV` in case that policy ever changes.

## Kalshi retired the order endpoint (fixed 2026-09-27)

Live trading could not place a single order, and every attempt crashed the engine.
`POST /trade-api/v2/portfolio/orders` now returns **410 `deprecated_v1_order_endpoint`**. The
exception propagated out of the per-strategy loop, so the whole tick aborted and the engine
restarted - which is why `binary_theory_edge`'s own log lines for 05:24 and 05:25 are missing while
its neighbours' are present.

New endpoint is `POST /trade-api/v2/portfolio/events/orders`, and the schema is genuinely
different: no `action` or `type` field, `side` is `bid`/`ask` on the YES leg (bid = buy YES, ask =
sell a YES position), and `count`/`price` are fixed-point **strings in dollars**, not integer cents.
Verified without creating an order by probing with a deliberately invalid body: the new path
answers `400 missing_parameters: CreateOrderV2Request.SelfTradePreventionType` (so it exists and
parses), the old path answers 410. Both `api.elections.kalshi.com` and `external-api.kalshi.com`
behave identically, so no host change was needed. Same 1c-99c bounds and whole-cent rounding as
before: this changed the transport, not the prices sent.

`time_in_force` is **immediate_or_cancel**, deliberately. The engine records a position straight
after the call and never reconciles fills, so a resting order would leave it believing it holds
something it does not - which already happened once, and `live_orders` still carries a March order
stuck at `resting`. IOC either crosses now, matching what the simulator assumes, or nothing happens.
**Open gap:** a partial fill is still recorded as a full fill. Reconciliation against Kalshi's
positions endpoint is not implemented.

**Second blocker, owner action only:** a well-formed order then returns
`403 "Your location attestation for API trading is missing or expired."` Kalshi requires a
geolocation attestation for API trading. No code can fix it - verify location in the Kalshi app.

## UI: actions that silently did nothing (fixed 2026-09-27)

`arm()` compared `ARMED.btn === btn`, a **DOM node identity** check, while the strategies table
re-renders every 10s and replaces that node. The confirming click therefore landed on a fresh
button and silently re-armed. Arming is now keyed by a stable `data-arm-key` string.

A second fix here - holding the render entirely while the operator was armed, had a config panel
open, or had focus inside the table - **was wrong and has since been reverted.** See the next
section: it is what made a strategy that had just been switched on keep reading "Off".

Save confirmations now render in `#strat_notice` inside the Strategies section. They previously
appeared at the top of `live-root`, which on a tall page meant a successful save looked exactly
like nothing happening.

The alerter now tails the engine log for error lines, reporting each once. It would not have caught
this failure otherwise: a crash-loop restarts too fast to look stale and writes no trade.

## "I turned it on, then it was off again" (fixed 2026-09-27)

Reported as: click **Turn on**, the banner says the strategy is live, refresh, and it reads `OFF`
again. The same shape for **Save caps**. Nothing was actually wrong with the write - the database
had `binary_theory_edge` at `live_enabled: true`, stamped `06:36:55 UTC`, the second the button was
clicked, with the operator's caps intact. **The strategy was live the whole time; only the screen
was lying.** Two independent staleness bugs, both on the read side, stacked:

**1. The read cache outlived the write.** `/live_metrics` and `/sim_metrics` go through `_cached`
with a 25-second TTL and nothing ever invalidated it. A POST committed, returned the fresh settings
(which is why the banner was correct), and then `refreshLiveMetrics()` - fired by the button itself
a millisecond later - was served the pre-write payload. Every read for the next 25 seconds, page
reloads included, showed the old state. Fixed by clearing the whole cache after **every** POST,
from a `finally:` on `do_POST` rather than per route, so no future route can forget it:

    def do_POST(self):
        try:
            self._handle_post()
        finally:
            invalidate_metrics_cache()

Clearing all keys rather than tracking which ones a write dirtied is deliberate: the cost is one
recomputed query on the next read, and the bookkeeping version is what rots.

**2. The render guard added the same day (above) refused to redraw the table.** It held the render
whenever a config panel was open - and the reporting screenshot shows exactly that: the
`binary_theory_edge` caps drawer open, the "NOW LIVE" banner up, and the row still reading `OFF`.
Even with fresh data arriving, the row could not repaint. Saving caps left the drawer open too, so
a successful save also never showed.

The guard was solving something real (a re-render under the cursor swallowing the click), but
"never repaint" is too blunt. The table now always renders and afterwards restores the three things
a redraw would otherwise destroy: open drawers, the focused field, and a half-confirmed armed
button. `CFG_EDITED` already carried in-progress values across a repaint.

Covered by `tests/test_dashboard_cache.py`, including a wiring test that fails if `do_POST` ever
stops routing through the `finally:`.

**Still open, noted here rather than changed silently:** `LIVE_TRADING_PASSWORD` falls back to a
hardcoded default in `dashboard_server.py` when the environment variable is unset - and it is unset
on the box, so the committed default is the live gate in production.

## Position reconciliation (added 2026-09-27)

`position_mismatches()` in the alerter, which already runs every 5 minutes with a DB cursor,
Kalshi auth, SNS and a state file - so no new service. It compares `live_positions` against
`GET /portfolio/positions` and reports:

- a **short** position (loud): we only ever buy YES, so a negative position cannot be intended.
  This is the exact signature of the 2026-09-27 phantom-order damage, which ran for hours because
  nothing ever asked Kalshi what we held.
- a holding Kalshi has and our book does not, or vice versa
- a size mismatch

Settlement clears Kalshi's position a beat before the engine books it, so a mismatch is only
reported if it is **still there on the next run** five minutes later.

Deliberately compares holdings, not money: a balance check needs deposits and withdrawals tracked,
which they are not, and would be wrong the first time either happened.

## The engine believed its own orders (fixed 2026-09-27) - INCIDENT

Reported as "the P&L doesn't add up": dashboard said **+$2.20 realised, 66.7% win** while cash had
gone **$90.26 -> $74.25**. The dashboard was summing the engine's *intentions*.

**Root cause.** `DummyExecutionKernel.execute` read `resp["order"]["status"]`. The Kalshi **v2**
create-order response has no nested `order` object - it is flat:

    filled   {"fill_count": "18.00", "average_fill_price": "0.7400", "average_fee_paid": "0.0134", ...}
    unfilled {"fill_count": "0.00",  "order_id": "...", "remaining_count": "0.00"}     <- no price at all

So since the v2 migration the kernel saw `{}` for every order, defaulted `status` to `"submitted"`,
set `accepted=True`, and reported `fill_price_dollars=intent.limit_price_dollars` and
`fill_qty_contracts=intent.qty_contracts` - the request echoed back as though it were a fill.
`open_live_position` then recorded the position under the comment *"Conservative assumption for
MVP: treat accepted order as filled at limit price"*, and never checked `rep.accepted` anyway.

**Why it cost money rather than just misreporting.** Orders are immediate-or-cancel. Four of six
buys on 2026-09-27 crossed nothing and were canceled. The engine recorded them as positions. A
minute later it "closed" each one - and **a sell against a position you do not hold is not a no-op
on Kalshi, it opens a short.** Three phantom closes bought 64 NO contracts on
`KXBTC15M-26SEP270315-15` for $17.76 + $1.44 fees. That market settled YES. All 64 expired worthless.

| market | dashboard said | actually |
|---|---|---|
| `...0300-00` | -$11.34 | **+$2.23** (18 YES @0.74 settled YES) |
| `...0315-15` | +$15.36 | **-$19.41** (64 worthless NO) |

Wrong in both directions: the one genuine trade *made* $2.23 and was booked as an $11.34 loss,
because the exit price was taken from the quote rather than the fill too.

**Fix.** Three layers, each independently sufficient for the four phantom trades:
- `DummyExecutionKernel` parses `fill_count` / `average_fill_price` / `average_fee_paid` from the
  flat v2 response. `accepted = fill_count > 0`. Status is `unfilled` / `partially_filled` / `filled`.
  A fill with an unreadable price falls back to the **limit**, never to something flattering.
- `open_live_position` records nothing when `fill_qty_contracts == 0`, records the partial when
  partial, and stores the real entry price and fee. The order is still written to `live_orders`
  for the audit trail.
- `close_live_position` returns without deleting the position when the exit does not fill, carries
  the remainder forward on a partial exit, and subtracts entry+exit fees from P&L. It already
  returned early when no position row existed, so fill-based recording alone closes the naked-sell
  hole: a position that was never recorded can never be sold.

Covered by `tests/test_execution_fills.py` (verbatim captured Kalshi payloads, including the v1
shape that must **not** read as a fill) and `tests/test_live_fill_recording.py`.

**Timeline.** Fix deployed and engine restarted 07:35:11 UTC. One last naked sell fired at
07:34:15, ~55s earlier, leaving a real **-21 contract short** on `KXBTC15M-26SEP270345-45`
($4.20 exposure) that settled on its own. `live_positions` and the phantom `open` rows were
voided against Kalshi's own position list (status `void`, not deleted - the attempts stay auditable).

**Still open.** `live_trades` ids 5-9 remain historically wrong (recorded from intentions), so the
dashboard reads **+$8.50 over 7 closed trades** against a real balance of ~$69.82 from ~$90. A
one-time back-correction against Kalshi fills/settlements was scoped out and is the obvious next
step. Nothing reconciles `live_trades` against Kalshi periodically, so a fill that happens outside
the engine's own call path is still invisible to it.

## Positions that expire were never booked (fixed 2026-09-27)

The engine only ever closed a position by **selling** it. When the exit order could not fill -
no bid, which is routine in the last minutes of a 15-minute contract - the market expired
underneath the position, the row stayed `open` forever, and the loss was never booked. The
dashboard went on showing it as a live holding at a stale mark.

It happened to 27 contracts of `KXBTC15M-26SEP271315-15`: six consecutive sell orders cancelled
(17:09-17:14), market settled `no`, $8.64 gone and invisible. `reconcile_settled_positions()` now
runs at the top of every tick, before any exit is attempted, and books settled markets directly
from `/portfolio/settlements` at $1.00 or $0.00. First tick after deploy:

    live random_forest_high_conviction KXBTC15M-26SEP271315-15 SETTLED no:
      27 contracts entered at 0.3200 -> 0.00, pnl -9.46

Status stays `'closed'`, deliberately: every P&L query **and the daily-loss / drawdown caps in
`current_risk_state`** filter on `status='closed'`. A separate `'settled'` status would have hidden
settlement losses from the risk caps - the same class of bug as the one being fixed. An exit price
of exactly 1.00 or 0.00 is what marks a trade as settled rather than sold.

## Why paper and live disagreed (2026-09-27)

The simulator is not modelling execution, it is modelling **quotes**. Measured, not assumed:

| finding | evidence |
|---|---|
| Paper P&L was **gross of fees** | `pnl = (exit - entry) * qty`, no fee term. rf_high_conviction: +$469.03 gross, **$154.36 of fees**, net **+$314.67** - a third of the headline |
| `FORCE_CLOSE_NEAR_EXPIRY_PRICE = 0.99` | An empty bid ladder near expiry was marked as a **near-certain win**, in exactly the illiquid case where live gets nothing |
| Exits assume the quoted bid is always hittable, in full | Live, 6/6 exit orders on `...271315-15` were cancelled |
| The sim never holds to settlement | Live does, whenever the sell does not fill |
| Sim sizes ~10 contracts, live sized 25-33 | Live ran ~3x the position the sim validated |

Head-to-head on the same markets that day: sim averaged **+8.7c per contract** per round trip over
its last 200 `rf_high_conviction` trades; live paid **-8c**. On `...271315-15` the sim booked +$0.30
and live lost $9.46.

Two hypotheses were **disproved** by measuring, and are recorded so they are not re-litigated:
the 0.99 force-close is *not* a major P&L driver for `rf_high_conviction` (0 trades of 462 hit it;
10 of 396 for `binary_theory_edge`, worth $35.10), and fees alone do not flip either strategy
negative in the sim.

**Applied:** fees on both legs now subtracted in `close_existing_position`; `FORCE_CLOSE_NEAR_EXPIRY_PRICE`
is `0.0` (no bid means no exit - a forward-running sim cannot know the settlement outcome, so the
mark must not assume a win); all 25,442 closed sim trades rebased from gross to net.

**Not done, and it is the real gap:** the simulator still has no fill model. It assumes every order
fills at the quoted price, in full, instantly, on both legs. Until it models partial fills, unfilled
IOC orders and holding to settlement, paper P&L remains an upper bound rather than a forecast.

## Live P&L rebuilt against Kalshi (2026-09-27)

`live_trades` ids 6-9 were voided (Kalshi: canceled, zero fill - they are not trades). Id 5 was
corrected to its real fill, 18 @ **0.74** (recorded 0.82), settled YES at 1.00, pnl **+$4.08**.

Dashboard now reads **-$11.37 over 10 real trades**: random_forest -$1.82, binary_theory_edge
+$3.06, random_forest_high_conviction -$12.61.

Cash went $90.26 -> ~$56.58. The difference between that ~-$33.68 and the -$11.37 of real strategy
P&L is one-off damage from the phantom-order bug - unintended short positions that belong to no
strategy - and is not recoverable into any `live_trades` row. **Nothing reconciles `live_trades`
against Kalshi on a schedule**, so this gap can reopen silently.

All three strategies set `live_enabled=false` on 2026-09-27 pending a fill model in the simulator.

## Execution rebuilt to price from the live book (2026-09-27)

**The defect.** Every order was built from `model_features_1m` `rows[-1]` - a completed one-minute
bar, up to ~75s stale by the time the order landed at :15s. Measured live: the bar read
**0.58 / 0.59** while Kalshi's book was **0.70 / 0.71**. It failed in both directions, which is why
the symptoms looked contradictory:

- **buying** at the stale ask, under the real ask -> never crosses -> cancelled (the unfilled entries)
- **selling** at the stale bid, under the real bid -> crosses instantly and gives away the difference

Top-of-book depth is **2,000-3,000 contracts** against orders of 25-33, so liquidity was never the
constraint. Stale pricing was the whole problem.

**Kalshi has no market order.** `type: "market"` on `/portfolio/events/orders` is rejected with
`invalid price: can't convert '' to decimal` - a price is always mandatory. Crossing the book
therefore means a *marketable limit*, which makes the quote the order is built from the single most
important input.

**What was built.**

`data_pipeline/market_data.py` - `MarketFeed` / `Quote`. Top of book with an explicit age.
Websocket-first with REST as both fallback and freshness backstop, because a socket that silently
stops updating looks exactly like a calm market. Returning `None` is a valid answer: no quote means
no order. In production `ws_feed=None`, so every quote is a REST read - at a one-minute decision
cadence that is 1-4 calls/min and *always* correct, where a second in-process socket would add a
stale-socket failure mode for latency that does not yet matter. The `ws_feed` hook exists for when
tick-level triggering makes it matter.

`MarketableLimitKernel` in `architecture/execution_kernel.py`, replacing the passthrough on the
live path. Three things the old kernel did not do:
1. re-prices from the live book at submit time;
2. **re-checks the edge at the price actually available** - if the live ask has run more than
   `MAX_ENTRY_SLIPPAGE` (default 2c) past the price the signal was computed at, the entry is
   abandoned, not paid up for. Following the book must not become chasing it;
3. **escalates one tick per retry on an exit.** Deliberately asymmetric: a missed entry costs
   nothing, a missed exit is how 27 contracts were carried into settlement for -$9.46. Bounded by
   `ORDER_MAX_ATTEMPTS` so it cannot walk the book down indefinitely.

Knobs (env): `KALSHI_ENTRY_CROSS_TICKS=1`, `KALSHI_EXIT_CROSS_TICKS=2`,
`KALSHI_MAX_ENTRY_SLIPPAGE=0.02`, `KALSHI_ORDER_MAX_ATTEMPTS=3`, `KALSHI_MAX_QUOTE_AGE_SECONDS=2.0`.

The engine's split is now explicit: **features from the bar** (what the model was trained on),
**prices, edge and sizing from the book** (what you can actually trade at). The bar's bid/ask no
longer reach any decision.

**Tick-level capture.** `forward_collector` subscribed to the `ticker` channel and sampled it on
20-second marks, discarding everything between - 180 distinct timestamps an hour, and 0 of 880,745
rows ever carried depth. New table `forward_quote_ticks` now records every top-of-book change:
**20 rows in 2 minutes where the sampler gave 6**, catching real intra-minute moves
(0.61 -> 0.60 -> 0.59 -> 0.58 inside 20 seconds). This is the prerequisite for a simulator fill
model and the history cannot be reconstructed after the fact, which is why it went first.

**Still open.**
- The simulator still has no fill model: it assumes every order fills at the quoted price, in full,
  instantly, on both legs. Until it replays `forward_quote_ticks` against the real cross policy,
  paper P&L is an upper bound, not a forecast.
- Triggering on book events rather than a minute timer. Constrained by the model itself: its label
  is `bid(t+1) > ask(t)` at **one-minute spacing**, so the prediction horizon is one minute however
  often it is evaluated. Changing the trigger changes the feature distribution it was fit on and
  needs retraining plus revalidation - which needs the fill model first to measure whether it helps.
- No `orderbook_delta` subscription, so still no depth beyond touch. Not currently a constraint
  (touch depth is ~100x our order size) but required for any strategy that sizes up.

All three strategies remain `live_enabled=false`.

## One execution policy, two venues (2026-09-27)

The simulator and the live engine now run the **same** `MarketableLimitKernel`, against the same
`MarketFeed`, with the same cross ticks, the same edge tolerance and the same retry behaviour.
Only the submitter differs:

    live:  MarketableLimitKernel(place_limit_order,    feed)
    sim:   MarketableLimitKernel(SimulatedVenue(feed), feed)

The policy knobs are read from the **same environment variables** in both engines
(`KALSHI_ENTRY_CROSS_TICKS`, `KALSHI_EXIT_CROSS_TICKS`, `KALSHI_MAX_ENTRY_SLIPPAGE`,
`KALSHI_ORDER_MAX_ATTEMPTS`), so a paper book cannot silently be run under a policy the live
account is not. That was the structural reason the two disagreed.

**`architecture/simulated_venue.py`** returns Kalshi's flat v2 response shape, so one fill parser
reads both venues and they cannot drift. It models crossing the touch, partial fills against the
size resting at the touch, Kalshi's taker fee, and orders that simply do not fill. It does not
model queue position (every order here is a taker) or depth past the touch (the ticker channel
does not carry it, and touch depth is ~100x our order size).

**What the simulator can now do that it could not before**, each of which happened live on
2026-09-27 and was invisible in paper:
- **miss an entry** - an order that does not fill is not a position
- **fail an exit** - an unfilled sell leaves the position exactly where it was
- **be carried into settlement** - `reconcile_settled_sim_positions()` books expired contracts at
  $1.00/$0.00 from the *public* market result, since the simulator has no account to query
- **abandon a trade whose edge has gone** - if the live ask has run past the signal price

The sim also now scores its edge against the **live book** rather than the bar's ask, matching the
live engine's features-from-the-bar / prices-from-the-book split.

Startup line, for confirming the two match: `sim execution: marketable limit, entry_cross=1
exit_cross=2 max_slippage=0.02 attempts=3`.

**Remaining gap.** This is forward paper trading with a realistic fill model, not a backtest.
`forward_quote_ticks` only began recording on 2026-09-27, so there is no tick history to replay
older signals against; a historical backtest would still have to use 20-second `forward_quotes`
samples and would inherit their optimism. Judge the strategies on paper results recorded from
tonight onward, not on the pre-existing 25,442 trades - those were produced by the old
fill-everything model and are an upper bound.

## Risk management (added 2026-09-12)

- `sim_config.SimRiskSettings` (stored in the `sim_settings` table, key `risk_config`): `max_position_fraction` (cap new-position notional as a fraction of a model's own current equity, default 0.20), `max_drawdown_pct` (pause a model once its drawdown from peak exceeds this, default 0.30), `min_equity_floor` (hard floor, default $10).
- Drawdown is computed from `sim_equity_1m`'s own realized-PnL history (peak vs current), not the separate `sim_portfolio_20s` table - that keeps the gate working identically whether ticking live or replaying via `recompute_sim_metrics.py`.
- A paused model stays paused until explicitly cleared via `POST /sim_risk/resume {"model_name": ...}` - no silent auto-resume. Pause state is visible in `/health`'s `sim_summary.models[].paused`/`paused_reason`.
- Near-expiry (`time_to_expiry_sec <= 60`): blocks new entries and force-closes any open position at $0.99 (matches the README's long-standing claim, which the code never actually implemented until now).

## Strategy research findings (2026-09-12)

Built `research/` (successor to the deleted `work/` dir): `expiry_resolution.py` is the reusable
backtesting harness (chronological 60/20/20 split snapped to ticker boundaries so no contract
straddles a split - the original methodology's plain row-index split didn't guarantee this),
`expiry_resolution_sensitivity.py` and `fee_sensitivity.py` are diagnostic follow-ups.

Investigated: revisiting the expiry-resolution label (terminal YES/NO instead of next-minute
direction) that looked promising in the deleted `work/` research - but that result was on only
5 days of data (9 test trades). With the current ~6 months (62,755 eligible rows):

- Reproducing the original take-profit-scalp exit rule on the larger sample: all 3 models
  (logistic/RF/HGB) are **negative** on held-out test (663 and 404 trades respectively for
  logistic/RF, both net losers despite ~77-82% win rates) - the original 9-trade result was noise.
- Diagnosis: high AUC (~0.87) but negative PnL despite high win rate means the *signal* has real
  information but the *exit rule* (fixed $0.05 take-profit, uncapped downside otherwise) fights it.
- Switching to hold-to-settlement exits (monetizing the resolution prediction directly): the
  logistic model showed a broad, robust-looking positive-PnL plateau across both validation and
  test threshold grids (not a lucky single point) - genuinely the most interesting finding.
- **But it does not survive transaction costs.** Gross test PnL was +$0.87 over 442 trades
  (+$0.002/trade). Even a 1% fee rate (well below Kalshi's actual schedule, which scales with
  `price*(1-price)` - highest exactly where these trades enter) flips it to **-$0.30 net**; at
  ~7% it's -$7.32. RF/HGB didn't replicate the effect under the same exit style either, which is
  a further reason not to trust it even before the fee check.

**Verdict: no candidate from this thread clears the bar.** This was a real, rigorous negative
result, not a lack of effort - see `research/` for the full methodology if revisiting this later.

### Follow-up checks on the existing production models (2026-09-12)

Two cheap retrospective checks on the ~24k real historical closed trades already in `sim_trades`,
before building anything new:

- `research/volatility_regime_check.py`: bucketed each model's trade PnL by `cb_vol_5m` quintile
  at entry. **Ruled out** - losses are roughly uniform across all 5 volatility regimes for all 3
  models; this isn't a "the models only fail in choppy/calm markets" problem.
- `research/pnl_distribution_check.py`: `random_forest` has win_rate > 50% in every volatility
  quintile yet still loses money in every one - looked like a fat-tail/stop-loss-fixable problem.
  **Ruled out on inspection**: loss/win ratio is only 1.16x (avg loss $1.78 vs avg win $1.53), and
  the worst 1% of trades account for only 6.2% of total losses (worst 10% account for 43.2% - a
  smooth distribution, not outlier-driven). `random_forest` is running almost exactly at its
  breakeven win rate (~53.7% needed given the 1.16x loss/win ratio; achieving ~52-53%) - a small,
  structurally persistent negative edge after spread costs, not a few bad trades a stop-loss would
  catch. This model needs a genuinely more accurate signal to cross breakeven, not better risk
  management.

### Fourth check: edge magnitude (2026-09-12) - the one live candidate

`research/edge_magnitude_check.py`: bucketed each model's historical trades by edge magnitude
(`prob_yes - ask`) at entry. For `random_forest` specifically, PnL rose monotonically with edge -
the top quintile (edge > ~0.167) was the only clearly profitable bucket (+$89.40/1449 trades,
+$0.062/trade avg), with a positive edge-PnL correlation. `logistic`/`naive_logistic_baseline`
showed no such pattern (if anything the opposite).

**Caveat found via `research/edge_magnitude_time_split_check.py`**: all 1449 of those trades fall
between 2026-03-07 and 2026-04-27 - the entire window before the connection-drop incident froze
the engine for ~5 months. There is zero out-of-sample evidence since, and the effect visibly
decayed within that window (March avg +$0.125/trade -> April avg +$0.006/trade). Not enough to
call this validated from backtesting alone.

**Decision**: rather than mine the same limited historical window further, added
`random_forest_high_conviction` as a new sim-only model (`simulated_trading_engine.py`,
`ALL_MODELS`) - reuses `random_forest`'s exact probability output unchanged, just requires
`edge > HIGH_CONVICTION_EDGE_THRESHOLD` (0.17, in `sim_config.py`) instead of the base 0.01. Runs
its own independent $100 book, subject to the same risk gate as every other model. This tests the
hypothesis forward on genuinely new data instead of re-analyzing the same 7-8 weeks. Deployed and
verified live 2026-09-12 (fresh $100 equity, not paused, correctly reusing random_forest's prob).
**Check back on this model's real forward performance before drawing any conclusion from it.**

### Fifth/sixth checks: open_interest and two-sided quotes (2026-09-12)

`research/two_sided_quote_check.py`: `open_interest_fp` was already flowing through
`model_features_1m_builder.py` (queried, never used) - tested it as an added feature via
time-series-CV logistic regression. **Negligible**: AUC delta +0.0010, not worth pipeline changes
on its own.

Also tested the NO-side quotes (`no_bid_dollars`/`no_ask_dollars`) as a potential
mispricing/liquidity signal (`(yes_ask+no_ask)-1.0` gap, etc.) - found these were only present in
0.67% of historical rows (403/60,000), too sparse to test. Root cause: `forward_collector.py`
stored the partial WebSocket ticker message as `raw_json` whenever available, which doesn't carry
the NO side, discarding the fuller REST market object that does. **Fixed** (not just diagnosed):
added `no_bid_dollars`/`no_ask_dollars` as explicit `forward_quotes` columns, populated via the
same `_pick_value(ws_msg, m, ...)` fallback already used for `open_interest_fp` - the REST market
object is fetched every 20s regardless of WS availability, so this gives near-100% coverage going
forward. Deployed and verified: fresh rows now show consistent two-sided quotes
(e.g. yes_bid=0.33/yes_ask=0.34, no_bid=0.66/no_ask=0.67 - correctly complementary, no gap in this
sample). **Needs days/weeks to accumulate enough volume for a real test** - this is infrastructure
for future research, not a finding yet.

### Seventh check: fine-grained realized volatility (2026-09-12)

`cb_vol_5m` (the only volatility feature) is computed from just 5 once-per-minute Coinbase price
samples, despite `coinbase_ticks` already being collected every 20 seconds (~74 samples available
in the same window) - a concrete "smart use of existing data" candidate needing zero new
collection. Tested two proper realized-volatility estimators from the quant-finance literature
(not ML - this was a deliberate move away from defaulting to logistic/RF for everything):
realized volatility (`RV = sqrt(sum(r_i^2))`, the standard high-frequency estimator) and an
EWMA-weighted variant. **Clean negative**: both correlate 0.86 with the existing coarse estimate
(same underlying signal, just smoothed differently) and AUC deltas were all ~0.0001-0.0002 -
noise. 20-second-level data isn't the bottleneck for this particular feature; the coarse version
was already adequate. See `research/fine_grained_volatility_check.py`.

### Eighth check: binary-option theory - a non-ML approach (2026-09-12)

Per explicit feedback that logistic/RF was too narrow a toolkit: derived a closed-form fair
probability from options theory instead of fitting anything. Model: BTC follows a driftless GBM
over the contract's remaining life; for a binary paying $1 if `S_T >= K`,
`P(YES) = Phi(ln(S_0/K) / (sigma*sqrt(T)))` - the Black-Scholes d2 term without the risk-neutral
drift correction, since this is a physical-measure probability question, not derivative pricing.
sigma comes from the existing `cb_vol_5m` scaled to the contract's own time-to-expiry. Zero
fitting, zero training data needed - see `data_pipeline/binary_theory.py` (production) and
`research/binary_option_theory_check.py` (validation, same formula, kept in sync intentionally).

**Result: matched ML-level standalone predictive power (AUC 0.858) with no fitting at all.**
Calibration showed a clear, systematic overconfidence bias (predicts 0.87 where only 0.775 of
that decile actually resolves YES, etc.) - consistent with a constant-volatility GBM
underestimating BTC's true tail risk. Filtered to only its largest mispricings (edge > 0.15,
`research/binary_theory_robustness_check.py`): 451 trades spanning the *entire* available window
(not just pre-incident, though that window is still only ~7-8 weeks + a few hours of fresh data -
same `model_features_1m_builder` outage gap noted above affects this dataset too), improving
rather than decaying (Mar avg +$0.0034/trade -> Apr avg +$0.0150/trade), and survived up to ~3%
simulated fees (vs. 1% for the earlier `random_forest` candidate) before turning negative.

**Decision**: this is the strongest candidate found this session by a meaningful margin - matches
an independent ML-based finding (large mispricings being where the edge lives) via a completely
different, non-fitted methodology, which raises confidence it's a real market feature rather than
one model's artifact. Deployed `binary_theory_edge` as a new sim-only model (own $100 book, same
risk gate, `HOLD_TO_SETTLEMENT_MODELS` exit style - never closes early on signal decay, only via
near-expiry force-close-at-$0.99 or ticker rotation, since the backtest's "hold to true settlement
price" isn't available live without lookahead). Deployed and verified live 2026-09-12: computing
a distinct probability every tick (confirmed different from the ML models'), fresh $100 equity,
not paused. **Still needs real forward time before treating this as validated** - same discipline
as `random_forest_high_conviction`.

### Ninth check: Kalshi's real tick size, fee formula, and a production incident (2026-09-12/13)

**Tick size correction.** Assumed (and the README documented) a flat $0.01 tick with a
force-close-at-$0.99 near-expiry floor. User feedback + our own `forward_quotes` history
disproved this: real quotes on `KXBTC15M-*` go down to $0.001 increments, observed across the
*entire* price range (not just near 0/1 - e.g. `0.042/0.049`, `0.977/0.979` bid/ask pairs from
2026-09-13, and non-whole-cent rows going back to 2026-03-17, ~648k of them). The near-expiry
force-close logic in both `simulated_trading_engine.py`/`sim_repository.py` and
`live_trading_engine.py` was hardcoding the exit at exactly $0.99 *even when a real bid was
available*, discarding real quotes as good as $0.999 on a winner and, more seriously, forcing a
flat $0.99 floor on a position that might legitimately be losing near expiry (this matters most
for `binary_theory_edge`, the one hold-to-settlement model that can actually reach near-expiry
while losing). Fixed: both now try the real current bid first via `best_bid_snapshot` and only
fall back to the $0.99 floor when no quote exists at all (empty ladder - the original, narrower
intent of that fallback). See `data_pipeline/sim_repository.py::close_existing_position` and
`data_pipeline/live_trading_engine.py`'s near-expiry branch.

**Fee formula correction.** The new Portfolio Manager "recommendation status" label
(`get_model_recommendation_status` in `sim_repository.py`) initially used a flat assumed 3% fee
rate. Corrected to Kalshi's actual published formula (taker: `ceil_cent(0.07*C*P*(1-P))`, maker:
`ceil_cent(0.0175*C*P*(1-P))`, source: kalshi-fee-schedule.pdf) in the new
`data_pipeline/kalshi_fees.py`, using `Decimal` (not float) for the cent-rounding so it doesn't
misround Kalshi's own documented $1.75-per-100-contracts peak example. The sim engine crosses the
book on both entry and exit (buys at ask, sells at bid), so both legs are fee'd at the taker rate.

**Also found while wiring the recommendation feature into the dashboard**: `get_model_recommendation_status`
was imported by `dashboard_server.py` but had gone missing from `sim_repository.py` (lost in an
earlier fork-merge conflict resolution this session) - the dashboard was crash-looping on every
deploy attempt with an `ImportError` until this was caught and re-added. Lesson: `py_compile`
does not catch a missing import target; added a quick AST-based cross-file import check as a
pre-deploy sanity step (not a saved script, just something to re-run before future deploys).

**Production incident: RDS `max_connections` exhaustion (2026-09-13, ~05:00-05:25 UTC).**
While redeploying the above, the dashboard and both trading engines were restarted, which surfaced
a real, unrelated bug: `sim_portfolio_20s_updater.py`/`live_portfolio_20s_updater.py` run
`SELECT MAX(peak_equity_dollars) FROM sim_portfolio_20s WHERE model_name=...` every ~20 seconds,
forever, against an append-only table that's now ~6 months deep - no index on
`peak_equity_dollars`, so this became a slow full scan per model per tick. Once one tick got
slow, the next tick's query queued up behind it (and the one after that), each opening its own
connection, on a small RDS instance with `max_connections=60` - a classic thundering-herd pileup
that eventually exhausted every connection slot and broke `/health` and other reads with `(1040,
'Too many connections')`. Fixed at the root: added covering indexes
(`idx_sim_portfolio_model_peak (model_name, peak_equity_dollars)` on `sim_portfolio_20s`,
`idx_live_portfolio_peak (peak_equity_dollars)` on `live_portfolio_20s`) so the `MAX()` is answered
via a loose index scan instead of a full scan - see the migration block in `init_schema.py`.
Immediate mitigation while the index built: killed the stuck queries via `KILL <id>` and briefly
stopped both `*_portfolio_20s_updater` processes so they'd stop adding to the pileup, then
restarted them once the index was in place. No trading logic or sim/live positions were affected -
this only touched the 20-second equity-snapshot cache tables, not `sim_trades`/`sim_positions`.
**Follow-up worth doing eventually**: this class of "unbounded re-scan of an ever-growing
append-only table" is a pattern, not a one-off - worth auditing `dashboard_server.py`'s other
aggregation queries (`table_counts()`, `sim_metrics()`) for the same shape before the next
multi-month milestone.

## Action Plan

1. **Monitor the two live, unvalidated strategy candidates** - give both real time to accumulate
   trades before judging either; a handful of trades proves nothing:
   - `random_forest_high_conviction` (edge > 0.17 filter on the existing random_forest signal)
   - `binary_theory_edge` (closed-form GBM probability, edge > 0.15, hold-to-settlement exit)
   Check `/health`'s `sim_summary`, the dashboard's Portfolio Manager panel, or query
   `sim_trades WHERE model_name IN (...)`.
2. **Let the no-side-quote data accumulate**, then test the two-sided-quote-gap hypothesis properly
   once there's a real sample (see `research/two_sided_quote_check.py` - already handles the
   `require_no_side` case, just needs enough post-2026-09-12 rows).
3. **Further strategy research**: eight hypotheses tested this session - six cleanly ruled out
   (expiry-resolution label, volatility-regime conditioning, stop-loss/tail-risk, open_interest,
   fine-grained realized volatility) and two deployed forward (above). Untested if continuing:
   calibration-weighted ensembling of the 3 base ML models (lower confidence - they share similar
   structural issues), GARCH-style conditional volatility (likely redundant given RV/EWMA already
   correlate 0.86 with the coarse estimate), or a genuinely different feature/label/asset-class
   angle. Not ML-only - traditional stats and closed-form finance are proving at least as useful
   here (see the binary-option-theory result above).
4. **Live trading remains off** (`live_enabled=False`) until a strategy demonstrates a real,
   validated, fee-adjusted edge over a statistically meaningful forward sample - not before.
5. **Ongoing monitoring**: report back on sim portfolio health regularly (equity, drawdown, any
   pause events, new-candidate progress) rather than letting it run silently unwatched - that
   silence is exactly what let the April 27 incident go unnoticed for months.
6. **UI**: Portfolio Manager panel shipped (equity/PnL/pause-status per model + a resume button,
   `/sim_risk/resume`) and verified visually in-browser. Still open: manual trigger buttons for
   recompute/model-guard-refresh/re-run-research, further visual cleanup of the older panels.

## Open Items / Follow-ups

- `live_trading_engine.py` and `live_portfolio_20s_updater.py` got the same reconnect fix as their sim counterparts (explicitly approved) - this only affects DB reconnection behavior, no change to trading/risk logic.
- The leaked `client_api` password (`kalshimakesmepoor`, hardcoded in `client_api/client.py` and `client_api/README.md`) was intentionally left as-is per explicit instruction - not rotated.
- `venv/` was untracked from git (was previously committed - 7500+ files); `.gitignore` updated. Files remain on disk, only git tracking changed.

## Sim-vs-real equity curve (Kalshi dev replay)

- `app/kalshi_dev.py`: READ-ONLY replay of a strategy's out-of-sample window against the
  Kalshi DEMO environment (`KALSHI_DEV_API_BASE`, e.g. `https://demo-api.kalshi.co/trade-api/v2`).
  Pulls public per-contract candlesticks (unauthenticated GET), rebuilds the OOS snapshots off the
  real demo order-book bid/ask while reusing the real BTC spot features, then re-scores with the
  backtester's own `simulate`/`metrics`/fee model so the realized curve is directly comparable to
  the simulated one. Never authenticates, never POSTs, never places an order.
- Endpoint `GET /api/strategies/{id}/dev-curve` (`strategy_dev_curve`) returns `{dev_curve, dev_metrics,
  contracts, capped}`; degrades to `{dev_curve: null, reason}` when demo isn't configured/reachable.
  Cached per strategy id (10 min). Capped to the first `KALSHI_DEV_MAX_CONTRACTS` (default 60) OOS
  contracts to bound API calls (ceiling noted in-file; raise/parallelise/persist for the full window).
- `app/static/app.js`: `equityChart` takes an optional `devCurve` (dashed accent line + legend); the
  strategy detail view fetches the dev-curve after load and redraws the chart with both lines.

## Tau-RSI: self-evolving research (Dream-RSI adapted) — DESIGN (2026-10-15)
Paper: Dream-RSI (arXiv 2609.14858, Google/UMD) — github.com/zhengkid/Dream-RSI.
Owner chose: per-user private memory; FULL Dream-RSI (replay simulator + dreaming);
paper-faithful **evolvable executable policy code**; retrieval + self-edited policy.

**Core safety invariant:** the exploration policy is a PURE decision function
`next_batch(tree, round) -> Batch | STOP` and `should_stop(tree, round)`. It reads the
discovery tree and returns allocation decisions only; it NEVER touches LLM/backtest/DB/
network — the harness performs all I/O. So per-user LLM-written policy CODE is sandboxable:
side-effect-free, run with no network/filesystem, import whitelist (math/statistics), AST
validation (no dunder/imports), CPU+mem+time limits, and a default-policy fallback on any
error/timeout.

**Mapping to our pipeline:** discovery agent = hypothesis proposer (LLM) + backtester
(evaluator); node = one tested hypothesis + its in-sample/OOS/gate outcome (already stored in
app_strategies); exploration policy = today's hardcoded BATCH=4/FINALISTS 3-8/stopping (to be
made evolvable); replay simulator = re-traverse the stored per-user tree with objective
`V = best_score - b1*generations + b2*parallelism` (no new LLM/backtest); dreaming = a
policy-development LLM revises the policy code, each validated over historical trees via replay,
best (>= current) deployed. NOTE our backtests are cheap, so the replay trick's payoff is
smaller than the paper's expensive-kernel setting; the dominant cost here is proposal tokens.

**Phases:** P1 foundation (ExplorationPolicy pure-fn interface + DefaultPolicy extracted from
current logic; discovery-tree schema: parent_id + per-user linkage; no behavior change) ->
P2 replay simulator + objective (read-only, tested) -> P3 sandbox (restricted subprocess +
AST validation + resource limits + loader/fallback) -> P4 dreaming loop (policy-dev agent +
per-user policy storage + deploy-best; billed as research).

## Tau-RSI: fixing "0 policies evolved" — GENERALIZATION OBJECTIVE (2026-10-15)
**Symptom:** 0 policies evolved across 6 users / 3 runs despite apparent headroom.

**Root-cause diagnosis (evidence from real trees users 7/1/2, market btc15m, pulled via SSM):**
1. **The old objective rewarded OVERFITTING the recorded node order, not better research.**
   A single fixed-order replay with a `-b1*generations` term made "stop early" look great
   *only when that recording's winner happened to appear early* — which does not recur next run.
   Proof: a stop-just-after-the-winner policy beats the default on the fixed order for every
   user (user 2: V 194.2->224.6) but **collapses** when V is averaged over shuffled orders
   (user 2: mean 194.2 -> -40.8; user 7 winner is actually at idx **462/500**, so stopping early
   there throws the winner away). The paper's premise ("winner appears early") is empirically
   false on our trees.
2. **The policy's only real lever is finalist SELECTION, not batch width / stopping.** With OOS
   P&L in the hundreds–thousands and b1=0.1, reaching the winner dwarfs any compute saving, so
   the generalization-optimal `next_batch` is just "reveal the budget" — stopping is a dead lever.
   The live winner for user 1 was a *selection* fix: the default ranks by in-sample score and
   tests the top ~8, which **MISSES** user 1's real OOS winner (+$282, idx 15) and instead gates
   money-losers (default mean V = **-71**). Testing every profitable/sturdy candidate catches it
   (mean V **+232**), order-invariant.
3. **The old objective had no multiple-testing penalty and an ungrounded parallelism bonus.**
   "Select everything" maximized best_quality for free (manufacturing false edges — the exact
   thing research_brief.md warns against); the `+b2*parallelism` term rewarded wide batches whose
   effect the replay cannot even measure (recorded outcomes don't depend on batch size) = a free
   gaming vector.
4. **Why the LLM found nothing:** the prompt exposed only {proposed,budget,round} and told the LLM
   stopping/batching was the lever, so it kept proposing early-stops that backfire on real trees,
   while the one reliable win (looser selection) was explicitly discouraged ("keep it small").
   Real Sonnet-4.5 run (old prompt): user 7 = 0/3 beat base, user 1 = 1/3 (and that one games the
   missing penalty). Non-deterministic + N_CANDIDATES=3 = ~0 adoptions.

**Fix (minimal, preserves pure-function + sandbox invariants):**
- `replay.replay_generalization(policy, tree, budget)` = **mean V over 32 orderings** (recorded +
  seeded shuffles). This is what `dreaming` scores base and candidates on. Order-overfitting is
  now self-defeating; the default (reveals all -> order-invariant) is the robust baseline.
- New objective `V = best_quality - 0.1*generations - 0.1*finalists`: dropped the parallelism
  bonus (ungrounded/gameable), added a **multiple-testing penalty** per gated finalist (grounds
  the brief's "best of fifty is weak evidence"), so selection is a real precision/recall tradeoff
  and "select all" can't game it.
- `next_batch` now sees only {proposed,budget,round} in replay too (was fed `history` the live
  harness never provides) — removed train/serve skew; dropped the vestigial `PolicyState.history`.
- `DREAM_SYSTEM`/prompt rewritten: tells the LLM it's scored on the AVERAGE over reshuffled orders
  (stopping early can't help), names **selection** as the lever (catch the OOS winner with as FEW
  finalists as possible), and surfaces the selection-gap signal (did the current policy catch the
  best strategy the history holds?). N_CANDIDATES 3->5.
- Guard: a candidate must actually explore+gate (`generations>0 and finalists>0`), so the new
  penalties can't make a do-nothing policy (V=0) "beat" a default that selects OOS losers (V<0).

**Signal flow (dreaming loop, after fix):**
```
recorded discovery tree (app_strategies, per user+market)
        │  build_tree()
        ▼
  ┌───────────────────────────── evolve_policy ─────────────────────────────┐
  │ current policy ──► replay_generalization (mean V over 32 shuffled orders)│  = base_v
  │                                                                          │
  │ policy-dev LLM (DREAM_SYSTEM + tree summary + selection-gap signal)      │
  │        │ N_CANDIDATES=5 pure-Python policies                            │
  │        ▼                                                                 │
  │   sandbox.load_policy (AST gate + restricted builtins + timeout)         │
  │        │ for each safe candidate                                         │
  │        ▼                                                                 │
  │   explore+gate guard ──► replay_generalization  ─► v                     │
  │                                                                          │
  │   keep best v (> base_v + eps)   ── monotonic: current always competes   │
  └──────────────────────────────────────────────────────────────────────────┘
        │  set_policy() only if a candidate genuinely generalizes
        ▼
  next run uses the evolved policy (agent.run_research -> current_policy)
```

**Before/after (real trees; default -> best adopted, generalization mean V):**
| user | default V | overfit stop-early (old would chase) | evolved (selection) | outcome |
|------|-----------|--------------------------------------|---------------------|---------|
| 7 (winner idx 462) | 4092.79 | fixed 4096.4 but **gen 4035.7 (rejected)** | 4093.3 (finalists 8->3, same winner) | tiny real win; overfit refused |
| 1 (winner idx 15)  | **-71.24** (gates OOS losers) | — | **+231.92** (catches the +$282 winner) | big real win, order-invariant |
| 2 (winner idx 13)  | 193.00 | fixed 224.6 but **gen -40.8 (rejected)** | none > default | default kept (already optimal); overfit refused |

Real Sonnet-4.5 with the new prompt: user 1 = **3/5 candidates reach +231.9** (all via selection,
no early-stop attempts); user 7 = 2/5 find the small tighter-selection win; overfit rejected. The
loop now improves real research where headroom exists and honestly adopts nothing where it doesn't.

**Deliberately NOT done (ponytail):**
- *Evolving proposal/directional guidance* (the biggest lever on research quality): the replay
  simulator replays FIXED recorded proposals — it cannot score what *different* guidance would
  propose, so making guidance evolvable would be optimizing a knob the simulator can't evaluate.
  Needs a different evaluator (e.g. held-out live runs), out of scope for a replay-validated loop.
- *Throttle*: dreaming is ~1k in / ~1.3k out tokens (~$0.02) per eligible run and is monotonic
  (never harmful), so a throttle is low-value. If wanted: persist the tree size at last dream and
  skip when it hasn't grown by N new gated nodes (needs a schema column; deferred).
