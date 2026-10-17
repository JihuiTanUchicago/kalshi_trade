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
`[delayed]` = owner chose to hold; `[blocked: …]` = needs a user/AWS action first; `[v0.3]` = next version.
These are NOT done. Completed items move to **## Done** below.
- claude code style animation demonstration in a research session. allow user to interrupt and then continue. do not ship minimum, this should be production grade, commercially good.
- **Per-bucket cash + funding** (live/demo/paper) — the 3-bucket dashboard has no funding story. Paper: in-app add/reset cash (app-minted). Demo: real sandbox FILLS (real slippage/fill prices) but money is app-controlled — a "Reload demo to $X" button, we never touch the real Kalshi demo balance. Live: show the real Kalshi balance (via live key) + a deposit link (can't mint real cash). Build after the expansion-merge integration pass (needs merged demo-mode base).
- `[blocked: worker environment]` Activate Alpaca stock/ETF agent data after secure worker configuration and entitlement checks, with a production canary before customer rollout. Source integration is complete for review; no production deployment yet. [Setup](kalshi_trade_infra/app/README.md#alpaca-stocketf-data-for-agents--october-16-2026).

- `[delayed]` All-markets collector + cross-contract. Phase 1 catalog shipped; ingestion split onto a dedicated collector box + S3 data-lake. Next: per-minute S3/Parquet snapshots (Phase 2). Backtest-over-any-series (3) + cross-contract research/eval (4) now built (see Done); cross-contract **live execution** still deferred.
- `[v0.3]` Wire the generator (agent.py) to PROPOSE cross-contract pairs + build merged validation/holdout partitions, then enable cross-contract LIVE execution (engine.py/live gate) — research + evaluation are in place; this is the remaining step.
- `[delayed]` Widen the live market universe — surface more of the already-collected Kalshi series in the UI (smaller than the full all-markets build).
- `[blocked: SES]` Email-all community digest — **code is live** (opt-out + HMAC unsubscribe + 4h per-recipient cooldown; background-thread dispatch on each new post), but SES is in sandbox so it only reaches *verified* addresses. Unblock: SES console → Account dashboard → Request production access (zero code change after).
- `[blocked: AWS]` Premium model access — Claude 5.5 / OpenAI GPT-6.x / Grok are AWS account-gated (agreements accepted, but invoke denies even from full-admin). Unblock: Bedrock console → Model access (us-east-1), or AWS Sales. Prices locked: Sonnet5.5 $2/$10, Opus5.5 $4/$20, Haiku5.5 $0.1/$0.5, GPT-6.1 Sol $2.2/$10, GPT-6 Sol $2/$10, GPT-5.6 Sol $8.8/$33.
- Kalshi-dev 2nd equity line — NOT blocked: uses the *public* demo candlesticks (no credentials), base URL now defaulted in code; draws once the slippage/dev-curve work deploys (verify after deploy). Covered by the slippage Done entry below.
- `[v0.3]` Agent internet access / web search (Google/Tavily/Brave).
- `[v0.3]` Polymarket as a 2nd venue: data + API + real & simulation trading.
- `[in progress]` Risk-management force-sell layer on drawdown + portfolio caps (lost when a prior background agent exited; needs rebuild).
- `[in review]` Arbitrary-quant **code strategies** — a strategy may be agent-authored Python/numpy (its own math/ML/quant framework) exposing one `signals(window)` contract. It runs in a KERNEL-isolated child (`app/sandbox.py` Tier-2): sandbox-exec on macOS / bwrap|firejail on Linux deny network + credential reads + writes outside scratch, and the sandbox is DEFAULT-DENY (refuses to run if no OS confiner is present — in-interpreter Python sandboxing of numpy-capable code is not a security boundary, confirmed by a demonstrated escape that this fix closes). Python-layer restrictions (scrubbed env, restricted builtins, import gate, AST ban, rlimits) remain as defense-in-depth. The backtester feeds it the SAME fee/sizing/settlement and the Statistical Gatekeeper judges it IDENTICALLY to a DSL spec (pre-registration hashes the code as the rule). Research-only — blocked from the live/paper engine. **Prod TODO before enabling: confirm bwrap/firejail is installed on the worker box** (else code strategies are inert by design). In a review worktree, not yet deployed.
- `[review]` "Dig deeper" on a passed strategy — a passed strategy is no longer a dead end. Backend seams in worktree (not committed): `POST /api/strategies/{id}/dig-deeper` + co-pilot `research` action both branch a NEW pre-registered research line off the passed strategy (seeds its thesis+spec, keeps the mechanism, refines/stress-tests/extends), through the normal gatekeeper (no bypass); branched strategies link to the parent via `parent_id` (first real use of the discovery-tree column). Also closes the "follow-up got stuck" report: the chat follow-up previously dead-ended because the co-pilot had no way to continue research. **UI still needed:** a "Dig deeper" button on the passed-strategy page → `POST /api/strategies/{id}/dig-deeper` then `go('/research/'+id)` (app.js + app.meridian.js).
- `[review]` NO-side (and side="either") live/demo execution — execution now places the correct leg: a NO order is sent as its YES complement (buy NO = sell-YES ask at 1−no_price), priced from the NO side of the book, filled/settled in NO terms; the YES-only guards in `agent.deploy_live` + `server.create_deployment` are relaxed (every other live gate kept, in order). Implemented in a worktree, tests green; **not deployed, live still off by default** — pending owner review + `/security-review`.

### From beta-tester feedback (2026-10-16) — user-first, deliver these greatly
- `[bug]` Research follow-up on a previously **passed** strategy gets **stuck** — reproduce + fix (a tester hit this). High priority; it blocks the "iterate on a winner" flow below.
- **Dig deeper on a passed strategy** — let a user continue research *from* a passed strategy: branch/refine it, stress-test, extend the thesis, run more validation — instead of it being a dead end.
- **Cross-day generalization in the gates** — a tester asked whether a passed strategy is a one-day-contract fluke or a pattern that holds across days. Evaluate each strategy across multiple days/contracts and factor "does it generalize across days" into the gatekeeper, not just a single window.
- **Order-book depth to research** — surface the collected order-book DEPTH/microstructure (not just minute-level price) to the agent + specs (we store `orderbook_imbalance`/sizes/trade-flow but don't expose them). Overlaps "any dataset" expansion.
- **Contract pairs/groups & hedging** — same-price-different-days and same-day-different-strike pairs/hedges; cross-sectional relative-value. Part of the cross-contract build.
- **NBA / Kalshi sports markets** — let Tau research + trade Kalshi sports contracts (NBA to start, season kicking off); support comparing quantitative vs fundamental bets. New market family beyond BTC.
- **Bittensor (TAO) subnet tokens as a new venue** — data from taostats.io; currently long-only (short coming), likely illiquid/event-driven; test whether Tau can reason about subnet tokenomics. New asset class.
- `[blocked: AWS]` **Onboard Opus 5.5** (`claude-opus-5-5`) + surface model comparison — tester wants it for NBA season. Blocked on AWS Bedrock model access like the other premium models.

## Done
### 2026-10-16
- **Slack-grade Community feed + instant reactor tooltip** — the reactor-names tooltip is now instant: dropped the native `title=""` attribute (which carries a ~1s browser delay) for a pure-CSS `:hover`/`:focus` popover drawn from already-loaded data (reactor names + `@handles` now in the `reactions_for` payload via one grouped query, no per-hover fetch). The feed was rebuilt into a Slack message model: avatar-gutter grid, 5-minute author grouping, an instant hover toolbar (react/reply/edit), always-on reaction pills with an inline add, a "N replies" thread affordance, and a pinned composer unified across both themes. Kursbuch tokens preserved; shared code byte-identical across themes. (Deployed + live `7c738c9`.)
- **Per-user demo-env (sandbox) trading + 3-bucket dashboard** — authenticated Kalshi DEMO execution that is host-isolated and can never reach the real exchange: a per-user dev key entered in-app and encrypted exactly like the live key (`app_kalshi_dev_keys`), a `demo` deployment mode routing orders through `engine.decide`'s shared kernel path to `kalshi_dev_exec.demo_kernel_factory` (paper/live untouched; no dev key → the deployment pauses, never trades), and a "Deploy on demo (sandbox)" button. The dashboard now splits money into **real / demo / paper** buckets, each with account value, realized P&L (today + all-time) and open positions. Also closed a gap: the manual `create_deployment` live path now also requires the gatekeeper's `DEPLOYMENT_CANDIDATE` check, matching the autopilot path. Live gate strengthened, never weakened. (Deployed + live `afdc31c`.)
- **Detailed Dev Logs** — each shipped entry now carries a full detail body (what changed, which components, the methodology) instead of a vague title: `devlog.py` SHIPPED is `(date, title, detail)`, the `devlog-sync` skill stops truncating the mvp.md Done bullets, and the Dev Logs page renders title + detail via the XSS-safe `mdLite` in the Kursbuch timetable style, both themes byte-identical. (Deployed + live `afdc31c`.)
- **Cross-contract research + cross-day gatekeeper** (research/eval only, NOT live) — specs gained an optional `cross` block (relative-value pairs: cross-sectional BTC-vs-ETH, cross-strike, calendar); `backtest.simulate_pairs` + `merge_datasets` simulate a 2-leg buy-YES-cheap/buy-NO-dear pair holding both legs to settlement, reusing the real Kalshi fee/sizing math; a cross spec spends from ONE shared FDR stream (`btc_daily+eth_daily`) while single markets keep their own; and a new cross-day generalization gate (purged walk-forward folds + per-day concentration) makes STAT_SUPPORTED strictly harder — a one-day fluke is demoted to INCONCLUSIVE. Per-fold breakdown recorded on the result row + rendered in the folds strip. Single-contract strategies unchanged. (Worktree, pending review.)
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