# MVP for launch (v0.1)

## The idea: RSI for Trading
A self-improving alpha discovery pipeline, from ideation, to similation, and finally real execution.

[Optional] Side idea: Agent generated UI for trading assistance. 

## User Story
Jonathan login to the website.

Jonathan wants to trade on bitcoin. Jonathan tells agent his intend to trade on bitcoin.
Agent will be dispatched and start analyzing available data, including market sentiments,
price movements, historical data, alternative data, etc.

Agent will then propose hypotheses, which itself will then validate in a backtesting stage.
Only strategies that pass the backtesting requirements will be available for deployment.

Jonathan will review agent's strategies and choose which to deploy.

Jonathan will continuously monitor the trading dashboards to see how
his strategies perform in real-time and step in to turn on or off existing
strategies. Agent will also continous assess the market and dynamically adjust
strategies and their model parameters.

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
Single source of truth for open work (merged in from the old `requested_queue.md`, 2026-10-15).
Remove a line once shipped; `[blocked]` = needs a user/AWS action first.

### Build (queued)
- All-markets collector + cross-contract — BUILDING. Phase 1 catalog shipped. Ingestion split onto a dedicated collector box (`i-0bd0683cc7e86243d`) + S3 data-lake. Next: per-minute S3/Parquet snapshots (Phase 2), backtest-over-any-series (3), cross-contract (4).
- Real/live deploy is broken — can't trade real money yet. Fix the live pipeline; **enabling the global live gate places real orders and needs explicit, separate owner sign-off.**
- Remove/undeploy a deployed strategy, and delete a strategy from inventory (no delete today).
- Track unrealized P&L for deployed strategies (paper/real).
- Strategy detail: show current open positions / holdings for a deployed strategy (/impeccable).
- Hyperlink each strategy to the actual Kalshi market it trades.
- Markets still show only a few — widen the live market universe.
- "Tries to find it": clarify what research actually does and verify it genuinely iterates.
- Passed strategies don't show under their research session.
- Community strategy-share snapshot: header counts (Passed/Void/Rejected) disagree with the listed rows (frozen/capped at share time) — recompute from real COUNT.
- Select-all / multi-select for deployment.
- Email all users on any new community update (needs unsubscribe + rate discipline).
- Web-box engine watchdog: extend `tau-watchdog` to `recursive-engine` (confirm it heartbeats when idle first).
- Kalshi dev-env 2nd curve needs `KALSHI_DEV_API_BASE` set on the box (one line until then).
- **Tau-RSI (self-evolving research, Dream-RSI-faithful)** — DESIGN in PLAN.md. Decisions: per-user private memory; FULL Dream-RSI (replay simulator + dreaming); evolvable **executable policy code** made safe by keeping the policy a pure decision function (no I/O) run in a sandbox. Phases: **P1 foundation SHIPPED** (app/exploration.py: pure-fn ExplorationPolicy + DefaultPolicy = today's behavior unchanged; app_strategies.parent_id discovery-tree column; 177 tests green) → **P2 NEXT** replay simulator + objective → P3 sandbox → P4 dreaming loop.
- **Protect `main` from pushes** (owner-only) + **open-source the repo** (BLOCKED on a secret/infra-leak audit before going public — never make public un-audited).

### Blocked on you / AWS
- Model selection: Claude 5.5 / OpenAI GPT-6.x / Grok are AWS-access-gated (agreements accepted + availability AUTHORIZED, but invoke denies even from full-admin — a Bedrock account grant AWS hasn't given). Request in Bedrock console → Model access (us-east-1) or AWS Sales. Prices locked: Sonnet5.5 $2/$10, Opus5.5 $4/$20, Haiku5.5 $0.1/$0.5, GPT-6.1 Sol $2.2/$10, GPT-6 Sol $2/$10, GPT-5.6 Sol $8.8/$33.
- DeepSeek R1 returns reasoning-only output via Converse — needs reasoningContent handling before it's safe to offer.

### Deferred to v0.3
- Agent internet access / web search (Google/Tavily/Brave).
- Polymarket as a 2nd venue: data + API + real & simulation trading.

### Shipped 2026-10-15
- Deploy cap 10→100; finite research-budget cap 50→1000.
- Default $5 stake / $100 capital sim book (agent may override for dynamic sizing).
- Community "My posts" filter.
- Heartbeat watchdog (silent-stall recovery) + forward_collector per-tick heartbeat (stops false-STALE flapping).
- Writer Palmyra X5 model added; Billing profile dropdown; System DB-node + market-chip fixes; landing-demo no-reflow.

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