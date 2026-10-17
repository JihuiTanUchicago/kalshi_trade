# MVP for launch (v0.1)

## The idea: RSI for Trading
A self-improving alpha discovery pipeline, from ideation, to similation, and finally real execution.

[Optional] Side idea: Agent generated UI for trading assistance. 


## Requirements
- **[Done]** Market: Kalshi BTC 5pm EDT — also added BTC 15-min.
- **[Done]** Data Pipeline: existing RDS DB reused (per-minute all-markets collector still TODO).
- TODO: Polymarket data collection + API + real & simulation trading pipeline (second venue).
- **[Done]** Google login + dashboard (cash balance, portfolio, ROI, open positions).
- **[Done]** Research hub: dispatch agents, live count of running/queued research.
- **[Done]** Strategies tab: all strategies, filter by Passed/Void/Rejected + market.
    - **[Done]** Each strategy shows in-sample vs out-of-sample (unseen) performance.
- **[Done]** Strategy thesis shown on each strategy (dossier).
- **[Done]** Deploy tab: pick strategies, monitor live; agent chat on the side.
    - **[Done]** Autopilot (dangerously-skip-permission) adjusts/deploys on paper, thoughts in chat.
- **[Done]** Funds tab to deposit/withdraw (paper now; live via user's own Kalshi key).
- Need company domain and emails for startup credits offer
- API/CLI usage of Tau

## TODO / Working Queue
Single source of truth for OPEN work — one flat list. Each item is tagged with what it's waiting on:
- `[built · awaiting integrate+deploy]` More robust, fast, intelligent execution service — `MarketableLimitKernel` gained four opt-in, fail-safe thin-book controls (participation / max-book-fraction cap, entry spread guard, per-order notional backstop, exit partial-fill continuation), each strictly-stricter and none able to block an exit; wired to env knobs (default OFF), covered by `tests/test_execution_thin_book.py`, documented in `kalshi_trade_infra/EXECUTION_DESIGN.md`. Live gate untouched. Recommend enabling `KALSHI_MAX_BOOK_FRACTION≈0.25` + `KALSHI_MAX_ENTRY_SPREAD≈0.05` on thin sports/crypto venues after deploy. **Next:** parent integrates + deploys, then measure.
`[delayed]` = owner chose to hold; `[blocked: …]` = needs a user/AWS action first; `[v0.3]` = next version.
These are NOT done. Completed items move to **## Done** below.
- `[blocked: worker environment]` Activate Alpaca stock/ETF agent data after secure worker configuration and entitlement checks, with a production canary before customer rollout. Source integration is complete for review; no production deployment yet. [Setup](kalshi_trade_infra/app/README.md#alpaca-stocketf-data-for-agents--october-16-2026).

- `[delayed]` All-markets collector + cross-contract. Phase 1 catalog shipped; ingestion split onto a dedicated collector box + S3 data-lake. Next: per-minute S3/Parquet snapshots (Phase 2). Backtest-over-any-series (3) + cross-contract research/eval (4) now built (see Done); cross-contract **live execution** still deferred.
- `[v0.3]` Wire the generator (agent.py) to PROPOSE cross-contract pairs + build merged validation/holdout partitions, then enable cross-contract LIVE execution (engine.py/live gate) — research + evaluation are in place; this is the remaining step.
- `[delayed]` Widen the live market universe — surface more of the already-collected Kalshi series in the UI (smaller than the full all-markets build).
- `[blocked: SES]` Email-all community digest — **code is live** (opt-out + HMAC unsubscribe + 4h per-recipient cooldown; background-thread dispatch on each new post), but SES is in sandbox so it only reaches *verified* addresses. Unblock: SES console → Account dashboard → Request production access (zero code change after).
- `[blocked: AWS]` Premium model access — Claude 5.5 / OpenAI GPT-6.x / Grok are AWS account-gated (agreements accepted, but invoke denies even from full-admin). Unblock: Bedrock console → Model access (us-east-1), or AWS Sales. Prices locked: Sonnet5.5 $2/$10, Opus5.5 $4/$20, Haiku5.5 $0.1/$0.5, GPT-6.1 Sol $2.2/$10, GPT-6 Sol $2/$10, GPT-5.6 Sol $8.8/$33.
- Kalshi-dev 2nd equity line — NOT blocked: uses the *public* demo candlesticks (no credentials), base URL now defaulted in code; draws once the slippage/dev-curve work deploys (verify after deploy). Covered by the slippage Done entry below.
- `[v0.3]` Agent internet access / web search (Google/Tavily/Brave).
- `[v0.3]` Polymarket as a 2nd venue: data + API + real & simulation trading.
- `[built · gated — awaiting demo validation]` NO-side (and side="either") LIVE execution — execution places the correct leg (buy NO = sell-YES ask at 1−no_price, priced from the NO book, filled/settled in NO terms); every other live gate kept, in order. Live NO is gated behind `APP_NO_SIDE_LIVE_ENABLED` (default OFF) until the mechanics are validated on the real demo sandbox; demo/paper NO work now. **Next:** place a demo NO order, confirm correct side/fill, then flip the flag.

### From beta-tester feedback (2026-10-16) — user-first, deliver these greatly
- `[blocked: taostats key]` **Bittensor (TAO) subnet tokens** — Phase-1 research venue BUILT + deployed (new `spot` instrument kind, `simulate_spot` + pool-depth fills, spot placebo, `tao_subnet_features` + repository, taostats v1 collector inert without key; stores USD/TAO + TAO/alpha, USD-denominated returns). Research-only, `deployable=False` (no order API — on-chain AMM is Phase 2, blocked). **Unblock:** user sets `TAOSTATS_API_KEY` (SSM) + confirms OHLC granularity + netuids; then data flows + strategies run through the gatekeeper. Live trading = separate wallet subsystem, blocked.
- `[blocked: AWS]` **Onboard Opus 5.5** (`claude-opus-5-5`) + surface model comparison — tester wants it for NBA season. Blocked on AWS Bedrock model access like the other premium models.

## Done
### 2026-10-17
- **Kalshi sports (NBA) + crypto markets now tradeable** — the live engine was BTC-hardcoded (it skipped strikeless contracts and always fetched BTC spot), which is the only reason NBA/ETH/SOL/XRP were research-only. Made the live feed market-aware: a sports contract (no strike) trades on book features alone with a 0.0 sentinel; each crypto market prices off its own Coinbase product; a spot-feed hiccup skips that tick instead of crashing the loop. Flipped NBA + ETH/SOL/XRP to deployable=True (7 tradeable markets now). TAO stays research-only (no order API). No live gate weakened — every guard still applies, and paper runs on the same feed so nothing reaches live unproven. (Deployed + live.)
- **TAO subnet-token research venue (Phase 1)** — a new `spot` instrument kind for Bittensor alpha tokens: continuous-price long/flat backtester (`simulate_spot`) with a pool-depth fill model, a spot statistical placebo in the gatekeeper, a `tao_subnet_features` table + repository, and the taostats v1 collector (inert until a key is set). Stores USD/TAO + TAO/alpha; returns denominated in USD. Research-only, never traded. Blocked on the taostats API key + granularity. (Deployed + live, dormant.)
- **Markdown in the research agent-log feed** — the live think-aloud feed rendered raw markdown (literal `**bold**`, unformatted lists); added a small XSS-safe, streaming-safe markdown renderer so the agent's reasoning reads as formatted prose. (Deployed + live.)
- **Live-streaming rich research feed** — the research session now shows the agent *thinking* in real time: the previously-silent multi-minute proposer call streams its reasoning (Bedrock `converse_stream`, think-aloud prose then JSON — same LLM-call count/cost), and each hypothesis renders as a progressively-filled card (intuition → mechanism → real spec/Python → challenger critique → gatekeeper verdict + stats grid). Falls back to non-streaming if the worker lacks `InvokeModelWithResponseStream`. Gatekeeper/live-gate/exec untouched; verdict stats go to the feed only, never back to the generator (anti-leak). (Deployed + live, CloudFront invalidated.)
- **Cross-contract strategy support (research + eval, deploy-gated)** — a spec can declare a `cross` block (multiple `involved_markets` + a merged `stream_key`); partitions build a merged purged walk-forward dataset across markets and the gatekeeper judges the holdout over it. Cross specs are refused for LIVE at the deploy gate (adds to, never weakens, the existing live guards) — research/eval only at the exchange. (Deployed + live.)
- **Bedrock read-timeout fix** — large hypothesis-generation responses exceeded botocore's default 60s read timeout and failed whole research runs ("Read timeout on endpoint"); raised to 600s read / 15s connect and made Read/Connect timeouts retry with backoff like the throttle path. Research runs no longer die mid-generation. (Deployed + live.)
- **NBA / Kalshi sports markets (research-only)** — KXNBAGAME added as a sports market family (outcome-settled, no strike/spot); the collector, spec, and backtest are sports-aware, and the candlestick fetch is chunked to ≤4900/request (an NBA game listed for days at 1-min candles blew past Kalshi's 5000 cap). Full intraday history ingesting. (Deployed + live.)
- **Per-bucket cash + funding** — Live shows your real Kalshi balance + a deposit link; Demo has an app-controlled balance with a "Reload to $X" button (real sandbox fills, money we set — never touches the real demo balance); Paper has Add/Withdraw/Reset. Dashboard buckets show real balances; Funds page grouped Live → Demo → Paper → History. (Deployed + live.)
- **Risk-management force-sell + portfolio caps** — auto-closes a deployment's positions when it draws down past a limit (25% default, per-user tunable, `0` disables), reusing the exact tested exit path; per-user open-notional / open-position caps on new entries. Also fixed a real-money bug: a partial exit fill was silently dropped (contracts sold but the DB kept the position open) — partial fills are now booked and the remainder retried. (Deployed + live.)
- **Research-session live feed + pause/resume + run-stability** — a Claude-Code-style streaming agent log (fixed the swallowed/truncated entries), interrupt-and-continue (Pause/Resume, not just Cancel), and — the big one — research runs now reconnect on a stale DB connection instead of dying, and you're no longer billed for an infra failure. So runs actually complete and the gatekeeper can classify. (Deployed + live.)
- **Realized demo-book line + slippage fixed, chart anchored** — the "Kalshi dev (real)" line + per-trade slippage were empty because the replay priced the first-seen OOS contracts (disjoint from what the strategy trades) instead of the strategy's traded contracts; fixed, so both populate. The real line is now anchored to the simulated line at its start, so it reads as a real-vs-sim divergence instead of a floating stub. (Deployed + live.)
- **Dashboard table cleanup** — removed the Realized mini-sparkline; long strategy names wrap so the Deployed table fits instead of clipping. (Deployed + live.)
- **Engine resilience fix** — one deployment's error (a stale-DB-connection blip, a bad key) in a trading tick no longer tears down the whole engine loop for everyone; a `decide()` exception now skips that deployment's tick and retries next slot. (Root-caused from a prod incident where an RDS outage thrash-restarted the engine.) Also: a live deployment paused for a genuinely-missing key now says "add your live Kalshi key" instead of the false "live trading is not enabled." (Deployed + live `cdd69d5`.)
- **Community feed cleanup** — removed the post hover-highlight and the redundant top-right react/reply toolbar; actions stay bottom-left (reaction pills, add-emoji, reply/N-replies, Edit on own posts); the instant reactor tooltip is kept. (Deployed + live `cdd69d5`.)
- **Sandbox confiner installed on the worker** — bubblewrap 0.10.0 installed and verified functional on the box, so arbitrary-quant **code strategies** now run in the kernel sandbox instead of being inert (fail-closed by design). (Done on prod.)
### 2026-10-16
- **Order-book depth + microstructure exposed to research, with dataset provenance** — the 9 collected microstructure features (order-book imbalance, bid/ask sizes, recent trade flow, quote-change intensity, short-horizon mid returns) that lived in `model_features_1m` but were hidden are now in the `FEATURES` namespace a spec can filter on (leak-safe as-of the decision minute; degrades gracefully on NULLs). Every hypothesis also records its `data_provenance` (features + data sources used) in the experiment ledger — the audit behind "use any dataset, as long as we track it." (Deployed + live.)
- **"Dig deeper" on a passed strategy (+ fixed the "stuck follow-up" bug)** — a passed strategy is no longer a dead end: `POST /api/strategies/{id}/dig-deeper` and a co-pilot `research` action branch a NEW pre-registered research line off it (seeds its thesis/spec, keeps the mechanism, refines/stress-tests/extends) through the normal gatekeeper — no bypass; branches link to the parent via `parent_id`. This also root-caused the beta tester's "follow-up got stuck": it was never a hang — the co-pilot simply had no way to continue research from a passed strategy, so it dead-ended; now it can. (Deployed + live.)
- **Arbitrary-quant code strategies (research-only, kernel-sandboxed)** — a strategy can be agent-authored Python/numpy (any math/ML/quant framework) exposing one `signals(window)` contract, judged IDENTICALLY to a DSL spec by the gatekeeper (pre-registration hashes the code as the rule). It runs in a DEFAULT-DENY kernel sandbox (`sandbox-exec`/`bwrap`/`firejail`: no network, no credential reads, no filesystem outside scratch, CPU/mem/time caps) — a security review found and closed a real in-interpreter escape (numpy-capable code re-exposing `os` via `random._os`), so the boundary is the OS kernel, not Python. Research-only, never in the live/paper engine; inert until a confiner is installed on the Linux worker (fail-closed). (Deployed + live.)
- **Slack-grade Community feed + instant reactor tooltip** — the reactor-names tooltip is now instant: dropped the native `title=""` attribute (which carries a ~1s browser delay) for a pure-CSS `:hover`/`:focus` popover drawn from already-loaded data (reactor names + `@handles` now in the `reactions_for` payload via one grouped query, no per-hover fetch). The feed was rebuilt into a Slack message model: avatar-gutter grid, 5-minute author grouping, an instant hover toolbar (react/reply/edit), always-on reaction pills with an inline add, a "N replies" thread affordance, and a pinned composer unified across both themes. Kursbuch tokens preserved; shared code byte-identical across themes. (Deployed + live `7c738c9`.)
- **Per-user demo-env (sandbox) trading + 3-bucket dashboard** — authenticated Kalshi DEMO execution that is host-isolated and can never reach the real exchange: a per-user dev key entered in-app and encrypted exactly like the live key (`app_kalshi_dev_keys`), a `demo` deployment mode routing orders through `engine.decide`'s shared kernel path to `kalshi_dev_exec.demo_kernel_factory` (paper/live untouched; no dev key → the deployment pauses, never trades), and a "Deploy on demo (sandbox)" button. The dashboard now splits money into **real / demo / paper** buckets, each with account value, realized P&L (today + all-time) and open positions. Also closed a gap: the manual `create_deployment` live path now also requires the gatekeeper's `DEPLOYMENT_CANDIDATE` check, matching the autopilot path. Live gate strengthened, never weakened. (Deployed + live `afdc31c`.)
- **Detailed Dev Logs** — each shipped entry now carries a full detail body (what changed, which components, the methodology) instead of a vague title: `devlog.py` SHIPPED is `(date, title, detail)`, the `devlog-sync` skill stops truncating the mvp.md Done bullets, and the Dev Logs page renders title + detail via the XSS-safe `mdLite` in the Kursbuch timetable style, both themes byte-identical. (Deployed + live `afdc31c`.)
- **Cross-contract research + cross-day gatekeeper** (research/eval only, NOT live) — specs gained an optional `cross` block (relative-value pairs: cross-sectional BTC-vs-ETH, cross-strike, calendar); `backtest.simulate_pairs` + `merge_datasets` simulate a 2-leg buy-YES-cheap/buy-NO-dear pair holding both legs to settlement, reusing the real Kalshi fee/sizing math; a cross spec spends from ONE shared FDR stream (`btc_daily+eth_daily`) while single markets keep their own; and a new cross-day generalization gate (purged walk-forward folds + per-day concentration) makes STAT_SUPPORTED strictly harder — a one-day fluke is demoted to INCONCLUSIVE. Per-fold breakdown recorded on the result row + rendered in the folds strip. Single-contract strategies unchanged. (Deployed + live.)
- **Statistically-rigorous research pipeline** (true "quant research") — splits generation from judgment: immutable experiment ledger + pre-registration, a Statistical Gatekeeper separate from the generator (BH/LORD++ online-FDR, Deflated/Probabilistic Sharpe, stationary-bootstrap p-values), research/validation/locked-holdout split + purged walk-forward/embargo, a 9-phase proposer + challenger, and the strategy detail page rebuilt as a research paper (thesis/mechanism/pre-registered test/results/holdout + 5 charts). Deploy gate gained an additive, fail-closed DEPLOYMENT_CANDIDATE requirement; live gate unchanged except stricter. (Deployed + live `b4d5f2e`.)
- **Real demo-book slippage accounting** — replays each strategy against the Kalshi demo book (read-only, no orders), measures the per-trade fill gap vs the simulated book as signed entry/exit cents, shows it on the strategy page, and defaults the what-if slippage knob to the measured value. (Deployed + live `a0d05a2`.)
- Live autopilot — full research→paper→live→risk loop, **gated and off by default** behind the typed-LIVE confirm + every existing safety gate (paper-proven, YES-only, per-user Kalshi key, daily-loss kill switch).
- Autopilot consolidated into the floating window; the Deploy page is now board-only (Agent panel removed).
- Dashboard pause/resume/stop for deployments (same code path as Deploy).
- Theme switcher — pick the Tau or Meridian frontend in Settings; Meridian brought to feature parity.
- Quant toolkit `app/quant.py` (BS-digital fair value, vol, Kalshi fees, edge, Kelly, portfolio metrics) — built + tested, not yet wired into the agent.

### 2026-10-16 — local integration
- Alpaca stock/ETF market data connected to research/copilot calls, with on-demand symbols, historical training cutoffs, feed provenance and stale-data handling. 258 Python tests passed, 7 opt-in MySQL tests skipped. Real IEX snapshot/history reads were verified locally; production activation remains above. [Implementation](kalshi_trade_infra/PLAN.md).

### 2026-10-15
- **@-mentions in the community (Slack-style).** Every user gets a unique `@handle` (backfilled from their email; assigned on signup), shown as `Name @handle` on posts/comments. Typing `@` in the composer or a reply opens a candidate list (by handle or name, arrow/enter to pick); `@handle` renders highlighted in bodies. The mentioned person gets an in-app notification + an email (emails wait on SES prod, like the rest). New: `app_users.username`, `/api/users/mention`, `MENTION_RE`/`assign_username`. Verified on the real DB (all 10 users backfilled, unique, dedup works).
- **Dev Logs tab** (public changelog: shipped list with dates + "shipping next"), **Credits & Usage receipt** download (CSV of the full ledger), **reaction-hover reactor names** ("and N others"), **comment lazy-load** (latest 10, "Load N earlier"), **full-width explore chart**, default model → **Claude Opus 4.5**, and **Kalshi-dev 2nd equity line enabled** (demo API is public). Fixed two bugs found in testing: `reactions_for` used a non-existent `r.id` column (broke the whole community feed) and the comment reply form read the search box instead of the reply box.
- **DeepSeek R1 model support.** `llm._bedrock` now falls back to the `reasoningContent` block when a model emits no plain text (reasoning models put the answer there), so `extract_json` still works. Added DeepSeek R1 (`us.deepseek.r1-v1:0`) to the catalog at the verified Bedrock price ($1.35/M in, $5.40/M out). Verified live on the box: a real call returns usable JSON. Accessible via the US inference profile (not access-gated, unlike Claude 5.5/GPT/Grok).
- **Comment search** on long threads — once a post has >6 replies, a search box filters them live (client-side over the loaded set, with an "N of M" count). ponytail: server-side search if a thread ever tops the 100-comment fetch cap.
- **Email-all on new community posts** (code shipped; delivery gated on SES prod — see Blocked) — background-thread dispatch to opted-in users on each new post, per-recipient 4h cooldown so a burst can't flood, one-click HMAC-signed **unsubscribe** link (`/unsubscribe`) + `email_opt_out` column. The in-app notification bell already covers community activity without email.
- **Community composer pinned to the bottom** (chat-style): the feed + filter chips scroll above a sticky composer bar with its own elevation; textarea auto-grows from one line. Fixed a token bug where `var(--surface)` (undefined at `:root`) made the bar transparent — now uses `--stock-raised` (opaque).
- **[ops] Found + fixed a deploy-targeting bug:** all deploys this session had been going to `i-0bd0683cc7e86243d` (tau-collector), but the CloudFront origin / real web box is `i-077d6f7873e7836ba` (kalshi-collector). Nothing reached users until caught. Also: must invalidate CloudFront `/*` (the HTML carries the `?v=` asset hash), not just the asset paths. Recorded in memory. Redeployed everything to the correct box; verified live.
- **Strategy sharing + notifications.** Share any strategy with a friend by the email they sign in with (strategy Share panel → `POST /api/strategies/:id/share`). It's **copied** into their inventory (so it's theirs to deploy like any other, and can't be revoked); idempotent — re-sharing the same one won't duplicate. A **notification bell** sits by the profile (top-right) with an unread dot + dropdown; it fires on a share to you and on a comment on your post. Shared strategies carry a **"Shared by X"** flag in the list and on the detail page. New: `app_notifications` table, `shared_from_user_id`/`shared_src_id` on `app_strategies`. Verified end-to-end on the real DB (copy origin, idempotent dedup, unread count).
- **Live unrealized (mark-to-market) P&L.** The engine stamps each open position's current YES bid (`mark_price`/`mark_ts` on `app_positions`) every decision tick — reusing the book it already fetches, so zero extra API calls. The web shows unrealized P&L in the strategy Holdings panel, the Deploy-board Open positions table, and the dashboard open-position cards (value by side; NO estimated as 1−bid, labeled "est."). Updates at decision cadence; "—" until the first mark. Verified end-to-end on the real DB.
- **Strategies list: Deployed/Live badge + search + Deployed-only filter.** Each row now shows a "Deployed" (or red "Live") pill when it has an active deployment (server-side `active_deps`/`live_deps` via correlated subqueries). Added a search box (`q`, matches title/thesis) and a "Deployed" toggle chip; both narrow the list AND the headline counts server-side (shared `_strategy_filter_sql`). Cross-page sort-by-P&L deferred (P&L lives in result JSON).
- **[ops] Deploys must ship the whole `app/` package.** Hit a prod outage: the box was missing `kalshi_dev/code_map/models_catalog/sandbox` because earlier deploys were file-by-file and never shipped them, so deploying a newer `server.py` (which imports `kalshi_dev`) crash-looped `recursive-web`. Fixed by deploying the full `app/` tar; box is now aligned to HEAD. Always tar `app` (not individual files).
- **Dashboard Deployed table no longer scrolls sideways** — `width:100%` on the strategy/deployment tables so long titles wrap instead of widening past the viewport; insanely long names break with `overflow-wrap`. Removed the empty/unhelpful Daily P&L bar chart (and its dead CSS).
- **Multi-select deploy** on the Strategies page — checkbox column on deployable (passed) rows + select-all + a sticky "Deploy N on paper" bar (loops the existing single-deploy endpoint; live stays per-strategy behind the typed-LIVE gate). Selection is per page.
- **Stop-then-delete made intuitive** — the Remove panel on a strategy now has an inline "Stop deployment(s) #N" button (previously you had to leave for the Deploy board, find the row, stop it, come back). Delete stays blocked with a clear hint until the deployment is stopped.
- **Tau-RSI dreaming now improves real research, not the recording.** Root cause of 0 policies evolving: the objective rewarded overfitting the recorded node order (stop-early only wins when that one recording's winner was early; on real trees user 7's winner is at idx 462/500), with no multiple-testing penalty, and the prompt pointed the LLM at the dead lever (batch width) instead of the real one (finalist selection). Fixes: score on `replay_generalization` (mean V over 32 shuffled orderings), `V = quality − 0.1·gen − 0.1·finalists` (drop parallelism bonus, add multiple-testing penalty), prompt rewritten around selection, guard that an adopted policy must actually explore+gate. Real Sonnet-4.5: user 1 goes from gating OOS losers (mean V −71) to catching the real +$282 winner (+232, order-invariant); overfit stop-early now rejected.
- **Markdown in community posts/comments** — safe `mdLite` subset (bold/italic/`code`/links/line-breaks), HTML-escaped first and http(s)-only links so there's no XSS surface. Inline-code + link styling added.
- **Meme emoji reactions** (goat/ape/whale/diamond/clown/skull/salute/moon) + spacing between the composer and the feed filter.
- Web-box engine **watchdog** for `recursive-engine` (added a per-tick heartbeat `recursive_engine_last_tick` + `tau-watchdog.timer` on the web box; restarts a silently-stalled engine — critical with live orders on).
- **Live/real trading ENABLED for all users** (`APP_LIVE_TRADING_ENABLED=1`), with **market-order-like entries** (cross the touch, IOC, 10c slippage tolerance; `KALSHI_*` env-tunable). Safeguards: YES-only, per-user Kalshi key, typed-LIVE confirm, risk caps + loss guard. Reversible via the flag.
- **Tau-RSI (P1–P4) shipped + live** (Dream-RSI adapted): pure-fn `ExplorationPolicy`+`DefaultPolicy`; replay simulator + objective `V=quality−β₁·gen+β₂·parallelism`; sandbox for LLM-authored policy code; dreaming loop (per-user self-evolving policy, monotonic). `app/{exploration,replay,sandbox,dreaming}.py` + `app_policies`; dreaming attempts now logged. 195+ tests.
- **Open-sourced the repo** (BSL-1.1 → Apache-2.0 at the change date; NOTICE w/ Dream-RSI attribution; public README + `.env.example`); branch protection on `main`; auto-push on commit. Repositioned as **RSI for Trading** (venue-agnostic).
- Strategy detail: live **Holdings** panel + Kalshi market link; **delete a strategy** (blocked while deployed).
- **Invite-only sign-in gate** (waitlist approval) + admin Approve/Remove; waitlist excludes account-holders.
- Passed strategies always show under their run; clearer 'Hypotheses tested' copy.
- Deploy cap 10→100; research budget cap 50→1000; default $5/$100 sim book.
- Community "My posts" filter; Billing profile dropdown; System DB-node + market-chip fixes; landing-demo no-reflow.
- Heartbeat watchdog (silent-stall recovery) + forward_collector per-tick heartbeat (stops false-STALE flapping); Writer Palmyra X5 model added.


## How do we charge customers? (v0.2)
- **[Done]** OpenRouter-style credits: $100 free, per-token billing, 5.5% top-up fee, Stripe.
    - **[Done]** Flipped to Stripe **live** keys (in Parameter Store → `.env.app`); real cards now save/charge. Test-mode `pmc_` dropped (code falls back to card). NOTE: webhook secret still test — set live `whsec_` before relying on top-up webhooks.
    - **[Done]** Save-card works: Payment Element collects only ZIP (correct for AVS), country `US` injected at `confirmSetup` — both the gate modal and the Billing page.


## THOUGHTS
### Must-have Features
- **[Done]** Our simulations do not consider the fact that Kalshi has a dev environment for testing
    - Strategy curve shows 2 lines — our standard sim + Kalshi-dev out-of-sample execution
      (code shipped; set `KALSHI_DEV_API_BASE` on the box to draw the real-dev line).
- **[Done]** Let users choose the model (Claude / Nova / Llama) their research runs on, billed at each model's exact price.
- **[Done]** Adapted OpenRouter's revenue model (credits + per-token billing + top-up fee).
- No major data vendor for prediction markets yet. We can be the databento for prediction market

### Interesting Features
- Make agent pipeline that allows the user to collect data itself
    - Maybe once collected, it can be shared across all users
    - Maybe we can charge also by storage cost? (i.e. how many data they use/subscribe to)
- Social/Interactive Elements
    - **[Done]** Community tab: share ideas/strategies/PnL, like, comment, photos, edit own posts.
    - **[Done]** Email to a post's author when someone replies (SES sandbox: verified addresses only).
    - TODO: emoji reactions (Slack/Mattermost style); friends' holdings; sell alpha with a margin.
    - Allow people to start a "Hedge Fund" on the platform where other people can put money in
- Agent generated UI for assited manual trading
    - UI is also a big part of trading business!
- Notification when RSI found something new.
- A "simulation lab" for agent-driven trading strategies. Adding super detailed features
for trading firms/teams that only focus on agent-driven strategies.
    - Specify number of swarms + number of agents in swarm
    - Specify direction/asset class
    - Specify how to cross contaminate
    - Specify competitions/rl rewards, etc.
    - Specify data
- Integrate with a person's paycheck.
    - A percentage of the paycheck will contribute to investment on this platform
        - Lean towards the "AI-native Hedge Fund" narrative. This sounds like we will
        want to manage the money for our customers
- A credit/debit card for customers to easily use their money deposited on our platform.
    - Automatically sell some positions to cover their expenses.
- Centralized dashboard to control what features we should enable, and to what user
    - **[Done]** Admin tab (operator only): grant credits, see users/waitlist; masthead admin-mode toggle.

### Open Souce?
- Software is cheap. We could probably open source our code. Our moats:
    - We build data collection automation pipeline. And we enable users who need
those data to collect and help us grow our datasets.
    - Our underlying execution service is not open sourced. Any edge we can win here?
    - We can post-train models using our in-house data for:
        - A jev like model that replaces traditional ML and only output "buy"/"sell"...?
            - TBH I don't even know what this means
    - 

## Traction
- Sell product EARLY. How to ask friends/strangers to try out product
whether making them willing to pay?
    - Maybe not subscription. Also subscription doesn't make sense because
    this won't generate a lot of revenue in the long run.
        - Option A: charge them when they deploy a strategy after backtesting
            - A small percentage cut of their profit
            - Or a fixed price "deployment to production" price
        - Option B: charge them when they need additional data
        - Option C: charge them when they need credits to fund their agents
            - e.g. a margin on top of their API credits
            - a quick thought but might be over-doing:
                - They plug in their exising API key, though we can't just tell OpenAI
                to give us some margins. What we can do, is that when user uses the API,
                we add a little embedding that routes someone else's request, so that
                we are cashing out the user's credit by using the user's credit and fulfills
                someone else's totally irrelevant requests.
                    - Bad, for rate limiting reasons, and bloating a user's bill
        - Option D: charge them for premium execution service
            - This can also let us make our product open source.

## Frictions found along the way.
- API keys are the bottleneck, not coding. A frictionless api-key-dependent development solution?
- **[Done]** Visualization layer: admin System tab — live signal-flow map of the codebase.
- Codes become harder and harder to read with fast development. (Visualization layer shipped, above.)
- User testing. Agent as a simulated user to test front end UIs.
- computer agent to help me do things that previously I needed to manually do.
- New UI/interface, but agent has old knowledge -- there should be a product that
ensure agent-friendly user interface so that knowledge doesn't drift